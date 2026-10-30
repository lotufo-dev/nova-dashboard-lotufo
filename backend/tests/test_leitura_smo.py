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


def test_medicao_final_vale_o_ordinal_e_desconto_sai_em_campo_proprio():
    r = leitura_smo.ler(_txt("capa-texto-final-descontos.txt"))
    assert r["ok"]
    c = r["campos"]
    # "29 - 32ª Medição Final": 29 e' o sequencial do SMO, a medicao e' a 32ª
    assert (c["numero"], c["tipo_medicao"]) == (32, "final")
    assert (c["valor_centavos"], c["reajuste_centavos"], c["total_centavos"]) == (50000000, 2000000, 51975000)
    assert c["descontos_centavos"] == 25000 and "acrescimos_centavos" not in c      # a linha nao vem na presente
    assert (c["acumulado_pi_centavos"], c["acumulado_total_centavos"]) == (300000000, 314850000)
    assert (c["acumulado_acrescimos_centavos"], c["acumulado_descontos_centavos"]) == (0, 150000)   # "-1.500,00"
    assert c["dias_paralisados"] == 4                 # rotulo sem ":" nesta capa
    assert (c["vigencia_fim"], c["execucao_fim"]) == ("2026-06-30", "2025-11-05")
    assert r["faltando"] == []                        # os opcionais nao entram em "faltando"
    assert r["avisos"] == ["presente medição: a capa tem acréscimos ou descontos além dos preços iniciais e do "
                           "reajustamento; confira o valor da nota"]


def test_capa_sem_opcionais_nao_os_inventa():
    c = leitura_smo.ler(_txt("capa-texto-aprovada.txt"))["campos"]
    assert not set(leitura_smo.CAMPOS_OPCIONAIS) & set(c)


def test_capa_sem_situacao_aprovada_e_recusada():
    texto = _txt("capa-texto-aprovada.txt").replace("Provisória - APROVADA", "Provisória - EM ANÁLISE")
    r = leitura_smo.ler(texto)
    assert not r["ok"] and r["motivo"] == "nao-aprovada"
    assert r["campos"]["situacao"] == "EM ANALISE"       # o leitor compara sem acento
    assert r["campos"]["valor_centavos"] == 123456789     # o lido volta, mas nao e' proposta


def test_situacao_que_so_comeca_por_aprovada_e_recusada():
    texto = _txt("capa-texto-aprovada.txt").replace("Provisória - APROVADA", "Provisória - APROVADA COM RESSALVAS")
    r = leitura_smo.ler(texto)
    assert (r["ok"], r["motivo"], r["campos"]["situacao"]) == (False, "nao-aprovada", "APROVADA COM RESSALVAS")


def test_sem_o_rotulo_tipo_depois_da_situacao_nao_e_capa():
    """O "Tipo" e' o unico fim da situacao (vem em todas as capas reais): sem ele, nada emenda o texto seguinte."""
    texto = _txt("capa-texto-aprovada.txt").replace("APROVADA\nTipo\n: Parcial", "APROVADA\nRESUMO FINANCEIRO")
    assert leitura_smo.ler(texto)["motivo"] == "capa-nao-encontrada"


def test_sobra_depois_da_situacao_no_texto():
    r = leitura_smo.ler(_txt("capa-texto-aprovada.txt").replace("APROVADA\nTipo", "APROVADA.\nTipo"))
    assert r["ok"] and r["campos"]["situacao"] == "APROVADA"


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


def test_realizacao_antes_do_fim_do_periodo_avisa_no_texto():
    texto = _txt("capa-texto-aprovada.txt").replace(": 14/04/2026", ": 14/03/2026")
    r = leitura_smo.ler(texto)
    assert r["ok"] and r["campos"]["data_realizacao"] == "2026-03-14"
    assert r["avisos"] == ["a data de realização é anterior ao fim do período da medição; confira a data"]


def test_reajustamento_negativo():
    texto = _txt("capa-texto-aprovada.txt").replace("98.765,43\nTotal :\n1.333.333,32",
                                                    "-34.567,89\nTotal :\n1.200.000,00")
    c = leitura_smo.ler(texto)["campos"]
    assert (c["valor_centavos"], c["reajuste_centavos"], c["total_centavos"]) == (123456789, -3456789, 120000000)


