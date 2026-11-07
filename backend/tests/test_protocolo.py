"""Protocolo de medicao feito pelo sistema (bloco 5): familias, pecas, carta, pacote, assinado, envio."""
import datetime
import io
import json
import pathlib
import re

import pypdf
import pytest
import yaml
from fpdf import FPDF

from app import (arquivos, auth, cadastro_aplicar, carta, certidoes, correio, db, documentos, graph, leitura_pdf,
                 protocolo, tempo)

# Gera PDF com a fonte da producao (Arial no Windows): a CI roda este modulo nos dois jobs (marcador pdf).
pytestmark = pytest.mark.pdf

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


def test_peca_exigida_no_oficio_nao_e_pendencia_na_etapa_da_medicao(cenario):
    """Issue #462: a peca que vai dentro do oficio assinado nao cobra; a sem a marca continua cobrando."""
    c, ids = cenario
    regras = {"pecas": [{"tipo": "boletim", "rotulo": "Boletim de medição", "exigida": True, "no_oficio": True},
                        {"tipo": "planilha", "rotulo": "Planilha editável", "exigida": True, "solto": True}]}
    c.execute("UPDATE orgaos SET regras=json_patch(regras, ?) WHERE chave='sinfra-x'", (json.dumps(regras),))
    c.commit()
    pid = protocolo.criar(c, ids["uid"], ids["sinfra"], "medicao", [ids["sinfra_exec"]], "310")

    def faltam():
        return [x["mensagem"] for x in protocolo.detalhe(c, pid)["pendencias"] if x["codigo"] == "peca"]

    assert faltam() == ["Planilha editável: não anexada"]
    # a tela recebe a marca efetiva; o anexo da peca marcada e' recusado (gate Sol, PR #473)
    assert {x["tipo"]: x["no_oficio"] for x in protocolo.listar(c, ids["sinfra"])["pecas"]} == \
        {"boletim": True, "planilha": False}
    with pytest.raises(ValueError, match="^Esta peça vai no ofício assinado$"):
        protocolo.adicionar_peca(c, ids["uid"], pid, "boletim", "boletim.pdf", _pdf("BOLETIM 23"), "pdf")
    assert protocolo.detalhe(c, pid)["pecas"] == []
    # a lista do contrato (vazia aqui) substitui a marca do orgao: o boletim volta a cobrar
    c.execute("UPDATE contratos SET pecas_no_oficio='[]' WHERE id=?", (ids["sinfra"],))
    c.commit()
    assert faltam() == ["Boletim de medição: não anexada", "Planilha editável: não anexada"]
    assert {x["tipo"]: x["no_oficio"] for x in protocolo.listar(c, ids["sinfra"])["pecas"]}["boletim"] is False
    protocolo.adicionar_peca(c, ids["uid"], pid, "boletim", "boletim.pdf", _pdf("BOLETIM 23"), "pdf")


def test_peca_no_oficio_continua_cobrando_fora_da_etapa_da_medicao(cenario):
    """Issue #462 (/code-review): o pacote da prefeitura (e da SES) e' outro documento, sem o oficio da planilha/carta."""
    c, ids = cenario
    regras = {"pecas": [{"tipo": "boletim", "rotulo": "Boletim de medição", "exigida": True, "no_oficio": True}]}
    c.execute("UPDATE orgaos SET familia='prefeitura', regras=json_patch(regras, ?) WHERE chave='mtpar'",
              (json.dumps(regras),))
    c.commit()
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    assert [x["mensagem"] for x in protocolo.detalhe(c, pid)["pendencias"] if x["codigo"] == "peca"] == \
        ["Boletim de medição: não anexada"]


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
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    # vence depois da montagem (#278, rodada 2 da PR #435: com ela vencida, o pacote nem monta)
    c.execute("UPDATE certidoes SET validade='2026-09-10' WHERE tipo_id=?", (documentos.tipo_por_chave(c, "federal")["id"],))
    c.commit()
    pv = protocolo.previa_envio(c, [pid])
    assert pv["bloqueio"]
    with pytest.raises(protocolo.Bloqueio):
        protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                         confirmadas=[x["mensagem"] for x in pv["pendencias"]])
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0


# --- issue #278: o oficio de reajuste da MT-PAR e da Prefeitura cita o apostilamento que cobre a competencia -------

SEM_APOSTILAMENTO = "Nenhum apostilamento cobre 09/2026; a nota de reajuste não pode sair antes dele"


