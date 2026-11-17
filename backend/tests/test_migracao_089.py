"""Migracao 089 (issue #755, docs/adr/0006): marca da nota e do titulo excluidos no RM. So' acrescenta."""
import contextlib

import pytest

from app import db
from tests.test_db import _aplicar, _banco_antes_de

pytestmark = pytest.mark.migracao_real

ARQUIVO = "089_excluidos_no_rm.sql"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def _semear(conn):
    conn.execute("INSERT INTO notas_fiscais (id, coligada, idmov, numero, numero_int, emissao, valor_centavos, situacao) "
                 "VALUES (5, 1, 901, '901', 901, '2026-07-01', 100001, 'ativa')")
    conn.execute("INSERT INTO baixas (id, coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                 "status_lan, data_baixa) VALUES (8, 1, 77, 5, 901, 92001, 92001, 1, '2026-08-01')")
    conn.commit()


def test_089_nota_e_titulo_existentes_nascem_sem_a_marca_e_nada_mais_muda(tmp_path, monkeypatch):
    """Como na producao: nota e titulo ja' existem quando a 089 chega. Nenhum nasce marcado (a migracao nao decide
    quem foi excluido: so' a sincronizacao marca), nenhuma outra coluna muda e nenhuma linha some."""
    conn, pasta = _banco_antes_de(ARQUIVO, tmp_path, monkeypatch)
    with contextlib.closing(conn):
        for tabela in ("notas_fiscais", "baixas"):
            assert "excluida_rm_em" not in [r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")]
        assert "exclusao_aviso" not in [r[1] for r in conn.execute("PRAGMA table_info(rm_sincronizacoes)")]
        conn.execute("INSERT INTO rm_sincronizacoes (id, disparo, estado, nfs, baixas) VALUES (3, 'agendado', 'success', 2, 4)")
        _semear(conn)
        antes = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in ("notas_fiscais", "baixas")}
        _aplicar(conn, pasta, ARQUIVO)
        for tabela, linhas in antes.items():
            depois = [dict(r) for r in conn.execute(f"SELECT * FROM {tabela}")]
            assert [d.pop("excluida_rm_em") for d in depois] == [None] * len(linhas)
            assert depois == linhas and len(depois) == 1
        assert tuple(conn.execute("SELECT id, estado, nfs, baixas, exclusao_aviso FROM rm_sincronizacoes").fetchone()) == (
            3, "success", 2, 4, None)


def test_089_reexecutavel_sem_perder_a_marca(conn):
    _semear(conn)
    conn.execute("UPDATE notas_fiscais SET excluida_rm_em='2026-11-10 12:00:00', situacao='cancelada'")
    conn.execute("UPDATE baixas SET excluida_rm_em='2026-11-10 12:00:00'")
    conn.execute("DELETE FROM schema_migrations WHERE nome=?", (ARQUIVO,))
    conn.commit()
    db.migrate(conn)
    for tabela in ("notas_fiscais", "baixas"):
        assert [r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")].count("excluida_rm_em") == 1
        assert conn.execute(f"SELECT excluida_rm_em FROM {tabela}").fetchone()[0] == "2026-11-10 12:00:00"
    assert tuple(conn.execute("SELECT valor_baixado_centavos, status_lan FROM baixas").fetchone()) == (92001, 1)