def test_primeira_medicao_presente_igual_ao_acumulado_e_proposta():
    texto = _txt("capa-texto-aprovada.txt").replace("8.765.432,10", "1.234.567,89").replace("9.222.221,11", "1.234.567,89") \
        .replace("456.789,01", "0,00").replace("98.765,43", "0,00").replace("1.333.333,32", "1.234.567,89")
    r = leitura_smo.ler(texto)
    assert r["ok"]
    c = r["campos"]
    assert (c["valor_centavos"], c["reajuste_centavos"], c["total_centavos"]) == (123456789, 0, 123456789)
    assert (c["acumulado_pi_centavos"], c["acumulado_reajuste_centavos"], c["acumulado_total_centavos"]) == \
        (123456789, 0, 123456789)


def test_acrescimo_e_desconto_da_presente_que_o_acumulado_nao_tem_nao_sao_propostos():
    # presente com acrescimo 100 e desconto 100 (a soma fecha), acumulado sem as duas linhas (zero)
    texto = _txt("capa-texto-aprovada.txt").replace("98.765,43\nTotal :\n1.333.333,32",
                                                    "98.765,43\nAcréscimos :\n100,00\nDescontos :\n100,00\n"
                                                    "Total :\n1.333.333,32")
    r = leitura_smo.ler(texto)
    assert "valor_centavos" not in r["campos"] and "descontos_centavos" not in r["campos"]
    assert "os valores da presente medição passam do acumulado; confira e digite os valores" in r["avisos"]


def test_presente_maior_que_o_acumulado_nao_e_proposta():
    # o mesmo digito trocado no PI e no total da presente: a soma fecha, mas passa do acumulado (8.765.432,10)
    texto = _txt("capa-texto-aprovada.txt").replace("1.234.567,89", "9.234.567,89").replace("1.333.333,32",
                                                                                              "9.333.333,32")
    r = leitura_smo.ler(texto)
    assert r["motivo"] == "campos-ausentes:valor_centavos"
    assert "valor_centavos" not in r["campos"] and "acumulado_pi_centavos" not in r["campos"]
    assert r["avisos"] == ["os valores da presente medição passam do acumulado; confira e digite os valores"]


def test_bloco_de_valores_irreconhecivel_avisa():
    texto = _txt("capa-texto-aprovada.txt").replace("Preços iniciais :\n1.234.567,89", "Preços iniciais :\n1.234.567")
    r = leitura_smo.ler(texto)
    assert r["motivo"] == "campos-ausentes:valor_centavos"
    assert r["avisos"] == ["presente medição: a capa traz o bloco, mas os valores não foram reconhecidos; "
                           "digite os valores"]


def test_texto_vazio_e_texto_que_nao_e_capa():
    assert leitura_smo.ler("")["motivo"] == "sem-texto"
    assert leitura_smo.ler("  \n ")["motivo"] == "sem-texto"
    nota = (pathlib.Path(__file__).parent / "fixtures" / "nfse" / "3105-cultural-mtpar.txt").read_text(encoding="utf-8")
    r = leitura_smo.ler(nota)
    assert (r["ok"], r["motivo"], r["campos"]) == (False, "capa-nao-encontrada", {})
    assert r["faltando"] == list(leitura_smo.CAMPOS)


def test_certificado_do_docusign_que_lista_a_capa_nao_e_capa():
    certificado = ("Resumo do certificado Assunto: Complete com o Docusign: 02 - Relatório de Capa da Medição.pdf "
                   "Documentos: 7 - 7ª Medição Provisória - APROVADA Tipo de assinatura: eletrônica")
    assert leitura_smo.ler(certificado)["motivo"] == "capa-nao-encontrada"


def test_titulo_da_capa_so_no_rodape_ainda_e_capa():
    """O pypdf pode por o "Relatório de Capa da Medição" so' no fim do texto da pagina (capa do BRT)."""
    texto = _txt("capa-texto-final-descontos.txt").split("\n", 1)[1]       # sem o "Capa da Medição" do topo
    assert leitura_smo.ler(texto)["ok"]


# --- OCR -----------------------------------------------------------------------------------------------------

