"""Tela da diretoria (bloco 8; spec §10.5): na cota, prazo do orgao, faixas, mes e ano, proximos, carteira."""
import datetime
import json
import pathlib

import pytest

from app import auth, avisos, cadastro_aplicar, db, diretoria, medicoes, qdop
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
                                   "dados": {}}]}
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
        avisos.aviso("pagamento_atrasado", "acao", "Própria: 15ª Medição protocolada há 85 dias", ids["propria"], "Própria",
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
    a = lambda nivel: avisos.aviso("pagamento_atrasado", nivel, "Própria: aviso", ids["propria"], "Própria", dias=5)
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
    # proprio: 1.000.000,00 - 39.000,00 medidos; consorcio: 50% de (12.000.000,00 - 4.010.000,00)
    assert k["saldo_centavos"] == 96_100_000 + 399_500_000
    assert "terminando" not in k
    assert k["ritmo_mensal_centavos"] == 33_833_333             # 203.000.000 / 6, meio para cima


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
    assert (por["SINFRA - X"]["vigente_centavos"], por["SINFRA - X"]["medido_centavos"], por["SINFRA - X"]["obras"]) == (100_000_000, 3_900_000, 1)
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
