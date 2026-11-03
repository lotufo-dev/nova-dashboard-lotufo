"""Envio da planilha/carta ao protocolo do orgao e congelamento do pedido (issue #282; spec 2026-10-20 §2.1)."""
import io
import json
import threading
import zipfile

import pytest

from app import cadastro_aplicar, contratos, correio, db, envio_reserva, medicao_planilhas, planilha_envio, tempo
from tests.test_api_medicoes import XLSX, _arquivos_planilha
from tests.test_envio_reserva import CorreioFalso
from tests.test_protocolo import CARTAS, _contrato

PECAS = [{"tipo": "boletim", "rotulo": "Memória de cálculo da medição", "exigida": True, "naturezas": ["execucao"]},
         {"tipo": "fotos", "rotulo": "Registro fotográfico", "naturezas": ["execucao"]},
         {"tipo": "outro", "rotulo": "Planilha de reajuste", "exigida": True, "naturezas": ["reajuste"]},
         {"tipo": "planilha", "rotulo": "Planilha editável", "exigida": True, "solto": True}]


@pytest.fixture
def api(client_admin, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    c = db.get_conn()
    cadastro_aplicar.aplicar(c, 1, {
        "orgaos": [{"chave": "sinfra", "nome": "SINFRA - SUEF II", "familia": "sinfra", "cnpj": None,
                    "regras": {"protocolo_para": ["protocolo@orgao-a.exemplo.com.br"],
                               "protocolo_copia": ["engenharia@lotufo.com"], "pecas": PECAS,
                               "documentos_medicao": [], "documentos_reajuste": []}},
                   {"chave": "mtpar", "nome": "MTPAR", "familia": "mtpar", "cnpj": None,
                    "regras": {"protocolo_para": ["protocolo@orgao-b.exemplo.com.br"], "documentos_medicao": [],
                               "documentos_reajuste": []}}],
        "entidades": [{"chave": "lotufo", "nome": "Construtora Exemplo Ltda", "cnpj": "31200101000130",
                       "papel": "lotufo", "coligada_rm": 1, "sigla_oficio": "LT", "nome_curto": "Exemplo"}],
        "contratos": [_contrato("Obra SINFRA", "sinfra", "IC 082/2025"), _contrato("Obra MTPAR", "mtpar", "099/2024")],
        "avisos": [], "geral": {"cartas": CARTAS}})
    ids = {r["nome_curto"]: r["id"] for r in c.execute("SELECT id, nome_curto FROM contratos")}
    c.commit(); c.close()
    return client_admin, ids["Obra SINFRA"], ids["Obra MTPAR"]


def _planilha(cl, cid, numero=1, valor="12.345,67"):
    r = cl.post(f"/api/contratos/{cid}/planilhas", files=_arquivos_planilha(f"oficio {numero}"),
                data={"numero": numero, "competencia": "2026-07", "periodo_inicio": "2026-07-01",
                      "periodo_fim": "2026-07-31", "valor": valor})
    assert r.status_code == 201, r.text
    return r.json()["medicao_id"]


def _revisar(cl, mid, valor, motivo="supervisora devolveu"):
    r = cl.post(f"/api/medicoes/{mid}/planilhas", files=_arquivos_planilha(f"revisao {valor}"),
                data={"periodo_inicio": "2026-07-01", "periodo_fim": "2026-07-31", "valor": valor, "motivo": motivo})
    assert r.status_code == 201, r.text


def _peca(cl, mid, tipo="boletim"):
    return cl.post(f"/api/medicoes/{mid}/envio-planilha/pecas", data={"tipo": tipo},
                   files={"arquivo": (f"{tipo}.pdf", b"%PDF-1.4 " + tipo.encode(), "application/pdf")})


def _corpo(pv: dict, **extra) -> dict:
    return {"numero_oficio": "337", **{k: pv[k] for k in ("para", "copia", "assunto", "corpo")},
            "anexos_previa": [{k: a[k] for k in ("nome", "tamanho", "sha256")} for a in pv["anexos"]], **extra}


def _pronta(cl, cid, **kw):
    mid = _planilha(cl, cid, **kw)
    assert _peca(cl, mid).status_code == 200
    pv = cl.post(f"/api/medicoes/{mid}/envio-planilha/previa", json={"numero_oficio": "337"})
    assert pv.status_code == 200, pv.text
    return mid, pv.json()


def _linha(sql, *args):
    c = db.get_conn()
    try:
        r = c.execute(sql, args).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


def _usuario():
    return {"id": _linha("SELECT id FROM usuarios WHERE email='admin@lotufo.com'")["id"], "email": "admin@lotufo.com"}


def test_previa_monta_o_email_de_protocolo_do_orgao(api):
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid)
    assert pv["assunto"] == "CT-337-LT-2026 - 1ª Medição (07_2026) - IC 082/2025 - Obra SINFRA"
    assert "versões editáveis para a supervisora e a fiscalização" in pv["corpo"]
    assert pv["para"] == ["protocolo@orgao-a.exemplo.com.br", "fiscal@exemplo.gov.br"]
    assert pv["copia"] == ["engenharia@lotufo.com"]
    assert [(a["nome"], a["origem"]) for a in pv["anexos"]] == [
        ("CT-337-LT-2026 - Obra SINFRA - 01ª Medição (07.2026).pdf", "oficio"),
        ("Planilha - Obra SINFRA - 01ª Medição (07.2026).zip", "planilha"),
        ("boletim.pdf", "pecas")]
    assert pv["pendencias"] == [] and pv["versao"] == 1


