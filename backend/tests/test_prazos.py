"""Prazo do contrato (spec §7.3 e §7.4): execucao, vigencia, folga, paralisacao, endosso, encerramento."""
import datetime
import json

import pytest

from app import auth, db, prazos

D = datetime.date


@pytest.fixture
def cenario(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "admin")
    for chave, auto in (("sinfra-x", True), ("mtpar", False)):
        c.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES (?, ?, ?, ?)",
                  (chave, chave.upper(), "sinfra" if chave == "sinfra-x" else "mtpar",
                   json.dumps({"vigencia_automatica": auto, "folga_vigencia_dias": 90})))
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos, orgao_id, "
              "execucao_fim, vigencia_fim) VALUES ('SINFRA', 'IC 1/2026', 'Obra A', 'obra', 100, "
              "(SELECT id FROM orgaos WHERE chave='sinfra-x'), '2026-10-20', '2027-01-20')")
    cid = c.execute("SELECT MAX(id) FROM contratos").fetchone()[0]
    c.commit()

    def aditivo(data, nova_exe, nova_vig, forma="termo_aditivo", numero="001/2026", chave="ta-1"):
        c.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, nova_execucao_fim, nova_vigencia_fim, "
                  "status, data_assinatura, numero, forma, chave_cadastro) VALUES (?, 'prazo', 0, ?, ?, 'assinado', ?, ?, ?, ?)",
                  (cid, nova_exe, nova_vig, data, numero, forma, chave))
        c.commit()

    def instrumento(tipo, data, dados=None, chave=None):
        c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) VALUES (?, ?, ?, ?, ?)",
                  (cid, chave or f"{tipo}-{data}", tipo, data, json.dumps(dados or {})))
        c.commit()

    def pleito(tipo, enviado_em, oficio="CT-310-LT-2026"):
        c.execute("INSERT INTO pleitos (contrato_id, tipo, origem, numero_oficio, situacao, enviado_em) "
                  "VALUES (?, ?, 'cadastro', ?, 'enviado', ?)", (cid, tipo, oficio, enviado_em))
        c.commit()

    yield c, {"contrato": cid, "aditivo": aditivo, "instrumento": instrumento, "pleito": pleito}
    c.close()


def _por_tipo(c, hoje):
    return {a["tipo"]: a for a in prazos.avisos(c, hoje)}


def test_execucao_60_30_e_vencida_sem_pedido_vai_para_a_diretoria(cenario):
    c, _ = cenario
    assert _por_tipo(c, D(2026, 9, 1))["execucao_vencendo"]["nivel"] == "atencao"
    assert _por_tipo(c, D(2026, 10, 1))["execucao_vencendo"]["nivel"] == "critico"
    a = _por_tipo(c, D(2026, 10, 25))["instrumento_pendente"]
    assert (a["nivel"], a["publico"]) == ("critico", ["operacao", "diretoria"]) and "sem pedido" in a["mensagem"]


def test_contagem_de_um_dia_sai_no_singular(cenario):
    """Visto no Inicio sobre o volume real: "execução termina em 1 dias"."""
    c, _ = cenario
    assert _por_tipo(c, D(2026, 10, 19))["execucao_vencendo"]["mensagem"] == "execução termina em 1 dia (20/10/2026)"
    assert _por_tipo(c, D(2026, 10, 18))["execucao_vencendo"]["mensagem"] == "execução termina em 2 dias (20/10/2026)"
    assert _por_tipo(c, D(2026, 10, 21))["instrumento_pendente"]["mensagem"] == \
        "execução vencida há 1 dia, sem pedido de prorrogação"


def test_pedido_enviado_troca_o_aviso_e_instrumento_posterior_fecha(cenario):
    c, ids = cenario
    ids["pleito"]("prazo", "2026-09-05")
    a = _por_tipo(c, D(2026, 9, 10))
    assert "execucao_vencendo" not in a and a["instrumento_pendente"]["nivel"] == "atencao"
    assert "pedida em 05/09/2026" in a["instrumento_pendente"]["mensagem"]
    ids["aditivo"]("2026-09-20", "2027-01-20", "2027-04-20")
    assert not {"execucao_vencendo", "instrumento_pendente"} & set(_por_tipo(c, D(2026, 9, 25)))


def test_resumo_para_a_lista_de_obras(cenario):
    c, ids = cenario                  # A9: dias ate' o fim e o pedido em curso, que o instrumento fecha
    r = prazos.resumo(c, ids["contrato"], D(2026, 9, 10))
    assert (r["dias_execucao"], r["dias_vigencia"], r["vigencia_automatica"], r["pedido_prorrogacao"]) == (40, 132, True, None)
    ids["pleito"]("prazo", "2026-09-05")
    assert prazos.resumo(c, ids["contrato"], D(2026, 9, 10))["pedido_prorrogacao"] == {
        "enviado_em": "2026-09-05", "numero_oficio": "CT-310-LT-2026", "dias": 5}
    ids["aditivo"]("2026-09-20", "2027-01-20", "2027-04-20")
    assert prazos.resumo(c, ids["contrato"], D(2026, 9, 25))["pedido_prorrogacao"] is None


def test_paralisacao_aberta_suspende_o_aviso_e_avisa_a_diretoria(cenario):
    c, ids = cenario
    ids["instrumento"]("paralisacao", "2026-02-01")
    a = _por_tipo(c, D(2026, 10, 1))
    assert "execucao_vencendo" not in a and a["obra_paralisada"]["publico"] == ["diretoria"]
    assert (a["obra_paralisada"]["data"], a["obra_paralisada"]["sentido"]) == ("2026-02-01", "desde")
    assert prazos.resumo(c, ids["contrato"], D(2026, 10, 1))["paralisada_desde"] == "2026-02-01"
    ids["instrumento"]("reinicio", "2026-05-05")
    assert prazos.resumo(c, ids["contrato"], D(2026, 10, 1))["paralisada_desde"] is None
    a = _por_tipo(c, D(2026, 10, 1))
    assert "obra_paralisada" not in a and "execucao_vencendo" in a


