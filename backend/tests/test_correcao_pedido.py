"""Issue #863: `corrigir_pedido` no `cadastro corrigir-medicoes`. Dados ficticios (cadastro-exemplo), valores
inventados com centavo impar."""
import json

from app import medicoes
from tests.test_correcao_medicoes import _ativas, _correcoes, _estado, _ligar, _medicao, _nota, _rodar, cenario  # noqa: F401

FONTE = "planilha de exemplo enviada ao órgão em 03/09/2026"
MOTIVO = "a carga gravou o valor da revisão e não o da primeira planilha"


def _op(mid, pedido="12.345,67", **extra):
    return {"operacao": "corrigir_pedido", "medicao_id": mid, "pedido": pedido, "motivo": MOTIVO, "fonte": FONTE,
            **extra}


def _linha(c, mid):
    return dict(c.execute("SELECT * FROM medicoes WHERE id=?", (mid,)).fetchone())


def _aprovar(c, mid, valor, pedido=None, arquivo=None, criado_em=None):
    aid = c.execute("INSERT INTO medicao_atestos (medicao_id, valor_centavos, origem, atestado_em, meio, arquivo, "
                    "pedido_centavos, criado_em) VALUES (?,?,'manual','2026-09-20',?,?,?,COALESCE(?, datetime('now')))",
                    (mid, valor, "oficio" if arquivo else None, arquivo, pedido, criado_em)).lastrowid
    c.execute("UPDATE medicoes SET valor_atestado_centavos=?, valor_atestado_origem='manual', atestado_em='2026-09-20' "
              "WHERE id=?", (valor, mid))
    c.commit()
    return aid


def _espelho(c, cid, mid, numero, valor, criado_em="2026-09-25 10:00:00", versao=1):
    uid = c.execute("SELECT id FROM usuarios LIMIT 1").fetchone()[0]
    eid = c.execute("INSERT INTO espelhos (contrato_id, numero, competencia, versao, situacao, entradas, saidas, "
                    "regra_sha256, criado_por, criado_em) VALUES (?,?,'2025-06',?,'vigente','{}','[]','x',?,?)",
                    (cid, numero, versao, uid, criado_em)).lastrowid
    c.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id, valor_centavos, valor_com_sinal_centavos) "
              "VALUES (?,?,?,?)", (eid, mid, valor if valor >= 0 else None, valor))
    c.commit()
    return eid


def _auditorias(c, mid):
    return c.execute("SELECT COUNT(*) FROM audit_log WHERE entidade='medicao' AND entidade_id=?", (str(mid),)).fetchone()[0]


# ------------------------------------------------------------------ o ato

def test_corrige_o_pedido_de_medicao_congelada_e_recebida_com_auditoria(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="recebida", valor=1_000_001)
    c.execute("UPDATE medicoes SET congelada=1, valor_protocolado_origem='aceito' WHERE id=?", (mid,))
    c.commit()
    nid = _nota(c, 701, valor=1_000_001)
    _ligar(c, mid, nid, valor=1_000_001)
    _aprovar(c, mid, 1_234_565)
    antes = _linha(c, mid)
    rel = _rodar(c, uid, [_op(mid)])
    assert rel["feitos"] == 1 and rel["erros"] == 0, rel
    depois = _linha(c, mid)
    assert depois["valor_protocolado_centavos"] == 1_234_567 and depois["valor_protocolado_origem"] == "manual"
    # nada mais muda: estado, congelamento, aprovado, notas
    for col in ("estado", "congelada", "valor_atestado_centavos", "atestado_em", "recebida_em", "competencia"):
        assert depois[col] == antes[col], col
    assert _ativas(c, mid) == [nid]
    a, d = _correcoes(c, mid)[0]
    assert (a["valor_protocolado_centavos"], a["valor_protocolado_origem"]) == (1_000_001, "aceito")
    assert (d["valor_protocolado_centavos"], d["valor_protocolado_origem"]) == (1_234_567, "manual")
    assert d["operacao"] == "corrigir_pedido" and d["origem"] == "correção de cadastro"
    assert d["motivo_correcao"] == MOTIVO and d["fonte"] == FONTE
    assert d["motivo"] == a["motivo"]               # o motivo do represamento (da foto) nao muda
    assert (d["pedido_antes_centavos"], d["pedido_depois_centavos"], d["origem_antes"]) == (1_000_001, 1_234_567, "aceito")
    # correcao silenciosa: nenhum evento de valor na linha do tempo
    assert not c.execute("SELECT 1 FROM audit_log WHERE acao='medicao.valor_protocolado' AND entidade_id=?",
                         (str(mid),)).fetchone()
    assert not any("protocolado" in e["texto"].lower() for e in medicoes.edicoes_valor(c, [mid])[mid])


