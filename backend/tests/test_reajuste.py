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


def test_duas_datas_base_geram_dois_avisos_com_aplica_a(cenario):
    # D7 (2026-10-20): duas bases no mesmo contrato, cada uma com o seu aniversario e a parte a que se aplica
    c, ids = cenario
    c.execute("UPDATE contrato_datas_base SET aplica_a='itens SINAPI' WHERE contrato_id=?", (ids["contrato"],))
    c.execute("INSERT INTO contrato_datas_base (contrato_id, mes, indice, aplica_a) "
              "VALUES (?, '2024-09', 'FGV/DNIT', 'itens SICRO')", (ids["contrato"],))
    c.commit()
    k = reajuste.ciclos(c, ids["contrato"], D(2026, 9, 1))
    assert [(x["data_base_mes"], x["aplica_a"]) for x in k] == [("2024-06", "itens SINAPI"), ("2024-09", "itens SICRO")]
    av = [a for a in reajuste.avisos(c, D(2026, 9, 1)) if a["tipo"] == "reajuste_pleito"]
    assert [a["data_base_mes"] for a in av] == ["2024-06", "2024-09"]
    assert "data-base 06/2024 (itens SINAPI)" in av[0]["mensagem"]
    assert "data-base 09/2024 (itens SICRO)" in av[1]["mensagem"]


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
    assert reajuste.previsoes_vigentes(c, cid, data_base_mes="") == []


def test_previsao_de_pleito_descartado_nao_vale_e_o_manual_vence(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    pid = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    _previsao(c, cid, "2026-07", 100_01, "pleito", pleito_id=pid, criado_em="2026-06-10 09:00:00")
    _previsao(c, cid, "2026-07", 99_99, "manual", criado_em="2026-07-01 09:00:00")
    assert [p["valor_previsto_centavos"] for p in reajuste.previsoes_vigentes(c, cid)] == [100_01]
    c.execute("UPDATE pleitos SET situacao='descartado' WHERE id=?", (pid,)); c.commit()
    assert [(p["valor_previsto_centavos"], p["origem"]) for p in reajuste.previsoes_vigentes(c, cid)] == [
        (99_99, "manual")]


def test_reemissao_enviada_substitui_o_cronograma_do_pleito_anterior(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    antigo = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    _previsao(c, cid, "2026-07", 100_01, "pleito", pleito_id=antigo)
    _previsao(c, cid, "2026-08", 200_03, "pleito", pleito_id=antigo)    # a reemissao nao traz 2026-08
    _previsao(c, cid, "2026-08", 150_05, "manual")
    c.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo, situacao, reemite_pleito_id) "
              "VALUES (?, 'reajuste', '2024-06', 2026, 'rascunho', ?)", (cid, antigo))
    novo = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    _previsao(c, cid, "2026-07", 110_07, "pleito", pleito_id=novo, criado_em="2026-10-01 09:00:00")
    c.commit()
    vig = lambda: {p["competencia"]: (p["valor_previsto_centavos"], p["origem"])  # noqa: E731
                   for p in reajuste.previsoes_vigentes(c, cid)}
    # reemissao em rascunho: o anterior segue valendo onde a nova nao diz nada
    assert vig() == {"2026-07": (110_07, "pleito"), "2026-08": (200_03, "pleito")}
    c.execute("UPDATE pleitos SET situacao='enviado', enviado_em='2026-10-02' WHERE id=?", (novo,)); c.commit()
    assert vig() == {"2026-07": (110_07, "pleito"), "2026-08": (150_05, "manual")}


def test_reiteracao_enviada_nao_derruba_o_cronograma_e_a_reemissao_depois_dela_derruba(cenario):
    """Issue #277: a reiteracao (familia B) nao traz cronograma; o do pleito reiterado segue valendo. A reemissao
    do cronograma feita depois da reiteracao derruba o pleito original, pela cadeia."""
    c, ids = cenario
    cid = ids["contrato"]
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    original = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    _previsao(c, cid, "2026-07", 100_01, "pleito", pleito_id=original)
    c.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo, situacao, enviado_em, reemite_pleito_id, "
              "reemissao) VALUES (?, 'reajuste', '2024-06', 2026, 'enviado', '2026-10-01', ?, 'reiteracao')",
              (cid, original))
    reiteracao = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    c.commit()
    vig = lambda: {p["competencia"]: (p["valor_previsto_centavos"], p["pleito_id"])  # noqa: E731
                   for p in reajuste.previsoes_vigentes(c, cid)}
    assert vig() == {"2026-07": (100_01, original)}
    c.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo, situacao, enviado_em, reemite_pleito_id, "
              "reemissao) VALUES (?, 'reajuste', '2024-06', 2026, 'enviado', '2026-10-20', ?, 'cronograma')",
              (cid, reiteracao))
    novo = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    _previsao(c, cid, "2026-08", 200_03, "pleito", pleito_id=novo)
    c.commit()
    assert vig() == {"2026-08": (200_03, novo)}


def test_previsao_vigente_compara_a_hora_e_nao_o_texto(cenario):
    """Carga com data ISO ('T') ou so' o dia nao pode passar na frente de um registro mais novo."""
    c, ids = cenario
    cid = ids["contrato"]
    _previsao(c, cid, "2026-07", 1_01, "manual", criado_em="2026-10-05 12:00:00")
    _previsao(c, cid, "2026-07", 2_03, "manual", criado_em="2026-10-05T10:00:00")
    _previsao(c, cid, "2026-08", 3_05, "manual", criado_em="2026-10-06")
    _previsao(c, cid, "2026-08", 4_07, "manual", criado_em="2026-10-05 23:00:00")
    assert [p["valor_previsto_centavos"] for p in reajuste.previsoes_vigentes(c, cid)] == [1_01, 3_05]
