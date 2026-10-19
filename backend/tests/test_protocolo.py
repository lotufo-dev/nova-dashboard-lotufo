"""Protocolo de medicao feito pelo sistema (bloco 5): familias, pecas, carta, pacote, assinado, envio."""
import datetime
import io
import json
import pathlib

import pypdf
import pytest
import yaml
from fpdf import FPDF

from app import (arquivos, auth, cadastro_aplicar, carta, certidoes, correio, db, documentos, graph, leitura_pdf,
                 protocolo, tempo)

D = datetime.date
CARTAS = yaml.safe_load((pathlib.Path(__file__).parents[2] / "cadastro-exemplo" / "cartas.yaml").read_text(encoding="utf-8"))
CINCO = ["federal", "fgts", "trabalhista", "estadual", "municipal"]


def _contrato(nome, orgao, numero):
    return {"nome_curto": nome, "numero_instrumento": numero, "orgao": orgao, "entidade": "lotufo",
            "objeto": nome, "objeto_completo": f"EXECUÇÃO DA OBRA {nome.upper()}", "municipio": "Cuiabá",
            "lei": "14.133", "cno": None, "numero_processo": None, "centro_custo_rm": None,
            "valor_original_centavos": 100_000_000, "percentual_direito_bp": 10000, "execucao_inicio": "2025-01-01",
            "execucao_fim": "2027-01-01", "vigencia_inicio": None, "vigencia_fim": "2027-04-01", "status": "ativo",
            "status_desde": None, "sem_reajuste": False, "datas_base": [],
            "fiscais": [{"nome": "Beatriz Exemplo", "email": "fiscal@exemplo.gov.br", "desde": "2026-01-01",
                         "cargo": "Engenheira Fiscal", "tratamento": "Senhora", "portaria": None}],
            "destinatarios_extras": [], "instrumentos": [], "cno_caminho": None}


def _pdf(texto: str) -> bytes:
    return carta.pagina_titulo([texto])


def _gravar(pasta, dados, ext="pdf"):
    return arquivos.gravar_bytes(pasta, dados, ext)


@pytest.fixture
def cenario(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    monkeypatch.setattr(tempo, "hoje_local", lambda: D(2026, 9, 16))
    c = db.get_conn(); db.migrate(c)
    uid = auth.criar_usuario(c, "Maria", "maria@l.com", "senha-forte-123", "admin")
    cad = {"orgaos": [
        {"chave": "mtpar", "nome": "MTPAR", "familia": "mtpar", "cnpj": None,
         "regras": {"protocolo_para": ["protocolo@orgao-b.exemplo.com.br"], "protocolo_copia": ["maria@l.com", "leo@l.com"],
                    "carta_destinatario": ["A MT PARTICIPAÇÕES E PROJETOS S.A – MT-PAR"],
                    "ordem_certidoes": ["municipal", "trabalhista", "estadual", "federal", "fgts"],
                    "documentos_medicao": CINCO, "documentos_reajuste": CINCO}},
        {"chave": "sinfra-x", "nome": "SINFRA - X", "familia": "sinfra", "cnpj": None,
         "regras": {"protocolo_para": ["sinfra@orgao-a.exemplo.com.br"], "protocolo_copia": ["leo@l.com"],
                    "limite_mb_por_documento": 25,
                    "pecas": [{"tipo": "boletim", "rotulo": "Boletim de medição", "exigida": True},
                              {"tipo": "planilha", "rotulo": "Planilha editável", "exigida": True, "solto": True}],
                    "documentos_medicao": CINCO + ["regularidade"], "documentos_reajuste": CINCO}}],
        "entidades": [{"chave": "lotufo", "nome": "Lotufo Engenharia e Construções Ltda", "cnpj": "31200101000130",
                       "papel": "lotufo", "coligada_rm": 1, "sigla_oficio": "LT", "nome_curto": "Lotufo"}],
        "contratos": [_contrato("Obra MTPAR", "mtpar", "099/2024/MTPAR"), _contrato("Obra SINFRA", "sinfra-x", "IC 1/2026")],
        "avisos": [], "geral": {"cartas": CARTAS}}
    cadastro_aplicar.aplicar(c, uid, cad)
    ids = {"uid": uid, "usuario": {"id": uid, "email": "maria@l.com"},
           "mtpar": c.execute("SELECT id FROM contratos WHERE nome_curto='Obra MTPAR'").fetchone()[0],
           "sinfra": c.execute("SELECT id FROM contratos WHERE nome_curto='Obra SINFRA'").fetchone()[0]}
    for chave in CINCO:
        rel, sha = _gravar("certidoes", _pdf(f"CERTIDAO {chave.upper()}"))
        certidoes.registrar(c, uid, 1, documentos.tipo_por_chave(c, chave)["id"], "2026-09-01", "2026-12-31", rel, sha,
                            "upload", natureza="negativa", leitura="automatica")
    rel, sha = _gravar("regularidades", _pdf("REGULARIDADE 07/2026"))
    documentos.registrar_regularidade(c, uid, 1, "2026-07", rel, sha, 100, "072026 - LOTUFO.pdf")
    for obra in ("mtpar", "sinfra"):
        for tipo in ("execucao", "reajuste"):
            c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
                      "VALUES (?, 23, ?, '2026-09', 'nota_emitida', 1000000)", (ids[obra], tipo))
            mid = c.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]
            ids[f"{obra}_{'exec' if tipo == 'execucao' else 'reaj'}"] = mid
            rel, sha = _gravar("notas", _pdf(f"NFS-e 23{mid:02d}"))
            c.execute("INSERT INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, numero_nf, item_id, arquivo, "
                      "sha256, tamanho) VALUES (?,?,?,?,?,?,?,?,?)",
                      (mid, "operacao", "nfs", f"NFS-e 23{mid:02d}.pdf", f"23{mid:02d}", f"pdf:{sha}", rel, sha, 10))
    c.commit()
    yield c, ids
    c.close()


