import pytest
from app import espelho


def brl(t: str) -> int:
    return int(t.replace(".", "").replace(",", ""))


BASE = {"mao_de_obra": {"percentual": "40", "arredondamento": "trunc"}, "material": {"modo": "diferenca"},
        "inss": {"percentual": "11", "base": "mao_de_obra", "arredondamento": "trunc"},
        "iss": {"percentual": "5", "base": "mao_de_obra", "arredondamento": "trunc"},
        "irrf": {"percentual": "1,2", "base": "total", "arredondamento": "trunc"}}


def regra_simples(irrf_arred="trunc"):
    return espelho.normalizar({
        "contrato": "MT-402", "situacao": "ativa",
        "entradas": [{"chave": "medicao", "rotulo": "Valor da medição", "natureza": "medicao"},
                     {"chave": "reajuste", "rotulo": "Valor do reajuste", "natureza": "reajuste"}],
        "retencoes": {**BASE, "irrf": {**BASE["irrf"], "arredondamento": irrf_arred}},
        "saidas": [{"chave": "medicao", "natureza": "medicao", "valor": "medicao", "emissor": "lotufo",
                    "municipio": "Cuiabá", "modelo": "medicao.docx"},
                   {"chave": "reajuste", "natureza": "reajuste", "valor": "reajuste", "emissor": "lotufo",
                    "municipio": "Cuiabá", "modelo": "reajuste.docx"}]})


MT388 = {"contrato": "MT-388", "situacao": "prova",
         "entradas": [{"chave": "medicao", "rotulo": "Valor da medição", "natureza": "medicao"},
                      {"chave": "reajuste", "rotulo": "Valor do reajuste", "natureza": "reajuste"}],
         "parcelas": [{"chave": "med-caceres", "de": "medicao", "fator": "0,8328", "arredondamento": "round"},
                      {"chave": "med-porto", "de": "medicao", "resto_de": ["med-caceres"]},
                      {"chave": "reaj-caceres", "de": "reajuste", "fator": "0,8328", "arredondamento": "round"},
                      {"chave": "reaj-porto", "de": "reajuste", "resto_de": ["reaj-caceres"]}],
         "retencoes": {**BASE, "iss": {**BASE["iss"], "deduz_liquido": False}},
         "saidas": [
             {"chave": "caceres-medicao", "natureza": "medicao", "valor": "med-caceres", "emissor": "lotufo",
              "municipio": "Cáceres", "retencoes": {"iss": {"base": "material"}}, "modelo": "a.docx"},
             {"chave": "porto-medicao", "natureza": "medicao", "valor": "med-porto", "emissor": "lotufo",
              "municipio": "Porto Esperidião", "modelo": "b.docx"},
             {"chave": "caceres-reajuste", "natureza": "reajuste", "valor": "reaj-caceres", "emissor": "lotufo",
              "municipio": "Cáceres", "retencoes": {"iss": {"base": "material"}}, "modelo": "c.docx"},
             {"chave": "porto-reajuste", "natureza": "reajuste", "valor": "reaj-porto", "emissor": "lotufo",
              "municipio": "Porto Esperidião", "modelo": "d.docx"}]}


def linha(s):
    return tuple(s[k] for k in ("valor", "mo", "material", "inss", "iss", "irrf"))


def test_mt402_23a_irrf_arredondado():
    r = regra_simples("round")
    s = espelho.calcular(r, {"medicao": brl("278.509,92"), "reajuste": brl("19.580,95")})
    assert linha(s[0]) == (27850992, 11140396, 16710596, 1225443, 557019, 334212)
    assert linha(s[1]) == (1958095, 783238, 1174857, 86156, 39161, 23497)
    assert s[0]["liquido"] == 27850992 - 1225443 - 557019 - 334212
    assert s[0]["extenso"].startswith("duzentos e setenta e oito mil")


def test_cavalaria_03a_tudo_truncado():
    s = espelho.calcular(regra_simples("trunc"), {"medicao": brl("584.463,68"), "reajuste": brl("103.099,39")})
    assert linha(s[0]) == (58446368, 23378547, 35067821, 2571640, 1168927, 701356)
    assert linha(s[1]) == (10309939, 4123975, 6185964, 453637, 206198, 123719)


