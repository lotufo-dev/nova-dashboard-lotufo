"""Garantia (com validade) como documento do contrato: issue #65, decisao de 15/10/2026 (a ART saiu na #239)."""
import datetime
import json

import pytest

from app import auth, avisos, db, documentos, garantias, tempo

D = datetime.date
HOJE = D(2026, 10, 15)


@pytest.fixture
def cenario(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(tempo, "hoje_local", lambda: HOJE)
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "admin")
    c.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('sinfra-x', 'SINFRA X', 'sinfra', ?)",
              (json.dumps({"vigencia_automatica": True, "documentos_medicao": [], "documentos_reajuste": []}),))
    c.execute("INSERT INTO contratos (orgao, numero_instrumento, nome_curto, objeto, valor_original_centavos, "
              "orgao_id, execucao_fim, vigencia_fim) VALUES ('SINFRA', 'IC 1/2026', 'Obra A', 'obra', 100, "
              "(SELECT id FROM orgaos WHERE chave='sinfra-x'), '2027-12-20', '2028-01-30')")
    cid = c.execute("SELECT MAX(id) FROM contratos").fetchone()[0]
    c.commit()

    def garantia(fim, apolice="AP-1"):
        c.execute("UPDATE contratos SET garantia_apolice=?, garantia_vigencia_fim=? WHERE id=?", (apolice, fim, cid))
        c.commit()

    def instrumento(tipo, data, dados, chave):
        c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) VALUES (?, ?, ?, ?, ?)",
                  (cid, chave, tipo, data, json.dumps(dados)))
        c.commit()

    yield c, {"contrato": cid, "garantia": garantia, "instrumento": instrumento}
    c.close()


def _g(c, hoje=HOJE):
    return [a for a in avisos.listar(c, hoje, publico="todos") if a["tipo"] == "garantia_vencendo"]


def test_garantia_30_15_e_vencida_como_as_certidoes(cenario):
    c, ids = cenario
    ids["garantia"]("2026-12-31")
    assert _g(c) == []                                                # 77 dias: nada
    ids["garantia"]("2026-11-14")                                     # 30 dias
    assert [(a["nivel"], a["dias"]) for a in _g(c)] == [("atencao", 30)]
    ids["garantia"]("2026-10-30")                                     # 15 dias
    assert [(a["nivel"], a["dias"]) for a in _g(c)] == [("acao", 15)]
    ids["garantia"]("2026-10-14")                                     # vencida ontem
    a = _g(c)[0]
    assert (a["nivel"], a["dias"], a["sentido"], a["data"]) == ("critico", -1, "prazo", "2026-10-14")
    assert "vencida" in a["mensagem"] and "14/10/2026" in a["mensagem"]
    assert a["publico"] == ["operacao", "diretoria"] and a["destino"] == {"tela": "documentos"}
    assert a["obra"] == "Obra A"


def test_endosso_com_vigencia_maior_substitui_e_o_aviso_some(cenario):
    c, ids = cenario
    ids["garantia"]("2026-10-30")
    assert len(_g(c)) == 1
    ids["instrumento"]("endosso_garantia", "2026-10-10", {"apolice": "AP-1", "vigencia_fim": "2027-04-30"}, "end-1")
    assert _g(c) == []
    g = garantias.garantia(c, ids["contrato"], HOJE)
    assert (g["vigencia_fim"], g["origem"], g["endosso"], g["apolice"]) == ("2027-04-30", "endosso", "end-1", "AP-1")
    # o historico fica: o endosso anterior continua gravado e o contrato mantem a vigencia original
    assert c.execute("SELECT garantia_vigencia_fim FROM contratos").fetchone()[0] == "2026-10-30"


def test_vale_o_endosso_mais_recente_por_data(cenario):
    c, ids = cenario
    ids["garantia"]("2026-10-01")
    ids["instrumento"]("endosso_garantia", "2026-03-01", {"apolice": "AP-1", "vigencia_fim": "2026-11-01"}, "end-1")
    ids["instrumento"]("endosso_garantia", "2026-09-01", {"apolice": "AP-1", "vigencia_fim": "2026-10-20"}, "end-2")
    assert garantias.garantia(c, ids["contrato"], HOJE)["endosso"] == "end-2"
    assert [a["dias"] for a in _g(c)] == [5]
    # endosso sem vigencia (o de prazo antigo, so' com `referente`) nao mexe na garantia
    ids["instrumento"]("endosso_garantia", "2026-10-01", {"referente": "ta-1"}, "end-3")
    assert garantias.garantia(c, ids["contrato"], HOJE)["endosso"] == "end-2"


def test_encerramento_avisa_ate_a_baixa_da_garantia_e_encerrado_nao_avisa(cenario):
    c, ids = cenario
    ids["garantia"]("2026-10-20")
    c.execute("UPDATE contratos SET encerramento_iniciado_em='2026-09-01'"); c.commit()
    assert len(_g(c)) == 1
    ids["instrumento"]("marco_encerramento", "2026-10-01", {"marco": "baixa_garantia"}, "baixa")
    assert _g(c) == []
    c.execute("DELETE FROM instrumentos"); c.execute("UPDATE contratos SET estado='encerrado'"); c.commit()
    assert _g(c) == []