def _textos(rel: str) -> list[str]:
    return leitura_pdf.textos_por_pagina_com_limite(arquivos.caminho_seguro(rel).read_bytes())


# --- parte 1: familias, criar, pecas, carta, montagem, pendencias ----------------------------------

def test_etapas_por_familia(cenario):
    c, ids = cenario
    assert [e.chave for e in protocolo.etapas_do_contrato(c, ids["mtpar"])] == ["unico"]
    assert [e.chave for e in protocolo.etapas_do_contrato(c, ids["sinfra"])] == ["medicao", "nota"]


def test_criar_normaliza_o_oficio_e_recusa_medicao_encerrada(cenario):
    c, ids = cenario
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    assert protocolo.detalhe(c, pid)["numero_oficio"] == "CT-301-LT-2026"
    c.execute("UPDATE medicoes SET estado='cancelada' WHERE id=?", (ids["mtpar_reaj"],)); c.commit()
    with pytest.raises(ValueError, match="cancelada"):
        protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")


def test_mtpar_nao_junta_execucao_e_reajuste(cenario):
    c, ids = cenario
    with pytest.raises(ValueError, match="separad"):
        protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"], ids["mtpar_reaj"]], "301")


def test_montar_mtpar_carta_notas_e_certidoes_na_ordem_do_orgao(cenario):
    c, ids = cenario
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    r = protocolo.montar(c, ids["uid"], pid)
    textos = _textos(r["arquivo"])
    assert "CT/301/LT/2026" in textos[0] and "A/C: Beatriz Exemplo" in textos[0] and "23ª Medição" in textos[0]
    assert "Prezada Senhora" in textos[0] and "EXECUÇÃO DA OBRA OBRA MTPAR" in textos[0]
    assert "NFS-e" in textos[1]
    assert "MUNICIPAL" in textos[2] and "FGTS" in textos[6]            # ordem_certidoes do orgao
    assert r["nome"] == "CT-301-LT-2026 - Obra MTPAR - 23ª Medição (09.2026).pdf"
    assert protocolo.detalhe(c, pid)["situacao"] == "montado"


