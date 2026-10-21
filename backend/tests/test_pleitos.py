"""Pleitos de reajuste, prazo e conclusao (bloco 7): criar, carta, assinado, envio."""
import datetime
import json
import pathlib

import pytest
import yaml

from app import arquivos, auth, cadastro_aplicar, correio, db, graph, leitura_pdf, medicoes, pleitos, reajuste, tempo
from tests.test_protocolo import _assinar, _contrato

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


def test_reiteracao_liga_ao_anterior_e_traz_a_carta_da_familia_b(cenario):
    c, ids = cenario
    _mtpar(c)
    original = pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "122")
    _enviar(c, ids, original, D(2026, 6, 15))
    assert pleitos.detalhe(c, original)["reemissoes_possiveis"] == ["reiteracao", "cronograma"]
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


def test_reiteracao_enviada_liga_os_dois_e_reabre_a_contagem_do_ciclo(cenario):
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
    assert pleitos.detalhe(c, pid)["reemissoes_possiveis"] == ["reiteracao", "cronograma"]
    k = reajuste.ciclos(c, ids["contrato"], D(2026, 11, 4))[0]
    assert (k["pleito"]["id"], k["dias"]) == (pid, 5)                  # o pedido sem resposta conta da reiteracao
    a = {x["tipo"]: x for x in reajuste.avisos(c, D(2026, 11, 4))}
    assert a["reajuste_apostilamento"]["dias"] == 5 and list(a["reajuste_apostilamento"]["publico"]) == ["operacao"]
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
    c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) VALUES (?, 'ap-1', "
              "'apostilamento_reajuste', '2026-09-01', ?)", (ids["contrato"], json.dumps({"ciclo": 2026})))
    c.commit()
    assert pleitos.detalhe(c, original)["reemissoes_possiveis"] == ["cronograma"]
    with pytest.raises(ValueError, match="apostilado"):
        pleitos.criar(c, ids["uid"], ids["contrato"], "reajuste", "245", reemite_pleito_id=original,
                      reemissao="reiteracao")
