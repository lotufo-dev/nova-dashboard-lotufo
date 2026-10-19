"""Fase 5: cliente do RM (parser) e sincronizacao com o simulador.

O simulador le `<pasta>/<CODIGO>.json` no formato exato da API (chaves NULL omitidas,
datas com fuso, decimais de 4 casas) -- os fixtures abaixo sao montados assim.
"""
import json
import pathlib

import pytest

from app import auditoria, contratos, db, documentos, entidades, medicoes, rm, sincronizacao_rm


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn(); db.migrate(c)
    # tipos de certidao semeados nao interessam aqui (o protocolo assume a pendencia)
    c.execute("UPDATE certidao_tipos SET aplicavel_por_padrao=0"); c.commit()
    # ... nem a lista de documentos do orgao quando o teste aplica o cadastro REAL (bloco 4)
    monkeypatch.setattr(documentos, "exigidos",
                        lambda conn, cid, natureza: {"entidades": [], "tipos": [], "regularidade": None})
    yield c
    c.close()


def _simulador(tmp_path, nfs, baixas):
    pasta = tmp_path / "rm"
    pasta.mkdir(exist_ok=True)
    (pasta / f"{rm.CONSULTA_NF}.json").write_text(json.dumps(nfs), encoding="utf-8")
    (pasta / f"{rm.CONSULTA_BAIXA}.json").write_text(json.dumps(baixas), encoding="utf-8")
    return rm.SimuladorRM(pasta)


def _nf(idmov, valor, coligada=1, numero=None, campo=None, status="F", emissao="2026-08-10T00:00:00-04:00",
        centro_custo=None):
    d = {"IDMOV": idmov, "CODCOLIGADA": coligada, "NUMEROMOV": numero or f"{idmov:010d}", "SERIE": "1",
         "DATAEMISSAO": emissao, "VALORBRUTO": valor, "CODTMV": "2.2.01", "STATUS": status}
    if campo:
        d["CAMPOLIVRE1"] = campo
    if centro_custo:
        d["CODCCUSTO"] = centro_custo
    return d


def _baixa(idlan, idmov, original, baixado, status, data=None, coligada=1):
    d = {"IDLAN": idlan, "CODCOLIGADA": coligada, "IDMOV": idmov, "NUMERODOCUMENTO": f"{idmov}\\1",
         "VALORORIGINAL": original, "VALORBAIXADO": baixado, "STATUSLAN": status}
    if data:
        d["DATABAIXA"] = data
    return d


def _tem_nf(conn, mid) -> bool:
    """Bloco 3: alocar nao muda mais o estado (protocolada fica protocolada); casou = tem NF vinculada."""
    return bool(medicoes.detalhe(conn, mid)["notas"])


def _medicao(conn, cid, numero, valor, comp="2026-07", tipo="execucao"):
    mid = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": numero, "tipo": tipo, "competencia": comp})
    medicoes.definir_valor(conn, 1, mid, "protocolado", valor, "manual")
    medicoes.registrar_protocolo(conn, 1, mid, f"{comp}-28", None, None, "manual")
    return mid


@pytest.fixture
def cid(conn):
    from app import auth
    auth.criar_usuario(conn, "U", "u@l.com", "senha-forte-123", "engenharia")
    return contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 082/2025",
                                     "objeto": "Obra", "valor_original_centavos": 10_000_000_00})


# --- parser ---

def test_centavos_exatos_e_data_plausivel():
    import datetime
    hoje = datetime.date(2026, 9, 2)
    assert rm.centavos(1128.8755) == 112888          # meio para cima, sem float*100
    assert rm.centavos("179254.4518") == 17925445
    assert rm.centavos(None) == 0
    assert rm.data("2026-08-25T00:00:00-04:00", hoje) == "2026-08-25"
    assert rm.data("2036-06-16T00:00:00-04:00", hoje) is None   # typo real do spike
    assert rm.data(None) is None and rm.data("lixo") is None
    assert rm.data("2028-03-01", datetime.date(2028, 2, 29)) == "2028-03-01"   # 29/02 nao estoura


def test_cliente_recusa_http_sem_flag(monkeypatch):
    with pytest.raises(rm.ErroRM):
        rm.ClienteRM("http://rm.exemplo.local:8000", "U", "s")
    assert rm.ClienteRM("http://rm.exemplo.local:8000", "U", "s", permitir_http=True).url.startswith("http://")
    monkeypatch.setenv("DASH_RM_URL", "http://rm.exemplo.local:8000")
    monkeypatch.setenv("DASH_RM_USUARIO", "U")
    monkeypatch.setenv("DASH_RM_SENHA", "s")
    monkeypatch.delenv("DASH_RM_SIMULADOR", raising=False)
    assert rm.de_ambiente() is None                     # sem a flag, nao configura
    monkeypatch.setenv("DASH_RM_HTTP_INSEGURO", "1")
    assert isinstance(rm.de_ambiente(), rm.ClienteRM)


def test_interpretar_campo_livre():
    f = sincronizacao_rm.interpretar_campo_livre
    assert f("IC 082/2025 - 12") == ("IC 082/2025", 12, "execucao")
    assert f("ic 082/2025 - 12ª REAJ") == ("IC 082/2025", 12, "reajuste")
    assert f("CT-271-LT-2026 / medição 3 proj") == ("CT-271-LT-2026", 3, "projeto")
    assert f("qualquer coisa") is None and f(None) is None


# --- sincronizacao ---

def test_campo_livre_aloca_sem_mudar_estado(conn, cid, tmp_path):
    mid = _medicao(conn, cid, 12, 461_900_00)
    cli = _simulador(tmp_path, [_nf(100, 461900.0, campo="IC 082/2025 - 12")], [])
    r = sincronizacao_rm.sincronizar(conn, cli, "manual")
    assert r["estado"] == "success" and r["alocacoes"] == 1, r
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "protocolada" and m["notas"]
    assert m["notas"][0]["regra"] == "campo_livre1" and m["notas"][0]["origem"] == "detectado"
    # idempotente: a segunda rodada nao aloca de novo nem cria sugestao
    r2 = sincronizacao_rm.sincronizar(conn, cli, "agendado")
    assert (r2["alocacoes"], r2["sugestoes"]) == (0, 0)
    assert conn.execute("SELECT COUNT(*) FROM notas_fiscais").fetchone()[0] == 1
    assert auditoria.verificar_cadeia(conn)


def test_valor_exato_unico_aloca_e_proximo_fica_sem_alocacao(conn, cid, tmp_path):
    m1 = _medicao(conn, cid, 1, 100_000_00, "2026-07")
    m2 = _medicao(conn, cid, 2, 200_000_00, "2026-08")
    m3 = _medicao(conn, cid, 3, 201_000_00, "2026-09")
    cli = _simulador(tmp_path, [_nf(1, 100000.0), _nf(2, 200500.0), _nf(3, 999.0)], [])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert (r["alocacoes"], r["sugestoes"]) == (1, 1), r     # `sugestoes` da rodada = NFs ambiguas
    assert _tem_nf(conn, m1)
    assert not _tem_nf(conn, m2) and not _tem_nf(conn, m3)
    # a ambigua (2) e a sem candidato (3) ficam na reconciliacao
    rec = sincronizacao_rm.reconciliacao(conn)
    assert sorted(n["idmov"] for n in rec["nfs_sem_medicao"]) == [2, 3]


def test_reconciliacao_pagina_as_nfs_sem_medicao_com_total_exato(conn, cid, tmp_path):
    """#22: a lista vem em paginas de 200, com o total exato; a segunda pagina traz o resto, sem repetir."""
    cli = _simulador(tmp_path, [_nf(i, 999.0) for i in range(1, 251)], [])
    sincronizacao_rm.sincronizar(conn, cli)
    rec = sincronizacao_rm.reconciliacao(conn)
    assert rec["totais"]["nfs_sem_medicao"] == 250
    assert len(rec["nfs_sem_medicao"]) == 200 and rec["ha_mais"]["nfs_sem_medicao"] is True
    seg = sincronizacao_rm.reconciliacao(conn, nfs_apos=rec["nfs_sem_medicao"][-1]["id"])
    assert seg["totais"]["nfs_sem_medicao"] == 250
    assert len(seg["nfs_sem_medicao"]) == 50 and seg["ha_mais"]["nfs_sem_medicao"] is False
    ids = [n["idmov"] for n in rec["nfs_sem_medicao"] + seg["nfs_sem_medicao"]]
    assert sorted(ids) == list(range(1, 251))


