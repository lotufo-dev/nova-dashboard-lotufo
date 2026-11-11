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


def test_medido_da_ultima_competencia_fechada(cenario):
    # B-01 (10/10/2026): a regra da Carteira -- competencia, valor cheio, mes inteiro. 06/11/2026: o mes do cartao e' a
    # ULTIMA COMPETENCIA FECHADA (em outubro, setembro), porque a medicao de um mes so' e' lancada no seguinte.
    # #642: a comparacao com o mes anterior e as barras por contratante sairam da tela e do calculo
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
    assert m == {"competencia": "2026-09", "valor_centavos": 1_000_005, "quantidade": 2, "ultimo_lancamento": "2026-10-09"}
    assert "por_contratante" not in p and "protocolado_mes" not in p


def test_mes_sem_medicao_da_competencia(cenario):
    c, cid = cenario
    _medicao(c, cid, 1, "2026-08-30 12:00:00", 10, competencia="2026-08")
    m = inicio.painel(c, HOJE)["medido"]
    assert (m["quantidade"], m["valor_centavos"], m["ultimo_lancamento"]) == (0, 0, "2026-08-30")


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
    assert p["medido"]["valor_centavos"] == 700_001


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


def test_protocoladas_por_dia_so_a_primeira_data_de_protocolo_da_nota(cenario):
    # a base do cartao de notas protocoladas no mes (a curva por dia saiu na #642)
    c, cid = cenario
    a = _medicao(c, cid, 1, "2026-10-01 10:00:00", 1_000, estado="protocolada")
    b = _medicao(c, cid, 2, "2026-10-01 10:00:00", 500, estado="protocolada")
    _protocolar(c, a, "2026-10-02"); _protocolar(c, a, "2026-10-08")       # reprotocolo: nao conta de novo
    _protocolar(c, b, "2026-10-04"); _protocolar(c, b, "2026-10-01", etapa="planilha")   # planilha nao e' da nota
    assert {r["id"]: r["data"] for r in inicio._protocoladas_dia(c)} == {a: "2026-10-02", b: "2026-10-04"}


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
    assert n == {"mes": "2026-10", "valor_centavos": 7_000, "notas": 2, "obras": 2}


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


# --- faixa do ciclo (#642): quanto dinheiro esta' em cada etapa, na cota, e a idade do item mais antigo ---

def _no_ciclo(c, cid, numero, estado, pedido, aprovado=None, **datas):
    """Medicao num estado do ciclo, com as datas de evento dadas (`planilha_enviada_em`, `atestado_em`,
    `nota_emitida_em`); o protocolo entra por `_protocolar`."""
    mid = _medicao(c, cid, numero, "2026-09-01 10:00:00", pedido, estado=estado)
    campos = {"valor_atestado_centavos": aprovado, **datas}
    c.execute(f"UPDATE medicoes SET {', '.join(k + '=?' for k in campos)} WHERE id=?", (*campos.values(), mid))
    c.commit()
    return mid


def _etapas(c):
    return {e["etapa"]: (e["valor_centavos"], e["quantidade"], e["mais_antigo_dias"]) for e in inicio.painel(c, HOJE)["ciclo"]}


def test_ciclo_tem_as_cinco_etapas_na_ordem_e_vazio_sem_medicao(cenario):
    c, _ = cenario
    ciclo = inicio.painel(c, HOJE)["ciclo"]
    assert [e["etapa"] for e in ciclo] == ["em_analise", "boletim", "nota", "protocolado", "recebido_mes"]
    assert set(_etapas(c).values()) == {(0, 0, None)}


def test_ciclo_valor_quantidade_e_idade_do_mais_antigo_por_etapa(cenario):
    c, cid = cenario
    _no_ciclo(c, cid, 1, "planilha_enviada", 1_001, planilha_enviada_em="2026-10-01")
    _no_ciclo(c, cid, 2, "planilha_enviada", 2_000, planilha_enviada_em="2026-09-19 14:00:00")
    # o valor e' o aprovado; enquanto nao ha', o pedido
    _no_ciclo(c, cid, 3, "boletim_recebido", 9_999, aprovado=3_003, atestado_em="2026-10-08")
    _no_ciclo(c, cid, 4, "espelho_gerado", 9_999, aprovado=4_000, atestado_em="2026-09-09")
    _no_ciclo(c, cid, 5, "espelho_enviado", 9_999, aprovado=5_000, atestado_em="2026-10-09")
    _no_ciclo(c, cid, 6, "nota_emitida", 9_999, aprovado=6_001, atestado_em="2026-08-01", nota_emitida_em="2026-10-04")
    p1 = _no_ciclo(c, cid, 7, "protocolada", 7_000, nota_emitida_em="2026-08-01")
    p2 = _no_ciclo(c, cid, 8, "nf_emitida", 8_005)                      # legado com data de protocolo: conta
    _protocolar(c, p1, "2026-09-29"); _protocolar(c, p1, "2026-10-07")   # reprotocolo: a idade e' do primeiro
    _protocolar(c, p2, "2026-07-01")
    # fora do ciclo: prevista, cancelada e recebida
    _no_ciclo(c, cid, 9, "prevista", 111, planilha_enviada_em="2026-10-01")
    _no_ciclo(c, cid, 10, "cancelada", 222, atestado_em="2026-10-01")
    _medicao(c, cid, 11, "2026-09-01 10:00:00", 333, estado="recebida", recebida_em="2026-10-02")
    assert _etapas(c) == {"em_analise": (3_001, 2, 20), "boletim": (12_003, 3, 30), "nota": (6_001, 1, 5),
                          "protocolado": (15_005, 2, 100), "recebido_mes": (0, 0, None)}


