"""Pagina Medicoes com abas (09/10/2026): situacao por estado, marco de cada situacao (nunca o criado_em), a linha
unica de medicao + reajuste, o contratante (sigla e sub-orgao) e as obras sem medicao aberta (prevista nao conta)."""
import datetime
import json

import pytest

from app import auth, db, medicoes

HOJE = datetime.date(2026, 10, 9)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn()
    db.migrate(c)
    yield c
    c.close()


def _orgao(c, chave, nome, familia):
    return c.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES (?,?,?,'{}')",
                     (chave, nome, familia)).lastrowid


def _obra(c, nome, orgao_id, estado="ativo", orgao_texto="ÓRGÃO"):
    return c.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos, estado, "
                     "nome_curto, orgao_id) VALUES (?,?,?,0,?,?,?)",
                     (orgao_texto, f"IC {nome}", nome, estado, nome, orgao_id)).lastrowid


def _medicao(c, cid, numero, tipo, estado, valor=None, criado_em="2026-01-01 10:00:00", **datas):
    cols = ", ".join(["contrato_id", "numero", "tipo", "competencia", "estado", "valor_protocolado_centavos",
                      "criado_em", *datas])
    vals = [cid, numero, tipo, "2026-09", estado, valor, criado_em, *datas.values()]
    return c.execute(f"INSERT INTO medicoes ({cols}) VALUES ({','.join('?' * len(vals))})", vals).lastrowid


@pytest.fixture
def cenario(conn):
    c = conn
    uid = auth.criar_usuario(c, "Leo", "leo@l.com", "senha-forte-123", "admin")
    suef2 = _orgao(c, "sinfra-suef2", "SINFRA - SUEF II", "sinfra")
    supu = _orgao(c, "sinfra-supu", "SINFRA - SUPU (Pavimentação Urbana)", "sinfra")
    mtpar = _orgao(c, "mtpar", "MT Participações e Projetos S.A. - MTPAR", "mtpar")
    vg = _orgao(c, "pref-vg", "Prefeitura de Várzea Grande - Secretaria Municipal de Saúde", "prefeitura")
    ids = {
        "a": _obra(c, "Obra A", suef2), "b": _obra(c, "Obra B", mtpar), "c": _obra(c, "Obra C", supu),
        "d": _obra(c, "Obra D", vg), "e": _obra(c, "Obra E", mtpar, estado="suspenso"),
        "f": _obra(c, "Obra F", None, orgao_texto="Órgão sem cadastro"),
    }
    # A: medicao + reajuste com a nota emitida (uma linha so', marco mais antigo) e um projeto em linha propria
    ids["a24"] = _medicao(c, ids["a"], 24, "execucao", "nota_emitida", 100000, nota_emitida_em="2026-10-03")
    ids["a24r"] = _medicao(c, ids["a"], 24, "reajuste", "nota_emitida", 2500, nota_emitida_em="2026-10-01")
    ids["a1p"] = _medicao(c, ids["a"], 1, "projeto", "nota_emitida", 7000, nota_emitida_em="2026-10-08")
    # B: medicao protocolada (aguardando pagamento) e o reajuste do mesmo numero em OUTRA situacao: duas linhas
    ids["b15"] = _medicao(c, ids["b"], 15, "execucao", "protocolada", 300000)
    c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, '2026-09-01', 'manual')", (ids["b15"],))
    ids["b15r"] = _medicao(c, ids["b"], 15, "reajuste", "espelho_enviado", 4000)
    envio = c.execute("INSERT INTO envios (tipo, usuario_id, remetente, para, copia, assunto, enviado_em) "
                      "VALUES ('espelho', ?, 'leo@l.com', '[]', '[]', 'Espelho', '2026-10-08 02:00:00')", (uid,)).lastrowid
    c.execute("INSERT INTO envio_medicoes (envio_id, medicao_id) VALUES (?,?)", (envio, ids["b15r"]))
    # C: espelho gerado; o espelho substituido (mais antigo) nao e' o marco, o vigente e'
    ids["c3"] = _medicao(c, ids["c"], 3, "execucao", "espelho_gerado", 5000)
    for versao, situacao, criado in ((1, "substituido", "2026-09-20 15:00:00"), (2, "vigente", "2026-10-09 15:00:00")):
        eid = c.execute("INSERT INTO espelhos (contrato_id, numero, competencia, versao, situacao, entradas, saidas, "
                        "regra_sha256, criado_por, criado_em) VALUES (?,3,'2026-09',?,?,'{}','[]','x',?,?)",
                        (ids["c"], versao, situacao, uid, criado)).lastrowid
        c.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id) VALUES (?,?)", (eid, ids["c3"]))
    # D: so' a prevista do cronograma -> sem medicao aberta, com a prevista para o "Iniciar processo"
    ids["d2"] = _medicao(c, ids["d"], 2, "execucao", "prevista")
    ids["d1"] = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
                          "VALUES (?, 1, 'execucao', '2026-08', 'prevista')", (ids["d"],)).lastrowid
    # F: espelho enviado sem e-mail registrado: o criado_em NAO vira marco
    ids["f1"] = _medicao(c, ids["f"], 1, "execucao", "espelho_enviado", 900, criado_em="2026-09-01 10:00:00")
    c.commit()
    return ids


def test_situacao_cobre_o_mesmo_em_andamento_do_proximo_passo():
    assert set(medicoes.SITUACAO) == set(medicoes.PROXIMO_PASSO)
    assert set(medicoes.SITUACAO.values()) == set(medicoes.ORDEM_SITUACAO)


