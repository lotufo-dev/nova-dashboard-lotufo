"""Pagina Em aberto (issue #816): o em aberto do Fechamento nota a nota, por contratante e pela data do protocolo. O
total, o subtotal de cada contratante e cada linha sao os do Fechamento, ao centavo; a' parte, fora do total, a nota
sem medicao ligada e o em aberto de antes de 2025. Dados ficticios (os cenarios de test_fechamento), centavos impares."""
import datetime
import json

import pytest

from app import a_receber, contratante, fechamento, feriados, fila_medicoes
from tests.test_fechamento import (CONSORCIO, EMPRESA, PAGO, SEM_ENVIO_DA_NOTA, _emitir, _lancar_dois_anos,  # noqa: F401
                                   _propria, cenario, contratantes, exemplo, medir, nota)

HOJE = datetime.date(2026, 11, 18)
SO_DO_FECHAMENTO = ("parada", "orgao_pagou_em")          # o que a linha leva alem da linha do em aberto do Fechamento
SO_DA_NOTA_SOLTA = "ligada_a_medicao_nao_enviada"         # a marca que a nota sem medicao leva alem da do Fechamento


def _linhas(r):
    return [linha for g in r["contratantes"] for linha in g["linhas"]]


def _grupo(r, nome):
    return next(g for g in r["contratantes"] if g["contratante"] == nome)


def _em_aberto_do_contratante(f, nome, chave, ano):
    """O em aberto da linha do Fechamento com o mesmo par (nome, chave) do grupo (issue #864): o nome sozinho acharia a
    linha errada quando dois contratantes tem o mesmo nome."""
    return next((g["em_aberto_centavos"] for g in f["por_contratante"][ano]
                 if (g["contratante"], g["contratante_chave"]) == (nome, chave)), 0)


def _chave_da_linha(e):
    return (e["medicao_id"], e["tipo_aberto"], e["nota_id"] or 0)


def _confere_com_o_fechamento(r, f):
    """O total, o de cada ano, o de cada contratante e cada linha fecham com o Fechamento, ao centavo."""
    assert r["em_aberto_centavos"] == sum(f["por_ano"][a]["em_aberto_centavos"] for a in f["anos"])
    assert r["por_ano"] == {a: f["por_ano"][a]["em_aberto_centavos"] for a in f["anos"]}
    for g in r["contratantes"]:
        assert g["por_ano"] == {a: _em_aberto_do_contratante(f, g["contratante"], g["chave"], a) for a in f["anos"]}, g["contratante"]
        assert g["em_aberto_centavos"] == sum(g["por_ano"].values()) == sum(e["valor_centavos"] for e in g["linhas"])
        assert g["quantidade"] == len(g["linhas"])
        assert g["notas_sem_medicao_centavos"] == sum(e["valor_centavos"] for e in g["notas_sem_medicao"])
        # dentro do contratante, pela data do protocolo (sem ela, a da emissao da nota), a mais antiga primeiro
        datas = [e["protocolo_em"] or e["emitida_em"] or "9999" for e in g["linhas"]]
        assert datas == sorted(datas)
    # as linhas sao as do Fechamento, nenhuma a mais nem a menos, com os mesmos campos e valores
    linhas = sorted(({k: v for k, v in e.items() if k not in SO_DO_FECHAMENTO} for e in _linhas(r)), key=_chave_da_linha)
    assert linhas == sorted(f["em_aberto"], key=_chave_da_linha)
    assert r["quantidade"] == len(f["em_aberto"])
    # a' parte, fora do total: as mesmas do Fechamento
    assert r["anteriores"] == f["em_aberto_anteriores"]
    assert r["anteriores"]["quantidade"] == sum(g["anteriores"]["quantidade"] for g in r["contratantes"])
    assert r["notas_sem_medicao_centavos"] == f["notas_sem_medicao"]["em_aberto_centavos"]
    assert [{k: v for k, v in n.items() if k != SO_DA_NOTA_SOLTA} for n in r["notas_sem_medicao"]] == f["notas_sem_medicao"]["em_aberto"]
    assert all(isinstance(n[SO_DA_NOTA_SOLTA], bool) for n in r["notas_sem_medicao"])
    assert sorted(n["nota_id"] for g in r["contratantes"] for n in g["notas_sem_medicao"]) == sorted(
        n["nota_id"] for n in f["notas_sem_medicao"]["em_aberto"])
    # o maior em aberto primeiro, empate pelo nome; cada contratante (o par nome e chave) uma vez
    assert [g["em_aberto_centavos"] for g in r["contratantes"]] == sorted((g["em_aberto_centavos"] for g in r["contratantes"]), reverse=True)
    assert len({(g["contratante"], g["chave"]) for g in r["contratantes"]}) == len(r["contratantes"])
    # e todo par do Fechamento com em aberto tem o seu grupo aqui, pelo mesmo valor
    for a in f["anos"]:
        for g in f["por_contratante"][a]:
            if g["em_aberto_centavos"]:
                par = (g["contratante"], g["contratante_chave"])
                assert next(x for x in r["contratantes"] if (x["contratante"], x["chave"]) == par)["por_ano"][a] == g["em_aberto_centavos"]


