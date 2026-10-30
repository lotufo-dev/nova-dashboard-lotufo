"""Leitor deterministico da capa do boletim do SMO da SINFRA (spec 2026-10-20 §2.3, D4).

Puro no miolo (`ler`: texto da pagina da capa -> campos, sem banco nem arquivo), no padrao de `leitura_nfse`;
`ler_pdf` busca o texto das 2 primeiras paginas (`leitura_pdf`, em subprocesso com limite), acha a pagina da capa e
cai no OCR local quando nao ha texto. Sem custo de API: regex sobre texto, Tesseract na maquina como reserva.

Leiaute: "Relatorio de Capa da Medicao" (ou "Capa da Medicao Reajustada") do SMO, desenhado sobre os textos das
capas reais extraidos do SharePoint (MT-402, MT-388, Leblon, BRT, Estacoes, Atalaia, MT-401). No texto do pypdf o
rotulo vem numa linha e o valor na seguinte (": 14/08/2026"); no do OCR, rotulo e valor na mesma linha e dois pares
lado a lado. Por isso o leitor casa sobre o texto com espacos e quebras NORMALIZADOS, como o DANFSe. A capa e'
reconhecida por tres marcas independentes ("Capa da Medicao", "RESUMO FINANCEIRO" e a linha "N - Nª Medicao ...").

O numero da medicao e' o ordinal ("32ª Medição Final"), nao o sequencial do SMO que vem antes do traco
("29 - 32ª ..."): costumam coincidir e diferem na medicao final e quando o SMO renumerou (medicao reapresentada).
Situacao e' o texto entre o traco e o rotulo "Tipo"; so' "APROVADA", exato, e' aprovacao. Valores em centavos
inteiros: "Faturamento realizado da presente medicao" da' o valor a precos iniciais (o da NF da medicao), o
reajustamento (o da NF do reajuste) e o total; o mesmo para o acumulado. Fins de vigencia e de execucao e dias
paralisados saem para a conferencia contra o cadastro.

O que nao e' proposto (vira aviso, e a pessoa digita): bloco cuja soma nao fecha; presente medicao sem o acumulado
lido ou maior que ele; no OCR, numero sem a confirmacao do ordinal por extenso do oficio ("8ª (oitava)") e data de
realizacao anterior ao fim do periodo. Todo valor lido por OCR sai com aviso de conferencia.
"""
import re
import unicodedata
from datetime import date

from . import leitura_pdf

# Campos sem os quais nao ha proposta de boletim (a pessoa digita os tres, spec §2.1 passo 3).
CAMPOS_OBRIGATORIOS = ("numero", "data_realizacao", "valor_centavos")
CAMPOS = ("numero", "tipo_medicao", "situacao", "periodo", "data_realizacao",
          "valor_centavos", "reajuste_centavos", "total_centavos",
          "acumulado_pi_centavos", "acumulado_reajuste_centavos", "acumulado_total_centavos",
          "vigencia_fim", "execucao_fim", "dias_paralisados")
# So' existem nas capas que imprimem as linhas (MT-401, Estacoes); ausentes nao contam como "faltando". Descontos
# em modulo: o SMO imprime ora "-1.500,00", ora "250,00", e sempre os subtrai do total.
CAMPOS_OPCIONAIS = ("acrescimos_centavos", "descontos_centavos",
                    "acumulado_acrescimos_centavos", "acumulado_descontos_centavos")

_DATA = r"(\d{2}/\d{2}/\d{4})"
_ATE = r"\s*(?:a|à|até)\s*"
_NUM = r"\s*:\s*(-?\s?\d{1,3}(?:\.\d{3})*,\d{2})"
_BLOCO = (r"\s*Preços iniciais" + _NUM + r"\s*Reajustamento" + _NUM + r"(?:\s*Acréscimos" + _NUM + r")?"
          r"(?:\s*Descontos" + _NUM + r")?\s*Total" + _NUM)
# "26 - 26ª Medição Provisória - APROVADA Tipo"; o OCR troca o ª por "a"/"o" e o traco por "–"/"—". Em todas as capas
# reais a situacao vem seguida do rotulo "Tipo"; os outros rotulos sao reserva, para nunca emendar o texto seguinte.
_TRACO = r"\s*[-–—]\s*"
_MEDICAO = re.compile(r"\b(\d{1,3})" + _TRACO + r"(\d{1,3})\s*(?:[ªº°]|[ao](?=\s))?\s*Medição (Provisória|Final)"
                      + _TRACO + r"(.{1,60}?)\s*(?=\bTipo\b|Período da medição|Data de realização|RESUMO FINANCEIRO)")
