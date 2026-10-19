"""Pagina Notas (plano 2026-10-09): lista a enviar, bloqueio por certidao vencida, envio pelo simulador, envio feito
por fora, aguardando pagamento, regras D1-D9 e a cobranca de certidoes por e-mail."""
import datetime
import io
import json
import zipfile

import pytest

from app import (arquivos, auth, cadastro_aplicar, certidoes, cobranca_certidoes, correio, db, documentos, frc,
                 medicoes, notas_envio, protocolo, tempo)
from tests import test_frc
from tests.test_frc import _texto, consorcio14, conn, usuario  # noqa: F401  (fixtures do consorcio com FRC)
from tests.test_protocolo import CARTAS, CINCO, _contrato, _pdf, _textos

D = datetime.date
HOJE = D(2026, 9, 16)


# Cobranca de certidao (geral.yaml, issue #110): conta do Outlook do Leo e os logins dele, ficticios
COBRANCA = {"para": ["leo.outlook@exemplo.com.br"], "enviada_por": ["leo.outlook@exemplo.com.br", "leo@exemplo.com.br"]}


def _cadastro(c, uid, assinados_para=None):
    sinfra = {"protocolo_para": ["sinfra@orgao-a.exemplo.com.br"], "documentos_medicao": CINCO + ["regularidade"],
              "protocolo_copia": ["josi@l.com", "leo.outlook@exemplo.com.br"], "documentos_reajuste": CINCO}
    if assinados_para:
        sinfra["protocolo_assinados_para"] = assinados_para
    cad = {"orgaos": [
        {"chave": "mtpar", "nome": "MTPAR", "familia": "mtpar", "cnpj": None,
         "regras": {"protocolo_para": ["protocolo@orgao-b.exemplo.com.br"], "protocolo_copia": ["josi@l.com"],
                    "carta_destinatario": ["A MT PARTICIPAÇÕES E PROJETOS S.A – MT-PAR"],
                    "ordem_certidoes": ["municipal", "trabalhista", "estadual", "federal", "fgts"],
                    "documentos_medicao": CINCO, "documentos_reajuste": CINCO}},
        {"chave": "sinfra-suef2", "nome": "SINFRA - SUEF II", "familia": "sinfra", "cnpj": None, "regras": sinfra},
        {"chave": "pref-vg", "nome": "Pref. VG", "familia": "prefeitura", "cnpj": None,
         "regras": {"protocolo_para": ["saude@vg.com"], "documentos_medicao": CINCO, "documentos_reajuste": CINCO}}],
        "entidades": [{"chave": "lotufo", "nome": "Lotufo Engenharia e Construções Ltda", "cnpj": "31200101000130",
                       "papel": "lotufo", "coligada_rm": 1, "sigla_oficio": "LT", "nome_curto": "Lotufo"}],
        "contratos": [_contrato("Obra MTPAR", "mtpar", "099/2024/MTPAR"), _contrato("Obra SINFRA", "sinfra-suef2", "IC 1/2026"),
                      _contrato("Obra VG", "pref-vg", "118/2025")],
        "avisos": [], "geral": {"cartas": CARTAS, "cobranca_certidoes": COBRANCA}}
    cad["contratos"][1]["destinatarios_extras"] = ["supervisora@x.com"]
    cadastro_aplicar.aplicar(c, uid, cad)
    ids = {nome: c.execute("SELECT id FROM contratos WHERE nome_curto=?", (f"Obra {nome.upper() if nome != 'vg' else 'VG'}",)
                           ).fetchone()[0] for nome in ("mtpar", "sinfra", "vg")}
    for chave in CINCO:
        rel, sha = arquivos.gravar_bytes("certidoes", _pdf(f"CERTIDAO {chave.upper()}"), "pdf")
        certidoes.registrar(c, uid, 1, documentos.tipo_por_chave(c, chave)["id"], "2026-09-01", "2026-12-31", rel, sha,
                            "upload", natureza="negativa", leitura="automatica")
    rel, sha = arquivos.gravar_bytes("regularidades", _pdf("REGULARIDADE 07/2026"), "pdf")
    documentos.registrar_regularidade(c, uid, 1, "2026-07", rel, sha, 100, "072026 - LOTUFO.pdf")
    for obra in ("mtpar", "sinfra", "vg"):
        for tipo in ("execucao", "reajuste"):
            c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
                      "nota_emitida_em) VALUES (?, 23, ?, '2026-09', 'nota_emitida', 1000000, '2026-09-15')",
                      (ids[obra], tipo))
            mid = c.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]
            ids[f"{obra}_{'exec' if tipo == 'execucao' else 'reaj'}"] = mid
            rel, sha = arquivos.gravar_bytes("notas", _pdf(f"NFS-e 23{mid:02d}"), "pdf")
            c.execute("INSERT INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, numero_nf, item_id, arquivo, "
                      "sha256, tamanho) VALUES (?,?,?,?,?,?,?,?,?)",
                      (mid, "operacao", "nfs", f"NFS 23{mid:02d}.pdf", f"23{mid:02d}", f"pdf:{sha}", rel, sha, 10))
    c.commit()
    return ids


def _validade(c, chave, validade):
    c.execute("UPDATE certidoes SET validade=? WHERE tipo_id=(SELECT id FROM certidao_tipos WHERE chave=?)",
              (validade, chave))
    c.commit()


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    monkeypatch.setattr(tempo, "hoje_local", lambda: HOJE)
    c = db.get_conn(); db.migrate(c)
    uid = auth.criar_usuario(c, "Leo", "leo@exemplo.com.br", "senha-forte-123", "admin")
    ids = _cadastro(c, uid)
    ids.update(uid=uid, usuario={"id": uid, "email": "leo@exemplo.com.br"}, sim=tmp_path / "sim")
    yield c, ids
    c.close()


@pytest.fixture
def api(client_admin, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    monkeypatch.setattr(tempo, "hoje_local", lambda: HOJE)
    c = db.get_conn()
    ids = _cadastro(c, 1)
    yield client_admin, c, ids
    c.close()


def _por_contrato(lista, cid):
    return [x for x in lista["envios"] if x["contrato_id"] == cid]


# --- lista -----------------------------------------------------------------------------------------

def test_lista_junta_na_sinfra_e_vg_e_separa_na_mtpar(svc):
    c, ids = svc
    lista = notas_envio.a_enviar(c, HOJE)
    sinfra, = _por_contrato(lista, ids["sinfra"])
    assert sinfra["medicao_ids"] == [ids["sinfra_exec"], ids["sinfra_reaj"]]
    assert (sinfra["grupo"], sinfra["orgao_sub"], sinfra["descricao"]) == ("SINFRA", "SUEF II", "23ª medição + reajuste")
    assert sinfra["situacao"] == "pronto" and sinfra["aviso"] is None and sinfra["dias"] == 1
    assert {i["chave"] for i in sinfra["itens"]} == {"notas", "certidoes:lotufo", "regularidade:lotufo"}
    assert len(_por_contrato(lista, ids["mtpar"])) == 2
    vg, = _por_contrato(lista, ids["vg"])                            # D9: VG junta
    assert vg["grupo"] == "Pref. VG" and len(vg["medicao_ids"]) == 2
    assert lista["contadores"] == {"Todas": 4, "MTPAR": 2, "SINFRA": 1, "Pref. VG": 1}


def test_aviso_de_15_dias_e_regularidade_que_falta(svc):
    c, ids = svc
    _validade(c, "municipal", "2026-09-24")
    c.execute("DELETE FROM regularidades"); c.commit()
    sinfra, = _por_contrato(notas_envio.a_enviar(c, HOJE), ids["sinfra"])
    assert sinfra["situacao"] == "pendente"
    assert sinfra["aviso"] == "municipal vence em 8 dias · Falta a regularidade"
    reg = next(i for i in sinfra["itens"] if i["chave"] == "regularidade:lotufo")
    assert (reg["estado"], reg["entidade_id"], reg["competencia"], reg["acao"]) == ("falta", 1, "2026-07",
                                                                                    "anexar_regularidade")
    mtpar = _por_contrato(notas_envio.a_enviar(c, HOJE), ids["mtpar"])[0]
    assert mtpar["situacao"] == "pronto" and "regularidade:lotufo" not in {i["chave"] for i in mtpar["itens"]}


def test_juntar_e_separar_descarta_o_rascunho_anterior(svc):
    c, ids = svc
    p1 = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_exec"]])
    assert notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_exec"]]) == p1
    p2 = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_exec"], ids["sinfra_reaj"]])
    assert p2 != p1 and protocolo.detalhe(c, p1)["situacao"] == "descartado"
    p_vg = notas_envio.iniciar(c, ids["uid"], ids["vg"], [ids["vg_exec"], ids["vg_reaj"]], "254")    # D9: um ofício
    assert len(protocolo.detalhe(c, p_vg)["medicoes"]) == 2
    with pytest.raises(ValueError, match="cada nota"):
        notas_envio.iniciar(c, ids["uid"], ids["mtpar"], [ids["mtpar_exec"], ids["mtpar_reaj"]], "361")


# --- regras do envio (D1-D7) -----------------------------------------------------------------------

def test_sinfra_corpo_pelos_anexos_regularidade_com_nome_novo_e_sem_cno(svc):
    c, ids = svc
    pid = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_exec"], ids["sinfra_reaj"]])
    d = notas_envio.detalhe_envio(c, pid, remetente="leo@exemplo.com.br", hoje=HOJE)
    assert "Seguem, em anexo, notas fiscais, certidões de regularidade e regularidade mensal." in d["previa"]["corpo"]
    nomes = [a["nome"] for a in d["previa"]["anexos"]]
    assert "Regularidade mensal - Lotufo - 07-2026.pdf" in nomes and not any(n.startswith("CNO") for n in nomes)
    assert d["pendencias"] == [] and d["bloqueio"] is None and d["carta"] is None
    protocolo.adicionar_peca(c, ids["uid"], pid, "outro", "Relatorio assinado.pdf", _pdf("RELATORIO"), "pdf")
    d = notas_envio.detalhe_envio(c, pid, hoje=HOJE)
    assert "Relatorio assinado.pdf" in [a["nome"] for a in d["previa"]["anexos"]] and d["pendencias"] == []
    assert "regularidade mensal e relatórios assinados." in d["previa"]["corpo"]


def test_anexo_separado_vai_solto_no_email_e_nao_desfaz_o_montado(svc):
    c, ids = svc
    pid = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_exec"]])
    protocolo.adicionar_peca(c, ids["uid"], pid, protocolo.ANEXO, "Justificativa tecnica.pdf", _pdf("JUSTIFICATIVA"), "pdf")
    d = notas_envio.detalhe_envio(c, pid, hoje=HOJE)
    assert {"nome": "Justificativa tecnica.pdf", "origem": "anexo"}.items() <= next(
        a for a in d["previa"]["anexos"] if a["nome"] == "Justificativa tecnica.pdf").items()
    assert "regularidade mensal e documento complementar." in d["previa"]["corpo"]
    assert [x["nome"] for x in d["extras"]] == ["Justificativa tecnica.pdf"]
    # com carta (MTPAR): fica fora do PDF montado e anexar/remover nao volta o protocolo a rascunho
    pm = notas_envio.iniciar(c, ids["uid"], ids["mtpar"], [ids["mtpar_exec"]], "361")
    paginas = notas_envio.detalhe_envio(c, pm, hoje=HOJE)["carta"]["paginas"]
    protocolo.montar(c, ids["uid"], pm, hoje=HOJE)
    protocolo.adicionar_peca(c, ids["uid"], pm, protocolo.ANEXO, "Justificativa.pdf", _pdf("J"), "pdf")
    d = notas_envio.detalhe_envio(c, pm, hoje=HOJE)
    assert d["situacao_protocolo"] == "montado" and d["carta"]["paginas"] == paginas
    assert "Justificativa.pdf" in [a["nome"] for a in d["previa"]["anexos"]]
    protocolo.remover_peca(c, ids["uid"], pm, d["extras"][0]["id"])
    d = notas_envio.detalhe_envio(c, pm, hoje=HOJE)
    assert d["situacao_protocolo"] == "montado" and d["extras"] == []


def test_zip_do_docusign_entra_como_documento_complementar(api):
    cli, c, ids = api
    pid = notas_envio.iniciar(c, 1, ids["sinfra"], [ids["sinfra_exec"]])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Diagrama_Linear.pdf", _pdf("DIAGRAMA"))
    zipado = buf.getvalue()
    r = cli.post(f"/api/protocolos/{pid}/pecas", data={"tipo": "anexo"},
                 files={"arquivo": ("Complete_com_o_Docusign_Diagrama.zip", zipado, "application/x-zip-compressed")})
    assert r.status_code == 200, r.text
    d = notas_envio.detalhe_envio(c, pid, hoje=HOJE)
    assert [x["nome"] for x in d["extras"]] == ["Complete_com_o_Docusign_Diagrama.zip"]
    assert {"nome": "Complete_com_o_Docusign_Diagrama.zip", "origem": "anexo"}.items() <= next(
        a for a in d["previa"]["anexos"] if a["nome"].startswith("Complete_com")).items()
    # zip fora do documento complementar nao entra (peca tecnica vai dentro do PDF da carta)
    r = cli.post(f"/api/protocolos/{pid}/pecas", data={"tipo": "boletim"},
                 files={"arquivo": ("x.zip", zipado, "application/zip")})
    assert r.status_code == 422
    # PDF disfarcado de zip e' recusado pela assinatura do arquivo
    r = cli.post(f"/api/protocolos/{pid}/pecas", data={"tipo": "anexo"},
                 files={"arquivo": ("falso.zip", _pdf("X"), "application/zip")})
    assert r.status_code == 415


def test_link_do_onedrive_entra_no_corpo_antes_da_assinatura_e_vira_clicavel(svc, monkeypatch):
    c, ids = svc
    monkeypatch.setenv("DASH_SHAREPOINT_HOSTS", "exemplo-my.sharepoint.com,exemplo.sharepoint.com")
    pid = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_exec"]])
    url = "https://exemplo-my.sharepoint.com/:u:/g/personal/leo/IQAbc?e=1&x=2"
    with pytest.raises(ValueError, match="https://"):
        protocolo.adicionar_link(c, ids["uid"], pid, "Documento juntado", "exemplo-my.sharepoint.com/x")
    with pytest.raises(ValueError, match="nome"):
        protocolo.adicionar_link(c, ids["uid"], pid, "  ", url)
    lid = protocolo.adicionar_link(c, ids["uid"], pid, "Documento juntado - 15ª Medição", url)
    d = notas_envio.detalhe_envio(c, pid, hoje=HOJE)
    corpo = d["previa"]["corpo"]
    assert f"Arquivos por link (OneDrive):\nDocumento juntado - 15ª Medição: {url}" in corpo
    assert corpo.index("Arquivos por link") < corpo.index("Atenciosamente")
    assert [x["nome"] for x in d["previa"]["links"]] == ["Documento juntado - 15ª Medição"]
    assert all(a["nome"] != "Documento juntado - 15ª Medição" for a in d["previa"]["anexos"])   # nao e' anexo
    html = protocolo._html(corpo)
    assert '<a href="https://exemplo-my.sharepoint.com/:u:/g/personal/leo/IQAbc?e=1&amp;x=2">' in html
    protocolo.remover_link(c, ids["uid"], pid, lid)
    assert "Arquivos por link" not in notas_envio.detalhe_envio(c, pid, hoje=HOJE)["previa"]["corpo"]


def test_mtpar_assunto_d1_carta_com_fiscal_d3_e_ordem_das_paginas(svc):
    c, ids = svc
    pid = notas_envio.iniciar(c, ids["uid"], ids["mtpar"], [ids["mtpar_exec"]], "361")
    d = notas_envio.detalhe_envio(c, pid, hoje=HOJE)
    assert d["previa"]["assunto"] == "Protocolo CT/361/LT/2026: 23ª Medição, ref. 09/2026, Obra MTPAR"
    assert d["carta"]["paginas"] == ["Ofício CT/361/LT/2026", f"NF 23{ids['mtpar_exec']:02d}",
                                     "Certidão municipal – Lotufo", "Certidão trabalhista – Lotufo",
                                     "Certidão estadual – Lotufo", "Certidão federal – Lotufo", "Certidão FGTS – Lotufo"]
    pagina = _textos(protocolo.montar(c, ids["uid"], pid, hoje=HOJE)["arquivo"])[0]
    assert "A/C: Beatriz Exemplo" in pagina and "Engenheiro(a) Fiscal: Beatriz Exemplo" in pagina


def test_zip_so_com_as_cinco(svc):
    c, ids = svc
    rel, sha = arquivos.gravar_bytes("certidoes", _pdf("FALENCIA"), "pdf")
    certidoes.registrar(c, ids["uid"], 1, documentos.tipo_por_chave(c, "falencia")["id"], "2026-09-01", "2026-10-30",
                        rel, sha, "upload", natureza="negativa", leitura="automatica")
    nome, dados = documentos.zip_vigentes(c, 1, HOJE.isoformat())
    assert len(zipfile.ZipFile(io.BytesIO(dados)).namelist()) == 5


def test_destinatarios_da_nota_com_protocolo_assinados_para(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(tempo, "hoje_local", lambda: HOJE)
    c = db.get_conn(); db.migrate(c)
    uid = auth.criar_usuario(c, "Leo", "leo@exemplo.com.br", "senha-forte-123", "admin")
    ids = _cadastro(c, uid, assinados_para=["fiscal@orgao-a.exemplo.com.br"])
    pid = notas_envio.iniciar(c, uid, ids["sinfra"], [ids["sinfra_exec"]])
    pv = protocolo.previa_envio(c, [pid], hoje=HOJE)
    assert pv["para"] == ["fiscal@orgao-a.exemplo.com.br"]               # sem fiscal e sem extras
    p_vg = notas_envio.iniciar(c, uid, ids["vg"], [ids["vg_exec"]], "254")
    assert protocolo.previa_envio(c, [p_vg], hoje=HOJE)["para"] == ["saude@vg.com", "fiscal@exemplo.gov.br"]
    c.close()


def test_remetente_fora_da_copia_pela_conta_do_outlook(svc, monkeypatch):
    c, ids = svc
    pid = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_exec"]])
    copia = protocolo.previa_envio(c, [pid], remetente="leo@exemplo.com.br", hoje=HOJE)["copia"]
    assert "leo.outlook@exemplo.com.br" in copia               # sem envio anterior: nao se sabe a conta
    monkeypatch.setattr(correio.CorreioSimulado, "remetente", lambda self: "leo.outlook@exemplo.com.br")
    eid = correio.enviar_e_registrar(c, ids["usuario"], "teste", ["x@y.com"],
                                     ["josi@l.com", "Leo.Outlook@exemplo.com.br"], "teste", "<p>a</p>", [])
    assert json.loads(c.execute("SELECT copia FROM envios WHERE id=?", (eid,)).fetchone()[0]) == ["josi@l.com"]
    copia = protocolo.previa_envio(c, [pid], remetente="leo@exemplo.com.br", hoje=HOJE)["copia"]
    assert copia == ["josi@l.com"]


def test_copia_da_obra_soma_a_do_orgao_so_naquele_contrato(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(tempo, "hoje_local", lambda: HOJE)
    c = db.get_conn(); db.migrate(c)
    uid = auth.criar_usuario(c, "Leo", "leo@exemplo.com.br", "senha-forte-123", "admin")
    ids = _cadastro(c, uid, assinados_para=["fiscal@orgao-a.exemplo.com.br"])
    for obra in ("mtpar", "sinfra"):        # o engenheiro de cada obra; repetido e quem ja' esta' no Para nao duplicam
        c.execute("UPDATE contratos SET copia_extras=? WHERE id=?",
                  (json.dumps([f"eng.{obra}@l.com", "josi@l.com", "fiscal@orgao-a.exemplo.com.br"]), ids[obra]))
    c.commit()
    p_mt = notas_envio.iniciar(c, uid, ids["mtpar"], [ids["mtpar_exec"]], "254")
    assert protocolo.previa_envio(c, [p_mt], hoje=HOJE)["copia"] == ["josi@l.com", "eng.mtpar@l.com",
                                                                      "fiscal@orgao-a.exemplo.com.br"]
    p_si = notas_envio.iniciar(c, uid, ids["sinfra"], [ids["sinfra_exec"]])
    assert protocolo.previa_envio(c, [p_si], hoje=HOJE)["copia"] == ["josi@l.com", "leo.outlook@exemplo.com.br",
                                                                      "eng.sinfra@l.com"]
    p_vg = notas_envio.iniciar(c, uid, ids["vg"], [ids["vg_exec"]], "255")
    assert protocolo.previa_envio(c, [p_vg], hoje=HOJE)["copia"] == []
    c.close()


# --- API: bloqueio, envio, por fora, aguardando pagamento ------------------------------------------

def test_certidao_vencida_bloqueia_com_409(api):
    cl, c, ids = api
    _validade(c, "federal", "2026-09-10")
    lista = cl.get("/api/notas/a-enviar").json()
    sinfra, = _por_contrato(lista, ids["sinfra"])
    assert sinfra["situacao"] == "bloqueado" and "federal vencida em 10/09" in sinfra["aviso"]
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"],
                                                    "medicao_ids": sinfra["medicao_ids"]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    assert d["bloqueio"] == "Certidão vencida — renove antes de enviar: Lotufo: federal vencida em 10/09/2026"
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d, justificativa="mandar assim mesmo, urgente"))
    assert r.status_code == 409, r.text
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0


def test_envio_pelo_simulador_vira_aguardando_pagamento(api, tmp_path):
    cl, c, ids = api
    r = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"],
                                                  "medicao_ids": [ids["sinfra_exec"], ids["sinfra_reaj"]]})
    pid = r.json()["protocolo_id"]
    assert _por_contrato(cl.get("/api/notas/a-enviar").json(), ids["sinfra"])[0]["protocolo_id"] == pid
    d = cl.get(f"/api/notas/envio/{pid}").json()
    assert d["etapa"] == "nota" and d["pendencias"] == []         # issue #213: nada falta, nada a confirmar
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d))
    assert r.status_code == 200, r.text
    enviado = json.loads(sorted((tmp_path / "sim" / "enviados").glob("*.json"))[0].read_text(encoding="utf-8"))
    assert "Regularidade mensal - Lotufo - 07-2026.pdf" in [a["nome"] for a in enviado["anexos"]]
    estados = {r[0] for r in c.execute("SELECT estado || '/' || envio_origem FROM medicoes WHERE id IN (?,?)",
                                       (ids["sinfra_exec"], ids["sinfra_reaj"]))}
    assert estados == {"protocolada/sistema"}
    assert not _por_contrato(cl.get("/api/notas/a-enviar").json(), ids["sinfra"])
    ag = {x["medicao_id"]: x for x in cl.get("/api/notas/aguardando-pagamento").json()}
    x = ag[ids["sinfra_exec"]]
    assert (x["origem"], x["familia"], x["orgao"]) == ("sistema", "sinfra", "SINFRA")
    assert x["enviada_em"] == tempo.para_local(tempo.agora_utc()).date().isoformat()    # data do e-mail, em Cuiaba


