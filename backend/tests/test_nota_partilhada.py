"""docs/adr/0005 ("Uma nota em mais de uma medicao"): `ligar_nf` com o valor de cada parte, e toda conta que usa o
vinculo respeitando o valor da parte. Dados ficticios (cadastro-exemplo), centavos impares e rateio com residuo."""
import contextlib
import json

import pytest

from app import db, diretoria, fechamento, medicoes, sincronizacao_rm
from tests.test_correcao_medicoes import _ativas, _estado, _ligar, _medicao, _nota, _rodar, cenario  # noqa: F401
from tests.test_db import _aplicar, _banco_antes_de

ARQUIVO = "093_nota_partilhada.sql"
A, B, NOTA = 100_001, 200_002, 300_003          # a nota fatura as duas medicoes, ao centavo


def _cobranca(c, numero, valor):
    nid = _nota(c, numero, valor=valor)
    c.execute("UPDATE notas_fiscais SET codtmv='2.2.01' WHERE id=?", (nid,))
    c.commit()
    return nid


def _titulo(c, nid, original, baixado=0, status=0, idlan=None):
    c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
              "status_lan, data_baixa) VALUES (1,?,?,?,?,?,?,?)",
              (idlan or 8000 + nid, nid, 900, original, baixado, status, "2025-08-01" if baixado else None))
    c.commit()


def _parte(mid, valor, numero=856):
    return {"operacao": "ligar_nf", "medicao_id": mid, "nfs": [{"numero": numero, "valor": valor}],
            "fonte": "PDF da nota de exemplo: fatura as duas medições"}


def _liberar(c):
    c.execute("INSERT OR REPLACE INTO cadastro_geral (chave, valor) VALUES ('diretoria', ?)",
              (json.dumps({"total_a_receber_liberado": True}),))
    c.commit()


def _duas(c, cid, uid, estado_a="protocolada", estado_b="protocolada"):
    a, b = _medicao(c, cid, 4, estado=estado_a, valor=A), _medicao(c, cid, 5, estado=estado_b, valor=B)
    nid = _cobranca(c, 856, NOTA)
    rel = _rodar(c, uid, [_parte(a, "1.000,01"), _parte(b, "2.000,02")])
    assert rel["feitos"] == 2 and rel["erros"] == 0, rel
    return a, b, nid


def test_ligar_nf_aceita_a_mesma_nota_em_duas_medicoes_pelo_valor_de_cada_parte(cenario):
    c, cid, uid = cenario
    a, b = _medicao(c, cid, 4, valor=A), _medicao(c, cid, 5, valor=B)
    nid = _cobranca(c, 856, NOTA)
    rel = _rodar(c, uid, [_parte(a, "1.000,01")])
    assert rel["feitos"] == 1
    assert "pela parte de R$ 1.000,01; da nota, R$ 2.000,02 seguem sem medição" in rel["itens"][0]["detalhes"][0]
    rel = _rodar(c, uid, [_parte(b, "2.000,02")])
    assert rel["feitos"] == 1 and "R$ 0,00 seguem sem medição" in rel["itens"][0]["detalhes"][0]
    assert [tuple(r) for r in c.execute("SELECT medicao_id, valor_alocado_centavos, partilhada FROM nf_alocacoes "
                                        "WHERE nota_id=? AND desfeita_em IS NULL ORDER BY id", (nid,))] == [
        (a, A, 1), (b, B, 1)]
    alocar = [json.loads(r[0]) for r in c.execute("SELECT depois FROM audit_log WHERE acao='nf.alocar' ORDER BY id")]
    assert [(x["partilhada"], x["valor_da_parte_centavos"], x["valor_centavos"]) for x in alocar] == [
        (True, A, NOTA), (True, B, NOTA)]
    assert _rodar(c, uid, [_parte(a, "1.000,01"), _parte(b, "2.000,02")])["ja_feitos"] == 2
    # a pagina de cada medicao mostra a nota com o valor da parte
    assert [(n["partilhada"], n["valor_vinculo_centavos"], n["valor_centavos"]) for n in medicoes.detalhe(c, a)["notas"]] == [
        (True, A, NOTA)]
    assert sincronizacao_rm.reconciliacao(c)["divergencias"] == []


