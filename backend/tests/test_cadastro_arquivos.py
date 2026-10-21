import pytest
import yaml

from app import cadastro_arquivos as ca

ORGAO = {"chave": "sinfra-suef1", "nome": "SINFRA - SUEF I", "familia": "sinfra",
         "protocolo_para": ["suef1@orgao-a.exemplo.com.br"], "folga_vigencia_dias": 90,
         "vigencia_automatica": True, "documentos_medicao": ["federal", "fgts"]}
ENTIDADE = {"chave": "lotufo", "nome": "Lotufo Engenharia e Construções Ltda",
            "cnpj": "31.200.101/0001-30", "papel": "lotufo", "coligada_rm": 1, "sigla_oficio": "LT"}
CONTRATO = {"nome_curto": "MT-402", "numero_instrumento": "019/2024/00/00-SINFRA",
            "orgao": "sinfra-suef1", "entidade": "lotufo", "objeto": "Remanescente da MT-402",
            "lei": "14.133", "valor_original": "15.127.200,00", "percentual_lotufo": "100",
            "execucao_fim": "2026-08-28", "vigencia_fim": "2026-11-22", "status": "ativo",
            "datas_base": [{"mes": "2023-04", "indice": "setorial FGV/DNIT"}],
            "instrumentos": [{"chave": "carga-legado", "tipo": "aditivo_valor", "data": "2026-08-04",
                              "delta_valor": "3.236.067,18", "objeto": "Carga inicial"}]}


def _escrever(raiz, orgaos=None, entidades=None, contratos=None):
    (raiz / "contratos").mkdir(parents=True, exist_ok=True)
    (raiz / "orgaos.yaml").write_text(yaml.safe_dump(orgaos or [ORGAO], allow_unicode=True), "utf-8")
    (raiz / "entidades.yaml").write_text(yaml.safe_dump(entidades or [ENTIDADE], allow_unicode=True), "utf-8")
    for c in (contratos if contratos is not None else [CONTRATO]):
        nome = c.get("_arquivo") or c["nome_curto"].lower()
        corpo = {k: v for k, v in c.items() if k != "_arquivo"}
        (raiz / "contratos" / f"{nome}.yaml").write_text(yaml.safe_dump(corpo, allow_unicode=True), "utf-8")
    return raiz


def _erros(raiz):
    with pytest.raises(ca.CadastroInvalido) as e:
        ca.preparar(raiz)
    return e.value.erros


def test_cadastro_minimo_normaliza(tmp_path):
    cad = ca.preparar(_escrever(tmp_path))
    c = cad["contratos"][0]
    assert c["valor_original_centavos"] == 1512720000
    assert c["percentual_direito_bp"] == 10000
    assert c["execucao_fim"] == "2026-08-28"
    assert c["instrumentos"][0]["delta_valor_centavos"] == 323606718
    assert cad["entidades"][0]["cnpj"] == "31200101000130"
    assert cad["orgaos"][0]["regras"]["folga_vigencia_dias"] == 90
    assert cad["avisos"] == []


def test_cnpj_com_dv_errado_e_erro(tmp_path):
    erros = _erros(_escrever(tmp_path, entidades=[{**ENTIDADE, "cnpj": "31.200.101/0001-31"}]))
    assert any("cnpj" in e.lower() for e in erros)


def test_orgao_inexistente_e_erro(tmp_path):
    erros = _erros(_escrever(tmp_path, contratos=[{**CONTRATO, "orgao": "nao-existe"}]))
    assert any("nao-existe" in e for e in erros)


def test_nome_do_arquivo_tem_que_bater_com_nome_curto(tmp_path):
    erros = _erros(_escrever(tmp_path, contratos=[{**CONTRATO, "_arquivo": "outra-obra"}]))
    assert any("nome_curto" in e for e in erros)


def test_arquivo_de_nome_com_acento_e_o_slug_ascii(tmp_path):
    c = {**CONTRATO, "nome_curto": "Coxipó 3ª Etapa", "_arquivo": "coxipo-3a-etapa"}
    assert ca.preparar(_escrever(tmp_path, contratos=[c]))["contratos"][0]["nome_curto"] == "Coxipó 3ª Etapa"


