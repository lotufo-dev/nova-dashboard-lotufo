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
    # #748: so' o que o Resumo e o QDOP da lista de Obras mostram
    assert r.status_code == 200 and set(r.json()) == {"hoje", "medido_ano", "curva_carteira", "carteira", "obras", "avisos",
                                                      "reajustes_apostilamento"}
    x = client.get("/api/diretoria/qdop.xlsx")
    assert x.status_code == 200 and "QDOP" in x.headers["content-disposition"]
    assert openpyxl.load_workbook(io.BytesIO(x.content)).active["S1"].value == "FRM.EXEMPLO.001"


def test_fechamento_so_leitura_e_401_sem_sessao_e_a_receber_saiu(client, monkeypatch):
    """Issue #748: a pagina Fechamento no lugar de A receber (a rota antiga nao existe mais) e da Carteira."""
    from app import permissoes
    assert client.get("/api/fechamento").status_code == 401
    c = db.get_conn()
    auth.criar_usuario(c, "Dir", "dir2@l.com", "senha-forte-123", "diretoria")
    c.close()
    _login(client, "dir2@l.com")
    r = client.get("/api/fechamento")
    assert r.status_code == 200 and set(r.json()) == {"anos", "meses", "por_ano", "acumulado", "em_aberto",
                                                      "em_aberto_anteriores", "notas_sem_medicao", "cobertura",
                                                      "notas_diferem", "total_a_receber_liberado"}
    assert r.json()["anos"] == ["2025", "2026"] and r.json()["meses"] == []
    assert client.get("/api/a-receber").status_code == 404
    assert client.get("/api/diretoria/custo").status_code == 404
    assert client.post("/api/fechamento").status_code == 405
    monkeypatch.setitem(permissoes.PERFIS, "diretoria", frozenset())
    assert client.get("/api/fechamento").status_code == 403


def test_custo_da_obra_404_sem_cadastro_e_403_sem_ver_paineis(client, monkeypatch):
    """Issue #491 e #748: o custo da obra (coluna da aba Medicoes); so' obra com cadastro de custo, so' quem tem
    `ver_paineis`."""
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
    c.execute("INSERT INTO custo_grupos (contrato_id, ordem, nome, tarefas, itens_planilha, item_chave_codigo, "
              "item_chave_unidade) VALUES (?,1,'G',?,?,'1.1','m³')", (com, json.dumps(["001"]), json.dumps(["1."])))
    c.commit(); c.close()
    assert client.get(f"/api/contratos/{com}/custo").status_code == 401
    _login(client, "dir3@l.com")
    r = client.get(f"/api/contratos/{com}/custo")
    assert r.status_code == 200 and set(r.json()) >= {"obra", "grupos", "linhas", "acumulado", "itens_chave", "rm"}
    # issue #492: o bloco do item-chave, em centavos por unidade (sem planilha lida: sem medicao)
    assert r.json()["itens_chave"] == [{
        "grupo": "G", "item": "1.1", "descricao": None, "unidade": "m³", "quantidade_acumulada": None,
        "medicao": None, "custo_centavos": 0, "custo_unitario_centavos": None, "preco_unitario_centavos": None,
        "diferenca_centavos": None, "situacao": "sem_medicao"}]
    r = client.get(f"/api/contratos/{sem}/custo")
    assert r.status_code == 404 and r.json()["detail"] == "Esta obra não tem cadastro de custo."
    assert client.get("/api/contratos/9999/custo").status_code == 404
    # outra obra com cadastro de custo no mesmo centro: 409 com as obras que disputam, sem valores
    c = db.get_conn()
    outra = contratos.criar(c, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 3", "objeto": "Obra Gama",
                                   "valor_original_centavos": 1_000_00, "centro_custo_rm": "2.001.012"})
    c.execute("UPDATE contratos SET projeto_rm='PRJ', custo_sem_tarefa='proporcional' WHERE id=?", (outra,))
    c.execute("INSERT INTO custo_grupos (contrato_id, ordem, nome, tarefas, itens_planilha) VALUES (?,1,'G',?,?)",
              (outra, json.dumps(["002"]), json.dumps(["2."])))
    c.commit(); c.close()
    r = client.get(f"/api/contratos/{com}/custo")
    assert r.status_code == 409 and "2.001.012 na obra IC 3" in r.json()["detail"]
    monkeypatch.setitem(permissoes.PERFIS, "diretoria", frozenset())
    assert client.get(f"/api/contratos/{com}/custo").status_code == 403


