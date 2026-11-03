"""Leitura da planilha de previsao de reajuste do pleito (issue #272; spec 2026-10-20 §2.2 e §4 item 1).

As planilhas sao sinteticas: o mesmo desenho do modelo "Mem. e Cron. - Prev. de Reajuste" (aba Resumo, cabecalho
MEDICAO | PERIODO | VALORES e, embaixo, A PI | INDICE | REAJUSTE | TOTAL), com numeros inventados."""
import io

import openpyxl
import pytest

from app import leitura_planilha_reajuste as leitura


def planilha_modelo(linhas=None, coluna_inicial=1, com_indice=True, outras_abas=("CRONOGRAMA",)) -> bytes:
    """Planilha no desenho do modelo. `linhas`: (medicao, periodo, reajuste em reais)."""
    linhas = linhas if linhas is not None else [
        ("1ª Medição ", "23/02/2026 a 31/03/2026", 1234.56),
        ("2ª Medição", "01/04/2026 a 30/04/2026", 2000.0),
        ("3ª Medição", "01/05/2026 a 31/05/2026", 0.1),
    ]
    wb = openpyxl.Workbook()
    wb.active.title = outras_abas[0] if outras_abas else "Plan1"
    ws = wb.create_sheet("Resumo") if outras_abas else wb.active
    if not outras_abas:
        ws.title = "Resumo"
    c = coluna_inicial
    ws.cell(2, c, "INCC DE MARÇO DE 2023 - DATA BASE DA PROPOSTA")
    ws.cell(6, c, "MEDIÇÃO"); ws.cell(6, c + 1, "PERÍODO"); ws.cell(6, c + 2, "VALORES")
    sub = ["A PI", "ÍNDICE", "REAJUSTE", "TOTAL"] if com_indice else ["A PI", "REAJUSTE", "TOTAL"]
    for i, t in enumerate(sub):
        ws.cell(7, c + 2 + i, t)
    r = 8
    for med, per, reaj in linhas:
        ws.cell(r, c, med); ws.cell(r, c + 1, per)
        ws.cell(r, c + 2, 100000.0)
        ws.cell(r, c + 2 + sub.index("REAJUSTE"), reaj)
        r += 1
    ws.cell(r + 1, c, "TOTAIS")
    ws.cell(r + 1, c + 2 + sub.index("REAJUSTE"), 99999.99)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_planilha_do_modelo_vira_previsao_por_competencia():
    linhas = leitura.ler(planilha_modelo())
    assert [(x["competencia"], x["valor_centavos"]) for x in linhas] == [
        ("2026-03", 123456), ("2026-04", 200000), ("2026-05", 10)]
    # o rotulo da medicao e o periodo vao junto, para a pessoa conferir com a planilha aberta
    assert linhas[0]["medicao"] == "1ª Medição" and linhas[0]["periodo"] == "23/02/2026 a 31/03/2026"


def test_coluna_inicial_e_indice_variam_entre_as_obras():
    """Uma obra comeca na coluna A com INDICE; outra na B, sem INDICE (as duas existem nos pleitos de 2026)."""
    linhas = leitura.ler(planilha_modelo(coluna_inicial=2, com_indice=False))
    assert [x["valor_centavos"] for x in linhas] == [123456, 200000, 10]


def test_float_da_planilha_vira_centavos_sem_erro_de_arredondamento():
    linhas = leitura.ler(planilha_modelo([("1ª Medição", "01/04/2026 a 30/04/2026", 4.35),
                                          ("2ª Medição", "01/05/2026 a 31/05/2026", 0.29),
                                          ("3ª Medição", "01/06/2026 a 30/06/2026", -15.07)]))
    # 4.35 * 100 em float da' 434.99999...; truncar daria 434 e 28 (0.29 * 100 = 28.99999...). E indice
    # deflacionario da' reajuste negativo, que tambem tem de sair com o centavo certo (-15.07 * 100 = -1507.0000...1)
    assert [x["valor_centavos"] for x in linhas] == [435, 29, -1507]


