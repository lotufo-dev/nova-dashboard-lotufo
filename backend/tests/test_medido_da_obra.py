"""Issue #742 (decisao do dono de 16/11/2026, #670; docs/adr/0011): o medido da obra soma execucao e projeto; o
reajuste fica fora; cancelada, desistida, prevista e planilha gerada nao contam. Cada numero que parte do medido
(saldo, lista de Obras, topo e ritmo da pagina da obra) segue a regra; a curva S continua so' com a execucao.

Dado sintetico: contrato de 1.000.000,01 com cota de 49% (rateio com residuo) e valores de centavo impar."""
import datetime

import pytest
from app import api_contratos, auth, contratos, db, ficha_obra, paineis, prazos

HOJE = datetime.date(2026, 9, 24)          # janela do ritmo: 03/2026 a 08/2026
VIGENTE = 1_000_000_01
COTA_BP = 4900


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "U", "u@exemplo.com.br", "senha-forte-123", "engenharia")
    yield c
    c.close()


@pytest.fixture
def cid(conn):
    return contratos.criar(conn, 1, {"orgao": "Órgão Fictício", "numero_instrumento": "CT 001/2026", "objeto": "Obra X",
                                     "valor_original_centavos": VIGENTE, "percentual_direito_bp": COTA_BP,
                                     "data_base": "2025-08-01", "execucao_inicio": "2025-09-01",
                                     "execucao_fim": "2027-06-30", "vigencia_fim": "2027-09-30"})


def _m(conn, cid, numero, tipo, comp, estado, pedido, aprovado=None):
    conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
                 "valor_atestado_centavos) VALUES (?,?,?,?,?,?,?)", (cid, numero, tipo, comp, estado, pedido, aprovado))
    conn.commit()


def _execucao(conn, cid):
    """Execucao: 250.000,03 aprovado (pedido 300.000,01) e 100.000,00 so' pedido (planilha enviada)."""
    _m(conn, cid, 1, "execucao", "2026-07", "protocolada", 300_000_01, 250_000_03)
    _m(conn, cid, 2, "execucao", "2026-08", "planilha_enviada", 100_000_00)


def _numeros(conn, cid) -> dict:
    s = paineis.saldo(conn, cid)
    lista = {o["id"]: o for o in api_contratos.listar(usuario={}, conn=conn)}[cid]
    ficha = ficha_obra.da_obra(conn, cid, HOJE)
    sug = prazos.sugestao_dias(conn, cid, HOJE)
    return {"medido": s["medido_centavos"], "saldo": s["saldo_centavos"],
            "lista_medido": lista["medido_centavos"], "lista_saldo": lista["saldo_centavos"],
            "lista_posicao": {k: lista["posicao"][k] for k in ("vigente_centavos", "medido_centavos", "saldo_centavos")},
            "topo": {k: ficha["topo"][k] for k in ("vigente_centavos", "medido_centavos", "saldo_centavos")},
            "ritmo": sug["ritmo_centavos"], "medido_periodo": sug["medido_periodo_centavos"],
            "saldo_sugestao": sug["saldo_centavos"], "por_contrato": paineis.medido_por_contrato(conn).get(cid, 0)}


def _esperado(medido_cheio: int, medido_janela: int, ritmo: int) -> dict:
    vig_cota = contratos.cota(VIGENTE, COTA_BP)
    med_cota = contratos.cota(medido_cheio, COTA_BP)
    posicao = {"vigente_centavos": vig_cota, "medido_centavos": med_cota, "saldo_centavos": vig_cota - med_cota}
    return {"medido": medido_cheio, "saldo": VIGENTE - medido_cheio, "lista_medido": medido_cheio,
            "lista_saldo": VIGENTE - medido_cheio, "lista_posicao": posicao, "topo": posicao, "ritmo": ritmo,
            "medido_periodo": medido_janela, "saldo_sugestao": VIGENTE - medido_cheio, "por_contrato": medido_cheio}


# Obra so' com execucao: os numeros de antes da #742, escritos a mao. 250.000,03 + 100.000,00 = 350.000,03;
# na cota: 49.000.000,49 -> 49.000.000 e 17.150.001,47 -> 17.150.001; ritmo 35.000.003 / 6 = 5.833.333,83 -> 5.833.334.
ANTES_SO_EXECUCAO = {"medido": 350_000_03, "saldo": 649_999_98, "lista_medido": 350_000_03, "lista_saldo": 649_999_98,
                     "lista_posicao": {"vigente_centavos": 490_000_00, "medido_centavos": 171_500_01,
                                       "saldo_centavos": 318_499_99},
                     "topo": {"vigente_centavos": 490_000_00, "medido_centavos": 171_500_01,
                              "saldo_centavos": 318_499_99},
                     "ritmo": 58_333_34, "medido_periodo": 350_000_03, "saldo_sugestao": 649_999_98,
                     "por_contrato": 350_000_03}


