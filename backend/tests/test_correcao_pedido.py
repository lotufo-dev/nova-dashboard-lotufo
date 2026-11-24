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


# ------------------------------------------------------------------ issue #883: espelho que cobre so' parte da medicao

def _medicao_de_duas_fontes(c, cid, origem="espelho"):
    """Medicao recebida em duas notas, uma por fonte de recurso: o espelho e' o de uma fonte so' (R$ 6.000,03) e o
    pedido nasceu dele; a outra nota (R$ 4.000,02) foi ligada depois. O aprovado e' a soma (R$ 10.000,05)."""
    mid = _medicao(c, cid, 22, estado="recebida", valor=600_003)
    c.execute("UPDATE medicoes SET congelada=1, valor_protocolado_origem=? WHERE id=?", (origem, mid))
    c.commit()
    eid = _espelho(c, cid, mid, 22, 600_003)
    _aprovar(c, mid, 1_000_005)                    # depois do espelho: o espelho saiu do pedido
    na, nb = _nota(c, 801, valor=600_003), _nota(c, 802, valor=400_002)
    _ligar(c, mid, na, valor=600_003)
    _ligar(c, mid, nb, valor=400_002)
    return mid, eid, na, nb


def _op_parcial(mid, pedido="10.000,05", **extra):
    return _op(mid, pedido=pedido, espelho_parcial=True, motivo="a medição saiu em duas notas, uma por fonte",
               **extra)


def test_espelho_parcial_corrige_com_a_soma_das_notas_e_audita_a_declaracao(cenario):
    c, cid, uid = cenario
    mid, eid, na, nb = _medicao_de_duas_fontes(c, cid)
    esp_antes = c.execute("SELECT * FROM espelho_medicoes WHERE espelho_id=?", (eid,)).fetchall()
    rel = _rodar(c, uid, [_op_parcial(mid)])
    assert rel["feitos"] == 1 and rel["erros"] == 0, rel
    linha = _linha(c, mid)
    assert (linha["valor_protocolado_centavos"], linha["valor_protocolado_origem"]) == (1_000_005, "manual")
    assert linha["estado"] == "recebida" and linha["congelada"] == 1 and linha["valor_atestado_centavos"] == 1_000_005
    # o espelho nao muda
    assert [tuple(r) for r in c.execute("SELECT * FROM espelho_medicoes WHERE espelho_id=?", (eid,))] \
        == [tuple(r) for r in esp_antes]
    assert _ativas(c, mid) == [na, nb]
    _, d = _correcoes(c, mid)[0]
    assert (d["pedido_antes_centavos"], d["pedido_depois_centavos"], d["origem_antes"]) == (600_003, 1_000_005, "espelho")
    assert d["fonte"] == FONTE and d["motivo_correcao"] == "a medição saiu em duas notas, uma por fonte"
    p = d["espelho_parcial"]
    assert p["declarado"] is True and p["soma_centavos"] == 1_000_005 and p["coligada"] == 1
    assert [(n["nota_id"], n["valor_vinculo_centavos"]) for n in p["notas_somadas"]] == [(na, 600_003), (nb, 400_002)]
    assert len(p["recusas_vencidas"]) == 2
    assert "veio do espelho" in p["recusas_vencidas"][0] and "gerado a partir do pedido" in p["recusas_vencidas"][1]
    assert p["espelhos"] == [{"versao": 1, "situacao": "vigente", "valor_centavos": 600_003, "origem": "coluna"}]


