"""Prova das regras REAIS de cadastro/espelho/*.yaml contra os gabaritos (spec §4.3).

Cada obra so' fica `ativa` quando reproduz ao centavo as notas de gabarito e um espelho real
recente. Os gabaritos sao os do levantamento de 2026-09-16 §6 (14 notas) e os espelhos reais
gravados nos modelos do motor antigo (2026-09-22).
"""
import io
import os
import zipfile
from pathlib import Path

import pytest
from app import cadastro_arquivos, cli, espelho, espelho_docx


def _cadastro_real() -> bool:
    """So' roda contra o cadastro REAL (repositorio privado `lotufo-cadastro`), nunca contra o exemplo."""
    pasta = os.environ.get("DASH_CADASTRO_DIR")
    return bool(pasta) and Path(pasta).is_dir() and Path(pasta).resolve() != (cli.REPOSITORIO / "cadastro-exemplo").resolve()


pytestmark = pytest.mark.skipif(
    not _cadastro_real(),
    reason="regressão contra os valores reais: defina DASH_CADASTRO_DIR apontando para o cadastro real "
           "(a CI e o cadastro-exemplo não têm esses valores)")


def brl(t: str) -> int:
    return int(t.replace(".", "").replace(",", ""))


@pytest.fixture(scope="module")
def cadastro():
    cad = cadastro_arquivos.preparar(cli.raiz_padrao())
    return {e["contrato"]: e for e in cad["espelho"]}


def _saidas(cadastro, obra, entradas):
    regra = cadastro[obra]["regra"]
    return regra, {s["chave"]: s for s in espelho.calcular(regra, entradas)}


def linha(s):
    return tuple(s[k] for k in ("valor", "mo", "material", "inss", "iss", "irrf"))


def test_situacao_das_obras(cadastro):
    assert {k: v["situacao"] for k, v in cadastro.items()} == {
        "MT-402": "ativa", "MT-401": "ativa", "Cavalaria": "ativa",
        "MT-388": "ativa", "Parque Atalaia": "ativa", "Integra BRT": "ativa", "Estações BRT": "ativa",
        "Complexo Cultural": "ativa", "Espaço Show": "ativa", "Granito": "ativa", "Complexo Orla": "ativa",
        "Complexo Xtreme": "ativa", "5 Bairros": "ativa", "Região Oeste": "ativa", "Leblon": "ativa",
        "Coxipó 3ª Etapa": "ativa", "Coxipó 2ª Etapa": "ativa", "Maternidade VG": "ativa",
        "Terminais BRT": "ativa"}      # ativada em 2026-10-09 com o Terminal do CPA


