"""Leitura do medido por grupo da planilha de medicao (issue #490).

A planilha padrao SINFRA tem uma aba de resumo ("Resumo" ou "Resumo Medição") com o cabecalho numa linha:
ITEM | BOLETIM | CÓDIGO | DISCRIMINAÇÃO | UNID. | QUANT. | NESTA MEDIÇÃO | MEDIDO ACUMULADO ANTERIOR | MEDIDO ACUMULADO |
PREÇO UNITÁRIO R$ | VALOR CONTRATO R$ | NESTA MEDIÇÃO R$ | VALOR ACUMULADO ANTERIOR R$ | VALOR ACUMULADO R$ | ...
A posicao das colunas e' achada pelo texto do cabecalho (quantidade e valor se distinguem pelo "R$"). Depois dele:
- linha de grupo: o nº do item ("1", "3.1") e o titulo, sem codigo e sem unidade;
- linha de item: o nº ("1.1", "3.1.2"), o codigo do servico e/ou a unidade, as quantidades, o preco e os valores;
- SUBTOTAL de cada grupo (pulado) e TOTAL GERAL no fim (a leitura para).

Outro modelo (issue #612) nao tem a coluna ITEM, so' o CÓDIGO do servico (que se repete: "s/c"). Nele, o titulo de
grupo ou de subgrupo e' a linha so' com a discriminacao (sem codigo, sem unidade e sem preco), o item cai no titulo
mais recente, o campo `item` vem vazio, e a leitura para tambem em TOTAL ACUMULADO ou TOTAL DESTA MEDIÇÃO (o rodape
desse modelo). Sem nº de item, os prefixos de nº do cadastro de custo nao se aplicam: o titulo do item (o mais
recente) e' procurado nos `titulos_planilha` do cadastro (issue #613; fora deles, "outros"); cadastro sem nenhum
titulo agrupa pelos titulos da propria planilha.

O grupo do item vem do cadastro de custo da obra quando houver (prefixos de `itens_planilha`, issue #489); sem ele,
do titulo de grupo mais proximo da propria planilha (o de nº mais longo que prefixa o nº do item). Item que nao cai
em grupo nenhum vai para "outros".

Deterministico (leitura direta do XML do .xlsx, sem custo de API), com teto no que se descompacta. O que nao
casa com o modelo levanta `PlanilhaRecusada` com o que faltou. Nada aqui grava: quem grava e' `medicao_grupos`.
"""
import io
import posixpath
import unicodedata
import zipfile
from decimal import Decimal, InvalidOperation

from defusedxml import ElementTree       # XML de fora: sem entidade expandida

from app import dinheiro, rm

ABAS = ("RESUMO", "RESUMO MEDICAO")     # na ordem de preferencia, comparadas sem acento e em maiusculas
OUTROS = "outros"
TOLERANCIA_CENTAVOS = 100               # um real entre a soma dos grupos e o valor pedido
LINHAS_CABECALHO = 40
MAX_LINHAS = 5000                       # a aba real tem ~1.500 linhas
MAX_COLUNAS = 60
MAX_ITENS = 3000
FIM_SEM_ITEM = ("TOTAL ACUMULADO", "TOTAL DESTA MEDICAO")   # o rodape do modelo sem ITEM, alem do TOTAL GERAL

# campo -> como aparece na mensagem quando falta
CAMPOS = {
    "item": "ITEM", "codigo": "CÓDIGO", "descricao": "DISCRIMINAÇÃO", "unidade": "UNID.",
    "quantidade_contratada": "QUANT.", "quantidade_medida": "NESTA MEDIÇÃO (quantidade)",
    "quantidade_acumulada": "MEDIDO ACUMULADO", "preco": "PREÇO UNITÁRIO R$",
    "valor_medido": "NESTA MEDIÇÃO R$", "valor_acumulado": "VALOR ACUMULADO R$",
}


class PlanilhaRecusada(ValueError):
    """A planilha nao casa com o modelo, ou a soma nao bate. `str()` diz o que faltou ou a diferenca."""


def _texto(v) -> str:
    """Comparavel: sem acento, maiusculo, quebras de linha e espacos repetidos viram um espaco."""
    if not isinstance(v, str):
        return ""
    s = unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