def test_total_subtotal_e_linhas_sao_os_do_fechamento_com_consorcio_e_nota_partilhada(contratantes):
    """A SINFRA de duas superintendencias e' um contratante so'; a fatura do consorcio em tres parcelas entra pela cota
    da soma; a fatura partilhada entre obras de dois contratantes entra em cada um pela parte dele, uma vez; a paga em
    parte, pelo que falta; a medicao sem nota, pelo valor dela; e o que e' de antes de 2025 fica a' parte, no
    contratante da obra. A chave de cada contratante e' a da pagina dele em Obras."""
    c, ids = contratantes
    m = _lancar_dois_anos(c, ids)
    r = a_receber.a_receber(c, HOJE)
    f = fechamento.fechamento(c, HOJE)
    _confere_com_o_fechamento(r, f)
    assert r["total_a_receber_liberado"] is True and r["anos"] == ["2025", "2026"]
    # SINFRA: as duas faturas abertas da Ponte (1.000.001 na cota) e a parte do reajuste na partilhada (200.001);
    # Secretaria X: a paga em parte da Escola (65.000), a medicao sem nota (70.001) e a parte do Hospital (99.991);
    # Companhia Y: contrato ativo e nada em aberto, com zero
    assert [(g["contratante"], g["chave"], g["quantidade"], g["em_aberto_centavos"]) for g in r["contratantes"]] == [
        ("SINFRA", "sinfra", 3, 1_200_002), ("Secretaria X", "orgao-x", 3, 234_992), ("Companhia Y", "companhia-y", 0, 0)]
    assert r["em_aberto_centavos"] == 1_434_994 and r["por_ano"] == {"2025": 0, "2026": 1_434_994}
    # a partilhada: uma linha em cada contratante, pela parte de cada medicao na cota do contrato dela
    partilhada = [(e["medicao_id"], e["valor_centavos"]) for e in _linhas(r) if e["nota_id"] == m["partilhada"]]
    assert sorted(partilhada) == sorted([(m["reajuste"], 200_001), (m["hospital"], 99_991)])
    # pela data do protocolo: o Hospital (09/04), a Escola paga em parte (01/06) e a sem nota (01/07)
    secretaria = [(e["obra"], e["tipo_aberto"], e["valor_centavos"], e["paga_em_parte"]) for e in _grupo(r, "Secretaria X")["linhas"]]
    assert secretaria == [("Hospital", "nota", 99_991, False), ("Escola", "nota", 65_000, True), ("Escola", "sem_nota", 70_001, False)]
    # o anterior a 2025 (a Escola de 2024) fica a' parte no contratante dela, fora do total
    assert _grupo(r, "Secretaria X")["anteriores"] == {"quantidade": 1, "valor_centavos": 50_000}
    assert _grupo(r, "SINFRA")["anteriores"] == {"quantidade": 0, "valor_centavos": 0}


def test_nota_partilhada_paga_em_parte_reparte_a_falta_com_residuo_e_continua_fechando(contratantes):
    c, ids = contratantes
    m = _lancar_dois_anos(c, ids)
    c.execute("UPDATE baixas SET valor_baixado_centavos=valor_original_centavos-200001, status_lan=4, data_baixa='2026-07-01' "
              "WHERE nota_id=?", (m["partilhada"],))
    c.commit()
    r = a_receber.a_receber(c, HOJE)
    _confere_com_o_fechamento(r, fechamento.fechamento(c, HOJE))
    # a falta de 200.001 reparte-se 114.286 e 85.715; na cota, 57.143 e 28.569
    assert sorted((e["medicao_id"], e["valor_centavos"], e["paga_em_parte"]) for e in _linhas(r) if e["nota_id"] == m["partilhada"]) == sorted(
        [(m["reajuste"], 57_143, True), (m["hospital"], 28_569, True)])