def test_formula_sem_valor_calculado_nao_some_em_silencio():
    """Arquivo salvo sem o valor das formulas (gerado por programa): a celula le vazia, mas nao e' vazia."""
    wb = openpyxl.load_workbook(io.BytesIO(planilha_modelo(outras_abas=())))
    wb["Resumo"]["E9"] = "=C9*0.05"                 # REAJUSTE da 2a medicao vira formula, sem cache
    buf = io.BytesIO(); wb.save(buf)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(buf.getvalue())
    assert "2ª Medição tem fórmula sem o valor calculado" in e.value.motivo
    # periodo em formula sem cache (o modelo monta o periodo com TEXT(...)) tambem
    wb["Resumo"]["E9"] = 2000.0
    wb["Resumo"]["B10"] = '=TEXT(A1,"dd/mm/aaaa")'
    buf = io.BytesIO(); wb.save(buf)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(buf.getvalue())
    assert "3ª Medição tem fórmula sem o valor calculado" in e.value.motivo


def _trocar_no_xml_da_aba(dados: bytes, antes: bytes, depois: bytes) -> bytes:
    import zipfile
    origem, destino = io.BytesIO(dados), io.BytesIO()
    with zipfile.ZipFile(origem) as z, zipfile.ZipFile(destino, "w") as novo:
        for item in z.infolist():
            conteudo = z.read(item.filename)
            if item.filename.startswith("xl/worksheets/"):
                assert antes in conteudo
                conteudo = conteudo.replace(antes, depois)
            novo.writestr(item, conteudo)
    return destino.getvalue()


def test_formula_que_da_texto_vazio_continua_vazia():
    """=SE(...;"";...) calculada: o Excel grava t="str" com <v></v>. E' vazia de verdade; reabrir e salvar nao
    mudaria nada, entao a planilha nao pode ser recusada por isso: a linha so' fica de fora."""
    wb = openpyxl.load_workbook(io.BytesIO(planilha_modelo(outras_abas=())))
    wb["Resumo"]["E9"] = '=IF(C9>0,"",1)'
    buf = io.BytesIO(); wb.save(buf)
    dados = _trocar_no_xml_da_aba(buf.getvalue(), b'<c r="E9"><f>', b'<c r="E9" t="str"><f>')
    assert [x["competencia"] for x in leitura.ler(dados)] == ["2026-03", "2026-05"]
    # a mesma formula sem nenhum <v> (nunca calculada) e' recusada
    sem_v = _trocar_no_xml_da_aba(dados, b'<v></v></c>', b'</c>')
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(sem_v)
    assert "2ª Medição tem fórmula sem o valor calculado" in e.value.motivo


def test_formatacao_distante_com_totais_perto_e_lida():
    """Aba formatada ate' a linha 8000 (a dimensao declarada vai la'), com o TOTAIS na linha 12: le normal."""
    wb = openpyxl.load_workbook(io.BytesIO(planilha_modelo(outras_abas=())))
    ws = wb["Resumo"]
    ws.cell(8000, 1).value = " "
    buf = io.BytesIO(); wb.save(buf)
    assert openpyxl.load_workbook(io.BytesIO(buf.getvalue()), read_only=True)["Resumo"].max_row == 8000
    assert len(leitura.ler(buf.getvalue())) == 3


def test_aba_sem_fim_nao_devolve_leitura_parcial(monkeypatch):
    monkeypatch.setattr(leitura, "MAX_VARRIDAS", 2)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(planilha_modelo())                 # 3 medicoes e o TOTAIS: passa do teto antes do fim
    assert "grande demais" in e.value.motivo


def _com_linhas_vazias(dados: bytes, de: int, quantas: int, colunas: int = 1, sem_totais: bool = False) -> bytes:
    """A planilha montada de proposito: `quantas` linhas vazias so' com formatacao, que comprimidas quase nao pesam
    (o .xlsx fica pequeno e a aba descompactada, enorme)."""
    if sem_totais:
        wb = openpyxl.load_workbook(io.BytesIO(dados))
        wb["Resumo"].delete_rows(12, 2)
        buf = io.BytesIO(); wb.save(buf); dados = buf.getvalue()
    letras = [openpyxl.utils.get_column_letter(c + 1) for c in range(colunas)]
    vazias = b"".join(b'<row r="%d">' % n + b"".join(b'<c r="%s%d" s="0"/>' % (x.encode(), n) for x in letras)
                      + b"</row>" for n in range(de, de + quantas))
    dados = _trocar_no_xml_da_aba(dados, b"</sheetData>", vazias + b"</sheetData>")
    # a dimensao declarada vai ate' a ultima linha (como o Excel grava a aba formatada)
    declarada = b'<dimension ref="A2:F10"/>' if sem_totais else b'<dimension ref="A2:F12"/>'
    return _trocar_no_xml_da_aba(dados, declarada, b'<dimension ref="A1:F%d"/>' % (de + quantas))


