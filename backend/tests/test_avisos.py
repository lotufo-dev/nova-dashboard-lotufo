"""Registro unico de avisos (spec §11) e resumo do mes da tela inicial (§10.1)."""
import datetime
import json
import sqlite3

import pytest

from app import auth, avisos, db, espelhos, medicoes, paineis, reajuste, tempo
from tests.test_espelhos import _antes_do_espelho, _boletim, ambiente, ambiente_projeto  # noqa: F401  (fixtures da obra com espelho)

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


# --- avisos do SIGA (issue #330) ---------------------------------------------------------------------------

UTC = datetime.timezone.utc
SITUACAO_COFIN = "1º Volume - Aguardando Andamento [COFIN, [X]]"
NUMERO_SIGA = "SINFRA-PRO-2026/00001"


def _cuiaba(ano, mes, dia, hora, minuto=0):
    return datetime.datetime(ano, mes, dia, hora, minuto, tzinfo=datetime.timezone(datetime.timedelta(hours=-4))
                             ).astimezone(UTC)


def _banco(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _processo_siga(c, ids, recebido_em, lido_em=None, medicao=1, numero=NUMERO_SIGA, outros_movs=()):
    """Processo recebido no COFIN em `recebido_em` (hora de Cuiaba). `medicao`: 1 (protocolada), 2 ou None (sem medicao)."""
    medicao_id = None if medicao is None else [r[0] for r in c.execute("SELECT id FROM medicoes ORDER BY id")][medicao - 1]
    pid = c.execute("INSERT INTO siga_processos (numero, nome, contrato_id, medicao_id) VALUES (?,?,?,?)",
                    (numero, "Processo Alfa", ids["contrato"] if medicao_id else None, medicao_id)).lastrowid
    c.execute("INSERT INTO siga_leituras (processo_id, lido_em, situacao) VALUES (?,?,?)",
              (pid, lido_em or _banco(_cuiaba(2026, 10, 28, 8)), SITUACAO_COFIN))
    for data, evento in ((recebido_em, "Recebimento"), *outros_movs):
        c.execute("INSERT INTO siga_movimentacoes (processo_id, data, evento, at_lotacao, at_pessoa) VALUES (?,?,?,?,?)",
                  (pid, data, evento, "COFIN/ORGAO", "Fulano"))
    c.commit()
    return pid


def _de_siga(c, hoje=D(2026, 10, 28), tipo="siga_parado"):
    return [a for a in avisos.listar(c, hoje) if a["tipo"] == tipo]


def test_processo_parado_ha_7_dias_uteis_e_atencao_com_a_obra_e_o_destino(cenario):
    c, ids = cenario
    pid = _processo_siga(c, ids, "2026-10-19 10:00:00")            # 19, 20, 21, 22, 23, 26 e 27/10: 7 dias uteis
    [a] = _de_siga(c)
    assert a["nivel"] == "atencao" and a["publico"] == ["operacao"]
    assert a["mensagem"] == "processo SINFRA-PRO-2026/00001 parado em COFIN há 7 dias úteis"
    assert (a["obra"], a["contrato_id"], a["medicao_id"]) == ("Obra A", ids["contrato"], c.execute(
        "SELECT medicao_id FROM siga_processos WHERE id=?", (pid,)).fetchone()[0])
    assert (a["dias"], a["data"], a["sentido"]) == (7, "2026-10-19", "desde")
    assert a["destino"] == {"tela": "siga", "processo": pid}


def test_processo_parado_ha_11_dias_uteis_e_acao_e_com_4_nao_aparece(cenario):
    c, ids = cenario
    _processo_siga(c, ids, "2026-10-13 10:00:00")                   # 13 a 27/10 sem o feriado de 12/10: 11 dias uteis
    [a] = _de_siga(c)
    assert (a["nivel"], a["dias"]) == ("acao", 11)
    assert [x["dias"] for x in _de_siga(c, D(2026, 10, 23))] == [8]   # 13 a 22/10
    assert [x["nivel"] for x in _de_siga(c, D(2026, 10, 23))] == ["atencao"]
    assert _de_siga(c, D(2026, 10, 15)) == []                         # 13 e 14/10: 2 dias uteis
    assert _de_siga(c, D(2026, 10, 19)) == []                         # 13, 14, 15 e 16/10: 4 dias uteis
    assert [x["nivel"] for x in _de_siga(c, D(2026, 10, 20))] == ["atencao"]   # 5 dias uteis
    assert [x["nivel"] for x in _de_siga(c, D(2026, 10, 27))] == ["acao"]       # 10 dias uteis


def test_processo_parado_some_com_movimentacao_de_hoje_ou_medicao_recebida(cenario):
    c, ids = cenario
    pid = _processo_siga(c, ids, "2026-10-19 10:00:00")
    assert len(_de_siga(c)) == 1
    c.execute("INSERT INTO siga_movimentacoes (processo_id, data, evento, at_lotacao) VALUES (?,?,?,?)",
              (pid, "2026-10-28 09:30:00", "Despacho", "COFIN/ORGAO")); c.commit()
    assert _de_siga(c) == []                                          # andou hoje
    assert _de_siga(c, D(2026, 10, 29)) == []                         # a movimentacao zera a contagem, nao so' no dia
    assert _de_siga(c, D(2026, 11, 4)) == []                          # 28, 29, 30/10, 3 e 4/11: ainda 4 dias uteis
    [a] = _de_siga(c, D(2026, 11, 5))                                 # 5 dias uteis depois do despacho, o aviso volta
    assert (a["nivel"], a["dias"], a["data"]) == ("atencao", 5, "2026-10-28")
    assert a["mensagem"] == "processo SINFRA-PRO-2026/00001 parado em COFIN há 5 dias úteis"
    c.execute("UPDATE medicoes SET estado='recebida' WHERE id=(SELECT medicao_id FROM siga_processos WHERE id=?)", (pid,))
    c.commit()
    assert _de_siga(c, D(2026, 11, 5)) == []


def test_so_o_processo_do_protocolo_mais_recente_da_medicao_avisa(cenario):
    c, ids = cenario                          # a medicao foi protocolada de novo: o processo antigo ficou arquivado no SIGA
    for _ in (1, 2):
        c.execute("INSERT INTO protocolos (contrato_id, etapa, natureza, usuario_id) VALUES (?,?,?,1)",
                  (ids["contrato"], "unico", "execucao"))
    p_antigo, p_novo = [r[0] for r in c.execute("SELECT id FROM protocolos ORDER BY id")]
    primeiro = _processo_siga(c, ids, "2026-10-13 10:00:00", numero="SINFRA-PRO-2026/00001")
    segundo = _processo_siga(c, ids, "2026-10-13 10:00:00", numero="SINFRA-PRO-2026/00002")
    c.execute("UPDATE siga_processos SET protocolo_id=? WHERE id=?", (p_antigo, primeiro))
    c.execute("UPDATE siga_processos SET protocolo_id=? WHERE id=?", (p_novo, segundo)); c.commit()
    assert [a["destino"]["processo"] for a in _de_siga(c)] == [segundo]
    # quem decide e' o protocolo, nao a ordem dos processos
    c.execute("UPDATE siga_processos SET protocolo_id=? WHERE id=?", (p_novo, primeiro))
    c.execute("UPDATE siga_processos SET protocolo_id=? WHERE id=?", (p_antigo, segundo)); c.commit()
    assert [a["destino"]["processo"] for a in _de_siga(c)] == [primeiro]
    # sem protocolo nenhum (envio por fora), vale o processo mais novo
    c.execute("UPDATE siga_processos SET protocolo_id=NULL"); c.commit()
    assert [a["destino"]["processo"] for a in _de_siga(c)] == [segundo]


def test_processo_cancelado_nao_conta_como_movimentacao_de_hoje(cenario):
    c, ids = cenario
    _processo_siga(c, ids, "2026-10-19 10:00:00", outros_movs=[("2026-10-28 09:30:00", "Despacho Cancelado")])
    assert len(_de_siga(c)) == 1


def test_processo_sem_medicao_nao_gera_aviso(cenario):
    c, ids = cenario
    _processo_siga(c, ids, "2026-09-01 10:00:00", medicao=None)       # "Outros processos": 20 dias uteis ou mais
    assert _de_siga(c) == []


def test_aviso_de_processo_parado_entra_na_ordem_do_nivel_e_nao_e_da_diretoria(cenario):
    c, ids = cenario
    _processo_siga(c, ids, "2026-10-13 10:00:00")
    lista = avisos.listar(c, D(2026, 10, 28))
    assert "siga_parado" in {a["tipo"] for a in lista}
    niveis = [avisos.NIVEIS.index(a["nivel"]) for a in lista]
    assert niveis == sorted(niveis)
    assert "siga_parado" not in {a["tipo"] for a in avisos.listar(c, D(2026, 10, 28), publico="diretoria")}


def test_monitor_sem_leitura_ha_mais_de_2_horas_em_dia_util_e_acao(cenario, monkeypatch):
    c, ids = cenario
    _processo_siga(c, ids, "2026-10-26 10:00:00", lido_em=_banco(_cuiaba(2026, 10, 27, 8)))
    terca = D(2026, 10, 27)
    monkeypatch.setattr(tempo, "agora_utc", lambda: _cuiaba(2026, 10, 27, 11))
    [a] = _de_siga(c, terca, "siga_sem_leitura")
    assert a["nivel"] == "acao" and a["publico"] == ["operacao"]
    assert a["mensagem"] == "monitor do SIGA sem leitura desde 27/10 08:00"
    assert (a["obra"], a["contrato_id"], a["destino"]) == (None, None, {"tela": "siga"})
    monkeypatch.setattr(tempo, "agora_utc", lambda: _cuiaba(2026, 10, 27, 10))      # so' 2 horas: ainda nao
    assert _de_siga(c, terca, "siga_sem_leitura") == []
    monkeypatch.setattr(tempo, "agora_utc", lambda: _cuiaba(2026, 10, 27, 18))      # fora do horario do robo
    assert _de_siga(c, terca, "siga_sem_leitura") == []
    monkeypatch.setattr(tempo, "agora_utc", lambda: _cuiaba(2026, 10, 27, 11))
    assert "siga_sem_leitura" not in {x["tipo"] for x in avisos.listar(c, terca, publico="diretoria")}


def test_monitor_sem_leitura_no_domingo_ou_sem_processo_acompanhado_nao_avisa(cenario, monkeypatch):
    c, ids = cenario
    monkeypatch.setattr(tempo, "agora_utc", lambda: _cuiaba(2026, 10, 27, 11))
    assert _de_siga(c, D(2026, 10, 27), "siga_sem_leitura") == []                    # nenhum processo acompanhado
    _processo_siga(c, ids, "2026-10-23 10:00:00", lido_em=_banco(_cuiaba(2026, 10, 23, 8)))
    monkeypatch.setattr(tempo, "agora_utc", lambda: _cuiaba(2026, 10, 25, 11))       # domingo
    assert _de_siga(c, D(2026, 10, 25), "siga_sem_leitura") == []


def test_monitor_sem_leitura_um_so_aviso_mesmo_com_varios_processos(cenario, monkeypatch):
    c, ids = cenario
    lido = _banco(_cuiaba(2026, 10, 27, 8))
    _processo_siga(c, ids, "2026-10-26 10:00:00", lido_em=lido)
    _processo_siga(c, ids, "2026-10-26 10:00:00", lido_em=lido, medicao=2, numero="SINFRA-PRO-2026/00002")
    _processo_siga(c, ids, "2026-10-26 10:00:00", lido_em=lido, medicao=None, numero="SINFRA-PRO-2026/00003")
    monkeypatch.setattr(tempo, "agora_utc", lambda: _cuiaba(2026, 10, 27, 11))
    assert len(_de_siga(c, D(2026, 10, 27), "siga_sem_leitura")) == 1


# --- issue #359: o aprovado mudou depois do espelho ---------------------------------------------------------------

def _desatualizados(conn):
    return [a for a in avisos.listar(conn) if a["tipo"] == "espelho_desatualizado"]


def _espelho_enviado(conn, u, cid, valor, numero=23):
    """Espelho gerado com `valor` (sem boletim, a medicao nasce nele) e enviado ao faturamento. Devolve a medicao."""
    eid = espelhos.gerar(conn, u, cid, numero, "2026-01", {"medicao": valor})
    mid = espelhos.detalhe(conn, eid)["medicoes"][0]["id"]
    medicoes.marcar_espelho_enviado(conn, u["id"], mid)
    return mid


def test_boletim_com_aprovado_diferente_do_espelho_avisa_sem_dizer_glosa(ambiente):
    conn, u, cid = ambiente
    mid = _espelho_enviado(conn, u, cid, 100_01)
    assert _desatualizados(conn) == []
    _boletim(conn, u, mid, 99_99)
    [a] = _desatualizados(conn)
    assert (a["medicao_id"], a["contrato_id"], a["nivel"], a["valor_centavos"]) == (mid, cid, "acao", 99_99)
    assert a["mensagem"] == "23ª Medição: o aprovado mudou depois do espelho, gere o espelho de novo"
    assert "glosa" not in a["mensagem"].lower()
    assert a["destino"] == {"tela": "contrato", "id": cid, "aba": "espelho"}
    assert medicoes.detalhe(conn, mid)["espelho_desatualizado"] == "aprovado_mudou"
    assert [m["espelho_desatualizado"] for m in medicoes.listar(conn, cid)] == ["aprovado_mudou"]


def test_boletim_com_o_mesmo_valor_do_espelho_nao_avisa(ambiente):
    conn, u, cid = ambiente
    mid = _espelho_enviado(conn, u, cid, 100_01)
    _boletim(conn, u, mid, 100_01)
    assert _desatualizados(conn) == []
    assert medicoes.detalhe(conn, mid)["espelho_desatualizado"] is None


def test_aviso_some_quando_a_versao_nova_e_gerada(ambiente):
    conn, u, cid = ambiente
    mid = _espelho_enviado(conn, u, cid, 100_01)
    _boletim(conn, u, mid, 99_99)
    assert len(_desatualizados(conn)) == 1
    espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 99_99}, motivo="boletim novo do órgão")
    assert _desatualizados(conn) == []
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["espelho_desatualizado"]) == ("espelho_gerado", None)


