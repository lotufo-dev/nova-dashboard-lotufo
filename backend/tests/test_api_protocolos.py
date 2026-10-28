"""Rotas do protocolo (bloco 5): fluxo pela API com o simulador do Graph, erros e permissao."""
import datetime
import json
import threading
import urllib.parse

import pytest

from app import auditoria, auth, cadastro_aplicar, correio, db, graph, medicoes, protocolo
from tests.test_envio_reserva import CorreioFalso, sempre_travado
from tests.test_protocolo import CARTAS, _assinar, _contrato, _pdf


@pytest.fixture
def api(client_admin, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    monkeypatch.setenv("DASH_SIGA_LINK_MODELO", "https://siga.exemplo.com.br/acompanhar?n={codigo}")    # issue #328
    c = db.get_conn()
    cad = {"orgaos": [{"chave": "mtpar", "nome": "MTPAR", "familia": "mtpar", "cnpj": None,
                       "regras": {"protocolo_para": ["protocolo@orgao-b.exemplo.com.br"], "documentos_medicao": [],
                                  "documentos_reajuste": []}}],
           "entidades": [{"chave": "lotufo", "nome": "Lotufo Engenharia e Construções Ltda", "cnpj": "31200101000130",
                          "papel": "lotufo", "coligada_rm": 1, "sigla_oficio": "LT", "nome_curto": "Lotufo"}],
           "contratos": [_contrato("Obra MTPAR", "mtpar", "099/2024/MTPAR")], "avisos": [], "geral": {"cartas": CARTAS}}
    cadastro_aplicar.aplicar(c, 1, cad)
    cid = c.execute("SELECT id FROM contratos WHERE nome_curto='Obra MTPAR'").fetchone()[0]
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, 23, 'execucao', '2026-09', 'nota_emitida', 1000000)", (cid,))
    mid = c.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]
    c.commit(); c.close()
    return client_admin, cid, mid


def _pdf_upload(dados, nome="assinado.pdf"):
    return {"arquivo": (nome, dados, "application/pdf")}


