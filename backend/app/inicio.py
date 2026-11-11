"""Pagina Inicio do redesenho (decisoes do Leonardo de 08/10/2026). So' leitura; tudo de uma vez.

Nada e' calculado de novo aqui: cada numero vem do modulo que ja' o calcula para a tela de origem.
- notas a enviar: `notas_envio.a_enviar` (Notas › A enviar), o contador "Todas";
- certidoes vencidas ou vencendo em ate' 15 dias: `cobranca_certidoes.listas` (a mesma lista do e-mail);
- reajuste a pedir: os avisos `reajuste_pleito` de `reajuste.avisos` (data-base na janela, pleito nao enviado);
- obras protocoladas: `avisos.resumo_mes` (o mesmo "X de N obras ativas" da fila de Medicoes);
- a receber: a regra da Carteira (`diretoria`), na COTA da Lotufo, so' com o total liberado;
- recebido no ano: a regra do "recebido no mes" da Carteira (medicao recebida, pela data da baixa, na cota);
- prazos: `prazos.situacao` (execucao e vigencia) e `reajuste.ciclos` (data-base);
- faixa do ciclo (#642): `_ciclo`, na cota, so' com a data do evento de cada etapa.

Medido no mes: B-01 (10/10/2026) -- a regra da Carteira: medicoes pela COMPETENCIA do mes INTEIRO, em valor CHEIO
(atestado, senao protocolado), como a pagina da medicao mostra. A data de
lancamento fazia a carga do legado virar "setembro R$ 765 mi". Cancelada, desistida e prevista nao contam (a
mesma exclusao do "medido" da Carteira).
"""
import datetime

from app import avisos, cobranca_certidoes, diretoria, notas_envio, prazos, reajuste, tempo

FORA = diretoria.FORA
HORIZONTE_PRAZOS = 90      # dias: o que vence ate' la' entra em "Prazos chegando"


def _dia_local(utc: str | None) -> datetime.date | None:
    if not utc:
        return None
    try:
        return tempo.para_local(datetime.datetime.fromisoformat(utc.replace("Z", ""))).date()
    except ValueError:
        return None


def _contratante(familia: str | None, chave: str | None, nome: str | None, orgao_texto: str | None) -> str:
    if familia:
        return notas_envio._grupo(familia, {"chave": chave, "nome": nome})
    return orgao_texto or "sem contratante"


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


def _recebido_ano(conn, hoje: datetime.date) -> dict:
    """Medicoes recebidas com a baixa no ano, na cota. Se ha' recebida SEM data de competencia deste ano ou do
    anterior (o corte de 22/09 fechou as protocoladas como recebidas sem dia), o total do ano nao e' confiavel:
    volta nulo, com a contagem das sem data."""
    ano = f"{hoje.year:04d}"
    ms = [m for m in diretoria._medicoes(conn) if m["estado"] == "recebida"]
    sem_data = sum(1 for m in ms if not m["recebida_em"] and (m["competencia"] or "")[:4] >= f"{hoje.year - 1:04d}")
    mes = hoje.strftime("%Y-%m")
    no_ano = [m for m in ms if (m["recebida_em"] or "")[:4] == ano]
    # 06/11/2026: o recebido de verdade do ano sao as baixas do RM (`diretoria.rm_por_mes`), que nao dependem da data
    # gravada na medicao; e' o que o cartao do Inicio mostra. Os campos das medicoes seguem para quem os usa.
    _, real = diretoria.rm_por_mes(conn)
    return {"valor_centavos": None if sem_data else sum(diretoria._cota(m) for m in no_ano),
            "mes_centavos": sum(diretoria._cota(m) for m in no_ano if m["recebida_em"][:7] == mes),
            "sem_data": sem_data,
            "real_centavos": sum(v for m, v in real.items() if m[:4] == ano and m <= mes)}


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


