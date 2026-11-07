"""Issue #491: custo lancado no RM por grupo da planilha, medicao a medicao (aba Custo da Carteira)."""
import json

import pytest

from app import auth, contratos, cronograma, custo_obra, db, entidades, medicao_grupos


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "engenharia")
    yield c
    c.close()


GRUPOS = [("Terraplenagem", ["001.01"]), ("Pavimentação", ["001.02", "001.03"])]
P = "GL.C01.P704"


def _obra(conn, centro="2.001.012", grupos=GRUPOS, nome="Obra Alfa", entidade_id=None, anteriores=None):
    dados = {"orgao": "SINFRA", "numero_instrumento": f"IC {nome}", "objeto": nome,
             "valor_original_centavos": 1_000_000_00, "centro_custo_rm": centro}
    if entidade_id:
        dados["entidade_id"] = entidade_id
    cid = contratos.criar(conn, 1, dados)
    conn.execute("UPDATE contratos SET nome_curto=?, centros_custo_anteriores_rm=? WHERE id=?",
                 (nome, json.dumps(anteriores) if anteriores else None, cid))
    if grupos:
        conn.execute("UPDATE contratos SET projeto_rm=?, custo_nao_e_custo=?, custo_sem_tarefa='proporcional' "
                     "WHERE id=?", (P, json.dumps(["2.02", "2.01.22"]), cid))
        for ordem, (g, tarefas) in enumerate(grupos, 1):
            conn.execute("INSERT INTO custo_grupos (contrato_id, ordem, nome, tarefas, itens_planilha) VALUES (?,?,?,?,?)",
                         (cid, ordem, g, json.dumps(tarefas), json.dumps([f"{ordem}."])))
    conn.commit()
    return cid


def _medicao(conn, cid, numero, competencia, valor, atestado=None, estado="protocolada", tipo="execucao"):
    mid = conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
                       "valor_atestado_centavos) VALUES (?,?,?,?,?,?,?)",
                       (cid, numero, tipo, competencia, estado, valor, atestado)).lastrowid
    conn.commit()
    return mid


def _item(valor):
    return {"item": "1", "codigo": None, "descricao": "x", "unidade": "m", "quantidade_contratada": None,
            "quantidade_medida": "1", "quantidade_acumulada": None, "preco_unitario_centavos": None,
            "valor_medido_centavos": valor, "valor_acumulado_centavos": None}


def _leitura(conn, cid, mid, por_grupo: dict[str, int]):
    cad = medicao_grupos.cadastro_de_custo(conn, cid)
    pedido = conn.execute("SELECT valor_protocolado_centavos FROM medicoes WHERE id=?", (mid,)).fetchone()[0]
    lido = {"grupo_por": "cadastro", "grupos": [{"nome": g, "itens": [_item(v)]} for g, v in por_grupo.items()]}
    with db.mutacao(conn):
        medicao_grupos._gravar(conn, None, mid, "a" * 64, "carga", None, None, "lida", None, lido,
                               medicao_grupos._assinatura(cad), sum(por_grupo.values()), pedido)


def _custo(conn, linhas):
    conn.executemany("INSERT INTO rm_custo_tarefas (coligada, centro_custo, projeto, tarefa, natureza, mes, qtd, "
                     "valor_centavos) VALUES (?,?,?,?,?,?,1,?)", linhas)
    conn.commit()


def _estoque(conn, linhas):
    conn.executemany("INSERT INTO rm_estoque_baixas (coligada, centro_custo, tipo_movimento, mes, qtd, valor_centavos) "
                     "VALUES (?,?,'1.1.21',?,1,?)", linhas)
    conn.commit()


def _linha(r, comp):
    return next(x for x in r["linhas"] if x["competencia"] == comp)


def _grupo(linha, nome):
    return next(g for g in linha["grupos"] if g["nome"] == nome)


