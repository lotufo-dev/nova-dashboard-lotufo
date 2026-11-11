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
    assert d["desde"] == "2026-10-02 09:00:00"   # a Transferencia que o levou ao setor, nao o Recebimento (#650)
    assert d["dias_uteis"] == 17                 # 02/10 a 27/10, sem o feriado de 12/10
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


# issue #650: "No setor ha'" conta da entrada no setor atual; Marcacao e Anotacao nao sao a ultima movimentacao
SITUACAO_GABIN = "1º Volume - Aguardando Andamento [GABIN, [X]]"


def test_varios_recebimentos_no_mesmo_setor_contam_da_primeira_entrada():
    movs = [_mov("2026-10-01 08:00:00", "Cadastro", at_lotacao="PROTOC/ORGAO"),
            _mov("2026-10-05 09:00:00", "Transferência", at_lotacao="GABIN/ORGAO"),
            _mov("2026-10-06 09:00:00", "Recebimento", at_lotacao="GABIN/ORGAO", at_pessoa="Fulano"),
            _mov("2026-10-20 09:00:00", "Recebimento", at_lotacao="GABIN/ORGAO", at_pessoa="Beltrano"),
            _mov("2026-10-26 09:00:00", "Recebimento", at_lotacao="GABIN/ORGAO", at_pessoa="Sicrana")]
    d = siga.derivar(SITUACAO_GABIN, movs, datetime.date(2026, 10, 28))
    assert d["desde"] == "2026-10-05 09:00:00"   # a Transferencia que o levou ao setor
    assert d["dias_uteis"] == 16                 # 05/10 a 27/10, sem o feriado de 12/10
    assert d["com_quem"] == "Sicrana"            # quem recebeu por ultimo
    # sem a Transferencia gravada, vale o primeiro Recebimento da permanencia
    d = siga.derivar(SITUACAO_GABIN, [movs[0], *movs[2:]], datetime.date(2026, 10, 28))
    assert d["desde"] == "2026-10-06 09:00:00" and d["dias_uteis"] == 15


def test_processo_que_saiu_e_voltou_ao_setor_conta_da_volta():
    movs = [_mov("2026-10-01 09:00:00", "Recebimento", at_lotacao="GABIN/ORGAO", at_pessoa="Fulano"),
            _mov("2026-10-08 09:00:00", "Transferência", at_lotacao="COFIN/ORGAO"),
            _mov("2026-10-09 09:00:00", "Recebimento", at_lotacao="COFIN/ORGAO", at_pessoa="Beltrano"),
            _mov("2026-10-21 09:00:00", "Transferência", at_lotacao="GABIN/ORGAO"),
            _mov("2026-10-22 09:00:00", "Recebimento", at_lotacao="GABIN/ORGAO", at_pessoa="Fulano"),
            _mov("2026-10-26 09:00:00", "Recebimento", at_lotacao="GABIN/ORGAO", at_pessoa="Sicrana")]
    d = siga.derivar(SITUACAO_GABIN, movs, datetime.date(2026, 10, 28))
    assert d["desde"] == "2026-10-21 09:00:00" and d["dias_uteis"] == 5     # 21, 22, 23, 26 e 27/10
    # juntada ou despacho no meio da permanencia nao recomeca a conta
    movs.append(_mov("2026-10-27 09:00:00", "Juntada", at_lotacao="OUTRO/ORGAO"))
    assert siga.derivar(SITUACAO_GABIN, movs, datetime.date(2026, 10, 28))["desde"] == "2026-10-21 09:00:00"


