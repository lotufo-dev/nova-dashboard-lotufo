"""Pagina Resumo das medicoes (issue #749): a etapa do ciclo da medicao de cada obra na competencia, as obras sem
medicao no mes e as medicoes abertas de meses anteriores. Dados sinteticos, com os nomes do `cadastro-exemplo/`."""
import datetime
import itertools
import json

import pytest

from app import auditoria, auth, db, fechamento, fila_medicoes, medicoes, resumo_medicoes
from tests.conftest import novo_contrato

HOJE = datetime.date(2026, 11, 16)
MES = "2026-10"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn()
    db.migrate(c)
    yield c
    c.close()


def _orgao(c, chave, nome, familia):
    return c.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES (?,?,?,'{}')", (chave, nome, familia)).lastrowid


def _obra(c, nome, orgao_id, estado="ativo", pct=10000, passos=None):
    return c.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos, estado, nome_curto, "
                     "orgao_id, percentual_direito_bp, passos_medicao) VALUES ('ÓRGÃO',?,?,0,?,?,?,?,?)",
                     (f"IC {nome}", nome, estado, nome, orgao_id, pct, passos)).lastrowid


def _medicao(c, cid, numero, estado, pedido=None, tipo="execucao", comp=MES, protocolo=None, **campos):
    cols = ["contrato_id", "numero", "tipo", "competencia", "estado", "valor_protocolado_centavos", *campos]
    vals = [cid, numero, tipo, comp, estado, pedido, *campos.values()]
    mid = c.execute(f"INSERT INTO medicoes ({', '.join(cols)}) VALUES ({','.join('?' * len(vals))})", vals).lastrowid
    for dia in protocolo or ():
        c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, ?, 'manual')", (mid, dia))
    return mid


@pytest.fixture
def cenario(conn):
    c = conn
    # familia sinfra, como no cadastro de exemplo: e' a que tem planilha/carta, e a sigla do grupo sai da familia
    secretaria = _orgao(c, "secretaria-exemplo", "Secretaria de Exemplo", "sinfra")
    companhia = _orgao(c, "companhia-exemplo", "Companhia de Exemplo", "mtpar")       # familia sem planilha/carta
    ids = {
        "propria": _obra(c, "Obra Própria", secretaria),
        "consorcio": _obra(c, "Obra Consórcio", secretaria, pct=3333),
        "companhia": _obra(c, "Obra da Companhia", companhia),
        "sem_envio": _obra(c, "Obra Sem Envio", secretaria, passos='["planilha","analise","espelhos","notas","pagamento"]'),
        "parada": _obra(c, "Obra Parada", secretaria),
        "sem_fluxo": _obra(c, "Obra Sem Fluxo", secretaria, passos="[]"),
        "suspensa": _obra(c, "Obra Suspensa", secretaria, estado="suspenso"),
    }
    # Propria: a execucao protocolada, com todas as datas; o protocolo reapresentado nao muda a data (vale o primeiro)
    ids["p12"] = _medicao(c, ids["propria"], 12, "protocolada", 100_001, planilha_enviada_em="2026-11-03",
                          atestado_em="2026-11-06", valor_atestado_centavos=99_999, nota_emitida_em="2026-11-09",
                          protocolo=("2026-11-10", "2026-11-13"))
    # Consorcio (cota de 33,33%): em analise, so' o pedido; centavo impar
    ids["k7"] = _medicao(c, ids["consorcio"], 7, "planilha_enviada", 1_000_001, planilha_enviada_em="2026-11-05")
    # Companhia: sem planilha/carta, a medicao nasce no espelho
    ids["c3"] = _medicao(c, ids["companhia"], 3, "espelho_gerado", 50_000)
    # Sem Envio: a obra nao tem o passo "Envio da nota"; a nota emitida espera o pagamento
    ids["s4"] = _medicao(c, ids["sem_envio"], 4, "nota_emitida", 70_000, planilha_enviada_em="2026-11-02",
                         atestado_em="2026-11-04", valor_atestado_centavos=70_000, nota_emitida_em="2026-11-08")
    # Parada: so' a prevista do mes (nao conta) e a 5ª, de setembro, ainda protocolada
    _medicao(c, ids["parada"], 6, "prevista")
    ids["x5"] = _medicao(c, ids["parada"], 5, "protocolada", 20_000, comp="2026-09", protocolo=("2026-10-20",))
    # meses anteriores: uma recebida (fora), uma cancelada (fora) e uma em analise de agosto
    _medicao(c, ids["propria"], 11, "recebida", 5_000, comp="2026-09", recebida_em="2026-10-30")
    _medicao(c, ids["propria"], 10, "cancelada", 5_000, comp="2026-08")
    ids["k5"] = _medicao(c, ids["consorcio"], 5, "planilha_enviada", 3_000, comp="2026-08", planilha_enviada_em="2026-09-04")
    c.commit()
    return ids


def _linha(r, obra):
    return next(x for g in r["grupos"] for x in g["linhas"] if x["obra"] == obra)


def _etapas(linha):
    return [(e["etapa"], e["situacao"], e["data"]) for e in linha["etapas"]]


def test_competencia_padrao_e_a_em_trabalho(conn, cenario):
    r = resumo_medicoes.resumo(conn, HOJE)
    assert (r["mes"], r["em_trabalho"], r["hoje"]) == ("2026-10", "2026-10", "2026-11-16")
    assert resumo_medicoes.resumo(conn, HOJE, mes="2026-09")["em_trabalho"] == "2026-10"


def test_linha_por_obra_agrupada_por_contratante_com_as_datas_registradas(conn, cenario):
    ids = cenario
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    assert [(g["contratante"], [x["obra"] for x in g["linhas"]]) for g in r["grupos"]] == [
        ("Companhia de Exemplo", ["Obra da Companhia"]),
        ("SINFRA", ["Obra Consórcio", "Obra Própria", "Obra Sem Envio"])]
    p = _linha(r, "Obra Própria")
    assert (p["medicao_id"], p["titulo"], p["etapa"], p["competencia"]) == (ids["p12"], "12ª Medição", "protocolado", MES)
    # cada etapa alcancada com a data do evento; a do protocolo e' a do PRIMEIRO; a que falta vem sem data
    assert _etapas(p) == [("em_analise", "feito", "2026-11-03"), ("boletim", "feito", "2026-11-06"),
                          ("nota", "feito", "2026-11-09"), ("protocolado", "atual", "2026-11-10"), ("recebido", "futuro", None)]
    assert p["valor_centavos"] == 99_999        # o medido: o aprovado e, sem boletim, o pedido


def test_valor_na_cota_com_arredondamento_unico(conn, cenario):
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    k = _linha(r, "Obra Consórcio")
    # 1.000.001 centavos x 33,33% = 333.300,3333: arredonda uma vez, para 333.300
    assert k["valor_centavos"] == 333_300 and k["etapa"] == "em_analise"
    assert _etapas(k)[0] == ("em_analise", "atual", "2026-11-05")
    assert {e["situacao"] for e in k["etapas"][1:]} == {"futuro"}


def test_obra_so_tem_as_etapas_do_fluxo_dela(conn, cenario):
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    # familia sem planilha/carta: nao existe "em analise"; a medicao no espelho esta' na etapa do boletim, sem data
    c = _linha(r, "Obra da Companhia")
    assert _etapas(c) == [("boletim", "atual", None), ("nota", "futuro", None), ("protocolado", "futuro", None),
                          ("recebido", "futuro", None)]
    # `passos_medicao` sem o envio da nota: nao existe "protocolado"; a nota emitida fica na etapa da nota
    s = _linha(r, "Obra Sem Envio")
    assert [e["etapa"] for e in s["etapas"]] == ["em_analise", "boletim", "nota", "recebido"]
    assert s["etapa"] == "nota" and _etapas(s)[2] == ("nota", "atual", "2026-11-08")
    assert resumo_medicoes.etapas_do_fluxo((1, 2, 3, 4, 5, 6)) == resumo_medicoes.ETAPAS