def test_envio_poe_em_planilha_enviada_com_data_e_origem_e_registra_o_email(api):
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid)
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv))
    assert r.status_code == 200, r.text
    eid = r.json()["envio_id"]
    d = cl.get(f"/api/medicoes/{mid}").json()
    assert (d["estado"], d["planilha_enviada_em"], d["planilha_envio_origem"]) == \
        ("planilha_enviada", tempo.hoje_local().isoformat(), "sistema")
    assert d["envio_planilha"]["disponivel"] is False
    assert [(e["versao"], e["numero_oficio"], e["envio_id"]) for e in d["envio_planilha"]["envios"]] == \
        [(1, "CT-337-LT-2026", eid)]
    envio = _linha("SELECT tipo, assunto, para FROM envios WHERE id=?", eid)
    assert envio["tipo"] == "planilha" and envio["assunto"] == pv["assunto"]
    assert json.loads(envio["para"]) == pv["para"]
    assert _linha("SELECT 1 AS ok FROM envio_medicoes WHERE envio_id=? AND medicao_id=?", eid, mid) == {"ok": 1}
    c = db.get_conn()
    nomes = [r[0] for r in c.execute("SELECT nome FROM envio_anexos WHERE envio_id=? ORDER BY id", (eid,))]
    c.close()
    assert nomes == [a["nome"] for a in pv["anexos"]]
    assert _linha("SELECT envio_reservado_em FROM medicao_planilha_envios WHERE envio_id=?", eid) == \
        {"envio_reservado_em": None}


def test_zip_leva_a_planilha_da_versao(api, monkeypatch):
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid)
    capturados = []

    class Captura(CorreioFalso):
        def enviar(self, para, copia, assunto, corpo_html, anexos, cco=(), inline=()):
            capturados.extend(anexos)
            return super().enviar(para, copia, assunto, corpo_html, anexos, cco, inline)

    monkeypatch.setattr(correio, "cliente", Captura())
    assert cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv)).status_code == 200
    nome, dados = capturados[1]
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        assert z.namelist() == ["Planilha - Obra SINFRA - 01ª Medição (07.2026).xlsx"]
        assert z.read(z.namelist()[0]) == _arquivos_planilha("oficio 1")["planilha"][1]


def test_dois_envios_simultaneos_mandam_um_email_so(api, monkeypatch):
    """1x200 e 1x409: o segundo POST chega com o e-mail do primeiro ainda saindo."""
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid)
    respostas = []

    def segundo_clique():
        t = threading.Thread(target=lambda: respostas.append(
            cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv))))
        t.start(); t.join()

    falso = CorreioFalso(no_meio=segundo_clique)
    monkeypatch.setattr(correio, "cliente", falso)
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv))
    assert r.status_code == 200, r.text
    assert [x.status_code for x in respostas] == [409]
    assert respostas[0].json()["detail"]["codigo"] == "ENVIO_RESERVADO"
    assert len(falso.enviados) == 1
    # o clique depois do envio concluido tambem nao manda outro
    depois = cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv))
    assert depois.status_code == 422 and "já foi enviada" in depois.json()["detail"]
    assert len(falso.enviados) == 1
    assert _linha("SELECT COUNT(*) AS n FROM envios")["n"] == 1


