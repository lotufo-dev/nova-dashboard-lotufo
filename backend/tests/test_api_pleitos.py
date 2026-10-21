"""Rotas dos pleitos e da medicao final (bloco 7): fluxo pela API com o simulador do Graph."""
import sqlite3
import threading

import pytest

from app import auditoria, cadastro_aplicar, correio, db, envio_reserva, pleitos
from tests.test_envio_reserva import CorreioFalso
from tests.test_protocolo import CARTAS, _assinar, _contrato


@pytest.fixture
def api(client_admin, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    c = db.get_conn()
    obra = {**_contrato("Obra MTPAR", "mtpar", "099/2024/MTPAR"), "datas_base": [{"mes": "2024-06", "indice": "INCC-DI"}]}
    cadastro_aplicar.aplicar(c, 1, {
        "orgaos": [{"chave": "mtpar", "nome": "MTPAR", "familia": "mtpar", "cnpj": None,
                    "regras": {"protocolo_para": ["protocolo@orgao-b.exemplo.com.br"], "documentos_medicao": [],
                               "documentos_reajuste": []}}],
        "entidades": [{"chave": "lotufo", "nome": "Lotufo Engenharia e Construções Ltda", "cnpj": "31200101000130",
                       "papel": "lotufo", "coligada_rm": 1, "sigla_oficio": "LT", "nome_curto": "Lotufo"}],
        "contratos": [obra], "avisos": [], "geral": {"cartas": CARTAS}})
    cid = c.execute("SELECT id FROM contratos").fetchone()[0]
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
              "VALUES (?, 30, 'execucao', '2026-08', 'protocolada')", (cid,))
    mid = c.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]
    c.commit(); c.close()
    return client_admin, cid, mid


def _arquivo(nome, dados, tipo):
    return {"arquivo": (nome, dados, tipo)}


def test_pleito_de_reajuste_pela_api(api):
    cl, cid, _ = api
    r = cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "reajuste", "numero_oficio": "122"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["corpo_padrao"] and r.json()["numero_oficio"] == "CT-122-LT-2026"
    cl.post(f"/api/pleitos/{pid}/anexos", data={"tipo": "planilha_calculo"},
            files=_arquivo("memoria.xlsx", b"PK\x03\x04memoria",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
    cl.post(f"/api/pleitos/{pid}/anexos", data={"tipo": "cronograma"},
            files=_arquivo("cronograma.pdf", b"%PDF-1.4 cronograma", "application/pdf"))
    assert cl.post(f"/api/pleitos/{pid}/montar", json={}).status_code == 200
    doc = cl.get(f"/api/pleitos/{pid}/documento")
    assert doc.status_code == 200 and doc.headers["content-type"] == "application/pdf"
    assert cl.post(f"/api/pleitos/{pid}/assinado", files=_arquivo("a.pdf", _assinar(doc.content),
                                                                  "application/pdf")).json()["conferencia"]["ok"]
    pv = cl.post(f"/api/pleitos/{pid}/previa").json()
    r = cl.post(f"/api/pleitos/{pid}/enviar", json={k: pv[k] for k in ("para", "copia", "assunto", "corpo")})
    assert r.status_code == 200, r.text
    ciclo = cl.get(f"/api/contratos/{cid}/reajuste").json()["ciclos"][0]
    assert ciclo["situacao"] == "apostilamento_pendente"


def test_pecas_do_orgao_entram_como_anexo_pela_api(api):
    """Issue #50: a API aceita as pecas que o orgao pede no pleito de reajuste (falencia, contrato social, ...)."""
    cl, cid, _ = api
    pid = cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "reajuste", "numero_oficio": "122"}).json()["id"]
    for tipo in ("falencia", "contrato_social", "documento_representante", "balanco"):
        r = cl.post(f"/api/pleitos/{pid}/anexos", data={"tipo": tipo},
                    files=_arquivo(f"{tipo}.pdf", b"%PDF-1.4 " + tipo.encode(), "application/pdf"))
        assert r.status_code < 300, r.text
    assert cl.post(f"/api/pleitos/{pid}/anexos", data={"tipo": "inventado"},
                   files=_arquivo("x.pdf", b"%PDF-1.4 x", "application/pdf")).status_code == 422


