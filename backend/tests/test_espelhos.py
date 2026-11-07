import hashlib
import json
import zipfile

import pytest
from app import arquivos, auth, cadastro_aplicar, correio, db, espelhos, graph, medicoes, notas
from tests.test_cadastro_aplicar import _cad_com_espelho
from tests.test_cadastro_arquivos import _modelo_completo


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn(); db.migrate(conn)
    uid = auth.criar_usuario(conn, "Maria", "maria@l.com", "senha-forte-123", "engenharia")
    conn.execute("UPDATE certidao_tipos SET aplicavel_por_padrao=0"); conn.commit()
    cad = _cad_com_espelho(tmp_path)
    m = tmp_path / "m.docx"; m.write_bytes(_modelo_completo())
    cad["espelho"][0]["modelos"]["medicao"] = {"caminho": m, "sha256": hashlib.sha256(m.read_bytes()).hexdigest()}
    cad["espelho"][0]["situacao"] = cad["espelho"][0]["regra"]["situacao"] = "ativa"
    cadastro_aplicar.aplicar(conn, uid, cad)
    cid = conn.execute("SELECT id FROM contratos").fetchone()[0]
    yield conn, {"id": uid, "email": "maria@l.com"}, cid
    conn.close()


def test_previa_uma_linha_por_nota_e_medicoes_a_criar(ambiente):
    conn, u, cid = ambiente
    p = espelhos.previa(conn, cid, 23, "2026-01", {"medicao": 27850992})
    assert [s["chave"] for s in p["saidas"]] == ["medicao"]
    assert p["saidas"][0]["nome_arquivo"] == "ESPELHO - MT-402 - 23ª Medição (01.2026).docx"
    assert p["medicoes"] == [{"tipo": "execucao", "valor_centavos": 27850992, "existente": None, "sem_boletim": False}]
    assert p["travados"] == [] and p["entradas"] == {"medicao": 27850992}      # #284: nada vem da medicao


def test_gerar_cria_medicao_espelho_arquivo_e_documento(ambiente):
    conn, u, cid = ambiente
    eid = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 27850992})
    d = espelhos.detalhe(conn, eid)
    assert d["versao"] == 1 and d["situacao"] == "vigente" and len(d["arquivos"]) == 1
    assert d["criado_por_nome"] == "Maria"
    mid = d["medicoes"][0]["id"]
    assert medicoes.detalhe(conn, mid)["estado"] == "espelho_gerado"
    doc = conn.execute("SELECT * FROM medicao_documentos WHERE medicao_id=?", (mid,)).fetchone()
    assert doc["tipo_doc"] == "espelho" and doc["arquivo"].startswith("espelhos/") and doc["espelho_id"] == eid
    with zipfile.ZipFile(arquivos.caminho_seguro(doc["arquivo"])) as z:
        assert "278.509,92" in z.read("word/document.xml").decode("utf-8")
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='espelho.gerar'").fetchone()[0] == 1


def test_gerar_de_novo_versiona_e_atualiza_o_valor(ambiente):
    conn, u, cid = ambiente
    e1 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})
    e2 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 200}, motivo="órgão corrigiu")
    d1, d2 = espelhos.detalhe(conn, e1), espelhos.detalhe(conn, e2)
    assert (d1["situacao"], d1["motivo"], d2["versao"], d2["situacao"]) == ("substituido", "órgão corrigiu", 2, "vigente")
    assert d1["medicoes"][0]["id"] == d2["medicoes"][0]["id"]
    assert medicoes.detalhe(conn, d2["medicoes"][0]["id"])["valor_protocolado_centavos"] == 200
    assert [x["versao"] for x in espelhos.listar(conn, cid)] == [2, 1]


def test_regra_em_prova_ou_ausente_recusa(ambiente):
    conn, u, cid = ambiente
    conn.execute("UPDATE espelho_regras SET situacao='prova'"); conn.commit()
    with pytest.raises(ValueError, match="fluxo antigo"):
        espelhos.previa(conn, cid, 1, "2026-01", {"medicao": 1})


def test_entrada_desconhecida_e_tudo_zero_recusam(ambiente):
    conn, u, cid = ambiente
    with pytest.raises(ValueError, match="entrada"):
        espelhos.previa(conn, cid, 1, "2026-01", {"reajuste": 1})
    with pytest.raises(ValueError, match="nenhuma nota"):
        espelhos.previa(conn, cid, 1, "2026-01", {"medicao": 0})


def test_medicao_protocolada_nao_ganha_espelho_novo(ambiente):
    conn, u, cid = ambiente
    eid = espelhos.gerar(conn, u, cid, 5, "2026-01", {"medicao": 100})
    mid = espelhos.detalhe(conn, eid)["medicoes"][0]["id"]
    medicoes.registrar_protocolo(conn, u["id"], mid, "2026-02-01", "CT-1", None, "manual")
    with pytest.raises(ValueError, match="protocolada"):
        espelhos.previa(conn, cid, 5, "2026-01", {"medicao": 200})


# --- envio ao faturamento -----------------------------------------------------------------

def test_rotulo_da_medicao_no_assunto():
    s = lambda *n: [{"natureza": x} for x in n]
    assert espelhos.rotulo_medicao(10, s("medicao")) == "10ª Medição"
    assert espelhos.rotulo_medicao(10, s("medicao", "reajuste")) == "10ª Medição e Reajuste"
    assert espelhos.rotulo_medicao(14, s("medicao", "projeto")) == "14ª Medição e Projeto"
    assert espelhos.rotulo_medicao(3, s("medicao", "projeto", "reajuste")) == "3ª Medição, Projeto e Reajuste"
    assert espelhos.rotulo_medicao(3, s("reajuste")) == "3ª Reajuste"


def test_previa_do_envio_monta_destinatarios_assunto_e_anexos(ambiente):
    conn, u, cid = ambiente
    eid = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 27850992})
    p = espelhos.previa_envio(conn, eid)
    assert p["para"] == ["f@x.com"] and p["assunto"] == "Emissão NF - 23ª Medição - MT-402"
    assert [a["nome"] for a in p["anexos"]] == ["ESPELHO - MT-402 - 23ª Medição (01.2026).docx"]
    assert p["corpo"] == "Bom dia." and p["avisos"] == []


def test_consorciada_emissora_entra_nos_destinatarios_e_remetente_sai_da_copia(ambiente):
    conn, u, cid = ambiente
    conn.execute("INSERT INTO entidades (nome, cnpj, papel, chave, emails_faturamento) "
                 "VALUES ('Rivoli','31201111000190','consorciada','rivoli',?)", (json.dumps(["adm@zeta.exemplo.com.br"]),))
    conn.execute("UPDATE cadastro_geral SET valor=? WHERE chave='faturamento'", (json.dumps(
        {"para": ["f@x.com"], "copia": ["maria@l.com", "leo@x.com"], "assunto": "{medicao} - {obra}", "corpo": "{saudacao}"}),))
    conn.commit()
    eid = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})
    conn.execute("UPDATE espelhos SET saidas=? WHERE id=?", (json.dumps(
        [{**s, "emissor": "rivoli"} for s in espelhos.detalhe(conn, eid)["saidas"]]), eid)); conn.commit()
    p = espelhos.previa_envio(conn, eid, remetente="maria@l.com")
    assert p["para"] == ["f@x.com", "adm@zeta.exemplo.com.br"] and p["copia"] == ["leo@x.com"]
    assert p["corpo"] in ("Bom dia.", "Boa tarde.")


