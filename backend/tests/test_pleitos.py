"""Pleitos de reajuste, prazo e conclusao (bloco 7): criar, carta, assinado, envio."""
import datetime
import json
import pathlib

import pytest
import yaml

from app import (arquivos, auth, cadastro_aplicar, correio, cronograma, db, graph, leitura_pdf, medicoes, paineis,
                 pleitos, reajuste, tempo)
from tests.test_protocolo import _assinar, _contrato

# Gera PDF com a fonte da producao (Arial no Windows): a CI roda este modulo nos dois jobs (marcador pdf).
pytestmark = pytest.mark.pdf

D = datetime.date
CARTAS = yaml.safe_load((pathlib.Path(__file__).parents[2] / "cadastro-exemplo" / "cartas.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def cenario(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    monkeypatch.setattr(tempo, "hoje_local", lambda: D(2026, 6, 15))
    c = db.get_conn(); db.migrate(c)
    uid = auth.criar_usuario(c, "Maria", "maria@l.com", "senha-forte-123", "admin")
    obra = {**_contrato("Obra SINFRA", "sinfra-x", "IC 1/2026"), "datas_base": [{"mes": "2024-06", "indice": "INCC-DI"}],
            "execucao_fim": "2026-10-20", "vigencia_fim": "2027-01-20"}
    cadastro_aplicar.aplicar(c, uid, {
        "orgaos": [{"chave": "sinfra-x", "nome": "SINFRA - X", "familia": "sinfra", "cnpj": None,
                    "regras": {"protocolo_para": ["sinfra@orgao-a.exemplo.com.br"], "protocolo_copia": ["leo@l.com"],
                               "documentos_medicao": [], "documentos_reajuste": []}}],
        "entidades": [{"chave": "lotufo", "nome": "Lotufo Engenharia e Construções Ltda", "cnpj": "31200101000130",
                       "papel": "lotufo", "coligada_rm": 1, "sigla_oficio": "LT", "nome_curto": "Lotufo"}],
        "contratos": [obra], "avisos": [], "geral": {"cartas": CARTAS}})
    cid = c.execute("SELECT id FROM contratos").fetchone()[0]
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
              "VALUES (?, 12, 'execucao', '2026-05', 'protocolada')", (cid,))
    c.commit()
    yield c, {"uid": uid, "usuario": {"id": uid, "email": "maria@l.com"}, "contrato": cid,
              "medicao": c.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]}
    c.close()


def test_reajuste_so_para_data_base_do_contrato_e_ciclo_corrente(cenario):
    c, ids = cenario
    with pytest.raises(ValueError, match="Data-base"):
        pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122", data_base_mes="2023-01")
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122", data_base_mes="2024-06")
    p = pleitos.detalhe(c, pid)
    assert (p["ciclo"], p["numero_oficio"]) == (2026, "CT-122-LT-2026")


def test_prazo_exige_dias_e_justificativa_e_chuva_vira_pendencia(cenario):
    c, ids = cenario
    with pytest.raises(ValueError, match="dias"):
        pleitos.criar(c, ids["uid"], ids["contrato"], "prazo", "310", justificativa="atraso")
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "prazo", "310", dias=120,
                        justificativa="Chuvas acima da média no período")
    assert "chuva" in [x["codigo"] for x in pleitos.detalhe(c, pid)["pendencias"]]


def test_conclusao_so_em_encerramento(cenario):
    c, ids = cenario
    with pytest.raises(ValueError, match="encerramento"):
        pleitos.criar(c, ids["uid"], ids["contrato"], "conclusao", "400")
    medicoes.marcar_final(c, ids["uid"], ids["medicao"], "2026-06-10")
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "conclusao", "400")
    assert "12ª Medição (10/06/2026)" in pleitos.corpo_padrao(c, pid)


def test_carta_de_prazo_traz_historico_e_novo_fim(cenario):
    c, ids = cenario
    c.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, nova_execucao_fim, status, "
              "data_assinatura, numero, forma) VALUES (?, 'prazo', 0, '2026-10-20', 'assinado', '2026-03-10', "
              "'001/2026', 'termo_aditivo')", (ids["contrato"],))
    c.execute("UPDATE contratos SET execucao_fim='2026-04-20'"); c.commit()
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "prazo", "310", dias=100, justificativa="Interferências na via")
    r = pleitos.montar(c, ids["uid"], pid)
    paginas = leitura_pdf.textos_por_pagina_com_limite(arquivos.caminho_seguro(r["arquivo"]).read_bytes())
    texto = " ".join(" ".join(paginas).split())                 # a quebra de linha do PDF vira espaco
    assert "1. HISTÓRICO" in texto and "O 1º termo aditivo" in texto
    assert "de 20/10/2026 para 28/01/2027" in texto


def _curvas_s(c, pid):
    return [a for a in pleitos.detalhe(c, pid)["anexos"] if a["nome"] == "Curva S.xlsx"]