def test_medicao_final_pela_api_poe_o_contrato_em_encerramento(api):
    cl, cid, mid = api
    assert cl.post(f"/api/medicoes/{mid}/final", json={"data": "2026-09-10"}).json()["final"] == 1
    assert cl.get(f"/api/contratos/{cid}/prazos").json()["situacao"]["encerramento"]["desde"] == "2026-09-10"
    assert cl.post(f"/api/medicoes/{mid}/final/desmarcar", json={"motivo": ""}).status_code == 422
    assert cl.post(f"/api/medicoes/{mid}/final/desmarcar", json={"motivo": "engano"}).json()["final"] == 0
    assert cl.get("/api/pleitos/999999").status_code == 404


# --- envio unico e registrado (pacote 1 da fase 4, 10/10/2026) ---------------------------------------------

def _pronto(cl, cid):
    pid = cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "reajuste", "numero_oficio": "122"}).json()["id"]
    cl.post(f"/api/pleitos/{pid}/montar", json={})
    doc = cl.get(f"/api/pleitos/{pid}/documento")
    cl.post(f"/api/pleitos/{pid}/assinado", files=_arquivo("a.pdf", _assinar(doc.content), "application/pdf"))
    pv = cl.post(f"/api/pleitos/{pid}/previa").json()
    return pid, {**{k: pv[k] for k in ("para", "copia", "assunto", "corpo")}, "justificativa": "teste do envio concorrente"}


def _estado(pid):
    c = db.get_conn()
    try:
        p = c.execute("SELECT situacao, envio_id, envio_reservado_em FROM pleitos WHERE id=?", (pid,)).fetchone()
        return dict(p), c.execute("SELECT COUNT(*) FROM envios").fetchone()[0]
    finally:
        c.close()


def test_segundo_envio_do_pleito_durante_o_primeiro_e_recusado(api, monkeypatch):
    cl, cid, _ = api
    pid, corpo = _pronto(cl, cid)
    args = [corpo[k] for k in ("para", "copia", "assunto", "corpo", "justificativa")]
    c = db.get_conn()
    u = {"id": c.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0],
         "email": "admin@lotufo.com"}
    erros = []

    def segundo():
        outra = db.get_conn()
        try:
            pleitos.enviar(outra, u, pid, *args)
        except Exception as e:
            erros.append(e)
        finally:
            outra.close()

    falso = CorreioFalso(no_meio=segundo)
    monkeypatch.setattr(correio, "cliente", falso)
    eid = pleitos.enviar(c, u, pid, *args)
    c.close()
    assert [type(e).__name__ for e in erros] == ["EnvioEmAndamento"]
    assert len(falso.enviados) == 1
    assert _estado(pid) == ({"situacao": "enviado", "envio_id": eid, "envio_reservado_em": None}, 1)


def test_pleito_registrado_pela_metade_diz_que_saiu_e_trava_a_repeticao(api, monkeypatch):
    cl, cid, _ = api
    pid, corpo = _pronto(cl, cid)
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    original = auditoria.registrar

    def trava_so_o_pleito(conn, usuario_id, acao, *a, **k):
        if acao == "pleito.enviar":
            raise sqlite3.OperationalError("database is locked")
        return original(conn, usuario_id, acao, *a, **k)

    monkeypatch.setattr(auditoria, "registrar", trava_so_o_pleito)
    r = cl.post(f"/api/pleitos/{pid}/enviar", json=corpo)
    assert r.status_code == 500 and "O e-mail SAIU" in r.json()["detail"], r.text
    p, envios = _estado(pid)
    assert p["situacao"] != "enviado" and p["envio_reservado_em"] is not None and envios == 1
    r = cl.post(f"/api/pleitos/{pid}/enviar", json=corpo)
    assert r.status_code == 409 and len(falso.enviados) == 1


