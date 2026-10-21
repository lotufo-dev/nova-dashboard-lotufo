import pytest
from app import auditoria, auth, contratos, cronograma, db, tempo
from tests.apoio_corrida import ConexaoComCorrida

@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "engenharia")
    yield c
    c.close()

@pytest.fixture
def cid(conn):
    return contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 1",
                                     "objeto": "X", "valor_original_centavos": 100_00})

def test_versao_e_vigente(conn, cid):
    v1 = cronograma.nova_versao(conn, 1, cid, [("2026-09", 10_00), ("2026-10", 20_00)], "manual")
    assert cronograma.vigente(conn, cid)["numero"] == 1
    cronograma.nova_versao(conn, 1, cid, [("2026-09", 15_00), ("2026-10", 25_00)], "manual")
    vig = cronograma.vigente(conn, cid)
    assert vig["numero"] == 2
    assert vig["itens"][0]["valor_previsto_centavos"] == 15_00
    assert v1 == 1 or v1 > 0  # id retornado

def test_competencia_duplicada_na_versao(conn, cid):
    with pytest.raises(ValueError, match="duplicada"):
        cronograma.nova_versao(conn, 1, cid, [("2026-09", 1), ("2026-09", 2)], "manual")

def test_previsto_efetivo_congela_passado(conn, cid):
    # v1 criada "agora"; efetivo de competencias futuras segue a versao vigente,
    # mas uma competencia ANTERIOR ao mes de criacao da v2 mantem o valor da v1.
    cronograma.nova_versao(conn, 1, cid, [("2020-01", 10_00), ("2099-01", 20_00)], "manual")
    cronograma.nova_versao(conn, 1, cid, [("2020-01", 99_00), ("2099-01", 30_00)], "manual")
    ef = cronograma.previsto_efetivo(conn, cid)
    assert ef["2020-01"] == 10_00   # passado congelado (2020-01 < mes de criacao da v2)
    assert ef["2099-01"] == 30_00   # futuro pela vigente

def test_sem_cronograma(conn, cid):
    assert cronograma.vigente(conn, cid) is None
    assert cronograma.previsto_efetivo(conn, cid) == {}


# --- guardas adicionais ---

def test_versao_vazia_rejeita(conn, cid):
    """Versao sem item nenhum nao e' cronograma: viraria uma versao vigente que
    apaga o futuro inteiro em previsto_efetivo sem substituir por nada."""
    with pytest.raises(ValueError, match="vazi"):
        cronograma.nova_versao(conn, 1, cid, [], "manual")

def test_competencia_nova_em_versao_posterior_e_semeada(conn, cid):
    """Competencia PASSADA que nunca teve valor entra pela versao que a introduziu.

    Sem a excecao `comp not in efetivo`, um cronograma cadastrado hoje para uma obra
    ja em andamento perderia todos os meses ja decorridos (previsto = 0 no painel)."""
    cronograma.nova_versao(conn, 1, cid, [("2099-01", 10_00)], "manual")
    cronograma.nova_versao(conn, 1, cid, [("2020-05", 77_00), ("2099-01", 11_00)], "manual")
    ef = cronograma.previsto_efetivo(conn, cid)
    assert ef == {"2020-05": 77_00, "2099-01": 11_00}

def test_congelamento_com_datas_explicitas(conn, cid):
    """A regra pinada em datas fixas (nao depende de quando o teste roda).

    v1 nasce em jan/2026, v2 em jun/2026. Cada versao so reescreve competencias a
    partir do mes em que nasceu: mar/2026 (ja decorrido quando a v2 apareceu)
    continua valendo pela v1; jun/2026 (mes da propria v2) e set/2026 vao pela v2.
    """
    itens = [("2026-03", 10_00), ("2026-06", 20_00), ("2026-09", 30_00)]
    cronograma.nova_versao(conn, 1, cid, itens, "manual")
    cronograma.nova_versao(conn, 1, cid, [(c, v * 9) for c, v in itens], "manual")
    conn.execute("UPDATE cronograma_versoes SET criado_em='2026-01-15 10:00:00' WHERE numero=1")
    conn.execute("UPDATE cronograma_versoes SET criado_em='2026-06-10 10:00:00' WHERE numero=2")
    conn.commit()
    assert cronograma.previsto_efetivo(conn, cid) == {
        "2026-03": 10_00,    # passado congelado pela v1
        "2026-06": 180_00,   # mes da criacao da v2 ainda nao e' passado
        "2026-09": 270_00,   # futuro pela vigente
    }

