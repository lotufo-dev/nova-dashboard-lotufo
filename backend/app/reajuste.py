"""Ciclo do reajuste por data-base (spec 2026-09-21 §7.2), bloco 7.

O sistema nao calcula indice nem valor. Sabe so' o calendario: o reajuste vale a partir do MES do
aniversario (OT 028/2015/CGE item 3.2.1; clausula 11.45 SINFRA); o aviso comeca 30 dias antes do 1o dia
desse mes; o ciclo fecha com o APOSTILAMENTO, nao com o oficio (reenviado a cada aditivo).
"""
import datetime
import json

from app import avisos as _av, tempo

JANELA_DIAS, DIRETORIA_DIAS = 30, 90


def aniversario(mes_base: str, ano: int) -> datetime.date:
    return datetime.date(ano, int(mes_base[5:7]), 1)


def _ciclo_corrente(mes_base: str, hoje: datetime.date) -> int | None:
    """Maior ano Y em que (1o dia do mes de aniversario de Y) - 30 dias ja' chegou."""
    anos = [y for y in range(int(mes_base[:4]) + 1, hoje.year + 2)
            if aniversario(mes_base, y) - datetime.timedelta(days=JANELA_DIAS) <= hoje]
    return max(anos) if anos else None


def ciclo_do_apostilamento(dados: dict, data: str) -> int | None:
    """O ciclo (ano) que o apostilamento fecha: `ciclo`, senao o ano da `eficacia`, senao o da data do termo."""
    try:
        return int(str(dados.get("ciclo") or dados.get("eficacia") or data)[:4])      # "2026-06" -> 2026
    except ValueError:
        return None


def _termo_vale(i: str) -> str:
    """Resolvedor unico do apostilamento de reajuste que vale (issue #271), como condicao SQL sobre o alias `i` de
    `instrumentos`: termo corrigido por outro (`corrige` nos dados) nao vale por inteiro, nem nas competencias que a
    correcao nao repete. Numa cadeia (T3 corrige T2, que corrige T1) cada elo e' corrigido pelo seguinte, entao so' o
    ultimo vale. Entre os que valem, a precedencia e' `_ORDEM_TERMO`: a data do instrumento, nao a da aplicacao."""
    return (f"NOT EXISTS (SELECT 1 FROM instrumentos x WHERE x.contrato_id = {i}.contrato_id "
            f"AND x.tipo = 'apostilamento_reajuste' AND json_extract(x.dados, '$.corrige') = {i}.chave)")


def _ordem_termo(i: str) -> str:
    """O termo mais novo manda (data do documento; empate: o aplicado depois)."""
    return f"{i}.data DESC, {i}.id DESC"


def base_do_termo(dados: dict, guardada: str | None, unica: str | None) -> str | None:
    """A data-base de um apostilamento, resolvida num lugar so' (revisor e gate Sol, rodada 3, PR #317): `data_base`
    nos dados; senao a que ficou guardada no termo quando ele foi aplicado (`instrumentos.data_base_mes`, migracao
    055: a base unica daquele momento, que nao muda quando o contrato ganha ou troca de base); so' o termo sem base
    guardada cai na data-base unica de agora (`unica`)."""
    return dados.get("data_base") or guardada or unica


def bases_dos_termos(conn, contrato_id: int) -> list[dict]:
    """A data-base resolvida (`base_do_termo`) de cada apostilamento do contrato, para a aba Reajuste por o termo no
    cartao certo; None quando nao se sabe."""
    bases = [r[0] for r in conn.execute("SELECT mes FROM contrato_datas_base WHERE contrato_id=?", (contrato_id,))]
    unica = bases[0] if len(bases) == 1 else None
    return [{"instrumento_id": r["id"],
             "data_base_mes": base_do_termo(json.loads(r["dados"] or "{}"), r["data_base_mes"], unica)}
            for r in conn.execute("SELECT id, dados, data_base_mes FROM instrumentos WHERE contrato_id=? "
                                  "AND tipo='apostilamento_reajuste' ORDER BY id", (contrato_id,))]


