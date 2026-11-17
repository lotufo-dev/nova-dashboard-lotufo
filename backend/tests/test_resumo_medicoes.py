"""Pagina Resumo das medicoes (issue #749): a etapa do ciclo da medicao de cada obra na competencia, as obras sem
medicao no mes e as medicoes abertas de meses anteriores. Dados sinteticos, com os nomes do `cadastro-exemplo/`."""
import datetime

import pytest

from app import auditoria, auth, db, fechamento, medicoes, resumo_medicoes
from tests.conftest import novo_contrato

HOJE = datetime.date(2026, 11, 16)
MES = "2026-10"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn()
    db.migrate(c)
    yield c
    c.close()


def _orgao(c, chave, nome, familia):
    return c.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES (?,?,?,'{}')", (chave, nome, familia)).lastrowid


def _obra(c, nome, orgao_id, estado="ativo", pct=10000, passos=None):
    return c.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos, estado, nome_curto, "
                     "orgao_id, percentual_direito_bp, passos_medicao) VALUES ('ÓRGÃO',?,?,0,?,?,?,?,?)",
                     (f"IC {nome}", nome, estado, nome, orgao_id, pct, passos)).lastrowid


def _medicao(c, cid, numero, estado, pedido=None, tipo="execucao", comp=MES, protocolo=None, **campos):
    cols = ["contrato_id", "numero", "tipo", "competencia", "estado", "valor_protocolado_centavos", *campos]
    vals = [cid, numero, tipo, comp, estado, pedido, *campos.values()]
    mid = c.execute(f"INSERT INTO medicoes ({', '.join(cols)}) VALUES ({','.join('?' * len(vals))})", vals).lastrowid
    for dia in protocolo or ():
        c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, ?, 'manual')", (mid, dia))
    return mid


@pytest.fixture
def cenario(conn):
    c = conn
    # familia sinfra, como no cadastro de exemplo: e' a que tem planilha/carta, e a sigla do grupo sai da familia
    secretaria = _orgao(c, "secretaria-exemplo", "Secretaria de Exemplo", "sinfra")
    companhia = _orgao(c, "companhia-exemplo", "Companhia de Exemplo", "mtpar")       # familia sem planilha/carta
    ids = {
        "propria": _obra(c, "Obra Própria", secretaria),
        "consorcio": _obra(c, "Obra Consórcio", secretaria, pct=3333),
        "companhia": _obra(c, "Obra da Companhia", companhia),
        "sem_envio": _obra(c, "Obra Sem Envio", secretaria, passos='["planilha","analise","espelhos","notas","pagamento"]'),
        "parada": _obra(c, "Obra Parada", secretaria),
        "sem_fluxo": _obra(c, "Obra Sem Fluxo", secretaria, passos="[]"),
        "suspensa": _obra(c, "Obra Suspensa", secretaria, estado="suspenso"),
    }
    # Propria: a execucao protocolada, com todas as datas; o protocolo reapresentado nao muda a data (vale o primeiro)
    ids["p12"] = _medicao(c, ids["propria"], 12, "protocolada", 100_001, planilha_enviada_em="2026-11-03",
                          atestado_em="2026-11-06", valor_atestado_centavos=99_999, nota_emitida_em="2026-11-09",
                          protocolo=("2026-11-10", "2026-11-13"))
    # Consorcio (cota de 33,33%): em analise, so' o pedido; centavo impar
    ids["k7"] = _medicao(c, ids["consorcio"], 7, "planilha_enviada", 1_000_001, planilha_enviada_em="2026-11-05")
    # Companhia: sem planilha/carta, a medicao nasce no espelho
    ids["c3"] = _medicao(c, ids["companhia"], 3, "espelho_gerado", 50_000)
    # Sem Envio: a obra nao tem o passo "Envio da nota"; a nota emitida espera o pagamento
    ids["s4"] = _medicao(c, ids["sem_envio"], 4, "nota_emitida", 70_000, planilha_enviada_em="2026-11-02",
                         atestado_em="2026-11-04", valor_atestado_centavos=70_000, nota_emitida_em="2026-11-08")
    # Parada: so' a prevista do mes (nao conta) e a 5ª, de setembro, ainda protocolada
    _medicao(c, ids["parada"], 6, "prevista")
    ids["x5"] = _medicao(c, ids["parada"], 5, "protocolada", 20_000, comp="2026-09", protocolo=("2026-10-20",))
    # meses anteriores: uma recebida (fora), uma cancelada (fora) e uma em analise de agosto
    _medicao(c, ids["propria"], 11, "recebida", 5_000, comp="2026-09", recebida_em="2026-10-30")
    _medicao(c, ids["propria"], 10, "cancelada", 5_000, comp="2026-08")
    ids["k5"] = _medicao(c, ids["consorcio"], 5, "planilha_enviada", 3_000, comp="2026-08", planilha_enviada_em="2026-09-04")
    c.commit()
    return ids