def test_objeto_carta_vence_o_do_qdop_no_ref_e_no_corpo(cenario):
    c, ids = cenario
    c.execute("UPDATE contratos SET objeto_carta='Complexo Cultural da Praça da família' WHERE id=?", (ids["mtpar"],))
    c.commit()
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    assert "responsável pela obra Complexo Cultural da Praça da família, envia" in protocolo.corpo_padrao(c, pid)
    texto = " ".join(_textos(protocolo.montar(c, ids["uid"], pid)["arquivo"])[0].split())
    assert "099/2024/MTPAR – Complexo Cultural da Praça da família" in texto
    assert "EXECUÇÃO DA OBRA" not in texto and "relativos ao Reajuste da 23ª Medição" in texto


def test_corpo_editado_vai_para_a_carta_e_fica_gravado(cenario):
    c, ids = cenario
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    corpo = protocolo.corpo_padrao(c, pid) + "\n\nSegue também o link: https://exemplo"
    r = protocolo.montar(c, ids["uid"], pid, corpo=corpo)
    assert "https://exemplo" in _textos(r["arquivo"])[0]
    assert protocolo.detalhe(c, pid)["corpo_carta"] == corpo.strip()
    r = protocolo.montar(c, ids["uid"], pid, corpo="   ")              # vazio nao apaga a carta
    assert "https://exemplo" in _textos(r["arquivo"])[0]


def test_sinfra_medicao_leva_carta_e_boletim_e_pendencia_de_planilha(cenario):
    c, ids = cenario
    pid = protocolo.criar(c, ids["uid"], ids["sinfra"], "medicao", [ids["sinfra_exec"]], "310")
    protocolo.adicionar_peca(c, ids["uid"], pid, "boletim", "boletim.pdf", _pdf("BOLETIM 23"), "pdf")
    codigos = [x["codigo"] for x in protocolo.detalhe(c, pid)["pendencias"]]
    assert "peca" in codigos and "sem_nota" not in codigos       # etapa da medicao nao cobra nota
    r = protocolo.montar(c, ids["uid"], pid)
    assert "BOLETIM 23" in _textos(r["arquivo"])[-1]


def test_sinfra_lista_em_romanos_e_reajuste_com_carta_e_pecas_proprias(cenario):
    c, ids = cenario
    regras = {"pecas": [{"tipo": "diagrama", "rotulo": "Diagrama Linear dos serviços", "exigida": True,
                         "naturezas": ["execucao"]},
                        {"tipo": "croqui", "rotulo": "Croqui de localização", "exigida": True, "naturezas": ["execucao"]},
                        {"tipo": "outro", "rotulo": "Planilha de reajustamento", "exigida": True,
                         "naturezas": ["reajuste"]}]}
    c.execute("UPDATE orgaos SET regras=json_patch(regras, ?) WHERE chave='sinfra-x'", (json.dumps(regras),))
    c.commit()
    p1 = protocolo.criar(c, ids["uid"], ids["sinfra"], "medicao", [ids["sinfra_exec"]], "310")
    corpo = protocolo.corpo_padrao(c, p1)
    assert "I - Diagrama Linear dos serviços;\nII - Croqui de localização." in corpo
    assert "reajustamento" not in corpo
    p2 = protocolo.criar(c, ids["uid"], ids["sinfra"], "medicao", [ids["sinfra_reaj"]], "311")
    assert protocolo.corpo_padrao(c, p2).startswith("Enviamos a planilha de reajuste "
                                                    "da 23ª (vigésima terceira) medição da obra")
    faltam = [x["mensagem"] for x in protocolo.detalhe(c, p2)["pendencias"] if x["codigo"] == "peca"]
    assert faltam == ["Planilha de reajustamento: não anexada"]           # diagrama e croqui nao valem no reajuste


def test_pendencias_de_certidao_e_nota(cenario):
    c, ids = cenario
    c.execute("DELETE FROM medicao_documentos WHERE medicao_id=?", (ids["mtpar_exec"],))
    c.execute("DELETE FROM certidoes WHERE tipo_id=(SELECT id FROM certidao_tipos WHERE chave='fgts')")
    c.commit()
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    codigos = [x["codigo"] for x in protocolo.detalhe(c, pid)["pendencias"]]
    assert "sem_nota" in codigos and "certidao" in codigos