def test_mt401_32a():
    s = espelho.calcular(regra_simples("round"), {"medicao": brl("985.375,86"), "reajuste": brl("133.083,30")})
    assert linha(s[0]) == (98537586, 39415034, 59122552, 4335653, 1970751, 1182451)
    assert linha(s[1]) == (13308330, 5323332, 7984998, 585566, 266166, 159700)


def test_reajuste_zero_nao_emite_e_valor_por_natureza():
    r = regra_simples()
    s = espelho.calcular(r, {"medicao": 100000, "reajuste": 0})
    assert [x["chave"] for x in s] == ["medicao"]
    assert espelho.valor_por_natureza(r, {"medicao": 100000, "reajuste": 0}) == {"execucao": 100000}


def test_mt388_10a_quatro_notas_iss_sobre_material_em_caceres():
    s = espelho.calcular(espelho.normalizar(MT388), {"medicao": brl("634.529,58"), "reajuste": brl("38.655,83")})
    assert [linha(x) for x in s] == [
        (52843623, 21137449, 31706174, 2325119, 1585308, 634123),
        (10609335, 4243734, 6365601, 466810, 212186, 127312),
        (3219258, 1287703, 1931555, 141647, 96577, 38631),
        (646325, 258530, 387795, 28438, 12926, 7755)]
    assert s[0]["liquido"] == 52843623 - 2325119 - 634123          # ISS nao deduz


def test_atalaia_43a_rateio_em_dois_niveis_com_resto():
    r = espelho.normalizar({
        "contrato": "Parque Atalaia", "situacao": "prova",
        "entradas": [{"chave": "medicao", "rotulo": "m", "natureza": "medicao"}],
        "parcelas": [{"chave": "cba", "de": "medicao", "fator": "0,5872", "arredondamento": "trunc"},
                     {"chave": "vg", "de": "medicao", "resto_de": ["cba"]},
                     {"chave": "cba-lotufo", "de": "cba", "fator": "0,8", "arredondamento": "trunc"},
                     {"chave": "cba-rivoli", "de": "cba", "resto_de": ["cba-lotufo"]},
                     {"chave": "vg-lotufo", "de": "vg", "fator": "0,8", "arredondamento": "trunc"},
                     {"chave": "vg-rivoli", "de": "vg", "resto_de": ["vg-lotufo"]}],
        "retencoes": BASE,
        "saidas": [{"chave": k, "natureza": "medicao", "valor": k, "emissor": e, "municipio": m, "modelo": f"{k}.docx"}
                   for k, e, m in [("cba-lotufo", "lotufo", "Cuiabá"), ("cba-rivoli", "rivoli", "Cuiabá"),
                                   ("vg-lotufo", "lotufo", "Várzea Grande"), ("vg-rivoli", "rivoli", "Várzea Grande")]]})
    s = espelho.calcular(r, {"medicao": brl("780.224,80")})
    assert linha(s[0]) == (36651840, 14660736, 21991104, 1612680, 733036, 439822)
    assert linha(s[1]) == (9162960, 3665184, 5497776, 403170, 183259, 109955)
    assert linha(s[2]) == (25766144, 10306457, 15459687, 1133710, 515322, 309193)
    assert s[0]["valor"] + s[1]["valor"] + s[2]["valor"] + s[3]["valor"] == brl("780.224,80")


PROJETO = {"mao_de_obra": None, "material": None, "inss": None,
           "iss": {"percentual": "5", "base": "total", "arredondamento": "trunc"},
           "irrf": {"percentual": "4,8", "base": "total", "arredondamento": "trunc"}}


