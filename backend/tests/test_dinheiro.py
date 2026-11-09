import pytest

from app.dinheiro import TETO_CENTAVOS, format_brl, parse_brl, ratear, ratear_proporcional


def test_parse_brl():
    assert parse_brl("4.075.275,90") == 407527590
    assert parse_brl("R$ 1.000,00") == 100000
    assert parse_brl("0,01") == 1


def test_parse_brl_invalido():
    with pytest.raises(ValueError):
        parse_brl("abc")


def test_parse_brl_invalido_ensina_o_formato():
    # B-03 (10/10/2026): "Valor monetario invalido: '1234.56'" sem acento e sem dizer o formato
    with pytest.raises(ValueError) as e:
        parse_brl("1234.56")
    # gate Sol S4 (10/10/2026): sem ecoar o valor recebido
    assert str(e.value) == "Valor monetário inválido: use vírgula nos centavos, ex.: 1.234,56"


def test_parse_brl_recusa_decimal_com_ponto():
    # "12.34" colado de planilha en-US virava R$ 1.234,00 (100x). Agora e' erro.
    for texto in ("12.34", "1234.56", "1.2345,00", "1.23", "1.000.00"):
        with pytest.raises(ValueError):
            parse_brl(texto)
    assert parse_brl("1234,5") == 123450
    assert parse_brl("1.000") == 100000


def test_parse_brl_inverte_format_brl():
    for c in (0, 1, 99, 100, 123456, 100000000, 407527590, 99999999999):
        assert parse_brl(format_brl(c)) == c


def test_parse_brl_nao_aceita_negativo():
    # v1: parse_brl nao aceita valores negativos
    with pytest.raises(ValueError):
        parse_brl("-1.000,00")


def test_format_brl():
    assert format_brl(407527590) == "R$ 4.075.275,90"
    assert format_brl(1) == "R$ 0,01"


def test_format_brl_negativo():
    # centavos negativos sao aceitos para exibir deltas de aditivo
    assert format_brl(-100000) == "-R$ 1.000,00"


def test_ratear_soma_sempre_igual_ao_total():
    partes = ratear(100000001, [("A", 60.0, "trunc2"), ("B", 40.0, "trunc2")], absorve="B")
    assert sum(partes.values()) == 100000001


def test_ratear_nome_duplicado_e_resto_desconhecido_rejeitados():
    with pytest.raises(ValueError):
        ratear(100, [("A", 50.0, "trunc2"), ("A", 50.0, "trunc2")], absorve="A")
    with pytest.raises(ValueError):
        ratear(100, [("A", 50.0, "trunc2"), ("B", 50.0, "trunc2")], absorve="C")


def test_ratear_metodo_por_parcela_e_resto_numa_so():
    # 49/49/2 fecha na terceira (precedente Encomind): 1.001 centavos
    partes = ratear(1001, [("A", 49.0, "round2"), ("B", 49.0, "trunc2"), ("C", 2.0, "trunc2")], "C")
    assert partes == {"A": 490, "B": 490, "C": 21}
    # 50/50 com resto na Rivoli: ela fica 1 centavo menor (aceito, nao bug)
    partes = ratear(101, [("Lotufo", 50.0, "round2"), ("Rivoli", 50.0, "round2")], "Rivoli")
    assert partes == {"Lotufo": 51, "Rivoli": 50}
    # sem float no caminho: total perto do int64 ainda fecha centavo a centavo
    grande = 9_000_000_000_000_000_01
    partes = ratear(grande, [("A", 33.33, "trunc2"), ("B", 66.67, "round2")], "B")
    assert partes["A"] == grande * 3333 // 10000 and sum(partes.values()) == grande
    with pytest.raises(ValueError):
        ratear(100, [("A", -10.0, "trunc2"), ("B", 110.0, "trunc2")], "B")


def test_parse_brl_teto():
    """A-08 (10/10/2026): acima de R$ 99.999.999.999,99 (o teto do espelho) e' recusado."""
    assert parse_brl("99.999.999.999,99") == TETO_CENTAVOS
    for grande in ("100.000.000.000,00", "99999999999999999999,00"):
        with pytest.raises(ValueError, match="máximo aceito"):
            parse_brl(grande)


def test_parse_brl_recusa_digito_nao_ascii():
    r"""A-14 (10/10/2026): `\d` do Python casa digito arabe-indico; o formato pt-BR e' so' 0-9."""
    with pytest.raises(ValueError):
        parse_brl("١٢٣,٤٥")


def test_ratear_proporcional_maiores_restos_e_sinal():
    """Issue #491: custo sem tarefa rateado na proporcao do apontado; a soma fecha no total, centavo a centavo."""
    assert ratear_proporcional(1001, [100, 200]) == [334, 667]
    assert ratear_proporcional(1, [1, 1, 1]) == [1, 0, 0]          # empate: o primeiro
    assert ratear_proporcional(-1001, [100, 200]) == [-334, -667]   # estorno: o mesmo rateio com sinal
    assert ratear_proporcional(0, [5, 7]) == [0, 0]
    assert ratear_proporcional(10, [0, 3]) == [0, 10]
    for ruim in ([], [0, 0], [-1, 2]):
        with pytest.raises(ValueError):
            ratear_proporcional(10, ruim)


def test_parse_brl_com_sinal():
    """Issue #589: o reajuste aceita o sinal (hifen ou o sinal tipografico); sem sinal, igual a parse_brl."""
    from app.dinheiro import parse_brl_com_sinal
    assert parse_brl_com_sinal("-10,01") == -1001
    assert parse_brl_com_sinal("−1.234,57") == -123457
    assert parse_brl_com_sinal("-R$ 1,00") == -100
    assert parse_brl_com_sinal("1.234,57") == 123457
    for ruim in ("--1,00", "1,00-", "- ", "-12.34"):
        with pytest.raises(ValueError):
            parse_brl_com_sinal(ruim)
    with pytest.raises(ValueError):
        parse_brl("-1,00")