def test_as_partes_somam_no_maximo_o_valor_da_nota(cenario):
    c, cid, uid = cenario
    a, b, d = _medicao(c, cid, 4, valor=A), _medicao(c, cid, 5, valor=B), _medicao(c, cid, 6, valor=1)
    nid = _cobranca(c, 856, NOTA)
    assert _rodar(c, uid, [_parte(a, "1.000,01"), _parte(b, "2.000,02")])["feitos"] == 2
    rel = _rodar(c, uid, [_parte(d, "0,01")])
    assert rel["erros"] == 1 and "somariam R$ 3.000,04, mais que o valor dela (R$ 3.000,03)" in rel["itens"][0]["erro"]
    # a parte maior que a nota, a parte zero e a nota ja' ligada inteira a outra medicao
    outra = _cobranca(c, 857, 50_001)
    casos = [(_parte(d, "500,02", 857), "é maior que a NF 857"), (_parte(d, "0,00", 857), "precisa ser maior que zero")]
    for op, erro in casos:
        rel = _rodar(c, uid, [{**op, "parcial": True}])
        assert rel["erros"] == 1 and erro in rel["itens"][0]["erro"], rel["itens"][0]
    _ligar(c, a, outra, valor=50_001)                               # vinculo antigo, da nota inteira
    rel = _rodar(c, uid, [_parte(d, "0,01", 857)])
    assert rel["erros"] == 1 and "já está alocada inteira a uma medição" in rel["itens"][0]["erro"]
    # sem dizer o valor, a nota que ja' esta' partilhada continua recusada, e a recusa diz como
    rel = _rodar(c, uid, [{"operacao": "ligar_nf", "medicao_id": d, "nfs": [856], "fonte": "x"}])
    assert rel["erros"] == 1 and "diga o valor da parte desta" in rel["itens"][0]["erro"]
    assert _ativas(c, d) == [] and len(_ativas(c, a)) == 2 and _ativas(c, b) == [nid]


def test_parte_que_nao_cobre_a_medicao_pede_parcial(cenario):
    c, cid, uid = cenario
    a = _medicao(c, cid, 4, valor=A)
    _cobranca(c, 856, NOTA)
    rel = _rodar(c, uid, [_parte(a, "1.000,00")])
    assert rel["erros"] == 1 and "as notas somam R$ 1.000,00 e a medição vale R$ 1.000,01" in rel["itens"][0]["erro"]


def test_nota_paga_fecha_as_duas_medicoes_pela_parte_de_cada_uma(cenario):
    """A cobertura da medicao (docs/adr/0006) conta o valor da PARTE: a nota de R$ 3.000,03 nao "cobre a mais" a
    medicao de R$ 1.000,01, e a parte menor que a medicao nao a fecha."""
    c, cid, uid = cenario
    a, b = _medicao(c, cid, 4, valor=A), _medicao(c, cid, 5, valor=B + 1)        # a segunda fica 1 centavo descoberta
    nid = _cobranca(c, 856, NOTA)
    _titulo(c, nid, 279_003, 279_003, 1)
    rel = _rodar(c, uid, [_parte(a, "1.000,01"), {**_parte(b, "2.000,02"), "parcial": True}])
    assert rel["feitos"] == 2
    assert (_estado(c, a), _estado(c, b)) == ("recebida", "protocolada")
    assert [x["medicao_id"] for x in sincronizacao_rm.pagas_sem_cobrir(c)] == [b]
    # o devido e o recebido dos titulos repartem-se pelas partes, so' com inteiros, e somam o titulo
    na, nb = medicoes.detalhe(c, a)["notas"][0], medicoes.detalhe(c, b)["notas"][0]
    assert (na["devido_centavos"], nb["devido_centavos"]) == (93_001, 186_002)
    assert na["recebido_centavos"] + nb["recebido_centavos"] == 279_003 and na["falta_centavos"] == nb["falta_centavos"] == 0


