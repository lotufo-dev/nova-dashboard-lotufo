"""Pagina Inicio do redesenho (08/10/2026): de onde vem cada numero."""
import datetime
import json

import pytest

from app import db, inicio, tempo

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
    # #805: as duas referencias da variacao, cada uma com a mesma conta do numero (competencia inteira, valor cheio)
    assert m == {"competencia": "2026-09", "valor_centavos": 1_000_005, "quantidade": 2, "ultimo_lancamento": "2026-10-09",
                 "anterior": {"competencia": "2026-08", "valor_centavos": 450_999},
                 "ano_anterior": {"competencia": "2025-09", "valor_centavos": 3}}
    assert "por_contratante" not in p and "protocolado_mes" not in p


def test_referencias_do_medido_so_com_lastro(cenario):
    # #805: sem medicao na competencia de referencia nao ha' com o que comparar, e a referencia vem nula; a
    # cancelada nao conta na referencia, como nao conta no numero
    c, cid = cenario
    _medicao(c, cid, 1, "2026-10-05 12:00:00", 300_001, competencia="2026-09")
    _medicao(c, cid, 2, "2026-09-05 12:00:00", 999, estado="cancelada", competencia="2026-08")
    m = inicio.painel(c, HOJE)["medido"]
    assert (m["valor_centavos"], m["anterior"], m["ano_anterior"]) == (300_001, None, None)


def test_referencia_do_medido_anterior_ao_ano_inicial_fica_nula(cenario):
    # #805: as telas da diretoria contam de `diretoria.ANO_INICIAL` em diante. Em fevereiro de 2026 o cartao e' de
    # janeiro: a competencia anterior (12/2025) compara, e a do ano anterior (01/2025) tambem; em fevereiro de 2025, o
    # cartao e' de janeiro de 2025 e as duas referencias (12/2024 e 01/2024) ficam fora, mesmo com medicao lancada
    c, cid = cenario
    _medicao(c, cid, 1, "2025-01-10 12:00:00", 70_001, competencia="2024-12")
    _medicao(c, cid, 2, "2025-02-05 12:00:00", 80_001, competencia="2025-01")
    _medicao(c, cid, 3, "2024-02-05 12:00:00", 60_001, competencia="2024-01")
    _medicao(c, cid, 4, "2026-01-05 12:00:00", 90_001, competencia="2025-12")
    _medicao(c, cid, 5, "2026-02-05 12:00:00", 100_001, competencia="2026-01")
    m = inicio.painel(c, D(2025, 2, 10))["medido"]
    assert (m["competencia"], m["valor_centavos"], m["anterior"], m["ano_anterior"]) == ("2025-01", 80_001, None, None)
    m = inicio.painel(c, D(2026, 2, 10))["medido"]
    assert m["anterior"] == {"competencia": "2025-12", "valor_centavos": 90_001}
    assert m["ano_anterior"] == {"competencia": "2025-01", "valor_centavos": 80_001}


def test_referencia_do_medido_leva_a_nota_do_rm_sem_medicao_como_o_numero(cenario):
    # #805: a referencia e' a mesma conta do numero, entao a competencia de referencia tambem vale pela nota do RM que
    # ainda nao tem medicao lancada (`diretoria.complemento_rm`): em novembro, o cartao e' de outubro e a competencia
    # anterior (setembro) so' tem a nota emitida em outubro
    c, cid = cenario
    _medicao(c, cid, 1, "2026-11-03 12:00:00", 500_001, competencia="2026-10")
    col = c.execute("SELECT e.coligada_rm FROM contratos k JOIN entidades e ON e.id=COALESCE(k.entidade_id, 1) WHERE k.id=?",
                    (cid,)).fetchone()[0]
    c.execute("UPDATE contratos SET centro_custo_rm='9.001.002' WHERE id=?", (cid,))
    c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, centro_custo, codtmv) "
              "VALUES (?, 501, '501', '2026-10-06', 700001, 'ativa', '9.001.002', '2.2.01')", (col,))
    c.commit()
    m = inicio.painel(c, D(2026, 11, 18))["medido"]
    assert (m["valor_centavos"], m["anterior"]) == (500_001, {"competencia": "2026-09", "valor_centavos": 700_001})


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


def test_a_receber_so_com_total_liberado_e_na_cota(cenario):
    c, cid = cenario
    c.execute("UPDATE contratos SET percentual_direito_bp=5000")
    mid = _medicao(c, cid, 1, "2026-07-01 12:00:00", 200_000, estado="protocolada", competencia="2026-06")
    c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, '2026-07-02', 'manual')", (mid,))
    c.commit()
    p = inicio.painel(c, HOJE)
    assert p["a_receber"] == {"liberado": False, "valor_centavos": None, "mais_60_centavos": None,
                                                "a_parte": None}
    assert p["protocoladas"] == {"obras_protocoladas": 0, "obras_ativas": 1, "ultima": "2026-07-02"}
    c.execute("INSERT INTO cadastro_geral (chave, valor) VALUES ('diretoria', ?)",
              (json.dumps({"total_a_receber_liberado": True}),))
    c.commit()
    r = inicio.painel(c, HOJE)["a_receber"]
    assert (r["liberado"], r["valor_centavos"], r["mais_60_centavos"], r["a_parte"]["valor_centavos"]) == (True, 100_000, 100_000, 0)


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
    # #805: hoje e' dia 9; a medicao protocolada em 20/09 fica depois do dia 9 de setembro, entao nao ha' referencia
    assert n == {"mes": "2026-10", "valor_centavos": 7_000, "notas": 2, "obras": 2, "anterior": None}


