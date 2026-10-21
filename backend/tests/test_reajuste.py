"""Ciclo do reajuste por data-base (spec §7.2)."""
import datetime
import json

import pytest

from app import auth, db, reajuste

D = datetime.date


@pytest.fixture
def cenario(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "admin")
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
              "VALUES ('MTPAR', '099/2024', 'Cultural', 'obra', 100)")
    cid = c.execute("SELECT MAX(id) FROM contratos").fetchone()[0]
    c.execute("INSERT INTO contrato_datas_base (contrato_id, mes, indice) VALUES (?, '2024-06', 'INCC-DI')", (cid,))
    c.commit()

    def pleito(data_base, ciclo, enviado_em):
        c.execute("INSERT INTO pleitos (contrato_id, tipo, origem, data_base_mes, ciclo, numero_oficio, situacao, "
                  "enviado_em) VALUES (?, 'reajuste', 'cadastro', ?, ?, 'CT-1-LT-2026', 'enviado', ?)",
                  (cid, data_base, ciclo, enviado_em))
        c.commit()

    def instrumento(tipo, data, dados):
        c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) VALUES (?, ?, ?, ?, ?)",
                  (cid, f"{tipo}-{data}", tipo, data, json.dumps(dados)))
        c.commit()

    yield c, {"contrato": cid, "pleito": pleito, "instrumento": instrumento}
    c.close()


def test_ciclo_corrente_e_janela_de_30_dias(cenario):
    c, ids = cenario                      # contrato com data-base 2024-06 (INCC-DI), sem pleito
    assert reajuste.ciclos(c, ids["contrato"], D(2026, 4, 30))[0]["ciclo"] == 2025  # jun/2026 - 30 dias ainda nao
    r = reajuste.ciclos(c, ids["contrato"], D(2026, 5, 2))[0]
    assert (r["ciclo"], r["situacao"], r["dias"]) == (2026, "pleito_pendente", 30)


def test_pleito_enviado_vira_apostilamento_pendente_e_apostilamento_fecha(cenario):
    c, ids = cenario
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    r = reajuste.ciclos(c, ids["contrato"], D(2026, 9, 10))[0]
    assert (r["situacao"], r["dias"]) == ("apostilamento_pendente", 92)
    ids["instrumento"]("apostilamento_reajuste", "2026-09-15", {"data_base": "2024-06", "ciclo": 2026, "percentual": "6,76"})
    assert reajuste.ciclos(c, ids["contrato"], D(2026, 9, 20))[0]["situacao"] == "apostilado"


def test_avisos_niveis_e_diretoria_depois_de_90_dias(cenario):
    c, ids = cenario
    a = {x["tipo"]: x for x in reajuste.avisos(c, D(2026, 6, 15))}
    assert a["reajuste_pleito"]["nivel"] == "acao"          # aniversario ja passou
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    a = {x["tipo"]: x for x in reajuste.avisos(c, D(2026, 9, 10))}
    assert "diretoria" in a["reajuste_apostilamento"]["publico"]
    a = {x["tipo"]: x for x in reajuste.avisos(c, D(2026, 7, 10))}
    assert a["reajuste_apostilamento"]["publico"] == ["operacao"]


def test_aviso_diz_a_data_base(cenario):
    # A10: o aviso leva ao ciclo da data-base na aba Reajuste, nao so' a aba
    c, ids = cenario
    assert [a["data_base_mes"] for a in reajuste.avisos(c, D(2026, 6, 15))] == ["2024-06"]
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    assert [(a["tipo"], a["data_base_mes"]) for a in reajuste.avisos(c, D(2026, 9, 10))] ==         [("reajuste_apostilamento", "2024-06")]


def test_sem_reajuste_desliga(cenario):
    c, ids = cenario
    c.execute("UPDATE contratos SET sem_reajuste=1 WHERE id=?", (ids["contrato"],)); c.commit()
    assert reajuste.ciclos(c, ids["contrato"], D(2026, 6, 15)) == []


