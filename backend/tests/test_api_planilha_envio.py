"""Envio da planilha/carta ao protocolo do orgao e congelamento do pedido (issue #282; spec 2026-10-20 §2.1)."""
import io
import json
import threading
import zipfile

import pytest

from app import (cadastro_aplicar, contratos, correio, db, envio_reserva, medicao_planilhas, planilha_envio, protocolo,
                 tempo)
from tests.test_api_medicoes import XLSX, _arquivos_planilha
from tests.test_envio_reserva import CorreioFalso
from tests.test_protocolo import CARTAS, _contrato

PECAS = [{"tipo": "boletim", "rotulo": "Memória de cálculo da medição", "exigida": True, "naturezas": ["execucao"]},
         {"tipo": "fotos", "rotulo": "Registro fotográfico", "naturezas": ["execucao"]},
         {"tipo": "outro", "rotulo": "Planilha de reajuste", "exigida": True, "naturezas": ["reajuste"]},
         {"tipo": "planilha", "rotulo": "Planilha editável", "exigida": True, "solto": True}]


def _cadastro(pecas=PECAS, **contrato_sinfra) -> dict:
    return {
        "orgaos": [{"chave": "sinfra", "nome": "SINFRA - SUEF II", "familia": "sinfra", "cnpj": None,
                    "regras": {"protocolo_para": ["protocolo@orgao-a.exemplo.com.br"],
                               "protocolo_copia": ["engenharia@lotufo.com"], "pecas": pecas,
                               "documentos_medicao": [], "documentos_reajuste": []}},
                   {"chave": "mtpar", "nome": "MTPAR", "familia": "mtpar", "cnpj": None,
                    "regras": {"protocolo_para": ["protocolo@orgao-b.exemplo.com.br"], "documentos_medicao": [],
                               "documentos_reajuste": []}}],
        "entidades": [{"chave": "lotufo", "nome": "Construtora Exemplo Ltda", "cnpj": "31200101000130",
                       "papel": "lotufo", "coligada_rm": 1, "sigla_oficio": "LT", "nome_curto": "Exemplo"}],
        "contratos": [{**_contrato("Obra SINFRA", "sinfra", "IC 082/2025"), **contrato_sinfra},
                      _contrato("Obra MTPAR", "mtpar", "099/2024")],
        "avisos": [], "geral": {"cartas": CARTAS}}


@pytest.fixture
def api(client_admin, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    c = db.get_conn()
    cadastro_aplicar.aplicar(c, 1, _cadastro())
    ids = {r["nome_curto"]: r["id"] for r in c.execute("SELECT id, nome_curto FROM contratos")}
    c.commit(); c.close()
    return client_admin, ids["Obra SINFRA"], ids["Obra MTPAR"]


def _planilha(cl, cid, numero=1, valor="12.345,67", **extra):
    r = cl.post(f"/api/contratos/{cid}/planilhas", files=_arquivos_planilha(f"oficio {numero}"),
                data={"numero": numero, "competencia": "2026-07", "periodo_inicio": "2026-07-01",
                      "periodo_fim": "2026-07-31", "valor": valor, **extra})
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


def test_linha_do_tempo_conta_a_geracao_e_o_envio_pelo_sistema(api):
    """#568: a planilha/carta gerada e o envio pelo sistema (data, quem e assunto) entram na linha do tempo."""
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid)
    assert cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv)).status_code == 200
    textos = [e["texto"] for e in cl.get(f"/api/medicoes/{mid}").json()["edicoes_valor"]]
    hoje = tempo.hoje_local().strftime("%d/%m/%Y")
    assert any(t.startswith("Planilha/carta gerada por ") for t in textos), textos
    assert any(t.startswith(f"Planilha/carta enviada pelo sistema em {hoje} (assunto: {pv['assunto']}) por ")
               for t in textos), textos


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


def _api_familia(familia: str):
    """Um contrato de outra familia (SES ou prefeitura), com as pecas no cadastro do orgao, como a SINFRA (#463)."""
    cad = _cadastro()
    cad["orgaos"].append({"chave": familia, "nome": familia.upper(), "familia": familia, "cnpj": None,
                          "regras": {"protocolo_para": ["protocolo@orgao-c.exemplo.com.br"], "pecas": PECAS,
                                     "documentos_medicao": [], "documentos_reajuste": []}})
    cad["contratos"].append(_contrato(f"Obra {familia}", familia, "123/2025"))
    c = db.get_conn()
    cadastro_aplicar.aplicar(c, 1, cad)
    cid = c.execute("SELECT id FROM contratos WHERE nome_curto=?", (f"Obra {familia}",)).fetchone()["id"]
    c.commit(); c.close()
    return cid