# (obra, entradas em BRL, {chave da saida: (valor, mo, material, inss, iss, irrf) em BRL})
GABARITOS = [
    ("MT-402", {"medicao": "278.509,92", "reajuste": "19.580,95"}, {
        "medicao": ("278.509,92", "111.403,96", "167.105,96", "12.254,43", "5.570,19", "3.342,12"),
        "reajuste": ("19.580,95", "7.832,38", "11.748,57", "861,56", "391,61", "234,97")}),
    ("MT-401", {"medicao": "985.375,86", "reajuste": "133.083,30"}, {
        "medicao": ("985.375,86", "394.150,34", "591.225,52", "43.356,53", "19.707,51", "11.824,51"),
        "reajuste": ("133.083,30", "53.233,32", "79.849,98", "5.855,66", "2.661,66", "1.597,00")}),
    ("Cavalaria", {"medicao": "584.463,68", "reajuste": "103.099,39"}, {
        "medicao": ("584.463,68", "233.785,47", "350.678,21", "25.716,40", "11.689,27", "7.013,56"),
        "reajuste": ("103.099,39", "41.239,75", "61.859,64", "4.536,37", "2.061,98", "1.237,19")}),
    ("MT-388", {"medicao": "634.529,58", "reajuste": "38.655,83"}, {
        "caceres-medicao": ("528.436,23", "211.374,49", "317.061,74", "23.251,19", "15.853,08", "6.341,23"),
        "porto-medicao": ("106.093,35", "42.437,34", "63.656,01", "4.668,10", "2.121,86", "1.273,12"),
        "caceres-reajuste": ("32.192,58", "12.877,03", "19.315,55", "1.416,47", "965,77", "386,31"),
        "porto-reajuste": ("6.463,25", "2.585,30", "3.877,95", "284,38", "129,26", "77,55")}),
    ("Parque Atalaia", {"medicao": "780.224,80", "reajuste": "623.268,84"}, {
        "med-cba-lotufo": ("366.518,40", "146.607,36", "219.911,04", "16.126,80", "7.330,36", "4.398,22"),
        "med-vg-lotufo": ("257.661,44", "103.064,57", "154.596,87", "11.337,10", "5.153,22", "3.091,93"),
        "reaj-cba-lotufo": ("292.786,76", "117.114,70", "175.672,06", "12.882,61", "5.855,73", "3.513,44"),
        "reaj-vg-lotufo": ("205.828,30", "82.331,32", "123.496,98", "9.056,44", "4.116,56", "2.469,93"),
        "med-cba-rivoli": ("91.629,60", "36.651,84", "54.977,76", "4.031,70", "1.832,59", "1.099,55")}),
    ("Integra BRT", {"medicao": "7.382.048,52", "projeto": "0"}, {
        "exec-cba-lotufo": ("3.117.641,10", "1.247.056,44", "1.870.584,66", "137.176,20", "62.352,82", "37.411,69"),
        "exec-vg-lotufo": ("499.562,67", "199.825,06", "299.737,61", "21.980,75", "9.991,25", "5.994,75")}),
    ("Estações BRT", {"medicao": "3.198.742,98", "reajuste": "202.800,30", "projeto": "0", "reajuste-projeto": "0"}, {
        "exec-cba": ("2.408.929,89", "963.571,95", "1.445.357,94", "105.992,91", "48.178,59", "28.907,15"),
        "exec-vg": ("789.813,09", "315.925,23", "473.887,86", "34.751,77", "15.796,26", "9.477,75"),
        "reaj-cba": ("152.726,15", "61.090,46", "91.635,69", "6.719,95", "3.054,52", "1.832,71"),
        "reaj-vg": ("50.074,15", "20.029,66", "30.044,49", "2.203,26", "1.001,48", "600,88")}),
    # MTPAR: tributos com ROUND na celula (`na_celula`), IRRF 1,5%; espelhos reais mais recentes da pasta da Maria
    ("Complexo Cultural", {"medicao": "2.896.868,02", "reajuste": "0"}, {
        "medicao": ("2.896.868,02", "1.158.747,20", "1.738.120,82", "127.462,19", "57.937,36", "43.453,02")}),
    ("Espaço Show", {"medicao": "54.346,50", "reajuste": "7.347,64"}, {
        "medicao": ("54.346,50", "21.738,60", "32.607,90", "2.391,25", "1.086,93", "815,20"),
        "reajuste": ("7.347,64", "2.939,05", "4.408,59", "323,30", "146,95", "110,21")}),
    ("Granito", {"medicao": "500.126,83"}, {
        "medicao": ("500.126,83", "200.050,73", "300.076,10", "22.005,58", "10.002,54", "7.501,90")}),
    ("Complexo Orla", {"medicao": "943.079,91", "reajuste": "47.113,04"}, {
        "medicao": ("943.079,91", "377.231,96", "565.847,95", "41.495,52", "18.861,60", "14.146,20"),
        "reajuste": ("47.113,04", "18.845,21", "28.267,83", "2.072,97", "942,26", "706,70")}),
    ("Complexo Xtreme", {"medicao": "37.867,67", "reajuste": "5.445,37"}, {
        "medicao": ("37.867,67", "15.147,06", "22.720,61", "1.666,18", "757,35", "568,02"),
        "reajuste": ("5.445,37", "2.178,14", "3.267,23", "239,60", "108,91", "81,68")}),
    ("5 Bairros", {"medicao": "395.291,44", "reajuste": "48.722,90"}, {
        "medicao": ("395.291,44", "158.116,57", "237.174,87", "17.392,82", "7.905,82", "4.743,50"),
        "reajuste": ("48.722,90", "19.489,16", "29.233,74", "2.143,80", "974,45", "584,67")}),
    ("Região Oeste", {"medicao": "184.360,14", "reajuste": "41.917,13"}, {
        "medicao": ("184.360,14", "73.744,05", "110.616,09", "8.111,84", "3.687,20", "2.212,32"),
        "reajuste": ("41.917,13", "16.766,85", "25.150,28", "1.844,35", "838,34", "503,00")}),
    ("Leblon", {"medicao": "4.524.929,08", "reajuste": "211.053,16"}, {
        "medicao-lotufo": ("2.262.464,54", "904.985,81", "1.357.478,73", "99.548,44", "45.249,29", "27.149,57"),
        "medicao-rivoli": ("2.262.464,54", "904.985,81", "1.357.478,73", "99.548,44", "45.249,29", "27.149,57"),
        "reajuste-lotufo": ("105.526,58", "42.210,63", "63.315,95", "4.643,17", "2.110,53", "1.266,32"),
        "reajuste-rivoli": ("105.526,58", "42.210,63", "63.315,95", "4.643,17", "2.110,53", "1.266,32")}),
    ("Coxipó 3ª Etapa", {"sudeco": "190.254,15", "fonte-100": "354.184,69", "reajuste": "18.289,26"}, {
        "medicao-sudeco": ("190.254,15", "76.101,66", "114.152,49", "8.371,18", "3.805,08", "2.283,05"),
        "medicao-fonte-100": ("354.184,69", "141.673,88", "212.510,81", "15.584,13", "7.083,69", "4.250,22"),
        "reajuste": ("18.289,26", "7.315,70", "10.973,56", "804,72", "365,78", "219,47")}),
    ("Coxipó 2ª Etapa", {"medicao": "0", "reajuste": "83.301,51"}, {
        "reajuste": ("83.301,51", "33.320,60", "49.980,91", "3.665,27", "1.666,03", "999,62")}),
    # medicao: nota emitida da 1a (arredonda; o espelho antigo cortava); reajuste: sem nota, pela mesma regra
    ("Maternidade VG", {"medicao": "337.189,96", "reajuste": "21.015,97"}, {
        "medicao": ("337.189,96", "134.875,98", "202.313,98", "14.836,36", "6.743,80", "4.046,28"),
        "reajuste": ("21.015,97", "8.406,39", "12.609,58", "924,70", "420,32", "252,19")}),
]


