"""`cadastro corrigir-medicoes`: correcao de medicoes existentes por YAML. Dados ficticios (cadastro-exemplo)."""
import json

import pytest
import yaml
from app import auth, cli, correcao_medicoes, db


@pytest.fixture
def cenario(tmp_path, monkeypatch):
    monkeypatch.delenv("DASH_CADASTRO_DIR", raising=False)
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn()
    db.migrate(c)
    auth.criar_usuario(c, "Leo", "leo@l.com", "senha-forte-123", "admin")
    assert cli.main(["cadastro", "aplicar", "--usuario", "leo@l.com"]) == 0
    cid = c.execute("SELECT id FROM contratos WHERE nome_curto='Obra Própria'").fetchone()[0]
    uid = c.execute("SELECT id FROM usuarios WHERE email='leo@l.com'").fetchone()[0]
    yield c, cid, uid
    c.close()


def _medicao(c, cid, numero, estado="protocolada", tipo="execucao", valor=100_001):
    mid = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos,"
                    " valor_protocolado_origem) VALUES (?,?,?,'2025-06',?,?,'manual')",
                    (cid, numero, tipo, estado, valor)).lastrowid
    c.commit()
    return mid


def _nota(c, numero, valor=100_001, centro="9.001.001", paga=False):
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, emissao, valor_centavos, situacao,"
                    " centro_custo) VALUES (1,?,?,?,'2025-07-01',?,'ativa',?)",
                    (900 + numero, str(numero), numero, valor, centro)).lastrowid
    if paga:
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos,"
                  " status_lan, data_baixa) VALUES (1,?,?,?,?,?,1,'2025-08-01')",
                  (900 + numero, nid, 900 + numero, valor - 7_001, valor - 7_001))
    c.commit()
    return nid


def _ligar(c, mid, nid, valor=100_001):
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
              "VALUES (?,?,?,'detectado','t')", (mid, nid, valor))
    c.commit()


def _rodar(c, uid, ops, ensaio=False):
    """O relatorio; com erro (nada gravado), o relatorio que veio na recusa."""
    try:
        return correcao_medicoes.executar(c, uid, ops, ensaio=ensaio)
    except correcao_medicoes.CorrecaoRecusada as e:
        return e.relatorio


def _estado(c, mid):
    return c.execute("SELECT estado FROM medicoes WHERE id=?", (mid,)).fetchone()[0]


def _ativas(c, mid):
    return [r[0] for r in c.execute("SELECT nota_id FROM nf_alocacoes WHERE medicao_id=? AND desfeita_em IS NULL",
                                    (mid,))]


def _correcoes(c, mid):
    return [(json.loads(r[0]), json.loads(r[1])) for r in c.execute(
        "SELECT antes, depois FROM audit_log WHERE acao='medicao.correcao_cadastro' AND entidade_id=?", (str(mid),))]


# ------------------------------------------------------------------ operacoes

def test_cancelar_desfaz_o_vinculo_sem_apagar_e_audita(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1)
    nid = _nota(c, 501)
    _ligar(c, mid, nid)
    rel = _rodar(c, uid, [{"operacao": "cancelar", "medicao_id": mid, "fonte": "ofício de cancelamento"}])
    assert rel["feitos"] == 1 and rel["erros"] == 0
    assert _estado(c, mid) == "cancelada" and _ativas(c, mid) == []
    assert c.execute("SELECT COUNT(*) FROM nf_alocacoes WHERE medicao_id=? AND desfeita_em IS NOT NULL",
                     (mid,)).fetchone()[0] == 1
    assert c.execute("SELECT motivo_represamento FROM medicoes WHERE id=?", (mid,)).fetchone()[0] == \
        "ofício de cancelamento"
    antes, depois = _correcoes(c, mid)[0]
    assert antes["estado"] == "protocolada" and antes["nfs"] == ["501/1"]
    assert depois["estado"] == "cancelada" and depois["nfs"] == []
    assert depois["origem"] == "correção de cadastro" and depois["fonte"] == "ofício de cancelamento"


