"""Roteiros de prova (issue #702): o que `servidor.py`, `retrato.py`, `capturar.mjs` e `ponta_a_ponta.py` tem em comum.

A prova de uma entrega roda sempre num banco que NAO e' o de trabalho: um banco temporario novo (cadastro aplicado
na hora) ou uma copia. Nenhum caminho de maquina mora nestes roteiros; tudo chega por variavel de ambiente:

  DASH_DB_PATH        o banco da prova. Arquivo que ainda nao existe = banco novo. Banco que ja' tem contrato so'
                      entra com `--copia` no `servidor.py`: nada aqui presume que um banco com dado e' copia.
                      Recusado se faltar, se for o banco padrao (`backend/dados/dashboard.db`), se ficar dentro
                      do repositorio (ao lado dele nascem a senha de teste, o correio simulado e o log) ou se for
                      o banco de uma instalacao (a producao): a prova roda migracoes e cria usuarios de teste, um
                      deles administrador, e isso so' se faz numa copia.
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


def como_escrito(valor: str, base: Path | None = None) -> Path:
    """O caminho absoluto como foi escrito: sem resolver link simbolico, juncao de pasta nem `..`."""
    p = Path(valor).expanduser()
    return p if p.is_absolute() else (base or Path.cwd()) / p


def absoluto(valor: str, base: Path | None = None) -> Path:
    return como_escrito(valor, base).resolve()


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


def marcador_de_instalacao(banco: Path) -> Path:
    """O arquivo que marca a instalacao dona de `banco`: `<pasta acima da do banco>/segredos/instalacao.json`.
    E' a regra de `backend/app/instalacao.py` (`caminho_arquivo`), repetida aqui porque estes roteiros rodam so'
    com a biblioteca padrao e aquele modulo pede as dependencias do backend. `backend/tests/test_prova.py` compara
    os dois: se a regra de la' mudar, o teste reprova."""
    return banco.parent.parent / "segredos" / "instalacao.json"


def _recusar_banco_de_instalacao(banco: Path, escrito: Path, ambiente, base: Path | None) -> None:
    """Banco de uma instalacao (a producao, ou a pasta dela copiada inteira) nunca e' banco de prova. Basta o
    arquivo existir; a assinatura nao e' conferida: na duvida, recusa.
    O arquivo e' procurado nas duas formas do caminho do banco. A escrita (`escrito`, sem resolver link) e' a que o
    backend usa: se a pasta `dados` da instalacao for um link ou uma juncao para outro disco, o arquivo esta' ao
    lado do link, nao do destino. A resolvida (`banco`) pega o caminho contrario: um link de fora que aponta para
    o banco dentro da pasta da instalacao."""
    copie = ("A prova roda as migrações e cria usuários de teste, um deles administrador: isso nunca se faz no "
             "banco em uso. Copie o arquivo do banco para uma pasta temporária e aponte DASH_DB_PATH para a cópia.")
    for marcador in dict.fromkeys((marcador_de_instalacao(escrito), marcador_de_instalacao(banco))):
        if marcador.exists():
            raise Recusa(f"DASH_DB_PATH aponta para o banco de uma instalação da dashboard ({banco}): existe "
                         f"{marcador}. {copie}")
    explicito = (ambiente.get("DASH_INSTALACAO_ARQUIVO") or "").strip()
    if explicito and absoluto(explicito, base).exists():
        raise Recusa("Este terminal está com as variáveis de uma instalação da dashboard: DASH_INSTALACAO_ARQUIVO "
                     "aponta para um arquivo que existe, e com ela o banco de DASH_DB_PATH é o da instalação. "
                     f"{copie} Depois apague a variável DASH_INSTALACAO_ARQUIVO deste terminal.")


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
    _recusar_banco_de_instalacao(banco, como_escrito(valor, base), ambiente, base)
    return banco


