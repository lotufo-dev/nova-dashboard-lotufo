"""Ancoras de texto invisiveis para o AutoPlace do DocuSign (issue #626)."""
import io
import re

import pypdf
import pypdfium2 as pdfium
import pytest
from fpdf import FPDF

from app import ancoras_docusign as ad

NOMES = {"fiscal": "Ana Souza", "supervisor": "Beto Lima", "executora": "Carla Dias"}
ANCORA = re.compile(r"#ass-[a-z]+#")


def _pdf(paginas: list[list[tuple[float, float, str]]], tamanho=(612, 792)) -> bytes:
    """Cada pagina: lista de (x, y a partir do alto, texto) em Helvetica 12 pt."""
    f = FPDF(unit="pt", format=tamanho)
    f.set_auto_page_break(False)
    for textos in paginas:
        f.add_page()
        f.set_font("Helvetica", size=12)
        for x, y, t in textos:
            f.text(x, y, t)
    return bytes(f.output())


def _pdf_girado(textos: list[tuple[float, float, str]], graus: int) -> bytes:
    """Pagina cujo texto aparece em pe (x, y a partir do alto da pagina COMO E' VISTA) mas esta' desenhado girado no
    conteudo, com `/Rotate` para desfazer: como sai um relatorio paisagem de verdade. Tamanho visto: 792x612 (90, 270)."""
    W, H = 612, 792
    f = FPDF(unit="pt", format=(W, H))
    f.set_auto_page_break(False)
    f.add_page()
    f.set_font("Helvetica", size=12)
    for vx, vy, t in textos:
        if graus == 90:
            x, y, ang = vy, H - vx, 90
        elif graus == 270:
            x, y, ang = W - vy, vx, -90
        else:   # 180
            x, y, ang = W - vx, H - vy, 180
        with f.rotation(ang, x, y):
            f.text(x, y, t)
    w = pypdf.PdfWriter(clone_from=io.BytesIO(bytes(f.output())))
    w.pages[0].rotate(graus)
    s = io.BytesIO()
    w.write(s)
    return s.getvalue()


def _processar(pdf: bytes, papeis=NOMES, marcar=(), desmarcar=(), mostrar=False):
    return ad.processar({"partes": [pdf], "papeis": papeis, "marcar": list(marcar), "desmarcar": list(desmarcar),
                         "mostrar": mostrar, "gerar": True})


def _achadas(pdf: bytes) -> list[dict[str, tuple[float, float, float]]]:
    """Por pagina, onde o texto de cada ancora esta': (esquerda, base, topo), na pagina como e' vista."""
    doc = pdfium.PdfDocument(pdf)
    leitor = pypdf.PdfReader(io.BytesIO(pdf))
    saida = []
    for i in range(len(doc)):
        pg = doc[i]
        tp = pg.get_textpage()
        texto = tp.get_text_range()
        caixa = leitor.pages[i].cropbox
        giro = int(leitor.pages[i].get("/Rotate", 0) or 0) % 360
        achadas = {}
        for m in ANCORA.finditer(texto):
            caixas = [ad._visivel(tp.get_charbox(k, loose=True), giro, float(caixa.width), float(caixa.height),
                                  float(caixa.left), float(caixa.bottom)) for k in range(m.start(), m.end())]
            achadas[m.group()] = (caixas[0][0], min(c[1] for c in caixas), max(c[3] for c in caixas))
        saida.append(achadas)
    return saida


def _texto(pdf: bytes, i: int) -> str:
    return pypdf.PdfReader(io.BytesIO(pdf)).pages[i].extract_text()


def test_comissao_com_dois_nomes_recebe_duas_ancoras_e_frase_nao_recebe():
    pdf = _pdf([[(72, 700, "Comissão: Ana Souza     Beto Lima")],
                [(72, 300, "O fiscal Ana Souza acompanhou a obra em junho.")]])
    r = _processar(pdf)
    p1, p2 = r["paginas"]
    assert p1 == {"pagina": 1, "motivo": "nome", "papeis": ["fiscal", "supervisor"]}
    assert p2 == {"pagina": 2, "motivo": None, "papeis": []}
    achadas = _achadas(r["pdf"])
    assert set(achadas[0]) == {"#ass-fiscal#", "#ass-supervisor#"} and achadas[1] == {}
    # 4 pt a esquerda do inicio do nome, topo 11 pt acima do topo do nome
    nomes = {p["texto"]: p for p in ad._linhas(_chars(pdf, 0))[0]}
    fiscal, supervisor = achadas[0]["#ass-fiscal#"], achadas[0]["#ass-supervisor#"]
    assert fiscal[0] == pytest.approx(nomes["Ana"]["esq"] - 4, abs=0.6)
    assert supervisor[0] == pytest.approx(nomes["Beto"]["esq"] - 4, abs=0.6)
    assert fiscal[2] == pytest.approx(nomes["Ana"]["topo"] + 11, abs=1.5)


