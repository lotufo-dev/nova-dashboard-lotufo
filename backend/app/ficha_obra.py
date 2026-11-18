"""Ficha executiva da obra (#510): o que a pagina da obra mostra alem do cabecalho e da curva. So' leitura.

A cor da informacao (semaforo, decidido em 06/11/2026): `critico` (vermelho), `atencao` (ambar), `normal` (preto).
O nivel do prazo vem de `prazos.situacao` (`prazos.nivel_do_prazo`), a mesma regra dos avisos e da aba Prazos."""
import datetime
import sqlite3

from app import contratos, medicoes, paineis, prazos, tempo


def _d(iso: str | None) -> datetime.date | None:
    """Dia do negocio (Cuiaba): carimbo com hora vira o dia local (`medicoes._dia`)."""
    return medicoes._dia(iso)


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
            "valor_centavos": m["valor_centavos"], "etapa": m["proximo_passo"],     # #699: o nome do passo da vez
            "desde": m["desde"] or None}


def da_obra(conn: sqlite3.Connection, contrato_id: int, hoje: datetime.date | None = None) -> dict:
    hoje = hoje or tempo.hoje_local()
    v = contratos.vigente(conn, contrato_id)
    # TAs: assinados e nao cancelados, sem o de reajuste (valor corrigido por indice, nao termo do contrato) e sem o
    # que outro aditivo corrige (`corrige_chave`), como `contratos.vigente` os descarta.
    tas = conn.execute(
        "SELECT COUNT(*) FROM aditivos a WHERE a.contrato_id=? AND a.status='assinado' AND a.cancelado_em IS NULL "
        "AND COALESCE(a.natureza, '') <> 'reajuste' AND NOT EXISTS (SELECT 1 FROM aditivos x WHERE x.contrato_id=a.contrato_id "
        "AND x.status='assinado' AND x.cancelado_em IS NULL AND x.corrige_chave = a.chave_cadastro)",
        (contrato_id,)).fetchone()[0]
    base = (v.get("data_base") or "")[:7]
    cab = contratos.cabecalho(conn, contrato_id, hoje)
    # #661: so' o que e' da obra; a certidao e' da empresa e se resolve em Documentos. O painel "Prazo" so' le o fim
    # da execucao (os dias e o nivel); o item da vigencia saiu com o cartao "Proximos vencimentos" (a data da
    # vigencia esta' na linha do tempo, pelo cabecalho da obra).
    venc = [{"chave": "execucao", "rotulo": "Fim da execução", "data": cab["execucao_fim"],
             "dias": cab["dias_execucao"], "nivel": cab["nivel_execucao"]}]
    # #646: o topo numa base so'. Valor vigente, medido e saldo na base de execucao (a precos iniciais, sem o aditivo
    # de reajuste: a mesma de `paineis.saldo`) e na cota da Lotufo. Vigente e medido arredondam uma vez cada e o saldo
    # e' a diferenca dos dois, para a conta da tela fechar ao centavo. O reajuste contratado vai a parte. O medido soma
    # execucao e projeto (#742).
    bp = v["percentual_direito_bp"]
    s = paineis.saldo(conn, contrato_id)
    posicao = paineis.posicao_na_cota(s["vigente_execucao_centavos"], s["medido_centavos"], bp)   # a da lista (#645)
    # #655, #803: o ritmo e o necessario por mes do painel "Prazo" na mesma base do topo, a cota, pela conta que a
    # lista de Obras tambem usa (`prazos.ritmo_na_cota`)
    ritmo = prazos.ritmo_na_cota(conn, contrato_id, hoje, bp, posicao["saldo_centavos"])
    return {"topo": {**posicao,
                     "reajuste_centavos": contratos.cota(s["reajuste_contratado_centavos"], bp)},
            "ritmo": ritmo,
            "contrato": {"original_centavos": contratos.cota(v["valor_original_centavos"], bp),
                         "original_igual": v["valor_original_centavos"] == v["valor_vigente_execucao_centavos"],
                         "tas": tas, "data_base": base or None},
            "ultima_medicao": _ultima(conn, contrato_id), "em_andamento": _em_andamento(conn, contrato_id),
            "vencimentos": venc}
