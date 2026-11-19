from tests.conftest import novo_contrato

NOVO = {"orgao": "SINFRA-MT", "numero_instrumento": "IC 082/2025",
        "objeto": "MT-388", "valor_original": "1.000.000,00",
        "vigencia_fim": "2027-12-31", "execucao_fim": "2027-06-30"}

def test_listar(client_admin):
    cid = novo_contrato(NOVO)
    lista = client_admin.get("/api/contratos").json()
    assert any(c["id"] == cid and c["valor_vigente_centavos"] == 100_000_000 for c in lista)

def test_sem_login_nega(client):
    assert client.get("/api/contratos").status_code == 401

def test_detalhe_inexistente_404(client_admin):
    assert client_admin.get("/api/contratos/9999").status_code == 404

def test_perfil_diretoria_le(client):
    from app import auth, db
    conn = db.get_conn()
    auth.criar_usuario(conn, "Dir", "dir@lotufo.com", "senha-forte-123", "diretoria")
    conn.close()
    r = client.post("/api/auth/login", json={"email": "dir@lotufo.com", "senha": "senha-forte-123"})
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))
    assert client.get("/api/contratos").status_code == 200

def test_escrita_de_contrato_pela_api_saiu(client_admin):
    """Bloco 9: contrato entra pelo cadastro versionado (`cadastro aplicar`), nao pela tela."""
    cid = novo_contrato(NOVO)
    assert client_admin.post("/api/contratos", json=NOVO).status_code == 405
    assert client_admin.put(f"/api/contratos/{cid}", json=NOVO).status_code == 405
    assert client_admin.post(f"/api/contratos/{cid}/estado",
                             json={"estado": "suspenso", "data": "2026-08-01"}).status_code == 404


def test_listar_traz_o_medido_e_o_saldo(client_admin):
    """Redesenho de Obras (#159): o % executado e o saldo a executar de cada obra vem da lista, em valor cheio."""
    from app import db, medicoes
    cid = novo_contrato(NOVO)
    conn = db.get_conn()
    mid = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, 1, mid, "protocolado", 250_000_00, "manual")
    medicoes.registrar_protocolo(conn, 1, mid, "2026-07-28", None, None, "manual", True, "teste de cenário")
    medicoes.definir_valor(conn, 1, mid, "atestado", 240_000_00, "manual")
    conn.close()
    outro = novo_contrato({**NOVO, "numero_instrumento": "IC 083/2025"})
    lista = {c["id"]: c for c in client_admin.get("/api/contratos").json()}
    assert lista[cid]["medido_centavos"] == 240_000_00      # o atestado vale
    assert lista[cid]["saldo_centavos"] == 100_000_000 - 240_000_00
    # a mesma conta do saldo do cronograma da obra
    from app import paineis
    conn = db.get_conn()
    for i in (cid, outro):
        s = paineis.saldo(conn, i)
        assert (lista[i]["medido_centavos"], lista[i]["saldo_centavos"]) == (s["medido_centavos"], s["saldo_centavos"])
    conn.close()
    assert lista[outro]["medido_centavos"] == 0 and lista[outro]["saldo_centavos"] == 100_000_000


def test_listar_saldo_exclui_o_aditivo_de_reajuste(client_admin):
    """#262: o vigente da lista continua com o reajuste; o saldo a executar e' a precos iniciais."""
    from app import db, paineis
    cid = novo_contrato(NOVO)
    conn = db.get_conn()
    conn.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza) "
                 "VALUES (?, 'valor', 10_000_01, 'assinado', '2026-03-01', 'reajuste')", (cid,))
    conn.commit()
    s = paineis.saldo(conn, cid)
    conn.close()
    obra = {c["id"]: c for c in client_admin.get("/api/contratos").json()}[cid]
    assert obra["valor_vigente_centavos"] == 100_000_000 + 10_000_01
    assert obra["saldo_centavos"] == 100_000_000 == s["saldo_centavos"]


def test_listar_agrupa_o_contratante_como_medicoes(client_admin):
    """Redesenho de Obras (#159): a escolha do contratante agrupa como a tela de Medicoes -- "SINFRA" para toda a
    familia, com a superintendencia em `orgao_sub`; o orgao com sigla propria (MTPAR) fica com ela."""
    from app import db
    a = novo_contrato(NOVO)
    b = novo_contrato({**NOVO, "numero_instrumento": "IC 083/2025"})
    c = novo_contrato({**NOVO, "numero_instrumento": "IC 084/2025", "orgao": "texto livre"})
    conn = db.get_conn()
    conn.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('sinfra-suef2', 'SINFRA - SUEF II', 'sinfra', '{}')")
    conn.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('mtpar', 'MTPAR', 'mtpar', '{}')")
    conn.execute("UPDATE contratos SET orgao_id=(SELECT id FROM orgaos WHERE chave='sinfra-suef2') WHERE id IN (?, ?)", (a, b))
    conn.execute("UPDATE contratos SET orgao_id=(SELECT id FROM orgaos WHERE chave='mtpar') WHERE id=?", (c,))
    conn.commit(); conn.close()
    lista = {x["id"]: x for x in client_admin.get("/api/contratos").json()}
    assert lista[a]["contratante"] == lista[b]["contratante"] == "SINFRA" and lista[a]["orgao_sub"] == "SUEF II"
    assert lista[c]["contratante"] == "MTPAR" and lista[c]["orgao_sub"] is None


def _com_grupos(cid):
    from app import db
    conn = db.get_conn()
    conn.execute("INSERT INTO custo_grupos (contrato_id, ordem, nome, tarefas, itens_planilha, item_chave_codigo, "
                 "item_chave_unidade) VALUES (?, 2, 'Drenagem', '[\"001.05\"]', '[\"3.\"]', NULL, NULL)", (cid,))
    conn.execute("INSERT INTO custo_grupos (contrato_id, ordem, nome, tarefas, itens_planilha, item_chave_codigo, "
                 "item_chave_unidade) VALUES (?, 1, 'Terraplanagem', '[\"001.03\"]', '[\"2.\"]', '2.1', 'm³')", (cid,))
    conn.commit(); conn.close()


