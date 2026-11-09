"""Migracao 080 (issue #627): PDF e envio nas assinaturas e a tabela dos envios dos assinados. So' acrescenta."""
import pytest

from app import db

pytestmark = pytest.mark.migracao_real


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def _medicao(conn) -> int:
    conn.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos) "
                 "VALUES ('SINFRA', 'IC 1', 'x', 100)")
    cid = conn.execute("SELECT id FROM contratos").fetchone()[0]
    conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia) VALUES (?, 1, 'execucao', '2026-07')",
                 (cid,))
    return conn.execute("SELECT id FROM medicoes").fetchone()[0]


def test_080_assinatura_antiga_continua_lendo_sem_pdf(conn):
    mid = _medicao(conn)
    conn.execute("INSERT INTO medicao_assinaturas (medicao_id, envelope, assinado_em) VALUES (?, 'Boletim 1', "
                 "'2026-08-12')", (mid,))
    r = conn.execute("SELECT origem, envelope, arquivo, sha256, envio_id, envio_origem FROM medicao_assinaturas").fetchone()
    assert tuple(r) == ("manual", "Boletim 1", None, None, None, None)


def test_080_envio_origem_so_aceita_sistema_ou_externo(conn):
    import sqlite3
    mid = _medicao(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO medicao_assinaturas (medicao_id, assinado_em, envio_origem) VALUES (?, '2026-08-12', "
                     "'outro')", (mid,))


def test_080_envio_dos_assinados_nao_se_apaga(conn):
    import sqlite3
    mid = _medicao(conn)
    conn.execute("INSERT INTO medicao_assinados_envios (medicao_id, origem, assinado_em, arquivo, sha256, nome) "
                 "VALUES (?, 'externo', '2026-11-09', 'assinados/x.pdf', 'x', 'x.pdf')", (mid,))
    with pytest.raises(sqlite3.IntegrityError, match="não se apaga"):
        conn.execute("DELETE FROM medicao_assinados_envios")


def test_080_reexecutavel(conn):
    conn.execute("DELETE FROM schema_migrations WHERE nome='080_assinados.sql'")
    conn.commit()
    db.migrate(conn)
    colunas = [r[1] for r in conn.execute("PRAGMA table_info(medicao_assinaturas)")]
    assert [colunas.count(c) for c in ("arquivo", "sha256", "envio_id", "envio_origem", "assinados_envio_id")] == [1] * 5