def test_chave_de_instrumento_repetida_e_erro(tmp_path):
    dois = CONTRATO["instrumentos"] * 2
    erros = _erros(_escrever(tmp_path, contratos=[{**CONTRATO, "instrumentos": dois}]))
    assert any("carga-legado" in e for e in erros)


def test_valor_em_formato_americano_e_recusado(tmp_path):
    erros = _erros(_escrever(tmp_path, contratos=[{**CONTRATO, "valor_original": "15127200.00"}]))
    assert any("valor_original" in e for e in erros)


def test_vigencia_antes_da_execucao_e_aviso_nao_erro(tmp_path):
    cad = ca.preparar(_escrever(tmp_path, contratos=[{**CONTRATO, "vigencia_fim": "2026-08-01"}]))
    assert any("vigência" in a.lower() for a in cad["avisos"])


def test_em_encerramento_exige_status_desde(tmp_path):
    erros = _erros(_escrever(tmp_path, contratos=[{**CONTRATO, "status": "em_encerramento"}]))
    assert any("status_desde" in e for e in erros)


# --- bloco 2: geral.yaml, espelho/<slug>.yaml, modelos e emails_faturamento ---------------

import hashlib
import io
import zipfile

from app import espelho
from tests.test_espelho_docx import W, docx_minimo, sdt

REGRA_MT402 = """
contrato: MT-402
situacao: ativa
entradas:
  - {chave: medicao, rotulo: Valor da medição, natureza: medicao}
retencoes:
  mao_de_obra: {percentual: '40', arredondamento: trunc}
  material: {modo: diferenca}
  inss: {percentual: '11', base: mao_de_obra, arredondamento: trunc}
  iss: {percentual: '5', base: mao_de_obra, arredondamento: trunc}
  irrf: {percentual: '1,2', base: total, arredondamento: round}
saidas:
  - {chave: medicao, natureza: medicao, valor: medicao, emissor: lotufo, municipio: Cuiabá, modelo: medicao.docx}
"""

GERAL = ("faturamento:\n  para: [faturista@x.com]\n  copia: [leo@x.com]\n"
         "  assunto: 'Emissão NF - {medicao} ({competencia}) - {obra} - {instrumento}'\n"
         "  corpo: |\n    Bom dia.\n    Seguem espelhos.\n")


def _modelo_completo() -> bytes:
    """Um controle por campo obrigatorio do espelho (docx_minimo so' tem valor e medicao)."""
    corpo = "".join(sdt(t, "xxx") for t in espelho.CAMPOS_MODELO)
    doc = f'<?xml version="1.0"?><w:document {W}><w:body><w:p>{corpo}</w:p></w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        # data fixa: o zip grava a hora de cada entrada (resolucao de 2 s); com ela a mesma chamada
        # em janelas diferentes daria bytes diferentes e o sha256 do teste de hash flutuaria
        z.writestr(zipfile.ZipInfo("word/document.xml", date_time=(2020, 1, 1, 0, 0, 0)), doc)
    return buf.getvalue()


def _com_espelho(raiz, regra=REGRA_MT402, modelo=None):
    (raiz / "espelho").mkdir(exist_ok=True)
    (raiz / "espelho" / "mt-402.yaml").write_text(regra, encoding="utf-8")
    pasta = raiz / "modelos" / "espelho" / "mt-402"; pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "medicao.docx").write_bytes(modelo or _modelo_completo())
    (raiz / "geral.yaml").write_text(GERAL, encoding="utf-8")
    return raiz


def test_espelho_valido_entra_normalizado_com_hash_dos_modelos(tmp_path):
    cad = ca.preparar(_com_espelho(_escrever(tmp_path)))
    e = cad["espelho"][0]
    assert (e["contrato"], e["slug"], e["situacao"]) == ("MT-402", "mt-402", "ativa")
    assert e["regra"]["saidas"][0]["retencoes"]["iss"]["deduz_liquido"] is True
    assert e["modelos"]["medicao"]["sha256"] == hashlib.sha256(_modelo_completo()).hexdigest()
    assert cad["geral"]["faturamento"]["para"] == ["faturista@x.com"]
    assert cad["avisos"] == []


