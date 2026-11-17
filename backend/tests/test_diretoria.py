"""Numeros da diretoria (bloco 8; spec §10.5): na cota, prazo do orgao, a receber, notas do RM, Resumo e QDOP da
lista de Obras (as telas Carteira e A receber sairam na #748)."""
import datetime
import json
import pathlib
import sys

import pytest

from app import auth, avisos, cadastro_aplicar, db, diretoria, medicoes, qdop, reajuste, sincronizacao_rm
from tests.test_protocolo import _contrato

D = datetime.date
HOJE = D(2026, 9, 24)
MODELO = pathlib.Path(__file__).parents[2] / "cadastro-exemplo" / "modelos" / "qdop" / "qdop-modelo.xlsx"
ATRASOS = [5, 5, 5, 6, 6, 7, 8, 9, 10, 12, 20, 40]


def _receber(c) -> int:
    """O a receber na cota, cobranca a cobranca: a soma da lista de Obras (`a_receber_por_obra`, #645). A tela A
    receber saiu na #748; a conta das cobrancas (medicoes protocoladas e notas do RM em aberto) continua."""
    return sum((diretoria.a_receber_por_obra(c, na_cota=True) or {}).values())


def _notas_rm(c) -> list[tuple[str, int]]:
    """As cobrancas do RM em aberto que nenhuma medicao em aberto representa (`_notas_em_aberto`): (numero, falta)."""
    return [(n["nf"], n["valor_protocolado_centavos"]) for n in diretoria._notas_em_aberto(c)]


@pytest.fixture
def cenario(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    uid = auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "admin")
    propria = {**_contrato("Própria", "sinfra-x", "IC 1/2025"), "valor_original_centavos": 100_000_000,
               "execucao_inicio": "2025-01-01", "execucao_fim": "2027-01-31", "vigencia_fim": "2027-04-30"}
    consorcio = {**_contrato("Consórcio", "mtpar-x", "050/2024/MTPAR"), "entidade": "cons",
                 "valor_original_centavos": 1_000_000_000, "percentual_direito_bp": 5000,
                 "execucao_inicio": "2024-01-01", "execucao_fim": "2027-12-31", "vigencia_fim": "2028-03-31",
                 "instrumentos": [{"chave": "ta-1", "tipo": "aditivo_valor", "numero": "1º TA", "objeto": None,
                                   "corrige": None, "pdf": None, "delta_valor_centavos": 200_000_000,
                                   "nova_execucao_fim": None, "nova_vigencia_fim": None, "data": "2025-06-01",
                                   "dados": {}, "natureza": "execucao"}]}
    cadastro_aplicar.aplicar(c, uid, {
        "orgaos": [{"chave": "sinfra-x", "nome": "SINFRA - X", "familia": "sinfra", "cnpj": None,
                    "regras": {"nome_qdop": "SINFRA - SECRETARIA", "tipo_contratante": "PÚBLICO"}},
                   {"chave": "mtpar-x", "nome": "MTPAR", "familia": "mtpar", "cnpj": None,
                    "regras": {"nome_qdop": "MT-PAR", "tipo_contratante": "PÚBLICO"}}],
        "entidades": [{"chave": "lotufo", "nome": "Lotufo Engenharia e Construções Ltda", "cnpj": "31200101000130",
                       "papel": "lotufo", "coligada_rm": 1, "sigla_oficio": "LT", "nome_curto": "Lotufo"},
                      {"chave": "cons", "nome": "Consórcio Teste", "cnpj": "31200404000152", "papel": "consorcio",
                       "coligada_rm": None, "sigla_oficio": None, "nome_curto": "Consórcio"}],
        "contratos": [propria, consorcio], "avisos": [],
        "geral": {"qdop": {"modelo_caminho": str(MODELO)}, "diretoria": {"total_a_receber_liberado": False}}})
    p = c.execute("SELECT id FROM contratos WHERE nome_curto='Própria'").fetchone()[0]
    k = c.execute("SELECT id FROM contratos WHERE nome_curto='Consórcio'").fetchone()[0]

    def medir(cid, numero, comp, estado, valor, tipo="execucao", protocolo=None, recebida=None):
        mid = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
                        "recebida_em) VALUES (?,?,?,?,?,?,?)", (cid, numero, tipo, comp, estado, valor, recebida)).lastrowid
        if protocolo:
            c.execute("INSERT INTO medicao_protocolos (medicao_id, data, origem) VALUES (?, ?, 'manual')", (mid, protocolo))

    for i, atraso in enumerate(ATRASOS):               # 12 recebidas da SINFRA nos ultimos 12 meses
        comp = f"{2025 + (8 + i) // 12:04d}-{(8 + i) % 12 + 1:02d}"          # 2025-09 ... 2026-08
        prot = D(2026, 1, 5) + datetime.timedelta(days=14 * i)
        medir(p, i + 1, comp, "recebida", 800_000 if i == 0 else 100_000, protocolo=prot.isoformat(),
              recebida=(prot + datetime.timedelta(days=atraso)).isoformat())
    medir(p, 13, "2026-09", "espelho_gerado", 1_000_000)
    medir(p, 14, "2026-08", "protocolada", 700_000, protocolo="2026-09-10")
    medir(p, 15, "2026-06", "protocolada", 300_000, protocolo="2026-07-01")
    medir(k, 1, "2026-09", "espelho_enviado", 1_000_000)
    medir(k, 2, "2026-05", "recebida", 400_000_000, protocolo="2026-06-01", recebida="2026-06-20")
    medir(k, 2, "2026-05", "recebida", 10_000_000, tipo="reajuste", protocolo="2026-06-01", recebida="2026-06-20")
    v = c.execute("INSERT INTO cronograma_versoes (contrato_id, numero, criado_em) VALUES (?, 1, '2025-01-01 00:00:00')",
                  (p,)).lastrowid
    c.execute("INSERT INTO cronograma_itens (versao_id, competencia, valor_previsto_centavos) VALUES (?, '2026-09', 2000000)",
              (v,))
    c.commit()

    def liberar():
        c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'",
                  (json.dumps({"total_a_receber_liberado": True}),)); c.commit()

    yield c, {"propria": p, "consorcio": k, "sinfra": c.execute("SELECT id FROM orgaos WHERE chave='sinfra-x'").fetchone()[0],
              "mtpar": c.execute("SELECT id FROM orgaos WHERE chave='mtpar-x'").fetchone()[0], "liberar": liberar}
    c.close()


def test_motivos_da_obra_um_a_um_sem_o_nome_da_obra(cenario, monkeypatch):
    c, ids = cenario                   # A5: motivos[] estruturado, na ordem dos avisos
    monkeypatch.setattr(diretoria._av, "listar", lambda conn, hoje, publico: [
        avisos.aviso("execucao_vencendo", "critico", "Própria: execução termina em 10 dias", ids["propria"], "Própria", dias=10),
        avisos.aviso("folga_quebrada", "acao", "Própria: 15ª Medição protocolada há 85 dias", ids["propria"], "Própria",
                     dias=85, valor_centavos=300_000)])
    obra = [o for o in diretoria.painel(c, HOJE)["obras"] if o["contrato_id"] == ids["propria"]][0]
    assert [(m["nivel"], m["texto"], m["dias"]) for m in obra["motivos"]] == [
        ("critico", "execução termina em 10 dias", 10), ("acao", "15ª Medição protocolada há 85 dias", 85)]
    assert obra["motivos"][1]["valor_centavos"] == 300_000 and obra["farol"] == "vermelho"


def test_farol_separa_acao_de_atencao(cenario, monkeypatch):
    c, ids = cenario                   # D10: o farol distingue Acao de Atencao (antes os dois eram "amarelo")
    def com(*avisos_):
        monkeypatch.setattr(diretoria._av, "listar", lambda conn, hoje, publico: list(avisos_))
        return [o for o in diretoria.painel(c, HOJE)["obras"] if o["contrato_id"] == ids["propria"]][0]["farol"]
    a = lambda nivel: avisos.aviso("folga_quebrada", nivel, "Própria: aviso", ids["propria"], "Própria", dias=5)
    assert com(a("atencao")) == "atencao"
    assert com(a("atencao"), a("acao")) == "acao"
    assert com(a("acao"), a("critico")) == "vermelho"
    assert com() == "verde"


def test_faturado_e_a_receber_da_obra_em_valor_cheio(cenario):
    c, ids = cenario                   # A3: recebidas 800 mil + 11 x 100 mil; protocoladas 700 mil e 300 mil
    assert diretoria.da_obra(c, ids["propria"]) == {"faturado_centavos": 2_900_000, "a_receber_centavos": None}
    ids["liberar"]()
    assert diretoria.da_obra(c, ids["propria"])["a_receber_centavos"] == 1_000_000
    assert diretoria.da_obra(c, ids["consorcio"])["faturado_centavos"] == 410_000_000     # cheio, nao a cota de 50%


