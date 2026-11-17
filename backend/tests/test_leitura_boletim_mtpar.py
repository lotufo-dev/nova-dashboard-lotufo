"""Leitor do boletim da MT-PAR (#753). Boletins sinteticos no modelo do orgao (`tests/boletim_mtpar.py`): obra,
valores e nomes inventados."""
import pytest

from app import leitura_boletim_mtpar as leitor, leitura_pdf
from tests import boletim_mtpar as bm

VALOR = 12_345_679          # R$ 123.456,79: centavo impar
REAJUSTE = 1_234_567        # R$ 12.345,67


def test_valor_colado_ao_rotulo_e_igual_ao_do_controle_financeiro_e_proposto():
    r = leitor.ler(bm.boletim(numero=7, valor=VALOR, reajuste=REAJUSTE))
    assert (r["ok"], r["motivo"], r["documento"]) == (True, None, "medicao")
    assert r["campos"] == {"numero": 7, "data": "2026-08-01", "valor_centavos": VALOR}
    assert r["leituras"] == {"rotulo_centavos": VALOR, "controle_centavos": VALOR}
    assert (r["contratos"], r["contratos_do_quadro"], r["numero_do_rotulo"]) == (["45/2025"], ["45/2025"], 7)


def test_valor_em_bloco_separado_dos_rotulos_vai_para_a_conferencia_com_a_leitura_do_quadro():
    r = leitor.ler(bm.boletim(valor=VALOR, colado=False))
    assert (r["ok"], r["motivo"]) == (False, "valor-fora-do-rotulo")
    assert r["leituras"] == {"rotulo_centavos": None, "controle_centavos": VALOR}
    # o numero e a data saem mesmo sem o valor; o valor nunca e' proposto por uma leitura so'
    assert r["campos"] == {"numero": 7, "data": "2026-08-01"}


@pytest.mark.parametrize("visto_na", [2, 5])
def test_visto_e_achado_pelos_rotulos_na_pagina_2_e_na_5(visto_na):
    paginas = bm.boletim(valor=VALOR, visto_na=visto_na)
    assert "Visto" in paginas[visto_na - 1] and all("Visto" not in p for i, p in enumerate(paginas) if i != visto_na - 1)
    r = leitor.ler(paginas)
    assert r["ok"] and r["campos"]["valor_centavos"] == VALOR


@pytest.mark.parametrize("reajuste", [REAJUSTE, 0, None])
def test_quadro_com_e_sem_as_colunas_de_reajuste(reajuste):
    """Sete valores por linha (com o reajuste, mesmo zerado) ou cinco (a obra sem reajuste): a mesma leitura."""
    r = leitor.ler(bm.boletim(valor=VALOR, reajuste=reajuste))
    assert r["ok"] and r["leituras"]["controle_centavos"] == VALOR


def test_leituras_que_nao_batem_voltam_as_duas_e_nenhum_valor():
    r = leitor.ler(bm.boletim(valor=VALOR, valor_no_quadro=VALOR + 1))        # um centavo de diferenca
    assert (r["ok"], r["motivo"]) == (False, "leituras-divergentes")
    assert r["leituras"] == {"rotulo_centavos": VALOR, "controle_centavos": VALOR + 1}
    assert "valor_centavos" not in r["campos"]


def test_acumulado_anterior_e_saldo_do_visto_nao_entram_na_conferencia():
    """Os dois campos vem errados em parte das obras: valores absurdos neles nao mudam a leitura."""
    certo = leitor.ler(bm.boletim(valor=VALOR))
    torto = leitor.ler(bm.boletim(valor=VALOR, anteriores=1, saldo=99_999_999_999))
    assert torto == certo and torto["ok"]


@pytest.mark.parametrize("marca,palavra", [("ª", "medição"), ("º", "medição"), ("ª", "Medição"), ("º", "MEDIÇÃO"),
                                           ("a", "medicao"), ("", "medição")])
def test_rotulo_da_linha_com_qualquer_ordinal_e_caixa(marca, palavra):
    quadro = bm.controle([bm.linha(6, 7_000_003, 700_001), bm.linha(7, VALOR, REAJUSTE, marca=marca, palavra=palavra)])
    r = leitor.ler([bm.capa(7), bm.visto(7, VALOR), quadro])
    assert r["ok"] and r["leituras"]["controle_centavos"] == VALOR