def test_espelho_misto_compara_o_valor_de_cada_medicao(ambiente_projeto):
    # o espelho com execucao e projeto: o aprovado da execucao se compara com o valor DELA, nao com o total
    conn, u, cid = ambiente_projeto
    eid = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100_01, "projeto": 7_01})
    exe = next(m["id"] for m in espelhos.detalhe(conn, eid)["medicoes"] if m["tipo"] == "execucao")
    _boletim(conn, u, exe, 100_01)
    assert _desatualizados(conn) == []
    _boletim(conn, u, exe, 100_03, sha="b")
    assert [a["medicao_id"] for a in _desatualizados(conn)] == [exe]


def test_espelho_de_antes_da_migracao_usa_as_entradas_gravadas(ambiente):
    # o espelho gerado antes da coluna do valor por medicao (065) nao tem o valor: vem das entradas pela regra
    conn, u, cid = ambiente
    mid = _espelho_enviado(conn, u, cid, 100_01)
    conn.execute("UPDATE espelho_medicoes SET valor_centavos=NULL"); conn.commit()
    _boletim(conn, u, mid, 100_01)
    assert _desatualizados(conn) == []
    _boletim(conn, u, mid, 99_99, sha="b")
    assert [a["medicao_id"] for a in _desatualizados(conn)] == [mid]

    # a regra trocada depois do espelho pode ter outras chaves: sem a do espelho, nao ha' como comparar
    conn.execute("UPDATE espelho_regras SET sha256='outra' WHERE contrato_id=?", (cid,)); conn.commit()
    assert _desatualizados(conn) == []


