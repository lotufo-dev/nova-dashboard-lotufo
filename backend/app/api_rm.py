"""Rotas da integracao RM (fase 5): status/frescor, disparo manual e reconciliacao.

Leitura de status e' `ver_paineis` (o carimbo de frescor aparece em toda tela com dado
importado, spec §6); disparar e reconciliar sao `administrar`.
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from app import instalacao, rm, sincronizacao_rm
from app.api_auth import conexao
from app.permissoes import exigir

router = APIRouter(prefix="/api/rm")
# id acima de int64 e' recusado na entrada (422): o sqlite3 levantaria OverflowError (500)
MAX_INT64 = 9223372036854775807


@router.get("/status")
def status(usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
           conn: sqlite3.Connection = Depends(conexao)):
    ultimas = sincronizacao_rm.rodadas(conn, 10)
    # `configurado` sai do ambiente, nao so' do ESTADO da thread: nos testes e no CLI a
    # thread nao existe e o ambiente e' a verdade.
    configurado = rm.de_ambiente() is not None
    return {"configurado": configurado, **{k: v for k, v in sincronizacao_rm.ESTADO.items() if k != "configurado"},
            "rodadas": ultimas, "custo_aviso": sincronizacao_rm.aviso_do_custo(conn)}


@router.post("/sincronizar")
def sincronizar(usuario: dict = Depends(exigir("administrar")),
                conn: sqlite3.Connection = Depends(conexao)):
    if not instalacao.ligada():          # issue #417: a copia nao fala com o RM
        raise HTTPException(422, instalacao.MSG_RM)
    cliente = rm.de_ambiente()
    if cliente is None:
        raise HTTPException(422, "RM não configurado neste servidor (DASH_RM_URL / DASH_RM_USUARIO / "
                                 "DASH_RM_SENHA_ARQUIVO) — ver docs/runbook.md")
    try:
        return sincronizacao_rm.sincronizar(conn, cliente, "manual")
    except sincronizacao_rm.RodadaEmAndamento as e:
        raise HTTPException(409, str(e))


@router.get("/reconciliacao")
def reconciliacao(nfs_apos: int | None = Query(None, ge=1, le=MAX_INT64),
                  desfeitas_apos: int | None = Query(None, ge=1, le=MAX_INT64),
                  usuario: dict = Depends(exigir("administrar", com_csrf=False)),
                  conn: sqlite3.Connection = Depends(conexao)):
    # #22: as NFs sem medicao e as alocacoes desfeitas vem em paginas, depois do id da ultima linha que a tela ja'
    # tem; `totais` traz o numero exato e `ha_mais` diz se ha' mais
    try:
        return sincronizacao_rm.reconciliacao(conn, nfs_apos, desfeitas_apos)
    except ValueError as e:
        raise HTTPException(422, str(e))
