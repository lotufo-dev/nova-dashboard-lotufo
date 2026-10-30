"""Leitor deterministico da capa do boletim do SMO da SINFRA (spec 2026-10-20 §2.3, D4).

Puro no miolo (`ler`: texto da pagina da capa -> campos, sem banco nem arquivo), no padrao de `leitura_nfse`;
`ler_pdf` busca o texto das 2 primeiras paginas (`leitura_pdf`, em subprocesso com limite), acha a pagina da capa e
cai no OCR local quando nao ha texto. Sem custo de API: regex sobre texto, Tesseract na maquina como reserva.

Leiaute: "Relatorio de Capa da Medicao" (ou "Capa da Medicao Reajustada") do SMO, desenhado sobre os textos das
capas reais extraidos do SharePoint (MT-402, MT-388, Leblon, BRT, Estacoes, Atalaia, MT-401). No texto do pypdf o
rotulo vem numa linha e o valor na seguinte (": 14/08/2026"); no do OCR, rotulo e valor na mesma linha e dois pares
lado a lado. Por isso o leitor casa sobre o texto com espacos e quebras NORMALIZADOS, como o DANFSe, e sem acentos
(o Tesseract nem sempre os le), com os rotulos em qualquer caixa. A capa e' uma pagina com tres marcas
independentes ("Capa da Medicao", "RESUMO FINANCEIRO" e a linha "N - Nª Medicao ... Tipo"); paginas que so' juntas
teriam as marcas nunca viram capa.

O numero da medicao e' o ordinal ("32ª Medição Final"), nao o sequencial do SMO que vem antes do traco
("29 - 32ª ..."): costumam coincidir e diferem na medicao final e quando o SMO renumerou (medicao reapresentada).
Situacao e' o texto entre o traco e o rotulo "Tipo" (assim em todas as capas reais); so' "APROVADA", exato, e'
aprovacao. Valores em centavos inteiros: "Faturamento realizado da presente medicao" da' o valor a precos iniciais
(o da NF da medicao), o reajustamento (o da NF do reajuste) e o total; o mesmo para o acumulado. Fins de vigencia e
de execucao e dias paralisados saem para a conferencia contra o cadastro.

O que nao e' proposto (vira aviso, e a pessoa digita): bloco cuja soma nao fecha; presente medicao sem o acumulado
lido ou maior que ele em qualquer parcela; no OCR, numero sem a confirmacao do ordinal por extenso noutra pagina
("8ª (oitava)" do oficio) e data de realizacao sem periodo lido ou anterior ao fim dele. Toda leitura por OCR sai
com aviso de conferencia.
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

# Os padroes casam sobre o texto SEM ACENTO (`_plano`) e, nos rotulos, em qualquer caixa (re.I).
_I = re.IGNORECASE
_DATA = r"(\d{2}/\d{2}/\d{4})"
_ATE = r"\s*(?:a|ate)\s*"
_NUM = r"\s*:\s*(-?\s?\d{1,3}(?:\.\d{3})*,\d{2})"
_BLOCO = (r"\s*Precos iniciais" + _NUM + r"\s*Reajustamento" + _NUM + r"(?:\s*Acrescimos" + _NUM + r")?"
          r"(?:\s*Descontos" + _NUM + r")?\s*Total" + _NUM)
# "26 - 26ª Medição Provisória - APROVADA Tipo" (sem acento, o ª vira "a" e o º vira "o"; o OCR troca o traco por
# "–"/"—"). Em todas as 123 capas reais a situacao vem seguida do rotulo "Tipo": e' o unico delimitador.
_TRACO = r"\s*[-–—]\s*"
_MEDICAO = re.compile(r"\b(\d{1,3})" + _TRACO + r"(\d{1,3})\s*(?:°|[ao](?=\s))?\s*Medicao (Provisoria|Final)"
                      + _TRACO + r"(.{1,60}?)\s*(?=\bTipo\b)", _I)
_EXTENSO = re.compile(r"\b\d{1,3}\s*\S{0,2}\s*\(([A-Za-z ]{4,40})\)\s*medi", _I)
_UNIDADES = {"primeir": 1, "segund": 2, "terceir": 3, "quart": 4, "quint": 5, "sext": 6, "setim": 7, "oitav": 8,
             "non": 9}
_DEZENAS = {"decim": 10, "vigesim": 20, "trigesim": 30, "quadragesim": 40, "quinquagesim": 50, "sexagesim": 60,
            "septuagesim": 70, "setuagesim": 70, "octogesim": 80, "nonagesim": 90}
_AVISO_OCR = "campos lidos por OCR: confira cada um contra o PDF antes de aceitar"


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


def _plano(texto: str | None) -> str:
    """Texto sem acento (ª -> a, º -> o) e com espacos e quebras de linha reduzidos a um espaco."""
    t = unicodedata.normalize("NFKD", texto or "")
    return re.sub(r"\s+", " ", "".join(ch for ch in t if not unicodedata.combining(ch)))


def _ordinal_por_extenso(texto: str) -> int | None:
    """'Vigésima Sexta' -> 26, 'oitava' -> 8; palavra que nao e' ordinal -> None."""
    total = 0
    for palavra in _plano(texto).lower().split():
        raiz = palavra[:-1] if palavra[-1:] in "ao" else palavra
        valor = _UNIDADES.get(raiz) or _DEZENAS.get(raiz)
        if valor is None:
            return None
        total += valor
    return total or None


