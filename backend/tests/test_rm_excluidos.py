"""Issue #755 (docs/adr/0006): nota e titulo que o RM deixou de devolver sao marcados como excluidos no RM e saem de
toda soma; voltando a vir, voltam a contar. Ao lado de `test_rm.py`, com o mesmo simulador.

O relogio dos testes: a marca exige ausencia em DUAS rodadas completas seguidas, medida pelo `ultimo_visto_em` contra
o inicio da rodada completa anterior. As rodadas de um teste caem no mesmo segundo, entao `_rodada` envelhece em uma
hora tudo o que o banco ja' tem antes de sincronizar, como se a rodada horaria tivesse esperado a vez dela."""
import pytest

from app import auditoria, diretoria, medicoes, notas, rm, sincronizacao_rm
from tests.test_rm import (CENTRO, _baixa, _declarar_tipos_extras, _medicao, _nf, _obra_com_centro, _simulador,
                           cid, conn)  # noqa: F401  (conn e cid sao fixtures)

# A nota mais antiga de toda rodada: marca o comeco da janela que a consulta cobre (fora das obras dos testes)
VELHA = _nf(1, 10.0, emissao="2025-01-15T00:00:00-04:00", codtmv="2.2.15")
TITULO_DA_VELHA = _baixa(900, 1, 10.0, 10.0, 1, "2025-02-01T00:00:00-04:00")
PAGO_EM_01_09 = "2026-09-01T00:00:00-04:00"


def _passa_uma_hora(conn):
    for tabela, colunas in (("notas_fiscais", ("ultimo_visto_em",)), ("baixas", ("ultimo_visto_em",)),
                            ("rm_sincronizacoes", ("iniciado_em", "terminado_em"))):
        for coluna in colunas:
            conn.execute(f"UPDATE {tabela} SET {coluna}=datetime({coluna}, '-1 hour') WHERE {coluna} IS NOT NULL")
    conn.commit()


def _rodada(conn, tmp_path, nfs, baixas, com_velha=True):
    _passa_uma_hora(conn)
    extra_n, extra_b = ([VELHA], [TITULO_DA_VELHA]) if com_velha else ([], [])
    return sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, extra_n + nfs, extra_b + baixas))


def _nota(conn, idmov):
    return conn.execute("SELECT id, situacao, excluida_rm_em FROM notas_fiscais WHERE idmov=?", (idmov,)).fetchone()


def _marcados(conn):
    return ([r[0] for r in conn.execute("SELECT idmov FROM notas_fiscais WHERE excluida_rm_em IS NOT NULL ORDER BY idmov")],
            [r[0] for r in conn.execute("SELECT idlan FROM baixas WHERE excluida_rm_em IS NOT NULL ORDER BY idlan")])


def _acoes(conn, prefixo="rm."):
    return [r[0] for r in conn.execute("SELECT acao FROM audit_log WHERE acao LIKE ? AND acao<>'rm.sincronizacao' "
                                       "ORDER BY id", (prefixo + "%",))]


def _nota_77(idmov, **extra):
    return _nf(idmov, 500.01, centro_custo=CENTRO, numero="77", **extra)


# ------------------------------------------------------------------ titulo

