"""Sentinela do log de seguranca do Windows (issue #423).

A cada 5 minutos, so' no Windows e fora de dev, le o log de Seguranca com `wevtutil` (sem dependencia nova) a partir
do ultimo `EventRecordID` lido e transforma o que importa em linhas `seguranca.sentinela` da auditoria, que
`app/seguranca.py` mostra no bloco Seguranca por 7 dias. Confere tambem, com `auditpol` e a leitura da SACL, que a
auditoria de arquivos continua ligada e que as pastas `dados`, `segredos` e `cadastro` continuam com a SACL.

Eventos: 4663 (acesso a arquivo nas tres pastas, agrupado por conta, processo, pasta e hora), 4670 (permissao trocada),
4672 (logon com privilegio, conta fora da lista), 4698 a 4702 (tarefa `DashboardLotufo*`), 1102 (log limpo) e 4719
(politica de auditoria alterada). Pre-requisitos na VM e limites: docs/runbook.md, secao "Sentinela".

Estado (`<raiz>\\dados\\sentinela.json`): ultimo EventRecordID lido, contas de 4672 ja avisadas no dia e as verificacoes
que estao falhando (cada uma vira item uma vez, quando comeca a falhar). Lista de contas e processos conhecidos
(`<raiz>\\segredos\\sentinela.json`, fora do repositorio): `{"contas": [...], "processos": [...]}`.
"""
import csv
import datetime
import io
import json
import logging
import os
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from app import auditoria, db, tempo

log = logging.getLogger("app.sentinela")

INTERVALO_SEG = 300
ACAO = "seguranca.sentinela"
PASTAS = ("dados", "segredos", "cadastro")
NIVEL_PASTA = {"dados": "critico", "segredos": "critico", "cadastro": "acao"}
MAX_EVENTOS = 5000
ACAO_PONTO = "seguranca.sentinela.ponto"
TEMPO_LIMITE_SEG = 60

NAO_RODA = "Sentinela não roda neste ambiente"

# Subcategorias pelo GUID: o Windows do servidor esta em portugues
GUID_ARQUIVOS = "{0CCE921D-69AE-11D9-BED3-505054503030}"
GUID_POLITICA = "{0CCE922F-69AE-11D9-BED3-505054503030}"
# INTERATIVO e REDE: quem entrou na VM e quem leu pela rede; SYSTEM (servidor, antivirus, backup) fica de fora
DIREITO_DELETE = 0x10000
SIDS_SACL = ("S-1-5-4", "S-1-5-2")
_COM_EXITO = ("success", "xito", "sucesso")

_TAREFAS = {"4698", "4699", "4700", "4701", "4702"}
_ID_TAREFA = {"4698": "criada", "4699": "apagada", "4700": "habilitada", "4701": "desabilitada", "4702": "alterada"}
_EVENTOS = ("4663", "4670", "4672", "4698", "4699", "4700", "4701", "4702", "1102", "4719")
_CONTAS_DE_SISTEMA = {"system", "local service", "network service", "servico local", "serviço local",
                      "servico de rede", "serviço de rede", "anonymous logon", "logon anônimo"}
_PREFIXOS_SISTEMA = ("dwm-", "umfd-", "font driver host")


def ativo() -> bool:
    """Roda so' no Windows e fora de dev."""
    return sys.platform == "win32" and os.environ.get("DASH_DEV") != "1"


def situacao() -> dict:
    """O que Saude mostra: roda ou nao neste ambiente."""
    return {"roda": ativo(), "mensagem": None if ativo() else NAO_RODA}


def raiz() -> Path:
    """`<raiz>`: a pasta acima de `dados`, onde mora o banco."""
    return db.db_path().parent.parent


def _arquivo_estado() -> Path:
    return db.db_path().parent / "sentinela.json"


def _arquivo_lista() -> Path:
    return raiz() / "segredos" / "sentinela.json"


