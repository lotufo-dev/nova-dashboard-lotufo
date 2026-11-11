from tests.conftest import novo_contrato

NOVO = {"orgao": "SINFRA-MT", "numero_instrumento": "IC 082/2025",
        "objeto": "MT-388", "valor_original": "1.000.000,00",
        "vigencia_fim": "2027-12-31", "execucao_fim": "2027-06-30"}

def test_listar(client_admin):
    cid = novo_contrato(NOVO)
    lista = client_admin.get("/api/contratos").json()
    assert any(c["id"] == cid and c["valor_vigente_centavos"] == 100_000_000 for c in lista)

def test_sem_login_nega(client):
    assert client.get("/api/contratos").status_code == 401

def test_detalhe_inexistente_404(client_admin):
    assert client_admin.get("/api/contratos/9999").status_code == 404

def test_perfil_diretoria_le(client):
    from app import auth, db
    conn = db.get_conn()
    auth.criar_usuario(conn, "Dir", "dir@lotufo.com", "senha-forte-123", "diretoria")
    conn.close()
    r = client.post("/api/auth/login", json={"email": "dir@lotufo.com", "senha": "senha-forte-123"})
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))
    assert client.get("/api/contratos").status_code == 200

def test_escrita_de_contrato_pela_api_saiu(client_admin):
    """Bloco 9: contrato entra pelo cadastro versionado (`cadastro aplicar`), nao pela tela."""
    cid = novo_contrato(NOVO)
    assert client_admin.post("/api/contratos", json=NOVO).status_code == 405
    assert client_admin.put(f"/api/contratos/{cid}", json=NOVO).status_code == 405
    assert client_admin.post(f"/api/contratos/{cid}/estado",
                             json={"estado": "suspenso", "data": "2026-08-01"}).status_code == 404


def test_listar_traz_o_medido_de_execucao_e_o_saldo(client_admin):
    """Redesenho de Obras (#159): o % executado e o saldo a executar de cada obra vem da lista, em valor cheio."""
    from app import db, medicoes
    cid = novo_contrato(NOVO)
    conn = db.get_conn()
    mid = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, 1, mid, "protocolado", 250_000_00, "manual")
    medicoes.registrar_protocolo(conn, 1, mid, "2026-07-28", None, None, "manual", True, "teste de cenário")
    medicoes.definir_valor(conn, 1, mid, "atestado", 240_000_00, "manual")
    conn.close()
    outro = novo_contrato({**NOVO, "numero_instrumento": "IC 083/2025"})
    lista = {c["id"]: c for c in client_admin.get("/api/contratos").json()}
    assert lista[cid]["medido_execucao_centavos"] == 240_000_00      # o atestado vale
    assert lista[cid]["saldo_centavos"] == 100_000_000 - 240_000_00
    # a mesma conta do saldo do cronograma da obra
    from app import paineis
    conn = db.get_conn()
    for i in (cid, outro):
        s = paineis.saldo(conn, i)
        assert (lista[i]["medido_execucao_centavos"], lista[i]["saldo_centavos"]) == (s["atestado_execucao_centavos"], s["saldo_centavos"])
    conn.close()
    assert lista[outro]["medido_execucao_centavos"] == 0 and lista[outro]["saldo_centavos"] == 100_000_000


def test_listar_saldo_exclui_o_aditivo_de_reajuste(client_admin):
    """#262: o vigente da lista continua com o reajuste; o saldo a executar e' a precos iniciais."""
    from app import db, paineis
    cid = novo_contrato(NOVO)
    conn = db.get_conn()
    conn.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza) "
                 "VALUES (?, 'valor', 10_000_01, 'assinado', '2026-03-01', 'reajuste')", (cid,))
    conn.commit()
    s = paineis.saldo(conn, cid)
    conn.close()
    obra = {c["id"]: c for c in client_admin.get("/api/contratos").json()}[cid]
    assert obra["valor_vigente_centavos"] == 100_000_000 + 10_000_01
    assert obra["saldo_centavos"] == 100_000_000 == s["saldo_centavos"]


