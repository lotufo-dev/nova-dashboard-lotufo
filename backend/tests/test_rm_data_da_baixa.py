"""Issue #842 (decisao do dono de 22/11/2026): a medicao recebida SEM a data do recebimento, com nota ligada e todos
os titulos dessas notas baixados no RM, ganha a data da ultima baixa (`sincronizacao_rm.datar_recebidas`). Ao lado de
`test_rm.py`, com o mesmo simulador. Dados ficticios, centavos impares.

O caso de todos os testes: a medicao do legado que o corte de 22/09/2026 fechou sem data (`conciliacao.cortar`) e
que ganhou a nota depois, pela correcao de cadastro (aqui, `_ligar`: o mesmo `alocar` com `aceita_recebida`)."""
import datetime
import json

import pytest

from app import cli, conciliacao, db, diretoria, medicoes, resumo_medicoes, sincronizacao_rm
from tests.test_conciliacao import _par_absorvido
from tests.test_rm import _baixa, _medicao, _nf, _simulador, cid, conn  # noqa: F401  (conn e cid sao fixtures)

CORTE = "2026-09-22"
EMISSAO = "2025-04-10T00:00:00-04:00"
MAIO, JUNHO, JULHO = ("2025-05-02T00:00:00-04:00", "2025-06-17T00:00:00-04:00", "2025-07-30T00:00:00-04:00")


def _fechada_pelo_corte(conn, cid, numero, valor, comp="2025-03", tipo="execucao"):
    mid = _medicao(conn, cid, numero, valor, comp=comp, tipo=tipo)
    conciliacao.cortar(conn, 1, CORTE, ensaio=False)
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "recebida" and m["recebida_em"] is None
    return mid


def _rodada(conn, tmp_path, nfs, baixas):
    return sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, nfs, baixas))


def _ligar(conn, mid, *idmovs):
    """A nota que a correcao de cadastro liga a' medicao ja' recebida: o estado fica (docs/adr/0006)."""
    for idmov in idmovs:
        nid = conn.execute("SELECT id FROM notas_fiscais WHERE idmov=?", (idmov,)).fetchone()[0]
        sincronizacao_rm.alocar(conn, 1, nid, mid, "manual", None, "correcao_cadastro", aceita_recebida=True)


def _recebida_em(conn, mid):
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "recebida"
    return m["recebida_em"]


def _eventos(conn, mid=None):
    filtro, par = (" AND entidade_id=?", (str(mid),)) if mid is not None else ("", ())
    return [(r["usuario_id"], json.loads(r["depois"])) for r in conn.execute(
        "SELECT usuario_id, depois FROM audit_log WHERE acao='medicao.recebida_em'" + filtro + " ORDER BY id", par)]


# ------------------------------------------------------------------ a regra

def test_baixa_unica_da_a_data_na_rodada_seguinte_ao_vinculo_e_a_segunda_rodada_nao_muda_nada(conn, cid, tmp_path):
    mid = _fechada_pelo_corte(conn, cid, 1, 500_01)
    nfs, baixas = [_nf(100, 500.01, emissao=EMISSAO)], [_baixa(1, 100, 470.01, 470.01, 1, MAIO)]
    assert _rodada(conn, tmp_path, nfs, baixas)["recebidas_datadas"] == 0     # a nota ainda nao esta' ligada
    _ligar(conn, mid, 100)
    assert _recebida_em(conn, mid) is None                  # ligar nao da' a data: quem olha e' a rodada
    assert _rodada(conn, tmp_path, nfs, baixas)["recebidas_datadas"] == 1
    assert _recebida_em(conn, mid) == "2025-05-02"
    # pelo sistema, dizendo que veio da baixa do RM e de qual nota
    nid = conn.execute("SELECT id FROM notas_fiscais WHERE idmov=100").fetchone()[0]
    assert _eventos(conn, mid) == [(None, {"recebida_em": "2025-05-02", "origem": "baixa do RM", "disparo": "rodada",
                                           "repasse": False, "notas": [nid], "titulos": 1, "com_diferenca": False})]
    # o estado nao mudou de novo: o recebimento continua sendo o do corte, e nao conta como recebimento a' mao
    assert [json.loads(r[0])["origem"] for r in conn.execute(
        "SELECT depois FROM audit_log WHERE acao='medicao.estado' AND entidade_id=? "
        "AND json_extract(depois, '$.estado')='recebida'", (str(mid),))] == ["corte"]
    assert conciliacao.recebidas_a_mao(conn) == set()
    # rodar de novo nao muda nada
    antes = conn.execute("SELECT COUNT(*) FROM audit_log WHERE entidade='medicao'").fetchone()[0]
    assert _rodada(conn, tmp_path, nfs, baixas)["recebidas_datadas"] == 0
    assert sincronizacao_rm.datar_recebidas(conn) == {"ensaio": False, "datadas": 0, "linhas": []}
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE entidade='medicao'").fetchone()[0] == antes
    assert _recebida_em(conn, mid) == "2025-05-02"


