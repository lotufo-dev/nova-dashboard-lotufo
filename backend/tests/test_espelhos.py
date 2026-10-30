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
    assert p["medicoes"] == [{"tipo": "execucao", "valor_centavos": 27850992, "existente": None}]


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


def test_versao_substituida_nao_se_envia_e_reenvio_mantem_estado(ambiente, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn, u, cid = ambiente
    e1 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 100})
    p = espelhos.previa_envio(conn, e1)
    espelhos.enviar(conn, u, e1, p["para"], p["copia"], p["assunto"], p["corpo"])
    e2 = espelhos.gerar(conn, u, cid, 23, "2026-01", {"medicao": 200}, motivo="corrigido")
    with pytest.raises(ValueError, match="substitu"):
        espelhos.previa_envio(conn, e1)
    p2 = espelhos.previa_envio(conn, e2)
    assert any("versão 1" in a for a in p2["avisos"])
    espelhos.enviar(conn, u, e2, p2["para"], p2["copia"], p2["assunto"], p2["corpo"])
    assert medicoes.detalhe(conn, espelhos.detalhe(conn, e2)["medicoes"][0]["id"])["estado"] == "espelho_enviado"


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
    assert p["medicoes"] == [{"tipo": "projeto", "valor_centavos": 500, "existente": None}]
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