def test_carta_de_prazo_leva_a_curva_s_na_lista_de_anexos(cenario):
    """Issue #293 (spec 2026-10-20 §4 item 3): a curva S do pedido, em xlsx gerado do cronograma vigente e do
    medido, entra na lista de anexos do pleito de prazo e vai na previa do e-mail; montar a carta de novo troca a
    curva pela do dia (a anterior fica no historico, marcada como removida)."""
    import io

    import openpyxl
    c, ids = cenario
    cronograma.nova_versao(c, ids["uid"], ids["contrato"], [("2026-04", 300_00), ("2026-05", 400_00)], "manual",
                           data_documento="2026-01-10")
    c.execute("UPDATE medicoes SET valor_protocolado_centavos=35000 WHERE id=?", (ids["medicao"],)); c.commit()
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "prazo", "310", dias=100, justificativa="Interferências na via")
    assert [(a["tipo"], a["ext"]) for a in _curvas_s(c, pid)] == [("outro", "xlsx")]
    do_criar = _curvas_s(c, pid)[0]["id"]

    def removidas():
        return c.execute("SELECT COUNT(*) FROM pleito_anexos WHERE pleito_id=? AND nome='Curva S.xlsx' "
                         "AND removido_em IS NOT NULL", (pid,)).fetchone()[0]

    pleitos.montar(c, ids["uid"], pid)
    assert [a["id"] for a in _curvas_s(c, pid)] == [do_criar] and removidas() == 0     # mesmos dados, mesma curva
    c.execute("UPDATE medicoes SET valor_protocolado_centavos=36000 WHERE id=?", (ids["medicao"],)); c.commit()
    pleitos.montar(c, ids["uid"], pid)
    curvas = _curvas_s(c, pid)
    assert len(curvas) == 1 and curvas[0]["id"] != do_criar and removidas() == 1      # a do dia troca a antiga
    ws = openpyxl.load_workbook(io.BytesIO(arquivos.caminho_seguro(curvas[0]["arquivo"]).read_bytes())).active
    assert [[x.value for x in linha] for linha in ws.iter_rows()] == [
        ["Competência", "Previsto vigente", "Previsto anterior", "Medido"],
        [datetime.datetime(2026, 4, 1), 300, None, 0],
        [datetime.datetime(2026, 5, 1), 700, None, 360]]
    assert "Curva S.xlsx" in [a["nome"] for a in pleitos.previa_envio(c, pid)["anexos"]]
    reajuste_id = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    pleitos.montar(c, ids["uid"], reajuste_id)
    assert _curvas_s(c, reajuste_id) == []                       # so' a carta de prazo leva a curva


def _com_cronograma(c, ids):
    cronograma.nova_versao(c, ids["uid"], ids["contrato"], [("2026-04", 300_00), ("2026-05", 400_00)], "manual",
                           data_documento="2026-01-10")


def _prazo(c, ids):
    return pleitos.criar(c, ids["uid"], ids["contrato"], "prazo", "310", dias=100, justificativa="Interferências na via")


def test_curva_s_do_sistema_nao_se_remove(cenario):
    """Rodada 1 da PR #436: a curva S vai com o pedido de prazo (spec §4 item 3, "anexado ao envio da carta")."""
    c, ids = cenario
    _com_cronograma(c, ids)
    pid = _prazo(c, ids)
    with pytest.raises(ValueError, match="não se remove"):
        pleitos.remover_anexo(c, ids["uid"], pid, _curvas_s(c, pid)[0]["id"])
    assert [a["gerado"] for a in _curvas_s(c, pid)] == [True]


def test_nome_da_curva_s_e_reservado_e_o_envio_nao_repete_nome(cenario):
    """Rodada 1 da PR #436: anexo arrastado com o nome da curva e' recusado (sem diferenciar maiusculas); um que ja'
    estivesse no banco com esse nome nao e' trocado pelo montar e vai no e-mail com outro nome."""
    c, ids = cenario
    _com_cronograma(c, ids)
    pid = _prazo(c, ids)
    with pytest.raises(ValueError, match="renomeie"):
        pleitos.adicionar_anexo(c, ids["uid"], pid, "outro", " curva s.XLSX ", b"PK\x03\x04curva do SMO", "xlsx")
    rel, sha = arquivos.gravar_bytes("pleitos", b"PK\x03\x04curva do SMO", "xlsx")
    antiga = c.execute("INSERT INTO pleito_anexos (pleito_id, tipo, nome, arquivo, sha256, tamanho, ext) "
                       "VALUES (?, 'outro', 'Curva S.xlsx', ?, ?, 20, 'xlsx')", (pid, rel, sha)).lastrowid
    c.commit()
    pleitos.montar(c, ids["uid"], pid)
    vigentes = {a["id"]: a["gerado"] for a in _curvas_s(c, pid)}
    assert vigentes.pop(antiga) is False and list(vigentes.values()) == [True]
    nomes = [a["nome"] for a in pleitos.previa_envio(c, pid)["anexos"]]
    assert nomes.count("Curva S.xlsx") == 1 and "Curva S (2).xlsx" in nomes and len(set(nomes)) == len(nomes)
    # rodada 2: o reajuste nunca gera curva, entao o nome fica livre nele
    reajuste_id = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    pleitos.adicionar_anexo(c, ids["uid"], reajuste_id, "outro", "Curva S.xlsx", b"PK\x03\x04curva do SMO", "xlsx")
    assert [a["nome"] for a in pleitos.detalhe(c, reajuste_id)["anexos"]] == ["Curva S.xlsx"]


def test_curva_s_sem_previsto_vigente_nao_vai(cenario):
    """Rodada 1 da PR #436: medicao protocolada sem cronograma vigente (ou so' com versao superada) daria a curva com
    o previsto zerado em todas as linhas; a curva e' a do cronograma vigente, entao nao vai nem vira pendencia."""
    c, ids = cenario
    c.execute("UPDATE medicoes SET valor_protocolado_centavos=35000 WHERE id=?", (ids["medicao"],)); c.commit()
    pid = _prazo(c, ids)
    assert _curvas_s(c, pid) == []
    _com_cronograma(c, ids)
    c.execute("UPDATE cronograma_versoes SET superada_em=datetime('now')"); c.commit()
    pleitos.montar(c, ids["uid"], pid)
    assert _curvas_s(c, pid) == []
    assert "curva_s" not in [x["codigo"] for x in pleitos.previa_envio(c, pid)["pendencias"]]