def test_quadro_que_continua_na_pagina_seguinte_sem_o_titulo():
    primeira = bm.controle([bm.linha(n, 1_000_001 * n, 0) for n in range(1, 6)])
    segunda = bm.controle([bm.linha(6, 7_000_003, 700_001), bm.linha(7, VALOR, REAJUSTE)], titulo=False)
    assert "CONTROLE FINANCEIRO" not in segunda
    r = leitor.ler([bm.capa(7), bm.dados_gerais(7), bm.visto(7, VALOR), primeira, segunda, bm.resumo(7)])
    assert r["ok"] and r["leituras"]["controle_centavos"] == VALOR


def test_linha_do_quadro_que_nao_fecha_nao_e_lida():
    """Colunas fora de ordem na extracao (o total onde devia estar o PI): a linha nao vale como leitura."""
    torta = f"7ª medição 01/07/2026 a 31/07/2026 31 120 R$ {bm.brl(VALOR)} R$ 900.000,00 R$ 1,00 R$ 2,00 R$ 3,00 R$ 4,00 R$ 5,00"
    r = leitor.ler([bm.capa(7), bm.visto(7, VALOR), bm.controle([torta])])
    assert (r["ok"], r["motivo"]) == (False, "controle-nao-lido")
    assert r["leituras"] == {"rotulo_centavos": VALOR, "controle_centavos": None}


def test_medicao_com_duas_linhas_no_quadro_nao_e_lida():
    quadro = bm.controle([bm.linha(7, VALOR, REAJUSTE), bm.linha(7, VALOR + 100, REAJUSTE)])
    r = leitor.ler([bm.capa(7), bm.visto(7, VALOR), quadro])
    assert r["motivo"] == "controle-nao-lido"


def test_sem_o_quadro_de_controle_financeiro_o_valor_nao_e_proposto():
    r = leitor.ler([bm.capa(7), bm.visto(7, VALOR), bm.resumo(7)])
    assert (r["ok"], r["motivo"]) == (False, "controle-nao-lido")
    assert r["leituras"] == {"rotulo_centavos": VALOR, "controle_centavos": None}


def test_digito_colado_depois_dos_centavos_nao_e_valor():
    """Revisao da PR #760: "123.456,795" nao e' R$ 123.456,79. O valor com digito grudado no fim nao e' lido, nem no
    Visto nem na linha do quadro."""
    paginas = bm.boletim(numero=7, valor=VALOR)
    visto = next(i for i, p in enumerate(paginas) if "Visto" in p)
    grudado = list(paginas)
    grudado[visto] = paginas[visto].replace(f"{bm.brl(VALOR)} R$ Valor Total Acumulado", f"{bm.brl(VALOR)}5 R$ Valor Total Acumulado")
    assert grudado[visto] != paginas[visto]
    r = leitor.ler(grudado)
    assert (r["ok"], r["motivo"]) == (False, "valor-fora-do-rotulo")
    assert r["leituras"] == {"rotulo_centavos": None, "controle_centavos": VALOR}
    quadro = next(i for i, p in enumerate(paginas) if "CONTROLE FINANCEIRO" in p)
    grudado = list(paginas)
    grudado[quadro] = paginas[quadro].replace(f"31 120 R$ {bm.brl(VALOR)} R$", f"31 120 R$ {bm.brl(VALOR)}5 R$")
    assert grudado[quadro] != paginas[quadro]
    r = leitor.ler(grudado)
    assert (r["ok"], r["motivo"]) == (False, "controle-nao-lido")
    assert r["leituras"] == {"rotulo_centavos": VALOR, "controle_centavos": None}
    # o "TOTAL REAJUSTE" tambem
    do_reajuste = bm.reajuste(numero=7, valor=REAJUSTE)
    do_reajuste[1] = do_reajuste[1].replace(f"TOTAL REAJUSTE R$ {bm.brl(REAJUSTE)}", f"TOTAL REAJUSTE R$ {bm.brl(REAJUSTE)}1")
    assert leitor.ler(do_reajuste)["leituras"] == {"rotulo_centavos": None, "controle_centavos": REAJUSTE}


