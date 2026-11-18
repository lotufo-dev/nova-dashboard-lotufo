"""docs/adr/0006 ("A receber antigo, a' parte"): o a receber do Inicio e da lista de Obras soma so' a competencia de
2025 em diante que o RM ainda informa; o anterior e a nota sem atualizacao do RM ficam a' parte, e a conta continua
fechando ao centavo com o Fechamento. Dados ficticios (cadastro-exemplo), centavos impares."""
import datetime
import json

from app import diretoria, fechamento, inicio
from tests.test_correcao_medicoes import _ligar, _nota, cenario  # noqa: F401

HOJE = datetime.date(2026, 11, 17)
AGORA, VELHO = "2026-11-17 12:00:00", "2026-10-03 03:00:00"        # a ultima rodada do RM e a de quem saiu da janela


def _liberar(c):
    c.execute("INSERT OR REPLACE INTO cadastro_geral (chave, valor) VALUES ('diretoria', ?)",
              (json.dumps({"total_a_receber_liberado": True}),))
    c.commit()


def _medicao(c, cid, numero, competencia, valor, estado="protocolada", protocolo=None, tipo="execucao"):
    mid = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
                    "valor_protocolado_origem, congelada) VALUES (?,?,?,?,?,?,'manual',1)",
                    (cid, numero, tipo, competencia, estado, valor)).lastrowid
    if protocolo:
        c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?,?,'manual')", (mid, protocolo))
    c.commit()
    return mid


def _cobranca(c, numero, valor, emissao, titulo, visto=AGORA):
    """Nota de cobranca ao orgao com o titulo (liquido) inteiro em aberto, vista pelo RM em `visto`."""
    nid = _nota(c, numero, valor=valor)
    c.execute("UPDATE notas_fiscais SET codtmv='2.2.01', emissao=?, ultimo_visto_em=? WHERE id=?", (emissao, visto, nid))
    c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
              "status_lan, ultimo_visto_em) VALUES (1,?,?,?,?,0,0,?)", (9000 + numero, nid, 900 + numero, titulo, visto))
    c.commit()
    return nid


def _cenario_completo(c, cid):
    """Sete pendencias, uma de cada caso; devolve o valor de cada uma."""
    _liberar(c)
    v = {}
    # 1. medicao de 2025 protocolada ha' mais de 60 dias: no total e na faixa
    v["nova_velha"] = 200_003
    _medicao(c, cid, 10, "2025-06", v["nova_velha"], protocolo="2025-07-01")
    # 2. medicao de 2026 protocolada ha' poucos dias: no total, fora da faixa
    v["nova"] = 300_001
    _medicao(c, cid, 11, "2026-09", v["nova"], protocolo="2026-11-10")
    # 3. medicao de 2024 protocolada: anterior, a' parte
    v["anterior_medicao"] = 100_001
    _medicao(c, cid, 5, "2024-11", v["anterior_medicao"], protocolo="2024-12-20")
    # 4. nota de 2024 sem medicao, titulo aberto, ainda informada pelo RM: anterior pela emissao
    v["anterior_nota"] = 50_001
    _cobranca(c, 701, 54_003, "2024-12-17", v["anterior_nota"])
    # 5. nota ligada a medicao de 2024 fechada em lote, titulo aberto: anterior pela competencia da medicao
    v["anterior_ligada"] = 70_003
    fechada = _medicao(c, cid, 4, "2024-10", 75_001, estado="recebida")
    _ligar(c, fechada, _cobranca(c, 702, 75_001, "2025-01-10", v["anterior_ligada"]), valor=75_001)
    # 6. nota de 2025 sem medicao que saiu da janela do RM: sem atualizacao
    v["sem_atualizacao_nota"] = 40_001
    _cobranca(c, 703, 43_001, "2025-03-05", v["sem_atualizacao_nota"], visto=VELHO)
    # 7. medicao de 2025 protocolada cuja unica nota saiu da janela: sem atualizacao (a baixa nao chega mais)
    v["sem_atualizacao_medicao"] = 60_001
    presa = _medicao(c, cid, 12, "2025-02", v["sem_atualizacao_medicao"], protocolo="2025-03-10")
    _ligar(c, presa, _cobranca(c, 704, 60_001, "2025-03-01", 55_003, visto=VELHO), valor=60_001)
    # e uma cobranca recente sem medicao: no total
    v["nota_recente"] = 30_003
    _cobranca(c, 705, 33_001, "2026-11-12", v["nota_recente"])
    return v


