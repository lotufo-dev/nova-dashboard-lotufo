"""Atos de correcao de cadastro de 17/11/2026 (docs/adr/0006): devolver ao estado provado, reabrir no estado certo,
desfazer o recebimento sem prova. Dados ficticios (cadastro-exemplo), valores com centavo impar."""
import datetime
import json

import pytest

from app import diretoria, inicio, medicoes
from tests.test_correcao_medicoes import _ativas, _correcoes, _estado, _ligar, _medicao, _nota, _rodar, cenario  # noqa: F401

HOJE = datetime.date(2026, 11, 17)
DEVOLVER = {"operacao": "devolver", "novo": "em_analise", "data": "2026-10-02", "processo": "PROC-77/26",
            "motivo": "a carga criou como protocolada; só houve o pedido", "fonte": "carta de exemplo, protocolo de 02/10/2026"}


def _protocolo_da_nota(c, mid, data="2026-10-02", processo="PROC-77/26"):
    pid = c.execute("INSERT INTO medicao_protocolos (medicao_id, data, numero_processo, origem) VALUES (?,?,?,'manual')",
                    (mid, data, processo)).lastrowid
    c.execute("UPDATE medicoes SET congelada=1 WHERE id=?", (mid,))
    c.commit()
    return pid


def _linha(c, mid):
    return dict(c.execute("SELECT * FROM medicoes WHERE id=?", (mid,)).fetchone())


def _liberar(c):
    c.execute("INSERT OR REPLACE INTO cadastro_geral (chave, valor) VALUES ('diretoria', ?)",
              (json.dumps({"total_a_receber_liberado": True}),))
    c.commit()


# ------------------------------------------------------------------ devolver

def test_devolver_leva_a_em_analise_e_invalida_o_protocolo_sem_apagar(cenario):
    c, cid, uid = cenario
    _liberar(c)
    mid = _medicao(c, cid, 4, valor=31_207_403)
    pid = _protocolo_da_nota(c, mid)
    assert inicio._a_receber(c, HOJE)["valor_centavos"] == 31_207_403
    assert [r["id"] for r in inicio._protocoladas_dia(c)] == [mid]
    rel = _rodar(c, uid, [{**DEVOLVER, "medicao_id": mid}])
    assert rel["feitos"] == 1 and rel["erros"] == 0, rel
    m = _linha(c, mid)
    assert (m["estado"], m["congelada"], m["planilha_enviada_em"], m["planilha_envio_origem"]) == \
        ("planilha_enviada", 0, "2026-10-02", "externo")
    assert m["valor_protocolado_centavos"] == 31_207_403            # o pedido fica, congelado pelo estado
    assert m["motivo_represamento"].startswith("Devolvida (correção de cadastro): a carga criou")
    # o protocolo de nota fica no banco, marcado; o da planilha/carta entra com o processo, na data do envio
    p = dict(c.execute("SELECT * FROM medicao_protocolos WHERE id=?", (pid,)).fetchone())
    assert p["etapa"] == "nota" and p["desfeita_em"] and "carta de exemplo" in p["motivo_desfazer"]
    assert [tuple(r) for r in c.execute("SELECT etapa, data, numero_processo, desfeita_em FROM medicao_protocolos "
                                        "WHERE medicao_id=? AND id<>?", (mid, pid))] == [
        ("planilha", "2026-10-02", "PROC-77/26", None)]
    d = medicoes.detalhe(c, mid)
    assert d["protocolos"] == [] and d["planilha_siga"] == {"data": "2026-10-02", "numero": "PROC-77/26"}
    # sai do a receber e do "protocolado no dia"; continua no medido (em analise conta)
    assert inicio._a_receber(c, HOJE)["valor_centavos"] == 0
    assert inicio._protocoladas_dia(c) == []
    assert all(x["id"] != mid for x in diretoria.a_receber_na_cota(c))
    # auditoria: a mudanca de estado, o protocolo desfeito e a correcao, com motivo e fonte
    estado = [json.loads(r[0]) for r in c.execute("SELECT depois FROM audit_log WHERE acao='medicao.estado' "
                                                  "AND entidade_id=?", (str(mid),))][-1]
    assert estado["estado"] == "planilha_enviada" and estado["origem"] == "correção de cadastro"
    assert estado["fonte"] == DEVOLVER["fonte"] and estado["protocolos_desfeitos"] == [pid]
    desfeito = c.execute("SELECT antes, depois FROM audit_log WHERE acao='medicao.protocolo_desfeito' AND entidade_id=?",
                         (str(mid),)).fetchone()
    assert json.loads(desfeito[0])["data"] == "2026-10-02" and json.loads(desfeito[1])["motivo"] == DEVOLVER["motivo"]
    antes, depois = _correcoes(c, mid)[0]
    assert antes["protocolos"] == ["2026-10-02"] and depois["protocolos"] == [] and depois["operacao"] == "devolver"
    # a linha do tempo diz o protocolo como desfeito e a devolucao com o motivo
    textos = [e["texto"] for e in medicoes.edicoes_valor(c, [mid])[mid]]
    assert any(t.startswith("Protocolo da nota de 02/10/2026 desfeito pela correção de cadastro") for t in textos)
    assert any(t.startswith("Devolvida (correção de cadastro)") for t in textos)
    # rodar de novo nao duplica
    rel = _rodar(c, uid, [{**DEVOLVER, "medicao_id": mid}])
    assert rel["ja_feitos"] == 1 and c.execute("SELECT COUNT(*) FROM medicao_protocolos WHERE medicao_id=?",
                                               (mid,)).fetchone()[0] == 2