def test_montar_tira_a_curva_velha_quando_a_do_dia_sai_vazia(cenario):
    """Rodada 1 da PR #436 (prova do gate Sol): o cronograma e a medicao deixam de valer depois do criar; o montar
    nao deixa a curva velha ir ao orgao (fica marcada como removida)."""
    c, ids = cenario
    _com_cronograma(c, ids)
    c.execute("UPDATE medicoes SET valor_protocolado_centavos=35000 WHERE id=?", (ids["medicao"],)); c.commit()
    pid = _prazo(c, ids)
    assert len(_curvas_s(c, pid)) == 1
    c.execute("UPDATE cronograma_versoes SET superada_em=datetime('now')")
    c.execute("UPDATE medicoes SET estado='cancelada' WHERE id=?", (ids["medicao"],)); c.commit()
    pleitos.montar(c, ids["uid"], pid)
    assert _curvas_s(c, pid) == []
    assert "Curva S.xlsx" not in [a["nome"] for a in pleitos.previa_envio(c, pid)["anexos"]]
    assert c.execute("SELECT COUNT(*) FROM pleito_anexos WHERE pleito_id=? AND removido_em IS NOT NULL",
                     (pid,)).fetchone()[0] == 1
    # rodada 2: a retirada tem acao propria na auditoria ("Curva S do pleito retirada"), nao a da curva gerada
    assert [r[0] for r in c.execute("SELECT acao FROM audit_log WHERE entidade='pleito' AND entidade_id=? AND acao "
                                    "LIKE 'pleito.curva%' ORDER BY id", (pid,))] == ["pleito.curva_s",
                                                                                   "pleito.curva_s_removida"]


def _pronto_para_enviar(c, ids):
    _com_cronograma(c, ids)
    c.execute("UPDATE medicoes SET valor_protocolado_centavos=35000 WHERE id=?", (ids["medicao"],)); c.commit()
    pid = _prazo(c, ids)
    r = pleitos.montar(c, ids["uid"], pid)
    pleitos.receber_assinado(c, ids["uid"], pid, _assinar(arquivos.caminho_seguro(r["arquivo"]).read_bytes()))
    return pid


@pytest.mark.parametrize("mudanca", ["cronograma_novo", "medicao_cancelada", "versoes_superadas"])
def test_curva_s_que_mudou_depois_do_montar_trava_o_envio_ate_montar_de_novo(cenario, mudanca):
    """Rodada 2 da PR #436 (gate Sol; a regra do termo no oficio, PR #435): a carta foi montada e assinada, e depois o
    cronograma, a medicao ou as versoes mudaram. A previa avisa e o envio recusa, com justificativa ou sem; montar de
    novo traz a curva de agora (ou tira a curva, se nao ha mais o que gerar) e libera."""
    c, ids = cenario
    pid = _pronto_para_enviar(c, ids)
    if mudanca == "cronograma_novo":
        cronograma.nova_versao(c, ids["uid"], ids["contrato"], [("2026-05", 500_00), ("2026-06", 100_00)], "manual",
                               data_documento="2026-03-01")
    elif mudanca == "medicao_cancelada":
        c.execute("UPDATE medicoes SET estado='cancelada' WHERE id=?", (ids["medicao"],)); c.commit()
    else:
        c.execute("UPDATE cronograma_versoes SET superada_em=datetime('now')"); c.commit()
    pv = pleitos.previa_envio(c, pid)
    assert pleitos.CURVA_S_MUDOU in [x["mensagem"] for x in pv["pendencias"]]
    with pytest.raises(ValueError, match="A curva S mudou desde a carta montada"):
        pleitos.enviar(c, ids["usuario"], pid, pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                       justificativa="conferido, segue assim mesmo")
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    eid = _enviar(c, ids, pid, D(2026, 6, 15))
    nomes = [x[0] for x in c.execute("SELECT nome FROM envio_anexos WHERE envio_id=?", (eid,))]
    assert ("Curva S.xlsx" in nomes) is (mudanca != "versoes_superadas")


def test_envio_do_prazo_exige_a_curva_s_quando_ha_curva_a_gerar(cenario):
    """Rodada 1 da PR #436: pedido montado antes de haver cronograma; com curva a gerar e nenhuma em vigor, a previa
    mostra a pendencia e o envio recusa mesmo com justificativa. Montar de novo gera a curva e libera."""
    c, ids = cenario
    pid = _prazo(c, ids)
    r = pleitos.montar(c, ids["uid"], pid)
    pleitos.receber_assinado(c, ids["uid"], pid, _assinar(arquivos.caminho_seguro(r["arquivo"]).read_bytes()))
    _com_cronograma(c, ids)
    pv = pleitos.previa_envio(c, pid)
    assert pleitos.CURVA_S_FALTA in [x["mensagem"] for x in pv["pendencias"]]
    with pytest.raises(ValueError, match="Curva S não anexada"):
        pleitos.enviar(c, ids["usuario"], pid, pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                       justificativa="cronograma físico vai depois")
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    eid = _enviar(c, ids, pid, D(2026, 6, 15))
    assert "Curva S.xlsx" in [x[0] for x in c.execute("SELECT nome FROM envio_anexos WHERE envio_id=?", (eid,))]