def test_consorcio_com_a_nota_da_empresa_e_a_fatura_ligadas_conta_uma_vez(exemplo):
    """A nota da empresa ao consorcio e a fatura do consorcio ligadas a' mesma medicao: a linha e' a da nota da empresa,
    pela face; a fatura nao entra de novo."""
    c, k = exemplo
    m1 = medir(c, k, 1, "2026-03", "protocolada", 2_000_001, aprovado=2_000_001, protocolo="2026-04-10")
    nota(c, 2_400_003, [m1], coligada=CONSORCIO, titulos=PAGO(2_232_003))
    da_empresa = nota(c, 1_000_001, [m1], coligada=EMPRESA, centro="5.001.001")
    propria = medir(c, _propria(c), 1, "2026-03", "protocolada", 700_001, aprovado=700_001, protocolo="2026-04-12")
    nota(c, 700_001, [propria], titulos=PAGO(650_001))
    r = a_receber.a_receber(c, HOJE)
    _confere_com_o_fechamento(r, fechamento.fechamento(c, HOJE))
    assert [(e["medicao_id"], e["tipo_aberto"], e["numero"], e["valor_centavos"]) for e in _linhas(r)] == [
        (m1, "nota", da_empresa, 1_000_001)]
    assert r["em_aberto_centavos"] == 1_000_001


def test_repasse_sem_baixa_fica_no_contratante_com_a_data_em_que_o_orgao_pagou(exemplo):
    """Na medicao que o orgao ja' pagou (recebida), a nota da empresa ao consorcio sem baixa e' repasse sem baixa: entra
    no total e no contratante, como no Fechamento, sem tempo parado com o orgao, e com a data do recebimento (nula na
    medicao recebida sem data)."""
    c, k = exemplo
    paga = medir(c, k, 2, "2026-09", "recebida", 1_200_003, aprovado=1_200_003, protocolo="2026-10-03")
    c.execute("UPDATE medicoes SET recebida_em='2026-11-04' WHERE id=?", (paga,)); c.commit()
    n1 = nota(c, 600_002, [paga], coligada=EMPRESA, centro="5.001.001", titulos=[(558_001, 0, 0)])
    sem_data = medir(c, k, 3, "2026-09", "recebida", 400_001, aprovado=400_001, protocolo="2026-10-05")
    n2 = nota(c, 200_001, [sem_data], coligada=EMPRESA, centro="5.001.001")
    r = a_receber.a_receber(c, HOJE)
    _confere_com_o_fechamento(r, fechamento.fechamento(c, HOJE))
    assert [(e["numero"], e["tipo_aberto"], e["valor_centavos"], e["parada"], e["orgao_pagou_em"]) for e in _linhas(r)] == [
        (n1, "repasse", 600_002, None, "2026-11-04"), (n2, "repasse", 200_001, None, None)]
    assert _grupo(r, "SINFRA")["alem_do_prazo"] == 0


def _recebidas(c, cid, numero, dias):
    """Medicoes recebidas nos ultimos doze meses, cada uma `dias[i]` dias depois do protocolo: a amostra do prazo do
    orgao (docs/adr/0007, cinco casos no minimo)."""
    for i, d in enumerate(dias):
        protocolo = datetime.date(2026, 6, 1) + datetime.timedelta(days=7 * i)
        mid = medir(c, cid, numero + i, "2026-05", "recebida", 100_001, aprovado=100_001, protocolo=protocolo.isoformat())
        c.execute("UPDATE medicoes SET recebida_em=? WHERE id=?", ((protocolo + datetime.timedelta(days=d)).isoformat(), mid))
    c.commit()