def test_estados_novos_do_motor_entram_na_lista_antes_do_espelho(conn, cenario):
    """#291 (spec motores §2.1): planilha gerada/enviada e boletim recebido sao situacoes proprias, contadas e
    ordenadas antes do espelho, cada uma com o marco do seu estado."""
    ids = cenario
    _medicao(conn, ids["a"], 30, "execucao", "boletim_recebido", 1000)
    _medicao(conn, ids["b"], 31, "execucao", "planilha_enviada", 2000, planilha_enviada_em="2026-10-07")
    _medicao(conn, ids["d"], 32, "execucao", "planilha_gerada", 3000)
    conn.commit()
    r = medicoes.resumo(conn, HOJE)
    assert [x["situacao"] for x in r["linhas"]][:3] == ["planilha-gerada", "planilha-enviada", "boletim-recebido"]
    assert r["contagens"]["planilha-gerada"] == r["contagens"]["planilha-enviada"] == r["contagens"]["boletim-recebido"] == 1
    env = next(x for x in r["linhas"] if x["situacao"] == "planilha-enviada")
    assert env["dias"] == 2 and env["proximo_passo"] == "Espelhos"   # a obra B (MTPAR) nao tem planilha e carta: comeca em Espelhos
    assert [x["estado"] for x in medicoes.em_andamento(conn, estado="boletim_recebido")] == ["boletim_recebido"]
    # "desde" usa os marcos novos (nao o criado_em); a planilha gerada conta da 1a versao
    assert {m["estado"]: m["desde"] for m in medicoes.em_andamento(conn)}["planilha_enviada"] == "2026-10-07"
    assert medicoes.rotulo_estado("planilha_gerada") == "com planilha/carta gerada"


def test_protocolada_com_atesto_posterior_mantem_o_desde(conn, cenario):
    ids = cenario
    mid = _medicao(conn, ids["a"], 40, "execucao", "protocolada", 1000, atestado_em="2026-10-18")
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, '2026-10-01', 'manual')", (mid,))
    conn.commit()
    assert {m["id"]: m["desde"] for m in medicoes.em_andamento(conn)}[mid] == "2026-10-01"


def test_contratante_sigla_e_sub_orgao():
    assert medicoes.contratante("sinfra", "sinfra-supu", "SINFRA - SUPU (Pavimentação Urbana)", None) == ("SINFRA", "SUPU")
    assert medicoes.contratante("sinfra", "sinfra-sagpm", "SINFRA - SAGPM / SUOESP", None) == ("SINFRA", "SAGPM / SUOESP")
    assert medicoes.contratante("prefeitura", "rota-do-oeste", "Concessionária Rota do Oeste S.A. (privado)", None) \
        == ("Rota do Oeste", None)
    assert medicoes.contratante("prefeitura", "pref-vg", "Prefeitura de Várzea Grande", None) == ("Pref. Várzea Grande", None)
    # sem sigla conhecida: o nome do cadastro; sem cadastro: o texto do contrato
    assert medicoes.contratante("prefeitura", "outra", "Prefeitura X", None) == ("Prefeitura X", None)
    assert medicoes.contratante(None, None, None, "Órgão antigo") == ("Órgão antigo", None)


def test_resumo_linhas_marcos_e_contagens(conn, cenario):
    ids = cenario
    r = medicoes.resumo(conn, HOJE)
    linhas = [(x["obra"], x["titulo"], x["situacao"], x["valor_centavos"], x["dias"]) for x in r["linhas"]]
    assert linhas == [
        ("Obra C", "3ª Medição", "faturamento", 5000, 0),               # o espelho vigente, de hoje
        ("Obra B", "Reajuste da 15ª Medição", "aguardando-nota", 4000, 2),  # 02:00 UTC do dia 8 = dia 7 em Cuiaba
        ("Obra F", "1ª Medição", "aguardando-nota", 900, None),         # sem e-mail: sem marco, nunca o criado_em
        ("Obra A", "24ª Medição + Reajuste", "enviar-nota", 102500, 8),  # marco mais antigo dos dois
        ("Obra A", "1ª Medição de Projeto", "enviar-nota", 7000, 1),
        ("Obra B", "15ª Medição", "aguardando-pagamento", 300000, 38),
    ]
    par = r["linhas"][3]
    assert par["medicao_id"] == ids["a24"] and par["medicao_ids"] == [ids["a24"], ids["a24r"]]
    assert par["contratante"] == "SINFRA" and par["orgao_sub"] == "SUEF II" and par["marco"] == "2026-10-01"
    assert par["proximo_passo"] == "Envio da nota" and par["passo"] == {"numero": 5, "nome": "Envio da nota"}
    assert {x["competencia"] for x in r["linhas"]} == {"2026-09"}   # #155: a competencia da medicao (AAAA-MM)
    assert r["contagens"] == {"sem-medicao": 1, "planilha-gerada": 0, "planilha-enviada": 0, "boletim-recebido": 0,
                              "faturamento": 1, "aguardando-nota": 2, "enviar-nota": 2, "aguardando-pagamento": 1,
                                  "iniciar": 5, "em-andamento": 6}   # #507: contagens do menu
    # obras ativas (a suspensa fica fora); a D so' tem prevista: sem medicao aberta, com a prevista mais antiga
    obras = {o["obra"]: o for o in r["obras"]}
    assert set(obras) == {"Obra A", "Obra B", "Obra C", "Obra D", "Obra F"}
    assert obras["Obra D"]["aberta"] is False and obras["Obra D"]["prevista_id"] == ids["d1"]
    assert obras["Obra D"]["contratante"] == "Pref. Várzea Grande"
    assert obras["Obra F"]["contratante"] == "Órgão sem cadastro" and obras["Obra F"]["aberta"] is True
    assert obras["Obra A"]["prevista_id"] is None