ESTADOS_COM_ETAPA = ("planilha_gerada", "planilha_enviada", "boletim_recebido", "espelho_gerado", "espelho_enviado",
                     "nota_emitida", "protocolada", "nf_emitida", "recebida")


def test_etapa_da_vez_sai_do_estado():
    da_vez = resumo_medicoes.etapa_da_vez
    assert [da_vez(e) for e in ESTADOS_COM_ETAPA] == [
        "antes", "em_analise", "boletim", "boletim", "boletim", "nota", "protocolado", "protocolado", "recebido"]
    assert [da_vez(e) for e in ("prevista", "cancelada", "desistida")] == [None, None, None]
    # todo estado da medicao tem etapa ou esta' fora da pagina: estado novo sem decisao quebra aqui
    assert set(medicoes.TRANSICOES) == {*ESTADOS_COM_ETAPA, "prevista", "cancelada", "desistida"}


def test_os_passos_so_dizem_quais_etapas_a_obra_tem():
    """Segunda revisao, achado 3: em nenhuma lista de `passos_medicao` que o cadastro aceita a medicao cai numa etapa
    que nao e' a do estado dela; a linha tem as etapas da obra e a etapa em que a medicao esta'."""
    nomes = medicoes.CHAVES_PASSO
    numero = {nome: i + 1 for i, nome in enumerate(nomes)}
    # as listas que `cadastro_arquivos._passos_medicao` aceita: com pagamento, e analise so' com planilha
    listas = [c for n in range(len(nomes)) for c in itertools.combinations(nomes, n + 1)
              if "pagamento" in c and ("analise" not in c or "planilha" in c)]
    assert len(listas) == 24
    for lista, estado in itertools.product(listas, ESTADOS_COM_ETAPA):
        passos = tuple(numero[nome] for nome in lista)
        da_obra = resumo_medicoes.etapas_do_fluxo(passos)
        da_linha = resumo_medicoes.etapas_da_medicao(estado, passos)
        da_vez = resumo_medicoes.etapa_da_vez(estado)
        assert set(da_linha) == set(da_obra) | ({da_vez} - {"antes"}), (lista, estado)
        assert list(da_linha) == [e for e in resumo_medicoes.ETAPAS if e in da_linha]


def _obra_com_lista(c, orgao_id, nome, lista):
    assert not set(lista) - set(medicoes.CHAVES_PASSO)
    return _obra(c, nome, orgao_id, passos=json.dumps(lista))


def test_lista_sem_analise_a_planilha_enviada_esta_em_analise_e_nao_no_boletim(conn, cenario):
    """Achado 3: na obra cuja lista nao tem `analise`, a planilha/carta enviada e ainda nao aprovada nao aparece no
    boletim. A linha dela mostra a etapa do estado; a medicao da mesma obra que ja' passou dali nao ganha a etapa."""
    c = conn
    orgao = c.execute("SELECT id FROM orgaos WHERE chave='secretaria-exemplo'").fetchone()[0]
    cid = _obra_com_lista(c, orgao, "Obra Sem Análise", ["planilha", "espelhos", "notas", "envio_nota", "pagamento"])
    enviada = _medicao(c, cid, 2, "planilha_enviada", 80_001, planilha_enviada_em="2026-11-05")
    aprovada = _medicao(c, cid, 1, "boletim_recebido", 70_001, comp="2026-09", planilha_enviada_em="2026-10-05",
                        atestado_em="2026-10-09", valor_atestado_centavos=70_001)
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    x = _linha(r, "Obra Sem Análise")
    assert (x["medicao_id"], x["etapa"]) == (enviada, "em_analise")
    assert _etapas(x) == [("em_analise", "atual", "2026-11-05"), ("boletim", "futuro", None), ("nota", "futuro", None),
                          ("protocolado", "futuro", None), ("recebido", "futuro", None)]
    [y] = [y for g in r["anteriores"] for y in g["linhas"] if y["medicao_id"] == aprovada]
    assert y["etapa"] == "boletim" and _etapas(y) == [
        ("boletim", "atual", "2026-10-09"), ("nota", "futuro", None), ("protocolado", "futuro", None), ("recebido", "futuro", None)]


def test_lista_sem_notas_a_medicao_aprovada_esta_no_boletim_e_nao_na_nota(conn, cenario):
    """Achado 3: sem `notas` na lista (e so' com `pagamento`), boletim recebido e espelho enviado nao aparecem na
    etapa da nota, que nao foi emitida."""
    c = conn
    orgao = c.execute("SELECT id FROM orgaos WHERE chave='secretaria-exemplo'").fetchone()[0]
    sem_notas = _obra_com_lista(c, orgao, "Obra Sem Notas", ["planilha", "analise", "espelhos", "envio_nota", "pagamento"])
    so_pagamento = _obra_com_lista(c, orgao, "Obra Só Pagamento", ["pagamento"])
    _medicao(c, sem_notas, 1, "espelho_enviado", 60_001, planilha_enviada_em="2026-11-03", atestado_em="2026-11-06",
             valor_atestado_centavos=60_001)
    _medicao(c, so_pagamento, 1, "boletim_recebido", 50_001, planilha_enviada_em="2026-11-03", atestado_em="2026-11-07",
             valor_atestado_centavos=50_001)
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    a = _linha(r, "Obra Sem Notas")
    assert a["etapa"] == "boletim" and _etapas(a) == [
        ("em_analise", "feito", "2026-11-03"), ("boletim", "atual", "2026-11-06"), ("nota", "futuro", None),
        ("protocolado", "futuro", None), ("recebido", "futuro", None)]
    # so' com pagamento, a obra tem nota e recebido; a medicao aprovada mostra o boletim em que esta', sem a nota feita
    b = _linha(r, "Obra Só Pagamento")
    assert b["etapa"] == "boletim" and _etapas(b) == [
        ("boletim", "atual", "2026-11-07"), ("nota", "futuro", None), ("recebido", "futuro", None)]


def test_protocolo_registrado_na_obra_sem_envio_da_nota_aparece_como_protocolado(conn, cenario):
    """A obra sem o passo "Envio da nota" nao tem a etapa do protocolado; a medicao dela que tem protocolo registrado
    (estado protocolada) mostra a etapa em que esta'. A outra medicao da obra continua sem ela."""
    c, ids = conn, cenario
    prot = _medicao(c, ids["sem_envio"], 3, "protocolada", 60_001, comp="2026-09", nota_emitida_em="2026-10-06",
                    protocolo=("2026-10-08",))
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    [x] = [x for g in r["anteriores"] for x in g["linhas"] if x["medicao_id"] == prot]
    assert x["etapa"] == "protocolado" and [e["etapa"] for e in x["etapas"]] == ["boletim", "nota", "protocolado", "recebido"]
    assert [e["etapa"] for e in _linha(r, "Obra Sem Envio")["etapas"]] == ["em_analise", "boletim", "nota", "recebido"]


# --- segunda revisao, achado 1: a etapa anterior so' e' "feita" com o registro do evento -------------------------