def test_reconciliacao_pagina_pelo_cursor_nao_pula_quando_a_lista_muda(conn, cid, tmp_path):
    """#22 (gate Sol S1): entre uma pagina e outra a sincronizacao aloca uma NF da primeira, traz uma nova e corrige
    a emissao de NFs das duas paginas, para tras e para frente; a segunda continua de onde a primeira parou, sem
    repetir nem pular nenhuma, porque o cursor e' o id (que nao muda)."""
    nfs = [_nf(i, 999.0, emissao=f"2026-08-{(i % 28) + 1:02d}T00:00:00-04:00") for i in range(1, 251)]
    sem_data = _nf(251, 999.0); del sem_data["DATAEMISSAO"]
    sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, nfs + [sem_data], []))
    rec = sincronizacao_rm.reconciliacao(conn)
    primeira = [n["id"] for n in rec["nfs_sem_medicao"]]
    idmov_da = {n["id"]: n["idmov"] for n in rec["nfs_sem_medicao"]}
    # some uma da primeira pagina (alocada), entra uma mais nova
    mid = _medicao(conn, cid, 1, 123_00)   # valor que nao casa com as NFs na sincronizacao seguinte
    conn.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem) VALUES (?, ?, 99900, 'manual')",
                 (mid, primeira[0])); conn.commit()
    # o RM corrige emissoes: a ultima da primeira pagina vai para bem antes, uma da segunda vai para bem depois
    ult = idmov_da[primeira[-1]]
    nfs[ult - 1] = _nf(ult, 999.0, emissao="2026-07-01T00:00:00-04:00")
    nfs[0] = _nf(1, 999.0, emissao="2026-09-29T00:00:00-04:00")
    sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, nfs + [sem_data, _nf(300, 999.0, emissao="2026-09-30T00:00:00-04:00")], []))
    seg = sincronizacao_rm.reconciliacao(conn, nfs_apos=primeira[-1])
    segunda = [n["id"] for n in seg["nfs_sem_medicao"]]
    todas = conn.execute("SELECT id FROM notas_fiscais WHERE idmov <= 251").fetchall()
    assert set(primeira) & set(segunda) == set()
    assert sorted(primeira + segunda) == sorted(r[0] for r in todas)
    assert seg["ha_mais"]["nfs_sem_medicao"] is False


def test_reconciliacao_le_lista_e_total_no_mesmo_retrato(conn, cid, tmp_path):
    """#22: a sincronizacao grava uma NF nova entre a leitura da lista e a do total; os dois saem do mesmo retrato
    do banco (total 3, nao 4), e a conexao nao fica com transacao aberta."""
    sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, [_nf(i, 999.0) for i in (1, 2, 3)], []))
    outra = db.get_conn()
    gravou = []

    def no_meio(sql):
        if not gravou and sql.lstrip().startswith("SELECT COUNT(*)") and "notas_fiscais n" in sql:
            outra.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, valor_centavos) VALUES (1, 99, '99', 100)")
            outra.commit()
            gravou.append(True)
    conn.set_trace_callback(no_meio)
    try:
        rec = sincronizacao_rm.reconciliacao(conn)
    finally:
        conn.set_trace_callback(None); outra.close()
    assert gravou
    assert len(rec["nfs_sem_medicao"]) == 3 and rec["totais"]["nfs_sem_medicao"] == 3
    assert not conn.in_transaction
    assert sincronizacao_rm.reconciliacao(conn)["totais"]["nfs_sem_medicao"] == 4


def test_nota_ambigua_nao_vira_sugestao(conn, cid, tmp_path):
    """Bloco 9 (decisao 3): NF so' proxima de uma medicao fica sem alocacao e sem fila; quem resolve
    e' o "vincular nota" da medicao."""
    mid = _medicao(conn, cid, 1, 100_000_00)
    cli = _simulador(tmp_path, [_nf(1, 101000.0)], [])   # 1% acima: proximo, nao exato
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert (r["alocacoes"], r["sugestoes"]) == (0, 1), r
    assert not _tem_nf(conn, mid)
    assert conn.execute("SELECT COUNT(*) FROM arquivo_sugestoes").fetchone()[0] == 0
    assert auditoria.verificar_cadeia(conn)


def test_baixas_movem_para_recebida_e_parcial_fica(conn, cid, tmp_path):
    # NF bruto R$ 1.000 partida em DOIS titulos (liquido 500 + 424 = 924); so' recebe quando
    # os dois entram. `devido` SOMA os titulos (cada idlan e' um titulo distinto).
    mid = _medicao(conn, cid, 12, 1000_00)
    nfs = [_nf(100, 1000.0, campo="IC 082/2025 - 12")]
    cli = _simulador(tmp_path, nfs, [_baixa(1, 100, 500.0, 500.0, 1, "2026-09-01T00:00:00-04:00"),
                                     _baixa(2, 100, 424.0, 0.0, 0)])                 # 2o titulo aberto
    sincronizacao_rm.sincronizar(conn, cli)
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "protocolada" and m["notas"][0]["recebido_centavos"] == 500_00   # parcial fica
    cli = _simulador(tmp_path, nfs, [_baixa(1, 100, 500.0, 500.0, 1, "2026-09-01T00:00:00-04:00"),
                                     _baixa(2, 100, 424.0, 424.0, 1, "2036-09-15T00:00:00-04:00")])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert r["recebimentos"] == 1
    m = medicoes.detalhe(conn, mid)
    # a data implausivel (2036) nao entra: a baixa valida e' a de setembro
    assert m["estado"] == "recebida" and m["recebida_em"] == "2026-09-01"
    b = conn.execute("SELECT data_baixa, data_baixa_bruta FROM baixas WHERE idlan=2").fetchone()
    assert b["data_baixa"] is None and b["data_baixa_bruta"].startswith("2036")


def test_recebida_pelo_titulo_liquido_mesmo_com_retencao(conn, cid, tmp_path):
    """A baixa do RM e' o LIQUIDO (titulo = bruto - ISS/INSS/IRRF). A medicao vira recebida
    quando o titulo esta quitado, mesmo com o recebido MENOR que o bruto da NF."""
    mid = _medicao(conn, cid, 12, 1000_00)
    nfs = [_nf(100, 1000.0, campo="IC 082/2025 - 12")]                          # NF bruto R$ 1.000
    cli = _simulador(tmp_path, nfs, [_baixa(1, 100, 924.0, 924.0, 1, "2026-09-01T00:00:00-04:00")])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert r["recebimentos"] == 1, r
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "recebida" and m["recebida_em"] == "2026-09-01"
    assert (m["notas"][0]["recebido_centavos"], m["notas"][0]["devido_centavos"]) == (924_00, 924_00)


def test_titulo_aberto_nao_recebe(conn, cid, tmp_path):
    """Titulo a receber ainda aberto (status 0, nada baixado) segura a medicao em protocolada."""
    mid = _medicao(conn, cid, 12, 1000_00)
    nfs = [_nf(100, 1000.0, campo="IC 082/2025 - 12")]
    cli = _simulador(tmp_path, nfs, [_baixa(1, 100, 924.0, 0.0, 0, "2026-09-01T00:00:00-04:00")])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert r["recebimentos"] == 0
    assert _tem_nf(conn, mid)


def _eventos_diferenca(conn, mid) -> list[dict]:
    return [json.loads(r["depois"]) for r in conn.execute(
        "SELECT depois FROM audit_log WHERE acao='medicao.recebida_com_diferenca' AND entidade='medicao' "
        "AND entidade_id=? ORDER BY id", (str(mid),))]