def test_espelho_parcial_o_ensaio_diz_a_recusa_vencida_e_nao_grava(cenario):
    c, cid, uid = cenario
    mid, _, _, _ = _medicao_de_duas_fontes(c, cid)
    n = _auditorias(c, mid)
    rel = _rodar(c, uid, [_op_parcial(mid)], ensaio=True)
    assert rel["ensaio"] and rel["feitos"] == 1, rel
    detalhes = rel["itens"][0]["detalhes"]
    assert detalhes[0] == "pedido R$ 6.000,03 → R$ 10.000,05 (valor cheio)"
    assert detalhes[1].startswith("espelho_parcial declarado: vence a recusa “o pedido desta medição veio do espelho")
    assert "” e a recusa “o espelho versão 1 desta medição foi gerado a partir do pedido" in detalhes[1]
    assert detalhes[2] == ("o pedido novo é a soma das notas ligadas: NF 801, idmov 1701 (R$ 6.000,03) + NF 802, "
                           "idmov 1702 (R$ 4.000,02) = R$ 10.000,05")
    assert detalhes[3] == "o espelho versão 1 leva R$ 6.000,03 e não muda: é a parte da NF 801, idmov 1701 (R$ 6.000,03)"
    assert not any(d.startswith("AVISO: o valor do espelho") for d in detalhes)
    assert any("a diferença aprovado − pedido passa de R$ 4.000,02 para R$ 0,00" in d for d in detalhes)
    assert _linha(c, mid)["valor_protocolado_centavos"] == 600_003
    assert _auditorias(c, mid) == n


def test_espelho_parcial_segunda_rodada_ja_feito(cenario):
    c, cid, uid = cenario
    mid, _, _, _ = _medicao_de_duas_fontes(c, cid)
    assert _rodar(c, uid, [_op_parcial(mid)])["feitos"] == 1
    n = _auditorias(c, mid)
    rel = _rodar(c, uid, [_op_parcial(mid)])
    assert rel["ja_feitos"] == 1 and rel["feitos"] == 0 and rel["erros"] == 0, rel
    assert "já é R$ 10.000,05" in rel["itens"][0]["detalhes"][0]
    assert _auditorias(c, mid) == n


def test_sem_a_declaracao_as_recusas_de_hoje_continuam(cenario):
    c, cid, uid = cenario
    mid, _, _, _ = _medicao_de_duas_fontes(c, cid)
    for op in (_op(mid, pedido="10.000,05"), _op(mid, pedido="10.000,05", espelho_parcial=False)):
        rel = _rodar(c, uid, [op])
        assert rel["erros"] == 1, rel
        assert rel["itens"][0]["erro"] == ("o pedido desta medição veio do espelho: o espelho é documento que saiu, e "
                                           "o valor dele muda gerando o espelho de novo (antes do protocolo), não por aqui")
    # pedido de outra origem com espelho gerado dele: a segunda recusa, a de hoje
    c.execute("UPDATE medicoes SET valor_protocolado_origem='manual' WHERE id=?", (mid,))
    c.commit()
    rel = _rodar(c, uid, [_op(mid, pedido="10.000,05")])
    assert rel["erros"] == 1 and rel["itens"][0]["erro"] == (
        "o espelho versão 1 desta medição foi gerado a partir do pedido (R$ 6.000,03), sem boletim: o espelho é "
        "documento que saiu e ficaria com um valor que não é mais o pedido"), rel
    assert _linha(c, mid)["valor_protocolado_centavos"] == 600_003
    assert _correcoes(c, mid) == []


def test_espelho_parcial_em_medicao_que_nao_se_enquadra_e_recusado(cenario):
    c, cid, uid = cenario
    mid, _, _, nb = _medicao_de_duas_fontes(c, cid)
    # soma diferente: nem o valor de uma nota, nem outro valor qualquer
    for pedido in ("4.000,02", "10.000,07"):
        rel = _rodar(c, uid, [_op_parcial(mid, pedido=pedido)])
        assert rel["erros"] == 1, rel
        erro = rel["itens"][0]["erro"]
        assert "com espelho_parcial o pedido é a soma das notas vigentes ligadas" in erro, erro
        assert "= R$ 10.000,05" in erro
    # declaracao que nao e' true/false
    rel = _rodar(c, uid, [_op(mid, pedido="10.000,05", espelho_parcial="sim")])
    assert rel["erros"] == 1 and "espelho_parcial deve ser true ou false" in rel["itens"][0]["erro"], rel
    # uma nota so': a outra desligada nao conta
    c.execute("UPDATE nf_alocacoes SET desfeita_em=datetime('now') WHERE medicao_id=? AND nota_id=?", (mid, nb))
    c.commit()
    rel = _rodar(c, uid, [_op_parcial(mid, pedido="6.000,05")])
    assert rel["erros"] == 1 and "só vale na medição com mais de uma nota ligada" in rel["itens"][0]["erro"], rel
    assert _linha(c, mid)["valor_protocolado_centavos"] == 600_003
    assert _correcoes(c, mid) == []


