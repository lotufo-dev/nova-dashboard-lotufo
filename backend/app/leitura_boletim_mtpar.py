"""Leitor deterministico do boletim de medicao da MT-PAR (issue #753; decisao do dono de 16/11/2026, #297).

Puro no miolo (`ler`: o texto de cada pagina -> campos, sem banco nem arquivo), no padrao de `leitura_smo`;
`ler_pdf` busca o texto das primeiras `PAGINAS` paginas (`leitura_pdf`, em subprocesso com limite). Sem custo de
API e sem OCR: regex sobre o texto. PDF sem texto volta `sem-texto` e a pessoa digita.

Modelo (o mesmo nas obras do orgao): o boletim da medicao e' um PDF unico, preenchido pela empresa no modelo do
orgao e assinado pelo fiscal do orgao e pelo engenheiro da empresa. Traz a capa ("Nª Medição - Mês/AAAA"), os dados
gerais, a pagina do "Visto" (com "Valor Total da Nª Medição ..... 0,00 R$"), o quadro "CONTROLE FINANCEIRO" (uma
linha por medicao, que pode continuar na pagina seguinte, sem o titulo) e o resumo item a item. O reajuste vem em
PDF proprio: a carta do fiscal ("Reajustamento da Nª Medição"), a planilha de reajustamento ("TOTAL REAJUSTE") e o
mesmo quadro de controle financeiro.

O que o leitor faz, e por que:

- **Acha a pagina pelos rotulos, nunca pelo numero dela.** O Visto ja' veio em paginas diferentes; ele e' a pagina
  com "Visto", "Fiscal - MTPAR" e o rotulo "Valor Total da Nª Medição".
- **Duas leituras do valor.** A do rotulo (o valor logo depois do rotulo e dos pontos de conducao) e a do quadro de
  controle financeiro (o valor a precos iniciais do periodo, na linha da medicao). A ordem do texto extraido muda de
  obra para obra: numas o valor sai colado ao rotulo, noutras num bloco separado, longe dele. Por isso o valor so' e'
  proposto (`ok`) quando as duas leituras existem e sao a mesma quantia; fora disso volta sem valor, com as duas
  leituras em `leituras`, para a conferencia humana.
- **A linha do quadro so' vale se fecha.** Com as colunas de reajuste sao sete valores (PI do periodo e acumulado,
  reajuste do periodo e acumulado, PI de novo, total, saldo): o quinto repete o primeiro e o sexto e' a soma do
  primeiro com o terceiro. Sem as colunas de reajuste sao cinco, e o terceiro e o quarto repetem o primeiro. Linha
  que nao fecha (colunas fora de ordem na extracao) nao e' lida.
- **O numero da medicao vem da capa** ("Nª Medição - Mês/AAAA") ou, sem ela, do campo "N.º da Medição" dos dados
  gerais; nunca do rodape nem do nome do arquivo (o rodape ja' veio com o numero da medicao anterior). O rotulo do
  Visto traz o numero de novo: se discorda, nada e' proposto.
- **Os campos "acumulado das medicoes anteriores" e "saldo" do Visto nao entram** em conferencia nenhuma: vem
  errados em parte das obras.
- **Reajuste.** No PDF proprio, a leitura do rotulo e' o "TOTAL REAJUSTE" e a do quadro e' o reajuste do periodo na
  linha da medicao; o numero vem da carta ("Reajustamento da Nª Medição").

`contratos` devolve os numeros de instrumento ("60/2024") impressos na capa (ou na carta) e no quadro, para quem
chama recusar o boletim de outra obra (`recusa`).
"""
import re
from datetime import date

from . import leitura_pdf
from .leitura_smo import _centavos, _plano

# O Visto ja' veio na 2a e na 5a pagina e o quadro de controle financeiro terminou na 7a; o resto do PDF (o resumo
# item a item, com centenas de paginas) nao e' lido.
PAGINAS = 12

_I = re.IGNORECASE
_VALOR = r"\d{1,3}(?:\.\d{3})*,\d{2}"
_DATA = r"\d{2}/\d{2}/\d{4}"
# "26ª", "3º", "26a", "26°" e "26": sem acento (`_plano`) o ª vira "a" e o º vira "o"
_ORDINAL = r"(?<![\d/.,])(\d{1,3}) ?[ao°]?"
_MESES = ("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
          "novembro", "dezembro")