def test_brt_10a_fracao_exata_round_por_empresa_e_projeto_sem_split():
    r = espelho.normalizar({
        "contrato": "Integra BRT", "situacao": "prova",
        "entradas": [{"chave": "medicao", "rotulo": "m", "natureza": "medicao"},
                     {"chave": "projeto", "rotulo": "p", "natureza": "projeto"}],
        "parcelas": [{"chave": "cba", "de": "medicao", "fracao": [6740, 7820], "arredondamento": "trunc"},
                     {"chave": "vg", "de": "medicao", "resto_de": ["cba"]},
                     {"chave": "cba-lotufo", "de": "cba", "fator": "0,49", "arredondamento": "round"},
                     {"chave": "vg-lotufo", "de": "vg", "fator": "0,49", "arredondamento": "round"},
                     {"chave": "proj-lotufo", "de": "projeto", "fator": "0,49", "arredondamento": "round"}],
        "retencoes": BASE,
        "saidas": [{"chave": "exec-cba-lotufo", "natureza": "medicao", "valor": "cba-lotufo", "emissor": "lotufo",
                    "municipio": "Cuiabá", "modelo": "a.docx"},
                   {"chave": "exec-vg-lotufo", "natureza": "medicao", "valor": "vg-lotufo", "emissor": "lotufo",
                    "municipio": "Várzea Grande", "modelo": "b.docx"},
                   {"chave": "proj-cba-lotufo", "natureza": "projeto", "valor": "proj-lotufo", "emissor": "lotufo",
                    "municipio": "Cuiabá", "modelo": "c.docx", "retencoes": PROJETO}]})
    s = espelho.calcular(r, {"medicao": brl("7.382.048,52"), "projeto": 0})
    assert linha(s[0]) == (311764110, 124705644, 187058466, 13717620, 6235282, 3741169)
    assert linha(s[1]) == (49956267, 19982506, 29973761, 2198075, 999125, 599475)
    assert len(s) == 2
    p = espelho.calcular(r, {"medicao": 0, "projeto": brl("15.351,18")})   # 7.522,08 / 0,49 -> Lotufo 7.522,08
    assert (p[0]["valor"], p[0]["mo"], p[0]["inss"], p[0]["iss"], p[0]["irrf"]) == (752208, None, None, 37610, 36105)


def test_estacoes_3a_fracao_61_81_truncada():
    r = espelho.normalizar({
        "contrato": "Estações BRT", "situacao": "prova",
        "entradas": [{"chave": "medicao", "rotulo": "m", "natureza": "medicao"},
                     {"chave": "reajuste", "rotulo": "r", "natureza": "reajuste"}],
        "parcelas": [{"chave": "med-cba", "de": "medicao", "fracao": [61, 81], "arredondamento": "trunc"},
                     {"chave": "med-vg", "de": "medicao", "resto_de": ["med-cba"]},
                     {"chave": "reaj-cba", "de": "reajuste", "fracao": [61, 81], "arredondamento": "trunc"},
                     {"chave": "reaj-vg", "de": "reajuste", "resto_de": ["reaj-cba"]}],
        "retencoes": BASE,
        "saidas": [{"chave": k, "natureza": n, "valor": k, "emissor": "lotufo", "municipio": m, "modelo": f"{k}.docx"}
                   for k, n, m in [("med-cba", "medicao", "Cuiabá"), ("med-vg", "medicao", "Várzea Grande"),
                                   ("reaj-cba", "reajuste", "Cuiabá"), ("reaj-vg", "reajuste", "Várzea Grande")]]})
    s = espelho.calcular(r, {"medicao": brl("3.198.742,98"), "reajuste": brl("202.800,30")})
    assert [linha(x) for x in s] == [
        (240892989, 96357195, 144535794, 10599291, 4817859, 2890715),
        (78981309, 31592523, 47388786, 3475177, 1579626, 947775),
        (15272615, 6109046, 9163569, 671995, 305452, 183271),
        (5007415, 2002966, 3004449, 220326, 100148, 60088)]


def test_leblon_resto_fica_um_centavo_menor_e_tributos_arredondados():
    r = espelho.normalizar({
        "contrato": "Leblon", "situacao": "prova",
        "entradas": [{"chave": "reajuste", "rotulo": "r", "natureza": "reajuste"}],
        "parcelas": [{"chave": "lotufo", "de": "reajuste", "fator": "0,5", "arredondamento": "round"},
                     {"chave": "rivoli", "de": "reajuste", "resto_de": ["lotufo"]}],
        "retencoes": {**BASE, "inss": {**BASE["inss"], "arredondamento": "round"},
                      "iss": {**BASE["iss"], "arredondamento": "round"},
                      "irrf": {**BASE["irrf"], "arredondamento": "round"}},
        "saidas": [{"chave": "lotufo", "natureza": "reajuste", "valor": "lotufo", "emissor": "lotufo",
                    "municipio": "Cuiabá", "modelo": "a.docx"},
                   {"chave": "rivoli", "natureza": "reajuste", "valor": "rivoli", "emissor": "rivoli",
                    "municipio": "Cuiabá", "modelo": "b.docx"}]})
    s = espelho.calcular(r, {"reajuste": brl("476.449,03")})
    assert (s[0]["valor"], s[1]["valor"]) == (23822452, 23822451)
    assert (s[0]["inss"], s[0]["iss"], s[0]["irrf"]) == (1048188, 476449, 285869)


