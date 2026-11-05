"""Integridade do codigo em producao (issue #421): clone e dist conferidos contra o registro do ultimo deploy."""
import json
import os
import subprocess

import pytest

from app import db, integridade, seguranca

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(clone, *args):
    return subprocess.run(["git", "-C", str(clone), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout


@pytest.fixture(autouse=True)
def estado_limpo(monkeypatch):
    monkeypatch.delenv("DASH_DEV", raising=False)
    monkeypatch.setattr(integridade, "ESTADO", None)
    monkeypatch.setattr(integridade, "_anterior", None)


@pytest.fixture
def producao(tmp_path):
    """Um clone git em <tmp>/app e a raiz dos dados em <tmp>/raiz; o deploy ja' registrado."""
    clone, raiz = tmp_path / "app", tmp_path / "raiz"
    (clone / "backend").mkdir(parents=True)
    (clone / "frontend" / "dist" / "assets").mkdir(parents=True)
    raiz.mkdir()
    (clone / ".gitignore").write_text(".venv\nnode_modules\nfrontend/dist/\n")
    (clone / "backend" / "x.py").write_text("print(1)\n")
    (clone / "frontend" / "dist" / "index.html").write_text("<html>")
    (clone / "frontend" / "dist" / "assets" / "app.js").write_text("a()")
    _git(clone, "init", "-q")
    _git(clone, "add", ".")
    _git(clone, "commit", "-q", "-m", "inicial")
    integridade.registrar_deploy(raiz, clone)
    return clone, raiz


def _itens():
    return [i["mensagem"] for i in integridade.itens()]


def test_registro_do_deploy_grava_commit_data_e_manifesto(producao):
    clone, raiz = producao
    r = json.loads((raiz / "deploy-atual.json").read_text(encoding="utf-8"))
    assert r["commit"] == _git(clone, "rev-parse", "HEAD").strip()
    assert r["data"] and len(r["manifesto"]) == 64
    assert sorted(r["dist"]) == ["assets/app.js", "index.html"]


def test_sem_diferenca_nao_ha_item(producao, client):
    clone, raiz = producao
    conn = db.get_conn()
    assert integridade.rodar(conn, raiz, clone)["estado"] == "ok"
    assert integridade.itens() == []
    assert seguranca.itens(conn) == []
    conn.close()


def test_arquivo_modificado_aparece_como_um_arquivo_alterado(producao, client):
    clone, raiz = producao
    (clone / "backend" / "x.py").write_text("print(2)\n")
    conn = db.get_conn()
    integridade.rodar(conn, raiz, clone)
    [item] = seguranca.itens(conn)
    assert item["nivel"] == "critico"
    assert item["mensagem"] == "Código em produção diferente do último deploy: 1 arquivo alterado"
    # nem nome de arquivo nem caminho absoluto
    assert "x.py" not in item["mensagem"] and str(clone) not in item["mensagem"]
    conn.close()


def test_arquivo_novo_nao_ignorado_conta_e_o_ignorado_nao(producao, client):
    clone, raiz = producao
    (clone / "backend" / ".venv").mkdir()
    (clone / "backend" / ".venv" / "lixo.py").write_text("x")
    (clone / "node_modules").mkdir()
    (clone / "node_modules" / "a.js").write_text("x")
    conn = db.get_conn()
    assert integridade.rodar(conn, raiz, clone)["estado"] == "ok"
    (clone / "backend" / "novo.py").write_text("x")
    integridade.rodar(conn, raiz, clone)
    assert _itens() == ["Código em produção diferente do último deploy: 1 arquivo alterado"]
    conn.close()


def test_head_diferente_do_registrado(producao, client):
    clone, raiz = producao
    (clone / "backend" / "x.py").write_text("print(3)\n")
    _git(clone, "commit", "-q", "-am", "fora do deploy")
    conn = db.get_conn()
    integridade.rodar(conn, raiz, clone)
    assert _itens() == ["Código em produção diferente do último deploy: commit diferente do registrado"]
    conn.close()


def test_dist_alterado(producao, client):
    clone, raiz = producao
    (clone / "frontend" / "dist" / "assets" / "app.js").write_text("hackeado()")
    conn = db.get_conn()
    integridade.rodar(conn, raiz, clone)
    assert _itens() == ["Código em produção diferente do último deploy: 1 arquivo do dist alterado"]
    (clone / "frontend" / "dist" / "novo.js").write_text("y")
    integridade.rodar(conn, raiz, clone)
    assert _itens() == ["Código em produção diferente do último deploy: 2 arquivos do dist alterados"]
    conn.close()


def test_sem_registro_e_atencao(producao, client):
    clone, raiz = producao
    (raiz / "deploy-atual.json").unlink()
    conn = db.get_conn()
    assert integridade.rodar(conn, raiz, clone)["estado"] == "sem_registro"
    [item] = integridade.itens()
    assert item["nivel"] == "atencao" and item["mensagem"] == "Sem registro do último deploy"
    conn.close()


def test_o_proximo_deploy_limpa_o_item(producao, client):
    clone, raiz = producao
    (clone / "backend" / "x.py").write_text("print(2)\n")
    (clone / "frontend" / "dist" / "index.html").write_text("outro")
    conn = db.get_conn()
    integridade.rodar(conn, raiz, clone)
    assert integridade.itens()
    _git(clone, "commit", "-q", "-am", "deploy novo")
    integridade.registrar_deploy(raiz, clone)
    integridade.rodar(conn, raiz, clone)
    assert integridade.itens() == []
    conn.close()


def _linhas_auditoria(conn):
    return conn.execute("SELECT depois FROM audit_log WHERE acao='seguranca.arvore_alterada' ORDER BY id").fetchall()


def test_auditoria_uma_vez_por_diferenca_nova(producao, client):
    clone, raiz = producao
    conn = db.get_conn()
    (clone / "backend" / "x.py").write_text("print(2)\n")
    integridade.rodar(conn, raiz, clone)
    integridade.rodar(conn, raiz, clone)          # a hora seguinte: a mesma diferenca
    assert len(_linhas_auditoria(conn)) == 1
    corpo = json.loads(_linhas_auditoria(conn)[0]["depois"])
    assert corpo["arquivos_alterados"] == 1 and "x.py" not in json.dumps(corpo)
    (clone / "backend" / "y.py").write_text("y")  # diferenca nova
    integridade.rodar(conn, raiz, clone)
    assert len(_linhas_auditoria(conn)) == 2
    # depois de reiniciar o servidor a mesma diferenca tambem nao repete
    integridade._anterior = None
    integridade.rodar(conn, raiz, clone)
    assert len(_linhas_auditoria(conn)) == 2
    conn.close()


def test_diferenca_que_some_e_volta_grava_de_novo(producao, client):
    clone, raiz = producao
    conn = db.get_conn()
    for _ in range(2):
        (clone / "backend" / "x.py").write_text("print(2)\n")
        integridade.rodar(conn, raiz, clone)
        _git(clone, "checkout", "--", "backend/x.py")
        integridade.rodar(conn, raiz, clone)
    assert len(_linhas_auditoria(conn)) == 2
    conn.close()


def test_em_dev_a_conferencia_nao_roda(producao, client, monkeypatch):
    clone, raiz = producao
    monkeypatch.setenv("DASH_DEV", "1")
    (clone / "backend" / "x.py").write_text("print(2)\n")
    conn = db.get_conn()
    assert integridade.rodar(conn, raiz, clone) is None
    assert integridade.itens() == [] and _linhas_auditoria(conn) == []
    conn.close()


def test_com_o_deploy_rodando_a_conferencia_espera(producao, client):
    clone, raiz = producao
    (raiz / "watchdog.pause").write_text("")
    (clone / "backend" / "x.py").write_text("print(2)\n")
    conn = db.get_conn()
    assert integridade.rodar(conn, raiz, clone) is None
    conn.close()


def test_git_que_nao_responde_vira_atencao(producao, client, tmp_path):
    _, raiz = producao
    conn = db.get_conn()
    integridade.rodar(conn, raiz, tmp_path / "nao-e-repositorio")
    [item] = integridade.itens()
    assert item["nivel"] == "atencao" and item["mensagem"] == "Não foi possível conferir o código em produção"
    conn.close()


def test_saude_traz_o_item_no_bloco_seguranca(producao, client_admin):
    clone, raiz = producao
    (clone / "backend" / "x.py").write_text("print(2)\n")
    from app import db as db_
    conn = db_.get_conn()
    integridade.rodar(conn, raiz, clone)
    conn.close()
    corpo = client_admin.get("/api/admin/saude").json()
    [item] = [i for i in corpo["seguranca"] if i["nivel"] == "critico"]
    assert "1 arquivo alterado" in item["mensagem"]


def test_cli_registrar_grava_o_arquivo(producao, tmp_path, monkeypatch, capsys):
    clone, _ = producao
    destino = tmp_path / "outra-raiz"
    from app import cli
    monkeypatch.setattr(integridade, "clone_padrao", lambda: clone)
    assert cli.main(["integridade", "registrar", "--raiz", str(destino)]) == 0
    assert (destino / "deploy-atual.json").is_file()
    assert "Registro do deploy gravado" in capsys.readouterr().out


def test_safe_directory_vai_com_barra_normal(monkeypatch):
    """O Git para Windows compara com `C:/pasta`; barra invertida faria o rev-parse sair 128 como SYSTEM."""
    from pathlib import PureWindowsPath
    chamadas = []

    class R:
        returncode, stdout = 0, "abc\n"

    monkeypatch.setattr(integridade.subprocess, "run", lambda cmd, **kw: chamadas.append(cmd) or R())
    assert integridade._git(PureWindowsPath(r"C:\DashboardLotufo\app"), "rev-parse", "HEAD") == "abc\n"
    assert "safe.directory=C:/DashboardLotufo/app" in chamadas[0]


def test_item_de_atencao_so_com_o_titulo(producao, client):
    clone, raiz = producao
    conn = db.get_conn()
    (raiz / "deploy-atual.json").unlink()
    integridade.rodar(conn, raiz, clone)
    assert _itens() == ["Sem registro do último deploy"]
    conn.close()


def test_com_a_pausa_a_proxima_conferencia_vem_logo(tmp_path):
    assert integridade.proxima_espera(tmp_path, 3600) == 3600
    (tmp_path / "watchdog.pause").write_text("")
    assert integridade.proxima_espera(tmp_path, 3600) == 60
    assert integridade.proxima_espera(None, 3600) == 3600