def test_data_base_com_digito_arabe_indico_da_422(api):
    r"""A-14 (testes de quebra 10/10/2026): o padrao de `data_base_mes` usava `\d`."""
    cl, cid, _ = api
    r = cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "reajuste", "numero_oficio": "122",
                                                       "data_base_mes": "٢٠٢٤-06"})
    assert r.status_code == 422
    assert any(e["loc"][-1] == "data_base_mes" for e in r.json()["detail"]), r.text


def test_validacao_do_pleito_em_portugues(api):
    """B-12 (10/10/2026): "Input should be less than or equal to 3650" chegava cru na tela."""
    cl, cid, _ = api
    r = cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "prazo", "numero_oficio": "999", "dias": 99999,
                                                      "justificativa": "teste de quebra"})
    assert r.status_code == 422
    erro = next(e for e in r.json()["detail"] if e["loc"][-1] == "dias")
    assert erro["msg"] == "no máximo 3650"
    r = cl.post(f"/api/contratos/{cid}/pleitos", json={"numero_oficio": "999"})
    assert next(e for e in r.json()["detail"] if e["loc"][-1] == "tipo")["msg"] == "campo obrigatório"
    r = cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "prazo", "numero_oficio": "999", "dias": "muitos"})
    assert next(e for e in r.json()["detail"] if e["loc"][-1] == "dias")["msg"] == "valor inválido"


def test_json_truncado_diz_json_invalido(api):
    """Gate Sol S3 (10/10/2026): corpo JSON torto virava "valor inválido" com loc numerica (posicao do erro)."""
    cl, cid, _ = api
    r = cl.post(f"/api/contratos/{cid}/pleitos", content=b'{"x":', headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert r.json()["detail"] == [{"type": "json_invalid", "loc": ["body"], "msg": "JSON inválido ou incompleto"}]


# --- um rascunho aberto por ciclo (issue #9) --------------------------------------------------------------

def test_segundo_pleito_do_mesmo_ciclo_da_409_ate_descartar_o_primeiro(api):
    cl, cid, _ = api
    primeiro = cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "reajuste", "numero_oficio": "122"})
    assert primeiro.status_code == 201, primeiro.text
    r = cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "reajuste", "numero_oficio": "130"})
    assert r.status_code == 409, r.text
    assert "CT-122-LT-2026" in r.json()["detail"] and "em aberto" in r.json()["detail"]
    assert cl.post(f"/api/pleitos/{primeiro.json()['id']}/descartar", json={"motivo": "ofício errado"}).status_code == 200
    r = cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "reajuste", "numero_oficio": "130"})
    assert r.status_code == 201, r.text


def test_pleito_enviado_libera_criar_outro_no_mesmo_ciclo(api):
    cl, cid, _ = api
    pid, corpo = _pronto(cl, cid)
    assert cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "reajuste", "numero_oficio": "130"}).status_code == 409
    assert cl.post(f"/api/pleitos/{pid}/enviar", json=corpo).status_code == 200
    r = cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "reajuste", "numero_oficio": "130"})
    assert r.status_code == 201, r.text


def test_rascunho_aberto_trava_so_o_mesmo_tipo(api):
    cl, cid, _ = api
    prazo = {"tipo": "prazo", "numero_oficio": "310", "dias": 60, "justificativa": "interferências na via"}
    assert cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "reajuste", "numero_oficio": "122"}).status_code == 201
    assert cl.post(f"/api/contratos/{cid}/pleitos", json=prazo).status_code == 201
    r = cl.post(f"/api/contratos/{cid}/pleitos", json={**prazo, "numero_oficio": "311"})
    assert r.status_code == 409 and "pedido de prorrogação" in r.json()["detail"], r.text