def test_pago_em_parcelas_leva_a_ultima_baixa(conn, cid, tmp_path):
    """Uma nota em dois titulos e outra medicao em duas notas: a data e' a da ultima baixa do conjunto."""
    em_titulos = _fechada_pelo_corte(conn, cid, 1, 1_000_01)
    em_notas = _fechada_pelo_corte(conn, cid, 2, 900_03)
    nfs = [_nf(100, 1000.01, emissao=EMISSAO), _nf(200, 600.02, emissao=EMISSAO), _nf(201, 300.01, emissao=EMISSAO)]
    baixas = [_baixa(1, 100, 470.01, 470.01, 1, JUNHO), _baixa(2, 100, 470.0, 470.0, 1, MAIO),
              _baixa(3, 200, 564.02, 564.02, 1, MAIO), _baixa(4, 201, 282.01, 282.01, 1, JULHO)]
    _rodada(conn, tmp_path, nfs, baixas)
    _ligar(conn, em_titulos, 100)
    _ligar(conn, em_notas, 200, 201)
    rel = sincronizacao_rm.datar_recebidas(conn)
    assert rel["datadas"] == 2
    assert (_recebida_em(conn, em_titulos), _recebida_em(conn, em_notas)) == ("2025-06-17", "2025-07-30")
    assert [(x["medicao_id"], x["recebida_em"], x["notas"], x["titulos"]) for x in rel["linhas"]] == [
        (em_titulos, "2025-06-17", 1, 2), (em_notas, "2025-07-30", 2, 2)]


def test_titulo_ainda_aberto_nao_preenche_e_a_baixa_que_chega_depois_preenche(conn, cid, tmp_path):
    mid = _fechada_pelo_corte(conn, cid, 1, 1_000_01)
    nfs = [_nf(100, 1000.01, emissao=EMISSAO)]
    aberto = [_baixa(1, 100, 470.01, 470.01, 1, MAIO), _baixa(2, 100, 470.0, 0.0, 0)]
    _rodada(conn, tmp_path, nfs, aberto)
    _ligar(conn, mid, 100)
    assert _rodada(conn, tmp_path, nfs, aberto)["recebidas_datadas"] == 0
    assert _recebida_em(conn, mid) is None and _eventos(conn) == []
    pago = [aberto[0], _baixa(2, 100, 470.0, 470.0, 1, JULHO)]
    assert _rodada(conn, tmp_path, nfs, pago)["recebidas_datadas"] == 1
    assert _recebida_em(conn, mid) == "2025-07-30"


@pytest.mark.parametrize("baixado,data", [(469.01, "2025-05-02"),     # falta R$ 1,00: dentro da tolerancia (#35)
                                          (469.0, None)])            # falta R$ 1,01: o titulo nao esta' baixado
def test_titulo_baixado_em_parte_so_conta_dentro_da_tolerancia(conn, cid, tmp_path, baixado, data):
    mid = _fechada_pelo_corte(conn, cid, 1, 500_01)
    _rodada(conn, tmp_path, [_nf(100, 500.01, emissao=EMISSAO)], [_baixa(1, 100, 470.01, baixado, 4, MAIO)])
    _ligar(conn, mid, 100)
    assert sincronizacao_rm.datar_recebidas(conn)["datadas"] == (1 if data else 0)
    assert _recebida_em(conn, mid) == data


