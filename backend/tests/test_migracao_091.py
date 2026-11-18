"""Migracao 091 (docs/adr/0006): protocolo da nota desfeito pela correcao de cadastro. So' acrescenta."""
import contextlib

import pytest

from app import db
from tests.test_db import _aplicar, _banco_antes_de

pytestmark = pytest.mark.migracao_real

ARQUIVO = "091_protocolo_desfeito.sql"


def _semear(conn):
    conn.execute("INSERT INTO contratos (id, orgao, numero_instrumento, objeto, valor_original_centavos, nome_curto) "
                 "VALUES (7, 'SECRETARIA DE EXEMPLO', '001/2025/00/00-EXEMPLO', 'Obra', 100000001, 'Obra 7')")
    conn.execute("INSERT INTO medicoes (id, contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
                 "VALUES (11, 7, 1, 'execucao', '2026-09', 'protocolada', 100001)")
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_processo, origem) "
                 "VALUES (11, '2026-10-02', 'PROC-1', 'manual')")
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_processo, origem, etapa) "
                 "VALUES (11, '2026-09-30', 'PROC-0', 'manual', 'planilha')")


def test_091_protocolo_existente_nasce_sem_a_marca_e_nenhuma_linha_muda(tmp_path, monkeypatch):
    conn, pasta = _banco_antes_de(ARQUIVO, tmp_path, monkeypatch)
    with contextlib.closing(conn):
        assert "desfeita_em" not in [r[1] for r in conn.execute("PRAGMA table_info(medicao_protocolos)")]
        _semear(conn)
        conn.commit()
        antes = [dict(r) for r in conn.execute("SELECT * FROM medicao_protocolos ORDER BY id")]
        _aplicar(conn, pasta, ARQUIVO)
        depois = [dict(r) for r in conn.execute("SELECT * FROM medicao_protocolos ORDER BY id")]
        assert [(d.pop("desfeita_em"), d.pop("motivo_desfazer")) for d in depois] == [(None, None), (None, None)]
        assert depois == antes and len(depois) == 2


def test_091_reexecutavel_sem_perder_a_marca(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()
    with contextlib.closing(conn):
        db.migrate(conn)
        _semear(conn)
        conn.execute("UPDATE medicao_protocolos SET desfeita_em='2026-11-17 10:00:00', motivo_desfazer='x' WHERE etapa='nota'")
        conn.execute("DELETE FROM schema_migrations WHERE nome=?", (ARQUIVO,))
        conn.commit()
        db.migrate(conn)
        colunas = [r[1] for r in conn.execute("PRAGMA table_info(medicao_protocolos)")]
        assert colunas.count("desfeita_em") == 1 and colunas.count("motivo_desfazer") == 1
        assert [tuple(r) for r in conn.execute("SELECT etapa, desfeita_em, motivo_desfazer FROM medicao_protocolos "
                                               "ORDER BY id")] == [("nota", "2026-11-17 10:00:00", "x"), ("planilha", None, None)]