# o titulo lido contra o `titulos_planilha` do cadastro de custo (issue #613): a mesma comparacao do cabecalho
titulo_comparavel = _texto


def _e_item(h: str) -> bool:
    """A coluna do nº do item: "ITEM", ou ate' duas palavras terminando em ITEM ("Nº ITEM" -> "NO ITEM", "N. ITEM")."""
    partes = h.split()
    return bool(partes) and partes[-1] == "ITEM" and len(partes) <= 2


def _menciona_item(textos: list[str]) -> bool:
    """Alguma celula fala de ITEM (mesmo que nao seja reconhecida): nao e' o modelo sem ITEM."""
    return any("ITEM" in t.split() for t in textos)


def _campo(h: str) -> str | None:
    """O campo de uma celula do cabecalho (ja' normalizada), ou None (coluna que a leitura nao usa)."""
    if not h:
        return None
    if _e_item(h):
        return "item"
    if h.startswith("CODIGO"):
        return "codigo"
    if h.startswith("DISCRIMINACAO") or h.startswith("DESCRICAO"):
        return "descricao"
    if h.startswith("UNID"):
        return "unidade"
    if "PRECO UNITARIO" in h:
        return "preco"
    if "ANTERIOR" in h or "PERCENTUAL" in h or "%" in h:
        return None
    if "R$" in h or h.startswith("VALOR"):
        if "CONTRAT" in h:              # o valor contratado nao entra
            return None
        if "NESTA" in h:
            return "valor_medido"
        if "ACUMULAD" in h:
            return "valor_acumulado"
        return None
    if "NESTA" in h:
        return "quantidade_medida"
    if "ACUMULAD" in h:
        return "quantidade_acumulada"
    if h.startswith("QUANT") or "CONTRAT" in h:
        return "quantidade_contratada"
    return None


def _e_cabecalho(valores: list) -> bool:
    """A linha do cabecalho tem ITEM (ou CÓDIGO, no modelo sem ITEM) e DISCRIMINAÇÃO (ou DESCRIÇÃO)."""
    textos = [_texto(v) for v in valores]
    return ((any(_e_item(t) for t in textos) or any(t.startswith("CODIGO") for t in textos))
            and any(t.startswith(("DISCRIMINACAO", "DESCRICAO")) for t in textos))


def _colunas(textos: list[str]) -> tuple[dict[str, int], list[str]]:
    """(campo -> coluna, rotulos das colunas que faltam). Com CÓDIGO e sem celula nenhuma falando de ITEM, ITEM nao
    e' exigido (modelo sem ITEM); a coluna de ITEM escrita de um jeito que nao se reconhece continua recusando."""
    colunas: dict[str, int] = {}
    for c, t in enumerate(textos):
        campo = _campo(t)
        if campo and campo not in colunas:
            colunas[campo] = c
    sem_item = "codigo" in colunas and not _menciona_item(textos)
    return colunas, [CAMPOS[k] for k in CAMPOS if k not in colunas and not (k == "item" and sem_item)]


def _combinar(pai: list, filho: list) -> list[str]:
    """Cabecalho em duas linhas (celula mesclada em cima, sub-colunas embaixo): o texto de cada coluna e' o do pai
    que a cobre mais o do filho ("NESTA MEDIÇÃO" sobre "QUANT." e "R$"). O pai mesclado na horizontal vale para as
    colunas seguintes que tem filho; o pai sem filho embaixo (mesclado na vertical, como ITEM) vale so' para si."""
    saida, cobre = [], ""
    for c in range(max(len(pai), len(filho))):
        p = _texto(pai[c]) if c < len(pai) else ""
        f = _texto(filho[c]) if c < len(filho) else ""
        if p:
            cobre = p if f else ""
            saida.append(f"{p} {f}".strip())
        elif f:
            saida.append(f"{cobre} {f}".strip())
        else:
            cobre = ""
            saida.append("")
    return saida


def _so_texto(valores: list) -> bool:
    """Linha que pode continuar o cabecalho: tem texto e nenhum numero."""
    return any(_texto(v) for v in valores) and not any(
        isinstance(v, int | float | Decimal) and not isinstance(v, bool) for v in valores)