def _apostilamento(conn, contrato_id: int, mes_base: str, ciclo: int, unica: bool) -> dict | None:
    """Apostilamento de reajuste com a mesma data-base (`base_do_termo`) e o mesmo ciclo. Sem `ciclo`, o ano da
    `eficacia` (ou da data do instrumento). Termo corrigido nao conta (`_termo_vale`)."""
    for r in conn.execute(f"SELECT * FROM instrumentos i WHERE i.contrato_id=? AND i.tipo='apostilamento_reajuste' "
                          f"AND {_termo_vale('i')} ORDER BY {_ordem_termo('i')}", (contrato_id,)):
        d = json.loads(r["dados"] or "{}")
        base = base_do_termo(d, r["data_base_mes"], mes_base if unica else None)
        ano = ciclo_do_apostilamento(d, r["data"])
        if ano is None:
            continue
        if base == mes_base and ano == ciclo:
            return {**dict(r), "dados": d}
    return None


def _termo_do_pleito(conn, contrato_id: int, pleito: dict) -> dict | None:
    """O apostilamento de reajuste que o cadastro ligou ao pleito (`instrumento_chave`, issue #271), se ainda vale
    (`_termo_vale`). Sem ligacao, nenhum: termo do ciclo que nao atendeu este pleito nao o fecha."""
    if not pleito.get("instrumento_chave"):
        return None
    r = conn.execute(f"SELECT * FROM instrumentos i WHERE i.contrato_id=? AND i.tipo='apostilamento_reajuste' "
                     f"AND i.chave=? AND {_termo_vale('i')}", (contrato_id, pleito["instrumento_chave"])).fetchone()
    return {**dict(r), "dados": json.loads(r["dados"] or "{}")} if r else None


def _termo_do_pedido(conn, contrato_id: int, pleito: dict) -> dict | None:
    """O termo ligado ao pleito ou, subindo pelas reiteracoes (`reemite_pleito_id`), ao pedido que elas reiteram
    (revisor, PR #317): a reiteracao nao traz cronograma, entao o termo que atendeu o pedido tambem fecha a
    reiteracao enviada depois dele. A reemissao do cronograma e' pedido novo e para a subida: espera o termo dela."""
    p, vistos = pleito, set()
    while p is not None and p["id"] not in vistos:
        vistos.add(p["id"])
        termo = _termo_do_pleito(conn, contrato_id, p)
        if termo is not None:
            return termo
        if p.get("reemissao") != "reiteracao" or not p.get("reemite_pleito_id"):
            return None
        r = conn.execute("SELECT * FROM pleitos WHERE id=?", (p["reemite_pleito_id"],)).fetchone()
        p = dict(r) if r else None
    return None


def apostilamento_do_ciclo(conn, contrato_id: int, mes_base: str, ciclo: int, unica: bool) -> dict | None:
    """O termo que fecha o ciclo, o unico criterio da aba, dos avisos e da recusa de reiterar/reemitir (gate Sol e
    revisor, PR #317): com pleito enviado no ciclo, o termo ligado ao vigente (ou ao pedido que ele reitera); sem
    pleito enviado registrado, o apostilamento do ciclo (`_apostilamento`)."""
    pl = _pleito(conn, contrato_id, mes_base, ciclo)
    if pl:
        return _termo_do_pedido(conn, contrato_id, pl)
    return _apostilamento(conn, contrato_id, mes_base, ciclo, unica)


def _pleito(conn, contrato_id: int, mes_base: str, ciclo: int, sem_reiteracao: bool = False) -> dict | None:
    """O ultimo pleito enviado do ciclo vale (reemissao a cada aditivo e' novo pleito no mesmo ciclo).
    `sem_reiteracao`: o ultimo PEDIDO (pleito original ou reemissao do cronograma). A reiteracao (issue #277) so'
    cobra o pedido; o tempo sem apostilamento e o "ultimo pleito" do aditivo contam dele, nao dela."""
    filtro = "AND COALESCE(reemissao, '') <> 'reiteracao' " if sem_reiteracao else ""
    r = conn.execute("SELECT * FROM pleitos WHERE contrato_id=? AND tipo='reajuste' AND data_base_mes=? AND ciclo=? "
                     f"AND situacao='enviado' {filtro}ORDER BY enviado_em DESC, id DESC LIMIT 1",
                     (contrato_id, mes_base, ciclo)).fetchone()
    return dict(r) if r else None