def _nota_da_medicao(c, mid, idmov, valor, situacao="ativa"):
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, codtmv) "
                    "VALUES (1, ?, ?, '2026-09-01', ?, ?, '2.2.01')", (idmov, str(idmov), valor, situacao)).lastrowid
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem) VALUES (?, ?, 1, 'manual')",
              (mid, nid))
    c.commit()
    return nid


def test_notas_do_mes_anterior_ate_o_mesmo_dia(cenario):
    # #805: a referencia das notas protocoladas no mes e' o mes anterior ATE' O MESMO DIA (hoje e' dia 9: de 1 a 9 de
    # setembro, o dia 9 incluido), com a mesma conta do numero: nota ativa, cada nota uma vez, reprotocolo nao conta
    c, cid = cenario
    ate_o_dia = _medicao(c, cid, 1, "2026-09-01 10:00:00", 100, estado="protocolada")
    no_dia = _medicao(c, cid, 2, "2026-09-01 10:00:00", 100, estado="protocolada")
    depois = _medicao(c, cid, 3, "2026-09-01 10:00:00", 100, estado="protocolada")
    reprotocolada = _medicao(c, cid, 4, "2026-08-01 10:00:00", 100, estado="protocolada")
    do_mes = _medicao(c, cid, 5, "2026-10-01 10:00:00", 100, estado="protocolada")
    for m, d in ((ate_o_dia, "2026-09-03"), (no_dia, "2026-09-09"), (depois, "2026-09-10"),
                 (reprotocolada, "2026-08-20"), (reprotocolada, "2026-09-05"),      # a primeira data e' de agosto
                 (do_mes, "2026-10-02")):
        _protocolar(c, m, d)
    partilhada = _nota_da_medicao(c, ate_o_dia, 1, 300_001)
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem) VALUES (?, ?, 1, 'manual')",
              (no_dia, partilhada))                                               # a mesma nota: conta uma vez
    _nota_da_medicao(c, no_dia, 2, 200_002)
    _nota_da_medicao(c, no_dia, 3, 999, situacao="cancelada")
    _nota_da_medicao(c, depois, 4, 70_000)
    _nota_da_medicao(c, reprotocolada, 5, 60_000)
    _nota_da_medicao(c, do_mes, 6, 400_003)
    n = inicio.painel(c, HOJE)["notas_mes"]
    assert (n["valor_centavos"], n["anterior"]) == (400_003, {"mes": "2026-09", "ate_dia": 9, "valor_centavos": 500_003})


def test_notas_do_mes_anterior_quando_ele_nao_tem_o_dia_de_hoje(cenario):
    # #805: em 31 de marco, fevereiro vai ate' o ultimo dia dele (28 em 2026), e a resposta diz o dia usado
    c, cid = cenario
    fim = _medicao(c, cid, 1, "2026-02-01 10:00:00", 100, estado="protocolada")
    _protocolar(c, fim, "2026-02-28")
    _nota_da_medicao(c, fim, 1, 150_001)
    n = inicio.painel(c, D(2026, 3, 31))["notas_mes"]
    assert n["anterior"] == {"mes": "2026-02", "ate_dia": 28, "valor_centavos": 150_001}
    assert inicio.painel(c, D(2026, 3, 27))["notas_mes"]["anterior"] is None      # dia 27: o protocolo do dia 28 fica fora
    # em 30 de marco de 2028 (bissexto), fevereiro vai ate' o dia 29
    bissexto = _medicao(c, cid, 2, "2028-02-01 10:00:00", 100, estado="protocolada")
    _protocolar(c, bissexto, "2028-02-29")
    _nota_da_medicao(c, bissexto, 2, 90_001)
    assert inicio.painel(c, D(2028, 3, 30))["notas_mes"]["anterior"] == {"mes": "2028-02", "ate_dia": 29, "valor_centavos": 90_001}


def test_notas_do_mes_anterior_antes_do_ano_inicial_ficam_sem_referencia(cenario):
    # #805: em janeiro de 2025 o mes anterior e' dezembro de 2024, antes de `diretoria.ANO_INICIAL`
    c, cid = cenario
    velha = _medicao(c, cid, 1, "2024-12-01 10:00:00", 100, estado="protocolada")
    _protocolar(c, velha, "2024-12-05")
    _nota_da_medicao(c, velha, 1, 150_001)
    assert inicio.painel(c, D(2025, 1, 20))["notas_mes"]["anterior"] is None


def test_painel_sem_as_chaves_que_nenhuma_tela_le(cenario):
    # issue #699: os cartoes antigos do Inicio sairam da tela e as chaves deles saem da resposta
    c, _ = cenario
    p = inicio.painel(c, HOJE)
    assert not {"notas_a_enviar", "certidoes", "reajustes", "recebido_ano", "prazos", "espelhos"} & set(p)
    # #817: o ciclo por contratante e o medido em 12 meses, que a tela mostra
    assert set(p) == {"hoje", "protocoladas", "medido", "a_receber", "ciclo", "recebido_12m", "previsao", "matriz",
                      "notas_mes", "ciclo_por_contratante", "medido_12m"}


def test_painel_nao_monta_mais_a_caixa_de_avisos(cenario):
    # issue #666: a caixa "Avisos importantes" le a fila da tela Avisos (GET /api/inicio) e a divide pelo tempo na
    # tela; as tres secoes por assunto (reajustes, prazos, certidoes) sairam do painel
    c, _ = cenario
    assert "avisos_importantes" not in inicio.painel(c, HOJE)
    assert not hasattr(inicio, "_avisos_importantes") and not hasattr(inicio, "AVISOS_REAJUSTE_NA_CAIXA")