def _linha(r, obra):
    return next(x for g in r["grupos"] for x in g["linhas"] if x["obra"] == obra)


def _etapas(linha):
    return [(e["etapa"], e["situacao"], e["data"]) for e in linha["etapas"]]


def test_competencia_padrao_e_a_em_trabalho(conn, cenario):
    r = resumo_medicoes.resumo(conn, HOJE)
    assert (r["mes"], r["em_trabalho"], r["hoje"]) == ("2026-10", "2026-10", "2026-11-16")
    assert resumo_medicoes.resumo(conn, HOJE, mes="2026-09")["em_trabalho"] == "2026-10"


def test_linha_por_obra_agrupada_por_contratante_com_as_datas_registradas(conn, cenario):
    ids = cenario
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    assert [(g["contratante"], [x["obra"] for x in g["linhas"]]) for g in r["grupos"]] == [
        ("Companhia de Exemplo", ["Obra da Companhia"]),
        ("SINFRA", ["Obra Consórcio", "Obra Própria", "Obra Sem Envio"])]
    p = _linha(r, "Obra Própria")
    assert (p["medicao_id"], p["titulo"], p["etapa"], p["competencia"]) == (ids["p12"], "12ª Medição", "protocolado", MES)
    # cada etapa alcancada com a data do evento; a do protocolo e' a do PRIMEIRO; a que falta vem sem data
    assert _etapas(p) == [("em_analise", "feito", "2026-11-03"), ("boletim", "feito", "2026-11-06"),
                          ("nota", "feito", "2026-11-09"), ("protocolado", "atual", "2026-11-10"), ("recebido", "futuro", None)]
    assert p["valor_centavos"] == 99_999        # o medido: o aprovado e, sem boletim, o pedido


def test_valor_na_cota_com_arredondamento_unico(conn, cenario):
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    k = _linha(r, "Obra Consórcio")
    # 1.000.001 centavos x 33,33% = 333.300,3333: arredonda uma vez, para 333.300
    assert k["valor_centavos"] == 333_300 and k["etapa"] == "em_analise"
    assert _etapas(k)[0] == ("em_analise", "atual", "2026-11-05")
    assert {e["situacao"] for e in k["etapas"][1:]} == {"futuro"}


def test_obra_so_tem_as_etapas_do_fluxo_dela(conn, cenario):
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    # familia sem planilha/carta: nao existe "em analise"; a medicao no espelho esta' na etapa do boletim, sem data
    c = _linha(r, "Obra da Companhia")
    assert _etapas(c) == [("boletim", "atual", None), ("nota", "futuro", None), ("protocolado", "futuro", None),
                          ("recebido", "futuro", None)]
    # `passos_medicao` sem o envio da nota: nao existe "protocolado"; a nota emitida fica na etapa da nota
    s = _linha(r, "Obra Sem Envio")
    assert [e["etapa"] for e in s["etapas"]] == ["em_analise", "boletim", "nota", "recebido"]
    assert s["etapa"] == "nota" and _etapas(s)[2] == ("nota", "atual", "2026-11-08")
    assert resumo_medicoes.etapas_do_fluxo((1, 2, 3, 4, 5, 6)) == resumo_medicoes.ETAPAS


