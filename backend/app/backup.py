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
import io
import json
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
# sha256 (`usuario-<id>`, trocada pela pessoa): o backup guarda a ultima de cada um no nome ativo (ver `_copiar_um`)
# e cada versao pelo sha256 (`usuario-<id>.<sha256>`, ver `_guardar_versao_assinatura`; #479).
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
                "ultima_copia_dono": None, "ultima_copia_dono_erro": None,
                "ultimo_envio_copia_dono": None, "ultimo_envio_copia_dono_erro": None}

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
                    conferir_estes: set[str] | None = None, falhos: set[str] | None = None,
                    pastas: tuple[str, ...] = PASTAS_ARQUIVOS, restauracao: bool = False) -> int:
    """Copia `raiz_origem/<pasta>/*` para `raiz_destino/<pasta>/` nas `pastas` (PASTAS_ARQUIVOS).

    Serve aos dois sentidos: backup (dados -> backups/arquivos) e restauracao
    (backups/arquivos -> dados, por `restaurar_arquivos`). So' copia o que falta no destino; nunca apaga nada.
    No backup, arquivo pelo sha256 que o backup tem e os dados nao tem mais e' erro da passada (#441), mesmo com a
    pasta recriada vazia: o sistema nao apaga esses arquivos, e o snapshot cita o que sumiu. Pasta que nunca existiu
    (nada gravado nela ainda) nao e' erro.
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
    ErroArquivo com os que ficaram sem copia, por pasta e motivo (o nome de cada um vai so' ao log:
    o health e a tela nao mostram caminho nem hash). Devolve quantos arquivos copiou.
    """
    conferir_estes = conferir_estes or set()
    copiados = 0
    falhas: dict[str, list[str]] = {}  # pasta -> motivo de cada arquivo sem copia
    faltando: dict[str, int] = {}      # pasta -> arquivos pelo sha256 do backup que nao estao mais nos dados
    ilegiveis: dict[str, str] = {}     # pasta -> motivo de nao conseguir listar o backup dela (#479)
    agora = time.time()
    for nome in pastas:
        origem = raiz_origem / nome
        destino = raiz_destino / nome
        nos_dados: set[str] = set()
        if origem.is_dir():
            destino.mkdir(parents=True, exist_ok=True)
            _limpar_parciais_abandonados(destino, agora)
        for arquivo in origem.iterdir() if origem.is_dir() else ():  # sem ordenar: a ordem nao importa
            if not arquivo.is_file() or arquivo.name.endswith(".tmp"):
                continue
            nos_dados.add(arquivo.name)
            rel = f"{nome}/{arquivo.name}"
            try:
                if not restauracao and nome == "assinaturas" and _NOME_ASSINATURA.fullmatch(arquivo.name):
                    copiados += _copiar_assinatura(arquivo, destino, conferir or rel in conferir_estes)
                elif _copiar_um(arquivo, destino / arquivo.name, conferir or rel in conferir_estes):
                    copiados += 1
            except OSError as e:
                log.warning("arquivo sem copia: %s -> %s", arquivo, destino, exc_info=True)
                falhas.setdefault(nome, []).append(_motivo(e))
                if falhos is not None:
                    falhos.add(rel)
        if restauracao:
            continue
        try:
            sumidos = _sumidos_dos_dados(destino, nos_dados)
        except OSError as e:
            log.error("backup de %s ilegivel: nao da' para saber se algo sumiu dos dados", nome, exc_info=True)
            ilegiveis[nome] = _motivo(e)
            continue
        if sumidos:
            log.error("%d arquivo(s) de %s estao no backup e nao nos dados: %s", len(sumidos), nome, sorted(sumidos)[:20])
            faltando[nome] = len(sumidos)
    partes = [f"{n} arquivo(s) de {nome} estão no backup e sumiram dos dados" for nome, n in sorted(faltando.items())]
    partes += [f"não foi possível ler o backup de {nome} ({motivo})" for nome, motivo in sorted(ilegiveis.items())]
    if falhas:
        total = sum(len(m) for m in falhas.values())
        por_pasta = ", ".join(f"{nome} {len(m)} ({'; '.join(sorted(set(m)))})" for nome, m in sorted(falhas.items()))
        partes.append(f"{total} arquivo(s) sem cópia: {por_pasta}")
    if partes:
        raise ErroArquivo("; ".join(partes))
    return copiados