def test_a_receber_do_inicio_separa_o_anterior_e_o_sem_atualizacao(cenario):
    c, cid, uid = cenario
    v = _cenario_completo(c, cid)
    r = inicio._a_receber(c, HOJE)
    total = v["nova_velha"] + v["nova"] + v["nota_recente"]
    anterior = v["anterior_medicao"] + v["anterior_nota"] + v["anterior_ligada"]
    sem = v["sem_atualizacao_nota"] + v["sem_atualizacao_medicao"]
    assert r == {"liberado": True, "valor_centavos": total, "mais_60_centavos": v["nova_velha"],
                 "a_parte": {"ano_inicial": "2025", "valor_centavos": anterior + sem, "anterior_centavos": anterior,
                             "sem_atualizacao_centavos": sem, "sem_atualizacao_desde": "2026-10-02"}}
    # nada some: o total e o que fica a' parte somam a lista inteira
    todas = diretoria.a_receber_na_cota(c)
    assert sum(diretoria._a_receber_cota(x) for x in todas) == total + anterior + sem
    # a lista de Obras faz o mesmo, obra a obra
    no_total, a_parte = diretoria.a_receber_na_cota_por_obra(c)
    assert no_total == {cid: total}
    assert a_parte == {cid: {"anterior_centavos": anterior, "sem_atualizacao_centavos": sem}}
    assert diretoria.a_receber_por_obra(c, na_cota=True) == {cid: total}


def test_ciclo_e_previsao_do_inicio_deixam_de_fora_a_pendencia_a_parte(cenario):
    c, cid, uid = cenario
    v = _cenario_completo(c, cid)
    protocolado = next(e for e in inicio._ciclo(c, HOJE) if e["etapa"] == "protocolado")
    assert (protocolado["valor_centavos"], protocolado["quantidade"]) == (v["nova_velha"] + v["nova"], 2)
    assert sum(x["valor_centavos"] for x in inicio._previsao(c, HOJE).values()) == v["nova_velha"] + v["nova"]


def test_a_conta_com_o_fechamento_fecha_ao_centavo_dos_dois_lados(cenario):
    """docs/adr/0006: o a receber do Inicio = o em aberto do Fechamento + as cobrancas do RM que nenhuma medicao em
    aberto representa, agora em duas contas separadas: a de 2025 em diante e a que fica a' parte."""
    c, cid, uid = cenario
    v = _cenario_completo(c, cid)
    f = fechamento.fechamento(c)
    r = inicio._a_receber(c, HOJE)
    do_rm = [x for x in diretoria.a_receber_na_cota(c) if x["tipo"] == "nota"]
    rm = lambda a_parte: sum(diretoria._a_receber_cota(x) for x in do_rm if x["a_parte"] == a_parte)
    em_aberto_dos_anos = sum(f["por_ano"][a]["em_aberto_centavos"] for a in f["anos"])
    # o "anterior a 2025" do Fechamento e' o mesmo corte (uma definicao so': `diretoria.ANO_INICIAL`)
    assert fechamento.ANOS[0] == diretoria.ANO_INICIAL == "2025"
    assert f["em_aberto_anteriores"]["valor_centavos"] == v["anterior_medicao"]
    # de 2025 em diante: o Fechamento ainda conta a medicao cuja nota o RM deixou de informar; o Inicio a poe a' parte
    assert r["valor_centavos"] == em_aberto_dos_anos + rm(False) - v["sem_atualizacao_medicao"]
    # a' parte: o anterior do Fechamento, as cobrancas do RM antigas ou sem atualizacao e essa medicao
    assert r["a_parte"]["valor_centavos"] == (f["em_aberto_anteriores"]["valor_centavos"] + rm(True)
                                              + v["sem_atualizacao_medicao"])


def test_sem_rodada_recente_nenhuma_nota_fica_sem_atualizacao(cenario):
    """Com a sincronizacao inteira parada, todas as notas tem a mesma idade: nada muda de lugar por isso."""
    c, cid, uid = cenario
    _liberar(c)
    _cobranca(c, 703, 43_001, "2025-03-05", 40_001, visto=VELHO)
    _cobranca(c, 705, 33_001, "2026-11-12", 30_003, visto=VELHO)
    assert diretoria.sem_atualizacao_do_rm(c) == {}
    r = inicio._a_receber(c, HOJE)
    assert r["valor_centavos"] == 70_004 and r["a_parte"]["valor_centavos"] == 0
    assert r["a_parte"]["sem_atualizacao_desde"] is None


def test_medicao_com_uma_nota_ainda_informada_pelo_rm_continua_no_total(cenario):
    c, cid, uid = cenario
    _liberar(c)
    mid = _medicao(c, cid, 12, "2025-02", 100_004, protocolo="2025-03-10")
    _ligar(c, mid, _cobranca(c, 704, 60_001, "2025-03-01", 55_003, visto=VELHO), valor=60_001)
    _ligar(c, mid, _cobranca(c, 706, 40_003, "2026-11-01", 37_001), valor=40_003)
    r = inicio._a_receber(c, HOJE)
    assert r["valor_centavos"] == 100_004 and r["a_parte"]["valor_centavos"] == 0


def test_sem_o_total_liberado_o_que_fica_a_parte_tambem_nao_sai(cenario):
    c, cid, uid = cenario
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'", (json.dumps({"total_a_receber_liberado": False}),))
    _medicao(c, cid, 5, "2024-11", 100_001, protocolo="2024-12-20")
    assert inicio._a_receber(c, HOJE) == {"liberado": False, "valor_centavos": None, "mais_60_centavos": None,
                                          "a_parte": None}
    assert diretoria.a_receber_na_cota_por_obra(c) is None