def test_espelho_de_contrato_inexistente_e_modelo_sem_controle_sao_erros(tmp_path):
    raiz = _escrever(tmp_path)
    _com_espelho(raiz, modelo=docx_minimo())
    erros = "\n".join(_erros(raiz))
    assert "medicao.docx" in erros and "material" in erros          # controle faltando
    _com_espelho(raiz, regra=REGRA_MT402.replace("contrato: MT-402", "contrato: MT-999"))
    erros = "\n".join(_erros(raiz))
    assert "MT-999" in erros and "mt-402.yaml" in erros


def test_emissor_desconhecido_e_arquivo_com_slug_errado_sao_erros(tmp_path):
    raiz = _com_espelho(_escrever(tmp_path), regra=REGRA_MT402.replace("emissor: lotufo", "emissor: acme"))
    (raiz / "espelho" / "mt-402.yaml").rename(raiz / "espelho" / "mt402.yaml")
    erros = "\n".join(_erros(raiz))
    assert "acme" in erros and "mt402.yaml" in erros


def test_duas_saidas_com_o_mesmo_nome_de_arquivo_e_erro(tmp_path):
    regra = REGRA_MT402 + "  - {chave: outra, natureza: medicao, valor: medicao, emissor: lotufo, municipio: Cuiabá, modelo: medicao.docx}\n"
    erros = "\n".join(_erros(_com_espelho(_escrever(tmp_path), regra=regra)))
    assert "mesmo arquivo" in erros and "rotulo" in erros


def test_ibs_sem_controle_no_modelo_e_aviso_nao_erro(tmp_path):
    regra = REGRA_MT402.replace("  irrf:", "  ibs: {percentual: '0,1', base: total, arredondamento: round}\n  irrf:")
    cad = ca.preparar(_com_espelho(_escrever(tmp_path), regra=regra))
    assert any("ibs" in a and "medicao.docx" in a for a in cad["avisos"])


def test_geral_faturamento_exige_para_e_assunto(tmp_path):
    raiz = _com_espelho(_escrever(tmp_path))
    (raiz / "geral.yaml").write_text("faturamento:\n  copia: []\n", encoding="utf-8")
    erros = "\n".join(_erros(raiz))
    assert "geral.yaml" in erros and "para" in erros and "assunto" in erros


def test_emails_faturamento_da_entidade_normalizados(tmp_path):
    rivoli = {"chave": "rivoli", "nome": "Rivoli", "cnpj": "11.444.777/0001-61", "papel": "consorciada",
              "emails_faturamento": [" Adm@Zeta.exemplo.com.br "]}
    cad = ca.preparar(_escrever(tmp_path, entidades=[ENTIDADE, rivoli]))
    assert next(e for e in cad["entidades"] if e["chave"] == "rivoli")["emails_faturamento"] == ["adm@zeta.exemplo.com.br"]
    assert cad["entidades"][0]["emails_faturamento"] == []
    assert cad["geral"] is None and cad["espelho"] == []


def test_copia_extras_do_contrato_normalizada_e_validada(tmp_path):
    cad = ca.preparar(_escrever(tmp_path, contratos=[{**CONTRATO, "copia_extras": [" Eng.Obra@Lotufo.com ", "eng.obra@lotufo.com"]}]))
    assert cad["contratos"][0]["copia_extras"] == ["eng.obra@lotufo.com"]
    assert ca.preparar(_escrever(tmp_path))["contratos"][0]["copia_extras"] == []
    erros = _erros(_escrever(tmp_path, contratos=[{**CONTRATO, "copia_extras": "eng@lotufo.com"}]))
    assert any("copia_extras" in e and "lista" in e for e in erros)
    for vazio_errado in ("", False, {}):
        erros = _erros(_escrever(tmp_path, contratos=[{**CONTRATO, "copia_extras": vazio_errado}]))
        assert any("copia_extras" in e and "lista" in e for e in erros)
    erros = _erros(_escrever(tmp_path, contratos=[{**CONTRATO, "copia_extras": ["eng@lotufo"]}]))
    assert any("copia_extras" in e and "inválido" in e for e in erros)


def test_orgao_com_cnpj_valido_normaliza_e_invalido_e_erro(tmp_path):
    cad = ca.preparar(_escrever(tmp_path, orgaos=[{**ORGAO, "cnpj": "31.300.101/0001-01"}]))
    assert cad["orgaos"][0]["cnpj"] == "31300101000101"
    assert "cnpj" not in cad["orgaos"][0]["regras"]
    assert ca.preparar(_escrever(tmp_path))["orgaos"][0]["cnpj"] is None       # opcional
    erros = _erros(_escrever(tmp_path, orgaos=[{**ORGAO, "cnpj": "11.111.111/1111-11"}]))
    assert any("cnpj" in e.lower() for e in erros)