def test_versoes_de_contratos_diferentes_nao_se_misturam(conn, cid):
    outro = contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 2",
                                      "objeto": "Y", "valor_original_centavos": 100_00})
    cronograma.nova_versao(conn, 1, cid, [("2099-01", 10_00)], "manual")
    cronograma.nova_versao(conn, 1, outro, [("2099-01", 20_00)], "manual")
    # numeracao e' por contrato: o segundo contrato tambem comeca na versao 1
    assert cronograma.vigente(conn, outro)["numero"] == 1
    assert cronograma.previsto_efetivo(conn, cid) == {"2099-01": 10_00}
    assert cronograma.previsto_efetivo(conn, outro) == {"2099-01": 20_00}

def test_numero_duplicado_por_corrida_vira_erro_de_dominio(conn, cid):
    """SELECT MAX(numero) + INSERT nao e' atomico entre requisicoes: quem perde a
    corrida colide no UNIQUE (contrato_id, numero). Tem que virar ValueError (422),
    nao IntegrityError crua dentro do handler (500)."""
    antigas = conn.execute("SELECT MAX(numero) AS n, MAX(criado_em) AS c FROM cronograma_versoes "
                           "WHERE contrato_id=?", (cid,)).fetchall()  # ainda sem versao nenhuma
    outro = db.get_conn()
    outro.execute("INSERT INTO cronograma_versoes (contrato_id, numero, origem) "
                  "VALUES (?,1,'manual')", (cid,))
    outro.commit()
    with pytest.raises(ValueError, match="concorrentemente"):
        cronograma.nova_versao(ConexaoComCorrida(conn, antigas, "MAX(NUMERO)"), 1, cid,
                               [("2099-01", 10_00)], "manual")
    conn.rollback()
    # so a versao do vencedor ficou, e sem itens orfaos da tentativa perdida
    vig = cronograma.vigente(conn, cid)
    assert vig["numero"] == 1 and vig["itens"] == []
    assert conn.execute("SELECT COUNT(*) FROM cronograma_versoes").fetchone()[0] == 1
    outro.close()

# --- endurecimento (gate 2 da fase) ---

def test_versao_nova_e_snapshot_do_futuro_nao_patch(conn, cid):
    """A versao vigente DEFINE o futuro inteiro; nao remenda o da anterior.

    Se a v2 omite uma competencia futura que a v1 previa, aquela previsao foi
    RETIRADA do cronograma. Tratar a versao como patch conservaria a previsao
    obsoleta no painel, contrariando "futuro pela versao vigente" (spec §5).
    """
    cronograma.nova_versao(conn, 1, cid, [("2026-03", 10_00), ("2026-09", 30_00),
                                          ("2026-12", 40_00)], "manual")
    cronograma.nova_versao(conn, 1, cid, [("2026-09", 35_00)], "manual")
    conn.execute("UPDATE cronograma_versoes SET criado_em='2026-01-15 10:00:00' WHERE numero=1")
    conn.execute("UPDATE cronograma_versoes SET criado_em='2026-06-10 10:00:00' WHERE numero=2")
    conn.commit()
    assert cronograma.previsto_efetivo(conn, cid) == {
        "2026-03": 10_00,   # passado congelado pela v1: a v2 nao o toca
        "2026-09": 35_00,   # futuro pela vigente
        # 2026-12 sumiu: a v2 nao preve mais aquele mes
    }

