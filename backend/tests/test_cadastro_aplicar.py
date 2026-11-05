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


def test_aplica_a_da_data_base_e_gravado_e_mudanca_so_nele_sincroniza(conn):
    # issue #257: `aplica_a` e' configuracao da data-base como o indice; mudar so' ele tambem atualiza
    bases = [{"mes": "2022-01", "indice": "INCC-DI", "aplica_a": "itens SINAPI"},
             {"mes": "2022-03", "indice": "FGV/DNIT", "aplica_a": "itens SICRO"}]
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(datas_base=bases)]))
    assert [tuple(r) for r in conn.execute("SELECT mes, indice, aplica_a FROM contrato_datas_base ORDER BY mes")] == [
        ("2022-01", "INCC-DI", "itens SINAPI"), ("2022-03", "FGV/DNIT", "itens SICRO")]
    bases[1] = {**bases[1], "aplica_a": "itens SICRO e DNIT"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(datas_base=bases)]))
    assert conn.execute("SELECT aplica_a FROM contrato_datas_base WHERE mes='2022-03'").fetchone()[0] == "itens SICRO e DNIT"


from app import contratos as contratos_mod

AD_VALOR = {"chave": "ta-01", "tipo": "aditivo_valor", "data": "2026-06-30", "numero": "019/2024/01/01",
            "objeto": "1ª revisão em fase de obra", "corrige": None, "pdf": None,
            "delta_valor_centavos": 323606718, "nova_execucao_fim": None, "nova_vigencia_fim": None, "dados": {},
            "natureza": "execucao"}
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


def test_natureza_do_aditivo_e_gravada(conn):
    """#262: o aditivo de reajuste (SES) entra no vigente mas fica fora do saldo."""
    reaj = {**AD_VALOR, "chave": "ta-08", "data": "2026-07-30", "delta_valor_centavos": 100_01, "natureza": "reajuste"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AD_VALOR, reaj])]))
    nat = dict(conn.execute("SELECT chave_cadastro, natureza FROM aditivos").fetchall())
    assert nat == {"ta-01": "execucao", "ta-08": "reajuste"}
    v = contratos_mod.vigente(conn, 1)
    assert v["valor_vigente_centavos"] == 1512720000 + 323606718 + 100_01
    assert v["valor_vigente_execucao_centavos"] == 1512720000 + 323606718
    assert v["valor_reajuste_centavos"] == 100_01


def test_aditivo_de_valor_novo_sem_natureza_e_recusado(conn):
    """Gate Sol (#262): o NULL e' so' do legado. Aditivo de valor novo sem `natureza` voltaria a inflar o saldo
    em silencio, entao o aplicar recusa e nada e' gravado. Instrumento sem valor (prazo) nao precisa."""
    sem = {k: v for k, v in AD_VALOR.items() if k != "natureza"}
    with pytest.raises(ValueError, match="natureza"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[sem])]))
    assert conn.execute("SELECT COUNT(*) FROM aditivos").fetchone()[0] == 0
    misto = {**sem, "chave": "tm-01", "tipo": "aditivo_misto", "nova_execucao_fim": "2027-01-31"}
    with pytest.raises(ValueError, match="natureza"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[misto])]))
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_PRAZO])]))
    assert conn.execute("SELECT natureza FROM aditivos").fetchone()[0] is None


def _legado(conn):
    """Aditivo aplicado antes da 046: a coluna ficou NULL (nao classificado, conta como execucao)."""
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AD_VALOR])]))
    conn.execute("UPDATE aditivos SET natureza=NULL"); conn.commit()


def _natureza_aplicada(conn, natureza):
    inst = {**AD_VALOR, "natureza": natureza}
    if natureza is None:
        del inst["natureza"]
    return cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[inst])]))


def test_natureza_primeira_classificacao_aceita_e_troca_depois_recusada(conn):
    """O aditivo legado (NULL) aceita a PRIMEIRA classificacao, auditada; depois ela trava como valor e data:
    trocar ou apagar o campo e' recusado e nada muda."""
    _legado(conn)
    assert _natureza_aplicada(conn, None)["instrumentos"]["iguais"] == 1          # legado sem o campo: igual
    r = _natureza_aplicada(conn, "reajuste")
    assert r["instrumentos"]["alterados"] == ["MT-402/ta-01"]
    assert conn.execute("SELECT natureza FROM aditivos").fetchone()[0] == "reajuste"
    ult = conn.execute("SELECT antes, depois FROM audit_log WHERE acao='cadastro.instrumento' ORDER BY id DESC").fetchone()
    assert json.loads(ult["antes"])["natureza"] is None and json.loads(ult["depois"])["natureza"] == "reajuste"
    assert _natureza_aplicada(conn, "reajuste")["instrumentos"]["iguais"] == 1
    for troca in ("execucao", None):                     # trocar, ou apagar sem querer, nao passa
        with pytest.raises(ValueError, match="já aplicado.*natureza.*corrige"):
            _natureza_aplicada(conn, troca)
        assert conn.execute("SELECT natureza FROM aditivos").fetchone()[0] == "reajuste"


def test_natureza_execucao_declarada_tambem_trava(conn):
    _natureza_aplicada(conn, "execucao")
    with pytest.raises(ValueError, match="já aplicado"):
        _natureza_aplicada(conn, "reajuste")
    assert conn.execute("SELECT natureza FROM aditivos").fetchone()[0] == "execucao"


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
    # o aditivo (issue #396) substitui a curva inteira: o previsto da contratual que ele nao traz sai
    assert cronograma_mod.previsto_efetivo(conn, 1) == {"2026-10": 250_00, "2026-12": 400_00}
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
        "2026-10": 250_00, "2026-12": 400_00}      # issue #396: o aditivo substitui a curva inteira
    assert conn.execute("SELECT COUNT(*) FROM cronograma_versoes").fetchone()[0] == 3     # nada apagado


# --- issue #395: cronograma_superadas tira a carga de 04/09/2026 da linha do tempo -------------------------

def _com_carga(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato()]))
    cronograma_mod.nova_versao(conn, 1, 1, [("2026-08", 50_00), ("2026-09", 60_00), ("2026-10", 70_00),
                                            ("2026-11", 80_00)], "manual")
    conn.execute("UPDATE cronograma_versoes SET criado_em='2026-09-04 15:00:00'")
    conn.commit()


def test_cronograma_superadas_supera_a_carga_com_auditoria(conn):
    _com_carga(conn)
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma=[V_CONTRATUAL],
                                                                    cronograma_superadas=[1])]))
    assert "MT-402: versão 1 superada" in r["cronograma"]["alterados"]
    assert not any("não é a vigente" in a for a in r["avisos"])        # a do documento passou a mandar
    assert cronograma_mod.vigente(conn, 1)["numero"] == 2
    assert cronograma_mod.previsto_efetivo(conn, 1) == {"2024-04": 100_01, "2026-10": 200_00, "2026-11": 300_00}
    sup = conn.execute("SELECT superada_em FROM cronograma_versoes WHERE numero=1").fetchone()[0]
    assert sup is not None
    aud = conn.execute("SELECT entidade, entidade_id, depois FROM audit_log "
                       "WHERE acao='cadastro.cronograma_superada'").fetchall()
    assert [(a[0], a[1], json.loads(a[2])) for a in aud] == [("contrato", "1", {"versao": 1, "superada_em": sup})]
    assert conn.execute("SELECT COUNT(*) FROM cronograma_versoes").fetchone()[0] == 2     # nada apagado


def test_cronograma_superadas_segunda_aplicacao_e_igual_e_tirar_da_lista_nao_dessupera(conn):
    _com_carga(conn)
    cad = _cad(contratos=[_contrato(cronograma=[V_CONTRATUAL], cronograma_superadas=[1])])
    cadastro_aplicar.aplicar(conn, 1, cad)
    sup = conn.execute("SELECT superada_em FROM cronograma_versoes WHERE numero=1").fetchone()[0]
    r2 = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r2["cronograma"] == {"criados": [], "alterados": [], "iguais": 2}      # a versao 2 e a superada
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma=[V_CONTRATUAL])]))
    assert conn.execute("SELECT superada_em FROM cronograma_versoes WHERE numero=1").fetchone()[0] == sup
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cadastro.cronograma_superada'").fetchone()[0] == 1


def test_ensaio_relata_a_versao_superada_e_nao_grava(conn):
    _com_carga(conn)
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma_superadas=[1])]), ensaio=True)
    assert r["cronograma"]["alterados"] == ["MT-402: versão 1 superada"]
    # sem versao de documento no YAML, a obra fica sem vigente: quem aplica fica sabendo no ensaio
    assert any("MT-402" in a and "sem cronograma vigente" in a for a in r["avisos"])
    assert conn.execute("SELECT superada_em FROM cronograma_versoes WHERE numero=1").fetchone()[0] is None


def test_cronograma_superadas_com_numero_inexistente_e_recusado(conn):
    _com_carga(conn)
    with pytest.raises(ValueError, match="versão 7 não existe"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma_superadas=[1, 7])]))
    assert conn.execute("SELECT superada_em FROM cronograma_versoes WHERE numero=1").fetchone()[0] is None


def test_cronograma_superadas_com_versao_do_cadastro_e_recusado(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma=[V_CONTRATUAL])]))
    with pytest.raises(ValueError, match="versão 1 veio do cadastro .*contratual"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(cronograma=[V_CONTRATUAL],
                                                                    cronograma_superadas=[1])]))
    assert conn.execute("SELECT superada_em FROM cronograma_versoes").fetchone()[0] is None


# --- issue #271: apostilamento com competencias vira previsao e atende o pleito (spec 2026-10-20 §2.2) ----------

from app import reajuste as reajuste_mod

PLEITO_2026 = {"tipo": "reajuste", "oficio": "CT-122-LT-2026", "data": "2026-04-23", "data_base": "2023-04",
               "ciclo": 2026, "dias": None}
AP_COMP = {**AP_REAJ, "chave": "ap-11", "data": "2026-09-15", "numero": "019/2024/02/11",
           "dados": {"data_base": "2023-04", "ciclo": 2026, "periodo": {"de": "2026-04", "ate": "2026-06"},
                     "competencias": [{"competencia": "2026-04", "valor": "1.234,57", "medicao": 24},
                                      {"competencia": "2026-05", "valor": "2.000,01", "medicao": 25}]}}


def _previsoes(conn):
    return [tuple(r) for r in conn.execute(
        "SELECT data_base_mes, ciclo, competencia, valor_previsto_centavos, origem, instrumento_id, usuario_id "
        "FROM reajuste_previsoes ORDER BY id")]