def test_previa_tira_da_copia_a_conta_do_outlook_diferente_do_login(ambiente):
    conn, u, cid = ambiente
    conn.execute("UPDATE cadastro_geral SET valor=? WHERE chave='faturamento'", (json.dumps(
        {"para": ["f@x.com"], "copia": ["leo.tal@x.com", "maria@l.com", "luana@l.com"], "assunto": "{medicao} - {obra}",
         "corpo": "{saudacao}"}),))
    conn.execute("INSERT INTO envios (tipo, usuario_id, remetente, para, copia, assunto) "
                 "VALUES ('espelho', ?, 'leo.tal@x.com', '[]', '[]', 'antes')", (u["id"],))
    conn.commit()
    eid = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})
    p = espelhos.previa_envio(conn, eid, remetente=u["email"])
    assert p["copia"] == ["luana@l.com"]


def test_enviar_registra_liga_medicoes_e_avanca_o_estado(ambiente, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente
    eid = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 27850992})
    p = espelhos.previa_envio(conn, eid)
    envio_id = espelhos.enviar(conn, u, eid, p["para"], p["copia"], p["assunto"], p["corpo"] + "\nLink: x")
    d = espelhos.detalhe(conn, eid)
    assert d["envio_id"] == envio_id and d["envio"]["para"] == ["f@x.com"]
    assert medicoes.detalhe(conn, d["medicoes"][0]["id"])["estado"] == "espelho_enviado"
    assert conn.execute("SELECT COUNT(*) FROM envio_medicoes WHERE envio_id=?", (envio_id,)).fetchone()[0] == 1
    gravado = json.loads(sorted((tmp_path / "sim" / "enviados").glob("*.json"))[0].read_text(encoding="utf-8"))
    assert gravado["anexos"][0]["nome"].endswith(".docx") and "<p>Link: x</p>" in gravado["corpo"]


def test_falha_no_envio_nao_muda_nada(ambiente, monkeypatch):
    conn, u, cid = ambiente
    eid = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})

    def quebra(*a, **k):
        raise graph.ErroGraph("Graph fora")
    monkeypatch.setattr(correio, "enviar_e_registrar", quebra)
    p = espelhos.previa_envio(conn, eid)
    with pytest.raises(graph.ErroGraph):
        espelhos.enviar(conn, u, eid, p["para"], p["copia"], p["assunto"], p["corpo"])
    d = espelhos.detalhe(conn, eid)
    assert d["envio_id"] is None and medicoes.detalhe(conn, d["medicoes"][0]["id"])["estado"] == "espelho_gerado"
    assert conn.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0


def test_versao_substituida_nao_se_envia_e_a_nova_volta_a_espelho_gerado(ambiente, tmp_path, monkeypatch):
    # issue #359 (decisao do Leo de 03/11/2026): a versao nova da medicao com espelho enviado volta a
    # `espelho_gerado` ate' o envio dela ao faturamento (antes, desde a #208, ficava `espelho_enviado`)
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente
    e1 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})
    p = espelhos.previa_envio(conn, e1)
    espelhos.enviar(conn, u, e1, p["para"], p["copia"], p["assunto"], p["corpo"])
    mid = espelhos.detalhe(conn, e1)["medicoes"][0]["id"]
    assert medicoes.detalhe(conn, mid)["estado"] == "espelho_enviado"
    e2 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 200}, motivo="corrigido")
    assert medicoes.detalhe(conn, mid)["estado"] == "espelho_gerado"
    with pytest.raises(ValueError, match="substitu"):
        espelhos.previa_envio(conn, e1)
    p2 = espelhos.previa_envio(conn, e2)
    assert any("versão 1" in a for a in p2["avisos"])
    espelhos.enviar(conn, u, e2, p2["para"], p2["copia"], p2["assunto"], p2["corpo"])
    assert medicoes.detalhe(conn, mid)["estado"] == "espelho_enviado"
    volta = conn.execute("SELECT antes, depois FROM audit_log WHERE acao='medicao.estado' AND entidade_id=? "
                         "ORDER BY id", (mid,)).fetchall()
    assert [(json.loads(a)["estado"], json.loads(d)["estado"]) for a, d in volta] == [
        ("espelho_gerado", "espelho_enviado"), ("espelho_enviado", "espelho_gerado"),
        ("espelho_gerado", "espelho_enviado")]


def test_mesmo_numero_com_outra_competencia_substitui_em_vez_de_duplicar(ambiente):
    conn, u, cid = ambiente
    e1 = espelhos.gerar(conn, u, cid, 10, "2026-05", {"medicao": 100})
    e2 = espelhos.gerar(conn, u, cid, 10, "2026-06", {"medicao": 200})
    assert espelhos.detalhe(conn, e1)["situacao"] == "substituido"
    assert (espelhos.detalhe(conn, e2)["versao"], espelhos.detalhe(conn, e2)["situacao"]) == (2, "vigente")
    assert conn.execute("SELECT COUNT(*) FROM espelhos WHERE contrato_id=? AND numero=10 AND situacao='vigente'",
                        (cid,)).fetchone()[0] == 1


