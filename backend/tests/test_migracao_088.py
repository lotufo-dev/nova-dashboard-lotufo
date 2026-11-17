"""Migracao 088 (docs/adr/0015): tipos de movimento do RM que so' numa obra sao cobranca ao orgao. So' acrescenta."""
import contextlib

import pytest

from app import cobranca_orgao, db
from tests.test_db import _aplicar, _banco_antes_de

pytestmark = pytest.mark.migracao_real

ARQUIVO = "088_tipos_cobranca_extras_rm.sql"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def _contrato(conn, cid, instrumento):
    conn.execute("INSERT INTO contratos (id, orgao, numero_instrumento, objeto, valor_original_centavos, nome_curto) "
                 "VALUES (?, 'SECRETARIA DE EXEMPLO', ?, 'Obra', 100000001, ?)", (cid, instrumento, f"Obra {cid}"))


def test_088_contrato_existente_fica_sem_tipo_extra_e_com_os_outros_campos_iguais(tmp_path, monkeypatch):
    """Como na producao: o contrato ja' existe quando a 088 chega. Nasce sem tipo extra (vale so' a lista geral) e
    nenhuma outra coluna dele muda."""
    conn, pasta = _banco_antes_de(ARQUIVO, tmp_path, monkeypatch)
    with contextlib.closing(conn):
        assert "tipos_cobranca_extras_rm" not in [r[1] for r in conn.execute("PRAGMA table_info(contratos)")]
        _contrato(conn, 7, "001/2025/00/00-EXEMPLO")
        conn.execute("UPDATE contratos SET centro_custo_rm='9.001.001', "
                     "passos_medicao='[\"espelhos\",\"notas\",\"pagamento\"]' WHERE id=7")
        conn.commit()
        antes = dict(conn.execute("SELECT * FROM contratos WHERE id=7").fetchone())
        _aplicar(conn, pasta, ARQUIVO)
        depois = dict(conn.execute("SELECT * FROM contratos WHERE id=7").fetchone())
        assert depois.pop("tipos_cobranca_extras_rm") is None
        assert depois == antes
        assert conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0] == 1
        assert cobranca_orgao.extras_por_contrato(conn) == {}


def test_088_reexecutavel_sem_perder_o_que_o_cadastro_gravou(conn):
    _contrato(conn, 7, "001/2025/00/00-EXEMPLO")
    _contrato(conn, 8, "002/2025/00/00-EXEMPLO")
    conn.execute("UPDATE contratos SET tipos_cobranca_extras_rm='[\"2.2.03\"]' WHERE id=8")
    conn.execute("DELETE FROM schema_migrations WHERE nome=?", (ARQUIVO,))
    conn.commit()
    db.migrate(conn)
    colunas = [r[1] for r in conn.execute("PRAGMA table_info(contratos)")]
    assert colunas.count("tipos_cobranca_extras_rm") == 1
    assert [tuple(r) for r in conn.execute("SELECT id, tipos_cobranca_extras_rm FROM contratos ORDER BY id")] == [
        (7, None), (8, '["2.2.03"]')]
    assert cobranca_orgao.extras_por_contrato(conn) == {8: frozenset({"2.2.03"})}
