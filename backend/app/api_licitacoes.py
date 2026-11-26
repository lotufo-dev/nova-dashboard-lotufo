"""Rotas das telas de Licitacoes (issue #908 e fatia 2 da #906, docs/adr/0018).

Leitura: sessao e `ver_licitacoes`. Decisao (favoritar, tirar a favorita, etapa, descartar, pedir a analise do edital e
marcar as mudancas como vistas): sessao, CSRF e `editar_licitacoes`; antes do corte, 409 (as decisoes ainda sao
espelho do radar). O certame e' enderecado pelo `id` que as linhas trazem.
"""
import datetime
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
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
    # os motivos do descarte vao com a fila em que se descarta: a tela nao tem a lista
    return {**_com_poder(licitacoes.triagem(conn), usuario),
            "motivos_descarte": licitacoes_decisoes.motivos_de_descarte()}


@router.get("/api/licitacoes/favoritas")
def favoritas(conn: sqlite3.Connection = Depends(conexao),
              usuario: dict = Depends(exigir(VER_LICITACOES, com_csrf=False))):
    return _com_poder(licitacoes.favoritas(conn), usuario)


@router.get("/api/licitacoes/calendario")
def calendario(mes: str | None = Query(None, pattern=r"^2[0-9]{3}-(0[1-9]|1[0-2])$"),
               conn: sqlite3.Connection = Depends(conexao),
               usuario: dict = Depends(exigir(VER_LICITACOES, com_csrf=False))):
    """O calendario das favoritas: o mes `mes` (AAAA-MM; padrao, o de hoje) com cada prazo no dia dele."""
    return _com_poder(licitacoes.calendario(conn, mes), usuario)


# os filtros que vem da busca do endereco: texto curto (o valor desconhecido nao acha nada) e as datas da sessao
_Filtro = Annotated[str, Query(max_length=120)]


@router.get("/api/licitacoes/todas")
def todas(vista: Literal["novas", "grande-vulto"] = "novas", ordem: Literal["padrao", "prazo", "publicacao", "valor"] = "padrao",
          q: Annotated[str, Query(max_length=200)] = "", tipo: _Filtro = "", modalidade: _Filtro = "", orgao: _Filtro = "",
          esfera: _Filtro = "", valor: _Filtro = "", km: _Filtro = "", situacao: _Filtro = "", decisao: _Filtro = "",
          portal: _Filtro = "", sessao_de: datetime.date | None = None, sessao_ate: datetime.date | None = None,
          conn: sqlite3.Connection = Depends(conexao), usuario: dict = Depends(exigir(VER_LICITACOES, com_csrf=False))):
    """Todas e Grande vulto (fatia 3 da #906): a lista inteira da vista, com a busca, os filtros e a ordem."""
    filtros = {"q": q, "tipo": tipo, "modalidade": modalidade, "orgao": orgao, "esfera": esfera, "valor": valor, "km": km,
               "situacao": situacao, "decisao": decisao, "portal": portal, "sessao_de": sessao_de, "sessao_ate": sessao_ate}
    return _com_poder(licitacoes.todas(conn, vista, filtros, ordem), usuario)


@router.get("/api/licitacoes/fontes")
def fontes(conn: sqlite3.Connection = Depends(conexao), usuario: dict = Depends(exigir(VER_LICITACOES, com_csrf=False))):
    """Fontes (fatia 4 da #906): a situacao de cada fonte, os alertas do dia e a conferencia."""
    return _com_poder(licitacoes.fontes(conn), usuario)


@router.get("/api/licitacoes/resultados")
def resultados(conn: sqlite3.Connection = Depends(conexao), _=Depends(exigir(VER_LICITACOES, com_csrf=False))):
    """Resultados (fatia 4 da #906): o ultimo quadro que o radar mandou."""
    return licitacoes.resultados(conn)


@router.get("/api/licitacoes/resumo")
def resumo(conn: sqlite3.Connection = Depends(conexao), _=Depends(exigir(VER_LICITACOES, com_csrf=False))):
    """A linha das licitacoes na Inicio: os numeros da Triagem, pela mesma funcao. Rota propria: `/api/inicio` e'
    pedida por paginas que so' querem os avisos, e por quem nao ve as licitacoes."""
    return licitacoes.resumo(conn)


# --- decisoes -------------------------------------------------------------------------------------------------

class EtapaIn(BaseModel):
    etapa: str = Field(max_length=30)                     # licitacoes_decisoes confere a lista, em portugues


class DescarteIn(BaseModel):
    motivo: str = Field(max_length=30)                    # idem


class VistasIn(BaseModel):
    # as chaves das mudancas que a tela mostrou (`chave` de cada mudanca nas rotas de leitura)
    chaves: list[Annotated[str, Field(min_length=1, max_length=32)]] = Field(min_length=1, max_length=200)


def _decidir(funcao, conn, usuario: dict, certame_id: int, *args):
    try:
        return funcao(conn, usuario["id"], certame_id, *args)
    except licitacoes_decisoes.NaoEncontrada as e:
        raise HTTPException(404, str(e)) from None
    except licitacoes_decisoes.Recusa as e:
        raise HTTPException(409, str(e)) from None
    except sqlite3.IntegrityError:
        # dois pedidos ao mesmo tempo: o indice de uma favorita (ou um descarte) ativa por chave recusa o segundo
        raise HTTPException(409, licitacoes_decisoes.JA_DECIDIDA) from None
    except licitacoes_decisoes.ForaDaLista as e:
        raise HTTPException(422, str(e)) from None
    # qualquer outra excecao e' defeito, e sobe: nao vira 404 nem 422


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


class ConferenciaIn(BaseModel):
    resposta: str = Field(max_length=10)                  # licitacoes_decisoes confere a lista


@router.post("/api/licitacoes/pares/{par_id}/conferencia")
def conferir(par_id: ID, dados: ConferenciaIn, usuario: dict = Depends(exigir(EDITAR_LICITACOES)),
             conn: sqlite3.Connection = Depends(conexao)):
    _decidir(licitacoes_decisoes.conferir, conn, usuario, par_id, dados.resposta)
    return {"id": par_id}


@router.post("/api/licitacoes/pares/{par_id}/conferencia/desfazer")
def desfazer_conferencia(par_id: ID, usuario: dict = Depends(exigir(EDITAR_LICITACOES)),
                         conn: sqlite3.Connection = Depends(conexao)):
    _decidir(licitacoes_decisoes.desfazer_conferencia, conn, usuario, par_id)
    return {"id": par_id}


@router.post("/api/licitacoes/{certame_id}/mudancas-vistas")
def marcar_mudancas_vistas(certame_id: ID, dados: VistasIn, usuario: dict = Depends(exigir(EDITAR_LICITACOES)),
                           conn: sqlite3.Connection = Depends(conexao)):
    _decidir(licitacoes_decisoes.marcar_mudancas_vistas, conn, usuario, certame_id, dados.chaves)
    return {"id": certame_id}
