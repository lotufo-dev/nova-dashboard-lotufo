"""Cobranca ao orgao (docs/adr/0015): a lista geral de tipos de movimento do RM e os tipos extras de cada contrato."""
import json

import pytest

from app import cobranca_orgao, contratos, db

GERAL = ("2.2.01", "2.2.02", "2.2.07", "2.2.16")


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    yield c
    c.close()


def _obra(conn, instrumento, extras=None):
    cid = contratos.criar(conn, None, {"orgao": "SECRETARIA DE EXEMPLO", "numero_instrumento": instrumento,
                                       "objeto": "Obra", "valor_original_centavos": 100_000_00})
    if extras is not None:
        conn.execute("UPDATE contratos SET tipos_cobranca_extras_rm=? WHERE id=?", (json.dumps(extras), cid))
        conn.commit()
    return cid


def test_lista_geral_continua_a_mesma_e_vale_em_toda_obra_e_sem_obra():
    assert cobranca_orgao.CODTMV_COBRANCA == GERAL
    for tipo in GERAL:
        assert cobranca_orgao.e_cobranca(tipo, None, {})
        assert cobranca_orgao.e_cobranca(tipo, 7, {})
        assert cobranca_orgao.e_cobranca(tipo, 7, {8: frozenset({"2.2.03"})})


def test_tipo_extra_so_e_cobranca_no_contrato_que_o_declara():
    extras = {7: frozenset({"2.2.03"})}
    assert cobranca_orgao.e_cobranca("2.2.03", 7, extras)
    assert not cobranca_orgao.e_cobranca("2.2.03", 8, extras)          # outra obra, sem a chave
    assert not cobranca_orgao.e_cobranca("2.2.03", 9, {**extras, 9: frozenset({"2.2.04"})})   # outra obra, outro tipo
    assert not cobranca_orgao.e_cobranca("2.2.03", None, extras)       # nota que nao caiu em contrato nenhum
    assert not cobranca_orgao.e_cobranca("2.2.03", 7, {})              # ninguem declara: so' a lista geral


@pytest.mark.parametrize("tipo", ["2.2.15", "2.2.10", "2.2.04", "", None])
def test_tipo_que_ninguem_declara_e_nota_sem_tipo_nao_sao_cobranca(tipo):
    extras = {7: frozenset({"2.2.03"})}
    assert not cobranca_orgao.e_cobranca(tipo, 7, extras)
    assert not cobranca_orgao.e_cobranca(tipo, None, extras)


def test_extras_por_contrato_le_so_o_contrato_com_a_chave(conn):
    sem = _obra(conn, "001/2025/00/00-EXEMPLO")
    com = _obra(conn, "002/2025/00/00-EXEMPLO", ["2.2.03"])
    dois = _obra(conn, "003/2025/00/00-EXEMPLO", ["2.2.03", "2.2.04"])
    extras = cobranca_orgao.extras_por_contrato(conn)
    assert extras == {com: frozenset({"2.2.03"}), dois: frozenset({"2.2.03", "2.2.04"})}
    assert cobranca_orgao.e_cobranca("2.2.04", dois, extras) and not cobranca_orgao.e_cobranca("2.2.04", com, extras)
    assert not cobranca_orgao.e_cobranca("2.2.03", sem, extras)


def test_tipos_buscados_e_a_lista_geral_mais_os_extras_de_todas_as_obras():
    """So' estreita a consulta: o tipo extra de uma obra vem do banco para toda nota, e `e_cobranca` decide."""
    assert cobranca_orgao.tipos_buscados({}) == GERAL
    extras = {7: frozenset({"2.2.03"}), 8: frozenset({"2.2.04", "2.2.03"})}
    assert cobranca_orgao.tipos_buscados(extras) == (*GERAL, "2.2.03", "2.2.04")
    # tipo da lista geral gravado como extra (o `cadastro validar` recusa) nao se repete
    assert cobranca_orgao.tipos_buscados({7: frozenset({"2.2.01"})}) == GERAL


@pytest.mark.parametrize("texto, vale", [("2.2.03", True), ("2.2.16", True), ("2.2.3", False), ("2.2.003", False),
                                         ("2.3.03", False), ("1.1.21", False), ("2.2.03 ", False), ("2.2.0a", False),
                                         ("٢.٢.٠٣", False)])
def test_formato_do_tipo_de_movimento(texto, vale):
    assert bool(cobranca_orgao.FORMATO_CODTMV.fullmatch(texto)) is vale
