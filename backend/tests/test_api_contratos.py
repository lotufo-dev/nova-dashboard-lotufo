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
