"""docs/adr/0006 ("Titulo baixado no RM nao tem falta"): o titulo que o RM da' como baixado nao e' divida, e o residuo
de nota ja' paga se encerra pela correcao de cadastro, sem apagar nada. Dados ficticios, centavos impares."""
import contextlib
import json

import pytest

from app import db, diretoria, sincronizacao_rm
from tests.test_correcao_medicoes import _ligar, _medicao, _nota, _rodar, cenario  # noqa: F401
from tests.test_db import _aplicar, _banco_antes_de

ARQUIVO = "092_residuo_encerrado.sql"
ENCERRAR = {"operacao": "encerrar_residuo_nf", "motivo": "sobra de baixa parcial antiga que o RM não baixa",
            "fonte": "extrato de exemplo: a nota foi paga inteira"}


def _titulo(c, nid, original, baixado, status, idlan=None):
    c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
              "status_lan, data_baixa) VALUES (1,?,?,?,?,?,?,?)",
              (idlan or 7000 + nid, nid, 900, original, baixado, status, "2025-08-01" if baixado else None))
    c.commit()


def _cobranca(c, numero, valor):
    nid = _nota(c, numero, valor=valor)
    c.execute("UPDATE notas_fiscais SET codtmv='2.2.01' WHERE id=?", (nid,))
    c.commit()
    return nid


def _falta(c, nid, **kw):
    return sincronizacao_rm._falta_por_titulo(c, nid, **kw)


# ------------------------------------------------------------------ a regra pelo status do titulo

def test_falta_segue_o_status_do_titulo_no_rm(cenario):
    c, cid, uid = cenario
    baixado = _cobranca(c, 601, 90_000_011)
    _titulo(c, baixado, 83_000_009, 82_800_008, 1)              # baixa total com R$ 2.000,01 a menos: quitado
    em_parte = _cobranca(c, 602, 50_000_003)
    _titulo(c, em_parte, 46_000_003, 45_990_002, 4)           # baixa parcial: falta o resto
    aberto = _cobranca(c, 603, 100_001)
    _titulo(c, aberto, 93_001, 0, 0)
    sem_valor = _cobranca(c, 604, 100_001)
    _titulo(c, sem_valor, 93_001, 0, 1)                         # baixa total sem valor: so' com `baixa_total_quita`
    misto = _cobranca(c, 605, 200_003)
    _titulo(c, misto, 100_001, 99_000, 1, idlan=1)              # baixado com diferenca: sem falta
    _titulo(c, misto, 86_002, 80_001, 4, idlan=2)               # em parte: falta 6.001
    assert _falta(c, baixado) == 0 and _falta(c, baixado, aberto_inteiro=True, baixa_total_quita=True) == 0
    assert sincronizacao_rm.diferenca_da_baixa_total(c, baixado) == 200_001
    assert _falta(c, em_parte) == 10_001
    assert _falta(c, aberto) is None and _falta(c, aberto, aberto_inteiro=True) == 93_001
    assert _falta(c, sem_valor) is None and _falta(c, sem_valor, aberto_inteiro=True) == 93_001
    assert _falta(c, sem_valor, aberto_inteiro=True, baixa_total_quita=True) == 0
    assert _falta(c, misto) == 6_001


def test_nota_com_titulo_baixado_a_menos_sai_do_a_receber(cenario):
    """A nota de medicao recebida pelo corte com o titulo baixado no RM por valor menor aparecia como divida pela
    diferenca. Baixado no RM, nao ha' falta: sai do a receber. A paga em parte continua."""
    c, cid, uid = cenario
    baixado, em_parte = _cobranca(c, 601, 90_000_011), _cobranca(c, 602, 50_000_003)
    _titulo(c, baixado, 83_000_009, 82_800_008, 1)
    _titulo(c, em_parte, 46_000_003, 45_990_002, 4)
    for numero, nid in ((1, baixado), (2, em_parte)):
        _ligar(c, _medicao(c, cid, numero, estado="recebida"), nid)
    assert [(x["numero"], x["valor_protocolado_centavos"]) for x in diretoria._notas_em_aberto(c)] == [("602", 10_001)]
    assert [x["numero_nf"] for x in sincronizacao_rm._recebidas_sem_baixa(c)] == ["602"]