def test_tempo_parado_desde_o_protocolo_com_o_prazo_do_orgao_como_limite(contratantes):
    """O tempo parado e a data prevista de cada linha: critico so' depois da data esperada (o primeiro protocolo + o
    prazo do orgao, o terceiro quartil); antes dela em andamento; o protocolo de hoje e' feito; sem prazo do orgao,
    em andamento e sem data prevista. A leitura e' a da fila de Medicoes para a mesma medicao."""
    c, ids = contratantes
    _recebidas(c, ids["Escola"], 50, [10, 20, 30, 40, 50])            # Secretaria X: prazo de 40 dias (4o de 5)
    atrasada = medir(c, ids["Escola"], 1, "2026-08", "protocolada", 300_001, aprovado=300_001, protocolo="2026-09-01")
    nota(c, 300_001, [atrasada], emissao="2026-08-25")
    no_prazo = medir(c, ids["Hospital"], 1, "2026-10", "protocolada", 300_003, aprovado=300_003, protocolo="2026-11-10")
    nota(c, 300_003, [no_prazo], coligada=12, emissao="2026-11-05")
    hoje = medir(c, ids["Escola"], 2, "2026-10", "protocolada", 70_001, protocolo=HOJE.isoformat())
    sem_prazo = medir(c, ids["Estrada"], 1, "2026-07", "protocolada", 500_001, aprovado=500_001, protocolo="2026-08-03")
    r = a_receber.a_receber(c, HOJE)
    _confere_com_o_fechamento(r, fechamento.fechamento(c, HOJE))
    secretaria, sinfra = _grupo(r, "Secretaria X"), _grupo(r, "SINFRA")
    assert (secretaria["prazo_orgao_dias"], sinfra["prazo_orgao_dias"], _grupo(r, "Companhia Y")["prazo_orgao_dias"]) == (40, None, None)
    p = {e["medicao_id"]: e["parada"] for e in _linhas(r)}
    assert p[atrasada] == {"desde": "2026-09-01", "dias_uteis": feriados.dias_uteis_entre(datetime.date(2026, 9, 1), HOJE),
                           "hoje": False, "situacao": "critico", "prazo_orgao_dias": 40, "esperada": "2026-10-11",
                           "alem_do_prazo": True, "revisao": None}
    assert (p[no_prazo]["situacao"], p[no_prazo]["esperada"], p[no_prazo]["alem_do_prazo"]) == ("andamento", "2026-12-20", False)
    assert (p[hoje]["situacao"], p[hoje]["hoje"], p[hoje]["dias_uteis"]) == ("feito", True, 0)
    assert (p[sem_prazo]["situacao"], p[sem_prazo]["esperada"], p[sem_prazo]["prazo_orgao_dias"]) == ("andamento", None, None)
    # o atraso conta no contratante e na pagina
    assert (secretaria["alem_do_prazo"], sinfra["alem_do_prazo"], r["alem_do_prazo"]) == (1, 0, 1)
    # uma leitura so': a mesma da fila de Medicoes para a medicao de um protocolo
    da_fila = fila_medicoes.paradas(c, HOJE)
    assert all(p[mid] == da_fila[mid] for mid in (atrasada, no_prazo, hoje, sem_prazo))
    # a Secretaria X: a do protocolo mais antigo primeiro
    assert [e["medicao_id"] for e in secretaria["linhas"]] == [atrasada, no_prazo, hoje]


def _protocolar_de_novo(c, mid, dia, desfeito=False):
    c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem, desfeita_em) VALUES (?, ?, 'manual', ?)",
              (mid, dia, "2026-11-01 10:00:00" if desfeito else None))
    c.commit()


