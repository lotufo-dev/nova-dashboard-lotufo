"""Migracao 050 (issue #277): `pleitos.reemissao` diz se o pleito que reemite outro e' reiteracao ou cronograma.
So' acrescenta."""
import sqlite3

import pytest

from app import db

pytestmark = pytest.mark.migracao_real

MIGRACAO = "050_pleito_reemissao.sql"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
              "VALUES ('MTPAR', '099/2024', 'Obra Alfa', 'obra', 100)")
    c.commit()
    yield c
    c.close()


def test_050_cria_a_coluna_e_recusa_valor_fora_da_lista(conn):
    assert "reemissao" in {r[1] for r in conn.execute("PRAGMA table_info(pleitos)")}
    conn.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo, reemissao) "
                 "VALUES (1, 'reajuste', '2024-06', 2026, 'reiteracao')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo, reemissao) "
                     "VALUES (1, 'reajuste', '2024-06', 2026, 'outra')")


def test_050_roda_duas_vezes_sem_mexer_no_que_existe(conn):
    conn.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo, reemissao) "
                 "VALUES (1, 'reajuste', '2024-06', 2026, 'cronograma')")
    conn.commit()
    antes = [tuple(r) for r in conn.execute("SELECT * FROM pleitos ORDER BY id")]
    for _ in range(2):
        conn.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); conn.commit()
        db.migrate(conn)
    assert [tuple(r) for r in conn.execute("SELECT * FROM pleitos ORDER BY id")] == antes
