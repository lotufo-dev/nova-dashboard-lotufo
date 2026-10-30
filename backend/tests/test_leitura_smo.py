"""Leitor da capa do boletim do SMO (#285). Fixtures sinteticas no leiaute das capas reais (nomes e numeros
trocados): texto do pypdf com rotulo e valor em linhas separadas, e texto do OCR com os pares na mesma linha."""
import pathlib

from app import leitura_pdf, leitura_smo

FIX = pathlib.Path(__file__).parent / "fixtures" / "smo"


def _txt(nome):
    return (FIX / nome).read_text(encoding="utf-8")


def test_capa_de_texto_aprovada_com_oficio_na_frente():
    r = leitura_smo.ler(_txt("capa-texto-aprovada.txt"))
    assert r["ok"] and r["motivo"] is None
    assert r["campos"] == {
        "numero": 7, "tipo_medicao": "provisoria", "situacao": "APROVADA",
        "periodo": ("2026-03-01", "2026-03-31"), "data_realizacao": "2026-04-14",
        "valor_centavos": 123456789, "reajuste_centavos": 9876543, "total_centavos": 133333332,
        "acumulado_pi_centavos": 876543210, "acumulado_reajuste_centavos": 45678901,
        "acumulado_total_centavos": 922222111,
        "vigencia_fim": "2027-02-24", "execucao_fim": "2026-11-06", "dias_paralisados": 12,
    }
    assert r["faltando"] == [] and r["avisos"] == []


def test_valores_sao_centavos_inteiros():
    campos = leitura_smo.ler(_txt("capa-texto-aprovada.txt"))["campos"]
    for nome, valor in campos.items():
        if nome.endswith("_centavos"):
            assert type(valor) is int, nome


def test_medicao_final_vale_o_ordinal_e_desconto_vira_aviso():
    r = leitura_smo.ler(_txt("capa-texto-final-descontos.txt"))
    assert r["ok"]
    c = r["campos"]
    # "29 - 32ª Medição Final": 29 e' o sequencial do SMO, a medicao e' a 32ª
    assert (c["numero"], c["tipo_medicao"]) == (32, "final")
    assert (c["valor_centavos"], c["reajuste_centavos"], c["total_centavos"]) == (50000000, 2000000, 51975000)
    assert (c["acumulado_pi_centavos"], c["acumulado_total_centavos"]) == (300000000, 314850000)
    assert c["dias_paralisados"] == 4                 # rotulo sem ":" nesta capa
    assert (c["vigencia_fim"], c["execucao_fim"]) == ("2026-06-30", "2025-11-05")
    assert r["avisos"] == ["presente medição: a capa tem acréscimos ou descontos além dos preços iniciais e do "
                           "reajustamento; confira o valor da nota"]


def test_capa_sem_situacao_aprovada_e_recusada():
    texto = _txt("capa-texto-aprovada.txt").replace("Provisória - APROVADA", "Provisória - EM ANÁLISE")
    r = leitura_smo.ler(texto)
    assert not r["ok"] and r["motivo"] == "nao-aprovada"
    assert r["campos"]["situacao"] == "EM ANÁLISE"
    assert r["campos"]["valor_centavos"] == 123456789     # o lido volta, mas nao e' proposta


def test_campos_ausentes_voltam_na_lista_e_o_resto_e_lido():
    texto = _txt("capa-texto-aprovada.txt").replace("Data de realização\n: 14/04/2026\n", "") \
        .replace("Faturamento realizado da presente medição", "Faturamento da medição")
    r = leitura_smo.ler(texto)
    assert not r["ok"] and r["motivo"] == "campos-ausentes:data_realizacao,valor_centavos"
    assert r["faltando"] == ["data_realizacao", "valor_centavos", "reajuste_centavos", "total_centavos"]
    assert r["campos"]["numero"] == 7 and r["campos"]["acumulado_pi_centavos"] == 876543210
    assert None not in r["campos"].values()