def test_reapresentada_e_par_em_datas_diferentes_tem_os_mesmos_dias_em_todas_as_telas(contratantes):
    """Issue #914 (decisao do dono de 26/11/2026): a medicao com a nota protocolada mais de uma vez conta os dias, o
    atraso e a data esperada do PRIMEIRO protocolo na pagina Em aberto, na fila de Medicoes e no Resumo das medicoes,
    e leva a revisao (o primeiro protocolo, quantas vezes foi reapresentada, o ultimo envio). O par medicao +
    reajuste protocolado em dias diferentes vira duas linhas na fila e no Resumo, cada uma com os proprios dias e a
    propria data esperada, como na Em aberto. O total da Em aberto continua o do Fechamento."""
    from app import inicio, resumo_medicoes
    c, ids = contratantes
    _recebidas(c, ids["Escola"], 50, [10, 20, 30, 40, 50])            # Secretaria X: prazo de 40 dias
    reapresentada = medir(c, ids["Escola"], 2, "2026-10", "protocolada", 300_001, aprovado=300_001, protocolo="2026-10-01")
    _protocolar_de_novo(c, reapresentada, "2026-10-20")              # reapresentada uma vez
    _protocolar_de_novo(c, reapresentada, "2026-10-20")              # o mesmo envio registrado duas vezes: nao conta
    _protocolar_de_novo(c, reapresentada, "2026-11-05", desfeito=True)   # protocolo desfeito: nao conta
    execucao = medir(c, ids["Escola"], 3, "2026-10", "protocolada", 200_003, aprovado=200_003, protocolo="2026-10-05")
    reajuste = medir(c, ids["Escola"], 3, "2026-10", "protocolada", 1_001, aprovado=1_001, tipo="reajuste",
                     protocolo="2026-10-15")
    unico = medir(c, ids["Escola"], 4, "2026-10", "protocolada", 70_001, protocolo="2026-10-20")
    _protocolar_de_novo(c, unico, "2026-10-20")                       # duas linhas no mesmo dia: protocolo unico

    r = a_receber.a_receber(c, HOJE)
    _confere_com_o_fechamento(r, fechamento.fechamento(c, HOJE))
    em_aberto = {e["medicao_id"]: e["parada"] for e in _linhas(r)}
    p = em_aberto[reapresentada]
    assert (p["desde"], p["esperada"], p["situacao"], p["alem_do_prazo"]) == ("2026-10-01", "2026-11-10", "critico", True)
    assert p["dias_uteis"] == feriados.dias_uteis_entre(datetime.date(2026, 10, 1), HOJE)
    assert p["revisao"] == {"primeiro_protocolo_em": "2026-10-01", "reapresentacoes": 1, "ultimo_envio_em": "2026-10-20"}
    assert em_aberto[unico]["revisao"] is None and em_aberto[execucao]["revisao"] is None
    # o par: a execucao passou da data esperada (05/10 + 40 = 14/11), o reajuste ainda nao (15/10 + 40 = 24/11)
    assert (em_aberto[execucao]["esperada"], em_aberto[execucao]["situacao"]) == ("2026-11-14", "critico")
    assert (em_aberto[reajuste]["esperada"], em_aberto[reajuste]["situacao"]) == ("2026-11-24", "andamento")

    # a fila de Medicoes: a mesma leitura, medicao a medicao, e o par em duas linhas
    assert all(fila_medicoes.paradas(c, HOJE)[mid] == em_aberto[mid] for mid in em_aberto)
    fila = [x for g in fila_medicoes.fila(c, HOJE, "2026-10")["grupos"] for x in g["linhas"]]
    assert {tuple(x["medicao_ids"]) for x in fila} >= {(reapresentada,), (execucao,), (reajuste,), (unico,)}
    assert all(x["parada"] == em_aberto[i] for x in fila for i in x["medicao_ids"] if i in em_aberto)
    # o Resumo das medicoes: o mesmo `parada` no cartao e a data do primeiro protocolo na etapa; o par em dois cartoes
    rdm = [x for g in resumo_medicoes.resumo(c, HOJE, "2026-10")["grupos"] for x in g["linhas"]]
    da_reapresentada = next(x for x in rdm if x["medicao_ids"] == [reapresentada])
    assert da_reapresentada["parada"] == p
    assert next(e for e in da_reapresentada["etapas"] if e["etapa"] == "protocolado")["data"] == "2026-10-01"
    assert [x["medicao_ids"] for x in rdm if execucao in x["medicao_ids"] or reajuste in x["medicao_ids"]] == [[execucao], [reajuste]]
    assert all(x["parada"] == em_aberto[x["medicao_id"]] for x in rdm if x["medicao_id"] in em_aberto)
    # a Inicio: atrasada e' a mesma medicao que passou da data esperada nas outras telas (a reapresentada e a execucao)
    previsao = inicio._previsao(c, HOJE)
    da_escola = [m for m in (reapresentada, execucao, reajuste, unico) if em_aberto[m]["alem_do_prazo"]]
    assert da_escola == [reapresentada, execucao]
    assert previsao["atrasado"]["quantidade"] == len([e for e in _linhas(r) if e["parada"] and e["parada"]["alem_do_prazo"]])


