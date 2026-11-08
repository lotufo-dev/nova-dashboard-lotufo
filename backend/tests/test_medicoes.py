import json

import pytest
from app import auditoria, auth, contratos, db, medicoes
from tests.apoio_corrida import ConexaoComCorrida

@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn()
    db.migrate(c)
    # Fase 3,5: o checklist trava o protocolo; estes testes nao sao sobre certidoes.
    c.execute("UPDATE certidao_tipos SET aplicavel_por_padrao=0"); c.commit()
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "engenharia")
    yield c
    c.close()

@pytest.fixture
def contrato_id(conn):
    return contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 1/2026",
                                     "objeto": "Obra X", "valor_original_centavos": 100_000_00})

def test_criar_e_listar(conn, contrato_id):
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 12,
                                   "tipo": "execucao", "competencia": "2026-07"})
    itens = medicoes.listar(conn, contrato_id)
    assert [ (i["numero"], i["tipo"], i["estado"]) for i in itens ] == [(12, "execucao", "prevista")]
    assert itens[0]["protocolos"] == []
    assert medicoes.detalhe(conn, mid)["competencia"] == "2026-07"

def test_numero_duplicado_no_mesmo_tipo_rejeita(conn, contrato_id):
    medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    with pytest.raises(ValueError, match="já existe"):
        medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-08"})
    # mesmo numero em tipo diferente e valido (execucao 1 + reajuste 1)
    medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "reajuste", "competencia": "2026-07"})

def test_protocolo_congela_e_muda_estado(conn, contrato_id):
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, 1, mid, "protocolado", 50_000_00, "manual")
    medicoes.registrar_protocolo(conn, 1, mid, "2026-08-05", "CT-279-LT-2026", None, "manual")
    d = medicoes.detalhe(conn, mid)
    assert d["estado"] == "protocolada" and d["congelada"] == 1
    with pytest.raises(ValueError, match="congelada"):
        medicoes.definir_valor(conn, 1, mid, "protocolado", 60_000_00, "manual")
    # atestado continua editavel (glosa sem cerimonia, spec §5)
    medicoes.definir_valor(conn, 1, mid, "atestado", 48_000_00, "manual")
    # reapresentacao = novo evento, sem apagar o anterior
    medicoes.registrar_protocolo(conn, 1, mid, "2026-08-20", "CT-301-LT-2026", None, "manual")
    assert len(medicoes.detalhe(conn, mid)["protocolos"]) == 2

def test_transicoes_de_estado(conn, contrato_id):
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    with pytest.raises(ValueError, match="Transição inválida"):
        medicoes.mudar_estado(conn, 1, mid, "recebida", None)   # pular etapas nao pode
    medicoes.registrar_protocolo(conn, 1, mid, "2026-08-05", None, None, "manual")
    with pytest.raises(ValueError, match="Transição inválida"):
        medicoes.mudar_estado(conn, 1, mid, "nf_emitida", None)   # bloco 3: a NF entra pela nota, nao por botao
    medicoes.mudar_estado(conn, 1, mid, "recebida", None)          # recebida direto de protocolada
    with pytest.raises(ValueError, match="Transição inválida"):
        medicoes.mudar_estado(conn, 1, mid, "cancelada", None)  # recebida e final


@pytest.mark.parametrize("estado", ["planilha_enviada", "boletim_recebido"])
@pytest.mark.parametrize("fim", ["cancelada", "desistida"])
def test_planilha_enviada_e_boletim_recebido_podem_ser_encerrados(conn, contrato_id, estado, fim):
    # #284 (revisor): sem isso a medicao ficava presa na obra sem regra de espelho
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    conn.execute("UPDATE medicoes SET estado=? WHERE id=?", (estado, mid)); conn.commit()
    medicoes.mudar_estado(conn, 1, mid, fim, "obra paralisada pelo órgão")
    assert medicoes.detalhe(conn, mid)["estado"] == fim


def test_em_andamento_com_boletim_recebido_mostra_o_aprovado(conn, contrato_id):
    # #284: a prevista sem pedido que recebeu o boletim nao aparece com "—"; com pedido, vale o aprovado
    sem = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    com = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 2, "tipo": "execucao", "competencia": "2026-08"})
    conn.execute("UPDATE medicoes SET estado='boletim_recebido', valor_atestado_centavos=70001 WHERE id=?", (sem,))
    conn.execute("UPDATE medicoes SET estado='boletim_recebido', valor_atestado_centavos=99999, "
                 "valor_protocolado_centavos=100001, valor_protocolado_origem='manual' WHERE id=?", (com,))
    conn.commit()
    valores = {m["id"]: m["valor_centavos"] for m in medicoes.em_andamento(conn, contrato_id)}
    assert valores == {sem: 70001, com: 99999}


def test_em_andamento_mostra_o_aprovado_em_todo_estado(conn, contrato_id):
    # #284: espelho gerado com atestado diferente do pedido: a linha mostra o aprovado; sem atestado, o pedido
    com = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 3, "tipo": "execucao", "competencia": "2026-09"})
    sem = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 4, "tipo": "execucao", "competencia": "2026-10"})
    conn.execute("UPDATE medicoes SET estado='espelho_gerado', valor_protocolado_centavos=100001, "
                 "valor_protocolado_origem='espelho', valor_atestado_centavos=99999 WHERE id=?", (com,))
    conn.execute("UPDATE medicoes SET estado='espelho_gerado', valor_protocolado_centavos=50001, "
                 "valor_protocolado_origem='espelho' WHERE id=?", (sem,))
    conn.commit()
    valores = {m["id"]: m["valor_centavos"] for m in medicoes.em_andamento(conn, contrato_id)}
    assert valores == {com: 99999, sem: 50001}


def test_espelho_enviado_vai_a_nota_emitida_com_data(conn, contrato_id):
    mid = medicoes.criar_para_espelho(conn, 1, contrato_id, 7, "execucao", "2026-08", 100_000)
    medicoes.marcar_espelho_enviado(conn, 1, mid)
    medicoes.mudar_estado(conn, 1, mid, "nota_emitida", None, "2026-09-14")
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["nota_emitida_em"]) == ("nota_emitida", "2026-09-14")


def test_nota_emitida_aceita_protocolo_e_nao_volta(conn, contrato_id):
    mid = medicoes.criar_para_espelho(conn, 1, contrato_id, 8, "execucao", "2026-08", 100_000)
    medicoes.mudar_estado(conn, 1, mid, "nota_emitida", "declarada completa: nota unica", "2026-09-14")
    medicoes.registrar_protocolo(conn, 1, mid, "2026-09-16", "CT-300-LT-2026", None, "manual")
    assert medicoes.detalhe(conn, mid)["estado"] == "protocolada"
    with pytest.raises(ValueError):
        medicoes.mudar_estado(conn, 1, mid, "nota_emitida", None, None)
    # a baixa nao vem antes da nota
    with pytest.raises(ValueError):
        medicoes.mudar_estado(conn, 1, mid, "recebida", None, "2026-09-01")

def test_prevista_nao_vira_protocolada_por_mudar_estado(conn, contrato_id):
    """`protocolada` so se alcanca por registrar_protocolo (spec §5).

    mudar_estado nao cria linha em medicao_protocolos nem liga `congelada`: aceitar
    a transicao aqui deixaria uma medicao "protocolada" SEM protocolo e com o valor
    protocolado ainda editavel -- a invariante de congelamento inteira furada.
    """
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    with pytest.raises(ValueError, match="Transição inválida"):
        medicoes.mudar_estado(conn, 1, mid, "protocolada", None)
    d = medicoes.detalhe(conn, mid)
    assert d["estado"] == "prevista" and d["congelada"] == 0 and d["protocolos"] == []
    # e sem protocolo nao existe caminho para os estados seguintes
    for alvo in ("nota_emitida", "nf_emitida", "recebida"):
        with pytest.raises(ValueError, match="Transição inválida"):
            medicoes.mudar_estado(conn, 1, mid, alvo, None)
    assert medicoes.detalhe(conn, mid)["estado"] == "prevista"

def test_cancelar_com_motivo(conn, contrato_id):
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.mudar_estado(conn, 1, mid, "cancelada", "órgão desistiu")
    assert medicoes.detalhe(conn, mid)["estado"] == "cancelada"

def test_campo_invalido_rejeita(conn, contrato_id):
    # fail-closed sem depender de assert (que some com python -O): nome de coluna
    # nunca pode vir cru do chamador para dentro do UPDATE.
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    with pytest.raises(ValueError, match="Campo inválido"):
        medicoes.definir_valor(conn, 1, mid, "protocolado_centavos=0, congelada", 1, "manual")
    assert medicoes.detalhe(conn, mid)["valor_protocolado_centavos"] is None


def _detalhe_com_corrida(monkeypatch, conn, outro, medicao_id: int, sql: str):
    """Simula outro usuario que escreveu ENTRE o SELECT e o UPDATE (TOCTOU deterministico).

    Desde a fase 3 a mutacao inteira roda dentro de um BEGIN IMMEDIATE (db.mutacao),
    entao a outra conexao NAO consegue mais escrever no meio dela -- ficaria travada
    ate o busy_timeout. A corrida e' encenada do lado de fora: tira-se o snapshot da
    leitura ANTES, a interferencia commita, e a mutacao sob teste recebe aquela leitura
    ja obsoleta. O que fica provado e' exatamente o mesmo: quem barra o perdedor e' o
    UPDATE condicional ao estado LIDO, nao a validacao em Python.
    """
    real = medicoes.detalhe
    antigo = real(conn, medicao_id)     # leitura ANTES da corrida
    outro.execute(sql, (medicao_id,))
    outro.commit()
    def wrapper(c, mid):
        monkeypatch.setattr(medicoes, "detalhe", real)  # so a primeira leitura perde a corrida
        return antigo
    monkeypatch.setattr(medicoes, "detalhe", wrapper)
    return real

