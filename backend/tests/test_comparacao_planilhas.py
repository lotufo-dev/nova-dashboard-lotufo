"""Comparacao de duas versoes da planilha de medicao, item a item (issue #610).

Planilhas sinteticas no desenho da aba de resumo SINFRA (com e sem a coluna ITEM), com obra, itens e valores
inventados, e o TOTAL escrito na linha do rodape."""
import io

import openpyxl
import pytest

from app import comparacao_planilhas as comp
from app import leitura_planilha_medicao as leitura

CAB_ITEM = ["ITEM", "CÓDIGO", "DISCRIMINAÇÃO", "UNID.", "QUANT.", "NESTA MEDIÇÃO", "MEDIDO ACUMULADO",
            "PREÇO UNITÁRIO R$", "NESTA MEDIÇÃO R$", "VALOR ACUMULADO R$"]
CAB_SEM_ITEM = CAB_ITEM[1:]

# (item, codigo, discriminacao, unidade, quantidade nesta medicao, valor nesta medicao)
BASE = [
    ("1.1", "1234567", "Serviço fictício A", "m³", 1250.5, 20000.01),
    ("1.2", "s/c", "Serviço fictício B", "und", 0.05, 5000.0),
    ("1.3", "7654321", "Serviço fictício C", "m", 10, 1500.55),
    ("1.4", "s/c", "Serviço fictício B", "und", 2, 300.0),
]
TOTAL_BASE = 20000_01 + 5000_00 + 1500_55 + 300_00


