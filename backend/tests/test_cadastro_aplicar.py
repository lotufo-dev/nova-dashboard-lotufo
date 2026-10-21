import json
import sqlite3

import pytest
from app import auth, cadastro_aplicar, db, medicoes

CNPJ_LOTUFO = "31200101000130"
CNPJ_OK = "11444777000161"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "admin")
    yield c
    c.close()


def _cad(**troca):
    base = {"orgaos": [{"chave": "sinfra-suef1", "nome": "SINFRA - SUEF I", "familia": "sinfra",
                        "regras": {"folga_vigencia_dias": 90}}],
            "entidades": [{"chave": "lotufo", "nome": "Lotufo Engenharia e Construções Ltda",
                           "cnpj": CNPJ_LOTUFO, "papel": "lotufo", "coligada_rm": 1, "sigla_oficio": "LT"}],
            "contratos": [], "avisos": []}
    return {**base, **troca}


def test_orgao_criado_depois_igual_depois_alterado(conn):
    r1 = cadastro_aplicar.aplicar(conn, 1, _cad())
    assert r1["orgaos"]["criados"] == ["sinfra-suef1"]
    r2 = cadastro_aplicar.aplicar(conn, 1, _cad())
    assert r2["orgaos"] == {"criados": [], "alterados": [], "iguais": 1}
    novo = _cad()
    novo["orgaos"][0]["regras"] = {"folga_vigencia_dias": 60}
    r3 = cadastro_aplicar.aplicar(conn, 1, novo)
    assert r3["orgaos"]["alterados"] == ["sinfra-suef1"]
    assert json.loads(conn.execute("SELECT regras FROM orgaos").fetchone()[0]) == {"folga_vigencia_dias": 60}


def test_entidade_casa_por_cnpj_com_a_lotufo_semeada(conn):
    r = cadastro_aplicar.aplicar(conn, 1, _cad())
    assert r["entidades"]["alterados"] == ["lotufo"]      # ganhou chave e sigla, nao duplicou
    linhas = conn.execute("SELECT id, chave, sigla_oficio FROM entidades").fetchall()
    assert [(x["id"], x["chave"], x["sigla_oficio"]) for x in linhas] == [(1, "lotufo", "LT")]


def test_empresa_propria_com_outro_cnpj_e_a_mesma_semeada_e_nao_uma_segunda(conn):
    """Cadastro de exemplo num banco vazio (#103): a `lotufo` do YAML tem CNPJ diferente da semeada pela
    migracao 006. Antes, nascia uma segunda `lotufo` e a coligada 1 colidia (IntegrityError)."""
    ent = {"chave": "lotufo", "nome": "Construtora Exemplo Ltda", "cnpj": "12345678000195", "papel": "lotufo",
           "coligada_rm": 1, "sigla_oficio": "EX"}
    r = cadastro_aplicar.aplicar(conn, 1, _cad(entidades=[ent]))
    assert r["entidades"]["alterados"] == ["lotufo"] and r["entidades"]["criados"] == []
    linhas = conn.execute("SELECT id, chave, cnpj, coligada_rm FROM entidades").fetchall()
    assert [tuple(x) for x in linhas] == [(1, "lotufo", "12345678000195", 1)]
    depois = json.loads(conn.execute("SELECT depois FROM audit_log WHERE acao='cadastro.entidade'").fetchone()[0])
    assert depois["cnpj"] == "12345678000195"
    assert cadastro_aplicar.aplicar(conn, 1, _cad(entidades=[ent]))["entidades"]["iguais"] == 1     # e de novo: igual
    # a semeada ja' foi reivindicada: CNPJ digitado errado depois disso e' recusado, nao troca o da empresa propria
    with pytest.raises(sqlite3.IntegrityError):
        cadastro_aplicar.aplicar(conn, 1, _cad(entidades=[{**ent, "cnpj": "98765432000198"}]))
    assert conn.execute("SELECT cnpj FROM entidades WHERE papel='lotufo'").fetchone()[0] == "12345678000195"


def test_entidade_nova_e_criada(conn):
    cad = _cad()
    cad["entidades"].append({"chave": "rivoli", "nome": "Rivoli", "cnpj": CNPJ_OK,
                             "papel": "consorciada", "coligada_rm": None, "sigla_oficio": None})
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["entidades"]["criados"] == ["rivoli"]


def test_ensaio_relata_e_nao_grava(conn):
    r = cadastro_aplicar.aplicar(conn, 1, _cad(), ensaio=True)
    assert r["ensaio"] is True and r["orgaos"]["criados"] == ["sinfra-suef1"]
    assert conn.execute("SELECT COUNT(*) FROM orgaos").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM cadastro_aplicacoes").fetchone()[0] == 0


