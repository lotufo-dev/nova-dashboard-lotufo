import datetime
import io
import json
import pathlib
import zipfile

import pytest

from app import auth, certidoes, db, documentos, leitura_certidao, tempo

D = datetime.date
FIX = pathlib.Path(__file__).parent / "fixtures" / "certidoes"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "admin")
    monkeypatch.setattr(tempo, "hoje_local", lambda: D(2026, 9, 23))
    yield c
    c.close()


# DML cru SEMPRE com commit: `db.mutacao` recusa transacao aberta fora dele.
def _orgao(conn, medicao, reajuste):
    conn.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('sinfra-x','SINFRA X','sinfra',?)",
                 (json.dumps({"documentos_medicao": medicao, "documentos_reajuste": reajuste}),))
    conn.commit()
    return conn.execute("SELECT id FROM orgaos WHERE chave='sinfra-x'").fetchone()[0]


def _consorcio(conn):
    conn.execute("UPDATE entidades SET nome_curto='Lotufo' WHERE id=1")
    conn.execute("INSERT INTO entidades (id, nome, cnpj, papel, nome_curto) VALUES "
                 "(2, 'Consórcio Complexo Leblon', '31200404000152', 'consorcio', 'Complexo Leblon'), "
                 "(3, 'Rivoli', '31200606000102', 'consorciada', 'Rivoli')")
    conn.execute("INSERT INTO entidade_consorciadas VALUES (2, 1), (2, 3)")
    conn.commit()


def _contrato(conn, orgao_id, entidade_id=1, documentos_json=None):
    conn.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos, orgao_id, "
                 "entidade_id, documentos) VALUES ('SINFRA', ?, 'obra', 100, ?, ?, ?)",
                 (f"C-{orgao_id}-{entidade_id}-{documentos_json}", orgao_id, entidade_id, documentos_json))
    conn.commit()
    return conn.execute("SELECT MAX(id) FROM contratos").fetchone()[0]


def _cert(conn, ent, chave, emissao, validade):
    t = documentos.tipo_por_chave(conn, chave)
    return certidoes.registrar(conn, 1, ent, t["id"], emissao, validade, f"certidoes/{ent}{chave}.pdf",
                               "a" * 64, "upload", natureza="negativa", leitura="automatica")


def test_exigidos_consorcio_natureza_e_excecao(conn):
    _consorcio(conn)
    oid = _orgao(conn, ["federal", "fgts", "regularidade"], ["estadual"])
    cid = _contrato(conn, oid, entidade_id=2)
    ex = documentos.exigidos(conn, cid, "execucao")
    assert ex["entidades"] == [2, 1, 3]
    assert [t["chave"] for t in ex["tipos"]] == ["federal", "fgts"]
    assert ex["regularidade"] == 1                        # so' da Lotufo
    reaj = documentos.exigidos(conn, cid, "reajuste")
    assert [t["chave"] for t in reaj["tipos"]] == ["estadual"] and reaj["regularidade"] is None
    cid2 = _contrato(conn, oid, documentos_json=json.dumps({"reajuste": ["estadual", "municipal"]}))
    assert [t["chave"] for t in documentos.exigidos(conn, cid2, "reajuste")["tipos"]] == ["estadual", "municipal"]
    assert [t["chave"] for t in documentos.exigidos(conn, cid2, "projeto")["tipos"]] == ["federal", "fgts"]


def test_consorcio_com_folha_propria_manda_a_propria_regularidade(conn):
    _consorcio(conn)
    conn.execute("UPDATE entidades SET regularidade_propria=1 WHERE id=2")
    conn.commit()
    cid = _contrato(conn, _orgao(conn, ["fgts", "regularidade"], ["estadual"]), entidade_id=2)
    assert documentos.exigidos(conn, cid, "execucao")["regularidade"] == 2


def test_contrato_sem_orgao_usa_os_tipos_padrao(conn):
    cid = _contrato(conn, None)
    assert [t["chave"] for t in documentos.exigidos(conn, cid, "execucao")["tipos"]] == ["federal", "fgts", "trabalhista",
                                                                                     "estadual", "municipal"]   # 031


