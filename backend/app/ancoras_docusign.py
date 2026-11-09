"""Ancoras de texto invisiveis para o AutoPlace do DocuSign (issue #626).

A pessoa solta os PDFs do pacote de medicao, informa o nome (como esta' impresso) de cada papel que assina, e baixa
um PDF juntado com, em cada ponto de assinatura, um texto invisivel por signatario (`#ass-fiscal#`...). No DocuSign
basta um campo de assinatura por signatario com a insercao automatica pelo texto da ancora. Nada e' gravado: a
ferramenta recebe os PDFs, devolve o PDF e a lista de paginas, e esquece.

Onde a ancora vai (medido no pacote real da SINFRA de 09/11/2026 e confirmado no DocuSign nos dois testes da issue):
1. Linha que e' so' nome de signatario (mais rotulos de uma palavra terminados em `:` e os prefixos `Eng.`/`Civil`):
   a ancora vai 4 pt a' esquerda do inicio do nome, com o topo 11 pt acima do topo do nome.
2. Pagina de Diario de Obra (linha `DIARIO DE OBRA` no alto): sem nome impresso, tres ancoras no rodape.
3. Pagina sem ancora que a pessoa marcar: as mesmas tres do rodape.

A posicao de cada letra vem do pypdfium2 (le texto dentro de XObject, o que o visitor do pypdf nao faz). A leitura e a
sobreposicao rodam NO SUBPROCESSO com limite de `leitura_pdf` (os PDFs vem de fora): ver o modo "ancoras" de
`leitura_pdf._trabalho`.
"""
import io
import threading
import unicodedata

import pypdf
import pypdfium2 as pdfium
from fpdf import FPDF
from fpdf.enums import TextMode
from pypdf import Transformation

from app import leitura_pdf, pdfs

# Os quatro papeis, na ordem em que a tela os mostra: chave, rotulo na tela e texto da ancora.
PAPEIS: dict[str, tuple[str, str]] = {
    "fiscal": ("Fiscal do órgão", "#ass-fiscal#"),
    "supervisor": ("Supervisor (supervisora)", "#ass-supervisor#"),
    "executora": ("Responsável técnico da executora", "#ass-executora#"),
    "superior": ("Superior imediato do fiscal", "#ass-superior#"),
}
# Papeis do rodape (Diario e paginas marcadas) e o x absoluto de cada um, em pt da borda esquerda da pagina como ela
# e' vista (onde a pessoa assinou a mao no pacote real). O superior imediato nao assina o rodape.
RODAPE: dict[str, float] = {"fiscal": 116.0, "supervisor": 272.0, "executora": 426.0}

TAMANHO_PT = 5.0
RECUO_X_PT = 4.0                # a ancora comeca 4 pt antes do nome
SOBE_PT = 11.0                  # o topo da ancora fica 11 pt acima do topo do nome
BASELINE_RODAPE_PT = 2.0
ASCENDENTE = 0.718              # Helvetica: altura da letra (cap height) / corpo, para o topo da ancora

# Prefixos que aparecem junto do nome no bloco de assinatura ("Eng. Civil Fulano"); "Engª" vira "enga" sem o sinal.
PREFIXOS = frozenset({"eng", "enga", "engenheiro", "engenheira", "civil"})
# O Diario de Obra tem a linha no alto: so' conta a que esta' no terco de cima da pagina.
TITULO_DIARIO = "diario de obra"
FRACAO_ALTO = 0.7

TETO_PAGINAS = 600              # o pacote real da SINFRA tem 467 paginas: o teto do protocolo (400) o recusaria
TEMPO_LIMITE_S = 120.0
# Vaga PROPRIA, uma so': a leitura de ate 2 min do pacote nao pode segurar as duas vagas de `leitura_pdf._VAGAS`, de que
# dependem a certidao, o pacote do protocolo e o boletim. Segundo uso simultaneo recebe a mesma frase de espera.
_VAGA = threading.BoundedSemaphore(1)

SOMA_DEMAIS = "Os arquivos somam mais de {mb} MB: separe o pacote."
ACHADO_DEMAIS = "O pacote tem {n} páginas, acima do limite de {teto}: separe em dois."