def test_protocolada_direto_da_prevista_nao_tem_etapa_feita_sem_registro(conn, cenario):
    """Obra com planilha/carta (regra de espelho ativa), medicao protocolada direto da prevista, pelo protocolo de
    verdade: a planilha nao foi enviada, nao houve boletim e a nota nao foi emitida. Nenhuma das tres aparece feita."""
    c, ids = conn, cenario
    c.execute("UPDATE certidao_tipos SET aplicavel_por_padrao=0")
    c.execute("INSERT INTO espelho_regras (contrato_id, situacao, regra, modelos, sha256) VALUES (?,'ativa','{}','{}','x')",
              (ids["parada"],))
    c.commit()
    uid = auth.criar_usuario(c, "Engenharia Exemplo", "engenharia@exemplo.com.br", "senha-forte-123", "engenharia")
    mid = medicoes.criar(c, uid, {"contrato_id": ids["parada"], "numero": 8, "tipo": "execucao", "competencia": MES})
    medicoes.definir_valor(c, uid, mid, "protocolado", 45_001, "manual")
    medicoes.registrar_protocolo(c, uid, mid, "2026-11-12", None, None, "manual")
    assert medicoes.detalhe(c, mid)["estado"] == "protocolada"
    x = _linha(resumo_medicoes.resumo(conn, HOJE, mes=MES), "Obra Parada")
    assert x["etapa"] == "protocolado" and _etapas(x) == [
        ("em_analise", "sem_registro", None), ("boletim", "sem_registro", None), ("nota", "sem_registro", None),
        ("protocolado", "atual", "2026-11-12"), ("recebido", "futuro", None)]
    # recebida: o recebimento e' o estado; as anteriores continuam sem registro
    medicoes.mudar_estado(c, uid, mid, "recebida", None, "2026-11-15")
    x = _linha(resumo_medicoes.resumo(conn, HOJE, mes=MES), "Obra Parada")
    assert _etapas(x) == [
        ("em_analise", "sem_registro", None), ("boletim", "sem_registro", None), ("nota", "sem_registro", None),
        ("protocolado", "feito", "2026-11-12"), ("recebido", "feito", "2026-11-15")]


def test_medicao_que_seguiu_sem_boletim_nao_tem_boletim_feito(conn, cenario):
    """Planilha/carta enviada, espelho e nota, sem boletim: o boletim fica sem registro; o envio e a nota, feitos."""
    c, ids = conn, cenario
    _medicao(c, ids["parada"], 8, "nota_emitida", 45_001, planilha_enviada_em="2026-11-03", nota_emitida_em="2026-11-10")
    c.commit()
    x = _linha(resumo_medicoes.resumo(conn, HOJE, mes=MES), "Obra Parada")
    assert x["etapa"] == "nota" and _etapas(x) == [
        ("em_analise", "feito", "2026-11-03"), ("boletim", "sem_registro", None), ("nota", "atual", "2026-11-10"),
        ("protocolado", "futuro", None), ("recebido", "futuro", None)]
    # o valor aprovado gravado sem a data do boletim e' registro do boletim: feito, sem data (o traco na tela)
    c.execute("UPDATE medicoes SET valor_atestado_centavos=44_001 WHERE contrato_id=? AND numero=8", (ids["parada"],))
    c.commit()
    assert _etapas(_linha(resumo_medicoes.resumo(conn, HOJE, mes=MES), "Obra Parada"))[1] == ("boletim", "feito", None)


def test_etapa_da_vez_sem_data_e_etapa_que_falta_nao_viram_sem_registro(conn, cenario):
    # a etapa atual vem do estado (sem data, o traco); `sem_registro` e' so' de etapa que ficou para tras
    c3 = _linha(resumo_medicoes.resumo(conn, HOJE, mes=MES), "Obra da Companhia")
    assert {e["situacao"] for e in c3["etapas"]} == {"atual", "futuro"}


def test_planilha_gerada_ainda_nao_entrou_no_ciclo(conn, cenario):
    c, ids = conn, cenario
    _medicao(c, ids["parada"], 7, "planilha_gerada", 9_000)
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    x = _linha(r, "Obra Parada")
    assert x["etapa"] == "antes" and {e["situacao"] for e in x["etapas"]} == {"futuro"}
    assert all(e["data"] is None for e in x["etapas"])
    assert "Obra Parada" not in [o["obra"] for o in r["sem_medicao"]]
    # a medicao ainda nao enviada ao orgao nao mede (`medicoes.ESTADOS_NO_MEDIDO`): a linha existe, sem valor
    assert x["valor_centavos"] is None
    assert next(e for e in r["etapas"] if e["etapa"] == "antes") == {"etapa": "antes", "medicoes": 1, "valor_centavos": 0}


def _medido_do_fechamento(conn, mes):
    [m] = [m for m in fechamento.fechamento(conn)["meses"] if m["competencia"] == mes]
    return m["medido_centavos"]


def test_medido_do_mes_fecha_com_o_do_fechamento(conn, cenario):
    """A soma do medido das linhas da competencia e' o medido do mes no Fechamento: a mesma regra (a medicao enviada
    ao orgao, o aprovado e, sem boletim, o pedido, na cota), com a planilha/carta so' gerada fora das duas."""
    c, ids = conn, cenario
    _medicao(c, ids["parada"], 7, "planilha_gerada", 9_001)
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    soma = sum(x["valor_centavos"] or 0 for g in r["grupos"] for x in g["linhas"])
    assert soma == _medido_do_fechamento(conn, MES) == 99_999 + 333_300 + 50_000 + 70_000
    assert sum(e["valor_centavos"] for e in r["etapas"]) == soma


@pytest.mark.parametrize("reajuste, cota_reajuste", [(500_001, 166_650), (-500_002, -166_651)])
def test_par_execucao_e_reajuste_em_consorcio_fecha_ao_centavo_com_o_fechamento(conn, cenario, reajuste, cota_reajuste):
    """Segunda revisao, achado 5: o par na mesma linha, em consorcio (33,33%), com centavo impar nas duas cotas e com o
    reajuste negativo, em estado que o sistema produz (as duas com o espelho enviado). Cada cota arredonda uma vez e a
    linha e' a soma das duas, como no Fechamento."""
    c, ids = conn, cenario
    # a execucao da 7ª sai da analise com o boletim (aprovado de centavo impar) e o espelho enviado; o reajuste, junto
    c.execute("UPDATE medicoes SET estado='espelho_enviado', atestado_em='2026-11-08', valor_atestado_centavos=1_000_002 "
              "WHERE id=?", (ids["k7"],))
    r7 = _medicao(c, ids["consorcio"], 7, "espelho_enviado", reajuste, tipo="reajuste", atestado_em="2026-11-08",
                  valor_atestado_centavos=reajuste)
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    k = _linha(r, "Obra Consórcio")
    # 1.000.002 x 33,33% = 333.300,67 -> 333.301; 500.001 x 33,33% = 166.650,33 -> 166.650; -500.002 -> -166.651
    assert (k["titulo"], k["medicao_ids"], k["etapa"]) == ("7ª Medição + Reajuste", [ids["k7"], r7], "boletim")
    assert k["valor_centavos"] == 333_301 + cota_reajuste
    soma = sum(x["valor_centavos"] or 0 for g in r["grupos"] for x in g["linhas"])
    assert soma == _medido_do_fechamento(conn, MES) == 99_999 + 333_301 + cota_reajuste + 50_000 + 70_000
    assert next(e for e in r["etapas"] if e["etapa"] == "boletim") == {
        "etapa": "boletim", "medicoes": 3, "valor_centavos": 333_301 + cota_reajuste + 50_000}


def test_medicao_de_projeto_tem_linha_valor_e_conta_como_ultima(conn, cenario):
    """#742: a medicao de projeto entra no medido. Aqui ela tem a linha e o valor dela e, na obra sem medicao no mes,
    e' a ultima medicao."""
    c, ids = conn, cenario
    proj = _medicao(c, ids["propria"], 1, "planilha_enviada", 40_001, tipo="projeto", planilha_enviada_em="2026-11-04")
    antigo = _medicao(c, ids["parada"], 2, "recebida", 10_000, tipo="projeto", comp="2026-09", recebida_em="2026-10-28")
    c.execute("UPDATE medicoes SET estado='recebida', recebida_em='2026-10-27' WHERE id=?", (ids["x5"],))
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    linhas = [x for g in r["grupos"] for x in g["linhas"] if x["obra"] == "Obra Própria"]
    assert [(x["medicao_id"], x["tipo"], x["etapa"], x["valor_centavos"]) for x in linhas] == [
        (ids["p12"], "execucao", "protocolado", 99_999), (proj, "projeto", "em_analise", 40_001)]
    assert next(e for e in r["etapas"] if e["etapa"] == "em_analise") == {
        "etapa": "em_analise", "medicoes": 2, "valor_centavos": 333_300 + 40_001}
    # execucao e projeto na mesma competencia: a de maior numero e' a ultima (a 5ª), seja qual for o tipo
    [parada] = r["sem_medicao"]
    assert parada["ultima"]["medicao_id"] == ids["x5"]
    c.execute("UPDATE medicoes SET competencia='2026-08' WHERE id=?", (ids["x5"],))
    c.commit()
    [parada] = resumo_medicoes.resumo(conn, HOJE, mes=MES)["sem_medicao"]
    assert parada["ultima"] == {"medicao_id": antigo, "titulo": medicoes.titulo({"numero": 2, "tipo": "projeto"}),
                                "competencia": "2026-09", "etapa": "recebido"}