# --- parte 2: assinado, previa, envio --------------------------------------------------------------

def _assinar(pdf_montado: bytes, guid="7E965481-0A1B-4C2D-8E9F-0123456789AB") -> bytes:
    """Assinado de mentira: as mesmas paginas, cada uma com o carimbo do DocuSign como texto a mais."""
    r, w = pypdf.PdfReader(io.BytesIO(pdf_montado)), pypdf.PdfWriter()
    for pagina in r.pages:
        f = FPDF(format="A4"); f.add_page(); f.set_font("Helvetica", size=6)
        f.text(5, 5, f"Docusign Envelope ID: {guid}")
        w.add_page(pagina)
        w.pages[-1].merge_page(pypdf.PdfReader(io.BytesIO(bytes(f.output()))).pages[0])
    buf = io.BytesIO(); w.write(buf)
    return buf.getvalue()


def _montado(c, ids, pid) -> bytes:
    return arquivos.caminho_seguro(protocolo.montar(c, ids["uid"], pid)["arquivo"]).read_bytes()


def test_assinado_conferido_e_nao_assinado_vira_pendencia(cenario):
    c, ids = cenario
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    montado = _montado(c, ids, pid)
    d = protocolo.receber_assinado(c, ids["uid"], pid, montado)          # o mesmo PDF, sem carimbo
    assert d["situacao"] == "assinado" and any(x["codigo"] == "conferencia" for x in d["pendencias"])
    d = protocolo.receber_assinado(c, ids["uid"], pid, _assinar(montado))
    assert d["conferencia"]["ok"] and not [x for x in d["pendencias"] if x["codigo"] == "conferencia"]


def test_enviar_mtpar_marca_protocolada_e_liga_o_envio(cenario):
    c, ids = cenario
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    pv = protocolo.previa_envio(c, [pid], remetente="maria@l.com")
    assert pv["assunto"] == "Protocolo CT/301/LT/2026: 23ª Medição, ref. 09/2026, Obra MTPAR" and pv["pendencias"] == []   # D1
    assert pv["para"] == ["protocolo@orgao-b.exemplo.com.br", "fiscal@exemplo.gov.br"] and pv["copia"] == ["leo@l.com"]
    envio = protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"])
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["mtpar_exec"],)).fetchone()[0] == "protocolada"
    mp = c.execute("SELECT protocolo_id, numero_oficio FROM medicao_protocolos WHERE medicao_id=?",
                   (ids["mtpar_exec"],)).fetchone()
    assert (mp["protocolo_id"], mp["numero_oficio"]) == (pid, "CT-301-LT-2026")
    d = protocolo.detalhe(c, pid)
    assert d["envio_id"] == envio
    assert d["enviado_por"] == "Maria" and d["enviado_em"]              # A6: quando e quem enviou


def test_enviar_com_pendencia_exige_a_confirmacao_da_lista_e_nada_muda_antes(cenario):
    """Issue #213: a justificativa escrita deu lugar a' confirmacao do aviso "ATENÇÃO"; sem ela, ou com outra lista,
    nada sai. A justificativa, se vier, continua gravada."""
    c, ids = cenario
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    protocolo.montar(c, ids["uid"], pid)                                  # sem assinar: pendencia
    pv = protocolo.previa_envio(c, [pid])
    faltam = [x["mensagem"] for x in pv["pendencias"]]
    assert faltam == ["Pacote ainda não assinado"]
    with pytest.raises(protocolo.ConfirmarPendencias, match="^ATENÇÃO: falta documento") as e:
        protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                         justificativa="assinado fisicamente pelo diretor")       # justificativa nao substitui
    assert e.value.pendencias == faltam
    with pytest.raises(protocolo.ConfirmarPendencias, match="mudou"):
        protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                         confirmadas=[*faltam, "Lotufo: CND Federal sem validade hoje"])
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE acao='protocolo.envio_confirmado'").fetchone()[0] == 0
    protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                     justificativa="assinado fisicamente pelo diretor", confirmadas=faltam)
    depois = c.execute("SELECT depois FROM audit_log WHERE acao='protocolo.enviar'").fetchone()[0]
    assert json.loads(depois)["justificativa"] == "assinado fisicamente pelo diretor"
    conf = c.execute("SELECT usuario_id, entidade_id, depois FROM audit_log "
                     "WHERE acao='protocolo.envio_confirmado'").fetchone()
    assert (conf["usuario_id"], conf["entidade_id"], json.loads(conf["depois"])) == (ids["uid"], str(pid),
                                                                                     {"pendencias": faltam})