def test_obras_so_com_cadastro_de_custo_e_fora_o_consorcio(conn):
    alfa = _obra(conn)
    sem = _obra(conn, centro="2.001.013", grupos=None, nome="Sem Cadastro")
    eid = entidades.criar(conn, 1, {"nome": "Consórcio X", "cnpj": "11444777000161", "papel": "consorcio",
                                    "coligada_rm": 12})
    cons = _obra(conn, centro="2.001.014", nome="Do Consórcio", entidade_id=eid)
    assert custo_obra.obras(conn) == [{"contrato_id": alfa, "obra": "Obra Alfa"}]
    for cid in (sem, cons, 9999):
        with pytest.raises(custo_obra.SemCadastro):
            custo_obra.custo_da_obra(conn, cid)


def test_soma_por_grupo_e_mes_pelos_prefixos_sem_natureza_nao_custo(conn):
    cid = _obra(conn, anteriores=["1.050.003"])
    _medicao(conn, cid, 1, "2026-03", 500_000_01)
    _custo(conn, [
        (1, "2.001.012", P, "001.01.004", "1.01.003", "2026-03", 100_000_01),   # Terraplenagem
        (1, "1.050.003", P, "001.01", "1.01.003", "2026-03", 1_00),             # centro anterior
        (1, "2.001.012", P, "001.02.1", "1.01.003", "2026-03", 30_000_00),      # Pavimentacao
        (1, "2.001.012", P, "001.03", "1.01.009", "2026-03", 20_000_00),        # Pavimentacao
        (1, "2.001.012", P, "001.010", "1.01.003", "2026-03", 7_00),            # 001.010 nao e' 001.01: fora
        (1, "2.001.012", "OUTRO.PRJ", "001.01", "1.01.003", "2026-03", 3_00),   # outro projeto: fora
        (1, "2.001.012", P, "001.02", "2.02.001", "2026-03", 9_999_00),         # nao e' custo
        (1, "2.001.012", P, "001.02", "2.01.22", "2026-03", 8_888_00),          # adiantamento: nao e' custo
        (1, "2.001.012", P, "001.02", "1.01.003", "2026-04", 5_00),             # outro mes
        (1, "2.001.099", P, "001.01", "1.01.003", "2026-03", 777_00),           # outra obra
        (12, "2.001.012", P, "001.01", "1.01.003", "2026-03", 666_00),          # outra coligada
    ])
    r = custo_obra.custo_da_obra(conn, cid)
    mar = _linha(r, "2026-03")
    assert _grupo(mar, "Terraplenagem")["apontado_centavos"] == 100_001_01
    assert _grupo(mar, "Pavimentação")["apontado_centavos"] == 50_000_00
    assert _grupo(mar, "Tarefa fora dos grupos")["apontado_centavos"] == 10_00
    assert mar["custo_centavos"] == 150_011_01
    assert all(g["rateado_centavos"] == 0 for g in mar["grupos"])
    assert _linha(r, "2026-04")["custo_centavos"] == 5_00
    assert _linha(r, "2026-04")["medicoes"] == []


def test_sem_tarefa_e_estoque_rateados_na_proporcao_com_residuo(conn):
    cid = _obra(conn)
    _custo(conn, [
        (1, "2.001.012", P, "001.01", "1.01.003", "2026-03", 1_00),       # Terraplenagem: peso 1
        (1, "2.001.012", P, "001.02", "1.01.003", "2026-03", 2_00),       # Pavimentacao: peso 2
        (1, "2.001.012", None, None, "1.02.001", "2026-03", 10_00),       # folha: sem tarefa
        (1, "2.001.012", None, None, "2.02.005", "2026-03", 50_00),       # sem tarefa, mas nao e' custo
    ])
    _estoque(conn, [(1, "2.001.012", "2026-03", 1), (1, "2.001.099", "2026-03", 99_00)])
    mar = _linha(custo_obra.custo_da_obra(conn, cid), "2026-03")
    t, p = _grupo(mar, "Terraplenagem"), _grupo(mar, "Pavimentação")
    # rateado 10,01 na proporcao 1:2 -> 3,33(67) e 6,67(33): o centavo do residuo vai para o maior resto
    assert (t["rateado_centavos"], p["rateado_centavos"]) == (3_34, 6_67)
    assert (t["custo_centavos"], p["custo_centavos"]) == (4_34, 8_67)
    assert mar["custo_centavos"] == 13_01
    assert not any(g["tipo"] == "sem_grupo" for g in mar["grupos"])


