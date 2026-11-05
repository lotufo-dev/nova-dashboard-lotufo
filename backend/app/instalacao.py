"""Instalacao assinada (issue #417): fora do servidor oficial a dashboard sobe em modo copia.

O dono gera no Mac um par Ed25519 (`python -m app.cli instalacao gerar-chave`) e assina um `instalacao.json` com o
nome da maquina, um identificador aleatorio e a data (`python -m app.cli instalacao assinar`). A chave privada nunca
vai ao servidor nem ao repositorio; a publica fica embutida abaixo, e trocar de chave e' uma PR.

Na subida (`create_app`) o servidor le `<raiz>/segredos/instalacao.json` -- a raiz e' a pasta acima de `dados`, onde
mora o banco (`DASH_DB_PATH`); `DASH_INSTALACAO_ARQUIVO` troca o caminho -- e confere a assinatura e o nome da
maquina (o `COMPUTERNAME`, lido do Windows). Arquivo ausente, assinatura que nao confere ou outra maquina: modo copia. Login e leitura
continuam; o envio de e-mail e a sincronizacao com o RM ficam desligados e toda tela mostra a faixa vermelha. O
objetivo e' marcar a copia, nao derruba-la: o /api/health continua 200 (o watchdog nao reinicia em laco).

`DASH_DEV=1` (e os testes, pelo conftest) sobem como `dev`: nada desligado, arquivo nao exigido. Quem edita o
ambiente ou o codigo passa por cima disto; a trava e' para a copia da pasta de producao que sobe sem ninguem notar.
"""
import base64
import binascii
import datetime
import json
import logging
import os
import platform
import secrets
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

log = logging.getLogger("app.instalacao")

# Chave publica do dono (comentario dele na issue #417, 05/11/2026). A privada correspondente fica so' com ele.
CHAVE_PUBLICA = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEABKEKf2uSKWVw3pPwMkSnd+viIu/NNudBFSdexV95tjk=
-----END PUBLIC KEY-----
"""

AUTORIZADA, NAO_AUTORIZADA, DEV = "autorizada", "nao-autorizada", "dev"
AUSENTE, ASSINATURA, MAQUINA = "ausente", "assinatura", "maquina"
MSG_ENVIO = "Envio desligado: instalação não autorizada."
MSG_RM = "Sincronização desligada: instalação não autorizada."
# O que a assinatura cobre (o documento sem a propria assinatura) e o teto do arquivo: o real tem ~200 bytes.
CAMPOS = ("data", "id", "maquina")
TAMANHO_MAX = 4096

# Resultado da conferencia feita na subida; vale ate' o proximo reinicio (`conferir`).
_estado: dict | None = None


class EnvioDesligado(ValueError):
    """Envio de e-mail numa instalacao nao autorizada. ValueError de proposito: as rotas de envio ja' respondem 422
    com a mensagem (e desfazem a transacao); a rota que nao captura ValueError cai no tratador de main.py."""

    def __init__(self):
        super().__init__(MSG_ENVIO)


def maquina_atual() -> str:
    """Nome desta maquina, lido do sistema e nao da variavel de ambiente (quem sobe a copia troca a variavel com um
    comando): no Windows (a producao) e' o mesmo nome do COMPUTERNAME, pela API; fora dele, o nome de rede."""
    if sys.platform == "win32":
        import ctypes
        tamanho = ctypes.c_ulong(256)
        nome = ctypes.create_unicode_buffer(256)
        if ctypes.windll.kernel32.GetComputerNameW(nome, ctypes.byref(tamanho)):
            return nome.value
    return platform.node()


def caminho_arquivo() -> Path | None:
    explicito = os.environ.get("DASH_INSTALACAO_ARQUIVO")
    if explicito:
        return Path(explicito)
    banco = os.environ.get("DASH_DB_PATH")
    if not banco:
        return None
    return Path(banco).parent.parent / "segredos" / "instalacao.json"


def _canonico(doc: dict) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _chave_publica() -> Ed25519PublicKey:
    chave = serialization.load_pem_public_key(CHAVE_PUBLICA.encode("ascii"))
    if not isinstance(chave, Ed25519PublicKey):
        raise ValueError("a chave publica embutida nao e' Ed25519")
    return chave


def assinar(chave_privada: Ed25519PrivateKey, maquina: str, hoje: datetime.date | None = None) -> bytes:
    """Conteudo do `instalacao.json` para `maquina`: uma linha de JSON canonico, que e' como o servidor o confere."""
    maquina = (maquina or "").strip()
    if not maquina:
        raise ValueError("Informe o nome da máquina")
    corpo = {"data": (hoje or datetime.date.today()).isoformat(), "id": secrets.token_hex(16), "maquina": maquina}
    assinatura = base64.b64encode(chave_privada.sign(_canonico(corpo))).decode("ascii")
    return _canonico({**corpo, "assinatura": assinatura}) + b"\n"


