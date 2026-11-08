"""Avisos do motor de medicao (issue #288; spec 2026-10-20 §2.1 "Avisos gerados" e §2.1.1; E4; decisao do Leo de
08/11/2026). Uma fonte do registro unico de `app/avisos.py`, que a tela le sem saber de onde o aviso vem.

- `planilha_nao_enviada` (operacao): obra ativa, nao paralisada, fora da MT-PAR (onde nao ha' o passo). Avisa cada
  competencia de execucao depois da ultima medicao de execucao ja' enviada (planilha enviada ou etapa seguinte, o
  fluxo antigo tambem), ate' o mes anterior a hoje, a partir do dia 5 do mes seguinte. Obra sem medicao enviada conta
  do mes do inicio da execucao; obra reiniciada, do mes do reinicio. Lacunas anteriores nao avisam.
- `pedido_sem_boletim` (operacao; diretoria em 2X): planilha/carta enviada ha' mais de X dias sem boletim, X =
  `prazo_boletim_dias` do orgao. Orgao sem o prazo nao tem o aviso.
- `aprovado_abaixo_do_pedido` (operacao; diretoria acima de 10%): o boletim vigente abaixo do pedido; some com a
  diferenca aceita (do boletim vigente) ou com boletim novo que nao fique abaixo.
- `medicao_fora_de_ordem` (operacao): planilha/carta gerada ou enviada com periodo que pula ou sobrepoe o da medicao
  anterior; some com o periodo corrigido (revisao desta ou da anterior) ou com o boletim registrado.
"""
import datetime
import json

from app import avisos as _av, contratos, prazos, tempo
from app.medicao_planilhas import _mes_br, _mes_seguinte
from app.medicoes import _data_br, diferenca_aceita, tem_boletim, titulo

# a planilha/carta ja' foi ao orgao: o envio dela ou qualquer etapa seguinte (o fluxo antigo nao tem a planilha)
ESTADOS_ENVIADA = ("planilha_enviada", "boletim_recebido", "espelho_gerado", "espelho_enviado", "nota_emitida",
                   "protocolada", "nf_emitida", "recebida")
DIA_DO_AVISO = 5
FAMILIAS_SEM_PEDIDO = ("mtpar",)       # na MT-PAR o oficio vai com a nota: nao ha' planilha/carta do mes
ESTADOS_PERIODO = ("planilha_gerada", "planilha_enviada")


def _destino(cid: int) -> dict:
    return {"tela": "contrato", "id": cid, "aba": "medicoes"}


def _ultimo_reinicio(conn, cid: int) -> str | None:
    return conn.execute("SELECT MAX(data) FROM instrumentos WHERE contrato_id=? AND tipo='reinicio'", (cid,)).fetchone()[0]


def _planilhas_nao_enviadas(conn, hoje: datetime.date) -> list[dict]:
    out = []
    marcas = ",".join("?" * len(ESTADOS_ENVIADA))
    for c in _av.ativos(conn):
        familia = conn.execute("SELECT familia FROM orgaos WHERE id=?", (c["orgao_id"],)).fetchone() \
            if c.get("orgao_id") else None
        if familia is not None and familia["familia"] in FAMILIAS_SEM_PEDIDO:
            continue
        if prazos._paralisacao(conn, c["id"]):      # a mesma regra da aba Prazos
            continue
        reinicio = _ultimo_reinicio(conn, c["id"])
        # depois do fim da execucao nao ha' competencia de execucao a medir (code-review)
        fim = (contratos.vigente(conn, c["id"]).get("execucao_fim_vigente") or "")[:7] or None
        ultima = conn.execute(f"SELECT MAX(competencia) FROM medicoes WHERE contrato_id=? AND tipo='execucao' "
                              f"AND estado IN ({marcas})", (c["id"], *ESTADOS_ENVIADA)).fetchone()[0]
        inicios = [_mes_seguinte(ultima)] if ultima else ([c["execucao_inicio"][:7]] if c.get("execucao_inicio") else [])
        if reinicio:
            inicios.append(reinicio[:7])
        if not inicios:
            continue        # sem medicao enviada, sem inicio da execucao e sem reinicio: nao ha' de quando contar
        mes = max(inicios)
        while fim is None or mes <= fim:
            seguinte = _mes_seguinte(mes)
            dia = datetime.date(int(seguinte[:4]), int(seguinte[5:7]), DIA_DO_AVISO)
            if dia > hoje:
                break
            out.append(_av.aviso("planilha_nao_enviada", "acao", f"planilha/carta de {_mes_br(mes)} não enviada",
                                 c["id"], c["nome_curto"] or c["numero_instrumento"], dias=(hoje - dia).days,
                                 destino=_destino(c["id"]), data=dia.isoformat(), sentido="desde"))
            mes = seguinte
    return out