def test_ciclo_medicao_sem_a_data_do_evento_fica_fora(cenario):
    # so' aparece o que tem evidencia: a idade nunca conta da competencia nem do lancamento
    c, cid = cenario
    _no_ciclo(c, cid, 1, "planilha_enviada", 1_000)                                  # sem data do envio
    _no_ciclo(c, cid, 2, "espelho_gerado", 2_000, aprovado=2_000)                    # sem data do atesto
    _no_ciclo(c, cid, 3, "nota_emitida", 3_000, atestado_em="2026-09-01")            # sem data da nota
    _no_ciclo(c, cid, 4, "protocolada", 4_000, nota_emitida_em="2026-09-01")         # sem protocolo
    so_planilha = _no_ciclo(c, cid, 5, "protocolada", 5_000)
    _protocolar(c, so_planilha, "2026-09-10", etapa="planilha")                      # protocolo da planilha nao e' o da nota
    _no_ciclo(c, cid, 6, "nf_emitida", 6_000)
    _no_ciclo(c, cid, 7, "planilha_enviada", 7_000, planilha_enviada_em="sem data")  # data ilegivel nao e' evidencia
    assert set(_etapas(c).values()) == {(0, 0, None)}


def test_ciclo_na_cota_da_lotufo_com_centavo_impar(cenario):
    # consorcio a 50%: cada medicao vai para a cota com o arredondamento unico (100.001 -> 50.001, meio para cima);
    # duas somam 100.002, nao a cota da soma (100.001)
    c, cid = cenario
    c.execute("UPDATE contratos SET percentual_direito_bp=5000")
    _no_ciclo(c, cid, 1, "planilha_enviada", 100_001, planilha_enviada_em="2026-10-08")
    _no_ciclo(c, cid, 2, "planilha_enviada", 100_001, planilha_enviada_em="2026-10-08")
    p = _no_ciclo(c, cid, 3, "protocolada", 999_999, aprovado=300_003)
    _protocolar(c, p, "2026-10-09")
    e = _etapas(c)
    assert e["em_analise"] == (100_002, 2, 1)
    assert e["protocolado"] == (150_002, 1, 0)


def test_ciclo_recebido_no_mes_sao_as_baixas_do_rm_do_mes_corrente_na_cota_e_sem_idade(cenario):
    from app import diretoria
    c, cid = cenario
    c.execute("UPDATE contratos SET percentual_direito_bp=5000, centro_custo_rm='9.001.002' WHERE id=?", (cid,))
    col = c.execute("SELECT e.coligada_rm FROM contratos k JOIN entidades e ON e.id=COALESCE(k.entidade_id, 1) WHERE k.id=?",
                    (cid,)).fetchone()[0]
    nota = {}
    for n in (1, 2, 3):
        nota[n] = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, centro_custo, "
                            "codtmv) VALUES (?, ?, ?, '2026-08-05', 900000, 'ativa', '9.001.002', '2.2.01')",
                            (col, n, str(n))).lastrowid
    baixas = ((11, nota[1], 100_001, 1, "2026-10-02"),     # no mes: 50.001 na cota
              (12, nota[1], 100_001, 1, "2026-10-09"),     # a mesma nota, outro titulo: soma o valor, a nota conta uma vez
              (13, nota[2], 40_000, 4, "2026-10-01"),      # baixa parcial e' recebido
              (14, nota[3], 70_000, 1, "2026-09-30"),      # mes anterior: fora
              (15, nota[3], 80_000, 0, "2026-10-05"))      # titulo em aberto nao e' recebido
    for idlan, nid, valor, status, data in baixas:
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan, data_baixa) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (col, idlan, nid, idlan, valor, valor, status, data))
    c.commit()
    assert _etapas(c)["recebido_mes"] == (120_002, 2, None)
    assert diretoria.rm_por_mes(c)[1]["2026-10"] == 120_002     # a mesma conta do recebido por mes da diretoria