def test_enviar_recusa_medicao_cancelada_antes_de_mandar(ambiente, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente
    eid = espelhos.gerar(conn, u, cid, 11, "2026-05", {"medicao": 100})
    mid = espelhos.detalhe(conn, eid)["medicoes"][0]["id"]
    medicoes.mudar_estado(conn, u["id"], mid, "cancelada", "teste")
    p = espelhos.previa_envio(conn, eid)
    with pytest.raises(ValueError, match="cancelada"):
        espelhos.enviar(conn, u, eid, p["para"], p["copia"], p["assunto"], p["corpo"])
    assert not (tmp_path / "sim").exists()


def test_gravar_bytes_regrava_arquivo_com_hash_que_nao_bate(ambiente):
    caminho, sha = arquivos.gravar_bytes("espelhos", b"conteudo bom", "bin")
    alvo = arquivos.caminho_seguro(caminho)
    alvo.write_bytes(b"truncado")
    arquivos.gravar_bytes("espelhos", b"conteudo bom", "bin")
    assert alvo.read_bytes() == b"conteudo bom"


def test_periodo_fora_do_mes_civil_vai_no_docx_e_fica_gravado(ambiente):
    # Terminais BRT 1a: 01/07 a 31/08/2026 na competencia 08; mes inteiro = NULL (nao grava o obvio)
    conn, u, cid = ambiente
    per = espelhos.validar_periodo("2026-08", "2026-07-01", "2026-08-31")
    assert espelhos.previa(conn, cid, 1, "2026-08", {"medicao": 100}, per)["periodo"] == "01/07/2026 A 31/08/2026"
    eid = espelhos.gerar(conn, u, cid, 1, "2026-08", {"medicao": 100}, periodo=per)
    d = espelhos.detalhe(conn, eid)
    assert (d["periodo_inicio"], d["periodo_fim"]) == ("2026-07-01", "2026-08-31")
    with zipfile.ZipFile(arquivos.caminho_seguro(conn.execute(
            "SELECT arquivo FROM medicao_documentos WHERE espelho_id=?", (eid,)).fetchone()[0])) as z:
        assert "01/07/2026 A 31/08/2026" in z.read("word/document.xml").decode("utf-8")
    assert espelhos.validar_periodo("2026-08", "2026-08-01", "2026-08-31") is None
    assert espelhos.validar_periodo("2026-08", None, None) is None
    for ini, fim in (("2026-08-10", None), ("2026-08-20", "2026-08-10"), ("2026-09-01", "2026-09-30"),
                     ("2025-01-01", "2026-08-31"), ("2026-02-30", "2026-08-31"), ("20260801", "2026-08-31"),
                     ("2026-W31-6", "2026-08-31")):
        with pytest.raises(ValueError, match="período"):
            espelhos.validar_periodo("2026-08", ini, fim)


# --- serie de Projeto com numeracao propria (#208) ------------------------------------------

@pytest.fixture
def ambiente_projeto(tmp_path, monkeypatch):
    """Obra com serie de Projeto: a regra tem entrada e nota de Projeto ao lado da de execucao."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn(); db.migrate(conn)
    uid = auth.criar_usuario(conn, "Maria", "maria@l.com", "senha-forte-123", "engenharia")
    conn.execute("UPDATE certidao_tipos SET aplicavel_por_padrao=0"); conn.commit()
    cad = _cad_com_espelho(tmp_path)
    m = tmp_path / "m.docx"; m.write_bytes(_modelo_completo())
    modelo = {"caminho": m, "sha256": hashlib.sha256(m.read_bytes()).hexdigest()}
    esp = cad["espelho"][0]
    esp["modelos"] = {"medicao": modelo, "projeto": modelo, "reajuste": modelo}
    esp["situacao"] = esp["regra"]["situacao"] = "ativa"
    for nat in ("projeto", "reajuste"):
        esp["regra"]["entradas"].append({"chave": nat, "rotulo": nat[0], "natureza": nat})
        esp["regra"]["saidas"].append({**esp["regra"]["saidas"][0], "chave": nat, "natureza": nat,
                                       "valor": [nat], "modelo": f"{nat}.docx"})
    cadastro_aplicar.aplicar(conn, uid, cad)
    cid = conn.execute("SELECT id FROM contratos").fetchone()[0]
    yield conn, {"id": uid, "email": "maria@l.com"}, cid
    conn.close()


def _estado_espelho(conn, eid):
    return tuple(conn.execute("SELECT situacao, versao, substituido_em, motivo FROM espelhos WHERE id=?",
                              (eid,)).fetchone())


def test_projeto_com_mesmo_numero_nao_substitui_espelho_da_execucao_protocolada(ambiente_projeto):
    conn, u, cid = ambiente_projeto
    e_exec = espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 100})
    mid = espelhos.detalhe(conn, e_exec)["medicoes"][0]["id"]
    medicoes.registrar_protocolo(conn, u["id"], mid, "2026-02-01", "CT-1", None, "manual")
    antes = _estado_espelho(conn, e_exec), medicoes.detalhe(conn, mid)["estado"]
    assert antes[0][0] == "vigente"
    p = espelhos.previa(conn, cid, 3, "2026-03", {"projeto": 500})
    assert p["medicoes"] == [{"tipo": "projeto", "valor_centavos": 500, "existente": None, "sem_boletim": False}]
    assert not any("já tem espelho" in a for a in p["avisos"])
    e_proj = espelhos.gerar(conn, u, cid, 3, "2026-03", {"projeto": 500})
    assert (_estado_espelho(conn, e_exec), medicoes.detalhe(conn, mid)["estado"]) == antes
    d = espelhos.detalhe(conn, e_proj)
    assert d["situacao"] == "vigente" and [m["tipo"] for m in d["medicoes"]] == ["projeto"]
    # o espelho vigente da execucao continua sendo o que o protocolo e as notas encontram
    assert [tuple(r) for r in conn.execute(
        "SELECT e.id FROM espelho_medicoes em JOIN espelhos e ON e.id=em.espelho_id "
        "WHERE em.medicao_id=? AND e.situacao='vigente'", (mid,))] == [(e_exec,)]
    log = conn.execute("SELECT depois FROM audit_log WHERE acao='espelho.gerar' AND entidade_id=?",
                       (e_proj,)).fetchone()[0]
    assert json.loads(log)["substitui"] is None


def test_gerar_de_novo_a_execucao_substitui_so_o_espelho_da_execucao(ambiente_projeto):
    conn, u, cid = ambiente_projeto
    e_exec = espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 100})
    e_proj = espelhos.gerar(conn, u, cid, 3, "2026-01", {"projeto": 500})
    proj_antes = _estado_espelho(conn, e_proj)
    assert proj_antes[0] == "vigente" and _estado_espelho(conn, e_exec)[0] == "vigente"
    e_exec2 = espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 200}, motivo="órgão corrigiu")
    assert _estado_espelho(conn, e_exec)[0] == "substituido"
    assert _estado_espelho(conn, e_proj) == proj_antes
    assert espelhos.detalhe(conn, e_exec2)["situacao"] == "vigente"
    # gerar de novo o Projeto substitui so' o do Projeto
    e_proj2 = espelhos.gerar(conn, u, cid, 3, "2026-01", {"projeto": 600})
    assert _estado_espelho(conn, e_proj)[0] == "substituido"
    assert _estado_espelho(conn, e_exec2)[0] == "vigente"
    assert espelhos.detalhe(conn, e_proj2)["situacao"] == "vigente"


def test_espelho_com_execucao_e_projeto_juntos_nao_e_substituido_por_uma_serie_so(ambiente_projeto):
    conn, u, cid = ambiente_projeto
    e = espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 100, "projeto": 500})
    antes = _estado_espelho(conn, e)
    with pytest.raises(ValueError, match="Medição 3 de execução está no mesmo espelho"):
        espelhos.previa(conn, cid, 3, "2026-01", {"projeto": 600})
    with pytest.raises(ValueError, match="mesmo espelho"):
        espelhos.gerar(conn, u, cid, 3, "2026-01", {"projeto": 600})
    assert _estado_espelho(conn, e) == antes
    assert conn.execute("SELECT COUNT(*) FROM espelhos").fetchone()[0] == 1
    # as duas juntas substituem normalmente
    e2 = espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 100, "projeto": 600})
    assert _estado_espelho(conn, e)[0] == "substituido" and espelhos.detalhe(conn, e2)["situacao"] == "vigente"


def _mid(conn, eid, tipo):
    return next(m["id"] for m in espelhos.detalhe(conn, eid)["medicoes"] if m["tipo"] == tipo)


def test_espelho_misto_com_execucao_protocolada_fica_vigente_e_projeto_ganha_espelho_proprio(ambiente_projeto):
    conn, u, cid = ambiente_projeto
    e = espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 100, "projeto": 500})
    m_exec, m_proj = _mid(conn, e, "execucao"), _mid(conn, e, "projeto")
    medicoes.registrar_protocolo(conn, u["id"], m_exec, "2026-02-01", "CT-1", None, "manual")
    antes = _estado_espelho(conn, e)
    e2 = espelhos.gerar(conn, u, cid, 3, "2026-01", {"projeto": 600})
    assert _estado_espelho(conn, e) == antes and antes[0] == "vigente"
    assert notas._espelho_vigente(conn, m_exec)["id"] == e
    assert notas._espelho_vigente(conn, m_proj)["id"] == e2
    assert [m["tipo"] for m in espelhos.detalhe(conn, e2)["medicoes"]] == ["projeto"]


def test_reajuste_sozinho_nao_substitui_espelho_da_execucao_protocolada(ambiente_projeto):
    conn, u, cid = ambiente_projeto
    # execucao sozinha no espelho
    e1 = espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 100})
    m1 = _mid(conn, e1, "execucao")
    medicoes.registrar_protocolo(conn, u["id"], m1, "2026-02-01", "CT-1", None, "manual")
    antes = _estado_espelho(conn, e1)
    e_r = espelhos.gerar(conn, u, cid, 3, "2026-01", {"reajuste": 7})
    assert _estado_espelho(conn, e1) == antes and antes[0] == "vigente"
    assert notas._espelho_vigente(conn, m1)["id"] == e1
    assert espelhos.detalhe(conn, e_r)["situacao"] == "vigente"
    # execucao e reajuste no mesmo espelho: regenerar o reajuste deixa o da execucao protocolada intocado
    e4 = espelhos.gerar(conn, u, cid, 4, "2026-02", {"medicao": 100, "reajuste": 7})
    m4 = _mid(conn, e4, "execucao")
    medicoes.registrar_protocolo(conn, u["id"], m4, "2026-03-01", "CT-2", None, "manual")
    antes4 = _estado_espelho(conn, e4)
    e4r = espelhos.gerar(conn, u, cid, 4, "2026-02", {"reajuste": 9})
    assert _estado_espelho(conn, e4) == antes4 and antes4[0] == "vigente"
    assert notas._espelho_vigente(conn, m4)["id"] == e4
    assert notas._espelho_vigente(conn, _mid(conn, e4r, "reajuste"))["id"] == e4r


def test_reajuste_sozinho_com_execucao_editavel_no_mesmo_espelho_recusa(ambiente_projeto):
    conn, u, cid = ambiente_projeto
    e = espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 100, "reajuste": 7})
    antes = _estado_espelho(conn, e)
    with pytest.raises(ValueError, match="Medição 3 de execução está no mesmo espelho"):
        espelhos.previa(conn, cid, 3, "2026-01", {"reajuste": 9})
    with pytest.raises(ValueError, match="gere junto"):
        espelhos.gerar(conn, u, cid, 3, "2026-01", {"reajuste": 9})
    assert _estado_espelho(conn, e) == antes
    assert notas._espelho_vigente(conn, _mid(conn, e, "execucao"))["id"] == e
    # execucao editavel em espelho proprio: o reajuste gerado depois nao a toca
    e5 = espelhos.gerar(conn, u, cid, 5, "2026-02", {"medicao": 100})
    e5r = espelhos.gerar(conn, u, cid, 5, "2026-02", {"reajuste": 7})
    assert _estado_espelho(conn, e5)[0] == "vigente" and _estado_espelho(conn, e5r)[0] == "vigente"


def test_aviso_de_envio_anterior_so_olha_as_mesmas_medicoes(ambiente_projeto, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente_projeto
    e_exec = espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 100})
    p = espelhos.previa_envio(conn, e_exec)
    espelhos.enviar(conn, u, e_exec, p["para"], p["copia"], p["assunto"], p["corpo"])
    e_proj = espelhos.gerar(conn, u, cid, 3, "2026-01", {"projeto": 500})
    assert not any("já foi enviada" in a for a in espelhos.previa_envio(conn, e_proj)["avisos"])
    e_exec2 = espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 200})
    assert any("versão 1" in a for a in espelhos.previa_envio(conn, e_exec2)["avisos"])


def _misto_desmembrado(conn, u, cid, competencia_nova="2026-01"):
    """Espelho A: execucao 100 + Projeto 500; execucao protocolada; Projeto gerado de novo com 600 (B)."""
    a = espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 100, "projeto": 500})
    medicoes.registrar_protocolo(conn, u["id"], _mid(conn, a, "execucao"), "2026-02-01", "CT-1", None, "manual")
    b = espelhos.gerar(conn, u, cid, 3, competencia_nova, {"projeto": 600})
    return a, b


def test_misto_com_medicao_de_espelho_mais_novo_nao_se_envia(ambiente_projeto, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente_projeto
    a, b = _misto_desmembrado(conn, u, cid)
    m_proj = _mid(conn, a, "projeto")
    assert {m["tipo"]: m["superado"] for m in espelhos.detalhe(conn, a)["medicoes"]} == \
        {"execucao": False, "projeto": True}
    assert [m["superado"] for m in espelhos.detalhe(conn, b)["medicoes"]] == [False]
    with pytest.raises(ValueError, match="Medição 3 de projeto tem espelho mais novo"):
        espelhos.previa_envio(conn, a)
    with pytest.raises(ValueError, match="espelho mais novo"):
        espelhos.enviar(conn, u, a, ["f@x.com"], [], "assunto", "corpo")
    assert espelhos.detalhe(conn, a)["envio_id"] is None
    assert medicoes.detalhe(conn, m_proj)["estado"] == "espelho_gerado"
    assert conn.execute("SELECT COUNT(*) FROM envio_medicoes").fetchone()[0] == 0
    # o mais novo do Projeto se envia normalmente
    p = espelhos.previa_envio(conn, b)
    espelhos.enviar(conn, u, b, p["para"], p["copia"], p["assunto"], p["corpo"])
    assert medicoes.detalhe(conn, m_proj)["estado"] == "espelho_enviado"


def test_listar_poe_a_versao_mais_nova_primeiro_mesmo_com_competencia_anterior(ambiente_projeto):
    conn, u, cid = ambiente_projeto
    a = espelhos.gerar(conn, u, cid, 3, "2026-02", {"medicao": 100, "projeto": 500})
    medicoes.registrar_protocolo(conn, u["id"], _mid(conn, a, "execucao"), "2026-03-01", "CT-1", None, "manual")
    b = espelhos.gerar(conn, u, cid, 3, "2026-01", {"projeto": 600})
    assert [e["id"] for e in espelhos.listar(conn, cid)] == [b, a]


def test_recusa_com_duas_medicoes_abertas_no_plural(ambiente_projeto):
    conn, u, cid = ambiente_projeto
    espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 100, "reajuste": 7, "projeto": 500})
    with pytest.raises(ValueError, match="Medição 3 de execução e Medição 3 de reajuste estão no mesmo espelho "
                                         "e ainda não foram protocoladas"):
        espelhos.previa(conn, cid, 3, "2026-01", {"projeto": 600})


# --- geracao x envio ao faturamento, em duas conexoes (#210) ------------------------------------

def _enviar_no_meio(monkeypatch, antes_de_reservar=None, durante_o_email=None):
    """Roda `antes_de_reservar` entre a leitura do espelho e a reserva, e `durante_o_email` com o e-mail
    'saindo' (reserva feita, envio ainda nao registrado): as duas janelas da corrida."""
    from app import envio_reserva
    reservar, registrar = envio_reserva.reservar, correio.enviar_e_registrar

    def reservar_atrasado(*a, **k):
        if antes_de_reservar:
            antes_de_reservar()
        return reservar(*a, **k)

    def registrar_atrasado(*a, **k):
        if durante_o_email:
            durante_o_email()
        return registrar(*a, **k)
    monkeypatch.setattr(envio_reserva, "reservar", reservar_atrasado)
    monkeypatch.setattr(correio, "enviar_e_registrar", registrar_atrasado)


def test_versao_nova_gerada_antes_da_reserva_barra_o_envio_da_antiga(ambiente, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente
    e1 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})
    p = espelhos.previa_envio(conn, e1)
    outra = db.get_conn()
    novos = []
    try:
        _enviar_no_meio(monkeypatch, antes_de_reservar=lambda: novos.append(
            espelhos.gerar(outra, u, cid, 23, "2026-01", {"medicao": 200}, motivo="corrigido")))
        with pytest.raises(ValueError, match="foi substituída; envie a versão vigente"):
            espelhos.enviar(conn, u, e1, p["para"], p["copia"], p["assunto"], p["corpo"])
    finally:
        outra.close()
    assert not (tmp_path / "sim").exists()                  # nenhum e-mail saiu
    d1 = espelhos.detalhe(conn, e1)
    assert (d1["situacao"], d1["envio_id"], d1["envio_reservado_em"]) == ("substituido", None, None)
    assert medicoes.detalhe(conn, d1["medicoes"][0]["id"])["estado"] == "espelho_gerado"
    assert espelhos.detalhe(conn, novos[0])["situacao"] == "vigente"


def test_misto_superado_antes_da_reserva_nao_se_envia(ambiente_projeto, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente_projeto
    a = espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 100, "projeto": 500})
    medicoes.registrar_protocolo(conn, u["id"], _mid(conn, a, "execucao"), "2026-02-01", "CT-1", None, "manual")
    p = espelhos.previa_envio(conn, a)
    outra = db.get_conn()
    try:
        _enviar_no_meio(monkeypatch, antes_de_reservar=lambda: espelhos.gerar(outra, u, cid, 3, "2026-01",
                                                                              {"projeto": 600}))
        with pytest.raises(ValueError, match="espelho mais novo"):
            espelhos.enviar(conn, u, a, p["para"], p["copia"], p["assunto"], p["corpo"])
    finally:
        outra.close()
    assert not (tmp_path / "sim").exists()
    d = espelhos.detalhe(conn, a)
    assert (d["envio_id"], d["envio_reservado_em"]) == (None, None)
    assert medicoes.detalhe(conn, _mid(conn, a, "projeto"))["estado"] == "espelho_gerado"


def test_reserva_direta_confere_vigente_e_superado(ambiente_projeto):
    from app import envio_reserva
    conn, u, cid = ambiente_projeto
    e1 = espelhos.gerar(conn, u, cid, 2, "2026-01", {"medicao": 100})
    espelhos.gerar(conn, u, cid, 2, "2026-01", {"medicao": 200})
    with pytest.raises(ValueError, match="substituída"):
        envio_reserva.reservar(conn, "espelhos", e1, u["id"])
    a, _ = _misto_desmembrado(conn, u, cid)
    with pytest.raises(ValueError, match="espelho mais novo"):
        envio_reserva.reservar(conn, "espelhos", a, u["id"])
    assert conn.execute("SELECT COUNT(*) FROM espelhos WHERE envio_reservado_em IS NOT NULL").fetchone()[0] == 0


def test_gerar_durante_o_envio_recusa_e_o_envio_termina_com_a_versao_enviada(ambiente, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente
    e1 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})
    p = espelhos.previa_envio(conn, e1)
    outra = db.get_conn()
    erros = []

    def gerar_na_outra():
        with pytest.raises(ValueError) as e:
            espelhos.gerar(outra, u, cid, 23, "2026-01", {"medicao": 200}, motivo="corrigido")
        erros.append(str(e.value))
    try:
        _enviar_no_meio(monkeypatch, durante_o_email=gerar_na_outra)
        envio_id = espelhos.enviar(conn, u, e1, p["para"], p["copia"], p["assunto"], p["corpo"])
    finally:
        outra.close()
    assert len(erros) == 1 and erros[0].startswith("A versão 1 deste espelho está sendo enviada ao faturamento "
                                                   "(iniciado às ")
    assert "por Maria): aguarde o envio terminar" in erros[0]
    d1 = espelhos.detalhe(conn, e1)
    assert (d1["situacao"], d1["envio_id"]) == ("vigente", envio_id)
    assert conn.execute("SELECT COUNT(*) FROM espelhos").fetchone()[0] == 1
    assert medicoes.detalhe(conn, d1["medicoes"][0]["id"])["valor_protocolado_centavos"] == 100
    assert medicoes.detalhe(conn, d1["medicoes"][0]["id"])["estado"] == "espelho_enviado"
    # terminado o envio, a versao nova se gera normalmente
    e2 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 200}, motivo="corrigido")
    assert espelhos.detalhe(conn, e2)["situacao"] == "vigente"


def test_gerar_com_misto_reservado_recusa_mesmo_sem_substituir(ambiente_projeto):
    """O misto com a execucao protocolada fica vigente, mas a medicao de Projeto passaria a valer pela versao
    nova enquanto o e-mail leva a velha: tambem recusa."""
    from app import envio_reserva
    conn, u, cid = ambiente_projeto
    a = espelhos.gerar(conn, u, cid, 3, "2026-01", {"medicao": 100, "projeto": 500})
    medicoes.registrar_protocolo(conn, u["id"], _mid(conn, a, "execucao"), "2026-02-01", "CT-1", None, "manual")
    envio_reserva.reservar(conn, "espelhos", a, u["id"])
    outra = db.get_conn()
    try:
        with pytest.raises(ValueError, match="está sendo enviada ao faturamento"):
            espelhos.gerar(outra, u, cid, 3, "2026-01", {"projeto": 600})
    finally:
        outra.close()
    assert conn.execute("SELECT COUNT(*) FROM espelhos").fetchone()[0] == 1
    # outra medicao do mesmo numero, fora do espelho reservado, nao e' barrada
    espelhos.gerar(conn, u, cid, 3, "2026-01", {"reajuste": 7})


# --- issue #284: o espelho usa o aprovado do boletim, senao o pedido; trava antes do boletim -------------------

JUSTIFICATIVA = "órgão manda a NF junto com o ofício"


def _antes_do_espelho(conn, cid, numero, estado, pedido=None):
    """Medicao que ja' existe antes do espelho (prevista, planilha/carta gerada ou enviada), com o pedido."""
    cur = conn.execute(
        "INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
        "valor_protocolado_origem) VALUES (?,?,'execucao','2026-01',?,?,?)",
        (cid, numero, estado, pedido, None if pedido is None else "manual"))
    conn.commit()
    return cur.lastrowid


def _boletim(conn, u, mid, valor, data="2026-02-10", sha="a"):
    return medicoes.registrar_boletim(conn, u["id"], mid, {"valor_centavos": valor, "data": data,
                                                           "numero_orgao": f"SMO {sha}"},
                                      {"arquivo": f"boletins/{sha}.pdf", "sha256": sha * 64})


def _texto_docx(conn, eid):
    doc = conn.execute("SELECT arquivo FROM medicao_documentos WHERE espelho_id=?", (eid,)).fetchone()
    with zipfile.ZipFile(arquivos.caminho_seguro(doc["arquivo"])) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_espelho_da_medicao_com_boletim_usa_o_aprovado_e_nao_sobrescreve_o_pedido(ambiente):
    conn, u, cid = ambiente
    mid = _antes_do_espelho(conn, cid, 23, "planilha_enviada", pedido=12_345_67)
    _boletim(conn, u, mid, 12_000_01)
    p = espelhos.previa(conn, cid, 23, "2026-01", {})
    assert p["medicoes"] == [{"tipo": "execucao", "valor_centavos": 12_000_01, "existente": "boletim_recebido",
                              "sem_boletim": False}]
    assert p["travados"] == [{"tipo": "execucao", "valor_centavos": 12_000_01, "fonte": "boletim",
                              "opcional": False, "sem_boletim": False}]
    eid = espelhos.gerar(conn, u, cid, 23, "2026-01", {})
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["valor_protocolado_centavos"], m["valor_protocolado_origem"], m["valor_atestado_centavos"]) == (
        "espelho_gerado", 12_345_67, "manual", 12_000_01)
    assert espelhos.detalhe(conn, eid)["entradas"] == {"medicao": 12_000_01}
    assert "12.000,01" in _texto_docx(conn, eid)


