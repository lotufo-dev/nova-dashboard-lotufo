"""Conciliacao dos recebidos do legado: nota do RM ligada a medicao antiga so' quando inequivoca."""
from app import conciliacao, medicoes, sincronizacao_rm
from tests.test_rm import _baixa, _medicao, _nf, _simulador, cid, conn  # noqa: F401 (fixtures)

EMISSAO = "2025-04-10T00:00:00-04:00"
PAGO = "2025-05-02T00:00:00-04:00"


def _carregar(conn, tmp_path, nfs, baixas):
    """Traz as notas e baixas do RM; o casador da rodada ignora o legado (competencia antes do corte)."""
    sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, nfs, baixas))


def _regras(conn, mid):
    return [n["regra"] for n in medicoes.detalhe(conn, mid)["notas"]]


def test_nota_unica_liga_e_a_baixa_quitada_marca_recebida(conn, cid, tmp_path):
    mid = _medicao(conn, cid, 12, 461_900_00, comp="2025-03")
    _carregar(conn, tmp_path, [_nf(100, 461900.0, emissao=EMISSAO)], [_baixa(1, 100, 430000.0, 430000.0, 1, PAGO)])
    assert _regras(conn, mid) == []                      # a rodada normal nao olha o legado
    rel = conciliacao.conciliar(conn, 1, ensaio=False)
    assert (rel["ligadas"], rel["recebidas"]) == (1, 1)
    m = medicoes.detalhe(conn, mid)
    assert _regras(conn, mid) == [conciliacao.REGRA]
    assert m["estado"] == "recebida" and m["recebida_em"] == "2025-05-02"


def test_soma_de_notas_do_mesmo_dia(conn, cid, tmp_path):
    mid = _medicao(conn, cid, 12, 1_000_00, comp="2025-03")
    _carregar(conn, tmp_path, [_nf(100, 600.0, emissao=EMISSAO), _nf(101, 400.0, emissao=EMISSAO)], [])
    rel = conciliacao.conciliar(conn, 1, ensaio=False)
    assert (rel["ligadas"], rel["ligadas_em_aberto"]) == (1, 1)     # sem baixa, fica protocolada
    assert _regras(conn, mid) == [conciliacao.REGRA] * 2


def test_duas_medicoes_de_mesmo_valor_nao_ligam(conn, cid, tmp_path):
    a = _medicao(conn, cid, 12, 500_00, comp="2025-03")
    b = _medicao(conn, cid, 13, 500_00, comp="2025-03", tipo="reajuste")
    _carregar(conn, tmp_path, [_nf(100, 500.0, emissao=EMISSAO)], [])
    rel = conciliacao.conciliar(conn, 1, ensaio=False)
    assert (rel["ligadas"], rel["ambiguas"]) == (0, 2)
    assert _regras(conn, a) == _regras(conn, b) == []


def test_nota_fora_da_janela_do_protocolo_nao_liga(conn, cid, tmp_path):
    mid = _medicao(conn, cid, 12, 500_00, comp="2025-03")
    _carregar(conn, tmp_path, [_nf(99, 77.0, emissao="2025-01-05T00:00:00-04:00"),      # abre a janela do RM
                               _nf(100, 500.0, emissao="2025-12-01T00:00:00-04:00")], [])
    assert conciliacao.conciliar(conn, 1, ensaio=False)["sem_nota"] == 1
    assert _regras(conn, mid) == []


def test_ensaio_relata_e_desfaz(conn, cid, tmp_path):
    mid = _medicao(conn, cid, 12, 500_00, comp="2025-03")
    _carregar(conn, tmp_path, [_nf(100, 500.0, emissao=EMISSAO)], [_baixa(1, 100, 470.0, 470.0, 1, PAGO)])
    rel = conciliacao.conciliar(conn, 1, ensaio=True)
    assert (rel["ensaio"], rel["ligadas"], rel["recebidas"]) == (True, 1, 1)
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "protocolada" and m["notas"] == []


