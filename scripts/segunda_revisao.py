"""PR que toca dinheiro, envio ou banco exige a segunda revisao independente (issue #709).

Regra do CLAUDE.md: mudanca em dinheiro, envio ou banco passa por uma segunda revisao, de quem nao escreveu o
codigo, antes do merge. Aqui ela deixa de ser frase: o script compara os arquivos alterados na PR com os caminhos
(`paths:`) de `.claude/rules/dinheiro.md`, `envio.md` e `banco.md` e, se algum bate, exige no corpo da PR o item
"Segunda revisao independente" marcado (`- [x]`) e com texto depois dos dois-pontos. Vale qualquer revisor
independente; o script nao confere quem revisou, so' que o item foi preenchido. So' conta o item cujo rotulo (o texto
antes dos dois-pontos) e' o da segunda revisao: citar as palavras em outro item nao o substitui (#800).

  - A lista de caminhos e' lida dos arquivos de regra, sem copia aqui. Com `--base`, vale a uniao dos caminhos da
    base e dos da propria PR: tirar um caminho da regra na mesma PR que mexe no arquivo nao dispensa a revisao.
  - PR que nao toca esses caminhos passa sem exigir o item.
  - `--so-avisa`: mostra o que pediria a revisao e sai com 0. A CI usa em PR cuja base nao e' o `master` (branch de
    integracao): a revisao e' cobrada na PR que leva o trabalho ao `master`.

Uso:
  python scripts/segunda_revisao.py --base origin/master --corpo corpo.md     # CI: arquivos de `git diff base...HEAD`
  gh pr diff 123 --name-only | python scripts/segunda_revisao.py --arquivos - --corpo corpo.md   # conferir a mao

So' biblioteca padrao. Codigos de saida: 0 passa, 1 falta a segunda revisao, 2 erro de uso, de git ou de regra.
"""
import argparse
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
REGRAS = {
    "dinheiro": ".claude/rules/dinheiro.md",
    "envio": ".claude/rules/envio.md",
    "banco": ".claude/rules/banco.md",
}
ITEM = "Segunda revisão independente"


class Erro(Exception):
    """Erro de uso, de git ou de arquivo de regra: codigo 2."""


# --- caminhos das regras ----------------------------------------------------------------------------------------

def caminhos_da_regra(texto: str) -> list:
    """A lista `paths:` do cabecalho (entre os dois `---`) de um arquivo de regra, na ordem escrita."""
    linhas = texto.lstrip("﻿").splitlines()
    if not linhas or linhas[0].strip() != "---":
        return []
    achados, dentro = [], False
    for linha in linhas[1:]:
        if linha.strip() == "---":
            break
        if re.match(r"paths\s*:\s*$", linha):
            dentro = True
        elif dentro:
            m = re.match(r"\s+-\s+(.+?)\s*$", linha)
            if m:
                achados.append(m.group(1).strip("\"'"))
            elif linha.strip() and not linha[0].isspace():
                dentro = False   # outra chave do cabecalho
    return achados


def _regex(padrao: str):
    """Glob dos arquivos de regra: `**` atravessa pastas, `*` e `?` ficam dentro de uma."""
    partes, i = [], 0
    while i < len(padrao):
        if padrao.startswith("**/", i):
            partes.append("(?:.*/)?")
            i += 3
        elif padrao.startswith("**", i):
            partes.append(".*")
            i += 2
        elif padrao[i] == "*":
            partes.append("[^/]*")
            i += 1
        elif padrao[i] == "?":
            partes.append("[^/]")
            i += 1
        else:
            partes.append(re.escape(padrao[i]))
            i += 1
    return re.compile("".join(partes) + r"\Z")


def tocados(arquivos, padroes: dict) -> list:
    """[(arquivo, area, padrao)] dos arquivos que batem com algum caminho de regra; um por arquivo e area."""
    compilados = [(area, p, _regex(p)) for area, lista in padroes.items() for p in lista]
    achados, vistos = [], set()
    for arquivo in arquivos:
        caminho = arquivo.strip().replace("\\", "/")
        for area, padrao, rx in compilados:
            if caminho and (caminho, area) not in vistos and rx.match(caminho):
                vistos.add((caminho, area))
                achados.append((caminho, area, padrao))
    return achados


# --- item no corpo da PR ----------------------------------------------------------------------------------------

def _plano(texto: str) -> str:
    sem = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return sem.lower()


_CAIXA = re.compile(r"\s*[-*+]\s*\[(?P<marca>[ xX])\]\s*(?P<resto>.*)$")
_CHAMADA = re.compile(r"^\s*quem revisou e o que achou\s*:?", re.I)
_ORDEM = ["ok", "nao_se_aplica", "vazio", "desmarcado", "ausente"]


def item_da_revisao(corpo: str) -> tuple:
    """Como esta' o item da segunda revisao no corpo da PR: (estado, texto).

    Estados: "ausente" (nao ha' o item), "desmarcado" (`- [ ]`), "vazio" (marcado, sem texto depois dos
    dois-pontos), "nao_se_aplica" (marcado e dizendo que nao se aplica) e "ok". O texto pode continuar nas linhas
    recuadas logo abaixo do item. Comentario HTML do modelo nao conta."""
    linhas = re.sub(r"<!--.*?-->", "", corpo or "", flags=re.S).replace("\r", "").split("\n")
    melhor = ("ausente", "")
    for i, linha in enumerate(linhas):
        m = _CAIXA.match(linha)
        if not m:
            continue
        # so' conta o item cujo ROTULO (o que vem antes dos dois-pontos) e' o da segunda revisao: a mencao as palavras
        # em outro item ("O que nao foi conferido: a segunda revisao esta em aberto") nao e' o item (#800)
        rotulo, dois_pontos, texto = m["resto"].partition(":")
        if not re.sub(r"^\W+", "", _plano(rotulo)).startswith("segunda revisao"):
            continue
        texto = _CHAMADA.sub("", texto, count=1) if dois_pontos else ""
        for seguinte in linhas[i + 1:]:
            if not seguinte.strip() or not seguinte[0].isspace():
                break
            texto += " " + seguinte.strip()
        texto = texto.strip()
        if m["marca"] == " ":
            estado = "desmarcado"
        elif not re.search(r"\w", texto):
            estado = "vazio"
        elif re.match(r"\W*(nao se aplica|n/a\b)", _plano(texto)):
            estado = "nao_se_aplica"
        else:
            estado = "ok"
        if _ORDEM.index(estado) < _ORDEM.index(melhor[0]):
            melhor = (estado, texto)
    return melhor


