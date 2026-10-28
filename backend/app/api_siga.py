"""Rotas do monitor do SIGA (issue #327).

Duas rotas de SERVICO, para o robo: `POST /api/siga/leituras` e `GET /api/siga/processos`. Nao usam sessao nem
CSRF; exigem `Authorization: Bearer <token>`, com o token lido do arquivo apontado por `DASH_SIGA_TOKEN_ARQUIVO`
(fora do repositorio; lido a cada pedido, entao trocar o token nao pede reinicio). Sem a variavel, 503.
Uma rota para as telas: `GET /api/siga`, com sessao e `ver_paineis`.
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

NAO_CONFIGURADO = "Monitor do SIGA não configurado"
TOKEN_INVALIDO = "Token do monitor do SIGA inválido ou ausente"


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