def test_apostilamento_com_competencias_grava_previsoes_e_liga_o_pleito(conn):
    cad = _cad(contratos=[_contrato(instrumentos=[AP_COMP], pleitos_anteriores=[PLEITO_2026])])
    cadastro_aplicar.aplicar(conn, 1, cad)
    inst = conn.execute("SELECT id FROM instrumentos WHERE chave='ap-11'").fetchone()[0]
    assert _previsoes(conn) == [("2023-04", 2026, "2026-04", 123457, "apostilamento", inst, 1),
                                ("2023-04", 2026, "2026-05", 200001, "apostilamento", inst, 1)]
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] == "ap-11"
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cadastro.reajuste_previsoes'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cadastro.pleito_atendido'").fetchone()[0] == 1
    # segunda aplicacao: nada duplica, nada se audita de novo
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["instrumentos"]["iguais"] == 1
    assert len(_previsoes(conn)) == 2
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao IN "
                        "('cadastro.reajuste_previsoes','cadastro.pleito_atendido')").fetchone()[0] == 2


def test_pleito_que_entra_depois_do_apostilamento_tambem_e_ligado(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP])]))
    assert len(_previsoes(conn)) == 2
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP],
                                                                pleitos_anteriores=[PLEITO_2026])]))
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] == "ap-11"


def test_apostilamento_sem_competencias_nao_grava_previsao_mas_atende_o_pleito(conn):
    ap = {**AP_REAJ, "data": "2026-09-15", "dados": {"data_base": "2023-04", "ciclo": 2026, "percentual": "6,76"}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[ap], pleitos_anteriores=[PLEITO_2026])]))
    assert _previsoes(conn) == []
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] == "ap-09"


def test_apostilamento_de_outro_ciclo_nao_atende_o_pleito(conn):
    ap = {**AP_COMP, "dados": {**AP_COMP["dados"], "ciclo": 2025, "periodo": None,
                               "competencias": [{"competencia": "2025-04", "valor": "1,00"}]}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[ap], pleitos_anteriores=[PLEITO_2026])]))
    assert [p[1:3] for p in _previsoes(conn)] == [(2025, "2025-04")]
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] is None


def test_termo_com_corrige_gera_previsoes_novas_que_valem_e_as_antigas_ficam(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP], pleitos_anteriores=[PLEITO_2026])]))
    correcao = {**AP_COMP, "chave": "ap-12", "numero": "019/2024/02/12", "data": "2026-10-01", "corrige": "ap-11",
                "dados": {**AP_COMP["dados"], "competencias": [{"competencia": "2026-04", "valor": "1.300,03", "medicao": 24}]}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP, correcao],
                                                                pleitos_anteriores=[PLEITO_2026])]))
    ids = dict(conn.execute("SELECT chave, id FROM instrumentos").fetchall())
    # as antigas continuam no historico
    assert [(p[2], p[3], p[5]) for p in _previsoes(conn)] == [
        ("2026-04", 123457, ids["ap-11"]), ("2026-05", 200001, ids["ap-11"]), ("2026-04", 130003, ids["ap-12"])]
    vig = {p["competencia"]: (p["valor_previsto_centavos"], p["instrumento_id"])
           for p in reajuste_mod.previsoes_vigentes(conn, 1)}
    # a correcao passa a valer, e o termo corrigido deixa de valer por inteiro: a competencia que a correcao nao
    # repete fica sem previsao de apostilamento (gates da PR #317)
    assert vig == {"2026-04": (130003, ids["ap-12"])}
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] == "ap-12"


def test_competencia_listada_por_engano_some_com_a_correcao(conn):
    errado = {**AP_COMP, "dados": {**AP_COMP["dados"], "periodo": None,
                                   "competencias": [{"competencia": "2026-04", "valor": "1,01"},
                                                    {"competencia": "2026-07", "valor": "7,07"}]}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[errado])]))
    correcao = {**AP_COMP, "chave": "ap-12", "data": "2026-10-01", "corrige": "ap-11",
                "dados": {**AP_COMP["dados"], "periodo": None,
                          "competencias": [{"competencia": "2026-04", "valor": "1,03"},
                                           {"competencia": "2026-06", "valor": "6,05"}]}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[errado, correcao])]))
    vig = {p["competencia"]: p["valor_previsto_centavos"] for p in reajuste_mod.previsoes_vigentes(conn, 1)}
    assert vig == {"2026-04": 103, "2026-06": 605}
    assert [x["competencia"] for x in reajuste_mod.competencias_apostiladas(conn, 1)] == ["2026-04", "2026-06"]


def _termo(chave, data, valor, corrige=None, ciclo=2026):
    return {**AP_COMP, "chave": chave, "numero": f"{chave}/2026", "data": data, "corrige": corrige,
            "dados": {"data_base": "2023-04", "ciclo": ciclo, "competencias": [{"competencia": "2026-04", "valor": valor}]}}


def test_termo_antigo_acrescentado_depois_nao_passa_por_cima_do_mais_novo(conn):
    novo = _termo("ap-novo", "2026-10-01", "2,03")
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[novo])]))
    antigo = _termo("ap-antigo", "2026-08-01", "1,01")
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[novo, antigo])]))
    assert [(x["valor_centavos"], x["instrumento_chave"]) for x in reajuste_mod.competencias_apostiladas(conn, 1)] \
        == [(203, "ap-novo")]


def test_correcao_aplicada_depois_de_termo_mais_novo_nao_passa_por_cima_dele(conn):
    t1 = _termo("ap-t1", "2026-09-01", "1,01")
    t3 = _termo("ap-t3", "2026-10-10", "3,03")
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[t1])]))
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[t1, t3])]))
    t2 = _termo("ap-t2", "2026-10-01", "2,05", corrige="ap-t1")
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[t1, t3, t2])]))
    assert [(x["valor_centavos"], x["instrumento_chave"]) for x in reajuste_mod.competencias_apostiladas(conn, 1)] \
        == [(303, "ap-t3")]


def test_termo_corrigido_nao_fecha_o_ciclo(conn):
    import datetime
    hoje = datetime.date(2026, 10, 20)
    t1 = _termo("ap-t1", "2026-09-01", "1,01")
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[t1])]))
    assert reajuste_mod.ciclos(conn, 1, hoje)[0]["situacao"] == "apostilado"
    # a correcao diz que o termo era do ciclo 2025: o de 2026 volta a esperar apostilamento
    t2 = _termo("ap-t2", "2026-10-01", "1,03", corrige="ap-t1", ciclo=2025)
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[t1, t2])]))
    assert reajuste_mod.ciclos(conn, 1, hoje)[0]["situacao"] == "pleito_pendente"


def test_correcao_herda_o_pleito_do_termo_corrigido_antes_de_buscar_por_data(conn):
    # A foi atendido por T1; B (reemissao) saiu depois de T1 e antes da correcao, e continua esperando o termo dela
    reemissao = {**PLEITO_2026, "oficio": "CT-200-LT-2026", "data": "2026-09-20"}
    cad = lambda insts: _cad(contratos=[_contrato(instrumentos=insts, pleitos_anteriores=[PLEITO_2026, reemissao])])  # noqa: E731
    cadastro_aplicar.aplicar(conn, 1, cad([AP_COMP]))
    correcao = {**AP_COMP, "chave": "ap-12", "data": "2026-10-01", "corrige": "ap-11"}
    cadastro_aplicar.aplicar(conn, 1, cad([AP_COMP, correcao]))
    ligados = dict(conn.execute("SELECT numero_oficio, instrumento_chave FROM pleitos").fetchall())
    assert ligados == {"CT-122-LT-2026": "ap-12", "CT-200-LT-2026": None}


def test_correcao_para_outro_ciclo_nao_herda_o_pleito_e_ele_fica_sem_termo(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP], pleitos_anteriores=[PLEITO_2026])]))
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] == "ap-11"
    # ap-12 corrige ap-11 dizendo que o termo era do ciclo 2025: o pleito de 2026 nao foi atendido por ele
    outro_ciclo = {**AP_COMP, "chave": "ap-12", "data": "2026-10-01", "corrige": "ap-11",
                   "dados": {**AP_COMP["dados"], "ciclo": 2025, "periodo": None,
                             "competencias": [{"competencia": "2025-04", "valor": "1,00"}]}}
    cad = _cad(contratos=[_contrato(instrumentos=[AP_COMP, outro_ciclo], pleitos_anteriores=[PLEITO_2026])])
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] is None
    assert r["pleitos"]["alterados"] == ["MT-402/reajuste CT-122-LT-2026: sem termo (ap-12 corrige ap-11 para outro ciclo)"]
    assert reajuste_mod.ciclos(conn, 1, __import__("datetime").date(2026, 10, 20))[0]["situacao"] == \
        "apostilamento_pendente"
    # reaplicar nao mexe de novo nem audita de novo
    antes = conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cadastro.pleito_atendido'").fetchone()[0]
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["pleitos"]["alterados"] == []
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cadastro.pleito_atendido'").fetchone()[0] == antes


def test_competencias_sem_ciclo_determinavel_e_erro_no_aplicar(conn):
    ruim = {**AP_COMP, "dados": {"competencias": [{"competencia": "2026-04", "valor": "1,00"}], "eficacia": "x"},
            "data": "2026-09-15"}
    ruim["dados"]["ciclo"] = "abc"
    with pytest.raises(ValueError, match="ciclo"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[ruim])]))
    assert conn.execute("SELECT COUNT(*) FROM instrumentos").fetchone()[0] == 0


def test_termo_aplicado_sem_data_base_segue_na_base_gravada_quando_entra_a_segunda(conn):
    # gate Sol (PR #317, S2): termo aplicado com uma base so' no contrato, sem `data_base` (imutavel); depois o
    # cadastro ganha a segunda base. O aplicar nao recusa: o termo segue na base e no ciclo das previsoes gravadas
    dados = {k: v for k, v in AP_COMP["dados"].items() if k != "data_base"}
    termo = {**AP_COMP, "dados": dados}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[termo])]))
    antes = _previsoes(conn)
    assert {x[0] for x in antes} == {"2023-04"}
    duas = [{"mes": "2023-04", "indice": "setorial"}, {"mes": "2023-06", "indice": "FGV/DNIT"}]
    pleito = {**PLEITO_2026}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[termo], datas_base=duas,
                                                                pleitos_anteriores=[pleito])]))
    assert _previsoes(conn) == antes
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] == "ap-11"


def test_termo_novo_sem_data_base_em_contrato_de_duas_bases_e_erro_no_aplicar(conn):
    dados = {k: v for k, v in AP_COMP["dados"].items() if k != "data_base"}
    duas = [{"mes": "2023-04", "indice": "setorial"}, {"mes": "2023-06", "indice": "FGV/DNIT"}]
    with pytest.raises(ValueError, match="data-base"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[{**AP_COMP, "dados": dados}],
                                                                    datas_base=duas)]))
    assert conn.execute("SELECT COUNT(*) FROM instrumentos").fetchone()[0] == 0