@pytest.mark.parametrize("pago, recebe", [
    (924.00, True),    # quitado: sem diferenca
    (923.99, True),    # 1 centavo a menos (centavo impar)
    (923.20, True),    # R$ 0,80 a menos
    (923.00, True),    # R$ 1,00 a menos: no limite, ainda recebe
    (922.99, False),   # R$ 1,01 a menos: passa do limite
    (779.04, False),   # R$ 144,96 a menos
])
def test_tolerancia_de_recebimento_ate_um_real(conn, cid, tmp_path, pago, recebe):
    """Issue #35 (decisao do Leo, 19/10/2026): titulo pago ate' R$ 1,00 abaixo do devido fecha a medicao como
    recebida; acima disso fica aberta para conferencia. Sem tolerancia percentual."""
    mid = _medicao(conn, cid, 12, 1000_00)
    cli = _simulador(tmp_path, [_nf(100, 1000.0, campo="IC 082/2025 - 12")],
                     [_baixa(1, 100, 924.0, pago, 1, "2026-09-01T00:00:00-04:00")])
    r = sincronizacao_rm.sincronizar(conn, cli)
    m = medicoes.detalhe(conn, mid)
    assert (r["recebimentos"], m["estado"]) == ((1, "recebida") if recebe else (0, "protocolada"))
    if recebe:
        assert m["recebida_em"] == "2026-09-01"
    assert auditoria.verificar_cadeia(conn)


def test_tolerancia_nao_alcanca_diferenca_grande(conn, cid, tmp_path):
    """O caso de R$ 2.016,48 a menos do backlog continua aberto para conferencia, sem evento de diferenca."""
    mid = _medicao(conn, cid, 12, 50_000_00)
    cli = _simulador(tmp_path, [_nf(100, 50_000.0, campo="IC 082/2025 - 12")],
                     [_baixa(1, 100, 46_200.0, 44_183.52, 1, "2026-09-01T00:00:00-04:00")])
    assert sincronizacao_rm.sincronizar(conn, cli)["recebimentos"] == 0
    assert medicoes.detalhe(conn, mid)["estado"] == "protocolada"
    assert _eventos_diferenca(conn, mid) == []


def test_recebida_com_diferenca_audita_evento_novo(conn, cid, tmp_path):
    """A diferenca aceita vai para a auditoria como evento proprio (quem: o sistema), ao lado da mudanca de estado;
    nada sobrescrito. Medicao com duas notas: a tolerancia vale por titulo e o evento lista so' a que ficou curta."""
    mid = _medicao(conn, cid, 12, 1500_00)
    nfs = [_nf(100, 1000.0, campo="IC 082/2025 - 12"), _nf(101, 500.0, campo="IC 082/2025 - 12")]
    cli = _simulador(tmp_path, nfs, [_baixa(1, 100, 924.0, 923.99, 1, "2026-09-01T00:00:00-04:00"),
                                     _baixa(2, 101, 462.0, 462.0, 1, "2026-09-03T00:00:00-04:00")])
    assert sincronizacao_rm.sincronizar(conn, cli)["recebimentos"] == 1
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["recebida_em"]) == ("recebida", "2026-09-03")
    nota = conn.execute("SELECT id, numero FROM notas_fiscais WHERE idmov=100").fetchone()
    assert _eventos_diferenca(conn, mid) == [{
        "diferenca_centavos": 1, "tolerancia_centavos": 100,
        "notas": [{"nota_id": nota["id"], "numero": nota["numero"], "devido_centavos": 924_00,
                   "recebido_centavos": 923_99, "diferenca_centavos": 1}]}]
    linha = conn.execute("SELECT usuario_id FROM audit_log WHERE acao='medicao.recebida_com_diferenca'").fetchone()
    assert linha["usuario_id"] is None
    assert auditoria.verificar_cadeia(conn)
    # rodada seguinte: a medicao ja' e' recebida, nada de novo evento
    sincronizacao_rm.sincronizar(conn, cli)
    assert len(_eventos_diferenca(conn, mid)) == 1


def test_titulo_quitado_sem_diferenca_nao_gera_evento(conn, cid, tmp_path):
    mid = _medicao(conn, cid, 12, 1000_00)
    cli = _simulador(tmp_path, [_nf(100, 1000.0, campo="IC 082/2025 - 12")],
                     [_baixa(1, 100, 924.0, 924.0, 1, "2026-09-01T00:00:00-04:00")])
    sincronizacao_rm.sincronizar(conn, cli)
    assert medicoes.detalhe(conn, mid)["estado"] == "recebida"
    assert _eventos_diferenca(conn, mid) == []


def test_tolerancia_exige_baixa_no_titulo(conn, cid, tmp_path):
    """Titulo pequeno (ate' R$ 1,00) sem baixa nenhuma nao e' 'pago com diferenca': nada foi recebido."""
    mid = _medicao(conn, cid, 12, 1000_00)
    cli = _simulador(tmp_path, [_nf(100, 1000.0, campo="IC 082/2025 - 12")],
                     [_baixa(1, 100, 0.80, 0.0, 0)])
    assert sincronizacao_rm.sincronizar(conn, cli)["recebimentos"] == 0
    assert medicoes.detalhe(conn, mid)["estado"] == "protocolada"


@pytest.mark.parametrize("titulos", [
    [(923.20, 923.20, 1), (0.80, 0.0, 0)],     # NF em dois titulos: o de R$ 0,80 ainda aberto
    [(500.0, 549.50, 1), (50.0, 0.0, 0)],      # juros num titulo nao cobrem o outro, aberto
])
def test_tolerancia_exige_baixa_em_cada_titulo_da_nota(conn, cid, tmp_path, titulos):
    """A soma da nota fica dentro de R$ 1,00, mas um titulo nao tem baixa nenhuma: nao e' 'pago com diferenca'."""
    mid = _medicao(conn, cid, 12, 1000_00)
    baixas = [_baixa(i, 100, orig, pago, st, "2026-09-01T00:00:00-04:00" if st else None)
              for i, (orig, pago, st) in enumerate(titulos, 1)]
    cli = _simulador(tmp_path, [_nf(100, 1000.0, campo="IC 082/2025 - 12")], baixas)
    assert sincronizacao_rm.sincronizar(conn, cli)["recebimentos"] == 0
    assert medicoes.detalhe(conn, mid)["estado"] == "protocolada"


def test_reconciliacao_lista_recebida_a_mao_com_titulo_aberto_no_rm(conn, cid, tmp_path):
    """Issue #203: o recebimento a mao vale, e a Saude avisa enquanto o RM nao tiver a baixa do titulo. A medicao
    fechada pelo corte nao entra (o titulo aberto dela segue no a receber); com o titulo quitado, o aviso sai."""
    from app import conciliacao
    a_mao = _medicao(conn, cid, 12, 1000_01)
    cortada = _medicao(conn, cid, 13, 500_00)
    nfs = [_nf(100, 1000.01, campo="IC 082/2025 - 12"), _nf(101, 500.0, campo="IC 082/2025 - 13")]
    abertas = [_baixa(1, 100, 924.01, 0.0, 0), _baixa(2, 101, 462.0, 0.0, 0)]
    sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, nfs, abertas))
    medicoes.mudar_estado(conn, 1, a_mao, "recebida", "a baixa nao entrou no RM; conferida no extrato", "2026-09-20")
    medicoes.mudar_estado(conn, 1, cortada, "recebida", conciliacao.MOTIVO_CORTE.format(data="22/09/2026"), None)
    # a mesma NF partida com outra medicao recebida a mao: uma linha so', sem contar o titulo duas vezes
    irma = _medicao(conn, cid, 14, 1_00)
    nid = conn.execute("SELECT id FROM notas_fiscais WHERE idmov=100").fetchone()[0]
    conn.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem, regra) "
                 "VALUES (?, ?, 1, 'detectado', 't')", (irma, nid)); conn.commit()
    medicoes.mudar_estado(conn, 1, irma, "recebida", "a baixa nao entrou no RM; conferida no extrato", "2026-09-20")
    r = sincronizacao_rm.reconciliacao(conn)["recebidas_sem_baixa"]
    assert [(x["medicao_id"], x["numero"], x["numero_nf"], x["falta_centavos"], x["recebida_em"]) for x in r] == [
        (a_mao, 12, "0000000100", 924_01, "2026-09-20")]
    pagas = [_baixa(1, 100, 924.01, 924.01, 1, "2026-09-25T00:00:00-04:00"), _baixa(2, 101, 462.0, 0.0, 0)]
    sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, nfs, pagas))
    assert sincronizacao_rm.reconciliacao(conn)["recebidas_sem_baixa"] == []