def test_obra_sem_envio_da_nota_vai_da_nota_ao_recebido_pela_baixa(conn, cenario):
    """#743: na obra sem o passo "Envio da nota", a medicao com nota emitida e' recebida sem protocolo. Na pagina ela
    sai da etapa da nota para a do recebido, sem a etapa do protocolado, e deixa os meses anteriores em aberto."""
    c, ids = conn, cenario
    uid = auth.criar_usuario(c, "Administrador Exemplo", "admin@exemplo.com.br", "senha-forte-123", "admin")
    antiga = _medicao(c, ids["sem_envio"], 3, "nota_emitida", 60_001, comp="2026-09", nota_emitida_em="2026-10-06")
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    [aberta] = [x for g in r["anteriores"] for x in g["linhas"] if x["medicao_id"] == antiga]
    assert _etapas(aberta) == [("boletim", "sem_registro", None), ("nota", "atual", "2026-10-06"), ("recebido", "futuro", None)]
    for mid, dia in ((ids["s4"], "2026-11-13"), (antiga, "2026-11-12")):
        assert "recebida" in medicoes.alcancaveis(c, medicoes.detalhe(c, mid))
        medicoes.mudar_estado(c, uid, mid, "recebida", "baixa conferida no extrato", dia, origem="manual")
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    s = _linha(r, "Obra Sem Envio")
    assert s["etapa"] == "recebido" and _etapas(s) == [
        ("em_analise", "feito", "2026-11-02"), ("boletim", "feito", "2026-11-04"), ("nota", "feito", "2026-11-08"),
        ("recebido", "feito", "2026-11-13")]
    assert antiga not in [x["medicao_id"] for g in r["anteriores"] for x in g["linhas"]]
    assert next(e for e in r["etapas"] if e["etapa"] == "recebido") == {"etapa": "recebido", "medicoes": 1, "valor_centavos": 70_000}
    # na obra com o passo, a nota emitida continua sem caminho para recebida: fica na etapa da nota ate' o protocolo
    outra = _medicao(c, ids["propria"], 13, "nota_emitida", 30_000, nota_emitida_em="2026-11-12")
    c.commit()
    assert "recebida" not in medicoes.alcancaveis(c, medicoes.detalhe(c, outra))


def test_recebida_tem_todas_as_etapas_feitas(conn, cenario):
    c, ids = conn, cenario
    c.execute("UPDATE medicoes SET estado='recebida', recebida_em='2026-11-14' WHERE id=?", (ids["p12"],))
    c.commit()
    p = _linha(resumo_medicoes.resumo(conn, HOJE, mes=MES), "Obra Própria")
    assert p["etapa"] == "recebido" and {e["situacao"] for e in p["etapas"]} == {"feito"}
    assert _etapas(p)[-1] == ("recebido", "feito", "2026-11-14")


def test_execucao_e_reajuste_na_mesma_etapa_sao_uma_linha_e_em_etapas_diferentes_sao_duas(conn, cenario):
    c, ids = conn, cenario
    r12 = _medicao(c, ids["propria"], 12, "protocolada", 1_001, tipo="reajuste", atestado_em="2026-11-06",
                   valor_atestado_centavos=1_001, nota_emitida_em="2026-11-11", protocolo=("2026-11-12",))
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    p = _linha(r, "Obra Própria")
    assert p["titulo"] == "12ª Medição + Reajuste" and p["medicao_ids"] == [ids["p12"], r12]
    assert p["valor_centavos"] == 99_999 + 1_001
    # a data de cada etapa e' a da ultima das duas a chegar nela
    assert _etapas(p)[2:4] == [("nota", "feito", "2026-11-11"), ("protocolado", "atual", "2026-11-12")]
    assert next(e for e in r["etapas"] if e["etapa"] == "protocolado")["medicoes"] == 2
    c.execute("UPDATE medicoes SET estado='nota_emitida' WHERE id=?", (r12,))
    c.commit()
    linhas = [x for g in resumo_medicoes.resumo(conn, HOJE, mes=MES)["grupos"] for x in g["linhas"] if x["obra"] == "Obra Própria"]
    assert [(x["titulo"], x["etapa"]) for x in linhas] == [("12ª Medição", "protocolado"), ("Reajuste da 12ª Medição", "nota")]


def test_execucao_e_reajuste_so_se_juntam_quando_dizem_o_mesmo_de_cada_etapa(conn, cenario):
    """Na mesma etapa, mas a execucao com o boletim registrado e o reajuste sem: duas linhas, para a linha conjunta
    nao dizer do reajuste o boletim que so' a execucao tem."""
    c, ids = conn, cenario
    _medicao(c, ids["propria"], 12, "protocolada", 1_001, tipo="reajuste", nota_emitida_em="2026-11-11", protocolo=("2026-11-12",))
    c.commit()
    linhas = [x for g in resumo_medicoes.resumo(conn, HOJE, mes=MES)["grupos"] for x in g["linhas"] if x["obra"] == "Obra Própria"]
    assert [(x["titulo"], x["etapa"], len(x["medicao_ids"])) for x in linhas] == [
        ("12ª Medição", "protocolado", 1), ("Reajuste da 12ª Medição", "protocolado", 1)]
    assert _etapas(linhas[1]) == [("boletim", "sem_registro", None), ("nota", "feito", "2026-11-11"),
                                  ("protocolado", "atual", "2026-11-12"), ("recebido", "futuro", None)]


def test_contagem_por_etapa_soma_as_linhas(conn, cenario):
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    assert [(e["etapa"], e["medicoes"], e["valor_centavos"]) for e in r["etapas"]] == [
        ("antes", 0, 0), ("em_analise", 1, 333_300), ("boletim", 1, 50_000), ("nota", 1, 70_000),
        ("protocolado", 1, 99_999), ("recebido", 0, 0)]
    linhas = [x for g in r["grupos"] for x in g["linhas"]]
    assert sum(e["valor_centavos"] for e in r["etapas"]) == sum(x["valor_centavos"] for x in linhas)
    assert sum(e["medicoes"] for e in r["etapas"]) == sum(len(x["medicao_ids"]) for x in linhas)


def test_obras_sem_medicao_no_mes(conn, cenario):
    ids = cenario
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    # so' a prevista nao conta; a suspensa e a sem fluxo de medicao no cadastro ficam fora
    assert r["sem_medicao"] == [{"contrato_id": ids["parada"], "obra": "Obra Parada", "contratante": "SINFRA",
                                 "ultima": {"medicao_id": ids["x5"], "titulo": "5ª Medição", "competencia": "2026-09",
                                            "etapa": "protocolado"}}]
    # em encerramento e sem medicao na competencia: fora
    conn.execute("UPDATE contratos SET encerramento_iniciado_em='2026-11-01' WHERE id=?", (ids["parada"],))
    conn.commit()
    assert resumo_medicoes.resumo(conn, HOJE, mes=MES)["sem_medicao"] == []
    # mes sem medicao nenhuma: todas as ativas com fluxo, e a obra nunca medida vem sem "ultima"
    futuro = resumo_medicoes.resumo(conn, HOJE, mes="2027-01")
    assert futuro["grupos"] == [] and [o["obra"] for o in futuro["sem_medicao"]] == [
        "Obra Consórcio", "Obra da Companhia", "Obra Própria", "Obra Sem Envio"]
    _obra(conn, "Obra Nova", None)
    conn.commit()
    nova = next(o for o in resumo_medicoes.resumo(conn, HOJE, mes=MES)["sem_medicao"] if o["obra"] == "Obra Nova")
    assert nova["ultima"] is None and nova["contratante"] == "ÓRGÃO"      # sem orgao no cadastro: o texto do contrato