def test_a_receber_por_obra_igual_ao_da_obra_e_escondido_ate_liberar(cenario):
    """Lista de Obras (#509): o a receber de todas as obras numa passada, na mesma conta de `da_obra`."""
    c, ids = cenario
    assert diretoria.a_receber_por_obra(c) is None
    ids["liberar"]()
    todas = diretoria.a_receber_por_obra(c)
    for chave in ("propria", "consorcio"):
        assert todas.get(ids[chave], 0) == diretoria.da_obra(c, ids[chave])["a_receber_centavos"]
    assert todas[ids["propria"]] == 1_000_000


def test_total_a_receber_escondido_ate_liberar(cenario):
    """O total a receber so' mostra valor com o cadastro liberando (`geral.yaml: diretoria.total_a_receber_liberado`):
    na lista de Obras e no em aberto do Fechamento (#748), que respeitam a mesma trava."""
    from app import fechamento
    c, ids = cenario
    assert diretoria.a_receber_por_obra(c, na_cota=True) is None
    f = fechamento.fechamento(c)
    assert f["total_a_receber_liberado"] is False and f["em_aberto"] == []
    assert all(t["em_aberto_centavos"] is None and t["recebido_centavos"] is None for t in f["por_ano"].values())
    ids["liberar"]()
    assert diretoria.a_receber_por_obra(c, na_cota=True)[ids["propria"]] == 1_000_000
    f = fechamento.fechamento(c)
    # as protocoladas 14 (7 mil) e 15 (3 mil) nao tem nota ligada: entram pelo valor da medicao
    assert sum(t["em_aberto_centavos"] for t in f["por_ano"].values()) == 1_000_000
    assert {e["tipo_aberto"] for e in f["em_aberto"]} == {"sem_nota"}


def test_medido_do_ano_no_resumo_na_cota(cenario):
    """O "Medido em 2026" do Resumo da lista de Obras: competencias de 01 a 09/2026 fora de FORA, na cota. Propria:
    8 recebidas de 1 mil (01 a 08), espelho de 10 mil, protocoladas de 7 mil e 3 mil; consorcio a 50%: espelho de 10
    mil, execucao de 4 mi e reajuste de 100 mil."""
    c, _ = cenario
    assert diretoria.painel(c, HOJE)["medido_ano"] == {
        "ano": "2026", "valor_centavos": 800_000 + 1_000_000 + 700_000 + 300_000 + 500_000 + 200_000_000 + 5_000_000}


def test_carteira_saldo_a_executar_na_cota(cenario):
    c, ids = cenario
    k = diretoria.painel(c, HOJE)["carteira"]
    # proprio: 1.000.000,00 - 39.000,00 medidos; consorcio: 50% de (12.000.000,00 - 4.010.000,00). #262 (gate Sol S2):
    # #561: o espelho gerado (10 mil, propria) e o enviado (10 mil, consorcio) medem, como em `paineis.saldo`
    assert k["saldo_centavos"] == 96_100_000 + 399_500_000
    assert set(k) == {"saldo_centavos", "por_orgao"}        # #748: ritmo e meses de producao sairam (sem tela)


def test_carteira_mede_so_execucao_nos_estados_que_medem(cenario):
    """#262 (gate Sol S2): saldo e medido da carteira contam o que `paineis.saldo` conta: execucao a partir do
    envio da planilha/carta (#561). Projeto e planilha gerada (ainda nao enviada) nao reduzem o saldo."""
    c, ids = cenario
    antes = diretoria.painel(c, HOJE)["carteira"]
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, 50, 'projeto', '2026-08', 'recebida', 3000001)", (ids["propria"],))
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, 51, 'execucao', '2026-08', 'planilha_gerada', 4000001)", (ids["propria"],))
    c.commit()
    depois = diretoria.painel(c, HOJE)["carteira"]
    assert depois["saldo_centavos"] == antes["saldo_centavos"]
    assert ({o["orgao"]: o["medido_centavos"] for o in depois["por_orgao"]}
            == {o["orgao"]: o["medido_centavos"] for o in antes["por_orgao"]})
    # e a execucao protocolada conta: 1,01 (centavo impar) a menos no saldo da propria
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, 52, 'execucao', '2026-08', 'protocolada', 101)", (ids["propria"],))
    c.commit()
    assert diretoria.painel(c, HOJE)["carteira"]["saldo_centavos"] == antes["saldo_centavos"] - 101


def test_carteira_saldo_exclui_o_aditivo_de_reajuste(cenario):
    """#262: o aditivo de reajuste entra no vigente do contrato, mas o saldo a executar e' a precos iniciais."""
    c, ids = cenario
    c.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza) "
              "VALUES (?, 'valor', 50_000_001, 'assinado', '2026-03-01', 'reajuste')", (ids["consorcio"],))
    c.commit()
    k = diretoria.painel(c, HOJE)["carteira"]
    assert k["saldo_centavos"] == 96_100_000 + 399_500_000
    por = {o["orgao"]: o for o in k["por_orgao"]}
    assert por["MTPAR"]["vigente_centavos"] == 600_000_000      # 50% de 12.000.000,00, sem o reajuste


def test_carteira_por_orgao_traz_vigente_e_medido_para_o_cartao(cenario):
    c, ids = cenario
    por = {o["orgao"]: o for o in diretoria.painel(c, HOJE)["carteira"]["por_orgao"]}
    # 06/11/2026: o cartao e' do contratante ("SINFRA" junta as superintendencias), nao de cada orgao do cadastro
    assert (por["SINFRA"]["vigente_centavos"], por["SINFRA"]["medido_centavos"]) == (100_000_000, 3_900_000)
    assert (por["MTPAR"]["vigente_centavos"], por["MTPAR"]["medido_centavos"]) == (600_000_000, 200_500_000)


def test_protocolada_ha_200_dias_nao_gera_aviso(cenario):
    c, ids = cenario                   # issue #255: o motor de atraso de pagamento por orgao saiu
    c.execute("UPDATE medicao_protocolos SET data='2026-03-08' WHERE medicao_id=(SELECT id FROM medicoes "
              "WHERE contrato_id=? AND numero=15)", (ids["propria"],))          # 200 dias antes de 24/09
    c.commit()
    ids["liberar"]()
    p = diretoria.painel(c, HOJE)
    assert not [a for a in p["avisos"] if a["tipo"] == "pagamento_atrasado"]
    assert not [a for a in avisos.listar(c, HOJE, publico="todos") if a["tipo"] == "pagamento_atrasado"]
    assert not [m for o in p["obras"] for m in o["motivos"] if m["tipo"] == "pagamento_atrasado"]
    assert _receber(c) == 1_000_000


def test_nota_em_aberto_no_rm_entra_no_a_receber_sem_contar_duas_vezes(cenario):
    c, ids = cenario
    def nota(idmov, emissao, falta, medicao_numero):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, codtmv) "
                        "VALUES (1, ?, ?, ?, ?, 'ativa', '2.2.01')", (idmov, f"{idmov:09d}", emissao, falta)).lastrowid
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan) VALUES (1, ?, ?, ?, ?, 0, 0)", (idmov, nid, idmov, falta))
        mid = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=?", (ids["propria"], medicao_numero)).fetchone()[0]
        c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                  "VALUES (?, ?, ?, 'detectado', 't')", (mid, nid, falta))
    nota(900, "2026-06-01", 2_500_000, 1)    # medicao 1 ja' recebida (fechada): a nota em aberto e' que conta
    nota(901, "2026-09-12", 700_000, 14)     # medicao 14 protocolada: ja' conta pela medicao
    c.commit()
    ids["liberar"]()
    assert _receber(c) == 700_000 + 300_000 + 2_500_000
    assert _notas_rm(c) == [("900", 2_500_000)]       # A14: das 3 cobrancas, 1 e' nota em aberto no RM


def test_recebimento_manual_tira_a_nota_do_a_receber_e_o_corte_nao(cenario):
    """Issue #203 (decisao A): medicao recebida a mao pelo admin com NF ligada e titulo aberto no RM nao soma de
    novo a nota em "a receber". A medicao fechada pelo corte continua com a
    nota em aberto no a receber, como antes."""
    c, ids = cenario
    uid = c.execute("SELECT id FROM usuarios").fetchone()[0]

    def nota(idmov, emissao, falta, medicao_numero):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, codtmv) "
                        "VALUES (1, ?, ?, ?, ?, 'ativa', '2.2.01')", (idmov, f"{idmov:09d}", emissao, falta)).lastrowid
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan) VALUES (1, ?, ?, ?, ?, 0, 0)", (idmov, nid, idmov, falta))
        mid = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=?", (ids["propria"], medicao_numero)).fetchone()[0]
        c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                  "VALUES (?, ?, ?, 'detectado', 't')", (mid, nid, falta))
        return mid
    a_mao = nota(910, "2026-06-01", 2_000_001, 14)    # protocolada; o admin registra o recebimento a mao
    cortada = nota(911, "2026-06-02", 300_001, 15)    # protocolada; fecha pelo corte
    c.commit()
    medicoes.mudar_estado(c, uid, a_mao, "recebida", "a baixa nao entrou no RM; conferida no extrato", "2026-09-20")
    # o corte se reconhece pelo comeco do motivo, mesmo que o resto do texto da epoca seja outro
    medicoes.mudar_estado(c, uid, cortada, "recebida", "corte de 22/09/2026: faturado conta como pago", None)
    ids["liberar"]()
    assert _receber(c) == 300_001                          # so' a nota da medicao fechada pelo corte
    assert _notas_rm(c) == [("911", 300_001)]
    assert diretoria.da_obra(c, ids["propria"])["a_receber_centavos"] == 300_001


