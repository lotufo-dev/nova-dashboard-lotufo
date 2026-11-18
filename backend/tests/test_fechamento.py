"""Pagina Fechamento (issue #748): medido, aprovado, protocolado e recebido por mes de competencia de 2025 e 2026, na
cota, com o em aberto nota a nota. Os totais fecham ao centavo com as linhas abertas. Dados sinteticos."""
import datetime
import json
import pathlib

import pytest

from app import auth, cadastro_aplicar, cadastro_arquivos, db, diretoria, fechamento, inicio, medicoes, sincronizacao_rm
from tests.conftest import CADASTRO_EXEMPLO
from tests.test_protocolo import _contrato

MODELO = pathlib.Path(__file__).parents[2] / "cadastro-exemplo" / "modelos" / "qdop" / "qdop-modelo.xlsx"
NUMEROS = fechamento.NUMEROS
SOMAS = fechamento.SOMAS


@pytest.fixture
def cenario(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    uid = auth.criar_usuario(c, "Adm", "adm@exemplo.com.br", "senha-forte-123", "admin")
    propria = {**_contrato("Própria", "orgao-x", "IC 1/2025"), "centro_custo_rm": "9.001.001"}
    consorcio = {**_contrato("Consórcio", "orgao-x", "IC 2/2025"), "entidade": "cons", "percentual_direito_bp": 5000}
    cadastro_aplicar.aplicar(c, uid, {
        "orgaos": [{"chave": "orgao-x", "nome": "Secretaria X", "familia": "prefeitura", "cnpj": None,
                    "regras": {"nome_qdop": "SECRETARIA X", "tipo_contratante": "PÚBLICO"}}],
        "entidades": [{"chave": "lotufo", "nome": "Construtora Alfa Ltda", "cnpj": "31200101000130", "papel": "lotufo",
                       "coligada_rm": 1, "sigla_oficio": "AL", "nome_curto": "Alfa"},
                      {"chave": "cons", "nome": "Consórcio Teste", "cnpj": "31200404000152", "papel": "consorcio",
                       "coligada_rm": 12, "sigla_oficio": None, "nome_curto": "Consórcio"}],
        "contratos": [propria, consorcio], "avisos": [],
        "geral": {"qdop": {"modelo_caminho": str(MODELO)}, "diretoria": {"total_a_receber_liberado": True}}})
    ids = {"propria": c.execute("SELECT id FROM contratos WHERE nome_curto='Própria'").fetchone()[0],
           "consorcio": c.execute("SELECT id FROM contratos WHERE nome_curto='Consórcio'").fetchone()[0], "uid": uid}
    yield c, ids
    c.close()


EMPRESA, CONSORCIO, OUTRA = 1, 90, 77      # coligadas no RM: a empresa, o Consorcio Exemplo e uma que nao e' nenhuma das duas


@pytest.fixture
def exemplo(tmp_path, monkeypatch):
    """O cadastro de exemplo (`cadastro-exemplo/`): a Obra Consorcio, do Consorcio Exemplo (coligada 90 no RM), com a
    cota de 50% da empresa (coligada 1). Devolve a conexao e o id do contrato."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    uid = auth.criar_usuario(c, "Adm", "adm@exemplo.com.br", "senha-forte-123", "admin")
    cadastro_aplicar.aplicar(c, uid, cadastro_arquivos.preparar(CADASTRO_EXEMPLO), ensaio=False)
    k = c.execute("SELECT id FROM contratos WHERE nome_curto='Obra Consórcio'").fetchone()[0]
    assert tuple(c.execute("SELECT e.coligada_rm, e.papel, k.percentual_direito_bp FROM contratos k JOIN entidades e "
                           "ON e.id=k.entidade_id WHERE k.id=?", (k,)).fetchone()) == (CONSORCIO, "consorcio", 5000)
    yield c, k
    c.close()


def medir(c, cid, numero, comp, estado, pedido, aprovado=None, tipo="execucao", protocolo=None):
    mid = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
                    "valor_atestado_centavos) VALUES (?,?,?,?,?,?,?)",
                    (cid, numero, tipo, comp, estado, pedido, aprovado)).lastrowid
    if protocolo:
        c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, ?, 'manual')", (mid, protocolo))
    c.commit()
    return mid


_IDMOV = iter(range(5000, 9000))


def nota(c, valor, medicoes_=(), coligada=1, situacao="ativa", codtmv="2.2.01", emissao="2026-03-10",
         alocado=None, titulos=None, desconsiderada=False, centro=None):
    """Nota do RM ligada as medicoes. `titulos`: [(original, baixado, status)]; sem dizer, um aberto pelo valor; com a
    lista vazia, a nota fica sem titulo nenhum no RM."""
    idmov = next(_IDMOV)
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, codtmv, "
                    "centro_custo, desconsiderada_em) VALUES (?,?,?,?,?,?,?,?,?)",
                    (coligada, idmov, f"{idmov:09d}", emissao, valor, "cancelada" if desconsiderada else situacao,
                     codtmv, centro, "2026-11-01" if desconsiderada else None)).lastrowid
    for k, (orig, baixado, st) in enumerate([(valor, 0, 0)] if titulos is None else titulos):
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan, data_baixa) VALUES (?,?,?,?,?,?,?,?)",
                  (coligada, idmov * 10 + k, nid, idmov, orig, baixado, st, "2026-05-02" if baixado else None))
    for mid in medicoes_:
        c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                  "VALUES (?, ?, ?, 'manual', 't')", (mid, nid, alocado if alocado is not None else valor))
    c.commit()
    return str(idmov)


PAGO = lambda v: [(v, v, 1)]                               # noqa: E731  titulo inteiro baixado


def _mes(f, comp):
    return next(m for m in f["meses"] if m["competencia"] == comp)


def _numeros(x):
    return tuple(x[k] for k in NUMEROS)


def _estado(c, medicao_id):
    """O estado da medicao no banco: a resposta da pagina nao o traz (revisao da PR #754)."""
    return c.execute("SELECT estado FROM medicoes WHERE id=?", (medicao_id,)).fetchone()[0]


def _confere_soma(f):
    """Os totais da pagina fecham com a soma das linhas abertas, ao centavo, em todos os niveis."""
    for m in f["meses"]:
        for o in m["obras"]:
            for md in o["medicoes"]:
                assert md["protocolado_centavos"] == sum(n["valor_centavos"] for n in md["notas"])
                assert md["recebido_centavos"] == sum(n["recebido_centavos"] for n in md["notas"])
                for n in md["notas"]:                       # cada nota: recebido + em aberto = o valor bruto dela
                    assert n["recebido_centavos"] + n["em_aberto_centavos"] == n["valor_centavos"]
                    assert n["recebido_centavos"] >= 0 and n["em_aberto_centavos"] >= 0
                    assert n["recebida"] == (n["em_aberto_centavos"] == 0)
                    assert n["paga_em_parte"] == (0 < n["em_aberto_centavos"] < n["valor_centavos"])
                    # repasse sem baixa: so' nota em aberto (da medicao recebida, que cada teste confere no banco)
                    assert not n["aguarda_repasse"] or n["em_aberto_centavos"] > 0
                assert "estado" not in md                   # o estado da medicao nao sai na resposta (PR #754)
                # a nota fora da conta (fatura do consorcio preterida pela nota da empresa) nao leva valor nem soma
                assert all(set(n) == {"nota_id", "numero"} for n in md["notas_fora_da_conta"])
                assert md["notas_fora_da_conta"] == [] or md["notas"]
                # em aberto = (a) nota protocolada nao paga (ou paga em parte) + (a') repasse sem baixa + (b) medicao
                # protocolada sem nota ligada; protocolado - recebido = (a) + (a'), e uma medicao nao tem (a) e (a') juntas
                assert md["em_aberto_notas_centavos"] + md["em_aberto_repasse_centavos"] == md["protocolado_centavos"] - md["recebido_centavos"]
                assert md["em_aberto_centavos"] == md["em_aberto_notas_centavos"] + md["em_aberto_repasse_centavos"] + md["sem_nota_centavos"]
                assert md["em_aberto_repasse_centavos"] == sum(n["em_aberto_centavos"] for n in md["notas"] if n["aguarda_repasse"])
                assert not (md["em_aberto_notas_centavos"] and md["em_aberto_repasse_centavos"])
                assert md["sem_nota_centavos"] == 0 or (md["sem_nota"] and md["notas"] == [])
            for k in SOMAS:
                assert o[k] == sum(md[k] for md in o["medicoes"]), (m["competencia"], o["obra"], k)
        for k in SOMAS:
            assert m[k] == sum(o[k] for o in m["obras"]), (m["competencia"], k)
    for ano, tot in f["por_ano"].items():
        for k in SOMAS:
            assert tot[k] == sum(m[k] for m in f["meses"] if m["competencia"][:4] == ano), (ano, k)
        assert tot["meses"] == sum(1 for m in f["meses"] if m["competencia"][:4] == ano)
        # o painel "Em aberto" do ano: as linhas do ano somam o total do ano, e as duas partes somam o total
        do_ano = [e for e in f["em_aberto"] if e["competencia"][:4] == ano]
        assert tot["em_aberto_centavos"] == sum(e["valor_centavos"] for e in do_ano)
        assert {e["tipo_aberto"] for e in do_ano} <= {"nota", "repasse", "sem_nota"}
        assert tot["em_aberto_notas_centavos"] == sum(e["valor_centavos"] for e in do_ano if e["tipo_aberto"] == "nota")
        assert tot["em_aberto_repasse_centavos"] == sum(e["valor_centavos"] for e in do_ano if e["tipo_aberto"] == "repasse")
        assert tot["sem_nota_centavos"] == sum(e["valor_centavos"] for e in do_ano if e["tipo_aberto"] == "sem_nota")
        assert tot["em_aberto_centavos"] == tot["protocolado_centavos"] - tot["recebido_centavos"] + tot["sem_nota_centavos"]
        assert tot["em_aberto_centavos"] == sum(tot[k] for k in fechamento.PARTES_DO_ABERTO)
    assert all(e["competencia"][:4] in f["anos"] for e in f["em_aberto"])
    # nenhuma nota em duas partes: a que conta numa medicao (a), a que ficou fora da conta e a sem medicao ligada (c)
    mds = [md for m in f["meses"] for o in m["obras"] for md in o["medicoes"]]
    contam = {n["nota_id"] for md in mds for n in md["notas"]}
    fora = {n["nota_id"] for md in mds for n in md["notas_fora_da_conta"]}
    soltas = {e["nota_id"] for e in f["notas_sem_medicao"]["em_aberto"]}
    assert not contam & soltas and not fora & soltas
    assert all(not {n["nota_id"] for n in md["notas"]} & {n["nota_id"] for n in md["notas_fora_da_conta"]} for md in mds)
    # os avisos so' falam de medicao da pagina; o da nota diferente da cota, pelos dois valores, acima da tolerancia
    assert all(e["medicao_id"] in {md["medicao_id"] for md in mds} for e in f["pares_mistos"])
    for e in f["notas_diferem"]:
        assert e["medicao_id"] in {md["medicao_id"] for md in mds}
        assert e["diferenca_centavos"] == e["notas_centavos"] - e["cota_centavos"]
        assert abs(e["diferenca_centavos"]) > 100


def _em_aberto(f):
    """O em aberto dos dois anos somados (a tela mostra um ano por vez, de `por_ano`)."""
    return sum(f["por_ano"][a]["em_aberto_centavos"] for a in f["anos"])


def test_sem_lancamento_a_pagina_vem_vazia_sem_zero_disfarcado(cenario):
    c, _ = cenario
    f = fechamento.fechamento(c)
    assert f["anos"] == ["2025", "2026"] and f["meses"] == [] and f["em_aberto"] == []
    assert f["acumulado"]["ate_mes"] is None and f["notas_diferem"] == [] and f["pares_mistos"] == []
    assert f["por_ano"]["2025"]["meses"] == f["por_ano"]["2026"]["meses"] == 0
    assert f["notas_sem_medicao"] == {"em_aberto": [], "em_aberto_centavos": 0, "pagas": {"quantidade": 0, "valor_centavos": 0}}
    assert f["cobertura"]["2026"] == {"aprovado_centavos": 0, "com_nota_centavos": 0, "sem_nota_centavos": 0,
                                      "medicoes_sem_nota": 0, "percentual": None}


def test_os_quatro_numeros_pela_competencia_da_medicao(cenario):
    """A nota e o recebimento caem na competencia da medicao a que a nota esta' ligada, nao na emissao nem na baixa."""
    c, ids = cenario
    p = ids["propria"]
    m1 = medir(c, p, 1, "2026-02", "recebida", 1_000_001, aprovado=900_001, protocolo="2026-04-01")
    nota(c, 900_001, [m1], emissao="2026-03-20", titulos=PAGO(800_000))
    medir(c, p, 2, "2026-03", "planilha_enviada", 500_000)                   # em analise: so' medido
    medir(c, p, 3, "2026-03", "espelho_gerado", 400_000, aprovado=350_001)   # aprovado, sem nota protocolada
    f = fechamento.fechamento(c)
    assert [m["competencia"] for m in f["meses"]] == ["2026-02", "2026-03"]
    assert _numeros(_mes(f, "2026-02")) == (900_001, 900_001, 900_001, 900_001, 0)
    # medido = aprovado e, sem boletim, o pedido; medido - aprovado = o que esta' em analise
    assert _numeros(_mes(f, "2026-03")) == (500_000 + 350_001, 350_001, 0, 0, 0)
    assert f["em_aberto"] == []
    _confere_soma(f)


def test_consorcio_na_cota_com_centavo_impar_e_nfse_de_outra_consorciada_fora(cenario):
    """Em consorcio sem a nota da propria empresa ligada: a cota de cada parcela (50%, meio para cima, uma vez por
    parcela), da fatura do consorcio (coligada do contrato, valor cheio). A NFS-e de outra consorciada na mesma
    medicao nao conta nem aparece."""
    c, ids = cenario
    k = ids["consorcio"]
    mid = medir(c, k, 1, "2025-07", "protocolada", 2_000_003, aprovado=2_000_001, protocolo="2025-09-02")
    nota(c, 2_000_001, [mid], coligada=12)
    nota(c, 1_000_000, [mid], coligada=OUTRA)                                # NFS-e de outra consorciada: fora
    f = fechamento.fechamento(c)
    m = _mes(f, "2025-07")
    assert _numeros(m) == (1_000_001, 1_000_001, 1_000_001, 0, 1_000_001)   # 2.000.001 x 50% = 1.000.000,5 -> 1.000.001
    assert [(e["obra"], e["protocolo_em"], e["valor_centavos"]) for e in f["em_aberto"]] == [
        ("Consórcio", "2025-09-02", 1_000_001)]
    assert m["obras"][0]["medicoes"][0]["notas_fora_da_conta"] == []
    _confere_soma(f)


def test_consorcio_com_varias_faturas_o_protocolado_fecha_com_o_aprovado(cenario):
    """Visto no Fechamento sobre o volume real: a medicao de consorcio cobrada em varias faturas saia com o
    protocolado um centavo acima do aprovado. A cota era arredondada fatura a fatura (tres vezes 500.000,5 ->
    1.500.003) e o aprovado uma vez so' (3.000.003 x 50% = 1.500.001,5 -> 1.500.002). As faturas de uma medicao sao
    uma parcela so': a cota da soma, repartida entre elas, com o residuo nos maiores restos."""
    c, ids = cenario
    k = ids["consorcio"]
    mid = medir(c, k, 1, "2026-04", "recebida", 3_000_003, aprovado=3_000_003, protocolo="2026-04-30")
    for _ in range(3):
        nota(c, 1_000_001, [mid], coligada=12, titulos=PAGO(1_000_001))
    outra = medir(c, k, 2, "2026-04", "protocolada", 1_000_001, aprovado=1_000_001, protocolo="2026-05-05")
    nota(c, 1_000_001, [outra], coligada=12)                 # uma fatura so': a cota dela, como sempre (500.001)
    f = fechamento.fechamento(c)
    md = _medicao(f, mid)
    assert _numeros(md) == (1_500_002, 1_500_002, 1_500_002, 1_500_002, 0)
    assert sorted(n["valor_centavos"] for n in md["notas"]) == [500_000, 500_001, 500_001]
    assert _numeros(_medicao(f, outra)) == (500_001, 500_001, 500_001, 0, 500_001)
    m = _mes(f, "2026-04")
    assert m["protocolado_centavos"] == m["aprovado_centavos"] == 2_000_003
    _confere_soma(f)
    # paga em parte: o que falta numa das tres faturas nao passa da cota que coube a ela
    assert fechamento._cotas([1_000_001] * 3, 5000) == [500_001, 500_001, 500_000]
    assert fechamento._cotas([1_000_001], 5000) == [500_001] and fechamento._cotas([7, 3], None) == [7, 3]
    assert fechamento._cotas([], 5000) == [] and fechamento._cotas([0, 0], 5000) == [0, 0]


def test_consorcio_com_varias_faturas_e_uma_delas_partilhada_com_outra_medicao(cenario):
    """As duas regras juntas: a cota das faturas do consorcio e' a da soma delas (um arredondamento, repartido), e a
    fatura que cobre duas medicoes entra em cada uma pelo valor da PARTE (docs/adr/0005), nao inteira. A execucao tem
    duas faturas inteiras e uma parte da terceira; o reajuste, a outra parte dela."""
    c, ids = cenario
    k = ids["consorcio"]
    execucao = medir(c, k, 7, "2026-05", "protocolada", 3_000_003, aprovado=3_000_003, protocolo="2026-06-01")
    reajuste = medir(c, k, 7, "2026-05", "protocolada", 500_003, aprovado=500_003, tipo="reajuste", protocolo="2026-06-01")
    for _ in range(2):
        nota(c, 1_000_001, [execucao], coligada=12)
    partilhada = nota(c, 1_500_004, coligada=12)                    # 1.000.001 da execucao + 500.003 do reajuste
    nid = c.execute("SELECT id FROM notas_fiscais WHERE numero=?", (f"{int(partilhada):09d}",)).fetchone()[0]
    for mid, parte in ((execucao, 1_000_001), (reajuste, 500_003)):
        c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra, partilhada) "
                  "VALUES (?, ?, ?, 'manual', 'correcao_cadastro', 1)", (mid, nid, parte))
    c.commit()
    f = fechamento.fechamento(c)
    # execucao: tres parcelas de 1.000.001; a cota e' a da soma (3.000.003 x 50% = 1.500.002), repartida com o residuo
    md = _medicao(f, execucao)
    assert sorted(n["valor_centavos"] for n in md["notas"]) == [500_000, 500_001, 500_001]
    assert md["protocolado_centavos"] == md["aprovado_centavos"] == 1_500_002
    # reajuste: so' a parte dele da nota partilhada (500.003 x 50% = 250.002), nao a nota inteira
    mr = _medicao(f, reajuste)
    assert [n["valor_centavos"] for n in mr["notas"]] == [250_002] and mr["protocolado_centavos"] == mr["aprovado_centavos"]
    m = _mes(f, "2026-05")
    assert m["protocolado_centavos"] == m["aprovado_centavos"] == 1_750_004
    # nenhuma tem baixa: tudo em aberto, e a nota partilhada aparece nas duas medicoes pelas partes
    assert m["em_aberto_centavos"] == 1_750_004 and m["recebido_centavos"] == 0
    _confere_soma(f)
    # a nota partilhada paga em parte: a falta dos titulos (300.001) reparte-se pelas partes, na proporcao (200.000 e
    # 100.001, com o residuo), e cada medicao fica em aberto pela cota da parte dela (100.000 e 50.000,5 -> 50.001)
    c.execute("UPDATE baixas SET valor_baixado_centavos=valor_original_centavos-300001, status_lan=4, data_baixa='2026-07-01' "
              "WHERE nota_id=?", (nid,))
    c.commit()
    f = fechamento.fechamento(c)
    da_partilhada = lambda mid: next(n for n in _medicao(f, mid)["notas"] if n["nota_id"] == nid)
    assert (da_partilhada(execucao)["em_aberto_centavos"], da_partilhada(reajuste)["em_aberto_centavos"]) == (100_000, 50_001)
    _confere_soma(f)


