"""Migracao 095 (issue #798): o envio do espelho ao faturamento feito por fora. So' acrescenta coluna."""
import contextlib

import pytest

from app import db
from tests.test_db import _aplicar, _banco_antes_de

pytestmark = pytest.mark.migracao_real

ARQUIVO = "095_espelho_envio_externo.sql"
COLUNAS = ["envio_externo_em", "envio_externo_observacao", "envio_externo_por", "envio_externo_registrado_em"]


def _espelhos(conn):
    """Um contrato, um usuario e tres versoes de espelho, uma delas ja' enviada pelo sistema."""
    conn.execute("INSERT INTO usuarios (id, nome, email, senha_hash, perfil) VALUES (1, 'U', 'u@exemplo.com.br', 'x', "
                 "'engenharia')")
    conn.execute("INSERT INTO contratos (id, orgao, numero_instrumento, objeto, valor_original_centavos, nome_curto) "
                 "VALUES (7, 'SECRETARIA DE EXEMPLO', '001/2025/00/00-EXEMPLO', 'Obra', 100000001, 'Obra 7')")
    envio = conn.execute("INSERT INTO envios (tipo, usuario_id, remetente, para, copia, assunto) "
                         "VALUES ('espelho', 1, 'u@exemplo.com.br', '[]', '[]', 'Espelho')").lastrowid
    for versao, situacao, envio_id in ((1, "substituido", None), (2, "substituido", envio), (3, "vigente", None)):
        conn.execute("INSERT INTO espelhos (contrato_id, numero, competencia, versao, situacao, entradas, saidas, "
                     "regra_sha256, criado_por, envio_id) VALUES (7, 3, '2026-01', ?, ?, '{\"medicao\": 100001}', '[]', "
                     "'x', 1, ?)", (versao, situacao, envio_id))
    conn.commit()


def test_095_espelho_existente_fica_sem_envio_por_fora_e_com_os_outros_campos_iguais(tmp_path, monkeypatch):
    """Como na producao: os espelhos ja' existem quando a 095 chega. Nenhum ganha envio por fora, nenhuma outra
    coluna muda e nenhuma linha se perde."""
    conn, pasta = _banco_antes_de(ARQUIVO, tmp_path, monkeypatch)
    with contextlib.closing(conn):
        assert not set(COLUNAS) & {r[1] for r in conn.execute("PRAGMA table_info(espelhos)")}
        _espelhos(conn)
        antes = [dict(r) for r in conn.execute("SELECT * FROM espelhos ORDER BY id")]
        _aplicar(conn, pasta, ARQUIVO)
        depois = [dict(r) for r in conn.execute("SELECT * FROM espelhos ORDER BY id")]
        assert [[d.pop(c) for c in COLUNAS] for d in depois] == [[None] * 4] * 3
        assert depois == antes and len(depois) == 3
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_095_reexecutavel_sem_perder_o_registro_ja_gravado(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()
    with contextlib.closing(conn):
        db.migrate(conn)
        _espelhos(conn)
        conn.execute("UPDATE espelhos SET envio_externo_em='2026-02-10', envio_externo_observacao='pelo Outlook', "
                     "envio_externo_por=1, envio_externo_registrado_em='2026-02-11 13:00:00' WHERE versao=3")
        conn.execute("DELETE FROM schema_migrations WHERE nome=?", (ARQUIVO,))
        conn.commit()
        db.migrate(conn)
        colunas = [r[1] for r in conn.execute("PRAGMA table_info(espelhos)")]
        assert [colunas.count(c) for c in COLUNAS] == [1, 1, 1, 1]
        assert [tuple(r) for r in conn.execute(
            "SELECT versao, envio_externo_em, envio_externo_observacao, envio_externo_por, envio_externo_registrado_em "
            "FROM espelhos ORDER BY versao")] == [
            (1, None, None, None, None), (2, None, None, None, None),
            (3, "2026-02-10", "pelo Outlook", 1, "2026-02-11 13:00:00")]
        with pytest.raises(Exception, match="FOREIGN KEY"):          # quem registrou e' um usuario de verdade
            conn.execute("UPDATE espelhos SET envio_externo_por=99 WHERE versao=1")