def test_fluxo_completo_pela_api(api):
    cl, cid, mid = api
    r = cl.post(f"/api/contratos/{cid}/protocolos", json={"etapa": "unico", "medicao_ids": [mid], "numero_oficio": "301"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["numero_oficio"] == "CT-301-LT-2026" and r.json()["corpo_padrao"]
    assert cl.get(f"/api/contratos/{cid}/protocolos").json()["protocolos"][0]["corpo_padrao"]   # a tela abre com o texto
    assert cl.post(f"/api/protocolos/{pid}/montar", json={}).status_code == 200
    pac = cl.get(f"/api/protocolos/{pid}/pacote")
    assert pac.status_code == 200 and pac.headers["content-type"] == "application/pdf"
    assert "CT-301-LT-2026 - Obra MTPAR - 23" in urllib.parse.unquote(pac.headers["content-disposition"])
    d = cl.post(f"/api/protocolos/{pid}/assinado", files=_pdf_upload(_assinar(pac.content))).json()
    assert d["conferencia"]["ok"] is True
    pv = cl.post("/api/protocolos/envio/previa", json={"protocolo_ids": [pid]}).json()
    r = cl.post("/api/protocolos/envio", json={"protocolo_ids": [pid], **{k: pv[k] for k in ("para", "copia", "assunto", "corpo")},
                                              "confirmadas": [x["mensagem"] for x in pv["pendencias"]]})
    assert r.status_code == 200, r.text
    assert cl.get(f"/api/protocolos/{pid}").json()["situacao"] == "enviado"


def test_erros_de_entrada(api):
    cl, cid, mid = api
    pid = cl.post(f"/api/contratos/{cid}/protocolos", json={"etapa": "unico", "medicao_ids": [mid],
                                                          "numero_oficio": "301"}).json()["id"]
    assert cl.post(f"/api/protocolos/{pid}/pecas", data={"tipo": "video"},
                   files=_pdf_upload(_pdf("X"), "x.pdf")).status_code == 422
    assert cl.get("/api/protocolos/999999").status_code == 404
    cl.post(f"/api/protocolos/{pid}/montar", json={})
    r = cl.post("/api/protocolos/envio", json={"protocolo_ids": [pid], "para": [], "copia": [], "assunto": "A",
                                              "corpo": "x", "justificativa": "teste"})
    assert r.status_code == 422 and "destinatário" in r.json()["detail"]


def test_diretoria_nao_cria_protocolo(api):
    cl, cid, mid = api
    c = db.get_conn()
    auth.criar_usuario(c, "Dir", "dir@l.com", "senha-forte-123", "diretoria")
    c.close()
    cl.cookies.clear()
    r = cl.post("/api/auth/login", json={"email": "dir@l.com", "senha": "senha-forte-123"})
    cl.cookies.set("sessao", r.cookies.get("sessao") or cl.cookies.get("sessao"))
    cl.headers["X-CSRF-Token"] = r.json()["csrf"]
    assert cl.post(f"/api/contratos/{cid}/protocolos",
                   json={"etapa": "unico", "medicao_ids": [mid], "numero_oficio": "1"}).status_code == 403


# --- envio unico e registrado (pacote 1 da fase 4, 10/10/2026) ---------------------------------------------

def _pronto(cl, cid, mid):
    """Protocolo montado e assinado + o corpo do POST de envio (com justificativa, que nao atrapalha, e o que falta
    confirmado, issue #213)."""
    pid = cl.post(f"/api/contratos/{cid}/protocolos",
                  json={"etapa": "unico", "medicao_ids": [mid], "numero_oficio": "301"}).json()["id"]
    cl.post(f"/api/protocolos/{pid}/montar", json={})
    cl.post(f"/api/protocolos/{pid}/assinado", files=_pdf_upload(_assinar(cl.get(f"/api/protocolos/{pid}/pacote").content)))
    pv = cl.post("/api/protocolos/envio/previa", json={"protocolo_ids": [pid]}).json()
    return pid, {"protocolo_ids": [pid], **{k: pv[k] for k in ("para", "copia", "assunto", "corpo")},
                 "justificativa": "teste do envio concorrente", "confirmadas": [x["mensagem"] for x in pv["pendencias"]]}


def _admin(c):
    return {"id": c.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0],
            "email": "admin@lotufo.com"}


def _estado(pid):
    c = db.get_conn()
    try:
        p = c.execute("SELECT situacao, envio_id, envio_reservado_em FROM protocolos WHERE id=?", (pid,)).fetchone()
        return dict(p), c.execute("SELECT COUNT(*) FROM envios").fetchone()[0]
    finally:
        c.close()


def test_segundo_envio_durante_o_primeiro_e_recusado(api, monkeypatch):
    """A-02 deterministico: com o e-mail 'saindo', outra conexao tenta o mesmo protocolo."""
    cl, cid, mid = api
    pid, corpo = _pronto(cl, cid, mid)
    args = [corpo[k] for k in ("para", "copia", "assunto", "corpo", "justificativa")]
    c = db.get_conn()
    u, erros = _admin(c), []

    def segundo():
        outra = db.get_conn()
        try:
            protocolo.enviar(outra, u, [pid], *args, confirmadas=corpo["confirmadas"])
        except Exception as e:
            erros.append(e)
        finally:
            outra.close()

    falso = CorreioFalso(no_meio=segundo)
    monkeypatch.setattr(correio, "cliente", falso)
    eid = protocolo.enviar(c, u, [pid], *args, confirmadas=corpo["confirmadas"])
    c.close()
    assert [type(e).__name__ for e in erros] == ["EnvioEmAndamento"]
    assert len(falso.enviados) == 1
    assert _estado(pid) == ({"situacao": "enviado", "envio_id": eid, "envio_reservado_em": None}, 1)


def test_tres_envios_simultaneos_saem_uma_vez(api, monkeypatch):
    """A-02 com threads: um 200, os outros 409, um e-mail e uma linha em `envios`."""
    cl, cid, mid = api
    pid, corpo = _pronto(cl, cid, mid)
    falso = CorreioFalso(espera=0.3)
    monkeypatch.setattr(correio, "cliente", falso)
    largada, respostas = threading.Barrier(3), []

    def dispara():
        largada.wait()
        respostas.append(cl.post("/api/protocolos/envio", json=corpo))

    ts = [threading.Thread(target=dispara) for _ in range(3)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(r.status_code for r in respostas) == [200, 409, 409], [r.text for r in respostas]
    assert all("Enviados" in r.json()["detail"]["mensagem"] for r in respostas if r.status_code == 409)
    assert len(falso.enviados) == 1 and _estado(pid)[1] == 1


def test_envio_recusa_se_os_anexos_mudaram_depois_da_previa(api, monkeypatch):
    """Issue #10, revisor R3 (PR #92): a tela manda os anexos que a pessoa viu na previa; se o servidor monta
    outros na hora do envio (NF anexada a' medicao com a previa aberta, p. ex.), recusa antes do e-mail."""
    cl, cid, mid = api
    pid, corpo = _pronto(cl, cid, mid)
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    vistos = [{"nome": a["nome"], "tamanho": a["tamanho"]}
              for a in cl.post("/api/protocolos/envio/previa", json={"protocolo_ids": [pid]}).json()["anexos"]]
    assert vistos
    r = cl.post("/api/protocolos/envio", json={**corpo, "anexos": vistos[:-1]})
    assert r.status_code == 422 and "anexos mudaram" in r.json()["detail"]
    assert _estado(pid) == ({"situacao": "assinado", "envio_id": None, "envio_reservado_em": None}, 0)
    assert falso.enviados == []
    r = cl.post("/api/protocolos/envio", json={**corpo, "anexos": vistos})
    assert r.status_code == 200, r.text
    assert len(falso.enviados) == 1


def test_falha_antes_do_email_destrava_e_a_segunda_tentativa_vai(api, monkeypatch):
    cl, cid, mid = api
    pid, corpo = _pronto(cl, cid, mid)
    monkeypatch.setattr(correio, "cliente", CorreioFalso(falha=graph.ErroGraph("Graph fora do ar")))
    r = cl.post("/api/protocolos/envio", json=corpo)
    assert r.status_code == 422 and "fora do ar" in r.json()["detail"]
    assert _estado(pid) == ({"situacao": "assinado", "envio_id": None, "envio_reservado_em": None}, 0)
    monkeypatch.setattr(correio, "cliente", CorreioFalso())
    assert cl.post("/api/protocolos/envio", json=corpo).status_code == 200


def test_registro_que_falha_depois_do_email_diz_que_saiu_e_trava_a_repeticao(api, monkeypatch):
    """A-03: o e-mail saiu e o banco nao gravou -> 500 dizendo a verdade (nao 503 'tente novamente')."""
    cl, cid, mid = api
    pid, corpo = _pronto(cl, cid, mid)
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    original = correio.registrar_envio
    monkeypatch.setattr(correio, "registrar_envio", sempre_travado)
    r = cl.post("/api/protocolos/envio", json=corpo)
    assert r.status_code == 500, r.text
    assert "O e-mail SAIU" in r.json()["detail"] and corpo["assunto"] in r.json()["detail"]
    assert "tente novamente" not in r.json()["detail"].lower()
    assert _estado(pid)[0]["envio_reservado_em"] is not None
    monkeypatch.setattr(correio, "registrar_envio", original)          # o banco voltou: repetir continua travado
    r = cl.post("/api/protocolos/envio", json=corpo)
    assert r.status_code == 409 and "em andamento" in r.json()["detail"]["mensagem"]
    assert len(falso.enviados) == 1


def test_marcacao_final_travada_tambem_diz_que_saiu(api, monkeypatch):
    """O registro do envio gravou, mas marcar o protocolo `enviado` pegou o banco travado."""
    cl, cid, mid = api
    pid, corpo = _pronto(cl, cid, mid)
    monkeypatch.setattr(correio, "cliente", CorreioFalso())
    monkeypatch.setattr(medicoes, "registrar_protocolo", sempre_travado)
    r = cl.post("/api/protocolos/envio", json=corpo)
    assert r.status_code == 500 and "O e-mail SAIU" in r.json()["detail"]
    p, envios = _estado(pid)
    assert p["situacao"] == "assinado" and p["envio_reservado_em"] is not None and envios == 1


def test_envio_de_nota_em_andamento_responde_409(api):
    cl, cid, mid = api
    pid, corpo = _pronto(cl, cid, mid)
    c = db.get_conn()
    with db.mutacao(c):
        c.execute("UPDATE protocolos SET envio_reservado_em=datetime('now'), envio_reservado_por=? WHERE id=?",
                  (_admin(c)["id"], pid))
    c.close()
    vistos = [{"nome": a["nome"], "tamanho": a["tamanho"]}
              for a in cl.get(f"/api/notas/envio/{pid}").json()["previa"]["anexos"]]
    r = cl.post(f"/api/notas/envio/{pid}/enviar",
                json={**{k: corpo[k] for k in ("para", "copia", "assunto", "corpo", "justificativa", "confirmadas")},
                      "anexos": vistos})
    d = r.json()["detail"]
    assert r.status_code == 409 and d["codigo"] == "ENVIO_RESERVADO" and d["reservado_por_nome"] == "Admin"
    assert "em andamento" in d["mensagem"] and d["reservado_em"] and d["liberavel_a_partir_de"]


def _entrar(cl, email):
    cl.cookies.clear()
    r = cl.post("/api/auth/login", json={"email": email, "senha": "senha-forte-123"})
    assert r.status_code == 200, r.text
    cl.cookies.set("sessao", r.cookies.get("sessao") or cl.cookies.get("sessao"))
    cl.headers["X-CSRF-Token"] = r.json()["csrf"]


def test_reserva_presa_so_sai_pela_liberacao_manual(api, monkeypatch):
    """Sem tomada automatica (10/10/2026): reserva presa da' 409 ate' alguem liberar, com justificativa."""
    cl, cid, mid = api
    pid, corpo = _pronto(cl, cid, mid)
    monkeypatch.setattr(correio, "cliente", CorreioFalso())
    c = db.get_conn()
    with db.mutacao(c):
        c.execute("UPDATE protocolos SET envio_reservado_em=datetime('now','-1 hours'), envio_reservado_por=? "
                  "WHERE id=?", (_admin(c)["id"], pid))
    auth.criar_usuario(c, "Dir", "dir@l.com", "senha-forte-123", "diretoria")
    auth.criar_usuario(c, "Eng", "eng@l.com", "senha-forte-123", "engenharia")
    c.close()
    r = cl.post("/api/protocolos/envio", json=corpo)
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "ENVIO_RESERVADO"
    pedido = {"tabela": "protocolos", "id": pid, "justificativa": "conferi os Enviados: o e-mail não saiu",
              "conferi_enviados": True}
    _entrar(cl, "dir@l.com")
    assert cl.post("/api/envios/liberar", json=pedido).status_code == 403
    _entrar(cl, "eng@l.com")
    assert cl.post("/api/envios/liberar", json={**pedido, "tabela": "usuarios"}).status_code == 422
    r = cl.post("/api/envios/liberar", json={**pedido, "justificativa": "curta"})
    assert r.status_code == 422 and "10 caracteres" in r.json()["detail"]
    assert cl.post("/api/envios/liberar", json={k: v for k, v in pedido.items() if k != "conferi_enviados"}
                   ).status_code == 422                                        # S5: declaracao obrigatoria
    r = cl.post("/api/envios/liberar", json={**pedido, "conferi_enviados": False})
    assert r.status_code == 422 and "Confirme que conferiu" in r.json()["detail"]
    assert cl.post("/api/envios/liberar", json=pedido).status_code == 200
    assert _estado(pid)[0]["envio_reservado_em"] is None
    assert cl.post("/api/envios/liberar", json=pedido).status_code == 422          # nada mais reservado
    assert cl.post("/api/protocolos/envio", json=corpo).status_code == 200


def test_liberar_envio_recente_pela_rota_e_recusado(api):
    """Gate Sol S1: reserva de 1 minuto pode ser um envio ainda saindo."""
    cl, cid, mid = api
    pid, _ = _pronto(cl, cid, mid)
    c = db.get_conn()
    with db.mutacao(c):
        c.execute("UPDATE protocolos SET envio_reservado_em=datetime('now','-1 minutes'), envio_reservado_por=? "
                  "WHERE id=?", (_admin(c)["id"], pid))
    c.close()
    r = cl.post("/api/envios/liberar", json={"tabela": "protocolos", "id": pid, "conferi_enviados": True,
                                             "justificativa": "conferi os Enviados: o e-mail não saiu"})
    assert r.status_code == 422 and "aguarde até" in r.json()["detail"]
    assert _estado(pid)[0]["envio_reservado_em"] is not None


def test_envio_incerto_no_graph_segura_a_reserva(api, monkeypatch):
    """Gate Sol S2: a conexao caiu no /send; o e-mail pode ter saido."""
    cl, cid, mid = api
    pid, corpo = _pronto(cl, cid, mid)
    monkeypatch.setattr(correio, "cliente", CorreioFalso(falha=correio.EnvioIncerto(None, corpo["assunto"],
                                                                                     corpo["para"])))
    r = cl.post("/api/protocolos/envio", json=corpo)
    assert r.status_code == 500 and "Não deu para confirmar se o e-mail saiu" in r.json()["detail"], r.text
    assert "depois de 15 minutos" in r.json()["detail"]
    p, envios = _estado(pid)
    assert p["envio_reservado_em"] is not None and p["situacao"] == "assinado" and envios == 0
    monkeypatch.setattr(correio, "cliente", CorreioFalso())
    assert cl.post("/api/protocolos/envio", json=corpo).status_code == 409


def test_qualquer_falha_na_marcacao_final_diz_que_o_email_saiu(api, monkeypatch):
    """Gate Sol S3: nao so' lock -- erro de auditoria, IntegrityError etc. depois do envio registrado."""
    cl, cid, mid = api
    pid, corpo = _pronto(cl, cid, mid)
    monkeypatch.setattr(correio, "cliente", CorreioFalso())
    original = auditoria.registrar

    def quebra_no_protocolo(conn, usuario_id, acao, *a, **k):
        if acao == "protocolo.enviar":
            raise RuntimeError("cadeia de auditoria quebrada")
        return original(conn, usuario_id, acao, *a, **k)

    monkeypatch.setattr(auditoria, "registrar", quebra_no_protocolo)
    r = cl.post("/api/protocolos/envio", json=corpo)
    assert r.status_code == 500 and "O e-mail SAIU" in r.json()["detail"], r.text
    p, envios = _estado(pid)
    assert p["situacao"] == "assinado" and p["envio_reservado_em"] is not None and envios == 1


def test_justificativa_curta_sem_pendencia_na_previa_nao_impede_marcar_depois_do_email(api, monkeypatch):
    """Gate Sol S6 (10/10/2026): a justificativa do envio e' opcional sem pendencia na previa. Se uma certidao
    vencer entre a previa e o envio, a marcacao (depois do e-mail) nao pode cair pelo minimo de 10 caracteres."""
    cl, cid, mid = api
    pid, corpo = _pronto(cl, cid, mid)
    monkeypatch.setattr(correio, "cliente", CorreioFalso())
    original, recebidas = medicoes.registrar_protocolo, []

    pendente = {"itens": [{"situacao": "pendente", "entidade_id": 1, "entidade": "Lotufo", "tipo": "CND Federal"}]}

    def espia(*a, **k):  # a certidao "vence" so' agora, depois da previa e do e-mail
        recebidas.append(k.get("justificativa"))
        with monkeypatch.context() as m:
            m.setattr(medicoes.checklist, "pronto_para_protocolar", lambda *x: pendente)
            return original(*a, **k)
    monkeypatch.setattr(medicoes, "registrar_protocolo", espia)
    # previa limpa (a nota da 23a fica de fora), tambem na conferencia sob o lock da reserva (issue #213)
    monkeypatch.setattr(protocolo, "_pendencias_envio", lambda *a, **k: [])
    r = cl.post("/api/protocolos/envio", json={**corpo, "justificativa": "ok", "confirmadas": None})
    assert r.status_code == 200, r.text
    assert len(recebidas) == 1 and len(recebidas[0]) >= protocolo.MIN_JUSTIFICATIVA
    assert cl.get(f"/api/medicoes/{mid}").json()["estado"] == "protocolada"


def test_corpo_formatado_do_protocolo_sai_sanitizado_e_com_link(api, tmp_path):
    """Issue #191: o HTML do editor passa pela lista fechada; o endereco https continua virando link."""
    from tests.test_html_email import LIMPO, PERIGOSO, corpo_enviado
    cl, cid, mid = api
    pid, corpo = _pronto(cl, cid, mid)
    html = PERIGOSO + "<div>Arquivo: https://arquivos.exemplo.com.br/a?b=1&c=2</div>"
    r = cl.post("/api/protocolos/envio", json={**corpo, "corpo": html})
    assert r.status_code == 200, r.text
    assert corpo_enviado(tmp_path / "sim") == (
        LIMPO + '<br>Arquivo: <a href="https://arquivos.exemplo.com.br/a?b=1&amp;c=2">'
                'https://arquivos.exemplo.com.br/a?b=1&amp;c=2</a>')


# --- issue #328: o link do SIGA na etapa 4 -----------------------------------------------------------------

LINK_SIGA = "https://siga.exemplo.com.br/acompanhar?n=AbCdEf1234"
MSG_LINK_INVALIDO = "Link do SIGA inválido: cole o link que o órgão mandou"


def _enviado(cl, cid, mid):
    pid, corpo = _pronto(cl, cid, mid)
    r = cl.post("/api/protocolos/envio", json=corpo)
    assert r.status_code == 200, r.text
    return pid


def _siga_processos(*campos):
    c = db.get_conn()
    try:
        return [tuple(r) for r in c.execute(f"SELECT {', '.join(campos)} FROM siga_processos ORDER BY id")]
    finally:
        c.close()


def _auditoria_siga():
    c = db.get_conn()
    try:
        return [dict(r) for r in c.execute("SELECT entidade, entidade_id, depois FROM audit_log "
                                           "WHERE acao='protocolo.siga' ORDER BY id")]
    finally:
        c.close()


def test_link_do_siga_valido_grava_o_processo_ligado_ao_protocolo_e_a_medicao(api):
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    assert cl.get(f"/api/protocolos/{pid}").json()["siga"] is None
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "MTPAR-PRO-2026/00123", "link_siga": LINK_SIGA})
    assert r.status_code == 200, r.text
    assert r.json()["numero_orgao"] == "MTPAR-PRO-2026/00123"
    siga = r.json()["siga"]
    assert siga["codigo"] == "AbCdEf1234" and siga["link"] == LINK_SIGA
    assert (siga["setor"], siga["com_quem"], siga["dias_uteis"], siga["lido_em"]) == (None, None, None, None)
    assert siga["registrado_em"]
    assert _siga_processos("codigo", "numero", "nome", "contrato_id", "protocolo_id", "medicao_id") == [
        ("AbCdEf1234", "MTPAR-PRO-2026/00123", "23ª Medição - Obra MTPAR", cid, pid, mid)]
    a = _auditoria_siga()
    assert [(x["entidade"], x["entidade_id"]) for x in a] == [("protocolo", str(pid))]
    assert json.loads(a[0]["depois"])["codigo"] == "AbCdEf1234"
    assert cl.get(f"/api/contratos/{cid}/protocolos").json()["protocolos"][0]["siga"]["codigo"] == "AbCdEf1234"