def test_ibs_cbs_informativos_nao_deduzem_do_liquido():
    r = espelho.normalizar({**MT388, "retencoes": {
        **BASE, "ibs": {"percentual": "0,1", "base": "total", "arredondamento": "round", "vigente_desde": "2026-01-01"},
        "cbs": {"percentual": "0,9", "base": "total", "arredondamento": "round", "vigente_desde": "2026-01-01"}}})
    s = espelho.calcular(r, {"medicao": 100000, "reajuste": 0})
    assert (s[0]["ibs"], s[0]["cbs"]) == (round(s[0]["valor"] * 0.001), round(s[0]["valor"] * 0.009))
    assert s[0]["liquido"] == s[0]["valor"] - s[0]["inss"] - s[0]["iss"] - s[0]["irrf"]


def test_nome_do_arquivo_e_controles():
    r = espelho.normalizar(MT388)
    s = espelho.calcular(r, {"medicao": brl("634.529,58"), "reajuste": 0})
    assert espelho.nome_arquivo(r, r["saidas"][0], "MT-388", 10, "2026-05", "Lotufo") == \
        "ESPELHO - MT-388 - 10ª Medição (05.2026) - Cáceres.docx"     # 1 emissor: sem consorciada
    rs = regra_simples()
    assert espelho.nome_arquivo(rs, rs["saidas"][1], "MT-402", 3, "2026-05", "Lotufo") == \
        "ESPELHO - MT-402 - 03ª Reajuste (05.2026).docx"
    c = espelho.formatar_controles(s[0], 10, "2026-05")
    assert c["valor"] == "528.436,23" and c["medicao"] == "10ª" and c["periodo"] == "01/05/2026 A 31/05/2026"
    assert c["valor_extenso"].startswith("QUINHENTOS E VINTE E OITO MIL, QUATROCENTOS")
    assert espelho.campos_da_saida(r["saidas"][0]) == {"valor", "mo", "material", "inss", "iss", "irrf",
                                                       "valor_extenso", "medicao", "periodo"}


@pytest.mark.parametrize("quebra,trecho", [
    ({"saidas": [{"chave": "xx", "natureza": "medicao", "valor": "nao-existe", "emissor": "lotufo",
                  "municipio": "C", "modelo": "a.docx"}]}, "nao-existe"),
    ({"parcelas": [{"chave": "pp", "de": "medicao", "fator": "0,5", "arredondamento": "round", "resto_de": ["q"]}]},
     "exatamente um"),
    ({"saidas": [{"chave": "x", "natureza": "medicao", "valor": "medicao", "emissor": "lotufo",
                  "municipio": "C", "modelo": "a.docx"}]}, "chave"),          # chave de 1 caractere
    ({"retencoes": {**BASE, "iss": {**BASE["iss"], "base": "lucro"}}}, "base"),
    ({"situacao": "ligada"}, "situacao"),
])
def test_normalizar_acumula_erros(quebra, trecho):
    with pytest.raises(espelho.RegraInvalida) as e:
        espelho.normalizar({**MT388, **quebra})
    assert any(trecho in x for x in e.value.erros)


def test_saida_de_natureza_diferente_da_entrada_e_erro():
    with pytest.raises(espelho.RegraInvalida) as e:
        espelho.normalizar({**MT388, "saidas": [{"chave": "xx", "natureza": "reajuste", "valor": "med-caceres",
                                                   "emissor": "lotufo", "municipio": "C", "modelo": "a.docx"}]})
    assert any("natureza" in x for x in e.value.erros)