def test_medicao_sem_nota_ligada_fica_sem_data_e_sem_aviso(conn, cid, tmp_path):
    """Decisao do dono de 22/11/2026: nao se poe data sem documento, e a medicao sem nota nao vira pendencia."""
    from app import notas
    mid = _fechada_pelo_corte(conn, cid, 1, 500_01)
    avisos_antes = notas.avisos(conn)
    # a nota existe no RM, paga, com o valor da medicao: sem vinculo, nao e' documento dela
    r = _rodada(conn, tmp_path, [_nf(100, 500.01, emissao=EMISSAO)], [_baixa(1, 100, 470.01, 470.01, 1, MAIO)])
    assert r["recebidas_datadas"] == 0
    assert sincronizacao_rm.datar_recebidas(conn) == {"ensaio": False, "datadas": 0, "linhas": []}
    assert _recebida_em(conn, mid) is None and _eventos(conn) == []
    assert [a for a in notas.avisos(conn) if a["medicao_id"] == mid] == [a for a in avisos_antes if a["medicao_id"] == mid] == []


def test_titulo_baixado_por_valor_menor_entra_com_a_data_e_continua_na_reconciliacao(conn, cid, tmp_path):
    """docs/adr/0006: o titulo que o RM deu como baixado por valor menor nao tem falta. A medicao ganha a data da
    baixa, e a diferenca continua a' vista no grupo da reconciliacao."""
    mid = _fechada_pelo_corte(conn, cid, 1, 500_01)
    _rodada(conn, tmp_path, [_nf(100, 500.01, emissao=EMISSAO)], [_baixa(1, 100, 470.01, 420.0, 1, MAIO)])
    _ligar(conn, mid, 100)
    grupo = lambda: [(x["medicao_id"], x["diferenca_centavos"], x["data_baixa"])
                     for x in sincronizacao_rm.reconciliacao(conn)["baixados_com_diferenca"]]
    assert grupo() == [(mid, 50_01, "2025-05-02")]
    rel = sincronizacao_rm.datar_recebidas(conn)
    assert [(x["medicao_id"], x["recebida_em"], x["com_diferenca"]) for x in rel["linhas"]] == [(mid, "2025-05-02", True)]
    assert _recebida_em(conn, mid) == "2025-05-02"
    assert _eventos(conn, mid)[0][1]["com_diferenca"] is True
    assert grupo() == [(mid, 50_01, "2025-05-02")]


def test_baixa_total_sem_valor_nao_e_recebimento_e_nao_da_a_data(conn, cid, tmp_path):
    """docs/adr/0006: a baixa total SEM valor (glosa, compensacao, encontro de contas) nao e' recebimento; a data
    dela nao e' a de um pagamento."""
    mid = _fechada_pelo_corte(conn, cid, 1, 500_01)
    _rodada(conn, tmp_path, [_nf(100, 500.01, emissao=EMISSAO)], [_baixa(1, 100, 470.01, 0.0, 1, MAIO)])
    _ligar(conn, mid, 100)
    assert sincronizacao_rm.datar_recebidas(conn)["datadas"] == 0
    assert _recebida_em(conn, mid) is None


def test_nota_sem_titulo_cancelada_ou_com_vinculo_desfeito_nao_da_a_data(conn, cid, tmp_path):
    sem_titulo = _fechada_pelo_corte(conn, cid, 1, 500_01)
    com_cancelada = _fechada_pelo_corte(conn, cid, 2, 900_03)
    desfeito = _fechada_pelo_corte(conn, cid, 3, 700_07)
    nfs = [_nf(100, 500.01, emissao=EMISSAO), _nf(200, 600.02, emissao=EMISSAO), _nf(201, 300.01, emissao=EMISSAO),
           _nf(300, 700.07, emissao=EMISSAO)]
    baixas = [_baixa(3, 200, 564.02, 564.02, 1, MAIO), _baixa(4, 201, 282.01, 282.01, 1, JUNHO),
              _baixa(5, 300, 658.07, 658.07, 1, MAIO)]
    _rodada(conn, tmp_path, nfs, baixas)
    _ligar(conn, sem_titulo, 100)
    _ligar(conn, com_cancelada, 200, 201)
    _ligar(conn, desfeito, 300)
    # uma das duas notas fica cancelada com o vinculo ainda vigente (a rodada o desfaz; aqui, antes dela)
    conn.execute("UPDATE notas_fiscais SET situacao='cancelada' WHERE idmov=201")
    conn.execute("UPDATE nf_alocacoes SET desfeita_em=datetime('now'), motivo_desfazer='teste' WHERE medicao_id=?", (desfeito,))
    conn.commit()
    assert sincronizacao_rm.datar_recebidas(conn)["datadas"] == 0
    assert [_recebida_em(conn, m) for m in (sem_titulo, com_cancelada, desfeito)] == [None, None, None]