def test_mudar_estado_perde_corrida(conn, contrato_id, monkeypatch):
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    outro = db.get_conn()
    real = _detalhe_com_corrida(monkeypatch, conn, outro, mid,
                                "UPDATE medicoes SET estado='cancelada' WHERE id=?")
    with pytest.raises(ValueError, match="concorrentemente"):
        medicoes.mudar_estado(conn, 1, mid, "desistida", None)
    assert real(conn, mid)["estado"] == "cancelada"  # estado final alheio nao foi sobrescrito
    outro.close()

def test_valor_protocolado_perde_corrida(conn, contrato_id, monkeypatch):
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    outro = db.get_conn()
    # Outro usuario protocola COM VALOR entre a leitura de `congelada` e o UPDATE. E'
    # esse o caso que a guarda tem que barrar: congelada e ja' com valor. (Congelada
    # ainda SEM valor aceita o primeiro preenchimento -- ver o teste do primeiro
    # preenchimento no fim do arquivo.)
    real = _detalhe_com_corrida(
        monkeypatch, conn, outro, mid,
        "UPDATE medicoes SET estado='protocolada', congelada=1, valor_protocolado_centavos=70000000, "
        "valor_protocolado_origem='manual' WHERE id=?")
    with pytest.raises(ValueError, match="congelada"):
        medicoes.definir_valor(conn, 1, mid, "protocolado", 50_000_00, "manual")
    conn.rollback()
    assert real(conn, mid)["valor_protocolado_centavos"] == 70000000  # valor alheio intacto
    outro.close()

def test_valor_atestado_nao_sofre_a_guarda(conn, contrato_id, monkeypatch):
    # a guarda vale so para protocolado: atestado segue editavel mesmo congelando no meio (glosa)
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    outro = db.get_conn()
    real = _detalhe_com_corrida(monkeypatch, conn, outro, mid,
                                "UPDATE medicoes SET estado='protocolada', congelada=1 WHERE id=?")
    medicoes.definir_valor(conn, 1, mid, "atestado", 48_000_00, "manual")
    assert real(conn, mid)["valor_atestado_centavos"] == 48_000_00
    outro.close()

def test_protocolo_perde_corrida(conn, contrato_id, monkeypatch):
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    outro = db.get_conn()
    real = _detalhe_com_corrida(monkeypatch, conn, outro, mid,
                                "UPDATE medicoes SET estado='cancelada' WHERE id=?")
    with pytest.raises(ValueError, match="concorrentemente"):
        medicoes.registrar_protocolo(conn, 1, mid, "2026-08-05", None, None, "manual")
    conn.rollback()
    d = real(conn, mid)
    assert d["estado"] == "cancelada" and d["congelada"] == 0
    assert d["protocolos"] == []  # nada de protocolo orfao numa medicao cancelada
    outro.close()

def test_auditoria_registrada(conn, contrato_id):
    medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    acoes = [r["acao"] for r in conn.execute("SELECT acao FROM audit_log")]
    assert "medicao.criar" in acoes



def test_criar_perde_corrida_vira_erro_de_dominio(conn, contrato_id):
    """Perdedor da corrida recebe ValueError de dominio, nao IntegrityError crua (500)."""
    dados = {"contrato_id": contrato_id, "numero": 7, "tipo": "execucao", "competencia": "2026-07"}
    antigas = conn.execute(
        "SELECT id FROM medicoes WHERE contrato_id=? AND numero=? AND tipo=?",
        (contrato_id, 7, "execucao")).fetchall()   # vazio: a checagem nao vera a corrida
    outro = db.get_conn()
    outro.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia) VALUES (?,?,?,?)",
                  (contrato_id, 7, "execucao", "2026-07"))
    outro.commit()
    with pytest.raises(ValueError, match="já existe"):
        medicoes.criar(ConexaoComCorrida(conn, antigas, "SELECT ID FROM MEDICOES", no_inicio=True), 1, dados)
    conn.rollback()
    assert len(medicoes.listar(conn, contrato_id)) == 1  # nada duplicado ficou gravado
    outro.close()

def test_auditoria_do_motivo_reflete_o_que_ficou_gravado(conn, contrato_id):
    """motivo=None PRESERVA o motivo anterior (COALESCE): a auditoria tem que dizer isso.

    Registrar depois={"motivo": null} descreveria um apagamento que nunca aconteceu --
    numa cadeia append-only, a versao auditada tem que casar com a persistida.
    """
    mid = medicoes.criar_para_espelho(conn, 1, contrato_id, 1, "execucao", "2026-07", 100_00)
    medicoes.mudar_estado(conn, 1, mid, "nota_emitida", "órgão represou a NF")
    medicoes.registrar_protocolo(conn, 1, mid, "2026-08-05", None, None, "manual")
    medicoes.mudar_estado(conn, 1, mid, "recebida", None)  # sem motivo novo: o antigo fica
    gravado = medicoes.detalhe(conn, mid)["motivo_represamento"]
    assert gravado == "órgão represou a NF"
    ultimo = conn.execute(
        "SELECT antes, depois FROM audit_log WHERE acao='medicao.estado' ORDER BY id DESC LIMIT 1").fetchone()
    antes, depois = json.loads(ultimo["antes"]), json.loads(ultimo["depois"])
    # `recebida_em` entra na auditoria desde a fase 3,5 (data do marco, aqui ausente).
    assert depois == {"estado": "recebida", "motivo": gravado, "recebida_em": None}
    assert antes == {"estado": "protocolada", "motivo": gravado}
    assert auditoria.verificar_cadeia(conn)


# --- fase 3,5: datas dos marcos (spec §6) ---

def test_datas_de_marco_e_atesto(conn, contrato_id):
    mid = medicoes.criar_para_espelho(conn, 1, contrato_id, 1, "execucao", "2026-07", 100_00)
    medicoes.mudar_estado(conn, 1, mid, "nota_emitida", None, "2026-08-01")     # a nota vem antes do protocolo
    medicoes.registrar_protocolo(conn, 1, mid, "2026-08-05", None, None, "manual")
    medicoes.definir_valor(conn, 1, mid, "atestado", 90_00, "manual", "2026-08-20")
    # corrigir o valor SEM data preserva a data do atesto (COALESCE)
    medicoes.definir_valor(conn, 1, mid, "atestado", 85_00, "manual")
    medicoes.mudar_estado(conn, 1, mid, "recebida", None, "2026-09-30")
    d = medicoes.detalhe(conn, mid)
    assert (d["atestado_em"], d["nota_emitida_em"], d["recebida_em"]) == ("2026-08-20", "2026-08-01", "2026-09-30")
    assert d["valor_atestado_centavos"] == 85_00
    # a data so' acompanha o atestado e so' os estados com marco
    with pytest.raises(ValueError):
        medicoes.definir_valor(conn, 1, mid, "protocolado", 1, "manual", "2026-08-01")
    mid2 = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 2, "tipo": "execucao", "competencia": "2026-08"})
    with pytest.raises(ValueError):
        medicoes.mudar_estado(conn, 1, mid2, "cancelada", None, "2026-08-01")
    assert auditoria.verificar_cadeia(conn)

# --- revisao final: estado final nao recebe valores ---

@pytest.mark.parametrize("final", ["cancelada", "desistida"])
def test_estado_final_recusa_definir_valor_nos_dois_campos(conn, contrato_id, final):
    """Cancelada/desistida sao encerramentos: nem protocolado nem atestado mudam mais.

    `congelada` sozinha nao cobria isso -- uma medicao cancelada ANTES de qualquer
    protocolo continua com congelada=0, e o atestado nunca passa pela guarda de
    congelamento (fica editavel de proposito, para glosa).
    """
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1,
                                   "tipo": "execucao", "competencia": "2026-07"})
    medicoes.mudar_estado(conn, 1, mid, final, "encerrada")
    for campo in ("protocolado", "atestado"):
        with pytest.raises(ValueError, match="estado final"):
            medicoes.definir_valor(conn, 1, mid, campo, 50_000_00, "manual")
    d = medicoes.detalhe(conn, mid)
    assert d["valor_protocolado_centavos"] is None and d["valor_atestado_centavos"] is None

def test_recebida_mantem_o_atestado_editavel(conn, contrato_id):
    """A guarda nova cobre so cancelada/desistida: `recebida` segue aceitando glosa
    no atestado (spec §5). O protocolado ja e' barrado la pelo congelamento."""
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1,
                                   "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, 1, mid, "protocolado", 50_000_00, "manual")
    medicoes.registrar_protocolo(conn, 1, mid, "2026-08-05", None, None, "manual")
    medicoes.mudar_estado(conn, 1, mid, "recebida", None)
    medicoes.definir_valor(conn, 1, mid, "atestado", 48_000_00, "manual")
    assert medicoes.detalhe(conn, mid)["valor_atestado_centavos"] == 48_000_00
    with pytest.raises(ValueError, match="congelada"):
        medicoes.definir_valor(conn, 1, mid, "protocolado", 60_000_00, "manual")