def test_so_o_codigo_tambem_vale_e_repetir_nao_duplica(api):
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    for _ in range(2):
        r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1", "link_siga": " AbCdEf1234 "})
        assert r.status_code == 200, r.text
    assert r.json()["siga"]["link"] == LINK_SIGA
    assert _siga_processos("codigo") == [("AbCdEf1234",)]
    assert len(_auditoria_siga()) == 1


@pytest.mark.parametrize("link", [
    "https://siga.exemplo.com.br.evil.example/acompanhar?n=AbCdEf1234",
    "https://siga.exemplo.com.br@evil.example/x?n=AbCdEf1234",
    "https://evil.example/sigaex/public/app/processoautenticar?n=AbCdEf1234",
    "https://siga.exemplo.com.br/acompanhar",
    "https://siga.exemplo.com.br/acompanhar?n=curto",
    "https://siga.exemplo.com.br/acompanhar?n=AbCdEf1234&n=Outro12345",
    "https://siga.exemplo.com.br/x?n=" + "A" * 21,
    "ftp://siga.exemplo.com.br/x?n=AbCdEf1234",
    "https://[::1/x?n=AbCdEf1234",
    "não é um link",
])
def test_link_do_siga_de_outro_site_ou_malformado_e_422_e_nada_e_gravado(api, link):
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1", "link_siga": link})
    assert r.status_code == 422 and r.json()["detail"] == MSG_LINK_INVALIDO
    assert _siga_processos("codigo") == [] and _auditoria_siga() == []
    assert cl.get(f"/api/protocolos/{pid}").json()["numero_orgao"] is None      # nem o numero do mesmo envio


