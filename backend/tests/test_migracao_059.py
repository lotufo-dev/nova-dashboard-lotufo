"""Migracao 059 (issue #409): `aditivos.corrige_chave` guarda o instrumento que o aditivo corrige. So' acrescenta: os
aditivos do cadastro ja' aplicados recebem a chave da observacao que o aplicar escreveu ("Corrige ta-01")."""
import pytest

from app import db

pytestmark = pytest.mark.migracao_real

MIGRACAO = "059_aditivo_corrige.sql"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
              "VALUES ('SES', '001/2021', 'Obra Alfa', 'obra', 100)")
    linhas = [("ta-01", None), ("ta-02", "Corrige ta-01"), ("carga-legado", "Corrige ta-01"),
              (None, "Corrige ta-01"), ("ta-03", "corrige ta-02 (digitado)")]
    c.executemany("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, "
                  "chave_cadastro, observacao, natureza) VALUES (1, 'valor', 100_01, 'assinado', '2025-11-20', ?, ?, "
                  "'reajuste')", linhas)
    c.execute("UPDATE aditivos SET corrige_chave = NULL")
    c.commit()
    yield c
    c.close()


def _reaplicar(conn):
    conn.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); conn.commit()
    db.migrate(conn)


def _corrige(conn):
    return [tuple(r) for r in conn.execute("SELECT chave_cadastro, corrige_chave FROM aditivos ORDER BY id")]


def test_aditivo_do_cadastro_recebe_a_chave_da_observacao_do_aplicar(conn):
    _reaplicar(conn)
    # so' o aditivo que o aplicar gravou com "Corrige <chave>": o da tela, o agregado do legado e a observacao
    # escrita de outro jeito ficam sem correcao
    assert _corrige(conn) == [("ta-01", None), ("ta-02", "ta-01"), ("carga-legado", None), (None, None),
                              ("ta-03", None)]


def test_reaplicar_a_migracao_nao_falha_nem_troca_o_gravado(conn):
    _reaplicar(conn)
    conn.execute("UPDATE aditivos SET corrige_chave='ta-09' WHERE chave_cadastro='ta-02'"); conn.commit()
    _reaplicar(conn)
    assert _corrige(conn)[1] == ("ta-02", "ta-09")
