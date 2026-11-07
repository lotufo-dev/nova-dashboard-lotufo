"""Migracao 060 (issue #278): os apostilamentos que o pacote montado cita. So' acrescenta."""
import pytest

from app import db

pytestmark = pytest.mark.migracao_real


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def test_060_protocolo_existente_nasce_sem_o_mapa(conn):
    cid = conn.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos) "
                       "VALUES ('MTPAR', '099/2024', 'Obra', 100)").lastrowid
    uid = conn.execute("INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES ('U', 'u@l.com', 'x', 'admin')"
                       ).lastrowid
    conn.execute("INSERT INTO protocolos (contrato_id, etapa, natureza, usuario_id) VALUES (?, 'unico', 'reajuste', ?)",
                 (cid, uid))
    assert conn.execute("SELECT montado_apostilamentos FROM protocolos").fetchone()[0] is None


def test_060_reexecutavel(conn):
    conn.execute("DELETE FROM schema_migrations WHERE nome='060_protocolo_montado_apostilamentos.sql'")
    conn.commit()
    db.migrate(conn)
    colunas = [r[1] for r in conn.execute("PRAGMA table_info(protocolos)")]
    assert colunas.count("montado_apostilamentos") == 1
