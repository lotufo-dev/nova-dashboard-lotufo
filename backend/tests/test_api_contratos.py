from tests.conftest import novo_contrato

NOVO = {"orgao": "SINFRA-MT", "numero_instrumento": "IC 082/2025",
        "objeto": "MT-388", "valor_original": "1.000.000,00",
        "vigencia_fim": "2027-12-31", "execucao_fim": "2027-06-30"}

def test_listar(client_admin):
    cid = novo_contrato(NOVO)
    lista = client_admin.get("/api/contratos").json()
    assert any(c["id"] == cid and c["valor_vigente_centavos"] == 100_000_000 for c in lista)

def test_listar_traz_o_a_receber_so_com_o_total_liberado(client_admin):
    """Lista de Obras (#509): `a_receber_centavos` e' nulo ate' o total ser liberado; liberado, e' o cheio da obra."""
    import json
    from app import db
    cid = novo_contrato(NOVO)
    lista = {c["id"]: c for c in client_admin.get("/api/contratos").json()}
    assert lista[cid]["a_receber_centavos"] is None
    conn = db.get_conn()
    conn.execute("INSERT OR REPLACE INTO cadastro_geral (chave, valor) VALUES ('diretoria', ?)", (json.dumps({"total_a_receber_liberado": True}),))
    conn.commit(); conn.close()
    lista = {c["id"]: c for c in client_admin.get("/api/contratos").json()}
    assert lista[cid]["a_receber_centavos"] == 0

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
         "item_chave": {"codigo": "2.1", "unidade": "m³"}},
        {"ordem": 2, "nome": "Drenagem", "tarefas": ["001.05"], "itens_planilha": ["3."], "item_chave": None}]


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