def test_espelho_parcial_sem_recusa_a_vencer_e_recusado(cenario):
    """Sem espelho (ou com espelho do aprovado e pedido de outra origem) nao ha' recusa do espelho: a declaracao nao
    se aplica e sairia como registro falso na auditoria."""
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, estado="recebida", valor=600_003)
    _aprovar(c, mid, 1_000_005)
    _ligar(c, mid, _nota(c, 811, valor=600_003), valor=600_003)
    _ligar(c, mid, _nota(c, 812, valor=400_002), valor=400_002)
    rel = _rodar(c, uid, [_op_parcial(mid)])
    assert rel["erros"] == 1 and "esta medição não tem nenhuma: tire espelho_parcial" in rel["itens"][0]["erro"], rel
    assert _linha(c, mid)["valor_protocolado_centavos"] == 600_003


def test_espelho_parcial_recusa_espelho_que_nao_e_parte(cenario):
    """O espelho que ja' leva o valor inteiro (ou mais) nao cobre so' parte da medicao: a declaracao e' falsa."""
    c, cid, uid = cenario
    mid, eid, _, _ = _medicao_de_duas_fontes(c, cid)
    c.execute("UPDATE espelho_medicoes SET valor_centavos=1000005, valor_com_sinal_centavos=1000005 WHERE espelho_id=?",
              (eid,))
    c.commit()
    rel = _rodar(c, uid, [_op_parcial(mid)])
    assert rel["erros"] == 1, rel
    assert "o espelho versão 1 leva R$ 10.000,05, não uma parte de R$ 10.000,05" in rel["itens"][0]["erro"]
    assert _linha(c, mid)["valor_protocolado_centavos"] == 600_003


def test_espelho_parcial_avisa_espelho_que_nao_bate_com_nota(cenario):
    c, cid, uid = cenario
    mid, eid, _, _ = _medicao_de_duas_fontes(c, cid)
    c.execute("UPDATE espelho_medicoes SET valor_centavos=500001, valor_com_sinal_centavos=500001 WHERE espelho_id=?",
              (eid,))
    c.commit()
    rel = _rodar(c, uid, [_op_parcial(mid)], ensaio=True)
    assert rel["feitos"] == 1, rel
    assert any(d.startswith("AVISO: o valor do espelho versão 1 não bate com nenhuma das notas somadas")
               for d in rel["itens"][0]["detalhes"])


def test_espelho_parcial_nao_soma_notas_de_coligadas_diferentes(cenario):
    """Consorcio: a fatura do consorcio (coligada 90) e a NF da Lotufo (coligada 1) cobrem a mesma medicao, uma o
    cheio e a outra a cota. Duas notas ligadas, mas nao duas fontes: a soma e' por coligada."""
    from tests.test_correcao_medicoes import _nota_col
    c, cid, uid = cenario
    mid, _, na, nb = _medicao_de_duas_fontes(c, cid)
    c.execute("UPDATE nf_alocacoes SET desfeita_em=datetime('now') WHERE medicao_id=? AND nota_id=?", (mid, nb))
    _ligar(c, mid, _nota_col(c, 803, 90, 400_002), valor=400_002)
    rel = _rodar(c, uid, [_op_parcial(mid)])
    assert rel["erros"] == 1, rel
    erro = rel["itens"][0]["erro"]
    assert "coligada 1: NF 801, idmov 1701 (R$ 6.000,03) = R$ 6.000,03" in erro and "coligada 90:" in erro, erro
    assert _linha(c, mid)["valor_protocolado_centavos"] == 600_003


# ------------------------------------------------------------------ #883, ensaio na producao: espelho sem valor gravado