def test_bloqueio_recusa_o_protocolo_mesmo_confirmado(cenario):
    """Issue #213: certidao vencida continua bloqueio, nao aviso; a confirmacao nao a contorna."""
    c, ids = cenario
    c.execute("UPDATE certidoes SET validade='2026-09-10' WHERE tipo_id=?", (documentos.tipo_por_chave(c, "federal")["id"],))
    c.commit()
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    pv = protocolo.previa_envio(c, [pid])
    assert pv["bloqueio"]
    with pytest.raises(protocolo.Bloqueio):
        protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                         confirmadas=[x["mensagem"] for x in pv["pendencias"]])
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0


def test_sinfra_medicao_nao_protocola_e_nota_protocola_com_o_oficio_da_medicao(cenario):
    c, ids = cenario
    p1 = protocolo.criar(c, ids["uid"], ids["sinfra"], "medicao", [ids["sinfra_exec"]], "310")
    protocolo.adicionar_peca(c, ids["uid"], p1, "boletim", "b.pdf", _pdf("B"), "pdf")
    protocolo.adicionar_peca(c, ids["uid"], p1, "planilha", "planilha.xlsx", b"PK\x03\x04planilha", "xlsx")
    protocolo.receber_assinado(c, ids["uid"], p1, _assinar(_montado(c, ids, p1)))
    pv = protocolo.previa_envio(c, [p1])
    assert "planilha.xlsx" in {a["nome"] for a in pv["anexos"]}
    protocolo.enviar(c, ids["usuario"], [p1], pv["para"], pv["copia"], pv["assunto"], pv["corpo"])
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["sinfra_exec"],)).fetchone()[0] == "nota_emitida"
    p2 = protocolo.criar(c, ids["uid"], ids["sinfra"], "nota", [ids["sinfra_exec"]], None)
    pv2 = protocolo.previa_envio(c, [p2])
    nomes = [a["nome"] for a in pv2["anexos"]]
    assert any(n.startswith("Certidoes - Lotufo") for n in nomes) and "Regularidade mensal - Lotufo - 07-2026.pdf" in nomes
    # D5: a nota nao leva mais a ficha do CNO; A-18 (10/10/2026): o reajuste irmao ficou fora do e-mail
    assert [x["codigo"] for x in pv2["pendencias"]] == ["irma_fora"]
    protocolo.enviar(c, ids["usuario"], [p2], pv2["para"], pv2["copia"], pv2["assunto"], pv2["corpo"],
                     confirmadas=[x["mensagem"] for x in pv2["pendencias"]])
    mp = c.execute("SELECT numero_oficio, protocolo_id FROM medicao_protocolos WHERE medicao_id=?",
                   (ids["sinfra_exec"],)).fetchone()
    assert (mp["numero_oficio"], mp["protocolo_id"]) == ("CT-310-LT-2026", p2)


def test_falha_do_graph_nao_muda_estado(cenario, monkeypatch):
    c, ids = cenario
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    pv = protocolo.previa_envio(c, [pid])

    def falha(*a, **k):
        raise graph.ErroGraph("fora do ar")

    monkeypatch.setattr(correio, "enviar_e_registrar", falha)
    with pytest.raises(graph.ErroGraph):
        protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"])
    assert protocolo.detalhe(c, pid)["situacao"] == "assinado"
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["mtpar_exec"],)).fetchone()[0] == "nota_emitida"


