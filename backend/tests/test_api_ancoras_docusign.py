"""Rotas das ancoras para o DocuSign (issue #626): nada e' gravado, tudo volta na resposta."""
import io
import json

import pypdf
import pytest

from app import db, pdfs
from tests.test_ancoras_docusign import _pdf

PAPEIS = json.dumps({"fiscal": "Ana Souza", "supervisor": "Beto Lima"})


def _arquivos(*pdfs_):
    return [("arquivos", (f"parte{i}.pdf", p, "application/pdf")) for i, p in enumerate(pdfs_)]


@pytest.fixture
def dois():
    return (_pdf([[(72, 700, "Comissão: Ana Souza  Beto Lima")]]),
            _pdf([[(200, 60, "DIÁRIO DE OBRA")], [(72, 100, "Cronograma")]]))


def test_dois_pdfs_viram_um_pdf_juntado_e_a_lista_de_paginas(client_admin, dois):
    r = client_admin.post("/api/ancoras-docusign/paginas", files=_arquivos(*dois), data={"papeis": PAPEIS})
    assert r.status_code == 200, r.text
    assert r.json()["paginas"] == [
        {"pagina": 1, "motivo": "nome", "papeis": ["fiscal", "supervisor"]},
        {"pagina": 2, "motivo": "diario", "papeis": ["fiscal", "supervisor", "executora"]},
        {"pagina": 3, "motivo": None, "papeis": []}]
    r = client_admin.post("/api/ancoras-docusign/pdf", files=_arquivos(*dois), data={"papeis": PAPEIS})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]
    leitor = pypdf.PdfReader(io.BytesIO(r.content))
    assert len(leitor.pages) == 3
    assert "#ass-fiscal#" in leitor.pages[0].extract_text() and "#ass-fiscal#" in leitor.pages[1].extract_text()
    assert "#ass-" not in leitor.pages[2].extract_text()


def test_desmarcar_tira_a_ancora_da_pagina_e_marcar_poe_o_rodape(client_admin, dois):
    dados = {"papeis": PAPEIS, "desmarcar": json.dumps([1]), "marcar": json.dumps([3])}
    r = client_admin.post("/api/ancoras-docusign/paginas", files=_arquivos(*dois), data=dados)
    assert [(p["pagina"], p["motivo"]) for p in r.json()["paginas"]] == [(1, None), (2, "diario"), (3, "rodape")]
    r = client_admin.post("/api/ancoras-docusign/pdf", files=_arquivos(*dois), data={**dados, "mostrar": "true"})
    textos = [p.extract_text() for p in pypdf.PdfReader(io.BytesIO(r.content)).pages]
    assert "#ass-" not in textos[0] and "#ass-fiscal#" in textos[2]
    assert "conferencia" in r.headers["content-disposition"]


def test_nada_e_gravado_no_banco(client_admin, dois):
    c = db.get_conn()
    antes = c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    client_admin.post("/api/ancoras-docusign/pdf", files=_arquivos(*dois), data={"papeis": PAPEIS})
    assert c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == antes
    c.close()


def test_pdf_acima_do_teto_e_recusado_em_portugues(client_admin, dois, monkeypatch):
    monkeypatch.setattr(pdfs, "TETO_BYTES_PACOTE", 1024)
    grande = dois[0] + b" " * 4096
    r = client_admin.post("/api/ancoras-docusign/pdf", files=_arquivos(grande), data={"papeis": PAPEIS})
    assert r.status_code == 413 and "acima do limite" in r.json()["detail"]


def test_arquivos_que_somam_acima_do_teto_sao_recusados(client_admin, dois, monkeypatch):
    monkeypatch.setattr(pdfs, "TETO_BYTES_PACOTE", max(map(len, dois)) + 10)
    r = client_admin.post("/api/ancoras-docusign/pdf", files=_arquivos(*dois), data={"papeis": PAPEIS})
    assert r.status_code == 422 and "somam mais de" in r.json()["detail"]


def test_entradas_invalidas(client_admin, dois):
    assert client_admin.post("/api/ancoras-docusign/pdf", files=[("arquivos", ("x.txt", b"oi", "text/plain"))],
                             data={}).status_code == 415
    r = client_admin.post("/api/ancoras-docusign/pdf", files=_arquivos(b"%PDF-1.4 lixo"), data={})
    assert r.status_code == 422 and "PDF" in r.json()["detail"]
    r = client_admin.post("/api/ancoras-docusign/paginas", files=_arquivos(*dois), data={"papeis": '{"chefe": "X"}'})
    assert r.status_code == 422
    r = client_admin.post("/api/ancoras-docusign/paginas", files=_arquivos(*dois), data={"marcar": '["a"]'})
    assert r.status_code == 422


def test_exige_login(client, dois):
    assert client.post("/api/ancoras-docusign/pdf", files=_arquivos(*dois)).status_code == 401
