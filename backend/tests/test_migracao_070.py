"""Migracao 070 (issue #290): o pedido congelado no evento do boletim e as leituras da capa. So' acrescenta: os
eventos de atesto ja' gravados ficam com o pedido NULL (a linha do tempo nao inventa pedido nem diferenca)."""
import pytest

from app import db

pytestmark = pytest.mark.migracao_real

MIGRACAO = "070_boletim_pedido_e_leituras.sql"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn()
    original = db.MIGRATIONS_DIR
    monkeypatch.setattr(db, "MIGRATIONS_DIR", tmp_path / "migracoes")
    db.MIGRATIONS_DIR.mkdir()
    for f in sorted(original.glob("*.sql")):
        if f.name < MIGRACAO:
            (db.MIGRATIONS_DIR / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    db.migrate(c)
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
              "VALUES ('SINFRA', 'IC 1/2026', 'Obra A', 'obra', 100)")
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, valor_protocolado_centavos) "
              "VALUES (1, 1, 'execucao', '2026-01', 100_01)")
    c.execute("INSERT INTO medicao_atestos (medicao_id, valor_centavos, origem, atestado_em) "
              "VALUES (1, 99_99, 'manual', '2026-02-10')")
    c.commit()
    (db.MIGRATIONS_DIR / MIGRACAO).write_text((original / MIGRACAO).read_text(encoding="utf-8"), encoding="utf-8")
    db.migrate(c)
    yield c
    c.close()


def test_070_acrescenta_o_pedido_nulo_nos_eventos_antigos_e_a_tabela_de_leituras(conn):
    assert [tuple(r) for r in conn.execute("SELECT valor_centavos, pedido_centavos FROM medicao_atestos")] == [
        (99_99, None)]
    assert conn.execute("SELECT COUNT(*) FROM medicao_boletim_leituras").fetchone()[0] == 0


def test_070_vem_depois_da_069_do_master_e_a_leitura_nao_duplica(conn):
    nomes = [r[0] for r in conn.execute("SELECT nome FROM schema_migrations ORDER BY rowid")]
    assert nomes.index("069_medicao_grupos_selada.sql") < nomes.index(MIGRACAO)
    for _ in range(2):
        conn.execute("INSERT OR IGNORE INTO medicao_boletim_leituras (medicao_id, sha256, numero_orgao, data, "
                     "valor_centavos) VALUES (1, 'a', '1', '2026-02-10', 99_99)")
    assert conn.execute("SELECT COUNT(*) FROM medicao_boletim_leituras").fetchone()[0] == 1


def test_070_reaplicada_nao_quebra(conn):
    conn.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,))
    conn.commit()
    db.migrate(conn)
    assert "pedido_centavos" in {r[1] for r in conn.execute("PRAGMA table_info(medicao_atestos)")}