def test_nota_partida_com_medicao_do_corte_fica_inteira_e_baixa_parcial_a_mao_sai(cenario):
    """Gate Sol S1 da PR #206: a nota so' sai do a receber quando TODAS as medicoes ligadas foram recebidas a mao.
    Ligada tambem a medicao fechada pelo corte, fica inteira (como antes). Com baixa parcial e so' a medicao a mao,
    sai inteira: o registro manual vale."""
    c, ids = cenario
    uid = c.execute("SELECT id FROM usuarios").fetchone()[0]

    def mid(n):
        return c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=?", (ids["propria"], n)).fetchone()[0]

    def nota(idmov, devido, baixado, numeros):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, codtmv) "
                        "VALUES (1, ?, ?, '2026-06-01', ?, 'ativa', '2.2.01')", (idmov, f"{idmov:09d}", devido)).lastrowid
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan) VALUES (1, ?, ?, ?, ?, ?, ?)", (idmov, nid, idmov, devido, baixado, 1 if baixado else 0))
        for n in numeros:
            c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                      "VALUES (?, ?, ?, 'detectado', 't')", (mid(n), nid, devido // len(numeros)))
    nota(920, 1_000_001, 0, (14, 15))          # partida: 14 a mao, 15 pelo corte
    nota(921, 500_001, 100_000, (14,))         # so' a 14 (a mao), baixa parcial no RM
    c.commit()
    medicoes.mudar_estado(c, uid, mid(14), "recebida", "a baixa nao entrou no RM; conferida no extrato", "2026-09-20",
                          origem="manual")
    medicoes.mudar_estado(c, uid, mid(15), "recebida", "corte de 22/09/2026: faturado conta como pago", None,
                          origem="corte")
    ids["liberar"]()
    assert (_receber(c), _notas_rm(c)) == (1_000_001, [("920", 1_000_001)])


# --- issue #279 (spec 2026-10-20 §2.2): o reajuste ja' medido sem apostilamento, por competencia e na cota ---

# --- issue #279 (spec 2026-10-20 §2.2): o reajuste ja' medido sem apostilamento, por competencia e na cota ---

def _reajuste(c, cid, numero, comp, estado, pedido=None, aprovado=None):
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
              "valor_atestado_centavos) VALUES (?, ?, 'reajuste', ?, ?, ?, ?)", (cid, numero, comp, estado, pedido, aprovado))
    c.commit()


def _data_base(c, cid, mes):
    c.execute("INSERT INTO contrato_datas_base (contrato_id, mes, indice) VALUES (?, ?, 'INCC-DI')", (cid, mes))
    c.commit()


def _apostilar(c, cid, chave, dados, competencias=()):
    """Apostilamento de reajuste como o cadastro aplica: o termo e, para cada competencia que ele lista, a previsao de
    origem apostilamento."""
    iid = c.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) "
                    "VALUES (?, ?, 'apostilamento_reajuste', '2026-09-01', ?)", (cid, chave, json.dumps(dados))).lastrowid
    for comp, valor in competencias:
        c.execute("INSERT INTO reajuste_previsoes (contrato_id, data_base_mes, ciclo, competencia, valor_previsto_centavos, "
                  "origem, instrumento_id, criado_em) VALUES (?, ?, ?, ?, ?, 'apostilamento', ?, '2026-09-01 10:00:00')",
                  (cid, dados["data_base"], dados["ciclo"], comp, valor, iid))
    c.commit()


def test_reajustes_esperando_apostilamento_somam_o_medido_por_competencia_na_cota(cenario):
    c, ids = cenario
    p, k = ids["propria"], ids["consorcio"]
    _data_base(c, p, "2025-01")
    _reajuste(c, p, 31, "2026-02", "planilha_enviada", pedido=100_001)            # pedida
    _reajuste(c, p, 32, "2026-02", "planilha_gerada", pedido=50_000)              # complemento da mesma competencia
    _reajuste(c, p, 33, "2026-03", "boletim_recebido", pedido=200_000, aprovado=199_999)   # aprovada: o aprovado vale
    _reajuste(c, p, 34, "2026-04", "nota_emitida", pedido=300_003, aprovado=300_003)       # faturada sem apostilamento
    _reajuste(c, p, 35, "2026-05", "boletim_recebido", aprovado=400_000)          # apostilada: fora
    _apostilar(c, p, "ap-1", {"data_base": "2025-01", "ciclo": 2026,
                              "competencias": [{"competencia": "2026-05", "valor": "4.000,00"}]}, [("2026-05", 400_000)])
    _reajuste(c, p, 36, "2026-06", "recebida", pedido=500_000)                    # recebida: fora
    _reajuste(c, p, 37, "2026-07", "cancelada", pedido=1)                         # cancelada: fora
    _reajuste(c, p, 38, "2026-08", "prevista")                                    # so' prevista: fora
    _data_base(c, k, "2024-01")
    # consorcio a 50%: 100.001 + 100.001 no cheio = 200.002, na cota 100.001 (arredondamento unico; por competencia
    # seriam 50.001 + 50.001)
    _reajuste(c, k, 31, "2026-03", "planilha_enviada", pedido=100_001)
    _reajuste(c, k, 32, "2026-04", "boletim_recebido", pedido=100_001, aprovado=100_001)
    r = diretoria.painel(c, HOJE)["reajustes_apostilamento"]
    assert [(o["contrato_id"], o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [
        (p, "Própria", 3, 100_001 + 50_000 + 199_999 + 300_003), (k, "Consórcio", 2, 100_001)]
    assert (r["competencias"], r["valor_centavos"]) == (5, 650_003 + 100_001)


def test_obra_com_tudo_apostilado_nao_aparece_nos_reajustes_esperando_apostilamento(cenario):
    c, ids = cenario
    p, k = ids["propria"], ids["consorcio"]
    _data_base(c, p, "2025-01")
    _reajuste(c, p, 31, "2026-02", "planilha_enviada", pedido=100_001)
    _reajuste(c, p, 32, "2026-03", "nota_emitida", pedido=200_000, aprovado=200_000)
    # percentual da MT-PAR com periodo: cobre as duas competencias
    _apostilar(c, p, "ap-1", {"data_base": "2025-01", "ciclo": 2026, "percentual": "6,76",
                              "periodo": {"de": "2026-01", "ate": "2026-12"}})
    _data_base(c, k, "2024-01")
    _reajuste(c, k, 31, "2026-03", "planilha_enviada", pedido=100_001)
    r = diretoria.painel(c, HOJE)["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Consórcio", 1, 50_001)]
    assert (r["competencias"], r["valor_centavos"]) == (1, 50_001)


def test_termo_so_com_periodo_parcial_deixa_o_mes_de_fora_esperando_apostilamento(cenario):
    # issue #444: o `periodo` sozinho limita o termo (o cadastro recusa competencia fora dele); a faturada de 06/2026,
    # fora do periodo 01-03/2026 do ciclo 2026, espera; a de 02/2026, dentro, nao. Centavo impar no valor
    c, ids = cenario
    p = ids["propria"]
    _data_base(c, p, "2025-01")
    _reajuste(c, p, 31, "2026-02", "nota_emitida", pedido=100_001, aprovado=100_001)
    _reajuste(c, p, 32, "2026-06", "nota_emitida", pedido=200_003, aprovado=200_003)
    _apostilar(c, p, "ap-1", {"data_base": "2025-01", "ciclo": 2026, "periodo": {"de": "2026-01", "ate": "2026-03"}})
    r = diretoria.painel(c, HOJE)["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Própria", 1, 200_003)]


