"""Pagina Resumo das medicoes (issue #749): em que etapa do ciclo esta' a medicao de cada obra numa competencia, as
obras sem medicao nela e as medicoes de competencias anteriores ainda em aberto. So' leitura.

As etapas sao as do glossario, na ordem do ciclo: em analise, boletim, nota, protocolado, recebido. A medicao so' tem
as etapas do fluxo dela (`medicoes.passos_das_medicoes`: a familia do orgao e a chave `passos_medicao` do contrato):

- em analise: a obra tem o passo "Análise do órgão";
- boletim: tem "Espelhos" ou "Notas" (a medicao aprovada espera a nota);
- nota e recebido: sempre (o passo "Pagamento" e' obrigatorio no cadastro, e so' se paga contra a nota);
- protocolado: tem "Envio da nota" (a obra sem esse passo vai da nota ao recebido).

A etapa da vez sai do passo da vez (`medicoes.passo_do_estado`), nunca de data ou de valor. Cada etapa alcancada leva
a data do evento que o sistema registrou (envio da planilha/carta, boletim, emissao da nota, primeiro protocolo da
nota, recebimento); sem o registro, a data vem nula e a tela mostra o traco. Nada e' estimado.

Valor: o medido (o aprovado e, sem boletim, o pedido) na COTA da Lotufo, medicao a medicao, com o arredondamento
unico de `contratos.cota`; medicao sem valor nenhum vem nula. A prevista, a cancelada e a desistida nao contam: a obra
so' com elas esta' sem medicao no mes (a regra do quadro do mes, `medicoes._quadro_do_mes`).
"""
import datetime

from app import contratos, diretoria, medicoes, tempo

ETAPAS = ("em_analise", "boletim", "nota", "protocolado", "recebido")
ROTULO = {"antes": "Planilha/carta a enviar", "em_analise": "Em análise", "boletim": "Boletim", "nota": "Nota",
          "protocolado": "Protocolado", "recebido": "Recebido"}
# o passo da barra da medicao (`medicoes.PASSOS`) cujo dia e' o evento que poe a medicao na etapa
_PASSO_DA_DATA = {"em_analise": 1, "boletim": 2, "nota": 4, "protocolado": 5, "recebido": 6}
_FORA = ("prevista", "cancelada", "desistida")
_ORDEM_TIPO = ("execucao", "projeto", "reajuste")


def etapas_do_fluxo(passos) -> tuple[str, ...]:
    """As etapas do ciclo que a medicao com estes passos (numeros de `medicoes.PASSOS`) tem."""
    tem = set(passos)
    return tuple(e for e, vale in (("em_analise", 2 in tem), ("boletim", bool(tem & {3, 4})), ("nota", True),
                                   ("protocolado", 5 in tem), ("recebido", True)) if vale)


def etapa_da_vez(estado: str, passos) -> str | None:
    """A etapa em que a medicao esta': `antes` (planilha/carta ainda nao enviada), uma de `ETAPAS`, ou None para a
    cancelada e a desistida. A prevista nao chega aqui: quem chama a deixa de fora (`_FORA`)."""
    n = medicoes.passo_do_estado(estado, passos)
    if n == 0:
        return None
    if n == 7:
        return "recebido"
    if n == 1:
        return "antes"
    do_fluxo = etapas_do_fluxo(passos)
    # esperando o pagamento (passo 6), a medicao esta' na ultima etapa antes do recebido que o fluxo dela tem
    return {2: "em_analise", 3: "boletim", 4: "boletim", 5: "nota"}.get(n) or do_fluxo[-2]


def _cota(m: dict) -> int | None:
    valor = m["valor_atestado_centavos"] if m["valor_atestado_centavos"] is not None else m["valor_protocolado_centavos"]
    return None if valor is None else contratos.cota(valor, m["pct"])


def _medicao(conn, m: dict, passos_de) -> dict | None:
    """A medicao com a etapa da vez e, de cada etapa do fluxo dela, a situacao (feito, atual, futuro) e a data."""
    passos = passos_de(m)
    da_vez = etapa_da_vez(m["estado"], passos)
    if da_vez is None:
        return None
    do_fluxo = etapas_do_fluxo(passos)
    datas = medicoes._datas_dos_passos(conn, m)
    pos = do_fluxo.index(da_vez) if da_vez in do_fluxo else -1
    etapas = []
    for i, e in enumerate(do_fluxo):
        # recebida, o ciclo acabou: a ultima etapa tambem esta' feita
        situacao = "futuro" if i > pos else "feito" if i < pos or e == "recebido" else "atual"
        dia = datas[_PASSO_DA_DATA[e]] if situacao != "futuro" else None
        etapas.append({"etapa": e, "situacao": situacao, "data": dia.isoformat() if dia else None})
    return {"id": m["id"], "contrato_id": m["contrato_id"], "numero": m["numero"], "tipo": m["tipo"],
            "competencia": m["competencia"], "titulo": medicoes.titulo(m), "etapa": da_vez, "etapas": etapas,
            "valor_centavos": _cota(m)}