def test_envio_feito_por_fora_e_numero_do_siga(api):
    cl, c, ids = api
    r = cl.post("/api/notas/envio-externo",
                data={"medicao_ids": [str(ids["mtpar_exec"])], "enviado_em": "2026-09-15",
                      "observacao": "Enviado pela Maria do Outlook dela"},
                files={"eml": ("envio.eml", b"From: Maria <maria@exemplo.com.br>\r\n"
                                            b"To: protocolo@orgao-b.exemplo.com.br\r\n"
                                            b"Date: Tue, 15 Sep 2026 10:00:00 -0400\r\n"
                                            b"Subject: CT/361\r\n\r\ncorpo", "message/rfc822")})
    assert r.status_code == 200, r.text
    m = c.execute("SELECT estado, envio_origem, envio_externo_em FROM medicoes WHERE id=?",
                  (ids["mtpar_exec"],)).fetchone()
    assert tuple(m) == ("protocolada", "externo", "2026-09-15")
    assert c.execute("SELECT COUNT(*) FROM medicao_documentos WHERE medicao_id=? AND tipo_doc='evidencia_orgao'",
                     (ids["mtpar_exec"],)).fetchone()[0] == 1
    x = next(a for a in cl.get("/api/notas/aguardando-pagamento").json() if a["medicao_id"] == ids["mtpar_exec"])
    assert (x["origem"], x["enviada_em"], x["sem_numero_orgao"]) == ("externo", "2026-09-15", True)
    assert cl.post(f"/api/notas/{ids['mtpar_exec']}/numero-orgao", json={"numero": "MTPARPRO202601234"}).status_code == 200
    x = next(a for a in cl.get("/api/notas/aguardando-pagamento").json() if a["medicao_id"] == ids["mtpar_exec"])
    assert x["numero_orgao"] == "MTPARPRO202601234" and x["sem_numero_orgao"] is False
    r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["mtpar_exec"])], "enviado_em": "2026-09-15",
                                                 "observacao": "de novo"})
    assert r.status_code == 422                                         # ja' protocolada


def _oficio_fora(c, mid):
    return [r[0] for r in c.execute("SELECT numero_oficio FROM medicao_protocolos WHERE medicao_id=?", (mid,))]


def test_registro_por_fora_grava_o_oficio_digitado_no_protocolo_da_medicao(api):
    """Issue #231: o nº do ofício do registro por fora vai para o protocolo da medição (normalizado como no envio
    pelo sistema, com a sigla da entidade e o ano do envio), e não mais só no texto da observação."""
    cl, c, ids = api
    r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["mtpar_exec"])], "enviado_em": "2026-09-15",
                                                 "observacao": "Pelo Outlook", "numero_oficio": " 360 "})
    assert r.status_code == 200, r.text
    assert _oficio_fora(c, ids["mtpar_exec"]) == ["CT-360-LT-2026"]
    aud = json.loads(c.execute("SELECT depois FROM audit_log WHERE acao='notas.envio_externo'").fetchone()[0])
    assert aud["numero_oficio"] == "CT-360-LT-2026" and aud["observacao"] == "Pelo Outlook"


def test_registro_por_fora_sem_oficio_segue_o_de_hoje(api):
    cl, c, ids = api
    r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["mtpar_exec"])], "enviado_em": "2026-09-15",
                                                 "observacao": "Pelo Outlook", "numero_oficio": "  "})
    assert r.status_code == 200, r.text
    assert _oficio_fora(c, ids["mtpar_exec"]) == [None]
    aud = json.loads(c.execute("SELECT depois FROM audit_log WHERE acao='notas.envio_externo'").fetchone()[0])
    assert "numero_oficio" not in aud


def test_registro_por_fora_usa_o_ano_do_envio_e_o_ano_digitado(api):
    cl, c, ids = api
    r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["mtpar_exec"])], "enviado_em": "2025-12-30",
                                                 "observacao": "Pelo Outlook", "numero_oficio": "12"})
    assert r.status_code == 200, r.text
    assert _oficio_fora(c, ids["mtpar_exec"]) == ["CT-012-LT-2025"]
    r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["mtpar_reaj"])], "enviado_em": "2026-09-15",
                                                 "observacao": "Pelo Outlook", "numero_oficio": "CT/361/LT/2025"})
    assert r.status_code == 200, r.text
    assert _oficio_fora(c, ids["mtpar_reaj"]) == ["CT-361-LT-2025"]


def test_registro_por_fora_usa_a_sigla_como_o_envio_pelo_sistema(api):
    """Como em `iniciar`: contrato sem entidade usa LT; entidade sem sigla (carta propria) vira CARTA-NNN-AAAA."""
    cl, c, ids = api
    c.execute("UPDATE contratos SET entidade_id=NULL WHERE id=?", (ids["mtpar"],)); c.commit()
    r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["mtpar_exec"])], "enviado_em": "2026-09-15",
                                                 "observacao": "Pelo Outlook", "numero_oficio": " Ofício 360/2026 "})
    assert r.status_code == 200, r.text
    assert _oficio_fora(c, ids["mtpar_exec"]) == ["CT-360-LT-2026"]
    c.execute("UPDATE entidades SET sigla_oficio=NULL"); c.commit()
    r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["sinfra_exec"])], "enviado_em": "2026-09-15",
                                                 "observacao": "Pelo Outlook", "numero_oficio": "48"})
    assert r.status_code == 200, r.text
    assert _oficio_fora(c, ids["sinfra_exec"]) == ["CARTA-048-2026"]


def test_registro_por_fora_sem_oficio_usa_o_do_ultimo_envio_e_o_digitado_vence(api):
    cl, c, ids = api
    for mid, oficio in ((ids["mtpar_exec"], ""), (ids["mtpar_reaj"], "361")):
        pid = notas_envio.iniciar(c, 1, ids["mtpar"], [mid], "300")
        c.execute("UPDATE protocolos SET situacao='enviado' WHERE id=?", (pid,)); c.commit()
        r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(mid)], "enviado_em": "2026-09-15",
                                                     "observacao": "Pelo Outlook", "numero_oficio": oficio})
        assert r.status_code == 200, r.text
    assert _oficio_fora(c, ids["mtpar_exec"]) == ["CT-300-LT-2026"]
    assert _oficio_fora(c, ids["mtpar_reaj"]) == ["CT-361-LT-2026"]


def test_registro_por_fora_recusa_oficio_sem_numero_ou_longo_sem_gravar_nada(api):
    cl, c, ids = api
    c.execute("UPDATE contratos SET entidade_id=NULL WHERE id=?", (ids["mtpar"],)); c.commit()   # sem sigla tambem
    for oficio, trecho in (("por e-mail", "Informe o número do ofício"), ("1" * 41, None)):
        r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["mtpar_exec"])], "enviado_em": "2026-09-15",
                                                     "observacao": "Pelo Outlook", "numero_oficio": oficio})
        assert r.status_code == 422, r.text
        if trecho:
            assert trecho in r.json()["detail"]
    assert _oficio_fora(c, ids["mtpar_exec"]) == []
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE acao='notas.envio_externo'").fetchone()[0] == 0


EML = (b"From: Engenharia <engenharia@exemplo.com.br>\r\nTo: sinfra@orgao-a.exemplo.com.br\r\n"
       b"Date: Tue, 15 Sep 2026 10:00:00 -0400\r\nSubject: 23 medicao e reajuste\r\n\r\ncorpo")