def test_curva_s_sai_da_mesma_transacao_que_a_troca(cenario, monkeypatch):
    """Rodada 1 da PR #436 (gate Sol): criar e montar calculam a curva dentro do BEGIN IMMEDIATE que troca o anexo;
    medicao cancelada ou versao nova do cronograma no meio nao misturam dois retratos."""
    c, ids = cenario
    _com_cronograma(c, ids)
    original, dentro = paineis.curva_s, []

    def espia(conn, contrato_id):
        dentro.append(conn.in_transaction)
        return original(conn, contrato_id)

    monkeypatch.setattr(paineis, "curva_s", espia)
    pid = _prazo(c, ids)
    pleitos.montar(c, ids["uid"], pid)
    assert dentro == [True, True]


def test_carta_de_prazo_sem_cronograma_nem_medicao_nao_leva_curva_vazia(cenario):
    c, ids = cenario
    c.execute("UPDATE medicoes SET estado='cancelada' WHERE id=?", (ids["medicao"],)); c.commit()
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "prazo", "310", dias=100, justificativa="Interferências na via")
    pleitos.montar(c, ids["uid"], pid)
    assert _curvas_s(c, pid) == []


def _texto_da_carta_de_prazo(c, ids):
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "prazo", "310", dias=100, justificativa="Interferências na via")
    r = pleitos.montar(c, ids["uid"], pid)
    paginas = leitura_pdf.textos_por_pagina_com_limite(arquivos.caminho_seguro(r["arquivo"]).read_bytes())
    return " ".join(" ".join(paginas).split())


def test_carta_de_prazo_com_so_o_3o_termo_carregado_diz_3o(cenario):
    """Issue #261: cadastro parcial; o ordinal vem do numero do termo, nao da contagem."""
    c, ids = cenario
    c.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, nova_execucao_fim, status, "
              "data_assinatura, numero, forma) VALUES (?, 'prazo', 0, '2026-10-20', 'assinado', '2026-03-10', "
              "'099/2020/01/03', 'termo_aditivo')", (ids["contrato"],))
    c.commit()
    texto = _texto_da_carta_de_prazo(c, ids)
    assert "O 3º termo aditivo n.º 099/2020/01/03" in texto and "O 1º termo aditivo" not in texto


def test_carta_de_prazo_usa_o_ordinal_do_cadastro(cenario):
    """Issue #261: com `ordinal` no instrumento do cadastro, vale o `ordinal`."""
    c, ids = cenario
    ta = {"chave": "ta-5", "tipo": "aditivo_prazo", "data": "2026-03-10", "numero": "TA s/n", "objeto": None,
          "corrige": None, "pdf": None, "delta_valor_centavos": 0, "nova_execucao_fim": "2026-12-20",
          "nova_vigencia_fim": None, "dados": {}, "ordinal": 5}
    obra = {**_contrato("Obra SINFRA", "sinfra-x", "IC 1/2026"), "datas_base": [{"mes": "2024-06", "indice": "INCC-DI"}],
            "execucao_fim": "2026-10-20", "vigencia_fim": "2027-01-20", "instrumentos": [ta]}
    cadastro_aplicar.aplicar(c, ids["uid"], {
        "orgaos": [{"chave": "sinfra-x", "nome": "SINFRA - X", "familia": "sinfra", "cnpj": None,
                    "regras": {"protocolo_para": ["sinfra@orgao-a.exemplo.com.br"], "protocolo_copia": ["leo@l.com"],
                               "documentos_medicao": [], "documentos_reajuste": []}}],
        "entidades": [{"chave": "lotufo", "nome": "Lotufo Engenharia e Construções Ltda", "cnpj": "31200101000130",
                       "papel": "lotufo", "coligada_rm": 1, "sigla_oficio": "LT", "nome_curto": "Lotufo"}],
        "contratos": [obra], "avisos": [], "geral": {"cartas": CARTAS}})
    texto = _texto_da_carta_de_prazo(c, ids)
    assert "O 5º termo aditivo n.º TA s/n" in texto


def test_enviar_reajuste_fecha_o_aviso_de_pleito(cenario):
    c, ids = cenario
    assert "reajuste_pleito" in {a["tipo"] for a in reajuste.avisos(c, D(2026, 6, 15))}
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    pleitos.adicionar_anexo(c, ids["uid"], pid, "planilha_calculo", "memoria.xlsx", b"PK\x03\x04memoria", "xlsx")
    pleitos.adicionar_anexo(c, ids["uid"], pid, "cronograma", "cronograma.pdf", b"%PDF-1.4 cronograma", "pdf")
    r = pleitos.montar(c, ids["uid"], pid)
    pleitos.receber_assinado(c, ids["uid"], pid, _assinar(arquivos.caminho_seguro(r["arquivo"]).read_bytes()))
    pv = pleitos.previa_envio(c, pid)
    assert pv["pendencias"] == [] and len(pv["anexos"]) == 3
    eid = pleitos.enviar(c, ids["usuario"], pid, pv["para"], pv["copia"], pv["assunto"], pv["corpo"])
    assert c.execute("SELECT tipo FROM envios WHERE id=?", (eid,)).fetchone()[0] == "pleito_reajuste"
    assert reajuste.ciclos(c, ids["contrato"], D(2026, 6, 15))[0]["situacao"] == "apostilamento_pendente"
    assert "reajuste_pleito" not in {a["tipo"] for a in reajuste.avisos(c, D(2026, 6, 15))}


def test_copia_do_pleito_soma_a_da_obra_sem_quem_esta_no_para_nem_quem_envia(cenario):
    c, ids = cenario
    c.execute("UPDATE contratos SET copia_extras=? WHERE id=?", (json.dumps(
        ["eng@l.com", "eng@l.com", "leo@l.com", "fiscal@exemplo.gov.br", "maria.outlook@l.com"]), ids["contrato"]))
    c.execute("INSERT INTO envios (tipo, usuario_id, remetente, para, copia, assunto) "
              "VALUES ('teste', ?, 'maria.outlook@l.com', '[]', '[]', 'antes')", (ids["uid"],))
    c.commit()
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    pv = pleitos.previa_envio(c, pid, remetente="maria@l.com")
    assert "fiscal@exemplo.gov.br" in pv["para"] and pv["copia"] == ["leo@l.com", "eng@l.com"]