def test_mes_sem_custo_apontado_deixa_o_rateado_sem_grupo(conn):
    cid = _obra(conn)
    _custo(conn, [(1, "2.001.012", None, None, "1.02.001", "2026-05", 12_345_67)])
    _estoque(conn, [(1, "2.001.012", "2026-05", 1_00)])
    mai = _linha(custo_obra.custo_da_obra(conn, cid), "2026-05")
    sem = _grupo(mai, "Sem grupo")
    assert sem["tipo"] == "sem_grupo" and sem["rateado_centavos"] == 12_346_67 and sem["apontado_centavos"] == 0
    assert all(g["custo_centavos"] == 0 for g in mai["grupos"] if g["tipo"] == "grupo")


def test_medido_por_grupo_lido_e_medicao_sem_leitura_vira_nao_lido(conn):
    cid = _obra(conn)
    m1 = _medicao(conn, cid, 1, "2026-03", 300_00)
    _leitura(conn, cid, m1, {"Terraplenagem": 100_00, "Pavimentação": 200_00})
    _medicao(conn, cid, 2, "2026-04", 450_01)
    _medicao(conn, cid, 3, "2026-04", 1_00, estado="cancelada")
    _medicao(conn, cid, 1, "2026-04", 9_00, tipo="reajuste")
    _custo(conn, [(1, "2.001.012", P, "001.01", "1.01.003", "2026-03", 40_00)])
    r = custo_obra.custo_da_obra(conn, cid)
    mar, abr = _linha(r, "2026-03"), _linha(r, "2026-04")
    assert [m["nome"] for m in mar["medicoes"]] == ["1ª medição"]
    assert _grupo(mar, "Terraplenagem")["medido_centavos"] == 100_00
    assert _grupo(mar, "Terraplenagem")["diferenca_centavos"] == 60_00
    assert _grupo(mar, "Pavimentação")["medido_centavos"] == 200_00
    assert mar["medido_centavos"] == 300_00 and mar["diferenca_centavos"] == 260_00
    nao = _grupo(abr, "Medido por grupo não lido")
    assert nao["tipo"] == "nao_lido" and nao["medido_centavos"] == 450_01
    assert abr["medido_centavos"] == 450_01
    assert all(g["medido_centavos"] is None for g in abr["grupos"] if g["tipo"] == "grupo")
    # medido do grupo desconhecido (esta' no "nao lido"): sem diferenca, nunca o custo negativo
    assert all(g["diferenca_centavos"] is None for g in abr["grupos"] if g["tipo"] == "grupo")
    assert nao["diferenca_centavos"] == 450_01


def test_atestado_diferente_da_planilha_vira_ajuste_e_a_linha_fecha(conn):
    cid = _obra(conn)
    m1 = _medicao(conn, cid, 1, "2026-03", 300_00, atestado=290_01)
    _leitura(conn, cid, m1, {"Terraplenagem": 100_00, "Pavimentação": 200_00})
    mar = _linha(custo_obra.custo_da_obra(conn, cid), "2026-03")
    assert mar["medido_centavos"] == 290_01
    assert _grupo(mar, "Ajuste ao medido")["medido_centavos"] == -9_99
    assert sum(g["medido_centavos"] or 0 for g in mar["grupos"]) == mar["medido_centavos"]