def test_atestado_digitado_sem_boletim_trava_o_valor_com_a_fonte_atestado(ambiente):
    # decisao do Leo de 03/11/2026: vale como aprovado; a trava do boletim continua (nao ha' PDF)
    conn, u, cid = ambiente
    mid = _antes_do_espelho(conn, cid, 23, "planilha_enviada", pedido=12_345_67)
    medicoes.definir_valor(conn, u["id"], mid, "atestado", 12_000_01, "manual", "2026-02-10")
    p = espelhos.previa(conn, cid, 23, "2026-01", {"medicao": 12_000_01})
    assert p["travados"] == [{"tipo": "execucao", "valor_centavos": 12_000_01, "fonte": "atestado", "opcional": True,
                              "sem_boletim": True}]
    assert p["medicoes"][0]["sem_boletim"] is True


def test_digitado_diferente_do_aprovado_recusa_com_os_dois_valores(ambiente):
    conn, u, cid = ambiente
    mid = _antes_do_espelho(conn, cid, 23, "planilha_enviada", pedido=12_345_67)
    _boletim(conn, u, mid, 12_000_01)
    with pytest.raises(ValueError, match=r"R\$ 12\.000,01.*R\$ 12\.345,67"):
        espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 12_345_67})
    assert medicoes.detalhe(conn, mid)["estado"] == "boletim_recebido"


