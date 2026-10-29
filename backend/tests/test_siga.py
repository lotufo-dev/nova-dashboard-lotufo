"""Leituras do monitor do SIGA (issue #327): derivacoes, gravacao idempotente, vinculo por numero igual e atraso.

Processos, setores e pessoas sao ficticios (repositorio publico): "Fulano", "Beltrano", "Sicrana"."""
import datetime

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
