"""Importacao do ledger historico de faturamento (dashboard antiga -> nova)."""
import pytest

from app import auditoria, contratos, db, importar_ledger, medicoes


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    c.execute("UPDATE certidao_tipos SET aplicavel_por_padrao=0"); c.commit()
    from app import auth
    auth.criar_usuario(c, "U", "u@l.com", "senha-forte-123", "engenharia")
    yield c
    c.close()


def _contrato(conn, instrumento="074/2021/00/00-SINFRA"):
    return contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": instrumento,
                                     "objeto": "Obra", "valor_original_centavos": 100_000_00})


def _medicao_emitida(conn, cid, numero, valor, tipo="execucao"):
    mid = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": numero, "tipo": tipo, "competencia": "2026-07"})
    medicoes.definir_valor(conn, 1, mid, "protocolado", valor, "manual")
    medicoes.registrar_protocolo(conn, 1, mid, "2026-07-28", None, None, "manual")
    # bloco 3: o legado `nf_emitida` virou `protocolada` (a NF entra pela nota, nao por estado)
    return mid


def _nf_rm(conn, coligada, idmov, valor, numero="0000000001", codtmv="2.2.01"):
    conn.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, valor_centavos, emissao, situacao, codtmv) "
                 "VALUES (?,?,?,?,?, 'ativa', ?)", (coligada, idmov, numero, valor, "2026-08-10", codtmv))
    return conn.execute("SELECT id FROM notas_fiscais WHERE coligada=? AND idmov=?", (coligada, idmov)).fetchone()[0]


def _baixa(conn, nota_id, coligada, idlan, valor):
    conn.execute("INSERT INTO baixas (coligada, idlan, nota_id, valor_original_centavos, valor_baixado_centavos, "
                 "status_lan, data_baixa) VALUES (?,?,?,?,?,1,?)", (coligada, idlan, nota_id, valor, valor, "2026-09-01"))


CAD = [{"Id": 1, "Contrato": "074/2021/00/00"}]


def test_importa_liga_nf_do_rm_e_recebe_idempotente(conn):
    cid = _contrato(conn)
    mid = _medicao_emitida(conn, cid, 1, 500_00)
    nf = _nf_rm(conn, 1, 100, 500_00)
    _baixa(conn, nf, 1, 1, 500_00); conn.commit()
    itens = [{"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "1ª", "IdMovRM": 100,
              "ChaveIdempotencia": "RM:1:100", "NumNF": "0000000001", "ValorBruto": 500.00}]
    # dry-run nao grava
    dry = importar_ledger.importar(conn, 1, itens, CAD, aplicar=False)
    assert dry["alocadas"] == 1 and len(dry["plano"]) == 1
    assert medicoes.detalhe(conn, mid)["notas"] == []
    # aplica: liga a NF e o recebimento vem da baixa do RM
    r = importar_ledger.importar(conn, 1, itens, CAD, aplicar=True)
    assert r["alocadas"] == 1 and r["recebimentos"] == 1, r
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "recebida" and m["notas"][0]["regra"] == "ledger_rm"
    assert auditoria.verificar_cadeia(conn)
    # idempotente: rodar de novo nao cria nada
    r2 = importar_ledger.importar(conn, 1, itens, CAD, aplicar=True)
    assert (r2["alocadas"], r2["ja_alocada"]) == (0, 1), r2


