"""Leitor deterministico da capa do boletim do SMO da SINFRA (spec 2026-10-20 §2.3, D4).

Puro no miolo (`ler`: texto -> campos, sem banco nem arquivo), no padrao de `leitura_nfse`; `ler_pdf` so' busca o
texto das 2 primeiras paginas (`leitura_pdf`, em subprocesso com limite) e cai no OCR local quando nao ha texto.
Sem custo de API: regex sobre texto, Tesseract na maquina como reserva.

Leiaute: "Relatorio de Capa da Medicao" (ou "Capa da Medicao Reajustada") do SMO, desenhado sobre os textos das
capas reais extraidos do SharePoint (MT-402, MT-388, Leblon, BRT, Estacoes, Atalaia, MT-401). No texto do pypdf o
rotulo vem numa linha e o valor na seguinte (": 14/08/2026"); no do OCR, rotulo e valor na mesma linha e dois pares
lado a lado. Por isso o leitor casa sobre o texto com espacos e quebras NORMALIZADOS, como o DANFSe.

O numero da medicao e' o ordinal ("32ª Medição Final"), nao o sequencial do SMO que vem antes do traco
("29 - 32ª ..."): costumam coincidir e diferem na medicao final e quando o SMO renumerou (medicao reapresentada).
No texto a diferenca nao avisa; no OCR avisa, porque pode ser leitura errada. Situacao diferente de APROVADA e'
recusa. Valores em centavos inteiros: "Faturamento realizado da presente medicao" da' o valor a precos iniciais
(o da NF da medicao), o reajustamento (o da NF do reajuste) e o total; o mesmo para o acumulado. Bloco cuja soma
nao fecha (PI + reajustamento != total, tipico de OCR que perdeu um digito) nao e' proposto: vira aviso e a pessoa
digita. Fins de vigencia e de execucao e dias paralisados saem para a conferencia contra o cadastro.
"""
import re
from datetime import date

from . import leitura_pdf

# Campos sem os quais nao ha proposta de boletim (a pessoa digita os tres, spec §2.1 passo 3).
CAMPOS_OBRIGATORIOS = ("numero", "data_realizacao", "valor_centavos")
CAMPOS = ("numero", "tipo_medicao", "situacao", "periodo", "data_realizacao",
          "valor_centavos", "reajuste_centavos", "total_centavos",
          "acumulado_pi_centavos", "acumulado_reajuste_centavos", "acumulado_total_centavos",
          "vigencia_fim", "execucao_fim", "dias_paralisados")

_DATA = r"(\d{2}/\d{2}/\d{4})"
_ATE = r"\s*(?:a|à|até)\s*"
_NUM = r"\s*:\s*(-?\s?\d{1,3}(?:\.\d{3})*,\d{2})"
# Acrescimos e Descontos so' aparecem em algumas capas (MT-401, Estacoes); o desconto vem ora com sinal, ora sem.
_BLOCO = (r"\s*Preços iniciais" + _NUM + r"\s*Reajustamento" + _NUM + r"(?:\s*Acréscimos" + _NUM + r")?"
          r"(?:\s*Descontos" + _NUM + r")?\s*Total" + _NUM)
# "26 - 26ª Medição Provisória - APROVADA"; o OCR troca o ª por "a"/"o" e o traco por "–"/"—". A situacao pega ate'
# duas palavras em maiusculas (o texto achatado pode emendar "APROVADA RESUMO FINANCEIRO").
_TRACO = r"\s*[-–—]\s*"
_MEDICAO = re.compile(r"\b(\d{1,3})" + _TRACO + r"(\d{1,3})\s*(?:[ªº°]|[ao](?=\s))?\s*Medição (Provisória|Final)"
                      + _TRACO + r"([A-ZÀ-Ý]+(?![a-zà-ÿ])(?: [A-ZÀ-Ý]+(?![a-zà-ÿ]))?)")


def _centavos(texto: str) -> int:
    """'2.509.917,07' -> 250991707; '-1.234,56' -> -123456 (reajustamento pode ser negativo)."""
    t = texto.replace(" ", "")
    negativo = t.startswith("-")
    inteiro, frac = t.lstrip("-").split(",")
    v = int(inteiro.replace(".", "")) * 100 + int(frac)
    return -v if negativo else v


def _iso(dmy: str) -> str | None:
    """'14/08/2026' -> '2026-08-14'; data que nao existe (OCR que trocou um digito) -> None."""
    d, m, a = (int(x) for x in dmy.split("/"))
    try:
        return date(a, m, d).isoformat()
    except ValueError:
        return None


def _fim(rotulo: str, plano: str) -> str | None:
    m = re.search(rotulo + r"\s*:\s*" + _DATA + _ATE + _DATA, plano)
    return _iso(m.group(2)) if m else None


def _e_capa(plano: str) -> bool:
    return "Capa da Medição" in plano and _MEDICAO.search(plano) is not None


def _bloco(rotulo: str, plano: str, nomes: tuple[str, str, str], c: dict, avisos: list, quem: str,
           presente: bool) -> None:
    """Le' um bloco do resumo financeiro e so' o propoe se a soma fecha: PI + reajustamento + acrescimos - descontos
    = total, como em todas as capas reais; o que nao fecha (OCR que perdeu um digito) vira aviso, e a pessoa digita.
    Acrescimo ou desconto na presente medicao vira aviso (o valor da nota pode nao ser o PI); no acumulado, nao."""
    m = re.search(rotulo + _BLOCO, plano)
    if not m:
        if rotulo in plano:
            avisos.append(f"{quem}: a capa traz o bloco, mas os valores não foram reconhecidos; digite os valores")
        return
    pi, reaj, acrescimos, descontos, total = (_centavos(x) if x else 0 for x in m.groups())
    if pi + reaj + acrescimos - abs(descontos) != total:
        avisos.append(f"{quem}: os valores da capa não fecham com o total impresso; confira e digite os valores")
        return
    c.update(zip(nomes, (pi, reaj, total)))
    if presente and (acrescimos or descontos):
        avisos.append(f"{quem}: a capa tem acréscimos ou descontos além dos preços iniciais e do reajustamento; "
                      "confira o valor da nota")