def test_listar_agrupa_o_contratante_como_medicoes(client_admin):
    """Redesenho de Obras (#159): a escolha do contratante agrupa como a tela de Medicoes -- "SINFRA" para toda a
    familia, com a superintendencia em `orgao_sub`; o orgao com sigla propria (MTPAR) fica com ela."""
    from app import db
    a = novo_contrato(NOVO)
    b = novo_contrato({**NOVO, "numero_instrumento": "IC 083/2025"})
    c = novo_contrato({**NOVO, "numero_instrumento": "IC 084/2025", "orgao": "texto livre"})
    conn = db.get_conn()
    conn.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('sinfra-suef2', 'SINFRA - SUEF II', 'sinfra', '{}')")
    conn.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('mtpar', 'MTPAR', 'mtpar', '{}')")
    conn.execute("UPDATE contratos SET orgao_id=(SELECT id FROM orgaos WHERE chave='sinfra-suef2') WHERE id IN (?, ?)", (a, b))
    conn.execute("UPDATE contratos SET orgao_id=(SELECT id FROM orgaos WHERE chave='mtpar') WHERE id=?", (c,))
    conn.commit(); conn.close()
    lista = {x["id"]: x for x in client_admin.get("/api/contratos").json()}
    assert lista[a]["contratante"] == lista[b]["contratante"] == "SINFRA" and lista[a]["orgao_sub"] == "SUEF II"
    assert lista[c]["contratante"] == "MTPAR" and lista[c]["orgao_sub"] is None


def _com_grupos(cid):
    from app import db
    conn = db.get_conn()
    conn.execute("INSERT INTO custo_grupos (contrato_id, ordem, nome, tarefas, itens_planilha, item_chave_codigo, "
                 "item_chave_unidade) VALUES (?, 2, 'Drenagem', '[\"001.05\"]', '[\"3.\"]', NULL, NULL)", (cid,))
    conn.execute("INSERT INTO custo_grupos (contrato_id, ordem, nome, tarefas, itens_planilha, item_chave_codigo, "
                 "item_chave_unidade) VALUES (?, 1, 'Terraplanagem', '[\"001.03\"]', '[\"2.\"]', '2.1', 'm³')", (cid,))
    conn.commit(); conn.close()


def test_custo_grupos_lista_na_ordem_do_cadastro(client_admin):
    """Issue #489: os grupos de custo da obra, na ordem do yaml, com tarefas, itens e item-chave."""
    cid = novo_contrato(NOVO)
    _com_grupos(cid)
    assert client_admin.get(f"/api/contratos/{cid}/custo-grupos").json() == [
        {"ordem": 1, "nome": "Terraplanagem", "tarefas": ["001.03"], "itens_planilha": ["2."],
         "titulos_planilha": [], "item_chave": {"codigo": "2.1", "unidade": "m³"}},
        {"ordem": 2, "nome": "Drenagem", "tarefas": ["001.05"], "itens_planilha": ["3."], "titulos_planilha": [],
         "item_chave": None}]


def test_custo_grupos_sem_cadastro_e_lista_vazia_e_inexistente_404(client_admin):
    cid = novo_contrato(NOVO)
    assert client_admin.get(f"/api/contratos/{cid}/custo-grupos").json() == []
    assert client_admin.get("/api/contratos/9999/custo-grupos").status_code == 404


def test_custo_grupos_exige_ver_paineis(client_admin, monkeypatch):
    from app import permissoes
    cid = novo_contrato(NOVO)
    monkeypatch.setitem(permissoes.PERFIS, "admin", frozenset())
    assert client_admin.get(f"/api/contratos/{cid}/custo-grupos").status_code == 403