def test_aplicacao_real_fica_registrada_com_o_commit(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(), commit_hash="abc123")
    linha = conn.execute("SELECT commit_hash, usuario_id FROM cadastro_aplicacoes").fetchone()
    assert (linha["commit_hash"], linha["usuario_id"]) == ("abc123", 1)
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cadastro.aplicar'").fetchone()[0] == 1


def _contrato(**troca):
    base = {"nome_curto": "MT-402", "numero_instrumento": "019/2024/00/00-SINFRA",
            "orgao": "sinfra-suef1", "entidade": "lotufo", "objeto": "Remanescente da MT-402",
            "municipio": "Cuiabá", "lei": "14.133", "cno": None, "numero_processo": None,
            "centro_custo_rm": "4.003.016", "valor_original_centavos": 1512720000,
            "percentual_direito_bp": 10000, "execucao_inicio": "2024-03-11", "execucao_fim": "2026-08-28",
            "vigencia_inicio": None, "vigencia_fim": "2026-11-22", "status": "ativo", "status_desde": None,
            "sem_reajuste": False, "datas_base": [{"mes": "2023-04", "indice": "setorial"}],
            "fiscais": [{"nome": "Zeno", "email": "z@orgao-a.exemplo.com.br", "desde": "2026-01-01"}],
            "destinatarios_extras": ["medicao@supervisora.exemplo.com.br"],
            "copia_extras": ["engenheiro@lotufo.com"], "instrumentos": []}
    return {**base, **troca}


def test_contrato_existente_e_atualizado_pelo_numero_do_instrumento(conn):
    conn.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos) "
                 "VALUES ('SINFRA','019/2024/00/00-SINFRA','MT-402',1512720000)")
    conn.commit()
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato()]))
    assert r["contratos"]["alterados"] == ["MT-402"] and r["contratos"]["criados"] == []
    c = conn.execute("SELECT * FROM contratos").fetchall()
    assert len(c) == 1 and c[0]["nome_curto"] == "MT-402" and c[0]["lei"] == "14.133"
    assert c[0]["orgao_id"] == 1 and c[0]["entidade_id"] == 1
    assert json.loads(c[0]["destinatarios_extras"]) == ["medicao@supervisora.exemplo.com.br"]
    assert json.loads(c[0]["copia_extras"]) == ["engenheiro@lotufo.com"]


def test_reaplicar_contrato_e_igual(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato()]))
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato()]))
    assert r["contratos"] == {"criados": [], "alterados": [], "iguais": 1}


def test_contrato_sem_copia_extras_continua_igual_depois_da_migracao_037(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(copia_extras=[])]))
    assert conn.execute("SELECT copia_extras FROM contratos").fetchone()[0] is None
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(copia_extras=[])]))
    assert r["contratos"] == {"criados": [], "alterados": [], "iguais": 1}


def test_em_encerramento_mantem_ativo_e_grava_a_data(conn):
    cad = _cad(contratos=[_contrato(status="em_encerramento", status_desde="2026-07-17")])
    cadastro_aplicar.aplicar(conn, 1, cad)
    c = conn.execute("SELECT estado, encerramento_iniciado_em FROM contratos").fetchone()
    assert (c["estado"], c["encerramento_iniciado_em"]) == ("ativo", "2026-07-17")


def test_suspender_gera_evento_do_contrato(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato()]))
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(status="suspenso", status_desde="2025-10-01")]))
    ev = conn.execute("SELECT tipo, data FROM contrato_eventos").fetchall()
    assert [(e["tipo"], e["data"]) for e in ev] == [("suspensao", "2025-10-01")]
    assert conn.execute("SELECT estado FROM contratos").fetchone()[0] == "suspenso"


def test_valor_original_nao_muda_com_medicao_congelada(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato()]))
    conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, congelada) "
                 "VALUES (1,1,'execucao','2026-08','protocolada',1)")
    conn.commit()
    with pytest.raises(ValueError, match="valor original"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(valor_original_centavos=1)]))
    assert conn.execute("SELECT valor_original_centavos FROM contratos").fetchone()[0] == 1512720000


def test_datas_base_sincronizam_e_fiscal_novo_nao_apaga_o_antigo(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato()]))
    novo = _contrato(datas_base=[{"mes": "2022-01", "indice": "SINAPI"}, {"mes": "2022-03", "indice": "SICRO"}],
                     fiscais=[{"nome": "Zeno", "email": "z@orgao-a.exemplo.com.br", "desde": "2026-01-01"},
                              {"nome": "Ana", "email": "ana@orgao-a.exemplo.com.br", "desde": "2026-09-01"}])
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[novo]))
    assert [r[0] for r in conn.execute("SELECT mes FROM contrato_datas_base ORDER BY mes")] == ["2022-01", "2022-03"]
    assert conn.execute("SELECT COUNT(*) FROM contrato_fiscais").fetchone()[0] == 2


