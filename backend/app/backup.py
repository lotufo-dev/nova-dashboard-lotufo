"""Snapshots do banco, ensaio de restauracao, copia externa diaria e retencao em camadas.

- Snapshot horario (e um no boot) por `VACUUM INTO`, atomico (.tmp + rename), 48 locais.
- Cada snapshot passa por um ENSAIO DE RESTAURACAO: abre-se a copia e roda-se
  `PRAGMA integrity_check`. Snapshot que nao abre e' apagado e contado como falha.
- Copia externa (outro volume ou compartilhamento, `DASH_BACKUP_EXTERNO`): uma vez
  por dia, com `.sha256` ao lado, conferida relendo o destino. Retencao em camadas:
  7 diarios, 5 semanais, 12 mensais.
- Arquivos ao lado do banco (issue #55; todas as pastas desde a #441, ver PASTAS_ARQUIVOS) vao
  para `<backups>/arquivos/<pasta>/` e, havendo pasta externa, para
  `<externo>/arquivos/<pasta>/`, num worker proprio (thread "backup-arquivos"), acordado
  logo depois de cada snapshot: a thread do banco so' faz snapshot (e a copia externa
  diaria do banco, como antes), entao copia lenta ou pendurada nao para os snapshots.
  Os nomes sao o sha256 do conteudo e nunca mudam de conteudo: uma copia de cada arquivo
  serve a todos os snapshots (o disco nao cresce 48 vezes) e o backup nunca apaga o que
  guardou (um snapshot antigo pode citar arquivo que ja saiu da pasta de dados).
- `ESTADO` guarda o resultado da ultima rodada; /api/health o expoe por `estado()`.
"""

import datetime
import errno
import hashlib
import logging
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from app import tempo

log = logging.getLogger("app.backup")

MANTER = 48  # ~2 dias de snapshots horarios
PADRAO = "dashboard-*.db"  # o que a rotacao enxerga (nao casa com *.db.tmp)
IDADE_TMP_SEG = 3600  # so e' "sobra" o .tmp que ja passou de 1 hora
_NOME = re.compile(r"dashboard-(\d{4})(\d{2})(\d{2})-\d{6}\.db$")
CAMADAS = {"diarios": 7, "semanais": 5, "mensais": 12}
# Toda pasta de `dados` que o sistema grava (issue #441; o teste confere no codigo). So' `assinaturas` nao e' pelo
# sha256 (`usuario-<id>`, trocada pela pessoa): o backup guarda a ultima de cada um (ver `_copiar_um`).
PASTAS_ARQUIVOS = ("notas", "espelhos", "modelos", "evidencias", "certidoes", "regularidades", "protocolos",
                   "pleitos", "curvas", "planilhas", "frc", "boletins", "anexos", "assinaturas")
SUBPASTA_ARQUIVOS = "arquivos"  # dentro da pasta de backups e da pasta externa
PRAZO_ARQUIVOS_SEG = 2 * 3600  # passada dos arquivos rodando ha mais que isso = acusada no health
CONFERIR_DESTINO_SEG = 24 * 3600  # releitura completa do destino pelo sha256: uma vez por dia

# Ultima rodada, para o health. Datas em ISO local; None = nunca nesta execucao.
ESTADO: dict = {"ultimo_snapshot": None, "ultimo_snapshot_erro": None,
                "ultima_copia_arquivos": None, "ultima_copia_arquivos_erro": None,
                "ultima_copia_externa": None, "ultima_copia_externa_erro": None,
                "ultima_copia_externa_arquivos": None, "ultima_copia_externa_arquivos_erro": None,
                "ultima_copia_dono": None, "ultima_copia_dono_erro": None}