def test_nota_cancelada_no_rm_segura_a_data_ate_outra_nota_ser_ligada(conn, cid, tmp_path):
    """Revisao da PR: a rodada desfaz o vinculo da nota cancelada ANTES de olhar a data. Sem a guarda, a medicao
    faturada em duas notas ganhava a data da que sobrou, e a substituta, ligada e paga depois, nao a movia."""
    mid = _fechada_pelo_corte(conn, cid, 2, 900_03)
    nfs = [_nf(200, 600.02, emissao=EMISSAO), _nf(201, 300.01, emissao=EMISSAO)]
    baixas = [_baixa(3, 200, 564.02, 564.02, 1, MAIO), _baixa(4, 201, 282.01, 0.0, 0)]
    _rodada(conn, tmp_path, nfs, baixas)
    _ligar(conn, mid, 200, 201)
    assert _rodada(conn, tmp_path, nfs, baixas)["recebidas_datadas"] == 0          # a segunda nota esta' em aberto
    cancelada = [nfs[0], _nf(201, 300.01, emissao=EMISSAO, status="C")]
    assert _rodada(conn, tmp_path, cancelada, baixas)["recebidas_datadas"] == 0
    assert [n["idmov"] for n in medicoes.detalhe(conn, mid)["notas"]] == [200]      # o vinculo da cancelada saiu
    assert _recebida_em(conn, mid) is None
    # a nota refeita entra, e' ligada e paga: a data e' a da ultima baixa do conjunto
    refeita = cancelada + [_nf(202, 300.01, emissao=EMISSAO)]
    pagas = baixas + [_baixa(5, 202, 282.01, 282.01, 1, JULHO)]
    _rodada(conn, tmp_path, refeita, pagas)
    _ligar(conn, mid, 202)
    assert _rodada(conn, tmp_path, refeita, pagas)["recebidas_datadas"] == 1
    assert _recebida_em(conn, mid) == "2025-07-30"


@pytest.mark.parametrize("baixa_em,marco", [
    ("2025-02-03T00:00:00-04:00", None),                  # antes da emissao da propria nota (10/04/2025)
    ("2025-05-02T00:00:00-04:00", "nf_emitida_em"),       # antes da emissao gravada na medicao
    ("2025-05-02T00:00:00-04:00", "nota_emitida_em"),
    ("2027-06-10T00:00:00-04:00", None)])                 # depois de hoje: ano digitado errado no RM
def test_baixa_fora_da_ordem_dos_marcos_ou_no_futuro_nao_da_a_data(conn, cid, tmp_path, monkeypatch, baixa_em, marco):
    """Revisao da PR: a ordem que `medicoes.mudar_estado` exige de quem registra o recebimento vale aqui, sem
    excecao (a rodada segue): a data so' nao entra."""
    from app import rm, tempo
    monkeypatch.setattr(tempo, "hoje_local", lambda: datetime.date(2026, 11, 22))
    monkeypatch.setattr(rm, "data", lambda v, hoje=None: v[:10] if v else None)      # o RM devolveu a data como esta'
    mid = _fechada_pelo_corte(conn, cid, 1, 500_01)
    if marco:
        conn.execute(f"UPDATE medicoes SET {marco}='2025-06-01' WHERE id=?", (mid,))
        conn.commit()
    nfs, baixas = [_nf(100, 500.01, emissao=EMISSAO)], [_baixa(1, 100, 470.01, 470.01, 1, baixa_em)]
    _rodada(conn, tmp_path, nfs, baixas)
    _ligar(conn, mid, 100)
    r = _rodada(conn, tmp_path, nfs, baixas)
    assert (r["estado"], r["recebidas_datadas"]) == ("success", 0)
    assert _recebida_em(conn, mid) is None and _eventos(conn) == []