from app import contratos as contratos_mod

AD_VALOR = {"chave": "ta-01", "tipo": "aditivo_valor", "data": "2026-06-30", "numero": "019/2024/01/01",
            "objeto": "1ª revisão em fase de obra", "corrige": None, "pdf": None,
            "delta_valor_centavos": 323606718, "nova_execucao_fim": None, "nova_vigencia_fim": None, "dados": {}}
AP_PRAZO = {"chave": "ap-10", "tipo": "apostilamento_prazo", "data": "2026-08-26", "numero": "019/2024/02/10",
            "objeto": None, "corrige": None, "pdf": None, "delta_valor_centavos": 0,
            "nova_execucao_fim": "2027-02-24", "nova_vigencia_fim": "2027-05-25", "dados": {}}
AP_REAJ = {"chave": "ap-09", "tipo": "apostilamento_reajuste", "data": "2026-03-06", "numero": "019/2024/02/09",
           "objeto": None, "corrige": None, "pdf": None, "delta_valor_centavos": 0,
           "nova_execucao_fim": None, "nova_vigencia_fim": None, "dados": {"ciclo": "2025-04", "percentual": None}}


def test_instrumentos_de_valor_e_prazo_mudam_o_vigente(conn):
    cad = _cad(contratos=[_contrato(instrumentos=[AP_PRAZO, AD_VALOR])])   # fora de ordem de proposito
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert sorted(r["instrumentos"]["criados"]) == ["MT-402/ap-10", "MT-402/ta-01"]
    v = contratos_mod.vigente(conn, 1)
    assert v["valor_vigente_centavos"] == 1512720000 + 323606718
    assert (v["execucao_fim_vigente"], v["vigencia_fim_vigente"]) == ("2027-02-24", "2027-05-25")
    ad = conn.execute("SELECT * FROM aditivos WHERE chave_cadastro='ta-01'").fetchone()
    assert (ad["status"], ad["forma"], ad["valor_anterior_centavos"]) == ("assinado", "termo_aditivo", 1512720000)
    assert conn.execute("SELECT forma FROM aditivos WHERE chave_cadastro='ap-10'").fetchone()[0] == "apostilamento"


def test_reaplicar_instrumentos_e_igual(conn):
    cad = _cad(contratos=[_contrato(instrumentos=[AD_VALOR, AP_REAJ])])
    cadastro_aplicar.aplicar(conn, 1, cad)
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["instrumentos"] == {"criados": [], "alterados": [], "iguais": 2}
    assert conn.execute("SELECT COUNT(*) FROM aditivos").fetchone()[0] == 1


def test_alterar_instrumento_aplicado_e_recusado_e_nada_muda(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AD_VALOR])]))
    adulterado = {**AD_VALOR, "delta_valor_centavos": 1}
    with pytest.raises(ValueError, match="já aplicado"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[adulterado])]))
    assert conn.execute("SELECT delta_valor_centavos FROM aditivos").fetchone()[0] == 323606718


def test_instrumento_aplicado_que_some_do_cadastro_e_recusado(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AD_VALOR])]))
    with pytest.raises(ValueError, match="sumiu"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[])]))


def test_trocar_a_categoria_de_instrumento_aplicado_e_recusado(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AD_VALOR])]))
    trocado = {**AP_REAJ, "chave": "ta-01"}
    with pytest.raises(ValueError, match="já aplicado"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[trocado])]))
    assert conn.execute("SELECT COUNT(*) FROM instrumentos").fetchone()[0] == 0


def test_apostilamento_de_reajuste_vai_para_instrumentos(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_REAJ])]))
    linha = conn.execute("SELECT tipo, numero, dados FROM instrumentos").fetchone()
    assert (linha["tipo"], linha["numero"]) == ("apostilamento_reajuste", "019/2024/02/09")
    assert json.loads(linha["dados"])["ciclo"] == "2025-04"
    assert conn.execute("SELECT COUNT(*) FROM aditivos").fetchone()[0] == 0


def test_texto_descritivo_do_aditivo_pode_ser_corrigido(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AD_VALOR])]))
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[{**AD_VALOR, "objeto": "1ª RPFO"}])]))
    assert r["instrumentos"]["alterados"] == ["MT-402/ta-01"]
    assert conn.execute("SELECT objeto FROM aditivos").fetchone()[0] == "1ª RPFO"


def test_ordinal_do_cadastro_e_gravado_e_pode_ser_corrigido(conn):
    """Issue #261: `ordinal` e' descricao do termo (como o numero): grava e aceita correcao."""
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[{**AP_PRAZO, "ordinal": 9}])]))
    assert conn.execute("SELECT ordinal FROM aditivos").fetchone()[0] == 9
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[{**AP_PRAZO, "ordinal": 10}])]))
    assert r["instrumentos"]["alterados"] == ["MT-402/ap-10"]
    assert conn.execute("SELECT ordinal FROM aditivos").fetchone()[0] == 10