def test_nf_cancelada_desfaz_alocacao(conn, cid, tmp_path):
    mid = _medicao(conn, cid, 12, 1000_00)
    cli = _simulador(tmp_path, [_nf(100, 1000.0, campo="IC 082/2025 - 12")], [])
    sincronizacao_rm.sincronizar(conn, cli)
    cli = _simulador(tmp_path, [_nf(100, 1000.0, campo="IC 082/2025 - 12", status="C")], [])
    sincronizacao_rm.sincronizar(conn, cli)
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "protocolada" and m["notas"] == []   # nao volta sozinha
    rec = sincronizacao_rm.reconciliacao(conn)
    assert rec["alocacoes_desfeitas"][0]["motivo_desfazer"] == "NF cancelada no RM"
    assert rec["totais"]["alocacoes_desfeitas"] == 1
    assert rec["ha_mais"]["alocacoes_desfeitas"] is False
    desf_id = rec["alocacoes_desfeitas"][0]["id"]
    assert sincronizacao_rm.reconciliacao(conn, desfeitas_apos=desf_id)["alocacoes_desfeitas"] == []
    assert [x["medicao_id"] for x in rec["medicoes_sem_nf"]] == [mid]
    assert auditoria.verificar_cadeia(conn)


def test_coligada_de_consorcio_so_casa_com_o_contrato_dele(conn, cid, tmp_path):
    eid = entidades.criar(conn, 1, {"nome": "Consórcio X", "cnpj": "11444777000161",
                                    "papel": "consorcio", "coligada_rm": 12})
    c2 = contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 9", "objeto": "Obra",
                                   "valor_original_centavos": 100_00, "entidade_id": eid})
    m_lotufo = _medicao(conn, cid, 1, 500_00)
    m_cons = _medicao(conn, c2, 1, 500_00)
    cli = _simulador(tmp_path, [_nf(7, 500.0, coligada=12)], [])
    sincronizacao_rm.sincronizar(conn, cli)
    assert _tem_nf(conn, m_cons)
    assert not _tem_nf(conn, m_lotufo)


def test_centro_custo_desambigua_obra_da_lotufo(conn, cid, tmp_path):
    """Duas obras da Lotufo (mesma coligada, mesma entidade) com medicao de valor igual:
    o centro de custo diz de qual obra e' a NF, e o valor desempata dentro dela."""
    c2 = contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "CT 9", "objeto": "Obra 2",
                                   "valor_original_centavos": 100_00, "centro_custo_rm": "2.001.012"})
    m1 = _medicao(conn, cid, 1, 500_00)
    m2 = _medicao(conn, c2, 1, 500_00)
    cli = _simulador(tmp_path, [_nf(7, 500.0, centro_custo="2.001.012")], [])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert (r["alocacoes"], r["sugestoes"]) == (1, 0), r
    assert _tem_nf(conn, m2)
    assert not _tem_nf(conn, m1)     # a obra errada nao se mexe
    nota = medicoes.detalhe(conn, m2)["notas"][0]
    assert (nota["regra"], nota["confianca"]) == ("centro_custo_valor", 0.9)
    assert conn.execute("SELECT centro_custo FROM notas_fiscais WHERE idmov=7").fetchone()[0] == "2.001.012"
    assert auditoria.verificar_cadeia(conn)


def test_centro_custo_nao_cadastrado_fica_ambiguo(conn, cid, tmp_path):
    """Sem contrato com aquele centro de custo o casamento nao estreita: as duas obras de
    valor igual voltam a ser candidatas ambiguas -- a NF fica sem alocacao, nao chute."""
    c2 = contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "CT 9", "objeto": "Obra 2",
                                   "valor_original_centavos": 100_00})
    m1 = _medicao(conn, cid, 1, 500_00)
    m2 = _medicao(conn, c2, 1, 500_00)
    cli = _simulador(tmp_path, [_nf(7, 500.0, centro_custo="9.999.999")], [])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert (r["alocacoes"], r["sugestoes"]) == (0, 1), r
    assert not _tem_nf(conn, m1) and not _tem_nf(conn, m2)


def test_modo_estrito_silencia_nf_de_centro_nao_mapeado(conn, cid, tmp_path):
    """Coligada que cadastra centros (Lotufo): NF cujo centro nao mapeia NAO casa por valor
    na coligada inteira nem vira sugestao -- silencio, sem chute em medicao de outra obra."""
    contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "CT 9", "objeto": "Obra 2",
                              "valor_original_centavos": 100_00, "centro_custo_rm": "4.003.009"})
    m = _medicao(conn, cid, 1, 500_00)   # obra SEM centro, protocolada de mesmo valor da NF
    cli = _simulador(tmp_path, [_nf(7, 500.0, centro_custo="2.001.099")], [])   # centro imobilizado
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert (r["alocacoes"], r["sugestoes"]) == (0, 0), r
    assert not _tem_nf(conn, m)


def test_soma_do_dia_aloca_o_par(conn, tmp_path):
    """Medicao faturada em duas notas do mesmo dia e centro (padrao MT-388): o par que soma
    o valor e' alocado inteiro; a medicao continua protocolada com as duas notas."""
    from app import auth
    auth.criar_usuario(conn, "U", "u@l.com", "senha-forte-123", "engenharia")
    c = contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "MT-388", "objeto": "O",
                                  "valor_original_centavos": 100_000_00, "centro_custo_rm": "4.003.025"})
    m = _medicao(conn, c, 1, 300_00)
    dia = "2026-08-03T00:00:00-04:00"
    cli = _simulador(tmp_path, [_nf(1, 120.0, centro_custo="4.003.025", emissao=dia),
                                _nf(2, 180.0, centro_custo="4.003.025", emissao=dia)], [])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert r["alocacoes"] == 1, r          # um casamento (o par), contado uma vez
    d = medicoes.detalhe(conn, m)
    assert d["estado"] == "protocolada" and len(d["notas"]) == 2
    assert {n["regra"] for n in d["notas"]} == {"centro_custo_soma_dia"}
    assert sum(n["valor_alocado_centavos"] for n in d["notas"]) == 300_00
    assert auditoria.verificar_cadeia(conn)


def test_soma_do_dia_dois_pares_no_mesmo_dia(conn, tmp_path):
    """Dia com 4 notas = 2 pares disjuntos para 2 medicoes (execucao + reajuste): cada par
    fecha a sua, sem ambiguidade -- a unicidade e' por NF, nao por grupo do dia."""
    from app import auth
    auth.criar_usuario(conn, "U", "u@l.com", "senha-forte-123", "engenharia")
    c = contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "MT-388", "objeto": "O",
                                  "valor_original_centavos": 100_000_00, "centro_custo_rm": "4.003.025"})
    m_exe = _medicao(conn, c, 1, 300_00, tipo="execucao")
    m_rea = _medicao(conn, c, 1, 500_00, tipo="reajuste")
    dia = "2026-08-03T00:00:00-04:00"
    # 130+170=300 (execucao); 210+290=500 (reajuste). Nenhuma nota sozinha bate uma
    # medicao e nenhum outro par cruzado fecha 300 ou 500 -- pares disjuntos e limpos.
    cli = _simulador(tmp_path, [_nf(1, 130.0, centro_custo="4.003.025", emissao=dia),
                                _nf(2, 170.0, centro_custo="4.003.025", emissao=dia),
                                _nf(3, 210.0, centro_custo="4.003.025", emissao=dia),
                                _nf(4, 290.0, centro_custo="4.003.025", emissao=dia)], [])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert r["alocacoes"] == 2, r
    assert _tem_nf(conn, m_exe)
    assert _tem_nf(conn, m_rea)
    assert len(medicoes.detalhe(conn, m_exe)["notas"]) == 2
    assert len(medicoes.detalhe(conn, m_rea)["notas"]) == 2


def test_soma_do_dia_dois_pares_para_a_mesma_medicao_nao_auto(conn, tmp_path):
    """Dois pares disjuntos que fecham a MESMA medicao: quem venceria dependeria da ordem
    de processamento -- entao nenhum auto-aloca (a medicao fica para decisao humana)."""
    from app import auth
    auth.criar_usuario(conn, "U", "u@l.com", "senha-forte-123", "engenharia")
    c = contratos.criar(conn, 1, {"orgao": "S", "numero_instrumento": "CT X", "objeto": "O",
                                  "valor_original_centavos": 100_000_00, "centro_custo_rm": "4.003.025"})
    m = _medicao(conn, c, 1, 300_00)
    dia = "2026-08-03T00:00:00-04:00"
    cli = _simulador(tmp_path, [_nf(1, 100.0, centro_custo="4.003.025", emissao=dia),
                                _nf(2, 200.0, centro_custo="4.003.025", emissao=dia),
                                _nf(3, 120.0, centro_custo="4.003.025", emissao=dia),
                                _nf(4, 180.0, centro_custo="4.003.025", emissao=dia)], [])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert r["alocacoes"] == 0, r
    assert not _tem_nf(conn, m)


