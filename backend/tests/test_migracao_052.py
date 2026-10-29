"""Migracao 052 (issue #342): pedidos de leitura do SIGA e rodadas do robo. So' acrescenta."""
import sqlite3

import pytest

from app import auth, db

pytestmark = pytest.mark.migracao_real

MIGRACAO = "052_siga_rodadas.sql"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def _tabelas(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_052_cria_as_duas_tabelas(conn):
    assert {"siga_pedidos", "siga_rodadas"} <= _tabelas(conn)
    uid = auth.criar_usuario(conn, "Engenharia", "engenharia@exemplo.com.br", "senha-forte-123", "engenharia")
    rid = conn.execute("INSERT INTO siga_rodadas (tipo, completa, processos, iniciada_em) "
                       "VALUES ('pedido', 0, '[]', '2026-10-29 14:00:00')").lastrowid
    conn.execute("INSERT INTO siga_pedidos (processo_id, usuario_id, pedido_em, rodada_id) "
                 "VALUES (NULL, ?, '2026-10-29 13:59:00', ?)", (uid, rid))
    with pytest.raises(sqlite3.IntegrityError):       # tipo fora da lista
        conn.execute("INSERT INTO siga_rodadas (tipo, completa, processos, iniciada_em) "
                     "VALUES ('outra', 0, '[]', '2026-10-29 14:00:00')")
    with pytest.raises(sqlite3.IntegrityError):       # rodada com falha e com nao lidos ao mesmo tempo
        conn.execute("INSERT INTO siga_rodadas (tipo, completa, processos, iniciada_em, terminada_em, falha, "
                     "nao_lidos) VALUES ('pedido', 0, '[]', '2026-10-29 14:00:00', '2026-10-29 14:01:00', 'caiu', '[]')")
    with pytest.raises(sqlite3.IntegrityError):       # pedido sem quem pediu
        conn.execute("INSERT INTO siga_pedidos (usuario_id, pedido_em) VALUES (NULL, '2026-10-29 14:00:00')")


def test_052_roda_duas_vezes_sem_mexer_no_que_existe(conn):
    uid = auth.criar_usuario(conn, "Engenharia", "engenharia@exemplo.com.br", "senha-forte-123", "engenharia")
    conn.execute("INSERT INTO siga_rodadas (tipo, completa, processos, iniciada_em) "
                 "VALUES ('automatica', 1, '[1]', '2026-10-29 14:00:00')")
    conn.execute("INSERT INTO siga_pedidos (usuario_id, pedido_em) VALUES (?, '2026-10-29 14:01:00')", (uid,))
    conn.commit()
    antes = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")]
             for t in ("siga_rodadas", "siga_pedidos")}
    for _ in range(2):
        conn.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); conn.commit()
        db.migrate(conn)
    assert {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")]
            for t in ("siga_rodadas", "siga_pedidos")} == antes