def _termo(c, cid, chave="ap-reaj-01", numero="001/2025/03/02", de="2026-09", ate="2027-08", data="2026-09-01",
           corrige=None):
    """Percentual apostilado da MT-PAR (data-base 09/2025, ciclo 2026) com o periodo de `de` a `ate`."""
    dados = {"data_base": "2025-09", "ciclo": 2026, "percentual": "4,15", "periodo": {"de": de, "ate": ate},
             **({"corrige": corrige} if corrige else {})}
    c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, numero, data, dados) "
              "VALUES (?, ?, 'apostilamento_reajuste', ?, ?, ?)", (cid, chave, numero, data, json.dumps(dados)))
    c.commit()


def _data_base_e_termo(c, cid, termo=True):
    """Data-base 09/2025 (a competencia 09/2026 abre o ciclo 2026) e, com `termo`, o percentual apostilado da MT-PAR
    com o periodo que a cobre."""
    c.execute("INSERT INTO contrato_datas_base (contrato_id, mes, indice) VALUES (?, '2025-09', 'INCC-DI')", (cid,))
    c.commit()
    if termo:
        _termo(c, cid)


def _reajuste(c, cid, numero, competencia):
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, ?, 'reajuste', ?, 'nota_emitida', 1000001)", (cid, numero, competencia))
    c.commit()
    return c.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]


def _corrido(texto: str) -> str:
    return " ".join(texto.split())


def _carta_montada(c, ids, pid, **kw) -> str:
    """O texto corrido da 1a pagina (a carta) do pacote montado agora."""
    return _corrido(_textos(protocolo.montar(c, ids["uid"], pid, **kw)["arquivo"])[0])


FRASE = "O reajuste da competência 09/2026 está apostilado no Termo de Apostilamento nº 001/2025/03/02."


def test_oficio_de_reajuste_mtpar_cita_o_apostilamento_e_a_competencia(cenario):
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"])
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    # rodada 2 da PR #435: o texto que a tela mostra e edita guarda o marcador, nunca a frase do termo
    corpo = protocolo.corpo_padrao(c, pid)
    assert "{apostilamento}" in corpo and "Termo de Apostilamento" not in corpo
    texto = _carta_montada(c, ids, pid)
    assert FRASE in texto and "{" not in texto
    assert "sem_apostilamento" not in [x["codigo"] for x in protocolo.detalhe(c, pid)["pendencias"]]
    assert protocolo.previa_envio(c, [pid])["exige_justificativa"] is False
    p_exec = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    texto = _carta_montada(c, ids, p_exec)                                  # o oficio da execucao nao muda
    assert "Apostilamento" not in texto and "{" not in texto


def test_oficio_com_um_reajuste_sem_termo_cita_so_a_competencia_coberta(cenario):
    # code-review da PR: com dois reajustes no mesmo oficio e so' um coberto, a carta nao diz que os dois sao do termo
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"])
    m24 = _reajuste(c, ids["mtpar"], 24, "2027-09")
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"], m24], "303")
    texto = _carta_montada(c, ids, pid)
    assert FRASE in texto and "09/2027" not in texto and "{" not in texto
    assert [x["mensagem"] for x in protocolo.detalhe(c, pid)["pendencias"] if x["codigo"] == "sem_apostilamento"] == [
        "Nenhum apostilamento cobre 09/2027; a nota de reajuste não pode sair antes dele"]


def test_dois_reajustes_de_competencias_diferentes_citam_cada_termo(cenario):
    # gate Sol e revisor (rodada 1 da PR #435): a competencia e o termo vao em par, nao so' os da primeira medicao
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"], termo=False)
    _termo(c, ids["mtpar"], "ap-a", "001/2025/03/02", "2026-09", "2026-09")
    _termo(c, ids["mtpar"], "ap-b", "001/2025/03/05", "2026-10", "2026-10", data="2026-10-01")
    m24 = _reajuste(c, ids["mtpar"], 24, "2026-10")
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"], m24], "303")
    assert ("O reajuste da competência 09/2026 está apostilado no Termo de Apostilamento nº 001/2025/03/02; o da "
            "competência 10/2026, no Termo de Apostilamento nº 001/2025/03/05.") in _carta_montada(c, ids, pid)
    m25 = _reajuste(c, ids["mtpar"], 25, "2026-11")
    _termo(c, ids["mtpar"], "ap-c", "001/2025/03/06", "2026-10", "2026-11", data="2026-11-01")     # vale o mais novo
    p2 = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [m24, m25], "304")
    assert ("O reajuste das competências 10/2026 e 11/2026 está apostilado no Termo de Apostilamento nº 001/2025/03/06."
            in _carta_montada(c, ids, p2))