def test_previsto_do_cronograma_e_acumulado_bate_com_a_soma_das_linhas(conn):
    cid = _obra(conn)
    cronograma.nova_versao(conn, 1, cid, [("2026-02", 50_00), ("2026-03", 1_000_00), ("2026-04", 2_000_01),
                                          ("2026-05", 3_00), ("2026-07", 9_000_00)], "manual")
    m1 = _medicao(conn, cid, 1, "2026-03", 333_33)
    _leitura(conn, cid, m1, {"Terraplenagem": 333_33})
    _medicao(conn, cid, 2, "2026-04", 111_11)
    _custo(conn, [(1, "2.001.012", P, "001.01", "1.01.003", "2026-03", 100_01),
                  (1, "2.001.012", P, "001.02", "1.01.003", "2026-04", 50_00),
                  (1, "2.001.012", None, None, "1.02.001", "2026-04", 25_01),
                  (1, "2.001.012", None, None, "1.02.001", "2026-06", 7_00)])
    r = custo_obra.custo_da_obra(conn, cid)
    # os meses so' de cronograma ate' a ultima linha com dado (06/2026) viram linha; 07 fica fora
    assert [x["competencia"] for x in r["linhas"]] == ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    assert _linha(r, "2026-02")["previsto_centavos"] == 50_00 and _linha(r, "2026-02")["grupos"][0]["custo_centavos"] == 0
    assert _linha(r, "2026-03")["previsto_centavos"] == 1_000_00
    assert _linha(r, "2026-06")["previsto_centavos"] is None
    a = r["acumulado"]
    for k in ("medido_centavos", "custo_centavos", "diferenca_centavos", "previsto_centavos"):
        assert a[k] == sum(x[k] or 0 for x in r["linhas"]), k
    assert a["previsto_centavos"] == 50_00 + 1_000_00 + 2_000_01 + 3_00
    assert a["custo_centavos"] == 182_02 and a["medido_centavos"] == 444_44
    assert a["diferenca_centavos"] == 444_44 - 182_02
    for x in r["linhas"]:
        assert sum(g["custo_centavos"] for g in x["grupos"]) == x["custo_centavos"]
        assert sum(g["apontado_centavos"] + g["rateado_centavos"] for g in x["grupos"]) == x["custo_centavos"]


def test_sincronizacao_do_rm_desatualizada(conn):
    cid = _obra(conn)
    assert custo_obra.custo_da_obra(conn, cid)["rm"] == {"sincronizado_em": None, "desatualizado": True}
    conn.execute("INSERT INTO rm_sincronizacoes (disparo, estado, iniciado_em, terminado_em, custo_tarefas) "
                 "VALUES ('agendado','success', datetime('now','-3 days'), datetime('now','-3 days'), 10)")
    conn.commit()
    rm = custo_obra.custo_da_obra(conn, cid)["rm"]
    assert rm["desatualizado"] is True and rm["sincronizado_em"].endswith("+00:00")
    # rodada recente que nao trouxe o custo nao conta
    conn.execute("INSERT INTO rm_sincronizacoes (disparo, estado, terminado_em) VALUES ('agendado','success', datetime('now'))")
    conn.commit()
    assert custo_obra.custo_da_obra(conn, cid)["rm"]["desatualizado"] is True
    conn.execute("INSERT INTO rm_sincronizacoes (disparo, estado, terminado_em, custo_tarefas) "
                 "VALUES ('manual','success', datetime('now','-2 hours'), 3)")
    conn.commit()
    assert custo_obra.custo_da_obra(conn, cid)["rm"]["desatualizado"] is False


def test_regra_sem_tarefa_desconhecida_nao_vira_proporcional_calado(conn):
    cid = _obra(conn)
    conn.execute("UPDATE contratos SET custo_sem_tarefa='fixo' WHERE id=?", (cid,)); conn.commit()
    with pytest.raises(custo_obra.RegraDesconhecida, match="fixo"):
        custo_obra.custo_da_obra(conn, cid)