def test_obra_numero_e_tipo_resolvem_a_medicao(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 3, estado="prevista")
    _rodar(c, uid, [{"operacao": "cancelar", "obra": "obra propria", "numero": 3, "tipo": "execucao",
                     "fonte": "planilha consolidada"}])
    assert _estado(c, mid) == "cancelada"


def test_reabrir_volta_a_protocolada_e_fecha_pelo_rm_se_a_nota_foi_paga(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1, estado="cancelada")
    nid = _nota(c, 502, paga=True)
    _ligar(c, mid, nid)
    rel = _rodar(c, uid, [{"operacao": "reabrir", "medicao_id": mid, "fonte": "extrato do RM: nota paga"}])
    assert rel["itens"][0]["antes"] == "cancelada"
    assert _estado(c, mid) == "recebida"
    assert c.execute("SELECT congelada FROM medicoes WHERE id=?", (mid,)).fetchone()[0] == 1


def test_reabrir_sem_nf_fica_protocolada_com_aviso(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1, estado="desistida")
    rel = _rodar(c, uid, [{"operacao": "reabrir", "medicao_id": mid, "fonte": "ofício"}])
    assert _estado(c, mid) == "protocolada"
    assert any("sem NF ligada" in d for d in rel["itens"][0]["detalhes"])


def test_trocar_tipo_e_numero_e_recusa_chave_existente(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 2)
    _medicao(c, cid, 2, tipo="reajuste", estado="cancelada")
    rel = _rodar(c, uid, [{"operacao": "trocar_tipo", "medicao_id": mid, "novo_tipo": "reajuste",
                           "fonte": "boletim"}])
    assert rel["erros"] == 1 and "já existe" in rel["itens"][0]["erro"]
    _rodar(c, uid, [{"operacao": "trocar_tipo", "medicao_id": mid, "novo_tipo": "reajuste", "novo_numero": 3,
                     "fonte": "boletim"}])
    assert tuple(c.execute("SELECT tipo, numero FROM medicoes WHERE id=?", (mid,)).fetchone()) == ("reajuste", 3)
    # por chave, a antiga que sumiu e a nova que existe e' "ja' feito"
    rel = _rodar(c, uid, [{"operacao": "trocar_tipo", "obra": "Obra Própria", "numero": 2, "tipo": "execucao",
                           "novo_tipo": "reajuste", "novo_numero": 3, "fonte": "boletim"}])
    assert rel["itens"][0]["situacao"] == "já feito"


def test_desligar_nf_marca_desfeita_e_nao_apaga(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1)
    nid = _nota(c, 503)
    _ligar(c, mid, nid)
    _rodar(c, uid, [{"operacao": "desligar_nf", "medicao_id": mid, "nf": 503, "fonte": "NF de outra medição"}])
    assert _ativas(c, mid) == []
    motivo = c.execute("SELECT motivo_desfazer FROM nf_alocacoes WHERE nota_id=?", (nid,)).fetchone()[0]
    assert motivo.startswith("Desfeita à mão: ")
    rel = _rodar(c, uid, [{"operacao": "desligar_nf", "medicao_id": mid, "nf": "503", "fonte": "idem"}])
    assert rel["itens"][0]["situacao"] == "já feito"


def test_ligar_nf_confere_centro_cobertura_e_fecha_pelo_rm(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1, valor=200_001)
    _nota(c, 504, valor=100_001, paga=True)
    _nota(c, 505, valor=100_000, paga=True)
    _nota(c, 506, valor=200_001, centro="9.999.999")
    # nota de outro centro: recusa; com forcar_centro passa e fica na auditoria
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [506], "fonte": "NF"}])
    assert "outra obra" in rel["itens"][0]["erro"]
    # uma nota so' nao cobre: recusa sem parcial
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [504], "fonte": "NF"}])
    assert "somam R$ 1.000,01" in rel["itens"][0]["erro"]
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [504, 505], "fonte": "NFs no RM"}])
    assert rel["feitos"] == 1 and len(_ativas(c, mid)) == 2
    assert _estado(c, mid) == "recebida"
    assert any("R$ 1.000,01" in d for d in rel["itens"][0]["detalhes"])