def test_aba_aguardando_pagamento_conta_as_notas_da_tabela(conn, cenario):
    """N-01 (10/10/2026): a aba contava linhas (medicao + reajuste viram uma) e a tabela, notas; agora as duas
    contam as medicoes protocoladas, uma por nota."""
    from app import notas_envio
    ids = cenario
    _medicao(conn, ids["b"], 16, "execucao", "protocolada", 1000)
    _medicao(conn, ids["b"], 16, "reajuste", "protocolada", 100)
    conn.commit()
    r = medicoes.resumo(conn, HOJE)
    assert sum(1 for x in r["linhas"] if x["situacao"] == "aguardando-pagamento") == 2      # o par vira uma linha
    assert r["contagens"]["aguardando-pagamento"] == len(notas_envio.aguardando_pagamento(conn)) == 3


def test_obra_sem_medicao_traz_ultima_ha_quanto_tempo_prevista_e_proxima(conn):
    """#154: a aba "Sem medição aberta" mostra a última medição (nº e competência), há quanto tempo (desde o FIM da
    competência), a prevista do cronograma e o nº da próxima. Sem medição anterior: tudo nulo e próxima = 1."""
    c = conn
    sinfra = _orgao(c, "sinfra-suef1", "SINFRA - SUEF I", "sinfra")
    a, b, d, e = (_obra(c, n, sinfra) for n in ("A", "B", "D", "E"))
    for cid, numero, comp, estado in ((a, 22, "2025-12", "recebida"), (a, 23, "2026-01", "recebida"),
                                      (a, 24, "2026-09", "prevista"), (a, 25, "2026-10", "prevista"),
                                      (b, 5, "2026-02", "recebida"), (b, 6, "2026-03", "cancelada"),
                                      (d, 3, "2026-10", "recebida")):
        c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) VALUES (?,?,'execucao',?,?)",
                  (cid, numero, comp, estado))
    # B mista: a projeto 9 é a última (mais recente), mas projeto é série própria: a próxima de execução segue a
    # execução (a cancelada 6 ocupa o número) e vale 7
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
              "VALUES (?,9,'projeto','2026-08','recebida')", (b,))
    # G mista sem cancelada: execução 5 e projeto 9 -> próxima de execução = 6
    g = _obra(c, "G", sinfra)
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
              "VALUES (?,5,'execucao','2026-02','recebida')", (g,))
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
              "VALUES (?,9,'projeto','2026-08','recebida')", (g,))
    # F só mede projeto (ex.: Terminais BRT): última de projeto e a próxima segue a série de projeto
    f = _obra(c, "F", sinfra)
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
              "VALUES (?,2,'projeto','2026-07','recebida')", (f,))
    # o reajuste repete o número da execução e não conta
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
              "VALUES (?,23,'reajuste','2026-02','recebida')", (a,))
    c.commit()
    obras = {o["obra"]: o for o in medicoes.resumo(conn, HOJE)["obras"]}
    assert obras["A"]["ultima"] == {"numero": 23, "tipo": "execucao", "competencia": "2026-01"}
    assert obras["A"]["ha_dias"] == (HOJE - datetime.date(2026, 1, 31)).days == 251
    assert obras["A"]["prevista"] == {"numero": 24, "tipo": "execucao", "competencia": "2026-09"}
    assert obras["A"]["proxima"] == 24 and obras["A"]["proxima_tipo"] == "execucao"
    assert obras["B"]["ultima"] == {"numero": 9, "tipo": "projeto", "competencia": "2026-08"} and obras["B"]["ha_dias"] == 39
    assert obras["B"]["prevista"] is None and obras["B"]["proxima"] == 7 and obras["B"]["proxima_tipo"] == "execucao"
    assert obras["G"]["proxima"] == 6 and obras["G"]["proxima_tipo"] == "execucao"
    assert obras["F"]["ultima"] == {"numero": 2, "tipo": "projeto", "competencia": "2026-07"}
    assert obras["F"]["proxima"] == 3 and obras["F"]["proxima_tipo"] == "projeto"
    # competência ainda em curso: "hoje" (0 dia), como no protótipo; "—" (nulo) só sem medição anterior
    assert obras["D"]["ultima"]["numero"] == 3 and obras["D"]["ha_dias"] == 0
    assert obras["E"]["ultima"] is None and obras["E"]["ha_dias"] is None
    assert obras["E"]["prevista"] is None and obras["E"]["proxima"] == 1 and obras["E"]["proxima_tipo"] == "execucao"


def test_prevista_da_aba_e_a_mesma_que_o_iniciar_abre(conn):
    """O rótulo "Iniciar a Nª medição" e o link (prevista_id) vêm da mesma medição prevista."""
    c = conn
    a = _obra(c, "A", _orgao(c, "sinfra-suef1", "SINFRA - SUEF I", "sinfra"))
    pid = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
                    "VALUES (?,2,'projeto','2026-02','prevista')", (a,)).lastrowid
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
              "VALUES (?,5,'execucao','2026-03','prevista')", (a,))
    c.commit()
    o = medicoes.resumo(conn, HOJE)["obras"][0]
    assert o["prevista_id"] == pid and o["prevista"] == {"numero": 2, "tipo": "projeto", "competencia": "2026-02"}
    assert o["proxima"] == 2 and o["proxima_tipo"] == "projeto"
    # competência que termina hoje já conta: "hoje"
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
              "VALUES (?,1,'execucao','2026-09','recebida')", (a,))
    c.commit()
    assert medicoes.resumo(conn, datetime.date(2026, 9, 30))["obras"][0]["ha_dias"] == 0


