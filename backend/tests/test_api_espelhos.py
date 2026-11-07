import hashlib
import threading

import pytest
from app import auth, cadastro_aplicar, correio, db, espelhos, graph, medicoes
from tests.test_envio_reserva import CorreioFalso, sempre_travado
from tests.test_cadastro_aplicar import _cad_com_espelho
from tests.test_cadastro_arquivos import _modelo_completo
from tests.conftest import _pdf_com_texto


@pytest.fixture
def ambiente_api(client, tmp_path, monkeypatch):
    """Banco do `client` com a regra do MT-402 ativa e o simulador de e-mail ligado."""
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn = db.get_conn()
    uid = auth.criar_usuario(conn, "Leo", "leo@l.com", "senha-forte-123", "admin")
    conn.execute("UPDATE certidao_tipos SET aplicavel_por_padrao=0"); conn.commit()
    cad = _cad_com_espelho(tmp_path)
    m = tmp_path / "m.docx"; m.write_bytes(_modelo_completo())
    cad["espelho"][0]["modelos"]["medicao"] = {"caminho": m, "sha256": hashlib.sha256(m.read_bytes()).hexdigest()}
    cad["espelho"][0]["situacao"] = cad["espelho"][0]["regra"]["situacao"] = "ativa"
    cadastro_aplicar.aplicar(conn, uid, cad)
    cid = conn.execute("SELECT id FROM contratos").fetchone()[0]
    conn.close()
    return cid


def _login(client, email, senha="senha-forte-123"):
    r = client.post("/api/auth/login", json={"email": email, "senha": senha})
    assert r.status_code == 200, r.text
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))
    client.headers["X-CSRF-Token"] = r.json()["csrf"]


def test_fluxo_previa_gerar_baixar_enviar(client_admin, ambiente_api):
    cid = ambiente_api
    r = client_admin.get(f"/api/contratos/{cid}/espelho")
    assert r.status_code == 200 and r.json()["regra"]["situacao"] == "ativa" and r.json()["espelhos"] == []
    corpo = {"numero": 23, "competencia": "2026-01", "entradas": {"medicao": "278.509,92"}}
    p = client_admin.post(f"/api/contratos/{cid}/espelho/previa", json=corpo)
    assert p.status_code == 200, p.text
    assert p.json()["saidas"][0]["valor"] == 27850992
    g = client_admin.post(f"/api/contratos/{cid}/espelho", json=corpo)
    assert g.status_code == 201, g.text
    eid = g.json()["espelho_id"]
    d = client_admin.get(f"/api/espelhos/{eid}").json()
    a = client_admin.get(f"/api/espelhos/{eid}/arquivos/{d['arquivos'][0]['documento_id']}")
    assert a.status_code == 200 and a.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "ESPELHO%20-%20MT-402" in a.headers["content-disposition"] or "ESPELHO - MT-402" in a.headers["content-disposition"]
    pe = client_admin.get(f"/api/espelhos/{eid}/envio").json()
    e = client_admin.post(f"/api/espelhos/{eid}/enviar", json={k: pe[k] for k in ("para", "copia", "assunto", "corpo")})
    assert e.status_code == 200, e.text
    assert e.json()["envio_id"] == 1
    assert client_admin.get(f"/api/espelhos/{eid}").json()["medicoes"][0]["estado"] == "espelho_enviado"
    assert client_admin.get(f"/api/contratos/{cid}/espelho").json()["espelhos"][0]["envio"]["para"] == pe["para"]


def test_valor_invalido_e_obra_inexistente(client_admin, ambiente_api):
    cid = ambiente_api
    r = client_admin.post(f"/api/contratos/{cid}/espelho/previa",
                          json={"numero": 1, "competencia": "2026-01", "entradas": {"medicao": "12.34"}})
    assert r.status_code == 422 and "medicao" in r.json()["detail"]
    r = client_admin.post("/api/contratos/999/espelho/previa",
                          json={"numero": 1, "competencia": "2026-01", "entradas": {}})
    assert r.status_code == 404


