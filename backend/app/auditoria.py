import hashlib
import json
import sqlite3

from app import db

def _payload(usuario_id, acao, entidade, entidade_id, antes, depois, criado_em) -> str:
    return json.dumps([usuario_id, acao, entidade, entidade_id, antes, depois, criado_em],
                      ensure_ascii=False, sort_keys=True)

def registrar(conn: sqlite3.Connection, usuario_id, acao: str, entidade=None,
              entidade_id=None, antes: dict | None = None, depois: dict | None = None) -> None:
    # Normalizar ANTES de hashear e inserir: as colunas tem afinidade TEXT/INTEGER,
    # entao entidade_id=42 (int) e gravado como '42' e verificar_cadeia releria a
    # string, recomputando um hash diferente -- cadeia acusada de adulterada para
    # sempre. O hash tem que ser calculado sobre exatamente o que vai ao banco.
    usuario_id = None if usuario_id is None else int(usuario_id)
    entidade_id = None if entidade_id is None else str(entidade_id)

    # QUEM E' DONO DA TRANSACAO E' O CHAMADOR (db.mutacao). registrar() so escreve
    # a linha da cadeia -- nao abre e nao commita. Assim a mutacao de negocio e o
    # registro que a descreve entram no mesmo commit: uma falha entre os dois nao
    # deixa mais dado sem rastro (nem rastro sem dado).
    # Exigir o ENVELOPE (nao apenas `in_transaction`) e' fail-closed: ler o head e
    # inserir tem que ser atomico sob o BEGIN IMMEDIATE do chamador. Sem ele, duas
    # requisicoes concorrentes leriam o mesmo hash_prev e a cadeia forkaria para
    # sempre. A transacao implicita de um DML cru nao serve: ninguem e' dono dela e
    # ela pode ser commitada por qualquer um, a qualquer momento.
    if not db.em_mutacao(conn):
        raise RuntimeError("registrar() exige transação aberta — use db.mutacao(conn)")

    ultimo = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    hash_prev = ultimo["hash"] if ultimo else "genesis"
    criado_em = conn.execute("SELECT datetime('now')").fetchone()[0]
    antes_j = json.dumps(antes, ensure_ascii=False, sort_keys=True) if antes is not None else None
    depois_j = json.dumps(depois, ensure_ascii=False, sort_keys=True) if depois is not None else None
    corpo = _payload(usuario_id, acao, entidade, entidade_id, antes_j, depois_j, criado_em)
    h = hashlib.sha256((hash_prev + corpo).encode()).hexdigest()
    conn.execute(
        """INSERT INTO audit_log (usuario_id, acao, entidade, entidade_id, antes, depois,
           criado_em, hash_prev, hash) VALUES (?,?,?,?,?,?,?,?,?)""",
        (usuario_id, acao, entidade, entidade_id, antes_j, depois_j, criado_em, hash_prev, h))

# LIMITE CONHECIDO: truncagem do FIM da cadeia nao e detectavel dentro do mesmo
# banco (quem apaga linhas reescreve ancoras); a defesa e a copia periodica do log
# para destino independente (spec §5), implementada em fase posterior.
def verificar_cadeia(conn: sqlite3.Connection) -> bool:
    esperado = "genesis"
    for r in conn.execute("SELECT * FROM audit_log ORDER BY id"):
        if r["hash_prev"] != esperado:
            return False
        corpo = _payload(r["usuario_id"], r["acao"], r["entidade"], r["entidade_id"],
                         r["antes"], r["depois"], r["criado_em"])
        if hashlib.sha256((r["hash_prev"] + corpo).encode()).hexdigest() != r["hash"]:
            return False
        esperado = r["hash"]
    return True


def conferir_linha(conn: sqlite3.Connection, linha: int, hash_: str) -> bool:
    """Issue #424: a linha `linha` da auditoria tem o hash `hash_` (o do resumo diario, ancora fora da VM) e a cadeia
    do comeco ate' ela confere. Quem reescreve a auditoria inteira recalcula os hashes: o enviado deixa de existir."""
    esperado = "genesis"
    for r in conn.execute("SELECT * FROM audit_log WHERE id <= ? ORDER BY id", (linha,)):
        if r["hash_prev"] != esperado:
            return False
        corpo = _payload(r["usuario_id"], r["acao"], r["entidade"], r["entidade_id"],
                         r["antes"], r["depois"], r["criado_em"])
        if hashlib.sha256((r["hash_prev"] + corpo).encode()).hexdigest() != r["hash"]:
            return False
        esperado = r["hash"]
        if r["id"] == linha:
            return r["hash"] == hash_.strip().lower()
    return False