def test_mes_de_criacao_e_o_de_cuiaba_nao_o_de_utc(conn, cid):
    """A versao publicada as 21h30 do dia 31 nasce no mes que ainda esta correndo.

    criado_em='2026-09-01 01:30:00' e' UTC; em Cuiaba (UTC-4) isso e' 31/08 21:30,
    ou seja mes de criacao 2026-08. Lendo a string crua (criado_em[:7]) o mes seria
    2026-09 e agosto ja apareceria congelado pela v1 -- um mes inteiro deixaria de
    ser reescrito quatro horas antes da hora.
    """
    itens = [("2026-08", 10_00), ("2026-09", 30_00)]
    cronograma.nova_versao(conn, 1, cid, itens, "manual")
    cronograma.nova_versao(conn, 1, cid, [(c, v * 9) for c, v in itens], "manual")
    conn.execute("UPDATE cronograma_versoes SET criado_em='2026-01-15 10:00:00' WHERE numero=1")
    conn.execute("UPDATE cronograma_versoes SET criado_em='2026-09-01 01:30:00' WHERE numero=2")
    conn.commit()
    assert cronograma.previsto_efetivo(conn, cid) == {
        "2026-08": 90_00,    # mes ainda corrente em Cuiaba: a v2 reescreve
        "2026-09": 270_00,
    }

def test_criado_em_nunca_retrocede(conn, cid):
    """Relogio regressivo (acerto de NTP, fuso trocado) nao pode reescrever passado.

    Se a versao nova nascesse com criado_em ANTERIOR ao da anterior, ela passaria a
    valer para competencias que a anterior ja havia congelado."""
    cronograma.nova_versao(conn, 1, cid, [("2099-01", 10_00)], "manual")
    conn.execute("UPDATE cronograma_versoes SET criado_em='2099-06-10 10:00:00' WHERE numero=1")
    conn.commit()
    cronograma.nova_versao(conn, 1, cid, [("2099-01", 20_00)], "manual")
    vig = cronograma.vigente(conn, cid)
    assert vig["numero"] == 2
    assert vig["criado_em"] >= "2099-06-10 10:00:00"  # herdou o da anterior, nao o relogio

def test_auditoria_registrada(conn, cid):
    cronograma.nova_versao(conn, 1, cid, [("2099-01", 10_00)], "manual")
    acoes = [r["acao"] for r in conn.execute("SELECT acao FROM audit_log")]
    assert "cronograma.nova_versao" in acoes
    assert auditoria.verificar_cadeia(conn)


# --- issue #256: criado_em = data do documento --------------------------------------------------

def test_versao_com_data_do_documento_nao_sofre_o_clamp(conn, cid):
    """A versao do cadastro nasce na data do documento, mesmo anterior as que ja existem."""
    cronograma.nova_versao(conn, 1, cid, [("2026-09", 1_00)], "manual")
    cronograma.nova_versao(conn, 1, cid, [("2025-01", 2_00)], "manual", data_documento="2024-12-31")
    vs = conn.execute("SELECT numero, criado_em FROM cronograma_versoes ORDER BY numero").fetchall()
    assert vs[1]["numero"] == 2 and vs[1]["criado_em"] == "2024-12-31 04:00:00"   # meia-noite em Cuiaba
    assert tempo.mes_local(vs[1]["criado_em"]) == "2024-12"


def test_previsto_efetivo_respeita_a_data_do_documento_e_nao_a_ordem_da_carga(conn, cid):
    """Carga de 04/09/2026 (versao 1) e, depois, a versao contratual de 2024 vinda do cadastro (versao 2): na
    linha do tempo a de 2024 vem antes, e a carga continua valendo dali em diante."""
    cronograma.nova_versao(conn, 1, cid, [("2026-08", 10_00), ("2026-10", 20_00)], "manual")
    conn.execute("UPDATE cronograma_versoes SET criado_em='2026-09-04 15:00:00'")
    conn.commit()
    cronograma.nova_versao(conn, 1, cid, [("2024-05", 5_00), ("2026-08", 99_00), ("2026-10", 99_00),
                                          ("2026-11", 99_00)], "manual", data_documento="2024-04-10")
    assert cronograma.previsto_efetivo(conn, cid) == {"2024-05": 5_00, "2026-08": 99_00, "2026-10": 20_00}
    assert cronograma.vigente(conn, cid)["numero"] == 1    # a vigente e' a de documento mais recente