DUAS_BASES = [{"mes": "2023-04", "indice": "setorial"}, {"mes": "2023-06", "indice": "FGV/DNIT"}]
SO_PERCENTUAL = {**AP_REAJ, "chave": "ap-11", "data": "2026-09-15", "numero": "019/2024/02/11",
                 "dados": {"ciclo": 2026, "percentual": "6,76"}}


def _situacao(conn):
    import datetime
    return {k["data_base_mes"]: k["situacao"] for k in reajuste_mod.ciclos(conn, 1, datetime.date(2026, 10, 1))}


def test_termo_so_com_percentual_guarda_a_base_e_segue_fechando_o_ciclo_quando_entra_a_segunda(conn):
    # Gate Sol (rodada 3, PR #317), item 1: termo sem `data_base` e sem competencias (estilo MT-PAR), aplicado com uma
    # base so'; nao grava previsao. A base vai junto com o termo, e a 2a base nao reabre o ciclo
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[SO_PERCENTUAL])]))
    assert conn.execute("SELECT data_base_mes FROM instrumentos WHERE chave='ap-11'").fetchone()[0] == "2023-04"
    assert _previsoes(conn) == []
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[SO_PERCENTUAL], datas_base=DUAS_BASES)]))
    assert _situacao(conn) == {"2023-04": "apostilado", "2023-06": "pleito_pendente"}
    assert reajuste_mod.bases_dos_termos(conn, 1)[0]["data_base_mes"] == "2023-04"


def test_termo_novo_sem_base_que_corrige_outro_e_recusado_e_nada_muda(conn):
    # item 2: em contrato de duas bases, o termo novo sem `data_base` e sem competencias que corrige outro era gravado,
    # tirava o anterior do ciclo e desligava o pleito dele, e depois era ignorado; agora o aplicar recusa
    t1 = {**SO_PERCENTUAL, "dados": {"data_base": "2023-04", "ciclo": 2026, "percentual": "6,76"}}
    cad = dict(datas_base=DUAS_BASES, pleitos_anteriores=[PLEITO_2026])
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[t1], **cad)]))
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] == "ap-11"
    t2 = {**SO_PERCENTUAL, "chave": "ap-12", "numero": "019/2024/02/12", "data": "2026-09-20", "corrige": "ap-11",
          "dados": {"ciclo": 2026, "percentual": "6,80"}}
    with pytest.raises(ValueError, match="data-base"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[t1, t2], **cad)]))
    assert conn.execute("SELECT COUNT(*) FROM instrumentos").fetchone()[0] == 1
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] == "ap-11"
    assert _situacao(conn)["2023-04"] == "apostilado"


def test_base_guardada_do_termo_vence_a_base_unica_nova(conn):
    # item 3: o termo gravou previsoes na 2023-04 e o cadastro troca a base unica para 2023-06; o termo fica na 2023-04
    dados = {k: v for k, v in AP_COMP["dados"].items() if k != "data_base"}
    termo = {**AP_COMP, "dados": dados}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[termo])]))
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[termo],
                                                                datas_base=[{"mes": "2023-06", "indice": "FGV/DNIT"}])]))
    assert _situacao(conn) == {"2023-06": "pleito_pendente"}
    assert reajuste_mod.bases_dos_termos(conn, 1)[0]["data_base_mes"] == "2023-04"


def test_termo_e_correcao_aplicados_juntos_a_correcao_vale_mesmo_com_data_anterior(conn):
    # a ordem de gravacao segue o `corrige`, nao so' a data: a correcao nunca fica atras do termo que corrige
    correcao = {**AP_COMP, "chave": "ap-12", "numero": "019/2024/02/12", "data": "2026-09-01", "corrige": "ap-11",
                "dados": {**AP_COMP["dados"], "competencias": [{"competencia": "2026-04", "valor": "1.300,03"}]}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[correcao, AP_COMP],
                                                                pleitos_anteriores=[PLEITO_2026])]))
    vig = {p["competencia"]: p["valor_previsto_centavos"] for p in reajuste_mod.previsoes_vigentes(conn, 1)}
    assert vig == {"2026-04": 130003}
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] == "ap-12"


def test_pleito_enviado_depois_do_termo_nao_e_atendido_por_ele(conn):
    # reemissao depois do termo (aditivo) espera o apostilamento dela; o pleito anterior e' o atendido
    reemissao = {**PLEITO_2026, "oficio": "CT-200-LT-2026", "data": "2026-11-05"}
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP],
                                                                    pleitos_anteriores=[PLEITO_2026, reemissao])]))
    ligados = dict(conn.execute("SELECT numero_oficio, instrumento_chave FROM pleitos").fetchall())
    assert ligados == {"CT-122-LT-2026": "ap-11", "CT-200-LT-2026": None}
    # o relatorio do aplicar (e do ensaio) diz qual pleito o termo atendeu
    assert r["pleitos"]["alterados"] == ["MT-402/reajuste CT-122-LT-2026: atendido por ap-11"]


def test_correcao_de_correcao_religa_o_pleito_mesmo_sem_o_termo_do_meio(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP], pleitos_anteriores=[PLEITO_2026])]))
    # ap-12 corrige ap-11, mas e' de outro ciclo (nao toca o pleito de 2026); ap-13 corrige ap-12
    meio = {**AP_COMP, "chave": "ap-12", "data": "2026-10-01", "corrige": "ap-11",
            "dados": {**AP_COMP["dados"], "ciclo": 2025, "periodo": None,
                      "competencias": [{"competencia": "2025-04", "valor": "1,00"}]}}
    fim = {**AP_COMP, "chave": "ap-13", "data": "2026-10-10", "corrige": "ap-12"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP, meio, fim],
                                                                pleitos_anteriores=[PLEITO_2026])]))
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] == "ap-13"


def test_ensaio_do_apostilamento_nao_grava_previsao(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP],
                                                                pleitos_anteriores=[PLEITO_2026])]), ensaio=True)
    assert conn.execute("SELECT COUNT(*) FROM reajuste_previsoes").fetchone()[0] == 0


# --- issue #399: correcao de pleito anterior aplicado pelo YAML ---------------------------------------

from app import pleitos as pleitos_mod

PRAZO_ERRADO = {"tipo": "prazo", "oficio": "CT-001-LT-2026", "data": "2026-08-14", "data_base": None,
                "ciclo": None, "dias": 180}
PRAZO_CERTO = {**PRAZO_ERRADO, "data": "2026-05-06", "corrige": {"oficio": "CT-001-LT-2026", "data": "2026-08-14"}}


def _pleito_auditoria(conn):
    return [(json.loads(r[0] or "null"), json.loads(r[1])) for r in conn.execute(
        "SELECT antes, depois FROM audit_log WHERE acao='cadastro.pleito' ORDER BY id")]


def test_correcao_da_data_do_pleito_grava_audita_e_e_igual_depois(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PRAZO_ERRADO])]))
    cad = _cad(contratos=[_contrato(pleitos_anteriores=[PRAZO_CERTO])])
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["pleitos"]["alterados"] == ["MT-402/prazo: pleito CT-001-LT-2026: data 14/08/2026 → 06/05/2026"]
    # a aba Prazos lista o pleito com a data nova; nao nasceu outro
    lista = pleitos_mod.listar(conn, 1, ("prazo", "conclusao"))
    assert [(p["numero_oficio"], p["enviado_em"]) for p in lista] == [("CT-001-LT-2026", "2026-05-06")]
    antes, depois = _pleito_auditoria(conn)[-1]
    assert antes == {"enviado_em": "2026-08-14"} and depois == {"enviado_em": "2026-05-06"}
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["pleitos"] == {"criados": [], "alterados": [], "iguais": 1}
    assert len(_pleito_auditoria(conn)) == 2          # a criacao e a correcao, nada mais


def test_ensaio_da_correcao_relata_e_nao_grava(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PRAZO_ERRADO])]))
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PRAZO_CERTO])]), ensaio=True)
    assert any("pleito CT-001-LT-2026: data 14/08/2026 → 06/05/2026" in x for x in r["pleitos"]["alterados"])
    assert conn.execute("SELECT enviado_em FROM pleitos").fetchone()[0] == "2026-08-14"
    assert len(_pleito_auditoria(conn)) == 1


def test_correcao_troca_o_oficio_e_reaplicar_e_igual(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PRAZO_ERRADO])]))
    novo = {**PRAZO_ERRADO, "oficio": "CT-007-LT-2026", "corrige": {"oficio": "CT-001-LT-2026", "data": None}}
    cad = _cad(contratos=[_contrato(pleitos_anteriores=[novo])])
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["pleitos"]["alterados"] == ["MT-402/prazo: pleito CT-001-LT-2026: ofício CT-001-LT-2026 → CT-007-LT-2026"]
    assert [tuple(x) for x in conn.execute("SELECT numero_oficio, enviado_em FROM pleitos")] == [
        ("CT-007-LT-2026", "2026-08-14")]
    assert cadastro_aplicar.aplicar(conn, 1, cad)["pleitos"]["iguais"] == 1


def test_corrigir_pleito_que_nao_existe_ou_com_data_gravada_diferente_e_erro(conn):
    with pytest.raises(ValueError, match="pleito CT-001-LT-2026 \\(prazo\\) a corrigir não existe"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PRAZO_CERTO])]))
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PRAZO_ERRADO])]))
    errada = {**PRAZO_CERTO, "corrige": {"oficio": "CT-001-LT-2026", "data": "2026-08-15"}}
    with pytest.raises(ValueError, match="gravado com a data 14/08/2026, não 15/08/2026"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[errada])]))
    assert conn.execute("SELECT enviado_em FROM pleitos").fetchone()[0] == "2026-08-14"


def test_pleito_criado_pela_tela_nao_se_corrige_pelo_cadastro(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato()]))
    conn.execute("INSERT INTO pleitos (contrato_id, tipo, origem, dias, numero_oficio, situacao, enviado_em) "
                 "VALUES (1, 'prazo', 'sistema', 180, 'CT-001-LT-2026', 'enviado', '2026-08-14')")
    conn.commit()
    with pytest.raises(ValueError, match="pleito CT-001-LT-2026 \\(prazo\\) foi criado pela tela"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PRAZO_CERTO])]))
    assert conn.execute("SELECT enviado_em FROM pleitos").fetchone()[0] == "2026-08-14"


def test_correcao_da_data_religa_o_pleito_de_reajuste_ao_termo(conn):
    # aplicado com a data da copia (depois do termo de 15/09): o termo nao o atende
    errado = {**PLEITO_2026, "data": "2026-10-20"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP], pleitos_anteriores=[errado])]))
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] is None
    certo = {**PLEITO_2026, "corrige": {"oficio": "CT-122-LT-2026", "data": "2026-10-20"}}
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP], pleitos_anteriores=[certo])]))
    assert tuple(conn.execute("SELECT enviado_em, instrumento_chave FROM pleitos").fetchone()) == ("2026-04-23", "ap-11")
    assert "MT-402/reajuste CT-122-LT-2026: atendido por ap-11" in r["pleitos"]["alterados"]
    # e o contrario: corrigida para depois do termo, a ligacao se desfaz
    tarde = {**PLEITO_2026, "data": "2026-10-20", "corrige": {"oficio": "CT-122-LT-2026", "data": "2026-04-23"}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP], pleitos_anteriores=[tarde])]))
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] is None
    antes, depois = _pleito_auditoria(conn)[-1]
    assert antes == {"enviado_em": "2026-04-23", "instrumento_chave": "ap-11"}
    assert depois == {"enviado_em": "2026-10-20", "instrumento_chave": None}