def test_titulo_cancelado_e_titulo_excluido_no_rm_ficam_fora_e_titulo_sem_data_segura(conn, cid, tmp_path):
    com_fora = _fechada_pelo_corte(conn, cid, 1, 500_01)
    sem_data = _fechada_pelo_corte(conn, cid, 2, 700_07)
    nfs = [_nf(100, 500.01, emissao=EMISSAO), _nf(200, 700.07, emissao=EMISSAO)]
    baixas = [_baixa(1, 100, 470.01, 470.01, 1, MAIO),
              _baixa(2, 100, 470.01, 0.0, 2),                       # titulo cancelado: nao e' devido
              _baixa(3, 100, 470.01, 470.01, 1, JULHO),              # sera' marcado como excluido no RM
              _baixa(4, 200, 329.03, 329.03, 1, MAIO), _baixa(5, 200, 329.04, 329.04, 1)]    # baixado sem a data
    _rodada(conn, tmp_path, nfs, baixas)
    conn.execute("UPDATE baixas SET excluida_rm_em='2026-11-01 10:00:00' WHERE idlan=3")
    conn.commit()
    _ligar(conn, com_fora, 100)
    _ligar(conn, sem_data, 200)
    rel = sincronizacao_rm.datar_recebidas(conn)
    assert [(x["medicao_id"], x["recebida_em"], x["titulos"]) for x in rel["linhas"]] == [(com_fora, "2025-05-02", 1)]
    assert _recebida_em(conn, sem_data) is None


def test_nota_partilhada_da_a_mesma_data_as_duas_medicoes(conn, cid, tmp_path):
    """docs/adr/0005: uma nota em duas medicoes, cada uma com a sua parte; os titulos sao os da nota."""
    a = _fechada_pelo_corte(conn, cid, 1, 300_01)
    b = _fechada_pelo_corte(conn, cid, 2, 200_02)
    _rodada(conn, tmp_path, [_nf(100, 500.03, emissao=EMISSAO)], [_baixa(1, 100, 470.03, 470.03, 1, MAIO)])
    nid = conn.execute("SELECT id FROM notas_fiscais WHERE idmov=100").fetchone()[0]
    for mid, parte in ((a, 300_01), (b, 200_02)):
        sincronizacao_rm.alocar(conn, 1, nid, mid, "manual", None, "correcao_cadastro", aceita_recebida=True,
                                valor_da_parte=parte)
    assert sincronizacao_rm.datar_recebidas(conn)["datadas"] == 2
    assert (_recebida_em(conn, a), _recebida_em(conn, b)) == ("2025-05-02", "2025-05-02")


def test_diferenca_que_a_reconciliacao_nao_mostra_nao_e_anunciada(conn, cid, tmp_path):
    """Revisao da PR: o aviso do comando segue a lista da reconciliacao (por titulo, acima de R$ 1,00), nao outra
    conta. Dois titulos com R$ 0,60 a menos cada um nao estao la'."""
    mid = _fechada_pelo_corte(conn, cid, 1, 1_000_01)
    _rodada(conn, tmp_path, [_nf(100, 1000.01, emissao=EMISSAO)],
            [_baixa(1, 100, 470.01, 469.41, 1, MAIO), _baixa(2, 100, 470.0, 469.4, 1, JUNHO)])
    _ligar(conn, mid, 100)
    assert sincronizacao_rm.reconciliacao(conn)["baixados_com_diferenca"] == []
    rel = sincronizacao_rm.datar_recebidas(conn)
    assert [(x["recebida_em"], x["com_diferenca"]) for x in rel["linhas"]] == [("2025-06-17", False)]


def test_falha_na_data_nao_derruba_a_rodada(conn, cid, tmp_path, monkeypatch):
    """Revisao da PR: o passo da data nao pode custar as notas, as baixas e os recebimentos da rodada."""
    mid = _fechada_pelo_corte(conn, cid, 1, 500_01)
    nfs, baixas = [_nf(100, 500.01, emissao=EMISSAO)], [_baixa(1, 100, 470.01, 470.01, 1, MAIO)]
    _rodada(conn, tmp_path, nfs, baixas)
    _ligar(conn, mid, 100)

    def quebra(*a, **k):
        raise RuntimeError("defeito de exemplo")
    monkeypatch.setattr(sincronizacao_rm, "_ultima_baixa", quebra)
    r = _rodada(conn, tmp_path, nfs + [_nf(101, 77.07, emissao=EMISSAO)], baixas)
    assert (r["estado"], r["nfs"], r["recebidas_datadas"], r["recebidas_datadas_erro"]) == (
        "success", 2, 0, "defeito de exemplo")
    assert conn.execute("SELECT COUNT(*) FROM notas_fiscais WHERE idmov=101").fetchone()[0] == 1
    assert _recebida_em(conn, mid) is None
    monkeypatch.undo()
    assert _rodada(conn, tmp_path, nfs, baixas)["recebidas_datadas"] == 1           # a rodada seguinte tenta de novo