def test_devolvida_segue_pelo_fluxo_da_tela(cenario):
    """Depois do ato, o boletim do orgao entra pela regra de sempre e a medicao vai a boletim recebido."""
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4, valor=31_207_403)
    assert _rodar(c, uid, [{**DEVOLVER, "medicao_id": mid}])["feitos"] == 1
    r = medicoes.registrar_boletim(c, uid, mid, {"data": "2026-10-20", "valor_centavos": 31_207_401, "numero_orgao": "B-1"},
                                   {"arquivo": "boletins/x.pdf", "sha256": "ab" * 32})
    assert r["estado"] == "boletim_recebido" and _linha(c, mid)["valor_atestado_centavos"] == 31_207_401


def test_devolver_ao_boletim_recebido_grava_o_aprovado_como_evento(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 5, valor=1_902_355)
    op = {"operacao": "devolver", "medicao_id": mid, "novo": "boletim_recebido", "aprovado": "19.023,53",
          "data_aprovacao": "2026-07-15", "meio": "oficio", "processo": "PROC-9", "data": "2026-07-02",
          "motivo": "o órgão aprovou e a nota não saiu", "fonte": "ofício de aprovação de exemplo"}
    rel = _rodar(c, uid, [op])
    assert rel["feitos"] == 1, rel
    m = _linha(c, mid)
    assert (m["estado"], m["valor_atestado_centavos"], m["atestado_em"], m["congelada"]) == \
        ("boletim_recebido", 1_902_353, "2026-07-15", 0)
    assert m["valor_protocolado_centavos"] == 1_902_355
    assert [tuple(r) for r in c.execute("SELECT valor_centavos, meio, atestado_em, pedido_centavos FROM medicao_atestos "
                                        "WHERE medicao_id=?", (mid,))] == [(1_902_353, "oficio", "2026-07-15", 1_902_355)]
    # sem aprovado na medicao nem na operacao, nao ha' boletim a provar
    outra = _medicao(c, cid, 6)
    rel = _rodar(c, uid, [{**DEVOLVER, "medicao_id": outra, "novo": "boletim_recebido"}])
    assert rel["erros"] == 1 and "pede o valor aprovado" in rel["itens"][0]["erro"]