def test_terminais_brt_1a_duas_notas_de_projeto(cadastro):
    # espelhos reais de 15/09/2026 (Terminal VG e Terminal do Porto + CCO): ISS 5% e IRRF 4,8% truncados
    _, s = _saidas(cadastro, "Terminais BRT", {"projeto-vg": brl("148.117,01"), "projeto-porto": brl("224.259,43")})
    assert (s["proj-vg"]["valor"], s["proj-vg"]["iss"], s["proj-vg"]["irrf"]) == (14811701, 740585, 710961)
    assert (s["proj-porto"]["valor"], s["proj-porto"]["iss"], s["proj-porto"]["irrf"]) == (22425943, 1121297, 1076445)
    assert s["proj-vg"]["mo"] is None and s["proj-vg"]["inss"] is None


def test_terminais_um_espelho_por_terminal(cadastro):
    # 1a medicao real (07 e 08/2026): VG 148.117,01 e Porto 224.259,43; o CPA segue a mesma conta
    _, s = _saidas(cadastro, "Terminais BRT", {"projeto-vg": brl("148.117,01"), "projeto-porto": brl("224.259,43"),
                                               "projeto-cpa": brl("100.000,00")})
    assert (s["proj-vg"]["iss"], s["proj-vg"]["irrf"]) == (740585, 710961)
    assert (s["proj-porto"]["iss"], s["proj-porto"]["irrf"]) == (1121297, 1076445)
    assert (s["proj-cpa"]["valor"], s["proj-cpa"]["iss"], s["proj-cpa"]["irrf"]) == (10000000, 500000, 480000)