def test_data_ja_gravada_nunca_e_trocada_e_medicao_que_nao_esta_recebida_nao_entra(conn, cid, tmp_path):
    a_mao = _medicao(conn, cid, 1, 500_01, comp="2025-03")
    medicoes.mudar_estado(conn, 1, a_mao, "recebida", "pago por fora, conferido no extrato", "2025-04-20", origem="manual")
    protocolada = _medicao(conn, cid, 2, 700_07, comp="2025-03")
    nfs = [_nf(100, 500.01, emissao=EMISSAO), _nf(200, 700.07, emissao=EMISSAO)]
    baixas = [_baixa(1, 100, 470.01, 470.01, 1, JULHO), _baixa(2, 200, 658.07, 658.07, 1, JULHO)]
    _rodada(conn, tmp_path, nfs, baixas)
    _ligar(conn, a_mao, 100)
    # a protocolada com nota paga vira recebida pela regra de sempre (`_recebimentos`, na rodada); a da data nao a toca
    sincronizacao_rm.alocar(conn, 1, conn.execute("SELECT id FROM notas_fiscais WHERE idmov=200").fetchone()[0],
                            protocolada, "manual", None, "correcao_cadastro")
    assert sincronizacao_rm.datar_recebidas(conn)["datadas"] == 0
    assert _recebida_em(conn, a_mao) == "2025-04-20"
    p = medicoes.detalhe(conn, protocolada)
    assert (p["estado"], p["recebida_em"]) == ("protocolada", None)


def test_em_consorcio_a_ultima_baixa_e_a_da_nota_da_empresa_de_outra_coligada(conn, cid, tmp_path):
    """docs/adr/0006 (#756): com a nota da empresa ligada, a ultima baixa e' a do repasse da cota. Contam as notas
    ligadas de qualquer coligada, e todas precisam estar baixadas."""
    mid = _fechada_pelo_corte(conn, cid, 1, 900_03)
    nfs = [_nf(100, 900.03, emissao=EMISSAO), _nf(500, 300.01, coligada=12, emissao=EMISSAO)]
    fatura = _baixa(1, 100, 846.03, 846.03, 1, MAIO)
    _rodada(conn, tmp_path, nfs, [fatura, _baixa(9, 500, 282.01, 0.0, 0, coligada=12)])
    _ligar(conn, mid, 100, 500)
    assert sincronizacao_rm.datar_recebidas(conn)["datadas"] == 0        # o repasse ainda nao tem baixa
    _rodada(conn, tmp_path, nfs, [fatura, _baixa(9, 500, 282.01, 282.01, 1, JULHO, coligada=12)])
    assert _recebida_em(conn, mid) == "2025-07-30"
    assert _eventos(conn, mid)[0][1]["repasse"] is True       # a data e' a do repasse, nao a do pagamento do orgao


@pytest.mark.parametrize("idmovs,repasse", [((100, 500), False),      # fatura e nota da empresa baixadas no mesmo dia
                                            ((500,), True)])          # so' a nota da empresa ligada
def test_marca_do_repasse_so_quando_a_data_nao_e_a_de_nota_da_coligada_do_contrato(conn, cid, tmp_path, idmovs, repasse):
    mid = _fechada_pelo_corte(conn, cid, 1, 900_03)
    _rodada(conn, tmp_path, [_nf(100, 900.03, emissao=EMISSAO), _nf(500, 300.01, coligada=12, emissao=EMISSAO)],
            [_baixa(1, 100, 846.03, 846.03, 1, JULHO), _baixa(9, 500, 282.01, 282.01, 1, JULHO, coligada=12)])
    _ligar(conn, mid, *idmovs)
    rel = sincronizacao_rm.datar_recebidas(conn)
    assert [(x["recebida_em"], x["repasse"]) for x in rel["linhas"]] == [("2025-07-30", repasse)]
    assert [bool(m["recebida_pelo_repasse"]) for m in diretoria._medicoes(conn) if m["id"] == mid] == [repasse]