def test_planilha_pequena_com_a_aba_enorme_e_recusada_sem_ser_percorrida(monkeypatch):
    """Achado do revisor: um .xlsx de poucos KB com milhoes de linhas vazias comprimidas consumia 1 GB e 20 s. A aba
    descompactada acima do teto e' recusada antes da leitura (e o TOTAIS perto nao salva: o custo vem antes)."""
    monkeypatch.setattr(leitura, "MAX_BYTES_XML", 200_000)
    dados = _com_linhas_vazias(planilha_modelo(outras_abas=()), 20, 20_000)
    assert len(dados) < 150_000                      # o arquivo e' pequeno; a aba descompactada passa de 700 KB
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(dados)
    assert e.value.motivo == "a aba Resumo é grande demais para o modelo"


def test_parte_lida_inteira_acima_do_teto_e_recusada(monkeypatch):
    """Os estilos (e os textos compartilhados) o openpyxl le inteiros ao abrir: tambem tem teto descompactado."""
    import zipfile
    monkeypatch.setattr(leitura, "MAX_BYTES_XML", 50_000)
    origem, destino = io.BytesIO(planilha_modelo(outras_abas=())), io.BytesIO()
    with zipfile.ZipFile(origem) as z, zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as novo:
        for item in z.infolist():
            conteudo = z.read(item.filename)
            if item.filename == "xl/styles.xml":
                conteudo = conteudo.replace(b"</styleSheet>", b"<!--" + b"x" * 100_000 + b"--></styleSheet>")
            novo.writestr(item, conteudo)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(destino.getvalue())
    assert e.value.motivo == "a planilha é grande demais para o modelo"


def test_linhas_vazias_alem_do_teto_nao_sao_percorridas_nem_guardadas():
    """Sem TOTAIS e com 150 mil linhas vazias abaixo da tabela (dentro do teto de bytes): le as 3 medicoes, sem
    guardar a aba na memoria (antes, a conferencia de formulas guardava cada <row> e a memoria crescia com a aba)."""
    import tracemalloc
    dados = _com_linhas_vazias(planilha_modelo(outras_abas=()), 20, 150_000, sem_totais=True)
    tracemalloc.start()
    try:
        assert len(leitura.ler(dados)) == 3
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert pico < 15_000_000, pico


def test_dado_depois_do_teto_de_linhas_ainda_recusa(monkeypatch):
    """O teto de linhas nao vira leitura pela metade: valor depois dele recusa; so' formatacao, nao."""
    monkeypatch.setattr(leitura, "MAX_VARRIDAS", 50)
    base = planilha_modelo(outras_abas=())
    wb = openpyxl.load_workbook(io.BytesIO(base))
    wb["Resumo"].delete_rows(12, 2)
    wb["Resumo"].cell(500, 2, "01/09/2026 a 30/09/2026")
    wb["Resumo"].cell(501, 2, " ")                       # texto em branco nao e' dado
    buf = io.BytesIO(); wb.save(buf)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(buf.getvalue())
    assert "grande demais" in e.value.motivo
    assert len(leitura.ler(_com_linhas_vazias(base, 20, 200, sem_totais=True))) == 3


def _refazer(dados: bytes, trocar=None, novas=()) -> bytes:
    """Remonta o zip: `trocar(nome, conteudo)` devolve o conteudo novo (ou None para tirar a entrada); `novas` sao
    (nome, conteudo) acrescentados."""
    import zipfile
    origem, destino = io.BytesIO(dados), io.BytesIO()
    with zipfile.ZipFile(origem) as z, zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as novo:
        for item in z.infolist():
            conteudo = z.read(item.filename)
            conteudo = trocar(item.filename, conteudo) if trocar else conteudo
            if conteudo is not None:
                novo.writestr(item.filename, conteudo)
        for nome, conteudo in novas:
            novo.writestr(nome, conteudo)
    return destino.getvalue()


_SST = ('<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<si><t>Resumo</t></si>{}</sst>')
_CT_SST = (b'<Override PartName="/%s" '
           b'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')


