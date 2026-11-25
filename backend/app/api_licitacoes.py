"""Rotas das telas de Licitacoes (issue #908, docs/adr/0018): sessao e `ver_licitacoes`. So' leitura nesta fatia: as
favoritas sao espelho do que o radar manda (`api_radar.py`)."""
import sqlite3

from fastapi import APIRouter, Depends

from app import licitacoes
from app.api_auth import conexao
from app.permissoes import VER_LICITACOES, exigir

router = APIRouter()


@router.get("/api/licitacoes/triagem")
def triagem(conn: sqlite3.Connection = Depends(conexao), _=Depends(exigir(VER_LICITACOES, com_csrf=False))):
    return licitacoes.triagem(conn)


@router.get("/api/licitacoes/favoritas")
def favoritas(conn: sqlite3.Connection = Depends(conexao), _=Depends(exigir(VER_LICITACOES, com_csrf=False))):
    return licitacoes.favoritas(conn)