def test_envio_por_fora_da_medicao_e_do_reajuste_juntos(api):
    """Issue #172: medicao e reajuste no mesmo e-mail viram um registro so': as duas com o mesmo .eml e uma auditoria."""
    cl, c, ids = api
    par = [ids["sinfra_exec"], ids["sinfra_reaj"]]
    r = cl.post("/api/notas/envio-externo",
                data={"medicao_ids": [str(x) for x in par], "enviado_em": "2026-09-15", "observacao": "Pelo Outlook"},
                files={"eml": ("envio.eml", EML, "message/rfc822")})
    assert r.status_code == 200, r.text
    linhas = c.execute("SELECT estado, envio_origem, envio_externo_em FROM medicoes WHERE id IN (?,?)", par).fetchall()
    assert {tuple(x) for x in linhas} == {("protocolada", "externo", "2026-09-15")}
    emls = c.execute("SELECT medicao_id, arquivo FROM medicao_documentos WHERE tipo_doc='evidencia_orgao'").fetchall()
    assert sorted(x[0] for x in emls) == par and len({x[1] for x in emls}) == 1
    aud = c.execute("SELECT depois FROM audit_log WHERE acao='notas.envio_externo'").fetchall()
    assert len(aud) == 1 and json.loads(aud[0][0])["medicoes"] == par


def test_envio_por_fora_com_a_irma_fora_de_nota_emitida_nao_registra_nenhuma(api):
    cl, c, ids = api
    c.execute("UPDATE medicoes SET estado='espelho_enviado' WHERE id=?", (ids["sinfra_reaj"],)); c.commit()
    r = cl.post("/api/notas/envio-externo",
                data={"medicao_ids": [str(ids["sinfra_exec"]), str(ids["sinfra_reaj"])], "enviado_em": "2026-09-15",
                      "observacao": "Pelo Outlook"}, files={"eml": ("envio.eml", EML, "message/rfc822")})
    assert r.status_code == 422 and "não está com a nota emitida" in r.json()["detail"]
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["sinfra_exec"],)).fetchone()[0] == "nota_emitida"
    assert c.execute("SELECT COUNT(*) FROM medicao_documentos WHERE tipo_doc='evidencia_orgao'").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE acao='notas.envio_externo'").fetchone()[0] == 0


def test_lista_traz_a_irma_em_outro_envio_so_onde_medicao_e_reajuste_vao_juntos(svc):
    """Issue #172: a irma (mesmo numero, outro tipo, nota emitida) fora do envio aparece para o registro por fora."""
    c, ids = svc
    for obra in ("sinfra", "vg", "mtpar"):           # competencias diferentes: a lista nao as junta sozinha
        c.execute("UPDATE medicoes SET competencia='2026-08' WHERE id=?", (ids[f"{obra}_reaj"],))
    c.commit()
    lista = notas_envio.a_enviar(c, HOJE)
    for obra in ("sinfra", "vg"):
        por_medicao = {x["medicao_ids"][0]: x for x in _por_contrato(lista, ids[obra])}
        assert por_medicao[ids[f"{obra}_exec"]]["irmas"] == [
            {"medicao_id": ids[f"{obra}_reaj"], "titulo": "Reajuste da 23ª Medição", "tipo": "reajuste"}]
        assert por_medicao[ids[f"{obra}_reaj"]]["irmas"] == [
            {"medicao_id": ids[f"{obra}_exec"], "titulo": "23ª Medição", "tipo": "execucao"}]
    assert all(x["irmas"] == [] for x in _por_contrato(lista, ids["mtpar"]))       # MTPAR tramita separado
    # irma que nao esta' em nota emitida nao e' oferecida
    c.execute("UPDATE medicoes SET estado='espelho_enviado' WHERE id=?", (ids["sinfra_reaj"],)); c.commit()
    sinfra, = _por_contrato(notas_envio.a_enviar(c, HOJE), ids["sinfra"])
    assert sinfra["irmas"] == []


def test_irma_bloqueada_ou_com_envio_montado_nao_e_oferecida(svc):
    """/code-review da PR do #172: o registro por fora nao pode contornar o bloqueio da irma nem descartar o envio
    montado dela; rascunho continua permitindo."""
    c, ids = svc
    c.execute("UPDATE medicoes SET competencia='2026-08' WHERE id=?", (ids["sinfra_reaj"],)); c.commit()
    pid = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_reaj"]])
    irmas = lambda: next(x for x in _por_contrato(notas_envio.a_enviar(c, HOJE), ids["sinfra"])
                         if x["medicao_ids"] == [ids["sinfra_exec"]])["irmas"]
    assert [i["medicao_id"] for i in irmas()] == [ids["sinfra_reaj"]]               # rascunho: oferece
    c.execute("UPDATE protocolos SET situacao='montado' WHERE id=?", (pid,)); c.commit()
    assert irmas() == []
    c.execute("UPDATE protocolos SET situacao='descartado' WHERE id=?", (pid,)); c.commit()
    _validade(c, "federal", "2026-09-10")                    # vencida: bloqueia a irma (e o envio dela)
    assert irmas() == []


def test_envio_por_fora_recusa_medicoes_de_contratos_diferentes(api):
    cl, c, ids = api
    r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["sinfra_exec"]), str(ids["vg_exec"])],
                                                 "enviado_em": "2026-09-15", "observacao": "Pelo Outlook"})
    assert r.status_code == 422 and r.json()["detail"] == "Medição de outro contrato"
    assert c.execute("SELECT COUNT(*) FROM medicoes WHERE estado='protocolada'").fetchone()[0] == 0


def _sem_registro(c, mid):
    assert c.execute("SELECT COUNT(*) FROM medicao_protocolos WHERE medicao_id=?", (mid,)).fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM medicao_documentos WHERE medicao_id=? AND tipo_doc='evidencia_orgao'",
                     (mid,)).fetchone()[0] == 0


def test_registro_por_fora_que_perde_a_corrida_nao_grava_nada(api, monkeypatch):
    """Revisor da PR #178 (aviso 1): o estado e' conferido de novo dentro da transacao. Aqui outro registro protocola
    o reajuste enquanto o .eml e' conferido; sem a nova conferencia, sairia um segundo protocolo e uma segunda
    auditoria. Gate Sol S2: a recusa tambem nao deixa o .eml gravado."""
    cl, c, ids = api
    conferir, antes = notas_envio._e_email, _evidencias()

    def conferir_e_perder(dados):
        c.execute("UPDATE medicoes SET estado='protocolada' WHERE id=?", (ids["sinfra_reaj"],)); c.commit()
        return conferir(dados)
    monkeypatch.setattr(notas_envio, "_e_email", conferir_e_perder)
    r = cl.post("/api/notas/envio-externo",
                data={"medicao_ids": [str(ids["sinfra_exec"]), str(ids["sinfra_reaj"])], "enviado_em": "2026-09-15",
                      "observacao": "Pelo Outlook"}, files={"eml": ("envio.eml", EML, "message/rfc822")})
    assert r.status_code == 422 and "não está com a nota emitida (protocolada)" in r.json()["detail"]
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["sinfra_exec"],)).fetchone()[0] == "nota_emitida"
    _sem_registro(c, ids["sinfra_exec"]); _sem_registro(c, ids["sinfra_reaj"])
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE acao='notas.envio_externo'").fetchone()[0] == 0
    assert _evidencias() == antes


def test_dois_registros_por_fora_simultaneos_da_mesma_irma_um_passa(api, monkeypatch):
    """Regra da casa para envio: dois POST simultaneos = 1x200 e 1x422. Os dois passam da primeira conferencia (a
    barreira segura os dois na conferencia do .eml, antes da transacao); so' um protocola a irma."""
    import threading
    cl, c, ids = api
    c.execute("UPDATE medicoes SET competencia='2026-08' WHERE id=?", (ids["sinfra_reaj"],)); c.commit()
    conferir, largada = notas_envio._e_email, threading.Barrier(2)

    def conferir_junto(dados):
        largada.wait(timeout=10)
        return conferir(dados)
    monkeypatch.setattr(notas_envio, "_e_email", conferir_junto)
    pedidos = [{"medicao_ids": [str(ids["sinfra_exec"])], "irma_ids": [str(ids["sinfra_reaj"])]},
               {"medicao_ids": [str(ids["sinfra_reaj"])]}]
    respostas = []

    def dispara(dados):
        respostas.append(cl.post("/api/notas/envio-externo",
                                 data={**dados, "enviado_em": "2026-09-15", "observacao": "Pelo Outlook"},
                                 files={"eml": ("envio.eml", EML, "message/rfc822")}))
    ts = [threading.Thread(target=dispara, args=(p,)) for p in pedidos]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(r.status_code for r in respostas) == [200, 422], [r.text for r in respostas]
    assert c.execute("SELECT COUNT(*) FROM medicao_protocolos WHERE medicao_id=?",
                     (ids["sinfra_reaj"],)).fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE acao='notas.envio_externo'").fetchone()[0] == 1


def test_registro_por_fora_recusa_protocolo_com_envio_reservado(api):
    """Revisor da PR #178 (aviso 2): o e-mail esta' saindo pelo sistema; descartar o protocolo reservado faria o
    orgao receber duas vezes."""
    cl, c, ids = api
    c.execute("UPDATE medicoes SET competencia='2026-08' WHERE id=?", (ids["sinfra_reaj"],)); c.commit()
    pid = notas_envio.iniciar(c, 1, ids["sinfra"], [ids["sinfra_reaj"]])
    c.execute("UPDATE protocolos SET envio_reservado_em=datetime('now'), envio_reservado_por=1 WHERE id=?", (pid,))
    c.commit()
    for dados in ({"medicao_ids": [str(ids["sinfra_exec"])], "irma_ids": [str(ids["sinfra_reaj"])]},
                  {"medicao_ids": [str(ids["sinfra_reaj"])]}):
        r = cl.post("/api/notas/envio-externo", data={**dados, "enviado_em": "2026-09-15", "observacao": "Pelo Outlook"})
        assert r.status_code == 422 and "está sendo enviada pelo sistema agora" in r.json()["detail"], r.text
    assert c.execute("SELECT situacao FROM protocolos WHERE id=?", (pid,)).fetchone()[0] == "rascunho"
    _sem_registro(c, ids["sinfra_exec"])


def test_registro_por_fora_recusa_irma_com_envio_montado_mas_aceita_a_medicao_da_pagina(api):
    """Revisor da PR #178 (aviso 2): o servidor reaplica o criterio da lista para a irma marcada; a medicao da propria
    pagina com envio montado continua podendo ser registrada por fora (como antes)."""
    cl, c, ids = api
    c.execute("UPDATE medicoes SET competencia='2026-08' WHERE id=?", (ids["sinfra_reaj"],)); c.commit()
    pid = notas_envio.iniciar(c, 1, ids["sinfra"], [ids["sinfra_reaj"]])
    c.execute("UPDATE protocolos SET situacao='montado' WHERE id=?", (pid,)); c.commit()
    r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["sinfra_exec"])],
                                                 "irma_ids": [str(ids["sinfra_reaj"])],
                                                 "enviado_em": "2026-09-15", "observacao": "Pelo Outlook"})
    assert r.status_code == 422 and "registre-a no envio dela" in r.json()["detail"]
    _sem_registro(c, ids["sinfra_exec"])
    assert c.execute("SELECT situacao FROM protocolos WHERE id=?", (pid,)).fetchone()[0] == "montado"
    r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["sinfra_reaj"])],
                                                 "enviado_em": "2026-09-15", "observacao": "Pelo Outlook"})
    assert r.status_code == 200, r.text


def test_registro_por_fora_recusa_irma_na_mtpar(api):
    cl, c, ids = api
    r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["mtpar_exec"])],
                                                 "irma_ids": [str(ids["mtpar_reaj"])],
                                                 "enviado_em": "2026-09-15", "observacao": "Pelo Outlook"})
    assert r.status_code == 422 and "registre-a no envio dela" in r.json()["detail"]
    _sem_registro(c, ids["mtpar_exec"])


def test_registro_por_fora_so_aceita_varias_medicoes_que_formam_um_envio(api):
    """Gate Sol S1 (PR #178): o cliente nao contorna a conferencia da irma pondo-a entre as medicoes do envio."""
    cl, c, ids = api
    mt = [str(ids["mtpar_exec"]), str(ids["mtpar_reaj"])]
    for dados in ({"medicao_ids": mt},                              # MTPAR tramita separado: nunca um envio so'
                  {"medicao_ids": mt, "irma_ids": [mt[1]]}):        # nas duas listas
        r = cl.post("/api/notas/envio-externo", data={**dados, "enviado_em": "2026-09-15", "observacao": "Pelo Outlook"},
                    files={"eml": ("envio.eml", EML, "message/rfc822")})
        assert r.status_code == 422, r.text
    assert c.execute("SELECT COUNT(*) FROM medicoes WHERE estado='protocolada'").fetchone()[0] == 0
    # SINFRA com o reajuste em envio proprio montado: medicao e reajuste ja' nao sao um envio
    c.execute("UPDATE medicoes SET competencia='2026-08' WHERE id=?", (ids["sinfra_reaj"],)); c.commit()
    pid = notas_envio.iniciar(c, 1, ids["sinfra"], [ids["sinfra_reaj"]])
    c.execute("UPDATE protocolos SET situacao='montado' WHERE id=?", (pid,)); c.commit()
    r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["sinfra_exec"]), str(ids["sinfra_reaj"])],
                                                 "enviado_em": "2026-09-15", "observacao": "Pelo Outlook"})
    assert r.status_code == 422 and "não vão no mesmo envio" in r.json()["detail"]
    _sem_registro(c, ids["sinfra_exec"]); _sem_registro(c, ids["sinfra_reaj"])
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE acao='notas.envio_externo'").fetchone()[0] == 0


def test_irma_no_mesmo_envio_nao_e_oferecida_de_novo(svc):
    c, ids = svc
    sinfra, = _por_contrato(notas_envio.a_enviar(c, HOJE), ids["sinfra"])
    assert len(sinfra["medicao_ids"]) == 2 and sinfra["irmas"] == []


# --- cobranca de certidoes por e-mail --------------------------------------------------------------

def _hora(h, mi=0, dia=HOJE):
    return datetime.datetime(dia.year, dia.month, dia.day, h, mi)


def test_cobranca_de_vencidas_a_cada_2h_e_vencendo_uma_vez_por_dia(svc):
    c, ids = svc
    _validade(c, "federal", "2026-09-10")
    _validade(c, "municipal", "2026-09-24")
    assert cobranca_certidoes.rodada(c, _hora(7, 50)) == []
    assert cobranca_certidoes.rodada(c, _hora(8, 5)) == ["Certidões vencidas (1)", "Certidões vencendo em 15 dias (1)"]
    assert cobranca_certidoes.rodada(c, _hora(9, 40)) == []                # mesma faixa, mesma lista
    assert cobranca_certidoes.rodada(c, _hora(10, 5)) == ["Certidões vencidas (1)"]
    assert cobranca_certidoes.rodada(c, _hora(19, 0)) == []
    enviado = json.loads(sorted((ids["sim"] / "enviados").glob("*.json"))[0].read_text(encoding="utf-8"))
    assert enviado["para"] == ["leo.outlook@exemplo.com.br"] and enviado["copia"] == []
    assert "Lotufo — CND Federal (RFB/PGFN) — validade 10/09/2026 — emitir em: https://" in enviado["corpo"]


