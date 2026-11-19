"""Tela Medicoes como fila de trabalho (issue #805, etapa 3a): com quem esta' cada medicao, ha' quantos dias uteis
esta' parada e a leitura disso, a diferenca aprovado x pedido no valor cheio, o quadro por contratante e os meses
anteriores que pedem acao. Valores e obras ficticios."""
import datetime
import json

import pytest

from app import auth, db, fila_medicoes

HOJE = datetime.date(2026, 11, 18)      # quarta-feira; 02/11 e 15/11 sao feriados nacionais
MES = "2026-10"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn()
    db.migrate(c)
    yield c
    c.close()


def _orgao(c, chave, nome, familia):
    return c.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES (?,?,?,'{}')", (chave, nome, familia)).lastrowid


def _obra(c, nome, orgao_id, **cols):
    campos = {"orgao": "ÓRGÃO", "numero_instrumento": f"IC {nome}", "objeto": nome, "valor_original_centavos": 0,
              "estado": "ativo", "nome_curto": nome, "orgao_id": orgao_id, **cols}
    return c.execute(f"INSERT INTO contratos ({', '.join(campos)}) VALUES ({','.join('?' * len(campos))})",
                     list(campos.values())).lastrowid


def _medicao(c, cid, numero, estado, competencia=MES, tipo="execucao", pedido=None, aprovado=None, protocolo=None, **datas):
    campos = {"contrato_id": cid, "numero": numero, "tipo": tipo, "competencia": competencia, "estado": estado,
              "valor_protocolado_centavos": pedido, "valor_atestado_centavos": aprovado,
              "criado_em": "2026-01-01 10:00:00", **datas}
    mid = c.execute(f"INSERT INTO medicoes ({', '.join(campos)}) VALUES ({','.join('?' * len(campos))})",
                    list(campos.values())).lastrowid
    if protocolo:
        c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, ?, 'manual')", (mid, protocolo))
    return mid


def _espelho(c, uid, cid, numero, criado_em, *medicoes_):
    eid = c.execute("INSERT INTO espelhos (contrato_id, numero, competencia, versao, situacao, entradas, saidas, "
                    "regra_sha256, criado_por, criado_em) VALUES (?,?,?,1,'vigente','{}','[]','x',?,?)",
                    (cid, numero, MES, uid, criado_em)).lastrowid
    for mid in medicoes_:
        c.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id) VALUES (?,?)", (eid, mid))


def _email_ao_faturamento(c, uid, mid, enviado_em):
    envio = c.execute("INSERT INTO envios (tipo, usuario_id, remetente, para, copia, assunto, enviado_em) "
                      "VALUES ('espelho', ?, 'eng@exemplo.com.br', '[]', '[]', 'Espelho', ?)", (uid, enviado_em)).lastrowid
    c.execute("INSERT INTO envio_medicoes (envio_id, medicao_id) VALUES (?,?)", (envio, mid))


