"""Pagina Inicio do redesenho (08/10/2026): de onde vem cada numero."""
import datetime
import json

import pytest

from app import db, inicio, tempo
from tests.test_espelhos import ambiente_projeto  # noqa: F401  (fixture: obra com espelho de execucao e projeto)

D = datetime.date
HOJE = D(2026, 10, 9)


@pytest.fixture
def cenario(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(tempo, "hoje_local", lambda: HOJE)
    c = db.get_conn(); db.migrate(c)
    c.execute("UPDATE certidao_tipos SET aplicavel_por_padrao=0")
    c.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('mtpar', 'MT Participações', 'mtpar', ?)",
              (json.dumps({"vigencia_automatica": False, "documentos_medicao": [], "documentos_reajuste": []}),))
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos, "
              "orgao_id, execucao_fim, vigencia_fim) VALUES ('MTPAR', 'CT 1/2025', 'Obra A', 'obra', 100, "
              "(SELECT id FROM orgaos WHERE chave='mtpar'), '2026-10-20', '2026-12-30')")
    cid = c.execute("SELECT MAX(id) FROM contratos").fetchone()[0]
    c.execute("INSERT INTO contrato_datas_base (contrato_id, mes) VALUES (?, '2025-11')", (cid,))
    c.commit()
    yield c, cid
    c.close()


def _medicao(c, cid, numero, criado_em, valor, estado="espelho_gerado", competencia="2026-09", recebida_em=None):
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
              "criado_em, recebida_em) VALUES (?, ?, 'execucao', ?, ?, ?, ?, ?)",
              (cid, numero, competencia, estado, valor, criado_em, recebida_em))
    c.commit()
    return c.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]


def test_medido_da_ultima_competencia_fechada_contra_a_anterior(cenario):
    # B-01 (10/10/2026): a regra da Carteira -- competencia, valor cheio, mes inteiro. 06/11/2026: o mes do cartao e' a
    # ULTIMA COMPETENCIA FECHADA (em outubro, setembro), porque a medicao de um mes so' e' lancada no seguinte
    c, cid = cenario
    _medicao(c, cid, 1, "2026-10-05 12:00:00", 1_000_000, competencia="2026-09")
    _medicao(c, cid, 2, "2026-10-08 12:00:00", 5, competencia="2026-09")
    _medicao(c, cid, 3, "2026-09-03 12:00:00", 400_000, competencia="2026-08")
    _medicao(c, cid, 4, "2026-09-28 12:00:00", 999, competencia="2026-08")
    _medicao(c, cid, 5, "2026-10-02 12:00:00", 777, estado="cancelada", competencia="2026-09")
    _medicao(c, cid, 6, "2026-10-09 12:00:00", 50_000, competencia="2026-08")  # lancada hoje, competencia passada
    _medicao(c, cid, 7, "2026-10-09 13:00:00", 3, competencia="2025-09")       # carga do legado lancada hoje: fora
    _medicao(c, cid, 8, "2026-10-09 14:00:00", 9, competencia="2026-10")       # o mes corrente nao entra no cartao
    p = inicio.painel(c, HOJE)
    m = p["medido"]
    assert (m["valor_centavos"], m["anterior_centavos"], m["quantidade"]) == (1_000_005, 450_999, 2)
    assert (m["competencia"], m["anterior_competencia"]) == ("2026-09", "2026-08")
    assert m["ultimo_lancamento"] == "2026-10-09"
    assert p["por_contratante"] == [{"contratante": "MTPAR", "atual_centavos": 1_000_005, "anterior_centavos": 450_999}]


def test_mes_sem_medicao_da_competencia(cenario):
    c, cid = cenario
    _medicao(c, cid, 1, "2026-08-30 12:00:00", 10, competencia="2026-08")
    m = inicio.painel(c, HOJE)["medido"]
    assert (m["quantidade"], m["valor_centavos"], m["anterior_centavos"], m["ultimo_lancamento"]) == (0, 0, 10, "2026-08-30")