def test_sem_o_modelo_de_link_so_o_codigo_vale_e_nao_ha_link_no_detalhe(api, monkeypatch):
    monkeypatch.delenv("DASH_SIGA_LINK_MODELO")
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1", "link_siga": LINK_SIGA})
    assert r.status_code == 422 and r.json()["detail"] == MSG_LINK_INVALIDO       # sem o modelo nao ha' dominio a conferir
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1", "link_siga": "AbCdEf1234"})
    assert r.status_code == 200, r.text
    assert (r.json()["siga"]["codigo"], r.json()["siga"]["link"]) == ("AbCdEf1234", None)


def test_link_do_siga_vazio_nao_apaga_o_que_esta_gravado(api):
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1", "link_siga": LINK_SIGA})
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-2", "link_siga": ""})
    assert r.status_code == 200 and r.json()["siga"]["codigo"] == "AbCdEf1234"
    assert _siga_processos("codigo", "protocolo_id") == [("AbCdEf1234", pid)]


def test_so_o_link_sem_numero_grava_o_link_e_nao_mexe_no_numero(api):
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "", "link_siga": LINK_SIGA})
    assert r.status_code == 200, r.text
    assert r.json()["numero_orgao"] is None and r.json()["siga"]["codigo"] == "AbCdEf1234"
    assert _siga_processos("codigo", "numero", "protocolo_id") == [("AbCdEf1234", None, pid)]
    # sem numero, sem link e sem comprovante continua recusado
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "", "link_siga": ""})
    assert r.status_code == 422 and r.json()["detail"] == protocolo.NUMERO_ORGAO_VAZIO


