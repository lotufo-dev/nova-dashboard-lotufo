"""Envio dos documentos assinados ao orgao (issue #627; SINFRA): previa, envio unico e registrado, reenvio com motivo,
envio por fora e o evento de assinatura com o PDF."""
import json
import threading

import pytest

from app import auth, cadastro_aplicar, correio, db, tempo
from tests.conftest import _pdf_com_texto
from tests.test_api_medicoes import _entrar, _registrar_boletim
from tests.test_api_planilha_envio import _cadastro, _corpo, _linha, _por_fora, _pronta
from tests.test_envio_reserva import CorreioFalso

ENVELOPE = "1A2B3C4D-1111-2222-3333-444455556666"
MB = 1024 * 1024


@pytest.fixture
def api(client_admin, tmp_path, monkeypatch):
    """A SINFRA com o limite de 25 MB por documento, como no cadastro de exemplo."""
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    cad = _cadastro()
    cad["orgaos"][0]["regras"]["limite_mb_por_documento"] = 25
    c = db.get_conn()
    cadastro_aplicar.aplicar(c, 1, cad)
    ids = {r["nome_curto"]: r["id"] for r in c.execute("SELECT id, nome_curto FROM contratos")}
    c.commit(); c.close()
    return client_admin, ids["Obra SINFRA"], ids["Obra MTPAR"]


def _pdf(texto: str, nome="assinado.pdf"):
    return (nome, _pdf_com_texto(texto), "application/pdf")


def _arquivos(reajuste=False, justificativa=False, medicao=None):
    out = {"arquivo": medicao or _pdf(f"Docusign Envelope ID: {ENVELOPE} 1a medicao", "Medicao assinada.pdf")}
    if reajuste:
        out["arquivo_reajuste"] = _pdf("Docusign Envelope ID: 9F8E7D6C-AAAA-BBBB-CCCC-DDDDEEEEFFFF reajuste",
                                       "Reajuste assinado.pdf")
    if justificativa:
        out["justificativa"] = _pdf("Justificativa de atraso do cronograma", "Justificativa.pdf")
    return out


def _com_boletim(cl, cid, reajuste=False):
    """Execucao (e o reajuste do par) com a planilha/carta enviada pelo sistema e o boletim do orgao registrado."""
    extra = {"reajuste_valor": "500,00"} if reajuste else {}
    mid, pv = _pronta(cl, cid, **extra)
    assert cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv)).status_code == 200
    hoje = tempo.hoje_local().isoformat()
    assert _registrar_boletim(cl, mid, data=hoje).status_code == 201
    rid = None
    if reajuste:
        rid = _linha("SELECT id FROM medicoes WHERE contrato_id=? AND numero=1 AND tipo='reajuste'", cid)["id"]
        assert _registrar_boletim(cl, rid, valor="500,00", data=hoje).status_code == 201
    return mid, rid, pv


def _previa(cl, mid, **kw):
    return cl.post(f"/api/medicoes/{mid}/assinados/previa", files=_arquivos(**kw))


def _enviar(cl, mid, pv, files=None, **extra):
    corpo = {**{k: pv[k] for k in ("para", "copia", "assunto", "corpo")},
             "anexos_previa": [{k: a[k] for k in ("nome", "tamanho", "sha256")} for a in pv["anexos"]], **extra}
    return cl.post(f"/api/medicoes/{mid}/assinados/enviar", data={"dados": json.dumps(corpo)},
                   files=files or _arquivos())


def _assinaturas(mid):
    c = db.get_conn()
    try:
        return [dict(r) for r in c.execute("SELECT * FROM medicao_assinaturas WHERE medicao_id=? ORDER BY id", (mid,))]
    finally:
        c.close()


def _textos(cl, mid):
    return [e for e in cl.get(f"/api/medicoes/{mid}").json()["edicoes_valor"] if "Documentos assinados" in e["texto"]]


# --- disponibilidade -------------------------------------------------------------------------------

