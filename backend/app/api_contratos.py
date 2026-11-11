"""Leitura de contratos. Bloco 9: a escrita saiu; contrato entra pelo cadastro versionado."""
import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app import contratos, diretoria, ficha_obra, medicoes, notas, paineis, prazos, tempo
from app.api_auth import conexao
from app.api_medicoes import ID
from app.permissoes import exigir

router = APIRouter(prefix="/api/contratos")


def _existe(conn: sqlite3.Connection, contrato_id: int) -> None:
    """404 antes de tocar no repositorio.

    As leituras de `contratos` assumem que o contrato existe (subscrito no fetchone)
    e estourariam TypeError com id inexistente -- a rota tem que barrar antes.
    """
    if conn.execute("SELECT id FROM contratos WHERE id=?", (contrato_id,)).fetchone() is None:
        raise HTTPException(404, "Contrato não encontrado")


@router.get("")
def listar(usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
           conn: sqlite3.Connection = Depends(conexao)):
    # A9: os dias ate' o fim da execucao e da vigencia e o pedido de prorrogacao em curso, por obra.
    # Redesenho de Obras (#159): o medido de execucao e o saldo a executar, em valor cheio (a mesma conta do saldo
    # do cronograma da obra, `paineis.saldo`), para o % executado e para a soma por contratante.
    # O contratante e' o mesmo de Medicoes ("SINFRA" para toda a familia, com a superintendencia em `orgao_sub`).
    hoje = tempo.hoje_local()
    orgaos = {r["id"]: r for r in conn.execute(
        "SELECT c.id, c.orgao AS orgao_texto, o.familia, o.chave, o.nome FROM contratos c LEFT JOIN orgaos o ON o.id=c.orgao_id")}
    medido = paineis.medido_execucao_por_contrato(conn)       # uma consulta so', nao uma por obra
    # #645: a lista de Obras le `posicao`, na cota da Lotufo: vigente, medido e saldo pela conta do topo da pagina da
    # obra (`paineis.posicao_na_cota`) e o a receber cobranca a cobranca, como a tela A receber; sem o total
    # liberado, nulo (a tela mostra "—"). O a receber cheio saiu da lista (so' ela o lia).
    a_receber = diretoria.a_receber_por_obra(conn, na_cota=True)
    saida = []
    for c in contratos.listar(conn):
        o = orgaos[c["id"]]
        contratante, orgao_sub = medicoes.contratante(o["familia"], o["chave"], o["nome"], o["orgao_texto"])
        feito = medido.get(c["id"], 0)
        saida.append({**c, **prazos.resumo(conn, c["id"], hoje), "contratante": contratante, "orgao_sub": orgao_sub,
                      "medido_execucao_centavos": feito, "saldo_centavos": c["valor_vigente_execucao_centavos"] - feito,
                      "posicao": {**paineis.posicao_na_cota(c["valor_vigente_execucao_centavos"], feito, c["percentual_direito_bp"]),
                                  "a_receber_centavos": None if a_receber is None else a_receber.get(c["id"], 0)}})
    return saida


@router.get("/{contrato_id}")
def detalhe(contrato_id: ID, usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
            conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, contrato_id)
    return contratos.vigente(conn, contrato_id)


@router.get("/{contrato_id}/cabecalho")
def cabecalho(contrato_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
              conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, contrato_id)
    # A3: faturado e a receber da obra, em valor cheio, ao lado do valor vigente.
    return {**contratos.cabecalho(conn, contrato_id), **diretoria.da_obra(conn, contrato_id)}


@router.get("/{contrato_id}/ficha")
def ficha(contrato_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
          conn: sqlite3.Connection = Depends(conexao)):
    """#510: contrato, ultima medicao, medicao em andamento e proximos vencimentos da ficha executiva da obra."""
    _existe(conn, contrato_id)
    return ficha_obra.da_obra(conn, contrato_id)


@router.get("/{contrato_id}/cadastro")
def cadastro(contrato_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
             conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, contrato_id)
    return contratos.cadastro_da_obra(conn, contrato_id)


@router.get("/{contrato_id}/custo-rm")
def custo_rm(contrato_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
             conn: sqlite3.Connection = Depends(conexao)):
    """#488: o custo por tarefa e a baixa de estoque do RM da obra, pelo centro de custo atual e pelos anteriores,
    na coligada da entidade do contrato; consorcio sem centro, pela coligada inteira so' se for a unica obra dela.
    Linhas como vieram do RM (o que nao e' custo a tela separa)."""
    _existe(conn, contrato_id)
    c = conn.execute("""SELECT c.centro_custo_rm, c.centros_custo_anteriores_rm, e.coligada_rm
                        FROM contratos c JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1) WHERE c.id=?""",
                     (contrato_id,)).fetchone()
    if c is None or c["coligada_rm"] is None:
        return {"custo": [], "estoque": []}
    centros = [c["centro_custo_rm"], *json.loads(c["centros_custo_anteriores_rm"] or "[]")]
    centros = sorted({x.strip() for x in centros if x and x.strip()})
    if centros:
        filtro = f"coligada=? AND centro_custo IN ({','.join('?' * len(centros))})"
    elif c["coligada_rm"] != 1 and conn.execute(
            """SELECT COUNT(*) FROM contratos c JOIN entidades e ON e.id=COALESCE(c.entidade_id, 1)
               WHERE e.coligada_rm=?""", (c["coligada_rm"],)).fetchone()[0] == 1:
        # so' quando e' a unica obra da coligada: com duas, a coligada nao diz de qual obra e' o custo
        filtro = "coligada=?"
    else:
        return {"custo": [], "estoque": []}
    args = (c["coligada_rm"], *centros)
    custo = conn.execute(f"""SELECT centro_custo, projeto, tarefa, natureza, mes, qtd, valor_centavos
                             FROM rm_custo_tarefas WHERE {filtro}
                             ORDER BY mes, centro_custo, tarefa, natureza, id""", args)
    estoque = conn.execute(f"""SELECT centro_custo, tipo_movimento, mes, qtd, valor_centavos
                               FROM rm_estoque_baixas WHERE {filtro}
                               ORDER BY mes, centro_custo, tipo_movimento, id""", args)
    return {"custo": [dict(r) for r in custo], "estoque": [dict(r) for r in estoque]}


@router.get("/{contrato_id}/notas")
def notas_da_obra(contrato_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
                  conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, contrato_id)
    return notas.do_contrato(conn, contrato_id)


@router.get("/{contrato_id}/custo-grupos")
def custo_grupos(contrato_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
                 conn: sqlite3.Connection = Depends(conexao)):
    # Issue #489: grupos da planilha do orgao com as tarefas do RM; obra sem secao `custo:` devolve lista vazia.
    _existe(conn, contrato_id)
    return contratos.custo_grupos(conn, contrato_id)
