import datetime

import pytest
from app import (auth, certidoes, contratos, cronograma, db, entidades, medicoes,
                 paineis, tempo)

@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "engenharia")
    # Os testes deste modulo sao sobre as tres federais semeadas na 006; a 031 cobra tambem estadual e
    # municipal por padrao -- aqui elas ficam de fora para o cenario continuar o mesmo.
    c.execute("UPDATE certidao_tipos SET aplicavel_por_padrao=0 WHERE chave IN ('estadual','municipal')")
    c.commit()
    yield c
    c.close()

@pytest.fixture
def cid(conn):
    return contratos.criar(conn, 1, {"orgao": "S", "numero_instrumento": "IC 1", "objeto": "X",
                                     "valor_original_centavos": 1_000_00,
                                     "vigencia_fim": "2026-10-15", "data_base": "2025-08-01"})

def _medir(conn, cid, numero, tipo, comp, protocolado, atestado=None):
    mid = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": numero, "tipo": tipo, "competencia": comp})
    medicoes.definir_valor(conn, 1, mid, "protocolado", protocolado, "manual")
    medicoes.registrar_protocolo(conn, 1, mid, f"{comp}-28", None, None, "manual", True, "teste de cenário")
    if atestado is not None:
        medicoes.definir_valor(conn, 1, mid, "atestado", atestado, "manual")
    return mid

def test_curva_previsto_e_medido(conn, cid):
    cronograma.nova_versao(conn, 1, cid, [("2026-07", 300_00), ("2026-08", 400_00)], "manual")
    _medir(conn, cid, 1, "execucao", "2026-07", 250_00, atestado=240_00)
    _medir(conn, cid, 1, "reajuste", "2026-07", 10_00)
    pontos = {p["competencia"]: p for p in paineis.curva(conn, cid)}
    assert pontos["2026-07"]["previsto_centavos"] == 300_00
    assert pontos["2026-07"]["medido_execucao_centavos"] == 240_00      # atestado vence
    assert pontos["2026-07"]["medido_reajuste_centavos"] == 10_00       # serie propria (§6)
    assert pontos["2026-07"]["atestado_pendente"] is False
    assert pontos["2026-08"]["previsto_centavos"] == 400_00 and pontos["2026-08"]["medido_execucao_centavos"] == 0

def test_medido_usa_protocolado_marcado_enquanto_nao_atesta(conn, cid):
    _medir(conn, cid, 1, "execucao", "2026-07", 250_00)  # sem atestado
    p = paineis.curva(conn, cid)[0]
    assert p["medido_execucao_centavos"] == 250_00 and p["atestado_pendente"] is True

def test_cancelada_fica_fora(conn, cid):
    mid = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 9, "tipo": "execucao", "competencia": "2026-09"})
    medicoes.mudar_estado(conn, 1, mid, "cancelada", "x")
    assert all(p["competencia"] != "2026-09" for p in paineis.curva(conn, cid))

def test_saldo_formula_visivel(conn, cid):
    _medir(conn, cid, 1, "execucao", "2026-07", 250_00, atestado=240_00)
    s = paineis.saldo(conn, cid)
    assert s["vigente_centavos"] == 1_000_00 and s["atestado_execucao_centavos"] == 240_00
    assert s["saldo_centavos"] == 760_00 and "vigente" in s["formula"]

def _aditivo(conn, cid, delta, natureza, data="2026-01-10"):
    conn.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza) "
                 "VALUES (?, 'valor', ?, 'assinado', ?, ?)", (cid, delta, data, natureza))
    conn.commit()

