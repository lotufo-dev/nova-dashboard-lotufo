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


def _planilha_cabecalho(linhas_cab: list[list], dados: list[list]) -> bytes:
    """Planilha com o cabecalho dado linha a linha (None = celula vazia, como embaixo de uma mesclada)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Resumo"
    r = 5
    for linha in linhas_cab + dados:
        for c, v in enumerate(linha, 1):
            if v is not None:
                ws.cell(r, c, v)
        r += 1
    ws.cell(r, 1, "TOTAL GERAL")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# item, codigo, descricao, unidade, qtd contratada, qtd nesta, qtd acumulada, preco, valor nesta, valor acumulado
DADOS_2_LINHAS = [["1", None, "DRENAGEM", None, None, None, None, None, None, None],
                  ["1.1", "2003", "Bueiro", "m", 50, 10, 20, 850.51, 8505.1, 17010.2],
                  ["1.2", "2004", "Sarjeta", "m", 20, 3, 3, 45.11, 135.33, 135.33]]


def test_cabecalho_em_duas_linhas_com_pais_mesclados():
    """Sol S4: QUANTIDADES e VALORES (R$) mesclados em cima, as sub-colunas embaixo."""
    cab = [["ITEM", "CÓDIGO", "DISCRIMINAÇÃO", "UNID.", "QUANTIDADES", None, None, "PREÇO UNITÁRIO R$",
            "VALORES (R$)", None],
           [None, None, None, None, "CONTRATADA", "NESTA MEDIÇÃO", "ACUMULADA", None, "NESTA MEDIÇÃO", "ACUMULADO"]]
    lido = leitura.ler(_planilha_cabecalho(cab, DADOS_2_LINHAS))
    assert lido["total_centavos"] == 8505_10 + 135_33            # centavo impar
    it = lido["grupos"][0]["itens"][0]
    assert (it["quantidade_contratada"], it["quantidade_medida"], it["quantidade_acumulada"]) == ("50", "10", "20")
    assert (it["preco_unitario_centavos"], it["valor_acumulado_centavos"]) == (850_51, 17010_20)


def test_cabecalho_em_duas_linhas_com_quant_e_rs_embaixo():
    """Sol S4: NESTA MEDIÇÃO e ACUMULADO em cima, QUANT. e R$ embaixo de cada um."""
    cab = [["ITEM", "CÓDIGO", "DISCRIMINAÇÃO", "UNID.", "CONTRATO", "NESTA MEDIÇÃO", None, "PREÇO UNITÁRIO R$",
            "ACUMULADO", None],
           [None, None, None, None, "QUANT.", "QUANT.", "R$", None, "QUANT.", "R$"]]
    dados = [[r[0], r[1], r[2], r[3], r[4], r[5], r[8], r[7], r[6], r[9]] for r in DADOS_2_LINHAS]
    lido = leitura.ler(_planilha_cabecalho(cab, dados))
    assert lido["total_centavos"] == 8505_10 + 135_33
    it = lido["grupos"][0]["itens"][1]
    assert (it["quantidade_contratada"], it["quantidade_medida"], it["quantidade_acumulada"]) == ("20", "3", "3")
    assert it["valor_medido_centavos"] == 135_33


def test_cabecalho_em_duas_linhas_ainda_incompleto_recusa_dizendo_o_que_falta():
    cab = [["ITEM", "CÓDIGO", "DISCRIMINAÇÃO", "UNID.", "QUANTIDADES", None, None, "PREÇO UNITÁRIO R$"],
           [None, None, None, None, "CONTRATADA", "NESTA MEDIÇÃO", "ACUMULADA", None]]
    with pytest.raises(leitura.PlanilhaRecusada, match="NESTA MEDIÇÃO R\\$"):
        leitura.ler(_planilha_cabecalho(cab, DADOS_2_LINHAS))


def test_subtotal_errado_da_planilha_nao_conta():
    """Revisor R2: na planilha real a diferenca para o TOTAL GERAL vem de SUBTOTAIS com intervalo errado (um item
    fora da soma, outro bloco somado duas vezes); a leitura soma os itens e ignora o SUBTOTAL da propria planilha."""
    linhas = [("1", None, "CONTENÇÃO", GRUPO), ("1.1", "1", "Armação", "kg", 1, 1, 1, 81.89, 81.89, 81.89),
              ("1.2", "2", "Concreto", "m³", 1, 1, 1, 10.0, 10.0, 10.0), "SUBTOTAL",
              ("2", None, "GABIÃO", GRUPO), ("2.1", "3", "Gabião", "m³", 1, 1, 1, 5.0, 5.0, 5.0), "SUBTOTAL"]
    lido = leitura.ler(planilha(linhas))
    assert [(g["nome"], g["valor_medido_centavos"]) for g in lido["grupos"]] == [("CONTENÇÃO", 91_89), ("GABIÃO", 5_00)]


def test_arquivo_acima_do_teto_recusa_antes_de_abrir(monkeypatch):
    monkeypatch.setattr(leitura, "MAX_BYTES_ARQUIVO", 100)
    with pytest.raises(leitura.PlanilhaRecusada, match="grande demais"):
        leitura.ler(planilha())


# --- issue #612: aba de resumo sem a coluna ITEM (so' o codigo do servico) ------------------------------------
# A tabela comeca na coluna B, as celulas do cabecalho tem quebra de linha, o titulo de grupo e' so' a discriminacao
# (sem nº, sem codigo, sem unidade, sem preco), e o rodape e' TOTAL ACUMULADO / A DEDUZIR / TOTAL DESTA MEDIÇÃO.
CABECALHO_SEM_ITEM = ["CÓDIGO", "DISCRIMINAÇÃO", "UNID.", "QTDADE\nDE\nCONTRATO", "NESTA\nMEDIÇÃO",
                      "MEDIÇÃO\nANTERIOR", "MEDIDO\nACUMULADO", "PREÇO\nUNITÁRIO R$", "VALOR\nCONTRATO R$",
                      "NESTA\nMEDIÇÃO R$", "VALOR ACUMULADO\nANTERIOR R$", "VALOR\nACUMULADO R$", "%\nEXE."]
TITULO, SUB = "titulo", "subtotal"
# (codigo, descricao, unidade, qtd contrato, nesta, anterior, acumulado, preco, valor contrato, valor nesta,
#  valor anterior, valor acumulado, % exe.)
LINHAS_SEM_ITEM = [
    (TITULO, "SERVIÇOS PRELIMINARES"),
    ("s/c", "Placa de obra", "un", 1, 1, 0, 1, 500.55, 500.55, 500.55, 0, 500.55, 1),
    ("s/c", "Mobilização", "vb", 1, 1, 0, 1, 1200.01, 1200.01, 1200.01, 0, 1200.01, 1),
    (SUB, "SUBTOTAL"),
    (TITULO, "PAVIMENTAÇÃO"),
    ("4011", "Base de brita graduada", "m³", 100, 10.5, 4, 14.5, 123.45, 12345.0, 1296.23, 493.8, 1790.03, 0.145),
    (TITULO, "Revestimento"),
    ("4100", "Concreto asfáltico", "t", 50, 2, 0, 2, 400.135, 20006.75, 800.27, 0, 800.27, 0.04),
    (SUB, "SUBTOTAL"),
    (SUB, "SUBTOTAL"),
    (SUB, "TOTAL ACUMULADO"),
    (SUB, "A DEDUZIR DAS MEDIÇÕES ANTERIORES"),
    (SUB, "TOTAL DESTA MEDIÇÃO"),
    # abaixo do rodape, outra tabela com cara de item: a leitura ja' parou
    ("9999", "Resumo por etapa", "un", 1, 1, 0, 1, 7.77, 7.77, 7.77, 0, 7.77, 1),
]
# 500,55 + 1200,01 + 1296,23 + 800,27
TOTAL_SEM_ITEM = 3797_06


def planilha_sem_item(linhas=LINHAS_SEM_ITEM, cabecalho=CABECALHO_SEM_ITEM) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Resumo"
    ws.cell(2, 2, "PLANILHA DE MEDIÇÃO")
    ws.cell(3, 2, "Obra: obra fictícia")
    linha_cab, coluna_b = 6, 2
    for c, t in enumerate(cabecalho):
        ws.cell(linha_cab, coluna_b + c, t)
    desc = cabecalho.index("DISCRIMINAÇÃO") if "DISCRIMINAÇÃO" in cabecalho else 1
    for r, ln in enumerate(linhas, linha_cab + 1):
        if ln[0] == TITULO:
            ws.cell(r, coluna_b + desc, ln[1])
        elif ln[0] == SUB:
            ws.cell(r, coluna_b + desc, ln[1])
            ws.cell(r, coluna_b + 9, 12345.67)          # a soma da propria planilha, que nao entra
        else:
            for c, v in enumerate(ln[:len(cabecalho)]):
                ws.cell(r, coluna_b + c, v)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_sem_item_le_pelos_titulos_da_planilha():
    lido = leitura.ler(planilha_sem_item())
    assert lido["grupo_por"] == "planilha"
    assert [(g["nome"], g["valor_medido_centavos"]) for g in lido["grupos"]] == [
        ("SERVIÇOS PRELIMINARES", 500_55 + 1200_01), ("PAVIMENTAÇÃO", 1296_23), ("Revestimento", 800_27)]
    assert lido["total_centavos"] == TOTAL_SEM_ITEM            # centavo impar, no centavo
    base = _por_nome(lido)["PAVIMENTAÇÃO"]["itens"][0]
    assert base == {"item": None, "codigo": "4011", "descricao": "Base de brita graduada", "unidade": "m³",
                    "quantidade_contratada": "100", "quantidade_medida": "10.5", "quantidade_acumulada": "14.5",
                    "preco_unitario_centavos": 123_45, "valor_medido_centavos": 1296_23,
                    "valor_acumulado_centavos": 1790_03}


def test_sem_item_codigo_s_c_repetido_sao_dois_itens():
    itens = _por_nome(leitura.ler(planilha_sem_item()))["SERVIÇOS PRELIMINARES"]["itens"]
    assert [(i["codigo"], i["descricao"], i["valor_medido_centavos"]) for i in itens] == [
        ("s/c", "Placa de obra", 500_55), ("s/c", "Mobilização", 1200_01)]


def test_sem_item_rodape_nao_vira_grupo_nem_item():
    lido = leitura.ler(planilha_sem_item())
    nomes = {g["nome"] for g in lido["grupos"]}
    descricoes = {i["descricao"] for g in lido["grupos"] for i in g["itens"]}
    for rodape in ("TOTAL ACUMULADO", "A DEDUZIR DAS MEDIÇÕES ANTERIORES", "TOTAL DESTA MEDIÇÃO"):
        assert rodape not in nomes and rodape not in descricoes
    assert "Resumo por etapa" not in descricoes and leitura.OUTROS not in nomes


def test_sem_item_para_tambem_no_total_acumulado():
    linhas = [ln for ln in LINHAS_SEM_ITEM if ln[1] not in ("A DEDUZIR DAS MEDIÇÕES ANTERIORES",
                                                              "TOTAL DESTA MEDIÇÃO")]
    assert leitura.ler(planilha_sem_item(linhas))["total_centavos"] == TOTAL_SEM_ITEM


def test_sem_item_para_tambem_no_total_desta_medicao():
    linhas = [ln for ln in LINHAS_SEM_ITEM if ln[1] not in ("TOTAL ACUMULADO", "A DEDUZIR DAS MEDIÇÕES ANTERIORES")]
    assert leitura.ler(planilha_sem_item(linhas))["total_centavos"] == TOTAL_SEM_ITEM


def test_sem_item_agrupa_pelos_titulos_mesmo_com_cadastro_de_custo():
    cadastro = [{"nome": "Pavimento", "itens_planilha": ["2."]}]
    lido = leitura.ler(planilha_sem_item(), cadastro)
    assert lido["grupo_por"] == "planilha"
    assert [g["nome"] for g in lido["grupos"]] == ["SERVIÇOS PRELIMINARES", "PAVIMENTAÇÃO", "Revestimento"]


def test_sem_item_cai_no_grupo_do_cadastro_pelo_titulo_e_o_que_sobra_vai_para_outros():
    """Issue #613: o titulo lido e' procurado nos `titulos_planilha` sem acento, sem maiusculas e com espacos
    normalizados; dois titulos no mesmo grupo somam; titulo fora do cadastro vai para "outros", com o valor."""
    cadastro = [{"nome": "Drenagem", "itens_planilha": [], "titulos_planilha": ["DRENAGEM"]},
                {"nome": "Pavimento", "itens_planilha": [], "titulos_planilha": ["pavimentacao", "  REVESTIMENTO "]}]
    lido = leitura.ler(planilha_sem_item(), cadastro)
    assert lido["grupo_por"] == "cadastro"
    assert [(g["nome"], g["valor_medido_centavos"]) for g in lido["grupos"]] == [
        ("Pavimento", 1296_23 + 800_27), (leitura.OUTROS, 500_55 + 1200_01)]
    assert lido["total_centavos"] == TOTAL_SEM_ITEM
    assert [i["codigo"] for i in _por_nome(lido)["Pavimento"]["itens"]] == ["4011", "4100"]


def test_sem_item_com_cadastro_so_de_itens_planilha_continua_pelos_titulos():
    cadastro = [{"nome": "Pavimento", "itens_planilha": ["2."], "titulos_planilha": []}]
    assert leitura.ler(planilha_sem_item(), cadastro)["grupo_por"] == "planilha"


def test_sem_item_e_sem_codigo_recusa_dizendo_as_colunas():
    sem_codigo = [c for c in CABECALHO_SEM_ITEM if c != "CÓDIGO"]
    with pytest.raises(leitura.PlanilhaRecusada, match="ITEM.*CÓDIGO.*DISCRIMINAÇÃO"):
        leitura.ler(planilha_sem_item(cabecalho=sem_codigo))


def test_sem_item_item_sem_codigo_com_unidade_e_preco_conta():
    linhas = [(TITULO, "SERVIÇOS FINAIS"), (None, "Limpeza final", "m²", 10, 3, 0, 3, 10.01, 100.1, 30.03, 0, 30.03, 0.3)]
    lido = leitura.ler(planilha_sem_item(linhas))
    assert lido["total_centavos"] == 30_03
    it = lido["grupos"][0]["itens"][0]
    assert (lido["grupos"][0]["nome"], it["codigo"], it["descricao"]) == ("SERVIÇOS FINAIS", None, "Limpeza final")


def test_linha_com_codigo_da_obra_acima_do_cabecalho_nao_e_o_cabecalho():
    """Code-review: um dado acima da tabela ("CÓDIGO DA OBRA" | "DESCRIÇÃO DO OBJETO") nao recusa a planilha."""
    wb = openpyxl.load_workbook(io.BytesIO(planilha()))
    ws = wb["Resumo Medição"]
    ws.cell(5, 1, "CÓDIGO DA OBRA: 123")
    ws.cell(5, 2, "DESCRIÇÃO DO OBJETO: obra fictícia")
    ws.cell(6, 1, "CÓDIGO DO CONTRATO")             # logo embaixo, outra igual: a busca segue
    ws.cell(6, 2, "DESCRIÇÃO")
    buf = io.BytesIO()
    wb.save(buf)
    assert leitura.ler(buf.getvalue())["total_centavos"] == TOTAL
    sem_item = openpyxl.load_workbook(io.BytesIO(planilha_sem_item()))
    sem_item["Resumo"].cell(4, 2, "CÓDIGO DA OBRA")
    sem_item["Resumo"].cell(4, 3, "DISCRIMINAÇÃO DO OBJETO")
    buf = io.BytesIO()
    sem_item.save(buf)
    assert leitura.ler(buf.getvalue())["total_centavos"] == TOTAL_SEM_ITEM


def _trocar(dados: bytes, aba: str, celulas: dict[tuple[int, int], str]) -> bytes:
    wb = openpyxl.load_workbook(io.BytesIO(dados))
    for (r, c), v in celulas.items():
        wb[aba].cell(r, c, v)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_sem_item_recusa_com_as_colunas_da_linha_mais_perto_do_cabecalho():
    """Gate Sol, #612: com "CÓDIGO DA OBRA" acima, a recusa diz so' o que falta no cabecalho de verdade."""
    sem_preco = [c for c in CABECALHO_SEM_ITEM if c != "PREÇO\nUNITÁRIO R$"]
    dados = _trocar(planilha_sem_item(cabecalho=sem_preco), "Resumo",
                    {(4, 2): "CÓDIGO DA OBRA", (4, 3): "DISCRIMINAÇÃO DO OBJETO"})
    with pytest.raises(leitura.PlanilhaRecusada) as e:
        leitura.ler(dados)
    assert str(e.value) == "o cabeçalho da aba Resumo não tem a coluna PREÇO UNITÁRIO R$"