def test_lista_de_documentos_do_orgao_so_aceita_chaves_conhecidas(tmp_path):
    erros = _erros(_escrever(tmp_path, orgaos=[{**ORGAO, "documentos_medicao": ["federal", "cnd-inventada"]}]))
    assert any("documentos_medicao" in e for e in erros)


def test_consorciadas_normalizadas_e_conferidas(tmp_path):
    rivoli = {"chave": "rivoli", "nome": "Rivoli", "cnpj": "31.200.606/0001-02", "papel": "consorciada"}
    leblon = {"chave": "complexo-leblon", "nome": "Consórcio Complexo Leblon", "nome_curto": "Complexo Leblon",
              "cnpj": "31.200.404/0001-52", "papel": "consorcio", "consorciadas": ["lotufo", "rivoli"],
              "regularidade_propria": True}
    cad = ca.preparar(_escrever(tmp_path, entidades=[ENTIDADE, rivoli, leblon]))
    e = {x["chave"]: x for x in cad["entidades"]}
    assert e["complexo-leblon"]["consorciadas"] == ["lotufo", "rivoli"]
    assert e["complexo-leblon"]["nome_curto"] == "Complexo Leblon"
    assert e["complexo-leblon"]["regularidade_propria"] is True
    assert e["rivoli"]["nome_curto"] == "Rivoli"          # sem nome_curto, vale o nome
    erros = _erros(_escrever(tmp_path, entidades=[ENTIDADE, {**leblon, "consorciadas": ["lotufo", "nao-existe"]}]))
    assert any("consorciadas" in x for x in erros)
    erros = _erros(_escrever(tmp_path, entidades=[{**ENTIDADE, "consorciadas": ["lotufo"]}]))
    assert any("consorciadas" in x for x in erros)       # so' consorcio tem composicao


def test_excecao_de_documentos_no_contrato(tmp_path):
    cad = ca.preparar(_escrever(tmp_path, contratos=[{**CONTRATO, "documentos_reajuste": ["estadual"]}]))
    assert cad["contratos"][0]["documentos"] == {"reajuste": ["estadual"]}
    assert ca.preparar(_escrever(tmp_path))["contratos"][0]["documentos"] is None


# --- bloco 5: cartas, pecas do orgao, CNO e dados do fiscal ---------------------------------------

def test_cartas_ausente_passa_e_familia_ou_timbre_invalidos_sao_erro(tmp_path):
    raiz = _escrever(tmp_path)
    assert "cartas" not in (ca.preparar(raiz)["geral"] or {})
    (raiz / "cartas.yaml").write_text(yaml.safe_dump({
        "signatario": ["Fernando Exemplo Neto"], "familias": {"outra": {"carta_corpo": "x"}},
        "emitentes": {"lotufo": {"razao_social": "LOTUFO", "logo": "modelos/carta/nao-existe.png"}}},
        allow_unicode=True), "utf-8")
    erros = _erros(raiz)
    assert any("familias.outra" in e for e in erros) and any("logo" in e for e in erros)


def test_cartas_validas_guardam_o_caminho_do_timbre(tmp_path):
    raiz = _escrever(tmp_path)
    (raiz / "modelos" / "carta").mkdir(parents=True)
    (raiz / "modelos" / "carta" / "timbre.png").write_bytes(b"png")
    (raiz / "cartas.yaml").write_text(yaml.safe_dump({
        "signatario": ["Fernando Exemplo Neto"], "familias": {"mtpar": {"carta_corpo": "{lista}"}},
        "emitentes": {"lotufo": {"razao_social": "LOTUFO", "logo": "modelos/carta/timbre.png"}}},
        allow_unicode=True), "utf-8")
    cartas = ca.preparar(raiz)["geral"]["cartas"]
    assert cartas["emitentes"]["lotufo"]["logo_caminho"].endswith("timbre.png")
    assert cartas["familias"]["mtpar"]["carta_corpo"] == "{lista}"


