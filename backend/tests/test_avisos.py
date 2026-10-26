"""Registro unico de avisos (spec §11) e resumo do mes da tela inicial (§10.1)."""
import datetime
import json

import pytest

from app import auth, avisos, db, paineis, tempo

D = datetime.date


@pytest.fixture
def cenario(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(tempo, "hoje_local", lambda: D(2026, 9, 20))
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "admin")
    c.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('sinfra-x', 'SINFRA X', 'sinfra', ?)",
              (json.dumps({"vigencia_automatica": True, "documentos_medicao": [], "documentos_reajuste": []}),))
    c.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('mtpar', 'MTPAR', 'mtpar', ?)",
              (json.dumps({"vigencia_automatica": False, "documentos_medicao": [], "documentos_reajuste": []}),))
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos, "
              "orgao_id, execucao_fim, vigencia_fim) VALUES ('SINFRA', 'IC 1/2026', 'Obra A', 'obra', 100, "
              "(SELECT id FROM orgaos WHERE chave='sinfra-x'), '2026-10-20', '2026-10-30')")
    cid = c.execute("SELECT MAX(id) FROM contratos").fetchone()[0]
    for numero, valor in ((1, 1_000_000), (2, 500_000)):
        c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
                  "VALUES (?, ?, 'execucao', '2026-08', 'protocolada', ?)", (cid, numero, valor))
    m1, m2 = [r[0] for r in c.execute("SELECT id FROM medicoes ORDER BY id")]
    c.executemany("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, ?, 'manual')",
                  [(m1, "2026-09-08"), (m1, "2026-09-15"), (m2, "2026-07-30")])
    c.commit()
    yield c, {"contrato": cid}
    c.close()


def test_aviso_de_execucao_nivel_por_dias(cenario):
    c, ids = cenario                          # contrato ativo, execucao termina em 2026-10-20
    tipos = {a["tipo"]: a for a in avisos.listar(c, D(2026, 9, 1))}
    assert tipos["execucao_vencendo"]["nivel"] == "atencao" and tipos["execucao_vencendo"]["dias"] == 49
    assert {a["tipo"]: a for a in avisos.listar(c, D(2026, 10, 1))}["execucao_vencendo"]["nivel"] == "critico"
    assert "execucao_vencendo" not in {a["tipo"] for a in avisos.listar(c, D(2026, 7, 1))}


def test_vigencia_so_em_orgao_sem_prorrogacao_automatica(cenario):
    c, ids = cenario                          # orgao SINFRA (vigencia_automatica: true), vigencia 2026-10-30
    assert "vigencia_vencendo" not in {a["tipo"] for a in avisos.listar(c, D(2026, 10, 1))}
    c.execute("UPDATE contratos SET orgao_id=(SELECT id FROM orgaos WHERE chave='mtpar')"); c.commit()
    assert "vigencia_vencendo" in {a["tipo"] for a in avisos.listar(c, D(2026, 10, 1))}


def test_contrato_em_encerramento_nao_tem_aviso_de_prazo(cenario):
    c, ids = cenario
    c.execute("UPDATE contratos SET encerramento_iniciado_em='2026-09-01' WHERE id=?", (ids["contrato"],)); c.commit()
    assert not [a for a in avisos.listar(c, D(2026, 10, 1)) if a["tipo"].startswith("execucao")]


def test_formato_ordem_e_publico(cenario):
    c, ids = cenario
    lista = avisos.listar(c, D(2026, 11, 1))
    assert lista[0]["tipo"] == "instrumento_pendente" and lista[0]["dias"] == -12   # bloco 7: vencida sem pedido
    assert "execução vencida há 12 dias, sem pedido de prorrogação" in lista[0]["mensagem"]
    for a in lista:
        assert set(a) >= {"tipo", "nivel", "publico", "contrato_id", "obra", "dias", "valor_centavos",
                          "mensagem", "destino"}
        assert a["nivel"] in avisos.NIVEIS and "operacao" in a["publico"]
    assert avisos.listar(c, D(2026, 10, 1), publico="diretoria") == [
        a for a in avisos.listar(c, D(2026, 10, 1), publico="todos") if "diretoria" in a["publico"]]


def test_avisos_antigos_sairam(cenario):
    c, ids = cenario
    c.execute("UPDATE contratos SET data_base='2025-09-01'"); c.commit()
    tipos = {a["tipo"] for a in paineis.alertas(c, hoje="2026-11-01")}
    assert not tipos & {"reajuste_sem_par", "data_base", "medicao_sem_protocolo", "vigencia_vencida",
                        "execucao_vencida"}


