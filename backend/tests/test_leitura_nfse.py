"""Leitor da NFS-e (bloco 3) contra o texto real de cinco notas (pypdf), leiaute Prefeitura de Cuiaba."""
import pathlib

import pytest

from app import leitura_nfse

FIX = pathlib.Path(__file__).parent / "fixtures" / "nfse"


def _txt(nome):
    return (FIX / nome).read_text(encoding="utf-8")


def test_centavos_moeda_br():
    assert leitura_nfse.centavos("R$4.075.275,90") == 407527590
    assert leitura_nfse.centavos("R$ 1.234,56") == 123456
    assert leitura_nfse.centavos("-") is None
    assert leitura_nfse.centavos("lixo") is None      # nunca zero


def test_le_nota_3105_cultural_mtpar():
    n = leitura_nfse.ler(_txt("3105-cultural-mtpar.txt"))
    assert n["ok"] and n["leiaute"] == "cuiaba"
    assert n["numero"] == 3105
    assert n["emissao"] == "2026-08-21"
    assert n["competencia"] == "2026-07" and n["periodo"] == ("2026-07-01", "2026-07-31")
    assert n["prestador_cnpj"] == "31200101000130"
    assert n["tomador_cnpj"] == "31300202000182"
    assert n["tomador_nome"].startswith("MT PARTICIPACOES")
    assert n["municipio"] == "Cuiabá"
    assert (n["valor_centavos"], n["iss_centavos"], n["inss_centavos"], n["irrf_centavos"]) == (
        407527590, 8150552, 17931214, 6112914)
    assert (n["cbs_centavos"], n["ibs_centavos"]) == (1384208, 153801)
    assert (n["retencao_total_centavos"], n["liquido_centavos"]) == (32194680, 375332910)
    assert n["natureza"] == "medicao" and n["numero_medicao"] == 22
    assert n["avisos"] == []


def test_le_nota_de_varzea_grande_pelo_portal_de_cuiaba():
    n = leitura_nfse.ler(_txt("3102-integra-vg.txt"))
    assert n["ok"] and n["municipio"] == "Várzea Grande"
    assert n["tomador_cnpj"] == "31300101000101"
    assert (n["valor_centavos"], n["iss_centavos"], n["inss_centavos"], n["irrf_centavos"]) == (
        84678831, 1693577, 3725868, 1016145)
    assert (n["cbs_centavos"], n["ibs_centavos"], n["retencao_total_centavos"], n["liquido_centavos"]) == (
        287620, 31958, 6435590, 78243241)
    assert n["competencia"] == "2026-06" and n["numero_medicao"] == 12


def test_le_reajuste_regiao_oeste_sem_periodo():
    n = leitura_nfse.ler(_txt("3104-regiao-oeste-reaj.txt"))
    assert n["ok"] and n["natureza"] == "reajuste" and n["numero_medicao"] == 40
    assert n["valor_centavos"] == 36736486
    assert n["tomador_cnpj"] == "31300303000153"          # Prefeitura de Cuiaba / SMOP
    assert n["periodo"] is None and n["competencia"] == "2026-08"   # sem "PERIODO DE dd/mm A dd/mm": mes da emissao


@pytest.mark.parametrize("nome", ["3103-leblon.txt", "3101-regiao-oeste.txt", "3102-integra-vg.txt",
                                  "3104-regiao-oeste-reaj.txt", "3105-cultural-mtpar.txt"])
def test_autoconferencia_fecha_nas_notas_reais(nome):
    n = leitura_nfse.ler(_txt(nome))
    assert n["ok"]
    assert n["iss_centavos"] + n["inss_centavos"] + n["irrf_centavos"] == n["retencao_total_centavos"]
    assert n["valor_centavos"] - n["retencao_total_centavos"] == n["liquido_centavos"]
    assert n["avisos"] == []