def test_pecas_ordem_e_destinatario_da_carta_no_orgao(tmp_path):
    ok = {**ORGAO, "carta_destinatario": ["A SINFRA"], "ordem_certidoes": ["municipal", "fgts"],
          "pecas": [{"tipo": "boletim", "rotulo": "Boletim", "exigida": True}]}
    assert ca.preparar(_escrever(tmp_path / "a", orgaos=[ok]))["orgaos"][0]["regras"]["pecas"][0]["tipo"] == "boletim"
    ruim = {**ORGAO, "carta_destinatario": "A SINFRA", "ordem_certidoes": ["regularidade"],
            "pecas": [{"tipo": "video", "rotulo": "X"}, {"tipo": "croqui", "rotulo": "C", "naturezas": ["obra"]}]}
    erros = _erros(_escrever(tmp_path / "b", orgaos=[ruim]))
    for campo in ("carta_destinatario", "ordem_certidoes", "pecas[0].tipo", "pecas[1].naturezas"):
        assert any(campo in e for e in erros), campo


def test_pecas_do_pleito_de_reajuste_no_orgao(tmp_path):
    """Issue #50: o orgao lista as pecas que o pleito de reajuste leva alem da memoria de calculo e do cronograma."""
    ok = {**ORGAO, "pecas_pleito_reajuste": ["falencia", "contrato_social", "documento_representante", "balanco"]}
    regras = ca.preparar(_escrever(tmp_path / "a", orgaos=[ok]))["orgaos"][0]["regras"]
    assert regras["pecas_pleito_reajuste"] == ["falencia", "contrato_social", "documento_representante", "balanco"]
    for ruim in (["falencia", "falencia"], ["certidao-inventada"], "balanco"):
        erros = _erros(_escrever(tmp_path / "b", orgaos=[{**ORGAO, "pecas_pleito_reajuste": ruim}]))
        assert any("pecas_pleito_reajuste" in e for e in erros), ruim
    from app import pleitos
    assert ca.PECAS_PLEITO == pleitos.PECAS_ORGAO        # copia de proposito: o cadastro nao importa o envio


def test_cno_inexistente_e_tratamento_invalido_sao_erro(tmp_path):
    c = {**CONTRATO, "cno_pdf": "anexos/mt-402/cno.pdf",
         "fiscais": [{"nome": "Ana", "email": "ana@orgao-a.exemplo.com.br", "desde": "2026-01-01", "tratamento": "Dona"}]}
    erros = _erros(_escrever(tmp_path, contratos=[c]))
    assert any("cno_pdf" in e for e in erros) and any("tratamento" in e for e in erros)


def test_fiscal_sem_nome_e_aviso_e_o_cadastro_segue(tmp_path):
    c = {**CONTRATO, "fiscais": [
        {"email": "Sem.Nome@orgao-a.exemplo.com.br", "desde": "2026-01-01"},
        {"nome": "  ", "email": "branco@orgao-a.exemplo.com.br", "desde": "2026-02-01"},
        {"nome": "Ana", "email": "ana@orgao-a.exemplo.com.br", "desde": "2026-03-01"}]}
    cad = ca.preparar(_escrever(tmp_path, contratos=[c]))
    assert cad["avisos"] == [
        "Contrato MT-402: fiscal sem.nome@orgao-a.exemplo.com.br sem nome",
        "Contrato MT-402: fiscal branco@orgao-a.exemplo.com.br sem nome"]
    assert len(cad["contratos"][0]["fiscais"]) == 3


def test_fiscal_com_nome_nao_gera_aviso(tmp_path):
    c = {**CONTRATO, "fiscais": [{"nome": "Ana", "email": "ana@orgao-a.exemplo.com.br", "desde": "2026-01-01"}]}
    assert ca.preparar(_escrever(tmp_path, contratos=[c]))["avisos"] == []


def test_cno_fora_da_pasta_do_cadastro_e_erro(tmp_path):
    (tmp_path / "segredo.pdf").write_bytes(b"%PDF-1.7 segredo")          # existe, mas fora da raiz
    erros = _erros(_escrever(tmp_path / "cad", contratos=[{**CONTRATO, "cno_pdf": "../segredo.pdf"}]))
    assert any("cno_pdf" in e and "pasta do cadastro" in e for e in erros)