def test_custo_grupos_lista_na_ordem_do_cadastro(client_admin):
    """Issue #489: os grupos de custo da obra, na ordem do yaml, com tarefas, itens e item-chave."""
    cid = novo_contrato(NOVO)
    _com_grupos(cid)
    assert client_admin.get(f"/api/contratos/{cid}/custo-grupos").json() == [
        {"ordem": 1, "nome": "Terraplanagem", "tarefas": ["001.03"], "itens_planilha": ["2."],
         "titulos_planilha": [], "item_chave": {"codigo": "2.1", "unidade": "m³"}},
        {"ordem": 2, "nome": "Drenagem", "tarefas": ["001.05"], "itens_planilha": ["3."], "titulos_planilha": [],
         "item_chave": None}]


def test_custo_grupos_sem_cadastro_e_lista_vazia_e_inexistente_404(client_admin):
    cid = novo_contrato(NOVO)
    assert client_admin.get(f"/api/contratos/{cid}/custo-grupos").json() == []
    assert client_admin.get("/api/contratos/9999/custo-grupos").status_code == 404


def test_custo_grupos_exige_ver_paineis(client_admin, monkeypatch):
    from app import permissoes
    cid = novo_contrato(NOVO)
    monkeypatch.setitem(permissoes.PERFIS, "admin", frozenset())
    assert client_admin.get(f"/api/contratos/{cid}/custo-grupos").status_code == 403


def test_custo_rm_da_obra_pelo_centro_atual_e_pelos_anteriores(client_admin):
    """#488: o custo do RM da obra sai pelo centro de custo atual e pelos anteriores, na coligada da entidade."""
    from app import db
    cid = novo_contrato(NOVO)
    sem_centro = novo_contrato({**NOVO, "numero_instrumento": "IC 083/2025"})
    conn = db.get_conn()
    conn.execute("UPDATE contratos SET centro_custo_rm='2.001.012', centros_custo_anteriores_rm='[\"1.050.003\"]' "
                 "WHERE id=?", (cid,))
    linhas = [(1, "2.001.012", "PRJ01", "1.02", "1.01.003", "2026-03", 3, 123457),
              (1, "1.050.003", None, None, "2.02.001", "2024-11", 1, -1001),
              (1, "2.001.099", "PRJ02", "1.01", "1.01.003", "2026-03", 1, 999),     # outra obra
              (12, "2.001.012", "PRJ01", "1.02", "1.01.003", "2026-03", 1, 777)]    # mesmo centro, outra coligada
    conn.executemany("INSERT INTO rm_custo_tarefas (coligada, centro_custo, projeto, tarefa, natureza, mes, qtd, "
                     "valor_centavos) VALUES (?,?,?,?,?,?,?,?)", linhas)
    conn.executemany("INSERT INTO rm_estoque_baixas (coligada, centro_custo, tipo_movimento, mes, qtd, valor_centavos) "
                     "VALUES (?,?,?,?,?,?)", [(1, "1.050.003", "1.1.21", "2024-10", 2, 50001),
                                              (1, "2.001.099", "1.1.21", "2024-10", 2, 3)])
    conn.commit(); conn.close()
    r = client_admin.get(f"/api/contratos/{cid}/custo-rm")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["custo"] == [
        {"centro_custo": "1.050.003", "projeto": None, "tarefa": None, "natureza": "2.02.001", "mes": "2024-11",
         "qtd": 1, "valor_centavos": -1001},
        {"centro_custo": "2.001.012", "projeto": "PRJ01", "tarefa": "1.02", "natureza": "1.01.003", "mes": "2026-03",
         "qtd": 3, "valor_centavos": 123457}]
    assert d["estoque"] == [{"centro_custo": "1.050.003", "tipo_movimento": "1.1.21", "mes": "2024-10", "qtd": 2,
                             "valor_centavos": 50001}]
    assert client_admin.get(f"/api/contratos/{sem_centro}/custo-rm").json() == {"custo": [], "estoque": []}
    assert client_admin.get("/api/contratos/9999/custo-rm").status_code == 404


def test_custo_rm_de_consorcio_sem_centro_vem_pela_coligada(client_admin):
    """#488: obra de consorcio sem centro de custo e' achada so' pela coligada, quando e' a unica obra dela."""
    from app import db, entidades
    conn = db.get_conn()
    eid = entidades.criar(conn, 1, {"nome": "Consórcio X", "cnpj": "11444777000161",
                                    "papel": "consorcio", "coligada_rm": 12})
    conn.close()
    cons = novo_contrato({**NOVO, "numero_instrumento": "IC 090/2025", "entidade_id": eid})
    lotufo_sem_centro = novo_contrato({**NOVO, "numero_instrumento": "IC 091/2025"})
    conn = db.get_conn()
    conn.executemany("INSERT INTO rm_custo_tarefas (coligada, centro_custo, projeto, tarefa, natureza, mes, qtd, "
                     "valor_centavos) VALUES (?,?,?,?,?,?,?,?)",
                     [(12, "1.01", None, None, "1.01.003", "2026-01", 1, 501), (1, "2.001.012", None, None,
                                                                                 "1.01.003", "2026-01", 1, 7)])
    conn.commit(); conn.close()
    d = client_admin.get(f"/api/contratos/{cons}/custo-rm").json()
    assert [x["valor_centavos"] for x in d["custo"]] == [501] and d["estoque"] == []
    # a Lotufo (coligada 1) sem centro nao recebe a coligada inteira
    assert client_admin.get(f"/api/contratos/{lotufo_sem_centro}/custo-rm").json() == {"custo": [], "estoque": []}
    # segunda obra na mesma coligada: a coligada deixa de identificar a obra, e nenhuma recebe o custo da outra
    outra = novo_contrato({**NOVO, "numero_instrumento": "IC 092/2025", "entidade_id": eid})
    for c in (cons, outra):
        assert client_admin.get(f"/api/contratos/{c}/custo-rm").json() == {"custo": [], "estoque": []}


