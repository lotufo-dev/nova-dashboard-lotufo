"""Leituras do monitor do SIGA (issue #327): derivacoes, gravacao idempotente, vinculo por numero igual e atraso.

Processos, setores e pessoas sao ficticios (repositorio publico): "Fulano", "Beltrano", "Sicrana"."""
import datetime
import subprocess
from types import SimpleNamespace

import pytest

from app import auth, db, siga, tempo

UTC = datetime.timezone.utc
CUIABA = datetime.timezone(datetime.timedelta(hours=-4))


@pytest.fixture(autouse=True)
def relogio(monkeypatch):
    """Agora = quarta-feira, 28/10/2026, 16h em Cuiaba: as leituras dos testes nao ficam no futuro."""
    monkeypatch.setattr(tempo, "agora_utc", lambda: datetime.datetime(2026, 10, 28, 20, 0, tzinfo=UTC))


def _mov(data, evento, at_lotacao="", at_pessoa="", cad_lotacao="", cad_pessoa=""):
    return {"data": data, "evento": evento, "cad_lotacao": cad_lotacao, "cad_pessoa": cad_pessoa,
            "at_lotacao": at_lotacao, "at_pessoa": at_pessoa}


# --- derivacoes -------------------------------------------------------------------------------------------

SITUACAO_COFIN = "1º Volume - Arquivado [PROTOC, [Y]] | 2º Volume - Aguardando Andamento [COFIN, [X]]"
MOVS = [
    _mov("2026-10-01 08:10:00", "Cadastro", at_lotacao="PROTOC/ORGAO", at_pessoa="Beltrano"),
    _mov("2026-10-02 09:00:00", "Transferência", at_lotacao="COFIN/ORGAO"),
    _mov("2026-10-19 10:00:00", "Recebimento", at_lotacao="COFIN/ORGAO", at_pessoa="Fulano"),
    _mov("2026-10-28 09:30:00", "Despacho", at_lotacao="COFIN/ORGAO", at_pessoa="Fulano"),
    _mov("2026-10-28 10:00:00", "Recebimento Cancelado", at_lotacao="COFIN/ORGAO", at_pessoa="Sicrana"),
]


def test_derivacoes_do_processo_com_recebimento_no_setor():
    d = siga.derivar(SITUACAO_COFIN, MOVS, datetime.date(2026, 10, 28))
    assert d["setor"] == "COFIN"                 # ultimo volume, primeiro nome entre colchetes
    assert d["caixa_entrada"] is False
    assert d["com_quem"] == "Fulano"             # o Recebimento cancelado (Sicrana) nao conta
    assert d["desde"] == "2026-10-19 10:00:00"
    assert d["dias_uteis"] == 7                  # 19, 20, 21, 22, 23, 26 e 27/10
    assert d["hoje"] == 1                        # o cancelado de hoje tambem nao conta
    assert d["ultima"]["evento"] == "Despacho"
    assert d["protocolado_em"] == "2026-10-01 08:10:00"


def test_dias_uteis_descontam_o_feriado_nacional():
    # 05/10 a 13/10/2026: 7 dias de semana, mas 12/10 e' feriado nacional
    movs = [_mov("2026-10-05 10:00:00", "Recebimento", at_lotacao="COFIN/ORGAO", at_pessoa="Fulano")]
    d = siga.derivar("2º Volume - Aguardando Andamento [COFIN, [X]]", movs, datetime.date(2026, 10, 14))
    assert d["dias_uteis"] == 6


def test_caixa_de_entrada_conta_desde_a_ultima_transferencia():
    situacao = "1º Volume - Caixa de Entrada [COFIN, [X]]"
    movs = [_mov("2026-10-01 08:00:00", "Cadastro", at_lotacao="PROTOC/ORGAO"),
            _mov("2026-10-20 08:00:00", "Transferência", at_lotacao="COFIN/ORGAO"),
            _mov("2026-10-21 08:00:00", "Transferência Cancelada", at_lotacao="COFIN/ORGAO")]
    d = siga.derivar(situacao, movs, datetime.date(2026, 10, 22))
    assert d["caixa_entrada"] is True and d["setor"] == "COFIN" and d["com_quem"] == ""
    assert d["desde"] == "2026-10-20 08:00:00" and d["dias_uteis"] == 2


def test_caixa_de_entrada_ignora_recebimento_antigo_no_mesmo_setor():
    # recebido no COFIN em 01/10, foi ao GABIN, voltou ao COFIN por Transferencia em 26/10 e ninguem recebeu ainda
    situacao = "2º Volume - Caixa de Entrada [COFIN, [X]]"
    movs = [_mov("2026-10-01 09:00:00", "Recebimento", at_lotacao="COFIN/ORGAO", at_pessoa="Fulano"),
            _mov("2026-10-10 09:00:00", "Transferência", at_lotacao="GABIN/ORGAO"),
            _mov("2026-10-13 09:00:00", "Recebimento", at_lotacao="GABIN/ORGAO", at_pessoa="Beltrano"),
            _mov("2026-10-26 09:00:00", "Transferência", at_lotacao="COFIN/ORGAO")]
    d = siga.derivar(situacao, movs, datetime.date(2026, 10, 28))
    assert (d["com_quem"], d["desde"], d["dias_uteis"]) == ("", "2026-10-26 09:00:00", 2)


def test_caixa_de_entrada_sem_transferencia_conta_da_movimentacao_mais_recente():
    movs = [_mov("2026-10-01 09:00:00", "Cadastro", at_lotacao="COFIN/ORGAO"),
            _mov("2026-10-26 09:00:00", "Despacho", at_lotacao="COFIN/ORGAO")]
    d = siga.derivar("1º Volume - Caixa de Entrada [COFIN, [X]]", movs, datetime.date(2026, 10, 28))
    assert d["desde"] == "2026-10-26 09:00:00" and d["protocolado_em"] == "2026-10-01 09:00:00"


