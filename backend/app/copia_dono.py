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


def carregar_destinatario(raiz: Path):
    """O destinatario age (chave publica). Sem arquivo ou vazio: NaoConfigurada.
    Chave privada no lugar da publica e' recusada: ela nunca deve estar no servidor."""
    arquivo = arquivo_chave_publica(raiz)
    try:
        texto = arquivo.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise NaoConfigurada(NAO_CONFIGURADA) from None
    if "AGE-SECRET-KEY" in texto.upper():
        raise CopiaDonoErro("o arquivo da chave contém uma chave privada; coloque só a chave pública "
                            "(age1...) e apague a privada do servidor")
    linhas = [l.strip() for l in texto.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not linhas:
        raise NaoConfigurada(NAO_CONFIGURADA)
    try:
        from pyrage import x25519
        return x25519.Recipient.from_str(linhas[0])
    except Exception:
        raise CopiaDonoErro("a chave pública do dono é inválida (esperado age1...)") from None


def configurada(raiz: Path) -> bool:
    """Ha' chave publica no arquivo (sem validar o formato: isso e' da geracao, que acusa o erro)."""
    try:
        texto = arquivo_chave_publica(raiz).read_text(encoding="utf-8")
    except OSError:
        return False
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


def _ultimo_snapshot_valido(pasta_backups: Path) -> Path:
    horarios = sorted((a for a in pasta_backups.glob(backup.PADRAO) if backup._NOME.match(a.name)), reverse=True)
    for a in horarios:
        try:
            backup.verificar_snapshot(a)
            return a
        except backup.SnapshotInvalido:
            continue
    raise CopiaDonoErro("nenhum snapshot válido para copiar")


def _sem_git(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    return None if ".git" in Path(info.name).parts else info


def montar_tar(snapshot: Path, segredos: Path, cadastro: Path) -> bytes:
    """O `.tar` em memoria: banco/<snapshot>, segredos/ e cadastro/ (sem a pasta .git)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(snapshot, arcname=f"banco/{snapshot.name}")
        for origem, nome in ((segredos, "segredos"), (cadastro, "cadastro")):
            if origem.is_dir():
                tar.add(origem, arcname=nome, filter=_sem_git)
    return buf.getvalue()


def gerar(raiz: Path, pasta_backups: Path) -> Path:
    """Gera a copia cifrada e devolve o caminho. Levanta NaoConfigurada sem chave publica."""
    with _lock:
        destinatario = carregar_destinatario(raiz)
        import pyrage
        snapshot = _ultimo_snapshot_valido(pasta_backups)
        cifrado = pyrage.encrypt(montar_tar(snapshot, raiz / "segredos", pasta_cadastro(raiz)), [destinatario])
        pasta = pasta_dono(pasta_backups)
        pasta.mkdir(parents=True, exist_ok=True)
        carimbo = f"{tempo.para_local(tempo.agora_utc()):%Y%m%d-%H%M%S}"
        destino = pasta / f"dashboard-dono-{carimbo}.tar.age"
        parcial = pasta / f"{destino.name}.tmp"
        try:
            with open(parcial, "wb") as f:
                f.write(cifrado)
                f.flush()
                os.fsync(f.fileno())
            if backup._sha256(parcial) != hashlib.sha256(cifrado).hexdigest():
                raise CopiaDonoErro("a cópia gravada não confere com o que foi cifrado")
            parcial.replace(destino)
        except BaseException:
            parcial.unlink(missing_ok=True)
            raise
        (pasta / f"{destino.name}.sha256").write_text(f"{backup._sha256(destino)}  {destino.name}\n",
                                                      encoding="utf-8")
        for velha in copias(pasta_backups)[:-MANTER]:
            velha.unlink(missing_ok=True)
            (pasta / f"{velha.name}.sha256").unlink(missing_ok=True)
        return destino


def gerar_e_registrar(raiz: Path, pasta_backups: Path) -> Path:
    """`gerar` + `backup.ESTADO` (o que o health e a Saude mostram)."""
    agora = tempo.para_local(tempo.agora_utc()).isoformat(timespec="seconds")
    try:
        destino = gerar(raiz, pasta_backups)
    except NaoConfigurada:
        raise
    except Exception as e:
        backup.ESTADO["ultima_copia_dono_erro"] = f"{agora}: {_motivo(e)}"
        log.exception("copia do dono falhou")
        raise
    backup.ESTADO["ultima_copia_dono"] = agora
    backup.ESTADO["ultima_copia_dono_erro"] = None
    return destino


def _motivo(e: BaseException) -> str:
    return str(e) if isinstance(e, CopiaDonoErro) else backup._motivo(e)


def rodada_semanal(raiz: Path, pasta_backups: Path) -> None:
    """Chamada a cada rodada do backup: gera se a anterior tem mais de 7 dias. Sem chave, nada."""
    ultima = ultima_copia(pasta_backups)
    if ultima is not None and not backup.ESTADO.get("ultima_copia_dono"):
        backup.ESTADO["ultima_copia_dono"] = tempo.para_local(ultima).isoformat(timespec="seconds")
    if ultima is not None and tempo.agora_utc() - ultima < INTERVALO:
        return
    try:
        gerar_e_registrar(raiz, pasta_backups)
    except NaoConfigurada:
        return
    except Exception:
        pass  # ja' registrado em ESTADO e no log