def test_mes_sem_lancamento_nao_vira_linha_e_o_acumulado_compara_os_mesmos_meses(cenario):
    c, ids = cenario
    p = ids["propria"]
    medir(c, p, 1, "2025-01", "planilha_enviada", 100_000)
    medir(c, p, 2, "2025-05", "planilha_enviada", 200_000)                   # depois de 03: fora do acumulado
    medir(c, p, 3, "2026-01", "planilha_enviada", 300_000)
    medir(c, p, 4, "2026-03", "planilha_enviada", 400_000)
    medir(c, p, 5, "2024-12", "planilha_enviada", 999_999)                   # antes de 2025: fora da pagina
    f = fechamento.fechamento(c)
    assert [m["competencia"] for m in f["meses"]] == ["2025-01", "2025-05", "2026-01", "2026-03"]
    assert f["acumulado"]["ate_mes"] == "03"
    assert f["acumulado"]["2026"]["medido_centavos"] == 700_000
    assert f["acumulado"]["2025"]["medido_centavos"] == 100_000
    assert f["por_ano"]["2025"]["medido_centavos"] == 300_000 and f["por_ano"]["2025"]["meses"] == 2
    _confere_soma(f)


def test_canceladas_desistidas_e_planilha_so_gerada_ficam_fora(cenario):
    c, ids = cenario
    p = ids["propria"]
    for n, estado in enumerate(("cancelada", "desistida", "prevista", "planilha_gerada"), 1):
        mid = medir(c, p, n, "2026-04", estado, 1_000_000, protocolo="2026-05-01")
        nota(c, 1_000_000, [mid])
    assert fechamento.fechamento(c)["meses"] == []
    assert set(fechamento.ESTADOS_APROVADO) | {"planilha_enviada"} == set(medicoes.ESTADOS_NO_MEDIDO)


def test_nota_em_aberto_nota_a_nota_e_medicao_com_duas_notas(cenario):
    """Uma medicao faturada em duas notas: a paga entra no recebido, a outra fica em aberto, uma linha por nota."""
    c, ids = cenario
    p = ids["propria"]
    mid = medir(c, p, 7, "2026-05", "protocolada", 1_500_001, aprovado=1_500_001, protocolo="2026-06-10")
    paga = nota(c, 1_000_000, [mid], titulos=PAGO(930_000))
    aberta = nota(c, 500_001, [mid])
    outra = medir(c, p, 8, "2026-05", "protocolada", 70_000, protocolo="2026-06-01")
    antiga = nota(c, 70_000, [outra])
    f = fechamento.fechamento(c)
    m = _mes(f, "2026-05")
    assert _numeros(m) == (1_570_001, 1_570_001, 1_570_001, 1_000_000, 570_001)
    md = next(x for x in m["obras"][0]["medicoes"] if x["medicao_id"] == mid)
    assert [(n["numero"], n["valor_centavos"], n["recebida"]) for n in md["notas"]] == [
        (paga, 1_000_000, True), (aberta, 500_001, False)]
    # a lista em aberto vem pela data do protocolo, a mais antiga primeiro
    assert [(e["numero"], e["protocolo_em"], e["medicao_numero"]) for e in f["em_aberto"]] == [
        (antiga, "2026-06-01", 8), (aberta, "2026-06-10", 7)]
    assert _em_aberto(f) == f["por_ano"]["2026"]["em_aberto_centavos"] == 570_001
    _confere_soma(f)


def test_nota_desconsiderada_ou_cancelada_fica_fora(cenario):
    c, ids = cenario
    mid = medir(c, ids["propria"], 1, "2026-06", "protocolada", 300_000, protocolo="2026-07-01")
    nota(c, 300_000, [mid], desconsiderada=True)
    nota(c, 300_000, [mid], situacao="cancelada")
    nota(c, 300_000, [mid], codtmv="2.2.15")                                 # nota do fornecedor: nao cobra o orgao
    f = fechamento.fechamento(c)
    # nenhuma nota conta: a medicao protocolada fica em aberto pelo valor dela, marcada sem nota ligada (b)
    assert _numeros(_mes(f, "2026-06")) == (300_000, 300_000, 0, 0, 300_000)
    assert [(e["tipo_aberto"], e["numero"], e["valor_centavos"]) for e in f["em_aberto"]] == [("sem_nota", None, 300_000)]
    vale = nota(c, 300_000, [mid])
    f = fechamento.fechamento(c)
    assert _numeros(_mes(f, "2026-06")) == (300_000, 300_000, 300_000, 0, 300_000)
    assert [(e["tipo_aberto"], e["numero"]) for e in f["em_aberto"]] == [("nota", vale)]


def test_recebida_a_mao_quita_as_notas_e_baixa_sem_valor_nao_quita(cenario):
    """docs/adr/0006: a medicao recebida (baixa ou registro do administrador) leva as notas dela para o recebido, mesmo
    com titulo aberto no RM. Titulo baixado sem valor (glosa, compensacao) nao e' recebimento; ate' R$ 1,00 a menos e'."""
    c, ids = cenario
    p = ids["propria"]
    a_mao = medir(c, p, 1, "2026-07", "protocolada", 100_000, protocolo="2026-08-01")
    nota(c, 100_000, [a_mao])
    medicoes.mudar_estado(c, ids["uid"], a_mao, "recebida", "a baixa nao entrou no RM; conferida no extrato",
                          "2026-09-20", origem="manual")
    sem_caixa = medir(c, p, 2, "2026-07", "protocolada", 200_000, protocolo="2026-08-01")
    nota(c, 200_000, [sem_caixa], titulos=[(200_000, 0, 1)])
    quase = medir(c, p, 3, "2026-07", "protocolada", 300_000, protocolo="2026-08-01")
    nota(c, 300_000, [quase], titulos=[(250_000, 249_901, 1)])               # faltam 0,99: quitada
    f = fechamento.fechamento(c)
    assert _numeros(_mes(f, "2026-07")) == (600_000, 600_000, 600_000, 400_000, 200_000)
    assert [e["valor_centavos"] for e in f["em_aberto"]] == [200_000]
    _confere_soma(f)


def test_nota_ligada_a_duas_medicoes_entra_em_cada_uma_pelo_valor_do_vinculo(cenario):
    c, ids = cenario
    p = ids["propria"]
    exe = medir(c, p, 1, "2026-08", "protocolada", 700_000, protocolo="2026-09-01")
    rea = medir(c, p, 1, "2026-08", "protocolada", 300_001, tipo="reajuste", protocolo="2026-09-01")
    nid = nota(c, 1_000_001, [exe], alocado=700_000)
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
              "SELECT ?, id, 300001, 'manual', 't' FROM notas_fiscais WHERE numero=?", (rea, f"{int(nid):09d}"))
    c.commit()
    f = fechamento.fechamento(c)
    assert _mes(f, "2026-08")["protocolado_centavos"] == 1_000_001            # nao 2.000.002
    assert sorted(e["valor_centavos"] for e in f["em_aberto"]) == [300_001, 700_000]
    _confere_soma(f)


def test_notas_sem_medicao_em_aberto_e_pagas_e_em_aberto_antes_de_2025_ficam_a_parte(cenario):
    """(c) Sem medicao ligada, a nota nao tem competencia: a em aberto no RM e' linha propria (com a data da emissao,
    de qualquer ano), na cota, fora dos meses e do total; a paga so' e' contada (emitidas em 2025 e 2026). O em aberto
    de competencia anterior a 2025 tambem fica a' parte."""
    c, ids = cenario
    a = nota(c, 400_001, centro="9.001.001", emissao="2026-02-01")              # em aberto, obra pelo centro de custo
    v = nota(c, 999_999, centro="9.001.001", emissao="2024-12-01")              # em aberto de 2024: continua devida
    k = nota(c, 600_001, coligada=12, emissao="2025-10-01")                     # consorcio sem centro: pela coligada, 50%
    nota(c, 123_457, centro="9.001.001", emissao="2025-11-01", titulos=PAGO(111_111))     # paga: so' contada
    nota(c, 7_000, centro="9.001.001", emissao="2024-05-01", titulos=PAGO(6_300))         # paga e de 2024: nem contada
    velha = medir(c, ids["propria"], 1, "2024-11", "protocolada", 50_000, protocolo="2025-01-10")
    nota(c, 50_000, [velha])
    f = fechamento.fechamento(c)
    assert f["meses"] == [] and f["em_aberto"] == [] and _em_aberto(f) == 0
    s_m = f["notas_sem_medicao"]
    assert [(e["numero"], e["emissao"], e["obra"], e["valor_centavos"]) for e in s_m["em_aberto"]] == [
        (v, "2024-12-01", "Própria", 999_999), (k, "2025-10-01", "Consórcio", 300_001), (a, "2026-02-01", "Própria", 400_001)]
    assert s_m["em_aberto_centavos"] == 999_999 + 300_001 + 400_001
    assert s_m["pagas"] == {"quantidade": 1, "valor_centavos": 123_457}
    assert f["em_aberto_anteriores"] == {"quantidade": 1, "valor_centavos": 50_000}


def test_medicao_protocolada_sem_nota_ligada_entra_no_em_aberto_pelo_valor_da_medicao(cenario):
    """(b) A medicao protocolada (e nao recebida) sem nota ligada entra no em aberto pelo aprovado, senao o pedido, na
    cota, com a data do protocolo; a recebida sem nota nao (ja' entrou). Com nota ligada, conta a nota."""
    c, ids = cenario
    medir(c, ids["consorcio"], 1, "2026-04", "protocolada", 2_000_003, aprovado=1_000_001, protocolo="2026-05-04")
    medir(c, ids["propria"], 2, "2026-04", "nf_emitida", 300_000, protocolo="2026-05-02")
    medir(c, ids["propria"], 3, "2026-04", "recebida", 900_000, aprovado=900_000, protocolo="2026-05-01")
    f = fechamento.fechamento(c)
    m = _mes(f, "2026-04")
    assert (m["protocolado_centavos"], m["recebido_centavos"], m["sem_nota_centavos"], m["em_aberto_centavos"]) == (
        0, 0, 500_001 + 300_000, 500_001 + 300_000)                               # 1.000.001 x 50% = 500.001
    assert [(e["tipo_aberto"], e["obra"], e["medicao_numero"], e["protocolo_em"], e["valor_centavos"]) for e in f["em_aberto"]] == [
        ("sem_nota", "Própria", 2, "2026-05-02", 300_000), ("sem_nota", "Consórcio", 1, "2026-05-04", 500_001)]
    assert _em_aberto(f) == 800_001
    _confere_soma(f)


def test_medicao_sem_nota_e_nota_sem_medicao_nao_se_casam_nem_somam_duas_vezes(cenario):
    """A mesma cobranca pode aparecer como medicao sem nota (b) e como nota solta (c) enquanto o vinculo nao e' feito.
    Nao se casa por valor (docs/adr/0005): as duas listas aparecem, o total do em aberto e' (a)+(b) e (c) e' subtotal
    a' parte. Feito o vinculo, as duas viram uma nota protocolada (a), uma vez so'."""
    c, ids = cenario
    mid = medir(c, ids["propria"], 4, "2026-05", "protocolada", 250_000, aprovado=250_000, protocolo="2026-06-01")
    solta = nota(c, 250_000, centro="9.001.001", emissao="2026-05-28")
    f = fechamento.fechamento(c)
    assert [e["tipo_aberto"] for e in f["em_aberto"]] == ["sem_nota"]
    assert [e["numero"] for e in f["notas_sem_medicao"]["em_aberto"]] == [solta]
    assert _em_aberto(f) == 250_000                                             # (c) fora da soma
    assert f["notas_sem_medicao"]["em_aberto_centavos"] == 250_000
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
              "SELECT ?, id, 250000, 'manual', 't' FROM notas_fiscais WHERE numero=?", (mid, f"{int(solta):09d}"))
    c.commit()
    f = fechamento.fechamento(c)
    assert [(e["tipo_aberto"], e["numero"]) for e in f["em_aberto"]] == [("nota", solta)]
    assert f["notas_sem_medicao"]["em_aberto"] == [] and _em_aberto(f) == 250_000
    _confere_soma(f)


def test_aprovado_sem_valor_do_boletim_so_conta_com_a_nota_emitida(cenario):
    """GLOSSARY.md, Aprovado: sem o valor do boletim gravado, a medicao so' conta como aprovada (pelo pedido) com a
    nota emitida ou alem; antes disso fica so' no medido."""
    c, ids = cenario
    p = ids["propria"]
    medir(c, p, 1, "2026-07", "boletim_recebido", 100_001)                      # sem valor do boletim: so' medido
    medir(c, p, 2, "2026-07", "espelho_enviado", 200_000)
    medir(c, p, 3, "2026-07", "espelho_gerado", 300_000, aprovado=290_000)      # com o valor: aprovado
    medir(c, p, 4, "2026-07", "nota_emitida", 400_000)                          # nota emitida: o pedido conta
    m = _mes(fechamento.fechamento(c), "2026-07")
    assert (m["medido_centavos"], m["aprovado_centavos"]) == (100_001 + 200_000 + 290_000 + 400_000, 290_000 + 400_000)


def test_cobertura_do_vinculo_por_ano(cenario):
    """Por ano, quanto do aprovado das medicoes com nota emitida (ou alem) tem nota ligada; a aprovada antes da nota
    nao entra na base."""
    c, ids = cenario
    p = ids["propria"]
    a = medir(c, p, 1, "2025-03", "recebida", 600_000, aprovado=600_000, protocolo="2025-04-01")
    nota(c, 600_000, [a], titulos=PAGO(540_000))
    medir(c, p, 2, "2025-04", "recebida", 300_001, aprovado=300_001, protocolo="2025-05-01")      # paga, sem nota ligada
    medir(c, p, 3, "2025-05", "espelho_gerado", 999_999, aprovado=999_999)                       # antes da nota: fora
    b = medir(c, p, 4, "2026-01", "protocolada", 100_000, aprovado=100_000, protocolo="2026-02-01")
    nota(c, 100_000, [b])
    f = fechamento.fechamento(c)
    assert f["cobertura"]["2025"] == {"aprovado_centavos": 900_001, "com_nota_centavos": 600_000,
                                      "sem_nota_centavos": 300_001, "medicoes_sem_nota": 1, "percentual": 66.7}
    assert f["cobertura"]["2026"]["sem_nota_centavos"] == 0 and f["cobertura"]["2026"]["percentual"] == 100.0