def test_recebimento_casa_a_sigla_inteira_do_setor():
    movs = [_mov("2026-10-01 09:00:00", "Cadastro", at_lotacao="PROTOC/ORGAO"),
            _mov("2026-10-20 09:00:00", "Recebimento", at_lotacao="GABIN/ORGAO", at_pessoa="Beltrano")]
    d = siga.derivar("1º Volume - Aguardando Andamento [GAB, [X]]", movs, datetime.date(2026, 10, 28))
    assert d["setor"] == "GAB" and d["com_quem"] == "" and d["desde"] == "2026-10-01 09:00:00"
    d = siga.derivar("1º Volume - Aguardando Andamento [GABIN, [X]]", movs, datetime.date(2026, 10, 28))
    assert d["com_quem"] == "Beltrano"


def test_sem_recebimento_no_setor_conta_desde_a_movimentacao_mais_antiga():
    movs = [_mov("2026-10-02 08:00:00", "Recebimento", at_lotacao="PROTOC/ORGAO", at_pessoa="Beltrano"),
            _mov("2026-10-01 08:00:00", "Cadastro", at_lotacao="PROTOC/ORGAO")]
    d = siga.derivar("1º Volume - Aguardando Andamento [GABIN, [X]]", movs, datetime.date(2026, 10, 2))
    assert d["setor"] == "GABIN" and d["com_quem"] == ""
    assert d["desde"] == "2026-10-01 08:00:00" and d["dias_uteis"] == 1


def test_processo_sem_movimentacao_nao_quebra():
    d = siga.derivar(None, [], datetime.date(2026, 10, 2))
    assert d == {"setor": "", "caixa_entrada": False, "com_quem": "", "desde": None, "dias_uteis": None,
                 "hoje": 0, "ultima": None, "protocolado_em": None}


# --- atraso -----------------------------------------------------------------------------------------------

def _cuiaba(ano, mes, dia, hora, minuto=0):
    return datetime.datetime(ano, mes, dia, hora, minuto, tzinfo=CUIABA).astimezone(UTC)


def _banco(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def test_atrasado_nos_quatro_casos():
    terca_11h = _cuiaba(2026, 10, 27, 11)
    assert siga.atrasado(_banco(_cuiaba(2026, 10, 27, 8)), terca_11h) is True
    assert siga.atrasado(_banco(_cuiaba(2026, 10, 27, 10)), terca_11h) is False
    assert siga.atrasado(_banco(_cuiaba(2026, 10, 23, 8)), _cuiaba(2026, 10, 25, 11)) is False   # domingo
    assert siga.atrasado(_banco(_cuiaba(2026, 10, 27, 8)), _cuiaba(2026, 10, 27, 18)) is False   # fora do horario
    assert siga.atrasado(_banco(_cuiaba(2026, 10, 9, 8)), _cuiaba(2026, 10, 12, 11)) is False    # feriado nacional
    assert siga.atrasado(None, terca_11h) is False                                               # nunca leu


def test_atraso_conta_das_8h_quando_a_ultima_leitura_e_de_ontem():
    ontem_17h30 = _banco(_cuiaba(2026, 10, 26, 17, 30))
    assert siga.atrasado(ontem_17h30, _cuiaba(2026, 10, 27, 8, 5)) is False      # antes da primeira rodada do dia
    assert siga.atrasado(ontem_17h30, _cuiaba(2026, 10, 27, 10, 1)) is True       # duas horas de janela sem leitura


# --- gravacao e vinculo -----------------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def _leitura(numero="ORGAO-PRO-2026/00010", codigo="ABC123"):
    return [{"codigo": codigo, "numero": numero, "nome": "Processo Alfa", "situacao": SITUACAO_COFIN,
             "movimentacoes": [{**m, "data": _br(m["data"])} for m in MOVS]},
            {"codigo": None, "numero": "ORGAO-PRO-2026/00011", "nome": "Processo Beta",
             "situacao": "1º Volume - Caixa de Entrada [GABIN, [X]]",
             "movimentacoes": [{**_mov("2026-10-20 08:00:00", "Transferência", at_lotacao="GABIN/ORGAO"),
                                "data": "20/10/2026 08:00:00"}]}]


def _br(iso):
    d = datetime.datetime.strptime(iso, "%Y-%m-%d %H:%M:%S")
    return d.strftime("%d/%m/%Y %H:%M:%S")


def _conta(conn, tabela):
    return conn.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]


def test_gravacao_e_idempotente(conn):
    lido = _cuiaba(2026, 10, 28, 11)
    assert siga.gravar_leitura(conn, lido, _leitura()) == {"gravados": 2, "novas_movimentacoes": 6}
    assert siga.gravar_leitura(conn, lido, _leitura()) == {"gravados": 2, "novas_movimentacoes": 0}
    assert _conta(conn, "siga_processos") == 2 and _conta(conn, "siga_leituras") == 2
    assert _conta(conn, "siga_movimentacoes") == 6
    # rodada nova: leitura nova, so' a movimentacao que ainda nao existia
    proc = _leitura()
    proc[1]["movimentacoes"].append({**_mov("", "Recebimento", at_lotacao="GABIN/ORGAO", at_pessoa="Beltrano"),
                                     "data": "28/10/2026 11:05:00"})
    assert siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11, 15), proc)["novas_movimentacoes"] == 1
    assert _conta(conn, "siga_leituras") == 4 and _conta(conn, "siga_movimentacoes") == 7
    assert conn.execute("SELECT data FROM siga_movimentacoes WHERE at_pessoa='Beltrano' AND evento='Recebimento'"
                        ).fetchone()[0] == "2026-10-28 11:05:00"
    assert conn.execute("SELECT lido_em FROM siga_leituras ORDER BY id").fetchone()[0] == "2026-10-28 15:00:00"