def test_fila_que_a_caixa_le_ignora_pendencia_de_cadastro_e_marca_o_aviso_sem_data(cenario, monkeypatch):
    # issue #666: a fila da caixa e' `avisos.listar` (a mesma da tela Avisos). A pendencia de cadastro (natureza
    # "ausencia") nao chega a nenhum perfil; o aviso de fato sem data chega com `data` e `dias` nulos, que e' o que
    # a tela usa para deixa-lo fora da agenda (`secaoDoAviso` em frontend/src/avisos.ts)
    from app import avisos
    c, cid = cenario
    base = {"nivel": "acao", "publico": ["operacao", "diretoria"], "contrato_id": cid, "obra": "Obra A",
            "valor_centavos": None, "destino": {"tela": "contrato", "id": cid, "aba": "prazos"}}

    def fonte(conn, hoje):
        return [
            {**base, "tipo": "com_data", "mensagem": "Obra A: com data", "data": "2026-10-01", "dias": None, "sentido": "prazo"},
            {**base, "tipo": "sem_data", "mensagem": "Obra A: sem data", "data": None, "dias": None, "sentido": None},
            {**base, "tipo": "pendencia", "mensagem": "Obra A: documento fora do cadastro", "data": "2026-09-01",
             "dias": None, "sentido": "desde", "natureza": "ausencia"}]
    monkeypatch.setattr(avisos, "FONTES", [fonte])
    for publico in ("operacao", "diretoria"):
        fila = {a["tipo"]: a for a in avisos.listar(c, HOJE, publico=publico)}
        assert set(fila) == {"com_data", "sem_data"}
        assert fila["com_data"]["dias"] == -8                    # vencido ha' 8 dias: entra na caixa
        assert fila["sem_data"]["data"] is None and fila["sem_data"]["dias"] is None      # fora da agenda


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


# --- recebido em 12 meses e previsao de entrada pelo prazo do orgao (#652) ---

def _obra_de(c, chave, nome, familia, numero):
    """Mais um orgao e um contrato dele."""
    c.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES (?, ?, ?, '{}')", (chave, nome, familia))
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos, orgao_id) "
              "VALUES (?, ?, ?, 'obra', 100, (SELECT id FROM orgaos WHERE chave=?))", (nome, numero, f"Obra {numero}", chave))
    c.commit()
    return c.execute("SELECT MAX(id) FROM contratos").fetchone()[0]


def _recebidas(c, cid, dias, recebida_em="2026-09-30", primeiro_numero=100):
    """Uma medicao recebida em `recebida_em` para cada prazo de `dias` (protocolo = recebimento - dias)."""
    fim = D.fromisoformat(recebida_em)
    for i, n in enumerate(dias):
        mid = _medicao(c, cid, primeiro_numero + i, "2026-01-01 10:00:00", 1_000, estado="recebida", recebida_em=recebida_em)
        _protocolar(c, mid, (fim - datetime.timedelta(days=n)).isoformat())


def _protocolada(c, cid, numero, protocolo, pedido, aprovado=None):
    mid = _no_ciclo(c, cid, numero, "protocolada", pedido, aprovado=aprovado)
    if protocolo:
        _protocolar(c, mid, protocolo)
    return mid


def _previsao(c):
    return {k: (v["valor_centavos"], v["quantidade"]) for k, v in inicio.painel(c, HOJE)["previsao"].items()}


VAZIA = {"neste_mes": (0, 0), "proximo_mes": (0, 0), "atrasado": (0, 0), "sem_previsao": (0, 0), "depois": (0, 0)}


