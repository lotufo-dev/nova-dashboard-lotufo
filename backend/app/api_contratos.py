"""Leitura de contratos. Bloco 9: a escrita saiu; contrato entra pelo cadastro versionado."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app import contratos, diretoria, medicoes, notas, paineis, prazos, tempo
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
    saida = []
    for c in contratos.listar(conn):
        o = orgaos[c["id"]]
        contratante, orgao_sub = medicoes.contratante(o["familia"], o["chave"], o["nome"], o["orgao_texto"])
        feito = medido.get(c["id"], 0)
        saida.append({**c, **prazos.resumo(conn, c["id"], hoje), "contratante": contratante, "orgao_sub": orgao_sub,
                      "medido_execucao_centavos": feito, "saldo_centavos": c["valor_vigente_execucao_centavos"] - feito})
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


@router.get("/{contrato_id}/cadastro")
def cadastro(contrato_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
             conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, contrato_id)
    return contratos.cadastro_da_obra(conn, contrato_id)


@router.get("/{contrato_id}/notas")
def notas_da_obra(contrato_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
                  conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, contrato_id)
    return notas.do_contrato(conn, contrato_id)
