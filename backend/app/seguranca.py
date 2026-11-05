"""Seguranca do acesso (issue #418): os ultimos acessos de cada pessoa e o bloco Seguranca de Administracao > Saude.

O login (`api_auth.login`) grava no `depois` de `auth.login` e de `auth.login_falha` a origem (o IP da conexao, o
mesmo do limite por origem; X-Forwarded-For e' ignorado) e o navegador (User-Agent cortado em `NAVEGADOR_MAX`).
Aqui so' se le a auditoria: ela continua append-only e encadeada, sem coluna nova.

`itens` monta o bloco Seguranca como uma lista de `{nivel, mensagem, data}`; as proximas verificacoes do plano de
protecao (integridade, sentinela, alertas) acrescentam itens a esta mesma lista.

Issue #422: `conferir`, de hora em hora (`agendar`), confere os gatilhos da migracao 062 em `usuarios` e `sessoes` e
a cadeia da auditoria; o que falhar vira item `critico` do bloco.
"""
import datetime
import hashlib
import json
import logging
import threading
import time

from app import auditoria, db, tempo

log = logging.getLogger(__name__)

NAVEGADOR_MAX = 200
ACESSOS_NA_TELA = 10
# Origem nova: login certo de administrador de uma origem que nao aparece nos logins certos dele nestes dias anteriores
JANELA_ORIGEM = datetime.timedelta(days=30)
# Quanto tempo o item fica no bloco depois do login que o criou
DURACAO_ITEM = datetime.timedelta(days=7)
# Teto da lista do bloco; o resto vira contagem (`bloco`)
ITENS_NA_TELA = 20