def test_cobranca_sem_conta_conectada_so_registra_no_log(svc, monkeypatch):
    c, ids = svc
    monkeypatch.delenv("DASH_GRAPH_SIMULADOR")
    _validade(c, "federal", "2026-09-10")
    assert cobranca_certidoes.rodada(c, _hora(10)) == []
    assert c.execute("SELECT COUNT(*) FROM cobranca_certidoes_envios").fetchone()[0] == 0


def test_cobranca_sem_destinatario_no_cadastro_nao_envia(svc):
    """Issue #110: destinatario e login de quem envia vem do geral.yaml; sem eles, nada sai e nada e' registrado."""
    c, ids = svc
    c.execute("DELETE FROM cadastro_geral WHERE chave='cobranca_certidoes'"); c.commit()
    _validade(c, "federal", "2026-09-10")
    assert cobranca_certidoes.rodada(c, _hora(10)) == []
    assert not (ids["sim"] / "enviados").exists() or not list((ids["sim"] / "enviados").glob("*.json"))
    assert c.execute("SELECT COUNT(*) FROM cobranca_certidoes_envios").fetchone()[0] == 0


# --- testes de quebra 10/10/2026: A-17 (Cco descartado) e A-18 (reajuste irmao fora do e-mail) ------

def _corpo(d, **extra):
    # issue #100: o envio da nota leva sempre os anexos que a previa mostrou
    vistos = [{"nome": a["nome"], "tamanho": a["tamanho"]} for a in d["previa"]["anexos"]]
    return {**{k: d["previa"][k] for k in ("para", "copia", "assunto", "corpo")}, "anexos": vistos, **extra}


def test_cco_do_envio_da_nota_chega_ao_email_e_ao_registro(api, tmp_path):
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"], "medicao_ids": [
        ids["sinfra_exec"], ids["sinfra_reaj"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d, cco=["oculto@exemplo.com"]))
    assert r.status_code == 200, r.text
    enviado = json.loads(sorted((tmp_path / "sim" / "enviados").glob("*.json"))[0].read_text(encoding="utf-8"))
    assert enviado["cco"] == ["oculto@exemplo.com"]
    gravado = c.execute("SELECT cco FROM envios WHERE id=?", (r.json()["envio_id"],)).fetchone()[0]
    assert json.loads(gravado) == ["oculto@exemplo.com"]


IRMA = "Reajuste da 23ª Medição (mesma competência) está com nota emitida e não vai neste e-mail"


def test_sinfra_medicao_sem_o_reajuste_irmao_vira_pendencia(svc):
    c, ids = svc
    pid = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_exec"]])
    pend = notas_envio.detalhe_envio(c, pid, hoje=HOJE)["pendencias"]
    assert [p for p in pend if p.startswith(IRMA)] == [
        IRMA + ": junte pela opção 'Juntar outra nota desta obra' ou confirme o envio sem ela"]
    assert "irma_fora" in [p["codigo"] for p in protocolo.previa_envio(c, [pid], hoje=HOJE)["pendencias"]]
    # VG tambem junta (D9); a MTPAR nao junta: cada nota no seu e-mail, sem pendencia
    p_vg = notas_envio.iniciar(c, ids["uid"], ids["vg"], [ids["vg_exec"]], "254")
    assert "irma_fora" in [p["codigo"] for p in protocolo.previa_envio(c, [p_vg], hoje=HOJE)["pendencias"]]
    p_mt = notas_envio.iniciar(c, ids["uid"], ids["mtpar"], [ids["mtpar_exec"]], "361")
    assert "irma_fora" not in [p["codigo"] for p in protocolo.previa_envio(c, [p_mt], hoje=HOJE)["pendencias"]]


def test_reajuste_irmao_em_outro_envio_separado_tambem_cobra(svc):
    """Gate Sol S1 (10/10/2026): dois rascunhos separados nao podem anular o A-18."""
    c, ids = svc
    pid = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_exec"]])
    p_reaj = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_reaj"]])
    assert notas_envio.detalhe_envio(c, pid, hoje=HOJE)["pendencias"] == [
        "Reajuste da 23ª Medição (mesma competência) está em outro envio separado: na SINFRA e na Pref. VG medição "
        "e reajuste vão no mesmo e-mail — junte pela opção 'Juntar outra nota desta obra' (o outro rascunho é "
        "descartado) ou confirme o envio sem ela"]
    assert [p.split(" (")[0] for p in notas_envio.detalhe_envio(c, p_reaj, hoje=HOJE)["pendencias"]] == ["23ª Medição"]
    # os dois protocolos no MESMO e-mail: a irma vai junto, nao ha' o que cobrar
    assert "irma_fora" not in [p["codigo"] for p in protocolo.previa_envio(c, [pid, p_reaj], hoje=HOJE)["pendencias"]]


def test_protocolo_ja_enviado_nao_lista_mais_a_irma_fora(svc):
    """Backlog 10/10/2026 (issue #6): depois do envio a pendencia so' informava; rascunho continua cobrando."""
    c, ids = svc
    pid = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_exec"]])
    cods = lambda: [p["codigo"] for p in protocolo.detalhe(c, pid, hoje=HOJE)["pendencias"]]
    assert "irma_fora" in cods()                                          # rascunho: como hoje
    pv = protocolo.previa_envio(c, [pid], hoje=HOJE)
    protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                     confirmadas=[x["mensagem"] for x in pv["pendencias"]])
    assert protocolo.detalhe(c, pid, hoje=HOJE)["situacao"] == "enviado"
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["sinfra_reaj"],)).fetchone()[0] == "nota_emitida"
    assert "irma_fora" not in cods()


def test_projeto_e_reajuste_do_mesmo_numero_nao_sao_irmas(svc):
    """Gate Sol S2 (10/10/2026): o par e' execucao x reajuste; projeto e' outra serie."""
    c, ids = svc
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
              "nota_emitida_em) VALUES (?, 23, 'projeto', '2026-09', 'nota_emitida', 1000000, '2026-09-15')",
              (ids["sinfra"],))
    c.commit()
    proj = c.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]
    p_proj = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [proj])
    assert "irma_fora" not in [p["codigo"] for p in protocolo.previa_envio(c, [p_proj], hoje=HOJE)["pendencias"]]
    p_reaj = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_reaj"]])
    irmas = [p["mensagem"] for p in protocolo.previa_envio(c, [p_reaj], hoje=HOJE)["pendencias"]
             if p["codigo"] == "irma_fora"]
    assert [m.split(" (")[0] for m in irmas] == ["23ª Medição"]                  # so' a execucao, nao o projeto


def _confirmacoes(c) -> list[tuple]:
    return [(r[0], json.loads(r[1])["pendencias"]) for r in c.execute(
        "SELECT usuario_id, depois FROM audit_log WHERE acao='protocolo.envio_confirmado' ORDER BY id")]


def test_envio_com_documento_faltando_sem_confirmacao_e_recusado(api):
    """Issue #213: falta documento nao bloqueia, mas sem a confirmacao do aviso nada sai e nada e' gravado."""
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"],
                                                    "medicao_ids": [ids["sinfra_exec"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    assert d["bloqueio"] is None and any(p.startswith(IRMA) for p in d["pendencias"])
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d))
    det = r.json()["detail"]
    assert r.status_code == 422 and det["codigo"] == "CONFIRMAR_PENDENCIAS" and det["pendencias"] == d["pendencias"]
    assert det["mensagem"].startswith("ATENÇÃO: falta documento neste envio")
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0 and _confirmacoes(c) == []
    assert c.execute("SELECT envio_reservado_em FROM protocolos WHERE id=?", (pid,)).fetchone()[0] is None


def test_envio_confirmado_sai_e_grava_quem_quando_e_a_lista(api, monkeypatch):
    """Issue #213: "Continuar com o envio" manda a lista; a confirmacao (quem, quando, o que faltava) e' gravada na
    transacao da reserva, ANTES do e-mail; a justificativa escrita nao e' mais exigida."""
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"],
                                                    "medicao_ids": [ids["sinfra_exec"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    original, vistas = correio.enviar_e_registrar, []

    def espia(*a, **k):               # na hora do e-mail, outra conexao ja' le a confirmacao gravada
        outra = db.get_conn()
        try:
            vistas.extend(_confirmacoes(outra))
        finally:
            outra.close()
        return original(*a, **k)
    monkeypatch.setattr(correio, "enviar_e_registrar", espia)
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d, confirmadas=list(reversed(d["pendencias"]))))
    assert r.status_code == 200, r.text
    uid = c.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0]
    assert vistas == [(uid, d["pendencias"])] and _confirmacoes(c) == vistas
    em = c.execute("SELECT criado_em FROM audit_log WHERE acao='protocolo.envio_confirmado'").fetchone()[0]
    assert em
    p = c.execute("SELECT situacao, justificativa FROM protocolos WHERE id=?", (pid,)).fetchone()
    assert p["situacao"] == "enviado" and p["justificativa"] == protocolo.CONFIRMADO_COM_FALTA + d["pendencias"][0]
    depois = json.loads(c.execute("SELECT depois FROM audit_log WHERE acao='protocolo.enviar'").fetchone()[0])
    assert depois["confirmadas"] == d["pendencias"]


def test_envio_sem_nada_faltando_nao_grava_confirmacao(api):
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"], "medicao_ids": [
        ids["sinfra_exec"], ids["sinfra_reaj"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    assert d["pendencias"] == []
    assert cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d)).status_code == 200
    assert _confirmacoes(c) == []
    assert c.execute("SELECT justificativa FROM protocolos WHERE id=?", (pid,)).fetchone()[0] is None


def test_lista_diferente_da_confirmada_e_recusada(api):
    """Issue #213: a lista mudou entre o aviso e o envio (outro item faltando, ou um a menos): pede nova confirmacao."""
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"],
                                                    "medicao_ids": [ids["sinfra_exec"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    for lista in ([*d["pendencias"], "Falta a certidão federal"], ["Outra coisa"]):
        r = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d, confirmadas=lista))
        det = r.json()["detail"]
        assert r.status_code == 422 and det["codigo"] == "CONFIRMAR_PENDENCIAS", r.text
        assert "mudou" in det["mensagem"] and det["pendencias"] == d["pendencias"]
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0 and _confirmacoes(c) == []


def test_confirmacao_antiga_sem_nada_faltando_agora_envia(api):
    """Code-review da PR: confirmou o que faltava e, antes do clique, tudo foi resolvido; nao ha' o que confirmar."""
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"], "medicao_ids": [
        ids["sinfra_exec"], ids["sinfra_reaj"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    assert d["pendencias"] == []
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d, confirmadas=["Falta a certidão federal"]))
    assert r.status_code == 200, r.text
    assert _confirmacoes(c) == []


def test_auditoria_e_ressalva_usam_a_lista_lida_sob_o_lock(api, monkeypatch):
    """Revisor adversarial da PR #227: confirmou o que faltava e tudo se resolveu ate' a reserva; a lista que vale e' a
    lida sob o lock (vazia): nada de confirmacao gravada nem ressalva com o que ja' nao faltava."""
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"],
                                                    "medicao_ids": [ids["sinfra_exec"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    original, chamadas = protocolo._pendencias_envio, []

    def resolve_na_segunda(*a, **k):
        chamadas.append(1)
        return original(*a, **k) if len(chamadas) == 1 else []
    monkeypatch.setattr(protocolo, "_pendencias_envio", resolve_na_segunda)
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d, confirmadas=d["pendencias"]))
    assert r.status_code == 200, r.text
    assert _confirmacoes(c) == []
    assert c.execute("SELECT justificativa FROM protocolos WHERE id=?", (pid,)).fetchone()[0] is None


def test_justificativa_curta_com_confirmacao_nao_vira_pendencia_surgida_depois(api, monkeypatch):
    """Revisor adversarial da PR #227: pela API, justificativa curta junto da confirmacao nao pode apagar a lista nem
    marcar a medicao com o texto de pendencia surgida depois do e-mail."""
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"],
                                                    "medicao_ids": [ids["sinfra_exec"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    original, recebidas = medicoes.registrar_protocolo, []

    def espia(*a, **k):
        recebidas.append(k.get("justificativa"))
        return original(*a, **k)
    monkeypatch.setattr(medicoes, "registrar_protocolo", espia)
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d, confirmadas=d["pendencias"], justificativa="ok"))
    assert r.status_code == 200, r.text
    esperado = "ok; " + protocolo.CONFIRMADO_COM_FALTA + d["pendencias"][0]
    assert c.execute("SELECT justificativa FROM protocolos WHERE id=?", (pid,)).fetchone()[0] == esperado
    assert recebidas == [esperado] and protocolo.JUSTIFICATIVA_POS_ENVIO not in recebidas


def test_recusa_traz_o_codigo_de_cada_item_e_limita_o_tamanho(api):
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"],
                                                    "medicao_ids": [ids["sinfra_exec"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    det = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d)).json()["detail"]
    assert [x["mensagem"] for x in det["itens"]] == det["pendencias"] and "irma_fora" in [x["codigo"] for x in det["itens"]]
    assert cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d, confirmadas=["x" * 2001])).status_code == 422
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0


def test_lista_que_muda_ate_a_reserva_e_recusada_sob_o_lock(api, monkeypatch):
    """Issue #213: a conferencia se repete sob o lock da reserva; o que mudou depois da primeira leitura recusa sem
    reservar nem gravar a confirmacao."""
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"],
                                                    "medicao_ids": [ids["sinfra_exec"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    original, chamadas = protocolo._pendencias_envio, []

    def muda_na_segunda(*a, **k):
        chamadas.append(1)
        out = original(*a, **k)
        return out if len(chamadas) == 1 else [*out, {"protocolo_id": pid, "codigo": "certidao",
                                                      "mensagem": "Lotufo: CND Federal sem validade hoje"}]
    monkeypatch.setattr(protocolo, "_pendencias_envio", muda_na_segunda)
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d, confirmadas=d["pendencias"]))
    det = r.json()["detail"]
    assert r.status_code == 422 and det["codigo"] == "CONFIRMAR_PENDENCIAS" and len(chamadas) == 2
    assert "Lotufo: CND Federal sem validade hoje" in det["pendencias"]
    assert c.execute("SELECT envio_reservado_em FROM protocolos WHERE id=?", (pid,)).fetchone()[0] is None
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0 and _confirmacoes(c) == []


def test_bloqueio_continua_recusando_mesmo_com_confirmacao(api):
    """Issue #213: bloqueio (certidao vencida, FRC recusada...) nao vira aviso: confirmar nao o contorna."""
    cl, c, ids = api
    _validade(c, "federal", "2026-09-10")
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"],
                                                    "medicao_ids": [ids["sinfra_exec"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    assert d["bloqueio"]
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d, confirmadas=d["pendencias"]))
    assert r.status_code == 409, r.text
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0 and _confirmacoes(c) == []


# --- issue #230: o registro por fora tambem pede a confirmacao do que falta ---------------------------