def test_pedido_congela_no_envio_e_so_muda_por_revisao(api):
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid, valor="1.000,01")
    assert cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv)).status_code == 200
    # o envio congela o PEDIDO (pelo estado), nao o valor original do contrato (revisor R3: `congelada` fica 0)
    assert _linha("SELECT congelada, valor_protocolado_centavos FROM medicoes WHERE id=?", mid) == \
        {"congelada": 0, "valor_protocolado_centavos": 1_000_01}
    c = db.get_conn()
    contratos.atualizar(c, _usuario()["id"], cid, {"valor_original_centavos": 200_000_001})
    c.close()
    r = cl.put(f"/api/medicoes/{mid}/valor", json={"campo": "protocolado", "valor": "999,99"})
    assert r.status_code == 422 and "revisão" in r.text
    _revisar(cl, mid, "1.234,57")
    d = cl.get(f"/api/medicoes/{mid}").json()
    assert d["valor_protocolado_centavos"] == 1_000_01
    assert [p["valor_pedido_centavos"] for p in d["planilhas"]] == [1_000_01, 1_234_57]
    # a revisao vai ao orgao como revisao, e o pedido congelado continua o da 1a versao enviada
    assert d["envio_planilha"]["disponivel"] is True
    pv2 = cl.post(f"/api/medicoes/{mid}/envio-planilha/previa", json={"numero_oficio": "340"}).json()
    assert pv2["versao"] == 2 and pv2["assunto"].endswith("Obra SINFRA - Rev01")
    assert pv2["anexos"][0]["nome"] == "CT-340-LT-2026 - Obra SINFRA - 01ª Medição (07.2026) - Rev01.pdf"
    assert cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv2, numero_oficio="340")).status_code == 200
    d = cl.get(f"/api/medicoes/{mid}").json()
    assert d["valor_protocolado_centavos"] == 1_000_01 and d["estado"] == "planilha_enviada"
    assert [e["versao"] for e in d["envio_planilha"]["envios"]] == [1, 2]


def test_revisao_registrada_durante_o_envio_nao_troca_o_pedido_enviado(api, monkeypatch):
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid, valor="500,01")

    def revisao_na_outra_aba():
        outra = db.get_conn()
        try:
            anexos = {"arquivo": None, "sha256": "x", "arquivo_planilha": None, "sha256_planilha": "y"}
            medicao_planilhas.revisar(outra, _usuario()["id"], mid, {"periodo_inicio": "2026-07-01",
                                      "periodo_fim": "2026-07-31", "valor_centavos": 777_77, "motivo": "corrigido"},
                                      anexos)
        finally:
            outra.close()

    monkeypatch.setattr(correio, "cliente", CorreioFalso(no_meio=revisao_na_outra_aba))
    assert cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv)).status_code == 200
    assert _linha("SELECT estado, valor_protocolado_centavos FROM medicoes WHERE id=?", mid) == \
        {"estado": "planilha_enviada", "valor_protocolado_centavos": 500_01}


def test_versao_revista_entre_a_previa_e_a_reserva_nao_sai(api, monkeypatch):
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid)
    _revisar(cl, mid, "13.000,00")
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    c = db.get_conn()
    c.execute("INSERT INTO medicao_planilha_envios (medicao_id, planilha_id) VALUES (?,?)", (mid, pv["planilha_id"]))
    rid = c.execute("SELECT MAX(id) FROM medicao_planilha_envios").fetchone()[0]
    c.commit()
    with pytest.raises(ValueError, match="foi revista"):
        envio_reserva.reservar(c, "medicao_planilha_envios", rid, _usuario()["id"], None)
    c.close()
    assert falso.enviados == []


def test_mtpar_nao_oferece_o_envio_da_planilha(api, monkeypatch):
    cl, _, cid_mtpar = api
    mid = _planilha(cl, cid_mtpar)
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    situacao = cl.get(f"/api/medicoes/{mid}").json()["envio_planilha"]
    assert situacao["disponivel"] is False and "MT-PAR" in situacao["motivo"]
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha/previa", json={"numero_oficio": "337"})
    assert r.status_code == 422 and "MT-PAR" in r.json()["detail"]
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json={
        "numero_oficio": "337", "para": ["protocolo@orgao-b.exemplo.com.br"], "copia": [], "assunto": "x",
        "corpo": "x", "anexos_previa": []})
    assert "MT-PAR" in r.json()["detail"]
    assert r.status_code == 422 and falso.enviados == []
    assert _linha("SELECT estado FROM medicoes WHERE id=?", mid) == {"estado": "planilha_gerada"}