def test_coluna_n_item_vale_como_item():
    """Gate Sol, #612: "Nº ITEM" e' a coluna ITEM; a planilha nao cai no modelo sem ITEM."""
    dados = _trocar(planilha(), "Resumo Medição", {(10, 1): "Nº ITEM"})
    assert leitura.ler(dados) == leitura.ler(planilha())
    cadastro = [{"nome": "Drenagem", "itens_planilha": ["3."]}]
    lido = leitura.ler(dados, cadastro)
    assert lido["grupo_por"] == "cadastro" and lido == leitura.ler(planilha(), cadastro)


def test_coluna_de_item_que_nao_se_reconhece_recusa_em_vez_de_virar_sem_item():
    dados = _trocar(planilha(), "Resumo Medição", {(10, 1): "ITEM Nº"})
    with pytest.raises(leitura.PlanilhaRecusada, match="não tem a coluna ITEM"):
        leitura.ler(dados)


def test_sem_item_linha_de_total_fora_do_rodape_nao_vira_titulo():
    linhas = [(TITULO, "DRENAGEM"), ("2003", "Bueiro", "m", 1, 1, 0, 1, 5.01, 5.01, 5.01, 0, 5.01, 1),
              (SUB, "TOTAL DO GRUPO"), (SUB, "SUB-TOTAL"),
              ("2004", "Sarjeta", "m", 1, 1, 0, 1, 2.0, 2.0, 2.0, 0, 2.0, 1)]
    lido = leitura.ler(planilha_sem_item(linhas))
    assert [(g["nome"], g["valor_medido_centavos"]) for g in lido["grupos"]] == [("DRENAGEM", 7_01)]


