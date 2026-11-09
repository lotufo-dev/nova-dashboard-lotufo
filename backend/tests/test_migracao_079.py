"""Migracao 079 (issue #613): titulos da planilha de cada grupo do cadastro de custo. So' acrescenta."""
import json

import pytest

from app import db

pytestmark = pytest.mark.migracao_real


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def test_079_grupo_existente_nasce_sem_titulos(conn):
    conn.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos) "
                 "VALUES ('SINFRA', 'IC 1', 'x', 100)")
    cid = conn.execute("SELECT id FROM contratos").fetchone()[0]
    conn.execute("INSERT INTO custo_grupos (contrato_id, ordem, nome, tarefas, itens_planilha) "
                 "VALUES (?, 1, 'Drenagem', '[]', '[\"3.\"]')", (cid,))
    assert json.loads(conn.execute("SELECT titulos_planilha FROM custo_grupos").fetchone()[0]) == []


def test_079_reexecutavel(conn):
    conn.execute("DELETE FROM schema_migrations WHERE nome='079_custo_titulos_planilha.sql'")
    conn.commit()
    db.migrate(conn)
    colunas = [r[1] for r in conn.execute("PRAGMA table_info(custo_grupos)")]
    assert colunas.count("titulos_planilha") == 1