def test_etapa_da_vez_por_estado():
    cheio, sem_planilha = (1, 2, 3, 4, 5, 6), (3, 4, 5, 6)
    da_vez = resumo_medicoes.etapa_da_vez
    assert [da_vez(e, cheio) for e in ("planilha_gerada", "planilha_enviada", "boletim_recebido", "espelho_gerado",
                                       "espelho_enviado", "nota_emitida", "protocolada", "nf_emitida", "recebida")] == [
        "antes", "em_analise", "boletim", "boletim", "boletim", "nota", "protocolado", "protocolado", "recebido"]
    assert da_vez("espelho_gerado", sem_planilha) == "boletim"
    assert da_vez("nota_emitida", (1, 2, 3, 4, 6)) == "nota" and da_vez("protocolada", (1, 2, 3, 4, 6)) == "nota"
    assert da_vez("cancelada", cheio) is None and da_vez("desistida", cheio) is None


def test_planilha_gerada_ainda_nao_entrou_no_ciclo(conn, cenario):
    c, ids = conn, cenario
    _medicao(c, ids["parada"], 7, "planilha_gerada", 9_000)
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    x = _linha(r, "Obra Parada")
    assert x["etapa"] == "antes" and {e["situacao"] for e in x["etapas"]} == {"futuro"}
    assert all(e["data"] is None for e in x["etapas"])
    assert "Obra Parada" not in [o["obra"] for o in r["sem_medicao"]]
    # a medicao ainda nao enviada ao orgao nao mede (`medicoes.ESTADOS_NO_MEDIDO`): a linha existe, sem valor
    assert x["valor_centavos"] is None
    assert next(e for e in r["etapas"] if e["etapa"] == "antes") == {"etapa": "antes", "medicoes": 1, "valor_centavos": 0}


def test_medido_do_mes_fecha_com_o_do_fechamento(conn, cenario):
    """A soma do medido das linhas da competencia e' o medido do mes no Fechamento: a mesma regra (a medicao enviada
    ao orgao, o aprovado e, sem boletim, o pedido, na cota), com a planilha/carta so' gerada fora das duas."""
    c, ids = conn, cenario
    _medicao(c, ids["parada"], 7, "planilha_gerada", 9_001)
    _medicao(c, ids["consorcio"], 7, "planilha_enviada", 500_001, tipo="reajuste")       # reajuste: linha e valor proprios
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    soma = sum(x["valor_centavos"] or 0 for g in r["grupos"] for x in g["linhas"])
    [mes] = [m for m in fechamento.fechamento(conn)["meses"] if m["competencia"] == MES]
    # consorcio a 33,33%: 333.300 da execucao + 166.650 do reajuste (500.001 x 33,33% = 166.650,33), cada um com o
    # arredondamento dele
    assert soma == mes["medido_centavos"] == 99_999 + 333_300 + 166_650 + 50_000 + 70_000
    assert sum(e["valor_centavos"] for e in r["etapas"]) == soma


def test_medicao_de_projeto_tem_linha_valor_e_conta_como_ultima(conn, cenario):
    """#742: a medicao de projeto entra no medido. Aqui ela tem a linha e o valor dela e, na obra sem medicao no mes,
    e' a ultima medicao."""
    c, ids = conn, cenario
    proj = _medicao(c, ids["propria"], 1, "planilha_enviada", 40_001, tipo="projeto", planilha_enviada_em="2026-11-04")
    antigo = _medicao(c, ids["parada"], 2, "recebida", 10_000, tipo="projeto", comp="2026-09", recebida_em="2026-10-28")
    c.execute("UPDATE medicoes SET estado='recebida', recebida_em='2026-10-27' WHERE id=?", (ids["x5"],))
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    linhas = [x for g in r["grupos"] for x in g["linhas"] if x["obra"] == "Obra Própria"]
    assert [(x["medicao_id"], x["tipo"], x["etapa"], x["valor_centavos"]) for x in linhas] == [
        (ids["p12"], "execucao", "protocolado", 99_999), (proj, "projeto", "em_analise", 40_001)]
    assert next(e for e in r["etapas"] if e["etapa"] == "em_analise") == {
        "etapa": "em_analise", "medicoes": 2, "valor_centavos": 333_300 + 40_001}
    # execucao e projeto na mesma competencia: a de maior numero e' a ultima (a 5ª), seja qual for o tipo
    [parada] = r["sem_medicao"]
    assert parada["ultima"]["medicao_id"] == ids["x5"]
    c.execute("UPDATE medicoes SET competencia='2026-08' WHERE id=?", (ids["x5"],))
    c.commit()
    [parada] = resumo_medicoes.resumo(conn, HOJE, mes=MES)["sem_medicao"]
    assert parada["ultima"] == {"medicao_id": antigo, "titulo": medicoes.titulo({"numero": 2, "tipo": "projeto"}),
                                "competencia": "2026-09", "etapa": "recebido"}


