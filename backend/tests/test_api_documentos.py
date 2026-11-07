"""Rotas dos documentos de protocolo (bloco 4): ler, gravar (lida ou digitada), regularidade, ZIP."""
import datetime
import io
import pathlib
import zipfile

import pytest

from app import db, leitura_pdf, tempo
from tests.conftest import _pdf_com_texto

FIX = pathlib.Path(__file__).parent / "fixtures" / "certidoes"


@pytest.fixture(autouse=True)
def hoje(monkeypatch):
    monkeypatch.setattr(tempo, "hoje_local", lambda: datetime.date(2026, 9, 23))


def _texto(monkeypatch, nome_ou_texto):
    arq = FIX / f"{nome_ou_texto}.txt"
    texto = arq.read_text(encoding="utf-8") if nome_ou_texto and arq.exists() else nome_ou_texto
    monkeypatch.setattr(leitura_pdf, "texto_de_pdf_com_limite", lambda pdf: texto)
    monkeypatch.setattr(leitura_pdf, "primeira_pagina_com_limite", lambda pdf: texto)


def _arq(nome="c.pdf"):
    return {"arquivo": (nome, _pdf_com_texto("x"), "application/pdf")}


def test_ler_e_gravar_automatico(client_admin, monkeypatch):
    _texto(monkeypatch, "trabalhista-alfa")
    r = client_admin.post("/api/documentos/certidoes/ler", files=_arq())
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["leitura"]["tipo"] == "trabalhista" and r.json()["leitura"]["entidade_id"] == 1
    g = client_admin.post("/api/documentos/certidoes", files=_arq("cndt.pdf"),
                          data={"tipo": "federal", "validade": "2030-01-01"})      # ignorados: a leitura manda
    assert g.status_code == 201, g.text
    assert (g.json()["leitura"], g.json()["tipo"], g.json()["validade"]) == ("automatica", "trabalhista", "2026-12-21")
    assert client_admin.post("/api/documentos/certidoes", files=_arq("cndt.pdf")).status_code == 409


def test_positiva_e_recusada_mesmo_com_campos(client_admin, monkeypatch):
    _texto(monkeypatch, "estadual-beta-cpd")
    r = client_admin.post("/api/documentos/certidoes/ler", files=_arq())
    # a natureza e' conferida antes da empresa: a Guaxe nem precisa estar no banco de teste
    assert (r.json()["ok"], r.json()["motivo"], r.json()["digitavel"]) == (False, "positiva", False)
    g = client_admin.post("/api/documentos/certidoes", files=_arq(),
                          data={"entidade_id": "1", "tipo": "estadual", "emissao": "2026-06-24",
                                "validade": "2026-08-22", "natureza": "negativa"})
    assert g.status_code == 422


def test_recusa_nao_deixa_pdf_no_disco(client_admin, monkeypatch):
    from app import arquivos
    _texto(monkeypatch, "estadual-beta-cpd")
    antes = set(arquivos.pasta_certidoes().glob("*.pdf"))
    assert client_admin.post("/api/documentos/certidoes", files=_arq()).status_code == 422
    assert set(arquivos.pasta_certidoes().glob("*.pdf")) == antes


def test_sem_texto_vira_digitacao(client_admin, monkeypatch):
    _texto(monkeypatch, "")
    r = client_admin.post("/api/documentos/certidoes/ler", files=_arq())
    assert (r.json()["ok"], r.json()["motivo"], r.json()["digitavel"]) == (False, "sem-texto", True)
    assert client_admin.post("/api/documentos/certidoes", files=_arq()).status_code == 422   # sem campos
    g = client_admin.post("/api/documentos/certidoes", files=_arq(),
                          data={"entidade_id": "1", "tipo": "falencia", "emissao": "2026-08-03", "natureza": "negativa"})
    assert g.status_code == 201 and g.json()["leitura"] == "manual" and g.json()["validade"] == "2026-09-14"


def test_sem_texto_passa_pelo_ocr_e_grava_com_a_marca(client_admin, monkeypatch):
    from app import db
    _texto(monkeypatch, "")
    ocr = (FIX / "trabalhista-alfa.txt").read_text(encoding="utf-8")
    monkeypatch.setattr(leitura_pdf, "texto_por_ocr_com_limite", lambda pdf: ocr)
    r = client_admin.post("/api/documentos/certidoes/ler", files=_arq())
    assert r.json()["ok"] is True and r.json()["leitura"]["ocr"] is True
    g = client_admin.post("/api/documentos/certidoes", files=_arq())
    assert g.status_code == 201 and (g.json()["leitura"], g.json()["ocr"]) == ("automatica", True)
    c = db.get_conn()
    assert c.execute("SELECT observacao FROM certidoes WHERE id=?", (g.json()["id"],)).fetchone()[0] == "lida por OCR"
    c.close()


