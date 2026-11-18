"""Contagem em frase que vai para a tela: o substantivo acompanha o numero."""
from app import texto


def test_contar_concorda_com_o_numero():
    assert texto.contar(1, "nota", "notas") == "1 nota"
    assert texto.contar(0, "nota", "notas") == "0 notas"
    assert texto.contar(2, "medição", "medições") == "2 medições"
    assert (texto.dias(1), texto.dias(30)) == ("1 dia", "30 dias")
    assert (texto.dias_uteis(1), texto.dias_uteis(11)) == ("1 dia útil", "11 dias úteis")
