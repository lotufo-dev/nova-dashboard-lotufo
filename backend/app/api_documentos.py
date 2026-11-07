"""Rotas dos documentos de protocolo (bloco 4, spec 2026-09-21 §9 e §10.4).

Gravar RELE o PDF no servidor: o que a tela mostrou e' conferencia, nao fonte (decisao 5 do plano).
Os campos do formulario so' valem quando o leitor nao consegue (motivo em DIGITAVEIS). O PDF so' vai
para o disco depois de decidido gravar: recusa nao deixa arquivo orfao na pasta de dados.
"""
import datetime
import sqlite3
import urllib.parse
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from app import arquivos, checklist, documentos, entidades, leitura_certidao, leitura_pdf, tempo
from app.api_auth import conexao
from app.api_medicoes import ID
from app.permissoes import exigir

router = APIRouter()
MAX_INT64 = 9223372036854775807


def _texto(pdf: bytes, status_inadequado: int = 422) -> str:
    """Texto do PDF em subprocesso. Recusa nossa (bomba, paginas ou texto demais, tempo) vira
    `status_inadequado`: 422 na leitura (a tela so' mostra), 415 na gravacao (mesma guarda de
    `arquivos.conferir_parseavel`, que o upload antigo usava)."""
    try:
        return leitura_pdf.texto_de_pdf_com_limite(pdf)
    except leitura_pdf.TextoInadequado as e:
        raise HTTPException(status_inadequado, str(e))
    except Exception:      # pypdf no filho: corrompido, cifrado, truncado
        raise HTTPException(415, leitura_pdf.PDF_CORROMPIDO)


@router.get("/api/documentos")
def painel(usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
           conn: sqlite3.Connection = Depends(conexao)):
    return documentos.painel(conn)


@router.post("/api/documentos/certidoes/ler")
def ler(arquivo: UploadFile = File(...), usuario: dict = Depends(exigir("editar_cadastros")),
        conn: sqlite3.Connection = Depends(conexao)):
    """PDF -> leitura para a pessoa conferir. NAO grava nada. PDF sem texto passa pelo OCR local."""
    pdf = b"".join(arquivos.blocos_validados(arquivo))
    texto, ocr = documentos.texto_para_leitura(pdf, _texto(pdf))
    try:
        return {"ok": True, "leitura": {**documentos.ler(conn, texto), "ocr": ocr}}
    except leitura_certidao.Recusa as e:
        return {"ok": False, "motivo": e.motivo, "mensagem": str(e),
                "digitavel": e.motivo in leitura_certidao.DIGITAVEIS, **({"lidos": e.lidos} if e.lidos else {})}