def test_sem_item_com_outra_coluna_faltando_diz_qual():
    sem_preco = [c for c in CABECALHO_SEM_ITEM if c != "PREÇO\nUNITÁRIO R$"]
    with pytest.raises(leitura.PlanilhaRecusada, match="PREÇO UNITÁRIO") as e:
        leitura.ler(planilha_sem_item(cabecalho=sem_preco))
    assert "ITEM" not in str(e.value)


# --- issue #617: no modelo sem ITEM, so' a linha sem unidade e sem preco e' linha de soma ----------------------
def test_sem_item_item_cuja_discriminacao_comeca_com_total_e_lido():
    linhas = [(TITULO, "DRENAGEM"),
              ("2003", "Total de bueiros executados", "m", 1, 1, 0, 1, 5.01, 5.01, 5.01, 0, 5.01, 1),
              # mediu 0 no mes, so' acumulado: sumir nao mudaria a soma, entao o teste olha o grupo
              ("2005", "Total de sarjetas", "m", 1, 0, 1, 1, 2.0, 2.0, 0, 2.0, 2.0, 1),
              (SUB, "TOTAL DO GRUPO"), (SUB, "SUB TOTAL"), (SUB, "SUB-TOTAL")]
    lido = leitura.ler(planilha_sem_item(linhas))
    assert lido["total_centavos"] == 5_01
    assert [g["nome"] for g in lido["grupos"]] == ["DRENAGEM"]
    itens = lido["grupos"][0]["itens"]
    assert [(i["codigo"], i["descricao"], i["valor_medido_centavos"], i["valor_acumulado_centavos"])
            for i in itens] == [("2003", "Total de bueiros executados", 5_01, 5_01),
                                ("2005", "Total de sarjetas", 0, 2_00)]