def test_sem_o_total_a_receber_liberado_nem_o_em_aberto_nem_o_que_deixa_deduzi_lo(cenario):
    """A trava `geral.yaml: diretoria.total_a_receber_liberado` (a da lista de Obras e do Inicio): sem ela, o em
    aberto nao sai do servidor, nem o recebido (protocolado - recebido e' o em aberto das notas), nem a marca de
    recebida de cada nota, nem as listas. Medido, aprovado e protocolado continuam."""
    import json
    c, ids = cenario
    mid = medir(c, ids["propria"], 1, "2026-03", "protocolada", 500_000, protocolo="2026-04-01")
    nota(c, 500_000, [mid], titulos=[(465_000, 400_000, 4)])                  # paga em parte
    paga = medir(c, ids["propria"], 3, "2026-03", "protocolada", 90_000, protocolo="2026-04-01")
    nota(c, 90_000, [paga], titulos=PAGO(83_000))
    medir(c, ids["propria"], 2, "2026-03", "protocolada", 70_000, protocolo="2026-04-02")
    nota(c, 1_000, centro="9.001.001", emissao="2026-03-02")
    nota(c, 2_000, centro="9.001.001", emissao="2026-03-03", titulos=PAGO(1_800))
    velha = medir(c, ids["propria"], 9, "2024-11", "protocolada", 50_000, protocolo="2025-01-10")
    nota(c, 50_000, [velha])
    assert fechamento.fechamento(c)["por_ano"]["2026"]["recebido_centavos"] == 90_000 + 435_000
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'", (json.dumps({"total_a_receber_liberado": False}),))
    c.commit()
    f = fechamento.fechamento(c)
    assert f["total_a_receber_liberado"] is False
    m = _mes(f, "2026-03")
    assert (m["medido_centavos"], m["aprovado_centavos"], m["protocolado_centavos"]) == (660_000, 660_000, 590_000)
    escondidos = ("recebido_centavos", "em_aberto_centavos", "em_aberto_notas_centavos", "em_aberto_repasse_centavos",
                  "sem_nota_centavos")
    niveis = [m, f["por_ano"]["2026"], f["por_ano"]["2025"], f["acumulado"]["2026"], f["acumulado"]["2025"],
              *m["obras"], *m["obras"][0]["medicoes"]]
    assert all(x[k] is None for x in niveis for k in escondidos)
    for md in m["obras"][0]["medicoes"]:
        assert md["sem_nota"] is False
        for n in md["notas"]:
            assert n["valor_centavos"] and (n["recebida"], n["paga_em_parte"], n["aguarda_repasse"], n["recebido_centavos"],
                                            n["em_aberto_centavos"]) == (None, None, None, None, None)
    assert f["em_aberto"] == [] and f["em_aberto_anteriores"] == {"quantidade": 0, "valor_centavos": None}
    assert f["notas_sem_medicao"] == {"em_aberto": [], "em_aberto_centavos": None,
                                      "pagas": {"quantidade": 0, "valor_centavos": None}}
    # nenhum numero do recebido nem do em aberto sobra na resposta
    texto = json.dumps(f)
    assert all(str(v) not in texto for v in (435_000, 65_000, 525_000, 135_000, 83_000))
    # nem o estado da medicao (revisao da PR #754): com ele e o protocolado dava para refazer o em aberto ao centavo
    assert '"estado"' not in texto and '"protocolada"' not in texto and '"recebida"' not in texto.replace('"recebida":', "")


def test_o_estado_da_medicao_nao_sai_na_resposta_com_ou_sem_a_trava(cenario):
    """Revisao da PR #754: a tela nao usa o estado da medicao, e ele deixava deduzir o em aberto com o total a receber
    nao liberado (medicao protocolada: as notas dela em aberto; recebida: pagas). O campo saiu da resposta nos dois
    casos, e duas medicoes que so' diferem no estado saem iguais com a trava."""
    c, ids = cenario
    aberta = medir(c, ids["propria"], 1, "2026-03", "protocolada", 500_001, protocolo="2026-04-01")
    paga = medir(c, ids["propria"], 2, "2026-03", "recebida", 500_001, protocolo="2026-04-01")
    for mid in (aberta, paga):
        nota(c, 500_001, [mid], titulos=[])                # sem titulo no RM: so' o estado separa as duas
    def linhas():
        f = fechamento.fechamento(c)
        return f, {md["medicao_id"]: md for md in _mes(f, "2026-03")["obras"][0]["medicoes"]}
    f, por = linhas()
    assert all("estado" not in md for md in por.values())
    assert (por[aberta]["em_aberto_centavos"], por[paga]["em_aberto_centavos"]) == (500_001, 0)   # liberado: a tela diz
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'", (json.dumps({"total_a_receber_liberado": False}),))
    c.commit()
    f, por = linhas()
    sem_o_que_identifica = lambda md: {k: v for k, v in md.items() if k not in ("medicao_id", "numero", "notas")} | {
        "notas": [{k: v for k, v in n.items() if k not in ("nota_id", "numero")} for n in md["notas"]]}
    assert sem_o_que_identifica(por[aberta]) == sem_o_que_identifica(por[paga])
    assert '"estado"' not in json.dumps(f)


def _tipos_extras(c, contrato_id, *tipos):
    """O que o `cadastro aplicar` grava em `contratos.tipos_cobranca_extras_rm` (docs/adr/0015)."""
    c.execute("UPDATE contratos SET tipos_cobranca_extras_rm=? WHERE id=?",
              (json.dumps(list(tipos)) if tipos else None, contrato_id))
    c.commit()


def test_nota_de_tipo_extra_conta_so_no_contrato_que_o_declara(cenario):
    """docs/adr/0015: a pagina decide se a nota ligada e' cobranca por `cobranca_orgao.e_cobranca`, com o contrato da
    medicao. A nota de tipo 2.2.03 conta no protocolado, no recebido, no em aberto e na cobertura so' na obra cujo
    cadastro declara o tipo; na obra que nao declara, a medicao segue "sem nota ligada", mesmo com a outra obra
    declarando. Tipo que ninguem declara (2.2.15) fica fora nas duas. Consorcio a 50% com centavo impar."""
    c, ids = cenario
    p, k = ids["propria"], ids["consorcio"]
    a = medir(c, p, 1, "2026-03", "protocolada", 250_001, aprovado=250_001, protocolo="2026-04-05")
    b = medir(c, k, 1, "2026-03", "protocolada", 333_333, aprovado=333_333, protocolo="2026-04-06")
    na = nota(c, 250_001, [a], codtmv="2.2.03", titulos=PAGO(250_001))
    nb = nota(c, 333_333, [b], coligada=12, codtmv="2.2.03")               # a fatura do consorcio, titulo aberto
    nota(c, 60_001, [a], codtmv="2.2.15")                                  # nota do fornecedor: em nenhuma
    nota(c, 60_001, [b], coligada=12, codtmv="2.2.15")

    def retrato():
        f = fechamento.fechamento(c)
        _confere_soma(f)
        por = {md["medicao_id"]: md for o in _mes(f, "2026-03")["obras"] for md in o["medicoes"]}
        return ({x: (_numeros(por[x])[2:], por[x]["sem_nota"], [n["numero"] for n in por[x]["notas"]]) for x in (a, b)},
                _numeros(f["por_ano"]["2026"]), f["cobertura"]["2026"]["medicoes_sem_nota"])
    # (protocolado, recebido, em aberto); 333.333 x 50% = 166.666,5 -> 166.667
    sem_nota_a, sem_nota_b = ((0, 0, 250_001), True, []), ((0, 0, 166_667), True, [])
    com_nota_a, com_nota_b = ((250_001, 250_001, 0), False, [na]), ((166_667, 0, 166_667), False, [nb])
    medido = 250_001 + 166_667
    ninguem = ({a: sem_nota_a, b: sem_nota_b}, (medido, medido, 0, 0, medido), 2)
    assert retrato() == ninguem                    # ninguem declara: como antes da regra
    _tipos_extras(c, p, "2.2.03")                  # so' a propria declara: a do consorcio continua fora
    assert retrato() == ({a: com_nota_a, b: sem_nota_b}, (medido, medido, 250_001, 250_001, 166_667), 1)
    _tipos_extras(c, p)
    _tipos_extras(c, k, "2.2.03")                  # so' o consorcio declara: a da propria continua fora
    assert retrato() == ({a: sem_nota_a, b: com_nota_b}, (medido, medido, 166_667, 0, medido), 1)
    _tipos_extras(c, p, "2.2.03")                  # as duas declaram
    assert retrato() == ({a: com_nota_a, b: com_nota_b}, (medido, medido, medido, 250_001, 166_667), 0)
    _tipos_extras(c, p)
    _tipos_extras(c, k)
    assert retrato() == ninguem


def test_nota_da_empresa_de_tipo_extra_conta_pela_face_no_consorcio_que_o_declara(cenario):
    """docs/adr/0015 com a regra da #756: no contrato em nome do consorcio, a nota da PROPRIA empresa (outra coligada)
    de tipo 2.2.03, ligada a' medicao, so' conta quando o contrato declara o tipo; ai' vale a regra da cota: pela
    face, sem multiplicar pelo percentual, e a fatura do consorcio ligada a' mesma medicao sai da conta. Sem a
    declaracao, a medicao conta pela fatura do consorcio vezes a cota, como se a nota da empresa nao estivesse la'."""
    c, ids = cenario
    k = ids["consorcio"]
    mid = medir(c, k, 1, "2026-03", "protocolada", 333_333, aprovado=333_333, protocolo="2026-04-06")
    fatura = nota(c, 333_333, [mid], coligada=12)                          # do consorcio, tipo da lista geral, aberta
    da_empresa = nota(c, 166_667, [mid], coligada=1, codtmv="2.2.03", titulos=PAGO(166_667))

    def retrato():
        f = fechamento.fechamento(c)
        _confere_soma(f)
        md = _mes(f, "2026-03")["obras"][0]["medicoes"][0]
        return (_numeros(md)[2:], [n["numero"] for n in md["notas"]], [n["numero"] for n in md["notas_fora_da_conta"]])
    assert retrato() == ((166_667, 0, 166_667), [fatura], [])
    _tipos_extras(c, k, "2.2.03")
    assert retrato() == ((166_667, 166_667, 0), [da_empresa], [fatura])
    _tipos_extras(c, ids["propria"], "2.2.03")     # declarado em OUTRA obra nao vale para esta
    _tipos_extras(c, k)
    assert retrato() == ((166_667, 0, 166_667), [fatura], [])


def test_nota_paga_em_parte_ligada_a_medicao_fica_em_aberto_pelo_que_falta_nos_titulos(cenario):
    """Nota com alguma baixa COM VALOR no RM e falta acima da tolerancia: o em aberto e' o que falta nos titulos, na
    cota, limitado ao valor da nota; o recebido e' o valor bruto menos a falta, e protocolado - recebido = em aberto
    continua fechando. Sem baixa com valor, a nota fica inteira em aberto, pelo bruto."""
    c, ids = cenario
    p, k = ids["propria"], ids["consorcio"]
    a = medir(c, p, 1, "2026-05", "protocolada", 1_000_000, aprovado=1_000_000, protocolo="2026-06-01")
    meia = nota(c, 1_000_000, [a], titulos=[(465_000, 465_000, 1), (465_000, 0, 0)])          # um titulo pago, outro aberto
    b = medir(c, k, 2, "2026-05", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-06-02")
    cons = nota(c, 2_000_001, [b], coligada=12, titulos=[(1_800_001, 900_000, 4)])           # baixa parcial, centavo impar
    d = medir(c, p, 3, "2026-05", "protocolada", 600_000, aprovado=600_000, protocolo="2026-06-03")
    glosa = nota(c, 600_000, [d], titulos=[(500_000, 500_000, 1), (58_000, 0, 1)])           # titulo baixado sem valor
    e = medir(c, p, 4, "2026-05", "protocolada", 100_000, aprovado=100_000, protocolo="2026-06-04")
    teto = nota(c, 100_000, [e], titulos=[(90_000, 10_000, 4), (90_000, 0, 0)])              # falta acima do valor da nota
    g = medir(c, p, 5, "2026-05", "protocolada", 300_000, aprovado=300_000, protocolo="2026-06-05")
    nota(c, 300_000, [g], titulos=[(279_000, 278_900, 1)])                                   # faltam R$ 1,00: paga
    h = medir(c, p, 6, "2026-05", "protocolada", 300_000, aprovado=300_000, protocolo="2026-06-06")
    um = nota(c, 300_000, [h], titulos=[(279_000, 278_899, 4)])                              # faltam R$ 1,01: em parte
    i = medir(c, p, 7, "2026-05", "protocolada", 200_000, aprovado=200_000, protocolo="2026-06-07")
    inteira = nota(c, 200_000, [i], titulos=[(186_000, 0, 0)])                               # nenhuma baixa: pelo bruto
    f = fechamento.fechamento(c)
    assert [(x["numero"], x["valor_centavos"], x["paga_em_parte"]) for x in f["em_aberto"]] == [
        (meia, 465_000, True),
        (cons, 450_001, True),                       # falta 900.001 x 50% = 450.000,5 -> 450.001
        (glosa, 58_000, True), (teto, 100_000, False), (um, 101, True), (inteira, 200_000, False)]
    m = _mes(f, "2026-05")
    protocolado = 1_000_000 + 1_000_001 + 600_000 + 100_000 + 300_000 + 300_000 + 200_000
    aberto = 465_000 + 450_001 + 58_000 + 100_000 + 101 + 200_000
    assert (m["protocolado_centavos"], m["recebido_centavos"], m["em_aberto_centavos"]) == (
        protocolado, protocolado - aberto, aberto)
    md = next(x for o in m["obras"] for x in o["medicoes"] if x["medicao_id"] == b)
    assert md["notas"] == [{"nota_id": md["notas"][0]["nota_id"], "numero": cons, "valor_centavos": 1_000_001,
                            "recebido_centavos": 550_000, "em_aberto_centavos": 450_001, "recebida": False,
                            "paga_em_parte": True, "aguarda_repasse": False}]
    assert f["por_ano"]["2026"]["em_aberto_centavos"] == aberto and f["por_ano"]["2026"]["sem_nota_centavos"] == 0
    _confere_soma(f)


def test_nota_paga_em_parte_ligada_a_duas_medicoes_reparte_a_falta_com_residuo(cenario):
    """A falta e' da nota: ligada a duas medicoes, reparte-se na proporcao do valor de cada vinculo, e o centavo que
    sobra vai a uma delas (`dinheiro.ratear_proporcional`): a soma das partes e' a falta, ao centavo."""
    c, ids = cenario
    p = ids["propria"]
    exe = medir(c, p, 1, "2026-08", "protocolada", 700_000, protocolo="2026-09-01")
    rea = medir(c, p, 1, "2026-08", "protocolada", 300_001, tipo="reajuste", protocolo="2026-09-01")
    nid = nota(c, 1_000_001, [exe], alocado=700_000, titulos=[(930_000, 430_000, 4)])       # faltam 500.000
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
              "SELECT ?, id, 300001, 'manual', 't' FROM notas_fiscais WHERE numero=?", (rea, f"{int(nid):09d}"))
    c.commit()
    f = fechamento.fechamento(c)
    # 500.000 x 700.000 / 1.000.001 = 349.999,65 e 500.000 x 300.001 / 1.000.001 = 150.000,35: o centavo vai ao maior resto
    assert sorted((e["tipo"], e["valor_centavos"], e["paga_em_parte"]) for e in f["em_aberto"]) == [
        ("execucao", 350_000, True), ("reajuste", 150_000, True)]
    m = _mes(f, "2026-08")
    assert (m["protocolado_centavos"], m["recebido_centavos"], m["em_aberto_centavos"]) == (1_000_001, 500_001, 500_000)
    _confere_soma(f)


def test_nota_sem_medicao_com_baixa_quase_total_aparece_pelo_que_falta(cenario):
    """(c) A nota sem medicao ligada com baixa quase total no RM aparece pelo que falta nos titulos (na cota, marcada
    paga em parte), nao pelo valor bruto inteiro; sem baixa com valor, pelo bruto; quitada dentro da tolerancia, so'
    contada entre as pagas."""
    c, ids = cenario
    quase = nota(c, 1_000_001, centro="9.001.001", emissao="2024-09-10", titulos=[(1_000_001, 995_000, 4)])
    cons = nota(c, 600_001, coligada=12, emissao="2025-10-01", titulos=[(560_001, 500_000, 4)])     # falta 60.001 x 50%
    sem_valor = nota(c, 80_000, centro="9.001.001", emissao="2026-01-05", titulos=[(74_000, 0, 1)])   # baixada sem valor
    nota(c, 90_000, centro="9.001.001", emissao="2026-02-01", titulos=[(83_000, 82_900, 1)])        # faltam R$ 1,00: paga
    f = fechamento.fechamento(c)
    s_m = f["notas_sem_medicao"]
    assert [(e["numero"], e["obra"], e["valor_centavos"], e["paga_em_parte"]) for e in s_m["em_aberto"]] == [
        (quase, "Própria", 5_001, True), (cons, "Consórcio", 30_001, True), (sem_valor, "Própria", 80_000, False)]
    assert s_m["em_aberto_centavos"] == 5_001 + 30_001 + 80_000
    assert s_m["pagas"] == {"quantidade": 1, "valor_centavos": 90_000}
    assert f["em_aberto"] == [] and _em_aberto(f) == 0                          # continua fora dos meses e do total


def test_o_em_aberto_de_cada_ano_fecha_com_as_linhas_do_ano(cenario):
    """O painel "Em aberto" segue o ano escolhido: o total e as duas partes de cada ano estao em `por_ano` e fecham com
    as linhas daquele ano (pela competencia da medicao), com nota paga em parte e medicao sem nota nos dois anos."""
    c, ids = cenario
    p = ids["propria"]
    a = medir(c, p, 1, "2025-10", "protocolada", 400_001, aprovado=400_001, protocolo="2025-11-20")
    nota(c, 400_001, [a], titulos=[(372_001, 300_000, 4)])                    # 2025: paga em parte, faltam 72.001
    medir(c, p, 2, "2025-12", "protocolada", 50_001, protocolo="2026-01-15")  # 2025: sem nota ligada
    b = medir(c, p, 3, "2026-02", "protocolada", 800_000, aprovado=800_000, protocolo="2026-03-20")
    nota(c, 800_000, [b])                                                     # 2026: nota inteira em aberto
    medir(c, p, 4, "2026-04", "nf_emitida", 30_003, protocolo="2026-05-11")   # 2026: sem nota ligada
    f = fechamento.fechamento(c)
    assert {a_: (t["em_aberto_centavos"], t["em_aberto_notas_centavos"], t["sem_nota_centavos"])
            for a_, t in f["por_ano"].items()} == {"2025": (122_002, 72_001, 50_001), "2026": (830_003, 800_000, 30_003)}
    assert "em_aberto_centavos" not in f                                      # nao ha' total dos dois anos na pagina
    assert f["por_ano"]["2025"]["recebido_centavos"] == 400_001 - 72_001
    _confere_soma(f)