def _sumidos_dos_dados(backup_da_pasta: Path, nos_dados: set[str]) -> set[str]:
    """Nomes pelo sha256 (`<sha256>.<ext>`) que o backup guardou e que nao estao nos dados. O sistema nao apaga esses
    arquivos (#441): faltar um e' disco perdido, pasta apagada ou recriada vazia, e o snapshot cita o que sumiu.
    Temporario, `desktop.ini` e qualquer nome fora do padrao nao contam. So' a pasta do backup que nao existe vale
    como vazia; erro de leitura (acesso negado no compartilhamento) sobe e vira erro da passada (#479): "nada sumiu"
    dito sem ler apagaria o alarme anterior."""
    try:
        backup_da_pasta.stat()
    except FileNotFoundError:
        return set()
    return {a.name for a in backup_da_pasta.iterdir()
            if a.name not in nos_dados and _NOME_SHA_COM_EXT.fullmatch(a.name) and a.is_file()}


# Assinatura de quem envia (`assinaturas/usuario-<id>`): o nome nao e' o sha256 e a pessoa troca ou tira a dela.
_NOME_ASSINATURA = re.compile(r"usuario-(\d+)")


def _copiar_assinatura(arquivo: Path, destino: Path, conferir: bool = False) -> int:
    """Leva ao backup a assinatura `usuario-<id>` (#479): cada versao fica pelo sha256 (`usuario-<id>.<sha256>`,
    imutavel) e o nome ativo e' a copia da atual. A restauracao acha pela versao a que valia no snapshot escolhido,
    mesmo depois de a pessoa trocar.

    Le a assinatura dos dados uma vez so' (tem ate' 1 MB): versao e nome ativo saem dos mesmos bytes, mesmo que a
    pessoa troque no meio. Antes de trocar o nome ativo do backup, o conteudo dele vira versao (o backup de antes das
    versoes so' tem o nome ativo: sem isso, a assinatura antiga se perderia na primeira troca). So' a assinatura que
    sumiu dos dados antes da leitura (a pessoa tirou) e' pulada; qualquer falha depois dela sobe. Devolve quantos
    arquivos gravou no backup."""
    try:
        conteudo = arquivo.read_bytes()
    except FileNotFoundError:
        return 0                # a pessoa tirou a assinatura no meio da passada: nada a guardar
    sha = hashlib.sha256(conteudo).hexdigest()
    ativo = destino / arquivo.name
    try:
        anterior = ativo.read_bytes()
    except FileNotFoundError:
        anterior = None
    sha_anterior = hashlib.sha256(anterior).hexdigest() if anterior is not None else None
    gravados = 0
    if anterior is not None and sha_anterior != sha:
        gravados += _guardar_versao_assinatura(anterior, sha_anterior, ativo, conferir)
    gravados += _guardar_versao_assinatura(conteudo, sha, ativo, conferir)
    if sha_anterior != sha:
        _gravar_conferido(conteudo, sha, ativo)
        gravados += 1
    return gravados


def _guardar_versao_assinatura(conteudo: bytes, sha: str, ativo: Path, conferir: bool) -> bool:
    """`usuario-<id>.<sha256>` ao lado do nome ativo do backup. Como nas pastas pelo sha256, mesmo nome e tamanho
    contam como presente; com `conferir` (a releitura diaria), a versao guardada e' relida. False se ja' estava la'."""
    alvo = ativo.with_name(f"{ativo.name}.{sha}")
    if alvo.is_file() and (_sha256(alvo) == sha if conferir else alvo.stat().st_size == len(conteudo)):
        return False
    _gravar_conferido(conteudo, sha, alvo)
    return True