def test_data_do_repasse_nao_e_caso_do_prazo_do_orgao(conn, cid, tmp_path):
    """docs/adr/0007: o prazo do orgao mede do protocolo ao pagamento do orgao. A medicao de consorcio datada pela
    nota da empresa leva o dia do repasse da cota, que soma a demora do consorcio: fica fora da amostra. A datada
    pela nota da coligada do contrato e' caso, como a recebida pela baixa de sempre."""
    hoje = datetime.date(2026, 11, 22)
    abril, agosto = "2026-04-07T00:00:00-04:00", "2026-08-25T00:00:00-04:00"
    emissao = "2026-04-01T00:00:00-04:00"
    diretas = [_medicao(conn, cid, n, 100_01 + n, comp="2026-03") for n in range(1, 6)]      # protocolo em 28/03/2026
    pelo_repasse = [_medicao(conn, cid, n, 300_03 + n, comp="2026-03", tipo="reajuste") for n in (1, 2)]
    conciliacao.cortar(conn, 1, CORTE, ensaio=False)
    nfs = [_nf(100 + n, 100.01 + n / 100, emissao=emissao) for n in range(1, 6)] + [
        _nf(500 + n, 100.0 + n, coligada=12, emissao=emissao) for n in (1, 2)]
    baixas = [_baixa(n, 100 + n, 94.0, 94.0, 1, abril) for n in range(1, 6)] + [
        _baixa(50 + n, 500 + n, 94.0, 94.0, 1, agosto, coligada=12) for n in (1, 2)]
    _rodada(conn, tmp_path, nfs, baixas)
    for n, mid in enumerate(diretas, start=1):
        _ligar(conn, mid, 100 + n)
    for n, mid in zip((1, 2), pelo_repasse):
        _ligar(conn, mid, 500 + n)
    rel = sincronizacao_rm.datar_recebidas(conn)
    assert sorted((x["medicao_id"], x["repasse"]) for x in rel["linhas"]) == sorted(
        [(m, False) for m in diretas] + [(m, True) for m in pelo_repasse])
    ms = diretoria._medicoes(conn)
    assert {m["id"] for m in ms if m["recebida_pelo_repasse"]} == set(pelo_repasse)
    assert diretoria.prazos_do_orgao(ms, hoje) == {"sem órgão": 10}              # 28/03 a 07/04, cinco casos
    # sem a marca, os dois repasses de 150 dias seriam o terceiro quartil
    assert diretoria.prazos_do_orgao([{**m, "recebida_pelo_repasse": 0} for m in ms], hoje) == {"sem órgão": 150}
    # a marca vale para a data que o evento gravou: recebida de novo por outro caminho, com outra data, e' caso
    conn.execute("UPDATE medicoes SET recebida_em='2026-08-26' WHERE id=?", (pelo_repasse[0],))
    conn.commit()
    assert {m["id"] for m in diretoria._medicoes(conn) if m["recebida_pelo_repasse"]} == {pelo_repasse[1]}


def test_reajuste_negativo_absorvido_acompanha_a_data_da_execucao(conn, cid, tmp_path):
    """Issue #589: o reajuste negativo absorvido pelo espelho da execucao nao tem nota propria; a nota do par e' a
    dela, e a data tambem."""
    ex, rj = _par_absorvido(conn, cid)                      # R$ 1.000,01 e -R$ 10,01: a nota do par vale R$ 990,00
    conciliacao.cortar(conn, 1, CORTE, ensaio=False)
    assert [medicoes.detalhe(conn, m)["recebida_em"] for m in (ex, rj)] == [None, None]
    _rodada(conn, tmp_path, [_nf(100, 990.0, emissao=EMISSAO)], [_baixa(1, 100, 930.6, 930.6, 1, MAIO)])
    _ligar(conn, ex, 100)
    rel = sincronizacao_rm.datar_recebidas(conn)
    assert [(x["medicao_id"], x["tipo"], x["recebida_em"], x["acompanha"]) for x in rel["linhas"]] == [
        (ex, "execucao", "2025-05-02", None), (rj, "reajuste", "2025-05-02", ex)]
    assert (_recebida_em(conn, ex), _recebida_em(conn, rj)) == ("2025-05-02", "2025-05-02")
    assert _eventos(conn, rj) == [(None, {"recebida_em": "2025-05-02", "origem": "baixa do RM", "disparo": "rodada",
                                          "repasse": False, "acompanha": medicoes.ACOMPANHA_A_EXECUCAO,
                                          "execucao_id": ex})]