def test_valor_zero_e_centavos_inteiros():
    r = leitor.ler(bm.boletim(valor=0, reajuste=0))
    assert r["ok"] and r["campos"]["valor_centavos"] == 0
    r = leitor.ler(bm.boletim(valor=1, reajuste=2))                     # R$ 0,01 e R$ 0,02: a soma da linha fecha
    assert r["ok"] and r["campos"]["valor_centavos"] == 1
    r = leitor.ler(bm.boletim(valor=345_678_901, reajuste=23_456_789))  # milhoes, com centavo impar na soma
    assert r["ok"] and r["campos"]["valor_centavos"] == 345_678_901


# --- o numero da medicao --------------------------------------------------------------------------------------

def test_numero_vem_da_capa_e_nao_do_rodape():
    """O rodape do arquivo ja' veio com o numero da medicao anterior: a capa manda."""
    paginas = bm.boletim(numero=7, valor=VALOR)
    paginas[0] = bm.capa(7, rodape="MED 06 - OBRA DE EXEMPLO REV01 Página 1 de 20")
    paginas[-1] = bm.resumo(6)                                          # o resumo e o rodape dele dizem "6ª" e "MED 06"
    r = leitor.ler(paginas)
    assert r["ok"] and r["campos"]["numero"] == 7


def test_sem_a_capa_o_numero_vem_do_campo_dos_dados_gerais():
    paginas = bm.boletim(numero=7, valor=VALOR)[1:]                     # sem a pagina da capa
    r = leitor.ler(paginas)
    assert r["ok"] and r["campos"]["numero"] == 7
    # sem a capa, o contrato so' sai no quadro: nao e' a fonte principal
    assert (r["contratos"], r["contratos_do_quadro"]) == ([], ["45/2025"])


def test_sem_capa_nem_campo_o_numero_nao_e_lido_e_nada_e_proposto():
    r = leitor.ler([bm.visto(7, VALOR), bm.controle([bm.linha(7, VALOR, REAJUSTE)])])
    assert (r["ok"], r["motivo"]) == (False, "numero-nao-lido")
    assert "numero" not in r["campos"] and "valor_centavos" not in r["campos"]
    # o numero impresso no rotulo do Visto nao serve de numero da medicao: nada do quadro e' lido por ele
    assert r["leituras"] == {"rotulo_centavos": VALOR, "controle_centavos": None}
    assert r["numero_do_rotulo"] == 7                                   # so' a reserva da recusa de "outra medicao"


def test_capa_nao_reconhecida_e_sem_o_campo_o_rotulo_do_visto_recusa_a_outra_medicao():
    """Revisao da PR #760: com a capa nao reconhecida e sem o campo dos dados gerais, o boletim da 6a medicao entrava
    na 7a. O numero do rotulo do Visto e' a reserva da recusa; ele nao vira o numero lido e nada e' proposto."""
    paginas = bm.sem_capa_reconhecida(bm.boletim(numero=6, valor=7_000_003), sem_campo=True)
    lido = leitor.ler(paginas)
    assert (lido["ok"], lido["motivo"], lido["numero_do_rotulo"]) == (False, "numero-nao-lido", 6)
    assert "numero" not in lido["campos"] and "valor_centavos" not in lido["campos"]
    assert lido["leituras"] == {"rotulo_centavos": 7_000_003, "controle_centavos": None}
    assert leitor.recusa(lido, "execucao", 7, "045/2025/MTPAR") == \
        "Este boletim é da 6ª medição, e esta é a 7ª: escolha o PDF da 7ª medição"
    assert leitor.recusa(lido, "execucao", 6, "045/2025/MTPAR") is None
    # o mesmo pelo PDF gerado
    do_pdf = leitor.ler_pdf(bm.pdf(paginas))
    assert (do_pdf["motivo"], do_pdf["numero_do_rotulo"]) == ("numero-nao-lido", 6)