def _fim(rotulo: str, plano: str) -> str | None:
    m = re.search(rotulo + r"\s*:\s*" + _DATA + _ATE + _DATA, plano, _I)
    return _iso(m.group(2)) if m else None


def e_capa(texto: str) -> bool:
    """A pagina e' uma capa do SMO: as tres marcas, e nao so' o nome do arquivo num certificado do DocuSign."""
    plano = _plano(texto)
    return re.search(r"Capa da Medicao", plano, _I) is not None and \
        re.search(r"RESUMO FINANCEIRO", plano, _I) is not None and _MEDICAO.search(plano) is not None


def _bloco(rotulo: str, plano: str, nomes: tuple[str, ...], avisos: list, quem: str) -> dict:
    """Um bloco do resumo financeiro, so' se a soma fecha: PI + reajustamento + acrescimos - descontos = total, como
    em todas as capas reais; o que nao fecha (OCR que perdeu um digito) vira aviso e volta vazio."""
    m = re.search(rotulo + _BLOCO, plano, _I)
    if not m:
        if re.search(rotulo, plano, _I):
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
    """O acumulado inclui a presente medicao: nenhuma parcela da presente passa da do acumulado (PI, total,
    acrescimos e descontos, ausente = zero; o reajustamento quando os dois sao positivos). Pega o bloco errado (OCR
    que emendou os rotulos) e o digito trocado num bloco so'."""
    pares = (("valor_centavos", "acumulado_pi_centavos"), ("total_centavos", "acumulado_total_centavos"),
             ("acrescimos_centavos", "acumulado_acrescimos_centavos"),
             ("descontos_centavos", "acumulado_descontos_centavos"))
    if any(pres.get(p, 0) > acum.get(a, 0) for p, a in pares):
        return False
    r, ra = pres["reajuste_centavos"], acum["acumulado_reajuste_centavos"]
    return not (r > 0 and ra >= 0 and r > ra)


