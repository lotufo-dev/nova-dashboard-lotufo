"""Redesenho 2026-11 (#507): a lista "Em andamento" (passo e com quem) e as contagens do menu lateral. Usa o cenario de
`test_medicoes_resumo` (as medicoes dele sao todas da competencia 2026-09; HOJE e' 2026-10-09)."""
from app import medicoes
from tests.test_medicoes_resumo import HOJE, _medicao, cenario, conn  # noqa: F401  (fixtures)


def test_em_andamento_traz_o_passo_e_com_quem_esta(conn, cenario):
    """#653: cada linha diz o passo da barra de passos da pagina da medicao (os seis nomes de `PASSOS`, numero e nome)
    e se a medicao esta com a Lotufo ou com o orgao. Os nomes das cinco etapas antigas nao saem mais do servidor."""
    ids = cenario
    _medicao(conn, ids["a"], 30, "execucao", "boletim_recebido", 1000)
    _medicao(conn, ids["c"], 32, "execucao", "planilha_gerada", 3000)
    _medicao(conn, ids["c"], 33, "execucao", "planilha_enviada", 3000, planilha_enviada_em="2026-10-07")
    conn.commit()
    linhas = medicoes.resumo(conn, HOJE)["linhas"]
    por = {x["situacao"]: x for x in linhas}
    assert [por[s]["passo"] for s in medicoes.ORDEM_SITUACAO] == [
        {"numero": 1, "nome": "Planilha e carta"}, {"numero": 2, "nome": "Análise do órgão"}, {"numero": 3, "nome": "Espelhos"},
        {"numero": 3, "nome": "Espelhos"}, {"numero": 4, "nome": "Notas"}, {"numero": 5, "nome": "Envio da nota"},
        {"numero": 6, "nome": "Pagamento"}]
    # o proximo passo diz o nome do passo, o mesmo do selo
    assert [por[s]["proximo_passo"] for s in medicoes.ORDEM_SITUACAO] == [
        "Planilha e carta", "Análise do órgão", "Espelhos", "Espelhos", "Notas", "Envio da nota", "Pagamento"]
    assert {x["passo"]["nome"] for x in linhas} <= set(medicoes.PASSOS)
    assert not {"Faturamento", "Envio ao órgão", "Nota fiscal", "Espelho"} & {x["passo"]["nome"] for x in linhas}
    assert (por["planilha-gerada"]["com_quem"], por["planilha-enviada"]["com_quem"]) == ("Lotufo", "Órgão")
    assert (por["enviar-nota"]["com_quem"], por["aguardando-pagamento"]["com_quem"]) == ("Lotufo", "Órgão")
    # todo estado de "em andamento" tem passo com um dos seis nomes (a tela nunca fica sem selo)
    assert set(medicoes.PROXIMO_PASSO.values()) <= set(medicoes.PASSOS)


def test_obra_sem_planilha_e_carta_comeca_em_espelhos(conn, cenario):
    """#653: a obra que nao manda planilha/carta ao orgao (MTPAR) nao tem os passos 1 e 2: a medicao dela nos estados
    do motor esta' em "Espelhos", como na barra da pagina da medicao; o reajuste tambem nao tem esses passos."""
    ids = cenario
    b = _medicao(conn, ids["b"], 31, "execucao", "planilha_gerada", 2000)
    r = _medicao(conn, ids["a"], 31, "reajuste", "planilha_enviada", 100, planilha_enviada_em="2026-10-07")
    a = _medicao(conn, ids["a"], 32, "execucao", "planilha_enviada", 100, planilha_enviada_em="2026-10-07")
    conn.commit()
    por = {m["id"]: m for m in medicoes.em_andamento(conn)}
    assert por[b]["proximo_passo"] == "Espelhos" and por[b]["passo"] == {"numero": 3, "nome": "Espelhos"}
    assert por[r]["proximo_passo"] == "Espelhos"
    assert por[a]["proximo_passo"] == "Análise do órgão" and por[a]["passo"] == {"numero": 2, "nome": "Análise do órgão"}