def test_recebido_12_meses_termina_no_mes_corrente_e_bate_com_o_rm_por_mes(cenario):
    from app import diretoria
    c, cid = cenario
    c.execute("UPDATE contratos SET percentual_direito_bp=5000, centro_custo_rm='9.001.002' WHERE id=?", (cid,))
    col = c.execute("SELECT e.coligada_rm FROM contratos k JOIN entidades e ON e.id=COALESCE(k.entidade_id, 1) WHERE k.id=?",
                    (cid,)).fetchone()[0]
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, centro_custo, "
                    "codtmv) VALUES (?, 1, '1', '2025-08-05', 900000, 'ativa', '9.001.002', '2.2.01')", (col,)).lastrowid
    baixas = ((11, 100_001, 1, "2025-10-31"),     # 13o mes para tras: fora da serie
              (12, 100_001, 1, "2025-11-01"),     # primeiro mes da serie: 50.001 na cota
              (13, 40_000, 1, "2026-03-10"), (14, 20_001, 4, "2026-03-28"),     # dois titulos no mesmo mes
              (15, 60_000, 1, "2026-10-02"),      # mes corrente, parcial
              (16, 80_000, 0, "2026-10-05"),      # titulo em aberto nao e' recebido
              (17, 70_000, 1, "2026-11-03"))      # mes futuro: fora
    for idlan, valor, status, data in baixas:
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan, data_baixa) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (col, idlan, nid, idlan, valor, valor, status, data))
    c.commit()
    serie = inicio.painel(c, HOJE)["recebido_12m"]
    assert [x["mes"] for x in serie] == ["2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
                                         "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    valores = {x["mes"]: x["valor_centavos"] for x in serie}
    rm = diretoria.rm_por_mes(c)[1]
    assert valores == {m: rm.get(m, 0) for m in valores}          # a mesma conta, mes a mes
    assert valores["2025-11"] == 50_001 and valores["2026-10"] == 30_000
    assert valores["2026-03"] == rm["2026-03"] > 0
    assert sum(valores.values()) == sum(v for m, v in rm.items() if "2025-11" <= m <= "2026-10")


def test_recebido_12_meses_vira_o_ano():
    assert inicio._ultimos_12_meses(D(2026, 1, 31)) == [f"2025-{m:02d}" for m in range(2, 13)] + ["2026-01"]


def test_prazo_do_orgao_e_o_terceiro_quartil_dos_recebimentos(cenario):
    """Issue #711 (docs/adr/0007): o prazo e' o terceiro quartil, o prazo de posicao ceil(0,75 * n) entre os dias em
    ordem: sempre um prazo que aconteceu (inteiro), nunca interpolado."""
    from app import diretoria
    c, cid = cenario
    seis = _obra_de(c, "prefeitura_alfa", "Prefeitura Alfa", "prefeitura", "CT 2/2025")
    oito = _obra_de(c, "autarquia_beta", "Autarquia Beta", "ses", "CT 5/2025")
    _recebidas(c, cid, [100, 10, 30, 40, 20])                               # cinco casos: o 4o (a mediana seria 30)
    _recebidas(c, seis, [60, 10, 41, 30, 20, 50], primeiro_numero=200)      # seis: o 5o (a mediana seria 35,5)
    _recebidas(c, oito, [80, 10, 70, 20, 60, 30, 50, 40], primeiro_numero=300)   # oito: 0,75 * 8 = 6, o 6o
    prazos = diretoria.prazos_do_orgao(diretoria._medicoes(c), HOJE)
    assert prazos == {"MTPAR": 40, "Prefeitura Alfa": 50, "Autarquia Beta": 60}
    assert all(type(v) is int for v in prazos.values())


def test_prazo_do_orgao_agrupa_pelo_contratante_e_nao_pela_superintendencia(cenario):
    from app import diretoria
    c, _ = cenario
    a = _obra_de(c, "sinfra_a", "SINFRA - SUEF II", "sinfra", "CT 3/2025")
    b = _obra_de(c, "sinfra_b", "SINFRA - SUPU (Pavimentação Urbana)", "sinfra", "CT 4/2025")
    _recebidas(c, a, [10, 20, 30])
    _recebidas(c, b, [40, 50], primeiro_numero=200)
    assert diretoria.prazos_do_orgao(diretoria._medicoes(c), HOJE) == {"SINFRA": 40}


def test_prazo_do_orgao_exige_cinco_recebimentos_em_365_dias(cenario):
    from app import diretoria
    c, cid = cenario
    _recebidas(c, cid, [10, 20, 30, 40])
    assert diretoria.prazos_do_orgao(diretoria._medicoes(c), HOJE) == {}
    _recebidas(c, cid, [50], recebida_em="2025-10-08", primeiro_numero=200)     # ha' 366 dias: nao conta
    _medicao(c, cid, 300, "2026-01-01 10:00:00", 1_000, estado="recebida", recebida_em="2026-09-30")   # sem protocolo
    _recebidas(c, cid, [50], recebida_em="2026-10-10", primeiro_numero=600)     # recebida amanha: nao conta
    futuro = _medicao(c, cid, 700, "2026-01-01 10:00:00", 1_000, estado="recebida", recebida_em="2026-09-30")
    _protocolar(c, futuro, "2026-10-01")                                         # protocolo depois do recebimento: nao conta
    assert diretoria.prazos_do_orgao(diretoria._medicoes(c), HOJE) == {}
    _protocolada(c, cid, 400, "2026-08-29", 7_000)
    assert _previsao(c) == {**VAZIA, "sem_previsao": (7_000, 1)}                # sem prazo, sem data esperada
    _recebidas(c, cid, [50], recebida_em="2025-10-09", primeiro_numero=500)     # ha' 365 dias: o quinto caso
    assert diretoria.prazos_do_orgao(diretoria._medicoes(c), HOJE) == {"MTPAR": 40}
    assert _previsao(c) == {**VAZIA, "atrasado": (7_000, 1)}                    # 29/08 + 40 dias = 08/10: ja' passou


def test_previsao_classifica_neste_mes_no_proximo_atrasado_e_depois(cenario):
    c, cid = cenario
    _recebidas(c, cid, [30] * 5)                                   # prazo do contratante: 30 dias
    lento = _obra_de(c, "prefeitura_alfa", "Prefeitura Alfa", "prefeitura", "CT 2/2025")
    _recebidas(c, lento, [90] * 5, primeiro_numero=200)            # 90 dias
    sem = _obra_de(c, "autarquia_beta", "Autarquia Beta", "ses", "CT 5/2025")
    _protocolada(c, cid, 1, "2026-09-08", 1_001)                   # esperada 08/10: ja' passou (31 dias > 30)
    _protocolada(c, cid, 2, "2026-09-09", 2_000)                   # esperada hoje: neste mes
    _protocolada(c, cid, 3, "2026-10-01", 9_999, aprovado=3_000)   # esperada 31/10; vale o aprovado
    _protocolada(c, cid, 4, "2026-10-02", 4_000)                   # esperada 01/11: no proximo mes
    _protocolada(c, cid, 5, "2026-10-09", 5_000)                   # esperada 08/11
    _protocolada(c, lento, 6, "2026-09-02", 6_000)                 # esperada 01/12: depois do proximo mes
    _protocolada(c, lento, 7, "2026-06-01", 7_000)                 # esperada 30/08: atrasado
    _protocolada(c, sem, 8, "2026-01-05", 8_000)                   # contratante sem prazo
    _protocolada(c, cid, 9, None, 9_000)                           # sem data de protocolo: fora da previsao
    recebida = _medicao(c, cid, 10, "2026-09-01 10:00:00", 333, estado="recebida", recebida_em="2026-10-02")
    _protocolar(c, recebida, "2026-09-02")                         # ja' recebida: nao e' previsao
    assert _previsao(c) == {"neste_mes": (5_000, 2), "proximo_mes": (9_000, 2), "atrasado": (8_001, 2),
                            "sem_previsao": (8_000, 1), "depois": (6_000, 1)}
    # cada protocolada com data cai em uma e so' uma linha: as cinco somam a etapa "Protocolado" da faixa do ciclo
    assert sum(v for v, _ in _previsao(c).values()) == _etapas(c)["protocolado"][0] == 36_001
    assert sum(q for _, q in _previsao(c).values()) == _etapas(c)["protocolado"][1] == 8


def test_previsao_entre_a_mediana_e_o_terceiro_quartil_nao_e_atrasado(cenario):
    """Issue #711 (docs/adr/0007): com a mediana, metade dos pagamentos normais aparecia como atrasada. Atrasado e' quem
    passou do terceiro quartil do contratante."""
    c, cid = cenario
    _recebidas(c, cid, [10, 20, 30, 40, 50])                       # mediana 30; terceiro quartil 40
    _protocolada(c, cid, 1, "2026-09-04", 1_001)                   # ha' 35 dias: passou da mediana, nao do quartil
    _protocolada(c, cid, 2, "2026-08-30", 2_000)                   # ha' 40 dias: a data esperada e' hoje
    _protocolada(c, cid, 3, "2026-08-29", 4_000)                   # ha' 41 dias: passou do quartil
    assert _previsao(c) == {**VAZIA, "neste_mes": (3_001, 2), "atrasado": (4_000, 1)}
    # as linhas continuam somando o valor e a quantidade da etapa Protocolado
    assert sum(v for v, _ in _previsao(c).values()) == _etapas(c)["protocolado"][0] == 7_001
    assert sum(q for _, q in _previsao(c).values()) == _etapas(c)["protocolado"][1] == 3


def test_previsao_do_inicio_usa_o_terceiro_quartil_do_prazo(cenario):
    """Issue #711: uma conta so' (o previsto da tela A receber, que tambem a usava, saiu na #748)."""
    c, cid = cenario
    c.execute("INSERT OR REPLACE INTO cadastro_geral (chave, valor) VALUES ('diretoria', '{\"total_a_receber_liberado\": true}')")
    c.commit()
    c.execute("UPDATE contratos SET percentual_direito_bp=5000")   # consorcio a 50%: 100.001 -> 50.001 na cota
    c.commit()
    _recebidas(c, cid, [10, 20, 30, 70, 80])                       # terceiro quartil 70 (a mediana seria 30)
    _protocolada(c, cid, 1, "2026-09-20", 100_001)                 # + 70 dias = 29/11: no proximo mes
    assert _previsao(c) == {**VAZIA, "proximo_mes": (50_001, 1)}   # com a mediana (20/10) seria "neste mes"


def test_contratante_sem_prazo_fica_sem_previsao(cenario):
    """Issue #711: contratante com menos de cinco recebimentos nao tem numero padrao; a protocolada dele fica em "Sem
    previsao" no Inicio, e o a receber nao muda."""
    from app import diretoria
    c, cid = cenario
    c.execute("INSERT OR REPLACE INTO cadastro_geral (chave, valor) VALUES ('diretoria', '{\"total_a_receber_liberado\": true}')")
    c.commit()
    _recebidas(c, cid, [30] * 4)
    _protocolada(c, cid, 1, "2026-09-20", 5_001)
    assert _previsao(c) == {**VAZIA, "sem_previsao": (5_001, 1)}
    assert sum(diretoria.a_receber_por_obra(c, na_cota=True).values()) == 5_001     # o a receber nao muda


def test_previsao_vira_o_ano_no_proximo_mes(cenario):
    c, cid = cenario
    _recebidas(c, cid, [30] * 5)
    _protocolada(c, cid, 1, "2026-12-05", 1_000)                   # esperada 04/01/2027
    _protocolada(c, cid, 2, "2026-11-25", 2_000)                   # esperada 25/12
    p = inicio.painel(c, D(2026, 12, 10))["previsao"]
    assert (p["proximo_mes"], p["neste_mes"]) == ({"valor_centavos": 1_000, "quantidade": 1},
                                                  {"valor_centavos": 2_000, "quantidade": 1})


def test_previsao_na_cota_da_lotufo_com_centavo_impar(cenario):
    # consorcio a 50%: cada medicao vai para a cota com o arredondamento unico (100.001 -> 50.001); duas somam 100.002
    c, cid = cenario
    c.execute("UPDATE contratos SET percentual_direito_bp=5000")
    _recebidas(c, cid, [30] * 5)
    _protocolada(c, cid, 1, "2026-10-05", 100_001)
    _protocolada(c, cid, 2, "2026-10-06", 999_999, aprovado=100_001)
    assert _previsao(c) == {**VAZIA, "proximo_mes": (100_002, 2)}
    assert _etapas(c)["protocolado"][0] == 100_002


# --- matriz obra por competencia (#659): a etapa da medicao de cada mes, obra a obra ---

def _na_matriz(c, cid, numero, estado, competencia, tipo="execucao", protocolo=None):
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, criado_em) "
              "VALUES (?, ?, ?, ?, ?, 1000, '2026-01-01 10:00:00')", (cid, numero, tipo, competencia, estado))
    c.commit()
    mid = c.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]
    if protocolo:
        _protocolar(c, mid, protocolo)
    return mid