def test_glosa_vira_evento_novo_e_o_espelho_usa_o_ultimo(ambiente):
    conn, u, cid = ambiente
    mid = _antes_do_espelho(conn, cid, 23, "planilha_enviada", pedido=12_345_67)
    _boletim(conn, u, mid, 12_000_01)
    _boletim(conn, u, mid, 11_999_99, "2026-02-12", sha="b")
    e1 = espelhos.gerar(conn, u, cid, 23, "2026-01", {})
    assert espelhos.detalhe(conn, e1)["entradas"] == {"medicao": 11_999_99}
    # glosa depois do espelho: gerar de novo (sem justificativa nenhuma) usa o aprovado novo; o pedido fica. A
    # medicao que ja' tem espelho so' entra digitada (nada digitado = fora), e digitada tem de ser o aprovado
    _boletim(conn, u, mid, 11_500_03, "2026-02-15", sha="c")
    with pytest.raises(ValueError, match="nenhuma nota"):
        espelhos.gerar(conn, u, cid, 23, "2026-01", {}, motivo="glosa do órgão")
    with pytest.raises(ValueError, match=r"R\$ 11\.500,03"):
        espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 11_999_99}, motivo="glosa do órgão")
    e2 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 11_500_03}, motivo="glosa do órgão")
    assert espelhos.detalhe(conn, e2)["entradas"] == {"medicao": 11_500_03}
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["valor_protocolado_centavos"], m["valor_atestado_centavos"]) == (
        "espelho_gerado", 12_345_67, 11_500_03)
    assert conn.execute("SELECT COUNT(*) FROM medicao_atestos WHERE medicao_id=?", (mid,)).fetchone()[0] == 3