def test_meses_anteriores_em_aberto(conn, cenario):
    ids = cenario
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    # da competencia mais antiga para a mais nova; a recebida e a cancelada nao entram
    assert [(g["competencia"], [(x["obra"], x["medicao_id"], x["etapa"]) for x in g["linhas"]]) for g in r["anteriores"]] == [
        ("2026-08", [("Obra Consórcio", ids["k5"], "em_analise")]),
        ("2026-09", [("Obra Parada", ids["x5"], "protocolado")])]
    x5 = r["anteriores"][1]["linhas"][0]
    assert _etapas(x5)[-2] == ("protocolado", "atual", "2026-10-20") and x5["valor_centavos"] == 20_000
    # olhando setembro, a de setembro e' do mes e so' a de agosto e' anterior
    setembro = resumo_medicoes.resumo(conn, HOJE, mes="2026-09")
    assert [g["competencia"] for g in setembro["anteriores"]] == ["2026-08"]
    assert _linha(setembro, "Obra Parada")["medicao_id"] == ids["x5"]


def test_atualizacao_e_o_ultimo_lancamento_de_uma_pessoa_e_a_ultima_leitura_do_rm(conn, cenario):
    c, ids = conn, cenario
    assert resumo_medicoes.resumo(conn, HOJE, mes=MES)["atualizacao"] == {"ultimo_lancamento": None, "rm_lido_em": None}
    uid = auth.criar_usuario(c, "Engenharia Exemplo", "engenharia@exemplo.com.br", "senha-forte-123", "engenharia")
    with db.mutacao(c):
        auditoria.registrar(c, uid, "medicao.estado", "medicao", ids["p12"])
        auditoria.registrar(c, None, "medicao.estado", "medicao", ids["k7"])      # pelo sistema: nao e' lancamento
    c.execute("UPDATE audit_log SET criado_em='2026-11-14 18:40:00' WHERE usuario_id IS NOT NULL AND entidade='medicao'")
    c.execute("UPDATE audit_log SET criado_em='2026-11-15 09:00:00' WHERE usuario_id IS NULL AND entidade='medicao'")
    c.execute("INSERT INTO rm_sincronizacoes (disparo, estado, terminado_em) VALUES ('agendado','success','2026-11-16 11:00:00')")
    c.execute("INSERT INTO rm_sincronizacoes (disparo, estado, terminado_em) VALUES ('agendado','failed','2026-11-16 12:00:00')")
    c.commit()
    assert resumo_medicoes.resumo(conn, HOJE, mes=MES)["atualizacao"] == {
        "ultimo_lancamento": "2026-11-14 18:40:00", "rm_lido_em": "2026-11-16 11:00:00"}


# --- issue #805: o quadro por etapa (medido do mes, mesma altura, parada ha, diferenca, filtro) -----------------

def test_medido_do_mes_e_o_do_fechamento_e_fecha_com_a_soma_das_etapas(conn, cenario):
    """O medido do mes e' o numero do Fechamento, e as cinco etapas somam esse numero: a pagina pode mostrar as
    etapas ao lado dele. As referencias sao o mesmo medido no mes anterior e no mesmo mes do ano anterior."""
    c, ids = conn, cenario
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    assert r["medido"]["valor_centavos"] == _medido_do_fechamento(conn, MES) == sum(e["valor_centavos"] for e in r["etapas"])
    # setembro: a 5ª da Obra Parada (20.000) e a 11ª recebida da Obra Propria (5.000); outubro de 2025 nao teve medicao
    assert r["medido"]["mes_anterior"] == {"competencia": "2026-09", "valor_centavos": 25_000}
    assert r["medido"]["mes_anterior"]["valor_centavos"] == _medido_do_fechamento(conn, "2026-09")
    assert r["medido"]["ano_anterior"] is None
    _medicao(c, ids["propria"], 1, "recebida", 61_000, comp="2025-10", recebida_em="2025-12-01")
    c.commit()
    assert resumo_medicoes.resumo(conn, HOJE, mes=MES)["medido"]["ano_anterior"] == {"competencia": "2025-10", "valor_centavos": 61_000}


def test_medido_sem_referencia_no_mes_em_curso_e_antes_do_primeiro_ano(conn, cenario):
    c, ids = conn, cenario
    _medicao(c, ids["propria"], 14, "planilha_enviada", 7_000, comp="2026-11", planilha_enviada_em="2026-11-12")
    _medicao(c, ids["propria"], 2, "recebida", 8_000, comp="2025-01", recebida_em="2025-03-01")
    _medicao(c, ids["propria"], 1, "recebida", 9_000, comp="2024-12", recebida_em="2025-02-01")
    c.commit()
    # novembro ainda recebe medicao: contra outubro inteiro diria sempre "caiu"
    em_curso = resumo_medicoes.resumo(conn, HOJE, mes="2026-11")["medido"]
    assert em_curso == {"valor_centavos": 7_000, "mes_anterior": None, "ano_anterior": None}
    # dezembro de 2024 e' anterior ao primeiro ano das telas da diretoria: nao serve de referencia
    janeiro = resumo_medicoes.resumo(conn, HOJE, mes="2025-01")
    assert janeiro["medido"] == {"valor_centavos": 8_000, "mes_anterior": None, "ano_anterior": None}
    assert janeiro["mesma_altura"] is None


def test_um_mes_antes_no_mesmo_dia_ou_no_ultimo_dia_do_mes():
    antes = resumo_medicoes._um_mes_antes
    assert antes(datetime.date(2026, 11, 18)) == datetime.date(2026, 10, 18)
    assert antes(datetime.date(2026, 1, 5)) == datetime.date(2025, 12, 5)
    assert antes(datetime.date(2026, 3, 31)) == datetime.date(2026, 2, 28)
    assert antes(datetime.date(2028, 3, 30)) == datetime.date(2028, 2, 29)
    assert antes(datetime.date(2026, 7, 31)) == datetime.date(2026, 6, 30)


def test_mesma_altura_e_o_retrato_da_competencia_anterior_um_mes_antes_pelas_datas_dos_eventos(conn, cenario):
    """Hoje e' 16/11 e a competencia e' outubro: a referencia e' o que as medicoes de setembro tinham no protocolado e
    no recebido em 16/10. Cada medicao entra pela data do evento, com o medido de hoje."""
    c, ids = conn, cenario
    # a 11ª recebida da Obra Propria (cenario) nao tem protocolo registrado: ganha um, para a referencia ter lastro
    c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) SELECT id, '2026-10-01', 'manual' FROM medicoes "
              "WHERE contrato_id=? AND numero=11", (ids["propria"],))
    # recebida antes de 16/10: estava no recebido; recebida depois e protocolada antes: estava no protocolado
    _medicao(c, ids["consorcio"], 6, "recebida", 300_000, comp="2026-09", recebida_em="2026-10-14", protocolo=("2026-10-05",))
    _medicao(c, ids["companhia"], 2, "recebida", 40_000, comp="2026-09", recebida_em="2026-10-25", protocolo=("2026-10-12",))
    # protocolada ate' 16/10 e ainda nao recebida: no protocolado; a obra sem o envio da nota recebe sem protocolo
    _medicao(c, ids["sem_envio"], 2, "protocolada", 15_000, comp="2026-09", protocolo=("2026-10-16",))
    _medicao(c, ids["sem_envio"], 1, "recebida", 9_000, comp="2026-09", recebida_em="2026-10-16")
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    # protocolado em 16/10: a 11ª (5.000: protocolo em 01/10, recebida em 30/10), a 2ª da Companhia (40.000) e a 2ª da
    # Sem Envio (15.000); a 5ª da Obra Parada so' foi protocolada em 20/10. Recebido: 300.000 x 33,33% = 99.990, e 9.000
    assert r["mesma_altura"] == {"competencia": "2026-09", "ate": "2026-10-16",
                                 "protocolado_centavos": 5_000 + 40_000 + 15_000, "recebido_centavos": 99_990 + 9_000}
    # o numero comparado e' o da propria etapa hoje
    assert next(e for e in r["etapas"] if e["etapa"] == "protocolado")["valor_centavos"] == 99_999
    # olhando setembro, a referencia e' agosto, na mesma data
    assert resumo_medicoes.resumo(conn, HOJE, mes="2026-09")["mesma_altura"] == {
        "competencia": "2026-08", "ate": "2026-10-16", "protocolado_centavos": 0, "recebido_centavos": 0}