def test_obra_sem_o_passo_envio_da_nota_conta_da_emissao_da_nota_sem_data_prevista(exemplo):
    c, _ = exemplo
    p = _propria(c)
    c.execute("UPDATE contratos SET passos_medicao=? WHERE id=?", (SEM_ENVIO_DA_NOTA, p))
    a = medir(c, p, 1, "2026-08", "nota_emitida", 500_001, aprovado=500_001)
    _emitir(c, a, "2026-09-01")
    n1 = nota(c, 500_001, [a], coligada=EMPRESA, emissao="2026-09-01")
    r = a_receber.a_receber(c, HOJE)
    _confere_com_o_fechamento(r, fechamento.fechamento(c, HOJE))
    [e] = _linhas(r)
    assert (e["numero"], e["protocolo_em"], e["emitida_em"], e["valor_centavos"]) == (n1, None, "2026-09-01", 500_001)
    assert (e["parada"]["desde"], e["parada"]["situacao"], e["parada"]["esperada"]) == ("2026-09-01", "andamento", None)


def test_nota_sem_medicao_e_anterior_a_2025_ficam_a_parte_no_contratante_da_obra(cenario):
    """A nota em aberto no RM sem medicao ligada e o em aberto de antes de 2025 nao entram no total: ficam a' parte, no
    contratante da obra (a nota, pela obra do centro de custo; no consorcio sem centro, pela coligada)."""
    c, ids = cenario
    a = nota(c, 400_001, centro="9.001.001", emissao="2026-02-01")
    k = nota(c, 600_001, coligada=12, emissao="2025-10-01")                     # consorcio: 50% = 300.001
    nota(c, 123_457, centro="9.001.001", emissao="2025-11-01", titulos=PAGO(111_111))     # paga: fora
    velha = medir(c, ids["propria"], 1, "2024-11", "protocolada", 50_000, protocolo="2025-01-10")
    nota(c, 50_000, [velha])
    mid = medir(c, ids["propria"], 4, "2026-05", "protocolada", 250_001, aprovado=250_001, protocolo="2026-06-01")
    r = a_receber.a_receber(c, HOJE)
    _confere_com_o_fechamento(r, fechamento.fechamento(c, HOJE))
    [g] = r["contratantes"]                                    # as duas obras sao da Secretaria X
    assert (g["contratante"], g["em_aberto_centavos"], [e["medicao_id"] for e in g["linhas"]]) == ("Secretaria X", 250_001, [mid])
    assert [(n["numero"], n["valor_centavos"]) for n in g["notas_sem_medicao"]] == [(k, 300_001), (a, 400_001)]
    assert g["notas_sem_medicao_centavos"] == r["notas_sem_medicao_centavos"] == 700_002
    assert g["anteriores"] == r["anteriores"] == {"quantidade": 1, "valor_centavos": 50_000}
    assert r["em_aberto_centavos"] == 250_001                  # nem a nota solta nem o anterior entram


def test_nota_ligada_a_medicao_ainda_nao_enviada_ganha_a_marca_e_o_total_nao_muda(cenario):
    """Decisao do dono de 19/11/2026: a nota sem medicao que esta' ligada a medicao prevista (ou com a planilha/carta so'
    gerada) leva a marca "ligada a medicao ainda nao enviada". So' a marca: a lista, o subtotal a' parte, o total e os
    numeros do Fechamento sao os mesmos de antes do vinculo."""
    c, ids = cenario
    prevista = medir(c, ids["propria"], 5, "2026-09", "prevista", 0)
    gerada = medir(c, ids["propria"], 6, "2026-10", "planilha_gerada", 0)
    cancelada = medir(c, ids["propria"], 7, "2026-08", "cancelada", 0)
    p = nota(c, 210_001, centro="9.001.001", emissao="2026-09-15")
    g_ = nota(c, 320_003, centro="9.001.001", emissao="2026-10-15")
    x = nota(c, 130_005, centro="9.001.001", emissao="2026-08-15")
    solta = nota(c, 40_007, centro="9.001.001", emissao="2026-07-15")
    mid = medir(c, ids["propria"], 4, "2026-05", "protocolada", 250_001, aprovado=250_001, protocolo="2026-06-01")
    nota(c, 250_001, [mid])
    antes = a_receber.a_receber(c, HOJE)
    f_antes = fechamento.fechamento(c, HOJE)
    assert all(not n[SO_DA_NOTA_SOLTA] for n in antes["notas_sem_medicao"])
    # o vinculo com as medicoes que ainda nao foram ao orgao (e com a cancelada, que nao conta)
    for numero, m in ((p, prevista), (g_, gerada), (x, cancelada)):
        nid = c.execute("SELECT id FROM notas_fiscais WHERE idmov=?", (int(numero),)).fetchone()[0]
        c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                  "VALUES (?, ?, 0, 'manual', 't')", (m, nid))
    c.commit()
    depois = a_receber.a_receber(c, HOJE)
    _confere_com_o_fechamento(depois, fechamento.fechamento(c, HOJE))
    marcas = {p: True, g_: True, x: False, solta: False}
    assert {n["numero"]: n[SO_DA_NOTA_SOLTA] for n in depois["notas_sem_medicao"]} == marcas
    [g] = depois["contratantes"]
    assert {n["numero"]: n[SO_DA_NOTA_SOLTA] for n in g["notas_sem_medicao"]} == marcas
    # o total, o subtotal a' parte e cada valor: os mesmos de antes do vinculo, aqui e no Fechamento
    def sem_as_listas(r):
        return {k: v for k, v in r.items() if k not in ("notas_sem_medicao", "contratantes")}
    assert sem_as_listas(depois) == sem_as_listas(antes)
    assert depois["em_aberto_centavos"] == antes["em_aberto_centavos"] == 250_001
    assert depois["notas_sem_medicao_centavos"] == antes["notas_sem_medicao_centavos"] == 700_016
    assert [(n["nota_id"], n["valor_centavos"]) for n in depois["notas_sem_medicao"]] == [
        (n["nota_id"], n["valor_centavos"]) for n in antes["notas_sem_medicao"]]
    assert (g["em_aberto_centavos"], g["notas_sem_medicao_centavos"]) == (250_001, 700_016)
    assert fechamento.fechamento(c, HOJE) == f_antes