@pytest.fixture
def cenario(conn):
    c = conn
    uid = auth.criar_usuario(c, "Engenharia", "eng@exemplo.com.br", "senha-forte-123", "admin")
    sinfra = _orgao(c, "sinfra-suef2", "SINFRA - SUEF II", "sinfra")
    mtpar = _orgao(c, "mtpar", "MT Participações e Projetos S.A. - MTPAR", "mtpar")
    ids = {k: _obra(c, f"Obra {k.upper()}", sinfra) for k in ("a", "c", "d", "f", "g", "h", "k", "x")}
    ids["b"] = _obra(c, "Obra B", sinfra, percentual_direito_bp=5000)                       # consorcio: cota de 50%
    ids["m"] = _obra(c, "Obra M", mtpar)
    ids["p"] = _obra(c, "Obra P", sinfra, passos_medicao=json.dumps(["espelhos", "notas", "pagamento"]))
    hist = _obra(c, "Obra Hist", sinfra, estado="encerrado")
    # o prazo da SINFRA (docs/adr/0007): cinco recebidas em doze meses, com 10, 20, 30, 30 e 40 dias -> 30 dias
    for n, (protocolo, recebida) in enumerate((("2026-05-01", "2026-05-11"), ("2026-05-01", "2026-05-21"),
                                               ("2026-05-01", "2026-05-31"), ("2026-06-01", "2026-07-01"),
                                               ("2026-06-01", "2026-07-11")), start=1):
        _medicao(c, hist, n, "recebida", "2026-04", pedido=1000, protocolo=protocolo, recebida_em=recebida)

    # --- a competencia do quadro (outubro)
    # A: execucao + reajuste com o espelho gerado em 04/11 (dia de Cuiaba) -> 10 dias uteis, critico, com a Lotufo
    ids["a5"] = _medicao(c, ids["a"], 5, "espelho_gerado", pedido=100001, aprovado=99997, planilha_enviada_em="2026-10-20",
                         atestado_em="2026-11-03")
    ids["a5r"] = _medicao(c, ids["a"], 5, "espelho_gerado", tipo="reajuste", pedido=3001, aprovado=3001)
    _espelho(c, uid, ids["a"], 5, "2026-11-04 15:00:00", ids["a5"], ids["a5r"])
    # B (consorcio): nota emitida ontem, aprovado 5% abaixo do pedido -> com a Lotufo, enviar a nota
    ids["b12"] = _medicao(c, ids["b"], 12, "nota_emitida", pedido=200003, aprovado=190000, planilha_enviada_em="2026-10-21",
                          nota_emitida_em="2026-11-17")
    # C: em analise no orgao desde 10/11 -> 6 dias uteis, vence em breve
    ids["c3"] = _medicao(c, ids["c"], 3, "planilha_enviada", pedido=70001, planilha_enviada_em="2026-11-10")
    # F: espelho enviado ao faturamento hoje (14:00 UTC = 10:00 em Cuiaba) -> com o faturamento, feito
    ids["f2"] = _medicao(c, ids["f"], 2, "espelho_enviado", pedido=40000, aprovado=40000, planilha_enviada_em="2026-10-22")
    _email_ao_faturamento(c, uid, ids["f2"], "2026-11-18 14:00:00")
    # G: protocolada em 01/10 -> esperada em 31/10, alem do prazo do orgao; aprovado acima do pedido
    ids["g9"] = _medicao(c, ids["g"], 9, "protocolada", pedido=50000, aprovado=50010, planilha_enviada_em="2026-09-20",
                         protocolo="2026-10-01")
    # H: protocolada em 10/11 -> esperada em 10/12, dentro do prazo
    ids["h4"] = _medicao(c, ids["h"], 4, "protocolada", pedido=80000, aprovado=80000, planilha_enviada_em="2026-10-23",
                         protocolo="2026-11-10")
    # K: recebida
    ids["k7"] = _medicao(c, ids["k"], 7, "recebida", pedido=60000, aprovado=60000, planilha_enviada_em="2026-10-10",
                         recebida_em="2026-11-10")
    # M (MT-PAR): passo do boletim sem planilha enviada -> com a Lotufo, sem marco
    ids["m8"] = _medicao(c, ids["m"], 8, "planilha_gerada", pedido=90000)
    # P: obra sem o passo "Envio da nota": a nota emitida ja' espera o pagamento, sem protocolo e sem prazo
    ids["p1"] = _medicao(c, ids["p"], 1, "nota_emitida", pedido=30000, nota_emitida_em="2026-11-12")
    # --- competencias anteriores
    ids["a4"] = _medicao(c, ids["a"], 4, "nota_emitida", "2026-09", pedido=11111, aprovado=11111, planilha_enviada_em="2026-09-20",
                         nota_emitida_em="2026-11-03")
    ids["c2"] = _medicao(c, ids["c"], 2, "planilha_enviada", "2026-08", pedido=22222, planilha_enviada_em="2026-11-16")
    ids["g8"] = _medicao(c, ids["g"], 8, "protocolada", "2026-09", pedido=33333, protocolo="2026-11-05")
    ids["x1"] = _medicao(c, ids["x"], 1, "nota_emitida", "2024-12", pedido=44444, nota_emitida_em="2025-01-10")
    ids["x0"] = _medicao(c, ids["x"], 9, "protocolada", "2024-11", pedido=55555, protocolo="2024-12-10")
    c.commit()
    return ids


def _linhas(f):
    return {x["medicao_id"]: x for g in f["grupos"] for x in g["linhas"]}