@pytest.mark.parametrize("familia, motivo", [
    ("ses", "Na SES-MT não há envio da planilha/carta: a medição vai com a nota"),
    ("prefeitura", "Nas prefeituras não há envio da planilha/carta: a medição vai ao fiscal da obra")])
def test_ses_e_prefeitura_nao_oferecem_o_envio_da_planilha(api, monkeypatch, familia, motivo):
    cl, cid_sinfra, _ = api
    mid = _planilha(cl, _api_familia(familia))
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    situacao = cl.get(f"/api/medicoes/{mid}").json()["envio_planilha"]
    assert situacao["disponivel"] is False and situacao["motivo"] == motivo
    assert situacao["pecas_do_orgao"] == []          # sem envio, sem pecas a anexar (o painel nao aparece)
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha/previa", json={"numero_oficio": "337"})
    assert r.status_code == 422 and r.json()["detail"] == motivo
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json={
        "numero_oficio": "337", "para": ["protocolo@orgao-c.exemplo.com.br"], "copia": [], "assunto": "x",
        "corpo": "x", "anexos_previa": []})
    assert r.status_code == 422 and r.json()["detail"] == motivo and falso.enviados == []
    r = _peca(cl, mid)
    assert r.status_code == 422 and r.json()["detail"] == motivo
    assert _linha("SELECT estado FROM medicoes WHERE id=?", mid) == {"estado": "planilha_gerada"}
    # a SINFRA continua com o envio, e a MT-PAR com a mensagem dela
    assert cl.get(f"/api/medicoes/{_planilha(cl, cid_sinfra)}").json()["envio_planilha"]["disponivel"] is True
    assert planilha_envio.SEM_ENVIO["mtpar"] == "Na MT-PAR não há envio da planilha/carta: o ofício vai com a nota"


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


def _por_fora(cl, mid, enviado_em):
    r = cl.post(f"/api/medicoes/{mid}/planilhas/envio-externo", data={"enviado_em": enviado_em, "meio": "Balcão"})
    assert r.status_code == 201, r.text


def test_revisao_enviada_por_fora_nao_sai_de_novo_pelo_sistema(api):
    """Gate Sol (PR #382): Original e Rev01 enviadas por fora; a vigente (2) ja' foi enviada, entao o sistema nao
    oferece o envio nem abre a previa, e a lista de envios traz os dois, com a origem."""
    cl, cid, _ = api
    mid = _planilha(cl, cid)
    _por_fora(cl, mid, "2026-08-03")
    _revisar(cl, mid, "12.000,01")
    _por_fora(cl, mid, "2026-08-05")
    s = cl.get(f"/api/medicoes/{mid}").json()["envio_planilha"]
    assert s["disponivel"] is False and "versão 2" in s["motivo"]
    assert [(e["versao"], e["origem"], e["enviado_em"]) for e in s["envios"]] == [
        (1, "externo", "2026-08-03"), (2, "externo", "2026-08-05")]
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha/previa", json={"numero_oficio": "337"})
    assert r.status_code == 422 and "versão 2" in r.json()["detail"]


# --- issue #590: o pedido do reajuste que nasceu com a planilha/carta congela no envio dela -------------------

def _valor(cl, mid, valor):
    return cl.put(f"/api/medicoes/{mid}/valor", json={"campo": "protocolado", "valor": valor})


def _medicao(cl, mid):
    return cl.get(f"/api/medicoes/{mid}").json()