def test_obra_so_com_cronograma_mostra_o_previsto_ate_o_mes_atual(conn, monkeypatch):
    import datetime
    from app import tempo
    monkeypatch.setattr(tempo, "hoje_local", lambda: datetime.date(2026, 4, 15))
    cid = _obra(conn)
    cronograma.nova_versao(conn, 1, cid, [("2026-03", 10_00), ("2026-04", 20_00), ("2026-05", 30_00)], "manual")
    r = custo_obra.custo_da_obra(conn, cid)
    assert [x["competencia"] for x in r["linhas"]] == ["2026-03", "2026-04"]
    assert r["acumulado"]["previsto_centavos"] == 30_00


def test_centro_em_duas_obras_com_cadastro_recusa_em_vez_de_duplicar(conn):
    alfa = _obra(conn, anteriores=["1.050.003"])
    beta = _obra(conn, centro="2.001.099", nome="Obra Beta", anteriores=["1.050.003"])
    _obra(conn, centro="2.001.012", grupos=None, nome="Sem Cadastro")      # sem cadastro de custo: nao disputa
    _custo(conn, [(1, "1.050.003", P, "001.01", "1.01.003", "2026-03", 100_00)])
    for cid, outra in ((alfa, "Obra Beta"), (beta, "Obra Alfa")):
        with pytest.raises(custo_obra.CentroDisputado, match=f"1.050.003 na obra {outra}"):
            custo_obra.custo_da_obra(conn, cid)
    # em outra coligada o mesmo codigo e' outro centro
    eid = entidades.criar(conn, 1, {"nome": "Construtora Alfa Ltda", "cnpj": "11444777000161", "papel": "lotufo",
                                    "coligada_rm": 5})
    gama = _obra(conn, centro="2.001.012", nome="Obra Gama", entidade_id=eid)
    assert custo_obra.custo_da_obra(conn, gama)["linhas"] == []


def test_le_de_um_retrato_so(conn, monkeypatch):
    """A carga do RM troca custo e estoque numa transacao: a tela le tudo dentro de `db.leitura`."""
    import contextlib
    entradas = []
    original = db.leitura

    @contextlib.contextmanager
    def espiao(c):
        with original(c):
            entradas.append(c.in_transaction)
            yield c

    monkeypatch.setattr(db, "leitura", espiao)
    cid = _obra(conn)
    custo_obra.custo_da_obra(conn, cid)
    assert entradas == [True]


def test_competencia_com_uma_medicao_lida_e_outra_nao_fica_sem_diferenca_por_grupo(conn):
    """Gate Sol, rodada 2: o medido de cada grupo no mes so' e' conhecido com todas as medicoes lidas."""
    cid = _obra(conn)
    m1 = _medicao(conn, cid, 1, "2026-03", 100_00)
    _leitura(conn, cid, m1, {"Terraplenagem": 100_00})
    _medicao(conn, cid, 2, "2026-03", 200_01)
    _custo(conn, [(1, "2.001.012", P, "001.01", "1.01.003", "2026-03", 150_00)])
    mar = _linha(custo_obra.custo_da_obra(conn, cid), "2026-03")
    t = _grupo(mar, "Terraplenagem")
    assert t["medido_centavos"] == 100_00 and t["custo_centavos"] == 150_00 and t["diferenca_centavos"] is None
    assert all(g["diferenca_centavos"] is None for g in mar["grupos"] if g["tipo"] == "grupo")
    assert _grupo(mar, "Medido por grupo não lido")["medido_centavos"] == 200_01
    # o total do mes continua fechando
    assert mar["medido_centavos"] == 300_01 and mar["custo_centavos"] == 150_00 and mar["diferenca_centavos"] == 150_01
    assert sum(g["medido_centavos"] or 0 for g in mar["grupos"]) == mar["medido_centavos"]