def _sem_nota(c, mid):
    """A medicao fica sem a nota fiscal anexada: o item "Notas fiscais" do envio vira "falta"."""
    c.execute("DELETE FROM medicao_documentos WHERE medicao_id=? AND tipo_doc='nfs'", (mid,))
    c.commit()


def _fora(cl, mid, confirmadas=None, observacao="Pelo Outlook, ao fiscal do contrato", eml=None):
    data = {"medicao_ids": [str(mid)], "enviado_em": "2026-09-15", "observacao": observacao}
    if confirmadas is not None:
        data["confirmadas"] = confirmadas
    return cl.post("/api/notas/envio-externo", data=data,
                   files={"eml": ("envio.eml", eml, "message/rfc822")} if eml else None)


def _confirmacoes_fora(c) -> list[tuple]:
    return [(r[0], int(r[1]), json.loads(r[2])["pendencias"]) for r in c.execute(
        "SELECT usuario_id, entidade_id, depois FROM audit_log WHERE acao='protocolo.envio_confirmado' "
        "AND entidade='medicao' ORDER BY id")]


def test_registro_por_fora_com_documento_faltando_sem_confirmacao_e_recusado(api):
    """Issue #230: falta a nota e a certidao venceu; sem a confirmacao do aviso nada e' registrado nem gravado."""
    cl, c, ids = api
    mid = ids["mtpar_exec"]
    _sem_nota(c, mid)
    _validade(c, "federal", "2026-09-10")
    antes = _evidencias()
    r = _fora(cl, mid, eml=EML)
    det = r.json()["detail"]
    assert r.status_code == 422 and det["codigo"] == "CONFIRMAR_PENDENCIAS", r.text
    assert det["mensagem"].startswith("ATENÇÃO: falta documento neste envio")
    assert det["mensagem"].endswith("Confirme para continuar com o registro do envio")
    assert len(det["pendencias"]) == 2
    assert any(p.startswith("Notas fiscais (0)") for p in det["pendencias"])
    assert any("federal vencida em 10/09" in p for p in det["pendencias"])
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (mid,)).fetchone()[0] == "nota_emitida"
    _sem_registro(c, mid)
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE acao IN ('notas.envio_externo', "
                     "'protocolo.envio_confirmado')").fetchone()[0] == 0
    assert _evidencias() == antes


def test_registro_por_fora_confirmado_grava_a_lista_e_junta_observacao_e_lista(api, monkeypatch):
    """Issue #230: "Continuar com o registro" manda a lista (em qualquer ordem); a confirmacao vai na auditoria
    (`protocolo.envio_confirmado`) e a ressalva e' "<observacao>; <lista>". Registro por fora nao ganha bloqueio novo:
    a certidao vencida so' entra na lista."""
    cl, c, ids = api
    mid = ids["mtpar_exec"]
    _sem_nota(c, mid)
    _validade(c, "federal", "2026-09-10")
    lista = _fora(cl, mid).json()["detail"]["pendencias"]
    original, recebidas = medicoes.registrar_protocolo, []

    def espia(*a, **k):
        recebidas.append(k.get("justificativa"))
        return original(*a, **k)
    monkeypatch.setattr(medicoes, "registrar_protocolo", espia)
    r = _fora(cl, mid, confirmadas=list(reversed(lista)))
    assert r.status_code == 200, r.text
    assert c.execute("SELECT estado, envio_externo_obs FROM medicoes WHERE id=?", (mid,)).fetchone()[:] == \
        ("protocolada", "Pelo Outlook, ao fiscal do contrato")
    uid = c.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0]
    assert _confirmacoes_fora(c) == [(uid, mid, lista)]
    assert recebidas == ["Envio feito por fora: Pelo Outlook, ao fiscal do contrato; "
                         + protocolo.CONFIRMADO_COM_FALTA + "; ".join(lista)]
    depois = json.loads(c.execute("SELECT depois FROM audit_log WHERE acao='notas.envio_externo'").fetchone()[0])
    assert depois["confirmadas"] == lista and depois["observacao"] == "Pelo Outlook, ao fiscal do contrato"


def test_ressalva_do_registro_confirmado_fica_gravada_mesmo_com_certidoes_em_dia(api):
    """Revisor adversarial da PR #237: so' a nota falta e as certidoes estao em dia; o registro do protocolo da medicao
    nao grava a justificativa nesse caso (o checklist nao acha pendencia), entao a ressalva "<observacao>; <lista>"
    tem de ficar na auditoria do registro por fora."""
    cl, c, ids = api
    mid = ids["mtpar_exec"]
    _sem_nota(c, mid)
    lista = _fora(cl, mid).json()["detail"]["pendencias"]
    assert lista and all("vencida" not in x for x in lista)
    assert _fora(cl, mid, confirmadas=lista).status_code == 200
    depois = json.loads(c.execute("SELECT depois FROM audit_log WHERE acao='notas.envio_externo'").fetchone()[0])
    assert depois["ressalva"] == ("Pelo Outlook, ao fiscal do contrato; " + protocolo.CONFIRMADO_COM_FALTA
                                  + "; ".join(lista))


def test_registro_por_fora_sem_nada_faltando_nao_pede_nem_grava_confirmacao(api, monkeypatch):
    cl, c, ids = api
    original, recebidas = medicoes.registrar_protocolo, []

    def espia(*a, **k):
        recebidas.append(k.get("justificativa"))
        return original(*a, **k)
    monkeypatch.setattr(medicoes, "registrar_protocolo", espia)
    r = _fora(cl, ids["mtpar_exec"], confirmadas=["Notas fiscais (0): confirmada antes"])
    assert r.status_code == 200, r.text
    assert _confirmacoes_fora(c) == [] and recebidas == ["Envio feito por fora: Pelo Outlook, ao fiscal do contrato"]
    depois = json.loads(c.execute("SELECT depois FROM audit_log WHERE acao='notas.envio_externo'").fetchone()[0])
    assert "confirmadas" not in depois


def test_registro_por_fora_continua_exigindo_a_observacao_mesmo_confirmado(api):
    cl, c, ids = api
    mid = ids["mtpar_exec"]
    _sem_nota(c, mid)
    lista = _fora(cl, mid).json()["detail"]["pendencias"]
    r = _fora(cl, mid, confirmadas=lista, observacao="  ")
    assert r.status_code == 422 and "observação" in r.json()["detail"]
    _sem_registro(c, mid)


def test_registro_por_fora_com_lista_diferente_da_confirmada_e_recusado(api):
    cl, c, ids = api
    mid = ids["mtpar_exec"]
    _sem_nota(c, mid)
    lista = _fora(cl, mid).json()["detail"]["pendencias"]
    for outra in ([*lista, "Certidões Lotufo (5): federal vencida em 10/09"], ["Outra coisa"]):
        r = _fora(cl, mid, confirmadas=outra)
        det = r.json()["detail"]
        assert r.status_code == 422 and det["codigo"] == "CONFIRMAR_PENDENCIAS", r.text
        assert "mudou" in det["mensagem"] and det["pendencias"] == lista
    _sem_registro(c, mid)
    assert _confirmacoes_fora(c) == []


def test_registro_por_fora_confere_a_lista_de_novo_sob_o_lock(api, monkeypatch):
    """Issue #230: a lista e' lida de novo dentro da transacao. A que surgiu depois da confirmacao recusa sem gravar;
    a que se resolveu nao entra na auditoria nem na ressalva (vale a lista lida sob o lock, nao a de antes)."""
    cl, c, ids = api
    mid = ids["mtpar_exec"]
    _sem_nota(c, mid)
    lista = _fora(cl, mid).json()["detail"]["pendencias"]
    original = notas_envio.faltas_externo
    extra = {"codigo": "certidoes", "mensagem": "Certidões Lotufo (5): federal vencida em 10/09"}
    registrar, recebidas = medicoes.registrar_protocolo, []

    def espia(*a, **k):
        recebidas.append(k.get("justificativa"))
        return registrar(*a, **k)
    monkeypatch.setattr(medicoes, "registrar_protocolo", espia)
    for troca in ("surge", "resolve"):
        chamadas = []

        def na_segunda(*a, **k):
            chamadas.append(1)
            out = original(*a, **k)
            if len(chamadas) == 1:
                return out
            return [*out, extra] if troca == "surge" else []
        monkeypatch.setattr(notas_envio, "faltas_externo", na_segunda)
        r = _fora(cl, mid, confirmadas=lista)
        assert len(chamadas) == 2
        if troca == "surge":
            det = r.json()["detail"]
            assert r.status_code == 422 and det["codigo"] == "CONFIRMAR_PENDENCIAS", r.text
            assert extra["mensagem"] in det["pendencias"]
            _sem_registro(c, mid)
            assert _confirmacoes_fora(c) == []
        else:
            assert r.status_code == 200, r.text
            assert _confirmacoes_fora(c) == []
            depois = json.loads(c.execute("SELECT depois FROM audit_log WHERE acao='notas.envio_externo'").fetchone()[0])
            assert "confirmadas" not in depois
            assert recebidas == ["Envio feito por fora: Pelo Outlook, ao fiscal do contrato"]


def test_registro_por_fora_limita_a_lista_confirmada(api):
    cl, c, ids = api
    mid = ids["mtpar_exec"]
    assert _fora(cl, mid, confirmadas=["x" * 2001]).status_code == 422
    assert _fora(cl, mid, confirmadas=[f"item {i}" for i in range(201)]).status_code == 422
    _sem_registro(c, mid)


# --- testes de quebra 10/10/2026: A-13 (link de qualquer site) e A-11 (qualquer arquivo como .eml) ---

def test_link_so_do_onedrive_ou_sharepoint_da_lotufo(api, monkeypatch):
    cl, c, ids = api
    monkeypatch.setenv("DASH_SHAREPOINT_HOSTS", "exemplo-my.sharepoint.com,exemplo.sharepoint.com")
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"], "medicao_ids": [
        ids["sinfra_exec"], ids["sinfra_reaj"]]}).json()["protocolo_id"]
    for url in ("https://exemplo-malicioso.test/x", "https://exemplo-my.sharepoint.com.evil.test/abcdef"):
        r = cl.post(f"/api/protocolos/{pid}/links", json={"nome": "Planilha", "url": url})
        assert r.status_code == 422, url
        assert "exemplo-my.sharepoint.com ou exemplo.sharepoint.com" in r.json()["detail"]
    r = cl.post(f"/api/protocolos/{pid}/links", json={"nome": "Planilha",
                                                      "url": "https://exemplo-my.sharepoint.com/:b:/g/abc"})
    assert r.status_code == 200, r.text
    corpo = cl.get(f"/api/notas/envio/{pid}").json()["previa"]["corpo"]
    assert "exemplo-malicioso" not in corpo and "evil.test" not in corpo


PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x04\x00\x00\x00\x01\x08\x02\x00\x00\x00"


def _evidencias():
    return sorted(arquivos.pasta("evidencias").glob("*"))


def test_envio_por_fora_recusa_arquivo_que_nao_e_email(api):
    cl, c, ids = api
    antes = _evidencias()
    r = cl.post("/api/notas/envio-externo",
                data={"medicao_ids": [str(ids["mtpar_exec"])], "enviado_em": "2026-09-15",
                      "observacao": "Enviado pela Maria do Outlook dela"},
                files={"eml": ("imagem.eml", PNG, "message/rfc822")})
    assert r.status_code == 422
    assert r.json()["detail"].startswith("O arquivo não é um e-mail salvo (.eml)")
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["mtpar_exec"],)).fetchone()[0] == "nota_emitida"
    assert c.execute("SELECT COUNT(*) FROM medicao_documentos WHERE tipo_doc='evidencia_orgao'").fetchone()[0] == 0
    assert _evidencias() == antes


def test_envio_por_fora_aceita_eml_minimo(api):
    cl, c, ids = api
    eml = (b"From: Maria <maria@exemplo.com.br>\r\nTo: protocolo@orgao-b.exemplo.com.br\r\n"
           b"Date: Tue, 15 Sep 2026 10:00:00 -0400\r\nSubject: CT/361\r\n\r\nSegue a nota.\r\n")
    r = cl.post("/api/notas/envio-externo",
                data={"medicao_ids": [str(ids["mtpar_exec"])], "enviado_em": "2026-09-15",
                      "observacao": "Enviado pela Maria do Outlook dela"},
                files={"eml": ("envio.eml", eml, "message/rfc822")})
    assert r.status_code == 200, r.text
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["mtpar_exec"],)).fetchone()[0] == "protocolada"


def test_envio_por_fora_recusa_texto_com_from_e_date_escritos_a_mao(api):
    """Gate Sol S3 (10/10/2026): 'From: x' e 'Date: y' digitados num .txt nao fazem um e-mail."""
    cl, c, ids = api
    r = cl.post("/api/notas/envio-externo",
                data={"medicao_ids": [str(ids["mtpar_exec"])], "enviado_em": "2026-09-15",
                      "observacao": "Enviado pela Maria do Outlook dela"},
                files={"eml": ("anotacao.eml", b"From: x\nDate: y\n\nqualquer coisa", "message/rfc822")})
    assert r.status_code == 422 and r.json()["detail"].startswith("O arquivo não é um e-mail salvo (.eml)")
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["mtpar_exec"],)).fetchone()[0] == "nota_emitida"


# --- issue #180: falha depois de gravar o .eml nao deixa arquivo orfao em evidencias ---

class _ConexaoQueFalhaNoCommit:
    """Repassa tudo para a conexao de verdade, mas o COMMIT falha (disco cheio, fsync travado)."""

    def __init__(self, conn):
        self._conn = conn

    def commit(self):
        raise OSError("disco cheio")

    def __getattr__(self, nome):
        return getattr(self._conn, nome)


def _par_sinfra(ids):
    return [ids["sinfra_exec"], ids["sinfra_reaj"]]


def _falhar_no_segundo_protocolo(monkeypatch):
    from app import medicoes
    original, chamadas = medicoes.registrar_protocolo, []

    def registrar(*a, **k):
        chamadas.append(1)
        if len(chamadas) == 2:
            raise OSError("erro de disco no segundo protocolo")
        return original(*a, **k)
    monkeypatch.setattr(medicoes, "registrar_protocolo", registrar)


def _nada_registrado(c, ids):
    for mid in _par_sinfra(ids):
        _sem_registro(c, mid)
        assert c.execute("SELECT estado FROM medicoes WHERE id=?", (mid,)).fetchone()[0] == "nota_emitida"
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE acao='notas.envio_externo'").fetchone()[0] == 0


def test_falha_no_segundo_protocolo_nao_deixa_eml_orfao(svc, monkeypatch):
    c, ids = svc
    antes = _evidencias()
    _falhar_no_segundo_protocolo(monkeypatch)
    with pytest.raises(OSError):
        notas_envio.envio_externo(c, ids["uid"], _par_sinfra(ids), "2026-09-15", "Pelo Outlook", ("envio.eml", EML))
    _nada_registrado(c, ids)
    assert _evidencias() == antes


def test_falha_no_commit_nao_deixa_eml_orfao(svc):
    c, ids = svc
    antes = _evidencias()
    with pytest.raises(OSError):
        notas_envio.envio_externo(_ConexaoQueFalhaNoCommit(c), ids["uid"], _par_sinfra(ids), "2026-09-15",
                                  "Pelo Outlook", ("envio.eml", EML))
    _nada_registrado(c, ids)
    assert _evidencias() == antes