def _achar_cabecalho(linhas) -> tuple[dict[str, int], object]:
    """(campo -> coluna, as linhas que sobram). O cabecalho e' a linha com ITEM (ou CÓDIGO, no modelo sem ITEM) e
    DISCRIMINAÇÃO; se na linha com ITEM faltam colunas, junta a linha de cima ou a de baixo (cabecalho em duas
    linhas). A linha so' com CÓDIGO (modelo sem ITEM, cabecalho numa linha) tem de vir completa; incompleta, pode
    ser um dado acima da tabela ("CÓDIGO DA OBRA"): a busca segue e so' recusa, com o que faltou, se nenhuma servir."""
    anterior, pendente = None, None
    for numero, valores in linhas:
        if numero > LINHAS_CABECALHO:
            break
        if not _e_cabecalho(valores):
            anterior = valores
            continue
        col, faltam = _colunas([_texto(v) for v in valores])
        if not faltam:
            return col, linhas
        if not any(_e_item(_texto(v)) for v in valores):
            if pendente is None or len(faltam) < len(pendente):
                pendente = faltam       # a linha mais perto de ser o cabecalho diz o que falta
            anterior = valores
            continue
        if anterior is not None and _so_texto(anterior):
            col2, faltam2 = _colunas(_combinar(anterior, valores))
            if not faltam2:
                return col2, linhas
        seguinte = next(linhas, None)
        if seguinte is not None and _so_texto(seguinte[1]):
            col2, faltam2 = _colunas(_combinar(valores, seguinte[1]))
            if not faltam2:
                return col2, linhas
            faltam = faltam2 if len(faltam2) < len(faltam) else faltam
        raise PlanilhaRecusada(f"o cabeçalho da aba Resumo não tem a coluna {', '.join(faltam)}")
    if pendente:
        raise PlanilhaRecusada(f"o cabeçalho da aba Resumo não tem a coluna {', '.join(pendente)}")
    raise PlanilhaRecusada("a aba Resumo não tem o cabeçalho com ITEM (ou CÓDIGO) e DISCRIMINAÇÃO")


def _nome_item(v) -> str:
    """Nº do item ou codigo como texto: 1 -> "1", 4011.0 -> "4011", "1.1 " -> "1.1"."""
    if v is None or isinstance(v, bool):
        return ""
    if isinstance(v, float | Decimal) and v == int(v):
        return str(int(v))
    return str(v).strip()


def _decimal(v, rotulo: str, item: str) -> Decimal | None:
    if v is None or (isinstance(v, str) and v.strip() in ("", "-")):
        return None
    if isinstance(v, bool) or not isinstance(v, int | float | Decimal):
        raise PlanilhaRecusada(f"{rotulo} do item {item} não é um número")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise PlanilhaRecusada(f"{rotulo} do item {item} não é um número") from None
    if not d.is_finite():
        raise PlanilhaRecusada(f"{rotulo} do item {item} não é um número")
    return d


def _qtd(d: Decimal | None) -> str | None:
    """Quantidade em texto decimal, sem expoente nem zeros a direita: 20.0 -> "20", 120.250 -> "120.25"."""
    if d is None:
        return None
    return format(d.normalize(), "f")


def _centavos(d: Decimal | None, item: str) -> int | None:
    if d is None:
        return None
    c = rm.centavos(d)      # o arredondamento unico do projeto (meio para cima, pelo texto do numero)
    if abs(c) > dinheiro.TETO_CENTAVOS:
        raise PlanilhaRecusada(f"o valor do item {item} passa do máximo aceito")
    return c


def _do_prefixo(numero: str, titulos: dict[str, str]) -> str | None:
    """O titulo de nº mais longo que prefixa o nº do item ("3.1" prefixa "3.1.2"; "3" tambem, mas e' mais curto)."""
    melhor = None
    for n in titulos:
        if (numero.startswith(n + ".") or numero == n) and (melhor is None or len(n) > len(melhor)):
            melhor = n
    return titulos[melhor] if melhor is not None else None