def test_regularidade_usa_a_competencia_impressa_no_pdf(client_admin, monkeypatch):
    # cabecalho real da folha do Consorcio Integra (extrator cola o codigo da empresa na data)
    _texto(monkeypatch, "31.200.303/0001-81 Centro Custo:Todos Emissão: 1Seção:Comp: 31/08/2026 12:45:55 "
                        "Cx: V.12.1.2510.215CONSÓRCIO INTEGRA BRT 4.001.00108/2026 Per:0 Chapa - Nome")
    monkeypatch.setattr(tempo, "hoje_local", lambda: datetime.date(2026, 10, 9))
    # o mes sugerido (antes do dia 10: 07/2026) nao bate com o PDF: recusa dizendo qual e' o certo
    r = client_admin.post("/api/documentos/regularidades", files=_arq("082026 - CONSÓRCIO INTEGRA BRT.pdf"),
                          data={"entidade_id": "1", "competencia": "2026-07"})
    assert r.status_code == 422 and "08/2026" in r.json()["detail"]
    # botao do envio (sem competencia): grava a do PDF
    r = client_admin.post("/api/documentos/regularidades", files=_arq("082026 - CONSÓRCIO INTEGRA BRT.pdf"),
                          data={"entidade_id": "1"})
    assert r.status_code == 201, r.text
    c = db.get_conn()
    assert c.execute("SELECT competencia FROM regularidades WHERE id=?", (r.json()["id"],)).fetchone()[0] == "2026-08"
    c.close()
    # PDF sem cabecalho e sem mes informado: pede o mes
    _texto(monkeypatch, "documento sem cabecalho")
    r = client_admin.post("/api/documentos/regularidades", files=_arq("y.pdf"), data={"entidade_id": "1"})
    assert r.status_code == 422 and "informe o mês" in r.json()["detail"]


def test_regularidade_e_zip(client_admin, monkeypatch):
    r = client_admin.post("/api/documentos/regularidades", files=_arq("072026 - LOTUFO ENGENHARIA.pdf"),
                          data={"entidade_id": "1", "competencia": "2026-07"})
    assert r.status_code == 201, r.text
    assert client_admin.get(f"/api/documentos/regularidades/{r.json()['id']}/arquivo").status_code == 200
    assert client_admin.post("/api/documentos/regularidades", files=_arq(),
                             data={"entidade_id": "1", "competencia": "07/2026"}).status_code == 422
    _texto(monkeypatch, "fgts-alfa")
    monkeypatch.setattr(tempo, "hoje_local", lambda: datetime.date(2026, 8, 1))
    assert client_admin.post("/api/documentos/certidoes", files=_arq()).status_code == 201
    z = client_admin.get("/api/documentos/zip", params={"entidade_id": 1, "data": "2026-08-01"})
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    assert zipfile.ZipFile(io.BytesIO(z.content)).namelist()[0].endswith("FGTS - 2026-08-09.pdf")
    assert client_admin.get("/api/documentos/zip", params={"entidade_id": 1, "data": "2026-12-01"}).status_code == 422


def test_painel_lista_a_empresa_com_documento(client_admin, monkeypatch):
    _texto(monkeypatch, "trabalhista-alfa")
    client_admin.post("/api/documentos/certidoes", files=_arq())
    p = client_admin.get("/api/documentos").json()
    lotufo = next(e for e in p["empresas"] if e["entidade_id"] == 1)
    trab = next(c for c in lotufo["certidoes"] if c["chave"] == "trabalhista")
    assert trab["situacao"] == "ok" and trab["link_emissao"].startswith("https://")


def test_rotas_antigas_de_leitura_e_upload_sairam(client_admin):
    assert client_admin.post("/api/certidoes/ler-pdf", files=_arq()).status_code in (404, 405)
    assert client_admin.post("/api/certidoes/upload", files=_arq()).status_code in (404, 405)


# --- testes de quebra 10/10/2026, A-19: certidao digitada com validade absurda ---

def _manual(client_admin, emissao, validade, tipo="municipal"):
    return client_admin.post("/api/documentos/certidoes", files=_arq(), data={
        "entidade_id": "1", "tipo": tipo, "emissao": emissao, "validade": validade, "natureza": "negativa"})


