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
                                                      "curva_carteira", "proximos", "carteira", "obras", "obras_base", "avisos",
                                                      "faturado_rm"}
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
    assert r.status_code == 200 and set(r.json()) == {"hoje", "total_a_receber_liberado", "total", "recebido_ano_centavos", "antes_do_protocolo", "mes", "meses", "por_obra",
                                                      "por_orgao", "itens"}


def test_custo_da_obra_404_sem_cadastro_e_403_sem_ver_paineis(client, monkeypatch):
    """Issue #491: a aba Custo da Carteira; so' obra com cadastro de custo, so' quem tem `ver_paineis`."""
    import json
    from app import contratos, permissoes
    c = db.get_conn()
    auth.criar_usuario(c, "Dir", "dir3@l.com", "senha-forte-123", "diretoria")
    com = contratos.criar(c, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 1", "objeto": "Obra Alfa",
                                 "valor_original_centavos": 1_000_00, "centro_custo_rm": "2.001.012"})
    sem = contratos.criar(c, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 2", "objeto": "Obra Beta",
                                 "valor_original_centavos": 1_000_00})
    c.execute("UPDATE contratos SET projeto_rm='PRJ', custo_nao_e_custo='[]', custo_sem_tarefa='proporcional' WHERE id=?",
              (com,))
    c.execute("INSERT INTO custo_grupos (contrato_id, ordem, nome, tarefas, itens_planilha) VALUES (?,1,'G',?,?)",
              (com, json.dumps(["001"]), json.dumps(["1."])))
    c.commit(); c.close()
    assert client.get(f"/api/diretoria/custo/{com}").status_code == 401
    _login(client, "dir3@l.com")
    assert client.get("/api/diretoria/custo").json() == [{"contrato_id": com, "obra": "IC 1"}]
    r = client.get(f"/api/diretoria/custo/{com}")
    assert r.status_code == 200 and set(r.json()) >= {"obra", "grupos", "linhas", "acumulado", "rm"}
    r = client.get(f"/api/diretoria/custo/{sem}")
    assert r.status_code == 404 and r.json()["detail"] == "Esta obra não tem cadastro de custo."
    assert client.get("/api/diretoria/custo/9999").status_code == 404
    # outra obra com cadastro de custo no mesmo centro: 409 com as obras que disputam, sem valores
    c = db.get_conn()
    outra = contratos.criar(c, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 3", "objeto": "Obra Gama",
                                   "valor_original_centavos": 1_000_00, "centro_custo_rm": "2.001.012"})
    c.execute("UPDATE contratos SET projeto_rm='PRJ', custo_sem_tarefa='proporcional' WHERE id=?", (outra,))
    c.execute("INSERT INTO custo_grupos (contrato_id, ordem, nome, tarefas, itens_planilha) VALUES (?,1,'G',?,?)",
              (outra, json.dumps(["002"]), json.dumps(["2."])))
    c.commit(); c.close()
    r = client.get(f"/api/diretoria/custo/{com}")
    assert r.status_code == 409 and "2.001.012 na obra IC 3" in r.json()["detail"]
    monkeypatch.setitem(permissoes.PERFIS, "diretoria", frozenset())
    assert client.get(f"/api/diretoria/custo/{com}").status_code == 403
    assert client.get("/api/diretoria/custo").status_code == 403
