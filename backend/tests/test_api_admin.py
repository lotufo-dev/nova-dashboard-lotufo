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
    assert client_admin.get("/api/admin/saude").json() == {
        "siga": {"ultima_leitura": None, "atrasado": False, "processos": 0}}
    conn = db.get_conn()
    with db.mutacao(conn):
        for numero, lido in (("SINFRA-PRO-2026/00001", "2026-10-28 14:00:00"), ("SINFRA-PRO-2026/00002", "2026-10-28 15:15:00")):
            pid = conn.execute("INSERT INTO siga_processos (numero) VALUES (?)", (numero,)).lastrowid
            conn.execute("INSERT INTO siga_leituras (processo_id, lido_em) VALUES (?,?)", (pid, lido))
    conn.close()
    r = client_admin.get("/api/admin/saude")
    assert r.status_code == 200, r.text
    assert r.json() == {"siga": {"ultima_leitura": "2026-10-28T15:15:00+00:00", "atrasado": False, "processos": 2}}
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
