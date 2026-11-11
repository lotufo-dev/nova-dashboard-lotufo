"""Pagina Inicio do redesenho (decisoes do Leonardo de 08/10/2026). So' leitura; tudo de uma vez.

Nada e' calculado de novo aqui: cada numero vem do modulo que ja' o calcula para a tela de origem.
- obras protocoladas: `avisos.resumo_mes` (o mesmo "X de N obras ativas" da fila de Medicoes);
- a receber: a regra da Carteira (`diretoria`), na COTA da Lotufo, so' com o total liberado;
- faixa do ciclo (#642): `_ciclo`, na cota, so' com a data do evento de cada etapa;
- recebido em 12 meses (#652): as baixas do RM de `diretoria.rm_por_mes`, mes a mes;
- previsao de entrada (#652): `_previsao`, as protocoladas da faixa do ciclo pela data esperada (protocolo + prazo
  do orgao, a mediana de `_prazos_do_orgao`);
- matriz obra por competencia (#659): `_matriz`, a etapa da medicao de cada mes pelo estado dela; a atrasada e' a da
  previsao de entrada (`_esperada`).

Medido no mes: B-01 (10/10/2026) -- a regra da Carteira: medicoes pela COMPETENCIA do mes INTEIRO, em valor CHEIO
(atestado, senao protocolado), como a pagina da medicao mostra. A data de
lancamento fazia a carga do legado virar "setembro R$ 765 mi". Cancelada, desistida e prevista nao contam (a
mesma exclusao do "medido" da Carteira).
"""
import datetime
import math
import statistics

from app import avisos, diretoria, tempo

FORA = diretoria.FORA


def _dia_local(utc: str | None) -> datetime.date | None:
    if not utc:
        return None
    try:
        return tempo.para_local(datetime.datetime.fromisoformat(utc.replace("Z", ""))).date()
    except ValueError:
        return None


def _medido(conn, hoje: datetime.date) -> dict:
    """06/11/2026: o mes do cartao e' a ULTIMA COMPETENCIA FECHADA (o mes anterior a hoje): a medicao de um mes so' e'
    lancada no seguinte, entao o mes corrente ficava sempre zerado. Entra tambem o que o RM mostra e ainda nao tem
    medicao lancada (`diretoria.complemento_rm`), em valor cheio, como as medicoes daqui. Issue #642: a comparacao
    com a competencia anterior e a quebra por contratante sairam da tela e daqui."""
    mes = diretoria._mes(hoje, -1)
    linhas = conn.execute(
        "SELECT criado_em, competencia, COALESCE(valor_atestado_centavos, valor_protocolado_centavos, 0) AS valor "
        f"FROM medicoes WHERE estado NOT IN ({','.join('?' * len(FORA))})", FORA).fetchall()
    atual = quantidade = 0
    ultimo = None
    for r in linhas:
        d = _dia_local(r["criado_em"])
        if d is not None and d <= hoje:
            ultimo = max(ultimo, d) if ultimo else d
        if r["competencia"] == mes:
            atual += r["valor"]; quantidade += 1
    atual += sum(por_comp.get(mes, 0) for por_comp in diretoria.complemento_rm(conn).values())
    return {"competencia": mes, "valor_centavos": atual, "quantidade": quantidade,
            "ultimo_lancamento": ultimo.isoformat() if ultimo else None}


# Issue #642: a faixa do ciclo. Cada etapa com os estados dela e a coluna da data do evento que e' a evidencia (envio
# da planilha, atesto, emissao da nota, primeiro protocolo da nota). "Recebido no mes" vem das baixas do RM.
CICLO = (("em_analise", ("planilha_enviada",), "planilha_enviada_em"),
         ("boletim", ("boletim_recebido", "espelho_gerado", "espelho_enviado"), "atestado_em"),
         ("nota", ("nota_emitida",), "nota_emitida_em"),
         ("protocolado", diretoria.PROTOCOLADAS, "protocolo_em"))