def test_documento_no_mesmo_dia_desempata_pelo_numero(conn, cid):
    cronograma.nova_versao(conn, 1, cid, [("2026-01", 1_00)], "manual", data_documento="2025-06-01")
    cronograma.nova_versao(conn, 1, cid, [("2026-01", 2_00)], "manual", data_documento="2025-06-01")
    assert cronograma.vigente(conn, cid)["numero"] == 2
    assert cronograma.previsto_efetivo(conn, cid) == {"2026-01": 2_00}


def test_lista_de_versoes_traz_os_dados_do_documento(conn, cid):
    cronograma.nova_versao(conn, 1, cid, [("2026-09", 1_01), ("2026-10", 2_00)], "manual")
    vid = conn.execute("SELECT id FROM cronograma_versoes").fetchone()[0]
    cronograma.nova_versao(conn, 1, cid, [("2024-05", 5_00)], "manual", data_documento="2024-04-10")
    vid2 = conn.execute("SELECT id FROM cronograma_versoes WHERE numero=2").fetchone()[0]
    conn.execute("INSERT INTO cronograma_versoes_cadastro (versao_id, contrato_id, chave, origem, data_documento,"
                 " instrumento) VALUES (?,?,?,?,?,?)", (vid2, cid, "contratual", "contratual", "2024-04-10", None))
    conn.commit()
    vs = cronograma.versoes(conn, cid)
    # ordem da linha do tempo (documento); a vigente marcada
    assert [(v["numero"], v["chave"], v["origem_documento"], v["data_documento"], v["competencias"],
             v["total_centavos"], v["vigente"]) for v in vs] == [
        (2, "contratual", "contratual", "2024-04-10", 1, 5_00, False),
        (1, None, None, None, 2, 3_01, True)]
    assert vid != vid2


# --- issue #295: curva S com a linha anterior a ultima repactuacao e as marcas dos aditivos -----

def _cadastro(conn, cid, numero, chave, origem, data, instrumento=None):
    vid = conn.execute("SELECT id FROM cronograma_versoes WHERE contrato_id=? AND numero=?", (cid, numero)).fetchone()[0]
    conn.execute("INSERT INTO cronograma_versoes_cadastro (versao_id, contrato_id, chave, origem, data_documento,"
                 " instrumento) VALUES (?,?,?,?,?,?)", (vid, cid, chave, origem, data, instrumento))
    conn.commit()


def _carga(conn, cid, itens):
    """Versao da carga de 04/09/2026: sem linha no cadastro, criada depois dos documentos."""
    cronograma.nova_versao(conn, 1, cid, itens, "manual")
    conn.execute("UPDATE cronograma_versoes SET criado_em='2026-09-04 15:00:00' WHERE numero="
                 "(SELECT MAX(numero) FROM cronograma_versoes)")
    conn.commit()


def test_anterior_e_o_previsto_antes_da_ultima_repactuacao_mesmo_com_a_carga_depois(conn, cid):
    cronograma.nova_versao(conn, 1, cid, [("2025-01", 10_00), ("2025-02", 10_00), ("2025-03", 10_00)], "manual",
                           data_documento="2024-12-01")
    cronograma.nova_versao(conn, 1, cid, [("2025-02", 5_00), ("2025-03", 5_00), ("2025-04", 5_00)], "manual",
                           data_documento="2025-02-10")
    _cadastro(conn, cid, 1, "contratual", "contratual", "2024-12-01")
    _cadastro(conn, cid, 2, "ta1", "aditivo", "2025-02-10")
    _carga(conn, cid, [("2025-03", 1_00), ("2025-05", 1_00)])     # vigente, mas nao e' repactuacao
    r = cronograma.curva_comparativa(conn, cid)
    # antes do TA1 so' havia a contratual; a carga (que ja inclui o TA) nao entra
    assert r["anterior"] == [{"competencia": "2025-01", "previsto_centavos": 10_00},
                             {"competencia": "2025-02", "previsto_centavos": 10_00},
                             {"competencia": "2025-03", "previsto_centavos": 10_00}]