def test_prevista_da_aba_ignora_reajuste(conn):
    """O reajuste (mesmo numero/competencia da execucao) nunca aparece como a medicao prevista da obra."""
    c = conn
    a = _obra(c, "A", _orgao(c, "sinfra-suef1", "SINFRA - SUEF I", "sinfra"))
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
              "VALUES (?,3,'reajuste','2026-01','prevista')", (a,))
    c.commit()
    o = medicoes.resumo(conn, HOJE)["obras"][0]
    assert o["prevista_id"] is None and o["prevista"] is None
    pid = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
                    "VALUES (?,4,'execucao','2026-02','prevista')", (a,)).lastrowid
    c.commit()
    o = medicoes.resumo(conn, HOJE)["obras"][0]
    assert o["prevista_id"] == pid and o["prevista"]["tipo"] == "execucao"


def test_prevista_da_aba_desempata_por_competencia_tipo_numero_e_id(conn):
    """Mesma competencia: execucao antes de projeto; mesmo tipo: menor numero."""
    c = conn
    a = _obra(c, "A", _orgao(c, "sinfra-suef1", "SINFRA - SUEF I", "sinfra"))
    ins = lambda n, t, comp: c.execute(  # noqa: E731
        "INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) VALUES (?,?,?,?,'prevista')",
        (a, n, t, comp)).lastrowid
    ins(1, "projeto", "2026-03")
    ins(9, "execucao", "2026-03")
    esperada = ins(5, "execucao", "2026-03")
    ins(1, "execucao", "2026-04")
    c.commit()
    o = medicoes.resumo(conn, HOJE)["obras"][0]
    assert o["prevista_id"] == esperada
    assert o["prevista"] == {"numero": 5, "tipo": "execucao", "competencia": "2026-03"}


def test_rota_do_resumo(client_admin):
    r = client_admin.get("/api/medicoes/resumo")
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"hoje", "mes", "contagens", "linhas", "obras", "quadro", "anteriores"}
    # a rota fixa nao cai em /api/medicoes/{medicao_id}
    assert client_admin.get("/api/medicoes/999").status_code == 404


def test_rota_do_resumo_exige_login(client):
    assert client.get("/api/medicoes/resumo").status_code == 401


def test_resumo_obras_trazem_a_medicao_aberta_a_prevista_e_a_ultima(conn, cenario):
    """#151 (15/10/2026): a janela Iniciar processo precisa do id e do numero da aberta, do numero e da competencia
    da prevista, da ultima medicao de cada serie (a sugestao) e de saber se a obra tem serie de Projeto."""
    ids = cenario
    obras = {o["obra"]: o for o in medicoes.resumo(conn, HOJE)["obras"]}
    # A: 24 (execucao + reajuste) aberta; o reajuste nao conta como serie; Projeto 1 aberto
    a = obras["Obra A"]
    assert a["execucao"]["aberta_id"] == ids["a24"] and a["execucao"]["aberta_numero"] == 24 and a["execucao"]["aberta_passo"] == "Envio da nota"
    assert a["execucao"]["ultima"] == {"numero": 24, "competencia": "2026-09"}
    assert a["projeto"] == {"aberta_id": ids["a1p"], "aberta_numero": 1, "aberta_passo": "Envio da nota",
                            "ultima": {"numero": 1, "competencia": "2026-09"},
                            "prevista_id": None, "prevista_numero": None, "prevista_competencia": None}
    # D: so' prevista (a mais antiga, 1); a prevista nao e' "ultima"; sem Projeto
    d, de = obras["Obra D"], obras["Obra D"]["execucao"]
    assert de["prevista_numero"] == 1 and de["prevista_competencia"] == "2026-08"
    assert de["aberta_id"] is None and de["aberta_numero"] is None and de["ultima"] is None and d["projeto"] is None
    # C: so' o espelho gerado; sem prevista
    c = obras["Obra C"]["execucao"]
    assert c["prevista_numero"] is None and c["prevista_competencia"] is None and c["aberta_numero"] == 3


def test_resumo_prevista_de_projeto_nao_aparece_na_serie_de_execucao(conn, cenario):
    """#151 (revisor): cada serie tem a sua prevista; a de Projeto vai no bloco `projeto`, nunca em `Execucao`."""
    ids = cenario
    proj = conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
                            "VALUES (?, 3, 'projeto', '2026-07', 'prevista')", (ids["d"],)).lastrowid
    conn.commit()
    d = {o["obra"]: o for o in medicoes.resumo(conn, HOJE)["obras"]}["Obra D"]
    assert d["execucao"]["prevista_id"] == ids["d1"] and d["execucao"]["prevista_numero"] == 1      # a de execucao, mais antiga que a de Projeto
    assert d["projeto"]["prevista_id"] == proj and d["projeto"]["prevista_numero"] == 3
    assert d["projeto"]["prevista_competencia"] == "2026-07"
    # obra so' com prevista de Projeto: execucao sem prevista
    outra = _obra(conn, "Obra G", None)
    conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
                 "VALUES (?, 1, 'projeto', '2026-09', 'prevista')", (outra,))
    conn.commit()
    g = {o["obra"]: o for o in medicoes.resumo(conn, HOJE)["obras"]}["Obra G"]
    assert g["execucao"]["prevista_id"] is None and g["projeto"]["prevista_numero"] == 1


def test_resumo_prevista_de_reajuste_nao_e_a_da_serie_de_execucao(conn):
    """#151 (revisor, rodada 2): o reajuste lancado a mao nasce `prevista`, mas nao e' a prevista da serie de
    execucao; a janela nao pode oferecer "Começar a 3ª" abrindo o reajuste."""
    c = conn
    a = _obra(c, "A", _orgao(c, "sinfra-suef1", "SINFRA - SUEF I", "sinfra"))
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
              "VALUES (?,3,'reajuste','2026-01','prevista')", (a,))
    c.commit()
    o = medicoes.resumo(conn, HOJE)["obras"][0]
    assert o["execucao"]["prevista_id"] is None and o["execucao"]["prevista_numero"] is None
    assert o["prevista_id"] is None and o["projeto"] is None