def test_soma_do_dia_nao_rouba_irma_de_casamento_exato(conn, tmp_path):
    """Uma irma que casa exato com a propria medicao nao pode ser consumida por um par --
    senao a alocacao dependeria de quem foi processado primeiro (gate Sol)."""
    from app import auth
    auth.criar_usuario(conn, "U", "u@l.com", "senha-forte-123", "engenharia")
    c = contratos.criar(conn, 1, {"orgao": "S", "numero_instrumento": "CT X", "objeto": "O",
                                  "valor_original_centavos": 100_000_00, "centro_custo_rm": "4.003.025"})
    m_a = _medicao(conn, c, 1, 300_00)
    m_b = _medicao(conn, c, 2, 200_00, "2026-08")
    dia = "2026-08-03T00:00:00-04:00"
    # NF2=200 casa exato com m_b; NF1=100 tentaria 100+200=300 (m_a) e roubaria a NF2.
    cli = _simulador(tmp_path, [_nf(1, 100.0, centro_custo="4.003.025", emissao=dia),
                                _nf(2, 200.0, centro_custo="4.003.025", emissao=dia)], [])
    sincronizacao_rm.sincronizar(conn, cli)
    d_b = medicoes.detalhe(conn, m_b)
    assert d_b["notas"] and d_b["notas"][0]["regra"] == "centro_custo_valor"
    assert not _tem_nf(conn, m_a)   # m_a sem par valido


def test_ambigua_aloca_quando_surge_o_valor_exato(conn, tmp_path):
    """A NF ambigua numa rodada aloca sozinha na seguinte, quando chega a medicao de valor exato."""
    from app import auth
    auth.criar_usuario(conn, "U", "u@l.com", "senha-forte-123", "engenharia")
    c = contratos.criar(conn, 1, {"orgao": "S", "numero_instrumento": "CT X", "objeto": "O",
                                  "valor_original_centavos": 10_000_000_00, "centro_custo_rm": "4.003.009"})
    _medicao(conn, c, 1, 100_000_00)          # so' proxima (1% abaixo da NF)
    nf = [_nf(1, 101000.0, centro_custo="4.003.009")]
    r = sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, nf, []))
    assert (r["alocacoes"], r["sugestoes"]) == (0, 1), r
    m2 = _medicao(conn, c, 2, 101_000_00, "2026-08")   # chega o valor exato da mesma obra
    r = sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, nf, []))
    assert r["alocacoes"] == 1
    assert _tem_nf(conn, m2)
    assert auditoria.verificar_cadeia(conn)


def test_centro_com_obra_sem_protocolada_nao_vaza(conn, cid, tmp_path):
    """Centro aponta a obra certa, mas ela nao tem medicao protocolada; a NF nao pode cair
    na medicao de OUTRA obra que por acaso tem o mesmo valor."""
    contratos.criar(conn, 1, {"orgao": "S", "numero_instrumento": "CT 9", "objeto": "O",
                              "valor_original_centavos": 100_00, "centro_custo_rm": "4.003.009"})
    m = _medicao(conn, cid, 1, 500_00)   # obra ERRADA, com protocolada de 500
    cli = _simulador(tmp_path, [_nf(7, 500.0, centro_custo="4.003.009")], [])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert (r["alocacoes"], r["sugestoes"]) == (0, 0), r
    assert not _tem_nf(conn, m)


def test_centro_igual_em_outra_coligada_nao_vaza(conn, cid, tmp_path):
    """Codigo de centro repetido entre coligadas: o alvo e' resolvido DENTRO da coligada da
    NF, nunca na obra de outra coligada com o mesmo codigo."""
    eid = entidades.criar(conn, 1, {"nome": "Consórcio Z", "cnpj": "11444777000161",
                                    "papel": "consorcio", "coligada_rm": 17})
    c_cons = contratos.criar(conn, 1, {"orgao": "S", "numero_instrumento": "CT Z", "objeto": "O",
                                       "valor_original_centavos": 100_00, "entidade_id": eid,
                                       "centro_custo_rm": "4.001.001"})
    c_lot = contratos.criar(conn, 1, {"orgao": "S", "numero_instrumento": "CT L", "objeto": "O",
                                      "valor_original_centavos": 100_00, "centro_custo_rm": "4.001.001"})
    m_cons = _medicao(conn, c_cons, 1, 900_00)
    m_lot = _medicao(conn, c_lot, 1, 900_00)
    cli = _simulador(tmp_path, [_nf(7, 900.0, coligada=1, centro_custo="4.001.001")], [])
    sincronizacao_rm.sincronizar(conn, cli)
    assert _tem_nf(conn, m_lot)
    assert not _tem_nf(conn, m_cons)


def test_falha_de_rede_fica_registrada_sem_segredo(conn, tmp_path):
    class Fora:
        def consultar(self, codigo, parametros=None):
            raise rm.ErroRM("RM inacessível (URLError) na consulta DASH10")
    r = sincronizacao_rm.sincronizar(conn, Fora())
    assert r["estado"] == "failed" and "inacessível" in r["erro"]
    rod = sincronizacao_rm.rodadas(conn)[0]
    assert rod["estado"] == "failed" and rod["terminado_em"]


def test_simulador_recusa_formato_estranho(tmp_path):
    pasta = tmp_path / "rm"; pasta.mkdir()
    (pasta / f"{rm.CONSULTA_NF}.json").write_text('{"a": [1]}', encoding="utf-8")
    assert rm.SimuladorRM(pasta).consultar(rm.CONSULTA_NF) == [{"a": [1]}]   # objeto unico vira lista
    (pasta / f"{rm.CONSULTA_NF}.json").write_text('[1, 2]', encoding="utf-8")
    with pytest.raises(rm.ErroRM):
        rm.SimuladorRM(pasta).consultar(rm.CONSULTA_NF)


# --- API ---

def test_rotas_rm(client_admin, tmp_path, monkeypatch):
    r = client_admin.get("/api/rm/status")
    assert r.status_code == 200 and r.json()["configurado"] is False
    assert client_admin.post("/api/rm/sincronizar").status_code == 422
    pasta = tmp_path / "rm"; pasta.mkdir()
    (pasta / f"{rm.CONSULTA_NF}.json").write_text("[]", encoding="utf-8")
    (pasta / f"{rm.CONSULTA_BAIXA}.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("DASH_RM_SIMULADOR", str(pasta))
    r = client_admin.post("/api/rm/sincronizar")
    assert r.status_code == 200 and r.json()["estado"] == "success", r.text
    assert client_admin.get("/api/rm/status").json()["rodadas"][0]["estado"] == "success"
    assert set(client_admin.get("/api/rm/reconciliacao").json()) == {
        "nfs_sem_medicao", "medicoes_sem_nf", "divergencias", "alocacoes_desfeitas", "recebidas_sem_baixa", "totais",
        "ha_mais"}
    # #22: a pagina seguinte pela URL, depois do id da ultima linha; id invalido ou desfeita que nao existe e' 422
    # em portugues
    r = client_admin.get("/api/rm/reconciliacao?nfs_apos=10")
    assert r.status_code == 200 and r.json()["nfs_sem_medicao"] == []
    assert client_admin.get("/api/rm/reconciliacao?nfs_apos=abc").status_code == 422
    r = client_admin.get("/api/rm/reconciliacao?desfeitas_apos=999999")
    assert r.status_code == 422 and "não encontrada" in r.json()["detail"]
    assert client_admin.get("/api/rm/reconciliacao?desfeitas_apos=0").status_code == 422


def test_nf_emitida_antes_do_protocolo_aloca_normalmente(conn, cid, tmp_path):
    """Bloco 3: a nota vem ANTES do protocolo por desenho; alocar nao mexe em estado nem em marco."""
    mid = _medicao(conn, cid, 12, 1000_00, comp="2026-09")          # protocolo em 2026-09-28
    cli = _simulador(tmp_path, [_nf(100, 1000.0, campo="IC 082/2025 - 12",
                                    emissao="2026-09-01T00:00:00-04:00")], [])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert r["alocacoes"] == 1, r
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "protocolada" and m["nota_emitida_em"] is None and len(m["notas"]) == 1


def test_campo_livre_exige_coligada_da_entidade(conn, cid, tmp_path):
    """Instrumento igual em duas entidades: a NF so' casa pelo campo livre dentro da coligada."""
    eid = entidades.criar(conn, 1, {"nome": "Consórcio Y", "cnpj": "11444777000161",
                                    "papel": "consorcio", "coligada_rm": 12})
    c2 = contratos.criar(conn, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 082/2025", "objeto": "Obra",
                                   "valor_original_centavos": 100_00, "entidade_id": eid})
    m_lotufo = _medicao(conn, cid, 12, 1000_00)
    m_cons = _medicao(conn, c2, 12, 7777_00)
    cli = _simulador(tmp_path, [_nf(7, 1000.0, coligada=12, campo="IC 082/2025 - 12")], [])
    sincronizacao_rm.sincronizar(conn, cli)
    assert _tem_nf(conn, m_cons)      # coligada 12 -> consorcio
    assert not _tem_nf(conn, m_lotufo)