def aditivo_depois(conn, contrato_id: int, desde: str | None) -> dict | None:
    """Aditivo de prazo ou valor assinado depois de `desde` (spec 2026-10-20 §2.2, estado `reemitir`): o que
    pede a reemissao do cronograma de reajuste. Sem `desde`, nenhum."""
    if not desde:
        return None
    r = conn.execute("SELECT * FROM aditivos WHERE contrato_id=? AND status='assinado' "
                     "AND tipo IN ('prazo','valor','misto') AND data_assinatura IS NOT NULL "
                     "AND substr(data_assinatura, 1, 10) > ? ORDER BY data_assinatura DESC, id DESC LIMIT 1",
                     (contrato_id, desde[:10])).fetchone()
    return dict(r) if r else None


# Origem mais forte primeiro (spec 2026-10-20 §2.2): o apostilamento manda, o pleito vem depois, o manual por ultimo.
ORDEM_ORIGEM = ("apostilamento", "pleito", "manual")


def previsoes_vigentes(conn, contrato_id: int, data_base_mes: str | None = None,
                       como_enviado: int | None = None, sem_apostilamento: bool = False) -> list[dict]:
    """Previsao vigente de cada competencia (por data-base e ciclo): a mais recente da origem mais forte.
    As previsoes sao eventos (migracao 043): nada se sobrescreve, a leitura escolhe.

    Previsao ligada a pleito (lida ou digitada nele) so' vale enquanto o pleito vale: pleito descartado, ou
    reemitido por outro pleito ja' enviado, sai da conta inteiro (a reemissao traz o cronograma todo; competencia
    que ela nao traz deixa de ter previsao de pleito e cai para o manual sem pleito, se houver). Reemissao ainda em
    rascunho nao derruba o anterior.

    A reiteracao (issue #277, migracao 050) nao traz cronograma: nao derruba o pleito que reitera. A reemissao do
    cronograma derruba o pleito que ela aponta e, subindo pelas reiteracoes no meio, o pleito que elas reiteram
    (original -> reiteracao -> cronograma novo: o original sai), mas so' depois que a reemissao tem previsoes
    proprias gravadas (lidas ou digitadas nela).

    Previsao de apostilamento segue o termo (issue #271, `_termo_vale`): termo corrigido sai da conta inteiro, e
    entre termos que valem manda o de data mais recente, seja qual for a ordem em que o cadastro os aplicou.

    `como_enviado`: le como se esse pleito ja' estivesse enviado (o que ele derrubaria sai da conta). E' a conferencia
    da gravacao da previsao num pleito ainda em rascunho: a previsao dele tem de ser a que vale depois do envio.

    `sem_apostilamento`: so' as previsoes de pleito e manuais (o previsto que se compara com o apostilado)."""
    ordem = " ".join(f"WHEN '{o}' THEN {i}" for i, o in enumerate(ORDEM_ORIGEM))
    filtro, args = ("AND p.data_base_mes=?", (contrato_id, como_enviado, contrato_id, data_base_mes)) \
        if data_base_mes is not None else ("", (contrato_id, como_enviado, contrato_id))
    if sem_apostilamento:         # issue #273: o previsto da tabela por competencia (o apostilado e' outra coluna)
        filtro += " AND p.origem <> 'apostilamento'"
    rows = conn.execute(
        # `derrubado`: os pleitos cujo cronograma uma reemissao enviada substituiu (sem `reemissao`, antes da 050,
        # a reemissao conta como cronograma)
        # a reemissao so' derruba quando ja' tem previsoes proprias gravadas (a leitura da planilha do pleito e'
        # outro passo): sem elas o previsto do anterior segue, em vez de cair para manual ou zero
        f"WITH RECURSIVE derrubado(id) AS (SELECT r.reemite_pleito_id FROM pleitos r WHERE r.contrato_id=? "
        f"AND (r.situacao = 'enviado' OR r.id = ?) AND r.reemite_pleito_id IS NOT NULL "
        f"AND COALESCE(r.reemissao, 'cronograma') = 'cronograma' "
        f"AND EXISTS (SELECT 1 FROM reajuste_previsoes x WHERE x.pleito_id = r.id) "
        f"UNION SELECT q.reemite_pleito_id FROM derrubado d JOIN pleitos q ON q.id = d.id "
        # sobe pela reiteracao e pela reemissao que ainda nao tem previsoes proprias (nenhuma das duas traz
        # cronograma): P1 -> P2 vazio -> P3 com previsoes derruba P2 e P1, sem cronograma hibrido
        f"WHERE (q.reemissao = 'reiteracao' OR (COALESCE(q.reemissao, 'cronograma') = 'cronograma' "
        f"AND NOT EXISTS (SELECT 1 FROM reajuste_previsoes x WHERE x.pleito_id = q.id))) "
        f"AND q.reemite_pleito_id IS NOT NULL) "
        f"SELECT * FROM (SELECT p.*, ROW_NUMBER() OVER (PARTITION BY p.data_base_mes, p.ciclo, p.competencia "
        f"ORDER BY CASE p.origem {ordem} END, {_ordem_termo('i')}, datetime(p.criado_em) DESC, p.id DESC) AS _ordem "
        f"FROM reajuste_previsoes p LEFT JOIN instrumentos i ON i.id = p.instrumento_id "
        f"WHERE p.contrato_id=? {filtro} AND (p.origem <> 'apostilamento' OR {_termo_vale('i')}) "
        f"AND (p.pleito_id IS NULL OR (NOT EXISTS (SELECT 1 FROM pleitos pl WHERE pl.id = p.pleito_id "
        f"AND pl.situacao = 'descartado') AND p.pleito_id NOT IN (SELECT id FROM derrubado)))) WHERE _ordem=1 "
        f"ORDER BY data_base_mes, ciclo, competencia", args)
    return [{k: r[k] for k in r.keys() if k != "_ordem"} for r in rows]


