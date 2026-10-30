import pytest
from app import auth, contratos, db

BASE = {"orgao": "SINFRA-MT", "numero_instrumento": "IC 082/2025",
        "objeto": "MT-388 Porto Esperidiao", "valor_original_centavos": 1_000_000_00,
        "vigencia_fim": "2027-12-31", "execucao_fim": "2027-06-30"}


def _conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn(); db.migrate(conn)
    # usuario_id=1 precisa existir: audit_log.usuario_id tem FK para usuarios(id).
    auth.criar_usuario(conn, "Leo", "leo@lotufo.com", "senha-forte-123", "admin")
    return conn


def test_criar_e_vigente_sem_aditivos(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = contratos.criar(conn, 1, BASE)
    v = contratos.vigente(conn, cid)
    assert v["valor_vigente_centavos"] == 1_000_000_00
    assert v["vigencia_fim_vigente"] == "2027-12-31"


def test_vigente_soma_deltas_assinados_em_ordem(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = contratos.criar(conn, 1, BASE)
    conn.execute("""INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos,
        status, data_assinatura) VALUES (?, 'valor', 30000000, 'assinado', '2026-03-01')""", (cid,))
    conn.execute("""INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos,
        nova_execucao_fim, status, data_assinatura)
        VALUES (?, 'misto', -12000000, '2027-09-30', 'assinado', '2026-06-01')""", (cid,))
    conn.execute("""INSERT INTO aditivos (contrato_id, tipo, delta_valor_centavos, status)
        VALUES (?, 'valor', 99999999, 'em_andamento')""", (cid,))  # nao conta
    conn.commit()
    v = contratos.vigente(conn, cid)
    assert v["valor_vigente_centavos"] == 1_000_000_00 + 300_000_00 - 120_000_00
    assert v["execucao_fim_vigente"] == "2027-09-30"


def test_estado_transicao_invalida(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = contratos.criar(conn, 1, BASE)
    contratos.mudar_estado(conn, 1, cid, "encerrado", "2026-08-01", None)
    with pytest.raises(ValueError):
        contratos.mudar_estado(conn, 1, cid, "suspenso", "2026-09-01", None)  # encerrado e terminal


def test_mudar_estado_condicional_rowcount(tmp_path, monkeypatch):
    # caminho feliz: ativo->suspenso continua funcionando com o UPDATE condicional
    conn = _conn(tmp_path, monkeypatch)
    cid = contratos.criar(conn, 1, BASE)
    contratos.mudar_estado(conn, 1, cid, "suspenso", "2026-08-01", "OS de paralisacao")
    assert conn.execute("SELECT estado FROM contratos WHERE id=?", (cid,)).fetchone()["estado"] == "suspenso"
    assert conn.execute("SELECT COUNT(*) FROM contrato_eventos WHERE contrato_id=?", (cid,)).fetchone()[0] == 1
    # contrato terminal: transicao barrada pela validacao em Python (comportamento preservado)
    contratos.mudar_estado(conn, 1, cid, "ativo", "2026-08-15", None)  # volta para ativo
    contratos.mudar_estado(conn, 1, cid, "encerrado", "2026-09-01", None)
    with pytest.raises(ValueError):
        contratos.mudar_estado(conn, 1, cid, "suspenso", "2026-09-15", None)


def test_retomar_contrato_de_entidade_desativada_rejeita(tmp_path, monkeypatch):
    """Achado do round 3, a outra porta da guarda de `entidades.desativar`: bastava
    suspender o contrato, desativar a entidade e retomar para chegar ao estado que a
    primeira porta proibe -- contrato em execucao pendurado num CNPJ que sumiu dos
    paineis e do checklist de protocolo."""
    from app import entidades
    conn = _conn(tmp_path, monkeypatch)
    eid = entidades.criar(conn, 1, {"nome": "Consórcio Norte", "cnpj": "11444777000161",
                                    "papel": "consorcio"})
    cid = contratos.criar(conn, 1, {**BASE, "entidade_id": eid})
    contratos.mudar_estado(conn, 1, cid, "suspenso", "2026-08-01", None)
    entidades.desativar(conn, 1, eid)          # com o contrato suspenso, isto e' legitimo

    with pytest.raises(ValueError, match="desativada"):
        contratos.mudar_estado(conn, 1, cid, "ativo", "2026-09-01", None)
    assert conn.execute("SELECT estado FROM contratos WHERE id=?",
                        (cid,)).fetchone()["estado"] == "suspenso"


def test_valor_original_congela_apos_protocolo(tmp_path, monkeypatch):
    from app import medicoes
    conn = _conn(tmp_path, monkeypatch)
    cid = contratos.criar(conn, 1, BASE)
    contratos.atualizar(conn, 1, cid, {"valor_original_centavos": 2_000_000_00})  # livre antes
    mid = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    medicoes.definir_valor(conn, 1, mid, "protocolado", 1_00, "manual")
    # apesar das pendencias: o banco de teste tem os tipos de certidao semeados e nenhuma
    # certidao anexada (fase 3,5 trava o protocolo); aqui o assunto e' o congelamento.
    medicoes.registrar_protocolo(conn, 1, mid, "2026-07-28", None, None, "manual", True, "teste de cenário")
    with pytest.raises(ValueError, match="congelado"):
        contratos.atualizar(conn, 1, cid, {"valor_original_centavos": 3_000_000_00})
    contratos.atualizar(conn, 1, cid, {"valor_original_centavos": 2_000_000_00, "objeto": "novo"})  # igual: passa
    assert contratos.vigente(conn, cid)["valor_vigente_centavos"] == 2_000_000_00


def test_cota_do_consorcio(tmp_path, monkeypatch):
    """Spec §3 decisão 14: a página da obra mostra o valor cheio do contrato, o
    consolidado soma a parte da Lotufo. Percentual em pontos-base para 33,3% ser exato."""
    from app import contratos as c
    assert c.cota(10_000_00, 10000) == 10_000_00        # obra própria: valor cheio
    assert c.cota(10_000_00, 5000) == 5_000_00          # Leblon 50%
    assert c.cota(10_000_00, 3330) == 3_330_00          # Deciolândia 33,3%
    assert c.cota(1, 3330) == 0                          # arredonda uma vez, meio para cima
    assert c.cota(2, 3330) == 1
    assert c.cota(None, 5000) is None
    conn = _conn(tmp_path, monkeypatch)
    cid = contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 041/2025",
                                    "objeto": "BRT", "valor_original_centavos": 76_032_712_00,
                                    "percentual_direito_bp": 4900})
    v = contratos.vigente(conn, cid)
    assert v["valor_vigente_centavos"] == 76_032_712_00      # o contrato é do consórcio
    assert v["cota_vigente_centavos"] == 37_256_028_88       # 49% é da Lotufo


def test_contrato_proprio_nasce_com_direito_integral(tmp_path, monkeypatch):
    conn = _conn(tmp_path, monkeypatch)
    cid = contratos.criar(conn, 1, {"orgao": "S", "numero_instrumento": "IC 1", "objeto": "X",
                                    "valor_original_centavos": 1_000_00})
    v = contratos.vigente(conn, cid)
    assert v["percentual_direito_bp"] == 10000
    assert v["cota_vigente_centavos"] == v["valor_vigente_centavos"]


def test_cabecalho_e_cadastro_da_obra(tmp_path, monkeypatch):
    import datetime
    import json
    conn = _conn(tmp_path, monkeypatch)
    cid = contratos.criar(conn, 1, BASE)
    conn.execute("UPDATE contratos SET encerramento_iniciado_em='2026-09-01' WHERE id=?", (cid,))
    conn.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, numero, data, dados) VALUES "
                 "(?, 'apost-1', 'apostilamento_reajuste', '1', '2026-05-10', ?)", (cid, json.dumps({"percentual": "4,21"})))
    conn.commit()
    cab = contratos.cabecalho(conn, cid, datetime.date(2027, 6, 20))
    assert cab["status"] == "em_encerramento" and cab["dias_execucao"] == 10 and cab["orgao"] == "SINFRA-MT"
    ap = contratos.cadastro_da_obra(conn, cid)["instrumentos"][0]
    assert ap["tipo"] == "apostilamento_reajuste" and ap["dados"]["percentual"] == "4,21"