_MES = "(" + "|".join(_MESES) + ")"

_ROTULO_VISTO = re.compile(r"Valor Total da " + _ORDINAL + r" ?Medicao", _I)
# o valor "ao lado do rotulo": entre o rotulo e ele so' espaco e pontos de conducao
_VISTO_AO_LADO = re.compile(r"Valor Total da " + _ORDINAL + r" ?Medicao[ .:_]*(" + _VALOR + r")(?! ?%)", _I)
_FISCAL = re.compile(r"Fiscal ?- ?MT ?-? ?PAR", _I)
_CAPA = re.compile(_ORDINAL + r" ?Medicao ?- ?" + _MES + r" ?/ ?\d{4}", _I)
# dados gerais: "N.º da Medição" com o valor noutro bloco ("26ª 01/07/2026 31/07/2026": numero, inicio e fim)
_CAMPO_NUMERO = re.compile(r"(?<![\d/.,])(\d{1,3}) ?[ao°] (" + _DATA + r") (" + _DATA + r")", _I)
# "26ª medição 01/07/2026 a 31/07/2026 31 89 R$ 1.000,00 R$ 2.000,00 ..." (dias do periodo e dias restantes, que
# podem ser negativos, e os valores do quadro)
_LINHA = re.compile(_ORDINAL + r" ?Medicao (" + _DATA + r") a (" + _DATA + r") -?\d{1,4} -?\d{1,5}"
                    r"((?: ?R\$ ?" + _VALOR + r"){2,12})", _I)
_TOTAL_REAJUSTE = re.compile(r"TOTAL REAJUSTE[ .:_]*(?:R\$ ?)?(" + _VALOR + r")", _I)
_CARTA_REAJUSTE = re.compile(r"Reajustamento da " + _ORDINAL + r"(?: ?\([^)]{0,40}\))? ?Medicao", _I)
_CONTRATO = re.compile(r"(?<![\d/.,])(\d{1,4})/(\d{4})(?!\d)(?!/\d)")
_DATA_EXTENSO = re.compile(r"\b(\d{1,2}) de " + _MES + r" de (\d{4})\b", _I)
_DATA_CARTA = re.compile(r"MT, ?(" + _DATA + r")", _I)


def _iso(dia: int, mes: int, ano: int) -> str | None:
    try:
        return date(ano, mes, dia).isoformat()
    except ValueError:
        return None


def _data(plano: str) -> str | None:
    """A data do documento: "Cidade - UF, 1 de Agosto de 2026" (Visto e capa) ou "Cidade-MT, 01/08/2026" (carta do
    reajuste). Duas datas diferentes na mesma pagina: nenhuma."""
    datas = {_iso(int(d), _MESES.index(m.lower()) + 1, int(a)) for d, m, a in _DATA_EXTENSO.findall(plano)}
    if not datas:
        datas = {_iso(int(x[:2]), int(x[3:5]), int(x[6:])) for x in _DATA_CARTA.findall(plano)}
    datas.discard(None)
    return datas.pop() if len(datas) == 1 else None


def _contratos(planos: list[str]) -> list[str]:
    """Os numeros de instrumento impressos ("060/2024 MTPAR", "N° 060/2024/MTPAR"), sem os zeros da frente."""
    return sorted({f"{int(n)}/{a}" for p in planos for n, a in _CONTRATO.findall(p)})


def numero_do_instrumento(texto: str | None) -> str | None:
    """"060/2024/MTPAR" -> "60/2024" (o numero do contrato como `contratos` o devolve); sem o padrao, None."""
    m = _CONTRATO.search(texto or "")
    return f"{int(m.group(1))}/{m.group(2)}" if m else None


def _um(numeros) -> int | None:
    """O numero, se a pagina traz um so' (dois diferentes: nenhum)."""
    unicos = {int(n) for n in numeros if int(n) > 0}
    return unicos.pop() if len(unicos) == 1 else None


def _linha_fecha(v: list[int]) -> bool:
    if len(v) == 7:
        return v[4] == v[0] and v[5] == v[0] + v[2]
    if len(v) == 5:
        return v[2] == v[0] and v[3] == v[0]
    return False


