"""Ficha executiva da obra (#510): o que a pagina da obra mostra alem do cabecalho e da curva. So' leitura.

A cor da informacao (semaforo, decidido em 06/11/2026) e' decidida AQUI, num lugar so': `critico` (vermelho),
`atencao` (ambar), `normal` (preto)."""
import datetime
import sqlite3

from app import contratos, documentos, entidades, medicoes, tempo

CRITICO_DIAS = 30      # prazo de execucao/vigencia a ate' 30 dias (ou ja' vencido): vermelho
ATENCAO_DIAS = 90      # ate' 90 dias: ambar

# O passo atual da medicao em andamento, na palavra de quem opera.
ETAPA = {"planilha_gerada": "planilha gerada", "planilha_enviada": "planilha enviada ao órgão",
         "boletim_recebido": "boletim recebido", "espelho_gerado": "espelho gerado",
         "espelho_enviado": "no faturamento", "nota_emitida": "nota emitida",
         "protocolada": "análise do órgão", "nf_emitida": "análise do órgão"}


def nivel_do_prazo(dias: int | None) -> str:
    if dias is None:
        return "normal"
    return "critico" if dias <= CRITICO_DIAS else "atencao" if dias <= ATENCAO_DIAS else "normal"


def _d(iso: str | None) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(iso[:10]) if iso else None
    except ValueError:
        return None


def _rotulo(m) -> str:
    """"15ª" para a medicao de execucao; as de projeto e reajuste levam o titulo inteiro."""
    return f"{m['numero']}ª" if m["tipo"] == "execucao" else medicoes.titulo(m)


def _ultima(conn, contrato_id: int) -> dict | None:
    m = conn.execute("SELECT * FROM medicoes WHERE contrato_id=? AND estado='recebida' "
                     "ORDER BY competencia DESC, numero DESC, id DESC LIMIT 1", (contrato_id,)).fetchone()
    if m is None:
        return None
    recebida, nota = _d(m["recebida_em"]), _d(m["nota_emitida_em"])
    return {"id": m["id"], "titulo": medicoes.titulo(m), "rotulo": _rotulo(m), "numero": m["numero"], "competencia": m["competencia"],
            "valor_centavos": (medicoes.valor_travado(m) or (m["valor_protocolado_centavos"],))[0],
            "recebida_em": recebida.isoformat() if recebida else None,
            "dias_apos_nota": (recebida - nota).days if recebida and nota and recebida >= nota else None}


def _em_andamento(conn, contrato_id: int) -> dict | None:
    lista = medicoes.em_andamento(conn, contrato_id)
    if not lista:
        return None
    m = max(lista, key=lambda x: (x["competencia"], x["numero"], x["id"]))
    return {"id": m["id"], "titulo": m["titulo"], "rotulo": _rotulo(m), "numero": m["numero"], "competencia": m["competencia"],
            "valor_centavos": m["valor_centavos"], "etapa": ETAPA.get(m["estado"], m["proximo_passo"]),
            "desde": m["desde"] or None, "outras": len(lista) - 1}


def _certidao_mais_proxima(conn, contrato_id: int, hoje: datetime.date) -> dict | None:
    ex = documentos.exigidos(conn, contrato_id, "execucao")
    achados = []
    for eid in ex["entidades"]:
        e = entidades.detalhe(conn, eid)
        if e is None or not e["ativo"]:
            continue
        for t in ex["tipos"]:
            s = documentos.situacao(conn, eid, t, hoje)
            cert = s["certidao"]
            if s["situacao"] in ("ok", "vencendo", "vencida") and cert and _d(cert["validade"]):
                achados.append((cert["validade"][:10], eid, t, s["situacao"], e))
    if not achados:
        return None
    validade, _, t, situacao, e = min(achados, key=lambda a: (a[0], a[1], a[2]["id"]))
    dias = (_d(validade) - hoje).days
    rotulo = f"{documentos.ROTULO.get(t['chave'], t['nome'])} {documentos._nome(e)}"
    return {"chave": "certidao", "rotulo": rotulo[:1].upper() + rotulo[1:], "data": validade, "dias": dias,
            "nivel": "critico" if situacao == "vencida" else "atencao" if situacao == "vencendo" else "normal"}


def da_obra(conn: sqlite3.Connection, contrato_id: int, hoje: datetime.date | None = None) -> dict:
    hoje = hoje or tempo.hoje_local()
    v = contratos.vigente(conn, contrato_id)
    tas = conn.execute("SELECT COUNT(*) FROM aditivos WHERE contrato_id=? AND status='assinado'", (contrato_id,)).fetchone()[0]
    base = (v.get("data_base") or "")[:7]
    cab = contratos.cabecalho(conn, contrato_id, hoje)
    venc = []
    cert = _certidao_mais_proxima(conn, contrato_id, hoje)
    if cert:
        venc.append(cert)
    venc.append({"chave": "execucao", "rotulo": "Fim da execução", "data": cab["execucao_fim"],
                 "dias": cab["dias_execucao"], "nivel": nivel_do_prazo(cab["dias_execucao"])})
    venc.append({"chave": "vigencia", "rotulo": "Fim da vigência", "data": cab["vigencia_fim"],
                 "dias": cab["dias_vigencia"], "nivel": nivel_do_prazo(cab["dias_vigencia"])})
    return {"contrato": {"original_centavos": v["valor_original_centavos"],
                         "original_igual": v["valor_original_centavos"] == v["valor_vigente_centavos"],
                         "tas": tas, "data_base": base or None},
            "ultima_medicao": _ultima(conn, contrato_id), "em_andamento": _em_andamento(conn, contrato_id),
            "vencimentos": venc}