def test_custo_rm_exige_ver_paineis(client, monkeypatch):
    from app import auth, db, permissoes
    cid = novo_contrato(NOVO)
    assert client.get(f"/api/contratos/{cid}/custo-rm").status_code == 401
    conn = db.get_conn()
    auth.criar_usuario(conn, "Dir", "dir@lotufo.com", "senha-forte-123", "diretoria")
    conn.close()
    r = client.post("/api/auth/login", json={"email": "dir@lotufo.com", "senha": "senha-forte-123"})
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))
    assert client.get(f"/api/contratos/{cid}/custo-rm").status_code == 200
    monkeypatch.setitem(permissoes.PERFIS, "diretoria", frozenset())
    assert client.get(f"/api/contratos/{cid}/custo-rm").status_code == 403


def test_ficha_traz_ultima_medicao_em_andamento_e_o_fim_da_execucao(client_admin, monkeypatch):
    """#510: a ficha executiva da obra. Ultima = a recebida mais nova; em andamento = a aberta mais nova, com a etapa
    e o desde; vencimentos = o fim da execucao, com o nivel do semaforo (sem certidao: #661; o fim da vigencia e a
    contagem das outras medicoes abertas sairam com os cartoes que os mostravam)."""
    import datetime
    from app import db, medicoes, tempo
    hoje = datetime.date(2026, 11, 6)
    monkeypatch.setattr(tempo, "hoje_local", lambda: hoje)
    cid = novo_contrato({**NOVO, "execucao_fim": "2026-11-18", "vigencia_fim": "2027-02-16"})
    conn = db.get_conn()
    a = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 15, "tipo": "execucao", "competencia": "2026-09"})
    medicoes.definir_valor(conn, 1, a, "protocolado", 787_288_979, "manual")
    conn.execute("UPDATE medicoes SET estado='recebida', recebida_em='2026-10-16', nota_emitida_em='2026-10-02' WHERE id=?", (a,))
    conn.commit()
    b = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 16, "tipo": "execucao", "competencia": "2026-10"})
    medicoes.definir_valor(conn, 1, b, "protocolado", 990_529_648, "manual")
    conn.execute("UPDATE medicoes SET estado='protocolada' WHERE id=?", (b,))
    conn.commit()
    conn.close()
    f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    assert f["ultima_medicao"]["titulo"] == "15ª Medição"
    assert f["ultima_medicao"]["valor_centavos"] == 787_288_979
    assert f["ultima_medicao"]["recebida_em"] == "2026-10-16" and f["ultima_medicao"]["dias_apos_nota"] == 14
    assert f["em_andamento"]["titulo"] == "16ª Medição" and f["em_andamento"]["valor_centavos"] == 990_529_648
    # #699: a etapa e' o nome do passo da vez (os seis de `medicoes.PASSOS`), nao uma palavra propria da ficha
    assert f["em_andamento"]["etapa"] == "Pagamento"
    v = {x["chave"]: x for x in f["vencimentos"]}
    assert v["execucao"]["data"] == "2026-11-18" and v["execucao"]["dias"] == 12 and v["execucao"]["nivel"] == "critico"
    assert set(v) == {"execucao"} and "outras" not in f["em_andamento"]
    assert f["contrato"]["original_igual"] is True and f["contrato"]["tas"] == 0
    conn = db.get_conn()
    conn.execute("UPDATE medicoes SET estado='espelho_enviado' WHERE id=?", (b,))
    conn.commit()
    conn.close()
    assert client_admin.get(f"/api/contratos/{cid}/ficha").json()["em_andamento"]["etapa"] == "Notas"


def test_ficha_e_cabecalho_sem_prazo_de_execucao_conhecido_mostram_so_a_data(client_admin, monkeypatch):
    """#662: execucao registrada vencida e aditivo posterior so' de vigencia: a data fica, sem dias nem vermelho."""
    import datetime
    from app import db, tempo
    monkeypatch.setattr(tempo, "hoje_local", lambda: datetime.date(2026, 12, 1))
    cid = novo_contrato({**NOVO, "execucao_fim": "2026-10-20", "vigencia_fim": "2027-02-16"})

    def execucao():
        f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
        cab = client_admin.get(f"/api/contratos/{cid}/cabecalho").json()
        v = {x["chave"]: x for x in f["vencimentos"]}["execucao"]
        return (v["data"], v["dias"], v["nivel"]), (cab["execucao_fim"], cab["dias_execucao"], cab["execucao_sem_prazo"])

    assert execucao() == (("2026-10-20", -42, "critico"), ("2026-10-20", -42, False))
    conn = db.get_conn()
    conn.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, nova_vigencia_fim, status, data_assinatura) "
                 "VALUES (?, 'prazo', 0, '2027-06-30', 'assinado', '2026-11-10')", (cid,))
    conn.commit(); conn.close()
    assert execucao() == (("2026-10-20", None, "normal"), ("2026-10-20", None, True))


def test_ficha_obra_sem_medicao_e_inexistente_404(client_admin):
    cid = novo_contrato(NOVO)
    f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    assert f["ultima_medicao"] is None and f["em_andamento"] is None
    assert client_admin.get("/api/contratos/99999/ficha").status_code == 404


def test_nivel_do_prazo_e_um_so_nos_limites_do_aviso():
    """Os limites sao os do aviso "Execução vencendo" (60 dias do fim, critico aos 30), em `prazos`: o numero dos
    dias da ficha, as linhas do tempo, a aba Prazos e os avisos usam a mesma funcao."""
    from app import prazos
    assert (prazos.DIAS_EXECUCAO, prazos.DIAS_CRITICO, prazos.DIAS_VIGENCIA) == (60, 30, 60)
    assert [prazos.nivel_do_prazo(d) for d in (None, -3, 30, 31, 60, 61)] == [
        "normal", "critico", "critico", "atencao", "atencao", "normal"]


