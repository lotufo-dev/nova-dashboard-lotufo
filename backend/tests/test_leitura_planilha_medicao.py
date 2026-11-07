"""Leitura do medido por grupo da planilha de medicao (issue #490).

As planilhas sao sinteticas, no desenho da planilha padrao SINFRA (aba de resumo: cabecalho numa linha, ITEM |
CÓDIGO | DISCRIMINAÇÃO | UNID. | QUANT. | NESTA MEDIÇÃO | MEDIDO ACUMULADO | PREÇO UNITÁRIO R$ | NESTA MEDIÇÃO R$ |
VALOR ACUMULADO R$; linha de grupo com o nº e o titulo em maiusculas; SUBTOTAL por grupo; TOTAL GERAL no fim),
com numeros inventados."""
import io

import openpyxl
import pytest

from app import leitura_planilha_medicao as leitura

CABECALHO = ["ITEM", "BOLETIM", "CÓDIGO", "DISCRIMINAÇÃO", "UNID.", "QUANT.", "NESTA\nMEDIÇÃO",
             "MEDIDO ACUMULADO ANTERIOR", "MEDIDO ACUMULADO", "PREÇO UNITÁRIO R$", "VALOR CONTRATO R$",
             "NESTA MEDIÇÃO R$", "VALOR ACUMULADO ANTERIOR R$", "VALOR ACUMULADO R$", "PERCENTUAL EXECUTADO %"]

# (item, codigo, descricao, unidade, quant. contratada, nesta medicao, acumulado, preco, valor nesta, valor acum.)
GRUPO = "grupo"
LINHAS = [
    ("1", None, "ADMINISTRAÇÃO LOCAL", GRUPO),
    ("1.1", "ADML", "Administração local da obra", "un", 24, 1, 5, 10000.01, 10000.01, 50000.05),
    "SUBTOTAL",
    ("2", None, "TERRAPLENAGEM", GRUPO),
    ("2.1", "4011", "Escavação e carga", "m³", 1000.5, 120.25, 300.5, 12.35, 1485.09, 3711.18),
    ("2.2", "4012", "Compactação de aterro", "m³", 800, 100, 100, 7.03, 703.0, 703.0),
    "SUBTOTAL",
    ("3", None, "DRENAGEM", GRUPO),
    ("3.1", "2003", "Bueiro tubular", "m", 50, 10, 20, 850.5, 8505.0, 17010.0),
    ("3.2", "2004", "Sarjeta de concreto", "m", 200, 0, 40, 45.1, None, 1804.0),
    "SUBTOTAL",
]
# 10000,01 + 1485,09 + 703,00 + 8505,00 = 20693,10
TOTAL = 20_693_10


def planilha(linhas=LINHAS, cabecalho=CABECALHO, aba="Resumo Medição", linha_cab=10) -> bytes:
    wb = openpyxl.Workbook()
    wb.active.title = "Boletim"
    ws = wb.create_sheet(aba)
    ws.cell(1, 1, "RESUMO DA MEDIÇÃO")
    ws.cell(3, 1, "Obra:")
    ws.cell(3, 2, "Obra fictícia")
    col = {t: i + 1 for i, t in enumerate(cabecalho)}
    for t, c in col.items():
        ws.cell(linha_cab, c, t)
    r = linha_cab + 1
    for ln in linhas:
        if ln == "SUBTOTAL":
            ws.cell(r, col.get("DISCRIMINAÇÃO", 1), "SUBTOTAL")
            if "NESTA MEDIÇÃO R$" in col:
                ws.cell(r, col["NESTA MEDIÇÃO R$"], 99999.99)
        elif ln[3] == GRUPO:
            ws.cell(r, col.get("ITEM", 1), ln[0])
            ws.cell(r, col.get("DISCRIMINAÇÃO", 2), ln[2])
            if ln[1] and "CÓDIGO" in col:
                ws.cell(r, col["CÓDIGO"], ln[1])
        else:
            item, cod, desc, un, qc, qm, qa, pu, vm, va = ln
            for nome, v in (("ITEM", item), ("CÓDIGO", cod), ("DISCRIMINAÇÃO", desc), ("UNID.", un),
                            ("QUANT.", qc), ("NESTA\nMEDIÇÃO", qm), ("MEDIDO ACUMULADO", qa),
                            ("PREÇO UNITÁRIO R$", pu), ("NESTA MEDIÇÃO R$", vm), ("VALOR ACUMULADO R$", va),
                            ("VALOR CONTRATO R$", 1.0), ("MEDIDO ACUMULADO ANTERIOR", 7)):
                if v is not None and nome in col:
                    ws.cell(r, col[nome], v)
        r += 1
    ws.cell(r + 1, col.get("BOLETIM", 1), "TOTAL GERAL NESTA MEDIÇÃO")
    if "NESTA MEDIÇÃO R$" in col:
        ws.cell(r + 1, col["NESTA MEDIÇÃO R$"], "vinte mil reais")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _por_nome(lido):
    return {g["nome"]: g for g in lido["grupos"]}