def _linhas(partes: list[dict], obras: dict[int, dict]) -> list[dict]:
    """Uma linha por medicao. A execucao e o reajuste de mesmo numero, na mesma competencia e na mesma etapa, viram
    uma linha so' ("24ª Medição + Reajuste", como em `medicoes.linhas_em_andamento`): o valor e' a soma das duas cotas
    e cada etapa leva a data da ultima das duas a chegar nela."""
    grupos: dict[tuple, list[dict]] = {}
    for p in partes:
        grupos.setdefault((p["contrato_id"], p["competencia"], p["numero"], p["etapa"]), []).append(p)
    linhas = []
    for ps in grupos.values():
        tipos = {p["tipo"]: p for p in ps}
        par = [tipos["execucao"], tipos["reajuste"]] if {"execucao", "reajuste"} <= set(tipos) else []
        for juntas in ([par] if par else []) + [[p] for p in ps if p not in par]:
            principal = juntas[0]
            etapas = []
            for e in principal["etapas"]:
                dias = [x["data"] for p in juntas for x in p["etapas"] if x["etapa"] == e["etapa"] and x["data"]]
                etapas.append({**e, "data": max(dias) if dias else None})
            valores = [p["valor_centavos"] for p in juntas if p["valor_centavos"] is not None]
            o = obras.get(principal["contrato_id"], {})
            linhas.append({
                "contrato_id": principal["contrato_id"], "obra": o.get("obra"), "contratante": o.get("contratante"),
                "medicao_id": principal["id"], "medicao_ids": [p["id"] for p in juntas],
                "titulo": f"{principal['titulo']} + Reajuste" if len(juntas) == 2 else principal["titulo"],
                "numero": principal["numero"], "tipo": principal["tipo"], "competencia": principal["competencia"],
                "etapa": principal["etapa"], "etapas": etapas,
                "valor_centavos": sum(valores) if valores else None})
    linhas.sort(key=lambda x: (medicoes._chave_nome(x["obra"]), x["contrato_id"], _ORDEM_TIPO.index(x["tipo"]),
                               x["numero"], x["medicao_id"]))
    return linhas


def _atualizacao(conn) -> dict:
    """De quando e' o dado: o ultimo lancamento feito por uma pessoa em qualquer medicao (a auditoria) e a ultima
    leitura do RM que terminou bem (de onde vem o recebido). Carimbos em UTC, como o banco guarda."""
    lancamento = conn.execute("SELECT MAX(criado_em) FROM audit_log WHERE entidade='medicao' "
                              "AND usuario_id IS NOT NULL").fetchone()[0]
    rm = conn.execute("SELECT MAX(terminado_em) FROM rm_sincronizacoes WHERE estado='success'").fetchone()[0]
    return {"ultimo_lancamento": lancamento, "rm_lido_em": rm}