_EXTENSO = re.compile(r"\b\d{1,3}\s*\S{0,2}\s*\(([A-Za-zÀ-ÿ ]{4,40})\)\s*[Mm]edi")
_UNIDADES = {"primeir": 1, "segund": 2, "terceir": 3, "quart": 4, "quint": 5, "sext": 6, "setim": 7, "oitav": 8,
             "non": 9}
_DEZENAS = {"decim": 10, "vigesim": 20, "trigesim": 30, "quadragesim": 40, "quinquagesim": 50, "sexagesim": 60,
            "septuagesim": 70, "setuagesim": 70, "octogesim": 80, "nonagesim": 90}
_AVISO_OCR = "valores lidos por OCR: confira cada um contra o PDF antes de aceitar"


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


def _ordinal_por_extenso(texto: str) -> int | None:
    """'Vigésima Sexta' -> 26, 'oitava' -> 8; palavra que nao e' ordinal -> None."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    total = 0
    for palavra in sem_acento.split():
        raiz = palavra[:-1] if palavra[-1:] in "ao" else palavra
        valor = _UNIDADES.get(raiz) or _DEZENAS.get(raiz)
        if valor is None:
            return None
        total += valor
    return total or None


def _fim(rotulo: str, plano: str) -> str | None:
    m = re.search(rotulo + r"\s*:\s*" + _DATA + _ATE + _DATA, plano)
    return _iso(m.group(2)) if m else None


def _plano(texto: str | None) -> str:
    return re.sub(r"\s+", " ", texto or "")


def e_capa(texto: str) -> bool:
    """A pagina e' uma capa do SMO: as tres marcas, e nao so' o nome do arquivo num certificado do DocuSign."""
    plano = _plano(texto)
    return "Capa da Medição" in plano and "RESUMO FINANCEIRO" in plano and _MEDICAO.search(plano) is not None


def _bloco(rotulo: str, plano: str, nomes: tuple[str, ...], avisos: list, quem: str) -> dict:
    """Um bloco do resumo financeiro, so' se a soma fecha: PI + reajustamento + acrescimos - descontos = total, como
    em todas as capas reais; o que nao fecha (OCR que perdeu um digito) vira aviso e volta vazio."""
    m = re.search(rotulo + _BLOCO, plano)
    if not m:
        if rotulo in plano:
            avisos.append(f"{quem}: a capa traz o bloco, mas os valores não foram reconhecidos; digite os valores")
        return {}
    pi, reaj, acrescimos, descontos, total = (_centavos(x) if x else None for x in m.groups())
    if pi + reaj + (acrescimos or 0) - abs(descontos or 0) != total:
        avisos.append(f"{quem}: os valores da capa não fecham com o total impresso; confira e digite os valores")
        return {}
    lido = dict(zip(nomes[:3], (pi, reaj, total)))
    if acrescimos is not None:
        lido[nomes[3]] = acrescimos
    if descontos is not None:
        lido[nomes[4]] = abs(descontos)
    return lido


def _presente_cabe_no_acumulado(pres: dict, acum: dict) -> bool:
    """O acumulado inclui a presente medicao: PI e total da presente nunca passam dos do acumulado (e o reajustamento,
    quando os dois sao positivos). Pega o bloco errado (OCR que emendou os rotulos) e o digito trocado num so'."""
    if pres["valor_centavos"] > acum["acumulado_pi_centavos"] or \
            pres["total_centavos"] > acum["acumulado_total_centavos"]:
        return False
    r, ra = pres["reajuste_centavos"], acum["acumulado_reajuste_centavos"]
    return not (r > 0 and ra >= 0 and r > ra)