def test_ligar_nf_forcar_centro_e_parcial(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1, valor=300_001)
    _nota(c, 507, valor=100_001, centro="9.999.999", paga=True)
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [507], "forcar_centro": True,
                           "parcial": True, "fonte": "NF emitida no centro errado"}])
    assert rel["feitos"] == 1 and _estado(c, mid) == "protocolada"
    _, depois = _correcoes(c, mid)[0]
    assert depois["centro_forcado"][0]["nf"] == "507"


def test_ligar_nf_em_medicao_recebida_sem_nota(cenario):
    # Paga, mas o vinculo com a nota faltou: a NF entra e o estado continua recebida
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1, estado="recebida", valor=100_001)
    _nota(c, 509, valor=100_001, paga=True)
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [509], "fonte": "NF paga no RM"}])
    assert rel["feitos"] == 1 and len(_ativas(c, mid)) == 1 and _estado(c, mid) == "recebida"
    cancelada = _medicao(c, cid, 2, estado="cancelada")
    _nota(c, 510, valor=100_001)
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": cancelada, "nfs": [510], "fonte": "NF"}])
    assert "não recebe NF" in rel["itens"][0]["erro"]


def test_ligar_nf_recusa_nota_ja_ligada_a_outra_medicao(cenario):
    c, cid, uid = cenario
    m1, m2 = _medicao(c, cid, 1), _medicao(c, cid, 2)
    nid = _nota(c, 508)
    _ligar(c, m1, nid)
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": m2, "nfs": [508], "fonte": "NF"}])
    assert "desligue-a lá antes" in rel["itens"][0]["erro"]
    # desligar e ligar no mesmo arquivo
    rel = _rodar(c, uid, [{"operacao": "desligar_nf", "medicao_id": m1, "nf": 508, "fonte": "NF"},
                          {"operacao": "ligar_nf", "medicao_id": m2, "nfs": [508], "fonte": "NF"}])
    assert rel["feitos"] == 2 and _ativas(c, m2) == [nid] and _ativas(c, m1) == []


def _nota_serie(c, numero, idmov, serie, valor=100_001, centro="9.001.001"):
    """Nota com numero repetido no RM (outra serie, outro movimento)."""
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, serie, emissao, valor_centavos,"
                    " situacao, centro_custo) VALUES (1,?,?,?,?,'2025-07-01',?,'ativa',?)",
                    (idmov, str(numero), numero, serie, valor, centro)).lastrowid
    c.commit()
    return nid


def test_ligar_nf_numero_repetido_sem_desambiguar_e_recusado(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1, valor=100_001)
    _nota_serie(c, 1856, 7001, "1")
    _nota_serie(c, 1856, 7002, "2")
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [1856], "fonte": "NF"}])
    erro = rel["itens"][0]["erro"]
    assert "NF 1856 é ambígua" in erro and "idmov 7001 (série 1" in erro and "idmov 7002 (série 2" in erro
    assert "{idmov: N}" in erro
    assert _ativas(c, mid) == []


def test_ligar_nf_por_idmov_liga_a_nota_certa(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1, valor=100_001)
    _nota_serie(c, 1856, 7001, "1")
    certa = _nota_serie(c, 1856, 7002, "2")
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [{"idmov": 7002}],
                           "fonte": "NF no RM (série 2)"}])
    assert rel["feitos"] == 1 and _ativas(c, mid) == [certa]
    assert "NF 1856 (R$ 1.000,01) ligada" in rel["itens"][0]["detalhes"][0]
    # rodar de novo: ja' feito
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [{"idmov": 7002}], "fonte": "NF"}])
    assert rel["itens"][0]["situacao"] == "já feito"


def test_ligar_nf_por_numero_e_serie_e_idmov_inexistente(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1, valor=100_001)
    certa = _nota_serie(c, 1856, 7001, "1")
    _nota_serie(c, 1856, 7002, "2")
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [{"idmov": 9999}], "fonte": "NF"}])
    assert "idmov 9999 não encontrada (ativa) na coligada 1" in rel["itens"][0]["erro"]
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [{"numero": 1856, "idmov": 7001}],
                           "fonte": "NF"}])
    assert "idmov ou numero + serie" in rel["itens"][0]["erro"]
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [{"numero": 1856, "serie": "1"}],
                           "fonte": "NF série 1"}])
    assert rel["feitos"] == 1 and _ativas(c, mid) == [certa]