def test_obra_sem_envio_da_nota_vai_da_nota_ao_recebido_pela_baixa(conn, cenario):
    """#743: na obra sem o passo "Envio da nota", a medicao com nota emitida e' recebida sem protocolo. Na pagina ela
    sai da etapa da nota para a do recebido, sem a etapa do protocolado, e deixa os meses anteriores em aberto."""
    c, ids = conn, cenario
    uid = auth.criar_usuario(c, "Administrador Exemplo", "admin@exemplo.com.br", "senha-forte-123", "admin")
    antiga = _medicao(c, ids["sem_envio"], 3, "nota_emitida", 60_001, comp="2026-09", nota_emitida_em="2026-10-06")
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    [aberta] = [x for g in r["anteriores"] for x in g["linhas"] if x["medicao_id"] == antiga]
    assert _etapas(aberta) == [("boletim", "feito", None), ("nota", "atual", "2026-10-06"), ("recebido", "futuro", None)]
    for mid, dia in ((ids["s4"], "2026-11-13"), (antiga, "2026-11-12")):
        assert "recebida" in medicoes.alcancaveis(c, medicoes.detalhe(c, mid))
        medicoes.mudar_estado(c, uid, mid, "recebida", "baixa conferida no extrato", dia, origem="manual")
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    s = _linha(r, "Obra Sem Envio")
    assert s["etapa"] == "recebido" and _etapas(s) == [
        ("em_analise", "feito", "2026-11-02"), ("boletim", "feito", "2026-11-04"), ("nota", "feito", "2026-11-08"),
        ("recebido", "feito", "2026-11-13")]
    assert antiga not in [x["medicao_id"] for g in r["anteriores"] for x in g["linhas"]]
    assert next(e for e in r["etapas"] if e["etapa"] == "recebido") == {"etapa": "recebido", "medicoes": 1, "valor_centavos": 70_000}
    # na obra com o passo, a nota emitida continua sem caminho para recebida: fica na etapa da nota ate' o protocolo
    outra = _medicao(c, ids["propria"], 13, "nota_emitida", 30_000, nota_emitida_em="2026-11-12")
    c.commit()
    assert "recebida" not in medicoes.alcancaveis(c, medicoes.detalhe(c, outra))


def test_recebida_tem_todas_as_etapas_feitas(conn, cenario):
    c, ids = conn, cenario
    c.execute("UPDATE medicoes SET estado='recebida', recebida_em='2026-11-14' WHERE id=?", (ids["p12"],))
    c.commit()
    p = _linha(resumo_medicoes.resumo(conn, HOJE, mes=MES), "Obra Própria")
    assert p["etapa"] == "recebido" and {e["situacao"] for e in p["etapas"]} == {"feito"}
    assert _etapas(p)[-1] == ("recebido", "feito", "2026-11-14")


def test_execucao_e_reajuste_na_mesma_etapa_sao_uma_linha_e_em_etapas_diferentes_sao_duas(conn, cenario):
    c, ids = conn, cenario
    r12 = _medicao(c, ids["propria"], 12, "protocolada", 1_001, tipo="reajuste", nota_emitida_em="2026-11-11",
                   protocolo=("2026-11-12",))
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    p = _linha(r, "Obra Própria")
    assert p["titulo"] == "12ª Medição + Reajuste" and p["medicao_ids"] == [ids["p12"], r12]
    assert p["valor_centavos"] == 99_999 + 1_001
    # a data de cada etapa e' a da ultima das duas a chegar nela
    assert _etapas(p)[2:4] == [("nota", "feito", "2026-11-11"), ("protocolado", "atual", "2026-11-12")]
    assert next(e for e in r["etapas"] if e["etapa"] == "protocolado")["medicoes"] == 2
    c.execute("UPDATE medicoes SET estado='nota_emitida' WHERE id=?", (r12,))
    c.commit()
    linhas = [x for g in resumo_medicoes.resumo(conn, HOJE, mes=MES)["grupos"] for x in g["linhas"] if x["obra"] == "Obra Própria"]
    assert [(x["titulo"], x["etapa"]) for x in linhas] == [("12ª Medição", "protocolado"), ("Reajuste da 12ª Medição", "nota")]