def test_so_aparece_na_sinfra_depois_do_boletim(api):
    cl, cid, cid_mtpar = api
    mid, pv = _pronta(cl, cid)
    s = cl.get(f"/api/medicoes/{mid}").json()["envio_assinados"]
    assert s["disponivel"] is False and s["motivo"] == "Registre o boletim do órgão antes da assinatura"
    r = _previa(cl, mid)
    assert r.status_code == 422 and r.json()["detail"] == "Registre o boletim do órgão antes da assinatura"
    assert cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv)).status_code == 200
    assert _registrar_boletim(cl, mid, data=tempo.hoje_local().isoformat()).status_code == 201
    s = cl.get(f"/api/medicoes/{mid}").json()["envio_assinados"]
    assert s["disponivel"] is True and s["limite"] == 25 * MB and s["reajuste"] is None
    # MT-PAR nao tem esse passo
    from tests.test_api_planilha_envio import _planilha
    outra = _planilha(cl, cid_mtpar)
    s = cl.get(f"/api/medicoes/{outra}").json()["envio_assinados"]
    assert s["disponivel"] is False and "SINFRA" in s["motivo"]
    assert _previa(cl, outra).status_code == 422


@pytest.mark.parametrize("familia", ["ses", "prefeitura"])
def test_ses_e_prefeitura_nao_tem_o_ato(api, familia):
    from tests.test_api_planilha_envio import _api_familia, _planilha
    cl, _, _ = api
    mid = _planilha(cl, _api_familia(familia))
    _por_fora(cl, mid, "2026-08-03")
    assert _registrar_boletim(cl, mid).status_code == 201
    s = cl.get(f"/api/medicoes/{mid}").json()["envio_assinados"]
    assert s["disponivel"] is False
    r = cl.post(f"/api/medicoes/{mid}/assinados/envio-externo", data={"enviado_em": "2026-08-12"}, files=_arquivos())
    assert r.status_code == 422 and _assinaturas(mid) == []


def test_cancelada_nao_envia(api):
    cl, cid, _ = api
    mid, _, pv = _com_boletim(cl, cid)
    assert cl.post(f"/api/medicoes/{mid}/estado", json={"estado": "cancelada"}).status_code == 200
    r = _previa(cl, mid)
    assert r.status_code == 422 and "cancelada" in r.json()["detail"]
    assert cl.get(f"/api/medicoes/{mid}").json()["envio_assinados"]["disponivel"] is False


# --- previa ----------------------------------------------------------------------------------------

def test_previa_usa_os_destinatarios_e_o_assunto_da_planilha(api):
    cl, cid, _ = api
    mid, rid, pv_planilha = _com_boletim(cl, cid, reajuste=True)
    r = _previa(cl, mid, reajuste=True, justificativa=True)
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["para"] == pv_planilha["para"] and pv["copia"] == pv_planilha["copia"]
    assert pv["assunto"] == f"RE: {pv_planilha['assunto']}"
    assert pv["corpo"] == "Encaminho, em anexo, os documentos assinados e a justificativa de atraso do cronograma."
    assert [(a["nome"], a["origem"]) for a in pv["anexos"]] == [
        ("Medicao assinada.pdf", "medicao"), ("Reajuste assinado.pdf", "reajuste"), ("Justificativa.pdf", "justificativa")]
    assert pv["reajuste"] == {"id": rid, "numero": 1} and pv["reenvio"] is False
    # sem a justificativa, o corpo nao fala dela
    assert _previa(cl, mid).json()["corpo"] == "Encaminho, em anexo, os documentos assinados."


def test_planilha_por_fora_usa_o_assunto_do_modelo_do_orgao(api):
    from tests.test_api_planilha_envio import _planilha
    cl, cid, _ = api
    mid = _planilha(cl, cid)
    _por_fora(cl, mid, "2026-08-03")
    assert _registrar_boletim(cl, mid).status_code == 201
    pv = _previa(cl, mid).json()
    assert pv["assunto"] == "RE: 1ª Medição (07_2026) - IC 082/2025 - Obra SINFRA"


