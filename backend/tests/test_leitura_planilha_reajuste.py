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