def test_processo_e_identificado_pelo_codigo_ou_pelo_numero(conn):
    lido = _cuiaba(2026, 10, 28, 11)
    siga.gravar_leitura(conn, lido, [{"codigo": None, "numero": "ORGAO-PRO-2026/00010", "nome": None,
                                      "situacao": None, "movimentacoes": []}])
    # o mesmo processo, agora com o codigo e o numero escrito de outro jeito: ganha o codigo e o nome
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 12), [
        {"codigo": "ABC123", "numero": "orgao-pro-2026/00010 ", "nome": "Processo Alfa", "situacao": None,
         "movimentacoes": []}])
    # e so' pelo numero, com tabulacao e espaco nao separavel no meio (texto raspado do SIGA)
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 12, 30), [
        {"codigo": None, "numero": "ORGAO-PRO-2026/\t00010", "nome": None, "situacao": None, "movimentacoes": []},
        {"codigo": None, "numero": "ORGAO-PRO-\u00a02026/00010", "nome": None, "situacao": None,
         "movimentacoes": []}])
    # e depois so' pelo codigo
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 13), [
        {"codigo": "ABC123", "numero": None, "nome": "Outro nome", "situacao": None, "movimentacoes": []}])
    assert [tuple(r) for r in conn.execute("SELECT codigo, numero, nome FROM siga_processos")] == [
        ("ABC123", "ORGAO-PRO-2026/00010", "Processo Alfa")]
    assert siga.processos_para_o_robo(conn) == [
        {"codigo": "ABC123", "numero": "ORGAO-PRO-2026/00010", "nome": "Processo Alfa"}]


def test_processo_sem_codigo_e_sem_numero_e_recusado_sem_gravar_nada(conn):
    with pytest.raises(ValueError, match="código ou o número"):
        siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), [
            *_leitura(), {"codigo": "", "numero": "  ", "nome": "x", "situacao": None, "movimentacoes": []}])
    assert _conta(conn, "siga_processos") == 0


def test_leitura_com_data_no_futuro_e_recusada(conn):
    with pytest.raises(ValueError, match="no futuro"):
        siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 16, 11), _leitura())
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 16, 9), _leitura())        # folga de 10 minutos no relogio
    assert _conta(conn, "siga_processos") == 2


def test_data_de_movimentacao_invalida_e_recusada(conn):
    proc = _leitura()
    proc[0]["movimentacoes"][0]["data"] = "31/02/2026 08:00:00"
    with pytest.raises(ValueError, match="Data de movimentação inválida"):
        siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), proc)
    assert _conta(conn, "siga_movimentacoes") == 0


def _protocolo_enviado(conn, numero_orgao):
    uid = auth.criar_usuario(conn, "Engenharia", "engenharia@exemplo.com.br", "senha-forte-123", "engenharia")
    conn.execute("INSERT INTO contratos (id, orgao, numero_instrumento, objeto, valor_original_centavos, nome_curto) "
                 "VALUES (7, 'SINFRA', 'IC 1/2026', 'Obra', 100, 'Obra Alfa')")
    conn.execute("INSERT INTO medicoes (id, contrato_id, numero, tipo, competencia, estado) "
                 "VALUES (31, 7, 3, 'execucao', '2026-09', 'protocolada')")
    pid = conn.execute("INSERT INTO protocolos (contrato_id, etapa, natureza, usuario_id, situacao, numero_orgao) "
                       "VALUES (7, 'unico', 'execucao', ?, 'enviado', ?)", (uid, numero_orgao)).lastrowid
    conn.execute("INSERT INTO protocolo_medicoes (protocolo_id, medicao_id) VALUES (?, 31)", (pid,))
    conn.commit()
    return pid


def _vinculo(conn):
    return tuple(conn.execute("SELECT contrato_id, protocolo_id, medicao_id FROM siga_processos "
                              "WHERE codigo='ABC123'").fetchone())


def test_vincula_ao_protocolo_pelo_numero_igual(conn):
    pid = _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), _leitura(numero="sinfra-pro-2026/00001"))
    assert _vinculo(conn) == (7, pid, 31)
    eventos = conn.execute("SELECT usuario_id, entidade, entidade_id FROM audit_log WHERE acao='siga.vinculo'"
                           ).fetchall()
    assert [tuple(e) for e in eventos] == [(None, "medicao", "31")]
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11, 15), _leitura(numero="sinfra-pro-2026/00001"))
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='siga.vinculo'").fetchone()[0] == 1
    painel = siga.painel(conn, _cuiaba(2026, 10, 28, 11, 10))
    p = next(x for x in painel["processos"] if x["codigo"] == "ABC123")
    assert (p["contrato_id"], p["protocolo_id"], p["medicao_id"]) == (7, pid, 31)
    assert p["obra"] == "Obra Alfa" and p["medicao_titulo"] == "3ª Medição"