def _previsao(c, cid, competencia, valor, origem, data_base="2024-06", ciclo=2026, pleito_id=None,
              instrumento_id=None, criado_em="2026-07-01 10:00:00"):
    c.execute("INSERT INTO reajuste_previsoes (contrato_id, data_base_mes, ciclo, competencia, "
              "valor_previsto_centavos, origem, pleito_id, instrumento_id, criado_em) VALUES (?,?,?,?,?,?,?,?,?)",
              (cid, data_base, ciclo, competencia, valor, origem, pleito_id, instrumento_id, criado_em))
    c.commit()


def test_previsao_vigente_pela_ordem_apostilamento_pleito_manual(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    pid = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    ids["instrumento"]("apostilamento_reajuste", "2026-09-15", {"data_base": "2024-06", "ciclo": 2026})
    iid = c.execute("SELECT MAX(id) FROM instrumentos").fetchone()[0]
    # 2026-07: manual mais novo que o pleito, mas o pleito e' origem mais forte
    _previsao(c, cid, "2026-07", 100_01, "pleito", pleito_id=pid, criado_em="2026-06-10 09:00:00")
    _previsao(c, cid, "2026-07", 999_99, "manual", criado_em="2026-08-01 09:00:00")
    # 2026-08: apostilamento vence pleito e manual, mesmo sendo o mais antigo
    _previsao(c, cid, "2026-08", 777_77, "apostilamento", instrumento_id=iid, criado_em="2026-06-01 09:00:00")
    _previsao(c, cid, "2026-08", 200_03, "pleito", pleito_id=pid, criado_em="2026-06-10 09:00:00")
    _previsao(c, cid, "2026-08", 300_05, "manual", criado_em="2026-09-20 09:00:00")
    # 2026-09: so' manual; dentro da mesma origem vale a mais recente (correcao e' evento novo)
    _previsao(c, cid, "2026-09", 50_01, "manual", criado_em="2026-07-01 09:00:00")
    _previsao(c, cid, "2026-09", 49_99, "manual", criado_em="2026-07-02 09:00:00")
    # 2026-10: reemissao do pleito (mais recente) vence o pleito anterior; manual nao interfere
    _previsao(c, cid, "2026-10", 400_01, "pleito", pleito_id=pid, criado_em="2026-06-10 09:00:00")
    _previsao(c, cid, "2026-10", 1_00, "manual", criado_em="2026-11-01 09:00:00")
    _previsao(c, cid, "2026-10", 410_03, "pleito", pleito_id=pid, criado_em="2026-10-05 09:00:00")
    # 2026-11: mesma origem e mesmo segundo: desempata pela ordem de gravacao
    _previsao(c, cid, "2026-11", 7_01, "manual", criado_em="2026-10-05 09:00:00")
    _previsao(c, cid, "2026-11", 7_03, "manual", criado_em="2026-10-05 09:00:00")
    vig = {(p["data_base_mes"], p["competencia"]): (p["valor_previsto_centavos"], p["origem"])
           for p in reajuste.previsoes_vigentes(c, cid)}
    assert vig == {("2024-06", "2026-07"): (100_01, "pleito"),
                   ("2024-06", "2026-08"): (777_77, "apostilamento"),
                   ("2024-06", "2026-09"): (49_99, "manual"),
                   ("2024-06", "2026-10"): (410_03, "pleito"),
                   ("2024-06", "2026-11"): (7_03, "manual")}
    assert [p["competencia"] for p in reajuste.previsoes_vigentes(c, cid)] == [
        "2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]


def test_previsao_vigente_separa_as_datas_base_e_o_contrato(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
              "VALUES ('MTPAR', '100/2024', 'Outra', 'obra', 100)")
    outro = c.execute("SELECT MAX(id) FROM contratos").fetchone()[0]
    _previsao(c, cid, "2026-07", 10_01, "manual", data_base="2024-06")
    _previsao(c, cid, "2026-07", 20_03, "manual", data_base="2024-03")
    _previsao(c, outro, "2026-07", 30_05, "manual")
    assert [(p["data_base_mes"], p["valor_previsto_centavos"]) for p in reajuste.previsoes_vigentes(c, cid)] == [
        ("2024-03", 20_03), ("2024-06", 10_01)]
    assert [p["valor_previsto_centavos"] for p in reajuste.previsoes_vigentes(c, cid, data_base_mes="2024-06")] \
        == [10_01]