def _do_cadastro(numero: str, cadastro: list[dict]) -> str | None:
    """O grupo do cadastro cujo prefixo cobre o nº do item, no limite do ponto: "1" e "1." cobrem "1" e "1.2", nao
    "10.1"."""
    for g in cadastro:
        for p in g.get("itens_planilha") or []:
            p = str(p).strip()
            raiz = p.rstrip(".")
            if numero and raiz and (numero == raiz or numero.startswith(raiz + ".")):
                return g["nome"]
    return None


def _somar_quantidade(itens: list[dict], chave: str) -> str | None:
    if not itens or len({i["unidade"] for i in itens}) != 1:
        return None                     # m³ com m nao se soma
    valores = [Decimal(i[chave]) for i in itens if i[chave] is not None]
    return _qtd(sum(valores, Decimal(0))) if valores else None


def agrupar(itens: list[tuple[str, dict]], ordem: list[str]) -> list[dict]:
    """Os grupos (na ordem do cadastro, senao na do primeiro item; "outros" por ultimo) com as somas e os itens."""
    por: dict[str, list[dict]] = {}
    for g, it in itens:
        por.setdefault(g, []).append(it)
    nomes = [n for n in ordem if n in por] + [n for n in por if n not in ordem and n != OUTROS]
    if OUTROS in por:
        nomes.append(OUTROS)
    saida = []
    for n in nomes:
        its = por[n]
        unidades = {i["unidade"] for i in its}
        saida.append({
            "nome": n, "unidade": next(iter(unidades)) if len(unidades) == 1 else None,
            "quantidade_medida": _somar_quantidade(its, "quantidade_medida"),
            "quantidade_acumulada": _somar_quantidade(its, "quantidade_acumulada"),
            "valor_medido_centavos": sum(i["valor_medido_centavos"] for i in its),
            "valor_acumulado_centavos": sum(i["valor_acumulado_centavos"] or 0 for i in its),
            "itens": its})
    return saida



# --- abertura do xlsx: so' as partes que a leitura usa, em fluxo e com teto -----------------------------------
# A planilha real da SINFRA tem ~240 abas (as memorias de calculo), ~2.000 partes no zip, workbook.xml de 25 MB
# (nomes definidos) e estilos de 11 MB: o openpyxl carregaria tudo isso. Aqui so' se abrem o workbook (ate' a lista
# de abas), os rels, os textos compartilhados e a aba do resumo, com teto no que DE FATO se descompacta.
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAX_ENTRADAS = 10_000
MAX_BYTES_INDICE = 2_000_000           # o indice (diretorio central) do zip, lido inteiro ao abrir
MAX_BYTES_ARQUIVO = 60_000_000         # o .xlsx inteiro (o real da SINFRA, com as memorias de calculo, tem ~30 MB)
MAX_BYTES_ABA = 30_000_000              # a aba do resumo real tem ~1,6 MB
MAX_BYTES_TEXTOS = 30_000_000           # os textos compartilhados reais, ~0,2 MB
MAX_BYTES_RELS = 5_000_000
MAX_BYTES_WORKBOOK = 5_000_000          # so' ate' o fim da lista de abas (os nomes definidos vem depois)
MAX_TEXTOS = 1_000_000
GRANDE_DEMAIS = "a planilha é grande demais para o modelo"
COMPRESSOES = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)


class _Contada:
    """Uma parte do zip aberta, que para no teto (nunca le mais que o teto mais um pedaco)."""

    def __init__(self, bruto, teto: int):
        self._bruto, self._teto, self._lidos = bruto, teto, 0

    def read(self, n: int = -1) -> bytes:
        pedaco = self._bruto.read(64 * 1024 if n is None or n < 0 else min(n, 64 * 1024))
        self._lidos += len(pedaco)
        if self._lidos > self._teto:
            raise PlanilhaRecusada(GRANDE_DEMAIS)
        return pedaco


def _eventos(z: zipfile.ZipFile, nome: str, teto: int):
    try:
        info = z.getinfo(nome)
    except KeyError:
        raise PlanilhaRecusada("o arquivo não abre como planilha .xlsx") from None
    if info.compress_type not in COMPRESSOES:
        raise PlanilhaRecusada("a planilha usa uma compressão que o Excel não grava")
    with z.open(info) as bruto:
        yield from ElementTree.iterparse(_Contada(bruto, teto), events=("start", "end"))