def test_sigla_do_setor_escrita_sem_espaco_nao_quebra_a_permanencia():
    # o SIGA escreve o mesmo setor com e sem espaco ("ALFA I" e "ALFAI"); "ALFA II" e' outro setor
    situacao = "1º Volume - Aguardando Andamento [ALFA I, [X]]"
    movs = [_mov("2026-10-01 08:00:00", "Cadastro", at_lotacao="PROTOC/ORGAO"),
            _mov("2026-10-05 09:00:00", "Transferência", at_lotacao="ALFA I/ORGAO"),
            _mov("2026-10-06 09:00:00", "Recebimento", at_lotacao="ALFA I/ORGAO", at_pessoa="Fulano"),
            _mov("2026-10-13 09:00:00", "Transferência", at_lotacao="ALFA I/ORGAO", cad_lotacao="ALFA I/ORGAO"),
            _mov("2026-10-14 09:00:00", "Recebimento", at_lotacao="ALFA I/ORGAO", at_pessoa="Beltrano"),
            _mov("2026-10-19 09:00:00", "Transferência", at_lotacao="ALFAI/ORGAO", cad_lotacao="ALFA I/ORGAO"),
            _mov("2026-10-20 09:00:00", "Recebimento", at_lotacao="alfai/ORGAO", at_pessoa="Sicrana")]
    d = siga.derivar(situacao, movs, datetime.date(2026, 10, 28))
    assert d["desde"] == "2026-10-05 09:00:00" and d["dias_uteis"] == 16
    assert d["com_quem"] == "Sicrana"            # o recebimento escrito sem espaco tambem e' do setor
    # "ALFA II" continua sendo outro setor: a ida para la' encerra a permanencia
    movs += [_mov("2026-10-21 09:00:00", "Transferência", at_lotacao="ALFA II/ORGAO"),
             _mov("2026-10-23 09:00:00", "Transferência", at_lotacao="ALFA I/ORGAO"),
             _mov("2026-10-26 09:00:00", "Recebimento", at_lotacao="ALFAI/ORGAO", at_pessoa="Fulano")]
    d = siga.derivar(situacao, movs, datetime.date(2026, 10, 28))
    assert (d["desde"], d["dias_uteis"], d["com_quem"]) == ("2026-10-23 09:00:00", 3, "Fulano")


def test_caixa_de_entrada_com_duas_transferencias_ao_setor_conta_da_primeira():
    movs = [_mov("2026-10-01 08:00:00", "Cadastro", at_lotacao="PROTOC/ORGAO"),
            _mov("2026-10-19 08:00:00", "Transferência", at_lotacao="GABIN/ORGAO"),
            _mov("2026-10-23 08:00:00", "Transferência", at_lotacao="GABIN/ORGAO")]
    d = siga.derivar("1º Volume - Caixa de Entrada [GABIN, [X]]", movs, datetime.date(2026, 10, 28))
    assert (d["com_quem"], d["desde"], d["dias_uteis"]) == ("", "2026-10-19 08:00:00", 7)


def test_ultima_movimentacao_nao_e_marcacao_nem_anotacao():
    movs = [_mov("2026-10-01 08:00:00", "Cadastro", at_lotacao="PROTOC/ORGAO"),
            _mov("2026-10-20 09:00:00", "Recebimento", at_lotacao="GABIN/ORGAO", at_pessoa="Fulano"),
            _mov("2026-10-26 09:00:00", "Marcação", at_lotacao="GABIN/ORGAO"),
            _mov("2026-10-27 09:00:00", "Anotação | texto", at_lotacao="GABIN/ORGAO")]
    d = siga.derivar(SITUACAO_GABIN, movs, datetime.date(2026, 10, 28))
    assert d["ultima"]["evento"] == "Recebimento" and d["ultima"]["data"] == "2026-10-20 09:00:00"
    assert d["protocolado_em"] == "2026-10-01 08:00:00"
    so_marcacao = [_mov("2026-10-26 09:00:00", "Marcação", at_lotacao="GABIN/ORGAO")]
    d = siga.derivar(SITUACAO_GABIN, so_marcacao, datetime.date(2026, 10, 28))
    assert d["ultima"] is None and d["protocolado_em"] == "2026-10-26 09:00:00"


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


def _planilha_por_fora(conn):
    """Issue #283: medicao 31 com o nº do SIGA da planilha/carta (111); a nota ainda nao foi protocolada."""
    _protocolo_enviado(conn, None)
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_processo, origem, etapa) "
                 "VALUES (31, '2026-08-03', 'SINFRA-PRO-2026/00111', 'manual', 'planilha')")
    conn.commit()


def _ligados(conn):
    return [tuple(r) for r in conn.execute("SELECT numero, contrato_id, medicao_id FROM siga_processos "
                                           "WHERE codigo IS NOT NULL AND codigo<>'ABC123' ORDER BY id")]


def _leitura_unica(numero, codigo):
    return _leitura(numero=numero, codigo=codigo)[:1]