def test_saldo_exclui_o_aditivo_de_reajuste_e_mostra_o_reajuste_a_parte(conn, cid):
    """Spec 2026-10-20 §3.2 (#262): o medido e' a precos iniciais; o aditivo de reajuste (SES) fica fora do saldo
    e aparece em serie propria. Centavo impar para pegar arredondamento escondido."""
    _aditivo(conn, cid, 200_01, "execucao")
    _aditivo(conn, cid, 133_33, "reajuste", data="2026-02-10")
    _medir(conn, cid, 1, "execucao", "2026-07", 250_00, atestado=240_00)
    s = paineis.saldo(conn, cid)
    assert s["vigente_centavos"] == 1_000_00 + 200_01 + 133_33             # o contrato vale tudo isso
    assert s["vigente_execucao_centavos"] == 1_000_00 + 200_01
    assert s["reajuste_contratado_centavos"] == 133_33
    assert s["saldo_centavos"] == 1_000_00 + 200_01 - 240_00               # sem o reajuste
    assert "reajuste" in s["formula"]

def test_saldo_sem_aditivo_de_reajuste_e_o_de_antes(conn, cid):
    _aditivo(conn, cid, 200_01, "execucao")
    _medir(conn, cid, 1, "execucao", "2026-07", 250_00, atestado=240_00)
    s = paineis.saldo(conn, cid)
    assert s["vigente_execucao_centavos"] == s["vigente_centavos"] == 1_200_01
    assert s["reajuste_contratado_centavos"] == 0
    assert s["saldo_centavos"] == 1_200_01 - 240_00

def test_aditivo_gravado_antes_da_natureza_conta_como_execucao(conn, cid):
    conn.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura) "
                 "VALUES (?, 'valor', 50_00, 'assinado', '2026-01-10')", (cid,))
    conn.commit()
    assert paineis.saldo(conn, cid)["saldo_centavos"] == 1_050_00

def test_aditivo_de_reajuste_em_andamento_nao_conta(conn, cid):
    conn.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, natureza) "
                 "VALUES (?, 'valor', 99_00, 'em_andamento', 'reajuste')", (cid,))
    conn.commit()
    s = paineis.saldo(conn, cid)
    assert s["reajuste_contratado_centavos"] == 0 and s["saldo_centavos"] == 1_000_00

def test_pendencia_e_por_serie_nao_por_competencia(conn, cid):
    # execucao atestada + reajuste so protocolado no MESMO mes: a pendencia do
    # reajuste nao pode contaminar a execucao (series independentes, §6)
    _medir(conn, cid, 1, "execucao", "2026-07", 250_00, atestado=240_00)
    _medir(conn, cid, 1, "reajuste", "2026-07", 10_00)
    p = paineis.curva(conn, cid)[0]
    assert p["atestado_pendente"] is False
    assert p["pendente_por_tipo"] == {"execucao": False, "reajuste": True, "projeto": False}

def test_saldo_declara_o_fallback_do_protocolado(conn, cid):
    # sem atestado o protocolado entra no saldo -- a formula tem que dizer isso
    _medir(conn, cid, 1, "execucao", "2026-07", 250_00)
    s = paineis.saldo(conn, cid)
    assert s["saldo_centavos"] == 750_00
    assert "protocolado" in s["formula"]

def test_alertas_ignora_data_ilegivel_em_vez_de_quebrar(conn, cid):
    # aditivos ainda entram sem a validacao do pydantic; um cadastro torto nao pode
    # derrubar o painel inteiro -- sem dado legivel, sem alerta (regra da casa)
    conn.execute("UPDATE contratos SET vigencia_fim='15/10/2026', data_base='' WHERE id=?", (cid,))
    tipos = {a["tipo"] for a in paineis.alertas(conn, hoje="2026-08-31")}
    assert "vigencia_vencendo" not in tipos and "data_base" not in tipos

def test_alertas_rejeita_hoje_invalido(conn, cid):
    # a tolerancia vale para dado ja gravado, nao para argumento de quem chama:
    # "hoje" torto tem que falhar, nao virar silenciosamente a data de hoje
    with pytest.raises(ValueError):
        paineis.alertas(conn, hoje="31/08/2026")