def test_congelada_sem_valor_aceita_o_primeiro_preenchimento(conn, contrato_id):
    """Protocolo detectado (fase 6) congela a medicao ANTES de alguem saber o valor do
    oficio. O congelamento barra a ALTERACAO, nao o primeiro preenchimento -- senao a
    medicao ficaria protocolada sem valor para sempre (gate Sol da fase 6)."""
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 7, "tipo": "execucao",
                                   "competencia": "2026-07"})
    medicoes.registrar_protocolo(conn, 1, mid, "2026-08-05", "CT-279-LT-2026", None, "detectado")
    assert medicoes.detalhe(conn, mid)["congelada"] == 1
    medicoes.definir_valor(conn, 1, mid, "protocolado", 50_000_00, "manual")
    assert medicoes.detalhe(conn, mid)["valor_protocolado_centavos"] == 50_000_00
    # a partir daqui vale o congelamento de sempre
    with pytest.raises(ValueError, match="congelada"):
        medicoes.definir_valor(conn, 1, mid, "protocolado", 60_000_00, "manual")


# --- bloco 2: a medicao nasce ao gerar o espelho ---------------------------------------

def test_criar_para_espelho_nasce_em_espelho_gerado_com_valor(conn, contrato_id):
    mid = medicoes.criar_para_espelho(conn, 1, contrato_id, 7, "execucao", "2026-05", 27850992)
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["valor_protocolado_centavos"], m["valor_protocolado_origem"], m["congelada"]) == \
        ("espelho_gerado", 27850992, "espelho", 0)


def test_criar_para_espelho_de_novo_atualiza_o_valor_e_recusa_protocolada(conn, contrato_id):
    mid = medicoes.criar_para_espelho(conn, 1, contrato_id, 7, "execucao", "2026-05", 100)
    assert medicoes.criar_para_espelho(conn, 1, contrato_id, 7, "execucao", "2026-05", 200) == mid
    assert medicoes.detalhe(conn, mid)["valor_protocolado_centavos"] == 200
    medicoes.registrar_protocolo(conn, 1, mid, "2026-06-10", "CT-1", None, "manual")
    with pytest.raises(ValueError, match="protocolada"):
        medicoes.criar_para_espelho(conn, 1, contrato_id, 7, "execucao", "2026-05", 300)


def test_protocolo_a_partir_de_espelho_enviado_congela(conn, contrato_id):
    mid = medicoes.criar_para_espelho(conn, 1, contrato_id, 8, "execucao", "2026-05", 100)
    medicoes.marcar_espelho_enviado(conn, 1, mid)
    medicoes.marcar_espelho_enviado(conn, 1, mid)          # idempotente
    assert medicoes.detalhe(conn, mid)["estado"] == "espelho_enviado"
    medicoes.registrar_protocolo(conn, 1, mid, "2026-06-10", "CT-2", None, "manual")
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["congelada"]) == ("protocolada", 1)
    with pytest.raises(ValueError):
        medicoes.mudar_estado(conn, 1, mid, "espelho_enviado", None)   # nao volta


def test_em_andamento_lista_do_espelho_ao_pagamento_com_proximo_passo(conn, contrato_id):
    for numero, estado in ((1, "recebida"), (2, "protocolada"), (3, "nota_emitida"), (4, "cancelada")):
        conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
                     "VALUES (?, ?, 'execucao', '2026-08', ?)", (contrato_id, numero, estado))
    conn.commit()
    lista = medicoes.em_andamento(conn)
    assert [(m["numero"], m["proximo_passo"]) for m in lista] == [(3, "protocolar"), (2, "aguardando pagamento")]
    assert [m["titulo"] for m in medicoes.em_andamento(conn, estado="nota_emitida")] == ["3ª Medição"]


def test_medicao_final_poe_e_tira_o_contrato_do_encerramento(conn, contrato_id):
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 30, "tipo": "execucao", "competencia": "2026-08"})
    medicoes.marcar_final(conn, 1, mid, "2026-09-10")
    assert conn.execute("SELECT final FROM medicoes WHERE id=?", (mid,)).fetchone()[0] == 1
    enc = "SELECT encerramento_iniciado_em FROM contratos WHERE id=?"
    assert conn.execute(enc, (contrato_id,)).fetchone()[0] == "2026-09-10"
    with pytest.raises(ValueError, match="motivo"):
        medicoes.desmarcar_final(conn, 1, mid, " ")
    medicoes.desmarcar_final(conn, 1, mid, "marcada na obra errada")
    assert conn.execute(enc, (contrato_id,)).fetchone()[0] is None


def test_edicoes_valor_filtra_no_sql_pelo_indice_e_em_lotes(conn, contrato_id, monkeypatch):
    """Gate Sol S2 (10/10/2026): a linha do tempo lia todas as edicoes de valor da auditoria a cada obra aberta."""
    a = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    b = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 2, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, 1, a, "protocolado", 100, "manual")
    medicoes.definir_valor(conn, 1, b, "protocolado", 200, "manual")
    assert [e["texto"] for e in medicoes.edicoes_valor(conn, [a])[a]] == ["Valor protocolado definido em R$ 1,00 por U"]
    assert b not in medicoes.edicoes_valor(conn, [a])
    # a consulta usa o indice (migracao 036), sem varrer audit_log
    plano = " ".join(r[3] for r in conn.execute(
        "EXPLAIN QUERY PLAN SELECT id FROM audit_log WHERE entidade='medicao' AND entidade_id IN ('1','2') "
        "AND acao = 'medicao.valor_protocolado'"))
    assert "ix_audit_log_entidade" in plano
    # o atestado vem dos eventos de atesto (issue #61), tambem por indice
    plano = " ".join(r[3] for r in conn.execute(
        "EXPLAIN QUERY PLAN SELECT id FROM medicao_atestos WHERE medicao_id IN (1, 2)"))
    assert "ix_medicao_atestos_medicao" in plano
    # mais de 500 ids: em lotes, sem estourar o limite de parametros do SQLite
    monkeypatch.setattr(medicoes, "LOTE_AUDITORIA", 1)
    r = medicoes.edicoes_valor(conn, [a, b, *range(10_000, 10_600)])
    assert len(r[a]) == 1 and len(r[b]) == 1 and r[10_000] == []


def test_edicao_de_valor_sem_usuario_diz_pelo_sistema(conn, contrato_id):
    """Gate Sol S5 (10/10/2026): evento sem usuario ficava sem autoria na linha do tempo."""
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, None, mid, "protocolado", 100, "detectado")
    assert [e["texto"] for e in medicoes.edicoes_valor(conn, [mid])[mid]] == [
        "Valor protocolado definido em R$ 1,00 pelo sistema"]


def test_em_andamento_desde_usa_o_dia_de_cuiaba_no_criado_em(conn, contrato_id):
    """Sem marco, o `desde` cai no criado_em (UTC do SQLite): 01:30Z do dia 11 e' 21:30 do dia 10 em Cuiaba."""
    conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, criado_em) "
                 "VALUES (?, 5, 'execucao', '2026-09', 'espelho_gerado', '2026-10-11 01:30:00')", (contrato_id,))
    conn.commit()
    assert medicoes.em_andamento(conn)[0]["desde"] == "2026-10-10"


def test_mensagens_do_servidor_usam_o_rotulo_da_tela_para_nf_emitida(conn, contrato_id):
    assert medicoes.rotulo_estado("nf_emitida") == "lançada no RM"
    mid = medicoes.criar_para_espelho(conn, 1, contrato_id, 40, "execucao", "2026-08", 100_000)
    with pytest.raises(ValueError) as e:
        medicoes.mudar_estado(conn, 1, mid, "protocolada", None, "2026-09-14")
    assert "NF emitida" not in str(e.value)
    assert "lançada no RM" in str(e.value)


def _atestos(conn, mid):
    return [tuple(r) for r in conn.execute(
        "SELECT valor_centavos, origem, atestado_em, usuario_id FROM medicao_atestos WHERE medicao_id=? ORDER BY id",
        (mid,))]


def test_duas_edicoes_de_atesto_geram_dois_eventos_e_o_vigente_e_o_ultimo(conn, contrato_id):
    """Issue #61 (decisao do Leo, 15/10/2026): atesto e' evento append-only, com autor e data; vale o ultimo."""
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, 1, mid, "atestado", 1_234_57, "manual", "2026-08-20")
    medicoes.definir_valor(conn, 1, mid, "atestado", 1_234_56, "manual")      # glosa de um centavo, sem data nova
    assert _atestos(conn, mid) == [(1_234_57, "manual", "2026-08-20", 1), (1_234_56, "manual", "2026-08-20", 1)]
    assert all(r[0] for r in conn.execute("SELECT criado_em FROM medicao_atestos WHERE medicao_id=?", (mid,)))
    d = medicoes.detalhe(conn, mid)
    assert (d["valor_atestado_centavos"], d["atestado_em"]) == (1_234_56, "2026-08-20")
    assert [e["texto"] for e in medicoes.edicoes_valor(conn, [mid])[mid]] == [
        "Atestado definido em R$ 1.234,57 por U",
        "Atestado alterado de R$ 1.234,57 para R$ 1.234,56 por U"]


def test_atesto_mudar_so_o_dia_e_evento_e_regravar_igual_nao(conn, contrato_id):
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, 1, mid, "atestado", 90_01, "manual", "2026-08-20")
    medicoes.definir_valor(conn, 1, mid, "atestado", 90_01, "manual", "2026-08-25")
    medicoes.definir_valor(conn, 1, mid, "atestado", 90_01, "manual")           # nada muda: nao vira evento
    assert _atestos(conn, mid) == [(90_01, "manual", "2026-08-20", 1), (90_01, "manual", "2026-08-25", 1)]
    assert [e["texto"] for e in medicoes.edicoes_valor(conn, [mid])[mid]] == [
        "Atestado definido em R$ 90,01 por U",
        "Data do atesto alterada de 20/08/2026 para 25/08/2026 por U"]


