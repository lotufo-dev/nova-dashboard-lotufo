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
    linhas = leitura.ler(planilha_modelo([("1ª Medição", "01/04/2026 a 30/04/2026", 21342.29),
                                          ("2ª Medição", "01/05/2026 a 31/05/2026", -15.07)]))
    # 21342.29 * 100 em float da' 2134228.9999...; e indice deflacionario da' reajuste negativo
    assert [x["valor_centavos"] for x in linhas] == [2134229, -1507]


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


def test_modelo_sem_nenhuma_linha_de_valor_nao_e_reconhecido():
    with pytest.raises(leitura.PlanilhaNaoReconhecida) as e:
        leitura.ler(planilha_modelo([]))
    assert "nenhuma" in e.value.motivo
