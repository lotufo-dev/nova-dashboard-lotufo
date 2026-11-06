"""Tela da diretoria (spec 2026-09-21 §10.5), bloco 8. Tudo na COTA da Lotufo; vocabulario fixo: medido,
faturado (nota emitida), protocolado, recebido. O total a receber (valor do protocolado) so' aparece com o cadastro
liberando (`geral.yaml: diretoria.total_a_receber_liberado`), depois da conciliacao com a controladoria.

Corte de 2026-09-25 (decisao do Leonardo): o faturado ate o QDOP de 22/09/2026 conta como pago, menos o que o RM
mostra em aberto. O "a receber" soma as medicoes protocoladas e as cobrancas do RM ainda nao pagas que nenhuma
medicao em aberto representa (`_notas_em_aberto`), com a idade contada da emissao da nota.

Valor de uma medicao: o atestado quando houver, senao o protocolado (a mesma regra do "medido" dos paineis),
convertido para a cota uma vez, com o arredondamento unico de `contratos.cota`.
"""
import contextlib
import datetime
import json
import math
from decimal import ROUND_HALF_UP, Decimal

from app import avisos as _av, conciliacao, contratos, cronograma, medicoes, paineis, qdop, reajuste, sincronizacao_rm, tempo

QUARTIL, MINIMO, PADRAO_DIAS = 0.75, 10, 30   # prazo do orgao: so' o "previsto" da tela A receber usa
ESPERANDO_NOTA = ("espelho_gerado", "espelho_enviado")
ESPERANDO_PROTOCOLO = ("nota_emitida",)
PROTOCOLADAS = ("protocolada", "nf_emitida")
FORA = ("cancelada", "desistida", "prevista")
FAIXAS = (("ate_30", 0, 30), ("de_31_a_60", 31, 60), ("mais_60", 61, None))
COMPETENCIA_NOTA_VALE = "2026-06"   # `complemento_rm`: a carga do historico trouxe as medicoes ate' 05/2026
TOLERANCIA_CENTAVOS = 100      # titulo pago com ate R$ 1,00 de diferenca nao e' divida (arredondamento do RM)


def _quantil(valores: list[int], q: float) -> int:
    """Pela posicao mais proxima: o elemento de posicao ceil(q*n) na lista ordenada."""
    v = sorted(valores)
    return v[max(0, math.ceil(q * len(v)) - 1)]


def _d(iso: str | None) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(iso[:10]) if iso else None
    except ValueError:
        return None


def _medicoes(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT m.*, c.percentual_direito_bp AS pct, c.orgao_id, c.estado AS contrato_estado, "
        "COALESCE(c.nome_curto, c.numero_instrumento) AS obra, o.nome AS orgao_nome, o.familia AS orgao_familia, "
        "o.chave AS orgao_chave, "
        "(SELECT MIN(mp.data) FROM medicao_protocolos mp WHERE mp.medicao_id=m.id AND mp.etapa='nota') AS protocolo_em "
        "FROM medicoes m JOIN contratos c ON c.id=m.contrato_id LEFT JOIN orgaos o ON o.id=c.orgao_id")]


def _cota(m: dict) -> int:
    valor = m["valor_atestado_centavos"] if m["valor_atestado_centavos"] is not None else m["valor_protocolado_centavos"]
    return contratos.cota(valor or 0, m["pct"]) or 0


def _prazo(ms: list[dict], orgao_id, hoje: datetime.date, quantil: float) -> int:
    desde = (hoje - datetime.timedelta(days=365)).isoformat()
    dias = [(_d(m["recebida_em"]) - _d(m["protocolo_em"])).days for m in ms
            if m["orgao_id"] == orgao_id and m["estado"] == "recebida" and _d(m["recebida_em"]) and _d(m["protocolo_em"])
            and m["recebida_em"][:10] >= desde]
    dias = [d for d in dias if d >= 0]
    return _quantil(dias, quantil) if len(dias) >= MINIMO else PADRAO_DIAS


def _mapa_contratos(conn) -> tuple[dict, dict, dict]:
    """Os contratos com a coligada da entidade, e os indices para achar a obra de uma nota do RM sem medicao:
    por (coligada, centro de custo, atual ou anterior) e, para consorcio sem centro, so' pela coligada."""
    contr = {r["id"]: dict(r) for r in conn.execute("""
        SELECT c.id, c.percentual_direito_bp pct, c.orgao_id, c.estado, COALESCE(c.nome_curto, c.numero_instrumento) obra,
               c.centro_custo_rm, c.centros_custo_anteriores_rm, e.coligada_rm col, o.nome orgao_nome,
               o.familia orgao_familia, o.chave orgao_chave
        FROM contratos c JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1) LEFT JOIN orgaos o ON o.id=c.orgao_id""")}
    por_centro, por_coligada = {}, {}
    for c in contr.values():
        centros = [c["centro_custo_rm"], *json.loads(c["centros_custo_anteriores_rm"] or "[]")]
        for cc in filter(None, (x and x.strip() for x in centros)):
            por_centro.setdefault((c["col"], cc), []).append(c["id"])
        if not (c["centro_custo_rm"] or "").strip() and c["col"] not in (None, 1):
            por_coligada.setdefault(c["col"], []).append(c["id"])
    return contr, por_centro, por_coligada