def test_rodada_em_andamento_trava_e_expira(conn, tmp_path):
    cli = _simulador(tmp_path, [], [])
    conn.execute("INSERT INTO rm_sincronizacoes (disparo, estado) VALUES ('manual','running')"); conn.commit()
    with pytest.raises(sincronizacao_rm.RodadaEmAndamento):
        sincronizacao_rm.sincronizar(conn, cli)
    # rodada morta (mais velha que o prazo) e' expirada e a nova passa
    conn.execute("UPDATE rm_sincronizacoes SET iniciado_em=datetime('now','-2 hours')"); conn.commit()
    assert sincronizacao_rm.sincronizar(conn, cli)["estado"] == "success"
    estados = [r["estado"] for r in sincronizacao_rm.rodadas(conn)]
    assert estados == ["success", "failed"]


def test_coligada_unica_por_entidade(conn):
    with pytest.raises(ValueError):
        entidades.criar(conn, 1, {"nome": "Dup", "cnpj": "11444777000161", "papel": "consorcio", "coligada_rm": 1})


# --- bloco 3: RM confirma a nota do PDF, casa pela saida esperada, nao ataca o legado ---

RAIZ = pathlib.Path(__file__).parent.parent.parent / "cadastro-exemplo"


def _pdf_nota(conn, numero, valor, emissao="2026-07-15", coligada=1):
    cur = conn.execute("INSERT INTO notas_fiscais (coligada, numero, numero_int, emissao, valor_centavos, origem, "
                       "confirmacao, valor_pdf_centavos) VALUES (?,?,?,?,?,'pdf','aguardando_rm',?)",
                       (coligada, str(numero), numero, emissao, valor, valor))
    conn.commit()
    return cur.lastrowid


def test_rm_confirma_nota_que_veio_do_pdf(conn, cid, tmp_path):
    mid = medicoes.criar(conn, 1, {"contrato_id": cid, "numero": 4, "tipo": "execucao", "competencia": "2026-08"})
    medicoes.definir_valor(conn, 1, mid, "protocolado", 84678831, "manual")
    nid = _pdf_nota(conn, 3102, 84678831)
    sincronizacao_rm.alocar(conn, 1, nid, mid, "manual", None, "pdf")
    cli = _simulador(tmp_path, [_nf(900, 846788.31, numero="000003102", emissao="2026-07-15T00:00:00-04:00",
                                    centro_custo="4.003.016")], [])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert r["estado"] == "success", r
    assert conn.execute("SELECT COUNT(*) FROM notas_fiscais").fetchone()[0] == 1          # nao duplicou
    nf = conn.execute("SELECT idmov, confirmacao, centro_custo, origem, emissao FROM notas_fiscais").fetchone()
    assert tuple(nf) == (900, "confirmada", "4.003.016", "pdf", "2026-07-15")
    assert conn.execute("SELECT COUNT(*) FROM nf_alocacoes WHERE desfeita_em IS NULL").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='nota.confirmacao'").fetchone()[0] == 1
    # segunda rodada: nada muda
    sincronizacao_rm.sincronizar(conn, cli)
    assert conn.execute("SELECT COUNT(*) FROM notas_fiscais").fetchone()[0] == 1


def test_rm_marca_divergente_quando_o_valor_difere(conn, tmp_path):
    _pdf_nota(conn, 3102, 84678831)
    cli = _simulador(tmp_path, [_nf(900, 846788.32, numero="000003102", emissao="2026-07-15T00:00:00-04:00")], [])
    sincronizacao_rm.sincronizar(conn, cli)
    nf = conn.execute("SELECT idmov, confirmacao, valor_centavos, valor_pdf_centavos FROM notas_fiscais").fetchone()
    assert tuple(nf) == (900, "divergente", 84678832, 84678831)      # bruto do RM manda; o lido fica guardado
    # o RM corrige o valor: a confirmacao acompanha
    cli = _simulador(tmp_path, [_nf(900, 846788.31, numero="000003102", emissao="2026-07-15T00:00:00-04:00")], [])
    sincronizacao_rm.sincronizar(conn, cli)
    assert conn.execute("SELECT confirmacao FROM notas_fiscais").fetchone()[0] == "confirmada"


def test_numero_igual_com_emissao_e_valor_diferentes_nao_confirma(conn, tmp_path):
    _pdf_nota(conn, 3106, 71919072, emissao="2026-09-14")
    cli = _simulador(tmp_path, [_nf(901, 700.00, numero="000003106", emissao="2025-03-27T00:00:00-04:00", coligada=1)], [])
    sincronizacao_rm.sincronizar(conn, cli)
    assert conn.execute("SELECT COUNT(*) FROM notas_fiscais").fetchone()[0] == 2
    assert conn.execute("SELECT confirmacao FROM notas_fiscais WHERE origem='pdf'").fetchone()[0] == "aguardando_rm"


@pytest.fixture
def espelho_mt402(conn):
    """Cadastro de exemplo aplicado; espelho da Obra Propria 27a gerado (R$ 719.190,72, uma nota so') e enviado.
    Devolve (contrato_id, medicao_execucao_id)."""
    from app import auth, cadastro_aplicar, cadastro_arquivos, espelhos
    auth.criar_usuario(conn, "U", "u@l.com", "senha-forte-123", "engenharia")
    cadastro_aplicar.aplicar(conn, 1, cadastro_arquivos.preparar(RAIZ), ensaio=False)
    c = conn.execute("SELECT id FROM contratos WHERE nome_curto='Obra Própria'").fetchone()[0]
    eid = espelhos.gerar(conn, {"id": 1, "email": "u@l.com"}, c, 27, "2026-08", {"medicao": 71919072})
    ids = {r["tipo"]: r["id"] for r in conn.execute(
        "SELECT m.id, m.tipo FROM espelho_medicoes em JOIN medicoes m ON m.id=em.medicao_id WHERE em.espelho_id=?", (eid,))}
    for mid in ids.values():
        medicoes.marcar_espelho_enviado(conn, 1, mid)
    return c, ids["execucao"]


def test_rm_primeiro_casa_pela_saida_esperada_e_fecha_nota_emitida(conn, tmp_path, espelho_mt402):
    """Medicao nascida do espelho, sem PDF: a NF do RM com o valor EXATO da saida e o centro de custo da obra
    aloca e fecha `nota_emitida`."""
    cid, mid_exec = espelho_mt402
    cli = _simulador(tmp_path, [_nf(910, 719190.72, numero="000003106", centro_custo="9.001.001",
                                    emissao="2026-09-14T00:00:00-04:00")], [])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert r["alocacoes"] == 1, r
    al = conn.execute("SELECT regra, confianca FROM nf_alocacoes WHERE medicao_id=?", (mid_exec,)).fetchone()
    assert (al["regra"], al["confianca"]) == ("saida_espelho", 0.95)
    m = medicoes.detalhe(conn, mid_exec)
    assert m["estado"] == "nota_emitida" and m["nota_emitida_em"] == "2026-09-14"
    assert conn.execute("SELECT COUNT(*) FROM notas_fiscais").fetchone()[0] == 1