def test_planilha_enviada_sem_boletim_exige_justificativa_e_usa_o_pedido(ambiente):
    conn, u, cid = ambiente
    mid = _antes_do_espelho(conn, cid, 23, "planilha_enviada", pedido=12_345_67)
    # sem boletim a medicao nao entra sozinha: nada digitado = fora deste espelho
    with pytest.raises(ValueError, match="nenhuma nota"):
        espelhos.previa(conn, cid, 23, "2026-01", {})
    pedido = {"medicao": 12_345_67}
    p = espelhos.previa(conn, cid, 23, "2026-01", pedido)      # a previa mostra, nao recusa
    assert p["medicoes"][0]["sem_boletim"] is True
    assert p["travados"] == [{"tipo": "execucao", "valor_centavos": 12_345_67, "fonte": "pedido", "opcional": True,
                              "sem_boletim": True}]
    with pytest.raises(ValueError, match="seguir sem boletim"):
        espelhos.gerar(conn, u, cid, 23, "2026-01", pedido)
    with pytest.raises(ValueError, match="justificativa"):
        espelhos.gerar(conn, u, cid, 23, "2026-01", pedido, justificativa_sem_boletim="curta")
    with pytest.raises(ValueError, match="R\\$ 12.345,67"):     # digitado, tem de ser o pedido
        espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 1}, justificativa_sem_boletim=JUSTIFICATIVA)
    assert medicoes.detalhe(conn, mid)["estado"] == "planilha_enviada"
    eid = espelhos.gerar(conn, u, cid, 23, "2026-01", pedido, justificativa_sem_boletim=JUSTIFICATIVA)
    assert espelhos.detalhe(conn, eid)["entradas"] == {"medicao": 12_345_67}
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["valor_protocolado_centavos"], m["valor_atestado_centavos"]) == (
        "espelho_gerado", 12_345_67, None)
    a = conn.execute("SELECT depois FROM audit_log WHERE acao='medicao.sem_boletim' AND entidade_id=?",
                     (str(mid),)).fetchone()
    assert json.loads(a["depois"])["justificativa"] == JUSTIFICATIVA
    textos = [e["texto"] for e in medicoes.edicoes_valor(conn, [mid])[mid]]
    assert f"Espelho gerado sem boletim: {JUSTIFICATIVA} por Maria" in textos
    # gerar de novo um espelho ja' gerado nao pede nada
    espelhos.gerar(conn, u, cid, 23, "2026-01", pedido)


def test_prevista_sem_valor_exige_justificativa_e_o_valor_e_digitado(ambiente):
    conn, u, cid = ambiente
    mid = _antes_do_espelho(conn, cid, 23, "prevista")
    assert espelhos.previa(conn, cid, 23, "2026-01", {"medicao": 500_01})["travados"] == []
    with pytest.raises(ValueError, match="seguir sem boletim"):
        espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 500_01})
    espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 500_01}, justificativa_sem_boletim=JUSTIFICATIVA)
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["valor_protocolado_centavos"], m["valor_protocolado_origem"]) == (
        "espelho_gerado", 500_01, "espelho")
    textos = [e["texto"] for e in medicoes.edicoes_valor(conn, [mid])[mid]]
    assert "Valor protocolado definido em R$ 500,01 por Maria" in textos


def test_prevista_com_boletim_nao_pede_justificativa(ambiente):
    conn, u, cid = ambiente
    mid = _antes_do_espelho(conn, cid, 23, "prevista")
    _boletim(conn, u, mid, 700_01)
    espelhos.gerar(conn, u, cid, 23, "2026-01", {})
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["valor_protocolado_centavos"], m["valor_atestado_centavos"]) == (
        "espelho_gerado", 700_01, 700_01)


def test_envio_da_v1_terminado_durante_a_geracao_da_v2_recusa_a_v2(ambiente, tmp_path, monkeypatch):
    # gate Sol (#284): A comeca a v2, B termina o envio da v1 enquanto o .docx e' montado; A nao grava por cima
    from app import espelho_docx
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente
    e1 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})
    p = espelhos.previa_envio(conn, e1)
    preencher, outra = espelho_docx.preencher, db.get_conn()

    def preencher_com_envio(*a, **k):
        if not conn.execute("SELECT envio_id FROM espelhos WHERE id=?", (e1,)).fetchone()[0]:
            espelhos.enviar(outra, u, e1, p["para"], p["copia"], p["assunto"], p["corpo"])
        return preencher(*a, **k)
    monkeypatch.setattr(espelho_docx, "preencher", preencher_com_envio)
    try:
        with pytest.raises(ValueError, match="mudou enquanto o espelho era gerado"):
            espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 200}, motivo="corrigido")
    finally:
        outra.close()
    d1 = espelhos.detalhe(conn, e1)
    assert d1["situacao"] == "vigente" and d1["envio_id"] is not None
    assert conn.execute("SELECT COUNT(*) FROM espelhos").fetchone()[0] == 1