# --- issue #492: custo unitario realizado do item-chave ----------------------------------------------------------

def _chave(conn, cid, grupo, codigo, unidade):
    conn.execute("UPDATE custo_grupos SET item_chave_codigo=?, item_chave_unidade=? WHERE contrato_id=? AND nome=?",
                 (codigo, unidade, cid, grupo))
    conn.commit()


def _leitura_itens(conn, cid, mid, itens: dict[str, list[dict]]):
    """Leitura com itens de verdade: {grupo: [{item, quantidade_acumulada, preco_unitario_centavos, valor}]}."""
    cad = medicao_grupos.cadastro_de_custo(conn, cid)
    pedido = conn.execute("SELECT valor_protocolado_centavos FROM medicoes WHERE id=?", (mid,)).fetchone()[0]
    grupos = []
    total = 0
    for g, its in itens.items():
        lista = []
        for it in its:
            lista.append({"item": it["item"], "codigo": None, "descricao": it.get("descricao", "Serviço"),
                          "unidade": it.get("unidade", "m³"), "quantidade_contratada": None,
                          "quantidade_medida": None, "quantidade_acumulada": it["quantidade_acumulada"],
                          "preco_unitario_centavos": it["preco_unitario_centavos"],
                          "valor_medido_centavos": it["valor"], "valor_acumulado_centavos": None})
            total += it["valor"]
        grupos.append({"nome": g, "itens": lista})
    with db.mutacao(conn):
        medicao_grupos._gravar(conn, None, mid, "b" * 64, "carga", None, None, "lida", None,
                               {"grupo_por": "cadastro", "grupos": grupos}, medicao_grupos._assinatura(cad),
                               total, pedido)


def test_custo_unitario_do_item_chave_e_custo_acumulado_sobre_quantidade_acumulada(conn):
    cid = _obra(conn)
    _chave(conn, cid, "Terraplenagem", "1.2", "m³")
    m1 = _medicao(conn, cid, 1, "2026-03", 100_00)
    _leitura_itens(conn, cid, m1, {"Terraplenagem": [
        {"item": "1.1", "quantidade_acumulada": "999", "preco_unitario_centavos": 1, "valor": 40_00},
        {"item": "1.2", "quantidade_acumulada": "1", "preco_unitario_centavos": 9_99, "valor": 60_00}]})
    m2 = _medicao(conn, cid, 2, "2026-04", 200_00)
    # a planilha mais recente: quantidade acumulada 3 e preco novo (aditivo) de 12,35
    _leitura_itens(conn, cid, m2, {"Terraplenagem": [
        {"item": "1.1", "quantidade_acumulada": "999", "preco_unitario_centavos": 1, "valor": 50_00},
        {"item": "1.2", "quantidade_acumulada": "3", "preco_unitario_centavos": 12_35, "valor": 150_00,
         "descricao": "Escavação"}]})
    _custo(conn, [(1, "2.001.012", P, "001.01", "1.01.003", "2026-03", 10_00),
                  (1, "2.001.012", P, "001.01", "1.01.003", "2026-04", 5_00),
                  (1, "2.001.012", P, "001.02", "1.01.003", "2026-04", 1_00),     # Pavimentacao: peso do rateio
                  (1, "2.001.012", None, None, "1.02.001", "2026-04", 6_01)])     # rateado: 5:1
    r = custo_obra.custo_da_obra(conn, cid)
    custo_terra = sum(_grupo(x, "Terraplenagem")["custo_centavos"] for x in r["linhas"])
    assert custo_terra == 10_00 + 5_00 + 5_01           # o rateado 6,01 na proporcao 5:1 -> 5,01 e 1,00
    assert r["itens_chave"] == [{
        "grupo": "Terraplenagem", "item": "1.2", "descricao": "Escavação", "unidade": "m³",
        "quantidade_acumulada": "3", "medicao": "2ª medição", "custo_centavos": 20_01,
        # 20,01 / 3 = 6,67 (6,6700): arredondamento unico, meio para cima
        "custo_unitario_centavos": 6_67, "preco_unitario_centavos": 12_35, "diferenca_centavos": 12_35 - 6_67,
        "situacao": "ok"}]