def normalizar(texto: str) -> str:
    """Sem acento, sem caixa e so' letras e numeros: `Engª` -> `enga`, `Eng.` -> `eng`."""
    base = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in base if c.isalnum() and not unicodedata.combining(c)).lower()


def _palavras(nome: str) -> list[str]:
    ps = [normalizar(p) for p in nome.split()]
    return [p for p in ps if p and p not in PREFIXOS]


# --- leitura da pagina ----------------------------------------------------------------------------------------

def _visivel(caixa, giro: int, larg: float, alt: float, ox: float, oy: float) -> tuple[float, float, float, float]:
    """Caixa do caractere (esquerda, baixo, direita, topo) no espaco do usuario -> a mesma na pagina como e' vista,
    com origem no canto inferior esquerdo dela. `larg` x `alt` sao o tamanho SEM giro, `ox, oy` a origem da caixa."""
    l, b, r, t = caixa[0] - ox, caixa[1] - oy, caixa[2] - ox, caixa[3] - oy
    if giro == 90:
        return b, larg - r, t, larg - l
    if giro == 180:
        return larg - r, alt - t, larg - l, alt - b
    if giro == 270:
        return alt - t, l, alt - b, r
    return l, b, r, t


def _sobrepoe(b1: float, t1: float, b2: float, t2: float) -> bool:
    """Os dois trechos de altura se cobrem em pelo menos metade do menor (a letra pequena, como o `ª`, cabe na linha)."""
    return min(t1, t2) - max(b1, b2) >= 0.5 * min(t1 - b1, t2 - b2)


def _linhas(chars: list[tuple[str, float, float, float, float]]) -> list[list[dict]]:
    """Agrupa os caracteres em linhas (pela altura) e cada linha em palavras (pelo vao entre as letras). Cada palavra:
    texto, esquerda, base e topo na pagina como e' vista."""
    linhas: list[list] = []                 # cada uma: [baixo, topo, caracteres]
    for c in chars:                         # na ordem do fluxo do PDF
        for lin in linhas[-3:]:
            if _sobrepoe(c[2], c[4], lin[0], lin[1]):
                lin[0], lin[1] = min(lin[0], c[2]), max(lin[1], c[4])
                lin[2].append(c)
                break
        else:
            linhas.append([c[2], c[4], [c]])
    if len(linhas) <= 400:                  # pagina com milhares de linhas (planilha) nao e' bloco de assinatura
        i = 0                               # colunas lidas em outra ordem: junta as linhas que se sobrepoem
        while i < len(linhas):
            j = i + 1
            while j < len(linhas):
                if _sobrepoe(linhas[i][0], linhas[i][1], linhas[j][0], linhas[j][1]):
                    b = linhas.pop(j)
                    linhas[i][0], linhas[i][1] = min(linhas[i][0], b[0]), max(linhas[i][1], b[1])
                    linhas[i][2].extend(b[2])
                else:
                    j += 1
            i += 1
    linhas = [lin[2] for lin in linhas]
    saida = []
    for lin in linhas:
        lin.sort(key=lambda c: c[1])
        palavras, atual = [], [lin[0]]
        for c in lin[1:]:
            ant = atual[-1]
            # os dois pontos tem caixa curta e o vao antes dele engana: ele sempre cola na palavra anterior
            if c[0] != ":" and c[1] - ant[3] > 0.15 * max(c[4] - c[2], ant[4] - ant[2]):
                palavras.append(atual)
                atual = []
            atual.append(c)
        palavras.append(atual)
        saida.append([{"texto": "".join(c[0] for c in p), "esq": p[0][1], "base": min(c[2] for c in p),
                       "topo": max(c[4] for c in p)} for p in palavras])
    return saida