def _gravar_conferido(conteudo: bytes, sha: str, alvo: Path) -> None:
    """Grava `conteudo` em `alvo` pelo mesmo protocolo de `_copiar_um`: parcial aberto, fsync, conferido pelo sha256,
    so' entao renomeado (ou aparece inteiro, ou nao aparece)."""
    parcial = alvo.parent / f"{alvo.name}.{os.getpid()}-{threading.get_ident()}-{secrets.token_hex(4)}.tmp"
    try:
        with open(parcial, "xb") as saida:
            shutil.copyfileobj(io.BytesIO(conteudo), saida)
            saida.flush()
            os.fsync(saida.fileno())
            if _sha256(parcial) != sha:
                raise ErroArquivo("cópia conferida diferente da original")
        parcial.replace(alvo)
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise


def _assinaturas_do_banco(banco: Path) -> dict[str, dict]:
    """usuario_id -> `depois` do ultimo evento `correio.assinatura` do banco (sha256 da gravada, ou removida)."""
    conn = sqlite3.connect(f"file:{banco}?mode=ro", uri=True)
    try:
        linhas = conn.execute("SELECT entidade_id, depois FROM audit_log WHERE acao='correio.assinatura' "
                              "AND entidade='usuario' ORDER BY id").fetchall()
    finally:
        conn.close()
    return {str(uid): json.loads(depois or "{}") for uid, depois in linhas if str(uid).isdigit()}


def _sha_ou_nada(arquivo: Path) -> str | None:
    return _sha256(arquivo) if arquivo.is_file() else None


def _restaurar_assinaturas(origem: Path, destino: Path, banco: Path) -> tuple[int, int, list[str]]:
    """Reconcilia `dados/assinaturas` com o banco restaurado (#441). Parte dos eventos `correio.assinatura` do banco,
    nao dos arquivos: para cada pessoa, no nome ativo (`usuario-<id>`) fica so' a imagem com o sha256 do ultimo evento
    dela, a que ja' esta' em `dados` ou a do backup. A que diverge, a de quem tirou a assinatura e a de quem o banco
    nao conhece vao para `assinaturas/quarentena-<data>/` (nada se apaga); o e-mail nao sai com uma imagem que nao e' a
    vigente. Um problema numa pessoa nao para as outras. Devolve (copiadas do backup, postas em quarentena, motivos de
    quem ficou sem a assinatura vigente)."""
    vigentes = _assinaturas_do_banco(banco)
    quarentena = destino / f"quarentena-{tempo.para_local(tempo.agora_utc()):%Y%m%d}"
    copiadas = isoladas = 0
    motivos: list[str] = []

    def isolar(arquivo: Path) -> None:
        nonlocal isoladas
        quarentena.mkdir(parents=True, exist_ok=True)
        os.replace(arquivo, quarentena / f"{arquivo.name}.{secrets.token_hex(4)}")
        log.warning("assinatura que nao e' a vigente no banco restaurado foi para a quarentena: %s", arquivo.name)
        isoladas += 1

    ativas = {m[1] for a in (destino.iterdir() if destino.is_dir() else ())
              if (m := _NOME_ASSINATURA.fullmatch(a.name)) and a.is_file()}
    for uid in sorted(set(vigentes) | ativas, key=int):
        ativo, do_backup = destino / f"usuario-{uid}", origem / f"usuario-{uid}"
        evento = vigentes.get(uid) or {}
        esperado = None if evento.get("removida") else evento.get("sha256")
        try:
            atual = _sha_ou_nada(ativo)
            if atual is not None and atual != esperado:
                isolar(ativo)
                atual = None
            if esperado is None or atual == esperado:
                continue
            # a versao pelo sha256 primeiro (#479: a que valia no snapshot, mesmo que a pessoa tenha trocado depois);
            # o nome ativo do backup serve aos backups de antes das versoes
            versao = origem / f"usuario-{uid}.{esperado}" if _NOME_SHA.fullmatch(str(esperado)) else None
            fonte = next((f for f in (versao, do_backup) if f is not None and _sha_ou_nada(f) == esperado), None)
            if fonte is None:
                motivos.append(f"usuário {uid}: nenhuma cópia tem a assinatura vigente no banco")
                continue
            destino.mkdir(parents=True, exist_ok=True)
            copiadas += _copiar_um(fonte, ativo, conferir=True)
        except OSError as e:
            log.warning("assinatura do usuario %s nao reconciliada", uid, exc_info=True)
            motivos.append(f"usuário {uid}: {_motivo(e)}")
    return copiadas, isoladas, motivos