# --- bloco 2: geral, regra do espelho e modelos ---------------------------------------------

import hashlib
from pathlib import Path


def _cad_com_espelho(tmp_path):
    modelo = tmp_path / "m.docx"; modelo.write_bytes(b"PK-fake-docx")
    regra = {"contrato": "MT-402", "situacao": "prova",
             "entradas": [{"chave": "medicao", "rotulo": "m", "natureza": "medicao"}],
             "parcelas": [],
             "saidas": [{"chave": "medicao", "natureza": "medicao", "rotulo": None, "valor": ["medicao"],
                         "emissor": "lotufo", "municipio": "Cuiabá", "modelo": "medicao.docx",
                         "retencoes": {"mao_de_obra": {"percentual": "40", "arredondamento": "trunc"},
                                       "material": {"modo": "diferenca"},
                                       "inss": {"percentual": "11", "base": "mao_de_obra", "arredondamento": "trunc"},
                                       "iss": {"percentual": "5", "base": "mao_de_obra", "arredondamento": "trunc",
                                               "deduz_liquido": True},
                                       "irrf": {"percentual": "1.2", "base": "total", "arredondamento": "round"}}}]}
    contrato = {"nome_curto": "MT-402", "numero_instrumento": "019/2024", "orgao": "sinfra-suef1",
                "entidade": "lotufo", "objeto": "MT-402", "municipio": None, "lei": None, "cno": None,
                "numero_processo": None, "centro_custo_rm": None, "status": "ativo",
                "status_desde": None, "sem_reajuste": False, "destinatarios_extras": [],
                "valor_original_centavos": 100, "percentual_direito_bp": 10000,
                # gate Sol S2 (10/10/2026): sem data de inicio o espelho nao e' gerado
                "execucao_inicio": "2024-03-11", "execucao_fim": None, "vigencia_inicio": None, "vigencia_fim": None,
                "datas_base": [], "fiscais": [], "instrumentos": []}
    return _cad(contratos=[contrato],
                geral={"faturamento": {"para": ["f@x.com"], "copia": [],
                                       "assunto": "Emissão NF - {medicao} - {obra}", "corpo": "Bom dia."}},
                espelho=[{"contrato": "MT-402", "slug": "mt-402", "situacao": "prova", "regra": regra,
                          "sha256": "abc",
                          "modelos": {"medicao": {"caminho": modelo,
                                                  "sha256": hashlib.sha256(b"PK-fake-docx").hexdigest()}}}])


def test_espelho_grava_regra_copia_modelo_e_e_idempotente(conn, tmp_path):
    cad = _cad_com_espelho(tmp_path)
    r1 = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r1["espelho"]["criados"] == ["MT-402"] and r1["geral"]["criados"] == ["faturamento"]
    linha = conn.execute("SELECT situacao, modelos FROM espelho_regras").fetchone()
    m = json.loads(linha["modelos"])["medicao"]
    assert linha["situacao"] == "prova" and m["arquivo"].startswith("modelos/") and m["arquivo"].endswith(".docx")
    assert (cadastro_aplicar.pasta_modelos() / Path(m["arquivo"]).name).read_bytes() == b"PK-fake-docx"
    r2 = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r2["espelho"]["iguais"] == 1 and r2["geral"]["iguais"] == 1


def test_trocar_situacao_para_ativa_e_alteracao_auditada(conn, tmp_path):
    cad = _cad_com_espelho(tmp_path); cadastro_aplicar.aplicar(conn, 1, cad)
    cad["espelho"][0]["situacao"] = "ativa"; cad["espelho"][0]["regra"]["situacao"] = "ativa"
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["espelho"]["alterados"] == ["MT-402"]
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cadastro.espelho'").fetchone()[0] == 2


def test_ensaio_do_espelho_nao_copia_modelo(conn, tmp_path):
    cad = _cad_com_espelho(tmp_path)
    cadastro_aplicar.aplicar(conn, 1, cad, ensaio=True)
    assert conn.execute("SELECT COUNT(*) FROM espelho_regras").fetchone()[0] == 0
    assert not list(cadastro_aplicar.pasta_modelos().glob("*.docx"))


def test_emails_faturamento_da_entidade_sao_gravados(conn):
    cad = _cad(); cad["entidades"][0]["emails_faturamento"] = ["a@x.com"]
    cadastro_aplicar.aplicar(conn, 1, cad)
    assert json.loads(conn.execute("SELECT emails_faturamento FROM entidades WHERE cnpj=?",
                                   (CNPJ_LOTUFO,)).fetchone()[0]) == ["a@x.com"]


