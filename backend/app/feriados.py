"""Feriados nacionais e contagem de dias uteis (spec §9: validade da certidao de falencia).

So' feriados NACIONAIS de lei: Lei 662/1949 com a 10.607/2002 (01/01, 21/04, 01/05, 07/09, 02/11,
15/11, 25/12), Lei 6.802/1980 (12/10), Lei 14.759/2023 (20/11, desde 2024) e a Paixao de Cristo.
Carnaval e Corpus Christi sao ponto facultativo e contam como dia util: contar menos feriados
encurta a validade calculada, que e' o lado seguro para quem protocola.
"""
import datetime
from functools import lru_cache

_FIXOS = ((1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25))


def pascoa(ano: int) -> datetime.date:
    """Domingo de Pascoa (algoritmo de Meeus/Jones/Butcher, calendario gregoriano)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return datetime.date(ano, mes, dia + 1)


@lru_cache(maxsize=64)
def nacionais(ano: int) -> frozenset[datetime.date]:
    dias = {datetime.date(ano, m, d) for m, d in _FIXOS if (m, d) != (11, 20) or ano >= 2024}
    dias.add(pascoa(ano) - datetime.timedelta(days=2))
    return frozenset(dias)


def dia_util(d: datetime.date) -> bool:
    return d.weekday() < 5 and d not in nacionais(d.year)


def somar_dias_uteis(inicio: datetime.date, n: int) -> datetime.date:
    """O n-esimo dia util a partir de `inicio`, que conta como o 1o quando e' dia util."""
    if n < 1:
        raise ValueError("n precisa ser pelo menos 1")
    d, contados = inicio, 0
    while True:
        if dia_util(d):
            contados += 1
            if contados == n:
                return d
        d += datetime.timedelta(days=1)


def dias_uteis_entre(desde: datetime.date, ate: datetime.date) -> int:
    """Dias uteis de `desde` (inclusive) ate' `ate` (exclusive): o dia do envio conta, hoje nao (issue #508,
    "com o orgao ha N dias uteis"). Data futura da' 0."""
    dias, d = 0, desde
    while d < ate:
        dias += dia_util(d)
        d += datetime.timedelta(days=1)
    return dias