REGRA_DUAS_FONTES = {"entradas": [{"chave": "fonte-a", "natureza": "medicao", "rotulo": "Fonte A"},
                                  {"chave": "fonte-b", "natureza": "medicao", "rotulo": "Fonte B"},
                                  {"chave": "reajuste", "natureza": "reajuste", "rotulo": "Reajuste"}]}


def _so_nas_entradas(c, cid, eid, entradas, sha_espelho="sha-exemplo", sha_regra="sha-exemplo"):
    """O espelho de antes da coluna 065: `espelho_medicoes` sem valor e o valor so' nas entradas do proprio espelho,
    lidas pela regra da obra (de mesmo sha256, ou de outro, quando a regra mudou depois)."""
    c.execute("UPDATE espelho_medicoes SET valor_centavos=NULL, valor_com_sinal_centavos=NULL WHERE espelho_id=?",
              (eid,))
    c.execute("UPDATE espelhos SET entradas=?, regra_sha256=? WHERE id=?", (json.dumps(entradas), sha_espelho, eid))
    c.execute("INSERT OR REPLACE INTO espelho_regras (contrato_id, situacao, regra, modelos, sha256) "
              "VALUES (?,'ativa',?,'{}',?)", (cid, json.dumps(REGRA_DUAS_FONTES), sha_regra))
    c.commit()


def test_espelho_parcial_le_o_valor_das_entradas_do_espelho_sem_valor_gravado(cenario):
    """O caso da producao: as duas colunas de `espelho_medicoes` nulas e o valor do espelho so' nas entradas dele. A
    declaracao passa, o ensaio diz de onde leu e a auditoria guarda a origem."""
    c, cid, uid = cenario
    mid, eid, na, nb = _medicao_de_duas_fontes(c, cid)
    _so_nas_entradas(c, cid, eid, {"fonte-a": 600_003})
    rel = _rodar(c, uid, [_op_parcial(mid)], ensaio=True)
    assert rel["feitos"] == 1 and rel["erros"] == 0, rel
    detalhes = rel["itens"][0]["detalhes"]
    assert ("o espelho versão 1 leva R$ 6.000,03 (lido das entradas do espelho) e não muda: é a parte da NF 801, "
            "idmov 1701 (R$ 6.000,03)") in detalhes, detalhes
    assert not any(d.startswith("AVISO: o valor do espelho") for d in detalhes)
    assert _linha(c, mid)["valor_protocolado_centavos"] == 600_003
    rel = _rodar(c, uid, [_op_parcial(mid)])
    assert rel["feitos"] == 1 and rel["erros"] == 0, rel
    assert _linha(c, mid)["valor_protocolado_centavos"] == 1_000_005
    _, d = _correcoes(c, mid)[0]
    assert d["espelho_parcial"]["espelhos"] == [{"versao": 1, "situacao": "vigente", "valor_centavos": 600_003,
                                                 "origem": "entradas"}]
    # o espelho nao muda: segue sem valor gravado
    assert tuple(c.execute("SELECT valor_centavos, valor_com_sinal_centavos FROM espelho_medicoes WHERE espelho_id=?",
                           (eid,)).fetchone()) == (None, None)


def test_espelho_parcial_das_entradas_que_leva_o_valor_inteiro_e_recusado(cenario):
    c, cid, uid = cenario
    mid, eid, _, _ = _medicao_de_duas_fontes(c, cid)
    _so_nas_entradas(c, cid, eid, {"fonte-a": 600_003, "fonte-b": 400_002})
    rel = _rodar(c, uid, [_op_parcial(mid)])
    assert rel["erros"] == 1, rel
    assert "o espelho versão 1 leva R$ 10.000,05, não uma parte de R$ 10.000,05" in rel["itens"][0]["erro"]
    assert _linha(c, mid)["valor_protocolado_centavos"] == 600_003