@pytest.mark.parametrize("obra,entradas,esperado", GABARITOS, ids=[g[0] for g in GABARITOS])
def test_regra_real_reproduz_o_gabarito(cadastro, obra, entradas, esperado):
    _, saidas = _saidas(cadastro, obra, {k: brl(v) for k, v in entradas.items()})
    for chave, valores in esperado.items():
        assert linha(saidas[chave]) == tuple(brl(v) for v in valores), chave


def test_brt_projeto_e_o_resto_da_encomind(cadastro):
    _, s = _saidas(cadastro, "Integra BRT", {"medicao": 0, "projeto": brl("15.351,18")})
    assert (s["proj-cba-lotufo"]["valor"], s["proj-cba-lotufo"]["iss"], s["proj-cba-lotufo"]["irrf"]) == (752208, 37610, 36105)
    assert (s["proj-tangara-guaxe"]["valor"], s["proj-tangara-guaxe"]["iss"]) == (752208, None)
    assert s["proj-cba-encomind"]["valor"] == 30702              # 307,02 do espelho real
    assert s["proj-cba-lotufo"]["mo"] is None and s["proj-cba-lotufo"]["inss"] is None


def test_oriundi_46a_rivoli_vg_herda_o_ponto_flutuante_do_excel(cadastro):
    # espelho real enviado em 03/08/2026: o resto 16.910,50 e' 16.910,4999... na celula e o TRUNC
    # do Excel da' MO 6.764,19 (a conta exata daria 6.764,20 e ISS 338,21)
    _, s = _saidas(cadastro, "Parque Atalaia", {"medicao": brl("204.826,68"), "reajuste": 0})
    assert linha(s["med-vg-rivoli"]) == tuple(brl(v) for v in
                                              ("16.910,50", "6.764,19", "10.146,31", "744,06", "338,20", "202,92"))


def test_estacoes_projeto_da_2a(cadastro):
    _, s = _saidas(cadastro, "Estações BRT", {"medicao": 0, "reajuste": 0, "projeto": brl("937.803,58"),
                                              "reajuste-projeto": brl("59.456,74")})
    assert (s["proj-cba"]["iss"], s["proj-cba"]["irrf"]) == (4689017, 4501457)
    assert (s["reaj-proj-cba"]["iss"], s["reaj-proj-cba"]["irrf"]) == (297283, 285392)


@pytest.mark.parametrize("obra,entradas,esperado", GABARITOS, ids=[g[0] for g in GABARITOS])
def test_modelos_reais_recebem_os_valores(cadastro, obra, entradas, esperado):
    regra, saidas = _saidas(cadastro, obra, {k: brl(v) for k, v in entradas.items()})
    for chave in esperado:
        modelo = cadastro[obra]["modelos"][chave]["caminho"].read_bytes()
        controles = espelho.formatar_controles(saidas[chave], 10, "2026-05")
        docx = espelho_docx.preencher(modelo, controles)
        with zipfile.ZipFile(io.BytesIO(docx)) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        assert controles["valor"] in xml and controles["valor_extenso"] in xml and "10ª" in xml
        assert "01/05/2026 A 31/05/2026" in xml or "MAIO/2026" in xml     # Regiao Oeste: controle mes_ano
        if saidas[chave]["irrf"] is not None:
            assert controles["irrf"] in xml