def competencias_apostiladas(conn, contrato_id: int) -> list[dict]:
    """Issue #271: as competencias cuja previsao vigente vem de apostilamento, com o termo e o nº da medicao que
    ele cita (do `competencias` do cadastro). Qual termo vale e' o de `previsoes_vigentes` (`_termo_vale`)."""
    termos, medicoes = {}, {}
    for r in conn.execute("SELECT id, chave, numero, data, dados FROM instrumentos WHERE contrato_id=? "
                          "AND tipo='apostilamento_reajuste'", (contrato_id,)):
        termos[r["id"]] = r
        itens = json.loads(r["dados"] or "{}").get("competencias") or []
        medicoes[r["id"]] = {str(x.get("competencia")): x.get("medicao") for x in itens if isinstance(x, dict)}
    out = []
    for p in previsoes_vigentes(conn, contrato_id):
        t = termos.get(p["instrumento_id"]) if p["origem"] == "apostilamento" else None
        if t is None:
            continue
        medicao = medicoes[t["id"]].get(p["competencia"])
        out.append({"data_base_mes": p["data_base_mes"], "ciclo": p["ciclo"], "competencia": p["competencia"],
                    "valor_centavos": p["valor_previsto_centavos"], "medicao": medicao,
                    "instrumento_chave": t["chave"], "instrumento_numero": t["numero"], "instrumento_data": t["data"]})
    return out


# Estados derivados de cada competencia do ciclo (issue #273, spec 2026-10-20 §2.2), na ordem: vale o mais adiantado
# cuja regra se cumpre. `apostilada` nao depende da medicao; por isso cada competencia diz tambem se e' apostilada
# (nota antes do apostilamento fica `faturada` com `apostilada` falso).
ESTADOS_COMPETENCIA = ("prevista", "pedida", "aprovada", "apostilada", "faturada", "recebida")
_MEDICAO_PEDIDA = ("planilha_gerada", "planilha_enviada", "boletim_recebido")
_MEDICAO_FATURADA = ("nota_emitida", "protocolada", "nf_emitida", "recebida")
# ciclo enviado e ainda sem apostilamento: com ou sem cronograma a reemitir, o aviso e a diretoria seguem valendo
SEM_APOSTILAMENTO = ("apostilamento_pendente", "reemitir")


