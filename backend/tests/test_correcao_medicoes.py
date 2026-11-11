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
    # o ensaio e a auditoria dizem qual das duas 1856 entrou (gate Sol da #565)
    assert "NF 1856, série 2, idmov 7002 (R$ 1.000,01) ligada" in rel["itens"][0]["detalhes"][0]
    _, depois = _correcoes(c, mid)[0]
    assert depois["notas"] == [{"nota_id": certa, "numero": "1856", "coligada": 1, "serie": "2", "idmov": 7002}]
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
    assert "idmov ou numero + serie, não os dois" in rel["itens"][0]["erro"]
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [{"nf": 1856}], "fonte": "NF"}])
    assert "os campos são idmov, numero e serie" in rel["itens"][0]["erro"]
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [{"numero": 1856, "serie": "1"}],
                           "fonte": "NF série 1"}])
    assert rel["feitos"] == 1 and _ativas(c, mid) == [certa]


def test_ligar_nf_serie_com_zero_a_esquerda_e_referencia_unica_sem_lista(cenario):
    c, cid, uid = cenario
    m1, m2 = _medicao(c, cid, 1, valor=100_001), _medicao(c, cid, 2, valor=100_001)
    serie01 = _nota_serie(c, 1857, 7101, "01")
    outra = _nota_serie(c, 1857, 7102, "02")
    # `serie: 1` sem aspas chega como numero; o RM grava '01'
    arq = yaml.safe_load("[{operacao: ligar_nf, medicao_id: %d, nfs: [{numero: 1857, serie: 1}], fonte: NF}]" % m1)
    rel = _rodar(c, uid, arq)
    assert rel["feitos"] == 1 and _ativas(c, m1) == [serie01]
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": m2, "nfs": {"idmov": 7102}, "fonte": "NF"}])
    assert rel["feitos"] == 1 and _ativas(c, m2) == [outra]


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
    assert any("NF 511, idmov 1411 (R$ 2.330,15) desligada" in d for d in item["detalhes"])
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
    assert not any(d.startswith("AVISO") for d in rel["itens"][0]["detalhes"])


def test_cancelar_recebida_duplicata_de_verdadeira_nao_recebida_ou_de_outro_tipo_avisa(cenario):
    c, cid, uid = cenario
    verdadeira = _medicao(c, cid, 15, tipo="reajuste")
    dup = _medicao(c, cid, 11, estado="recebida")
    rel = _rodar(c, uid, [{"operacao": "cancelar", "medicao_id": dup, "duplicata_de": verdadeira,
                           "motivo": "lançada duas vezes", "fonte": "planilha"}], ensaio=True)
    detalhes = rel["itens"][0]["detalhes"]
    assert any("AVISO: a verdadeira está protocolada" in d and "ligar_nf" in d for d in detalhes)
    assert any("AVISO: a verdadeira é de reajuste e esta de execução" in d for d in detalhes)


def test_cancelar_duplicata_avisa_quando_a_verdadeira_fica_sem_a_nota(cenario):
    # O caso da issue: a verdadeira foi dada como recebida pela data da baixa, sem NF; a duplicata tem a NF paga.
    # Desligada a' mao, o casador do RM nao a religa: o ensaio tem de mandar liga-la a' verdadeira.
    c, cid, uid = cenario
    verdadeira = _medicao(c, cid, 49, estado="recebida", valor=233_015)
    dup = _medicao(c, cid, 45, estado="recebida", valor=233_015)
    nid = _nota(c, 512, valor=233_015, paga=True)
    _ligar(c, dup, nid, valor=233_015)
    op = {"operacao": "cancelar", "medicao_id": dup, "duplicata_de": verdadeira, "motivo": "lançada duas vezes",
          "fonte": "planilha"}
    detalhes = _rodar(c, uid, [op], ensaio=True)["itens"][0]["detalhes"]
    assert any("AVISO: a verdadeira não tem NF ligada" in d and "ligue NF 512, idmov 1412 (R$ 2.330,15)" in d
               and "ligar_nf" in d for d in detalhes)
    # verdadeira com NF que nao cobre o valor dela: avisa tambem
    _ligar(c, verdadeira, _nota(c, 513, valor=100_001), valor=100_001)
    detalhes = _rodar(c, uid, [op], ensaio=True)["itens"][0]["detalhes"]
    assert any("AVISO: a verdadeira tem NF da coligada 1 que não cobre o valor dela" in d for d in detalhes)
    # cancelar e ligar a nota na verdadeira no mesmo arquivo: a nota paga nao fica sem medicao
    rel = _rodar(c, uid, [op, {"operacao": "ligar_nf", "medicao_id": verdadeira, "nfs": [512], "fonte": "NF paga"}])
    assert rel["feitos"] == 2 and nid in _ativas(c, verdadeira)