def test_correcao_so_do_oficio_mantem_o_termo_que_atende_o_pleito(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP], pleitos_anteriores=[PLEITO_2026])]))
    novo = {**PLEITO_2026, "oficio": "CT-123-LT-2026", "corrige": {"oficio": "CT-122-LT-2026", "data": None}}
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP], pleitos_anteriores=[novo])]))
    assert tuple(conn.execute("SELECT numero_oficio, instrumento_chave FROM pleitos").fetchone()) == ("CT-123-LT-2026", "ap-11")
    assert r["pleitos"]["alterados"] == ["MT-402/reajuste: pleito CT-122-LT-2026: ofício CT-122-LT-2026 → CT-123-LT-2026"]
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cadastro.pleito_atendido'").fetchone()[0] == 1


def test_numero_antigo_usado_depois_pela_tela_nao_trava_a_reaplicacao(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PRAZO_ERRADO])]))
    novo = {**PRAZO_ERRADO, "oficio": "CT-007-LT-2026", "corrige": {"oficio": "CT-001-LT-2026", "data": None}}
    cad = _cad(contratos=[_contrato(pleitos_anteriores=[novo])])
    cadastro_aplicar.aplicar(conn, 1, cad)
    conn.execute("INSERT INTO pleitos (contrato_id, tipo, origem, dias, numero_oficio, situacao, enviado_em) "
                 "VALUES (1, 'prazo', 'sistema', 90, 'CT-001-LT-2026', 'enviado', '2026-10-01')")
    conn.commit()
    assert cadastro_aplicar.aplicar(conn, 1, cad)["pleitos"]["iguais"] == 1


def test_pleito_corrigido_escrito_de_outro_jeito_na_lista_e_erro(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PRAZO_ERRADO])]))
    velho = {**PRAZO_ERRADO, "oficio": "CT/001/LT/2026"}
    novo = {**PRAZO_ERRADO, "oficio": "CT-007-LT-2026", "corrige": {"oficio": "CT-001-LT-2026", "data": None}}
    with pytest.raises(ValueError, match="CT-001-LT-2026 \\(prazo\\) é corrigido por outro item"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[novo, velho])]))




# --- issue #390: o aditivo de valor de natureza reajuste (SES) atende o pleito como o apostilamento ---

TA_REAJ = {**AD_VALOR, "chave": "ta-08", "numero": "019/2024/01/08", "data": "2026-07-30",
           "delta_valor_centavos": 100_01, "natureza": "reajuste"}


def test_pleito_enviado_antes_do_aditivo_de_reajuste_fica_ligado_a_ele(conn):
    cad = _cad(contratos=[_contrato(instrumentos=[TA_REAJ], pleitos_anteriores=[PLEITO_2026])])
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] == "ta-08"
    assert r["pleitos"]["alterados"] == ["MT-402/reajuste CT-122-LT-2026: atendido por ta-08"]
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cadastro.pleito_atendido'").fetchone()[0] == 1
    k = reajuste_mod.ciclos(conn, 1, __import__("datetime").date(2026, 8, 10))[0]
    assert (k["ciclo"], k["situacao"], k["apostilamento"]["numero"]) == (2026, "apostilado", "019/2024/01/08")
    # reaplicar nao religa nem audita de novo
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["pleitos"]["alterados"] == []
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cadastro.pleito_atendido'").fetchone()[0] == 1


def test_aditivo_de_execucao_nao_atende_pleito_e_o_de_reajuste_nao_pega_o_enviado_depois(conn):
    execucao = {**TA_REAJ, "chave": "ta-07", "natureza": "execucao"}
    depois = {**PLEITO_2026, "oficio": "CT-200-LT-2026", "data": "2026-08-05"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[execucao],
                                                                pleitos_anteriores=[PLEITO_2026])]))
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] is None
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[execucao, TA_REAJ],
                                                                pleitos_anteriores=[PLEITO_2026, depois])]))
    ligados = dict(conn.execute("SELECT numero_oficio, instrumento_chave FROM pleitos").fetchall())
    assert ligados == {"CT-122-LT-2026": "ta-08", "CT-200-LT-2026": None}


def test_ciclo_declarado_no_aditivo_liga_o_pleito_desse_ciclo_e_nao_o_do_ciclo_da_data(conn):
    # revisor (PR #407): o termo do reajuste de 2025 assinado depois do aniversario de 2026, com o pleito de 2026 ja'
    # enviado: o `ciclo` do cadastro liga o pleito de 2025; o de 2026 segue esperando (o aviso dele nao some)
    pleito_2025 = {**PLEITO_2026, "oficio": "CT-90-LT-2025", "data": "2025-04-20", "ciclo": 2025}
    tardio = {**TA_REAJ, "dados": {"ciclo": 2025}}
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[tardio],
                                                                    pleitos_anteriores=[pleito_2025, PLEITO_2026])]))
    ligados = dict(conn.execute("SELECT numero_oficio, instrumento_chave FROM pleitos").fetchall())
    assert ligados == {"CT-090-LT-2025": "ta-08", "CT-122-LT-2026": None}
    assert r["pleitos"]["alterados"] == ["MT-402/reajuste CT-090-LT-2025: atendido por ta-08"]
    k = reajuste_mod.ciclos(conn, 1, __import__("datetime").date(2026, 8, 10))[0]
    assert (k["ciclo"], k["situacao"]) == (2026, "apostilamento_pendente")


PLEITO_2025 = {**PLEITO_2026, "oficio": "CT-90-LT-2025", "data": "2025-04-20", "ciclo": 2025}


def _ta(conn):
    return tuple(conn.execute("SELECT data_base_mes, ciclo_reajuste FROM aditivos WHERE chave_cadastro='ta-08'").fetchone())


def test_ciclo_declarado_fica_guardado_e_vale_sem_pleito(conn):
    # revisor e gate Sol (rodada 2, PR #407; migracao 058): base 2023-04, termo de 2025 assinado em 30/07/2026 com
    # `ciclo: 2025`, sem pleito: o 2025 fica apostilado pelo aditivo e o 2026 continua pendente
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[{**TA_REAJ, "dados": {"ciclo": 2025}}])]))
    assert _ta(conn) == ("2023-04", 2025)
    assert reajuste_mod.apostilamento_do_ciclo(conn, 1, "2023-04", 2025, True)["chave"] == "ta-08"
    k = reajuste_mod.ciclos(conn, 1, __import__("datetime").date(2026, 8, 10))[0]
    assert (k["ciclo"], k["situacao"]) == (2026, "pleito_pendente")


def test_reaplicar_com_ciclo_declarado_move_a_ligacao_para_o_pleito_desse_ciclo(conn):
    # gate Sol (rodada 2): a primeira aplicacao, sem `ciclo`, liga o pleito de 2026 pela data; a segunda, com
    # `ciclo: 2025`, tira a ligacao do de 2026 e liga o de 2025, auditado
    pleitos = [PLEITO_2025, PLEITO_2026]
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[TA_REAJ], pleitos_anteriores=pleitos)]))
    assert dict(conn.execute("SELECT numero_oficio, instrumento_chave FROM pleitos").fetchall()) == \
        {"CT-090-LT-2025": None, "CT-122-LT-2026": "ta-08"}
    assert _ta(conn) == ("2023-04", None)
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[{**TA_REAJ, "dados": {"ciclo": 2025}}],
                                                                    pleitos_anteriores=pleitos)]))
    assert dict(conn.execute("SELECT numero_oficio, instrumento_chave FROM pleitos").fetchall()) == \
        {"CT-090-LT-2025": "ta-08", "CT-122-LT-2026": None}
    assert _ta(conn) == ("2023-04", 2025)
    assert r["pleitos"]["alterados"] == ["MT-402/reajuste CT-122-LT-2026: sem termo (ta-08 atende o ciclo 2025)",
                                         "MT-402/reajuste CT-090-LT-2025: atendido por ta-08"]
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cadastro.pleito_atendido'").fetchone()[0] == 3
    k = reajuste_mod.ciclos(conn, 1, __import__("datetime").date(2026, 8, 10))[0]
    assert (k["ciclo"], k["situacao"]) == (2026, "apostilamento_pendente")
    # reaplicar de novo nao mexe; trocar o ciclo ja' guardado e' instrumento novo
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[{**TA_REAJ, "dados": {"ciclo": 2025}}],
                                                                    pleitos_anteriores=pleitos)]))
    assert r["pleitos"]["alterados"] == []
    with pytest.raises(ValueError, match="ciclo_reajuste"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[{**TA_REAJ, "dados": {"ciclo": 2024}}],
                                                                    pleitos_anteriores=pleitos)]))


def test_reaplicar_com_ciclo_sem_pleito_tira_a_ligacao_com_aviso(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[TA_REAJ], pleitos_anteriores=[PLEITO_2026])]))
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] == "ta-08"
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[{**TA_REAJ, "dados": {"ciclo": 2025}}],
                                                                    pleitos_anteriores=[PLEITO_2026])]))
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] is None
    assert any("MT-402/ta-08" in a and "ciclo 2025" in a and "CT-122-LT-2026 saiu" in a for a in r["avisos"]), r["avisos"]


def test_aditivo_aplicado_antes_da_058_recebe_a_base_unica_no_proximo_aplicar(conn):
    cad = _cad(contratos=[_contrato(instrumentos=[TA_REAJ])])
    cadastro_aplicar.aplicar(conn, 1, cad)
    conn.execute("UPDATE aditivos SET data_base_mes=NULL WHERE chave_cadastro='ta-08'"); conn.commit()
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert _ta(conn) == ("2023-04", None)
    assert r["instrumentos"]["alterados"] == ["MT-402/ta-08"]
    # o contrato ganha outra base, sem declaracao: o aditivo segue na que guardou
    cad2 = _cad(contratos=[_contrato(instrumentos=[TA_REAJ], datas_base=[{"mes": "2023-04", "indice": "setorial"},
                                                                         {"mes": "2023-06", "indice": "SICRO"}])])
    cadastro_aplicar.aplicar(conn, 1, cad2)
    assert _ta(conn) == ("2023-04", None)


MISTO = {**TA_REAJ, "tipo": "aditivo_misto", "nova_execucao_fim": "2027-06-30"}