def test_tres_grupos_e_cinco_itens_dao_os_valores_por_grupo():
    lido = leitura.ler(planilha())
    assert lido["total_centavos"] == TOTAL and lido["grupo_por"] == "planilha"
    assert [g["nome"] for g in lido["grupos"]] == ["ADMINISTRAÇÃO LOCAL", "TERRAPLENAGEM", "DRENAGEM"]
    g = _por_nome(lido)
    assert g["TERRAPLENAGEM"]["valor_medido_centavos"] == 1485_09 + 703_00
    assert g["TERRAPLENAGEM"]["valor_acumulado_centavos"] == 3711_18 + 703_00
    assert g["DRENAGEM"]["valor_medido_centavos"] == 8505_00       # a sarjeta sem valor nesta medicao conta 0
    assert sum(len(x["itens"]) for x in lido["grupos"]) == 5
    esc = g["TERRAPLENAGEM"]["itens"][0]
    assert esc == {"item": "2.1", "codigo": "4011", "descricao": "Escavação e carga", "unidade": "m³",
                   "quantidade_contratada": "1000.5", "quantidade_medida": "120.25", "quantidade_acumulada": "300.5",
                   "preco_unitario_centavos": 12_35, "valor_medido_centavos": 1485_09,
                   "valor_acumulado_centavos": 3711_18}
    # mesma unidade no grupo: a quantidade do grupo e' a soma, com a unidade
    assert (g["TERRAPLENAGEM"]["unidade"], g["TERRAPLENAGEM"]["quantidade_medida"]) == ("m³", "220.25")
    assert g["TERRAPLENAGEM"]["quantidade_acumulada"] == "400.5"
    assert g["ADMINISTRAÇÃO LOCAL"]["itens"][0]["valor_medido_centavos"] == 10000_01     # centavo impar


def test_unidades_diferentes_no_grupo_nao_somam_quantidade():
    linhas = [("1", None, "OBRAS", GRUPO), ("1.1", "1", "Aterro", "m³", 10, 1, 1, 1.0, 1.0, 1.0),
              ("1.2", "2", "Meio-fio", "m", 10, 2, 2, 1.0, 2.0, 2.0)]
    g = leitura.ler(planilha(linhas))["grupos"][0]
    assert g["unidade"] is None and g["quantidade_medida"] is None and g["valor_medido_centavos"] == 3_00


def test_cabecalho_fora_de_ordem_e_lido_pelo_nome():
    embaralhado = [CABECALHO[i] for i in (3, 0, 13, 2, 11, 4, 9, 6, 1, 5, 8, 7, 10, 12, 14)]
    lido = leitura.ler(planilha(cabecalho=embaralhado, linha_cab=4))
    assert lido["total_centavos"] == TOTAL
    assert _por_nome(lido)["DRENAGEM"]["itens"][0]["quantidade_acumulada"] == "20"


def test_item_sem_grupo_cai_em_outros():
    linhas = [("1.1", "ADML", "Administração local", "un", 1, 1, 1, 10.0, 10.0, 10.0),
              ("2", None, "DRENAGEM", GRUPO), ("2.1", "2003", "Bueiro", "m", 1, 1, 1, 5.0, 5.0, 5.0)]
    lido = leitura.ler(planilha(linhas))
    assert [(g["nome"], g["valor_medido_centavos"]) for g in lido["grupos"]] == [("DRENAGEM", 5_00), ("outros", 10_00)]


def test_grupo_pelo_cadastro_quando_ha():
    cadastro = [{"nome": "Drenagem", "itens_planilha": ["3."]}, {"nome": "Terraplanagem", "itens_planilha": ["2."]}]
    lido = leitura.ler(planilha(), cadastro)
    assert lido["grupo_por"] == "cadastro"
    assert [(g["nome"], g["valor_medido_centavos"]) for g in lido["grupos"]] == [
        ("Drenagem", 8505_00), ("Terraplanagem", 2188_09), ("outros", 10000_01)]


