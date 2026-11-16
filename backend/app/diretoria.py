"""Numeros da diretoria (spec 2026-09-21 §10.5, bloco 8): o Resumo e o QDOP da lista de Obras (`painel`), o a
receber da lista e da pagina da obra e as contas que o Inicio e o Fechamento reaproveitam (prazo do orgao, notas do
RM, cobranca ao orgao). As telas Carteira e A receber sairam na issue #748. Tudo na COTA da Lotufo; vocabulario
fixo: medido, faturado (nota emitida), protocolado, recebido. O total a receber (valor do protocolado) so' aparece com o cadastro
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

from app import avisos as _av, conciliacao, contratos, cronograma, medicoes, paineis, qdop, sincronizacao_rm, tempo

# Prazo do orgao (docs/adr/0007, issue #711): o terceiro quartil dos dias entre o protocolo e o recebimento, com no
# minimo cinco recebimentos em doze meses. A conta e' uma so' (`prazos_do_orgao`); nao ha' numero padrao.
PRAZO_QUARTIL, PRAZO_MINIMO_CASOS, PRAZO_JANELA_DIAS = 0.75, 5, 365
ESPERANDO_NOTA = ("espelho_gerado", "espelho_enviado")
ESPERANDO_PROTOCOLO = ("nota_emitida",)
PROTOCOLADAS = ("protocolada", "nf_emitida")
# #561: fora do medido = o que nao esta' em `medicoes.ESTADOS_NO_MEDIDO` (conta a partir do envio da planilha/carta). A
# planilha gerada sai junto: o `complemento_rm` nao a conta como lancada, e conta-la aqui somaria ela e a nota do RM.
FORA = ("cancelada", "desistida", "prevista", "planilha_gerada")
FAIXAS = (("ate_30", 0, 30), ("de_31_a_60", 31, 60), ("mais_60", 61, None))
COMPETENCIA_NOTA_VALE = "2026-06"   # `complemento_rm`: a carga do historico trouxe as medicoes ate' 05/2026
TOLERANCIA_CENTAVOS = 100      # titulo pago com ate R$ 1,00 de diferenca nao e' divida (arredondamento do RM)
# Issue #563: tipos de movimento do RM (codtmv) que sao cobranca ao orgao. So' eles entram no a receber e no faturado
# do RM; 2.2.15 (nota do fornecedor, saida contra fornecedor) e 2.2.10 (pessoas fisicas) ficam fora. 2.2.07 e' o do
# consorcio do Leblon com tomador SINFRA. Tipo novo so' entra por decisao.
CODTMV_COBRANCA = ("2.2.01", "2.2.02", "2.2.07", "2.2.16")
_FILTRO_COBRANCA = f"codtmv IN ({','.join('?' * len(CODTMV_COBRANCA))})"


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


def prazos_do_orgao(ms: list[dict], hoje: datetime.date) -> dict[str, int]:
    """O prazo de pagamento de cada contratante, em dias (docs/adr/0007; a UNICA conta de prazo do sistema: a previsao
    de entrada e o "Atrasado" do Inicio, a matriz e o campo `previsto_centavos` de `a_receber` saem daqui).

    E' o terceiro quartil (`_quantil`: o elemento de posicao ceil(0,75 * n) dos dias em ordem, sempre um prazo que
    aconteceu, sem interpolar) dos dias entre o primeiro protocolo da nota e o recebimento, das medicoes recebidas nos
    ultimos 365 dias. O contratante e' a sigla de `_contratante` (a SINFRA inteira, nao cada superintendencia).
    Cada medicao recebida e' um caso (execucao e reajuste pagos juntos contam dois). Nao e' caso a recebida sem data
    de protocolo ou sem `recebida_em` (o corte de 25/09/2026), a de recebimento anterior ao protocolo nem a de
    recebimento com data depois de hoje. Contratante com menos de PRAZO_MINIMO_CASOS recebimentos fica FORA do
    dicionario: e' "sem previsao", e ninguem preenche com numero padrao."""
    desde = hoje - datetime.timedelta(days=PRAZO_JANELA_DIAS)
    dias: dict[str, list[int]] = {}
    for m in ms:
        recebida, protocolo = _d(m["recebida_em"]), _d(m["protocolo_em"])
        if m["estado"] != "recebida" or not recebida or not protocolo or not desde <= recebida <= hoje or recebida < protocolo:
            continue
        dias.setdefault(_contratante(m), []).append((recebida - protocolo).days)
    return {k: _quantil(v, PRAZO_QUARTIL) for k, v in dias.items() if len(v) >= PRAZO_MINIMO_CASOS}


