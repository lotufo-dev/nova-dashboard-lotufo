"""Migracao 100 (fatia 4 da #906): alertas, resultados, pares e conferencias das licitacoes. So' acrescenta."""
import sqlite3

import pytest

from app import db

pytestmark = pytest.mark.migracao_real

MIGRACAO = "100_licitacoes_fontes.sql"
A, B = "11444777000161-1-000001/2026", "12345678000195-1-000002/2026"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def test_100_a_leitura_nasce_sem_alerta_e_sem_resultado(conn):
    conn.execute("INSERT INTO lic_leituras (lido_em, certames) VALUES ('2026-11-24 13:05:00', 3)")
    assert tuple(conn.execute("SELECT alertas, resultados FROM lic_leituras").fetchone()) == ("[]", None)


def test_100_um_par_por_identidade_e_uma_conferencia_em_vigor_por_par(conn):
    conn.execute("INSERT INTO lic_pares (par, chave_a, chave_b) VALUES ('p1', ?, ?)", (A, B))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO lic_pares (par, chave_a, chave_b) VALUES ('p1', ?, ?)", (B, A))
    conn.execute("INSERT INTO lic_conferencias (par, chave_a, chave_b, resposta) VALUES ('p1', ?, ?, 'mesmo')", (A, B))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO lic_conferencias (par, chave_a, chave_b, resposta) VALUES ('p1', ?, ?, 'outro')", (A, B))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO lic_conferencias (par, chave_a, chave_b, resposta) VALUES ('p2', ?, ?, 'talvez')", (A, B))
    conn.execute("UPDATE lic_conferencias SET desfeita_em='2026-11-24 12:00:00' WHERE par='p1'")
    conn.execute("INSERT INTO lic_conferencias (par, chave_a, chave_b, resposta) VALUES ('p1', ?, ?, 'outro')", (A, B))
    assert conn.execute("SELECT COUNT(*) FROM lic_conferencias").fetchone()[0] == 2      # a refeita fica


def test_100_roda_duas_vezes_sem_mexer_no_que_existe(conn):
    conn.execute("INSERT INTO lic_leituras (lido_em, certames, alertas, resultados) VALUES ('2026-11-24 13:05:00', 3, "
                 "'[{\"regra\": \"r1\"}]', '{\"funil\": []}')")
    conn.execute("INSERT INTO lic_pares (par, chave_a, chave_b, motivo) VALUES ('p1', ?, ?, 'mesmo objeto')", (A, B))
    conn.execute("INSERT INTO lic_conferencias (par, chave_a, chave_b, resposta) VALUES ('p1', ?, ?, 'mesmo')", (A, B))
    conn.commit()
    tabelas = ("lic_leituras", "lic_pares", "lic_conferencias")
    antes = [[tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in tabelas]
    for _ in range(2):
        conn.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); conn.commit()
        db.migrate(conn)
    assert [[tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in tabelas] == antes