def test_custo_rm_da_obra_pelo_centro_atual_e_pelos_anteriores(client_admin):
    """#488: o custo do RM da obra sai pelo centro de custo atual e pelos anteriores, na coligada da entidade."""
    from app import db
    cid = novo_contrato(NOVO)
    sem_centro = novo_contrato({**NOVO, "numero_instrumento": "IC 083/2025"})
    conn = db.get_conn()
    conn.execute("UPDATE contratos SET centro_custo_rm='2.001.012', centros_custo_anteriores_rm='[\"1.050.003\"]' "
                 "WHERE id=?", (cid,))
    linhas = [(1, "2.001.012", "PRJ01", "1.02", "1.01.003", "2026-03", 3, 123457),
              (1, "1.050.003", None, None, "2.02.001", "2024-11", 1, -1001),
              (1, "2.001.099", "PRJ02", "1.01", "1.01.003", "2026-03", 1, 999),     # outra obra
              (12, "2.001.012", "PRJ01", "1.02", "1.01.003", "2026-03", 1, 777)]    # mesmo centro, outra coligada
    conn.executemany("INSERT INTO rm_custo_tarefas (coligada, centro_custo, projeto, tarefa, natureza, mes, qtd, "
                     "valor_centavos) VALUES (?,?,?,?,?,?,?,?)", linhas)
    conn.executemany("INSERT INTO rm_estoque_baixas (coligada, centro_custo, tipo_movimento, mes, qtd, valor_centavos) "
                     "VALUES (?,?,?,?,?,?)", [(1, "1.050.003", "1.1.21", "2024-10", 2, 50001),
                                              (1, "2.001.099", "1.1.21", "2024-10", 2, 3)])
    conn.commit(); conn.close()
    r = client_admin.get(f"/api/contratos/{cid}/custo-rm")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["custo"] == [
        {"centro_custo": "1.050.003", "projeto": None, "tarefa": None, "natureza": "2.02.001", "mes": "2024-11",
         "qtd": 1, "valor_centavos": -1001},
        {"centro_custo": "2.001.012", "projeto": "PRJ01", "tarefa": "1.02", "natureza": "1.01.003", "mes": "2026-03",
         "qtd": 3, "valor_centavos": 123457}]
    assert d["estoque"] == [{"centro_custo": "1.050.003", "tipo_movimento": "1.1.21", "mes": "2024-10", "qtd": 2,
                             "valor_centavos": 50001}]
    assert client_admin.get(f"/api/contratos/{sem_centro}/custo-rm").json() == {"custo": [], "estoque": []}
    assert client_admin.get("/api/contratos/9999/custo-rm").status_code == 404


def test_custo_rm_de_consorcio_sem_centro_vem_pela_coligada(client_admin):
    """#488: obra de consorcio sem centro de custo e' achada so' pela coligada, quando e' a unica obra dela."""
    from app import db, entidades
    conn = db.get_conn()
    eid = entidades.criar(conn, 1, {"nome": "Consórcio X", "cnpj": "11444777000161",
                                    "papel": "consorcio", "coligada_rm": 12})
    conn.close()
    cons = novo_contrato({**NOVO, "numero_instrumento": "IC 090/2025", "entidade_id": eid})
    lotufo_sem_centro = novo_contrato({**NOVO, "numero_instrumento": "IC 091/2025"})
    conn = db.get_conn()
    conn.executemany("INSERT INTO rm_custo_tarefas (coligada, centro_custo, projeto, tarefa, natureza, mes, qtd, "
                     "valor_centavos) VALUES (?,?,?,?,?,?,?,?)",
                     [(12, "1.01", None, None, "1.01.003", "2026-01", 1, 501), (1, "2.001.012", None, None,
                                                                                 "1.01.003", "2026-01", 1, 7)])
    conn.commit(); conn.close()
    d = client_admin.get(f"/api/contratos/{cons}/custo-rm").json()
    assert [x["valor_centavos"] for x in d["custo"]] == [501] and d["estoque"] == []
    # a Lotufo (coligada 1) sem centro nao recebe a coligada inteira
    assert client_admin.get(f"/api/contratos/{lotufo_sem_centro}/custo-rm").json() == {"custo": [], "estoque": []}
    # segunda obra na mesma coligada: a coligada deixa de identificar a obra, e nenhuma recebe o custo da outra
    outra = novo_contrato({**NOVO, "numero_instrumento": "IC 092/2025", "entidade_id": eid})
    for c in (cons, outra):
        assert client_admin.get(f"/api/contratos/{c}/custo-rm").json() == {"custo": [], "estoque": []}


def test_custo_rm_exige_ver_paineis(client, monkeypatch):
    from app import auth, db, permissoes
    cid = novo_contrato(NOVO)
    assert client.get(f"/api/contratos/{cid}/custo-rm").status_code == 401
    conn = db.get_conn()
    auth.criar_usuario(conn, "Dir", "dir@lotufo.com", "senha-forte-123", "diretoria")
    conn.close()
    r = client.post("/api/auth/login", json={"email": "dir@lotufo.com", "senha": "senha-forte-123"})
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))
    assert client.get(f"/api/contratos/{cid}/custo-rm").status_code == 200
    monkeypatch.setitem(permissoes.PERFIS, "diretoria", frozenset())
    assert client.get(f"/api/contratos/{cid}/custo-rm").status_code == 403


