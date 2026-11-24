"""Rotas das telas de Licitacoes (issue #908 e fatia 2 da #906, docs/adr/0018).

Leitura: sessao e `ver_licitacoes`. Decisao (favoritar, tirar a favorita, etapa, descartar, pedir a analise do edital e
marcar as mudancas como vistas): sessao, CSRF e `editar_licitacoes`; antes do corte, 409 (as decisoes ainda sao
espelho do radar). O certame e' enderecado pelo `id` que as linhas trazem.
"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import licitacoes, licitacoes_decisoes
from app.api_auth import conexao
from app.api_medicoes import ID
from app.permissoes import EDITAR_LICITACOES, VER_LICITACOES, exigir, tem

router = APIRouter()


def _com_poder(dados: dict, usuario: dict) -> dict:
    """`pode_decidir`: a tela mostra os botoes so' depois do corte e a quem decide; o servidor confere de novo."""
    return {**dados, "pode_decidir": dados["decisoes"] == "dashboard" and tem(usuario["perfil"], EDITAR_LICITACOES)}


@router.get("/api/licitacoes/triagem")
def triagem(conn: sqlite3.Connection = Depends(conexao),
            usuario: dict = Depends(exigir(VER_LICITACOES, com_csrf=False))):
    return _com_poder(licitacoes.triagem(conn), usuario)


@router.get("/api/licitacoes/favoritas")
def favoritas(conn: sqlite3.Connection = Depends(conexao),
              usuario: dict = Depends(exigir(VER_LICITACOES, com_csrf=False))):
    return _com_poder(licitacoes.favoritas(conn), usuario)


# --- decisoes -------------------------------------------------------------------------------------------------

class EtapaIn(BaseModel):
    etapa: str = Field(max_length=30)                     # licitacoes_decisoes confere a lista, em portugues


class DescarteIn(BaseModel):
    motivo: str = Field(max_length=30)                    # idem


def _decidir(funcao, conn, usuario: dict, certame_id: int, *args):
    try:
        return funcao(conn, usuario["id"], certame_id, *args)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except licitacoes_decisoes.Recusa as e:
        raise HTTPException(409, str(e)) from None
    except sqlite3.IntegrityError:
        # dois pedidos ao mesmo tempo: o indice de uma favorita (ou um descarte) ativa por chave recusa o segundo
        raise HTTPException(409, licitacoes_decisoes.JA_DECIDIDA) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.post("/api/licitacoes/{certame_id}/favorita")
def favoritar(certame_id: ID, usuario: dict = Depends(exigir(EDITAR_LICITACOES)),
              conn: sqlite3.Connection = Depends(conexao)):
    _decidir(licitacoes_decisoes.favoritar, conn, usuario, certame_id)
    return {"id": certame_id}


@router.post("/api/licitacoes/{certame_id}/favorita/remover")
def remover_favorita(certame_id: ID, usuario: dict = Depends(exigir(EDITAR_LICITACOES)),
                     conn: sqlite3.Connection = Depends(conexao)):
    _decidir(licitacoes_decisoes.remover_favorita, conn, usuario, certame_id)
    return {"id": certame_id}


@router.post("/api/licitacoes/{certame_id}/etapa")
def mudar_etapa(certame_id: ID, dados: EtapaIn, usuario: dict = Depends(exigir(EDITAR_LICITACOES)),
                conn: sqlite3.Connection = Depends(conexao)):
    _decidir(licitacoes_decisoes.mudar_etapa, conn, usuario, certame_id, dados.etapa)
    return {"id": certame_id}


@router.post("/api/licitacoes/{certame_id}/descarte")
def descartar(certame_id: ID, dados: DescarteIn, usuario: dict = Depends(exigir(EDITAR_LICITACOES)),
              conn: sqlite3.Connection = Depends(conexao)):
    _decidir(licitacoes_decisoes.descartar, conn, usuario, certame_id, dados.motivo)
    return {"id": certame_id}


@router.post("/api/licitacoes/{certame_id}/descarte/desfazer")
def desfazer_descarte(certame_id: ID, usuario: dict = Depends(exigir(EDITAR_LICITACOES)),
                      conn: sqlite3.Connection = Depends(conexao)):
    _decidir(licitacoes_decisoes.desfazer_descarte, conn, usuario, certame_id)
    return {"id": certame_id}


@router.post("/api/licitacoes/{certame_id}/analise")
def analisar(certame_id: ID, usuario: dict = Depends(exigir(EDITAR_LICITACOES)),
             conn: sqlite3.Connection = Depends(conexao)):
    return {"id": certame_id, **_decidir(licitacoes_decisoes.analisar, conn, usuario, certame_id)}


@router.post("/api/licitacoes/{certame_id}/mudancas-vistas")
def marcar_mudancas_vistas(certame_id: ID, usuario: dict = Depends(exigir(EDITAR_LICITACOES)),
                           conn: sqlite3.Connection = Depends(conexao)):
    _decidir(licitacoes_decisoes.marcar_mudancas_vistas, conn, usuario, certame_id)
    return {"id": certame_id}