def _nomes_da_linha(palavras: list[dict], nomes: dict[str, list[str]]) -> list[tuple[str, float, float]]:
    """(papel, esquerda, topo) de cada nome da linha -- ou nada se a linha tem qualquer outra coisa alem de nomes,
    rotulos de uma palavra terminados em `:` e prefixos. Nome no meio de frase ou de tabela nao recebe ancora."""
    uteis = [p for p in palavras if not p["texto"].endswith(":")]
    norm = [normalizar(p["texto"]) for p in uteis]
    ordem = sorted(nomes.items(), key=lambda kv: -len(kv[1]))
    achados, i = [], 0
    while i < len(uteis):
        if norm[i] == "" or norm[i] in PREFIXOS:
            i += 1
            continue
        for papel, ps in ordem:
            if norm[i:i + len(ps)] == ps:
                topo = max(p["topo"] for p in uteis[i:i + len(ps)])
                # a mesma pessoa em dois papeis (fiscal e superior) leva as duas ancoras
                achados += [(outro, uteis[i]["esq"], topo) for outro, qs in ordem if qs == ps]
                i += len(ps)
                break
        else:
            return []
    return achados


class Pagina:
    """Uma pagina do pacote juntado: tamanho como e' vista, a ancora que a leitura achou e por que."""
    def __init__(self, numero: int, largura: float, altura: float):
        self.numero = numero
        self.largura = largura
        self.altura = altura
        self.motivo: str | None = None                   # "nome", "diario", "rodape" ou None (sem ancora)
        self.ancoras: list[tuple[str, float, float]] = []   # (papel, x, base) na pagina como e' vista

    def papeis(self) -> list[str]:
        return [a[0] for a in self.ancoras]


def _rodape(pg: Pagina) -> list[tuple[str, float, float]]:
    return [(papel, max(0.0, min(x, pg.largura - 60.0)), BASELINE_RODAPE_PT) for papel, x in RODAPE.items()]


def ler_paginas(pdf: bytes, papeis: dict[str, str]) -> list[Pagina]:
    """Le o texto posicionado de cada pagina e decide as ancoras automaticas (nome e Diario). `papeis`: papel -> nome."""
    nomes = {papel: _palavras(nome) for papel, nome in papeis.items() if _palavras(nome)}
    doc = pdfium.PdfDocument(pdf)
    leitor = pypdf.PdfReader(io.BytesIO(pdf))
    paginas = []
    try:
        for i in range(len(doc)):
            pp = leitor.pages[i]
            caixa = pp.cropbox
            larg, alt = float(caixa.width), float(caixa.height)
            giro = int(pp.get("/Rotate", 0) or 0) % 360
            visiv = (alt, larg) if giro in (90, 270) else (larg, alt)
            pg = Pagina(i + 1, *visiv)
            pagina = doc[i]
            tp = pagina.get_textpage()
            try:
                texto = tp.get_text_range()
                chars = []
                for k, ch in enumerate(texto):
                    if ch.isspace() or not ch.isprintable():
                        continue
                    l, b, r, t = _visivel(tp.get_charbox(k, loose=True), giro, larg, alt, float(caixa.left), float(caixa.bottom))
                    if r > l and t > b:
                        chars.append((ch, l, b, r, t))
            finally:
                tp.close()
                pagina.close()
            linhas = _linhas(chars) if chars else []
            diario = any(normalizar(" ".join(p["texto"] for p in lin)) == normalizar(TITULO_DIARIO)
                         and max(p["topo"] for p in lin) >= FRACAO_ALTO * pg.altura for lin in linhas)
            if diario:
                pg.motivo = "diario"
                pg.ancoras = _rodape(pg)
            elif nomes:
                for lin in linhas:
                    for papel, esq, topo in _nomes_da_linha(lin, nomes):
                        base = min(topo + SOBE_PT - TAMANHO_PT * ASCENDENTE, pg.altura - TAMANHO_PT)
                        pg.ancoras.append((papel, max(0.0, esq - RECUO_X_PT), base))
                if pg.ancoras:
                    pg.motivo = "nome"
            paginas.append(pg)
    finally:
        doc.close()
    return paginas


def aplicar_marcacoes(paginas: list[Pagina], marcar: set[int], desmarcar: set[int]) -> None:
    """`desmarcar`: paginas que ficam sem ancora (valem sobre as automaticas); `marcar`: paginas sem ancora que
    recebem o rodape."""
    for pg in paginas:
        if pg.numero in desmarcar:
            pg.motivo, pg.ancoras = None, []
        elif pg.numero in marcar and pg.motivo is None:
            pg.motivo, pg.ancoras = "rodape", _rodape(pg)