def test_digitada_com_validade_de_2099_e_recusada(client_admin, monkeypatch):
    _texto(monkeypatch, "")
    r = _manual(client_admin, "2026-09-01", "2099-12-31")
    assert r.status_code == 422
    assert r.json()["detail"] == ("Validade de 26784 dias passa do máximo de 95 para certidão municipal: "
                                  "confira as datas no documento")
    conn = db.get_conn()
    try:
        assert conn.execute("SELECT COUNT(*) FROM certidoes WHERE validade='2099-12-31'").fetchone()[0] == 0
    finally:
        conn.close()


# Gate Sol S5 (10/10/2026): teto por tipo, pelos prazos reais das certidoes de producao mais uma folga.
TETOS = {"federal": (185, "federal"), "trabalhista": (185, "trabalhista"), "estadual": (65, "estadual"),
         "municipal": (95, "municipal"), "fgts": (35, "FGTS"), "falencia": (60, "falência")}


@pytest.mark.parametrize("tipo", sorted(TETOS))
def test_digitada_no_teto_do_tipo_passa_e_um_dia_a_mais_nao(client_admin, monkeypatch, tipo):
    _texto(monkeypatch, "")
    teto, rotulo = TETOS[tipo]
    emissao = datetime.date(2026, 9, 1)
    r = _manual(client_admin, emissao.isoformat(), (emissao + datetime.timedelta(days=teto + 1)).isoformat(), tipo)
    assert r.status_code == 422
    assert r.json()["detail"] == (f"Validade de {teto + 1} dias passa do máximo de {teto} para certidão {rotulo}: "
                                  "confira as datas no documento")
    r = _manual(client_admin, emissao.isoformat(), (emissao + datetime.timedelta(days=teto)).isoformat(), tipo)
    assert r.status_code == 201, r.text
    assert r.json()["leitura"] == "manual"


def test_digitada_com_emissao_futura_e_recusada(client_admin, monkeypatch):
    _texto(monkeypatch, "")
    r = _manual(client_admin, "2026-09-24", "2026-10-24")          # hoje e' 23/09
    assert r.status_code == 422 and "futura" in r.json()["detail"]


def _cndt_com_validade(validade_br):
    return (FIX / "trabalhista-alfa.txt").read_text(encoding="utf-8").replace(
        "Validade: 21/12/2026", f"Validade: {validade_br}")


def test_lida_com_datas_implausiveis_vira_digitacao_pre_preenchida(client_admin, monkeypatch):
    """Gate Sol S6 (10/10/2026): OCR que le 2028 onde era 2026 nao instala uma vigente errada."""
    _texto(monkeypatch, _cndt_com_validade("21/12/2028"))
    r = client_admin.post("/api/documentos/certidoes/ler", files=_arq()).json()
    assert (r["ok"], r["motivo"], r["digitavel"]) == (False, "datas-implausiveis", True)
    assert r["mensagem"] == ("As datas lidas (emissão 24/06/2026, validade 21/12/2028) não batem com o prazo normal "
                             "desta certidão: confira no documento e digite")
    assert r["lidos"] == {"entidade_id": 1, "tipo": "trabalhista", "emissao": "2026-06-24", "validade": "2028-12-21",
                          "natureza": "negativa"}
    assert client_admin.post("/api/documentos/certidoes", files=_arq("cndt.pdf")).status_code == 422
    conn = db.get_conn()
    try:
        assert conn.execute("SELECT COUNT(*) FROM certidoes WHERE validade='2028-12-21'").fetchone()[0] == 0
    finally:
        conn.close()


def test_lida_com_emissao_futura_vira_digitacao(client_admin, monkeypatch):
    monkeypatch.setattr(tempo, "hoje_local", lambda: datetime.date(2026, 6, 1))     # antes da expedicao (24/06)
    _texto(monkeypatch, "trabalhista-alfa")
    r = client_admin.post("/api/documentos/certidoes/ler", files=_arq()).json()
    assert (r["ok"], r["motivo"]) == (False, "datas-implausiveis")


def test_digitada_com_validade_antes_da_emissao_e_recusada(client_admin, monkeypatch):
    """Gate Sol S4 (refutado, 10/10/2026): a rota ja' recusa validade <= emissao, logo depois de dados_manuais."""
    _texto(monkeypatch, "")
    r = _manual(client_admin, "2026-09-01", "2026-08-31")
    assert r.status_code == 422 and "posterior à emissão" in r.json()["detail"]