def test_sem_item_linha_de_total_com_rotulo_na_coluna_do_codigo_continua_pulada():
    linhas = [(TITULO, "DRENAGEM"), ("2003", "Bueiro", "m", 1, 1, 0, 1, 5.01, 5.01, 5.01, 0, 5.01, 1),
              ("TOTAL DO GRUPO", None, None, None, None, None, None, None, None, 5.01, 0, 5.01, None),
              (TITULO, "PONTES"), ("2004", "Sarjeta", "m", 1, 1, 0, 1, 2.0, 2.0, 2.0, 0, 2.0, 1),
              (None, "TOTAL DAS PONTES", None, None, None, None, None, None, None, 2.0, 0, 2.0, None),
              ("2006", "Meio-fio", "m", 1, 1, 0, 1, 3.0, 3.0, 3.0, 0, 3.0, 1)]
    lido = leitura.ler(planilha_sem_item(linhas))
    assert [(g["nome"], g["valor_medido_centavos"]) for g in lido["grupos"]] == [("DRENAGEM", 5_01),
                                                                                 ("PONTES", 5_00)]


@pytest.mark.parametrize(("unidade", "preco"), [(None, "-"), (None, 0), ("R$", None), ("R$", "-"), ("%", 0)])
def test_sem_item_linha_de_total_com_traco_zero_ou_r_na_unidade_continua_pulada(unidade, preco):
    """Code-review #617: o "TOTAL DO GRUPO" com "-" ou 0 no preco, ou "R$" na unidade, nao vira item."""
    linhas = [(TITULO, "DRENAGEM"), ("2003", "Bueiro", "m", 1, 1, 0, 1, 5.01, 5.01, 5.01, 0, 5.01, 1),
              (None, "TOTAL DO GRUPO", unidade, None, None, None, None, preco, None, 5.01, 0, 5.01, None),
              (None, "Sub-total da drenagem", unidade, None, None, None, None, preco, None, 5.01, 0, 5.01, None)]
    lido = leitura.ler(planilha_sem_item(linhas))
    assert [(g["nome"], g["valor_medido_centavos"]) for g in lido["grupos"]] == [("DRENAGEM", 5_01)]