def test_contagem_por_etapa_soma_as_linhas(conn, cenario):
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    assert [(e["etapa"], e["medicoes"], e["valor_centavos"]) for e in r["etapas"]] == [
        ("antes", 0, 0), ("em_analise", 1, 333_300), ("boletim", 1, 50_000), ("nota", 1, 70_000),
        ("protocolado", 1, 99_999), ("recebido", 0, 0)]
    linhas = [x for g in r["grupos"] for x in g["linhas"]]
    assert sum(e["valor_centavos"] for e in r["etapas"]) == sum(x["valor_centavos"] for x in linhas)
    assert sum(e["medicoes"] for e in r["etapas"]) == sum(len(x["medicao_ids"]) for x in linhas)


def test_obras_sem_medicao_no_mes(conn, cenario):
    ids = cenario
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    # so' a prevista nao conta; a suspensa e a sem fluxo de medicao no cadastro ficam fora
    assert r["sem_medicao"] == [{"contrato_id": ids["parada"], "obra": "Obra Parada", "contratante": "SINFRA",
                                 "ultima": {"medicao_id": ids["x5"], "titulo": "5ª Medição", "competencia": "2026-09",
                                            "etapa": "protocolado"}}]
    # em encerramento e sem medicao na competencia: fora
    conn.execute("UPDATE contratos SET encerramento_iniciado_em='2026-11-01' WHERE id=?", (ids["parada"],))
    conn.commit()
    assert resumo_medicoes.resumo(conn, HOJE, mes=MES)["sem_medicao"] == []
    # mes sem medicao nenhuma: todas as ativas com fluxo, e a obra nunca medida vem sem "ultima"
    futuro = resumo_medicoes.resumo(conn, HOJE, mes="2027-01")
    assert futuro["grupos"] == [] and [o["obra"] for o in futuro["sem_medicao"]] == [
        "Obra Consórcio", "Obra da Companhia", "Obra Própria", "Obra Sem Envio"]
    _obra(conn, "Obra Nova", None)
    conn.commit()
    nova = next(o for o in resumo_medicoes.resumo(conn, HOJE, mes=MES)["sem_medicao"] if o["obra"] == "Obra Nova")
    assert nova["ultima"] is None and nova["contratante"] == "ÓRGÃO"      # sem orgao no cadastro: o texto do contrato


def test_meses_anteriores_em_aberto(conn, cenario):
    ids = cenario
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    # da competencia mais antiga para a mais nova; a recebida e a cancelada nao entram
    assert [(g["competencia"], [(x["obra"], x["medicao_id"], x["etapa"]) for x in g["linhas"]]) for g in r["anteriores"]] == [
        ("2026-08", [("Obra Consórcio", ids["k5"], "em_analise")]),
        ("2026-09", [("Obra Parada", ids["x5"], "protocolado")])]
    x5 = r["anteriores"][1]["linhas"][0]
    assert _etapas(x5)[-2] == ("protocolado", "atual", "2026-10-20") and x5["valor_centavos"] == 20_000
    # olhando setembro, a de setembro e' do mes e so' a de agosto e' anterior
    setembro = resumo_medicoes.resumo(conn, HOJE, mes="2026-09")
    assert [g["competencia"] for g in setembro["anteriores"]] == ["2026-08"]
    assert _linha(setembro, "Obra Parada")["medicao_id"] == ids["x5"]


