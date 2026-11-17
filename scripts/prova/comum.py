"""Roteiros de prova (issue #702): o que `servidor.py`, `retrato.py`, `capturar.mjs` e `ponta_a_ponta.py` tem em comum.

A prova de uma entrega roda sempre num banco que NAO e' o de trabalho: um banco temporario novo (cadastro aplicado
na hora) ou uma copia. Nenhum caminho de maquina mora nestes roteiros; tudo chega por variavel de ambiente:

  DASH_DB_PATH        o banco da prova. Arquivo que ainda nao existe = banco novo; arquivo que existe = copia.
                      Recusado se faltar, se for o banco padrao (`backend/dados/dashboard.db`) ou se ficar dentro
                      do repositorio: ao lado dele nascem a senha de teste, o correio simulado e o log.
  DASH_CADASTRO_DIR   a pasta do cadastro (YAML). Recusada se faltar ou nao existir. Para dado de exemplo, aponte
                      para `cadastro-exemplo/`.
  DASH_PROVA_SAIDA    opcional: onde gravar retratos e capturas. Padrao: `prova-saida/` ao lado do banco (fora do
                      repositorio). Dentro do repositorio so' vale `.prova/`, que o git ignora.

So' biblioteca padrao: roda com qualquer Python 3.12+, sem o ambiente do backend.
"""
from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BACKEND = RAIZ / "backend"
FRONTEND = RAIZ / "frontend"
CADASTRO_EXEMPLO = RAIZ / "cadastro-exemplo"
# Unica pasta de saida aceita dentro do repositorio (esta no .gitignore).
SAIDA_NO_REPOSITORIO = ".prova"
# Os tres perfis do sistema (backend/app/permissoes.py). Cada um ganha um usuario de teste no banco da prova.
PERFIS = ("admin", "engenharia", "diretoria")
DOMINIO_DE_TESTE = "exemplo.com.br"

# Variaveis DASH_* que passam do terminal de quem roda para o servidor de prova. O resto e' apagado: uma
# DASH_RM_URL ou um DASH_GRAPH_CLIENT_ID esquecidos no terminal ligariam o RM e o e-mail de verdade.
HERDADAS = ("DASH_FONTE_CARTA", "DASH_FONTE_CARTA_NEGRITO", "DASH_TESSERACT", "DASH_TESSDATA")


class Recusa(Exception):
    """O roteiro nao roda com o ambiente como esta'. A mensagem diz o que acertar."""


def email_de_teste(perfil: str) -> str:
    return f"prova-{perfil}@{DOMINIO_DE_TESTE}"


def absoluto(valor: str, base: Path | None = None) -> Path:
    p = Path(valor).expanduser()
    if not p.is_absolute():
        p = (base or Path.cwd()) / p
    return p.resolve()


def dentro(caminho: Path, pasta: Path) -> bool:
    try:
        caminho.resolve().relative_to(pasta.resolve())
    except ValueError:
        return False
    return True


def eh_banco_padrao(valor: str, raiz: Path = RAIZ, base: Path | None = None) -> bool:
    """O banco padrao do desenvolvimento (`backend/dados/dashboard.db`), escrito de qualquer jeito: absoluto,
    relativo a pasta de quem chama, relativo a `backend/` (como o servidor o resolve) ou o de OUTRA copia do
    repositorio (a pasta principal, vista de um worktree)."""
    padrao = (raiz / "backend" / "dados" / "dashboard.db").resolve()
    candidatos = [absoluto(valor, base)]
    if not Path(valor).expanduser().is_absolute():
        candidatos.append(absoluto(valor, raiz / "backend"))
    for c in candidatos:
        if str(c).casefold() == str(padrao).casefold():
            return True
        if tuple(p.casefold() for p in c.parts[-3:]) == ("backend", "dados", "dashboard.db"):
            return True
    return False