def test_envio_pelo_sistema_congela_o_pedido_do_reajuste_de_mesmo_numero(api):
    """Issue #590 (spec 2026-10-20 §2.2, como na execucao): o envio da planilha/carta congela o pedido da medicao de
    reajuste de mesmo nº e competencia que nasceu com ela; a revisao da planilha/carta continua aceita e nao
    descongela nenhum dos dois pedidos (§2.1, "Revisão não descongela")."""
    cl, cid, _ = api
    r = cl.post(f"/api/contratos/{cid}/planilhas", files=_arquivos_planilha("oficio 1"),
                data={"numero": 1, "competencia": "2026-07", "periodo_inicio": "2026-07-01",
                      "periodo_fim": "2026-07-31", "valor": "1.000,01", "reajuste_valor": "500,00"})
    assert r.status_code == 201, r.text
    mid, rid = r.json()["medicao_id"], r.json()["reajuste_medicao_id"]
    # antes do envio o pedido do reajuste ainda se corrige a mao
    assert _valor(cl, rid, "600,00").status_code == 200
    assert _peca(cl, mid).status_code == 200
    pv = cl.post(f"/api/medicoes/{mid}/envio-planilha/previa", json={"numero_oficio": "337"}).json()
    assert cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv)).status_code == 200
    d = _medicao(cl, rid)
    assert (d["estado"], d["valor_protocolado_centavos"], d["planilha_enviada_em"], d["planilha_envio_origem"]) == \
        ("prevista", 600_00, tempo.hoje_local().isoformat(), "sistema")
    # congela pelo envio, como a execucao (revisor R3): `congelada` e' do protocolo da nota
    assert _linha("SELECT congelada FROM medicoes WHERE id=?", rid) == {"congelada": 0}
    ev = _linha("SELECT depois FROM audit_log WHERE entidade='medicao' AND entidade_id=? AND acao=?",
                str(rid), medicao_planilhas.REAJUSTE_CONGELADO)
    assert json.loads(ev["depois"])["valor_protocolado_centavos"] == 600_00
    assert json.loads(ev["depois"])["medicao_execucao_id"] == mid
    r = _valor(cl, rid, "700,00")
    assert r.status_code == 422 and "congelou no envio da planilha/carta" in r.json()["detail"]
    _revisar(cl, mid, "1.234,57")
    assert _medicao(cl, rid)["valor_protocolado_centavos"] == 600_00
    assert _valor(cl, rid, "700,00").status_code == 422


def test_envio_por_fora_congela_o_pedido_do_reajuste_e_nao_toca_o_sem_pedido(api):
    """Issue #590: o envio por fora (#283) congela igual; a de reajuste prevista sem pedido e a de outra competencia
    nao sao tocadas pelo envio da planilha/carta do numero delas."""
    from app import medicoes
    cl, cid, _ = api
    c = db.get_conn()
    sem_pedido = medicoes.criar(c, _usuario()["id"], {"contrato_id": cid, "numero": 2, "tipo": "reajuste",
                                                      "competencia": "2026-07"})
    outra = medicoes.criar(c, _usuario()["id"], {"contrato_id": cid, "numero": 3, "tipo": "reajuste",
                                                 "competencia": "2026-06", "valor_centavos": 10_00})
    c.close()
    mid = _planilha(cl, cid, reajuste_valor="500,00")
    rid = _linha("SELECT id FROM medicoes WHERE contrato_id=? AND numero=1 AND tipo='reajuste'", cid)["id"]
    _por_fora(cl, mid, "2026-08-03")
    d = _medicao(cl, rid)
    assert (d["valor_protocolado_centavos"], d["planilha_enviada_em"], d["planilha_envio_origem"]) == \
        (500_00, "2026-08-03", "externo")
    assert _valor(cl, rid, "700,00").status_code == 422
    for numero in (2, 3):
        _por_fora(cl, _planilha(cl, cid, numero=numero), "2026-08-03")
    for x in (sem_pedido, outra):
        assert _medicao(cl, x)["planilha_enviada_em"] is None
        assert _valor(cl, x, "1,00").status_code == 200


# --- issue #462: peca que vai no oficio assinado ---------------------------------------------------

# a memoria (exigida) vai dentro do PDF assinado do oficio, como nas cartas da SINFRA ("conforme abaixo elencado")
PECAS_NO_OFICIO = [{**PECAS[0], "no_oficio": True}, *PECAS[1:]]


def _reaplicar(**kw):
    c = db.get_conn()
    try:
        cadastro_aplicar.aplicar(c, 1, _cadastro(**kw))
        c.commit()
    finally:
        c.close()


def _no_oficio(cl, mid) -> dict:
    s = cl.get(f"/api/medicoes/{mid}").json()["envio_planilha"]
    return {p["tipo"]: p["no_oficio"] for p in s["pecas_do_orgao"]}