def test_bloco7_marco_referente_pleito_e_folga_invalidos(tmp_path):
    c = {**CONTRATO, "folga_vigencia_dias": -1,
         "instrumentos": [{"chave": "marco-1", "tipo": "marco_encerramento", "data": "2026-09-01", "marco": "outro"},
                          {"chave": "endosso-1", "tipo": "endosso_garantia", "data": "2026-09-01", "referente": "nada"}],
         "pleitos_anteriores": [{"tipo": "reajuste", "oficio": "CT-122-LT-2026", "data": "2026-04-23",
                                 "data_base": "2023-04"}]}
    erros = _erros(_escrever(tmp_path, contratos=[c]))
    for campo in ("folga_vigencia_dias", ".marco", ".referente", "pleitos_anteriores[0].ciclo"):
        assert any(campo in e for e in erros), campo


def test_bloco8_tipo_contratante_e_modelo_do_qdop(tmp_path):
    erros = _erros(_escrever(tmp_path, orgaos=[{**ORGAO, "tipo_contratante": "MISTO"}]))
    assert any("tipo_contratante" in e for e in erros)
    raiz = _escrever(tmp_path / "ok", orgaos=[{**ORGAO, "tipo_contratante": "PÚBLICO", "nome_qdop": "SINFRA"}])
    (raiz / "geral.yaml").write_text(yaml.safe_dump({
        "faturamento": {"para": ["f@l.com"], "assunto": "{medicao} {obra}", "corpo": "x"},
        "diretoria": {"total_a_receber_liberado": False}, "qdop": {"modelo": "nao-existe.xlsx"}}), "utf-8")
    assert any("qdop.modelo" in e for e in _erros(raiz))


# --- issue #110: FRC e cobranca de certidao vem do cadastro, nao do codigo --------------------------

CONSORCIO = {"chave": "consorcio-gama", "nome": "Consórcio Gama", "cnpj": "31.200.303/0001-81", "papel": "consorcio",
             "consorciadas": ["lotufo"]}
PARTE = {"razao_social": "CONSÓRCIO GAMA", "endereco": "RUA DE EXEMPLO, 100", "municipio": "CUIABÁ - MT / BRASIL",
         "cep": "00000-000", "cnpj": "31.200.303/0001-81", "inscricao_municipal": "123456",
         "telefone": "(00) 0000-0000", "email": "contato@exemplo.com.br"}
FRC = {"formulario": "A", "ultimo_anterior": 21, "logo": "modelos/frc/gama.jpg", "rotulo_empresa": "RAZÃO SOCIAL",
       "prestador": PARTE, "tomador": {**PARTE, "razao_social": "SECRETARIA DE EXEMPLO", "email": "Fiscal@Exemplo.gov.br"},
       "descricao": {"execucao": "{n}ª MEDIÇÃO - {inicio} A {fim}"},
       "consorciadas": [{"chave": "lotufo", "cnpj": "31.200.101/0001-30", "razao_social": "CONSTRUTORA ALFA LTDA"}]}


def _com_frc(raiz, frc):
    raiz = _escrever(raiz, entidades=[ENTIDADE, CONSORCIO])
    (raiz / "modelos" / "frc").mkdir(parents=True, exist_ok=True)
    (raiz / "modelos" / "frc" / "gama.jpg").write_bytes(b"jpg")
    (raiz / "frc.yaml").write_text(yaml.safe_dump(frc, allow_unicode=True), "utf-8")
    return raiz


def test_frc_ausente_passa_e_valida_normaliza_com_o_caminho_do_logo(tmp_path):
    assert ca.preparar(_escrever(tmp_path / "sem"))["frc"] == []
    [f] = ca.preparar(_com_frc(tmp_path / "com", {"consorcio-gama": FRC}))["frc"]
    assert (f["consorcio"], f["formulario"], f["ultimo_anterior"]) == ("consorcio-gama", "A", 21)
    assert f["logo_caminho"].endswith("gama.jpg") and "logo" not in f["dados"]
    assert f["dados"]["tomador"]["email"] == "fiscal@exemplo.gov.br"
    assert f["dados"]["prestador"]["cnpj"] == "31.200.303/0001-81"       # impresso como no cadastro
    assert f["dados"]["descricao"] == FRC["descricao"] and f["dados"]["consorciadas"] == FRC["consorciadas"]
    sem_logo = ca.preparar(_com_frc(tmp_path / "sem-logo", {"consorcio-gama": {**FRC, "logo": None}}))["frc"][0]
    assert sem_logo["logo_caminho"] is None


