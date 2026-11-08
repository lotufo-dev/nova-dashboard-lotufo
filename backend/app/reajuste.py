"""Ciclo do reajuste por data-base (spec 2026-09-21 §7.2), bloco 7.

O sistema nao calcula indice nem valor. Sabe so' o calendario: o reajuste vale a partir do MES do
aniversario (OT 028/2015/CGE item 3.2.1; clausula 11.45 SINFRA); o aviso comeca 30 dias antes do 1o dia
desse mes; o ciclo fecha com o APOSTILAMENTO, nao com o oficio (reenviado a cada aditivo).
"""
import datetime
import json
import re

from app import auditoria, avisos as _av, contratos, db, dinheiro, tempo

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


def aditivo_de_reajuste(a: str, com_corrigido: bool = False) -> str:
    """Issue #390: na SES o reajuste anual sai por termo aditivo de valor (`natureza: reajuste`, migracao 046), nao por
    apostilamento. O aditivo assinado e nao cancelado fecha o ciclo como o apostilamento fecha. Com valor: o misto so'
    de prazo (delta zero) nao concede reajuste (gate Sol, PR #407). Condicao SQL sobre o alias `a` de `aditivos`.

    Issue #409 (migracao 059): aditivo corrigido por outro aditivo de reajuste (`corrige_chave` do corretor) nao vale,
    como o apostilamento corrigido por outro apostilamento de reajuste (`_termo_vale`); numa cadeia (TA3 corrige TA2,
    que corrige TA1) so' o ultimo vale. O aditivo de prazo ou de execucao que corrige um de reajuste nao o tira (corrige
    outra coisa nele). `com_corrigido`: o aditivo de reajuste mesmo que corrigido (o aplicar, para achar o pleito que
    o corrigido atendia)."""
    sql = (f"{a}.status='assinado' AND {a}.cancelado_em IS NULL AND {a}.natureza='reajuste' "
           f"AND {a}.tipo IN ('valor','misto') AND {a}.delta_valor_centavos <> 0 AND {a}.data_assinatura IS NOT NULL")
    if com_corrigido:
        return sql
    return (f"{sql} AND NOT EXISTS (SELECT 1 FROM aditivos x WHERE x.contrato_id = {a}.contrato_id "
            f"AND x.corrige_chave = {a}.chave_cadastro AND {aditivo_de_reajuste('x', com_corrigido=True)})")


def ciclo_do_aditivo(mes_base: str, data_assinatura: str) -> int | None:
    """O ciclo que o aditivo de reajuste fecha: o do ultimo aniversario da data-base ate' a assinatura (inclusive).
    Assinado antes do primeiro aniversario, nenhum."""
    data = datetime.date.fromisoformat(data_assinatura[:10])
    anos = [y for y in range(int(mes_base[:4]) + 1, data.year + 1) if aniversario(mes_base, y) <= data]
    return max(anos) if anos else None


def base_e_ciclo_do_aditivo(r, unica: str | None) -> tuple[str | None, int | None]:
    """A data-base e o ciclo que o aditivo de reajuste atende, resolvidos num lugar so' (rodada 2, PR #407): a base
    guardada no aditivo (migracao 058: a declarada, senao a unica de quando foi aplicado), senao a base unica de agora
    (`unica`); o ciclo guardado (o `ciclo` declarado), senao o da data (`ciclo_do_aditivo`). Sem base, nenhum dos dois:
    com mais de uma data-base e nada guardado, nao se adivinha."""
    base = r["data_base_mes"] or unica
    if base is None:
        return None, None
    return base, r["ciclo_reajuste"] or ciclo_do_aditivo(base, r["data_assinatura"])


def _como_termo(r) -> dict:
    """O aditivo no formato do apostilamento que a aba e os avisos leem (chave, tipo, numero, data, dados)."""
    return {"id": r["id"], "chave": r["chave_cadastro"], "tipo": f"aditivo_{r['tipo']}", "numero": r["numero"],
            "data": r["data_assinatura"][:10], "dados": {}, "origem": "aditivo"}


def _aditivo_do_ciclo(conn, contrato_id: int, mes_base: str, ciclo: int, unica: bool) -> dict | None:
    """Sem pleito enviado: o aditivo de reajuste cuja base e ciclo (`base_e_ciclo_do_aditivo`) sao estes. Um aditivo
    so' fecha um ciclo (gate Sol, rodada extra, PR #407): o ja' ligado a pleito de outro ciclo ou base atende aquele, e
    nao este pela data (a janela entre a migracao 058 e o primeiro `aplicar`, com base e ciclo ainda vazios)."""
    for r in conn.execute(f"SELECT * FROM aditivos a WHERE a.contrato_id=? AND {aditivo_de_reajuste('a')} "
                          "AND NOT EXISTS (SELECT 1 FROM pleitos p WHERE p.contrato_id = a.contrato_id "
                          "AND p.instrumento_chave = a.chave_cadastro AND NOT (p.data_base_mes = ? AND p.ciclo = ?)) "
                          "ORDER BY data_assinatura DESC, id DESC", (contrato_id, mes_base, ciclo)):
        if base_e_ciclo_do_aditivo(r, mes_base if unica else None) == (mes_base, ciclo):
            return _como_termo(r)
    return None


def _aditivo_do_pleito(conn, contrato_id: int, pleito: dict, unica: bool) -> dict | None:
    """O aditivo de reajuste que o cadastro ligou ao pleito (`instrumento_chave` = chave do aditivo no cadastro), se
    ele e' da data-base do pleito. Aditivo sem base guardada so' vale com data-base unica (gate Sol, PR #407): a ligacao
    feita quando o contrato tinha uma so' deixa de dizer qual atende depois que entra a segunda. Com base ou ciclo
    guardados (migracao 058), o par inteiro tem de ser o do pleito (gate Sol, rodada extra): um aditivo nao fecha dois
    ciclos."""
    if not pleito.get("instrumento_chave"):
        return None
    r = conn.execute(f"SELECT * FROM aditivos a WHERE a.contrato_id=? AND a.chave_cadastro=? "
                     f"AND {aditivo_de_reajuste('a')}", (contrato_id, pleito["instrumento_chave"])).fetchone()
    if r is None:
        return None
    base, ciclo = base_e_ciclo_do_aditivo(r, pleito["data_base_mes"] if unica else None)
    guardado = r["data_base_mes"] is not None or r["ciclo_reajuste"] is not None
    if base != pleito["data_base_mes"] or (guardado and ciclo != pleito["ciclo"]):
        return None
    return _como_termo(r)


def aditivos_de_reajuste(conn, contrato_id: int) -> list[dict]:
    """Os aditivos que valem como termo de reajuste (o mesmo criterio do ciclo), para a aba dizer qual atendeu cada
    pleito (gate Sol, PR #407): os de base determinavel (guardada, ou a unica do contrato)."""
    unica = conn.execute("SELECT COUNT(*) FROM contrato_datas_base WHERE contrato_id=?",
                         (contrato_id,)).fetchone()[0] == 1
    return [_como_termo(r) for r in conn.execute(
        f"SELECT * FROM aditivos a WHERE a.contrato_id=? AND {aditivo_de_reajuste('a')} "
        f"AND (a.data_base_mes IS NOT NULL OR ?) ORDER BY a.data_assinatura, a.id", (contrato_id, unica))]