def test_arquivo_de_outro_espelho_da_404(client_admin, ambiente_api):
    cid = ambiente_api
    corpo = {"numero": 1, "competencia": "2026-01", "entradas": {"medicao": "1,00"}}
    e1 = client_admin.post(f"/api/contratos/{cid}/espelho", json=corpo).json()["espelho_id"]
    e2 = client_admin.post(f"/api/contratos/{cid}/espelho", json={**corpo, "numero": 2}).json()["espelho_id"]
    doc2 = client_admin.get(f"/api/espelhos/{e2}").json()["arquivos"][0]["documento_id"]
    assert client_admin.get(f"/api/espelhos/{e1}/arquivos/{doc2}").status_code == 404
    assert client_admin.get("/api/espelhos/999").status_code == 404


def test_diretoria_le_mas_nao_gera(client, ambiente_api):
    cid = ambiente_api
    conn = db.get_conn()
    auth.criar_usuario(conn, "Dir", "dir@l.com", "senha-forte-123", "diretoria"); conn.close()
    _login(client, "dir@l.com")
    assert client.get(f"/api/contratos/{cid}/espelho").status_code == 200
    r = client.post(f"/api/contratos/{cid}/espelho",
                    json={"numero": 1, "competencia": "2026-01", "entradas": {"medicao": "1,00"}})
    assert r.status_code == 403


def test_evidencia_do_orgao_anexada_e_baixada(client_admin, ambiente_api):
    cid = ambiente_api
    eid = client_admin.post(f"/api/contratos/{cid}/espelho",
                            json={"numero": 3, "competencia": "2026-02", "entradas": {"medicao": "1,00"}}).json()["espelho_id"]
    mid = client_admin.get(f"/api/espelhos/{eid}").json()["medicoes"][0]["id"]
    pdf = _pdf_com_texto("medição 3 informada pelo órgão")
    r = client_admin.post(f"/api/medicoes/{mid}/documentos", files={"arquivo": ("orgao.pdf", pdf, "application/pdf")})
    assert r.status_code == 201, r.text
    did = r.json()["documento_id"]
    docs = client_admin.get(f"/api/medicoes/{mid}").json()["documentos"]
    ev = next(d for d in docs if d["tipo_doc"] == "evidencia_orgao")
    assert ev["nome"] == "orgao.pdf" and ev["arquivo"].startswith("evidencias/") and ev["tamanho"] == len(pdf)
    b = client_admin.get(f"/api/medicoes/{mid}/documentos/{did}")
    assert b.status_code == 200 and b.headers["content-type"].startswith("application/pdf") and b.content == pdf
    # o mesmo PDF de novo nao duplica
    assert client_admin.post(f"/api/medicoes/{mid}/documentos",
                             files={"arquivo": ("orgao2.pdf", pdf, "application/pdf")}).json()["repetido"] is True


def test_evidencia_que_nao_e_pdf_da_415(client_admin, ambiente_api):
    cid = ambiente_api
    eid = client_admin.post(f"/api/contratos/{cid}/espelho",
                            json={"numero": 4, "competencia": "2026-02", "entradas": {"medicao": "1,00"}}).json()["espelho_id"]
    mid = client_admin.get(f"/api/espelhos/{eid}").json()["medicoes"][0]["id"]
    r = client_admin.post(f"/api/medicoes/{mid}/documentos", files={"arquivo": ("x.pdf", b"nao e pdf", "application/pdf")})
    assert r.status_code == 415
    assert client_admin.post("/api/medicoes/999/documentos",
                             files={"arquivo": ("x.pdf", b"%PDF-1.4", "application/pdf")}).status_code == 404


# --- envio unico e registrado (pacote 1 da fase 4, 10/10/2026) ---------------------------------------------
# Reenviar a versao vigente continua permitido ("este envio substitui"); o que nao pode e' o SIMULTANEO.

def _pronto(cl, cid, numero=40):
    eid = cl.post(f"/api/contratos/{cid}/espelho",
                  json={"numero": numero, "competencia": "2026-10", "entradas": {"medicao": "100,00"}}).json()["espelho_id"]
    pe = cl.get(f"/api/espelhos/{eid}/envio").json()
    return eid, {k: pe[k] for k in ("para", "copia", "assunto", "corpo")}


def _estado(eid):
    c = db.get_conn()
    try:
        e = c.execute("SELECT envio_id, envio_reservado_em FROM espelhos WHERE id=?", (eid,)).fetchone()
        return dict(e), c.execute("SELECT COUNT(*) FROM envios").fetchone()[0]
    finally:
        c.close()