@pytest.mark.parametrize("quebra,trecho", [
    ({"retencoes": {**BASE, "irrf": {**BASE["irrf"], "percentual": "NaN"}}}, "domínio"),
    ({"retencoes": {**BASE, "irrf": {**BASE["irrf"], "percentual": "-1"}}}, "domínio"),
    ({"retencoes": {**BASE, "irrf": {**BASE["irrf"], "percentual": "101"}}}, "acima de 100"),
    ({"parcelas": [{"chave": "med-caceres", "de": "medicao", "fator": "Infinity", "arredondamento": "round"},
                   {"chave": "med-porto", "de": "medicao", "resto_de": ["med-caceres"]},
                   {"chave": "reaj-caceres", "de": "reajuste", "fator": "1,5", "arredondamento": "round"},
                   {"chave": "reaj-porto", "de": "reajuste", "resto_de": ["reaj-caceres"]}]}, "entre 0 e 1"),
])
def test_numeros_fora_do_dominio_sao_erro_na_validacao(quebra, trecho):
    with pytest.raises(espelho.RegraInvalida) as e:
        espelho.normalizar({**MT388, **quebra})
    assert any(trecho in x for x in e.value.erros)


def test_vigente_desde_desliga_o_tributo_antes_da_data():
    r = espelho.normalizar({**MT388, "retencoes": {**BASE, "ibs": {"percentual": "0,1", "base": "total",
                                                                    "arredondamento": "round", "vigente_desde": "2027-01-01"}}})
    antes = espelho.calcular(r, {"medicao": 100000, "reajuste": 0}, competencia="2026-12")
    depois = espelho.calcular(r, {"medicao": 100000, "reajuste": 0}, competencia="2027-01")
    assert antes[0]["ibs"] is None and depois[0]["ibs"] == round(depois[0]["valor"] * 0.001)
    assert espelho.calcular(r, {"medicao": 100000, "reajuste": 0})[0]["ibs"] is not None   # sem competencia: vale


def test_valor_acima_do_teto_e_recusado():
    # acima de 13 digitos o double deixa de imitar os 15 significativos do Excel
    with pytest.raises(ValueError, match="99.999.999.999,99"):
        espelho.calcular(regra_simples(), {"medicao": espelho.TETO_CENTAVOS + 1, "reajuste": 0})


def test_tributo_arredondado_na_celula_segue_o_round_do_excel():
    # MTPAR: C12 = ROUND(C5*1,5%;2). 11,00 x 0,015 = 0,16499999... no double: o ROUND do Excel (15 digitos)
    # da' 0,17; a leitura de celula crua (Math.round) daria 0,16
    base = {**BASE, "irrf": {"percentual": "1,5", "base": "total", "arredondamento": "round"}}
    r = espelho.normalizar({"contrato": "X", "situacao": "prova",
                            "entradas": [{"chave": "medicao", "rotulo": "m", "natureza": "medicao"}],
                            "retencoes": {**base, "irrf": {**base["irrf"], "na_celula": True}},
                            "saidas": [{"chave": "medicao", "natureza": "medicao", "valor": "medicao", "emissor": "lotufo",
                                        "municipio": "Cuiabá", "modelo": "a.docx"}]})
    assert espelho.calcular(r, {"medicao": 1100})[0]["irrf"] == 17
    r["saidas"][0]["retencoes"]["irrf"]["na_celula"] = False
    assert espelho.calcular(r, {"medicao": 1100})[0]["irrf"] == 16


def test_texto_da_obra_numero_com_zero_e_extenso_minusculo():
    r = espelho.normalizar({"contrato": "X", "situacao": "prova", "texto": {"numero_com_zero": True},
                            "entradas": [{"chave": "medicao", "rotulo": "m", "natureza": "medicao"}],
                            "retencoes": BASE,
                            "saidas": [{"chave": "medicao", "natureza": "medicao", "valor": "medicao",
                                        "emissor": "lotufo", "municipio": "Cuiabá", "modelo": "a.docx"}]})
    s = espelho.calcular(r, {"medicao": 100})[0]
    assert espelho.formatar_controles(s, 4, "2026-06", r["texto"])["medicao"] == "04ª"      # Cavalaria, Maternidade
    c = espelho.formatar_controles(s, 4, "2026-06", {"extenso_minusculo": True})             # Coxipó 2ª
    assert (c["medicao"], c["valor_extenso"]) == ("4ª", "um real")
    assert "texto" not in regra_simples()        # sem declarar, a regra (e o sha256 dela) nao muda
    with pytest.raises(espelho.RegraInvalida, match="texto"):
        espelho.normalizar({**MT388, "texto": {"caixa": True}})


# --- issue #284: o valor do espelho vem do aprovado do boletim, senao do pedido ---------------------------

