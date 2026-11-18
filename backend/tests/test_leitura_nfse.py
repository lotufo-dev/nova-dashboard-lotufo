"""Leitor da NFS-e (bloco 3) contra o texto real de cinco notas (pypdf), leiaute Prefeitura de Cuiaba."""
import pathlib
import re

import pytest
from fpdf import FPDF

from app import leitura_nfse, leitura_pdf

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


# --- DANFSe gerado pelo proprio emissor nacional ("Ambiente Gerador: 2", 11/2026). Texto sintetico no formato que o
# pypdf devolve: o canhoto do rodape ("DATA CIENTIFICAÇÃO ... CHAVE NFS-e") vem ANTES do cabecalho, os rotulos dizem
# "NFS-e" (o gerador do municipio diz "NFS-E") e a CBS e' "Valor Total Apurado - CBS". O leitor recusava com
# `leiaute-desconhecido` e a nota anexada nao nascia.

NACIONAL = "3107-danfse-emissor-nacional.txt"
_TITULOS = ("DANFSe v2.0", "CHAVE DE ACESSO DA NFS-e", "PRESTADOR / FORNECEDOR", "TOMADOR / ADQUIRENTE",
            "DESTINATÁRIO DA OPERAÇÃO", "INTERMEDIÁRIO DA OPERAÇÃO", "SERVIÇO PRESTADO", "TRIBUTAÇÃO MUNICIPAL",
            "TRIBUTAÇÃO FEDERAL", "TRIBUTAÇÃO IBS/CBS", "VALOR TOTAL DA NFS-e", "INFORMAÇÕES COMPLEMENTARES")


def _quadros(texto: str) -> list[str]:
    """O texto partido nos quadros do DANFSe (o canhoto e' o primeiro), cada um com as suas linhas."""
    quadros: list[list[str]] = [[]]
    for linha in texto.strip().split("\n"):
        if linha.startswith(_TITULOS):
            quadros.append([])
        quadros[-1].append(linha)
    return ["\n".join(q) for q in quadros]


def _cabecalho_primeiro(texto: str) -> str:
    canhoto, *resto = _quadros(texto)
    return "\n".join([*resto, canhoto])


def test_le_danfse_do_emissor_nacional_com_o_rodape_na_frente():
    t = _txt(NACIONAL)
    assert t.startswith("DATA CIENTIFICAÇÃO")
    n = leitura_nfse.ler(t)
    assert n["ok"] and n["leiaute"] == "danfse", n
    assert (n["numero"], n["serie_dps"], n["emissao"], n["competencia"], n["periodo"]) == (
        3107, "70000", "2026-08-26", "2026-07", ("2026-07-01", "2026-07-31"))
    assert (n["prestador_cnpj"], n["prestador_nome"]) == ("31200101000130", "CONSTRUTORA ALFA LTDA")
    assert (n["tomador_cnpj"], n["tomador_nome"]) == ("31300101000101", "SECRETARIA DE EXEMPLO")
    assert n["municipio"] == "Cuiabá"
    # centavo impar no bruto e em cada parcela; bruto - retencoes = liquido, ao centavo
    assert (n["valor_centavos"], n["iss_centavos"], n["inss_centavos"], n["irrf_centavos"]) == (
        98765433, 1975309, 4345679, 1481481)
    assert (n["cbs_centavos"], n["ibs_centavos"], n["retencao_total_centavos"], n["liquido_centavos"]) == (
        871111, 96790, 7802469, 90962964)
    assert (n["natureza"], n["numero_medicao"], n["avisos"]) == ("medicao", 14, [])


def test_danfse_do_emissor_nacional_le_igual_com_o_cabecalho_na_frente():
    t = _txt(NACIONAL)
    outro = _cabecalho_primeiro(t)
    assert outro.startswith("DANFSe v2.0") and outro.rstrip().split("\n")[-2].startswith("DATA CIENTIFICAÇÃO")
    assert leitura_nfse.ler(outro) == leitura_nfse.ler(t)


def test_danfse_nao_depende_da_ordem_dos_quadros_nem_das_quebras_de_linha():
    t = _txt(NACIONAL)
    esperado = leitura_nfse.ler(t)
    assert esperado["ok"]
    q = _quadros(t)
    assert len(q) == len(_TITULOS) + 1
    ordens = [q[::-1], q[5:] + q[:5], q[1::2] + q[0::2], sorted(q), sorted(q, key=len)]
    for ordem in ordens:
        assert ordem != q
        assert leitura_nfse.ler("\n".join(ordem)) == esperado
        assert leitura_nfse.ler("  ".join(ordem).replace("\n", "  ")) == esperado
    # o DANFSe do gerador do municipio (rotulos "NFS-E") tambem: o canhoto colado na frente nao muda a leitura
    municipal = _txt("3106-mt402-danfse.txt")
    chave = re.search(r"\d{50}", municipal).group()
    canhoto = f"DATA CIENTIFICAÇÃO: IDENTIFICAÇÃO E ASSINATURA N° NFS-e / CHAVE NFS-e 3106 / {chave}  "
    assert leitura_nfse.ler(canhoto + municipal) == leitura_nfse.ler(municipal)


def _pdf_danfse(quadros: list[str]) -> bytes:
    """PDF sintetico de uma pagina: os quadros desenhados na ordem dada (e' a ordem em que o pypdf devolve o texto),
    com o canhoto no pe' da pagina, onde o DANFSe o imprime."""
    f = FPDF(unit="pt", format="A4")
    f.set_auto_page_break(False)
    f.add_page()
    f.set_font("Helvetica", size=5)
    y = 20
    for quadro in quadros:
        no_pe = quadro.startswith("DATA CIENTIFICAÇÃO")
        for i, linha in enumerate(quadro.split("\n")):
            if no_pe:
                f.text(20, 800 + 6 * i, linha)
            else:
                f.text(20, y, linha)
                y += 5
    return bytes(f.output())


