"""Carta, capa e divisoria em PDF (bloco 5)."""
import base64
import datetime
import io
import os
import re

import pypdf

import pytest

from app import carta

# Gera PDF com a fonte da lista de candidatas (Arial no Windows e no Mac, Liberation Sans no Linux da CI).
pytestmark = pytest.mark.pdf


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


def _sem_candidatas(monkeypatch, tmp_path):
    monkeypatch.setattr(carta, "_FONTES", ((tmp_path / "nao-existe.ttf", tmp_path / "nao-existe-negrito.ttf"),))
    monkeypatch.delenv("DASH_FONTE_CARTA", raising=False)
    monkeypatch.delenv("DASH_FONTE_CARTA_NEGRITO", raising=False)


def _fonte_real():
    """O par de TTF que esta maquina tem; na CI (variavel CI) a falta dele e' erro, nao pulo (issue #385)."""
    par = carta.fonte_carta()
    if par is None:
        if os.environ.get("CI"):
            pytest.fail("CI sem fonte Unicode para a carta: o job precisa da Liberation Sans (fonts-liberation)")
        pytest.skip("maquina sem Arial nem Liberation Sans")
    return par


def test_sem_candidata_cai_na_helvetica_sem_quebrar(monkeypatch, tmp_path):
    _sem_candidatas(monkeypatch, tmp_path)
    assert carta.fonte_carta() is None
    t = _texto(carta.gerar(_carta()))
    assert "MT-PAR" in t and "CT/301/LT/2026" in t
    assert "099/2024/MTPAR - Complexo Cultural" in t               # plano B latin-1: travessao vira hifen


def test_travessao_sai_no_pdf_com_a_fonte_da_lista():
    _fonte_real()
    t = _texto(carta.gerar(_carta()))
    assert "099/2024/MTPAR – Complexo Cultural" in t
    assert "NF nº 2311" in t and "Nota fiscal – NF" in t


def test_variavel_de_ambiente_aponta_outro_ttf(monkeypatch, tmp_path):
    regular, negrito = _fonte_real()
    _sem_candidatas(monkeypatch, tmp_path)
    (tmp_path / "outra.ttf").write_bytes(regular.read_bytes())
    (tmp_path / "outra-negrito.ttf").write_bytes(negrito.read_bytes())
    monkeypatch.setenv("DASH_FONTE_CARTA", str(tmp_path / "outra.ttf"))
    monkeypatch.setenv("DASH_FONTE_CARTA_NEGRITO", str(tmp_path / "outra-negrito.ttf"))
    assert carta.fonte_carta() == (tmp_path / "outra.ttf", tmp_path / "outra-negrito.ttf")
    assert "MTPAR – Complexo Cultural" in _texto(carta.gerar(_carta()))


def test_variavel_so_com_o_regular_nao_vale(monkeypatch, tmp_path):
    regular, _ = _fonte_real()
    _sem_candidatas(monkeypatch, tmp_path)
    monkeypatch.setenv("DASH_FONTE_CARTA", str(regular))
    assert carta.fonte_carta() is None


def test_primeira_candidata_com_os_dois_arquivos_vence(monkeypatch, tmp_path):
    regular, negrito = _fonte_real()
    _sem_candidatas(monkeypatch, tmp_path)
    so_regular = (regular, tmp_path / "falta.ttf")
    monkeypatch.setattr(carta, "_FONTES", (so_regular, (regular, negrito), (negrito, regular)))
    assert carta.fonte_carta() == (regular, negrito)


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


# --- issue #293: curva S em xlsx anexa a carta de prorrogacao --------------------------------------

def _planilha(dados: bytes):
    import openpyxl
    return openpyxl.load_workbook(io.BytesIO(dados)).active


def test_curva_s_em_xlsx_abre_com_as_colunas_e_os_valores():
    """Spec 2026-10-20 §4 item 3 e D9: competencia, previsto vigente, previsto anterior a ultima repactuacao e
    medido, acumulados; o centavo inteiro vira real uma vez so', na celula (sem arredondar de novo)."""
    linhas = [{"competencia": "2025-12", "previsto_vigente_centavos": 100_000_00,
               "previsto_anterior_centavos": 120_000_00, "medido_centavos": 90_123_45},
              {"competencia": "2026-01", "previsto_vigente_centavos": 250_000_01,
               "previsto_anterior_centavos": 300_000_00, "medido_centavos": None}]
    ws = _planilha(carta.curva_s_xlsx(linhas))
    assert ws.title == "Curva S"
    assert [x.value for x in ws[1]] == ["Competência", "Previsto vigente", "Previsto anterior", "Medido"]
    assert [[x.value for x in linha] for linha in ws.iter_rows(min_row=2)] == [
        [datetime.datetime(2025, 12, 1), 100000, 120000, 90123.45],
        [datetime.datetime(2026, 1, 1), 250000.01, 300000, None]]          # depois do ultimo mes medido, vazio
    assert ws["A2"].number_format == "mm/yyyy"
    assert {ws[f"{col}2"].number_format for col in "BCD"} == {"#,##0.00"}


