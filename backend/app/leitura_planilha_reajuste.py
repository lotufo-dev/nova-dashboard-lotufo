"""Leitura da planilha de previsao de reajuste do pleito (issue #272; spec 2026-10-20 §2.2 e §4 item 1).

O modelo "Mem. e Cron. - Prev. de Reajuste" tem a aba `Resumo` com uma linha por medicao futura: cabecalho
MEDICAO | PERIODO | VALORES e, na linha de baixo, A PI | (INDICE) | REAJUSTE | TOTAL. A coluna inicial varia
entre as obras (A ou B) e o INDICE nem sempre existe, entao as colunas sao achadas pelo texto do cabecalho.
A competencia e' o mes do FIM do periodo ("23/02/2026 a 31/03/2026" e' 03/2026: a 1a medicao pode comecar no
mes anterior). O valor e' a coluna REAJUSTE, em reais, que a planilha ja' trunca em 2 casas.

Deterministico (openpyxl, sem custo de API). O que nao casa com o modelo levanta `PlanilhaNaoReconhecida` e a
pessoa digita a previsao (fila humana, origem `manual`). Nada aqui grava: quem grava e' `pleitos`.
"""
import datetime
import io
import re
import unicodedata
import zipfile

import openpyxl

from app import dinheiro, rm

ABA = "Resumo"
MENSAGEM = "Não reconheci a planilha; digite a previsão"
LINHAS_CABECALHO = 40          # o cabecalho do modelo fica nas primeiras linhas (6 e 7, ou 3 e 4)
MAX_COMPETENCIAS = 240         # 20 anos de medicoes mensais: acima disso nao e' o modelo (pleitos usa o mesmo)
MAX_VARRIDAS = 5000            # linhas lidas da aba (as em branco formatadas contam aqui, nao no teto acima)
MAX_COLUNAS = 60               # o cabecalho do modelo ocupa 4 a 7 colunas; celula distante nao entra na leitura
_DATA = re.compile(r"([0-9]{2})/([0-9]{2})/([0-9]{4})")


class PlanilhaNaoReconhecida(ValueError):
    """A planilha nao casa com o modelo. `str()` e' a mensagem da tela; `motivo` diz o que faltou."""

    def __init__(self, motivo: str):
        super().__init__(MENSAGEM)
        self.motivo = motivo


def _texto(v) -> str:
    """Cabecalho comparavel: sem acento, maiusculo, sem espacos nas pontas ("MEDIÇÃO " -> "MEDICAO")."""
    if not isinstance(v, str):
        return ""
    s = unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def _competencia(periodo) -> str | None:
    """Mes do fim do periodo: "01/04/2026 a 30/04/2026" -> "2026-04". Data do Excel tambem vale."""
    if isinstance(periodo, datetime.datetime | datetime.date):
        return f"{periodo.year:04d}-{periodo.month:02d}"
    datas = _DATA.findall(periodo) if isinstance(periodo, str) else []
    if not datas:
        return None
    dia, mes, ano = datas[-1]
    try:
        datetime.date(int(ano), int(mes), int(dia))
    except ValueError:
        return None
    return f"{ano}-{mes}"


def _centavos(v) -> int:
    """Reais da planilha (float) -> centavos inteiros: o arredondamento unico do projeto (`rm.centavos`, pelo texto
    do float: 21342.29 nao vira 2134228)."""
    c = rm.centavos(v)
    if abs(c) > dinheiro.TETO_CENTAVOS:
        raise PlanilhaNaoReconhecida("valor de reajuste acima do máximo aceito")
    return c


def _colunas(ws) -> tuple[int, int, int, int]:
    """(linha do primeiro dado, coluna MEDICAO, coluna PERIODO, coluna REAJUSTE), achadas pelo cabecalho."""
    linhas = list(ws.iter_rows(min_row=1, max_row=LINHAS_CABECALHO, max_col=MAX_COLUNAS, values_only=True))
    for i, linha in enumerate(linhas):
        textos = [_texto(v) for v in linha]
        if "MEDICAO" not in textos or "PERIODO" not in textos:
            continue
        col_med, col_per = textos.index("MEDICAO"), textos.index("PERIODO")
        # REAJUSTE na mesma linha ou na de baixo (o modelo agrupa os valores sob "VALORES")
        for j in (i, i + 1):
            sub = [_texto(v) for v in linhas[j]] if j < len(linhas) else []
            if "REAJUSTE" in sub:
                return j + 2, col_med, col_per, sub.index("REAJUSTE")
        raise PlanilhaNaoReconhecida("a aba Resumo não tem a coluna REAJUSTE")
    raise PlanilhaNaoReconhecida("a aba Resumo não tem o cabeçalho MEDIÇÃO e PERÍODO")