def test_mesma_altura_sem_a_data_do_evento_nao_tem_referencia(conn, cenario):
    """So' aparece o que tem lastro: a etapa em que alguma medicao da competencia anterior chegou sem a data do evento
    vem nula, e a outra continua."""
    c, ids = conn, cenario
    # o cenario: a 11ª da Obra Propria foi recebida em 30/10 sem protocolo registrado, numa obra que tem a etapa. Nao
    # da' para dizer se estava no protocolado em 16/10; o recebido tem a data
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    assert r["mesma_altura"] == {"competencia": "2026-09", "ate": "2026-10-16", "protocolado_centavos": None, "recebido_centavos": 0}
    # recebida antes de 16/10, mesmo sem o protocolo: ja' tinha saido do protocolado, e a referencia volta
    c.execute("UPDATE medicoes SET recebida_em='2026-10-15' WHERE contrato_id=? AND numero=11", (ids["propria"],))
    c.commit()
    assert resumo_medicoes.resumo(conn, HOJE, mes=MES)["mesma_altura"] == {
        "competencia": "2026-09", "ate": "2026-10-16", "protocolado_centavos": 0, "recebido_centavos": 5_000}
    # recebida sem a data do recebimento: nem o recebido nem o protocolado daquele dia tem lastro
    _medicao(c, ids["consorcio"], 6, "recebida", 300_000, comp="2026-09", protocolo=("2026-10-05",))
    c.commit()
    assert resumo_medicoes.resumo(conn, HOJE, mes=MES)["mesma_altura"] == {
        "competencia": "2026-09", "ate": "2026-10-16", "protocolado_centavos": None, "recebido_centavos": None}
    # protocolada pelo estado, sem a data do protocolo (o legado `nf_emitida`): o protocolado nao tem lastro
    c.execute("UPDATE medicoes SET recebida_em='2026-10-10' WHERE contrato_id=? AND numero=6", (ids["consorcio"],))
    _medicao(c, ids["companhia"], 2, "nf_emitida", 40_000, comp="2026-09")
    c.commit()
    assert resumo_medicoes.resumo(conn, HOJE, mes=MES)["mesma_altura"] == {
        "competencia": "2026-09", "ate": "2026-10-16", "protocolado_centavos": None, "recebido_centavos": 5_000 + 99_990}


def _prazo_da_sinfra(c, ids):
    """Cinco recebidas em doze meses, com 10, 20, 30, 30 e 40 dias do protocolo ao recebimento: prazo de 30 dias
    (docs/adr/0007). Numa obra suspensa, que nao aparece em nenhuma lista da pagina."""
    casos = [("2026-03-02", "2026-03-12"), ("2026-04-01", "2026-04-21"), ("2026-05-04", "2026-06-03"),
             ("2026-06-01", "2026-07-01"), ("2026-07-01", "2026-08-10")]
    for n, (protocolo, recebida) in enumerate(casos, start=1):
        _medicao(c, ids["suspensa"], n, "recebida", 1_000, comp=f"2026-0{n + 1}", recebida_em=recebida, protocolo=(protocolo,))


def test_parada_e_a_da_fila_de_trabalho_medicao_a_medicao(conn, cenario):
    """#805: o tempo parado do cartao e' o `parada` da fila de trabalho da tela Medicoes (`fila_medicoes`), a mesma
    leitura: os dias uteis do evento da situacao, os limites do SIGA e, no Pagamento, o prazo do orgao. A mesma
    medicao nao sai critica numa tela e em andamento na outra."""
    c, ids = conn, cenario
    _prazo_da_sinfra(c, ids)
    # protocolada em 01/10: a data esperada (31/10) ja' passou
    _medicao(c, ids["parada"], 9, "protocolada", 30_000, nota_emitida_em="2026-09-28", protocolo=("2026-10-01",))
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    linhas = [x for g in r["grupos"] for x in g["linhas"]]
    da_fila = {i: x["parada"] for g in fila_medicoes.fila(conn, HOJE, mes=MES)["grupos"] for x in g["linhas"]
               for i in x["medicao_ids"]}
    assert len(linhas) == 5 and all(x["parada"] == da_fila[x["medicao_id"]] for x in linhas)
    # no Pagamento conta do ULTIMO protocolo (13/11, sexta; hoje e' segunda, 16/11) e o tom sai do prazo do orgao: o
    # primeiro protocolo (10/11) + 30 dias ainda nao passou. A data da etapa continua a do primeiro
    p = _linha(r, "Obra Própria")
    assert p["parada"] == {"desde": "2026-11-13", "dias_uteis": 1, "hoje": False, "situacao": "andamento",
                           "prazo_orgao_dias": 30, "esperada": "2026-12-10", "alem_do_prazo": False}
    assert _etapas(p)[3] == ("protocolado", "atual", "2026-11-10")
    assert (p["recebida_em"], p["dias_da_nota_ao_recebimento"]) == (None, None)
    # alem do prazo do orgao: critico, com a data esperada
    a = _linha(r, "Obra Parada")["parada"]
    assert (a["desde"], a["situacao"], a["esperada"], a["alem_do_prazo"]) == ("2026-10-01", "critico", "2026-10-31", True)
    # em analise desde 05/11: 7 dias uteis, pelos limites do SIGA (5 ou mais, vence em breve), sem prazo do orgao
    k = _linha(r, "Obra Consórcio")["parada"]
    assert (k["desde"], k["dias_uteis"], k["situacao"], k["prazo_orgao_dias"]) == ("2026-11-05", 7, "breve", None)
    # a nota emitida da obra sem o passo "Envio da nota" espera o pagamento: 5 dias uteis nao sao alerta, e sem
    # protocolo nao ha' data esperada
    s = _linha(r, "Obra Sem Envio")["parada"]
    assert (s["desde"], s["dias_uteis"], s["situacao"], s["esperada"]) == ("2026-11-08", 5, "andamento", None)
    # sem a data do evento, nada e' contado da competencia
    comp = _linha(r, "Obra da Companhia")["parada"]
    assert (comp["desde"], comp["dias_uteis"], comp["situacao"]) == (None, None, None)
    # os meses anteriores levam a mesma leitura: a 5ª da Obra Parada, protocolada em 20/10, espera ate' 19/11
    [x5] = [x for g in r["anteriores"] for x in g["linhas"] if x["medicao_id"] == ids["x5"]]
    assert (x5["parada"]["situacao"], x5["parada"]["esperada"]) == ("andamento", "2026-11-19")