def _regra_duas_fontes():
    """Como a obra com dois valores digitados de medicao (duas fontes de recurso) e um de reajuste."""
    return espelho.normalizar({
        "contrato": "X", "situacao": "ativa",
        "entradas": [{"chave": "fonte-a", "rotulo": "Medição fonte A", "natureza": "medicao"},
                     {"chave": "fonte-b", "rotulo": "Medição fonte B", "natureza": "medicao"},
                     {"chave": "reajuste", "rotulo": "Valor do reajuste", "natureza": "reajuste"}],
        "retencoes": BASE,
        "saidas": [{"chave": "saida-a", "natureza": "medicao", "valor": "fonte-a", "emissor": "lotufo",
                    "municipio": "Cuiabá", "modelo": "a.docx"},
                   {"chave": "saida-b", "natureza": "medicao", "valor": "fonte-b", "emissor": "lotufo",
                    "municipio": "Cuiabá", "modelo": "b.docx"},
                   {"chave": "saida-r", "natureza": "reajuste", "valor": "reajuste", "emissor": "lotufo",
                    "municipio": "Cuiabá", "modelo": "r.docx"}]})


def test_campo_unico_vem_preenchido_com_o_aprovado():
    # centavo impar: o valor do boletim entra inteiro, sem arredondar nada
    saida = espelho.entradas_pela_medicao(regra_simples(), {"reajuste": 50_00},
                                          {"execucao": (1_234_567, "boletim")})
    assert saida == {"medicao": 1_234_567, "reajuste": 50_00}
    assert espelho.valor_por_natureza(regra_simples(), saida) == {"execucao": 1_234_567, "reajuste": 50_00}


def test_campo_unico_digitado_igual_passa_e_diferente_recusa_com_os_dois_valores():
    assert espelho.entradas_pela_medicao(regra_simples(), {"medicao": 1_234_567},
                                         {"execucao": (1_234_567, "boletim")})["medicao"] == 1_234_567
    with pytest.raises(ValueError) as e:
        espelho.entradas_pela_medicao(regra_simples(), {"medicao": 1_000_000}, {"execucao": (1_234_567, "boletim")})
    assert "R$ 12.345,67" in str(e.value) and "R$ 10.000,00" in str(e.value) and "aprovado" in str(e.value)


def test_atestado_digitado_sem_boletim_vale_como_aprovado_e_a_mensagem_nao_cita_o_boletim():
    # decisao do Leo de 03/11/2026: o atestado digitado (sem PDF) vale como aprovado no espelho
    with pytest.raises(ValueError) as e:
        espelho.entradas_pela_medicao(regra_simples(), {"medicao": 1}, {"execucao": (2, "atestado")})
    assert "o aprovado (R$ 0,02)" in str(e.value) and "boletim" not in str(e.value)


def test_sem_aprovado_vale_o_pedido():
    with pytest.raises(ValueError, match="pedido"):
        espelho.entradas_pela_medicao(regra_simples(), {"medicao": 1}, {"execucao": (2, "pedido")})
    assert espelho.entradas_pela_medicao(regra_simples(), {}, {"execucao": (2, "pedido")}) == {"medicao": 2}


def test_mais_de_um_campo_a_divisao_e_digitada_e_tem_de_somar_o_aprovado():
    # rateio com residuo: 1.000,01 dividido em 500,00 + 500,01
    r = _regra_duas_fontes()
    ok = espelho.entradas_pela_medicao(r, {"fonte-a": 500_00, "fonte-b": 500_01}, {"execucao": (1_000_01, "boletim")})
    assert ok == {"fonte-a": 500_00, "fonte-b": 500_01}
    with pytest.raises(ValueError) as e:
        espelho.entradas_pela_medicao(r, {"fonte-a": 500_00, "fonte-b": 500_00}, {"execucao": (1_000_01, "boletim")})
    assert "R$ 1.000,00" in str(e.value) and "R$ 1.000,01" in str(e.value)
    with pytest.raises(ValueError, match="R\\$ 1.000,01"):     # nada digitado: a soma zero tambem nao bate
        espelho.entradas_pela_medicao(r, {}, {"execucao": (1_000_01, "boletim")})