def test_custo_unitario_arredonda_uma_vez_meio_para_cima(conn):
    cid = _obra(conn)
    _chave(conn, cid, "Terraplenagem", "1.2", "t·km")
    m1 = _medicao(conn, cid, 1, "2026-03", 100_00)
    _leitura_itens(conn, cid, m1, {"Terraplenagem": [
        {"item": "1.2", "quantidade_acumulada": "0.4", "preco_unitario_centavos": 3_00, "valor": 100_00}]})
    _custo(conn, [(1, "2.001.012", P, "001.01", "1.01.003", "2026-03", 1)])    # 0,01 / 0,4 = 0,025 -> 0,03
    k = custo_obra.custo_da_obra(conn, cid)["itens_chave"][0]
    assert k["custo_unitario_centavos"] == 3 and k["diferenca_centavos"] == 2_97
    assert k["unidade"] == "t·km"


def test_item_chave_sem_medicao_e_sem_custo(conn):
    cid = _obra(conn)
    _chave(conn, cid, "Terraplenagem", "1.2", "m³")
    _chave(conn, cid, "Pavimentação", "2.1", "m³")
    _custo(conn, [(1, "2.001.012", P, "001.01", "1.01.003", "2026-03", 10_00)])
    r = custo_obra.custo_da_obra(conn, cid)
    # nenhuma planilha lida: sem medicao nos dois
    assert [(k["grupo"], k["situacao"]) for k in r["itens_chave"]] == [("Terraplenagem", "sem_medicao"),
                                                                       ("Pavimentação", "sem_medicao")]
    assert all(k["custo_unitario_centavos"] is None and k["diferenca_centavos"] is None for k in r["itens_chave"])
    m1 = _medicao(conn, cid, 1, "2026-03", 100_00)
    _leitura_itens(conn, cid, m1, {
        "Terraplenagem": [{"item": "1.2", "quantidade_acumulada": "0", "preco_unitario_centavos": 5_00, "valor": 0}],
        "Pavimentação": [{"item": "2.1", "quantidade_acumulada": "4", "preco_unitario_centavos": 7_00,
                          "valor": 100_00}]})
    t, p = custo_obra.custo_da_obra(conn, cid)["itens_chave"]
    # quantidade zero vira "sem medição", com o preco do contrato ainda a' mostra
    assert t["situacao"] == "sem_medicao" and t["custo_unitario_centavos"] is None
    assert t["preco_unitario_centavos"] == 5_00 and t["quantidade_acumulada"] == "0"
    # medido, mas sem custo no grupo: "sem custo lançado", sem custo unitario nem diferenca
    assert p["situacao"] == "sem_custo" and p["custo_centavos"] == 0
    assert p["custo_unitario_centavos"] is None and p["diferenca_centavos"] is None
    assert p["quantidade_acumulada"] == "4" and p["preco_unitario_centavos"] == 7_00


def _sem_medicao(k):
    assert k["situacao"] == "sem_medicao"
    assert all(k[c] is None for c in ("quantidade_acumulada", "preco_unitario_centavos", "custo_unitario_centavos",
                                      "diferenca_centavos", "medicao"))