def test_protocolo_com_duas_medicoes_liga_so_ao_protocolo(conn):
    pid = _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    conn.execute("INSERT INTO medicoes (id, contrato_id, numero, tipo, competencia, estado) "
                 "VALUES (30, 7, 3, 'reajuste', '2026-09', 'protocolada')")
    conn.execute("INSERT INTO protocolo_medicoes (protocolo_id, medicao_id) VALUES (?, 30)", (pid,))
    conn.commit()
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), _leitura(numero="SINFRA-PRO-2026/00001"))
    assert _vinculo(conn) == (7, pid, None)
    eventos = conn.execute("SELECT entidade, entidade_id FROM audit_log WHERE acao='siga.vinculo'").fetchall()
    assert [tuple(e) for e in eventos] == [("protocolo", str(pid))]
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11, 15), _leitura(numero="SINFRA-PRO-2026/00001"))
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='siga.vinculo'").fetchone()[0] == 1


def test_mesmo_numero_em_dois_contratos_nao_vincula(conn):
    pid = _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    conn.execute("INSERT INTO contratos (id, orgao, numero_instrumento, objeto, valor_original_centavos, nome_curto) "
                 "VALUES (8, 'SINFRA', 'IC 2/2026', 'Obra', 100, 'Obra Beta')")
    conn.execute("INSERT INTO medicoes (id, contrato_id, numero, tipo, competencia, estado) "
                 "VALUES (41, 8, 1, 'execucao', '2026-09', 'protocolada')")
    outro = conn.execute("INSERT INTO protocolos (contrato_id, etapa, natureza, usuario_id, situacao, numero_orgao) "
                         "SELECT 8, 'unico', 'execucao', usuario_id, 'enviado', 'SINFRA-PRO-2026/00001' "
                         "FROM protocolos WHERE id=?", (pid,)).lastrowid
    conn.execute("INSERT INTO protocolo_medicoes (protocolo_id, medicao_id) VALUES (?, 41)", (outro,))
    conn.commit()
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), _leitura(numero="SINFRA-PRO-2026/00001"))
    assert _vinculo(conn) == (None, None, None)


def test_mesmo_numero_no_protocolo_e_num_envio_por_fora_de_outra_medicao_liga_so_ao_protocolo(conn):
    _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    conn.execute("INSERT INTO medicoes (id, contrato_id, numero, tipo, competencia, estado) "
                 "VALUES (32, 7, 4, 'execucao', '2026-10', 'protocolada')")
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_processo, origem) "
                 "VALUES (32, '2026-10-20', 'SINFRA-PRO-2026/00001', 'manual')")
    conn.commit()
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), _leitura(numero="SINFRA-PRO-2026/00001"))
    assert _vinculo(conn) == (7, 1, None)     # um protocolo so', mas duas medicoes: so' o protocolo


def test_numero_parecido_nao_vincula(conn):
    _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), _leitura(numero="SINFRA-PRO-2026/00002"))
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 12), _leitura(numero="SINFRA-PRO-2026/000010"))
    assert _vinculo(conn) == (None, None, None)


def test_vincula_ao_envio_registrado_por_fora(conn):
    _protocolo_enviado(conn, None)
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_processo, origem) "
                 "VALUES (31, '2026-10-01', 'SINFRA-PRO-2026/00003', 'manual')")
    conn.commit()
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), _leitura(numero="SINFRA-PRO-2026/00003"))
    assert _vinculo(conn) == (7, None, 31)


def test_vinculo_chega_na_rodada_seguinte_ao_numero_registrado(conn):
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), _leitura(numero="SINFRA-PRO-2026/00001"))
    assert _vinculo(conn) == (None, None, None)
    pid = _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11, 15), _leitura(numero="SINFRA-PRO-2026/00001"))
    assert _vinculo(conn) == (7, pid, 31)


def test_painel_traz_situacao_da_ultima_leitura_e_as_movimentacoes_mais_recentes(conn):
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 8), _leitura())
    proc = _leitura()
    proc[0]["situacao"] = "2º Volume - Caixa de Entrada [GABIN, [X]]"
    proc[0]["movimentacoes"] = [{**_mov("", "Transferência", at_lotacao="GABIN/ORGAO"),
                                 "data": f"{d:02d}/09/2026 08:00:00"} for d in range(1, 31)]
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 9), proc)
    painel = siga.painel(conn, _cuiaba(2026, 10, 28, 11))
    assert painel["lido_em"] == "2026-10-28T13:00:00+00:00" and painel["atrasado"] is False
    p = next(x for x in painel["processos"] if x["codigo"] == "ABC123")
    assert p["situacao"].startswith("2º Volume - Caixa de Entrada") and p["setor"] == "GABIN"
    assert len(p["movimentacoes"]) == 30
    assert p["movimentacoes"][0]["evento"] == "Recebimento Cancelado"      # gravada, aparece; so' nao deriva
    assert p["movimentacoes"][0]["data"] == "2026-10-28T10:00:00-04:00"         # hora de Cuiaba, com o fuso
    assert p["desde"] == "2026-10-02T09:00:00-04:00" and p["protocolado_em"] == "2026-09-01T08:00:00-04:00"
    assert p["ultima"]["data"] == "2026-10-28T09:30:00-04:00"
    assert p["medicao_id"] is None and p["obra"] is None
    assert set(p) >= {"id", "codigo", "numero", "nome", "contrato_id", "obra", "medicao_id", "medicao_titulo",
                      "protocolo_id", "situacao", "setor", "com_quem", "caixa_entrada", "desde", "dias_uteis",
                      "hoje", "ultima", "protocolado_em", "movimentacoes"}