def test_processo_da_nota_toma_o_lugar_do_processo_da_planilha(conn):
    import json
    _planilha_por_fora(conn)
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 9), _leitura_unica("SINFRA-PRO-2026/00111", "PLA111"))
    assert _ligados(conn) == [("SINFRA-PRO-2026/00111", 7, 31)]
    # a nota protocolada por fora com outro numero
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_processo, origem) "
                 "VALUES (31, '2026-09-15', 'SINFRA-PRO-2026/00222', 'manual')")
    conn.commit()
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), _leitura_unica("SINFRA-PRO-2026/00222", "NOT222"))
    # o da nota liga; o da planilha perde o vinculo e continua gravado, com as leituras
    assert _ligados(conn) == [("SINFRA-PRO-2026/00111", None, None), ("SINFRA-PRO-2026/00222", 7, 31)]
    assert conn.execute("SELECT COUNT(*) FROM siga_leituras l JOIN siga_processos p ON p.id=l.processo_id "
                        "WHERE p.codigo='PLA111'").fetchone()[0] == 1
    troca = conn.execute("SELECT antes, depois FROM audit_log WHERE acao='siga.vinculo' ORDER BY id DESC LIMIT 1"
                         ).fetchone()
    assert json.loads(troca["antes"]) == {"processos_siga_da_planilha": ["SINFRA-PRO-2026/00111"], "medicao_id": 31}
    assert json.loads(troca["depois"])["processo_siga"] == "SINFRA-PRO-2026/00222"
    # a leitura seguinte do processo da planilha nao o liga de volta
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), _leitura_unica("SINFRA-PRO-2026/00111", "PLA111"))
    assert _ligados(conn) == [("SINFRA-PRO-2026/00111", None, None), ("SINFRA-PRO-2026/00222", 7, 31)]
    # o aviso de processo parado da medicao vem do processo da nota
    conn.execute("UPDATE medicoes SET estado='protocolada' WHERE id=31"); conn.commit()
    parados = [a for a in siga.avisos(conn, datetime.date(2026, 11, 10)) if a["tipo"] == "siga_parado"]
    assert [a["medicao_id"] for a in parados] == [31] and "SINFRA-PRO-2026/00222" in parados[0]["mensagem"]


def test_so_o_processo_da_nota_desloca_o_da_planilha(conn):
    # outro processo que casa so' com a planilha (sem nota com o numero dele) nao troca o que ja' esta' ligado
    _planilha_por_fora(conn)
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 9), _leitura_unica("SINFRA-PRO-2026/00111", "PLA111"))
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_processo, origem) "
                 "VALUES (31, '2026-09-15', 'SINFRA-PRO-2026/00222', 'manual')")
    conn.commit()
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), _leitura_unica("SINFRA-PRO-2026/00222", "NOT222"))
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), _leitura_unica("SINFRA-PRO-2026/00222", "OUT222"))
    assert ("SINFRA-PRO-2026/00222", 7, 31) == _ligados(conn)[1]
    assert conn.execute("SELECT medicao_id FROM siga_processos WHERE codigo='OUT222'").fetchone()[0] is None


def test_processo_da_nota_toma_o_lugar_do_da_planilha_com_o_numero_corrigido(conn):
    # o robo ligou o 111; a pessoa corrigiu o nº do SIGA da planilha para 112 (mesma linha) antes de a nota chegar
    _planilha_por_fora(conn)
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 9), _leitura_unica("SINFRA-PRO-2026/00111", "PLA111"))
    conn.execute("UPDATE medicao_protocolos SET numero_processo='SINFRA-PRO-2026/00112' "
                 "WHERE medicao_id=31 AND etapa='planilha'")
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_processo, origem) "
                 "VALUES (31, '2026-09-15', 'SINFRA-PRO-2026/00222', 'manual')")
    conn.commit()
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), _leitura_unica("SINFRA-PRO-2026/00222", "NOT222"))
    assert _ligados(conn) == [("SINFRA-PRO-2026/00111", None, None), ("SINFRA-PRO-2026/00222", 7, 31)]
    conn.execute("UPDATE medicoes SET estado='protocolada' WHERE id=31"); conn.commit()
    parados = [a for a in siga.avisos(conn, datetime.date(2026, 11, 10)) if a["tipo"] == "siga_parado"]
    assert [a["medicao_id"] for a in parados] == [31] and "SINFRA-PRO-2026/00222" in parados[0]["mensagem"]


def test_link_colado_na_medicao_nao_cede_ao_processo_da_nota(conn):
    # o processo que a pessoa ligou colando o link fica: o robo nao o troca pelo numero igual ao da nota
    _planilha_por_fora(conn)
    uid = conn.execute("SELECT id FROM usuarios ORDER BY id LIMIT 1").fetchone()[0]
    with db.mutacao(conn):
        siga.registrar_link_medicao(conn, uid, 31, "LNK111", "SINFRA-PRO-2026/00111")
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_processo, origem) "
                 "VALUES (31, '2026-09-15', 'SINFRA-PRO-2026/00222', 'manual')")
    conn.commit()
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), _leitura_unica("SINFRA-PRO-2026/00222", "NOT222"))
    assert _ligados(conn) == [("SINFRA-PRO-2026/00111", 7, 31), ("SINFRA-PRO-2026/00222", None, None)]