# ------------------------------------------------------------------ encerrar o residuo

def test_encerrar_residuo_tira_a_nota_paga_do_a_receber_sem_apagar(cenario):
    c, cid, uid = cenario
    nid = _cobranca(c, 602, 50_000_003)
    _titulo(c, nid, 46_000_003, 45_990_002, 4)
    _ligar(c, _medicao(c, cid, 4, estado="recebida"), nid)
    antes = [tuple(r) for r in c.execute("SELECT * FROM baixas")]
    rel = _rodar(c, uid, [{**ENCERRAR, "nf": 602}], ensaio=True)
    assert rel["feitos"] == 1 and _falta(c, nid) == 10_001                 # o ensaio nao grava
    rel = _rodar(c, uid, [{**ENCERRAR, "nf": 602}])
    assert rel["feitos"] == 1 and "resíduo de R$ 100,01 encerrado" in rel["itens"][0]["detalhes"][0]
    assert len(rel["itens"][0]["detalhes"]) == 1                            # 0,02% do titulo: sem aviso
    n = dict(c.execute("SELECT * FROM notas_fiscais WHERE id=?", (nid,)).fetchone())
    assert n["residuo_encerrado_centavos"] == 10_001 and n["residuo_encerrado_em"] and n["situacao"] == "ativa"
    assert [tuple(r) for r in c.execute("SELECT * FROM baixas")] == antes   # titulos e baixas como o RM deu
    assert _falta(c, nid) == 0 and diretoria._notas_em_aberto(c) == []
    assert sincronizacao_rm._recebidas_sem_baixa(c) == []
    reg = json.loads(c.execute("SELECT depois FROM audit_log WHERE acao='nota.residuo_encerrado'").fetchone()[0])
    assert (reg["residuo_encerrado_centavos"], reg["titulos_centavos"], reg["motivo"], reg["fonte"], reg["origem"]) == (
        10_001, 46_000_003, ENCERRAR["motivo"], ENCERRAR["fonte"], "correção de cadastro")
    assert _rodar(c, uid, [{**ENCERRAR, "nf": 602}])["ja_feitos"] == 1
    # o que passar do residuo encerrado volta a aparecer (um titulo novo em aberto, por exemplo)
    _titulo(c, nid, 5_001, 0, 0, idlan=2)
    assert _falta(c, nid, aberto_inteiro=True) == 5_001
    # e o ato tem volta, como evento novo
    rel = _rodar(c, uid, [{"operacao": "reabrir_residuo_nf", "nf": 602, "motivo": "encerrado por engano", "fonte": "y"}])
    assert rel["feitos"] == 1 and _falta(c, nid, aberto_inteiro=True) == 10_001 + 5_001
    assert c.execute("SELECT COUNT(*) FROM audit_log WHERE acao='nota.residuo_reaberto'").fetchone()[0] == 1