def test_folga_quebrada_pelo_contrato_e_pelo_orgao(cenario):
    c, ids = cenario
    c.execute("UPDATE contratos SET execucao_fim='2026-12-01', vigencia_fim='2027-01-15'"); c.commit()
    a = _por_tipo(c, D(2026, 9, 1))["folga_quebrada"]
    assert a["nivel"] == "acao" and "folga de 45 dias, o órgão pede 90" in a["mensagem"]
    c.execute("UPDATE contratos SET folga_vigencia_dias=30"); c.commit()
    assert "folga_quebrada" not in _por_tipo(c, D(2026, 9, 1))


def test_vigencia_so_sem_prorrogacao_automatica(cenario):
    c, _ = cenario
    assert "vigencia_vencendo" not in _por_tipo(c, D(2026, 12, 1))
    c.execute("UPDATE contratos SET orgao_id=(SELECT id FROM orgaos WHERE chave='mtpar')"); c.commit()
    assert _por_tipo(c, D(2026, 12, 1))["vigencia_vencendo"]["dias"] == 50


def test_endosso_ate_5_dias_atencao_depois_acao_e_endosso_fecha(cenario):
    c, ids = cenario
    ids["aditivo"]("2026-09-20", "2027-01-20", "2027-04-20")
    a = _por_tipo(c, D(2026, 9, 23))["endosso_garantia"]
    assert a["nivel"] == "atencao" and "vence em 2 dias" in a["mensagem"]
    a = _por_tipo(c, D(2026, 9, 28))["endosso_garantia"]
    assert a["nivel"] == "acao" and "atrasado 3 dias" in a["mensagem"]
    ids["instrumento"]("endosso_garantia", "2026-09-19", {"referente": "ta-1"})
    assert "endosso_garantia" not in _por_tipo(c, D(2026, 9, 28))


def test_endosso_nao_cobra_instrumento_antigo(cenario):
    c, ids = cenario
    ids["aditivo"]("2026-06-01", "2027-01-20", "2027-04-20")
    assert "endosso_garantia" not in _por_tipo(c, D(2026, 9, 1))


def test_retroativo_sinalizado(cenario):
    c, ids = cenario
    c.execute("UPDATE contratos SET execucao_fim='2026-02-28'"); c.commit()
    ids["aditivo"]("2026-03-10", "2026-08-31", None)
    assert prazos.situacao(c, ids["contrato"], D(2026, 3, 15))["instrumentos"][0]["retroativo"] is True


def test_em_encerramento_so_conclusao_nao_comunicada(cenario):
    c, ids = cenario
    c.execute("UPDATE contratos SET encerramento_iniciado_em='2026-09-01'"); c.commit()
    a = prazos.avisos(c, D(2026, 10, 15))
    assert [(x["tipo"], x["nivel"], x["dias"]) for x in a] == [("conclusao_nao_comunicada", "acao", 44)]
    ids["pleito"]("conclusao", "2026-10-16", "CT-400-LT-2026")
    assert prazos.avisos(c, D(2026, 10, 20)) == []


def test_historico_texto_ordinal_por_forma(cenario):
    c, ids = cenario
    ids["aditivo"]("2025-03-10", "2025-10-20", "2026-01-18", numero="001/2025", chave="ta-1")
    ids["aditivo"]("2025-09-01", "2026-10-20", None, forma="apostilamento", numero="002/2025", chave="ap-1")
    texto = prazos.historico_texto(c, ids["contrato"])
    assert ("O 1º termo aditivo n.º 001/2025 foi assinado em 10/03/2025, com término da execução em 20/10/2025 "
            "e da vigência em 18/01/2026.") in texto
    assert "O 1º termo de apostilamento n.º 002/2025 foi assinado em 01/09/2025" in texto


def test_ordinal_do_historico_pelo_numero_pelo_campo_e_pela_contagem(cenario):
    """Issue #261: o ordinal sai do numero do termo (sufixo /14), depois do campo `ordinal` do cadastro e so' na
    falta dos dois da contagem dos instrumentos carregados."""
    c, ids = cenario
    ids["aditivo"]("2025-01-10", "2025-12-31", None, numero="099/2020/01/14", chave="ta-14")
    ids["aditivo"]("2025-03-10", "2026-03-31", None, numero="088/2023/02/10-SINFRA", forma="apostilamento",
                   chave="ap-10")
    ids["aditivo"]("2025-06-10", "2026-06-30", None, numero="099/2020/01/15", chave="ta-15")
    ids["aditivo"]("2025-07-10", "2026-07-31", None, numero="TA s/n", chave="ta-y")
    c.execute("UPDATE aditivos SET ordinal=99 WHERE chave_cadastro='ta-15'")    # o numero vem antes do campo
    c.execute("UPDATE aditivos SET ordinal=16 WHERE chave_cadastro='ta-y'")     # sem sufixo, vale o campo
    ids["aditivo"]("2025-09-10", "2026-09-30", None, numero="001/2026", chave="ta-x")    # sem sufixo nem campo
    t = prazos.historico_texto(c, ids["contrato"])
    assert "O 14º termo aditivo n.º 099/2020/01/14" in t
    assert "O 10º termo de apostilamento n.º 088/2023/02/10-SINFRA" in t
    assert "O 15º termo aditivo n.º 099/2020/01/15" in t
    assert "O 16º termo aditivo n.º TA s/n" in t
    assert "O 4º termo aditivo n.º 001/2026" in t        # contagem: quarto termo aditivo carregado


def test_numero_sem_termo_no_fim_cai_na_contagem(cenario):
    """O sufixo so' vale no formato contrato/ano/tipo/termo; termo 00 (o proprio contrato) nao e' ordinal."""
    c, ids = cenario
    ids["aditivo"]("2025-01-10", "2025-12-31", None, numero="099/2020/00/00", chave="ta-a")
    ids["aditivo"]("2025-02-10", "2026-01-31", None, numero="IC 041/2025", chave="ta-b")
    t = prazos.historico_texto(c, ids["contrato"])
    assert "O 1º termo aditivo n.º 099/2020/00/00" in t and "O 2º termo aditivo n.º IC 041/2025" in t


