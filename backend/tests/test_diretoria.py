"""Tela da diretoria (bloco 8; spec §10.5): na cota, prazo do orgao, faixas, mes e ano, proximos, carteira."""
import datetime
import json
import pathlib
import sys

import pytest

from app import auth, avisos, cadastro_aplicar, db, diretoria, medicoes, qdop, reajuste
from tests.test_protocolo import _contrato

D = datetime.date
HOJE = D(2026, 9, 24)
MODELO = pathlib.Path(__file__).parents[2] / "cadastro-exemplo" / "modelos" / "qdop" / "qdop-modelo.xlsx"
ATRASOS = [5, 5, 5, 6, 6, 7, 8, 9, 10, 12, 20, 40]


@pytest.fixture
def cenario(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    uid = auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "admin")
    propria = {**_contrato("Própria", "sinfra-x", "IC 1/2025"), "valor_original_centavos": 100_000_000,
               "execucao_inicio": "2025-01-01", "execucao_fim": "2027-01-31", "vigencia_fim": "2027-04-30"}
    consorcio = {**_contrato("Consórcio", "mtpar-x", "050/2024/MTPAR"), "entidade": "cons",
                 "valor_original_centavos": 1_000_000_000, "percentual_direito_bp": 5000,
                 "execucao_inicio": "2024-01-01", "execucao_fim": "2027-12-31", "vigencia_fim": "2028-03-31",
                 "instrumentos": [{"chave": "ta-1", "tipo": "aditivo_valor", "numero": "1º TA", "objeto": None,
                                   "corrige": None, "pdf": None, "delta_valor_centavos": 200_000_000,
                                   "nova_execucao_fim": None, "nova_vigencia_fim": None, "data": "2025-06-01",
                                   "dados": {}, "natureza": "execucao"}]}
    cadastro_aplicar.aplicar(c, uid, {
        "orgaos": [{"chave": "sinfra-x", "nome": "SINFRA - X", "familia": "sinfra", "cnpj": None,
                    "regras": {"nome_qdop": "SINFRA - SECRETARIA", "tipo_contratante": "PÚBLICO"}},
                   {"chave": "mtpar-x", "nome": "MTPAR", "familia": "mtpar", "cnpj": None,
                    "regras": {"nome_qdop": "MT-PAR", "tipo_contratante": "PÚBLICO"}}],
        "entidades": [{"chave": "lotufo", "nome": "Lotufo Engenharia e Construções Ltda", "cnpj": "31200101000130",
                       "papel": "lotufo", "coligada_rm": 1, "sigla_oficio": "LT", "nome_curto": "Lotufo"},
                      {"chave": "cons", "nome": "Consórcio Teste", "cnpj": "31200404000152", "papel": "consorcio",
                       "coligada_rm": None, "sigla_oficio": None, "nome_curto": "Consórcio"}],
        "contratos": [propria, consorcio], "avisos": [],
        "geral": {"qdop": {"modelo_caminho": str(MODELO)}, "diretoria": {"total_a_receber_liberado": False}}})
    p = c.execute("SELECT id FROM contratos WHERE nome_curto='Própria'").fetchone()[0]
    k = c.execute("SELECT id FROM contratos WHERE nome_curto='Consórcio'").fetchone()[0]

    def medir(cid, numero, comp, estado, valor, tipo="execucao", protocolo=None, recebida=None):
        mid = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
                        "recebida_em) VALUES (?,?,?,?,?,?,?)", (cid, numero, tipo, comp, estado, valor, recebida)).lastrowid
        if protocolo:
            c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, ?, 'manual')", (mid, protocolo))

    for i, atraso in enumerate(ATRASOS):               # 12 recebidas da SINFRA nos ultimos 12 meses
        comp = f"{2025 + (8 + i) // 12:04d}-{(8 + i) % 12 + 1:02d}"          # 2025-09 ... 2026-08
        prot = D(2026, 1, 5) + datetime.timedelta(days=14 * i)
        medir(p, i + 1, comp, "recebida", 800_000 if i == 0 else 100_000, protocolo=prot.isoformat(),
              recebida=(prot + datetime.timedelta(days=atraso)).isoformat())
    medir(p, 13, "2026-09", "espelho_gerado", 1_000_000)
    medir(p, 14, "2026-08", "protocolada", 700_000, protocolo="2026-09-10")
    medir(p, 15, "2026-06", "protocolada", 300_000, protocolo="2026-07-01")
    medir(k, 1, "2026-09", "espelho_enviado", 1_000_000)
    medir(k, 2, "2026-05", "recebida", 400_000_000, protocolo="2026-06-01", recebida="2026-06-20")
    medir(k, 2, "2026-05", "recebida", 10_000_000, tipo="reajuste", protocolo="2026-06-01", recebida="2026-06-20")
    v = c.execute("INSERT INTO cronograma_versoes (contrato_id, numero, criado_em) VALUES (?, 1, '2025-01-01 00:00:00')",
                  (p,)).lastrowid
    c.execute("INSERT INTO cronograma_itens (versao_id, competencia, valor_previsto_centavos) VALUES (?, '2026-09', 2000000)",
              (v,))
    c.commit()

    def liberar():
        c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'",
                  (json.dumps({"total_a_receber_liberado": True}),)); c.commit()

    yield c, {"propria": p, "consorcio": k, "sinfra": c.execute("SELECT id FROM orgaos WHERE chave='sinfra-x'").fetchone()[0],
              "mtpar": c.execute("SELECT id FROM orgaos WHERE chave='mtpar-x'").fetchone()[0], "liberar": liberar}
    c.close()


def test_dinheiro_na_cota_e_por_faixa(cenario):
    c, ids = cenario
    d = diretoria.painel(c, HOJE)["dinheiro"]
    assert d["medido_esperando_nota"]["valor_centavos"] == 1_000_000 + 500_000     # 10 mil proprio + 50% de 10 mil
    assert d["protocolado"]["faixas"]["mais_60"]["quantidade"] == 1


def test_a_receber_por_orgao_com_faixas_e_obras_sem_prazo_normal(cenario):
    c, ids = cenario                   # A4: protocoladas da SINFRA em 10/09 (14 dias) e 01/07 (85 dias)
    ids["liberar"]()
    o = diretoria.painel(c, HOJE)["dinheiro"]["protocolado"]["por_orgao"][0]
    assert (o["orgao_id"], o["maior_dias"]) == (ids["sinfra"], 85)
    assert "prazo_normal_dias" not in o          # issue #255: o prazo normal do orgao saiu
    assert (o["faixas"]["ate_30"]["valor_centavos"], o["faixas"]["mais_60"]["valor_centavos"]) == (700_000, 300_000)
    assert o["obras"] == [{"contrato_id": ids["propria"], "obra": "Própria", "quantidade": 2, "notas_rm": 0,
                           "valor_centavos": 1_000_000, "maior_dias": 85}]


def test_motivos_da_obra_um_a_um_sem_o_nome_da_obra(cenario, monkeypatch):
    c, ids = cenario                   # A5: motivos[] estruturado, na ordem dos avisos
    monkeypatch.setattr(diretoria._av, "listar", lambda conn, hoje, publico: [
        avisos.aviso("execucao_vencendo", "critico", "Própria: execução termina em 10 dias", ids["propria"], "Própria", dias=10),
        avisos.aviso("folga_quebrada", "acao", "Própria: 15ª Medição protocolada há 85 dias", ids["propria"], "Própria",
                     dias=85, valor_centavos=300_000)])
    obra = [o for o in diretoria.painel(c, HOJE)["obras"] if o["contrato_id"] == ids["propria"]][0]
    assert [(m["nivel"], m["texto"], m["dias"]) for m in obra["motivos"]] == [
        ("critico", "execução termina em 10 dias", 10), ("acao", "15ª Medição protocolada há 85 dias", 85)]
    assert obra["motivos"][1]["valor_centavos"] == 300_000 and obra["farol"] == "vermelho"


def test_farol_separa_acao_de_atencao(cenario, monkeypatch):
    c, ids = cenario                   # D10: o farol distingue Acao de Atencao (antes os dois eram "amarelo")
    def com(*avisos_):
        monkeypatch.setattr(diretoria._av, "listar", lambda conn, hoje, publico: list(avisos_))
        return [o for o in diretoria.painel(c, HOJE)["obras"] if o["contrato_id"] == ids["propria"]][0]["farol"]
    a = lambda nivel: avisos.aviso("folga_quebrada", nivel, "Própria: aviso", ids["propria"], "Própria", dias=5)
    assert com(a("atencao")) == "atencao"
    assert com(a("atencao"), a("acao")) == "acao"
    assert com(a("acao"), a("critico")) == "vermelho"
    assert com() == "verde"


def test_faturado_e_a_receber_da_obra_em_valor_cheio(cenario):
    c, ids = cenario                   # A3: recebidas 800 mil + 11 x 100 mil; protocoladas 700 mil e 300 mil
    assert diretoria.da_obra(c, ids["propria"]) == {"faturado_centavos": 2_900_000, "a_receber_centavos": None}
    ids["liberar"]()
    assert diretoria.da_obra(c, ids["propria"])["a_receber_centavos"] == 1_000_000
    assert diretoria.da_obra(c, ids["consorcio"])["faturado_centavos"] == 410_000_000     # cheio, nao a cota de 50%