def _ciclo_da_competencia(mes_base: str, competencia: str) -> int | None:
    """O ciclo (ano do aniversario) a que a competencia pertence: do mes do aniversario de Y ao mes anterior ao de
    Y+1. Antes do 1o aniversario, nenhum (ainda nao ha' reajuste)."""
    y = int(competencia[:4]) - (1 if competencia[5:7] < mes_base[5:7] else 0)
    return y if y > int(mes_base[:4]) else None


def _percentuais(conn, contrato_id: int, unica: str | None) -> list[dict]:
    """Termos que valem (`_termo_vale`) com `periodo` (o percentual da MT-PAR), o mais novo primeiro."""
    out = []
    for r in conn.execute(f"SELECT * FROM instrumentos i WHERE i.contrato_id=? AND i.tipo='apostilamento_reajuste' "
                          f"AND {_termo_vale('i')} ORDER BY {_ordem_termo('i')}", (contrato_id,)):
        d = json.loads(r["dados"] or "{}")
        per = d.get("periodo")
        if not isinstance(per, dict) or not per.get("de") or not per.get("ate"):
            continue
        out.append({"base": base_do_termo(d, r["data_base_mes"], unica), "ciclo": ciclo_do_apostilamento(d, r["data"]),
                    "de": str(per["de"]), "ate": str(per["ate"]), "chave": r["chave"],
                    "percentual": d.get("percentual")})
    return out