def _dia(enviado_em: str | None) -> datetime.date | None:
    """O dia do envio: o por fora ja' e' o dia; o do sistema e' instante UTC, que vira o dia em Cuiaba."""
    if not enviado_em:
        return None
    try:
        if len(enviado_em) == 10:
            return datetime.date.fromisoformat(enviado_em)
        return tempo.para_local(datetime.datetime.fromisoformat(enviado_em.replace("Z", "+00:00"))).date()
    except ValueError:
        return None


def _ultimo_envio(conn, m: dict) -> datetime.date | None:
    """O envio mais recente da planilha/carta (a revisao enviada recomeca a conta, como o passo 2 da pagina da obra);
    sem envio listado (historico), o 1o envio gravado na medicao."""
    from app import planilha_envio      # import tardio: planilha_envio importa medicoes, que nao importa este
    dias = [d for d in (_dia(e["enviado_em"]) for e in planilha_envio.envios(conn, m["id"])) if d]
    return max(dias) if dias else _dia((m["planilha_enviada_em"] or "")[:10] or None)


def _pedidos_sem_boletim(conn, hoje: datetime.date) -> list[dict]:
    out = []
    for m in conn.execute(
            "SELECT m.*, c.nome_curto, c.numero_instrumento, o.regras FROM medicoes m JOIN contratos c ON c.id=m.contrato_id "
            "LEFT JOIN orgaos o ON o.id=c.orgao_id WHERE m.estado='planilha_enviada' ORDER BY m.id").fetchall():
        m = dict(m)
        try:
            x = json.loads(m["regras"] or "{}").get("prazo_boletim_dias")
        except (ValueError, AttributeError):
            x = None
        if not isinstance(x, int) or isinstance(x, bool) or x < 1 or tem_boletim(conn, m["id"]):
            continue
        enviado = _ultimo_envio(conn, m)
        if enviado is None:
            continue
        dias = (hoje - enviado).days
        if dias <= x:
            continue
        diretoria = dias > 2 * x
        out.append({**_av.aviso(
            "pedido_sem_boletim", "acao" if diretoria else "atencao",
            f"{titulo(m)}: pedido enviado há {dias} dias sem boletim do órgão (prazo de {x} dias)",
            m["contrato_id"], m["nome_curto"] or m["numero_instrumento"], dias=dias,
            valor_centavos=m["valor_protocolado_centavos"],
            publico=("operacao", "diretoria") if diretoria else ("operacao",), destino=_destino(m["contrato_id"]),
            data=enviado.isoformat(), sentido="desde"), "medicao_id": m["id"]})
    return out


