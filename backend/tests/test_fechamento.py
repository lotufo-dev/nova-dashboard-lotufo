"""Pagina Fechamento (issue #748): medido, aprovado, protocolado e recebido por mes de competencia de 2025 e 2026, na
cota, com o em aberto nota a nota. Os totais fecham ao centavo com as linhas abertas. Dados sinteticos."""
import pathlib

import pytest

from app import auth, cadastro_aplicar, cadastro_arquivos, db, fechamento, medicoes
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
                assert md["recebido_centavos"] == sum(n["recebido_centavos"] for n in md["notas"])
                for n in md["notas"]:                       # cada nota: recebido + em aberto = o valor bruto dela
                    assert n["recebido_centavos"] + n["em_aberto_centavos"] == n["valor_centavos"]
                    assert n["recebido_centavos"] >= 0 and n["em_aberto_centavos"] >= 0
                    assert n["recebida"] == (n["em_aberto_centavos"] == 0)
                    assert n["paga_em_parte"] == (0 < n["em_aberto_centavos"] < n["valor_centavos"])
                # a nota fora da conta (fatura do consorcio preterida pela nota da empresa) nao leva valor nem soma
                assert all(set(n) == {"nota_id", "numero"} for n in md["notas_fora_da_conta"])
                assert md["notas_fora_da_conta"] == [] or md["notas"]
                # em aberto = (a) nota protocolada nao paga (ou paga em parte) + (b) medicao protocolada sem nota ligada
                assert md["em_aberto_notas_centavos"] == md["protocolado_centavos"] - md["recebido_centavos"]
                assert md["em_aberto_centavos"] == md["em_aberto_notas_centavos"] + md["sem_nota_centavos"]
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
        assert tot["em_aberto_notas_centavos"] == sum(e["valor_centavos"] for e in do_ano if e["tipo_aberto"] == "nota")
        assert tot["sem_nota_centavos"] == sum(e["valor_centavos"] for e in do_ano if e["tipo_aberto"] == "sem_nota")
        assert tot["em_aberto_centavos"] == tot["protocolado_centavos"] - tot["recebido_centavos"] + tot["sem_nota_centavos"]
    assert all(e["competencia"][:4] in f["anos"] for e in f["em_aberto"])
    # nenhuma nota em duas partes: a que conta numa medicao (a), a que ficou fora da conta e a sem medicao ligada (c)
    mds = [md for m in f["meses"] for o in m["obras"] for md in o["medicoes"]]
    contam = {n["nota_id"] for md in mds for n in md["notas"]}
    fora = {n["nota_id"] for md in mds for n in md["notas_fora_da_conta"]}
    soltas = {e["nota_id"] for e in f["notas_sem_medicao"]["em_aberto"]}
    assert not contam & soltas and not fora & soltas
    assert all(not {n["nota_id"] for n in md["notas"]} & {n["nota_id"] for n in md["notas_fora_da_conta"]} for md in mds)


def _em_aberto(f):
    """O em aberto dos dois anos somados (a tela mostra um ano por vez, de `por_ano`)."""
    return sum(f["por_ano"][a]["em_aberto_centavos"] for a in f["anos"])


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
    escondidos = ("recebido_centavos", "em_aberto_centavos", "em_aberto_notas_centavos", "sem_nota_centavos")
    niveis = [m, f["por_ano"]["2026"], f["por_ano"]["2025"], f["acumulado"]["2026"], f["acumulado"]["2025"],
              *m["obras"], *m["obras"][0]["medicoes"]]
    assert all(x[k] is None for x in niveis for k in escondidos)
    for md in m["obras"][0]["medicoes"]:
        assert md["sem_nota"] is False
        for n in md["notas"]:
            assert n["valor_centavos"] and (n["recebida"], n["paga_em_parte"], n["recebido_centavos"], n["em_aberto_centavos"]) == (
                None, None, None, None)
    assert f["em_aberto"] == [] and f["em_aberto_anteriores"] == {"quantidade": 0, "valor_centavos": None}
    assert f["notas_sem_medicao"] == {"em_aberto": [], "em_aberto_centavos": None,
                                      "pagas": {"quantidade": 0, "valor_centavos": None}}
    # nenhum numero do recebido nem do em aberto sobra na resposta
    texto = json.dumps(f)
    assert all(str(v) not in texto for v in (435_000, 65_000, 525_000, 135_000, 83_000))


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
    um = nota(c, 300_000, [h], titulos=[(279_000, 278_899, 1)])                              # faltam R$ 1,01: em parte
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
                            "paga_em_parte": True}]
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
    quase = nota(c, 1_000_001, centro="9.001.001", emissao="2024-09-10", titulos=[(1_000_001, 995_000, 1)])
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
                            "paga_em_parte": True}]
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