def test_curva_s_mesmas_linhas_dao_os_mesmos_bytes(monkeypatch):
    """Rodada 2 da PR #436: o sha256 do xlsx e' a impressao da curva; o relogio nao pode muda-lo."""
    import time
    linhas = [{"competencia": "2026-03", "previsto_vigente_centavos": 1_00, "previsto_anterior_centavos": None,
               "medido_centavos": 50}]
    monkeypatch.setattr(time, "time", lambda: 1_700_000_000.0)
    antes = carta.curva_s_xlsx(linhas)
    monkeypatch.setattr(time, "time", lambda: 1_800_000_000.0)
    assert carta.curva_s_xlsx(linhas) == antes
    assert carta.curva_s_xlsx([{**linhas[0], "medido_centavos": 51}]) != antes


def test_curva_s_sem_repactuacao_deixa_o_previsto_anterior_vazio():
    ws = _planilha(carta.curva_s_xlsx([{"competencia": "2026-03", "previsto_vigente_centavos": 1_00,
                                        "previsto_anterior_centavos": None, "medido_centavos": 50}]))
    assert [x.value for x in ws[1]] == ["Competência", "Previsto vigente", "Previsto anterior", "Medido"]
    assert [x.value for x in ws[2]] == [datetime.datetime(2026, 3, 1), 1, None, 0.5]


def test_curva_s_lida_de_volta_da_o_conteudo_em_centavos_mesmo_salva_pelo_openpyxl_comum():
    """Issue #447: a conferencia compara o conteudo (competencia e centavos inteiros), nao os bytes; o mesmo xlsx
    salvo pelo `wb.save` comum (outra data no zip e nas propriedades) le o mesmo conteudo."""
    import openpyxl
    linhas = [{"competencia": "2025-12", "previsto_vigente_centavos": 100_000_00,
               "previsto_anterior_centavos": 120_000_00, "medido_centavos": 90_123_45},
              {"competencia": "2026-01", "previsto_vigente_centavos": 250_000_01,
               "previsto_anterior_centavos": None, "medido_centavos": None}]
    gerado = carta.curva_s_xlsx(linhas)
    assert carta.ler_curva_s(gerado) == carta.conteudo_curva_s(linhas) == [
        ("2025-12", 100_000_00, 120_000_00, 90_123_45), ("2026-01", 250_000_01, None, None)]
    wb = openpyxl.load_workbook(io.BytesIO(gerado))
    outro = io.BytesIO()
    wb.save(outro)
    assert outro.getvalue() != gerado
    assert carta.ler_curva_s(outro.getvalue()) == carta.conteudo_curva_s(linhas)
    assert carta.ler_curva_s(carta.curva_s_xlsx([{**linhas[0], "medido_centavos": 90_123_46}])) != \
        carta.conteudo_curva_s(linhas[:1])


def test_curva_s_ilegivel_ou_de_outro_formato_recusa():
    import openpyxl
    with pytest.raises(ValueError):
        carta.ler_curva_s(b"PK\x03\x04truncado")
    wb = openpyxl.Workbook()
    wb.active.append(["Outra", "planilha"])
    saida = io.BytesIO()
    wb.save(saida)
    with pytest.raises(ValueError, match="cabeçalho"):
        carta.ler_curva_s(saida.getvalue())


def test_curva_s_lida_em_centavos_exatos_ate_o_teto():
    """Gate Sol na PR #455 (S3): o centavo lido e' o gravado, sem a multiplicacao de float, ate' o teto da curva
    (R$ 10 trilhoes); acima dele, ou com fracao de centavo, a leitura recusa (a curva vira ilegivel, nunca
    "igual com 1 centavo de diferenca")."""
    import random
    sorteio = random.Random(447)
    valores = [1, 7, 99, 101, 10_05, 123_456_789_01, 999_999_999_999_99, carta.TETO_CURVA_S_CENTAVOS - 1] + \
        [sorteio.randrange(carta.TETO_CURVA_S_CENTAVOS) for _ in range(300)]
    linhas = [{"competencia": f"{2000 + i // 12:04d}-{i % 12 + 1:02d}", "previsto_vigente_centavos": v,
               "previsto_anterior_centavos": v, "medido_centavos": v} for i, v in enumerate(valores)]
    assert carta.ler_curva_s(carta.curva_s_xlsx(linhas)) == carta.conteudo_curva_s(linhas)
    for fora in (3585351136095505, carta.TETO_CURVA_S_CENTAVOS):
        with pytest.raises(ValueError):
            carta.ler_curva_s(carta.curva_s_xlsx([{**linhas[0], "medido_centavos": fora}]))
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(carta.curva_s_xlsx(linhas[:1])))
    wb.active["D2"] = 0.001                                     # fracao de centavo nao e' a curva gerada
    saida = io.BytesIO()
    wb.save(saida)
    with pytest.raises(ValueError, match="centavo exato"):
        carta.ler_curva_s(saida.getvalue())


# --- rodape do emitente sem o "L" e largura do logo (issue #566) ------------------------------------