def test_obra_paralisada_com_execucao_vencida_nao_tem_nivel_no_numero_nem_na_linha_do_tempo(client_admin, monkeypatch):
    """Uma regra so' para o painel "Prazo": o nivel do numero (ficha) e o das linhas do tempo (cabecalho) saem de
    `ficha_obra.nivel_do_prazo`. A obra ativa vencida e' critica nos dois; paralisada, em nenhum."""
    import datetime
    from app import db, tempo
    monkeypatch.setattr(tempo, "hoje_local", lambda: datetime.date(2026, 12, 1))
    cid = novo_contrato({**NOVO, "execucao_fim": "2026-10-20", "vigencia_fim": "2026-12-21"})

    def niveis():
        f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
        cab = client_admin.get(f"/api/contratos/{cid}/cabecalho").json()
        return f["vencimentos"][0]["nivel"], cab["nivel_execucao"], cab["nivel_vigencia"], cab["dias_execucao"]

    def prazos_da_aba():
        s = client_admin.get(f"/api/contratos/{cid}/prazos").json()["situacao"]
        return s["nivel_execucao"], s["nivel_vigencia"]

    assert niveis() == ("critico", "critico", "critico", -42)
    assert prazos_da_aba() == ("critico", "critico")          # a aba Prazos le a mesma regra
    conn = db.get_conn()
    conn.execute("UPDATE contratos SET estado='suspenso' WHERE id=?", (cid,))
    conn.commit(); conn.close()
    assert niveis() == ("normal", "normal", "normal", -42)
    assert prazos_da_aba() == ("normal", "normal")


def test_nivel_do_prazo_cala_onde_o_aviso_cala():
    """A regra unica (`prazos._niveis`): paralisacao registrada cala a execucao e nao a vigencia; a vigencia que o
    orgao prorroga junto nao tem nivel; em encerramento, nenhum dos dois."""
    from app import prazos
    s = {"dias_execucao": -5, "dias_vigencia": 45, "paralisacao": None, "vigencia_automatica": False, "encerramento": None}
    assert prazos._niveis("ativo", s) == ("critico", "atencao")
    assert prazos._niveis("ativo", {**s, "paralisacao": {"desde": "2026-09-01", "numero": None}}) == ("normal", "atencao")
    assert prazos._niveis("ativo", {**s, "vigencia_automatica": True}) == ("critico", "normal")
    assert prazos._niveis("ativo", {**s, "encerramento": {"desde": "2026-10-01"}}) == ("normal", "normal")
    assert prazos._niveis("ativo", {**s, "dias_execucao": None}) == ("normal", "atencao")
    assert prazos._niveis("encerrado", s) == ("normal", "normal")


def test_ficha_conta_so_os_tas_que_valem(client_admin):
    """Reajuste e aditivo corrigido por outro nao entram em "N TAs"; cancelado tambem nao."""
    from app import db
    cid = novo_contrato(NOVO)
    conn = db.get_conn()
    ins = ("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza, chave_cadastro, "
           "corrige_chave, cancelado_em) VALUES (?, ?, ?, 'assinado', '2026-03-01', ?, ?, ?, ?)")
    conn.execute(ins, (cid, "prazo", 0, None, "ta1", None, None))
    conn.execute(ins, (cid, "valor", 100, None, "ta2", None, None))
    conn.execute(ins, (cid, "valor", 100, None, "ta2b", "ta2", None))      # corrige o ta2: so' o corretor vale
    conn.execute(ins, (cid, "valor", 500, "reajuste", "rj", None, None))
    conn.execute(ins, (cid, "prazo", 0, None, "ta4", None, "2026-04-01"))  # cancelado
    conn.commit()
    conn.close()
    assert client_admin.get(f"/api/contratos/{cid}/ficha").json()["contrato"]["tas"] == 2


def _obra_com_reajuste_e_medicoes(bp=None):
    """Contrato com um aditivo de valor, um aditivo de reajuste e duas medicoes de execucao."""
    from app import db, medicoes
    cid = novo_contrato({**NOVO, "valor_original": "1.000.000,01"})
    conn = db.get_conn()
    if bp is not None:
        conn.execute("UPDATE contratos SET percentual_direito_bp=? WHERE id=?", (bp, cid))
    ins = ("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza, chave_cadastro) "
           "VALUES (?, 'valor', ?, 'assinado', '2026-03-01', ?, ?)")
    conn.execute(ins, (cid, 200_000_00, None, "ta1"))
    conn.execute(ins, (cid, 50_000_03, "reajuste", "rj1"))
    conn.commit()
    for numero, competencia, valor in ((1, "2026-04", 300_000_33), (2, "2026-05", 100_000_00)):
        m = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": numero, "tipo": "execucao", "competencia": competencia})
        medicoes.definir_valor(conn, 1, m, "protocolado", valor, "manual")
        conn.execute("UPDATE medicoes SET estado='protocolada' WHERE id=?", (m,))
        conn.commit()
    conn.close()
    return cid


def test_ficha_topo_na_base_de_execucao_sem_o_aditivo_de_reajuste(client_admin):
    """#646: valor vigente, medido e saldo do topo falam da mesma coisa: execucao a precos iniciais. O aditivo de
    reajuste fica fora dos tres e aparece a parte."""
    cid = _obra_com_reajuste_e_medicoes()
    f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    t = f["topo"]
    assert t["vigente_centavos"] == 1_200_000_01          # original + TA de valor, sem o reajuste
    assert t["medido_centavos"] == 400_000_33
    assert t["saldo_centavos"] == 799_999_68
    assert t["vigente_centavos"] - t["medido_centavos"] == t["saldo_centavos"]
    assert t["reajuste_centavos"] == 50_000_03
    assert f["contrato"]["original_centavos"] == 1_000_000_01 and f["contrato"]["original_igual"] is False


def test_ficha_topo_na_cota_da_lotufo_fecha_ao_centavo(client_admin):
    """#646: em consorcio os tres numeros vao na cota; vigente e medido arredondam uma vez cada e o saldo e' a
    diferenca dos dois (centavo impar e rateio com residuo: 49% de 1.200.000,01 e de 400.000,33 nao sao inteiros)."""
    cid = _obra_com_reajuste_e_medicoes(bp=4900)
    f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    t = f["topo"]
    assert t["vigente_centavos"] == 588_000_00            # 588.000,0049
    assert t["medido_centavos"] == 196_000_16             # 196.000,1617
    assert t["saldo_centavos"] == 391_999_84
    assert t["vigente_centavos"] - t["medido_centavos"] == t["saldo_centavos"]
    assert t["reajuste_centavos"] == 24_500_01            # 24.500,0147
    assert f["contrato"]["original_centavos"] == 490_000_00   # 490.000,0049