def test_falha_do_graph_nao_muda_o_pleito(cenario, monkeypatch):
    c, ids = cenario
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    pleitos.montar(c, ids["uid"], pid)
    pv = pleitos.previa_envio(c, pid)

    def falha(*a, **k):
        raise graph.ErroGraph("fora do ar")

    monkeypatch.setattr(correio, "enviar_e_registrar", falha)
    with pytest.raises(graph.ErroGraph):
        pleitos.enviar(c, ids["usuario"], pid, pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                       justificativa="teste de falha do Graph")
    assert pleitos.detalhe(c, pid)["situacao"] == "montado"
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0


def test_pleito_de_reajuste_exige_as_pecas_do_orgao(cenario):
    """Issue #50: o apostilamento de reajuste da Prefeitura de Cuiaba pede falencia, contrato social, documento do
    representante e balanco; o orgao declara isso no cadastro (`pecas_pleito_reajuste`) e o pleito cobra as quatro."""
    c, ids = cenario
    c.execute("UPDATE orgaos SET regras=json_set(regras, '$.pecas_pleito_reajuste', json(?))",
              ('["falencia", "contrato_social", "documento_representante", "balanco"]',)); c.commit()
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    p = pleitos.detalhe(c, pid)
    assert [x["tipo"] for x in p["exigidos"]] == ["planilha_calculo", "cronograma", "falencia", "contrato_social",
                                                 "documento_representante", "balanco"]
    faltam = [x["mensagem"] for x in p["pendencias"] if x["codigo"] == "anexo"]
    for rotulo in ("Certidão de falência", "Contrato social", "Documento do representante legal",
                   "Balanço patrimonial"):
        assert f"{rotulo}: não anexado" in faltam
    pleitos.adicionar_anexo(c, ids["uid"], pid, "falencia", "falencia.pdf", b"%PDF-1.4 falencia", "pdf")
    faltam = [x["mensagem"] for x in pleitos.detalhe(c, pid)["pendencias"] if x["codigo"] == "anexo"]
    assert "Certidão de falência: não anexado" not in faltam and len(faltam) == 5


def test_pecas_do_orgao_so_valem_no_pleito_de_reajuste(cenario):
    c, ids = cenario
    c.execute("UPDATE orgaos SET regras=json_set(regras, '$.pecas_pleito_reajuste', json(?))",
              ('["falencia"]',)); c.commit()
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "prazo", "310", dias=60, justificativa="Interferências na via")
    assert [x["tipo"] for x in pleitos.detalhe(c, pid)["exigidos"]] == ["cronograma"]


# --- reiteracao e reemissao do pleito de reajuste (issue #277; spec 2026-10-20 §2.2) ------------------------

def _enviar(c, ids, pid, hoje):
    r = pleitos.montar(c, ids["uid"], pid, hoje=hoje)
    pleitos.receber_assinado(c, ids["uid"], pid, _assinar(arquivos.caminho_seguro(r["arquivo"]).read_bytes()))
    pv = pleitos.previa_envio(c, pid, hoje=hoje)
    return pleitos.enviar(c, ids["usuario"], pid, pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                          justificativa="teste da reiteração", hoje=hoje)


def _mtpar(c):
    c.execute("UPDATE orgaos SET familia='mtpar'"); c.commit()


def _aditivo(c, ids, assinado_em, tipo="prazo"):
    c.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, nova_execucao_fim, status, "
              "data_assinatura, numero, forma) VALUES (?, ?, 0, '2027-01-20', 'assinado', ?, '002/2026', "
              "'termo_aditivo')", (ids["contrato"], tipo, assinado_em))
    c.commit()


def test_reiteracao_liga_ao_anterior_e_traz_a_carta_da_familia_b(cenario):
    c, ids = cenario
    _mtpar(c)
    original = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    _enviar(c, ids, original, D(2026, 6, 15))
    # sem aditivo depois do pleito, so' a reiteracao (nao ha' prazo minimo para reiterar)
    assert pleitos.detalhe(c, original)["reemissoes_possiveis"] == ["reiteracao"]
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "245", reemite_pleito_id=original,
                        reemissao="reiteracao", hoje=D(2026, 10, 30))
    p = pleitos.detalhe(c, pid)
    assert (p["reemite_pleito_id"], p["reemissao"], p["data_base_mes"], p["ciclo"]) == (original, "reiteracao",
                                                                                         "2024-06", 2026)
    assert p["rotulo"] == "Reiteração do pleito de reajuste" and p["exigidos"] == []
    assert p["anterior"]["numero_oficio"] == "CT-122-LT-2026"
    corpo = pleitos.corpo_padrao(c, pid, D(2026, 10, 30))
    assert "reiteramos" in corpo and "CT/122/LT/2026, de 15/06/2026" in corpo and "137 dias" in corpo
    assert "previsão de reajuste do contrato" not in corpo            # nao e' a carta da familia A
    assert "reiteração" in pleitos.previa_envio(c, pid, hoje=D(2026, 10, 30))["assunto"]


