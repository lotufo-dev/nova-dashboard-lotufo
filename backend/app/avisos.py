"""Registro unico dos avisos da operacao e da diretoria (spec 2026-09-21 §11), bloco 6.

Cada FONTE e' uma funcao (conn, hoje) -> [aviso]. O bloco 6 registra documentos, notas e o prazo do
contrato; o bloco 7 trocou o prazo simples pelos avisos de `prazos` e `reajuste`; o bloco 8 acrescentou
o pagamento atrasado. A tela nao sabe de onde o aviso vem: so' le o formato.

Formato: {tipo, nivel: critico|acao|atencao, publico: [operacao|diretoria], contrato_id, obra, dias,
valor_centavos, mensagem, destino, data, sentido}. Aviso some por ato real (documento gravado, carta
enviada, instrumento carregado), nunca por "dispensar".

Alem do formato, cada fonte pode dizer o objeto do aviso: `entidade_id` (documentos), `medicao_id` (nota, A2)
e `data_base_mes` (reajuste, A10), para o clique levar a empresa, a medicao ou o ciclo, e nao so' a aba.

`data` e `sentido` (mapa de navegacao de 2026-09-28, mudanca A8): a data do fato e o que `dias` conta.
`sentido="prazo"`: `data` e' um prazo e `dias` conta ATE' ele (negativo = vencido). `sentido="desde"`:
`data` e' um acontecimento e `dias` conta DESDE ele. Nos dois casos, hoje − data e' o atraso, que a tela
usa para pôr o mais atrasado primeiro. Aviso sem data de fato (nota divergente, folga) leva os dois nulos.
"""
import datetime

from app import documentos, notas, tempo

NIVEIS = ("critico", "acao", "atencao")
_ORDEM = {n: i for i, n in enumerate(NIVEIS)}


def aviso(tipo, nivel, mensagem, contrato_id=None, obra=None, dias=None, valor_centavos=None,
          publico=("operacao",), destino=None, data=None, sentido=None) -> dict:
    return {"tipo": tipo, "nivel": nivel, "publico": list(publico), "contrato_id": contrato_id, "obra": obra,
            "dias": dias, "valor_centavos": valor_centavos, "mensagem": mensagem,
            "destino": destino or ({"tela": "contrato", "id": contrato_id, "aba": "medicoes"} if contrato_id else None),
            "data": data, "sentido": sentido}


def obra(conn, contrato_id: int | None) -> str | None:
    if not contrato_id:
        return None
    r = conn.execute("SELECT nome_curto, numero_instrumento FROM contratos WHERE id=?", (contrato_id,)).fetchone()
    return (r["nome_curto"] or r["numero_instrumento"]) if r else None


def ativos(conn) -> list[dict]:
    """Contratos `ativo` sem encerramento iniciado (os que ainda medem)."""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM contratos WHERE estado='ativo' AND encerramento_iniciado_em IS NULL "
        "ORDER BY nome_curto, id")]


def _de_documentos(conn, hoje: datetime.date) -> list[dict]:
    return [{**aviso(a["tipo"], a["nivel"], a["mensagem"], a.get("contrato_id"), obra(conn, a.get("contrato_id")),
                     destino={"tela": "documentos"}, data=a.get("data"), sentido="prazo" if a.get("data") else None),
             "entidade_id": a["entidade_id"], "entidade": a.get("entidade")}
            for a in documentos.avisos(conn, hoje)]


# D10 (2026-09-26): nota divergente do espelho e' CRITICO, como a aba Notas ja' a mostra.
_NIVEL_NOTA = {"nota_divergente": "critico", "nota_ausente_rm": "atencao", "nota_cancelada_rm": "acao"}


def _de_notas(conn, hoje: datetime.date) -> list[dict]:
    out = []
    for a in notas.avisos(conn, hoje):
        cid = a.get("contrato_id")
        nome = obra(conn, cid)
        dias = a.get("dias")
        # A2 (mapa de 2026-09-28): a medicao da nota, para o aviso levar as notas DELA, e nao a obra toda.
        out.append({**aviso(a["tipo"], _NIVEL_NOTA.get(a["tipo"], "atencao"),
                            a["mensagem"], cid, nome, dias=dias,
                            destino={"tela": "contrato", "id": cid, "aba": "notas"} if cid else None,
                            data=(hoje - datetime.timedelta(days=dias)).isoformat() if dias is not None else None,
                            sentido="desde" if dias is not None else None),
                    "medicao_id": a.get("medicao_id")})
    return out