def test_a_receber_por_obra_igual_ao_da_obra_e_escondido_ate_liberar(cenario):
    """Lista de Obras (#509): o a receber de todas as obras numa passada, na mesma conta de `da_obra`."""
    c, ids = cenario
    assert diretoria.a_receber_por_obra(c) is None
    ids["liberar"]()
    todas = diretoria.a_receber_por_obra(c)
    for chave in ("propria", "consorcio"):
        assert todas.get(ids[chave], 0) == diretoria.da_obra(c, ids[chave])["a_receber_centavos"]
    assert todas[ids["propria"]] == 1_000_000


def test_total_a_receber_escondido_ate_liberar(cenario):
    c, ids = cenario
    p = diretoria.painel(c, HOJE)
    assert p["total_a_receber_liberado"] is False
    assert p["dinheiro"]["protocolado"]["faixas"]["ate_30"]["valor_centavos"] is None
    ids["liberar"]()
    p = diretoria.painel(c, HOJE)
    assert p["dinheiro"]["protocolado"]["faixas"]["ate_30"]["valor_centavos"] == 700_000


def test_mes_e_ano_contra_previsto_e_ano_anterior(cenario):
    c, _ = cenario
    m = diretoria.painel(c, HOJE)["mes_ano"]
    assert (m["medido_mes_centavos"], m["previsto_mes_centavos"]) == (1_500_000, 2_000_000)
    assert m["mesmo_mes_ano_anterior_centavos"] == 800_000
    assert len(m["serie"]) == 12 and m["serie"][-1]["competencia"] == "2026-09"


def test_proximos_meses_so_com_o_faturamento_previsto(cenario):
    c, ids = cenario                   # issue #255: o recebimento previsto (mediana do orgao) saiu
    ids["liberar"]()
    proximos = diretoria.painel(c, HOJE)["proximos"]
    assert [x["competencia"] for x in proximos] == ["2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02"]
    assert proximos[0] == {"competencia": "2026-09", "faturamento_previsto_centavos": 2_000_000}
    assert all(set(x) == {"competencia", "faturamento_previsto_centavos"} for x in proximos)


def test_carteira_saldo_ritmo_e_termino(cenario):
    c, ids = cenario
    k = diretoria.painel(c, HOJE)["carteira"]
    # proprio: 1.000.000,00 - 39.000,00 medidos; consorcio: 50% de (12.000.000,00 - 4.010.000,00). #262 (gate Sol S2):
    # #561: o espelho gerado (10 mil, propria) e o enviado (10 mil, consorcio) medem, como em `paineis.saldo`
    assert k["saldo_centavos"] == 96_100_000 + 399_500_000
    assert "terminando" not in k
    assert k["ritmo_mensal_centavos"] == 33_833_333             # 203.000.000 / 6, meio para cima


def test_carteira_mede_so_execucao_nos_estados_que_medem(cenario):
    """#262 (gate Sol S2): saldo, medido e ritmo da carteira contam o que `paineis.saldo` conta: execucao a partir do
    envio da planilha/carta (#561). Projeto e planilha gerada (ainda nao enviada) nao reduzem o saldo nem o ritmo."""
    c, ids = cenario
    antes = diretoria.painel(c, HOJE)["carteira"]
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, 50, 'projeto', '2026-08', 'recebida', 3000001)", (ids["propria"],))
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, 51, 'execucao', '2026-08', 'planilha_gerada', 4000001)", (ids["propria"],))
    c.commit()
    depois = diretoria.painel(c, HOJE)["carteira"]
    assert depois["saldo_centavos"] == antes["saldo_centavos"]
    assert depois["ritmo_mensal_centavos"] == antes["ritmo_mensal_centavos"]
    assert ({o["orgao"]: o["medido_centavos"] for o in depois["por_orgao"]}
            == {o["orgao"]: o["medido_centavos"] for o in antes["por_orgao"]})
    # e a execucao protocolada conta: 1,01 (centavo impar) a menos no saldo da propria
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, 52, 'execucao', '2026-08', 'protocolada', 101)", (ids["propria"],))
    c.commit()
    assert diretoria.painel(c, HOJE)["carteira"]["saldo_centavos"] == antes["saldo_centavos"] - 101


def test_carteira_saldo_exclui_o_aditivo_de_reajuste(cenario):
    """#262: o aditivo de reajuste entra no vigente do contrato, mas o saldo a executar e' a precos iniciais."""
    c, ids = cenario
    c.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza) "
              "VALUES (?, 'valor', 50_000_001, 'assinado', '2026-03-01', 'reajuste')", (ids["consorcio"],))
    c.commit()
    k = diretoria.painel(c, HOJE)["carteira"]
    assert k["saldo_centavos"] == 96_100_000 + 399_500_000
    por = {o["orgao"]: o for o in k["por_orgao"]}
    assert por["MTPAR"]["vigente_centavos"] == 600_000_000      # 50% de 12.000.000,00, sem o reajuste


def test_faturado_no_mes_e_a_regra_do_qdop_fatiada_pelo_mes_da_nota(cenario):
    c, ids = cenario

    def nota_em(contrato, numero, data, tipo="execucao"):
        c.execute("UPDATE medicoes SET nota_emitida_em=? WHERE contrato_id=? AND numero=? AND tipo=?", (data, contrato, numero, tipo))
    nota_em(ids["propria"], 14, "2026-09-05")        # protocolada, 7.000,00: entra
    nota_em(ids["propria"], 1, "2026-09-20")         # recebida, 8.000,00: entra
    nota_em(ids["propria"], 15, "2026-06-15")        # faturada em junho: fora de setembro
    nota_em(ids["propria"], 13, "2026-09-12")        # espelho gerado, sem nota de fato: nao e' faturado
    nota_em(ids["consorcio"], 2, "2026-09-10")       # 4.000.000,00 a 50%: 2.000.000,00 na cota
    nota_em(ids["consorcio"], 2, "2026-09-10", "reajuste")   # reajuste nao entra (e' outra coluna do QDOP)
    c.commit()
    m = diretoria.painel(c, HOJE)["mes_ano"]
    assert m["faturado_mes_centavos"] == 700_000 + 800_000 + 200_000_000
    assert m["notas_faturadas_mes"] == 3
    # medicao com nota registrada, sem nota no RM (nenhuma linha em notas_fiscais), entra do mesmo jeito
    assert c.execute("SELECT COUNT(*) FROM notas_fiscais").fetchone()[0] == 0


def test_medicao_faturada_sem_data_da_nota_nao_entra_em_mes_nenhum(cenario):
    c, ids = cenario
    c.execute("UPDATE medicoes SET nota_emitida_em='2026-09-05' WHERE contrato_id=? AND numero=14", (ids["propria"],))
    c.commit()
    assert diretoria.painel(c, HOJE)["mes_ano"]["faturado_mes_centavos"] == 700_000
    c.execute("UPDATE medicoes SET nota_emitida_em=NULL WHERE contrato_id=? AND numero=14", (ids["propria"],))   # protocolada, sem data da nota
    c.commit()
    assert diretoria.painel(c, HOJE)["mes_ano"]["faturado_mes_centavos"] == 0
    # mas ela segue no "Faturado" acumulado do QDOP
    assert any(l["faturados"] >= 700_000 for l in qdop.linhas(c, HOJE) if l["contrato_id"] == ids["propria"])


def test_faturado_no_mes_bate_com_a_coluna_faturado_do_qdop(cenario):
    c, ids = cenario
    c.execute("UPDATE medicoes SET nota_emitida_em='2026-09-15'")      # todas as medicoes com nota no mesmo mes
    c.commit()
    total_qdop = sum(l["faturados"] for l in qdop.linhas(c, HOJE))
    assert total_qdop > 0
    assert diretoria.painel(c, HOJE)["mes_ano"]["faturado_mes_centavos"] == total_qdop
    # em outro mes, nada
    c.execute("UPDATE medicoes SET nota_emitida_em='2026-08-15'")
    c.commit()
    assert diretoria.painel(c, HOJE)["mes_ano"]["faturado_mes_centavos"] == 0


def test_carteira_por_orgao_traz_vigente_medido_e_obras_para_o_cartao(cenario):
    c, ids = cenario
    por = {o["orgao"]: o for o in diretoria.painel(c, HOJE)["carteira"]["por_orgao"]}
    # 06/11/2026: o cartao e' do contratante ("SINFRA" junta as superintendencias), nao de cada orgao do cadastro
    assert (por["SINFRA"]["vigente_centavos"], por["SINFRA"]["medido_centavos"], por["SINFRA"]["obras"]) == (100_000_000, 3_900_000, 1)
    assert (por["MTPAR"]["vigente_centavos"], por["MTPAR"]["medido_centavos"]) == (600_000_000, 200_500_000)


def test_protocolada_ha_200_dias_nao_gera_aviso_e_fica_em_mais_de_60(cenario):
    c, ids = cenario                   # issue #255: o motor de atraso de pagamento por orgao saiu
    c.execute("UPDATE medicao_protocolos SET data='2026-03-08' WHERE medicao_id=(SELECT id FROM medicoes "
              "WHERE contrato_id=? AND numero=15)", (ids["propria"],))          # 200 dias antes de 24/09
    c.commit()
    ids["liberar"]()
    p = diretoria.painel(c, HOJE)
    assert not [a for a in p["avisos"] if a["tipo"] == "pagamento_atrasado"]
    assert not [a for a in avisos.listar(c, HOJE, publico="todos") if a["tipo"] == "pagamento_atrasado"]
    assert not [m for o in p["obras"] for m in o["motivos"] if m["tipo"] == "pagamento_atrasado"]
    d = p["dinheiro"]["protocolado"]
    assert (d["faixas"]["mais_60"]["quantidade"], d["faixas"]["mais_60"]["valor_centavos"]) == (1, 300_000)
    assert d["valor_centavos"] == 1_000_000 and d["por_orgao"][0]["maior_dias"] == 200