def test_nota_do_rm_sem_medicao_lancada_entra_no_medido_do_inicio(cenario):
    # 06/11/2026: a competencia sem medicao lancada vale pela nota do RM emitida no mes seguinte (valor cheio)
    c, cid = cenario
    _medicao(c, cid, 1, "2026-09-03 12:00:00", 400_000, competencia="2026-08")
    col = c.execute("SELECT e.coligada_rm FROM contratos k JOIN entidades e ON e.id=COALESCE(k.entidade_id, 1) WHERE k.id=?",
                    (cid,)).fetchone()[0]
    c.execute("UPDATE contratos SET centro_custo_rm='9.001.002' WHERE id=?", (cid,))
    c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, centro_custo, codtmv) "
              "VALUES (?, 501, '501', '2026-10-06', 700001, 'ativa', '9.001.002', '2.2.01')", (col,))
    c.commit()
    p = inicio.painel(c, HOJE)
    assert (p["medido"]["valor_centavos"], p["medido"]["anterior_centavos"]) == (700_001, 400_000)
    assert p["por_contratante"] == [{"contratante": "MTPAR", "atual_centavos": 700_001, "anterior_centavos": 400_000}]


def test_prazos_e_reajuste_a_pedir(cenario):
    c, cid = cenario
    p = inicio.painel(c, HOJE)
    assert [(x["tipo"], x["data"], x["dias"]) for x in p["prazos"]] == [
        ("execucao", "2026-10-20", 11), ("data_base", "2026-11-01", 23), ("vigencia", "2026-12-30", 82)]
    assert p["prazos"][0]["contratante"] == "MTPAR"
    assert p["reajustes"] == [{"contrato_id": cid, "obra": "Obra A", "data_base_mes": "2025-11",
                               "aniversario": "2026-11-01", "dias": 23}]
    # apostilado: a data-base sai dos dois
    c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, numero, data, dados) "
              "VALUES (?, 'ap1', 'apostilamento_reajuste', '1', '2026-10-05', ?)", (cid, json.dumps({"ciclo": 2026})))
    c.commit()
    p = inicio.painel(c, HOJE)
    assert p["reajustes"] == [] and "data_base" not in {x["tipo"] for x in p["prazos"]}


def test_recebido_no_ano_nulo_com_recebida_sem_data(cenario):
    c, cid = cenario
    _medicao(c, cid, 1, "2026-08-01 12:00:00", 300_000, estado="recebida", competencia="2026-07", recebida_em="2026-10-02")
    _medicao(c, cid, 2, "2026-06-01 12:00:00", 100_000, estado="recebida", competencia="2026-05", recebida_em="2026-06-20")
    assert inicio.painel(c, HOJE)["recebido_ano"] == {"valor_centavos": 400_000, "mes_centavos": 300_000, "sem_data": 0,
                                                      "real_centavos": 0}
    _medicao(c, cid, 3, "2026-09-25 12:00:00", 50, estado="recebida", competencia="2026-04")
    assert inicio.painel(c, HOJE)["recebido_ano"] == {"valor_centavos": None, "mes_centavos": 300_000, "sem_data": 1,
                                                      "real_centavos": 0}
    # o recebido de verdade vem das baixas do RM e nao depende da data gravada na medicao (06/11/2026)
    mid = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=1", (cid,)).fetchone()[0]
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, codtmv) "
                    "VALUES (1, 77, '77', '2026-08-05', 300000, 'ativa', '2.2.01')").lastrowid
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
              "VALUES (?, ?, 300000, 'detectado', 't')", (mid, nid))
    c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, status_lan, "
              "data_baixa) VALUES (1, 77, ?, 77, 280000, 280000, 1, '2026-10-02')", (nid,))
    c.commit()
    assert inicio.painel(c, HOJE)["recebido_ano"]["real_centavos"] == 280_000