def test_aviso_de_processo_parado_usa_a_data_de_entrada_no_setor(conn):
    # issue #650: o aviso conta os mesmos dias da tela; recebimento ou despacho seguinte no setor nao recomeca
    _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    proc = _leitura(numero="SINFRA-PRO-2026/00001")[:1]
    proc[0]["movimentacoes"] += [
        {**_mov("", "Recebimento", at_lotacao="COFIN/ORGAO", at_pessoa="Sicrana"), "data": "26/10/2026 09:00:00"}]
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), proc)
    hoje = datetime.date(2026, 10, 28)
    p = next(x for x in siga.painel(conn, _cuiaba(2026, 10, 28, 11))["processos"] if x["codigo"] == "ABC123")
    [a] = [x for x in siga.avisos(conn, hoje) if x["tipo"] == "siga_parado"]
    assert p["desde"] == "2026-10-02T09:00:00-04:00" and p["dias_uteis"] == 17
    assert (a["dias"], a["data"], a["nivel"]) == (17, "2026-10-02", "acao")
    assert a["mensagem"] == "processo SINFRA-PRO-2026/00001 parado em COFIN há 17 dias úteis"


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
    assert len(p["movimentacoes"]) == 35      # todas as gravadas (#512), nao so' as 30 ultimas
    assert p["movimentacoes"][0]["evento"] == "Recebimento Cancelado"      # gravada, aparece; so' nao deriva
    assert p["movimentacoes"][0]["data"] == "2026-10-28T10:00:00-04:00"         # hora de Cuiaba, com o fuso
    assert p["desde"] == "2026-10-02T09:00:00-04:00" and p["protocolado_em"] == "2026-09-01T08:00:00-04:00"
    assert p["ultima"]["data"] == "2026-10-28T09:30:00-04:00"
    assert p["medicao_id"] is None and p["obra"] is None
    assert set(p) >= {"id", "codigo", "numero", "nome", "contrato_id", "obra", "medicao_id", "medicao_titulo",
                      "protocolo_id", "situacao", "setor", "com_quem", "caixa_entrada", "desde", "dias_uteis",
                      "hoje", "ultima", "protocolado_em", "movimentacoes"}


def test_tipo_da_movimentacao_classifica_o_evento_para_os_filtros_do_historico():
    # issue #512: Transferencias, Recebimentos, Juntadas, Marcacoes e o resto em Outras
    casos = {"Transferência": "transferencia", "Transferencia | texto": "transferencia", "Recebimento": "recebimento",
             "Recebimento Cancelado": "recebimento", "Juntada": "juntada", "Juntada de documento": "juntada",
             "Marcação": "marcacao", "Marcacao": "marcacao", "Anotação": "outras", "Encerramento de volume": "outras",
             "Arquivamento": "outras", "Processo transferido": "transferencia", None: "outras", "": "outras"}
    for evento, tipo in casos.items():
        assert siga.tipo_da_movimentacao(evento) == tipo, evento


def test_painel_marca_o_tipo_de_cada_movimentacao(conn):
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 8), _leitura())
    p = siga.painel(conn, _cuiaba(2026, 10, 28, 11))["processos"][0]
    assert p["movimentacoes"] and all(m["tipo"] == siga.tipo_da_movimentacao(m["evento"]) for m in p["movimentacoes"])


def test_acompanhar_avulso_normaliza_o_numero_e_le_o_codigo_do_link(conn, monkeypatch):
    # issue #339: o mesmo extrair_codigo da etapa 4; numero gravado sem espacos. #663: sem nome digitado
    monkeypatch.setenv("DASH_SIGA_LINK_MODELO", "https://siga.exemplo.com.br/acompanhar?n={codigo}")
    pid = siga.acompanhar_avulso(conn, None, "https://siga.exemplo.com.br/acompanhar?n=AbCdEf1234",
                                 " ORGAO-PRO-2026/ 00009 ", "outros", None, complemento="  Licença  ")
    p = conn.execute("SELECT codigo, numero, nome, contrato_id, categoria, complemento FROM siga_processos WHERE id=?",
                     (pid,)).fetchone()
    assert tuple(p) == ("AbCdEf1234", "ORGAO-PRO-2026/00009", "Licença", None, "outros", "Licença")
    with pytest.raises(siga.JaAcompanhado) as e:
        siga.acompanhar_avulso(conn, None, "AbCdEf1234", None, "outros", None)
    assert e.value.nome == "Licença"
    with pytest.raises(ValueError, match="Escolha a categoria"):
        siga.acompanhar_avulso(conn, None, "XyZ98765", None, "", None)