def test_subgrupo_vale_o_titulo_mais_proximo():
    # o subgrupo pode ter codigo ("3.1*"): sem unidade e sem preco, e' titulo; o item sem unidade, com preco, e' item
    linhas = [("3", None, "OBRAS DE ARTE", GRUPO), ("3.1", "3.1*", "TERRAPLENAGEM", GRUPO),
              ("3.1.1", "1", "Aterro", "m³", 1, 1, 1, 2.0, 2.0, 2.0), ("3.2", None, "DRENAGEM", GRUPO),
              ("3.2.1", "2", "Bueiro", None, 1, 1, 1, 3.0, 3.0, 3.0),
              ("3.3", "3", "Placa", "un", 1, 1, 1, 4.0, 4.0, 4.0)]
    lido = leitura.ler(planilha(linhas))
    assert [(g["nome"], g["valor_medido_centavos"]) for g in lido["grupos"]] == [
        ("TERRAPLENAGEM", 2_00), ("DRENAGEM", 3_00), ("OBRAS DE ARTE", 4_00)]


def test_aba_resumo_ausente_recusa():
    with pytest.raises(leitura.PlanilhaRecusada, match="falta a aba Resumo"):
        leitura.ler(planilha(aba="Memória de cálculo"))


def test_aba_chamada_so_resumo_tambem_vale():
    assert leitura.ler(planilha(aba="Resumo"))["total_centavos"] == TOTAL


def test_cabecalho_sem_coluna_recusa_dizendo_qual():
    sem_preco = [c for c in CABECALHO if c != "PREÇO UNITÁRIO R$"]
    with pytest.raises(leitura.PlanilhaRecusada, match="PREÇO UNITÁRIO"):
        leitura.ler(planilha(cabecalho=sem_preco))
    with pytest.raises(leitura.PlanilhaRecusada, match="cabeçalho"):
        leitura.ler(planilha(cabecalho=["A", "B", "C"]))


def test_arquivo_que_nao_e_xlsx_recusa():
    with pytest.raises(leitura.PlanilhaRecusada, match="xlsx"):
        leitura.ler(b"PK\x03\x04 nao sou planilha")


def test_valor_que_nao_e_numero_recusa_dizendo_o_item():
    linhas = [("1", None, "OBRAS", GRUPO), ("1.1", "1", "Aterro", "m³", 10, 1, 1, 1.0, "mil", 1.0)]
    with pytest.raises(leitura.PlanilhaRecusada, match="1.1"):
        leitura.ler(planilha(linhas))


def test_conferir_total_tolera_um_real_e_recusa_com_a_diferenca():
    leitura.conferir_total(TOTAL, TOTAL + 100)          # um real de diferenca passa
    leitura.conferir_total(TOTAL, TOTAL - 100)
    with pytest.raises(leitura.PlanilhaRecusada) as e:
        leitura.conferir_total(TOTAL, TOTAL + 101)
    msg = str(e.value)
    assert "diferença de R$ 1,01" in msg and "R$ 20.693,10" in msg and "R$ 20.694,11" in msg


def test_prefixo_do_cadastro_respeita_o_ponto():
    linhas = [("1", None, "A", GRUPO), ("1.1", "1", "Item um", "m", 1, 1, 1, 1.0, 1.0, 1.0),
              ("10", None, "B", GRUPO), ("10.1", "2", "Item dez", "m", 1, 1, 1, 2.0, 2.0, 2.0)]
    lido = leitura.ler(planilha(linhas), [{"nome": "Grupo um", "itens_planilha": ["1"]}])
    assert [(g["nome"], g["valor_medido_centavos"]) for g in lido["grupos"]] == [("Grupo um", 1_00), ("outros", 2_00)]


def test_indice_do_zip_grande_demais_recusa_antes_de_abrir():
    dados = bytearray(planilha())
    fim = dados.rfind(b"PK\x05\x06")
    dados[fim + 12:fim + 16] = (leitura.MAX_BYTES_INDICE + 1).to_bytes(4, "little")
    with pytest.raises(leitura.PlanilhaRecusada, match="grande demais"):
        leitura.ler(bytes(dados))
