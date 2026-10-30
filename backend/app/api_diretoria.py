"""Tela da diretoria e exportacao do QDOP (bloco 8; spec 2026-09-21 §10.5). So' leitura; a operacao tambem ve."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app import diretoria, qdop, tempo
from app.api_auth import conexao
from app.permissoes import exigir

router = APIRouter()
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/api/diretoria")
def painel(_=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    return diretoria.painel(conn)


@router.get("/api/a-receber")
def a_receber(_=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    return diretoria.a_receber(conn)


@router.get("/api/diretoria/qdop.xlsx")
def qdop_xlsx(_=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    try:
        dados = qdop.gerar_xlsx(conn)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    nome = f"GL.SGI.FRP.DE.250 - QDOP - {tempo.hoje_local().isoformat()}.xlsx"
    return Response(dados, media_type=MIME_XLSX, headers={"Content-Disposition": f'attachment; filename="{nome}"',
                                                          "X-Content-Type-Options": "nosniff"})