def test_situacao_limiar_pela_validade_da_propria_certidao(conn):
    _cert(conn, 1, "fgts", "2026-08-31", "2026-09-29")          # 29 dias de validade -> limiar 7
    _cert(conn, 1, "federal", "2026-06-24", "2026-10-05")       # longa -> limiar 15
    _cert(conn, 1, "municipal", "2026-06-24", "2026-07-24")     # vencida
    s = lambda ch: documentos.situacao(conn, 1, documentos.tipo_por_chave(conn, ch), D(2026, 9, 23))
    assert (s("fgts")["situacao"], s("fgts")["dias"]) == ("vencendo", 6)
    assert (s("federal")["situacao"], s("federal")["dias"]) == ("vencendo", 12)
    assert s("municipal")["situacao"] == "vencida"
    assert s("trabalhista")["situacao"] == "faltando"


def test_competencia_esperada_da_regularidade():
    assert documentos.competencia_esperada(D(2026, 6, 22)) == "2026-04"
    assert documentos.competencia_esperada(D(2026, 8, 3)) == "2026-05"     # antes do dia 10: mes - 3
    assert documentos.competencia_esperada(D(2026, 9, 16)) == "2026-07"
    assert documentos.competencia_esperada(D(2026, 1, 12)) == "2025-11"


def test_regularidade_vale_a_maior_competencia_e_repetida_e_recusada(conn):
    documentos.registrar_regularidade(conn, 1, 1, "2026-06", "regularidades/a.pdf", "a" * 64, 10, "062026 - LOTUFO.pdf")
    documentos.registrar_regularidade(conn, 1, 1, "2026-07", "regularidades/b.pdf", "b" * 64, 10, "072026 - LOTUFO.pdf")
    assert documentos.regularidade_vigente(conn, 1)["competencia"] == "2026-07"
    assert documentos.situacao_regularidade(conn, 1, D(2026, 9, 23))["situacao"] == "ok"
    assert documentos.situacao_regularidade(conn, 1, D(2026, 10, 10))["situacao"] == "atrasada"
    with pytest.raises(ValueError, match="já está anexad"):
        documentos.registrar_regularidade(conn, 1, 1, "2026-07", "regularidades/b.pdf", "b" * 64, 10, None)
    with pytest.raises(ValueError, match="competência"):
        documentos.registrar_regularidade(conn, 1, 1, "2026-12", "regularidades/c.pdf", "c" * 64, 10, None)


def test_ler_resolve_empresa_e_recusa_cnpj_de_fora(conn):
    texto = (FIX / "federal-alfa.txt").read_text(encoding="utf-8")
    r = documentos.ler(conn, texto)
    assert (r["entidade_id"], r["tipo_id"], r["tipo"]) == (1, 1, "federal")
    with pytest.raises(leitura_certidao.Recusa) as e:
        documentos.ler(conn, (FIX / "federal-epsilon.txt").read_text(encoding="utf-8"))   # Oriundi nao cadastrado aqui
    assert e.value.motivo == "empresa-desconhecida"


def test_gravar_lida_e_repetida(conn):
    r = documentos.ler(conn, (FIX / "trabalhista-alfa.txt").read_text(encoding="utf-8"))
    cid = documentos.gravar_certidao(conn, 1, r, "certidoes/x.pdf", "c" * 64, "cndt.pdf", "automatica")
    linha = conn.execute("SELECT natureza, leitura, nome_original, numero FROM certidoes WHERE id=?", (cid,)).fetchone()
    assert tuple(linha) == ("negativa", "automatica", "cndt.pdf", "99100001/2026")
    with pytest.raises(ValueError, match="já está cadastrada"):
        documentos.gravar_certidao(conn, 1, r, "certidoes/x.pdf", "c" * 64, "cndt.pdf", "automatica")


def test_manual_da_falencia_calcula_a_validade(conn):
    d = documentos.dados_manuais(conn, 1, "falencia", "2026-08-03", None, "negativa", None)
    assert d["validade"] == "2026-09-14"
    with pytest.raises(ValueError, match="negativa"):
        documentos.dados_manuais(conn, 1, "fgts", "2026-08-03", "2026-09-01", "positiva", None)