def test_ficha_traz_ultima_medicao_em_andamento_e_vencimentos(client_admin, monkeypatch):
    """#510: a ficha executiva da obra. Ultima = a recebida mais nova; em andamento = a aberta mais nova, com a etapa
    e o desde; vencimentos = certidao (quando ha), fim da execucao e fim da vigencia, com o nivel do semaforo."""
    import datetime
    from app import db, medicoes, tempo
    hoje = datetime.date(2026, 11, 6)
    monkeypatch.setattr(tempo, "hoje_local", lambda: hoje)
    cid = novo_contrato({**NOVO, "execucao_fim": "2026-11-18", "vigencia_fim": "2027-02-16"})
    conn = db.get_conn()
    a = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 15, "tipo": "execucao", "competencia": "2026-09"})
    medicoes.definir_valor(conn, 1, a, "protocolado", 787_288_979, "manual")
    conn.execute("UPDATE medicoes SET estado='recebida', recebida_em='2026-10-16', nota_emitida_em='2026-10-02' WHERE id=?", (a,))
    conn.commit()
    b = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 16, "tipo": "execucao", "competencia": "2026-10"})
    medicoes.definir_valor(conn, 1, b, "protocolado", 990_529_648, "manual")
    conn.execute("UPDATE medicoes SET estado='protocolada' WHERE id=?", (b,))
    conn.commit()
    conn.close()
    f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    assert f["ultima_medicao"]["titulo"] == "15ª Medição"
    assert f["ultima_medicao"]["valor_centavos"] == 787_288_979
    assert f["ultima_medicao"]["recebida_em"] == "2026-10-16" and f["ultima_medicao"]["dias_apos_nota"] == 14
    assert f["em_andamento"]["titulo"] == "16ª Medição" and f["em_andamento"]["valor_centavos"] == 990_529_648
    assert f["em_andamento"]["etapa"] == "análise do órgão"
    v = {x["chave"]: x for x in f["vencimentos"]}
    assert v["execucao"]["data"] == "2026-11-18" and v["execucao"]["dias"] == 12 and v["execucao"]["nivel"] == "critico"
    assert v["vigencia"]["data"] == "2027-02-16" and v["vigencia"]["nivel"] == "normal"
    assert f["contrato"]["original_igual"] is True and f["contrato"]["tas"] == 0


def test_ficha_e_cabecalho_sem_prazo_de_execucao_conhecido_mostram_so_a_data(client_admin, monkeypatch):
    """#662: execucao registrada vencida e aditivo posterior so' de vigencia: a data fica, sem dias nem vermelho."""
    import datetime
    from app import db, tempo
    monkeypatch.setattr(tempo, "hoje_local", lambda: datetime.date(2026, 12, 1))
    cid = novo_contrato({**NOVO, "execucao_fim": "2026-10-20", "vigencia_fim": "2027-02-16"})

    def execucao():
        f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
        cab = client_admin.get(f"/api/contratos/{cid}/cabecalho").json()
        v = {x["chave"]: x for x in f["vencimentos"]}["execucao"]
        return (v["data"], v["dias"], v["nivel"]), (cab["execucao_fim"], cab["dias_execucao"], cab["execucao_sem_prazo"])

    assert execucao() == (("2026-10-20", -42, "critico"), ("2026-10-20", -42, False))
    conn = db.get_conn()
    conn.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, nova_vigencia_fim, status, data_assinatura) "
                 "VALUES (?, 'prazo', 0, '2027-06-30', 'assinado', '2026-11-10')", (cid,))
    conn.commit(); conn.close()
    assert execucao() == (("2026-10-20", None, "normal"), ("2026-10-20", None, True))


def test_ficha_obra_sem_medicao_e_inexistente_404(client_admin):
    cid = novo_contrato(NOVO)
    f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    assert f["ultima_medicao"] is None and f["em_andamento"] is None
    assert client_admin.get("/api/contratos/99999/ficha").status_code == 404


def test_ficha_nivel_do_prazo_e_o_semaforo():
    from app.ficha_obra import nivel_do_prazo
    assert [nivel_do_prazo(d) for d in (None, -3, 30, 31, 90, 91)] == ["normal", "critico", "critico", "atencao", "atencao", "normal"]