def test_reiteracao_enviada_liga_os_dois_e_nao_zera_a_espera_do_pedido(cenario):
    c, ids = cenario
    _mtpar(c)
    original = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    _enviar(c, ids, original, D(2026, 6, 15))
    assert reajuste.ciclos(c, ids["contrato"], D(2026, 10, 30))[0]["dias"] == 137
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "245", reemite_pleito_id=original,
                        reemissao="reiteracao", hoje=D(2026, 10, 30))
    eid = _enviar(c, ids, pid, D(2026, 10, 30))
    assert c.execute("SELECT tipo FROM envios WHERE id=?", (eid,)).fetchone()[0] == "pleito_reiteracao"
    antes = pleitos.detalhe(c, original)
    assert [(x["id"], x["reemissao"], x["situacao"]) for x in antes["reemissoes"]] == [(pid, "reiteracao", "enviado")]
    assert antes["reemissoes_possiveis"] == []                          # so' o mais recente se reitera
    assert pleitos.detalhe(c, pid)["reemissoes_possiveis"] == ["reiteracao"]
    k = reajuste.ciclos(c, ids["contrato"], D(2026, 11, 4))[0]
    # a reiteracao e' o pleito vigente, mas a espera pelo apostilamento conta do pedido original
    assert (k["pleito"]["id"], k["pedido"]["id"], k["dias"]) == (pid, original, 142)
    a = {x["tipo"]: x for x in reajuste.avisos(c, D(2026, 11, 4))}["reajuste_apostilamento"]
    assert (a["dias"], a["data"]) == (142, "2026-06-15") and "diretoria" in a["publico"]
    with pytest.raises(ValueError, match="mais recente"):
        pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "250", reemite_pleito_id=original,
                      reemissao="reiteracao", hoje=D(2026, 11, 4))


def test_reiteracao_so_na_mtpar_e_na_prefeitura_e_de_pleito_enviado(cenario):
    c, ids = cenario                                                    # cenario: SINFRA
    original = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    with pytest.raises(ValueError, match="enviado"):
        pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "245", reemite_pleito_id=original,
                      reemissao="cronograma")
    _enviar(c, ids, original, D(2026, 6, 15))
    # reemitir o cronograma pede aditivo de prazo ou valor assinado depois do pleito (estado `reemitir`)
    _aditivo(c, ids, "2026-05-01")                                       # antes do pleito: nao conta
    assert pleitos.detalhe(c, original)["reemissoes_possiveis"] == []
    with pytest.raises(ValueError, match="aditivo"):
        pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "260", reemite_pleito_id=original,
                      reemissao="cronograma")
    _aditivo(c, ids, "2026-08-01", tipo="valor")
    assert pleitos.detalhe(c, original)["reemissoes_possiveis"] == ["cronograma"]
    with pytest.raises(ValueError, match="MT-PAR"):
        pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "245", reemite_pleito_id=original,
                      reemissao="reiteracao")
    pid = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "260", reemite_pleito_id=original,
                        reemissao="cronograma")
    p = pleitos.detalhe(c, pid)
    # reemissao do cronograma e' o pleito da familia A de novo, com os mesmos anexos exigidos
    assert p["rotulo"] == "Reemissão do pleito de reajuste"
    assert [x["tipo"] for x in p["exigidos"]] == ["planilha_calculo", "cronograma"]
    assert "previsão de reajuste do contrato" in pleitos.corpo_padrao(c, pid)
    with pytest.raises(ValueError, match="reajuste"):
        pleitos.criar(c, ids["uid"], ids["contrato"], "prazo", "311", dias=10, justificativa="interferências",
                      reemite_pleito_id=original, reemissao="cronograma")


def test_reiteracao_recusada_com_o_ciclo_apostilado(cenario):
    c, ids = cenario
    _mtpar(c)
    original = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    _enviar(c, ids, original, D(2026, 6, 15))
    _aditivo(c, ids, "2026-08-01")
    c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) VALUES (?, 'ap-1', "
              "'apostilamento_reajuste', '2026-09-01', ?)", (ids["contrato"], json.dumps({"ciclo": 2026})))
    c.execute("UPDATE pleitos SET instrumento_chave='ap-1' WHERE id=?", (original,))   # o cadastro liga (issue #271)
    c.commit()
    # o apostilamento fecha o ciclo: nem reiteracao nem reemissao (como o antigo "Reenviar pleito")
    assert pleitos.detalhe(c, original)["reemissoes_possiveis"] == []
    for r in ("reiteracao", "cronograma"):
        with pytest.raises(ValueError, match="apostilado"):
            pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "245", reemite_pleito_id=original, reemissao=r)


def test_termo_do_ciclo_sem_ligacao_nao_recusa_a_reiteracao(cenario):
    # gate Sol (PR #317, S1): o termo que o cadastro nao ligou ao pleito nao fecha o ciclo (como na aba)
    c, ids = cenario
    _mtpar(c)
    original = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    _enviar(c, ids, original, D(2026, 6, 15))
    c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) VALUES (?, 'ap-1', "
              "'apostilamento_reajuste', '2026-09-01', ?)", (ids["contrato"], json.dumps({"ciclo": 2026})))
    c.commit()
    assert reajuste.ciclos(c, ids["contrato"], D(2026, 10, 30))[0]["situacao"] == "apostilamento_pendente"
    assert pleitos.detalhe(c, original)["reemissoes_possiveis"] == ["reiteracao"]