# --- categorias e nome montado (issue #663) ------------------------------------------------------------------

def test_o_que_e_por_categoria():
    assert siga.o_que_e("medicoes", "ignorado", "7ª Medição") == "7ª Medição"
    assert siga.o_que_e("aditivos", "de prazo", None) == "Aditivo de prazo"
    assert siga.o_que_e("aditivos", None, None) == "Aditivo"
    assert siga.o_que_e("indenizatorios", "2025", None) == "Indenizatório 2025"
    # em Outros o complemento vale sozinho; sem ele, "Outro"
    assert siga.o_que_e("outros", "Licença ambiental", None) == "Licença ambiental"
    assert siga.o_que_e("outros", None, None) == "Outro"


def _categorias(conn):
    return [tuple(r) for r in conn.execute("SELECT numero, categoria FROM siga_processos ORDER BY id")]


def test_processo_que_o_robo_liga_a_medicao_entra_em_medicoes_e_os_demais_em_outros(conn):
    _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), _leitura(numero="SINFRA-PRO-2026/00001"))
    assert _categorias(conn) == [("SINFRA-PRO-2026/00001", "medicoes"), ("ORGAO-PRO-2026/00011", "outros")]
    alfa, beta = siga.painel(conn, _cuiaba(2026, 10, 28, 11))["processos"]
    assert (alfa["categoria"], alfa["o_que_e"], alfa["obra"]) == ("medicoes", "3ª Medição", "Obra Alfa")
    assert (beta["categoria"], beta["o_que_e"], beta["obra"], beta["nome"]) == ("outros", "Outro", None, "Processo Beta")


def test_protocolo_com_medicao_e_reajuste_e_medicoes_com_os_dois_titulos(conn):
    pid = _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    conn.execute("INSERT INTO medicoes (id, contrato_id, numero, tipo, competencia, estado) "
                 "VALUES (30, 7, 3, 'reajuste', '2026-09', 'protocolada')")
    conn.execute("INSERT INTO protocolo_medicoes (protocolo_id, medicao_id) VALUES (?, 30)", (pid,))
    conn.commit()
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), _leitura(numero="SINFRA-PRO-2026/00001")[:1])
    (p,) = siga.painel(conn, _cuiaba(2026, 10, 28, 11))["processos"]
    assert (p["categoria"], p["medicao_id"], p["o_que_e"]) == ("medicoes", None, "3ª Medição e Reajuste da 3ª Medição")


def test_processo_que_perde_o_vinculo_para_o_da_nota_volta_a_outros(conn):
    _planilha_por_fora(conn)
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 9), _leitura_unica("SINFRA-PRO-2026/00111", "PLA111"))
    assert _categorias(conn) == [("SINFRA-PRO-2026/00111", "medicoes")]
    conn.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_processo, origem) "
                 "VALUES (31, '2026-09-15', 'SINFRA-PRO-2026/00222', 'manual')")
    conn.commit()
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), _leitura_unica("SINFRA-PRO-2026/00222", "NOT222"))
    assert _categorias(conn) == [("SINFRA-PRO-2026/00111", "outros"), ("SINFRA-PRO-2026/00222", "medicoes")]


def test_classificar_troca_categoria_obra_e_complemento_sem_tocar_no_nome_do_robo(conn):
    _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), _leitura()[1:])
    pid = conn.execute("SELECT id FROM siga_processos").fetchone()[0]
    siga.classificar(conn, None, pid, "indenizatorios", 7, None, " 2025 ")
    p = conn.execute("SELECT nome, categoria, contrato_id, medicao_id, complemento FROM siga_processos").fetchone()
    assert tuple(p) == ("Processo Beta", "indenizatorios", 7, None, "2025")
    siga.classificar(conn, None, pid, "medicoes", 7, 31, None)
    assert tuple(conn.execute("SELECT categoria, contrato_id, medicao_id, protocolo_id FROM siga_processos"
                              ).fetchone()) == ("medicoes", 7, 31, None)
    # sai de Medicoes: perde a medicao; Outros pode ficar sem obra
    siga.classificar(conn, None, pid, "outros", None, None, None)
    assert tuple(conn.execute("SELECT categoria, contrato_id, medicao_id, complemento FROM siga_processos"
                              ).fetchone()) == ("outros", None, None, None)
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='siga.classificacao'").fetchone()[0] == 3
    with pytest.raises(ValueError, match="Medição não encontrada nesta obra"):
        siga.classificar(conn, None, pid, "medicoes", 7, 999, None)
    with pytest.raises(LookupError, match="Processo do SIGA não encontrado"):
        siga.classificar(conn, None, 999, "outros", None, None, None)


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