@pytest.mark.parametrize("segundo,previsoes", [
    ({"periodo": {"de": "2026-04", "ate": "2026-05"}}, ()),
    ({"percentual": "6,80", "periodo": {"de": "2026-04", "ate": "2026-05"}}, ()),
    ({"competencias": [{"competencia": "2026-04", "valor": "1.000,00"}]}, [("2026-04", 100_000)]),
], ids=["so-periodo", "percentual", "lista"])
def test_dois_termos_parciais_no_mesmo_ciclo_cobrem_cada_um_os_seus_meses(cenario, segundo, previsoes):
    # revisor e gate Sol (rodada 1, PR #524): o 2o termo do ciclo (o mais novo) nao apaga o periodo do 1o so' com
    # periodo; 02/2026 (do 1o) e 04/2026 (do 2o) nao esperam, 06/2026 espera. Centavo impar no valor
    c, ids = cenario
    p = ids["propria"]
    _data_base(c, p, "2025-01")
    _reajuste(c, p, 31, "2026-02", "nota_emitida", pedido=100_001, aprovado=100_001)
    _reajuste(c, p, 32, "2026-04", "nota_emitida", pedido=100_000, aprovado=100_000)
    _reajuste(c, p, 33, "2026-06", "nota_emitida", pedido=200_003, aprovado=200_003)
    _apostilar(c, p, "ap-1", {"data_base": "2025-01", "ciclo": 2026, "periodo": {"de": "2026-01", "ate": "2026-03"}})
    _apostilar(c, p, "ap-2", {"data_base": "2025-01", "ciclo": 2026, **segundo}, previsoes)
    r = diretoria.painel(c, HOJE)["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Própria", 1, 200_003)]


def test_reajustes_esperando_apostilamento_contam_obra_encerrada_e_nao_a_rescindida(cenario):
    # revisor (rodada 1, PR #431): o reajuste so' sai do bloco com o apostilamento (spec 2026-10-20 §2.2); fora fica
    # so' o rescindido, como no QDOP
    c, ids = cenario
    p, k = ids["propria"], ids["consorcio"]
    for cid, base in ((p, "2025-01"), (k, "2024-01")):
        _data_base(c, cid, base)
        _reajuste(c, cid, 31, "2026-03", "planilha_enviada", pedido=100_000)
    c.execute("UPDATE contratos SET estado='encerrado' WHERE id=?", (p,))
    c.execute("UPDATE contratos SET estado='rescindido' WHERE id=?", (k,))
    c.commit()
    r = diretoria.painel(c, HOJE)["reajustes_apostilamento"]
    assert [o["obra"] for o in r["obras"]] == ["Própria"]
    c.execute("UPDATE contratos SET estado='suspenso' WHERE id=?", (k,)); c.commit()
    r = diretoria.painel(c, HOJE)["reajustes_apostilamento"]
    assert sorted(o["obra"] for o in r["obras"]) == ["Consórcio", "Própria"]


def test_termo_que_fecha_o_ciclo_sem_dizer_os_meses_tira_a_obra_do_bloco(cenario):
    # revisor (rodada 1, PR #431): o apostilamento so' com percentual (sem periodo) e o aditivo de valor de reajuste da
    # SES (#390) fecham o ciclo inteiro em `reajuste.ciclos`; a competencia do ciclo fechado nao espera apostilamento
    c, ids = cenario
    p, k = ids["propria"], ids["consorcio"]
    _data_base(c, p, "2025-01")
    _reajuste(c, p, 31, "2026-03", "boletim_recebido", pedido=200_000, aprovado=200_000)
    _apostilar(c, p, "ap-g", {"data_base": "2025-01", "ciclo": 2026, "percentual": "5,00"})
    _data_base(c, k, "2024-01")
    _reajuste(c, k, 31, "2026-03", "nota_emitida", pedido=300_000, aprovado=300_000)
    _reajuste(c, k, 32, "2025-03", "nota_emitida", pedido=100_001, aprovado=100_001)     # ciclo 2025: nao fechado
    c.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, numero, "
              "chave_cadastro, natureza) VALUES (?, 'valor', 300000, 'assinado', '2026-04-10', '3º TA', 'ta-3', "
              "'reajuste')", (k,))
    c.commit()
    assert [(x["ciclo"], x["situacao"]) for x in reajuste.ciclos(c, p, HOJE)] == [(2026, "apostilado")]
    assert [(x["ciclo"], x["situacao"]) for x in reajuste.ciclos(c, k, HOJE)] == [(2026, "apostilado")]
    r = diretoria.painel(c, HOJE)["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Consórcio", 1, 50_001)]


def test_medicao_sem_data_base_em_contrato_de_duas_bases_so_sai_com_as_duas_apostiladas(cenario):
    # revisor (rodada 1, PR #431): medicao sem `data_base_mes` em contrato de duas datas-base cai no grupo sem
    # data-base (`reajuste.competencias_por_ciclo`); ela so' deixa de esperar quando todas as bases apostilaram o mes
    c, ids = cenario
    p = ids["propria"]
    _data_base(c, p, "2025-01")
    _data_base(c, p, "2025-03")
    _reajuste(c, p, 31, "2026-04", "boletim_recebido", pedido=100_000, aprovado=100_000)
    _apostilar(c, p, "ap-a", {"data_base": "2025-01", "ciclo": 2026,
                              "competencias": [{"competencia": "2026-04", "valor": "1.000,00"}]}, [("2026-04", 100_000)])
    # as duas bases com previsao do mes: a medicao nao tem como escolher e vai para o grupo sem data-base
    c.execute("INSERT INTO reajuste_previsoes (contrato_id, data_base_mes, ciclo, competencia, valor_previsto_centavos, "
              "origem, criado_em) VALUES (?, '2025-03', 2026, '2026-04', 100000, 'manual', '2026-08-01 10:00:00')", (p,))
    c.commit()
    r = diretoria.painel(c, HOJE)["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Própria", 1, 100_000)]
    _apostilar(c, p, "ap-b", {"data_base": "2025-03", "ciclo": 2026,
                              "competencias": [{"competencia": "2026-04", "valor": "1.000,00"}]}, [("2026-04", 100_000)])
    assert diretoria.painel(c, HOJE)["reajustes_apostilamento"]["obras"] == []


def test_contrato_sem_data_base_tem_o_reajuste_medido_esperando_apostilamento(cenario):
    # revisor (rodada 2, PR #431): sem data-base nenhum termo cobre a competencia, entao ela espera; a pedida e a
    # aprovada nao estao em "Onde esta' o dinheiro". Consorcio a 50%: 100.001 + 200.001 = 300.002, na cota 150.001
    c, ids = cenario
    k = ids["consorcio"]
    _reajuste(c, k, 31, "2026-03", "planilha_enviada", pedido=100_001)
    _reajuste(c, k, 32, "2026-04", "boletim_recebido", pedido=200_000, aprovado=200_001)
    r = diretoria.painel(c, HOJE)["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Consórcio", 2, 150_001)]


def test_complemento_ainda_nao_recebido_espera_mesmo_com_a_principal_recebida(cenario):
    # revisor (rodada 1, PR #431): a principal recebida nao esconde o complemento pedido da competencia sem apostilamento
    c, ids = cenario
    p = ids["propria"]
    _data_base(c, p, "2025-01")
    _reajuste(c, p, 31, "2026-03", "recebida", pedido=100_000, aprovado=100_000)
    _reajuste(c, p, 32, "2026-03", "planilha_enviada", pedido=50_001)
    r = diretoria.painel(c, HOJE)["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Própria", 1, 50_001)]


def test_medicao_sem_base_em_mes_sem_reajuste_em_nenhuma_data_base_espera(cenario):
    # revisor (PR #431, pedido na rodada 2 da PR #438): datas-base 2025-01 e 2025-03, medicao de reajuste pedida de
    # 06/2025 sem previsao. Cai no grupo sem data-base; nenhuma base tem reajuste no mes (o 1o aniversario e' em 2026),
    # entao nenhum termo a cobre e ela espera, pelo criterio unico da aba (`reajuste.cobertura_das_competencias`)
    c, ids = cenario
    p = ids["propria"]
    _data_base(c, p, "2025-01")
    _data_base(c, p, "2025-03")
    _reajuste(c, p, 31, "2025-06", "planilha_enviada", pedido=100_001)
    [grupo] = reajuste.competencias_por_ciclo(c, p)
    assert (grupo["data_base_mes"], grupo["ciclo"], grupo["competencias"][0]["data_base_incerta"]) == (None, None, True)
    r = diretoria.painel(c, HOJE)["reajustes_apostilamento"]
    assert [(o["obra"], o["competencias"], o["valor_centavos"]) for o in r["obras"]] == [("Própria", 1, 100_001)]


def test_a_receber_por_obra_na_cota_com_centavo_impar(cenario):
    """Lista de Obras (#645): o a receber de cada obra na cota, cobranca a cobranca; escondido ate' liberar."""
    c, ids = cenario
    c.execute("UPDATE medicoes SET valor_protocolado_centavos=800001 WHERE contrato_id=? AND numero=14", (ids["propria"],))
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, 3, 'execucao', '2026-08', 'protocolada', 1000001)", (ids["consorcio"],))
    c.commit()
    assert diretoria.a_receber_por_obra(c, na_cota=True) is None
    ids["liberar"]()
    # centavo impar: 1.000.001 x 50% = 500.001 (arredondamento unico em `contratos.cota`); propria na cota cheia
    assert diretoria.a_receber_por_obra(c, na_cota=True) == {ids["propria"]: 800_001 + 300_000, ids["consorcio"]: 500_001}
    assert diretoria.a_receber_por_obra(c)[ids["consorcio"]] == 1_000_001       # cheio, na pagina da obra