def test_numero_vem_do_conteudo_e_rascunho_e_recusado():
    texto = _txt("3105-cultural-mtpar.txt").replace("Número da Nota Fiscal\n3105", "Número da Nota Fiscal\n0")
    n = leitura_nfse.ler(texto)
    assert n["ok"] is False and n["motivo"] == "sem-numero"


def test_texto_vazio_e_leiaute_desconhecido():
    assert leitura_nfse.ler("")["motivo"] == "sem-texto"
    assert leitura_nfse.ler("DANFSe v2.0 Documento Auxiliar da NFS-e ...")["motivo"] == "leiaute-desconhecido"


def test_autoconferencia_avisa_quando_totais_nao_fecham():
    texto = _txt("3105-cultural-mtpar.txt").replace("R$321.946,80 R$13.842,08", "R$321.946,81 R$13.842,08")
    n = leitura_nfse.ler(texto)
    assert n["ok"] and any("retenção" in a for a in n["avisos"])


def test_tributo_ausente_fica_none_e_nota_de_projeto_sem_inss_e_valida():
    texto = _txt("3105-cultural-mtpar.txt").replace("Vl. CP Retido: R$179.312,14", "Vl. CP Retido: -")
    texto = texto.replace("22ª MEDIÇÃO DA EXECUÇÃO DAS OBRAS", "22ª MEDIÇÃO DA ELABORAÇÃO DE PROJETO DAS OBRAS")
    n = leitura_nfse.ler(texto)
    assert n["ok"] and n["inss_centavos"] is None and n["natureza"] == "projeto"


@pytest.mark.parametrize("descricao, natureza", [
    # Estacoes BRT (NF 2315/2318): execucao de obra com INSS retido, apesar de citar "PROJETO DAS OBRAS" (#564)
    ("7ª MEDIÇÃO DA EXECUÇÃO DE PROJETO DAS OBRAS DAS ESTAÇÕES", "medicao"),
    ("22ª MEDIÇÃO DA ELABORAÇÃO DE PROJETO DAS OBRAS", "projeto"),
    ("1ª MEDIÇÃO DA ELABORAÇÃO DE PROJETO", "projeto"),      # Terminais BRT, NF 2325/2326
    ("22ª MEDIÇÃO DOS SERVIÇOS DE PROJETO DAS OBRAS", "projeto"),   # caso generico da regra anterior continua
])
def test_natureza_pela_descricao_execucao_de_projeto_das_obras(descricao, natureza):
    texto = _txt("3105-cultural-mtpar.txt").replace("22ª MEDIÇÃO DA EXECUÇÃO DAS OBRAS", descricao)
    assert descricao in texto
    assert leitura_nfse.ler(texto)["natureza"] == natureza


# --- DANFSe v2.0 (emissor nacional): nota 3106 da MT-402, 27a medicao. O texto veio da extracao do anexo pelo
# Microsoft Graph (o PDF nao pode ser baixado nesta maquina); o perfil normaliza espacos e quebras de linha, e
# o teste abaixo prova que a leitura nao muda se o extrator do produto (pypdf) quebrar as linhas em outro lugar.

def test_le_danfse_3106_mt402():
    n = leitura_nfse.ler(_txt("3106-mt402-danfse.txt"))
    assert n["ok"] and n["leiaute"] == "danfse"
    assert (n["numero"], n["emissao"], n["competencia"], n["periodo"]) == (
        3106, "2026-09-14", "2026-08", ("2026-08-01", "2026-08-31"))
    assert (n["prestador_cnpj"], n["tomador_cnpj"]) == ("31200101000130", "31300101000101")
    assert n["tomador_nome"].startswith("SECRETARIA DE ESTADO DE INFRAESTRUTURA")
    assert n["municipio"] == "Cuiabá"
    assert (n["valor_centavos"], n["iss_centavos"], n["inss_centavos"], n["irrf_centavos"]) == (
        71919072, 1438381, 3164439, 863029)
    assert (n["cbs_centavos"], n["ibs_centavos"], n["retencao_total_centavos"], n["liquido_centavos"]) == (
        244280, 27142, 5465849, 66453223)
    assert (n["natureza"], n["numero_medicao"], n["avisos"]) == ("medicao", 27, [])