def test_misto_de_reajuste_com_prazo_novo_que_atende_o_pleito_deixa_o_ciclo_apostilado(conn):
    # gate Sol (rodada 2): o termo ligado concede o reajuste do ciclo; a prorrogacao nao reabre este ciclo
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[MISTO], pleitos_anteriores=[PLEITO_2026])]))
    assert conn.execute("SELECT instrumento_chave FROM pleitos").fetchone()[0] == "ta-08"
    k = reajuste_mod.ciclos(conn, 1, __import__("datetime").date(2026, 8, 10))[0]
    assert (k["ciclo"], k["situacao"], k["aditivo"]) == (2026, "apostilado", None)


def test_misto_de_reajuste_de_outro_ciclo_com_prazo_novo_pede_reemissao_do_pleito_ja_enviado(conn):
    # o termo de 2025 com prorrogacao, assinado depois do pleito de 2026: o 2025 fica apostilado e o 2026, cujo
    # cronograma saiu antes do prazo novo, vai para reemitir
    misto = {**MISTO, "dados": {"ciclo": 2025}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[misto],
                                                                pleitos_anteriores=[PLEITO_2025, PLEITO_2026])]))
    assert dict(conn.execute("SELECT numero_oficio, instrumento_chave FROM pleitos").fetchall()) == \
        {"CT-090-LT-2025": "ta-08", "CT-122-LT-2026": None}
    k = reajuste_mod.ciclos(conn, 1, __import__("datetime").date(2026, 8, 10))[0]
    assert (k["ciclo"], k["situacao"], k["aditivo"]["chave_cadastro"]) == (2026, "reemitir", "ta-08")
    assert reajuste_mod.apostilamento_do_ciclo(conn, 1, "2023-04", 2025, True)["chave"] == "ta-08"


# --- issue #409: aditivo corrigido por outro (`corrige`, migracao 059) sai do motor e a ligacao passa adiante ---

TA_CORR = {**TA_REAJ, "chave": "ta-09", "numero": "019/2024/01/09", "data": "2026-08-15", "corrige": "ta-08"}


def _trilha_pleitos(conn):
    return [(json.loads(a), json.loads(d)) for a, d in conn.execute(
        "SELECT antes, depois FROM audit_log WHERE acao='cadastro.pleito_atendido' ORDER BY id")]


def test_aditivo_que_corrige_o_de_reajuste_para_outro_ciclo_move_a_ligacao_com_auditoria(conn):
    # gate Sol (rodada 2, PR #407): o TA1 (ta-08) atendia o pleito de 2026; o TA2 (ta-09) o corrige para o ciclo
    # 2025. So' o 2025 fica apostilado, o 2026 volta a esperar o termo, e a auditoria registra as duas pontas
    pleitos = [PLEITO_2025, PLEITO_2026]
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[TA_REAJ], pleitos_anteriores=pleitos)]))
    assert _ligacoes(conn) == {"CT-090-LT-2025": None, "CT-122-LT-2026": "ta-08"}
    cad = _cad(contratos=[_contrato(instrumentos=[TA_REAJ, {**TA_CORR, "dados": {"ciclo": 2025}}],
                                    pleitos_anteriores=pleitos)])
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert _ligacoes(conn) == {"CT-090-LT-2025": "ta-09", "CT-122-LT-2026": None}
    assert r["pleitos"]["alterados"] == [
        "MT-402/reajuste CT-122-LT-2026: sem termo (ta-09 corrige ta-08 para o ciclo 2025)",
        "MT-402/reajuste CT-090-LT-2025: atendido por ta-09"]
    assert _trilha_pleitos(conn) == [({"instrumento_chave": None}, {"instrumento_chave": "ta-08"}),
                                     ({"instrumento_chave": "ta-08"}, {"instrumento_chave": None}),
                                     ({"instrumento_chave": None}, {"instrumento_chave": "ta-09"})]
    assert conn.execute("SELECT corrige_chave FROM aditivos WHERE chave_cadastro='ta-09'").fetchone()[0] == "ta-08"
    assert reajuste_mod.apostilamento_do_ciclo(conn, 1, "2023-04", 2025, True)["chave"] == "ta-09"
    assert reajuste_mod.apostilamento_do_ciclo(conn, 1, "2023-04", 2026, True) is None
    assert [a["chave"] for a in reajuste_mod.aditivos_de_reajuste(conn, 1)] == ["ta-09"]
    k = reajuste_mod.ciclos(conn, 1, __import__("datetime").date(2026, 8, 20))[0]
    assert (k["ciclo"], k["situacao"], k["apostilamento"]) == (2026, "apostilamento_pendente", None)
    # reaplicar e' igual: nada se religa nem se audita de novo
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["pleitos"]["alterados"] == [] and r["instrumentos"]["alterados"] == []
    assert len(_trilha_pleitos(conn)) == 3


def test_correcao_do_aditivo_no_mesmo_ciclo_herda_o_pleito_do_corrigido(conn):
    # como no apostilamento (PR #411): a correcao atende o pleito que o corrigido atendeu, e nao a reemissao enviada
    # entre as datas dos dois (que segue esperando o termo dela)
    reemissao = {**PLEITO_2026, "oficio": "CT-130-LT-2026", "data": "2026-08-01"}
    pleitos = [PLEITO_2026, reemissao]
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[TA_REAJ], pleitos_anteriores=pleitos)]))
    assert _ligacoes(conn) == {"CT-122-LT-2026": "ta-08", "CT-130-LT-2026": None}
    cad = _cad(contratos=[_contrato(instrumentos=[TA_REAJ, TA_CORR], pleitos_anteriores=pleitos)])
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert _ligacoes(conn) == {"CT-122-LT-2026": "ta-09", "CT-130-LT-2026": None}
    assert r["pleitos"]["alterados"] == ["MT-402/reajuste CT-122-LT-2026: atendido por ta-09 (corrige ta-08)"]
    assert _trilha_pleitos(conn)[-1] == ({"instrumento_chave": "ta-08"}, {"instrumento_chave": "ta-09"})
    assert [a["chave"] for a in reajuste_mod.aditivos_de_reajuste(conn, 1)] == ["ta-09"]
    assert cadastro_aplicar.aplicar(conn, 1, cad)["pleitos"]["alterados"] == []


def test_correcao_do_aditivo_aplicada_do_zero_atende_o_pleito_do_corrigido(conn):
    # banco montado do zero com os dois aditivos: o resultado e' o mesmo da aplicacao em duas vezes
    reemissao = {**PLEITO_2026, "oficio": "CT-130-LT-2026", "data": "2026-08-01"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[TA_REAJ, TA_CORR],
                                                                pleitos_anteriores=[PLEITO_2026, reemissao])]))
    assert _ligacoes(conn) == {"CT-122-LT-2026": "ta-09", "CT-130-LT-2026": None}


def test_corrige_do_aditivo_fica_gravado_e_trava(conn):
    # como a natureza: o aditivo aplicado sem `corrige` aceita o primeiro, auditado; depois trocar ou tirar e' erro
    def cad(corrige):
        return _cad(contratos=[_contrato(instrumentos=[TA_REAJ, {**TA_CORR, "corrige": corrige}])])
    cadastro_aplicar.aplicar(conn, 1, cad(None))
    assert [a["chave"] for a in reajuste_mod.aditivos_de_reajuste(conn, 1)] == ["ta-08", "ta-09"]
    r = cadastro_aplicar.aplicar(conn, 1, cad("ta-08"))
    assert r["instrumentos"]["alterados"] == ["MT-402/ta-09"]
    antes, depois = conn.execute("SELECT antes, depois FROM audit_log WHERE acao='cadastro.instrumento' "
                                 "ORDER BY id DESC LIMIT 1").fetchone()
    assert (json.loads(antes), json.loads(depois)) == ({"corrige_chave": None, "observacao": None},
                                                       {"corrige_chave": "ta-08", "observacao": "Corrige ta-08"})
    assert [a["chave"] for a in reajuste_mod.aditivos_de_reajuste(conn, 1)] == ["ta-09"]
    assert cadastro_aplicar.aplicar(conn, 1, cad("ta-08"))["instrumentos"]["alterados"] == []
    with pytest.raises(ValueError, match="corrige: 'ta-08' → None"):
        cadastro_aplicar.aplicar(conn, 1, cad(None))
    with pytest.raises(ValueError, match="corrige: 'ta-08' → 'ta-07'"):
        cadastro_aplicar.aplicar(conn, 1, cad("ta-07"))


def test_aditivo_de_prazo_que_corrige_o_de_reajuste_nao_o_tira_nem_trava(conn):
    # /code-review: o aditivo de prazo corrige outra coisa no de reajuste (o prazo); o reajuste segue valendo, a
    # ligacao fica, e o `corrige` dele nao trava o aplicar (o motor nao o le)
    prazo = {**AD_VALOR, "chave": "ta-10", "tipo": "aditivo_prazo", "numero": "019/2024/01/10", "data": "2026-08-20",
             "delta_valor_centavos": 0, "nova_execucao_fim": "2027-06-30", "natureza": None, "corrige": "ta-08"}
    cad = _cad(contratos=[_contrato(instrumentos=[TA_REAJ, prazo], pleitos_anteriores=[PLEITO_2026])])
    cadastro_aplicar.aplicar(conn, 1, cad)
    assert _ligacoes(conn) == {"CT-122-LT-2026": "ta-08"}
    assert [a["chave"] for a in reajuste_mod.aditivos_de_reajuste(conn, 1)] == ["ta-08"]
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[TA_REAJ, {**prazo, "corrige": None}],
                                                                    pleitos_anteriores=[PLEITO_2026])]))
    assert r["instrumentos"]["alterados"] == [] and r["pleitos"]["alterados"] == []


def test_correcao_sem_base_determinavel_tira_a_ligacao_do_corrigido_com_aviso(conn):
    # /code-review: o contrato ganhou a segunda data-base e a correcao nao declara a dela; o corrigido deixa de valer
    # e o pleito dele volta a esperar o termo, com aviso (nada some em silencio)
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[TA_REAJ], pleitos_anteriores=[PLEITO_2026])]))
    duas = [{"mes": "2023-04", "indice": "setorial"}, {"mes": "2023-06", "indice": "SICRO"}]
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[TA_REAJ, TA_CORR], datas_base=duas,
                                                                    pleitos_anteriores=[PLEITO_2026])]))
    assert _ligacoes(conn) == {"CT-122-LT-2026": None}
    assert r["pleitos"]["alterados"] == ["MT-402/reajuste CT-122-LT-2026: sem termo (ta-09 corrige ta-08)"]
    assert any("MT-402/ta-09" in a and "CT-122-LT-2026" in a and "ligação saiu" in a for a in r["avisos"]), r["avisos"]
    assert _trilha_pleitos(conn)[-1] == ({"instrumento_chave": "ta-08"}, {"instrumento_chave": None})


