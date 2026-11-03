"""Migracao 055 (issue #271): `instrumentos.data_base_mes` guarda a data-base do apostilamento de reajuste, com os
termos ja' aplicados preenchidos pela regra que valia. So' acrescenta."""
import pytest

from app import db

pytestmark = pytest.mark.migracao_real

MIGRACAO = "055_instrumento_data_base.sql"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    for nome in ("Obra Alfa", "Obra Beta", "Obra Gama"):
        c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
                  "VALUES ('MTPAR', ?, ?, 'obra', 100)", (f"{nome}/2024", nome))
    # Alfa: uma base so'; Beta: duas; Gama: duas, com o termo que gravou previsoes na 2024-06
    c.executemany("INSERT INTO contrato_datas_base (contrato_id, mes, indice) VALUES (?,?,?)",
                  [(1, "2024-06", "INCC-DI"), (2, "2024-06", "INCC-DI"), (2, "2024-04", "SICRO"),
                   (3, "2024-06", "INCC-DI"), (3, "2024-04", "SICRO")])
    termos = [(1, "a-sem", '{"ciclo": 2026}'), (2, "b-com", '{"data_base": "2024-04", "ciclo": 2026}'),
              (2, "b-sem", '{"ciclo": 2026}'), (3, "g-prev", '{"ciclo": 2026}'), (1, "a-vazia", '{"data_base": ""}')]
    c.executemany("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) "
                  "VALUES (?, ?, 'apostilamento_reajuste', '2026-09-15', ?)", termos)
    c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) VALUES (1, 'par', 'paralisacao', "
              "'2026-01-01', '{}')")
    gprev = c.execute("SELECT id FROM instrumentos WHERE chave='g-prev'").fetchone()[0]
    c.execute("INSERT INTO reajuste_previsoes (contrato_id, data_base_mes, ciclo, competencia, valor_previsto_centavos, "
              "origem, instrumento_id) VALUES (3, '2024-06', 2026, '2026-07', 101, 'apostilamento', ?)", (gprev,))
    c.execute("UPDATE instrumentos SET data_base_mes = NULL")
    c.commit()
    yield c
    c.close()


def _reaplicar(conn):
    conn.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); conn.commit()
    db.migrate(conn)
    return dict(conn.execute("SELECT chave, data_base_mes FROM instrumentos").fetchall())


def test_055_preenche_pela_regra_que_valia(conn):
    assert _reaplicar(conn) == {"a-sem": "2024-06", "b-com": "2024-04", "b-sem": None, "g-prev": "2024-06",
                                "a-vazia": "2024-06", "par": None}


def test_055_roda_duas_vezes_sem_mexer_no_que_ja_tem_base(conn):
    primeira = _reaplicar(conn)
    conn.execute("UPDATE instrumentos SET data_base_mes='2024-04' WHERE chave='a-sem'"); conn.commit()
    assert _reaplicar(conn) == {**primeira, "a-sem": "2024-04"}