def _pendencias(cl, mid) -> tuple[dict, list[str]]:
    pv = cl.post(f"/api/medicoes/{mid}/envio-planilha/previa", json={"numero_oficio": "337"})
    assert pv.status_code == 200, pv.text
    return pv.json(), [p["mensagem"] for p in pv.json()["pendencias"]]


def test_peca_no_oficio_exigida_nao_e_pendencia_e_o_envio_sai_sem_justificativa(api):
    cl, cid, _ = api
    _reaplicar(pecas=PECAS_NO_OFICIO)
    mid = _planilha(cl, cid)
    assert _no_oficio(cl, mid) == {"boletim": True, "fotos": False}
    pv, pend = _pendencias(cl, mid)
    assert pend == []
    # a lista de anexos continua dizendo so' o que vai: o oficio e a planilha
    assert [a["origem"] for a in pv["anexos"]] == ["oficio", "planilha"]
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv))
    assert r.status_code == 200, r.text
    assert _linha("SELECT justificativa FROM medicao_planilha_envios WHERE medicao_id=?", mid) == {"justificativa": None}


def test_peca_no_oficio_nao_aceita_anexo_e_a_sem_marca_continua_anexavel(api):
    cl, cid, _ = api
    _reaplicar(pecas=PECAS_NO_OFICIO)
    mid = _planilha(cl, cid)
    r = _peca(cl, mid, "boletim")
    assert r.status_code == 422 and r.json()["detail"] == "Esta peça vai no ofício assinado"
    assert _linha("SELECT COUNT(*) AS n FROM medicao_planilha_pecas WHERE medicao_id=?", mid) == {"n": 0}
    assert _peca(cl, mid, "fotos").status_code == 200


def test_peca_anexada_antes_da_marca_nao_vai_no_email(api):
    """Gate Sol (PR #473): o oficio assinado ja' leva a peca; o anexo antigo nao vai de novo nem pesa no total."""
    cl, cid, _ = api
    mid = _planilha(cl, cid)
    assert _peca(cl, mid, "boletim").status_code == 200
    assert _peca(cl, mid, "fotos").status_code == 200
    _reaplicar(pecas=PECAS_NO_OFICIO)
    pv, pend = _pendencias(cl, mid)
    assert pend == []
    assert [(a["nome"], a["origem"]) for a in pv["anexos"]][2:] == [("fotos.pdf", "pecas")]
    assert pv["total"] == sum(a["tamanho"] for a in pv["anexos"])
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv))
    assert r.status_code == 200, r.text
    c = db.get_conn()
    nomes = [x[0] for x in c.execute("SELECT nome FROM envio_anexos WHERE envio_id=? ORDER BY id", (r.json()["envio_id"],))]
    c.close()
    assert "boletim.pdf" not in nomes and "fotos.pdf" in nomes


def test_marca_posta_entre_a_previa_e_o_envio_recusa_pelos_anexos(api):
    """A previa e' refeita no envio (planilha_envio.enviar) e a conferencia dos anexos recusa o que mudou."""
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid)          # boletim anexado, sem a marca
    _reaplicar(pecas=PECAS_NO_OFICIO)
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv))
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "ANEXOS_MUDARAM"


def test_marca_fora_da_sinfra_e_ignorada():
    pecas = {"pecas": [{"tipo": "boletim", "no_oficio": True}]}
    assert protocolo.tipos_no_oficio("sinfra", pecas, {}) == {"boletim"}
    for familia in ("ses", "prefeitura", "mtpar"):
        assert protocolo.tipos_no_oficio(familia, pecas, {"pecas_no_oficio": '["boletim"]'}) == set()


def test_sem_a_marca_a_peca_exigida_continua_cobrando(api):
    cl, cid, _ = api
    mid = _planilha(cl, cid)
    assert _no_oficio(cl, mid) == {"boletim": False, "fotos": False}
    assert _pendencias(cl, mid)[1] == ["Falta a peça que o órgão exige: Memória de cálculo da medição"]