def test_aplicar_grava_e_atualiza_o_cnpj_do_orgao(conn):
    cad = _cad()
    cad["orgaos"][0]["cnpj"] = "31300101000101"
    cadastro_aplicar.aplicar(conn, 1, cad)
    assert conn.execute("SELECT cnpj FROM orgaos WHERE chave='sinfra-suef1'").fetchone()[0] == "31300101000101"
    assert cadastro_aplicar.aplicar(conn, 1, cad)["orgaos"]["iguais"] == 1
    cad["orgaos"][0]["cnpj"] = None
    assert cadastro_aplicar.aplicar(conn, 1, cad)["orgaos"]["alterados"] == ["sinfra-suef1"]
    assert conn.execute("SELECT cnpj FROM orgaos WHERE chave='sinfra-suef1'").fetchone()[0] is None


def test_consorciadas_nome_curto_e_folha_propria_aplicados_e_idempotentes(conn):
    rivoli = {"chave": "rivoli", "nome": "Rivoli", "cnpj": "31200606000102", "papel": "consorciada",
              "coligada_rm": None, "sigla_oficio": None, "nome_curto": "Rivoli", "consorciadas": []}
    leblon = {"chave": "complexo-leblon", "nome": "Consórcio Complexo Leblon", "cnpj": "31200404000152",
              "papel": "consorcio", "coligada_rm": 17, "sigla_oficio": "CCL", "nome_curto": "Complexo Leblon",
              "consorciadas": ["lotufo", "rivoli"], "regularidade_propria": True}
    lotufo = {**_cad()["entidades"][0], "nome_curto": "Lotufo", "consorciadas": []}
    cad = _cad(entidades=[lotufo, rivoli, leblon])
    cadastro_aplicar.aplicar(conn, 1, cad)
    ids = {r["chave"]: r["id"] for r in conn.execute("SELECT id, chave FROM entidades")}
    pares = conn.execute("SELECT consorciada_id FROM entidade_consorciadas WHERE consorcio_id=? ORDER BY 1",
                         (ids["complexo-leblon"],)).fetchall()
    assert [p[0] for p in pares] == sorted([ids["lotufo"], ids["rivoli"]])
    assert conn.execute("SELECT nome_curto FROM entidades WHERE id=?", (ids["lotufo"],)).fetchone()[0] == "Lotufo"
    assert conn.execute("SELECT regularidade_propria FROM entidades WHERE id=?",
                        (ids["complexo-leblon"],)).fetchone()[0] == 1
    r2 = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r2["entidades"]["alterados"] == []
    leblon2 = {**leblon, "consorciadas": ["lotufo"]}
    r3 = cadastro_aplicar.aplicar(conn, 1, _cad(entidades=[lotufo, rivoli, leblon2]))
    assert "complexo-leblon (consorciadas)" in r3["entidades"]["alterados"]
    assert conn.execute("SELECT COUNT(*) FROM entidade_consorciadas").fetchone()[0] == 1


# --- bloco 5: objeto completo, CNO, dados do fiscal e timbre copiados para a pasta de dados -------

def test_objeto_cno_fiscal_e_timbre(conn, tmp_path):
    from app import arquivos
    cno = tmp_path / "cno.pdf"
    cno.write_bytes(b"%PDF-1.4 cno")
    timbre = tmp_path / "timbre.png"
    timbre.write_bytes(b"png")
    fiscal = {"nome": "Ana", "email": "ana@orgao-a.exemplo.com.br", "desde": "2026-01-01",
              "cargo": "Fiscal de Obras", "tratamento": "Senhora", "portaria": "Portaria 026/2026"}
    geral = {"cartas": {"signatario": ["F"], "familias": {}, "emitentes": {
        "lotufo": {"razao_social": "LOTUFO", "logo_caminho": str(timbre)}}}}
    cad = _cad(contratos=[_contrato(objeto_completo="EXECUÇÃO DA MT-402", cno_caminho=str(cno), fiscais=[fiscal])],
               geral=geral)
    assert cadastro_aplicar.aplicar(conn, 1, cad, ensaio=True)["contratos"]["criados"] == ["MT-402"]
    assert not (arquivos.pasta("anexos") / f"{arquivos.sha_de(b'%PDF-1.4 cno')}.pdf").exists()
    cadastro_aplicar.aplicar(conn, 1, cad)
    c = conn.execute("SELECT objeto_completo, cno_arquivo FROM contratos").fetchone()
    assert c["objeto_completo"] == "EXECUÇÃO DA MT-402" and arquivos.caminho_seguro(c["cno_arquivo"]).is_file()
    f = conn.execute("SELECT cargo, tratamento, portaria FROM contrato_fiscais").fetchone()
    assert tuple(f) == ("Fiscal de Obras", "Senhora", "Portaria 026/2026")
    cartas = json.loads(conn.execute("SELECT valor FROM cadastro_geral WHERE chave='cartas'").fetchone()[0])
    assert arquivos.caminho_seguro(cartas["emitentes"]["lotufo"]["logo"]).is_file()
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["contratos"]["iguais"] == 1 and r["geral"]["iguais"] == 1


