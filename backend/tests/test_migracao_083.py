"""Migracao 083 (issue #663): categoria e complemento dos processos do SIGA. So' acrescenta."""
import pytest

from app import auth, db

pytestmark = pytest.mark.migracao_real


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def _base(conn):
    uid = auth.criar_usuario(conn, "Engenharia", "engenharia@exemplo.com.br", "senha-forte-123", "engenharia")
    conn.execute("INSERT INTO contratos (id, orgao, numero_instrumento, objeto, valor_original_centavos, nome_curto) "
                 "VALUES (7, 'ORGAO', 'IC 1/2026', 'Obra', 100, 'Obra Alfa')")
    conn.execute("INSERT INTO medicoes (id, contrato_id, numero, tipo, competencia, estado) "
                 "VALUES (31, 7, 3, 'execucao', '2026-09', 'protocolada')")
    return conn.execute("INSERT INTO protocolos (contrato_id, etapa, natureza, usuario_id, situacao) "
                        "VALUES (7, 'unico', 'execucao', ?, 'enviado')", (uid,)).lastrowid


def test_083_processo_novo_nasce_em_outros_sem_complemento_e_a_categoria_e_fechada(conn):
    conn.execute("INSERT INTO siga_processos (codigo, nome) VALUES ('ABC123', 'Processo Alfa')")
    assert tuple(conn.execute("SELECT nome, categoria, complemento FROM siga_processos").fetchone()) == (
        "Processo Alfa", "outros", None)
    with pytest.raises(Exception, match="CHECK"):
        conn.execute("UPDATE siga_processos SET categoria='contratos'")


def test_083_existente_ligado_a_medicao_ou_protocolo_fica_em_medicoes_e_reexecutar_nao_muda_o_resto(conn):
    protocolo = _base(conn)
    conn.execute("INSERT INTO siga_processos (codigo, nome, contrato_id, medicao_id) VALUES ('MED111', 'A', 7, 31)")
    conn.execute("INSERT INTO siga_processos (codigo, nome, contrato_id, protocolo_id) VALUES ('PRO222', 'B', 7, ?)",
                 (protocolo,))
    conn.execute("INSERT INTO siga_processos (codigo, nome, contrato_id) VALUES ('AVU333', 'C', 7)")
    conn.execute("INSERT INTO siga_processos (codigo, nome, contrato_id, categoria, complemento) "
                 "VALUES ('ADI444', 'D', 7, 'aditivos', 'de prazo')")
    colunas_antigas = "codigo, numero, nome, contrato_id, protocolo_id, medicao_id, criado_em"
    antes = [tuple(r) for r in conn.execute(f"SELECT {colunas_antigas} FROM siga_processos ORDER BY id")]
    # como na producao: os existentes chegam a' migracao com o valor padrao da categoria
    conn.execute("DELETE FROM schema_migrations WHERE nome='083_siga_categorias.sql'")
    conn.commit()
    db.migrate(conn)
    colunas = [r[1] for r in conn.execute("PRAGMA table_info(siga_processos)")]
    assert colunas.count("categoria") == 1 and colunas.count("complemento") == 1
    assert [tuple(r) for r in conn.execute("SELECT codigo, categoria, complemento FROM siga_processos ORDER BY id")] == [
        ("MED111", "medicoes", None), ("PRO222", "medicoes", None), ("AVU333", "outros", None),
        ("ADI444", "aditivos", "de prazo")]
    assert [tuple(r) for r in conn.execute(f"SELECT {colunas_antigas} FROM siga_processos ORDER BY id")] == antes