def conferir_arquivo(bruto: bytes, maquina: str) -> str | None:
    """None se o arquivo vale para `maquina`; senao o motivo: `assinatura` (ilegivel, adulterado ou de outra chave)
    ou `maquina` (assinado pelo dono para outra maquina).

    O arquivo vale exatamente como saiu do `assinar` (so' o fim de linha pode ser o do Windows): um byte trocado que o
    JSON aceitaria igual (espaco, escape, o bit que o base64 ignora) tambem recusa."""
    texto = bruto.removesuffix(b"\n").removesuffix(b"\r")
    try:
        doc = json.loads(texto.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        return ASSINATURA
    if (not isinstance(doc, dict) or set(doc) != {*CAMPOS, "assinatura"}
            or not all(isinstance(v, str) for v in doc.values()) or _canonico(doc) != texto):
        return ASSINATURA
    try:
        assinatura = base64.b64decode(doc["assinatura"], validate=True)
        if base64.b64encode(assinatura).decode("ascii") != doc["assinatura"]:
            return ASSINATURA
        _chave_publica().verify(assinatura, _canonico({k: doc[k] for k in CAMPOS}))
    except (binascii.Error, ValueError, InvalidSignature):
        return ASSINATURA
    if doc["maquina"].casefold() != (maquina or "").strip().casefold():
        return MAQUINA
    return None


def verificar() -> dict:
    """Le e confere o arquivo agora. {"instalacao": autorizada|nao-autorizada|dev, "motivo": None|ausente|...}."""
    if os.environ.get("DASH_DEV") == "1":
        return {"instalacao": DEV, "motivo": None}
    return conferir_caminho(caminho_arquivo())


def conferir_caminho(caminho: Path | None) -> dict:
    """Confere o arquivo em `caminho` para esta maquina, sem o atalho do dev (o deploy usa, antes de trocar o
    processo: `python -m app.cli instalacao verificar`)."""
    if caminho is None:
        return {"instalacao": NAO_AUTORIZADA, "motivo": AUSENTE}
    try:
        with open(caminho, "rb") as f:
            bruto = f.read(TAMANHO_MAX + 1)
    except OSError as e:
        if not isinstance(e, FileNotFoundError):
            log.warning("arquivo da instalacao ilegivel: %s", e)
        return {"instalacao": NAO_AUTORIZADA, "motivo": AUSENTE}
    motivo = ASSINATURA if len(bruto) > TAMANHO_MAX else conferir_arquivo(bruto, maquina_atual())
    return {"instalacao": AUTORIZADA if motivo is None else NAO_AUTORIZADA, "motivo": motivo}


def conferir() -> dict:
    """Na subida: confere e guarda o resultado, que vale ate' o proximo reinicio."""
    global _estado
    _estado = verificar()
    if _estado["instalacao"] == NAO_AUTORIZADA:
        log.warning("instalacao NAO autorizada (motivo: %s): envio de e-mail e sincronizacao com o RM desligados",
                    _estado["motivo"])
    else:
        log.info("instalacao: %s", _estado["instalacao"])
    return dict(_estado)


def estado() -> dict:
    return dict(_estado) if _estado is not None else conferir()


def ligada() -> bool:
    """Envio de e-mail e RM ligados: instalacao autorizada ou dev."""
    return estado()["instalacao"] != NAO_AUTORIZADA


def exigir_envio() -> None:
    """Chamada no ponto central do envio, antes da reserva (`envio_reserva.reservar`) e antes do e-mail
    (`correio.enviar_e_registrar`)."""
    if not ligada():
        raise EnvioDesligado()


# --- linha de comando (no Mac do dono) ------------------------------------------------------------------------

PRIVADA, PUBLICA = "instalacao-privada.pem", "instalacao-publica.pem"


def gerar_chave(pasta: Path) -> tuple[Path, Path]:
    """Grava o par em `pasta` (a privada so' para o dono, 0600). Nunca sobrescreve: FileExistsError."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
    privada, publica = pasta / PRIVADA, pasta / PUBLICA
    for p in (privada, publica):
        if p.exists():
            raise FileExistsError(p)
    chave = Ed25519PrivateKey.generate()
    texto_privada = chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption())
    fd = os.open(privada, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(texto_privada)
    publica.write_bytes(texto_publica(chave).encode("ascii"))
    return privada, publica


def texto_publica(chave_privada: Ed25519PrivateKey) -> str:
    return chave_privada.public_key().public_bytes(serialization.Encoding.PEM,
                                                   serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


def ler_chave_privada(caminho: Path, senha: bytes | None = None) -> Ed25519PrivateKey:
    """ValueError se o arquivo nao e' uma chave privada Ed25519; TypeError se ela pede senha e nao veio."""
    chave = serialization.load_pem_private_key(Path(caminho).read_bytes(), password=senha)
    if not isinstance(chave, Ed25519PrivateKey):
        raise ValueError("a chave não é Ed25519")
    return chave


def e_a_chave_embutida(chave_privada: Ed25519PrivateKey) -> bool:
    bruta = (serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return chave_privada.public_key().public_bytes(*bruta) == _chave_publica().public_bytes(*bruta)