def _matriz(c, hoje=HOJE):
    return inicio.painel(c, hoje)["matriz"]


def _celulas(c, cid, hoje=HOJE):
    """As celulas pintadas da obra: competencia -> (etapa, medicao)."""
    m = _matriz(c, hoje)
    obra = next(o for g in m["grupos"] for o in g["obras"] if o["contrato_id"] == cid)
    assert len(obra["celulas"]) == len(m["competencias"]) == 12
    return {comp: (cel["etapa"], cel["medicao_id"]) for comp, cel in zip(m["competencias"], obra["celulas"]) if cel}


def test_matriz_tem_12_competencias_ate_o_mes_anterior_e_as_obras_ativas_por_contratante(cenario):
    c, cid = cenario
    b = _obra_de(c, "sinfra_b", "SINFRA - SUPU (Pavimentação Urbana)", "sinfra", "CT 4/2025")
    a = _obra_de(c, "sinfra_a", "SINFRA - SUEF II", "sinfra", "CT 3/2025")
    encerrada = _obra_de(c, "prefeitura_alfa", "Prefeitura Alfa", "prefeitura", "CT 2/2025")
    c.execute("UPDATE contratos SET estado='encerrado' WHERE id=?", (encerrada,)); c.commit()
    m = _matriz(c)
    assert m["competencias"] == ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
                                 "2026-06", "2026-07", "2026-08", "2026-09"]
    # agrupadas pelo contratante (a SINFRA inteira, como na previsao); obra ativa sem medicao tem a linha vazia
    assert [(g["contratante"], [(o["contrato_id"], o["obra"]) for o in g["obras"]]) for g in m["grupos"]] == [
        ("MTPAR", [(cid, "Obra A")]), ("SINFRA", [(a, "Obra CT 3/2025"), (b, "Obra CT 4/2025")])]
    assert all(o["celulas"] == [None] * 12 for g in m["grupos"] for o in g["obras"])
    assert _matriz(c, D(2027, 1, 5))["competencias"][-2:] == ["2026-11", "2026-12"]      # vira o ano