def test_infere_coligada_do_consorcio_quando_chave_e_backfill(conn):
    """Item de backfill (ChaveIdempotencia 'MIG:...') sem coligada na chave: infere pela
    entidade da obra (consorcio) para achar a NF."""
    from app import entidades
    eid = entidades.criar(conn, 1, {"nome": "Consórcio Oriundi", "cnpj": "11444777000161",
                                    "papel": "consorcio", "coligada_rm": 12})
    cid = contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "074/2021/00/00-SINFRA",
                                    "objeto": "Atalaia", "valor_original_centavos": 100_00, "entidade_id": eid})
    mid = _medicao_emitida(conn, cid, 3, 900_00)
    nf = _nf_rm(conn, 12, 555, 900_00); conn.commit()
    itens = [{"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "3ª", "IdMovRM": 555,
              "ChaveIdempotencia": "MIG:159:FATURAMENTO:3:0000", "NumNF": "0000000005", "ValorBruto": 900.00}]
    r = importar_ledger.importar(conn, 1, itens, CAD, aplicar=True)
    assert r["alocadas"] == 1, r
    assert medicoes.detalhe(conn, mid)["notas"][0]["nota_id"] == nf


@pytest.mark.parametrize("codtmv", ["2.2.15", "2.2.10", None])
def test_nf_fora_da_cobranca_nao_cria_vinculo_e_e_relatada(conn, codtmv):
    """Issue #598: so' nota de cobranca ao orgao (`diretoria.CODTMV_COBRANCA`) vira vinculo automatico; a linha com
    nota de outro tipo (ou sem tipo) e' pulada e relatada."""
    cid = _contrato(conn)
    mid = _medicao_emitida(conn, cid, 1, 500_00)
    nf = _nf_rm(conn, 1, 100, 500_00, codtmv=codtmv)
    _baixa(conn, nf, 1, 1, 500_00); conn.commit()
    itens = [{"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "1ª", "IdMovRM": 100,
              "ChaveIdempotencia": "RM:1:100", "NumNF": "0000000001", "ValorBruto": 500.00}]
    r = importar_ledger.importar(conn, 1, itens, CAD, aplicar=True)
    assert (r["alocadas"], r["fora_da_cobranca"], r["plano"]) == (0, 1, []), r
    assert r["puladas_fora_da_cobranca"] == [{"medicao_id": mid, "nota_id": nf, "numero_nf": "0000000001",
                                              "codtmv": codtmv}]
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "protocolada" and m["notas"] == []