def test_com_quem_sai_do_passo_e_a_mtpar_sem_envio_fica_com_a_lotufo():
    assert [fila_medicoes.com_quem(n, "nota_emitida") for n in range(1, 7)] == [
        "lotufo", "lotufo", "lotufo", "faturamento", "lotufo", "orgao"]
    assert fila_medicoes.com_quem(2, "planilha_enviada") == "orgao"
    assert fila_medicoes.com_quem(2, "planilha_gerada") == "lotufo"


def test_acao_so_existe_quando_a_vez_e_de_quem_opera():
    assert fila_medicoes.acao(1, "planilha_gerada") == "enviar_planilha"
    assert fila_medicoes.acao(2, "planilha_gerada") == "registrar_boletim"
    assert fila_medicoes.acao(3, "boletim_recebido") == "gerar_espelho"
    assert fila_medicoes.acao(3, "espelho_gerado") == "enviar_espelho"
    assert fila_medicoes.acao(5, "nota_emitida") == "enviar_nota"
    assert [fila_medicoes.acao(n, e) for n, e in ((2, "planilha_enviada"), (4, "espelho_enviado"), (6, "protocolada"))] == [None] * 3


@pytest.mark.parametrize("desde,dias,situacao", [
    ("2026-11-18", 0, "feito"),        # o evento foi hoje
    ("2026-11-12", 4, "andamento"),    # 12, 13, 16 e 17
    ("2026-11-11", 5, "breve"),
    ("2026-11-05", 9, "breve"),
    ("2026-11-04", 10, "critico"),
    ("2026-10-30", 12, "critico"),     # 02/11 (segunda) e' feriado e nao conta
])
def test_parada_conta_dias_uteis_com_os_limites_do_siga(desde, dias, situacao):
    p = fila_medicoes._parada(datetime.date.fromisoformat(desde), HOJE, 3, None, None)
    assert (p["dias_uteis"], p["situacao"], p["hoje"]) == (dias, situacao, desde == "2026-11-18")
    assert p["prazo_orgao_dias"] is None and p["esperada"] is None and p["alem_do_prazo"] is False


def test_parada_no_pagamento_so_e_critica_alem_do_prazo_do_orgao():
    protocolo = datetime.date(2026, 10, 1)
    dentro = fila_medicoes._parada(protocolo, HOJE, 6, datetime.date(2026, 11, 30), 60)
    assert (dentro["situacao"], dentro["alem_do_prazo"], dentro["esperada"], dentro["prazo_orgao_dias"]) == (
        "andamento", False, "2026-11-30", 60)
    alem = fila_medicoes._parada(protocolo, HOJE, 6, datetime.date(2026, 11, 17), 47)
    assert (alem["situacao"], alem["alem_do_prazo"]) == ("critico", True)
    # no dia esperado ainda nao passou; sem prazo do orgao, espera sem alerta
    assert fila_medicoes._parada(protocolo, HOJE, 6, HOJE, 48)["situacao"] == "andamento"
    assert fila_medicoes._parada(protocolo, HOJE, 6, None, None)["situacao"] == "andamento"
    assert fila_medicoes._parada(None, HOJE, 3, None, None) == {
        "desde": None, "dias_uteis": None, "hoje": False, "situacao": None, "prazo_orgao_dias": None, "esperada": None,
        "alem_do_prazo": False}


def test_fila_agrupa_por_quem_age_da_mais_parada_para_a_menos(conn, cenario):
    ids = cenario
    f = fila_medicoes.fila(conn, HOJE, MES)
    assert [g["com_quem"] for g in f["grupos"]] == ["lotufo", "faturamento", "orgao"]
    por = {g["com_quem"]: [x["medicao_id"] for x in g["linhas"]] for g in f["grupos"]}
    # com a Lotufo: 10 dias uteis, 1 dia util e, por ultimo, a sem marco
    assert por["lotufo"] == [ids["a5"], ids["b12"], ids["m8"]]
    assert por["faturamento"] == [ids["f2"]]
    # com o orgao: 32 dias uteis (protocolo de 01/10), 6, 6 e 4; no empate, o evento mais antigo
    assert por["orgao"] == [ids["g9"], ids["c3"], ids["h4"], ids["p1"]]
    assert f["limites"] == {"dias_atencao": 5, "dias_critico": 10, "diferenca_critica_por_mil": 5}