def test_espelho_parcial_espelho_sem_valor_em_lugar_nenhum_e_recusado(cenario):
    """Sem valor na coluna e sem valor da medicao nas entradas (ou com a regra da obra mudada depois do espelho, que
    deixa as entradas sem dizer de qual medicao e' cada valor): nao se adivinha, recusa."""
    c, cid, uid = cenario
    mid, eid, _, _ = _medicao_de_duas_fontes(c, cid)
    _so_nas_entradas(c, cid, eid, {"reajuste": 50_001})
    rel = _rodar(c, uid, [_op_parcial(mid)])
    assert rel["erros"] == 1, rel
    erro = rel["itens"][0]["erro"]
    assert erro.startswith("espelho_parcial diz que o espelho cobre só parte da medição, e o espelho versão 1 não tem "
                           "o valor desta medição gravado nem lido das entradas dele (as entradas do espelho não têm "
                           "valor de execução)"), erro
    _so_nas_entradas(c, cid, eid, {"fonte-a": 600_003}, sha_regra="sha-regra-nova")
    rel = _rodar(c, uid, [_op_parcial(mid)])
    assert rel["erros"] == 1, rel
    assert "(a regra do espelho da obra não é mais a que gerou este espelho" in rel["itens"][0]["erro"]
    c.execute("DELETE FROM espelho_regras WHERE contrato_id=?", (cid,))
    c.commit()
    rel = _rodar(c, uid, [_op_parcial(mid)])
    assert rel["erros"] == 1 and "a regra do espelho da obra não é mais" in rel["itens"][0]["erro"], rel
    assert _linha(c, mid)["valor_protocolado_centavos"] == 600_003
    assert _correcoes(c, mid) == []


def test_espelho_parcial_espelho_de_execucao_e_reajuste_sem_valor_por_medicao(cenario):
    """Espelho que leva a execucao e o reajuste, sem valor por medicao na coluna: as entradas, pela regra que gerou o
    espelho, separam o valor de cada medicao pela natureza (so' a execucao conta). Com a regra mudada, nao da' para
    saber quanto e' de cada uma: recusa, dizendo que o espelho leva tambem o reajuste."""
    c, cid, uid = cenario
    mid, eid, _, _ = _medicao_de_duas_fontes(c, cid)
    rid = _medicao(c, cid, 22, estado="recebida", tipo="reajuste", valor=50_001)
    c.execute("INSERT INTO espelho_medicoes (espelho_id, medicao_id) VALUES (?,?)", (eid, rid))
    _so_nas_entradas(c, cid, eid, {"fonte-a": 600_003, "reajuste": 50_001})
    rel = _rodar(c, uid, [_op_parcial(mid)], ensaio=True)
    assert rel["feitos"] == 1 and rel["erros"] == 0, rel
    assert any(d.startswith("o espelho versão 1 leva R$ 6.000,03 (lido das entradas do espelho) e não muda: é a parte "
                            "da NF 801") for d in rel["itens"][0]["detalhes"]), rel
    _so_nas_entradas(c, cid, eid, {"fonte-a": 600_003, "reajuste": 50_001}, sha_regra="sha-regra-nova")
    rel = _rodar(c, uid, [_op_parcial(mid)])
    assert rel["erros"] == 1, rel
    erro = rel["itens"][0]["erro"]
    assert "a regra do espelho da obra não é mais a que gerou este espelho" in erro, erro
    assert "; ele leva também a medição de reajuste)" in erro, erro
    assert _linha(c, mid)["valor_protocolado_centavos"] == 600_003


def test_sem_a_declaracao_espelho_sem_valor_gravado_recusa_como_sempre(cenario):
    c, cid, uid = cenario
    mid, eid, _, _ = _medicao_de_duas_fontes(c, cid)
    _so_nas_entradas(c, cid, eid, {"fonte-a": 600_003})
    rel = _rodar(c, uid, [_op(mid, pedido="10.000,05")])
    assert rel["erros"] == 1 and rel["itens"][0]["erro"] == (
        "o pedido desta medição veio do espelho: o espelho é documento que saiu, e o valor dele muda gerando o "
        "espelho de novo (antes do protocolo), não por aqui"), rel
    assert _linha(c, mid)["valor_protocolado_centavos"] == 600_003