# --- quadro do mes (#643): uma linha por obra, uma coluna por passo, na competencia pedida ---------------------

def _passos(linha):
    return {p["numero"]: (p["situacao"], p["data"], p["medicao_id"]) for p in linha["passos"]}


def test_quadro_tem_uma_linha_por_obra_ativa_e_iniciar_na_obra_sem_medicao(conn, cenario):
    ids = cenario
    quadro = {x["obra"]: x for x in medicoes.resumo(conn, HOJE, mes="2026-09")["quadro"]}
    # a suspensa sem medicao na competencia fica fora; a D so' tem prevista: sem medicao, com o Iniciar
    assert list(quadro) == ["Obra A", "Obra B", "Obra C", "Obra D", "Obra F"]
    d = quadro["Obra D"]
    assert d["iniciar"] is True and d["passos"] == [] and d["medicoes"] == []
    assert d["pedido_centavos"] is None and d["aprovado_centavos"] is None and d["contrato_id"] == ids["d"]
    assert d["contratante"] == "Pref. Várzea Grande"
    c = quadro["Obra C"]
    assert c["iniciar"] is False and c["medicoes"] == [{"id": ids["c3"], "titulo": "3ª Medição"}]
    # sem planilha/carta na medicao, a linha comeca em Espelhos (passo 3); o da vez leva a medicao
    assert _passos(c) == {3: ("atual", None, ids["c3"]), 4: ("futuro", None, None), 5: ("futuro", None, None),
                          6: ("futuro", None, None)}
    assert [p["nome"] for p in c["passos"]] == ["Espelhos", "Notas", "Envio da nota", "Pagamento"]
    # outra competencia: ninguem mediu, todas as ativas com o Iniciar
    outubro = medicoes.resumo(conn, HOJE, mes="2026-10")["quadro"]
    assert [x["obra"] for x in outubro] == ["Obra A", "Obra B", "Obra C", "Obra D", "Obra F"]
    assert all(x["iniciar"] and x["passos"] == [] for x in outubro)


def test_quadro_datas_por_passo_pedido_e_aprovado(conn, cenario):
    """As datas dos passos feitos saem do servidor (dia de Cuiaba): ultimo envio da planilha/carta, boletim, e-mail
    do espelho vigente, nota, protocolo. Pedido e aprovado em colunas proprias (centavo impar)."""
    c, ids = conn, cenario
    g = _obra(c, "Obra G", c.execute("SELECT orgao_id FROM contratos WHERE id=?", (ids["a"],)).fetchone()[0])
    mid = _medicao(c, g, 7, "execucao", "protocolada", 100001, planilha_enviada_em="2026-10-01",
                   atestado_em="2026-10-03", valor_atestado_centavos=99999, nota_emitida_em="2026-10-06")
    c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, '2026-10-07', 'manual')", (mid,))
    uid = c.execute("SELECT id FROM usuarios").fetchone()[0]
    # 02:00 UTC do dia 5 = dia 4 em Cuiaba
    envio = c.execute("INSERT INTO envios (tipo, usuario_id, remetente, para, copia, assunto, enviado_em) "
                      "VALUES ('espelho', ?, 'a@l.com', '[]', '[]', 'Espelho', '2026-10-05 02:00:00')", (uid,)).lastrowid
    eid = c.execute("INSERT INTO espelhos (contrato_id, numero, competencia, versao, situacao, entradas, saidas, "
                    "regra_sha256, criado_por, envio_id) VALUES (?,7,'2026-09',1,'vigente','{}','[]','x',?,?)",
                    (g, uid, envio)).lastrowid
    c.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id) VALUES (?,?)", (eid, mid))
    c.commit()
    linha = next(x for x in medicoes.resumo(conn, HOJE, mes="2026-09")["quadro"] if x["obra"] == "Obra G")
    assert _passos(linha) == {
        1: ("feito", "2026-10-01", None), 2: ("feito", "2026-10-03", None), 3: ("feito", "2026-10-04", None),
        4: ("feito", "2026-10-06", None), 5: ("feito", "2026-10-07", None), 6: ("atual", None, mid)}
    assert [p["nome"] for p in linha["passos"]][:2] == ["Planilha e carta", "Análise do órgão"]
    assert linha["pedido_centavos"] == 100001 and linha["aprovado_centavos"] == 99999
    # recebida: tudo feito, com a data do pagamento, e nenhum passo da vez
    c.execute("UPDATE medicoes SET estado='recebida', recebida_em='2026-10-08' WHERE id=?", (mid,))
    c.commit()
    linha = next(x for x in medicoes.resumo(conn, HOJE, mes="2026-09")["quadro"] if x["obra"] == "Obra G")
    assert _passos(linha)[6] == ("feito", "2026-10-08", None)
    assert {p["situacao"] for p in linha["passos"]} == {"feito"}