def test_atesto_dia_posto_depois_aparece_com_autor(conn, contrato_id):
    """Gate Sol S1: valor sem dia e, depois, so' o dia: o evento existia mas nao aparecia na linha do tempo."""
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, 1, mid, "atestado", 70_01, "manual")
    medicoes.definir_valor(conn, 1, mid, "atestado", 70_01, "manual", "2026-08-20")
    assert [e["texto"] for e in medicoes.edicoes_valor(conn, [mid])[mid]] == [
        "Atestado definido em R$ 70,01 por U",
        "Data do atesto definida em 20/08/2026 por U"]


def test_atesto_confirmar_o_detectado_vira_evento_com_autor(conn, contrato_id):
    """Revisor R3: detectado -> aceito, mesmo valor e dia, e' quem confirmou; fica no historico."""
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, None, mid, "atestado", 60_01, "detectado", "2026-08-20")
    medicoes.definir_valor(conn, 1, mid, "atestado", 60_01, "aceito")
    assert _atestos(conn, mid) == [(60_01, "detectado", "2026-08-20", None), (60_01, "aceito", "2026-08-20", 1)]
    assert medicoes.detalhe(conn, mid)["valor_atestado_origem"] == "aceito"
    # revisor R4: a confirmacao aparece na linha do tempo, com autor
    medicoes.definir_valor(conn, 1, mid, "atestado", 60_01, "manual")
    assert [e["texto"] for e in medicoes.edicoes_valor(conn, [mid])[mid]] == [
        "Atestado definido em R$ 60,01 pelo sistema",
        "Atestado confirmado em R$ 60,01 por U",
        "Atestado confirmado em R$ 60,01 por U"]


def test_atesto_mudar_valor_e_dia_juntos_da_duas_linhas(conn, contrato_id):
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, 1, mid, "atestado", 1_000_00, "manual", "2026-08-20")
    medicoes.definir_valor(conn, 1, mid, "atestado", 900_01, "manual", "2026-08-25")
    assert len(_atestos(conn, mid)) == 2
    assert [e["texto"] for e in medicoes.edicoes_valor(conn, [mid])[mid]] == [
        "Atestado definido em R$ 1.000,00 por U",
        "Atestado alterado de R$ 1.000,00 para R$ 900,01 por U",
        "Data do atesto alterada de 20/08/2026 para 25/08/2026 por U"]


def test_atesto_depois_do_recebimento_tambem_e_evento(conn, contrato_id):
    """O Sol pediu os atestos como eventos inclusive apos NF/recebimento: la' o atestado segue editavel (glosa)."""
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, 1, mid, "protocolado", 50_000_00, "manual")
    medicoes.registrar_protocolo(conn, 1, mid, "2026-07-10", "CT-1", None, "manual")
    medicoes.mudar_estado(conn, 1, mid, "recebida", None)
    medicoes.definir_valor(conn, None, mid, "atestado", 48_000_01, "detectado")
    assert _atestos(conn, mid) == [(48_000_01, "detectado", None, None)]
    assert [e["texto"] for e in medicoes.edicoes_valor(conn, [mid])[mid]][-1] == \
        "Atestado definido em R$ 48.000,01 pelo sistema"


def test_evento_de_atesto_nao_se_altera_nem_se_apaga(conn, contrato_id):
    import sqlite3
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, 1, mid, "atestado", 100, "manual")
    with pytest.raises(sqlite3.DatabaseError, match="não se altera"):
        conn.execute("UPDATE medicao_atestos SET valor_centavos=1 WHERE medicao_id=?", (mid,))
    conn.rollback()
    with pytest.raises(sqlite3.DatabaseError, match="não se apaga"):
        conn.execute("DELETE FROM medicao_atestos WHERE medicao_id=?", (mid,))
    conn.rollback()
    assert _atestos(conn, mid) == [(100, "manual", None, 1)]


def test_banco_aceita_os_estados_do_motor_e_recusa_estado_desconhecido(conn, contrato_id):
    """Migracao 042 (issue #280): planilha/carta e boletim sao estados antes do espelho."""
    import sqlite3
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    for estado in ("planilha_gerada", "planilha_enviada", "boletim_recebido", "espelho_gerado"):
        conn.execute("UPDATE medicoes SET estado=? WHERE id=?", (estado, mid))
        assert medicoes.detalhe(conn, mid)["estado"] == estado
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE medicoes SET estado='boletim_inventado' WHERE id=?", (mid,))
    conn.rollback()


# --- issue #281: planilha/carta de medicao ---------------------------------------------------------------

ANEXOS = {"arquivo": "planilhas/a.pdf", "sha256": "a" * 64, "arquivo_planilha": "planilhas/b.xlsx",
          "sha256_planilha": "b" * 64}


def _planilha(numero, competencia, inicio, fim, valor, **extra):
    return {"numero": numero, "tipo": "execucao", "competencia": competencia, "periodo_inicio": inicio,
            "periodo_fim": fim, "valor_centavos": valor, **extra}


def _com_valores(conn, contrato_id, numero, estado, protocolado, atestado):
    conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
                 "valor_atestado_centavos) VALUES (?,?,'execucao','2026-01',?,?,?)",
                 (contrato_id, numero, estado, protocolado, atestado))
    conn.commit()


def test_acumulado_anterior_soma_aprovado_senao_pedido(conn, contrato_id):
    """Spec §2.1 passo 1: acumulado anterior = soma dos aprovados, senao pedidos, das medicoes anteriores do mesmo
    tipo. Prevista, cancelada e desistida e as de numero igual ou maior ficam de fora. Centavo impar de proposito."""
    from app import medicao_planilhas
    _com_valores(conn, contrato_id, 1, "protocolada", 10_000_01, 9_999_99)     # aprovado manda
    _com_valores(conn, contrato_id, 2, "planilha_gerada", 5_000_03, None)      # sem aprovado: o pedido
    _com_valores(conn, contrato_id, 3, "cancelada", 7_000_00, 7_000_00)        # fora
    _com_valores(conn, contrato_id, 4, "prevista", 1_00, None)                 # fora
    _com_valores(conn, contrato_id, 6, "protocolada", 3_00, 3_00)              # depois da 5: fora
    conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
                 "VALUES (?, 1, 'reajuste', '2026-01', 'protocolada', 999)", (contrato_id,))   # outro tipo: fora
    conn.commit()
    assert medicao_planilhas.acumulado_anterior(conn, contrato_id, "execucao", 5) == 9_999_99 + 5_000_03


def test_planilha_cria_versao_1_em_planilha_gerada(conn, contrato_id):
    from app import medicao_planilhas
    r = medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-07", "2026-07-01", "2026-07-31",
                                                                     12_345_67, numero_orgao=3), ANEXOS)
    d = medicoes.detalhe(conn, r["medicao_id"])
    assert d["estado"] == "planilha_gerada" and d["valor_protocolado_centavos"] == 12_345_67
    assert (d["periodo_inicio"], d["periodo_fim"], d["numero_orgao"]) == ("2026-07-01", "2026-07-31", 3)
    v = medicao_planilhas.versoes(conn, r["medicao_id"])
    assert [(x["versao"], x["valor_pedido_centavos"], x["motivo"]) for x in v] == [(1, 12_345_67, None)]
    assert r["saldo_centavos"] == 100_000_00 and r["saldo_apos_pedido_centavos"] == 100_000_00 - 12_345_67


def test_planilha_promove_a_prevista_do_mesmo_numero(conn, contrato_id):
    from app import medicao_planilhas
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    r = medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-07", "2026-07-01", "2026-07-31", 100),
                                    ANEXOS)
    assert r["medicao_id"] == mid and medicoes.detalhe(conn, mid)["estado"] == "planilha_gerada"
    with pytest.raises(ValueError, match="registre uma revisão"):
        medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-07", "2026-07-01", "2026-07-31", 100),
                                    ANEXOS)


def test_revisao_exige_motivo_e_so_antes_do_envio_muda_o_pedido(conn, contrato_id):
    from app import medicao_planilhas
    mid = medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-07", "2026-07-01", "2026-07-31",
                                                                       100_01), ANEXOS)["medicao_id"]
    rev = {"periodo_inicio": "2026-07-01", "periodo_fim": "2026-07-31", "valor_centavos": 90_03}
    with pytest.raises(ValueError, match="motivo"):
        medicao_planilhas.revisar(conn, 1, mid, {**rev, "motivo": "  "}, ANEXOS)
    assert medicao_planilhas.revisar(conn, 1, mid, {**rev, "motivo": "Rev01 da supervisora"}, ANEXOS)["versao"] == 2
    assert medicoes.detalhe(conn, mid)["valor_protocolado_centavos"] == 90_03
    # depois do envio, a revisao so' acrescenta a versao: o pedido congelado e' o da versao enviada
    conn.execute("UPDATE medicoes SET estado='planilha_enviada' WHERE id=?", (mid,)); conn.commit()
    assert medicao_planilhas.revisar(conn, 1, mid, {**rev, "valor_centavos": 80_00, "motivo": "Rev02"},
                                     ANEXOS)["versao"] == 3
    assert medicoes.detalhe(conn, mid)["valor_protocolado_centavos"] == 90_03
    conn.execute("UPDATE medicoes SET estado='boletim_recebido' WHERE id=?", (mid,)); conn.commit()
    with pytest.raises(ValueError, match="está com boletim recebido: a planilha/carta só se revisa antes do boletim"):
        medicao_planilhas.revisar(conn, 1, mid, {**rev, "motivo": "Rev03"}, ANEXOS)
    assert [v["versao"] for v in medicao_planilhas.versoes(conn, mid)] == [1, 2, 3]