def test_outro_link_no_mesmo_protocolo_e_recusado_e_o_primeiro_fica(api):
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1", "link_siga": LINK_SIGA})
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1", "link_siga": "ZzYyXx9988"})
    assert r.status_code == 422 and r.json()["detail"] == "Este protocolo já tem outro link do SIGA gravado"
    assert _siga_processos("codigo") == [("AbCdEf1234",)]


def test_codigo_ja_ligado_a_outro_protocolo_e_recusado(api):
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    c = db.get_conn()
    uid = c.execute("SELECT id FROM usuarios LIMIT 1").fetchone()[0]
    outro = c.execute("INSERT INTO protocolos (contrato_id, etapa, natureza, usuario_id, situacao) "
                      "VALUES (?, 'unico', 'execucao', ?, 'enviado')", (cid, uid)).lastrowid
    c.execute("INSERT INTO siga_processos (codigo, numero, contrato_id, protocolo_id) VALUES ('AbCdEf1234', 'Y-9', ?, ?)",
              (cid, outro))
    c.commit(); c.close()
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1", "link_siga": LINK_SIGA})
    assert r.status_code == 422 and r.json()["detail"] == "Este processo do SIGA já está ligado a outro protocolo"
    assert _siga_processos("protocolo_id") == [(outro,)]