def _durante_a_montagem(monkeypatch, acao):
    """Roda `acao` uma vez, no meio da montagem do .docx (entre a conta e a gravacao)."""
    from app import espelho_docx
    preencher, feito = espelho_docx.preencher, []

    def preencher_com_acao(*a, **k):
        if not feito:
            feito.append(1)
            acao()
        return preencher(*a, **k)
    monkeypatch.setattr(espelho_docx, "preencher", preencher_com_acao)


def test_regra_trocada_durante_a_montagem_recusa_e_o_sha_e_o_capturado(ambiente, monkeypatch):
    from app import espelho_docx
    conn, u, cid = ambiente
    sha0 = conn.execute("SELECT sha256 FROM espelho_regras WHERE contrato_id=?", (cid,)).fetchone()[0]
    preencher, outra = espelho_docx.preencher, db.get_conn()

    def trocar_regra():
        outra.execute("UPDATE espelho_regras SET situacao='prova', sha256='outro' WHERE contrato_id=?", (cid,))
        outra.commit()
    try:
        _durante_a_montagem(monkeypatch, trocar_regra)
        with pytest.raises(ValueError, match="regra do espelho desta obra mudou"):
            espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})
    finally:
        outra.close()
    assert conn.execute("SELECT COUNT(*) FROM espelhos").fetchone()[0] == 0
    # sem troca, o sha gravado e' o da regra lida no inicio
    conn.execute("UPDATE espelho_regras SET situacao='ativa', sha256=? WHERE contrato_id=?", (sha0, cid)); conn.commit()
    monkeypatch.setattr(espelho_docx, "preencher", preencher)
    eid = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})
    assert espelhos.detalhe(conn, eid)["regra_sha256"] == sha0


def test_regra_trocada_e_desfeita_durante_a_geracao_usa_a_capturada(ambiente, monkeypatch):
    # gate Sol, rodada 3 (A->B->A): a regra muda logo depois da captura e volta antes do lock. O calculo tem de usar
    # a regra capturada (A), a mesma do sha gravado; relida do banco, ele sairia com B (aqui, em prova: recusa)
    conn, u, cid = ambiente
    sha0 = conn.execute("SELECT sha256 FROM espelho_regras WHERE contrato_id=?", (cid,)).fetchone()[0]
    outra, vigentes, feito = db.get_conn(), espelhos._vigentes, []

    def vigentes_trocando_a_regra(*a, **k):
        if not feito:           # 1a chamada: logo depois de `gerar` capturar a regra
            feito.append(1)
            outra.execute("UPDATE espelho_regras SET situacao='prova', sha256='b' WHERE contrato_id=?", (cid,))
            outra.commit()
        return vigentes(*a, **k)

    def desfazer():
        outra.execute("UPDATE espelho_regras SET situacao='ativa', sha256=? WHERE contrato_id=?", (sha0, cid))
        outra.commit()
    try:
        monkeypatch.setattr(espelhos, "_vigentes", vigentes_trocando_a_regra)
        _durante_a_montagem(monkeypatch, desfazer)
        eid = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})
    finally:
        outra.close()
    assert feito and espelhos.detalhe(conn, eid)["regra_sha256"] == sha0


def test_reenvio_da_v1_durante_a_geracao_da_v2_recusa(ambiente, tmp_path, monkeypatch):
    # so' o envio_id muda (a medicao ja' estava em espelho_enviado): a v2 nao substitui o reenvio sem ninguem ver
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente
    e1 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})
    p = espelhos.previa_envio(conn, e1)
    espelhos.enviar(conn, u, e1, p["para"], p["copia"], p["assunto"], p["corpo"])
    envio1 = espelhos.detalhe(conn, e1)["envio_id"]
    outra = db.get_conn()
    try:
        _durante_a_montagem(monkeypatch, lambda: espelhos.enviar(outra, u, e1, p["para"], p["copia"], p["assunto"],
                                                                 p["corpo"], reenviar=True))
        with pytest.raises(ValueError, match="mudou enquanto o espelho era gerado"):
            espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 200}, motivo="corrigido")
    finally:
        outra.close()
    d1 = espelhos.detalhe(conn, e1)
    assert d1["situacao"] == "vigente" and d1["envio_id"] != envio1


def test_reenvio_da_execucao_durante_a_geracao_so_do_projeto_nao_recusa(ambiente_projeto, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente_projeto
    e1 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})
    p = espelhos.previa_envio(conn, e1)
    espelhos.enviar(conn, u, e1, p["para"], p["copia"], p["assunto"], p["corpo"])
    outra = db.get_conn()
    try:
        _durante_a_montagem(monkeypatch, lambda: espelhos.enviar(outra, u, e1, p["para"], p["copia"], p["assunto"],
                                                                 p["corpo"], reenviar=True))
        e2 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"projeto": 500})
    finally:
        outra.close()
    assert [m["tipo"] for m in espelhos.detalhe(conn, e2)["medicoes"]] == ["projeto"]
    assert espelhos.detalhe(conn, e1)["situacao"] == "vigente"


def test_espelho_so_de_projeto_nao_puxa_a_execucao_ja_enviada(ambiente_projeto):
    # revisor (#284): a execucao com glosa depois do espelho enviado nao entra sozinha no espelho do projeto
    conn, u, cid = ambiente_projeto
    e1 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100_00})
    mid = espelhos.detalhe(conn, e1)["medicoes"][0]["id"]
    medicoes.marcar_espelho_enviado(conn, u["id"], mid)
    _boletim(conn, u, mid, 99_99)
    p = espelhos.previa(conn, cid, 23, "2026-01", {"projeto": 7_00})
    assert [m["tipo"] for m in p["medicoes"]] == ["projeto"]
    e2 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"projeto": 7_00})
    assert [m["tipo"] for m in espelhos.detalhe(conn, e2)["medicoes"]] == ["projeto"]
    assert espelhos.detalhe(conn, e1)["situacao"] == "vigente"
    assert medicoes.detalhe(conn, mid)["estado"] == "espelho_enviado"


def test_planilha_sendo_enviada_ao_orgao_nao_ganha_espelho(ambiente):
    conn, u, cid = ambiente
    mid = _antes_do_espelho(conn, cid, 23, "planilha_gerada", pedido=12_345_67)
    pid = conn.execute("INSERT INTO medicao_planilhas (medicao_id, versao, valor_pedido_centavos, "
                       "acumulado_anterior_centavos, origem) VALUES (?,1,1234567,0,'manual')", (mid,)).lastrowid
    conn.execute("INSERT INTO medicao_planilha_envios (medicao_id, planilha_id, envio_reservado_em, "
                 "envio_reservado_por) VALUES (?,?,datetime('now'),?)", (mid, pid, u["id"]))
    conn.commit()
    with pytest.raises(ValueError, match="sendo enviada ao órgão"):
        espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 12_345_67}, justificativa_sem_boletim=JUSTIFICATIVA)
    assert medicoes.detalhe(conn, mid)["estado"] == "planilha_gerada"


# --- issue #460: a planilha/carta gerada (sem envio registrado) segue ao espelho sem boletim, em toda obra ---------