def test_titulo_refeito_deixa_de_contar_e_a_medicao_recebe_pela_baixa_do_vigente(conn, cid, tmp_path):
    """O faturamento exclui o titulo e o refaz: a nota continua vindo, o titulo antigo para de vir e chega outro, do
    mesmo valor. Na primeira rodada sem ele nada muda (o devido da nota aparece em dobro, como antes da #755); na
    segunda rodada completa seguida ele e' marcado: devido, recebido e falta so' pelo vigente, o marcado aparece na
    nota como excluido, e a medicao e' recebida pela baixa do vigente. Centavo impar."""
    c2 = _obra_com_centro(conn, CENTRO)
    m = _medicao(conn, c2, 3, 500_01)
    r = _rodada(conn, tmp_path, [_nota_77(7)], [_baixa(1, 7, 470.03, 0.0, 0)])
    assert r["alocacoes"] == 1, r
    refeito = [_baixa(2, 7, 470.03, 0.0, 0)]
    r = _rodada(conn, tmp_path, [_nota_77(7)], refeito)
    assert (r["notas_excluidas"], r["titulos_excluidos"]) == (0, 0) and _marcados(conn) == ([], [])
    n = medicoes.detalhe(conn, m)["notas"][0]
    assert (n["devido_centavos"], n["falta_centavos"], n["titulos_excluidos_rm"]) == (2 * 470_03, 2 * 470_03, [])

    r = _rodada(conn, tmp_path, [_nota_77(7)], refeito)
    assert (r["notas_excluidas"], r["titulos_excluidos"]) == (0, 1) and _marcados(conn) == ([], [1])
    n = medicoes.detalhe(conn, m)["notas"][0]
    assert (n["devido_centavos"], n["recebido_centavos"], n["falta_centavos"]) == (470_03, 0, 470_03)
    assert [(t["valor_original_centavos"], t["valor_baixado_centavos"], t["excluida_rm_em"] is not None)
            for t in n["titulos_excluidos_rm"]] == [(470_03, 0, True)]
    assert conn.execute("SELECT COUNT(*) FROM baixas WHERE nota_id=?", (n["nota_id"],)).fetchone()[0] == 2   # nada se apaga
    assert _acoes(conn) == ["rm.titulo_excluido"]

    r = _rodada(conn, tmp_path, [_nota_77(7)], [_baixa(2, 7, 470.03, 470.03, 1, PAGO_EM_01_09)])
    assert r["recebimentos"] == 1, r
    d = medicoes.detalhe(conn, m)
    assert (d["estado"], d["recebida_em"]) == ("recebida", "2026-09-01")
    assert (d["notas"][0]["devido_centavos"], d["notas"][0]["recebido_centavos"], d["notas"][0]["falta_centavos"]) == (
        470_03, 470_03, 0)
    assert diretoria.rm_por_mes(conn) == ({"2026-08": 500_01}, {"2026-09": 470_03})
    assert auditoria.verificar_cadeia(conn)


def test_titulo_antigo_aberto_segurava_a_medicao_ate_ser_marcado(conn, cid, tmp_path):
    """O defeito que a issue descreve: com o titulo novo ja' quitado, o antigo (aberto, que parou de vir) impede o
    recebimento. A medicao fecha na rodada em que ele e' marcado, nao antes."""
    c2 = _obra_com_centro(conn, CENTRO)
    m = _medicao(conn, c2, 3, 500_01)
    _rodada(conn, tmp_path, [_nota_77(7)], [_baixa(1, 7, 470.03, 0.0, 0)])
    pago = [_baixa(2, 7, 470.03, 470.03, 1, PAGO_EM_01_09)]
    r = _rodada(conn, tmp_path, [_nota_77(7)], pago)
    assert r["recebimentos"] == 0 and medicoes.detalhe(conn, m)["estado"] == "protocolada"
    r = _rodada(conn, tmp_path, [_nota_77(7)], pago)
    assert (r["titulos_excluidos"], r["recebimentos"]) == (1, 1), r
    assert medicoes.detalhe(conn, m)["estado"] == "recebida"


def test_titulo_que_so_muda_de_valor_ou_de_status_e_atualizacao(conn, cid, tmp_path):
    c2 = _obra_com_centro(conn, CENTRO)
    _medicao(conn, c2, 3, 500_01)
    for original, baixado, status in ((470.03, 0.0, 0), (460.01, 0.0, 0), (460.01, 100.0, 4), (460.01, 0.0, 2),
                                      (460.01, 460.01, 1)):
        r = _rodada(conn, tmp_path, [_nota_77(7)], [_baixa(1, 7, original, baixado, status,
                                                           PAGO_EM_01_09 if baixado else None)])
        assert (r["notas_excluidas"], r["titulos_excluidos"]) == (0, 0), r
    assert _marcados(conn) == ([], []) and _acoes(conn) == []
    assert [tuple(b) for b in conn.execute("SELECT idlan, valor_original_centavos, valor_baixado_centavos, status_lan "
                                           "FROM baixas WHERE idmov=7")] == [(1, 460_01, 460_01, 1)]