def test_reemissao_enviada_depois_do_termo_continua_reiteravel(cenario):
    # revisor (PR #317, R2): o termo ligado ao pleito anterior nao atende a reemissao do cronograma enviada depois;
    # a aba mostra o apostilamento pendente, e a reemissao pode ser reiterada (mesmo criterio de reajuste.ciclos)
    c, ids = cenario
    _mtpar(c)
    original = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    _enviar(c, ids, original, D(2026, 6, 15))
    c.execute("INSERT INTO pleitos (contrato_id, tipo, origem, data_base_mes, ciclo, numero_oficio, situacao, enviado_em, "
              "reemite_pleito_id, reemissao) VALUES (?, 'reajuste', 'cadastro', '2024-06', 2026, 'CT-260-LT-2026', "
              "'enviado', '2026-09-20', ?, 'cronograma')", (ids["contrato"], original))
    p2 = c.execute("SELECT MAX(id) FROM pleitos").fetchone()[0]
    c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) VALUES (?, 'ap-1', "
              "'apostilamento_reajuste', '2026-09-01', ?)", (ids["contrato"], json.dumps({"ciclo": 2026})))
    c.execute("UPDATE pleitos SET instrumento_chave='ap-1' WHERE id=?", (original,))
    c.commit()
    assert reajuste.ciclos(c, ids["contrato"], D(2026, 10, 30))[0]["situacao"] == "apostilamento_pendente"
    assert pleitos.detalhe(c, p2)["reemissoes_possiveis"] == ["reiteracao"]


def test_reiteracao_sem_os_textos_no_cadastro_nao_e_oferecida(cenario):
    """Sem `pleito_reiteracao` no cartas.yaml a carta nao monta; o rascunho travaria o ciclo (RascunhoAberto)."""
    c, ids = cenario
    _mtpar(c)
    original = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    _enviar(c, ids, original, D(2026, 6, 15))
    c.execute("UPDATE cadastro_geral SET valor=json_remove(valor, '$.pleito_reiteracao') WHERE chave='cartas'")
    c.commit()
    _aditivo(c, ids, "2026-08-01")
    assert pleitos.detalhe(c, original)["reemissoes_possiveis"] == ["cronograma"]
    with pytest.raises(ValueError, match="carta de reiteração ainda não está no cadastro"):
        pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "245", reemite_pleito_id=original,
                      reemissao="reiteracao")


def test_segunda_reiteracao_cita_o_pedido_original(cenario):
    c, ids = cenario
    _mtpar(c)
    original = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    _enviar(c, ids, original, D(2026, 6, 15))
    r1 = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "245", reemite_pleito_id=original,
                       reemissao="reiteracao", hoje=D(2026, 9, 1))
    _enviar(c, ids, r1, D(2026, 9, 1))
    r2 = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "300", reemite_pleito_id=r1,
                       reemissao="reiteracao", hoje=D(2026, 10, 30))
    assert pleitos.detalhe(c, r2)["anterior"]["id"] == r1                # a cadeia liga ao imediato
    corpo = pleitos.corpo_padrao(c, r2, D(2026, 10, 30))
    assert "CT/122/LT/2026, de 15/06/2026" in corpo and "137 dias" in corpo    # a carta cobra o pedido original


# --- issue #447: curva S conferida pelo conteudo e trocada sem reassinar a carta ---------------------

def _mudar_medicao(c, ids, valor=36000):
    c.execute("UPDATE medicoes SET valor_protocolado_centavos=? WHERE id=?", (valor, ids["medicao"])); c.commit()


def test_curva_s_que_mudou_aparece_no_que_falta_e_na_previa(cenario):
    """Issue #447 item 1: a curva fora dos dados de agora e' pendencia do pleito ("O que falta"), nao so' da previa."""
    c, ids = cenario
    pid = _pronto_para_enviar(c, ids)
    assert "curva_s" not in [x["codigo"] for x in pleitos.detalhe(c, pid)["pendencias"]]
    _mudar_medicao(c, ids)
    assert pleitos.CURVA_S_MUDOU in [x["mensagem"] for x in pleitos.detalhe(c, pid)["pendencias"]]
    assert [x["mensagem"] for x in pleitos.previa_envio(c, pid)["pendencias"]].count(pleitos.CURVA_S_MUDOU) == 1
    assert pleitos.CURVA_S_MUDOU.startswith("A curva S mudou desde a carta montada")
    assert pleitos.CURVA_S_FALTA.startswith("Curva S não anexada")


def test_curva_s_que_falta_aparece_no_que_falta(cenario):
    c, ids = cenario
    pid = _prazo(c, ids)
    pleitos.montar(c, ids["uid"], pid)
    _com_cronograma(c, ids)
    assert pleitos.CURVA_S_FALTA in [x["mensagem"] for x in pleitos.detalhe(c, pid)["pendencias"]]


def test_atualizar_curva_s_troca_a_curva_sem_apagar_a_carta_assinada(cenario):
    """Issue #447 item 2: medicao protocolada entre o montar e o envio; "Atualizar curva S" troca a curva, a carta
    montada e a assinada ficam, e o envio libera."""
    c, ids = cenario
    pid = _pronto_para_enviar(c, ids)
    antes = pleitos.detalhe(c, pid)
    velha = _curvas_s(c, pid)[0]["id"]
    _mudar_medicao(c, ids)
    pleitos.atualizar_curva_s(c, ids["uid"], pid)
    depois = pleitos.detalhe(c, pid)
    for k in ("situacao", "montado_arquivo", "montado_sha256", "assinado_arquivo", "assinado_sha256", "conferencia"):
        assert depois[k] == antes[k], k
    assert depois["situacao"] == "assinado"
    curvas = _curvas_s(c, pid)
    assert len(curvas) == 1 and curvas[0]["id"] != velha
    assert "curva_s" not in [x["codigo"] for x in depois["pendencias"]]
    pv = pleitos.previa_envio(c, pid)
    eid = pleitos.enviar(c, ids["usuario"], pid, pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                         justificativa="conferido, segue assim")
    assert "Curva S.xlsx" in [x[0] for x in c.execute("SELECT nome FROM envio_anexos WHERE envio_id=?", (eid,))]