def _ler_json(caminho: Path) -> dict:
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _gravar_estado(estado: dict) -> None:
    destino = _arquivo_estado()
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp, destino)


def _executar(args: list[str]) -> tuple[int, str]:
    """Roda um programa do Windows e devolve (codigo, saida). Os testes trocam esta funcao."""
    p = subprocess.run(args, capture_output=True, timeout=TEMPO_LIMITE_SEG)
    return p.returncode, p.stdout.decode("utf-8", errors="replace")


# --- leitura dos eventos ---------------------------------------------------------------------------------------

def _sem_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _instante(texto: str | None) -> datetime.datetime | None:
    if not texto:
        return None
    base = texto.rstrip("Z")
    if "." in base:
        inteiro, frac = base.split(".", 1)
        base = f"{inteiro}.{frac[:6]}"
    return datetime.datetime.fromisoformat(base).replace(tzinfo=datetime.timezone.utc)


def eventos(xml: str) -> list[dict]:
    """O XML do `wevtutil qe /f:xml` (varios `<Event>` sem raiz) -> `[{id, registro, quando, dados}]`. `dados` reune os
    `<Data Name=...>` do EventData e, nos eventos que usam UserData (1102), as folhas dele."""
    if not xml.strip():
        return []
    raiz_xml = ET.fromstring(f"<Eventos>{xml}</Eventos>")
    out = []
    for ev in raiz_xml:
        id_ = registro = quando = None
        dados: dict[str, str] = {}
        for filho in ev:
            nome = _sem_ns(filho.tag)
            if nome == "System":
                for s in filho:
                    n = _sem_ns(s.tag)
                    if n == "EventID":
                        id_ = (s.text or "").strip()
                    elif n == "EventRecordID":
                        registro = int((s.text or "0").strip())
                    elif n == "TimeCreated":
                        quando = _instante(s.get("SystemTime"))
            elif nome == "EventData":
                for d in filho:
                    if d.get("Name"):
                        dados[d.get("Name")] = (d.text or "").strip()
            elif nome == "UserData":
                for d in filho.iter():
                    if len(d) == 0 and d is not filho and (d.text or "").strip():
                        dados[_sem_ns(d.tag)] = d.text.strip()
        if id_ is not None and registro is not None and quando is not None:
            out.append({"id": id_, "registro": registro, "quando": quando, "dados": dados})
    return out


def _conta(d: dict) -> str:
    dominio, nome = d.get("SubjectDomainName", ""), d.get("SubjectUserName", "")
    return f"{dominio}\\{nome}" if dominio and nome else nome


def _pasta_do_objeto(objeto: str, base: Path) -> str | None:
    """'segredos' se `objeto` esta em `<raiz>\\segredos`, etc.; None fora das tres pastas."""
    norma = objeto.replace("/", "\\").rstrip("\\").casefold()
    for p in PASTAS:
        alvo = str(base / p).replace("/", "\\").rstrip("\\").casefold()
        if norma == alvo or norma.startswith(alvo + "\\"):
            return p
    return None


def _processo(caminho: str) -> str:
    return caminho.replace("/", "\\").rsplit("\\", 1)[-1] or "desconhecido"


def _conhecida(conta: str, contas: set[str]) -> bool:
    return conta.casefold() in contas or conta.rsplit("\\", 1)[-1].casefold() in contas


def _conta_de_sistema(d: dict) -> bool:
    nome = d.get("SubjectUserName", "").casefold()
    sid = d.get("SubjectUserSid", "")
    return (not nome or nome.endswith("$") or nome in _CONTAS_DE_SISTEMA or nome.startswith(_PREFIXOS_SISTEMA)
            or sid in ("S-1-5-18", "S-1-5-19", "S-1-5-20"))


def _achado(evento, nivel, mensagem, hora, conta=None, processo=None, pasta=None, quantidade=1) -> dict:
    return {"evento": evento, "nivel": nivel, "mensagem": mensagem, "conta": conta, "processo": processo,
            "pasta": pasta, "quantidade": quantidade, "hora": hora}


