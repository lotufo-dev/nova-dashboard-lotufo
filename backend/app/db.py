import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

# Erros de LOCK do SQLite: escrita concorrente que estourou o busy_timeout. Nao e' bug
# nosso nem culpa do cliente -- e' contencao momentanea. Reconhecidos pela mensagem porque
# o sqlite3 nao separa isso em subclasse. Mora aqui (veio de main.py em 10/10/2026) porque
# o correio tambem precisa: registro do envio travado depois do e-mail tenta de novo.
LOCK = ("locked", "busy")


def eh_lock(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and any(t in str(exc).lower() for t in LOCK)

def exigir_uma_linha(cur, mensagem: str) -> None:
    """Perdeu a corrida: o UPDATE condicional nao achou a linha no estado lido.

    Unico lugar do "rowcount != 1 -> ValueError". O perdedor de duas requisicoes concorrentes
    recebe a frase (422), e nao grava auditoria de uma mudanca que nao aconteceu.
    """
    if cur.rowcount != 1:
        raise ValueError(mensagem)


def db_path() -> Path:
    caminho = os.environ.get("DASH_DB_PATH")
    if not caminho:
        # Fora de dev nao ha caminho padrao: era assim que dev e producao acabavam no
        # MESMO banco (parecer de 2026-09-01). Producao vem de scripts\rodar_producao.ps1.
        if os.environ.get("DASH_DEV") != "1":
            raise RuntimeError("DASH_DB_PATH nao definida: fora do desenvolvimento (DASH_DEV=1) "
                               "o caminho do banco e' obrigatorio -- ver docs/runbook.md")
        caminho = "dados/dashboard.db"
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

# Profundidade do envelope de mutacao ABERTO POR NOS, por conexao.
#
# Por que um registro externo e nao um atributo na conexao: sqlite3.Connection e' um
# tipo C sem __dict__ e sem suporte a weakref -- nao aceita nem `conn._em_mutacao = True`
# nem WeakKeyDictionary. A chave e' id(conn); a entrada existe EXATAMENTE enquanto o
# `with` externo esta na pilha (que segura a referencia viva, entao nao ha id reciclado
# por baixo) e some no finally, sempre. Threads usam conexoes distintas -- chaves
# distintas.
_PROFUNDIDADE: dict[int, int] = {}


def em_mutacao(conn) -> bool:
    """True quando `conn` esta dentro de um envelope db.mutacao aberto por nos.

    Distingue "transacao NOSSA" de "transacao qualquer": `conn.in_transaction` fica
    True tambem para a transacao implicita que o sqlite3 abre num DML cru, e essa
    NAO e' um envelope -- ninguem e' dono dela, e commitar por ela seria commitar no
    lugar errado.
    """
    return _PROFUNDIDADE.get(id(conn), 0) > 0


@contextmanager
def mutacao(conn):
    """Dona da transacao de uma mutacao de negocio.

    BEGIN IMMEDIATE serializa escritores desde o inicio (a leitura do head da
    cadeia de auditoria acontece ja sob lock -- sem fork da cadeia).

    Reentrante: dentro de um envelope nosso, compoe com ele em vez de abrir outra
    transacao -- e' o que permite um repositorio envolver `medicoes.criar` sem
    que a parte interna feche a transacao no meio. A composicao usa SAVEPOINT, e nao
    "nao faz nada": sem ponto de retorno proprio, um repositorio interno que escreve
    e levanta deixaria os efeitos parciais gravados caso o chamador externo capturasse
    a excecao e seguisse ate o commit.

    Transacao aberta FORA de um envelope (DML cru sem commit) e' recusada com
    RuntimeError: adotar transacao de dono desconhecido e commitar por ela e' pior do
    que falhar alto.

    Contrato: o dado E a linha da cadeia de auditoria que o descreve entram no
    MESMO commit. Falha em qualquer ponto do bloco desfaz tudo.
    """
    chave = id(conn)
    nivel = _PROFUNDIDADE.get(chave, 0)

    if nivel:
        ponto = f"mutacao_{nivel}"
        conn.execute(f"SAVEPOINT {ponto}")
        _PROFUNDIDADE[chave] = nivel + 1
        try:
            try:
                yield conn
            except BaseException:
                # ROLLBACK TO desfaz so' o que este bloco escreveu e MANTEM a
                # transacao externa viva; o RELEASE seguinte descarta o ponto.
                conn.execute(f"ROLLBACK TO {ponto}")
                conn.execute(f"RELEASE {ponto}")
                raise
            conn.execute(f"RELEASE {ponto}")
        finally:
            _PROFUNDIDADE[chave] = nivel
        return

    if conn.in_transaction:
        raise RuntimeError(
            "Transação já aberta fora de db.mutacao (DML sem commit?): toda escrita "
            "precisa acontecer dentro de db.mutacao(conn)")

    conn.execute("BEGIN IMMEDIATE")
    _PROFUNDIDADE[chave] = 1
    try:
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        try:
            conn.commit()
        except BaseException:
            # Commit pode falhar (disco cheio, fsync travado, lock no WAL). Sem este
            # rollback a excecao escaparia deixando a transacao -- e o lock de escrita
            # -- abertos ate a conexao morrer.
            try:
                conn.rollback()
            except Exception:
                pass
            raise
    finally:
        _PROFUNDIDADE.pop(chave, None)


# `ALTER TABLE <t> ADD COLUMN <c> ...;` -- a UNICA forma de DDL deste projeto que o
# SQLite nao sabe escrever de modo idempotente (nao existe ADD COLUMN IF NOT EXISTS;
# repetir levanta "duplicate column name"). Ver `_sem_alters_ja_aplicados`.
#
# ANCORADO NO INICIO DA LINHA (`(?m)^[ \t]*`): comando SQL comeca linha neste projeto,
# e mencao a ALTER no meio de um texto NAO e' comando. Junto com a mascara de
# comentarios abaixo, sao as duas guardas que impedem a regex de "executar" prosa.
_ALTER_ADD = re.compile(
    r"(?m)^[ \t]*ALTER\s+TABLE\s+[\"'`\[]?(\w+)[\"'`\]]?\s+ADD\s+(?:COLUMN\s+)?"
    r"[\"'`\[]?(\w+)[\"'`\]]?[^;]*;",
    re.IGNORECASE)

_COMENTARIO = re.compile(r"--[^\n]*")


def _mascarar_comentarios(sql: str) -> str:
    """Copia do script com cada comentario `--` trocado por espacos do MESMO tamanho.

    Preserva os offsets de todo o resto: um casamento nesta copia aponta para
    exatamente o mesmo trecho do original, o que permite recortar do original sem
    nunca reescrever o SQL que vai rodar (comentario de migracao e' documentacao de
    decisao -- ele continua no script inteiro).
    """
    return _COMENTARIO.sub(lambda m: " " * len(m.group(0)), sql)


def _sem_alters_ja_aplicados(conn: sqlite3.Connection, sql: str) -> str:
    """Remove do script os ADD COLUMN cuja coluna JA existe (PRAGMA table_info).

    E' o mecanismo minimo que falta ao SQLite para cumprir a convencao de migracao
    idempotente deste projeto (ver `migrate`). O resto do DDL se resolve sozinho com
    IF NOT EXISTS / INSERT OR IGNORE; ADD COLUMN nao tem essa forma, entao a guarda
    mora aqui, no runner, e nao copiada em cada migracao.

    Casar por regex e' aceitavel porque o universo e' fechado e versionado: as
    migracoes sao arquivos deste repositorio, revisados, nao SQL de terceiro. O que
    NAO e' aceitavel e' casar dentro de COMENTARIO: as migracoes desta casa explicam
    no cabecalho o que fizeram, e citar um `ALTER TABLE ... ADD COLUMN` ja aplicado e'
    documentacao normal. Como o `[^;]*;` atravessa linhas, esse casamento comecava no
    meio da prosa e terminava no `;` do PROXIMO comando de verdade -- se a coluna
    citada existisse, a guarda apagava o comando junto, em silencio, e a migracao era
    registrada como aplicada com o DDL que nunca rodou. Por isso o casamento acontece
    sobre a copia mascarada, e o recorte, por indice, sobre o original.
    """
    fora: list[tuple[int, int]] = []
    for m in _ALTER_ADD.finditer(_mascarar_comentarios(sql)):
        tabela, coluna = m.group(1), m.group(2)
        colunas = {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}
        # Tabela inexistente devolve zero linhas: nesse caso o ALTER tem que RODAR
        # (e falhar alto), porque migracao que altera tabela que nao existe e' bug.
        if coluna in colunas:
            fora.append(m.span())
    if not fora:
        return sql
    partes = []
    anterior = 0
    for inicio, fim in fora:
        partes.append(sql[anterior:inicio])
        anterior = fim
    partes.append(sql[anterior:])
    return "".join(partes)


def migrate(conn: sqlite3.Connection) -> None:
    # CONVENCAO: migracoes devem ser idempotentes (IF NOT EXISTS) -- executescript
    # nao e transacional (faz COMMIT implicito antes do INSERT em schema_migrations),
    # entao uma falha no meio deixa o schema aplicado sem registro e a proxima
    # execucao reaplica o arquivo inteiro. ADD COLUMN e' a excecao que o SQLite nao
    # sabe escrever assim: `_sem_alters_ja_aplicados` cuida dela antes do script rodar.
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (nome TEXT PRIMARY KEY)")
    aplicadas = {r[0] for r in conn.execute("SELECT nome FROM schema_migrations")}
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if sql_file.name not in aplicadas:
            sql = _sem_alters_ja_aplicados(conn, sql_file.read_text(encoding="utf-8"))
            try:
                conn.executescript(sql)
            except BaseException:
                # Migracao com BEGIN proprio (042) que falha no meio deixa a transacao aberta: desfaz antes de
                # religar as FK, porque PRAGMA foreign_keys dentro de transacao e' ignorado pelo SQLite.
                if conn.in_transaction:
                    conn.rollback()
                raise
            finally:
                # Uma migracao que reconstroi tabela (020) desliga foreign_keys no comeco do
                # script e religa no fim; se falhar no meio, a conexao nao pode seguir sem FK.
                conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("INSERT INTO schema_migrations (nome) VALUES (?)", (sql_file.name,))
    conn.commit()