def test_pleitos_anteriores_entram_enviados_e_nao_duplicam(conn):
    pleitos = [{"tipo": "reajuste", "oficio": "CT-122-LT-2026", "data": "2026-04-23", "data_base": "2023-04",
                "ciclo": 2026, "dias": None},
               {"tipo": "prazo", "oficio": "331", "data": "2025-11-10", "data_base": None, "ciclo": None, "dias": 120}]
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=pleitos)]))
    assert len(r["pleitos"]["criados"]) == 2
    linhas = conn.execute("SELECT tipo, origem, situacao, enviado_em, numero_oficio FROM pleitos ORDER BY id").fetchall()
    assert [tuple(x) for x in linhas] == [("reajuste", "cadastro", "enviado", "2026-04-23", "CT-122-LT-2026"),
                                          ("prazo", "cadastro", "enviado", "2025-11-10", "CT-331-LT-2025")]
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=pleitos)]))
    assert r["pleitos"] == {"criados": [], "alterados": [], "iguais": 2}


def test_medicao_final_preserva_o_encerramento_e_avisa(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato()]))
    cid = conn.execute("SELECT id FROM contratos").fetchone()[0]
    mid = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 30, "tipo": "execucao", "competencia": "2026-08"})
    medicoes.marcar_final(conn, 1, mid, "2026-09-10")
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato()]))
    assert conn.execute("SELECT encerramento_iniciado_em FROM contratos").fetchone()[0] == "2026-09-10"
    assert any("medição final marcada" in a for a in r["avisos"])


def test_modelo_do_qdop_vai_para_a_pasta_de_dados(conn, tmp_path):
    from app import arquivos
    modelo = tmp_path / "qdop.xlsx"
    modelo.write_bytes(b"PK\x03\x04modelo")
    geral = {"qdop": {"modelo_caminho": str(modelo)}, "diretoria": {"total_a_receber_liberado": False}}
    cadastro_aplicar.aplicar(conn, 1, _cad(geral=geral))
    rel = json.loads(conn.execute("SELECT valor FROM cadastro_geral WHERE chave='qdop'").fetchone()[0])["modelo"]
    assert arquivos.caminho_seguro(rel).read_bytes() == b"PK\x03\x04modelo"
    assert cadastro_aplicar.aplicar(conn, 1, _cad(geral=geral))["geral"]["iguais"] == 2


# --- issue #110: FRC do cadastro ------------------------------------------------------------------

def _cadastro_exemplo():
    from app import cadastro_arquivos
    from tests.conftest import CADASTRO_EXEMPLO
    return cadastro_arquivos.preparar(CADASTRO_EXEMPLO)


def test_frc_do_cadastro_exemplo_vai_para_o_banco_com_o_logo_na_pasta_de_dados(conn):
    from app import arquivos
    cad = _cadastro_exemplo()
    assert cadastro_aplicar.aplicar(conn, 1, cad)["frc"]["criados"] == ["consorcio-exemplo"]
    r = conn.execute("SELECT formulario, ultimo_anterior, dados FROM frc_consorcios").fetchall()
    assert [(x[0], x[1]) for x in r] == [("A", 40)]
    dados = json.loads(r[0][2])
    assert dados["tomador"]["email"] == "fiscal@exemplo.gov.br" and dados["prestador"]["email"] == "contato@exemplo.com.br"
    assert dados["logo"].startswith("modelos/") and arquivos.caminho_seguro(dados["logo"]).is_file()
    assert cadastro_aplicar.aplicar(conn, 1, cad)["frc"] == {"criados": [], "alterados": [], "iguais": 1}


def test_frc_com_outro_destinatario_atualiza_e_audita(conn):
    cad = _cadastro_exemplo()
    cadastro_aplicar.aplicar(conn, 1, cad)
    cad["frc"][0]["dados"]["tomador"]["email"] = "outra.fiscal@exemplo.gov.br"
    assert cadastro_aplicar.aplicar(conn, 1, cad)["frc"]["alterados"] == ["consorcio-exemplo"]
    dados = json.loads(conn.execute("SELECT dados FROM frc_consorcios").fetchone()[0])
    assert dados["tomador"]["email"] == "outra.fiscal@exemplo.gov.br"
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cadastro.frc'").fetchone()[0] == 2