@pytest.mark.parametrize("nome", ["xl/s.bin", "xl/worksheets/sharedStrings.xml"])
def test_parte_renomeada_conta_no_teto(monkeypatch, nome):
    """Achado do revisor: o openpyxl acha os textos compartilhados pelo [Content_Types].xml, nao pelo nome. Com o
    nome trocado (ou posto entre as abas), a parte enorme continua sendo lida e tem de contar no teto."""
    monkeypatch.setattr(leitura, "MAX_BYTES_XML", 50_000)
    dados = _refazer(planilha_modelo(outras_abas=()),
                     lambda n, c: c.replace(b"</Types>", _CT_SST % nome.encode()) if n == "[Content_Types].xml" else c,
                     [(nome, _SST.format("<si><t>a</t></si>" * 5_000).encode())])
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(dados)
    assert e.value.motivo == "a planilha é grande demais para o modelo"


def test_rels_da_aba_grande_conta_no_teto(monkeypatch):
    """Os rels da aba o openpyxl le inteiros mesmo no modo read_only (estao em xl/worksheets/_rels/)."""
    monkeypatch.setattr(leitura, "MAX_BYTES_XML", 50_000)
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(f'<Relationship Id="r{i}" Type="x" Target="y"/>' for i in range(2_000)) + "</Relationships>")
    dados = _refazer(planilha_modelo(outras_abas=()), novas=[("xl/worksheets/_rels/sheet1.xml.rels", rels.encode())])
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(dados)
    assert e.value.motivo == "a planilha é grande demais para o modelo"


def test_soma_das_partes_abertas_e_entradas_demais_tem_teto(monkeypatch):
    """Cada parte abaixo do teto, mas a soma das abertas acima; e o zip com entradas demais (o indice vai inteiro
    para a memoria ao abrir)."""
    monkeypatch.setattr(leitura, "MAX_BYTES_XML", 50_000)
    monkeypatch.setattr(leitura, "MAX_BYTES_PARTES", 60_000)
    estilos = lambda n, c: c.replace(b"</styleSheet>", b"<!--" + b"x" * 30_000 + b"--></styleSheet>") \
        if n == "xl/styles.xml" else c                                                       # noqa: E731
    base = _refazer(planilha_modelo(outras_abas=()), estilos)
    assert len(leitura.ler(base)) == 3                                   # uma parte grande so': passa
    dados = _refazer(base, lambda n, c: c.replace(b"</Types>", _CT_SST % b"xl/s.xml") if n == "[Content_Types].xml"
                     else c, [("xl/s.xml", _SST.format("<si><t>a</t></si>" * 2_000).encode())])
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(dados)
    assert e.value.motivo == "a planilha é grande demais para o modelo"
    monkeypatch.setattr(leitura, "MAX_ENTRADAS", 30)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(_refazer(base, novas=[(f"xl/media/x{i}.bin", b"") for i in range(30)]))
    assert e.value.motivo == "a planilha é grande demais para o modelo"


def test_parte_que_nao_se_abre_nao_conta(monkeypatch):
    """O que nao se le nao custa: parte que nada aponta, e a outra aba grande (as abas de memoria do modelo tem
    milhares de colunas), da qual o openpyxl so' le ate' a dimensao. Sem a dimensao ele varre a aba inteira, e ai'
    o teto conta."""
    monkeypatch.setattr(leitura, "MAX_BYTES_XML", 50_000)
    dados = _refazer(planilha_modelo(), novas=[("xl/worksheets/sheet9.xml", b"<x/>" * 20_000),
                                               ("xl/media/image1.png", b"\0" * 60_000)])
    assert len(leitura.ler(dados)) == 3
    linhas = b"".join(b'<row r="%d"><c r="A%d" s="0"/></row>' % (n, n) for n in range(1, 3_000))
    cronograma = _refazer(planilha_modelo(), lambda n, c: c.replace(b"<sheetData></sheetData>",
                          b"<sheetData>" + linhas + b"</sheetData>") if n == "xl/worksheets/sheet1.xml" else c)
    assert len(leitura.ler(cronograma)) == 3                     # a aba CRONOGRAMA passa de 50 KB, com dimensao
    sem_dimensao = _refazer(cronograma, lambda n, c: c.replace(b'<dimension ref="A1:A1"/>', b"")
                            if n == "xl/worksheets/sheet1.xml" else c)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(sem_dimensao)
    assert e.value.motivo == "a planilha é grande demais para o modelo"