def test_alertas_vencidos(conn, cid):
    # prazo vencido e' aviso critico com os dias negativos
    conn.execute("UPDATE contratos SET execucao_fim='2026-09-30' WHERE id=?", (cid,)); conn.commit()
    alertas = {a["tipo"]: a for a in paineis.alertas(conn, hoje="2026-11-01")}
    assert "execucao_vencida" not in alertas
    # bloco 7: vencida sem pedido de prorrogacao e' "instrumento pendente", critico, tambem para a diretoria
    assert alertas["instrumento_pendente"]["nivel"] == "critico" and alertas["instrumento_pendente"]["dias"] == -32
    assert "execução vencida há 32 dias" in alertas["instrumento_pendente"]["mensagem"]

def test_alertas_sem_hoje_usa_a_data_de_cuiaba(conn, cid, monkeypatch):
    """O default de `hoje` e' a data do NEGOCIO (America/Cuiaba), nao a de UTC."""
    conn.execute("UPDATE contratos SET execucao_fim='2099-04-01' WHERE id=?", (cid,))
    conn.commit()
    monkeypatch.setattr(tempo, "hoje_local", lambda: datetime.date(2099, 3, 10))
    assert paineis.alertas(conn) == paineis.alertas(conn, hoje="2099-03-10")
    assert "execucao_vencendo" in {a["tipo"] for a in paineis.alertas(conn)}

def test_alertas_vence_hoje_ainda_e_vencendo(conn, cid):
    # a fronteira: no proprio dia do fim o prazo ainda nao venceu
    conn.execute("UPDATE contratos SET execucao_fim='2026-10-15' WHERE id=?", (cid,)); conn.commit()
    a = {a["tipo"]: a for a in paineis.alertas(conn, hoje="2026-10-15")}["execucao_vencendo"]
    assert a["dias"] == 0 and "termina em 0 dias" in a["mensagem"]

# --- endurecimento (gate 2 da fase) ---

def test_saldo_nao_estoura_com_valores_extremos(conn, cid):
    """SUM() do SQLite acumula em int64: duas medicoes VALIDAS (cada uma cabe na
    coluna) somam acima do teto e o driver levanta "integer overflow" -- 500
    persistente em curva/saldo/CSV ate' o dado sumir. Somar em Python
    (inteiro ilimitado) e' aritmetica honesta: o saldo fica muito negativo, e o
    painel continua respondendo."""
    quase_teto = 9_000_000_000_000_000_000
    _medir(conn, cid, 1, "execucao", "2026-07", quase_teto)
    _medir(conn, cid, 2, "execucao", "2026-08", quase_teto)
    s = paineis.saldo(conn, cid)
    assert s["atestado_execucao_centavos"] == 2 * quase_teto
    assert s["saldo_centavos"] == 1_000_00 - 2 * quase_teto

def test_alertas_antigos_sairam_da_tela(conn, cid):
    # bloco 6 (spec §11): data-base, medicao sem protocolo e reajuste sem par nao sao mais avisos
    cronograma.nova_versao(conn, 1, cid, [("2026-07", 300_00)], "manual")
    _medir(conn, cid, 1, "execucao", "2026-08", 1_00)
    for hoje in ("2026-06-15", "2026-08-31", "2026-09-10"):
        tipos = {a["tipo"] for a in paineis.alertas(conn, hoje=hoje)}
        assert not tipos & {"data_base", "medicao_sem_protocolo", "reajuste_sem_par", "vigencia_vencida"}

# --- alertas de certidao (fase 3, T7) ---
#
# O alerta deriva do ESTADO DO BANCO, nao da memoria da ultima rodada do robo: o que
# importa e' se HA cobertura hoje, quem quer que a tenha anexado. So entidades com
# contrato ATIVO entram -- consorciada de obra encerrada nao e' pendencia de ninguem.

def _cert(conn, ent=1, tipo=1, emissao="2026-08-01", validade="2026-12-01"):
    return certidoes.registrar(conn, 1, ent, tipo, emissao, validade,
                               f"certidoes/{ent}-{tipo}-{validade}.pdf", "a" * 64, "upload")

# Bloco 4: os alertas de certidao viraram 'documentos_empresa' (spec §11, app/documentos.py). O
# contrato do fixture nao tem orgao no cadastro, entao exige os tres tipos padrao.
def _de_documentos(conn, hoje="2026-09-01"):
    return [a for a in paineis.alertas(conn, hoje=hoje) if a["tipo"] == "documentos_empresa"]

