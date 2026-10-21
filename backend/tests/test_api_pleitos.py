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


# --- previsao de reajuste lida da planilha do pleito (issue #272; spec 2026-10-20 §2.2) ---------------------

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _previsoes(cid):
    c = db.get_conn()
    try:
        return [dict(r) for r in c.execute("SELECT competencia, valor_previsto_centavos AS valor, origem, pleito_id, "
                                           "data_base_mes, ciclo, usuario_id FROM reajuste_previsoes "
                                           "WHERE contrato_id=? ORDER BY id", (cid,))]
    finally:
        c.close()


def _novo_pleito(cl, cid):
    return cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "reajuste", "numero_oficio": "122"}).json()["id"]


def test_planilha_de_previsao_e_lida_para_conferir_sem_gravar(api):
    from tests.test_leitura_planilha_reajuste import planilha_modelo
    cl, cid, _ = api
    pid = _novo_pleito(cl, cid)
    r = cl.post(f"/api/pleitos/{pid}/previsao/ler", files=_arquivo("Mem. e Cron.xlsx", planilha_modelo(), XLSX))
    assert r.status_code == 200, r.text
    assert r.json()["reconhecida"] is True
    assert [(x["competencia"], x["valor_centavos"]) for x in r.json()["linhas"]] == [
        ("2026-03", 123456), ("2026-04", 200000), ("2026-05", 10)]
    assert _previsoes(cid) == []                       # ler so' mostra: quem grava e' o aceite


def test_planilha_fora_do_modelo_pede_a_digitacao(api):
    import io

    import openpyxl
    cl, cid, _ = api
    pid = _novo_pleito(cl, cid)
    wb = openpyxl.Workbook()
    buf = io.BytesIO()
    wb.save(buf)
    r = cl.post(f"/api/pleitos/{pid}/previsao/ler", files=_arquivo("outra.xlsx", buf.getvalue(), XLSX))
    assert r.status_code == 200, r.text
    assert r.json() == {"reconhecida": False, "mensagem": "Não reconheci a planilha; digite a previsão",
                        "motivo": "falta a aba Resumo", "linhas": []}
    # PDF no lugar da planilha: recusado na entrada, como os outros anexos .xlsx
    assert cl.post(f"/api/pleitos/{pid}/previsao/ler",
                   files=_arquivo("x.pdf", b"%PDF-1.4 x", "application/pdf")).status_code == 415


def test_aceitar_grava_previsoes_de_origem_pleito_e_aparecem_na_aba_reajuste(api):
    cl, cid, _ = api
    pid = _novo_pleito(cl, cid)
    linhas = [{"competencia": "2026-07", "valor_centavos": 123456}, {"competencia": "2026-08", "valor_centavos": -10}]
    r = cl.post(f"/api/pleitos/{pid}/previsao", json={"origem": "pleito", "linhas": linhas})
    assert r.status_code == 200, r.text
    grav = _previsoes(cid)
    assert [(p["competencia"], p["valor"], p["origem"], p["pleito_id"], p["data_base_mes"], p["ciclo"]) for p in grav] \
        == [("2026-07", 123456, "pleito", pid, "2024-06", 2026), ("2026-08", -10, "pleito", pid, "2024-06", 2026)]
    assert all(p["usuario_id"] for p in grav)
    aba = cl.get(f"/api/contratos/{cid}/reajuste").json()
    assert [(p["competencia"], p["valor_previsto_centavos"], p["origem"]) for p in aba["previsoes"]] == [
        ("2026-07", 123456, "pleito"), ("2026-08", -10, "pleito")]
    # aceitar de novo e' evento novo: o anterior fica, a leitura escolhe o mais recente
    cl.post(f"/api/pleitos/{pid}/previsao", json={"origem": "pleito",
                                                  "linhas": [{"competencia": "2026-07", "valor_centavos": 5}]})
    assert len(_previsoes(cid)) == 3
    vig = {p["competencia"]: p["valor_previsto_centavos"]
           for p in cl.get(f"/api/contratos/{cid}/reajuste").json()["previsoes"]}
    assert vig == {"2026-07": 5, "2026-08": -10}
    c = db.get_conn()
    try:
        acoes = [r[0] for r in c.execute("SELECT acao FROM audit_log WHERE entidade='pleito' AND entidade_id=?",
                                         (str(pid),))]
    finally:
        c.close()
    assert acoes.count("pleito.previsao") == 2


def test_previsao_digitada_grava_origem_manual(api):
    cl, cid, _ = api
    pid = _novo_pleito(cl, cid)
    r = cl.post(f"/api/pleitos/{pid}/previsao", json={"origem": "manual",
                                                      "linhas": [{"competencia": "2026-09", "valor_centavos": 700}]})
    assert r.status_code == 200, r.text
    assert [(p["origem"], p["pleito_id"]) for p in _previsoes(cid)] == [("manual", pid)]


@pytest.mark.parametrize("corpo, trecho", [
    ({"origem": "pleito", "linhas": []}, None),
    ({"origem": "apostilamento", "linhas": [{"competencia": "2026-07", "valor_centavos": 1}]}, None),
    ({"origem": "pleito", "linhas": [{"competencia": "2026-13", "valor_centavos": 1}]}, None),
    ({"origem": "pleito", "linhas": [{"competencia": "2026-07", "valor_centavos": 1.5}]}, None),
    ({"origem": "pleito", "linhas": [{"competencia": "2026-07", "valor_centavos": 10**13}]}, None),
    ({"origem": "pleito", "linhas": [{"competencia": "2026-07", "valor_centavos": 1},
                                     {"competencia": "2026-07", "valor_centavos": 2}]}, "07/2026"),
])
def test_previsao_invalida_e_recusada_sem_gravar(api, corpo, trecho):
    cl, cid, _ = api
    pid = _novo_pleito(cl, cid)
    r = cl.post(f"/api/pleitos/{pid}/previsao", json=corpo)
    assert r.status_code == 422, r.text
    if trecho:
        assert trecho in r.json()["detail"]
    assert _previsoes(cid) == []


def test_previsao_so_no_pleito_de_reajuste_que_vale(api):
    cl, cid, _ = api
    linhas = [{"competencia": "2026-07", "valor_centavos": 1}]
    prazo = cl.post(f"/api/contratos/{cid}/pleitos", json={"tipo": "prazo", "numero_oficio": "200", "dias": 30,
                                                           "justificativa": "atraso na liberacao da area"}).json()["id"]
    r = cl.post(f"/api/pleitos/{prazo}/previsao", json={"origem": "pleito", "linhas": linhas})
    assert r.status_code == 422 and "reajuste" in r.json()["detail"]
    pid = _novo_pleito(cl, cid)
    cl.post(f"/api/pleitos/{pid}/descartar", json={"motivo": "numero errado"})
    r = cl.post(f"/api/pleitos/{pid}/previsao", json={"origem": "pleito", "linhas": linhas})
    assert r.status_code == 422 and "descartado" in r.json()["detail"]
    assert cl.post("/api/pleitos/999999/previsao", json={"origem": "pleito", "linhas": linhas}).status_code == 404
    assert _previsoes(cid) == []