def test_cabecalho_traz_o_inicio_da_execucao_e_da_vigencia(tmp_path, monkeypatch):
    """#160: as linhas do tempo da pagina da obra pedem a data de inicio; sem o cadastro dela, vem nula."""
    import datetime
    conn = _conn(tmp_path, monkeypatch)
    sem = contratos.criar(conn, 1, BASE)
    com = contratos.criar(conn, 1, {**BASE, "numero_instrumento": "IC 083/2025",
                                    "execucao_inicio": "2025-07-01", "vigencia_inicio": "2025-06-15"})
    hoje = datetime.date(2026, 1, 10)
    c = contratos.cabecalho(conn, com, hoje)
    assert c["execucao_inicio"] == "2025-07-01" and c["vigencia_inicio"] == "2025-06-15"
    c0 = contratos.cabecalho(conn, sem, hoje)
    assert c0["execucao_inicio"] is None and c0["vigencia_inicio"] is None


def test_lista_de_obras_traz_a_data_da_paralisacao_para_a_operacao(client, tmp_path):
    """"Paralisada desde" na lista: o aviso e' so' da diretoria, entao a data vem do proprio /api/contratos,
    tambem para obra suspensa (estado que o cadastro do QDOP usa para 'paralisada')."""
    import json
    conn = db.get_conn()
    auth.criar_usuario(conn, "Leo", "leo@lotufo.com", "senha-forte-123", "admin")
    auth.criar_usuario(conn, "Eng", "eng@lotufo.com", "senha-forte-123", "engenharia")
    cid = contratos.criar(conn, 1, BASE)
    contratos.mudar_estado(conn, 1, cid, "suspenso", "2026-08-01", None)
    conn.execute("INSERT INTO instrumentos (contrato_id, chave, tipo, data, dados) VALUES (?, 'par-1', 'paralisacao', "
                 "'2026-08-01', ?)", (cid, json.dumps({})))
    conn.commit()
    conn.close()
    r = client.post("/api/auth/login", json={"email": "eng@lotufo.com", "senha": "senha-forte-123"})
    assert r.status_code == 200, r.text
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))
    obra = next(o for o in client.get("/api/contratos").json() if o["id"] == cid)
    assert obra["estado"] == "suspenso" and obra["paralisada_desde"] == "2026-08-01"