def test_a_receber_so_com_total_liberado_e_na_cota(cenario):
    c, cid = cenario
    c.execute("UPDATE contratos SET percentual_direito_bp=5000")
    mid = _medicao(c, cid, 1, "2026-07-01 12:00:00", 200_000, estado="protocolada", competencia="2026-06")
    c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, '2026-07-02', 'manual')", (mid,))
    c.commit()
    p = inicio.painel(c, HOJE)
    assert p["a_receber"] == {"liberado": False, "valor_centavos": None, "mais_60_centavos": None}
    assert p["protocoladas"] == {"obras_protocoladas": 0, "obras_ativas": 1, "ultima": "2026-07-02"}
    c.execute("INSERT INTO cadastro_geral (chave, valor) VALUES ('diretoria', ?)",
              (json.dumps({"total_a_receber_liberado": True}),))
    c.commit()
    assert inicio.painel(c, HOJE)["a_receber"] == {"liberado": True, "valor_centavos": 100_000, "mais_60_centavos": 100_000}


def test_cartoes_vazios(cenario):
    c, _ = cenario
    p = inicio.painel(c, HOJE)
    assert p["notas_a_enviar"] == 0
    assert p["certidoes"] == {"vencidas": 0, "vencendo": 0, "itens": []}
    assert p["espelhos"] == []


def test_espelho_a_conferir_conta_uma_vez_o_espelho_com_duas_medicoes(ambiente_projeto, monkeypatch):
    # rodada 2 da PR #474 (gate Sol): execucao e projeto do mesmo espelho sao um espelho a conferir; leva a' medicao
    # cuja situacao pede o ato (a execucao com nota emitida nao esconde o "gere de novo" do projeto)
    from app import espelhos, medicoes, notas
    from tests.test_espelhos import _boletim
    conn, u, cid = ambiente_projeto
    eid = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100_01, "projeto": 7_01})
    ids = {m["tipo"]: m["id"] for m in espelhos.detalhe(conn, eid)["medicoes"]}
    _boletim(conn, u, ids["execucao"], 99_99)
    _boletim(conn, u, ids["projeto"], 7_03, sha="b")
    monkeypatch.setattr(notas, "faltam", lambda c, m: 0)
    assert notas.fechar_se_completa(conn, u["id"], ids["execucao"])
    assert medicoes.detalhe(conn, ids["execucao"])["estado"] == "nota_emitida"
    [e] = inicio.painel(conn)["espelhos"]
    assert (e["espelho_id"], e["medicao_id"], e["situacao"]) == (eid, ids["projeto"], "aprovado_mudou")


def _protocolar(c, mid, data, etapa="nota"):
    c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem, etapa) VALUES (?, ?, 'manual', ?)",
              (mid, data, etapa))
    c.commit()


def test_protocolado_por_dia_soma_so_a_primeira_data_de_protocolo_da_nota(cenario):
    c, cid = cenario
    a = _medicao(c, cid, 1, "2026-10-01 10:00:00", 1_000, estado="protocolada")
    b = _medicao(c, cid, 2, "2026-10-01 10:00:00", 500, estado="protocolada")
    _protocolar(c, a, "2026-10-02"); _protocolar(c, a, "2026-10-08")       # reprotocolo: nao conta de novo
    _protocolar(c, b, "2026-10-04"); _protocolar(c, b, "2026-10-01", etapa="planilha")   # planilha nao e' da nota
    atual = inicio.painel(c, HOJE)["protocolado_mes"]["atual"]
    assert atual["valor_centavos"] == 1_500 and atual["quantidade"] == 2 and atual["ate_dia"] == 9
    assert atual["acumulado_centavos"] == [0, 1_000, 1_000, 1_500, 1_500, 1_500, 1_500, 1_500, 1_500]


def test_mesmo_periodo_do_mes_anterior_corta_no_mesmo_dia(cenario):
    c, cid = cenario
    a = _medicao(c, cid, 1, "2026-09-01 10:00:00", 2_000, estado="protocolada")
    b = _medicao(c, cid, 2, "2026-09-01 10:00:00", 700, estado="protocolada")
    _protocolar(c, a, "2026-09-05"); _protocolar(c, b, "2026-09-10")     # 10/09 esta' depois do dia 9: fora
    p = inicio.painel(c, HOJE)["protocolado_mes"]
    assert p["anterior"]["mes"] == "2026-09" and p["anterior"]["ate_dia"] == 9
    assert p["anterior"]["valor_centavos"] == 2_000 and p["anterior"]["quantidade"] == 1
    assert len(p["anterior"]["acumulado_centavos"]) == 9
    assert p["atual"]["valor_centavos"] == 0 and p["variacao_pct"] == -100.0
    # mes anterior mais curto: 31/03 compara com ate' 28/02
    assert inicio._protocolado_mes(c, D(2026, 3, 31))["anterior"]["ate_dia"] == 28