def test_sem_item_item_sem_codigo_comecando_com_total_e_lido_pela_unidade_e_preco():
    linhas = [(TITULO, "DRENAGEM"), (None, "Total de bocas de lobo", "un", 1, 1, 0, 1, 3.0, 3.0, 3.0, 0, 3.0, 1)]
    lido = leitura.ler(planilha_sem_item(linhas))
    assert lido["total_centavos"] == 3_00 and lido["grupos"][0]["itens"][0]["descricao"] == "Total de bocas de lobo"


@pytest.mark.parametrize("coluna", ["SUB ITEM", "VALOR ITEM", "POR ITEM"])
def test_sem_item_coluna_extra_terminada_em_item_nao_vira_a_coluna_item(coluna):
    lido = leitura.ler(planilha_sem_item(cabecalho=CABECALHO_SEM_ITEM + [coluna]))
    assert lido["grupo_por"] == "planilha"
    assert [g["nome"] for g in lido["grupos"]] == ["SERVIÇOS PRELIMINARES", "PAVIMENTAÇÃO", "Revestimento"]
    assert lido["total_centavos"] == TOTAL_SEM_ITEM            # parou no TOTAL ACUMULADO


@pytest.mark.parametrize("rotulo", ["Nº ITEM", "N. ITEM", "N ITEM", "NUM ITEM", "N° ITEM", "N.º ITEM", "NR. ITEM",
                                    "NRO ITEM", "NÚMERO ITEM", "SEQ. ITEM", "COD. ITEM", "NMR ITEM"])