def xlsx(itens=BASE, com_item=True, total="soma", aba="Resumo", rodape=None) -> bytes:
    """`total`: "soma" escreve a soma dos itens na linha do total; None nao escreve numero; um numero, ele."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = aba
    ws.cell(2, 1, "PLANILHA DE MEDIÇÃO — obra fictícia")
    cab = CAB_ITEM if com_item else CAB_SEM_ITEM
    col = {t: i + 1 for i, t in enumerate(cab)}
    for t, c in col.items():
        ws.cell(5, c, t)
    r = 6
    if com_item:
        ws.cell(r, col["ITEM"], "1")
    ws.cell(r, col["DISCRIMINAÇÃO"], "SERVIÇOS FICTÍCIOS")
    r += 1
    soma = 0
    for item, cod, desc, un, qm, vm in itens:
        valores = {"ITEM": item, "CÓDIGO": cod, "DISCRIMINAÇÃO": desc, "UNID.": un, "QUANT.": 99999,
                   "NESTA MEDIÇÃO": qm, "MEDIDO ACUMULADO": qm, "PREÇO UNITÁRIO R$": 1.0, "NESTA MEDIÇÃO R$": vm,
                   "VALOR ACUMULADO R$": vm}
        for nome, v in valores.items():
            if nome in col and v is not None:
                ws.cell(r, col[nome], v)
        soma += round(vm * 100) if vm is not None else 0
        r += 1
    ws.cell(r, col["DISCRIMINAÇÃO"], "SUBTOTAL")
    ws.cell(r, col["NESTA MEDIÇÃO R$"], 1.0)               # o subtotal da planilha nao entra
    r += 1
    for texto in rodape or (["TOTAL GERAL"] if com_item else ["TOTAL ACUMULADO", "TOTAL DESTA MEDIÇÃO"]):
        ws.cell(r, col["DISCRIMINAÇÃO"], texto)
        if texto in ("TOTAL GERAL", "TOTAL DESTA MEDIÇÃO") and total is not None:
            ws.cell(r, col["NESTA MEDIÇÃO R$"], soma / 100 if total == "soma" else total)
        r += 1
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def comparar(de_itens, para_itens, **kw):
    return comp.comparar_leituras(leitura.ler(xlsx(de_itens, **kw)), leitura.ler(xlsx(para_itens, **kw)))


def _trocar(itens, indice, qm=None, vm=None):
    novo = list(itens)
    item, cod, desc, un, qm0, vm0 = novo[indice]
    novo[indice] = (item, cod, desc, un, qm0 if qm is None else qm, vm0 if vm is None else vm)
    return novo


def test_item_zerado_e_quantidade_reduzida_sao_os_unicos_que_voltam():
    revisada = _trocar(_trocar(BASE, 0, qm=0, vm=0), 2, qm=7.5, vm=1125.41)
    r = comparar(BASE, revisada)
    assert r["itens"] == [
        {"codigo": "1234567", "discriminacao": "Serviço fictício A", "unidade": "m³", "situacao": "alterado",
         "quantidade_de": "1250.500", "quantidade_para": "0.000", "valor_de_centavos": 20000_01,
         "valor_para_centavos": 0, "diferenca_centavos": -20000_01},
        {"codigo": "7654321", "discriminacao": "Serviço fictício C", "unidade": "m", "situacao": "alterado",
         "quantidade_de": "10.000", "quantidade_para": "7.500", "valor_de_centavos": 1500_55,
         "valor_para_centavos": 1125_41, "diferenca_centavos": -375_14}]
    assert r["total_de"] == TOTAL_BASE and r["total_para"] == TOTAL_BASE - 20000_01 - 375_14
    assert r["diferenca_centavos"] == r["total_para"] - r["total_de"] == -20000_01 - 375_14


def test_diferenca_total_e_a_dos_totais_da_planilha_com_centavo_impar():
    revisada = _trocar(BASE, 1, vm=4999.99)
    de, para = leitura.ler(xlsx(BASE)), leitura.ler(xlsx(revisada))
    r = comp.comparar_leituras(de, para)
    assert r["diferenca_centavos"] == -1
    assert r["diferenca_centavos"] == para["total_planilha_centavos"] - de["total_planilha_centavos"]


def test_incluido_vai_no_fim_e_retirado_fica_na_ordem():
    revisada = [BASE[0], BASE[2], BASE[3], ("1.5", "1111111", "Serviço fictício D", "kg", 3, 33.33)]
    r = comparar(BASE, revisada)
    assert [(i["situacao"], i["codigo"]) for i in r["itens"]] == [("retirado", "s/c"), ("incluido", "1111111")]
    retirado, incluido = r["itens"]
    assert (retirado["quantidade_de"], retirado["quantidade_para"], retirado["valor_para_centavos"]) == (
        "0.050", None, None)
    assert retirado["diferenca_centavos"] == -5000_00
    assert (incluido["quantidade_de"], incluido["valor_de_centavos"], incluido["quantidade_para"]) == (
        None, None, "3.000")
    assert incluido["diferenca_centavos"] == 33_33
    assert r["diferenca_centavos"] == 33_33 - 5000_00


def test_versoes_iguais_dao_lista_vazia_e_diferenca_zero():
    r = comparar(BASE, BASE)
    assert r["itens"] == [] and r["diferenca_centavos"] == 0 and r["total_de"] == r["total_para"] == TOTAL_BASE


def test_quantidade_igual_em_tres_casas_nao_e_mudanca():
    r = comparar(BASE, _trocar(BASE, 0, qm=1250.5004))
    assert r["itens"] == []


def test_s_c_repetido_nao_se_confunde_sem_coluna_item():
    """Sem ITEM: a chave e' codigo + discriminacao + ocorrencia; os dois "s/c" "Serviço fictício B" sao itens
    diferentes, e mudar o segundo nao mexe no primeiro."""
    revisada = _trocar(BASE, 3, qm=1, vm=150.0)
    r = comparar(BASE, revisada, com_item=False)
    assert [(i["codigo"], i["quantidade_de"], i["quantidade_para"], i["diferenca_centavos"]) for i in r["itens"]] == [
        ("s/c", "2.000", "1.000", -150_00)]


def test_sem_coluna_item_retirar_o_primeiro_s_c_desloca_a_ocorrencia():
    """Sem nº de item nada distingue os dois "s/c" iguais alem da ordem: tirar o primeiro aparece como o segundo
    retirado e o primeiro alterado para o valor do segundo; a diferenca total fecha do mesmo jeito."""
    revisada = [BASE[0], BASE[2], BASE[3]]
    r = comparar(BASE, revisada, com_item=False)
    assert r["diferenca_centavos"] == -5000_00
    assert sum(i["diferenca_centavos"] for i in r["itens"]) == -5000_00


def test_com_coluna_item_a_chave_e_o_numero():
    """Com ITEM, mudar a discriminacao nao faz o item virar retirado + incluido."""
    revisada = [(i, c, "Outro texto" if i == "1.3" else d, u, q, v) for i, c, d, u, q, v in BASE]
    assert comparar(BASE, revisada)["itens"] == []


def test_soma_que_nao_fecha_com_o_total_da_planilha_recusa():
    de = leitura.ler(xlsx(BASE))
    para = leitura.ler(xlsx(BASE, total=TOTAL_BASE / 100 + 0.01))
    with pytest.raises(leitura.PlanilhaRecusada, match="não fecha"):
        comp.comparar_leituras(de, para)


def test_planilha_sem_total_escrito_compara_pela_soma():
    r = comparar(BASE, _trocar(BASE, 1, vm=4999.99), total=None)
    assert r["diferenca_centavos"] == -1


def test_sem_item_total_desta_medicao_abaixo_do_total_acumulado_confere():
    de = leitura.ler(xlsx(BASE, com_item=False))
    assert de["total_planilha_centavos"] == TOTAL_BASE
    para = leitura.ler(xlsx(BASE, com_item=False, total=1.0))
    with pytest.raises(leitura.PlanilhaRecusada):
        comp.comparar_leituras(de, para)


def test_versao_recusada_pelo_leitor_vira_nao_comparavel():
    with pytest.raises(leitura.PlanilhaRecusada):
        comp._ler_versao(None)
    with pytest.raises(leitura.PlanilhaRecusada):
        comp._ler_versao("planilhas/abc.pdf")
    with pytest.raises(leitura.PlanilhaRecusada, match="falta a aba Resumo"):
        leitura.ler(xlsx(aba="Boletim"))


def test_quantidade_acima_da_precisao_vira_nao_comparavel():
    """Revisor/gate A1: quantidade de 26+ digitos (1e30) estourava o quantize (InvalidOperation, erro 500)."""
    with pytest.raises(leitura.PlanilhaRecusada, match="quantidade"):
        comparar(BASE, _trocar(BASE, 0, qm=1e30))


def test_item_com_numero_e_sem_codigo_mostra_o_numero_no_codigo():
    """Gate S1: no modelo com ITEM, o item sem codigo e' identificado pelo nº (a tela mostra "codigo · texto")."""
    de = [("1.1", None, "Serviço sem código", "m", 2, 20.0)] + BASE[1:]
    para = [("1.1", None, "Serviço sem código", "m", 1, 10.0)] + BASE[1:]
    r = comparar(de, para)
    assert [(i["codigo"], i["discriminacao"]) for i in r["itens"]] == [("1.1", "Serviço sem código")]