def _chars(pdf: bytes, i: int):
    """Os caracteres da pagina na pagina como e' vista."""
    doc = pdfium.PdfDocument(pdf)
    pp = pypdf.PdfReader(io.BytesIO(pdf)).pages[i]
    giro = int(pp.get("/Rotate", 0) or 0) % 360
    tp = doc[i].get_textpage()
    saida = []
    for k, ch in enumerate(tp.get_text_range()):
        if not ch.isspace():
            saida.append((ch, *ad._visivel(tp.get_charbox(k, loose=True), giro, float(pp.cropbox.width), float(pp.cropbox.height),
                                           float(pp.cropbox.left), float(pp.cropbox.bottom))))
    return saida


def test_titulo_diario_de_obra_recebe_tres_ancoras_no_rodape():
    pdf = _pdf([[(200, 60, "DIÁRIO DE OBRA"), (72, 120, "Fiscal: Ana Souza")]])
    r = _processar(pdf)
    assert r["paginas"] == [{"pagina": 1, "motivo": "diario", "papeis": ["fiscal", "supervisor", "executora"]}]
    achadas = _achadas(r["pdf"])[0]
    assert [round(achadas[a][0]) for a in ("#ass-fiscal#", "#ass-supervisor#", "#ass-executora#")] == [116, 272, 426]
    assert all(a[1] < 5 for a in achadas.values())          # a base da letra a ~2 pt da borda inferior
    assert "#ass-superior#" not in achadas


def test_pagina_girada_recebe_a_ancora_em_pe_no_rodape_visivel():
    for graus, (larg, alt) in ((90, (792, 612)), (180, (612, 792)), (270, (792, 612))):
        girado = _pdf_girado([(300, 60, "DIÁRIO DE OBRA")], graus)
        r = _processar(girado)
        assert r["paginas"][0]["motivo"] == "diario", graus
        saida = pypdf.PdfReader(io.BytesIO(r["pdf"]))
        assert float(saida.pages[0].mediabox.width) == larg and float(saida.pages[0].mediabox.height) == alt
        assert not saida.pages[0].get("/Rotate", 0)
        achadas = _achadas(r["pdf"])[0]
        assert [round(achadas[a][0]) for a in ("#ass-fiscal#", "#ass-supervisor#", "#ass-executora#")] == [116, 272, 426]
        assert all(0 <= a[1] < 5 for a in achadas.values()), graus


def test_pagina_girada_com_nome_no_lugar_do_nome():
    girado = _pdf_girado([(100, 100, "Comissão: Ana Souza")], 90)
    r = _processar(girado)
    assert r["paginas"][0]["papeis"] == ["fiscal"]
    nome = next(p for p in ad._linhas(_chars(girado, 0))[0] if p["texto"] == "Ana")
    ancora = _achadas(r["pdf"])[0]["#ass-fiscal#"]
    assert ancora[0] == pytest.approx(nome["esq"] - 4, abs=0.6)
    assert ancora[2] == pytest.approx(nome["topo"] + 11, abs=1.5)