def test_formas_de_numero_do_item_valem_como_item(rotulo):
    """Revisor #617: so' "SUB/VALOR/POR ITEM" deixam de ser ITEM; "SEQ. ITEM" e "COD. ITEM" seguem como antes, com o
    cadastro de custo (nao caem no modelo sem ITEM, que agrupa pelos titulos)."""
    dados = _trocar(planilha(), "Resumo Medição", {(10, 1): rotulo})
    assert leitura.ler(dados) == leitura.ler(planilha())
    cadastro = [{"nome": "G1", "itens_planilha": ["1"]}, {"nome": "G3", "itens_planilha": ["3"]}]
    lido = leitura.ler(dados, cadastro)
    assert lido["grupo_por"] == "cadastro" and lido == leitura.ler(planilha(), cadastro)


@pytest.mark.parametrize(("codigo", "unidade", "preco", "nesta"), [
    ("-", "-", "-", 5.01), ("-", "-", "-", 0), ("s/c", "-", "-", 5.01), ("s/c", "-", "-", 0),
    (None, "-", 5.01, 5.01), ("-", None, None, 5.01), ("s/c", "R$", "-", 0)])
def test_sem_item_linha_de_total_com_traco_no_codigo_ou_na_unidade_continua_pulada(codigo, unidade, preco, nesta):
    """Gate Sol #617: "-" no codigo ou na unidade e "s/c" no codigo nao fazem da linha de soma um item."""
    linhas = [(TITULO, "DRENAGEM"), ("2003", "Bueiro", "m", 1, nesta and 1, 1, 1, 5.01, 5.01, nesta, 5.01, 5.01, 1),
              (codigo, "TOTAL DO GRUPO", unidade, None, None, None, None, preco, None, nesta, 5.01, 5.01, None)]
    lido = leitura.ler(planilha_sem_item(linhas))
    assert [(g["nome"], g["valor_medido_centavos"]) for g in lido["grupos"]] == [("DRENAGEM", round(nesta * 100))]
    assert [i["descricao"] for i in lido["grupos"][0]["itens"]] == ["Bueiro"]