def test_recebimento_fecha_medicao_protocolada(conn, cid, tmp_path):
    mid = _medicao(conn, cid, 5, 100_000)                       # protocolada
    cli = _simulador(tmp_path, [_nf(920, 1000.00, campo="IC 082/2025 - 5")],
                     [_baixa(1, 920, 924.00, 924.00, 1, "2026-09-01T00:00:00-04:00")])
    sincronizacao_rm.sincronizar(conn, cli)
    m = medicoes.detalhe(conn, mid)
    assert (m["estado"], m["recebida_em"]) == ("recebida", "2026-09-01")


def test_legado_protocolada_sem_nf_nao_atrai_casamento(conn, cid, tmp_path):
    """Medicao de competencia anterior ao corte e origem manual (a carga do legado) nao e' candidata:
    24 meses de NFs contra 422 protocoladas seria o cenario das 29 sugestoes de 2026-09-04."""
    conn.execute("UPDATE contratos SET centro_custo_rm='4.003.016' WHERE id=?", (cid,)); conn.commit()
    mid = _medicao(conn, cid, 7, 100_000, comp="2026-03")
    cli = _simulador(tmp_path, [_nf(930, 1000.00, centro_custo="4.003.016"), _nf(931, 1010.00, centro_custo="4.003.016")], [])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert (r["alocacoes"], r["sugestoes"]) == (0, 0), r
    assert medicoes.detalhe(conn, mid)["estado"] == "protocolada" and not _tem_nf(conn, mid)


def test_nota_lotufo_em_obra_de_consorcio_casa_pela_saida_e_nao_segura_recebimento(conn, tmp_path):
    """A NFS-e da Lotufo ao orgao em obra de consorcio fica na coligada 1 (centro 5.001.x, sem contrato): casa
    pela saida esperada do espelho; a fatura do consorcio (coligada 90, valor cheio) casa por valor exato e e'
    quem decide o recebimento."""
    from app import auth, cadastro_aplicar, cadastro_arquivos, espelhos
    auth.criar_usuario(conn, "U", "u@l.com", "senha-forte-123", "engenharia")
    cadastro_aplicar.aplicar(conn, 1, cadastro_arquivos.preparar(RAIZ), ensaio=False)
    cid = conn.execute("SELECT id FROM contratos WHERE nome_curto='Obra Consórcio'").fetchone()[0]
    eid = espelhos.gerar(conn, {"id": 1, "email": "u@l.com"}, cid, 12, "2026-06", {"medicao": 1000000007})
    mid = conn.execute("SELECT m.id FROM espelho_medicoes em JOIN medicoes m ON m.id=em.medicao_id "
                       "WHERE em.espelho_id=? AND m.tipo='execucao'", (eid,)).fetchone()[0]
    medicoes.marcar_espelho_enviado(conn, 1, mid)
    medicoes.registrar_protocolo(conn, 1, mid, "2026-07-20", "CT-1", None, "manual")     # protocolada sem nota
    nfs = [_nf(940, 2000000.02, coligada=1, centro_custo="5.001.011", numero="000003102"),   # propria, VG (saida)
           _nf(941, 10000000.07, coligada=90, numero="000000021")]                           # fatura do consorcio
    cli = _simulador(tmp_path, nfs, [_baixa(1, 941, 9000000.00, 9000000.00, 1, "2026-09-01T00:00:00-04:00", coligada=90)])
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert r["alocacoes"] == 2, r
    regras = {a["regra"] for a in conn.execute("SELECT regra FROM nf_alocacoes WHERE medicao_id=?", (mid,))}
    assert regras == {"saida_espelho", "valor_exato"}
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "recebida"          # a nota da Lotufo (sem titulo quitado) nao segurou


# --- desalocacao manual (issue #71) ---

def _alocada(conn, cid, tmp_path):
    """Medicao protocolada com a NF casada pelo valor exato; devolve (medicao, alocacao, cliente)."""
    mid = _medicao(conn, cid, 3, 1234_57)                       # centavo impar
    cli = _simulador(tmp_path, [_nf(950, 1234.57)], [])
    assert sincronizacao_rm.sincronizar(conn, cli)["alocacoes"] == 1
    aid = conn.execute("SELECT id FROM nf_alocacoes WHERE medicao_id=? AND desfeita_em IS NULL", (mid,)).fetchone()[0]
    return mid, aid, cli


def test_desalocar_a_mao_audita_e_o_casador_nao_refaz(conn, cid, tmp_path):
    mid, aid, cli = _alocada(conn, cid, tmp_path)
    usuario = conn.execute("SELECT id FROM usuarios LIMIT 1").fetchone()[0]
    sincronizacao_rm.desalocar(conn, usuario, mid, aid, "  NF de outra obra  ")
    m = medicoes.detalhe(conn, mid)
    assert m["estado"] == "protocolada" and m["notas"] == []      # o estado nao volta sozinho
    a = conn.execute("SELECT desfeita_em, motivo_desfazer FROM nf_alocacoes WHERE id=?", (aid,)).fetchone()
    assert a["desfeita_em"] is not None and a["motivo_desfazer"] == "Desfeita à mão: NF de outra obra"
    aud = conn.execute("SELECT usuario_id, antes, depois FROM audit_log WHERE acao='nf.desalocar'").fetchone()
    assert aud["usuario_id"] == usuario
    assert json.loads(aud["antes"])["valor_centavos"] == 1234_57
    assert json.loads(aud["depois"])["motivo"] == "Desfeita à mão: NF de outra obra"
    # a reconciliacao mostra a desfeita e a medicao que ficou sem nota
    rec = sincronizacao_rm.reconciliacao(conn)
    assert rec["alocacoes_desfeitas"][0]["motivo_desfazer"].startswith("Desfeita à mão")
    assert [x["medicao_id"] for x in rec["medicoes_sem_nf"]] == [mid]
    # a rodada seguinte nao casa de novo a mesma NF (o valor exato continua unico)
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert r["alocacoes"] == 0, r
    assert not _tem_nf(conn, mid)
    assert auditoria.verificar_cadeia(conn)


def test_nf_desfeita_a_mao_nao_entra_como_irma_da_soma_do_dia(conn, cid, tmp_path):
    """A NF desvinculada a' mao tambem nao volta pela porta do par: nao completa a soma de outra NF do dia."""
    conn.execute("UPDATE contratos SET centro_custo_rm='4.003.016' WHERE id=?", (cid,)); conn.commit()
    m1 = _medicao(conn, cid, 1, 500_00)
    cli = _simulador(tmp_path, [_nf(960, 100.00, centro_custo="4.003.016")], [])
    sincronizacao_rm.sincronizar(conn, cli)                     # 100 nao casa com 500: fica solta
    nota_a = conn.execute("SELECT id FROM notas_fiscais WHERE idmov=960").fetchone()[0]
    aid = sincronizacao_rm.alocar(conn, 1, nota_a, m1, "manual", None, "pdf")
    sincronizacao_rm.desalocar(conn, 1, m1, aid, "nota de outra medição")
    m2 = _medicao(conn, cid, 2, 300_00, comp="2026-08")
    cli = _simulador(tmp_path, [_nf(960, 100.00, centro_custo="4.003.016"),
                                _nf(961, 200.00, centro_custo="4.003.016")], [])   # 100 + 200 = medicao 2
    r = sincronizacao_rm.sincronizar(conn, cli)
    assert r["alocacoes"] == 0, r
    assert not _tem_nf(conn, m2) and not _tem_nf(conn, m1)


def test_desalocar_recusa_sem_motivo_de_outra_medicao_e_repetida(conn, cid, tmp_path):
    mid, aid, _ = _alocada(conn, cid, tmp_path)
    outra = _medicao(conn, cid, 4, 999_99)
    with pytest.raises(ValueError, match="motivo"):
        sincronizacao_rm.desalocar(conn, 1, mid, aid, "   ")
    with pytest.raises(ValueError, match="não encontrado"):
        sincronizacao_rm.desalocar(conn, 1, outra, aid, "errada")
    sincronizacao_rm.desalocar(conn, 1, mid, aid, "errada")
    with pytest.raises(ValueError, match="já foi desfeito"):
        sincronizacao_rm.desalocar(conn, 1, mid, aid, "de novo")
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='nf.desalocar'").fetchone()[0] == 1