def _ciclo(conn, hoje: datetime.date) -> list[dict]:
    """Quanto dinheiro esta' em cada etapa do ciclo da medicao, na COTA da Lotufo (`diretoria._cota`: o aprovado,
    senao o pedido, medicao a medicao com o arredondamento unico), quantas medicoes e a idade, em dias, da mais
    antiga. So' entra a medicao que tem a data do evento da etapa: a idade conta dessa data ate' hoje, nunca da
    competencia; medicao no estado e sem a data fica fora do valor e da quantidade. "Recebido no mes" sao as baixas
    do RM com data no mes de hoje (`diretoria.recebido_rm_no_mes`); a quantidade dele e' de notas, e nao tem idade."""
    ms = diretoria._medicoes(conn)
    out = []
    for etapa, estados, campo in CICLO:
        com_data = [(m, d) for m, d in ((m, diretoria._d(m[campo])) for m in ms if m["estado"] in estados) if d]
        out.append({"etapa": etapa, "valor_centavos": sum(diretoria._cota(m) for m, _ in com_data),
                    "quantidade": len(com_data),
                    "mais_antigo_dias": max(0, max((hoje - d).days for _, d in com_data)) if com_data else None})
    recebido = diretoria.recebido_rm_no_mes(conn, hoje.strftime("%Y-%m"))
    out.append({"etapa": "recebido_mes", "valor_centavos": recebido["valor_centavos"], "quantidade": recebido["notas"],
                "mais_antigo_dias": None})
    return out


def _ultimos_12_meses(hoje: datetime.date) -> list[str]:
    return [diretoria._mes(hoje, -n) for n in range(11, -1, -1)]


def _recebido_12m(conn, hoje: datetime.date) -> list[dict]:
    """Issue #652: o recebido de cada um dos 12 ultimos meses, terminando no mes de hoje (parcial). Sao as baixas do
    RM pela data da baixa, na cota (`diretoria.rm_por_mes`, a conta do recebido por mes da diretoria)."""
    _, recebido = diretoria.rm_por_mes(conn)
    return [{"mes": mes, "valor_centavos": recebido.get(mes, 0)} for mes in _ultimos_12_meses(hoje)]


PRAZO_MINIMO_CASOS = 5      # #652: com menos recebimentos em 365 dias o contratante fica sem prazo
PRAZO_JANELA_DIAS = 365


def _prazos_do_orgao(ms: list[dict], hoje: datetime.date) -> dict[str, float]:
    """Issue #652: o prazo de cada contratante (a sigla de `diretoria._contratante`, a SINFRA inteira e nao cada
    superintendencia) = a mediana dos dias entre o primeiro protocolo da nota e o recebimento, das medicoes recebidas
    nos ultimos 365 dias. Em amostra par, a media dos dois do meio (pode dar meio dia). Recebimento com data anterior
    ao protocolo nao e' prazo (como em `diretoria._prazo`). Contratante com menos de PRAZO_MINIMO_CASOS fica fora."""
    desde = hoje - datetime.timedelta(days=PRAZO_JANELA_DIAS)
    dias: dict[str, list[int]] = {}
    for m in ms:
        recebida, protocolo = diretoria._d(m["recebida_em"]), diretoria._d(m["protocolo_em"])
        if m["estado"] != "recebida" or not recebida or not protocolo or not desde <= recebida <= hoje or recebida < protocolo:
            continue
        dias.setdefault(diretoria._contratante(m), []).append((recebida - protocolo).days)
    return {k: statistics.median(v) for k, v in dias.items() if len(v) >= PRAZO_MINIMO_CASOS}


def _esperada(m: dict, prazos_: dict[str, float]) -> datetime.date | None:
    """A data esperada do recebimento de uma medicao protocolada: o primeiro protocolo da nota + o prazo do contratante
    (a parte inteira da mediana). Sem a data do protocolo ou com o contratante sem prazo, nao ha' data esperada.
    Atrasada e' a medicao com essa data anterior a hoje, na previsao de entrada e na matriz (#659)."""
    protocolo, prazo = diretoria._d(m["protocolo_em"]), prazos_.get(diretoria._contratante(m))
    if protocolo is None or prazo is None:
        return None
    return protocolo + datetime.timedelta(days=math.floor(prazo))


