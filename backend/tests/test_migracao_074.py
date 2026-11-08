"""Migracao 074 (issue #588): alerta de seguranca que saiu sem registro marcado no banco. So' acrescenta."""
import pytest

from app import db

pytestmark = pytest.mark.migracao_real


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def test_074_linha_existente_nasce_sem_a_marca(conn):
    conn.execute("INSERT INTO alertas_seguranca_envios (chave, tipo, assunto) VALUES ('a', 'alerta', 'x')")
    assert conn.execute("SELECT envio_saiu_sem_registro_em FROM alertas_seguranca_envios").fetchone()[0] is None


def test_074_reexecutavel(conn):
    conn.execute("DELETE FROM schema_migrations WHERE nome='074_alertas_saiu_sem_registro.sql'")
    conn.commit()
    db.migrate(conn)
    colunas = [r[1] for r in conn.execute("PRAGMA table_info(alertas_seguranca_envios)")]
    assert colunas.count("envio_saiu_sem_registro_em") == 1
