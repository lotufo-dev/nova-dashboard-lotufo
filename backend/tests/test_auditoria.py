import json
from app import db, auditoria

def _conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn(); db.migrate(conn); return conn

def _registrar(conn, *args, **kwargs):
    """registrar() nao abre mais transacao: quem e' dono dela e' o chamador.

    Nos testes que exercitam a cadeia isoladamente (sem passar por um repositorio),
    o envelope de uma mutacao de negocio e' este helper.
    """
    with db.mutacao(conn):
        return auditoria.registrar(conn, *args, **kwargs)

def test_registro_encadeado(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    _registrar(conn, None, "auth.login", depois={"email": "a@b.c"})
    _registrar(conn, None, "contrato.criar", "contrato", "1", depois={"objeto": "obra X"})
    linhas = conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
    assert linhas[0]["hash_prev"] == "genesis"
    assert linhas[1]["hash_prev"] == linhas[0]["hash"]
    assert auditoria.verificar_cadeia(conn) is True

def test_adulteracao_detectada(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    _registrar(conn, None, "auth.login")
    _registrar(conn, None, "auth.logout")
    conn.execute("UPDATE audit_log SET acao='hackeado' WHERE id=1")
    conn.commit()
    assert auditoria.verificar_cadeia(conn) is False


# --- testes adicionais (nao previstos no brief) -------------------------------

import threading

from app import auth
from app.permissoes import PERFIS

def test_entidade_id_inteiro_nao_quebra_cadeia(tmp_path, monkeypatch):
    # o SQLite grava 42 (int) como '42' na coluna TEXT: se o hash for calculado
    # sobre o int, a releitura recomputa outro hash e a cadeia fica "adulterada"
    # para sempre. registrar() precisa normalizar ANTES de hashear e inserir.
    conn = _conn(tmp_path, monkeypatch)
    _registrar(conn, None, "contrato.criar", "contrato", 42)
    r = conn.execute("SELECT entidade_id FROM audit_log").fetchone()
    assert r["entidade_id"] == "42"
    assert auditoria.verificar_cadeia(conn) is True

def test_concorrencia_nao_forka_cadeia(tmp_path, monkeypatch):
    # sem transacao imediata, threads concorrentes leem o mesmo head e inserem
    # duas linhas com o mesmo hash_prev -- a cadeia forka e nunca mais fecha.
    conn = _conn(tmp_path, monkeypatch)

    def trabalhar(n):
        c = db.get_conn()
        try:
            for i in range(30):
                _registrar(c, None, f"carga.t{n}e{i}")
        finally:
            c.close()

    threads = [threading.Thread(target=trabalhar, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 120
    assert auditoria.verificar_cadeia(conn) is True

def _seed(email="leo@lotufo.com", senha="senha-forte-123", perfil="admin"):
    conn = db.get_conn()
    db.migrate(conn)
    uid = auth.criar_usuario(conn, "Leo", email, senha, perfil)
    conn.close()
    return uid

def _login(client, email="leo@lotufo.com", senha="senha-forte-123"):
    r = client.post("/api/auth/login", json={"email": email, "senha": senha})
    assert r.status_code == 200, r.text
    # cookie secure nao volta sozinho em http://testserver: injetar na jar do client
    token = r.cookies.get("sessao") or client.cookies.get("sessao")
    client.cookies.set("sessao", token)
    return r.json()

def test_cadeia_vazia_e_integra(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    assert auditoria.verificar_cadeia(conn) is True

def test_campos_gravados_e_json_serializado(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    uid = auth.criar_usuario(conn, "Leo", "leo@lotufo.com", "senha-forte-123", "admin")
    _registrar(conn, uid, "contrato.editar", "contrato", "42",
               antes={"valor": 100}, depois={"valor": 200})
    r = conn.execute("SELECT * FROM audit_log").fetchone()
    assert r["usuario_id"] == uid
    assert r["acao"] == "contrato.editar"
    assert r["entidade"] == "contrato" and r["entidade_id"] == "42"
    assert json.loads(r["antes"]) == {"valor": 100}
    assert json.loads(r["depois"]) == {"valor": 200}
    assert r["criado_em"] and len(r["hash"]) == 64

def test_acentos_preservados_no_payload(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    _registrar(conn, None, "contrato.criar", depois={"objeto": "Manutenção Rodoviária"})
    r = conn.execute("SELECT depois FROM audit_log").fetchone()
    assert json.loads(r["depois"])["objeto"] == "Manutenção Rodoviária"
    assert auditoria.verificar_cadeia(conn) is True

def test_adulteracao_em_hash_prev_detectada(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    _registrar(conn, None, "auth.login")
    _registrar(conn, None, "auth.logout")
    conn.execute("UPDATE audit_log SET hash_prev='genesis' WHERE id=2")
    conn.commit()
    assert auditoria.verificar_cadeia(conn) is False

def test_remocao_de_linha_detectada(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    for i in range(3):
        _registrar(conn, None, f"teste.evento{i}")
    conn.execute("DELETE FROM audit_log WHERE id=2")
    conn.commit()
    assert auditoria.verificar_cadeia(conn) is False

def test_login_e_logout_auditados(client):
    uid = _seed()
    corpo = _login(client)
    assert client.post("/api/auth/logout",
                       headers={"X-CSRF-Token": corpo["csrf"]}).status_code == 200

    conn = db.get_conn()
    linhas = conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
    integra = auditoria.verificar_cadeia(conn)
    conn.close()

    assert [l["acao"] for l in linhas] == ["auth.login", "auth.logout"]
    assert all(l["usuario_id"] == uid for l in linhas)
    assert integra is True

def test_logout_sem_sessao_nao_audita(client):
    _seed()
    assert client.post("/api/auth/logout").status_code == 200
    conn = db.get_conn()
    n = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    conn.close()
    assert n == 0

def test_login_falho_audita_sem_vazar_senha(client):
    # tentativa recusada tem que deixar rastro (forca bruta / conta bloqueada),
    # mas o evento so pode conter o e-mail -- nunca a senha tentada.
    _seed()
    assert client.post("/api/auth/login",
                       json={"email": "LEO@Lotufo.com", "senha": "senha-secreta-errada"}).status_code == 401
    conn = db.get_conn()
    linhas = conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
    integra = auditoria.verificar_cadeia(conn)
    conn.close()

    assert [l["acao"] for l in linhas] == ["auth.login_falha"]
    assert linhas[0]["usuario_id"] is None  # nao ha sessao: nao se sabe "quem"
    assert linhas[0]["entidade"] == "usuario" and linhas[0]["entidade_id"] is None
    # normalizado; #418: com a origem e o navegador de quem tentou (o TestClient se apresenta como "testclient")
    assert json.loads(linhas[0]["depois"]) == {"email": "leo@lotufo.com", "origem": "testclient", "navegador": "testclient"}
    assert integra is True
    # nenhuma coluna do log pode conter a senha tentada
    assert all("senha-secreta-errada" not in str(dict(l)) for l in linhas)

def test_login_falho_de_email_inexistente_tambem_audita(client):
    _seed()
    assert client.post("/api/auth/login",
                       json={"email": "ninguem@lotufo.com", "senha": "x"}).status_code == 401
    conn = db.get_conn()
    linhas = conn.execute("SELECT acao, depois FROM audit_log").fetchall()
    integra = auditoria.verificar_cadeia(conn)
    conn.close()
    assert [l["acao"] for l in linhas] == ["auth.login_falha"]
    assert json.loads(linhas[0]["depois"]) == {"email": "ninguem@lotufo.com", "origem": "testclient", "navegador": "testclient"}
    assert integra is True

def test_lockout_produz_sequencia_de_falhas_com_cadeia_integra(client):
    # 5 senhas erradas bloqueiam a conta; a 6a tentativa (senha certa) tambem
    # falha. Todas as 6 viram evento e a cadeia continua fechada.
    _seed()
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "leo@lotufo.com", "senha": "errada"})
    assert client.post("/api/auth/login",
                       json={"email": "leo@lotufo.com", "senha": "senha-forte-123"}).status_code == 401
    conn = db.get_conn()
    acoes = [l["acao"] for l in conn.execute("SELECT acao FROM audit_log ORDER BY id")]
    integra = auditoria.verificar_cadeia(conn)
    conn.close()
    assert acoes == ["auth.login_falha"] * 6
    assert integra is True

def test_endpoint_auditoria_admin(client):
    _seed(perfil="admin")
    _login(client)
    r = client.get("/api/admin/auditoria")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["cadeia_integra"] is True
    assert corpo["eventos"][0]["acao"] == "auth.login"
    assert "hash" in corpo["eventos"][0]

def test_endpoint_auditoria_ordem_desc_e_limite(client):
    _seed(perfil="admin")
    _login(client)
    conn = db.get_conn()
    for i in range(5):
        _registrar(conn, None, f"teste.evento{i}")
    conn.close()

    r = client.get("/api/admin/auditoria", params={"limite": 3})
    eventos = r.json()["eventos"]
    assert len(eventos) == 3
    assert [e["acao"] for e in eventos] == ["teste.evento4", "teste.evento3", "teste.evento2"]

def test_endpoint_auditoria_limite_teto_500(client):
    _seed(perfil="admin")
    _login(client)
    # acima do teto agora e rejeitado pela validacao (le=500), nao mais grampeado
    assert client.get("/api/admin/auditoria", params={"limite": 100000}).status_code == 422
    # o proprio teto (500) e aceito
    r = client.get("/api/admin/auditoria", params={"limite": 500})
    assert r.status_code == 200
    assert len(r.json()["eventos"]) <= 500

def test_endpoint_auditoria_403_sem_permissao(client):
    _seed(perfil="engenharia")
    _login(client)
    r = client.get("/api/admin/auditoria")
    assert r.status_code == 403
    assert "administrar" in r.json()["detail"]

def test_endpoint_auditoria_401_sem_sessao(client):
    assert client.get("/api/admin/auditoria").status_code == 401

def test_endpoint_auditoria_denuncia_adulteracao(client):
    _seed(perfil="admin")
    _login(client)
    conn = db.get_conn()
    conn.execute("UPDATE audit_log SET acao='hackeado' WHERE id=1")
    conn.commit()
    conn.close()
    assert client.get("/api/admin/auditoria").json()["cadeia_integra"] is False

def test_apenas_admin_tem_permissao_administrar():
    assert {p for p, perms in PERFIS.items() if "administrar" in perms} == {"admin"}

def test_auditoria_limite_negativo_rejeitado(client_admin):
    # limite=-1 viraria "LIMIT -1" (sem limite) no SQLite: a validacao do FastAPI
    # (ge=1) tem que rejeitar com 422 antes de chegar ao banco.
    r = client_admin.get("/api/admin/auditoria", params={"limite": -1})
    assert r.status_code == 422, r.text

def test_registrar_dict_vazio_preservado(tmp_path, monkeypatch):
    # dict vazio {} nao pode virar NULL: precisa ser distinguivel de "nao informado".
    conn = _conn(tmp_path, monkeypatch)
    _registrar(conn, None, "teste.acao", antes={}, depois={})
    r = conn.execute("SELECT antes, depois FROM audit_log").fetchone()
    assert r["antes"] == "{}"
    assert r["depois"] == "{}"
    assert auditoria.verificar_cadeia(conn) is True