def test_formula_sem_valor_depois_do_teto_de_linhas_tambem_recusa(monkeypatch):
    """Dentro do teto, formula sem valor calculado recusa; depois dele tambem (antes passava como vazia)."""
    monkeypatch.setattr(leitura, "MAX_VARRIDAS", 50)
    wb = openpyxl.load_workbook(io.BytesIO(planilha_modelo(outras_abas=())))
    wb["Resumo"].delete_rows(12, 2)
    wb["Resumo"]["E500"] = "=C9*2"                     # sem cache: o openpyxl nao calcula
    buf = io.BytesIO(); wb.save(buf)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(buf.getvalue())
    assert e.value.motivo == ("a linha 500 tem fórmula sem o valor calculado; abra a planilha no Excel, salve e "
                              "anexe de novo")
    # a formula que da' texto vazio (t="str" com <v></v>) depois do teto continua vazia
    calculada = _trocar_no_xml_da_aba(buf.getvalue(), b'<c r="E500"><f>C9*2</f><v></v></c>',
                                      b'<c r="E500" t="str"><f>C9*2</f><v></v></c>')
    assert len(leitura.ler(calculada)) == 3


def test_so_as_primeiras_colunas_sao_lidas():
    """Celula distante (coluna 10.000) nao faz a leitura percorrer a linha inteira: o cabecalho tem de estar perto."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Resumo"
    ws.cell(1, 10000, "x")
    ws.cell(6, leitura.MAX_COLUNAS + 1, "MEDIÇÃO"); ws.cell(6, leitura.MAX_COLUNAS + 2, "PERÍODO")
    ws.cell(6, leitura.MAX_COLUNAS + 3, "REAJUSTE")
    buf = io.BytesIO(); wb.save(buf)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(buf.getvalue())
    assert "cabeçalho" in e.value.motivo
    assert len(leitura.ler(planilha_modelo())) == 3


def test_linha_sem_reajuste_fica_de_fora():
    linhas = leitura.ler(planilha_modelo([("1ª Medição", "01/04/2026 a 30/04/2026", None),
                                          ("2ª Medição", "01/05/2026 a 31/05/2026", 50.0)]))
    assert [x["competencia"] for x in linhas] == ["2026-05"]


@pytest.mark.parametrize("dados, motivo", [
    (b"PK\x03\x04 nao e' planilha", "não abre"),
    (planilha_modelo(outras_abas=()), None),        # so' a aba Resumo: ainda e' o modelo
])
def test_arquivo_que_nao_abre_e_aba_unica(dados, motivo):
    if motivo:
        with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
            leitura.ler(dados)
        assert motivo in e.value.motivo
    else:
        assert len(leitura.ler(dados)) == 3


def test_planilha_sem_a_aba_resumo_nao_e_reconhecida():
    wb = openpyxl.Workbook()
    wb.active.title = "Cronograma"
    buf = io.BytesIO(); wb.save(buf)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(buf.getvalue())
    assert str(e.value) == leitura.MENSAGEM == "Não reconheci a planilha; digite a previsão"
    assert "Resumo" in e.value.motivo


def test_planilha_sem_a_coluna_reajuste_nao_e_reconhecida():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Resumo"
    ws.append(["MEDIÇÃO", "PERÍODO", "VALORES"])
    ws.append([None, None, "A PI", "TOTAL"])
    ws.append(["1ª Medição", "01/04/2026 a 30/04/2026", 10.0, 10.0])
    buf = io.BytesIO(); wb.save(buf)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(buf.getvalue())
    assert "REAJUSTE" in e.value.motivo


def test_periodo_ilegivel_ou_competencia_repetida_nao_e_reconhecida():
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(planilha_modelo([("1ª Medição", "abril", 10.0)]))
    assert "período" in e.value.motivo
    # a mesma competencia em duas linhas: a planilha nao diz qual vale, a pessoa decide
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(planilha_modelo([("2ª Medição", "01/04/2026 a 30/04/2026", 10.0),
                                     ("26ª Medição", "01/04/2026 a 30/04/2026", 20.0)]))
    assert "04/2026" in e.value.motivo


def test_aba_com_xml_quebrado_cai_na_digitacao_e_nao_em_erro_500():
    import zipfile
    origem, destino = io.BytesIO(planilha_modelo(outras_abas=())), io.BytesIO()
    with zipfile.ZipFile(origem) as z, zipfile.ZipFile(destino, "w") as novo:
        for item in z.infolist():
            dados = z.read(item.filename)
            novo.writestr(item, b"<worksheet><sheetData><row" if item.filename.startswith("xl/worksheets/") else dados)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(destino.getvalue())
    assert "não pôde ser lida" in e.value.motivo


def test_xml_quebrado_no_meio_da_aba_tambem_cai_na_digitacao(monkeypatch):
    """No modo read_only a aba e' lida aos poucos: o erro pode vir na varredura, depois de abrir."""
    from xml.etree.ElementTree import ParseError

    def quebra(*a, **k):
        raise ParseError("unclosed token")
    monkeypatch.setattr(leitura, "_colunas", quebra)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(planilha_modelo())
    assert "não pôde ser lida" in e.value.motivo


