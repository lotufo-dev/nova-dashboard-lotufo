"""Checklist "pronto para protocolar" (fase 3, T7).

A pergunta que este modulo responde e' a da mesa de protocolo: "posso levar ESTE
contrato ao orgao hoje?". A resposta depende da ENTIDADE do contrato -- obra de
consorcio se habilita com as certidoes do consorcio, nao com as da Lotufo.
"""
import datetime

import pytest
from app import auth, certidoes, checklist, contratos, db, entidades, tempo
from tests.conftest import novo_contrato

HOJE = datetime.date(2026, 9, 1)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "admin")
    # Os testes deste modulo sao sobre as tres federais semeadas na 006; a 031 cobra tambem estadual e
    # municipal por padrao -- aqui elas ficam de fora para o cenario continuar o mesmo.
    c.execute("UPDATE certidao_tipos SET aplicavel_por_padrao=0 WHERE chave IN ('estadual','municipal')")
    c.commit()
    monkeypatch.setattr(tempo, "hoje_local", lambda: HOJE)
    yield c
    c.close()


def _reg(conn, ent=1, tipo=1, emissao="2026-08-01", validade="2026-12-01"):
    return certidoes.registrar(conn, 1, ent, tipo, emissao, validade,
                               f"certidoes/{ent}-{tipo}-{validade}.pdf", "a" * 64, "upload")


def _contrato(conn, entidade_id=None, numero="IC 1/2026"):
    dados = {"orgao": "SINFRA", "numero_instrumento": numero, "objeto": "Obra X",
             "valor_original_centavos": 1_000_00}
    if entidade_id is not None:
        dados["entidade_id"] = entidade_id
    return contratos.criar(conn, 1, dados)


def _consorcio(conn):
    return entidades.criar(conn, 1, {"nome": "Consórcio Y", "cnpj": "11444777000161",
                                     "papel": "consorcio"})


def _por_tipo(resultado):
    return {i["tipo_id"]: i for i in resultado["itens"]}


def test_tres_federais_vigentes_deixam_pronto(conn):
    cid = _contrato(conn)
    for tipo in (1, 2, 3):
        _reg(conn, tipo=tipo)
    r = checklist.pronto_para_protocolar(conn, cid)
    assert r["pronto"] is True
    assert r["entidade_id"] == 1
    assert {i["situacao"] for i in r["itens"]} == {"ok"}
    assert len(r["itens"]) == 3
    assert _por_tipo(r)[1]["validade"] == "2026-12-01"


def test_uma_vencida_derruba_o_pronto_e_aponta_o_tipo(conn):
    cid = _contrato(conn)
    _reg(conn, tipo=1)
    _reg(conn, tipo=2, emissao="2026-01-01", validade="2026-02-01")   # vencida
    _reg(conn, tipo=3)
    r = checklist.pronto_para_protocolar(conn, cid)
    assert r["pronto"] is False
    itens = _por_tipo(r)
    assert itens[2]["situacao"] == "pendente" and itens[2]["validade"] is None
    assert itens[1]["situacao"] == "ok" and itens[3]["situacao"] == "ok"


def test_pendente_separa_a_vencida_da_nunca_cadastrada(conn):
    """As duas saem `pendente` (nenhuma vale hoje), mas so' a vencida trava o envio: `nunca_cadastrada` diz qual e'."""
    cid = _contrato(conn)
    _reg(conn, tipo=1)
    _reg(conn, tipo=2, emissao="2026-01-01", validade="2026-02-01")   # vencida; o tipo 3 nunca foi cadastrado
    itens = _por_tipo(checklist.pronto_para_protocolar(conn, cid))
    assert (itens[2]["situacao"], itens[2]["nunca_cadastrada"]) == ("pendente", False)
    assert (itens[3]["situacao"], itens[3]["nunca_cadastrada"]) == ("pendente", True)
    assert (itens[1]["situacao"], itens[1]["nunca_cadastrada"]) == ("ok", False)


def test_vencendo_conta_como_pronto_mas_aparece_com_aviso(conn):
    # 10 dias para vencer: da' para protocolar hoje, mas quem le precisa VER
    cid = _contrato(conn)
    _reg(conn, tipo=1, validade="2026-09-11")
    _reg(conn, tipo=2)
    _reg(conn, tipo=3)
    r = checklist.pronto_para_protocolar(conn, cid)
    assert r["pronto"] is True
    assert _por_tipo(r)[1]["situacao"] == "vencendo"
    assert _por_tipo(r)[1]["dias"] == 10


def test_contrato_de_consorcio_usa_as_certidoes_do_consorcio(conn):
    """O ponto da fase: habilitacao e' por CNPJ. A Lotufo em dia nao habilita o
    consorcio, e o consorcio em dia nao depende da Lotufo."""
    eid = _consorcio(conn)
    do_consorcio = _contrato(conn, entidade_id=eid, numero="IC 2/2026")
    da_lotufo = _contrato(conn, numero="IC 3/2026")
    for tipo in (1, 2, 3):
        _reg(conn, ent=1, tipo=tipo)          # so' a Lotufo tem certidao

    r = checklist.pronto_para_protocolar(conn, do_consorcio)
    assert r["entidade_id"] == eid and r["entidade"] == "Consórcio Y"
    assert r["pronto"] is False
    assert {i["situacao"] for i in r["itens"]} == {"pendente"}
    assert checklist.pronto_para_protocolar(conn, da_lotufo)["pronto"] is True

    for tipo in (1, 2, 3):
        _reg(conn, ent=eid, tipo=tipo)
    assert checklist.pronto_para_protocolar(conn, do_consorcio)["pronto"] is True


