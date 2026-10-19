"""Leitura de aditivos: lista do contrato.

Bloco 9: a escrita (rascunho, assinatura, cancelamento, leitura do termo em PDF) saiu; aditivo entra
pelo cadastro versionado (`cadastro/*.yaml` + `python -m app.cli cadastro aplicar`)."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app import aditivos
from app.api_auth import conexao
from app.api_medicoes import ID
from app.permissoes import exigir

router = APIRouter()


def _contrato_existe(conn, contrato_id: int) -> None:
    if conn.execute("SELECT 1 FROM contratos WHERE id=?", (contrato_id,)).fetchone() is None:
        raise HTTPException(404, "Contrato não encontrado")


@router.get("/api/contratos/{contrato_id}/aditivos")
def listar(contrato_id: ID, usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
           conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    return aditivos.listar(conn, contrato_id)