def competencias_por_ciclo(conn, contrato_id: int) -> list[dict]:
    """Issue #273: por data-base e ciclo, cada competencia com o estado derivado (`ESTADOS_COMPETENCIA`) e o valor de
    cada fonte: previsto (pleito ou manual), pedido e aprovado (medicao de reajuste), apostilado (competencia do
    termo, ou percentual com `periodo` que a cobre), faturado (NF alocada) e recebido (baixa no RM). So' le; nada se
    calcula alem de somar o que ja' esta' gravado.

    A medicao de reajuste vai para a data-base e o ciclo gravados nela; sem eles (medicao anterior ao motor), para a
    unica data-base do contrato (com duas, a que tem previsao da competencia, se for uma so') e para o ciclo da
    previsao da competencia ou, sem previsao, o do aniversario. Cancelada ou desistida nao conta. Duas medicoes na
    mesma competencia: vale a de maior numero."""
    c = conn.execute("SELECT sem_reajuste FROM contratos WHERE id=?", (contrato_id,)).fetchone()
    if c is None or c["sem_reajuste"]:
        return []
    bases = [r[0] for r in conn.execute("SELECT mes FROM contrato_datas_base WHERE contrato_id=? ORDER BY mes",
                                        (contrato_id,))]
    unica = bases[0] if len(bases) == 1 else None
    linhas: dict[tuple[str, int, str], dict] = {}

    def linha(base: str, ciclo: int, comp: str) -> dict:
        return linhas.setdefault((base, ciclo, comp), {
            "competencia": comp, "estado": "prevista", "previsto_centavos": None, "previsto_origem": None,
            "medicao_id": None, "medicao_numero": None, "medicao_estado": None, "pedido_centavos": None,
            "aprovado_centavos": None, "apostilada": False, "apostilado_centavos": None, "apostilado_percentual": None,
            "apostilamento_chave": None, "medicao_orgao": None, "faturado_centavos": None, "recebida_em": None})

    for p in previsoes_vigentes(conn, contrato_id, sem_apostilamento=True):
        x = linha(p["data_base_mes"], p["ciclo"], p["competencia"])
        x["previsto_centavos"], x["previsto_origem"] = p["valor_previsto_centavos"], p["origem"]
    for a in competencias_apostiladas(conn, contrato_id):
        x = linha(a["data_base_mes"], a["ciclo"], a["competencia"])
        x.update(apostilada=True, apostilado_centavos=a["valor_centavos"], apostilamento_chave=a["instrumento_chave"],
                 medicao_orgao=a["medicao"])

    previstas: dict[tuple[str, str], set[int]] = {}
    for base, ciclo, comp in linhas:
        previstas.setdefault((base, comp), set()).add(ciclo)
    faturado = {r[0]: r[1] for r in conn.execute(
        "SELECT a.medicao_id, SUM(a.valor_alocado_centavos) FROM nf_alocacoes a JOIN notas_fiscais n ON n.id = a.nota_id "
        "JOIN medicoes m ON m.id = a.medicao_id WHERE m.contrato_id=? AND a.desfeita_em IS NULL "
        "AND n.situacao = 'ativa' GROUP BY a.medicao_id", (contrato_id,))}
    for m in conn.execute("SELECT * FROM medicoes WHERE contrato_id=? AND tipo='reajuste' "
                          "AND estado NOT IN ('cancelada','desistida') ORDER BY numero, id", (contrato_id,)):
        base = m["data_base_mes"] or unica
        if base is None:
            com_previsao = [b for b in bases if (b, m["competencia"]) in previstas]
            base = com_previsao[0] if len(com_previsao) == 1 else None
        if base is None:
            continue
        ciclo = m["ciclo"]
        if ciclo is None:
            ciclos_previstos = previstas.get((base, m["competencia"]), set())
            ciclo = next(iter(ciclos_previstos)) if len(ciclos_previstos) == 1 \
                else _ciclo_da_competencia(base, m["competencia"])
        if ciclo is None:
            continue
        x = linha(base, ciclo, m["competencia"])
        x.update(medicao_id=m["id"], medicao_numero=m["numero"], medicao_estado=m["estado"],
                 pedido_centavos=m["valor_protocolado_centavos"], aprovado_centavos=m["valor_atestado_centavos"],
                 faturado_centavos=faturado.get(m["id"]), recebida_em=m["recebida_em"])

    percentuais = _percentuais(conn, contrato_id, unica)
    grupos: dict[tuple[str, int], list[dict]] = {}
    for (base, ciclo, comp), x in sorted(linhas.items()):
        if not x["apostilada"]:
            t = next((t for t in percentuais if (t["base"], t["ciclo"]) == (base, ciclo)
                      and t["de"] <= comp <= t["ate"]), None)
            if t:
                x.update(apostilada=True, apostilado_percentual=t["percentual"], apostilamento_chave=t["chave"])
        me = x["medicao_estado"]
        feitos = [True,
                  me is not None and (me in _MEDICAO_PEDIDA or me in _MEDICAO_FATURADA
                                      or x["pedido_centavos"] is not None),
                  me is not None and (me == "boletim_recebido" or x["aprovado_centavos"] is not None),
                  x["apostilada"],
                  me in _MEDICAO_FATURADA or x["faturado_centavos"] is not None,
                  me == "recebida"]
        x["estado"] = ESTADOS_COMPETENCIA[max(i for i, f in enumerate(feitos) if f)]
        grupos.setdefault((base, ciclo), []).append(x)
    return [{"data_base_mes": b, "ciclo": y, "competencias": xs} for (b, y), xs in grupos.items()]