def test_falha_depois_da_gravacao_nao_apaga_eml_que_ja_existia(svc, monkeypatch):
    """O mesmo .eml (mesmo hash) ja' estava guardado: a falha desfaz o banco e o arquivo continua no lugar."""
    c, ids = svc
    rel, _ = arquivos.gravar_bytes("evidencias", EML, "eml")
    antes = _evidencias()
    _falhar_no_segundo_protocolo(monkeypatch)
    with pytest.raises(OSError):
        notas_envio.envio_externo(c, ids["uid"], _par_sinfra(ids), "2026-09-15", "Pelo Outlook", ("envio.eml", EML))
    _nada_registrado(c, ids)
    assert _evidencias() == antes and arquivos.caminho_seguro(rel).read_bytes() == EML


class _ConexaoQuePerdeOLockNoRollback:
    """Gate Sol S1 (PR #199): logo depois do ROLLBACK, outro escritor pega o lock e o segura alem do busy_timeout."""

    def __init__(self, conn, outro):
        self._conn, self._outro = conn, outro

    def rollback(self):
        self._conn.rollback()
        if not self._outro.in_transaction:
            self._outro.execute("BEGIN IMMEDIATE")

    def __getattr__(self, nome):
        return getattr(self._conn, nome)


def test_falha_no_registro_limpa_o_eml_ainda_sob_o_lock(svc, monkeypatch):
    """Gate Sol S1 (PR #199): a limpeza nao depende de pegar o lock de novo; outro escritor segurando o banco depois
    do ROLLBACK nao deixa o .eml orfao."""
    c, ids = svc
    antes = _evidencias()
    _falhar_no_segundo_protocolo(monkeypatch)
    outro = db.get_conn()
    c.execute("PRAGMA busy_timeout=50")
    try:
        with pytest.raises(OSError):
            notas_envio.envio_externo(_ConexaoQuePerdeOLockNoRollback(c, outro), ids["uid"], _par_sinfra(ids),
                                      "2026-09-15", "Pelo Outlook", ("envio.eml", EML))
        assert outro.in_transaction                     # o lock ficou mesmo com o outro escritor
    finally:
        outro.rollback(); outro.close()
        c.execute("PRAGMA busy_timeout=5000")
    _nada_registrado(c, ids)
    assert _evidencias() == antes


def test_limpeza_do_eml_nao_apaga_arquivo_que_outro_registro_cita(svc):
    """Outro registro com o mesmo .eml entrou entre o ROLLBACK e a limpeza: a linha dele cita o arquivo, que fica.
    Chamada dentro de um envelope de fora, a limpeza nao fecha a transacao dele."""
    c, ids = svc
    rel, sha = arquivos.gravar_bytes("evidencias", EML, "eml")
    with db.mutacao(c):
        c.execute("INSERT INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, item_id, arquivo, sha256, tamanho) "
                  "VALUES (?,'operacao','evidencia_orgao','envio.eml',?,?,?,?)", (ids["vg_exec"], sha, rel, sha, len(EML)))
        notas_envio._remover_eml_sem_registro(c, rel)
        assert c.in_transaction
    assert arquivos.caminho_seguro(rel).exists()
    c.execute("DELETE FROM medicao_documentos WHERE arquivo=?", (rel,)); c.commit()
    notas_envio._remover_eml_sem_registro(c, rel)
    assert not arquivos.caminho_seguro(rel).exists()


def test_gravar_bytes_que_falha_nao_deixa_temporario(svc, monkeypatch):
    """Disco cheio no meio da gravacao: nem o .eml nem o temporario ficam em evidencias."""
    import os

    def falhar(*a):
        raise OSError("disco cheio")
    antes = _evidencias()
    monkeypatch.setattr(os, "replace", falhar)
    with pytest.raises(OSError):
        arquivos.gravar_bytes("evidencias", EML, "eml")
    assert _evidencias() == antes


# --- testes de quebra 10/10/2026, A-15: numero do orgao vazio nao apaga o gravado ---

def _numero(cl, mid):
    return next(a for a in cl.get("/api/notas/aguardando-pagamento").json() if a["medicao_id"] == mid)["numero_orgao"]


def test_numero_do_orgao_vazio_nao_apaga_no_envio_pelo_sistema(api):
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"], "medicao_ids": [
        ids["sinfra_exec"], ids["sinfra_reaj"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    assert cl.post(f"/api/notas/envio/{pid}/enviar",
                   json=_corpo(d)).status_code == 200
    mid = ids["sinfra_exec"]
    assert cl.post(f"/api/notas/{mid}/numero-orgao", json={"numero": "X-1"}).status_code == 200
    for vazio in ("", "   "):
        r = cl.post(f"/api/notas/{mid}/numero-orgao", json={"numero": vazio})
        assert r.status_code == 422 and r.json()["detail"] == "Informe o número do protocolo no órgão"
        r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": vazio})
        assert r.status_code == 422 and r.json()["detail"] == "Informe o número do protocolo no órgão"
    assert _numero(cl, mid) == "X-1"


def test_numero_do_orgao_vazio_nao_apaga_no_envio_por_fora(api):
    cl, c, ids = api
    mid = ids["mtpar_exec"]
    assert cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(mid)], "enviado_em": "2026-09-15",
                                                     "observacao": "Enviado pela Maria do Outlook dela"}).status_code == 200
    assert cl.post(f"/api/notas/{mid}/numero-orgao", json={"numero": "X-1"}).status_code == 200
    r = cl.post(f"/api/notas/{mid}/numero-orgao", json={"numero": ""})
    assert r.status_code == 422 and r.json()["detail"] == "Informe o número do protocolo no órgão"
    assert _numero(cl, mid) == "X-1"


def _enviar_sinfra(cl, ids):
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"], "medicao_ids": [
        ids["sinfra_exec"], ids["sinfra_reaj"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    assert cl.post(f"/api/notas/envio/{pid}/enviar",
                   json=_corpo(d)).status_code == 200
    return pid


def test_comprovante_sozinho_mantem_o_numero_ja_gravado(api):
    """Gate Sol S1 (10/10/2026): numero vazio + comprovante, com numero ja' gravado, salva so' o comprovante."""
    cl, c, ids = api
    pid = _enviar_sinfra(cl, ids)
    assert cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1"}).status_code == 200
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": ""},
                files={"comprovante": ("comprovante.pdf", _pdf("comprovante"), "application/pdf")})
    assert r.status_code == 200, r.text
    p = c.execute("SELECT numero_orgao, comprovante_arquivo FROM protocolos WHERE id=?", (pid,)).fetchone()
    assert p["numero_orgao"] == "X-1" and p["comprovante_arquivo"]


def test_comprovante_sem_numero_na_primeira_vez_e_recusado(api):
    """Gate Sol S1: sem numero gravado, o comprovante sozinho nao basta; nada vai para o disco nem para o banco."""
    cl, c, ids = api
    pid = _enviar_sinfra(cl, ids)
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": " "},
                files={"comprovante": ("comprovante.pdf", _pdf("comprovante"), "application/pdf")})
    assert r.status_code == 422 and r.json()["detail"] == "Informe o número do protocolo junto com o comprovante"
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": ""})
    assert r.status_code == 422 and r.json()["detail"] == "Informe o número do protocolo no órgão"
    p = c.execute("SELECT numero_orgao, comprovante_arquivo FROM protocolos WHERE id=?", (pid,)).fetchone()
    assert p["numero_orgao"] is None and p["comprovante_arquivo"] is None


def test_comprovante_gravado_baixa_pela_rota_do_protocolo(api):
    """Issue #2: a tela baixa o comprovante pela rota; sem comprovante, 404."""
    cl, c, ids = api
    pid = _enviar_sinfra(cl, ids)
    assert cl.get(f"/api/protocolos/{pid}/comprovante").status_code == 404
    pdf = _pdf("comprovante do orgao")
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1"},
                files={"comprovante": ("comprovante.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["comprovante_arquivo"]                               # a tela decide o link por aqui
    b = cl.get(f"/api/protocolos/{pid}/comprovante")
    assert b.status_code == 200 and b.headers["content-type"] == "application/pdf" and b.content == pdf


def test_trocar_o_comprovante_guarda_o_anterior_na_auditoria(api):
    """Revisao da issue #2: a tela oferece 'Trocar'; o log precisa dizer qual PDF foi substituido."""
    cl, c, ids = api
    pid = _enviar_sinfra(cl, ids)
    files = lambda t: {"comprovante": ("c.pdf", _pdf(t), "application/pdf")}          # noqa: E731
    p1 = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1"}, files=files("um")).json()["comprovante_arquivo"]
    p2 = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": ""}, files=files("dois")).json()["comprovante_arquivo"]
    assert p1 != p2
    a = c.execute("SELECT antes, depois FROM audit_log WHERE acao='protocolo.numero_orgao' AND entidade_id=? "
                  "ORDER BY id DESC LIMIT 1", (str(pid),)).fetchone()
    assert json.loads(a["antes"])["comprovante"] == p1 and json.loads(a["depois"])["comprovante"] == p2


def test_comprovante_que_nao_e_pdf_ou_passa_do_limite_e_recusado_em_portugues(api):
    cl, c, ids = api
    pid = _enviar_sinfra(cl, ids)
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1"},
                files={"comprovante": ("c.png", b"\x89PNG\r\n", "image/png")})
    assert r.status_code == 415 and r.json()["detail"].startswith("Envie um PDF")
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1"},
                files={"comprovante": ("c.pdf", b"nao e pdf", "application/pdf")})
    assert r.status_code == 415 and "não é um PDF" in r.json()["detail"]
    grande = b"%PDF-1.4\n" + b"0" * arquivos.TETO_BYTES
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "X-1"},
                files={"comprovante": ("c.pdf", grande, "application/pdf")})
    assert r.status_code == 413 and r.json()["detail"] == "Arquivo acima do limite de 10 MB"
    p = c.execute("SELECT numero_orgao, comprovante_arquivo FROM protocolos WHERE id=?", (pid,)).fetchone()
    assert p["numero_orgao"] is None and p["comprovante_arquivo"] is None


# --- issue #100: os anexos da previa conferidos tambem no Enviar a nota ------------------------------

def test_nf_anexada_depois_da_previa_recusa_o_envio_da_nota_sem_reservar(api, tmp_path):
    """Revisor adversarial na PR #92: a tela Enviar a nota manda os anexos que a pessoa viu; NF anexada a' medicao
    com a previa aberta faz o servidor recusar antes de reservar, com a mesma mensagem do protocolo."""
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"], "medicao_ids": [
        ids["sinfra_exec"], ids["sinfra_reaj"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    vistos = [{"nome": a["nome"], "tamanho": a["tamanho"]} for a in d["previa"]["anexos"]]
    assert vistos
    rel, sha = arquivos.gravar_bytes("notas", _pdf("FRC ASSINADA"), "pdf")
    c.execute("INSERT INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, numero_nf, item_id, arquivo, sha256, "
              "tamanho) VALUES (?,?,?,?,?,?,?,?,?)",
              (ids["sinfra_exec"], "operacao", "fatura", "FRC 77.pdf", "77", f"pdf:{sha}", rel, sha, 10))
    c.commit()
    assert len(cl.get(f"/api/notas/envio/{pid}").json()["previa"]["anexos"]) == len(vistos) + 1
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d, anexos=vistos))
    assert r.status_code == 422, r.text
    # gate Sol S2 (PR #141): a recusa traz `codigo`, para a tela recarregar so' nela e nao em qualquer erro
    assert r.json()["detail"] == {"codigo": "ANEXOS_MUDARAM", "mensagem": (
        "Os anexos mudaram depois da prévia: descarte esta prévia e abra outra para conferir o que vai no e-mail")}
    p = c.execute("SELECT situacao, envio_id, envio_reservado_em FROM protocolos WHERE id=?", (pid,)).fetchone()
    assert tuple(p) == ("rascunho", None, None)
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    assert not list((tmp_path / "sim").glob("enviados/*.json"))
    # a previa nova (com a FRC) envia
    d = cl.get(f"/api/notas/envio/{pid}").json()
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d))
    assert r.status_code == 200, r.text


def test_envio_da_nota_sem_os_anexos_da_previa_e_recusado(api):
    """Revisor adversarial na PR #141: sem a lista (aba aberta antes do deploy, chamada direta) nao envia sem conferir."""
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"], "medicao_ids": [
        ids["sinfra_exec"], ids["sinfra_reaj"]]}).json()["protocolo_id"]
    corpo = _corpo(cl.get(f"/api/notas/envio/{pid}").json())
    del corpo["anexos"]
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json=corpo)
    assert r.status_code == 422 and r.json()["detail"][0]["loc"] == ["body", "anexos"]
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0


def test_envio_da_nota_por_dentro_exige_os_anexos_da_previa(svc):
    """Gate Sol S1 (PR #141): chamador interno sem a lista (ou com None) nao envia sem conferir nem reserva."""
    c, ids = svc
    pid = notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_exec"], ids["sinfra_reaj"]])
    pv = protocolo.previa_envio(c, [pid], hoje=HOJE)
    args = (c, ids["usuario"], pid, pv["para"], pv["copia"], pv["assunto"], pv["corpo"], None)
    with pytest.raises(TypeError):
        notas_envio.enviar(*args)                                   # anexos_previa e' obrigatorio, so' por nome
    with pytest.raises(ValueError, match="anexos da prévia"):
        notas_envio.enviar(*args, anexos_previa=None)
    p = c.execute("SELECT situacao, envio_id, envio_reservado_em FROM protocolos WHERE id=?", (pid,)).fetchone()
    assert tuple(p) == ("rascunho", None, None)
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0


def test_corpo_formatado_da_nota_sai_sanitizado(api, tmp_path):
    """Issue #191: o HTML do editor passa pela lista fechada antes de ir ao orgao."""
    from tests.test_html_email import LIMPO, PERIGOSO, corpo_enviado
    cl, c, ids = api
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"],
                                                    "medicao_ids": [ids["sinfra_exec"], ids["sinfra_reaj"]]}
                  ).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    r = cl.post(f"/api/notas/envio/{pid}/enviar", json={**_corpo(d), "corpo": PERIGOSO})
    assert r.status_code == 200, r.text
    assert corpo_enviado(tmp_path / "sim") == LIMPO


# --- issue #188: medicao e reajuste da mesma competencia, a espera fica na tela e no envio (opcao A) ---------------

def _sem_notas(c, mid, estado="espelho_enviado"):
    c.execute("UPDATE medicoes SET estado=?, nota_emitida_em=NULL WHERE id=?", (estado, mid))
    c.commit()