def test_regularidade_com_digito_arabe_indico_da_422(client_admin):
    r"""A-14 (testes de quebra 10/10/2026): o padrao da competencia usava `\d`, que casa "٢٠٢٦-08"."""
    r = client_admin.post("/api/documentos/regularidades", files=_arq("072026 - LOTUFO ENGENHARIA.pdf"),
                          data={"entidade_id": "1", "competencia": "٢٠٢٦-08"})
    assert r.status_code == 422
    assert any(e["loc"][-1] == "competencia" for e in r.json()["detail"]), r.text


def test_pdf_corrompido_recusa_sem_o_nome_da_excecao(client_admin):
    """B-08 (10/10/2026): a recusa dizia "PDF inválido ou corrompido (ValueError)"."""
    r = client_admin.post("/api/documentos/certidoes/ler",
                          files={"arquivo": ("c.pdf", b"%PDF-1.4\n" + b"x" * 4096, "application/pdf")})
    assert r.status_code == 415
    assert r.json()["detail"] == "PDF inválido ou corrompido — envie o arquivo original emitido pelo órgão"


# --- "Anexar PDF" unico (issue #513) ----------------------------------------------------------------------

_FOLHA = "LOTUFO ENGENHARIA E CONSTRUÇÕES LTDA 4.001.00108/2026 Per:0 Chapa - Nome"


def test_anexar_distingue_certidao_de_regularidade_pelo_conteudo(client_admin, monkeypatch):
    # certidao: o mesmo caminho da leitura de hoje, marcada como certidao
    _texto(monkeypatch, "trabalhista-alfa")
    r = client_admin.post("/api/documentos/anexar/ler", files=_arq("qualquer.pdf")).json()
    assert r["ok"] is True and r["documento"] == "certidao" and r["leitura"]["tipo"] == "trabalhista"
    g = client_admin.post("/api/documentos/anexar", files=_arq("qualquer.pdf"))
    assert g.status_code == 201 and g.json()["documento"] == "certidao" and g.json()["tipo"] == "trabalhista"
    # folha do DP: o nome do arquivo nao importa, a competencia e a empresa vem do cabecalho
    _texto(monkeypatch, _FOLHA)
    r = client_admin.post("/api/documentos/anexar/ler", files=_arq("x.pdf")).json()
    assert r["ok"] is True and r["documento"] == "regularidade"
    assert (r["leitura"]["competencia"], r["leitura"]["entidade_id"]) == ("2026-08", 1)
    g = client_admin.post("/api/documentos/anexar", files=_arq("x.pdf"))
    assert g.status_code == 201, g.text
    assert (g.json()["documento"], g.json()["competencia"]) == ("regularidade", "2026-08")
    c = db.get_conn()
    assert c.execute("SELECT entidade_id, competencia FROM regularidades").fetchall()[0][:] == (1, "2026-08")
    c.close()
    assert client_admin.post("/api/documentos/anexar", files=_arq("x.pdf")).status_code == 422   # mesmo arquivo


def test_anexar_folha_de_empresa_desconhecida_cai_na_fila_humana_sem_gravar(client_admin, monkeypatch):
    _texto(monkeypatch, "EMPRESA QUE NAO EXISTE LTDA 4.001.00108/2026 Per:0 Chapa - Nome")
    r = client_admin.post("/api/documentos/anexar/ler", files=_arq()).json()
    assert (r["ok"], r["motivo"], r["digitavel"]) == (False, "regularidade-sem-empresa", False)
    assert client_admin.post("/api/documentos/anexar", files=_arq()).status_code == 422
    c = db.get_conn()
    assert c.execute("SELECT COUNT(*) FROM regularidades").fetchone()[0] == 0
    c.close()


def test_anexar_folha_que_cita_duas_empresas_nao_adivinha(client_admin, monkeypatch):
    # folha do consorcio com a lider no cabecalho: o nome mais longo nao decide, cai na fila humana
    c = db.get_conn()
    c.execute("INSERT INTO entidades (id, nome, cnpj, papel, nome_curto) VALUES "
              "(2, 'Consórcio Integra BRT', '31200303000181', 'consorcio', 'Integra BRT')")
    c.commit(); c.close()
    _texto(monkeypatch, "CONSÓRCIO INTEGRA BRT LOTUFO ENGENHARIA E CONSTRUÇÕES LTDA 4.001.00108/2026 Per:0 Chapa - Nome")
    r = client_admin.post("/api/documentos/anexar/ler", files=_arq()).json()
    assert (r["ok"], r["motivo"]) == (False, "regularidade-sem-empresa")
    assert client_admin.post("/api/documentos/anexar", files=_arq()).status_code == 422
