"""Protocolo de medicao (bloco 5; spec 2026-09-21 §3 passos 4 a 7): criar, pecas, carta, pacote, assinado,
previa e envio. Tudo o que recusa vem do servico (`protocolo`); aqui so' validacao de entrada e HTTP."""
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import arquivos, envio_reserva, graph, pdfs, protocolo
from app.api_auth import conexao
from app.api_espelhos import _emails
from app.api_medicoes import ID, MAX_INT64, _contrato_existe
from app.permissoes import exigir

router = APIRouter()
TipoPeca = Literal["boletim", "planilha", "diario", "fotos", "cronograma", "art", "ensaios", "memorial", "diagrama",
                   "pluviometria", "croqui", "outro", "anexo"]
TETO_PLANILHA = 25 * 1024 * 1024


class CriarIn(BaseModel):
    etapa: Literal["unico", "medicao", "nota"]
    medicao_ids: list[int] = Field(min_length=1, max_length=10)
    numero_oficio: str | None = Field(default=None, max_length=40)


class MontarIn(BaseModel):
    corpo: str | None = Field(default=None, max_length=20000)


class PreviaIn(BaseModel):
    protocolo_ids: list[int] = Field(min_length=1, max_length=10)


class AnexoVistoIn(BaseModel):
    nome: str = Field(max_length=500)
    tamanho: int


# issue #213: a lista do aviso "ATENÇÃO" confirmada pela pessoa (cada item e' uma linha do que falta)
Confirmadas = Annotated[list[Annotated[str, Field(max_length=2000)]] | None, Field(default=None, max_length=200)]


class EnvioIn(PreviaIn):
    para: list[str] = Field(max_length=30)
    copia: list[str] = Field(max_length=30)
    cco: list[str] = Field(default_factory=list, max_length=30)
    assunto: str = Field(min_length=1, max_length=300)
    corpo: str = Field(max_length=20000)
    justificativa: str | None = Field(default=None, max_length=2000)
    # issue #10: os anexos que a pessoa viu na previa; se o servidor montar outros, o envio e' recusado
    anexos: list[AnexoVistoIn] | None = Field(default=None, max_length=200)
    # issue #213: o que falta, como a pessoa viu e confirmou no aviso "ATENÇÃO"
    confirmadas: Confirmadas = None


class DescartarIn(BaseModel):
    motivo: str = Field(min_length=1, max_length=500)


def _existe(conn, pid: int) -> None:
    if not 1 <= pid <= MAX_INT64 or conn.execute("SELECT 1 FROM protocolos WHERE id=?", (pid,)).fetchone() is None:
        raise HTTPException(404, "Protocolo não encontrado")


def _detalhe(conn, pid: int) -> dict:
    d = protocolo.detalhe(conn, pid)
    if d["tem_carta"] and not d["corpo_carta"] and d["situacao"] != "enviado":
        try:
            d["corpo_padrao"] = protocolo.corpo_padrao(conn, pid)
        except ValueError as e:
            d["corpo_padrao"], d["erro_carta"] = None, str(e)
    return d


def _arquivo(rel: str | None, nome: str) -> FileResponse:
    if not rel:
        raise HTTPException(404, "Arquivo não encontrado")
    try:
        caminho = arquivos.caminho_seguro(rel)
    except ValueError:
        raise HTTPException(404, "Arquivo não encontrado") from None
    if not caminho.is_file():
        raise HTTPException(404, "Arquivo não encontrado")
    return FileResponse(caminho, media_type=arquivos.MIME, filename=nome,
                        headers={"X-Content-Type-Options": "nosniff"})


