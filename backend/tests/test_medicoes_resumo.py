"""Pagina Medicoes com abas (09/10/2026): situacao por estado, marco de cada situacao (nunca o criado_em), a linha
unica de medicao + reajuste, o contratante (sigla e sub-orgao) e as obras sem medicao aberta (prevista nao conta)."""
import datetime

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
    assert env["dias"] == 2 and env["proximo_passo"] == "registrar o boletim"
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
    assert par["proximo_passo"] == "protocolar"
    assert {x["competencia"] for x in r["linhas"]} == {"2026-09"}   # #155: a competencia da medicao (AAAA-MM)
    assert r["contagens"] == {"sem-medicao": 1, "planilha-gerada": 0, "planilha-enviada": 0, "boletim-recebido": 0,
                              "faturamento": 1, "aguardando-nota": 2, "enviar-nota": 2, "aguardando-pagamento": 1}
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
    assert set(r.json()) == {"hoje", "contagens", "linhas", "obras"}
    # a rota fixa nao cai em /api/medicoes/{medicao_id}
    assert client_admin.get("/api/medicoes/999").status_code == 404


def test_rota_do_resumo_exige_login(client):
    assert client.get("/api/medicoes/resumo").status_code == 401