def test_excecao_do_contrato_substitui_as_pecas_no_oficio_do_orgao(api):
    cl, cid, _ = api
    _reaplicar(pecas=PECAS_NO_OFICIO, pecas_no_oficio=["fotos"])
    mid = _planilha(cl, cid)
    # so' o que o contrato diz vai no oficio: a memoria exigida volta a cobrar, como no orgao sem a marca
    assert _no_oficio(cl, mid) == {"boletim": False, "fotos": True}
    assert _pendencias(cl, mid)[1] == ["Falta a peça que o órgão exige: Memória de cálculo da medição"]
    assert _peca(cl, mid, "fotos").json()["detail"] == "Esta peça vai no ofício assinado"
    assert _peca(cl, mid, "boletim").status_code == 200
    # lista vazia desliga todas
    _reaplicar(pecas=PECAS_NO_OFICIO, pecas_no_oficio=[])
    assert _linha("SELECT pecas_no_oficio FROM contratos WHERE id=?", cid) == {"pecas_no_oficio": "[]"}
    assert _no_oficio(cl, mid) == {"boletim": False, "fotos": False}
    # sem a chave no contrato, vale o orgao de novo
    _reaplicar(pecas=PECAS_NO_OFICIO)
    assert _no_oficio(cl, mid) == {"boletim": True, "fotos": False}


def test_pagina_da_obra_sabe_se_a_obra_tem_os_passos_da_planilha(api):
    """Issue #508: a pagina da obra em medicao so' mostra "Planilha e carta" e "Análise do órgão" onde a planilha/carta
    vai ao orgao; na MT-PAR (o oficio vai com a nota) a barra comeca em Espelhos."""
    cl, cid_sinfra, cid_mtpar = api
    _planilha(cl, cid_sinfra)
    _planilha(cl, cid_mtpar)
    assert [m["com_envio_planilha"] for m in cl.get(f"/api/contratos/{cid_sinfra}/medicoes").json()] == [True]
    assert [m["com_envio_planilha"] for m in cl.get(f"/api/contratos/{cid_mtpar}/medicoes").json()] == [False]


def test_orgao_que_vira_ses_entre_a_previa_e_a_reserva_nao_manda_o_email(api, monkeypatch):
    """Gate Sol (#463): a familia e' relida depois da reserva; cadastro aplicado no intervalo recusa e destrava."""
    cl, cid, _ = api
    mid, pv = _pronta(cl, cid)
    falso = CorreioFalso()
    monkeypatch.setattr(correio, "cliente", falso)
    original = envio_reserva.reservar

    def reservar_depois_do_cadastro(conn, *a, **kw):
        conn.execute("UPDATE orgaos SET familia='ses' WHERE id=(SELECT orgao_id FROM contratos WHERE id=?)", (cid,))
        return original(conn, *a, **kw)
    monkeypatch.setattr(envio_reserva, "reservar", reservar_depois_do_cadastro)
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv))
    assert r.status_code == 422 and r.json()["detail"] == planilha_envio.SEM_ENVIO["ses"]
    assert falso.enviados == []
    assert _linha("SELECT estado FROM medicoes WHERE id=?", mid) == {"estado": "planilha_gerada"}
    assert _linha(f"SELECT COUNT(*) n FROM {planilha_envio.TABELA} WHERE medicao_id=? "
                  "AND envio_reservado_em IS NOT NULL", mid) == {"n": 0}


# --- respostas do orgao lidas da conversa do envio (issue #644) ----------------------------------------------

def _enviada(cl, cid, **kw):
    mid, pv = _pronta(cl, cid, **kw)
    r = cl.post(f"/api/medicoes/{mid}/envio-planilha", json=_corpo(pv))
    assert r.status_code == 200, r.text
    eid = r.json()["envio_id"]
    return mid, eid, _linha("SELECT conversa_id FROM envios WHERE id=?", eid)["conversa_id"]


def _resposta_simulada(tmp_path, conversa, nome="001", **campos):
    pasta = tmp_path / "sim" / "respostas" / conversa
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / f"{nome}.json").write_text(json.dumps({
        "de": "fiscal@orgao-a.exemplo.com.br", "nome": "Fiscal do contrato", "recebida_em": "2026-11-10T14:00:00Z",
        "assunto": "RES: medição", "texto": "Recebido. Segue em análise.", "anexos": [], **campos}), encoding="utf-8")


def test_envio_pelo_simulador_grava_a_conversa(api):
    cl, cid, _ = api
    _, _, conversa = _enviada(cl, cid)
    assert conversa.startswith("conversa-")