def _notas_em_aberto(conn) -> list[dict]:
    """Cobrancas do RM (nota ativa com titulo nao pago) que nenhuma medicao em aberto representa, no formato das
    medicoes protocoladas: nota sem medicao, ou ligada so' a medicao ja' fechada (recebida pelo corte, por
    exemplo). A obra vem da medicao ligada ou do centro de custo (atual ou anterior); consorcio sem centro, pela
    coligada. So' notas da coligada da entidade do contrato: a NFS-e da Lotufo em obra de consorcio e' repassada
    pelo consorcio e nao e' cobranca ao orgao. O valor e' o que falta dos titulos (liquido), titulo a titulo, na cota.
    Nota ligada a medicao recebida a mao fica fora (issue #203): o registro manual vale, e o titulo ainda aberto
    no RM aparece na Saude, nao de novo no a receber."""
    em_aberto = set(ESPERANDO_NOTA + ESPERANDO_PROTOCOLO + PROTOCOLADAS)
    a_mao = conciliacao.recebidas_a_mao(conn)
    contr, por_centro, por_coligada = _mapa_contratos(conn)
    out = []
    for n in conn.execute("SELECT * FROM notas_fiscais WHERE idmov IS NOT NULL AND situacao='ativa' AND emissao IS NOT NULL"):
        ligadas = conn.execute("""SELECT m.id, m.contrato_id, m.estado FROM nf_alocacoes a JOIN medicoes m ON m.id=a.medicao_id
                                  WHERE a.nota_id=? AND a.desfeita_em IS NULL""", (n["id"],)).fetchall()
        if any(r["estado"] in em_aberto for r in ligadas):
            continue                                        # a medicao em aberto ja' conta
        if ligadas and all(r["id"] in a_mao for r in ligadas):
            continue                                        # recebida a mao: o registro manual vale (#203)
        # (`sincronizacao_rm.alocar` so' liga a nota a uma medicao; se um dia houver nota partida com medicao
        # fechada de outro jeito, ela fica inteira no a receber, como antes do #203)
        if ligadas:
            cid = ligadas[0]["contrato_id"]
        else:
            ids = por_centro.get((n["coligada"], (n["centro_custo"] or "").strip())) or por_coligada.get(n["coligada"]) or []
            cid = ids[0] if len(ids) == 1 else None
        c = contr.get(cid)
        if c is None or c["col"] != n["coligada"]:
            continue
        # Issue #253: a falta e' contada titulo a titulo (a conta da #35 e da #251): juros num titulo nao
        # escondem outro titulo aberto da mesma nota.
        falta = sincronizacao_rm._falta_por_titulo(conn, n["id"], aberto_inteiro=True)
        if falta <= TOLERANCIA_CENTAVOS:
            continue
        out.append({"estado": "protocolada", "tipo": "nota", "numero": n["numero"], "nf": _numero_nf(n["numero"]),
                    "valor_atestado_centavos": None, "valor_protocolado_centavos": falta, "pct": c["pct"],
                    "protocolo_em": n["emissao"], "orgao_id": c["orgao_id"], "orgao_nome": c["orgao_nome"],
                    "orgao_familia": c["orgao_familia"], "orgao_chave": c["orgao_chave"],
                    "obra": c["obra"], "contrato_id": c["id"], "contrato_estado": c["estado"],
                    "competencia": None, "recebida_em": None})
    return out


def _notas_do_rm(conn) -> list[tuple]:
    """As notas do RM com o contrato de cada uma: `(nota, contrato, tem_medicao_ativa)`. A obra da nota e' a de
    `_notas_em_aberto`: a medicao ligada, senao o centro de custo (atual ou anterior), senao a coligada do consorcio sem
    centro; so' notas da coligada da entidade do contrato (a NFS-e da Lotufo em obra de consorcio e' repassada pelo
    consorcio). Nota que nao cai em nenhum contrato cadastrado fica fora."""
    contr, por_centro, por_coligada = _mapa_contratos(conn)
    ligadas: dict[int, list] = {}
    for r in conn.execute("SELECT a.nota_id, m.contrato_id, m.estado FROM nf_alocacoes a JOIN medicoes m ON m.id=a.medicao_id "
                          "WHERE a.desfeita_em IS NULL ORDER BY a.id"):
        ligadas.setdefault(r["nota_id"], []).append((r["contrato_id"], r["estado"]))
    out = []
    for n in conn.execute("SELECT id, coligada, centro_custo, emissao, valor_centavos, situacao FROM notas_fiscais "
                          "WHERE idmov IS NOT NULL"):
        lig = ligadas.get(n["id"], [])
        if lig:
            cid = lig[0][0]
        else:
            ids = por_centro.get((n["coligada"], (n["centro_custo"] or "").strip())) or por_coligada.get(n["coligada"]) or []
            cid = ids[0] if len(ids) == 1 else None
        c = contr.get(cid)
        if c is None or c["col"] != n["coligada"]:
            continue
        out.append((n, c, any(estado not in FORA for _, estado in lig)))
    return out


def rm_por_mes(conn) -> tuple[dict[str, int], dict[str, int]]:
    """(faturado, recebido) por mes, na cota, direto do RM (06/11/2026, telas da diretoria). O cadastro de medicoes pode
    estar atrasado; a nota e a baixa chegam sozinhas do RM, entao a serie mensal da diretoria sai delas.

    Faturado: o bruto das notas ativas do RM, pelo mes da emissao. Recebido: o que foi baixado nos titulos da nota
    (`sincronizacao_rm.STATUS_RECEBIDO`), pelo mes da baixa; e' o liquido que entrou (o titulo nasce sem as retencoes).
    A obra de cada nota e' a de `_notas_do_rm`."""
    pct_da_nota: dict[int, int] = {}
    faturado: dict[str, int] = {}
    recebido: dict[str, int] = {}
    for n, c, _ in _notas_do_rm(conn):
        pct_da_nota[n["id"]] = c["pct"]
        if n["situacao"] == "ativa" and n["emissao"]:
            mes = n["emissao"][:7]
            faturado[mes] = faturado.get(mes, 0) + (contratos.cota(n["valor_centavos"], c["pct"]) or 0)
    for b in conn.execute("SELECT nota_id, valor_baixado_centavos, status_lan, data_baixa FROM baixas "
                          "WHERE data_baixa IS NOT NULL AND nota_id IS NOT NULL"):
        if b["status_lan"] not in sincronizacao_rm.STATUS_RECEBIDO or b["nota_id"] not in pct_da_nota:
            continue
        mes = b["data_baixa"][:7]
        recebido[mes] = recebido.get(mes, 0) + (contratos.cota(b["valor_baixado_centavos"] or 0, pct_da_nota[b["nota_id"]]) or 0)
    return faturado, recebido


def complemento_rm(conn) -> dict[int, dict[str, int]]:
    """Medicao que o RM mostra e o sistema ainda nao tem (06/11/2026): por contrato e competencia, em valor CHEIO, quanto
    as notas do RM passam do que esta' lancado. Vale so' de `COMPETENCIA_NOTA_VALE` em diante (a carga do historico
    cobriu as medicoes ate' o mes anterior). A competencia de uma nota sem medicao e' o mes anterior ao da emissao (a
    medicao de um mes e' faturada no seguinte); so' entram notas ativas que nenhuma medicao ativa representa. O
    complemento da competencia e' `max(0, notas sem medicao - medicoes lancadas)`: onde a medicao existe e cobre as
    notas, nada entra; onde falta (ou foi lancada por valor menor), entra a diferenca. Some quando a medicao e' lancada.
    Nao distingue execucao de reajuste: a nota do RM nao diz."""
    soltas: dict[int, dict[str, int]] = {}
    for n, c, tem_medicao in _notas_do_rm(conn):
        if tem_medicao or n["situacao"] != "ativa" or not n["emissao"]:
            continue
        ano, mes = int(n["emissao"][:4]), int(n["emissao"][5:7])
        comp = _mes(datetime.date(ano, mes, 1), -1)
        if comp >= COMPETENCIA_NOTA_VALE:
            d = soltas.setdefault(c["id"], {})
            d[comp] = d.get(comp, 0) + n["valor_centavos"]
    if not soltas:
        return {}
    lancado: dict[tuple, int] = {}
    for m in conn.execute("SELECT contrato_id, competencia, estado, COALESCE(valor_atestado_centavos, valor_protocolado_centavos, 0) v "
                          "FROM medicoes WHERE competencia>=?", (COMPETENCIA_NOTA_VALE,)):
        if m["estado"] not in FORA:
            lancado[(m["contrato_id"], m["competencia"])] = lancado.get((m["contrato_id"], m["competencia"]), 0) + m["v"]
    out: dict[int, dict[str, int]] = {}
    for cid, por_comp in soltas.items():
        for comp, v in por_comp.items():
            falta = v - lancado.get((cid, comp), 0)
            if falta > 0:
                out.setdefault(cid, {})[comp] = falta
    return out