def test_rodada_que_falha_ou_vem_vazia_nao_marca_nem_conta_como_rodada_completa(conn, cid, tmp_path):
    """So' a rodada completa conta. A que falha (consulta sem resposta) e a que vem vazia de notas ou de titulos nao
    marcam nada, por mais tempo que o titulo esteja sem vir, e tambem nao valem como a "rodada completa anterior" da
    seguinte: depois delas, a marca ainda pede duas completas seguidas sem o titulo."""
    c2 = _obra_com_centro(conn, CENTRO)
    _medicao(conn, c2, 3, 500_01)
    refeito = [_baixa(2, 7, 470.03, 0.0, 0)]
    _rodada(conn, tmp_path, [_nota_77(7)], [_baixa(1, 7, 470.03, 0.0, 0)])
    # falha: a consulta de titulos nao responde
    _passa_uma_hora(conn)
    pasta = tmp_path / "quebrado"; pasta.mkdir()
    (pasta / f"{rm.CONSULTA_NF}.json").write_text("[]", encoding="utf-8")
    r = sincronizacao_rm.sincronizar(conn, rm.SimuladorRM(pasta))
    assert r["estado"] == "failed" and _marcados(conn) == ([], [])
    # vazias: sem titulo nenhum, depois sem nota nenhuma (repetidas: nem com o tempo passando)
    for _ in range(3):
        r = _rodada(conn, tmp_path, [_nota_77(7)], [], com_velha=False)
        assert r["estado"] == "success" and (r["notas_excluidas"], r["titulos_excluidos"]) == (0, 0)
        r = _rodada(conn, tmp_path, [], refeito, com_velha=False)
        assert r["estado"] == "success" and (r["notas_excluidas"], r["titulos_excluidos"]) == (0, 0)
    assert _marcados(conn) == ([], [])
    assert tuple(_nota(conn, 7))[1:] == ("ativa", None)
    # a primeira completa depois delas tem como anterior a completa de antes do titulo sumir... que o viu
    conn.execute("UPDATE baixas SET ultimo_visto_em=(SELECT MAX(iniciado_em) FROM rm_sincronizacoes "
                 "WHERE estado='success' AND nfs>0 AND baixas>0) WHERE idlan=1")
    conn.commit()
    r = _rodada(conn, tmp_path, [_nota_77(7)], refeito)
    assert r["titulos_excluidos"] == 0 and _marcados(conn) == ([], [])
    r = _rodada(conn, tmp_path, [_nota_77(7)], refeito)
    assert r["titulos_excluidos"] == 1 and _marcados(conn) == ([], [1])


def test_primeira_rodada_de_um_banco_sem_rodada_completa_nao_marca(conn, cid, tmp_path):
    """Sem rodada completa anterior nao ha' historico: nota e titulo antigos no banco, que esta rodada nao traz, ficam
    como estao (nada de marcar em massa por falta de historico)."""
    conn.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, emissao, valor_centavos, codtmv, "
                 "ultimo_visto_em) VALUES (1, 7, '77', 77, '2026-08-10', 50001, '2.2.01', '2026-01-01 00:00:00')")
    conn.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, status_lan, "
                 "ultimo_visto_em) SELECT 1, 1, id, 7, 47003, 0, '2026-01-01 00:00:00' FROM notas_fiscais")
    conn.commit()
    r = _rodada(conn, tmp_path, [_nota_77(8)], [_baixa(2, 8, 470.03, 0.0, 0)])
    assert r["estado"] == "success" and _marcados(conn) == ([], [])
    r = _rodada(conn, tmp_path, [_nota_77(8)], [_baixa(2, 8, 470.03, 0.0, 0)])      # agora ha' uma completa anterior
    assert (r["notas_excluidas"], r["titulos_excluidos"]) == (1, 1) and _marcados(conn) == ([7], [1])