FALTA = {
    "ausente": f'o corpo da PR não tem o item "{ITEM}"',
    "desmarcado": f'o item "{ITEM}" do corpo da PR está desmarcado',
    "vazio": f'o item "{ITEM}" do corpo da PR está marcado, mas sem texto depois dos dois-pontos',
    "nao_se_aplica": f'o item "{ITEM}" do corpo da PR diz que não se aplica, e a PR toca essas áreas',
}


def conferir(arquivos, corpo: str, padroes: dict) -> tuple:
    """(passa, linhas da mensagem). Passa quando a PR nao toca as areas ou quando o item esta' preenchido."""
    achados = tocados(arquivos, padroes)
    if not achados:
        return True, ["Nenhum arquivo de dinheiro, envio ou banco nesta PR: a segunda revisão não é exigida."]
    lista = [f"  {arquivo}  ({area}: {padrao})" for arquivo, area, padrao in achados]
    areas = ", ".join(sorted({area for _, area, _ in achados}))
    estado, _ = item_da_revisao(corpo)
    if estado == "ok":
        return True, [f"A PR toca {areas} e a segunda revisão independente está registrada no corpo da PR.", *lista]
    return False, [
        f"Esta PR toca {areas} e {FALTA[estado]}.",
        "Arquivos que pedem a segunda revisão (área: caminho da regra em .claude/rules/):",
        *lista,
        "Como resolver: a mudança passa por uma segunda revisão, de quem não escreveu o código. No corpo da PR, "
        f'marque o item "- [x] {ITEM}" e escreva depois dos dois-pontos quem revisou e o que achou. '
        "Depois, reexecute este job.",
    ]


# --- git e linha de comando ---------------------------------------------------------------------------------------

def _git(*args) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as erro:
        detalhe = getattr(erro, "stderr", b"") or b""
        raise Erro(f"git {' '.join(args[:3])} falhou: {detalhe.decode('utf-8', 'replace').strip() or erro}") from erro
    return r.stdout.decode("utf-8", "replace")


def ler_padroes(base: str | None = None) -> dict:
    """Caminhos de cada regra, do arquivo desta arvore e, com `base`, tambem do arquivo na base (uniao)."""
    padroes = {}
    for area, rel in REGRAS.items():
        arquivo = RAIZ / rel
        lista = caminhos_da_regra(arquivo.read_text(encoding="utf-8")) if arquivo.is_file() else []
        if base:
            try:
                da_base = caminhos_da_regra(_git("show", f"{base}:{rel}"))
            except Erro:
                da_base = []   # regra que ainda nao existe na base
            lista += [p for p in da_base if p not in lista]
        if not lista:
            raise Erro(f"{rel} sem lista `paths:` no cabeçalho: não há o que comparar")
        padroes[area] = lista
    return padroes


def arquivos_da_pr(base: str) -> list:
    saida = _git("diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD")
    return [a for a in saida.split("\0") if a]


def _ler(caminho: str) -> str:
    if caminho == "-":
        return sys.stdin.read()
    try:
        return Path(caminho).read_text(encoding="utf-8-sig")
    except OSError as erro:
        raise Erro(f"não consegui ler {caminho}: {erro}") from erro


def main(argv=None) -> int:
    for saida in (sys.stdout, sys.stderr):
        if hasattr(saida, "reconfigure"):
            saida.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description="Exige a segunda revisão em PR que toca dinheiro, envio ou banco.")
    origem = p.add_mutually_exclusive_group(required=True)
    origem.add_argument("--base", help="ref da base da PR; os arquivos saem de `git diff base...HEAD`")
    origem.add_argument("--arquivos", help="arquivo com um caminho alterado por linha (`-` lê da entrada)")
    p.add_argument("--corpo", required=True, help="arquivo com o corpo da PR (`-` lê da entrada)")
    p.add_argument("--so-avisa", action="store_true", help="mostra o que falta e sai com 0")
    args = p.parse_args(argv)
    if args.arquivos == "-" and args.corpo == "-":
        p.error("só um de --arquivos e --corpo pode vir da entrada")

    try:
        padroes = ler_padroes(args.base)
        arquivos = arquivos_da_pr(args.base) if args.base else _ler(args.arquivos).splitlines()
        corpo = _ler(args.corpo)
    except Erro as erro:
        print(f"segunda_revisao: {erro}", file=sys.stderr)
        return 2

    passa, linhas = conferir(arquivos, corpo, padroes)
    if passa:
        print("\n".join(linhas))
        return 0
    na_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    if args.so_avisa:
        prefixo = "::warning::" if na_ci else "AVISO: "
        print(prefixo + linhas[0] + " A base desta PR não é o master: a revisão será cobrada na PR que levar a "
              "mudança ao master.")
        print("\n".join(linhas[1:-1]))
        return 0
    print(("::error::" if na_ci else "ERRO: ") + linhas[0])
    print("\n".join(linhas[1:]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