def test_notas_antigas_do_rm_entram_so_quando_ligam(conn, cid, tmp_path):
    """Fase 2: as linhas da DASH12/DASH13 nao passam pela sincronizacao; so' a nota que liga (e as baixas dela)
    entra no banco."""
    mid = _medicao(conn, cid, 3, 800_00, comp="2023-03")
    nfs = [_nf(200, 800.0, emissao="2023-04-12T00:00:00-04:00"), _nf(201, 55.0, emissao="2023-04-12T00:00:00-04:00")]
    baixas = [_baixa(9, 200, 740.0, 740.0, 1, "2023-05-03T00:00:00-04:00")]
    rel = conciliacao.conciliar(conn, 1, ensaio=False, antigas=(nfs, baixas))
    assert (rel["ligadas"], rel["recebidas"]) == (1, 1)
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "recebida" and m["recebida_em"] == "2023-05-03"
    assert [r[0] for r in conn.execute("SELECT idmov FROM notas_fiscais")] == [200]


def test_centro_anterior_do_cadastro_vale_para_nota_antiga(conn, cid, tmp_path):
    """O RM trocou os centros por volta de 2024: nota antiga no centro velho casa se o cadastro o lista."""
    conn.execute("UPDATE contratos SET centro_custo_rm='4.004.004', centros_custo_anteriores_rm='[\"6.004.003\"]' "
                 "WHERE id=?", (cid,)); conn.commit()
    mid = _medicao(conn, cid, 1, 403_665_96, comp="2022-07")
    nfs = [_nf(300, 403665.96, emissao="2022-08-25T00:00:00-04:00", centro_custo="6.004.003")]
    assert conciliacao.conciliar(conn, 1, ensaio=False, antigas=(nfs, []))["ligadas"] == 1
    assert _regras(conn, mid) == [conciliacao.REGRA]


def test_nota_fora_da_cobranca_com_valor_exato_nao_vira_opcao(conn, cid, tmp_path):
    """Issue #598: so' nota de cobranca ao orgao (`diretoria.CODTMV_COBRANCA`) liga. Nota 2.2.15 (fornecedor) do
    centro da obra, na janela e com o valor exato, nao vira opcao; nem nota sem tipo."""
    mid = _medicao(conn, cid, 12, 461_900_00, comp="2025-03")
    fornecedor = dict(_nf(100, 461900.0, emissao=EMISSAO), CODTMV="2.2.15")
    sem_tipo = {k: v for k, v in _nf(101, 461900.0, emissao=EMISSAO).items() if k != "CODTMV"}
    _carregar(conn, tmp_path, [fornecedor, sem_tipo], [_baixa(1, 100, 461900.0, 461900.0, 1, PAGO)])
    rel = conciliacao.conciliar(conn, 1, ensaio=False)
    assert (rel["ligadas"], rel["sem_nota"]) == (0, 1)
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "protocolada" and _regras(conn, mid) == []


def test_nota_antiga_fora_da_cobranca_nao_liga_nem_entra_no_banco(conn, cid, tmp_path):
    """Issue #598, fase 2 (DASH12 traz todo 2.2.%): nota 2.2.15 ou sem tipo nao liga; a 2.2.16 do mesmo valor liga."""
    mid = _medicao(conn, cid, 3, 800_00, comp="2023-03")
    emissao = "2023-04-12T00:00:00-04:00"
    nfs = [dict(_nf(200, 800.0, emissao=emissao), CODTMV="2.2.15"),
           {k: v for k, v in _nf(201, 800.0, emissao=emissao).items() if k != "CODTMV"}]
    rel = conciliacao.conciliar(conn, 1, ensaio=False, antigas=(nfs, []))
    assert (rel["ligadas"], rel["sem_nota"]) == (0, 1)
    assert conn.execute("SELECT COUNT(*) FROM notas_fiscais").fetchone()[0] == 0
    nfs.append(dict(_nf(202, 800.0, emissao=emissao), CODTMV="2.2.16"))
    assert conciliacao.conciliar(conn, 1, ensaio=False, antigas=(nfs, []))["ligadas"] == 1
    assert [r[0] for r in conn.execute("SELECT idmov FROM notas_fiscais")] == [202]
    assert _regras(conn, mid) == [conciliacao.REGRA]