def test_contratante_sem_nada_em_aberto_fica_na_fileira_e_o_de_contrato_encerrado_sai(contratantes):
    c, ids = contratantes
    r = a_receber.a_receber(c, HOJE)
    assert [(g["contratante"], g["quantidade"], g["em_aberto_centavos"], g["linhas"]) for g in r["contratantes"]] == [
        ("Companhia Y", 0, 0, []), ("Secretaria X", 0, 0, []), ("SINFRA", 0, 0, [])]
    assert (r["em_aberto_centavos"], r["quantidade"]) == (0, 0)
    c.execute("UPDATE contratos SET estado='encerrado' WHERE id=?", (ids["Galpão"],)); c.commit()
    assert "Companhia Y" not in {g["contratante"] for g in a_receber.a_receber(c, HOJE)["contratantes"]}
    # encerrado e com nota em aberto: continua, pelo que deve
    m = medir(c, ids["Galpão"], 1, "2026-06", "protocolada", 90_001, aprovado=90_001, protocolo="2026-07-01")
    nota(c, 90_001, [m])
    g = _grupo(a_receber.a_receber(c, HOJE), "Companhia Y")
    assert (g["quantidade"], g["em_aberto_centavos"]) == (1, 90_001)


def test_sem_o_total_a_receber_liberado_nada_do_em_aberto_sai(contratantes):
    """A trava do total a receber (a do Fechamento, do Inicio e da lista de Obras): nem valor, nem linha, nem contagem."""
    c, ids = contratantes
    _lancar_dois_anos(c, ids)
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'", (json.dumps({"total_a_receber_liberado": False}),))
    c.commit()
    r = a_receber.a_receber(c, HOJE)
    assert r == {"anos": ["2025", "2026"], "total_a_receber_liberado": False}


def _por_par(r):
    return {(g["contratante"], g["chave"]): (g["quantidade"], g["em_aberto_centavos"]) for g in r["contratantes"]}


