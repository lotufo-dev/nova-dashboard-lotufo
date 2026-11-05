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
    # o cadastro liga o pleito ao termo que o atendeu (issue #271): e' essa ligacao que fecha o ciclo
    c.execute("UPDATE pleitos SET instrumento_chave='apostilamento_reajuste-2026-09-15'"); c.commit()
    assert reajuste.ciclos(c, ids["contrato"], D(2026, 9, 20))[0]["situacao"] == "apostilado"


def test_termo_do_ciclo_sem_ligacao_nao_atende_o_pleito_vigente(cenario):
    # gate Sol (PR #317): com pleito enviado, quem fecha o ciclo e' o termo ligado a ele; termo do ciclo que nao o
    # atendeu (ex.: reemissao enviada depois do termo) deixa o apostilamento pendente, com o aviso
    c, ids = cenario
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    ids["instrumento"]("apostilamento_reajuste", "2026-09-15", {"data_base": "2024-06", "ciclo": 2026, "percentual": "6,76"})
    r = reajuste.ciclos(c, ids["contrato"], D(2026, 9, 20))[0]
    assert (r["situacao"], r["dias"], r["apostilamento"]) == ("apostilamento_pendente", 102, None)
    assert [a["tipo"] for a in reajuste.avisos(c, D(2026, 9, 20))] == ["reajuste_apostilamento"]
    c.execute("UPDATE pleitos SET instrumento_chave='apostilamento_reajuste-2026-09-15'"); c.commit()
    r = reajuste.ciclos(c, ids["contrato"], D(2026, 9, 20))[0]
    assert (r["situacao"], r["apostilamento"]["chave"]) == ("apostilado", "apostilamento_reajuste-2026-09-15")
    assert reajuste.avisos(c, D(2026, 9, 20)) == []


def test_reiteracao_enviada_depois_do_termo_nao_reabre_o_ciclo(cenario):
    # revisor (PR #317, R1): P1 em 10/06, termo de 15/09, reiteracao R em 20/09; o aplicar liga P1 (ultimo enviado
    # ate' a data do termo). A reiteracao nao traz cronograma: o termo ligado ao pedido fecha o ciclo
    c, ids = cenario
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    p1 = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    c.execute("INSERT INTO pleitos (contrato_id, tipo, origem, data_base_mes, ciclo, numero_oficio, situacao, enviado_em, "
              "reemite_pleito_id, reemissao) VALUES (?, 'reajuste', 'sistema', '2024-06', 2026, 'CT-2-LT-2026', "
              "'enviado', '2026-09-20', ?, 'reiteracao')", (ids["contrato"], p1))
    ids["instrumento"]("apostilamento_reajuste", "2026-09-15", {"data_base": "2024-06", "ciclo": 2026, "percentual": "6,76"})
    c.execute("UPDATE pleitos SET instrumento_chave='apostilamento_reajuste-2026-09-15' WHERE id=?", (p1,)); c.commit()
    r = reajuste.ciclos(c, ids["contrato"], D(2026, 10, 30))[0]
    assert (r["situacao"], r["apostilamento"]["chave"]) == ("apostilado", "apostilamento_reajuste-2026-09-15")
    assert reajuste.avisos(c, D(2026, 10, 30)) == []


def test_reemissao_do_cronograma_depois_do_termo_espera_o_dela(cenario):
    # a reemissao do cronograma traz pedido novo: o termo ligado ao pleito anterior nao a atende
    c, ids = cenario
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    p1 = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    c.execute("INSERT INTO pleitos (contrato_id, tipo, origem, data_base_mes, ciclo, numero_oficio, situacao, enviado_em, "
              "reemite_pleito_id, reemissao) VALUES (?, 'reajuste', 'sistema', '2024-06', 2026, 'CT-2-LT-2026', "
              "'enviado', '2026-09-20', ?, 'cronograma')", (ids["contrato"], p1))
    ids["instrumento"]("apostilamento_reajuste", "2026-09-15", {"data_base": "2024-06", "ciclo": 2026, "percentual": "6,76"})
    c.execute("UPDATE pleitos SET instrumento_chave='apostilamento_reajuste-2026-09-15' WHERE id=?", (p1,)); c.commit()
    assert reajuste.ciclos(c, ids["contrato"], D(2026, 10, 30))[0]["situacao"] == "apostilamento_pendente"


def test_sem_pleito_enviado_o_termo_do_ciclo_fecha_o_ciclo(cenario):
    # pleito feito fora do sistema e nao registrado: nao ha' pleito a ligar, o termo do ciclo basta
    c, ids = cenario
    ids["instrumento"]("apostilamento_reajuste", "2026-09-15", {"data_base": "2024-06", "ciclo": 2026, "percentual": "6,76"})
    assert reajuste.ciclos(c, ids["contrato"], D(2026, 9, 20))[0]["situacao"] == "apostilado"


def _termo_sem_base_aplicado_e_segunda_base(c, ids):
    """Termo sem `data_base` aplicado quando o contrato tinha uma base so' (o aplicar guardou a 2024-06 no termo,
    migracao 055); depois o contrato ganha a 2a data-base (revisor e gate Sol, rodada 3, PR #317). O caminho inteiro
    pelo aplicar esta' em test_cadastro_aplicar."""
    ids["instrumento"]("apostilamento_reajuste", "2026-09-15", {"ciclo": 2026, "percentual": "6,76"})
    iid = c.execute("SELECT MAX(id) FROM instrumentos").fetchone()[0]
    c.execute("UPDATE instrumentos SET data_base_mes='2024-06' WHERE id=?", (iid,))
    c.execute("INSERT INTO contrato_datas_base (contrato_id, mes, indice) VALUES (?, '2024-04', 'SICRO')", (ids["contrato"],))
    c.commit()
    return iid


def test_termo_sem_data_base_segue_fechando_o_ciclo_depois_da_segunda_base(cenario):
    # sem pleito registrado, o termo fecha o ciclo da base em que gravou as previsoes; nao vira "ambiguo"
    c, ids = cenario
    _termo_sem_base_aplicado_e_segunda_base(c, ids)
    k = {x["data_base_mes"]: x for x in reajuste.ciclos(c, ids["contrato"], D(2026, 9, 20))}
    assert (k["2024-06"]["situacao"], k["2024-06"]["apostilamento"]["chave"]) == \
        ("apostilado", "apostilamento_reajuste-2026-09-15")
    assert k["2024-04"]["situacao"] == "pleito_pendente"       # o termo nao vai para a outra base
    assert [a["data_base_mes"] for a in reajuste.avisos(c, D(2026, 9, 20))] == ["2024-04"]