def _linhas_do_controle(planos: list[str]) -> dict[int, list[list[int]]]:
    """numero da medicao -> os valores de cada linha dela no quadro "CONTROLE FINANCEIRO": a pagina do titulo e as
    seguintes enquanto trouxerem linhas (o quadro continua na pagina seguinte sem repetir o titulo)."""
    inicio = next((i for i, p in enumerate(planos) if re.search(r"CONTROLE FINANCEIRO", p, _I)), None)
    linhas: dict[int, list[list[int]]] = {}
    if inicio is None:
        return linhas
    for i, p in enumerate(planos[inicio:]):
        achadas = _LINHA.findall(p)
        if not achadas and i > 0:
            break
        for numero, _ini, _fim, valores in achadas:
            linhas.setdefault(int(numero), []).append([_centavos(x) for x in re.findall(_VALOR, valores)])
    return linhas


def _do_controle(linhas: dict[int, list[list[int]]], numero: int | None, coluna: int) -> int | None:
    """O valor da `coluna` na linha da medicao `numero`, so' se a linha e' uma, fecha e tem a coluna. `coluna` 0 e'
    o valor a precos iniciais do periodo; 2, o reajuste do periodo (so' no quadro com as colunas de reajuste)."""
    if numero is None or len(linhas.get(numero, [])) != 1:
        return None
    v = linhas[numero][0]
    if not _linha_fecha(v) or (coluna == 2 and len(v) != 7):
        return None
    return v[coluna]


def _resultado(motivo: str | None, documento: str | None = None, campos: dict | None = None,
               leituras: dict | None = None, contratos: list[str] | None = None) -> dict:
    return {"ok": motivo is None, "motivo": motivo, "documento": documento, "campos": campos or {},
            "leituras": leituras or {"rotulo_centavos": None, "controle_centavos": None},
            "contratos": contratos or []}


def ler(paginas: list[str]) -> dict:
    """{ok, motivo, documento, campos, leituras, contratos} do boletim cujas primeiras paginas tem os textos `paginas`.

    `documento`: "medicao" (o boletim, com o Visto), "reajuste" (o PDF proprio do reajuste) ou None. `campos` traz so'
    o que foi lido: `numero` (da medicao), `data` (AAAA-MM-DD) e, so' com `ok`, `valor_centavos`. `leituras` traz as
    duas leituras do valor, cada uma em centavos ou None: `rotulo_centavos` (o valor ao lado do rotulo do Visto ou do
    "TOTAL REAJUSTE") e `controle_centavos` (a linha da medicao no quadro de controle financeiro).

    `ok=False` com `motivo`: `sem-texto`, `modelo-nao-reconhecido` (nao e' boletim deste modelo), `numero-nao-lido`,
    `numero-divergente` (a capa e o rotulo do Visto dizem medicoes diferentes), `valor-fora-do-rotulo` (o valor nao
    saiu ao lado do rotulo), `controle-nao-lido` (a linha da medicao nao foi lida no quadro) ou
    `leituras-divergentes` (as duas leituras existem e nao sao a mesma quantia).
    """
    planos = [_plano(p) for p in paginas]
    if not any(p.strip() for p in planos):
        return _resultado("sem-texto")
    linhas = _linhas_do_controle(planos)
    visto = next((p for p in planos if re.search(r"\bVisto\b", p, _I) and _FISCAL.search(p)
                  and _ROTULO_VISTO.search(p)), None)
    if visto is not None:
        return _ler_medicao(planos, visto, linhas)
    planilha = next((p for p in planos if re.search(r"TOTAL REAJUSTE", p, _I)), None)
    if planilha is not None and any(re.search(r"REAJUSTAMENTO", p, _I) for p in planos):
        return _ler_reajuste(planos, planilha, linhas)
    return _resultado("modelo-nao-reconhecido")


def _fechar(documento: str, numero: int | None, divergente: bool, data: str | None, rotulo: int | None,
            controle: int | None, contratos: list[str]) -> dict:
    campos: dict = {}
    if numero is not None:
        campos["numero"] = numero
    if data:
        campos["data"] = data
    leituras = {"rotulo_centavos": rotulo, "controle_centavos": controle}
    motivo = ("numero-divergente" if divergente else "numero-nao-lido" if numero is None
              else "valor-fora-do-rotulo" if rotulo is None else "controle-nao-lido" if controle is None
              else "leituras-divergentes" if rotulo != controle else None)
    if motivo is None:
        campos["valor_centavos"] = rotulo
    return _resultado(motivo, documento, campos, leituras, contratos)


