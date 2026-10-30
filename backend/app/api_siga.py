"""Rotas do monitor do SIGA (issue #327).

Duas rotas de SERVICO, para o robo: `POST /api/siga/leituras` e `GET /api/siga/processos`. Nao usam sessao nem
CSRF; exigem `Authorization: Bearer <token>`, com o token lido do arquivo apontado por `DASH_SIGA_TOKEN_ARQUIVO`
(fora do repositorio; lido a cada pedido, entao trocar o token nao pede reinicio). Sem a variavel, 503.
Uma rota para as telas: `GET /api/siga`, com sessao e `ver_paineis`. E uma de escrita, `POST /api/siga/processos-avulsos`
(issue #339): link colado na tela SIGA, com sessao, CSRF e `editar_cadastros`.
Issue #342: `POST /api/siga/atualizar` (sessao, CSRF e `ver_paineis`) grava o pedido de leitura e manda o Windows
iniciar o robo; o robo conversa pelas rotas de servico `POST /api/siga/rodadas` ("comecei"),
`POST /api/siga/rodadas/{id}/fim` ("terminei") e `POST /api/siga/rodadas/{id}/falha` ("cai"), com o mesmo token.
"""
import hmac
import logging
import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import AwareDatetime, BaseModel, Field

from app import siga
from app.api_auth import conexao
from app.permissoes import exigir

router = APIRouter()
log = logging.getLogger("app.siga")

MAX_INT64 = 9223372036854775807
NAO_CONFIGURADO = "Monitor do SIGA não configurado"
TOKEN_INVALIDO = "Token do monitor do SIGA inválido ou ausente"
TAREFA_NAO_CONFIGURADA = "Atualizar pelo SIGA não está disponível neste servidor"


def _token_esperado() -> bytes:
    caminho = os.environ.get("DASH_SIGA_TOKEN_ARQUIVO")
    if not caminho:
        raise HTTPException(503, NAO_CONFIGURADO)
    # utf-8-sig: o Set-Content -Encoding UTF8 do PowerShell 5.1 grava BOM, que viraria parte do token (401 eterno).
    # UTF-16 (o `>` do PowerShell 5.1) nao decodifica: 503 com log, nunca 500.
    try:
        token = Path(caminho).read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError):
        log.exception("arquivo do token do SIGA ilegivel")
        raise HTTPException(503, NAO_CONFIGURADO) from None
    if not token:
        log.error("arquivo do token do SIGA vazio")
        raise HTTPException(503, NAO_CONFIGURADO)
    return token.encode("utf-8")


def exigir_robo(authorization: str | None = Header(default=None)) -> None:
    esperado = _token_esperado()
    tipo, _, valor = (authorization or "").partition(" ")
    # compare_digest em bytes: tempo constante, e o cabecalho pode trazer nao-ASCII
    if tipo.lower() != "bearer" or not hmac.compare_digest(valor.strip().encode("utf-8"), esperado):
        raise HTTPException(401, TOKEN_INVALIDO, headers={"WWW-Authenticate": "Bearer"})


class MovimentacaoIn(BaseModel):
    data: str = Field(max_length=30)                      # DD/MM/AAAA HH:MM:SS (siga._data_iso confere)
    evento: str | None = Field(default=None, max_length=500)
    cad_lotacao: str | None = Field(default=None, max_length=300)
    cad_pessoa: str | None = Field(default=None, max_length=300)
    at_lotacao: str | None = Field(default=None, max_length=300)
    at_pessoa: str | None = Field(default=None, max_length=300)


class ProcessoIn(BaseModel):
    codigo: str | None = Field(default=None, max_length=100, pattern=r"^\s*[A-Za-z0-9]*\s*$")
    numero: str | None = Field(default=None, max_length=100)
    nome: str | None = Field(default=None, max_length=500)
    situacao: str | None = Field(default=None, max_length=2000)
    movimentacoes: list[MovimentacaoIn] = Field(default_factory=list, max_length=2000)


class LeituraIn(BaseModel):
    lido_em: AwareDatetime
    processos: list[ProcessoIn] = Field(max_length=1000)