def test_segundo_envio_do_espelho_durante_o_primeiro_e_recusado(client_admin, ambiente_api, monkeypatch):
    """A-01 deterministico."""
    eid, corpo = _pronto(client_admin, ambiente_api)
    args = [corpo[k] for k in ("para", "copia", "assunto", "corpo")]
    c = db.get_conn()
    u = {"id": c.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0],
         "email": "admin@lotufo.com"}
    erros = []

    def segundo():
        outra = db.get_conn()
        try:
            espelhos.enviar(outra, u, eid, *args)
        except Exception as e:
            erros.append(e)
        finally:
            outra.close()

    falso = CorreioFalso(no_meio=segundo)
    monkeypatch.setattr(correio, "cliente", falso)
    envio_id = espelhos.enviar(c, u, eid, *args)
    c.close()
    assert [type(e).__name__ for e in erros] == ["EnvioEmAndamento"]
    assert len(falso.enviados) == 1
    assert _estado(eid) == ({"envio_id": envio_id, "envio_reservado_em": None}, 1)


@pytest.mark.parametrize("espera", [0.3, 0.0], ids=["graph-lento", "instantaneo"])
def test_tres_envios_simultaneos_do_espelho_saem_uma_vez(client_admin, ambiente_api, monkeypatch, espera):
    """A-01 com threads. `instantaneo` e' o S8 (10/10/2026): com o envio acabando antes de os outros lerem o
    espelho, eles viam o envio_id novo e reenviavam sem ninguem confirmar."""
    eid, corpo = _pronto(client_admin, ambiente_api)
    falso = CorreioFalso(espera=espera)
    monkeypatch.setattr(correio, "cliente", falso)
    largada, respostas = threading.Barrier(3), []

    def dispara():
        largada.wait()
        respostas.append(client_admin.post(f"/api/espelhos/{eid}/enviar", json=corpo))

    ts = [threading.Thread(target=dispara) for _ in range(3)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(r.status_code for r in respostas) == [200, 409, 409], [r.text for r in respostas]
    assert len(falso.enviados) == 1 and _estado(eid)[1] == 1
    # reenvio depois, de proposito e confirmado, continua valendo
    assert client_admin.post(f"/api/espelhos/{eid}/enviar", json={**corpo, "reenviar": True}).status_code == 200


def test_reenvio_da_mesma_versao_exige_confirmacao(client_admin, ambiente_api, monkeypatch):
    """S8: segundo envio da versao ja' enviada sem `reenviar` -> 409 ESPELHO_JA_ENVIADO, nenhum e-mail novo."""
    eid, corpo = _pronto(client_admin, ambiente_api)
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    assert client_admin.post(f"/api/espelhos/{eid}/enviar", json=corpo).status_code == 200
    r = client_admin.post(f"/api/espelhos/{eid}/enviar", json=corpo)
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["codigo"] == "ESPELHO_JA_ENVIADO" and d["reservado_por_nome"] == "Admin" and d["reservado_em"]
    assert d["mensagem"].startswith("Esta versão do espelho já foi enviada ao faturamento (às ")
    assert d["mensagem"].endswith("por Admin). Para mandar de novo, confirme o reenvio.")
    assert len(falso.enviados) == 1 and _estado(eid) == ({"envio_id": 1, "envio_reservado_em": None}, 1)
    r = client_admin.post(f"/api/espelhos/{eid}/enviar", json={**corpo, "reenviar": True})
    assert r.status_code == 200 and len(falso.enviados) == 2 and _estado(eid)[1] == 2


def test_falha_antes_do_email_destrava_o_espelho(client_admin, ambiente_api, monkeypatch):
    eid, corpo = _pronto(client_admin, ambiente_api)
    monkeypatch.setattr(correio, "cliente", CorreioFalso(falha=graph.ErroGraph("Graph fora do ar")))
    assert client_admin.post(f"/api/espelhos/{eid}/enviar", json=corpo).status_code == 422
    assert _estado(eid) == ({"envio_id": None, "envio_reservado_em": None}, 0)
    monkeypatch.setattr(correio, "cliente", CorreioFalso())
    assert client_admin.post(f"/api/espelhos/{eid}/enviar", json=corpo).status_code == 200


def test_espelho_registrado_pela_metade_diz_que_saiu_e_trava_a_repeticao(client_admin, ambiente_api, monkeypatch):
    """A-03 no espelho: a marcacao final pega o banco travado depois do e-mail."""
    eid, corpo = _pronto(client_admin, ambiente_api)
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    monkeypatch.setattr(medicoes, "marcar_espelho_enviado", sempre_travado)
    r = client_admin.post(f"/api/espelhos/{eid}/enviar", json=corpo)
    assert r.status_code == 500 and "O e-mail SAIU" in r.json()["detail"], r.text
    e, envios = _estado(eid)
    assert e["envio_id"] is None and e["envio_reservado_em"] is not None and envios == 1
    r = client_admin.post(f"/api/espelhos/{eid}/enviar", json=corpo)
    assert r.status_code == 409 and len(falso.enviados) == 1


# --- testes de quebra 10/10/2026, A-20: competencia fora da vida do contrato ---

def _datas_do_contrato(cid, execucao_inicio, vigencia_inicio):
    conn = db.get_conn()
    try:
        conn.execute("UPDATE contratos SET execucao_inicio=?, vigencia_inicio=? WHERE id=?",
                     (execucao_inicio, vigencia_inicio, cid))
        conn.commit()
    finally:
        conn.close()


def test_competencia_anterior_ao_inicio_do_contrato_da_422(client_admin, ambiente_api):
    cid = ambiente_api
    _datas_do_contrato(cid, "2023-03-01", "2023-03-01")
    corpo = {"numero": 33, "competencia": "2020-01", "entradas": {"medicao": "100,00"}}
    for rota in ("espelho/previa", "espelho"):
        r = client_admin.post(f"/api/contratos/{cid}/{rota}", json=corpo)
        assert r.status_code == 422, r.text
        assert r.json()["detail"] == "Competência 01/2020 é anterior ao início do contrato (03/2023)"
    assert client_admin.get(f"/api/contratos/{cid}/espelho").json()["espelhos"] == []
    # sem data de execucao vale a de vigencia
    _datas_do_contrato(cid, None, "2024-05-10")
    r = client_admin.post(f"/api/contratos/{cid}/espelho/previa", json={**corpo, "competencia": "2024-04"})
    assert r.status_code == 422 and "(05/2024)" in r.json()["detail"]
    r = client_admin.post(f"/api/contratos/{cid}/espelho/previa", json={**corpo, "competencia": "2024-05"})
    assert r.status_code == 200 and r.json()["avisos"] == []


def test_competencia_anterior_a_da_ultima_medicao_so_avisa(client_admin, ambiente_api):
    cid = ambiente_api
    corpo = {"numero": 5, "competencia": "2026-08", "entradas": {"medicao": "100,00"}}
    assert client_admin.post(f"/api/contratos/{cid}/espelho", json=corpo).status_code == 201
    r = client_admin.post(f"/api/contratos/{cid}/espelho/previa", json={**corpo, "numero": 6, "competencia": "2026-07"})
    assert r.status_code == 200
    assert r.json()["avisos"] == ["Competência 07/2026 é anterior à da última medição (nº 5, 08/2026): confira"]
    r = client_admin.post(f"/api/contratos/{cid}/espelho/previa", json={**corpo, "numero": 6, "competencia": "2026-09"})
    assert r.status_code == 200 and r.json()["avisos"] == []
    # gerar de novo a propria medicao com outra competencia nao se compara consigo mesma
    r = client_admin.post(f"/api/contratos/{cid}/espelho/previa", json={**corpo, "competencia": "2026-07"})
    assert r.status_code == 200 and r.json()["avisos"] == ["Medição 5 de execução já tem espelho: será gerada uma versão nova"]


def test_contrato_sem_data_de_inicio_nao_gera_espelho(client_admin, ambiente_api):
    """Gate Sol S2 (10/10/2026): sem execucao_inicio nem vigencia_inicio a conferencia do A-20 nao valia nada."""
    cid = ambiente_api
    _datas_do_contrato(cid, None, None)
    corpo = {"numero": 1, "competencia": "2026-08", "entradas": {"medicao": "100,00"}}
    for rota in ("espelho/previa", "espelho"):
        r = client_admin.post(f"/api/contratos/{cid}/{rota}", json=corpo)
        assert r.status_code == 422
        assert r.json()["detail"] == "Contrato sem data de início cadastrada: complete o cadastro antes de gerar espelho"


def test_medicao_recebida_nao_gera_espelho_e_diz_o_tipo_por_extenso(client_admin, ambiente_api):
    """B-12 (10/10/2026): "Medição 32 (execucao) já está recebida" trazia o codigo interno do tipo."""
    from app import db
    cid = ambiente_api
    corpo = {"numero": 5, "competencia": "2026-08", "entradas": {"medicao": "100,00"}}
    assert client_admin.post(f"/api/contratos/{cid}/espelho", json=corpo).status_code == 201
    conn = db.get_conn()
    conn.execute("UPDATE medicoes SET estado='recebida' WHERE contrato_id=? AND numero=5", (cid,))
    conn.commit(); conn.close()
    r = client_admin.post(f"/api/contratos/{cid}/espelho/previa", json=corpo)
    assert r.status_code == 422
    assert r.json()["detail"] == "Medição 5 de execução já está recebida: não pode gerar espelho de novo"


def test_corpo_formatado_sai_sanitizado_e_com_a_assinatura_no_fim(client_admin, ambiente_api, tmp_path):
    """Issue #191: o HTML do editor passa pela lista fechada; a assinatura continua no fim."""
    from tests.test_correio import PNG
    from tests.test_html_email import LIMPO, PERIGOSO, corpo_enviado
    eid, corpo = _pronto(client_admin, ambiente_api)
    c = db.get_conn()
    correio.gravar_assinatura(c, c.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0], PNG)
    c.close()
    r = client_admin.post(f"/api/espelhos/{eid}/enviar", json={**corpo, "corpo": PERIGOSO})
    assert r.status_code == 200, r.text
    enviado = corpo_enviado(tmp_path / "sim")
    assert enviado.startswith(LIMPO) and f"cid:{correio.ASSINATURA_CID}" in enviado.removeprefix(LIMPO)
    assert "script" not in enviado and "onclick" not in enviado and "position" not in enviado