def test_pdf_acima_do_limite_do_orgao_e_recusado(api):
    cl, cid, _ = api
    mid, _, _ = _com_boletim(cl, cid)
    base = _pdf_com_texto("grande")
    grande = ("grande.pdf", base + b"\0" * (25 * MB + 1 - len(base)), "application/pdf")
    r = cl.post(f"/api/medicoes/{mid}/assinados/previa", files={"arquivo": grande})
    assert r.status_code == 422
    assert r.json()["detail"] == "PDF acima de 25 MB, o limite por documento do órgão: divida o arquivo"


def test_orgao_sem_limite_por_documento_vale_o_teto_do_email(api):
    from app import assinados_envio
    assert assinados_envio.limite({}) == (correio.MAX_TOTAL, "PDF acima de 25 MB, o limite do e-mail: divida o arquivo")
    assert assinados_envio.limite({"limite_mb_por_documento": 10})[0] == 10 * MB


def test_pdf_do_reajuste_sem_par_com_boletim_e_recusado(api):
    cl, cid, _ = api
    mid, _, _ = _com_boletim(cl, cid)
    r = _previa(cl, mid, reajuste=True)
    assert r.status_code == 422 and "reajuste" in r.json()["detail"]


# --- envio -----------------------------------------------------------------------------------------

def test_envio_manda_um_email_e_grava_as_assinaturas_com_o_pdf(api, monkeypatch):
    cl, cid, _ = api
    mid, rid, _ = _com_boletim(cl, cid, reajuste=True)
    pv = _previa(cl, mid, reajuste=True, justificativa=True).json()
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    r = _enviar(cl, mid, pv, files=_arquivos(reajuste=True, justificativa=True))
    assert r.status_code == 200, r.text
    eid = r.json()["envio_id"]
    assert falso.enviados == [pv["assunto"]]
    assert _linha("SELECT tipo FROM envios WHERE id=?", eid) == {"tipo": "assinados"}
    c = db.get_conn()
    ligadas = sorted(x[0] for x in c.execute("SELECT medicao_id FROM envio_medicoes WHERE envio_id=?", (eid,)))
    nomes = [x[0] for x in c.execute("SELECT nome FROM envio_anexos WHERE envio_id=? ORDER BY id", (eid,))]
    c.close()
    assert ligadas == sorted([mid, rid]) and nomes == [a["nome"] for a in pv["anexos"]]
    hoje = tempo.hoje_local().isoformat()
    (a,) = _assinaturas(mid)
    assert (a["assinado_em"], a["envelope"], a["envio_id"], a["envio_origem"]) == (hoje, ENVELOPE, eid, "sistema")
    assert a["arquivo"] and a["sha256"] == pv["anexos"][0]["sha256"]
    (b,) = _assinaturas(rid)
    assert (b["envelope"], b["envio_id"], b["sha256"]) == ("9F8E7D6C-AAAA-BBBB-CCCC-DDDDEEEEFFFF", eid,
                                                           pv["anexos"][1]["sha256"])
    # linha do tempo das duas, com o PDF que abre pelo link
    br = tempo.hoje_local().strftime("%d/%m/%Y")
    for x, ass in ((mid, a), (rid, b)):
        (ev,) = _textos(cl, x)
        assert ev["texto"].startswith(f"Documentos assinados enviados em {br} (PDF) por ")
        pdf = cl.get(f"/api/medicoes/{x}/assinados/{ev['assinatura_id']}")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert cl.get(f"/api/medicoes/{mid}/assinados/{b['id']}").status_code == 404     # o de outra medicao nao
    s = r.json()
    assert [e["envio_id"] for e in s["envios"]] == [eid] and s["envios"][0]["vigente"] is True


def test_reajuste_so_ganha_evento_quando_o_pdf_dele_foi(api, monkeypatch):
    cl, cid, _ = api
    mid, rid, _ = _com_boletim(cl, cid, reajuste=True)
    pv = _previa(cl, mid).json()
    monkeypatch.setattr(correio, "cliente", CorreioFalso())
    r = _enviar(cl, mid, pv)
    assert r.status_code == 200, r.text
    assert len(_assinaturas(mid)) == 1 and _assinaturas(rid) == []
    c = db.get_conn()
    ligadas = [x[0] for x in c.execute("SELECT medicao_id FROM envio_medicoes WHERE envio_id=?", (r.json()["envio_id"],))]
    c.close()
    assert ligadas == [mid]