def test_ficha_original_igual_compara_com_o_vigente_de_execucao(client_admin):
    """#646: contrato so' com aditivo de reajuste: o valor vigente do topo (sem reajuste) e' o original."""
    from app import db
    cid = novo_contrato(NOVO)
    conn = db.get_conn()
    conn.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza, chave_cadastro) "
                 "VALUES (?, 'valor', 500, 'assinado', '2026-03-01', 'reajuste', 'rj')", (cid,))
    conn.commit()
    conn.close()
    f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    assert f["contrato"]["original_igual"] is True
    assert f["topo"]["vigente_centavos"] == 100_000_000 and f["topo"]["reajuste_centavos"] == 500


def test_ficha_ritmo_e_prazo_na_cota(client_admin, monkeypatch):
    """#655: o ritmo do painel "Prazo" fala na mesma base do resto do resumo: na cota da Lotufo. Conclusao, situacao
    e dias sao os de `prazos.ritmo_e_prazo`. O saldo e o fim da execucao sairam do bloco: a tela os tem no topo e na
    linha do tempo."""
    import datetime
    from app import contratos, db, prazos, tempo
    hoje = datetime.date(2026, 10, 15)   # janela 04 a 09/2026: as duas medicoes do cenario estao nela
    monkeypatch.setattr(tempo, "hoje_local", lambda: hoje)
    cid = _obra_com_reajuste_e_medicoes(bp=4900)
    conn = db.get_conn()
    conn.execute("UPDATE contratos SET execucao_fim='2026-12-20' WHERE id=?", (cid,))
    conn.commit()
    cheio = prazos.ritmo_e_prazo(conn, cid, hoje)
    conn.close()
    f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    r = f["ritmo"]
    assert cheio["ritmo_centavos"] == 66_666_72 and cheio["situacao"] == "atrasa" and cheio["dias_alem"] > 0
    assert r["ritmo_centavos"] == contratos.cota(66_666_72, 4900) == 32_666_69
    assert f["topo"]["saldo_centavos"] == 391_999_84
    assert set(r) == {"ritmo_centavos", "necessario_centavos", "competencias_restantes", "conclusao", "situacao", "dias_alem",
                      "leitura"}
    # #822: as medicoes do cenario sao de abril e maio: em outubro a obra esta' ha' tres competencias sem medir, fora
    # da regua. A conclusao estimada continua; o selo dela (situacao e dias) se cala junto com a leitura
    assert (r["conclusao"], r["situacao"], r["dias_alem"]) == (cheio["conclusao"], None, None)
    assert r["leitura"]["motivo"] == "sem_medicao"
    # #803: o necessario por mes vai na cota e fecha com o topo da tela: vigente - medido = saldo, e o saldo dividido
    # pelas competencias que restam (outubro, novembro e dezembro) e' o necessario mostrado, ao centavo
    t = f["topo"]
    assert (cheio["necessario_centavos"], cheio["competencias_restantes"]) == (266_666_56, 3)   # 799.999,68 / 3
    assert r["competencias_restantes"] == 3
    assert r["necessario_centavos"] == prazos.necessario_por_mes(t["vigente_centavos"] - t["medido_centavos"], 3) == 130_666_61
    # so' a obra ativa, fora do encerramento e sem paralisacao tem prazo a cobrar: na que ja' fez a medicao final,
    # o painel dizia "N dias alem do prazo" pelo ritmo ao lado de "vencido ha' N dias". O ritmo continua
    conn = db.get_conn()
    conn.execute("UPDATE contratos SET encerramento_iniciado_em='2026-10-01' WHERE id=?", (cid,))
    conn.commit()
    r = prazos.ritmo_e_prazo(conn, cid, hoje)
    assert (r["ritmo_centavos"], r["conclusao"], r["situacao"], r["dias_alem"]) == (66_666_72, None, None, None)
    assert (r["necessario_centavos"], r["competencias_restantes"]) == (None, None)
    nulo = client_admin.get(f"/api/contratos/{cid}/ficha").json()["ritmo"]
    assert (nulo["ritmo_centavos"], nulo["necessario_centavos"], nulo["competencias_restantes"]) == (32_666_69, None, None)
    conn.execute("UPDATE contratos SET encerramento_iniciado_em=NULL WHERE id=?", (cid,))
    conn.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) VALUES (?, 'par-1', 'paralisacao', "
                 "'2026-10-10', '{}')", (cid,))
    conn.commit()
    assert prazos.ritmo_e_prazo(conn, cid, hoje)["situacao"] is None
    conn.execute("DELETE FROM instrumentos WHERE contrato_id=?", (cid,))
    conn.execute("UPDATE contratos SET estado='encerrado' WHERE id=?", (cid,))
    conn.commit()
    assert prazos.ritmo_e_prazo(conn, cid, hoje)["situacao"] is None
    conn.close()


def test_ficha_necessario_na_cota_fecha_com_o_saldo_da_tela(client_admin, monkeypatch):
    """#803: na cota, o necessario e' o saldo do topo (a diferenca de dois valores ja' arredondados) dividido pelas
    competencias que restam, para a conta da tela fechar ao centavo; a cota do necessario cheio ficaria a um centavo."""
    import datetime
    from app import contratos, db, prazos, tempo
    hoje = datetime.date(2026, 10, 15)
    monkeypatch.setattr(tempo, "hoje_local", lambda: hoje)
    cid = _obra_com_reajuste_e_medicoes(bp=4900)
    conn = db.get_conn()
    conn.execute("UPDATE contratos SET execucao_fim='2026-12-20' WHERE id=?", (cid,))
    conn.execute("UPDATE medicoes SET valor_protocolado_centavos=100_000_17 WHERE contrato_id=? AND numero=2", (cid,))
    conn.commit()
    cheio = prazos.ritmo_e_prazo(conn, cid, hoje)
    conn.close()
    f = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    assert f["topo"]["saldo_centavos"] == 391_999_75 and f["ritmo"]["competencias_restantes"] == 3
    assert f["ritmo"]["necessario_centavos"] == 130_666_58                       # 391.999,75 / 3 = 130.666,583
    assert cheio["necessario_centavos"] == 266_666_50 and contratos.cota(266_666_50, 4900) == 130_666_59