def _de_prazos(conn, hoje: datetime.date) -> list[dict]:
    from app import prazos           # import tardio: `prazos` importa este modulo (formato do aviso)
    return prazos.avisos(conn, hoje)


def _de_reajuste(conn, hoje: datetime.date) -> list[dict]:
    from app import reajuste
    return reajuste.avisos(conn, hoje)


def _de_garantias(conn, hoje: datetime.date) -> list[dict]:
    """Issue #65: garantia contratual (30/15/vencida), na tela Documentos."""
    from app import contratos, garantias
    out = []
    for a in garantias.avisos(conn, hoje):
        c = conn.execute("SELECT entidade_id FROM contratos WHERE id=?", (a["contrato_id"],)).fetchone()
        # o aviso leva a empresa contratada: a pagina dela em Documentos abre na aba da garantia
        out.append({**aviso(a["tipo"], a["nivel"], a["mensagem"], a["contrato_id"], obra(conn, a["contrato_id"]),
                            dias=a["dias"], publico=a["publico"], destino={"tela": "documentos"}, data=a["data"],
                            sentido="prazo" if a["data"] else None),
                    "entidade_id": contratos.entidade_de(c) if c else None})
    return out


FONTES = [_de_documentos, _de_notas, _de_prazos, _de_reajuste, _de_garantias]


def listar(conn, hoje: datetime.date | None = None, publico: str = "operacao") -> list[dict]:
    hoje = hoje or tempo.hoje_local()
    todos = [a for fonte in FONTES for a in fonte(conn, hoje)]
    if publico != "todos":
        todos = [a for a in todos if publico in a["publico"]]
    # nivel; depois o mais atrasado primeiro (os piores no topo do nivel); sem data nem dias, no fim
    return sorted(todos, key=lambda a: (_ORDEM[a["nivel"]], _chave_atraso(a, hoje), a["obra"] or ""))


def _chave_atraso(a: dict, hoje: datetime.date):
    """Atraso negado, para ordenar do pior ao menos grave. Com `data` (a do fato), o atraso e' hoje - data, o
    mesmo nos dois sentidos (docstring do modulo); sem ela, `dias` conta desde o fato ("desde") ou ate' o prazo (negativo = vencido)."""
    if a["data"]:
        return (0, -(hoje - datetime.date.fromisoformat(a["data"][:10])).days)
    if a["dias"] is not None:
        return (0, -a["dias"] if a["sentido"] == "desde" else a["dias"])
    return (1, 0)


def _mes(d: datetime.date) -> str:
    return d.strftime("%Y-%m")


def resumo_mes(conn, hoje: datetime.date | None = None) -> dict:
    """"X de N obras ativas protocoladas no mes" e o valor protocolado no mes e no anterior, pela PRIMEIRA
    data de protocolo de cada medicao (reprotocolo nao conta de novo)."""
    hoje = hoje or tempo.hoje_local()
    mes, ant = _mes(hoje), _mes(hoje.replace(day=1) - datetime.timedelta(days=1))
    ids_ativos = {c["id"] for c in ativos(conn)}
    linhas = conn.execute(
        "SELECT m.id, m.contrato_id, COALESCE(m.valor_protocolado_centavos, 0) AS valor, MIN(mp.data) AS data "
        "FROM medicoes m JOIN medicao_protocolos mp ON mp.medicao_id=m.id "
        "WHERE m.estado NOT IN ('cancelada','desistida') GROUP BY m.id").fetchall()
    no_mes = [r for r in linhas if (r["data"] or "")[:7] == mes]
    protocolaram = {r["contrato_id"] for r in no_mes} & ids_ativos
    # A1 (mapa de 2026-09-28): QUAIS obras ativas protocolaram e quais faltam, para cobrar as que faltam.
    lista = [{"contrato_id": c["id"], "obra": c["nome_curto"] or c["numero_instrumento"]} for c in ativos(conn)]
    return {"mes": mes, "obras_ativas": len(ids_ativos),
            "obras_protocoladas": len(protocolaram),
            "valor_mes_centavos": sum(r["valor"] for r in no_mes),
            "valor_mes_anterior_centavos": sum(r["valor"] for r in linhas if (r["data"] or "")[:7] == ant),
            "protocoladas": [o for o in lista if o["contrato_id"] in protocolaram],
            "faltam": [o for o in lista if o["contrato_id"] not in protocolaram]}