def test_por_obra_numero_e_tipo_e_reajuste_negativo(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 2, tipo="reajuste", estado="nf_emitida", valor=123_457)
    rel = _rodar(c, uid, [{"operacao": "corrigir_pedido", "obra": "obra propria", "numero": 2, "tipo": "reajuste",
                           "pedido": "-1.234,57", "motivo": "o reajuste negativo entrou sem sinal", "fonte": FONTE}])
    assert rel["feitos"] == 1, rel
    assert _linha(c, mid)["valor_protocolado_centavos"] == -123_457


def test_segunda_rodada_ja_feito_sem_linha_nova_na_auditoria(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, valor=1_000_001)
    assert _rodar(c, uid, [_op(mid)])["feitos"] == 1
    n = _auditorias(c, mid)
    rel = _rodar(c, uid, [_op(mid)])
    assert rel["ja_feitos"] == 1 and rel["feitos"] == 0 and rel["erros"] == 0
    assert "já é R$ 12.345,67" in rel["itens"][0]["detalhes"][0]
    assert _auditorias(c, mid) == n


def test_ensaio_nao_grava_e_relata_antes_depois_e_a_diferenca(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="boletim_recebido", valor=1_000_001)
    _aprovar(c, mid, 1_234_565)
    n = _auditorias(c, mid)
    rel = _rodar(c, uid, [_op(mid)], ensaio=True)
    assert rel["ensaio"] and rel["feitos"] == 1, rel
    detalhes = rel["itens"][0]["detalhes"]
    assert detalhes[0] == "pedido R$ 10.000,01 → R$ 12.345,67 (valor cheio)"
    assert detalhes[1] == ("aprovado R$ 12.345,65: a diferença aprovado − pedido passa de R$ 2.345,64 para "
                           "-R$ 0,02")
    assert _linha(c, mid)["valor_protocolado_centavos"] == 1_000_001
    assert _auditorias(c, mid) == n


def test_aviso_quando_a_diferenca_aceita_era_do_pedido_antigo(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="boletim_recebido", valor=1_000_003)
    aid = _aprovar(c, mid, 1_000_001, pedido=1_000_003, arquivo="boletins/exemplo.pdf")
    medicoes.aceitar_diferenca(c, uid, mid, "glosa de dois centavos aceita")
    assert medicoes.diferenca_aceita(c, mid) is not None
    rel = _rodar(c, uid, [_op(mid, pedido="10.000,05")])
    assert rel["feitos"] == 1, rel
    assert any(d.startswith("AVISO: a diferença aceita do boletim era a do pedido antigo") for d in rel["itens"][0]["detalhes"])
    assert medicoes.diferenca_aceita(c, mid) is None      # a aceitacao continua no banco, mas nao vale para o pedido novo
    assert c.execute("SELECT COUNT(*) FROM medicao_diferencas_aceitas WHERE atesto_id=?", (aid,)).fetchone()[0] == 1


def test_boletim_da_linha_do_tempo_diz_o_pedido_corrigido(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="boletim_recebido", valor=1_000_001)
    _aprovar(c, mid, 1_234_565, pedido=1_000_001, arquivo="boletins/exemplo.pdf")
    texto = next(e["texto"] for e in medicoes.edicoes_valor(c, [mid])[mid] if e["texto"].startswith("Boletim"))
    assert "pedido R$ 10.000,01" in texto
    assert _rodar(c, uid, [_op(mid)])["feitos"] == 1
    texto = next(e["texto"] for e in medicoes.edicoes_valor(c, [mid])[mid] if e["texto"].startswith("Boletim"))
    assert "aprovado R$ 12.345,65, pedido R$ 12.345,67, diferença -R$ 0,02" in texto and "correção" not in texto
    # o evento de atesto nao muda (append-only): so' a leitura troca o pedido
    assert c.execute("SELECT pedido_centavos FROM medicao_atestos WHERE medicao_id=?", (mid,)).fetchone()[0] == 1_000_001


def test_pedido_corrigido_vale_na_diferenca_do_fechamento(cenario):
    """O Fechamento, o Resumo e a fila leem o pedido da medicao, sem copia: a diferenca nova aparece."""
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="boletim_recebido", valor=1_000_001)
    _aprovar(c, mid, 1_234_565)
    assert _rodar(c, uid, [_op(mid)])["feitos"] == 1
    d = medicoes.detalhe(c, mid)
    assert d["valor_protocolado_centavos"] == 1_234_567