def test_resposta_simulada_e_registrada_uma_vez_e_aparece_na_medicao(api, tmp_path):
    cl, cid, _ = api
    mid, eid, conversa = _enviada(cl, cid)
    _resposta_simulada(tmp_path, conversa, texto="Recebido.\n\n" + "x" * 600, anexos=["parecer.pdf"])
    _resposta_simulada(tmp_path, conversa, nome="002", de="ADMIN@lotufo.com", texto="minha tréplica")   # de quem enviou
    _resposta_simulada(tmp_path, "outra-conversa", texto="de outra conversa")
    r = cl.post("/api/correio/respostas/ler")
    assert r.status_code == 200, r.text
    assert [(x["medicao_id"], x["remetente"]) for x in r.json()["novas"]] == [(mid, "fiscal@orgao-a.exemplo.com.br")]
    assert cl.post("/api/correio/respostas/ler").json() == {"novas": []}            # de novo: nada duplica
    lista = cl.get(f"/api/medicoes/{mid}/respostas-orgao").json()
    assert len(lista) == 1
    x = lista[0]
    assert (x["remetente"], x["remetente_nome"], x["recebida_em"], x["assunto"], x["anexos"]) == \
        ("fiscal@orgao-a.exemplo.com.br", "Fiscal do contrato", "2026-11-10T14:00:00Z", "RES: medição", ["parecer.pdf"])
    assert len(x["trecho"]) == 500 and x["trecho"].startswith("Recebido. xxx")      # so' o trecho inicial
    assert _linha("SELECT COUNT(*) AS n FROM medicao_respostas_orgao")["n"] == 1    # a outra conversa nao entrou
    assert _linha("SELECT COUNT(*) AS n FROM audit_log WHERE acao='medicao.resposta_orgao' AND entidade_id=?",
                  str(mid))["n"] == 1


def test_respostas_vem_da_mais_nova_para_a_mais_antiga(api, tmp_path):
    cl, cid, _ = api
    mid, _, conversa = _enviada(cl, cid)
    _resposta_simulada(tmp_path, conversa, nome="001", recebida_em="2026-11-10T14:00:00Z", assunto="primeira")
    _resposta_simulada(tmp_path, conversa, nome="002", recebida_em="2026-11-11T09:00:00Z", assunto="segunda")
    assert len(cl.post("/api/correio/respostas/ler").json()["novas"]) == 2
    assert [x["assunto"] for x in cl.get(f"/api/medicoes/{mid}/respostas-orgao").json()] == ["segunda", "primeira"]


def test_graph_fora_do_ar_na_leitura_responde_vazio_e_nao_insiste(api, tmp_path, monkeypatch):
    cl, cid, _ = api
    _enviada(cl, cid)
    _enviada(cl, cid, numero=2)
    tentativas = []

    def sem_rede(self, conversa_id):
        tentativas.append(conversa_id)
        raise correio.graph.ErroGraph("Graph inacessível (TimeoutError)")
    monkeypatch.setattr(correio.CorreioSimulado, "mensagens_da_conversa", sem_rede)
    r = cl.post("/api/correio/respostas/ler")
    assert r.status_code == 200 and r.json() == {"novas": []}
    assert len(tentativas) == 1


def test_medicao_fechada_ou_envio_de_outra_pessoa_nao_e_lido(api, tmp_path):
    from app import auth
    cl, cid, _ = api
    mid, eid, conversa = _enviada(cl, cid)
    _resposta_simulada(tmp_path, conversa)
    c = db.get_conn()
    c.execute("UPDATE medicoes SET estado='cancelada' WHERE id=?", (mid,)); c.commit()
    assert cl.post("/api/correio/respostas/ler").json() == {"novas": []}
    # medicao aberta de novo, mas o envio e' de outra pessoa: quem esta' logado nao le a conversa dela
    outra = auth.criar_usuario(c, "Engenheira da obra", "engenheira@lotufo.com", "senha-forte-123", "engenharia")
    c.execute("UPDATE medicoes SET estado='planilha_enviada' WHERE id=?", (mid,))
    c.execute("UPDATE envios SET usuario_id=? WHERE id=?", (outra, eid))
    c.commit(); c.close()
    assert cl.post("/api/correio/respostas/ler").json() == {"novas": []}
    assert _linha("SELECT COUNT(*) AS n FROM medicao_respostas_orgao")["n"] == 0