def test_soma_fecha_ao_centavo_em_dois_anos_com_consorcio(cenario):
    """Cenario misto em 2025 e 2026: cada total da pagina e' a soma das linhas abertas, ao centavo."""
    c, ids = cenario
    p, k = ids["propria"], ids["consorcio"]
    for i, comp in enumerate(("2025-03", "2025-11", "2026-03", "2026-10")):
        a = medir(c, p, 10 + i, comp, "protocolada", 123_457 + i, aprovado=123_455 + i, protocolo=f"{comp}-28")
        nota(c, 100_001 + i, [a], titulos=PAGO(90_001) if i % 2 else None)
        nota(c, 23_454, [a])
        b = medir(c, k, 10 + i, comp, "recebida", 777_777 + i, protocolo=f"{comp}-27")
        nota(c, 777_777 + i, [b], coligada=12)
        medir(c, k, 20 + i, comp, "boletim_recebido", 33_333, aprovado=33_331)
        medir(c, p, 30 + i, comp, "planilha_enviada", 5)
    f = fechamento.fechamento(c)
    assert len(f["meses"]) == 4 and f["por_ano"]["2025"]["meses"] == f["por_ano"]["2026"]["meses"] == 2
    assert f["acumulado"]["ate_mes"] == "10"
    for k_ in NUMEROS:
        assert f["acumulado"]["2026"][k_] == f["por_ano"]["2026"][k_]
    _confere_soma(f)


# ---------------------------------------------------------------- consorcio: a nota da propria empresa (issue #756)

def _medicao(f, mid):
    return next(md for m in f["meses"] for o in m["obras"] for md in o["medicoes"] if md["medicao_id"] == mid)


def _ligar(c, mid, numero, valor):
    """Mais um vinculo da mesma nota, em outra medicao, pelo valor dado."""
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
              "SELECT ?, id, ?, 'manual', 't' FROM notas_fiscais WHERE numero=?", (mid, valor, f"{int(numero):09d}"))
    c.commit()


def test_consorcio_so_com_a_fatura_do_consorcio_ligada_vale_ela_vezes_a_cota(exemplo):
    """(a) Sem a nota da empresa ligada, continua a fatura do consorcio, valor cheio vezes a cota."""
    c, k = exemplo
    mid = medir(c, k, 1, "2026-03", "protocolada", 2_400_003, aprovado=2_400_003, protocolo="2026-04-10")
    fatura = nota(c, 2_400_003, [mid], coligada=CONSORCIO, titulos=[(2_232_003, 1_000_000, 4)])     # faltam 1.232.003
    f = fechamento.fechamento(c)
    md = _medicao(f, mid)
    # 2.400.003 x 50% = 1.200.001,5 -> 1.200.002; a falta 1.232.003 x 50% = 616.001,5 -> 616.002
    assert _numeros(md) == (1_200_002, 1_200_002, 1_200_002, 1_200_002 - 616_002, 616_002)
    assert [(n["numero"], n["valor_centavos"], n["paga_em_parte"]) for n in md["notas"]] == [(fatura, 1_200_002, True)]
    assert md["notas_fora_da_conta"] == [] and md["sem_nota"] is False
    _confere_soma(f)