def test_numero_com_resto_nao_reconhecido_nao_vale_e_o_ordinal_vence(cenario):
    """Gate Sol da PR #304: depois do termo so' o sufixo institucional; outro resto deixa o `ordinal` valer."""
    c, ids = cenario
    ids["aditivo"]("2025-01-10", "2025-12-31", None, numero="099/2020/01/14/02", chave="ta-a")
    ids["aditivo"]("2025-02-10", "2026-01-31", None, numero="099/2020/01/14-retificado/15", chave="ta-b")
    c.execute("UPDATE aditivos SET ordinal=15 WHERE chave_cadastro='ta-b'"); c.commit()
    t = prazos.historico_texto(c, ids["contrato"])
    assert "O 1º termo aditivo n.º 099/2020/01/14/02" in t          # sem ordinal: contagem
    assert "O 15º termo aditivo n.º 099/2020/01/14-retificado/15" in t


# --- issue #292: sugestao de dias da carta de prorrogacao pelo ritmo dos ultimos 6 meses -------------------

def _medicao(c, cid, numero, competencia, atestado=None, protocolado=None, estado="recebida", tipo="execucao"):
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
              "valor_atestado_centavos) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (cid, numero, tipo, competencia, estado, protocolado, atestado))
    c.commit()


def _valor(c, cid, centavos):
    c.execute("UPDATE contratos SET valor_original_centavos=? WHERE id=?", (centavos, cid)); c.commit()


def _fim(c, cid, data):
    c.execute("UPDATE contratos SET execucao_fim=? WHERE id=?", (data, cid)); c.commit()


def test_sugestao_pelo_ritmo_dos_ultimos_6_meses(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 1_000_000_01)   # centavo impar
    # janela de hoje 15/10/2026: competencias 2026-04 a 2026-09; fora dela (03 e 10) entra no saldo, nao no ritmo
    _medicao(c, cid, 1, "2026-03", atestado=400_000_00)
    _medicao(c, cid, 2, "2026-05", atestado=200_000_00)
    _medicao(c, cid, 3, "2026-07", protocolado=100_000_01, estado="protocolada")   # sem atestado: vale o protocolado
    _medicao(c, cid, 4, "2026-09", atestado=0)
    _medicao(c, cid, 5, "2026-08", protocolado=999_999_00, estado="cancelada")     # cancelada nao mede
    _medicao(c, cid, 6, "2026-06", protocolado=50_000_00, tipo="reajuste")       # reajuste nao e' execucao
    _medicao(c, cid, 7, "2026-10", atestado=100_000_00)
    s = prazos.sugestao_dias(c, cid, D(2026, 10, 15))
    # saldo 1.000.000,01 - 800.000,01 = 200.000,00; medido nos 6 meses 300.000,01; ritmo 50.000,00/mes (arred. 1x)
    assert (s["saldo_centavos"], s["medido_periodo_centavos"], s["ritmo_centavos"]) == (200_000_00, 300_000_01, 50_000_00)
    assert (s["meses"], s["de"], s["ate"], s["motivo"]) == (6, "2026-04", "2026-09", None)
    # 4 meses no ritmo mostrado: conclusao 15/02/2027 (hoje + 4 meses); pedido = 15/02/2027 - 20/10/2026
    assert (s["execucao_fim"], s["novo_fim"], s["dias"]) == ("2026-10-20", "2027-02-15", 118)


def test_sugestao_so_os_dias_depois_do_fim_vigente(cenario):
    """Fim em 20/12, 4 meses de saldo a partir de 15/10: a obra termina em 15/02; o pedido e' de 20/12 a 15/02."""
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 1_000_00); _fim(c, cid, "2026-12-20")
    _medicao(c, cid, 1, "2026-09", atestado=600_00)   # ritmo 100,00; saldo 400,00
    s = prazos.sugestao_dias(c, cid, D(2026, 10, 15))
    assert (s["novo_fim"], s["dias"]) == ("2027-02-15", 57)


def test_sugestao_com_execucao_ja_vencida_conta_de_hoje(cenario):
    """Fim em 31/01/2026, pedido em 15/10/2026 com 3 meses de saldo: o novo fim e' 15/01/2027, depois do pedido."""
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 900_00); _fim(c, cid, "2026-01-31")
    _medicao(c, cid, 1, "2026-09", atestado=600_00)   # ritmo 100,00; saldo 300,00
    s = prazos.sugestao_dias(c, cid, D(2026, 10, 15))
    assert (s["novo_fim"], s["dias"]) == ("2027-01-15", 349)


def test_conclusao_antes_do_fim_vigente_nao_sugere(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 1_000_00); _fim(c, cid, "2027-12-20")
    _medicao(c, cid, 1, "2026-09", atestado=600_00)
    s = prazos.sugestao_dias(c, cid, D(2026, 10, 15))
    assert s["dias"] is None and s["novo_fim"] == "2027-02-15"
    assert s["motivo"] == ("No ritmo de 04/2026 a 09/2026 a obra termina em 15/02/2027, até o fim da execução "
                           "(20/12/2027): não há dias a pedir.")


def test_fracao_do_ultimo_mes_arredonda_para_cima(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 375_00)
    _medicao(c, cid, 1, "2026-09", atestado=300_00)
    # saldo 75,00 / ritmo 50,00 = 1,5 mes: 15/11 + metade de 30 dias = 30/11/2026; pedido de 20/10 a 30/11
    s = prazos.sugestao_dias(c, cid, D(2026, 10, 15))
    assert (s["ritmo_centavos"], s["novo_fim"], s["dias"]) == (50_00, "2026-11-30", 41)