def test_devolver_recusa_nota_ligada_envio_pelo_sistema_recebida_e_campos_que_faltam(cenario):
    c, cid, uid = cenario
    com_nota = _medicao(c, cid, 1)
    _ligar(c, com_nota, _nota(c, 501))
    recebida = _medicao(c, cid, 2, estado="recebida")
    enviada = _medicao(c, cid, 3)
    c.execute("PRAGMA foreign_keys=OFF")
    c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem, protocolo_id) VALUES (?, '2026-10-05', 'aceito', 99)",
              (enviada,))
    c.commit()
    limpa = _medicao(c, cid, 7)
    casos = [({**DEVOLVER, "medicao_id": com_nota}, "tem nota ligada"),
             ({**DEVOLVER, "medicao_id": recebida}, "só se devolve medição protocolada"),
             ({**DEVOLVER, "medicao_id": enviada}, "enviada ao órgão pelo sistema"),
             ({k: v for k, v in DEVOLVER.items() if k != "motivo"} | {"medicao_id": limpa}, "diga o motivo"),
             ({k: v for k, v in DEVOLVER.items() if k != "data"} | {"medicao_id": limpa}, "diga a data do envio"),
             ({**DEVOLVER, "medicao_id": limpa, "novo": "prevista"}, "diga o estado que o documento prova"),
             ({**DEVOLVER, "medicao_id": limpa, "data": "2999-01-01"}, "não pode ser futura"),
             ({**DEVOLVER, "medicao_id": limpa, "aprovado": "1,00"}, "só valem com novo: boletim_recebido"),
             ({k: v for k, v in DEVOLVER.items() if k != "fonte"} | {"medicao_id": limpa}, "falta a fonte")]
    for op, erro in casos:
        rel = _rodar(c, uid, [op])
        assert rel["erros"] == 1 and erro in rel["itens"][0]["erro"], (op, rel["itens"][0])
    assert [_estado(c, x) for x in (com_nota, recebida, enviada, limpa)] == ["protocolada", "recebida", "protocolada", "protocolada"]
    assert c.execute("SELECT COUNT(*) FROM medicao_protocolos WHERE desfeita_em IS NOT NULL").fetchone()[0] == 0


def test_devolver_no_ensaio_nao_grava(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 4)
    pid = _protocolo_da_nota(c, mid)
    rel = _rodar(c, uid, [{**DEVOLVER, "medicao_id": mid}], ensaio=True)
    assert rel["feitos"] == 1 and rel["itens"][0]["depois"] == "planilha_enviada"
    assert _estado(c, mid) == "protocolada"
    assert c.execute("SELECT desfeita_em FROM medicao_protocolos WHERE id=?", (pid,)).fetchone()[0] is None


# ------------------------------------------------------------------ reabrir no estado certo

def test_reabrir_com_destino_leva_a_cancelada_direto_a_em_analise(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 7, tipo="reajuste", estado="cancelada", valor=12_750_911)
    op = {**DEVOLVER, "operacao": "reabrir", "medicao_id": mid}
    rel = _rodar(c, uid, [op])
    # o reajuste em analise e' guardado como a tela guarda: previsto, com o pedido congelado pelo marcador do envio
    assert rel["feitos"] == 1 and rel["itens"][0]["antes"] == "cancelada" and rel["itens"][0]["depois"] == "prevista"
    m = _linha(c, mid)
    assert (m["estado"], m["congelada"], m["planilha_enviada_em"], m["planilha_envio_origem"]) == \
        ("prevista", 0, "2026-10-02", "externo")
    assert m["valor_protocolado_centavos"] == 12_750_911
    with pytest.raises(ValueError, match="congelou no envio"):       # o pedido nao muda mais a' mao
        medicoes.definir_valor(c, uid, mid, "protocolado", 1, "manual")
    assert all(x["id"] != mid for x in diretoria.a_receber_na_cota(c))
    assert _rodar(c, uid, [op])["ja_feitos"] == 1