def test_nota_em_aberto_no_rm_entra_no_a_receber_sem_contar_duas_vezes(cenario):
    c, ids = cenario
    def nota(idmov, emissao, falta, medicao_numero):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao) "
                        "VALUES (1, ?, ?, ?, ?, 'ativa')", (idmov, f"{idmov:09d}", emissao, falta)).lastrowid
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan) VALUES (1, ?, ?, ?, ?, 0, 0)", (idmov, nid, idmov, falta))
        mid = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=?", (ids["propria"], medicao_numero)).fetchone()[0]
        c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                  "VALUES (?, ?, ?, 'detectado', 't')", (mid, nid, falta))
    nota(900, "2026-06-01", 2_500_000, 1)    # medicao 1 ja' recebida (fechada): a nota em aberto e' que conta
    nota(901, "2026-09-12", 700_000, 14)     # medicao 14 protocolada: ja' conta pela medicao
    c.commit()
    ids["liberar"]()
    d = diretoria.painel(c, HOJE)["dinheiro"]["protocolado"]
    assert d["valor_centavos"] == 700_000 + 300_000 + 2_500_000
    assert d["faixas"]["mais_60"]["valor_centavos"] == 300_000 + 2_500_000
    # A14: das 3 cobrancas da SINFRA, 1 e' nota em aberto no RM
    o = d["por_orgao"][0]
    assert (d["notas_rm"], o["quantidade"], o["notas_rm"], o["obras"][0]["notas_rm"]) == (1, 3, 1, 1)


def test_recebimento_manual_tira_a_nota_do_a_receber_e_o_corte_nao(cenario):
    """Issue #203 (decisao A): medicao recebida a mao pelo admin com NF ligada e titulo aberto no RM nao soma de
    novo a nota em "a receber". A medicao fechada pelo corte continua com a
    nota em aberto no a receber, como antes."""
    c, ids = cenario
    uid = c.execute("SELECT id FROM usuarios").fetchone()[0]

    def nota(idmov, emissao, falta, medicao_numero):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao) "
                        "VALUES (1, ?, ?, ?, ?, 'ativa')", (idmov, f"{idmov:09d}", emissao, falta)).lastrowid
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan) VALUES (1, ?, ?, ?, ?, 0, 0)", (idmov, nid, idmov, falta))
        mid = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=?", (ids["propria"], medicao_numero)).fetchone()[0]
        c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                  "VALUES (?, ?, ?, 'detectado', 't')", (mid, nid, falta))
        return mid
    a_mao = nota(910, "2026-06-01", 2_000_001, 14)    # protocolada; o admin registra o recebimento a mao
    cortada = nota(911, "2026-06-02", 300_001, 15)    # protocolada; fecha pelo corte
    c.commit()
    medicoes.mudar_estado(c, uid, a_mao, "recebida", "a baixa nao entrou no RM; conferida no extrato", "2026-09-20")
    # o corte se reconhece pelo comeco do motivo, mesmo que o resto do texto da epoca seja outro
    medicoes.mudar_estado(c, uid, cortada, "recebida", "corte de 22/09/2026: faturado conta como pago", None)
    ids["liberar"]()
    d = diretoria.painel(c, HOJE)["dinheiro"]["protocolado"]
    assert d["valor_centavos"] == 300_001                  # so' a nota da medicao fechada pelo corte
    assert d["notas_rm"] == 1
    assert d["faixas"]["mais_60"]["valor_centavos"] == 300_001
    assert diretoria.da_obra(c, ids["propria"])["a_receber_centavos"] == 300_001


def test_nota_partida_com_medicao_do_corte_fica_inteira_e_baixa_parcial_a_mao_sai(cenario):
    """Gate Sol S1 da PR #206: a nota so' sai do a receber quando TODAS as medicoes ligadas foram recebidas a mao.
    Ligada tambem a medicao fechada pelo corte, fica inteira (como antes). Com baixa parcial e so' a medicao a mao,
    sai inteira: o registro manual vale."""
    c, ids = cenario
    uid = c.execute("SELECT id FROM usuarios").fetchone()[0]

    def mid(n):
        return c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=?", (ids["propria"], n)).fetchone()[0]

    def nota(idmov, devido, baixado, numeros):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao) "
                        "VALUES (1, ?, ?, '2026-06-01', ?, 'ativa')", (idmov, f"{idmov:09d}", devido)).lastrowid
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan) VALUES (1, ?, ?, ?, ?, ?, ?)", (idmov, nid, idmov, devido, baixado, 1 if baixado else 0))
        for n in numeros:
            c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                      "VALUES (?, ?, ?, 'detectado', 't')", (mid(n), nid, devido // len(numeros)))
    nota(920, 1_000_001, 0, (14, 15))          # partida: 14 a mao, 15 pelo corte
    nota(921, 500_001, 100_000, (14,))         # so' a 14 (a mao), baixa parcial no RM
    c.commit()
    medicoes.mudar_estado(c, uid, mid(14), "recebida", "a baixa nao entrou no RM; conferida no extrato", "2026-09-20",
                          origem="manual")
    medicoes.mudar_estado(c, uid, mid(15), "recebida", "corte de 22/09/2026: faturado conta como pago", None,
                          origem="corte")
    ids["liberar"]()
    d = diretoria.painel(c, HOJE)["dinheiro"]["protocolado"]
    assert (d["valor_centavos"], d["notas_rm"]) == (1_000_001, 1)


def test_reajustes_esperando_apostilamento_por_obra(cenario, monkeypatch):
    c, ids = cenario                   # A13: um item por ciclo, o mais antigo primeiro
    def ciclo(situacao, base, dias):
        return {"situacao": situacao, "data_base_mes": base, "dias": dias, "aniversario": f"{base}-01",
                "pleito": {"enviado_em": "2026-05-01T10:00:00"}, "apostilamento": None}
    ciclos = {ids["propria"]: [ciclo("apostilamento_pendente", "2025-01", 40)],
              ids["consorcio"]: [ciclo("apostilamento_pendente", "2024-01", 120), ciclo("apostilado", "2023-01", None)]}
    monkeypatch.setattr(diretoria.reajuste, "ciclos", lambda conn, cid, hoje=None: ciclos.get(cid, []))
    r = diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]
    assert (r["quantidade"], r["maior_dias"]) == (2, 120)
    assert [(x["obra"], x["data_base_mes"], x["dias"]) for x in r["itens"]] == [("Consórcio", "2024-01", 120),
                                                                               ("Própria", "2025-01", 40)]


def test_ciclo_a_reemitir_continua_esperando_apostilamento(cenario, monkeypatch):
    # issue #273: o cronograma a reemitir nao tira o ciclo do bloco "reajustes esperando apostilamento"
    c, ids = cenario
    ciclos = {ids["propria"]: [{"situacao": "reemitir", "data_base_mes": "2025-01", "dias": 40,
                                "aniversario": "2025-01-01", "pleito": {"enviado_em": "2026-05-01T10:00:00"},
                                "apostilamento": None}]}
    monkeypatch.setattr(diretoria.reajuste, "ciclos", lambda conn, cid, hoje=None: ciclos.get(cid, []))
    r = diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]
    assert (r["quantidade"], r["maior_dias"]) == (1, 40)


# --- issue #279 (spec 2026-10-20 §2.2): o reajuste ja' medido sem apostilamento, por competencia e na cota ---

def _reajuste(c, cid, numero, comp, estado, pedido=None, aprovado=None):
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
              "valor_atestado_centavos) VALUES (?, ?, 'reajuste', ?, ?, ?, ?)", (cid, numero, comp, estado, pedido, aprovado))
    c.commit()


def _data_base(c, cid, mes):
    c.execute("INSERT INTO contrato_datas_base (contrato_id, mes, indice) VALUES (?, ?, 'INCC-DI')", (cid, mes))
    c.commit()


def _apostilar(c, cid, chave, dados, competencias=()):
    """Apostilamento de reajuste como o cadastro aplica: o termo e, para cada competencia que ele lista, a previsao de
    origem apostilamento."""
    iid = c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) "
                    "VALUES (?, ?, 'apostilamento_reajuste', '2026-09-01', ?)", (cid, chave, json.dumps(dados))).lastrowid
    for comp, valor in competencias:
        c.execute("INSERT INTO reajuste_previsoes (contrato_id, data_base_mes, ciclo, competencia, valor_previsto_centavos, "
                  "origem, instrumento_id, criado_em) VALUES (?, ?, ?, ?, ?, 'apostilamento', ?, '2026-09-01 10:00:00')",
                  (cid, dados["data_base"], dados["ciclo"], comp, valor, iid))
    c.commit()