def test_base_dos_termos_resolvida_para_a_aba(cenario):
    # a aba recebe a base de cada termo: `data_base`, senao a guardada no termo, senao a unica; sem nenhuma, None
    c, ids = cenario
    iid = _termo_sem_base_aplicado_e_segunda_base(c, ids)
    ids["instrumento"]("apostilamento_reajuste", "2026-10-01", {"data_base": "2024-04", "ciclo": 2026})
    ids["instrumento"]("apostilamento_reajuste", "2026-10-02", {"ciclo": 2026})
    bases = {x["instrumento_id"]: x["data_base_mes"] for x in reajuste.bases_dos_termos(c, ids["contrato"])}
    assert [bases[iid], bases[iid + 1], bases[iid + 2]] == ["2024-06", "2024-04", None]


def _reiteracao(c, cid, anterior, enviado_em, numero):
    c.execute("INSERT INTO pleitos (contrato_id, tipo, origem, data_base_mes, ciclo, numero_oficio, situacao, enviado_em, "
              "reemite_pleito_id, reemissao) VALUES (?, 'reajuste', 'sistema', '2024-06', 2026, ?, 'enviado', ?, ?, "
              "'reiteracao')", (cid, numero, enviado_em, anterior))
    c.commit()
    return c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]


def test_termo_do_pedido_sobe_por_duas_reiteracoes(cenario):
    # P1 <- R1 <- R2: o termo ligado a P1 fecha o ciclo com R2 como pleito vigente
    c, ids = cenario
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    p1 = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    r1 = _reiteracao(c, ids["contrato"], p1, "2026-08-10", "CT-2-LT-2026")
    _reiteracao(c, ids["contrato"], r1, "2026-09-20", "CT-3-LT-2026")
    ids["instrumento"]("apostilamento_reajuste", "2026-09-15", {"data_base": "2024-06", "ciclo": 2026})
    c.execute("UPDATE pleitos SET instrumento_chave='apostilamento_reajuste-2026-09-15' WHERE id=?", (p1,)); c.commit()
    r = reajuste.ciclos(c, ids["contrato"], D(2026, 10, 30))[0]
    assert (r["situacao"], r["apostilamento"]["chave"]) == ("apostilado", "apostilamento_reajuste-2026-09-15")


def test_laco_em_reemite_pleito_id_nao_trava_e_fica_pendente(cenario):
    # dado torto (R1 reitera R2 e R2 reitera R1): a subida para no laco, sem termo
    c, ids = cenario
    r1 = _reiteracao(c, ids["contrato"], None, "2026-08-10", "CT-2-LT-2026")
    r2 = _reiteracao(c, ids["contrato"], r1, "2026-09-20", "CT-3-LT-2026")
    c.execute("UPDATE pleitos SET reemite_pleito_id=? WHERE id=?", (r2, r1)); c.commit()
    assert reajuste.ciclos(c, ids["contrato"], D(2026, 10, 30))[0]["situacao"] == "apostilamento_pendente"


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


def test_reemissao_enviada_sem_previsoes_proprias_nao_derruba_o_anterior(cenario):
    """Gate Sol da PR #319: a reemissao enviada so' derruba o cronograma do anterior quando ja' tem previsoes
    gravadas (a leitura da planilha e' outro passo); antes disso o previsto do anterior segue valendo."""
    c, ids = cenario
    cid = ids["contrato"]
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    antigo = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    _previsao(c, cid, "2026-07", 100_01, "pleito", pleito_id=antigo)
    c.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo, situacao, enviado_em, reemite_pleito_id, "
              "reemissao) VALUES (?, 'reajuste', '2024-06', 2026, 'enviado', '2026-10-02', ?, 'cronograma')",
              (cid, antigo))
    novo = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    c.commit()
    vig = lambda: {p["competencia"]: (p["valor_previsto_centavos"], p["pleito_id"])  # noqa: E731
                   for p in reajuste.previsoes_vigentes(c, cid)}
    assert vig() == {"2026-07": (100_01, antigo)}                       # sem previsoes da reemissao: o anterior fica
    _previsao(c, cid, "2026-08", 300_05, "pleito", pleito_id=novo)
    assert vig() == {"2026-08": (300_05, novo)}                         # com elas, o anterior sai


@pytest.mark.parametrize("com_reiteracao", [False, True])
def test_reemissao_com_previsoes_derruba_a_cadeia_inteira_ate_o_ultimo_cronograma(cenario, com_reiteracao):
    """Gates da PR #319, rodada 2: P1 (com previsoes) -> P2 reemissao sem previsoes [-> reiteracao] -> P3 com
    previsoes. P3 derruba P2 e P1: nenhuma competencia de P1 que P3 nao traz sobra (sem cronograma hibrido)."""
    c, ids = cenario
    cid = ids["contrato"]
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    p1 = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    _previsao(c, cid, "2026-07", 100_01, "pleito", pleito_id=p1)
    _previsao(c, cid, "2026-09", 999_99, "pleito", pleito_id=p1)

    def reemite(anterior, reemissao, enviado_em):
        c.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo, situacao, enviado_em, "
                  "reemite_pleito_id, reemissao) VALUES (?, 'reajuste', '2024-06', 2026, 'enviado', ?, ?, ?)",
                  (cid, enviado_em, anterior, reemissao))
        c.commit()
        return c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]

    p2 = reemite(p1, "cronograma", "2026-08-01")                       # sem previsoes proprias
    meio = reemite(p2, "reiteracao", "2026-09-01") if com_reiteracao else p2
    vig = lambda: {p["competencia"]: (p["valor_previsto_centavos"], p["pleito_id"])  # noqa: E731
                   for p in reajuste.previsoes_vigentes(c, cid)}
    assert vig() == {"2026-07": (100_01, p1), "2026-09": (999_99, p1)}  # P2 vazio ainda nao derruba P1
    p3 = reemite(meio, "cronograma", "2026-10-01")
    _previsao(c, cid, "2026-07", 110_03, "pleito", pleito_id=p3)
    _previsao(c, cid, "2026-08", 300_05, "pleito", pleito_id=p3)
    assert vig() == {"2026-07": (110_03, p3), "2026-08": (300_05, p3)}


