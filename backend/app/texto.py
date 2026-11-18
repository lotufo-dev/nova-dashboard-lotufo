"""Contagem escrita em frase que vai para a tela: o substantivo acompanha o numero ("1 dia", "2 dias").

O par no frontend e' `contar` e `fmtDias`, em `frontend/src/formato.ts`. Frase com contagem montada no servidor
(aviso, pendencia, mensagem de erro) passa por aqui, para nao sair "termina em 1 dias".
"""


def contar(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def dias(n: int) -> str:
    return contar(n, "dia", "dias")


def dias_uteis(n: int) -> str:
    return contar(n, "dia útil", "dias úteis")