def test_linha_traz_passos_da_obra_tempo_parado_e_o_proximo_ato(conn, cenario):
    ids = cenario
    linhas = _linhas(fila_medicoes.fila(conn, HOJE, MES))
    a = linhas[ids["a5"]]
    assert a["titulo"] == "5ª Medição + Reajuste" and a["medicao_ids"] == [ids["a5"], ids["a5r"]]
    assert (a["obra"], a["contratante"], a["orgao_sub"]) == ("Obra A", "SINFRA", "SUEF II")
    assert a["passo"] == {"numero": 3, "nome": "Espelhos", "posicao": 3, "total": 6}
    assert [p["situacao"] for p in a["passos"]] == ["feito", "feito", "atual", "futuro", "futuro", "futuro"]
    assert a["parada"]["desde"] == "2026-11-04" and a["parada"]["dias_uteis"] == 10 and a["parada"]["situacao"] == "critico"
    assert a["acao"] == "enviar_espelho"
    # a obra sem planilha, analise e envio da nota: tres passos, e a nota emitida ja' espera o pagamento
    p = linhas[ids["p1"]]
    assert [x["nome"] for x in p["passos"]] == ["Espelhos", "Notas", "Pagamento"]
    assert p["passo"] == {"numero": 6, "nome": "Pagamento", "posicao": 3, "total": 3}
    assert p["com_quem"] == "orgao" and p["acao"] is None
    assert p["parada"] == {"desde": "2026-11-12", "dias_uteis": 4, "hoje": False, "situacao": "andamento",
                           "prazo_orgao_dias": 30, "esperada": None, "alem_do_prazo": False}
    # a MT-PAR comeca no passo do boletim, que e' da Lotufo enquanto nada foi ao orgao; sem marco, sem dias
    m = linhas[ids["m8"]]
    assert m["passo"] == {"numero": 2, "nome": "Análise do órgão", "posicao": 1, "total": 5}
    assert (m["com_quem"], m["acao"], m["parada"]["dias_uteis"], m["parada"]["situacao"]) == ("lotufo", "registrar_boletim", None, None)
    # o e-mail ao faturamento saiu hoje
    assert linhas[ids["f2"]]["parada"]["hoje"] is True and linhas[ids["f2"]]["parada"]["situacao"] == "feito"
    assert linhas[ids["c3"]]["parada"]["situacao"] == "breve" and linhas[ids["c3"]]["acao"] is None


def test_pagamento_usa_o_prazo_do_orgao_para_o_critico(conn, cenario):
    ids = cenario
    linhas = _linhas(fila_medicoes.fila(conn, HOJE, MES))
    g, h = linhas[ids["g9"]]["parada"], linhas[ids["h4"]]["parada"]
    assert (g["prazo_orgao_dias"], g["esperada"], g["alem_do_prazo"], g["situacao"]) == (30, "2026-10-31", True, "critico")
    assert (h["prazo_orgao_dias"], h["esperada"], h["alem_do_prazo"], h["situacao"]) == (30, "2026-12-10", False, "andamento")
    # fora do pagamento o prazo do orgao nao aparece: ele conta do protocolo ao recebimento (docs/adr/0007)
    assert linhas[ids["c3"]]["parada"]["prazo_orgao_dias"] is None


def test_diferenca_no_valor_cheio_com_a_regra_do_fechamento(conn, cenario):
    ids = cenario
    f = fila_medicoes.fila(conn, HOJE, MES)
    linhas = _linhas(f)
    # ate' R$ 0,05 e' arredondamento do orgao: igual (o reajuste, igual ao centavo, soma na mesma linha)
    a = linhas[ids["a5"]]
    assert (a["pedido_centavos"], a["aprovado_centavos"]) == (103002, 102998)
    assert (a["pedido_do_aprovado_centavos"], a["abaixo_do_pedido_centavos"], a["acima_do_pedido_centavos"]) == (103002, 0, 0)
    # consorcio com cota de 50%: a tela mostra o valor cheio da medicao, nao a cota
    b = linhas[ids["b12"]]
    assert (b["pedido_centavos"], b["aprovado_centavos"], b["abaixo_do_pedido_centavos"]) == (200003, 190000, 10003)
    assert (b["aprovado_com_pedido_centavos"], b["pedido_do_aprovado_centavos"]) == (190000, 200003)
    # acima do pedido: so' na linha da medicao
    assert (linhas[ids["g9"]]["abaixo_do_pedido_centavos"], linhas[ids["g9"]]["acima_do_pedido_centavos"]) == (0, 10)
    # em analise nao ha' o que comparar
    c = linhas[ids["c3"]]
    assert c["aprovado_centavos"] is None and c["abaixo_do_pedido_centavos"] is None and c["pedido_do_aprovado_centavos"] is None
    # o mes: o pedido e o aprovado de todas as medicoes da competencia; a diferenca, so' das que tem os dois, e so' o corte
    n = f["numeros"]
    assert n["pedido_centavos"] == 100001 + 3001 + 200003 + 70001 + 40000 + 50000 + 80000 + 60000 + 90000 + 30000
    assert n["aprovado_centavos"] == 99997 + 3001 + 190000 + 40000 + 50010 + 80000 + 60000
    assert n["aprovado_com_pedido_centavos"] == n["aprovado_centavos"]
    assert n["pedido_do_aprovado_centavos"] == 100001 + 3001 + 200003 + 40000 + 50000 + 80000 + 60000
    assert n["abaixo_do_pedido_centavos"] == 10003 and "acima_do_pedido_centavos" not in n