# --- sobreposicao ---------------------------------------------------------------------------------------------

def _sobreposicao(paginas: list[Pagina], mostrar: bool) -> pypdf.PdfReader:
    """Um PDF so' com as ancoras: uma pagina do tamanho de cada pagina ancorada, texto Helvetica 5 pt. Sem `mostrar`
    o texto e' invisivel (modo de renderizacao 3: o DocuSign o le e a impressao nao o mostra); com `mostrar`, vermelho."""
    pdf = FPDF(unit="pt")
    pdf.set_auto_page_break(False)
    pdf.set_font("Helvetica", size=TAMANHO_PT)
    pdf.text_mode = TextMode.FILL if mostrar else TextMode.INVISIBLE
    if mostrar:
        pdf.set_text_color(255, 0, 0)
    for pg in paginas:
        pdf.add_page(format=(pg.largura, pg.altura))
        for papel, x, base in pg.ancoras:
            pdf.text(x, pg.altura - base, PAPEIS[papel][1])
    return pypdf.PdfReader(io.BytesIO(bytes(pdf.output())))


def carimbar(pdf: bytes, paginas: list[Pagina], mostrar: bool) -> bytes:
    """O PDF juntado com as ancoras. So' as paginas ancoradas sao tocadas; a de `/Rotate` passa por
    `transfer_rotation_to_content` antes, para a ancora sair em pe."""
    ancoradas = [pg for pg in paginas if pg.ancoras]
    escritor = pypdf.PdfWriter(clone_from=leitura_pdf.leitor_de_pdf(pdf, pacote=True))
    sobre = _sobreposicao(ancoradas, mostrar)
    for pg, camada in zip(ancoradas, sobre.pages):
        destino = escritor.pages[pg.numero - 1]
        if int(destino.get("/Rotate", 0) or 0) % 360:
            destino.transfer_rotation_to_content()
        caixa = destino.cropbox
        destino.merge_transformed_page(camada, Transformation().translate(float(caixa.left), float(caixa.bottom)))
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()


# --- entrada (roda no subprocesso) ---------------------------------------------------------------------------

def processar(opcoes: dict) -> dict:
    """Junta, le e (se `gerar`) carimba. `opcoes`: partes, papeis (papel -> nome), marcar, desmarcar, mostrar, gerar.
    Devolve `{"pdf": bytes | None, "paginas": [...]}`; `paginas` traz TODAS, com `motivo` e `papeis` ja' com as
    marcacoes da pessoa aplicadas."""
    juntado, n = leitura_pdf._juntar(opcoes["partes"])
    if n > TETO_PAGINAS:
        raise leitura_pdf.TextoInadequado(ACHADO_DEMAIS.format(n=n, teto=TETO_PAGINAS))
    paginas = ler_paginas(juntado, opcoes["papeis"])
    aplicar_marcacoes(paginas, set(opcoes["marcar"]), set(opcoes["desmarcar"]))
    pdf = carimbar(juntado, paginas, opcoes["mostrar"]) if opcoes["gerar"] else None
    return {"pdf": pdf, "paginas": [{"pagina": pg.numero, "motivo": pg.motivo, "papeis": pg.papeis()}
                                    for pg in paginas]}


def com_limite(partes: list[bytes], papeis: dict[str, str], marcar=(), desmarcar=(), mostrar=False,
               gerar=True) -> dict:
    """`processar` no subprocesso com limite de tempo e a guarda de streams de `leitura_pdf` (PDF vem de fora)."""
    if sum(len(p) for p in partes) > pdfs.TETO_BYTES_PACOTE:
        raise leitura_pdf.TextoInadequado(SOMA_DEMAIS.format(mb=pdfs.TETO_BYTES_PACOTE // (1024 * 1024)))
    return leitura_pdf.com_limite(b"", "ancoras", TEMPO_LIMITE_S, {
        "partes": list(partes), "papeis": papeis, "marcar": sorted(marcar), "desmarcar": sorted(desmarcar),
        "mostrar": mostrar, "gerar": gerar}, vagas=_VAGA)