def _ocr_bom():
    """A capa do OCR com o total acumulado certo (a fixture perdeu um digito de proposito)."""
    return _txt("capa-ocr.txt").replace("Total: 564.210,00", "Total: 5.642.100,00")


def _ler_ocr(texto: str) -> dict:
    """Como o `ler_pdf` faz: a p. 1 (oficio) e' o contexto, a p. 2 e' a capa."""
    oficio, capa = texto.split("Período: 01/03/2026 a 31/03/2026.\n", 1)
    return leitura_smo.ler(capa, ocr=True, contexto=oficio)


_AVISO_OCR = "campos lidos por OCR: confira cada um contra o PDF antes de aceitar"


def test_capa_lida_por_ocr_sai_com_aviso_de_conferencia():
    r = _ler_ocr(_ocr_bom())
    assert r["ok"]
    c = r["campos"]
    assert (c["numero"], c["data_realizacao"], c["periodo"]) == (8, "2026-04-02", ("2026-03-01", "2026-03-31"))
    assert (c["valor_centavos"], c["reajuste_centavos"], c["total_centavos"]) == (65432100, 3210050, 68642150)
    assert c["acumulado_total_centavos"] == 564210000
    assert (c["vigencia_fim"], c["execucao_fim"], c["dias_paralisados"]) == ("2027-06-06", "2027-03-24", 0)
    # erro sistematico do OCR (o mesmo digito trocado em todos os valores) fecha a soma: o aviso e' obrigatorio
    assert r["avisos"] == [_AVISO_OCR]


def test_ocr_sem_bloco_financeiro_lido_ainda_avisa():
    texto = _ocr_bom().replace("Total: 5.642.100,00", "Total: 1,00").replace("Total: 686.421,50", "Total: 1,00")
    r = _ler_ocr(texto)
    assert "valor_centavos" not in r["campos"] and r["campos"]["numero"] == 8
    assert r["avisos"][-1] == _AVISO_OCR


def test_ocr_com_acumulado_que_nao_fecha_nao_propoe_a_presente():
    r = _ler_ocr(_txt("capa-ocr.txt"))
    assert r["motivo"] == "campos-ausentes:valor_centavos"
    assert not {"valor_centavos", "acumulado_pi_centavos"} & set(r["campos"])
    assert r["avisos"] == ["acumulado: os valores da capa não fecham com o total impresso; confira e digite os valores",
                           "sem o acumulado lido não há como conferir os valores da presente medição; "
                           "digite os valores", _AVISO_OCR]


def test_ocr_que_emenda_os_rotulos_nao_poe_o_acumulado_na_presente():
    texto = _ocr_bom().replace("Faturamento realizado acumulado\n", "Faturamento realizado acumulado\n"
                                                                   "Faturamento realizado da presente medição\n", 1)
    texto = texto.replace("Total: 5.642.100,00\nFaturamento realizado da presente medição\n", "Total: 5.642.100,00\n")
    r = _ler_ocr(texto)
    assert "valor_centavos" not in r["campos"]


def test_ocr_numero_so_com_o_extenso_de_outra_pagina():
    # sequencial e ordinal lidos errados juntos ("8 - 8º" -> "82 - 82º"): o "(oitava)" do oficio nao confirma
    r = _ler_ocr(_ocr_bom().replace("8-8º Medição", "82-82º Medição"))
    assert r["motivo"] == "campos-ausentes:numero" and "numero" not in r["campos"]
    assert r["avisos"][0] == ("a leitura por OCR traz a 82ª medição, sem o número por extenso que a confirme; "
                              "confira e digite o número")
    capa = _ocr_bom().split("Período: 01/03/2026 a 31/03/2026.\n", 1)[1]
    # capa sozinha, sem oficio: nao ha confirmacao, a pessoa digita
    assert "numero" not in leitura_smo.ler(capa, ocr=True)["campos"]
    # o extenso na propria capa (OCR que duplicou o texto) nao confirma o proprio erro
    duplicada = capa.replace("Observação :", "Observação : 8ª (oitava) Medição")
    assert "numero" not in leitura_smo.ler(duplicada, ocr=True)["campos"]
    assert _ler_ocr(_ocr_bom())["campos"]["numero"] == 8