def test_cancelar_recebida_como_duplicata_desliga_a_nota_e_audita(cenario):
    c, cid, uid = cenario
    verdadeira = _medicao(c, cid, 49, estado="recebida")
    dup = _medicao(c, cid, 45, estado="recebida", valor=233_015)
    nid = _nota(c, 511, valor=233_015, paga=True)
    _ligar(c, dup, nid, valor=233_015)
    op = {"operacao": "cancelar", "medicao_id": dup, "duplicata_de": verdadeira,
          "motivo": "carga antiga lançou a 49ª duas vezes", "fonte": "planilha consolidada"}
    # ensaio mostra o que muda e nao grava
    antes = _foto(c)
    rel = _rodar(c, uid, [op], ensaio=True)
    item = rel["itens"][0]
    assert rel["feitos"] == 1 and item["antes"] == "recebida" and item["depois"] == "cancelada"
    assert any("NF 511 (R$ 2.330,15) desligada" in d for d in item["detalhes"])
    assert any("duplicata da medição 49 de execução" in d and f"id {verdadeira}" in d for d in item["detalhes"])
    assert _foto(c) == antes
    rel = _rodar(c, uid, [op])
    assert rel["feitos"] == 1 and _estado(c, dup) == "cancelada" and _ativas(c, dup) == []
    # a nota volta livre (vinculo desfeito, nada apagado) e a verdadeira nao muda
    assert c.execute("SELECT COUNT(*) FROM nf_alocacoes WHERE nota_id=? AND desfeita_em IS NULL",
                     (nid,)).fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM nf_alocacoes WHERE nota_id=?", (nid,)).fetchone()[0] == 1
    assert _estado(c, verdadeira) == "recebida"
    motivo = c.execute("SELECT motivo_represamento FROM medicoes WHERE id=?", (dup,)).fetchone()[0]
    assert "carga antiga lançou a 49ª duas vezes" in motivo and f"id {verdadeira}" in motivo
    antes_a, depois_a = _correcoes(c, dup)[0]
    assert antes_a["estado"] == "recebida" and antes_a["nfs"] == ["511/1"]
    assert depois_a["estado"] == "cancelada" and depois_a["duplicata_de"] == verdadeira
    assert depois_a["motivo_cancelamento"] == "carga antiga lançou a 49ª duas vezes"
    est = c.execute("SELECT antes, depois FROM audit_log WHERE acao='medicao.estado' AND entidade_id=?",
                    (str(dup),)).fetchall()
    assert json.loads(est[-1][0])["estado"] == "recebida" and json.loads(est[-1][1])["estado"] == "cancelada"
    # rodar de novo: ja' feito
    assert _rodar(c, uid, [op])["itens"][0]["situacao"] == "já feito"


def test_cancelar_duplicata_em_estado_que_ja_se_cancela(cenario):
    c, cid, uid = cenario
    verdadeira = _medicao(c, cid, 15)
    dup = _medicao(c, cid, 11)
    rel = _rodar(c, uid, [{"operacao": "cancelar", "medicao_id": dup, "duplicata_de": verdadeira,
                           "motivo": "lançada duas vezes", "fonte": "planilha"}])
    assert rel["feitos"] == 1 and _estado(c, dup) == "cancelada" and _estado(c, verdadeira) == "protocolada"
    assert _correcoes(c, dup)[0][1]["duplicata_de"] == verdadeira