def test_quadro_execucao_e_reajuste_mostram_o_menos_adiantado(conn, cenario):
    ids = cenario
    quadro = {x["obra"]: x for x in medicoes.resumo(conn, HOJE, mes="2026-09")["quadro"]}
    # B: a execucao espera o pagamento (passo 6) e o reajuste ainda espera a nota (passo 4): a linha esta' no passo 4
    b = quadro["Obra B"]
    assert [m["id"] for m in b["medicoes"]] == [ids["b15"], ids["b15r"]]
    assert _passos(b) == {3: ("feito", None, None), 4: ("atual", None, ids["b15r"]),
                          5: ("futuro", None, None), 6: ("futuro", None, None)}
    assert b["pedido_centavos"] == 304000 and b["aprovado_centavos"] is None
    # A: as tres no envio da nota; o passo feito leva a data da ultima a fechar e o da vez abre a execucao
    a = quadro["Obra A"]
    assert _passos(a) == {3: ("feito", None, None), 4: ("feito", "2026-10-08", None),
                          5: ("atual", None, ids["a24"]), 6: ("futuro", None, None)}
    assert a["pedido_centavos"] == 109500


def test_quadro_obra_nao_ativa_so_aparece_com_medicao_na_competencia(conn, cenario):
    c, ids = conn, cenario
    mid = _medicao(c, ids["e"], 4, "execucao", "espelho_gerado", 100)     # a suspensa
    h = _obra(c, "Obra H", None)
    c.execute("UPDATE contratos SET encerramento_iniciado_em='2026-10-01' WHERE id=?", (h,))
    _medicao(c, ids["a"], 50, "execucao", "cancelada", 1)                 # cancelada nao conta
    c.commit()
    quadro = {x["obra"]: x for x in medicoes.resumo(conn, HOJE, mes="2026-09")["quadro"]}
    assert _passos(quadro["Obra E"])[3] == ("atual", None, mid) and quadro["Obra E"]["iniciar"] is False
    assert "Obra H" not in quadro      # em encerramento e sem medicao na competencia: nem linha nem Iniciar
    assert len(quadro["Obra A"]["medicoes"]) == 3


def test_meses_anteriores_trazem_as_medicoes_abertas_de_competencias_passadas(conn, cenario):
    c, ids = conn, cenario
    _medicao(c, ids["c"], 2, "execucao", "recebida", 10)
    _medicao(c, ids["c"], 1, "execucao", "cancelada", 10)
    antiga = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, planilha_enviada_em) "
                       "VALUES (?, 9, 'execucao', '2026-07', 'planilha_enviada', '2026-08-02')", (ids["c"],)).lastrowid
    c.commit()
    r = medicoes.resumo(conn, HOJE, mes="2026-10")
    assert [(x["obra"], x["titulo"], x["competencia"], x["passo"]["numero"], x["passo"]["nome"]) for x in r["anteriores"]] == [
        ("Obra C", "9ª Medição", "2026-07", 2, "Análise do órgão"),
        ("Obra A", "24ª Medição + Reajuste", "2026-09", 5, "Envio da nota"),
        ("Obra A", "1ª Medição de Projeto", "2026-09", 5, "Envio da nota"),
        ("Obra B", "15ª Medição", "2026-09", 6, "Pagamento"),
        ("Obra B", "Reajuste da 15ª Medição", "2026-09", 4, "Notas"),
        ("Obra C", "3ª Medição", "2026-09", 3, "Espelhos"),
        ("Obra F", "1ª Medição", "2026-09", 4, "Notas"),
    ]
    assert r["anteriores"][0]["medicao_id"] == antiga and r["anteriores"][0]["contrato_id"] == ids["c"]
    # a competencia do quadro nao e' "anterior": em setembro so' sobra a de julho
    assert [x["titulo"] for x in medicoes.resumo(conn, HOJE, mes="2026-09")["anteriores"]] == ["9ª Medição"]


def test_rota_do_resumo_traz_o_quadro_da_competencia_pedida(client_admin):
    r = client_admin.get("/api/medicoes/resumo?mes=2026-09")
    assert r.status_code == 200, r.text
    assert r.json()["mes"] == "2026-09" and r.json()["quadro"] == [] and r.json()["anteriores"] == []


# --- passos da medicao por obra pelo cadastro (#660) ------------------------------------------------------------

def _passos_do_cadastro(conn, cid, lista):
    conn.execute("UPDATE contratos SET passos_medicao=? WHERE id=?", (None if lista is None else json.dumps(lista), cid))
    conn.commit()


def test_passo_do_estado_pula_o_passo_que_a_obra_nao_tem():
    estados = ["prevista", "planilha_gerada", "planilha_enviada", "boletim_recebido", "espelho_gerado",
               "espelho_enviado", "nota_emitida", "protocolada", "nf_emitida", "recebida", "cancelada"]
    assert [medicoes.passo_do_estado(e, (1, 2, 3, 4, 5, 6)) for e in estados] == [1, 1, 2, 3, 3, 4, 5, 6, 6, 7, 0]
    assert [medicoes.passo_do_estado(e, (3, 4, 5, 6)) for e in estados] == [3, 3, 3, 3, 3, 4, 5, 6, 6, 7, 0]
    # sem "Envio da nota": a nota emitida ja' esta' no pagamento; sem "Análise do órgão": a enviada esta' nos espelhos
    assert [medicoes.passo_do_estado(e, (1, 3, 4, 6)) for e in estados] == [1, 1, 3, 3, 3, 4, 6, 6, 6, 7, 0]


