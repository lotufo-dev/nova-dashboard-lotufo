"""Migracao 042 (issue #280): estados e tabelas do motor de medicao (planilha/carta, boletim, assinatura).

So' acrescenta. Reconstroi `medicoes` pelo CHECK de `estado`: a reconstrucao preserva todas as linhas e colunas e
pode rodar de novo (licao da 020).
"""
import shutil
import sqlite3

import pytest

from app import db

# Exercita a propria migracao: parte de um banco vazio de verdade, sem o banco-modelo do conftest.
pytestmark = pytest.mark.migracao_real

ARQUIVO = "042_motor_medicao.sql"
ESTADOS_DE_HOJE = ("prevista", "espelho_gerado", "espelho_enviado", "nota_emitida", "protocolada", "nf_emitida",
                   "recebida", "cancelada", "desistida")


def _colunas(conn, tabela):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")]


@pytest.fixture
def antes_da_042(tmp_path, monkeypatch):
    """Banco "ate' a 041": roda todas as migracoes anteriores a 042, de uma copia da pasta."""
    pasta = tmp_path / "migracoes"
    pasta.mkdir()
    for f in db.MIGRATIONS_DIR.glob("*.sql"):
        if f.name < "042":
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
    """Uma medicao em cada estado de hoje, com as colunas preenchidas, e filhas (atesto, protocolo, envio)."""
    c.execute("INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES ('U','u@l.com','x','engenharia')")
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos) "
              "VALUES ('SINFRA','X/2026','obra',100)")
    for i, estado in enumerate(ESTADOS_DE_HOJE, start=1):
        c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
                  "valor_protocolado_origem, valor_atestado_centavos, valor_atestado_origem, motivo_represamento, "
                  "congelada, atestado_em, nf_emitida_em, recebida_em, espelho_em, espelho_origem, nota_emitida_em, "
                  "final, final_em, envio_origem, envio_externo_em, envio_externo_obs) "
                  "VALUES (1,?,'execucao','2026-05',?,?, 'manual', ?, 'aceito', 'motivo', ?, '2026-06-01', "
                  "'2026-06-02', '2026-06-03', '2026-06-04', 'manual', '2026-06-05', ?, '2026-06-06', 'externo', "
                  "'2026-06-07', 'obs')",
                  (i, estado, 1_000_01 * i, 999_99 * i, i % 2, i % 2))
    c.execute("INSERT INTO medicao_atestos (medicao_id, valor_centavos, origem, atestado_em, usuario_id) "
              "VALUES (2, 999_99, 'manual', '2026-06-01', 1)")
    c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (5,'2026-06-01','manual')")
    c.execute("INSERT INTO envios (tipo, usuario_id, remetente, para, copia, assunto) "
              "VALUES ('espelho', 1, 'a@l.com', '[]', '[]', 'assunto')")
    c.execute("INSERT INTO envio_medicoes (envio_id, medicao_id) VALUES (1, 3)")
    c.commit()


def _foto(c, colunas):
    """As colunas dadas de todas as medicoes, mais as filhas."""
    cols = ", ".join(colunas)
    return ([tuple(r) for r in c.execute(f"SELECT {cols} FROM medicoes ORDER BY id")],
            [tuple(r) for r in c.execute("SELECT id, medicao_id, valor_centavos, origem, atestado_em, usuario_id, "
                                         "criado_em FROM medicao_atestos ORDER BY id")],
            [tuple(r) for r in c.execute("SELECT id, medicao_id, data, numero_oficio, numero_processo, origem, "   # a 054 acrescenta `etapa`
                                         "criado_em, protocolo_id FROM medicao_protocolos ORDER BY id")],
            [tuple(r) for r in c.execute("SELECT * FROM envio_medicoes")])


def _rodar_script(c):
    sql = (db.MIGRATIONS_DIR / ARQUIVO).read_text(encoding="utf-8")
    c.executescript(db._sem_alters_ja_aplicados(c, sql))
    c.execute("PRAGMA foreign_keys=ON")


def test_042_roda_duas_vezes_e_preserva_as_medicoes_de_todos_os_estados(antes_da_042):
    c = antes_da_042
    _semear(c)
    de_hoje = _colunas(c, "medicoes")
    antes = _foto(c, de_hoje)
    db.migrate(c)                                   # 1a vez, pelo runner (como em create_app)
    assert _foto(c, de_hoje) == antes
    c.execute("DELETE FROM schema_migrations WHERE nome=?", (ARQUIVO,)); c.commit()
    db.migrate(c)                                   # 2a vez, inteira
    _rodar_script(c)                                # 3a vez, o script cru
    assert _foto(c, de_hoje) == antes
    # colunas de hoje na mesma ordem, as novas no fim
    assert _colunas(c, "medicoes")[:len(de_hoje)] == de_hoje
    assert {"periodo_inicio", "periodo_fim", "planilha_enviada_em", "planilha_envio_origem",
            "numero_orgao"} <= set(_colunas(c, "medicoes"))
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    # as filhas continuam apontando para `medicoes`, nao para a tabela temporaria
    for filha in ("medicao_atestos", "medicao_protocolos", "envio_medicoes", "medicao_planilhas",
                  "medicao_assinaturas"):
        ddl = c.execute("SELECT sql FROM sqlite_master WHERE name=?", (filha,)).fetchone()[0]
        assert "REFERENCES medicoes(id)" in ddl and "medicoes_nova" not in ddl
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='medicoes_nova'").fetchone()[0] == 0
    # os gatilhos da 039 seguem de pe' depois da reconstrucao
    gatilhos = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"medicao_atestos_sem_update", "medicao_atestos_sem_delete", "medicao_planilhas_sem_update",
            "medicao_planilhas_sem_delete", "medicao_assinaturas_sem_update",
            "medicao_assinaturas_sem_delete"} <= gatilhos
    # a unicidade (contrato, numero, tipo) sobreviveu
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia) VALUES (1,1,'execucao','2026-05')")