def test_data_que_nao_existe_nao_e_proposta():
    texto = _txt("capa-texto-aprovada.txt").replace(": 14/04/2026", ": 31/02/2026")
    r = leitura_smo.ler(texto)
    assert r["motivo"] == "campos-ausentes:data_realizacao" and "data_realizacao" not in r["campos"]


def test_reajustamento_negativo():
    texto = _txt("capa-texto-aprovada.txt").replace("98.765,43\nTotal :\n1.333.333,32",
                                                    "-34.567,89\nTotal :\n1.200.000,00")
    c = leitura_smo.ler(texto)["campos"]
    assert (c["valor_centavos"], c["reajuste_centavos"], c["total_centavos"]) == (123456789, -3456789, 120000000)


def test_texto_vazio_e_texto_que_nao_e_capa():
    assert leitura_smo.ler("")["motivo"] == "sem-texto"
    assert leitura_smo.ler("  \n ")["motivo"] == "sem-texto"
    nota = (pathlib.Path(__file__).parent / "fixtures" / "nfse" / "3105-cultural-mtpar.txt").read_text(encoding="utf-8")
    r = leitura_smo.ler(nota)
    assert (r["ok"], r["motivo"], r["campos"]) == (False, "capa-nao-encontrada", {})
    assert r["faltando"] == list(leitura_smo.CAMPOS)


def test_capa_lida_por_ocr_e_soma_que_nao_fecha_nao_e_proposta():
    r = leitura_smo.ler(_txt("capa-ocr.txt"), ocr=True)
    assert r["ok"]
    c = r["campos"]
    assert (c["numero"], c["data_realizacao"], c["periodo"]) == (8, "2026-04-02", ("2026-03-01", "2026-03-31"))
    assert (c["valor_centavos"], c["reajuste_centavos"], c["total_centavos"]) == (65432100, 3210050, 68642150)
    assert (c["vigencia_fim"], c["execucao_fim"], c["dias_paralisados"]) == ("2027-06-06", "2027-03-24", 0)
    # o OCR perdeu um digito do total acumulado: o bloco inteiro fica para a pessoa
    assert r["faltando"] == ["acumulado_pi_centavos", "acumulado_reajuste_centavos", "acumulado_total_centavos"]
    assert r["avisos"] == ["acumulado: os valores da capa não fecham com o total impresso; confira e digite os valores"]


def test_no_ocr_ordinal_diferente_do_sequencial_avisa():
    texto = _txt("capa-ocr.txt").replace("8-8º Medição", "8-82 Medição")
    r = leitura_smo.ler(texto, ocr=True)
    assert r["campos"]["numero"] == 82
    assert any("sequencial do SMO" in a for a in r["avisos"])
    # no texto do pypdf a diferenca e' comum (medicao reapresentada) e nao avisa
    assert leitura_smo.ler(_txt("capa-texto-final-descontos.txt"))["campos"]["numero"] == 32


# --- ler_pdf: PDF de texto e PDF imagem --------------------------------------------------------------------

def test_pdf_de_texto_le_as_duas_primeiras_paginas_sem_ocr(monkeypatch):
    oficio, capa = _txt("capa-texto-aprovada.txt").split("SINFRA - Secretaria de Estado de Infraestrutura e Logística\n")
    monkeypatch.setattr(leitura_pdf, "primeiras_paginas_com_limite", lambda pdf: [oficio, capa])

    def ocr(*a, **k):
        raise AssertionError("PDF com texto nao vai ao OCR")
    monkeypatch.setattr(leitura_pdf, "texto_por_ocr_com_limite", ocr)
    r = leitura_smo.ler_pdf(b"%PDF-")
    assert r["ok"] and r["fonte"] == "texto" and r["campos"]["valor_centavos"] == 123456789


