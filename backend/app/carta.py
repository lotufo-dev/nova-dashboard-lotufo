"""Carta, capa e divisoria em PDF (bloco 5; reusado pelos oficios do bloco 7).

Nao existe modelo Word de carta de protocolo (levantamento de 2026-09-24) nem conversao Word->PDF no
servidor: a carta e' desenhada aqui (fpdf2). O texto fixo vem do cadastro (`cadastro/cartas.yaml`,
aplicado em `cadastro_geral['cartas']`); o timbre e' imagem recortada de carta real, copiada para a
pasta de dados pelo `cadastro aplicar`.

O CORPO e' texto simples com tres marcas, e e' o que a pessoa edita na previa: linha em branco separa
paragrafos; linha comecando por "# " e' titulo de secao (negrito); linha comecando por "i. ", "ii. ",
"1. " etc. e' item de lista (recuado).

A curva S que vai com a carta de prazo (issue #293) e' uma planilha (openpyxl), desenhada aqui tambem.
"""
import datetime
import io
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from decimal import Decimal
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from fpdf import FPDF
from PIL import Image
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.writer.excel import ExcelWriter

from app import arquivos

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro")
# Fonte Unicode das cartas, oficios e FRC (issue #385), em ordem: a primeira com o regular e o negrito vale.
# A producao (Windows) acha a Arial primeiro e o PDF dela nao muda; o Mac tem a Arial do sistema; o Linux da
# CI usa a Liberation Sans (pacote fonts-liberation, mesmas metricas da Arial). DASH_FONTE_CARTA e
# DASH_FONTE_CARTA_NEGRITO, juntas, apontam outro par de TTF e vem antes da lista. Sem nenhuma, Helvetica.
_FONTES = (
    (Path(r"C:\Windows\Fonts\arial.ttf"), Path(r"C:\Windows\Fonts\arialbd.ttf")),
    (Path("/System/Library/Fonts/Supplemental/Arial.ttf"), Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")),
    (Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
     Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")),
)
_ITEM = re.compile(r"^((?:[ivxlc]+|\d{1,2}))\.\s+(.*)$", re.IGNORECASE)
_TROCAS_LATIN1 = {"–": "-", "—": "-", "“": '"', "”": '"', "‘": "'", "’": "'", "…": "..."}
ALTURA = 5.5


def fonte_carta() -> tuple[Path, Path] | None:
    """O par (regular, negrito) da fonte Unicode, ou None para o plano B Helvetica/latin-1."""
    candidatas = list(_FONTES)
    regular, negrito = os.environ.get("DASH_FONTE_CARTA"), os.environ.get("DASH_FONTE_CARTA_NEGRITO")
    if regular and negrito:
        candidatas.insert(0, (Path(regular), Path(negrito)))
    for par in candidatas:
        if par[0].is_file() and par[1].is_file():
            return par
    return None


def data_extenso(d: datetime.date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


_UNIDADES = ("", "primeira", "segunda", "terceira", "quarta", "quinta", "sexta", "sétima", "oitava", "nona")
_DEZENAS = ("", "décima", "vigésima", "trigésima", "quadragésima", "quinquagésima", "sexagésima",
            "septuagésima", "octogésima", "nonagésima")


_EXECUCAO = re.compile(r"^\s*execu[çc][ãa]o\s+", re.IGNORECASE)


def objeto_do_contrato(c: dict) -> str | None:
    """O objeto que as cartas escrevem: `objeto_carta` (o texto das cartas reais) antes do do QDOP."""
    return c.get("objeto_carta") or c.get("objeto_completo") or c.get("objeto")


def objeto_na_frase(objeto: str | None) -> str:
    """O objeto por extenso (QDOP: "EXECUÇÃO DO REMANESCENTE DA OBRA ...") entra nas cartas depois de "empresa
    responsável pela execução": sem o "EXECUÇÃO" inicial a frase nao repete a palavra."""
    return _EXECUCAO.sub("", objeto or "").strip()


def ordinal_extenso(n: int) -> str:
    """Ordinal feminino por extenso, 1 a 199 ("27" -> "vigésima sétima"), como na carta de reajuste SINFRA."""
    if not 1 <= n <= 199:
        return f"{n}ª"
    partes = ["centésima"] if n >= 100 else []
    partes += [_DEZENAS[n % 100 // 10], _UNIDADES[n % 10]]
    return " ".join(p for p in partes if p)


class _Campos(dict):
    def __missing__(self, chave):           # campo que o dado nao tem fica visivel, nao quebra
        return "{" + chave + "}"


def preencher(modelo: str, campos: dict) -> str:
    return modelo.format_map(_Campos(campos))


@dataclass
class Carta:
    numero: str
    local_data: str
    destinatario: list[str]
    ac: list[str]
    referencia: str
    assunto: str
    vocativo: str
    corpo: str
    assinatura: list[str]
    emitente: dict = field(default_factory=dict)   # razao_social, cnpj, endereco, ie, contato, logo, fundo, rodape,
                                                   # logo_largura_mm


CINZA = (204, 204, 204)
LOGO_LARGURA_MM = 58          # largura padrao do logo no topo (papel da Lotufo)
LOGO_ALTURA_MAX_MM = 50       # teto da altura do logo: o corpo e o titulo da capa (120 mm) ficam abaixo dele


def _arquivo_de_dados(rel: str | None) -> Path | None:
    if not rel:
        return None
    try:
        p = arquivos.caminho_seguro(rel)
    except (ValueError, RuntimeError):
        return None
    return p if p.is_file() else None


def textos_do_timbre(emitente: dict | None) -> list[str]:
    """O texto que o papel timbrado (`_Doc.header` e `_Doc.footer`) repete em toda pagina: a conferencia do assinado
    o tira antes de juntar as paginas (`protocolo._plano_sem_timbre`)."""
    e = emitente or {}
    cnpj = f"CNPJ {e['cnpj']}" if e.get("cnpj") else None
    return [x for x in (e.get("razao_social"), " | ".join(x for x in (e.get("endereco"), cnpj) if x), e.get("endereco"),
                        "     ".join(x for x in (f"CNPJ: {e['cnpj']}" if e.get("cnpj") else None,
                                                 f"Inscrição Estadual: {e['ie']}" if e.get("ie") else None) if x),
                        e.get("contato")) if x]


class _Doc(FPDF):
    """Papel timbrado da carta real (CT-301, MTPAR, 16/09/2026): logo centralizado no topo, um "L" cinza
    ocupando a margem esquerda e a base, e os dados da empresa no rodape, sobre a faixa cinza. Sem logo
    no cadastro, cabecalho de texto (razao social, endereco, CNPJ).

    Os consorcios (#46, issue #566) tem papel proprio: `rodape: true` poe os dados da empresa no pe da pagina sem o
    "L" (que so' vem com `fundo: true`, e o `fundo` ja' traz o rodape); `logo_largura_mm` muda a largura do logo."""

    def __init__(self, emitente: dict | None):
        super().__init__(format="A4")
        self.emitente = emitente or {}
        self.logo = _arquivo_de_dados(self.emitente.get("logo"))
        self.fundo = bool(self.emitente.get("fundo")) and self.logo is not None
        # sem logo, o cabecalho de texto ja' traz razao social, endereco e CNPJ: o rodape so' vem com o logo
        self.rodape = self.fundo or (bool(self.emitente.get("rodape")) and self.logo is not None)
        self.logo_largura = self._largura_do_logo()
        if self.fundo:
            self.set_margins(33, 20, 20)
            self.set_auto_page_break(True, margin=42)
        else:
            self.set_margins(25, 20, 20)
            self.set_auto_page_break(True, margin=28 if self.rodape else 22)     # o rodape comeca em 272 mm
        fonte = fonte_carta()
        if fonte:
            self.add_font("Carta", "", str(fonte[0]))
            self.add_font("Carta", "B", str(fonte[1]))
            self.fonte, self.unicode = "Carta", True
        else:
            self.fonte, self.unicode = "Helvetica", False

    def _largura_do_logo(self) -> float:
        """A largura do cadastro (padrao 58 mm), reduzida se o logo passaria de LOGO_ALTURA_MAX_MM de altura:
        logo alto demais empurraria o corpo para fora da pagina e cobriria o titulo da capa."""
        largura = float(self.emitente.get("logo_largura_mm") or LOGO_LARGURA_MM)
        if self.logo is None:
            return largura
        try:
            with Image.open(self.logo) as im:
                px_l, px_a = im.size
        except (OSError, ValueError):
            return largura
        if px_l and px_a and largura * px_a / px_l > LOGO_ALTURA_MAX_MM:
            largura = LOGO_ALTURA_MAX_MM * px_l / px_a
        return largura

    def t(self, s: str) -> str:
        if self.unicode:
            return s
        for de, para in _TROCAS_LATIN1.items():
            s = s.replace(de, para)
        return s.encode("latin-1", "replace").decode("latin-1")

    def _l_cinza(self):
        """O "L" do timbre: barra a esquerda, faixa na base e a curva entre as duas."""
        # Medidas tiradas do CT-301 desenhado: barra ate' 30 mm, faixa a partir de 262 mm, e a curva
        # interna indo de (30, 160) a (150, 262) -- um quarto de elipse de raios 120 x 102 mm.
        self.set_fill_color(*CINZA)
        self.rect(0, 0, 30, 262, style="F")
        self.rect(0, 262, 210, 35, style="F")
        self.rect(30, 160, 120, 102, style="F")
        self.set_fill_color(255, 255, 255)
        self.ellipse(30, 58, 240, 204, style="F")         # centro (150, 160), raios 120 x 102

    def header(self):
        if self.fundo:
            self._l_cinza()
        if self.logo is not None:
            info = self.image(str(self.logo), x=(210 - self.logo_largura) / 2, y=6, w=self.logo_largura)
            y = 34                                              # papel da Lotufo (58 mm): o corpo comeca em 34 mm
            if self.emitente.get("logo_largura_mm"):           # largura do cadastro: o corpo comeca abaixo do logo
                y = max(y, 6 + info.rendered_height + 4)
            self.set_y(y)
            return
        if self.emitente.get("razao_social"):
            self.set_font(self.fonte, "B", 11)
            self.cell(0, 5, self.t(self.emitente["razao_social"]), new_x="LMARGIN", new_y="NEXT", align="C")
            partes = [self.emitente.get("endereco"),
                      f"CNPJ {self.emitente['cnpj']}" if self.emitente.get("cnpj") else None]
            linha = " | ".join(x for x in partes if x)
            if linha:
                self.set_font(self.fonte, "", 8)
                self.cell(0, 4, self.t(linha), new_x="LMARGIN", new_y="NEXT", align="C")
            self.ln(6)

    def footer(self):
        if not self.rodape:
            return
        e = self.emitente
        x = 8 if self.fundo else self.l_margin            # sem o "L", alinhado com o corpo
        self.set_xy(x, 272)
        self.set_font(self.fonte, "B", 8)
        self.cell(0, 3.6, self.t(e.get("razao_social") or ""), new_x="LMARGIN", new_y="NEXT")
        self.set_font(self.fonte, "", 7.5)
        linhas = [e.get("endereco"),
                  "     ".join(x for x in (f"CNPJ: {e['cnpj']}" if e.get("cnpj") else None,
                                           f"Inscrição Estadual: {e['ie']}" if e.get("ie") else None) if x),
                  e.get("contato")]
        for l in linhas:
            if l:
                self.set_x(x)
                self.cell(0, 3.4, self.t(l), new_x="LMARGIN", new_y="NEXT")

    def linha(self, texto: str, estilo: str = "", align: str = "L"):
        self.set_font(self.fonte, estilo, 11)
        self.multi_cell(0, ALTURA, self.t(texto), align=align, new_x="LMARGIN", new_y="NEXT")


def _corpo(pdf: _Doc, corpo: str) -> None:
    for bloco in re.split(r"\n\s*\n", (corpo or "").strip()):
        for bruta in bloco.splitlines():
            linha = bruta.strip()
            if not linha:
                continue
            if linha.startswith("# "):
                pdf.ln(2)
                pdf.linha(linha[2:].strip(), "B")
            elif (m := _ITEM.match(linha)):
                pdf.set_x(pdf.l_margin + 8)
                pdf.set_font(pdf.fonte, "", 11)
                pdf.multi_cell(0, ALTURA, pdf.t(f"{m.group(1)}. {m.group(2)}"), new_x="LMARGIN", new_y="NEXT")
            elif bruta.startswith("   "):       # sub-item (SES: "Sendo: 41ª Medição – R$ ...")
                pdf.set_x(pdf.l_margin + 14)
                pdf.set_font(pdf.fonte, "", 11)
                pdf.multi_cell(0, ALTURA, pdf.t(linha), new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.linha(linha, align="J")
        pdf.ln(3)


def gerar(c: Carta) -> bytes:
    pdf = _Doc(c.emitente)
    pdf.add_page()
    pdf.linha(c.numero)
    pdf.linha(c.local_data, align="R")
    pdf.ln(5)
    for l in c.destinatario:
        pdf.linha(l)
    for l in c.ac:
        pdf.linha(l)
    pdf.ln(3)
    pdf.linha(c.referencia, "U")
    pdf.linha(c.assunto, "U")
    pdf.ln(6)
    pdf.set_x(pdf.l_margin + 25)
    pdf.linha(c.vocativo)
    pdf.ln(2)
    _corpo(pdf, c.corpo)
    pdf.ln(12)
    pdf.set_font(pdf.fonte, "", 11)
    pdf.cell(0, ALTURA, "_" * 38, new_x="LMARGIN", new_y="NEXT")     # linha para a assinatura do DocuSign
    for l in c.assinatura:
        pdf.cell(0, ALTURA, pdf.t(l), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


# --- dados do cadastro para a carta ------------------------------------------------------------------

def config(conn) -> dict:
    r = conn.execute("SELECT valor FROM cadastro_geral WHERE chave='cartas'").fetchone()
    if r is None:
        raise ValueError("Textos das cartas não carregados: rode `cadastro aplicar` com cadastro/cartas.yaml")
    return json.loads(r["valor"])


def _cnpj(c: str) -> str:
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}" if c and len(c) == 14 else (c or "")


def emitente(conn, entidade_id: int) -> dict:
    """Quem assina a carta: o que o cadastro das cartas diz da entidade, ou o nome e o CNPJ dela."""
    e = conn.execute("SELECT * FROM entidades WHERE id=?", (entidade_id,)).fetchone()
    if e is None:
        return {}
    try:
        cfg = config(conn).get("emitentes", {})
    except ValueError:
        cfg = {}
    base = {"razao_social": (e["nome"] or "").upper(), "cnpj": _cnpj(e["cnpj"]), "endereco": None,
            "logo": None, "sigla": e["sigla_oficio"]}
    return {**base, **(cfg.get(e["chave"]) or {})} if e["chave"] else base


def fiscal_vigente(conn, contrato_id: int, na_data: str) -> dict | None:
    r = conn.execute("SELECT * FROM contrato_fiscais WHERE contrato_id=? AND desde<=? "
                     "ORDER BY desde DESC, id DESC LIMIT 1", (contrato_id, na_data)).fetchone()
    return dict(r) if r else None


def pagina_titulo(linhas: list[str], emitente: dict | None = None) -> bytes:
    """Capa ou divisoria (SES): linhas em negrito, centralizadas no meio da pagina."""
    pdf = _Doc(emitente)
    pdf.add_page()
    pdf.set_y(120)
    for l in linhas:
        pdf.set_font(pdf.fonte, "B", 20)
        pdf.multi_cell(0, 11, pdf.t(l), align="C", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


# --- curva S da carta de prazo (issue #293; spec 2026-10-20 §4 item 3, D9) -------------------------

NOME_CURVA_S = "Curva S.xlsx"
COLUNAS_CURVA_S = ("Competência", "Previsto vigente", "Previsto anterior", "Medido")
_CHAVES_CURVA_S = ("previsto_vigente_centavos", "previsto_anterior_centavos", "medido_centavos")
_SEM_RELOGIO = datetime.datetime(1980, 1, 1)        # a menor data que o zip aceita


def _reais(centavos: int | None) -> float | None:
    """Centavo inteiro -> real na celula, como a planilha do QDOP (`qdop.gerar_xlsx`). None fica celula vazia."""
    return None if centavos is None else centavos / 100


def curva_s_xlsx(linhas: list[dict]) -> bytes:
    """A planilha da curva S, uma linha por competencia, os valores acumulados como a tela da obra os desenha
    (`paineis.curva_s`). A primeira linha e' o cabecalho; competencia como data (mes/ano) e valores em reais.

    Deterministica (rodada 2 da PR #436): as mesmas linhas dao os mesmos bytes, sem relogio nas propriedades nem
    nas datas do zip. Assim o sha256 do arquivo e' a impressao da curva, e a previa e o envio conferem se a curva
    anexada ainda e' a dos dados de agora."""
    wb = Workbook()
    wb.properties.created = wb.properties.modified = _SEM_RELOGIO
    ws = wb.active
    ws.title = "Curva S"
    ws.append(COLUNAS_CURVA_S)
    for cel in ws[1]:
        cel.font = Font(bold=True)
    for linha in linhas:
        comp = linha["competencia"]
        ws.append([datetime.date(int(comp[:4]), int(comp[5:7]), 1), *(_reais(linha[k]) for k in _CHAVES_CURVA_S)])
    for cels in ws.iter_rows(min_row=2):
        cels[0].number_format = "mm/yyyy"
        for cel in cels[1:]:
            cel.number_format = "#,##0.00"
    ws.column_dimensions["A"].width = 13
    for col in "BCD":
        ws.column_dimensions[col].width = 20
    ws.freeze_panes = "A2"
    bruto = io.BytesIO()
    ExcelWriter(wb, ZipFile(bruto, "w", ZIP_DEFLATED)).save()    # sem o `save_workbook`, que grava a hora no arquivo
    saida = io.BytesIO()
    with ZipFile(bruto) as origem, ZipFile(saida, "w", ZIP_DEFLATED) as destino:
        for parte in origem.infolist():          # a data de cada parte do zip tambem sai fixa
            destino.writestr(ZipInfo(parte.filename, date_time=_SEM_RELOGIO.timetuple()[:6]),
                             origem.read(parte.filename), compress_type=ZIP_DEFLATED)
    return saida.getvalue()


# Teto dos acumulados da curva (R$ 10 trilhoes): ate' 15 algarismos, o real da celula (float) volta pelo `repr`
# exatamente ao decimal de 2 casas (DBL_DIG = 15), entao o centavo lido e' o gravado, sem arredondar.
TETO_CURVA_S_CENTAVOS = 10 ** 15


def _centavos(valor) -> int | None:
    """Real da celula -> centavo inteiro (o inverso de `_reais`), exato: pelo `repr` em Decimal, sem a multiplicacao
    de float (gate Sol na PR #455). Celula vazia fica None; fracao de centavo ou acima do teto, ValueError."""
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ValueError("valor da curva S não numérico")
    c = Decimal(repr(valor)) * 100
    if c != c.to_integral_value() or abs(c) >= TETO_CURVA_S_CENTAVOS:
        raise ValueError("valor da curva S fora do centavo exato")
    return int(c)


def conteudo_curva_s(linhas: list[dict]) -> list[tuple]:
    """Issue #447: a curva como dado, uma tupla por competencia ("AAAA-MM" e os tres acumulados em centavos inteiros).
    E' isto que a previa e o envio comparam, nao os bytes do xlsx: o zip muda com o sistema e as versoes do openpyxl,
    lxml e zlib sem o dado mudar."""
    return [(x["competencia"][:7], *(x[k] for k in _CHAVES_CURVA_S)) for x in linhas]


def ler_curva_s(dados: bytes) -> list[tuple]:
    """O conteudo (`conteudo_curva_s`) de um xlsx gerado por `curva_s_xlsx`. ValueError se nao for uma curva S."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(dados), read_only=True, data_only=True)
        try:
            linhas = list(wb.active.iter_rows(values_only=True))
        finally:
            wb.close()                              # read_only segura o zip aberto ate' o close
    except Exception as e:                          # zip truncado, xml quebrado: nao e' a curva gerada
        raise ValueError("arquivo da curva S ilegível") from e
    if not linhas or tuple(linhas[0][:4]) != COLUNAS_CURVA_S:
        raise ValueError("arquivo da curva S sem o cabeçalho esperado")
    out = []
    for linha in linhas[1:]:
        comp, *valores = (tuple(linha) + (None,) * 4)[:4]
        if not isinstance(comp, (datetime.date, datetime.datetime)):
            raise ValueError("competência da curva S não é data")
        out.append((f"{comp.year:04d}-{comp.month:02d}", *(_centavos(v) for v in valores)))
    return out