def mensagem_leitura(pasta: str, processo: str, conta: str, n: int) -> str:
    return f"Leitura de {pasta} por {processo} ({conta}), {n} arquivo{'' if n == 1 else 's'}"


def achados(evs: list[dict], base: Path, lista: dict, avisados: dict[str, list[str]]) -> list[dict]:
    """Os eventos viram achados `{evento, nivel, mensagem, conta, processo, pasta, quantidade, hora}`. `avisados` (dia
    -> contas de 4672 ja avisadas) e' atualizado aqui. 4663 de conta E processo da lista nao vira item."""
    contas = {str(c).casefold() for c in lista.get("contas", [])}
    processos = {str(p).casefold() for p in lista.get("processos", [])}
    grupos: dict[tuple, dict] = {}
    out: list[dict] = []
    for e in evs:
        d, id_, quando = e["dados"], e["id"], e["quando"]
        hora = quando.strftime("%Y-%m-%dT%H:%M:%SZ")
        conta = _conta(d)
        if id_ == "4663":
            pasta = _pasta_do_objeto(d.get("ObjectName", ""), base)
            if pasta is None:
                continue
            proc = _processo(d.get("ProcessName", ""))
            if _conhecida(conta, contas) and proc.casefold() in processos:
                continue
            g = grupos.setdefault((conta.casefold(), proc.casefold(), pasta, quando.strftime("%Y-%m-%dT%H")),
                                  _achado(4663, NIVEL_PASTA[pasta], "", hora, conta, proc, pasta))
            g.setdefault("arquivos", set()).add(d.get("ObjectName", "").casefold())
        elif id_ == "4670":
            pasta = _pasta_do_objeto(d.get("ObjectName", ""), base)
            if pasta is None:
                continue
            proc = _processo(d.get("ProcessName", ""))
            out.append(_achado(4670, "critico", f"Permissão de {pasta} trocada por {proc} ({conta})", hora,
                               conta, proc, pasta))
        elif id_ == "4672":
            if _conta_de_sistema(d) or _conhecida(conta, contas):
                continue
            dia = tempo.para_local(quando).date().isoformat()
            if conta.casefold() in avisados.setdefault(dia, []):
                continue
            avisados[dia].append(conta.casefold())
            out.append(_achado(4672, "atencao", f"Logon com privilégio de administrador por conta fora da lista "
                                                f"({conta})", hora, conta))
        elif id_ in _TAREFAS:
            nome = d.get("TaskName", "").lstrip("\\")
            if nome.startswith("DashboardLotufo"):
                out.append(_achado(int(id_), "critico", f"Tarefa {nome} {_ID_TAREFA[id_]} por {conta}", hora, conta))
        elif id_ == "1102":
            out.append(_achado(1102, "critico", f"Log de segurança do Windows limpo por {conta}", hora, conta))
        elif id_ == "4719":
            out.append(_achado(4719, "critico", f"Política de auditoria do Windows alterada por {conta}", hora, conta))
    for g in grupos.values():
        n = len(g.pop("arquivos"))
        g["quantidade"] = n
        g["mensagem"] = mensagem_leitura(g["pasta"], g["processo"], g["conta"], n)
        out.append(g)
    return out


# --- leitura do log e verificacoes -----------------------------------------------------------------------------

def _consulta(maior_que: int) -> str:
    ids = " or ".join(f"EventID={i}" for i in _EVENTOS)
    return f"*[System[({ids}) and EventRecordID>{maior_que}]]"


def _ultimo_registro() -> int:
    """O maior EventRecordID do log (qualquer evento); 0 com o log vazio."""
    codigo, saida = _executar(["wevtutil", "qe", "Security", "/c:1", "/rd:true", "/f:xml"])
    if codigo != 0:
        raise RuntimeError(f"wevtutil terminou com código {codigo}")
    return max((e["registro"] for e in eventos(saida)), default=0)


