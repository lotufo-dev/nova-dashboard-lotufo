"""Migracao 056 (issue #398): `pleitos.tipo` aceita 'valor' (pedido de aditivo de valor do cadastro), com o valor
pedido em `valor_centavos` e o `objeto`. So' acrescenta: a reconstrucao de `pleitos` preserva linhas, colunas,
indices e as filhas, e pode rodar de novo."""
import shutil
import sqlite3

import pytest

from app import db

pytestmark = pytest.mark.migracao_real

MIGRACAO = "056_pleitos_tipo_valor.sql"


@pytest.fixture
def antes_da_056(tmp_path, monkeypatch):
    pasta = tmp_path / "migracoes"
    pasta.mkdir()
    for f in db.MIGRATIONS_DIR.glob("*.sql"):
        if f.name < "056":
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
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
              "VALUES ('MTPAR', '099/2024', 'Obra Alfa', 'obra', 100)")
    c.execute("INSERT INTO pleitos (contrato_id, tipo, origem, data_base_mes, ciclo, numero_oficio, situacao, "
              "enviado_em, instrumento_chave) VALUES (1, 'reajuste', 'cadastro', '2024-06', 2026, 'CT-122-LT-2026', "
              "'enviado', '2026-04-23', 'ap-1')")
    c.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo, numero_oficio, reemite_pleito_id, "
              "reemissao) VALUES (1, 'reajuste', '2024-06', 2026, 'CT-130-LT-2026', 1, 'reiteracao')")
    c.execute("INSERT INTO pleitos (contrato_id, tipo, dias, justificativa) VALUES (1, 'prazo', 120, 'atraso')")
    c.execute("INSERT INTO pleito_anexos (pleito_id, tipo, nome, arquivo, sha256, tamanho, ext) "
              "VALUES (2, 'cronograma', 'c.pdf', 'pleitos/c.pdf', 'abc', 10, 'pdf')")
    c.execute("INSERT INTO reajuste_previsoes (contrato_id, data_base_mes, ciclo, competencia, valor_previsto_centavos, "
              "origem, pleito_id) VALUES (1, '2024-06', 2026, '2026-05', 12345, 'pleito', 1)")
    c.commit()


def _tudo(c):
    return {t: [tuple(r) for r in c.execute(f"SELECT * FROM {t} ORDER BY id")]
            for t in ("pleitos", "pleito_anexos", "reajuste_previsoes")}


def test_056_preserva_os_pleitos_e_as_filhas(antes_da_056):
    c = antes_da_056
    _semear(c)
    antes = _tudo(c)
    db.migrate(c)
    depois = _tudo(c)
    # as colunas novas entram no fim, vazias
    assert [r[:-2] for r in depois["pleitos"]] == antes["pleitos"]
    assert all(r[-2:] == (None, None) for r in depois["pleitos"])
    assert depois["pleito_anexos"] == antes["pleito_anexos"]
    assert depois["reajuste_previsoes"] == antes["reajuste_previsoes"]
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    indices = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='pleitos'")}
    assert {"pleitos_contrato", "pleitos_cadastro"} <= indices
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='pleitos_nova'").fetchone()[0] == 0


def test_056_aceita_o_pedido_de_valor_do_cadastro_e_so_ele(antes_da_056):
    c = antes_da_056
    _semear(c)
    db.migrate(c)
    c.execute("INSERT INTO pleitos (contrato_id, tipo, origem, numero_oficio, situacao, enviado_em, valor_centavos, "
              "objeto) VALUES (1, 'valor', 'cadastro', 'CT-001-LT-2026', 'enviado', '2026-03-27', 100000000, "
              "'1ª RPFO')")
    for sql in (
            # pedido de valor sem valor
            "INSERT INTO pleitos (contrato_id, tipo, origem) VALUES (1, 'valor', 'cadastro')",
            # valor fora do pedido de valor
            "INSERT INTO pleitos (contrato_id, tipo, valor_centavos) VALUES (1, 'prazo', 100)",
            # valor nao inteiro
            "INSERT INTO pleitos (contrato_id, tipo, origem, valor_centavos) VALUES (1, 'valor', 'cadastro', 100.5)",
            # pedido de valor feito no sistema: nao ha' carta de aditivo de valor
            "INSERT INTO pleitos (contrato_id, tipo, valor_centavos) VALUES (1, 'valor', 100)",
            "INSERT INTO pleitos (contrato_id, tipo) VALUES (1, 'inventado')"):
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(sql)
    # a guarda da 043 (previsao aponta pleito de reajuste do contrato) continua valendo
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO reajuste_previsoes (contrato_id, data_base_mes, ciclo, competencia, "
                  "valor_previsto_centavos, origem, pleito_id) VALUES (1, '2024-06', 2026, '2026-06', 1, 'pleito', 4)")


def test_056_roda_de_novo_sem_mexer_no_que_existe(antes_da_056):
    c = antes_da_056
    _semear(c)
    db.migrate(c)
    c.execute("INSERT INTO pleitos (contrato_id, tipo, origem, numero_oficio, situacao, enviado_em, valor_centavos, "
              "objeto) VALUES (1, 'valor', 'cadastro', 'CT-001-LT-2026', 'enviado', '2026-03-27', 100000000, "
              "'1ª RPFO')")
    c.commit()
    antes = _tudo(c)
    for _ in range(2):
        c.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); c.commit()
        db.migrate(c)
    assert _tudo(c) == antes
