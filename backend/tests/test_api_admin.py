import datetime

from app import auth, db


def test_contas_microsoft_lista_quem_conectou(client_admin, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_TOKENS_DIR", str(tmp_path / "tokens"))
    conn = db.get_conn()
    maria = auth.criar_usuario(conn, "Maria", "maria@lotufo.com", "senha-forte-123", "engenharia")
    conn.close()
    (tmp_path / "tokens").mkdir()
    (tmp_path / "tokens" / f"usuario-{maria}.txt").write_text("refresh-token", encoding="utf-8")

    r = client_admin.get("/api/admin/contas-microsoft")
    assert r.status_code == 200, r.text
    por_email = {c["email"]: c for c in r.json()}
    assert por_email["maria@lotufo.com"]["conectada"] is True
    assert por_email["maria@lotufo.com"]["token_em"]
    assert por_email["admin@lotufo.com"] == {**por_email["admin@lotufo.com"], "conectada": False, "token_em": None}


def _gravar_eventos(n):
    from app import auditoria
    conn = db.get_conn()
    with db.mutacao(conn):
        for i in range(n):
            auditoria.registrar(conn, None, f"teste.evento{i}")
    conn.close()


def test_auditoria_cursor_devolve_todos_os_eventos_sem_repetir(client_admin):
    # 600 eventos (mais os do login do admin): duas chamadas com cursor percorrem tudo, ate' o primeiro
    _gravar_eventos(600)
    conn = db.get_conn()
    total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    conn.close()
    p1 =client_admin.get("/api/admin/auditoria", params={"limite": 500}).json()
    assert len(p1["eventos"]) == 500 and p1["ha_mais"] is True
    p2 = client_admin.get("/api/admin/auditoria",
                          params={"limite": 500, "antes_de": p1["eventos"][-1]["id"]}).json()
    ids = [e["id"] for e in p1["eventos"] + p2["eventos"]]
    assert len(ids) == total == len(set(ids))
    assert p2["ha_mais"] is False
    assert p2["eventos"][-1]["id"] == 1
    # a cadeia inteira e' verificada so' na primeira pagina; as seguintes nao repetem o custo
    assert p1["cadeia_integra"] is True and p2["cadeia_integra"] is None


def test_auditoria_ha_mais_falso_quando_a_pagina_pega_o_ultimo(client_admin):
    conn = db.get_conn()
    total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    conn.close()
    r = client_admin.get("/api/admin/auditoria", params={"limite": total}).json()
    assert len(r["eventos"]) == total and r["ha_mais"] is False


def test_auditoria_cursor_invalido_e_422_nao_500(client_admin):
    for cursor in (0, -1, 2 ** 63):
        assert client_admin.get("/api/admin/auditoria", params={"antes_de": cursor}).status_code == 422


def test_saude_do_backup_so_para_admin(client_admin):
    # issue #31: Administracao > Saude le o backup por rota de admin (o /api/health e' aberto)
    from app import backup
    pasta = backup.pasta_local()
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "dashboard-20261013-070000.db").write_bytes(b"x" * 100)
    r = client_admin.get("/api/admin/backup")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["guardados"] == 1 and corpo["tamanho_bytes"] == 100
    assert corpo["atrasado"] is False and corpo["ultimo_backup"]

    client_admin.post("/api/admin/usuarios", json={"nome": "Eng", "email": "eng@lotufo.com",
                                                   "senha": "senha-eng-123", "perfil": "engenharia"})
    r = client_admin.post("/api/auth/login", json={"email": "eng@lotufo.com", "senha": "senha-eng-123"})
    client_admin.cookies.clear()
    client_admin.cookies.set("sessao", r.cookies["sessao"])
    client_admin.headers["X-CSRF-Token"] = r.json()["csrf"]
    assert client_admin.get("/api/admin/backup").status_code == 403