@router.post("/api/documentos/certidoes", status_code=201)
def gravar(arquivo: UploadFile = File(...),
           entidade_id: int | None = Form(default=None, ge=1, le=MAX_INT64),
           tipo: Literal["federal", "fgts", "trabalhista", "estadual", "municipal", "falencia"] | None = Form(default=None),
           emissao: datetime.date | None = Form(default=None),
           validade: datetime.date | None = Form(default=None),
           natureza: Literal["negativa", "positiva_efeito_negativa"] | None = Form(default=None),
           numero: str | None = Form(default=None, max_length=100),
           usuario: dict = Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    # Guarda barata ANTES dos bytes e do subprocesso (como no upload da fase 3): entidade que nao
    # existe e' 404, desativada e' 422.
    if entidade_id is not None:
        e = entidades.detalhe(conn, entidade_id)
        if e is None:
            raise HTTPException(404, f"Entidade {entidade_id} não encontrada")
        if not e["ativo"]:
            raise HTTPException(422, f"Entidade '{e['nome']}' está desativada e não aceita novas certidões")
    # Em memoria (teto de 10 MB em blocos); a extracao em subprocesso prova que o PDF abre.
    pdf = b"".join(arquivos.blocos_validados(arquivo))
    texto, ocr = documentos.texto_para_leitura(pdf, _texto(pdf, 415))
    try:
        dados, leitura = documentos.ler(conn, texto), "automatica"
    except leitura_certidao.Recusa as e:
        if e.motivo not in leitura_certidao.DIGITAVEIS:
            raise HTTPException(422, str(e))
        if entidade_id is None or tipo is None or emissao is None:
            raise HTTPException(422, f"{e} Faltam empresa, tipo e emissão.")
        try:
            dados = documentos.dados_manuais(conn, entidade_id, tipo, emissao.isoformat(),
                                             validade.isoformat() if validade else None, natureza, numero,
                                             cnpjs_do_texto=leitura_certidao.cnpjs_no_texto(texto))
        except ValueError as v:
            raise HTTPException(422, str(v))
        if dados["validade"] <= dados["emissao"]:
            raise HTTPException(422, f"A validade ({dados['validade']}) precisa ser posterior à emissão "
                                     f"({dados['emissao']})")
        leitura, ocr = "manual", False
    # Tudo o que recusa vem ANTES de o PDF ir para o disco (gate Sol, achado 7); a conferencia de
    # repetida se refaz dentro da transacao em `gravar_certidao`.
    if documentos.ja_cadastrada(conn, dados):
        validade = datetime.date.fromisoformat(dados["validade"]).strftime("%d/%m/%Y")
        raise HTTPException(409, f"Esta certidão já está cadastrada (válida até {validade})")
    _, sha = arquivos.gravar_bytes("certidoes", pdf, "pdf")
    try:
        cid = documentos.gravar_certidao(conn, usuario["id"], dados, f"certidoes/{sha}.pdf", sha,
                                         arquivo.filename, leitura, ocr=ocr)
    except ValueError as v:
        raise HTTPException(409 if "já está cadastrada" in str(v) else 422, str(v))
    return {"id": cid, "leitura": leitura, "ocr": ocr, **{k: v for k, v in dados.items() if k != "evidencia"}}


@router.post("/api/documentos/regularidades", status_code=201)
def regularidade(arquivo: UploadFile = File(...),
                 entidade_id: int = Form(..., ge=1, le=MAX_INT64),
                 competencia: str | None = Form(None, pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$"),  # A-14: \d casa "٢٠٢٦"
                 usuario: dict = Depends(exigir("editar_cadastros")),
                 conn: sqlite3.Connection = Depends(conexao)):
    # A competencia que vale e' a impressa no PDF (09/10/2026): sem `competencia` (botao do envio) usa a do PDF;
    # com ela (formulario de Documentos), se nao bater com a do PDF, recusa dizendo qual e' a certa.
    inicio = arquivo.file.read(arquivos.TETO_BYTES + 1)
    arquivo.file.seek(0)
    do_pdf = documentos.competencia_do_pdf(inicio) if len(inicio) <= arquivos.TETO_BYTES else None
    if competencia and do_pdf and competencia != do_pdf:
        raise HTTPException(422, f"O PDF é da competência {do_pdf[5:]}/{do_pdf[:4]} (cabeçalho da folha), mas foi "
                                 f"informada {competencia[5:]}/{competencia[:4]}. Confira o arquivo ou o mês.")
    competencia = competencia or do_pdf
    if not competencia:
        raise HTTPException(422, "Não foi possível ler a competência no PDF: informe o mês em Documentos")
    # Guardas de dominio ANTES de gravar o PDF (gate Sol, achado 6): recusa nao deixa arquivo orfao.
    try:
        documentos.conferir_regularidade(conn, entidade_id, competencia)
    except ValueError as v:
        raise HTTPException(422, str(v))
    pasta = arquivos.pasta("regularidades")
    sha = arquivos.receber_pdf(arquivo, pasta)
    try:
        rid = documentos.registrar_regularidade(conn, usuario["id"], entidade_id, competencia,
                                                f"regularidades/{sha}.pdf", sha,
                                                (pasta / f"{sha}.pdf").stat().st_size, arquivo.filename)
    except ValueError as v:
        raise HTTPException(422, str(v))
    return {"id": rid}


@router.get("/api/documentos/regularidades/{rid}/arquivo")
def baixar_regularidade(rid: ID, usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
                        conn: sqlite3.Connection = Depends(conexao)):
    if not 1 <= rid <= MAX_INT64:
        raise HTTPException(404, "Regularidade não encontrada")
    r = conn.execute("SELECT * FROM regularidades WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "Regularidade não encontrada")
    try:
        caminho = arquivos.caminho_seguro(r["arquivo"])
    except Exception:
        raise HTTPException(404, "Arquivo da regularidade não encontrado")
    if not caminho.is_file():
        raise HTTPException(404, "Arquivo da regularidade não encontrado")
    return FileResponse(caminho, media_type=arquivos.MIME, filename=f"regularidade-{r['competencia']}.pdf",
                        headers={"X-Content-Type-Options": "nosniff"})


@router.get("/api/documentos/zip")
def zip_vigentes(entidade_id: int = Query(ge=1, le=MAX_INT64), data: datetime.date | None = None,
                 usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
                 conn: sqlite3.Connection = Depends(conexao)):
    na_data = (data or tempo.hoje_local()).isoformat()
    try:
        nome, dados = documentos.zip_vigentes(conn, entidade_id, na_data)
    except ValueError as v:
        raise HTTPException(422, str(v))
    return Response(dados, media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(nome)}"})


# --- checklist do protocolo (era de api_certidoes ate' o bloco 9; mesmo caminho) -------------

@router.get("/api/contratos/{contrato_id}/checklist-protocolo")
def checklist_protocolo(contrato_id: ID,
                        natureza: Literal["execucao", "projeto", "reajuste"] = "execucao",
                        usuario: dict = Depends(exigir("ver_paineis", com_csrf=False)),
                        conn: sqlite3.Connection = Depends(conexao)):
    """"Posso protocolar este contrato hoje?" -- certidoes da entidade DELE.

    Mora neste modulo, e nao em api_contratos.py, porque o assunto e' certidao: o
    contrato so' diz de qual CNPJ a pergunta e'. O caminho segue o do contrato
    (`/api/contratos/{id}/...`, como a curva em api_paineis.py) porque e' assim que a
    tela chega ate' aqui -- da pagina do contrato.

    Leitura pura: `ver_paineis` sem CSRF (o header so' faz sentido em escrita) e nada
    de auditoria. O 404 vem ANTES do repositorio, que assume contrato existente.
    """
    if not 1 <= contrato_id <= MAX_INT64 or conn.execute(
            "SELECT id FROM contratos WHERE id=?", (contrato_id,)).fetchone() is None:
        raise HTTPException(404, "Contrato não encontrado")
    return checklist.pronto_para_protocolar(conn, contrato_id, natureza)


# --- "Anexar PDF" unico (issue #513): o conteudo decide se e' certidao ou regularidade mensal ---------------

def _folha(conn, arquivo: UploadFile) -> dict | None:
    """Le o PDF recebido (sem gravar) e diz se e' a folha do DP; devolve o ponteiro do arquivo ao inicio."""
    pdf = arquivo.file.read(arquivos.TETO_BYTES + 1)
    arquivo.file.seek(0)
    if len(pdf) > arquivos.TETO_BYTES:
        return None          # o teto e' recusado adiante, pelo mesmo caminho da certidao
    return documentos.reconhecer_regularidade(conn, pdf)


@router.post("/api/documentos/anexar/ler")
def anexar_ler(arquivo: UploadFile = File(...), usuario: dict = Depends(exigir("editar_cadastros")),
               conn: sqlite3.Connection = Depends(conexao)):
    """Um ponto de entrada para qualquer PDF: folha do DP vira regularidade mensal; o resto segue a leitura da
    certidao. NAO grava nada. Folha cuja empresa nao se reconhece cai na fila humana (recusada, com o motivo)."""
    f = _folha(conn, arquivo)
    if f is None:
        r = ler(arquivo, usuario, conn)
        return {**r, "documento": "certidao"} if r.get("ok") else r
    if f["entidade_id"] is None:
        return {"ok": False, "motivo": "regularidade-sem-empresa", "digitavel": False,
                "mensagem": f"Folha do DP de {f['competencia'][5:]}/{f['competencia'][:4]}, mas a empresa não aparece "
                            "no cadastro: anexe pela página da empresa (aba Regularidade do mês)."}
    return {"ok": True, "documento": "regularidade", "leitura": {"documento": "regularidade", **f}}


@router.post("/api/documentos/anexar", status_code=201)
def anexar(arquivo: UploadFile = File(...),
           entidade_id: int | None = Form(default=None, ge=1, le=MAX_INT64),
           tipo: Literal["federal", "fgts", "trabalhista", "estadual", "municipal", "falencia"] | None = Form(default=None),
           emissao: datetime.date | None = Form(default=None),
           validade: datetime.date | None = Form(default=None),
           natureza: Literal["negativa", "positiva_efeito_negativa"] | None = Form(default=None),
           numero: str | None = Form(default=None, max_length=100),
           usuario: dict = Depends(exigir("editar_cadastros")),
           conn: sqlite3.Connection = Depends(conexao)):
    f = _folha(conn, arquivo)
    if f is None:
        g = gravar(arquivo, entidade_id, tipo, emissao, validade, natureza, numero, usuario, conn)
        return {**g, "documento": "certidao"}
    if f["entidade_id"] is None:
        raise HTTPException(422, "Folha do DP, mas a empresa não aparece no cadastro: anexe pela página da empresa "
                                 "(aba Regularidade do mês)")
    r = regularidade(arquivo, f["entidade_id"], f["competencia"], usuario, conn)
    return {**r, "documento": "regularidade", "entidade": f["entidade"], "competencia": f["competencia"]}