def ler(texto: str, ocr: bool = False) -> dict:
    """{ok, motivo, campos, faltando, avisos}.

    `campos` traz so' o que foi lido (nunca None, nunca zero inventado); `faltando` os nomes de `CAMPOS` que nao
    foram lidos. `ok=False` com motivo `sem-texto`, `capa-nao-encontrada`, `nao-aprovada` (situacao em `campos`)
    ou `campos-ausentes:<lista>` (so' os obrigatorios); fora `sem-texto` e `capa-nao-encontrada`, o que foi lido
    volta mesmo assim, para a pessoa so' completar.
    """
    plano = re.sub(r"\s+", " ", texto or "")
    if not plano.strip():
        return _resultado("sem-texto", {}, [])
    if not _e_capa(plano):
        return _resultado("capa-nao-encontrada", {}, [])
    c: dict = {}
    avisos: list[str] = []

    m = _MEDICAO.search(plano)
    sequencial, ordinal = int(m.group(1)), int(m.group(2))
    if ocr and sequencial != ordinal:
        # no texto e' comum (medicao reapresentada, medicao final); no OCR pode ser leitura errada ("8º" lido "82"),
        # e o numero nao e' proposto
        avisos.append(f"a leitura da capa traz {sequencial} no sequencial do SMO e {ordinal}ª no nome da medição; "
                      "confira e digite o número")
    elif ordinal > 0:
        c["numero"] = ordinal
    c["tipo_medicao"] = "final" if m.group(3) == "Final" else "provisoria"
    c["situacao"] = "APROVADA" if m.group(4).split()[0] == "APROVADA" else m.group(4)

    m = re.search(r"Período da medição\s*:\s*" + _DATA + _ATE + _DATA, plano)
    if m:
        ini, fim = _iso(m.group(1)), _iso(m.group(2))
        if ini and fim and fim >= ini:
            c["periodo"] = (ini, fim)
    m = re.search(r"Data de realização\s*:\s*" + _DATA, plano)
    if m and _iso(m.group(1)):
        c["data_realizacao"] = _iso(m.group(1))

    _bloco(r"Faturamento realizado da presente medição", plano,
           ("valor_centavos", "reajuste_centavos", "total_centavos"), c, avisos, "presente medição", True)
    _bloco(r"Faturamento realizado acumulado", plano,
           ("acumulado_pi_centavos", "acumulado_reajuste_centavos", "acumulado_total_centavos"), c, avisos,
           "acumulado", False)

    for campo, rotulo in (("vigencia_fim", r"Período de vigência"), ("execucao_fim", r"Período de execução")):
        fim = _fim(rotulo, plano)
        if fim:
            c[campo] = fim
    # "Dias paralisados : 93" do contrato, nao o "Dias paralisados até a presente medição"; o OCR le zero como "O"
    m = re.search(r"Dias paralisados\s*:?\s*(\d{1,5}|O)\b", plano)
    if m:
        c["dias_paralisados"] = 0 if m.group(1) == "O" else int(m.group(1))

    if c["situacao"] != "APROVADA":
        return _resultado("nao-aprovada", c, avisos)
    faltando = [x for x in CAMPOS_OBRIGATORIOS if x not in c]
    return _resultado("campos-ausentes:" + ",".join(faltando) if faltando else None, c, avisos)


def _resultado(motivo: str | None, campos: dict, avisos: list) -> dict:
    return {"ok": motivo is None, "motivo": motivo, "campos": campos,
            "faltando": [x for x in CAMPOS if x not in campos], "avisos": avisos}


def ler_pdf(pdf: bytes) -> dict:
    """`ler` sobre as 2 primeiras paginas do PDF, com `fonte` = "texto" ou "ocr" (None quando nenhuma serviu).

    A capa vem na p. 1 (PDF so' da capa) ou na p. 2 (pacote do DocuSign com o oficio na frente). Sem capa no texto
    (PDF de imagem, como os envelopes do BRT Lote 1), tenta o OCR local das mesmas paginas; sem OCR instalado ou com
    OCR que falhou, devolve o resultado do texto e a pessoa digita.
    """
    try:
        texto = "\n".join(leitura_pdf.primeiras_paginas_com_limite(pdf))
    except (leitura_pdf.TextoInadequado, ValueError):
        texto = ""      # o pypdf nao abriu (ou fila, ou prazo): o OCR ainda pode ler; senao a pessoa digita
    lido = ler(texto)
    if lido["motivo"] not in ("sem-texto", "capa-nao-encontrada"):
        return {**lido, "fonte": "texto"}
    texto_ocr = leitura_pdf.texto_por_ocr_com_limite(pdf, pacote=True)
    if texto_ocr is not None:
        lido_ocr = ler(texto_ocr, ocr=True)
        if lido_ocr["motivo"] not in ("sem-texto", "capa-nao-encontrada"):
            return {**lido_ocr, "fonte": "ocr"}
    return {**lido, "fonte": None}