def test_consorcio_so_com_a_nota_da_empresa_ligada_vale_ela_pela_face(exemplo):
    """(b) A nota da propria empresa ao consorcio ja' e' a cota: entra pelo valor de face, sem o percentual, e o
    recebido sai da baixa dos titulos dela. A medicao deixa de aparecer como "sem nota ligada"."""
    c, k = exemplo
    aberta = medir(c, k, 1, "2026-03", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-04-10")
    n1 = nota(c, 999_999, [aberta], coligada=EMPRESA, centro="5.001.001")       # face impar; x 50% daria 500.000
    paga = medir(c, k, 2, "2026-03", "protocolada", 600_001, aprovado=600_001, protocolo="2026-04-11")
    n2 = nota(c, 300_001, [paga], coligada=EMPRESA, centro="5.001.001", titulos=PAGO(279_001))
    f = fechamento.fechamento(c)
    a, p = _medicao(f, aberta), _medicao(f, paga)
    # medido e aprovado continuam o valor cheio da medicao vezes a cota (2.000.001 x 50% -> 1.000.001; 600.001 -> 300.001)
    assert _numeros(a) == (1_000_001, 1_000_001, 999_999, 0, 999_999)
    assert _numeros(p) == (300_001, 300_001, 300_001, 300_001, 0)
    assert [(n["numero"], n["valor_centavos"], n["recebida"]) for n in a["notas"]] == [(n1, 999_999, False)]
    assert [(n["numero"], n["valor_centavos"], n["recebida"]) for n in p["notas"]] == [(n2, 300_001, True)]
    assert a["sem_nota"] is False and a["sem_nota_centavos"] == 0 and a["notas_fora_da_conta"] == []
    assert [(e["tipo_aberto"], e["numero"], e["valor_centavos"]) for e in f["em_aberto"]] == [("nota", n1, 999_999)]
    _confere_soma(f)


def test_consorcio_com_as_duas_ligadas_conta_so_a_nota_da_empresa(exemplo):
    """(c) Com a nota da empresa ligada, a fatura do consorcio ligada a' MESMA medicao nao entra na conta: nem no
    protocolado, nem no recebido, nem no em aberto, esteja ela paga ou nao no RM. Aparece na medicao, sem valor."""
    c, k = exemplo
    m1 = medir(c, k, 1, "2026-03", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-04-10")
    fat1 = nota(c, 2_400_003, [m1], coligada=CONSORCIO, titulos=PAGO(2_232_003))     # a fatura paga nao quita a da empresa
    emp1 = nota(c, 1_000_001, [m1], coligada=EMPRESA, centro="5.001.001")
    m2 = medir(c, k, 2, "2026-03", "protocolada", 800_001, aprovado=800_001, protocolo="2026-04-11")
    fat2 = nota(c, 800_001, [m2], coligada=CONSORCIO)                                # a fatura aberta nao segura a da empresa
    emp2 = nota(c, 400_001, [m2], coligada=EMPRESA, centro="5.001.001", titulos=PAGO(372_001))
    f = fechamento.fechamento(c)
    a, b = _medicao(f, m1), _medicao(f, m2)
    assert _numeros(a) == (1_000_001, 1_000_001, 1_000_001, 0, 1_000_001)           # e nao 1.200.002 nem 2.200.003
    assert _numeros(b) == (400_001, 400_001, 400_001, 400_001, 0)
    assert [n["numero"] for n in a["notas"]] == [emp1] and [n["numero"] for n in b["notas"]] == [emp2]
    assert [n["numero"] for n in a["notas_fora_da_conta"]] == [fat1]
    assert [n["numero"] for n in b["notas_fora_da_conta"]] == [fat2]
    assert _numeros(_mes(f, "2026-03")) == (1_400_002, 1_400_002, 1_400_002, 400_001, 1_000_001)
    assert [(e["numero"], e["valor_centavos"]) for e in f["em_aberto"]] == [(emp1, 1_000_001)]
    # a fatura preterida esta' ligada a medicao: tambem nao vira "nota sem medicao ligada"
    assert f["notas_sem_medicao"]["em_aberto"] == [] and f["notas_sem_medicao"]["pagas"]["quantidade"] == 0
    _confere_soma(f)


def test_consorcio_nota_da_empresa_paga_em_parte_fica_pelo_que_falta_sem_aplicar_a_cota(exemplo):
    """(d) A regra da nota paga em parte vale igual: o em aberto e' o que falta nos titulos da nota da empresa, que ja'
    e' a cota (nao se multiplica pelo percentual), limitado ao valor dela; o recebido e' a face menos a falta."""
    c, k = exemplo
    mid = medir(c, k, 1, "2026-05", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-06-01")
    nota(c, 2_000_001, [mid], coligada=CONSORCIO, titulos=PAGO(1_860_001))           # a do consorcio, quitada: fora
    emp = nota(c, 1_000_001, [mid], coligada=EMPRESA, centro="5.001.001", titulos=[(930_001, 400_000, 4)])
    teto = medir(c, k, 2, "2026-05", "protocolada", 200_001, aprovado=200_001, protocolo="2026-06-02")
    nota(c, 100_001, [teto], coligada=EMPRESA, centro="5.001.001", titulos=[(90_000, 10_000, 4), (90_000, 0, 0)])
    quase = medir(c, k, 3, "2026-05", "protocolada", 600_001, aprovado=600_001, protocolo="2026-06-03")
    nota(c, 300_001, [quase], coligada=EMPRESA, centro="5.001.001", titulos=[(279_001, 278_901, 1)])   # faltam R$ 1,00
    f = fechamento.fechamento(c)
    md = _medicao(f, mid)
    # faltam 530.001 nos titulos da nota da empresa: e' o em aberto (x 50% daria 265.001)
    assert md["notas"] == [{"nota_id": md["notas"][0]["nota_id"], "numero": emp, "valor_centavos": 1_000_001,
                            "recebido_centavos": 470_000, "em_aberto_centavos": 530_001, "recebida": False,
                            "paga_em_parte": True, "aguarda_repasse": False}]
    assert _numeros(md) == (1_000_001, 1_000_001, 1_000_001, 470_000, 530_001)
    # a falta (170.000) acima do valor da nota fica no teto; ate' R$ 1,00 de falta, paga
    assert _numeros(_medicao(f, teto))[2:] == (100_001, 0, 100_001)
    assert _numeros(_medicao(f, quase))[2:] == (300_001, 300_001, 0)
    assert [(e["valor_centavos"], e["paga_em_parte"]) for e in f["em_aberto"]] == [(530_001, True), (100_001, False)]
    _confere_soma(f)


def test_consorcio_execucao_com_nota_da_empresa_e_reajuste_com_fatura_do_consorcio_no_mesmo_mes(exemplo):
    """(e) A escolha e' por medicao: no mesmo mes, a execucao com a nota da empresa conta pela face e o reajuste, so'
    com a fatura do consorcio, conta por ela vezes a cota. A fatura do consorcio ligada as duas (pelo valor de cada
    vinculo) fica fora na execucao e entra no reajuste pelo valor do vinculo dele."""
    c, k = exemplo
    exe = medir(c, k, 5, "2026-06", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-07-10")
    rea = medir(c, k, 5, "2026-06", "protocolada", 300_003, aprovado=300_003, tipo="reajuste", protocolo="2026-07-10")
    emp = nota(c, 1_000_001, [exe], coligada=EMPRESA, centro="5.001.001", titulos=PAGO(930_001))
    fat = nota(c, 300_003, [rea], coligada=CONSORCIO)
    f = fechamento.fechamento(c)
    e, r = _medicao(f, exe), _medicao(f, rea)
    assert _numeros(e) == (1_000_001, 1_000_001, 1_000_001, 1_000_001, 0)
    assert _numeros(r) == (150_002, 150_002, 150_002, 0, 150_002)                # 300.003 x 50% = 150.001,5 -> 150.002
    assert [n["numero"] for n in e["notas"]] == [emp] and [n["numero"] for n in r["notas"]] == [fat]
    assert e["notas_fora_da_conta"] == r["notas_fora_da_conta"] == []
    assert _numeros(_mes(f, "2026-06")) == (1_150_003, 1_150_003, 1_150_003, 1_000_001, 150_002)
    _confere_soma(f)
    # a mesma fatura do consorcio passa a cobrir tambem a execucao: la' fica fora da conta; no reajuste, o vinculo dele
    c.execute("UPDATE nf_alocacoes SET valor_alocado_centavos=200003 WHERE medicao_id=?", (rea,))
    _ligar(c, exe, fat, 100_000)
    f = fechamento.fechamento(c)
    e, r = _medicao(f, exe), _medicao(f, rea)
    assert _numeros(e) == (1_000_001, 1_000_001, 1_000_001, 1_000_001, 0)
    assert [n["numero"] for n in e["notas_fora_da_conta"]] == [fat]
    assert _numeros(r) == (150_002, 150_002, 100_002, 0, 100_002)                # 200.003 x 50% = 100.001,5 -> 100.002
    _confere_soma(f)


def test_consorcio_nota_da_empresa_ligada_a_duas_medicoes_entra_pelo_valor_do_vinculo_sem_cota(exemplo):
    """A nota da empresa ligada a' execucao e ao reajuste entra em cada um pelo valor do vinculo, pela face; paga em
    parte, a falta reparte-se na proporcao dos vinculos, com o centavo de residuo, tambem sem a cota."""
    c, k = exemplo
    exe = medir(c, k, 1, "2026-08", "protocolada", 1_400_000, protocolo="2026-09-01")
    rea = medir(c, k, 1, "2026-08", "protocolada", 600_002, tipo="reajuste", protocolo="2026-09-01")
    nid = nota(c, 1_000_001, [exe], coligada=EMPRESA, centro="5.001.001", alocado=700_000,
               titulos=[(930_000, 430_000, 4)])                                  # faltam 500.000
    _ligar(c, rea, nid, 300_001)
    f = fechamento.fechamento(c)
    # 500.000 x 700.000 / 1.000.001 = 349.999,65 e 500.000 x 300.001 / 1.000.001 = 150.000,35: o centavo vai ao maior resto
    assert sorted((e["tipo"], e["valor_centavos"], e["paga_em_parte"]) for e in f["em_aberto"]) == [
        ("execucao", 350_000, True), ("reajuste", 150_000, True)]
    assert (_medicao(f, exe)["protocolado_centavos"], _medicao(f, rea)["protocolado_centavos"]) == (700_000, 300_001)
    m = _mes(f, "2026-08")
    assert (m["protocolado_centavos"], m["recebido_centavos"], m["em_aberto_centavos"]) == (1_000_001, 500_001, 500_000)
    _confere_soma(f)


def test_consorcio_cobertura_do_vinculo_conta_a_nota_da_empresa(exemplo):
    """(f) A medicao de consorcio com a nota da empresa ligada conta como coberta, como a que tem a fatura do
    consorcio; so' com a NFS-e de outra consorciada, ou sem nota, nao."""
    c, k = exemplo
    a = medir(c, k, 1, "2026-01", "recebida", 2_000_001, aprovado=2_000_001, protocolo="2026-02-01")
    nota(c, 1_000_001, [a], coligada=EMPRESA, centro="5.001.001", titulos=PAGO(930_001))
    b = medir(c, k, 2, "2026-02", "nota_emitida", 400_001, aprovado=400_001)
    nota(c, 200_001, [b], coligada=EMPRESA, centro="5.001.001")                 # ainda nao protocolada: ja' cobre
    d = medir(c, k, 3, "2026-03", "protocolada", 600_001, aprovado=600_001, protocolo="2026-04-01")
    nota(c, 600_001, [d], coligada=CONSORCIO)
    e = medir(c, k, 4, "2026-04", "protocolada", 100_001, aprovado=100_001, protocolo="2026-05-01")
    nota(c, 50_001, [e], coligada=OUTRA)                                        # de outra consorciada: nao cobre
    f = fechamento.fechamento(c)
    # a base e' o aprovado na cota: 1.000.001 + 200.001 + 300.001 + 50.001
    assert f["cobertura"]["2026"] == {"aprovado_centavos": 1_550_004, "com_nota_centavos": 1_500_003,
                                      "sem_nota_centavos": 50_001, "medicoes_sem_nota": 1, "percentual": 96.8}
    assert _medicao(f, b)["protocolado_centavos"] == 0 and _medicao(f, b)["notas"] == []
    assert _medicao(f, e)["sem_nota"] is True and _medicao(f, e)["sem_nota_centavos"] == 50_001
    _confere_soma(f)


def test_consorcio_nota_da_empresa_sem_medicao_ligada_nao_vira_nota_sem_medicao(exemplo):
    """O que NAO mudou: a nota da empresa ao consorcio sem vinculo com medicao nao aparece em lugar nenhum da pagina
    (a lista "nota sem medicao ligada" so' tem nota da coligada da entidade do contrato); ligada, entra na medicao e
    continua fora dessa lista. A fatura do consorcio sem medicao ligada segue na lista, vezes a cota."""
    c, k = exemplo
    mid = medir(c, k, 1, "2026-03", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-04-10")
    solta = nota(c, 1_000_001, coligada=EMPRESA, centro="5.001.001", emissao="2026-04-02")
    fatura = nota(c, 700_001, coligada=CONSORCIO, emissao="2026-04-03")
    f = fechamento.fechamento(c)
    assert [(e["numero"], e["valor_centavos"]) for e in f["notas_sem_medicao"]["em_aberto"]] == [(fatura, 350_001)]
    assert _medicao(f, mid)["sem_nota"] is True and _em_aberto(f) == 1_000_001   # (b), pelo valor da medicao
    _ligar(c, mid, solta, 1_000_001)
    f = fechamento.fechamento(c)
    assert [(e["tipo_aberto"], e["numero"], e["valor_centavos"]) for e in f["em_aberto"]] == [("nota", solta, 1_000_001)]
    assert [e["numero"] for e in f["notas_sem_medicao"]["em_aberto"]] == [fatura]
    _confere_soma(f)


def test_consorcio_com_a_trava_a_nota_fora_da_conta_aparece_sem_nada_do_recebido(exemplo):
    """Com o total a receber nao liberado, a medicao continua dizendo qual fatura ficou fora da conta (so' o numero);
    o recebido e o em aberto seguem escondidos."""
    import json
    c, k = exemplo
    mid = medir(c, k, 1, "2026-03", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-04-10")
    fat = nota(c, 2_000_001, [mid], coligada=CONSORCIO)
    nota(c, 1_000_001, [mid], coligada=EMPRESA, centro="5.001.001", titulos=[(930_001, 400_000, 4)])
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'", (json.dumps({"total_a_receber_liberado": False}),))
    c.commit()
    f = fechamento.fechamento(c)
    md = _medicao(f, mid)
    assert f["total_a_receber_liberado"] is False and md["protocolado_centavos"] == 1_000_001
    assert [set(n) for n in md["notas_fora_da_conta"]] == [{"nota_id", "numero"}]
    assert md["notas_fora_da_conta"][0]["numero"] == fat
    assert md["recebido_centavos"] is None and md["em_aberto_centavos"] is None
    assert all(str(v) not in json.dumps(f) for v in (470_000, 530_001))


def test_obra_propria_nao_muda_com_a_regra_do_consorcio(exemplo):
    """Em obra propria a nota da empresa e' a da entidade do contrato: valor da nota, sem nota fora da conta."""
    c, _ = exemplo
    p = c.execute("SELECT id FROM contratos WHERE nome_curto='Obra Própria'").fetchone()[0]
    mid = medir(c, p, 1, "2026-03", "protocolada", 500_001, aprovado=500_001, protocolo="2026-04-10")
    nota(c, 500_001, [mid], coligada=EMPRESA)
    nota(c, 500_001, [mid], coligada=CONSORCIO)                                 # nota de outra coligada: nao conta
    f = fechamento.fechamento(c)
    md = _medicao(f, mid)
    assert _numeros(md) == (500_001, 500_001, 500_001, 0, 500_001) and md["notas_fora_da_conta"] == []
    _confere_soma(f)


# ------------------------------------------- consorcio: o recebido da nota da empresa so' pela baixa dos titulos dela

def _abertas(f):
    return [(e["numero"], e["valor_centavos"], e["paga_em_parte"]) for e in f["em_aberto"]]


def test_consorcio_medicao_recebida_a_nota_da_empresa_so_entra_no_recebido_pela_baixa_dos_titulos_dela(exemplo):
    """Decisao do dono de 17/11/2026 ("pela baixa do titulo", issue #756): a medicao de consorcio vira recebida quando o
    orgao paga a fatura do consorcio; a cota da empresa so' entrou quando o consorcio repassou. Com a nota da empresa
    ligada, o recebido e' so' o que foi baixado nos titulos DELA, e o em aberto e' a face menos isso. O estado da
    medicao nao muda."""
    c, k = exemplo
    # o orgao pagou o consorcio (fatura quitada, medicao recebida) e o consorcio ainda nao repassou: titulo em aberto
    aberta = medir(c, k, 1, "2026-09", "recebida", 2_000_001, aprovado=2_000_001, protocolo="2026-10-01")
    fat = nota(c, 2_000_001, [aberta], coligada=CONSORCIO, titulos=PAGO(1_860_001))
    n1 = nota(c, 1_000_001, [aberta], coligada=EMPRESA, centro="5.001.001", titulos=[(930_001, 0, 0)])
    # repassou uma parte: um titulo baixado em parte, com centavo impar
    parte = medir(c, k, 2, "2026-09", "recebida", 1_200_003, aprovado=1_200_003, protocolo="2026-10-02")
    nota(c, 1_200_003, [parte], coligada=CONSORCIO, titulos=PAGO(1_116_003))
    n2 = nota(c, 600_002, [parte], coligada=EMPRESA, centro="5.001.001", titulos=[(558_001, 200_000, 4)])   # faltam 358.001
    # repassou tudo: titulo baixado inteiro
    inteira = medir(c, k, 3, "2026-09", "recebida", 800_001, aprovado=800_001, protocolo="2026-10-03")
    nota(c, 800_001, [inteira], coligada=CONSORCIO, titulos=PAGO(744_001))
    n3 = nota(c, 400_001, [inteira], coligada=EMPRESA, centro="5.001.001", titulos=PAGO(372_001))
    f = fechamento.fechamento(c)
    a, p, i = _medicao(f, aberta), _medicao(f, parte), _medicao(f, inteira)
    assert _numeros(a) == (1_000_001, 1_000_001, 1_000_001, 0, 1_000_001)           # recebido zero, em aberto = a face
    assert _numeros(p) == (600_002, 600_002, 600_002, 242_001, 358_001)             # as duas partes somam a face
    assert _numeros(i) == (400_001, 400_001, 400_001, 400_001, 0)                   # tudo no recebido
    assert a["notas"] == [{"nota_id": a["notas"][0]["nota_id"], "numero": n1, "valor_centavos": 1_000_001,
                           "recebido_centavos": 0, "em_aberto_centavos": 1_000_001, "recebida": False,
                           "paga_em_parte": False, "aguarda_repasse": True}]
    assert [(n["numero"], n["recebido_centavos"], n["em_aberto_centavos"], n["recebida"], n["paga_em_parte"])
            for n in p["notas"] + i["notas"]] == [(n2, 242_001, 358_001, False, True), (n3, 400_001, 0, True, False)]
    # a fatura do consorcio quitada continua fora da conta: nao leva a nota da empresa ao recebido
    assert [n["numero"] for n in a["notas_fora_da_conta"]] == [fat]
    # o estado da medicao no banco nao muda; nenhuma vira "sem nota ligada"
    assert [r[0] for r in c.execute("SELECT estado FROM medicoes ORDER BY id")] == ["recebida"] * 3
    assert not (a["sem_nota"] or p["sem_nota"] or i["sem_nota"])
    # o em aberto da medicao recebida entra no mes, no ano e na lista, nota a nota, com a data do protocolo
    assert _numeros(_mes(f, "2026-09")) == (2_000_004, 2_000_004, 2_000_004, 642_002, 1_358_002)
    assert _abertas(f) == [(n1, 1_000_001, False), (n2, 358_001, True)]
    assert [e["protocolo_em"] for e in f["em_aberto"]] == ["2026-10-01", "2026-10-02"]
    t = f["por_ano"]["2026"]
    # o orgao ja' pagou: o em aberto e' do repasse (a'), nao de "nota protocolada nao paga" (a)
    assert [e["tipo_aberto"] for e in f["em_aberto"]] == ["repasse", "repasse"]
    assert (t["recebido_centavos"], t["em_aberto_centavos"], t["em_aberto_notas_centavos"], t["em_aberto_repasse_centavos"],
            t["sem_nota_centavos"]) == (642_002, 1_358_002, 0, 1_358_002, 0)
    assert f["notas_diferem"] == []
    _confere_soma(f)


def test_consorcio_medicao_recebida_nota_da_empresa_sem_baixa_com_valor_fica_inteira_em_aberto(exemplo):
    """As bordas da mesma regra: sem titulo nenhum no RM, so' lida do PDF (sem RM), com titulo baixado sem valor (glosa,
    compensacao), com a falta acima da face (teto) e com a medicao recebida pelo registro do administrador
    (docs/adr/0006), a nota da empresa so' entra no recebido pelo que os titulos dela mostram baixado."""
    c, k = exemplo
    uid = c.execute("SELECT id FROM usuarios").fetchone()[0]
    sem_titulo = medir(c, k, 1, "2026-08", "recebida", 2_000_001, aprovado=2_000_001, protocolo="2026-09-01")
    n1 = nota(c, 1_000_001, [sem_titulo], coligada=EMPRESA, centro="5.001.001", titulos=[])
    do_pdf = medir(c, k, 2, "2026-08", "recebida", 600_001, aprovado=600_001, protocolo="2026-09-02")
    n2 = nota(c, 300_001, [do_pdf], coligada=EMPRESA, codtmv=None, titulos=[])
    glosa = medir(c, k, 3, "2026-08", "recebida", 400_001, aprovado=400_001, protocolo="2026-09-03")
    n3 = nota(c, 200_001, [glosa], coligada=EMPRESA, centro="5.001.001", titulos=[(186_001, 0, 1)])
    teto = medir(c, k, 4, "2026-08", "recebida", 200_001, aprovado=200_001, protocolo="2026-09-04")
    n4 = nota(c, 100_001, [teto], coligada=EMPRESA, centro="5.001.001", titulos=[(90_000, 10_000, 4), (90_000, 0, 0)])
    a_mao = medir(c, k, 5, "2026-08", "protocolada", 1_000_001, aprovado=1_000_001, protocolo="2026-09-05")
    n5 = nota(c, 500_001, [a_mao], coligada=EMPRESA, centro="5.001.001")
    medicoes.mudar_estado(c, uid, a_mao, "recebida", "o orgao pagou o consorcio; conferido no extrato", "2026-10-20",
                          origem="manual")
    quase = medir(c, k, 6, "2026-08", "recebida", 600_003, aprovado=600_003, protocolo="2026-09-06")
    nota(c, 300_002, [quase], coligada=EMPRESA, centro="5.001.001", titulos=[(279_002, 278_902, 1)])   # faltam R$ 1,00: paga
    f = fechamento.fechamento(c)
    assert _abertas(f) == [(n1, 1_000_001, False), (n2, 300_001, False), (n3, 200_001, False), (n4, 100_001, False),
                           (n5, 500_001, False)]
    assert {e["tipo_aberto"] for e in f["em_aberto"]} == {"repasse"}
    for mid, face in ((sem_titulo, 1_000_001), (do_pdf, 300_001), (glosa, 200_001), (teto, 100_001), (a_mao, 500_001)):
        md = _medicao(f, mid)
        assert _estado(c, mid) == "recebida" and _numeros(md)[2:] == (face, 0, face)
    assert _numeros(_medicao(f, quase))[2:] == (300_002, 300_002, 0)
    _confere_soma(f)


def test_medicao_recebida_sem_a_nota_da_empresa_ao_consorcio_continua_inteira_no_recebido(exemplo):
    """O que NAO mudou: em obra propria, e em consorcio so' com a fatura do consorcio, a medicao recebida leva as notas
    dela inteiras ao recebido, mesmo com titulo em aberto ou pago em parte no RM (docs/adr/0006); protocolada, cada
    nota segue os titulos dela, como antes."""
    c, k = exemplo
    p = c.execute("SELECT id FROM contratos WHERE nome_curto='Obra Própria'").fetchone()[0]
    uid = c.execute("SELECT id FROM usuarios").fetchone()[0]
    aberta = medir(c, p, 1, "2026-09", "recebida", 500_001, aprovado=500_001, protocolo="2026-10-01")
    nota(c, 500_001, [aberta], coligada=EMPRESA, titulos=[(465_001, 0, 0)])                    # titulo em aberto
    parte = medir(c, p, 2, "2026-09", "recebida", 300_001, aprovado=300_001, protocolo="2026-10-02")
    nota(c, 300_001, [parte], coligada=EMPRESA, titulos=[(279_001, 100_000, 4)])               # pago em parte
    a_mao = medir(c, p, 3, "2026-09", "protocolada", 200_001, aprovado=200_001, protocolo="2026-10-03")
    nota(c, 200_001, [a_mao], coligada=EMPRESA)
    medicoes.mudar_estado(c, uid, a_mao, "recebida", "a baixa nao entrou no RM; conferida no extrato", "2026-10-20",
                          origem="manual")
    cobrando = medir(c, p, 4, "2026-09", "protocolada", 100_001, aprovado=100_001, protocolo="2026-10-04")
    n4 = nota(c, 100_001, [cobrando], coligada=EMPRESA, titulos=[(93_001, 50_000, 4)])         # faltam 43.001
    # consorcio so' com a fatura do consorcio (e a NFS-e de outra consorciada, que nao conta): pelo estado, vezes a cota
    cons = medir(c, k, 1, "2026-09", "recebida", 2_000_001, aprovado=2_000_001, protocolo="2026-10-05")
    nota(c, 2_000_001, [cons], coligada=CONSORCIO, titulos=[(1_860_001, 0, 0)])
    nota(c, 1_000_000, [cons], coligada=OUTRA)
    f = fechamento.fechamento(c)
    assert _numeros(_medicao(f, aberta)) == (500_001, 500_001, 500_001, 500_001, 0)
    assert _numeros(_medicao(f, parte)) == (300_001, 300_001, 300_001, 300_001, 0)
    assert _numeros(_medicao(f, a_mao)) == (200_001, 200_001, 200_001, 200_001, 0)
    assert _numeros(_medicao(f, cobrando)) == (100_001, 100_001, 100_001, 57_000, 43_001)
    assert _numeros(_medicao(f, cons)) == (1_000_001, 1_000_001, 1_000_001, 1_000_001, 0)
    assert all(n["recebida"] for mid in (aberta, parte, a_mao, cons) for n in _medicao(f, mid)["notas"])
    assert _abertas(f) == [(n4, 43_001, True)]
    assert f["notas_diferem"] == []
    _confere_soma(f)


def test_consorcio_avisa_quando_as_notas_da_empresa_ligadas_nao_somam_a_cota_da_medicao(exemplo):
    """A cobertura do vinculo so' diz se ha' nota ligada. Em consorcio, as notas da empresa ligadas a' medicao deveriam
    somar a cota dela: quando a diferenca passa de R$ 1,00 (`diretoria.TOLERANCIA_CENTAVOS`), a medicao sai em
    `notas_diferem`, com a soma das notas, a cota e a diferenca. So' avisa: os numeros da pagina nao mudam."""
    import json
    c, k = exemplo
    p = c.execute("SELECT id FROM contratos WHERE nome_curto='Obra Própria'").fetchone()[0]
    falta = medir(c, k, 1, "2026-03", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-04-01")
    nota(c, 700_001, [falta], coligada=EMPRESA, centro="5.001.001")             # a cota e' 1.000.001: faltam 300.000
    duas = medir(c, k, 2, "2026-03", "protocolada", 1_200_003, aprovado=1_200_003, protocolo="2026-04-02")
    nota(c, 400_001, [duas], coligada=EMPRESA, centro="5.001.001")              # duas notas que somam a cota (600.002)
    nota(c, 200_001, [duas], coligada=EMPRESA, centro="5.001.001")
    limite = medir(c, k, 3, "2026-03", "protocolada", 600_001, aprovado=600_001, protocolo="2026-04-03")
    nota(c, 300_101, [limite], coligada=EMPRESA, centro="5.001.001")            # R$ 1,00 a mais que a cota: nao avisa
    acima = medir(c, k, 4, "2026-04", "nota_emitida", 600_001)                  # sem boletim gravado: a cota do pedido
    nota(c, 300_102, [acima], coligada=EMPRESA, centro="5.001.001")             # R$ 1,01 a mais: avisa, ja' na nota emitida
    so_fatura = medir(c, k, 5, "2026-04", "protocolada", 800_001, aprovado=800_001, protocolo="2026-05-01")
    nota(c, 700_001, [so_fatura], coligada=CONSORCIO)                           # sem a nota da empresa: fora do aviso
    propria = medir(c, p, 1, "2026-04", "protocolada", 500_001, aprovado=500_001, protocolo="2026-05-02")
    nota(c, 400_000, [propria], coligada=EMPRESA)                               # obra propria: fora do aviso
    antes = medir(c, k, 6, "2026-05", "espelho_gerado", 400_001, aprovado=400_001)
    nota(c, 1, [antes], coligada=EMPRESA, centro="5.001.001")                   # antes da nota emitida: fora
    velha = medir(c, k, 7, "2024-12", "protocolada", 400_001, aprovado=400_001, protocolo="2025-01-10")
    nota(c, 1, [velha], coligada=EMPRESA, centro="5.001.001")                   # competencia fora dos anos da pagina
    f = fechamento.fechamento(c)
    obra = {"contrato_id": k, "obra": "Obra Consórcio", "tipo": "execucao"}
    esperado = [
        {**obra, "medicao_id": falta, "medicao_numero": 1, "competencia": "2026-03", "notas_centavos": 700_001,
         "cota_centavos": 1_000_001, "diferenca_centavos": -300_000},
        {**obra, "medicao_id": acima, "medicao_numero": 4, "competencia": "2026-04", "notas_centavos": 300_102,
         "cota_centavos": 300_001, "diferenca_centavos": 101}]
    assert f["notas_diferem"] == esperado
    # a cobertura continua dizendo 100%: as duas medicoes tem nota ligada; e a conta e' pela face da nota, como antes
    assert f["cobertura"]["2026"]["medicoes_sem_nota"] == 0 and f["cobertura"]["2026"]["percentual"] == 100.0
    assert _numeros(_medicao(f, falta)) == (1_000_001, 1_000_001, 700_001, 0, 700_001)
    _confere_soma(f)
    # com o total a receber nao liberado o aviso continua: so' compara nota com medicao, nada do recebido
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'", (json.dumps({"total_a_receber_liberado": False}),))
    c.commit()
    assert fechamento.fechamento(c)["notas_diferem"] == esperado


def test_consorcio_aviso_da_nota_diferente_compara_com_o_liquido_do_par_que_absorveu_reajuste_negativo(exemplo):
    """Issue #589: a execucao que absorveu um reajuste negativo e' faturada pelo liquido do par
    (`medicoes.valor_do_par`). A nota da empresa pela cota do liquido nao e' divergencia; pela cota do valor da
    execucao sozinha, e'."""
    c, k = exemplo
    uid = c.execute("SELECT id FROM usuarios").fetchone()[0]

    def par(numero, comp, face):
        exe = medir(c, k, numero, comp, "protocolada", 2_000_001, aprovado=2_000_001, protocolo=f"{comp}-28")
        rea = medir(c, k, numero, comp, "protocolada", -200_002, aprovado=-200_002, tipo="reajuste", protocolo=f"{comp}-28")
        eid = c.execute("INSERT INTO espelhos (contrato_id, numero, competencia, versao, situacao, entradas, saidas, "
                        "regra_sha256, criado_por) VALUES (?,?,?,1,'vigente','{}','[]','x',?)", (k, numero, comp, uid)).lastrowid
        c.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id, valor_com_sinal_centavos) VALUES (?,?,?)",
                  (eid, exe, 2_000_001))
        c.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id, valor_com_sinal_centavos) VALUES (?,?,?)",
                  (eid, rea, -200_002))
        c.commit()
        nota(c, face, [exe], coligada=EMPRESA, centro="5.001.001")
        return exe

    par(1, "2026-03", 900_000)                    # liquido 1.799.999 x 50% = 899.999,5 -> 900.000: fecha
    cheia = par(2, "2026-04", 1_000_001)          # a cota da execucao sozinha: 100.001 acima da cota do liquido
    f = fechamento.fechamento(c)
    assert [(e["medicao_id"], e["notas_centavos"], e["cota_centavos"], e["diferenca_centavos"]) for e in f["notas_diferem"]] == [
        (cheia, 1_000_001, 900_000, 100_001)]
    _confere_soma(f)


# ------------------------------------------------- em aberto: o repasse sem baixa em grupo proprio (parecer da PR #761)

def test_em_aberto_separa_o_repasse_sem_baixa_da_nota_que_o_orgao_ainda_nao_pagou(exemplo):
    """A nota da empresa ao consorcio em aberto numa medicao que o orgao JA' pagou (recebida) nao e' "nota protocolada
    nao paga": quem deve e' o consorcio. Sai como `tipo_aberto` "repasse", com subtotal proprio
    (`em_aberto_repasse_centavos`); a mesma nota em medicao so' protocolada continua em (a). As tres partes somam o
    total do ano, e protocolado - recebido = (a) + (a')."""
    import json
    c, k = exemplo
    p = c.execute("SELECT id FROM contratos WHERE nome_curto='Obra Própria'").fetchone()[0]
    orgao = medir(c, p, 1, "2026-09", "protocolada", 300_001, aprovado=300_001, protocolo="2026-10-01")
    n1 = nota(c, 300_001, [orgao], coligada=EMPRESA)                                             # (a) obra propria
    cobrando = medir(c, k, 1, "2026-09", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-10-02")
    n2 = nota(c, 1_000_001, [cobrando], coligada=EMPRESA, centro="5.001.001")                    # (a) o orgao nao pagou
    repasse = medir(c, k, 2, "2026-09", "recebida", 1_200_003, aprovado=1_200_003, protocolo="2026-10-03")
    n3 = nota(c, 600_002, [repasse], coligada=EMPRESA, centro="5.001.001", titulos=[(558_001, 0, 0)])        # (a')
    em_parte = medir(c, k, 3, "2026-09", "recebida", 800_001, aprovado=800_001, protocolo="2026-10-04")
    n4 = nota(c, 400_001, [em_parte], coligada=EMPRESA, centro="5.001.001", titulos=[(372_001, 100_000, 4)])  # (a'): faltam 272.001
    medir(c, k, 4, "2026-09", "protocolada", 600_001, aprovado=600_001, protocolo="2026-10-05")              # (b): 300.001
    so_fatura = medir(c, k, 5, "2026-09", "recebida", 400_001, aprovado=400_001, protocolo="2026-10-06")
    nota(c, 400_001, [so_fatura], coligada=CONSORCIO)                    # so' a fatura do consorcio: recebida, nada em aberto
    velha = medir(c, k, 6, "2025-11", "recebida", 200_001, aprovado=200_001, protocolo="2025-12-10")
    n7 = nota(c, 100_001, [velha], coligada=EMPRESA, centro="5.001.001")                         # (a') de 2025
    antiga = medir(c, k, 7, "2024-11", "recebida", 200_001, aprovado=200_001, protocolo="2024-12-10")
    nota(c, 100_001, [antiga], coligada=EMPRESA, centro="5.001.001")                             # antes de 2025: a' parte
    f = fechamento.fechamento(c)
    assert [(e["tipo_aberto"], e["numero"], e["valor_centavos"], e["paga_em_parte"]) for e in f["em_aberto"]] == [
        ("repasse", n7, 100_001, False), ("nota", n1, 300_001, False), ("nota", n2, 1_000_001, False),
        ("repasse", n3, 600_002, False), ("repasse", n4, 272_001, True), ("sem_nota", None, 300_001, False)]
    partes = lambda t: tuple(t[k_] for k_ in ("em_aberto_centavos",) + fechamento.PARTES_DO_ABERTO)   # noqa: E731
    assert partes(f["por_ano"]["2026"]) == (2_472_006, 1_300_002, 872_003, 300_001)
    assert partes(f["por_ano"]["2025"]) == (100_001, 0, 100_001, 0)
    t = f["por_ano"]["2026"]
    assert t["protocolado_centavos"] - t["recebido_centavos"] == 1_300_002 + 872_003
    # a medicao e a nota levam a mesma marca; a nota que o orgao nao pagou e a recebida so' com a fatura, nao
    assert partes(_medicao(f, repasse)) == (600_002, 0, 600_002, 0) and partes(_medicao(f, cobrando)) == (1_000_001, 1_000_001, 0, 0)
    assert [n["aguarda_repasse"] for mid in (orgao, cobrando, repasse, em_parte, so_fatura) for n in _medicao(f, mid)["notas"]] == [
        False, False, True, True, False]
    assert f["em_aberto_anteriores"] == {"quantidade": 1, "valor_centavos": 100_001}
    _confere_soma(f)
    # com o total a receber nao liberado, o grupo novo some junto com o resto do em aberto
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'", (json.dumps({"total_a_receber_liberado": False}),))
    c.commit()
    f = fechamento.fechamento(c)
    assert f["em_aberto"] == [] and all(f["por_ano"][a][k_] is None for a in f["anos"] for k_ in fechamento.ESCONDIDOS)
    assert all(n["aguarda_repasse"] is None for mid in (repasse, em_parte) for n in _medicao(f, mid)["notas"])
    assert all(str(v) not in json.dumps(f) for v in (872_003, 272_001, 1_300_002, 2_472_006))


def test_consorcio_medicao_recebida_com_duas_notas_da_empresa_uma_baixada_e_outra_aberta(exemplo):
    """A medicao recebida faturada em duas notas da empresa: cada nota segue os proprios titulos. A baixada entra no
    recebido; a aberta fica como repasse sem baixa, pela face dela."""
    c, k = exemplo
    mid = medir(c, k, 1, "2026-09", "recebida", 2_000_001, aprovado=2_000_001, protocolo="2026-10-01")
    nota(c, 2_000_001, [mid], coligada=CONSORCIO, titulos=PAGO(1_860_001))
    paga = nota(c, 700_000, [mid], coligada=EMPRESA, centro="5.001.001", titulos=PAGO(651_000))
    aberta = nota(c, 300_001, [mid], coligada=EMPRESA, centro="5.001.001", titulos=[(279_001, 0, 0)])
    f = fechamento.fechamento(c)
    md = _medicao(f, mid)
    assert _numeros(md) == (1_000_001, 1_000_001, 1_000_001, 700_000, 300_001)
    assert [(n["numero"], n["recebido_centavos"], n["em_aberto_centavos"], n["recebida"], n["aguarda_repasse"])
            for n in md["notas"]] == [(paga, 700_000, 0, True, False), (aberta, 0, 300_001, False, True)]
    assert [(e["tipo_aberto"], e["numero"], e["valor_centavos"]) for e in f["em_aberto"]] == [("repasse", aberta, 300_001)]
    assert f["notas_diferem"] == []                                     # as duas somam a cota
    _confere_soma(f)


def test_consorcio_medicao_recebida_cuja_nota_da_empresa_nao_conta_volta_a_fatura_do_consorcio(exemplo):
    """A nota da empresa cancelada, desconsiderada, de tipo fora da cobranca ou com o vinculo desfeito nao conta: a
    medicao recebida volta a' regra da fatura do consorcio (vezes a cota, inteira no recebido), sem nota fora da conta."""
    c, k = exemplo

    def caso(numero, **kw):
        mid = medir(c, k, numero, "2026-09", "recebida", 2_000_001, aprovado=2_000_001, protocolo="2026-10-01")
        nota(c, 2_000_001, [mid], coligada=CONSORCIO, titulos=[(1_860_001, 0, 0)])        # titulo aberto: vale o estado
        return mid, nota(c, 1_000_001, [mid], coligada=EMPRESA, centro="5.001.001", **kw)

    cancelada, _ = caso(1, situacao="cancelada")
    desconsiderada, nd = caso(2)
    c.execute("UPDATE notas_fiscais SET desconsiderada_em='2026-11-01' WHERE numero=?", (f"{int(nd):09d}",))
    outro_tipo, _ = caso(3, codtmv="2.2.15")
    desfeito, nv = caso(4)
    c.execute("UPDATE nf_alocacoes SET desfeita_em='2026-11-01', motivo_desfazer='t' WHERE medicao_id=? AND nota_id="
              "(SELECT id FROM notas_fiscais WHERE numero=?)", (desfeito, f"{int(nv):09d}"))
    vale, _ = caso(5)                                                    # o controle: a nota da empresa valendo
    c.commit()
    f = fechamento.fechamento(c)
    for mid in (cancelada, desconsiderada, outro_tipo, desfeito):
        md = _medicao(f, mid)
        assert _numeros(md) == (1_000_001, 1_000_001, 1_000_001, 1_000_001, 0)      # 2.000.001 x 50% -> 1.000.001
        assert md["notas_fora_da_conta"] == [] and [n["aguarda_repasse"] for n in md["notas"]] == [False]
    assert _numeros(_medicao(f, vale)) == (1_000_001, 1_000_001, 1_000_001, 0, 1_000_001)
    assert [e["medicao_id"] for e in f["em_aberto"]] == [vale]
    _confere_soma(f)


def test_entidade_que_nao_e_consorcio_com_outra_coligada_nao_entra_na_regra_da_nota_da_empresa(exemplo):
    """A regra da nota da empresa so' vale em contrato de CONSORCIO. Contrato de entidade que nao e' consorcio e tem
    outra coligada no RM segue a regra de sempre: contam as notas da coligada do contrato, pelo percentual; a nota da
    empresa ligada a' mesma medicao nao conta nem preterir nada, e a medicao recebida leva a nota inteira ao recebido."""
    c, k = exemplo
    c.execute("UPDATE entidades SET papel='consorciada' WHERE coligada_rm=?", (CONSORCIO,))
    c.commit()
    mid = medir(c, k, 1, "2026-09", "recebida", 2_000_001, aprovado=2_000_001, protocolo="2026-10-01")
    da_entidade = nota(c, 2_000_001, [mid], coligada=CONSORCIO, titulos=[(1_860_001, 0, 0)])
    nota(c, 700_001, [mid], coligada=EMPRESA, centro="5.001.001")
    f = fechamento.fechamento(c)
    md = _medicao(f, mid)
    assert _numeros(md) == (1_000_001, 1_000_001, 1_000_001, 1_000_001, 0)
    assert [(n["numero"], n["valor_centavos"], n["recebida"]) for n in md["notas"]] == [(da_entidade, 1_000_001, True)]
    assert md["notas_fora_da_conta"] == [] and f["notas_diferem"] == [] and f["pares_mistos"] == [] and f["em_aberto"] == []
    _confere_soma(f)


def test_consorcio_avisa_o_par_misto_execucao_e_reajuste_contando_por_notas_diferentes(exemplo):
    """A fatura unica do consorcio cobre a execucao e o reajuste. Com ela ligada so' a uma das duas e a nota da empresa
    ligada so' a' outra, a mesma cobranca entra duas vezes no mes, e `notas_diferem` nao pega (a nota da empresa fecha
    com a cota da medicao dela). `pares_mistos` diz qual medicao ainda conta pela fatura do consorcio; ligada a nota
    da empresa tambem a ela, o aviso some."""
    import json
    c, k = exemplo
    p = c.execute("SELECT id FROM contratos WHERE nome_curto='Obra Própria'").fetchone()[0]

    def par(numero, comp, exe=None, rea=None, estado_rea="protocolada"):
        """`exe` e `rea`: "empresa", "consorcio" ou nada (sem nota)."""
        ids = []
        for tipo, quem, pedido, estado in (("execucao", exe, 2_000_001, "protocolada"), ("reajuste", rea, 200_001, estado_rea)):
            mid = medir(c, k, numero, comp, estado, pedido, aprovado=pedido, tipo=tipo, protocolo=f"{comp}-28")
            if quem == "empresa":
                nota(c, 1_000_001 if tipo == "execucao" else 100_001, [mid], coligada=EMPRESA, centro="5.001.001")
            elif quem == "consorcio":
                nota(c, 2_200_002, [mid], coligada=CONSORCIO)
            ids.append(mid)
        return ids

    e1, r1 = par(1, "2026-03", exe="consorcio", rea="empresa")           # misto: falta a nota da empresa na execucao
    e2, r2 = par(2, "2026-04", exe="empresa", rea="consorcio")           # misto ao contrario: falta no reajuste
    par(3, "2026-05", exe="empresa", rea="empresa")                      # as duas pela nota da empresa
    par(4, "2026-06", exe="consorcio", rea="consorcio")                  # as duas pela fatura do consorcio
    par(5, "2026-07", exe="empresa")                                     # reajuste sem nota: nao e' par misto
    par(6, "2026-08", exe="consorcio", rea="empresa", estado_rea="espelho_gerado")   # reajuste antes da nota emitida
    par(7, "2024-12", exe="consorcio", rea="empresa")                    # competencia fora dos anos da pagina
    proj = medir(c, k, 8, "2026-09", "protocolada", 400_001, aprovado=400_001, tipo="projeto", protocolo="2026-09-28")
    nota(c, 400_001, [proj], coligada=CONSORCIO)                         # projeto de mesmo numero nao e' o par
    exe8 = medir(c, k, 8, "2026-09", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-09-28")
    nota(c, 1_000_001, [exe8], coligada=EMPRESA, centro="5.001.001")
    a = medir(c, p, 9, "2026-09", "protocolada", 500_001, aprovado=500_001, protocolo="2026-09-28")
    nota(c, 500_001, [a], coligada=EMPRESA)                              # obra propria: fora
    f = fechamento.fechamento(c)
    obra = {"contrato_id": k, "obra": "Obra Consórcio"}
    esperado = [
        {**obra, "medicao_id": e1, "medicao_numero": 1, "tipo": "execucao", "competencia": "2026-03",
         "par_medicao_id": r1, "par_tipo": "reajuste"},
        {**obra, "medicao_id": r2, "medicao_numero": 2, "tipo": "reajuste", "competencia": "2026-04",
         "par_medicao_id": e2, "par_tipo": "execucao"}]
    assert f["pares_mistos"] == esperado
    # o que o aviso protege: o mes soma a fatura (que cobre as duas) vezes a cota E a nota da empresa do reajuste
    m = _mes(f, "2026-03")
    assert (m["aprovado_centavos"], m["protocolado_centavos"]) == (1_100_002, 1_100_001 + 100_001)
    assert f["notas_diferem"] == []                                      # o outro aviso nao pega este caso
    _confere_soma(f)
    # com o total a receber nao liberado o aviso continua
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'", (json.dumps({"total_a_receber_liberado": False}),))
    c.commit()
    assert fechamento.fechamento(c)["pares_mistos"] == esperado
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'", (json.dumps({"total_a_receber_liberado": True}),))
    # ligada a nota da empresa tambem a' execucao, o par deixa de ser misto e o mes volta a fechar com o aprovado
    nota(c, 1_000_001, [e1], coligada=EMPRESA, centro="5.001.001")
    f = fechamento.fechamento(c)
    assert f["pares_mistos"] == esperado[1:]
    m = _mes(f, "2026-03")
    assert (m["aprovado_centavos"], m["protocolado_centavos"]) == (1_100_002, 1_000_001 + 100_001)
    _confere_soma(f)


# ---- A medicao com nota emitida da obra sem o passo "Envio da nota" (#743) e a regra do consorcio (#756) nos outros
# ---- lugares: o a receber do Inicio e da lista de Obras, a pagina da obra e o passo Pagamento da pagina da medicao

HOJE_TESTE = datetime.date(2026, 11, 17)
SEM_ENVIO_DA_NOTA = '["planilha", "analise", "espelhos", "notas", "pagamento"]'


def _emitir(c, mid, dia):
    c.execute("UPDATE medicoes SET nota_emitida_em=? WHERE id=?", (dia, mid))
    c.commit()


def _propria(c):
    return c.execute("SELECT id FROM contratos WHERE nome_curto='Obra Própria'").fetchone()[0]


def _a_receber_das_telas(c, cid):
    """(Inicio: total, ha' mais de 60 dias; lista de Obras, na cota; pagina da obra, cheio)."""
    ini = inicio._a_receber(c, HOJE_TESTE)
    return (ini["valor_centavos"], ini["mais_60_centavos"], (diretoria.a_receber_por_obra(c, na_cota=True) or {}).get(cid, 0),
            diretoria.da_obra(c, cid)["a_receber_centavos"])


def test_nota_emitida_da_obra_sem_o_passo_envio_da_nota_conta_como_a_protocolada(exemplo):
    """Issue #743: na obra cujo cadastro nao tem o passo "Envio da nota", a nota emitida ja' e' a cobranca. A medicao
    em `nota_emitida` entra no protocolado e no em aberto do Fechamento (com nota ligada, pela nota; sem ela, pelo
    valor da medicao), no a receber do Inicio, da lista de Obras e da pagina da obra, com a espera contada da emissao
    da nota. Na obra COM o passo (a Obra Consorcio, pela familia do orgao), a nota emitida espera o protocolo e nao
    entra em nenhum deles."""
    c, k = exemplo
    p = _propria(c)
    com_passo = medir(c, k, 1, "2026-08", "nota_emitida", 400_001, aprovado=400_001)
    _emitir(c, com_passo, "2026-09-01")
    nota(c, 400_001, [com_passo], coligada=CONSORCIO, emissao="2026-09-01")
    a = medir(c, p, 1, "2026-08", "nota_emitida", 500_001, aprovado=500_001)
    _emitir(c, a, "2026-09-01")
    n1 = nota(c, 500_001, [a], coligada=EMPRESA, emissao="2026-09-01")
    b = medir(c, p, 2, "2026-09", "nota_emitida", 300_001, aprovado=300_001)
    _emitir(c, b, "2026-11-01")

    # com o passo "Envio da nota" (o cadastro de exemplo): nenhuma das tres esta' cobrada
    f = fechamento.fechamento(c)
    assert [_numeros(_medicao(f, m))[2:] for m in (com_passo, a, b)] == [(0, 0, 0)] * 3 and f["em_aberto"] == []
    assert _a_receber_das_telas(c, p) == (0, 0, 0, 0)
    ciclo = {e["etapa"]: (e["valor_centavos"], e["quantidade"]) for e in inicio._ciclo(c, HOJE_TESTE)}
    assert ciclo["nota"] == (200_001 + 500_001 + 300_001, 3) and ciclo["protocolado"] == (0, 0)

    c.execute("UPDATE contratos SET passos_medicao=? WHERE id=?", (SEM_ENVIO_DA_NOTA, p)); c.commit()
    f = fechamento.fechamento(c)
    # (medido, aprovado, protocolado, recebido, em aberto)
    assert _numeros(_medicao(f, a)) == (500_001, 500_001, 500_001, 0, 500_001)
    assert _numeros(_medicao(f, b)) == (300_001, 300_001, 0, 0, 300_001) and _medicao(f, b)["sem_nota"] is True
    assert _numeros(_medicao(f, com_passo))[2:] == (0, 0, 0)                  # na obra com o passo, nada muda
    assert [(e["tipo_aberto"], e["numero"], e["valor_centavos"], e["protocolo_em"], e["emitida_em"]) for e in f["em_aberto"]] == [
        ("nota", n1, 500_001, None, "2026-09-01"), ("sem_nota", None, 300_001, None, "2026-11-01")]
    assert f["notas_sem_medicao"]["em_aberto"] == []                         # a nota dela nao vira "sem medicao ligada"
    _confere_soma(f)
    # Inicio, lista de Obras e pagina da obra: a soma das duas; a de 01/09 espera ha' mais de 60 dias
    assert _a_receber_das_telas(c, p) == (800_002, 500_001, 800_002, 800_002)
    assert _a_receber_das_telas(c, k)[2:] == (0, 0)
    # a nota ligada a ela nao entra de novo como cobranca do RM, e a medicao sai da etapa que espera o protocolo
    assert diretoria._notas_em_aberto(c) == []
    ciclo = {e["etapa"]: (e["valor_centavos"], e["quantidade"], e["mais_antigo_dias"]) for e in inicio._ciclo(c, HOJE_TESTE)}
    assert ciclo["nota"] == (200_001, 1, 77) and ciclo["protocolado"] == (800_002, 2, 77)
    prev = inicio._previsao(c, HOJE_TESTE)
    assert prev["sem_previsao"] == {"valor_centavos": 800_002, "quantidade": 2}        # sem protocolo nao ha' data esperada
    assert sum(g["valor_centavos"] for g in prev.values()) == ciclo["protocolado"][0]

    # paga a nota no RM (a medicao segue com nota emitida ate' a sincronizacao): sai do em aberto do Fechamento
    c.execute("UPDATE baixas SET valor_baixado_centavos=valor_original_centavos, status_lan=1, data_baixa='2026-11-10'"); c.commit()
    f = fechamento.fechamento(c)
    assert _numeros(_medicao(f, a)) == (500_001, 500_001, 500_001, 500_001, 0)
    _confere_soma(f)
    # recebida sem protocolo (a baixa do RM ou o administrador): sai do a receber
    c.execute("UPDATE medicoes SET estado='recebida', recebida_em='2026-11-10' WHERE id IN (?, ?)", (a, b)); c.commit()
    assert _a_receber_das_telas(c, p) == (0, 0, 0, 0)


def test_sem_o_total_liberado_a_nota_emitida_sem_protocolo_nao_aparece_em_a_receber_nenhum(exemplo):
    c, _ = exemplo
    p = _propria(c)
    c.execute("UPDATE contratos SET passos_medicao=? WHERE id=?", (SEM_ENVIO_DA_NOTA, p))
    a = medir(c, p, 1, "2026-08", "nota_emitida", 500_001, aprovado=500_001)
    _emitir(c, a, "2026-09-01")
    nota(c, 500_001, [a], coligada=EMPRESA, emissao="2026-09-01")
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'", (json.dumps({"total_a_receber_liberado": False}),))
    c.commit()
    assert inicio._a_receber(c, HOJE_TESTE) == {"liberado": False, "valor_centavos": None, "mais_60_centavos": None,
                                                "a_parte": None}
    assert diretoria.a_receber_por_obra(c, na_cota=True) is None and diretoria.da_obra(c, p)["a_receber_centavos"] is None
    f = fechamento.fechamento(c)
    assert f["em_aberto"] == [] and _medicao(f, a)["em_aberto_centavos"] is None
    assert _medicao(f, a)["protocolado_centavos"] == 500_001 and "emitida_em" not in json.dumps(f)


def test_a_receber_do_inicio_e_de_obras_segue_a_nota_da_empresa_em_consorcio(exemplo):
    """Issue #756 no Inicio e na lista de Obras, pela escolha do Fechamento (`_notas_da_conta`): com a nota da propria
    empresa ligada, a medicao que espera o pagamento entra pelo em aberto dela (a face, nao a cota da medicao); a
    medicao que o orgao ja' pagou entra pelo repasse sem baixa; e a fatura do consorcio da mesma medicao nao entra
    de novo como cobranca do RM. Sem a nota da empresa, vale a fatura do consorcio vezes a cota, como antes."""
    c, k = exemplo
    # espera o pagamento: nota da empresa de face 999.999 (a cota da medicao seria 1.000.001) e a fatura do consorcio
    cobrando = medir(c, k, 1, "2026-09", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-10-02")
    nota(c, 999_999, [cobrando], coligada=EMPRESA, centro="5.001.001")
    nota(c, 2_400_003, [cobrando], coligada=CONSORCIO)
    # o orgao ja' pagou; nota da empresa sem baixa (repasse), com a fatura do consorcio ainda aberta no RM
    repasse = medir(c, k, 2, "2026-08", "recebida", 1_200_003, aprovado=1_200_003, protocolo="2026-09-03")
    nota(c, 600_002, [repasse], coligada=EMPRESA, centro="5.001.001", titulos=[(558_001, 0, 0)])
    nota(c, 1_200_003, [repasse], coligada=CONSORCIO)
    # o orgao ja' pagou; nota da empresa baixada em parte: faltam 272.001 (sem aplicar a cota)
    em_parte = medir(c, k, 3, "2026-08", "recebida", 800_001, aprovado=800_001, protocolo="2026-10-04")
    nota(c, 400_001, [em_parte], coligada=EMPRESA, centro="5.001.001", titulos=[(372_001, 100_000, 4)])
    # o orgao ja' pagou e o repasse foi baixado: nada a receber
    baixada = medir(c, k, 4, "2026-08", "recebida", 600_001, aprovado=600_001, protocolo="2026-10-05")
    nota(c, 300_001, [baixada], coligada=EMPRESA, centro="5.001.001", titulos=PAGO(279_001))
    # sem a nota da empresa: a fatura do consorcio com titulo aberto em medicao ja' fechada, vezes a cota
    so_fatura = medir(c, k, 5, "2026-08", "recebida", 1_000_001, aprovado=1_000_001, protocolo="2026-10-06")
    nota(c, 1_000_001, [so_fatura], coligada=CONSORCIO, titulos=[(930_001, 0, 0)])         # 930.001 x 50% -> 465.001
    # sem nota nenhuma: a protocolada pelo valor da medicao na cota (600.001 x 50% -> 300.001)
    medir(c, k, 6, "2026-09", "protocolada", 600_001, aprovado=600_001, protocolo="2026-10-07")

    total = 999_999 + 600_002 + 272_001 + 465_001 + 300_001
    # (Inicio, mais de 60 dias, lista de Obras na cota, pagina da obra em valor cheio)
    # ha' mais de 60 dias: o repasse da medicao protocolada em 03/09 e a fatura do consorcio emitida em 10/03
    # a pagina da obra mostra o que o ORGAO deve ao contrato, em valor cheio: as duas protocoladas e as faturas do
    # consorcio com titulo aberto (a da medicao 2 e a da 5); a nota da empresa e o repasse nao entram ali
    assert _a_receber_das_telas(c, k) == (total, 600_002 + 465_001, total, 2_000_001 + 600_001 + 1_200_003 + 930_001)
    linhas = diretoria.a_receber_na_cota(c)
    assert sorted(diretoria._a_receber_cota(x) for x in linhas) == sorted([999_999, 600_002, 272_001, 465_001, 300_001])
    assert sum(1 for x in linhas if x.get("repasse")) == 2
    # as mesmas partes do Fechamento: (a) nota nao paga, (a') repasse sem baixa e (b) sem nota ligada
    f = fechamento.fechamento(c)
    t = f["por_ano"]["2026"]
    assert (t["em_aberto_notas_centavos"], t["em_aberto_repasse_centavos"], t["sem_nota_centavos"]) == (999_999, 872_003, 300_001)
    _confere_soma(f)
    # o estado das medicoes nao muda com a conta
    assert [_estado(c, m) for m in (cobrando, repasse, em_parte, baixada, so_fatura)] == ["protocolada"] + ["recebida"] * 4

    # desfeito o vinculo da nota da empresa, a medicao volta a' regra da fatura do consorcio (a saida do docs/adr/0006)
    c.execute("UPDATE nf_alocacoes SET desfeita_em='2026-11-17' WHERE medicao_id=? AND nota_id IN "
              "(SELECT id FROM notas_fiscais WHERE coligada=?)", (repasse, EMPRESA)); c.commit()
    # sai o repasse (600.002) e a fatura do consorcio da medicao volta a contar pelo titulo aberto (1.200.003 x 50% -> 600.002)
    assert _a_receber_das_telas(c, k)[2] == total - 600_002 + 600_002
    assert sum(1 for x in diretoria.a_receber_na_cota(c) if x.get("repasse")) == 1


def _baixada_em(c, numero, dia):
    c.execute("UPDATE baixas SET data_baixa=? WHERE nota_id=(SELECT id FROM notas_fiscais WHERE numero=?) "
              "AND valor_baixado_centavos>0", (dia, f"{int(numero):09d}")); c.commit()


def test_recebido_do_inicio_segue_a_nota_da_empresa_em_consorcio(exemplo):
    """Issue #756 no recebido do Inicio (o do mes e o dos 12 meses), pela escolha do Fechamento (`_notas_da_conta`):
    com a nota da propria empresa ligada a' medicao, o recebido e' a baixa do titulo DELA, pela face e no mes da baixa
    dela (o repasse do consorcio), e a baixa da fatura do consorcio da mesma medicao nao entra. Sem a nota da empresa,
    vale a baixa da fatura do consorcio vezes a cota, como antes. Centavo impar na cota."""
    import datetime
    from app import inicio
    c, k = exemplo
    # o orgao pagou o consorcio em junho; o consorcio repassou em agosto (baixa da nota da empresa)
    repassada = medir(c, k, 1, "2026-05", "recebida", 2_000_001, aprovado=2_000_001, protocolo="2026-06-02")
    _baixada_em(c, nota(c, 2_000_001, [repassada], coligada=CONSORCIO, titulos=PAGO(1_860_001)), "2026-06-20")
    _baixada_em(c, nota(c, 1_000_001, [repassada], coligada=EMPRESA, centro="5.001.001", titulos=PAGO(930_001)), "2026-08-05")
    # o orgao pagou o consorcio em julho e o repasse ainda nao foi baixado: nada entrou
    sem_repasse = medir(c, k, 2, "2026-06", "recebida", 1_200_003, aprovado=1_200_003, protocolo="2026-07-03")
    _baixada_em(c, nota(c, 1_200_003, [sem_repasse], coligada=CONSORCIO, titulos=PAGO(1_116_003)), "2026-07-20")
    nota(c, 600_002, [sem_repasse], coligada=EMPRESA, centro="5.001.001", titulos=[(558_001, 0, 0)])
    # repasse baixado em parte, em setembro: entra so' o que foi baixado
    em_parte = medir(c, k, 3, "2026-07", "recebida", 800_001, aprovado=800_001, protocolo="2026-08-04")
    _baixada_em(c, nota(c, 800_001, [em_parte], coligada=CONSORCIO, titulos=PAGO(744_001)), "2026-08-20")
    _baixada_em(c, nota(c, 400_001, [em_parte], coligada=EMPRESA, centro="5.001.001", titulos=[(372_001, 100_001, 4)]), "2026-09-10")
    # sem a nota da empresa: a baixa da fatura do consorcio vezes a cota (930.001 x 50% -> 465.001), em setembro
    so_fatura = medir(c, k, 4, "2026-08", "recebida", 1_000_001, aprovado=1_000_001, protocolo="2026-09-06")
    _baixada_em(c, nota(c, 1_000_001, [so_fatura], coligada=CONSORCIO, titulos=PAGO(930_001)), "2026-09-25")
    # fatura do consorcio sem medicao ligada: continua pela cota (500.001 x 50% -> 250.001), em setembro
    _baixada_em(c, nota(c, 540_001, coligada=CONSORCIO, titulos=PAGO(500_001)), "2026-09-26")

    _, recebido = diretoria.rm_por_mes(c)
    assert recebido == {"2026-08": 930_001, "2026-09": 100_001 + 465_001 + 250_001}
    assert diretoria.recebido_rm_no_mes(c, "2026-06") == {"valor_centavos": 0, "notas": 0}
    assert diretoria.recebido_rm_no_mes(c, "2026-08") == {"valor_centavos": 930_001, "notas": 1}
    assert diretoria.recebido_rm_no_mes(c, "2026-09") == {"valor_centavos": 815_003, "notas": 3}
    p = inicio.painel(c, datetime.date(2026, 9, 30))
    assert {x["mes"]: x["valor_centavos"] for x in p["recebido_12m"] if x["valor_centavos"]} == recebido
    assert next(x for x in p["ciclo"] if x["etapa"] == "recebido_mes")["valor_centavos"] == 815_003
    # o estado das medicoes nao muda com a conta, e as duas telas escolhem as mesmas notas
    assert [_estado(c, m) for m in (repassada, sem_repasse, em_parte, so_fatura)] == ["recebida"] * 4
    f = fechamento.fechamento(c)
    assert [nt["valor_centavos"] for nt in _medicao(f, repassada)["notas"]] == [1_000_001]

    # desfeito o vinculo da nota da empresa, a medicao volta a' regra da fatura do consorcio: a baixa de julho conta
    c.execute("UPDATE nf_alocacoes SET desfeita_em='2026-11-17' WHERE medicao_id=? AND nota_id IN "
              "(SELECT id FROM notas_fiscais WHERE coligada=?)", (sem_repasse, EMPRESA)); c.commit()
    assert diretoria.rm_por_mes(c)[1]["2026-07"] == 558_002                # 1.116.003 x 50%, meio para cima


def test_recebido_do_inicio_na_obra_propria_nao_muda_com_a_regra_do_consorcio(exemplo):
    c, _ = exemplo
    p = _propria(c)
    m = medir(c, p, 1, "2026-05", "recebida", 500_001, aprovado=500_001, protocolo="2026-06-02")
    _baixada_em(c, nota(c, 500_001, [m], coligada=EMPRESA, centro="9.001.001", titulos=PAGO(465_001)), "2026-06-20")
    assert diretoria.rm_por_mes(c)[1] == {"2026-06": 465_001}
    assert diretoria.recebido_rm_no_mes(c, "2026-06") == {"valor_centavos": 465_001, "notas": 1}


def test_passo_pagamento_em_consorcio_conta_a_nota_da_empresa_ou_a_fatura_pela_cota(exemplo):
    """Issue #756 no passo Pagamento da pagina da medicao (`sincronizacao_rm.pagamento_cota`, contra os TITULOS do RM):
    em consorcio, com a nota da propria empresa ligada contam os titulos dela, pela face, e a fatura do consorcio fica
    fora (a tela a mostra sem valor, `fora_da_conta`); sem a nota da empresa, os titulos da fatura do consorcio vezes
    a cota, com o centavo impar. Obra propria nao muda."""
    c, k = exemplo
    resumo = lambda mid: {x: v for x, v in sincronizacao_rm.pagamento_cota(c, mid).items()                  # noqa: E731
                          if x in ("completo", "total_centavos", "recebido_centavos", "falta_centavos", "parcial")}
    fora = lambda mid: [(n["coligada"], n["fora_da_conta"]) for n in sincronizacao_rm.notas_da_medicao(c, mid)]   # noqa: E731
    # nota da empresa com titulo aberto, e a fatura do consorcio paga: nada recebido da cota
    aberta = medir(c, k, 1, "2026-09", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-10-02")
    nota(c, 2_400_003, [aberta], coligada=CONSORCIO, titulos=PAGO(2_232_003))
    nota(c, 999_999, [aberta], coligada=EMPRESA, centro="5.001.001", titulos=[(929_999, 0, 0)])
    assert resumo(aberta) == {"completo": True, "total_centavos": 929_999, "recebido_centavos": 0, "falta_centavos": 929_999,
                              "parcial": False}
    assert fora(aberta) == [(CONSORCIO, True), (EMPRESA, False)]
    # nota da empresa baixada em parte, em medicao que o orgao ja' pagou: vale a baixa dos titulos dela
    parte = medir(c, k, 2, "2026-09", "recebida", 800_001, aprovado=800_001, protocolo="2026-10-04")
    nota(c, 400_001, [parte], coligada=EMPRESA, centro="5.001.001", titulos=[(372_001, 100_000, 4)])
    assert resumo(parte) == {"completo": True, "total_centavos": 372_001, "recebido_centavos": 100_000, "falta_centavos": 272_001,
                             "parcial": True}
    # nota da empresa com o titulo baixado
    paga = medir(c, k, 3, "2026-09", "recebida", 600_001, aprovado=600_001, protocolo="2026-10-05")
    nota(c, 300_001, [paga], coligada=EMPRESA, centro="5.001.001", titulos=PAGO(279_001))
    assert resumo(paga) == {"completo": True, "total_centavos": 279_001, "recebido_centavos": 279_001, "falta_centavos": 0,
                            "parcial": False}
    # sem a nota da empresa: a fatura do consorcio vezes a cota. 2.232.003 x 50% = 1.116.001,5 -> 1.116.002; faltam
    # 1.232.003 x 50% = 616.001,5 -> 616.002; o recebido e' a diferenca, para a conta fechar ao centavo
    fatura = medir(c, k, 4, "2026-09", "protocolada", 2_400_003, aprovado=2_400_003, protocolo="2026-10-06")
    nota(c, 2_400_003, [fatura], coligada=CONSORCIO, titulos=[(2_232_003, 1_000_000, 4)])
    assert resumo(fatura) == {"completo": True, "total_centavos": 1_116_002, "recebido_centavos": 500_000,
                              "falta_centavos": 616_002, "parcial": True}
    assert fora(fatura) == [(CONSORCIO, False)]
    # sem a nota da empresa, medicao recebida: a fatura do consorcio vai inteira ao recebido, como no Fechamento
    fechada = medir(c, k, 5, "2026-09", "recebida", 1_000_001, aprovado=1_000_001, protocolo="2026-10-07")
    nota(c, 1_000_001, [fechada], coligada=CONSORCIO, titulos=[(930_001, 0, 0)])
    assert resumo(fechada) == {"completo": True, "total_centavos": 465_001, "recebido_centavos": 465_001, "falta_centavos": 0,
                               "parcial": False}
    # nota da empresa sem titulo no RM: o resumo nao fecha (a tela mostra "—")
    sem_titulo = medir(c, k, 6, "2026-09", "protocolada", 200_001, aprovado=200_001, protocolo="2026-10-08")
    nota(c, 100_001, [sem_titulo], coligada=EMPRESA, centro="5.001.001", titulos=[])
    assert resumo(sem_titulo)["completo"] is False and resumo(sem_titulo)["falta_centavos"] is None
    # medicao de consorcio sem nota nenhuma, e obra propria sem espelho: como antes, sem resumo
    vazia = medir(c, k, 7, "2026-09", "protocolada", 200_001, aprovado=200_001, protocolo="2026-10-09")
    assert sincronizacao_rm.pagamento_cota(c, vazia) is None
    p = _propria(c)
    da_casa = medir(c, p, 1, "2026-09", "protocolada", 500_001, aprovado=500_001, protocolo="2026-10-10")
    nota(c, 500_001, [da_casa], coligada=EMPRESA)
    assert sincronizacao_rm.pagamento_cota(c, da_casa) is None and fora(da_casa) == [(EMPRESA, False)]


# --- issue #755 (docs/adr/0006): nota e titulo excluidos no RM ficam fora de todo numero do Fechamento ------------

def _titulo(c, numero, k):
    """O id do k-esimo titulo (na ordem em que `nota` os criou) da nota de numero `numero`."""
    return c.execute("SELECT id FROM baixas WHERE idlan=?", (int(numero) * 10 + k,)).fetchone()[0]


def _marcar_titulos(c, *ids, marca="2026-09-10 12:00:00"):
    c.execute(f"UPDATE baixas SET excluida_rm_em=? WHERE id IN ({','.join('?' * len(ids))})", (marca, *ids))
    c.commit()


def _retrato_do_mes(f, comp):
    m = _mes(f, comp)
    return m["protocolado_centavos"], m["recebido_centavos"], m["em_aberto_centavos"]


def test_titulo_excluido_no_rm_nao_entra_no_devido_no_recebido_nem_na_falta(cenario):
    """O titulo que o RM deixou de devolver (`baixas.excluida_rm_em`) sai da situacao da nota nos titulos: o aberto
    antigo deixa de somar na falta, e o pago antigo deixa de ser recebimento. Obra propria e consorcio a 50% com
    centavo impar; a nota sem medicao ligada segue a mesma leitura. Tirada a marca, tudo volta."""
    c, ids = cenario
    p, k = ids["propria"], ids["consorcio"]
    # o titulo foi refeito: o vigente pago em parte (faltam 500.001) e o antigo, aberto, que dobrava a falta
    a = medir(c, p, 1, "2026-05", "protocolada", 1_000_001, aprovado=1_000_001, protocolo="2026-06-01")
    dobrada = nota(c, 1_000_001, [a], titulos=[(930_001, 430_000, 4), (930_001, 0, 0)])
    # consorcio: o titulo antigo tinha baixa; o vigente esta' aberto. A baixa do antigo nao e' recebimento
    b = medir(c, k, 2, "2026-05", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-06-02")
    estornada = nota(c, 2_000_001, [b], coligada=12, titulos=[(1_860_001, 1_860_001, 1), (1_860_001, 0, 0)])
    # o vigente foi pago inteiro; o antigo, aberto, segurava a nota como paga em parte
    d = medir(c, p, 3, "2026-05", "protocolada", 600_001, aprovado=600_001, protocolo="2026-06-03")
    quitada = nota(c, 600_001, [d], titulos=[(558_001, 558_001, 1), (558_001, 0, 0)])
    # sem medicao ligada: uma com a baixa no titulo antigo, outra quitada no vigente com o antigo aberto
    solta = nota(c, 80_001, centro="9.001.001", titulos=[(74_001, 74_001, 1), (74_001, 0, 0)])
    solta_paga = nota(c, 90_001, centro="9.001.001", titulos=[(83_001, 83_001, 1), (83_001, 0, 0)])
    protocolado = 1_000_001 + 1_000_001 + 600_001               # 2.000.001 x 50% = 1.000.000,5 -> 1.000.001

    def retrato():
        f = fechamento.fechamento(c)
        _confere_soma(f)
        s_m = f["notas_sem_medicao"]
        return (_retrato_do_mes(f, "2026-05"),
                [(e["numero"], e["valor_centavos"], e["paga_em_parte"]) for e in f["em_aberto"]],
                [(e["numero"], e["valor_centavos"], e["paga_em_parte"]) for e in s_m["em_aberto"]], s_m["pagas"])

    # antes da marca: a falta em dobro passa do valor da nota (limitada a ele), a baixa do titulo antigo conta como
    # recebimento (falta 1.860.001 x 50% = 930.000,5 -> 930.001) e a nota quitada aparece paga em parte
    em_dobro = retrato()
    assert em_dobro == (
        (protocolado, 112_000, 1_000_001 + 930_001 + 558_001),
        [(dobrada, 1_000_001, False), (estornada, 930_001, True), (quitada, 558_001, True)],
        [(solta, 74_001, True), (solta_paga, 83_001, True)], {"quantidade": 0, "valor_centavos": 0})

    _marcar_titulos(c, _titulo(c, dobrada, 1), _titulo(c, estornada, 0), _titulo(c, quitada, 1), _titulo(c, solta, 0),
                    _titulo(c, solta_paga, 1))
    assert retrato() == (
        (protocolado, 500_000 + 600_001, 500_001 + 1_000_001),
        # a paga em parte, pelo que falta no titulo vigente; a que so' tinha baixa no antigo, inteira, pelo bruto
        [(dobrada, 500_001, True), (estornada, 1_000_001, False)],
        [(solta, 80_001, False)], {"quantidade": 1, "valor_centavos": 90_001})
    # a pagina da medicao le os mesmos titulos: devido, recebido e falta sem o excluido, que aparece a' parte
    n = sincronizacao_rm.notas_da_medicao(c, a)[0]
    assert (n["devido_centavos"], n["recebido_centavos"], n["falta_centavos"]) == (930_001, 430_000, 500_001)
    assert [t["valor_original_centavos"] for t in n["titulos_excluidos_rm"]] == [930_001]

    c.execute("UPDATE baixas SET excluida_rm_em=NULL")
    c.commit()
    assert retrato() == em_dobro


def _excluir_notas_no_rm(c, *numeros):
    """Marca as notas como a sincronizacao marca (`sincronizacao_rm._marcar`): a nota deixa de ser ativa, o vinculo e'
    desfeito e os titulos dela saem junto."""
    marcas = ",".join("?" * len(numeros))
    alvo = [f"{int(n):09d}" for n in numeros]
    notas = c.execute(f"SELECT id, coligada, idmov, numero, serie, emissao, valor_centavos, situacao FROM notas_fiscais "
                      f"WHERE numero IN ({marcas}) ORDER BY id", alvo).fetchall()
    assert len(notas) == len(numeros)
    titulos = c.execute(f"""SELECT b.id, b.coligada, b.idlan, b.nota_id, b.valor_original_centavos, b.valor_baixado_centavos,
                                   b.status_lan, n.excluida_rm_em AS nota_excluida
                            FROM baixas b JOIN notas_fiscais n ON n.id=b.nota_id WHERE n.numero IN ({marcas})
                            ORDER BY b.id""", alvo).fetchall()
    with db.mutacao(c):
        sincronizacao_rm._marcar(c, None, None, notas, titulos)


def test_nota_excluida_no_rm_nao_entra_no_protocolado_nem_no_em_aberto(cenario):
    """A nota que o RM deixou de devolver (movimento refeito) sai do protocolado e do em aberto. Com a substituta
    ligada, a medicao conta uma vez; a medicao que fica sem nota volta ao em aberto pelo valor dela ("sem nota
    ligada"); a nota sem medicao some da lista a' parte e da contagem das pagas, e do a receber da lista de Obras."""
    c, ids = cenario
    p = ids["propria"]
    a = medir(c, p, 1, "2026-05", "protocolada", 1_000_001, aprovado=1_000_001, protocolo="2026-06-01")
    antiga = nota(c, 1_000_001, [a], titulos=[(930_001, 0, 0)])
    nova = nota(c, 1_000_001, [a], titulos=[(930_001, 0, 0)])               # a substituta, com o movimento refeito
    b = medir(c, p, 2, "2026-05", "protocolada", 500_001, aprovado=500_001, protocolo="2026-06-02")
    unica = nota(c, 500_001, [b])
    solta = nota(c, 80_001, centro="9.001.001")
    solta_paga = nota(c, 90_001, centro="9.001.001", titulos=PAGO(83_001))

    def retrato():
        f = fechamento.fechamento(c)
        _confere_soma(f)
        s_m = f["notas_sem_medicao"]
        return (_retrato_do_mes(f, "2026-05"), f["por_ano"]["2026"]["sem_nota_centavos"],
                sorted((e["tipo_aberto"], e["numero"], e["valor_centavos"]) for e in f["em_aberto"]),
                [(e["numero"], e["valor_centavos"]) for e in s_m["em_aberto"]], s_m["pagas"],
                diretoria.a_receber_por_obra(c, na_cota=True))

    # antes da marca: a nota antiga dobra o protocolado e o em aberto da medicao
    assert retrato() == (
        (2_000_002 + 500_001, 0, 2_000_002 + 500_001), 0,
        sorted([("nota", antiga, 1_000_001), ("nota", nova, 1_000_001), ("nota", unica, 500_001)]),
        [(solta, 80_001)], {"quantidade": 1, "valor_centavos": 90_001},
        {p: 1_000_001 + 500_001 + 80_001})

    _excluir_notas_no_rm(c, antiga, unica, solta, solta_paga)
    assert retrato() == (
        (1_000_001, 0, 1_000_001 + 500_001), 500_001,
        sorted([("nota", nova, 1_000_001), ("sem_nota", None, 500_001)], key=lambda e: (e[0], e[1] or "")),
        [], {"quantidade": 0, "valor_centavos": 0},
        {p: 1_000_001 + 500_001})
    # a pagina da medicao diz a nota como excluida no RM, fora da lista das que contam
    assert [n["numero"] for n in sincronizacao_rm.notas_da_medicao(c, a)] == [f"{int(nova):09d}"]
    assert [n["numero"] for n in sincronizacao_rm.notas_excluidas_da_medicao(c, a)] == [f"{int(antiga):09d}"]


# ---------------------------------------------------------------- familias de valor (issue #805)

def test_diferenca_aprovado_x_pedido_so_das_medicoes_com_boletim_e_pedido(cenario):
    # #805: os dois lados da diferenca saem prontos, na cota, e so' das medicoes que tem o valor do boletim gravado E
    # o pedido. A medicao em analise nao e' diferenca (e' etapa nao alcancada), e a de nota emitida sem o valor do
    # boletim nao tem dois valores para comparar. Centavo impar: a cota de 50% arredonda cada lado uma vez.
    from app import avisos_medicao
    c, ids = cenario
    medir(c, ids["propria"], 1, "2026-03", "boletim_recebido", 1_000_001, 990_001)          # aprovado abaixo do pedido
    medir(c, ids["propria"], 2, "2026-03", "planilha_enviada", 500_000)                     # em analise: fora
    medir(c, ids["propria"], 3, "2026-03", "nota_emitida", 300_003)                         # sem o valor do boletim: fora
    medir(c, ids["propria"], 4, "2026-03", "boletim_recebido", None, 70_001)                # boletim sem pedido: fora
    medir(c, ids["consorcio"], 1, "2026-03", "recebida", 200_001, 200_001)                  # igual: cota 100.001 nos dois
    medir(c, ids["consorcio"], 2, "2026-03", "espelho_gerado", 333_333, 333_331)            # cotas 166.667 e 166.666
    f = fechamento.fechamento(c, datetime.date(2026, 11, 18))
    _confere_soma(f)
    mes = _mes(f, "2026-03")
    par = lambda x: (x["aprovado_com_pedido_centavos"], x["pedido_do_aprovado_centavos"])   # noqa: E731
    propria, consorcio = (next(o for o in mes["obras"] if o["contrato_id"] == ids[k]) for k in ("propria", "consorcio"))
    assert [par(md) for md in propria["medicoes"]] == [(990_001, 1_000_001), (0, 0), (0, 0), (0, 0)]
    assert [par(md) for md in consorcio["medicoes"]] == [(100_001, 100_001), (166_666, 166_667)]
    assert par(propria) == (990_001, 1_000_001) and par(consorcio) == (266_667, 266_668)
    assert par(mes) == par(f["por_ano"]["2026"]) == par(f["acumulado"]["2026"]) == (1_256_668, 1_266_669)
    assert par(f["por_ano"]["2025"]) == (0, 0)
    # nao e' "medido - aprovado": o medido leva a medicao em analise, que nao e' diferenca
    assert mes["medido_centavos"] - mes["aprovado_centavos"] == 500_000
    assert mes["aprovado_centavos"] == 990_001 + 300_003 + 70_001 + 100_001 + 166_666
    # o limite da diferenca critica e' o do aviso "aprovado abaixo do pedido" (#741): um numero so'
    assert f["diferenca_critica_por_mil"] == avisos_medicao.ABAIXO_DO_PEDIDO_POR_MIL == 5


def test_diferenca_aprovado_x_pedido_nao_some_com_a_trava_do_a_receber(cenario):
    # #805: a trava do total a receber esconde o recebido e o em aberto; aprovado e pedido nao deixam deduzi-los
    c, ids = cenario
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'", (json.dumps({"total_a_receber_liberado": False}),))
    medir(c, ids["propria"], 1, "2026-03", "protocolada", 1_000_001, 990_001, protocolo="2026-04-10")
    f = fechamento.fechamento(c, datetime.date(2026, 11, 18))
    mes = _mes(f, "2026-03")
    assert not f["total_a_receber_liberado"] and mes["em_aberto_centavos"] is None
    assert (mes["aprovado_com_pedido_centavos"], mes["pedido_do_aprovado_centavos"]) == (990_001, 1_000_001)


def test_medido_do_ano_anterior_so_em_competencia_encerrada(cenario):
    # #805: a referencia da variacao do medido e' o medido do mesmo mes do ano anterior, quando ele esta' na pagina e
    # tem valor, e so' nos meses anteriores ao de hoje (o mes em curso ainda recebe medicao)
    c, ids = cenario
    medir(c, ids["propria"], 1, "2025-03", "recebida", 900_001, 900_001)
    medir(c, ids["propria"], 2, "2026-03", "boletim_recebido", 1_000_001, 1_000_001)
    medir(c, ids["propria"], 3, "2026-05", "boletim_recebido", 100_001, 100_001)            # 05/2025 sem lancamento
    medir(c, ids["propria"], 4, "2025-11", "recebida", 500_001, 500_001)
    medir(c, ids["consorcio"], 1, "2026-11", "planilha_enviada", 800_001)
    f = fechamento.fechamento(c, datetime.date(2026, 11, 18))
    referencia = lambda f: {m["competencia"]: m["medido_ano_anterior_centavos"] for m in f["meses"]}   # noqa: E731
    assert referencia(f) == {"2025-03": None,            # 2024 nao esta' na pagina
                             "2025-11": None,
                             "2026-03": 900_001,
                             "2026-05": None,            # o ano anterior nao teve medido no mes
                             "2026-11": None}            # o mes de hoje ainda esta' aberto
    # virou o mes: novembro encerrou e passa a comparar (o medido de 11/2025, na cota: a obra propria conta inteira)
    assert referencia(fechamento.fechamento(c, datetime.date(2026, 12, 1)))["2026-11"] == 500_001
    # a referencia nao entra nas somas nem desce para a obra e a medicao
    assert "medido_ano_anterior_centavos" not in fechamento.SOMAS
    assert all("medido_ano_anterior_centavos" not in o for m in f["meses"] for o in m["obras"])