def test_reabrir_sem_destino_volta_a_protocolada_e_o_devolver_vale_em_seguida(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 7, estado="cancelada")
    ops = [{"operacao": "reabrir", "medicao_id": mid, "fonte": "carta de exemplo"}, {**DEVOLVER, "medicao_id": mid}]
    rel = _rodar(c, uid, ops)
    assert rel["feitos"] == 2 and [i["depois"] for i in rel["itens"]] == ["protocolada", "planilha_enviada"]
    assert _estado(c, mid) == "planilha_enviada"
    # o mesmo arquivo de novo: as duas ja' estao feitas (a reabertura nao vira erro por a medicao estar em analise)
    rel = _rodar(c, uid, ops)
    assert rel["ja_feitos"] == 2 and rel["erros"] == 0
    # medicao em analise que nunca foi reaberta pela correcao continua recusando o reabrir
    outra = _medicao(c, cid, 8, estado="planilha_enviada")
    rel = _rodar(c, uid, [{"operacao": "reabrir", "medicao_id": outra, "fonte": "x"}])
    assert rel["erros"] == 1 and "só se reabre medição cancelada ou desistida" in rel["itens"][0]["erro"]


def test_reabrir_recusa_campos_do_destino_sem_o_destino(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 7, estado="cancelada")
    rel = _rodar(c, uid, [{"operacao": "reabrir", "medicao_id": mid, "data": "2026-10-02", "fonte": "x"}])
    assert rel["erros"] == 1 and "só valem com o estado de destino" in rel["itens"][0]["erro"]
    rel = _rodar(c, uid, [{"operacao": "reabrir", "medicao_id": mid, "novo": "recebida", "fonte": "x"}])
    assert rel["erros"] == 1 and "novo desconhecido" in rel["itens"][0]["erro"]
    assert _estado(c, mid) == "cancelada"


# ------------------------------------------------------------------ desfazer o recebimento sem prova

DESFAZER = {"operacao": "desfazer_recebimento", "motivo": "a carta de cobrança de exemplo ainda cobra esta medição",
            "fonte": "carta de cobrança de exemplo, p. 1"}


def _titulo(c, nid, original, baixado=0, status=0):
    c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
              "status_lan, data_baixa) VALUES (1,?,?,?,?,?,?,?)",
              (5000 + nid, nid, 900, original, baixado, status, "2025-08-01" if baixado else None))
    c.commit()


def test_desfazer_recebimento_do_corte_volta_a_protocolada_e_ao_a_receber(cenario):
    c, cid, uid = cenario
    _liberar(c)
    mid = _medicao(c, cid, 9, valor=40_100_007)
    _protocolo_da_nota(c, mid, data="2024-11-30", processo=None)
    nid = _nota(c, 645, valor=40_100_007)
    c.execute("UPDATE notas_fiscais SET codtmv='2.2.01' WHERE id=?", (nid,))       # nota de cobranca ao orgao
    _ligar(c, mid, nid, valor=40_100_007)
    _titulo(c, nid, 37_052_407)                                     # o titulo, liquido, inteiro em aberto no RM
    medicoes.mudar_estado(c, uid, mid, "recebida", "corte de 22/09/2026: faturado até o QDOP conta como pago", None,
                          origem="corte")
    # recebida pelo corte com titulo aberto: o a receber conta o que falta do titulo (liquido), pela nota
    assert inicio._a_receber(c, HOJE)["valor_centavos"] == 37_052_407
    rel = _rodar(c, uid, [{**DESFAZER, "medicao_id": mid}], ensaio=True)
    assert rel["feitos"] == 1 and _estado(c, mid) == "recebida"            # o ensaio nao grava
    rel = _rodar(c, uid, [{**DESFAZER, "medicao_id": mid}])
    assert rel["feitos"] == 1 and rel["itens"][0]["antes"] == "recebida" and rel["itens"][0]["depois"] == "protocolada"
    m = _linha(c, mid)
    assert (m["estado"], m["recebida_em"], m["congelada"]) == ("protocolada", None, 1)
    assert m["motivo_represamento"].startswith("Recebimento desfeito (correção de cadastro): a carta de cobrança")
    assert _ativas(c, mid) == [nid]                                 # a nota continua ligada
    # volta a contar pela medicao (o valor dela), nao de novo pela nota
    assert inicio._a_receber(c, HOJE)["valor_centavos"] == 40_100_007
    depois = [json.loads(r[0]) for r in c.execute("SELECT depois FROM audit_log WHERE acao='medicao.estado' "
                                                  "AND entidade_id=?", (str(mid),))][-1]
    assert depois["origem"] == "correção de cadastro" and depois["fonte"] == DESFAZER["fonte"]
    assert depois["recebimento_desfeito"] == "lote"
    assert any(t.startswith("Recebimento desfeito (correção de cadastro)")
               for t in (e["texto"] for e in medicoes.edicoes_valor(c, [mid])[mid]))
    assert _rodar(c, uid, [{**DESFAZER, "medicao_id": mid}])["ja_feitos"] == 1