def _aprovados_abaixo(conn, hoje: datetime.date) -> list[dict]:
    from app.dinheiro import format_brl
    out = []
    for m in conn.execute(
            "SELECT m.*, c.nome_curto, c.numero_instrumento FROM medicoes m JOIN contratos c ON c.id=m.contrato_id "
            "WHERE m.estado NOT IN ('cancelada','desistida') AND m.valor_atestado_centavos IS NOT NULL "
            "AND m.valor_protocolado_centavos IS NOT NULL AND m.valor_atestado_centavos < m.valor_protocolado_centavos "
            "ORDER BY m.id").fetchall():
        m = dict(m)
        # o atesto digitado a mao (historico, sem o PDF do orgao) nao e' boletim (#284)
        if not tem_boletim(conn, m["id"]) or diferenca_aceita(conn, m["id"]) is not None:
            continue
        pedido, aprovado = m["valor_protocolado_centavos"], m["valor_atestado_centavos"]
        falta = pedido - aprovado
        diretoria = falta * 10 > pedido        # acima de 10% do pedido, em inteiros
        data = (m["atestado_em"] or "")[:10] or None
        out.append({**_av.aviso(
            "aprovado_abaixo_do_pedido", "acao",
            f"{titulo(m)}: aprovado {format_brl(aprovado)}, abaixo do pedido de {format_brl(pedido)} "
            f"(diferença de {format_brl(falta)})",
            m["contrato_id"], m["nome_curto"] or m["numero_instrumento"],
            dias=(hoje - datetime.date.fromisoformat(data)).days if data else None, valor_centavos=falta,
            publico=("operacao", "diretoria") if diretoria else ("operacao",), destino=_destino(m["contrato_id"]),
            data=data, sentido="desde" if data else None), "medicao_id": m["id"]})
    return out


def _periodo(conn, m: dict) -> tuple[str | None, str | None]:
    """O periodo da planilha/carta vigente (a revisao enviada corrige o da medicao, que congela no envio); sem
    versao registrada, o da medicao."""
    v = conn.execute("SELECT periodo_inicio, periodo_fim FROM medicao_planilhas WHERE medicao_id=? "
                     "ORDER BY versao DESC LIMIT 1", (m["id"],)).fetchone()
    if v is not None and v["periodo_inicio"] and v["periodo_fim"]:
        return v["periodo_inicio"], v["periodo_fim"]
    return m["periodo_inicio"], m["periodo_fim"]


def _fora_de_ordem(conn, hoje: datetime.date) -> list[dict]:
    from app.medicao_planilhas import _anterior
    out = []
    for m in conn.execute(
            "SELECT m.*, c.nome_curto, c.numero_instrumento FROM medicoes m JOIN contratos c ON c.id=m.contrato_id "
            f"WHERE m.estado IN ({','.join('?' * len(ESTADOS_PERIODO))}) ORDER BY m.id", ESTADOS_PERIODO).fetchall():
        m = dict(m)
        inicio, _ = _periodo(conn, m)
        ant = _anterior(conn, m["contrato_id"], m["tipo"], m["numero"])
        if not inicio or ant is None:
            continue
        ant_id = conn.execute("SELECT id FROM medicoes WHERE contrato_id=? AND tipo=? AND numero=?",
                              (m["contrato_id"], m["tipo"], ant["numero"])).fetchone()["id"]
        _, fim_ant = _periodo(conn, {"id": ant_id, "periodo_inicio": ant["periodo_inicio"],
                                     "periodo_fim": ant["periodo_fim"]})
        if not fim_ant:
            continue        # anterior sem periodo registrado (historico): nao ha' com o que comparar
        try:
            ini, fim = datetime.date.fromisoformat(inicio), datetime.date.fromisoformat(fim_ant)
        except ValueError:
            continue
        if ini <= fim:
            texto = f"o período se sobrepõe ao da {ant['numero']}ª medição, que vai até {_data_br(fim_ant)}"
        elif ini > fim + datetime.timedelta(days=1):
            texto = (f"o período pula dias (a {ant['numero']}ª medição terminou em {_data_br(fim_ant)} e esta começa "
                     f"em {_data_br(inicio)})")
        else:
            continue
        out.append({**_av.aviso("medicao_fora_de_ordem", "atencao", f"{titulo(m)}: {texto}", m["contrato_id"],
                                m["nome_curto"] or m["numero_instrumento"], destino=_destino(m["contrato_id"])),
                    "medicao_id": m["id"]})
    return out


def avisos(conn, hoje: datetime.date) -> list[dict]:
    return (_planilhas_nao_enviadas(conn, hoje) + _pedidos_sem_boletim(conn, hoje) + _aprovados_abaixo(conn, hoje)
            + _fora_de_ordem(conn, hoje))