def _ler_medicao(planos: list[str], visto: str, linhas: dict) -> dict:
    capa = next((p for p in planos if _CAPA.search(p) and re.search(r"Contratad[ao]", p, _I)
                 and re.search(r"Periodo", p, _I)), None)
    numero = _um(m[0] for m in _CAPA.findall(capa)) if capa else None
    if numero is None:
        gerais = next((p for p in planos if re.search(r"N\.? ?o da Medicao", p, _I)
                       and re.search(r"Status da Medicao", p, _I)), None)
        numero = _um(m[0] for m in _CAMPO_NUMERO.findall(gerais)) if gerais else None
    do_rotulo = _um(_ROTULO_VISTO.findall(visto))
    divergente = numero is not None and do_rotulo != numero
    ao_lado = _VISTO_AO_LADO.findall(visto)
    rotulo = _centavos(ao_lado[0][1]) if len(ao_lado) == 1 else None
    controle = _do_controle(linhas, numero, 0)
    quadro = [p for p in planos if re.search(r"CONTROLE FINANCEIRO", p, _I)]
    return _fechar("medicao", numero, divergente, _data(visto), rotulo, controle,
                   _contratos(([capa] if capa else []) + quadro))


def _ler_reajuste(planos: list[str], planilha: str, linhas: dict) -> dict:
    cartas = [p for p in planos if _CARTA_REAJUSTE.search(p)]
    numero = _um(n for p in cartas for n in _CARTA_REAJUSTE.findall(p)) if cartas else None
    totais = {_centavos(x) for x in _TOTAL_REAJUSTE.findall(planilha)}
    rotulo = totais.pop() if len(totais) == 1 else None
    controle = _do_controle(linhas, numero, 2)
    quadro = [p for p in planos if re.search(r"CONTROLE FINANCEIRO", p, _I)]
    data = next((d for d in (_data(p) for p in cartas) if d), None)
    return _fechar("reajuste", numero, False, data, rotulo, controle, _contratos(cartas + quadro))


_ROTULO_TIPO = {"execucao": "execução", "projeto": "projeto", "reajuste": "reajuste"}


def recusa(lido: dict, tipo: str, numero: int, instrumento: str | None) -> str | None:
    """Por que este boletim nao e' o desta medicao (None: pode ser). `tipo` e `numero` sao os da medicao (o numero no
    orgao, quando difere); `instrumento`, o numero do contrato no cadastro. So' recusa o que o PDF diz com todas as
    letras: o documento do outro tipo, a medicao de outro numero e o contrato de outra obra. O que nao foi lido nao
    recusa (a pessoa confere e digita)."""
    documento = lido.get("documento")
    if documento is None:
        return None
    if documento == "reajuste" and tipo != "reajuste":
        return (f"Este PDF é o do reajuste, e esta é a medição de {_ROTULO_TIPO.get(tipo, tipo)}: "
                "escolha o boletim da medição")
    if documento == "medicao" and tipo == "reajuste":
        return "Este PDF é o boletim da medição, e esta é a medição de reajuste: escolha o PDF do reajuste"
    lida = lido["campos"].get("numero")
    if lida is not None and lida != numero:
        return f"Este boletim é da {lida}ª medição, e esta é a {numero}ª: escolha o PDF da {numero}ª medição"
    da_obra = numero_do_instrumento(instrumento)
    if da_obra and lido["contratos"] and da_obra not in lido["contratos"]:
        return (f"Este boletim é de outra obra: traz o contrato {', '.join(lido['contratos'])}, e o desta obra é o "
                f"{da_obra}")
    return None


def ler_pdf(pdf: bytes) -> dict:
    """`ler` sobre as primeiras `PAGINAS` paginas do PDF, so' pelo texto (sem OCR). Nunca levanta: o PDF que o pypdf
    nao abre e' `sem-texto`; o recusado pela guarda, pela fila ou pelo prazo, `pdf-recusado` (com a frase em `aviso`)."""
    try:
        paginas = leitura_pdf.paginas_iniciais_com_limite(pdf, PAGINAS)
    except leitura_pdf.TextoInadequado as e:
        return {**_resultado("pdf-recusado"), "aviso": str(e)}
    except ValueError:
        return _resultado("sem-texto")
    return ler(paginas)