# Worker dos arquivos (um por processo). Fase ("local"/"externa") e inicio (time.monotonic) da
# passada em andamento, None = parado; `estado()` le isto na hora do /api/health para acusar a
# passada que nao termina, sem depender do proprio worker (que e' quem pode estar travado).
_arquivos_fase: str | None = None
_arquivos_desde: float | None = None
_thread_arquivos: threading.Thread | None = None
_acordar_arquivos = threading.Event()
_conferido_em: dict[str, float] = {}  # destino -> ultima releitura completa tentada (time.monotonic)
_pendentes: dict[str, set[str]] = {}  # destino -> "<pasta>/<nome>" que falharam na ultima passada
_lock_worker = threading.Lock()  # criacao e supervisao do worker: nunca dois vivos no processo


class SnapshotInvalido(Exception):
    pass


def _limpar_tmp_abandonados(pasta_destino: Path, agora: float) -> None:
    """Remove SO os .tmp velhos o bastante para nao serem de ninguem vivo.

    Dois processos podem escrever snapshots na mesma pasta (a tarefa agendada e
    uma execucao manual, por exemplo). Apagar todo *.db.tmp no inicio destruiria
    o VACUUM em andamento do outro processo, que so descobriria isso no rename
    final. O corte por mtime resolve: .tmp com mais de 1h e' sobra de processo
    morto; um recem-criado pertence a alguem que ainda esta trabalhando.
    """
    for sobra in pasta_destino.glob("*.db.tmp"):
        try:
            if agora - sobra.stat().st_mtime > IDADE_TMP_SEG:
                sobra.unlink(missing_ok=True)
        except OSError:
            pass  # sumiu/travou no meio (outro processo renomeou): nao e' problema nosso


def verificar_snapshot(arquivo: Path) -> None:
    """Ensaio de restauracao: o snapshot abre e passa no integrity_check.

    E' o que o runbook manda fazer ao restaurar; fazer a cada snapshot garante que o
    backup que sera' usado no pior dia ja foi aberto pelo menos uma vez.
    """
    try:
        conn = sqlite3.connect(f"file:{arquivo}?mode=ro", uri=True)
        try:
            r = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        raise SnapshotInvalido(f"{arquivo.name}: nao abre ({e})") from e
    if r is None or r[0] != "ok":
        raise SnapshotInvalido(f"{arquivo.name}: integrity_check = {r[0] if r else None!r}")


def criar_snapshot(origem_db: Path, pasta_destino: Path) -> Path:
    pasta_destino.mkdir(parents=True, exist_ok=True)

    _limpar_tmp_abandonados(pasta_destino, time.time())

    # Carimbo na hora de CUIABA, nao no relogio da maquina: e' o nome pelo qual alguem
    # procura "o backup de ontem de manha", e a rotacao ordena por ele. `datetime.now()`
    # sem fuso mudava de significado com o servidor (a proibicao esta em app/tempo.py).
    carimbo = f"{tempo.para_local(tempo.agora_utc()):%Y%m%d-%H%M%S}"
    nome = f"dashboard-{carimbo}.db"
    destino = pasta_destino / nome
    # Escrever num nome que a rotacao NAO enxerga e so entao renomear: se o
    # VACUUM morrer no meio, o arquivo parcial nunca conta como snapshot valido
    # nem empurra um backup bom para fora da janela de 48.
    # O PID entra no nome do temporario para que dois processos concorrentes
    # nunca escrevam no MESMO arquivo parcial (um sobrescreveria o VACUUM do outro).
    parcial = pasta_destino / f"dashboard-{carimbo}-pid{os.getpid()}.db.tmp"
    conn = sqlite3.connect(origem_db)
    try:
        conn.execute("VACUUM INTO ?", (str(parcial),))
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise
    finally:
        conn.close()
    # Ensaio ANTES do rename: um parcial que nao passa nunca vira snapshot valido.
    try:
        verificar_snapshot(parcial)
    except SnapshotInvalido:
        parcial.unlink(missing_ok=True)
        raise
    parcial.replace(destino)  # rename atomico no mesmo volume

    # So os horarios (dashboard-AAAAMMDD-HHMMSS.db): os PRE-* nao entram na conta nem sao apagados.
    antigos = sorted(a for a in pasta_destino.glob(PADRAO) if _NOME.match(a.name))
    for velho in antigos[:-MANTER] if len(antigos) > MANTER else []:
        velho.unlink()
    return destino