def test_a_capa_e_o_campo_mandam_antes_do_rotulo_do_visto():
    """A reserva so' vale sem as outras fontes: com a capa lida, e' o numero dela que recusa."""
    lido = leitor.ler([bm.capa(7), bm.visto(6, VALOR), bm.controle([bm.linha(6, VALOR, 0), bm.linha(7, VALOR, 0)])])
    assert (lido["campos"]["numero"], lido["numero_do_rotulo"]) == (7, 6)
    assert leitor.recusa(lido, "execucao", 7, "045/2025/MTPAR") is None       # numero-divergente: nada e' proposto
    assert leitor.recusa(lido, "execucao", 6, "045/2025/MTPAR") == \
        "Este boletim é da 7ª medição, e esta é a 6ª: escolha o PDF da 6ª medição"


def test_sem_fonte_nenhuma_do_numero_o_boletim_nao_e_recusado_e_nada_e_proposto():
    """Sem capa, sem o campo e com dois rotulos de medicoes diferentes no Visto: nenhuma fonte diz o numero."""
    visto = bm.visto(7, VALOR) + " Valor Total da 6ª Medição ........ 70.000,03 R$"
    lido = leitor.ler([visto, bm.controle([bm.linha(6, 7_000_003, 0), bm.linha(7, VALOR, 0)])])
    assert (lido["ok"], lido["motivo"], lido["numero_do_rotulo"]) == (False, "numero-nao-lido", None)
    assert "numero" not in lido["campos"] and "valor_centavos" not in lido["campos"]
    assert leitor.recusa(lido, "execucao", 7, "045/2025/MTPAR") is None
    assert leitor.recusa(lido, "execucao", 9, "045/2025/MTPAR") is None


def test_capa_com_dois_numeros_nao_decide():
    capa = bm.capa(7, rodape="6ª Medição - Junho/2026")
    r = leitor.ler([capa, bm.visto(7, VALOR), bm.controle([bm.linha(7, VALOR, REAJUSTE)])])
    assert r["motivo"] == "numero-nao-lido"


def test_capa_de_uma_medicao_e_visto_de_outra_nao_propoe_valor():
    r = leitor.ler([bm.capa(7), bm.visto(6, VALOR), bm.controle([bm.linha(6, VALOR, 0), bm.linha(7, VALOR, 0)])])
    assert (r["ok"], r["motivo"]) == (False, "numero-divergente")
    assert r["campos"] == {"numero": 7, "data": "2026-08-01"}


# --- recusa: outra medicao, outra obra, outro tipo -------------------------------------------------------------

def test_recusa_o_boletim_de_outra_medicao_por_extenso():
    lido = leitor.ler(bm.boletim(numero=6, valor=VALOR))
    assert leitor.recusa(lido, "execucao", 7, "045/2025/MTPAR") == \
        "Este boletim é da 6ª medição, e esta é a 7ª: escolha o PDF da 7ª medição"
    assert leitor.recusa(lido, "execucao", 6, "045/2025/MTPAR") is None


def test_recusa_o_boletim_de_outra_obra_por_extenso():
    lido = leitor.ler(bm.boletim(numero=7, valor=VALOR, contrato="012/2023"))
    assert leitor.recusa(lido, "execucao", 7, "045/2025/MTPAR") == \
        "Este boletim é de outra obra: traz o contrato 12/2023, e o desta obra é o 45/2025"
    assert leitor.recusa(lido, "execucao", 7, "012/2023/MTPAR") is None
    assert leitor.recusa(lido, "execucao", 7, "contrato sem número") is None    # sem o que comparar, nao recusa
    assert leitor.recusa(lido, "execucao", 7, None) is None