def test_a_receber_nota_do_rm_entra_na_lista_e_no_total(cenario):
    c, ids = cenario
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, codtmv) "
                    "VALUES (1, 900, '000000900', '2026-06-01', 2500000, 'ativa', '2.2.01')").lastrowid
    c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, status_lan) "
              "VALUES (1, 900, ?, 900, 2500000, 0, 0)", (nid,))
    mid = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=1", (ids["propria"],)).fetchone()[0]
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
              "VALUES (?, ?, 2500000, 'detectado', 't')", (mid, nid))
    c.commit()
    ids["liberar"]()
    assert _notas_rm(c) == [("900", 2_500_000)]
    assert _receber(c) == 700_000 + 300_000 + 2_500_000


def test_titulo_baixado_sem_valor_fica_fora_do_recebido_e_do_a_receber(cenario):
    """Issue #583 (decisao do Leo de 08/11/2026, opcao 2): o titulo do RM com baixa total (status 1) e valor baixado
    zero fica fora do recebido e do a receber (a linha "baixado sem caixa" saiu com a tela A receber, #748). A
    medicao ligada continua sem fechar (regra da #574)."""
    c, ids = cenario
    c.execute("UPDATE contratos SET centro_custo_rm='9.001.001' WHERE id=?", (ids["propria"],))
    def nota(idmov, emissao, valor, coligada=1, medicao=None, situacao="ativa"):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, codtmv, "
                        "centro_custo) VALUES (?, ?, ?, ?, ?, ?, '2.2.01', ?)",
                        (coligada, idmov, str(idmov), emissao, valor, situacao, None if medicao else "9.001.001")).lastrowid
        if medicao:
            c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                      "VALUES (?, ?, ?, 'detectado', 't')", (medicao, nid, valor))
        return nid
    def baixa(nid, idlan, original, baixado, status, data):
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan, data_baixa) VALUES (1, ?, ?, ?, ?, ?, ?, ?)", (idlan, nid, idlan, original, baixado, status, data))
    a = nota(941, "2026-07-10", 1_000_001)
    baixa(a, 9411, 700_001, 0, 1, "2026-08-05")          # baixado sem valor: sem caixa
    baixa(a, 9412, 300_000, 300_000, 1, "2026-08-05")    # baixado com valor: recebido
    b = nota(942, "2025-07-10", 500_000)
    baixa(b, 9421, 500_000, 0, 1, "2025-08-05")          # sem caixa, mas em outro ano
    d = nota(943, "2026-07-10", 80_000)
    baixa(d, 9431, 40_000, 0, 0, None)                   # aberto: a receber
    baixa(d, 9432, 40_000, 0, 2, "2026-08-01")           # cancelado: fora
    x = nota(946, "2026-07-12", 90_000, situacao="cancelada")
    baixa(x, 9461, 90_000, 0, 1, "2026-08-07")           # nota cancelada: fora do faturado, fora do sem caixa
    # consorcio (sem centro: cai pela coligada): entra pela cota (50% de 333.333 = 166.666,5 -> 166.667)
    c.execute("UPDATE entidades SET coligada_rm=12 WHERE chave='cons'")
    k = nota(944, "2026-07-20", 333_333, coligada=12)
    baixa(k, 9441, 333_333, 0, 1, "2026-09-02")
    c.commit()
    ids["liberar"]()
    faturado, recebido = diretoria.rm_por_mes(c)
    assert {m: v for m, v in recebido.items() if v} == {"2026-08": 300_000}
    assert _notas_rm(c) == [("943", 40_000)]
    assert faturado["2026-07"] == 1_000_001 + 80_000 + 166_667
    antes = _receber(c)
    # medicao em aberto ligada a nota com titulo sem caixa: segue no a receber pela medicao, nao fecha (#574) e o
    # titulo nao entra de novo no baixado sem caixa (nao conta duas vezes)
    m15 = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=15", (ids["propria"],)).fetchone()[0]
    nid = nota(945, "2026-07-11", 300_000, medicao=m15)
    baixa(nid, 9451, 300_000, 0, 1, "2026-08-06")
    c.commit()
    sincronizacao_rm._recebimentos(c)
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (m15,)).fetchone()[0] == "protocolada"
    assert _receber(c) == antes and _notas_rm(c) == [("943", 40_000)]


@pytest.mark.parametrize("titulos, falta", [
    ([(50_000, 55_100, 1), (5_000, 0, 0)], 5_000),      # issue #253: juros em A nao escondem B aberto
    ([(50_000, 60_000, 1), (5_000, 0, 0)], 5_000),      # ... nem juros acima do valor de B inteiro
    ([(50_000, 55_100, 1), (5_000, 3_000, 4)], 2_000),  # ... nem a falta de B com baixa parcial
    ([(50_000, 55_100, 1), (5_000, 5_000, 1)], None),   # todos pagos (um com juros): sai, como hoje
    ([(50_000, 50_000, 1), (5_000, 4_901, 1)], None),   # ate' R$ 1,00 a menos no total: sai, como hoje
    ([(50_000, 50_000, 1), (5_000, 0, 1)], None),       # issue #563: baixa total com valor baixado zero e' quitado
    ([(50_000, 0, 1), (5_000, 0, 0)], 5_000),           # ... e o titulo aberto ao lado continua contando
])
def test_a_receber_conta_a_falta_da_nota_titulo_a_titulo(cenario, titulos, falta):
    """Issue #253: a nota em aberto do RM entra no a receber pelo que falta titulo a titulo (a conta da #35 e da
    #251): pagamento a mais num titulo nao compensa outro titulo aberto da mesma nota."""
    c, ids = cenario
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, codtmv) "
                    "VALUES (1, 930, '000000930', '2026-06-01', 60000, 'ativa', '2.2.01')").lastrowid
    for i, (orig, baixado, st) in enumerate(titulos, 1):
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan) VALUES (1, ?, ?, 930, ?, ?, ?)", (9300 + i, nid, orig, baixado, st))
    mid = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=1", (ids["propria"],)).fetchone()[0]
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
              "VALUES (?, ?, 55000, 'detectado', 't')", (mid, nid))
    c.commit()
    ids["liberar"]()
    assert [v for _, v in _notas_rm(c)] == ([] if falta is None else [falta])
    assert _receber(c) == 700_000 + 300_000 + (falta or 0)


def test_so_nota_de_cobranca_ao_orgao_entra_no_a_receber_e_no_faturado(cenario):
    """Issue #563: so' os codtmv de `CODTMV_COBRANCA` sao cobranca ao orgao. Nota 2.2.15 (nota do fornecedor) e 2.2.10
    (pessoas fisicas) com centro de custo da obra e titulo aberto ficam fora do a receber, do faturado do RM e do
    complemento; a 2.2.01 continua."""
    c, ids = cenario
    assert diretoria.CODTMV_COBRANCA == ("2.2.01", "2.2.02", "2.2.07", "2.2.16")
    c.execute("UPDATE contratos SET centro_custo_rm='9.001.001' WHERE id=?", (ids["propria"],))
    def nota(idmov, codtmv, valor):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, centro_custo, "
                        "codtmv) VALUES (1, ?, ?, '2026-08-10', ?, 'ativa', '9.001.001', ?)",
                        (idmov, str(idmov), valor, codtmv)).lastrowid
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan) VALUES (1, ?, ?, ?, ?, 0, 0)", (idmov, nid, idmov, valor))
    nota(9701, "2.2.15", 2_130_000)
    nota(9702, "2.2.10", 250_000)
    c.commit()
    ids["liberar"]()
    assert _notas_rm(c) == []
    assert _receber(c) == 700_000 + 300_000
    assert diretoria.rm_por_mes(c)[0] == {} and diretoria.complemento_rm(c) == {}
    nota(9703, "2.2.01", 1_000_000)
    c.commit()
    assert [v for _, v in _notas_rm(c)] == [1_000_000]
    assert _receber(c) == 700_000 + 300_000 + 1_000_000
    assert diretoria.rm_por_mes(c)[0] == {"2026-08": 1_000_000}
    assert diretoria.complemento_rm(c) == {ids["propria"]: {"2026-07": 900_000}}


# --- issue #296: curva S da carteira (soma das obras ativas, na cota) e desvio em p.p. por obra no QDOP -----