def test_processo_que_o_robo_ligou_pelo_numero_ganha_o_codigo_do_link(api):
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "MTPAR-PRO-2026/00123"})
    c = db.get_conn()
    c.execute("INSERT INTO siga_processos (numero, contrato_id, protocolo_id, medicao_id) VALUES "
              "('MTPAR-PRO-2026/00123', ?, ?, ?)", (cid, pid, mid))
    c.commit(); c.close()
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "MTPAR-PRO-2026/00123", "link_siga": LINK_SIGA})
    assert r.status_code == 200, r.text
    assert _siga_processos("codigo", "numero", "protocolo_id") == [("AbCdEf1234", "MTPAR-PRO-2026/00123", pid)]


def test_processo_ja_ligado_pelo_robo_com_o_mesmo_codigo_ainda_registra_quem_colou_o_link(api):
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    c = db.get_conn()
    c.execute("INSERT INTO siga_processos (codigo, numero, contrato_id, protocolo_id, medicao_id) VALUES "
              "('AbCdEf1234', 'X-1', ?, ?, ?)", (cid, pid, mid))
    c.commit(); c.close()
    for _ in range(2):
        r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1", "link_siga": LINK_SIGA})
        assert r.status_code == 200, r.text
    assert r.json()["siga"]["registrado_em"]            # a linha do tempo ganha o evento
    assert len(_auditoria_siga()) == 1 and len(_siga_processos("id")) == 1