def test_manual_confere_a_empresa_contra_o_cnpj_do_texto(conn):
    with pytest.raises(ValueError, match="CNPJ"):
        documentos.dados_manuais(conn, 1, "estadual", "2026-06-24", "2026-08-22", "negativa", None,
                                 cnpjs_do_texto=["31200202000100"])          # PDF da Guaxe, empresa Lotufo
    assert documentos.dados_manuais(conn, 1, "estadual", "2026-06-24", "2026-08-22", "negativa", None,
                                    cnpjs_do_texto=["31200101000130"])["entidade_id"] == 1


def test_avisos_uma_linha_por_empresa_e_regularidade_do_mes(conn):
    oid = _orgao(conn, ["fgts", "municipal", "regularidade"], ["estadual"])
    _contrato(conn, oid)
    _cert(conn, 1, "fgts", "2026-08-31", "2026-09-27")
    _cert(conn, 1, "municipal", "2026-06-20", "2026-09-20")
    av = documentos.avisos(conn, D(2026, 9, 23))
    doc = [a for a in av if a["tipo"] == "documentos_empresa"]
    assert len(doc) == 1 and doc[0]["entidade_id"] == 1 and doc[0]["nivel"] == "critico"   # D10
    assert doc[0]["mensagem"].startswith(f"{doc[0]['entidade']}: ")   # A11: o nome da empresa num campo
    assert "municipal vencida em 20/09/2026" in doc[0]["mensagem"] and "FGTS vence em 4 dias" in doc[0]["mensagem"]
    assert "estadual" in doc[0]["mensagem"]             # exigida no reajuste e nunca anexada
    assert doc[0]["data"] == "2026-09-20"               # A8: a validade que pesa primeiro (a vencida)
    reg = [a for a in av if a["tipo"] == "regularidade_mes"]
    assert len(reg) == 1 and "07/2026" in reg[0]["mensagem"]
    assert [a for a in documentos.avisos(conn, D(2026, 9, 9)) if a["tipo"] == "regularidade_mes"] == []


def test_painel_diz_as_obras_que_exigem_cada_empresa(conn):
    _consorcio(conn)                                    # A7: consórcio (2) com Lotufo (1) e Rivoli (3)
    oid = _orgao(conn, ["fgts"], [])
    c1 = _contrato(conn, oid, entidade_id=2)
    c2 = _contrato(conn, oid, entidade_id=1)
    conn.execute("UPDATE contratos SET nome_curto='Leblon' WHERE id=?", (c1,))
    conn.execute("UPDATE contratos SET nome_curto='Cavalaria' WHERE id=?", (c2,)); conn.commit()
    obras = {e["entidade_id"]: [o["obra"] for o in e["obras"]] for e in documentos.painel(conn)["empresas"]}
    assert obras == {1: ["Cavalaria", "Leblon"], 2: ["Leblon"], 3: ["Leblon"]}


def test_zip_das_vigentes_na_data(conn):
    pasta = db.db_path().parent / "certidoes"
    pasta.mkdir(exist_ok=True)
    (pasta / "1fgts.pdf").write_bytes(b"%PDF-1.4 fgts")
    conn.execute("UPDATE entidades SET nome_curto='Lotufo' WHERE id=1")
    conn.commit()
    _cert(conn, 1, "fgts", "2026-08-31", "2026-09-29")
    nome, dados = documentos.zip_vigentes(conn, 1, "2026-09-23")
    assert nome == "Certidoes - Lotufo - 2026-09-23.zip"
    assert zipfile.ZipFile(io.BytesIO(dados)).namelist() == ["Lotufo - FGTS - 2026-09-29.pdf"]
    with pytest.raises(ValueError, match="nenhuma certidão vigente"):
        documentos.zip_vigentes(conn, 1, "2026-10-15")


def test_orgao_que_so_exige_regularidade_gera_aviso(conn):
    # gate Sol, achado 5
    _contrato(conn, _orgao(conn, ["regularidade"], []))
    assert [a["tipo"] for a in documentos.avisos(conn, D(2026, 9, 23))] == ["regularidade_mes"]