def test_matriz_etapa_de_cada_medicao_pelo_estado(cenario):
    c, cid = cenario
    ids = {estado: _na_matriz(c, cid, n, estado, f"2026-{n:02d}") for n, estado in enumerate(
        ["planilha_enviada", "boletim_recebido", "espelho_gerado", "espelho_enviado", "nota_emitida", "protocolada",
         "nf_emitida", "recebida"], start=1)}
    # nao pintam: cancelada e desistida (a issue), e as que ainda nao entraram no ciclo (prevista, planilha gerada)
    for n, estado in enumerate(["cancelada", "desistida", "prevista", "planilha_gerada"], start=20):
        _na_matriz(c, cid, n, estado, "2026-09")
    _na_matriz(c, cid, 30, "recebida", "2025-09")          # competencia fora das 12
    _na_matriz(c, cid, 31, "recebida", "2026-10")          # o mes corrente nao entra
    assert _celulas(c, cid) == {
        "2026-01": ("em_analise", ids["planilha_enviada"]), "2026-02": ("boletim", ids["boletim_recebido"]),
        "2026-03": ("boletim", ids["espelho_gerado"]), "2026-04": ("boletim", ids["espelho_enviado"]),
        "2026-05": ("nota", ids["nota_emitida"]), "2026-06": ("protocolado", ids["protocolada"]),
        "2026-07": ("protocolado", ids["nf_emitida"]), "2026-08": ("recebida", ids["recebida"])}


def test_matriz_competencia_com_execucao_e_reajuste_mostra_a_menos_adiantada(cenario):
    c, cid = cenario
    _na_matriz(c, cid, 1, "recebida", "2026-08")
    reajuste_ = _na_matriz(c, cid, 1, "nota_emitida", "2026-08", tipo="reajuste")
    execucao = _na_matriz(c, cid, 2, "planilha_enviada", "2026-07")
    _na_matriz(c, cid, 2, "protocolada", "2026-07", tipo="reajuste")
    so_ela = _na_matriz(c, cid, 3, "recebida", "2026-06")
    _na_matriz(c, cid, 3, "cancelada", "2026-06", tipo="reajuste")       # a cancelada nao segura a celula
    assert _celulas(c, cid) == {"2026-08": ("nota", reajuste_), "2026-07": ("em_analise", execucao),
                                "2026-06": ("recebida", so_ela)}


def test_matriz_protocolada_alem_do_prazo_do_contratante_e_atrasada_como_na_previsao(cenario):
    c, cid = cenario
    _recebidas(c, cid, [30] * 5)                                         # prazo do contratante: 30 dias
    sem = _obra_de(c, "autarquia_beta", "Autarquia Beta", "ses", "CT 5/2025")
    atrasada = _na_matriz(c, cid, 1, "protocolada", "2026-07", protocolo="2026-09-08")    # esperada 08/10: ja' passou
    no_prazo = _na_matriz(c, cid, 2, "protocolada", "2026-06", protocolo="2026-09-09")    # esperada hoje
    sem_data = _na_matriz(c, cid, 3, "protocolada", "2026-05")                            # sem data de protocolo
    sem_prazo = _na_matriz(c, sem, 4, "protocolada", "2026-07", protocolo="2026-01-05")   # contratante sem prazo
    # duas protocoladas na competencia, uma atrasada: a celula e' a atrasada
    _na_matriz(c, cid, 5, "protocolada", "2026-04", protocolo="2026-10-01")
    par = _na_matriz(c, cid, 5, "protocolada", "2026-04", tipo="reajuste", protocolo="2026-08-01")
    cel = _celulas(c, cid)
    assert {k: cel[k] for k in ("2026-07", "2026-06", "2026-05", "2026-04")} == {
        "2026-07": ("atrasado", atrasada), "2026-06": ("protocolado", no_prazo), "2026-05": ("protocolado", sem_data),
        "2026-04": ("atrasado", par)}
    assert _celulas(c, sem) == {"2026-07": ("protocolado", sem_prazo)}
    # a mesma regra da previsao de entrada: as atrasadas da matriz sao as da linha "Atrasado"
    assert inicio.painel(c, HOJE)["previsao"]["atrasado"]["quantidade"] == 2