def test_sem_medicao_nos_6_meses_nao_sugere_e_diz_por_que(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 900_00)
    _medicao(c, cid, 1, "2026-03", atestado=300_00)   # antes da janela
    _medicao(c, cid, 2, "2026-10", atestado=100_00)   # mes corrente, fora da janela
    s = prazos.sugestao_dias(c, cid, D(2026, 10, 15))
    assert (s["dias"], s["ritmo_centavos"], s["saldo_centavos"]) == (None, None, 500_00)
    assert s["motivo"] == "Sem medição de execução de 04/2026 a 09/2026: sem ritmo para sugerir os dias."


def test_ritmo_que_arredonda_a_zero_nao_sugere(cenario):
    """R$ 0,01 em 6 meses: a tela mostraria R$ 0,00/mes; a conta tem de bater com o que se mostra."""
    c, ids = cenario
    cid = ids["contrato"]
    _medicao(c, cid, 1, "2026-09", atestado=1)
    s = prazos.sugestao_dias(c, cid, D(2026, 10, 15))
    assert (s["dias"], s["ritmo_centavos"]) == (None, 0)
    assert s["motivo"] == "Ritmo de 04/2026 a 09/2026 abaixo de R$ 0,01/mês: sem ritmo para sugerir os dias."


def test_saldo_zero_nao_sugere(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 300_00)
    _medicao(c, cid, 1, "2026-09", atestado=300_00)
    s = prazos.sugestao_dias(c, cid, D(2026, 10, 15))
    assert (s["dias"], s["saldo_centavos"], s["ritmo_centavos"]) == (None, 0, 50_00)
    assert s["motivo"] == "Sem saldo a executar: não há dias a sugerir."


def test_sem_fim_de_execucao_nao_sugere(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _fim(c, cid, None)
    _medicao(c, cid, 1, "2026-09", atestado=50)
    s = prazos.sugestao_dias(c, cid, D(2026, 10, 15))
    assert s["dias"] is None and s["motivo"] == "Sem fim de execução no cadastro: não há de onde contar os dias."


def test_janela_atravessa_o_ano(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _medicao(c, cid, 1, "2025-08", atestado=10)
    s = prazos.sugestao_dias(c, cid, D(2026, 2, 3))
    assert (s["de"], s["ate"]) == ("2025-08", "2026-01")


def test_acima_do_teto_do_pedido_nao_sugere(cenario):
    """A API recusa pedido acima de 3.650 dias: a sugestao nao pode preencher o campo com um numero que da 422."""
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 1_006_00)
    _medicao(c, cid, 1, "2026-09", atestado=6_00)   # ritmo 1,00; saldo 1.000,00 = 1.000 meses
    s = prazos.sugestao_dias(c, cid, D(2026, 10, 15))
    assert s["dias"] is None and s["motivo"] == prazos.ACIMA_DO_TETO
    assert s["motivo"] == "No ritmo dos últimos 6 meses o pedido passaria de 3.650 dias, o máximo."


def test_ritmo_irrisorio_nao_derruba_a_aba(cenario):
    """Saldo de R$ 10 milhoes contra R$ 1,00 medido na janela: bilhoes de meses passariam do ano 9999."""
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 10_000_000_00 + 1_00)
    _medicao(c, cid, 1, "2026-09", atestado=1_00)
    s = prazos.sugestao_dias(c, cid, D(2026, 10, 15))
    assert s["dias"] is None and s["motivo"] == prazos.ACIMA_DO_TETO


def test_fim_de_execucao_no_ano_9999_nao_derruba_a_aba(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _fim(c, cid, "9999-12-31")
    _medicao(c, cid, 1, "2026-09", atestado=60)
    s = prazos.sugestao_dias(c, cid, D(2026, 10, 15))
    assert s["dias"] is None and "não há dias a pedir" in s["motivo"]


def test_mes_exato_nao_calcula_o_mes_seguinte(cenario):
    """1 mes exato de 15/11/9999: conclusao 15/12/9999, 1 dia depois do fim vigente. O mes seguinte (01/10000) nao
    existe; com resto zero ele nao pode entrar na conta, senao a sugestao some com o motivo errado."""
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 700); _fim(c, cid, "9999-12-14")
    _medicao(c, cid, 1, "9999-10", atestado=600)   # ritmo 1,00; saldo 1,00 = 1 mes
    s = prazos.sugestao_dias(c, cid, D(9999, 11, 15))
    assert (s["novo_fim"], s["dias"], s["motivo"]) == ("9999-12-15", 1, None)


# --- issue #662: execucao vencida so' quando o prazo de execucao e' conhecido -------------------------------------

TEXTO_662 = ("Aditivo de 10/11/2026 prorroga a vigência sem o prazo de execução; "
             "último prazo de execução registrado: 20/10/2026")


def test_execucao_vencida_com_aditivo_posterior_so_de_vigencia_vira_pendencia_de_cadastro(cenario):
    c, ids = cenario                  # execucao registrada ate' 2026-10-20; aditivo de 10/11 so' prorroga a vigencia
    ids["aditivo"]("2026-11-10", None, "2027-06-30")
    hoje = D(2026, 12, 1)
    todos = prazos.avisos(c, hoje)
    assert not [a for a in todos if a["tipo"] in ("instrumento_pendente", "execucao_vencendo")]
    assert not [a for a in todos if "execução vencida" in a["mensagem"]]
    [p] = [a for a in todos if a["tipo"] == "execucao_sem_prazo"]
    assert (p["natureza"], p["mensagem"], p["data"], p["contrato_id"]) == ("ausencia", TEXTO_662, "2026-11-10", ids["contrato"])
    s = prazos.situacao(c, ids["contrato"], hoje)
    # nada e' inferido: a data registrada fica; so' nao ha' dias a contar
    assert (s["execucao_fim"], s["dias_execucao"]) == ("2026-10-20", None)
    assert s["execucao_sem_prazo"] == {"aditivo_em": "2026-11-10", "execucao_fim": "2026-10-20"}
    assert prazos.resumo(c, ids["contrato"], hoje)["dias_execucao"] is None