def test_sem_data_de_garantia_no_cadastro_nao_avisa(cenario):
    c, ids = cenario
    assert garantias.garantia(c, ids["contrato"], HOJE) is None and _g(c) == []


def test_art_nao_gera_aviso_nem_existe_mais_no_modulo(cenario):
    c, ids = cenario
    assert not hasattr(garantias, "art")
    assert [a for a in avisos.listar(c, HOJE) if a["tipo"] == "art_nao_anexada"] == []
    assert [a for a in garantias.avisos(c, HOJE) if a["tipo"] == "art_nao_anexada"] == []


def test_painel_de_documentos_traz_garantia_por_contrato(cenario):
    c, ids = cenario
    ids["garantia"]("2026-11-01")
    (o,) = documentos.painel(c, HOJE)["contratos"]
    assert o["contrato_id"] == ids["contrato"] and o["obra"] == "Obra A"
    assert (o["garantia"]["situacao"], o["garantia"]["dias"], o["garantia"]["apolice"]) == ("vencendo", 17, "AP-1")
    assert "art" not in o


def test_correcao_de_endosso_vale_mesmo_com_data_anterior(cenario):
    c, ids = cenario
    ids["garantia"]("2026-10-01")
    ids["instrumento"]("endosso_garantia", "2026-09-01", {"apolice": "AP-1", "vigencia_fim": "2027-09-30"}, "end-errado")
    ids["instrumento"]("endosso_garantia", "2026-08-15", {"apolice": "AP-1", "vigencia_fim": "2026-10-25", "corrige": "end-errado"},
                       "end-certo")
    g = garantias.garantia(c, ids["contrato"], HOJE)
    assert (g["endosso"], g["vigencia_fim"]) == ("end-certo", "2026-10-25")


def test_apolice_nova_no_contrato_com_data_maior_que_o_endosso_some_com_o_aviso(cenario):
    c, ids = cenario
    ids["garantia"]("2026-12-01")
    ids["instrumento"]("endosso_garantia", "2026-09-01", {"apolice": "AP-1", "vigencia_fim": "2027-03-01"}, "end-1")
    assert garantias.garantia(c, ids["contrato"], D(2027, 3, 10)) is not None
    ids["garantia"]("2028-03-01", apolice="AP-2")                 # apolice nova entra no cadastro
    g = garantias.garantia(c, ids["contrato"], D(2027, 3, 10))
    assert (g["vigencia_fim"], g["origem"], g["apolice"]) == ("2028-03-01", "contrato", "AP-2")
    assert _g(c, D(2027, 3, 10)) == []


def test_troca_de_apolice_com_data_menor_que_a_do_endosso_antigo_vale_a_nova(cenario):
    c, ids = cenario
    ids["garantia"]("2026-12-01")
    ids["instrumento"]("endosso_garantia", "2026-09-01", {"apolice": "AP-1", "vigencia_fim": "2027-12-01"}, "end-1")
    assert garantias.garantia(c, ids["contrato"], HOJE)["vigencia_fim"] == "2027-12-01"
    ids["garantia"]("2027-06-01", apolice="AP-2")                 # AP-2 vence antes do endosso da AP-1
    g = garantias.garantia(c, ids["contrato"], HOJE)
    assert (g["apolice"], g["vigencia_fim"], g["origem"]) == ("AP-2", "2027-06-01", "contrato")
    ids["instrumento"]("endosso_garantia", "2027-01-10", {"apolice": "AP-2", "vigencia_fim": "2027-09-01"}, "end-2")
    assert garantias.garantia(c, ids["contrato"], HOJE)["vigencia_fim"] == "2027-09-01"


def test_ordem_dos_endossos_nao_muda_o_resultado(cenario):
    c, ids = cenario
    ids["garantia"]("2026-12-01")
    # inseridos fora de ordem (o id do mais novo vem primeiro); vale o de data maior da apolice do contrato
    ids["instrumento"]("endosso_garantia", "2027-01-10", {"apolice": "AP-1", "vigencia_fim": "2026-11-01"}, "end-2")
    ids["instrumento"]("endosso_garantia", "2026-09-01", {"apolice": "AP-1", "vigencia_fim": "2027-06-01"}, "end-1")
    g = garantias.garantia(c, ids["contrato"], HOJE)
    assert (g["endosso"], g["vigencia_fim"]) == ("end-2", "2026-11-01")
    c.execute("DELETE FROM instrumentos"); c.commit()
    ids["instrumento"]("endosso_garantia", "2026-09-01", {"apolice": "AP-1", "vigencia_fim": "2027-06-01"}, "end-1")
    ids["instrumento"]("endosso_garantia", "2027-01-10", {"apolice": "AP-1", "vigencia_fim": "2026-11-01"}, "end-2")
    assert garantias.garantia(c, ids["contrato"], HOJE)["endosso"] == "end-2"
    c.execute("DELETE FROM instrumentos WHERE chave='end-1'"); c.commit()
    assert garantias.garantia(c, ids["contrato"], HOJE)["endosso"] == "end-2"     # sozinho, mesmo resultado