@pytest.mark.parametrize("nesta", [5.01, 0])
@pytest.mark.parametrize(("codigo", "unidade", "preco"), [
    ("–", "R$", 0), ("S/C.", "R$", "-"), ("-", "R$", 1234.5), (None, "R$", 100.0), ("—", "R$", 0), ("S/C", "%", 0)])
def test_sem_item_linha_de_total_com_codigo_sem_digito_ou_unidade_de_dinheiro_continua_pulada(
        codigo, unidade, preco, nesta):
    """Revisor #617, rodada 2: codigo sem digito (travessao, "S/C.") e unidade "R$" ou "%" nao fazem da soma um
    item, mesmo com numero no preco unitario."""
    linhas = [(TITULO, "DRENAGEM"), ("2003", "Bueiro", "m", 1, nesta and 1, 1, 1, 5.01, 5.01, nesta, 5.01, 5.01, 1),
              (codigo, "TOTAL DO GRUPO", unidade, None, None, None, None, preco, None, nesta, 5.01, 5.01, None)]
    lido = leitura.ler(planilha_sem_item(linhas))
    assert [(i["descricao"], i["valor_acumulado_centavos"]) for g in lido["grupos"] for i in g["itens"]] == [
        ("Bueiro", 5_01)]
    assert lido["total_centavos"] == round(nesta * 100)


def test_sem_item_item_total_com_codigo_unidade_e_preco_continua_lido():
    linhas = [(TITULO, "DRENAGEM"), ("2003", "Total de bueiros", "m", 1, 1, 0, 1, 7.0, 7.0, 7.0, 0, 7.0, 1)]
    lido = leitura.ler(planilha_sem_item(linhas))
    assert lido["total_centavos"] == 7_00
    assert [(i["codigo"], i["descricao"]) for i in lido["grupos"][0]["itens"]] == [("2003", "Total de bueiros")]