def test_aviso_de_periodo_sobreposto_ou_pulando(conn, contrato_id):
    from app import medicao_planilhas
    medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-07", "2026-06-26", "2026-07-25", 1), ANEXOS)
    junto = medicao_planilhas.avisos(conn, contrato_id, "execucao", 2, "2026-08", "2026-07-26")
    sobre = medicao_planilhas.avisos(conn, contrato_id, "execucao", 2, "2026-08", "2026-07-20")
    pula = medicao_planilhas.avisos(conn, contrato_id, "execucao", 2, "2026-09", "2026-08-26")
    assert junto == []
    assert len(sobre) == 1 and "sobrepõe" in sobre[0] and "25/07/2026" in sobre[0]
    assert len(pula) == 1 and "pula" in pula[0]


def test_planilha_gerada_pode_ser_cancelada(conn, contrato_id):
    from app import medicao_planilhas
    mid = medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-07", "2026-07-01", "2026-07-31", 1),
                                      ANEXOS)["medicao_id"]
    medicoes.mudar_estado(conn, 1, mid, "cancelada", "lançada no mês errado")
    assert medicoes.detalhe(conn, mid)["estado"] == "cancelada"


def test_sugestao_proximo_numero_e_mes_seguinte(conn, contrato_id):
    from app import medicao_planilhas
    medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(4, "2026-11", "2026-11-01", "2026-11-30", 1_000_01,
                                                                 numero_orgao=12), ANEXOS)
    s = medicao_planilhas.sugestao(conn, contrato_id)
    assert (s["numero"], s["numero_orgao"], s["competencia"]) == (5, 13, "2026-12")
    assert (s["periodo_inicio"], s["periodo_fim"]) == ("2026-12-01", "2026-12-31")
    assert s["acumulado_anterior_centavos"] == 1_000_01 and s["saldo_centavos"] == 100_000_00 - 1_000_01
    medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(5, "2026-12", "2026-12-01", "2026-12-31", 1), ANEXOS)
    assert medicao_planilhas.sugestao(conn, contrato_id)["competencia"] == "2027-01"


def test_sugestao_pula_o_numero_de_medicao_cancelada(conn, contrato_id):
    """(contrato, numero, tipo) e' UNIQUE: sugerir o nº de uma cancelada levaria a gravacao recusada."""
    from app import medicao_planilhas
    _com_valores(conn, contrato_id, 4, "protocolada", 1_00, None)
    _com_valores(conn, contrato_id, 5, "cancelada", 1_00, None)
    assert medicao_planilhas.sugestao(conn, contrato_id)["numero"] == 6


def _de_tipo(conn, contrato_id, numero, tipo, competencia, estado, valor):
    conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
                 "VALUES (?,?,?,?,?,?)", (contrato_id, numero, tipo, competencia, estado, valor))
    conn.commit()


def test_sugestao_na_obra_so_de_projeto_segue_a_serie_de_projeto(conn, contrato_id):
    """Issue #567 (obra so' com medicoes de projeto): sem tipo, a sugestao segue o tipo da ultima medicao; a 3a de
    projeto, na competencia seguinte, com o acumulado das duas de projeto."""
    from app import medicao_planilhas
    _de_tipo(conn, contrato_id, 1, "projeto", "2026-08", "protocolada", 20_693_11)
    _de_tipo(conn, contrato_id, 2, "projeto", "2026-09", "planilha_enviada", 15_000_03)
    s = medicao_planilhas.sugestao(conn, contrato_id)
    assert (s["tipo"], s["numero"], s["competencia"]) == ("projeto", 3, "2026-10")
    assert (s["periodo_inicio"], s["periodo_fim"]) == ("2026-10-01", "2026-10-31")
    assert s["acumulado_anterior_centavos"] == 20_693_11 + 15_000_03
    # com o tipo escolhido, segue o escolhido
    assert medicao_planilhas.sugestao(conn, contrato_id, "execucao")["numero"] == 1


def test_tipo_da_ultima_medicao(conn, contrato_id):
    """Issue #567: o tipo pre-selecionado e' o da ultima medicao de execucao ou projeto (competencia mais recente; na
    mesma, a execucao); prevista, cancelada e desistida nao contam; o reajuste, mesmo mais recente, nao troca a
    serie; obra sem medicao: execucao."""
    from app import medicao_planilhas
    assert medicao_planilhas.tipo_da_ultima(conn, contrato_id) == "execucao"
    _de_tipo(conn, contrato_id, 1, "projeto", "2026-08", "protocolada", 1)
    assert medicao_planilhas.tipo_da_ultima(conn, contrato_id) == "projeto"
    _de_tipo(conn, contrato_id, 1, "execucao", "2026-09", "protocolada", 1)
    _de_tipo(conn, contrato_id, 1, "reajuste", "2026-09", "protocolada", 1)
    assert medicao_planilhas.tipo_da_ultima(conn, contrato_id) == "execucao"
    _de_tipo(conn, contrato_id, 2, "projeto", "2026-10", "cancelada", 1)
    _de_tipo(conn, contrato_id, 3, "projeto", "2026-11", "prevista", 1)
    assert medicao_planilhas.tipo_da_ultima(conn, contrato_id) == "execucao"
    _de_tipo(conn, contrato_id, 2, "reajuste", "2026-12", "planilha_gerada", 1)
    assert medicao_planilhas.tipo_da_ultima(conn, contrato_id) == "execucao"
    _de_tipo(conn, contrato_id, 4, "projeto", "2026-12", "protocolada", 1)
    assert medicao_planilhas.tipo_da_ultima(conn, contrato_id) == "projeto"
    _de_tipo(conn, contrato_id, 2, "execucao", "2026-12", "protocolada", 1)
    assert medicao_planilhas.tipo_da_ultima(conn, contrato_id) == "execucao"


def test_planilha_de_reajuste_e_recusada(conn, contrato_id):
    """Issue #567 (rodada 1): o reajuste nasce pelo formulario da execucao, em prevista, com data-base e ciclo (#276);
    a planilha/carta de reajuste e' recusada e nada e' gravado."""
    from app import medicao_planilhas
    with pytest.raises(ValueError, match="A planilha/carta é de medição de execução ou de projeto"):
        medicao_planilhas.registrar(conn, 1, contrato_id, {**_planilha(1, "2026-07", "2026-07-01", "2026-07-31", 5_00),
                                                           "tipo": "reajuste"}, ANEXOS)
    assert medicoes.listar(conn, contrato_id) == []


def test_sugestao_sai_de_um_retrato_so(conn, contrato_id):
    """Issue #567 (gate Sol, rodada 1): a medicao gravada por outra conexao no meio da sugestao nao mistura o nº de
    depois (MAX) com a competencia de antes (ultima)."""
    from app import medicao_planilhas
    _de_tipo(conn, contrato_id, 1, "projeto", "2026-08", "protocolada", 1_00)
    _de_tipo(conn, contrato_id, 2, "projeto", "2026-09", "protocolada", 1_00)
    outro = db.get_conn()

    class GravaNoMeio:
        """Depois da consulta da ultima medicao, outra conexao grava a 3a de projeto."""
        def __init__(self, real):
            self._real, self._armada = real, True

        def execute(self, sql, params=()):
            cur = self._real.execute(sql, params)
            if self._armada and "NUMERO_ORGAO FROM MEDICOES" in sql.upper():
                self._armada = False
                linhas = cur.fetchall()
                outro.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
                              "VALUES (?, 3, 'projeto', '2026-10', 'planilha_gerada')", (contrato_id,))
                outro.commit()
                from tests.apoio_corrida import CursorMaterializado
                return CursorMaterializado(linhas)
            return cur

        def __getattr__(self, nome):
            return getattr(self._real, nome)

    try:
        s = medicao_planilhas.sugestao(GravaNoMeio(conn), contrato_id)
    finally:
        outro.close()
    assert (s["tipo"], s["numero"], s["competencia"]) == ("projeto", 3, "2026-10")
    assert not conn.in_transaction


def test_numero_do_orgao_nao_e_inventado_nem_apagado_na_prevista(conn, contrato_id):
    from app import medicao_planilhas
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 3, "tipo": "execucao", "competencia": "2026-07"})
    conn.execute("UPDATE medicoes SET numero_orgao=8 WHERE id=?", (mid,))
    _com_valores(conn, contrato_id, 4, "protocolada", 1_00, None)
    conn.execute("UPDATE medicoes SET numero_orgao=10 WHERE numero=4"); conn.commit()
    s = medicao_planilhas.sugestao(conn, contrato_id)
    assert (s["numero"], s["numero_orgao"]) == (3, None)     # prevista abaixo da ultima: nada a extrapolar
    medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(3, "2026-07", "2026-07-01", "2026-07-31", 1), ANEXOS)
    assert medicoes.detalhe(conn, mid)["numero_orgao"] == 8


