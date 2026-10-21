"""Carga do historico de medicoes por CSV (spec 2026-10-20 §2.4, opcao A; issue #258).

So' o ENSAIO: le o CSV de uma obra, confere linha a linha contra o banco e devolve o relatorio. Nao grava nada
(nem abre transacao de escrita); gravar e' a issue seguinte. A chave e' (obra, numero, tipo).

Categorias por linha: `nova` (nao existe medicao com a chave), `igual`, `valor diferente` (pedido ou aprovado
diferem do banco) e `conflito` (o mesmo numero e tipo com outra competencia). Linha que nao se le vira `erro`,
com o numero da linha do arquivo.
"""

import csv
import datetime
import io
import re
import unicodedata
from pathlib import Path

from app import contratos, dinheiro
from app.cadastro_arquivos import slug

TIPOS = ("execucao", "projeto", "reajuste")
CATEGORIAS = ("nova", "igual", "valor diferente", "conflito", "erro")

# Cabecalho normalizado (sem acento, minusculas, "nº" vira "no") -> campo
COLUNAS = {
    "no": "numero",
    "no do orgao": "numero_orgao",
    "tipo": "tipo",
    "competencia": "competencia",
    "periodo": "periodo",
    "valor pedido": "valor_pedido",
    "valor aprovado": "valor_aprovado",
    "data da aprovacao": "data_aprovacao",
    "meio": "meio",
    "no do processo no orgao": "processo_orgao",
    "data do protocolo da nota": "data_protocolo_nota",
    "nf": "nf",
    "fonte": "fonte",
}
OBRIGATORIAS = ("numero", "tipo", "competencia")


class CsvInvalido(ValueError):
    """O arquivo inteiro nao se le (cabecalho, codificacao, obra): nada a relatar por linha."""


def _normalizar(texto: str) -> str:
    # "n°" (grau, comum no Excel) vale "nº"; o ponto de "nº." cai
    texto = texto.replace("°", "º").replace("º.", "º")
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_.strip().lower())


def _competencia(texto: str) -> str:
    """'2025-04' ou '04/2025' -> '2025-04'."""
    m = re.fullmatch(r"([0-9]{4})-([0-9]{2})", texto) or re.fullmatch(r"([0-9]{2})/([0-9]{4})", texto)
    if not m:
        raise ValueError(f"competência inválida: {texto!r} (use AAAA-MM ou MM/AAAA)")
    ano, mes = (m.group(1), m.group(2)) if "-" in texto else (m.group(2), m.group(1))
    if not 1 <= int(mes) <= 12:
        raise ValueError(f"competência inválida: {texto!r} (mês fora de 01 a 12)")
    return f"{ano}-{mes}"


def _data(texto: str, campo: str) -> str | None:
    if not texto:
        return None
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"{campo} inválida: {texto!r} (use DD/MM/AAAA)")


def _valor(texto: str, campo: str) -> int | None:
    if not texto:
        return None
    try:
        return dinheiro.parse_brl(texto)
    except ValueError as e:
        raise ValueError(f"{campo}: {texto!r}: {e}") from None


def _ler_texto(caminho: Path) -> str:
    bruto = caminho.read_bytes()
    try:
        return bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        return bruto.decode("cp1252")  # CSV salvo pelo Excel em pt-BR


def ler_csv(caminho: Path) -> list[tuple[int, dict]]:
    """Linhas do CSV como (numero da linha no arquivo, {campo: texto}). Separador `;` (Excel pt-BR) ou `,`."""
    texto = _ler_texto(caminho)
    primeira = texto.split("\n", 1)[0]
    leitor = csv.reader(io.StringIO(texto), delimiter=";" if ";" in primeira else ",")
    try:
        cabecalho = next(leitor)
    except StopIteration:
        raise CsvInvalido("arquivo vazio") from None
    campos = []
    for coluna in cabecalho:
        nome = _normalizar(coluna)
        if nome not in COLUNAS:
            raise CsvInvalido(f"coluna desconhecida no cabeçalho: {coluna!r}")
        if COLUNAS[nome] in campos:
            raise CsvInvalido(f"coluna repetida no cabeçalho: {coluna!r}")
        campos.append(COLUNAS[nome])
    faltam = [c for c in OBRIGATORIAS if c not in campos]
    if faltam:
        raise CsvInvalido(f"faltam colunas no cabeçalho: {', '.join(faltam)}")
    linhas, inicio = [], leitor.line_num + 1
    for celulas in leitor:
        n_linha, inicio = inicio, leitor.line_num + 1      # a linha onde o registro COMECA (celula com quebra)
        if not any(c.strip() for c in celulas):
            continue
        dados = {campo: celulas[i].strip() for i, campo in enumerate(campos) if i < len(celulas)}
        if len(celulas) != len(campos):
            # Valor com virgula sem aspas num CSV separado por virgula desloca as colunas: nunca adivinhar
            dados["_erro"] = f"a linha tem {len(celulas)} colunas e o cabeçalho tem {len(campos)}"
        linhas.append((n_linha, dados))
    return linhas