def test_custo_da_obra_com_planilha_sem_item_lida_pelos_titulos_do_cadastro(client):
    """Issue #613: o JSON da rota traz o medido nos grupos do cadastro (dois titulos no mesmo grupo), o titulo fora
    do cadastro em "outros" e nada em "Medido por grupo não lido"."""
    import json
    from app import contratos, medicao_grupos
    from tests.test_leitura_planilha_medicao import TOTAL_SEM_ITEM, planilha_sem_item
    c = db.get_conn()
    auth.criar_usuario(c, "Dir", "dir4@l.com", "senha-forte-123", "diretoria")
    cid = contratos.criar(c, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 4", "objeto": "Obra Delta",
                                 "valor_original_centavos": 1_000_00, "centro_custo_rm": "2.001.044"})
    c.execute("UPDATE contratos SET projeto_rm='PRJ', custo_sem_tarefa='proporcional' WHERE id=?", (cid,))
    c.execute("INSERT INTO custo_grupos (contrato_id, ordem, nome, tarefas, itens_planilha, titulos_planilha) "
              "VALUES (?,1,'Pavimentação','[\"001\"]','[]',?)", (cid, json.dumps(["pavimentacao", "REVESTIMENTO"])))
    mid = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
                    "VALUES (?,1,'execucao','2026-03','protocolada',?)", (cid, TOTAL_SEM_ITEM)).lastrowid
    c.commit()
    assert medicao_grupos.ler_e_registrar(c, None, mid, planilha_sem_item(), origem="carga")["situacao"] == "lida"
    c.close()
    _login(client, "dir4@l.com")
    r = client.get(f"/api/contratos/{cid}/custo")
    assert r.status_code == 200
    grupos = {g["nome"]: g["medido_centavos"] for g in r.json()["linhas"][0]["grupos"]}
    assert grupos == {"Pavimentação": 1296_23 + 800_27, "outros": 500_55 + 1200_01}