def _termo_do_pedido(conn, contrato_id: int, pleito: dict, unica: bool) -> dict | None:
    """O termo ligado ao pleito ou, subindo pelas reiteracoes (`reemite_pleito_id`), ao pedido que elas reiteram
    (revisor, PR #317): a reiteracao nao traz cronograma, entao o termo que atendeu o pedido tambem fecha a
    reiteracao enviada depois dele. A reemissao do cronograma e' pedido novo e para a subida: espera o termo dela."""
    p, vistos = pleito, set()
    while p is not None and p["id"] not in vistos:
        vistos.add(p["id"])
        termo = _termo_do_pleito(conn, contrato_id, p) or _aditivo_do_pleito(conn, contrato_id, p, unica)
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
    pleito enviado registrado, o apostilamento do ciclo (`_apostilamento`). O aditivo de valor de reajuste (issue
    #390) vale como termo nos dois caminhos."""
    pl = _pleito(conn, contrato_id, mes_base, ciclo)
    if pl:
        return _termo_do_pedido(conn, contrato_id, pl, unica)
    return (_apostilamento(conn, contrato_id, mes_base, ciclo, unica)
            or _aditivo_do_ciclo(conn, contrato_id, mes_base, ciclo, unica))


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
    pede a reemissao do cronograma de reajuste. Sem `desde`, nenhum. O aditivo de natureza reajuste (issue #390) e'
    o termo que concede o reajuste e nao pede reemissao, salvo se tambem muda o prazo (misto com data nova, revisor
    e gate Sol, PR #407). Aditivo cancelado nao conta (gate Sol, rodada 2).

    Regra do misto de reajuste com prazo novo (gate Sol, rodada 2, PR #407): no ciclo que ele concede (o termo
    ligado ao pleito), o ciclo esta' apostilado e nao ha' o que reemitir; a prorrogacao pede reemissao no ciclo cujo
    pleito ja' tinha saido antes dele sem ser atendido por ele (este criterio, em `ciclos`), e o pleito dos ciclos
    seguintes, enviado depois do aditivo, ja' sai com o prazo novo."""
    if not desde:
        return None
    r = conn.execute(f"SELECT * FROM aditivos WHERE contrato_id=? AND {_PEDE_REEMISSAO} "
                     "AND substr(data_assinatura, 1, 10) > ? ORDER BY data_assinatura DESC, id DESC LIMIT 1",
                     (contrato_id, desde[:10])).fetchone()
    return dict(r) if r else None


# O aditivo que pede a reemissao do cronograma de reajuste (`aditivo_depois`), um criterio so' para o estado `reemitir`
# e para a linha do tempo do ciclo (`aditivos_do_ciclo`).
_PEDE_REEMISSAO = ("status='assinado' AND cancelado_em IS NULL "
                   "AND NOT (COALESCE(natureza, '') = 'reajuste' AND nova_execucao_fim IS NULL "
                   "AND nova_vigencia_fim IS NULL) "
                   "AND tipo IN ('prazo','valor','misto') AND data_assinatura IS NOT NULL")


def aditivos_do_ciclo(conn, contrato_id: int, k: dict) -> list[dict]:
    """Issue #275 (spec 2026-10-20 §2.2, linha do tempo do ciclo): os aditivos que pedem reemissao (`_PEDE_REEMISSAO`)
    assinados depois do primeiro pleito enviado do ciclo `k` (um item de `ciclos`) e, com o ciclo fechado, ate' a data
    do termo. Antes do primeiro pleito o aditivo ja' entra no cronograma do pedido; depois do termo, e' de outro ciclo.
    O termo que e' ele mesmo um aditivo (issue #390) fica de fora: na linha do tempo ele e' o termo."""
    desde = conn.execute("SELECT MIN(enviado_em) FROM pleitos WHERE contrato_id=? AND tipo='reajuste' "
                         "AND data_base_mes=? AND ciclo=? AND situacao='enviado'",
                         (contrato_id, k["data_base_mes"], k["ciclo"])).fetchone()[0]
    if not desde:
        return []
    termo = k.get("apostilamento")
    ate = str(termo["data"])[:10] if termo else None
    rows = conn.execute(f"SELECT id, numero, tipo, data_assinatura FROM aditivos WHERE contrato_id=? "
                        f"AND {_PEDE_REEMISSAO} AND substr(data_assinatura, 1, 10) > ? "
                        f"AND (? IS NULL OR substr(data_assinatura, 1, 10) <= ?) ORDER BY data_assinatura, id",
                        (contrato_id, str(desde)[:10], ate, ate))
    return [dict(r) for r in rows
            if not (termo and termo.get("origem") == "aditivo" and termo.get("id") == r["id"])]


def linhas_do_tempo(conn, contrato_id: int) -> list[dict]:
    """Issue #275 (Gate Sol, rodada 1 da PR #438): a linha do tempo de cada ciclo com pleito enviado, de cada data-base
    do contrato, e nao so' do corrente: o termo que fecha o ciclo (`apostilamento_do_ciclo`) e os aditivos dele
    (`aditivos_do_ciclo`). Os pleitos a aba ja' tem."""
    bases = [r[0] for r in conn.execute("SELECT mes FROM contrato_datas_base WHERE contrato_id=? ORDER BY mes",
                                        (contrato_id,))]
    out = []
    for base, ciclo in conn.execute("SELECT DISTINCT data_base_mes, ciclo FROM pleitos WHERE contrato_id=? "
                                    "AND tipo='reajuste' AND situacao='enviado' AND ciclo IS NOT NULL "
                                    "ORDER BY data_base_mes, ciclo", (contrato_id,)).fetchall():
        if base not in bases:
            continue
        termo = apostilamento_do_ciclo(conn, contrato_id, base, ciclo, len(bases) == 1)
        out.append({"data_base_mes": base, "ciclo": ciclo, "termo": termo,
                    "aditivos": aditivos_do_ciclo(conn, contrato_id,
                                                  {"data_base_mes": base, "ciclo": ciclo, "apostilamento": termo}),
                    # issue #586: as respostas do orgao aos pleitos do ciclo (indeferimento, deferimento parcial)
                    "respostas": respostas_do_ciclo(conn, contrato_id, base, ciclo)})
    return out


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
_MEDICAO_PEDIDA = ("planilha_gerada", "planilha_enviada", "boletim_recebido", "espelho_gerado", "espelho_enviado")
# `protocolada` fica de fora de proposito: o protocolo promove `prevista` e `planilha_gerada` direto a `protocolada`
# (`medicoes.ESTADOS_PROMOVIDOS_PELO_PROTOCOLO`), e o envio por fora e a carga legada tambem, sem nota. Protocolada
# so' conta como faturada com a nota (`nota_emitida_em`) ou NF ativa alocada; senao, pedida.
_MEDICAO_FATURADA = ("nota_emitida", "nf_emitida", "recebida")
_PEDIDA, _APROVADA, _APOSTILADA, _FATURADA, _RECEBIDA = 1, 2, 3, 4, 5


def _passo_da_medicao(m, com_nf: bool, com_atesto: bool) -> int:
    """O passo de `ESTADOS_COMPETENCIA` a que a medicao de reajuste chegou sozinha (o apostilamento e' do termo).
    Enquanto o motor de medicao nao cobre tudo, o valor pedido gravado ja' conta como pedida; aprovada e' o boletim
    registrado (evento de atesto ou valor aprovado)."""
    me = m["estado"]
    if me == "recebida":
        return _RECEBIDA
    if me in _MEDICAO_FATURADA or com_nf or m["nota_emitida_em"]:
        return _FATURADA
    if me == "boletim_recebido" or com_atesto or m["valor_atestado_centavos"] is not None:
        return _APROVADA
    if me in _MEDICAO_PEDIDA or me == "protocolada" or m["valor_protocolado_centavos"] is not None:
        return _PEDIDA
    return 0


# Issue #275 (spec 2026-10-20 §2.2, avisos do motor de apostilamento): a marca de cada competencia na aba Reajuste.
TOLERANCIA_PREVISAO_CENTAVOS = 100           # "Reajuste fora da previsao": diferenca de ate' R$ 1,00 nao conta
_COM_BOLETIM = ("aprovada", "faturada", "recebida")
_COM_NOTA = ("faturada", "recebida")


def vigente_da_competencia(x: dict) -> int | None:
    """O previsto vigente com que o pedido se compara: o apostilado em valor, senao o previsto do pleito ou digitado
    (a origem mais forte, `ORDEM_ORIGEM`)."""
    return x["apostilado_centavos"] if x["apostilado_centavos"] is not None else x["previsto_centavos"]


def avisos_da_competencia(x: dict, coberta: bool, justificada: bool = False) -> list[str]:
    """Os avisos de uma linha de `competencias_por_ciclo` (spec 2026-10-20 §2.2, tabela de avisos):

    - `fora_da_previsao`: pedido diferente do previsto vigente por mais de R$ 1,00. O vigente e' o da origem mais
      forte (`ORDEM_ORIGEM`): o apostilado em valor, senao o previsto do pleito ou digitado. Sem previsto, nada a
      comparar.
    - `sem_apostilamento`: aprovada ou faturada (ou recebida) sem termo que cubra a competencia.
    - `nota_antes_do_apostilamento`: nota emitida em competencia nao apostilada (o critico da spec). Some quando o
      apostilamento e' carregado (a coluna "some quando" da spec), como o anterior.

    `coberta`: algum termo cobre a competencia (`cobertura_das_competencias`, o criterio unico da aba e da diretoria).
    `justificada`: a operacao justificou a diferenca e pedido e previsto sao os da justificativa (issue #274,
    `justificativa_vigente`): o `fora_da_previsao` sai, como na reapresentacao."""
    out = []
    vigente = vigente_da_competencia(x)
    if x["pedido_centavos"] is not None and vigente is not None and not justificada \
            and abs(x["pedido_centavos"] - vigente) > TOLERANCIA_PREVISAO_CENTAVOS:
        out.append("fora_da_previsao")
    if not coberta and x["estado"] in _COM_BOLETIM:
        out.append("sem_apostilamento")
        if x["estado"] in _COM_NOTA:
            out.append("nota_antes_do_apostilamento")
    return out


def _periodo_do_termo(d: dict) -> tuple[str, str] | None:
    per = d.get("periodo")
    if isinstance(per, dict) and per.get("de") and per.get("ate"):
        return str(per["de"]), str(per["ate"])
    return None


def termo_sem_meses(termo: dict) -> bool:
    """O termo que fecha o ciclo sem dizer os meses que cobre: o termo aditivo de valor de reajuste (issue #390) e o
    apostilamento sem a lista `competencias` e sem `periodo`. Sem meses, o termo cobre o ciclo inteiro, como em
    `ciclos`. O `periodo` sozinho diz os meses (issue #444): o cadastro o trata como limite do termo
    (`cadastro_arquivos._periodo_e_competencias`), e o termo cobre so' os meses dele (`termo_cobre_o_mes`)."""
    if termo.get("origem") == "aditivo":
        return True
    d = termo.get("dados") or {}
    return not (d.get("competencias") or _periodo_do_termo(d))


def termo_cobre_o_mes(termo: dict, competencia: str) -> bool:
    """O termo do ciclo cobre a competencia sem ela estar `apostilada`: o termo sem meses (`termo_sem_meses`) cobre o
    ciclo inteiro; o apostilamento so' com `periodo` (sem lista nem percentual, que ja' marcam a competencia
    `apostilada`) cobre so' os meses do periodo (issue #444)."""
    if termo_sem_meses(termo):
        return True
    d = termo.get("dados") or {}
    per = _periodo_do_termo(d)
    if per is None or d.get("competencias") or d.get("percentual") not in (None, ""):
        return False
    return per[0] <= competencia <= per[1]


def _termos_com_periodo(conn, contrato_id: int, unica: str | None) -> dict[tuple[str, int], list[dict]]:
    """Por (base, ciclo), todos os apostilamentos que valem (`_termo_vale`) com `periodo`, na base e no ciclo
    resolvidos como em `_percentuais` (revisor e gate Sol, rodada 1 da PR #524): o mes no periodo de qualquer termo so'
    com `periodo` fica coberto (`termo_cobre_o_mes`), seja qual for o termo que `apostilamento_do_ciclo` escolhe."""
    out: dict[tuple[str, int], list[dict]] = {}
    for r in conn.execute(f"SELECT * FROM instrumentos i WHERE i.contrato_id=? AND i.tipo='apostilamento_reajuste' "
                          f"AND {_termo_vale('i')}", (contrato_id,)):
        d = json.loads(r["dados"] or "{}")
        if _periodo_do_termo(d) is None:
            continue
        base, ciclo = base_do_termo(d, r["data_base_mes"], unica), ciclo_do_apostilamento(d, r["data"])
        if base is not None and ciclo is not None:
            out.setdefault((base, ciclo), []).append({"dados": d})
    return out


def cobertura_das_competencias(conn, contrato_id: int, grupos: list[dict]):
    """O criterio unico de "algum termo cobre a competencia" (issue #275, o mesmo da diretoria na #279), sobre os
    `grupos` de `competencias_por_ciclo`. Devolve `coberta(base, ciclo, x)` para a linha `x` do grupo (base, ciclo):

    - com data-base: a competencia `apostilada`; ou o ciclo fechado pelo termo do ciclo (`apostilamento_do_ciclo`) sem
      meses (`termo_sem_meses`); ou o mes no periodo de qualquer apostilamento que vale so' com `periodo`, na mesma
      base e ciclo (`termo_cobre_o_mes`, issue #444);
    - sem data-base (medicao de base incerta, contrato de duas): coberta so' quando toda data-base em que o mes tem
      reajuste a cobre; sem nenhuma, nenhum termo a cobre."""
    bases = [r[0] for r in conn.execute("SELECT mes FROM contrato_datas_base WHERE contrato_id=? ORDER BY mes",
                                        (contrato_id,))]
    termos: dict[tuple[str, int], dict | None] = {}
    com_periodo = _termos_com_periodo(conn, contrato_id, bases[0] if len(bases) == 1 else None)

    def fechado(base: str, ciclo: int, comp: str) -> bool:
        if (base, ciclo) not in termos:
            termos[(base, ciclo)] = apostilamento_do_ciclo(conn, contrato_id, base, ciclo, len(bases) == 1)
        termo = termos[(base, ciclo)]
        if termo is not None and termo_cobre_o_mes(termo, comp):
            return True
        return any(termo_cobre_o_mes(t, comp) for t in com_periodo.get((base, ciclo), ()))

    linhas: dict[tuple[str, str], list[tuple[int | None, bool]]] = {}
    for g in grupos:
        if g["data_base_mes"] is not None:
            for x in g["competencias"]:
                linhas.setdefault((g["data_base_mes"], x["competencia"]), []).append((g["ciclo"], x["apostilada"]))

    def na_base(base: str, comp: str) -> bool | None:
        """None: o mes nao tem reajuste nesta data-base (antes do 1o aniversario dela)."""
        ls = linhas.get((base, comp)) or [(_ciclo_da_competencia(base, comp), False)]
        if all(y is None for y, _ in ls):
            return None
        return any(a or (y is not None and fechado(base, y, comp)) for y, a in ls)

    def coberta(base: str | None, ciclo: int | None, x: dict) -> bool:
        if base is not None:
            return x["apostilada"] or (ciclo is not None and fechado(base, ciclo, x["competencia"]))
        vs = [v for v in (na_base(b, x["competencia"]) for b in bases) if v is not None]
        return bool(vs) and all(vs)

    return coberta


def _medido_da_medicao(m, faturado: int | None) -> int | None:
    """O ja' medido de uma medicao de reajuste: o faturado (NF alocada); sem ele, o aprovado; sem ele, o pedido."""
    for v in (faturado, m["valor_atestado_centavos"], m["valor_protocolado_centavos"]):
        if v is not None:
            return v
    return None


def _soma(valores) -> int | None:
    """Soma dos centavos gravados; None quando nenhum foi gravado (zero gravado e' zero)."""
    v = [x for x in valores if x is not None]
    return sum(v) if v else None


def _meses(de: str, ate: str) -> list[str]:
    """Os meses AAAA-MM de `de` a `ate`, inclusive."""
    out, (a, m) = [], (int(de[:4]), int(de[5:7]))
    while f"{a:04d}-{m:02d}" <= ate:
        out.append(f"{a:04d}-{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return out
# ciclo enviado e ainda sem apostilamento: com ou sem cronograma a reemitir, o aviso e a diretoria seguem valendo
SEM_APOSTILAMENTO = ("apostilamento_pendente", "reemitir")


def _ciclo_da_competencia(mes_base: str, competencia: str) -> int | None:
    """O ciclo (ano do aniversario) a que a competencia pertence: do mes do aniversario de Y ao mes anterior ao de
    Y+1. Antes do 1o aniversario, nenhum (ainda nao ha' reajuste)."""
    y = int(competencia[:4]) - (1 if competencia[5:7] < mes_base[5:7] else 0)
    return y if y > int(mes_base[:4]) else None


def _percentuais(conn, contrato_id: int, unica: str | None) -> list[dict]:
    """Termos que valem (`_termo_vale`) com `percentual` e `periodo` (o percentual da MT-PAR), o mais novo primeiro.
    Termo com `periodo` e sem `percentual` so' delimita a lista explicita de competencias (`competencias_apostiladas`):
    mes do periodo fora da lista nao e' apostilado."""
    out = []
    for r in conn.execute(f"SELECT * FROM instrumentos i WHERE i.contrato_id=? AND i.tipo='apostilamento_reajuste' "
                          f"AND {_termo_vale('i')} ORDER BY {_ordem_termo('i')}", (contrato_id,)):
        d = json.loads(r["dados"] or "{}")
        per = d.get("periodo")
        if d.get("percentual") in (None, "") or not isinstance(per, dict) or not per.get("de") or not per.get("ate"):
            continue
        base, ciclo = base_do_termo(d, r["data_base_mes"], unica), ciclo_do_apostilamento(d, r["data"])
        if base is None or ciclo is None:
            continue
        out.append({"base": base, "ciclo": ciclo, "de": str(per["de"]), "ate": str(per["ate"]), "chave": r["chave"],
                    "percentual": d.get("percentual")})
    return out


def competencias_por_ciclo(conn, contrato_id: int) -> list[dict]:
    """Issue #273: por data-base e ciclo, cada competencia com o estado derivado (`ESTADOS_COMPETENCIA`) e o valor de
    cada fonte: previsto (pleito ou manual), pedido e aprovado (medicao de reajuste), apostilado (competencia do
    termo, ou percentual com `periodo` que a cobre), faturado (NF alocada) e recebido (baixa no RM). So' le; nada se
    calcula alem de somar o que ja' esta' gravado.

    A medicao de reajuste vai para a data-base e o ciclo gravados nela; sem eles (medicao anterior ao motor), para a
    unica data-base do contrato e para o ciclo da previsao da competencia ou, sem previsao, o do aniversario. Com duas
    datas-base e nada gravado, se so' uma tem previsao da competencia, vai para ela; senao entra uma vez so' no grupo
    sem data-base (`data_base_mes` e `ciclo` nulos, linhas com `data_base_incerta`): nada some em silencio e nada
    conta em dobro quando se somam as datas-base. Cancelada ou desistida nao conta.

    Varias medicoes na mesma competencia (complemento): pedido, aprovado e faturado sao a soma delas, e o medido nao
    recebido, a das ainda nao recebidas (o aprovado de cada uma, senao o pedido); `medicoes` lista
    os numeros (e `medicoes_pedido`, `medicoes_aprovado`, `medicoes_nota`, so' as que entraram em cada soma, issue
    #275), e o estado e a medicao principal sao os da mais adiantada (empate: maior numero). O faturado so' conta
    NF da coligada da entidade do contrato (em consorcio, a fatura cheia do consorcio, e nao tambem a NFS-e da
    Lotufo pela cota); sem coligada no cadastro, todas. Mes do periodo de um percentual (MT-PAR) entra mesmo sem
    previsao digitada."""
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
            "apostilamento_chave": None, "medicao_orgao": None, "faturado_centavos": None, "recebida_em": None, "recebidas": [],
            "medido_nao_recebido_centavos": None, "medicoes": [], "medicoes_pedido": [], "medicoes_aprovado": [],
            "medicoes_nota": [], "data_base_incerta": False, "medido_centavos": None, "previsao_id": None, "_medicoes": []})

    for p in previsoes_vigentes(conn, contrato_id, sem_apostilamento=True):
        x = linha(p["data_base_mes"], p["ciclo"], p["competencia"])
        x.update(previsto_centavos=p["valor_previsto_centavos"], previsto_origem=p["origem"], previsao_id=p["id"])
    for a in competencias_apostiladas(conn, contrato_id):
        x = linha(a["data_base_mes"], a["ciclo"], a["competencia"])
        x.update(apostilada=True, apostilado_centavos=a["valor_centavos"], apostilamento_chave=a["instrumento_chave"],
                 medicao_orgao=a["medicao"])
    percentuais = _percentuais(conn, contrato_id, unica)
    for t in percentuais:
        for comp in _meses(t["de"], t["ate"]):
            linha(t["base"], t["ciclo"], comp)

    previstas: dict[tuple[str, str], set[int]] = {}
    for base, ciclo, comp in linhas:
        previstas.setdefault((base, comp), set()).add(ciclo)
    coligada = conn.execute("SELECT e.coligada_rm FROM contratos c LEFT JOIN entidades e ON e.id = c.entidade_id "
                            "WHERE c.id=?", (contrato_id,)).fetchone()[0]
    faturado, com_nf = {}, set()
    for r in conn.execute(
            # so' NF elegivel (da coligada do contrato) cria o grupo: a NFS-e da Lotufo em obra de consorcio nem
            # fatura nem marca `faturada` (como `diretoria._notas_em_aberto`)
            "SELECT a.medicao_id, SUM(a.valor_alocado_centavos) "
            "FROM nf_alocacoes a JOIN notas_fiscais n ON n.id = a.nota_id JOIN medicoes m ON m.id = a.medicao_id "
            "WHERE m.contrato_id=? AND a.desfeita_em IS NULL AND n.situacao = 'ativa' "
            "AND (? IS NULL OR n.coligada = ?) GROUP BY a.medicao_id",
            (contrato_id, coligada, coligada)):
        com_nf.add(r[0])
        faturado[r[0]] = r[1]
    com_atesto = {r[0] for r in conn.execute("SELECT DISTINCT e.medicao_id FROM medicao_atestos e "
                                             "JOIN medicoes m ON m.id = e.medicao_id WHERE m.contrato_id=?",
                                             (contrato_id,))}
    for m in conn.execute("SELECT * FROM medicoes WHERE contrato_id=? AND tipo='reajuste' "
                          "AND estado NOT IN ('cancelada','desistida') ORDER BY numero, id", (contrato_id,)):
        comp = m["competencia"]
        if m["data_base_mes"] or unica:
            candidatas = [m["data_base_mes"] or unica]
        else:
            candidatas = [b for b in bases if (b, comp) in previstas] or bases
        passo = _passo_da_medicao(m, m["id"] in com_nf, m["id"] in com_atesto)
        if len(candidatas) != 1:
            # data-base ambigua: entra uma vez so', no grupo sem data-base, para nada contar em dobro
            x = linha(None, None, comp)
            x["_medicoes"].append((passo, m["numero"], m))
            x["data_base_incerta"] = True
            continue
        base = candidatas[0]
        ciclo = m["ciclo"]
        if ciclo is None:
            ciclos_previstos = previstas.get((base, comp), set())
            ciclo = next(iter(ciclos_previstos)) if len(ciclos_previstos) == 1 \
                else _ciclo_da_competencia(base, comp)
        if ciclo is None:
            continue
        linha(base, ciclo, comp)["_medicoes"].append((passo, m["numero"], m))

    grupos: dict[tuple[str | None, int | None], list[dict]] = {}
    # o grupo sem data-base (medicoes de base ambigua) vai por ultimo
    for (base, ciclo, comp), x in sorted(linhas.items(), key=lambda kv: (kv[0][0] is None, kv[0][0] or "",
                                                                        kv[0][1] or 0, kv[0][2])):
        if not x["apostilada"]:
            t = next((t for t in percentuais if (t["base"], t["ciclo"]) == (base, ciclo)
                      and t["de"] <= comp <= t["ate"]), None)
            if t:
                x.update(apostilada=True, apostilado_percentual=t["percentual"], apostilamento_chave=t["chave"])
        ms = x.pop("_medicoes")
        passo = 0
        if ms:
            passo, _, m = max(ms, key=lambda v: (v[0], v[1]))
            x.update(medicao_id=m["id"], medicao_numero=m["numero"], medicao_estado=m["estado"],
                     recebida_em=max((v[2]["recebida_em"] for v in ms if v[2]["recebida_em"]), default=None),
                     # issue #445: todas as baixas da competencia (numero e data), a celula mostra a ultima
                     recebidas=sorted(({"numero": v[1], "recebida_em": v[2]["recebida_em"]} for v in ms
                                       if v[2]["recebida_em"]), key=lambda r: r["numero"]),
                     medicoes=sorted(v[1] for v in ms),
                     pedido_centavos=_soma(v[2]["valor_protocolado_centavos"] for v in ms),
                     aprovado_centavos=_soma(v[2]["valor_atestado_centavos"] for v in ms),
                     faturado_centavos=_soma(faturado.get(v[2]["id"]) for v in ms),
                     # issue #279: o ja' medido e ainda nao recebido, medicao a medicao (o aprovado quando houver,
                     # senao o pedido): pedida, aprovada ou faturada
                     medido_nao_recebido_centavos=_soma(
                         v[2]["valor_atestado_centavos"] if v[2]["valor_atestado_centavos"] is not None
                         else v[2]["valor_protocolado_centavos"] for v in ms if _PEDIDA <= v[0] < _RECEBIDA),
                     # issue #275: as medicoes que entraram em cada soma, para a origem de cada celula da aba
                     medicoes_pedido=sorted(v[1] for v in ms if v[2]["valor_protocolado_centavos"] is not None),
                     medicoes_aprovado=sorted(v[1] for v in ms if v[2]["valor_atestado_centavos"] is not None),
                     medicoes_nota=sorted(v[1] for v in ms if faturado.get(v[2]["id"]) is not None),
                     # issue #274 (decisao do Leo de 08/11/2026): o ja' medido, medicao a medicao (o faturado; sem
                     # ele, o aprovado; sem ele, o pedido), somado: o complemento aprovado sem nota tambem conta
                     medido_centavos=_soma(_medido_da_medicao(v[2], faturado.get(v[2]["id"])) for v in ms))
        x["estado"] = ESTADOS_COMPETENCIA[max(passo, _APOSTILADA if x["apostilada"] else 0)]
        grupos.setdefault((base, ciclo), []).append(x)
    out = [{"data_base_mes": b, "ciclo": y, "competencias": xs} for (b, y), xs in grupos.items()]
    # issue #275: a marca de aviso de cada competencia, pelo criterio unico de cobertura (o grupo sem data-base olha
    # as linhas das datas-base, ja' completas aqui)
    coberta = cobertura_das_competencias(conn, contrato_id, out)
    justificativas = _justificativas(conn, contrato_id)
    for g in out:
        for x in g["competencias"]:
            # issue #274: a justificativa do "fora da previsao" so' vale com o pedido e o previsto de quando foi dada
            j = justificativa_vigente(x, justificativas.get((g["data_base_mes"], g["ciclo"], x["competencia"])))
            x["justificativa"] = j
            x["avisos"] = avisos_da_competencia(x, coberta(g["data_base_mes"], g["ciclo"], x), justificada=j is not None)
    return out


# Issue #274 (spec 2026-10-20 §2.2; decisao do Leo de 08/11/2026): justificativa do "Reajuste fora da previsao"
MIN_JUSTIFICATIVA = 10


def _justificativas(conn, contrato_id: int) -> dict[tuple[str, int, str], dict]:
    """A ultima justificativa de cada competencia (data-base, ciclo, competencia), com o nome de quem a deu. As
    justificativas sao eventos (migracao 072): a leitura escolhe a mais recente."""
    out = {}
    for r in conn.execute("SELECT j.*, u.nome AS usuario FROM reajuste_justificativas j "
                          "LEFT JOIN usuarios u ON u.id = j.usuario_id WHERE j.contrato_id=? ORDER BY j.id",
                          (contrato_id,)):
        out[(r["data_base_mes"], r["ciclo"], r["competencia"])] = dict(r)
    return out


def _ref_previsto(x: dict) -> str:
    """O evento que da' o previsto vigente da linha (`vigente_da_competencia`): o termo, quando o apostilado tem valor;
    senao a previsao (pleito ou digitada) vigente."""
    if x["apostilado_centavos"] is not None:
        return f"apostilamento:{x['apostilamento_chave']}"
    return f"previsao:{x['previsao_id']}"


def justificativa_vigente(x: dict, j: dict | None) -> dict | None:
    """A justificativa que ainda vale para a linha `x`: a ultima, se o pedido e o previsto vigente de agora sao os
    que ela guardou, nos centavos e na identidade (rodada 1 da PR #579, gate Sol): o mesmo evento de previsto
    (`_ref_previsto`) e as mesmas medicoes no pedido. Previsao nova com o valor de antes (R$ 100 -> 90 -> 100) nao
    revive a justificativa. Se algo mudou, nenhuma (o aviso volta)."""
    if j is None or j["pedido_centavos"] != x["pedido_centavos"] or j["previsto_centavos"] != vigente_da_competencia(x) \
            or j["previsto_ref"] != _ref_previsto(x) or json.loads(j["medicoes"]) != x["medicoes_pedido"]:
        return None
    return {"texto": j["texto"], "usuario": j["usuario"], "criado_em": j["criado_em"],
            "pedido_centavos": j["pedido_centavos"], "previsto_centavos": j["previsto_centavos"]}


def justificar(conn, usuario_id: int, contrato_id: int, data_base_mes: str, ciclo: int, competencia: str,
               texto: str) -> int:
    """Registra a justificativa do pedido fora da previsao de uma competencia, com o pedido e o previsto vigente de
    agora (os que ela explica). So' na competencia que tem o aviso agora."""
    texto = (texto or "").strip()
    if len(texto) < MIN_JUSTIFICATIVA:
        raise ValueError(f"Escreva a justificativa com pelo menos {MIN_JUSTIFICATIVA} caracteres")
    with db.mutacao(conn):
        # dentro do BEGIN IMMEDIATE: o pedido e o previsto gravados sao os que a leitura viu
        g = next((g for g in competencias_por_ciclo(conn, contrato_id)
                  if (g["data_base_mes"], g["ciclo"]) == (data_base_mes, ciclo)), None)
        x = next((x for x in g["competencias"] if x["competencia"] == competencia), None) if g else None
        if x is None or "fora_da_previsao" not in x["avisos"]:
            raise ValueError("O pedido desta competência não está fora da previsão")
        previsto = vigente_da_competencia(x)
        ref, medicoes = _ref_previsto(x), json.dumps(x["medicoes_pedido"])
        jid = conn.execute("INSERT INTO reajuste_justificativas (contrato_id, data_base_mes, ciclo, competencia, "
                           "texto, pedido_centavos, previsto_centavos, previsto_ref, medicoes, usuario_id) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (contrato_id, data_base_mes, ciclo, competencia, texto, x["pedido_centavos"], previsto,
                            ref, medicoes, usuario_id)).lastrowid
        auditoria.registrar(conn, usuario_id, "reajuste.justificativa", "contrato", contrato_id, None,
                            {"justificativa_id": jid, "data_base_mes": data_base_mes, "ciclo": ciclo,
                             "competencia": competencia, "pedido_centavos": x["pedido_centavos"],
                             "previsto_centavos": previsto, "previsto_ref": ref, "medicoes": x["medicoes_pedido"],
                             "texto": texto})
    return jid


def apostilamento_da_medicao(conn, medicao: dict, grupos: list[dict] | None = None) -> dict | None:
    """Issue #278: o apostilamento que cobre a competencia desta medicao de reajuste (chave, numero e data do termo),
    pela mesma leitura da aba Reajuste (`competencias_por_ciclo`): a competencia na lista do termo ou no `periodo` do
    percentual (MT-PAR), so' termo que vale. None quando nenhum cobre, quando a competencia nao entra em ciclo (antes
    do 1o aniversario) ou quando a data-base da medicao e' incerta. `grupos`: a leitura ja' feita do contrato (varias
    medicoes de uma vez). O numero identifica a medicao de reajuste no contrato (UNIQUE contrato, numero, tipo)."""
    for g in grupos if grupos is not None else competencias_por_ciclo(conn, medicao["contrato_id"]):
        for x in g["competencias"]:
            if x["competencia"] != medicao["competencia"] or medicao["numero"] not in x["medicoes"]:
                continue
            if not x["apostilada"]:
                return None
            r = conn.execute("SELECT chave, numero, data FROM instrumentos WHERE contrato_id=? "
                             "AND tipo='apostilamento_reajuste' AND chave=?",
                             (medicao["contrato_id"], x["apostilamento_chave"])).fetchone()
            return dict(r) if r else None
    return None


ORIGEM_DA_SUGESTAO = {"pleito": "previsto no pleito", "manual": "previsto"}
ESCOLHA_A_DATA_BASE = "Escolha a data-base do reajuste"


def _outras_medicoes(conn, contrato_id: int, competencia: str, numero: int | None) -> list:
    """As medicoes de reajuste ativas (fora cancelada e desistida) da competencia, menos a do `numero`."""
    return conn.execute("SELECT numero, data_base_mes, valor_protocolado_centavos FROM medicoes WHERE contrato_id=? "
                        "AND tipo='reajuste' AND competencia=? AND estado NOT IN ('cancelada','desistida') "
                        "AND numero IS NOT ? ORDER BY numero", (contrato_id, competencia, numero)).fetchall()


def sugestao_da_medicao(conn, contrato_id: int, competencia: str, numero: int | None = None) -> dict:
    """Issue #276 (spec 2026-10-20 §2.2, D7): para a medicao de reajuste da competencia, cada data-base do contrato
    com o ciclo, o valor sugerido e a origem dita na tela. O sistema nao calcula: a sugestao e' a previsao vigente da
    competencia (`previsoes_vigentes`: o apostilado manda, senao o previsto no pleito, senao o manual); sem previsao,
    nula. O ciclo e' o da previsao mais forte (a origem decide, nao o aniversario); duas previsoes da mesma forca em
    ciclos diferentes deixam o ciclo em aberto (`ciclos_em_conflito`) e nada e' sugerido. Sem previsao, o ciclo do
    aniversario (`_ciclo_da_competencia`).

    `numero`: o da medicao de reajuste que vai nascer (ou ser completada). A prevista desse nº que ja' tem pedido
    sugere o proprio pedido (nao e' trocado pelo previsto sem a pessoa ver). Outra medicao de reajuste ativa da mesma
    competencia e data-base (`ja_pedido_em`) tira a sugestao: o pedido contaria duas vezes. Previsao negativa (indice
    deflacionario) nao vira sugestao: a medicao nao guarda pedido negativo (CHECK >= 0, migracao 042); vai no
    `aviso`.

    `data_base_mes` e' a base ja' escolhida: a unica do contrato ou, com duas, a unica que tem previsao na
    competencia; senao nula (a pessoa escolhe). Contrato sem reajuste ou sem data-base: nenhuma base."""
    c = conn.execute("SELECT sem_reajuste FROM contratos WHERE id=?", (contrato_id,)).fetchone()
    if c is None or c["sem_reajuste"]:
        return {"competencia": competencia, "bases": [], "data_base_mes": None}
    termos = {r["id"]: r["numero"] for r in conn.execute(
        "SELECT id, numero FROM instrumentos WHERE contrato_id=? AND tipo='apostilamento_reajuste'", (contrato_id,))}
    vigentes = [p for p in previsoes_vigentes(conn, contrato_id) if p["competencia"] == competencia]
    linhas = conn.execute("SELECT mes, aplica_a FROM contrato_datas_base WHERE contrato_id=? ORDER BY mes",
                          (contrato_id,)).fetchall()
    unica = linhas[0]["mes"] if len(linhas) == 1 else None
    outras = _outras_medicoes(conn, contrato_id, competencia, numero)
    propria = None if numero is None else conn.execute(
        "SELECT data_base_mes, valor_protocolado_centavos FROM medicoes WHERE contrato_id=? AND tipo='reajuste' "
        "AND numero=? AND competencia=? AND estado='prevista' AND valor_protocolado_centavos IS NOT NULL",
        (contrato_id, numero, competencia)).fetchone()
    bases = []
    for b in linhas:
        mes = b["mes"]
        ps = [p for p in vigentes if p["data_base_mes"] == mes]
        forca = min((ORDEM_ORIGEM.index(p["origem"]) for p in ps), default=None)
        fortes = [p for p in ps if ORDEM_ORIGEM.index(p["origem"]) == forca]
        conflito = sorted({p["ciclo"] for p in fortes})
        p = fortes[0] if len(conflito) == 1 else None
        ciclo = p["ciclo"] if p is not None else None if conflito else _ciclo_da_competencia(mes, competencia)
        x = {"data_base_mes": mes, "aplica_a": b["aplica_a"] or "", "ciclo": ciclo, "valor_centavos": None,
             "origem": None, "origem_texto": None, "aviso": None, "tem_previsao": bool(ps),
             "ciclos_em_conflito": conflito if len(conflito) > 1 else [],
             "ja_pedido_em": [m["numero"] for m in outras if (m["data_base_mes"] or unica) in (mes, None)]}
        if p is not None:
            x["origem"] = p["origem"]
            if p["origem"] == "apostilamento":
                n = termos.get(p["instrumento_id"])
                x["origem_texto"] = f"apostilado no termo {n}" if n else "apostilado em termo sem número"
            else:
                x["origem_texto"] = ORIGEM_DA_SUGESTAO[p["origem"]]
            x["valor_centavos"] = p["valor_previsto_centavos"]
        divergente = None
        if propria is not None and (propria["data_base_mes"] or unica) == mes:
            if p is not None and p["valor_previsto_centavos"] != propria["valor_protocolado_centavos"]:
                # o pedido da prevista fica no campo, mas o apostilado (ou previsto) diferente e' dito ao lado
                divergente = f"{x['origem_texto']} em {dinheiro.format_brl(p['valor_previsto_centavos'])}"
            x.update(valor_centavos=propria["valor_protocolado_centavos"], origem="prevista",
                     origem_texto="pedido já registrado na prevista")
        if divergente:
            x["aviso"] = f"pedido já registrado na prevista; {divergente}"
        if x["ciclos_em_conflito"]:
            x["aviso"] = f"previsão em mais de um ciclo ({', '.join(map(str, x['ciclos_em_conflito']))})"
        elif x["ja_pedido_em"]:
            m = next(m for m in outras if m["numero"] == x["ja_pedido_em"][0])
            x["aviso"] = (f"já pedido na medição {m['numero']} de reajuste" if m["valor_protocolado_centavos"]
                          is not None else f"já lançado na medição {m['numero']} de reajuste")
            x.update(valor_centavos=None, origem=None, origem_texto=None)
        elif x["valor_centavos"] is not None and x["valor_centavos"] < 0:
            x["aviso"] = (f"{x['origem_texto']} em {dinheiro.format_brl(x['valor_centavos'])}; "
                          "o sistema não registra reajuste negativo")
            x.update(valor_centavos=None, origem=None, origem_texto=None)
        bases.append(x)
    com_previsao = [x for x in bases if x["tem_previsao"]]
    escolhida = bases[0] if len(bases) == 1 else com_previsao[0] if len(com_previsao) == 1 else None
    return {"competencia": competencia, "bases": bases,
            "data_base_mes": escolhida["data_base_mes"] if escolhida else None}


def _ja_esta_em(competencia: str, numero: int) -> str:
    return f"O reajuste de {_mes(competencia)} já está na medição {numero} de reajuste: o pedido contaria duas vezes"


def base_e_ciclo_da_medicao(conn, contrato_id: int, competencia: str, escolhida: str | None,
                            numero: int | None = None) -> tuple[str | None, int | None]:
    """Issue #276: a data-base e o ciclo que a medicao de reajuste grava na criacao. Com uma data-base, ela (a
    escolhida, se vier, tem de ser ela); com duas, a escolhida, e sem escolha a gravacao e' recusada
    (`ESCOLHA_A_DATA_BASE`). Contrato sem data-base (ou sem reajuste): nada a gravar. O ciclo segue a base, pela
    mesma leitura da sugestao; ciclo em aberto (previsoes da mesma forca em dois ciclos) e' recusado. Outra medicao
    de reajuste ativa da competencia e base (fora a do `numero`) recusa, com ou sem valor: vazia, o pedido entraria
    depois pela edicao de valor e contaria duas vezes (revisor, rodada 2 da PR #580)."""
    bases = sugestao_da_medicao(conn, contrato_id, competencia, numero)["bases"]
    if not bases:
        if escolhida:
            raise ValueError("Este contrato não tem data-base de reajuste no cadastro")
        return None, None
    if escolhida is None and len(bases) == 1:
        escolhida = bases[0]["data_base_mes"]
    if escolhida is None:
        raise ValueError(ESCOLHA_A_DATA_BASE)
    b = next((b for b in bases if b["data_base_mes"] == escolhida), None)
    if b is None:
        raise ValueError(f"Data-base {_mes(escolhida)} não é deste contrato")
    if b["ciclos_em_conflito"]:
        raise ValueError(f"A previsão de reajuste de {_mes(competencia)} está nos ciclos "
                         f"{' e '.join(map(str, b['ciclos_em_conflito']))} da data-base {_mes(escolhida)}; "
                         "a correção é pelo pleito ou pelo cadastro")
    if b["ciclo"] is None:
        # antes do 1o aniversario nao ha' reajuste: a medicao ficaria sem ciclo e fora da aba Reajuste
        raise ValueError(f"Competência {_mes(competencia)} é anterior ao primeiro reajuste da "
                         f"data-base {_mes(escolhida)}")
    if b["ja_pedido_em"]:
        raise ValueError(_ja_esta_em(competencia, b["ja_pedido_em"][0]))
    return b["data_base_mes"], b["ciclo"]


def conferir_pedido_sem_dobro(conn, m) -> None:
    """Revisor, rodada 2 da PR #580: o pedido informado depois na medicao de reajuste com data-base gravada (a do
    motor, issue #276) e' recusado se outra medicao de reajuste ativa da mesma competencia e data-base ja' existe.
    Medicao sem data-base gravada (anterior ao motor, ou complemento do legado) segue como antes."""
    if m["tipo"] != "reajuste" or not m["data_base_mes"]:
        return
    for o in _outras_medicoes(conn, m["contrato_id"], m["competencia"], m["numero"]):
        if o["data_base_mes"] in (m["data_base_mes"], None):
            raise ValueError(_ja_esta_em(m["competencia"], o["numero"]))


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
                        "apostilamento": None, "aditivo": None, "resposta": None})
            continue
        aniv = aniversario(b["mes"], y)
        ap = apostilamento_do_ciclo(conn, contrato_id, b["mes"], y, len(bases) == 1)
        pl = _pleito(conn, contrato_id, b["mes"], y)
        # o pedido que espera o apostilamento: a reiteracao nao zera a espera (issue #277)
        pd = _pleito(conn, contrato_id, b["mes"], y, sem_reiteracao=True) or pl
        aditivo = None
        # issue #586: a resposta do orgao ao pleito enviado mais recente; o indeferimento fecha o ciclo
        resposta = resposta_vigente(conn, pl["id"]) if pl else None
        if ap:
            sit, dias = "apostilado", None
        elif pl and resposta and resposta["resultado"] == "indeferido":
            sit, dias = "indeferido", None
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
                    "situacao": sit, "dias": dias, "pleito": pl, "pedido": pd, "apostilamento": ap, "aditivo": aditivo,
                    "resposta": resposta})
    return out


