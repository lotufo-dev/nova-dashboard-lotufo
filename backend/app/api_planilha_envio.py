"""Envio da planilha/carta ao protocolo do orgao (issue #282; spec 2026-10-20 §2.1, passo 2). Tudo o que recusa
vem do servico (`planilha_envio`); aqui so' validacao de entrada e HTTP, no molde de `api_pleitos`."""
import sqlite3

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app import arquivos, envio_reserva, graph, pdfs, planilha_envio
from app.api_auth import conexao
from app.api_espelhos import _emails
from app.api_medicoes import ID, _medicao_existe
from app.permissoes import exigir

router = APIRouter()
TETO_PLANILHA = 25 * 1024 * 1024


class PreviaIn(BaseModel):
    numero_oficio: str = Field(min_length=1, max_length=40)


class AnexoConferido(BaseModel):
    nome: str = Field(max_length=300)
    tamanho: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")      # o conteudo conferido (gate Sol S5), como a previa devolve


class EnvioIn(BaseModel):
    numero_oficio: str = Field(min_length=1, max_length=40)
    para: list[str] = Field(max_length=30)
    copia: list[str] = Field(max_length=30)
    cco: list[str] = Field(default_factory=list, max_length=30)
    assunto: str = Field(min_length=1, max_length=300)
    corpo: str = Field(max_length=20000)
    justificativa: str | None = Field(default=None, max_length=2000)
    # os anexos que a pessoa conferiu na previa (nome, tamanho e sha256): obrigatorio, como no envio da nota; mudou depois
    # dela, o envio recusa
    anexos_previa: list[AnexoConferido] = Field(max_length=60)


@router.post("/api/medicoes/{mid}/envio-planilha/previa")
def previa(mid: ID, dados: PreviaIn, usuario: dict = Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    _medicao_existe(conn, mid)
    try:
        return planilha_envio.previa(conn, mid, dados.numero_oficio, remetente=usuario.get("email"))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.post("/api/medicoes/{mid}/envio-planilha")
def enviar(mid: ID, dados: EnvioIn, usuario: dict = Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    _medicao_existe(conn, mid)
    try:
        eid = planilha_envio.enviar(
            conn, {"id": usuario["id"], "email": usuario["email"]}, mid, dados.numero_oficio, _emails(dados.para),
            _emails(dados.copia), dados.assunto.strip(), dados.corpo, [a.model_dump() for a in dados.anexos_previa],
            dados.justificativa, cco=_emails(dados.cco))
    except envio_reserva.EnvioEmAndamento as e:
        conn.rollback()
        raise HTTPException(409, detail=e.detalhe()) from None
    except planilha_envio.AnexosMudaram as e:      # a tela reabre a previa pelo `codigo`, como no envio da nota
        conn.rollback()
        raise HTTPException(422, detail={"codigo": e.codigo, "mensagem": str(e)}) from None
    except (ValueError, graph.ErroGraph) as e:
        conn.rollback()
        raise HTTPException(422, str(e)) from None
    return {"envio_id": eid, **planilha_envio.situacao(conn, mid)}


@router.post("/api/medicoes/{mid}/envio-planilha/pecas")
def peca(mid: ID, tipo: str = Form(..., max_length=40), arquivo: UploadFile = File(...),
         usuario: dict = Depends(exigir("editar_cadastros")), conn: sqlite3.Connection = Depends(conexao)):
    _medicao_existe(conn, mid)
    nome = (arquivo.filename or "peca")[-200:]
    if nome.lower().endswith(".xlsx"):
        dados, ext = b"".join(arquivos.blocos_validados(arquivo, teto_bytes=TETO_PLANILHA, tipo="xlsx")), "xlsx"
    else:
        dados, ext = b"".join(arquivos.blocos_validados(arquivo, teto_bytes=pdfs.TETO_BYTES_PACOTE)), "pdf"
    try:
        planilha_envio.adicionar_peca(conn, usuario["id"], mid, tipo, nome, dados, ext)
    except envio_reserva.EnvioEmAndamento as e:     # e-mail saindo (ou preso): as pecas nao mudam
        raise HTTPException(409, detail=e.detalhe()) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return planilha_envio.situacao(conn, mid)


@router.post("/api/medicoes/{mid}/envio-planilha/pecas/{peca_id}/remover")
def remover_peca(mid: ID, peca_id: ID, usuario: dict = Depends(exigir("editar_cadastros")),
                 conn: sqlite3.Connection = Depends(conexao)):
    _medicao_existe(conn, mid)
    try:
        planilha_envio.remover_peca(conn, usuario["id"], mid, peca_id)
    except envio_reserva.EnvioEmAndamento as e:
        raise HTTPException(409, detail=e.detalhe()) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return planilha_envio.situacao(conn, mid)
