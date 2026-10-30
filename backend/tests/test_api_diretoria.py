"""Rotas da diretoria e do QDOP (bloco 8)."""
import io
import pathlib

import openpyxl

from app import auth, cadastro_aplicar, db

MODELO = pathlib.Path(__file__).parents[2] / "cadastro-exemplo" / "modelos" / "qdop" / "qdop-modelo.xlsx"


def _login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "senha": "senha-forte-123"})
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))


def test_painel_e_qdop_para_a_diretoria_e_401_sem_sessao(client):
    assert client.get("/api/diretoria").status_code == 401
    c = db.get_conn()
    auth.criar_usuario(c, "Dir", "dir@l.com", "senha-forte-123", "diretoria")
    cadastro_aplicar.aplicar(c, 1, {"orgaos": [], "entidades": [], "contratos": [], "avisos": [],
                                    "geral": {"qdop": {"modelo_caminho": str(MODELO)}}})
    c.close()
    _login(client, "dir@l.com")
    r = client.get("/api/diretoria")
    assert r.status_code == 200 and set(r.json()) == {"hoje", "total_a_receber_liberado", "dinheiro", "mes_ano",
                                                      "curva_carteira", "proximos", "carteira", "obras", "obras_base", "avisos"}
    x = client.get("/api/diretoria/qdop.xlsx")
    assert x.status_code == 200 and "QDOP" in x.headers["content-disposition"]
    assert openpyxl.load_workbook(io.BytesIO(x.content)).active["S1"].value == "FRM.EXEMPLO.001"


def test_a_receber_so_leitura_e_401_sem_sessao(client):
    assert client.get("/api/a-receber").status_code == 401
    c = db.get_conn()
    auth.criar_usuario(c, "Dir", "dir2@l.com", "senha-forte-123", "diretoria")
    c.close()
    _login(client, "dir2@l.com")
    r = client.get("/api/a-receber")
    assert r.status_code == 200 and set(r.json()) == {"hoje", "total_a_receber_liberado", "total", "mes", "meses", "por_obra", "itens"}