def _ler_eventos(maior_que: int) -> list[dict]:
    codigo, saida = _executar(["wevtutil", "qe", "Security", f"/q:{_consulta(maior_que)}", f"/c:{MAX_EVENTOS}",
                               "/f:xml"])
    if codigo != 0:
        raise RuntimeError(f"wevtutil terminou com código {codigo}")
    return eventos(saida)


def _auditoria_ligada(guid: str) -> bool:
    codigo, saida = _executar(["auditpol", "/get", f"/subcategory:{guid}", "/r"])
    if codigo != 0:
        raise RuntimeError(f"auditpol terminou com código {codigo}")
    for linha in csv.reader(io.StringIO(saida)):
        celulas = [c.strip() for c in linha]
        for i, c in enumerate(celulas):
            if c.casefold() == guid.casefold() and i + 1 < len(celulas):
                return any(m in celulas[i + 1].casefold() for m in _COM_EXITO)
    raise RuntimeError("saída do auditpol sem a subcategoria")


_LER_SACL = ("(Get-Acl -LiteralPath '{pasta}' -Audit).Audit | ForEach-Object {{ "
             "$_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value + '|' + "
             "$_.AuditFlags + '|' + [int]$_.FileSystemRights }}")


def _sacl_no_lugar(pasta: Path) -> bool:
    """A SACL da pasta tem INTERATIVO e REDE com auditoria de exito."""
    codigo, saida = _executar(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                               _LER_SACL.format(pasta=str(pasta).replace("'", "''"))])
    if codigo != 0:
        raise RuntimeError(f"powershell terminou com código {codigo}")
    com_exito = set()
    for linha in saida.splitlines():
        sid, _, resto = linha.strip().partition("|")
        flags, _, direitos = resto.partition("|")
        # Delete (0x10000) tem que estar no direito auditado: apagar o estado da sentinela gera evento
        if "success" in flags.casefold() and direitos.strip().isdigit() and int(direitos) & DIREITO_DELETE:
            com_exito.add(sid)
    return all(s in com_exito for s in SIDS_SACL)


def verificacoes(base: Path) -> dict[str, tuple[str, str]]:
    """O que esta errado agora: `{chave: (nivel, mensagem)}`. Verificacao que nao consegue rodar vira atencao."""
    falhas: dict[str, tuple[str, str]] = {}
    for chave, guid, texto, nome in (("auditoria-arquivos", GUID_ARQUIVOS, "Auditoria de arquivos desligada",
                                "a auditoria de arquivos"),
                               ("auditoria-politica", GUID_POLITICA, "Auditoria da alteração da política desligada",
                                "a auditoria da alteração da política")):
        try:
            if not _auditoria_ligada(guid):
                falhas[chave] = ("critico", texto)
        except Exception as e:
            log.warning("sentinela: nao conferiu %s: %s", chave, e)
            falhas[chave] = ("atencao", f"Sentinela não conseguiu conferir {nome}")
    for pasta in PASTAS:
        caminho = base / pasta
        if not caminho.is_dir():
            continue
        try:
            if not _sacl_no_lugar(caminho):
                falhas[f"sacl-{pasta}"] = ("critico", f"SACL ausente em {pasta}")
        except Exception as e:
            log.warning("sentinela: nao leu a SACL de %s: %s", pasta, e)
            falhas[f"sacl-{pasta}"] = ("atencao", f"Sentinela não conseguiu ler a SACL de {pasta}")
    return falhas


# --- a rodada --------------------------------------------------------------------------------------------------

def _ponto_gravado(conn) -> int | None:
    """Onde a leitura do log parou, gravado no banco (fonte da verdade); None = nunca leu o log com sucesso.
    O `sentinela.json` e' so' uma copia: apaga-lo ou edita-lo nao faz a sentinela pular eventos."""
    r = conn.execute("SELECT depois FROM audit_log WHERE acao=? ORDER BY id DESC LIMIT 1", (ACAO_PONTO,)).fetchone()
    if r is None:
        return None
    try:
        return int(json.loads(r["depois"])["ultimo_registro"])
    except (ValueError, KeyError, TypeError):
        return None