def _nota_col(c, numero, coligada, valor):
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, emissao, valor_centavos, situacao)"
                    " VALUES (?,?,?,?,'2025-07-01',?,'ativa')", (coligada, 900 + numero, str(numero), numero,
                                                                 valor)).lastrowid
    c.commit()
    return nid


def test_cancelar_duplicata_em_consorcio_confere_a_cobertura_por_coligada(cenario):
    # Consorcio: a fatura do consorcio (coligada 90) vale o cheio; a NF da Lotufo (coligada 1) vale a cota.
    c, _, uid = cenario
    cons, pct = c.execute("SELECT id, percentual_direito_bp FROM contratos WHERE nome_curto='Obra Consórcio'").fetchone()
    from app import contratos
    cheio = 1_000_001   # centavo impar: a cota arredonda uma vez so'
    cota = contratos.cota(cheio, pct)
    assert cota < cheio
    op = {"operacao": "cancelar", "duplicata_de": None, "motivo": "lançada duas vezes", "fonte": "planilha"}
    # (a) a verdadeira tem so' a fatura do consorcio (cheio); a NF da Lotufo paga esta' na duplicata: avisa
    v1, d1 = _medicao(c, cons, 49, estado="recebida", valor=cheio), _medicao(c, cons, 45, estado="recebida", valor=cheio)
    _ligar(c, v1, _nota_col(c, 601, 90, cheio), valor=cheio)
    _ligar(c, d1, _nota_col(c, 602, 1, cota), valor=cota)
    detalhes = _rodar(c, uid, [{**op, "medicao_id": d1, "duplicata_de": v1}], ensaio=True)["itens"][0]["detalhes"]
    assert any("AVISO: a verdadeira não tem NF ligada da coligada 1" in d and "NF 602" in d for d in detalhes)
    # (b) a verdadeira tem a NF da Lotufo pela cota; a duplicata tem outra NF da Lotufo: a cota esta' coberta, sem aviso
    v2, d2 = _medicao(c, cons, 50, estado="recebida", valor=cheio), _medicao(c, cons, 46, estado="recebida", valor=cheio)
    _ligar(c, v2, _nota_col(c, 603, 1, cota), valor=cota)
    _ligar(c, d2, _nota_col(c, 604, 1, cota), valor=cota)
    detalhes = _rodar(c, uid, [{**op, "medicao_id": d2, "duplicata_de": v2}], ensaio=True)["itens"][0]["detalhes"]
    assert not any(d.startswith("AVISO") for d in detalhes)
    # a duplicata tambem tinha a fatura do consorcio, que a verdadeira nao tem: avisa so' dessa coligada
    _ligar(c, d2, _nota_col(c, 605, 90, cheio), valor=cheio)
    detalhes = _rodar(c, uid, [{**op, "medicao_id": d2, "duplicata_de": v2}], ensaio=True)["itens"][0]["detalhes"]
    avisos = [d for d in detalhes if d.startswith("AVISO")]
    assert len(avisos) == 1 and "coligada 90" in avisos[0] and "NF 605" in avisos[0] and "NF 604" not in avisos[0]
    # (c) limite de baixo da cota: 1.000.001 a 50% e' 500.001 (meio para cima, valor escrito aqui e nao tirado de
    # contratos.cota); a NF da Lotufo da verdadeira com 500.000 nao a cobre: avisa que nao cobre o valor dela
    assert cota == 500_001
    v3, d3 = _medicao(c, cons, 51, estado="recebida", valor=cheio), _medicao(c, cons, 47, estado="recebida", valor=cheio)
    _ligar(c, v3, _nota_col(c, 606, 1, 500_000), valor=500_000)
    _ligar(c, d3, _nota_col(c, 607, 1, 500_001), valor=500_001)
    detalhes = _rodar(c, uid, [{**op, "medicao_id": d3, "duplicata_de": v3}], ensaio=True)["itens"][0]["detalhes"]
    avisos = [d for d in detalhes if d.startswith("AVISO")]
    assert len(avisos) == 1 and "tem NF da coligada 1 que não cobre o valor dela" in avisos[0] and "NF 607" in avisos[0]