def test_notas_protocoladas_no_mes_contam_notas_e_obras_distintas(cenario):
    c, cid = cenario
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
              "VALUES ('MTPAR', 'CT 2/2025', 'Obra B', 'obra', 100)")
    cid2 = c.execute("SELECT MAX(id) FROM contratos").fetchone()[0]
    m1 = _medicao(c, cid, 1, "2026-10-01 10:00:00", 100, estado="protocolada")
    m2 = _medicao(c, cid, 2, "2026-10-01 10:00:00", 100, estado="protocolada")
    m3 = _medicao(c, cid2, 1, "2026-10-01 10:00:00", 100, estado="protocolada")
    m4 = _medicao(c, cid2, 2, "2026-10-01 10:00:00", 100, estado="protocolada")   # protocolada em setembro
    for m, d in ((m1, "2026-10-03"), (m2, "2026-10-05"), (m3, "2026-10-06"), (m4, "2026-09-20")):
        _protocolar(c, m, d)
    nota = {}
    for n, valor, situacao in ((1, 3_000, "ativa"), (2, 4_000, "ativa"), (3, 9_000, "cancelada"), (4, 8_000, "ativa")):
        nota[n] = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, codtmv) "
                            "VALUES (1, ?, ?, '2026-10-01', ?, ?, '2.2.01')", (n, str(n), valor, situacao)).lastrowid
    for m, n in ((m1, 1), (m2, 1),      # a mesma nota nas duas medicoes da obra A: conta uma vez
                 (m3, 2), (m3, 3),      # cancelada nao entra
                 (m4, 4)):              # medicao protocolada em setembro nao entra
        c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem) "
                  "VALUES (?, ?, 1, 'manual')", (m, nota[n]))
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, desfeita_em) "
              "VALUES (?, ?, 1, 'manual', '2026-10-07')", (m1, nota[4]))   # alocacao desfeita nao conta
    c.commit()
    n = inicio.painel(c, HOJE)["notas_mes"]
    assert (n["valor_centavos"], n["notas"], n["obras"]) == (7_000, 2, 2)
    assert n["acumulado_centavos"][-1] == 7_000 and len(n["acumulado_centavos"]) == 9


def test_variacao_do_medido_do_mes_fechado(cenario):
    c, cid = cenario
    _medicao(c, cid, 1, "2026-10-01 10:00:00", 1_000, competencia="2026-09")
    _medicao(c, cid, 2, "2026-10-01 10:00:00", 1_250, competencia="2026-08")
    assert inicio.painel(c, HOJE)["medido"]["variacao_pct"] == -20.0
    assert inicio._variacao_pct(10, 0) is None


def test_avisos_importantes_tem_contagem_e_tres_itens_por_secao(cenario):
    c, cid = cenario
    a = inicio.painel(c, HOJE)["avisos_importantes"]
    assert set(a) == {"reajustes", "prazos", "certidoes"}
    assert a["reajustes"]["total"] == 1 and a["reajustes"]["itens"][0]["obra"] == "Obra A"
    # execucao em 20/10 (11 dias); a vigencia 30/12 e' alem do horizonte e a data-base nao e' "prazo"
    assert a["prazos"]["total"] == 2 and a["prazos"]["itens"][0]["tipo"] == "execucao"
    assert a["certidoes"] == {"total": 0, "itens": []}
    for i in range(5):
        c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos, "
                  "execucao_fim) VALUES ('X', ?, ?, 'o', 100, ?)", (f"N{i}", f"Obra {i}", f"2026-09-0{i + 1}"))
    c.commit()
    p = inicio.painel(c, HOJE)["avisos_importantes"]["prazos"]
    assert p["total"] == 7 and len(p["itens"]) == 3
    assert [x["dias"] for x in p["itens"]] == sorted(x["dias"] for x in p["itens"]) and p["itens"][0]["dias"] < 0