def test_execucao_vencida_sem_aditivo_posterior_continua_com_o_aviso(cenario):
    c, ids = cenario
    hoje = D(2026, 12, 1)
    a = _por_tipo(c, hoje)["instrumento_pendente"]
    assert a["nivel"] == "critico" and "execução vencida há 42 dias" in a["mensagem"]
    s = prazos.situacao(c, ids["contrato"], hoje)
    assert s["dias_execucao"] == -42 and s["execucao_sem_prazo"] is None
    assert "execucao_sem_prazo" not in _por_tipo(c, hoje)


def test_aditivo_de_vigencia_assinado_antes_do_fim_da_execucao_nao_tira_o_aviso(cenario):
    c, ids = cenario                  # o aditivo e' anterior ao fim da execucao registrada: ela venceu depois dele
    ids["aditivo"]("2026-10-01", None, "2027-06-30")
    a = _por_tipo(c, D(2026, 12, 1))
    assert "execução vencida há 42 dias" in a["instrumento_pendente"]["mensagem"] and "execucao_sem_prazo" not in a


def test_aditivo_posterior_que_traz_a_execucao_segue_a_regra_de_sempre(cenario):
    c, ids = cenario
    ids["aditivo"]("2026-11-10", None, "2027-06-30")
    # um aditivo mais novo traz a execucao: o prazo e' conhecido de novo, vencido ou nao
    ids["aditivo"]("2026-11-15", "2026-11-20", None, numero="002/2026", chave="ta-2")
    a = _por_tipo(c, D(2026, 12, 1))
    assert "execução vencida há 11 dias" in a["instrumento_pendente"]["mensagem"] and "execucao_sem_prazo" not in a
    ids["aditivo"]("2026-11-25", "2027-03-31", None, numero="003/2026", chave="ta-3")
    a = _por_tipo(c, D(2026, 12, 1))
    assert not {"instrumento_pendente", "execucao_vencendo", "execucao_sem_prazo"} & set(a)


def test_pedido_em_curso_sem_prazo_de_execucao_conhecido_nao_diz_vencida(cenario):
    c, ids = cenario
    ids["aditivo"]("2026-11-10", None, "2027-06-30")
    ids["pleito"]("prazo", "2026-11-20")          # pedido posterior ao aditivo: segue sem instrumento
    todos = _por_tipo(c, D(2026, 12, 1))
    a = todos["instrumento_pendente"]
    assert a["nivel"] == "atencao" and a["publico"] == ["operacao"] and "vencida" not in a["mensagem"]
    # o aviso conta desde o pedido, e nao ate' a execucao registrada (que o poria como vencido na agenda)
    assert (a["data"], a["sentido"], a["dias"]) == ("2026-11-20", "desde", 11)
    assert "execucao_sem_prazo" in todos


def test_pendencia_de_execucao_sem_prazo_para_no_encerramento(cenario):
    c, ids = cenario
    ids["aditivo"]("2026-11-10", None, "2027-06-30")
    c.execute("UPDATE contratos SET encerramento_iniciado_em='2026-11-20' WHERE id=?", (ids["contrato"],)); c.commit()
    assert "execucao_sem_prazo" not in _por_tipo(c, D(2026, 12, 1))


def test_ritmo_e_prazo_sem_prazo_de_execucao_conhecido_nao_diz_que_atrasa(cenario):
    """#662 no cartao "Ritmo e prazo" (#655): sem prazo de execucao conhecido nao ha' com o que comparar a conclusao."""
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 1_000_00)
    _medicao(c, cid, 1, "2026-09", atestado=600_00)   # ritmo 100,00; saldo 400,00
    assert prazos.ritmo_e_prazo(c, cid, D(2026, 12, 1))["situacao"] == "atrasa"
    ids["aditivo"]("2026-11-10", None, "2027-06-30")
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 12, 1))
    assert r == {"ritmo_centavos": 100_00, "necessario_centavos": None, "competencias_restantes": None,
                 "conclusao": None, "situacao": None, "dias_alem": None}


# --- issue #655: cartao "Ritmo e prazo" da pagina da obra (a mesma conta da sugestao, so' mostrada) --------

def test_ritmo_e_prazo_conclusao_depois_do_fim_atrasa_com_os_dias(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 1_000_00); _fim(c, cid, "2026-12-20")
    _medicao(c, cid, 1, "2026-09", atestado=600_00)   # ritmo 100,00; saldo 400,00; conclusao 15/02/2027
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 10, 15))
    # #803: restam outubro, novembro e dezembro; 400,00 / 3 = 133,33 por mes, acima do ritmo
    assert r == {"ritmo_centavos": 100_00, "necessario_centavos": 133_33, "competencias_restantes": 3,
                 "conclusao": "2027-02-15", "situacao": "atrasa", "dias_alem": 57}


def test_ritmo_e_prazo_conclusao_ate_o_fim_e_no_prazo(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 1_000_00); _fim(c, cid, "2027-02-15")   # no proprio dia do fim ainda e' no prazo
    _medicao(c, cid, 1, "2026-09", atestado=600_00)
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 10, 15))
    assert (r["conclusao"], r["situacao"], r["dias_alem"]) == ("2027-02-15", "no_prazo", None)


def test_ritmo_e_prazo_acima_do_teto_do_pedido_nao_fecha_a_conta(cenario):
    """Ritmo muito baixo (obra que mal comecou ou quase parada): a conclusao cairia decadas a frente. Acima do teto
    do pedido o cartao nao diz conclusao nem situacao; ritmo, saldo e fim da execucao continuam."""
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 1_006_00)
    _medicao(c, cid, 1, "2026-09", atestado=6_00)   # ritmo 1,00; saldo 1.000,00 = 1.000 meses
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 10, 15))
    # #803: o necessario nao depende do ritmo: 1.000,00 em outubro, o mes do fim da execucao (20/10/2026)
    assert r == {"ritmo_centavos": 1_00, "necessario_centavos": 1_000_00, "competencias_restantes": 1,
                 "conclusao": None, "situacao": None, "dias_alem": None}