def test_cancelar_duplicata_sem_aviso_quando_a_verdadeira_ja_tem_a_nota(cenario):
    c, cid, uid = cenario
    verdadeira = _medicao(c, cid, 49, estado="recebida", valor=100_001)
    _ligar(c, verdadeira, _nota(c, 514, valor=100_001, paga=True))
    dup = _medicao(c, cid, 45, estado="recebida", valor=100_001)
    _ligar(c, dup, _nota(c, 515, valor=100_001, paga=True))
    detalhes = _rodar(c, uid, [{"operacao": "cancelar", "medicao_id": dup, "duplicata_de": verdadeira,
                                "motivo": "lançada duas vezes", "fonte": "planilha"}], ensaio=True)["itens"][0]["detalhes"]
    assert not any(d.startswith("AVISO") for d in detalhes)


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
    assert any("NF 509, idmov 1409 (R$ 1.000,01) desligada" in d for d in rel["itens"][0]["detalhes"])
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


# ------------------------------------------------------------------ nota desconsiderada (issue #638)

def _titulo_aberto(c, nid, valor):
    c.execute("INSERT INTO baixas (coligada, idlan, nota_id, valor_original_centavos, valor_baixado_centavos, status_lan) "
              "VALUES (1,?,?,?,0,0)", (5000 + nid, nid, valor))
    c.commit()


def _nota_db(c, nid):
    return c.execute("SELECT situacao, desconsiderada_em, status_rm, valor_centavos FROM notas_fiscais WHERE id=?",
                     (nid,)).fetchone()


def _eventos_da_nota(c, nid):
    return [(r[0], r[1], json.loads(r[2]), json.loads(r[3])) for r in c.execute(
        "SELECT acao, usuario_id, antes, depois FROM audit_log WHERE entidade='nota_fiscal' AND entidade_id=? "
        "ORDER BY id", (str(nid),))]


DESCONSIDERAR = {"operacao": "desconsiderar_nf", "nf": 601, "motivo": "cancelada na prefeitura e substituída",
                 "substituida_por": "NF 615", "fonte": "comprovante de cancelamento da prefeitura"}


def test_desconsiderar_nf_marca_a_nota_e_audita_motivo_e_fonte(cenario):
    c, cid, uid = cenario
    nid = _nota(c, 601, valor=100_001)
    _titulo_aberto(c, nid, 93_001)
    rel = _rodar(c, uid, [DESCONSIDERAR])
    assert rel["feitos"] == 1 and rel["erros"] == 0
    item = rel["itens"][0]
    assert item["antes"] == "ativa" and item["depois"] == "desconsiderada"
    assert "NF 601, idmov 1501 (R$ 1.000,01)" in item["alvo"]
    n = _nota_db(c, nid)
    assert n["situacao"] == "cancelada" and n["desconsiderada_em"] is not None and n["valor_centavos"] == 100_001
    assert c.execute("SELECT COUNT(*) FROM baixas WHERE nota_id=?", (nid,)).fetchone()[0] == 1     # nada se apaga
    (acao, quem, antes, depois), = _eventos_da_nota(c, nid)
    assert acao == "nota.desconsiderar" and quem == uid and antes == {"situacao": "ativa"}
    assert depois["motivo"] == "cancelada na prefeitura e substituída"
    assert depois["fonte"] == "comprovante de cancelamento da prefeitura" and depois["substituida_por"] == "NF 615"
    assert depois["numero"] == "601" and depois["idmov"] == 1501 and depois["valor_centavos"] == 100_001
    assert depois["origem"] == "correção de cadastro"


