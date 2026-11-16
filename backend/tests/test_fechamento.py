"""Pagina Fechamento (issue #748): medido, aprovado, protocolado e recebido por mes de competencia de 2025 e 2026, na
cota, com o em aberto nota a nota. Os totais fecham ao centavo com as linhas abertas. Dados sinteticos."""
import pathlib

import pytest

from app import auth, cadastro_aplicar, db, fechamento, medicoes
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
    """Nota do RM ligada as medicoes. `titulos`: [(original, baixado, status)]; sem titulos, um aberto pelo valor."""
    idmov = next(_IDMOV)
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, codtmv, "
                    "centro_custo, desconsiderada_em) VALUES (?,?,?,?,?,?,?,?,?)",
                    (coligada, idmov, f"{idmov:09d}", emissao, valor, "cancelada" if desconsiderada else situacao,
                     codtmv, centro, "2026-11-01" if desconsiderada else None)).lastrowid
    for k, (orig, baixado, st) in enumerate(titulos or [(valor, 0, 0)]):
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


def _confere_soma(f):
    """Os totais da pagina fecham com a soma das linhas abertas, ao centavo, em todos os niveis."""
    for m in f["meses"]:
        for o in m["obras"]:
            for md in o["medicoes"]:
                assert md["protocolado_centavos"] == sum(n["valor_centavos"] for n in md["notas"])
                assert md["recebido_centavos"] == sum(n["valor_centavos"] for n in md["notas"] if n["recebida"])
                # em aberto = (a) nota protocolada nao paga + (b) medicao protocolada sem nota ligada
                assert md["em_aberto_centavos"] == md["protocolado_centavos"] - md["recebido_centavos"] + md["sem_nota_centavos"]
                assert md["sem_nota_centavos"] == 0 or (md["sem_nota"] and md["notas"] == [])
            for k in SOMAS:
                assert o[k] == sum(md[k] for md in o["medicoes"]), (m["competencia"], o["obra"], k)
        for k in SOMAS:
            assert m[k] == sum(o[k] for o in m["obras"]), (m["competencia"], k)
    for ano, tot in f["por_ano"].items():
        for k in SOMAS:
            assert tot[k] == sum(m[k] for m in f["meses"] if m["competencia"][:4] == ano), (ano, k)
        assert tot["meses"] == sum(1 for m in f["meses"] if m["competencia"][:4] == ano)
    assert f["em_aberto_centavos"] == f["em_aberto_notas_centavos"] + f["em_aberto_sem_nota_centavos"]
    assert f["em_aberto_sem_nota_centavos"] == sum(m["sem_nota_centavos"] for m in f["meses"])
    assert f["em_aberto_centavos"] == sum(e["valor_centavos"] for e in f["em_aberto"]) \
        == sum(m["em_aberto_centavos"] for m in f["meses"])


def test_sem_lancamento_a_pagina_vem_vazia_sem_zero_disfarcado(cenario):
    c, _ = cenario
    f = fechamento.fechamento(c)
    assert f["anos"] == ["2025", "2026"] and f["meses"] == [] and f["em_aberto"] == []
    assert f["acumulado"]["ate_mes"] is None
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


def test_consorcio_na_cota_com_centavo_impar_e_nfse_da_consorciada_fora(cenario):
    """Em consorcio: a cota de cada parcela (50%, meio para cima, uma vez por parcela); a fatura do consorcio (coligada
    do contrato, valor cheio) e' a que cobra o orgao; a NFS-e da empresa (coligada 1) na mesma medicao nao conta."""
    c, ids = cenario
    k = ids["consorcio"]
    mid = medir(c, k, 1, "2025-07", "protocolada", 2_000_003, aprovado=2_000_001, protocolo="2025-09-02")
    nota(c, 2_000_001, [mid], coligada=12)
    nota(c, 1_000_001, [mid], coligada=1)                                    # NFS-e da consorciada: fora
    f = fechamento.fechamento(c)
    m = _mes(f, "2025-07")
    assert _numeros(m) == (1_000_001, 1_000_001, 1_000_001, 0, 1_000_001)   # 2.000.001 x 50% = 1.000.000,5 -> 1.000.001
    assert [(e["obra"], e["protocolo_em"], e["valor_centavos"]) for e in f["em_aberto"]] == [
        ("Consórcio", "2025-09-02", 1_000_001)]
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
    assert f["em_aberto_centavos"] == 570_001
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
    assert f["meses"] == [] and f["em_aberto"] == [] and f["em_aberto_centavos"] == 0
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
    assert f["em_aberto_centavos"] == 800_001
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
    assert f["em_aberto_centavos"] == 250_000                                   # (c) fora da soma
    assert f["notas_sem_medicao"]["em_aberto_centavos"] == 250_000
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
              "SELECT ?, id, 250000, 'manual', 't' FROM notas_fiscais WHERE numero=?", (mid, f"{int(solta):09d}"))
    c.commit()
    f = fechamento.fechamento(c)
    assert [(e["tipo_aberto"], e["numero"]) for e in f["em_aberto"]] == [("nota", solta)]
    assert f["notas_sem_medicao"]["em_aberto"] == [] and f["em_aberto_centavos"] == 250_000
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


def test_em_aberto_escondido_ate_liberar_o_total_a_receber(cenario):
    """A trava `geral.yaml: diretoria.total_a_receber_liberado` (a da lista de Obras) vale para o em aberto: sem ela,
    as linhas aparecem e o valor vem nulo; medido, aprovado, protocolado e recebido continuam."""
    import json
    c, ids = cenario
    mid = medir(c, ids["propria"], 1, "2026-03", "protocolada", 500_000, protocolo="2026-04-01")
    nota(c, 500_000, [mid])
    medir(c, ids["propria"], 2, "2026-03", "protocolada", 70_000, protocolo="2026-04-02")
    nota(c, 1_000, centro="9.001.001", emissao="2026-03-02")
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'", (json.dumps({"total_a_receber_liberado": False}),))
    c.commit()
    f = fechamento.fechamento(c)
    assert f["total_a_receber_liberado"] is False
    m = _mes(f, "2026-03")
    assert (m["protocolado_centavos"], m["em_aberto_centavos"], m["sem_nota_centavos"]) == (500_000, None, None)
    assert f["por_ano"]["2026"]["em_aberto_centavos"] is None and f["em_aberto_centavos"] is None
    assert len(f["em_aberto"]) == 2 and all(e["valor_centavos"] is None for e in f["em_aberto"])
    assert f["notas_sem_medicao"]["em_aberto_centavos"] is None
    assert [e["valor_centavos"] for e in f["notas_sem_medicao"]["em_aberto"]] == [None]


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