def test_pdf_imagem_vai_ao_ocr_do_pacote(monkeypatch):
    chamadas = []
    monkeypatch.setattr(leitura_pdf, "primeiras_paginas_com_limite", lambda pdf: ["", ""])

    def ocr(pdf, pacote=False):
        chamadas.append(pacote)
        return _txt("capa-ocr.txt")
    monkeypatch.setattr(leitura_pdf, "texto_por_ocr_com_limite", ocr)
    r = leitura_smo.ler_pdf(b"%PDF-")
    assert chamadas == [True]
    assert r["ok"] and r["fonte"] == "ocr" and r["campos"]["valor_centavos"] == 65432100
    assert "acumulado_total_centavos" in r["faltando"]


def test_pdf_imagem_sem_ocr_devolve_vazio_para_digitar(monkeypatch):
    monkeypatch.setattr(leitura_pdf, "primeiras_paginas_com_limite", lambda pdf: ["", ""])
    r = leitura_smo.ler_pdf(b"%PDF-")          # o conftest desliga o OCR
    assert (r["ok"], r["motivo"], r["fonte"], r["campos"]) == (False, "sem-texto", None, {})
    assert r["faltando"] == list(leitura_smo.CAMPOS)


def test_ocr_que_nao_acha_capa_fica_com_o_resultado_do_texto(monkeypatch):
    monkeypatch.setattr(leitura_pdf, "primeiras_paginas_com_limite", lambda pdf: ["Ofício de encaminhamento", ""])
    monkeypatch.setattr(leitura_pdf, "texto_por_ocr_com_limite", lambda pdf, pacote=False: "texto qualquer")
    r = leitura_smo.ler_pdf(b"%PDF-")
    assert (r["ok"], r["motivo"], r["fonte"]) == (False, "capa-nao-encontrada", None)


def _pdf_paginas(textos: list[str]) -> bytes:
    """PDF com uma pagina por texto (uma linha cada), fonte com WinAnsiEncoding para os acentos sairem no pypdf.
    Montado a mao como o `_pdf_com_texto` do conftest, com o xref de offsets reais."""
    n = len(textos)
    objetos = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % (4 + 2 * i) for i in range(n)), n),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    for i, texto in enumerate(textos):
        escapado = texto.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        fluxo = f"BT /F1 6 Tf 20 700 Td ({escapado}) Tj ET".encode("latin-1")
        objetos.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
                       b"/Resources << /Font << /F1 3 0 R >> >> >>" % (5 + 2 * i))
        objetos.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(fluxo), fluxo))
    saida = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, corpo in enumerate(objetos, start=1):
        offsets.append(len(saida))
        saida += b"%d 0 obj\n" % i + corpo + b"\nendobj\n"
    inicio_xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    for off in offsets:
        saida += b"%010d 00000 n \n" % off
    saida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, inicio_xref)
    return bytes(saida)


def test_pdf_de_verdade_le_a_capa_da_pagina_2_e_ignora_a_3():
    """Pacote com oficio na p. 1, capa na p. 2 e, na p. 3, outra capa: so' as duas primeiras paginas contam."""
    oficio, capa = _txt("capa-texto-aprovada.txt").split("SINFRA - Secretaria de Estado de Infraestrutura e Logística\n")
    outra = _txt("capa-texto-final-descontos.txt")
    pdf = _pdf_paginas([oficio.replace("\n", " "), capa.replace("\n", " "), outra.replace("\n", " ")])
    r = leitura_smo.ler_pdf(pdf)
    assert r["ok"] and r["fonte"] == "texto"
    assert (r["campos"]["numero"], r["campos"]["valor_centavos"]) == (7, 123456789)


def test_pdf_de_verdade_com_a_capa_so_na_pagina_3_nao_e_lido():
    pdf = _pdf_paginas(["Ofício", "Resumo", _txt("capa-texto-aprovada.txt").replace("\n", " ")])
    r = leitura_smo.ler_pdf(pdf)
    assert (r["ok"], r["motivo"], r["fonte"]) == (False, "capa-nao-encontrada", None)