def test_encerrar_residuo_recusa_o_que_nao_e_residuo_de_nota_paga(cenario):
    c, cid, uid = cenario
    aberta = _cobranca(c, 603, 100_001)
    _titulo(c, aberta, 93_001, 0, 0)                            # titulo inteiro em aberto: divida, nao residuo
    quitada = _cobranca(c, 604, 100_001)
    _titulo(c, quitada, 93_001, 93_001, 1)
    _cobranca(c, 605, 100_001)                                  # sem titulo
    grande = _cobranca(c, 606, 100_001)
    _titulo(c, grande, 93_001, 60_000, 4)
    casos = [(603, "tem título sem baixa no RM"), (604, "não tem resíduo"), (605, "não tem título no RM")]
    for nf, erro in casos:
        rel = _rodar(c, uid, [{**ENCERRAR, "nf": nf}])
        assert rel["erros"] == 1 and erro in rel["itens"][0]["erro"], rel["itens"][0]
    sem_motivo = {k: v for k, v in ENCERRAR.items() if k != "motivo"} | {"nf": 606}
    assert "diga o motivo" in _rodar(c, uid, [sem_motivo])["itens"][0]["erro"]
    # resto grande (35% do titulo): o ato nao trava, avisa
    rel = _rodar(c, uid, [{**ENCERRAR, "nf": 606}], ensaio=True)
    assert rel["feitos"] == 1 and any("AVISO: o resíduo passa de 1%" in d for d in rel["itens"][0]["detalhes"])
    assert c.execute("SELECT COUNT(*) FROM notas_fiscais WHERE residuo_encerrado_centavos IS NOT NULL").fetchone()[0] == 0
    # o desconsiderar_nf continua recusando a nota com baixa: o resto dela se encerra por este ato
    rel = _rodar(c, uid, [{"operacao": "desconsiderar_nf", "nf": 606, "motivo": "x", "fonte": "y"}])
    assert "tem baixa no RM" in rel["itens"][0]["erro"]


# ------------------------------------------------------------------ a diferenca fica a' vista na reconciliacao

def test_reconciliacao_lista_o_titulo_baixado_por_valor_menor_acima_de_um_real(cenario):
    """Recebeu menos do que cobrou: nao e' divida e nao segura a medicao, mas aparece para o administrador. Entra o
    titulo baixado (status 1) com mais de R$ 1,00 a menos; fica de fora o que esta' na tolerancia, o baixado em parte
    (esse tem falta e ja' aparece no a receber), o titulo excluido no RM e a nota que nao e' cobranca ao orgao."""
    c, cid, uid = cenario
    mid = _medicao(c, cid, 1, estado="recebida")
    ligada = _cobranca(c, 601, 90_000_011)
    _ligar(c, mid, ligada)
    _titulo(c, ligada, 83_000_009, 82_800_008, 1)                   # R$ 2.000,01 a menos: entra, com a medicao
    solta = _cobranca(c, 607, 60_001)
    _titulo(c, solta, 50_102, 50_001, 1, idlan=71)                  # R$ 1,01 a menos, sem medicao: entra
    _titulo(c, solta, 5_100, 5_000, 1, idlan=72)                    # R$ 1,00 a menos: na tolerancia, fora
    em_parte = _cobranca(c, 602, 50_000_003)
    _titulo(c, em_parte, 46_000_003, 45_990_002, 4)                 # baixado em parte: fora (tem falta)
    excluido = _cobranca(c, 608, 100_001)
    _titulo(c, excluido, 93_001, 80_000, 1)
    c.execute("UPDATE baixas SET excluida_rm_em='2026-11-01 10:00:00' WHERE nota_id=?", (excluido,))
    fornecedor = _nota(c, 609, valor=100_001)                       # sem tipo de cobranca ao orgao: fora
    _titulo(c, fornecedor, 93_001, 80_000, 1)
    c.execute("UPDATE baixas SET data_baixa='2025-09-10' WHERE nota_id=?", (solta,))
    c.commit()
    linhas = sincronizacao_rm.reconciliacao(c)["baixados_com_diferenca"]
    assert [(x["numero_nf"], x["contrato_id"], x["medicao_id"], x["numero"], x["tipo"], x["valor_original_centavos"],
             x["valor_baixado_centavos"], x["diferenca_centavos"], x["data_baixa"]) for x in linhas] == [
        ("607", cid, None, None, None, 50_102, 50_001, 101, "2025-09-10"),
        ("601", cid, mid, 1, "execucao", 83_000_009, 82_800_008, 200_001, "2025-08-01")]
    assert linhas[0]["numero_instrumento"]
    # nenhuma das duas e' divida: nao estao no a receber
    assert [x["numero"] for x in diretoria._notas_em_aberto(c)] == ["602"]