def test_frc_de_quem_nao_e_consorcio_ou_com_campo_invalido_e_erro(tmp_path):
    ruim = {**FRC, "formulario": "B", "ultimo_anterior": -1, "logo": "../fora.jpg",
            "tomador": {**PARTE, "email": "sem-arroba"}, "prestador": {**PARTE, "cnpj": "31.200.303/0001-82"},
            "descricao": {"medicao": "x"}, "consorciadas": [{"chave": "nao-existe", "cnpj": "", "razao_social": ""}]}
    erros = "\n".join(_erros(_com_frc(tmp_path, {"consorcio-gama": ruim, "lotufo": FRC})))
    for trecho in ("frc.yaml: lotufo", "formulario", "ultimo_anterior", "logo", "tomador.email", "prestador.cnpj",
                   "descricao", "consorciadas"):
        assert trecho in erros, trecho
    placeholder = {**FRC, "descricao": {"execucao": "{n}ª MEDIÇÃO CONFORME IC {ic}"}}       # so' {n}, {inicio}, {fim}
    assert any("descricao" in e for e in _erros(_com_frc(tmp_path / "c", {"consorcio-gama": placeholder})))
    sem_campo = {**FRC, "tomador": {k: v for k, v in PARTE.items() if k != "telefone"}}
    assert any("tomador.telefone" in e for e in _erros(_com_frc(tmp_path / "b", {"consorcio-gama": sem_campo})))


def test_cobranca_de_certidoes_no_geral(tmp_path):
    raiz = _escrever(tmp_path)
    base = {"faturamento": {"para": ["f@exemplo.com.br"], "assunto": "{medicao} {obra}", "corpo": "x"}}
    (raiz / "geral.yaml").write_text(yaml.safe_dump({**base, "cobranca_certidoes": {
        "para": [" Leo@Exemplo.com.br "], "enviada_por": ["leo@exemplo.com.br", "leo.login@exemplo.com.br"]}}), "utf-8")
    assert ca.preparar(raiz)["geral"]["cobranca_certidoes"] == {
        "para": ["leo@exemplo.com.br"], "enviada_por": ["leo@exemplo.com.br", "leo.login@exemplo.com.br"]}
    (raiz / "geral.yaml").write_text(yaml.safe_dump({**base, "cobranca_certidoes": {
        "para": [], "enviada_por": ["nao-e-email"]}}), "utf-8")
    erros = "\n".join(_erros(raiz))
    assert "cobranca_certidoes.para" in erros and "cobranca_certidoes.enviada_por" in erros


# --- issue #65: garantia com vigencia, endosso que traz a nova vigencia ----------

def test_garantia_do_contrato_normalizada(tmp_path):
    raiz = tmp_path / "cad"
    (raiz / "anexos").mkdir(parents=True)
    (raiz / "anexos" / "gar.pdf").write_bytes(b"%PDF-1.4 gar")
    c = {**CONTRATO, "garantia": {"apolice": "AP-9", "vigencia_fim": "2027-03-31", "arquivo": "anexos/gar.pdf"},
         "instrumentos": [*CONTRATO["instrumentos"], {"chave": "end-1", "tipo": "endosso_garantia",
                                                      "data": "2026-09-01", "vigencia_fim": "2027-09-30", "apolice": "AP-9"}]}
    got = ca.preparar(_escrever(raiz, contratos=[c]))["contratos"][0]
    assert "art" not in got and "art_caminho" not in got
    assert (got["garantia_apolice"], got["garantia_vigencia_fim"]) == ("AP-9", "2027-03-31")
    assert got["garantia_caminho"].endswith("gar.pdf")
    assert got["instrumentos"][1]["dados"]["vigencia_fim"] == "2027-09-30"


def test_art_null_no_contrato_e_aceito_e_ignorado(tmp_path):
    got = ca.preparar(_escrever(tmp_path, contratos=[{**CONTRATO, "art": None}]))["contratos"][0]
    assert "art" not in got and got["garantia_vigencia_fim"] is None