def test_texto_das_ancoras_e_extraivel_e_o_original_continua_igual():
    pdf = _pdf([[(72, 700, "Comissão: Ana Souza"), (72, 100, "Relatório do mês de junho")], [(72, 100, "Sem nome aqui")]])
    original = [pypdf.PdfReader(io.BytesIO(pdf)).pages[i].extract_text() for i in range(2)]
    for mostrar in (False, True):
        r = _processar(pdf, mostrar=mostrar)
        assert "#ass-fiscal#" in _texto(r["pdf"], 0)
        # o original segue la' e a pagina sem ancora e' a mesma
        assert original[0] in _texto(r["pdf"], 0).replace("#ass-fiscal#", "").strip() or \
            all(l in _texto(r["pdf"], 0) for l in original[0].splitlines())
        assert _texto(r["pdf"], 1) == original[1]
    # invisivel por padrao: modo de renderizacao 3 no conteudo da pagina; em conferencia, vermelho e visivel
    inv = pypdf.PdfReader(io.BytesIO(_processar(pdf)["pdf"])).pages[0].get_contents().get_data()
    vis = pypdf.PdfReader(io.BytesIO(_processar(pdf, mostrar=True)["pdf"])).pages[0].get_contents().get_data()
    assert b"3 Tr" in inv and b"3 Tr" not in vis
    assert b"1 0 0 rg" in vis


def test_nome_com_enga_e_acento_casa_com_o_nome_informado_sem_acento():
    pdf = _pdf([[(72, 700, "Engª Civil Ana Souza")], [(72, 700, "ENG. CIVIL BETO LIMA")],
                [(72, 700, "Equipe: Eng. Civil Carla Díaz")]])
    r = _processar(pdf, papeis={"fiscal": "ANA SOUZA", "supervisor": "beto  lima", "executora": "Carla Diaz"})
    assert [p["papeis"] for p in r["paginas"]] == [["fiscal"], ["supervisor"], ["executora"]]
    # o nome tambem pode vir com acento e prefixo
    r = _processar(pdf, papeis={"fiscal": "Eng. Ana Souza"})
    assert r["paginas"][0]["papeis"] == ["fiscal"]


def test_nome_com_outras_palavras_na_linha_nao_recebe_ancora():
    pdf = _pdf([[(72, 100, "Fiscal do contrato: Ana Souza"), (72, 140, "Ana Souza - CREA 12345"),
                 (72, 180, "Ana Souza Lima")]])
    assert _processar(pdf)["paginas"][0]["papeis"] == []


def test_marcar_pagina_sem_ancora_poe_o_rodape_e_desmarcar_tira():
    pdf = _pdf([[(72, 700, "Comissão: Ana Souza")], [(72, 100, "Cronograma")], [(72, 100, "Outra")]])
    r = _processar(pdf, marcar=[2, 1], desmarcar=[1])
    p1, p2, p3 = r["paginas"]
    assert p1 == {"pagina": 1, "motivo": None, "papeis": []}      # desmarcar vale sobre a automatica
    assert p2 == {"pagina": 2, "motivo": "rodape", "papeis": ["fiscal", "supervisor", "executora"]}
    assert p3["motivo"] is None
    achadas = _achadas(r["pdf"])
    assert achadas[0] == {} and len(achadas[1]) == 3 and achadas[2] == {}


def test_sem_nomes_so_o_diario_recebe():
    pdf = _pdf([[(72, 700, "Comissão: Ana Souza")], [(200, 60, "Diário de Obra")]])
    r = _processar(pdf, papeis={})
    assert [p["motivo"] for p in r["paginas"]] == [None, "diario"]


def test_diario_so_conta_no_alto_da_pagina():
    pdf = _pdf([[(72, 700, "Diário de Obra")]])
    assert _processar(pdf)["paginas"][0]["motivo"] is None


def test_junta_varios_pdfs_e_numera_as_paginas_em_sequencia():
    a = _pdf([[(72, 700, "Comissão: Ana Souza")]])
    b = _pdf([[(200, 60, "DIÁRIO DE OBRA")], [(72, 100, "x")]])
    r = ad.processar({"partes": [a, b], "papeis": NOMES, "marcar": [], "desmarcar": [], "mostrar": False,
                      "gerar": True})
    assert [(p["pagina"], p["motivo"]) for p in r["paginas"]] == [(1, "nome"), (2, "diario"), (3, None)]
    assert len(pypdf.PdfReader(io.BytesIO(r["pdf"])).pages) == 3


def test_pacote_acima_do_teto_de_paginas_e_recusado(monkeypatch):
    from app import leitura_pdf
    monkeypatch.setattr(ad, "TETO_PAGINAS", 2)
    with pytest.raises(leitura_pdf.TextoInadequado, match="3 páginas"):
        _processar(_pdf([[(1, 20, "a")], [(1, 20, "b")], [(1, 20, "c")]]))