def test_peca_exigida_faltando_e_pendencia_que_pede_justificativa(api):
    cl, cid, _ = api
    mid = _planilha(cl, cid)
    pv = cl.post(f"/api/medicoes/{mid}/envio-planilha/previa", json={"numero_oficio": "337"}).json()
    assert [p["mensagem"] for p in pv["pendencias"]] == \
        ["Falta a peça que o órgão exige: Memória de cálculo da medição"]
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv))
    assert r.status_code == 422 and "justificativa" in r.json()["detail"]
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv, justificativa="memória vai no próximo envio"))
    assert r.status_code == 200, r.text
    assert _linha("SELECT justificativa FROM medicao_planilha_envios WHERE medicao_id=?", mid) == \
        {"justificativa": "memória vai no próximo envio"}


def test_peca_que_o_orgao_nao_pede_e_recusada_e_remover_tira_do_email(api):
    cl, cid, _ = api
    mid = _planilha(cl, cid)
    r = _peca(cl, mid, "croqui")
    assert r.status_code == 422 and "não pede" in r.json()["detail"]
    s = _peca(cl, mid, "fotos").json()
    assert [p["tipo"] for p in s["pecas"]] == ["fotos"]
    s = cl.post(f"/api/medicoes/{mid}/envio-planilha/pecas/{s['pecas'][0]['id']}/remover").json()
    assert s["pecas"] == []
    pv = cl.post(f"/api/medicoes/{mid}/envio-planilha/previa", json={"numero_oficio": "337"}).json()
    assert [a["origem"] for a in pv["anexos"]] == ["oficio", "planilha"]


def test_peca_anexada_depois_da_previa_recusa_o_envio_e_destrava(api, monkeypatch):
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid)
    assert _peca(cl, mid, "fotos").status_code == 200
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv))
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "ANEXOS_MUDARAM"
    assert falso.enviados == []
    assert _linha("SELECT envio_reservado_em FROM medicao_planilha_envios WHERE medicao_id=?", mid) in \
        (None, {"envio_reservado_em": None})


def test_reserva_presa_da_planilha_se_libera_pela_rota_de_envios(api):
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid)
    c = db.get_conn()
    c.execute("INSERT INTO medicao_planilha_envios (medicao_id, planilha_id, envio_reservado_em, envio_reservado_por) "
              "VALUES (?,?,datetime('now','-30 minutes'),?)", (mid, pv["planilha_id"], _usuario()["id"]))
    c.commit(); c.close()
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv))
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "ENVIO_RESERVADO"
    # a tela acha a reserva presa na propria medicao (tabela e id para a liberacao)
    reserva = cl.get(f"/api/medicoes/{mid}").json()["envio_planilha"]["reserva"]
    assert reserva["tabela"] == "medicao_planilha_envios" and reserva["reservado_por"] == "Admin"
    rid = reserva["id"]
    r = cl.post("/api/envios/liberar", json={"tabela": "medicao_planilha_envios", "id": rid,
                                             "justificativa": "conferi os Enviados e não saiu",
                                             "conferi_enviados": True})
    assert r.status_code == 200, r.text
    # a auditoria aponta a medicao (com link na tela), nao a linha da reserva (revisor R2)
    assert _linha("SELECT entidade, entidade_id FROM audit_log WHERE acao='envio.liberar' ORDER BY id DESC LIMIT 1") \
        == {"entidade": "medicao", "entidade_id": str(mid)}
    assert cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv)).status_code == 200


def test_envio_registrado_some_e_nao_se_apaga(api):
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid)
    assert cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv)).status_code == 200
    c = db.get_conn()
    try:
        with pytest.raises(Exception, match="não se apaga"):
            c.execute("DELETE FROM medicao_planilha_envios")
    finally:
        c.close()


def test_planilha_xlsx_nao_vira_peca_do_orgao(api):
    """A `planilha` das pecas do orgao e' a planilha editavel da versao: nao e' pedida de novo como peca."""
    cl, cid, _ = api
    mid = _planilha(cl, cid)
    s = cl.get(f"/api/medicoes/{mid}").json()["envio_planilha"]
    assert [p["tipo"] for p in s["pecas_do_orgao"]] == ["boletim", "fotos"]
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha/pecas", data={"tipo": "planilha"},
                files={"arquivo": ("p.xlsx", b"PK\x03\x04planilha" + b"\x00" * 64, XLSX)})
    assert r.status_code == 422
    assert planilha_envio.TIPO_ENVIO == "planilha"