def ler(texto: str, ocr: bool = False, contexto: str = "") -> dict:
    """{ok, motivo, campos, faltando, avisos} da pagina `texto` (a da capa).

    `campos` traz so' o que foi lido (nunca None, nunca zero inventado); `faltando` os nomes de `CAMPOS` que nao
    foram lidos. `ok=False` com motivo `sem-texto`, `capa-nao-encontrada`, `nao-aprovada` (situacao em `campos`)
    ou `campos-ausentes:<lista>` (so' os obrigatorios); fora `sem-texto` e `capa-nao-encontrada`, o que foi lido
    volta mesmo assim, para a pessoa so' completar. `ocr=True` aperta as regras (ver o modulo); `contexto` e' o
    texto das outras paginas lidas (o oficio), de onde sai a confirmacao do numero por extenso.
    """
    plano = _plano(texto)
    if not plano.strip():
        return _resultado("sem-texto", {}, [])
    if not e_capa(plano):
        return _resultado("capa-nao-encontrada", {}, [])
    c: dict = {}
    avisos: list[str] = []

    m = _MEDICAO.search(plano)
    ordinal = int(m.group(2))
    if ocr:
        extensos = {_ordinal_por_extenso(x) for x in _EXTENSO.findall(_plano(contexto) + " " + plano)}
        if ordinal in extensos:
            c["numero"] = ordinal
        else:
            avisos.append(f"a leitura por OCR traz a {ordinal}ª medição, sem o número por extenso que a confirme; "
                          "confira e digite o número")
    elif ordinal > 0:
        c["numero"] = ordinal
    c["tipo_medicao"] = "final" if m.group(3) == "Final" else "provisoria"
    c["situacao"] = m.group(4).strip()

    m = re.search(r"Período da medição\s*:\s*" + _DATA + _ATE + _DATA, plano)
    if m:
        ini, fim = _iso(m.group(1)), _iso(m.group(2))
        if ini and fim and fim >= ini:
            c["periodo"] = (ini, fim)
    m = re.search(r"Data de realização\s*:\s*" + _DATA, plano)
    realizacao = _iso(m.group(1)) if m else None
    if realizacao and "periodo" in c and realizacao < c["periodo"][1]:
        avisos.append("a data de realização é anterior ao fim do período da medição; confira a data")
        if ocr:
            realizacao = None
    if realizacao:
        c["data_realizacao"] = realizacao

    pres = _bloco(r"Faturamento realizado da presente medição", plano,
                  ("valor_centavos", "reajuste_centavos", "total_centavos", "acrescimos_centavos",
                   "descontos_centavos"), avisos, "presente medição")
    acum = _bloco(r"Faturamento realizado acumulado", plano,
                  ("acumulado_pi_centavos", "acumulado_reajuste_centavos", "acumulado_total_centavos",
                   "acumulado_acrescimos_centavos", "acumulado_descontos_centavos"), avisos, "acumulado")
    if pres and acum and not _presente_cabe_no_acumulado(pres, acum):
        avisos.append("os valores da presente medição passam do acumulado; confira e digite os valores")
        pres, acum = {}, {}
    elif pres and not acum:
        avisos.append("sem o acumulado lido não há como conferir os valores da presente medição; digite os valores")
        pres = {}
    if pres.get("acrescimos_centavos") or pres.get("descontos_centavos"):
        avisos.append("presente medição: a capa tem acréscimos ou descontos além dos preços iniciais e do "
                      "reajustamento; confira o valor da nota")
    c.update(pres)
    c.update(acum)
    if ocr and (pres or acum):
        avisos.append(_AVISO_OCR)

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


def _ler_paginas(paginas: list[str], ocr: bool) -> dict:
    """`ler` na primeira pagina que e' capa, com as outras como contexto; nenhuma capa -> o `ler` do texto todo."""
    for i, pagina in enumerate(paginas):
        if e_capa(pagina):
            return ler(pagina, ocr=ocr, contexto="\n".join(paginas[:i] + paginas[i + 1:]))
    return ler("\n".join(paginas), ocr=ocr)


def ler_pdf(pdf: bytes) -> dict:
    """`ler` sobre a capa nas 2 primeiras paginas do PDF, com `fonte` = "texto" ou "ocr" (None quando nenhuma serviu).

    A capa vem na p. 1 (PDF so' da capa) ou na p. 2 (pacote do DocuSign com o oficio na frente). Sem capa no texto
    (PDF de imagem, como os envelopes do BRT Lote 1), tenta o OCR local das mesmas paginas; sem OCR instalado ou com
    OCR que falhou, devolve o resultado do texto e a pessoa digita. PDF recusado pela guarda, pela fila ou pelo prazo
    (`TextoInadequado`) nao vai ao OCR, que passaria pela mesma guarda: motivo `pdf-recusado`, com a mensagem.
    """
    try:
        paginas = leitura_pdf.primeiras_paginas_com_limite(pdf)
    except leitura_pdf.TextoInadequado as e:
        return {**_resultado("pdf-recusado", {}, [str(e)]), "fonte": None}
    except ValueError:
        paginas = []    # o pypdf nao abriu (PDF torto que o pdfium ainda desenha): fica com o OCR
    lido = _ler_paginas(paginas, ocr=False)
    if lido["motivo"] not in ("sem-texto", "capa-nao-encontrada"):
        return {**lido, "fonte": "texto"}
    paginas_ocr = leitura_pdf.paginas_por_ocr_com_limite(pdf)
    if paginas_ocr is not None:
        lido_ocr = _ler_paginas(paginas_ocr, ocr=True)
        if lido_ocr["motivo"] not in ("sem-texto", "capa-nao-encontrada"):
            return {**lido_ocr, "fonte": "ocr"}
    return {**lido, "fonte": None}
