"""Tela inicial e lista de medicoes em andamento (bloco 6; spec 2026-09-21 §10.1 e §10.2). So' leitura.

Registrado ANTES do router de medicoes: `/api/medicoes/andamento` e `/api/medicoes/resumo` nao podem cair em
`/api/medicoes/{medicao_id}`."""
import sqlite3

from fastapi import APIRouter, Depends, Query

from app import avisos, inicio as pagina_inicio, medicoes
from app.api_auth import conexao
from app.api_medicoes import MAX_INT64
from app.permissoes import exigir

router = APIRouter()


@router.get("/api/inicio")
def inicio(usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
           conn: sqlite3.Connection = Depends(conexao)):
    publico = "diretoria" if usuario.get("perfil") == "diretoria" else "operacao"
    return {"avisos": avisos.listar(conn, publico=publico), "resumo": avisos.resumo_mes(conn)}


@router.get("/api/inicio/painel")
def painel(usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    """Pagina Inicio do redesenho (08/10/2026): cartoes, numeros, faixa do ciclo (#642) e prazos. Os avisos de
    reajuste seguem o perfil, como em `inicio` (rodada 2 da PR #579); a faixa do ciclo e' a mesma para todo perfil."""
    publico = "diretoria" if usuario.get("perfil") == "diretoria" else "operacao"
    return pagina_inicio.painel(conn, publico=publico)


@router.get("/api/medicoes/andamento")
def andamento(contrato_id: int | None = Query(None, ge=1, le=MAX_INT64), estado: str | None = Query(None, max_length=30),
              _=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    return medicoes.em_andamento(conn, contrato_id, estado)


@router.get("/api/medicoes/resumo")
def resumo(mes: str | None = Query(None, pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$"),
           _=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    """Medicoes (09/10/2026; redesenho 2026-11, #507): contagens, linhas em andamento (passo e com quem) e as obras
    ativas, com `sem_no_mes` para a competencia `mes` (AAAA-MM; padrao, o mes de hoje). #643: o `quadro` da
    competencia (uma linha por obra, um passo por coluna) e as medicoes abertas dos meses `anteriores`."""
    return medicoes.resumo(conn, mes=mes)