def test_listar_traz_a_posicao_na_cota_igual_ao_topo_da_pagina_da_obra(client_admin):
    """#645: a lista de Obras le `posicao` (vigente, medido e saldo de execucao, na cota da Lotufo), a mesma conta do
    topo da pagina da obra, obra a obra; os campos cheios de antes continuam para as outras telas."""
    consorcio = _obra_com_reajuste_e_medicoes(bp=4900)
    propria = _obra_com_reajuste_e_medicoes()
    lista = {c["id"]: c for c in client_admin.get("/api/contratos").json()}
    p = lista[consorcio]["posicao"]
    assert p["vigente_centavos"] == 588_000_00            # 49% de 1.200.000,01, sem o aditivo de reajuste
    assert p["medido_centavos"] == 196_000_16             # 49% de 400.000,33
    assert p["saldo_centavos"] == 391_999_84 == p["vigente_centavos"] - p["medido_centavos"]
    assert lista[consorcio]["medido_centavos"] == 400_000_33     # o cheio de antes nao mudou
    assert lista[propria]["posicao"]["vigente_centavos"] == 1_200_000_01
    for cid in (consorcio, propria):
        topo = client_admin.get(f"/api/contratos/{cid}/ficha").json()["topo"]
        for campo in ("vigente_centavos", "medido_centavos", "saldo_centavos"):
            assert lista[cid]["posicao"][campo] == topo[campo]


def test_listar_traz_o_a_receber_na_cota_so_com_o_total_liberado(client_admin):
    """#645: o a receber da lista vai na cota, cobranca a cobranca (a conta da tela A receber); nulo ate' liberar."""
    import json
    from app import db, diretoria
    cid = _obra_com_reajuste_e_medicoes(bp=4900)          # protocoladas: 300.000,33 e 100.000,00
    outro = novo_contrato({**NOVO, "numero_instrumento": "IC 084/2025"})
    lista = {c["id"]: c for c in client_admin.get("/api/contratos").json()}
    assert lista[cid]["posicao"]["a_receber_centavos"] is None
    conn = db.get_conn()
    conn.execute("INSERT OR REPLACE INTO cadastro_geral (chave, valor) VALUES ('diretoria', ?)", (json.dumps({"total_a_receber_liberado": True}),))
    conn.commit()
    tela = diretoria.a_receber_por_obra(conn, na_cota=True)
    conn.close()
    lista = {c["id"]: c for c in client_admin.get("/api/contratos").json()}
    assert lista[cid]["posicao"]["a_receber_centavos"] == 147_000_16 + 49_000_00 == tela[cid]   # 147.000,1617 e 49.000,00
    assert "a_receber_centavos" not in lista[cid]                         # o cheio saiu da lista
    assert lista[outro]["posicao"]["a_receber_centavos"] == 0


def test_ficha_vencimentos_sem_certidao_da_empresa(client_admin, monkeypatch):
    """#661: certidao e' da empresa e se resolve em Documentos; "Proximos vencimentos" fica com o que e' da obra,
    mesmo com certidao exigida perto de vencer."""
    import datetime
    from app import certidoes, contratos, db, documentos, tempo
    hoje = datetime.date(2026, 11, 6)
    monkeypatch.setattr(tempo, "hoje_local", lambda: hoje)
    cid = novo_contrato({**NOVO, "execucao_fim": "2026-11-18", "vigencia_fim": "2027-02-16"})
    conn = db.get_conn()
    try:
        c = conn.execute("SELECT * FROM contratos WHERE id=?", (cid,)).fetchone()
        ex = documentos.exigidos(conn, cid, "execucao")
        assert ex["tipos"], "o cenario precisa de certidao exigida"
        certidoes.registrar(conn, 1, contratos.entidade_de(c), ex["tipos"][0]["id"], "2026-08-01", "2026-11-10",
                            "dados/certidoes/teste.pdf", "a" * 64, "upload")
    finally:
        conn.close()
    venc = client_admin.get(f"/api/contratos/{cid}/ficha").json()["vencimentos"]
    assert [x["chave"] for x in venc] == ["execucao"]


def test_cabecalho_da_obra_encerrada_pelo_cadastro_traz_a_data_do_encerramento(client_admin):
    """A obra que entra no cadastro ja' encerrada, com `status_desde`, chega a' pagina com a data ("encerrada desde"):
    o `cadastro-exemplo/` inteiro aplicado, lido pela API do cabecalho."""
    from app import cadastro_aplicar, cadastro_arquivos, db
    from tests.conftest import CADASTRO_EXEMPLO
    conn = db.get_conn()
    cadastro_aplicar.aplicar(conn, 1, cadastro_arquivos.preparar(CADASTRO_EXEMPLO))
    ids = {r["nome_curto"]: r["id"] for r in conn.execute("SELECT id, nome_curto FROM contratos")}
    conn.close()
    cab = client_admin.get(f"/api/contratos/{ids['Obra Encerrada']}/cabecalho").json()
    assert (cab["status"], cab["status_desde"]) == ("encerrado", "2023-11-17")
    assert client_admin.get(f"/api/contratos/{ids['Obra Própria']}/cabecalho").json()["status_desde"] is None