def test_corpo_em_texto_puro_continua_como_antes(client_admin, ambiente_api, tmp_path):
    from tests.test_html_email import corpo_enviado
    eid, corpo = _pronto(client_admin, ambiente_api)
    r = client_admin.post(f"/api/espelhos/{eid}/enviar", json={**corpo, "corpo": "Bom dia,\n\nSegue a <nota>."})
    assert r.status_code == 200, r.text
    assert corpo_enviado(tmp_path / "sim") == "<p>Bom dia,</p><p>&nbsp;</p><p>Segue a &lt;nota&gt;.</p>"


# --- issue #284: seguir sem boletim, com justificativa, e o valor do aprovado ---------------------------------

def _planilha_enviada(cid, numero=23, pedido=12_345_67):
    c = db.get_conn()
    try:
        mid = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
                        "valor_protocolado_origem) VALUES (?,?,'execucao','2026-01','planilha_enviada',?,'manual')",
                        (cid, numero, pedido)).lastrowid
        c.commit()
    finally:
        c.close()
    return mid


def test_api_seguir_sem_boletim_exige_justificativa(client_admin, ambiente_api):
    cid = ambiente_api
    mid = _planilha_enviada(cid)
    corpo = {"numero": 23, "competencia": "2026-01", "entradas": {"medicao": "12.345,67"}}
    p = client_admin.post(f"/api/contratos/{cid}/espelho/previa", json=corpo)
    assert p.status_code == 200, p.text
    assert p.json()["medicoes"][0]["sem_boletim"] is True and p.json()["entradas"] == {"medicao": 12_345_67}
    r = client_admin.post(f"/api/contratos/{cid}/espelho", json=corpo)
    assert r.status_code == 422 and "seguir sem boletim" in r.json()["detail"]
    r = client_admin.post(f"/api/contratos/{cid}/espelho",
                          json={**corpo, "justificativa_sem_boletim": "NF vai junto com o ofício ao órgão"})
    assert r.status_code == 201, r.text
    m = client_admin.get(f"/api/medicoes/{mid}").json()
    assert (m["estado"], m["valor_protocolado_centavos"]) == ("espelho_gerado", 12_345_67)
    assert any(e["texto"].startswith("Espelho gerado sem boletim: NF vai junto") for e in m["edicoes_valor"])