def test_dois_pleitos_simultaneos_do_mesmo_ciclo_criam_um_so(api):
    _, cid, _ = api
    c = db.get_conn()
    uid = c.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0]
    c.close()
    largada, criados, erros = threading.Barrier(2, timeout=10), [], []

    def criar(numero):
        conn = db.get_conn()
        try:
            largada.wait()
            criados.append(pleitos.criar(conn, uid, cid, "reajuste", numero))
        except Exception as e:
            erros.append(e)
        finally:
            conn.close()

    ts = [threading.Thread(target=criar, args=(n,)) for n in ("122", "130")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(criados) == 1 and [type(e).__name__ for e in erros] == ["RascunhoAberto"]


def test_pleito_com_envio_reservado_nao_se_descarta_e_segura_o_ciclo(api):
    """Revisor da PR #94 (R1): e-mail que saiu sem registro deixa a reserva presa; descartar e criar outro
    abriria caminho para o segundo oficio do mesmo ciclo."""
    cl, cid, _ = api
    pid, _ = _pronto(cl, cid)
    c = db.get_conn()
    uid = c.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0]
    envio_reserva.reservar(c, "pleitos", pid, uid)
    c.close()
    r = cl.post(f"/api/pleitos/{pid}/descartar", json={"motivo": "ofício errado"})
    # a mesma recusa do envio: com o codigo, a tela oferece a liberacao (revisor da PR #94, R2)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "ENVIO_RESERVADO", r.text
    assert "Enviados" in r.json()["detail"]["mensagem"] and r.json()["detail"]["liberavel_a_partir_de"]
    assert _estado(pid)[0]["situacao"] == "assinado"
    assert cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "reajuste", "numero_oficio": "130"}).status_code == 409


def test_pleito_descartado_durante_o_envio_nao_sai(api, monkeypatch):
    """Revisor da PR #94 (R1): outra aba descarta entre a leitura do envio e a reserva; o e-mail nao pode sair."""
    cl, cid, _ = api
    pid, corpo = _pronto(cl, cid)
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    original = pleitos.previa_envio

    def previa_e_descarte_na_outra_aba(conn, *a, **k):
        pv = original(conn, *a, **k)
        outra = db.get_conn()
        try:
            uid = outra.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0]
            pleitos.descartar(outra, uid, pid, "descartado na outra aba")
        finally:
            outra.close()
        return pv

    monkeypatch.setattr(pleitos, "previa_envio", previa_e_descarte_na_outra_aba)
    r = cl.post(f"/api/pleitos/{pid}/enviar", json=corpo)
    assert r.status_code == 422 and "descartado" in r.json()["detail"], r.text
    assert falso.enviados == []
    assert _estado(pid) == ({"situacao": "descartado", "envio_id": None, "envio_reservado_em": None}, 0)


def test_corpo_formatado_do_pleito_sai_sanitizado(api, tmp_path):
    """Issue #191: o HTML do editor passa pela lista fechada antes de ir ao orgao."""
    from tests.test_html_email import LIMPO, PERIGOSO, corpo_enviado
    cl, cid, _ = api
    pid, corpo = _pronto(cl, cid)
    r = cl.post(f"/api/pleitos/{pid}/enviar", json={**corpo, "corpo": PERIGOSO})
    assert r.status_code == 200, r.text
    assert corpo_enviado(tmp_path / "sim") == LIMPO


# --- reiteracao do pleito de reajuste (issue #277) ------------------------------------------------------------