def test_sem_item_item_total_com_preco_em_texto_nao_some():
    """Revisor #617: preco gravado como texto nao faz o item virar soma; a leitura recusa dizendo o preco."""
    linhas = [(TITULO, "DRENAGEM"), (None, "Total de bocas de lobo", "un", 1, 1, 0, 1, "3,00", 3.0, 3.0, 0, 3.0, 1)]
    with pytest.raises(leitura.PlanilhaRecusada, match="preço unitário do item Total de bocas de lobo"):
        leitura.ler(planilha_sem_item(linhas))


def test_sem_item_total_na_coluna_de_observacao_nao_some_com_o_item():
    """Revisor #617: "Total executado" numa coluna que a leitura nao usa nao derruba um item com codigo, unidade e
    preco; a linha de soma com o rotulo nessa coluna continua pulada."""
    cab = CABECALHO_SEM_ITEM + ["OBSERVAÇÃO"]
    linhas = [(TITULO, "DRENAGEM"),
              ("2003", "Bueiro", "m", 1, 1, 0, 1, 5.01, 5.01, 5.01, 0, 5.01, 1, "Total executado no trecho"),
              (None, None, None, None, None, None, None, None, None, 5.01, 0, 5.01, None, "TOTAL DO GRUPO")]
    lido = leitura.ler(planilha_sem_item(linhas, cabecalho=cab))
    assert [(g["nome"], g["valor_medido_centavos"]) for g in lido["grupos"]] == [("DRENAGEM", 5_01)]


@pytest.mark.parametrize("rotulo", ["Nº DO ITEM"])
def test_coluna_de_nº_do_item_que_nao_se_reconhece_continua_recusando(rotulo):
    dados = _trocar(planilha(), "Resumo Medição", {(10, 1): rotulo})
    with pytest.raises(leitura.PlanilhaRecusada, match="não tem a coluna ITEM"):
        leitura.ler(dados)


# --- issue #610: os itens na ordem da planilha e o total que a propria planilha escreve -------------------------

def test_itens_na_ordem_da_planilha_mesmo_com_outros_no_fim():
    linhas = [("1.1", "ADML", "Administração local", "un", 1, 1, 1, 10.0, 10.0, 10.0),
              ("2", None, "DRENAGEM", GRUPO), ("2.1", "2003", "Bueiro", "m", 1, 1, 1, 5.0, 5.0, 5.0)]
    lido = leitura.ler(planilha(linhas))
    assert [g["nome"] for g in lido["grupos"]] == ["DRENAGEM", "outros"]
    assert [i["item"] for i in lido["itens"]] == ["1.1", "2.1"]


def test_total_escrito_na_planilha():
    assert leitura.ler(planilha())["total_planilha_centavos"] is None          # "vinte mil reais": nao e' numero
    dados = _trocar(planilha(), "Resumo Medição", {(23, 12): 20693.11})          # TOTAL GERAL, NESTA MEDIÇÃO R$
    lido = leitura.ler(dados)
    assert lido["total_planilha_centavos"] == 20693_11 and lido["total_centavos"] == TOTAL
    # sem ITEM: a leitura para no TOTAL ACUMULADO e o TOTAL DESTA MEDIÇÃO vem de baixo (o 12345,67 da fixture)
    assert leitura.ler(planilha_sem_item())["total_planilha_centavos"] == 12345_67


def test_total_escrito_fora_da_coluna_ou_absurdo_nao_recusa_a_leitura():
    """Code-review: o total e' opcional; o numero em outra coluna nao vale, e o acima do teto nao recusa a leitura."""
    so_acumulado = leitura.ler(_trocar(planilha(), "Resumo Medição", {(23, 14): 99999.99}))
    assert so_acumulado["total_planilha_centavos"] is None and so_acumulado["total_centavos"] == TOTAL
    absurdo = leitura.ler(_trocar(planilha(), "Resumo Medição", {(23, 12): 1e15}))
    assert absurdo["total_planilha_centavos"] is None and absurdo["total_centavos"] == TOTAL