def test_ficha_conta_so_os_tas_que_valem(client_admin):
    """Reajuste e aditivo corrigido por outro nao entram em "N TAs"; cancelado tambem nao."""
    from app import db
    cid = novo_contrato(NOVO)
    conn = db.get_conn()
    ins = ("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza, chave_cadastro, "
           "corrige_chave, cancelado_em) VALUES (?, ?, ?, 'assinado', '2026-03-01', ?, ?, ?, ?)")
    conn.execute(ins, (cid, "prazo", 0, None, "ta1", None, None))
    conn.execute(ins, (cid, "valor", 100, None, "ta2", None, None))
    conn.execute(ins, (cid, "valor", 100, None, "ta2b", "ta2", None))      # corrige o ta2: so' o corretor vale
    conn.execute(ins, (cid, "valor", 500, "reajuste", "rj", None, None))
    conn.execute(ins, (cid, "prazo", 0, None, "ta4", None, "2026-04-01"))  # cancelado
    conn.commit()
    conn.close()
    assert client_admin.get(f"/api/contratos/{cid}/ficha").json()["contrato"]["tas"] == 2


def _obra_com_reajuste_e_medicoes(bp=None):
    """Contrato com um aditivo de valor, um aditivo de reajuste e duas medicoes de execucao."""
    from app import db, medicoes
    cid = novo_contrato({**NOVO, "valor_original": "1.000.000,01"})
    conn = db.get_conn()
    if bp is not None:
        conn.execute("UPDATE contratos SET percentual_direito_bp=? WHERE id=?", (bp, cid))
    ins = ("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza, chave_cadastro) "
           "VALUES (?, 'valor', ?, 'assinado', '2026-03-01', ?, ?)")
    conn.execute(ins, (cid, 200_000_00, None, "ta1"))
    conn.execute(ins, (cid, 50_000_03, "reajuste", "rj1"))
    conn.commit()
    for numero, competencia, valor in ((1, "2026-04", 300_000_33), (2, "2026-05", 100_000_00)):
        m = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": numero, "tipo": "execucao", "competencia": competencia})
        medicoes.definir_valor(conn, 1, m, "protocolado", valor, "manual")
        conn.execute("UPDATE medicoes SET estado='protocolada' WHERE id=?", (m,))
        conn.commit()
    conn.close()
    return cid


def test_ficha_topo_na_base_de_execucao_sem_o_aditivo_de_reajuste(client_admin):
    """#646: valor vigente, medido e saldo do topo falam da mesma coisa: execucao a precos iniciais. O aditivo de
    reajuste fica fora dos tres e aparece a parte."""
    cid = _obra_com_reajuste_e_medicoes()
    f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    t = f["topo"]
    assert t["vigente_centavos"] == 1_200_000_01          # original + TA de valor, sem o reajuste
    assert t["medido_centavos"] == 400_000_33
    assert t["saldo_centavos"] == 799_999_68
    assert t["vigente_centavos"] - t["medido_centavos"] == t["saldo_centavos"]
    assert t["reajuste_centavos"] == 50_000_03
    assert f["contrato"]["original_centavos"] == 1_000_000_01 and f["contrato"]["original_igual"] is False


def test_ficha_topo_na_cota_da_lotufo_fecha_ao_centavo(client_admin):
    """#646: em consorcio os tres numeros vao na cota; vigente e medido arredondam uma vez cada e o saldo e' a
    diferenca dos dois (centavo impar e rateio com residuo: 49% de 1.200.000,01 e de 400.000,33 nao sao inteiros)."""
    cid = _obra_com_reajuste_e_medicoes(bp=4900)
    f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    t = f["topo"]
    assert t["vigente_centavos"] == 588_000_00            # 588.000,0049
    assert t["medido_centavos"] == 196_000_16             # 196.000,1617
    assert t["saldo_centavos"] == 391_999_84
    assert t["vigente_centavos"] - t["medido_centavos"] == t["saldo_centavos"]
    assert t["reajuste_centavos"] == 24_500_01            # 24.500,0147
    assert f["contrato"]["original_centavos"] == 490_000_00   # 490.000,0049


def test_ficha_original_igual_compara_com_o_vigente_de_execucao(client_admin):
    """#646: contrato so' com aditivo de reajuste: o valor vigente do topo (sem reajuste) e' o original."""
    from app import db
    cid = novo_contrato(NOVO)
    conn = db.get_conn()
    conn.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza, chave_cadastro) "
                 "VALUES (?, 'valor', 500, 'assinado', '2026-03-01', 'reajuste', 'rj')", (cid,))
    conn.commit()
    conn.close()
    f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    assert f["contrato"]["original_igual"] is True
    assert f["topo"]["vigente_centavos"] == 100_000_000 and f["topo"]["reajuste_centavos"] == 500