def test_sem_termo_o_oficio_sai_sem_a_frase_e_nunca_com_campo_sem_dado(cenario):
    # (a) gate Sol e revisor (rodadas 1 e 2 da PR #435): sem termo, a frase some; campo sem dado nao monta, inclusive
    # com acento, maiuscula ou numero no nome
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"], termo=False)
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    corpo = protocolo.corpo_padrao(c, pid)
    texto = _corrido(" ".join(_textos(protocolo.montar(c, ids["uid"], pid)["arquivo"])))
    assert "Apostilamento" not in texto and "{" not in texto
    for campo in ("{período}", "{Obra}", "{municipio2}", "{data_base}"):
        with pytest.raises(ValueError, match="campo sem dado: " + re.escape(campo)):
            protocolo.montar(c, ids["uid"], pid, corpo=f"{corpo}\n\nVer {campo}.")
    assert protocolo.campos_sem_dado("Sem campo: { espaço } nem {}") == []


def test_termo_aplicado_depois_da_montagem_bloqueia_ate_montar_de_novo(cenario):
    # (b) o pacote montado sem o termo nao sai depois que o termo chega; montar de novo refaz o texto padrao
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"], termo=False)
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    _termo(c, ids["mtpar"])
    pv = protocolo.previa_envio(c, [pid])
    assert pv["bloqueio"] == protocolo.APOSTILAMENTO_MUDOU and pv["exige_justificativa"] is False
    with pytest.raises(protocolo.Bloqueio, match="monte o pacote de novo"):
        protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                         confirmadas=[x["mensagem"] for x in pv["pendencias"]])
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    r = protocolo.montar(c, ids["uid"], pid)                               # como a tela de envio: corpo vazio
    assert "Termo de Apostilamento nº 001/2025/03/02" in _corrido(_textos(r["arquivo"])[0])
    d = protocolo.detalhe(c, pid)
    assert d["corpo_carta"] is None and protocolo.previa_envio(c, [pid])["bloqueio"] is None


def test_termo_corrigido_depois_da_montagem_bloqueia_e_a_nova_montagem_cita_o_novo(cenario):
    # (c) o termo que o pacote cita foi corrigido por outro: o pacote nao sai com o termo velho
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"])
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    _termo(c, ids["mtpar"], "ap-reaj-02", "001/2025/03/09", data="2026-09-10", corrige="ap-reaj-01")
    assert protocolo.previa_envio(c, [pid])["bloqueio"] == protocolo.APOSTILAMENTO_MUDOU
    texto = _corrido(_textos(protocolo.montar(c, ids["uid"], pid)["arquivo"])[0])
    assert "nº 001/2025/03/09" in texto and "001/2025/03/02" not in texto
    assert protocolo.previa_envio(c, [pid])["bloqueio"] is None


def test_assinado_do_pacote_anterior_nao_entra_depois_de_montar_com_o_termo_novo(cenario):
    # Rodada extra da PR #435 (revisor e gate Sol, rodada 3): o assinado do pacote anterior passa pela semelhanca de
    # 90% da conferencia; o oficio nao pode sair com o termo velho (ou sem o termo) depois de montar de novo
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"])
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    velho = _assinar(_montado(c, ids, pid))
    _termo(c, ids["mtpar"], "ap-reaj-02", "001/2025/03/09", data="2026-09-10", corrige="ap-reaj-01")
    novo = _assinar(_montado(c, ids, pid))
    with pytest.raises(ValueError, match="não traz o termo de apostilamento do pacote montado agora"):
        protocolo.receber_assinado(c, ids["uid"], pid, velho)
    assert protocolo._linha(c, pid)["situacao"] == "montado"
    assert protocolo.receber_assinado(c, ids["uid"], pid, novo)["situacao"] == "assinado"


def test_assinado_sem_o_termo_nao_entra_depois_que_o_termo_chega(cenario):
    # o pacote montado antes do termo nao citava nada; montado de novo cita, e o assinado de antes nao serve
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"], termo=False)
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    sem_termo = _assinar(_montado(c, ids, pid))
    _termo(c, ids["mtpar"])
    protocolo.montar(c, ids["uid"], pid)
    with pytest.raises(ValueError, match="não traz o termo de apostilamento do pacote montado agora"):
        protocolo.receber_assinado(c, ids["uid"], pid, sem_termo)