def esperada(m: dict, prazos: dict[str, int]) -> datetime.date | None:
    """A data esperada do recebimento de uma medicao: o primeiro protocolo da nota + o prazo do contratante
    (`prazos_do_orgao`). Sem a data do protocolo ou com o contratante sem prazo, nao ha' data esperada. Atrasada e' a
    protocolada com essa data anterior a hoje: passou do que e' normal naquele orgao."""
    protocolo, prazo = _d(m["protocolo_em"]), prazos.get(_contratante(m))
    if protocolo is None or prazo is None:
        return None
    return protocolo + datetime.timedelta(days=prazo)


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
    no RM aparece na Saude, nao de novo no a receber. Issue #713: a nota que chega DEPOIS do recebimento a mao e'
    ligada a' medicao pelo casador do RM (`sincronizacao_rm._candidatas`) e sai daqui por esta mesma regra; antes
    ficava solta e somava, pelo centro de custo, um dinheiro que ja' entrou. So' notas de `CODTMV_COBRANCA` (#563)."""
    em_aberto = set(ESPERANDO_NOTA + ESPERANDO_PROTOCOLO + PROTOCOLADAS)
    a_mao = conciliacao.recebidas_a_mao(conn)
    contr, por_centro, por_coligada = _mapa_contratos(conn)
    out = []
    for n in conn.execute("SELECT * FROM notas_fiscais WHERE idmov IS NOT NULL AND situacao='ativa' AND emissao IS NOT NULL "
                          "AND " + _FILTRO_COBRANCA, CODTMV_COBRANCA):
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
        falta = sincronizacao_rm._falta_por_titulo(conn, n["id"], aberto_inteiro=True, baixa_total_quita=True)
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
    consorcio). Nota que nao cai em nenhum contrato cadastrado fica fora, e so' as de `CODTMV_COBRANCA` (#563)."""
    contr, por_centro, por_coligada = _mapa_contratos(conn)
    ligadas: dict[int, list] = {}
    for r in conn.execute("SELECT a.nota_id, m.contrato_id, m.estado FROM nf_alocacoes a JOIN medicoes m ON m.id=a.medicao_id "
                          "WHERE a.desfeita_em IS NULL ORDER BY a.id"):
        ligadas.setdefault(r["nota_id"], []).append((r["contrato_id"], r["estado"]))
    out = []
    for n in conn.execute("SELECT id, coligada, centro_custo, emissao, valor_centavos, situacao FROM notas_fiscais "
                          "WHERE idmov IS NOT NULL AND " + _FILTRO_COBRANCA, CODTMV_COBRANCA):
        lig = ligadas.get(n["id"], [])
        if lig:
            cid = lig[0][0]
        else:
            ids = por_centro.get((n["coligada"], (n["centro_custo"] or "").strip())) or por_coligada.get(n["coligada"]) or []
            cid = ids[0] if len(ids) == 1 else None
        c = contr.get(cid)
        if c is None or c["col"] != n["coligada"]:
            continue
        # #561: so' a medicao que mede (`medicoes.ESTADOS_NO_MEDIDO`) representa a nota; a planilha gerada, nao
        out.append((n, c, any(estado in medicoes.ESTADOS_NO_MEDIDO for _, estado in lig)))
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