def _repactuar_consorcio(c, k):
    """Consorcio: contratual (4 mi em 05/2026, 2 mi em 08/2026) e o 1º TA, que repactua para 3 mi e 1 mi."""
    from app import cronograma
    for numero, itens, data, chave, origem in (
            (1, [("2026-05", 400_000_000), ("2026-08", 200_000_000)], "2024-01-01", "contratual", "contratual"),
            (2, [("2026-05", 300_000_000), ("2026-08", 100_000_000)], "2025-06-01", "ta1", "aditivo")):
        cronograma.nova_versao(c, 1, k, itens, "manual", data_documento=data)
        vid = c.execute("SELECT id FROM cronograma_versoes WHERE contrato_id=? AND numero=?", (k, numero)).fetchone()[0]
        c.execute("INSERT INTO cronograma_versoes_cadastro (versao_id, contrato_id, chave, origem, data_documento, instrumento)"
                  " VALUES (?,?,?,?,?,NULL)", (vid, k, chave, origem, data))
        c.commit()


def test_curva_da_carteira_soma_as_obras_ativas_na_cota_com_as_duas_linhas(cenario):
    c, ids = cenario
    _repactuar_consorcio(c, ids["consorcio"])
    curva = diretoria.painel(c, HOJE)["curva_carteira"]
    assert [p["competencia"] for p in curva] == ["2025-10", "2025-11", "2025-12"] + [f"2026-{m:02d}" for m in range(1, 10)]
    por = {p["competencia"]: p for p in curva}
    # 05/2026: o consorcio entra com 50% (TA 3 mi, anterior 4 mi, medido 4 mi) e a propria com o medido de 1 mil
    assert por["2026-05"] == {"competencia": "2026-05", "previsto_centavos": 150_000_000,
                              "previsto_anterior_centavos": 200_000_000, "medido_centavos": 200_000_000 + 100_000}
    # 08/2026: a propria mede 1 mil (recebida) + 7 mil (protocolada); o consorcio so' preve
    assert por["2026-08"] == {"competencia": "2026-08", "previsto_centavos": 50_000_000,
                              "previsto_anterior_centavos": 100_000_000, "medido_centavos": 800_000}
    # 09/2026: a propria nao tem repactuacao e entra na linha anterior com o vigente; o espelho mede (#561): 10 mil da propria + 50% de 10 mil
    assert por["2026-09"] == {"competencia": "2026-09", "previsto_centavos": 2_000_000,
                              "previsto_anterior_centavos": 2_000_000, "medido_centavos": 1_500_000}
    # o reajuste nao e' medido de execucao
    c.execute("UPDATE medicoes SET tipo='reajuste' WHERE contrato_id=? AND competencia='2026-08'", (ids["propria"],))
    c.commit()
    assert {p["competencia"]: p for p in diretoria.painel(c, HOJE)["curva_carteira"]}["2026-08"]["medido_centavos"] == 0


def test_curva_da_carteira_deixa_de_fora_a_obra_que_nao_esta_ativa(cenario):
    c, ids = cenario
    _repactuar_consorcio(c, ids["consorcio"])
    c.execute("UPDATE contratos SET estado='encerrado' WHERE id=?", (ids["consorcio"],))
    c.commit()
    por = {p["competencia"]: p for p in diretoria.painel(c, HOJE)["curva_carteira"]}
    assert por["2026-05"] == {"competencia": "2026-05", "previsto_centavos": 0, "previsto_anterior_centavos": 0,
                              "medido_centavos": 100_000}


def _reajuste_no_consorcio(c, ids, valor=240_000_001):
    """#262: aditivo de reajuste (SES) de 2.400.000,01 no consorcio: entra no vigente, fica fora da base de execucao."""
    c.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza) "
              "VALUES (?, 'valor', ?, 'assinado', '2026-03-01', 'reajuste')", (ids["consorcio"], valor))
    c.commit()


def test_tabela_de_obras_usa_o_vigente_de_execucao_e_o_qdop_nao_muda(cenario):
    """#262 (gate Sol S1): na tabela de obras da Diretoria, PI+VA, VA, saldo e percentuais a precos iniciais; o
    reajuste so' na coluna propria. O QDOP exportado fica como esta' (#352, QDOP com saldo a precos iniciais)."""
    c, ids = cenario
    _reajuste_no_consorcio(c, ids)
    o = {x["contrato_id"]: x for x in diretoria.painel(c, HOJE)["obras"]}[ids["consorcio"]]
    # 50% de 12.000.000,00 (sem o reajuste); faturado = 50% de 4.000.000,00; reajuste faturado = 50% de 100.000,00
    assert (o["pi"], o["va"], o["pi_va"]) == (500_000_000, 100_000_000, 600_000_000)
    assert (o["faturados"], o["reajuste_recebido"], o["saldo"]) == (200_000_000, 5_000_000, 399_500_000)
    assert (o["pct_recebido"], o["pct_a_receber"]) == (200_500_000 / 600_000_000, 399_500_000 / 600_000_000)
    assert "desvio_pp" not in o                          # #748: o desvio nao tinha tela e saiu
    q = {x["contrato_id"]: x for x in qdop.linhas(c, HOJE)}[ids["consorcio"]]
    assert q["pi_va"] == 720_000_001                         # 50% de 14.400.000,01, meio para cima


def _medir(c, contrato, numero, estado, valor, tipo="execucao", comp="2026-08"):
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, ?, ?, ?, ?, ?)", (contrato, numero, tipo, comp, estado, valor))


def _saldos(c):
    p = diretoria.painel(c, HOJE)
    tabela = {o["contrato_id"]: o["saldo"] for o in p["obras"]}
    carteira = {o["orgao"]: o["saldo_centavos"] for o in p["carteira"]["por_orgao"]}
    return tabela, carteira, {o["contrato_id"]: o for o in p["obras"]}


def test_tabela_de_obras_mede_como_a_carteira(cenario):
    """#262 (revisao, rodada 3): o saldo da tabela de obras desconta o mesmo medido da carteira, logo acima na tela
    (`paineis.mede_execucao`): projeto recebido nao abate o saldo; execucao com nota emitida abate (#561)."""
    c, ids = cenario
    _medir(c, ids["propria"], 60, "recebida", 50_000_000, tipo="projeto")
    _medir(c, ids["propria"], 61, "nota_emitida", 3_000_001)
    c.commit()
    tabela, carteira, obras = _saldos(c)
    assert tabela[ids["propria"]] == carteira["SINFRA"] == 93_099_999      # 1.000.000,00 - 39.000,00 - 30.000,01
    assert tabela[ids["consorcio"]] == carteira["MTPAR"] == 399_500_000
    assert obras[ids["propria"]]["faturados"] == 2_900_000 + 50_000_000 + 3_000_001   # a coluna do QDOP fica


def test_tabela_e_carteira_leem_as_mesmas_medicoes(cenario, monkeypatch):
    """#262 (gate Sol, rodada 3): a tabela de obras tira o medido da mesma leitura de medicoes da carteira. Uma
    medicao que passa de planilha gerada a protocolada no meio do painel nao deixa os dois saldos diferentes."""
    c, ids = cenario
    _medir(c, ids["propria"], 60, "planilha_gerada", 5_000_000)
    c.commit()
    original = avisos.listar

    def protocola_no_meio(conn, *a, **k):         # roda depois da leitura das medicoes do painel
        conn.execute("UPDATE medicoes SET estado='protocolada' WHERE contrato_id=? AND numero=60", (ids["propria"],))
        conn.commit()
        return original(conn, *a, **k)
    monkeypatch.setattr(avisos, "listar", protocola_no_meio)
    tabela, carteira, _ = _saldos(c)
    assert tabela[ids["propria"]] == carteira["SINFRA"] == 96_100_000


def test_medido_da_tabela_e_da_carteira_vale_o_atestado(cenario):
    """#262 (gate Sol, rodada 3): com atestado, o medido de execucao e' o atestado, nao o protocolado."""
    c, ids = cenario
    _medir(c, ids["propria"], 60, "protocolada", 10_000_000)
    c.execute("UPDATE medicoes SET valor_atestado_centavos=3000001 WHERE contrato_id=? AND numero=60", (ids["propria"],))
    c.commit()
    tabela, carteira, _ = _saldos(c)
    assert tabela[ids["propria"]] == carteira["SINFRA"] == 96_100_000 - 3_000_001


def test_carteira_usa_o_percentual_do_vigente_que_a_tabela_reaproveita(cenario, monkeypatch):
    """#262 (gate Sol, rodada 3): a carteira aplica a cota com o percentual do mesmo `contratos.vigente` que a tabela
    reaproveita, nao com o da linha lida antes. O percentual do consorcio muda de 50% para 40% logo depois da lista
    de contratos da carteira: as duas mostram 40% de (12.000.000,00 - 4.010.000,00) = 3.196.000,00."""
    c, ids = cenario
    original = diretoria._ativos

    def muda_depois_da_lista(conn):
        linhas = original(conn)
        if sys._getframe(1).f_code.co_name in ("_carteira", "<genexpr>") and not getattr(muda_depois_da_lista, "feito", False):
            conn.execute("UPDATE contratos SET percentual_direito_bp=4000 WHERE id=?", (ids["consorcio"],))
            conn.commit()
            muda_depois_da_lista.feito = True
        return linhas
    monkeypatch.setattr(diretoria, "_ativos", muda_depois_da_lista)
    p = diretoria.painel(c, HOJE)
    assert muda_depois_da_lista.feito
    o = {x["contrato_id"]: x for x in p["obras"]}[ids["consorcio"]]
    por = {x["orgao"]: x for x in p["carteira"]["por_orgao"]}["MTPAR"]
    assert o["saldo"] == por["saldo_centavos"] == 319_600_000
    assert o["pi_va"] == por["vigente_centavos"] == 480_000_000