def test_assinado_com_o_termo_nao_entra_no_pacote_que_ja_nao_o_cita(cenario):
    # o termo saiu do cadastro (corrigido para outro periodo): o pacote novo nao cita termo e o assinado velho cita
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"])
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    com_termo = _assinar(_montado(c, ids, pid))
    _termo(c, ids["mtpar"], "ap-reaj-02", "001/2025/03/09", de="2027-09", ate="2028-08", data="2026-09-10",
           corrige="ap-reaj-01")
    assert "Apostilamento" not in _corrido(" ".join(_textos(protocolo.montar(c, ids["uid"], pid)["arquivo"])))
    with pytest.raises(ValueError, match="não traz o termo de apostilamento do pacote montado agora"):
        protocolo.receber_assinado(c, ids["uid"], pid, com_termo)


def _corpo_com_o_termo_na_quebra(c, ids, pid):
    """O corpo padrao com linhas antes do campo {apostilamento}, ate' o fpdf quebrar a pagina dentro da frase do termo
    ("... no Termo de" no pe' da pagina 1, o cabecalho do papel timbrado e "Apostilamento nº ..." na 2). Procura so'
    com a carta (`carta.gerar`), que e' a primeira parte do pacote."""
    p, padrao = protocolo._linha(c, pid), protocolo.corpo_padrao(c, pid)
    frase = protocolo.frase_do_apostilamento(protocolo.apostilamentos(c, "mtpar", protocolo._medicoes(c, pid)))
    hoje = tempo.hoje_local()

    def paginas(corpo):
        pdf = carta.gerar(protocolo._carta(c, p, protocolo._renderizar(corpo, frase), hoje, frase))
        return [_corrido(t) for t in leitura_pdf.textos_por_pagina_com_limite(pdf, 50)]

    def corpo(linhas, prefixo):
        return padrao.replace("{apostilamento}", "\n".join(["Linha de enchimento."] * linhas)
                              + "\n\n" + "x " * prefixo + "{apostilamento}")

    # a primeira altura em que o numero do termo ja' nao cabe na pagina 1; dali, o prefixo move a quebra na frase
    linhas = next(n for n in range(10, 80) if "nº 001/2025/03/02" not in paginas(corpo(n, 0))[0])
    for n in (linhas, linhas - 1):
        for prefixo in range(0, 40):
            pags = paginas(corpo(n, prefixo))
            if len(pags) > 1 and pags[0].endswith("Termo de") and pags[1].find("Apostilamento nº") > 0:
                return corpo(n, prefixo)
    raise AssertionError("a frase do termo nao caiu na quebra de pagina")


def test_termo_quebrado_na_pagina_com_cabecalho_tambem_e_conferido(cenario):
    # Gate Sol, rodada extra (07/11/2026), Critico 1: o papel timbrado repete o cabecalho de texto em toda pagina; com
    # a frase do termo partida na quebra, o assinado do termo velho nao pode passar
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"])
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    corpo = _corpo_com_o_termo_na_quebra(c, ids, pid)
    velho = _assinar(arquivos.caminho_seguro(protocolo.montar(c, ids["uid"], pid, corpo=corpo)["arquivo"]).read_bytes())
    _termo(c, ids["mtpar"], "ap-reaj-02", "001/2025/03/09", data="2026-09-10", corrige="ap-reaj-01")
    novo = _assinar(arquivos.caminho_seguro(protocolo.montar(c, ids["uid"], pid, corpo=corpo)["arquivo"]).read_bytes())
    with pytest.raises(ValueError, match="não traz o termo de apostilamento do pacote montado agora"):
        protocolo.receber_assinado(c, ids["uid"], pid, velho)
    assert protocolo.receber_assinado(c, ids["uid"], pid, novo)["situacao"] == "assinado"


def test_competencia_acrescentada_ao_mesmo_termo_tambem_e_conferida(cenario):
    # Critico 2: a correcao acrescenta uma competencia no comeco da lista do mesmo termo (numero igual)
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"], termo=False)
    _termo(c, ids["mtpar"], "ap-a", "001/2025/03/05", "2026-10", "2027-08", data="2026-10-01")
    m24 = _reajuste(c, ids["mtpar"], 24, "2026-10")
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"], m24], "303")
    velho = _assinar(_montado(c, ids, pid))
    _termo(c, ids["mtpar"], "ap-b", "001/2025/03/05", "2026-09", "2027-08", data="2026-10-02", corrige="ap-a")
    assert "das competências 09/2026 e 10/2026" in _carta_montada(c, ids, pid)
    with pytest.raises(ValueError, match="não traz o termo de apostilamento do pacote montado agora"):
        protocolo.receber_assinado(c, ids["uid"], pid, velho)