def test_auditoria_traz_a_obra_da_medicao_e_do_protocolo(client_admin):
    from app import auditoria
    from tests.conftest import novo_contrato
    cid = novo_contrato({"orgao": "SINFRA", "numero_instrumento": "IC 1/2026", "objeto": "Obra",
                         "valor_original": "100.000,00"})
    mid = client_admin.post(f"/api/contratos/{cid}/medicoes",
                            json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"}).json()["id"]
    conn = db.get_conn()
    with db.mutacao(conn):
        pid = conn.execute("INSERT INTO protocolos (contrato_id, etapa, natureza, usuario_id) VALUES (?,?,?,1)",
                           (cid, "unico", "execucao")).lastrowid
        auditoria.registrar(conn, None, "protocolo.criar", "protocolo", pid)
        auditoria.registrar(conn, None, "medicao.protocolo", "medicao", 99999)  # medicao que nao existe mais
    conn.close()
    por_acao = {e["acao"]: e for e in client_admin.get("/api/admin/auditoria").json()["eventos"]}
    assert por_acao["medicao.criar"]["entidade_id"] == str(mid) and por_acao["medicao.criar"]["contrato_id"] == cid
    assert por_acao["protocolo.criar"]["contrato_id"] == cid
    assert por_acao["medicao.protocolo"]["contrato_id"] is None
    assert por_acao["auth.login"]["contrato_id"] is None


def test_saude_traz_a_ultima_leitura_os_processos_e_o_atraso_do_monitor_do_siga(client_admin, monkeypatch):
    # issue #330: sem leitura, nulo; com leitura, o instante (UTC, com fuso explicito), a contagem e se esta' atrasado
    from app import tempo
    UTC = datetime.timezone.utc
    agora = datetime.datetime(2026, 10, 28, 16, 0, tzinfo=UTC)          # quarta, 12h00 em Cuiaba
    monkeypatch.setattr(tempo, "agora_utc", lambda: agora)
    assert client_admin.get("/api/admin/saude").json()["siga"] == {
        "ultima_leitura": None, "atrasado": False, "processos": 0}
    conn = db.get_conn()
    with db.mutacao(conn):
        for numero, lido in (("SINFRA-PRO-2026/00001", "2026-10-28 14:00:00"), ("SINFRA-PRO-2026/00002", "2026-10-28 15:15:00")):
            pid = conn.execute("INSERT INTO siga_processos (numero) VALUES (?)", (numero,)).lastrowid
            conn.execute("INSERT INTO siga_leituras (processo_id, lido_em) VALUES (?,?)", (pid, lido))
    conn.close()
    r = client_admin.get("/api/admin/saude")
    assert r.status_code == 200, r.text
    assert r.json()["siga"] == {"ultima_leitura": "2026-10-28T15:15:00+00:00", "atrasado": False, "processos": 2}
    monkeypatch.setattr(tempo, "agora_utc", lambda: agora + datetime.timedelta(hours=2))   # 14h00: 2h45 sem leitura
    assert client_admin.get("/api/admin/saude").json()["siga"]["atrasado"] is True


def test_saude_so_para_admin(client_admin):
    client_admin.post("/api/admin/usuarios", json={"nome": "Eng", "email": "eng@lotufo.com",
                                                   "senha": "senha-eng-123", "perfil": "engenharia"})
    r = client_admin.post("/api/auth/login", json={"email": "eng@lotufo.com", "senha": "senha-eng-123"})
    client_admin.cookies.clear()
    client_admin.cookies.set("sessao", r.cookies["sessao"])
    client_admin.headers["X-CSRF-Token"] = r.json()["csrf"]
    assert client_admin.get("/api/admin/saude").status_code == 403


# --- #418: bloco Seguranca da Saude: administrador entrando de uma origem nova -------------------------

from fastapi.testclient import TestClient


def _login_de(client, ip, email="admin@lotufo.com", senha="senha-forte-123"):
    r = TestClient(client.app, client=(ip, 50000)).post("/api/auth/login", json={"email": email, "senha": senha})
    assert r.status_code == 200, r.text


def _seguranca(client):
    r = client.get("/api/admin/saude")
    assert r.status_code == 200, r.text
    return r.json()["seguranca"]


def _recuar_logins(dias):
    """Os logins ja' gravados passam a ter acontecido `dias` atras (o registrar carimba com o relogio do banco)."""
    conn = db.get_conn()
    with db.mutacao(conn):
        conn.execute("UPDATE audit_log SET criado_em=datetime(criado_em, ?) WHERE acao='auth.login'", (f"-{dias} days",))
    conn.close()


def test_seguranca_avisa_administrador_que_entra_de_origem_nova(client_admin):
    # o login do client_admin e' o primeiro desse administrador: a origem dele e' nova
    itens = _seguranca(client_admin)
    assert [(i["nivel"], i["mensagem"]) for i in itens] == [
        ("acao", "Administrador Admin entrou de uma origem nova (testclient)")]
    assert itens[0]["data"].endswith("+00:00")
    _login_de(client_admin, "10.0.0.51")
    _login_de(client_admin, "10.0.0.51")                    # a segunda vez a origem ja' foi vista: um item so'
    assert [i["mensagem"] for i in _seguranca(client_admin)] == [
        "Administrador Admin entrou de uma origem nova (10.0.0.51)",
        "Administrador Admin entrou de uma origem nova (testclient)"]


def test_seguranca_nao_avisa_origem_vista_nos_30_dias_anteriores(client_admin):
    _login_de(client_admin, "10.0.0.52")
    _recuar_logins(10)                                      # testclient e 10.0.0.52 vistos ha' 10 dias
    _login_de(client_admin, "10.0.0.52")
    assert _seguranca(client_admin) == []


def test_seguranca_avisa_origem_vista_so_antes_dos_30_dias(client_admin):
    _recuar_logins(31)                                      # testclient visto ha' 31 dias: fora da janela
    _login_de(client_admin, "testclient")
    assert [i["mensagem"] for i in _seguranca(client_admin)] == [
        "Administrador Admin entrou de uma origem nova (testclient)"]


def test_seguranca_item_fica_7_dias(client_admin, monkeypatch):
    from app import tempo
    agora = tempo.agora_utc()
    monkeypatch.setattr(tempo, "agora_utc", lambda: agora + datetime.timedelta(days=6, hours=23))
    assert len(_seguranca(client_admin)) == 1
    monkeypatch.setattr(tempo, "agora_utc", lambda: agora + datetime.timedelta(days=7, minutes=1))
    assert _seguranca(client_admin) == []


def test_seguranca_nao_avisa_quem_nao_e_administrador_nem_login_falho(client_admin):
    for perfil in ("engenharia", "diretoria"):
        client_admin.post("/api/admin/usuarios", json={"nome": perfil, "email": f"{perfil}@lotufo.com",
                                                       "senha": "senha-forte-123", "perfil": perfil})
        _login_de(client_admin, "10.0.0.53", f"{perfil}@lotufo.com")
    r = TestClient(client_admin.app, client=("10.0.0.54", 50000)).post(
        "/api/auth/login", json={"email": "admin@lotufo.com", "senha": "senha-errada-1"})
    assert r.status_code == 401
    assert [i["mensagem"] for i in _seguranca(client_admin)] == [
        "Administrador Admin entrou de uma origem nova (testclient)"]


def test_seguranca_negada_a_engenharia_e_diretoria(client_admin):
    for perfil in ("engenharia", "diretoria"):
        client_admin.post("/api/admin/usuarios", json={"nome": perfil, "email": f"{perfil}@lotufo.com",
                                                       "senha": "senha-forte-123", "perfil": perfil})
        c = TestClient(client_admin.app)
        r = c.post("/api/auth/login", json={"email": f"{perfil}@lotufo.com", "senha": "senha-forte-123"})
        c.cookies.set("sessao", r.cookies["sessao"])
        assert c.get("/api/admin/saude").status_code == 403


def _novo(client, nome, email, perfil):
    r = client.post("/api/admin/usuarios", json={"nome": nome, "email": email, "senha": "senha-forte-123", "perfil": perfil})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_seguranca_vale_o_perfil_no_momento_do_login(client_admin):
    # Gate Sol S2: promovida depois do login nao vira "Administrador entrou"; rebaixada depois continua avisando
    promovida = _novo(client_admin, "Promovida", "promovida@lotufo.com", "engenharia")
    rebaixada = _novo(client_admin, "Rebaixada", "rebaixada@lotufo.com", "admin")
    _login_de(client_admin, "10.0.0.61", "promovida@lotufo.com")
    _login_de(client_admin, "10.0.0.62", "rebaixada@lotufo.com")
    assert client_admin.put(f"/api/admin/usuarios/{promovida}", json={"perfil": "admin"}).status_code == 200
    assert client_admin.put(f"/api/admin/usuarios/{rebaixada}", json={"perfil": "engenharia"}).status_code == 200
    assert [i["mensagem"] for i in _seguranca(client_admin)] == [
        "Administrador Rebaixada entrou de uma origem nova (10.0.0.62)",
        "Administrador Admin entrou de uma origem nova (testclient)"]
    # ja' administradora: a origem que ela usou como engenharia nos 30 dias anteriores conta como vista; outra, nao
    _login_de(client_admin, "10.0.0.61", "promovida@lotufo.com")
    _login_de(client_admin, "10.0.0.63", "promovida@lotufo.com")
    assert [i["mensagem"] for i in _seguranca(client_admin)][0] == "Administrador Promovida entrou de uma origem nova (10.0.0.63)"
    assert len(_seguranca(client_admin)) == 3


def test_seguranca_login_sem_perfil_gravado_usa_o_perfil_de_hoje(client_admin):
    # login gravado antes do perfil ir para o evento: vale o perfil atual da pessoa
    from app import auditoria
    eng = _novo(client_admin, "Engenheira da obra", "eng@lotufo.com", "engenharia")
    admin_id = client_admin.get("/api/auth/eu").json()["id"]
    conn = db.get_conn()
    with db.mutacao(conn):
        auditoria.registrar(conn, admin_id, "auth.login", depois={"origem": "10.0.0.64", "navegador": None})
        auditoria.registrar(conn, eng, "auth.login", depois={"origem": "10.0.0.65", "navegador": None})
    conn.close()
    assert [i["mensagem"] for i in _seguranca(client_admin)] == [
        "Administrador Admin entrou de uma origem nova (10.0.0.64)",
        "Administrador Admin entrou de uma origem nova (testclient)"]


def test_seguranca_devolve_no_maximo_20_e_diz_quantos_ficaram_de_fora(client_admin):
    # Gate Sol S3: a lista tem teto; o que passa dele vira contagem
    from app import auditoria, seguranca
    assert client_admin.get("/api/admin/saude").json()["seguranca_fora"] == 0
    admin_id = client_admin.get("/api/auth/eu").json()["id"]
    conn = db.get_conn()
    with db.mutacao(conn):
        for i in range(25):
            auditoria.registrar(conn, admin_id, "auth.login",
                                depois={"origem": f"10.0.3.{i}", "navegador": None, "perfil": "admin"})
    conn.close()
    corpo = client_admin.get("/api/admin/saude").json()
    assert seguranca.ITENS_NA_TELA == 20
    assert (len(corpo["seguranca"]), corpo["seguranca_fora"]) == (20, 6)       # 25 + o login do client_admin
    assert corpo["seguranca"][0]["mensagem"].endswith("(10.0.3.24)")            # do mais novo ao mais antigo


def test_copia_dono_botao_so_admin_e_sem_chave_nao_gera(client_admin):
    # issue #419: sem chave publica, o botao responde "Cópia do dono não configurada" e nada e' gerado
    from app import backup
    r = client_admin.post("/api/admin/copia-dono")
    assert r.status_code == 409 and r.json()["detail"] == "Cópia do dono não configurada"
    assert not (backup.pasta_local() / "dono").exists()
    s = client_admin.get("/api/admin/backup").json()
    assert s["copia_dono_configurada"] is False and s["ultima_copia_dono"] is None

    client_admin.post("/api/admin/usuarios", json={"nome": "Eng", "email": "eng@lotufo.com",
                                                   "senha": "senha-eng-123", "perfil": "engenharia"})
    r = client_admin.post("/api/auth/login", json={"email": "eng@lotufo.com", "senha": "senha-eng-123"})
    client_admin.cookies.clear()
    client_admin.cookies.set("sessao", r.cookies["sessao"])
    client_admin.headers["X-CSRF-Token"] = r.json()["csrf"]
    assert client_admin.post("/api/admin/copia-dono").status_code == 403


def test_copia_dono_botao_gera_e_a_saude_mostra_a_data(client_admin, tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("pyrage")
    from pyrage import x25519
    from app import backup, db
    chave = tmp_path / "chave-publica-dono.txt"  # fora de pastas compartilhadas entre testes
    chave.write_text(str(x25519.Identity.generate().to_public()), encoding="utf-8")
    monkeypatch.setenv("DASH_CHAVE_PUBLICA_DONO", str(chave))
    monkeypatch.delenv("DASH_CADASTRO_DIR", raising=False)  # nunca empacota o cadastro real
    backup.criar_snapshot(db.db_path(), backup.pasta_local())
    r = client_admin.post("/api/admin/copia-dono")
    assert r.status_code == 200, r.text
    assert (backup.pasta_local() / "dono" / r.json()["arquivo"]).exists()
    s = client_admin.get("/api/admin/backup").json()
    assert s["copia_dono_configurada"] is True and s["ultima_copia_dono"] and s["copia_dono_atrasada"] is False
    assert "ultima_copia_dono" in backup.estado()
