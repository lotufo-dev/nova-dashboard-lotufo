"""Registro unico de avisos (spec §11) e resumo do mes da tela inicial (§10.1)."""
import datetime
import json

import pytest

from app import auth, avisos, db, espelhos, medicoes, paineis, tempo
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


# --- issue #288: avisos do motor de medicao (spec 2026-10-20 §2.1 e §2.1.1; decisao do Leo de 08/11/2026) ----------

@pytest.fixture
def motor(tmp_path, monkeypatch):
    """Obra SINFRA ativa (execucao desde 15/06/2026), orgao com prazo X de 15 dias; hoje = 08/11/2026."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(tempo, "hoje_local", lambda: D(2026, 11, 8))
    c = db.get_conn(); db.migrate(c)
    uid = auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "admin")
    for chave, familia, regras in (("sinfra-x", "sinfra", {"prazo_boletim_dias": 15}), ("sem-prazo", "sinfra", {}),
                                   ("mtpar", "mtpar", {})):
        c.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES (?, ?, ?, ?)",
                  (chave, chave.upper(), familia, json.dumps({"vigencia_automatica": True, **regras})))
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos, "
              "orgao_id, execucao_inicio, execucao_fim, vigencia_fim) VALUES ('SINFRA', 'IC 1/2026', 'Obra A', "
              "'obra', 100, (SELECT id FROM orgaos WHERE chave='sinfra-x'), '2026-06-15', '2027-12-31', '2027-12-31')")
    cid = c.execute("SELECT MAX(id) FROM contratos").fetchone()[0]
    c.commit()
    yield c, {"id": uid}, cid
    c.close()


def _med(c, cid, numero, competencia, estado, pedido=None, inicio=None, fim=None, enviada_em=None, tipo="execucao"):
    mid = c.execute(
        "INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
        "periodo_inicio, periodo_fim, planilha_enviada_em) VALUES (?,?,?,?,?,?,?,?,?)",
        (cid, numero, tipo, competencia, estado, pedido, inicio, fim, enviada_em)).lastrowid
    c.commit()
    return mid


def _do_tipo(c, tipo, hoje, publico="operacao"):
    return [a for a in avisos.listar(c, hoje, publico=publico) if a["tipo"] == tipo]


def _meses_sem_planilha(c, hoje, publico="operacao"):
    return [a["mensagem"] for a in _do_tipo(c, "planilha_nao_enviada", hoje, publico)]


def test_planilha_do_mes_nao_enviada_a_partir_do_dia_5_do_mes_seguinte(motor):
    c, u, cid = motor
    _med(c, cid, 1, "2026-06", "protocolada")
    _med(c, cid, 2, "2026-07", "planilha_enviada", enviada_em="2026-08-03")
    assert _meses_sem_planilha(c, D(2026, 9, 4)) == []                       # 08/2026 so' avisa em 05/09
    assert _meses_sem_planilha(c, D(2026, 9, 5)) == ["planilha/carta de 08/2026 não enviada"]
    [a] = _do_tipo(c, "planilha_nao_enviada", D(2026, 10, 5))[1:]
    assert (a["contrato_id"], a["obra"], a["nivel"], a["publico"], a["data"], a["sentido"], a["dias"]) == (
        cid, "Obra A", "acao", ["operacao"], "2026-10-05", "desde", 0)
    assert _meses_sem_planilha(c, D(2026, 10, 5), publico="diretoria") == []   # so' a operacao
    # a planilha/carta so' gerada ainda nao foi enviada; enviada (ou etapa seguinte, mesmo do fluxo antigo), sai
    m8 = _med(c, cid, 3, "2026-08", "planilha_gerada")
    assert len(_meses_sem_planilha(c, D(2026, 10, 5))) == 2
    c.execute("UPDATE medicoes SET estado='planilha_enviada', planilha_enviada_em='2026-09-02' WHERE id=?", (m8,))
    assert _meses_sem_planilha(c, D(2026, 10, 5)) == ["planilha/carta de 09/2026 não enviada"]
    _med(c, cid, 4, "2026-09", "espelho_gerado")
    assert _meses_sem_planilha(c, D(2026, 10, 5)) == []


def test_planilha_nao_enviada_sem_lacuna_antiga_e_obra_sem_medicao_desde_o_inicio(motor):
    c, u, cid = motor
    # obra sem medicao: desde o mes do inicio da execucao (06/2026), ate' o mes anterior a hoje
    assert _meses_sem_planilha(c, D(2026, 8, 10)) == ["planilha/carta de 06/2026 não enviada",
                                                      "planilha/carta de 07/2026 não enviada"]
    # a lacuna antes da ultima medicao enviada (07/2026) nao avisa
    _med(c, cid, 1, "2026-06", "recebida")
    _med(c, cid, 2, "2026-08", "protocolada")
    _med(c, cid, 3, "2026-09", "cancelada")                  # cancelada nao conta como enviada
    assert _meses_sem_planilha(c, D(2026, 10, 6)) == ["planilha/carta de 09/2026 não enviada"]
    _med(c, cid, 1, "2026-09", "protocolada", tipo="projeto")   # so' a execucao conta
    assert _meses_sem_planilha(c, D(2026, 10, 6)) == ["planilha/carta de 09/2026 não enviada"]


def test_planilha_nao_enviada_fora_da_obra_paralisada_da_mtpar_e_inativa(motor):
    c, u, cid = motor
    _med(c, cid, 1, "2026-06", "protocolada")
    c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) VALUES (?, 'par-1', 'paralisacao', "
              "'2026-07-20', '{}')", (cid,)); c.commit()
    assert _meses_sem_planilha(c, D(2026, 11, 8)) == []
    # reiniciada: desde o mes do reinicio, e os meses parados nao avisam
    c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) VALUES (?, 'rei-1', 'reinicio', "
              "'2026-10-10', '{}')", (cid,)); c.commit()
    assert _meses_sem_planilha(c, D(2026, 11, 8)) == ["planilha/carta de 10/2026 não enviada"]
    c.execute("UPDATE contratos SET orgao_id=(SELECT id FROM orgaos WHERE chave='mtpar')"); c.commit()
    assert _meses_sem_planilha(c, D(2026, 11, 8)) == []
    c.execute("UPDATE contratos SET orgao_id=(SELECT id FROM orgaos WHERE chave='sinfra-x'), estado='encerrado'")
    c.commit()
    assert _meses_sem_planilha(c, D(2026, 11, 8)) == []


def test_obra_so_de_projeto_conta_a_serie_de_projeto(motor):
    # revisor (rodada 1 da PR #582): sem execucao, a obra segue a serie de projeto (medicoes.resumo, #154)
    c, u, cid = motor
    for numero, mes in enumerate(("2026-06", "2026-07", "2026-08", "2026-09"), start=1):
        _med(c, cid, numero, mes, "recebida", tipo="projeto")
    assert _meses_sem_planilha(c, D(2026, 11, 8)) == ["planilha/carta de 10/2026 não enviada"]
    _med(c, cid, 5, "2026-10", "planilha_enviada", tipo="projeto", enviada_em="2026-11-03")
    assert _meses_sem_planilha(c, D(2026, 11, 8)) == []


def test_planilha_nao_enviada_para_no_fim_da_execucao(motor):
    # code-review: depois do fim da execucao (vigente) nao ha' competencia de execucao a medir
    c, u, cid = motor
    _med(c, cid, 1, "2026-06", "protocolada")
    c.execute("UPDATE contratos SET execucao_fim='2026-08-12' WHERE id=?", (cid,)); c.commit()
    assert _meses_sem_planilha(c, D(2026, 11, 8)) == ["planilha/carta de 07/2026 não enviada",
                                                      "planilha/carta de 08/2026 não enviada"]


def test_pedido_sem_boletim_x_para_a_operacao_2x_para_a_diretoria_e_some_com_o_boletim(motor):
    c, u, cid = motor
    _med(c, cid, 1, "2026-10", "protocolada")        # sem aviso de planilha do mes no caminho
    mid = _med(c, cid, 2, "2026-10", "planilha_enviada", pedido=10_000_01, enviada_em="2026-10-20")
    assert _do_tipo(c, "pedido_sem_boletim", D(2026, 11, 4)) == []           # 15 dias: ainda no prazo
    [a] = _do_tipo(c, "pedido_sem_boletim", D(2026, 11, 5))
    assert (a["medicao_id"], a["nivel"], a["publico"], a["dias"], a["data"], a["sentido"]) == (
        mid, "atencao", ["operacao"], 16, "2026-10-20", "desde")
    assert a["mensagem"] == "2ª Medição: pedido enviado há 16 dias sem boletim do órgão (prazo de 15 dias)"
    assert a["valor_centavos"] == 10_000_01
    assert _do_tipo(c, "pedido_sem_boletim", D(2026, 11, 19), "diretoria") == []    # 30 dias = 2X: ainda nao
    [d] = _do_tipo(c, "pedido_sem_boletim", D(2026, 11, 20), "diretoria")
    assert (d["publico"], d["nivel"]) == (["operacao", "diretoria"], "acao")
    medicoes.registrar_boletim(c, u["id"], mid, {"valor_centavos": 10_000_01, "data": "2026-11-06",
                                                 "numero_orgao": "SMO 1"}, {"arquivo": "boletins/a.pdf", "sha256": "a" * 64})
    assert _do_tipo(c, "pedido_sem_boletim", D(2026, 11, 20), "todos") == []


def test_orgao_sem_prazo_boletim_dias_nao_avisa_pedido_sem_boletim(motor):
    c, u, cid = motor
    _med(c, cid, 1, "2026-06", "planilha_enviada", pedido=100, enviada_em="2026-07-01")
    assert len(_do_tipo(c, "pedido_sem_boletim", D(2026, 11, 8))) == 1
    for chave in ("sem-prazo", "mtpar"):
        c.execute("UPDATE contratos SET orgao_id=(SELECT id FROM orgaos WHERE chave=?)", (chave,)); c.commit()
        assert _do_tipo(c, "pedido_sem_boletim", D(2026, 11, 8), "todos") == []


def _bol(c, u, mid, valor, sha, data="2026-11-02"):
    return medicoes.registrar_boletim(c, u["id"], mid, {"valor_centavos": valor, "data": data, "numero_orgao": f"SMO {sha}"},
                                      {"arquivo": f"boletins/{sha}.pdf", "sha256": sha * 64})


def test_aprovado_abaixo_do_pedido_operacao_sempre_diretoria_acima_de_10_por_cento(motor):
    c, u, cid = motor
    mid = _med(c, cid, 1, "2026-10", "planilha_enviada", pedido=10_000_01, enviada_em="2026-10-30")
    _bol(c, u, mid, 9_000_01, "a")               # diferenca de 1.000,00 = 9,99990% do pedido (centavo impar)
    [a] = _do_tipo(c, "aprovado_abaixo_do_pedido", D(2026, 11, 8))
    assert (a["medicao_id"], a["nivel"], a["publico"], a["valor_centavos"], a["data"]) == (
        mid, "acao", ["operacao"], 1_000_00, "2026-11-02")
    assert a["mensagem"] == "1ª Medição: aprovado R$ 9.000,01, abaixo do pedido de R$ 10.000,01 (diferença de R$ 1.000,00)"
    _bol(c, u, mid, 9_000_00, "b")               # 1.000,01: acima de 10%
    [d] = _do_tipo(c, "aprovado_abaixo_do_pedido", D(2026, 11, 8), "diretoria")
    assert d["publico"] == ["operacao", "diretoria"]
    _bol(c, u, mid, 10_000_01, "c")              # boletim novo igual ao pedido: some
    assert _do_tipo(c, "aprovado_abaixo_do_pedido", D(2026, 11, 8), "todos") == []
    _bol(c, u, mid, 10_500_00, "d")              # acima do pedido nao avisa
    assert _do_tipo(c, "aprovado_abaixo_do_pedido", D(2026, 11, 8), "todos") == []


def test_aceitar_a_diferenca_tira_o_aviso_ate_o_proximo_boletim_abaixo(motor):
    c, u, cid = motor
    mid = _med(c, cid, 1, "2026-10", "planilha_enviada", pedido=10_000_01, enviada_em="2026-10-30")
    with pytest.raises(ValueError, match="boletim do órgão"):
        medicoes.aceitar_diferenca(c, u["id"], mid, "glosa de itens não executados")
    _bol(c, u, mid, 8_000_00, "a")
    with pytest.raises(ValueError, match="justificativa"):
        medicoes.aceitar_diferenca(c, u["id"], mid, "   curta ")
    medicoes.aceitar_diferenca(c, u["id"], mid, "  glosa de itens não executados  ")
    assert _do_tipo(c, "aprovado_abaixo_do_pedido", D(2026, 11, 8), "todos") == []
    aceite = medicoes.detalhe(c, mid)["diferenca_aceita"]
    assert (aceite["justificativa"], aceite["diferenca_centavos"], aceite["usuario"]) == (
        "glosa de itens não executados", -2_000_01, "U")
    with pytest.raises(ValueError, match="já foi aceita"):
        medicoes.aceitar_diferenca(c, u["id"], mid, "de novo, clique duplo")
    textos = [e["texto"] for e in medicoes.edicoes_valor(c, [mid])[mid]]
    assert "Diferença de R$ 2.000,01 abaixo do pedido aceita: glosa de itens não executados por U" in textos
    acao = c.execute("SELECT acao FROM audit_log WHERE entidade='medicao' AND entidade_id=? ORDER BY id DESC LIMIT 1",
                     (str(mid),)).fetchone()[0]
    assert acao == "medicao.diferenca_aceita"
    # boletim novo (glosa) ainda abaixo: o aviso volta, e a aceitacao antiga nao vale para ele
    _bol(c, u, mid, 7_000_00, "b")
    assert len(_do_tipo(c, "aprovado_abaixo_do_pedido", D(2026, 11, 8))) == 1
    assert medicoes.detalhe(c, mid)["diferenca_aceita"] is None
    # sem diferenca nao ha' o que aceitar
    _bol(c, u, mid, 10_000_01, "c")
    with pytest.raises(ValueError, match="não está abaixo do pedido"):
        medicoes.aceitar_diferenca(c, u["id"], mid, "glosa de itens não executados")


def test_aceite_vale_so_para_o_pedido_de_quando_foi_aceito(motor):
    # code-review: o pedido que muda depois (prevista do fluxo antigo que recebe o valor do espelho) e' diferenca nova
    c, u, cid = motor
    mid = _med(c, cid, 1, "2026-10", "planilha_enviada", pedido=10_000_01, enviada_em="2026-10-30")
    _bol(c, u, mid, 9_900_00, "a")
    medicoes.aceitar_diferenca(c, u["id"], mid, "glosa pequena de itens")
    c.execute("UPDATE medicoes SET valor_protocolado_centavos=60_000_00 WHERE id=?", (mid,)); c.commit()
    assert medicoes.detalhe(c, mid)["diferenca_aceita"] is None
    [a] = _do_tipo(c, "aprovado_abaixo_do_pedido", D(2026, 11, 8), "diretoria")
    assert a["valor_centavos"] == 50_100_00
    medicoes.aceitar_diferenca(c, u["id"], mid, "pedido novo também conferido")
    assert _do_tipo(c, "aprovado_abaixo_do_pedido", D(2026, 11, 8), "todos") == []


def test_diferenca_aceita_e_evento_que_nao_se_altera_nem_se_apaga(motor):
    import sqlite3
    c, u, cid = motor
    mid = _med(c, cid, 1, "2026-10", "planilha_enviada", pedido=10_000_01, enviada_em="2026-10-30")
    _bol(c, u, mid, 8_000_00, "a")
    medicoes.aceitar_diferenca(c, u["id"], mid, "glosa de itens não executados")
    for sql in ("UPDATE medicao_diferencas_aceitas SET justificativa='x'", "DELETE FROM medicao_diferencas_aceitas"):
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(sql)
    c.rollback()


def test_medicao_fora_de_ordem_enquanto_a_planilha_esta_gerada_ou_enviada(motor):
    c, u, cid = motor
    _med(c, cid, 1, "2026-09", "protocolada", inicio="2026-09-01", fim="2026-09-30")
    m2 = _med(c, cid, 2, "2026-10", "planilha_gerada", pedido=100, inicio="2026-10-03", fim="2026-10-31")
    [a] = _do_tipo(c, "medicao_fora_de_ordem", D(2026, 11, 8))
    assert (a["medicao_id"], a["nivel"], a["publico"]) == (m2, "atencao", ["operacao"])
    assert a["mensagem"] == "2ª Medição: o período pula dias (a 1ª medição terminou em 30/09/2026 e esta começa em 03/10/2026)"
    # sobreposicao, ja' com a planilha enviada
    c.execute("UPDATE medicoes SET periodo_inicio='2026-09-20', estado='planilha_enviada', planilha_enviada_em='2026-11-01' "
              "WHERE id=?", (m2,)); c.commit()
    [a] = _do_tipo(c, "medicao_fora_de_ordem", D(2026, 11, 8))
    assert a["mensagem"] == "2ª Medição: o período se sobrepõe ao da 1ª medição, que vai até 30/09/2026"
    # a revisao enviada depois do envio corrige o periodo (a versao vigente manda, nao a coluna congelada)
    for versao, inicio in ((1, "2026-09-20"), (2, "2026-10-01")):
        c.execute("INSERT INTO medicao_planilhas (medicao_id, versao, periodo_inicio, periodo_fim, valor_pedido_centavos, "
                  "acumulado_anterior_centavos, origem, motivo) VALUES (?,?,?,'2026-10-31',100,0,'manual',?)",
                  (m2, versao, inicio, None if versao == 1 else "Rev01"))
    c.commit()
    assert _do_tipo(c, "medicao_fora_de_ordem", D(2026, 11, 8), "todos") == []
    # com o boletim registrado o aviso some (a revisao nao existe mais)
    c.execute("INSERT INTO medicao_planilhas (medicao_id, versao, periodo_inicio, periodo_fim, valor_pedido_centavos, "
              "acumulado_anterior_centavos, origem, motivo) VALUES (?,3,'2026-10-05','2026-10-31',100,0,'manual','Rev02')",
              (m2,)); c.commit()
    assert len(_do_tipo(c, "medicao_fora_de_ordem", D(2026, 11, 8))) == 1
    c.execute("UPDATE medicoes SET estado='boletim_recebido' WHERE id=?", (m2,)); c.commit()
    assert _do_tipo(c, "medicao_fora_de_ordem", D(2026, 11, 8), "todos") == []


def test_periodo_contiguo_ou_anterior_sem_periodo_nao_avisa_fora_de_ordem(motor):
    c, u, cid = motor
    m1 = _med(c, cid, 1, "2026-09", "protocolada")                               # historico sem periodo
    _med(c, cid, 2, "2026-10", "planilha_gerada", pedido=100, inicio="2026-10-03", fim="2026-10-31")
    assert _do_tipo(c, "medicao_fora_de_ordem", D(2026, 11, 8)) == []
    c.execute("UPDATE medicoes SET periodo_inicio='2026-09-01', periodo_fim='2026-10-02' WHERE id=?", (m1,)); c.commit()
    assert _do_tipo(c, "medicao_fora_de_ordem", D(2026, 11, 8)) == []
