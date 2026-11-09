"""Ancoras para o DocuSign (issue #626): a pessoa solta os PDFs, informa os nomes e baixa o PDF juntado com as
ancoras. Nada e' gravado (sem banco, sem arquivo, sem registro na medicao): cada chamada recebe tudo e devolve."""
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app import ancoras_docusign, arquivos, leitura_pdf, pdfs
from app.permissoes import exigir

router = APIRouter()
MAX_ARQUIVOS = 60


def _json(texto: str, campo: str, tipo: type):
    try:
        valor = json.loads(texto or "null")
    except ValueError:
        raise HTTPException(422, f"Campo {campo} inválido") from None
    if valor is None:
        return tipo()
    if not isinstance(valor, tipo):
        raise HTTPException(422, f"Campo {campo} inválido")
    return valor


def _pedido(arquivos_up: list[UploadFile], papeis: str, marcar: str, desmarcar: str) -> dict:
    if not arquivos_up:
        raise HTTPException(422, "Envie ao menos um PDF")
    if len(arquivos_up) > MAX_ARQUIVOS:
        raise HTTPException(422, f"No máximo {MAX_ARQUIVOS} arquivos por vez")
    nomes = _json(papeis, "papéis", dict)
    for papel, nome in nomes.items():
        if papel not in ancoras_docusign.PAPEIS or not isinstance(nome, str) or len(nome) > 200:
            raise HTTPException(422, "Campo papéis inválido")
    paginas = {}
    for campo, texto in (("marcar", marcar), ("desmarcar", desmarcar)):
        lista = _json(texto, campo, list)
        if len(lista) > ancoras_docusign.TETO_PAGINAS or not all(
                isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in lista):
            raise HTTPException(422, f"Campo {campo} inválido")
        paginas[campo] = lista
    partes = [b"".join(arquivos.blocos_validados(a, teto_bytes=pdfs.TETO_BYTES_PACOTE)) for a in arquivos_up]
    return {"partes": partes, "papeis": {p: n for p, n in nomes.items() if n.strip()}, **paginas}


def _processar(pedido: dict, mostrar: bool, gerar: bool) -> dict:
    try:
        return ancoras_docusign.com_limite(pedido["partes"], pedido["papeis"], pedido["marcar"], pedido["desmarcar"],
                                           mostrar, gerar)
    except leitura_pdf.TextoInadequado as e:
        raise HTTPException(422, str(e)) from None
    except ValueError:
        raise HTTPException(422, leitura_pdf.PDF_CORROMPIDO) from None


@router.post("/api/ancoras-docusign/paginas")
def paginas(arquivos_up: list[UploadFile] = File(..., alias="arquivos"), papeis: str = Form("{}", max_length=2000),
            marcar: str = Form("[]", max_length=10000), desmarcar: str = Form("[]", max_length=10000),
            usuario: dict = Depends(exigir("editar_cadastros"))):
    """Que paginas recebem ancora, por que e para quem; e as que ficam sem."""
    r = _processar(_pedido(arquivos_up, papeis, marcar, desmarcar), mostrar=False, gerar=False)
    return {"paginas": r["paginas"]}


@router.post("/api/ancoras-docusign/pdf")
def pdf(arquivos_up: list[UploadFile] = File(..., alias="arquivos"), papeis: str = Form("{}", max_length=2000),
        marcar: str = Form("[]", max_length=10000), desmarcar: str = Form("[]", max_length=10000),
        mostrar: bool = Form(False), usuario: dict = Depends(exigir("editar_cadastros"))):
    """O PDF juntado com as ancoras (invisiveis, ou em vermelho com `mostrar`)."""
    r = _processar(_pedido(arquivos_up, papeis, marcar, desmarcar), mostrar=mostrar, gerar=True)
    nome = "pacote-com-ancoras-conferencia.pdf" if mostrar else "pacote-com-ancoras.pdf"
    return Response(r["pdf"], media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"', "Cache-Control": "no-store"})