def test_dois_envios_simultaneos_mandam_um_email_so(api, monkeypatch):
    """1x200 e 1x409: o segundo POST chega com o e-mail do primeiro ainda saindo."""
    cl, cid, _ = api
    mid, _, _ = _com_boletim(cl, cid)
    pv = _previa(cl, mid).json()
    respostas = []

    def segundo_clique():
        t = threading.Thread(target=lambda: respostas.append(_enviar(cl, mid, pv)))
        t.start(); t.join()

    falso = CorreioFalso(no_meio=segundo_clique)
    monkeypatch.setattr(correio, "cliente", falso)
    r = _enviar(cl, mid, pv)
    assert r.status_code == 200, r.text
    assert [x.status_code for x in respostas] == [409]
    assert respostas[0].json()["detail"]["codigo"] == "ENVIO_RESERVADO"
    assert len(falso.enviados) == 1 and len(_assinaturas(mid)) == 1
    assert _linha("SELECT COUNT(*) AS n FROM envios WHERE tipo='assinados'")["n"] == 1


def test_reenvio_exige_motivo_e_os_dois_ficam_na_linha_do_tempo(api, monkeypatch):
    cl, cid, _ = api
    mid, _, _ = _com_boletim(cl, cid)
    monkeypatch.setattr(correio, "cliente", CorreioFalso())
    pv = _previa(cl, mid).json()
    assert _enviar(cl, mid, pv).status_code == 200
    pv2 = _previa(cl, mid, justificativa=True).json()
    assert pv2["reenvio"] is True
    sem = _enviar(cl, mid, pv2, files=_arquivos(justificativa=True))
    assert sem.status_code == 422 and "motivo do reenvio" in sem.json()["detail"]
    r = _enviar(cl, mid, pv2, files=_arquivos(justificativa=True), motivo="faltou a justificativa de atraso")
    assert r.status_code == 200, r.text
    envios = r.json()["envios"]
    assert [e["vigente"] for e in envios] == [False, True]
    assert envios[1]["motivo"] == "faltou a justificativa de atraso"
    textos = [e["texto"] for e in _textos(cl, mid)]
    assert len(textos) == 2 and textos[0].startswith("Documentos assinados enviados em ")
    assert textos[1].startswith("Documentos assinados reenviados em ") and "faltou a justificativa" in textos[1]


def test_envio_sem_a_conferencia_da_previa_e_recusado(api, monkeypatch):
    cl, cid, _ = api
    mid, _, _ = _com_boletim(cl, cid)
    pv = _previa(cl, mid).json()
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    outro = _arquivos(medicao=_pdf("outro conteudo", "Medicao assinada.pdf"))
    r = _enviar(cl, mid, pv, files=outro)
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "ANEXOS_MUDARAM"
    assert falso.enviados == [] and _assinaturas(mid) == []


def test_falha_no_email_destrava_e_nao_grava_assinatura(api, monkeypatch):
    from app import graph
    cl, cid, _ = api
    mid, _, _ = _com_boletim(cl, cid)
    pv = _previa(cl, mid).json()
    monkeypatch.setattr(correio, "cliente", CorreioFalso(falha=graph.ErroGraph("caiu")))
    assert _enviar(cl, mid, pv).status_code == 422
    assert _assinaturas(mid) == []
    assert _linha("SELECT envio_reservado_em FROM medicao_assinados_envios WHERE medicao_id=?", mid) == \
        {"envio_reservado_em": None}
    monkeypatch.setattr(correio, "cliente", CorreioFalso())
    assert _enviar(cl, mid, pv).status_code == 200      # sem motivo: o que falhou nao conta como enviado


