"""Espelho de NF: previa, geracao, download dos .docx e envio ao faturamento (spec §3 passos 1-2)."""
import sqlite3

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import arquivos, auditoria, db, dinheiro, envio_reserva, espelho, espelhos, graph
from app.api_auth import conexao
from app.api_medicoes import COMPETENCIA, ID, MAX_INT64, _contrato_existe, _medicao_existe
from app.permissoes import exigir

router = APIRouter()
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class EspelhoIn(BaseModel):
    numero: int = Field(ge=1, le=999)
    competencia: str = Field(pattern=COMPETENCIA)
    # chave da entrada (regra da obra) -> valor em BRL ("278.509,92"); vazio = zero
    entradas: dict[str, str] = Field(max_length=10)
    motivo: str | None = Field(default=None, max_length=500)
    # periodo do texto do espelho quando nao e' o mes civil da competencia (ISO); vazio = mes inteiro
    periodo_inicio: str | None = Field(default=None, max_length=10)
    periodo_fim: str | None = Field(default=None, max_length=10)
    # issue #284: "seguir sem boletim" na medicao que ja' existia antes do espelho (vai para a auditoria)
    justificativa_sem_boletim: str | None = Field(default=None, max_length=500)


class EnvioIn(BaseModel):
    para: list[str] = Field(max_length=30)
    copia: list[str] = Field(max_length=30)
    cco: list[str] = Field(default_factory=list, max_length=30)
    assunto: str = Field(min_length=1, max_length=300)
    corpo: str = Field(max_length=20000)
    reenviar: bool = False          # versao ja' enviada: so' manda de novo confirmado (S8, 10/10/2026)


def _centavos(entradas: dict[str, str]) -> dict[str, int]:
    out = {}
    for k, v in entradas.items():
        if len(k) > 40 or len(v) > 40:
            raise HTTPException(422, "entrada ou valor longo demais")
        try:
            # issue #589: o reajuste negativo entra com o sinal; quem recusa o sinal fora do reajuste e' o motor
            out[k] = dinheiro.parse_brl_com_sinal(v) if v.strip() else 0
        except ValueError as e:
            raise HTTPException(422, f"{k}: {e}") from None
        if abs(out[k]) > espelho.TETO_CENTAVOS:
            raise HTTPException(422, f"{k}: valor acima do limite")
    return out


def _emails(lista: list[str]) -> list[str]:
    limpos = []
    for e in lista:
        e = e.strip().lower()
        if not e:
            continue
        if len(e) > 200 or "@" not in e:
            raise HTTPException(422, f"e-mail inválido: {e}")
        limpos.append(e)
    return list(dict.fromkeys(limpos))