def test_a_conta_da_diferenca_e_uma_so_no_cheio_aqui_e_na_cota_no_fechamento():
    from app import fechamento
    # sem `pct`, o valor cheio (esta tela); com a cota de 33,33%, o Fechamento. Centavo impar: a cota arredonda uma vez
    assert fechamento.aprovado_contra_o_pedido("nota_emitida", 200003, 190000) == {
        "aprovado_com_pedido_centavos": 190000, "pedido_do_aprovado_centavos": 200003, "abaixo_do_pedido_centavos": 10003,
        "acima_do_pedido_centavos": 0}
    assert fechamento.aprovado_contra_o_pedido("nota_emitida", 200003, 190000, 3333) == {
        "aprovado_com_pedido_centavos": 63327, "pedido_do_aprovado_centavos": 66661, "abaixo_do_pedido_centavos": 3334,
        "acima_do_pedido_centavos": 0}
    # a tolerancia de R$ 0,05 e' do valor cheio; antes do boletim, ou sem um dos valores, nao ha' o que comparar
    assert fechamento.aprovado_contra_o_pedido("recebida", 100005, 100000)["abaixo_do_pedido_centavos"] == 0
    assert fechamento.aprovado_contra_o_pedido("recebida", 100006, 100000)["abaixo_do_pedido_centavos"] == 6
    assert fechamento.aprovado_contra_o_pedido("recebida", 100000, 100006)["acima_do_pedido_centavos"] == 6
    assert fechamento.aprovado_contra_o_pedido("planilha_enviada", 100000, 90000) is None
    assert fechamento.aprovado_contra_o_pedido("recebida", 100000, None) is None


def test_numeros_da_faixa(conn, cenario):
    n = fila_medicoes.fila(conn, HOJE, MES)["numeros"]
    assert n["com"] == {
        "lotufo": {"quantidade": 3, "criticas": 1, "breves": 0, "alem_do_prazo": 0},
        "faturamento": {"quantidade": 1, "criticas": 0, "breves": 0, "alem_do_prazo": 0},
        "orgao": {"quantidade": 4, "criticas": 1, "breves": 1, "alem_do_prazo": 1}}
    assert (n["concluidas"], n["sem_medicao"]) == (1, 2)


def test_concluidas_e_obras_sem_medicao(conn, cenario):
    ids = cenario
    f = fila_medicoes.fila(conn, HOJE, MES)
    assert f["concluidas"] == [{"contrato_id": ids["k"], "obra": "Obra K", "medicao_id": ids["k7"], "titulo": "7ª Medição",
                                "recebida_em": "2026-11-10"}]
    # a obra ativa sem medicao na competencia (a que so' tem medicao de 2024 tambem); a encerrada nao entra
    assert f["sem_medicao"] == [{"contrato_id": ids["d"], "obra": "Obra D", "contratante": "SINFRA"},
                                {"contrato_id": ids["x"], "obra": "Obra X", "contratante": "SINFRA"}]
    assert {o["obra"] for o in f["obras"]} >= {"Obra D", "Obra X"}