def avisos(conn, hoje: datetime.date | None = None) -> list[dict]:
    """Pleito nao enviado (atencao antes do aniversario, acao depois) e apostilamento pendente (a diretoria
    ve depois de 90 dias). Contratos ativos ou suspensos; em encerramento o reajuste continua valendo
    (as ultimas medicoes tambem se reajustam). A10 (mapa de 2026-09-28): o aviso diz a data-base, para
    levar ao ciclo dela na aba Reajuste, e nao so' a aba.

    Issue #274 (spec 2026-10-20 §2.2 e §4 item 1): o pleito nao enviado diz o valor previsto do ciclo, quando ha'
    previsao; e entram os avisos do motor de apostilamento (`_avisos_dos_ciclos` e `_avisos_das_competencias`)."""
    hoje = hoje or tempo.hoje_local()
    out = []
    for c in conn.execute("SELECT id, nome_curto, numero_instrumento, percentual_direito_bp FROM contratos "
                          "WHERE estado IN ('ativo','suspenso')"):
        nome = c["nome_curto"] or c["numero_instrumento"]
        destino = {"tela": "contrato", "id": c["id"], "aba": "reajuste"}
        ks = ciclos(conn, c["id"], hoje)
        previstos: dict[tuple[str, int], int] = {}
        if any(k["situacao"] == "pleito_pendente" for k in ks):
            for p in previsoes_vigentes(conn, c["id"]):
                chave = (p["data_base_mes"], p["ciclo"])
                previstos[chave] = previstos.get(chave, 0) + p["valor_previsto_centavos"]
        for k in ks:
            base = _rotulo_base(k["data_base_mes"], k.get("aplica_a"))
            aniv = datetime.date.fromisoformat(k["aniversario"])
            if k["situacao"] == "pleito_pendente":
                quando = (f"faz aniversário em {aniv:%d/%m/%Y} (em {k['dias']} dias)" if k["dias"] >= 0
                          else f"fez aniversário em {aniv:%d/%m/%Y} (há {-k['dias']} dias)")
                previsto = previstos.get((k["data_base_mes"], k["ciclo"]))
                valor = (f"{dinheiro.format_brl(previsto)} previstos para o ciclo de {k['ciclo']}; "
                         if previsto is not None else "")
                out.append({**_av.aviso("reajuste_pleito", "atencao" if k["dias"] >= 0 else "acao",
                                        f"data-base {base} {quando}; {valor}pleito de reajuste não enviado",
                                        c["id"], nome, dias=k["dias"], valor_centavos=previsto, destino=destino,
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
        if not ks:                           # sem reajuste no contrato, ou sem data-base
            continue
        aplica = {k["data_base_mes"]: k.get("aplica_a") for k in ks}
        out += _avisos_dos_ciclos(conn, c["id"], hoje, nome, destino, aplica)
        out += _avisos_das_competencias(conn, dict(c), nome, destino, aplica)
    return out


SEM_RESPOSTA_DIAS = 120              # "Pedido de reajuste sem resposta": 120 dias ou mais do ultimo pleito enviado
DIRETORIA_SEM_APOSTILAMENTO_CENTAVOS = 100_000_00   # "Reajuste sem apostilamento": a diretoria ve acima de R$ 100 mil


def _rotulo_base(mes: str | None, aplica_a: str | None = None) -> str:
    if mes is None:
        return "não definida"
    base = f"{mes[5:7]}/{mes[:4]}"
    return f"{base} ({aplica_a})" if aplica_a else base   # D7: com duas bases, a parte do contrato de cada uma


def _mes(comp: str) -> str:
    return f"{comp[5:7]}/{comp[:4]}"


def _lista_meses(comps: list[str]) -> str:
    ms = [_mes(x) for x in comps]
    return ms[0] if len(ms) == 1 else f"{', '.join(ms[:-1])} e {ms[-1]}"


def _avisos_dos_ciclos(conn, contrato_id: int, hoje: datetime.date, nome: str, destino: dict,
                       aplica: dict) -> list[dict]:
    """Issue #274 (spec 2026-10-20 §2.2), os avisos de cada ciclo com pleito enviado e sem o termo que o fecha
    (`apostilamento_do_ciclo`), de cada data-base do contrato, e nao so' do corrente (revisor e gate Sol, rodada 1 da
    PR #579): o ciclo anterior ainda sem resposta nao perde o aviso quando a janela do aniversario seguinte abre.

    - `reajuste_reemitir`: aditivo de prazo ou valor assinado depois do ultimo pedido enviado (`aditivo_depois`, o
      criterio do estado `reemitir` de `ciclos`); some com o pleito novo enviado (a reemissao do cronograma).
      Operacao.
    - `reajuste_sem_resposta`: o ultimo pleito enviado do ciclo (pleito, reiteracao ou reemissao do cronograma: os
      dois zeram a contagem, decisao do Leo de 08/11/2026) ha' 120 dias ou mais, em qualquer orgao. Some com a
      reiteracao ou a reemissao enviada, ou com o apostilamento. Operacao e diretoria.

    Issue #586: o ciclo indeferido (`indeferimento_do_ciclo`) fecha para os dois, como o termo."""
    out = []
    bases = [r[0] for r in conn.execute("SELECT mes FROM contrato_datas_base WHERE contrato_id=? ORDER BY mes",
                                        (contrato_id,))]
    for mes, ciclo in conn.execute("SELECT DISTINCT data_base_mes, ciclo FROM pleitos WHERE contrato_id=? "
                                   "AND tipo='reajuste' AND situacao='enviado' AND ciclo IS NOT NULL "
                                   "ORDER BY data_base_mes, ciclo", (contrato_id,)).fetchall():
        if mes not in bases or apostilamento_do_ciclo(conn, contrato_id, mes, ciclo, len(bases) == 1):
            continue
        pl = _pleito(conn, contrato_id, mes, ciclo)
        r = resposta_vigente(conn, pl["id"])
        if r and r["resultado"] == "indeferido":        # issue #586 (`indeferimento_do_ciclo`): o orgao disse que nao
            continue
        pd = _pleito(conn, contrato_id, mes, ciclo, sem_reiteracao=True) or pl
        out += _avisos_do_ciclo(mes, ciclo, pl, aditivo_depois(conn, contrato_id, pd["enviado_em"]),
                                _rotulo_base(mes, aplica.get(mes)), hoje, contrato_id, nome, destino)
    return out


def _avisos_do_ciclo(mes: str, ciclo: int, pleito: dict, aditivo: dict | None, base: str, hoje: datetime.date,
                     contrato_id: int, nome: str, destino: dict) -> list[dict]:
    """Os dois avisos de um ciclo sem termo (`_avisos_dos_ciclos`): o ultimo pleito enviado e o aditivo que pede a
    reemissao, se houver."""
    out = []
    marca = {"data_base_mes": mes, "ciclo": ciclo}
    if aditivo:
        assinado = datetime.date.fromisoformat(aditivo["data_assinatura"][:10])
        numero = f" {aditivo['numero']}" if aditivo.get("numero") else ""
        out.append({**_av.aviso("reajuste_reemitir", "acao",
                                f"data-base {base}, ciclo de {ciclo}: aditivo{numero} assinado em {assinado:%d/%m/%Y}, "
                                f"depois do pleito; cronograma de reajuste a reemitir", contrato_id, nome,
                                dias=(hoje - assinado).days, destino=destino, data=assinado.isoformat(),
                                sentido="desde"), **marca})
    if pleito:
        enviado = datetime.date.fromisoformat(pleito["enviado_em"][:10])
        dias = (hoje - enviado).days
        if dias >= SEM_RESPOSTA_DIAS:
            out.append({**_av.aviso("reajuste_sem_resposta", "acao",
                                    f"pedido de reajuste da data-base {base}, ciclo de {ciclo}, enviado em {enviado:%d/%m/%Y}, há {dias} "
                                    f"dias, sem resposta", contrato_id, nome, dias=dias,
                                    publico=("operacao", "diretoria"), destino=destino, data=enviado.isoformat(),
                                    sentido="desde"), **marca})
    return out


def _avisos_das_competencias(conn, c: dict, nome: str, destino: dict, aplica: dict | None = None) -> list[dict]:
    """Issue #274 (spec 2026-10-20 §2.2), os avisos das competencias do contrato, pelas marcas da aba Reajuste
    (`competencias_por_ciclo`, `avisos_da_competencia`): cada um some quando a marca some.

    - `reajuste_fora_da_previsao`: um por competencia; some com a reapresentacao (pedido a ate' R$ 1,00 do previsto
      vigente) ou com a justificativa (`justificar`). Operacao.
    - `reajuste_sem_apostilamento`: um por data-base e ciclo (decisao do Leo de 08/11/2026), com as competencias
      aprovadas ou faturadas que nenhum termo cobre e a soma do valor ja' medido delas (`medido_centavos` de `competencias_por_ciclo`, medicao a medicao) na cota da Lotufo
      (arredondamento unico, sobre a soma). Operacao; diretoria quando a soma passa de R$ 100 mil. Some com o
      apostilamento carregado.
    - `reajuste_nota_antes_do_apostilamento`: um por competencia, critico. Operacao. Some com o apostilamento."""
    out = []
    for g in competencias_por_ciclo(conn, c["id"]):
        base = _rotulo_base(g["data_base_mes"], (aplica or {}).get(g["data_base_mes"]))   # D7, como nos do ciclo
        marca = {"data_base_mes": g["data_base_mes"], "ciclo": g["ciclo"]}
        sem_termo = []
        for x in g["competencias"]:
            comp = x["competencia"]
            if "fora_da_previsao" in x["avisos"]:
                previsto = vigente_da_competencia(x)
                rotulo = "apostilado" if x["apostilado_centavos"] is not None else "previsto"
                out.append({**_av.aviso("reajuste_fora_da_previsao", "atencao",
                                        f"reajuste de {_mes(comp)} (data-base {base}): pedido "
                                        f"{dinheiro.format_brl(x['pedido_centavos'])}, {rotulo} "
                                        f"{dinheiro.format_brl(previsto)}; reajuste fora da previsão",
                                        c["id"], nome, valor_centavos=x["pedido_centavos"], destino=destino),
                            **marca, "competencia": comp})
            if "nota_antes_do_apostilamento" in x["avisos"]:
                out.append({**_av.aviso("reajuste_nota_antes_do_apostilamento", "critico",
                                        f"nota de reajuste de {_mes(comp)} (data-base {base}) emitida antes do "
                                        f"apostilamento", c["id"], nome, valor_centavos=x["faturado_centavos"],
                                        destino=destino),
                            **marca, "competencia": comp})
            if "sem_apostilamento" in x["avisos"]:
                sem_termo.append(x)
        if sem_termo:
            valor = contratos.cota(sum(x["medido_centavos"] or 0 for x in sem_termo), c["percentual_direito_bp"]) or 0
            publico = ("operacao", "diretoria") if valor > DIRETORIA_SEM_APOSTILAMENTO_CENTAVOS else ("operacao",)
            ciclo = f", ciclo de {g['ciclo']}" if g["ciclo"] is not None else ""
            out.append({**_av.aviso("reajuste_sem_apostilamento", "atencao",
                                    f"data-base {base}{ciclo}: reajuste de "
                                    f"{_lista_meses([x['competencia'] for x in sem_termo])} sem apostilamento",
                                    c["id"], nome, valor_centavos=valor, publico=publico, destino=destino),
                        **marca, "competencias": [x["competencia"] for x in sem_termo]})
    return out


# ---- Resposta do orgao ao pleito (issue #586) ----------------------------------------------------------------------
# 'indeferido' fecha o ciclo para os avisos de pedido sem resposta e de cronograma a reemitir (e para o "apostilamento
# pendente" da aba e da diretoria); 'deferido_parcial' fica registrado e o ciclo continua esperando o termo. A resposta
# e' do pleito enviado mais recente do ciclo (`_pleito`): pleito enviado depois dela (recurso, reiteracao, reemissao do
# cronograma) reabre o ciclo, porque a resposta dele ainda nao veio. Correcao e' resposta nova no mesmo pleito (vale a
# mais recente); 'sem_efeito' anula a resposta registrada por engano e o ciclo volta a esperar. Nada se altera nem se
# apaga (migracao 075).
RESULTADOS_RESPOSTA = ("indeferido", "deferido_parcial", "sem_efeito")
_DATA_ISO = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")       # \d casaria digito arabe-indico


def _resposta(r) -> dict:
    return {k: r[k] for k in ("id", "pleito_id", "resultado", "data", "documento", "texto", "corrige_resposta_id",
                              "criado_em")}


def _ultima_resposta(conn, pleito_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM pleito_respostas WHERE pleito_id=? ORDER BY id DESC LIMIT 1",
                     (pleito_id,)).fetchone()
    return _resposta(r) if r else None


def resposta_vigente(conn, pleito_id: int | None) -> dict | None:
    """A resposta do orgao que vale para o pleito: a mais recente (a correcao e' resposta nova); anulada
    ('sem_efeito'), nenhuma."""
    r = _ultima_resposta(conn, pleito_id) if pleito_id is not None else None
    return r if r and r["resultado"] != "sem_efeito" else None


def indeferimento_do_ciclo(conn, contrato_id: int, mes_base: str, ciclo: int) -> dict | None:
    """O indeferimento que fecha o ciclo: a resposta vigente do pleito enviado mais recente, quando e' 'indeferido'."""
    pl = _pleito(conn, contrato_id, mes_base, ciclo)
    r = resposta_vigente(conn, pl["id"]) if pl else None
    return r if r and r["resultado"] == "indeferido" else None


def respostas_do_ciclo(conn, contrato_id: int, mes_base: str, ciclo: int) -> list[dict]:
    """Todas as respostas registradas nos pleitos enviados do ciclo, na ordem do registro (a linha do tempo)."""
    return [_resposta(r) for r in conn.execute(
        "SELECT r.* FROM pleito_respostas r JOIN pleitos p ON p.id=r.pleito_id WHERE p.contrato_id=? "
        "AND p.tipo='reajuste' AND p.data_base_mes=? AND p.ciclo=? AND p.situacao='enviado' ORDER BY r.id",
        (contrato_id, mes_base, ciclo))]


def _recusa_resposta(conn, p: dict) -> str | None:
    if p["tipo"] != "reajuste" or p["situacao"] != "enviado" or not p["data_base_mes"] or p["ciclo"] is None:
        return "Só se registra a resposta do órgão em pleito de reajuste enviado"
    vig = _pleito(conn, p["contrato_id"], p["data_base_mes"], p["ciclo"])
    if vig and vig["id"] != p["id"]:
        return (f"Registre a resposta no pleito mais recente do ciclo "
                f"({vig['numero_oficio'] or 'ofício sem número'})")
    unica = conn.execute("SELECT COUNT(*) FROM contrato_datas_base WHERE contrato_id=?",
                         (p["contrato_id"],)).fetchone()[0] == 1
    if apostilamento_do_ciclo(conn, p["contrato_id"], p["data_base_mes"], p["ciclo"], unica):
        return "O ciclo já está apostilado: não há resposta a registrar"
    return None


def registrar_resposta(conn, usuario_id: int, pleito_id: int, resultado: str, data: str, documento: str,
                       texto: str, hoje: datetime.date | None = None) -> int:
    """Registra a resposta formal do orgao ao pleito enviado mais recente do ciclo (issue #586), com a auditoria.
    Havendo resposta anterior no mesmo pleito, a nova a corrige (`corrige_resposta_id`)."""
    hoje = hoje or tempo.hoje_local()
    documento, texto = (documento or "").strip(), (texto or "").strip()
    # o que nao depende do banco recusa antes de tomar a escrita
    if resultado not in RESULTADOS_RESPOSTA:
        raise ValueError("Resposta inválida: indeferido, deferido parcialmente ou registro sem efeito")
    try:
        dia = datetime.date.fromisoformat(data) if _DATA_ISO.match(data or "") else None
    except ValueError:
        dia = None
    with db.mutacao(conn):
        r = conn.execute("SELECT * FROM pleitos WHERE id=?", (pleito_id,)).fetchone()
        if r is None:
            raise ValueError("Pleito não encontrado")
        p = dict(r)
        if (motivo := _recusa_resposta(conn, p)):
            raise ValueError(motivo)
        anterior = _ultima_resposta(conn, pleito_id)
        if resultado == "sem_efeito" and (anterior is None or anterior["resultado"] == "sem_efeito"):
            raise ValueError("Não há resposta registrada neste pleito para deixar sem efeito")
        if dia is None:
            raise ValueError("Data inválida: use AAAA-MM-DD")
        if dia.isoformat() < str(p["enviado_em"])[:10]:
            raise ValueError(f"Data da resposta anterior ao envio do pleito ({p['enviado_em'][8:10]}/"
                             f"{p['enviado_em'][5:7]}/{p['enviado_em'][:4]})")
        if dia > hoje:
            raise ValueError("Data da resposta futura")
        if not documento:
            raise ValueError("Informe o documento do órgão com a resposta")
        if len(texto) < MIN_JUSTIFICATIVA:
            raise ValueError(f"Escreva o texto da resposta com pelo menos {MIN_JUSTIFICATIVA} caracteres")
        rid = conn.execute("INSERT INTO pleito_respostas (pleito_id, resultado, data, documento, texto, "
                           "corrige_resposta_id, usuario_id) VALUES (?,?,?,?,?,?,?)",
                           (pleito_id, resultado, dia.isoformat(), documento, texto,
                            anterior["id"] if anterior else None, usuario_id)).lastrowid
        auditoria.registrar(conn, usuario_id, "pleito.resposta", "pleito", pleito_id, anterior,
                            {"resposta_id": rid, "resultado": resultado, "data": dia.isoformat(),
                             "documento": documento, "texto": texto, "contrato_id": p["contrato_id"],
                             "data_base_mes": p["data_base_mes"], "ciclo": p["ciclo"],
                             "corrige_resposta_id": anterior["id"] if anterior else None})
    return rid