def test_ordinal_por_extenso():
    assert leitura_smo._ordinal_por_extenso("Vigésima Sexta") == 26
    assert leitura_smo._ordinal_por_extenso("oitava") == 8
    assert leitura_smo._ordinal_por_extenso("trigésimo segundo") == 32
    assert leitura_smo._ordinal_por_extenso("Vinte") is None


def test_ocr_com_ordinal_em_letra_e_travessao():
    texto = _ocr_bom().replace("8-8º Medição Provisória - APROVADA", "8 — 8a Medição Provisória — APROVADA")
    r = _ler_ocr(texto)
    assert r["ok"] and r["campos"]["numero"] == 8


def test_ocr_sem_acento_e_em_outra_caixa():
    texto = _ocr_bom().replace("Relatório de Capa da Medição", "RELATORIO DE CAPA DA MEDICAO") \
        .replace("Capa da Medição Reajustada", "CAPA DA MEDICAO REAJUSTADA") \
        .replace("8-8º Medição Provisória", "8-8º MEDICAO PROVISORIA").replace("RESUMO FINANCEIRO", "Resumo Financeiro") \
        .replace("Preços iniciais", "PRECOS INICIAIS").replace("Data de realização", "Data de realizacao")
    r = _ler_ocr(texto)
    assert r["ok"] and (r["campos"]["numero"], r["campos"]["valor_centavos"]) == (8, 65432100)


def test_ocr_sobra_depois_da_situacao_nao_recusa():
    for sobra in ("APROVADA.", "APROVADA |"):
        r = _ler_ocr(_ocr_bom().replace("APROVADA Tipo", sobra + " Tipo"))
        assert r["ok"] and r["campos"]["situacao"] == "APROVADA", sobra


def test_ocr_situacao_com_minuscula_cai_para_digitacao():
    r = _ler_ocr(_ocr_bom().replace("APROVADA Tipo", "Aprovada Tipo"))
    assert (r["ok"], r["motivo"], r["campos"]) == (False, "capa-nao-encontrada", {})


def test_ocr_realizacao_antes_do_fim_do_periodo_nao_e_proposta():
    r = _ler_ocr(_ocr_bom().replace("Data de realização: 02/04/2026", "Data de realização: 02/04/2025"))
    assert r["motivo"] == "campos-ausentes:data_realizacao" and "data_realizacao" not in r["campos"]
    assert "a data de realização é anterior ao fim do período da medição; confira a data" in r["avisos"]


def test_ocr_realizacao_sem_periodo_lido_nao_e_proposta():
    r = _ler_ocr(_ocr_bom().replace("Período da medição : 01/03/2026 a 31/03/2026", "Período da medição : 01/03/2026"))
    assert "periodo" not in r["campos"] and "data_realizacao" not in r["campos"]
    assert "sem o período da medição lido não há como conferir a data de realização; digite a data" in r["avisos"]


# --- ler_pdf: PDF de texto e PDF imagem --------------------------------------------------------------------

def _paginas_texto():
    return _txt("capa-texto-aprovada.txt").split("SINFRA - Secretaria de Estado de Infraestrutura e Logística\n")


def _paginas_ocr():
    oficio, capa = _ocr_bom().split("Período: 01/03/2026 a 31/03/2026.\n", 1)
    return [oficio, capa]


def _sem_ocr(*a, **k):
    raise AssertionError("nao devia ir ao OCR")


def test_pdf_de_texto_le_a_capa_sem_ocr(monkeypatch):
    monkeypatch.setattr(leitura_pdf, "primeiras_paginas_com_limite", lambda pdf: _paginas_texto())
    monkeypatch.setattr(leitura_pdf, "paginas_por_ocr_com_limite", _sem_ocr)
    r = leitura_smo.ler_pdf(b"%PDF-")
    assert r["ok"] and r["fonte"] == "texto" and r["campos"]["valor_centavos"] == 123456789


def test_campos_saem_so_da_pagina_da_capa(monkeypatch):
    ficha = "Relatório de Ficha do Contrato Analítica Período de vigência : 01/01/2020 a 01/01/2021"
    monkeypatch.setattr(leitura_pdf, "primeiras_paginas_com_limite", lambda pdf: [ficha, _paginas_texto()[1]])
    r = leitura_smo.ler_pdf(b"%PDF-")
    assert r["ok"] and r["campos"]["vigencia_fim"] == "2027-02-24"