def test_item_chave_so_no_grupo_dele_e_comparado_por_segmento(conn):
    """/code-review: o mesmo nº em outro grupo nao vale; "1.2." e "1.2" sao o mesmo item."""
    cid = _obra(conn)
    _chave(conn, cid, "Terraplenagem", "1.2", "m³")
    m1 = _medicao(conn, cid, 1, "2026-03", 100_00)
    _leitura_itens(conn, cid, m1, {"Terraplenagem": [
        {"item": "1.2.", "quantidade_acumulada": "4", "preco_unitario_centavos": 8_00, "valor": 90_00}],
        "Pavimentação": [{"item": "1.2", "quantidade_acumulada": "999", "preco_unitario_centavos": 1, "valor": 10_00}]})
    _custo(conn, [(1, "2.001.012", P, "001.01", "1.01.003", "2026-03", 10_00)])
    k = custo_obra.custo_da_obra(conn, cid)["itens_chave"][0]
    assert (k["quantidade_acumulada"], k["preco_unitario_centavos"], k["medicao"]) == ("4", 8_00, "1ª medição")
    assert k["custo_unitario_centavos"] == 2_50 and k["situacao"] == "ok"


def test_planilha_mais_recente_sem_o_item_vira_sem_medicao(conn):
    """Gate Sol (#492): a quantidade antiga contra o custo acumulado de agora nao vale."""
    cid = _obra(conn)
    _chave(conn, cid, "Terraplenagem", "1.2", "m³")
    m1 = _medicao(conn, cid, 1, "2026-03", 100_00)
    _leitura_itens(conn, cid, m1, {"Terraplenagem": [
        {"item": "1.2", "quantidade_acumulada": "4", "preco_unitario_centavos": 8_00, "valor": 100_00}]})
    m2 = _medicao(conn, cid, 2, "2026-04", 50_00)
    _leitura_itens(conn, cid, m2, {"Terraplenagem": [
        {"item": "1.1", "quantidade_acumulada": "7", "preco_unitario_centavos": 1_00, "valor": 50_00}]})
    _custo(conn, [(1, "2.001.012", P, "001.01", "1.01.003", "2026-04", 10_00)])
    _sem_medicao(custo_obra.custo_da_obra(conn, cid)["itens_chave"][0])


def test_medicao_mais_recente_sem_leitura_vira_sem_medicao(conn):
    cid = _obra(conn)
    _chave(conn, cid, "Terraplenagem", "1.2", "m³")
    m1 = _medicao(conn, cid, 1, "2026-03", 100_00)
    _leitura_itens(conn, cid, m1, {"Terraplenagem": [
        {"item": "1.2", "quantidade_acumulada": "4", "preco_unitario_centavos": 8_00, "valor": 100_00}]})
    _medicao(conn, cid, 2, "2026-04", 50_00)                          # sem planilha lida
    _custo(conn, [(1, "2.001.012", P, "001.01", "1.01.003", "2026-04", 10_00)])
    _sem_medicao(custo_obra.custo_da_obra(conn, cid)["itens_chave"][0])


def test_custo_acumulado_negativo_do_grupo_nao_vira_custo_unitario(conn):
    cid = _obra(conn)
    _chave(conn, cid, "Terraplenagem", "1.2", "m³")
    m1 = _medicao(conn, cid, 1, "2026-03", 100_00)
    _leitura_itens(conn, cid, m1, {"Terraplenagem": [
        {"item": "1.2", "quantidade_acumulada": "4", "preco_unitario_centavos": 8_00, "valor": 100_00}]})
    _custo(conn, [(1, "2.001.012", P, "001.01", "1.01.003", "2026-03", -10_01)])     # estorno
    k = custo_obra.custo_da_obra(conn, cid)["itens_chave"][0]
    assert k["situacao"] == "sem_custo" and k["custo_centavos"] == -10_01
    assert k["custo_unitario_centavos"] is None and k["diferenca_centavos"] is None


def test_grupo_sem_item_chave_fica_fora_do_bloco(conn):
    cid = _obra(conn)
    assert custo_obra.custo_da_obra(conn, cid)["itens_chave"] == []
    _chave(conn, cid, "Pavimentação", "2.1", "m³")
    assert [k["grupo"] for k in custo_obra.custo_da_obra(conn, cid)["itens_chave"]] == ["Pavimentação"]