def test_frc_semeada_no_formato_antigo_so_troca_o_logo(conn):
    """A producao tem a linha da semente antiga da 032 (JSON em outra ordem, logo `frc-integra-brt.jpg`, que saiu do
    app). O frc.yaml com os mesmos dados troca so' o logo pelo arquivo copiado; nada se perde e a auditoria guarda
    o antes."""
    cad = _cadastro_exemplo()
    f = cad["frc"][0]
    antigo = {"logo": "frc-integra-brt.jpg", **{k: f["dados"][k] for k in reversed(list(f["dados"]))}}
    conn.execute("INSERT INTO frc_consorcios (consorcio, formulario, ultimo_anterior, dados) VALUES (?, 'A', 40, ?)",
                 (f["consorcio"], json.dumps(antigo, ensure_ascii=False)))
    conn.commit()
    assert cadastro_aplicar.aplicar(conn, 1, cad)["frc"]["alterados"] == ["consorcio-exemplo"]
    linha = conn.execute("SELECT formulario, ultimo_anterior, dados FROM frc_consorcios").fetchone()
    novo = json.loads(linha["dados"])
    assert (linha["formulario"], linha["ultimo_anterior"]) == ("A", 40)
    assert novo.pop("logo").startswith("modelos/") and {k: v for k, v in antigo.items() if k != "logo"} == novo
    antes = json.loads(conn.execute("SELECT antes FROM audit_log WHERE acao='cadastro.frc'").fetchone()[0])
    assert json.loads(antes["dados"])["logo"] == "frc-integra-brt.jpg" and set(antes) == {"dados"}


def test_ensaio_da_frc_nao_grava_nem_copia_o_logo(conn):
    r = cadastro_aplicar.aplicar(conn, 1, _cadastro_exemplo(), ensaio=True)
    assert r["frc"]["criados"] == ["consorcio-exemplo"]
    assert conn.execute("SELECT COUNT(*) FROM frc_consorcios").fetchone()[0] == 0
    assert not list((db.db_path().parent / "modelos").glob("*.jpg"))


# --- issue #65: garantia do contrato, copiada para a pasta de dados -------------------------

def test_garantia_gravada_e_ensaio_nao_copia(conn, tmp_path):
    from app import arquivos
    gar = tmp_path / "gar.pdf"
    gar.write_bytes(b"%PDF-1.4 gar")
    cad = _cad(contratos=[_contrato(garantia_apolice="AP-9",
                                    garantia_vigencia_fim="2027-03-31", garantia_caminho=str(gar))])
    cadastro_aplicar.aplicar(conn, 1, cad, ensaio=True)
    assert not (arquivos.pasta("anexos") / f"{arquivos.sha_de(b'%PDF-1.4 gar')}.pdf").exists()
    cadastro_aplicar.aplicar(conn, 1, cad)
    c = conn.execute("SELECT art, art_arquivo, garantia_apolice, garantia_vigencia_fim, garantia_arquivo "
                     "FROM contratos").fetchone()
    assert (c["art"], c["art_arquivo"]) == (None, None)       # a ART saiu do contrato (#239)
    assert (c["garantia_apolice"], c["garantia_vigencia_fim"]) == ("AP-9", "2027-03-31")
    assert arquivos.caminho_seguro(c["garantia_arquivo"]).is_file()
    assert cadastro_aplicar.aplicar(conn, 1, cad)["contratos"]["iguais"] == 1


def test_endosso_com_vigencia_aplicado_e_imutavel(conn):
    inst = {"chave": "end-1", "tipo": "endosso_garantia", "numero": None, "objeto": None, "corrige": None,
            "pdf": None, "data": "2026-09-01", "delta_valor_centavos": 0, "nova_execucao_fim": None,
            "nova_vigencia_fim": None, "dados": {"vigencia_fim": "2027-09-30", "apolice": "AP-1"}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[inst])]))
    dados = json.loads(conn.execute("SELECT dados FROM instrumentos").fetchone()[0])
    assert dados["vigencia_fim"] == "2027-09-30"
    troca = {**inst, "dados": {"vigencia_fim": "2028-01-01"}}
    with pytest.raises(ValueError, match="já aplicado"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[troca])]))


# --- issue #256: cronograma por versao, com a data do documento -------------------------------

from app import cronograma as cronograma_mod

V_CONTRATUAL = {"chave": "contratual", "origem": "contratual", "data": "2024-03-11", "instrumento": None,
                "itens": [("2024-04", 100_01), ("2026-10", 200_00), ("2026-11", 300_00)]}
V_TA = {"chave": "ta-01", "origem": "aditivo", "data": "2026-10-05", "instrumento": "ta-01",
        "itens": [("2026-10", 250_00), ("2026-12", 400_00)]}