def restaurar_arquivos(raiz_backup: Path, dados: Path, banco: Path | None = None) -> int:
    """Passo 5 do runbook: devolve a `dados` os arquivos do backup, conferidos pelo sha256, sem apagar nada.

    As pastas pelo sha256 voltam inteiras (`copiar_arquivos` com conferir). As assinaturas sao reconciliadas com o
    banco restaurado (`banco`, padrao `dados/dashboard.db`, que o passo anterior ja' devolveu; ver
    `_restaurar_assinaturas`). Devolve quantos arquivos copiou; o que nao se resolveu sobe ErroArquivo no fim."""
    banco = banco or dados / "dashboard.db"
    erros: list[str] = []
    copiados = 0
    try:
        copiados = copiar_arquivos(raiz_backup, dados, conferir=True, restauracao=True,
                                   pastas=tuple(p for p in PASTAS_ARQUIVOS if p != "assinaturas"))
    except ErroArquivo as e:
        erros.append(str(e))
    try:
        n, isoladas, motivos = _restaurar_assinaturas(raiz_backup / "assinaturas", dados / "assinaturas", banco)
        copiados += n
        if isoladas:
            log.warning("%d assinatura(s) foram para a quarentena (nao sao as vigentes no banco restaurado)", isoladas)
        if motivos:
            erros.append(f"{len(motivos)} assinatura(s) sem a vigente: {'; '.join(motivos)}")
    except (OSError, sqlite3.Error, ValueError) as e:  # ValueError: `depois` que nao e' JSON
        log.exception("assinaturas nao restauradas")
        erros.append(f"assinaturas não devolvidas ({_motivo(e)})")
    if erros:
        raise ErroArquivo("; ".join(erros))
    return copiados


# `<nome>.<pid>-<thread>-<aleatorio>.tmp`: so' o que _copiar_um cria. PID, thread e sufixo
# aleatorio no nome: duas copias (outro processo, outra thread) nunca escrevem no mesmo parcial.
_PARCIAL_NOSSO = re.compile(r"\.\d+-\d+-[0-9a-f]{8}\.tmp$")
_NOME_SHA = re.compile(r"[0-9a-f]{64}")
_NOME_SHA_COM_EXT = re.compile(r"[0-9a-f]{64}\.[a-z0-9]{1,5}")  # como `arquivos.gravar_bytes` nomeia


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
        if not conferir and com_sha:
            # o nome e' o sha256 do conteudo: mesmo nome e mesmo tamanho = mesmo arquivo. Nome que nao e' o sha256
            # (a assinatura, trocada pela pessoa; #441) e' sempre comparado pelo conteudo
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
    envio_em, envio_erro = _erro_dos_arquivos(e.get("ultimo_envio_copia_dono_erro"))  # frase nossa, sem caminho
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
        # issue #420: o envio dessa copia por e-mail (so' desta execucao do servidor)
        "ultimo_envio_copia_dono": e.get("ultimo_envio_copia_dono"),
        "ultimo_envio_copia_dono_erro": envio_erro,
        "ultimo_envio_copia_dono_erro_em": envio_em,
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
            try:  # issue #419: copia do dono, uma por semana (sem chave publica, nao faz nada); #420: e o e-mail
                from app import copia_dono_envio
                copia_dono_envio.rodada_semanal(pasta_destino.parent.parent, pasta_destino)
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
