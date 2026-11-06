"""Migracao 065 (issue #359): `espelho_medicoes.valor_centavos`, o valor de cada medicao no espelho. So' acrescenta:
as ligacoes dos espelhos ja' gerados ficam com NULL (o valor sai das entradas gravadas pela regra da obra)."""
import sqlite3

import pytest

from app import auth, db

pytestmark = pytest.mark.migracao_real

MIGRACAO = "065_espelho_medicoes_valor.sql"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn()
    # banco ate' a anterior: a 065 fica de fora
    original = db.MIGRATIONS_DIR
    monkeypatch.setattr(db, "MIGRATIONS_DIR", tmp_path / "migracoes")
    db.MIGRATIONS_DIR.mkdir()
    for f in sorted(original.glob("*.sql")):
        if f.name < MIGRACAO:
            (db.MIGRATIONS_DIR / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    db.migrate(c)
    assert "valor_centavos" not in {r[1] for r in c.execute("PRAGMA table_info(espelho_medicoes)")}
    uid = auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "admin")
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
              "VALUES ('SINFRA', 'IC 1/2026', 'Obra A', 'obra', 100)")
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
              "valor_protocolado_origem) VALUES (1, 23, 'execucao', '2026-01', 'espelho_enviado', 100_01, 'espelho')")
    c.execute("INSERT INTO espelhos (contrato_id, numero, competencia, versao, situacao, entradas, saidas, "
              "regra_sha256, criado_por) VALUES (1, 23, '2026-01', 1, 'vigente', '{\"medicao\": 10001}', '[]', 'a', ?)",
              (uid,))
    c.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id) VALUES (1, 1)")
    c.commit()
    (db.MIGRATIONS_DIR / MIGRACAO).write_text((original / MIGRACAO).read_text(encoding="utf-8"), encoding="utf-8")
    db.migrate(c)
    yield c
    c.close()


def test_coluna_nova_e_a_ligacao_antiga_fica_sem_valor(conn):
    assert "valor_centavos" in {r[1] for r in conn.execute("PRAGMA table_info(espelho_medicoes)")}
    assert [tuple(r) for r in conn.execute("SELECT espelho_id, medicao_id, valor_centavos FROM espelho_medicoes")] == [
        (1, 1, None)]


def test_reaplicar_nao_falha_nem_muda_nada(conn):
    conn.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); conn.commit()
    db.migrate(conn)
    assert [tuple(r) for r in conn.execute("SELECT espelho_id, medicao_id, valor_centavos FROM espelho_medicoes")] == [
        (1, 1, None)]


def test_valor_negativo_recusa(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE espelho_medicoes SET valor_centavos=-1")