def test_rodada_completa_por_tempo_aos_59_minutos_da_ultima_completa(conn, robo):
    r = siga.iniciar_rodada(conn, AGORA)
    siga.terminar_rodada(conn, r["rodada_id"], [], AGORA + _min(3))
    # 58 minutos depois, sem pedido: nada a ler, e nada gravado
    assert siga.iniciar_rodada(conn, AGORA + _min(58)) == {"rodada_id": None, "tipo": None, "processos": []}
    assert _conta(conn, "siga_rodadas") == 1
    # com o pedido de um processo, so' ele
    _pedir(conn, robo, robo.ids[1], AGORA + _min(58))
    r2 = siga.iniciar_rodada(conn, AGORA + _min(58))
    assert r2["tipo"] == "pedido" and [p["codigo"] for p in r2["processos"]] == ["DEF456"]
    siga.terminar_rodada(conn, r2["rodada_id"], [], AGORA + _min(58, 30))
    # 59 minutos depois do inicio da ultima completa (a rodada automatica de hora em hora, #657), todos
    r3 = siga.iniciar_rodada(conn, AGORA + _min(59))
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


def test_so_pedidos_nunca_abre_rodada_automatica(conn, robo):
    # o robo fora do horario (#347): sem pedido nada a ler, mesmo sem rodada completa ha' mais de 59 minutos
    assert siga.iniciar_rodada(conn, AGORA, so_pedidos=True) == {"rodada_id": None, "tipo": None, "processos": []}
    assert _conta(conn, "siga_rodadas") == 0
    _pedir(conn, robo, robo.ids[1], AGORA)
    r = siga.iniciar_rodada(conn, AGORA + _min(1), so_pedidos=True)
    assert r["tipo"] == "pedido" and [p["codigo"] for p in r["processos"]] == ["DEF456"]
    # "comecei" repetido com a rodada aberta: a mesma rodada, tambem com so_pedidos
    assert siga.iniciar_rodada(conn, AGORA + _min(1, 30), so_pedidos=True)["rodada_id"] == r["rodada_id"]
    siga.terminar_rodada(conn, r["rodada_id"], [], AGORA + _min(2))
    _pedir(conn, robo, None, AGORA + _min(30))
    r = siga.iniciar_rodada(conn, AGORA + _min(30), so_pedidos=True)
    assert r["tipo"] == "pedido" and len(r["processos"]) == 3


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
                             "pedido_em": "2026-10-28T14:00:00+00:00", "travado": False}]
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


def test_pedido_travado_e_o_do_proprio_pedido_nao_o_do_ultimo_aviso(conn, robo):
    travados = lambda agora: {p["processo_id"]: p["travado"] for p in siga.situacao_robo(conn, agora)["pedidos"]}  # noqa: E731
    robo.resposta.update(codigo=1, erro=b"ERRO: acesso negado.")
    _pedir(conn, robo, robo.ids[0], AGORA)
    assert travados(AGORA) == {robo.ids[0]: True}                         # o Windows recusou o disparo dele
    # a rodada atende o pedido recusado; um pedido feito com o robo lendo nao dispara e o aviso velho continua
    r = siga.iniciar_rodada(conn, AGORA + _min(1))
    _pedir(conn, robo, robo.ids[1], AGORA + _min(2))
    assert travados(AGORA + _min(2)) == {robo.ids[1]: False}               # com rodada, nada esta' travado
    siga.terminar_rodada(conn, r["rodada_id"], [], AGORA + _min(3))
    assert any(a["tipo"] == "disparo" for a in siga.situacao_robo(conn, AGORA + _min(3))["avisos"])
    assert travados(AGORA + _min(3)) == {robo.ids[1]: False}               # o aviso de disparo nao e' dele
    assert travados(AGORA + _min(5, 1)) == {robo.ids[1]: True}             # robo nao comecou em 2 minutos


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
    r2 = siga.iniciar_rodada(conn, AGORA + _min(60))
    with pytest.raises(ValueError, match="código ou o número"):
        siga.terminar_rodada(conn, r2["rodada_id"], [{"codigo": " ", "numero": None, "motivo": "x"}], AGORA + _min(61))
    assert conn.execute("SELECT terminada_em FROM siga_rodadas WHERE id=?", (r2["rodada_id"],)).fetchone()[0] is None


# --- processo encerrado (issue #657) ----------------------------------------------------------------------

def _encerrado(conn, codigo="ABC123"):
    painel = siga.painel(conn, _cuiaba(2026, 10, 28, 11))
    return next(p for p in painel["processos"] if p["codigo"] == codigo)["encerrado"]


