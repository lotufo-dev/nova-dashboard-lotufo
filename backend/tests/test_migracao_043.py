"""Migracao 043 (issue #270): tabelas e colunas do motor de apostilamento (spec 2026-10-20, secao 2.2).
So' acrescenta; `reajuste_previsoes` e' evento (nao se altera nem se apaga)."""
import sqlite3

import pytest

from app import db

# Exercita a propria migracao: parte de um banco vazio de verdade, sem o banco-modelo do conftest.
pytestmark = pytest.mark.migracao_real

MIGRACAO = "043_reajuste_previsoes.sql"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
              "VALUES ('MTPAR', '099/2024', 'Obra Alfa', 'obra', 100)")
    c.commit()
    yield c
    c.close()


def _colunas(c, tabela):
    return {r[1] for r in c.execute(f"PRAGMA table_info({tabela})")}


def _previsao(c, valor=1_234_57, origem="manual", **extra):
    campos = {"contrato_id": 1, "data_base_mes": "2024-06", "ciclo": 2026, "competencia": "2026-07",
              "valor_previsto_centavos": valor, "origem": origem}
    campos.update(extra)
    c.execute(f"INSERT INTO reajuste_previsoes ({', '.join(campos)}) VALUES ({', '.join('?' * len(campos))})",
              tuple(campos.values()))
    c.commit()
    return c.execute("SELECT MAX(id) FROM reajuste_previsoes").fetchone()[0]


def test_043_cria_tabela_e_colunas(conn):
    assert {"id", "contrato_id", "data_base_mes", "ciclo", "competencia", "valor_previsto_centavos", "origem",
            "pleito_id", "instrumento_id", "usuario_id", "criado_em"} <= _colunas(conn, "reajuste_previsoes")
    assert {"data_base_mes", "ciclo"} <= _colunas(conn, "medicoes")
    assert {"reemite_pleito_id", "instrumento_chave"} <= _colunas(conn, "pleitos")


def test_043_roda_duas_vezes_sem_erro_e_sem_mexer_no_que_existe(conn):
    _previsao(conn, 1_000_01)
    conn.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo, reemite_pleito_id, "
                 "instrumento_chave) VALUES (1, 'reajuste', '2024-06', 2026, NULL, 'apostilamento-1')")
    conn.commit()
    antes = ([tuple(r) for r in conn.execute("SELECT * FROM reajuste_previsoes ORDER BY id")],
             [tuple(r) for r in conn.execute("SELECT * FROM pleitos ORDER BY id")])
    for _ in range(2):
        conn.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); conn.commit()
        db.migrate(conn)
    depois = ([tuple(r) for r in conn.execute("SELECT * FROM reajuste_previsoes ORDER BY id")],
              [tuple(r) for r in conn.execute("SELECT * FROM pleitos ORDER BY id")])
    assert depois == antes
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE nome=?", (MIGRACAO,)).fetchone()[0] == 1


def test_043_previsao_e_evento_update_e_delete_recusados(conn):
    pid = _previsao(conn, 1_234_57)
    with pytest.raises(sqlite3.IntegrityError, match="não se altera"):
        conn.execute("UPDATE reajuste_previsoes SET valor_previsto_centavos=1 WHERE id=?", (pid,))
    with pytest.raises(sqlite3.IntegrityError, match="não se apaga"):
        conn.execute("DELETE FROM reajuste_previsoes WHERE id=?", (pid,))
    conn.rollback()
    assert conn.execute("SELECT valor_previsto_centavos FROM reajuste_previsoes WHERE id=?",
                        (pid,)).fetchone()[0] == 1_234_57


def test_043_recusa_origem_desconhecida_valor_nao_inteiro_e_origem_sem_fonte(conn):
    with pytest.raises(sqlite3.IntegrityError):
        _previsao(conn, origem="planilha")
    with pytest.raises(sqlite3.IntegrityError):
        _previsao(conn, valor=12.5)
    with pytest.raises(sqlite3.IntegrityError):
        _previsao(conn, origem="pleito")            # previsao do pleito sem apontar o pleito
    with pytest.raises(sqlite3.IntegrityError):
        _previsao(conn, origem="apostilamento")     # previsao do apostilamento sem apontar o instrumento
    for mes in ("07/2026", "2026-00", "2026-13", "2026-19"):
        with pytest.raises(sqlite3.IntegrityError):
            _previsao(conn, competencia=mes)
    with pytest.raises(sqlite3.IntegrityError):
        _previsao(conn, data_base_mes="2024-13")


def test_043_fonte_tem_que_ser_do_mesmo_contrato(conn):
    conn.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
                 "VALUES ('MTPAR', '100/2024', 'Obra Beta', 'obra', 100)")
    conn.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo) VALUES (2, 'reajuste', '2024-06', 2026)")
    conn.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) "
                 "VALUES (2, 'ap-1', 'apostilamento_reajuste', '2026-09-15', '{}')")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="outro contrato"):
        _previsao(conn, origem="pleito", pleito_id=1)
    with pytest.raises(sqlite3.IntegrityError, match="outro contrato"):
        _previsao(conn, origem="apostilamento", instrumento_id=1)
    conn.rollback()
    assert _previsao(conn, origem="pleito", contrato_id=2, pleito_id=1)
    assert _previsao(conn, origem="apostilamento", contrato_id=2, instrumento_id=1)