def test_medicao_cancelada_durante_o_envio_nao_desfaz_o_registro(cenario, monkeypatch):
    c, ids = cenario
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    pv = protocolo.previa_envio(c, [pid])
    original = correio.enviar_e_registrar

    def cancela_no_meio(*a, **k):                  # outra pessoa cancela enquanto o Graph responde
        eid = original(*a, **k)
        c.execute("UPDATE medicoes SET estado='cancelada' WHERE id=?", (ids["mtpar_exec"],)); c.commit()
        return eid

    monkeypatch.setattr(correio, "enviar_e_registrar", cancela_no_meio)
    eid = protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"])
    assert protocolo.detalhe(c, pid)["situacao"] == "enviado" and protocolo.detalhe(c, pid)["envio_id"] == eid
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["mtpar_exec"],)).fetchone()[0] == "cancelada"
    depois = json.loads(c.execute("SELECT depois FROM audit_log WHERE acao='protocolo.enviar'").fetchone()[0])
    assert depois["nao_marcadas"][0]["medicao_id"] == ids["mtpar_exec"]


# --- issue #118: hosts do link (OneDrive/SharePoint) vem de DASH_SHAREPOINT_HOSTS, nao do codigo ------------------

def test_link_aceita_so_os_hosts_da_variavel(cenario, monkeypatch):
    c, ids = cenario
    monkeypatch.setenv("DASH_SHAREPOINT_HOSTS", " Exemplo-my.SharePoint.com , exemplo.sharepoint.com,, ")
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    for url in ("https://outro-my.sharepoint.com/:b:/g/abc", "https://exemplo-my.sharepoint.com.evil.test/abcdef",
                "https://sub.exemplo.sharepoint.com/abcdef",
                "https://evil.test\\@exemplo.sharepoint.com/abcdef",       # navegador le "\" como "/": abre evil.test
                "https://evil.test@exemplo.sharepoint.com/abcdef",         # userinfo
                "https://exemplo.sharepoint.com:8443/abcdef",              # porta
                "https://exemplo.sharepoint.com%2f.evil.test/abcdef",
                "https://exemplo.sharepoint.com?arquivo=1", "https://exemplo.sharepoint.com#trecho",
                "https://exemplo.sharepoint.com",                          # gate Sol: exige a primeira barra
                "https://exemplo.sharepoint.com／evil.test/abc", "https://[exemplo/abcdef"):   # urlparse daria erro em ingles
        with pytest.raises(ValueError, match=r"exemplo-my\.sharepoint\.com ou exemplo\.sharepoint\.com"):
            protocolo.adicionar_link(c, ids["uid"], pid, "Planilha", url)
    assert protocolo.adicionar_link(c, ids["uid"], pid, "Planilha", "https://exemplo-my.sharepoint.com/:b:/g/abc")
    assert protocolo.adicionar_link(c, ids["uid"], pid, "Planilha 2", "https://EXEMPLO.sharepoint.com/sites/x/abc")
    assert [x["nome"] for x in protocolo.links(c, pid)] == ["Planilha", "Planilha 2"]


@pytest.mark.parametrize("valor", [None, "", " , "])
def test_link_sem_a_variavel_recusa_qualquer_host(cenario, monkeypatch, valor):
    c, ids = cenario
    if valor is None:
        monkeypatch.delenv("DASH_SHAREPOINT_HOSTS", raising=False)
    else:
        monkeypatch.setenv("DASH_SHAREPOINT_HOSTS", valor)
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    for url in ("https://exemplo-my.sharepoint.com/:b:/g/abc", "https://qualquer.test/abcdef"):
        with pytest.raises(ValueError, match="não estão liberados neste servidor"):
            protocolo.adicionar_link(c, ids["uid"], pid, "Planilha", url)
    assert protocolo.links(c, pid) == []


def test_peca_art_do_protocolo_continua_aceita_no_orgao():
    """#239: a ART saiu do contrato, mas segue como peca do pacote (SES-MT pede a copia das ARTs)."""
    from app import api_protocolos, cadastro_arquivos
    assert "art" in cadastro_arquivos.TIPOS_PECA
    assert "art" in api_protocolos.TipoPeca.__args__