def test_ficha_ritmo_e_prazo_na_cota_e_com_o_saldo_do_topo(client_admin, monkeypatch):
    """#655: o cartao "Ritmo e prazo" fala na mesma base do resto do resumo: ritmo na cota da Lotufo e o saldo do
    topo (o mesmo numero do cartao Execucao). Conclusao, situacao e dias sao os de `prazos.ritmo_e_prazo`."""
    import datetime
    from app import contratos, db, prazos, tempo
    hoje = datetime.date(2026, 10, 15)   # janela 04 a 09/2026: as duas medicoes do cenario estao nela
    monkeypatch.setattr(tempo, "hoje_local", lambda: hoje)
    cid = _obra_com_reajuste_e_medicoes(bp=4900)
    conn = db.get_conn()
    conn.execute("UPDATE contratos SET execucao_fim='2026-12-20' WHERE id=?", (cid,))
    conn.commit()
    cheio = prazos.ritmo_e_prazo(conn, cid, hoje)
    conn.close()
    f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    r = f["ritmo"]
    assert cheio["ritmo_centavos"] == 66_666_72 and cheio["situacao"] == "atrasa" and cheio["dias_alem"] > 0
    assert r["ritmo_centavos"] == contratos.cota(66_666_72, 4900) == 32_666_69
    assert r["saldo_centavos"] == f["topo"]["saldo_centavos"] == 391_999_84
    assert (r["conclusao"], r["execucao_fim"], r["situacao"], r["dias_alem"]) == (
        cheio["conclusao"], "2026-12-20", "atrasa", cheio["dias_alem"])


def test_listar_traz_a_posicao_na_cota_igual_ao_topo_da_pagina_da_obra(client_admin):
    """#645: a lista de Obras le `posicao` (vigente, medido e saldo de execucao, na cota da Lotufo), a mesma conta do
    topo da pagina da obra, obra a obra; os campos cheios de antes continuam para as outras telas."""
    consorcio = _obra_com_reajuste_e_medicoes(bp=4900)
    propria = _obra_com_reajuste_e_medicoes()
    lista = {c["id"]: c for c in client_admin.get("/api/contratos").json()}
    p = lista[consorcio]["posicao"]
    assert p["vigente_centavos"] == 588_000_00            # 49% de 1.200.000,01, sem o aditivo de reajuste
    assert p["medido_centavos"] == 196_000_16             # 49% de 400.000,33
    assert p["saldo_centavos"] == 391_999_84 == p["vigente_centavos"] - p["medido_centavos"]
    assert lista[consorcio]["medido_execucao_centavos"] == 400_000_33     # o cheio de antes nao mudou
    assert lista[propria]["posicao"]["vigente_centavos"] == 1_200_000_01
    for cid in (consorcio, propria):
        topo = client_admin.get(f"/api/contratos/{cid}/ficha").json()["topo"]
        for campo in ("vigente_centavos", "medido_centavos", "saldo_centavos"):
            assert lista[cid]["posicao"][campo] == topo[campo]


def test_listar_traz_o_a_receber_na_cota_so_com_o_total_liberado(client_admin):
    """#645: o a receber da lista vai na cota, cobranca a cobranca (a conta da tela A receber); nulo ate' liberar."""
    import json
    from app import db, diretoria
    cid = _obra_com_reajuste_e_medicoes(bp=4900)          # protocoladas: 300.000,33 e 100.000,00
    outro = novo_contrato({**NOVO, "numero_instrumento": "IC 084/2025"})
    lista = {c["id"]: c for c in client_admin.get("/api/contratos").json()}
    assert lista[cid]["posicao"]["a_receber_centavos"] is None
    conn = db.get_conn()
    conn.execute("INSERT OR REPLACE INTO cadastro_geral (chave, valor) VALUES ('diretoria', ?)", (json.dumps({"total_a_receber_liberado": True}),))
    conn.commit()
    tela = {o["contrato_id"]: o["valor_centavos"] for o in diretoria.a_receber(conn)["por_obra"]}
    conn.close()
    lista = {c["id"]: c for c in client_admin.get("/api/contratos").json()}
    assert lista[cid]["posicao"]["a_receber_centavos"] == 147_000_16 + 49_000_00 == tela[cid]   # 147.000,1617 e 49.000,00
    assert "a_receber_centavos" not in lista[cid]                         # o cheio saiu da lista
    assert lista[outro]["posicao"]["a_receber_centavos"] == 0