@pytest.mark.parametrize("estado", ["planilha_gerada", "planilha_enviada", "boletim_recebido"])
def test_pedido_da_planilha_nao_muda_pelo_valor_avulso(conn, contrato_id, estado):
    """Gate Sol rodada 1: da planilha ao boletim o pedido so' muda por revisao (versao nova com motivo)."""
    from app import medicao_planilhas
    mid = medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-07", "2026-07-01", "2026-07-31",
                                                                       100_01), ANEXOS)["medicao_id"]
    conn.execute("UPDATE medicoes SET estado=? WHERE id=?", (estado, mid)); conn.commit()
    # depois do boletim a revisao tambem e' recusada: a mensagem nao a sugere (gate Sol, rodada 2)
    esperada = ("O pedido não pode mais ser alterado depois do boletim do órgão" if estado == "boletim_recebido"
                else "Para mudar o pedido, registre uma revisão da planilha/carta")
    with pytest.raises(ValueError, match=esperada):
        medicoes.definir_valor(conn, 1, mid, "protocolado", 200_00, "manual")
    assert medicoes.detalhe(conn, mid)["valor_protocolado_centavos"] == 100_01
    medicoes.definir_valor(conn, 1, mid, "atestado", 99_99, "manual")     # o aprovado segue (boletim/glosa)


def test_saldo_da_revisao_depois_do_envio_usa_o_pedido_da_medicao(conn, contrato_id):
    from app import medicao_planilhas
    mid = medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-07", "2026-07-01", "2026-07-31",
                                                                       10_000_01), ANEXOS)["medicao_id"]
    conn.execute("UPDATE medicoes SET estado='planilha_enviada' WHERE id=?", (mid,)); conn.commit()
    r = medicao_planilhas.revisar(conn, 1, mid, {"periodo_inicio": "2026-07-01", "periodo_fim": "2026-07-31",
                                                 "valor_centavos": 5_000_00, "motivo": "Rev01"}, ANEXOS)
    assert r["saldo_apos_pedido_centavos"] == 100_000_00 - 10_000_01


def test_revisao_igual_a_vigente_e_recusada(conn, contrato_id):
    from app import medicao_planilhas
    mid = medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-07", "2026-07-01", "2026-07-31",
                                                                       100), ANEXOS)["medicao_id"]
    rev = {"periodo_inicio": "2026-07-01", "periodo_fim": "2026-07-31", "valor_centavos": 90, "motivo": "Rev01"}
    medicao_planilhas.revisar(conn, 1, mid, rev, ANEXOS)
    with pytest.raises(ValueError, match="Esta revisão é igual à versão 2 já registrada"):
        medicao_planilhas.revisar(conn, 1, mid, {**rev, "motivo": "clique repetido"}, ANEXOS)
    # outro arquivo com o mesmo valor e periodo e' revisao de verdade
    medicao_planilhas.revisar(conn, 1, mid, rev, {**ANEXOS, "sha256_planilha": "c" * 64})
    assert [v["versao"] for v in medicao_planilhas.versoes(conn, mid)] == [1, 2, 3]


def test_numero_cancelado_nao_sugere_revisao(conn, contrato_id):
    from app import medicao_planilhas
    _com_valores(conn, contrato_id, 1, "cancelada", 1_00, None)
    with pytest.raises(ValueError) as e:
        medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-07", "2026-07-01", "2026-07-31", 1),
                                    ANEXOS)
    assert str(e.value) == "Medição 1 de execução já existe neste contrato e está cancelada"


def test_projeto_nao_tem_saldo_contra_o_contrato(conn, contrato_id):
    from app import medicao_planilhas
    r = medicao_planilhas.registrar(conn, 1, contrato_id, {**_planilha(1, "2026-07", "2026-07-01", "2026-07-31", 1),
                                                           "tipo": "projeto"}, ANEXOS)
    assert r["saldo_centavos"] is None and r["saldo_apos_pedido_centavos"] is None
    assert medicao_planilhas.sugestao(conn, contrato_id, "projeto")["saldo_centavos"] is None


@pytest.mark.parametrize("estado", ["planilha_enviada", "boletim_recebido"])
def test_protocolo_a_mao_recusado_depois_do_envio_da_planilha(conn, contrato_id, estado):
    """Gate Sol S4 (#281): nesses estados o protocolo a mao congelava o pedido sem mudar o estado. A lista de estados
    que recebem protocolo e' explicita; os demais sao recusados e nada e' gravado."""
    _com_valores(conn, contrato_id, 1, estado, 1_00, None)
    mid = conn.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=1", (contrato_id,)).fetchone()[0]
    with pytest.raises(ValueError, match=f"Medição {medicoes.rotulo_estado(estado)} não recebe protocolo"):
        medicoes.registrar_protocolo(conn, 1, mid, "2026-08-05", "CT-1-LT-2026", None, "manual")
    d = medicoes.detalhe(conn, mid)
    assert (d["estado"], d["congelada"]) == (estado, 0)
    assert conn.execute("SELECT COUNT(*) FROM medicao_protocolos WHERE medicao_id=?", (mid,)).fetchone()[0] == 0


def test_detalhe_le_tudo_de_um_retrato_so(conn, contrato_id, monkeypatch):
    """Issue #559: notas, notas_faltam e pagamento_cota saem da mesma leitura (a baixa do RM nao entra no meio)."""
    from app import notas as _notas, sincronizacao_rm
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    vistas = []
    for modulo, nome in ((sincronizacao_rm, "notas_da_medicao"), (_notas, "faltam"), (sincronizacao_rm, "pagamento_cota")):
        original = getattr(modulo, nome)

        def espiao(c, *a, _o=original, _n=nome, **k):
            vistas.append((_n, c.in_transaction))
            return _o(c, *a, **k)
        monkeypatch.setattr(modulo, nome, espiao)
    medicoes.detalhe(conn, mid)
    assert vistas == [("notas_da_medicao", True), ("faltam", True), ("pagamento_cota", True)]
    assert not conn.in_transaction


# --- issue #276: medicao de reajuste sugere o valor e grava data-base e ciclo ----------------------------------------

def _base(conn, contrato_id, mes="2024-06", aplica_a=""):
    conn.execute("INSERT INTO contrato_datas_base (contrato_id, mes, indice, aplica_a) VALUES (?,?,'INCC-DI',?)",
                 (contrato_id, mes, aplica_a))
    conn.commit()


def _prevista(conn, contrato_id, competencia, valor, origem, data_base="2024-06", ciclo=2026, termo=None):
    pleito_id = instrumento_id = None
    if origem == "apostilamento":
        conn.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, numero, data, dados) "
                     "VALUES (?, ?, 'apostilamento_reajuste', ?, '2026-09-15', ?)",
                     (contrato_id, f"ap-{termo}", termo, json.dumps({"ciclo": ciclo, "data_base": data_base})))
        instrumento_id = conn.execute("SELECT MAX(id) FROM instrumentos").fetchone()[0]
    elif origem == "pleito":
        conn.execute("INSERT INTO pleitos (contrato_id, tipo, origem, data_base_mes, ciclo, numero_oficio, situacao) "
                     "VALUES (?, 'reajuste', 'sistema', ?, ?, 'CT-1-LT-2026', 'enviado')",
                     (contrato_id, data_base, ciclo))
        pleito_id = conn.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    conn.execute("INSERT INTO reajuste_previsoes (contrato_id, data_base_mes, ciclo, competencia, "
                 "valor_previsto_centavos, origem, pleito_id, instrumento_id) VALUES (?,?,?,?,?,?,?,?)",
                 (contrato_id, data_base, ciclo, competencia, valor, origem, pleito_id, instrumento_id))
    conn.commit()


def _evento(conn, acao, medicao_id):
    return conn.execute("SELECT antes, depois FROM audit_log WHERE acao=? AND entidade='medicao' AND entidade_id=?",
                        (acao, medicao_id)).fetchone()


def test_sugestao_do_reajuste_apostilado_senao_previsto_senao_vazio(conn, contrato_id):
    """Issue #276: a competencia apostilada sugere o apostilado e diz o termo; sem apostilamento, o previsto (pleito,
    senao manual); sem nada, vazio. Centavo impar de proposito."""
    from app import reajuste
    _base(conn, contrato_id)
    _prevista(conn, contrato_id, "2026-07", 1_234_55, "pleito")
    _prevista(conn, contrato_id, "2026-07", 1_300_01, "apostilamento", termo="001/2026")
    _prevista(conn, contrato_id, "2026-08", 2_000_03, "pleito")
    _prevista(conn, contrato_id, "2026-09", 3_000_07, "manual")

    def base(comp):
        s = reajuste.sugestao_da_medicao(conn, contrato_id, comp)
        assert s["data_base_mes"] == "2024-06"
        (b,) = s["bases"]
        return b["valor_centavos"], b["origem_texto"], b["ciclo"]

    assert base("2026-07") == (1_300_01, "apostilado no termo 001/2026", 2026)
    assert base("2026-08") == (2_000_03, "previsto no pleito", 2026)
    assert base("2026-09") == (3_000_07, "previsto", 2026)
    assert base("2026-10") == (None, None, 2026)
    assert base("2027-05") == (None, None, 2026)        # antes do aniversario de 2027: ainda o ciclo 2026


def test_sugestao_sem_data_base_ou_sem_reajuste_nao_tem_base(conn, contrato_id):
    from app import reajuste
    assert reajuste.sugestao_da_medicao(conn, contrato_id, "2026-07")["bases"] == []
    assert reajuste.base_e_ciclo_da_medicao(conn, contrato_id, "2026-07", None) == (None, None)
    _base(conn, contrato_id)
    conn.execute("UPDATE contratos SET sem_reajuste=1 WHERE id=?", (contrato_id,)); conn.commit()
    assert reajuste.sugestao_da_medicao(conn, contrato_id, "2026-07")["bases"] == []