def test_acompanhar_avulso_normaliza_o_numero_e_le_o_codigo_do_link(conn, monkeypatch):
    # issue #339: o mesmo extrair_codigo da etapa 4; numero gravado sem espacos
    monkeypatch.setenv("DASH_SIGA_LINK_MODELO", "https://siga.exemplo.com.br/acompanhar?n={codigo}")
    pid = siga.acompanhar_avulso(conn, None, "https://siga.exemplo.com.br/acompanhar?n=AbCdEf1234",
                                 " ORGAO-PRO-2026/ 00009 ", "  Aditivo  ", None)
    p = conn.execute("SELECT codigo, numero, nome, contrato_id FROM siga_processos WHERE id=?", (pid,)).fetchone()
    assert tuple(p) == ("AbCdEf1234", "ORGAO-PRO-2026/00009", "Aditivo", None)
    with pytest.raises(siga.JaAcompanhado) as e:
        siga.acompanhar_avulso(conn, None, "AbCdEf1234", None, "Outro", None)
    assert e.value.nome == "Aditivo"
    with pytest.raises(ValueError, match="Dê um nome"):
        siga.acompanhar_avulso(conn, None, "XyZ98765", None, "", None)


# --- pedidos de leitura e rodadas do robo (issue #342) -------------------------------------------------------

AGORA = _cuiaba(2026, 10, 28, 10)          # quarta-feira, 10h em Cuiaba
TAREFA = "Robo SIGA de teste"


def _min(minutos, segundos=0):
    return datetime.timedelta(minutes=minutos, seconds=segundos)


@pytest.fixture
def robo(conn, monkeypatch):
    """Tres processos acompanhados, uma pessoa que pede e o `schtasks` trocado por um duble."""
    uid = auth.criar_usuario(conn, "Engenharia", "engenharia@exemplo.com.br", "senha-forte-123", "engenharia")
    with db.mutacao(conn):
        ids = [conn.execute("INSERT INTO siga_processos (codigo, numero, nome) VALUES (?,?,?)", p).lastrowid
               for p in (("ABC123", "ORGAO-PRO-2026/00010", "Processo Alfa"), ("DEF456", None, "Processo Beta"),
                         (None, "ORGAO-PRO-2026/00012", "Processo Gama"))]
    chamadas, resposta = [], {"codigo": 0, "saida": b"", "erro": b"", "estoura": False}

    def schtasks(args, **kw):
        chamadas.append((args, kw))
        if resposta["estoura"]:
            raise subprocess.TimeoutExpired(args, kw.get("timeout"))
        return subprocess.CompletedProcess(args, resposta["codigo"], resposta["saida"], resposta["erro"])

    monkeypatch.setattr(siga.subprocess, "run", schtasks)
    return SimpleNamespace(uid=uid, ids=ids, chamadas=chamadas, resposta=resposta)


def _pedir(conn, robo, processo_id, agora):
    return siga.pedir_leitura(conn, robo.uid, processo_id, TAREFA, agora)


def _textos(conn, agora):
    return [a["texto"] for a in siga.situacao_robo(conn, agora)["avisos"]]


def test_disparo_roda_o_schtasks_sem_shell_com_o_nome_da_tarefa_e_prazo(robo):
    assert siga.disparar_robo(TAREFA) is None
    ((args, kw),) = robo.chamadas
    assert args[0].lower().endswith("schtasks.exe") and args[1:] == ["/Run", "/TN", TAREFA]
    assert kw["timeout"] == 15 and not kw.get("shell")


def test_disparo_recusado_devolve_a_saida_cortada_ou_o_prazo(robo):
    robo.resposta.update(codigo=1, erro=b"ERRO: " + b"x" * 400)
    motivo = siga.disparar_robo(TAREFA)
    assert motivo.startswith("ERRO: x") and len(motivo) == 300
    robo.resposta.update(codigo=1, erro=b"", saida=b"")
    assert siga.disparar_robo(TAREFA) == "código de saída 1"
    robo.resposta.update(estoura=True)
    assert siga.disparar_robo(TAREFA) == "sem resposta em 15 segundos"


def test_saida_do_schtasks_em_utf8_ou_na_pagina_do_console(robo):
    # com o console em UTF-8 o schtasks escreve UTF-8; sem ele, na pagina OEM (cp850 em portugues)
    robo.resposta.update(codigo=1, erro="ERRO: O sistema não pode encontrar o arquivo especificado.".encode())
    assert siga.disparar_robo(TAREFA) == "ERRO: O sistema não pode encontrar o arquivo especificado."
    robo.resposta.update(codigo=1, erro=b"ERRO: O sistema n\xc6o pode encontrar o arquivo especificado.")
    assert siga.disparar_robo(TAREFA).startswith("ERRO: O sistema n")


def test_sem_rodada_completa_terminada_a_rodada_e_completa_e_automatica(conn, robo):
    r = siga.iniciar_rodada(conn, AGORA)
    assert r["rodada_id"] is not None and r["tipo"] == "automatica"
    assert r["processos"] == [{"codigo": "ABC123", "numero": "ORGAO-PRO-2026/00010", "nome": "Processo Alfa"},
                              {"codigo": "DEF456", "numero": None, "nome": "Processo Beta"},
                              {"codigo": None, "numero": "ORGAO-PRO-2026/00012", "nome": "Processo Gama"}]


def test_rodada_completa_por_tempo_aos_14_minutos_da_ultima_completa(conn, robo):
    r = siga.iniciar_rodada(conn, AGORA)
    siga.terminar_rodada(conn, r["rodada_id"], [], AGORA + _min(3))
    # 13 minutos depois, sem pedido: nada a ler, e nada gravado
    assert siga.iniciar_rodada(conn, AGORA + _min(13)) == {"rodada_id": None, "tipo": None, "processos": []}
    assert _conta(conn, "siga_rodadas") == 1
    # com o pedido de um processo, so' ele
    _pedir(conn, robo, robo.ids[1], AGORA + _min(13))
    r2 = siga.iniciar_rodada(conn, AGORA + _min(13))
    assert r2["tipo"] == "pedido" and [p["codigo"] for p in r2["processos"]] == ["DEF456"]
    siga.terminar_rodada(conn, r2["rodada_id"], [], AGORA + _min(13, 30))
    # 14 minutos depois do inicio da ultima completa (a rodada automatica de 15 em 15 minutos), todos
    r3 = siga.iniciar_rodada(conn, AGORA + _min(14))
    assert r3["tipo"] == "automatica" and len(r3["processos"]) == 3