def test_numero_longo_do_termo_e_conferido_inteiro(cenario):
    # Critico 2: o numero do termo nao tem limite; a diferenca no fim de um numero longo tambem recusa o assinado
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"], termo=False)
    longo = "001/2025/03 do processo administrativo 2025.00.000000000000000000000000000000000001"
    _termo(c, ids["mtpar"], "ap-a", longo)
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    velho = _assinar(_montado(c, ids, pid))
    _termo(c, ids["mtpar"], "ap-b", longo[:-1] + "2", data="2026-09-10", corrige="ap-a")
    _montado(c, ids, pid)
    with pytest.raises(ValueError, match="não traz o termo de apostilamento do pacote montado agora"):
        protocolo.receber_assinado(c, ids["uid"], pid, velho)


def test_certificado_do_docusign_que_cita_o_termo_nao_recusa_o_assinado(cenario):
    # Aviso: as paginas do certificado repetem o assunto do envelope, que pode citar o termo
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"])
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    assinado = pypdf.PdfWriter(clone_from=io.BytesIO(_assinar(_montado(c, ids, pid))))
    assinado.append(io.BytesIO(_pdf("Certificado de Conclusao - Oficio - Termo de Apostilamento nº 001/2026")))
    buf = io.BytesIO(); assinado.write(buf)
    assert protocolo.receber_assinado(c, ids["uid"], pid, buf.getvalue())["situacao"] == "assinado"


def test_texto_sem_o_campo_do_termo_nao_monta(cenario):
    """Revisor e gate Sol (rodada 2 da PR #435): o texto da carta guarda o marcador {apostilamento}, nunca a frase. O
    que chega sem ele, quando o texto da familia o tem, nao monta: (A) o texto da tela de antes do termo, (B) o texto
    com a frase de um termo que foi corrigido, (C) a edicao a' mao sem o campo e (F) o texto gravado antes desta
    versao. So' a tela de envio, que nao mostra o texto, troca o gravado velho pelo padrao (`refazer_texto`)."""
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"], termo=False)
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    marcado = protocolo.corpo_padrao(c, pid)
    antes_do_termo = protocolo._sem_linhas_vazias(marcado.replace("{apostilamento}", ""))         # (A) e (F)
    _termo(c, ids["mtpar"])
    frase_velha = marcado.replace("{apostilamento}", FRASE)                                      # (B)
    _termo(c, ids["mtpar"], "ap-reaj-02", "001/2025/03/09", data="2026-09-10", corrige="ap-reaj-01")
    editado = marcado.replace("{apostilamento}", "Conforme o termo do reajuste.")                 # (C)
    for corpo in (antes_do_termo, frase_velha, editado):
        for refazer in (False, True):           # texto que veio da tela nunca e' trocado em silencio
            with pytest.raises(ValueError, match="não cita o termo de apostilamento de agora"):
                protocolo.montar(c, ids["uid"], pid, corpo=corpo, refazer_texto=refazer)
    assert protocolo.detalhe(c, pid)["situacao"] == "rascunho"
    c.execute("UPDATE protocolos SET corpo_carta=? WHERE id=?", (antes_do_termo, pid))            # (F)
    c.commit()
    with pytest.raises(ValueError, match="não cita o termo de apostilamento de agora"):
        protocolo.montar(c, ids["uid"], pid)
    texto = _carta_montada(c, ids, pid, refazer_texto=True)
    assert "Termo de Apostilamento nº 001/2025/03/09" in texto and "001/2025/03/02" not in texto
    assert protocolo.detalhe(c, pid)["corpo_carta"] is None
    # o editado com o campo vale, e fica gravado com o marcador, nunca com a frase
    texto = _carta_montada(c, ids, pid, corpo=marcado.replace("Ficamos à disposição.", "Ficamos à disposição, sempre."))
    assert "Termo de Apostilamento nº 001/2025/03/09" in texto and "sempre" in texto
    gravado = protocolo.detalhe(c, pid)["corpo_carta"]
    assert "{apostilamento}" in gravado and "Termo de Apostilamento" not in gravado


def _cartas(c, cfg):
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='cartas'", (json.dumps(cfg),))
    c.commit()