def rodada(conn) -> int:
    """Uma rodada. Devolve quantos achados novos gravou. Leitura do log ou verificacao que falha vira item uma vez,
    ate' voltar ao normal (regravada uma vez por dia enquanto durar). Achados e ponto de leitura entram na mesma
    transacao, entao nenhum evento e' lido sem ser gravado nem gravado sem avancar o ponto."""
    base = raiz()
    estado = _ler_json(_arquivo_estado())
    ponto = _ponto_gravado(conn)
    ultimo = ponto
    agora = tempo.agora_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    # falhas em aberto: chave -> ultimo dia (local) em que virou item; regravada 1x por dia enquanto durar, para nao
    # sumir da Saude ao fim dos 7 dias com a sentinela ainda cega
    pendencias = estado.get("pendencias", {})
    if not isinstance(pendencias, dict):
        pendencias = {k: "" for k in pendencias}
    avisados = {k: list(v) for k, v in estado.get("avisados_4672", {}).items()}
    lista = _ler_json(_arquivo_lista())
    novos: list[dict] = []
    atuais: dict[str, tuple[str, str]] = {}
    copia = estado.get("ultimo_registro")
    if ponto is not None and (not isinstance(copia, int) or copia > ponto):
        # a copia no arquivo sumiu, ficou ilegivel ou aponta alem do que a sentinela gravou: a leitura segue do ponto
        # gravado no banco (nada se perde) e o fato vira item, uma vez (a copia e' refeita no fim da rodada)
        novos.append(_achado("estado-perdido", "critico", "Estado da sentinela apagado, ilegível ou alterado; "
                             "leitura retomada do ponto gravado no banco", agora))
    try:
        no_log = _ultimo_registro()
        if ultimo is None:
            ultimo = no_log          # primeira leitura com sucesso: marca o ponto de partida, nao le o historico
        elif no_log < ultimo:
            ultimo = 0               # log limpo ou reiniciado: le tudo o que ha
        if no_log > ultimo:
            evs = _ler_eventos(ultimo)
            novos += achados(evs, base, lista, avisados)
            ultimo = max([ultimo] + [e["registro"] for e in evs])
    except Exception as e:
        log.warning("sentinela: nao leu o log de seguranca: %s", e)
        atuais["leitura-log"] = ("atencao", "Sentinela não conseguiu ler o log de segurança")
    atuais.update(verificacoes(base))
    hoje = tempo.hoje_local()
    for chave, (nivel, msg) in atuais.items():
        if pendencias.get(chave) != hoje.isoformat():
            novos.append(_achado(chave, nivel, msg, agora))
    with db.mutacao(conn):
        for a in novos:
            auditoria.registrar(conn, None, ACAO, "sentinela", None, None, a)
        if ultimo is not None and ultimo != ponto:
            auditoria.registrar(conn, None, ACAO_PONTO, "sentinela", None, None, {"ultimo_registro": ultimo})
    recentes = {hoje.isoformat(), (hoje - datetime.timedelta(days=1)).isoformat()}
    _gravar_estado({"ultimo_registro": ultimo, "pendencias": {k: hoje.isoformat() for k in atuais},
                    "avisados_4672": {k: v for k, v in avisados.items() if k in recentes}})
    return len(novos)


def agendar(intervalo_seg: int = INTERVALO_SEG) -> threading.Thread | None:
    """Thread de 5 em 5 minutos. Fora do Windows ou em dev nao sobe."""
    if not ativo():
        return None

    def loop():
        while True:
            try:
                conn = db.get_conn()
                try:
                    rodada(conn)
                finally:
                    conn.close()
            except Exception:
                log.exception("rodada da sentinela falhou")
            time.sleep(intervalo_seg)

    t = threading.Thread(target=loop, name="sentinela", daemon=True)
    t.start()
    return t