def _complemento_de_execucao(conn, ms: list[dict], compl: dict[int, dict[str, int]], cache: dict) -> dict[int, dict[str, int]]:
    """O complemento que entra no medido de EXECUCAO (saldo, executado, curva): a nota do RM nao diz se e' execucao ou
    reajuste, entao o complemento de cada contrato para no que ainda falta executar (vigente de execucao - medido de
    execucao das medicoes), das competencias mais antigas para as mais novas. Assim uma nota de reajuste de obra ja'
    toda medida nao deixa o saldo negativo."""
    medido = _medido_execucao(ms)
    out: dict[int, dict[str, int]] = {}
    for cid, por_comp in compl.items():
        falta = max(0, _vigente(conn, cid, cache)["valor_vigente_execucao_centavos"] - medido.get(cid, 0))
        for comp in sorted(por_comp):
            v = min(por_comp[comp], falta)
            if v > 0:
                out.setdefault(cid, {})[comp] = v
                falta -= v
    return out


def _complemento_na_cota(conn, compl: dict[int, dict[str, int]]) -> dict[str, int]:
    """O complemento por competencia, na cota (cada contrato com o percentual dele, arredondamento unico por parcela)."""
    pct = {r["id"]: r["percentual_direito_bp"] for r in conn.execute("SELECT id, percentual_direito_bp FROM contratos")}
    out: dict[str, int] = {}
    for cid, por_comp in compl.items():
        for comp, v in por_comp.items():
            out[comp] = out.get(comp, 0) + (contratos.cota(v, pct.get(cid)) or 0)
    return out


def _faturado_rm(conn, hoje: datetime.date) -> dict:
    """Faturado no RM, na cota, nos 12 meses fechados ate' o mes anterior a hoje, cada um ao lado do mesmo mes do ano
    anterior, e o acumulado do ano ate' o ultimo mes fechado contra o mesmo periodo do ano anterior. O mes corrente
    fica fora: ainda esta' aberto e a comparacao com um mes inteiro enganaria."""
    faturado, _ = rm_por_mes(conn)
    serie = [{"competencia": _mes(hoje, k), "faturado_centavos": faturado.get(_mes(hoje, k), 0),
              "ano_anterior_centavos": faturado.get(_mes(hoje, k - 12), 0)} for k in range(-12, 0)]
    fechados = [f"{hoje.year:04d}-{k:02d}" for k in range(1, hoje.month)]
    return {"serie": serie, "ate": fechados[-1] if fechados else None,
            "ano_centavos": sum(faturado.get(m, 0) for m in fechados),
            "ano_anterior_centavos": sum(faturado.get(f"{hoje.year - 1:04d}{m[4:]}", 0) for m in fechados)}


def _contratante(m: dict) -> str:
    """O contratante de uma medicao ou nota: a sigla de Medicoes e de Obras ("SINFRA" para a familia toda, sem separar
    por superintendencia; decisao do dono de 06/11/2026 para as telas da diretoria)."""
    return medicoes.contratante(m.get("orgao_familia"), m.get("orgao_chave"), m.get("orgao_nome"), None)[0] \
        if m.get("orgao_nome") else "sem órgão"


def _numero_nf(numero) -> str:
    s = str(numero or "").strip()
    return str(int(s)) if s.isdigit() else s


def _liberado(conn) -> bool:
    r = conn.execute("SELECT valor FROM cadastro_geral WHERE chave='diretoria'").fetchone()
    return bool(json.loads(r["valor"]).get("total_a_receber_liberado")) if r else False


def _grupo(ms: list[dict], com_valor: bool = True) -> dict:
    return {"quantidade": len(ms), "valor_centavos": sum(_cota(m) for m in ms) if com_valor else None}


def _grupo_rec(ms: list[dict], com_valor: bool = True) -> dict:
    """Grupo do a receber. A14 (2026-09-28): quantas das cobrancas sao notas em aberto no RM (o resto sao
    medicoes protocoladas), para a tela nao chamar tudo de medicao."""
    return {**_grupo(ms, com_valor), "notas_rm": sum(1 for m in ms if m.get("tipo") == "nota")}


