"""Pagina do contratante (issue #805), abas Medicoes, A receber e Processos no SIGA (issue #818). So' leitura.

Nenhuma conta nova. Cada aba e' o RECORTE, pelas obras do contratante, de uma resposta que outra tela ja' mostra, lida
pela mesma funcao e sem mudar nada nela:
- Medicoes: a fila de trabalho (`fila_medicoes.fila`) na competencia em trabalho, o mes anterior ao de hoje (a mesma
  da tela Medicoes e do Resumo das medicoes): as linhas em andamento por quem tem de agir (cada grupo da mais parada
  para a menos, com a etapa, o tempo parado e a diferenca aprovado x pedido que a fila ja' traz), as concluidas no mes
  e as obras ativas sem medicao nele, so' as das obras do contratante.
- A receber: o grupo do contratante na pagina A receber (`a_receber.a_receber`), o mesmo objeto, sem tirar nem por.
  O subtotal e' o da pagina A receber filtrada por ele (`?contratante=<chave>`), ao centavo. Com o total a receber
  nao liberado, so' a trava, como la'.
- Processos no SIGA: os processos vivos das obras do contratante, na leitura da tela SIGA (`siga.painel`), do mais
  parado para o menos (`siga._mais_parado`, a ordem da tela). O encerrado continua so' na tela SIGA. Processo sem obra
  nao tem contratante e nao entra em aba nenhuma. Quem nao abre a tela SIGA (a diretoria) nao recebe esta aba: a rota
  exige a permissao da tela (`api_contratante.py`).

A chave e' a da pagina do contratante (`/obras/contratante/<chave>`): `fechamento._contratantes`, a mesma da lista de
Obras (`diretoria.chave_do_contratante`) e do `?contratante=` da pagina A receber, comparada sem diferenca de
maiuscula, como la'. Chave que nenhuma obra tem da' o recorte vazio, nao erro.

`quantidade`, em cada aba, e' o numero de linhas que ela mostra; a tela o escreve ao lado do nome da aba. Em
Medicoes: as linhas da fila mais as concluidas no mes (a obra sem medicao nao e' medicao e nao conta). Em A receber: as
linhas do em aberto do contratante, a mesma quantidade da fileira de escolhas da pagina A receber. No SIGA: os
processos.
"""
import datetime

from app import a_receber, diretoria, fechamento, fila_medicoes, siga, tempo


def obras_do(conn, chave: str) -> set[int]:
    """Os contratos do contratante da `chave`, de qualquer estado (o recorte de cada aba decide o que mostra)."""
    alvo = chave.lower()
    return {cid for cid, (_, ch) in fechamento._contratantes(conn).items() if ch is not None and ch.lower() == alvo}


def medicoes(conn, chave: str, hoje: datetime.date | None = None) -> dict:
    hoje = hoje or tempo.hoje_local()
    f = fila_medicoes.fila(conn, hoje, diretoria._mes(hoje, -1))
    ids = obras_do(conn, chave)
    grupos = [{"com_quem": g["com_quem"], "linhas": [x for x in g["linhas"] if x["contrato_id"] in ids]} for g in f["grupos"]]
    grupos = [g for g in grupos if g["linhas"]]
    concluidas = [x for x in f["concluidas"] if x["contrato_id"] in ids]
    return {"hoje": f["hoje"], "mes": f["mes"], "limites": f["limites"], "grupos": grupos, "concluidas": concluidas,
            "sem_medicao": [x for x in f["sem_medicao"] if x["contrato_id"] in ids],
            "quantidade": sum(len(g["linhas"]) for g in grupos) + len(concluidas)}


def em_aberto(conn, chave: str, hoje: datetime.date | None = None) -> dict:
    r = a_receber.a_receber(conn, hoje)
    if not r["total_a_receber_liberado"]:
        return {"anos": r["anos"], "total_a_receber_liberado": False}
    alvo = chave.lower()
    g = next((g for g in r["contratantes"] if g["chave"] is not None and g["chave"].lower() == alvo), None)
    return {"anos": r["anos"], "total_a_receber_liberado": True, "contratante": g, "quantidade": g["quantidade"] if g else 0}


def _mais_parado(p: dict) -> tuple:
    return siga._mais_parado({"dias_uteis": p["dias_uteis"], "desde": p["desde"], "processo_id": p["id"]})


def processos_no_siga(conn, chave: str, agora: datetime.datetime | None = None) -> dict:
    p = siga.painel(conn, agora)
    ids = obras_do(conn, chave)
    processos = sorted((x for x in p["processos"] if x["contrato_id"] in ids and not x["encerrado"]), key=_mais_parado)
    deles = {x["id"] for x in processos}
    # do robo, so' o que as linhas mostram: a rodada em andamento e o "nao lido" de cada processo da aba
    robo = {**p["robo"], "avisos": [a for a in p["robo"]["avisos"] if a["processo_id"] in deles]}
    return {"lido_em": p["lido_em"], "limites": p["limites"], "robo": robo, "processos": processos,
            "quantidade": len(processos)}