@router.get("/api/contratos/{contrato_id}/protocolos")
def listar(contrato_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
           conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    try:
        d = protocolo.listar(conn, contrato_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    d["protocolos"] = [_detalhe(conn, p["id"]) for p in d["protocolos"]]     # com o corpo padrao da carta
    return d


@router.post("/api/contratos/{contrato_id}/protocolos", status_code=201)
def criar(contrato_id: ID, dados: CriarIn, usuario: dict = Depends(exigir("editar_cadastros")),
          conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    try:
        pid = protocolo.criar(conn, usuario["id"], contrato_id, dados.etapa, dados.medicao_ids, dados.numero_oficio)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _detalhe(conn, pid)


@router.get("/api/protocolos/{pid}")
def detalhe(pid: ID, _=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    return _detalhe(conn, pid)


@router.post("/api/protocolos/{pid}/pecas")
def peca(pid: ID, tipo: TipoPeca = Form(...), arquivo: UploadFile = File(...),
         usuario: dict = Depends(exigir("editar_cadastros")), conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    nome = (arquivo.filename or "peca")[-200:]
    if nome.lower().endswith(".xlsx"):
        dados, ext = b"".join(arquivos.blocos_validados(arquivo, teto_bytes=TETO_PLANILHA, tipo="xlsx")), "xlsx"
    elif nome.lower().endswith(".zip"):     # so' documento complementar (protocolo.adicionar_peca confere)
        dados, ext = b"".join(arquivos.blocos_validados(arquivo, teto_bytes=pdfs.TETO_BYTES_PACOTE, tipo="zip")), "zip"
    else:
        dados, ext = b"".join(arquivos.blocos_validados(arquivo, teto_bytes=pdfs.TETO_BYTES_PACOTE)), "pdf"
    try:
        protocolo.adicionar_peca(conn, usuario["id"], pid, tipo, nome, dados, ext)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _detalhe(conn, pid)


class LinkIn(BaseModel):
    nome: str = Field(max_length=200)
    url: str = Field(max_length=2100)


@router.post("/api/protocolos/{pid}/links")
def link(pid: ID, dados: LinkIn, usuario: dict = Depends(exigir("editar_cadastros")),
         conn: sqlite3.Connection = Depends(conexao)):
    """Arquivo grande por link do OneDrive (vai no corpo do e-mail, fora do limite dos anexos)."""
    _existe(conn, pid)
    try:
        protocolo.adicionar_link(conn, usuario["id"], pid, dados.nome, dados.url)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _detalhe(conn, pid)


@router.post("/api/protocolos/{pid}/links/{link_id}/remover")
def remover_link(pid: ID, link_id: ID, usuario: dict = Depends(exigir("editar_cadastros")),
                 conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    try:
        protocolo.remover_link(conn, usuario["id"], pid, link_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _detalhe(conn, pid)


@router.post("/api/protocolos/{pid}/pecas/{peca_id}/remover")
def remover_peca(pid: ID, peca_id: ID, usuario: dict = Depends(exigir("editar_cadastros")),
                 conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    try:
        protocolo.remover_peca(conn, usuario["id"], pid, peca_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _detalhe(conn, pid)


@router.post("/api/protocolos/{pid}/montar")
def montar(pid: ID, dados: MontarIn, usuario: dict = Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    try:
        protocolo.montar(conn, usuario["id"], pid, dados.corpo)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _detalhe(conn, pid)


@router.get("/api/protocolos/{pid}/pacote")
def pacote(pid: ID, _=Depends(exigir("ver_paineis", com_csrf=False)), conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    d = protocolo.detalhe(conn, pid)
    return _arquivo(d["montado_arquivo"], d["nome_arquivo"] or "pacote.pdf")


@router.get("/api/protocolos/{pid}/assinado")
def baixar_assinado(pid: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
                    conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    d = protocolo.detalhe(conn, pid)
    return _arquivo(d["assinado_arquivo"], d["nome_arquivo"] or "assinado.pdf")


@router.post("/api/protocolos/{pid}/assinado")
def assinado(pid: ID, arquivo: UploadFile = File(...), usuario: dict = Depends(exigir("editar_cadastros")),
             conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    pdf = b"".join(arquivos.blocos_validados(arquivo, teto_bytes=pdfs.TETO_BYTES_PACOTE))
    try:
        protocolo.receber_assinado(conn, usuario["id"], pid, pdf)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _detalhe(conn, pid)


@router.post("/api/protocolos/envio/previa")
def previa(dados: PreviaIn, usuario: dict = Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    for pid in dados.protocolo_ids:
        _existe(conn, pid)
    try:
        return protocolo.previa_envio(conn, dados.protocolo_ids, remetente=usuario.get("email"))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.post("/api/protocolos/envio")
def enviar(dados: EnvioIn, usuario: dict = Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    for pid in dados.protocolo_ids:
        _existe(conn, pid)
    try:
        eid = protocolo.enviar(conn, {"id": usuario["id"], "email": usuario["email"]}, dados.protocolo_ids,
                               _emails(dados.para), _emails(dados.copia), dados.assunto.strip(), dados.corpo,
                               dados.justificativa, cco=_emails(dados.cco),
                               anexos_previa=None if dados.anexos is None else [a.model_dump() for a in dados.anexos],
                               confirmadas=dados.confirmadas)
    except envio_reserva.EnvioEmAndamento as e:
        conn.rollback()
        raise HTTPException(409, detail=e.detalhe()) from None
    except protocolo.ConfirmarPendencias as e:
        conn.rollback()
        raise HTTPException(422, detail=e.detalhe()) from None
    except (ValueError, graph.ErroGraph) as e:
        conn.rollback()
        raise HTTPException(422, str(e)) from None
    return {"envio_id": eid}


@router.get("/api/protocolos/{pid}/comprovante")
def baixar_comprovante(pid: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
                       conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    d = protocolo.detalhe(conn, pid)
    return _arquivo(d["comprovante_arquivo"], "comprovante-do-protocolo.pdf")


@router.post("/api/protocolos/{pid}/numero-orgao")
def numero_orgao(pid: ID, numero: str = Form("", max_length=100), link_siga: str = Form("", max_length=500),
                 comprovante: UploadFile | None = File(None),
                 usuario: dict = Depends(exigir("editar_cadastros")), conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    dados = b"".join(arquivos.blocos_validados(comprovante)) if comprovante is not None else None
    try:
        protocolo.registrar_numero_orgao(conn, usuario["id"], pid, numero, dados, link_siga)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return _detalhe(conn, pid)


@router.post("/api/protocolos/{pid}/descartar")
def descartar(pid: ID, dados: DescartarIn, usuario: dict = Depends(exigir("editar_cadastros")),
              conn: sqlite3.Connection = Depends(conexao)):
    _existe(conn, pid)
    try:
        protocolo.descartar(conn, usuario["id"], pid, dados.motivo)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}