def test_reajustes_esperando_apostilamento_somam_o_medido_por_competencia_na_cota(cenario):
    c, ids = cenario
    p, k = ids["propria"], ids["consorcio"]
    _data_base(c, p, "2025-01")
    _reajuste(c, p, 31, "2026-02", "planilha_enviada", pedido=100_001)            # pedida
    _reajuste(c, p, 32, "2026-02", "planilha_gerada", pedido=50_000)              # complemento da mesma competencia
    _reajuste(c, p, 33, "2026-03", "boletim_recebido", pedido=200_000, aprovado=199_999)   # aprovada: o aprovado vale
    _reajuste(c, p, 34, "2026-04", "nota_emitida", pedido=300_003, aprovado=300_003)       # faturada sem apostilamento
    _reajuste(c, p, 35, "2026-05", "boletim_recebido", aprovado=400_000)          # apostilada: fora
    _apostilar(c, p, "ap-1", {"data_base": "2025-01", "ciclo": 2026,
                              "competencias": [{"competencia": "2026-05", "valor": "4.000,00"}]}, [("2026-05", 400_000)])
    _reajuste(c, p, 36, "2026-06", "recebida", pedido=500_000)                    # recebida: fora
    _reajuste(c, p, 37, "2026-07", "cancelada", pedido=1)                         # cancelada: fora
    _reajuste(c, p, 38, "2026-08", "prevista")                                    # so' prevista: fora
    _data_base(c, k, "2024-01")
    # consorcio a 50%: 100.001 + 100.001 no cheio = 200.002, na cota 100.001 (arredondamento unico; por competencia
    # seriam 50.001 + 50.001)
    _reajuste(c, k, 31, "2026-03", "planilha_enviada", pedido=100_001)
    _reajuste(c, k, 32, "2026-04", "boletim_recebido", pedido=100_001, aprovado=100_001)
    r = diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]
    assert [(o["contrato_id"], o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [
        (p, "Própria", 3, 100_001 + 50_000 + 199_999 + 300_003), (k, "Consórcio", 2, 100_001)]
    assert (r["competencias"], r["valor_centavos"]) == (5, 650_003 + 100_001)


def test_obra_com_tudo_apostilado_nao_aparece_nos_reajustes_esperando_apostilamento(cenario):
    c, ids = cenario
    p, k = ids["propria"], ids["consorcio"]
    _data_base(c, p, "2025-01")
    _reajuste(c, p, 31, "2026-02", "planilha_enviada", pedido=100_001)
    _reajuste(c, p, 32, "2026-03", "nota_emitida", pedido=200_000, aprovado=200_000)
    # percentual da MT-PAR com periodo: cobre as duas competencias
    _apostilar(c, p, "ap-1", {"data_base": "2025-01", "ciclo": 2026, "percentual": "6,76",
                              "periodo": {"de": "2026-01", "ate": "2026-12"}})
    _data_base(c, k, "2024-01")
    _reajuste(c, k, 31, "2026-03", "planilha_enviada", pedido=100_001)
    r = diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Consórcio", 1, 50_001)]
    assert (r["competencias"], r["valor_centavos"]) == (1, 50_001)


def test_termo_so_com_periodo_parcial_deixa_o_mes_de_fora_esperando_apostilamento(cenario):
    # issue #444: o `periodo` sozinho limita o termo (o cadastro recusa competencia fora dele); a faturada de 06/2026,
    # fora do periodo 01-03/2026 do ciclo 2026, espera; a de 02/2026, dentro, nao. Centavo impar no valor
    c, ids = cenario
    p = ids["propria"]
    _data_base(c, p, "2025-01")
    _reajuste(c, p, 31, "2026-02", "nota_emitida", pedido=100_001, aprovado=100_001)
    _reajuste(c, p, 32, "2026-06", "nota_emitida", pedido=200_003, aprovado=200_003)
    _apostilar(c, p, "ap-1", {"data_base": "2025-01", "ciclo": 2026, "periodo": {"de": "2026-01", "ate": "2026-03"}})
    r = diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Própria", 1, 200_003)]


@pytest.mark.parametrize("segundo,previsoes", [
    ({"periodo": {"de": "2026-04", "ate": "2026-05"}}, ()),
    ({"percentual": "6,80", "periodo": {"de": "2026-04", "ate": "2026-05"}}, ()),
    ({"competencias": [{"competencia": "2026-04", "valor": "1.000,00"}]}, [("2026-04", 100_000)]),
], ids=["so-periodo", "percentual", "lista"])
def test_dois_termos_parciais_no_mesmo_ciclo_cobrem_cada_um_os_seus_meses(cenario, segundo, previsoes):
    # revisor e gate Sol (rodada 1, PR #524): o 2o termo do ciclo (o mais novo) nao apaga o periodo do 1o so' com
    # periodo; 02/2026 (do 1o) e 04/2026 (do 2o) nao esperam, 06/2026 espera. Centavo impar no valor
    c, ids = cenario
    p = ids["propria"]
    _data_base(c, p, "2025-01")
    _reajuste(c, p, 31, "2026-02", "nota_emitida", pedido=100_001, aprovado=100_001)
    _reajuste(c, p, 32, "2026-04", "nota_emitida", pedido=100_000, aprovado=100_000)
    _reajuste(c, p, 33, "2026-06", "nota_emitida", pedido=200_003, aprovado=200_003)
    _apostilar(c, p, "ap-1", {"data_base": "2025-01", "ciclo": 2026, "periodo": {"de": "2026-01", "ate": "2026-03"}})
    _apostilar(c, p, "ap-2", {"data_base": "2025-01", "ciclo": 2026, **segundo}, previsoes)
    r = diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Própria", 1, 200_003)]


def test_reajustes_esperando_apostilamento_contam_obra_encerrada_e_nao_a_rescindida(cenario):
    # revisor (rodada 1, PR #431): o reajuste so' sai do bloco com o apostilamento (spec 2026-10-20 §2.2); fora fica
    # so' o rescindido, como no QDOP
    c, ids = cenario
    p, k = ids["propria"], ids["consorcio"]
    for cid, base in ((p, "2025-01"), (k, "2024-01")):
        _data_base(c, cid, base)
        _reajuste(c, cid, 31, "2026-03", "planilha_enviada", pedido=100_000)
    c.execute("UPDATE contratos SET estado='encerrado' WHERE id=?", (p,))
    c.execute("UPDATE contratos SET estado='rescindido' WHERE id=?", (k,))
    c.commit()
    r = diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]
    assert [o["obra"] for o in r["obras"]] == ["Própria"]
    c.execute("UPDATE contratos SET estado='suspenso' WHERE id=?", (k,)); c.commit()
    r = diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]
    assert sorted(o["obra"] for o in r["obras"]) == ["Consórcio", "Própria"]


def test_termo_que_fecha_o_ciclo_sem_dizer_os_meses_tira_a_obra_do_bloco(cenario):
    # revisor (rodada 1, PR #431): o apostilamento so' com percentual (sem periodo) e o aditivo de valor de reajuste da
    # SES (#390) fecham o ciclo inteiro em `reajuste.ciclos`; a competencia do ciclo fechado nao espera apostilamento
    c, ids = cenario
    p, k = ids["propria"], ids["consorcio"]
    _data_base(c, p, "2025-01")
    _reajuste(c, p, 31, "2026-03", "boletim_recebido", pedido=200_000, aprovado=200_000)
    _apostilar(c, p, "ap-g", {"data_base": "2025-01", "ciclo": 2026, "percentual": "5,00"})
    _data_base(c, k, "2024-01")
    _reajuste(c, k, 31, "2026-03", "nota_emitida", pedido=300_000, aprovado=300_000)
    _reajuste(c, k, 32, "2025-03", "nota_emitida", pedido=100_001, aprovado=100_001)     # ciclo 2025: nao fechado
    c.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, numero, "
              "chave_cadastro, natureza) VALUES (?, 'valor', 300000, 'assinado', '2026-04-10', '3º TA', 'ta-3', "
              "'reajuste')", (k,))
    c.commit()
    assert [(x["ciclo"], x["situacao"]) for x in reajuste.ciclos(c, p, HOJE)] == [(2026, "apostilado")]
    assert [(x["ciclo"], x["situacao"]) for x in reajuste.ciclos(c, k, HOJE)] == [(2026, "apostilado")]
    r = diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Consórcio", 1, 50_001)]


def test_medicao_sem_data_base_em_contrato_de_duas_bases_so_sai_com_as_duas_apostiladas(cenario):
    # revisor (rodada 1, PR #431): medicao sem `data_base_mes` em contrato de duas datas-base cai no grupo sem
    # data-base (`reajuste.competencias_por_ciclo`); ela so' deixa de esperar quando todas as bases apostilaram o mes
    c, ids = cenario
    p = ids["propria"]
    _data_base(c, p, "2025-01")
    _data_base(c, p, "2025-03")
    _reajuste(c, p, 31, "2026-04", "boletim_recebido", pedido=100_000, aprovado=100_000)
    _apostilar(c, p, "ap-a", {"data_base": "2025-01", "ciclo": 2026,
                              "competencias": [{"competencia": "2026-04", "valor": "1.000,00"}]}, [("2026-04", 100_000)])
    # as duas bases com previsao do mes: a medicao nao tem como escolher e vai para o grupo sem data-base
    c.execute("INSERT INTO reajuste_previsoes (contrato_id, data_base_mes, ciclo, competencia, valor_previsto_centavos, "
              "origem, criado_em) VALUES (?, '2025-03', 2026, '2026-04', 100000, 'manual', '2026-08-01 10:00:00')", (p,))
    c.commit()
    r = diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Própria", 1, 100_000)]
    _apostilar(c, p, "ap-b", {"data_base": "2025-03", "ciclo": 2026,
                              "competencias": [{"competencia": "2026-04", "valor": "1.000,00"}]}, [("2026-04", 100_000)])
    assert diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]["obras"] == []


