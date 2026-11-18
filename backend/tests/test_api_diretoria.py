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
    assert r.status_code == 200 and set(r.json()) == {"hoje", "medido_ano", "curva_carteira", "obras", "avisos",
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
                                                      "notas_diferem", "pares_mistos", "total_a_receber_liberado",
                                                      "diferenca_critica_por_mil"}       # #805: o limite da diferenca
    assert r.json()["anos"] == ["2025", "2026"] and r.json()["meses"] == []
    assert r.json()["diferenca_critica_por_mil"] == 5
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


def test_tipo_extra_do_cadastro_muda_o_a_receber_e_o_faturado_so_da_obra_que_o_declara(client, tmp_path):
    """docs/adr/0015, de ponta a ponta: o cadastro em arquivo (`tipos_cobranca_extras_rm: ['2.2.03']` na Obra Consorcio
    do `cadastro-exemplo/`) aplicado, as notas e os titulos trazidos pela sincronizacao com o RM, e os numeros que as
    telas do redesenho mostram: Inicio (o a receber, na cota), lista de Obras (a receber na cota), cabecalho da obra (a
    receber em valor cheio) e Fechamento (a nota em aberto sem medicao ligada, pelo bruto na cota, que sai da mesma
    lista do faturado do RM, `diretoria._notas_do_rm`). As telas A receber e Diretoria sairam na #748. Sem a chave, a
    nota 2.2.03 do consorcio esta' fora de tudo; com ela, entra so' na obra que a declara, e a 2.2.03 da Obra Propria
    continua fora. Cota de 50% com centavo impar."""
    import copy
    import datetime
    from app import cadastro_arquivos, sincronizacao_rm
    from tests.conftest import CADASTRO_EXEMPLO
    from tests.test_rm import _baixa, _nf, _simulador
    c = db.get_conn()
    auth.criar_usuario(c, "Adm", "adm@exemplo.com.br", "senha-forte-123", "admin")
    com_a_chave = cadastro_arquivos.preparar(CADASTRO_EXEMPLO)
    sem_a_chave = copy.deepcopy(com_a_chave)
    for contrato in sem_a_chave["contratos"]:
        contrato["tipos_cobranca_extras_rm"] = []
    cadastro_aplicar.aplicar(c, 1, sem_a_chave)
    propria, consorcio = (c.execute("SELECT id FROM contratos WHERE nome_curto=?", (nome,)).fetchone()[0]
                          for nome in ("Obra Própria", "Obra Consórcio"))
    # emitidas no mes passado: entram na serie do faturado do RM (meses fechados) seja qual for o dia do teste
    mes_passado = (datetime.date.today().replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    emissao = f"{mes_passado:%Y-%m}-10T00:00:00-04:00"
    nfs = [_nf(971, 3333.33, coligada=90, codtmv="2.2.03", emissao=emissao),                      # fatura do consorcio
           _nf(972, 2500.01, centro_custo="9.001.001", codtmv="2.2.03", emissao=emissao),         # obra que nao declara
           _nf(973, 400.01, centro_custo="9.001.001", emissao=emissao)]                           # lista geral
    baixas = [_baixa(9711, 971, 3100.01, 0, 0, coligada=90), _baixa(9721, 972, 2300.01, 0, 0), _baixa(9731, 973, 400.01, 0, 0)]
    r = sincronizacao_rm.sincronizar(c, _simulador(tmp_path, nfs, baixas))
    assert (r["estado"], r["nfs"], r["baixas"]) == ("success", 3, 3), r
    # a sincronizacao traz a nota 2.2.03 e o titulo dela com ou sem a chave: o tipo nao filtra o que vem do RM
    assert [tuple(x) for x in c.execute("SELECT n.idmov, n.codtmv, b.valor_original_centavos FROM notas_fiscais n "
                                        "JOIN baixas b ON b.nota_id=n.id ORDER BY n.idmov")] == [
        (971, "2.2.03", 310_001), (972, "2.2.03", 230_001), (973, "2.2.01", 40_001)]
    _login(client, "adm@exemplo.com.br")

    def retrato():
        soltas = client.get("/api/fechamento").json()["notas_sem_medicao"]
        obras = {o["id"]: o["posicao"]["a_receber_centavos"] for o in client.get("/api/contratos").json()
                 if o["id"] in (propria, consorcio)}          # a Obra Encerrada do exemplo nao entra nesta conta
        cheio = {cid: client.get(f"/api/contratos/{cid}/cabecalho").json()["a_receber_centavos"] for cid in (propria, consorcio)}
        return {"total": client.get("/api/inicio/painel").json()["a_receber"]["valor_centavos"],
                "sem_medicao": {x["contrato_id"]: x["valor_centavos"] for x in soltas["em_aberto"]},
                "sem_medicao_total": soltas["em_aberto_centavos"], "obras": obras, "cheio": cheio}
    assert retrato() == {"total": 40_001, "sem_medicao": {propria: 40_001}, "sem_medicao_total": 40_001,
                         "obras": {propria: 40_001, consorcio: 0}, "cheio": {propria: 40_001, consorcio: 0}}
    rel = cadastro_aplicar.aplicar(c, 1, com_a_chave)
    assert rel["contratos"]["alterados"] == ["Obra Consórcio (tipos de cobrança extras do RM: nenhum → 2.2.03)"]
    c.close()
    # 310.001 x 50% = 155.000,5 -> 155.001 (a receber, na cota); 333.333 x 50% = 166.666,5 -> 166.667 (o bruto)
    assert retrato() == {"total": 40_001 + 155_001, "sem_medicao": {propria: 40_001, consorcio: 166_667},
                         "sem_medicao_total": 40_001 + 166_667, "obras": {propria: 40_001, consorcio: 155_001},
                         "cheio": {propria: 40_001, consorcio: 310_001}}