def _caminho_da_aba(z: zipfile.ZipFile) -> str:
    """O caminho no zip da aba do resumo ("Resumo", senao "Resumo Medição"), pelo workbook e pelos rels."""
    abas: dict[str, str] = {}
    for evento, el in _eventos(z, "xl/workbook.xml", MAX_BYTES_WORKBOOK):
        if evento == "end" and el.tag == f"{_NS}sheet":
            abas.setdefault(_texto(el.get("name")), el.get(f"{_NS_REL}id") or "")
        elif evento == "end" and el.tag == f"{_NS}sheets":
            break
    rid = next((abas[a] for a in ABAS if a in abas), None)
    if rid is None:
        raise PlanilhaRecusada("falta a aba Resumo (ou Resumo Medição)")
    for evento, el in _eventos(z, "xl/_rels/workbook.xml.rels", MAX_BYTES_RELS):
        if evento == "end" and el.tag == f"{_NS_PKG}Relationship" and el.get("Id") == rid:
            alvo = (el.get("Target") or "").replace("\\", "/")
            return alvo.lstrip("/") if alvo.startswith("/") else posixpath.normpath(f"xl/{alvo}")
    raise PlanilhaRecusada("a aba Resumo não pôde ser lida")


def _textos(z: zipfile.ZipFile) -> list[str]:
    """Os textos compartilhados (as celulas de texto apontam para eles pelo indice). Sem a parte, nenhum."""
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    saida: list[str] = []
    raiz = None
    for evento, el in _eventos(z, "xl/sharedStrings.xml", MAX_BYTES_TEXTOS):
        if evento == "start":
            if el.tag == f"{_NS}sst":
                raiz = el
            continue
        if el.tag == f"{_NS}si":
            # texto simples (<t>) ou com formatacao (<r><t>); o fonetico (<rPh>) nao faz parte do valor
            partes = []
            for filho in el:
                t = filho if filho.tag == f"{_NS}t" else filho.find(f"{_NS}t") if filho.tag == f"{_NS}r" else None
                if t is not None:
                    partes.append(t.text or "")
            saida.append("".join(partes))
            if raiz is not None:
                raiz.clear()            # o <si> lido sai da memoria (fica so' o texto)
            if len(saida) > MAX_TEXTOS:
                raise PlanilhaRecusada(GRANDE_DEMAIS)
    return saida


def _coluna(ref: str) -> int:
    """"AB12" -> 27 (indice a partir de 0)."""
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _valor(c, textos: list[str]):
    """O valor guardado da celula (o calculado, nas formulas): numero, texto, booleano ou None."""
    tipo = c.get("t")
    if tipo == "inlineStr":
        el = c.find(f"{_NS}is")
        return "".join(t.text or "" for t in el.iter(f"{_NS}t")) if el is not None else None
    v = c.find(f"{_NS}v")
    if v is None or v.text is None:
        return None
    if tipo == "s":
        try:
            return textos[int(v.text)]
        except (ValueError, IndexError):
            raise PlanilhaRecusada("a aba Resumo aponta para um texto que não existe") from None
    if tipo in ("str", "e"):
        return v.text if tipo == "str" else None
    if tipo == "b":
        return v.text == "1"
    try:
        d = Decimal(v.text.strip())
    except InvalidOperation:
        return None
    if not d.is_finite():
        return None
    return int(d) if d == int(d) and "." not in v.text and "E" not in v.text.upper() else d


def _linhas(z: zipfile.ZipFile, caminho: str, textos: list[str]):
    """(nº da linha, [valores por coluna]) da aba, em fluxo: a linha entregue sai da memoria."""
    numero, dados_aba = 0, None
    for evento, el in _eventos(z, caminho, MAX_BYTES_ABA):
        if evento == "start":
            if el.tag == f"{_NS}sheetData":
                dados_aba = el
            continue
        if el.tag != f"{_NS}row":
            continue
        try:
            numero = int(el.get("r") or numero + 1)
        except ValueError:
            numero += 1
        valores: list = []
        for c in el.iter(f"{_NS}c"):
            col = _coluna(c.get("r") or "") if c.get("r") else len(valores)
            if col < 0 or col >= MAX_COLUNAS:
                continue
            while len(valores) <= col:
                valores.append(None)
            valores[col] = _valor(c, textos)
        yield numero, valores
        if dados_aba is not None:
            dados_aba.clear()


