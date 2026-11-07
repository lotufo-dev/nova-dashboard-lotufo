"""Modulo de dinheiro: tudo em centavos inteiros, nunca float exposto.

Regra do projeto: valores monetarios circulam SEMPRE como `int` de centavos.
Float so aparece internamente no rateio percentual, e o resultado volta a ser
inteiro com o residuo distribuido de forma que a soma das partes seja
exatamente igual ao total.
"""

import math
import re
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

# Agrupamento pt-BR validado ANTES de limpar: ponto so como separador de milhar
# (grupos de exatamente tres digitos), decimal so com virgula. "12.34" (colado de
# planilha em formato en-US) e' invalido -- antes virava R$ 1.234,00, cem vezes maior.
# A-14 (testes de quebra 10/10/2026): [0-9], nao \d -- o \d do Python casa digito arabe-indico ("١٢٣,٤٥").
_PADRAO_BRL = re.compile(r"([0-9]{1,3}(\.[0-9]{3})*|[0-9]+)(,[0-9]{1,2})?")
# A-08 (testes de quebra 10/10/2026): sem teto, "99999999999999999999,00" estourava o int64 do SQLite (500).
# O mesmo teto do espelho (espelho.TETO_CENTAVOS); o maior contrato real e' de centenas de milhoes.
TETO_CENTAVOS = 10**13 - 1


def parse_brl(texto: str) -> int:
    """Converte texto monetario em pt-BR para centavos inteiros.

    Aceita "4.075.275,90", "R$ 1.000,00", "0,01", "1234,5". Recusa "12.34" e
    "1234.56" (decimal com ponto) e valores negativos (ValueError).
    """
    limpo = texto.replace("R$", "").strip()
    if not _PADRAO_BRL.fullmatch(limpo):
        # B-03 (10/10/2026): com acento e ensinando o formato (o placeholder some quando se digita); sem ecoar o
        # valor recebido (gate Sol S4)
        raise ValueError("Valor monetário inválido: use vírgula nos centavos, ex.: 1.234,56")
    inteiro, _, dec = limpo.replace(".", "").partition(",")
    centavos = int(inteiro) * 100 + (int(dec.ljust(2, "0")) if dec else 0)
    if centavos > TETO_CENTAVOS:
        raise ValueError("Valor acima do máximo aceito (R$ 99.999.999.999,99)")
    return centavos


def format_brl(centavos: int) -> str:
    """Formata centavos inteiros como "R$ 4.075.275,90".

    Aceita centavos negativos (para exibir deltas de aditivo): "-R$ 1.000,00".
    """
    sinal = "-" if centavos < 0 else ""
    inteiro, dec = divmod(abs(centavos), 100)
    milhares = f"{inteiro:,}".replace(",", ".")
    return f"{sinal}R$ {milhares},{dec:02d}"


METODOS = ("trunc2", "round2")


def _aplicar(valor: Decimal, metodo: str) -> int:
    if metodo == "trunc2":
        return int(valor.to_integral_value(rounding=ROUND_DOWN))
    if metodo == "round2":
        return int(valor.to_integral_value(rounding=ROUND_HALF_UP))
    raise ValueError(f"Metodo de arredondamento desconhecido: {metodo!r}")


def ratear(total_centavos: int, parcelas: list[tuple[str, float, str]], absorve: str) -> dict[str, int]:
    """Rateia `total_centavos` pelo modelo congelado da spec §5.

    Cada parcela e' (nome, percentual, metodo) com metodo `trunc2` ou `round2`;
    EXATAMENTE UMA parcela (`absorve`) recebe o resto: total menos a soma das outras.
    A soma das partes e' sempre igual ao total. A parcela-resto pode ficar 1 centavo
    abaixo ou acima da sua fracao (precedente: 50/50 fecha na Rivoli) -- aceito.
    """
    nomes = [nome for nome, _, _ in parcelas]
    if len(nomes) != len(set(nomes)):
        duplicados = sorted({n for n in nomes if nomes.count(n) > 1})
        raise ValueError(f"Nomes duplicados no rateio: {duplicados}")
    if absorve not in nomes:
        raise ValueError(f"Parcela-resto {absorve!r} não está no rateio")

    if any(not math.isfinite(pct) or pct < 0 or pct > 100 for _, pct, _ in parcelas):
        raise ValueError("Percentual de rateio fora de [0, 100]")
    soma_pct = sum(pct for _, pct, _ in parcelas)
    if not math.isclose(soma_pct, 100.0, abs_tol=1e-6):
        raise ValueError(f"Percentuais devem somar 100, somam {soma_pct!r}")

    # Decimal de ponta a ponta: float perde o centavo em totais grandes antes de
    # arredondar. `str(pct)` fixa o percentual como foi escrito (49.0, 33.33).
    partes = {nome: _aplicar(Decimal(total_centavos) * Decimal(str(pct)) / Decimal(100), metodo)
              for nome, pct, metodo in parcelas if nome != absorve}
    partes[absorve] = total_centavos - sum(partes.values())
    return {nome: partes[nome] for nome in nomes}


def ratear_proporcional(total_centavos: int, pesos: list[int]) -> list[int]:
    """Issue #491: rateia `total_centavos` na proporcao de `pesos` (centavos inteiros, >= 0, soma > 0), so' com
    inteiros: cada parte e' o piso da sua fracao e o residuo vai, um centavo por vez, aos maiores restos (empate: o
    primeiro). Total negativo (estorno) rateia como o positivo, com o sinal. A soma das partes e' sempre o total."""
    if not pesos or any(p < 0 for p in pesos) or sum(pesos) <= 0:
        raise ValueError("Pesos do rateio precisam ser inteiros não negativos com soma positiva")
    soma, sinal, total = sum(pesos), -1 if total_centavos < 0 else 1, abs(total_centavos)
    partes = [total * p // soma for p in pesos]
    restos = [total * p % soma for p in pesos]
    for i in sorted(range(len(pesos)), key=lambda i: (-restos[i], i))[:total - sum(partes)]:
        partes[i] += 1
    return [sinal * x for x in partes]