def test_reiteracao_nao_zera_a_espera_do_apostilamento_nem_tira_a_diretoria(cenario):
    """Revisor da PR #319: original ha' mais de 90 dias e reiteracao hoje; o atraso conta do pedido original."""
    c, ids = cenario
    cid = ids["contrato"]
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    original = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    c.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo, situacao, enviado_em, reemite_pleito_id, "
              "reemissao) VALUES (?, 'reajuste', '2024-06', 2026, 'enviado', '2026-10-10', ?, 'reiteracao')",
              (cid, original))
    reiteracao = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    c.commit()
    k = reajuste.ciclos(c, cid, D(2026, 10, 10))[0]
    assert (k["pleito"]["id"], k["pedido"]["id"], k["dias"]) == (reiteracao, original, 122)
    a = {x["tipo"]: x for x in reajuste.avisos(c, D(2026, 10, 10))}["reajuste_apostilamento"]
    assert "diretoria" in a["publico"] and (a["dias"], a["data"]) == (122, "2026-06-10")
    # a reemissao do cronograma e' pedido novo: a espera recomeca dela
    c.execute("INSERT INTO pleitos (contrato_id, tipo, data_base_mes, ciclo, situacao, enviado_em, reemite_pleito_id, "
              "reemissao) VALUES (?, 'reajuste', '2024-06', 2026, 'enviado', '2026-10-20', ?, 'cronograma')",
              (cid, reiteracao))
    c.commit()
    assert reajuste.ciclos(c, cid, D(2026, 10, 25))[0]["dias"] == 5


def test_previsao_vigente_compara_a_hora_e_nao_o_texto(cenario):
    """Carga com data ISO ('T') ou so' o dia nao pode passar na frente de um registro mais novo."""
    c, ids = cenario
    cid = ids["contrato"]
    _previsao(c, cid, "2026-07", 1_01, "manual", criado_em="2026-10-05 12:00:00")
    _previsao(c, cid, "2026-07", 2_03, "manual", criado_em="2026-10-05T10:00:00")
    _previsao(c, cid, "2026-08", 3_05, "manual", criado_em="2026-10-06")
    _previsao(c, cid, "2026-08", 4_07, "manual", criado_em="2026-10-05 23:00:00")
    assert [p["valor_previsto_centavos"] for p in reajuste.previsoes_vigentes(c, cid)] == [1_01, 3_05]


def test_previsao_digitada_no_pleito_descartado_tambem_sai_da_conta(cenario):
    """Issue #272: a digitada (manual) aponta o pleito em que foi feita; descartado o pleito, ela deixa de valer,
    e a manual sem pleito continua."""
    c, ids = cenario
    cid = ids["contrato"]
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    pid = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    _previsao(c, cid, "2026-07", 100_01, "manual", pleito_id=pid, criado_em="2026-07-01 09:00:00")
    _previsao(c, cid, "2026-08", 5_03, "manual", criado_em="2026-07-01 09:00:00")
    assert [p["valor_previsto_centavos"] for p in reajuste.previsoes_vigentes(c, cid)] == [100_01, 5_03]
    c.execute("UPDATE pleitos SET situacao='descartado' WHERE id=?", (pid,)); c.commit()
    assert [p["valor_previsto_centavos"] for p in reajuste.previsoes_vigentes(c, cid)] == [5_03]


def test_competencias_apostiladas_vigentes_com_o_termo_e_a_medicao(cenario):
    """Issue #271: a aba Reajuste le' as competencias apostiladas vigentes, com o termo que as traz e o nº da
    medicao que o termo cita; a previsao de pleito ou manual nao entra."""
    c, ids = cenario
    cid = ids["contrato"]
    for chave, data, comps in (("ap-1", "2026-09-15", [{"competencia": "2026-07", "valor": "100,01", "medicao": 30},
                                                       {"competencia": "2026-08", "valor": "200,03"}]),
                               ("ap-2", "2026-10-01", [{"competencia": "2026-07", "valor": "110,05", "medicao": 30}])):
        c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, numero, data, dados) "
                  "VALUES (?, ?, 'apostilamento_reajuste', ?, ?, ?)",
                  (cid, chave, f"{chave}/2026", data, json.dumps({"ciclo": 2026, "competencias": comps})))
    ap1, ap2 = [r[0] for r in c.execute("SELECT id FROM instrumentos ORDER BY id")]
    _previsao(c, cid, "2026-07", 100_01, "apostilamento", instrumento_id=ap1, criado_em="2026-09-15 10:00:00")
    _previsao(c, cid, "2026-08", 200_03, "apostilamento", instrumento_id=ap1, criado_em="2026-09-15 10:00:00")
    _previsao(c, cid, "2026-07", 110_05, "apostilamento", instrumento_id=ap2, criado_em="2026-10-01 10:00:00")
    _previsao(c, cid, "2026-09", 50_00, "manual")
    assert reajuste.competencias_apostiladas(c, cid) == [
        {"data_base_mes": "2024-06", "ciclo": 2026, "competencia": "2026-07", "valor_centavos": 110_05, "medicao": 30,
         "instrumento_chave": "ap-2", "instrumento_numero": "ap-2/2026", "instrumento_data": "2026-10-01"},
        {"data_base_mes": "2024-06", "ciclo": 2026, "competencia": "2026-08", "valor_centavos": 200_03, "medicao": None,
         "instrumento_chave": "ap-1", "instrumento_numero": "ap-1/2026", "instrumento_data": "2026-09-15"}]


# --- issue #273: estado do ciclo `reemitir` e estados por competencia (spec 2026-10-20 §2.2) ---

def _aditivo(c, cid, tipo, assinado_em, status="assinado"):
    c.execute("INSERT INTO aditivos (contrato_id, tipo, status, data_assinatura) VALUES (?,?,?,?)",
              (cid, tipo, status, assinado_em))
    c.commit()