def ler(dados: bytes) -> list[dict]:
    """Previsao por competencia: [{"competencia": "AAAA-MM", "valor_centavos": int, "medicao", "periodo"}]."""
    try:
        # read_only: so' a aba Resumo e' lida (as abas de memoria do modelo tem milhares de colunas)
        wb = openpyxl.load_workbook(io.BytesIO(dados), read_only=True, data_only=True)
    except zipfile.BadZipFile as e:
        raise PlanilhaNaoReconhecida("o arquivo não abre como planilha .xlsx") from e
    except Exception as e:   # arquivo de fora: XML quebrado (ParseError e afins) vira digitacao, nao erro 500
        raise PlanilhaNaoReconhecida("a planilha não pôde ser lida") from e
    try:
        return _ler_resumo(wb, dados)
    except PlanilhaNaoReconhecida:
        raise
    except Exception as e:   # arquivo de fora: XML quebrado dentro da aba vira digitacao, nao erro 500
        raise PlanilhaNaoReconhecida("a aba Resumo não pôde ser lida") from e
    finally:
        wb.close()


def _formulas_sem_valor(dados: bytes, linhas: list[tuple[int, str]], colunas: tuple[int, ...]) -> list[str]:
    """Das linhas lidas sem valor (data_only devolve None), as que tem FORMULA na celula: o arquivo foi salvo sem
    o valor calculado (gerado por programa, ou Excel sem recalculo), e a leitura nao pode tratar como vazio."""
    nomes = dict(linhas)
    wb = openpyxl.load_workbook(io.BytesIO(dados), read_only=True, data_only=False)
    try:
        ws = wb[ABA]
        com_formula = []
        # uma varredura so' (no read_only, pular para uma linha custa reler a aba ate' ela)
        for numero, linha in enumerate(ws.iter_rows(min_row=min(nomes), max_row=max(nomes), max_col=MAX_COLUNAS,
                                                    values_only=True), start=min(nomes)):
            if numero in nomes and any(c < len(linha) and isinstance(linha[c], str) and linha[c].startswith("=")
                                       for c in colunas):
                com_formula.append(nomes[numero])
        return com_formula
    finally:
        wb.close()


def _recusar_formula_sem_valor(dados: bytes, sem_valor: list[tuple[int, str]], *colunas: int) -> None:
    if not sem_valor:
        return
    nomes = _formulas_sem_valor(dados, sem_valor, colunas)
    if nomes:
        raise PlanilhaNaoReconhecida(f"{nomes[0]} tem fórmula sem o valor calculado; abra a planilha no Excel, "
                                     "salve e anexe de novo")


def _ler_resumo(wb, dados: bytes) -> list[dict]:
    if ABA not in wb.sheetnames:
        raise PlanilhaNaoReconhecida("falta a aba Resumo")
    ws = wb[ABA]
    # a dimensao declarada na aba: tabela de medicoes nao passa de alguns milhares de linhas
    if (ws.max_row or 0) > MAX_VARRIDAS:
        raise PlanilhaNaoReconhecida("a aba Resumo é grande demais para o modelo")
    inicio, col_med, col_per, col_reaj = _colunas(ws)
    out: list[dict] = []
    vistas: dict[str, str] = {}
    sem_valor: list[tuple[int, str]] = []
    for n, linha in enumerate(ws.iter_rows(min_row=inicio, max_col=MAX_COLUNAS, values_only=True)):
        if n >= MAX_VARRIDAS:     # sem TOTAIS e sem fim: leitura parcial nao serve
            raise PlanilhaNaoReconhecida("a aba Resumo é grande demais para o modelo")
        celula = lambda c: linha[c] if c < len(linha) else None   # noqa: E731
        medicao, periodo, valor = celula(col_med), celula(col_per), celula(col_reaj)
        rotulo = _texto(medicao)
        if rotulo.startswith("TOTA"):        # "TOTAIS": acabou a tabela
            break
        if not rotulo and periodo is None:   # linha em branco no meio ou no fim (ou formula sem valor: abaixo)
            if medicao is None:
                sem_valor.append((inicio + n, f"a linha {inicio + n}"))
            continue
        texto_med = str(medicao).strip() if medicao is not None else ""
        nome = texto_med or f"a linha {inicio + n}"     # sem rotulo, a linha da planilha identifica (nunca "None")
        if valor is None or periodo is None:  # medicao sem reajuste previsto (vazia) ou formula sem valor (abaixo)
            sem_valor.append((inicio + n, nome))
            if valor is None:
                continue
        if not isinstance(valor, int | float) or isinstance(valor, bool):
            raise PlanilhaNaoReconhecida(f"o reajuste de {nome} não é um número")
        comp = _competencia(periodo)
        if comp is None:
            _recusar_formula_sem_valor(dados, sem_valor, col_med, col_per, col_reaj)
            raise PlanilhaNaoReconhecida(f"o período de {nome} não tem data legível")
        if comp in vistas:
            raise PlanilhaNaoReconhecida(f"a competência {comp[5:]}/{comp[:4]} aparece em {vistas[comp]} e em {nome}")
        vistas[comp] = nome
        if len(out) >= MAX_COMPETENCIAS:
            raise PlanilhaNaoReconhecida("competências demais na aba Resumo")
        out.append({"competencia": comp, "valor_centavos": _centavos(valor), "medicao": texto_med,
                    "periodo": periodo.strip() if isinstance(periodo, str) else comp})
    _recusar_formula_sem_valor(dados, sem_valor, col_med, col_per, col_reaj)
    if not out:
        raise PlanilhaNaoReconhecida("nenhuma linha de medição com reajuste na aba Resumo")
    return sorted(out, key=lambda x: x["competencia"])
