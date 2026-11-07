"""Migracao 061 (issue #410): `aditivos.data_base_origem` diz de onde veio a data-base guardada no aditivo de reajuste.
So' acrescenta: os aditivos ja' aplicados ficam sem origem, e o proximo `cadastro aplicar` os trata como base deduzida
(a primeira declaracao entra, auditada)."""
import pytest

from app import auth, cadastro_aplicar, db

pytestmark = pytest.mark.migracao_real

MIGRACAO = "061_aditivo_data_base_origem.sql"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn()
    # banco ate' a 060: a 061 fica de fora
    original = db.MIGRATIONS_DIR
    monkeypatch.setattr(db, "MIGRATIONS_DIR", tmp_path / "migracoes")
    db.MIGRATIONS_DIR.mkdir()
    for f in sorted(original.glob("*.sql")):
        if f.name < MIGRACAO:
            (db.MIGRATIONS_DIR / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    db.migrate(c)
    assert "data_base_origem" not in {r[1] for r in c.execute("PRAGMA table_info(aditivos)")}
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "admin")
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
              "VALUES ('SINFRA', '019/2024/00/00-SINFRA', 'MT-402', 'obra', 1512720000)")
    c.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, chave_cadastro, "
              "natureza, data_base_mes, numero, forma, valor_anterior_centavos, valor_novo_centavos) "
              "VALUES (1, 'valor', 100_01, 'assinado', '2026-07-30', 'ta-08', 'reajuste', '2023-04', '019/2024/01/08', "
              "'termo_aditivo', 1512720000, 1512730001)")
    c.commit()
    (db.MIGRATIONS_DIR / MIGRACAO).write_text((original / MIGRACAO).read_text(encoding="utf-8"), encoding="utf-8")
    db.migrate(c)
    yield c
    c.close()


def _origem(conn):
    return tuple(conn.execute("SELECT data_base_mes, data_base_origem FROM aditivos WHERE chave_cadastro='ta-08'")
                 .fetchone())


def test_aditivo_existente_fica_sem_origem(conn):
    assert _origem(conn) == ("2023-04", None)


def test_reaplicar_a_migracao_nao_falha(conn):
    conn.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); conn.commit()
    db.migrate(conn)
    assert _origem(conn) == ("2023-04", None)


def test_proximo_aplicar_trata_a_base_sem_origem_como_deduzida(conn):
    from tests.test_cadastro_aplicar import DUAS_BASES, TA_REAJ, _cad, _contrato
    declarado = {**TA_REAJ, "dados": {"data_base": "2023-06"}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[declarado], datas_base=DUAS_BASES)]))
    assert _origem(conn) == ("2023-06", "declarada")
