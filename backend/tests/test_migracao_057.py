"""Migracao 057 (issue #390, rodada 2 da PR #407): `aditivos.data_base_mes` e `aditivos.ciclo_reajuste` guardam a
data-base e o ciclo do aditivo de reajuste. So' acrescenta: os existentes ficam NULL e o aplicar preenche."""
import pytest

from app import db

pytestmark = pytest.mark.migracao_real

MIGRACAO = "057_aditivo_reajuste_ciclo.sql"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
              "VALUES ('SES', '001/2021', 'Obra Alfa', 'obra', 100)")
    c.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza) "
              "VALUES (1, 'valor', 100_01, 'assinado', '2025-11-20', 'reajuste')")
    c.commit()
    yield c
    c.close()


def test_colunas_novas_nulas_nos_aditivos_existentes(conn):
    r = conn.execute("SELECT data_base_mes, ciclo_reajuste, delta_valor_centavos FROM aditivos").fetchone()
    assert tuple(r) == (None, None, 100_01)


def test_reaplicar_a_migracao_nao_falha_nem_mexe_nos_dados(conn):
    conn.execute("UPDATE aditivos SET data_base_mes='2021-10', ciclo_reajuste=2025"); conn.commit()
    conn.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); conn.commit()
    db.migrate(conn)
    assert tuple(conn.execute("SELECT data_base_mes, ciclo_reajuste FROM aditivos").fetchone()) == ("2021-10", 2025)