def test_quadro_e_proximo_passo_so_com_os_passos_da_lista_do_cadastro(conn, cenario):
    ids = cenario
    _passos_do_cadastro(conn, ids["c"], ["espelhos", "notas", "pagamento"])
    c = next(x for x in medicoes.resumo(conn, HOJE, mes="2026-09")["quadro"] if x["obra"] == "Obra C")
    assert [(p["numero"], p["nome"], p["situacao"]) for p in c["passos"]] == [
        (3, "Espelhos", "atual"), (4, "Notas", "futuro"), (6, "Pagamento", "futuro")]
    # a nota emitida, sem o passo "Envio da nota": o passo da vez e' o pagamento, no quadro e no proximo passo
    conn.execute("UPDATE medicoes SET estado='nota_emitida', nota_emitida_em='2026-10-02' WHERE id=?", (ids["c3"],))
    conn.commit()
    c = next(x for x in medicoes.resumo(conn, HOJE, mes="2026-09")["quadro"] if x["obra"] == "Obra C")
    assert _passos(c) == {3: ("feito", None, None), 4: ("feito", "2026-10-02", None), 6: ("atual", None, ids["c3"])}
    [linha] = [x for x in medicoes.em_andamento(conn) if x["id"] == ids["c3"]]
    assert linha["proximo_passo"] == "Pagamento" and linha["passo"] == {"numero": 6, "nome": "Pagamento"}
    # a lista nao da' a' obra o passo que a familia do orgao nao tem (a B e' da MT-PAR: sem planilha e analise)
    _passos_do_cadastro(conn, ids["b"], ["planilha", "analise", "espelhos", "notas", "envio_nota", "pagamento"])
    b = next(x for x in medicoes.resumo(conn, HOJE, mes="2026-09")["quadro"] if x["obra"] == "Obra B")
    assert [p["numero"] for p in b["passos"]] == [3, 4, 5, 6]


def test_obra_com_a_lista_vazia_sai_do_quadro_e_nao_oferece_iniciar(conn, cenario):
    ids = cenario
    antes = medicoes.resumo(conn, HOJE, mes="2026-10")
    assert {o["contrato_id"] for o in antes["obras"] if o["sem_no_mes"]} >= {ids["c"], ids["d"]}
    _passos_do_cadastro(conn, ids["d"], [])     # sem medicao: sairia com o Iniciar
    _passos_do_cadastro(conn, ids["c"], [])     # com medicao na competencia de setembro
    setembro = medicoes.resumo(conn, HOJE, mes="2026-09")
    assert [x["obra"] for x in setembro["quadro"]] == ["Obra A", "Obra B", "Obra F"]
    outubro = medicoes.resumo(conn, HOJE, mes="2026-10")
    assert [x["obra"] for x in outubro["quadro"]] == ["Obra A", "Obra B", "Obra F"]
    sem = {o["contrato_id"]: o["sem_no_mes"] for o in outubro["obras"]}
    assert sem[ids["c"]] is False and sem[ids["d"]] is False and sem[ids["a"]] is True
    assert outubro["contagens"]["iniciar"] == antes["contagens"]["iniciar"] - 2
    # a medicao que ja' existe na obra continua em andamento, com os passos da familia do orgao
    [linha] = [x for x in medicoes.em_andamento(conn) if x["id"] == ids["c3"]]
    assert linha["passo"] == {"numero": 3, "nome": "Espelhos"}


def test_obra_sem_a_chave_continua_igual(conn, cenario):
    antes = medicoes.resumo(conn, HOJE, mes="2026-09")
    _passos_do_cadastro(conn, cenario["c"], ["espelhos", "pagamento"])
    assert medicoes.resumo(conn, HOJE, mes="2026-09") != antes
    _passos_do_cadastro(conn, cenario["c"], None)
    assert medicoes.resumo(conn, HOJE, mes="2026-09") == antes


# --- posicao do SIGA no quadro do mes (#664) -------------------------------------------------------------------

SIGA_HOJE = datetime.date(2026, 10, 30)      # sexta-feira


def _processo_siga(c, codigo, medicao_id=None, protocolo_id=None, setor="COFIN", entrada="2026-10-20 09:00:00",
                   situacao=None, lido=True):
    """Processo do SIGA ligado a' medicao (ou ao protocolo), com uma leitura e a transferencia de entrada no setor."""
    pid = c.execute("INSERT INTO siga_processos (codigo, medicao_id, protocolo_id, categoria) VALUES (?,?,?,'medicoes')",
                    (codigo, medicao_id, protocolo_id)).lastrowid
    if lido:
        c.execute("INSERT INTO siga_leituras (processo_id, lido_em, situacao) VALUES (?, '2026-10-30 12:00:00', ?)",
                  (pid, situacao or f"1º Volume - Aguardando Andamento [{setor}, [X]]"))
        c.execute("INSERT INTO siga_movimentacoes (processo_id, data, evento, at_lotacao) VALUES (?,?,'Transferência',?)",
                  (pid, entrada, f"{setor}/ORGAO"))
    return pid


def _siga(linha):
    return {p["numero"]: p["siga"] for p in linha["passos"]}


def _linha(conn, obra):
    return next(x for x in medicoes.resumo(conn, SIGA_HOJE, mes="2026-09")["quadro"] if x["obra"] == obra)


def _obra_no_orgao_da(c, nome, contrato_id):
    return _obra(c, nome, c.execute("SELECT orgao_id FROM contratos WHERE id=?", (contrato_id,)).fetchone()[0])


def test_quadro_sem_processo_ligado_traz_o_campo_vazio_em_todo_passo(conn, cenario):
    # processo que nao esta' ligado a medicao nenhuma nao aparece no quadro
    _processo_siga(conn, "AVULSO1")
    quadro = medicoes.resumo(conn, SIGA_HOJE, mes="2026-09")["quadro"]
    assert all(p["siga"] is None for x in quadro for p in x["passos"])
    assert any(x["passos"] for x in quadro)