def test_recebida_nao_esta_parada_leva_a_data_e_os_dias_da_nota_ao_recebimento(conn, cenario):
    c, ids = conn, cenario
    c.execute("UPDATE medicoes SET estado='recebida', recebida_em='2026-11-14' WHERE id=?", (ids["p12"],))
    # a par dela, com a nota de 11/11: a linha conjunta conta da ultima das duas
    _medicao(c, ids["propria"], 12, "recebida", 1_001, tipo="reajuste", atestado_em="2026-11-06", valor_atestado_centavos=1_001,
             nota_emitida_em="2026-11-11", recebida_em="2026-11-14", protocolo=("2026-11-12",))
    c.commit()
    p = _linha(resumo_medicoes.resumo(conn, HOJE, mes=MES), "Obra Própria")
    assert p["titulo"] == "12ª Medição + Reajuste"
    assert (p["parada"], p["recebida_em"], p["dias_da_nota_ao_recebimento"]) == (None, "2026-11-14", 3)
    # recebida sem a emissao da nota registrada: so' a data
    c.execute("UPDATE medicoes SET nota_emitida_em=NULL WHERE contrato_id=? AND numero=12", (ids["propria"],))
    c.commit()
    p = _linha(resumo_medicoes.resumo(conn, HOJE, mes=MES), "Obra Própria")
    assert (p["recebida_em"], p["dias_da_nota_ao_recebimento"]) == ("2026-11-14", None)


def test_linha_que_a_fila_nao_junta_leva_a_parada_da_mais_parada(conn, cenario):
    """A pagina junta execucao e reajuste pela etapa; a fila, pela situacao. Com o boletim da execucao recebido e o
    espelho do reajuste ja' gerado, as duas estao na etapa do boletim (uma linha aqui) e em situacoes diferentes na
    fila (duas linhas la'): o cartao leva a leitura da mais parada."""
    c, ids = conn, cenario
    # o boletim das duas em 03/11 (terca): 9 dias uteis ate' 16/11; o espelho do reajuste nao tem data registrada
    c.execute("UPDATE medicoes SET estado='boletim_recebido', atestado_em='2026-11-03', valor_atestado_centavos=1_000_001 "
              "WHERE id=?", (ids["k7"],))
    r7 = _medicao(c, ids["consorcio"], 7, "espelho_gerado", 30_000, tipo="reajuste", atestado_em="2026-11-03",
                  valor_atestado_centavos=30_000)
    c.commit()
    k = _linha(resumo_medicoes.resumo(conn, HOJE, mes=MES), "Obra Consórcio")
    assert (k["titulo"], k["medicao_ids"], k["etapa"]) == ("7ª Medição + Reajuste", [ids["k7"], r7], "boletim")
    da_fila = {i: x["parada"] for g in fila_medicoes.fila(conn, HOJE, mes=MES)["grupos"] for x in g["linhas"]
               for i in x["medicao_ids"]}
    assert da_fila[ids["k7"]] != da_fila[r7] and da_fila[r7]["dias_uteis"] is None
    assert k["parada"] == da_fila[ids["k7"]]
    assert (k["parada"]["desde"], k["parada"]["dias_uteis"], k["parada"]["situacao"]) == ("2026-11-03", 9, "breve")


def test_diferenca_entre_o_aprovado_e_o_pedido_e_a_conta_do_fechamento(conn, cenario):
    c, ids = conn, cenario
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    assert r["diferenca_critica_por_mil"] == 5
    # aprovado 2 centavos abaixo do pedido: dentro da tolerancia de R$ 0,05, conta como igual
    p = _linha(r, "Obra Própria")
    assert (p["pedido_do_aprovado_centavos"], p["abaixo_do_pedido_centavos"], p["acima_do_pedido_centavos"]) == (100_001, 0, 0)
    # em analise: nao ha' dois valores para comparar
    k = _linha(r, "Obra Consórcio")
    assert (k["pedido_do_aprovado_centavos"], k["abaixo_do_pedido_centavos"], k["acima_do_pedido_centavos"]) == (None, None, None)
    # consorcio (33,33%): aprovado 900.000 de 1.000.001 pedidos; o corte sai na cota, e o reajuste da mesma linha, com
    # o aprovado acima do pedido, soma do lado dele
    c.execute("UPDATE medicoes SET estado='espelho_enviado', atestado_em='2026-11-08', valor_atestado_centavos=900_000 "
              "WHERE id=?", (ids["k7"],))
    _medicao(c, ids["consorcio"], 7, "espelho_enviado", 30_000, tipo="reajuste", atestado_em="2026-11-08",
             valor_atestado_centavos=33_000)
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    k = _linha(r, "Obra Consórcio")
    assert k["titulo"] == "7ª Medição + Reajuste"
    # 1.000.001 -> 333.300; 900.000 -> 299.970; 30.000 -> 9.999; 33.000 -> 10.999 (10.998,9)
    assert (k["pedido_do_aprovado_centavos"], k["abaixo_do_pedido_centavos"], k["acima_do_pedido_centavos"]) == (
        333_300 + 9_999, 333_300 - 299_970, 10_999 - 9_999)
    # os mesmos numeros do Fechamento para as duas medicoes
    [obra] = [o for m in fechamento.fechamento(conn)["meses"] if m["competencia"] == MES for o in m["obras"]
              if o["contrato_id"] == ids["consorcio"]]
    assert obra["pedido_do_aprovado_centavos"] == k["pedido_do_aprovado_centavos"]
    assert obra["abaixo_do_pedido_centavos"] == k["abaixo_do_pedido_centavos"]
    assert sum(m["acima_do_pedido_centavos"] for m in obra["medicoes"]) == k["acima_do_pedido_centavos"]


def test_filtro_por_contratante_recorta_tudo_e_a_lista_de_contratantes_fica_inteira(conn, cenario):
    ids = cenario
    inteiro = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    assert inteiro["contratante"] is None
    assert inteiro["contratantes"] == [{"contratante": "Companhia de Exemplo", "medicoes": 1, "anteriores": 0},
                                       {"contratante": "SINFRA", "medicoes": 3, "anteriores": 2}]
    assert [(g["contratante"], g["medicoes"], g["valor_centavos"]) for g in inteiro["grupos"]] == [
        ("Companhia de Exemplo", 1, 50_000), ("SINFRA", 3, 333_300 + 99_999 + 70_000)]
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES, contratante="Companhia de Exemplo")
    assert r["contratante"] == "Companhia de Exemplo" and r["contratantes"] == inteiro["contratantes"]
    assert [g["contratante"] for g in r["grupos"]] == ["Companhia de Exemplo"]
    assert [(e["etapa"], e["medicoes"], e["valor_centavos"]) for e in r["etapas"] if e["medicoes"]] == [("boletim", 1, 50_000)]
    assert r["medido"] == {"valor_centavos": 50_000, "mes_anterior": None, "ano_anterior": None}
    assert r["sem_medicao"] == [] and r["anteriores"] == []
    assert r["mesma_altura"] == {"competencia": "2026-09", "ate": "2026-10-16", "protocolado_centavos": 0, "recebido_centavos": 0}
    sinfra = resumo_medicoes.resumo(conn, HOJE, mes=MES, contratante="SINFRA")
    assert sinfra["medido"]["valor_centavos"] == 333_300 + 99_999 + 70_000
    assert sinfra["medido"]["mes_anterior"] == {"competencia": "2026-09", "valor_centavos": 25_000}
    assert [o["contrato_id"] for o in sinfra["sem_medicao"]] == [ids["parada"]]
    assert [g["competencia"] for g in sinfra["anteriores"]] == ["2026-08", "2026-09"]
    # o contratante que nao existe nao tem nada, e a lista continua dizendo quem tem
    nada = resumo_medicoes.resumo(conn, HOJE, mes=MES, contratante="Órgão Inexistente")
    assert nada["grupos"] == [] and nada["medido"]["valor_centavos"] == 0 and nada["contratantes"] == inteiro["contratantes"]