# ------------------------------------------------------------------ recusas

def test_recusa_sem_motivo_sem_fonte_valor_ilegivel_e_negativo_fora_de_reajuste(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, valor=1_000_001)
    casos = [
        ({k: v for k, v in _op(mid).items() if k != "motivo"}, "diga o motivo"),
        ({k: v for k, v in _op(mid).items() if k != "fonte"}, "falta a fonte"),
        ({k: v for k, v in _op(mid).items() if k != "pedido"}, "diga o pedido certo"),
        (_op(mid, pedido="doze mil"), "pedido: 'doze mil'"),
        (_op(mid, pedido=12345.67), "escreva entre aspas"),
        (_op(mid, pedido="-1.000,01"), "não aceita valor negativo"),
        (_op(mid, campo_estranho=1), "campo que corrigir_pedido não usa"),
    ]
    for op, erro in casos:
        rel = _rodar(c, uid, [op])
        assert rel["erros"] == 1 and erro in rel["itens"][0]["erro"], (op, rel)
    assert _linha(c, mid)["valor_protocolado_centavos"] == 1_000_001
    assert _correcoes(c, mid) == []


def test_recusa_cancelada_e_desistida(cenario):
    c, cid, uid = cenario
    for n, estado in ((5, "cancelada"), (6, "desistida")):
        mid = _medicao(c, cid, n, estado=estado, valor=1_000_001)
        rel = _rodar(c, uid, [_op(mid)])
        assert rel["erros"] == 1 and "não tem pedido a corrigir" in rel["itens"][0]["erro"], rel
        assert _linha(c, mid)["valor_protocolado_centavos"] == 1_000_001


def test_recusa_medicao_com_espelho_gerado_do_pedido(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="protocolada", valor=1_000_001)
    _espelho(c, cid, mid, 4, 1_000_001)
    rel = _rodar(c, uid, [_op(mid)])
    assert rel["erros"] == 1 and "espelho versão 1 desta medição foi gerado a partir do pedido" in rel["itens"][0]["erro"]
    # boletim que chegou depois do espelho nao muda o fato: o espelho saiu do pedido
    _aprovar(c, mid, 1_234_565, criado_em="2026-09-30 10:00:00")
    rel = _rodar(c, uid, [_op(mid)])
    assert rel["erros"] == 1 and "gerado a partir do pedido" in rel["itens"][0]["erro"]
    assert _linha(c, mid)["valor_protocolado_centavos"] == 1_000_001


def test_espelho_gerado_do_aprovado_nao_impede(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="protocolada", valor=1_000_001)
    _aprovar(c, mid, 1_234_565, criado_em="2026-09-20 10:00:00")
    _espelho(c, cid, mid, 4, 1_234_565, criado_em="2026-09-25 10:00:00")
    rel = _rodar(c, uid, [_op(mid)])
    assert rel["feitos"] == 1, rel
    assert _linha(c, mid)["valor_protocolado_centavos"] == 1_234_567


def test_recusa_pedido_que_veio_do_espelho(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="espelho_gerado", valor=1_000_001)
    c.execute("UPDATE medicoes SET valor_protocolado_origem='espelho' WHERE id=?", (mid,))
    c.commit()
    rel = _rodar(c, uid, [_op(mid)])
    assert rel["erros"] == 1 and "veio do espelho" in rel["itens"][0]["erro"], rel


def test_planilha_do_sistema_so_aceita_o_valor_de_uma_versao(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="protocolada", valor=1_000_003)
    for versao, valor in ((1, 1_000_001), (2, 1_000_003)):
        c.execute("INSERT INTO medicao_planilhas (medicao_id, versao, valor_pedido_centavos, acumulado_anterior_centavos, "
                  "origem, motivo) VALUES (?,?,?,0,'manual',?)", (mid, versao, valor, None if versao == 1 else "revisão"))
    c.commit()
    rel = _rodar(c, uid, [_op(mid, pedido="10.000,05")])
    assert rel["erros"] == 1, rel
    erro = rel["itens"][0]["erro"]
    assert "versão 1: R$ 10.000,01; versão 2: R$ 10.000,03" in erro and "R$ 10.000,05 não é o de nenhuma versão" in erro
    # a primeira planilha enviada (a decisao do dono) e' aceita
    rel = _rodar(c, uid, [_op(mid, pedido="10.000,01")])
    assert rel["feitos"] == 1, rel
    assert _linha(c, mid)["valor_protocolado_centavos"] == 1_000_001