def test_desconsiderar_nf_ja_feito_na_segunda_vez_e_ensaio_nao_grava(cenario):
    c, cid, uid = cenario
    nid = _nota(c, 601)
    rel = _rodar(c, uid, [DESCONSIDERAR], ensaio=True)
    assert rel["ensaio"] and rel["feitos"] == 1 and rel["itens"][0]["depois"] == "desconsiderada"
    assert _nota_db(c, nid)["situacao"] == "ativa" and _nota_db(c, nid)["desconsiderada_em"] is None
    assert _eventos_da_nota(c, nid) == []
    assert _rodar(c, uid, [DESCONSIDERAR])["feitos"] == 1
    rel = _rodar(c, uid, [DESCONSIDERAR])
    assert rel["feitos"] == 0 and rel["ja_feitos"] == 1 and rel["erros"] == 0
    assert len(_eventos_da_nota(c, nid)) == 1


def test_desconsiderar_nf_recusa_o_arquivo_inteiro(cenario):
    """Ligada a medicao, com baixa, inexistente e ambigua: nada gravado, nem a operacao valida do mesmo arquivo."""
    c, cid, uid = cenario
    boa = _nota(c, 601)
    ligada = _nota(c, 602)
    mid = _medicao(c, cid, 1)
    _ligar(c, mid, ligada)
    paga = _nota(c, 603, paga=True)
    _nota_serie(c, 1856, 7001, "1")
    _nota_serie(c, 1856, 7002, "2")
    c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, emissao, valor_centavos, situacao, status_rm) "
              "VALUES (1, 1604, '604', 604, '2025-07-01', 5000, 'cancelada', 'C')")
    c.commit()
    base = {"operacao": "desconsiderar_nf", "motivo": "cancelada na prefeitura", "fonte": "comprovante"}
    ops = [{**base, "nf": 601}, {**base, "nf": 602}, {**base, "nf": 603}, {**base, "nf": 999}, {**base, "nf": 1856},
           {**base, "nf": 604}, {"operacao": "desconsiderar_nf", "nf": 601, "fonte": "comprovante"},
           {**base, "nf": 601, "medicao_id": mid}]
    with pytest.raises(correcao_medicoes.CorrecaoRecusada) as e:
        correcao_medicoes.executar(c, uid, ops, ensaio=False)
    erros = [i.get("erro") for i in e.value.relatorio["itens"]]
    assert erros[0] is None
    assert "ligada" in erros[1] and "desligar_nf" in erros[1]
    assert "tem baixa no RM" in erros[2]
    assert "NF 999 não encontrada" in erros[3]
    assert "NF 1856 é ambígua" in erros[4] and "idmov 7001" in erros[4] and "idmov 7002" in erros[4]
    assert "já está cancelada no RM" in erros[5]
    assert "diga o motivo" in erros[6]
    assert "campo que desconsiderar_nf não usa: medicao_id" in erros[7]
    for nid in (boa, ligada, paga):
        assert _nota_db(c, nid)["situacao"] == "ativa" and _nota_db(c, nid)["desconsiderada_em"] is None
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE acao='nota.desconsiderar'").fetchone()[0] == 0
    assert _ativas(c, mid) == [ligada]


def test_desconsiderar_nf_por_idmov_e_coligada_desempatam(cenario):
    c, cid, uid = cenario
    a = _nota_serie(c, 1856, 7001, "1")
    b = _nota_serie(c, 1856, 7002, "2")
    outra = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, serie, emissao, valor_centavos, "
                      "situacao) VALUES (12, 7003, '1856', 1856, '2', '2025-07-01', 50000, 'ativa')").lastrowid
    c.commit()                                    # mesmo numero e serie em outra coligada
    base = {"operacao": "desconsiderar_nf", "motivo": "substituída", "fonte": "comprovante"}
    rel = _rodar(c, uid, [{**base, "nf": {"numero": 1856, "serie": 2}}])
    assert "ambígua" in rel["itens"][0]["erro"] and "coligada 12" in rel["itens"][0]["erro"]
    rel = _rodar(c, uid, [{**base, "nf": {"numero": 1856, "serie": 2}, "coligada": 1}, {**base, "nf": {"idmov": 7001}}])
    assert rel["feitos"] == 2
    assert [_nota_db(c, n)["situacao"] for n in (a, b, outra)] == ["cancelada", "cancelada", "ativa"]