@pytest.mark.parametrize("com_correcao", [False, True])
def test_pleito_do_ciclo_cadastrado_tarde_e_o_atendido_com_ou_sem_correcao(conn, com_correcao):
    # gate Sol (rodada 1, PR #433), refutado com este teste: o CT-125, enviado depois do CT-122 e antes da assinatura
    # do TA1, entra no cadastro depois. Sem correcao, o TA1 passa a atende-lo (a ligacao se reconfere pela data a cada
    # aplicar, rodada 2 da PR #407); com o TA2 corrigindo o TA1 no mesmo ciclo, o TA2 atende o mesmo pleito, como o
    # termo de correcao do apostilamento (#414). Herdar o CT-122 daria resultados diferentes nos dois casos
    tarde = {**PLEITO_2026, "oficio": "CT-125-LT-2026", "data": "2026-06-10"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[TA_REAJ], pleitos_anteriores=[PLEITO_2026])]))
    assert _ligacoes(conn) == {"CT-122-LT-2026": "ta-08"}
    instrumentos = [TA_REAJ, TA_CORR] if com_correcao else [TA_REAJ]
    cad = _cad(contratos=[_contrato(instrumentos=instrumentos, pleitos_anteriores=[PLEITO_2026, tarde])])
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    termo = "ta-09" if com_correcao else "ta-08"
    assert _ligacoes(conn) == {"CT-122-LT-2026": None, "CT-125-LT-2026": termo}
    saiu = ("sem termo (ta-09 corrige ta-08 e atende o CT-125-LT-2026, o último enviado até 30/07/2026)"
            if com_correcao else "sem termo (ta-08 atende o ciclo 2026)")
    assert r["pleitos"]["alterados"] == [f"MT-402/reajuste CT-122-LT-2026: {saiu}",
                                         f"MT-402/reajuste CT-125-LT-2026: atendido por {termo}"]
    assert not any("ligação saiu" in a for a in r["avisos"]), r["avisos"]
    k = reajuste_mod.ciclos(conn, 1, __import__("datetime").date(2026, 8, 20))[0]
    assert (k["ciclo"], k["situacao"], k["apostilamento"]["chave"]) == (2026, "apostilado", termo)
    assert cadastro_aplicar.aplicar(conn, 1, cad)["pleitos"]["alterados"] == []


@pytest.mark.parametrize("ciclo_do_aditivo", [None, 2025])
def test_aditivo_que_corrige_um_apostilamento_nao_mexe_no_pleito_dele(conn, ciclo_do_aditivo):
    # revisor (rodada 1, PR #433): `corrige` entre tabelas nao tem efeito. O ap-09 (ciclo 2025) segue com o pleito de
    # 2025, de outro ciclo (o ta-08 cai em 2026 pela data) ou do mesmo (`ciclo: 2025`), e reaplicar e' "igual"
    ap = {**AP_REAJ, "dados": {"data_base": "2023-04", "ciclo": 2025}}
    ta = {**TA_REAJ, "corrige": "ap-09", "dados": {"ciclo": ciclo_do_aditivo} if ciclo_do_aditivo else {}}
    cad = _cad(contratos=[_contrato(instrumentos=[ap, ta], pleitos_anteriores=[PLEITO_2025, PLEITO_2026])])
    cadastro_aplicar.aplicar(conn, 1, cad)
    assert _ligacoes(conn)["CT-090-LT-2025"] == "ap-09"
    assert reajuste_mod.apostilamento_do_ciclo(conn, 1, "2023-04", 2025, True)["chave"] == "ap-09"
    auditorias = len(_trilha_pleitos(conn))
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["pleitos"]["alterados"] == [] and _ligacoes(conn)["CT-090-LT-2025"] == "ap-09"
    assert len(_trilha_pleitos(conn)) == auditorias

# --- issue #398: pedido de aditivo de valor (RPFO) enviado antes do sistema ----------------------------------

from app import prazos as prazos_mod

PEDIDO_VALOR = {"tipo": "valor", "oficio": "CT-001-LT-2026", "data": "2026-03-27", "data_base": None, "ciclo": None,
                "dias": None, "valor_centavos": 100000001, "objeto": "1ª RPFO"}


def test_pleito_de_valor_e_gravado_com_o_valor_e_o_objeto_e_nao_duplica(conn):
    cad = _cad(contratos=[_contrato(pleitos_anteriores=[PEDIDO_VALOR])])
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["pleitos"]["criados"] == ["MT-402/valor CT-001-LT-2026"]
    linha = conn.execute("SELECT tipo, origem, situacao, enviado_em, numero_oficio, valor_centavos, objeto "
                         "FROM pleitos").fetchone()
    assert tuple(linha) == ("valor", "cadastro", "enviado", "2026-03-27", "CT-001-LT-2026", 100000001, "1ª RPFO")
    assert cadastro_aplicar.aplicar(conn, 1, cad)["pleitos"] == {"criados": [], "alterados": [], "iguais": 1}


def test_pedido_de_valor_sem_aditivo_depois_fica_sem_resposta(conn):
    # o aditivo de valor assinado ANTES do pedido nao o atende; o de prazo depois dele tambem nao
    antes = {**AD_VALOR, "data": "2026-01-15"}
    prazo = {**AP_PRAZO, "data": "2026-04-10"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[antes, prazo],
                                                                pleitos_anteriores=[PEDIDO_VALOR])]))
    [p] = prazos_mod.pedidos_de_valor(conn, 1)
    assert (p["numero_oficio"], p["enviado_em"], p["valor_centavos"], p["objeto"]) == (
        "CT-001-LT-2026", "2026-03-27", 100000001, "1ª RPFO")
    assert p["atendido_por"] is None


def test_pedido_de_valor_e_ligado_ao_aditivo_de_valor_assinado_depois(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PEDIDO_VALOR])]))
    assert prazos_mod.pedidos_de_valor(conn, 1)[0]["atendido_por"] is None
    # o aditivo entra numa carga posterior do cadastro: a ligacao e' pela data, na leitura
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AD_VALOR],
                                                                pleitos_anteriores=[PEDIDO_VALOR])]))
    [p] = prazos_mod.pedidos_de_valor(conn, 1)
    assert p["atendido_por"] == {"numero": "019/2024/01/01", "data_assinatura": "2026-06-30", "rotulo": "1º TA"}


def test_pedido_de_valor_e_atendido_pelo_primeiro_aditivo_de_valor_depois_dele(conn):
    ta2 = {**AD_VALOR, "chave": "ta-02", "data": "2026-09-30", "numero": "019/2024/01/02"}
    segundo = {**PEDIDO_VALOR, "oficio": "CT-050-LT-2026", "data": "2026-07-10", "objeto": "2ª RPFO"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AD_VALOR, ta2],
                                                                pleitos_anteriores=[PEDIDO_VALOR, segundo])]))
    por_oficio = {p["numero_oficio"]: p["atendido_por"]["rotulo"] for p in prazos_mod.pedidos_de_valor(conn, 1)}
    assert por_oficio == {"CT-001-LT-2026": "1º TA", "CT-050-LT-2026": "2º TA"}


def test_pleito_de_valor_mudado_no_yaml_fica_como_gravado_e_vira_aviso(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PEDIDO_VALOR])]))
    mudado = {**PEDIDO_VALOR, "valor_centavos": 120000000, "objeto": "1ª RPFO revista"}
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[mudado])]))
    assert r["pleitos"]["iguais"] == 1
    assert "MT-402/valor CT-001-LT-2026: valor, objeto no YAML difere do gravado; o gravado fica " \
           "(para corrigir a data ou o ofício, use corrige: {oficio, data})" in r["avisos"]
    assert conn.execute("SELECT valor_centavos FROM pleitos").fetchone()[0] == 100000001
    # igual de verdade: sem aviso
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PEDIDO_VALOR])]))
    assert not any("difere do gravado" in a for a in r["avisos"])


def test_pleito_de_prazo_com_outra_data_no_yaml_vira_aviso(conn):
    prazo = {"tipo": "prazo", "oficio": "331", "data": "2025-11-10", "data_base": None, "ciclo": None, "dias": 120}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[prazo])]))
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[{**prazo, "data": "2025-08-10"}])]))
    assert any(a.startswith("MT-402/prazo CT-331-LT-2025: data no YAML difere do gravado") for a in r["avisos"])


def test_supressao_e_aditivo_de_reajuste_nao_atendem_o_pedido_de_valor(conn):
    supressao = {**AD_VALOR, "delta_valor_centavos": -1000001}
    de_reajuste = {**AD_VALOR, "chave": "ta-02", "data": "2026-07-30", "numero": "019/2024/01/02",
                   "natureza": "reajuste"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[supressao, de_reajuste],
                                                                pleitos_anteriores=[PEDIDO_VALOR])]))
    assert prazos_mod.pedidos_de_valor(conn, 1)[0]["atendido_por"] is None


def test_indice_reajuste_vem_da_data_base_unica_e_reaplicar_e_igual(conn):
    # issue #397: a coluna do contrato e' derivada de contrato_datas_base, nunca a tabela de precos
    conn.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos, indice_reajuste) "
                 "VALUES ('SINFRA','019/2024/00/00-SINFRA','MT-402',1512720000,'SINAPI')")
    conn.commit()
    c = _contrato(datas_base=[{"mes": "2023-04", "indice": "INCC-DI/FGV"}])
    ensaio = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[c]), ensaio=True)
    assert ensaio["contratos"]["alterados"] == ["MT-402"]
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[c]))
    assert conn.execute("SELECT indice_reajuste FROM contratos").fetchone()[0] == "INCC-DI/FGV"
    linha = conn.execute("SELECT * FROM audit_log WHERE acao='cadastro.contrato' ORDER BY id DESC LIMIT 1").fetchone()
    assert "SINAPI" in json.dumps(dict(linha)) and "INCC-DI/FGV" in json.dumps(dict(linha))
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[c]))
    assert r["contratos"] == {"criados": [], "alterados": [], "iguais": 1}


def test_indice_reajuste_com_duas_bases_traz_as_duas_com_aplica_a(conn):
    bases = [{"mes": "2022-03", "indice": "FGV/DNIT", "aplica_a": "itens SICRO"},
             {"mes": "2022-01", "indice": "INCC-DI", "aplica_a": "itens SINAPI"}]
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(datas_base=bases)]))
    assert conn.execute("SELECT indice_reajuste FROM contratos").fetchone()[0] == \
        "2022-01: INCC-DI (itens SINAPI); 2022-03: FGV/DNIT (itens SICRO)"


# --- PR #411, rodada 1: revisor-adversarial e gate Sol ---------------------------------------------------------

def _ligacoes(conn):
    return dict(conn.execute("SELECT numero_oficio, instrumento_chave FROM pleitos ORDER BY id").fetchall())