def test_rateio_da_falta_com_residuo_soma_o_total(cenario):
    c, cid, uid = cenario
    ms = [_medicao(c, cid, n, valor=100_001) for n in (4, 5, 6)]
    nid = _cobranca(c, 856, NOTA)
    assert _rodar(c, uid, [_parte(m, "1.000,01") for m in ms])["feitos"] == 3
    partes = sincronizacao_rm.partes_da_nota(c, nid, 100_000)       # 100.000 em tres partes iguais: sobra 1 centavo
    assert sorted(v for k, v in partes.items() if k is not None) == [33_333, 33_333, 33_334] and partes[None] == 0
    assert sum(partes.values()) == 100_000
    # com so' uma parte ligada, o resto da nota leva a parte dele
    c.execute("UPDATE nf_alocacoes SET desfeita_em=datetime('now') WHERE medicao_id IN (?,?)", ms[1:])
    c.commit()
    partes = sincronizacao_rm.partes_da_nota(c, nid, 100_000)
    assert sum(partes.values()) == 100_000 and partes[None] == 66_667


def test_fechamento_conta_a_nota_em_cada_medicao_pelo_valor_da_parte(cenario):
    c, cid, uid = cenario
    _liberar(c)
    a, b, nid = _duas(c, cid, uid)
    _titulo(c, nid, 279_003, 100_000, 4)                            # paga em parte: faltam 179.003 nos titulos
    for mid in (a, b):
        c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, '2025-07-10', 'manual')", (mid,))
    c.commit()
    f = fechamento.fechamento(c)
    ano = f["por_ano"]["2025"]
    assert ano["protocolado_centavos"] == NOTA                      # a nota entra uma vez, repartida
    por_medicao = {x["medicao_id"]: x for mes in f["meses"] for o in mes["obras"] for x in o["medicoes"]}
    assert [por_medicao[m]["protocolado_centavos"] for m in (a, b)] == [A, B]
    # a falta dos titulos (179.003) reparte-se 1:2 com residuo, e as partes somam a falta
    abertos = [por_medicao[m]["em_aberto_centavos"] for m in (a, b)]
    assert abertos == [59_668, 119_335] and sum(abertos) == 179_003
    assert ano["em_aberto_centavos"] == 179_003 and ano["recebido_centavos"] == NOTA - 179_003


def test_a_receber_do_inicio_conta_a_parte_da_medicao_fechada_e_o_resto_sem_medicao(cenario):
    c, cid, uid = cenario
    _liberar(c)
    a = _medicao(c, cid, 4, valor=A)
    b = _medicao(c, cid, 5, valor=B)
    nid = _cobranca(c, 856, NOTA)
    _titulo(c, nid, 279_003)                                        # titulo inteiro em aberto no RM
    # 1. so' a parte da primeira ligada: a medicao conta por ela (o valor dela) e o resto da nota, pelo titulo
    assert _rodar(c, uid, [_parte(a, "1.000,01")])["feitos"] == 1
    linhas = {(x["tipo"], x["numero"]): diretoria._a_receber_cota(x) for x in diretoria.a_receber_na_cota(c)}
    assert linhas == {("execucao", 4): A, ("execucao", 5): B, ("nota", "856"): 186_002}
    # 2. as duas ligadas e em aberto: cada medicao conta por si, a nota nao entra de novo
    assert _rodar(c, uid, [_parte(b, "2.000,02")])["feitos"] == 1
    linhas = {(x["tipo"], x["numero"]): diretoria._a_receber_cota(x) for x in diretoria.a_receber_na_cota(c)}
    assert linhas == {("execucao", 4): A, ("execucao", 5): B}
    # 3. a segunda fechada em lote (sem prova de pagamento): a parte dela do titulo aberto segue a receber pela nota
    medicoes.mudar_estado(c, uid, b, "recebida", "corte de 22/09/2026: x", None, origem="corte")
    linhas = {(x["tipo"], x["numero"]): diretoria._a_receber_cota(x) for x in diretoria.a_receber_na_cota(c)}
    assert linhas == {("execucao", 4): A, ("nota", "856"): 186_002}