def test_danfse_em_pdf_sintetico_nas_duas_ordens():
    t = _txt(NACIONAL)
    q = _quadros(t)
    rodape_primeiro = leitura_pdf.texto_de_pdf(_pdf_danfse(q))
    cabecalho_primeiro = leitura_pdf.texto_de_pdf(_pdf_danfse(q[1:] + q[:1]))
    assert rodape_primeiro.startswith("DATA CIENTIFICAÇÃO") and cabecalho_primeiro.startswith("DANFSe v2.0")
    assert leitura_nfse.ler(rodape_primeiro) == leitura_nfse.ler(cabecalho_primeiro) == leitura_nfse.ler(t)


def test_danfse_texto_livre_nao_e_lido_como_campo():
    t = _txt(NACIONAL)
    esperado = leitura_nfse.ler(t)
    # a descricao e as informacoes complementares citam tributos, valores e a chave da nota substituida
    outra_chave = re.search(r"\d{50}", _txt("3106-mt402-danfse.txt")).group()
    livre = (t.replace("VALOR IRRF (1,50%) SOBRE O", "IRRF R$ 1,23 ISSQN Apurado R$ 4,56 VALOR IRRF (1,50%) SOBRE O")
              .replace("Totais aproximados",
                       f"NFS-e Subst.: {outra_chave} | VALOR LÍQUIDO DA NFS-e R$ 7,89 | Totais aproximados"))
    assert livre.count("IRRF R$ 1,23") == 1 and outra_chave in livre
    assert leitura_nfse.ler(livre) == esperado
    assert leitura_nfse.ler(_cabecalho_primeiro(livre)) == esperado


@pytest.mark.parametrize("a_mais, campo", [
    # dois valores diferentes para o mesmo rotulo (duas notas no mesmo PDF, texto embaralhado)
    ("VALOR DA OPERAÇÃO / SERVIÇO\nR$ 987.654,34", "valor_centavos"),
    ("VALOR LÍQUIDO DA NFS-e\nR$ 909.629,65", "liquido_centavos"),
    ("ISSQN Apurado\nR$ 0,01", "iss_centavos"),
    ("NÚMERO DA NFS-e\n3108", "numero"),
    ("DATA E HORA DA EMISSÃO DA NFS-e\n27/08/2026 08:00:00", "emissao"),
])
def test_danfse_leitura_ambigua_nao_e_proposta(a_mais, campo):
    t = _txt(NACIONAL)
    for texto in (t, _cabecalho_primeiro(t)):
        n = leitura_nfse.ler(texto.replace("INFORMAÇÕES COMPLEMENTARES", a_mais + "\nINFORMAÇÕES COMPLEMENTARES"))
        assert n == {"ok": False, "motivo": f"campos-ausentes:{campo}", "leiaute": "danfse"}
    # o mesmo valor impresso duas vezes (segunda via na mesma pagina) nao e' ambiguidade
    assert leitura_nfse.ler(t + "VALOR DA OPERAÇÃO / SERVIÇO\nR$987.654,33\n") == leitura_nfse.ler(t)


def test_danfse_com_duas_chaves_de_acesso_nao_e_proposto():
    t = _txt(NACIONAL)
    outra_chave = re.search(r"\d{50}", _txt("3106-mt402-danfse.txt")).group()
    chave = re.search(r"\d{50}", t).group()
    n = leitura_nfse.ler(t.replace(f"3107 / {chave}", f"3106 / {outra_chave}"))
    assert n == {"ok": False, "motivo": "campos-ausentes:chave_de_acesso", "leiaute": "danfse"}


def test_danfse_leitura_parcial_cai_na_fila_com_o_motivo():
    t = _txt(NACIONAL)
    # rotulo separado do valor (o extrator devolveu os dois em quadros diferentes): o campo nao e' adivinhado
    n = leitura_nfse.ler(t.replace("VALOR DA OPERAÇÃO / SERVIÇO\nR$ 987.654,33", "VALOR DA OPERAÇÃO / SERVIÇO"))
    assert n == {"ok": False, "motivo": "campos-ausentes:valor_centavos", "leiaute": "danfse"}
    n = leitura_nfse.ler(t.replace("DATA E HORA DA EMISSÃO DA NFS-e\n26/08/2026 10:42:07", "DATA E HORA DA EMISSÃO DA NFS-e"))
    assert n == {"ok": False, "motivo": "campos-ausentes:emissao", "leiaute": "danfse"}
    # o tomador e' por onde a nota e' conferida contra o orgao: sem ele, fila humana
    n = leitura_nfse.ler(t.replace("TOMADOR / ADQUIRENTE CNPJ / CPF / NIF\n31.300.101/0001-01", "TOMADOR / ADQUIRENTE"))
    assert n == {"ok": False, "motivo": "campos-ausentes:tomador_cnpj", "leiaute": "danfse"}
    # sem o rotulo do numero e sem o CNPJ no quadro do prestador, valem os da chave de acesso
    n = leitura_nfse.ler(t.replace("NÚMERO DA NFS-e\n3107\n", "")
                          .replace("PRESTADOR / FORNECEDOR CNPJ / CPF / NIF\n31.200.101/0001-30", "PRESTADOR / FORNECEDOR"))
    assert n["ok"] and n["numero"] == 3107 and n["prestador_cnpj"] == "31200101000130" and n["avisos"] == []


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