def ler(texto: str, ocr: bool = False, contexto: str = "") -> dict:
    """{ok, motivo, campos, faltando, avisos} da pagina `texto` (a da capa).

    `campos` traz so' o que foi lido (nunca None, nunca zero inventado); `faltando` os nomes de `CAMPOS` que nao
    foram lidos. `ok=False` com motivo `sem-texto`, `capa-nao-encontrada`, `nao-aprovada` (situacao em `campos`)
    ou `campos-ausentes:<lista>` (so' os obrigatorios); fora `sem-texto` e `capa-nao-encontrada`, o que foi lido
    volta mesmo assim, para a pessoa so' completar. `ocr=True` aperta as regras (ver o modulo); `contexto` e' o
    texto das OUTRAS paginas lidas (o oficio), unico lugar de onde sai a confirmacao do numero por extenso.
    """
    plano = _plano(texto)
    if not plano.strip():
        return _resultado("sem-texto", {}, [])
    if not e_capa(plano):
        return _resultado("capa-nao-encontrada", {}, [])
    m = _MEDICAO.search(plano)
    # sobra de OCR entre a situacao e o "Tipo" ("APROVADA.", "APROVADA |") nao conta
    situacao = re.sub(r"[\s.,;:|/\\]+$", "", m.group(4)).strip()
    if ocr and situacao != situacao.upper():
        return _resultado("capa-nao-encontrada", {}, [])   # minuscula onde o SMO so' imprime maiuscula: OCR torto
    c: dict = {}
    avisos: list[str] = []

    ordinal = int(m.group(2))
    if ocr:
        if ordinal in {_ordinal_por_extenso(x) for x in _EXTENSO.findall(_plano(contexto))}:
            c["numero"] = ordinal
        else:
            avisos.append(f"a leitura por OCR traz a {ordinal}ª medição, sem o número por extenso que a confirme; "
                          "confira e digite o número")
    elif ordinal > 0:
        c["numero"] = ordinal
    c["tipo_medicao"] = "final" if m.group(3).lower() == "final" else "provisoria"
    c["situacao"] = situacao

    m = re.search(r"Periodo da medicao\s*:\s*" + _DATA + _ATE + _DATA, plano, _I)
    if m:
        ini, fim = _iso(m.group(1)), _iso(m.group(2))
        if ini and fim and fim >= ini:
            c["periodo"] = (ini, fim)
    m = re.search(r"Data de realizacao\s*:\s*" + _DATA, plano, _I)
    realizacao = _iso(m.group(1)) if m else None
    if realizacao and "periodo" in c and realizacao < c["periodo"][1]:
        avisos.append("a data de realização é anterior ao fim do período da medição; confira a data")
        if ocr:
            realizacao = None
    elif realizacao and ocr and "periodo" not in c:
        avisos.append("sem o período da medição lido não há como conferir a data de realização; digite a data")
        realizacao = None
    if realizacao:
        c["data_realizacao"] = realizacao

    pres = _bloco(r"Faturamento realizado da presente medicao", plano,
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

    for campo, rotulo in (("vigencia_fim", r"Periodo de vigencia"), ("execucao_fim", r"Periodo de execucao")):
        fim = _fim(rotulo, plano)
        if fim:
            c[campo] = fim
    # "Dias paralisados : 93" do contrato, nao o "Dias paralisados até a presente medição"; o OCR le zero como "O"
    m = re.search(r"Dias paralisados\s*:?\s*(\d{1,5}|(?-i:O))\b", plano, _I)
    if m:
        c["dias_paralisados"] = 0 if m.group(1) == "O" else int(m.group(1))
    if ocr:
        avisos.append(_AVISO_OCR)

    if c["situacao"] != "APROVADA":
        return _resultado("nao-aprovada", c, avisos)
    faltando = [x for x in CAMPOS_OBRIGATORIOS if x not in c]
    return _resultado("campos-ausentes:" + ",".join(faltando) if faltando else None, c, avisos)


def _resultado(motivo: str | None, campos: dict, avisos: list) -> dict:
    return {"ok": motivo is None, "motivo": motivo, "campos": campos,
            "faltando": [x for x in CAMPOS if x not in campos], "avisos": avisos}


def _ler_paginas(paginas: list[str], ocr: bool) -> dict:
    """`ler` na primeira pagina que, sozinha, e' capa, com as outras como contexto. Nunca sobre a juncao das paginas:
    um certificado do DocuSign na p. 1 e um relatorio na p. 2 juntos teriam as marcas da capa."""
    for i, pagina in enumerate(paginas):
        if e_capa(pagina):
            return ler(pagina, ocr=ocr, contexto="\n".join(paginas[:i] + paginas[i + 1:]))
    return _resultado("capa-nao-encontrada" if any(p.strip() for p in paginas) else "sem-texto", {}, [])


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