def test_titulo_que_volta_a_vir_volta_a_contar(conn, cid, tmp_path):
    c2 = _obra_com_centro(conn, CENTRO)
    m = _medicao(conn, c2, 3, 500_01)
    os_dois = [_baixa(1, 7, 200.01, 0.0, 0), _baixa(2, 7, 270.02, 0.0, 0)]
    _rodada(conn, tmp_path, [_nota_77(7)], os_dois)
    for _ in range(2):
        _rodada(conn, tmp_path, [_nota_77(7)], os_dois[1:])
    assert _marcados(conn) == ([], [1])
    assert medicoes.detalhe(conn, m)["notas"][0]["devido_centavos"] == 270_02
    r = _rodada(conn, tmp_path, [_nota_77(7)], os_dois)
    assert _marcados(conn) == ([], []) and r["titulos_excluidos"] == 0
    n = medicoes.detalhe(conn, m)["notas"][0]
    assert (n["devido_centavos"], n["falta_centavos"], n["titulos_excluidos_rm"]) == (470_03, 470_03, [])
    assert _acoes(conn) == ["rm.titulo_excluido", "rm.titulo_voltou"]
    assert auditoria.verificar_cadeia(conn)


# ------------------------------------------------------------------ nota

@pytest.mark.parametrize("declara", [True, False])
def test_nota_que_some_e_marcada_e_a_substituta_assume(conn, cid, tmp_path, declara):
    """O faturamento refaz o movimento (reclassificacao): chega outro idmov com o mesmo numero, emissao e valor, no
    tipo 2.2.03, e o antigo so' deixa de vir. Depois de duas rodadas completas sem ele, a nota antiga e' marcada como
    excluida no RM: deixa de ser ativa, o titulo dela (com baixa) sai do recebido, o vinculo com a medicao e' desfeito
    e ela aparece na medicao como excluida. Na obra que declara o tipo, a nova liga, a medicao e' recebida pela baixa
    dela e a nota conta uma vez; nao ha' mais par de gemeas. Sem a chave, a nova nao e' cobranca: a medicao fica sem
    nota, com o aviso."""
    c2 = _obra_com_centro(conn, CENTRO)
    m = _medicao(conn, c2, 3, 500_01)
    # a antiga chegou a ter baixa (em parte): dinheiro que o RM mostrava nela
    r = _rodada(conn, tmp_path, [_nota_77(7)], [_baixa(1, 7, 470.03, 100.0, 4, "2026-08-28T00:00:00-04:00")])
    assert (r["alocacoes"], r["recebimentos"]) == (1, 0), r
    if declara:
        _declarar_tipos_extras(conn, c2, "2.2.03")
    so_a_nova = ([_nota_77(8, codtmv="2.2.03")], [_baixa(2, 8, 470.03, 470.03, 1, PAGO_EM_01_09)])
    r = _rodada(conn, tmp_path, *so_a_nova)
    assert (r["notas_excluidas"], r["titulos_excluidos"], r["recebimentos"]) == (0, 0, 0)
    # primeira rodada sem a antiga: nada muda ainda (com a chave, as duas contam)
    assert diretoria.rm_por_mes(conn) == (
        {"2026-08": (2 if declara else 1) * 500_01},
        {"2026-08": 100_00, "2026-09": 470_03} if declara else {"2026-08": 100_00})

    r = _rodada(conn, tmp_path, *so_a_nova)
    assert (r["notas_excluidas"], r["titulos_excluidos"]) == (1, 1), r
    antiga = _nota(conn, 7)
    assert (antiga["situacao"], antiga["excluida_rm_em"] is not None) == ("cancelada", True)
    assert _marcados(conn) == ([7], [1])
    assert [tuple(a) for a in conn.execute("SELECT motivo_desfazer FROM nf_alocacoes WHERE nota_id=?",
                                           (antiga["id"],))] == [("NF excluída no RM",)]
    d = medicoes.detalhe(conn, m)
    assert [(n["numero"], n["valor_centavos"], n["excluida_rm_em"] is not None) for n in d["notas_excluidas_rm"]] == [
        ("77", 500_01, True)]
    assert diretoria.notas_gemeas_de_tipo_extra(conn, c2, {"2.2.03"}) == []
    faturado, recebido = diretoria.rm_por_mes(conn)
    if declara:
        assert (r["alocacoes"], r["recebimentos"]) == (1, 1), r
        assert [(n["idmov"], n["regra"]) for n in d["notas"]] == [(8, "centro_custo_valor")]
        assert (d["estado"], d["recebida_em"]) == ("recebida", "2026-09-01")
        assert faturado == {"2026-08": 500_01} and recebido == {"2026-09": 470_03}       # uma vez; a baixa antiga saiu
    else:
        assert (r["alocacoes"], r["recebimentos"]) == (0, 0), r
        assert d["estado"] == "protocolada" and d["notas"] == []
        assert faturado == {} and recebido == {}
        assert [a["mensagem"] for a in notas.avisos(conn) if a["medicao_id"] == m] == [
            "nota 77 foi excluída no RM e nenhuma nota nova foi vinculada"]
    assert "rm.nota_excluida" in _acoes(conn) and auditoria.verificar_cadeia(conn)