def test_quadro_com_o_ano_do_contrato_trocado_nao_recusa_o_boletim_certo():
    """Revisao da PR #760: o quadro de controle financeiro ja' veio com o ano do contrato trocado. Sozinho ele nao e'
    fonte confiavel: so' a capa (ou a carta do reajuste) recusa o boletim de outra obra."""
    paginas = bm.boletim(numero=7, valor=VALOR, contrato_no_quadro="045/2024")
    # com a capa lida e certa, o quadro nem entra na conferencia
    lido = leitor.ler(paginas)
    assert (lido["ok"], lido["contratos"], lido["contratos_do_quadro"]) == (True, ["45/2025"], ["45/2024"])
    assert leitor.recusa(lido, "execucao", 7, "045/2025/MTPAR") is None
    assert leitor.contrato_nao_conferido(lido, "045/2025/MTPAR") is None
    # com a capa nao reconhecida, so' o quadro foi lido e discorda: nao recusa, e o contrato fica por conferir
    lido = leitor.ler(bm.sem_capa_reconhecida(paginas))
    assert (lido["campos"]["numero"], lido["contratos"], lido["contratos_do_quadro"]) == (7, [], ["45/2024"])
    assert leitor.recusa(lido, "execucao", 7, "045/2025/MTPAR") is None
    assert leitor.contrato_nao_conferido(lido, "045/2025/MTPAR") == \
        "O contrato não pôde ser conferido: só o controle financeiro traz o número (45/2024), e o desta obra é o 45/2025"
    do_pdf = leitor.ler_pdf(bm.pdf(bm.sem_capa_reconhecida(paginas)))
    assert leitor.recusa(do_pdf, "execucao", 7, "045/2025/MTPAR") is None
    assert leitor.contrato_nao_conferido(do_pdf, "045/2025/MTPAR") is not None


def test_conferencia_do_contrato_pela_fonte_principal():
    certo, outro = "045/2025/MTPAR", "012/2023/MTPAR"
    # so' o quadro foi lido e traz o contrato da obra: confere
    so_quadro = leitor.ler(bm.sem_capa_reconhecida(bm.boletim(numero=7, valor=VALOR)))
    assert (so_quadro["contratos"], so_quadro["contratos_do_quadro"]) == ([], ["45/2025"])
    assert leitor.recusa(so_quadro, "execucao", 7, certo) is None
    assert leitor.contrato_nao_conferido(so_quadro, certo) is None
    # a capa traz outro contrato e o quadro tambem: outra obra (recusa, e nao "por conferir")
    de_outra = leitor.ler(bm.boletim(numero=7, valor=VALOR, contrato="012/2023"))
    assert leitor.recusa(de_outra, "execucao", 7, certo) is not None
    assert leitor.contrato_nao_conferido(de_outra, certo) is None
    # a capa traz outro contrato e so' o quadro traz o da obra: as fontes discordam; nao recusa, fica por conferir
    discordam = leitor.ler(bm.boletim(numero=7, valor=VALOR, contrato="012/2023", contrato_no_quadro="045/2025"))
    assert leitor.recusa(discordam, "execucao", 7, certo) is None
    assert leitor.contrato_nao_conferido(discordam, certo) == (
        "O contrato não pôde ser conferido: a capa traz o 12/2023 e o controle financeiro traz o 45/2025, que é o "
        "desta obra")
    # o reajuste confere pela carta
    carta_de_outra = leitor.ler(bm.reajuste(numero=7, contrato="012/2023"))
    assert leitor.recusa(carta_de_outra, "reajuste", 7, certo) == \
        "Este boletim é de outra obra: traz o contrato 12/2023, e o desta obra é o 45/2025"
    assert leitor.recusa(carta_de_outra, "reajuste", 7, outro) is None
    # o PDF que nao e' deste modelo nao tem contrato a conferir (nada dele e' proposto)
    assert leitor.contrato_nao_conferido(leitor.ler(["Ofício qualquer"]), certo) is None
    assert leitor.contrato_nao_conferido(leitor.ler([""]), certo) is None


