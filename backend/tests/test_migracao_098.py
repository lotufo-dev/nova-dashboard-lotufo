"""Migracao 098 (issue #908): tabelas das licitacoes que o radar entrega. So' acrescenta."""
import sqlite3

import pytest

from app import db

pytestmark = pytest.mark.migracao_real

MIGRACAO = "098_licitacoes.sql"
CHAVE = "11444777000161-1-000001/2026"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def test_098_cria_as_tres_tabelas(conn):
    tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"lic_certames", "lic_leituras", "lic_favoritas"} <= tabelas
    conn.execute("INSERT INTO lic_certames (chave, resumo, dados) VALUES (?, 'aaaaaaaa', '{}')", (CHAVE,))
    with pytest.raises(sqlite3.IntegrityError):               # a chave e' a identidade do certame
        conn.execute("INSERT INTO lic_certames (chave, resumo, dados) VALUES (?, 'bbbbbbbb', '{}')", (CHAVE,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO lic_certames (chave, resumo, dados, encerrada) VALUES ('outra', 'c', '{}', 2)")
    conn.execute("INSERT INTO lic_leituras (lido_em, certames) VALUES ('2026-11-24 13:00:00', 1)")
    with pytest.raises(sqlite3.IntegrityError):               # a mesma rodada nao cria outra linha
        conn.execute("INSERT INTO lic_leituras (lido_em, certames) VALUES ('2026-11-24 13:00:00', 1)")


def test_098_uma_favorita_ativa_por_chave(conn):
    conn.execute("INSERT INTO lic_favoritas (chave, desde, etapa) VALUES (?, '2026-11-12', 'em_analise')", (CHAVE,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO lic_favoritas (chave, desde) VALUES (?, '2026-11-13')", (CHAVE,))
    with pytest.raises(sqlite3.IntegrityError):               # etapa fora da lista
        conn.execute("INSERT INTO lic_favoritas (chave, desde, etapa) VALUES ('outra', '2026-11-13', 'ganhamos')")
    conn.execute("UPDATE lic_favoritas SET removida_em='2026-11-20 12:00:00' WHERE chave=?", (CHAVE,))
    conn.execute("INSERT INTO lic_favoritas (chave, desde) VALUES (?, '2026-11-21')", (CHAVE,))    # a tirada fica
    assert conn.execute("SELECT COUNT(*) FROM lic_favoritas WHERE chave=?", (CHAVE,)).fetchone()[0] == 2


def test_098_roda_duas_vezes_sem_mexer_no_que_existe(conn):
    conn.execute("INSERT INTO lic_certames (chave, resumo, dados, nota) VALUES (?, 'aaaaaaaa', '{}', 7)", (CHAVE,))
    conn.execute("INSERT INTO lic_favoritas (chave, desde) VALUES (?, '2026-11-12')", (CHAVE,))
    conn.commit()
    antes = [[tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")]
             for t in ("lic_certames", "lic_leituras", "lic_favoritas")]
    for _ in range(2):
        conn.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); conn.commit()
        db.migrate(conn)
    assert [[tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")]
            for t in ("lic_certames", "lic_leituras", "lic_favoritas")] == antes