def test_pedido_todos_faz_rodada_completa_do_tipo_pedido_e_liga_os_pedidos(conn, robo):
    r = siga.iniciar_rodada(conn, AGORA)
    siga.terminar_rodada(conn, r["rodada_id"], [], AGORA + _min(2))
    um = _pedir(conn, robo, robo.ids[0], AGORA + _min(5))
    todos = _pedir(conn, robo, None, AGORA + _min(5))
    assert todos["id"] != um["id"] and todos["processo_id"] is None
    r2 = siga.iniciar_rodada(conn, AGORA + _min(6))
    assert r2["tipo"] == "pedido" and len(r2["processos"]) == 3
    assert {x[0] for x in conn.execute("SELECT rodada_id FROM siga_pedidos")} == {r2["rodada_id"]}


def test_rodada_de_pedido_le_so_os_processos_pedidos(conn, robo):
    r = siga.iniciar_rodada(conn, AGORA)
    siga.terminar_rodada(conn, r["rodada_id"], [], AGORA + _min(2))
    _pedir(conn, robo, robo.ids[2], AGORA + _min(4))
    _pedir(conn, robo, robo.ids[0], AGORA + _min(5))
    r2 = siga.iniciar_rodada(conn, AGORA + _min(6))
    assert r2["tipo"] == "pedido" and [p["nome"] for p in r2["processos"]] == ["Processo Alfa", "Processo Gama"]
    # pedidos atendidos: o robo pergunta de novo antes de encerrar e nao ha' nada a ler
    siga.terminar_rodada(conn, r2["rodada_id"], [], AGORA + _min(7))
    assert siga.iniciar_rodada(conn, AGORA + _min(7))["rodada_id"] is None


def test_pedido_repetido_nao_duplica_e_todos_cobre_o_de_um_processo(conn, robo):
    a1 = _pedir(conn, robo, robo.ids[0], AGORA)
    a2 = _pedir(conn, robo, robo.ids[0], AGORA + _min(1))
    assert a2["id"] == a1["id"] and a1["novo"] is True and a2["novo"] is False
    todos = _pedir(conn, robo, None, AGORA + _min(1))
    assert todos["id"] != a1["id"] and todos["novo"] is True
    assert _pedir(conn, robo, robo.ids[1], AGORA + _min(2))["id"] == todos["id"]
    assert _pedir(conn, robo, None, AGORA + _min(2))["id"] == todos["id"]
    assert _conta(conn, "siga_pedidos") == 2
    # depois de atendido, o clique seguinte e' pedido novo
    siga.iniciar_rodada(conn, AGORA + _min(3))
    assert _pedir(conn, robo, robo.ids[0], AGORA + _min(4))["novo"] is True


def test_pedido_de_processo_que_nao_existe_e_recusado(conn, robo):
    with pytest.raises(ValueError, match="Processo do SIGA não encontrado"):
        _pedir(conn, robo, 999, AGORA)
    assert _conta(conn, "siga_pedidos") == 0 and robo.chamadas == []


def test_com_rodada_em_andamento_o_pedido_e_gravado_sem_disparar(conn, robo):
    siga.iniciar_rodada(conn, AGORA)
    p = _pedir(conn, robo, robo.ids[0], AGORA + _min(5))
    assert (p["disparado"], p["erro_disparo"]) == (False, None) and robo.chamadas == []
    assert siga.situacao_robo(conn, AGORA + _min(5))["pedidos"][0]["id"] == p["id"]
    assert _pedir(conn, robo, robo.ids[0], AGORA + _min(10))["disparado"] is False and robo.chamadas == []
    # o Windows encerra o robo aos 10 minutos: dai' em diante o clique dispara de novo, mesmo com a tela ainda
    # mostrando "lendo" ate' os 12 (quando a rodada vira "nao terminou")
    p2 = _pedir(conn, robo, robo.ids[0], AGORA + _min(10, 1))
    assert p2["id"] == p["id"] and p2["disparado"] is True and len(robo.chamadas) == 1
    assert siga.situacao_robo(conn, AGORA + _min(10, 1))["estado"] == "lendo"


def test_estado_parado_na_fila_e_lendo(conn, robo):
    s = siga.situacao_robo(conn, AGORA)
    assert s == {"estado": "parado", "rodada": None, "pedidos": [], "avisos": []}
    p = _pedir(conn, robo, robo.ids[0], AGORA)
    s = siga.situacao_robo(conn, AGORA + _min(1))
    assert s["estado"] == "na_fila" and s["rodada"] is None
    assert s["pedidos"] == [{"id": p["id"], "processo_id": robo.ids[0], "usuario": "Engenharia",
                             "pedido_em": "2026-10-28T14:00:00+00:00"}]
    r = siga.iniciar_rodada(conn, AGORA + _min(1))
    s = siga.situacao_robo(conn, AGORA + _min(13))
    assert s["estado"] == "lendo" and s["pedidos"] == []
    assert s["rodada"] == {"id": r["rodada_id"], "tipo": "automatica", "iniciada_em": "2026-10-28T14:01:00+00:00",
                           "processos": robo.ids}
    assert siga.situacao_robo(conn, AGORA + _min(13, 1))["estado"] == "parado"