def recebido_rm_no_mes(conn, mes: str) -> dict:
    """Issue #642 (faixa do ciclo no Inicio): o recebido de UM mes pela conta de `rm_por_mes` (baixa com status de
    `sincronizacao_rm.STATUS_RECEBIDO`, pelo mes da baixa, na cota, nota a nota de `_notas_do_rm`), com quantas notas
    tiveram baixa com valor no mes (a nota com dois titulos baixados conta uma vez)."""
    pct_da_nota = {n["id"]: c["pct"] for n, c, _ in _notas_do_rm(conn)}
    valor, notas = 0, set()
    for b in conn.execute("SELECT nota_id, valor_baixado_centavos, status_lan FROM baixas "
                          "WHERE nota_id IS NOT NULL AND substr(data_baixa, 1, 7)=?", (mes,)):
        if b["status_lan"] not in sincronizacao_rm.STATUS_RECEBIDO or b["nota_id"] not in pct_da_nota:
            continue
        valor += contratos.cota(b["valor_baixado_centavos"] or 0, pct_da_nota[b["nota_id"]]) or 0
        if (b["valor_baixado_centavos"] or 0) > 0:
            notas.add(b["nota_id"])
    return {"valor_centavos": valor, "notas": len(notas)}


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
        if m["estado"] in medicoes.ESTADOS_NO_MEDIDO:     # #561: o lancado e' o que mede, como o medido da Carteira
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


def _medido(ms: list[dict], mes: str, compl: dict[str, int] | None = None) -> int:
    return sum(_cota(m) for m in ms if m["competencia"] == mes and m["estado"] not in FORA) + (compl or {}).get(mes, 0)


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


def _carteira(conn, ms: list[dict], cache: dict, compl: dict[int, dict[str, int]] | None = None) -> dict:
    """Contratos ativos sem encerramento iniciado: o que ainda vai ser executado (o Resumo da lista de Obras). Por
    contratante, o vigente, o medido e o saldo de execucao na cota, para os cartoes e os tres numeros do alto."""
    linhas = []
    medidos = _medido_execucao(ms, compl)
    for c in (x for x in _ativos(conn) if not x["encerramento_iniciado_em"]):
        v = _vigente(conn, c["id"], cache)
        # #262: o medido e' o de `paineis.saldo` (execucao nos estados que medem), na mesma base do vigente de execucao
        medido = medidos.get(c["id"], 0)
        pct = v["percentual_direito_bp"]   # #262: o percentual do mesmo vigente que a tabela de obras reaproveita
        # #262: saldo a precos iniciais -- o aditivo de reajuste fica fora, como no saldo da obra (`paineis.saldo`)
        linhas.append({"orgao_id": c["orgao_id"],
                       "saldo_centavos": contratos.cota(v["valor_vigente_execucao_centavos"] - medido, pct) or 0,
                       "vigente_centavos": contratos.cota(v["valor_vigente_execucao_centavos"], pct) or 0,
                       "medido_centavos": contratos.cota(medido, pct) or 0})
    # por contratante: a sigla de Medicoes e de Obras ("SINFRA" junta as superintendencias; 06/11/2026)
    nomes = {r["id"]: medicoes.contratante(r["familia"], r["chave"], r["nome"], None)[0]
             for r in conn.execute("SELECT id, nome, familia, chave FROM orgaos")}
    por_orgao: dict = {}
    for x in linhas:
        o = por_orgao.setdefault(nomes.get(x["orgao_id"], "sem órgão"), dict.fromkeys(("saldo", "vigente", "medido"), 0))
        o["saldo"] += x["saldo_centavos"]; o["vigente"] += x["vigente_centavos"]; o["medido"] += x["medido_centavos"]
    return {"saldo_centavos": sum(x["saldo_centavos"] for x in linhas),
            "por_orgao": [{"orgao": k, "saldo_centavos": o["saldo"], "vigente_centavos": o["vigente"],
                           "medido_centavos": o["medido"]}
                          for k, o in sorted(por_orgao.items(), key=lambda kv: -kv[1]["saldo"])]}


def _medido_ano(ms: list[dict], hoje: datetime.date, compl: dict[str, int]) -> dict:
    """O "Medido em <ano>" do Resumo: o medido (`_medido`) das competencias do ano ate' o mes atual, na cota, com o
    complemento do RM por competencia (`complemento_rm`, na cota)."""
    meses = [f"{hoje.year:04d}-{k:02d}" for k in range(1, hoje.month + 1)]
    return {"ano": f"{hoje.year:04d}", "valor_centavos": sum(_medido(ms, x, compl) for x in meses)}


