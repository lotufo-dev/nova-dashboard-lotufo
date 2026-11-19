"""Busca unica do topo (issue #819): `GET /api/busca?q=`. Sessao e `ver_paineis` (todo perfil); o recorte do que cada
perfil abre e' de `busca.buscar` (o perfil sem SIGA nao recebe o grupo de processos)."""
import sqlite3

from fastapi import APIRouter, Depends, Query

from app import busca
from app.api_auth import conexao
from app.permissoes import exigir

router = APIRouter()


@router.get("/api/busca")
def buscar(q: str = Query(default="", max_length=busca.MAX_PERGUNTA),
           usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
           conn: sqlite3.Connection = Depends(conexao)):
    return busca.buscar(conn, q, usuario["perfil"])
