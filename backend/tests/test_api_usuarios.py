def test_criar_usuario_e_listar(client_admin):
    r = client_admin.post("/api/admin/usuarios", json={
        "nome": "Maria", "email": "maria@lotufo.com",
        "senha": "outra-senha-123", "perfil": "engenharia"})
    assert r.status_code == 201
    lista = client_admin.get("/api/admin/usuarios").json()
    assert any(u["email"] == "maria@lotufo.com" for u in lista)
    assert all("senha_hash" not in u for u in lista)

def test_nao_admin_negado(client_admin, client):
    client_admin.post("/api/admin/usuarios", json={
        "nome": "Eng", "email": "eng@lotufo.com", "senha": "senha-eng-123", "perfil": "engenharia"})
    r = client.post("/api/auth/login", json={"email": "eng@lotufo.com", "senha": "senha-eng-123"})
    # ADAPTACAO ao brief: `client_admin` devolve o MESMO TestClient de `client`, e o
    # cookie secure=True do login nao volta sozinho em http://testserver. Sem injetar
    # a sessao da engenharia na jar, a requisicao abaixo seguiria com o cookie do
    # admin e daria 200 -- o teste passaria pelo motivo errado. Mesmo tratamento
    # usado em test_permissoes.py e test_api_contratos.py.
    client.cookies.set("sessao", r.cookies["sessao"])
    client.headers["X-CSRF-Token"] = r.json()["csrf"]
    assert client.get("/api/admin/usuarios").status_code == 403


# --- erros tratados (fix round 1) --------------------------------------------

NOVO = {"nome": "Maria", "email": "maria@lotufo.com",
        "senha": "outra-senha-123", "perfil": "engenharia"}

