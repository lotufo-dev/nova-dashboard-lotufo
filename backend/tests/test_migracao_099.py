"""Migracao 099 (fatia 2 da #906): o corte e os descartes das licitacoes. So' acrescenta."""
import sqlite3

import pytest

from app import db

pytestmark = pytest.mark.migracao_real

MIGRACAO = "099_licitacoes_decisoes.sql"
CHAVE = "11444777000161-1-000001/2026"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def test_099_o_estado_tem_uma_linha_so_sem_corte(conn):
    assert [tuple(r) for r in conn.execute("SELECT id, corte_em, corte_por FROM lic_estado")] == [(1, None, None)]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO lic_estado (id) VALUES (2)")


def test_099_um_descarte_ativo_por_chave_e_motivo_da_lista(conn):
    conn.execute("INSERT INTO lic_descartes (chave, motivo) VALUES (?, 'órgão')", (CHAVE,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO lic_descartes (chave, motivo) VALUES (?, 'valor')", (CHAVE,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO lic_descartes (chave, motivo) VALUES ('outra', 'caro')")
    conn.execute("UPDATE lic_descartes SET desfeito_em='2026-11-24 12:00:00' WHERE chave=?", (CHAVE,))
    conn.execute("INSERT INTO lic_descartes (chave, motivo) VALUES (?, 'valor')", (CHAVE,))         # o desfeito fica
    assert conn.execute("SELECT COUNT(*) FROM lic_descartes").fetchone()[0] == 2


def test_099_roda_duas_vezes_sem_mexer_no_que_existe(conn):
    conn.execute("INSERT INTO lic_favoritas (chave, desde, mudancas_vistas_ate) VALUES (?, '2026-11-12', '2026-11-20')",
                 (CHAVE,))
    conn.execute("UPDATE lic_estado SET corte_em='2026-11-24 15:00:00'")
    conn.execute("INSERT INTO lic_descartes (chave, motivo) VALUES (?, 'local')", (CHAVE,))
    conn.commit()
    tabelas = ("lic_estado", "lic_descartes", "lic_favoritas")
    antes = [[tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in tabelas]
    for _ in range(2):
        conn.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); conn.commit()
        db.migrate(conn)
    assert [[tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")] for t in tabelas] == antes