def test_desfazer_recebimento_da_correcao_em_lote_sem_nota(cenario):
    c, cid, uid = cenario
    mid = _medicao(c, cid, 9, valor=5_210_009)
    assert _rodar(c, uid, [{"operacao": "estado", "medicao_id": mid, "novo": "recebida", "motivo": "lote do histórico",
                            "fonte": "planilha de exemplo"}])["feitos"] == 1
    rel = _rodar(c, uid, [{**DESFAZER, "medicao_id": mid}])
    assert rel["feitos"] == 1 and _estado(c, mid) == "protocolada"
    assert any("sem NF ligada" in d for d in rel["itens"][0]["detalhes"])


def test_desfazer_recebimento_recusa_baixa_do_rm_registro_a_mao_e_nota_com_baixa(cenario):
    from app import sincronizacao_rm
    c, cid, uid = cenario
    # 1. recebida pela baixa do RM
    pelo_rm = _medicao(c, cid, 1)
    _protocolo_da_nota(c, pelo_rm)
    _ligar(c, pelo_rm, _nota(c, 501, paga=True))
    assert sincronizacao_rm._recebimentos(c) == 1 and _estado(c, pelo_rm) == "recebida"
    # 2. recebida a' mao pelo administrador (a rota de estado grava a origem "manual")
    a_mao = _medicao(c, cid, 2)
    medicoes.mudar_estado(c, uid, a_mao, "recebida", "extrato bancário de exemplo", "2026-10-10", origem="manual")
    # 3. recebida pelo corte, com a nota paga em parte no RM
    em_parte = _medicao(c, cid, 3)
    nid = _nota(c, 503)
    _ligar(c, em_parte, nid)
    _titulo(c, nid, 93_001, baixado=90_000, status=4)
    medicoes.mudar_estado(c, uid, em_parte, "recebida", "corte de 22/09/2026: x", None, origem="corte")
    c.commit()
    for mid, erro in ((pelo_rm, "recebida pela baixa do RM"), (a_mao, "recebida à mão pelo administrador"),
                      (em_parte, "tem baixa no RM")):
        rel = _rodar(c, uid, [{**DESFAZER, "medicao_id": mid}])
        assert rel["erros"] == 1 and erro in rel["itens"][0]["erro"], rel["itens"][0]
        assert _estado(c, mid) == "recebida"
    sem_motivo = {k: v for k, v in DESFAZER.items() if k != "motivo"} | {"medicao_id": em_parte}
    assert "diga o motivo" in _rodar(c, uid, [sem_motivo])["itens"][0]["erro"]
    aberta = _medicao(c, cid, 4, estado="planilha_enviada")
    erro = _rodar(c, uid, [{**DESFAZER, "medicao_id": aberta}])["itens"][0]["erro"]
    assert "só se desfaz o recebimento de medição recebida" in erro