def test_cancelar_recebida_exige_duplicata_e_motivo(cenario):
    c, cid, uid = cenario
    verdadeira = _medicao(c, cid, 15, estado="recebida")
    dup = _medicao(c, cid, 11, estado="recebida")
    # sem duplicata_de: recebida continua nao se cancelando
    rel = _rodar(c, uid, [{"operacao": "cancelar", "medicao_id": dup, "fonte": "x"}])
    assert "não se cancela" in rel["itens"][0]["erro"]
    # sem motivo: recusado
    rel = _rodar(c, uid, [{"operacao": "cancelar", "medicao_id": dup, "duplicata_de": verdadeira, "fonte": "x"}])
    assert "diga o motivo" in rel["itens"][0]["erro"]
    # duplicata de si mesma, de medicao inexistente, cancelada ou de outro contrato: recusado
    rel = _rodar(c, uid, [{"operacao": "cancelar", "medicao_id": dup, "duplicata_de": dup, "motivo": "m",
                           "fonte": "x"}])
    assert "ela mesma" in rel["itens"][0]["erro"]
    rel = _rodar(c, uid, [{"operacao": "cancelar", "medicao_id": dup, "duplicata_de": 9999, "motivo": "m",
                           "fonte": "x"}])
    assert "9999 não existe" in rel["itens"][0]["erro"]
    cancelada = _medicao(c, cid, 20, estado="cancelada")
    rel = _rodar(c, uid, [{"operacao": "cancelar", "medicao_id": dup, "duplicata_de": cancelada, "motivo": "m",
                           "fonte": "x"}])
    assert "está cancelada" in rel["itens"][0]["erro"]
    outro = c.execute("SELECT id FROM contratos WHERE id<>? LIMIT 1", (cid,)).fetchone()[0]
    alheia = _medicao(c, outro, 1, estado="recebida")
    rel = _rodar(c, uid, [{"operacao": "cancelar", "medicao_id": dup, "duplicata_de": alheia, "motivo": "m",
                           "fonte": "x"}])
    assert "outro contrato" in rel["itens"][0]["erro"]
    # motivo sem duplicata_de: recusado (o motivo do cancelamento comum e' a fonte)
    rel = _rodar(c, uid, [{"operacao": "cancelar", "medicao_id": dup, "motivo": "m", "fonte": "x"}])
    assert "motivo só vale com duplicata_de" in rel["itens"][0]["erro"]
    assert _estado(c, dup) == "recebida"


def test_protocolar_promove_congela_e_e_idempotente(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1, estado="prevista")
    ops = [{"operacao": "protocolar", "medicao_id": mid, "data": "2025-07-10", "processo": "PROC-0001",
            "fonte": "recibo do protocolo"}]
    rel = _rodar(c, uid, ops)
    assert rel["itens"][0]["antes"] == "prevista" and _estado(c, mid) == "protocolada"
    p = c.execute("SELECT data, numero_processo, origem, etapa FROM medicao_protocolos WHERE medicao_id=?",
                  (mid,)).fetchall()
    assert [tuple(r) for r in p] == [("2025-07-10", "PROC-0001", "manual", "nota")]
    assert c.execute("SELECT congelada FROM medicoes WHERE id=?", (mid,)).fetchone()[0] == 1
    rel = _rodar(c, uid, ops)
    assert rel["itens"][0]["situacao"] == "já feito"
    assert c.execute("SELECT COUNT(*) FROM medicao_protocolos WHERE medicao_id=?", (mid,)).fetchone()[0] == 1


def test_estado_transicao_permitida_e_recusada(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1)
    rel = _rodar(c, uid, [{"operacao": "estado", "medicao_id": mid, "novo": "recebida", "data": "2025-09-01",
                           "motivo": "baixa conferida no extrato", "fonte": "extrato"}])
    assert rel["feitos"] == 1 and _estado(c, mid) == "recebida"
    assert c.execute("SELECT recebida_em FROM medicoes WHERE id=?", (mid,)).fetchone()[0] == "2025-09-01"
    rel = _rodar(c, uid, [{"operacao": "estado", "medicao_id": mid, "novo": "prevista", "fonte": "x"}])
    assert "Transição inválida" in rel["itens"][0]["erro"]


# ------------------------------------------------------------------ ensaio, atomicidade, idempotencia

