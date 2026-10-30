"""Migracao 054 (issue #283): etapa do registro de protocolo da medicao. So' acrescenta."""
import sqlite3

import pytest

from app import db

pytestmark = pytest.mark.migracao_real


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def _medicao(conn):
    cid = conn.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos) "
                       "VALUES ('SINFRA', 'IC 1/2026', 'Obra', 100)").lastrowid
    return conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia) VALUES (?, 1, 'execucao', "
                        "'2026-07')", (cid,)).lastrowid


def test_054_linha_existente_e_de_nota_e_a_planilha_tem_uma_por_medicao(conn):
    mid = _medicao(conn)
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, '2026-08-03', 'manual')", (mid,))
    assert conn.execute("SELECT etapa FROM medicao_protocolos").fetchone()[0] == "nota"
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem, etapa) VALUES (?, '2026-08-03', 'manual', "
                 "'planilha')", (mid,))
    with pytest.raises(sqlite3.IntegrityError):       # segunda linha da planilha da mesma medicao
        conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem, etapa) VALUES (?, '2026-08-04', "
                     "'manual', 'planilha')", (mid,))
    with pytest.raises(sqlite3.IntegrityError):       # etapa fora da lista
        conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem, etapa) VALUES (?, '2026-08-03', "
                     "'manual', 'outra')", (mid,))


def test_054_reexecutavel(conn):
    db.migrate(conn)
    db.migrate(conn)
    colunas = [r[1] for r in conn.execute("PRAGMA table_info(medicao_protocolos)")]
    assert colunas.count("etapa") == 1