def test_processo_que_o_robo_ligou_so_a_medicao_do_protocolo_passa_a_ser_dele(api):
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    c = db.get_conn()
    c.execute("INSERT INTO siga_processos (codigo, numero, contrato_id, medicao_id) VALUES ('AbCdEf1234', 'X-1', ?, ?)",
              (cid, mid))
    c.commit(); c.close()
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1", "link_siga": LINK_SIGA})
    assert r.status_code == 200, r.text
    assert _siga_processos("codigo", "protocolo_id", "medicao_id") == [("AbCdEf1234", pid, mid)]


def test_detalhe_traz_setor_com_quem_e_dias_uteis_depois_da_leitura_do_robo(api, tmp_path, monkeypatch):
    from app import tempo
    # quarta-feira, 28/10/2026, 12h em Cuiaba
    monkeypatch.setattr(tempo, "agora_utc", lambda: datetime.datetime(2026, 10, 28, 16, 0, tzinfo=datetime.timezone.utc))
    token = tmp_path / "siga-token.txt"
    token.write_text("token-de-teste-do-siga-0123456789", encoding="utf-8")
    monkeypatch.setenv("DASH_SIGA_TOKEN_ARQUIVO", str(token))
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1", "link_siga": LINK_SIGA})
    leitura = {"lido_em": "2026-10-28T11:00:00-04:00", "processos": [{
        "codigo": "AbCdEf1234", "numero": "X-1", "nome": "Processo Alfa",
        "situacao": "2º Volume - Aguardando Andamento [COFIN, [X]]",
        "movimentacoes": [{"data": "20/10/2026 10:00:00", "evento": "Recebimento", "cad_lotacao": "PROTOC/ORGAO",
                           "cad_pessoa": "Beltrano", "at_lotacao": "COFIN/ORGAO", "at_pessoa": "Fulano"}]}]}
    robo = {"Authorization": "Bearer token-de-teste-do-siga-0123456789"}
    r = cl.post("/api/siga/leituras", json=leitura, headers=robo)
    assert r.status_code == 200, r.text
    siga = cl.get(f"/api/protocolos/{pid}").json()["siga"]
    assert (siga["setor"], siga["com_quem"], siga["dias_uteis"]) == ("COFIN", "Fulano", 6)     # 20, 21, 22, 23, 26, 27
    assert siga["lido_em"] == "2026-10-28T15:00:00+00:00"