def test_nota_que_volta_a_vir_volta_a_contar_com_os_titulos(conn, cid, tmp_path):
    """A nota marcada que o RM volta a devolver: a marca sai dela e dos titulos, ela volta a ser ativa e a contar, e
    o casador a liga de novo a' medicao que ficou sem nota."""
    c2 = _obra_com_centro(conn, CENTRO)
    m = _medicao(conn, c2, 3, 500_01)
    com_ela = ([_nota_77(7)], [_baixa(1, 7, 470.03, 0.0, 0)])
    outra = ([_nf(9, 123.45, centro_custo=CENTRO)], [_baixa(3, 9, 120.0, 0.0, 0)])
    _rodada(conn, tmp_path, com_ela[0] + outra[0], com_ela[1] + outra[1])
    for _ in range(2):
        _rodada(conn, tmp_path, *outra)
    assert _marcados(conn) == ([7], [1])
    assert diretoria.rm_por_mes(conn)[0] == {"2026-08": 123_45}
    d = medicoes.detalhe(conn, m)
    assert d["notas"] == [] and len(d["notas_excluidas_rm"]) == 1

    r = _rodada(conn, tmp_path, com_ela[0] + outra[0], com_ela[1] + outra[1])
    assert _marcados(conn) == ([], []) and r["alocacoes"] == 1
    assert tuple(_nota(conn, 7))[1:] == ("ativa", None)
    d = medicoes.detalhe(conn, m)
    assert [n["idmov"] for n in d["notas"]] == [7] and d["notas_excluidas_rm"] == []
    assert d["notas"][0]["devido_centavos"] == 470_03
    assert diretoria.rm_por_mes(conn)[0] == {"2026-08": 500_01 + 123_45}
    assert _acoes(conn) == ["rm.nota_excluida", "rm.titulo_excluido", "rm.nota_voltou", "rm.titulo_voltou"]
    assert auditoria.verificar_cadeia(conn)