def test_reconsiderar_nf_desfaz_com_evento_novo(cenario):
    c, cid, uid = cenario
    nid = _nota(c, 601)
    _rodar(c, uid, [DESCONSIDERAR])
    volta = {"operacao": "reconsiderar_nf", "nf": 601, "fonte": "a prefeitura reativou a nota"}
    rel = _rodar(c, uid, [volta])
    assert rel["feitos"] == 1 and rel["itens"][0]["antes"] == "desconsiderada" and rel["itens"][0]["depois"] == "ativa"
    n = _nota_db(c, nid)
    assert n["situacao"] == "ativa" and n["desconsiderada_em"] is None
    ev = _eventos_da_nota(c, nid)
    assert [e[0] for e in ev] == ["nota.desconsiderar", "nota.reconsiderar"]
    assert ev[1][3]["fonte"] == "a prefeitura reativou a nota" and ev[1][2]["situacao"] == "desconsiderada"
    rel = _rodar(c, uid, [volta])
    assert rel["ja_feitos"] == 1 and len(_eventos_da_nota(c, nid)) == 2
    assert "falta a fonte" in _rodar(c, uid, [{"operacao": "reconsiderar_nf", "nf": 601}])["itens"][0]["erro"]


def test_reconsiderar_nf_que_o_rm_cancelou_continua_cancelada(cenario):
    c, cid, uid = cenario
    nid = _nota(c, 601)
    _rodar(c, uid, [DESCONSIDERAR])
    c.execute("UPDATE notas_fiscais SET status_rm='C' WHERE id=?", (nid,)); c.commit()
    rel = _rodar(c, uid, [{"operacao": "reconsiderar_nf", "nf": 601, "fonte": "conferência"}])
    assert rel["itens"][0]["depois"] == "cancelada" and any("AVISO" in d for d in rel["itens"][0]["detalhes"])
    assert _nota_db(c, nid)["situacao"] == "cancelada" and _nota_db(c, nid)["desconsiderada_em"] is None


def test_ligar_nf_em_nota_desconsiderada_e_recusado(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1)
    nid = _nota(c, 601)
    _rodar(c, uid, [DESCONSIDERAR])
    for ref in (601, {"idmov": 1501}):
        rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": mid, "nfs": [ref], "fonte": "NF no RM"}])
        assert "foi desconsiderada" in rel["itens"][0]["erro"] and "reconsiderar_nf" in rel["itens"][0]["erro"]
    assert _ativas(c, mid) == []
    # a tela de vincular nota (e qualquer outro caminho) cai em `alocar`, que recusa em portugues e sem citar o RM
    from app import sincronizacao_rm
    with pytest.raises(ValueError, match="Nota fiscal 601 está cancelada$"):
        sincronizacao_rm.alocar(c, uid, nid, mid, "manual", None, "manual")


def test_cli_desconsiderar_nf_ensaio_e_gravacao(cenario, tmp_path, capsys):
    c, cid, uid = cenario
    nid = _nota(c, 601)
    arq = tmp_path / "correcoes.yaml"
    arq.write_text(yaml.safe_dump([DESCONSIDERAR], allow_unicode=True), "utf-8")
    assert cli.main(["cadastro", "corrigir-medicoes", str(arq), "--ensaio", "--usuario", "leo@l.com"]) == 0
    saida = capsys.readouterr().out
    assert "ENSAIO (nada foi gravado)" in saida and "ativa → desconsiderada" in saida and "NF 601" in saida
    assert _nota_db(c, nid)["situacao"] == "ativa"
    assert cli.main(["cadastro", "corrigir-medicoes", str(arq), "--usuario", "leo@l.com"]) == 0
    assert "GRAVADO" in capsys.readouterr().out and _nota_db(c, nid)["situacao"] == "cancelada"
    assert cli.main(["cadastro", "corrigir-medicoes", str(arq), "--usuario", "leo@l.com"]) == 0
    assert "já feito 1" in capsys.readouterr().out