def test_operacao_invalida_recusa_o_arquivo_inteiro(cenario):
    c, cid, uid = cenario
    boa = _medicao(c, cid, 4, valor=1_000_001)
    cancelada = _medicao(c, cid, 5, estado="cancelada", valor=1_000_001)
    rel = _rodar(c, uid, [_op(boa), _op(cancelada)])
    assert rel["erros"] == 1 and rel["itens"][0]["situacao"] == "feito"
    assert _linha(c, boa)["valor_protocolado_centavos"] == 1_000_001
    assert _estado(c, boa) == "protocolada"
    assert json.dumps(rel, ensure_ascii=False)        # o relatorio se imprime


# ------------------------------------------------------------------ revisao independente (segunda rodada)

def test_sem_aprovado_com_nota_ligada_o_pedido_tem_de_ser_o_que_a_nota_cobre(cenario):
    """Sem boletim, o pedido faz as vezes do aprovado contra a nota (Fechamento, nota acima da medicao, cobertura do
    recebimento): o pedido que a nota nao cobre e' recusado; o que ela cobre passa, com o aviso do Fechamento."""
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="nf_emitida", valor=900_001)
    _ligar(c, mid, _nota(c, 702, valor=1_000_001), valor=1_000_001)
    rel = _rodar(c, uid, [_op(mid, pedido="9.500,01")])
    assert rel["erros"] == 1 and "não tem aprovado e tem nota ligada" in rel["itens"][0]["erro"], rel
    assert _linha(c, mid)["valor_protocolado_centavos"] == 900_001
    rel = _rodar(c, uid, [_op(mid, pedido="10.000,01")])
    assert rel["feitos"] == 1, rel
    assert any("o Fechamento conta o pedido como aprovado: passa a contar R$ 10.000,01" in d
               for d in rel["itens"][0]["detalhes"])
    assert _linha(c, mid)["valor_protocolado_centavos"] == 1_000_001


def test_com_aprovado_a_nota_nao_impede(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="nf_emitida", valor=900_001)
    _aprovar(c, mid, 1_000_001)
    _ligar(c, mid, _nota(c, 703, valor=1_000_001), valor=1_000_001)
    assert _rodar(c, uid, [_op(mid, pedido="9.500,01")])["feitos"] == 1


def test_recusa_valor_sem_aspas_e_pedido_zero(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, valor=1_000_001)
    for pedido, erro in ((12345, "escreva entre aspas"), ("0,00", "pedido zero não é pedido"),
                         ("-0,00", "pedido zero não é pedido")):
        rel = _rodar(c, uid, [_op(mid, pedido=pedido)])
        assert rel["erros"] == 1 and erro in rel["itens"][0]["erro"], (pedido, rel)
    assert _linha(c, mid)["valor_protocolado_centavos"] == 1_000_001


def test_planilha_ainda_nao_enviada_recusa(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="planilha_gerada", valor=1_000_003)
    c.execute("INSERT INTO medicao_planilhas (medicao_id, versao, valor_pedido_centavos, acumulado_anterior_centavos, "
              "origem) VALUES (?,1,1000001,0,'manual')", (mid,))
    c.commit()
    rel = _rodar(c, uid, [_op(mid, pedido="10.000,01")])
    assert rel["erros"] == 1 and "ainda não foi enviada" in rel["itens"][0]["erro"], rel


def test_ensaio_avisa_a_leitura_por_grupo_do_pedido_antigo(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, valor=1_000_001)
    c.execute("INSERT INTO medicao_grupos (medicao_id, origem, sha256, situacao, total_centavos, pedido_centavos) "
              "VALUES (?, 'carga', 'ab', 'lida', 1000001, 1000001)", (mid,))
    c.commit()
    rel = _rodar(c, uid, [_op(mid)], ensaio=True)
    assert any(d.startswith("AVISO: a leitura por grupo") for d in rel["itens"][0]["detalhes"]), rel


def test_boletim_registrado_depois_da_correcao_nao_e_trocado(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="boletim_recebido", valor=1_000_001)
    assert _rodar(c, uid, [_op(mid)])["feitos"] == 1
    # um boletim posterior que, por outro caminho, guardou o pedido antigo continua dizendo o que guardou
    _aprovar(c, mid, 1_234_565, pedido=1_000_001, arquivo="boletins/exemplo.pdf", criado_em="2999-01-01 00:00:00")
    texto = next(e["texto"] for e in medicoes.edicoes_valor(c, [mid])[mid] if e["texto"].startswith("Boletim"))
    assert "pedido R$ 10.000,01" in texto