def test_listar_traz_o_andamento_na_cota_pela_conta_da_pagina_da_obra(client_admin, monkeypatch):
    """#805: a coluna Andamento da lista de Obras le o ritmo e o necessario por mes de `andamento`, na cota, pela mesma
    conta do painel "Prazo" da pagina da obra (`prazos.ritmo_na_cota`): os dois numeros sao os da ficha, ao centavo."""
    import datetime
    from app import db, prazos, tempo
    hoje = datetime.date(2026, 10, 15)   # janela 04 a 09/2026; restam outubro, novembro e dezembro
    monkeypatch.setattr(tempo, "hoje_local", lambda: hoje)
    cid = _obra_com_reajuste_e_medicoes(bp=4900)
    sem_medicao = novo_contrato({**NOVO, "numero_instrumento": "IC 083/2025"})      # execucao ate' 30/06/2027
    encerrada = _obra_com_reajuste_e_medicoes()
    conn = db.get_conn()
    conn.execute("UPDATE contratos SET execucao_fim='2026-12-20' WHERE id IN (?, ?)", (cid, encerrada))
    conn.execute("UPDATE contratos SET estado='encerrado' WHERE id=?", (encerrada,))
    conn.commit()
    conn.close()
    lista = {c["id"]: c for c in client_admin.get("/api/contratos").json()}

    def valores(a):
        return {k: a[k] for k in ("ritmo_centavos", "necessario_centavos")}

    assert valores(lista[cid]["andamento"]) == {"ritmo_centavos": 32_666_69, "necessario_centavos": 130_666_61}
    ficha = client_admin.get(f"/api/contratos/{cid}/ficha").json()
    assert valores(lista[cid]["andamento"]) == valores(ficha["ritmo"])
    # o necessario fecha com o saldo que a propria lista mostra: saldo / competencias que restam
    assert lista[cid]["andamento"]["necessario_centavos"] == prazos.necessario_por_mes(lista[cid]["posicao"]["saldo_centavos"], 3)
    # #822: a leitura vem pronta, e e' a da ficha. As medicoes do cenario sao de abril e maio: em outubro, julho,
    # agosto e setembro fecharam sem medicao
    assert lista[cid]["andamento"]["leitura"] == ficha["ritmo"]["leitura"] == {
        **SEM_LEITURA, "motivo": "sem_medicao", "sem_medicao_desde": "2026-05"}
    # sem medicao na janela nao ha' ritmo; o necessario continua (9 competencias, de 10/2026 a 06/2027). A obra que
    # nunca mediu execucao nao tem leitura nem motivo
    assert lista[sem_medicao]["andamento"] == {"ritmo_centavos": None, "leitura": SEM_LEITURA,
                                               "necessario_centavos": prazos.necessario_por_mes(100_000_000, 9)}
    # obra encerrada nao tem prazo a cumprir: sem necessario (a tela nao desenha o andamento)
    assert lista[encerrada]["andamento"] == {"ritmo_centavos": 66_666_72, "necessario_centavos": None, "leitura": SEM_LEITURA}


SEM_LEITURA = {"situacao": None, "pct": None, "motivo": None, "prorrogacao_pedida": False, "sem_medicao_desde": None,
               "atencao_desde_pct": 70, "adiantada_desde_pct": 100}


def test_a_lista_e_a_pagina_da_obra_dao_a_mesma_leitura_do_andamento(client_admin, monkeypatch):
    """#822: a leitura do andamento nasce numa funcao so' (`prazos.ritmo_na_cota`), e `GET /api/contratos` e
    `GET /api/contratos/{id}/ficha` a devolvem igual para a mesma obra, em cada caso da regua: com leitura (tres
    competencias), prazo no fim (duas), prorrogacao pedida, sem medicao ha' tres competencias, ritmo que nao fecha a
    conclusao estimada (a pagina calava a situacao e a lista escrevia "Devagar") e obra sem prazo a cumprir."""
    import datetime
    from app import db, medicoes, tempo
    hoje = datetime.date(2026, 11, 18)   # janela 05 a 10/2026
    monkeypatch.setattr(tempo, "hoje_local", lambda: hoje)
    conn = db.get_conn()

    def obra(numero, execucao_fim, meds, bp=None, pedido=None, estado=None):
        cid = novo_contrato({**NOVO, "numero_instrumento": numero, "execucao_fim": execucao_fim})
        if bp is not None:
            conn.execute("UPDATE contratos SET percentual_direito_bp=? WHERE id=?", (bp, cid))
        if estado:
            conn.execute("UPDATE contratos SET estado=? WHERE id=?", (estado, cid))
        if pedido:
            conn.execute("INSERT INTO pleitos (contrato_id, tipo, origem, numero_oficio, situacao, enviado_em) "
                         "VALUES (?, 'prazo', 'cadastro', 'CT-001-LT-2026', 'enviado', ?)", (cid, pedido))
        conn.commit()
        for n, (competencia, valor) in enumerate(meds, start=1):
            m = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": n, "tipo": "execucao", "competencia": competencia})
            medicoes.definir_valor(conn, 1, m, "protocolado", valor, "manual")
            conn.execute("UPDATE medicoes SET estado='protocolada' WHERE id=?", (m,))
            conn.commit()
        return cid

    recentes = (("2026-09", 150_000_00), ("2026-10", 150_000_00))     # ritmo 50.000,00; saldo 700.000,00
    casos = {
        "tres competencias": (obra("IC 101/2025", "2027-01-31", recentes, bp=4900), {"situacao": "devagar", "pct": 21}),
        "duas competencias": (obra("IC 102/2025", "2026-12-31", recentes), {"motivo": "prazo_no_fim"}),
        "duas, com pedido": (obra("IC 103/2025", "2026-12-31", recentes, pedido="2026-11-04"),
                             {"motivo": "prazo_no_fim", "prorrogacao_pedida": True}),
        "prorrogacao pedida": (obra("IC 104/2025", "2027-06-30", recentes, pedido="2026-11-04"),
                               {"motivo": "prorrogacao_pedida", "prorrogacao_pedida": True}),
        "sem medicao": (obra("IC 105/2025", "2027-06-30", (("2026-07", 300_000_00),)),
                        {"motivo": "sem_medicao", "sem_medicao_desde": "2026-07"}),
        "conclusao nao fecha": (obra("IC 106/2025", "2027-06-30", (("2026-10", 6_00),)), {"situacao": "devagar", "pct": 0}),
        "adiantada": (obra("IC 107/2025", "2027-06-30", (("2026-08", 300_000_00), ("2026-09", 300_000_00), ("2026-10", 300_000_00))),
                      {"situacao": "adiantada", "pct": 1200}),
        "encerrada": (obra("IC 108/2025", "2027-06-30", recentes, estado="encerrado"), {}),
        "nunca mediu": (obra("IC 109/2025", "2027-06-30", ()), {}),
    }
    conn.close()
    lista = {c["id"]: c for c in client_admin.get("/api/contratos").json()}
    for nome, (cid, esperado) in casos.items():
        da_lista = lista[cid]["andamento"]["leitura"]
        da_ficha = client_admin.get(f"/api/contratos/{cid}/ficha").json()["ritmo"]["leitura"]
        assert da_lista == da_ficha == {**SEM_LEITURA, **esperado}, nome

    def ritmo_da_ficha(nome):
        return client_admin.get(f"/api/contratos/{casos[nome][0]}/ficha").json()["ritmo"]

    # a pagina da obra calava a situacao deste caso (conclusao alem do teto do pedido): continua sem conclusao
    # estimada, e a leitura agora e' a da lista
    ficha = ritmo_da_ficha("conclusao nao fecha")
    assert (ficha["conclusao"], ficha["situacao"]) == (None, None) and ficha["leitura"]["situacao"] == "devagar"
    # o selo da conclusao estimada acompanha a leitura: com ela, diz os dias alem do fim (ou que esta' no ritmo); fora
    # da regua se cala, e a data da conclusao fica
    ficha = ritmo_da_ficha("tres competencias")
    assert ficha["situacao"] == "atrasa" and ficha["dias_alem"] > 0
    assert ritmo_da_ficha("adiantada")["situacao"] == "no_prazo"
    for nome in ("duas competencias", "duas, com pedido", "prorrogacao pedida", "sem medicao"):
        ficha = ritmo_da_ficha(nome)
        assert ficha["conclusao"] and (ficha["situacao"], ficha["dias_alem"]) == (None, None), nome