@pytest.mark.parametrize("valor", ["98765", {"numero": "1", "arquivo": "x.pdf"}])
def test_art_preenchida_no_contrato_e_recusada_em_portugues(tmp_path, valor):
    with pytest.raises(Exception) as e:
        ca.preparar(_escrever(tmp_path, contratos=[{**CONTRATO, "art": valor}]))
    assert "a ART saiu do contrato" in str(e.value)


def test_garantia_sem_data_arquivo_inexistente_e_endosso_com_data_ruim_sao_erro(tmp_path):
    c = {**CONTRATO, "garantia": {"apolice": "AP-9", "arquivo": "anexos/nao-existe.pdf"},
         "instrumentos": [{"chave": "end-1", "tipo": "endosso_garantia", "data": "2026-09-01",
                           "vigencia_fim": "amanha"}]}
    erros = _erros(_escrever(tmp_path, contratos=[c]))
    assert any("garantia.vigencia_fim" in e for e in erros)
    assert any("garantia.arquivo" in e for e in erros)
    assert any("end-1" in e and "vigencia_fim" in e for e in erros)


def test_endosso_com_vigencia_sem_apolice_e_recusado(tmp_path):
    c = {**CONTRATO, "instrumentos": [{"chave": "end-1", "tipo": "endosso_garantia", "data": "2026-09-01",
                                       "vigencia_fim": "2027-09-30"}]}
    erros = _erros(_escrever(tmp_path, contratos=[c]))
    assert any("end-1" in e and "apolice" in e and "apólice" in e for e in erros)


def _endosso(apolice):
    return {"chave": "end-1", "tipo": "endosso_garantia", "data": "2026-09-01", "vigencia_fim": "2027-09-30",
            "apolice": apolice}


def test_endosso_com_vigencia_em_contrato_sem_apolice_e_erro(tmp_path):
    erros = _erros(_escrever(tmp_path, contratos=[{**CONTRATO, "instrumentos": [_endosso("AP-1")]}]))
    assert any("end-1" in e and "garantia.apolice" in e for e in erros)


def test_endosso_de_outra_apolice_gera_aviso_nao_erro(tmp_path):
    c = {**CONTRATO, "garantia": {"apolice": "AP-1", "vigencia_fim": "2027-03-31"},
         "instrumentos": [_endosso("AP 1")]}
    cad = ca.preparar(_escrever(tmp_path, contratos=[c]))
    assert any("end-1" in a and "'AP 1'" in a and "diferente da apólice do contrato" in a for a in cad["avisos"])
    c["instrumentos"] = [_endosso("AP-1")]
    assert ca.preparar(_escrever(tmp_path, contratos=[c]))["avisos"] == []


def test_natureza_do_instrumento_de_valor_padrao_execucao_e_aceita_reajuste(tmp_path):
    """#262: aditivo de valor ganha `natureza` (execucao|reajuste); sem o campo, None (nao classificado = execucao)."""
    reaj = {"chave": "ta-08", "tipo": "aditivo_valor", "data": "2026-09-01", "delta_valor": "1.000,01",
            "natureza": "reajuste"}
    c = {**CONTRATO, "instrumentos": [*CONTRATO["instrumentos"], reaj]}
    insts = ca.preparar(_escrever(tmp_path, contratos=[c]))["contratos"][0]["instrumentos"]
    assert [i["natureza"] for i in insts] == [None, "reajuste"]
    assert "natureza" not in insts[1]["dados"]


def test_natureza_so_aceita_execucao_ou_reajuste(tmp_path):
    ruim = {"chave": "ta-08", "tipo": "aditivo_valor", "data": "2026-09-01", "delta_valor": "1.000,00",
            "natureza": "Reajuste"}
    erros = _erros(_escrever(tmp_path, contratos=[{**CONTRATO, "instrumentos": [ruim]}]))
    assert any("natureza" in e and "execucao" in e and "reajuste" in e for e in erros)


def test_natureza_em_instrumento_que_nao_e_de_valor_e_erro(tmp_path):
    prazo = {"chave": "ap-01", "tipo": "apostilamento_prazo", "data": "2026-09-01",
             "nova_execucao_fim": "2027-01-01", "natureza": "reajuste"}
    erros = _erros(_escrever(tmp_path, contratos=[{**CONTRATO, "instrumentos": [prazo]}]))
    assert any("natureza" in e for e in erros)