def test_mapa_do_pacote_so_compara_quando_o_texto_cita_o_termo(cenario):
    """Gate Sol (S3) e revisor (rodada 2 da PR #435): com o texto da familia sem o campo (a producao de hoje), o termo
    que chega depois nao bloqueia, porque o oficio nao muda. Com o campo, o pacote montado sem a frase (antes da 060,
    mapa nulo, ou com o texto de antes) pede montar de novo quando o oficio leva reajuste; so' de execucao, nao."""
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"], termo=False)
    com_campo = carta.config(c)
    sem_campo = json.loads(json.dumps(com_campo))
    sem_campo["familias"]["mtpar"]["carta_corpo"] = com_campo["familias"]["mtpar"]["carta_corpo"].replace(
        "{apostilamento}", "")
    _cartas(c, sem_campo)
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    assert json.loads(protocolo._linha(c, pid)["montado_apostilamentos"]) == {"cita": False, "apostilamentos": []}
    _termo(c, ids["mtpar"])
    assert protocolo.previa_envio(c, [pid])["bloqueio"] is None                     # (D) nada muda no oficio
    _cartas(c, com_campo)                                                             # o Leo poe o campo no texto
    assert protocolo.previa_envio(c, [pid])["bloqueio"] == protocolo.APOSTILAMENTO_MUDOU
    assert FRASE in _carta_montada(c, ids, pid)
    assert protocolo.previa_envio(c, [pid])["bloqueio"] is None
    c.execute("UPDATE protocolos SET montado_apostilamentos=NULL WHERE id=?", (pid,))   # montado antes da 060
    c.commit()
    assert protocolo.previa_envio(c, [pid])["bloqueio"] == protocolo.APOSTILAMENTO_MUDOU
    p_exec = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    protocolo.montar(c, ids["uid"], p_exec)
    c.execute("UPDATE protocolos SET montado_apostilamentos=NULL WHERE id=?", (p_exec,))
    c.commit()
    assert protocolo.previa_envio(c, [p_exec])["bloqueio"] is None


def test_montar_recusa_certidao_vencida_que_iria_no_pacote(cenario):
    # revisor (rodada 2 da PR #435): montado sem a certidao vencida, o pacote sairia sem ela depois da renovacao
    c, ids = cenario
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    c.execute("UPDATE certidoes SET validade='2026-09-10' WHERE tipo_id=?", (documentos.tipo_por_chave(c, "municipal")["id"],))
    c.commit()
    with pytest.raises(ValueError, match="Certidão vencida — renove antes de montar"):
        protocolo.montar(c, ids["uid"], pid)
    assert protocolo.detalhe(c, pid)["situacao"] == "rascunho"


def test_termo_mudando_entre_a_reserva_e_o_envio_nao_sai(cenario, monkeypatch):
    # revisor (rodada 2 da PR #435): depois da reserva, a leitura dos anexos confere de novo o termo, como a FRC
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"])
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    pv = protocolo.previa_envio(c, [pid])
    assert pv["pendencias"] == [] and pv["bloqueio"] is None
    original = protocolo._anexos_rotulados

    def termo_corrigido_depois_da_reserva(conn, p, hoje):
        if p.get("envio_reservado_em") and not conn.execute(
                "SELECT 1 FROM instrumentos WHERE chave='ap-reaj-02'").fetchone():
            _termo(conn, ids["mtpar"], "ap-reaj-02", "001/2025/03/09", data="2026-09-10", corrige="ap-reaj-01")
        return original(conn, p, hoje)

    monkeypatch.setattr(protocolo, "_anexos_rotulados", termo_corrigido_depois_da_reserva)
    with pytest.raises(protocolo.Bloqueio, match="monte o pacote de novo"):
        protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"])
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    p = protocolo._linha(c, pid)
    assert (p["situacao"], p["envio_reservado_em"]) == ("assinado", None)


def test_termo_sem_numero_vira_pendencia_e_pede_justificativa(cenario):
    # gate Sol (rodada 1 da PR #435): o termo sem numero nao se cita; o envio avisa e pede justificativa
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"], termo=False)
    _termo(c, ids["mtpar"], numero=None)
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    assert "Apostilamento" not in protocolo.corpo_padrao(c, pid)
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    pv = protocolo.previa_envio(c, [pid])
    assert [x["mensagem"] for x in pv["pendencias"]] == [
        "O apostilamento que cobre 09/2026 está sem número no cadastro; o ofício sai sem citá-lo"]
    assert pv["exige_justificativa"] is True
    with pytest.raises(ValueError, match="justificativa"):
        protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                         confirmadas=[x["mensagem"] for x in pv["pendencias"]])