def test_nota_desconsiderada_some_das_rotas_sem_marca_e_aparece_so_na_auditoria(client):
    """Issue #638: depois de `desconsiderar_nf`, a lista de Obras (a receber), o Fechamento (notas sem medicao), o
    Inicio e a reconciliacao deixam
    de contar a nota, ao centavo, e nenhuma dessas respostas fala da correcao; a auditoria do admin traz o evento com
    o motivo e a fonte. `reconsiderar_nf` devolve os numeros e a auditoria fica com os dois eventos."""
    import datetime
    import json
    from app import correcao_medicoes
    from tests.test_protocolo import _contrato
    c = db.get_conn()
    auth.criar_usuario(c, "Adm", "adm@l.com", "senha-forte-123", "admin")
    cadastro_aplicar.aplicar(c, 1, {
        "orgaos": [{"chave": "sinfra-x", "nome": "SINFRA - X", "familia": "sinfra", "cnpj": None,
                    "regras": {"nome_qdop": "SINFRA - SECRETARIA", "tipo_contratante": "PÚBLICO"}}],
        "entidades": [{"chave": "lotufo", "nome": "Lotufo Engenharia e Construções Ltda", "cnpj": "31200101000130",
                       "papel": "lotufo", "coligada_rm": 1, "sigla_oficio": "LT", "nome_curto": "Lotufo"}],
        "contratos": [{**_contrato("Própria", "sinfra-x", "IC 1/2025"), "centro_custo_rm": "9.001.001"}], "avisos": [],
        "geral": {"qdop": {"modelo_caminho": str(MODELO)}, "diretoria": {"total_a_receber_liberado": True}}})
    # emitida em 2026 e sem medicao: entra nas "notas sem medição" do Fechamento (#748)
    mes_passado = datetime.date(2026, 10, 15)
    for idmov, valor, falta in ((961, 1_000_001, 930_001), (962, 80_000, 80_000)):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, emissao, valor_centavos, situacao, "
                        "codtmv, centro_custo) VALUES (1, ?, ?, ?, ?, ?, 'ativa', '2.2.01', '9.001.001')",
                        (idmov, str(idmov), idmov, mes_passado.isoformat(), valor)).lastrowid
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan) VALUES (1, ?, ?, ?, ?, 0, 0)", (idmov, nid, idmov, falta))
    c.commit()
    _login(client, "adm@l.com")

    def retrato():
        rotas = {r: client.get(r) for r in ("/api/contratos", "/api/fechamento", "/api/inicio", "/api/inicio/painel",
                                            "/api/rm/reconciliacao")}
        assert all(v.status_code == 200 for v in rotas.values()), {r: v.status_code for r, v in rotas.items()}
        j = {r: v.json() for r, v in rotas.items()}
        a_receber = sum(o["posicao"]["a_receber_centavos"] or 0 for o in j["/api/contratos"])
        numeros = (a_receber, j["/api/fechamento"]["notas_sem_medicao"]["em_aberto_centavos"],
                   j["/api/inicio/painel"]["a_receber"]["valor_centavos"],
                   sorted(n["numero"] for n in j["/api/rm/reconciliacao"]["nfs_sem_medicao"]),
                   j["/api/rm/reconciliacao"]["totais"]["nfs_sem_medicao"], j["/api/inicio"]["avisos"])
        return numeros, json.dumps(j, ensure_ascii=False).lower()
    antes, _ = retrato()
    assert antes[3] == ["961", "962"]
    correcao_medicoes.executar(c, 1, [{"operacao": "desconsiderar_nf", "nf": 961, "motivo": "cancelada na prefeitura",
                                       "fonte": "comprovante da prefeitura"}], ensaio=False)
    depois, texto = retrato()
    assert depois[0] == antes[0] - 930_001 and depois[1] == antes[1] - 1_000_001 and depois[2] == antes[2] - 930_001
    assert depois[3] == ["962"] and depois[4] == antes[4] - 1 and depois[5] == antes[5]
    # nenhuma resposta traz a marca, o motivo ou a fonte (a coluna vem nula nas outras notas da reconciliacao)
    assert '"desconsiderada_em": "' not in texto and "desconsiderada_em" not in texto.replace('"desconsiderada_em": null', "")
    assert "cancelada na prefeitura" not in texto and "comprovante da prefeitura" not in texto
    ev = [e for e in client.get("/api/admin/auditoria").json()["eventos"] if e["entidade"] == "nota_fiscal"]
    assert [e["acao"] for e in ev] == ["nota.desconsiderar"] and ev[0]["usuario_id"] == 1
    d = json.loads(ev[0]["depois"])
    assert (d["numero"], d["motivo"], d["fonte"]) == ("961", "cancelada na prefeitura", "comprovante da prefeitura")
    correcao_medicoes.executar(c, 1, [{"operacao": "reconsiderar_nf", "nf": 961, "fonte": "conferência"}], ensaio=False)
    c.close()
    assert retrato()[0] == antes
    ev = [e["acao"] for e in client.get("/api/admin/auditoria").json()["eventos"] if e["entidade"] == "nota_fiscal"]
    assert ev == ["nota.reconsiderar", "nota.desconsiderar"]