def test_regularidade_de_entidade_desativada_e_recusada(conn):
    conn.execute("INSERT INTO entidades (id, nome, cnpj, papel, ativo) VALUES (9, 'X', '11444777000161', 'consorciada', 0)")
    conn.commit()
    with pytest.raises(ValueError, match="desativada"):
        documentos.registrar_regularidade(conn, 1, 9, "2026-07", "regularidades/x.pdf", "d" * 64, 10, None)


def test_zip_com_arquivo_ausente_e_erro_de_dominio(conn):
    _cert(conn, 1, "fgts", "2026-08-31", "2026-09-29")          # linha sem PDF na pasta
    with pytest.raises(ValueError, match="não está na pasta"):
        documentos.zip_vigentes(conn, 1, "2026-09-23")


def test_painel_diz_a_composicao_do_consorcio_o_dono_de_cada_obra_e_as_regularidades_anexadas(conn):
    # redesenho de Documentos (#161): a pagina da empresa precisa saber as consorciadas, de quem e' a garantia
    # de cada obra e o que ja' foi anexado da regularidade (so' leitura)
    _consorcio(conn)
    oid = _orgao(conn, ["fgts", "regularidade"], [])
    c_consorcio = _contrato(conn, oid, entidade_id=2)
    c_lotufo = _contrato(conn, oid, entidade_id=1)
    for comp in ("2026-06", "2026-07"):
        conn.execute("INSERT INTO regularidades (entidade_id, competencia, arquivo, sha256, tamanho) "
                     "VALUES (1, ?, ?, ?, 1)", (comp, f"regularidades/{comp}.pdf", comp[-2:] * 32))
    conn.commit()
    p = documentos.painel(conn)
    por_id = {e["entidade_id"]: e for e in p["empresas"]}
    assert por_id[2]["consorciadas"] == [1, 3] and por_id[2]["consorcios"] == []
    assert por_id[3]["consorcios"] == [2] and por_id[3]["consorciadas"] == []
    assert {o["contrato_id"]: o["entidade_id"] for o in p["contratos"]} == {c_consorcio: 2, c_lotufo: 1}
    anexadas = por_id[1]["regularidades_anexadas"]
    assert [a["competencia"] for a in anexadas] == ["2026-07", "2026-06"]
    assert set(anexadas[0]) == {"id", "competencia", "anexada_em"} and len(anexadas[0]["anexada_em"]) == 10
    assert por_id[3]["regularidades_anexadas"] == []


def test_empresa_contratada_entra_no_painel_mesmo_sem_certidao_exigida(conn):
    # revisor, rodada 1: o consorcio cujo orgao so' exige a regularidade ficava fora e a garantia dele sumia da tela
    _consorcio(conn)
    cid = _contrato(conn, _orgao(conn, ["regularidade"], []), entidade_id=2)
    p = documentos.painel(conn)
    assert 2 in {e["entidade_id"] for e in p["empresas"]}
    assert {o["contrato_id"]: o["entidade_id"] for o in p["contratos"]}[cid] == 2


def test_anexada_em_da_regularidade_e_o_dia_de_cuiaba(conn):
    # 01:30 UTC de 09/07 ainda e' 21:30 de 08/07 em Cuiaba
    conn.execute("INSERT INTO regularidades (entidade_id, competencia, arquivo, sha256, tamanho, criado_em) "
                 "VALUES (1, '2026-06', 'r.pdf', ?, 1, '2026-07-09 01:30:00')", ("a" * 64,))
    conn.commit()
    _contrato(conn, _orgao(conn, ["regularidade"], []))
    e = {x["entidade_id"]: x for x in documentos.painel(conn)["empresas"]}[1]
    assert e["regularidades_anexadas"][0]["anexada_em"] == "2026-07-08"


def test_aviso_de_garantia_leva_a_empresa_contratada(conn):
    from app import avisos
    _consorcio(conn)
    cid = _contrato(conn, _orgao(conn, ["fgts"], []), entidade_id=2)
    conn.execute("UPDATE contratos SET garantia_vigencia_fim='2026-09-30', garantia_apolice='A1' WHERE id=?", (cid,))
    conn.commit()
    g = [a for a in avisos.listar(conn, D(2026, 9, 23)) if a["tipo"] == "garantia_vencendo"]
    assert g and g[0]["entidade_id"] == 2