def test_justificativa_e_conferida_de_novo_sob_o_lock(cenario, monkeypatch):
    # revisor (rodada 1 da PR #435): o termo some entre a previa e a reserva; a confirmacao do aviso nao basta
    from app import notas_envio
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"])
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    pv = protocolo.previa_envio(c, [pid])
    assert pv["pendencias"] == [] and pv["bloqueio"] is None
    original = notas_envio.recusar_se_espera

    def termo_corrigido_no_meio(conn, m, *a, **k):        # ja' sob o lock: o termo novo nao cobre 09/2026
        conn.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, numero, data, dados) VALUES (?, 'ap-ret', "
                     "'apostilamento_reajuste', '001/2025/03/09', '2026-09-10', ?)",
                     (ids["mtpar"], json.dumps({"data_base": "2025-09", "ciclo": 2026, "percentual": "4,15",
                                                "corrige": "ap-reaj-01", "periodo": {"de": "2027-01", "ate": "2027-08"}})))
        return original(conn, m, *a, **k)

    monkeypatch.setattr(notas_envio, "recusar_se_espera", termo_corrigido_no_meio)
    with pytest.raises(ValueError, match="justificativa"):
        protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                         confirmadas=[SEM_APOSTILAMENTO])
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM instrumentos WHERE chave='ap-ret'").fetchone()[0] == 0     # desfeito


def test_reajuste_sem_apostilamento_avisa_na_montagem_e_o_envio_exige_justificativa(cenario):
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"], termo=False)
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    avisos = [x["mensagem"] for x in protocolo.detalhe(c, pid)["pendencias"] if x["codigo"] == "sem_apostilamento"]
    assert avisos == [SEM_APOSTILAMENTO]                                   # antes de montar
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    pv = protocolo.previa_envio(c, [pid])
    faltam = [x["mensagem"] for x in pv["pendencias"]]
    assert pv["exige_justificativa"] is True and faltam == [SEM_APOSTILAMENTO]
    args = (c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"])
    with pytest.raises(protocolo.ConfirmarPendencias):                      # a confirmacao continua valendo
        protocolo.enviar(*args, justificativa="o órgão pediu a nota antes do termo")
    for curta in (None, "", "   curta  "):
        with pytest.raises(ValueError, match="justificativa"):
            protocolo.enviar(*args, justificativa=curta, confirmadas=faltam)
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    assert protocolo.detalhe(c, pid)["situacao"] == "assinado"
    protocolo.enviar(*args, justificativa="o órgão pediu a nota antes do termo", confirmadas=faltam)
    d = protocolo.detalhe(c, pid)
    assert d["situacao"] == "enviado" and d["justificativa"].startswith("o órgão pediu a nota antes do termo; ")
    assert SEM_APOSTILAMENTO in d["justificativa"]
    # a execucao da mesma competencia e o reajuste da SINFRA (aba do caderno, feito por fora) nao ganham o aviso
    p_exec = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    p_sinfra = protocolo.criar(c, ids["uid"], ids["sinfra"], "medicao", [ids["sinfra_reaj"]], "311")
    for p in (p_exec, p_sinfra):
        assert "sem_apostilamento" not in [x["codigo"] for x in protocolo.detalhe(c, p)["pendencias"]]
        assert protocolo.previa_envio(c, [p])["exige_justificativa"] is False


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


def test_carta_da_ses_le_o_aprovado_senao_o_pedido(tmp_path, monkeypatch):
    """#284 (decisao do Leo de 03/11/2026): o pedido fica congelado; a nota sai pelo aprovado do boletim, e a carta
    da SES ("Nota Fiscal – R$" e as linhas "Sendo") mostra o valor da nota: aprovado, senao pedido."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn()
    db.migrate(c)
    ms = [{"id": 999_001, "numero": 41, "tipo": "execucao", "valor_protocolado_centavos": 12_345_67,
           "valor_atestado_centavos": 12_000_01},
          {"id": 999_002, "numero": 41, "tipo": "reajuste", "valor_protocolado_centavos": 1_000_00,
           "valor_atestado_centavos": None}]
    texto = protocolo._lista(c, {"id": 999_999, "etapa": "unico", "natureza": "execucao"}, "ses", {}, ms)
    c.close()
    linhas = texto.splitlines()
    assert linhas[0] == "1. Nota Fiscal – R$ 13.000,01"
    assert linhas[1:3] == ["   Sendo: 41ª Medição – R$ 12.000,01", "   Sendo: Reajuste da 41ª Medição – R$ 1.000,00"]


# --- issue #448: texto da carta legivel e guardado, sem troca silenciosa da edicao -----------------------------------

def test_texto_editado_a_mao_nunca_e_trocado_pelo_padrao_sem_aviso(cenario):
    """Issue #448 (item 1): com o campo {apostilamento} posto no texto da familia depois, a tela de envio da nota
    (`refazer_texto`) so' troca o gravado que e' o padrao sem o campo; o editado a' mao recusa e diz como por o campo."""
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"])
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    marcado = protocolo.corpo_padrao(c, pid)
    editado = protocolo._sem_linhas_vazias(marcado.replace("{apostilamento}", "Em complemento ao Ofício 777/2026."))
    c.execute("UPDATE protocolos SET corpo_carta=? WHERE id=?", (editado, pid))
    c.commit()
    with pytest.raises(ValueError, match=re.escape(protocolo.MARCADOR_NA_TELA)) as erro:
        protocolo.montar(c, ids["uid"], pid, refazer_texto=True)
    assert "seção Protocolo" in str(erro.value) and "recarregue" not in str(erro.value)
    p = protocolo._linha(c, pid)
    assert (p["corpo_carta"], p["situacao"]) == (editado, "rascunho")
    # a edicao com o campo (como a tela o mostra, convertido de volta) monta e guarda a frase "777/2026"
    texto = _carta_montada(c, ids, pid, corpo=protocolo.da_tela(protocolo.para_tela(
        editado.replace("Em complemento ao Ofício 777/2026.",
                        f"Em complemento ao Ofício 777/2026.\n\n{protocolo.MARCADOR_NA_TELA}"))))
    assert "777/2026" in texto and FRASE in texto


def test_texto_enviado_com_o_padrao_fica_guardado_em_toda_familia(cenario):
    """Issue #448 (itens 2 e 3): o protocolo enviado com o texto padrao guarda o texto que foi ao orgao (com o
    marcador; antes do envio o padrao se refaz com os dados de agora), e a tela o mostra com a frase do termo enviada,
    nunca vazio nem com o marcador."""
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"])
    for mid, oficio, frase in ((ids["mtpar_reaj"], "302", FRASE), (ids["mtpar_exec"], "301", None)):
        pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [mid], oficio)
        padrao = protocolo.corpo_padrao(c, pid)
        protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
        assert protocolo._linha(c, pid)["corpo_carta"] is None
        pv = protocolo.previa_envio(c, [pid])
        protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                         confirmadas=[x["mensagem"] for x in pv["pendencias"]])
        p = protocolo._linha(c, pid)
        assert (p["situacao"], p["corpo_carta"]) == ("enviado", padrao)
        tela = protocolo.texto_da_tela(p)
        assert tela and "{" not in tela and protocolo.MARCADOR_NA_TELA not in tela
        assert (frase in _corrido(tela)) if frase else "Apostilamento" not in tela


