"""Pagina Inicio do redesenho (decisoes do Leonardo de 08/10/2026). So' leitura; tudo de uma vez.

Nada e' calculado de novo aqui: cada numero vem do modulo que ja' o calcula para a tela de origem.
- notas a enviar: `notas_envio.a_enviar` (Notas › A enviar), o contador "Todas";
- certidoes vencidas ou vencendo em ate' 15 dias: `cobranca_certidoes.listas` (a mesma lista do e-mail);
- reajuste a pedir: os avisos `reajuste_pleito` de `reajuste.avisos` (data-base na janela, pleito nao enviado);
- obras protocoladas: `avisos.resumo_mes` (o mesmo "X de N obras ativas" da fila de Medicoes);
- a receber: a regra da Carteira (`diretoria`), na COTA da Lotufo, so' com o total liberado;
- recebido no ano: a regra do "recebido no mes" da Carteira (medicao recebida, pela data da baixa, na cota);
- prazos: `prazos.situacao` (execucao e vigencia) e `reajuste.ciclos` (data-base).

Medido no mes: B-01 (10/10/2026) -- a regra da Carteira: medicoes pela COMPETENCIA do mes contra a competencia
do mes anterior INTEIRO, em valor CHEIO (atestado, senao protocolado), como a pagina da medicao mostra. A data de
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


def _medido(conn, hoje: datetime.date) -> tuple[dict, list[dict]]:
    mes, ant = diretoria._mes(hoje), diretoria._mes(hoje, -1)
    linhas = conn.execute(
        "SELECT m.criado_em, m.competencia, COALESCE(m.valor_atestado_centavos, m.valor_protocolado_centavos, 0) AS valor, "
        "c.orgao_id, c.orgao AS orgao_texto, o.familia, o.chave, o.nome "
        f"FROM medicoes m JOIN contratos c ON c.id=m.contrato_id LEFT JOIN orgaos o ON o.id=c.orgao_id "
        f"WHERE m.estado NOT IN ({','.join('?' * len(FORA))})", FORA).fetchall()
    atual = anterior = quantidade = 0
    ultimo = None
    grupos: dict[str, dict] = {}
    for r in linhas:
        d = _dia_local(r["criado_em"])
        if d is not None and d <= hoje:
            ultimo = max(ultimo, d) if ultimo else d
        if r["competencia"] not in (mes, ant):
            continue
        nome = _contratante(r["familia"], r["chave"], r["nome"], r["orgao_texto"])
        g = grupos.setdefault(nome, {"contratante": nome, "atual_centavos": 0, "anterior_centavos": 0})
        if r["competencia"] == mes:
            atual += r["valor"]; quantidade += 1
            g["atual_centavos"] += r["valor"]
        else:
            anterior += r["valor"]
            g["anterior_centavos"] += r["valor"]
    medido = {"competencia": mes, "anterior_competencia": ant, "valor_centavos": atual, "anterior_centavos": anterior,
              "quantidade": quantidade, "ultimo_lancamento": ultimo.isoformat() if ultimo else None}
    por = sorted(grupos.values(), key=lambda g: (-max(g["atual_centavos"], g["anterior_centavos"]), g["contratante"]))
    return medido, por


def _recebido_ano(conn, hoje: datetime.date) -> dict:
    """Medicoes recebidas com a baixa no ano, na cota. Se ha' recebida SEM data de competencia deste ano ou do
    anterior (o corte de 22/09 fechou as protocoladas como recebidas sem dia), o total do ano nao e' confiavel:
    volta nulo, com a contagem das sem data."""
    ano = f"{hoje.year:04d}"
    ms = [m for m in diretoria._medicoes(conn) if m["estado"] == "recebida"]
    sem_data = sum(1 for m in ms if not m["recebida_em"] and (m["competencia"] or "")[:4] >= f"{hoje.year - 1:04d}")
    mes = hoje.strftime("%Y-%m")
    no_ano = [m for m in ms if (m["recebida_em"] or "")[:4] == ano]
    return {"valor_centavos": None if sem_data else sum(diretoria._cota(m) for m in no_ano),
            "mes_centavos": sum(diretoria._cota(m) for m in no_ano if m["recebida_em"][:7] == mes),
            "sem_data": sem_data}


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


def painel(conn, hoje: datetime.date | None = None) -> dict:
    hoje = hoje or tempo.hoje_local()
    vencidas, vencendo = cobranca_certidoes.listas(conn, hoje)
    pedir = [a for a in reajuste.avisos(conn, hoje) if a["tipo"] == "reajuste_pleito"]
    resumo = avisos.resumo_mes(conn, hoje)
    ultima = conn.execute("SELECT MAX(mp.data) FROM medicao_protocolos mp JOIN medicoes m ON m.id=mp.medicao_id "
                          "WHERE mp.etapa='nota' AND m.estado NOT IN ('cancelada','desistida')").fetchone()[0]
    medido, por_contratante = _medido(conn, hoje)
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
        "medido": medido,
        "por_contratante": por_contratante,
        "recebido_ano": _recebido_ano(conn, hoje),
        "a_receber": _a_receber(conn, hoje),
        "prazos": _prazos(conn, hoje),
    }
