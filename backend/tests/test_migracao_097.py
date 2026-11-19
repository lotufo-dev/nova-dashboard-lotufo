"""Migracao 097 (issue #841): vinculo pela tela, encerramento a' mao e leitura vazia do SIGA. So' acrescenta."""
import contextlib
import sqlite3

import pytest

from app import db
from tests.test_db import _aplicar, _banco_antes_de

pytestmark = pytest.mark.migracao_real

ARQUIVO = "097_siga_encerramento.sql"


def _processos(conn):
    """Um usuario, uma obra, uma medicao, dois processos (um ligado a' medicao) e tres leituras."""
    conn.execute("INSERT INTO usuarios (id, nome, email, senha_hash, perfil) VALUES (1, 'U', 'u@exemplo.com.br', 'x', "
                 "'engenharia')")
    conn.execute("INSERT INTO contratos (id, orgao, numero_instrumento, objeto, valor_original_centavos, nome_curto) "
                 "VALUES (7, 'SECRETARIA DE EXEMPLO', '001/2025/00/00-EXEMPLO', 'Obra', 100000001, 'Obra 7')")
    conn.execute("INSERT INTO medicoes (id, contrato_id, numero, tipo, competencia, estado) "
                 "VALUES (31, 7, 3, 'execucao', '2026-09', 'protocolada')")
    conn.execute("INSERT INTO siga_processos (id, codigo, numero, nome, contrato_id, medicao_id, categoria) "
                 "VALUES (1, 'AAA111', 'ORGAO-PRO-2026/00001', 'Processo Alfa', 7, 31, 'medicoes')")
    conn.execute("INSERT INTO siga_processos (id, codigo, nome) VALUES (2, 'BBB222', 'Processo Beta')")
    for pid, lido in ((1, "2026-10-28 14:00:00"), (1, "2026-10-28 15:00:00"), (2, "2026-10-28 15:00:00")):
        conn.execute("INSERT INTO siga_leituras (processo_id, lido_em, situacao) VALUES (?, ?, "
                     "'1º Volume - Aguardando Andamento [SETORX, [X]]')", (pid, lido))
    conn.commit()


def test_097_processos_e_leituras_existentes_ficam_como_estavam(tmp_path, monkeypatch):
    """Como na producao: processos e leituras ja' existem. Nenhum ganha vinculo pela tela nem encerramento a' mao,
    toda leitura existente continua valendo (sem_movimentacoes = 0) e nenhuma linha se perde."""
    conn, pasta = _banco_antes_de(ARQUIVO, tmp_path, monkeypatch)
    with contextlib.closing(conn):
        _processos(conn)
        antes_p = [dict(r) for r in conn.execute("SELECT * FROM siga_processos ORDER BY id")]
        antes_l = [dict(r) for r in conn.execute("SELECT * FROM siga_leituras ORDER BY id")]
        _aplicar(conn, pasta, ARQUIVO)
        depois_p = [dict(r) for r in conn.execute("SELECT * FROM siga_processos ORDER BY id")]
        depois_l = [dict(r) for r in conn.execute("SELECT * FROM siga_leituras ORDER BY id")]
        assert [[d.pop(c) for c in ("medicao_vinculada_por", "medicao_vinculada_em")] for d in depois_p] == [
            [None, None]] * 2
        assert [d.pop("sem_movimentacoes") for d in depois_l] == [0, 0, 0]
        assert depois_p == antes_p and depois_l == antes_l
        assert conn.execute("SELECT COUNT(*) FROM siga_encerramentos").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_097_reexecutavel_e_com_as_travas_do_encerramento(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()
    with contextlib.closing(conn):
        db.migrate(conn)
        _processos(conn)
        conn.execute("UPDATE siga_processos SET medicao_vinculada_por=1, medicao_vinculada_em='2026-10-28 15:00:00' "
                     "WHERE id=1")
        conn.execute("INSERT INTO siga_encerramentos (processo_id, motivo, encerrado_por, encerrado_em) "
                     "VALUES (2, 'aditivo publicado', 1, '2026-10-28 15:00:00')")
        conn.execute("UPDATE siga_leituras SET sem_movimentacoes=1 WHERE id=3")
        conn.execute("DELETE FROM schema_migrations WHERE nome=?", (ARQUIVO,))
        conn.commit()
        db.migrate(conn)                                   # roda de novo sem perder nada do que foi gravado
        assert tuple(conn.execute("SELECT medicao_vinculada_por, medicao_vinculada_em FROM siga_processos "
                                  "WHERE id=1").fetchone()) == (1, "2026-10-28 15:00:00")
        assert conn.execute("SELECT COUNT(*) FROM siga_encerramentos").fetchone()[0] == 1
        assert conn.execute("SELECT sem_movimentacoes FROM siga_leituras WHERE id=3").fetchone()[0] == 1
        # um encerramento em aberto por processo
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            conn.execute("INSERT INTO siga_encerramentos (processo_id, motivo, encerrado_por, encerrado_em) "
                         "VALUES (2, 'outro', 1, '2026-10-29 15:00:00')")
        # reaberto, abre outro: o primeiro fica, preenchido
        conn.execute("UPDATE siga_encerramentos SET reaberto_em='2026-10-29 12:00:00', reaberto_por=1 WHERE processo_id=2")
        conn.execute("INSERT INTO siga_encerramentos (processo_id, motivo, encerrado_por, encerrado_em) "
                     "VALUES (2, 'outro', 1, '2026-10-29 15:00:00')")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):           # motivo em branco
            conn.execute("INSERT INTO siga_encerramentos (processo_id, motivo, encerrado_por, encerrado_em) "
                         "VALUES (1, '   ', 1, '2026-10-29 15:00:00')")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):           # quem reabriu sem a data
            conn.execute("INSERT INTO siga_encerramentos (processo_id, motivo, encerrado_por, encerrado_em, "
                         "reaberto_por) VALUES (1, 'x', 1, '2026-10-29 15:00:00', 1)")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):     # quem encerrou e' um usuario de verdade
            conn.execute("INSERT INTO siga_encerramentos (processo_id, motivo, encerrado_por, encerrado_em) "
                         "VALUES (1, 'x', 99, '2026-10-29 15:00:00')")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute("UPDATE siga_leituras SET sem_movimentacoes=2 WHERE id=1")