def _nao_conferidos(conn):
    return [a for a in avisos.listar(conn) if a["tipo"] == "espelho_nao_conferido"]


def _espelho_antigo(conn, cid, criado_em="2026-01-05 10:00:00"):
    """O espelho de antes da 065 (sem o valor por medicao), com a regra da obra trocada depois dele."""
    conn.execute("UPDATE espelho_medicoes SET valor_centavos=NULL")
    conn.execute("UPDATE espelho_regras SET sha256='outra' WHERE contrato_id=?", (cid,))
    conn.execute("UPDATE espelhos SET criado_em=?", (criado_em,))
    conn.commit()


def _atesto_depois(conn, u, mid, valor, origem="manual"):
    """Atesto registrado depois do espelho antigo (o evento e' imutavel: entra com a data, como a carga faria)."""
    conn.execute("INSERT INTO medicao_atestos (medicao_id, valor_centavos, origem, atestado_em, usuario_id, criado_em) "
                 "VALUES (?,?,?,'2026-02-20',?,'2026-03-01 10:00:00')", (mid, valor, origem, u["id"]))
    conn.execute("UPDATE medicoes SET valor_atestado_centavos=? WHERE id=?", (valor, mid))
    conn.commit()


def test_espelho_antigo_com_a_regra_trocada_compara_com_o_pedido_que_travou(ambiente):
    # rodada 2 da PR #474: sem o valor e com a regra trocada, a referencia e' o que o espelho travou ao ser gerado
    # (sem atesto ate' ele, o pedido): o mesmo valor nao avisa, de boletim, de carga ou de correcao digitada
    conn, u, cid = ambiente
    mid = _espelho_enviado(conn, u, cid, 100_01)
    _espelho_antigo(conn, cid)
    medicoes.definir_valor(conn, u["id"], mid, "atestado", 100_01, "manual", "2026-02-21")    # digitado (sem boletim)
    _atesto_depois(conn, u, mid, 100_01, origem="detectado")                                    # carga
    _boletim(conn, u, mid, 100_01)
    assert _nao_conferidos(conn) == [] and _desatualizados(conn) == []
    assert medicoes.detalhe(conn, mid)["espelho_desatualizado"] is None
    _boletim(conn, u, mid, 99_99, sha="b")
    [a] = _desatualizados(conn)
    assert (a["medicao_id"], a["mensagem"]) == (mid, "23ª Medição: o aprovado mudou depois do espelho, gere o espelho "
                                                     "de novo")
    espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 99_99}, motivo="boletim novo do órgão")
    assert _desatualizados(conn) == [] and _nao_conferidos(conn) == []