def test_alerta_de_documento_ausente_para_entidade_com_contrato_ativo(conn, cid):
    # UM alerta por ENTIDADE, com os tipos na mensagem
    alertas = _de_documentos(conn)
    assert len(alertas) == 1
    a = alertas[0]
    assert a["nivel"] == "critico" and a["entidade_id"] == 1 and a["contrato_id"] == cid   # D10
    m = a["mensagem"]
    assert "Lotufo" in m and "federal sem certidão" in m and "FGTS sem certidão" in m and "trabalhista" in m
    assert not {x["tipo"] for x in paineis.alertas(conn, hoje="2026-09-01")} & {
        "certidao_vencida_ou_ausente", "certidao_vencendo"}

def test_alerta_de_documento_vencendo_na_fronteira_do_limiar(conn, cid):
    _cert(conn, tipo=1, validade="2026-09-16")   # 46 dias de validade -> limiar 15; faltam 15 -> alerta
    _cert(conn, tipo=2, validade="2026-09-17")   # faltam 16 -> silencio
    _cert(conn, tipo=3, validade="2026-12-01")
    alertas = _de_documentos(conn)
    assert len(alertas) == 1 and alertas[0]["nivel"] == "atencao"
    assert "federal vence em 15 dias" in alertas[0]["mensagem"] and "FGTS" not in alertas[0]["mensagem"]

def test_entidade_sem_contrato_ativo_nao_polui_o_painel(conn, cid):
    eid = entidades.criar(conn, 1, {"nome": "Consórcio Y", "cnpj": "11444777000161",
                                    "papel": "consorcio"})
    assert all(a["entidade_id"] != eid for a in _de_documentos(conn))
    contratos.criar(conn, 1, {"orgao": "S", "numero_instrumento": "IC 2", "objeto": "Y",
                              "valor_original_centavos": 1, "entidade_id": eid})
    assert {a["entidade_id"] for a in _de_documentos(conn)} == {1, eid}

def test_contrato_encerrado_nao_gera_alerta_de_documento(conn, cid):
    contratos.mudar_estado(conn, 1, cid, "encerrado", "2026-01-01", None)
    assert _de_documentos(conn) == []

def test_nao_se_aplica_silencia_o_alerta_do_tipo(conn, cid):
    certidoes.marcar_nao_se_aplica(conn, 1, 1, 3, "entidade não sujeita")
    m = _de_documentos(conn)[0]["mensagem"]
    assert "trabalhista" not in m and "federal" in m

def test_dois_contratos_da_mesma_entidade_nao_duplicam_o_alerta(conn, cid):
    # a pendencia e' da ENTIDADE: repeti-la por contrato encheria a tela com a mesma frase
    contratos.criar(conn, 1, {"orgao": "S", "numero_instrumento": "IC 2", "objeto": "Y",
                              "valor_original_centavos": 1})
    alertas = _de_documentos(conn)
    assert len(alertas) == 1 and alertas[0]["contrato_id"] == cid


def test_datas_de_marco_respeitam_a_ordem(conn, cid):
    # bloco 3: a nota vem ANTES do protocolo; a baixa nao vem antes da nota
    m = medicoes.criar_para_espelho(conn, 1, cid, 1, "execucao", "2026-07", 100_00)
    medicoes.mudar_estado(conn, 1, m, "nota_emitida", None, "2026-08-10")
    medicoes.registrar_protocolo(conn, 1, m, "2026-08-15", None, None, "manual", True, "teste de cenário")
    with pytest.raises(ValueError):
        medicoes.mudar_estado(conn, 1, m, "recebida", None, "2026-08-09")     # antes da nota
    medicoes.mudar_estado(conn, 1, m, "recebida", None, "2026-08-20")
    assert medicoes.detalhe(conn, m)["recebida_em"] == "2026-08-20"


# --- bloco 3: emitido pela nota vinculada; pendencias da nota ---