def test_atualizar_curva_s_so_no_prazo_e_nao_depois_do_envio(cenario):
    c, ids = cenario
    reajuste_id = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    with pytest.raises(ValueError, match="pedido de prorrogação"):
        pleitos.atualizar_curva_s(c, ids["uid"], reajuste_id)
    pid = _pronto_para_enviar(c, ids)
    pv = pleitos.previa_envio(c, pid)
    pleitos.enviar(c, ids["usuario"], pid, pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                   justificativa="conferido, segue assim")
    with pytest.raises(ValueError, match="enviado"):
        pleitos.atualizar_curva_s(c, ids["uid"], pid)


def test_curva_s_conferida_pelo_conteudo_nao_pelos_bytes(cenario, monkeypatch):
    """Issue #447 item 3: outro sistema ou outra versao do openpyxl gera um zip de bytes diferentes com as mesmas
    celulas; a conferencia nao muda e montar de novo nao troca a curva."""
    import io
    import zipfile
    c, ids = cenario
    pid = _pronto_para_enviar(c, ids)
    curva = _curvas_s(c, pid)[0]
    original = arquivos.caminho_seguro(curva["arquivo"]).read_bytes()
    saida = io.BytesIO()                              # o mesmo xlsx, zip refeito com outra compressao e outro sistema
    with zipfile.ZipFile(io.BytesIO(original)) as o, zipfile.ZipFile(saida, "w", zipfile.ZIP_STORED) as d:
        for parte in o.infolist():
            info = zipfile.ZipInfo(parte.filename, date_time=(2030, 5, 5, 10, 0, 0))
            info.create_system = 0
            d.writestr(info, o.read(parte.filename))
    outro = saida.getvalue()
    assert outro != original
    from app import carta
    gerar = carta.curva_s_xlsx
    assert carta.ler_curva_s(outro) == carta.ler_curva_s(original)
    # o gerador de agora passa a dar estes outros bytes (deploy que trocou dependencia)
    monkeypatch.setattr(carta, "curva_s_xlsx", lambda linhas: outro)
    assert "curva_s" not in [x["codigo"] for x in pleitos.detalhe(c, pid)["pendencias"]]
    pleitos.montar(c, ids["uid"], pid)
    assert [a["id"] for a in _curvas_s(c, pid)] == [curva["id"]]
    # e o inverso: a curva anexada com os outros bytes, o gerador com os de antes
    monkeypatch.setattr(carta, "curva_s_xlsx", gerar)
    rel, sha = arquivos.gravar_bytes(pleitos.PASTA_CURVA_S, outro, "xlsx")
    c.execute("UPDATE pleito_anexos SET arquivo=?, sha256=? WHERE id=?", (rel, sha, curva["id"])); c.commit()
    assert "curva_s" not in [x["codigo"] for x in pleitos.detalhe(c, pid)["pendencias"]]


@pytest.mark.parametrize("estrago", ["ausente", "corrompido"])
def test_curva_s_com_arquivo_ausente_e_regravada_ao_atualizar_ou_montar(cenario, estrago):
    """Issue #447 item 4: o arquivo em `curvas/` sumiu (backup sem a pasta, #441) ou nao bate com o sha256; a previa
    avisa, o envio recusa e atualizar (ou montar) regrava a curva."""
    c, ids = cenario
    pid = _pronto_para_enviar(c, ids)
    for acao in ("atualizar", "montar"):
        caminho = arquivos.caminho_seguro(_curvas_s(c, pid)[0]["arquivo"])
        if estrago == "ausente":
            caminho.unlink()
        else:
            caminho.write_bytes(b"PK\x03\x04truncado")
        assert pleitos.CURVA_S_ILEGIVEL in [x["mensagem"] for x in pleitos.detalhe(c, pid)["pendencias"]]
        if acao == "atualizar":           # o envio recusa antes de ler os anexos do disco
            with pytest.raises(ValueError, match="sumiu ou está corrompido"):
                pleitos.enviar(c, ids["usuario"], pid, ["sinfra@orgao-a.exemplo.com.br"], [], "Assunto", "Corpo",
                               justificativa="segue assim mesmo")
        if acao == "atualizar":
            pleitos.atualizar_curva_s(c, ids["uid"], pid)
        else:
            pleitos.montar(c, ids["uid"], pid)
        assert "curva_s" not in [x["codigo"] for x in pleitos.detalhe(c, pid)["pendencias"]]
        assert arquivos.caminho_seguro(_curvas_s(c, pid)[0]["arquivo"]).exists()


def test_curva_s_que_some_sob_a_reserva_recusa_com_a_mensagem_e_destrava(cenario, monkeypatch):
    """Issue #447 (/code-review): o arquivo da curva some entre a primeira conferencia e a reserva; o envio recusa
    com a mensagem da curva (nao um erro de disco), nada sai e a reserva e' liberada."""
    from app import envio_reserva
    c, ids = cenario
    pid = _pronto_para_enviar(c, ids)
    caminho = arquivos.caminho_seguro(_curvas_s(c, pid)[0]["arquivo"])
    reservar = envio_reserva.reservar

    def reserva_e_apaga(*a, **k):
        reservar(*a, **k)
        caminho.unlink()

    monkeypatch.setattr(envio_reserva, "reservar", reserva_e_apaga)
    pv = pleitos.previa_envio(c, pid)
    with pytest.raises(ValueError, match="sumiu ou está corrompido"):
        pleitos.enviar(c, ids["usuario"], pid, pv["para"], pv["copia"], pv["assunto"], pv["corpo"],
                       justificativa="conferido, segue assim")
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    assert pleitos.detalhe(c, pid)["envio_reservado_em"] is None