def test_envio_sem_a_conferencia_da_previa_e_recusado(api, monkeypatch):
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid)
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    corpo = _corpo(pv)
    del corpo["anexos_previa"]
    assert cl.post(f"/api/medicoes/{mid}/envio-planilha", json=corpo).status_code == 422
    assert falso.enviados == []


def test_medicao_ja_enviada_fora_do_sistema_nao_reenvia_a_mesma_versao(api):
    """Carga do historico ou envio por fora: a medicao ja' esta' em planilha_enviada sem envio pelo sistema."""
    cl, cid, _ = api
    mid = _planilha(cl, cid)
    c = db.get_conn()
    c.execute("UPDATE medicoes SET estado='planilha_enviada', planilha_envio_origem='externo', "
              "planilha_enviada_em='2026-08-03' WHERE id=?", (mid,))
    c.commit(); c.close()
    s = cl.get(f"/api/medicoes/{mid}").json()["envio_planilha"]
    assert s["disponivel"] is False and "já foi enviada" in s["motivo"]
    _revisar(cl, mid, "13.000,00")
    assert cl.get(f"/api/medicoes/{mid}").json()["envio_planilha"]["disponivel"] is True


def test_obra_sem_nome_curto_nao_poe_barra_no_nome_do_anexo(api):
    cl, cid, _ = api
    c = db.get_conn()
    c.execute("UPDATE contratos SET nome_curto=NULL WHERE id=?", (cid,))
    c.commit(); c.close()
    mid, pv = _pronta(cl, cid)
    assert [a["nome"] for a in pv["anexos"][:2]] == ["CT-337-LT-2026 - IC 082-2025 - 01ª Medição (07.2026).pdf",
                                                    "Planilha - IC 082-2025 - 01ª Medição (07.2026).zip"]


def test_peca_de_3_mb_passa_pelo_limite_de_upload(api):
    """Revisor R1: a rota de pecas esta' em ROTAS_UPLOAD (sem isso o middleware corta em 2 MB com 413)."""
    cl, cid, _ = api
    mid = _planilha(cl, cid)
    grande = b"%PDF-1.4 " + b"0" * (3 * 1024 * 1024)
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha/pecas", data={"tipo": "fotos"},
                files={"arquivo": ("fotos.pdf", grande, "application/pdf")})
    assert r.status_code == 200, r.text


def test_peca_trocada_por_outra_de_mesmo_nome_e_tamanho_recusa_o_envio(api, monkeypatch):
    """Gate Sol S5: a conferencia da previa e' pelo conteudo (sha256), nao so' pelo nome e tamanho."""
    cl, cid, _ = api
    mid = _planilha(cl, cid)
    s = _peca(cl, mid, "fotos").json()
    pv = cl.post(f"/api/medicoes/{mid}/envio-planilha/previa", json={"numero_oficio": "337"}).json()
    cl.post(f"/api/medicoes/{mid}/envio-planilha/pecas/{s['pecas'][0]['id']}/remover")
    assert cl.post(f"/api/medicoes/{mid}/envio-planilha/pecas", data={"tipo": "fotos"},
                   files={"arquivo": ("fotos.pdf", b"%PDF-1.4 FOTOS", "application/pdf")}).status_code == 200
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv, justificativa="sem memória por enquanto"))
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "ANEXOS_MUDARAM"
    assert falso.enviados == []


def test_pecas_nao_mudam_com_o_envio_reservado(api):
    """Gate Sol S5: com o e-mail saindo (ou preso), anexar ou remover peca da' 409."""
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid)
    peca_id = cl.get(f"/api/medicoes/{mid}").json()["envio_planilha"]["pecas"][0]["id"]
    c = db.get_conn()
    c.execute("INSERT INTO medicao_planilha_envios (medicao_id, planilha_id, envio_reservado_em, envio_reservado_por) "
              "VALUES (?,?,datetime('now'),?)", (mid, pv["planilha_id"], _usuario()["id"]))
    c.commit(); c.close()
    r = _peca(cl, mid, "fotos")
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "ENVIO_RESERVADO"
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha/pecas/{peca_id}/remover")
    assert r.status_code == 409
    assert [p["id"] for p in cl.get(f"/api/medicoes/{mid}").json()["envio_planilha"]["pecas"]] == [peca_id]