def test_duas_datas_base_pre_escolhe_a_que_tem_previsao(conn, contrato_id):
    """Issue #276, D7 (5 Bairros): com duas bases, cada uma traz o aplica_a, o ciclo e a sugestao dela; vem escolhida
    a unica que tem previsao na competencia, senao nenhuma, e a gravacao sem escolha e' recusada."""
    from app import reajuste
    _base(conn, contrato_id, "2024-04", "itens SICRO")
    _base(conn, contrato_id, "2024-06", "demais itens")
    _prevista(conn, contrato_id, "2026-05", 777_77, "manual", data_base="2024-04")
    s = reajuste.sugestao_da_medicao(conn, contrato_id, "2026-05")
    assert s["data_base_mes"] == "2024-04"
    assert [(b["data_base_mes"], b["aplica_a"], b["ciclo"], b["valor_centavos"]) for b in s["bases"]] == [
        ("2024-04", "itens SICRO", 2026, 777_77), ("2024-06", "demais itens", 2025, None)]
    assert reajuste.sugestao_da_medicao(conn, contrato_id, "2026-08")["data_base_mes"] is None
    with pytest.raises(ValueError, match="Escolha a data-base do reajuste"):
        reajuste.base_e_ciclo_da_medicao(conn, contrato_id, "2026-08", None)
    assert reajuste.base_e_ciclo_da_medicao(conn, contrato_id, "2026-05", "2024-06") == ("2024-06", 2025)
    with pytest.raises(ValueError, match="não é deste contrato"):
        reajuste.base_e_ciclo_da_medicao(conn, contrato_id, "2026-05", "2024-01")


def test_planilha_com_reajuste_cria_a_medicao_de_reajuste_prevista(conn, contrato_id):
    """Issue #276 (decisao do Leo, 08/11/2026): a planilha/carta com o campo Reajuste faz nascer a medicao de reajuste
    de mesmo nº e competencia, em `prevista`, com o pedido, a data-base e o ciclo; a aba Reajuste a ve' pedida."""
    from app import medicao_planilhas, reajuste
    _base(conn, contrato_id)
    r = medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(3, "2026-07", "2026-07-01", "2026-07-31", 100_00,
                                                                     reajuste_centavos=1_300_01), ANEXOS)
    m = medicoes.detalhe(conn, r["reajuste_medicao_id"])
    assert (m["tipo"], m["numero"], m["competencia"], m["estado"]) == ("reajuste", 3, "2026-07", "prevista")
    assert (m["valor_protocolado_centavos"], m["valor_protocolado_origem"]) == (1_300_01, "manual")
    assert (m["data_base_mes"], m["ciclo"]) == ("2024-06", 2026)
    (g,) = reajuste.competencias_por_ciclo(conn, contrato_id)
    assert [(x["competencia"], x["estado"], x["pedido_centavos"]) for x in g["competencias"]] == [
        ("2026-07", "pedida", 1_300_01)]
    assert json.loads(_evento(conn, "medicao.criar", r["reajuste_medicao_id"])["depois"])["ciclo"] == 2026


def test_planilha_sem_reajuste_nao_cria_a_de_reajuste(conn, contrato_id):
    from app import medicao_planilhas
    _base(conn, contrato_id)
    r = medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-07", "2026-07-01", "2026-07-31", 1),
                                    ANEXOS)
    assert r["reajuste_medicao_id"] is None
    assert conn.execute("SELECT COUNT(*) FROM medicoes WHERE tipo='reajuste'").fetchone()[0] == 0


def test_envio_da_planilha_congela_o_pedido_do_reajuste_e_definir_valor_recusa(conn, contrato_id):
    """Issue #590: enviada a planilha/carta (aqui por fora), `definir_valor` recusa o pedido do reajuste de mesmo nº
    e competencia; o atestado (glosa) segue livre e a de reajuste continua prevista."""
    from app import medicao_planilhas
    _base(conn, contrato_id)
    r = medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(3, "2026-07", "2026-07-01", "2026-07-31", 100_00,
                                                                     reajuste_centavos=1_300_01), ANEXOS)
    rid = r["reajuste_medicao_id"]
    medicao_planilhas.registrar_envio_externo(conn, 1, r["medicao_id"], {"enviado_em": "2026-08-03", "meio": "SIGA"})
    with pytest.raises(ValueError, match="congelou no envio da planilha/carta"):
        medicoes.definir_valor(conn, 1, rid, "protocolado", 1, "manual")
    medicoes.definir_valor(conn, 1, rid, "atestado", 1_200_00, "manual")
    m = medicoes.detalhe(conn, rid)
    assert (m["estado"], m["valor_protocolado_centavos"], m["valor_atestado_centavos"]) == (
        "prevista", 1_300_01, 1_200_00)


def test_planilha_com_reajuste_completa_a_prevista_de_reajuste_existente(conn, contrato_id):
    """Issue #276: a de reajuste ja' prevista (sem planilha/carta) recebe o pedido, a data-base e o ciclo, com a
    auditoria do antes; a de outra competencia e' recusada sem gravar nada."""
    from app import medicao_planilhas
    _base(conn, contrato_id)
    rid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 2, "tipo": "reajuste",
                                   "competencia": "2026-08"})
    r = medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(2, "2026-08", "2026-08-01", "2026-08-31", 5_00,
                                                                     reajuste_centavos=99_99), ANEXOS)
    assert r["reajuste_medicao_id"] == rid
    m = medicoes.detalhe(conn, rid)
    assert (m["estado"], m["valor_protocolado_centavos"], m["data_base_mes"], m["ciclo"]) == (
        "prevista", 99_99, "2024-06", 2026)
    assert json.loads(_evento(conn, "medicao.reajuste_da_planilha", rid)["antes"])["valor_protocolado_centavos"] is None

    medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 4, "tipo": "reajuste", "competencia": "2026-09"})
    with pytest.raises(ValueError, match="com a competência 09/2026"):
        medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(4, "2026-10", "2026-10-01", "2026-10-31", 1,
                                                                     reajuste_centavos=1), ANEXOS)
    assert conn.execute("SELECT COUNT(*) FROM medicoes WHERE tipo='execucao' AND numero=4").fetchone()[0] == 0


def test_planilha_com_reajuste_em_contrato_de_duas_bases_exige_a_escolha(conn, contrato_id):
    from app import medicao_planilhas
    _base(conn, contrato_id, "2024-04", "itens SICRO")
    _base(conn, contrato_id, "2024-06")
    dados = _planilha(1, "2026-05", "2026-05-01", "2026-05-31", 1, reajuste_centavos=10_01)
    with pytest.raises(ValueError, match="Escolha a data-base do reajuste"):
        medicao_planilhas.registrar(conn, 1, contrato_id, dados, ANEXOS)
    assert conn.execute("SELECT COUNT(*) FROM medicoes").fetchone()[0] == 0
    r = medicao_planilhas.registrar(conn, 1, contrato_id, {**dados, "reajuste_data_base": "2024-04"}, ANEXOS)
    m = medicoes.detalhe(conn, r["reajuste_medicao_id"])
    assert (m["data_base_mes"], m["ciclo"], m["valor_protocolado_centavos"]) == ("2024-04", 2026, 10_01)


def test_prevista_de_reajuste_com_data_base_gravada_dispensa_a_escolha(conn, contrato_id):
    """Code-review da #276: com duas bases, a prevista de reajuste que ja' tem data-base nao exige a escolha de novo."""
    from app import medicao_planilhas
    _base(conn, contrato_id, "2024-04", "itens SICRO")
    _base(conn, contrato_id, "2024-06")
    rid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "reajuste",
                                   "competencia": "2026-05", "data_base_mes": "2024-06", "ciclo": 2025})
    r = medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-05", "2026-05-01", "2026-05-31", 1,
                                                                     reajuste_centavos=3_01), ANEXOS)
    assert r["reajuste_medicao_id"] == rid
    m = medicoes.detalhe(conn, rid)
    assert (m["data_base_mes"], m["ciclo"], m["valor_protocolado_centavos"]) == ("2024-06", 2025, 3_01)


def test_reajuste_antes_do_primeiro_aniversario_e_recusado(conn, contrato_id):
    """Code-review da #276: sem ciclo (competencia antes do 1o aniversario da data-base) a medicao de reajuste nao
    nasce: ficaria fora da aba Reajuste."""
    from app import medicao_planilhas, reajuste
    _base(conn, contrato_id, "2025-08")
    with pytest.raises(ValueError, match="anterior ao primeiro reajuste da data-base 08/2025"):
        reajuste.base_e_ciclo_da_medicao(conn, contrato_id, "2026-03", None)
    with pytest.raises(ValueError, match="anterior ao primeiro reajuste"):
        medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-03", "2026-03-01", "2026-03-31", 1,
                                                                     reajuste_centavos=1), ANEXOS)
    assert conn.execute("SELECT COUNT(*) FROM medicoes").fetchone()[0] == 0


