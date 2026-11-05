"""Seguranca do acesso (issue #418): os ultimos acessos de cada pessoa e o bloco Seguranca de Administracao > Saude.

O login (`api_auth.login`) grava no `depois` de `auth.login` e de `auth.login_falha` a origem (o IP da conexao, o
mesmo do limite por origem; X-Forwarded-For e' ignorado) e o navegador (User-Agent cortado em `NAVEGADOR_MAX`).
Aqui so' se le a auditoria: ela continua append-only e encadeada, sem coluna nova.

`itens` monta o bloco Seguranca como uma lista de `{nivel, mensagem, data}`; `app/integridade.py` (#421) acrescenta o item do codigo
em producao diferente do ultimo deploy; as proximas verificacoes do plano de protecao acrescentam os seus.
"""
import datetime
import json

from app import integridade, tempo

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
    """Bloco Seguranca de Administracao > Saude: `[{nivel, mensagem, data}]`, do mais novo ao mais antigo (empate
    mantem a ordem de gravacao, do mais novo ao mais antigo)."""
    agora = agora or tempo.agora_utc()
    return sorted(_origem_nova(conn, agora) + integridade.itens(), key=lambda i: i["data"], reverse=True)


def bloco(conn, agora: datetime.datetime | None = None) -> tuple[list[dict], int]:
    """Gate Sol S3: os `ITENS_NA_TELA` itens mais novos e quantos ficaram de fora."""
    todos = itens(conn, agora)
    return todos[:ITENS_NA_TELA], max(0, len(todos) - ITENS_NA_TELA)