def test_espelho_antigo_com_a_regra_trocada_compara_com_o_aprovado_de_quando_foi_gerado(ambiente):
    # a medicao com boletim antes do espelho: o espelho travou aquele aprovado, nao o pedido
    conn, u, cid = ambiente
    mid = _antes_do_espelho(conn, cid, 23, "planilha_enviada", pedido=12_345_67)
    _boletim(conn, u, mid, 12_000_01)
    espelhos.gerar(conn, u, cid, 23, "2026-01", {})
    _espelho_antigo(conn, cid, criado_em="2999-01-01 10:00:00")     # o boletim acima fica antes do espelho
    assert _desatualizados(conn) == [] and _nao_conferidos(conn) == []
    conn.execute("UPDATE espelhos SET criado_em='2026-02-28 10:00:00'"); conn.commit()
    _atesto_depois(conn, u, mid, 11_999_99)
    assert [a["medicao_id"] for a in _desatualizados(conn)] == [mid]


def test_espelho_antigo_sem_referencia_nenhuma_avisa_que_nao_confere(ambiente):
    # gate Sol (PR #474): sem valor, sem a regra do espelho, sem atesto ate' ele e sem pedido, nao ha' como comparar
    conn, u, cid = ambiente
    mid = _espelho_enviado(conn, u, cid, 100_01)
    _espelho_antigo(conn, cid)
    conn.execute("UPDATE medicoes SET valor_protocolado_centavos=NULL, valor_protocolado_origem=NULL"); conn.commit()
    _atesto_depois(conn, u, mid, 100_01)
    [a] = _nao_conferidos(conn)
    assert a["mensagem"] == "23ª Medição: não foi possível conferir o valor do espelho antigo, gere o espelho de novo"
    assert "aprovado mudou" not in a["mensagem"] and "glosa" not in a["mensagem"].lower()
    assert (a["medicao_id"], a["destino"]) == (mid, {"tela": "contrato", "id": cid, "aba": "espelho"})
    assert medicoes.detalhe(conn, mid)["espelho_desatualizado"] == "nao_conferido"
    # na nota emitida o espelho nao se gera mais: o texto da nota emitida, que leva as notas (gate Sol, rodada 2)
    conn.execute("UPDATE medicoes SET estado='nota_emitida' WHERE id=?", (mid,)); conn.commit()
    assert _nao_conferidos(conn) == []
    [a] = _desatualizados(conn)
    assert (a["mensagem"], a["destino"]["aba"]) == (
        "23ª Medição: o aprovado mudou depois do espelho e a nota já foi emitida", "notas")