def test_danfse_independe_das_quebras_de_linha():
    t = _txt("3106-mt402-danfse.txt")
    assert leitura_nfse.ler(t.replace("  ", "\n")) == leitura_nfse.ler(t)
    assert leitura_nfse.ler(t.replace("  ", " \n ").replace(" R$", "\nR$")) == leitura_nfse.ler(t)


def test_danfse_numero_que_nao_bate_com_a_chave_vira_aviso():
    t = _txt("3106-mt402-danfse.txt").replace("NÚMERO DA NFS-E  3106", "NÚMERO DA NFS-E  3207")
    n = leitura_nfse.ler(t)
    assert n["ok"] and n["numero"] == 3207 and any("chave de acesso" in a for a in n["avisos"])


# --- Centi (Prefeitura de Tangara da Serra): nota 20260000812 da Guaxe, consorciada do Integra BRT, 11a medicao
# (Varzea Grande). E' a nota de consorciada que a FRC soma: bruto, INSS, IR, ISS retido e liquido.

def test_le_nota_centi_da_guaxe():
    n = leitura_nfse.ler(_txt("2026812-integra-beta-vg.txt"))
    assert n["ok"] and n["leiaute"] == "centi"
    assert (n["numero"], n["emissao"], n["competencia"], n["periodo"]) == (
        20260000812, "2026-06-24", "2026-05", ("2026-05-01", "2026-05-31"))
    assert (n["prestador_cnpj"], n["tomador_cnpj"], n["prestador_nome"]) == (
        "31200202000100", "31300101000101", "ENGENHARIA BETA S.A.")
    assert n["municipio"] == "Várzea Grande"           # impresso em maiusculas
    assert (n["valor_centavos"], n["inss_centavos"], n["irrf_centavos"], n["iss_centavos"]) == (
        91447797, 4023702, 1097373, 1828956)
    assert (n["retencao_total_centavos"], n["liquido_centavos"]) == (6950031, 84497766)   # FRC 18: 69.500,31
    assert (n["natureza"], n["numero_medicao"], n["avisos"]) == ("medicao", 11, [])


def test_le_nota_centi_da_guaxe_modelo_tributacao_federal():
    # 09/10/2026, 15a medicao do Integra: o quadro "RETENÇÕES FEDERAIS" virou "TRIBUTAÇÃO FEDERAL" (rotulos
    # "Contrib. Previdenciária - Retida", "IRRF"...), mesmos cinco valores na mesma ordem
    n = leitura_nfse.ler(_txt("2026913-integra-beta-cba-tributacao-federal.txt"))
    assert n["ok"] and n["leiaute"] == "centi" and n["avisos"] == []
    assert (n["numero"], n["prestador_cnpj"], n["municipio"]) == (20260000913, "31200202000100", "Cuiabá")
    assert (n["valor_centavos"], n["inss_centavos"], n["irrf_centavos"], n["iss_centavos"], n["liquido_centavos"]) == (
        332493680, 14629721, 3989924, 6649874, 307224161)
    assert (n["natureza"], n["numero_medicao"]) == ("medicao", 15)


def test_centi_numero_que_nao_bate_com_a_chave_vira_aviso_e_rascunho_e_recusado():
    t = _txt("2026812-integra-beta-vg.txt")
    n = leitura_nfse.ler(t.replace("Número da Nota\n20260000812\n7c3e", "Número da Nota\n20260000814\n7c3e"))
    assert n["ok"] and any("chave de acesso" in a for a in n["avisos"])
    n = leitura_nfse.ler(t.replace("Número da Nota\n20260000812", "Número da Nota\n0"))
    assert n["ok"] is False and n["motivo"] == "sem-numero"