@router.post("/api/siga/leituras", dependencies=[Depends(exigir_robo)], include_in_schema=False)
def receber_leituras(dados: LeituraIn, conn: sqlite3.Connection = Depends(conexao)):
    try:
        return siga.gravar_leitura(conn, dados.lido_em, [p.model_dump() for p in dados.processos])
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/api/siga/processos", dependencies=[Depends(exigir_robo)], include_in_schema=False)
def processos_do_robo(conn: sqlite3.Connection = Depends(conexao)):
    return siga.processos_para_o_robo(conn)


@router.get("/api/siga")
def painel(conn: sqlite3.Connection = Depends(conexao), _usuario: dict = Depends(exigir("ver_paineis",
                                                                                         com_csrf=False))):
    return siga.painel(conn)


class AvulsoIn(BaseModel):
    link: str = Field(max_length=500)                 # link inteiro ou so' o codigo (siga.extrair_codigo)
    nome: str = Field(max_length=200)
    numero: str | None = Field(default=None, max_length=100)
    contrato_id: int | None = Field(default=None, ge=1, le=MAX_INT64)


@router.post("/api/siga/processos-avulsos")
def acompanhar_avulso(dados: AvulsoIn, usuario: dict = Depends(exigir("editar_cadastros")),
                      conn: sqlite3.Connection = Depends(conexao)):
    try:
        pid = siga.acompanhar_avulso(conn, usuario["id"], dados.link, dados.numero, dados.nome, dados.contrato_id)
    except siga.JaAcompanhado as e:
        raise HTTPException(409, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"id": pid}


# --- pedido de leitura pela tela e rodadas do robo (issue #342) --------------------------------------------

class AtualizarIn(BaseModel):
    processo_id: int | None = Field(default=None, ge=1, le=MAX_INT64)     # sem processo = todos


@router.post("/api/siga/atualizar")
def atualizar(dados: AtualizarIn, usuario: dict = Depends(exigir("ver_paineis")),
              conn: sqlite3.Connection = Depends(conexao)):
    """"Atualizar processo" e "Atualizar todos": pedir uma leitura nao muda dado nenhum, entao basta ver a tela."""
    tarefa = siga.tarefa_do_robo()
    if not tarefa:
        raise HTTPException(503, TAREFA_NAO_CONFIGURADA)
    try:
        return siga.pedir_leitura(conn, usuario["id"], dados.processo_id, tarefa)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


class RodadaIn(BaseModel):
    so_pedidos: bool = False                               # o robo fora do horario: sem rodada automatica (#347)


@router.post("/api/siga/rodadas", dependencies=[Depends(exigir_robo)], include_in_schema=False)
def iniciar_rodada(dados: RodadaIn | None = None, conn: sqlite3.Connection = Depends(conexao)):
    return siga.iniciar_rodada(conn, so_pedidos=bool(dados and dados.so_pedidos))


class NaoLidoIn(BaseModel):
    codigo: str | None = Field(default=None, max_length=100)
    numero: str | None = Field(default=None, max_length=100)
    motivo: str = Field(max_length=2000)                  # gravado cortado em 300 caracteres


class FimIn(BaseModel):
    nao_lidos: list[NaoLidoIn] = Field(default_factory=list, max_length=1000)


class FalhaIn(BaseModel):
    motivo: str = Field(max_length=2000)                  # gravado cortado em 300 caracteres


def _na_rodada(funcao, conn, rodada_id: int, *args) -> dict:
    if not 1 <= rodada_id <= MAX_INT64:
        raise HTTPException(404, siga.RODADA_INEXISTENTE)
    try:
        funcao(conn, rodada_id, *args)
    except siga.RodadaTerminada as e:
        raise HTTPException(409, str(e)) from None
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"rodada_id": rodada_id}


@router.post("/api/siga/rodadas/{rodada_id}/fim", dependencies=[Depends(exigir_robo)], include_in_schema=False)
def terminar_rodada(rodada_id: int, dados: FimIn, conn: sqlite3.Connection = Depends(conexao)):
    return _na_rodada(siga.terminar_rodada, conn, rodada_id, [n.model_dump() for n in dados.nao_lidos])


@router.post("/api/siga/rodadas/{rodada_id}/falha", dependencies=[Depends(exigir_robo)], include_in_schema=False)
def falhar_rodada(rodada_id: int, dados: FalhaIn, conn: sqlite3.Connection = Depends(conexao)):
    return _na_rodada(siga.falhar_rodada, conn, rodada_id, dados.motivo)