def test_aditivo_depois_do_pleito_poe_o_ciclo_em_reemitir(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    _aditivo(c, cid, "prazo", "2026-06-01")                 # antes do pleito: nao pede reemissao
    _aditivo(c, cid, "escopo", "2026-07-01")                # escopo nao e' prazo nem valor
    _aditivo(c, cid, "valor", "2026-07-15", status="em_andamento")   # ainda nao assinado
    assert reajuste.ciclos(c, cid, D(2026, 9, 10))[0]["situacao"] == "apostilamento_pendente"
    _aditivo(c, cid, "prazo", "2026-08-01")
    r = reajuste.ciclos(c, cid, D(2026, 9, 10))[0]
    assert (r["situacao"], r["dias"], r["aditivo"]["data_assinatura"]) == ("reemitir", 92, "2026-08-01")
    # o ciclo continua sem apostilamento: o aviso segue valendo
    assert [a["tipo"] for a in reajuste.avisos(c, D(2026, 9, 10))] == ["reajuste_apostilamento"]


def test_reiteracao_depois_do_aditivo_nao_tira_do_reemitir_e_a_reemissao_tira(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    p1 = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    _aditivo(c, cid, "misto", "2026-08-01")
    _reiteracao(c, cid, p1, "2026-08-20", "CT-2-LT-2026")
    assert reajuste.ciclos(c, cid, D(2026, 9, 10))[0]["situacao"] == "reemitir"
    c.execute("INSERT INTO pleitos (contrato_id, tipo, origem, data_base_mes, ciclo, numero_oficio, situacao, enviado_em, "
              "reemite_pleito_id, reemissao) VALUES (?, 'reajuste', 'sistema', '2024-06', 2026, 'CT-3-LT-2026', "
              "'enviado', '2026-09-01', ?, 'cronograma')", (cid, p1))
    c.commit()
    r = reajuste.ciclos(c, cid, D(2026, 9, 10))[0]
    assert (r["situacao"], r["dias"], r["aditivo"]) == ("apostilamento_pendente", 9, None)


def test_ciclo_apostilado_nao_vai_para_reemitir(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    ids["pleito"](data_base="2024-06", ciclo=2026, enviado_em="2026-06-10")
    ids["instrumento"]("apostilamento_reajuste", "2026-07-15", {"data_base": "2024-06", "ciclo": 2026, "percentual": "6,76"})
    c.execute("UPDATE pleitos SET instrumento_chave='apostilamento_reajuste-2026-07-15'"); c.commit()
    _aditivo(c, cid, "prazo", "2026-08-01")
    assert reajuste.ciclos(c, cid, D(2026, 9, 10))[0]["situacao"] == "apostilado"


def _medicao(c, cid, numero, competencia, estado, pedido=None, aprovado=None, data_base=None, ciclo=None):
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
              "valor_atestado_centavos, data_base_mes, ciclo) VALUES (?, ?, 'reajuste', ?, ?, ?, ?, ?, ?)",
              (cid, numero, competencia, estado, pedido, aprovado, data_base, ciclo))
    c.commit()
    return c.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]


def _nota(c, medicao_id, valor, situacao="ativa"):
    c.execute("INSERT INTO notas_fiscais (coligada, numero, valor_centavos, situacao, origem) VALUES (1, ?, ?, ?, 'pdf')",
              (f"NF-{medicao_id}", valor, situacao))
    nid = c.execute("SELECT MAX(id) FROM notas_fiscais").fetchone()[0]
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem) VALUES (?, ?, ?, 'manual')",
              (medicao_id, nid, valor))
    c.commit()


def _por_competencia(c, cid, data_base="2024-06", ciclo=2026):
    grupo = next(g for g in reajuste.competencias_por_ciclo(c, cid)
                 if (g["data_base_mes"], g["ciclo"]) == (data_base, ciclo))
    return {x["competencia"]: x for x in grupo["competencias"]}