def test_meses_anteriores_so_do_primeiro_ano_em_diante_com_o_subtotal_de_cada_competencia(conn, cenario):
    """Decisao do dono (#805): pendencia de competencia anterior a 2025 fica fora das telas da diretoria."""
    c, ids = conn, cenario
    velha = _medicao(c, ids["propria"], 1, "protocolada", 77_000, comp="2024-12", protocolo=("2025-01-20",))
    de_2025 = _medicao(c, ids["propria"], 2, "protocolada", 66_000, comp="2025-01", protocolo=("2025-02-20",))
    c.commit()
    r = resumo_medicoes.resumo(conn, HOJE, mes=MES)
    abertas = [x["medicao_id"] for g in r["anteriores"] for x in g["linhas"]]
    assert de_2025 in abertas and velha not in abertas
    assert [(g["competencia"], g["medicoes"], g["valor_centavos"]) for g in r["anteriores"]] == [
        ("2025-01", 1, 66_000), ("2026-08", 1, 1_000), ("2026-09", 1, 20_000)]
    # a contagem por etapa dos meses anteriores: 3.000 x 33,33% = 999,9 -> 1.000 em analise; duas protocoladas
    assert [(e["etapa"], e["medicoes"], e["valor_centavos"]) for e in r["anteriores_etapas"] if e["medicoes"]] == [
        ("em_analise", 1, 1_000), ("protocolado", 2, 86_000)]
    assert r["contratantes"][-1] == {"contratante": "SINFRA", "medicoes": 3, "anteriores": 3}
    # a exportacao segue a pagina: a de 2024 nao sai
    linhas = resumo_medicoes.linhas_csv(r, lambda v: str(v))
    assert [x[4] for x in linhas if x[0] == "meses anteriores"] == ["01/2025", "08/2026", "09/2026"]


# --- rotas ---------------------------------------------------------------------------------------------------

@pytest.fixture
def _sem_certidoes(sem_certidoes_exigidas):
    """As rotas abaixo nao sao sobre certidoes (ver conftest)."""


def test_rota_e_exportacao_da_relacao(client_admin, _sem_certidoes):
    cid = novo_contrato({"orgao": "Secretaria de Exemplo", "numero_instrumento": "IC 1/2026", "objeto": "=Obra Própria",
                         "valor_original": "100.000,00"})
    outra = novo_contrato({"orgao": "Secretaria de Exemplo", "numero_instrumento": "IC 2/2026", "objeto": "Obra Consórcio",
                           "valor_original": "100.000,00"})
    c = db.get_conn()
    c.execute("UPDATE contratos SET nome_curto=objeto")
    mid = _medicao(c, cid, 3, "nota_emitida", 150_001, nota_emitida_em="2026-11-09")
    reajuste = _medicao(c, cid, 3, "nota_emitida", 2_000, tipo="reajuste", nota_emitida_em="2026-11-10")
    antiga = _medicao(c, cid, 2, "protocolada", 80_000, comp="2026-09", nota_emitida_em="2026-10-05",
                      protocolo=("2026-10-09",))
    c.commit()
    c.close()
    r = client_admin.get(f"/api/resumo-medicoes?mes={MES}")
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"hoje", "mes", "em_trabalho", "atualizacao", "contratante", "contratantes", "etapas", "medido",
                      "mesma_altura", "diferenca_critica_por_mil", "grupos", "sem_medicao", "anteriores_etapas", "anteriores"}
    assert d["medido"]["valor_centavos"] == 152_001 == sum(e["valor_centavos"] for e in d["etapas"])
    [linha] = [x for g in d["grupos"] for x in g["linhas"]]
    assert (linha["medicao_ids"], linha["etapa"], linha["valor_centavos"]) == ([mid, reajuste], "nota", 152_001)
    assert [o["contrato_id"] for o in d["sem_medicao"]] == [outra]
    assert [x["medicao_id"] for g in d["anteriores"] for x in g["linhas"]] == [antiga]
    assert client_admin.get("/api/resumo-medicoes").json()["mes"] == d["em_trabalho"]
    assert client_admin.get("/api/resumo-medicoes?mes=2026-13").status_code == 422

    x = client_admin.get(f"/api/resumo-medicoes.csv?mes={MES}")
    assert x.status_code == 200 and x.headers["content-type"].startswith("text/csv")
    assert f'filename="resumo-das-medicoes-{MES}.csv"' in x.headers["content-disposition"]
    texto = x.content.decode("utf-8-sig").split("\r\n")
    # o valor e' o medido na cota, dito no nome da coluna
    assert texto[0] == "parte;contratante;obra;medicao;competencia;etapa;data_em_analise;data_boletim;data_nota;data_protocolado;data_recebido;medido_cota"
    # o nome que comeca com "=" sai neutralizado (formula em planilha); a data no formato da tela; o valor em reais.
    # A linha conjunta: a soma das duas cotas e, na nota, a data da ultima das duas
    assert texto[1] == "competência;Secretaria de Exemplo;'=Obra Própria;3ª Medição + Reajuste;10/2026;Nota;;;10/11/2026;;;R$ 1.520,01"
    assert texto[2] == "sem medição no mês;Secretaria de Exemplo;Obra Consórcio;;10/2026;;;;;;;"
    # meses anteriores em aberto, com a competencia de cada linha
    assert texto[3] == "meses anteriores;Secretaria de Exemplo;'=Obra Própria;2ª Medição;09/2026;Protocolado;;;05/10/2026;09/10/2026;;R$ 800,00"
    assert texto[4:] == [""]

    # #805: o filtro por contratante recorta a resposta e a exportacao
    assert d["contratantes"] == [{"contratante": "Secretaria de Exemplo", "medicoes": 2, "anteriores": 1}]
    do_orgao = client_admin.get("/api/resumo-medicoes", params={"mes": MES, "contratante": "Secretaria de Exemplo"}).json()
    assert do_orgao["contratante"] == "Secretaria de Exemplo" and do_orgao["grupos"] == d["grupos"]
    de_outro = client_admin.get("/api/resumo-medicoes", params={"mes": MES, "contratante": "Outro Órgão"})
    assert de_outro.status_code == 200 and de_outro.json()["grupos"] == [] and de_outro.json()["contratantes"] == d["contratantes"]
    x = client_admin.get("/api/resumo-medicoes.csv", params={"mes": MES, "contratante": "Outro Órgão"})
    assert x.status_code == 200 and x.content.decode("utf-8-sig").split("\r\n")[1:] == [""]
    assert client_admin.get("/api/resumo-medicoes?contratante=").status_code == 422


@pytest.mark.parametrize("perfil", ["diretoria", "engenharia"])
def test_rota_e_csv_abrem_para_quem_so_consulta_e_para_quem_opera(client, _sem_certidoes, perfil):
    """A pagina e' de leitura para os tres perfis (`ver_paineis`); o admin esta' no teste acima."""
    c = db.get_conn()
    auth.criar_usuario(c, "Pessoa Exemplo", f"{perfil}@exemplo.com.br", "senha-forte-123", perfil)
    c.close()
    r = client.post("/api/auth/login", json={"email": f"{perfil}@exemplo.com.br", "senha": "senha-forte-123"})
    assert r.status_code == 200, r.text
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))
    d = client.get(f"/api/resumo-medicoes?mes={MES}")
    assert d.status_code == 200 and d.json()["mes"] == MES
    x = client.get(f"/api/resumo-medicoes.csv?mes={MES}")
    assert x.status_code == 200 and x.headers["content-type"].startswith("text/csv")


def test_resumo_le_um_retrato_so_do_banco(conn, cenario, monkeypatch):
    """Segunda revisao, achado 4: todas as consultas dentro de uma transacao de leitura (`db.leitura`), fechada no fim."""
    visto = []
    original = resumo_medicoes._atualizacao
    monkeypatch.setattr(resumo_medicoes, "_atualizacao", lambda c: (visto.append(c.in_transaction), original(c))[1])
    assert not conn.in_transaction
    resumo_medicoes.resumo(conn, HOJE, mes=MES)
    assert visto == [True] and not conn.in_transaction


def test_rota_exige_login(client):
    assert client.get("/api/resumo-medicoes").status_code == 401
    assert client.get("/api/resumo-medicoes.csv").status_code == 401