def test_reajuste_absorvido_que_ja_tem_data_fica_com_a_dele(conn, cid, tmp_path):
    ex, rj = _par_absorvido(conn, cid)
    conciliacao.cortar(conn, 1, CORTE, ensaio=False)
    conn.execute("UPDATE medicoes SET recebida_em='2025-04-30' WHERE id=?", (rj,))
    conn.commit()
    _rodada(conn, tmp_path, [_nf(100, 990.0, emissao=EMISSAO)], [_baixa(1, 100, 930.6, 930.6, 1, MAIO)])
    _ligar(conn, ex, 100)
    rel = sincronizacao_rm.datar_recebidas(conn)
    assert [x["medicao_id"] for x in rel["linhas"]] == [ex]
    assert (_recebida_em(conn, ex), _recebida_em(conn, rj)) == ("2025-05-02", "2025-04-30")
    assert _eventos(conn, rj) == []


# ------------------------------------------------------------------ o ensaio e o comando

def test_ensaio_relata_e_nao_grava_e_o_comando_grava_uma_vez(conn, cid, tmp_path, capsys):
    mid = _fechada_pelo_corte(conn, cid, 1, 500_01)
    sem_nota = _fechada_pelo_corte(conn, cid, 2, 700_07)
    _rodada(conn, tmp_path, [_nf(100, 500.01, emissao=EMISSAO)], [_baixa(1, 100, 470.01, 420.0, 1, MAIO)])
    _ligar(conn, mid, 100)
    rel = sincronizacao_rm.datar_recebidas(conn, ensaio=True)
    assert (rel["ensaio"], rel["datadas"], rel["linhas"][0]["recebida_em"]) == (True, 1, "2025-05-02")
    assert _recebida_em(conn, mid) is None and _eventos(conn) == []
    with db.mutacao(conn):                                  # dentro de outra transacao, o ensaio desfaz so' o dele
        conn.execute("UPDATE medicoes SET motivo_represamento='marca do teste' WHERE id=?", (sem_nota,))
        assert sincronizacao_rm.datar_recebidas(conn, ensaio=True)["datadas"] == 1
    assert _recebida_em(conn, mid) is None and _eventos(conn) == []
    assert medicoes.detalhe(conn, sem_nota)["motivo_represamento"] == "marca do teste"
    assert cli.main(["rm", "datar-recebidas", "--ensaio"]) == 0
    saida = capsys.readouterr().out
    assert "ENSAIO (nada foi gravado)" in saida and "ganham a data da última baixa do RM: 1" in saida
    assert "Medição 1 de execução de 2025-03" in saida and "02/05/2025" in saida
    assert "título baixado por valor menor: conferir na Reconciliação" in saida
    assert _recebida_em(conn, mid) is None and _eventos(conn) == []
    assert cli.main(["rm", "datar-recebidas"]) == 0
    assert "APLICADO" in capsys.readouterr().out
    assert _recebida_em(conn, mid) == "2025-05-02" and _recebida_em(conn, sem_nota) is None
    assert [d["disparo"] for _, d in _eventos(conn)] == ["comando"]
    assert cli.main(["rm", "datar-recebidas"]) == 0
    assert "ganham a data da última baixa do RM: 0" in capsys.readouterr().out
    assert len(_eventos(conn)) == 1


# ------------------------------------------------------------------ para que serve: a referencia do Recebido

def test_com_a_data_a_referencia_do_recebido_no_resumo_deixa_de_vir_nula(conn, cid, tmp_path):
    """O motivo da issue: a recebida sem data deixava sem lastro o recebido da competencia na mesma altura
    (`resumo_medicoes._mesma_altura`), e a tela nao mostrava a variacao."""
    hoje = datetime.date(2026, 11, 22)
    mid = _fechada_pelo_corte(conn, cid, 1, 500_01, comp="2025-03")
    referencia = lambda: resumo_medicoes.resumo(conn, hoje, mes="2025-04")["mesma_altura"]
    assert referencia()["competencia"] == "2025-03" and referencia()["recebido_centavos"] is None
    _rodada(conn, tmp_path, [_nf(100, 500.01, emissao=EMISSAO)], [_baixa(1, 100, 470.01, 470.01, 1, MAIO)])
    _ligar(conn, mid, 100)
    sincronizacao_rm.datar_recebidas(conn)
    assert referencia()["recebido_centavos"] == 500_01