def test_sem_numero_de_contrato_no_pdf_ou_no_cadastro_o_contrato_fica_por_conferir():
    """Segunda revisao da PR #760: o que nao da' para conferir nao se propoe. Sem numero de contrato lido em lugar
    nenhum (nem capa/carta, nem quadro), ou com o cadastro da obra sem numero reconhecivel, o boletim nao e'
    recusado, mas o contrato fica por conferir (antes era "nada a comparar" e o valor saia proposto)."""
    certo = "045/2025/MTPAR"
    sem_numero = leitor.ler(bm.sem_contrato_impresso(bm.boletim(numero=7, valor=VALOR)))
    assert (sem_numero["ok"], sem_numero["campos"]["numero"]) == (True, 7)       # o leitor leu; quem chama nao propoe
    assert (sem_numero["contratos"], sem_numero["contratos_do_quadro"]) == ([], [])
    assert leitor.recusa(sem_numero, "execucao", 7, certo) is None
    assert leitor.contrato_nao_conferido(sem_numero, certo) == \
        "O contrato não pôde ser conferido: o número do contrato não foi lido no boletim"
    do_pdf = leitor.ler_pdf(bm.pdf(bm.sem_contrato_impresso(bm.boletim(numero=7, valor=VALOR))))
    assert leitor.contrato_nao_conferido(do_pdf, certo) == leitor.contrato_nao_conferido(sem_numero, certo)
    # o reajuste sem a carta (so' a planilha e o quadro sem o numero)
    do_reajuste = leitor.ler(bm.sem_contrato_impresso(bm.reajuste(numero=7, valor=REAJUSTE)))
    assert (do_reajuste["documento"], do_reajuste["contratos"], do_reajuste["contratos_do_quadro"]) == ("reajuste", [], [])
    assert leitor.contrato_nao_conferido(do_reajuste, certo) is not None
    # o cadastro sem numero reconhecivel: mesmo com o contrato impresso na capa e no quadro, nao ha' como conferir
    completo = leitor.ler(bm.boletim(numero=7, valor=VALOR))
    for cadastro in ("contrato sem número", "", None):
        assert leitor.recusa(completo, "execucao", 7, cadastro) is None
        assert leitor.contrato_nao_conferido(completo, cadastro) == \
            "O contrato não pôde ser conferido: o cadastro desta obra não traz o número do contrato"
    # os casos legitimos continuam conferindo: a capa com o contrato da obra, com o quadro certo ou com o ano trocado
    assert leitor.contrato_nao_conferido(completo, certo) is None
    trocado = leitor.ler(bm.boletim(numero=7, valor=VALOR, contrato_no_quadro="045/2024"))
    assert trocado["ok"] and leitor.contrato_nao_conferido(trocado, certo) is None


def test_numero_do_instrumento_ignora_zeros_data_e_cnpj():
    assert leitor.numero_do_instrumento("045/2025/MTPAR") == "45/2025"
    assert leitor.numero_do_instrumento("IC 1/2026") == "1/2026"
    assert leitor.numero_do_instrumento("01/07/2026") is None
    assert leitor.numero_do_instrumento(None) is None
    # a capa traz CNPJ, periodo e data: so' o numero do contrato vira `contratos`
    assert leitor.ler(bm.boletim())["contratos"] == ["45/2025"]


def test_recusa_o_documento_do_outro_tipo():
    medicao, do_reajuste = leitor.ler(bm.boletim(numero=7)), leitor.ler(bm.reajuste(numero=7))
    assert leitor.recusa(do_reajuste, "execucao", 7, "045/2025/MTPAR") == \
        "Este PDF é o do reajuste, e esta é a medição de execução: escolha o boletim da medição"
    assert leitor.recusa(medicao, "reajuste", 7, "045/2025/MTPAR") == \
        "Este PDF é o boletim da medição, e esta é a medição de reajuste: escolha o PDF do reajuste"
    assert leitor.recusa(medicao, "projeto", 7, "045/2025/MTPAR") is None
    assert leitor.recusa(do_reajuste, "reajuste", 7, "045/2025/MTPAR") is None


def test_o_que_nao_foi_reconhecido_nao_recusa():
    assert leitor.recusa(leitor.ler(["Ofício qualquer"]), "execucao", 7, "045/2025/MTPAR") is None
    assert leitor.recusa(leitor.ler([""]), "execucao", 7, "045/2025/MTPAR") is None


# --- reajuste: o PDF proprio ----------------------------------------------------------------------------------

def test_reajuste_le_o_total_e_confere_com_a_linha_do_quadro():
    r = leitor.ler(bm.reajuste(numero=7, valor=REAJUSTE, pi=VALOR))
    assert (r["ok"], r["documento"]) == (True, "reajuste")
    assert r["campos"] == {"numero": 7, "data": "2026-08-01", "valor_centavos": REAJUSTE}
    assert r["leituras"] == {"rotulo_centavos": REAJUSTE, "controle_centavos": REAJUSTE}
    assert r["contratos"] == ["45/2025"]


