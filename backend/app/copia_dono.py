"""Copia cifrada semanal para a chave do dono (issue #419).

O pacote reune o ultimo snapshot valido de `dados\\backups` (o que passou no ensaio de
restauracao), a pasta `segredos` e a arvore do clone do cadastro, num `.tar` cifrado no formato
age (X25519) para a chave PUBLICA do dono. A chave privada fica so' no Mac dele: este modulo nao
aceita chave privada como configuracao e nao decifra nada.

Nada em claro no disco: o `.tar` e' montado em memoria e so' o texto cifrado e' gravado
(`.tmp` + rename, com `.sha256` ao lado). Ficam as 4 copias mais recentes.
"""

import datetime
import hashlib
import io
import logging
import os
import re
import tarfile
import threading
from pathlib import Path

from app import backup, tempo

log = logging.getLogger("app.copia_dono")

MANTER = 4
INTERVALO = datetime.timedelta(days=7)  # primeira rodada do backup depois de 7 dias da copia anterior
ATRASO_MAX = datetime.timedelta(days=8)  # acima disso a tela de Saude acusa
SUBPASTA = "dono"
PADRAO = "dashboard-dono-*.tar.age"
NAO_CONFIGURADA = "Cópia do dono não configurada"
_NOME = re.compile(r"dashboard-dono-\d{8}-\d{6}\.tar\.age$")
_lock = threading.Lock()  # uma geracao por vez no processo (botao e rodada semanal)


class NaoConfigurada(Exception):
    pass


class CopiaDonoErro(Exception):
    """Falha com mensagem nossa, em portugues e sem caminho do servidor."""


def arquivo_chave_publica(raiz: Path) -> Path:
    """`DASH_CHAVE_PUBLICA_DONO` (caminho do arquivo) sobrescreve o padrao da `segredos`."""
    env = os.environ.get("DASH_CHAVE_PUBLICA_DONO")
    return Path(env) if env else raiz / "segredos" / "chave-publica-dono.txt"


def pasta_cadastro(raiz: Path) -> Path:
    env = os.environ.get("DASH_CADASTRO_DIR")
    return Path(env) if env else raiz / "cadastro"


def _decodificar(bruto: bytes) -> str:
    """Unica porta de leitura de texto de chave: UTF-16 com BOM (o `>` e o `Out-File` do PowerShell 5.1),
    UTF-8 com ou sem BOM (`Set-Content -Encoding UTF8`) e, se o UTF-8 falhar, cp1252 (`Set-Content` ANSI;
    a linha age1... e' sempre ASCII). UTF-16 sem BOM: os NUL saem antes de decodificar. O texto volta sem NUL (comentario alem de U+00FF
    em UTF-16 sem BOM vira lixo; so' a linha age1..., ASCII, importa).
    UTF-16 com BOM truncado: UnicodeDecodeError."""
    if bruto.startswith((b"\xff\xfe", b"\xfe\xff")):
        return bruto.decode("utf-16").replace("\x00", "")
    bruto = bruto.replace(b"\x00", b"")
    try:
        return bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        return bruto.decode("cp1252", errors="replace")


def _texto_da_chave(arquivo: Path) -> str:
    return _decodificar(arquivo.read_bytes())


def _tem_chave_privada(arquivo: Path) -> bool:
    """Chave privada age em qualquer codificacao e em arquivo misto (BOM UTF-16 + ASCII no fim): a busca
    e' sempre nos bytes, sem os NUL. Arquivo binario ou ilegivel nao quebra: so' nao tem a chave."""
    return b"AGE-SECRET-KEY" in arquivo.read_bytes().replace(b"\x00", b"").upper()