def test_ritmo_e_prazo_no_teto_do_pedido_ainda_atrasa(cenario):
    """O limite e' o do pedido: exatamente 3.650 dias alem do fim ainda aparece; um dia a mais, nao."""
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 1_000_00)
    _medicao(c, cid, 1, "2026-09", atestado=600_00)   # ritmo 100,00; saldo 400,00; conclusao 15/02/2027
    _fim(c, cid, (D(2027, 2, 15) - datetime.timedelta(days=prazos.TETO_DIAS)).isoformat())
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 10, 15))
    assert (r["conclusao"], r["situacao"], r["dias_alem"]) == ("2027-02-15", "atrasa", prazos.TETO_DIAS)
    _fim(c, cid, (D(2027, 2, 14) - datetime.timedelta(days=prazos.TETO_DIAS)).isoformat())
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 10, 15))
    assert (r["conclusao"], r["situacao"], r["dias_alem"]) == (None, None, None)


def test_ritmo_e_prazo_sem_medicao_na_janela_sem_ritmo_sem_conclusao_sem_situacao(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 900_00)
    _medicao(c, cid, 1, "2026-03", atestado=300_00)   # antes da janela
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 10, 15))
    # #803: sem ritmo ainda ha' quanto medir por mes: 600,00 em outubro, o mes do fim da execucao
    assert r == {"ritmo_centavos": None, "necessario_centavos": 600_00, "competencias_restantes": 1,
                 "conclusao": None, "situacao": None, "dias_alem": None}


def test_ritmo_e_prazo_sem_saldo_ou_sem_fim_de_execucao_nao_tem_situacao(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 600_00)
    _medicao(c, cid, 1, "2026-09", atestado=600_00)
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 10, 15))
    assert (r["ritmo_centavos"], r["conclusao"], r["situacao"]) == (100_00, None, None)
    _valor(c, cid, 1_000_00); _fim(c, cid, None)
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 10, 15))
    assert (r["ritmo_centavos"], r["conclusao"], r["situacao"], r["dias_alem"]) == (100_00, None, None, None)


# --- issue #803: o necessario por mes para terminar no prazo (saldo a executar / competencias que restam) ---

def test_competencias_que_restam_contam_o_mes_de_hoje_e_o_do_fim_da_execucao():
    assert prazos.competencias_restantes(D(2026, 11, 18), D(2027, 3, 31)) == 5     # nov, dez, jan, fev, mar
    assert prazos.competencias_restantes(D(2026, 11, 18), D(2026, 11, 30)) == 1    # o fim no mes de hoje
    assert prazos.competencias_restantes(D(2026, 12, 31), D(2027, 1, 1)) == 2      # a virada de ano
    assert prazos.competencias_restantes(D(2026, 1, 1), D(2026, 12, 31)) == 12
    assert prazos.competencias_restantes(D(2026, 11, 18), D(2028, 2, 10)) == 16


def test_necessario_por_mes_arredonda_uma_vez_a_centavos_como_o_ritmo():
    assert prazos.necessario_por_mes(10_000_000_00, 5) == 2_000_000_00
    assert prazos.necessario_por_mes(100_00, 3) == 33_33
    assert prazos.necessario_por_mes(200_00, 3) == 66_67
    assert prazos.necessario_por_mes(5, 2) == 3                                    # meio centavo sobe, como no ritmo
    # centavo impar num valor que o float nao guarda inteiro: a conta e' decimal
    assert prazos.necessario_por_mes(90_071_992_547_409_93, 1) == 90_071_992_547_409_93


def test_necessario_e_o_saldo_a_executar_pelas_competencias_que_restam_com_virada_de_ano(cenario):
    """O exemplo da issue: saldo de 10.000.000,00, hoje em novembro, execucao ate' marco: 5 competencias."""
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 12_000_000_00); _fim(c, cid, "2027-03-31")
    _medicao(c, cid, 1, "2026-09", atestado=2_000_000_00)   # saldo 10.000.000,00; ritmo 2.000.000,00 / 6
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 11, 18))
    assert (r["necessario_centavos"], r["competencias_restantes"]) == (2_000_000_00, 5)
    assert r["ritmo_centavos"] == 333_333_33 and r["situacao"] == "atrasa" and r["dias_alem"] > 0
    # o saldo e' o de `paineis.saldo`, o mesmo do ritmo: a medicao de projeto baixa o saldo e o necessario
    _medicao(c, cid, 2, "2026-10", atestado=1_000_000_00, tipo="projeto")
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 11, 18))
    assert (r["necessario_centavos"], r["competencias_restantes"]) == (1_800_000_00, 5)


def test_necessario_com_o_fim_da_execucao_no_mes_de_hoje_e_o_saldo_inteiro(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 1_000_00)
    _medicao(c, cid, 1, "2026-09", atestado=600_00)        # saldo 400,00; ritmo 100,00
    for fim in ("2026-11-30", "2026-11-18"):               # no dia do fim a execucao ainda nao venceu
        _fim(c, cid, fim)
        r = prazos.ritmo_e_prazo(c, cid, D(2026, 11, 18))
        assert (r["necessario_centavos"], r["competencias_restantes"], r["situacao"]) == (400_00, 1, "atrasa")
    # venceu ontem, no mesmo mes: nao ha' competencia que reste; o selo dos dias alem do fim continua
    _fim(c, cid, "2026-11-17")
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 11, 18))
    assert (r["necessario_centavos"], r["competencias_restantes"]) == (None, None)
    assert r["ritmo_centavos"] == 100_00 and r["situacao"] == "atrasa" and r["dias_alem"] > 0


def test_ritmo_igual_ou_acima_do_necessario_e_no_prazo_e_um_centavo_abaixo_atrasa(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    _valor(c, cid, 1_000_00); _fim(c, cid, "2027-01-31")
    _medicao(c, cid, 1, "2026-09", atestado=600_00)        # ritmo 100,00; saldo 400,00
    # restam out, nov, dez e jan: necessario 100,00 = ritmo. A conclusao estimada conta os meses do dia de hoje e
    # passa do fim por menos de um mes; o necessario conta inteira a competencia de hoje, e e' ele que decide
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 10, 15))
    assert r == {"ritmo_centavos": 100_00, "necessario_centavos": 100_00, "competencias_restantes": 4,
                 "conclusao": "2027-02-15", "situacao": "no_prazo", "dias_alem": None}
    _valor(c, cid, 1_000_04)                                # saldo 400,04: necessario 100,01, um centavo acima do ritmo
    r = prazos.ritmo_e_prazo(c, cid, D(2026, 10, 15))
    assert r == {"ritmo_centavos": 100_00, "necessario_centavos": 100_01, "competencias_restantes": 4,
                 "conclusao": "2027-02-16", "situacao": "atrasa", "dias_alem": 16}