def test_contrato_sem_data_base_tem_o_reajuste_medido_esperando_apostilamento(cenario):
    # revisor (rodada 2, PR #431): sem data-base nenhum termo cobre a competencia, entao ela espera; a pedida e a
    # aprovada nao estao em "Onde esta' o dinheiro". Consorcio a 50%: 100.001 + 200.001 = 300.002, na cota 150.001
    c, ids = cenario
    k = ids["consorcio"]
    _reajuste(c, k, 31, "2026-03", "planilha_enviada", pedido=100_001)
    _reajuste(c, k, 32, "2026-04", "boletim_recebido", pedido=200_000, aprovado=200_001)
    r = diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Consórcio", 2, 150_001)]


def test_complemento_ainda_nao_recebido_espera_mesmo_com_a_principal_recebida(cenario):
    # revisor (rodada 1, PR #431): a principal recebida nao esconde o complemento pedido da competencia sem apostilamento
    c, ids = cenario
    p = ids["propria"]
    _data_base(c, p, "2025-01")
    _reajuste(c, p, 31, "2026-03", "recebida", pedido=100_000, aprovado=100_000)
    _reajuste(c, p, 32, "2026-03", "planilha_enviada", pedido=50_001)
    r = diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Própria", 1, 50_001)]


def test_medicao_sem_base_em_mes_sem_reajuste_em_nenhuma_data_base_espera(cenario):
    # revisor (PR #431, pedido na rodada 2 da PR #438): datas-base 2025-01 e 2025-03, medicao de reajuste pedida de
    # 06/2025 sem previsao. Cai no grupo sem data-base; nenhuma base tem reajuste no mes (o 1o aniversario e' em 2026),
    # entao nenhum termo a cobre e ela espera, pelo criterio unico da aba (`reajuste.cobertura_das_competencias`)
    c, ids = cenario
    p = ids["propria"]
    _data_base(c, p, "2025-01")
    _data_base(c, p, "2025-03")
    _reajuste(c, p, 31, "2025-06", "planilha_enviada", pedido=100_001)
    [grupo] = reajuste.competencias_por_ciclo(c, p)
    assert (grupo["data_base_mes"], grupo["ciclo"], grupo["competencias"][0]["data_base_incerta"]) == (None, None, True)
    r = diretoria.painel(c, HOJE)["dinheiro"]["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Própria", 1, 100_001)]


def test_a_receber_total_por_obra_e_lista_na_cota(cenario):
    c, ids = cenario
    c.execute("UPDATE medicoes SET valor_protocolado_centavos=800001 WHERE contrato_id=? AND numero=14", (ids["propria"],))
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, 3, 'execucao', '2026-08', 'protocolada', 1000001)", (ids["consorcio"],))
    mid = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=3", (ids["consorcio"],)).lastrowid
    c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, '2026-09-01', 'manual')", (mid,))
    c.commit()
    r = diretoria.a_receber(c, HOJE)
    assert r["total_a_receber_liberado"] is False and r["total"] == {"quantidade": 3, "obras": 2, "valor_centavos": None}
    assert all(o["valor_centavos"] is None for o in r["por_obra"]) and all(i["valor_centavos"] is None for i in r["itens"])
    assert all(m["previsto_centavos"] is None for m in r["meses"])
    ids["liberar"]()
    r = diretoria.a_receber(c, HOJE)
    # centavo impar: 1.000.001 x 50% = 500.001 (arredondamento unico em `contratos.cota`); propria na cota cheia
    assert r["total"] == {"quantidade": 3, "obras": 2, "valor_centavos": 800_001 + 300_000 + 500_001}
    assert [(o["obra"], o["quantidade"], o["valor_centavos"]) for o in r["por_obra"]] == [
        ("Própria", 2, 1_100_001), ("Consórcio", 1, 500_001)]
    assert [(i["obra"], i["numero"], i["protocolada_em"], i["valor_centavos"]) for i in r["itens"]] == [
        ("Própria", 15, "2026-07-01", 300_000), ("Consórcio", 3, "2026-09-01", 500_001), ("Própria", 14, "2026-09-10", 800_001)]
    assert sum(i["valor_centavos"] for i in r["itens"]) == sum(o["valor_centavos"] for o in r["por_obra"])
    # por contratante: o mesmo total, agrupado pelo orgao do contrato, do maior para o menor
    assert sum(o["valor_centavos"] for o in r["por_orgao"]) == r["total"]["valor_centavos"]
    assert sum(o["quantidade"] for o in r["por_orgao"]) == 3
    assert [o["valor_centavos"] for o in r["por_orgao"]] == sorted((o["valor_centavos"] for o in r["por_orgao"]), reverse=True)
    assert {i["orgao_id"] for i in r["itens"]} == {o["orgao_id"] for o in r["por_orgao"]}
    assert {o["orgao"] for o in r["por_orgao"]} == {"SINFRA", "MTPAR"}
    # o dinheiro antes do protocolo e' o do painel da diretoria (medido sem nota, nota sem protocolo)
    d = diretoria.painel(c, HOJE)["dinheiro"]
    assert r["antes_do_protocolo"] == {"medido_esperando_nota": d["medido_esperando_nota"],
                                       "nota_esperando_protocolo": d["nota_esperando_protocolo"]}


def test_a_receber_previsto_pelo_vencimento_e_recebido_pelo_mes_do_recebimento(cenario):
    c, ids = cenario
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, recebida_em) "
              "VALUES (?, 20, 'execucao', '2026-07', 'recebida', 250001, '2026-09-15')", (ids["consorcio"],))
    c.commit()
    ids["liberar"]()
    r = diretoria.a_receber(c, HOJE)
    assert [m["competencia"] for m in r["meses"]] == ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09",
                                                      "2026-10", "2026-11", "2026-12"]
    por = {m["competencia"]: m for m in r["meses"]}
    # julho: a 15 (protocolo 01/07 + 10 dias da SINFRA) e a 2 do consorcio (01/06 + 30 dias do MTPAR, 50% de 400 mil + reajuste)
    assert por["2026-07"]["previsto_centavos"] == 300_000 + 200_000_000 + 5_000_000
    assert por["2026-09"]["previsto_centavos"] == 700_000                       # a 14: protocolo 10/09 + 10 dias
    assert (r["mes"]["competencia"], r["mes"]["atual"], r["mes"]["previsto_centavos"]) == ("2026-09", True, 700_000)
    assert r["mes"]["recebido_centavos"] == 125_001                              # 250.001 x 50%, arredondado uma vez
    assert por["2026-10"]["futuro"] is True and por["2026-10"]["recebido_centavos"] is None


def test_a_receber_recebido_aparece_antes_de_liberar_e_previsto_nao(cenario):
    c, _ = cenario
    r = diretoria.a_receber(c, HOJE)
    assert r["total_a_receber_liberado"] is False
    assert r["meses"][2]["recebido_centavos"] is not None and r["meses"][2]["previsto_centavos"] is None


def test_a_receber_nota_do_rm_entra_na_lista_e_no_total(cenario):
    c, ids = cenario
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao) "
                    "VALUES (1, 900, '000000900', '2026-06-01', 2500000, 'ativa')").lastrowid
    c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, status_lan) "
              "VALUES (1, 900, ?, 900, 2500000, 0, 0)", (nid,))
    mid = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=1", (ids["propria"],)).fetchone()[0]
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
              "VALUES (?, ?, 2500000, 'detectado', 't')", (mid, nid))
    c.commit()
    ids["liberar"]()
    r = diretoria.a_receber(c, HOJE)
    nota = [i for i in r["itens"] if i["tipo"] == "nota"]
    assert len(nota) == 1 and nota[0]["medicao_id"] is None and nota[0]["nota_numero"] == "900"
    assert nota[0]["valor_centavos"] == 2_500_000 and r["total"]["valor_centavos"] == 700_000 + 300_000 + 2_500_000


@pytest.mark.parametrize("titulos, falta", [
    ([(50_000, 55_100, 1), (5_000, 0, 0)], 5_000),      # issue #253: juros em A nao escondem B aberto
    ([(50_000, 60_000, 1), (5_000, 0, 0)], 5_000),      # ... nem juros acima do valor de B inteiro
    ([(50_000, 55_100, 1), (5_000, 3_000, 4)], 2_000),  # ... nem a falta de B com baixa parcial
    ([(50_000, 55_100, 1), (5_000, 5_000, 1)], None),   # todos pagos (um com juros): sai, como hoje
    ([(50_000, 50_000, 1), (5_000, 4_901, 1)], None),   # ate' R$ 1,00 a menos no total: sai, como hoje
])
def test_a_receber_conta_a_falta_da_nota_titulo_a_titulo(cenario, titulos, falta):
    """Issue #253: a nota em aberto do RM entra no a receber pelo que falta titulo a titulo (a conta da #35 e da
    #251): pagamento a mais num titulo nao compensa outro titulo aberto da mesma nota."""
    c, ids = cenario
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao) "
                    "VALUES (1, 930, '000000930', '2026-06-01', 60000, 'ativa')").lastrowid
    for i, (orig, baixado, st) in enumerate(titulos, 1):
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan) VALUES (1, ?, ?, 930, ?, ?, ?)", (9300 + i, nid, orig, baixado, st))
    mid = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=1", (ids["propria"],)).fetchone()[0]
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
              "VALUES (?, ?, 55000, 'detectado', 't')", (mid, nid))
    c.commit()
    ids["liberar"]()
    r = diretoria.a_receber(c, HOJE)
    nota = [i["valor_centavos"] for i in r["itens"] if i["tipo"] == "nota"]
    assert nota == ([] if falta is None else [falta])
    assert r["total"]["valor_centavos"] == 700_000 + 300_000 + (falta or 0)