# --- issue #460: a planilha/carta gerada (sem envio registrado) segue ao espelho sem boletim, em toda obra ---------

@pytest.mark.parametrize("familia", ["sinfra", "mtpar", "ses", "prefeitura"])
def test_api_planilha_gerada_segue_sem_boletim_com_o_pedido_da_ultima_versao(client_admin, ambiente_api, familia):
    from tests.test_api_medicoes import _arquivos_planilha
    cid = ambiente_api
    c = db.get_conn()
    c.execute("UPDATE orgaos SET familia=? WHERE id=(SELECT orgao_id FROM contratos WHERE id=?)", (familia, cid))
    c.commit(); c.close()
    r = client_admin.post(f"/api/contratos/{cid}/planilhas", files=_arquivos_planilha("oficio 27"),
                          data={"numero": 27, "competencia": "2026-08", "periodo_inicio": "2026-08-01",
                                "periodo_fim": "2026-08-31", "valor": "719.190,72"})
    assert r.status_code == 201, r.text
    mid = r.json()["medicao_id"]
    # a Rev01, ainda gerada (nunca enviada): o pedido do espelho e' o dela, a ultima
    r = client_admin.post(f"/api/medicoes/{mid}/planilhas", files=_arquivos_planilha("rev01"),
                          data={"periodo_inicio": "2026-08-01", "periodo_fim": "2026-08-31", "valor": "700.000,01",
                                "motivo": "Rev01: fiscal pediu ajuste"})
    assert r.status_code == 201, r.text
    corpo = {"numero": 27, "competencia": "2026-08", "entradas": {"medicao": "700.000,01"}}
    p = client_admin.post(f"/api/contratos/{cid}/espelho/previa", json=corpo)
    assert p.status_code == 200, p.text
    assert p.json()["medicoes"][0]["sem_boletim"] is True
    assert p.json()["travados"] == [{"tipo": "execucao", "valor_centavos": 700_000_01, "fonte": "pedido",
                                     "opcional": True, "sem_boletim": True}]
    r = client_admin.post(f"/api/contratos/{cid}/espelho", json=corpo)
    assert r.status_code == 422 and "seguir sem boletim" in r.json()["detail"], r.text
    r = client_admin.post(f"/api/contratos/{cid}/espelho", json={**corpo, "entradas": {"medicao": "719.190,72"},
                                                                 "justificativa_sem_boletim": "enviada ao órgão por fora"})
    assert r.status_code == 422 and "700.000,01" in r.json()["detail"], r.text     # o pedido da v1 nao vale mais
    r = client_admin.post(f"/api/contratos/{cid}/espelho",
                          json={**corpo, "justificativa_sem_boletim": "enviada ao órgão por fora"})
    assert r.status_code == 201, r.text
    m = client_admin.get(f"/api/medicoes/{mid}").json()
    assert (m["estado"], m["valor_protocolado_centavos"]) == ("espelho_gerado", 700_000_01)
    assert any(e["texto"] == "Espelho gerado sem boletim e sem o envio da planilha/carta registrado: enviada ao órgão "
               "por fora por Admin" for e in m["edicoes_valor"]), m["edicoes_valor"]