def _foto(c):
    return ([tuple(r) for r in c.execute("SELECT * FROM medicoes ORDER BY id")],
            [tuple(r) for r in c.execute("SELECT * FROM nf_alocacoes ORDER BY id")],
            c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM medicao_protocolos").fetchone()[0])


def test_ensaio_relata_e_nao_grava(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1)
    _ligar(c, mid, _nota(c, 509))
    antes = _foto(c)
    rel = _rodar(c, uid, [{"operacao": "cancelar", "medicao_id": mid, "fonte": "ofício"}], ensaio=True)
    assert rel["ensaio"] and rel["feitos"] == 1
    assert rel["itens"][0]["antes"] == "protocolada" and rel["itens"][0]["depois"] == "cancelada"
    assert any("NF 509 (R$ 1.000,01) desligada" in d for d in rel["itens"][0]["detalhes"])
    assert _foto(c) == antes


def test_operacao_invalida_recusa_o_arquivo_inteiro(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1)
    antes = _foto(c)
    ops = [{"operacao": "cancelar", "medicao_id": mid, "fonte": "ofício"},
           {"operacao": "protocolar", "medicao_id": mid, "fonte": "sem data"},
           {"operacao": "cancelar", "medicao_id": 9999, "fonte": "x"},
           {"operacao": "apagar", "medicao_id": mid, "fonte": "x"},
           {"operacao": "cancelar", "medicao_id": mid}]
    with pytest.raises(correcao_medicoes.CorrecaoRecusada) as e:
        correcao_medicoes.executar(c, uid, ops, ensaio=False)
    erros = [i.get("erro") for i in e.value.relatorio["itens"]]
    assert erros[0] is None
    assert "diga a data" in erros[1] and "não existe" in erros[2]
    assert "operação desconhecida" in erros[3] and "falta a fonte" in erros[4]
    assert _foto(c) == antes


def test_rodar_duas_vezes_nao_duplica(cenario):
    c, cid, uid = cenario
    m1, m2 = _medicao(c, cid, 1), _medicao(c, cid, 2, estado="prevista")
    ops = [{"operacao": "cancelar", "medicao_id": m1, "fonte": "ofício"},
           {"operacao": "protocolar", "medicao_id": m2, "data": "2025-07-10", "fonte": "recibo"}]
    assert _rodar(c, uid, ops)["feitos"] == 2
    depois = _foto(c)
    rel = _rodar(c, uid, ops)
    assert rel["feitos"] == 0 and rel["ja_feitos"] == 2
    assert _foto(c) == depois


# ------------------------------------------------------------------ CLI

def test_cli_ensaio_e_gravacao(cenario, tmp_path, capsys):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1)
    arq = tmp_path / "correcoes.yaml"
    arq.write_text(yaml.safe_dump([{"operacao": "cancelar", "obra": "Obra Própria", "numero": 1,
                                    "tipo": "execucao", "fonte": "ofício"}], allow_unicode=True), "utf-8")
    assert cli.main(["cadastro", "corrigir-medicoes", str(arq), "--ensaio", "--usuario", "leo@l.com"]) == 0
    saida = capsys.readouterr().out
    assert "ENSAIO (nada foi gravado)" in saida and "protocolada → cancelada" in saida
    assert _estado(c, mid) == "protocolada"
    assert cli.main(["cadastro", "corrigir-medicoes", str(arq), "--usuario", "leo@l.com"]) == 0
    assert "GRAVADO" in capsys.readouterr().out and _estado(c, mid) == "cancelada"
    assert cli.main(["cadastro", "corrigir-medicoes", str(arq), "--usuario", "leo@l.com"]) == 0
    assert "já feito 1" in capsys.readouterr().out


def test_cli_recusa_arquivo_com_erro_e_sem_usuario(cenario, tmp_path, capsys):
    c, cid, uid = cenario
    arq = tmp_path / "correcoes.yaml"
    arq.write_text(yaml.safe_dump([{"operacao": "cancelar", "medicao_id": 999, "fonte": "x"}]), "utf-8")
    assert cli.main(["cadastro", "corrigir-medicoes", str(arq), "--usuario", "leo@l.com"]) == 1
    assert "Recusado, nada foi gravado" in capsys.readouterr().out
    assert cli.main(["cadastro", "corrigir-medicoes", str(arq)]) == 1
    assert "exige --usuario" in capsys.readouterr().out
    arq.write_text("operacao: cancelar\n", "utf-8")
    assert cli.main(["cadastro", "corrigir-medicoes", str(arq), "--usuario", "leo@l.com"]) == 1
    assert "lista de operações" in capsys.readouterr().out