def test_a_receber_recebida_sem_data_do_corte_fica_fora_do_previsto(cenario):
    c, ids = cenario        # medicao do legado protocolada em 05/09, fechada pelo corte (recebida, sem recebida_em)
    mid = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
                    "VALUES (?, 30, 'execucao', '2026-07', 'recebida', 5000000)", (ids["propria"],)).lastrowid
    c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, '2026-09-05', 'manual')", (mid,))
    c.commit(); ids["liberar"]()
    r = diretoria.a_receber(c, HOJE)
    assert r["mes"]["previsto_centavos"] == 700_000            # so' a 14; os 50.000,00 sem data nao entram


def test_a_receber_previsao_futura_nao_conta_medicao_ja_paga(cenario):
    c, ids = cenario
    ids["liberar"]()
    antes = {m["competencia"]: m["previsto_centavos"] for m in diretoria.a_receber(c, HOJE)["meses"]}
    mid = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, recebida_em) "
                    "VALUES (?, 31, 'execucao', '2026-08', 'recebida', 9000000, ?)", (ids["propria"], HOJE.isoformat())).lastrowid
    c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, ?, 'manual')", (mid, HOJE.isoformat()))
    c.commit()                       # protocolada e paga em 24/09; SINFRA (10 dias) venceria em 04/10
    por = {m["competencia"]: m for m in diretoria.a_receber(c, HOJE)["meses"]}
    assert all(por[k]["previsto_centavos"] == antes[k] for k in por if por[k]["futuro"])
    assert por["2026-09"]["recebido_centavos"] == 9_000_000


# --- issue #296: curva S da carteira (soma das obras ativas, na cota) e desvio em p.p. por obra no QDOP -----

def _repactuar_consorcio(c, k):
    """Consorcio: contratual (4 mi em 05/2026, 2 mi em 08/2026) e o 1º TA, que repactua para 3 mi e 1 mi."""
    from app import cronograma
    for numero, itens, data, chave, origem in (
            (1, [("2026-05", 400_000_000), ("2026-08", 200_000_000)], "2024-01-01", "contratual", "contratual"),
            (2, [("2026-05", 300_000_000), ("2026-08", 100_000_000)], "2025-06-01", "ta1", "aditivo")):
        cronograma.nova_versao(c, 1, k, itens, "manual", data_documento=data)
        vid = c.execute("SELECT id FROM cronograma_versoes WHERE contrato_id=? AND numero=?", (k, numero)).fetchone()[0]
        c.execute("INSERT INTO cronograma_versoes_cadastro (versao_id, contrato_id, chave, origem, data_documento, instrumento)"
                  " VALUES (?,?,?,?,?,NULL)", (vid, k, chave, origem, data))
        c.commit()


def test_curva_da_carteira_soma_as_obras_ativas_na_cota_com_as_duas_linhas(cenario):
    c, ids = cenario
    _repactuar_consorcio(c, ids["consorcio"])
    curva = diretoria.painel(c, HOJE)["curva_carteira"]
    assert [p["competencia"] for p in curva] == ["2025-10", "2025-11", "2025-12"] + [f"2026-{m:02d}" for m in range(1, 10)]
    por = {p["competencia"]: p for p in curva}
    # 05/2026: o consorcio entra com 50% (TA 3 mi, anterior 4 mi, medido 4 mi) e a propria com o medido de 1 mil
    assert por["2026-05"] == {"competencia": "2026-05", "previsto_centavos": 150_000_000,
                              "previsto_anterior_centavos": 200_000_000, "medido_centavos": 200_000_000 + 100_000}
    # 08/2026: a propria mede 1 mil (recebida) + 7 mil (protocolada); o consorcio so' preve
    assert por["2026-08"] == {"competencia": "2026-08", "previsto_centavos": 50_000_000,
                              "previsto_anterior_centavos": 100_000_000, "medido_centavos": 800_000}
    # 09/2026: a propria nao tem repactuacao e entra na linha anterior com o vigente; o espelho mede (#561): 10 mil da propria + 50% de 10 mil
    assert por["2026-09"] == {"competencia": "2026-09", "previsto_centavos": 2_000_000,
                              "previsto_anterior_centavos": 2_000_000, "medido_centavos": 1_500_000}
    # o reajuste nao e' medido de execucao
    c.execute("UPDATE medicoes SET tipo='reajuste' WHERE contrato_id=? AND competencia='2026-08'", (ids["propria"],))
    c.commit()
    assert {p["competencia"]: p for p in diretoria.painel(c, HOJE)["curva_carteira"]}["2026-08"]["medido_centavos"] == 0


def test_curva_da_carteira_deixa_de_fora_a_obra_que_nao_esta_ativa(cenario):
    c, ids = cenario
    _repactuar_consorcio(c, ids["consorcio"])
    c.execute("UPDATE contratos SET estado='encerrado' WHERE id=?", (ids["consorcio"],))
    c.commit()
    por = {p["competencia"]: p for p in diretoria.painel(c, HOJE)["curva_carteira"]}
    assert por["2026-05"] == {"competencia": "2026-05", "previsto_centavos": 0, "previsto_anterior_centavos": 0,
                              "medido_centavos": 100_000}


def test_desvio_por_obra_no_qdop_pela_linha_anterior_ate_a_ultima_competencia_fechada(cenario):
    c, ids = cenario
    obras = {o["contrato_id"]: o for o in diretoria.painel(c, HOJE)["obras"]}
    assert (obras[ids["consorcio"]]["desvio_pp"], obras[ids["consorcio"]]["desvio_base"]) == (None, None)  # sem cronograma
    _repactuar_consorcio(c, ids["consorcio"])
    obras = {o["contrato_id"]: o for o in diretoria.painel(c, HOJE)["obras"]}
    # consorcio: medido 4 mi contra o anterior 6 mi ate 08/2026, sobre o vigente de 12 mi: -16,67 -> -16,7
    assert (obras[ids["consorcio"]]["desvio_pp"], obras[ids["consorcio"]]["desvio_base"]) == (-16.7, "anterior")
    # propria: sem repactuacao, pelo vigente; o previsto de 09/2026 (mes corrente) ainda nao conta;
    # medido de execucao ate' 08/2026 = 29 mil sobre 1 mi = 2,9 (o espelho de 09/2026 e' do mes corrente)
    assert (obras[ids["propria"]]["desvio_pp"], obras[ids["propria"]]["desvio_base"]) == (2.9, "vigente")
    # o medido do mes corrente tambem fica fora: uma execucao protocolada de 09/2026 nao mexe no desvio de hoje
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, 40, 'execucao', '2026-09', 'protocolada', 5000000)", (ids["propria"],))
    c.commit()
    assert {o["contrato_id"]: o for o in diretoria.painel(c, HOJE)["obras"]}[ids["propria"]]["desvio_pp"] == 2.9
    c.execute("DELETE FROM medicoes WHERE contrato_id=? AND numero=40", (ids["propria"],))
    c.commit()
    # em outubro, 09/2026 fecha: o previsto de 20 mil e o espelho de 10 mil entram (39 - 20 mil = 1,9)
    assert {o["contrato_id"]: o for o in diretoria.painel(c, D(2026, 10, 1))["obras"]}[ids["propria"]]["desvio_pp"] == 1.9


def _reajuste_no_consorcio(c, ids, valor=240_000_001):
    """#262: aditivo de reajuste (SES) de 2.400.000,01 no consorcio: entra no vigente, fica fora da base de execucao."""
    c.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza) "
              "VALUES (?, 'valor', ?, 'assinado', '2026-03-01', 'reajuste')", (ids["consorcio"], valor))
    c.commit()


def test_tabela_de_obras_usa_o_vigente_de_execucao_e_o_qdop_nao_muda(cenario):
    """#262 (gate Sol S1): na tabela de obras da Diretoria, PI+VA, VA, saldo e percentuais a precos iniciais; o
    reajuste so' na coluna propria. O QDOP exportado fica como esta' (#352, QDOP com saldo a precos iniciais)."""
    c, ids = cenario
    _reajuste_no_consorcio(c, ids)
    o = {x["contrato_id"]: x for x in diretoria.painel(c, HOJE)["obras"]}[ids["consorcio"]]
    # 50% de 12.000.000,00 (sem o reajuste); faturado = 50% de 4.000.000,00; reajuste faturado = 50% de 100.000,00
    assert (o["pi"], o["va"], o["pi_va"]) == (500_000_000, 100_000_000, 600_000_000)
    assert (o["faturados"], o["reajuste_recebido"], o["saldo"]) == (200_000_000, 5_000_000, 399_500_000)
    assert (o["pct_recebido"], o["pct_a_receber"]) == (200_500_000 / 600_000_000, 399_500_000 / 600_000_000)
    q = {x["contrato_id"]: x for x in qdop.linhas(c, HOJE)}[ids["consorcio"]]
    assert q["pi_va"] == 720_000_001                         # 50% de 14.400.000,01, meio para cima


