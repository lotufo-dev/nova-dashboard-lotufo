"""Migracao 078 (issue #589): medicao de reajuste aceita valor negativo.

So' acrescenta. Reconstroi `medicoes` pelo CHECK do protocolado e do atestado (negativo so' no tipo reajuste), pela
receita da 042: preserva todas as linhas e colunas, pode rodar de novo e e' atomica. Acrescenta em
`espelho_medicoes` a coluna do valor com sinal.
"""
import shutil
import sqlite3

import pytest

from app import db

pytestmark = pytest.mark.migracao_real

ARQUIVO = "078_reajuste_negativo.sql"
ESTADOS = ("prevista", "planilha_gerada", "planilha_enviada", "boletim_recebido", "espelho_gerado",
           "espelho_enviado", "nota_emitida", "protocolada", "nf_emitida", "recebida", "cancelada", "desistida")


def _colunas(conn, tabela):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")]


@pytest.fixture
def antes_da_078(tmp_path, monkeypatch):
    """Banco "ate' a 077": roda todas as migracoes anteriores a 078, de uma copia da pasta."""
    pasta = tmp_path / "migracoes"
    pasta.mkdir()
    for f in db.MIGRATIONS_DIR.glob("*.sql"):
        if f.name < "078":
            shutil.copy(f, pasta / f.name)
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    original = db.MIGRATIONS_DIR
    monkeypatch.setattr(db, "MIGRATIONS_DIR", pasta)
    c = db.get_conn()
    db.migrate(c)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", original)
    yield c
    c.close()


def _semear(c):
    """Uma medicao em cada estado, de cada tipo, com as colunas preenchidas, e filhas (atesto, protocolo, espelho)."""
    c.execute("INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES ('U','u@l.com','x','engenharia')")
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos) "
              "VALUES ('SINFRA','X/2026','obra',100)")
    n = 0
    for tipo in ("execucao", "projeto", "reajuste"):
        for estado in ESTADOS:
            n += 1
            c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
                      "valor_protocolado_origem, valor_atestado_centavos, valor_atestado_origem, motivo_represamento, "
                      "congelada, atestado_em, periodo_inicio, periodo_fim, numero_orgao, data_base_mes, ciclo) "
                      "VALUES (1,?,?,'2026-05',?,?,'manual',?,'aceito','motivo',?,'2026-06-01','2026-05-01',"
                      "'2026-05-31',?,'2024-06',2026)",
                      (n, tipo, estado, 1_000_01 * n, 999_99 * n, n % 2, n))
    c.execute("INSERT INTO medicao_atestos (medicao_id, valor_centavos, origem, atestado_em, usuario_id) "
              "VALUES (2, 999_99, 'manual', '2026-06-01', 1)")
    c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (8,'2026-06-01','manual')")
    c.execute("INSERT INTO espelhos (contrato_id, numero, competencia, versao, situacao, entradas, saidas, regra_sha256, criado_por) "
              "VALUES (1, 5, '2026-05', 1, 'vigente', '{}', '[]', 'abc', 1)")
    c.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id, valor_centavos) VALUES (1, 5, 5_000_05)")
    c.commit()


def _foto(c, colunas):
    cols = ", ".join(colunas)
    return ([tuple(r) for r in c.execute(f"SELECT {cols} FROM medicoes ORDER BY id")],
            [tuple(r) for r in c.execute("SELECT id, medicao_id, valor_centavos FROM medicao_atestos ORDER BY id")],
            [tuple(r) for r in c.execute("SELECT id, medicao_id, data FROM medicao_protocolos ORDER BY id")],
            [tuple(r) for r in c.execute("SELECT espelho_id, medicao_id, valor_centavos FROM espelho_medicoes")])


def _rodar_script(c):
    sql = (db.MIGRATIONS_DIR / ARQUIVO).read_text(encoding="utf-8")
    c.executescript(db._sem_alters_ja_aplicados(c, sql))
    c.execute("PRAGMA foreign_keys=ON")


def _negativo(c, tipo, coluna):
    c.execute(f"INSERT INTO medicoes (contrato_id, numero, tipo, competencia, {coluna}) VALUES (1, 900, ?, '2026-05', -1)",
              (tipo,))


def test_078_roda_duas_vezes_preserva_as_medicoes_e_libera_o_negativo_so_no_reajuste(antes_da_078):
    c = antes_da_078
    _semear(c)
    de_hoje = _colunas(c, "medicoes")
    antes = _foto(c, de_hoje)
    # antes da 078 nem o reajuste aceitava negativo
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _negativo(c, "reajuste", "valor_protocolado_centavos")
    c.rollback()
    db.migrate(c)                                   # 1a vez, pelo runner
    assert _foto(c, de_hoje) == antes
    c.execute("DELETE FROM schema_migrations WHERE nome=?", (ARQUIVO,)); c.commit()
    db.migrate(c)                                   # 2a vez, inteira
    _rodar_script(c)                                # 3a vez, o script cru
    assert _foto(c, de_hoje) == antes
    assert _colunas(c, "medicoes") == de_hoje       # mesmas colunas, mesma ordem
    assert _colunas(c, "espelho_medicoes").count("valor_com_sinal_centavos") == 1
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    for filha in ("medicao_atestos", "medicao_protocolos", "envio_medicoes", "medicao_planilhas", "espelho_medicoes"):
        ddl = c.execute("SELECT sql FROM sqlite_master WHERE name=?", (filha,)).fetchone()[0]
        assert "REFERENCES medicoes(id)" in ddl and "medicoes_nova" not in ddl
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='medicoes_nova'").fetchone()[0] == 0
    # o reajuste aceita negativo no pedido e no aprovado; execucao e projeto continuam recusando
    for coluna in ("valor_protocolado_centavos", "valor_atestado_centavos"):
        _negativo(c, "reajuste", coluna)
        c.rollback()
        for tipo in ("execucao", "projeto"):
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                _negativo(c, tipo, coluna)
            c.rollback()
    # o valor com sinal do espelho grava o negativo; o da 065 continua recusando
    c.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id, valor_com_sinal_centavos) VALUES (1, 30, -10_01)")
    c.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        c.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id, valor_centavos) VALUES (1, 30, -10_01)")
    c.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia) VALUES (1,1,'execucao','2026-05')")


def test_078_falha_no_meio_nao_perde_medicoes(antes_da_078):
    """A reconstrucao e' uma transacao so': uma visao que le `medicoes` faz o RENAME falhar DEPOIS do DROP, e nada
    fica gravado."""
    c = antes_da_078
    _semear(c)
    de_hoje = _colunas(c, "medicoes")
    antes = _foto(c, de_hoje)
    c.execute("CREATE VIEW v_medicoes AS SELECT id FROM medicoes"); c.commit()
    with pytest.raises(sqlite3.Error):
        db.migrate(c)
    assert not c.in_transaction
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert _foto(c, de_hoje) == antes
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='medicoes_nova'").fetchone()[0] == 0
    assert "valor_com_sinal_centavos" not in _colunas(c, "espelho_medicoes")