def test_parte_desfeita_a_mao_nao_deixa_a_medicao_recebida_pela_outra_nota(conn, cid, tmp_path):
    """Gate Sol S1 (PR #202): medicao de R$ 300 faturada em duas notas (soma do dia); desfeita a de R$ 100, a de
    R$ 200 quitada nao fecha o recebimento sozinha -- falta parte do faturamento."""
    conn.execute("UPDATE contratos SET centro_custo_rm='4.003.016' WHERE id=?", (cid,)); conn.commit()
    mid = _medicao(conn, cid, 1, 300_00)
    nfs = [_nf(970, 100.00, centro_custo="4.003.016"), _nf(971, 200.00, centro_custo="4.003.016")]
    sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, nfs, []))
    assert len(medicoes.detalhe(conn, mid)["notas"]) == 2               # o par fecha a medicao
    aid = conn.execute("""SELECT a.id FROM nf_alocacoes a JOIN notas_fiscais n ON n.id=a.nota_id
                          WHERE n.idmov=970""").fetchone()[0]
    sincronizacao_rm.desalocar(conn, 1, mid, aid, "nota de outra medição")
    baixas = [_baixa(1, 970, 92.00, 92.00, 1, "2026-09-01T00:00:00-04:00"),
              _baixa(2, 971, 184.00, 184.00, 1, "2026-09-02T00:00:00-04:00")]
    r = sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, nfs, baixas))
    assert r["recebimentos"] == 0, r
    assert medicoes.detalhe(conn, mid)["estado"] == "protocolada"


def test_nota_a_mais_desfeita_a_mao_nao_segura_o_recebimento(conn, cid, tmp_path):
    """A outra ponta: a nota desfeita sobrava (a restante cobre a medicao inteira) -> recebida normalmente."""
    mid = _medicao(conn, cid, 1, 200_01)                        # centavo impar
    nfs = [_nf(980, 200.01), _nf(981, 100.00, emissao="2026-08-11T00:00:00-04:00")]
    sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, nfs, []))
    extra = conn.execute("SELECT id FROM notas_fiscais WHERE idmov=981").fetchone()[0]
    aid = sincronizacao_rm.alocar(conn, 1, extra, mid, "manual", None, "pdf")
    sincronizacao_rm.desalocar(conn, 1, mid, aid, "nota de outra medição")
    baixas = [_baixa(1, 980, 184.01, 184.01, 1, "2026-09-01T00:00:00-04:00")]
    r = sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, nfs, baixas))
    assert r["recebimentos"] == 1, r
    assert medicoes.detalhe(conn, mid)["estado"] == "recebida"


def test_desalocar_recusa_tirar_a_nota_que_falta_de_medicao_com_nota_emitida(conn, cid, tmp_path):
    """Revisor R1 (PR #202): em nota_emitida, desfazer a unica nota deixaria a medicao protocolar sem nota e sem a
    ressalva "nota nao emitida" (A-09). Recusa; o vinculo continua."""
    mid, aid, _ = _alocada(conn, cid, tmp_path)
    conn.execute("UPDATE medicoes SET estado='nota_emitida' WHERE id=?", (mid,)); conn.commit()
    with pytest.raises(ValueError, match="nota emitida"):
        sincronizacao_rm.desalocar(conn, 1, mid, aid, "errada")
    assert conn.execute("SELECT desfeita_em FROM nf_alocacoes WHERE id=?", (aid,)).fetchone()[0] is None
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='nf.desalocar'").fetchone()[0] == 0


def test_desalocar_nota_a_mais_de_medicao_declarada_completa(conn, tmp_path, espelho_mt402):
    """Revisor R4 (PR #202): declarada completa (nota_emitida com saida sem nota), a NF errada que nao atende saida
    nenhuma sai -- a falta nao aumenta. A ultima nota nao sai: a medicao ficaria em nota_emitida sem nota."""
    from app import notas
    _, mid = espelho_mt402
    nfs = [_nf(990, 500.01, centro_custo="0.000.000"), _nf(991, 300.00, centro_custo="0.000.000")]   # centro sem obra
    sincronizacao_rm.sincronizar(conn, _simulador(tmp_path, nfs, []))
    a, b = (conn.execute("SELECT id FROM notas_fiscais WHERE idmov=?", (i,)).fetchone()[0] for i in (990, 991))
    al_a = sincronizacao_rm.alocar(conn, 1, a, mid, "manual", None, "pdf")
    notas.declarar_completa(conn, {"id": 1}, mid, "Cuiabá não teve serviço neste mês")
    al_b = sincronizacao_rm.alocar(conn, 1, b, mid, "detectado", 0.9, "centro_custo_valor")     # a errada
    assert medicoes.detalhe(conn, mid)["estado"] == "nota_emitida" and notas.faltam(conn, mid) == 1
    sincronizacao_rm.desalocar(conn, 1, mid, al_b, "nota de outra obra")
    assert [n["nota_id"] for n in medicoes.detalhe(conn, mid)["notas"]] == [a]
    with pytest.raises(ValueError, match="nota emitida"):
        sincronizacao_rm.desalocar(conn, 1, mid, al_a, "errada")


def test_desalocar_recusa_medicao_encerrada_e_nota_do_pdf_anexado(conn, cid, tmp_path):
    """Medicao recebida nao recebe NF de volta; a nota que veio do PDF anexado seguiria no envio ao orgao."""
    mid, aid, _ = _alocada(conn, cid, tmp_path)
    nota = conn.execute("SELECT nota_id FROM nf_alocacoes WHERE id=?", (aid,)).fetchone()[0]
    did = conn.execute("INSERT INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, item_id) "
                       "VALUES (?, 'operacao', 'nfs', 'nota.pdf', 'x1')", (mid,)).lastrowid
    conn.execute("UPDATE notas_fiscais SET documento_id=? WHERE id=?", (did, nota)); conn.commit()
    with pytest.raises(ValueError, match="PDF anexado nesta medição"):
        sincronizacao_rm.desalocar(conn, 1, mid, aid, "errada")
    conn.execute("UPDATE notas_fiscais SET documento_id=NULL WHERE id=?", (nota,))
    conn.execute("UPDATE medicoes SET estado='recebida' WHERE id=?", (mid,)); conn.commit()
    with pytest.raises(ValueError, match="recebida"):
        sincronizacao_rm.desalocar(conn, 1, mid, aid, "errada")
    assert conn.execute("SELECT desfeita_em FROM nf_alocacoes WHERE id=?", (aid,)).fetchone()[0] is None


def test_rota_desalocar_so_admin(client_admin, tmp_path, monkeypatch):
    from app import auth
    monkeypatch.setattr(documentos, "exigidos",
                        lambda conn, cid, natureza: {"entidades": [], "tipos": [], "regularidade": None})
    c = db.get_conn()
    c.execute("UPDATE certidao_tipos SET aplicavel_por_padrao=0"); c.commit()
    auth.criar_usuario(c, "Eng", "eng@lotufo.com", "senha-forte-123", "engenharia")
    cid = contratos.criar(c, 1, {"orgao": "SINFRA", "numero_instrumento": "IC 082/2025",
                                 "objeto": "Obra", "valor_original_centavos": 10_000_000_00})
    mid, aid, _ = _alocada(c, cid, tmp_path)
    c.close()
    url = f"/api/medicoes/{mid}/notas/alocacoes/{aid}/desfazer"
    assert client_admin.post(url, json={"motivo": ""}).status_code == 422
    r = client_admin.post(url, json={"motivo": "NF de outra obra"})
    assert r.status_code == 200, r.text
    assert client_admin.get(f"/api/medicoes/{mid}/notas").json()["notas"] == []
    r = client_admin.post(url, json={"motivo": "de novo"})
    assert r.status_code == 422 and "já foi desfeito" in r.json()["detail"]
    # engenharia nao desfaz vinculo
    client_admin.cookies.clear()
    r = client_admin.post("/api/auth/login", json={"email": "eng@lotufo.com", "senha": "senha-forte-123"})
    client_admin.cookies.set("sessao", r.cookies.get("sessao") or client_admin.cookies.get("sessao"))
    client_admin.headers["X-CSRF-Token"] = r.json()["csrf"]
    assert client_admin.post(url, json={"motivo": "x"}).status_code == 403
