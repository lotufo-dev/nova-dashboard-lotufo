"""Redesenho 2026-11 (#507): a lista "Em andamento" (passo e com quem) e as contagens do menu lateral. Usa o cenario de
`test_medicoes_resumo` (as medicoes dele sao todas da competencia 2026-09; HOJE e' 2026-10-09)."""
from app import medicoes
from tests.test_medicoes_resumo import HOJE, _medicao, cenario, conn  # noqa: F401  (fixtures)


def test_em_andamento_traz_o_passo_e_com_quem_esta(conn, cenario):
    """Cada linha diz o passo da barra de passos (numero e nome) e se a medicao esta com a Lotufo ou com o orgao."""
    ids = cenario
    _medicao(conn, ids["a"], 30, "execucao", "boletim_recebido", 1000)
    _medicao(conn, ids["d"], 32, "execucao", "planilha_gerada", 3000)
    _medicao(conn, ids["d"], 33, "execucao", "planilha_enviada", 3000, planilha_enviada_em="2026-10-07")
    conn.commit()
    por = {x["situacao"]: x for x in medicoes.resumo(conn, HOJE)["linhas"]}
    # os mesmos numeros e nomes das ETAPAS da pagina da medicao (Etapas.tsx): 5 etapas, nao 6
    assert [por[s]["passo"] for s in ("planilha-gerada", "planilha-enviada", "boletim-recebido", "faturamento", "aguardando-nota",
                                      "enviar-nota", "aguardando-pagamento") if s in por] == [
        {"numero": 1, "nome": "Espelho"}, {"numero": 1, "nome": "Espelho"}, {"numero": 1, "nome": "Espelho"},
        {"numero": 2, "nome": "Faturamento"}, {"numero": 3, "nome": "Nota fiscal"}, {"numero": 4, "nome": "Envio ao órgão"},
        {"numero": 5, "nome": "Pagamento"}]
    assert (por["planilha-gerada"]["com_quem"], por["planilha-enviada"]["com_quem"]) == ("Lotufo", "Órgão")
    assert (por["enviar-nota"]["com_quem"], por["aguardando-pagamento"]["com_quem"]) == ("Lotufo", "Órgão")
    # toda situacao do ciclo tem passo (a tela nunca fica sem selo)
    assert set(medicoes.PASSO_DA_SITUACAO) == set(medicoes.ORDEM_SITUACAO)


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