def test_desvio_divide_pelo_vigente_de_execucao(cenario):
    """#262 (gate Sol S3): o desvio compara medido e previsto a precos iniciais; o denominador tambem."""
    c, ids = cenario
    _repactuar_consorcio(c, ids["consorcio"])
    _reajuste_no_consorcio(c, ids)
    obras = {o["contrato_id"]: o for o in diretoria.painel(c, HOJE)["obras"]}
    # -2 mi sobre 12 mi (nao sobre 14,4 mi): -16,7, como sem o reajuste
    assert obras[ids["consorcio"]]["desvio_pp"] == -16.7


def _medir(c, contrato, numero, estado, valor, tipo="execucao", comp="2026-08"):
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, ?, ?, ?, ?, ?)", (contrato, numero, tipo, comp, estado, valor))


def _saldos(c):
    p = diretoria.painel(c, HOJE)
    tabela = {o["contrato_id"]: o["saldo"] for o in p["obras"]}
    carteira = {o["orgao"]: o["saldo_centavos"] for o in p["carteira"]["por_orgao"]}
    return tabela, carteira, {o["contrato_id"]: o for o in p["obras"]}


def test_tabela_de_obras_mede_como_a_carteira(cenario):
    """#262 (revisao, rodada 3): o saldo da tabela de obras desconta o mesmo medido da carteira, logo acima na tela
    (`paineis.mede_execucao`): projeto recebido nao abate o saldo; execucao com nota emitida abate (#561)."""
    c, ids = cenario
    _medir(c, ids["propria"], 60, "recebida", 50_000_000, tipo="projeto")
    _medir(c, ids["propria"], 61, "nota_emitida", 3_000_001)
    c.commit()
    tabela, carteira, obras = _saldos(c)
    assert tabela[ids["propria"]] == carteira["SINFRA"] == 93_099_999      # 1.000.000,00 - 39.000,00 - 30.000,01
    assert tabela[ids["consorcio"]] == carteira["MTPAR"] == 399_500_000
    # os percentuais na mesma base: medido de execucao sobre o vigente de execucao
    assert obras[ids["propria"]]["pct_recebido"] == 6_900_001 / 100_000_000
    assert obras[ids["propria"]]["pct_a_receber"] == 93_099_999 / 100_000_000
    assert obras[ids["propria"]]["faturados"] == 2_900_000 + 50_000_000 + 3_000_001   # a coluna do QDOP fica


def test_tabela_e_carteira_leem_as_mesmas_medicoes(cenario, monkeypatch):
    """#262 (gate Sol, rodada 3): a tabela de obras tira o medido da mesma leitura de medicoes da carteira. Uma
    medicao que passa de planilha gerada a protocolada no meio do painel nao deixa os dois saldos diferentes."""
    c, ids = cenario
    _medir(c, ids["propria"], 60, "planilha_gerada", 5_000_000)
    c.commit()
    original = avisos.listar

    def protocola_no_meio(conn, *a, **k):         # roda depois da leitura das medicoes do painel
        conn.execute("UPDATE medicoes SET estado='protocolada' WHERE contrato_id=? AND numero=60", (ids["propria"],))
        conn.commit()
        return original(conn, *a, **k)
    monkeypatch.setattr(avisos, "listar", protocola_no_meio)
    tabela, carteira, _ = _saldos(c)
    assert tabela[ids["propria"]] == carteira["SINFRA"] == 96_100_000


def test_medido_da_tabela_e_da_carteira_vale_o_atestado(cenario):
    """#262 (gate Sol, rodada 3): com atestado, o medido de execucao e' o atestado, nao o protocolado."""
    c, ids = cenario
    _medir(c, ids["propria"], 60, "protocolada", 10_000_000)
    c.execute("UPDATE medicoes SET valor_atestado_centavos=3000001 WHERE contrato_id=? AND numero=60", (ids["propria"],))
    c.commit()
    tabela, carteira, _ = _saldos(c)
    assert tabela[ids["propria"]] == carteira["SINFRA"] == 96_100_000 - 3_000_001


def test_carteira_usa_o_percentual_do_vigente_que_a_tabela_reaproveita(cenario, monkeypatch):
    """#262 (gate Sol, rodada 3): a carteira aplica a cota com o percentual do mesmo `contratos.vigente` que a tabela
    reaproveita, nao com o da linha lida antes. O percentual do consorcio muda de 50% para 40% logo depois da lista
    de contratos da carteira: as duas mostram 40% de (12.000.000,00 - 4.000.000,00) = 3.200.000,00."""
    c, ids = cenario
    original = diretoria._ativos

    def muda_depois_da_lista(conn):
        linhas = original(conn)
        if sys._getframe(1).f_code.co_name in ("_carteira", "<genexpr>") and not getattr(muda_depois_da_lista, "feito", False):
            conn.execute("UPDATE contratos SET percentual_direito_bp=4000 WHERE id=?", (ids["consorcio"],))
            conn.commit()
            muda_depois_da_lista.feito = True
        return linhas
    monkeypatch.setattr(diretoria, "_ativos", muda_depois_da_lista)
    p = diretoria.painel(c, HOJE)
    assert muda_depois_da_lista.feito
    o = {x["contrato_id"]: x for x in p["obras"]}[ids["consorcio"]]
    por = {x["orgao"]: x for x in p["carteira"]["por_orgao"]}["MTPAR"]
    assert o["saldo"] == por["saldo_centavos"] == 319_600_000
    assert o["pi_va"] == por["vigente_centavos"] == 480_000_000


def test_aditivo_entre_a_carteira_e_as_obras_nao_muda_a_base(cenario, monkeypatch):
    """#262 (gate Sol, rodada 3): carteira, tabela e desvio usam o mesmo vigente do painel. Um aditivo de execucao de
    2.400.000,00 que chega depois da carteira nao entra na tabela nem no denominador do desvio (-2 mi sobre 12 mi)."""
    c, ids = cenario
    _repactuar_consorcio(c, ids["consorcio"])
    original = diretoria._curva_carteira

    def aditivo_no_meio(conn, *a, **k):              # roda depois da carteira e antes das obras
        conn.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza) "
                     "VALUES (?, 'valor', 240000000, 'assinado', '2026-03-01', 'execucao')", (ids["consorcio"],))
        conn.commit()
        return original(conn, *a, **k)
    monkeypatch.setattr(diretoria, "_curva_carteira", aditivo_no_meio)
    p = diretoria.painel(c, HOJE)
    o = {x["contrato_id"]: x for x in p["obras"]}[ids["consorcio"]]
    por = {x["orgao"]: x for x in p["carteira"]["por_orgao"]}["MTPAR"]
    assert o["pi_va"] == por["vigente_centavos"] == 600_000_000
    assert o["saldo"] == por["saldo_centavos"] == 399_500_000
    assert o["desvio_pp"] == -16.7                       # com o aditivo lido de novo daria -2/14,4 = -13,9


def test_painel_le_uma_fotografia_do_banco(cenario, monkeypatch):
    """#262 (revisor, rodada 3): o painel inteiro le numa transacao de leitura so'. Um `cadastro aplicar` em outra
    conexao muda o consorcio de 50% para 40% no meio da montagem: a escrita grava sem esperar (WAL, a leitura nao
    segura a escrita) e o painel continua todo em 50% (PI, VA, PI+VA e direito da mesma linha batem)."""
    c, ids = cenario
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    original = diretoria._curva_carteira

    def cadastro_no_meio(conn, *a, **k):             # depois da carteira, antes das obras
        outra = db.get_conn()
        try:
            outra.execute("UPDATE contratos SET percentual_direito_bp=4000 WHERE id=?", (ids["consorcio"],))
            outra.commit()
        finally:
            outra.close()
        return original(conn, *a, **k)
    monkeypatch.setattr(diretoria, "_curva_carteira", cadastro_no_meio)
    p = diretoria.painel(c, HOJE)
    o = {x["contrato_id"]: x for x in p["obras"]}[ids["consorcio"]]
    assert o["va"] == o["pi_va"] - o["pi"] == 100_000_000
    assert (o["direito"], o["pi"], o["pi_va"]) == (0.5, 500_000_000, 600_000_000)
    assert not c.in_transaction                        # a transacao de leitura fechou
    monkeypatch.setattr(diretoria, "_curva_carteira", original)
    o = {x["contrato_id"]: x for x in diretoria.painel(c, HOJE)["obras"]}[ids["consorcio"]]
    assert (o["direito"], o["pi_va"]) == (0.4, 480_000_000)      # a escrita gravou; o painel seguinte a ve


def test_painel_dentro_de_transacao_aberta_nao_a_fecha(cenario):
    """#262: com transacao ja' aberta por quem chamou, o painel le nela e a deixa aberta."""
    c, ids = cenario
    c.execute("BEGIN")
    assert diretoria.painel(c, HOJE)["obras"]
    assert c.in_transaction
    c.rollback()


def test_saldo_da_tabela_aplica_a_cota_uma_vez(cenario):
    """#262 (revisao, rodada 3): saldo = cota(vigente de execucao - medido), arredondamento unico, como na carteira.
    Consorcio a 50%: 12.000.000,00 - 4.010.000,01 = 7.989.999,99 -> 3.995.000,00 (meio para cima); duas cotas
    arredondadas dariam 6.000.000,00 - 2.005.000,01 = 3.994.999,99."""
    c, ids = cenario
    _medir(c, ids["consorcio"], 60, "protocolada", 1)
    c.commit()
    tabela, carteira, _ = _saldos(c)
    assert tabela[ids["consorcio"]] == carteira["MTPAR"] == 399_500_000