def test_aditivo_entre_a_carteira_e_as_obras_nao_muda_a_base(cenario, monkeypatch):
    """#262 (gate Sol, rodada 3): carteira e tabela usam o mesmo vigente do painel. Um aditivo de execucao de
    2.400.000,00 que chega depois da carteira nao entra na tabela."""
    c, ids = cenario
    _repactuar_consorcio(c, ids["consorcio"])
    original = diretoria._curva_carteira

    def aditivo_no_meio(conn, *a, **k):              # roda depois da carteira e antes das obras
        conn.execute("INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status, data_assinatura, natureza) "
                     "VALUES (?, 'valor', 240000000, 'assinado', '2026-03-01', 'execucao')", (ids["consorcio"],))
        conn.commit()
        return original(conn, *a, **k)
    monkeypatch.setattr(diretoria, "_curva_carteira", aditivo_no_meio)
    p = diretoria.painel(c, HOJE)
    o = {x["contrato_id"]: x for x in p["obras"]}[ids["consorcio"]]
    por = {x["orgao"]: x for x in p["carteira"]["por_orgao"]}["MTPAR"]
    assert o["pi_va"] == por["vigente_centavos"] == 600_000_000
    assert o["saldo"] == por["saldo_centavos"] == 399_500_000


def test_painel_le_uma_fotografia_do_banco(cenario, monkeypatch):
    """#262 (revisor, rodada 3): o painel inteiro le numa transacao de leitura so'. Um `cadastro aplicar` em outra
    conexao muda o consorcio de 50% para 40% no meio da montagem: a escrita grava sem esperar (WAL, a leitura nao
    segura a escrita) e o painel continua todo em 50% (PI, VA, PI+VA e direito da mesma linha batem)."""
    c, ids = cenario
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    original = diretoria._curva_carteira

    def cadastro_no_meio(conn, *a, **k):             # depois da carteira, antes das obras
        outra = db.get_conn()
        try:
            outra.execute("UPDATE contratos SET percentual_direito_bp=4000 WHERE id=?", (ids["consorcio"],))
            outra.commit()
        finally:
            outra.close()
        return original(conn, *a, **k)
    monkeypatch.setattr(diretoria, "_curva_carteira", cadastro_no_meio)
    p = diretoria.painel(c, HOJE)
    o = {x["contrato_id"]: x for x in p["obras"]}[ids["consorcio"]]
    assert o["pi_va"] - o["pi"] == 100_000_000
    assert (o["direito"], o["pi"], o["pi_va"]) == (0.5, 500_000_000, 600_000_000)
    assert not c.in_transaction                        # a transacao de leitura fechou
    monkeypatch.setattr(diretoria, "_curva_carteira", original)
    o = {x["contrato_id"]: x for x in diretoria.painel(c, HOJE)["obras"]}[ids["consorcio"]]
    assert (o["direito"], o["pi_va"]) == (0.4, 480_000_000)      # a escrita gravou; o painel seguinte a ve


def test_painel_dentro_de_transacao_aberta_nao_a_fecha(cenario):
    """#262: com transacao ja' aberta por quem chamou, o painel le nela e a deixa aberta."""
    c, ids = cenario
    c.execute("BEGIN")
    assert diretoria.painel(c, HOJE)["obras"]
    assert c.in_transaction
    c.rollback()


def test_saldo_da_tabela_aplica_a_cota_uma_vez(cenario):
    """#262 (revisao, rodada 3): saldo = cota(vigente de execucao - medido), arredondamento unico, como na carteira.
    Consorcio a 50%: 12.000.000,00 - 4.010.000,01 = 7.989.999,99 -> 3.995.000,00 (meio para cima); duas cotas
    arredondadas dariam 6.000.000,00 - 2.005.000,01 = 3.994.999,99."""
    c, ids = cenario
    _medir(c, ids["consorcio"], 60, "protocolada", 1)
    c.commit()
    tabela, carteira, _ = _saldos(c)
    assert tabela[ids["consorcio"]] == carteira["MTPAR"] == 399_500_000


def test_faturado_e_recebido_reais_saem_do_rm_por_mes_na_cota(cenario):
    """06/11/2026: a serie mensal da diretoria vem das notas e das baixas do RM, nao das medicoes (o cadastro de medicoes
    pode estar atrasado). Nota da coligada do consorcio entra na cota (50%); a NFS-e da Lotufo em obra de consorcio,
    a cancelada e a de fora dos contratos, nao."""
    c, ids = cenario
    def nota(idmov, emissao, valor, situacao="ativa", coligada=1, medicao=None):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, codtmv) "
                        "VALUES (?, ?, ?, ?, ?, ?, '2.2.01')", (coligada, idmov, str(idmov), emissao, valor, situacao)).lastrowid
        if medicao:
            c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                      "VALUES (?, ?, ?, 'detectado', 't')", (medicao, nid, valor))
        return nid
    def baixa(nid, idlan, original, baixado, status, data):
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan, data_baixa) VALUES (1, ?, ?, ?, ?, ?, ?, ?)", (idlan, nid, idlan, original, baixado, status, data))
    m_propria = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=1", (ids["propria"],)).fetchone()[0]
    a = nota(901, "2026-08-10", 1_000_001, medicao=m_propria)
    b = nota(902, "2025-08-20", 400_000, medicao=m_propria)              # mesmo mes do ano anterior
    nota(903, "2026-08-15", 9_999_999, situacao="cancelada", medicao=m_propria)
    nota(904, "2026-08-15", 7_777_777, coligada=99)                      # fora dos contratos: sem medicao e sem centro
    baixa(a, 9011, 900_000, 900_000, 1, "2026-09-05")                    # liquido pago em setembro
    baixa(a, 9012, 50_000, 0, 0, None)                                   # titulo aberto: nao e' recebido
    baixa(b, 9021, 380_000, 380_000, 1, "2025-09-10")
    baixa(b, 9022, 10_000, 10_000, 2, "2025-09-11")                      # titulo cancelado: fora
    # o consorcio tem coligada propria no RM: a nota dela entra pela metade; a da Lotufo na mesma obra fica fora
    c.execute("UPDATE entidades SET coligada_rm=12 WHERE chave='cons'")
    m_cons = c.execute("SELECT id FROM medicoes WHERE contrato_id=? ORDER BY id LIMIT 1", (ids["consorcio"],)).fetchone()[0]
    k = nota(905, "2026-08-25", 1_000_001, coligada=12, medicao=m_cons)
    baixa(k, 9051, 1_000_001, 1_000_001, 1, "2026-09-20")
    nota(906, "2026-08-26", 3_333_333, coligada=1, medicao=m_cons)
    c.commit()
    faturado, recebido = diretoria.rm_por_mes(c)
    cota_cons = 500_001                                                  # 1.000.001 x 50%, arredondamento unico
    assert faturado == {"2026-08": 1_000_001 + cota_cons, "2025-08": 400_000}
    assert recebido == {"2026-09": 900_000 + cota_cons, "2025-09": 380_000}
    # o recebido do mes do Inicio (#642) e' a mesma conta
    assert diretoria.recebido_rm_no_mes(c, "2026-09") == {"valor_centavos": 900_000 + cota_cons, "notas": 2}