def banco_de_prova(ambiente=os.environ, raiz: Path = RAIZ, base: Path | None = None) -> Path:
    valor = (ambiente.get("DASH_DB_PATH") or "").strip()
    if not valor:
        raise Recusa("DASH_DB_PATH não definida. Aponte para o banco da prova: um arquivo novo numa pasta "
                     "temporária (banco novo, com o cadastro aplicado na hora) ou uma cópia do banco.")
    if eh_banco_padrao(valor, raiz, base):
        raise Recusa("DASH_DB_PATH aponta para o banco padrão do desenvolvimento (backend/dados/dashboard.db). "
                     "A prova nunca roda nele: use um arquivo novo numa pasta temporária ou uma cópia.")
    banco = absoluto(valor, base)
    if dentro(banco, raiz):
        raise Recusa(f"DASH_DB_PATH fica dentro do repositório ({banco}). Ao lado do banco da prova nascem a "
                     "senha de teste, o correio simulado e o log: use uma pasta temporária, fora do repositório.")
    if banco.is_dir():
        raise Recusa(f"DASH_DB_PATH é uma pasta ({banco}); precisa ser o arquivo do banco.")
    return banco


def cadastro_de_prova(ambiente=os.environ, base: Path | None = None) -> Path:
    valor = (ambiente.get("DASH_CADASTRO_DIR") or "").strip()
    if not valor:
        raise Recusa("DASH_CADASTRO_DIR não definida. Aponte para a pasta do cadastro; para dado de exemplo, "
                     "a pasta cadastro-exemplo/ do repositório.")
    pasta = absoluto(valor, base)
    if not pasta.is_dir():
        raise Recusa(f"DASH_CADASTRO_DIR não é uma pasta que existe: {pasta}")
    return pasta


def saida_de_prova(ambiente=os.environ, banco: Path | None = None, raiz: Path = RAIZ,
                   base: Path | None = None) -> Path:
    """Onde ficam os retratos e as capturas. Uma copia do banco tem dado real, e o que sai dela tambem: por isso
    a saida mora fora do repositorio, ou em `.prova/`, que o git ignora."""
    valor = (ambiente.get("DASH_PROVA_SAIDA") or "").strip()
    if valor:
        saida = absoluto(valor, base)
    else:
        saida = (banco or banco_de_prova(ambiente, raiz, base)).parent / "prova-saida"
    if dentro(saida, raiz) and not dentro(saida, raiz / SAIDA_NO_REPOSITORIO):
        raise Recusa(f"DASH_PROVA_SAIDA fica dentro do repositório ({saida}). Use uma pasta de fora ou "
                     f"{SAIDA_NO_REPOSITORIO}/, que o git ignora.")
    return saida


def arquivos_da_prova(banco: Path) -> dict:
    """O que nasce ao lado do banco da prova (sempre fora do repositorio)."""
    pasta = banco.parent
    return {
        "senha": pasta / "prova-senha.txt",            # a senha dos usuarios de teste, gerada na hora
        "servidor": pasta / "prova-servidor.json",     # endereco do servidor de prova no ar
        "log": pasta / "prova-servidor.log",
        "correio": pasta / "correio-simulado",         # os e-mails "enviados" caem aqui, em JSON
        "dist": pasta / "prova-dist",                  # o frontend montado para a prova
    }


def ambiente_do_servidor(ambiente, banco: Path, cadastro: Path, dist: Path | None) -> dict:
    """O ambiente do servidor de prova: sem nenhuma DASH_* do terminal (fora as de `HERDADAS`), em modo de
    desenvolvimento, sem jobs (RM, cobranca, backup) e com o e-mail no simulador."""
    env = {k: v for k, v in ambiente.items() if not k.upper().startswith("DASH_") or k.upper() in HERDADAS}
    env.update({
        "DASH_DEV": "1",
        "DASH_SEM_JOBS": "1",
        "DASH_DB_PATH": str(banco),
        "DASH_CADASTRO_DIR": str(cadastro),
        "DASH_GRAPH_SIMULADOR": str(arquivos_da_prova(banco)["correio"]),
        "PYTHONUNBUFFERED": "1",
    })
    if dist is None:
        env["DASH_SEM_FRONTEND"] = "1"
    else:
        env["DASH_DIST_PATH"] = str(dist)
    return env


def python_do_backend() -> str:
    """O Python que tem as dependencias do backend: o do `.venv` quando existe; senao o que esta' rodando (CI)."""
    import sys
    for candidato in (BACKEND / ".venv" / "bin" / "python", BACKEND / ".venv" / "Scripts" / "python.exe"):
        if candidato.exists():
            return str(candidato)
    return sys.executable
