"""Migracao 056 (issue #395): versao de cronograma superada pelo cadastro. So' acrescenta."""
import pytest

from app import db

pytestmark = pytest.mark.migracao_real


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def test_056_versao_existente_nasce_valendo(conn):
    cid = conn.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos) "
                       "VALUES ('SINFRA', 'IC 1/2026', 'Obra', 100)").lastrowid
    conn.execute("INSERT INTO cronograma_versoes (contrato_id, numero, origem) VALUES (?, 1, 'manual')", (cid,))
    assert conn.execute("SELECT superada_em FROM cronograma_versoes").fetchone()[0] is None


def test_056_reexecutavel(conn):
    conn.execute("DELETE FROM schema_migrations WHERE nome='056_cronograma_superada.sql'")
    conn.commit()
    db.migrate(conn)
    colunas = [r[1] for r in conn.execute("PRAGMA table_info(cronograma_versoes)")]
    assert colunas.count("superada_em") == 1