def test_cronograma_aplicado_cria_uma_versao_por_entrada_com_a_data_do_documento(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma=[V_TA, V_CONTRATUAL])]))
    vs = conn.execute("SELECT v.numero, v.criado_em, k.chave, k.origem, k.data_documento, k.instrumento "
                      "FROM cronograma_versoes v JOIN cronograma_versoes_cadastro k ON k.versao_id=v.id "
                      "ORDER BY v.numero").fetchall()
    # numero pela ordem do documento (nao a do arquivo); criado_em = meia-noite de Cuiaba do dia do documento
    assert [tuple(v) for v in vs] == [
        (1, "2024-03-11 04:00:00", "contratual", "contratual", "2024-03-11", None),
        (2, "2026-10-05 04:00:00", "ta-01", "aditivo", "2026-10-05", "ta-01")]
    assert cronograma_mod.previsto_efetivo(conn, 1) == {"2024-04": 100_01, "2026-10": 250_00, "2026-12": 400_00}
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cronograma.nova_versao'").fetchone()[0] == 2


def test_aplicar_cronograma_duas_vezes_nao_duplica(conn):
    cad = _cad(contratos=[_contrato(cronograma=[V_CONTRATUAL, V_TA])])
    r1 = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r1["cronograma"]["criados"] == ["MT-402/contratual (11/03/2024)", "MT-402/ta-01 (05/10/2026)"]
    assert not any("vigente" in a for a in r1["avisos"])     # a ultima aplicada e' a vigente: sem aviso
    r2 = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r2["cronograma"] == {"criados": [], "alterados": [], "iguais": 2}
    assert conn.execute("SELECT COUNT(*) FROM cronograma_versoes").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM cronograma_itens").fetchone()[0] == 5


@pytest.mark.parametrize("troca", [{"itens": [("2026-10", 250_01), ("2026-12", 400_00)]},
                                   {"itens": [("2026-10", 250_00)]},
                                   {"data": "2026-10-06"}, {"origem": "carta"}, {"instrumento": "ta-02"}])
def test_versao_de_cronograma_aplicada_nao_se_altera(conn, troca):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma=[V_TA])]))
    with pytest.raises(ValueError, match="já aplicada"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma=[{**V_TA, **troca}])]))
    assert conn.execute("SELECT COUNT(*) FROM cronograma_versoes").fetchone()[0] == 1
    assert [tuple(r) for r in conn.execute("SELECT competencia, valor_previsto_centavos FROM cronograma_itens "
                                           "ORDER BY competencia")] == [("2026-10", 250_00), ("2026-12", 400_00)]


def test_versao_de_cronograma_aplicada_que_some_do_cadastro_e_recusada(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma=[V_CONTRATUAL])]))
    with pytest.raises(ValueError, match="sumiu"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma=[])]))


def test_ensaio_lista_as_versoes_de_cronograma_e_nao_grava(conn):
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma=[V_CONTRATUAL, V_TA])]), ensaio=True)
    assert r["cronograma"]["criados"] == ["MT-402/contratual (11/03/2024)", "MT-402/ta-01 (05/10/2026)"]
    assert conn.execute("SELECT COUNT(*) FROM cronograma_versoes").fetchone()[0] == 0


def test_versao_da_carga_fica_superada_so_pela_versao_do_yaml_de_data_posterior(conn):
    """As versoes da carga de 04/09/2026 nao se apagam: a versao do YAML com documento ANTERIOR entra antes
    dela na linha do tempo, e a primeira com documento POSTERIOR a supera."""
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato()]))
    cronograma_mod.nova_versao(conn, 1, 1, [("2026-08", 50_00), ("2026-09", 60_00), ("2026-10", 70_00),
                                            ("2026-11", 80_00)], "manual")
    conn.execute("UPDATE cronograma_versoes SET criado_em='2026-09-04 15:00:00'")
    conn.commit()
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma=[V_CONTRATUAL])]))
    assert cronograma_mod.vigente(conn, 1)["numero"] == 1                  # a carga segue vigente
    # quem aplica fica sabendo que a versao nova nao mexeu no futuro
    assert any("MT-402/contratual" in a and "não é a vigente" in a for a in r["avisos"])
    assert cronograma_mod.previsto_efetivo(conn, 1) == {
        "2024-04": 100_01, "2026-08": 50_00, "2026-09": 60_00, "2026-10": 70_00, "2026-11": 80_00}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma=[V_CONTRATUAL, V_TA])]))
    assert cronograma_mod.vigente(conn, 1)["numero"] == 3                  # o aditivo supera a carga
    assert cronograma_mod.previsto_efetivo(conn, 1) == {
        "2024-04": 100_01, "2026-08": 50_00, "2026-09": 60_00, "2026-10": 250_00, "2026-12": 400_00}
    assert conn.execute("SELECT COUNT(*) FROM cronograma_versoes").fetchone()[0] == 3     # nada apagado
