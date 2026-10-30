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