def test_042_residuo_de_execucao_interrompida_nao_atrapalha(antes_da_042):
    c = antes_da_042
    _semear(c)
    de_hoje = _colunas(c, "medicoes")
    antes = _foto(c, de_hoje)
    c.execute("CREATE TABLE medicoes_nova (id INTEGER PRIMARY KEY)"); c.execute("INSERT INTO medicoes_nova VALUES (1)")
    c.commit()
    db.migrate(c)
    assert _foto(c, de_hoje) == antes
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_042_depois_da_043_preserva_data_base_e_ciclo(antes_da_042):
    """Orquestradora: a 043 (issue #270) acrescenta `data_base_mes` e `ciclo` em `medicoes` e pode ter rodado antes
    desta num banco que a recebeu primeiro. A reconstrucao nao pode perder as duas colunas nem os valores."""
    c = antes_da_042
    _semear(c)
    # o que a 043 faz em `medicoes` (mesmas definicoes)
    c.execute("ALTER TABLE medicoes ADD COLUMN data_base_mes TEXT")
    c.execute("ALTER TABLE medicoes ADD COLUMN ciclo INTEGER")
    c.execute("UPDATE medicoes SET data_base_mes='2025-03', ciclo=id WHERE id % 2 = 0")
    c.commit()
    de_hoje = _colunas(c, "medicoes")
    antes = _foto(c, de_hoje)
    db.migrate(c)
    assert _foto(c, de_hoje) == antes
    assert c.execute("SELECT COUNT(*) FROM medicoes WHERE data_base_mes='2025-03' AND ciclo=id").fetchone()[0] == 4
    assert _colunas(c, "medicoes").count("ciclo") == 1
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_042_falha_no_meio_nao_perde_medicoes(antes_da_042):
    """Code-review: a reconstrucao e' uma transacao so'. Uma visao que le `medicoes` faz o RENAME falhar DEPOIS do
    DROP; sem a transacao, as medicoes so' existiriam na `_nova` (e a proxima execucao a apagaria)."""
    c = antes_da_042
    _semear(c)
    de_hoje = _colunas(c, "medicoes")
    antes = _foto(c, de_hoje)
    c.execute("CREATE VIEW v_medicoes AS SELECT id FROM medicoes"); c.commit()
    with pytest.raises(sqlite3.Error):
        db.migrate(c)
    # gate Sol: o runner desfaz a transacao aberta pela 042 e as FK voltam a valer na mesma conexao
    assert not c.in_transaction
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert _foto(c, de_hoje) == antes
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='medicoes_nova'").fetchone()[0] == 0
    assert "periodo_inicio" not in _colunas(c, "medicoes")


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "n.db"))
    c = db.get_conn(); db.migrate(c)
    c.execute("INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES ('U','u@l.com','x','engenharia')")
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos) "
              "VALUES ('SINFRA','X/2026','obra',100)")
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia) VALUES (1,1,'execucao','2026-05')")
    c.commit()
    yield c
    c.close()


def _planilha(c, versao=1, motivo=None):
    c.execute("INSERT INTO medicao_planilhas (medicao_id, versao, periodo_inicio, periodo_fim, valor_pedido_centavos, "
              "acumulado_anterior_centavos, arquivo, sha256, origem, usuario_id, motivo) "
              "VALUES (1,?,'2026-05-01','2026-05-31',1_000_01,0,'planilhas/abc.pdf','abc','manual',1,?)",
              (versao, motivo))