def test_marcas_da_capa_espalhadas_em_paginas_diferentes_nao_fazem_capa(monkeypatch):
    certificado = ("Resumo do certificado Assunto: Complete com o Docusign: 02 - Relatório de Capa da Medição.pdf "
                   "7 - 7ª Medição Provisória - APROVADA Tipo de assinatura: eletrônica")
    relatorio = "Relatório de Resumo da Medição RESUMO FINANCEIRO Data de realização : 14/04/2026"
    monkeypatch.setattr(leitura_pdf, "primeiras_paginas_com_limite", lambda pdf: [certificado, relatorio])
    assert leitura_smo.e_capa(certificado + " " + relatorio)          # juntas, teriam as tres marcas
    r = leitura_smo.ler_pdf(b"%PDF-")
    assert (r["ok"], r["motivo"], r["campos"], r["fonte"]) == (False, "capa-nao-encontrada", {}, None)


def test_pdf_imagem_vai_ao_ocr_do_pacote(monkeypatch):
    monkeypatch.setattr(leitura_pdf, "primeiras_paginas_com_limite", lambda pdf: ["", ""])
    monkeypatch.setattr(leitura_pdf, "paginas_por_ocr_com_limite", lambda pdf: _paginas_ocr())
    r = leitura_smo.ler_pdf(b"%PDF-")
    assert r["ok"] and r["fonte"] == "ocr"
    assert (r["campos"]["numero"], r["campos"]["valor_centavos"]) == (8, 65432100)    # numero confirmado pelo oficio


def test_pdf_imagem_sem_ocr_devolve_vazio_para_digitar(monkeypatch):
    monkeypatch.setattr(leitura_pdf, "primeiras_paginas_com_limite", lambda pdf: ["", ""])
    r = leitura_smo.ler_pdf(b"%PDF-")          # o conftest desliga o OCR
    assert (r["ok"], r["motivo"], r["fonte"], r["campos"]) == (False, "sem-texto", None, {})
    assert r["faltando"] == list(leitura_smo.CAMPOS)


def test_pdf_que_o_pypdf_nao_abre_ainda_vai_ao_ocr(monkeypatch):
    def recusa(pdf):
        raise ValueError("PDF inválido (PdfReadError): xref")
    monkeypatch.setattr(leitura_pdf, "primeiras_paginas_com_limite", recusa)
    monkeypatch.setattr(leitura_pdf, "paginas_por_ocr_com_limite", lambda pdf: _paginas_ocr())
    r = leitura_smo.ler_pdf(b"%PDF-")
    assert r["ok"] and r["fonte"] == "ocr"
    monkeypatch.setattr(leitura_pdf, "paginas_por_ocr_com_limite", lambda pdf: None)
    r = leitura_smo.ler_pdf(b"%PDF-")
    assert (r["motivo"], r["fonte"]) == ("sem-texto", None)


def test_pdf_recusado_pela_guarda_ou_pelo_prazo_nao_vai_ao_ocr(monkeypatch):
    def recusa(pdf):
        raise leitura_pdf.TextoInadequado("O PDF demorou mais de 60 s para ser lido")
    monkeypatch.setattr(leitura_pdf, "primeiras_paginas_com_limite", recusa)
    monkeypatch.setattr(leitura_pdf, "paginas_por_ocr_com_limite", _sem_ocr)
    r = leitura_smo.ler_pdf(b"%PDF-")
    assert (r["ok"], r["motivo"], r["fonte"]) == (False, "pdf-recusado", None)
    assert r["avisos"] == ["O PDF demorou mais de 60 s para ser lido"]


def test_ocr_que_nao_acha_capa_fica_com_o_resultado_do_texto(monkeypatch):
    monkeypatch.setattr(leitura_pdf, "primeiras_paginas_com_limite", lambda pdf: ["Ofício de encaminhamento", ""])
    monkeypatch.setattr(leitura_pdf, "paginas_por_ocr_com_limite", lambda pdf: ["texto qualquer", ""])
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