def test_reajuste_que_nao_bate_com_o_quadro_vai_para_a_conferencia():
    r = leitor.ler(bm.reajuste(valor=REAJUSTE, no_quadro=REAJUSTE - 1))
    assert (r["ok"], r["motivo"]) == (False, "leituras-divergentes")
    assert r["leituras"] == {"rotulo_centavos": REAJUSTE, "controle_centavos": REAJUSTE - 1}


def test_reajuste_com_o_quadro_sem_as_colunas_de_reajuste_nao_e_proposto():
    r = leitor.ler(bm.reajuste(valor=REAJUSTE, no_quadro=None))
    assert (r["ok"], r["motivo"]) == (False, "controle-nao-lido")
    assert r["leituras"] == {"rotulo_centavos": REAJUSTE, "controle_centavos": None}


def test_boletim_da_medicao_sem_reajuste_nao_gera_erro():
    """A obra sem reajuste na medicao: o quadro de cinco valores e nenhum PDF de reajuste; o boletim e' lido inteiro."""
    r = leitor.ler(bm.boletim(valor=VALOR, reajuste=None))
    assert r["ok"] and r["documento"] == "medicao"


# --- o que nao e' o modelo ------------------------------------------------------------------------------------

def test_texto_vazio_e_documento_de_outro_modelo():
    assert leitor.ler(["", "  \n "])["motivo"] == "sem-texto"
    assert leitor.ler([])["motivo"] == "sem-texto"
    outro = leitor.ler(["Relatório de Capa da Medição RESUMO FINANCEIRO 7 - 7ª Medição Provisória - APROVADA Tipo"])
    assert (outro["ok"], outro["motivo"], outro["documento"], outro["campos"]) == (False, "modelo-nao-reconhecido", None, {})


def test_pagina_com_visto_sem_o_fiscal_do_orgao_nao_e_o_visto():
    pagina = bm.visto(7, VALOR).replace("Fiscal - MTPAR", "Fiscal de outro órgão")
    assert leitor.ler([bm.capa(7), pagina, bm.controle([bm.linha(7, VALOR, 0)])])["motivo"] == "modelo-nao-reconhecido"


# --- PDF de verdade -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("visto_na", [2, 5])
def test_pdf_gerado_com_o_visto_na_pagina_2_e_na_5(visto_na):
    r = leitor.ler_pdf(bm.pdf(bm.boletim(numero=7, valor=VALOR, reajuste=REAJUSTE, visto_na=visto_na)))
    assert r["ok"], r
    assert r["campos"] == {"numero": 7, "data": "2026-08-01", "valor_centavos": VALOR}


def test_pdf_gerado_com_o_valor_separado_e_do_reajuste():
    r = leitor.ler_pdf(bm.pdf(bm.boletim(valor=VALOR, colado=False)))
    assert r["motivo"] == "valor-fora-do-rotulo" and r["leituras"]["controle_centavos"] == VALOR
    r = leitor.ler_pdf(bm.pdf(bm.reajuste(valor=REAJUSTE)))
    assert r["ok"] and r["campos"]["valor_centavos"] == REAJUSTE


def test_pdf_sem_texto_vai_para_a_fila_humana():
    r = leitor.ler_pdf(bm.pdf(["", "", ""]))
    assert (r["ok"], r["motivo"], r["campos"]) == (False, "sem-texto", {})
    assert leitor.ler_pdf(b"%PDF-1.4 quebrado")["motivo"] == "sem-texto"       # o que o pypdf nao abre


def test_so_as_primeiras_paginas_sao_lidas():
    """O Visto depois da ultima pagina lida (o resumo item a item tem centenas) nao e' procurado."""
    paginas = ["Página de enchimento"] * leitor.PAGINAS + bm.boletim(valor=VALOR)
    assert leitor.ler_pdf(bm.pdf(paginas))["motivo"] == "modelo-nao-reconhecido"


def test_pdf_recusado_pela_guarda_nao_levanta(monkeypatch):
    def recusa(pdf, quantas):
        raise leitura_pdf.TextoInadequado("O PDF demorou demais para ser lido")
    monkeypatch.setattr(leitura_pdf, "paginas_iniciais_com_limite", recusa)
    r = leitor.ler_pdf(b"%PDF-")
    assert (r["motivo"], r["aviso"]) == ("pdf-recusado", "O PDF demorou demais para ser lido")