def test_nota_fora_da_janela_da_consulta_nao_e_exclusao(conn, cid, tmp_path):
    """A consulta traz 24 meses. A nota que deixa de vir e e' mais antiga do que a nota mais antiga da resposta (ou do
    mesmo dia dela, ou sem data) saiu pela janela: fica como esta', com os titulos. A de dentro da janela e' marcada."""
    antiga = _nf(20, 300.01, emissao="2024-12-20T00:00:00-04:00", centro_custo=CENTRO)
    do_dia = _nf(21, 300.03, emissao="2025-01-15T00:00:00-04:00", centro_custo=CENTRO)     # o dia da VELHA
    de_dentro = _nf(22, 300.05, emissao="2025-01-16T00:00:00-04:00", centro_custo=CENTRO)
    titulos = [_baixa(20, 20, 280.01, 280.01, 1, "2025-01-10T00:00:00-04:00"), _baixa(21, 21, 280.03, 0.0, 0),
               _baixa(22, 22, 280.05, 0.0, 0)]
    comeco = _nf(2, 5.0, emissao="2024-12-01T00:00:00-04:00", codtmv="2.2.15")     # a janela comecava antes
    _rodada(conn, tmp_path, [comeco, antiga, do_dia, de_dentro], titulos)
    conn.execute("UPDATE notas_fiscais SET emissao=NULL WHERE idmov=2"); conn.commit()     # e uma nota sem data
    for _ in range(3):
        r = _rodada(conn, tmp_path, [], [])            # so' a VELHA (15/01/2025) e o titulo dela
    assert _marcados(conn) == ([22], [22])
    assert [tuple(n) for n in conn.execute("SELECT idmov, situacao FROM notas_fiscais WHERE idmov IN (2, 20, 21, 22) "
                                           "ORDER BY idmov")] == [(2, "ativa"), (20, "ativa"), (21, "ativa"),
                                                                  (22, "cancelada")]
    assert r["notas_excluidas"] == 0                   # ja' marcada na rodada anterior: nao marca de novo
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='rm.nota_excluida'").fetchone()[0] == 1


def test_nota_excluida_nao_se_liga_nem_se_desconsidera_e_reconsiderada_segue_fora(conn, cid, tmp_path):
    from app import correcao_medicoes
    c2 = _obra_com_centro(conn, CENTRO)
    m = _medicao(conn, c2, 3, 500_01)
    conn.execute("UPDATE contratos SET centro_custo_rm=NULL WHERE id=?", (c2,)); conn.commit()   # nao liga sozinha
    outra = ([_nf(9, 123.45)], [_baixa(3, 9, 120.0, 0.0, 0)])
    _rodada(conn, tmp_path, [_nota_77(7)] + outra[0], [_baixa(1, 7, 470.03, 0.0, 0)] + outra[1])
    correcao_medicoes.executar(conn, 1, [{"operacao": "desconsiderar_nf", "nf": {"idmov": 9}, "coligada": 1,
                                          "motivo": "teste", "fonte": "teste"}], ensaio=False)
    for _ in range(2):
        _rodada(conn, tmp_path, [], [])
    assert _marcados(conn) == ([7, 9], [1, 3])
    nid = _nota(conn, 7)["id"]
    with pytest.raises(ValueError, match="foi excluída no RM"):
        sincronizacao_rm.alocar(conn, 1, nid, m, "manual", None, "manual")
    rel = correcao_medicoes.executar(conn, 1, [{"operacao": "desconsiderar_nf", "nf": {"idmov": 7}, "coligada": 1,
                                                "motivo": "teste", "fonte": "teste"}], ensaio=True)
    assert rel["itens"][0]["erro"] == "NF 77 foi excluída no RM e já não conta: não há o que desconsiderar"
    assert rel["itens"][0]["antes"] == "excluída no RM"
    # a desconsiderada que tambem sumiu: tirar a marca da correcao nao a devolve a' conta
    correcao_medicoes.executar(conn, 1, [{"operacao": "reconsiderar_nf", "nf": {"idmov": 9}, "coligada": 1,
                                          "fonte": "teste"}], ensaio=False)
    assert tuple(conn.execute("SELECT situacao, desconsiderada_em, excluida_rm_em IS NOT NULL FROM notas_fiscais "
                              "WHERE idmov=9").fetchone()) == ("cancelada", None, 1)