def test_correcao_da_data_reavalia_o_termo_ja_ligado_a_outro_pleito_do_ciclo(conn):
    # ap-11 (15/09) atende o CT-120 (01/03); o CT-122 entrou com a data da copia (20/10), depois do termo
    ct120 = {**PLEITO_2026, "oficio": "CT-120-LT-2026", "data": "2026-03-01"}
    errado = {**PLEITO_2026, "data": "2026-10-20"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[AP_COMP],
                                                                pleitos_anteriores=[ct120, errado])]))
    assert _ligacoes(conn) == {"CT-120-LT-2026": "ap-11", "CT-122-LT-2026": None}
    certo = {**PLEITO_2026, "corrige": {"oficio": "CT-122-LT-2026", "data": "2026-10-20"}}
    cad = _cad(contratos=[_contrato(instrumentos=[AP_COMP], pleitos_anteriores=[ct120, certo])])
    cadastro_aplicar.aplicar(conn, 1, cad)
    # o mesmo estado da aplicacao do zero: o termo atende o ultimo pleito enviado ate' a data dele
    assert _ligacoes(conn) == {"CT-120-LT-2026": None, "CT-122-LT-2026": "ap-11"}
    assert reajuste_mod.apostilamento_do_ciclo(conn, 1, "2023-04", 2026, True) is not None
    desligado = conn.execute("SELECT antes, depois FROM audit_log WHERE acao='cadastro.pleito_atendido' "
                             "AND entidade_id=(SELECT id FROM pleitos WHERE numero_oficio='CT-120-LT-2026') "
                             "ORDER BY id DESC LIMIT 1").fetchone()
    assert json.loads(desligado[0]) == {"instrumento_chave": "ap-11"} and json.loads(desligado[1]) == {"instrumento_chave": None}
    assert cadastro_aplicar.aplicar(conn, 1, cad)["pleitos"]["iguais"] == 2
    assert _ligacoes(conn) == {"CT-120-LT-2026": None, "CT-122-LT-2026": "ap-11"}


def test_corrige_sem_ano_nem_data_nao_escolhe_entre_dois_anos(conn):
    de_2025 = {**PRAZO_ERRADO, "oficio": "CT-001-LT-2025", "data": "2025-12-20"}
    de_2026 = {**PRAZO_ERRADO, "oficio": "CT-001-LT-2026", "data": "2026-02-01"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[de_2025, de_2026])]))
    novo = {**de_2025, "data": "2026-01-05", "corrige": {"oficio": "1", "data": None}}
    with pytest.raises(ValueError, match="há mais de um pleito CT-001-LT-<ano> \\(prazo\\)"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[novo, de_2026])]))
    assert [tuple(r) for r in conn.execute("SELECT numero_oficio, enviado_em FROM pleitos ORDER BY id")] == [
        ("CT-001-LT-2025", "2025-12-20"), ("CT-001-LT-2026", "2026-02-01")]


def test_corrige_sem_ano_acha_o_unico_gravado_mesmo_de_outro_ano(conn):
    de_2025 = {**PRAZO_ERRADO, "oficio": "CT-001-LT-2025", "data": "2025-12-20"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[de_2025])]))
    novo = {**de_2025, "data": "2026-01-05", "corrige": {"oficio": "1", "data": None}}
    cad = _cad(contratos=[_contrato(pleitos_anteriores=[novo])])
    cadastro_aplicar.aplicar(conn, 1, cad)
    assert [tuple(r) for r in conn.execute("SELECT numero_oficio, enviado_em FROM pleitos")] == [
        ("CT-001-LT-2025", "2026-01-05")]
    assert cadastro_aplicar.aplicar(conn, 1, cad)["pleitos"]["iguais"] == 1


def test_corrige_avisa_dias_diferente_do_gravado_e_recusa_ciclo_diferente(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PRAZO_ERRADO, PLEITO_2026])]))
    r = cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[
        {**PRAZO_CERTO, "dias": 120}, PLEITO_2026])]))
    assert "MT-402/prazo CT-001-LT-2026: dias no YAML difere do gravado; o gravado fica " \
           "(corrige troca só a data e o ofício)" in r["avisos"]
    assert conn.execute("SELECT dias FROM pleitos WHERE tipo='prazo'").fetchone()[0] == 180
    outro_ciclo = {**PLEITO_2026, "ciclo": 2025, "data": "2026-04-20", "corrige": {"oficio": "CT-122-LT-2026", "data": None}}
    with pytest.raises(ValueError, match="gravado no ciclo 2026, não 2025"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PRAZO_CERTO, outro_ciclo])]))


def test_corrige_com_data_antiga_que_nao_bate_com_o_banco_nao_vira_igual(conn):
    # o banco ja' esta' em 06/05 sem ter passado por esta correcao: a data antiga dita (14/08) nao tem prova
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[{**PRAZO_ERRADO, "data": "2026-05-06"}])]))
    with pytest.raises(ValueError, match="gravado com a data 06/05/2026, não 14/08/2026"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[PRAZO_CERTO])]))


def test_correcao_de_pedido_de_valor(conn):
    errado = {**PEDIDO_VALOR, "data": "2026-06-27"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[errado])]))
    certo = {**PEDIDO_VALOR, "corrige": {"oficio": "CT-001-LT-2026", "data": "2026-06-27"}}
    cad = _cad(contratos=[_contrato(pleitos_anteriores=[certo])])
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["pleitos"]["alterados"] == ["MT-402/valor: pleito CT-001-LT-2026: data 27/06/2026 → 27/03/2026"]
    assert not any("difere do gravado" in a for a in r["avisos"])
    assert tuple(conn.execute("SELECT enviado_em, valor_centavos, objeto FROM pleitos").fetchone()) == (
        "2026-03-27", 100000001, "1ª RPFO")
    assert cadastro_aplicar.aplicar(conn, 1, cad)["pleitos"]["iguais"] == 1


# --- PR #411, rodada 2 -------------------------------------------------------------------------------------------

T1 = {**AP_COMP, "chave": "ap-11", "data": "2026-05-01"}
T2 = {**AP_COMP, "chave": "ap-12", "numero": "019/2024/02/12", "data": "2026-07-01", "corrige": "ap-11"}


def test_correcao_da_data_mantem_a_heranca_do_termo_de_correcao(conn):
    # ap-11 (01/05) atende o CT-120 (01/04); o CT-130 (01/06) e' reemissao ainda sem termo; ap-12 corrige ap-11
    ct120 = {**PLEITO_2026, "oficio": "CT-120-LT-2026", "data": "2026-04-01"}
    ct130 = {**PLEITO_2026, "oficio": "CT-130-LT-2026", "data": "2026-06-01"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[T1], pleitos_anteriores=[ct120, ct130])]))
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[T1, T2], pleitos_anteriores=[ct120, ct130])]))
    assert _ligacoes(conn) == {"CT-120-LT-2026": "ap-12", "CT-130-LT-2026": None}
    certo = {**ct120, "data": "2026-04-02", "corrige": {"oficio": "CT-120-LT-2026", "data": "2026-04-01"}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[T1, T2], pleitos_anteriores=[certo, ct130])]))
    assert _ligacoes(conn) == {"CT-120-LT-2026": "ap-12", "CT-130-LT-2026": None}


def test_termo_de_correcao_aplicado_do_zero_atende_o_pleito_do_termo_original(conn):
    ct120 = {**PLEITO_2026, "oficio": "CT-120-LT-2026", "data": "2026-04-01"}
    ct130 = {**PLEITO_2026, "oficio": "CT-130-LT-2026", "data": "2026-06-01"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[T1, T2], pleitos_anteriores=[ct120, ct130])]))
    assert _ligacoes(conn) == {"CT-120-LT-2026": "ap-12", "CT-130-LT-2026": None}


def test_correcao_num_ciclo_nao_mexe_no_termo_de_outro_ciclo(conn):
    ap05 = {**AP_COMP, "chave": "ap-05", "numero": "019/2024/02/05", "data": "2025-09-01",
            "dados": {**AP_COMP["dados"], "ciclo": 2025, "periodo": None,
                      "competencias": [{"competencia": "2025-04", "valor": "1,00"}]}}
    ct050 = {**PLEITO_2026, "oficio": "CT-050-LT-2025", "data": "2025-05-01", "ciclo": 2025}
    errado = {**PLEITO_2026, "data": "2026-10-20"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[ap05, AP_COMP],
                                                                pleitos_anteriores=[ct050, errado])]))
    assert _ligacoes(conn) == {"CT-050-LT-2025": "ap-05", "CT-122-LT-2026": None}
    id050 = conn.execute("SELECT id FROM pleitos WHERE numero_oficio='CT-050-LT-2025'").fetchone()[0]
    eventos = conn.execute("SELECT COUNT(*) FROM audit_log WHERE entidade='pleito' AND entidade_id=?",
                           (str(id050),)).fetchone()[0]
    certo = {**PLEITO_2026, "corrige": {"oficio": "CT-122-LT-2026", "data": "2026-10-20"}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[ap05, AP_COMP],
                                                                pleitos_anteriores=[ct050, certo])]))
    assert _ligacoes(conn) == {"CT-050-LT-2025": "ap-05", "CT-122-LT-2026": "ap-11"}
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE entidade='pleito' AND entidade_id=?",
                        (str(id050),)).fetchone()[0] == eventos


def test_reaplicacao_da_correcao_com_ciclo_trocado_no_yaml_e_erro(conn):
    errado = {**PLEITO_2026, "data": "2026-10-20"}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[errado])]))
    certo = {**PLEITO_2026, "corrige": {"oficio": "CT-122-LT-2026", "data": "2026-10-20"}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[certo])]))
    with pytest.raises(ValueError, match="gravado no ciclo 2026, não 2025"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[{**certo, "ciclo": 2025}])]))


def test_corrige_que_aponta_para_o_estado_atual_sem_correcao_registrada_e_erro(conn):
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[{**PRAZO_ERRADO, "data": "2026-05-06"}])]))
    sobra = {**PRAZO_CERTO, "corrige": {"oficio": "CT-001-LT-2026", "data": None}}
    with pytest.raises(ValueError, match="já está com a data 06/05/2026 e esse ofício, sem correção registrada; "
                                         "tire o corrige do item"):
        cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(pleitos_anteriores=[sobra])]))


# --- issue #414: termo de correcao ligado pela regra antiga (data do proprio termo) e' religado ------------------

CT120 = {**PLEITO_2026, "oficio": "CT-120-LT-2026", "data": "2026-04-01"}     # P1: antes de ap-11 (01/05)
CT130 = {**PLEITO_2026, "oficio": "CT-130-LT-2026", "data": "2026-06-01"}     # P2: reemissao entre ap-11 e ap-12


def _atendidos(conn):
    return conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='cadastro.pleito_atendido'").fetchone()[0]