def test_classifica_sem_idmov_sem_medicao_sem_contrato_sem_nf(conn):
    cid = _contrato(conn)
    _medicao_emitida(conn, cid, 1, 500_00)
    itens = [
        {"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "1ª"},                       # sem IdMovRM
        {"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "9ª", "IdMovRM": 9,
         "ChaveIdempotencia": "RM:1:9"},                                                        # medicao 9 nao existe
        {"ObraId": 99, "TipoDocumento": "Medição", "MedicaoRotulo": "1ª", "IdMovRM": 1,
         "ChaveIdempotencia": "RM:1:1"},                                                        # obra nao mapeada
        {"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "1ª", "IdMovRM": 777,
         "ChaveIdempotencia": "RM:1:777"},                                                      # NF nao sincronizada
    ]
    r = importar_ledger.importar(conn, 1, itens, CAD, aplicar=True)
    assert r["alocadas"] == 0
    assert (r["sem_idmov"], r["sem_medicao"], r["sem_contrato"], r["sem_nf_rm"]) == (1, 1, 1, 1), r


def test_reajuste_casa_a_medicao_de_reajuste_nao_a_de_execucao(conn):
    cid = _contrato(conn)
    m_ex = _medicao_emitida(conn, cid, 5, 300_00, tipo="execucao")
    m_re = _medicao_emitida(conn, cid, 5, 40_00, tipo="reajuste")
    nf = _nf_rm(conn, 1, 200, 40_00); conn.commit()  # noqa: F841
    itens = [{"ObraId": 1, "TipoDocumento": "Reajuste", "MedicaoRotulo": "5ª", "IdMovRM": 200,
              "ChaveIdempotencia": "RM:1:200", "ValorBruto": 40.00}]
    r = importar_ledger.importar(conn, 1, itens, CAD, aplicar=True)
    assert r["alocadas"] == 1
    assert medicoes.detalhe(conn, m_re)["notas"] and medicoes.detalhe(conn, m_ex)["notas"] == []


def test_cria_medicao_faltante_soma_nfs_e_depois_importar_liga_e_recebe(conn):
    """A medicao nao existe na lista antiga, mas ha' duas NFs do RM (mesmo rotulo) com
    baixa: cria UMA medicao protocolada no valor da SOMA; o importar liga as duas e
    recebe pela baixa."""
    cid = _contrato(conn)
    nf1 = _nf_rm(conn, 1, 301, 300_00, "0000000301")
    nf2 = _nf_rm(conn, 1, 302, 200_00, "0000000302")
    _baixa(conn, nf1, 1, 11, 300_00); _baixa(conn, nf2, 1, 12, 200_00); conn.commit()
    itens = [{"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "15ª", "IdMovRM": 301,
              "ChaveIdempotencia": "RM:1:301", "ValorBruto": 300.00, "Competencia": "02/2026"},
             {"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "15ª", "IdMovRM": 302,
              "ChaveIdempotencia": "RM:1:302", "ValorBruto": 200.00, "Competencia": "02/2026"}]
    # dry-run nao grava
    dry = importar_ledger.criar_medicoes_faltantes(conn, 1, itens, CAD, aplicar=False)
    assert (dry["grupos"], dry["criadas"], dry["nfs_cobertas"]) == (1, 0, 2), dry
    assert medicoes.listar(conn, cid) == []
    # aplica: cria a medicao no valor da soma, protocolada, competencia normalizada
    r = importar_ledger.criar_medicoes_faltantes(conn, 1, itens, CAD, aplicar=True)
    assert r["criadas"] == 1
    mid = r["plano"][0]["medicao_id"]
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "protocolada" and m["valor_protocolado_centavos"] == 500_00
    assert m["competencia"] == "2026-02" and m["numero"] == 15
    assert auditoria.verificar_cadeia(conn)
    # o importar liga as duas NFs e o recebimento vem das baixas do RM
    r2 = importar_ledger.importar(conn, 1, itens, CAD, aplicar=True)
    assert (r2["alocadas"], r2["recebimentos"]) == (2, 1), r2
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "recebida" and len(m["notas"]) == 2
    # idempotente: a medicao ja' existe, nao cria de novo
    r3 = importar_ledger.criar_medicoes_faltantes(conn, 1, itens, CAD, aplicar=True)
    assert (r3["criadas"], r3["ja_tem_medicao"]) == (0, 2), r3


def test_grupo_parcialmente_invalido_nao_cria_nada(conn):
    """Duas NFs do mesmo rotulo, uma com valor divergente: o grupo INTEIRO cai -- nunca
    nasce medicao com valor parcial."""
    cid = _contrato(conn)
    _nf_rm(conn, 1, 401, 300_00, "0000000401")
    _nf_rm(conn, 1, 402, 200_00, "0000000402"); conn.commit()
    itens = [{"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "15ª", "IdMovRM": 401,
              "ChaveIdempotencia": "RM:1:401", "ValorBruto": 300.00, "Competencia": "02/2026"},
             {"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "15ª", "IdMovRM": 402,
              "ChaveIdempotencia": "RM:1:402", "ValorBruto": 999.99, "Competencia": "02/2026"}]  # bruto != NF
    r = importar_ledger.criar_medicoes_faltantes(conn, 1, itens, CAD, aplicar=True)
    assert (r["criadas"], r["grupos"], r["valor_divergente"]) == (0, 0, 1), r
    assert r["grupo_incompleto"] == 1 and medicoes.listar(conn, cid) == []


def test_nf_fora_da_cobranca_no_grupo_nao_cria_medicao(conn):
    """Issue #598: uma NF do grupo e' de fornecedor (2.2.15): o grupo inteiro cai, sem medicao nascida dela."""
    cid = _contrato(conn)
    _nf_rm(conn, 1, 411, 300_01, "0000000411")
    _nf_rm(conn, 1, 412, 200_00, "0000000412", codtmv="2.2.15"); conn.commit()
    itens = [{"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "15ª", "IdMovRM": 411,
              "ChaveIdempotencia": "RM:1:411", "ValorBruto": 300.01, "Competencia": "02/2026"},
             {"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "15ª", "IdMovRM": 412,
              "ChaveIdempotencia": "RM:1:412", "ValorBruto": 200.00, "Competencia": "02/2026"}]
    r = importar_ledger.criar_medicoes_faltantes(conn, 1, itens, CAD, aplicar=True)
    assert (r["criadas"], r["fora_da_cobranca"], r["grupo_incompleto"]) == (0, 1, 1), r
    assert medicoes.listar(conn, cid) == []


def test_nota_ja_ligada_conta_como_ja_alocada_mesmo_fora_da_cobranca(conn):
    """Issue #598: rodar o importar de novo sobre um vinculo que ja' existe continua relatando `ja_alocada`; o relato
    de puladas fica so' para vinculo que seria criado agora."""
    from app import sincronizacao_rm
    cid = _contrato(conn)
    mid = _medicao_emitida(conn, cid, 1, 500_00)
    nf = _nf_rm(conn, 1, 100, 500_00, codtmv="2.2.15"); conn.commit()
    with db.mutacao(conn):
        sincronizacao_rm.alocar(conn, 1, nf, mid, "detectado", 1.0, "ledger_rm")
    itens = [{"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "1ª", "IdMovRM": 100,
              "ChaveIdempotencia": "RM:1:100", "NumNF": "0000000001", "ValorBruto": 500.00}]
    r = importar_ledger.importar(conn, 1, itens, CAD, aplicar=False)
    assert (r["ja_alocada"], r["fora_da_cobranca"], r["puladas_fora_da_cobranca"]) == (1, 0, []), r


def test_competencia_invalida_recusa_o_grupo(conn):
    cid = _contrato(conn)
    _nf_rm(conn, 1, 501, 100_00, "0000000501"); conn.commit()
    itens = [{"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "7ª", "IdMovRM": 501,
              "ChaveIdempotencia": "RM:1:501", "ValorBruto": 100.00, "Competencia": "13/2024"}]
    r = importar_ledger.criar_medicoes_faltantes(conn, 1, itens, CAD, aplicar=True)
    assert (r["criadas"], r["sem_competencia"]) == (0, 1), r
    assert medicoes.listar(conn, cid) == []


def test_nf_duplicada_no_grupo_conta_uma_vez(conn):
    """A mesma NF listada duas vezes no ledger nao dobra o valor da medicao."""
    cid = _contrato(conn)  # noqa: F841
    _nf_rm(conn, 1, 601, 250_00, "0000000601"); conn.commit()
    item = {"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "8ª", "IdMovRM": 601,
            "ChaveIdempotencia": "RM:1:601", "ValorBruto": 250.00, "Competencia": "03/2026"}
    r = importar_ledger.criar_medicoes_faltantes(conn, 1, [item, dict(item)], CAD, aplicar=True)
    assert r["criadas"] == 1
    m = medicoes.detalhe(conn, r["plano"][0]["medicao_id"])
    assert m["valor_protocolado_centavos"] == 250_00, m["valor_protocolado_centavos"]


def test_nf_reivindicada_por_dois_grupos_recusa_ambos(conn):
    """A mesma NF citada em dois rotulos: nenhuma medicao nasce -- nem mesmo a do grupo cujos
    outros membros seriam validos (invariante 'mesma NF em 2 grupos recusa ambos')."""
    cid = _contrato(conn)
    _nf_rm(conn, 1, 700, 100_00, "0000000700"); conn.commit()   # so' a 700 existe (a 999 nao)
    itens = [{"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "30ª", "IdMovRM": 700,
              "ChaveIdempotencia": "RM:1:700", "ValorBruto": 100.00, "Competencia": "01/2026"},   # grupo A (valido)
             {"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "31ª", "IdMovRM": 700,
              "ChaveIdempotencia": "RM:1:700", "ValorBruto": 100.00, "Competencia": "01/2026"},   # grupo B, mesma NF
             {"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "31ª", "IdMovRM": 999,
              "ChaveIdempotencia": "RM:1:999", "ValorBruto": 50.00, "Competencia": "01/2026"}]     # grupo B, NF ausente
    r = importar_ledger.criar_medicoes_faltantes(conn, 1, itens, CAD, aplicar=True)
    assert r["criadas"] == 0 and r["nf_duplicada"] >= 1, r
    assert medicoes.listar(conn, cid) == []


def test_cria_por_chave_mig_de_backfill_com_conferencia_de_valor(conn):
    """Backfill (ChaveIdempotencia 'MIG:...') sem coligada na chave: a coligada vem da
    entidade e a conferencia de valor e' a trava -- o mesmo que o importar ja' faz."""
    cid = _contrato(conn)                        # entidade default = Lotufo (coligada 1)  # noqa: F841
    _nf_rm(conn, 1, 223731, 278_509_92, "0000002081"); conn.commit()
    itens = [{"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "23ª", "IdMovRM": 223731,
              "ChaveIdempotencia": "MIG:172:FATURAMENTO:23:2081", "ValorBruto": 278509.92,
              "Competencia": "01/2026"}]
    r = importar_ledger.criar_medicoes_faltantes(conn, 1, itens, CAD, aplicar=True)
    assert r["criadas"] == 1, r
    m = medicoes.detalhe(conn, r["plano"][0]["medicao_id"])
    assert m["valor_protocolado_centavos"] == 278_509_92 and m["numero"] == 23
    # mas se o valor NAO bate, o backfill nao cria (trava contra coligada inferida errada):
    # outra medicao (24), NF com valor diferente do ValorBruto do ledger
    _nf_rm(conn, 1, 223999, 500_00, "0000002099"); conn.commit()
    outro = [{"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "24ª", "IdMovRM": 223999,
              "ChaveIdempotencia": "MIG:172:FATURAMENTO:24:2099", "ValorBruto": 111.11,
              "Competencia": "02/2026"}]
    r2 = importar_ledger.criar_medicoes_faltantes(conn, 1, outro, CAD, aplicar=False)
    assert (r2["criadas"], r2["grupos"], r2["valor_divergente"]) == (0, 0, 1), r2


def test_nao_cria_quando_a_nf_esta_em_outra_coligada_que_a_entidade(conn):
    """Guard da decisao 2026-09-09: NF numa coligada diferente da entidade do contrato
    (BR-163: entidade coligada 20, NF na 6 = Arica) NAO vira medicao."""
    from app import entidades
    eid = entidades.criar(conn, 1, {"nome": "Consórcio BR-163", "cnpj": "31200909000117",
                                    "papel": "consorcio", "coligada_rm": 20})
    cid = contratos.criar(conn, 1, {"orgao": "—", "numero_instrumento": "074/2021/00/00-SINFRA",
                                    "objeto": "Rota do Oeste", "valor_original_centavos": 100_00,
                                    "entidade_id": eid})
    _nf_rm(conn, 6, 14814, 201_667_57, "0000000106"); conn.commit()
    itens = [{"ObraId": 1, "TipoDocumento": "Medição", "MedicaoRotulo": "14ª", "IdMovRM": 14814,
              "ChaveIdempotencia": "RM:6:14814", "ValorBruto": 201667.57, "Competencia": "12/2024"}]
    r = importar_ledger.criar_medicoes_faltantes(conn, 1, itens, CAD, aplicar=True)
    assert (r["criadas"], r["coligada_divergente"]) == (0, 1), r
    assert medicoes.listar(conn, cid) == []