def test_grupo_vazio_nao_aparece(conn, cenario):
    conn.execute("DELETE FROM envio_medicoes")
    conn.execute("UPDATE medicoes SET estado='nota_emitida', nota_emitida_em='2026-11-17' WHERE id=?", (cenario["f2"],))
    conn.commit()
    f = fila_medicoes.fila(conn, HOJE, MES)
    assert [g["com_quem"] for g in f["grupos"]] == ["lotufo", "orgao"]
    assert f["numeros"]["com"]["faturamento"]["quantidade"] == 0


def test_quadro_por_contratante_com_os_dias_no_passo_da_vez_e_a_diferenca(conn, cenario):
    ids = cenario
    quadro = fila_medicoes.fila(conn, HOJE, MES)["quadro"]
    # o contratante com mais obras primeiro; as obras sem medicao sairam da matriz
    assert [(g["contratante"], [x["obra"] for x in g["linhas"]]) for g in quadro] == [
        ("SINFRA", ["Obra A", "Obra B", "Obra C", "Obra F", "Obra G", "Obra H", "Obra K", "Obra P"]), ("MTPAR", ["Obra M"])]
    sinfra = quadro[0]
    assert sinfra["abaixo_do_pedido_centavos"] == 10003 and "acima_do_pedido_centavos" not in sinfra
    assert sinfra["pedido_centavos"] == 100001 + 3001 + 200003 + 70001 + 40000 + 50000 + 80000 + 60000 + 30000
    a = sinfra["linhas"][0]
    atual = next(p for p in a["passos"] if p["situacao"] == "atual")
    assert atual["medicao_id"] == ids["a5"] and atual["parada"]["dias_uteis"] == 10 and atual["parada"]["situacao"] == "critico"
    assert all(p["parada"] is None for p in a["passos"] if p["situacao"] != "atual")
    assert (a["pedido_centavos"], a["aprovado_centavos"], a["abaixo_do_pedido_centavos"]) == (103002, 102998, 0)
    g = next(x for x in sinfra["linhas"] if x["obra"] == "Obra G")
    assert g["acima_do_pedido_centavos"] == 10 and next(p for p in g["passos"] if p["situacao"] == "atual")["parada"]["alem_do_prazo"]
    assert quadro[1]["abaixo_do_pedido_centavos"] is None      # a MT-PAR nao tem medicao comparavel no mes
    assert all("_ms" not in x for grupo in quadro for x in grupo["linhas"])


def test_meses_anteriores_so_o_que_pede_acao_o_resto_vira_contagem(conn, cenario):
    ids = cenario
    ant = fila_medicoes.fila(conn, HOJE, MES)["anteriores"]
    # da mais parada para a menos: a nota a enviar (11 dias uteis) e a planilha em analise (2)
    assert [(x["medicao_id"], x["competencia"], x["com_quem"]) for x in ant["linhas"]] == [
        (ids["a4"], "2026-09", "lotufo"), (ids["c2"], "2026-08", "orgao")]
    assert ant["linhas"][0]["pedido_centavos"] == 11111 and ant["linhas"][0]["parada"]["dias_uteis"] == 11
    # a que so' espera o pagamento e as de antes de 2025 nao sao linha
    assert (ant["esperam_pagamento"], ant["antes_do_ano_inicial"], ant["ano_inicial"]) == (1, 2, "2025")
    # a competencia do quadro nao e' "anterior": em setembro so' sobra a de agosto
    assert [x["medicao_id"] for x in fila_medicoes.fila(conn, HOJE, "2026-09")["anteriores"]["linhas"]] == [ids["c2"]]


def test_rota_da_fila(client_admin):
    r = client_admin.get("/api/medicoes/fila?mes=2026-10")
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"hoje", "mes", "obras", "limites", "numeros", "grupos", "concluidas", "sem_medicao", "quadro",
                             "anteriores"}
    assert r.json()["mes"] == "2026-10" and r.json()["grupos"] == [] and r.json()["quadro"] == []
    assert r.json()["anteriores"] == {"linhas": [], "esperam_pagamento": 0, "antes_do_ano_inicial": 0, "ano_inicial": "2025"}
    assert r.json()["numeros"]["abaixo_do_pedido_centavos"] is None
    assert client_admin.get("/api/medicoes/fila?mes=2026-13").status_code == 422
    # a rota fixa nao cai em /api/medicoes/{medicao_id}
    assert client_admin.get("/api/medicoes/999").status_code == 404


def test_rota_da_fila_exige_login(client):
    assert client.get("/api/medicoes/fila").status_code == 401