def test_diretoria_ve_o_siga_no_detalhe_mas_nao_grava(api):
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1", "link_siga": LINK_SIGA})
    c = db.get_conn()
    auth.criar_usuario(c, "Dir", "dir@l.com", "senha-forte-123", "diretoria")
    c.close()
    cl.cookies.clear()
    r = cl.post("/api/auth/login", json={"email": "dir@l.com", "senha": "senha-forte-123"})
    cl.cookies.set("sessao", r.cookies.get("sessao") or cl.cookies.get("sessao"))
    cl.headers["X-CSRF-Token"] = r.json()["csrf"]
    assert cl.get(f"/api/protocolos/{pid}").json()["siga"]["link"] == LINK_SIGA
    assert cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1", "link_siga": LINK_SIGA}).status_code == 403


def _fora(cl, mid, **extra):
    return cl.post(f"/api/medicoes/{mid}/protocolo", json={
        "data": "2026-10-20", "numero_processo": "MTPAR-PRO-2026/00123", "apesar_das_pendencias": True,
        "justificativa": "documentos em dia fora do sistema", **extra})


def test_protocolo_feito_fora_com_link_do_siga_liga_o_processo_a_medicao(api):
    cl, cid, mid = api
    r = _fora(cl, mid, link_siga=LINK_SIGA)
    assert r.status_code == 201, r.text
    assert _siga_processos("codigo", "numero", "nome", "contrato_id", "protocolo_id", "medicao_id") == [
        ("AbCdEf1234", "MTPAR-PRO-2026/00123", "23ª Medição - Obra MTPAR", cid, None, mid)]
    a = _auditoria_siga()
    assert [(x["entidade"], x["entidade_id"]) for x in a] == [("medicao", str(mid))]
    assert cl.get(f"/api/medicoes/{mid}").json()["siga_registrado_em"]
    assert cl.get(f"/api/contratos/{cid}/medicoes").json()[0]["siga_registrado_em"]


def test_protocolo_feito_fora_sem_link_nao_cria_processo_e_link_invalido_nao_protocola(api):
    cl, cid, mid = api
    r = _fora(cl, mid, link_siga="https://evil.example/x?n=AbCdEf1234")
    assert r.status_code == 422 and r.json()["detail"] == MSG_LINK_INVALIDO
    assert cl.get(f"/api/medicoes/{mid}").json()["estado"] == "nota_emitida" and _siga_processos("codigo") == []
    assert _fora(cl, mid).status_code == 201
    assert _siga_processos("codigo") == [] and cl.get(f"/api/medicoes/{mid}").json()["siga_registrado_em"] is None