def _reiteracao_pronta(cl, cid):
    """Pleito original enviado e a reiteracao dele montada, assinada e com a previa (fixture: MT-PAR)."""
    original, corpo = _pronto(cl, cid)
    assert cl.post(f"/api/pleitos/{original}/enviar", json=corpo).status_code == 200
    r = cl.post(f"/api/pleitos/{original}/reemitir", json={"reemissao": "reiteracao", "numero_oficio": "245"})
    assert r.status_code == 201, r.text
    p = r.json()
    assert (p["reemite_pleito_id"], p["reemissao"], p["anterior"]["id"]) == (original, "reiteracao", original)
    assert "reiteramos" in p["corpo_padrao"] and "CT/122/LT/" in p["corpo_padrao"]
    pid = p["id"]
    cl.post(f"/api/pleitos/{pid}/montar", json={})
    doc = cl.get(f"/api/pleitos/{pid}/documento")
    cl.post(f"/api/pleitos/{pid}/assinado", files=_arquivo("a.pdf", _assinar(doc.content), "application/pdf"))
    pv = cl.post(f"/api/pleitos/{pid}/previa").json()
    assert pv["pendencias"] == [], pv["pendencias"]                 # reiteracao nao exige cronograma nem memoria
    return original, pid, {k: pv[k] for k in ("para", "copia", "assunto", "corpo")}


def test_reiteracao_pela_api_liga_ao_anterior_e_segundo_clique_nao_reenvia(api):
    cl, cid, _ = api
    original, pid, corpo = _reiteracao_pronta(cl, cid)
    assert cl.post(f"/api/pleitos/{pid}/enviar", json=corpo).status_code == 200
    r = cl.post(f"/api/pleitos/{pid}/enviar", json=corpo)              # segundo clique: nada sai de novo
    assert r.status_code == 422 and "já enviado" in r.json()["detail"], r.text
    assert _estado(pid)[1] == 2                                         # o original e a reiteracao, uma vez cada
    lista = {p["id"]: p for p in cl.get(f"/api/contratos/{cid}/reajuste").json()["pleitos"]}
    assert [x["id"] for x in lista[original]["reemissoes"]] == [pid] and lista[pid]["anterior"]["id"] == original
    # sem aditivo depois do pleito, so' a reiteracao (a reemissao do cronograma pede aditivo)
    assert lista[original]["reemissoes_possiveis"] == [] and lista[pid]["reemissoes_possiveis"] == ["reiteracao"]
    ciclo = cl.get(f"/api/contratos/{cid}/reajuste").json()["ciclos"][0]
    assert (ciclo["pleito"]["id"], ciclo["pedido"]["id"]) == (pid, original)
    # o anterior ja' foi reiterado: reiterar ele de novo e' recusado
    r = cl.post(f"/api/pleitos/{original}/reemitir", json={"reemissao": "reiteracao", "numero_oficio": "250"})
    assert r.status_code == 422 and "mais recente" in r.json()["detail"], r.text


def test_dois_envios_simultaneos_da_reiteracao_mandam_um_so(api, monkeypatch):
    cl, cid, _ = api
    _, pid, corpo = _reiteracao_pronta(cl, cid)
    args = [corpo[k] for k in ("para", "copia", "assunto", "corpo")]
    c = db.get_conn()
    u = {"id": c.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0],
         "email": "admin@lotufo.com"}
    erros = []

    def segundo():
        outra = db.get_conn()
        try:
            pleitos.enviar(outra, u, pid, *args)
        except Exception as e:
            erros.append(e)
        finally:
            outra.close()

    falso = CorreioFalso(no_meio=segundo)
    monkeypatch.setattr(correio, "cliente", falso)
    eid = pleitos.enviar(c, u, pid, *args)
    c.close()
    assert [type(e).__name__ for e in erros] == ["EnvioEmAndamento"]
    assert len(falso.enviados) == 1
    assert _estado(pid) == ({"situacao": "enviado", "envio_id": eid, "envio_reservado_em": None}, 2)


def test_reemitir_pela_api_valida_em_portugues(api):
    cl, cid, _ = api
    rascunho = cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "reajuste", "numero_oficio": "122"}).json()["id"]
    r = cl.post(f"/api/pleitos/{rascunho}/reemitir", json={"reemissao": "reiteracao", "numero_oficio": "245"})
    assert r.status_code == 422 and "enviado" in r.json()["detail"], r.text
    assert cl.post("/api/pleitos/999999/reemitir", json={"reemissao": "reiteracao", "numero_oficio": "1"}
                   ).status_code == 404