def test_necessario_nulo_sem_fim_sem_saldo_e_na_obra_parada_encerrada_ou_com_medicao_final(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    hoje = D(2026, 11, 18)
    _valor(c, cid, 1_000_00); _fim(c, cid, "2027-03-31")
    _medicao(c, cid, 1, "2026-09", atestado=600_00)

    def necessario():
        r = prazos.ritmo_e_prazo(c, cid, hoje)
        return r["necessario_centavos"], r["competencias_restantes"]

    assert necessario() == (80_00, 5)
    _fim(c, cid, None)                                       # sem fim de execucao
    assert necessario() == (None, None)
    _fim(c, cid, "2027-03-31"); _valor(c, cid, 600_00)       # sem saldo
    assert necessario() == (None, None)
    _valor(c, cid, 1_000_00)
    ids["instrumento"]("paralisacao", "2026-11-01")          # obra parada
    assert necessario() == (None, None)
    ids["instrumento"]("reinicio", "2026-11-10")
    assert necessario() == (80_00, 5)
    c.execute("UPDATE contratos SET encerramento_iniciado_em='2026-11-05' WHERE id=?", (cid,)); c.commit()   # medicao final
    assert necessario() == (None, None)
    c.execute("UPDATE contratos SET encerramento_iniciado_em=NULL, estado='encerrado' WHERE id=?", (cid,)); c.commit()
    assert necessario() == (None, None)
    r = prazos.ritmo_e_prazo(c, cid, hoje)                   # o ritmo continua; situacao, nao
    assert (r["ritmo_centavos"], r["situacao"], r["dias_alem"]) == (100_00, None, None)


# --- issue #822: a leitura do andamento, uma so', com o prazo no fim e a parada de fato fora da regua ------

SEM_LEITURA = {"situacao": None, "pct": None, "motivo": None, "prorrogacao_pedida": False, "sem_medicao_desde": None,
               "execucao_fim": None, "atencao_desde_pct": 70, "adiantada_desde_pct": 100}


def _leitura(c, cid, hoje, bp=None):
    """A leitura como as duas rotas a pedem: `ritmo_na_cota` sobre o saldo de `paineis.posicao_na_cota`."""
    from app import paineis
    s = paineis.saldo(c, cid)
    posicao = paineis.posicao_na_cota(s["vigente_execucao_centavos"], s["medido_centavos"], bp)
    return prazos.ritmo_na_cota(c, cid, hoje, bp, posicao["saldo_centavos"])["leitura"]


def test_leitura_do_andamento_o_corte_70_100_e_o_percentual_por_piso():
    hoje = D(2026, 11, 18)

    def lida(ritmo, necessario=100_000):
        r = prazos.leitura_do_andamento(ritmo, necessario, 5, False, "2026-10", hoje)
        assert (r["motivo"], r["atencao_desde_pct"], r["adiantada_desde_pct"]) == (None, 70, 100)
        return r["situacao"], r["pct"]

    assert lida(115_000) == ("adiantada", 115)
    assert lida(100_000) == ("adiantada", 100)
    assert lida(99_999) == ("atencao", 99)       # 99,999% nao vira 100%
    assert lida(70_000) == ("atencao", 70)
    assert lida(69_999) == ("devagar", 69)
    assert lida(0) == ("devagar", 0)
    # sem prazo a cumprir (sem necessario) ou sem ritmo nao ha' leitura nem motivo
    for ritmo, necessario, competencias in ((100, None, None), (100, 0, 5), (100, 100, None), (None, 100, 5)):
        assert prazos.leitura_do_andamento(ritmo, necessario, competencias, False, None, hoje) == SEM_LEITURA


def test_obra_com_duas_competencias_de_prazo_fica_sem_leitura_e_com_tres_tem(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    hoje = D(2026, 11, 18)
    _valor(c, cid, 1_000_00)
    _medicao(c, cid, 1, "2026-09", atestado=300_00)
    _medicao(c, cid, 2, "2026-10", atestado=300_00)        # ritmo 100,00; saldo 400,00
    _fim(c, cid, "2026-12-31")                             # novembro e dezembro: duas competencias
    assert prazos.ritmo_e_prazo(c, cid, hoje)["competencias_restantes"] == 2
    # o fim da execucao vai junto, para a Situacao escrever "Prazo no fim · execucao ate' dd/mm" (19/11/2026)
    assert _leitura(c, cid, hoje) == {**SEM_LEITURA, "motivo": "prazo_no_fim", "execucao_fim": "2026-12-31"}
    _fim(c, cid, "2026-11-18")                             # vence hoje: uma competencia
    assert _leitura(c, cid, hoje) == {**SEM_LEITURA, "motivo": "prazo_no_fim", "execucao_fim": "2026-11-18"}
    _fim(c, cid, "2027-01-01")                             # novembro, dezembro e janeiro: tres competencias
    r = prazos.ritmo_e_prazo(c, cid, hoje)
    assert (r["competencias_restantes"], r["necessario_centavos"]) == (3, 133_33)
    assert _leitura(c, cid, hoje) == {**SEM_LEITURA, "situacao": "atencao", "pct": 75}
    # o necessario nao muda com a leitura: com duas competencias continua o saldo dividido por elas
    _fim(c, cid, "2026-12-31")
    assert prazos.ritmo_e_prazo(c, cid, hoje)["necessario_centavos"] == 200_00


def test_prorrogacao_pedida_e_sem_resposta_tira_a_obra_da_regua(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    hoje = D(2026, 11, 18)
    _valor(c, cid, 1_000_00); _fim(c, cid, "2027-03-31")   # cinco competencias
    _medicao(c, cid, 1, "2026-09", atestado=300_00)
    _medicao(c, cid, 2, "2026-10", atestado=300_00)
    assert _leitura(c, cid, hoje)["situacao"] == "adiantada"
    ids["pleito"]("prazo", "2026-11-04")
    assert _leitura(c, cid, hoje) == {**SEM_LEITURA, "motivo": "prorrogacao_pedida", "prorrogacao_pedida": True}
    # com o prazo no fim, o motivo e' o prazo, e o pedido vai junto
    _fim(c, cid, "2026-12-15")
    assert _leitura(c, cid, hoje) == {**SEM_LEITURA, "motivo": "prazo_no_fim", "prorrogacao_pedida": True,
                                      "execucao_fim": "2026-12-15"}
    # o instrumento de prazo assinado no dia do envio ou depois responde o pedido: a leitura volta
    ids["aditivo"]("2026-11-10", "2027-03-31", "2027-06-30")
    assert _leitura(c, cid, hoje)["situacao"] == "adiantada"


def test_sem_medicao_ha_tres_competencias_leva_o_mes_da_ultima(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    hoje = D(2026, 11, 18)                                 # fechadas: agosto, setembro e outubro
    _valor(c, cid, 1_000_00); _fim(c, cid, "2027-03-31")
    _medicao(c, cid, 1, "2026-07", atestado=600_00)        # ritmo 100,00, na janela de maio a outubro
    assert prazos.ritmo_e_prazo(c, cid, hoje)["ritmo_centavos"] == 100_00
    assert _leitura(c, cid, hoje) == {**SEM_LEITURA, "motivo": "sem_medicao", "sem_medicao_desde": "2026-07"}
    # medicao que nao conta no ritmo tambem nao conta aqui: cancelada, projeto, reajuste e a sem valor
    _medicao(c, cid, 2, "2026-09", protocolado=50_00, estado="cancelada")
    _medicao(c, cid, 3, "2026-09", atestado=50_00, tipo="projeto")
    _medicao(c, cid, 4, "2026-10", protocolado=50_00, tipo="reajuste")
    _medicao(c, cid, 5, "2026-10", atestado=0)
    assert _leitura(c, cid, hoje)["sem_medicao_desde"] == "2026-07"
    # mediu em agosto: so' duas competencias fechadas sem medicao, a regua vale
    _medicao(c, cid, 6, "2026-08", atestado=10_00)
    r = _leitura(c, cid, hoje)
    assert (r["situacao"], r["motivo"], r["sem_medicao_desde"]) == ("adiantada", None, None)


def test_sem_medicao_fora_da_janela_do_ritmo_tambem_leva_o_mes_e_quem_nunca_mediu_fica_sem_leitura(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    hoje = D(2026, 11, 18)
    _valor(c, cid, 1_000_00); _fim(c, cid, "2027-10-31")
    assert _leitura(c, cid, hoje) == SEM_LEITURA           # nunca mediu execucao: nao ha' mes a escrever
    _medicao(c, cid, 1, "2026-02", atestado=100_00)        # fora da janela: sem ritmo
    assert prazos.ritmo_e_prazo(c, cid, hoje)["ritmo_centavos"] is None
    assert _leitura(c, cid, hoje) == {**SEM_LEITURA, "motivo": "sem_medicao", "sem_medicao_desde": "2026-02"}


def test_ritmo_que_nao_fecha_a_conclusao_continua_com_leitura(cenario):
    """A pagina da obra calava a situacao (conclusao alem do teto do pedido) e a lista escrevia "Devagar": a leitura
    agora e' uma so', e a obra que mede quase nada do necessario e' devagar nas duas."""
    c, ids = cenario
    cid = ids["contrato"]
    hoje = D(2026, 11, 18)
    _valor(c, cid, 10_000_000_00); _fim(c, cid, "2027-03-31")
    _medicao(c, cid, 1, "2026-10", atestado=6_00)          # ritmo 1,00 contra um saldo de quase 10 milhoes
    r = prazos.ritmo_e_prazo(c, cid, hoje)
    assert (r["conclusao"], r["situacao"], r["dias_alem"]) == (None, None, None)
    assert _leitura(c, cid, hoje) == {**SEM_LEITURA, "situacao": "devagar", "pct": 0}


def test_leitura_sai_dos_valores_na_cota_que_a_tela_mostra(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    hoje = D(2026, 11, 18)
    _valor(c, cid, 1_000_01); _fim(c, cid, "2027-01-31")   # tres competencias
    _medicao(c, cid, 1, "2026-10", atestado=600_00)        # ritmo 100,00; saldo 400,01
    from app import paineis
    s = paineis.saldo(c, cid)
    posicao = paineis.posicao_na_cota(s["vigente_execucao_centavos"], s["medido_centavos"], 4900)
    r = prazos.ritmo_na_cota(c, cid, hoje, 4900, posicao["saldo_centavos"])
    assert (r["ritmo_centavos"], r["necessario_centavos"]) == (49_00, 65_33)   # a cota do ritmo; o saldo da tela / 3
    assert r["leitura"]["pct"] == r["ritmo_centavos"] * 100 // r["necessario_centavos"] == 75
    assert r["leitura"]["situacao"] == "atencao"


def test_obra_sem_prazo_a_cumprir_nao_tem_leitura_nem_motivo(cenario):
    c, ids = cenario
    cid = ids["contrato"]
    hoje = D(2026, 11, 18)
    _valor(c, cid, 1_000_00); _fim(c, cid, "2026-11-17")   # venceu ontem
    _medicao(c, cid, 1, "2026-06", atestado=600_00)
    ids["pleito"]("prazo", "2026-11-04")
    assert _leitura(c, cid, hoje) == SEM_LEITURA
    _fim(c, cid, "2026-12-15")
    ids["instrumento"]("paralisacao", "2026-11-01")        # paralisada
    assert _leitura(c, cid, hoje) == SEM_LEITURA