def _legado_p2_t2(conn, instrumentos=(T1, T2), pleitos=(CT120, CT130)):
    """O estado que a carga de antes da PR #411 deixou: ap-12 corrige ap-11 e foi ligado pela data dele (01/07), ao
    CT-130 (reemissao), e nao pela data de ap-11 (01/05), ao CT-120."""
    cad = _cad(contratos=[_contrato(instrumentos=list(instrumentos), pleitos_anteriores=list(pleitos))])
    cadastro_aplicar.aplicar(conn, 1, cad)
    conn.execute("UPDATE pleitos SET instrumento_chave=NULL WHERE numero_oficio='CT-120-LT-2026'")
    conn.execute("UPDATE pleitos SET instrumento_chave='ap-12' WHERE numero_oficio='CT-130-LT-2026'")
    conn.commit()
    return cad


RELIGADO = ["MT-402/reajuste CT-130-LT-2026: sem termo (ap-12 religado ao CT-120-LT-2026, o último enviado até "
            "01/05/2026)",
            "MT-402/reajuste CT-120-LT-2026: atendido por ap-12 (religado)"]


def test_termo_de_correcao_ligado_pela_regra_antiga_e_religado_com_auditoria(conn):
    import datetime
    cad = _legado_p2_t2(conn)
    assert _ligacoes(conn) == {"CT-120-LT-2026": None, "CT-130-LT-2026": "ap-12"}
    assert reajuste_mod.ciclos(conn, 1, datetime.date(2026, 10, 20))[0]["situacao"] == "apostilado"
    antes = _atendidos(conn)
    # o ensaio mostra a mudanca e nao grava
    r = cadastro_aplicar.aplicar(conn, 1, cad, ensaio=True)
    assert r["pleitos"]["alterados"] == RELIGADO
    assert _ligacoes(conn) == {"CT-120-LT-2026": None, "CT-130-LT-2026": "ap-12"}
    assert _atendidos(conn) == antes
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["pleitos"]["alterados"] == RELIGADO
    assert _ligacoes(conn) == {"CT-120-LT-2026": "ap-12", "CT-130-LT-2026": None}
    # auditoria dos dois lados: a reemissao perde o termo, o pleito do termo original o ganha
    ids = dict(conn.execute("SELECT numero_oficio, id FROM pleitos").fetchall())
    eventos = [(int(r[0]), json.loads(r[1]), json.loads(r[2])) for r in conn.execute(
        "SELECT entidade_id, antes, depois FROM audit_log WHERE acao='cadastro.pleito_atendido' ORDER BY id")][antes:]
    assert eventos == [(ids["CT-130-LT-2026"], {"instrumento_chave": "ap-12"}, {"instrumento_chave": None}),
                       (ids["CT-120-LT-2026"], {"instrumento_chave": None}, {"instrumento_chave": "ap-12"})]
    # a reemissao volta a esperar o termo dela
    assert reajuste_mod.ciclos(conn, 1, datetime.date(2026, 10, 20))[0]["situacao"] == "apostilamento_pendente"


def test_segunda_reaplicacao_do_termo_religado_e_igual_e_nao_audita(conn):
    cad = _legado_p2_t2(conn)
    cadastro_aplicar.aplicar(conn, 1, cad)
    antes = conn.execute("SELECT COUNT(*) FROM audit_log WHERE entidade='pleito'").fetchone()[0]
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["pleitos"] == {"criados": [], "alterados": [], "iguais": 2}
    assert _ligacoes(conn) == {"CT-120-LT-2026": "ap-12", "CT-130-LT-2026": None}
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE entidade='pleito'").fetchone()[0] == antes


def test_ciclo_sem_cadeia_de_correcao_nao_e_tocado_pela_religacao(conn):
    # ap-05 (ciclo 2025, sem correcao) atendeu o CT-050; o CT-060, enviado antes de ap-05, entrou depois no cadastro.
    # A ligacao do termo original fica como esta': so' o termo de correcao se reconfere
    ap05 = {**AP_COMP, "chave": "ap-05", "numero": "019/2024/02/05", "data": "2025-09-01",
            "dados": {**AP_COMP["dados"], "ciclo": 2025, "periodo": None,
                      "competencias": [{"competencia": "2025-04", "valor": "1,00"}]}}
    ct050 = {**PLEITO_2026, "oficio": "CT-050-LT-2025", "data": "2025-05-01", "ciclo": 2025}
    ct060 = {**PLEITO_2026, "oficio": "CT-060-LT-2025", "data": "2025-08-01", "ciclo": 2025}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[ap05], pleitos_anteriores=[ct050])]))
    cad = _legado_p2_t2(conn, instrumentos=(ap05, T1, T2), pleitos=(ct050, ct060, CT120, CT130))
    assert _ligacoes(conn) == {"CT-050-LT-2025": "ap-05", "CT-060-LT-2025": None,
                               "CT-120-LT-2026": None, "CT-130-LT-2026": "ap-12"}
    de_2025 = [str(i) for (i,) in conn.execute("SELECT id FROM pleitos WHERE ciclo=2025")]
    sql = f"SELECT COUNT(*) FROM audit_log WHERE entidade='pleito' AND entidade_id IN ({','.join('?' * len(de_2025))})"
    eventos = conn.execute(sql, de_2025).fetchone()[0]
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["pleitos"]["alterados"] == RELIGADO
    assert _ligacoes(conn) == {"CT-050-LT-2025": "ap-05", "CT-060-LT-2025": None,
                               "CT-120-LT-2026": "ap-12", "CT-130-LT-2026": None}
    assert conn.execute(sql, de_2025).fetchone()[0] == eventos


def test_correcao_de_correcao_que_herdou_a_ligacao_antiga_e_religada(conn):
    # ap-12 ficou ligado pela regra antiga ao CT-130; ap-13 corrige ap-12 e herda a ligacao: se reconfere do mesmo jeito
    _legado_p2_t2(conn)
    t3 = {**AP_COMP, "chave": "ap-13", "numero": "019/2024/02/13", "data": "2026-08-01", "corrige": "ap-12"}
    cad = _cad(contratos=[_contrato(instrumentos=[T1, T2, t3], pleitos_anteriores=[CT120, CT130])])
    cadastro_aplicar.aplicar(conn, 1, cad)
    assert _ligacoes(conn) == {"CT-120-LT-2026": "ap-13", "CT-130-LT-2026": None}
    antes = _atendidos(conn)
    assert cadastro_aplicar.aplicar(conn, 1, cad)["pleitos"]["alterados"] == []
    assert _atendidos(conn) == antes


def test_termo_de_correcao_sem_pleito_ate_a_data_do_original_perde_a_ligacao_antiga_com_aviso(conn):
    # sem o CT-120 no cadastro, pela data de ap-11 nao ha' pleito: a ligacao antiga ao CT-130 sai, com aviso
    cad = _legado_p2_t2(conn, pleitos=(CT130,))
    assert _ligacoes(conn) == {"CT-130-LT-2026": "ap-12"}
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert _ligacoes(conn) == {"CT-130-LT-2026": None}
    assert r["pleitos"]["alterados"] == ["MT-402/reajuste CT-130-LT-2026: sem termo (ap-12 religado: nenhum pleito do "
                                         "ciclo enviado até 01/05/2026)"]
    assert any(a.startswith("MT-402/ap-12: ") and "CT-130-LT-2026 saiu" in a for a in r["avisos"]), r["avisos"]
    antes = _atendidos(conn)
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert r["pleitos"]["alterados"] == [] and not any("MT-402/ap-12" in a for a in r["avisos"])
    assert _atendidos(conn) == antes


def test_pleito_esperado_atendido_por_outro_termo_nao_tira_a_heranca_e_avisa(conn):
    # code-review (#414): ap-11 atendeu o CT-100; o CT-120, que entrou depois, foi pego pelo aditivo ta-08. Pela data de
    # ap-11 a correcao atenderia o CT-120, que e' do aditivo: nada de adivinhar, a heranca fica e o aplicar avisa
    ct100 = {**PLEITO_2026, "oficio": "CT-100-LT-2026", "data": "2026-03-01"}
    ta = {**TA_REAJ, "data": "2026-04-15", "dados": {"ciclo": 2026}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[T1], pleitos_anteriores=[ct100])]))
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[T1, ta], pleitos_anteriores=[ct100, CT120])]))
    assert _ligacoes(conn) == {"CT-100-LT-2026": "ap-11", "CT-120-LT-2026": "ta-08"}
    cad = _cad(contratos=[_contrato(instrumentos=[T1, ta, T2], pleitos_anteriores=[ct100, CT120])])
    r = cadastro_aplicar.aplicar(conn, 1, cad)
    assert _ligacoes(conn) == {"CT-100-LT-2026": "ap-12", "CT-120-LT-2026": "ta-08"}
    assert r["pleitos"]["alterados"] == ["MT-402/reajuste CT-100-LT-2026: atendido por ap-12"]
    assert any(a.startswith("MT-402/ap-12: ") and "CT-120-LT-2026" in a and "ta-08" in a for a in r["avisos"]), r["avisos"]
    antes = _atendidos(conn)
    assert cadastro_aplicar.aplicar(conn, 1, cad)["pleitos"]["alterados"] == []
    assert _atendidos(conn) == antes


def test_correcao_da_data_de_pleito_nao_perde_a_ligacao_ao_aditivo_de_reajuste(conn):
    # comentario da #414: a correcao de data desliga os pleitos do ciclo, inclusive o ligado ao aditivo de reajuste
    # (#390); o aplicar o religa como numa aplicacao do zero
    errado = {**PLEITO_2026, "data": "2026-10-20"}        # depois do aditivo (30/07)
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[TA_REAJ],
                                                                pleitos_anteriores=[CT120, errado])]))
    assert _ligacoes(conn) == {"CT-120-LT-2026": "ta-08", "CT-122-LT-2026": None}
    # ainda depois do aditivo: o CT-120 continua atendido por ele
    tarde = {**PLEITO_2026, "data": "2026-08-15", "corrige": {"oficio": "CT-122-LT-2026", "data": "2026-10-20"}}
    cad = _cad(contratos=[_contrato(instrumentos=[TA_REAJ], pleitos_anteriores=[CT120, tarde])])
    cadastro_aplicar.aplicar(conn, 1, cad)
    assert _ligacoes(conn) == {"CT-120-LT-2026": "ta-08", "CT-122-LT-2026": None}
    antes = _atendidos(conn)
    assert cadastro_aplicar.aplicar(conn, 1, cad)["pleitos"]["alterados"] == []
    assert _atendidos(conn) == antes
    # antes do aditivo: o ultimo enviado ate' a assinatura passa a ser o atendido
    cedo = {**PLEITO_2026, "corrige": {"oficio": "CT-122-LT-2026", "data": "2026-08-15"}}
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[_contrato(instrumentos=[TA_REAJ], pleitos_anteriores=[CT120, cedo])]))
    assert _ligacoes(conn) == {"CT-120-LT-2026": None, "CT-122-LT-2026": "ta-08"}