def resumo(conn, hoje: datetime.date | None = None, mes: str | None = None) -> dict:
    """A competencia `mes` (AAAA-MM; sem ela, a competencia em trabalho: o mes anterior ao de hoje): as linhas por
    contratante, a contagem por etapa, as obras ativas sem medicao nela (com a ultima medicao de cada uma) e as
    medicoes abertas de competencias anteriores, da mais antiga para a mais nova."""
    hoje = hoje or tempo.hoje_local()
    em_trabalho = diretoria._mes(hoje, -1)
    mes = mes or em_trabalho
    obras = medicoes._obras_com_contratante(conn)
    passos_de = medicoes.passos_das_medicoes(conn)
    marcas = ",".join("?" * len(_FORA))
    # a data do protocolo e' a do PRIMEIRO protocolo da nota (a que comeca a contar o prazo do orgao), como no Inicio
    sql = ("SELECT m.*, c.percentual_direito_bp AS pct, (SELECT MIN(p.data) FROM medicao_protocolos p "
           "WHERE p.medicao_id=m.id AND p.etapa='nota') AS protocolado_em FROM medicoes m "
           f"JOIN contratos c ON c.id=m.contrato_id WHERE m.estado NOT IN ({marcas}) ")
    do_mes, anteriores = [], []
    for r in conn.execute(sql + "AND (m.competencia=? OR (m.competencia<? AND m.estado<>'recebida'))", (*_FORA, mes, mes)):
        p = _medicao(conn, dict(r), passos_de)
        if p is not None:
            (do_mes if p["competencia"] == mes else anteriores).append(p)

    linhas = _linhas(do_mes, obras)
    grupos: dict[str, list[dict]] = {}
    for x in linhas:
        grupos.setdefault(x["contratante"] or "sem contratante", []).append(x)
    etapas = [{"etapa": e, "medicoes": sum(1 for p in do_mes if p["etapa"] == e),
               "valor_centavos": sum(p["valor_centavos"] or 0 for p in do_mes if p["etapa"] == e)}
              for e in ("antes", *ETAPAS)]

    # a ultima medicao de execucao ou de projeto de cada obra, ate' a competencia da pagina (o reajuste acompanha a execucao)
    ultima: dict[int, dict] = {}
    for r in conn.execute(sql + "AND m.tipo IN ('execucao','projeto') AND m.competencia<=? "
                          "ORDER BY m.competencia DESC, m.numero DESC, m.id DESC", (*_FORA, mes)):
        if r["contrato_id"] not in ultima:
            m = dict(r)
            da_vez = etapa_da_vez(m["estado"], passos_de(m))
            if da_vez is not None:
                ultima[m["contrato_id"]] = {"medicao_id": m["id"], "titulo": medicoes.titulo(m),
                                            "competencia": m["competencia"], "etapa": da_vez}
    com_medicao = {p["contrato_id"] for p in do_mes}
    sem_fluxo = medicoes.sem_fluxo(conn)
    sem_medicao = [{"contrato_id": o["id"], "obra": o["obra"], "contratante": o["contratante"], "ultima": ultima.get(o["id"])}
                   for o in sorted(obras.values(), key=lambda o: (medicoes._chave_nome(o["obra"]), o["id"]))
                   if o["id"] not in com_medicao and o["id"] not in sem_fluxo and o["estado"] == "ativo"
                   and not o["encerramento_iniciado_em"]]

    por_competencia: dict[str, list[dict]] = {}
    for x in _linhas(anteriores, obras):
        por_competencia.setdefault(x["competencia"], []).append(x)
    return {"hoje": hoje.isoformat(), "mes": mes, "em_trabalho": em_trabalho, "atualizacao": _atualizacao(conn),
            "etapas": etapas,
            "grupos": [{"contratante": k, "linhas": v} for k, v in sorted(grupos.items(), key=lambda kv: medicoes._chave_nome(kv[0]))],
            "sem_medicao": sem_medicao,
            "anteriores": [{"competencia": k, "linhas": por_competencia[k]} for k in sorted(por_competencia)]}


def _data_br(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


CABECALHO_CSV = ["parte", "contratante", "obra", "medicao", "competencia", "etapa",
                 *(f"data_{e}" for e in ETAPAS), "valor_cota"]


def linhas_csv(r: dict, brl) -> list[list[str]]:
    """A relacao que a pagina mostra, na ordem dela: as medicoes da competencia, as obras sem medicao e as medicoes
    abertas de competencias anteriores. `brl` formata os centavos (o de `app.dinheiro`)."""
    def comp(c: str) -> str:
        return f"{c[5:7]}/{c[:4]}"

    def da_linha(parte: str, x: dict) -> list[str]:
        datas = {e["etapa"]: e["data"] for e in x["etapas"]}
        return [parte, x["contratante"] or "", x["obra"] or "", x["titulo"], comp(x["competencia"]), ROTULO[x["etapa"]],
                *(_data_br(datas.get(e)) for e in ETAPAS), brl(x["valor_centavos"]) if x["valor_centavos"] is not None else ""]

    out = [da_linha("competência", x) for g in r["grupos"] for x in g["linhas"]]
    for o in r["sem_medicao"]:
        out.append(["sem medição no mês", o["contratante"] or "", o["obra"] or "", "", comp(r["mes"]), "", *[""] * len(ETAPAS), ""])
    out.extend(da_linha("meses anteriores", x) for g in r["anteriores"] for x in g["linhas"])
    return out