def test_estado_de_cada_competencia_do_ciclo(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    for comp, valor in (("2026-07", 100_01), ("2026-08", 200_03), ("2026-09", 300_05), ("2026-11", 500_07),
                        ("2026-12", 600_09)):
        _previsao(c, cid, comp, valor, "manual")
    ids["instrumento"]("apostilamento_reajuste", "2026-10-20",
                       {"data_base": "2024-06", "ciclo": 2026,
                        "competencias": [{"competencia": "2026-10", "valor": "400,11", "medicao": 4}]})
    ap = c.execute("SELECT MAX(id) FROM instrumentos").fetchone()[0]
    _previsao(c, cid, "2026-10", 400_11, "apostilamento", instrumento_id=ap, criado_em="2026-10-20 10:00:00")
    _medicao(c, cid, 2, "2026-08", "planilha_enviada", pedido=201_01)
    _medicao(c, cid, 3, "2026-09", "boletim_recebido", pedido=300_05, aprovado=299_99)
    _medicao(c, cid, 4, "2026-10", "planilha_gerada", pedido=400_11)
    m5 = _medicao(c, cid, 5, "2026-11", "nota_emitida", pedido=500_07, aprovado=500_07)
    _nota(c, m5, 500_07)
    m6 = _medicao(c, cid, 6, "2026-12", "recebida", pedido=600_09, aprovado=600_09)
    _nota(c, m6, 600_09)
    _medicao(c, cid, 7, "2026-12", "cancelada", pedido=1)          # cancelada nao conta

    x = _por_competencia(c, cid)
    assert {k: v["estado"] for k, v in x.items()} == {
        "2026-07": "prevista", "2026-08": "pedida", "2026-09": "aprovada", "2026-10": "apostilada",
        "2026-11": "faturada", "2026-12": "recebida"}
    assert (x["2026-07"]["previsto_centavos"], x["2026-07"]["previsto_origem"], x["2026-07"]["pedido_centavos"]) == \
        (100_01, "manual", None)
    assert (x["2026-08"]["previsto_centavos"], x["2026-08"]["pedido_centavos"]) == (200_03, 201_01)
    assert (x["2026-09"]["pedido_centavos"], x["2026-09"]["aprovado_centavos"]) == (300_05, 299_99)
    assert (x["2026-10"]["apostilado_centavos"], x["2026-10"]["apostilamento_chave"], x["2026-10"]["apostilada"]) == \
        (400_11, "apostilamento_reajuste-2026-10-20", True)
    assert (x["2026-11"]["faturado_centavos"], x["2026-11"]["apostilada"], x["2026-11"]["recebida_em"]) == \
        (500_07, False, None)
    assert (x["2026-12"]["medicao_numero"], x["2026-12"]["faturado_centavos"]) == (6, 600_09)


def test_nota_cancelada_e_alocacao_desfeita_nao_faturam(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _previsao(c, cid, "2026-07", 100_01, "manual")
    m = _medicao(c, cid, 1, "2026-07", "boletim_recebido", pedido=100_01, aprovado=100_01)
    _nota(c, m, 100_01, situacao="cancelada")
    _previsao(c, cid, "2026-08", 200_03, "manual")
    m2 = _medicao(c, cid, 2, "2026-08", "boletim_recebido", pedido=200_03, aprovado=200_03)
    _nota(c, m2, 200_03)
    c.execute("UPDATE nf_alocacoes SET desfeita_em='2026-09-01', motivo_desfazer='errada' WHERE medicao_id=?", (m2,))
    c.commit()
    x = _por_competencia(c, cid)
    assert [(x[k]["estado"], x[k]["faturado_centavos"]) for k in ("2026-07", "2026-08")] == \
        [("aprovada", None), ("aprovada", None)]


def test_faturado_soma_as_notas_da_medicao_com_centavo_impar(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    m = _medicao(c, cid, 1, "2026-07", "nota_emitida", pedido=500_07, aprovado=500_07)
    _nota(c, m, 250_03)
    _nota(c, m, 250_04)
    x = _por_competencia(c, cid)["2026-07"]
    assert (x["estado"], x["faturado_centavos"]) == ("faturada", 500_07)


def test_complemento_na_mesma_competencia_nao_esconde_a_medicao_recebida(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    m3 = _medicao(c, cid, 3, "2026-09", "recebida", pedido=300_05, aprovado=300_05)
    _nota(c, m3, 300_05)
    _medicao(c, cid, 8, "2026-09", "prevista")
    x = _por_competencia(c, cid)["2026-09"]
    assert (x["estado"], x["medicao_numero"], x["faturado_centavos"]) == ("recebida", 3, 300_05)


def test_boletim_registrado_segue_aprovado_depois_do_espelho(cenario):
    # o espelho vem depois do boletim: a medicao que ja' passou dele nao volta a `pedida`
    c, ids = cenario
    cid = ids["contrato"]
    m = _medicao(c, cid, 1, "2026-07", "espelho_gerado", pedido=100_01)
    c.execute("INSERT INTO medicao_atestos (medicao_id, valor_centavos, origem, atestado_em) "
              "VALUES (?, 99_99, 'manual', '2026-08-10')", (m,))
    c.commit()
    _medicao(c, cid, 2, "2026-08", "espelho_enviado", pedido=200_03)
    x = _por_competencia(c, cid)
    assert (x["2026-07"]["estado"], x["2026-08"]["estado"]) == ("aprovada", "pedida")


def test_medicao_sem_motor_com_valor_pedido_vale_como_pedida(cenario):
    # enquanto o motor de medicao nao cobre tudo, a medicao de reajuste com valor pedido conta como pedida; a que
    # so' existe (prevista, sem valor) nao muda o estado
    c, ids = cenario
    cid = ids["contrato"]
    _previsao(c, cid, "2026-07", 100_01, "manual")
    _previsao(c, cid, "2026-08", 200_03, "manual")
    _medicao(c, cid, 1, "2026-07", "prevista", pedido=100_01)
    _medicao(c, cid, 2, "2026-08", "prevista")
    x = _por_competencia(c, cid)
    assert (x["2026-07"]["estado"], x["2026-08"]["estado"]) == ("pedida", "prevista")


def test_percentual_da_mtpar_com_periodo_apostila_as_competencias_cobertas(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    for comp in ("2026-05", "2026-06", "2027-05", "2027-06"):
        _previsao(c, cid, comp, 100_01, "manual")
    ids["instrumento"]("apostilamento_reajuste", "2026-09-15",
                       {"data_base": "2024-06", "ciclo": 2026, "percentual": "6,76",
                        "periodo": {"de": "2026-06", "ate": "2027-05"}})
    x = _por_competencia(c, cid)
    # cada mes do periodo entra, mesmo sem previsao digitada (gate Sol, rodada 1, PR #381)
    cobertos = [f"2026-{m:02d}" for m in range(6, 13)] + [f"2027-{m:02d}" for m in range(1, 6)]
    assert {k: (v["estado"], v["apostilada"]) for k, v in x.items()} == {
        "2026-05": ("prevista", False), **{k: ("apostilada", True) for k in cobertos}, "2027-06": ("prevista", False)}
    assert (x["2026-06"]["apostilado_centavos"], x["2026-06"]["apostilado_percentual"],
            x["2026-06"]["apostilamento_chave"]) == (None, "6,76", "apostilamento_reajuste-2026-09-15")
    assert (x["2026-07"]["previsto_centavos"], x["2026-07"]["estado"]) == (None, "apostilada")


def test_periodo_sem_percentual_so_delimita_as_competencias_da_lista(cenario):
    # gate Sol (rodada 1, PR #381): termo abril a junho com valores so' de abril e maio nao apostila junho
    c, ids = cenario
    cid = ids["contrato"]
    ids["instrumento"]("apostilamento_reajuste", "2026-09-15",
                       {"data_base": "2024-06", "ciclo": 2026, "periodo": {"de": "2026-07", "ate": "2026-09"},
                        "competencias": [{"competencia": "2026-07", "valor": "100,01"},
                                         {"competencia": "2026-08", "valor": "200,03"}]})
    ap = c.execute("SELECT MAX(id) FROM instrumentos").fetchone()[0]
    for comp, valor in (("2026-07", 100_01), ("2026-08", 200_03)):
        _previsao(c, cid, comp, valor, "apostilamento", instrumento_id=ap, criado_em="2026-09-15 10:00:00")
    _previsao(c, cid, "2026-09", 300_05, "manual")
    x = _por_competencia(c, cid)
    assert {k: (v["estado"], v["apostilado_centavos"]) for k, v in x.items()} == {
        "2026-07": ("apostilada", 100_01), "2026-08": ("apostilada", 200_03), "2026-09": ("prevista", None)}


def test_protocolada_sem_nota_e_pedida_e_com_nota_e_faturada(cenario):
    # revisor (rodada 1, PR #381): o protocolo promove prevista e planilha_gerada direto a protocolada, sem nota
    c, ids = cenario
    cid = ids["contrato"]
    _medicao(c, cid, 1, "2026-07", "protocolada", pedido=100_01)
    m2 = _medicao(c, cid, 2, "2026-08", "protocolada", pedido=200_03)
    c.execute("UPDATE medicoes SET nota_emitida_em='2026-09-01' WHERE id=?", (m2,))
    m3 = _medicao(c, cid, 3, "2026-09", "protocolada", pedido=300_05)
    _nota(c, m3, 300_05)
    c.commit()
    x = _por_competencia(c, cid)
    assert [(x[k]["estado"], x[k]["faturado_centavos"]) for k in ("2026-07", "2026-08", "2026-09")] == \
        [("pedida", None), ("faturada", None), ("faturada", 300_05)]


def test_faturado_em_consorcio_so_conta_a_nota_da_coligada_do_contrato(cenario):
    # gate Sol (rodada 1, PR #381): a medicao guarda o cheio; a fatura do consorcio (coligada dele) e' o faturado,
    # a NFS-e da Lotufo pela cota (outra coligada) nao soma por cima
    c, ids = cenario
    cid = ids["contrato"]
    c.execute("INSERT INTO entidades (nome, cnpj, papel, coligada_rm) VALUES ('Consórcio Exemplo', '31200303000181', "
              "'consorcio', 90)")
    c.execute("UPDATE contratos SET entidade_id=(SELECT MAX(id) FROM entidades) WHERE id=?", (cid,))
    m = _medicao(c, cid, 1, "2026-07", "nota_emitida", pedido=10_000_000_07)
    for numero, coligada, valor in (("21", 90, 10_000_000_07), ("3102", 1, 2_000_000_02)):
        c.execute("INSERT INTO notas_fiscais (coligada, numero, valor_centavos, origem) VALUES (?, ?, ?, 'pdf')",
                  (coligada, numero, valor))
        c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem) "
                  "VALUES (?, (SELECT MAX(id) FROM notas_fiscais), ?, 'manual')", (m, valor))
    c.commit()
    x = _por_competencia(c, cid)["2026-07"]
    assert (x["estado"], x["faturado_centavos"]) == ("faturada", 10_000_000_07)


def test_complemento_soma_pedido_aprovado_e_faturado_das_medicoes(cenario):
    # revisor (rodada 1, PR #381): o complemento aparece na linha da competencia
    c, ids = cenario
    cid = ids["contrato"]
    _previsao(c, cid, "2026-07", 12_000_00, "manual")
    m3 = _medicao(c, cid, 3, "2026-07", "recebida", pedido=10_000_00, aprovado=9_999_99)
    _nota(c, m3, 9_999_99)
    _medicao(c, cid, 7, "2026-07", "planilha_gerada", pedido=2_000_01)
    x = _por_competencia(c, cid)["2026-07"]
    assert (x["estado"], x["medicao_numero"], x["medicoes"], x["pedido_centavos"], x["aprovado_centavos"],
            x["faturado_centavos"]) == ("recebida", 3, [3, 7], 12_000_01, 9_999_99, 9_999_99)


def test_medicao_sem_base_em_contrato_de_duas_bases_nao_some(cenario):
    # gate Sol (rodadas 1 e 2, PR #381): duas datas-base com previsao da mesma competencia e medicao sem base
    # gravada: entra uma vez so', no grupo sem data-base, em vez de sumir ou de contar nas duas
    c, ids = cenario
    cid = ids["contrato"]
    c.execute("INSERT INTO contrato_datas_base (contrato_id, mes, indice) VALUES (?, '2024-08', 'SICRO')", (cid,))
    _previsao(c, cid, "2026-09", 100_01, "manual")
    _previsao(c, cid, "2026-09", 200_03, "manual", data_base="2024-08")
    _previsao(c, cid, "2026-10", 300_05, "manual", data_base="2024-08")
    _medicao(c, cid, 2, "2026-09", "planilha_gerada", pedido=300_04)
    _medicao(c, cid, 3, "2026-09", "planilha_gerada", pedido=50_01, data_base="2024-06", ciclo=2026)
    _medicao(c, cid, 4, "2026-10", "planilha_gerada", pedido=300_05)
    a = _por_competencia(c, cid)["2026-09"]
    b = _por_competencia(c, cid, data_base="2024-08")
    sem_base = _por_competencia(c, cid, data_base=None, ciclo=None)
    assert (a["estado"], a["pedido_centavos"], a["medicoes"], a["data_base_incerta"]) == ("pedida", 50_01, [3], False)
    assert (b["2026-09"]["estado"], b["2026-09"]["pedido_centavos"]) == ("prevista", None)
    assert list(sem_base) == ["2026-09"]
    assert (sem_base["2026-09"]["pedido_centavos"], sem_base["2026-09"]["medicoes"],
            sem_base["2026-09"]["data_base_incerta"]) == (300_04, [2], True)
    # somando todas as datas-base, cada medicao conta uma vez: 300,04 + 50,01 + 300,05
    total = sum(x["pedido_centavos"] or 0 for g in reajuste.competencias_por_ciclo(c, cid) for x in g["competencias"])
    assert total == 300_04 + 50_01 + 300_05
    # so' uma base tem previsao da competencia: vai para ela, sem incerteza
    assert (b["2026-10"]["estado"], b["2026-10"]["data_base_incerta"]) == ("pedida", False)
    assert "2026-10" not in _por_competencia(c, cid)
    assert reajuste.competencias_por_ciclo(c, cid)[-1]["data_base_mes"] is None      # o grupo sem base vai por ultimo


def test_nf_so_de_outra_coligada_nao_fatura_a_medicao_de_consorcio(cenario):
    # gate Sol e revisor (rodada 2, PR #381): em consorcio, a NFS-e da Lotufo (outra coligada) sozinha nao fatura
    c, ids = cenario
    cid = ids["contrato"]
    c.execute("INSERT INTO entidades (nome, cnpj, papel, coligada_rm) VALUES ('Consórcio Exemplo', '31200303000181', "
              "'consorcio', 90)")
    c.execute("UPDATE contratos SET entidade_id=(SELECT MAX(id) FROM entidades) WHERE id=?", (cid,))
    m = _medicao(c, cid, 1, "2026-07", "espelho_enviado", pedido=10_000_000_07)
    c.execute("INSERT INTO notas_fiscais (coligada, numero, valor_centavos, origem) VALUES (1, '3102', 2000000_02, 'pdf')")
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem) "
              "VALUES (?, (SELECT MAX(id) FROM notas_fiscais), 2000000_02, 'manual')", (m,))
    c.commit()
    x = _por_competencia(c, cid)["2026-07"]
    assert (x["estado"], x["faturado_centavos"]) == ("pedida", None)


def test_percentual_de_termo_corrigido_ou_de_outro_ciclo_nao_apostila(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _previsao(c, cid, "2026-07", 100_01, "manual")
    ids["instrumento"]("apostilamento_reajuste", "2026-09-15",
                       {"data_base": "2024-06", "ciclo": 2026, "percentual": "6,76",
                        "periodo": {"de": "2026-06", "ate": "2027-05"}})
    ids["instrumento"]("apostilamento_reajuste", "2026-09-20",
                       {"data_base": "2024-06", "ciclo": 2025, "percentual": "3,00",
                        "periodo": {"de": "2026-06", "ate": "2027-05"}})      # outro ciclo
    ids["instrumento"]("apostilamento_reajuste", "2026-10-01",
                       {"data_base": "2024-06", "ciclo": 2026, "corrige": "apostilamento_reajuste-2026-09-15",
                        "percentual": "6,80", "periodo": {"de": "2026-08", "ate": "2027-05"}})
    x = _por_competencia(c, cid)["2026-07"]
    assert (x["estado"], x["apostilada"]) == ("prevista", False)


def test_medicao_sem_base_gravada_vai_para_o_ciclo_da_competencia(cenario):
    # medicao de reajuste antiga, sem data-base/ciclo gravados: com uma base so', o ciclo e' o do aniversario
    # (jun/2026 a mai/2027 = ciclo 2026); gravados, valem os dela
    c, ids = cenario
    cid = ids["contrato"]
    _medicao(c, cid, 1, "2026-05", "planilha_gerada", pedido=10_01)
    _medicao(c, cid, 2, "2026-06", "planilha_gerada", pedido=20_03)
    _medicao(c, cid, 3, "2026-07", "planilha_gerada", pedido=30_05, data_base="2024-06", ciclo=2027)
    assert list(_por_competencia(c, cid, ciclo=2025)) == ["2026-05"]
    assert list(_por_competencia(c, cid, ciclo=2026)) == ["2026-06"]
    assert list(_por_competencia(c, cid, ciclo=2027)) == ["2026-07"]
    assert _por_competencia(c, cid, ciclo=2026)["2026-06"]["estado"] == "pedida"


# --- issue #390: na SES o reajuste sai por termo aditivo de valor (`natureza: reajuste`), nao por apostilamento ---

def _aditivo_reajuste(c, cid, chave, assinado_em, natureza="reajuste", tipo="valor", numero=None, cancelado=False,
                      delta=123_45, nova_execucao_fim=None):
    c.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, numero, "
              "chave_cadastro, natureza, cancelado_em, nova_execucao_fim) VALUES (?,?,?, 'assinado', ?,?,?,?,?,?)",
              (cid, tipo, delta, assinado_em, numero or chave.upper(), chave, natureza,
               "2025-12-01 10:00:00" if cancelado else None, nova_execucao_fim))
    c.commit()


@pytest.fixture
def obra_ses(cenario):
    """A obra do criterio de aceite: data-base 2021-10, uma so'."""
    c, ids = cenario
    c.execute("UPDATE contrato_datas_base SET mes='2021-10' WHERE contrato_id=?", (ids["contrato"],)); c.commit()
    return c, ids["contrato"]


def test_aditivo_de_valor_de_reajuste_fecha_o_ciclo_da_data_base(obra_ses):
    c, cid = obra_ses
    _aditivo_reajuste(c, cid, "ta-03", "2025-11-20", numero="3º Termo Aditivo")
    r = reajuste.ciclos(c, cid, D(2026, 1, 10))[0]
    assert (r["ciclo"], r["situacao"], r["dias"]) == (2025, "apostilado", None)
    assert (r["apostilamento"]["chave"], r["apostilamento"]["numero"], r["apostilamento"]["data"]) == \
        ("ta-03", "3º Termo Aditivo", "2025-11-20")
    assert r["apostilamento"]["tipo"] == "aditivo_valor"
    assert reajuste.avisos(c, D(2026, 1, 10)) == []
    # o ciclo seguinte nao tem aditivo: segue pendente, com o aviso
    r = reajuste.ciclos(c, cid, D(2026, 11, 5))[0]
    assert (r["ciclo"], r["situacao"], r["apostilamento"]) == (2026, "pleito_pendente", None)
    assert [a["tipo"] for a in reajuste.avisos(c, D(2026, 11, 5))] == ["reajuste_pleito"]


def test_aditivo_de_execucao_cancelado_ou_sem_natureza_nao_fecha_o_ciclo(obra_ses):
    c, cid = obra_ses
    _aditivo_reajuste(c, cid, "ta-01", "2025-11-20", natureza="execucao")
    _aditivo_reajuste(c, cid, "ta-02", "2025-11-21", natureza=None)
    _aditivo_reajuste(c, cid, "ta-04", "2025-11-22", cancelado=True)
    _aditivo_reajuste(c, cid, "ta-05", "2025-11-23", tipo="prazo")
    r = reajuste.ciclos(c, cid, D(2026, 1, 10))[0]
    assert (r["ciclo"], r["situacao"]) == (2025, "pleito_pendente")


def test_aditivo_de_reajuste_fecha_so_o_ciclo_do_ultimo_aniversario_antes_da_assinatura(obra_ses):
    c, cid = obra_ses
    _aditivo_reajuste(c, cid, "ta-03", "2025-11-20")
    _aditivo_reajuste(c, cid, "ta-06", "2026-10-01", tipo="misto")   # no dia do aniversario: ciclo 2026
    assert reajuste.apostilamento_do_ciclo(c, cid, "2021-10", 2024, True) is None
    assert reajuste.apostilamento_do_ciclo(c, cid, "2021-10", 2025, True)["chave"] == "ta-03"
    assert reajuste.apostilamento_do_ciclo(c, cid, "2021-10", 2026, True)["chave"] == "ta-06"
    # assinado antes do primeiro aniversario: nao ha ciclo que ele feche
    assert reajuste.ciclo_do_aditivo("2021-10", "2022-09-30") is None
    assert reajuste.ciclo_do_aditivo("2021-10", "2022-10-01") == 2022


def test_aditivo_de_reajuste_ligado_ao_pleito_fecha_o_ciclo_e_sem_ligacao_nao(obra_ses):
    c, cid = obra_ses
    c.execute("INSERT INTO pleitos (contrato_id, tipo, origem, data_base_mes, ciclo, numero_oficio, situacao, "
              "enviado_em) VALUES (?, 'reajuste', 'cadastro', '2021-10', 2025, 'CT-1-LT-2025', 'enviado', '2025-10-05')",
              (cid,))
    _aditivo_reajuste(c, cid, "ta-03", "2025-11-20")
    r = reajuste.ciclos(c, cid, D(2026, 1, 10))[0]
    # pleito sem termo ligado: espera; o aditivo de reajuste depois dele nao pede reemissao do cronograma
    assert (r["situacao"], r["aditivo"]) == ("apostilamento_pendente", None)
    _aditivo(c, cid, "prazo", "2025-12-01")             # o de prazo pede
    assert reajuste.ciclos(c, cid, D(2026, 1, 10))[0]["situacao"] == "reemitir"
    c.execute("UPDATE pleitos SET instrumento_chave='ta-03'"); c.commit()
    r = reajuste.ciclos(c, cid, D(2026, 1, 10))[0]
    assert (r["situacao"], r["apostilamento"]["chave"]) == ("apostilado", "ta-03")
    assert reajuste.avisos(c, D(2026, 1, 10)) == []


def test_aditivo_de_reajuste_sem_pleito_em_contrato_de_duas_bases_nao_adivinha_a_base(obra_ses):
    c, cid = obra_ses
    c.execute("INSERT INTO contrato_datas_base (contrato_id, mes, indice) VALUES (?, '2022-03', 'INCC-DI')", (cid,))
    _aditivo_reajuste(c, cid, "ta-03", "2025-11-20")
    assert reajuste.apostilamento_do_ciclo(c, cid, "2021-10", 2025, False) is None


def _pleito_2025(c, cid, chave=None, ciclo=2025, enviado_em="2025-10-05"):
    c.execute("INSERT INTO pleitos (contrato_id, tipo, origem, data_base_mes, ciclo, numero_oficio, situacao, "
              "enviado_em, instrumento_chave) VALUES (?, 'reajuste', 'cadastro', '2021-10', ?, ?, 'enviado', ?, ?)",
              (cid, ciclo, f"CT-{ciclo}-LT", enviado_em, chave))
    c.commit()


def test_ligacao_ao_aditivo_deixa_de_fechar_o_ciclo_quando_entra_a_segunda_data_base(obra_ses):
    # gate Sol (PR #407): o aditivo nao guarda a base; com duas, a ligacao feita com uma so' nao diz qual atende
    c, cid = obra_ses
    _aditivo_reajuste(c, cid, "ta-03", "2025-11-20")
    _pleito_2025(c, cid, chave="ta-03")
    assert reajuste.ciclos(c, cid, D(2026, 1, 10))[0]["situacao"] == "apostilado"
    assert [a["chave"] for a in reajuste.aditivos_de_reajuste(c, cid)] == ["ta-03"]
    c.execute("INSERT INTO contrato_datas_base (contrato_id, mes, indice) VALUES (?, '2022-03', 'INCC-DI')", (cid,))
    c.commit()
    r = reajuste.ciclos(c, cid, D(2026, 1, 10))[0]
    assert (r["data_base_mes"], r["situacao"], r["apostilamento"]) == ("2021-10", "apostilamento_pendente", None)
    assert reajuste.aditivos_de_reajuste(c, cid) == []


def test_aditivo_misto_de_reajuste_sem_valor_nao_fecha_o_ciclo(obra_ses):
    # gate Sol (PR #407): misto so' de prazo (delta zero) nao concede reajuste
    c, cid = obra_ses
    _aditivo_reajuste(c, cid, "ta-03", "2025-11-20", tipo="misto", delta=0, nova_execucao_fim="2026-12-31")
    assert reajuste.ciclos(c, cid, D(2026, 1, 10))[0]["situacao"] == "pleito_pendente"
    assert reajuste.aditivos_de_reajuste(c, cid) == []


def test_aditivo_misto_de_reajuste_com_prazo_novo_depois_do_pedido_pede_reemissao(obra_ses):
    # revisor e gate Sol (PR #407): o prazo mudou, o cronograma de reajuste precisa ser reenviado
    c, cid = obra_ses
    _pleito_2025(c, cid)
    _aditivo_reajuste(c, cid, "ta-03", "2025-11-20", tipo="misto", nova_execucao_fim="2026-12-31")
    r = reajuste.ciclos(c, cid, D(2026, 1, 10))[0]
    assert (r["situacao"], r["aditivo"]["chave_cadastro"]) == ("reemitir", "ta-03")


def test_aditivo_ligado_a_pleito_nao_fecha_outro_ciclo_pela_data(obra_ses):
    # revisor (PR #407): o termo do reajuste de 2025 assinado em 20/10/2026, ligado ao pleito de 2025 pelo `ciclo` do
    # cadastro, nao fecha o ciclo 2026 (sem pleito) pela data da assinatura
    c, cid = obra_ses
    _pleito_2025(c, cid, chave="ta-03")
    _aditivo_reajuste(c, cid, "ta-03", "2026-10-20")
    assert reajuste.apostilamento_do_ciclo(c, cid, "2021-10", 2025, True)["chave"] == "ta-03"
    r = reajuste.ciclos(c, cid, D(2026, 11, 5))[0]
    assert (r["ciclo"], r["situacao"]) == (2026, "pleito_pendente")