def test_linha_sem_rotulo_de_medicao_nao_mostra_none():
    linhas = leitura.ler(planilha_modelo([(None, "01/04/2026 a 30/04/2026", 10.0)]))
    assert linhas[0]["medicao"] == ""
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(planilha_modelo([(None, "01/04/2026 a 30/04/2026", 10.0), ("2ª Medição", "01/04/2026 a 30/04/2026", 1.0)]))
    assert "None" not in e.value.motivo and "a linha 8" in e.value.motivo


def test_linhas_em_branco_formatadas_nao_contam_no_teto():
    """Modelo sem TOTAIS e com a aba formatada ate' a linha 1000: so' as linhas com valor contam."""
    wb = openpyxl.load_workbook(io.BytesIO(planilha_modelo(outras_abas=())))
    ws = wb["Resumo"]
    ws.delete_rows(12, 2)                        # tira o TOTAIS
    ws.cell(1000, 1).number_format = "0.00"      # celula vazia formatada: a aba vai ate' a linha 1000
    ws.cell(1000, 1).value = " "
    buf = io.BytesIO(); wb.save(buf)
    assert len(leitura.ler(buf.getvalue())) == 3


def test_modelo_sem_nenhuma_linha_de_valor_nao_e_reconhecido():
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(planilha_modelo([]))
    assert "nenhuma" in e.value.motivo


# --- rodada 3 do revisor (30/10): compressao, zip64 e as varreduras no mesmo teto ------------------------------