def test_espelho_antigo_regra_trocada_atesto_novo_e_nota_emitida_continua_avisando(ambiente, monkeypatch):
    # gate Sol (rodada 2 da PR #474): os quatro juntos nao podem fazer o aviso sumir
    from app import notas
    conn, u, cid = ambiente
    mid = _espelho_enviado(conn, u, cid, 100_01)
    _espelho_antigo(conn, cid)
    _atesto_depois(conn, u, mid, 99_99)
    monkeypatch.setattr(notas, "faltam", lambda c, m: 0)        # a nota da v1 alocada pela sincronizacao do RM
    assert notas.fechar_se_completa(conn, u["id"], mid)
    [a] = _desatualizados(conn)
    assert (a["medicao_id"], a["mensagem"], a["destino"]["aba"]) == (
        mid, "23ª Medição: o aprovado mudou depois do espelho e a nota já foi emitida", "notas")
    assert medicoes.detalhe(conn, mid)["espelho_desatualizado"] == "nota_emitida"


def test_nota_da_v1_lancada_depois_do_boletim_novo_mantem_o_aviso(ambiente, monkeypatch):
    # revisor (PR #474): o RM lanca a nota da v1 com o aviso na tela; a medicao vai a `nota_emitida` e o aviso fica
    from app import notas
    conn, u, cid = ambiente
    mid = _espelho_enviado(conn, u, cid, 100_01)
    _boletim(conn, u, mid, 99_99)
    monkeypatch.setattr(notas, "faltam", lambda c, m: 0)        # a nota da v1 alocada pela sincronizacao do RM
    assert notas.fechar_se_completa(conn, u["id"], mid)
    assert medicoes.detalhe(conn, mid)["estado"] == "nota_emitida"
    [a] = _desatualizados(conn)
    assert a["mensagem"] == "23ª Medição: o aprovado mudou depois do espelho e a nota já foi emitida"
    assert (a["medicao_id"], a["destino"]) == (mid, {"tela": "contrato", "id": cid, "aba": "notas"})
    assert medicoes.detalhe(conn, mid)["espelho_desatualizado"] == "nota_emitida"


def test_medicao_protocolada_nao_avisa_espelho_desatualizado(ambiente):
    # depois do protocolo o espelho nao se gera mais: o aviso pediria o que nao da' para fazer
    conn, u, cid = ambiente
    mid = _espelho_enviado(conn, u, cid, 100_01)
    _boletim(conn, u, mid, 99_99)
    conn.execute("UPDATE medicoes SET estado='protocolada' WHERE id=?", (mid,)); conn.commit()
    assert _desatualizados(conn) == []


# ---- Avisos do motor de apostilamento (issue #274; spec 2026-10-20 §2.2, decisao do Leo de 08/11/2026) ----