def test_atualizacao_e_o_ultimo_lancamento_de_uma_pessoa_e_a_ultima_leitura_do_rm(conn, cenario):
    c, ids = conn, cenario
    assert resumo_medicoes.resumo(conn, HOJE, mes=MES)["atualizacao"] == {"ultimo_lancamento": None, "rm_lido_em": None}
    uid = auth.criar_usuario(c, "Engenharia Exemplo", "engenharia@exemplo.com.br", "senha-forte-123", "engenharia")
    with db.mutacao(c):
        auditoria.registrar(c, uid, "medicao.estado", "medicao", ids["p12"])
        auditoria.registrar(c, None, "medicao.estado", "medicao", ids["k7"])      # pelo sistema: nao e' lancamento
    c.execute("UPDATE audit_log SET criado_em='2026-11-14 18:40:00' WHERE usuario_id IS NOT NULL AND entidade='medicao'")
    c.execute("UPDATE audit_log SET criado_em='2026-11-15 09:00:00' WHERE usuario_id IS NULL AND entidade='medicao'")
    c.execute("INSERT INTO rm_sincronizacoes (disparo, estado, terminado_em) VALUES ('agendado','success','2026-11-16 11:00:00')")
    c.execute("INSERT INTO rm_sincronizacoes (disparo, estado, terminado_em) VALUES ('agendado','failed','2026-11-16 12:00:00')")
    c.commit()
    assert resumo_medicoes.resumo(conn, HOJE, mes=MES)["atualizacao"] == {
        "ultimo_lancamento": "2026-11-14 18:40:00", "rm_lido_em": "2026-11-16 11:00:00"}


# --- rotas ---------------------------------------------------------------------------------------------------

@pytest.fixture
def _sem_certidoes(sem_certidoes_exigidas):
    """As rotas abaixo nao sao sobre certidoes (ver conftest)."""


def test_rota_e_exportacao_da_relacao(client_admin, _sem_certidoes):
    cid = novo_contrato({"orgao": "Secretaria de Exemplo", "numero_instrumento": "IC 1/2026", "objeto": "=Obra Própria",
                         "valor_original": "100.000,00"})
    outra = novo_contrato({"orgao": "Secretaria de Exemplo", "numero_instrumento": "IC 2/2026", "objeto": "Obra Consórcio",
                           "valor_original": "100.000,00"})
    c = db.get_conn()
    c.execute("UPDATE contratos SET nome_curto=objeto")
    mid = _medicao(c, cid, 3, "nota_emitida", 150_001, nota_emitida_em="2026-11-09")
    c.commit()
    c.close()
    r = client_admin.get(f"/api/resumo-medicoes?mes={MES}")
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"hoje", "mes", "em_trabalho", "atualizacao", "etapas", "grupos", "sem_medicao", "anteriores"}
    [linha] = [x for g in d["grupos"] for x in g["linhas"]]
    assert (linha["medicao_id"], linha["etapa"], linha["valor_centavos"]) == (mid, "nota", 150_001)
    assert [o["contrato_id"] for o in d["sem_medicao"]] == [outra]
    assert client_admin.get("/api/resumo-medicoes").json()["mes"] == d["em_trabalho"]
    assert client_admin.get("/api/resumo-medicoes?mes=2026-13").status_code == 422

    x = client_admin.get(f"/api/resumo-medicoes.csv?mes={MES}")
    assert x.status_code == 200 and x.headers["content-type"].startswith("text/csv")
    assert f'filename="resumo-das-medicoes-{MES}.csv"' in x.headers["content-disposition"]
    texto = x.content.decode("utf-8-sig").split("\r\n")
    assert texto[0] == "parte;contratante;obra;medicao;competencia;etapa;data_em_analise;data_boletim;data_nota;data_protocolado;data_recebido;valor_cota"
    # o nome que comeca com "=" sai neutralizado (formula em planilha); a data no formato da tela; o valor em reais
    assert texto[1] == "competência;Secretaria de Exemplo;'=Obra Própria;3ª Medição;10/2026;Nota;;;09/11/2026;;;R$ 1.500,01"
    assert texto[2] == "sem medição no mês;Secretaria de Exemplo;Obra Consórcio;;10/2026;;;;;;;"


def test_rota_exige_login(client):
    assert client.get("/api/resumo-medicoes").status_code == 401
    assert client.get("/api/resumo-medicoes.csv").status_code == 401