def test_parte_em_bzip2_ou_lzma_e_recusada_antes_de_abrir():
    """O teto conta o que sai da descompressao, mas BZIP2/LZMA descompactam a parte inteira antes de devolver o
    primeiro pedaco: o zip com uma parte nesses formatos e' recusado ao abrir (o Excel so' grava STORED/DEFLATED)."""
    import zipfile
    for tipo in (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
        origem, destino = io.BytesIO(planilha_modelo()), io.BytesIO()
        with zipfile.ZipFile(origem) as z, zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as novo:
            for item in z.infolist():
                novo.writestr(item.filename, z.read(item.filename),
                              compress_type=tipo if item.filename == "xl/styles.xml" else zipfile.ZIP_DEFLATED)
        with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
            leitura.ler(destino.getvalue())
        assert e.value.motivo == "a planilha usa uma compressão que o Excel não grava"


def _com_zip64(dados: bytes) -> bytes:
    """O mesmo zip com o registro e o localizador do zip64 antes do fim classico (o fim classico continua pequeno,
    como no zip adulterado; aqui o registro zip64 repete os valores verdadeiros, entao o `zipfile` abre normalmente)."""
    fim = dados.rfind(b"PK\x05\x06")
    entradas = int.from_bytes(dados[fim + 10:fim + 12], "little")
    tamanho = int.from_bytes(dados[fim + 12:fim + 16], "little")
    inicio = int.from_bytes(dados[fim + 16:fim + 20], "little")
    registro = (b"PK\x06\x06" + (44).to_bytes(8, "little") + (45).to_bytes(2, "little") * 2 + b"\0" * 8
                + entradas.to_bytes(8, "little") * 2 + tamanho.to_bytes(8, "little") + inicio.to_bytes(8, "little"))
    localizador = b"PK\x06\x07" + b"\0" * 4 + fim.to_bytes(8, "little") + (1).to_bytes(4, "little")
    return dados[:fim] + registro + localizador + dados[fim:]


def test_localizador_zip64_antes_do_fim_e_recusado():
    """Achado do revisor: com o localizador zip64 o `zipfile` troca a contagem e o tamanho do indice do fim classico
    (que o pre-teste olha) pelos do registro zip64; 24 MB com 280 mil entradas vazias alocavam ~300 MB. O modelo nao
    usa zip64: o localizador recusa antes de o `zipfile` abrir."""
    import zipfile
    dados = _com_zip64(planilha_modelo())
    with zipfile.ZipFile(io.BytesIO(dados)) as z:          # o arquivo adulterado abre (o zip64 vale para o zipfile)
        assert len(z.infolist()) == 10
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(dados)
    assert e.value.motivo == "a planilha é grande demais para o modelo"


def test_assinatura_do_fim_gravada_no_proprio_fim_nao_esconde_o_zip64():
    """Rodada 4 (revisor, medido): com o deslocamento do fim classico valendo `PK\\x05\\x06` (o zip64 ignora esse
    campo), a busca pela ultima assinatura achava o campo, saia sem conferir, e o zip64 passava. O fim e' achado
    como o `zipfile` acha."""
    import zipfile
    dados = _com_zip64(planilha_modelo())
    dados = dados[:-6] + b"PK\x05\x06" + dados[-2:]          # o campo de deslocamento do fim classico
    with zipfile.ZipFile(io.BytesIO(dados)) as z:            # o zipfile abre: usa o deslocamento do zip64
        assert len(z.infolist()) == 10
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(dados)
    assert e.value.motivo == "a planilha é grande demais para o modelo"


def test_contagem_do_fim_falsificada_e_recusada_antes_de_montar_o_indice(monkeypatch):
    """Rodada 4 (Sol): o fim classico declara poucas entradas e o indice tem muitas (o `zipfile` percorre pelo
    tamanho, e o openpyxl montava todos os registros antes do teto recusar). Contam os registros do indice, antes de
    qualquer `ZipFile`."""
    import zipfile
    monkeypatch.setattr(leitura, "MAX_ENTRADAS", 30)
    dados = _refazer(planilha_modelo(outras_abas=()), novas=[(f"xl/media/x{i}.bin", b"") for i in range(40)])
    fim = dados.rfind(b"PK\x05\x06")
    dados = dados[:fim + 8] + (5).to_bytes(2, "little") * 2 + dados[fim + 12:]
    montados = []
    real = zipfile.ZipFile._RealGetContents
    monkeypatch.setattr(zipfile.ZipFile, "_RealGetContents", lambda self: montados.append(1) or real(self))
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(dados)
    assert e.value.motivo == "a planilha é grande demais para o modelo"
    assert montados == []


def test_varredura_da_aba_conta_no_mesmo_teto_da_leitura(monkeypatch):
    """Achado do revisor: a varredura do XML depois do teto de linhas abria outro zip, fora do teto, e relia a aba
    inteira. Agora conta na soma: as outras partes mais a aba inteira passam da soma e a leitura e' recusada."""
    import zipfile
    monkeypatch.setattr(leitura, "MAX_VARRIDAS", 50)
    dados = _com_linhas_vazias(planilha_modelo(outras_abas=()), 20, 50_000, sem_totais=True)
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        aba = z.getinfo("xl/worksheets/sheet1.xml").file_size
        outras = sum(i.file_size for i in z.infolist()) - aba
    assert aba > 2_000_000
    assert len(leitura.ler(dados)) == 3                      # no teto do servidor, passa
    monkeypatch.setattr(leitura, "MAX_BYTES_PARTES", outras + 1_000_000)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(dados)
    assert e.value.motivo == "a planilha é grande demais para o modelo"


def test_abas_que_apontam_para_a_mesma_parte_ou_abas_demais_sao_recusadas(monkeypatch):
    """Achado do revisor: o teto conta cada parte uma vez, e o openpyxl abre cada aba ao carregar (sem a dimensao,
    a parte inteira): centenas de abas apontando para a mesma parte reliam 9 MB cada. A aba repetida recusa, e as
    abas demais tambem."""
    sheet = ('<sheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" name="Copia{}" '
             'sheetId="{}" state="visible" r:id="rId1"/>')
    repetidas = _refazer(planilha_modelo(), lambda n, c: c.replace(
        b"</sheets>", "".join(sheet.format(i, 10 + i) for i in range(3)).encode() + b"</sheets>")
        if n == "xl/workbook.xml" else c)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(repetidas)
    assert e.value.motivo == "a planilha é grande demais para o modelo"
    assert len(leitura.ler(planilha_modelo())) == 3          # duas abas, cada uma na sua parte
    monkeypatch.setattr(leitura, "MAX_ABAS", 1)
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(planilha_modelo())
    assert e.value.motivo == "a planilha é grande demais para o modelo"