@pytest.fixture
def obra_reajuste(tmp_path, monkeypatch):
    """Contrato com data-base 06/2024: o ciclo de 2026 vai de 06/2026 a 05/2027."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "r.db"))
    c = db.get_conn(); db.migrate(c)
    uid = auth.criar_usuario(c, "Engenharia", "e@l.com", "senha-forte-123", "engenharia")
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos) "
              "VALUES ('MTPAR', '099/2024', 'Cultural', 'obra', 100)")
    cid = c.execute("SELECT MAX(id) FROM contratos").fetchone()[0]
    c.execute("INSERT INTO contrato_datas_base (contrato_id, mes, indice) VALUES (?, '2024-06', 'INCC-DI')", (cid,))
    c.commit()
    yield c, cid, uid
    c.close()


def _r_previsao(c, cid, comp, valor, ciclo=2026, criado_em="2026-07-01 10:00:00"):
    c.execute("INSERT INTO reajuste_previsoes (contrato_id, data_base_mes, ciclo, competencia, valor_previsto_centavos, "
              "origem, criado_em) VALUES (?, '2024-06', ?, ?, ?, 'manual', ?)", (cid, ciclo, comp, valor, criado_em))
    c.commit()


def _r_medicao(c, cid, numero, comp, estado, pedido=None, aprovado=None):
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
              "valor_atestado_centavos) VALUES (?, ?, 'reajuste', ?, ?, ?, ?)", (cid, numero, comp, estado, pedido, aprovado))
    c.commit()
    return c.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]


def _r_nota(c, mid, valor):
    c.execute("INSERT INTO notas_fiscais (coligada, numero, valor_centavos, situacao, origem) VALUES (1, ?, ?, 'ativa', 'pdf')",
              (f"NF-{mid}", valor))
    nid = c.execute("SELECT MAX(id) FROM notas_fiscais").fetchone()[0]
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem) VALUES (?, ?, ?, 'manual')",
              (mid, nid, valor))
    c.commit()


def _r_pleito(c, cid, enviado_em, reemite=None, reemissao=None, numero="CT-1-LT-2026"):
    c.execute("INSERT INTO pleitos (contrato_id, tipo, origem, data_base_mes, ciclo, numero_oficio, situacao, enviado_em, "
              "reemite_pleito_id, reemissao) VALUES (?, 'reajuste', 'cadastro', '2024-06', 2026, ?, 'enviado', ?, ?, ?)",
              (cid, numero, enviado_em, reemite, reemissao))
    c.commit()
    return c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]


def _r_termo_do_ciclo(c, cid, ligar_pleito=None):
    """Apostilamento por percentual da MT-PAR com o periodo do ciclo de 2026 inteiro: apostila cada competencia."""
    c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) VALUES (?, 'ap-2026', "
              "'apostilamento_reajuste', '2026-11-20', ?)",
              (cid, json.dumps({"data_base": "2024-06", "ciclo": 2026, "percentual": "6,76",
                                "periodo": {"de": "2026-06", "ate": "2027-05"}})))
    if ligar_pleito:
        c.execute("UPDATE pleitos SET instrumento_chave='ap-2026' WHERE id=?", (ligar_pleito,))
    c.commit()


def _do_tipo(c, tipo, hoje=D(2026, 10, 1), publico="todos"):
    return [a for a in avisos.listar(c, hoje, publico=publico) if a["tipo"] == tipo]


def test_reajuste_fora_da_previsao_com_mais_de_um_real_e_some_com_a_reapresentacao(obra_reajuste):
    c, cid, _ = obra_reajuste
    _r_previsao(c, cid, "2026-07", 100_01)
    _r_previsao(c, cid, "2026-08", 100_01)
    _r_medicao(c, cid, 1, "2026-07", "planilha_enviada", pedido=101_01)          # R$ 1,00 acima: dentro da tolerancia
    m2 = _r_medicao(c, cid, 2, "2026-08", "planilha_enviada", pedido=101_02)     # R$ 1,01 acima
    [a] = _do_tipo(c, "reajuste_fora_da_previsao")
    assert (a["nivel"], a["publico"], a["obra"], a["valor_centavos"], a["competencia"], a["data_base_mes"], a["ciclo"]) \
        == ("atencao", ["operacao"], "Cultural", 101_02, "2026-08", "2024-06", 2026)
    assert a["mensagem"] == ("reajuste de 08/2026 (data-base 06/2024): pedido R$ 101,02, previsto R$ 100,01; "
                             "reajuste fora da previsão")
    assert a["destino"] == {"tela": "contrato", "id": cid, "aba": "reajuste"}
    assert _do_tipo(c, "reajuste_fora_da_previsao", publico="diretoria") == []
    # reapresentacao: o pedido volta para dentro da tolerancia
    c.execute("UPDATE medicoes SET valor_protocolado_centavos=99_01 WHERE id=?", (m2,)); c.commit()
    assert _do_tipo(c, "reajuste_fora_da_previsao") == []


def test_justificativa_tira_o_aviso_enquanto_pedido_e_previsto_nao_mudam(obra_reajuste):
    c, cid, uid = obra_reajuste
    _r_previsao(c, cid, "2026-08", 100_01)
    m = _r_medicao(c, cid, 1, "2026-08", "planilha_enviada", pedido=101_02)
    reajuste.justificar(c, uid, cid, "2024-06", 2026, "2026-08", "  Índice definitivo saiu maior  ")
    assert _do_tipo(c, "reajuste_fora_da_previsao") == []
    [g] = reajuste.competencias_por_ciclo(c, cid)
    x = g["competencias"][0]
    assert x["avisos"] == []
    assert (x["justificativa"]["texto"], x["justificativa"]["usuario"], x["justificativa"]["pedido_centavos"],
            x["justificativa"]["previsto_centavos"]) == ("Índice definitivo saiu maior", "Engenharia", 101_02, 100_01)
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE acao='reajuste.justificativa'").fetchone()[0] == 1
    # o previsto muda (previsao nova): a justificativa deixa de valer e o aviso volta
    _r_previsao(c, cid, "2026-08", 90_00, criado_em="2026-08-01 10:00:00")
    assert len(_do_tipo(c, "reajuste_fora_da_previsao")) == 1
    reajuste.justificar(c, uid, cid, "2024-06", 2026, "2026-08", "Previsão nova, mesmo índice")
    assert _do_tipo(c, "reajuste_fora_da_previsao") == []
    # o pedido muda: volta de novo
    c.execute("UPDATE medicoes SET valor_protocolado_centavos=105_00 WHERE id=?", (m,)); c.commit()
    assert len(_do_tipo(c, "reajuste_fora_da_previsao")) == 1


def test_justificativa_curta_ou_sem_aviso_e_recusada(obra_reajuste):
    c, cid, uid = obra_reajuste
    _r_previsao(c, cid, "2026-07", 100_01)
    _r_previsao(c, cid, "2026-08", 100_01)
    _r_medicao(c, cid, 1, "2026-07", "planilha_enviada", pedido=100_50)          # dentro da tolerancia
    _r_medicao(c, cid, 2, "2026-08", "planilha_enviada", pedido=200_00)
    with pytest.raises(ValueError, match="pelo menos 10 caracteres"):
        reajuste.justificar(c, uid, cid, "2024-06", 2026, "2026-08", "  curta   ")
    with pytest.raises(ValueError, match="não está fora da previsão"):
        reajuste.justificar(c, uid, cid, "2024-06", 2026, "2026-07", "Texto bem comprido aqui")
    with pytest.raises(ValueError, match="não está fora da previsão"):
        reajuste.justificar(c, uid, cid, "2024-06", 2025, "2026-08", "Texto bem comprido aqui")
    assert c.execute("SELECT COUNT(*) FROM reajuste_justificativas").fetchone()[0] == 0


def test_justificativa_e_evento_que_nao_se_altera_nem_se_apaga(obra_reajuste):
    c, cid, uid = obra_reajuste
    _r_previsao(c, cid, "2026-08", 100_01)
    _r_medicao(c, cid, 1, "2026-08", "planilha_enviada", pedido=200_00)
    jid = reajuste.justificar(c, uid, cid, "2024-06", 2026, "2026-08", "Índice definitivo saiu maior")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE reajuste_justificativas SET texto='outro texto qualquer' WHERE id=?", (jid,))
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("DELETE FROM reajuste_justificativas WHERE id=?", (jid,))
    c.rollback()


def test_reajuste_sem_apostilamento_um_aviso_por_ciclo_com_a_soma_medida_na_cota(obra_reajuste):
    c, cid, _ = obra_reajuste
    c.execute("UPDATE contratos SET percentual_direito_bp=5000"); c.commit()      # consorcio: metade da Lotufo
    _r_medicao(c, cid, 1, "2026-07", "planilha_enviada", pedido=900_000_00)                  # so' pedida: fora
    _r_medicao(c, cid, 2, "2026-08", "boletim_recebido", pedido=120_000_00, aprovado=110_000_01)   # o aprovado
    m3 = _r_medicao(c, cid, 3, "2026-09", "nota_emitida", pedido=95_000_00, aprovado=94_000_00)
    _r_nota(c, m3, 90_000_02)                                                                # o faturado
    [a] = _do_tipo(c, "reajuste_sem_apostilamento")
    # 110.000,01 + 90.000,02 = 200.000,03 cheio; a cota (50%) arredonda uma vez, sobre a soma: 100.000,02
    assert (a["nivel"], a["valor_centavos"], a["publico"], a["competencias"], a["ciclo"]) == \
        ("atencao", 100_000_02, ["operacao", "diretoria"], ["2026-08", "2026-09"], 2026)
    assert a["mensagem"] == "data-base 06/2024, ciclo de 2026: reajuste de 08/2026 e 09/2026 sem apostilamento"
    assert len(_do_tipo(c, "reajuste_sem_apostilamento", publico="diretoria")) == 1
    # o apostilamento carregado cobre as competencias: o aviso some
    _r_termo_do_ciclo(c, cid)
    assert _do_tipo(c, "reajuste_sem_apostilamento") == []


def test_reajuste_sem_apostilamento_so_vai_a_diretoria_acima_de_100_mil(obra_reajuste):
    c, cid, _ = obra_reajuste
    m = _r_medicao(c, cid, 1, "2026-08", "boletim_recebido", pedido=100_000_00, aprovado=100_000_00)
    [a] = _do_tipo(c, "reajuste_sem_apostilamento")
    assert (a["valor_centavos"], a["publico"]) == (100_000_00, ["operacao"])      # R$ 100 mil exatos: nao passa
    assert _do_tipo(c, "reajuste_sem_apostilamento", publico="diretoria") == []
    c.execute("UPDATE medicoes SET valor_atestado_centavos=100_000_01 WHERE id=?", (m,)); c.commit()
    [a] = _do_tipo(c, "reajuste_sem_apostilamento")
    assert (a["valor_centavos"], a["publico"]) == (100_000_01, ["operacao", "diretoria"])


def test_nota_de_reajuste_antes_do_apostilamento_e_critico_e_some_com_o_termo(obra_reajuste):
    c, cid, _ = obra_reajuste
    m = _r_medicao(c, cid, 1, "2026-09", "nota_emitida", pedido=300_05, aprovado=300_05)
    _r_nota(c, m, 300_05)
    [a] = _do_tipo(c, "reajuste_nota_antes_do_apostilamento")
    assert (a["nivel"], a["publico"], a["valor_centavos"], a["competencia"]) == ("critico", ["operacao"], 300_05, "2026-09")
    assert a["mensagem"] == "nota de reajuste de 09/2026 (data-base 06/2024) emitida antes do apostilamento"
    _r_termo_do_ciclo(c, cid)
    assert _do_tipo(c, "reajuste_nota_antes_do_apostilamento") == []


def test_cronograma_de_reajuste_a_reemitir_e_some_com_o_pleito_novo(obra_reajuste):
    c, cid, _ = obra_reajuste
    p1 = _r_pleito(c, cid, "2026-06-10")
    c.execute("INSERT INTO aditivos (contrato_id, tipo, status, data_assinatura, numero) "
              "VALUES (?, 'prazo', 'assinado', '2026-08-01', '5º Termo Aditivo')", (cid,)); c.commit()
    [a] = _do_tipo(c, "reajuste_reemitir")
    assert (a["nivel"], a["publico"], a["data"], a["sentido"], a["dias"], a["data_base_mes"]) == \
        ("acao", ["operacao"], "2026-08-01", "desde", 61, "2024-06")
    assert a["mensagem"] == ("data-base 06/2024: aditivo 5º Termo Aditivo assinado em 01/08/2026, depois do pleito; "
                             "cronograma de reajuste a reemitir")
    # a reiteracao nao traz cronograma: o aviso segue
    _r_pleito(c, cid, "2026-09-01", reemite=p1, reemissao="reiteracao", numero="CT-2-LT-2026")
    assert len(_do_tipo(c, "reajuste_reemitir")) == 1
    # a reemissao do cronograma enviada: some
    _r_pleito(c, cid, "2026-09-10", reemite=p1, reemissao="cronograma", numero="CT-3-LT-2026")
    assert _do_tipo(c, "reajuste_reemitir") == []


def test_pedido_de_reajuste_sem_resposta_depois_de_120_dias_do_ultimo_pleito(obra_reajuste):
    c, cid, _ = obra_reajuste
    p1 = _r_pleito(c, cid, "2026-06-10")
    assert _do_tipo(c, "reajuste_sem_resposta", D(2026, 10, 8)) == []              # 120 dias: ainda nao
    [a] = _do_tipo(c, "reajuste_sem_resposta", D(2026, 10, 9))
    assert (a["nivel"], a["publico"], a["dias"], a["data"], a["sentido"]) == \
        ("acao", ["operacao", "diretoria"], 121, "2026-06-10", "desde")
    assert a["mensagem"] == "pedido de reajuste da data-base 06/2024 enviado em 10/06/2026, há 121 dias, sem resposta"
    assert len(_do_tipo(c, "reajuste_sem_resposta", D(2026, 10, 9), publico="diretoria")) == 1
    # a reiteracao enviada zera a contagem, em qualquer orgao
    _r_pleito(c, cid, "2026-10-05", reemite=p1, reemissao="reiteracao", numero="CT-2-LT-2026")
    assert _do_tipo(c, "reajuste_sem_resposta", D(2026, 10, 9)) == []
    assert len(_do_tipo(c, "reajuste_sem_resposta", D(2027, 2, 3))) == 1          # 121 dias da reiteracao
    # o apostilamento ligado ao pedido: some
    _r_termo_do_ciclo(c, cid, ligar_pleito=p1)
    assert _do_tipo(c, "reajuste_sem_resposta", D(2027, 2, 3)) == []


def test_pleito_nao_enviado_diz_o_valor_previsto_do_ciclo(obra_reajuste):
    c, cid, _ = obra_reajuste
    [a] = _do_tipo(c, "reajuste_pleito", D(2026, 5, 15))                           # sem previsao: sem valor
    assert a["valor_centavos"] is None and "previstos" not in a["mensagem"]
    _r_previsao(c, cid, "2026-07", 100_01)
    _r_previsao(c, cid, "2026-08", 200_02)
    _r_previsao(c, cid, "2027-07", 999_99, ciclo=2027)                              # outro ciclo: fora
    [a] = _do_tipo(c, "reajuste_pleito", D(2026, 5, 15))
    assert a["valor_centavos"] == 300_03
    assert a["mensagem"] == ("data-base 06/2024 faz aniversário em 01/06/2026 (em 17 dias); R$ 300,03 previstos para "
                             "o ciclo de 2026; pleito de reajuste não enviado")
