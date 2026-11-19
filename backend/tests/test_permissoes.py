from app.permissoes import PERFIS, tem

def test_perfis():
    assert tem("admin", "administrar")
    assert tem("admin", "editar_config_fiscal")
    assert tem("engenharia", "editar_cadastros")
    assert not tem("engenharia", "editar_config_fiscal")
    assert not tem("engenharia", "administrar")
    assert tem("diretoria", "ver_paineis")
    assert not tem("diretoria", "editar_cadastros")


# --- testes adicionais (nao previstos no brief) -------------------------------

import sys

from fastapi import Depends

from app import auth, cli, db
from app.permissoes import exigir

PERMISSOES = {"ver_paineis", "ver_siga", "editar_cadastros", "editar_config_fiscal", "administrar"}


def test_ver_siga_e_dos_tres_perfis_e_so_quem_edita_cadastros_escreve_no_siga():
    """Issue #829 (decisao do dono de 19/11/2026): a diretoria le o SIGA e nao escreve nele. Nenhum perfil fica sem
    `ver_siga`; o perfil desconhecido nao tem."""
    for perfil in ("diretoria", "engenharia", "admin"):
        assert tem(perfil, "ver_siga")
    assert not tem("desconhecido", "ver_siga")
    assert not tem("diretoria", "editar_cadastros")
    from app.permissoes import do_perfil
    assert do_perfil("diretoria") == ["ver_paineis", "ver_siga"]
    assert do_perfil("desconhecido") == []

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

def test_perfis_do_banco_cobertos():
    # os perfis aceitos pelo CHECK da tabela usuarios sao exatamente estes
    assert set(PERFIS) == {"diretoria", "engenharia", "admin"}
    for perms in PERFIS.values():
        assert perms <= PERMISSOES

def test_tem_perfil_ou_permissao_desconhecidos():
    assert not tem("faxineiro", "ver_paineis")
    assert not tem("admin", "voar")
    assert not tem("", "")

def test_perfis_nao_e_mutavel_por_engano():
    # mutar o set devolvido por PERFIS.get nao pode escalar privilegio depois
    antes = set(PERFIS["diretoria"])
    with_default = PERFIS.get("inexistente", set())
    with_default.add("administrar")
    assert not tem("inexistente", "administrar")
    assert set(PERFIS["diretoria"]) == antes

def test_exigir_403_para_perfil_sem_permissao(client):
    _seed(perfil="engenharia")
    corpo = _login(client)

    @client.app.post("/api/_teste_fiscal")
    def _fiscal(usuario: dict = Depends(exigir("editar_config_fiscal"))):
        return {"ok": True}

    r = client.post("/api/_teste_fiscal", headers={"X-CSRF-Token": corpo["csrf"]})
    assert r.status_code == 403
    assert "editar_config_fiscal" in r.json()["detail"]

def test_exigir_200_para_perfil_com_permissao(client):
    _seed(perfil="admin")
    corpo = _login(client)

    @client.app.post("/api/_teste_admin")
    def _admin(usuario: dict = Depends(exigir("administrar"))):
        return {"perfil": usuario["perfil"]}

    r = client.post("/api/_teste_admin", headers={"X-CSRF-Token": corpo["csrf"]})
    assert r.status_code == 200
    assert r.json()["perfil"] == "admin"

def test_exigir_valida_csrf_por_padrao(client):
    _seed(perfil="admin")
    _login(client)

    @client.app.post("/api/_teste_csrf_perm")
    def _p(usuario: dict = Depends(exigir("administrar"))):
        return {"ok": True}

    assert client.post("/api/_teste_csrf_perm").status_code == 403
    assert client.post("/api/_teste_csrf_perm",
                       headers={"X-CSRF-Token": "errado"}).status_code == 403

def test_exigir_sem_csrf_para_leitura(client):
    _seed(perfil="diretoria")
    _login(client)

    @client.app.get("/api/_teste_leitura")
    def _l(usuario: dict = Depends(exigir("ver_paineis", com_csrf=False))):
        return {"ok": True}

    assert client.get("/api/_teste_leitura").status_code == 200

def test_exigir_401_sem_sessao(client):
    @client.app.get("/api/_teste_sem_sessao")
    def _s(usuario: dict = Depends(exigir("ver_paineis", com_csrf=False))):
        return {"ok": True}

    assert client.get("/api/_teste_sem_sessao").status_code == 401

def test_cli_criar_admin(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setattr(sys, "argv",
                        ["app.cli", "criar-admin", "--nome", "Leo", "--email", "leo@lotufo.com"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda *a, **k: "senha-forte-123")

    cli.main()

    assert "Administrador criado" in capsys.readouterr().out
    conn = db.get_conn()
    u = auth.autenticar(conn, "leo@lotufo.com", "senha-forte-123")
    conn.close()
    assert u is not None and u["perfil"] == "admin"
    assert tem(u["perfil"], "administrar")

def test_cli_sem_subcomando(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "cli2.db"))
    monkeypatch.setattr(sys, "argv", ["app.cli"])
    with pytest.raises(SystemExit):
        cli.main()