def _mes(d: datetime.date, soma: int = 0) -> str:
    total = d.year * 12 + d.month - 1 + soma
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _ativos(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM contratos WHERE estado='ativo' ORDER BY nome_curto, id")]


def _faixas(protocoladas: list[dict], hoje: datetime.date, liberado: bool) -> dict:
    faixas = {}
    for chave, de, ate in FAIXAS:
        sel = [m for m in protocoladas if _d(m["protocolo_em"])
               and de <= (hoje - _d(m["protocolo_em"])).days and (ate is None or (hoje - _d(m["protocolo_em"])).days <= ate)]
        faixas[chave] = _grupo_rec(sel, liberado)
    return faixas


def _maior_dias(ms: list[dict], hoje: datetime.date) -> int | None:
    dias = [(hoje - _d(m["protocolo_em"])).days for m in ms if _d(m["protocolo_em"])]
    return max(dias) if dias else None


# Issue #279 (spec 2026-10-20 §2.2): a competencia de reajuste ja' medida (pedida, aprovada ou faturada) que nenhum
# apostilamento cobre (`reajuste.competencias_por_ciclo`)
ESPERANDO_APOSTILAMENTO = ("pedida", "aprovada", "faturada")


def _termo_sem_meses(termo: dict) -> bool:
    """Revisor (rodada 1, PR #431): o termo que fecha o ciclo sem dizer os meses, o aditivo de valor de reajuste (#390)
    e o apostilamento sem a lista `competencias` nem `percentual` com `periodo` (os dois jeitos de
    `reajuste.competencias_por_ciclo` marcar a competencia). Com meses vale a competencia; sem, o ciclo inteiro, como
    em `reajuste.ciclos`."""
    d = termo.get("dados") or {}
    per = d.get("periodo")
    com_periodo = d.get("percentual") not in (None, "") and isinstance(per, dict) and bool(per.get("de")) and bool(per.get("ate"))
    return not (d.get("competencias") or com_periodo)


def _esperando_apostilamento(conn, contrato_id: int) -> list[dict]:
    """As competencias de reajuste do contrato ja' medidas e ainda nao recebidas que nenhum termo cobre: nem o
    apostilamento que lista o mes (`apostilada`), nem o termo sem meses que fecha o ciclo (`_termo_sem_meses`, o
    termo de `reajuste.apostilamento_do_ciclo`). A medicao sem data-base no contrato de duas (grupo sem data-base de
    `competencias_por_ciclo`) so' fica coberta quando todas as datas-base em que o mes tem reajuste o cobrem; sem
    nenhuma (contrato sem data-base, revisor na rodada 2 da PR #431), nenhum termo a cobre e ela espera."""
    grupos = reajuste.competencias_por_ciclo(conn, contrato_id)
    bases = [r[0] for r in conn.execute("SELECT mes FROM contrato_datas_base WHERE contrato_id=? ORDER BY mes", (contrato_id,))]
    if not grupos:
        return []
    fechados: dict = {}

    def fechado(base: str, ciclo: int) -> bool:
        if (base, ciclo) not in fechados:
            termo = reajuste.apostilamento_do_ciclo(conn, contrato_id, base, ciclo, len(bases) == 1)
            fechados[(base, ciclo)] = termo is not None and _termo_sem_meses(termo)
        return fechados[(base, ciclo)]

    linhas: dict = {}                     # (data-base, competencia) -> [(ciclo, apostilada)]
    for g in grupos:
        if g["data_base_mes"] is not None:
            for x in g["competencias"]:
                linhas.setdefault((g["data_base_mes"], x["competencia"]), []).append((g["ciclo"], x["apostilada"]))

    def coberta(base: str, comp: str) -> bool | None:
        """None: o mes nao tem reajuste nesta data-base (antes do 1o aniversario dela)."""
        ls = linhas.get((base, comp)) or [(reajuste._ciclo_da_competencia(base, comp), False)]
        if all(y is None for y, _ in ls):
            return None
        return any(a or (y is not None and fechado(base, y)) for y, a in ls)

    out = []
    for g in grupos:
        for x in g["competencias"]:
            if x["estado"] not in ESPERANDO_APOSTILAMENTO and x["medido_nao_recebido_centavos"] is None:
                continue                  # nada medido, ou tudo ja' recebido
            if g["data_base_mes"] is not None:
                if x["apostilada"] or fechado(g["data_base_mes"], g["ciclo"]):
                    continue
            else:
                vs = [v for v in (coberta(b, x["competencia"]) for b in bases) if v is not None]
                if vs and all(vs):        # sem data-base em que o mes tenha reajuste, nada o cobre
                    continue
            out.append(x)
    return out


def _reajustes_sem_apostilamento(conn) -> dict:
    """Por obra (todo contrato menos o rescindido, a base do QDOP: o reajuste so' sai com o apostilamento), as
    competencias de reajuste ja' medidas que esperam apostilamento (`_esperando_apostilamento`) e o valor ja' medido
    e ainda nao recebido delas (o aprovado de cada medicao, senao o pedido), na cota: o cheio da obra somado e
    convertido uma vez, como a carteira (arredondamento unico). Obra sem nenhuma nao aparece. As competencias de uma
    obra sao os meses (a mesma competencia em duas datas-base conta uma vez)."""
    obras = []
    for c in conn.execute("SELECT id, COALESCE(nome_curto, numero_instrumento) obra, percentual_direito_bp pct "
                          "FROM contratos WHERE estado<>'rescindido'"):
        xs = _esperando_apostilamento(conn, c["id"])
        if xs:
            obras.append({"contrato_id": c["id"], "obra": c["obra"], "competencias": len({x["competencia"] for x in xs}),
                          "valor_centavos": contratos.cota(sum(x["medido_nao_recebido_centavos"] or 0 for x in xs),
                                                           c["pct"]) or 0})
    obras.sort(key=lambda o: (-o["valor_centavos"], o["obra"]))
    return {"competencias": sum(o["competencias"] for o in obras), "valor_centavos": sum(o["valor_centavos"] for o in obras),
            "obras": obras}


def _dinheiro(conn, ms: list[dict], hoje: datetime.date, liberado: bool, notas: list[dict] = ()) -> dict:
    protocoladas = [m for m in ms if m["estado"] in PROTOCOLADAS] + list(notas)
    faixas = _faixas(protocoladas, hoje, liberado)
    por_orgao: dict = {}
    for m in protocoladas:
        o = por_orgao.setdefault(m["orgao_id"], {"orgao": m["orgao_nome"] or "sem órgão", "ms": []})
        o["ms"].append(m)
    orgaos = []
    for orgao_id, o in por_orgao.items():
        # A4 (mapa de 2026-09-28): as faixas de cada orgao e as obras que ele deve (o prazo normal saiu na #255).
        por_obra: dict = {}
        for m in o["ms"]:
            por_obra.setdefault(m["contrato_id"], {"obra": m["obra"], "ms": []})["ms"].append(m)
        obras = [{"contrato_id": cid, "obra": x["obra"], **_grupo_rec(x["ms"], liberado), "maior_dias": _maior_dias(x["ms"], hoje)}
                 for cid, x in por_obra.items()]
        orgaos.append({"orgao_id": orgao_id, "orgao": o["orgao"], **_grupo_rec(o["ms"], liberado),
                       "maior_dias": _maior_dias(o["ms"], hoje), "faixas": _faixas(o["ms"], hoje, liberado),
                       "obras": sorted(obras, key=lambda x: -(x["maior_dias"] or 0))})
    pendentes = [(c, k) for c in _ativos(conn) for k in reajuste.ciclos(conn, c["id"], hoje)
                 if k["situacao"] in reajuste.SEM_APOSTILAMENTO]
    mes = _mes(hoje)
    return {"medido_esperando_nota": _grupo([m for m in ms if m["estado"] in ESPERANDO_NOTA]),
            "nota_esperando_protocolo": _grupo([m for m in ms if m["estado"] in ESPERANDO_PROTOCOLO]),
            "protocolado": {**_grupo_rec(protocoladas, liberado), "faixas": faixas,
                            "por_orgao": sorted(orgaos, key=lambda o: -(o["maior_dias"] or 0))},
            "recebido_mes": _grupo([m for m in ms if m["estado"] == "recebida" and (m["recebida_em"] or "")[:7] == mes]),
            # A13 (2026-09-28): um item por ciclo, o mais antigo primeiro, para A receber listar por obra (os
            # avisos da diretoria so' trazem os de mais de 90 dias)
            # #279: e, por obra, o valor ja' medido das competencias sem apostilamento
            "reajustes_apostilamento": {**_reajustes_sem_apostilamento(conn), "quantidade": len(pendentes),
                                        "maior_dias": max((k["dias"] for _, k in pendentes), default=None),
                                        "itens": sorted(({"contrato_id": c["id"], "obra": c["nome_curto"] or c["numero_instrumento"],
                                                          "data_base_mes": k["data_base_mes"], "dias": k["dias"]}
                                                         for c, k in pendentes), key=lambda x: -(x["dias"] or 0))}}


def _previsto(conn, mes: str, cache: dict) -> int:
    total = 0
    for c in _ativos(conn):
        if c["id"] not in cache:
            cache[c["id"]] = cronograma.previsto_efetivo(conn, c["id"])
        total += contratos.cota(cache[c["id"]].get(mes, 0), c["percentual_direito_bp"]) or 0
    return total


def _medido(ms: list[dict], mes: str, compl: dict[str, int] | None = None) -> int:
    return sum(_cota(m) for m in ms if m["competencia"] == mes and m["estado"] not in FORA) + (compl or {}).get(mes, 0)


def _faturado_mes(conn, mes: str) -> dict:
    """Faturado no mes (decisao do Leo de 16/10/2026, opcao b): as medicoes que receberam a nota no mes, pelo valor
    atestado (senao o protocolado), na cota. E' a regra da coluna "Faturado" do QDOP (`qdop._faturado`), so'
    fatiada pelo mes da nota (`nota_emitida_em`, data da nota). So' leitura."""
    total, quantidade = 0, 0
    for c in conn.execute("SELECT id, percentual_direito_bp FROM contratos WHERE estado<>'rescindido'"):
        total += qdop._faturado(conn, c["id"], c["percentual_direito_bp"], False, mes)
        quantidade += conn.execute("SELECT COUNT(*) FROM medicoes WHERE contrato_id=? AND tipo IN ('execucao','projeto') "
                                   "AND estado IN ('nota_emitida','protocolada','nf_emitida','recebida') "
                                   "AND substr(nota_emitida_em,1,7)=?", (c["id"], mes)).fetchone()[0]
    return {"valor_centavos": total, "notas": quantidade}


def _mes_ano(conn, ms: list[dict], hoje: datetime.date, cache: dict, compl: dict[str, int] | None = None) -> dict:
    """`compl`: o complemento do RM por competencia, na cota (`complemento_rm`), somado ao medido das medicoes."""
    mes = _mes(hoje)
    meses_ano = [f"{hoje.year:04d}-{k:02d}" for k in range(1, hoje.month + 1)]
    faturado = _faturado_mes(conn, mes)
    return {"mes": mes, "medido_mes_centavos": _medido(ms, mes, compl),
            "faturado_mes_centavos": faturado["valor_centavos"], "notas_faturadas_mes": faturado["notas"], "previsto_mes_centavos": _previsto(conn, mes, cache),
            "mesmo_mes_ano_anterior_centavos": _medido(ms, _mes(hoje, -12), compl),
            "acumulado_ano_centavos": sum(_medido(ms, x, compl) for x in meses_ano),
            "previsto_ano_centavos": sum(_previsto(conn, x, cache) for x in meses_ano),
            "serie": [{"competencia": _mes(hoje, k), "medido_centavos": _medido(ms, _mes(hoje, k), compl),
                       "previsto_centavos": _previsto(conn, _mes(hoje, k), cache)} for k in range(-11, 1)]}


def _proximos(conn, hoje: datetime.date, cache: dict) -> list[dict]:
    """Faturamento previsto (cronograma) dos proximos seis meses. O recebimento previsto, pela mediana do prazo
    do orgao, saiu com o motor de atraso de pagamento (issue #255, decisao de 19/10/2026)."""
    return [{"competencia": x, "faturamento_previsto_centavos": _previsto(conn, x, cache)}
            for x in (_mes(hoje, k) for k in range(6))]


def _vigente(conn, contrato_id: int, cache: dict) -> dict:
    """`contratos.vigente` lido uma vez por painel: a carteira e a tabela de obras usam o mesmo (#262)."""
    chave = ("vigente", contrato_id)
    if chave not in cache:
        cache[chave] = contratos.vigente(conn, contrato_id)
    return cache[chave]


def _medido_execucao(ms: list[dict], compl: dict[int, dict[str, int]] | None = None) -> dict[int, int]:
    """#262: o medido de execucao CHEIO por contrato (`paineis.mede_execucao`, a regra de `paineis.saldo`), tirado da
    mesma leitura de medicoes do painel (`ms`), para a carteira e a tabela de obras nao divergirem na mesma resposta."""
    medido: dict[int, int] = {}
    for m in ms:
        if paineis.mede_execucao(m):
            valor = m["valor_atestado_centavos"] if m["valor_atestado_centavos"] is not None else m["valor_protocolado_centavos"] or 0
            medido[m["contrato_id"]] = medido.get(m["contrato_id"], 0) + valor
    # o que o RM mostra e ainda nao foi lancado (`complemento_rm`) conta como medido da obra
    for cid, por_comp in (compl or {}).items():
        medido[cid] = medido.get(cid, 0) + sum(por_comp.values())
    return medido


def _carteira(conn, ms: list[dict], hoje: datetime.date, cache: dict, compl: dict[int, dict[str, int]] | None = None) -> dict:
    """Contratos ativos sem encerramento iniciado: o que ainda vai ser executado."""
    ultimos = {_mes(hoje, k) for k in range(-5, 1)}
    linhas, ritmo = [], 0
    medidos = _medido_execucao(ms, compl)
    for c in (x for x in _ativos(conn) if not x["encerramento_iniciado_em"]):
        v = _vigente(conn, c["id"], cache)
        # #262: o medido e' o de `paineis.saldo` (execucao nos estados que medem), na mesma base do vigente de execucao
        exe = [m for m in ms if m["contrato_id"] == c["id"] and paineis.mede_execucao(m)]
        medido = medidos.get(c["id"], 0)
        pct = v["percentual_direito_bp"]   # #262: o percentual do mesmo vigente que a tabela de obras reaproveita
        # #262: saldo a precos iniciais -- o aditivo de reajuste fica fora, como no saldo da obra (`paineis.saldo`)
        saldo = contratos.cota(v["valor_vigente_execucao_centavos"] - medido, pct) or 0
        vigente_cota = contratos.cota(v["valor_vigente_execucao_centavos"], pct) or 0
        medido_cota = contratos.cota(medido, pct) or 0
        # #262: o cheio da janela, na cota uma vez por contrato (arredondamento unico, como o medido)
        ritmo += contratos.cota(sum((m["valor_atestado_centavos"] if m["valor_atestado_centavos"] is not None
                                     else m["valor_protocolado_centavos"] or 0)
                                    for m in exe if m["competencia"] in ultimos)
                               + sum(v for comp, v in (compl or {}).get(c["id"], {}).items() if comp in ultimos), pct) or 0
        fim = _d(v.get("execucao_fim_vigente"))
        linhas.append({"contrato_id": c["id"], "obra": c["nome_curto"] or c["numero_instrumento"],
                       "orgao_id": c["orgao_id"], "saldo_centavos": saldo,
                       "vigente_centavos": vigente_cota, "medido_centavos": medido_cota,
                       "execucao_fim": v.get("execucao_fim_vigente"), "dias": (fim - hoje).days if fim else None})
    saldo = sum(x["saldo_centavos"] for x in linhas)
    ritmo_mes = int((Decimal(ritmo) / 6).quantize(Decimal("1"), rounding=ROUND_HALF_UP))  # arredondamento unico
    # por contratante: a sigla de Medicoes e de Obras ("SINFRA" junta as superintendencias; 06/11/2026)
    nomes = {r["id"]: medicoes.contratante(r["familia"], r["chave"], r["nome"], None)[0]
             for r in conn.execute("SELECT id, nome, familia, chave FROM orgaos")}
    por_orgao: dict = {}
    for x in linhas:
        o = por_orgao.setdefault(nomes.get(x["orgao_id"], "sem órgão"), dict.fromkeys(("saldo", "vigente", "medido", "obras"), 0))
        o["saldo"] += x["saldo_centavos"]; o["vigente"] += x["vigente_centavos"]; o["medido"] += x["medido_centavos"]; o["obras"] += 1
    return {"saldo_centavos": saldo, "ritmo_mensal_centavos": ritmo_mes,
            "meses_de_producao": round(saldo / ritmo_mes, 1) if ritmo_mes > 0 else None,
            # vigente e medido na cota e o numero de obras, para o cartao por contratante (% executado = medido/vigente)
            "por_orgao": [{"orgao": k, "saldo_centavos": o["saldo"], "fracao": o["saldo"] / saldo if saldo else 0,
                           "vigente_centavos": o["vigente"], "medido_centavos": o["medido"], "obras": o["obras"]}
                          for k, o in sorted(por_orgao.items(), key=lambda kv: -kv[1]["saldo"])]}


def _curva_obra(conn, contrato_id: int, cache: dict) -> tuple[dict, str, dict, dict]:
    """A curva S da obra (issue #295), por competencia e em valor CHEIO: o previsto vigente; a linha de base ("anterior"
    quando a obra tem repactuacao, com o previsto anterior a ela; senao "vigente", com o vigente: decisao do Leo de
    28/10/2026); e o medido de execucao nos estados que medem (`paineis._medido`). O vigente sai do mesmo `cache` de
    `_previsto`, para nao ler o cronograma duas vezes."""
    chave = ("curva", contrato_id)
    if chave not in cache:
        if contrato_id not in cache:
            cache[contrato_id] = cronograma.previsto_efetivo(conn, contrato_id)
        vigente = cache[contrato_id]
        ant = cronograma.curva_comparativa(conn, contrato_id)["anterior"]
        base = ("anterior", {a["competencia"]: a["previsto_centavos"] for a in ant}) if ant else ("vigente", vigente)
        cache[chave] = (vigente, *base, {c: m["execucao"] for c, m in paineis._medido(conn, contrato_id).items()})
    return cache[chave]


def _curva_carteira(conn, hoje: datetime.date, cache: dict, compl: dict[int, dict[str, int]] | None = None) -> list[dict]:
    """Issue #296 (spec 2026-10-20 §4 item 5): a curva S da carteira, a soma das curvas das obras ativas nos ultimos
    12 meses, cada obra na sua cota (D8). A obra sem repactuacao entra na linha anterior com o previsto vigente
    (decisao do Leo de 28/10/2026), para as duas linhas somarem as mesmas obras."""
    meses = [_mes(hoje, k) for k in range(-11, 1)]
    out = {m: {"competencia": m, "previsto_centavos": 0, "previsto_anterior_centavos": 0, "medido_centavos": 0} for m in meses}
    for c in _ativos(conn):
        vigente, _, linha_base, medido = _curva_obra(conn, c["id"], cache)
        pct = c["percentual_direito_bp"]
        for m in meses:
            out[m]["previsto_centavos"] += contratos.cota(vigente.get(m, 0), pct) or 0
            out[m]["previsto_anterior_centavos"] += contratos.cota(linha_base.get(m, 0), pct) or 0
            out[m]["medido_centavos"] += contratos.cota(medido.get(m, 0) + (compl or {}).get(c["id"], {}).get(m, 0), pct) or 0
    return list(out.values())


def _desvio(conn, contrato_id: int, hoje: datetime.date, cache: dict) -> dict:
    """Issue #296, decisoes do Leo de 28/10/2026: desvio em p.p. = (medido acumulado - previsto acumulado) / valor
    vigente de execucao do contrato x 100 (#262: sem o aditivo de reajuste, a mesma base do medido), ate' a ultima competencia fechada (o mes anterior ao atual), contra a linha anterior a
    ultima repactuacao quando a obra tem uma, senao contra a vigente. Em valor cheio (a razao e' a mesma na cota, sem
    o arredondamento dela); uma casa decimal, meio para cima. Sem cronograma ou sem valor vigente, None."""
    _, base, previsto, medido = _curva_obra(conn, contrato_id, cache)
    total = _vigente(conn, contrato_id, cache)["valor_vigente_execucao_centavos"]
    if not previsto or not total or total <= 0:
        return {"desvio_pp": None, "desvio_base": None}
    ate = _mes(hoje, -1)
    diferenca = sum(v for c, v in medido.items() if c and c <= ate) - sum(v for c, v in previsto.items() if c <= ate)
    pp = (Decimal(diferenca) * 100 / Decimal(total)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return {"desvio_pp": float(pp), "desvio_base": base}


def _a_precos_iniciais(conn, linha: dict, medido: int, cache: dict) -> dict:
    """#262 (gate Sol): a linha da tabela de obras na base do saldo da obra (`paineis.saldo`) e da carteira, logo
    acima na tela: PI+VA, VA, saldo e percentuais com o vigente de execucao, sem o aditivo de reajuste, que fica so'
    na coluna do reajuste. `medido` e' o de execucao nos estados que medem, CHEIO (`_medido_execucao`, da mesma
    leitura de medicoes e do mesmo vigente da carteira); a coluna "faturados" continua a do QDOP. O saldo aplica a
    cota uma vez sobre o saldo cheio, como a carteira; os percentuais sao a razao no cheio (a mesma na cota, sem o
    arredondamento dela). O QDOP exportado continua com o vigente cheio (#352)."""
    v = _vigente(conn, linha["contrato_id"], cache)
    pct = v["percentual_direito_bp"]
    execucao = v["valor_vigente_execucao_centavos"]
    pi_va = contratos.cota(execucao, pct) or 0
    return {"pi_va": pi_va, "va": pi_va - linha["pi"], "saldo": contratos.cota(execucao - medido, pct) or 0,
            "pct_recebido": medido / execucao if execucao else 0,
            "pct_a_receber": (execucao - medido) / execucao if execucao else 0}


def _obras(conn, ms: list[dict], hoje: datetime.date, avisos: list[dict], cache: dict,
           compl: dict[int, dict[str, int]] | None = None, faturado_a_mais: dict[int, dict[str, int]] | None = None) -> list[dict]:
    """`compl`: o complemento de execucao (`_complemento_de_execucao`), que entra no medido e no saldo; `faturado_a_mais`:
    o complemento inteiro (`complemento_rm`), que entra na coluna "faturados"."""
    por_obra: dict = {}
    for a in avisos:
        if a.get("contrato_id"):
            por_obra.setdefault(a["contrato_id"], []).append(a)
    out = []
    medido = _medido_execucao(ms, compl)
    for linha in qdop.linhas(conn, hoje):
        # a nota do RM sem medicao lancada e' faturado por definicao: entra na coluna "faturados" da tela, na cota
        falta = sum((faturado_a_mais or {}).get(linha["contrato_id"], {}).values())
        if falta:
            pct = _vigente(conn, linha["contrato_id"], cache)["percentual_direito_bp"]
            linha = {**linha, "faturados": linha["faturados"] + (contratos.cota(falta, pct) or 0)}
        av = por_obra.get(linha["contrato_id"], [])
        # D10: o farol separa os niveis do aviso: critico = vermelho; acao = acao; o resto (atencao) = atencao
        niveis = {a["nivel"] for a in av}
        farol = "vermelho" if "critico" in niveis else "acao" if "acao" in niveis else "atencao" if av else "verde"
        # A5 (mapa de 2026-09-28; backlog de 2026-09-25): os motivos um a um, na ordem dos avisos (nivel e
        # dias), sem o prefixo com o nome da obra, que a linha ja' mostra. `motivo` fica para o QDOP exportado.
        prefixo = f"{av[0]['obra']}: " if av and av[0].get("obra") else None
        motivos = [{"tipo": a["tipo"], "nivel": a["nivel"], "dias": a["dias"], "valor_centavos": a["valor_centavos"],
                    "texto": a["mensagem"][len(prefixo):] if prefixo and a["mensagem"].startswith(prefixo) else a["mensagem"]}
                   for a in av]
        out.append({**linha, **_a_precos_iniciais(conn, linha, medido.get(linha["contrato_id"], 0), cache), "farol": farol,
                    "motivo": "; ".join(a["mensagem"] for a in av), "motivos": motivos,
                    **_desvio(conn, linha["contrato_id"], hoje, cache)})
    return out


def da_obra(conn, contrato_id: int) -> dict:
    """Faturado e a receber de UMA obra, em valor CHEIO (a pagina da obra mostra o contrato inteiro; mapa de
    2026-09-28, mudanca A3). As regras sao as desta tela e do QDOP: faturado = medicoes com nota emitida,
    protocoladas, com NF do legado ou recebidas, no atestado quando houver; a receber = protocoladas e com NF
    do legado, mais as cobrancas do RM em aberto da obra (`_notas_em_aberto`). O a receber so' tem valor com o
    total liberado, como o protocolado desta tela."""
    faturado = conn.execute(
        "SELECT COALESCE(SUM(COALESCE(valor_atestado_centavos, valor_protocolado_centavos)), 0) FROM medicoes "
        "WHERE contrato_id=? AND estado IN ('nota_emitida','protocolada','nf_emitida','recebida')", (contrato_id,)).fetchone()[0]
    a_receber = None
    if _liberado(conn):
        cheio = lambda m: m["valor_atestado_centavos"] if m["valor_atestado_centavos"] is not None else m["valor_protocolado_centavos"] or 0
        ms = [m for m in _medicoes(conn) if m["contrato_id"] == contrato_id and m["estado"] in PROTOCOLADAS]
        a_receber = sum(cheio(m) for m in ms) + sum(cheio(n) for n in _notas_em_aberto(conn) if n["contrato_id"] == contrato_id)
    return {"faturado_centavos": faturado, "a_receber_centavos": a_receber}


def _obras_base(conn) -> dict:
    """A-21 (10/10/2026): de que sao feitas as obras do farol (o QDOP conta tudo que nao e' rescindido), para a
    tela dizer a base; "ativas" e' a definicao unica de `avisos.ativos` (ativo sem encerramento iniciado)."""
    base = {"ativas": 0, "encerramento": 0, "suspensas": 0, "encerradas": 0}
    for c in conn.execute("SELECT c.estado, c.encerramento_iniciado_em FROM contratos c "
                          "JOIN orgaos o ON o.id=c.orgao_id WHERE c.estado<>'rescindido'"):   # o filtro de qdop.linhas
        chave = ("suspensas" if c["estado"] == "suspenso" else "encerradas" if c["estado"] == "encerrado"
                 else "encerramento" if c["encerramento_iniciado_em"] else "ativas")
        base[chave] += 1
    return base


@contextlib.contextmanager
def _leitura_unica(conn):
    """#262 (revisor): o painel inteiro le uma fotografia so' do banco. Uma transacao de leitura (BEGIN adiado: a
    fotografia e' a da primeira leitura) faz `qdop.linhas`, carteira, curva, previsto e medicoes verem o mesmo
    estado, mesmo com um `cadastro aplicar` ou uma medicao gravando em outra conexao no meio. Em WAL (`db.get_conn`)
    a leitura nao segura a escrita de ninguem. Com transacao ja' aberta por quem chamou, le nela e nao a fecha."""
    if conn.in_transaction:
        yield
        return
    conn.execute("BEGIN")
    try:
        yield
    finally:
        if conn.in_transaction:
            conn.commit()                # so' houve leitura; commit so' encerra a transacao


def painel(conn, hoje: datetime.date | None = None) -> dict:
    hoje = hoje or tempo.hoje_local()
    with _leitura_unica(conn):
        liberado = _liberado(conn)
        ms = _medicoes(conn)
        notas = _notas_em_aberto(conn) if liberado else []
        cache: dict = {}
        avisos = _av.listar(conn, hoje, publico="diretoria")
        # 06/11/2026: o que o RM mostra e ainda nao tem medicao lancada entra no medido da diretoria (`complemento_rm`)
        compl = complemento_rm(conn)
        execucao = _complemento_de_execucao(conn, ms, compl, cache)
        return {"hoje": hoje.isoformat(), "total_a_receber_liberado": liberado,
                "dinheiro": _dinheiro(conn, ms, hoje, liberado, notas),
                "mes_ano": _mes_ano(conn, ms, hoje, cache, _complemento_na_cota(conn, compl)),
                "faturado_rm": _faturado_rm(conn, hoje),
                "proximos": _proximos(conn, hoje, cache), "carteira": _carteira(conn, ms, hoje, cache, execucao),
                "curva_carteira": _curva_carteira(conn, hoje, cache, execucao),
                "obras": _obras(conn, ms, hoje, avisos, cache, execucao, compl), "obras_base": _obras_base(conn),
                "avisos": avisos}


def a_receber(conn, hoje: datetime.date | None = None) -> dict:
    """Tela A receber (redesenho #162; so' leitura; tudo na cota). O total e a lista sao as cobrancas protocoladas
    esperando pagamento (medicoes protocoladas e, como no painel da diretoria, as notas do RM em aberto que nenhuma
    medicao representa), por obra. Antes da conciliacao o valor e' None e as notas do RM ficam fora (como no painel).

    Regra do "previsto" (a confirmar pelo Leo; o sistema nao tem previsao por medicao): o previsto de um mes e' a
    soma, na cota, das medicoes protocoladas (hoje em aberto ou ja' recebidas) cujo
    vencimento (data do protocolo ou da emissao + prazo normal do orgao) cai naquele mes. O recebido do mes e' a
    soma, na cota, das medicoes com `recebida_em` no mes. Seis meses ate o atual e tres a frente."""
    hoje = hoje or tempo.hoje_local()
    liberado = _liberado(conn)
    ms = _medicoes(conn)
    notas = _notas_em_aberto(conn) if liberado else []
    abertas = sorted(([m for m in ms if m["estado"] in PROTOCOLADAS] + notas), key=lambda m: (m["protocolo_em"] or "9", m["contrato_id"]))
    valor = lambda xs: sum(_cota(m) for m in xs) if liberado else None
    por_obra: dict = {}
    for m in abertas:
        por_obra.setdefault(m["contrato_id"], {"contrato_id": m["contrato_id"], "obra": m["obra"], "ms": []})["ms"].append(m)
    obras = [{"contrato_id": o["contrato_id"], "obra": o["obra"], "quantidade": len(o["ms"]), "valor_centavos": valor(o["ms"])}
             for o in por_obra.values()]
    obras.sort(key=lambda o: (-(o["valor_centavos"] or 0), -o["quantidade"], o["obra"]))
    # Por contratante (06/11/2026, tela da diretoria): o mesmo total, agrupado pela sigla do contratante ("SINFRA" junta
    # as superintendencias); `orgao_id` e' o do primeiro orgao do grupo
    por_orgao: dict = {}
    for m in abertas:
        por_orgao.setdefault(_contratante(m), {"orgao_id": m["orgao_id"], "orgao": _contratante(m), "ms": []})["ms"].append(m)
    orgaos = [{"orgao_id": o["orgao_id"], "orgao": o["orgao"], "quantidade": len(o["ms"]), "valor_centavos": valor(o["ms"])}
              for o in por_orgao.values()]
    orgaos.sort(key=lambda o: (-(o["valor_centavos"] or 0), -o["quantidade"], o["orgao"]))
    itens = [{"contrato_id": m["contrato_id"], "orgao_id": m["orgao_id"], "obra": m["obra"], "medicao_id": None if m.get("tipo") == "nota" else m["id"],
              "numero": None if m.get("tipo") == "nota" else m["numero"], "tipo": m.get("tipo") or "execucao",
              "nota_numero": m.get("nf") if m.get("tipo") == "nota" else None, "competencia": m["competencia"],
              "protocolada_em": (m["protocolo_em"] or "")[:10] or None, "valor_centavos": _cota(m) if liberado else None}
             for m in abertas]
    prazos: dict = {}
    previsto = dict.fromkeys([_mes(hoje, k) for k in range(-5, 4)], 0)
    # so' medicoes (a nota do RM repetiria a recebida) e recebida so' com data: o corte de 25/09/2026 fechou o legado como
    # recebida sem `recebida_em`; essas nao entram no recebido e, por isso, tambem ficam fora do previsto
    for m in [x for x in ms if x["estado"] in PROTOCOLADAS or (x["estado"] == "recebida" and x["recebida_em"])]:
        base = _d(m["protocolo_em"])
        if not base:
            continue
        if m["orgao_id"] not in prazos:
            prazos[m["orgao_id"]] = _prazo(ms, m["orgao_id"], hoje, QUARTIL)
        mes = _mes(base + datetime.timedelta(days=prazos[m["orgao_id"]]))
        # meses futuros: so' o que ainda nao foi pago; a recebida conta se o vencimento nao e' posterior ao mes do recebimento
        if m["estado"] == "recebida" and mes > _mes(hoje) and mes > m["recebida_em"][:7]:
            continue
        if mes in previsto:
            previsto[mes] += _cota(m)
    recebido = dict.fromkeys(previsto, 0)
    for m in ms:
        if m["estado"] == "recebida" and (m["recebida_em"] or "")[:7] in recebido:
            recebido[m["recebida_em"][:7]] += _cota(m)
    atual = _mes(hoje)
    # o recebido de verdade: as baixas do RM (`rm_por_mes`). O `recebido_centavos` de cada mes segue sendo o das medicoes
    # com `recebida_em` (o par do "previsto"); a tela mostra o `recebido_real_centavos`.
    _, real = rm_por_mes(conn)
    meses = [{"competencia": x, "atual": x == atual, "futuro": x > atual,
              "previsto_centavos": previsto[x] if liberado else None,
              "recebido_centavos": None if x > atual else recebido[x],
              "recebido_real_centavos": None if x > atual else real.get(x, 0)} for x in previsto]
    return {"hoje": hoje.isoformat(), "total_a_receber_liberado": liberado,
            "total": {"quantidade": len(abertas), "obras": len(obras), "valor_centavos": valor(abertas)},
            "recebido_ano_centavos": sum(v for m, v in real.items() if m[:4] == f"{hoje.year:04d}" and m <= atual),
            # o caminho do dinheiro antes do protocolo, como no painel (`_dinheiro`): medido sem nota e nota sem protocolo
            "antes_do_protocolo": {"medido_esperando_nota": _grupo([m for m in ms if m["estado"] in ESPERANDO_NOTA]),
                                   "nota_esperando_protocolo": _grupo([m for m in ms if m["estado"] in ESPERANDO_PROTOCOLO])},
            "mes": next(x for x in meses if x["atual"]), "meses": meses, "por_obra": obras, "por_orgao": orgaos, "itens": itens}