def test_quadro_mostra_setor_e_dias_uteis_no_passo_em_que_o_processo_corre(conn, cenario):
    c, ids = conn, cenario
    # B: a 15ª protocolada (passo Pagamento), com processo vivo no setor desde 20/10 (terca): 8 dias uteis ate' 30/10
    pid = _processo_siga(c, "PAG001", medicao_id=ids["b15"])
    # G: planilha/carta enviada (passo Analise do orgao), no setor desde 28/10: 2 dias uteis
    g = _obra_no_orgao_da(c, "Obra G", ids["a"])
    g1 = _medicao(c, g, 1, "execucao", "planilha_enviada", 1001, planilha_enviada_em="2026-10-05 12:00:00")
    pid_g = _processo_siga(c, "ANA001", medicao_id=g1, setor="SUPE", entrada="2026-10-28 10:00:00")
    b = _siga(_linha(c, "Obra B"))
    assert b[6] == {"processo_id": pid, "setor": "COFIN", "dias_uteis": 8, "desde": "2026-10-20T09:00:00-04:00",
                    "hoje": 0}
    assert all(v is None for n, v in b.items() if n != 6)
    gq = _siga(_linha(c, "Obra G"))
    assert gq[2] == {"processo_id": pid_g, "setor": "SUPE", "dias_uteis": 2, "desde": "2026-10-28T10:00:00-04:00",
                     "hoje": 0}
    assert all(v is None for n, v in gq.items() if n != 2)
    # os mesmos setor, dias e entrada da tela SIGA
    from app import siga
    agora = datetime.datetime(2026, 10, 30, 16, tzinfo=datetime.timezone.utc)
    painel = {p["id"]: p for p in siga.painel(c, agora)["processos"]}
    assert (painel[pid]["setor"], painel[pid]["dias_uteis"], painel[pid]["desde"]) == ("COFIN", 8, b[6]["desde"])
    # movimentacao de hoje no processo: a tela SIGA escreve "hoje" no lugar dos dias, e o quadro recebe a mesma conta
    c.execute("INSERT INTO siga_movimentacoes (processo_id, data, evento) VALUES (?, '2026-10-30 08:00:00', 'Juntada')", (pid,))
    assert _siga(_linha(c, "Obra B"))[6]["hoje"] == siga.painel(c, agora)["processos"][0]["hoje"] == 1
    # as outras obras continuam sem nada
    assert all(v is None for v in _siga(_linha(c, "Obra A")).values())


def test_quadro_processo_encerrado_ou_sem_leitura_nao_aparece(conn, cenario):
    c, ids = conn, cenario
    _processo_siga(c, "ARQ001", medicao_id=ids["b15"], situacao="1º Volume - Arquivado [ARQUIVO, [X]]")
    _processo_siga(c, "NLIDO1", medicao_id=ids["b15"], lido=False)
    assert all(v is None for v in _siga(_linha(c, "Obra B")).values())
    # medicao fora do passo em que o processo corre (a nota emitida da Obra A): nada na linha
    _processo_siga(c, "FORA01", medicao_id=ids["a24"])
    assert all(v is None for v in _siga(_linha(c, "Obra A")).values())


def test_quadro_com_duas_medicoes_mostra_o_processo_mais_parado(conn, cenario):
    c, ids = conn, cenario
    # o reajuste da 15ª ainda no espelho: a celula do Pagamento mostra o processo da execucao, que esta' la'
    pid = _processo_siga(c, "PAG001", medicao_id=ids["b15"], entrada="2026-10-27 09:00:00")
    s = _siga(_linha(c, "Obra B"))[6]
    assert (s["processo_id"], s["dias_uteis"]) == (pid, 3)
    # as duas no Pagamento, cada uma com processo vivo: o mais parado
    c.execute("UPDATE medicoes SET estado='protocolada' WHERE id=?", (ids["b15r"],))
    parado = _processo_siga(c, "PAG002", medicao_id=ids["b15r"], setor="GABIN", entrada="2026-10-13 09:00:00")
    s = _siga(_linha(c, "Obra B"))[6]
    assert (s["processo_id"], s["setor"], s["dias_uteis"]) == (parado, "GABIN", 13)


def test_quadro_processo_ligado_so_ao_protocolo_vale_para_as_medicoes_dele(conn, cenario):
    c, ids = conn, cenario
    uid = c.execute("SELECT id FROM usuarios LIMIT 1").fetchone()[0]
    prot = c.execute("INSERT INTO protocolos (contrato_id, etapa, natureza, usuario_id, situacao) "
                     "VALUES (?, 'nota', 'execucao', ?, 'enviado')", (ids["b"], uid)).lastrowid
    c.execute("INSERT INTO protocolo_medicoes (protocolo_id, medicao_id) VALUES (?,?)", (prot, ids["b15"]))
    pid = _processo_siga(c, "PROT01", protocolo_id=prot)
    assert _siga(_linha(c, "Obra B"))[6]["processo_id"] == pid


def test_quadro_le_as_movimentacoes_do_siga_de_uma_vez(conn, cenario):
    """O quadro e' lido a cada entrada na tela: as movimentacoes dos processos de todas as linhas saem numa consulta
    so', seja qual for o numero de linhas com processo."""
    c, ids = conn, cenario
    _processo_siga(c, "PAG001", medicao_id=ids["b15"])
    _processo_siga(c, "AVULSO1")
    for n in (1, 2, 3):
        m = _medicao(c, _obra_no_orgao_da(c, f"Obra G{n}", ids["a"]), 1, "execucao", "protocolada", 1001)
        _processo_siga(c, f"PAGG0{n}", medicao_id=m)
    consultas = []
    c.set_trace_callback(lambda sql: consultas.append(sql) if "siga_movimentacoes" in sql else None)
    try:
        quadro = medicoes.resumo(c, SIGA_HOJE, mes="2026-09")["quadro"]
    finally:
        c.set_trace_callback(None)
    assert sum(1 for x in quadro for p in x["passos"] if p["siga"]) == 4
    assert len(consultas) == 1