@router.get("/api/contratos/{contrato_id}/espelho")
def regra_e_espelhos(contrato_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
                     conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    r = espelhos.regra_do_contrato(conn, contrato_id)
    regra = None if r is None else {"situacao": r["situacao"], "entradas": r["regra"]["entradas"],
                                    "saidas": len(r["regra"]["saidas"])}
    return {"regra": regra, "espelhos": espelhos.listar(conn, contrato_id)}


@router.post("/api/contratos/{contrato_id}/espelho/previa")
def previa(contrato_id: ID, dados: EspelhoIn, _=Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    try:
        return espelhos.previa(conn, contrato_id, dados.numero, dados.competencia, _centavos(dados.entradas),
                               espelhos.validar_periodo(dados.competencia, dados.periodo_inicio, dados.periodo_fim))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.post("/api/contratos/{contrato_id}/espelho", status_code=201)
def gerar(contrato_id: ID, dados: EspelhoIn, usuario: dict = Depends(exigir("editar_cadastros")),
          conn: sqlite3.Connection = Depends(conexao)):
    _contrato_existe(conn, contrato_id)
    try:
        eid = espelhos.gerar(conn, usuario, contrato_id, dados.numero, dados.competencia,
                             _centavos(dados.entradas), dados.motivo,
                             espelhos.validar_periodo(dados.competencia, dados.periodo_inicio, dados.periodo_fim),
                             justificativa_sem_boletim=dados.justificativa_sem_boletim)
    except ValueError as e:
        conn.rollback()
        raise HTTPException(422, str(e)) from None
    return {"espelho_id": eid}


def _espelho(conn, espelho_id) -> dict:
    if not 1 <= espelho_id <= MAX_INT64:
        raise HTTPException(404, "Espelho não encontrado")
    d = espelhos.detalhe(conn, espelho_id)
    if d is None:
        raise HTTPException(404, "Espelho não encontrado")
    return d


@router.get("/api/espelhos/{espelho_id}")
def detalhe(espelho_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
            conn: sqlite3.Connection = Depends(conexao)):
    return _espelho(conn, espelho_id)


@router.get("/api/espelhos/{espelho_id}/arquivos/{documento_id}")
def baixar(espelho_id: ID, documento_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
           conn: sqlite3.Connection = Depends(conexao)):
    if not (1 <= espelho_id <= MAX_INT64 and 1 <= documento_id <= MAX_INT64):
        raise HTTPException(404, "Arquivo não encontrado")
    doc = conn.execute("SELECT nome, arquivo FROM medicao_documentos WHERE id=? AND espelho_id=?",
                       (documento_id, espelho_id)).fetchone()
    if doc is None or not doc["arquivo"]:
        raise HTTPException(404, "Arquivo não encontrado")
    try:
        caminho = arquivos.caminho_seguro(doc["arquivo"])
    except ValueError:
        raise HTTPException(404, "Arquivo não encontrado") from None
    if not caminho.is_file():
        raise HTTPException(404, "Arquivo não encontrado")
    return FileResponse(caminho, media_type=DOCX, filename=doc["nome"])


@router.get("/api/espelhos/{espelho_id}/envio")
def previa_envio(espelho_id: ID, usuario: dict = Depends(exigir("editar_cadastros", com_csrf=False)),
                 conn: sqlite3.Connection = Depends(conexao)):
    _espelho(conn, espelho_id)
    try:
        return espelhos.previa_envio(conn, espelho_id, remetente=usuario.get("email"))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.post("/api/espelhos/{espelho_id}/enviar")
def enviar(espelho_id: ID, dados: EnvioIn, usuario: dict = Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    _espelho(conn, espelho_id)
    try:
        eid = espelhos.enviar(conn, {"id": usuario["id"], "email": usuario["email"]}, espelho_id,
                              _emails(dados.para), _emails(dados.copia), dados.assunto.strip(), dados.corpo,
                              cco=_emails(dados.cco), reenviar=dados.reenviar)
    except envio_reserva.EnvioEmAndamento as e:
        conn.rollback()
        raise HTTPException(409, detail=e.detalhe()) from None
    except (ValueError, graph.ErroGraph) as e:
        conn.rollback()
        raise HTTPException(422, str(e)) from None
    return {"envio_id": eid}


# --- documentos locais da medicao (evidencia do orgao, spec §3 passo 1) ----------------------

PDF = "application/pdf"


@router.post("/api/medicoes/{medicao_id}/documentos", status_code=201)
def anexar_documento(medicao_id: ID, arquivo: UploadFile = File(...), tipo_doc: str = Form("evidencia_orgao"),
                     usuario: dict = Depends(exigir("editar_cadastros")),
                     conn: sqlite3.Connection = Depends(conexao)):
    """Arrasta o que o orgao mandou (PDF): fica como evidencia 'informado pelo orgao' da medicao.
    Mesmas guardas do upload de certidao (app/arquivos.py): tipo, %PDF-, 10 MB, abre no leitor."""
    if not 1 <= medicao_id <= MAX_INT64:
        raise HTTPException(404, "Medição não encontrada")
    _medicao_existe(conn, medicao_id)
    if tipo_doc != "evidencia_orgao":
        raise HTTPException(422, "tipo_doc: só evidencia_orgao é aceito aqui")
    sha = arquivos.receber_pdf(arquivo, arquivos.pasta("evidencias"))
    caminho = f"evidencias/{sha}.pdf"
    nome = (arquivo.filename or "documento.pdf")[-200:]
    tamanho = arquivos.caminho_seguro(caminho).stat().st_size
    with db.mutacao(conn):
        ja = conn.execute("SELECT id FROM medicao_documentos WHERE medicao_id=? AND item_id=?",
                          (medicao_id, sha)).fetchone()
        if ja is not None:
            return {"documento_id": ja["id"], "repetido": True}
        cur = conn.execute(
            "INSERT INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, item_id, arquivo, sha256, tamanho) "
            "VALUES (?,'operacao','evidencia_orgao',?,?,?,?,?)", (medicao_id, nome, sha, caminho, sha, tamanho))
        auditoria.registrar(conn, usuario["id"], "medicao.documento", "medicao", medicao_id, None,
                            {"documento_id": cur.lastrowid, "tipo_doc": "evidencia_orgao", "nome": nome,
                             "sha256": sha, "tamanho": tamanho})
    return {"documento_id": cur.lastrowid, "repetido": False}


@router.get("/api/medicoes/{medicao_id}/documentos/{documento_id}")
def baixar_documento(medicao_id: ID, documento_id: ID, _=Depends(exigir("ver_paineis", com_csrf=False)),
                     conn: sqlite3.Connection = Depends(conexao)):
    if not (1 <= medicao_id <= MAX_INT64 and 1 <= documento_id <= MAX_INT64):
        raise HTTPException(404, "Arquivo não encontrado")
    doc = conn.execute("SELECT nome, arquivo FROM medicao_documentos WHERE id=? AND medicao_id=?",
                       (documento_id, medicao_id)).fetchone()
    if doc is None or not doc["arquivo"]:
        raise HTTPException(404, "Arquivo não encontrado")
    try:
        caminho = arquivos.caminho_seguro(doc["arquivo"])
    except ValueError:
        raise HTTPException(404, "Arquivo não encontrado") from None
    if not caminho.is_file():
        raise HTTPException(404, "Arquivo não encontrado")
    tipo = PDF if caminho.suffix.lower() == ".pdf" else DOCX
    return FileResponse(caminho, media_type=tipo, filename=doc["nome"])