def test_nao_se_aplica_aparece_sem_pesar_no_veredito(conn):
    cid = _contrato(conn)
    _reg(conn, tipo=1)
    _reg(conn, tipo=2)
    certidoes.marcar_nao_se_aplica(conn, 1, 1, 3, "entidade não sujeita")
    r = checklist.pronto_para_protocolar(conn, cid)
    assert r["pronto"] is True
    assert _por_tipo(r)[3]["situacao"] == "nao_se_aplica"


def test_nao_se_aplica_antigo_nao_esconde_pendencia_nova(conn, monkeypatch):
    """So' a decisao MAIS RECENTE do par manda (gate 2): NSA em janeiro, certidao em
    marco, vencida em agosto -> pendente, nao 'nao_se_aplica'."""
    cid = _contrato(conn)
    _reg(conn, tipo=1)
    _reg(conn, tipo=2)
    # a linha de NSA nasce datada de HOJE: para ela ser a decisao ANTIGA, a decisao
    # precisa mesmo ter sido tomada em janeiro
    monkeypatch.setattr(tempo, "hoje_local", lambda: datetime.date(2026, 1, 10))
    certidoes.marcar_nao_se_aplica(conn, 1, 1, 3, None)
    monkeypatch.setattr(tempo, "hoje_local", lambda: HOJE)
    _reg(conn, tipo=3, emissao="2026-03-01", validade="2026-08-01")   # voltou e venceu
    r = checklist.pronto_para_protocolar(conn, cid)
    assert _por_tipo(r)[3]["situacao"] == "pendente"
    assert r["pronto"] is False


def test_tipo_nao_aplicavel_por_padrao_fica_de_fora(conn):
    certidoes.criar_tipo(conn, 1, "CND Estadual MT", "estadual", "SEFAZ-MT", False)
    cid = _contrato(conn)
    for tipo in (1, 2, 3):
        _reg(conn, tipo=tipo)
    r = checklist.pronto_para_protocolar(conn, cid)
    assert [i["tipo_id"] for i in r["itens"]] == [1, 2, 3]
    assert r["pronto"] is True


def test_contrato_legado_sem_entidade_e_lido_como_lotufo(conn):
    """Defesa: contrato gravado antes da 009 (ou por caminho que nao preencheu a
    coluna) tem entidade_id NULL -- a leitura trata como 1, nunca como 'sem entidade'."""
    cid = _contrato(conn)
    conn.execute("UPDATE contratos SET entidade_id=NULL WHERE id=?", (cid,))
    conn.commit()
    for tipo in (1, 2, 3):
        _reg(conn, tipo=tipo)
    r = checklist.pronto_para_protocolar(conn, cid)
    assert r["entidade_id"] == 1 and r["pronto"] is True


def test_contrato_inexistente_levanta(conn):
    with pytest.raises(ValueError, match="não encontrado"):
        checklist.pronto_para_protocolar(conn, 999)


# --- rota -----------------------------------------------------------------------------

def test_rota_checklist_devolve_o_veredito(client_admin):
    cid = novo_contrato({"orgao": "SINFRA", "numero_instrumento": "IC 1/2026", "objeto": "Obra X",
                         "valor_original": "1.000,00"})
    r = client_admin.get(f"/api/contratos/{cid}/checklist-protocolo")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["contrato_id"] == cid and corpo["entidade_id"] == 1
    # sem nenhuma certidao cadastrada, os tres tipos padrao ficam pendentes
    assert corpo["pronto"] is False
    assert {i["situacao"] for i in corpo["itens"]} == {"pendente"}


def test_rota_checklist_404_em_contrato_inexistente(client_admin):
    assert client_admin.get("/api/contratos/999/checklist-protocolo").status_code == 404


def test_rota_checklist_exige_sessao(client):
    assert client.get("/api/contratos/1/checklist-protocolo").status_code == 401


def test_consorcio_cobra_consorciadas_e_regularidade(conn, monkeypatch):
    import json
    monkeypatch.setattr(tempo, "hoje_local", lambda: datetime.date(2026, 9, 23))
    conn.execute("INSERT INTO entidades (id, nome, cnpj, papel, nome_curto) VALUES "
                 "(20, 'Consórcio Complexo Leblon', '31200404000152', 'consorcio', 'Complexo Leblon'), "
                 "(21, 'Rivoli', '31200606000102', 'consorciada', 'Rivoli')")
    conn.execute("INSERT INTO entidade_consorciadas VALUES (20, 1), (20, 21)")
    conn.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('s','S','sinfra',?)",
                 (json.dumps({"documentos_medicao": ["fgts", "regularidade"], "documentos_reajuste": ["estadual"]}),))
    oid = conn.execute("SELECT id FROM orgaos WHERE chave='s'").fetchone()[0]
    conn.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos, orgao_id, entidade_id) "
                 "VALUES ('S', 'L-1', 'o', 100, ?, 20)", (oid,))
    conn.commit()
    cid = conn.execute("SELECT MAX(id) FROM contratos").fetchone()[0]
    ck = checklist.pronto_para_protocolar(conn, cid, "execucao")
    assert [(i["entidade_id"], i["chave"]) for i in ck["itens"]] == [(20, "fgts"), (1, "fgts"), (21, "fgts"), (1, "regularidade")]
    assert ck["pronto"] is False and all(i["situacao"] == "pendente" for i in ck["itens"])
    reaj = checklist.pronto_para_protocolar(conn, cid, "reajuste")
    assert [(i["entidade_id"], i["chave"]) for i in reaj["itens"]] == [(20, "estadual"), (1, "estadual"), (21, "estadual")]
