"""Migracao 081 (issue #638): marca da nota desconsiderada. So' acrescenta."""
import pytest

from app import db

pytestmark = pytest.mark.migracao_real


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def test_081_nota_existente_nasce_sem_a_marca_e_continua_lendo(conn):
    conn.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, emissao, valor_centavos, situacao) "
                 "VALUES (1, 901, '901', 901, '2026-07-01', 100001, 'ativa')")
    r = conn.execute("SELECT numero, valor_centavos, situacao, desconsiderada_em FROM notas_fiscais").fetchone()
    assert tuple(r) == ("901", 100_001, "ativa", None)


def test_081_reexecutavel_sem_perder_a_marca(conn):
    conn.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, emissao, valor_centavos, situacao, "
                 "desconsiderada_em) VALUES (1, 902, '902', 902, '2026-07-01', 100001, 'cancelada', '2026-11-10 12:00:00')")
    conn.execute("DELETE FROM schema_migrations WHERE nome='081_nota_desconsiderada.sql'")
    conn.commit()
    db.migrate(conn)
    colunas = [r[1] for r in conn.execute("PRAGMA table_info(notas_fiscais)")]
    assert colunas.count("desconsiderada_em") == 1
    assert conn.execute("SELECT desconsiderada_em FROM notas_fiscais").fetchone()[0] == "2026-11-10 12:00:00"
