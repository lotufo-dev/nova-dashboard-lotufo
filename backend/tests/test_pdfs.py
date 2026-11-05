"""Juntar PDF, texto por pagina e upload com teto por rota (bloco 5)."""
import io

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app import arquivos, carta, leitura_pdf, pdfs


# Gera PDF com a fonte da producao (Arial no Windows): a CI roda este modulo nos dois jobs (marcador pdf).
pytestmark = pytest.mark.pdf

def test_juntar_preserva_a_ordem_e_o_texto_por_pagina():
    a = carta.pagina_titulo(["PRIMEIRA"])
    b = carta.pagina_titulo(["SEGUNDA"])
    junto = pdfs.juntar([a, b, a])
    assert pdfs.paginas(junto) == 3
    textos = leitura_pdf.textos_por_pagina_com_limite(junto)
    assert ["PRIMEIRA" in textos[0], "SEGUNDA" in textos[1], "PRIMEIRA" in textos[2]] == [True, True, True]


def test_pacote_montado_no_subprocesso_recusa_parte_que_nao_e_pdf():
    a, b = carta.pagina_titulo(["PRIMEIRA"]), carta.pagina_titulo(["SEGUNDA"])
    junto, n = leitura_pdf.juntar_com_limite([a, b])
    assert n == 2 and "SEGUNDA" in leitura_pdf.textos_por_pagina_com_limite(junto)[1]
    with pytest.raises(ValueError):
        leitura_pdf.juntar_com_limite([a, b"%PDF-1.7 lixo"])


def test_texto_por_pagina_respeita_o_teto_de_paginas():
    junto = pdfs.juntar([carta.pagina_titulo(["X"])] * 3)
    with pytest.raises(leitura_pdf.TextoInadequado):
        leitura_pdf.textos_por_pagina_com_limite(junto, teto_paginas=2)


def _upload(dados: bytes, content_type: str) -> UploadFile:
    return UploadFile(io.BytesIO(dados), filename="x", headers=Headers({"content-type": content_type}))


def test_upload_de_planilha_e_teto_por_rota():
    planilha = b"PK\x03\x04" + b"x" * 10
    assert b"".join(arquivos.blocos_validados(_upload(planilha, arquivos.MIME_XLSX), tipo="xlsx")) == planilha
    with pytest.raises(HTTPException) as e:
        list(arquivos.blocos_validados(_upload(planilha, arquivos.MIME_XLSX)))        # PDF por padrao
    assert e.value.status_code == 415
    grande = b"%PDF-" + b"0" * (2 * 1024 * 1024)
    with pytest.raises(HTTPException) as e:
        list(arquivos.blocos_validados(_upload(grande, "application/pdf"), teto_bytes=1024 * 1024))
    assert e.value.status_code == 413