def test_sinfra_execucao_espera_as_notas_do_reajuste_e_depois_sai_com_as_duas(svc):
    c, ids = svc
    _sem_notas(c, ids["sinfra_reaj"])
    sinfra, = _por_contrato(notas_envio.a_enviar(c, HOJE), ids["sinfra"])
    assert sinfra["medicao_ids"] == [ids["sinfra_exec"]]
    assert sinfra["situacao"] == "esperando" and sinfra["aviso"].startswith("Esperando as notas do reajuste")
    assert sinfra["espera"] == {"medicao_id": ids["sinfra_reaj"], "titulo": "Reajuste da 23ª Medição",
                                "tipo": "reajuste", "texto": "esperando as notas do reajuste"}
    with pytest.raises(ValueError, match="23ª Medição está esperando as notas do reajuste: na SINFRA"):
        notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_exec"]])
    # o estado gravado nao muda (opcao A): a execucao segue em nota emitida, com a data das notas dela
    assert tuple(c.execute("SELECT estado, nota_emitida_em FROM medicoes WHERE id=?", (ids["sinfra_exec"],)
                           ).fetchone()) == ("nota_emitida", "2026-09-15")
    # chegaram as notas do reajuste: um envio com as duas
    c.execute("UPDATE medicoes SET estado='nota_emitida', nota_emitida_em='2026-09-16' WHERE id=?", (ids["sinfra_reaj"],))
    c.commit()
    sinfra, = _por_contrato(notas_envio.a_enviar(c, HOJE), ids["sinfra"])
    assert sinfra["medicao_ids"] == [ids["sinfra_exec"], ids["sinfra_reaj"]]
    assert sinfra["situacao"] == "pronto" and sinfra["espera"] is None
    assert notas_envio.iniciar(c, ids["uid"], ids["sinfra"], sinfra["medicao_ids"])


def test_reajuste_pronto_espera_as_notas_da_medicao_na_vg(svc):
    c, ids = svc
    _sem_notas(c, ids["vg_exec"], "prevista")
    vg, = _por_contrato(notas_envio.a_enviar(c, HOJE), ids["vg"])
    assert vg["situacao"] == "esperando" and vg["espera"]["texto"] == "esperando as notas da medição"
    with pytest.raises(ValueError, match="na Pref. VG"):
        notas_envio.iniciar(c, ids["uid"], ids["vg"], [ids["vg_reaj"]], "254")


def test_outra_metade_cancelada_ou_desistida_libera_sem_justificativa(svc):
    c, ids = svc
    for estado in ("cancelada", "desistida"):
        _sem_notas(c, ids["sinfra_reaj"], estado)
        sinfra, = _por_contrato(notas_envio.a_enviar(c, HOJE), ids["sinfra"])
        assert sinfra["situacao"] == "pronto" and sinfra["espera"] is None
    assert notas_envio.iniciar(c, ids["uid"], ids["sinfra"], [ids["sinfra_exec"]])


def test_orgao_que_separa_nao_espera(svc):
    c, ids = svc
    _sem_notas(c, ids["mtpar_reaj"])
    mtpar, = _por_contrato(notas_envio.a_enviar(c, HOJE), ids["mtpar"])
    assert mtpar["medicao_ids"] == [ids["mtpar_exec"]] and mtpar["situacao"] == "pronto" and mtpar["espera"] is None
    assert notas_envio.iniciar(c, ids["uid"], ids["mtpar"], [ids["mtpar_exec"]], "361")
    p = notas_envio.par(c, ids["mtpar_exec"])
    assert p["junta"] is False and [x["tipo"] for x in p["metades"]] == ["execucao", "reajuste"]


def test_saida_de_emergencia_pede_justificativa_e_libera_so_a_medicao_pronta(api):
    cl, c, ids = api
    _sem_notas(c, ids["sinfra_reaj"])
    rota = f"/api/medicoes/{ids['sinfra_exec']}/envio-sem-a-outra"
    r = cl.post(rota, json={"justificativa": "urgente"})
    assert r.status_code == 422 and "ao menos 10 caracteres" in r.json()["detail"]
    r = cl.post(f"/api/medicoes/{ids['sinfra_reaj']}/envio-sem-a-outra",
                json={"justificativa": "notas do reajuste presas no faturamento"})
    assert r.status_code == 422 and r.json()["detail"] == ("Reajuste da 23ª Medição não está com a nota emitida "
                                                           "(está com espelho enviado)")
    r = cl.post(rota, json={"justificativa": "notas do reajuste presas no faturamento"})
    assert r.status_code == 200, r.text
    assert cl.post(rota, json={"justificativa": "de novo, outra justificativa"}).status_code == 422   # ja' liberada
    aud = c.execute("SELECT entidade, entidade_id, depois FROM audit_log WHERE acao='notas.envio_sem_a_outra_metade'"
                    ).fetchall()
    assert len(aud) == 1 and aud[0][0] == "medicao" and aud[0][1] == str(ids["sinfra_exec"])
    assert json.loads(aud[0][2]) == {"justificativa": "notas do reajuste presas no faturamento",
                                     "outra_medicao_id": ids["sinfra_reaj"]}
    sinfra, = _por_contrato(cl.get("/api/notas/a-enviar").json(), ids["sinfra"])
    assert sinfra["situacao"] == "pronto" and sinfra["medicao_ids"] == [ids["sinfra_exec"]]
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"],
                                                    "medicao_ids": [ids["sinfra_exec"]]}).json()["protocolo_id"]
    d = cl.get(f"/api/notas/envio/{pid}").json()
    assert cl.post(f"/api/notas/envio/{pid}/enviar", json=_corpo(d)).status_code == 200
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["sinfra_exec"],)).fetchone()[0] == "protocolada"
    # a outra metade segue depois, num envio proprio
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["sinfra_reaj"],)).fetchone()[0] == "espelho_enviado"


def test_saida_de_emergencia_so_para_quem_espera(api):
    cl, c, ids = api
    r = cl.post(f"/api/medicoes/{ids['mtpar_exec']}/envio-sem-a-outra",
                json={"justificativa": "notas do reajuste presas no faturamento"})
    assert r.status_code == 422 and "não está esperando" in r.json()["detail"]


def test_registro_por_fora_tambem_espera(api):
    cl, c, ids = api
    _sem_notas(c, ids["sinfra_reaj"])
    r = cl.post("/api/notas/envio-externo", data={"medicao_ids": [str(ids["sinfra_exec"])], "enviado_em": "2026-09-15",
                                                 "observacao": "Pelo Outlook"})
    assert r.status_code == 422 and "esperando as notas do reajuste" in r.json()["detail"]
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["sinfra_exec"],)).fetchone()[0] == "nota_emitida"


def test_protocolo_registrado_a_mao_tambem_espera(api):
    """Revisor R2 / Sol S1 (rodada 1 da #188): POST /api/medicoes/{id}/protocolo nao contorna a espera."""
    cl, c, ids = api
    _sem_notas(c, ids["sinfra_reaj"])
    corpo = {"data": "2026-09-15", "numero_oficio": "LT 1/2026", "apesar_das_pendencias": True,
             "justificativa": "protocolado no balcão do órgão"}
    r = cl.post(f"/api/medicoes/{ids['sinfra_exec']}/protocolo", json=corpo)
    assert r.status_code == 422 and "esperando as notas do reajuste" in r.json()["detail"]
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["sinfra_exec"],)).fetchone()[0] == "nota_emitida"
    assert c.execute("SELECT COUNT(*) FROM medicao_protocolos WHERE medicao_id=?", (ids["sinfra_exec"],)).fetchone()[0] == 0
    # orgao que separa: o registro a mao segue como antes
    _sem_notas(c, ids["mtpar_reaj"])
    assert cl.post(f"/api/medicoes/{ids['mtpar_exec']}/protocolo", json=corpo).status_code == 201


def test_rascunho_montado_antes_da_espera_nao_envia(svc):
    """O protocolo criado antes (ou por outro caminho) tambem espera: o envio recusa antes de reservar."""
    c, ids = svc
    _sem_notas(c, ids["sinfra_reaj"])
    pid = protocolo.criar(c, ids["uid"], ids["sinfra"], "nota", [ids["sinfra_exec"]], None)
    pv = protocolo.previa_envio(c, [pid], hoje=HOJE)
    with pytest.raises(ValueError, match="esperando as notas do reajuste"):
        notas_envio.enviar(c, ids["usuario"], pid, pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                           "reajuste vai no próximo e-mail", anexos_previa=pv["anexos"])
    # a rota generica de protocolos (POST /api/protocolos/envio) passa pelo mesmo protocolo.enviar
    with pytest.raises(ValueError, match="esperando as notas do reajuste"):
        protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                         "reajuste vai no próximo e-mail")
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    p = c.execute("SELECT situacao, envio_reservado_em FROM protocolos WHERE id=?", (pid,)).fetchone()
    assert tuple(p) == ("rascunho", None)                       # nada reservado: a recusa desfez a transacao


def test_par_da_pagina_traz_a_outra_metade_e_a_liberacao(api):
    cl, c, ids = api
    _sem_notas(c, ids["sinfra_reaj"])
    p = cl.get(f"/api/medicoes/{ids['sinfra_reaj']}/par").json()
    assert (p["junta"], p["orgao"]) == (True, "SINFRA")
    exe, rea = p["metades"]
    assert (exe["medicao_id"], exe["tipo"], exe["titulo"], exe["completa"]) == (ids["sinfra_exec"], "execucao",
                                                                                "23ª Medição", True)
    assert (rea["medicao_id"], rea["completa"], rea["espera"], rea["liberacao"]) == (ids["sinfra_reaj"], False, None, None)
    assert rea["esperadas"] == [] and rea["faltam"] == 1      # sem espelho nesta obra: uma nota, nenhuma lida
    assert exe["espera"]["texto"] == "esperando as notas do reajuste" and exe["liberacao"] is None
    cl.post(f"/api/medicoes/{ids['sinfra_exec']}/envio-sem-a-outra",
            json={"justificativa": "notas do reajuste presas no faturamento"})
    exe, _ = cl.get(f"/api/medicoes/{ids['sinfra_exec']}/par").json()["metades"]
    assert exe["espera"] is None and exe["liberacao"]["justificativa"] == "notas do reajuste presas no faturamento"
    assert exe["liberacao"]["por"] and exe["liberacao"]["em"]
    # medicao sem reajuste (nem projeto): a pagina fica com um bloco so'
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) VALUES (?, 24, 'execucao', "
              "'2026-10', 'prevista')", (ids["sinfra"],))
    c.commit()
    sozinha = c.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]
    assert cl.get(f"/api/medicoes/{sozinha}/par").json()["metades"] == []
    assert cl.get("/api/medicoes/999999/par").status_code == 404


# --- issue #169: a FRC assinada do envio e' a da FRC vigente ----------------------------------------

def test_assinada_de_frc_anterior_recusa_o_envio(conn, usuario, consorcio14, _texto, tmp_path, monkeypatch):  # noqa: F811
    """Gate Sol na PR #168: as notas mudam, a FRC e' gerada de novo e a assinada anexada e' a da versao anterior. O
    item nao fica pronto e o servidor recusa o envio (bloqueio, sem justificativa possivel) antes de reservar."""
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    cid, mid = consorcio14
    n = test_frc.ULTIMA + 1
    test_frc._anexar(conn, usuario, mid, _texto, test_frc.NOTAS_FRC)
    conn.execute("UPDATE medicoes SET estado='nota_emitida' WHERE id=?", (mid,))
    conn.commit()
    test_frc._assinar(conn, usuario, mid, _texto, f"FRC {n} assinada.pdf")
    pid = notas_envio.iniciar(conn, usuario["id"], cid, [mid])
    assert notas_envio.detalhe_envio(conn, pid)["bloqueio"] is None
    frc.gerar(conn, usuario, mid, n)                       # FRC gerada de novo: a assinada anexada e' da anterior
    d = notas_envio.detalhe_envio(conn, pid)
    item = next(i for i in d["envio"]["itens"] if i["chave"] == f"frc:{mid}")
    assert item["estado"] == "falta" and d["envio"]["situacao"] == "bloqueado"
    assert "FRC assinada não é a da FRC vigente" in d["envio"]["aviso"]
    assert d["bloqueio"] == (f"14ª Medição: A FRC assinada anexada não é a da FRC nº {n} vigente: baixe a FRC "
                             "gerada, assine no DocuSign e anexe aqui")
    assert not [a for a in d["previa"]["anexos"] if a["origem"] == "frc"]          # a velha nao vai
    pv = protocolo.previa_envio(conn, [pid])
    with pytest.raises(protocolo.Bloqueio, match="não é a da FRC nº"):
        notas_envio.enviar(conn, usuario, pid, pv["para"] or ["orgao@exemplo.com.br"], pv["copia"], pv["assunto"],
                           pv["corpo"], "justificativa longa o bastante para passar", anexos_previa=pv["anexos"])
    p = conn.execute("SELECT situacao, envio_id, envio_reservado_em FROM protocolos WHERE id=?", (pid,)).fetchone()
    assert tuple(p) == ("rascunho", None, None)
    assert conn.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    # a assinada da FRC vigente destrava, e so' ela vai no e-mail
    test_frc._assinar(conn, usuario, mid, _texto, f"FRC {n} assinada de novo.pdf")
    d = notas_envio.detalhe_envio(conn, pid)
    assert d["bloqueio"] is None
    assert [a["nome"] for a in d["previa"]["anexos"] if a["origem"] == "frc"] == [f"FRC {n} assinada de novo.pdf"]


def test_pdf_assinado_da_versao_anterior_com_o_mesmo_numero_e_recusado(conn, usuario, consorcio14, _texto):  # noqa: F811
    """Revisor adversarial na PR #179 (critico 1): baixa a FRC nº N (v1) e assina; troca uma nota; "Gerar de novo"
    faz a v2 com o mesmo nº N. Anexar o PDF assinado da v1 e' recusado (o texto traz a nota velha); o da v2 entra."""
    cid, mid = consorcio14
    n = test_frc.ULTIMA + 1
    test_frc._anexar(conn, usuario, mid, _texto, test_frc.NOTAS_FRC)
    v1 = test_frc._texto_da_frc(conn, mid)
    trocada = ("lotufo", 2290, *test_frc.NOTAS_FRC[2][2:])       # a nota de Cuiaba reemitida com outro numero
    test_frc._anexar(conn, usuario, mid, _texto, [trocada])
    assert frc.situacao(conn, mid)["frc"]["desatualizada"] is True
    frc.gerar(conn, usuario, mid, n)
    assert frc.situacao(conn, mid)["frc"]["numero"] == n and "2290" in test_frc._texto_da_frc(conn, mid)
    with pytest.raises(ValueError, match=f"Este PDF não é a FRC nº {n} vigente"):
        test_frc._assinar(conn, usuario, mid, _texto, f"FRC {n} v1 assinada.pdf", texto=v1)
    item, _ = test_frc._item_frc(conn, cid, mid)
    assert item["estado"] == "falta"
    test_frc._assinar(conn, usuario, mid, _texto, f"FRC {n} v2 assinada.pdf")
    assert test_frc._item_frc(conn, cid, mid)[0]["estado"] == "ok"


# --- rodada 4 da PR #179 (revisor adversarial na rodada 3) ---------------------------------------------------

def _consorcio_nota_emitida(conn, usuario, consorcio14, _texto, nome):  # noqa: F811
    cid, mid = consorcio14
    test_frc._anexar(conn, usuario, mid, _texto, test_frc.NOTAS_FRC)
    conn.execute("UPDATE medicoes SET estado='nota_emitida' WHERE id=?", (mid,))
    conn.commit()
    doc = test_frc._assinar(conn, usuario, mid, _texto, nome)["documento_id"]
    return cid, mid, doc


