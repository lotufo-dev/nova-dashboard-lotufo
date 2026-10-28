"""Migracao 051 (issue #327): tabelas das leituras do monitor do SIGA. So' acrescenta."""
import sqlite3

import pytest

from app import db

pytestmark = pytest.mark.migracao_real

MIGRACAO = "051_siga.sql"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def _tabelas(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_051_cria_as_tres_tabelas(conn):
    assert {"siga_processos", "siga_leituras", "siga_movimentacoes"} <= _tabelas(conn)
    pid = conn.execute("INSERT INTO siga_processos (codigo, nome) VALUES ('ABC123', 'Processo Alfa')").lastrowid
    conn.execute("INSERT INTO siga_movimentacoes (processo_id, data, evento) VALUES (?, '2026-10-01 09:00:00', "
                 "'Recebimento')", (pid,))
    with pytest.raises(sqlite3.IntegrityError):       # a linha inteira repetida nao entra
        conn.execute("INSERT INTO siga_movimentacoes (processo_id, data, evento) VALUES (?, '2026-10-01 09:00:00', "
                     "'Recebimento')", (pid,))
    conn.execute("INSERT INTO siga_leituras (processo_id, lido_em, situacao) VALUES (?, '2026-10-01 12:00:00', 'x')",
                 (pid,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO siga_leituras (processo_id, lido_em, situacao) VALUES (?, '2026-10-01 12:00:00', "
                     "'x')", (pid,))
    with pytest.raises(sqlite3.IntegrityError):       # sem codigo e sem numero nao se identifica
        conn.execute("INSERT INTO siga_processos (nome) VALUES ('sem nada')")


def test_051_roda_duas_vezes_sem_mexer_no_que_existe(conn):
    conn.execute("INSERT INTO siga_processos (numero, nome) VALUES ('ORGAO-PRO-2026/00001', 'Processo Beta')")
    conn.commit()
    antes = [tuple(r) for r in conn.execute("SELECT * FROM siga_processos ORDER BY id")]
    for _ in range(2):
        conn.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); conn.commit()
        db.migrate(conn)
    assert [tuple(r) for r in conn.execute("SELECT * FROM siga_processos ORDER BY id")] == antes