def test_listar_traz_o_medido_do_mes_fechado_igual_ao_do_fechamento(client_admin, monkeypatch):
    """#805: `medido_mes` e' o medido da obra na ultima competencia fechada (o mes anterior ao de hoje) e, como
    referencia da variacao, o da competencia antes dela; na cota, o mesmo numero do Fechamento para a obra no mes."""
    import datetime
    from app import contratos, db, fechamento, tempo
    hoje = datetime.date(2026, 10, 15)
    monkeypatch.setattr(tempo, "hoje_local", lambda: hoje)
    cid = novo_contrato(NOVO)
    parada = novo_contrato({**NOVO, "numero_instrumento": "IC 083/2025"})
    conn = db.get_conn()
    conn.execute("UPDATE contratos SET percentual_direito_bp=4900 WHERE id=?", (cid,))
    ins = ("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
           "valor_atestado_centavos) VALUES (?, ?, ?, ?, ?, ?, ?)")
    conn.execute(ins, (cid, 1, "execucao", "2026-08", "recebida", 50_000_01, None))
    conn.execute(ins, (cid, 2, "execucao", "2026-09", "boletim_recebido", 100_000_01, 90_000_03))   # o aprovado vale
    conn.execute(ins, (cid, 2, "reajuste", "2026-09", "planilha_enviada", 7_000_01, None))          # em analise: o pedido
    conn.execute(ins, (cid, 3, "execucao", "2026-10", "planilha_enviada", 1_000_00, None))          # o mes em curso fica fora
    conn.commit()
    lista = {c["id"]: c for c in client_admin.get("/api/contratos").json()}
    assert lista[cid]["medido_mes"] == {
        "competencia": "2026-09", "valor_centavos": contratos.cota(90_000_03, 4900) + contratos.cota(7_000_01, 4900),
        "referencia_competencia": "2026-08", "referencia_centavos": contratos.cota(50_000_01, 4900)}
    assert lista[cid]["medido_mes"]["valor_centavos"] == 44_100_01 + 3_430_00
    assert lista[parada]["medido_mes"] == {"competencia": "2026-09", "valor_centavos": 0,
                                           "referencia_competencia": "2026-08", "referencia_centavos": 0}
    f = fechamento.fechamento(conn, hoje)
    conn.close()
    do_fechamento = {m["competencia"]: {o["contrato_id"]: o["medido_centavos"] for o in m["obras"]} for m in f["meses"]}
    assert lista[cid]["medido_mes"]["valor_centavos"] == do_fechamento["2026-09"][cid]
    assert lista[cid]["medido_mes"]["referencia_centavos"] == do_fechamento["2026-08"][cid]


def test_listar_traz_a_chave_do_contratante_pelo_que_o_servidor_agrupa(client_admin):
    """#805: a pagina do contratante tem endereco pela `contratante_chave`: "sinfra" para a familia toda (um
    contratante so'), a chave do orgao no cadastro nos outros, e nula no contrato sem orgao no cadastro."""
    from app import db
    a = novo_contrato(NOVO)
    b = novo_contrato({**NOVO, "numero_instrumento": "IC 083/2025"})
    c = novo_contrato({**NOVO, "numero_instrumento": "IC 084/2025", "orgao": "texto livre"})
    d = novo_contrato({**NOVO, "numero_instrumento": "IC 085/2025", "orgao": "sem cadastro"})
    conn = db.get_conn()
    conn.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('sinfra-suef2', 'SINFRA - SUEF II', 'sinfra', '{}')")
    conn.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('sinfra-supu', 'SINFRA - SUPU', 'sinfra', '{}')")
    conn.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('pref-cuiaba', 'Prefeitura de Cuiabá', 'prefeitura', '{}')")
    conn.execute("UPDATE contratos SET orgao_id=(SELECT id FROM orgaos WHERE chave='sinfra-suef2') WHERE id=?", (a,))
    conn.execute("UPDATE contratos SET orgao_id=(SELECT id FROM orgaos WHERE chave='sinfra-supu') WHERE id=?", (b,))
    conn.execute("UPDATE contratos SET orgao_id=(SELECT id FROM orgaos WHERE chave='pref-cuiaba') WHERE id=?", (c,))
    conn.commit(); conn.close()
    lista = {x["id"]: x for x in client_admin.get("/api/contratos").json()}
    assert [(lista[i]["contratante"], lista[i]["contratante_chave"]) for i in (a, b, c, d)] == [
        ("SINFRA", "sinfra"), ("SINFRA", "sinfra"), ("Pref. Cuiabá", "pref-cuiaba"), ("sem cadastro", None)]
    # a pagina da obra recebe os mesmos dois, para o caminho "Obras > contratante > obra"
    for i in (a, c, d):
        cab = client_admin.get(f"/api/contratos/{i}/cabecalho").json()
        assert (cab["contratante"], cab["contratante_chave"]) == (lista[i]["contratante"], lista[i]["contratante_chave"])