def test_ritmo_aplica_a_cota_uma_vez_por_contrato(cenario):
    """#262 (revisao, rodada 3): o ritmo soma o cheio da janela e aplica a cota uma vez por contrato, como o medido.
    Doze execucoes de 1 centavo no consorcio a 50%: cota(4.010.000,12) = 2.005.000,06 (nao 2.005.000,12, que viria
    de doze cotas de 0,5 centavo arredondadas para cima). 203.000.006 / 6 = 33.833.334,33 -> 33.833.334."""
    c, ids = cenario
    for i in range(12):
        _medir(c, ids["consorcio"], 60 + i, "protocolada", 1)
    c.commit()
    assert diretoria.painel(c, HOJE)["carteira"]["ritmo_mensal_centavos"] == 33_833_334


def test_faturado_e_recebido_reais_saem_do_rm_por_mes_na_cota(cenario):
    """06/11/2026: a serie mensal da diretoria vem das notas e das baixas do RM, nao das medicoes (o cadastro de medicoes
    pode estar atrasado). Nota da coligada do consorcio entra na cota (50%); a NFS-e da Lotufo em obra de consorcio,
    a cancelada e a de fora dos contratos, nao."""
    c, ids = cenario
    def nota(idmov, emissao, valor, situacao="ativa", coligada=1, medicao=None):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao) "
                        "VALUES (?, ?, ?, ?, ?, ?)", (coligada, idmov, str(idmov), emissao, valor, situacao)).lastrowid
        if medicao:
            c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                      "VALUES (?, ?, ?, 'detectado', 't')", (medicao, nid, valor))
        return nid
    def baixa(nid, idlan, original, baixado, status, data):
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan, data_baixa) VALUES (1, ?, ?, ?, ?, ?, ?, ?)", (idlan, nid, idlan, original, baixado, status, data))
    m_propria = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=1", (ids["propria"],)).fetchone()[0]
    a = nota(901, "2026-08-10", 1_000_001, medicao=m_propria)
    b = nota(902, "2025-08-20", 400_000, medicao=m_propria)              # mesmo mes do ano anterior
    nota(903, "2026-08-15", 9_999_999, situacao="cancelada", medicao=m_propria)
    nota(904, "2026-08-15", 7_777_777, coligada=99)                      # fora dos contratos: sem medicao e sem centro
    baixa(a, 9011, 900_000, 900_000, 1, "2026-09-05")                    # liquido pago em setembro
    baixa(a, 9012, 50_000, 0, 0, None)                                   # titulo aberto: nao e' recebido
    baixa(b, 9021, 380_000, 380_000, 1, "2025-09-10")
    baixa(b, 9022, 10_000, 10_000, 2, "2025-09-11")                      # titulo cancelado: fora
    # o consorcio tem coligada propria no RM: a nota dela entra pela metade; a da Lotufo na mesma obra fica fora
    c.execute("UPDATE entidades SET coligada_rm=12 WHERE chave='cons'")
    m_cons = c.execute("SELECT id FROM medicoes WHERE contrato_id=? ORDER BY id LIMIT 1", (ids["consorcio"],)).fetchone()[0]
    k = nota(905, "2026-08-25", 1_000_001, coligada=12, medicao=m_cons)
    baixa(k, 9051, 1_000_001, 1_000_001, 1, "2026-09-20")
    nota(906, "2026-08-26", 3_333_333, coligada=1, medicao=m_cons)
    c.commit()
    faturado, recebido = diretoria.rm_por_mes(c)
    cota_cons = 500_001                                                  # 1.000.001 x 50%, arredondamento unico
    assert faturado == {"2026-08": 1_000_001 + cota_cons, "2025-08": 400_000}
    assert recebido == {"2026-09": 900_000 + cota_cons, "2025-09": 380_000}
    # A receber: o recebido real do mes (setembro, o corrente do cenario) e o do ano
    r = diretoria.a_receber(c, HOJE)
    assert r["mes"]["recebido_real_centavos"] == 900_000 + cota_cons
    assert r["recebido_ano_centavos"] == 900_000 + cota_cons
    assert [m["recebido_real_centavos"] for m in r["meses"] if m["futuro"]] == [None, None, None]
    # Carteira: 12 meses fechados (ate' agosto), cada um com o mesmo mes do ano anterior, e o ano ate' o ultimo fechado
    f = diretoria.painel(c, HOJE)["faturado_rm"]
    assert [s["competencia"] for s in f["serie"]][0] == "2025-09" and f["serie"][-1] == {
        "competencia": "2026-08", "faturado_centavos": 1_000_001 + cota_cons, "ano_anterior_centavos": 400_000}
    assert len(f["serie"]) == 12 and f["ate"] == "2026-08"
    assert (f["ano_centavos"], f["ano_anterior_centavos"]) == (1_000_001 + cota_cons, 400_000)


def test_nota_do_rm_sem_medicao_lancada_entra_no_medido_da_diretoria(cenario):
    """06/11/2026: o que o RM mostra e o sistema ainda nao tem (`complemento_rm`) conta como medido na Carteira. A
    competencia da nota solta e' o mes anterior ao da emissao; so' entra o que passa do que ja' esta' lancado na
    competencia; antes de `COMPETENCIA_NOTA_VALE` nada entra; nota ligada a medicao ativa nao entra."""
    c, ids = cenario
    antes = diretoria.painel(c, HOJE)
    assert diretoria.complemento_rm(c) == {}
    c.execute("UPDATE contratos SET centro_custo_rm='9.001.001' WHERE id=?", (ids["propria"],))
    c.execute("UPDATE entidades SET coligada_rm=12 WHERE chave='cons'")
    def nota(idmov, emissao, valor, coligada=1, centro="9.001.001", medicao=None):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, centro_custo) "
                        "VALUES (?, ?, ?, ?, ?, 'ativa', ?)", (coligada, idmov, str(idmov), emissao, valor, centro)).lastrowid
        if medicao:
            c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                      "VALUES (?, ?, ?, 'detectado', 't')", (medicao, nid, valor))
    nota(801, "2026-08-10", 1_000_001)                    # competencia 07/2026: lancado 100.000 -> faltam 900.001
    nota(802, "2026-07-05", 350_000)                      # competencia 06/2026: lancado 400.000 cobre -> nada
    nota(803, "2026-06-10", 5_000_000)                    # competencia 05/2026: antes do corte -> nada
    m13 = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=13", (ids["propria"],)).fetchone()[0]
    nota(804, "2026-09-20", 1_000_000, medicao=m13)       # ligada a medicao ativa -> nada
    nota(805, "2026-08-15", 1_000_001, coligada=12, centro=None)   # consorcio (50%), competencia 07/2026 sem medicao
    c.commit()
    compl = diretoria.complemento_rm(c)
    assert compl == {ids["propria"]: {"2026-07": 900_001}, ids["consorcio"]: {"2026-07": 1_000_001}}
    depois = diretoria.painel(c, HOJE)
    cota = 900_001 + 500_001                              # 1.000.001 x 50% = 500.001 (arredondamento unico)
    serie = lambda p: {s["competencia"]: s["medido_centavos"] for s in p["mes_ano"]["serie"]}
    assert serie(depois)["2026-07"] - serie(antes)["2026-07"] == cota
    assert serie(depois)["2026-06"] == serie(antes)["2026-06"] and serie(depois)["2026-08"] == serie(antes)["2026-08"]
    assert depois["mes_ano"]["acumulado_ano_centavos"] - antes["mes_ano"]["acumulado_ano_centavos"] == cota
    # o saldo a executar cai o mesmo tanto (no consorcio, a cota e' aplicada uma vez sobre o saldo cheio: o meio centavo
    # do 1.000.001 cai do outro lado); a curva da carteira ganha o medido de 07/2026
    assert antes["carteira"]["saldo_centavos"] - depois["carteira"]["saldo_centavos"] == 900_001 + 500_000
    curva = lambda p: {s["competencia"]: s["medido_centavos"] for s in p["curva_carteira"]}
    assert curva(depois)["2026-07"] - curva(antes)["2026-07"] == cota
    # na tabela de obras (QDOP na tela), a nota sem medicao e' faturado e baixa o saldo da obra
    obra = lambda p, k: next(o for o in p["obras"] if o["contrato_id"] == ids[k])
    assert obra(depois, "propria")["faturados"] - obra(antes, "propria")["faturados"] == 900_001
    assert obra(antes, "propria")["saldo"] - obra(depois, "propria")["saldo"] == 900_001
    assert obra(depois, "consorcio")["faturados"] - obra(antes, "consorcio")["faturados"] == 500_001
    # a nota do RM nao diz se e' execucao ou reajuste: o complemento de execucao para no que falta executar da obra,
    # e o saldo nunca fica negativo por causa dele; a coluna "faturados" leva a nota inteira
    c.execute("UPDATE contratos SET valor_original_centavos=4400000 WHERE id=?", (ids["propria"],))
    c.commit()
    apertado = diretoria.painel(c, HOJE)
    assert obra(apertado, "propria")["saldo"] == 0
    assert obra(apertado, "propria")["faturados"] == obra(depois, "propria")["faturados"]
    c.execute("UPDATE contratos SET valor_original_centavos=100000000 WHERE id=?", (ids["propria"],))
    c.commit()
    # lancada a medicao da competencia, o complemento dela some
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, 40, 'execucao', '2026-07', 'protocolada', 900001)", (ids["propria"],))
    c.commit()
    assert ids["propria"] not in diretoria.complemento_rm(c)
