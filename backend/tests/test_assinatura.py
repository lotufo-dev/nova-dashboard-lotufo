"""Conferencia do PDF assinado (spec §6): paginas batem, extras so' certificado, carimbo em todas."""
from app import assinatura

G1 = "7E965481-0A1B-4C2D-8E9F-0123456789AB"
G2 = "C923C2B0-1111-2222-3333-444455556666"
MONTADO = ["CT/301/LT/2026 Cuiabá 16 de setembro Ref.: Contrato 099/2024 23ª Medição", "NOTA FISCAL 2311 valor 1.234,56", ""]


def _carimbar(paginas, guid=G1):
    return [f"Docusign Envelope ID: {guid}\n{t}" for t in paginas]


def test_assinado_certo_passa():
    r = assinatura.conferir(MONTADO, _carimbar(MONTADO))
    assert r["ok"] and r["envelope"] == G1 and r["avisos"] == []


def test_pdf_nao_assinado_e_pego():
    r = assinatura.conferir(MONTADO, MONTADO)
    assert not r["ok"] and [a["codigo"] for a in r["avisos"]] == ["nao_assinado"]


def test_pagina_trocada_e_pega():
    trocado = _carimbar([MONTADO[0], "OUTRA COISA COMPLETAMENTE DIFERENTE", ""])
    r = assinatura.conferir(MONTADO, trocado)
    assert any(a["codigo"] == "pagina_diferente" and "2" in a["mensagem"] for a in r["avisos"])


def test_certificado_no_fim_e_aceito_e_pagina_extra_qualquer_nao():
    cert = "Certificado de Conclusão\nIdentificação de envelope: " + G1
    r = assinatura.conferir(MONTADO, _carimbar(MONTADO) + [cert])
    assert r["ok"] and r["certificado"] == 1
    r = assinatura.conferir(MONTADO, _carimbar(MONTADO) + ["pagina solta"])
    assert [a["codigo"] for a in r["avisos"]] == ["paginas_extras"]


def test_pdfs_reais_do_docusign():
    """Textos por pagina de tres PDFs reais (tarefa 5.11): o CT-291 da Cavalaria (montado x assinado; paginas
    de planilha com o carimbo no fim do texto), o CT-073 da MT-388 (4 paginas + 4 de certificado, so' a
    primeira com o titulo) e o CT-286 da Orla, protocolado sem assinatura."""
    import json
    import pathlib
    fix = pathlib.Path(__file__).parent / "fixtures" / "assinatura"
    cav = json.loads((fix / "cavalaria-ct291.json").read_text(encoding="utf-8"))
    assert assinatura.conferir(cav["montado"], cav["assinado"])["ok"]
    trocado = cav["assinado"][:3] + [cav["assinado"][5]] + cav["assinado"][4:]
    assert [a["codigo"] for a in assinatura.conferir(cav["montado"], trocado)["avisos"]] == ["pagina_diferente"]
    ct073 = json.loads((fix / "mt388-ct073.json").read_text(encoding="utf-8"))["assinado"]
    r = assinatura.conferir([assinatura._ENVELOPE.sub("", t) for t in ct073[:4]], ct073)
    assert r["ok"] and r["certificado"] == 4
    ct286 = json.loads((fix / "orla-ct286.json").read_text(encoding="utf-8"))["assinado"]
    assert [a["codigo"] for a in assinatura.conferir(ct286, ct286)["avisos"]] == ["nao_assinado"]


def test_envelopes_diferentes_e_paginas_a_menos():
    misturado = _carimbar(MONTADO[:2]) + _carimbar(MONTADO[2:], G2)
    assert "envelopes_diferentes" in [a["codigo"] for a in assinatura.conferir(MONTADO, misturado)["avisos"]]
    assert "paginas_a_menos" in [a["codigo"] for a in assinatura.conferir(MONTADO, _carimbar(MONTADO[:2]))["avisos"]]


def test_bloco_da_assinatura_sai_e_o_texto_dos_assinados_reais_fica():
    """Issue #519: o rotulo, o nome e o codigo que a assinatura do DocuSign poe na pagina saem; nos assinados reais das
    fixtures (carimbo no fim, sem esse bloco no texto) nada muda."""
    import json
    import pathlib
    for rotulo in ("DocuSigned by:", "Assinado por:"):
        t = f"{rotulo}\nAssinante Exemplo\n4C6B1A2D3E4F4A5B...\nApostilamento nº 001/2025"
        assert assinatura._plano(assinatura.sem_bloco_de_assinatura(t)) == "APOSTILAMENTONO0012025"
    for t in ("Signed by:\n\nAssinante Exemplo\n\n4c6b1a2d3e4f4a5b...\nApostilamento",   # linha em branco, minuscula
              "4C6B1A2D3E4F4A5B...\nDocuSigned by:\nApostilamento",                   # codigo antes, sem nome
              "DocuSigned by: Assinante Exemplo\n4C6B1A2D3E4F4A5B…\nApostilamento"):
        assert assinatura._plano(assinatura.sem_bloco_de_assinatura(t)) == "APOSTILAMENTO"
    for t in ("4C6B1A2D3E4F4A5B...\nDocuSigned by:\nAssinante Exemplo\nApostilamento",    # codigo, rotulo, nome
              "DocuSigned by: Assinante Exemplo 4C6B1A2D3E4F4A5B...\nApostilamento"):     # tudo na mesma linha
        assert assinatura._plano(assinatura.sem_bloco_de_assinatura(t)) == "APOSTILAMENTO"
    # gate Sol da PR #549: linha da carta intercalada entre o rotulo e o codigo nunca sai
    t = "Assinado por:\nTermo de Apostilamento nº 001/2025/03/02\n4C6B1A2D3E4F4A5B..."
    assert assinatura._plano(assinatura.sem_bloco_de_assinatura(t)) == "TERMODEAPOSTILAMENTONO001202503 02".replace(" ", "")
    # sem o codigo logo abaixo, a linha seguinte e' texto da carta e fica
    assert assinatura._plano(assinatura.sem_bloco_de_assinatura("Termo de\nAssinado por:\nApostilamento nº 1")) == \
        "TERMODEAPOSTILAMENTONO1"
    fix = pathlib.Path(__file__).parent / "fixtures" / "assinatura"
    for nome in ("cavalaria-ct291.json", "mt388-ct073.json", "orla-ct286.json"):
        for t in json.loads((fix / nome).read_text(encoding="utf-8"))["assinado"]:
            assert assinatura.sem_bloco_de_assinatura(t) == t