def test_citacao_do_termo_escrita_diferente_nao_monta(cenario):
    """Issue #448 (code-review): o marcador legivel escrito errado nao vira campo; nao pode sair cru no oficio."""
    c, ids = cenario
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    corpo = protocolo.corpo_padrao(c, pid).replace("{apostilamento}", "[citacao do termo de apostilamento]")
    with pytest.raises(ValueError, match="escrita diferente"):
        protocolo.montar(c, ids["uid"], pid, corpo=corpo)
    assert protocolo._linha(c, pid)["situacao"] == "rascunho"


def test_reajuste_sem_termo_nao_pede_nova_assinatura(cenario):
    """Issue #448 (item 5): montado sem o mapa (antes da 060), o reajuste sem termo antes e depois nao muda o oficio
    (a frase fica vazia): o envio nao pede montar e assinar de novo."""
    c, ids = cenario
    _data_base_e_termo(c, ids["mtpar"], termo=False)
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_reaj"]], "302")
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    c.execute("UPDATE protocolos SET montado_apostilamentos=NULL WHERE id=?", (pid,))
    c.commit()
    assert protocolo.apostilamento_mudou(c, protocolo._linha(c, pid)) is None
    assert protocolo.previa_envio(c, [pid])["bloqueio"] is None


def test_guid_entre_chaves_do_link_do_sharepoint_nao_e_campo_sem_dado(cenario):
    """Issue #448 (item 6): o link do SharePoint traz o GUID entre chaves (sourcedoc={6C5B...}); nao e' campo."""
    c, ids = cenario
    link = ("https://lotufo.sharepoint.com/:x:/r/sites/x/_layouts/15/Doc.aspx?sourcedoc={6C5B1A2E-0F3D-4C1B-9A8E-"
            "1234567890AB}&file=Planilha.xlsx e {ABCDEF12-0F3D-4C1B-9A8E-1234567890AB}")
    assert protocolo.campos_sem_dado(f"Planilha: {link}") == []
    assert protocolo.campos_sem_dado("Ver {período}, {obra2}, {oficio-barra} e {data.base}") == [
        "{data.base}", "{obra2}", "{oficio-barra}", "{período}"]
    pid = protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")
    protocolo.montar(c, ids["uid"], pid, corpo=f"{protocolo.corpo_padrao(c, pid)}\n\nPlanilha: {link}")
    assert protocolo._linha(c, pid)["situacao"] == "montado"