def test_api_espelho_usa_o_aprovado_do_boletim(client_admin, ambiente_api):
    cid = ambiente_api
    mid = _planilha_enviada(cid)
    b = client_admin.post(f"/api/medicoes/{mid}/boletim", files={"arquivo": ("b.pdf", _pdf_com_texto("SMO 23"),
                                                                             "application/pdf")},
                          data={"valor": "12.000,01", "data": "2026-02-10", "numero_orgao": "SMO 23"})
    assert b.status_code == 201, b.text
    corpo = {"numero": 23, "competencia": "2026-01", "entradas": {"medicao": "12.345,67"}}   # o pedido: recusa
    r = client_admin.post(f"/api/contratos/{cid}/espelho", json=corpo)
    assert r.status_code == 422 and "R$ 12.000,01" in r.json()["detail"]
    r = client_admin.post(f"/api/contratos/{cid}/espelho", json={**corpo, "entradas": {}})
    assert r.status_code == 201, r.text
    d = client_admin.get(f"/api/espelhos/{r.json()['espelho_id']}").json()
    assert d["entradas"] == {"medicao": 12_000_01} and d["saidas"][0]["valor"] == 12_000_01
    m = client_admin.get(f"/api/medicoes/{mid}").json()
    assert (m["valor_protocolado_centavos"], m["valor_atestado_centavos"], m["diferenca_centavos"]) == (
        12_345_67, 12_000_01, -345_66)