def test_meses_anteriores_trazem_o_mesmo_passo_da_linha(conn, cenario):
    """#653: o passo de "Meses anteriores" e' o do selo da linha, com o numero que a tela usa na ancora da medicao."""
    r = medicoes.resumo(conn, HOJE, mes="2026-10")
    passo_da_linha = {x["medicao_id"]: x["passo"] for x in r["linhas"]}
    assert r["anteriores"] and all(x["passo"] == passo_da_linha[x["medicao_id"]] for x in r["anteriores"])
    assert {x["titulo"]: x["passo"]["numero"] for x in r["anteriores"] if x["obra"] == "Obra A"} == {
        "24ª Medição + Reajuste": 5, "1ª Medição de Projeto": 5}


def test_contagens_do_menu_iniciar_e_em_andamento(conn, cenario):
    """"Iniciar medicao" conta as obras ativas sem medicao NA competencia do mes; "Em andamento", as linhas da lista."""
    ids = cenario
    r = medicoes.resumo(conn, HOJE)
    assert r["mes"] == "2026-10"
    # o cenario so' tem medicoes de 2026-09: as obras ativas (A, B, C, D e F) estao sem medicao em outubro
    assert {o["obra"] for o in r["obras"] if o["sem_no_mes"]} == {"Obra A", "Obra B", "Obra C", "Obra D", "Obra F"}
    assert r["contagens"]["iniciar"] == 5
    assert r["contagens"]["em-andamento"] == len(r["linhas"]) > 0
    # em setembro saem as que tem medicao viva; a prevista (D) nao conta como medicao
    s = medicoes.resumo(conn, HOJE, mes="2026-09")
    assert {o["obra"] for o in s["obras"] if o["sem_no_mes"]} == {"Obra D"} and s["contagens"]["iniciar"] == 1
    # uma medicao de outubro tira a obra da lista de outubro, mesmo com a de setembro ainda aberta
    nova = _medicao(conn, ids["a"], 25, "execucao", "planilha_gerada", 100)
    conn.execute("UPDATE medicoes SET competencia='2026-10' WHERE id=?", (nova,))
    conn.commit()
    r2 = medicoes.resumo(conn, HOJE)
    assert "Obra A" not in {o["obra"] for o in r2["obras"] if o["sem_no_mes"]} and r2["contagens"]["iniciar"] == 4
    # cancelada nao conta como medicao do mes
    conn.execute("UPDATE medicoes SET estado='cancelada' WHERE id=?", (nova,))
    conn.commit()
    assert medicoes.resumo(conn, HOJE)["contagens"]["iniciar"] == 5


def test_reajuste_sozinho_no_mes_nao_tira_a_obra_de_iniciar_medicao(conn, cenario):
    """O reajuste acompanha a execucao: so' ele na competencia nao quer dizer que a medicao do mes foi iniciada."""
    ids = cenario
    r = _medicao(conn, ids["a"], 25, "reajuste", "planilha_gerada", 100)
    conn.execute("UPDATE medicoes SET competencia='2026-10' WHERE id=?", (r,))
    conn.commit()
    assert "Obra A" in {o["obra"] for o in medicoes.resumo(conn, HOJE)["obras"] if o["sem_no_mes"]}


def test_obra_em_encerramento_fica_fora_de_iniciar_medicao(conn, cenario):
    """A-21: a obra em encerramento nao e' ativa; sai da lista e da contagem de "Iniciar medicao"."""
    ids = cenario
    conn.execute("UPDATE contratos SET encerramento_iniciado_em='2026-10-01' WHERE id=?", (ids["a"],))
    conn.commit()
    r = medicoes.resumo(conn, HOJE)
    assert "Obra A" not in {o["obra"] for o in r["obras"] if o["sem_no_mes"]} and r["contagens"]["iniciar"] == 4


def test_ultima_medicao_traz_estado_e_valor(conn, cenario):
    r = medicoes.resumo(conn, HOJE)
    b = next(o for o in r["obras"] if o["obra"] == "Obra B")
    assert b["ultima_medicao"] == {"numero": 15, "tipo": "execucao", "competencia": "2026-09", "estado": "protocolada",
                                   "valor_centavos": 300000}