def test_obra_so_com_execucao_nada_muda(conn, cid):
    _execucao(conn, cid)
    _m(conn, cid, 1, "reajuste", "2026-07", "protocolada", 20_000_01)       # reajuste: fora, como sempre
    assert _numeros(conn, cid) == ANTES_SO_EXECUCAO
    # a regra de antes, recalculada da serie de execucao da curva: o medido e' o mesmo
    assert sum(p["medido_execucao_centavos"] for p in paineis.curva(conn, cid)) == ANTES_SO_EXECUCAO["medido"]


def test_projeto_cancelado_desistido_ou_nao_enviado_nao_conta(conn, cid):
    _execucao(conn, cid)
    for numero, estado in ((1, "cancelada"), (2, "desistida"), (3, "prevista"), (4, "planilha_gerada")):
        _m(conn, cid, numero, "projeto", "2026-06", estado, 77_777_77, 77_777_77 if estado == "cancelada" else None)
    assert _numeros(conn, cid) == ANTES_SO_EXECUCAO


def test_obra_so_com_projeto_tem_medido_e_saldo(conn, cid):
    # antes da #742 esta obra aparecia com medido zero e saldo igual ao contrato inteiro
    _m(conn, cid, 1, "projeto", "2026-05", "recebida", 200_000_01, 199_999_99)
    _m(conn, cid, 2, "projeto", "2026-06", "planilha_enviada", 50_000_00)
    medido = 199_999_99 + 50_000_00
    assert _numeros(conn, cid) == _esperado(medido, medido, 41_666_67)     # 24.999.999 / 6 = 4.166.666,5 -> meio para cima
    assert _numeros(conn, cid)["saldo"] == 750_000_02
    # a curva S compara o realizado de execucao com o cronograma: o projeto nao entra nela
    assert all(p["medido_centavos"] is None for p in paineis.curva_s(conn, cid))


def test_obra_com_execucao_projeto_e_reajuste(conn, cid):
    _execucao(conn, cid)
    _m(conn, cid, 1, "projeto", "2026-02", "nota_emitida", 120_000_01)     # fora da janela do ritmo
    _m(conn, cid, 2, "projeto", "2026-08", "boletim_recebido", 30_000_00, 29_999_97)
    _m(conn, cid, 1, "reajuste", "2026-07", "protocolada", 20_000_01, 20_000_01)
    _m(conn, cid, 2, "reajuste", "2026-08", "recebida", 9_999_99)
    medido = 350_000_03 + 120_000_01 + 29_999_97                      # 500.000,01; reajuste fora
    janela = 350_000_03 + 29_999_97                                   # 380.000,00
    assert _numeros(conn, cid) == _esperado(medido, janela, 63_333_33)    # 38.000.000 / 6 = 6.333.333,33
    assert _numeros(conn, cid)["saldo"] == 500_000_00
    # o reajuste contratado continua a parte e a serie de reajuste continua propria
    s = paineis.saldo(conn, cid)
    assert s["vigente_execucao_centavos"] - s["medido_centavos"] == s["saldo_centavos"]
    pontos = {p["competencia"]: p for p in paineis.curva(conn, cid)}
    assert pontos["2026-08"]["medido_projeto_centavos"] == 29_999_97
    assert pontos["2026-08"]["medido_reajuste_centavos"] == 9_999_99
    # a curva S segue so' com a execucao: o acumulado final e' o medido de execucao
    assert [p["medido_centavos"] for p in paineis.curva_s(conn, cid)][-1] == 350_000_03


def test_lista_de_obras_e_saldo_da_obra_na_mesma_conta(conn, cid):
    _execucao(conn, cid)
    _m(conn, cid, 1, "projeto", "2026-04", "espelho_enviado", 10_000_01, 10_000_01)
    outro = contratos.criar(conn, 1, {"orgao": "Órgão Fictício", "numero_instrumento": "CT 002/2026", "objeto": "Y",
                                      "valor_original_centavos": 5_000_00, "data_base": "2025-08-01"})
    _m(conn, outro, 1, "projeto", "2026-04", "protocolada", 1)
    lista = {o["id"]: o for o in api_contratos.listar(usuario={}, conn=conn)}
    for i in (cid, outro):
        s = paineis.saldo(conn, i)
        assert (lista[i]["medido_centavos"], lista[i]["saldo_centavos"]) == (s["medido_centavos"], s["saldo_centavos"])
    assert lista[outro]["saldo_centavos"] == 4_999_99       # 5.000,00 - 0,01 de projeto
    assert paineis.mede_no_medido({"tipo": "projeto", "estado": "recebida"})
    assert not paineis.mede_no_medido({"tipo": "reajuste", "estado": "recebida"})
    assert not paineis.mede_no_medido({"tipo": "projeto", "estado": "cancelada"})