def test_recusa_do_windows_avisa_ate_o_proximo_disparo_aceito(conn, robo):
    robo.resposta.update(codigo=1, erro="ERRO: acesso negado.\r\n".encode())
    p = _pedir(conn, robo, robo.ids[0], AGORA)
    assert (p["disparado"], p["erro_disparo"]) == (False, "ERRO: acesso negado.")
    assert "O Windows não iniciou o robô: ERRO: acesso negado." in _textos(conn, AGORA)
    # um clique com rodada em andamento nao e' disparo: o aviso continua
    siga.iniciar_rodada(conn, AGORA + _min(1))
    _pedir(conn, robo, robo.ids[1], AGORA + _min(2))
    assert "O Windows não iniciou o robô: ERRO: acesso negado." in _textos(conn, AGORA + _min(2))
    robo.resposta.update(codigo=0, erro=b"")
    _pedir(conn, robo, robo.ids[1], AGORA + _min(14))
    assert not [t for t in _textos(conn, AGORA + _min(14)) if t.startswith("O Windows")]


def test_pedido_parado_ha_mais_de_2_minutos_avisa_que_o_robo_nao_comecou(conn, robo):
    aviso = "O robô não começou. O usuário dele pode estar desconectado do servidor."
    _pedir(conn, robo, robo.ids[0], AGORA)
    assert aviso not in _textos(conn, AGORA + _min(2))
    assert aviso in _textos(conn, AGORA + _min(2, 1))
    siga.iniciar_rodada(conn, AGORA + _min(3))
    assert aviso not in _textos(conn, AGORA + _min(3))
    # pedido feito com o robo lendo espera a rodada terminar: nao e' "nao comecou"
    _pedir(conn, robo, robo.ids[1], AGORA + _min(4))
    assert aviso not in _textos(conn, AGORA + _min(10))


def test_nao_comecou_conta_do_ultimo_disparo_do_pedido(conn, robo):
    aviso = "O robô não começou. O usuário dele pode estar desconectado do servidor."
    robo.resposta.update(codigo=1, erro=b"ERRO: tarefa desabilitada.")
    _pedir(conn, robo, robo.ids[0], AGORA)
    # o Windows recusou: o aviso e' o da recusa, nao o de "aceitou e o robo nao comecou"
    assert _textos(conn, AGORA + _min(5)) == ["O Windows não iniciou o robô: ERRO: tarefa desabilitada."]
    # o mesmo pedido, disparado de novo e aceito: os 2 minutos contam do disparo novo
    robo.resposta.update(codigo=0, erro=b"")
    _pedir(conn, robo, robo.ids[0], AGORA + _min(5))
    assert _textos(conn, AGORA + _min(7)) == []
    assert _textos(conn, AGORA + _min(7, 1)) == [aviso]


def test_nao_comecou_conta_do_fim_da_rodada_que_segurou_o_pedido(conn, robo):
    aviso = "O robô não começou. O usuário dele pode estar desconectado do servidor."
    r = siga.iniciar_rodada(conn, AGORA)
    _pedir(conn, robo, robo.ids[0], AGORA + _min(1))                     # com o robo lendo: nao dispara
    siga.terminar_rodada(conn, r["rodada_id"], [], AGORA + _min(6))      # e ele encerrou sem perguntar de novo
    assert aviso not in _textos(conn, AGORA + _min(8))
    assert aviso in _textos(conn, AGORA + _min(8, 1))
    # rodada que morreu sem avisar: conta de quando ela deixou de estar em andamento (12 minutos)
    _pedir(conn, robo, robo.ids[0], AGORA + _min(9))
    siga.iniciar_rodada(conn, AGORA + _min(9))
    _pedir(conn, robo, robo.ids[1], AGORA + _min(10))
    assert aviso not in _textos(conn, AGORA + _min(23))
    assert aviso in _textos(conn, AGORA + _min(23, 1))


def test_disparo_mais_antigo_que_responde_depois_nao_apaga_o_aceito(conn, robo):
    _pedir(conn, robo, robo.ids[0], AGORA + _min(1))                     # aceito
    robo.resposta.update(estoura=True)
    # um clique anterior, preso no schtasks, responde depois do aceito
    assert _pedir(conn, robo, robo.ids[0], AGORA)["erro_disparo"] == "sem resposta em 15 segundos"
    assert _textos(conn, AGORA + _min(1)) == []


def test_falha_avisa_ate_a_proxima_rodada_terminar_sem_falha(conn, robo):
    r = siga.iniciar_rodada(conn, AGORA)
    siga.falhar_rodada(conn, r["rodada_id"], "O SIGA não abriu", AGORA + _min(1))
    assert _textos(conn, AGORA + _min(1)) == ["A rodada das 10:00 falhou: O SIGA não abriu"]
    _pedir(conn, robo, robo.ids[0], AGORA + _min(5))
    r2 = siga.iniciar_rodada(conn, AGORA + _min(5))
    assert _textos(conn, AGORA + _min(6)) == ["A rodada das 10:00 falhou: O SIGA não abriu"]   # ainda lendo
    siga.terminar_rodada(conn, r2["rodada_id"], [], AGORA + _min(6))
    assert _textos(conn, AGORA + _min(6)) == []