_UTC = datetime.timezone.utc
# A primeira marca que aparece decide: Edge e Opera tambem dizem "Chrome/", Chrome tambem diz "Safari/"
_NAVEGADORES = (("Edg/", "Edge"), ("EdgA/", "Edge"), ("EdgiOS/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                ("FxiOS/", "Firefox"), ("CriOS/", "Chrome"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
# iPhone e iPad dizem "like Mac OS X"; Android diz "Linux"
_SISTEMAS = (("iPhone", "iOS"), ("iPad", "iOS"), ("Android", "Android"), ("CrOS", "ChromeOS"), ("Windows", "Windows"),
             ("Macintosh", "macOS"), ("Mac OS X", "macOS"), ("Linux", "Linux"))
_OUTRO_MAX = 40

# Issue #422: os gatilhos da migracao 062, por tabela, e o sha256 do SQL deles em sqlite_master, com os espacos em
# branco reduzidos a um (o checkout no Windows pode trocar o fim de linha da migracao). Mudar um gatilho na migracao
# exige mudar aqui.
GATILHOS = {
    "usuarios": {
        "usuarios_protecao_insert": "00414b3b71696849914503d5894af5bd4b23629a94348823cd10e7a81d37a324",
        "usuarios_protecao_delete": "22bfe86500c5740e20926b446bd4c118a60c4542808b478347682dd471e4b2ed",
        "usuarios_protecao_update": "9004d8af32f3f6cd104da062e00f7695ac82c7baa0b690fba0ccfcd6cc25bf91",
    },
    "sessoes": {
        "sessoes_protecao_insert": "1fb59b90962caba5d0cb2e92dca17afb51357eb412f8dccd6aa285ac59b3ed50",
        "sessoes_protecao_delete": "3053dbf83ca811dade2c9d999f6f3c30a4144dd78a490d5619b3b646aaf25200",
        "sessoes_protecao_update": "76985d0862ba96542e03d0212a5d8ee2e5052c449885bcc4dd7ae80b75fadbfe",
    },
}
PROTECAO_REMOVIDA = "Proteção da tabela de usuários removida"
PROTECAO_SESSOES_REMOVIDA = "Proteção da tabela de sessões removida"
CADEIA_QUEBRADA = "Cadeia da auditoria quebrada"
_MENSAGENS = {"usuarios": PROTECAO_REMOVIDA, "sessoes": PROTECAO_SESSOES_REMOVIDA}
INTERVALO_CONFERENCIA_SEG = 3600
# O resultado da ultima conferencia (`conferir`), do processo: o bloco le daqui; reinicio refaz no boot (`agendar`)
_conferencia: list[dict] = []
# Uma conferencia por vez no processo (a do boot e uma chamada direta nao se cruzam)
_TRAVA = threading.Lock()


def navegador(user_agent: str | None) -> str | None:
    """O User-Agent que vai para a auditoria: cortado em `NAVEGADOR_MAX` (o cabecalho e' do cliente e nao tem teto)."""
    return user_agent[:NAVEGADOR_MAX] if user_agent else None


def resumir_navegador(user_agent: str | None) -> str | None:
    """'Chrome no Windows', 'Safari no iOS'... O que nao e' navegador conhecido (curl, script) aparece pelo primeiro
    pedaco do proprio User-Agent, que e' o que diz quem chamou."""
    if not user_agent or not user_agent.strip():
        return None
    nome = next((n for marca, n in _NAVEGADORES if marca in user_agent), None)
    if nome is None:
        return user_agent.split()[0][:_OUTRO_MAX]
    sistema = next((s for marca, s in _SISTEMAS if marca in user_agent), None)
    return f"{nome} no {sistema}" if sistema else nome


def acessos(conn, usuario_id: int, limite: int = ACESSOS_NA_TELA) -> list[dict]:
    """Os `limite` acessos mais recentes da pessoa, do mais novo ao mais antigo: os logins certos dela e as tentativas
    recusadas com o e-mail dela. A tentativa recusada nao tem usuario no evento (o login nao revela se a conta existe),
    entao entra pelo e-mail gravado; so' as de depois de a conta existir, para a conta nova nao herdar tentativas
    feitas antes com o mesmo e-mail. A fronteira e' o evento `usuario.criar` da conta (id, exclusivo: o carimbo tem
    precisao de segundo); conta criada fora da API, sem esse evento, usa o `criado_em` dela. Evento de antes do #418
    vem sem origem e sem navegador."""
    u = conn.execute("SELECT email, criado_em FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
    if u is None:
        return []
    criacao = conn.execute("SELECT MAX(id) FROM audit_log WHERE entidade='usuario' AND entidade_id=? "
                           "AND acao='usuario.criar'", (str(usuario_id),)).fetchone()[0]
    # `depois_da_conta` e' uma das duas frases fixas abaixo: a f-string nao ve entrada do cliente
    depois_da_conta, fronteira = ("id > ?", criacao) if criacao is not None else ("criado_em >= ?", u["criado_em"])
    linhas = conn.execute(
        "SELECT acao, depois, criado_em FROM audit_log WHERE (acao='auth.login' AND usuario_id=?) OR "
        f"(acao='auth.login_falha' AND json_extract(depois, '$.email')=? AND {depois_da_conta}) ORDER BY id DESC LIMIT ?",
        (usuario_id, u["email"], fronteira, limite)).fetchall()
    out = []
    for r in linhas:
        d = json.loads(r["depois"]) if r["depois"] else {}
        out.append({"data": tempo.iso_utc(r["criado_em"]), "sucesso": r["acao"] == "auth.login",
                    "origem": d.get("origem"), "navegador": resumir_navegador(d.get("navegador"))})
    return out


def _carimbo(dt: datetime.datetime) -> str:
    """Instante -> o formato do `criado_em` do SQLite (UTC), para comparar como texto no banco."""
    return dt.astimezone(_UTC).strftime("%Y-%m-%d %H:%M:%S")


def _origem_nova(conn, agora: datetime.datetime) -> list[dict]:
    """Login certo de administrador, nos ultimos `DURACAO_ITEM`, de uma origem que nao aparece nos logins certos
    dessa mesma pessoa nos `JANELA_ORIGEM` anteriores. Gate Sol S2: administrador e' o perfil NO MOMENTO do login,
    gravado no evento (quem e' promovido depois nao vira "Administrador entrou"; quem e' rebaixado depois nao esconde
    o acesso); login gravado antes disso cai no perfil de hoje. A origem vista conta qualquer login certo da pessoa,
    tambem os de antes de ela ser administradora. Login sem origem (antes do #418) nao gera item nem conta como vista."""
    desde = agora - DURACAO_ITEM - JANELA_ORIGEM
    ultimo: dict[tuple[int, str], datetime.datetime] = {}
    out = []
    for r in conn.execute(
            "SELECT a.usuario_id, a.criado_em, json_extract(a.depois, '$.origem') AS origem, "
            "COALESCE(json_extract(a.depois, '$.perfil'), u.perfil) AS perfil, u.nome FROM audit_log a "
            "JOIN usuarios u ON u.id = a.usuario_id WHERE a.acao='auth.login' "
            "AND a.criado_em >= ? AND a.criado_em <= ? ORDER BY a.id", (_carimbo(desde), _carimbo(agora))):
        if r["origem"] is None:
            continue
        quando = datetime.datetime.fromisoformat(r["criado_em"]).replace(tzinfo=_UTC)
        chave = (r["usuario_id"], r["origem"])
        anterior = ultimo.get(chave)
        ultimo[chave] = quando
        if (r["perfil"] == "admin" and quando > agora - DURACAO_ITEM
                and (anterior is None or quando - anterior > JANELA_ORIGEM)):
            out.append({"nivel": "atencao", "data": tempo.iso_utc(r["criado_em"]),
                        "mensagem": f"Administrador {r['nome']} entrou de uma origem nova ({r['origem'] or 'desconhecida'})"})
    return out[::-1]


def itens(conn, agora: datetime.datetime | None = None) -> list[dict]:
    """Bloco Seguranca de Administracao > Saude: `[{nivel, mensagem, data}]`, os `critico` primeiro (issue #422: o
    problema que continua guarda a data em que foi visto e nao pode cair para fora do teto do bloco) e, dentro de cada
    nivel, do mais novo ao mais antigo (empate mantem a ordem de gravacao, do mais novo ao mais antigo)."""
    agora = agora or tempo.agora_utc()
    por_data = sorted(_conferencia + _origem_nova(conn, agora), key=lambda i: i["data"], reverse=True)
    return sorted(por_data, key=lambda i: i["nivel"] != "critico")


def bloco(conn, agora: datetime.datetime | None = None) -> tuple[list[dict], int]:
    """Gate Sol S3: os `ITENS_NA_TELA` itens mais novos e quantos ficaram de fora."""
    todos = itens(conn, agora)
    return todos[:ITENS_NA_TELA], max(0, len(todos) - ITENS_NA_TELA)


def _protecao_intacta(conn, tabela: str) -> bool:
    """Os gatilhos da migracao 062 em `tabela` existem e o SQL deles e' o da migracao."""
    achados = {r[0]: r[1] for r in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabela,))}
    return all(achados.get(nome) is not None
               and hashlib.sha256(" ".join(achados[nome].split()).encode()).hexdigest() == sha
               for nome, sha in GATILHOS[tabela].items())


def _alerta_aberto(conn, mensagem: str) -> str | None:
    """O `criado_em` do `seguranca.alerta` da mensagem que nenhum `seguranca.alerta_resolvido` fechou depois."""
    r = conn.execute(
        "SELECT acao, criado_em FROM audit_log WHERE acao IN ('seguranca.alerta', 'seguranca.alerta_resolvido') "
        "AND json_extract(depois, '$.mensagem')=? ORDER BY id DESC LIMIT 1", (mensagem,)).fetchone()
    return r[1] if r is not None and r[0] == "seguranca.alerta" else None


def _registrar_na_auditoria(conn, problemas: list[str]) -> None:
    """Abre o alerta do problema de protecao novo e fecha o do que sumiu. O incidente aberto mora na auditoria, entao
    reiniciar o servico com o problema presente nao grava outro; a releitura dentro do BEGIN IMMEDIATE e' o que impede
    duas conferencias ao mesmo tempo (outro processo) de abrirem o mesmo alerta duas vezes."""
    def mudancas():
        out = []
        for m in _MENSAGENS.values():
            aberto = _alerta_aberto(conn, m) is not None
            if (m in problemas) != aberto:
                out.append(("seguranca.alerta" if m in problemas else "seguranca.alerta_resolvido", m))
        return out

    if not mudancas():
        return
    with db.mutacao(conn):
        for acao, m in mudancas():
            auditoria.registrar(conn, None, acao, depois={"mensagem": m})


def conferir(conn, agora: datetime.datetime | None = None) -> list[dict]:
    """Issue #422: confere a protecao das tabelas de usuarios e de sessoes e a cadeia da auditoria, publica o
    resultado para o bloco e o devolve. Problema que continua mantem a data em que foi visto primeiro (a do alerta
    aberto na auditoria; a cadeia quebrada, que nao grava, a da primeira conferencia do processo que a viu).

    O resultado e' publicado ANTES de gravar: falha ao gravar na auditoria (banco travado, por exemplo) nao deixa a tela
    em "nenhum alerta". Com a cadeia quebrada nada se grava (a linha nova so' encadearia sobre o adulterado)."""
    global _conferencia
    with _TRAVA:
        agora = agora or tempo.agora_utc()
        cadeia_ok = auditoria.verificar_cadeia(conn)
        problemas = [m for tabela, m in _MENSAGENS.items() if not _protecao_intacta(conn, tabela)]
        if not cadeia_ok:
            problemas.append(CADEIA_QUEBRADA)
        anteriores = {i["mensagem"]: i["data"] for i in _conferencia}
        publicado = []
        for m in problemas:
            aberto = _alerta_aberto(conn, m) if m != CADEIA_QUEBRADA else None
            data = tempo.iso_utc(aberto) if aberto else anteriores.get(m) or tempo.iso_utc(_carimbo(agora))
            publicado.append({"nivel": "critico", "mensagem": m, "data": data})
        _conferencia = publicado
        if cadeia_ok:
            try:
                _registrar_na_auditoria(conn, problemas)
            except Exception:
                log.exception("conferencia de seguranca: o alerta nao foi gravado na auditoria")
        return list(_conferencia)


def agendar(intervalo_seg: int = INTERVALO_CONFERENCIA_SEG) -> threading.Thread:
    """Thread da conferencia (como o backup): a primeira no boot, depois a cada `intervalo_seg`."""
    def loop():
        while True:
            try:
                conn = db.get_conn()
                try:
                    conferir(conn)
                finally:
                    conn.close()
            except Exception:  # a thread nunca morre; a proxima rodada tenta de novo
                log.exception("conferencia de seguranca falhou fora do previsto")
            time.sleep(intervalo_seg)

    t = threading.Thread(target=loop, name="seguranca", daemon=True)
    t.start()
    return t