def ciclos(conn, contrato_id: int, hoje: datetime.date | None = None) -> list[dict]:
    """Um ciclo por data-base: o corrente (ou o proximo, `futuro`, antes da primeira janela)."""
    hoje = hoje or tempo.hoje_local()
    c = conn.execute("SELECT sem_reajuste FROM contratos WHERE id=?", (contrato_id,)).fetchone()
    if c is None or c["sem_reajuste"]:
        return []
    bases = [dict(r) for r in conn.execute("SELECT mes, indice, aplica_a FROM contrato_datas_base WHERE contrato_id=? "
                                           "ORDER BY mes", (contrato_id,))]
    out = []
    for b in bases:
        y = _ciclo_corrente(b["mes"], hoje)
        if y is None:
            y = int(b["mes"][:4]) + 1
            aniv = aniversario(b["mes"], y)
            out.append({"data_base_mes": b["mes"], "indice": b["indice"], "aplica_a": b["aplica_a"], "ciclo": y, "aniversario": aniv.isoformat(),
                        "situacao": "futuro", "dias": (aniv - hoje).days, "pleito": None, "pedido": None,
                        "apostilamento": None, "aditivo": None})
            continue
        aniv = aniversario(b["mes"], y)
        ap = apostilamento_do_ciclo(conn, contrato_id, b["mes"], y, len(bases) == 1)
        pl = _pleito(conn, contrato_id, b["mes"], y)
        # o pedido que espera o apostilamento: a reiteracao nao zera a espera (issue #277)
        pd = _pleito(conn, contrato_id, b["mes"], y, sem_reiteracao=True) or pl
        aditivo = None
        if ap:
            sit, dias = "apostilado", None
        elif pl:
            sit, dias = "apostilamento_pendente", (hoje - datetime.date.fromisoformat(pd["enviado_em"][:10])).days
            # issue #273 (spec 2026-10-20 §2.2): aditivo de prazo ou valor assinado depois do ultimo pedido enviado
            # (o mesmo criterio da reemissao em `pleitos._recusa_reemissao`; a reiteracao nao traz cronograma) e
            # nenhum pedido depois dele. Continua sem apostilamento: `dias` segue contando do pedido.
            aditivo = aditivo_depois(conn, contrato_id, pd["enviado_em"])
            if aditivo:
                sit = "reemitir"
        else:
            sit, dias = "pleito_pendente", (aniv - hoje).days
        out.append({"data_base_mes": b["mes"], "indice": b["indice"], "aplica_a": b["aplica_a"], "ciclo": y, "aniversario": aniv.isoformat(),
                    "situacao": sit, "dias": dias, "pleito": pl, "pedido": pd, "apostilamento": ap, "aditivo": aditivo})
    return out


def avisos(conn, hoje: datetime.date | None = None) -> list[dict]:
    """Pleito nao enviado (atencao antes do aniversario, acao depois) e apostilamento pendente (a diretoria
    ve depois de 90 dias). Contratos ativos ou suspensos; em encerramento o reajuste continua valendo
    (as ultimas medicoes tambem se reajustam). A10 (mapa de 2026-09-28): o aviso diz a data-base, para
    levar ao ciclo dela na aba Reajuste, e nao so' a aba."""
    hoje = hoje or tempo.hoje_local()
    out = []
    for c in conn.execute("SELECT id, nome_curto, numero_instrumento FROM contratos "
                          "WHERE estado IN ('ativo','suspenso')"):
        nome = c["nome_curto"] or c["numero_instrumento"]
        destino = {"tela": "contrato", "id": c["id"], "aba": "reajuste"}
        for k in ciclos(conn, c["id"], hoje):
            base = f"{k['data_base_mes'][5:7]}/{k['data_base_mes'][:4]}"
            if k.get("aplica_a"):              # D7: com duas bases, o aviso diz a parte do contrato de cada uma
                base += f" ({k['aplica_a']})"
            aniv = datetime.date.fromisoformat(k["aniversario"])
            if k["situacao"] == "pleito_pendente":
                quando = (f"faz aniversário em {aniv:%d/%m/%Y} (em {k['dias']} dias)" if k["dias"] >= 0
                          else f"fez aniversário em {aniv:%d/%m/%Y} (há {-k['dias']} dias)")
                out.append({**_av.aviso("reajuste_pleito", "atencao" if k["dias"] >= 0 else "acao",
                                        f"data-base {base} {quando}; pleito de reajuste não enviado",
                                        c["id"], nome, dias=k["dias"], destino=destino,
                                        data=k["aniversario"], sentido="prazo"),
                            "data_base_mes": k["data_base_mes"]})
            elif k["situacao"] in SEM_APOSTILAMENTO:
                publico = ("operacao", "diretoria") if k["dias"] > DIRETORIA_DIAS else ("operacao",)
                out.append({**_av.aviso("reajuste_apostilamento", "atencao",
                                        f"pleito da data-base {base} enviado há {k['dias']} dias; "
                                        f"apostilamento pendente", c["id"], nome, dias=k["dias"],
                                        publico=publico, destino=destino,
                                        data=(k.get("pedido") or k["pleito"])["enviado_em"][:10], sentido="desde"),
                            "data_base_mes": k["data_base_mes"]})
    return out