def test_anterior_usa_a_ultima_de_varias_repactuacoes_e_aceita_carta_e_smo(conn, cid):
    cronograma.nova_versao(conn, 1, cid, [("2025-01", 10_00), ("2025-02", 10_00)], "manual", data_documento="2024-12-01")
    cronograma.nova_versao(conn, 1, cid, [("2025-01", 4_00), ("2025-02", 4_00)], "manual", data_documento="2025-01-15")
    cronograma.nova_versao(conn, 1, cid, [("2025-01", 4_00), ("2025-02", 2_00)], "manual", data_documento="2025-01-20")
    cronograma.nova_versao(conn, 1, cid, [("2025-02", 9_00)], "manual", data_documento="2025-03-01")   # correcao manual
    _cadastro(conn, cid, 1, "contratual", "contratual", "2024-12-01")
    _cadastro(conn, cid, 2, "ta1", "aditivo", "2025-01-15")
    _cadastro(conn, cid, 3, "smo1", "smo", "2025-01-20")
    assert cronograma.curva_comparativa(conn, cid)["anterior"] == [
        {"competencia": "2025-01", "previsto_centavos": 4_00}, {"competencia": "2025-02", "previsto_centavos": 4_00}]


def test_sem_repactuacao_nao_tem_linha_anterior(conn, cid):
    assert cronograma.curva_comparativa(conn, cid) == {"anterior": None, "aditivos": []}
    cronograma.nova_versao(conn, 1, cid, [("2025-01", 10_00)], "manual", data_documento="2024-12-01")
    _cadastro(conn, cid, 1, "contratual", "contratual", "2024-12-01")
    _carga(conn, cid, [("2025-01", 9_00)])                  # contratual + carga: nada foi repactuado
    assert cronograma.curva_comparativa(conn, cid)["anterior"] is None
    cronograma.nova_versao(conn, 1, cid, [("2025-01", 8_00)], "manual")     # correcao manual
    assert cronograma.curva_comparativa(conn, cid)["anterior"] is None


def test_repactuacao_unica_sem_nada_antes_nao_tem_linha_anterior(conn, cid):
    cronograma.nova_versao(conn, 1, cid, [("2025-01", 10_00)], "manual", data_documento="2024-12-01")
    _cadastro(conn, cid, 1, "ta1", "aditivo", "2024-12-01")
    assert cronograma.curva_comparativa(conn, cid)["anterior"] is None


def _aditivo(conn, cid, data, numero=None, ordinal=None, status="assinado", cancelado=None, forma=None):
    conn.execute("INSERT INTO aditivos (contrato_id, tipo, status, data_assinatura, numero, ordinal, cancelado_em, forma)"
                 " VALUES (?,?,?,?,?,?,?,?)", (cid, "prazo", status, data, numero, ordinal, cancelado, forma))
    conn.commit()


def test_marcas_vem_dos_aditivos_assinados_no_mes_da_assinatura(conn, cid):
    _aditivo(conn, cid, "2025-09-02", ordinal=2)
    _aditivo(conn, cid, "2025-06-30", ordinal=1)
    _aditivo(conn, cid, "2025-11-05", numero="7/2025")
    _aditivo(conn, cid, "2025-12-01")
    _aditivo(conn, cid, "2025-12-15", numero="099/2020/01/14")                       # ordinal pelo sufixo do numero
    _aditivo(conn, cid, "2025-12-20", ordinal=3, forma="apostilamento")             # apostilamento nao e' aditivo
    _aditivo(conn, cid, None, status="em_andamento", ordinal=3)                      # nao assinado
    _aditivo(conn, cid, "2025-07-01", ordinal=9, cancelado="2025-07-02 10:00:00")     # cancelado
    assert cronograma.curva_comparativa(conn, cid)["aditivos"] == [
        {"competencia": "2025-06", "data": "2025-06-30", "nome": "1º TA"},
        {"competencia": "2025-09", "data": "2025-09-02", "nome": "2º TA"},
        {"competencia": "2025-11", "data": "2025-11-05", "nome": "TA 7/2025"},
        {"competencia": "2025-12", "data": "2025-12-01", "nome": "Termo aditivo"},
        {"competencia": "2025-12", "data": "2025-12-15", "nome": "14º TA"}]