def estado_do_banco(banco: Path) -> dict:
    """O que o banco ja' tem, lido sem gravar nada nele: quantos contratos e quais usuarios de teste."""
    vazio = {"contratos": 0, "usuarios_de_teste": []}
    if not banco.exists() or banco.stat().st_size == 0:
        return vazio
    import sqlite3

    def ler(conn, sql, parametros=()):
        try:
            return conn.execute(sql, parametros).fetchall()
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):   # banco de antes da migracao que cria a tabela
                return []
            raise   # banco travado ou ilegivel: recusa abaixo, em vez de passar por vazio

    emails = [email_de_teste(p) for p in PERFIS]
    real = banco.resolve()
    # num banco em modo WAL, abrir ate' para ler cria `-wal` e `-shm` vazios ao lado dele. Sem nenhum dos dois, ninguem
    # esta' com o banco aberto e ele esta' todo no arquivo principal: `immutable=1` le o mesmo e nao cria nada. Com
    # algum deles, alguem o tem aberto: le como sempre (so' `mode=ro`) e nao mexe em arquivo nenhum
    auxiliares = [real.with_name(real.name + sufixo) for sufixo in ("-wal", "-shm")]
    so_leitura = "?mode=ro" if any(a.exists() for a in auxiliares) else "?mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(real.as_uri() + so_leitura, uri=True)
        try:
            contratos = ler(conn, "SELECT COUNT(*) FROM contratos")
            usuarios = ler(conn, f"SELECT email FROM usuarios WHERE email IN ({','.join('?' * len(emails))})", emails)
        finally:
            conn.close()
    except sqlite3.DatabaseError as e:
        raise Recusa(f"DASH_DB_PATH não abre como banco SQLite ({banco}): {e}") from None
    return {"contratos": contratos[0][0] if contratos else 0, "usuarios_de_teste": sorted(u[0] for u in usuarios)}


def conferir_copia(banco: Path, copia: bool) -> str:
    """Diz o que o banco da prova e' (`novo`, `vazio`, `copia` ou `preparado`) e recusa o banco que ja' tem contrato
    quando ninguem disse que e' copia. `preparado` e' o banco em que a prova ja' rodou (tem os tres usuarios de
    teste): subir de novo nele nao cria conta nenhuma, entao nao pede `--copia` outra vez."""
    if not banco.exists():
        if copia:
            raise Recusa(f"--copia pede um banco que já existe, e não há arquivo em {banco}. Confira o caminho em "
                         "DASH_DB_PATH; sem --copia, a prova cria ali um banco novo com o cadastro.")
        return "novo"
    estado = estado_do_banco(banco)
    if estado["contratos"] == 0:
        return "vazio"
    if len(estado["usuarios_de_teste"]) == len(PERFIS):
        return "preparado"
    if not copia:
        raise Recusa(f"O banco de DASH_DB_PATH já tem contratos ({banco}) e a prova ainda não rodou nele. Ela roda as "
                     "migrações e cria três usuários de teste, um deles administrador. Se este arquivo é uma cópia, "
                     "suba com --copia; se não é, copie antes e aponte DASH_DB_PATH para a cópia.")
    return "copia"


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
    return saida_permitida(saida, "DASH_PROVA_SAIDA", raiz)


def saida_permitida(pasta: Path, o_que: str, raiz: Path = RAIZ) -> Path:
    """Devolve a pasta, ou recusa a que fica dentro do repositorio fora de `.prova/`. Vale para toda saida da prova
    (`DASH_PROVA_SAIDA` e a pasta de um retrato dada por caminho): o repositorio e' publico."""
    if dentro(pasta, raiz) and not dentro(pasta, raiz / SAIDA_NO_REPOSITORIO):
        raise Recusa(f"{o_que} fica dentro do repositório ({pasta}). Use uma pasta de fora ou "
                     f"{SAIDA_NO_REPOSITORIO}/, que o git ignora.")
    return pasta


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