def _interpretar(bruto: dict, janela: tuple[str, str] | None) -> dict:
    """Valida e converte uma linha. ValueError com a mensagem do primeiro problema."""
    if bruto.get("_erro"):
        raise ValueError(bruto["_erro"])
    numero = bruto.get("numero", "")
    if not re.fullmatch(r"[0-9]+", numero) or int(numero) < 1:
        raise ValueError(f"nº inválido: {numero!r}")
    tipo = _normalizar(bruto.get("tipo", ""))
    if tipo not in TIPOS:
        raise ValueError(f"tipo desconhecido: {bruto.get('tipo', '')!r} (use {', '.join(TIPOS)})")
    competencia = _competencia(bruto.get("competencia", ""))
    if janela and not janela[0] <= competencia <= janela[1]:
        raise ValueError(f"competência {competencia} fora do contrato ({janela[0]} a {janela[1]})")
    return {"numero": int(numero), "tipo": tipo, "competencia": competencia,
            "valor_pedido": _valor(bruto.get("valor_pedido", ""), "valor pedido"),
            "valor_aprovado": _valor(bruto.get("valor_aprovado", ""), "valor aprovado"),
            "data_aprovacao": _data(bruto.get("data_aprovacao", ""), "data da aprovação"),
            "data_protocolo_nota": _data(bruto.get("data_protocolo_nota", ""), "data do protocolo da nota")}


def contrato_da_obra(conn, obra: str):
    """O contrato cujo slug do nome curto e' `obra` (o mesmo nome do arquivo `contratos/<obra>.yaml`)."""
    achados = [c for c in conn.execute(
        "SELECT id, nome_curto, vigencia_inicio, vigencia_fim FROM contratos WHERE nome_curto IS NOT NULL")
        if slug(c["nome_curto"]) == obra]
    if len(achados) != 1:
        raise CsvInvalido(f"obra {obra!r} não encontrada no banco" if not achados
                          else f"obra {obra!r} corresponde a mais de um contrato")
    return achados[0]


def _janela(conn, contrato) -> tuple[str, str] | None:
    """Competencias aceitas: do mes do inicio ao mes do fim da vigencia, com os aditivos de prazo assinados.
    Sem as duas datas, nao confere."""
    ini, fim = contrato["vigencia_inicio"], contratos.vigente(conn, contrato["id"])["vigencia_fim_vigente"]
    return (ini[:7], fim[:7]) if ini and fim else None


def ensaiar(conn, caminho: Path, obra: str | None = None) -> dict:
    """Relatorio do ensaio. `obra` padrao: o nome do arquivo sem extensao. So' le o banco."""
    obra = obra or caminho.stem
    contrato = contrato_da_obra(conn, obra)
    janela = _janela(conn, contrato)
    existentes = {(m["numero"], m["tipo"]): m for m in conn.execute(
        "SELECT numero, tipo, competencia, valor_protocolado_centavos, valor_atestado_centavos "
        "FROM medicoes WHERE contrato_id=?", (contrato["id"],))}
    linhas, vistas = [], {}
    for n_linha, bruto in ler_csv(caminho):
        item = {"linha": n_linha, "numero": bruto.get("numero", ""), "tipo": bruto.get("tipo", "")}
        try:
            d = _interpretar(bruto, janela)
        except ValueError as e:
            linhas.append({**item, "categoria": "erro", "detalhe": str(e)})
            continue
        item.update(numero=d["numero"], tipo=d["tipo"], competencia=d["competencia"])
        chave = (d["numero"], d["tipo"])
        if chave in vistas:
            linhas.append({**item, "categoria": "erro",
                           "detalhe": f"nº {d['numero']} {d['tipo']} repetido (já na linha {vistas[chave]})"})
            continue
        vistas[chave] = n_linha
        m = existentes.get(chave)
        if m is None:
            linhas.append({**item, "categoria": "nova", "detalhe": ""})
        elif m["competencia"] != d["competencia"]:
            linhas.append({**item, "categoria": "conflito",
                           "detalhe": f"banco tem competência {m['competencia']}"})
        else:
            difs, vazios = [], []
            for rotulo, campo, col in (("pedido", "valor_pedido", "valor_protocolado_centavos"),
                                       ("aprovado", "valor_aprovado", "valor_atestado_centavos")):
                if d[campo] is None:
                    # Celula vazia = o CSV nao informa (nao e' zero): nao compara, mas o relatorio diz
                    if m[col] is not None:
                        vazios.append(f"{rotulo} vazio no CSV, banco {_fmt(m[col])}")
                elif d[campo] != m[col]:
                    difs.append(f"{rotulo}: banco {_fmt(m[col])}, CSV {_fmt(d[campo])}")
            linhas.append({**item, "categoria": "valor diferente" if difs else "igual",
                           "detalhe": "; ".join(difs + vazios)})
    totais = {c: sum(1 for li in linhas if li["categoria"] == c) for c in CATEGORIAS}
    return {"obra": obra, "contrato": contrato["nome_curto"], "linhas": linhas, "totais": totais}


def _fmt(centavos: int | None) -> str:
    return "vazio" if centavos is None else dinheiro.format_brl(centavos)