def _previsao(conn, hoje: datetime.date) -> dict:
    """Issue #652: quando o protocolado deve entrar. As medicoes sao as da etapa "Protocolado" da faixa do ciclo
    (estado protocolado e com a data do primeiro protocolo da nota), na cota (`diretoria._cota`), e cada uma cai em
    uma e so' uma linha, pela data esperada = protocolo + prazo do contratante (a parte inteira da mediana: quem esta'
    protocolado ha' mais dias que a mediana ja' passou da data): `atrasado` (a data ja' passou), `neste_mes`,
    `proximo_mes`, `depois` (alem do proximo mes) e `sem_previsao` (contratante sem prazo)."""
    ms = diretoria._medicoes(conn)
    prazos_ = _prazos_do_orgao(ms, hoje)
    neste, proximo = diretoria._mes(hoje), diretoria._mes(hoje, 1)
    out = {k: {"valor_centavos": 0, "quantidade": 0} for k in ("neste_mes", "proximo_mes", "atrasado", "sem_previsao", "depois")}
    for m in ms:
        protocolo = diretoria._d(m["protocolo_em"])
        if m["estado"] not in diretoria.PROTOCOLADAS or not protocolo:
            continue
        esperada = _esperada(m, prazos_)
        if esperada is None:
            linha = "sem_previsao"
        else:
            mes = esperada.strftime("%Y-%m")
            linha = "atrasado" if esperada < hoje else "neste_mes" if mes == neste else "proximo_mes" if mes == proximo else "depois"
        out[linha]["valor_centavos"] += diretoria._cota(m)
        out[linha]["quantidade"] += 1
    return out


# Issue #659: a etapa de cada estado na matriz, na ordem da menos para a mais adiantada. A protocolada atrasada vem
# antes da protocolada no prazo: na mesma competencia, a celula e' a atrasada.
ETAPAS_MATRIZ = ("em_analise", "boletim", "nota", "atrasado", "protocolado", "recebida")
_ETAPA_DO_ESTADO = {**{estado: etapa for etapa, estados, _ in CICLO for estado in estados}, "recebida": "recebida"}


def _matriz(conn, hoje: datetime.date) -> dict:
    """Issue #659: uma linha por obra ativa, agrupadas pelo contratante (`diretoria._contratante`), e uma celula por
    competencia, as 12 ultimas terminando no mes anterior a hoje. A celula traz a etapa da medicao daquela competencia,
    pelo estado dela (os estados de `CICLO`, mais `recebida`), e a medicao para o link; a protocolada com a data
    esperada (`_esperada`) anterior a hoje e' `atrasado`. Com mais de uma medicao na competencia (execucao e reajuste),
    vale a menos adiantada. Cancelada, desistida, prevista e planilha so' gerada nao pintam: a celula fica nula."""
    competencias = [diretoria._mes(hoje, -n) for n in range(12, 0, -1)]
    ms = diretoria._medicoes(conn)
    prazos_ = _prazos_do_orgao(ms, hoje)
    celulas: dict[tuple[int, str], tuple[int, int]] = {}      # (obra, competencia) -> (ordem da etapa, medicao)
    for m in ms:
        etapa = _ETAPA_DO_ESTADO.get(m["estado"])
        if etapa is None or m["competencia"] not in competencias:
            continue
        if etapa == "protocolado":
            esperada = _esperada(m, prazos_)
            etapa = "atrasado" if esperada is not None and esperada < hoje else etapa
        chave, nova = (m["contrato_id"], m["competencia"]), (ETAPAS_MATRIZ.index(etapa), m["id"])
        celulas[chave] = min(celulas.get(chave, nova), nova)
    grupos: dict[str, list[dict]] = {}
    for c in conn.execute("SELECT c.id, COALESCE(c.nome_curto, c.numero_instrumento) AS obra, o.nome AS orgao_nome, "
                          "o.familia AS orgao_familia, o.chave AS orgao_chave FROM contratos c "
                          "LEFT JOIN orgaos o ON o.id=c.orgao_id WHERE c.estado='ativo'"):
        linha = [celulas.get((c["id"], comp)) for comp in competencias]
        grupos.setdefault(diretoria._contratante(dict(c)), []).append({
            "contrato_id": c["id"], "obra": c["obra"],
            "celulas": [x and {"etapa": ETAPAS_MATRIZ[x[0]], "medicao_id": x[1]} for x in linha]})
    return {"competencias": competencias,
            "grupos": [{"contratante": k, "obras": sorted(v, key=lambda o: (o["obra"] or "", o["contrato_id"]))}
                       for k, v in sorted(grupos.items())]}


