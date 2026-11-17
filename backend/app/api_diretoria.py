"""Numeros da diretoria (bloco 8; spec 2026-09-21 §10.5): o Resumo e o QDOP da lista de Obras, a exportacao do QDOP e
a pagina Fechamento (issue #748). So' leitura; a operacao tambem ve."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app import diretoria, fechamento, qdop, tempo
from app.api_auth import conexao
from app.permissoes import exigir

router = APIRouter()
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/api/diretoria")
def painel(_=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    return diretoria.painel(conn)


@router.get("/api/fechamento")
def fechamento_mensal(_=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    """Issue #748: medido, aprovado, protocolado e recebido por mes de competencia de 2025 e 2026, na cota, com o em
    aberto nota a nota (`app/fechamento.py`)."""
    return fechamento.fechamento(conn)


@router.get("/api/diretoria/qdop.xlsx")
def qdop_xlsx(_=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    try:
        dados = qdop.gerar_xlsx(conn)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    nome = f"GL.SGI.FRP.DE.250 - QDOP - {tempo.hoje_local().isoformat()}.xlsx"
    return Response(dados, media_type=MIME_XLSX, headers={"Content-Disposition": f'attachment; filename="{nome}"',
                                                          "X-Content-Type-Options": "nosniff"})
