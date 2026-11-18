"""Migracao 091: o fiscal do contrato pode ficar sem e-mail.

Reconstroi `contrato_fiscais` so' para tirar o NOT NULL do e-mail, pela receita da 042 e da 078: nenhuma linha muda,
pode rodar de novo e e' atomica. O indice parcial segura a repeticao do fiscal sem e-mail.
"""
import shutil
import sqlite3

import pytest

from app import db

pytestmark = pytest.mark.migracao_real

ARQUIVO = "091_fiscal_sem_email.sql"
COLUNAS = "id, contrato_id, nome, email, desde, cargo, tratamento, portaria"


@pytest.fixture
def antes_da_091(tmp_path, monkeypatch):
    """Banco "ate' a 090": roda todas as migracoes anteriores a 091, de uma copia da pasta."""
    pasta = tmp_path / "migracoes"
    pasta.mkdir()
    for f in db.MIGRATIONS_DIR.glob("*.sql"):
        if f.name < "091":
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
    for i in (1, 2):
        c.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos) "
                  "VALUES ('SINFRA',?,'obra',100)", (f"X{i}/2026",))
    linhas = [(1, "Fiscal Um", "um@exemplo.gov.br", "2025-01-01", "Fiscal do Contrato", "Senhor", "Portaria n.º 1/2025"),
              (1, "Fiscal Dois", "dois@exemplo.gov.br", "2026-02-01", None, "Senhora", None),
              (1, "", "sem.nome@exemplo.gov.br", "2026-03-01", None, None, None),
              (2, "Fiscal Um", "um@exemplo.gov.br", "2025-01-01", "Engenheiro Fiscal", None, "Portaria n.º 9/2025")]
    c.executemany("INSERT INTO contrato_fiscais (contrato_id, nome, email, desde, cargo, tratamento, portaria) "
                  "VALUES (?,?,?,?,?,?,?)", linhas)
    c.commit()


def _linhas(c):
    return [tuple(r) for r in c.execute(f"SELECT {COLUNAS} FROM contrato_fiscais ORDER BY id")]


def _rodar(c):
    sql = (db.MIGRATIONS_DIR / ARQUIVO).read_text(encoding="utf-8")
    c.executescript(db._sem_alters_ja_aplicados(c, sql))
    c.execute("PRAGMA foreign_keys=ON")


def test_antes_da_091_o_email_era_obrigatorio(antes_da_091):
    c = antes_da_091
    _semear(c)
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO contrato_fiscais (contrato_id, nome, email, desde) VALUES (1,'Sem',NULL,'2026-04-01')")


def test_nenhuma_linha_muda_e_o_email_passa_a_aceitar_nulo(antes_da_091):
    c = antes_da_091
    _semear(c)
    antes = _linhas(c)
    colunas = [(r[1], r[2]) for r in c.execute("PRAGMA table_info(contrato_fiscais)")]
    _rodar(c)
    assert _linhas(c) == antes and len(antes) == 4                    # contagem e conteudo, linha a linha
    assert [(r[1], r[2]) for r in c.execute("PRAGMA table_info(contrato_fiscais)")] == colunas
    notnull = {r[1]: r[3] for r in c.execute("PRAGMA table_info(contrato_fiscais)")}
    assert notnull["email"] == 0 and notnull["nome"] == 1 and notnull["desde"] == 1 and notnull["contrato_id"] == 1
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='contrato_fiscais_nova'").fetchone()[0] == 0
    c.execute("INSERT INTO contrato_fiscais (contrato_id, nome, email, desde, cargo) "
              "VALUES (1,'Fiscal Tres',NULL,'2026-04-01','Fiscal')")
    assert c.execute("SELECT email FROM contrato_fiscais WHERE nome='Fiscal Tres'").fetchone()[0] is None


def test_as_unicidades_continuam_e_o_fiscal_sem_email_nao_repete(antes_da_091):
    c = antes_da_091
    _semear(c)
    _rodar(c)
    with pytest.raises(sqlite3.IntegrityError):                      # a de sempre: contrato, e-mail e data
        c.execute("INSERT INTO contrato_fiscais (contrato_id, nome, email, desde) "
                  "VALUES (1,'Outro','um@exemplo.gov.br','2025-01-01')")
    c.execute("INSERT INTO contrato_fiscais (contrato_id, nome, email, desde) VALUES (1,'Sem',NULL,'2026-04-01')")
    with pytest.raises(sqlite3.IntegrityError):                      # a nova: contrato, nome e data, sem e-mail
        c.execute("INSERT INTO contrato_fiscais (contrato_id, nome, email, desde) VALUES (1,'Sem',NULL,'2026-04-01')")
    c.execute("INSERT INTO contrato_fiscais (contrato_id, nome, email, desde) VALUES (2,'Sem',NULL,'2026-04-01')")
    with pytest.raises(sqlite3.IntegrityError):                      # o contrato continua obrigatorio e conferido
        c.execute("INSERT INTO contrato_fiscais (contrato_id, nome, email, desde) VALUES (99,'Sem',NULL,'2026-04-01')")


def test_pode_rodar_de_novo_sem_perder_o_fiscal_sem_email(antes_da_091):
    c = antes_da_091
    _semear(c)
    _rodar(c)
    c.execute("INSERT INTO contrato_fiscais (contrato_id, nome, email, desde) VALUES (1,'Sem',NULL,'2026-04-01')")
    c.commit()
    antes = _linhas(c)
    c.execute("CREATE TABLE contrato_fiscais_nova (lixo TEXT)")      # residuo de execucao interrompida
    c.commit()
    _rodar(c)
    assert _linhas(c) == antes and len(antes) == 5
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='contrato_fiscais_sem_email'").fetchone()[0] == 1


def test_banco_novo_sobe_ja_com_o_email_opcional(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "novo.db"))
    c = db.get_conn()
    db.migrate(c)
    assert {r[1]: r[3] for r in c.execute("PRAGMA table_info(contrato_fiscais)")}["email"] == 0
    assert c.execute("SELECT 1 FROM schema_migrations WHERE nome=?", (ARQUIVO,)).fetchone()
    c.close()