def _prazos(conn, hoje: datetime.date) -> list[dict]:
    """Execucao e vigencia dos contratos ativos (vigencia so' onde o orgao nao prorroga sozinho; execucao parada
    enquanto ha' paralisacao; obra em encerramento fora, como nos avisos) e a data-base de reajuste que ainda
    vai fazer aniversario, ate' HORIZONTE_PRAZOS dias. Execucao e vigencia vencidas tambem entram (dias < 0);
    a data-base que ja' passou sem pleito e' o cartao "reajuste a pedir"."""
    out = []
    for c in conn.execute("SELECT c.id, c.estado, c.orgao AS orgao_texto, "
                          "COALESCE(c.nome_curto, c.numero_instrumento) AS obra, c.encerramento_iniciado_em, "
                          "o.familia, o.chave, o.nome FROM contratos c LEFT JOIN orgaos o ON o.id=c.orgao_id "
                          "WHERE c.estado IN ('ativo','suspenso')"):
        base = {"contrato_id": c["id"], "obra": c["obra"],
                "contratante": _contratante(c["familia"], c["chave"], c["nome"], c["orgao_texto"])}
        if c["estado"] == "ativo" and not c["encerramento_iniciado_em"]:
            s = prazos.situacao(conn, c["id"], hoje)
            if not s["paralisacao"] and s["dias_execucao"] is not None and s["dias_execucao"] <= HORIZONTE_PRAZOS:
                out.append({**base, "tipo": "execucao", "data": s["execucao_fim"][:10], "dias": s["dias_execucao"]})
            if not s["vigencia_automatica"] and s["dias_vigencia"] is not None and s["dias_vigencia"] <= HORIZONTE_PRAZOS:
                out.append({**base, "tipo": "vigencia", "data": s["vigencia_fim"][:10], "dias": s["dias_vigencia"]})
        for k in reajuste.ciclos(conn, c["id"], hoje):
            if k["situacao"] in ("futuro", "pleito_pendente") and 0 <= k["dias"] <= HORIZONTE_PRAZOS:
                out.append({**base, "tipo": "data_base", "data": k["aniversario"], "dias": k["dias"],
                            "data_base_mes": k["data_base_mes"]})
    return sorted(out, key=lambda x: (x["dias"], x["obra"] or ""))


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


AVISOS_VISIVEIS = 3
# Issue #274: o que a secao Reajustes dos avisos importantes mostra (o pleito a pedir e os avisos do motor de
# apostilamento; o "apostilamento pendente" de antes continua so' na tela Avisos)
AVISOS_REAJUSTE_NA_CAIXA = ("reajuste_pleito", "reajuste_fora_da_previsao", "reajuste_sem_apostilamento",
                            "reajuste_nota_antes_do_apostilamento", "reajuste_reemitir", "reajuste_sem_resposta")


def _avisos_importantes(reajustes: list[dict], prazos_: list[dict], vencidas: list[dict], vencendo: list[dict],
                        hoje: datetime.date) -> dict:
    """Caixa "Avisos importantes": contagem e tres itens dos avisos de reajuste (`reajustes`, ja' na ordem do mais
    grave), prazos de execucao e vigencia (vencidos primeiro) e certidoes (vencidas primeiro, depois as que vencem
    antes). Cada secao leva a uma familia da tela Avisos (`reajuste`, `prazo`, `documentos`)."""
    certidoes = []
    for x, vencida in [(x, True) for x in vencidas] + [(x, False) for x in vencendo]:
        dias = x["dias"]
        if dias is None and x["validade"]:
            dias = (datetime.date.fromisoformat(x["validade"][:10]) - hoje).days
        certidoes.append({"tipo": x["tipo"], "entidade": x["entidade"], "validade": x["validade"], "dias": dias,
                          "vencida": vencida})
    certidoes.sort(key=lambda c: (c["dias"] is None, c["dias"] if c["dias"] is not None else 0))
    prazos_ = [p for p in prazos_ if p["tipo"] in ("execucao", "vigencia")]
    # rodada 2 da PR #579: um item por obra e tipo (tres competencias da mesma obra nao tomam os tres lugares), na
    # posicao do mais grave, com as competencias e as datas-base que juntou; o total conta esses itens (mesma unidade das linhas)
    grupos: dict[tuple[int, str], dict] = {}
    for a in reajustes:
        g = grupos.setdefault((a["contrato_id"], a["tipo"]), {
            "contrato_id": a["contrato_id"], "obra": a["obra"], "dias": a["dias"], "tipo": a["tipo"],
            "nivel": a["nivel"], "data_base_mes": a.get("data_base_mes"), "competencias": [], "datas_base": []})
        for comp in ([a["competencia"]] if a.get("competencia") else a.get("competencias") or []):
            if comp not in g["competencias"]:
                g["competencias"].append(comp)
        if a.get("data_base_mes") and a["data_base_mes"] not in g["datas_base"]:
            g["datas_base"].append(a["data_base_mes"])
    reaj = list(grupos.values())
    return {
        "reajustes": {"total": len(reaj), "itens": reaj[:AVISOS_VISIVEIS]},
        "prazos": {"total": len(prazos_), "itens": [{"contrato_id": p["contrato_id"], "obra": p["obra"], "tipo": p["tipo"],
                                                    "dias": p["dias"]} for p in prazos_[:AVISOS_VISIVEIS]]},
        "certidoes": {"total": len(certidoes), "itens": certidoes[:AVISOS_VISIVEIS]},
    }