def _planilha_gerada(conn, cid, numero=23, pedidos=(12_345_67,)):
    """Medicao em `planilha_gerada` com uma versao por pedido (a ultima e' a vigente, o pedido da medicao)."""
    mid = _antes_do_espelho(conn, cid, numero, "planilha_gerada", pedido=pedidos[-1])
    for versao, valor in enumerate(pedidos, start=1):
        conn.execute("INSERT INTO medicao_planilhas (medicao_id, versao, valor_pedido_centavos, "
                     "acumulado_anterior_centavos, origem, motivo) VALUES (?,?,?,0,'manual',?)",
                     (mid, versao, valor, None if versao == 1 else f"Rev0{versao - 1}: fiscal pediu ajuste"))
    conn.commit()
    return mid


@pytest.mark.parametrize("familia", ["sinfra", "mtpar", "ses", "prefeitura"])
def test_planilha_gerada_segue_sem_boletim_com_justificativa_em_toda_familia(ambiente, familia):
    conn, u, cid = ambiente
    conn.execute("UPDATE orgaos SET familia=? WHERE id=(SELECT orgao_id FROM contratos WHERE id=?)", (familia, cid))
    mid = _planilha_gerada(conn, cid, pedidos=(12_345_67, 12_000_01))
    pedido = {"medicao": 12_000_01}
    p = espelhos.previa(conn, cid, 23, "2026-01", pedido)
    assert p["medicoes"][0]["sem_boletim"] is True
    assert p["travados"] == [{"tipo": "execucao", "valor_centavos": 12_000_01, "fonte": "pedido", "opcional": True,
                              "sem_boletim": True}]
    with pytest.raises(ValueError, match="seguir sem boletim"):
        espelhos.gerar(conn, u, cid, 23, "2026-01", pedido)
    with pytest.raises(ValueError, match="justificativa"):
        espelhos.gerar(conn, u, cid, 23, "2026-01", pedido, justificativa_sem_boletim="curta")
    with pytest.raises(ValueError, match=r"R\$ 12\.000,01"):        # a v1 nao vale mais: o pedido e' o da ultima
        espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 12_345_67}, justificativa_sem_boletim=JUSTIFICATIVA)
    assert medicoes.detalhe(conn, mid)["estado"] == "planilha_gerada"
    eid = espelhos.gerar(conn, u, cid, 23, "2026-01", pedido, justificativa_sem_boletim=JUSTIFICATIVA)
    assert espelhos.detalhe(conn, eid)["entradas"] == {"medicao": 12_000_01}
    assert "12.000,01" in _texto_docx(conn, eid)
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["valor_protocolado_centavos"], m["valor_atestado_centavos"]) == (
        "espelho_gerado", 12_000_01, None)
    a = conn.execute("SELECT antes, depois FROM audit_log WHERE acao='medicao.sem_boletim' AND entidade_id=?",
                     (str(mid),)).fetchone()
    assert json.loads(a["antes"]) == {"estado": "planilha_gerada"}
    assert json.loads(a["depois"]) == {"justificativa": JUSTIFICATIVA, "espelho_id": eid,
                                       "envio_planilha_registrado": False}
    textos = [e["texto"] for e in medicoes.edicoes_valor(conn, [mid])[mid]]
    assert (f"Espelho gerado sem boletim e sem o envio da planilha/carta registrado: {JUSTIFICATIVA} por Maria"
            in textos)


def test_planilha_enviada_sem_boletim_nao_leva_a_marca_de_envio_nao_registrado(ambiente):
    conn, u, cid = ambiente
    mid = _antes_do_espelho(conn, cid, 23, "planilha_enviada", pedido=12_345_67)
    espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 12_345_67}, justificativa_sem_boletim=JUSTIFICATIVA)
    a = conn.execute("SELECT depois FROM audit_log WHERE acao='medicao.sem_boletim' AND entidade_id=?",
                     (str(mid),)).fetchone()
    assert "envio_planilha_registrado" not in json.loads(a["depois"])


def test_planilha_gerada_saindo_pelo_sistema_segura_tambem_a_previa(ambiente):
    conn, u, cid = ambiente
    mid = _planilha_gerada(conn, cid)
    pid = conn.execute("SELECT id FROM medicao_planilhas WHERE medicao_id=?", (mid,)).fetchone()[0]
    conn.execute("INSERT INTO medicao_planilha_envios (medicao_id, planilha_id, envio_reservado_em, "
                 "envio_reservado_por) VALUES (?,?,datetime('now'),?)", (mid, pid, u["id"]))
    conn.commit()
    with pytest.raises(ValueError, match="sendo enviada ao protocolo"):
        espelhos.previa(conn, cid, 23, "2026-01", {"medicao": 12_345_67})
    with pytest.raises(ValueError, match="sendo enviada"):
        espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 12_345_67}, justificativa_sem_boletim=JUSTIFICATIVA)
    assert medicoes.detalhe(conn, mid)["estado"] == "planilha_gerada"


def test_planilha_gerada_so_ganha_espelho_na_competencia_dela(ambiente):
    conn, u, cid = ambiente
    mid = _planilha_gerada(conn, cid)
    with pytest.raises(ValueError, match="competência 01/2026"):
        espelhos.gerar(conn, u, cid, 23, "2026-02", {"medicao": 12_345_67}, justificativa_sem_boletim=JUSTIFICATIVA)
    assert medicoes.detalhe(conn, mid)["estado"] == "planilha_gerada"


# --- issue #359: a versao nova do espelho enviado volta a medicao a `espelho_gerado` ---------------------------

def test_boletim_novo_depois_do_envio_e_v2_voltam_a_espelho_gerado_ate_o_novo_envio(ambiente, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente
    mid = _antes_do_espelho(conn, cid, 23, "planilha_enviada", pedido=12_345_67)
    _boletim(conn, u, mid, 12_000_01)
    e1 = espelhos.gerar(conn, u, cid, 23, "2026-01", {})
    p = espelhos.previa_envio(conn, e1)
    espelhos.enviar(conn, u, e1, p["para"], p["copia"], p["assunto"], p["corpo"])
    _boletim(conn, u, mid, 11_999_99, "2026-02-12", sha="b")
    assert medicoes.detalhe(conn, mid)["estado"] == "espelho_enviado"     # o boletim novo nao muda o estado
    e2 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 11_999_99}, motivo="boletim novo do órgão")
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["valor_protocolado_centavos"], m["valor_atestado_centavos"]) == (
        "espelho_gerado", 12_345_67, 11_999_99)
    p2 = espelhos.previa_envio(conn, e2)
    espelhos.enviar(conn, u, e2, p2["para"], p2["copia"], p2["assunto"], p2["corpo"])
    assert medicoes.detalhe(conn, mid)["estado"] == "espelho_enviado"


def test_v2_so_do_projeto_nao_volta_a_execucao_enviada(ambiente_projeto, tmp_path, monkeypatch):
    # so' a medicao da versao nova volta; a do outro espelho continua enviada
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente_projeto
    e1 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100_01})
    p = espelhos.previa_envio(conn, e1)
    espelhos.enviar(conn, u, e1, p["para"], p["copia"], p["assunto"], p["corpo"])
    exe = espelhos.detalhe(conn, e1)["medicoes"][0]["id"]
    e2 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"projeto": 7_01})
    p2 = espelhos.previa_envio(conn, e2)
    espelhos.enviar(conn, u, e2, p2["para"], p2["copia"], p2["assunto"], p2["corpo"])
    proj = espelhos.detalhe(conn, e2)["medicoes"][0]["id"]
    espelhos.gerar(conn, u, cid, 23, "2026-01", {"projeto": 7_03}, motivo="corrigido")
    assert medicoes.detalhe(conn, proj)["estado"] == "espelho_gerado"
    assert medicoes.detalhe(conn, exe)["estado"] == "espelho_enviado"