def test_pacote_montado_com_a_assinada_velha_exige_montar_de_novo(conn, usuario, consorcio14, _texto, tmp_path,
                                                                   monkeypatch):  # noqa: F811
    """Critico: orgao com as notas DENTRO do pacote (familia mtpar). Assinada A (FRC v1) no pacote montado; a FRC e'
    gerada de novo e a assinada B (v2) anexada: o bloqueio da A some, mas o pacote ainda leva a A. O envio fica
    bloqueado ate' montar de novo; o pacote novo leva a B e libera."""
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    cid, mid, velha = _consorcio_nota_emitida(conn, usuario, consorcio14, _texto, "FRC v1 assinada.pdf")
    oid = conn.execute("SELECT orgao_id FROM contratos WHERE id=?", (cid,)).fetchone()[0]
    conn.execute("UPDATE orgaos SET familia='mtpar' WHERE id=?", (oid,))
    conn.commit()
    pid = notas_envio.iniciar(conn, usuario["id"], cid, [mid], "301")
    assert "notas" in protocolo._contexto(conn, protocolo._linha(conn, pid))[2].partes
    protocolo.montar(conn, usuario["id"], pid)
    assert json.loads(protocolo._linha(conn, pid)["montado_frcs"]) == [velha]
    frc.gerar(conn, usuario, mid, test_frc.ULTIMA + 1)
    nova = test_frc._assinar(conn, usuario, mid, _texto, "FRC v2 assinada.pdf")["documento_id"]
    assert frc.assinada(conn, mid)["documento"]["id"] == nova
    assert protocolo.bloqueio(conn, protocolo._linha(conn, pid), HOJE) == protocolo.PACOTE_FRC_VELHA
    env = notas_envio.detalhe_envio(conn, pid)["envio"]
    assert env["situacao"] == "bloqueado" and "Pacote com a FRC assinada anterior" in env["aviso"]
    pv = protocolo.previa_envio(conn, [pid], hoje=HOJE)
    with pytest.raises(protocolo.Bloqueio, match="O pacote foi montado antes da FRC assinada que vale agora"):
        protocolo.enviar(conn, usuario, [pid], ["orgao@exemplo.com.br"], [], pv["assunto"], pv["corpo"],
                         "justificativa longa o bastante para passar", hoje=HOJE)
    assert conn.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    protocolo.montar(conn, usuario["id"], pid)
    assert json.loads(protocolo._linha(conn, pid)["montado_frcs"]) == [nova]
    assert protocolo.bloqueio(conn, protocolo._linha(conn, pid), HOJE) is None


def test_frc_que_muda_durante_a_reserva_recusa_e_destrava(conn, usuario, consorcio14, _texto, tmp_path,
                                                          monkeypatch):  # noqa: F811
    """Aviso: a FRC fica desatualizada entre a previa e a reserva. A conferencia depois da reserva recusa antes do
    e-mail e destrava a reserva (senao o e-mail sairia sem a FRC assinada, que deixou de valer)."""
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    cid, mid, _ = _consorcio_nota_emitida(conn, usuario, consorcio14, _texto, "FRC assinada.pdf")
    pid = notas_envio.iniciar(conn, usuario["id"], cid, [mid])
    pv = protocolo.previa_envio(conn, [pid])
    assert pv["bloqueio"] is None and [a for a in pv["anexos"] if a["origem"] == "frc"]
    reservar = protocolo.envio_reserva.reservar

    def no_meio(conn_, *a, **k):            # outra pessoa troca uma nota enquanto o envio reserva
        reservar(conn_, *a, **k)
        conn_.execute("UPDATE frcs SET notas='[]' WHERE medicao_id=? AND substituida_em IS NULL", (mid,))
    monkeypatch.setattr(protocolo.envio_reserva, "reservar", no_meio)
    with pytest.raises(protocolo.Bloqueio, match="As notas mudaram depois da FRC nº"):
        notas_envio.enviar(conn, usuario, pid, pv["para"] or ["orgao@exemplo.com.br"], pv["copia"], pv["assunto"],
                           pv["corpo"], "justificativa longa o bastante para passar", anexos_previa=pv["anexos"])
    p = conn.execute("SELECT situacao, envio_id, envio_reservado_em FROM protocolos WHERE id=?", (pid,)).fetchone()
    assert tuple(p) == ("rascunho", None, None)
    assert conn.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0


def test_irma_com_frc_que_bloqueia_nao_vai_no_registro_por_fora(conn, usuario, consorcio14, _texto):  # noqa: F811
    """Aviso: onde medicao e reajuste vao juntos, a irma cuja FRC assinada bloqueia (aqui: reajuste sem espelho) nao
    se oferece nem entra no registro por fora, que contornaria o bloqueio do envio."""
    cid, mid, _ = _consorcio_nota_emitida(conn, usuario, consorcio14, _texto, "FRC assinada.pdf")
    reaj = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 14, "tipo": "reajuste", "competencia": "2026-08"})
    conn.execute("UPDATE medicoes SET estado='nota_emitida' WHERE id=?", (reaj,))
    conn.commit()
    assert frc.assinada(conn, reaj)["recusa"] == frc.SEM_ESPELHO
    c = protocolo._contrato(conn, cid)
    familia, _, o = protocolo._orgao(conn, c)
    m = dict(conn.execute("SELECT * FROM medicoes WHERE id=?", (mid,)).fetchone())
    assert notas_envio._irmas(conn, c, familia, o, [m], HOJE) == []
    with pytest.raises(ValueError, match="não pode ir neste registro"):
        notas_envio._conferir_externo(conn, [mid, reaj], {reaj})


# --- rodada 5 da PR #179 (revisor adversarial na rodada 4) ---------------------------------------------------

def _mtpar(conn, cid):
    oid = conn.execute("SELECT orgao_id FROM contratos WHERE id=?", (cid,)).fetchone()[0]
    conn.execute("UPDATE orgaos SET familia='mtpar' WHERE id=?", (oid,))
    conn.commit()


def test_assinado_do_pacote_anterior_e_recusado_depois_de_montar_de_novo(conn, usuario, consorcio14, _texto,
                                                                         monkeypatch):  # noqa: F811
    """Critico: monta com a assinada A (FRC v1), troca uma nota, gera a v2, anexa B e monta de novo; o PDF assinado do
    pacote ANTERIOR (com a A) passa na semelhanca de paginas, mas nao traz a FRC vigente: o anexo e' recusado. O
    assinado do pacote de agora entra."""
    cid, mid, _ = _consorcio_nota_emitida(conn, usuario, consorcio14, _texto, "FRC v1 assinada.pdf")
    _mtpar(conn, cid)
    n = test_frc.ULTIMA + 1
    v1 = test_frc._texto_da_frc(conn, mid)
    pid = notas_envio.iniciar(conn, usuario["id"], cid, [mid], "301")
    protocolo.montar(conn, usuario["id"], pid)
    pacote_v1 = arquivos.caminho_seguro(protocolo._linha(conn, pid)["montado_arquivo"]).read_bytes()
    test_frc._anexar(conn, usuario, mid, _texto, [("lotufo", 2290, *test_frc.NOTAS_FRC[2][2:])])   # nota reemitida
    frc.gerar(conn, usuario, mid, n)
    v2 = test_frc._texto_da_frc(conn, mid)
    assert "2290" in v2 and "2290" not in v1
    test_frc._assinar(conn, usuario, mid, _texto, "FRC v2 assinada.pdf")
    carimbo = "\nDocuSign Envelope ID: 0A1B2C3D-0000-1111-2222-333344445555\n"
    # o texto de cada pacote como o DocuSign o devolve: o da FRC que ele leva (as notas de teste nao tem texto)
    textos = {pacote_v1: [v1 + carimbo]}
    monkeypatch.setattr(protocolo.leitura_pdf, "textos_por_pagina_com_limite", lambda pdf, teto=400: textos[pdf])
    # o pacote de agora ainda leva a A: assinar de novo nao resolve, a mensagem manda montar de novo
    with pytest.raises(ValueError, match="O pacote foi montado antes da FRC assinada que vale agora"):
        protocolo.receber_assinado(conn, usuario["id"], pid, pacote_v1)
    protocolo.montar(conn, usuario["id"], pid)
    pacote_v2 = arquivos.caminho_seguro(protocolo._linha(conn, pid)["montado_arquivo"]).read_bytes()
    textos[pacote_v2] = [v2 + carimbo]
    with pytest.raises(ValueError, match=f"O assinado não traz a FRC nº {n} vigente da 14ª Medição"):
        protocolo.receber_assinado(conn, usuario["id"], pid, pacote_v1)
    # os numeros e valores da v2 numa pagina que nao e' a da FRC (nota, carta) nao contam
    textos[b"fora"] = [v2.replace("FATURA DE RECEBIMENTO DE CONSÓRCIO", "NOTA FISCAL") + carimbo, v1 + carimbo]
    with pytest.raises(ValueError, match=f"O assinado não traz a FRC nº {n} vigente"):
        protocolo.receber_assinado(conn, usuario["id"], pid, b"fora")
    textos[b"digitalizado"] = ["", ""]
    with pytest.raises(ValueError, match="O assinado não tem texto para conferir a FRC"):
        protocolo.receber_assinado(conn, usuario["id"], pid, b"digitalizado")
    p = protocolo._linha(conn, pid)
    assert (p["situacao"], p["assinado_arquivo"]) == ("montado", None)
    # o pacote montado de novo entre a conferencia e a gravacao: a conferencia sob o lock recusa
    conferir = protocolo.assinatura.conferir

    def no_meio(*a):
        conn.execute("UPDATE protocolos SET montado_sha256='outro' WHERE id=?", (pid,))
        conn.commit()
        return conferir(*a)
    monkeypatch.setattr(protocolo.assinatura, "conferir", no_meio)
    with pytest.raises(ValueError, match="O pacote foi montado de novo enquanto o assinado era conferido"):
        protocolo.receber_assinado(conn, usuario["id"], pid, pacote_v2)
    monkeypatch.setattr(protocolo.assinatura, "conferir", conferir)
    conn.execute("UPDATE protocolos SET montado_sha256=? WHERE id=?", (p["montado_sha256"], pid))
    conn.commit()
    d = protocolo.receber_assinado(conn, usuario["id"], pid, pacote_v2)
    assert d["situacao"] == "assinado" and protocolo.bloqueio(conn, protocolo._linha(conn, pid), HOJE) is None


def test_pacote_sem_a_frc_assinada_pede_montar_de_novo(conn, usuario, consorcio14, _texto):  # noqa: F811
    """Sugestao: pacote montado antes de qualquer assinada, ou de antes da migracao 041 (montado_frcs NULL), nao
    leva a assinada que vale: bloqueio com a mensagem de pacote SEM a FRC (nao "leva a anterior")."""
    cid, mid = consorcio14
    test_frc._anexar(conn, usuario, mid, _texto, test_frc.NOTAS_FRC)
    conn.execute("UPDATE medicoes SET estado='nota_emitida' WHERE id=?", (mid,))
    conn.commit()
    _mtpar(conn, cid)
    pid = notas_envio.iniciar(conn, usuario["id"], cid, [mid], "301")
    protocolo.montar(conn, usuario["id"], pid)                 # sem assinada: o pacote vai sem FRC
    assert json.loads(protocolo._linha(conn, pid)["montado_frcs"]) == []
    doc = test_frc._assinar(conn, usuario, mid, _texto, "FRC assinada.pdf")["documento_id"]
    assert protocolo.bloqueio(conn, protocolo._linha(conn, pid), HOJE) == protocolo.PACOTE_SEM_FRC
    env = notas_envio.detalhe_envio(conn, pid)["envio"]
    assert env["situacao"] == "bloqueado" and "Pacote sem a FRC assinada: monte de novo" in env["aviso"]
    protocolo.montar(conn, usuario["id"], pid)
    assert json.loads(protocolo._linha(conn, pid)["montado_frcs"]) == [doc]
    assert protocolo.bloqueio(conn, protocolo._linha(conn, pid), HOJE) is None
    conn.execute("UPDATE protocolos SET montado_frcs=NULL WHERE id=?", (pid,))      # montado antes da 041
    conn.commit()
    assert protocolo.bloqueio(conn, protocolo._linha(conn, pid), HOJE) == protocolo.PACOTE_SEM_FRC


def test_anexo_que_muda_de_tamanho_durante_a_reserva_recusa_e_destrava(conn, usuario, consorcio14, _texto, tmp_path,
                                                                       monkeypatch):  # noqa: F811
    """Sugestao: sem `anexos_previa` (rota generica de protocolos), uma nota que muda de tamanho entre a previa e a
    reserva recusa com AnexosMudaram depois da reserva e destrava antes de qualquer e-mail."""
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    cid, mid, _ = _consorcio_nota_emitida(conn, usuario, consorcio14, _texto, "FRC assinada.pdf")
    pid = notas_envio.iniciar(conn, usuario["id"], cid, [mid])
    pv = protocolo.previa_envio(conn, [pid], hoje=HOJE)
    assert pv["bloqueio"] is None and [a for a in pv["anexos"] if a["origem"] == "nota"]
    nota = conn.execute("SELECT arquivo FROM medicao_documentos WHERE medicao_id=? AND tipo_doc='nfs' ORDER BY id "
                        "LIMIT 1", (mid,)).fetchone()[0]
    reservar = protocolo.envio_reserva.reservar

    def no_meio(conn_, *a, **k):            # o arquivo da nota muda enquanto o envio reserva
        reservar(conn_, *a, **k)
        caminho = arquivos.caminho_seguro(nota)
        caminho.write_bytes(caminho.read_bytes() + b"\n% mais")
    monkeypatch.setattr(protocolo.envio_reserva, "reservar", no_meio)
    with pytest.raises(protocolo.AnexosMudaram):
        protocolo.enviar(conn, usuario, [pid], ["orgao@exemplo.com.br"], [], pv["assunto"], pv["corpo"],
                         "justificativa longa o bastante para passar", hoje=HOJE)
    p = conn.execute("SELECT situacao, envio_id, envio_reservado_em FROM protocolos WHERE id=?", (pid,)).fetchone()
    assert tuple(p) == ("rascunho", None, None)
    assert conn.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0


def test_a_enviar_mostra_se_o_envio_comecado_esta_reservado(api):
    """So' leitura: a pagina da medicao oferece 'Liberar envio preso' apenas com reserva de fato."""
    cl, c, ids = api
    sinfra, = _por_contrato(cl.get("/api/notas/a-enviar").json(), ids["sinfra"])
    assert sinfra["protocolo_id"] is None and sinfra["envio_reservado_em"] is None
    pid = cl.post("/api/notas/envio/iniciar", json={"contrato_id": ids["sinfra"],
                                                    "medicao_ids": sinfra["medicao_ids"]}).json()["protocolo_id"]
    sinfra, = _por_contrato(cl.get("/api/notas/a-enviar").json(), ids["sinfra"])
    assert sinfra["protocolo_id"] == pid and sinfra["envio_reservado_em"] is None
    c.execute("UPDATE protocolos SET envio_reservado_em=datetime('now') WHERE id=?", (pid,)); c.commit()
    sinfra, = _por_contrato(cl.get("/api/notas/a-enviar").json(), ids["sinfra"])
    assert sinfra["envio_reservado_em"] is not None