def test_nao_lidos_avisam_por_processo_com_o_resumo_ate_a_proxima_rodada_sem_eles(conn, robo):
    r = siga.iniciar_rodada(conn, AGORA)
    siga.terminar_rodada(conn, r["rodada_id"], [
        {"codigo": "DEF456", "numero": None, "motivo": "A página do processo não abriu"},
        {"codigo": None, "numero": "ORGAO-PRO-2026/ 00012", "motivo": "Processo sem código"}], AGORA + _min(3))
    assert siga.situacao_robo(conn, AGORA + _min(3))["avisos"] == [
        {"tipo": "nao_lido", "processo_id": robo.ids[1], "texto": "não lido às 10:00: A página do processo não abriu"},
        {"tipo": "nao_lido", "processo_id": robo.ids[2], "texto": "não lido às 10:00: Processo sem código"},
        {"tipo": "nao_lidos", "processo_id": None, "texto": "2 de 3 processos não foram lidos"}]
    _pedir(conn, robo, robo.ids[1], AGORA + _min(5))
    r2 = siga.iniciar_rodada(conn, AGORA + _min(5))
    siga.terminar_rodada(conn, r2["rodada_id"], [], AGORA + _min(6))
    assert _textos(conn, AGORA + _min(6)) == []


def test_resumo_dos_nao_lidos_conta_cada_processo_da_rodada_uma_vez(conn, robo):
    r = siga.iniciar_rodada(conn, AGORA)
    siga.terminar_rodada(conn, r["rodada_id"], [], AGORA + _min(2))
    _pedir(conn, robo, robo.ids[0], AGORA + _min(3))
    r2 = siga.iniciar_rodada(conn, AGORA + _min(3))
    # o mesmo processo duas vezes e um que nao estava nesta rodada (o robo tambem le a lista dele)
    siga.terminar_rodada(conn, r2["rodada_id"], [
        {"codigo": "ABC123", "numero": None, "motivo": "A página do processo não abriu"},
        {"codigo": None, "numero": "ORGAO-PRO-2026/00010", "motivo": "De novo"},
        {"codigo": "XYZ999", "numero": None, "motivo": "Processo da lista do robô"}], AGORA + _min(4))
    assert siga.situacao_robo(conn, AGORA + _min(4))["avisos"] == [
        {"tipo": "nao_lido", "processo_id": robo.ids[0], "texto": "não lido às 10:03: A página do processo não abriu"},
        {"tipo": "nao_lido", "processo_id": None,
         "texto": "processo XYZ999 não lido às 10:03: Processo da lista do robô"},
        {"tipo": "nao_lidos", "processo_id": None, "texto": "1 de 1 processos não foram lidos"}]


def test_rodada_sem_fim_ha_mais_de_12_minutos_avisa_ate_outra_terminar(conn, robo):
    siga.iniciar_rodada(conn, AGORA)
    assert _textos(conn, AGORA + _min(12)) == []
    assert _textos(conn, AGORA + _min(12, 1)) == ["A rodada das 10:00 não terminou."]
    r2 = siga.iniciar_rodada(conn, AGORA + _min(15))
    assert _textos(conn, AGORA + _min(16)) == ["A rodada das 10:00 não terminou."]   # a seguinte ainda lendo
    siga.terminar_rodada(conn, r2["rodada_id"], [], AGORA + _min(17))
    assert _textos(conn, AGORA + _min(17)) == []


def test_rodadas_sem_fim_seguidas_avisam_so_a_mais_recente(conn, robo):
    siga.iniciar_rodada(conn, AGORA)
    siga.iniciar_rodada(conn, AGORA + _min(15))          # a anterior morreu: rodada nova
    assert _conta(conn, "siga_rodadas") == 2
    assert _textos(conn, AGORA + _min(27, 1)) == ["A rodada das 10:15 não terminou."]


def test_comecei_repetido_com_a_rodada_aberta_devolve_a_mesma_rodada(conn, robo):
    _pedir(conn, robo, robo.ids[0], AGORA)
    r = siga.iniciar_rodada(conn, AGORA)
    _pedir(conn, robo, robo.ids[1], AGORA + _min(1))                     # chega durante a rodada
    assert siga.iniciar_rodada(conn, AGORA + _min(1)) == r                # o robo repetiu o "comecei"
    assert _conta(conn, "siga_rodadas") == 1
    assert [p["processo_id"] for p in siga.situacao_robo(conn, AGORA + _min(1))["pedidos"]] == [robo.ids[1]]
    # passado o limite do Windows (10 minutos), a rodada morreu: o "comecei" abre outra e atende o pedido
    r2 = siga.iniciar_rodada(conn, AGORA + _min(10, 1))
    assert r2["rodada_id"] != r["rodada_id"] and siga.situacao_robo(conn, AGORA + _min(10, 1))["pedidos"] == []


def test_rodada_terminada_nao_aceita_outro_fim_nem_falha(conn, robo):
    r = siga.iniciar_rodada(conn, AGORA)
    siga.terminar_rodada(conn, r["rodada_id"], [], AGORA + _min(2))
    with pytest.raises(siga.RodadaTerminada):
        siga.terminar_rodada(conn, r["rodada_id"], [], AGORA + _min(3))
    with pytest.raises(siga.RodadaTerminada):
        siga.falhar_rodada(conn, r["rodada_id"], "caiu", AGORA + _min(3))
    with pytest.raises(LookupError):
        siga.falhar_rodada(conn, 999, "caiu", AGORA + _min(3))
    r2 = siga.iniciar_rodada(conn, AGORA + _min(20))
    with pytest.raises(ValueError, match="código ou o número"):
        siga.terminar_rodada(conn, r2["rodada_id"], [{"codigo": " ", "numero": None, "motivo": "x"}], AGORA + _min(21))
    assert conn.execute("SELECT terminada_em FROM siga_rodadas WHERE id=?", (r2["rodada_id"],)).fetchone()[0] is None
