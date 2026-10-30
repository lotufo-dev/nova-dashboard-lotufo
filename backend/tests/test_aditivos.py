"""Fase 4: aditivos em andamento -> assinado com o delta conferido."""
import pytest

from app import aditivos, auditoria, auth, contratos, db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "engenharia")
    yield c
    c.close()


@pytest.fixture
def cid(conn):
    return contratos.criar(conn, 1, {"orgao": "S", "numero_instrumento": "IC 1", "objeto": "X",
                                     "valor_original_centavos": 1_000_000_00,
                                     "vigencia_fim": "2026-12-31", "execucao_fim": "2026-10-31"})


def test_assinar_confere_delta_e_recalcula_vigente(conn, cid):
    aid = aditivos.criar(conn, 1, cid, {"tipo": "misto", "numero": "1º TA", "delta_valor_centavos": 250_000_00,
                                        "nova_vigencia_fim": "2027-06-30"})
    assert contratos.vigente(conn, cid)["valor_vigente_centavos"] == 1_000_000_00   # rascunho nao conta
    with pytest.raises(ValueError, match="Conferência"):
        aditivos.assinar(conn, 1, aid, "2026-09-01", 1_200_000_00, None)
    r = aditivos.assinar(conn, 1, aid, "2026-09-01", 1_250_000_00, "reajuste do saldo pela data-base original")
    assert r == {"valor_anterior_centavos": 1_000_000_00, "valor_novo_centavos": 1_250_000_00}
    vig = contratos.vigente(conn, cid)
    assert vig["valor_vigente_centavos"] == 1_250_000_00 and vig["vigencia_fim_vigente"] == "2027-06-30"
    a = aditivos.detalhe(conn, aid)
    assert a["status"] == "assinado" and a["assinado_por"] == 1 and a["ressalva_reajuste"]
    # assinado congela
    with pytest.raises(ValueError):
        aditivos.atualizar(conn, 1, aid, {"delta_valor_centavos": 1})
    with pytest.raises(ValueError):
        aditivos.cancelar(conn, 1, aid, None)
    assert auditoria.verificar_cadeia(conn)


def test_segundo_aditivo_confere_contra_o_vigente_ja_aditado(conn, cid):
    a1 = aditivos.criar(conn, 1, cid, {"tipo": "valor", "delta_valor_centavos": 100_00})
    aditivos.assinar(conn, 1, a1, "2026-01-10", 1_000_100_00, None)
    a2 = aditivos.criar(conn, 1, cid, {"tipo": "valor", "delta_valor_centavos": -50_00})   # supressao
    with pytest.raises(ValueError):
        aditivos.assinar(conn, 1, a2, "2026-02-10", 999_950_00, None)     # esqueceu o 1º
    aditivos.assinar(conn, 1, a2, "2026-02-10", 1_000_050_00, None)
    assert contratos.vigente(conn, cid)["valor_vigente_centavos"] == 1_000_050_00


def test_datas_novas_tem_que_ser_posteriores_as_vigentes(conn, cid):
    aid = aditivos.criar(conn, 1, cid, {"tipo": "prazo", "nova_execucao_fim": "2026-10-31"})
    with pytest.raises(ValueError, match="posterior"):
        aditivos.assinar(conn, 1, aid, "2026-09-01", 1_000_000_00, None)
    aditivos.atualizar(conn, 1, aid, {"nova_execucao_fim": "2027-01-31"})
    aditivos.assinar(conn, 1, aid, "2026-09-01", 1_000_000_00, None)
    assert contratos.vigente(conn, cid)["execucao_fim_vigente"] == "2027-01-31"


def test_validacoes_do_rascunho_e_cancelamento(conn, cid):
    with pytest.raises(ValueError):
        aditivos.criar(conn, 1, cid, {"tipo": "prazo", "delta_valor_centavos": 10})        # prazo com valor
    with pytest.raises(ValueError):
        aditivos.criar(conn, 1, cid, {"tipo": "valor", "nova_vigencia_fim": "2027-01-01"})  # valor com data
    with pytest.raises(ValueError):
        aditivos.criar(conn, 1, cid, {"tipo": "escopo"})                                    # sem efeito
    aid = aditivos.criar(conn, 1, cid, {"tipo": "valor", "delta_valor_centavos": 10})
    aditivos.cancelar(conn, 1, aid, "órgão desistiu")
    a = aditivos.detalhe(conn, aid)
    assert a["cancelado_em"] and a["status"] == "em_andamento"
    with pytest.raises(ValueError):
        aditivos.assinar(conn, 1, aid, "2026-09-01", 1_000_000_10, None)
    assert contratos.vigente(conn, cid)["valor_vigente_centavos"] == 1_000_000_00