def test_tipo_opcional_sem_nada_digitado_fica_fora_e_digitado_tem_de_bater():
    # a medicao ainda sem boletim nao entra sozinha no espelho: so' quando a pessoa a poe (e com o valor travado)
    r = _regra_duas_fontes()
    trav = {"execucao": (1_000_01, "pedido"), "reajuste": (300_01, "pedido")}
    saida = espelho.entradas_pela_medicao(r, {"fonte-a": 500_00, "fonte-b": 500_01}, trav, {"reajuste"})
    assert saida == {"fonte-a": 500_00, "fonte-b": 500_01}
    assert espelho.valor_por_natureza(r, saida) == {"execucao": 1_000_01}
    assert espelho.entradas_pela_medicao(r, {"fonte-a": 1_000_01, "reajuste": 300_01}, trav, {"reajuste"})["reajuste"] == 300_01
    with pytest.raises(ValueError, match="R\\$ 300,01"):
        espelho.entradas_pela_medicao(r, {"fonte-a": 1_000_01, "reajuste": 300_00}, trav, {"reajuste"})


def test_tipo_sem_valor_ou_que_a_regra_nao_gera_fica_como_esta():
    assert espelho.entradas_pela_medicao(regra_simples(), {"medicao": 7}, {}) == {"medicao": 7}
    assert espelho.entradas_pela_medicao(regra_simples(), {"medicao": 7}, {"projeto": (9, "boletim")}) == {"medicao": 7}


# --- issue #589: reajuste negativo abate na nota da medicao do mesmo emissor e municipio ---------------------------

def test_reajuste_negativo_abate_na_nota_da_medicao_com_o_sinal():
    """Decisao do Leo de 08/11/2026: a nota nao sai negativa. O reajuste negativo (centavo impar) soma com o sinal na
    nota de medicao, que sai com o valor liquido e os tributos sobre ele; a saida de reajuste nao vira nota."""
    r = regra_simples()
    s = espelho.calcular(r, {"medicao": 1_000_01, "reajuste": -10_01})
    assert [x["chave"] for x in s] == ["medicao"]
    assert s[0]["valor"] == 990_00 and s[0]["reajuste_abatido"] == -10_01
    (so_liquido,) = espelho.calcular(r, {"medicao": 990_00})
    assert linha(s[0]) == linha(so_liquido) and s[0]["liquido"] == so_liquido["liquido"]
    assert "reajuste_abatido" not in so_liquido
    assert espelho.valor_por_natureza(r, {"medicao": 1_000_01, "reajuste": -10_01}) == {
        "execucao": 1_000_01, "reajuste": -10_01}


def test_espelho_so_de_reajuste_negativo_e_recusado():
    with pytest.raises(ValueError, match="A nota não sai com valor negativo; inclua a execução do mesmo número"):
        espelho.calcular(regra_simples(), {"reajuste": -10_01})


def test_reajuste_negativo_que_zera_ou_passa_da_medicao_e_recusado():
    for reajuste in (-1_000_01, -1_000_02):
        with pytest.raises(ValueError, match="zera a nota de medição"):
            espelho.calcular(regra_simples(), {"medicao": 1_000_01, "reajuste": reajuste})


def test_reajuste_negativo_rateado_abate_em_cada_municipio_e_fecha_no_centavo():
    """MT-388: o rateio do reajuste negativo (fator 0,8328 com resto) abate em Caceres e em Porto Esperidiao; a soma
    das notas e' a medicao mais o reajuste, ao centavo."""
    regra = espelho.normalizar(MT388)
    s = espelho.calcular(regra, {"medicao": brl("634.529,58"), "reajuste": -brl("38.655,83")})
    assert [x["chave"] for x in s] == ["caceres-medicao", "porto-medicao"]
    assert sum(x["valor"] for x in s) == brl("634.529,58") - brl("38.655,83")
    assert sum(x["reajuste_abatido"] for x in s) == -brl("38.655,83")


def test_reajuste_negativo_com_duas_notas_de_medicao_do_mesmo_emissor_e_recusado():
    with pytest.raises(ValueError, match="mais de uma nota de medição"):
        espelho.calcular(_regra_duas_fontes(), {"fonte-a": 1_000_00, "fonte-b": 1_000_00, "reajuste": -1_00})


def test_medicao_e_projeto_negativos_sao_recusados():
    with pytest.raises(ValueError, match="Valor da medição: valor negativo só no reajuste"):
        espelho.calcular(regra_simples(), {"medicao": -1, "reajuste": 0})