def test_processo_de_medicao_recebida_e_encerrado_e_volta_se_a_medicao_deixar_de_estar_recebida(conn):
    _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), _leitura(numero="SINFRA-PRO-2026/00001"))
    assert _encerrado(conn) is None
    conn.execute("UPDATE medicoes SET estado='recebida' WHERE id=31"); conn.commit()
    assert _encerrado(conn) == "recebida"
    assert _encerrado(conn, codigo=None) is None            # o outro processo, sem medicao, continua vivo
    conn.execute("UPDATE medicoes SET estado='protocolada' WHERE id=31"); conn.commit()
    assert _encerrado(conn) is None                          # derivado: nada foi gravado


@pytest.mark.parametrize("situacao,eventos,esperado", [
    ("1º Volume - Aguardando Andamento [ARQUIVO GERAL, [X]]", ["Transferência"], "arquivado"),
    ("1º Volume - Arquivado [PROTOC, [X]]", ["Transferência"], "arquivado"),
    ("1º Volume - Aguardando Andamento [COFIN, [X]]", ["Transferência", "ARQUIVAMENTO definitivo"], "arquivado"),
    ("1º Volume - Aguardando Andamento [COFIN, [X]]", ["Arquivamento", "Marcação"], "arquivado"),
    ("1º Volume - Aguardando Andamento [COFIN, [X]]", ["Arquivamento", "Desarquivamento"], None),
    ("1º Volume - Aguardando Andamento [COFIN, [X]]", ["Arquivamento", "Transferência"], None),
    ("1º Volume - Aguardando Andamento [COFIN, [X]]", ["Arquivamento", "Arquivamento Cancelado"], None),
    # o volume anterior arquivado nao encerra o processo: vale o ultimo volume
    (SITUACAO_COFIN, ["Transferência", "Juntada | Termo de arquivamento"], None),
])
def test_processo_arquivado_pelo_setor_ou_pela_ultima_movimentacao(conn, situacao, eventos, esperado):
    proc = [{"codigo": "ABC123", "numero": None, "nome": "Processo Alfa", "situacao": situacao,
             "movimentacoes": [{**_mov("", e, at_lotacao="COFIN/ORGAO"), "data": f"{20 + i}/10/2026 09:00:00"}
                               for i, e in enumerate(eventos)]}]
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), proc)
    assert _encerrado(conn) == esperado


def _ler(conn, processo_id, lido, situacao="1º Volume - Aguardando Andamento [COFIN, [X]]"):
    with db.mutacao(conn):
        conn.execute("INSERT INTO siga_leituras (processo_id, lido_em, situacao) VALUES (?,?,?)",
                     (processo_id, _banco(lido), situacao))


def _arquivar(conn, processo_id, lido=None):
    _ler(conn, processo_id, lido or AGORA - _min(60), "1º Volume - Aguardando Andamento [ARQUIVO, [X]]")


def test_lista_do_robo_e_rodada_completa_nao_trazem_processo_encerrado(conn, robo):
    _arquivar(conn, robo.ids[1])
    assert [p["nome"] for p in siga.processos_para_o_robo(conn)] == ["Processo Alfa", "Processo Gama"]
    r = siga.iniciar_rodada(conn, AGORA)
    assert r["tipo"] == "automatica" and [p["nome"] for p in r["processos"]] == ["Processo Alfa", "Processo Gama"]
    siga.terminar_rodada(conn, r["rodada_id"], [], AGORA + _min(2))
    _pedir(conn, robo, None, AGORA + _min(3))                # "todos" tambem nao traz o encerrado
    r2 = siga.iniciar_rodada(conn, AGORA + _min(3))
    assert [p["nome"] for p in r2["processos"]] == ["Processo Alfa", "Processo Gama"]
    siga.terminar_rodada(conn, r2["rodada_id"], [], AGORA + _min(4))
    _pedir(conn, robo, robo.ids[1], AGORA + _min(5))         # pedido da pessoa para aquele processo: e' lido
    r3 = siga.iniciar_rodada(conn, AGORA + _min(5))
    assert [p["nome"] for p in r3["processos"]] == ["Processo Beta"]


def test_so_processos_encerrados_nao_abrem_rodada_automatica(conn, robo):
    for pid in robo.ids:
        _arquivar(conn, pid)
    assert siga.iniciar_rodada(conn, AGORA) == {"rodada_id": None, "tipo": None, "processos": []}
    assert _conta(conn, "siga_rodadas") == 0