def painel(conn, hoje: datetime.date | None = None, publico: str = "operacao") -> dict:
    """`publico`: o perfil de quem le (`operacao` ou `diretoria`, como `api_inicio.inicio`). Os avisos do motor de
    apostilamento na secao Reajustes seguem o publico de cada um (rodada 2 da PR #579); o pleito a pedir aparece para
    todo perfil, como antes."""
    hoje = hoje or tempo.hoje_local()
    vencidas, vencendo = cobranca_certidoes.listas(conn, hoje)
    reaj = reajuste.avisos(conn, hoje)
    pedir = [a for a in reaj if a["tipo"] == "reajuste_pleito"]
    # issue #274: a secao Reajustes dos avisos importantes traz o pleito a pedir e os avisos do motor de apostilamento
    reaj_caixa = sorted((a for a in reaj if a["tipo"] in AVISOS_REAJUSTE_NA_CAIXA
                         and (a["tipo"] == "reajuste_pleito" or publico in a["publico"])),
                        key=lambda a: (avisos.NIVEIS.index(a["nivel"]), avisos._chave_atraso(a, hoje), a["obra"] or ""))
    resumo = avisos.resumo_mes(conn, hoje)
    ultima = conn.execute("SELECT MAX(mp.data) FROM medicao_protocolos mp JOIN medicoes m ON m.id=mp.medicao_id "
                          "WHERE mp.etapa='nota' AND m.estado NOT IN ('cancelada','desistida')").fetchone()[0]
    prazos_lista = _prazos(conn, hoje)
    return {
        "hoje": hoje.isoformat(),
        "notas_a_enviar": notas_envio.a_enviar(conn, hoje)["contadores"]["Todas"],
        "certidoes": {"vencidas": len(vencidas), "vencendo": len(vencendo),
                      "itens": [{"tipo": x["tipo"], "entidade": x["entidade"], "validade": x["validade"],
                                 "dias": x["dias"], "vencida": x in vencidas} for x in vencidas + vencendo]},
        "reajustes": [{"contrato_id": a["contrato_id"], "obra": a["obra"], "data_base_mes": a["data_base_mes"],
                       "aniversario": a["data"], "dias": a["dias"]} for a in sorted(pedir, key=lambda a: a["dias"])],
        "protocoladas": {"obras_protocoladas": resumo["obras_protocoladas"], "obras_ativas": resumo["obras_ativas"],
                         "ultima": ultima[:10] if ultima else None},
        "medido": _medido(conn, hoje),
        "recebido_ano": _recebido_ano(conn, hoje),
        "a_receber": _a_receber(conn, hoje),
        "prazos": prazos_lista,
        "espelhos": _espelhos(conn),
        "ciclo": _ciclo(conn, hoje),
        "notas_mes": _notas_mes(conn, hoje),
        "avisos_importantes": _avisos_importantes(reaj_caixa, prazos_lista, vencidas, vencendo, hoje),
    }


def _espelhos(conn) -> list[dict]:
    """Issue #359: os espelhos vigentes com medicao de aprovado mudado depois deles (`espelhos.desatualizadas`, a
    mesma fonte do aviso), um por espelho (execucao e reajuste do mesmo espelho contam uma vez, rodada 2 da PR #474),
    para o cartao do Inicio levar a eles. De cada espelho, a medicao da situacao que pede o ato (espelhos.PRIORIDADE)."""
    from app import espelhos, medicoes      # import local: espelhos importa medicoes e correio
    por_espelho: dict[int, dict] = {}
    for m in espelhos.desatualizadas(conn):
        atual = por_espelho.get(m["espelho_id"])
        if atual is None or espelhos.PRIORIDADE[m["situacao"]] < espelhos.PRIORIDADE[atual["situacao"]]:
            por_espelho[m["espelho_id"]] = {"espelho_id": m["espelho_id"], "contrato_id": m["contrato_id"],
                                            "medicao_id": m["id"], "obra": m["obra"], "titulo": medicoes.titulo(m),
                                            "situacao": m["situacao"]}
    return [por_espelho[k] for k in sorted(por_espelho)]
