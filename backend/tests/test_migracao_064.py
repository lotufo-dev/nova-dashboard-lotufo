"""Migracao 064 (issue #462): `contratos.pecas_no_oficio`, NULL por padrao (segue o orgao), e reaplicar nao perde
o que ja' estava gravado."""
import pytest

from app import db

pytestmark = pytest.mark.migracao_real


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def test_064_acrescenta_a_coluna_nula_e_reaplicar_preserva(conn):
    sql = ("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos, nome_curto, "
           "pecas_no_oficio) VALUES ('Órgão', ?, 'Obra', 100, ?, ?)")
    conn.execute(sql, ("001/2026", "Obra A", None))
    conn.execute(sql, ("002/2026", "Obra B", "[]"))
    conn.commit()
    conn.execute("DELETE FROM schema_migrations WHERE nome='064_pecas_no_oficio.sql'"); conn.commit()
    db.migrate(conn)
    assert [tuple(r) for r in conn.execute("SELECT nome_curto, pecas_no_oficio FROM contratos ORDER BY id")] == \
        [("Obra A", None), ("Obra B", "[]")]