def test_rodada_completa_no_maximo_uma_vez_por_hora(conn, robo):
    r = siga.iniciar_rodada(conn, AGORA)
    siga.terminar_rodada(conn, r["rodada_id"], [], AGORA + _min(3))
    for minutos in (15, 30, 45, 58):
        assert siga.iniciar_rodada(conn, AGORA + _min(minutos))["rodada_id"] is None
    assert _conta(conn, "siga_rodadas") == 1
    r2 = siga.iniciar_rodada(conn, AGORA + _min(59))        # a tarefa de hora em hora, com a folga de 1 minuto
    assert r2["tipo"] == "automatica" and len(r2["processos"]) == 3


def _nao_lido_do_beta(conn, robo, lido, agora):
    """Beta lido em `lido`; a rodada de `agora` nao consegue le-lo. -> os avisos logo depois."""
    _ler(conn, robo.ids[1], lido)
    r = siga.iniciar_rodada(conn, agora)
    siga.terminar_rodada(conn, r["rodada_id"], [{"codigo": "DEF456", "numero": None, "motivo": "Não abriu"}],
                         agora + _min(1))
    return siga.situacao_robo(conn, agora + _min(1))["avisos"]


def test_processo_vivo_sem_leitura_ha_30_minutos_nao_mostra_nao_lido(conn, robo):
    assert _nao_lido_do_beta(conn, robo, AGORA - _min(30), AGORA) == []


def test_processo_vivo_sem_leitura_ha_mais_de_2_horas_uteis_mostra_nao_lido(conn, robo):
    agora = _cuiaba(2026, 10, 28, 11)
    assert _nao_lido_do_beta(conn, robo, _cuiaba(2026, 10, 28, 8, 30), agora) == [
        {"tipo": "nao_lido", "processo_id": robo.ids[1], "texto": "não lido às 11:00: Não abriu"},
        {"tipo": "nao_lidos", "processo_id": None, "texto": "1 de 3 processos não foram lidos"}]


def test_nao_lido_conta_das_8h_quando_a_ultima_leitura_e_de_ontem(conn, robo):
    # a mesma regra de horario do atraso geral: a leitura de ontem as 17h nao acusa as 9h
    assert _nao_lido_do_beta(conn, robo, _cuiaba(2026, 10, 27, 17), _cuiaba(2026, 10, 28, 9)) == []


def test_processo_encerrado_nao_mostra_nao_lido(conn, robo):
    _pedir(conn, robo, robo.ids[1], AGORA)
    _arquivar(conn, robo.ids[1], _cuiaba(2026, 10, 27, 9))
    r = siga.iniciar_rodada(conn, AGORA)
    siga.terminar_rodada(conn, r["rodada_id"], [{"codigo": "DEF456", "numero": None, "motivo": "Não abriu"}],
                         AGORA + _min(1))
    assert siga.situacao_robo(conn, AGORA + _min(1))["avisos"] == []


def test_atraso_do_monitor_so_olha_os_processos_vivos(conn, robo):
    agora = _cuiaba(2026, 10, 28, 11)
    _arquivar(conn, robo.ids[1], _cuiaba(2026, 10, 27, 9))
    # so' o encerrado tem leitura, e antiga: ninguem esta' atrasado

    def sem_leitura():
        return [a["mensagem"] for a in siga.avisos(conn, agora.date(), agora) if a["tipo"] == "siga_sem_leitura"]
    assert siga.painel(conn, agora)["atrasado"] is False and sem_leitura() == []
    _ler(conn, robo.ids[0], _cuiaba(2026, 10, 28, 8, 30))
    assert siga.painel(conn, agora)["atrasado"] is True
    assert sem_leitura() == ["monitor do SIGA sem leitura desde 28/10 08:30"]
    # leitura mais nova so' do encerrado nao desliga o atraso dos vivos
    _arquivar(conn, robo.ids[1], _cuiaba(2026, 10, 28, 10, 50))
    assert siga.painel(conn, agora)["atrasado"] is True


def test_processo_arquivado_nao_avisa_parado(conn):
    _protocolo_enviado(conn, "SINFRA-PRO-2026/00001")
    proc = _leitura(numero="SINFRA-PRO-2026/00001")[:1]
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 10), proc)
    hoje = datetime.date(2026, 10, 28)

    def parados():
        return [a["tipo"] for a in siga.avisos(conn, hoje) if a["tipo"] == "siga_parado"]
    assert parados() == ["siga_parado"]
    proc[0]["movimentacoes"] += [{**_mov("", "Arquivamento", at_lotacao="COFIN/ORGAO"), "data": "28/10/2026 10:30:00"}]
    siga.gravar_leitura(conn, _cuiaba(2026, 10, 28, 11), proc)
    assert parados() == []