def _ler_linhas(linhas, cadastro: list[dict] | None) -> dict:
    col, linhas = _achar_cabecalho(iter(linhas))
    sem_item = "item" not in col        # modelo sem ITEM (issue #612): grupo pelo titulo mais recente
    por_titulo: dict[str, str] = {}     # titulo comparavel -> grupo do cadastro (issue #613)
    if sem_item:
        # os prefixos do cadastro sao de nº de item, que este modelo nao tem: vale so' o `titulos_planilha`; sem
        # nenhum titulo no cadastro, agrupa pelos titulos da propria planilha (como antes da #613)
        por_titulo = {titulo_comparavel(t): g["nome"] for g in cadastro or [] for t in g.get("titulos_planilha") or []}
        if not por_titulo:
            cadastro = None
    titulo_atual: str | None = None
    titulos: dict[str, str] = {}
    itens: list[tuple[str, dict]] = []
    lidas = 0
    for _numero, linha in linhas:
        lidas += 1
        if lidas > MAX_LINHAS:
            raise PlanilhaRecusada("a aba Resumo é grande demais para o modelo")
        textos = [_texto(v) for v in linha]
        if any(t.startswith("TOTAL GERAL") for t in textos):
            break                       # sem TOTAL GERAL, a tabela acaba no fim da aba
        if sem_item and any(t.startswith(FIM_SEM_ITEM) for t in textos):
            break
        if sem_item and any(t.split()[0] in ("TOTAL", "SUB-TOTAL") or t.startswith("SUB TOTAL")
                            for t in textos if t):
            continue                    # outra linha de soma: nunca titulo nem item
        if any(t.startswith("SUBTOTAL") for t in textos):
            continue
        celula = lambda k: linha[col[k]] if k in col and col[k] < len(linha) else None   # noqa: E731
        numero_item, codigo = _nome_item(celula("item")), _nome_item(celula("codigo"))
        unidade = celula("unidade")
        unidade = unidade.strip() if isinstance(unidade, str) else _nome_item(unidade)
        descricao = celula("descricao")
        descricao = " ".join(descricao.split()) if isinstance(descricao, str) else _nome_item(descricao)
        preco = celula("preco")
        sem_preco = preco is None or (isinstance(preco, str) and not preco.strip())
        if sem_item and not codigo and not unidade and sem_preco and descricao:
            titulo_atual = descricao     # titulo de grupo ou de subgrupo, sem nº
            continue
        if not numero_item and not codigo and not (sem_item and descricao and (unidade or not sem_preco)):
            continue                    # linha em branco, rodape, subtotal sem rotulo (sem ITEM: item sem codigo vale)
        # o item tem unidade ou preco unitario; o grupo (e o subgrupo), nem um nem outro, mesmo com codigo ("11.2*")
        # e com a soma dos itens nas colunas de valor (que nao entra: os itens ja' contam)
        if not unidade and sem_preco:
            if numero_item and descricao:
                titulos[numero_item] = descricao     # linha de grupo
            continue
        nome = numero_item or codigo or descricao
        if len(itens) >= MAX_ITENS:
            raise PlanilhaRecusada("itens demais na aba Resumo")
        qc = _decimal(celula("quantidade_contratada"), "a quantidade contratada", nome)
        qm = _decimal(celula("quantidade_medida"), "a quantidade nesta medição", nome)
        qa = _decimal(celula("quantidade_acumulada"), "a quantidade acumulada", nome)
        pu = _decimal(celula("preco"), "o preço unitário", nome)
        vm = _decimal(celula("valor_medido"), "o valor nesta medição", nome)
        va = _decimal(celula("valor_acumulado"), "o valor acumulado", nome)
        if sem_item and cadastro:
            grupo = por_titulo.get(titulo_comparavel(titulo_atual)) if titulo_atual else None
        elif sem_item:
            grupo = titulo_atual
        elif cadastro:
            grupo = _do_cadastro(numero_item, cadastro)
        else:
            grupo = _do_prefixo(numero_item, titulos) if numero_item else None
        itens.append((grupo or OUTROS, {
            "item": numero_item or None, "codigo": codigo or None, "descricao": descricao or None,
            "unidade": unidade or None, "quantidade_contratada": _qtd(qc), "quantidade_medida": _qtd(qm),
            "quantidade_acumulada": _qtd(qa), "preco_unitario_centavos": _centavos(pu, nome),
            "valor_medido_centavos": _centavos(vm, nome) or 0, "valor_acumulado_centavos": _centavos(va, nome)}))
    if not itens:
        raise PlanilhaRecusada("nenhum item com valor na aba Resumo")
    ordem = [g["nome"] for g in cadastro] if cadastro else []
    grupos = agrupar(itens, ordem)
    return {"grupos": grupos, "total_centavos": sum(g["valor_medido_centavos"] for g in grupos),
            "grupo_por": "cadastro" if cadastro else "planilha"}


