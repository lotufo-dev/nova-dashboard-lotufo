"""Migracao 090 (docs/adr/0005): centro de custo da propria empresa no contrato de consorcio. So' acrescenta."""
import contextlib

import pytest

from app import db
from tests.test_db import _aplicar, _banco_antes_de

pytestmark = pytest.mark.migracao_real

ARQUIVO = "090_centro_custo_empresa_rm.sql"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def _contrato(conn, cid, instrumento):
    conn.execute("INSERT INTO contratos (id, orgao, numero_instrumento, objeto, valor_original_centavos, nome_curto) "
                 "VALUES (?, 'SECRETARIA DE EXEMPLO', ?, 'Obra', 100000001, ?)", (cid, instrumento, f"Obra {cid}"))


def test_090_contrato_existente_fica_sem_o_centro_da_empresa_e_com_os_outros_campos_iguais(tmp_path, monkeypatch):
    """Como na producao: o contrato ja' existe quando a 090 chega. Nasce sem o centro da empresa (a nota dela nao liga
    sozinha) e nenhuma outra coluna dele muda; nenhuma linha se perde."""
    conn, pasta = _banco_antes_de(ARQUIVO, tmp_path, monkeypatch)
    with contextlib.closing(conn):
        assert "centro_custo_empresa_rm" not in [r[1] for r in conn.execute("PRAGMA table_info(contratos)")]
        _contrato(conn, 7, "001/2025/00/00-EXEMPLO")
        _contrato(conn, 8, "002/2025/00/00-EXEMPLO")
        conn.execute("UPDATE contratos SET centro_custo_rm='9.001.001', tipos_cobranca_extras_rm='[\"2.2.03\"]' WHERE id=7")
        conn.commit()
        antes = [dict(r) for r in conn.execute("SELECT * FROM contratos ORDER BY id")]
        _aplicar(conn, pasta, ARQUIVO)
        depois = [dict(r) for r in conn.execute("SELECT * FROM contratos ORDER BY id")]
        assert [d.pop("centro_custo_empresa_rm") for d in depois] == [None, None]
        assert depois == antes and len(depois) == 2


def test_090_reexecutavel_sem_perder_o_que_o_cadastro_gravou(conn):
    _contrato(conn, 7, "001/2025/00/00-EXEMPLO")
    _contrato(conn, 8, "002/2025/00/00-EXEMPLO")
    conn.execute("UPDATE contratos SET centro_custo_empresa_rm='9.005.001' WHERE id=8")
    conn.execute("DELETE FROM schema_migrations WHERE nome=?", (ARQUIVO,))
    conn.commit()
    db.migrate(conn)
    colunas = [r[1] for r in conn.execute("PRAGMA table_info(contratos)")]
    assert colunas.count("centro_custo_empresa_rm") == 1
    assert [tuple(r) for r in conn.execute("SELECT id, centro_custo_empresa_rm FROM contratos ORDER BY id")] == [
        (7, None), (8, "9.005.001")]
