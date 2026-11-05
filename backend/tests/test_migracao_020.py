import shutil

import pytest
from app import db

# Exercita a propria migracao: parte de um banco vazio de verdade, sem o banco-modelo do
# conftest (issue #88).
pytestmark = pytest.mark.migracao_real


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def _colunas(conn, tabela):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}


def _semear_filhas(conn):
    """Contrato + medicao legada + uma linha em cada tabela filha de medicoes."""
    conn.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos) "
                 "VALUES ('SINFRA','X/2026','obra',100)")
    conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
                 "VALUES (1, 1, 'execucao', '2026-05', 'protocolada')")
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (1,'2026-06-01','manual')")
    conn.execute("INSERT INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, item_id) "
                 "VALUES (1,'controladoria_sp','nf','NF 1.pdf','item-1')")
    conn.commit()


def test_estados_novos_e_origem_espelho_sao_aceitos(conn):
    conn.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos) "
                 "VALUES ('SINFRA','X/2026','obra',100)")
    for estado in ("espelho_gerado", "espelho_enviado", "nota_emitida", "prevista"):
        conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, "
                     "valor_protocolado_centavos, valor_protocolado_origem) "
                     "VALUES (1,?, 'execucao','2026-05',?,100,'espelho')", (len(estado), estado))
    assert conn.execute("SELECT COUNT(*) FROM medicoes").fetchone()[0] == 4


def test_filhas_de_medicoes_sobrevivem_a_reexecucao_do_script(conn):
    _semear_filhas(conn)
    sql = (db.MIGRATIONS_DIR / "020_espelho.sql").read_text(encoding="utf-8")
    conn.executescript(db._sem_alters_ja_aplicados(conn, sql))
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("SELECT estado FROM medicoes WHERE id=1").fetchone()[0] == "protocolada"
    assert conn.execute("SELECT COUNT(*) FROM medicao_protocolos WHERE medicao_id=1").fetchone()[0] == 1
    assert conn.execute("SELECT tipo_doc FROM medicao_documentos WHERE medicao_id=1").fetchone()[0] == "nf"
    # a FK das filhas continua apontando para `medicoes`, nao para a tabela temporaria
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name='medicao_protocolos'").fetchone()[0]
    assert "REFERENCES medicoes(id)" in ddl and "medicoes_nova" not in ddl


def test_tabelas_e_colunas_novas(conn):
    assert {"arquivo", "sha256", "tamanho", "espelho_id", "saida"} <= _colunas(conn, "medicao_documentos")
    assert {"contrato_id", "numero", "competencia", "versao", "situacao", "entradas", "saidas",
            "regra_sha256", "criado_por", "envio_id", "motivo"} <= _colunas(conn, "espelhos")
    assert {"espelho_id", "medicao_id"} <= _colunas(conn, "espelho_medicoes")
    assert {"envio_id", "medicao_id"} <= _colunas(conn, "envio_medicoes")
    assert {"chave", "valor"} <= _colunas(conn, "cadastro_geral")
    assert {"contrato_id", "situacao", "regra", "modelos", "sha256"} <= _colunas(conn, "espelho_regras")
    assert "emails_faturamento" in _colunas(conn, "entidades")
    _semear_filhas(conn)
    conn.execute("INSERT INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, item_id) "
                 "VALUES (1,'sistema','espelho','x.docx','abc')")
    with pytest.raises(Exception):
        conn.execute("INSERT INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, item_id) "
                     "VALUES (1,'sistema','outro','x.docx','def')")


def test_reexecucao_preserva_documentos_locais_e_residuo_nao_atrapalha(conn):
    _semear_filhas(conn)
    conn.execute("INSERT INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, item_id, arquivo, sha256, "
                 "tamanho, saida) VALUES (1,'sistema','espelho','x.docx','1:abc','espelhos/abc.docx','abc',10,'medicao')")
    # residuo de uma execucao interrompida: tabela temporaria populada
    conn.execute("CREATE TABLE medicoes_nova (id INTEGER PRIMARY KEY)"); conn.execute("INSERT INTO medicoes_nova VALUES (1)")
    conn.commit()
    sql = (db.MIGRATIONS_DIR / "020_espelho.sql").read_text(encoding="utf-8")
    conn.executescript(db._sem_alters_ja_aplicados(conn, sql))
    d = conn.execute("SELECT arquivo, sha256, tamanho, saida FROM medicao_documentos WHERE item_id='1:abc'").fetchone()
    assert tuple(d) == ("espelhos/abc.docx", "abc", 10, "medicao")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migrate_religa_foreign_keys_mesmo_se_o_script_falhar(tmp_path, monkeypatch):
    # Pasta temporaria com copia das migracoes: nunca escrever na pasta versionada (issue #416),
    # senao outro worker do xdist lista a pasta enquanto o arquivo existe.
    pasta = tmp_path / "migracoes"
    pasta.mkdir()
    for f in db.MIGRATIONS_DIR.glob("*.sql"):
        shutil.copy(f, pasta / f.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", pasta)
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "f.db"))
    c = db.get_conn(); db.migrate(c)
    (pasta / "999_teste_falha.sql").write_text("PRAGMA foreign_keys=OFF;\nSELECT * FROM nao_existe;\n", "utf-8")
    try:
        with pytest.raises(Exception):
            db.migrate(c)
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        c.close()