def test_email_duplicado_409(client_admin):
    assert client_admin.post("/api/admin/usuarios", json=NOVO).status_code == 201
    r = client_admin.post("/api/admin/usuarios", json={**NOVO, "nome": "Outra"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "E-mail já cadastrado"

def test_email_duplicado_nao_audita_nem_quebra_cadeia(client_admin):
    client_admin.post("/api/admin/usuarios", json=NOVO)
    client_admin.post("/api/admin/usuarios", json={**NOVO, "nome": "Outra"})
    a = client_admin.get("/api/admin/auditoria").json()
    assert a["cadeia_integra"] is True
    # a tentativa recusada nao pode deixar rastro de criacao no log
    assert len([e for e in a["eventos"] if e["acao"] == "usuario.criar"]) == 1

def test_put_perfil_invalido_422(client_admin):
    uid = client_admin.post("/api/admin/usuarios", json=NOVO).json()["id"]
    r = client_admin.put(f"/api/admin/usuarios/{uid}", json={"perfil": "faxineiro"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "Perfil inválido"
    # perfil intacto no banco
    lista = client_admin.get("/api/admin/usuarios").json()
    assert next(u for u in lista if u["id"] == uid)["perfil"] == "engenharia"

def test_put_perfil_valido_muda(client_admin):
    uid = client_admin.post("/api/admin/usuarios", json=NOVO).json()["id"]
    assert client_admin.put(f"/api/admin/usuarios/{uid}",
                            json={"perfil": "diretoria"}).status_code == 200
    lista = client_admin.get("/api/admin/usuarios").json()
    assert next(u for u in lista if u["id"] == uid)["perfil"] == "diretoria"

def test_admin_nao_se_desativa_nem_tira_o_proprio_perfil(client_admin):
    eu = client_admin.get("/api/auth/eu").json()["id"]
    for corpo in ({"ativo": False}, {"perfil": "engenharia"}):
        r = client_admin.put(f"/api/admin/usuarios/{eu}", json=corpo)
        assert r.status_code == 409, r.text
    u = next(u for u in client_admin.get("/api/admin/usuarios").json() if u["id"] == eu)
    assert (u["ativo"], u["perfil"]) == (1, "admin")

def test_com_outro_admin_ativo_desativar_admin_continua_valendo(client_admin):
    uid = client_admin.post("/api/admin/usuarios", json={**NOVO, "perfil": "admin"}).json()["id"]
    assert client_admin.put(f"/api/admin/usuarios/{uid}", json={"ativo": False}).status_code == 200

def test_put_usuario_inexistente_404(client_admin):
    r = client_admin.put("/api/admin/usuarios/99999", json={"perfil": "diretoria"})
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "Usuário não encontrado"


# --- fix round 1: a linha some ENTRE o 404 externo e o BEGIN IMMEDIATE --------

import pytest
from fastapi import HTTPException

from app import api_usuarios, auth, db


class _CursorVazio:
    def fetchone(self):
        return None
    def fetchall(self):
        return []


class _SumiuNoMeio:
    """Passa pelo 404 externo e devolve None na leitura de DENTRO do envelope."""
    def __init__(self, real):
        self._real, self._armada = real, True
    def execute(self, sql, params=()):
        if self._armada and sql.lstrip().upper().startswith("SELECT PERFIL, ATIVO"):
            self._armada = False
            return _CursorVazio()
        return self._real.execute(sql, params)
    def __getattr__(self, nome):
        return getattr(self._real, nome)


def test_put_usuario_apagado_no_meio_vira_404_e_nao_500(tmp_path, monkeypatch):
    """`dict(None)` daria TypeError dentro do handler -> 500 sem mensagem nenhuma."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn(); db.migrate(conn)
    uid = auth.criar_usuario(conn, "Alvo", "alvo@l.com", "senha-forte-123", "engenharia")
    try:
        with pytest.raises(HTTPException) as e:
            # quem pede e' outro admin: o proprio alvo cairia na trava do auto-desativar (409)
            api_usuarios.atualizar(uid, api_usuarios.UsuarioPatch(perfil="diretoria"),
                                   {"id": uid + 1}, _SumiuNoMeio(conn))
        assert e.value.status_code == 404
        assert e.value.detail == "Usuário não encontrado"
        assert not conn.in_transaction  # envelope desfeito, sem lock pendurado
        assert conn.execute("SELECT perfil FROM usuarios WHERE id=?",
                            (uid,)).fetchone()["perfil"] == "engenharia"
    finally:
        conn.close()


def test_ultimo_admin_ativo_nao_sai_nem_em_corrida(tmp_path, monkeypatch):
    """Issue #28 (revisor): dois admins se desativando ao mesmo tempo -- o `exigir` de cada um confere ANTES
    do BEGIN IMMEDIATE. Aqui o pedido de A chega depois de B ja' ter desativado A; desativar ou rebaixar B
    deixaria o sistema sem administrador ativo."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn(); db.migrate(conn)
    a = auth.criar_usuario(conn, "Admin A", "a@l.com", "senha-forte-123", "admin")
    b = auth.criar_usuario(conn, "Admin B", "b@l.com", "senha-forte-123", "admin")
    conn.execute("UPDATE usuarios SET ativo=0 WHERE id=?", (a,)); conn.commit()
    try:
        for corpo in (api_usuarios.UsuarioPatch(ativo=False), api_usuarios.UsuarioPatch(perfil="engenharia")):
            with pytest.raises(HTTPException) as e:
                api_usuarios.atualizar(b, corpo, {"id": a}, conn)
            assert e.value.status_code == 409
            assert not conn.in_transaction
        r = conn.execute("SELECT perfil, ativo FROM usuarios WHERE id=?", (b,)).fetchone()
        assert (r["perfil"], r["ativo"]) == ("admin", 1)
    finally:
        conn.close()


def test_rota_com_banco_travado_vira_503(client_admin, monkeypatch):
    """Lock alem do busy_timeout: 503 pt-BR em vez de OperationalError crua (500).

    Com a mutacao inteira sob BEGIN IMMEDIATE, este erro passou a ser possivel de
    verdade -- o segundo escritor espera o lock. A resposta tem que dizer que nada foi
    gravado e que da para repetir.
    """
    real = db.get_conn
    def com_espera_curta():
        c = real()
        c.execute("PRAGMA busy_timeout=100")  # nao segurar o teste por 5s
        return c
    monkeypatch.setattr(db, "get_conn", com_espera_curta)

    travadora = real()
    travadora.execute("BEGIN IMMEDIATE")  # segura o lock de escrita
    try:
        r = client_admin.post("/api/admin/usuarios", json=NOVO)
        assert r.status_code == 503, r.text
        assert r.json()["detail"] == "Banco de dados ocupado — tente novamente em instantes."
        assert r.headers["Retry-After"] == "1"
    finally:
        travadora.rollback()
        travadora.close()


# --- A-05 + B-10 (testes de quebra 10/10/2026): desbloquear, redefinir e trocar senha ------

def _entrar(client, email, senha):
    """Loga e devolve (token, csrf), deixando o client com essa sessao."""
    r = client.post("/api/auth/login", json={"email": email, "senha": senha})
    assert r.status_code == 200, r.text
    token, csrf = r.cookies["sessao"], r.json()["csrf"]
    _como(client, token, csrf)
    return token, csrf

def _como(client, token, csrf):
    # a jar guarda tambem o cookie da resposta do login (dominio proprio): limpar antes evita
    # dois "sessao" e o CookieConflict do httpx
    client.cookies.clear()
    client.cookies.set("sessao", token)
    client.headers["X-CSRF-Token"] = csrf

def _bloquear(email):
    for _ in range(5):
        conn = db.get_conn()
        try:
            auth.autenticar(conn, email, "senha-errada-xx")
        finally:
            conn.close()

def test_listar_devolve_bloqueio_e_tentativas(client_admin):
    uid = client_admin.post("/api/admin/usuarios", json=NOVO).json()["id"]
    u = next(u for u in client_admin.get("/api/admin/usuarios").json() if u["id"] == uid)
    assert (u["bloqueado_ate"], u["tentativas_falhas"]) == (None, 0)
    _bloquear(NOVO["email"])
    u = next(u for u in client_admin.get("/api/admin/usuarios").json() if u["id"] == uid)
    assert u["bloqueado_ate"] is not None and u["bloqueado_ate"].endswith("-04:00")  # hora de Cuiaba
    assert u["tentativas_falhas"] == 0

def test_desbloquear_volta_o_login(client_admin):
    uid = client_admin.post("/api/admin/usuarios", json=NOVO).json()["id"]
    admin = _entrar(client_admin, "admin@lotufo.com", "senha-forte-123")
    _bloquear(NOVO["email"])
    assert client_admin.post("/api/auth/login", json={"email": NOVO["email"], "senha": NOVO["senha"]}).status_code == 401
    _como(client_admin, *admin)
    r = client_admin.post(f"/api/admin/usuarios/{uid}/desbloquear")
    assert r.status_code == 200, r.text
    assert client_admin.post("/api/auth/login", json={"email": NOVO["email"], "senha": NOVO["senha"]}).status_code == 200
    _como(client_admin, *admin)
    acoes = [e["acao"] for e in client_admin.get("/api/admin/auditoria").json()["eventos"]]
    assert "usuario.desbloquear" in acoes

def test_desbloquear_inexistente_404(client_admin):
    assert client_admin.post("/api/admin/usuarios/99999/desbloquear").status_code == 404

def test_redefinir_senha_derruba_sessoes_e_a_nova_entra(client_admin):
    uid = client_admin.post("/api/admin/usuarios", json=NOVO).json()["id"]
    admin = _entrar(client_admin, "admin@lotufo.com", "senha-forte-123")
    antiga1 = _entrar(client_admin, NOVO["email"], NOVO["senha"])
    antiga2 = _entrar(client_admin, NOVO["email"], NOVO["senha"])
    _como(client_admin, *admin)
    assert client_admin.post(f"/api/admin/usuarios/{uid}/senha", json={"senha": "curta"}).status_code == 422
    r = client_admin.post(f"/api/admin/usuarios/{uid}/senha", json={"senha": "senha-nova-456"})
    assert r.status_code == 200, r.text
    for s in (antiga1, antiga2):
        _como(client_admin, *s)
        assert client_admin.get("/api/auth/eu").status_code == 401
    assert client_admin.post("/api/auth/login", json={"email": NOVO["email"], "senha": NOVO["senha"]}).status_code == 401
    _entrar(client_admin, NOVO["email"], "senha-nova-456")
    _como(client_admin, *admin)
    eventos = [e for e in client_admin.get("/api/admin/auditoria").json()["eventos"] if e["acao"] == "usuario.senha_redefinida"]
    assert len(eventos) == 1 and "senha-nova-456" not in str(eventos[0])

def test_redefinir_senha_zera_bloqueio(client_admin):
    uid = client_admin.post("/api/admin/usuarios", json=NOVO).json()["id"]
    _bloquear(NOVO["email"])
    assert client_admin.post(f"/api/admin/usuarios/{uid}/senha", json={"senha": "senha-nova-456"}).status_code == 200
    assert client_admin.post("/api/auth/login", json={"email": NOVO["email"], "senha": "senha-nova-456"}).status_code == 200

def test_rotas_novas_de_admin_negadas_a_diretoria_e_engenharia(client_admin):
    alvo = client_admin.post("/api/admin/usuarios", json=NOVO).json()["id"]
    for perfil in ("diretoria", "engenharia"):
        email = f"{perfil}@lotufo.com"
        client_admin.post("/api/admin/usuarios", json={"nome": perfil, "email": email,
                                                       "senha": "senha-forte-123", "perfil": perfil})
        admin = _entrar(client_admin, "admin@lotufo.com", "senha-forte-123")
        _entrar(client_admin, email, "senha-forte-123")
        assert client_admin.post(f"/api/admin/usuarios/{alvo}/desbloquear").status_code == 403
        assert client_admin.post(f"/api/admin/usuarios/{alvo}/senha", json={"senha": "senha-nova-456"}).status_code == 403
        assert client_admin.put(f"/api/admin/usuarios/{alvo}", json={"perfil": "admin"}).status_code == 403
        _como(client_admin, *admin)

def test_trocar_a_propria_senha(client_admin):
    client_admin.post("/api/admin/usuarios", json=NOVO)
    outra = _entrar(client_admin, NOVO["email"], NOVO["senha"])
    _entrar(client_admin, NOVO["email"], NOVO["senha"])
    r = client_admin.post("/api/auth/senha", json={"senha_atual": "errada-errada", "senha_nova": "senha-nova-456"})
    assert r.status_code == 422, r.text
    r = client_admin.post("/api/auth/senha", json={"senha_atual": NOVO["senha"], "senha_nova": "curta"})
    assert r.status_code == 422, r.text
    r = client_admin.post("/api/auth/senha", json={"senha_atual": NOVO["senha"], "senha_nova": NOVO["senha"]})
    assert r.status_code == 422, r.text
    r = client_admin.post("/api/auth/senha", json={"senha_atual": NOVO["senha"], "senha_nova": "senha-nova-456"})
    assert r.status_code == 200, r.text
    assert client_admin.get("/api/auth/eu").status_code == 200  # a sessao atual continua
    _como(client_admin, *outra)
    assert client_admin.get("/api/auth/eu").status_code == 401  # as outras caem
    assert client_admin.post("/api/auth/login", json={"email": NOVO["email"], "senha": NOVO["senha"]}).status_code == 401
    _entrar(client_admin, NOVO["email"], "senha-nova-456")

def test_trocar_senha_exige_csrf(client_admin):
    client_admin.post("/api/admin/usuarios", json=NOVO)
    _entrar(client_admin, NOVO["email"], NOVO["senha"])
    del client_admin.headers["X-CSRF-Token"]
    r = client_admin.post("/api/auth/senha", json={"senha_atual": NOVO["senha"], "senha_nova": "senha-nova-456"})
    assert r.status_code == 403


# --- #418: ultimos acessos de cada pessoa (Administracao > Usuarios e Minha conta) ------------------

from fastapi.testclient import TestClient

from app import auditoria, seguranca

FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0"

def _login_de(client, ip, email, senha, ua="testclient"):
    """Login vindo de outro IP, na MESMA app (o banco e' o mesmo); nao mexe na sessao do `client`."""
    return TestClient(client.app, client=(ip, 50000)).post(
        "/api/auth/login", json={"email": email, "senha": senha}, headers={"User-Agent": ua})

def test_ultimos_acessos_da_pessoa_com_sucesso_e_falha_do_mais_novo_ao_mais_antigo(client_admin):
    uid = client_admin.post("/api/admin/usuarios", json=NOVO).json()["id"]
    assert _login_de(client_admin, "10.0.0.31", NOVO["email"], "senha-errada-1").status_code == 401
    assert _login_de(client_admin, "10.0.0.32", NOVO["email"], NOVO["senha"], FIREFOX_LINUX).status_code == 200
    # falha de outro e-mail e login de outra pessoa nao entram na lista da Maria
    assert _login_de(client_admin, "10.0.0.33", "outra@lotufo.com", "senha-errada-1").status_code == 401
    assert _login_de(client_admin, "10.0.0.34", "admin@lotufo.com", "senha-forte-123").status_code == 200

    r = client_admin.get(f"/api/admin/usuarios/{uid}/acessos")
    assert r.status_code == 200, r.text
    acessos = r.json()
    assert [(a["sucesso"], a["origem"], a["navegador"]) for a in acessos] == [
        (True, "10.0.0.32", "Firefox no Linux"), (False, "10.0.0.31", "testclient")]
    assert all(a["data"].endswith("+00:00") for a in acessos)   # instante UTC com o fuso explicito; a tela mostra Cuiaba

def test_ultimos_acessos_sao_no_maximo_10(client_admin):
    uid = client_admin.post("/api/admin/usuarios", json=NOVO).json()["id"]
    conn = db.get_conn()
    with db.mutacao(conn):
        for i in range(12):
            auditoria.registrar(conn, uid, "auth.login", depois={"origem": f"10.0.1.{i}", "navegador": None})
    conn.close()
    acessos = client_admin.get(f"/api/admin/usuarios/{uid}/acessos").json()
    assert [a["origem"] for a in acessos] == [f"10.0.1.{i}" for i in range(11, 1, -1)]
    assert acessos[0]["navegador"] is None

def test_login_antigo_sem_origem_aparece_com_traco_e_conta_nova_nao_herda_falha_anterior(client_admin):
    # eventos de antes do #418 nao tem `depois`; a falha de um e-mail antes de a conta existir nao e' da pessoa
    conn = db.get_conn()
    with db.mutacao(conn):
        auditoria.registrar(conn, None, "auth.login_falha", "usuario", None, depois={"email": NOVO["email"]})
    conn.close()
    uid = client_admin.post("/api/admin/usuarios", json=NOVO).json()["id"]
    conn = db.get_conn()
    with db.mutacao(conn):
        conn.execute("UPDATE audit_log SET criado_em=datetime(criado_em, '-1 day') WHERE acao='auth.login_falha'")
        auditoria.registrar(conn, uid, "auth.login")
    conn.close()
    acessos = client_admin.get(f"/api/admin/usuarios/{uid}/acessos").json()
    assert [(a["sucesso"], a["origem"], a["navegador"]) for a in acessos] == [(True, None, None)]

def _falha(email):
    conn = db.get_conn()
    with db.mutacao(conn):
        auditoria.registrar(conn, None, "auth.login_falha", "usuario", None, depois={"email": email, "origem": "10.0.2.1"})
    conn.close()

def test_falha_anterior_a_conta_fica_de_fora_mesmo_no_mesmo_segundo(client_admin):
    # Gate Sol S4: a fronteira e' o evento usuario.criar (id), nao o carimbo de segundo da conta
    _falha(NOVO["email"])
    uid = client_admin.post("/api/admin/usuarios", json=NOVO).json()["id"]
    conn = db.get_conn()
    with db.mutacao(conn):   # a conta "nasceu" antes da falha pelo relogio: so' o id do evento separa as duas
        conn.execute("UPDATE usuarios SET criado_em=datetime(criado_em, '-1 day') WHERE id=?", (uid,))
    conn.close()
    _falha(NOVO["email"])
    assert [a["sucesso"] for a in client_admin.get(f"/api/admin/usuarios/{uid}/acessos").json()] == [False]

def test_conta_sem_evento_de_criacao_usa_a_data_da_conta(client_admin):
    # conta criada fora da API (CLI, primeira carga) nao tem usuario.criar: vale o criado_em dela
    _falha(NOVO["email"])
    conn = db.get_conn()
    with db.mutacao(conn):
        conn.execute("UPDATE audit_log SET criado_em=datetime(criado_em, '-1 day') WHERE acao='auth.login_falha'")
    uid = auth.criar_usuario(conn, NOVO["nome"], NOVO["email"], NOVO["senha"], NOVO["perfil"])
    conn.close()
    _falha(NOVO["email"])
    assert [a["sucesso"] for a in client_admin.get(f"/api/admin/usuarios/{uid}/acessos").json()] == [False]

def test_acessos_de_usuario_inexistente_404(client_admin):
    r = client_admin.get("/api/admin/usuarios/99999/acessos")
    assert r.status_code == 404
    assert r.json()["detail"] == "Usuário não encontrado"

def test_acessos_de_outra_pessoa_negados_a_engenharia_e_diretoria(client_admin):
    admin_id = client_admin.get("/api/auth/eu").json()["id"]
    for perfil in ("engenharia", "diretoria"):
        email = f"{perfil}@lotufo.com"
        client_admin.post("/api/admin/usuarios", json={"nome": perfil, "email": email,
                                                       "senha": "senha-forte-123", "perfil": perfil})
        admin = _entrar(client_admin, "admin@lotufo.com", "senha-forte-123")
        _entrar(client_admin, email, "senha-forte-123")
        meu_id = client_admin.get("/api/auth/eu").json()["id"]
        assert client_admin.get(f"/api/admin/usuarios/{admin_id}/acessos").status_code == 403
        # nem os proprios pela rota de administracao: os proprios saem em Minha conta
        assert client_admin.get(f"/api/admin/usuarios/{meu_id}/acessos").status_code == 403
        _como(client_admin, *admin)

def test_minha_conta_mostra_so_os_proprios_acessos(client_admin):
    client_admin.post("/api/admin/usuarios", json=NOVO)
    assert _login_de(client_admin, "10.0.0.41", NOVO["email"], "senha-errada-1").status_code == 401
    _entrar(client_admin, NOVO["email"], NOVO["senha"])
    r = client_admin.get("/api/auth/acessos")
    assert r.status_code == 200, r.text
    assert [(a["sucesso"], a["origem"]) for a in r.json()] == [(True, "testclient"), (False, "10.0.0.41")]

def test_minha_conta_sem_sessao_401(client):
    assert client.get("/api/auth/acessos").status_code == 401

@pytest.mark.parametrize("ua, resumo", [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
     "Chrome no Windows"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 "
     "Edg/130.0.0.0", "Edge no Windows"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
     "Safari no macOS"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
     "Mobile/15E148 Safari/604.1", "Safari no iOS"),
    ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
     "Chrome no Android"),
    (FIREFOX_LINUX, "Firefox no Linux"),
    ("curl/8.4.0", "curl/8.4.0"),
    ("python-requests/2.32.3", "python-requests/2.32.3"),
    ("", None),
    (None, None),
])
def test_navegador_resumido(ua, resumo):
    assert seguranca.resumir_navegador(ua) == resumo