@pytest.mark.parametrize("sem_orgao_primeiro", [True, False])
def test_obra_sem_orgao_com_o_texto_de_uma_sigla_fica_no_grupo_dela_nas_duas_ordens(contratantes, sem_orgao_primeiro):
    """Issue #864: o contrato sem orgao no cadastro cujo texto e' a sigla de um contratante ("SINFRA") fica no grupo
    dele, sem chave, como na aba "Por contratante" do Fechamento, em qualquer ordem de chegada das medicoes. O grupo da
    SINFRA de verdade continua com a chave (o link e o filtro `?contratante=`, a pagina do contratante), o subtotal de
    cada grupo e' o da linha do Fechamento com o mesmo par, e o total e' a soma dos dois, a mesma de antes."""
    c, ids = contratantes
    c.execute("UPDATE contratos SET orgao_id=NULL, orgao='SINFRA' WHERE id=?", (ids["Galpão"],))
    c.commit()
    primeira, segunda = ("Galpão", "Estrada") if sem_orgao_primeiro else ("Estrada", "Galpão")
    m1 = medir(c, ids[primeira], 1, "2026-03", "protocolada", 50_001, aprovado=50_001, protocolo="2026-04-01")
    nota(c, 50_001, [m1], emissao="2026-03-25")
    m2 = medir(c, ids[segunda], 1, "2026-04", "protocolada", 70_003, aprovado=70_003, protocolo="2026-05-04")
    nota(c, 70_003, [m2], emissao="2026-04-27")
    r = a_receber.a_receber(c, HOJE)
    f = fechamento.fechamento(c, HOJE)
    _confere_com_o_fechamento(r, f)
    sem_orgao, sinfra = (50_001, 70_003) if sem_orgao_primeiro else (70_003, 50_001)
    pares = _por_par(r)
    assert (pares[("SINFRA", "sinfra")], pares[("SINFRA", None)]) == ((1, sinfra), (1, sem_orgao))
    assert sum(q for _, q in pares.values()) == r["em_aberto_centavos"] == 120_004
    # a pagina do contratante acha o grupo pela chave, com o subtotal so' da SINFRA de verdade
    assert contratante.em_aberto(c, "sinfra", HOJE)["contratante"]["em_aberto_centavos"] == sinfra


def test_dois_orgaos_de_mesmo_nome_ficam_em_dois_grupos(contratantes):
    """Issue #864: dois orgaos do cadastro com o mesmo nome e chaves diferentes ("Secretaria X" e a Companhia Y
    renomeada) sao dois grupos, cada um com a sua chave e o subtotal da linha do Fechamento com o mesmo par; a soma dos
    dois e' o subtotal de antes, quando eram um grupo so'. Consorcio a 33,33% com centavo impar e nota partilhada com
    residuo (o cenario de dois anos)."""
    c, ids = contratantes
    _lancar_dois_anos(c, ids)
    antes = a_receber.a_receber(c, HOJE)
    galpao = medir(c, ids["Galpão"], 90, "2026-05", "protocolada", 90_001, aprovado=90_001, protocolo="2026-06-01")
    nota(c, 90_001, [galpao], emissao="2026-05-26")
    com_o_galpao = a_receber.a_receber(c, HOJE)
    c.execute("UPDATE orgaos SET nome='Secretaria X' WHERE chave='companhia-y'")
    c.commit()
    r = a_receber.a_receber(c, HOJE)
    _confere_com_o_fechamento(r, fechamento.fechamento(c, HOJE))
    pares = _por_par(r)
    assert pares[("Secretaria X", "orgao-x")] == _por_par(antes)[("Secretaria X", "orgao-x")] == (3, 234_992)
    assert pares[("Secretaria X", "companhia-y")] == (1, 90_001)
    # so' a divisao muda: o total, o de cada ano e a quantidade sao os de antes de renomear
    assert (r["em_aberto_centavos"], r["por_ano"], r["quantidade"]) == (
        com_o_galpao["em_aberto_centavos"], com_o_galpao["por_ano"], com_o_galpao["quantidade"]) == (
        1_434_994 + 90_001, {"2025": 0, "2026": 1_434_994 + 90_001}, 7)
    assert pares[("Secretaria X", "orgao-x")][1] + pares[("Secretaria X", "companhia-y")][1] == 234_992 + 90_001


def test_grupo_sem_orgao_nao_pega_o_prazo_do_contratante_de_mesmo_nome(contratantes):
    """Issue #864: o grupo do contrato sem orgao cujo texto e' o nome de um contratante, sem linha no total (so' na
    fileira do filtro), nao herda o prazo de pagamento do contratante de verdade: o prazo do contrato sem orgao e' o de
    "sem órgão" (`diretoria._contratante`), que aqui nao tem amostra."""
    c, ids = contratantes
    _recebidas(c, ids["Escola"], 50, [10, 20, 30, 40, 50])            # Secretaria X: prazo de 40 dias
    c.execute("UPDATE contratos SET orgao_id=NULL, orgao='Secretaria X' WHERE id=?", (ids["Galpão"],))
    c.commit()
    r = a_receber.a_receber(c, HOJE)
    prazo = {(g["contratante"], g["chave"]): g["prazo_orgao_dias"] for g in r["contratantes"]}
    assert (prazo[("Secretaria X", "orgao-x")], prazo[("Secretaria X", None)]) == (40, None)