def _curva_obra(conn, contrato_id: int, cache: dict) -> tuple[dict, str, dict, dict]:
    """A curva S da obra (issue #295), por competencia e em valor CHEIO: o previsto vigente; a linha de base ("anterior"
    quando a obra tem repactuacao, com o previsto anterior a ela; senao "vigente", com o vigente: decisao do Leo de
    28/10/2026); e o medido de execucao nos estados que medem (`paineis._medido`). O vigente sai do mesmo `cache` de
    `cache` por contrato, para nao ler o cronograma duas vezes."""
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


def _a_precos_iniciais(conn, linha: dict, medido: int, cache: dict) -> dict:
    """#262 (gate Sol): a linha da tabela de obras na base do saldo da obra (`paineis.saldo`) e da carteira, logo
    acima na tela: PI+VA, VA, saldo e percentuais com o vigente de execucao, sem o aditivo de reajuste, que fica so' na coluna do
    reajuste. `medido` e' o de execucao nos estados que medem, CHEIO (`_medido_execucao`, da mesma
    leitura de medicoes e do mesmo vigente da carteira); a coluna "faturados" continua a do QDOP. O saldo aplica a
    cota uma vez sobre o saldo cheio, como a carteira. O QDOP exportado continua com o vigente cheio (#352)."""
    v = _vigente(conn, linha["contrato_id"], cache)
    pct = v["percentual_direito_bp"]
    execucao = v["valor_vigente_execucao_centavos"]
    # va e os percentuais nao tem tela, mas a linha do `qdop.linhas` (a do arquivo exportado) os traz no vigente cheio:
    # sobrescritos aqui, a linha da tela fica toda na mesma base em vez de misturar duas
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
                    "motivo": "; ".join(a["mensagem"] for a in av), "motivos": motivos})
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


def a_receber_por_obra(conn, na_cota: bool = False) -> dict[int, int] | None:
    """O a receber de TODAS as obras de uma vez, em valor CHEIO, pela mesma conta de `da_obra` (#509).
    Sem o total liberado, nulo: a lista mostra "—" em vez de um numero nao conciliado. Obra sem nada a receber fica de fora.
    `na_cota` (lista de Obras, #645): cada cobranca na cota da Lotufo (`_cota`), a conta do `por_obra` da tela A receber."""
    if not _liberado(conn):
        return None
    cheio = lambda m: m["valor_atestado_centavos"] if m["valor_atestado_centavos"] is not None else m["valor_protocolado_centavos"] or 0
    valor = _cota if na_cota else cheio
    por_obra: dict[int, int] = {}
    for m in _medicoes(conn):
        if m["estado"] in PROTOCOLADAS:
            por_obra[m["contrato_id"]] = por_obra.get(m["contrato_id"], 0) + valor(m)
    for n in _notas_em_aberto(conn):
        por_obra[n["contrato_id"]] = por_obra.get(n["contrato_id"], 0) + valor(n)
    return por_obra


@contextlib.contextmanager
def _leitura_unica(conn):
    """#262 (revisor): o painel inteiro le uma fotografia so' do banco. Uma transacao de leitura (BEGIN adiado: a
    fotografia e' a da primeira leitura) faz `qdop.linhas`, carteira, curva e medicoes verem o mesmo
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
    """O Resumo e o QDOP da lista de Obras (issue #748: sairam da Carteira, que deixou de existir). O resto da antiga
    tela da diretoria (faixas do a receber, faturado do RM por mes, proximos meses, reajustes esperando apostilamento,
    ritmo e desvio) saiu com ela: o backend so' calcula o que alguma tela mostra."""
    hoje = hoje or tempo.hoje_local()
    with _leitura_unica(conn):
        ms = _medicoes(conn)
        cache: dict = {}
        avisos = _av.listar(conn, hoje, publico="diretoria")
        # 06/11/2026: o que o RM mostra e ainda nao tem medicao lancada entra no medido da diretoria (`complemento_rm`)
        compl = complemento_rm(conn)
        execucao = _complemento_de_execucao(conn, ms, compl, cache)
        return {"hoje": hoje.isoformat(), "medido_ano": _medido_ano(ms, hoje, _complemento_na_cota(conn, compl)),
                "carteira": _carteira(conn, ms, cache, execucao),
                "curva_carteira": _curva_carteira(conn, hoje, cache, execucao),
                "obras": _obras(conn, ms, hoje, avisos, cache, execucao, compl), "avisos": avisos}