# --- issue #817: ciclo por contratante e medido em 12 meses ---

ETAPAS_DO_CICLO = ("em_analise", "boletim", "nota", "protocolado")


def _liberar_a_receber(c):
    c.execute("INSERT INTO cadastro_geral (chave, valor) VALUES ('diretoria', ?)",
              (json.dumps({"total_a_receber_liberado": True}),))
    c.commit()


def _por_contratante(p):
    return {x["contratante"]: tuple(x[f"{e}_centavos"] for e in ETAPAS_DO_CICLO) + (x["a_receber_centavos"],)
            for x in p["ciclo_por_contratante"]}


def _fecha_com_a_faixa(p):
    """Em cada etapa, a soma dos contratantes e' o numero da faixa do ciclo; a do a receber, o total do a receber."""
    faixa = {e["etapa"]: e["valor_centavos"] for e in p["ciclo"]}
    for etapa in ETAPAS_DO_CICLO:
        assert sum(x[f"{etapa}_centavos"] for x in p["ciclo_por_contratante"]) == faixa[etapa], etapa
    if p["a_receber"]["liberado"]:
        assert sum(x["a_receber_centavos"] for x in p["ciclo_por_contratante"]) == p["a_receber"]["valor_centavos"]
    else:
        assert all(x["a_receber_centavos"] is None for x in p["ciclo_por_contratante"])


def test_ciclo_por_contratante_fecha_com_a_faixa_em_cada_etapa_e_com_o_a_receber(cenario):
    """A soma por contratante, em cada etapa, e' o total que o Inicio ja' mostra; a do a receber e' o total dele. Cota
    com centavo impar em consorcio (50% e um terco), a SINFRA numa linha so', medicao sem a data do evento, pendencia
    a' parte e nota do RM sem medicao."""
    from app import diretoria
    c, mtpar = cenario
    c.execute("UPDATE contratos SET percentual_direito_bp=5000 WHERE id=?", (mtpar,))
    suef = _obra_de(c, "sinfra_a", "SINFRA - SUEF II", "sinfra", "CT 3/2025")
    supu = _obra_de(c, "sinfra_b", "SINFRA - SUPU (Pavimentação Urbana)", "sinfra", "CT 4/2025")
    alfa = _obra_de(c, "prefeitura_alfa", "Prefeitura Alfa", "prefeitura", "CT 2/2025")
    c.execute("UPDATE contratos SET percentual_direito_bp=3333 WHERE id=?", (alfa,))
    c.execute("UPDATE contratos SET centro_custo_rm='9.001.003' WHERE id=?", (supu,))
    _liberar_a_receber(c)
    # em analise: duas no consorcio a 50% (100.001 -> 50.001 cada: 100.002, e nao a cota da soma) e uma na SINFRA
    _no_ciclo(c, mtpar, 1, "planilha_enviada", 100_001, planilha_enviada_em="2026-10-08")
    _no_ciclo(c, mtpar, 2, "planilha_enviada", 100_001, planilha_enviada_em="2026-10-07")
    _no_ciclo(c, suef, 3, "planilha_enviada", 70_007, planilha_enviada_em="2026-10-01")
    _no_ciclo(c, supu, 4, "planilha_enviada", 999)                                     # sem a data do envio: fora
    # boletim: so' na Prefeitura Alfa, a um terco (100.000 x 33,33% = 33.330)
    _no_ciclo(c, alfa, 5, "espelho_gerado", 999_999, aprovado=100_000, atestado_em="2026-10-02")
    # nota: as duas superintendencias da SINFRA somam numa linha
    _no_ciclo(c, suef, 6, "nota_emitida", 9, aprovado=20_001, nota_emitida_em="2026-10-03")
    _no_ciclo(c, supu, 7, "nota_emitida", 9, aprovado=30_002, nota_emitida_em="2026-10-04")
    # protocolado: uma com a data do protocolo em cada contratante; a sem data fica fora da etapa e dentro do a receber
    _protocolada(c, mtpar, 8, "2026-09-10", 300_003)                                   # 150.001,5 -> 150.002
    _protocolada(c, supu, 9, "2026-09-11", 40_000)
    _protocolada(c, alfa, 10, None, 90_000)                                            # 90.000 x 33,33% = 29.997
    # a' parte (competencia anterior a 2025): fora da etapa, do a receber e da linha do contratante
    velha = _medicao(c, suef, 11, "2024-12-20 10:00:00", 555_555, estado="protocolada", competencia="2024-11")
    _protocolar(c, velha, "2024-12-22")
    # nota do RM em aberto sem medicao, na obra da SUPU pelo centro de custo: entra so' no a receber
    col = c.execute("SELECT e.coligada_rm FROM contratos k JOIN entidades e ON e.id=COALESCE(k.entidade_id, 1) WHERE k.id=?",
                    (supu,)).fetchone()[0]
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, centro_custo, "
                    "codtmv) VALUES (?, 71, '71', '2026-09-05', 60001, 'ativa', '9.001.003', '2.2.01')", (col,)).lastrowid
    c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
              "status_lan) VALUES (?, 71, ?, 71, 60001, 0, 0)", (col, nid))
    c.commit()
    p = inicio.painel(c, HOJE)
    _fecha_com_a_faixa(p)
    assert {e["etapa"]: e["valor_centavos"] for e in p["ciclo"]} == {
        "em_analise": 170_009, "boletim": 33_330, "nota": 50_003, "protocolado": 190_002, "recebido_mes": 0}
    assert p["a_receber"]["valor_centavos"] == 150_002 + 40_000 + 60_001 + 29_997
    assert p["a_receber"]["a_parte"]["anterior_centavos"] == 555_555
    #                                         em analise, boletim, nota, protocolado, a receber
    assert _por_contratante(p) == {"SINFRA": (70_007, 0, 50_003, 40_000, 100_001),
                                   "MTPAR": (100_002, 0, 0, 150_002, 150_002),
                                   "Prefeitura Alfa": (0, 33_330, 0, 0, 29_997)}
    # do que tem mais dinheiro nas quatro etapas para o que tem menos; a chave e' a da pagina do contratante
    assert [(x["contratante"], x["chave"]) for x in p["ciclo_por_contratante"]] == [
        ("MTPAR", "mtpar"), ("SINFRA", "sinfra"), ("Prefeitura Alfa", "prefeitura_alfa")]
    assert {x["chave"] for x in p["ciclo_por_contratante"]} == {
        diretoria.contratante_da_obra(c, cid)["contratante_chave"] for cid in (mtpar, suef, supu, alfa)}


