"""Carta, capa e divisoria em PDF (bloco 5)."""
import base64
import datetime
import io

import pypdf

from app import carta


def _texto(pdf: bytes) -> str:
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def _carta(**mudar):
    base = dict(numero="CT/301/LT/2026", local_data="Cuiabá/MT, 16 de setembro de 2026.",
                destinatario=["A MT PARTICIPAÇÕES E PROJETOS S.A – MT-PAR"],
                ac=["A/C: Beatriz Exemplo", "Engenheira Fiscal"],
                referencia="Ref.: Contrato n.º 099/2024/MTPAR – Complexo Cultural",
                assunto="Asst.: 23ª Medição contratual (01/08/2026 a 31/08/2026)",
                vocativo="Prezada Senhora,",
                corpo="A LOTUFO encaminha os arquivos da 23ª Medição:\n\ni. Nota fiscal – NF nº 2311\n"
                      "ii. Certidões de regularidade fiscal\n\n# 2. DO PEDIDO\n\nCertos de contar com a usual brevidade.",
                assinatura=["Fernando Exemplo Neto", "Diretor"])
    base.update(mudar)
    return carta.Carta(**base)


def test_carta_leva_os_dados_e_as_marcas_do_corpo():
    t = _texto(carta.gerar(_carta()))
    for trecho in ("CT/301/LT/2026", "16 de setembro de 2026", "A/C: Beatriz Exemplo", "Contrato n.º 099/2024/MTPAR",
                   "23ª Medição contratual", "i. Nota fiscal", "ii. Certidões", "2. DO PEDIDO", "Fernando Exemplo Neto"):
        assert trecho in t, trecho
    assert "# 2." not in t                        # a marca de titulo nao vai para o papel


def test_sem_arial_cai_na_helvetica_sem_quebrar(monkeypatch, tmp_path):
    monkeypatch.setattr(carta, "_ARIAL", tmp_path / "nao-existe.ttf")
    t = _texto(carta.gerar(_carta()))
    assert "MT-PAR" in t and "CT/301/LT/2026" in t


def test_pagina_titulo_e_data_extenso_e_preencher():
    assert "NOTA FISCAL" in _texto(carta.pagina_titulo(["NOTA FISCAL"]))
    assert carta.data_extenso(datetime.date(2026, 9, 16)) == "16 de setembro de 2026"
    assert [carta.ordinal_extenso(n) for n in (7, 27, 110)] == ["sétima", "vigésima sétima", "centésima décima"]
    assert carta.objeto_na_frase("EXECUÇÃO DO REMANESCENTE DA OBRA") == "DO REMANESCENTE DA OBRA"
    assert carta.preencher("{medicao} de {obra} ({faltou})", {"medicao": "23ª Medição", "obra": "Cultural"}) \
        == "23ª Medição de Cultural ({faltou})"


def test_fiscal_vigente_e_emitente_sem_cadastro_de_cartas(tmp_path, monkeypatch):
    from app import db
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    c.execute("INSERT INTO contratos (id, orgao, numero_instrumento, objeto, valor_original_centavos) "
              "VALUES (1,'SINFRA','IC 1','Obra',100)")
    for nome, desde in (("Antigo", "2026-01-01"), ("Novo", "2026-09-16")):
        c.execute("INSERT INTO contrato_fiscais (contrato_id, nome, email, desde) VALUES (1,?,?,?)",
                  (nome, f"{nome}@exemplo.gov.br", desde))
    c.commit()
    assert carta.fiscal_vigente(c, 1, "2026-09-15")["nome"] == "Antigo"
    assert carta.fiscal_vigente(c, 1, "2026-09-16")["nome"] == "Novo"
    em = carta.emitente(c, 1)                          # Lotufo semeada na migracao, sem cartas.yaml aplicado
    assert em["cnpj"] == "31.200.101/0001-30" and em["razao_social"]
    c.close()


def _imagens(pdf: bytes) -> int:
    return sum(len(p.images) for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)


_PNG_MINIMO = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _logo_sintetico(pasta, nome="logo.png"):
    (pasta / nome).write_bytes(_PNG_MINIMO)
    return nome


def test_emitente_com_logo_leva_a_imagem_na_carta(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))      # a pasta de dados e' a do banco
    emitente = {"razao_social": "Consorcio Exemplo", "logo": _logo_sintetico(tmp_path)}
    pdf = carta.gerar(_carta(emitente=emitente))
    assert _imagens(pdf) == 1
    assert "Consorcio Exemplo" not in _texto(pdf)                    # com logo, sem cabecalho de texto


def test_emitente_sem_logo_sai_com_cabecalho_de_texto(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    pdf = carta.gerar(_carta(emitente={"razao_social": "Consorcio Exemplo", "cnpj": "00.000.000/0001-00"}))
    assert _imagens(pdf) == 0
    assert "Consorcio Exemplo" in _texto(pdf)


def test_logo_inexistente_sai_sem_logo(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    pdf = carta.gerar(_carta(emitente={"razao_social": "Consorcio Exemplo", "logo": "nao-existe.png", "fundo": True}))
    assert _imagens(pdf) == 0
    assert "Consorcio Exemplo" in _texto(pdf)                        # cai no cabecalho de texto, sem erro


def test_logo_fora_da_pasta_de_dados_e_recusado_mesmo_existindo(tmp_path, monkeypatch):
    dados = tmp_path / "dados"
    dados.mkdir()
    monkeypatch.setenv("DASH_DB_PATH", str(dados / "t.db"))
    _logo_sintetico(tmp_path, "fora.png")                            # imagem valida, so' que fora da pasta de dados
    pdf = carta.gerar(_carta(emitente={"razao_social": "Consorcio Exemplo", "logo": "../fora.png"}))
    assert _imagens(pdf) == 0
    assert "Consorcio Exemplo" in _texto(pdf)


def test_corpo_da_reiteracao_familia_b_preenche_todos_os_campos():
    """Issue #277: a reiteracao do pleito de reajuste (familia B) tem corpo proprio no cartas.yaml, que cita o
    oficio anterior, a data dele e ha' quantos dias esta' sem resposta."""
    import pathlib

    import yaml
    cartas = yaml.safe_load((pathlib.Path(__file__).parents[2] / "cadastro-exemplo" / "cartas.yaml")
                            .read_text(encoding="utf-8"))
    textos = cartas["pleito_reiteracao"]
    campos = {"razao_social": "CONSTRUTORA EXEMPLO LTDA", "cnpj": "31.200.101/0001-30", "objeto": "DA OBRA ALFA",
              "instrumento": "099/2024", "oficio_anterior": "CT/068/LT/2026", "data_oficio_anterior": "27/02/2026",
              "dias_sem_resposta": "202", "data_base_extenso": "MARÇO/2024", "mes_aniversario": "MARÇO",
              "oficio": "CT-245-LT-2026", "obra": "Obra Alfa", "saudacao": "Bom dia,"}
    for chave in ("carta_assunto", "carta_corpo", "email_assunto", "email_corpo"):
        assert "{" not in carta.preencher(textos[chave], campos), chave        # nenhum campo sobrando
    corpo = carta.preencher(textos["carta_corpo"], campos)
    assert "CT/068/LT/2026, de 27/02/2026" in corpo and "202 dias" in corpo
    assert corpo != carta.preencher(cartas["pleito_reajuste"]["carta_corpo"], campos)     # nao e' a familia A
    t = _texto(carta.gerar(_carta(corpo=corpo, assunto=carta.preencher(textos["carta_assunto"], campos))))
    assert "reiteração" in t and "CT/068/LT/2026" in t