def test_diferenca_conferida_pelo_ato_sai_da_reconciliacao_e_volta_se_o_ato_e_desfeito(cenario):
    c, cid, uid = cenario
    nid = _cobranca(c, 601, 90_000_011)
    _titulo(c, nid, 83_000_009, 82_800_008, 1)
    grupo = lambda: [x["numero_nf"] for x in sincronizacao_rm.reconciliacao(c)["baixados_com_diferenca"]]
    assert grupo() == ["601"]
    rel = _rodar(c, uid, [{**ENCERRAR, "nf": 601, "motivo": "desconto lançado na baixa, conferido"}])
    assert rel["feitos"] == 1, rel
    assert "diferença de R$ 2.000,01 na baixa total conferida" in rel["itens"][0]["detalhes"][0]
    assert grupo() == []
    n = dict(c.execute("SELECT * FROM notas_fiscais WHERE id=?", (nid,)).fetchone())
    assert n["residuo_encerrado_centavos"] == 0 and n["residuo_encerrado_em"]       # nao havia falta a abater
    reg = json.loads(c.execute("SELECT depois FROM audit_log WHERE acao='nota.residuo_encerrado'").fetchone()[0])
    assert reg["diferenca_da_baixa_total_centavos"] == 200_001 and reg["residuo_encerrado_centavos"] == 0
    assert _rodar(c, uid, [{**ENCERRAR, "nf": 601}])["ja_feitos"] == 1
    rel = _rodar(c, uid, [{"operacao": "reabrir_residuo_nf", "nf": 601, "motivo": "conferência errada", "fonte": "y"}])
    assert rel["feitos"] == 1 and grupo() == ["601"]


# ------------------------------------------------------------------ migracao 092

@pytest.mark.migracao_real
def test_092_nota_existente_nasce_sem_residuo_e_nenhuma_linha_muda(tmp_path, monkeypatch):
    conn, pasta = _banco_antes_de(ARQUIVO, tmp_path, monkeypatch)
    with contextlib.closing(conn):
        assert "residuo_encerrado_centavos" not in [r[1] for r in conn.execute("PRAGMA table_info(notas_fiscais)")]
        for i in (1, 2):
            conn.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, emissao, valor_centavos, situacao) "
                         "VALUES (1,?,?,?,'2025-07-01',100001,'ativa')", (900 + i, str(i), i))
        conn.commit()
        antes = [dict(r) for r in conn.execute("SELECT * FROM notas_fiscais ORDER BY id")]
        _aplicar(conn, pasta, ARQUIVO)
        depois = [dict(r) for r in conn.execute("SELECT * FROM notas_fiscais ORDER BY id")]
        assert [(d.pop("residuo_encerrado_centavos"), d.pop("residuo_encerrado_em")) for d in depois] == [(None, None)] * 2
        assert depois == antes and len(depois) == 2


@pytest.mark.migracao_real
def test_092_reexecutavel_sem_perder_o_residuo_gravado(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()
    with contextlib.closing(conn):
        db.migrate(conn)
        conn.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, emissao, valor_centavos, situacao, "
                     "residuo_encerrado_centavos, residuo_encerrado_em) VALUES (1,901,'1',1,'2025-07-01',100001,'ativa',"
                     "10001,'2026-11-17 10:00:00')")
        conn.execute("DELETE FROM schema_migrations WHERE nome=?", (ARQUIVO,))
        conn.commit()
        db.migrate(conn)
        colunas = [r[1] for r in conn.execute("PRAGMA table_info(notas_fiscais)")]
        assert colunas.count("residuo_encerrado_centavos") == 1 and colunas.count("residuo_encerrado_em") == 1
        assert tuple(conn.execute("SELECT residuo_encerrado_centavos, residuo_encerrado_em FROM notas_fiscais").fetchone()) == (
            10001, "2026-11-17 10:00:00")