def _recusar_indice_grande(dados: bytes) -> None:
    """Antes de o `zipfile` montar o indice inteiro na memoria: o fim do zip declara quantas entradas ha' e o
    tamanho do indice, que o `zipfile` le de uma vez. O zip64 (localizador `PK\\x06\\x07` antes do fim) troca esses
    campos pelos do registro zip64 e nao e' o que o Excel grava para uma planilha deste tamanho: recusa. Mesma
    conferencia da leitura de reajuste, com o teto da planilha da SINFRA (~2.000 partes, indice de ~0,2 MB)."""
    n = len(dados)
    fim = n - 22 if n >= 22 and dados[n - 22:n - 18] == b"PK\x05\x06" else dados.rfind(b"PK\x05\x06", max(0, n - 65_557))
    if fim < 0:
        return                         # sem o fim, o `zipfile` recusa antes de montar o indice
    if fim + 22 > n or (fim >= 20 and dados[fim - 20:fim - 16] == b"PK\x06\x07"):
        raise PlanilhaRecusada(GRANDE_DEMAIS)
    entradas = int.from_bytes(dados[fim + 10:fim + 12], "little")
    indice = int.from_bytes(dados[fim + 12:fim + 16], "little")
    if entradas > MAX_ENTRADAS or indice > MAX_BYTES_INDICE:
        raise PlanilhaRecusada(GRANDE_DEMAIS)


def ler(dados: bytes, cadastro: list[dict] | None = None) -> dict:
    """{"grupos": [{nome, unidade, quantidade_medida, quantidade_acumulada, valor_medido_centavos,
    valor_acumulado_centavos, itens: [...]}], "total_centavos", "grupo_por": "cadastro" | "planilha"}.
    `cadastro`: [{"nome", "itens_planilha": [prefixos], "titulos_planilha": [titulos] (opcional)}] do cadastro de
    custo da obra, na ordem do yaml."""
    try:
        if len(dados) > MAX_BYTES_ARQUIVO:
            raise PlanilhaRecusada(GRANDE_DEMAIS)
        _recusar_indice_grande(dados)
        with zipfile.ZipFile(io.BytesIO(dados)) as z:
            if len(z.infolist()) > MAX_ENTRADAS:
                raise PlanilhaRecusada(GRANDE_DEMAIS)
            caminho = _caminho_da_aba(z)
            textos = _textos(z)
            return _ler_linhas(_linhas(z, caminho, textos), cadastro)
    except PlanilhaRecusada:
        raise
    except Exception as e:      # arquivo de fora: zip ou XML quebrado vira recusa, nao erro 500
        raise PlanilhaRecusada("o arquivo não abre como planilha .xlsx") from e

def conferir_total(total_centavos: int, pedido_centavos: int) -> None:
    """A soma dos grupos tem de bater com o valor pedido da medicao, com tolerancia de um real."""
    diferenca = total_centavos - pedido_centavos
    if abs(diferenca) > TOLERANCIA_CENTAVOS:
        raise PlanilhaRecusada(
            f"diferença de {dinheiro.format_brl(abs(diferenca))} entre a soma dos grupos da planilha "
            f"({dinheiro.format_brl(total_centavos)}) e o valor pedido da medição "
            f"({dinheiro.format_brl(pedido_centavos)})")