def _a_receber(conn, hoje: datetime.date) -> dict:
    """O "protocolado" da Carteira: medicoes protocoladas e cobrancas do RM em aberto, na cota, com a faixa de
    mais de 60 dias. Sem o total liberado (antes da conciliacao), nulo, como na Carteira."""
    liberado = diretoria._liberado(conn)
    if not liberado:
        return {"liberado": False, "valor_centavos": None, "mais_60_centavos": None}
    ms = [m for m in diretoria._medicoes(conn) if m["estado"] in diretoria.PROTOCOLADAS]
    todas = ms + diretoria._notas_em_aberto(conn)
    faixas = diretoria._faixas(todas, hoje, True)
    return {"liberado": True, "valor_centavos": diretoria._grupo_rec(todas)["valor_centavos"],
            "mais_60_centavos": faixas["mais_60"]["valor_centavos"]}


def _protocoladas_dia(conn) -> list[dict]:
    """Medicoes (nao canceladas nem desistidas) com a PRIMEIRA data de protocolo da nota (`etapa='nota'`, como em
    `avisos.resumo_mes`): reprotocolo nao conta de novo."""
    return [dict(r) for r in conn.execute(
        "SELECT m.id, m.contrato_id, COALESCE(m.valor_protocolado_centavos, 0) AS valor, MIN(mp.data) AS data "
        "FROM medicoes m JOIN medicao_protocolos mp ON mp.medicao_id=m.id AND mp.etapa='nota' "
        "WHERE m.estado NOT IN ('cancelada','desistida') GROUP BY m.id")]


def _notas_mes(conn, hoje: datetime.date, linhas: list[dict] | None = None) -> dict:
    """Notas fiscais ativas alocadas (alocacao nao desfeita) as medicoes protocoladas no mes de hoje: valor da nota
    (cada nota uma vez), quantidade de notas e de obras distintas. Issue #642: o acumulado por dia saiu com o
    minigrafico do cartao."""
    mes = hoje.strftime("%Y-%m")
    linhas = _protocoladas_dia(conn) if linhas is None else linhas
    do_mes = {r["id"]: r for r in linhas if (r["data"] or "")[:7] == mes}
    notas: dict[int, dict] = {}
    for a in conn.execute("SELECT a.medicao_id, a.nota_id, n.valor_centavos FROM nf_alocacoes a "
                          "JOIN notas_fiscais n ON n.id=a.nota_id "
                          "WHERE a.desfeita_em IS NULL AND n.situacao='ativa'"):
        m = do_mes.get(a["medicao_id"])
        if m is None:
            continue
        n = notas.setdefault(a["nota_id"], {"valor": a["valor_centavos"], "obras": set()})
        n["obras"].add(m["contrato_id"])
    return {"mes": mes, "valor_centavos": sum(n["valor"] for n in notas.values()), "notas": len(notas),
            "obras": len({o for n in notas.values() for o in n["obras"]})}


def painel(conn, hoje: datetime.date | None = None) -> dict:
    """O painel e' o mesmo para todo perfil. Issue #666: a caixa "Avisos importantes" saiu daqui; a tela le a fila da
    tela Avisos (GET /api/inicio, `avisos.listar`, com o recorte do perfil) e a divide pelo tempo. Issue #699: sairam
    as chaves dos cartoes antigos, que nenhuma tela lia (notas a enviar, certidoes, reajustes, recebido no ano, prazos,
    espelhos)."""
    hoje = hoje or tempo.hoje_local()
    resumo = avisos.resumo_mes(conn, hoje)
    ultima = conn.execute("SELECT MAX(mp.data) FROM medicao_protocolos mp JOIN medicoes m ON m.id=mp.medicao_id "
                          "WHERE mp.etapa='nota' AND m.estado NOT IN ('cancelada','desistida')").fetchone()[0]
    return {
        "hoje": hoje.isoformat(),
        "protocoladas": {"obras_protocoladas": resumo["obras_protocoladas"], "obras_ativas": resumo["obras_ativas"],
                         "ultima": ultima[:10] if ultima else None},
        "medido": _medido(conn, hoje),
        "a_receber": _a_receber(conn, hoje),
        "ciclo": _ciclo(conn, hoje),
        "recebido_12m": _recebido_12m(conn, hoje),
        "previsao": _previsao(conn, hoje),
        "matriz": _matriz(conn, hoje),
        "notas_mes": _notas_mes(conn, hoje),
    }