_CINZA_DO_L = b"0.8 0.8 0.8 rg"          # set_fill_color(204, 204, 204): a cor do "L" do papel da Lotufo


def _conteudo(pdf: bytes) -> bytes:
    return pypdf.PdfReader(io.BytesIO(pdf)).pages[0].get_contents().get_data()


def _largura_do_logo_mm(pdf: bytes) -> float:
    m = re.search(rb"q ([\d.]+) 0 0 [\d.]+ [\d.]+ [\d.]+ cm /I\d+ Do Q", _conteudo(pdf))
    assert m, "logo nao desenhado"
    return float(m.group(1)) * 25.4 / 72


def _logo_faixa(pasta, nome="faixa.png", largura_px=40, altura_px=10):
    """Logo em faixa (4:1 por padrao), como o dos consorcios; o `_logo_sintetico` e' quadrado."""
    from PIL import Image
    Image.new("RGB", (largura_px, altura_px), (79, 70, 229)).save(pasta / nome)
    return nome


def _consorcio(pasta, **mudar):
    e = {"razao_social": "CONSORCIO EXEMPLO", "cnpj": "00.000.000/0001-00", "ie": "11.111.111-1",
         "endereco": "Rua do Consorcio, 10 - Cuiaba/MT", "contato": "Tel.: (00) 1111-1111",
         "logo": _logo_faixa(pasta)}
    e.update(mudar)
    return e


def test_emitente_sem_fundo_e_com_rodape_sai_com_o_rodape_e_sem_o_l(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    emitente = _consorcio(tmp_path, fundo=False, rodape=True)
    pdf = carta.gerar(_carta(emitente=emitente))
    texto = _texto(pdf)
    for parte in ("CONSORCIO EXEMPLO", "Rua do Consorcio, 10", "11.111.111-1", "Tel.: (00) 1111-1111"):
        assert parte in texto
    assert _CINZA_DO_L not in _conteudo(pdf)
    doc = carta._Doc(emitente)
    assert doc.l_margin == 25 and 297 - doc.b_margin <= 270      # o corpo para antes do rodape (272 mm)


def test_emitente_sem_fundo_e_sem_rodape_continua_sem_rodape(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    pdf = carta.gerar(_carta(emitente=_consorcio(tmp_path, fundo=False)))
    assert "Rua do Consorcio" not in _texto(pdf)
    assert _CINZA_DO_L not in _conteudo(pdf)


def test_carta_da_lotufo_com_fundo_continua_com_o_l_o_rodape_e_o_logo_de_58_mm(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    emitente = _consorcio(tmp_path, fundo=True)
    pdf = carta.gerar(_carta(emitente=emitente))
    assert _CINZA_DO_L in _conteudo(pdf)
    assert "Rua do Consorcio, 10" in _texto(pdf)
    assert _largura_do_logo_mm(pdf) == pytest.approx(58, abs=0.01)
    doc = carta._Doc(emitente)
    assert (doc.l_margin, doc.b_margin) == (33, 42)


def test_logo_com_largura_configurada_sai_nessa_largura(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    pdf = carta.gerar(_carta(emitente=_consorcio(tmp_path, logo_largura_mm=120)))
    assert _largura_do_logo_mm(pdf) == pytest.approx(120, abs=0.01)


def test_logo_alto_empurra_o_corpo_para_baixo_dele(tmp_path, monkeypatch):
    """O PNG sintetico e' quadrado: com 40 mm de largura vai de 6 a 46 mm, e o corpo comeca abaixo dele."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    pdf = carta.gerar(_carta(emitente=_consorcio(tmp_path, logo=_logo_sintetico(tmp_path), logo_largura_mm=40)))
    primeira_y = max(float(y) for y in re.findall(rb"BT [\d.]+ ([\d.]+) Td", _conteudo(pdf)))
    assert (841.89 - primeira_y) * 25.4 / 72 > 46


def test_logo_alto_demais_e_reduzido_ao_teto_de_altura_e_a_carta_sai(tmp_path, monkeypatch):
    """Quadrado com 150 mm de largura iria ate' 156 mm de altura e empurraria o corpo para fora da pagina."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    emitente = _consorcio(tmp_path, logo=_logo_sintetico(tmp_path), logo_largura_mm=150, rodape=True)
    pdf = carta.gerar(_carta(emitente=emitente))
    assert _largura_do_logo_mm(pdf) == pytest.approx(carta.LOGO_ALTURA_MAX_MM, abs=0.01)
    assert "Prezada Senhora" in _texto(pdf)
    assert _imagens(carta.pagina_titulo(["CAPA"], emitente)) == 1


def test_rodape_sem_logo_nao_repete_os_dados_do_cabecalho_de_texto(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    pdf = carta.gerar(_carta(emitente=_consorcio(tmp_path, logo=None, rodape=True)))
    texto = _texto(pdf)
    assert texto.count("CONSORCIO EXEMPLO") == 1                     # so' o cabecalho de texto
    assert "Tel.: (00) 1111-1111" not in texto