def test_reajuste_ja_lancado_em_outra_medicao_nao_e_sugerido_nem_pedido_de_novo(conn, contrato_id):
    """Revisor da PR #580, Critico: a medicao 6 de reajuste de 08/2026 ja' pede R$ 50.000,00; a planilha/carta nº 5
    da mesma competencia nao sugere o reajuste de novo e o registro com valor e' recusado (o pedido contaria duas
    vezes). Cancelada nao conta."""
    from app import medicao_planilhas, reajuste
    _base(conn, contrato_id)
    _prevista(conn, contrato_id, "2026-08", 50_000_01, "pleito")
    seis = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 6, "tipo": "reajuste",
                                    "competencia": "2026-08", "valor_centavos": 50_000_01, "data_base_mes": "2024-06",
                                    "ciclo": 2026})
    (b,) = reajuste.sugestao_da_medicao(conn, contrato_id, "2026-08", 5)["bases"]
    assert (b["valor_centavos"], b["origem_texto"], b["ja_pedido_em"]) == (None, None, [6])
    assert b["aviso"] == "já pedido na medição 6 de reajuste"
    with pytest.raises(ValueError, match="já está na medição 6 de reajuste"):
        medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(5, "2026-08", "2026-08-01", "2026-08-31", 1,
                                                                     reajuste_centavos=50_000_01), ANEXOS)
    assert conn.execute("SELECT COUNT(*) FROM medicoes").fetchone()[0] == 1
    # rodada 2: vazia tambem nao nasce (o pedido entraria depois pela edicao de valor)
    with pytest.raises(ValueError, match="já está na medição 6"):
        reajuste.base_e_ciclo_da_medicao(conn, contrato_id, "2026-08", None, 7)
    medicoes.mudar_estado(conn, 1, seis, "cancelada", "lançada no nº errado")
    (b,) = reajuste.sugestao_da_medicao(conn, contrato_id, "2026-08", 5)["bases"]
    assert (b["valor_centavos"], b["aviso"]) == (50_000_01, None)
    assert reajuste.base_e_ciclo_da_medicao(conn, contrato_id, "2026-08", None, 7) == ("2024-06", 2026)


def test_pedido_informado_depois_nao_contorna_a_trava_do_dobro(conn, contrato_id):
    """Revisor, rodada 2 da PR #580, Critico: a 2a medicao de reajuste da mesma competencia e data-base, criada vazia
    por qualquer caminho, nao recebe o pedido pela edicao de valor. A medicao sem data-base gravada (legado) segue."""
    _base(conn, contrato_id)
    comum = {"contrato_id": contrato_id, "tipo": "reajuste", "competencia": "2026-08"}
    seis = medicoes.criar(conn, 1, {**comum, "numero": 6, "valor_centavos": 50_000_01, "data_base_mes": "2024-06",
                                    "ciclo": 2026})
    sete = medicoes.criar(conn, 1, {**comum, "numero": 7, "data_base_mes": "2024-06", "ciclo": 2026})
    with pytest.raises(ValueError, match="já está na medição 6 de reajuste"):
        medicoes.definir_valor(conn, 1, sete, "protocolado", 50_000_01, "manual")
    assert medicoes.detalhe(conn, sete)["valor_protocolado_centavos"] is None
    medicoes.definir_valor(conn, 1, sete, "atestado", 1_00, "manual")      # o aprovado nao e' pedido
    legado = medicoes.criar(conn, 1, {**comum, "numero": 8})
    medicoes.definir_valor(conn, 1, legado, "protocolado", 3_01, "manual")
    medicoes.mudar_estado(conn, 1, seis, "cancelada", "lançada no nº errado")
    with pytest.raises(ValueError, match="já está na medição 8 de reajuste"):
        medicoes.definir_valor(conn, 1, sete, "protocolado", 50_000_01, "manual")


def test_prevista_do_numero_com_pedido_sugere_o_proprio_pedido(conn, contrato_id):
    """Revisor da PR #580, Aviso: o pedido digitado na prevista (R$ 10.000,00) nao e' trocado pelo apostilado
    (R$ 9.876,54) sem a pessoa ver; rodada 2: o apostilado diferente e' dito no aviso (o apostilado manda)."""
    from app import reajuste
    _base(conn, contrato_id)
    _prevista(conn, contrato_id, "2026-08", 9_876_54, "apostilamento", termo="001/2026")
    medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 2, "tipo": "reajuste", "competencia": "2026-08",
                             "valor_centavos": 10_000_00, "data_base_mes": "2024-06", "ciclo": 2026})
    (b,) = reajuste.sugestao_da_medicao(conn, contrato_id, "2026-08", 2)["bases"]
    assert (b["valor_centavos"], b["origem"], b["origem_texto"]) == (
        10_000_00, "prevista", "pedido já registrado na prevista")
    assert b["aviso"] == "pedido já registrado na prevista; apostilado no termo 001/2026 em R$ 9.876,54"


def test_previsao_negativa_vira_sugestao_com_o_sinal(conn, contrato_id):
    """Issue #589 (decisao do Leo de 08/11/2026): o apostilamento negativo (indice deflacionario) pre-preenche o
    Reajuste com o sinal, com a origem, e a medicao de reajuste nasce com o pedido negativo (centavo impar)."""
    from app import medicao_planilhas, reajuste
    _base(conn, contrato_id)
    _prevista(conn, contrato_id, "2026-08", -10_01, "apostilamento", termo="002/2026")
    s = reajuste.sugestao_da_medicao(conn, contrato_id, "2026-08")
    (b,) = s["bases"]
    assert (b["valor_centavos"], b["origem_texto"], b["aviso"]) == (-10_01, "apostilado no termo 002/2026", None)
    assert s["data_base_mes"] == "2024-06"
    r = medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-08", "2026-08-01", "2026-08-31", 1_00,
                                                                     reajuste_centavos=-10_01), ANEXOS)
    m = medicoes.detalhe(conn, r["reajuste_medicao_id"])
    assert (m["tipo"], m["estado"], m["valor_protocolado_centavos"]) == ("reajuste", "prevista", -10_01)


def test_ciclo_pela_forca_da_origem_e_empate_em_dois_ciclos_recusa(conn, contrato_id):
    """Gate Sol da PR #580: com previsoes da competencia em dois ciclos, vale a origem mais forte (o apostilado do
    ciclo 2026 vence o pleito do ciclo 2025 do aniversario); empate de forca em ciclos diferentes nao sugere e
    recusa a gravacao."""
    from app import reajuste
    _base(conn, contrato_id)
    _prevista(conn, contrato_id, "2026-05", 1_00, "pleito", ciclo=2025)
    _prevista(conn, contrato_id, "2026-05", 2_01, "apostilamento", ciclo=2026, termo=None)
    (b,) = reajuste.sugestao_da_medicao(conn, contrato_id, "2026-05")["bases"]
    assert (b["ciclo"], b["valor_centavos"], b["origem_texto"]) == (2026, 2_01, "apostilado em termo sem número")
    _prevista(conn, contrato_id, "2026-04", 3_00, "manual", ciclo=2025)
    _prevista(conn, contrato_id, "2026-04", 4_00, "manual", ciclo=2026)
    (b,) = reajuste.sugestao_da_medicao(conn, contrato_id, "2026-04")["bases"]
    assert (b["ciclo"], b["valor_centavos"], b["ciclos_em_conflito"]) == (None, None, [2025, 2026])
    assert b["aviso"] == "previsão em mais de um ciclo (2025, 2026)"
    with pytest.raises(ValueError, match="^A previsão de reajuste de 04/2026 está nos ciclos 2025 e 2026 da data-base "
                                         "06/2024; a correção é pelo pleito ou pelo cadastro$"):
        reajuste.base_e_ciclo_da_medicao(conn, contrato_id, "2026-04", None)


def test_prevista_de_reajuste_com_pedido_do_espelho_recusa_em_minuscula(conn, contrato_id):
    from app import medicao_planilhas
    _base(conn, contrato_id)
    rid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 2, "tipo": "reajuste",
                                   "competencia": "2026-08"})
    conn.execute("UPDATE medicoes SET valor_protocolado_centavos=1, valor_protocolado_origem='espelho' WHERE id=?",
                 (rid,)); conn.commit()
    with pytest.raises(ValueError, match="^O pedido da medição 2 de reajuste vem do espelho"):
        medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(2, "2026-08", "2026-08-01", "2026-08-31", 1,
                                                                     reajuste_centavos=1), ANEXOS)


def test_reajuste_so_acompanha_a_planilha_de_execucao(conn, contrato_id):
    from app import medicao_planilhas
    _base(conn, contrato_id)
    with pytest.raises(ValueError, match="só a planilha/carta de execução"):
        medicao_planilhas.registrar(conn, 1, contrato_id, {**_planilha(1, "2026-07", "2026-07-01", "2026-07-31", 1),
                                                           "tipo": "projeto", "reajuste_centavos": 1}, ANEXOS)


def test_execucao_e_projeto_continuam_recusando_valor_negativo(conn, contrato_id):
    """Issue #589: so' a medicao de reajuste aceita pedido negativo; execucao e projeto recusam no servidor (antes de
    gravar) e no banco (CHECK da migracao 078). O reajuste negativo grava, no banco tambem."""
    import sqlite3
    for tipo in ("execucao", "projeto"):
        with pytest.raises(ValueError, match="não aceita valor negativo"):
            medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": tipo,
                                     "competencia": "2026-05", "valor_centavos": -1})
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, valor_protocolado_centavos) "
                         "VALUES (?, 9, ?, '2026-05', -1)", (contrato_id, tipo))
        conn.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, valor_atestado_centavos) "
                         "VALUES (?, 9, ?, '2026-05', -1)", (contrato_id, tipo))
        conn.rollback()
    mid = medicoes.criar(conn, 1, {"contrato_id": contrato_id, "numero": 1, "tipo": "reajuste",
                                   "competencia": "2026-05", "valor_centavos": -10_01})
    assert medicoes.detalhe(conn, mid)["valor_protocolado_centavos"] == -10_01


def test_planilha_de_execucao_nao_recebe_valor_negativo(conn, contrato_id):
    """Issue #589: o valor da planilha/carta de execucao continua sem sinal; so' o reajuste que a acompanha aceita."""
    from app import medicao_planilhas
    with pytest.raises(ValueError, match="não aceita valor negativo"):
        medicao_planilhas.registrar(conn, 1, contrato_id, _planilha(1, "2026-05", "2026-05-01", "2026-05-31", -1),
                                    ANEXOS)