def carregar_destinatario(raiz: Path):
    """O destinatario age (chave publica). Sem arquivo ou vazio: NaoConfigurada.
    Chave privada no lugar da publica e' recusada: ela nunca deve estar no servidor."""
    arquivo = arquivo_chave_publica(raiz)
    try:
        texto = _texto_da_chave(arquivo)
    except FileNotFoundError:
        raise NaoConfigurada(NAO_CONFIGURADA) from None
    except UnicodeError:
        raise CopiaDonoErro("não foi possível ler o arquivo da chave pública (grave-o em UTF-8)") from None
    if "AGE-SECRET-KEY" in texto.upper():
        raise CopiaDonoErro("o arquivo da chave contém uma chave privada; coloque só a chave pública "
                            "(age1...) e apague a privada do servidor")
    linhas = [l.strip() for l in texto.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not linhas:
        raise NaoConfigurada(NAO_CONFIGURADA)
    from pyrage import x25519
    try:
        return x25519.Recipient.from_str(linhas[0])
    except Exception:
        raise CopiaDonoErro("a chave pública do dono é inválida (esperado age1...)") from None


def configurada(raiz: Path) -> bool:
    """Ha' chave publica no arquivo (sem validar o formato: isso e' da geracao, que acusa o erro)."""
    try:
        texto = _texto_da_chave(arquivo_chave_publica(raiz))
    except (OSError, ValueError):
        return arquivo_chave_publica(raiz).exists()  # ilegivel: a geracao acusa o erro
    return any(l.strip() and not l.lstrip().startswith("#") for l in texto.splitlines())


def pasta_dono(pasta_backups: Path) -> Path:
    return pasta_backups / SUBPASTA


def copias(pasta_backups: Path) -> list[Path]:
    pasta = pasta_dono(pasta_backups)
    try:
        return sorted(a for a in pasta.glob(PADRAO) if _NOME.match(a.name)) if pasta.exists() else []
    except OSError:
        return []


def ultima_copia(pasta_backups: Path) -> datetime.datetime | None:
    """Momento (UTC) da copia mais recente em disco; sobrevive ao reinicio do servidor."""
    for a in reversed(copias(pasta_backups)):
        try:
            return datetime.datetime.fromtimestamp(a.stat().st_mtime, datetime.timezone.utc)
        except OSError:
            continue
    return None


def atrasada(pasta_backups: Path, agora: datetime.datetime) -> bool:
    ultima = ultima_copia(pasta_backups)
    return ultima is None or agora - ultima > ATRASO_MAX


def _snapshots_validos(pasta_backups: Path):
    """Do mais novo ao mais antigo, so' os que passam no ensaio de restauracao."""
    horarios = sorted((a for a in pasta_backups.glob(backup.PADRAO) if backup._NOME.match(a.name)), reverse=True)
    for a in horarios:
        try:
            backup.verificar_snapshot(a)
        except (backup.SnapshotInvalido, FileNotFoundError):
            continue
        yield a


def _sem_git(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    return None if ".git" in Path(info.name).parts else info


def montar_tar(snapshot: Path, segredos: Path, cadastro: Path) -> bytes:
    """O `.tar` em memoria: banco/<snapshot>, segredos/ e cadastro/ (sem a pasta .git)."""
    if segredos.is_dir():
        for arq in segredos.rglob("*"):
            if arq.is_file() and _tem_chave_privada(arq):
                raise CopiaDonoErro("há uma chave privada na pasta de segredos do servidor; "
                                    "apague-a e deixe só a chave pública")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(snapshot, arcname=f"banco/{snapshot.name}")
        for origem, nome in ((segredos, "segredos"), (cadastro, "cadastro")):
            if origem.is_dir():
                tar.add(origem, arcname=nome, filter=_sem_git)
    return buf.getvalue()


def _vencida(pasta_backups: Path) -> bool:
    ultima = ultima_copia(pasta_backups)
    return ultima is None or tempo.agora_utc() - ultima >= INTERVALO


def gerar(raiz: Path, pasta_backups: Path, so_se_vencida: bool = False) -> Path | None:
    """Gera a copia cifrada e devolve o caminho. Levanta NaoConfigurada sem chave publica.
    `so_se_vencida` (rodada semanal): refaz a conferencia dos 7 dias DENTRO do lock, para que o
    botao e a rodada ao mesmo tempo nao gerem duas copias; devolve None se outra acabou de gerar."""
    with _lock:
        if so_se_vencida and not _vencida(pasta_backups):
            return None
        destinatario = carregar_destinatario(raiz)
        import pyrage
        tar = None
        for snapshot in _snapshots_validos(pasta_backups):
            try:
                tar = montar_tar(snapshot, raiz / "segredos", pasta_cadastro(raiz))
                break
            except FileNotFoundError:
                if snapshot.exists():
                    raise  # o que faltou foi outro arquivo, nao o snapshot rotacionado pelo backup
        if tar is None:
            raise CopiaDonoErro("nenhum snapshot válido para copiar")
        cifrado = pyrage.encrypt(tar, [destinatario])
        del tar
        pasta = pasta_dono(pasta_backups)
        pasta.mkdir(parents=True, exist_ok=True)
        carimbo = f"{tempo.para_local(tempo.agora_utc()):%Y%m%d-%H%M%S}"
        destino = pasta / f"dashboard-dono-{carimbo}.tar.age"
        if destino.exists():
            raise CopiaDonoErro("já existe uma cópia deste mesmo segundo; tente de novo")
        esperado = hashlib.sha256(cifrado).hexdigest()
        parcial = pasta / f"{destino.name}.tmp"
        try:
            with open(parcial, "wb") as f:
                f.write(cifrado)
                f.flush()
                os.fsync(f.fileno())
            if backup._sha256(parcial) != esperado:
                raise CopiaDonoErro("a cópia gravada não confere com o que foi cifrado")
            # o .sha256 antes do rename: queda no meio nunca deixa copia sem checksum
            (pasta / f"{destino.name}.sha256").write_text(f"{esperado}  {destino.name}\n", encoding="utf-8")
            parcial.replace(destino)
        except BaseException:
            parcial.unlink(missing_ok=True)
            (pasta / f"{destino.name}.sha256").unlink(missing_ok=True)
            raise
        for velha in copias(pasta_backups)[:-MANTER]:
            velha.unlink(missing_ok=True)
            (pasta / f"{velha.name}.sha256").unlink(missing_ok=True)
        return destino


def gerar_e_registrar(raiz: Path, pasta_backups: Path, so_se_vencida: bool = False) -> Path | None:
    """`gerar` + `backup.ESTADO` (o que o health e a Saude mostram)."""
    agora = tempo.para_local(tempo.agora_utc()).isoformat(timespec="seconds")
    try:
        destino = gerar(raiz, pasta_backups, so_se_vencida)
    except NaoConfigurada:
        raise
    except Exception as e:
        backup.ESTADO["ultima_copia_dono_erro"] = f"{agora}: {_motivo(e)}"
        log.exception("copia do dono falhou")
        raise
    if destino is not None:
        backup.ESTADO["ultima_copia_dono"] = agora
        backup.ESTADO["ultima_copia_dono_erro"] = None
    return destino


def _motivo(e: BaseException) -> str:
    return str(e) if isinstance(e, CopiaDonoErro) else backup._motivo(e)


def rodada_semanal(raiz: Path, pasta_backups: Path) -> Path | None:
    """Chamada a cada rodada do backup: gera se a anterior tem mais de 7 dias. Sem chave, nada.
    Devolve a copia gerada (issue #420: `copia_dono_envio` a envia por e-mail), ou None."""
    ultima = ultima_copia(pasta_backups)
    if ultima is not None and not backup.ESTADO.get("ultima_copia_dono"):
        backup.ESTADO["ultima_copia_dono"] = tempo.para_local(ultima).isoformat(timespec="seconds")
    if ultima is not None and tempo.agora_utc() - ultima < INTERVALO:
        return None
    try:
        return gerar_e_registrar(raiz, pasta_backups, so_se_vencida=True)
    except NaoConfigurada:
        return None
    except Exception:
        return None  # ja' registrado em ESTADO e no log