def test_data_da_assinatura_anterior_ao_boletim_da_422(api, monkeypatch):
    cl, cid, _ = api
    mid, _, _ = _com_boletim(cl, cid)
    pv = _previa(cl, mid).json()
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    r = _enviar(cl, mid, pv, assinado_em="2026-01-02")
    assert r.status_code == 422 and "anterior à do boletim" in r.json()["detail"]
    assert falso.enviados == []


# --- por fora --------------------------------------------------------------------------------------

def test_envio_por_fora_grava_a_assinatura_sem_email(api, monkeypatch):
    cl, cid, _ = api
    mid, _, _ = _com_boletim(cl, cid)
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    hoje = tempo.hoje_local().isoformat()
    r = cl.post(f"/api/medicoes/{mid}/assinados/envio-externo", data={"enviado_em": hoje}, files=_arquivos())
    assert r.status_code == 201, r.text
    assert falso.enviados == []
    (a,) = _assinaturas(mid)
    assert (a["assinado_em"], a["envelope"], a["envio_id"], a["envio_origem"]) == (hoje, ENVELOPE, None, "externo")
    (ev,) = _textos(cl, mid)
    assert ev["texto"].startswith(f"Documentos assinados enviados em {tempo.hoje_local():%d/%m/%Y} (PDF), "
                                  "registrado por fora por ")
    assert r.json()["envios"][0]["origem"] == "externo"


def test_envio_por_fora_anterior_ao_boletim_ou_futuro_da_422(api):
    import datetime
    cl, cid, _ = api
    mid, _, _ = _com_boletim(cl, cid)
    for data in ("2026-01-02", (tempo.hoje_local() + datetime.timedelta(days=2)).isoformat()):
        r = cl.post(f"/api/medicoes/{mid}/assinados/envio-externo", data={"enviado_em": data}, files=_arquivos())
        assert r.status_code == 422
    assert _assinaturas(mid) == []


def test_por_fora_exige_o_pdf_da_medicao(api):
    cl, cid, _ = api
    mid, _, _ = _com_boletim(cl, cid)
    r = cl.post(f"/api/medicoes/{mid}/assinados/envio-externo", data={"enviado_em": tempo.hoje_local().isoformat()},
                files={"justificativa": _pdf("Justificativa")})
    assert r.status_code == 422 and r.json()["detail"] == "Anexe o PDF assinado da medição"


# --- registrar assinatura com o PDF e permissao ------------------------------------------------------

def test_registrar_assinatura_com_pdf_le_o_envelope(api):
    cl, cid, _ = api
    mid, _, _ = _com_boletim(cl, cid)
    hoje = tempo.hoje_local().isoformat()
    r = cl.post(f"/api/medicoes/{mid}/assinatura-com-pdf", data={"data": hoje}, files=_arquivos())
    assert r.status_code == 201, r.text
    (a,) = _assinaturas(mid)
    assert (a["envelope"], a["envio_origem"]) == (ENVELOPE, None) and a["arquivo"]
    ev = [e for e in cl.get(f"/api/medicoes/{mid}").json()["edicoes_valor"] if "DocuSign" in e["texto"]]
    assert ev[0]["texto"].endswith(f"(envelope {ENVELOPE}) (PDF) por Admin") and ev[0]["assinatura_id"] == a["id"]
    # so' a data continua como antes
    assert cl.post(f"/api/medicoes/{mid}/assinatura", json={"data": hoje}).status_code == 201


def test_diretoria_recebe_403_nos_dois_atos(api):
    cl, cid, _ = api
    mid, _, _ = _com_boletim(cl, cid)
    pv = _previa(cl, mid).json()
    c = db.get_conn()
    auth.criar_usuario(c, "Dir", "dir@lotufo.com", "senha-forte-123", "diretoria")
    c.close()
    _entrar(cl, "dir@lotufo.com")
    assert _previa(cl, mid).status_code == 403
    assert _enviar(cl, mid, pv).status_code == 403
    r = cl.post(f"/api/medicoes/{mid}/assinados/envio-externo", data={"enviado_em": tempo.hoje_local().isoformat()},
                files=_arquivos())
    assert r.status_code == 403
    assert _assinaturas(mid) == []