def test_nota_do_rm_sem_medicao_lancada_entra_no_medido_da_diretoria(cenario):
    """06/11/2026: o que o RM mostra e o sistema ainda nao tem (`complemento_rm`) conta como medido na Carteira. A
    competencia da nota solta e' o mes anterior ao da emissao; so' entra o que passa do que ja' esta' lancado na
    competencia; antes de `COMPETENCIA_NOTA_VALE` nada entra; nota ligada a medicao ativa nao entra."""
    c, ids = cenario
    antes = diretoria.painel(c, HOJE)
    assert diretoria.complemento_rm(c) == {}
    c.execute("UPDATE contratos SET centro_custo_rm='9.001.001' WHERE id=?", (ids["propria"],))
    c.execute("UPDATE entidades SET coligada_rm=12 WHERE chave='cons'")
    def nota(idmov, emissao, valor, coligada=1, centro="9.001.001", medicao=None):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, centro_custo, codtmv) "
                        "VALUES (?, ?, ?, ?, ?, 'ativa', ?, '2.2.01')", (coligada, idmov, str(idmov), emissao, valor, centro)).lastrowid
        if medicao:
            c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                      "VALUES (?, ?, ?, 'detectado', 't')", (medicao, nid, valor))
    nota(801, "2026-08-10", 1_000_001)                    # competencia 07/2026: lancado 100.000 -> faltam 900.001
    nota(802, "2026-07-05", 350_000)                      # competencia 06/2026: lancado 400.000 cobre -> nada
    nota(803, "2026-06-10", 5_000_000)                    # competencia 05/2026: antes do corte -> nada
    m13 = c.execute("SELECT id FROM medicoes WHERE contrato_id=? AND numero=13", (ids["propria"],)).fetchone()[0]
    nota(804, "2026-09-20", 1_000_000, medicao=m13)       # ligada a medicao ativa -> nada
    nota(805, "2026-08-15", 1_000_001, coligada=12, centro=None)   # consorcio (50%), competencia 07/2026 sem medicao
    c.commit()
    compl = diretoria.complemento_rm(c)
    assert compl == {ids["propria"]: {"2026-07": 900_001}, ids["consorcio"]: {"2026-07": 1_000_001}}
    depois = diretoria.painel(c, HOJE)
    cota = 900_001 + 500_001                              # 1.000.001 x 50% = 500.001 (arredondamento unico)
    assert depois["medido_ano"]["valor_centavos"] - antes["medido_ano"]["valor_centavos"] == cota
    # o saldo a executar cai o mesmo tanto (no consorcio, a cota e' aplicada uma vez sobre o saldo cheio: o meio centavo
    # do 1.000.001 cai do outro lado); a curva da carteira ganha o medido de 07/2026
    assert antes["carteira"]["saldo_centavos"] - depois["carteira"]["saldo_centavos"] == 900_001 + 500_000
    curva = lambda p: {s["competencia"]: s["medido_centavos"] for s in p["curva_carteira"]}
    assert curva(depois)["2026-07"] - curva(antes)["2026-07"] == cota
    # na tabela de obras (QDOP na tela), a nota sem medicao e' faturado e baixa o saldo da obra
    obra = lambda p, k: next(o for o in p["obras"] if o["contrato_id"] == ids[k])
    assert obra(depois, "propria")["faturados"] - obra(antes, "propria")["faturados"] == 900_001
    assert obra(antes, "propria")["saldo"] - obra(depois, "propria")["saldo"] == 900_001
    assert obra(depois, "consorcio")["faturados"] - obra(antes, "consorcio")["faturados"] == 500_001
    # a nota do RM nao diz se e' execucao ou reajuste: o complemento de execucao para no que falta executar da obra,
    # e o saldo nunca fica negativo por causa dele; a coluna "faturados" leva a nota inteira
    c.execute("UPDATE contratos SET valor_original_centavos=4400000 WHERE id=?", (ids["propria"],))
    c.commit()
    apertado = diretoria.painel(c, HOJE)
    assert obra(apertado, "propria")["saldo"] == 0
    assert obra(apertado, "propria")["faturados"] == obra(depois, "propria")["faturados"]
    c.execute("UPDATE contratos SET valor_original_centavos=100000000 WHERE id=?", (ids["propria"],))
    c.commit()
    # lancada a medicao da competencia, o complemento dela some
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
              "VALUES (?, 40, 'execucao', '2026-07', 'protocolada', 900001)", (ids["propria"],))
    c.commit()
    assert ids["propria"] not in diretoria.complemento_rm(c)


def test_planilha_gerada_nao_esconde_a_nota_do_rm(cenario):
    """#561 (gate Sol): a planilha gerada (ainda nao enviada) nao mede; logo, nao conta como lancada nem representa a
    nota do RM. Sem isso a nota sumia do complemento e a planilha tambem do medido: a Carteira ficava abaixo."""
    c, ids = cenario
    c.execute("UPDATE contratos SET centro_custo_rm='9.001.001' WHERE id=?", (ids["propria"],))
    gerada = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos) "
                       "VALUES (?, 41, 'execucao', '2026-07', 'planilha_gerada', 5000000)", (ids["propria"],)).lastrowid
    c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, centro_custo, codtmv) "
              "VALUES (1, 801, '801', '2026-08-10', 1000001, 'ativa', '9.001.001', '2.2.01')")
    c.commit()
    # competencia 07/2026: lancado so' a recebida de 100.000 (a gerada fica fora) -> faltam 900.001
    assert diretoria.complemento_rm(c) == {ids["propria"]: {"2026-07": 900_001}}
    # nota ligada a planilha gerada tambem nao e' "representada": entra pelo que passa do lancado
    nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, emissao, valor_centavos, situacao, centro_custo, codtmv) "
                    "VALUES (1, 802, '802', '2026-08-12', 300000, 'ativa', '9.001.001', '2.2.01')").lastrowid
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
              "VALUES (?, ?, 300000, 'detectado', 't')", (gerada, nid))
    c.commit()
    assert diretoria.complemento_rm(c) == {ids["propria"]: {"2026-07": 1_200_001}}
    # e o medido do mes nao soma a planilha gerada por cima da nota: so' a recebida de 100.000 e o complemento
    compl = diretoria._complemento_na_cota(c, diretoria.complemento_rm(c))
    assert diretoria._medido(diretoria._medicoes(c), "2026-07", compl) == 100_000 + 1_200_001


def test_fora_do_medido_e_o_complemento_da_lista_unica():
    """#561: FORA (Diretoria, Inicio, custo da obra) e `medicoes.ESTADOS_NO_MEDIDO` repartem os estados sem sobra."""
    assert not set(diretoria.FORA) & set(medicoes.ESTADOS_NO_MEDIDO)
    assert set(diretoria.FORA) | set(medicoes.ESTADOS_NO_MEDIDO) == set(medicoes.TRANSICOES)


def test_nota_desconsiderada_sai_do_faturado_e_do_a_receber_ao_centavo_e_volta(cenario):
    """Issue #638: a nota desconsiderada pela correcao de cadastro vale como cancelada. O faturado do RM no mes cai o valor
    dela na cota e o a receber cai o que faltava do titulo, na cota (centavo impar e consorcio de 50%); a nota que
    ficou continua contando, e `reconsiderar_nf` devolve tudo."""
    from app import contratos, correcao_medicoes, inicio
    c, ids = cenario
    c.execute("UPDATE contratos SET centro_custo_rm='9.001.001' WHERE id=?", (ids["propria"],))
    c.execute("UPDATE entidades SET coligada_rm=12 WHERE chave='cons'")

    def nota(idmov, valor, falta, coligada=1):
        nid = c.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, numero_int, emissao, valor_centavos, situacao, "
                        "codtmv, centro_custo) VALUES (?, ?, ?, ?, '2026-07-10', ?, 'ativa', '2.2.01', ?)",
                        (coligada, idmov, str(idmov), idmov, valor, "9.001.001" if coligada == 1 else None)).lastrowid
        c.execute("INSERT INTO baixas (coligada, idlan, nota_id, idmov, valor_original_centavos, valor_baixado_centavos, "
                  "status_lan) VALUES (?, ?, ?, ?, ?, 0, 0)", (coligada, idmov, nid, idmov, falta))
    nota(951, 1_000_001, 930_001)
    nota(952, 333_333, 300_001, coligada=12)          # consorcio: 50% de 333.333 = 166.667; de 300.001 = 150.001
    nota(953, 80_000, 80_000)
    c.commit()
    ids["liberar"]()

    def retrato():
        return (diretoria.rm_por_mes(c)[0]["2026-07"], _receber(c), inicio._a_receber(c, HOJE)["valor_centavos"],
                sorted(n for n, _ in _notas_rm(c)), diretoria.a_receber_por_obra(c)[ids["propria"]])
    antes = retrato()
    assert antes[3] == ["951", "952", "953"]
    assert (contratos.cota(333_333, 5000), contratos.cota(300_001, 5000)) == (166_667, 150_001)
    base = {"motivo": "cancelada na prefeitura e substituída", "fonte": "comprovante da prefeitura"}
    correcao_medicoes.executar(c, 1, [{"operacao": "desconsiderar_nf", "nf": 951, "coligada": 1, **base},
                                      {"operacao": "desconsiderar_nf", "nf": 952, "coligada": 12, **base}], ensaio=False)
    depois = retrato()
    assert depois[0] == antes[0] - 1_000_001 - 166_667
    assert depois[1] == antes[1] - 930_001 - 150_001
    assert depois[2] == antes[2] - 930_001 - 150_001
    assert depois[3] == ["953"]
    assert depois[4] == antes[4] - 930_001
    assert diretoria.complemento_rm(c).get(ids["propria"], {}).get("2026-06", 0) <= 80_000     # so' a nota que ficou
    correcao_medicoes.executar(c, 1, [{"operacao": "reconsiderar_nf", "nf": 951, "coligada": 1, "fonte": "conferência"},
                                      {"operacao": "reconsiderar_nf", "nf": 952, "coligada": 12, "fonte": "conferência"}],
                               ensaio=False)
    assert retrato() == antes
