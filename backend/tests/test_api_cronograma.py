from tests.conftest import novo_contrato
def _contrato(client_admin):
    return novo_contrato({
        "orgao": "S", "numero_instrumento": "IC 1", "objeto": "X",
        "valor_original": "1.000,00"})

def test_cronograma_api(client_admin):
    cid = _contrato(client_admin)
    assert client_admin.get(f"/api/contratos/{cid}/cronograma").json() is None
    r = client_admin.post(f"/api/contratos/{cid}/cronograma", json={
        "itens": [{"competencia": "2026-09", "valor": "100,00"},
                  {"competencia": "2026-10", "valor": "200,00"}]})
    assert r.status_code == 201 and r.json()["versao"] == 1
    vig = client_admin.get(f"/api/contratos/{cid}/cronograma").json()
    assert vig["numero"] == 1 and vig["itens"][0]["valor_previsto_centavos"] == 100_00
    assert client_admin.post(f"/api/contratos/{cid}/cronograma", json={
        "itens": [{"competencia": "2026-09", "valor": "1,00"},
                  {"competencia": "2026-09", "valor": "2,00"}]}).status_code == 422
    assert client_admin.get("/api/contratos/9999/cronograma").status_code == 404


# --- guardas adicionais ---

def test_post_em_contrato_inexistente_da_404(client_admin):
    assert client_admin.post("/api/contratos/9999/cronograma", json={
        "itens": [{"competencia": "2026-09", "valor": "1,00"}]}).status_code == 404

def test_competencia_com_digitos_unicode_da_422(client_admin):
    """`\\d` do Python casa digito UNICODE; o GLOB do SQLite so casa [0-9].

    "٢٠٢٦-09" passaria no pydantic e estouraria o CHECK como IntegrityError (500)."""
    cid = _contrato(client_admin)
    assert client_admin.post(f"/api/contratos/{cid}/cronograma", json={
        "itens": [{"competencia": "٢٠٢٦-09", "valor": "1,00"}]}).status_code == 422
    assert client_admin.get(f"/api/contratos/{cid}/cronograma").json() is None

def test_competencias_invalidas_dao_422(client_admin):
    cid = _contrato(client_admin)
    for comp in ("09/2026", "2026-13", "2026-00", "2026-9", ""):
        assert client_admin.post(f"/api/contratos/{cid}/cronograma", json={
            "itens": [{"competencia": comp, "valor": "1,00"}]}).status_code == 422, comp

def test_valor_gigante_da_422(client_admin):
    """Acima de int64 o sqlite3 levanta OverflowError dentro do handler (500)."""
    cid = _contrato(client_admin)
    assert client_admin.post(f"/api/contratos/{cid}/cronograma", json={
        "itens": [{"competencia": "2026-09", "valor": "9" * 30 + ",00"}]}).status_code == 422
    # acima do max_length do campo, o pydantic barra antes mesmo do parse
    assert client_admin.post(f"/api/contratos/{cid}/cronograma", json={
        "itens": [{"competencia": "2026-09", "valor": "9" * 300 + ",00"}]}).status_code == 422
    assert client_admin.get(f"/api/contratos/{cid}/cronograma").json() is None

def test_valor_brl_invalido_da_422(client_admin):
    cid = _contrato(client_admin)
    assert client_admin.post(f"/api/contratos/{cid}/cronograma", json={
        "itens": [{"competencia": "2026-09", "valor": "cem reais"}]}).status_code == 422

def test_lista_vazia_ou_gigante_da_422(client_admin):
    cid = _contrato(client_admin)
    assert client_admin.post(f"/api/contratos/{cid}/cronograma",
                             json={"itens": []}).status_code == 422
    demais = [{"competencia": "2026-09", "valor": "1,00"}] * 601
    assert client_admin.post(f"/api/contratos/{cid}/cronograma",
                             json={"itens": demais}).status_code == 422

def test_422_nao_deixa_transacao_aberta(client_admin):
    """Depois de um 422 a escrita seguinte tem que funcionar (handler faz rollback)."""
    cid = _contrato(client_admin)
    assert client_admin.post(f"/api/contratos/{cid}/cronograma", json={
        "itens": [{"competencia": "2026-09", "valor": "1,00"},
                  {"competencia": "2026-09", "valor": "2,00"}]}).status_code == 422
    r = client_admin.post(f"/api/contratos/{cid}/cronograma", json={
        "itens": [{"competencia": "2026-09", "valor": "3,00"}]})
    assert r.status_code == 201 and r.json()["versao"] == 1
    assert client_admin.get(f"/api/contratos/{cid}/cronograma").json()["numero"] == 1

def test_nova_versao_incrementa_e_nao_apaga_a_anterior(client_admin):
    cid = _contrato(client_admin)
    client_admin.post(f"/api/contratos/{cid}/cronograma", json={
        "itens": [{"competencia": "2099-01", "valor": "100,00"}]})
    r = client_admin.post(f"/api/contratos/{cid}/cronograma", json={
        "itens": [{"competencia": "2099-01", "valor": "150,00"}]})
    assert r.status_code == 201 and r.json()["versao"] == 2
    vig = client_admin.get(f"/api/contratos/{cid}/cronograma").json()
    assert vig["numero"] == 2 and vig["itens"][0]["valor_previsto_centavos"] == 150_00
    assert vig["origem"] == "manual"

def test_leitura_exige_login(client):
    assert client.get("/api/contratos/1/cronograma").status_code in (401, 403)

def test_escrita_exige_permissao(client):
    from app import auth, db
    conn = db.get_conn()
    auth.criar_usuario(conn, "Dir", "dir@lotufo.com", "senha-forte-123", "diretoria")
    conn.close()
    r = client.post("/api/auth/login", json={"email": "dir@lotufo.com", "senha": "senha-forte-123"})
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))
    client.headers["X-CSRF-Token"] = r.json()["csrf"]
    assert client.post("/api/contratos/1/cronograma", json={
        "itens": [{"competencia": "2026-09", "valor": "1,00"}]}).status_code == 403


def test_lista_de_versoes(client_admin):
    """Issue #256: a aba Cronograma lista uma linha por versao, com a data do documento quando veio do cadastro."""
    from app import cronograma, db
    cid = _contrato(client_admin)
    assert client_admin.get(f"/api/contratos/{cid}/cronograma/versoes").json() == []
    conn = db.get_conn()
    try:
        cronograma.nova_versao(conn, 1, cid, [("2024-05", 5_00)], "manual", data_documento="2024-04-10")
        conn.execute("INSERT INTO cronograma_versoes_cadastro (versao_id, contrato_id, chave, origem, "
                     "data_documento, instrumento) VALUES (1,?,?,?,?,?)", (cid, "ta-01", "aditivo", "2024-04-10", "ta-01"))
        conn.commit()
    finally:
        conn.close()
    vs = client_admin.get(f"/api/contratos/{cid}/cronograma/versoes").json()
    assert len(vs) == 1
    assert {k: vs[0][k] for k in ("numero", "chave", "origem_documento", "data_documento", "instrumento",
                                  "competencias", "total_centavos", "vigente")} == {
        "numero": 1, "chave": "ta-01", "origem_documento": "aditivo", "data_documento": "2024-04-10",
        "instrumento": "ta-01", "competencias": 1, "total_centavos": 5_00, "vigente": True}
    assert client_admin.get("/api/contratos/9999/cronograma/versoes").status_code == 404