def test_eventos_novos_nao_se_alteram_nem_se_apagam(conn):
    _planilha(conn)
    conn.execute("INSERT INTO medicao_assinaturas (medicao_id, envelope, assinado_em, origem, usuario_id) "
                 "VALUES (1,'Envelope 14a medicao','2026-06-10','manual',1)")
    conn.execute("INSERT INTO medicao_atestos (medicao_id, valor_centavos, origem, atestado_em, usuario_id, meio, "
                 "numero_orgao, arquivo, sha256, observacao) "
                 "VALUES (1, 999_99, 'manual', '2026-06-01', 1, 'smo', 'SMO 123/2026', 'boletins/x.pdf', 'x', 'obs')")
    conn.commit()
    for tabela, coluna in (("medicao_planilhas", "valor_pedido_centavos"), ("medicao_assinaturas", "assinado_em"),
                           ("medicao_atestos", "valor_centavos")):
        with pytest.raises(sqlite3.IntegrityError, match="evento"):
            conn.execute(f"UPDATE {tabela} SET {coluna}={coluna} WHERE medicao_id=1")
        with pytest.raises(sqlite3.IntegrityError, match="evento"):
            conn.execute(f"DELETE FROM {tabela} WHERE medicao_id=1")
        assert conn.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0] == 1


def test_planilha_versao_unica_e_revisao_exige_motivo(conn):
    _planilha(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _planilha(conn, versao=1, motivo="de novo")          # versao repetida
    with pytest.raises(sqlite3.IntegrityError):
        _planilha(conn, versao=2)                           # revisao sem motivo
    with pytest.raises(sqlite3.IntegrityError):
        _planilha(conn, versao=2, motivo="   ")
    _planilha(conn, versao=2, motivo="Rev01: supervisora devolveu")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO medicao_planilhas (medicao_id, versao, valor_pedido_centavos, "
                     "acumulado_anterior_centavos, origem) VALUES (1,3,-1,0,'manual')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO medicao_planilhas (medicao_id, versao, valor_pedido_centavos, "
                     "acumulado_anterior_centavos, origem, motivo) VALUES (1,3,1,0,'inventado','m')")


def test_planilha_recusa_centavo_fracionario(conn):
    """Gate Sol: INTEGER no SQLite e' afinidade; 100.5 ficaria REAL e o evento congelaria meio centavo."""
    for pedido, acumulado in ((100.5, 0), (100, 0.5), ("100,5", 0)):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO medicao_planilhas (medicao_id, versao, valor_pedido_centavos, "
                         "acumulado_anterior_centavos, origem) VALUES (1,1,?,?,'manual')", (pedido, acumulado))
    conn.execute("INSERT INTO medicao_planilhas (medicao_id, versao, valor_pedido_centavos, "
                 "acumulado_anterior_centavos, origem) VALUES (1,1,1_000_01,0,'manual')")


def test_inteiros_novos_recusam_real_e_texto(conn):
    """Gate Sol R2: com so' `>= 1`, versao 1.5 ou 'abc' entravam, e 'abc' venceria o MAX(versao)."""
    for versao in (1.5, "abc", "2,0"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO medicao_planilhas (medicao_id, versao, valor_pedido_centavos, "
                         "acumulado_anterior_centavos, origem, motivo) VALUES (1,?,1,0,'manual','m')", (versao,))
    for numero in (46.5, "46a", 0):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE medicoes SET numero_orgao=? WHERE id=1", (numero,))
    conn.execute("UPDATE medicoes SET numero_orgao=46 WHERE id=1")
    conn.execute("UPDATE medicoes SET numero_orgao=NULL WHERE id=1")
    _planilha(conn)
    assert conn.execute("SELECT MAX(versao) FROM medicao_planilhas").fetchone()[0] == 1


def test_colunas_novas_recusam_valor_fora_da_lista(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO medicao_atestos (medicao_id, valor_centavos, meio) VALUES (1, 1, 'telefone')")
    for meio in ("smo", "oficio", "email", "carimbo", "ci", "outro"):
        conn.execute("INSERT INTO medicao_atestos (medicao_id, valor_centavos, meio) VALUES (1, 1, ?)", (meio,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE medicoes SET planilha_envio_origem='pombo' WHERE id=1")
    conn.execute("UPDATE medicoes SET planilha_envio_origem='externo', planilha_enviada_em='2026-06-01', "
                 "numero_orgao=46, periodo_inicio='2026-05-01', periodo_fim='2026-05-31' WHERE id=1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO medicao_assinaturas (medicao_id, assinado_em, origem) VALUES (1,'2026-06-10','x')")


def test_042_na_ordem_normal_ja_deixa_as_colunas_da_043(conn):
    """Na ordem normal (042 antes da 043), as colunas da 043 ja' existem e o ALTER dela e' pulado pelo runner."""
    cols = _colunas(conn, "medicoes")
    assert "data_base_mes" in cols and "ciclo" in cols
    sql = "ALTER TABLE medicoes ADD COLUMN data_base_mes TEXT;\nALTER TABLE medicoes ADD COLUMN ciclo INTEGER;\n"
    assert db._sem_alters_ja_aplicados(conn, sql).strip() == ""


def test_envio_aceita_o_tipo_planilha(conn):
    conn.execute("INSERT INTO envios (tipo, usuario_id, remetente, para, copia, assunto) "
                 "VALUES ('planilha', 1, 'a@l.com', '[]', '[]', 'CT-001-LT-2026 - 14a Medicao')")
    assert conn.execute("SELECT tipo FROM envios").fetchone()[0] == "planilha"