def test_corte_fecha_o_legado_protocolado_ate_a_data(conn, cid, tmp_path):
    antiga = _medicao(conn, cid, 1, 500_00, comp="2025-03")          # protocolo 2025-03-28
    depois = _medicao(conn, cid, 2, 700_00, comp="2026-10")          # competencia depois do corte do RM
    rel = conciliacao.cortar(conn, 1, "2026-09-22", ensaio=False)
    assert (rel["fechadas"], rel["valor_centavos"]) == (1, 500_00)
    a = medicoes.detalhe(conn, antiga)
    assert a["estado"] == "recebida" and a["recebida_em"] is None and "corte de 22/09/2026" in a["motivo_represamento"]
    assert medicoes.detalhe(conn, depois)["estado"] == "protocolada"


def test_corte_grava_a_origem_e_nao_conta_como_recebimento_a_mao(conn, cid, tmp_path, monkeypatch):
    """Issue #203 (gate Sol S2): o corte se reconhece pela origem que o servidor grava, nao pelo texto do motivo."""
    monkeypatch.setattr(conciliacao, "MOTIVO_CORTE", "fechada no corte de {data}")
    antiga = _medicao(conn, cid, 1, 500_00, comp="2025-03")
    conciliacao.cortar(conn, 1, "2026-09-22", ensaio=False)
    assert medicoes.detalhe(conn, antiga)["estado"] == "recebida"
    assert conciliacao.recebidas_a_mao(conn) == set()


def _par_absorvido(conn, cid, numero=3, comp="2025-03"):
    """Issue #589: execucao (R$ 1.000,01) e reajuste negativo (-R$ 10,01) no mesmo espelho vigente; o protocolo da
    execucao leva o reajuste a protocolada."""
    ex = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": numero, "tipo": "execucao", "competencia": comp})
    medicoes.definir_valor(conn, 1, ex, "protocolado", 1_000_01, "manual")
    rj = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": numero, "tipo": "reajuste", "competencia": comp,
                                  "valor_centavos": -10_01})
    eid = conn.execute("INSERT INTO espelhos (contrato_id, numero, competencia, versao, situacao, entradas, saidas, "
                       "regra_sha256, criado_por) VALUES (?, ?, ?, 1, 'vigente', '{}', '[]', 'x', 1)",
                       (cid, numero, comp)).lastrowid
    conn.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id, valor_centavos, valor_com_sinal_centavos) "
                 "VALUES (?,?,100001,100001), (?,?,NULL,-1001)", (eid, ex, eid, rj))
    conn.commit()
    medicoes.registrar_protocolo(conn, 1, ex, f"{comp}-28", "CT-1", None, "manual")
    assert medicoes.detalhe(conn, rj)["estado"] == "protocolada"
    return ex, rj


def test_corte_fecha_o_reajuste_absorvido_pela_execucao_e_nao_aborta(conn, cid, tmp_path):
    """Revisor da PR #608 (rodada 2, critico): o reajuste absorvido (pedido manual) entra na consulta do corte, mas fecha
    pela execucao; o corte nao aborta e conta o valor do par uma vez."""
    ex, rj = _par_absorvido(conn, cid)
    rel = conciliacao.cortar(conn, 1, "2026-09-22", ensaio=False)
    assert (rel["fechadas"], rel["valor_centavos"]) == (1, 990_00)
    assert [medicoes.detalhe(conn, m)["estado"] for m in (ex, rj)] == ["recebida", "recebida"]


def test_corte_com_a_execucao_fora_deixa_o_reajuste_absorvido_com_ela(conn, cid, tmp_path):
    """Variante: a execucao do espelho fica fora do corte; o reajuste absorvido tambem fica (segue a execucao), sem
    abortar o corte das outras medicoes."""
    ex, rj = _par_absorvido(conn, cid)
    conn.execute("UPDATE medicoes SET valor_protocolado_origem='espelho' WHERE id=?", (ex,))
    conn.commit()
    antiga = _medicao(conn, cid, 1, 500_00, comp="2025-03")
    rel = conciliacao.cortar(conn, 1, "2026-09-22", ensaio=False)
    assert (rel["fechadas"], rel["valor_centavos"]) == (1, 500_00)
    assert [medicoes.detalhe(conn, m)["estado"] for m in (ex, rj, antiga)] == ["protocolada", "protocolada", "recebida"]