def test_resumo_do_mes_conta_primeiro_protocolo(cenario):
    c, ids = cenario                          # a 1a protocolada em 08/09 e reprotocolada em 15/09; a 2a em 30/07
    r = avisos.resumo_mes(c, D(2026, 9, 20))
    assert (r["obras_protocoladas"], r["obras_ativas"]) == (1, 1)
    assert r["valor_mes_centavos"] == 1_000_000 and r["valor_mes_anterior_centavos"] == 0
    assert avisos.resumo_mes(c, D(2026, 8, 5))["valor_mes_anterior_centavos"] == 500_000


def test_resumo_do_mes_diz_quais_obras_faltam(cenario):
    c, ids = cenario                          # A1: a lista, para cobrar as que faltam
    obra = {"contrato_id": ids["contrato"], "obra": "Obra A"}
    r = avisos.resumo_mes(c, D(2026, 9, 20))
    assert (r["protocoladas"], r["faltam"]) == ([obra], [])
    r = avisos.resumo_mes(c, D(2026, 10, 2))
    assert (r["protocoladas"], r["faltam"]) == ([], [obra])


def test_aviso_diz_a_data_do_fato_e_o_que_os_dias_contam(cenario):
    c, ids = cenario                          # A8: prazo (dias ate' a data) e desde (dias desde a data)
    execucao = {a["tipo"]: a for a in avisos.listar(c, D(2026, 9, 1))}["execucao_vencendo"]
    assert (execucao["data"], execucao["sentido"], execucao["dias"]) == ("2026-10-20", "prazo", 49)
    c.execute("UPDATE contratos SET encerramento_iniciado_em='2026-09-01' WHERE id=?", (ids["contrato"],)); c.commit()
    conclusao = {a["tipo"]: a for a in avisos.listar(c, D(2026, 10, 1))}["conclusao_nao_comunicada"]
    assert (conclusao["data"], conclusao["sentido"], conclusao["dias"]) == ("2026-09-01", "desde", 30)


def test_aviso_de_nota_leva_a_medicao(cenario, monkeypatch):
    c, ids = cenario                          # A2: o aviso de nota diz de que medicao e' a nota
    monkeypatch.setattr(avisos.notas, "avisos", lambda conn, hoje: [
        {"tipo": "nota_ausente_rm", "nota_id": 5, "numero": 12, "medicao_id": 77, "contrato_id": ids["contrato"],
         "dias": 6, "mensagem": "nota 12 protocolada há 6 dias e ainda não apareceu no RM"}])
    a = [x for x in avisos.listar(c, D(2026, 9, 20)) if x["tipo"] == "nota_ausente_rm"][0]
    assert (a["medicao_id"], a["data"], a["sentido"]) == (77, "2026-09-14", "desde")


def test_avisos_do_nivel_vem_do_mais_atrasado_para_o_menos(cenario, monkeypatch):
    c, ids = cenario                          # G4-04: os piores primeiro dentro do nivel, tanto "prazo" quanto "desde"
    def mk(tipo, dias, sentido, data=None):
        return avisos.aviso(tipo, "acao", "x", ids["contrato"], "Obra A", dias=dias, sentido=sentido, data=data)
    monkeypatch.setattr(avisos, "FONTES", [lambda conn, hoje: [
        mk("a", 3, "desde"), mk("b", -10, "prazo"), mk("c", 40, "desde"), mk("d", 5, "prazo"),
        mk("e", None, None), mk("f", -2, "prazo"), mk("g", None, "desde", "2026-01-01")]])
    assert [a["tipo"] for a in avisos.listar(c, D(2026, 9, 20))] == ["g", "c", "b", "a", "f", "d", "e"]


def test_mensagem_sem_prefixo_da_obra_e_datas_com_ano(cenario):
    c, ids = cenario                          # G1-07: a tela mostra a obra em coluna; datas com ano
    lista = avisos.listar(c, D(2026, 9, 1), publico="todos")
    assert lista and not [a for a in lista if a["mensagem"].startswith("Obra A")]
    execucao = [a for a in lista if a["tipo"] == "execucao_vencendo"][0]
    assert execucao["mensagem"] == "execução termina em 49 dias (20/10/2026)"


def test_diretoria_nao_tem_aviso_de_pagamento_atrasado(cenario):
    c, ids = cenario                          # issue #255: o motor de atraso de pagamento por orgao saiu
    c.execute("INSERT OR REPLACE INTO cadastro_geral (chave, valor) VALUES ('diretoria', ?)",
              (json.dumps({"total_a_receber_liberado": True}),))
    c.commit()                                # a 2a medicao esta' protocolada desde 30/07/2026: 200 dias depois
    lista = avisos.listar(c, D(2027, 2, 15), publico="diretoria")
    assert "pagamento_atrasado" not in {a["tipo"] for a in lista}