# --- copia externa -----------------------------------------------------------------

def _sha256(arquivo: Path) -> str:
    h = hashlib.sha256()
    with open(arquivo, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _data_do_nome(arquivo: Path) -> datetime.date | None:
    m = _NOME.match(arquivo.name)
    return datetime.date(int(m[1]), int(m[2]), int(m[3])) if m else None


def copiar_externo(snapshot: Path, pasta_externa: Path) -> Path:
    """Copia o snapshot para fora com checksum conferido no destino.

    Escreve `.tmp` + rename e grava `<nome>.sha256`; depois RELE o destino e compara
    -- a copia so conta quando o que esta no outro volume e' o que saiu daqui.
    """
    pasta_externa.mkdir(parents=True, exist_ok=True)
    esperado = _sha256(snapshot)
    destino = pasta_externa / snapshot.name
    parcial = pasta_externa / f"{snapshot.name}.tmp"
    try:
        shutil.copyfile(snapshot, parcial)
        if _sha256(parcial) != esperado:
            raise OSError(f"cópia externa de {snapshot.name} conferida diferente da original")
        parcial.replace(destino)
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise
    (pasta_externa / f"{snapshot.name}.sha256").write_text(f"{esperado}  {snapshot.name}\n",
                                                           encoding="utf-8")
    rotacionar_externo(pasta_externa)
    return destino


def rotacionar_externo(pasta_externa: Path) -> None:
    """Retencao em camadas: o mais novo de cada dia (7), semana ISO (5) e mes (12).

    Um arquivo fica se cabe em QUALQUER camada. Com uma copia por dia, o diario e'
    o proprio arquivo; o semanal e o mensal sao o ultimo de cada periodo.
    """
    arquivos = [(d, a) for a in pasta_externa.glob(PADRAO) if (d := _data_do_nome(a))]
    arquivos.sort(key=lambda par: (par[0], par[1].name))
    manter: set[Path] = set()
    for chave, quantos in ((lambda d: d, CAMADAS["diarios"]),
                           (lambda d: d.isocalendar()[:2], CAMADAS["semanais"]),
                           (lambda d: (d.year, d.month), CAMADAS["mensais"])):
        ultimo_por_periodo: dict = {}
        for d, a in arquivos:
            ultimo_por_periodo[chave(d)] = a  # ordenado: o ultimo visto e' o mais novo
        for periodo in sorted(ultimo_por_periodo)[-quantos:]:
            manter.add(ultimo_por_periodo[periodo])
    for _, a in arquivos:
        if a not in manter:
            a.unlink(missing_ok=True)
            (pasta_externa / f"{a.name}.sha256").unlink(missing_ok=True)


# --- arquivos ao lado do banco (issue #55) ---------------------------------------------

class ErroArquivo(OSError):
    """Falha da copia com mensagem nossa, ja' em portugues e sem caminho do servidor."""


def _motivo(e: BaseException) -> str:
    """O que vai ao health e a' tela: sem caminho absoluto (o log guarda o resto)."""
    if isinstance(e, ErroArquivo):
        return str(e)
    if isinstance(e, PermissionError):
        return "acesso negado"
    if isinstance(e, FileNotFoundError):
        return "arquivo ou pasta não encontrado"
    if isinstance(e, OSError) and e.errno == errno.ENOSPC:
        return "disco cheio"
    if isinstance(e, TimeoutError):
        return "a pasta não respondeu a tempo"
    if isinstance(e, OSError) and e.errno is None and e.filename is None and len(e.args) == 1:
        return str(e)  # levantado pelo nosso codigo, com texto nosso (sem caminho)
    if isinstance(e, SnapshotInvalido):
        return "o snapshot não passou no ensaio de restauração"
    if isinstance(e, sqlite3.OperationalError) and "locked" in str(e):
        return "banco ocupado"
    if isinstance(e, sqlite3.Error):
        return "erro do banco (detalhes no log do servidor)"
    return "erro de leitura ou gravação (detalhes no log do servidor)"


def copiar_arquivos(raiz_origem: Path, raiz_destino: Path, conferir: bool = False,
                    conferir_estes: set[str] | None = None, falhos: set[str] | None = None) -> int:
    """Copia `raiz_origem/<pasta>/*` para `raiz_destino/<pasta>/` nas PASTAS_ARQUIVOS.

    Serve aos dois sentidos: backup (dados -> backups/arquivos) e restauracao
    (backups/arquivos -> dados). So' copia o que falta no destino; nunca apaga nada.
    Temporarios (`*.tmp`, upload em andamento) ficam de fora. Cada copia vai para um
    `.tmp`, e' conferida pelo sha256 contra a origem e so' entao renomeada: ou o
    arquivo aparece inteiro, ou nao aparece. Origem cujo conteudo nao bate com o
    sha256 do proprio nome nao e' copiada (copiaria o defeito para o backup).

    Sem `conferir`, arquivo do mesmo nome e tamanho no destino conta como presente (barato:
    roda toda hora). Com `conferir`, o destino e' relido e comparado ao sha256; o estragado
    e' substituido pela origem (o worker faz isso uma vez por dia; a restauracao, sempre).

    `conferir_estes` ("<pasta>/<nome>") confere so' esses (os que falharam na passada
    anterior); `falhos`, se dado, recebe os que falharam nesta.

    Um arquivo com problema nao impede os outros: todos sao tentados e, no fim, sobe
    ErroArquivo com os que ficaram sem copia. Devolve quantos arquivos copiou.
    """
    conferir_estes = conferir_estes or set()
    copiados = 0
    falhas: list[str] = []
    agora = time.time()
    for nome in PASTAS_ARQUIVOS:
        origem = raiz_origem / nome
        if not origem.is_dir():
            continue
        destino = raiz_destino / nome
        destino.mkdir(parents=True, exist_ok=True)
        _limpar_parciais_abandonados(destino, agora)
        for arquivo in sorted(origem.iterdir()):
            if not arquivo.is_file() or arquivo.name.endswith(".tmp"):
                continue
            rel = f"{nome}/{arquivo.name}"
            try:
                if _copiar_um(arquivo, destino / arquivo.name, conferir or rel in conferir_estes):
                    copiados += 1
            except OSError as e:
                log.warning("arquivo sem copia: %s -> %s", arquivo, destino, exc_info=True)
                falhas.append(f"{rel} ({_motivo(e)})")
                if falhos is not None:
                    falhos.add(rel)
    if falhas:
        mais = f" e mais {len(falhas) - 3}" if len(falhas) > 3 else ""
        raise ErroArquivo(f"{len(falhas)} arquivo(s) sem cópia: {'; '.join(falhas[:3])}{mais}")
    return copiados


# `<nome>.<pid>-<thread>-<aleatorio>.tmp`: so' o que _copiar_um cria. PID, thread e sufixo
# aleatorio no nome: duas copias (outro processo, outra thread) nunca escrevem no mesmo parcial.
_PARCIAL_NOSSO = re.compile(r"\.\d+-\d+-[0-9a-f]{8}\.tmp$")
_NOME_SHA = re.compile(r"[0-9a-f]{64}")


def _limpar_parciais_abandonados(destino: Path, agora: float) -> None:
    """Sobra de copia interrompida (processo morto no meio): ninguem mais a renomeia.

    So' sai o parcial com mais de 1 hora E que nao esta' aberto: a copia ativa segura o
    seu parcial aberto do primeiro byte ate' a conferencia, e no Windows (a producao) um
    arquivo aberto nao se apaga -- o unlink falha e o parcial vivo fica.
    """
    for sobra in destino.glob("*.tmp"):
        try:
            if _PARCIAL_NOSSO.search(sobra.name) and agora - sobra.stat().st_mtime > IDADE_TMP_SEG:
                sobra.unlink(missing_ok=True)
        except OSError:
            pass  # aberto por uma copia viva (ou sumiu): nao e' sobra


def _copiar_um(arquivo: Path, alvo: Path, conferir: bool = False) -> bool:
    """Copia um arquivo conferido; False se ja estava la (e, com `conferir`, integro)."""
    com_sha = bool(_NOME_SHA.fullmatch(arquivo.stem))
    if alvo.exists():
        if not conferir:
            # o nome e' o sha256 do conteudo: mesmo nome e mesmo tamanho = mesmo arquivo
            if alvo.stat().st_size == arquivo.stat().st_size:
                return False
        elif _sha256(alvo) == (arquivo.stem if com_sha else _sha256(arquivo)):
            return False
        # tamanho diferente ou conteudo estragado: substitui pela origem conferida
    esperado = _sha256(arquivo)
    if com_sha and arquivo.stem != esperado:
        raise ErroArquivo("conteúdo não confere com o nome")
    parcial = alvo.parent / f"{arquivo.name}.{os.getpid()}-{threading.get_ident()}-{secrets.token_hex(4)}.tmp"
    try:
        # "x": criacao exclusiva. O parcial fica aberto ate' conferido (ver _limpar_parciais_abandonados).
        with open(parcial, "xb") as saida:
            with open(arquivo, "rb") as entrada:
                shutil.copyfileobj(entrada, saida, 1 << 20)
            saida.flush()
            os.fsync(saida.fileno())
            if _sha256(parcial) != esperado:
                raise ErroArquivo("cópia conferida diferente da original")
        parcial.replace(alvo)
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise
    return True


def _copiou_hoje(pasta_externa: Path, hoje: datetime.date) -> bool:
    """So conta o dia como feito com o par .db + .sha256 (o .sha256 e' gravado por
    ultimo: sem ele, a copia pode ter morrido no meio e a proxima rodada refaz)."""
    if not pasta_externa.exists():
        return False
    return any(_data_do_nome(a) == hoje and (pasta_externa / f"{a.name}.sha256").exists()
               for a in pasta_externa.glob(PADRAO))


# --- rodada e agendamento ------------------------------------------------------------

def rodada(origem_db: Path, pasta_destino: Path, pasta_externa: Path | None) -> None:
    """Rodada do banco: snapshot + ensaio; copia externa do banco se ainda nao houve hoje.
    Os arquivos sao de outra thread (`rodada_arquivos`): copia lenta ou pendurada nao pode
    parar os snapshots."""
    agora = tempo.para_local(tempo.agora_utc())
    try:
        snapshot = criar_snapshot(origem_db, pasta_destino)
        ESTADO["ultimo_snapshot"] = agora.isoformat(timespec="seconds")
        ESTADO["ultimo_snapshot_erro"] = None
    except Exception as e:
        ESTADO["ultimo_snapshot_erro"] = f"{agora.isoformat(timespec='seconds')}: {_motivo(e)}"
        log.exception("snapshot falhou")
        return
    if pasta_externa is None:
        return
    try:
        # `exists()`/`glob()` num compartilhamento sem permissao levantam PermissionError
        # (pathlib so engole ENOENT): tem que estar DENTRO do try, senao a thread morre
        # calada e o health segue dizendo "sem erro" para sempre.
        if _copiou_hoje(pasta_externa, agora.date()):
            return
        copiar_externo(snapshot, pasta_externa)
        ESTADO["ultima_copia_externa"] = agora.isoformat(timespec="seconds")
        ESTADO["ultima_copia_externa_erro"] = None
    except Exception as e:
        ESTADO["ultima_copia_externa_erro"] = f"{agora.isoformat(timespec='seconds')}: {_motivo(e)}"
        log.exception("copia externa falhou")


def rodada_arquivos(origem_db: Path, pasta_destino: Path, pasta_externa: Path | None) -> None:
    """Uma passada dos arquivos: primeiro a pasta local de backups, depois a externa.

    Roda no worker dos arquivos, uma passada por vez (nunca duas ao mesmo tempo no processo).
    Comeca logo depois de cada snapshot (o worker e' acordado por ele): todo arquivo que o
    snapshot cita ja estava no disco (o sistema grava o arquivo antes da linha do banco),
    entao a passada seguinte o alcanca. `_arquivos_desde` marca a passada em andamento para
    o health acusar a que nao termina (ver `estado`).
    """
    global _arquivos_fase, _arquivos_desde
    destinos = [("local", "ultima_copia_arquivos", pasta_destino / SUBPASTA_ARQUIVOS)]
    if pasta_externa is not None:
        destinos.append(("externa", "ultima_copia_externa_arquivos", pasta_externa / SUBPASTA_ARQUIVOS))
    for fase, chave, destino in destinos:
        agora = tempo.para_local(tempo.agora_utc())
        inicio = time.monotonic()
        _arquivos_fase, _arquivos_desde = fase, inicio
        ultima = _conferido_em.get(str(destino))
        conferir = ultima is None or inicio - ultima > CONFERIR_DESTINO_SEG
        if conferir:
            # vale a TENTATIVA: falha em um arquivo nao faz reler o acervo inteiro toda hora;
            # os que falharam voltam sozinhos na passada seguinte (`_pendentes`)
            _conferido_em[str(destino)] = inicio
        falhos: set[str] = set()
        try:
            copiar_arquivos(origem_db.parent, destino, conferir=conferir,
                            conferir_estes=_pendentes.get(str(destino)), falhos=falhos)
            ESTADO[chave] = agora.isoformat(timespec="seconds")
            ESTADO[f"{chave}_erro"] = None
        except Exception as e:
            ESTADO[f"{chave}_erro"] = f"{agora.isoformat(timespec='seconds')}: {_motivo(e)}"
            log.exception("copia dos arquivos falhou (%s)", fase)
        finally:
            _pendentes[str(destino)] = falhos
            _arquivos_fase, _arquivos_desde = None, None


def estado() -> dict:
    """O ESTADO como o /api/health o mostra, com o que so' se sabe na hora da leitura:
    passada dos arquivos rodando alem do prazo, ou worker dos arquivos morto. Calculado
    aqui (na thread do pedido) e nao no worker, que e' justamente quem pode estar travado."""
    d = dict(ESTADO)
    fase, desde = _arquivos_fase, _arquivos_desde
    if desde is not None and time.monotonic() - desde > PRAZO_ARQUIVOS_SEG:
        horas = int((time.monotonic() - desde) // 3600)
        chave = "ultima_copia_arquivos_erro" if fase == "local" else "ultima_copia_externa_arquivos_erro"
        d[chave] = f"a cópia está rodando há {horas} horas sem terminar"
    t = _thread_arquivos
    if t is not None and not t.is_alive():
        d["ultima_copia_arquivos_erro"] = "a tarefa de cópia dos arquivos parou (veja o log do servidor)"
    return d


def _loop_arquivos(origem_db: Path, pasta_destino: Path, pasta_externa: Path | None) -> None:
    while True:
        _acordar_arquivos.wait(3600)  # acordado pelo snapshot; de hora em hora no pior caso
        _acordar_arquivos.clear()
        try:
            rodada_arquivos(origem_db, pasta_destino, pasta_externa)
        except Exception:  # rede de seguranca: o worker nao morre por excecao comum
            log.exception("copia dos arquivos falhou fora do previsto")


def _iniciar_worker_arquivos(origem_db: Path, pasta_destino: Path, pasta_externa: Path | None) -> bool:
    """Sobe o worker so' se nao houver um vivo (sob `_lock_worker`). True se subiu."""
    global _thread_arquivos
    with _lock_worker:
        if _thread_arquivos is not None and _thread_arquivos.is_alive():
            return False
        _thread_arquivos = threading.Thread(target=_loop_arquivos, args=(origem_db, pasta_destino, pasta_externa),
                                            daemon=True, name="backup-arquivos")
        _thread_arquivos.start()
        return True


def _supervisionar_arquivos(origem_db: Path, pasta_destino: Path, pasta_externa: Path | None) -> None:
    """Worker dos arquivos morto: registra e sobe outro (a thread do banco chama a cada hora)."""
    t = _thread_arquivos
    if t is not None and not t.is_alive() and _iniciar_worker_arquivos(origem_db, pasta_destino, pasta_externa):
        agora = tempo.para_local(tempo.agora_utc())
        ESTADO["ultima_copia_arquivos_erro"] = (f"{agora.isoformat(timespec='seconds')}: a tarefa de "
                                                "cópia dos arquivos tinha parado e foi reiniciada")
        log.error("worker dos arquivos estava morto; reiniciado")


def pasta_local() -> Path:
    """Onde ficam os snapshots: ao lado do banco (nunca dependem do diretorio de trabalho)."""
    from app import db
    return db.db_path().parent / "backups"


def pasta_externa() -> Path | None:
    """A copia externa diaria, se `DASH_BACKUP_EXTERNO` estiver configurada."""
    externo = os.environ.get("DASH_BACKUP_EXTERNO")
    return Path(externo) if externo else None


# Snapshot e' horario: passou de 2 h sem um novo, uma rodada inteira falhou ou a thread parou.
ATRASO_MAX = datetime.timedelta(hours=2)


def _snapshots_locais(local: Path) -> list[os.stat_result]:
    """stat de cada snapshot HORARIO guardado (nome `dashboard-AAAAMMDD-HHMMSS.db`). O
    `dashboard-PRE-*.db` do deploy casa com PADRAO mas nao e' a rotina horaria: contado, um
    deploy recente esconderia o snapshot horario parado. Arquivo que some no meio (a rotacao do
    outro processo) fica de fora; pasta ilegivel conta como vazia, e a tela mostra o atraso."""
    stats = []
    try:
        arquivos = [a for a in local.glob(PADRAO) if _NOME.match(a.name)] if local.exists() else []
    except OSError:
        return []
    for a in arquivos:
        try:
            stats.append(a.stat())
        except OSError:
            pass
    return stats


def _erro_para_tela(bruto: str | None, mensagem: str) -> tuple[str | None, str | None]:
    """`ESTADO` guarda "<iso>: <excecao>", e a excecao traz caminho, compartilhamento e maquina.
    A tela recebe so' o momento e uma frase fixa; o detalhe fica no log do servidor (`log.exception`)."""
    if not bruto:
        return None, None
    em = bruto.split(": ", 1)[0]  # o ISO nao tem ": " (so' ":" sem espaco)
    return em, f"{mensagem}; o detalhe está no log do servidor"


_ISO_NA_FRENTE = re.compile(r"(\d{4}-\d{2}-\d{2}T\S+): (.*)", re.S)


def _erro_dos_arquivos(bruto: str | None) -> tuple[str | None, str | None]:
    """A copia dos arquivos ja' grava no ESTADO a frase da tela (`_motivo`, sem caminho), com
    os arquivos que faltaram ou o "rodando ha N horas": vai inteira, separada do momento."""
    if not bruto:
        return None, None
    m = _ISO_NA_FRENTE.fullmatch(bruto)
    return (m[1], m[2]) if m else (None, bruto)


def situacao(local: Path, externa_configurada: bool, agora: datetime.datetime) -> dict:
    """Saude do backup para a tela de Administracao (issue #31).

    O ultimo backup e a contagem vem do DISCO (sobrevivem ao servidor reiniciar); os erros
    vem de `ESTADO`, que so existe na memoria desta execucao. Sem snapshot nenhum conta como
    atrasado: backup parado sem ninguem ver e' o risco que a tela existe para mostrar.
    A pasta externa NAO e' lida aqui: um compartilhamento fora do ar travaria a tela.
    """
    stats = _snapshots_locais(local)
    ultimo = max(stats, key=lambda s: s.st_mtime) if stats else None
    ultimo_em = datetime.datetime.fromtimestamp(ultimo.st_mtime, datetime.timezone.utc) if ultimo else None
    e = estado()  # com o que so' se sabe na leitura (copia dos arquivos sem terminar, worker parado)
    snap_erro_em, snap_erro = _erro_para_tela(e["ultimo_snapshot_erro"], "não foi possível gravar o snapshot")
    copia_erro_em, copia_erro = _erro_para_tela(e["ultima_copia_externa_erro"],
                                                "não foi possível fazer a cópia externa")
    arq_erro_em, arq_erro = _erro_dos_arquivos(e["ultima_copia_arquivos_erro"])
    arq_ext_erro_em, arq_ext_erro = _erro_dos_arquivos(e["ultima_copia_externa_arquivos_erro"])
    from app import copia_dono  # import tardio: copia_dono importa este modulo
    dono_em, dono_erro = _erro_dos_arquivos(e["ultima_copia_dono_erro"])  # frase nossa (_motivo), sem caminho
    dono_ultima = copia_dono.ultima_copia(local)
    dono_ok = copia_dono.configurada(local.parent.parent)  # backups -> dados -> <raiz>
    return {
        "ultimo_snapshot": e["ultimo_snapshot"],
        "ultimo_snapshot_erro": snap_erro,
        "ultimo_snapshot_erro_em": snap_erro_em,
        "ultima_copia_externa": e["ultima_copia_externa"],
        "ultima_copia_externa_erro": copia_erro,
        "ultima_copia_externa_erro_em": copia_erro_em,
        # issue #55: as pastas de PASTAS_ARQUIVOS (local e, havendo, externa)
        "ultima_copia_arquivos": e["ultima_copia_arquivos"],
        "ultima_copia_arquivos_erro": arq_erro,
        "ultima_copia_arquivos_erro_em": arq_erro_em,
        "ultima_copia_externa_arquivos": e["ultima_copia_externa_arquivos"],
        "ultima_copia_externa_arquivos_erro": arq_ext_erro,
        "ultima_copia_externa_arquivos_erro_em": arq_ext_erro_em,
        # issue #419: copia cifrada semanal para a chave do dono (a data vem do DISCO)
        "ultima_copia_dono": tempo.para_local(dono_ultima).isoformat(timespec="seconds") if dono_ultima else None,
        "ultima_copia_dono_erro": dono_erro,
        "ultima_copia_dono_erro_em": dono_em,
        "copia_dono_configurada": dono_ok,
        "copia_dono_atrasada": dono_ok and copia_dono.atrasada(local, agora),
        "ultimo_backup": tempo.para_local(ultimo_em).isoformat(timespec="seconds") if ultimo_em else None,
        "tamanho_bytes": ultimo.st_size if ultimo else None,
        "guardados": len(stats),
        "copia_externa_configurada": externa_configurada,
        "atrasado": ultimo_em is None or agora - ultimo_em > ATRASO_MAX,
    }


def agendar_backup_horario(origem_db: Path, pasta_destino: Path,
                           pasta_externa: Path | None = None) -> threading.Thread:
    def loop():
        while True:  # primeira rodada no boot, nao uma hora depois
            try:
                rodada(origem_db, pasta_destino, pasta_externa)
            except Exception:  # rede de seguranca: a thread de backup nunca morre
                log.exception("rodada de backup falhou fora do previsto")
            _acordar_arquivos.set()  # passada dos arquivos logo depois do snapshot
            try:  # issue #419: copia do dono, uma por semana (sem chave publica, nao faz nada)
                from app import copia_dono
                copia_dono.rodada_semanal(pasta_destino.parent.parent, pasta_destino)
            except Exception:
                log.exception("rodada da copia do dono falhou fora do previsto")
            try:
                _supervisionar_arquivos(origem_db, pasta_destino, pasta_externa)
            except Exception:
                log.exception("supervisao do worker dos arquivos falhou")
            time.sleep(3600)

    _iniciar_worker_arquivos(origem_db, pasta_destino, pasta_externa)
    t = threading.Thread(target=loop, daemon=True, name="backup")
    t.start()
    return t