def test_nota_que_volta_do_rm_nao_refaz_sozinha_o_vinculo_partilhado(cenario):
    c, cid, uid = cenario
    a, b, nid = _duas(c, cid, uid)
    with db.mutacao(c):
        sincronizacao_rm._desfazer_alocacoes_de_nf_cancelada(c, nid, "856", sincronizacao_rm.MOTIVO_EXCLUIDA_RM)
        assert sincronizacao_rm._refazer_vinculo_da_que_voltou(c, nid) is None
    motivo = json.loads(c.execute("SELECT depois FROM audit_log WHERE acao='rm.vinculo_nao_refeito'").fetchone()[0])["motivo"]
    assert "partilhada entre medições" in motivo and _ativas(c, a) == [] and _ativas(c, b) == []


# ------------------------------------------------------------------ migracao 093

@pytest.mark.migracao_real
def test_093_vinculo_existente_nasce_inteiro_e_nenhuma_linha_muda(tmp_path, monkeypatch):
    conn, pasta = _banco_antes_de(ARQUIVO, tmp_path, monkeypatch)
    with contextlib.closing(conn):
        assert "partilhada" not in [r[1] for r in conn.execute("PRAGMA table_info(nf_alocacoes)")]
        conn.execute("INSERT INTO contratos (id, orgao, numero_instrumento, objeto, valor_original_centavos, nome_curto) "
                     "VALUES (7, 'SECRETARIA DE EXEMPLO', '001/2025/00/00-EXEMPLO', 'Obra', 100000001, 'Obra 7')")
        conn.execute("INSERT INTO medicoes (id, contrato_id, numero, tipo, competencia, estado) "
                     "VALUES (11, 7, 1, 'execucao', '2026-09', 'protocolada')")
        conn.execute("INSERT INTO notas_fiscais (id, coligada, idmov, numero, numero_int, emissao, valor_centavos, situacao) "
                     "VALUES (5, 1, 901, '1', 1, '2025-07-01', 100001, 'ativa')")
        conn.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                     "VALUES (11, 5, 100001, 'manual', 't')")
        conn.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra, desfeita_em, "
                     "motivo_desfazer) VALUES (11, 5, 100001, 'detectado', 't', '2026-01-01 00:00:00', 'x')")
        conn.commit()
        antes = [dict(r) for r in conn.execute("SELECT * FROM nf_alocacoes ORDER BY id")]
        _aplicar(conn, pasta, ARQUIVO)
        depois = [dict(r) for r in conn.execute("SELECT * FROM nf_alocacoes ORDER BY id")]
        assert [d.pop("partilhada") for d in depois] == [0, 0]
        assert depois == antes and len(depois) == 2


@pytest.mark.migracao_real
def test_093_reexecutavel_sem_perder_a_marca(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()
    with contextlib.closing(conn):
        db.migrate(conn)
        conn.execute("DELETE FROM schema_migrations WHERE nome=?", (ARQUIVO,))
        conn.commit()
        db.migrate(conn)
        assert [r[1] for r in conn.execute("PRAGMA table_info(nf_alocacoes)")].count("partilhada") == 1
        with pytest.raises(Exception, match="CHECK"):
            conn.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, partilhada) "
                         "VALUES (1, 1, 1, 'manual', 2)")