def test_endosso_de_outra_apolice_nao_conta(cenario):
    c, ids = cenario
    ids["garantia"]("2026-12-01")
    ids["instrumento"]("endosso_garantia", "2026-09-01", {"apolice": "AP-0", "vigencia_fim": "2027-06-01"}, "end-x")
    assert garantias.garantia(c, ids["contrato"], HOJE)["origem"] == "contrato"


# --- issue #294: a garantia cobre o fim de execucao vigente + folga do orgao (D10, 20/10/2026) ---

def _aq(c, hoje=HOJE):
    return [a for a in avisos.listar(c, hoje, publico="todos") if a["tipo"] == "garantia_aquem_execucao"]


def _aditivo_prazo(c, cid, nova_exec, assinatura="2026-10-10"):
    c.execute("INSERT INTO aditivos (contrato_id, tipo, status, data_assinatura, nova_execucao_fim) "
              "VALUES (?, 'prazo', 'assinado', ?, ?)", (cid, assinatura, nova_exec))
    c.commit()


def test_prazo_prorrogado_alem_da_garantia_pede_endosso_ate_o_novo_fim_mais_a_folga(cenario):
    c, ids = cenario
    ids["garantia"]("2027-12-20")                                   # cobre a execucao original (2027-12-20)
    assert _aq(c) == []
    _aditivo_prazo(c, ids["contrato"], "2028-06-30")                # prorrogou alem da garantia
    (a,) = _aq(c)
    assert "Endosso necessário até 30/06/2028" in a["mensagem"]
    assert a["obra"] == "Obra A" and a["publico"] == ["operacao", "diretoria"]
    assert a["nivel"] == "acao" and a["data"] == "2028-06-30"


def test_folga_do_orgao_entra_na_conta(cenario):
    c, ids = cenario
    c.execute("UPDATE orgaos SET regras=?", (json.dumps({"folga_vigencia_dias": 90}),)); c.commit()
    ids["garantia"]("2028-02-01")                                   # cobre 20/12/2027 mas nao +90 (19/03/2028)
    (a,) = _aq(c)
    assert "19/03/2028" in a["mensagem"]
    ids["garantia"]("2028-03-19")                                   # cobre exatamente o fim + folga
    assert _aq(c) == []


def test_folga_propria_do_contrato_vale_mais_que_a_do_orgao(cenario):
    c, ids = cenario
    c.execute("UPDATE orgaos SET regras=?", (json.dumps({"folga_vigencia_dias": 90}),))
    c.execute("UPDATE contratos SET folga_vigencia_dias=10"); c.commit()
    ids["garantia"]("2027-12-30")                                   # 20/12/2027 + 10
    assert _aq(c) == []
    ids["garantia"]("2027-12-29")
    assert "30/12/2027" in _aq(c)[0]["mensagem"]


def test_endosso_com_vigencia_suficiente_faz_o_aviso_sumir(cenario):
    c, ids = cenario
    ids["garantia"]("2027-12-20")
    _aditivo_prazo(c, ids["contrato"], "2028-06-30")
    assert len(_aq(c)) == 1
    ids["instrumento"]("endosso_garantia", "2026-10-12", {"apolice": "AP-1", "vigencia_fim": "2028-06-29"}, "end-1")
    assert len(_aq(c)) == 1                                         # ainda um dia aquem
    ids["instrumento"]("endosso_garantia", "2026-10-13", {"apolice": "AP-1", "vigencia_fim": "2028-06-30"}, "end-2")
    assert _aq(c) == []


def test_garantia_que_cobre_fim_mais_folga_nao_avisa_e_sem_garantia_ou_baixada_tambem_nao(cenario):
    c, ids = cenario
    assert _aq(c) == []                                             # sem data de garantia no cadastro
    ids["garantia"]("2028-12-31")
    assert _aq(c) == []
    ids["garantia"]("2027-01-01")
    assert len(_aq(c)) == 1
    ids["instrumento"]("marco_encerramento", "2026-10-01", {"marco": "baixa_garantia"}, "baixa")
    assert _aq(c) == []


def test_aviso_de_cobertura_vira_critico_depois_da_data_e_nao_vale_em_encerramento(cenario):
    c, ids = cenario
    ids["garantia"]("2027-06-01")
    assert [a["nivel"] for a in _aq(c, D(2027, 12, 21))] == ["critico"]
    assert [a["nivel"] for a in _aq(c)] == ["acao"]
    c.execute("UPDATE contratos SET encerramento_iniciado_em='2026-09-01'"); c.commit()
    assert _aq(c) == []
