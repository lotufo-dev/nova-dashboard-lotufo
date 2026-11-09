"""Envio dos documentos assinados ao orgao (issue #627). Tudo o que recusa vem do servico (`assinados_envio`); aqui
so' validacao de entrada e HTTP, no molde de `api_planilha_envio`. Os PDFs chegam por multipart a cada chamada."""
import datetime
import sqlite3

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from app import arquivos, assinados_envio, envio_reserva, graph, medicoes, pdfs
from app.api_auth import conexao
from app.api_espelhos import _emails
from app.api_medicoes import ID, _medicao_existe
from app.api_planilha_envio import AnexoConferido
from app.permissoes import exigir

router = APIRouter()


class EnvioIn(BaseModel):
    para: list[str] = Field(max_length=30)
    copia: list[str] = Field(max_length=30)
    cco: list[str] = Field(default_factory=list, max_length=30)
    assunto: str = Field(min_length=1, max_length=300)
    corpo: str = Field(max_length=20000)
    motivo: str | None = Field(default=None, max_length=1000)
    assinado_em: datetime.date | None = None
    anexos_previa: list[AnexoConferido] = Field(max_length=10)


def _ler(arquivo: UploadFile | None) -> tuple[str, bytes] | None:
    """O PDF arrastado, com as guardas do upload (tipo, %PDF- e o teto do pacote, 413). O limite do orgao vem depois,
    no servico, com a mensagem dele."""
    if arquivo is None or not arquivo.filename:
        return None
    return arquivo.filename, b"".join(arquivos.blocos_validados(arquivo, teto_bytes=pdfs.TETO_BYTES_PACOTE))


def _docs(conn, mid: int, arquivo, arquivo_reajuste, justificativa) -> dict:
    """Le os tres arquivos, confere as recusas do servico (estado, familia, limite do orgao) ANTES de abrir os PDFs num
    leitor de verdade (415), e devolve o dicionario do servico."""
    docs = {"medicao": _ler(arquivo), "reajuste": _ler(arquivo_reajuste), "justificativa": _ler(justificativa)}
    try:
        assinados_envio.conferir(conn, mid, docs)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    for d in docs.values():
        if d:
            arquivos.conferir_bytes_parseaveis(d[1], pacote=True)
    return docs


@router.post("/api/medicoes/{mid}/assinados/previa")
def previa(mid: ID, arquivo: UploadFile | None = File(None), arquivo_reajuste: UploadFile | None = File(None),
           justificativa: UploadFile | None = File(None), usuario: dict = Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    _medicao_existe(conn, mid)
    docs = _docs(conn, mid, arquivo, arquivo_reajuste, justificativa)
    try:
        return assinados_envio.previa(conn, mid, docs, remetente=usuario.get("email"))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.post("/api/medicoes/{mid}/assinados/enviar")
def enviar(mid: ID, dados: str = Form(..., max_length=100_000), arquivo: UploadFile | None = File(None),
           arquivo_reajuste: UploadFile | None = File(None), justificativa: UploadFile | None = File(None),
           usuario: dict = Depends(exigir("editar_cadastros")), conn: sqlite3.Connection = Depends(conexao)):
    _medicao_existe(conn, mid)
    try:
        d = EnvioIn.model_validate_json(dados)
    except ValidationError:
        raise HTTPException(422, "Dados do e-mail inválidos") from None
    docs = _docs(conn, mid, arquivo, arquivo_reajuste, justificativa)
    try:
        eid = assinados_envio.enviar(
            conn, {"id": usuario["id"], "email": usuario["email"]}, mid, docs, _emails(d.para), _emails(d.copia),
            d.assunto.strip(), d.corpo, [a.model_dump() for a in d.anexos_previa], d.motivo,
            d.assinado_em.isoformat() if d.assinado_em else None, cco=_emails(d.cco))
    except envio_reserva.EnvioEmAndamento as e:
        conn.rollback()
        raise HTTPException(409, detail=e.detalhe()) from None
    except assinados_envio.AnexosMudaram as e:
        conn.rollback()
        raise HTTPException(422, detail={"codigo": e.codigo, "mensagem": str(e)}) from None
    except (ValueError, graph.ErroGraph) as e:
        conn.rollback()
        raise HTTPException(422, str(e)) from None
    return {"envio_id": eid, **assinados_envio.situacao(conn, mid)}


@router.post("/api/medicoes/{mid}/assinados/envio-externo", status_code=201)
def envio_externo(mid: ID, enviado_em: str = Form(..., max_length=10), arquivo: UploadFile | None = File(None),
                  arquivo_reajuste: UploadFile | None = File(None), justificativa: UploadFile | None = File(None),
                  eml: UploadFile | None = File(None), usuario: dict = Depends(exigir("editar_cadastros")),
                  conn: sqlite3.Connection = Depends(conexao)):
    from app import notas_envio
    _medicao_existe(conn, mid)
    docs = _docs(conn, mid, arquivo, arquivo_reajuste, justificativa)
    msg = (eml.filename, eml.file.read(notas_envio.TETO_EML + 1)) if eml is not None and eml.filename else None
    try:
        rid = assinados_envio.registrar_por_fora(conn, usuario["id"], mid, docs, enviado_em, msg)
    except ValueError as e:
        conn.rollback()
        raise HTTPException(422, str(e)) from None
    return {"id": rid, **assinados_envio.situacao(conn, mid)}


@router.post("/api/medicoes/{mid}/assinatura-com-pdf", status_code=201)
def assinatura_com_pdf(mid: ID, data: datetime.date = Form(...), envelope: str | None = Form(None, max_length=200),
                       arquivo: UploadFile = File(...), usuario: dict = Depends(exigir("editar_cadastros")),
                       conn: sqlite3.Connection = Depends(conexao)):
    """"Registrar assinatura" com o PDF assinado (opcional na tela): sem envelope digitado, vale o lido do PDF."""
    _medicao_existe(conn, mid)
    try:
        medicoes.conferir_data_assinatura(conn, mid, data.isoformat())    # recusa antes de gravar o PDF
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    _, pdf = _ler(arquivo) or ("", b"")
    arquivos.conferir_bytes_parseaveis(pdf, pacote=True)
    rel, sha = arquivos.gravar_bytes("assinados", pdf, "pdf")
    try:
        aid = medicoes.registrar_assinatura(conn, usuario["id"], mid, data.isoformat(),
                                            (envelope or "").strip() or medicoes.envelope_do_pdf(pdf), rel, sha)
    except ValueError as e:
        conn.rollback()
        raise HTTPException(422, str(e)) from None
    return {"id": aid}


@router.get("/api/medicoes/{mid}/assinados/{assinatura_id}")
def baixar(mid: ID, assinatura_id: ID, usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
           conn: sqlite3.Connection = Depends(conexao)):
    a = medicoes.arquivo_assinatura(conn, mid, assinatura_id)
    if a is None or not a["arquivo"]:
        raise HTTPException(404, "Arquivo não encontrado")
    try:
        caminho = arquivos.caminho_seguro(a["arquivo"])
    except ValueError:
        raise HTTPException(404, "Arquivo não encontrado") from None
    if not caminho.is_file():
        raise HTTPException(404, "Arquivo não encontrado")
    return FileResponse(caminho, media_type=arquivos.MIME, filename=f"assinados-medicao-{a['numero']}-{assinatura_id}.pdf",
                        headers={"X-Content-Type-Options": "nosniff"})