def test_ciclo_por_contratante_sem_o_total_liberado_nao_traz_o_a_receber(cenario):
    c, cid = cenario
    _no_ciclo(c, cid, 1, "planilha_enviada", 1_001, planilha_enviada_em="2026-10-08")
    _protocolada(c, cid, 2, "2026-09-10", 2_003)
    p = inicio.painel(c, HOJE)
    assert p["a_receber"]["liberado"] is False
    _fecha_com_a_faixa(p)
    assert _por_contratante(p) == {"MTPAR": (1_001, 0, 0, 2_003, None)}


def test_ciclo_por_contratante_vazio_sem_medicao_e_obra_sem_orgao_sem_chave(cenario):
    c, _ = cenario
    _liberar_a_receber(c)
    assert inicio.painel(c, HOJE)["ciclo_por_contratante"] == []
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
              "VALUES ('texto livre', 'CT 9/2025', 'Obra sem órgão', 'obra', 100)")
    solta = c.execute("SELECT MAX(id) FROM contratos").fetchone()[0]
    _no_ciclo(c, solta, 1, "planilha_enviada", 4_004, planilha_enviada_em="2026-10-08")
    p = inicio.painel(c, HOJE)
    _fecha_com_a_faixa(p)
    assert p["ciclo_por_contratante"] == [{"contratante": "sem órgão", "chave": None, "em_analise_centavos": 4_004,
                                           "boletim_centavos": 0, "nota_centavos": 0, "protocolado_centavos": 0,
                                           "a_receber_centavos": 0}]


def test_medido_12_meses_sao_as_competencias_fechadas_com_a_conta_do_fechamento(cenario):
    """A serie do medido e' a do Fechamento, competencia a competencia, na cota: as 12 ultimas fechadas (as da matriz),
    sem o mes de hoje. Consorcio com centavo impar; cancelada, prevista e planilha so' gerada nao medem."""
    from app import fechamento
    c, cid = cenario
    c.execute("UPDATE contratos SET percentual_direito_bp=5000 WHERE id=?", (cid,))
    propria = _obra_de(c, "sinfra_a", "SINFRA - SUEF II", "sinfra", "CT 3/2025")
    _no_ciclo(c, cid, 1, "planilha_enviada", 100_001)                       # so' o pedido: 50.001 na cota
    _no_ciclo(c, cid, 2, "espelho_gerado", 999_999, aprovado=100_001)       # o aprovado vale: mais 50.001
    _no_ciclo(c, propria, 3, "recebida", 7_007)
    for numero, estado in ((4, "cancelada"), (5, "prevista"), (6, "planilha_gerada")):
        _no_ciclo(c, propria, numero, estado, 1_000_000)
    _medicao(c, propria, 7, "2025-11-05 10:00:00", 30_003, estado="recebida", competencia="2025-10")
    _medicao(c, propria, 8, "2025-10-05 10:00:00", 9_999, estado="recebida", competencia="2025-09")   # 13a para tras
    _medicao(c, propria, 9, "2026-10-08 10:00:00", 8_888, estado="planilha_enviada", competencia="2026-10")  # mes de hoje
    p = inicio.painel(c, HOJE)
    serie = p["medido_12m"]
    assert [x["competencia"] for x in serie] == p["matriz"]["competencias"]
    assert (serie[0]["competencia"], serie[-1]["competencia"]) == ("2025-10", "2026-09")
    do_fechamento = {m["competencia"]: m["medido_centavos"] for m in fechamento.fechamento(c, HOJE)["meses"]}
    assert do_fechamento["2026-10"] == 8_888 and do_fechamento["2025-09"] == 9_999       # o Fechamento os tem; a serie nao
    assert {x["competencia"]: x["valor_centavos"] for x in serie} == {
        x["competencia"]: do_fechamento.get(x["competencia"], 0) for x in serie}
    valores = {x["competencia"]: x["valor_centavos"] for x in serie}
    assert valores["2026-09"] == 50_001 + 50_001 + 7_007 and valores["2025-10"] == 30_003
    assert sum(valores.values()) == 137_012 and valores["2026-08"] == 0
    # nao e' a conta do cartao do alto, que e' valor cheio (B-01): em consorcio os dois numeros diferem
    assert p["medido"]["valor_centavos"] == 100_001 + 100_001 + 7_007 != valores["2026-09"]

