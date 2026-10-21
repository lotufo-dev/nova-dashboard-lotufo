import pytest
from tests.conftest import novo_contrato


@pytest.fixture(autouse=True)
def _sem_certidoes(sem_certidoes_exigidas):
    """Fase 3,5: estes testes nao sao sobre certidoes (ver conftest)."""

# issue #53: recebimento a mao so' para admin, com motivo (saida para quando o RM falhar)
MOTIVO_RM = "baixa do RM não entrou: conferido no extrato"

def _contrato(client_admin):
    return novo_contrato({
        "orgao": "SINFRA", "numero_instrumento": "IC 1/2026",
        "objeto": "Obra", "valor_original": "100.000,00"})

def test_fluxo_completo(client_admin):
    cid = _contrato(client_admin)
    r = client_admin.post(f"/api/contratos/{cid}/medicoes",
                          json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    assert r.status_code == 201
    mid = r.json()["id"]
    assert client_admin.put(f"/api/medicoes/{mid}/valor",
                            json={"campo": "protocolado", "valor": "50.000,00"}).status_code == 200
    _no_estado(mid, "nota_emitida")  # A-09: o protocolo feito fora vem depois da nota
    assert client_admin.post(f"/api/medicoes/{mid}/protocolo",
                             json={"data": "2026-08-05", "numero_oficio": "CT-279-LT-2026"}).status_code == 201
    d = client_admin.get(f"/api/medicoes/{mid}").json()
    assert d["estado"] == "protocolada" and d["valor_protocolado_centavos"] == 5_000_000
    assert d["valor_protocolado_origem"] == "manual" and len(d["protocolos"]) == 1
    # congelada: mudar protocolado agora e 422
    r = client_admin.put(f"/api/medicoes/{mid}/valor", json={"campo": "protocolado", "valor": "60.000,00"})
    assert r.status_code == 422

def test_validacoes(client_admin):
    cid = _contrato(client_admin)
    assert client_admin.post(f"/api/contratos/{cid}/medicoes",
        json={"numero": 1, "tipo": "outro", "competencia": "2026-07"}).status_code == 422
    assert client_admin.post(f"/api/contratos/{cid}/medicoes",
        json={"numero": 1, "tipo": "execucao", "competencia": "07/2026"}).status_code == 422
    assert client_admin.post("/api/contratos/99999/medicoes",
        json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"}).status_code == 404
    assert client_admin.get("/api/medicoes/99999").status_code == 404

def test_leitura_exige_login(client):
    assert client.get("/api/medicoes/1").status_code in (401, 403)


# --- guardas adicionais (revisao da Task 1) ---

def test_mutacoes_em_medicao_inexistente_dao_404(client_admin):
    """As funcoes do repositorio estouram TypeError com id inexistente (detalhe()
    devolve None): a rota tem que barrar com 404 ANTES de chama-las."""
    assert client_admin.put("/api/medicoes/99999/valor",
        json={"campo": "protocolado", "valor": "10,00"}).status_code == 404
    assert client_admin.post("/api/medicoes/99999/protocolo",
        json={"data": "2026-08-05"}).status_code == 404
    assert client_admin.post("/api/medicoes/99999/estado",
        json={"estado": "cancelada"}).status_code == 404
    assert client_admin.get("/api/contratos/99999/medicoes").status_code == 404

def test_listar_e_estado(client_admin):
    cid = _contrato(client_admin)
    mid = client_admin.post(f"/api/contratos/{cid}/medicoes",
        json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"}).json()["id"]
    _no_estado(mid, "nota_emitida")
    assert client_admin.post(f"/api/medicoes/{mid}/protocolo",
        json={"data": "2026-08-05"}).status_code == 201
    # bloco 3: `nf_emitida` saiu da rota (a NF entra pela nota); recebida vem direto de protocolada
    assert client_admin.post(f"/api/medicoes/{mid}/estado",
        json={"estado": "nf_emitida"}).status_code == 422
    assert client_admin.post(f"/api/medicoes/{mid}/estado",
        json={"estado": "recebida", "motivo": MOTIVO_RM}).status_code == 200
    # repetir o estado atual e transicao invalida -> 422 (nao 500)
    assert client_admin.post(f"/api/medicoes/{mid}/estado",
        json={"estado": "recebida", "motivo": MOTIVO_RM}).status_code == 422
    itens = client_admin.get(f"/api/contratos/{cid}/medicoes").json()
    assert [i["estado"] for i in itens] == ["recebida"]

def test_valor_brl_invalido_da_422(client_admin):
    cid = _contrato(client_admin)
    mid = client_admin.post(f"/api/contratos/{cid}/medicoes",
        json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"}).json()["id"]
    assert client_admin.put(f"/api/medicoes/{mid}/valor",
        json={"campo": "protocolado", "valor": "cinquenta mil"}).status_code == 422
    assert client_admin.put(f"/api/medicoes/{mid}/valor",
        json={"campo": "congelada", "valor": "1,00"}).status_code == 422

def test_422_nao_deixa_transacao_aberta(client_admin):
    """Depois de um 422 vindo das guardas de rowcount, a escrita seguinte tem que
    funcionar normalmente (o handler faz rollback antes de levantar o HTTPException)."""
    cid = _contrato(client_admin)
    mid = client_admin.post(f"/api/contratos/{cid}/medicoes",
        json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"}).json()["id"]
    # o valor entra ANTES do protocolo: e' a ALTERACAO depois do congelamento que da'
    # 422 (congelada ainda sem valor aceita o primeiro preenchimento, fase 6)
    client_admin.put(f"/api/medicoes/{mid}/valor", json={"campo": "protocolado", "valor": "50.000,00"})
    _no_estado(mid, "nota_emitida")
    client_admin.post(f"/api/medicoes/{mid}/protocolo", json={"data": "2026-08-05"})
    assert client_admin.put(f"/api/medicoes/{mid}/valor",
        json={"campo": "protocolado", "valor": "60.000,00"}).status_code == 422
    # atestado continua editavel (glosa) e a gravacao seguinte persiste
    assert client_admin.put(f"/api/medicoes/{mid}/valor",
        json={"campo": "atestado", "valor": "48.000,00"}).status_code == 200
    assert client_admin.get(f"/api/medicoes/{mid}").json()["valor_atestado_centavos"] == 4_800_000

# --- gate adversarial 1 ---

def _medicao(client_admin, cid, numero=1):
    return client_admin.post(f"/api/contratos/{cid}/medicoes",
        json={"numero": numero, "tipo": "execucao", "competencia": "2026-07"}).json()["id"]

def test_estado_protocolada_nao_e_aceito_pela_rota(client_admin):
    """POST /estado nunca produz `protocolada` -- isso e' exclusividade de POST /protocolo.

    Sem isso a medicao virava "protocolada" sem NENHUMA linha de protocolo e sem
    congelar, e ainda podia seguir ate `recebida` com zero protocolos (spec §5).
    """
    cid = _contrato(client_admin)
    mid = _medicao(client_admin, cid)
    assert client_admin.post(f"/api/medicoes/{mid}/estado",
        json={"estado": "protocolada"}).status_code == 422
    d = client_admin.get(f"/api/medicoes/{mid}").json()
    assert d["estado"] == "prevista" and d["congelada"] == 0 and d["protocolos"] == []
    # e sem protocolo nao ha como avancar
    for alvo in ("nf_emitida", "recebida"):
        assert client_admin.post(f"/api/medicoes/{mid}/estado",
            json={"estado": alvo}).status_code == 422
    d = client_admin.get(f"/api/medicoes/{mid}").json()
    assert d["estado"] == "prevista" and d["protocolos"] == []

def test_competencia_com_digitos_unicode_da_422(client_admin):
    """`\\d` do Python casa digito UNICODE; o GLOB do SQLite so casa [0-9].

    "٢٠٢٦-07" passava no pydantic e estourava o CHECK como IntegrityError (500).
    """
    cid = _contrato(client_admin)
    assert client_admin.post(f"/api/contratos/{cid}/medicoes",
        json={"numero": 1, "tipo": "execucao", "competencia": "٢٠٢٦-07"}).status_code == 422

def test_valor_gigante_da_422(client_admin):
    """Acima de int64 o sqlite3 levanta OverflowError dentro do handler (500)."""
    cid = _contrato(client_admin)
    mid = _medicao(client_admin, cid)
    assert client_admin.put(f"/api/medicoes/{mid}/valor",
        json={"campo": "protocolado", "valor": "9" * 30 + ",00"}).status_code == 422
    assert client_admin.put(f"/api/medicoes/{mid}/valor",
        json={"campo": "protocolado", "valor": "9" * 300 + ",00"}).status_code == 422
    assert client_admin.get(f"/api/medicoes/{mid}").json()["valor_protocolado_centavos"] is None

def test_textos_longos_dao_422(client_admin):
    """Teto nos textos que vao para a auditoria append-only (nao da para apagar depois)."""
    cid = _contrato(client_admin)
    mid = _medicao(client_admin, cid)
    assert client_admin.post(f"/api/medicoes/{mid}/estado",
        json={"estado": "cancelada", "motivo": "x" * 1001}).status_code == 422
    assert client_admin.post(f"/api/medicoes/{mid}/protocolo",
        json={"data": "2026-08-05", "numero_oficio": "O" * 101}).status_code == 422
    assert client_admin.post(f"/api/medicoes/{mid}/protocolo",
        json={"data": "2026-08-05", "numero_processo": "P" * 101}).status_code == 422
    d = client_admin.get(f"/api/medicoes/{mid}").json()
    assert d["estado"] == "prevista" and d["protocolos"] == []
    # no limite ainda passa
    assert client_admin.post(f"/api/medicoes/{mid}/estado",
        json={"estado": "cancelada", "motivo": "x" * 1000}).status_code == 200


def test_escrita_exige_permissao(client):
    from app import auth, db
    conn = db.get_conn()
    auth.criar_usuario(conn, "Dir", "dir@lotufo.com", "senha-forte-123", "diretoria")
    conn.close()
    r = client.post("/api/auth/login", json={"email": "dir@lotufo.com", "senha": "senha-forte-123"})
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))
    client.headers["X-CSRF-Token"] = r.json()["csrf"]
    assert client.post("/api/contratos/1/medicoes",
        json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"}).status_code == 403


def test_valor_em_estado_final_da_422(client_admin):
    """A guarda de estado final chega na rota como 422 (nao 500) e com rollback:
    a escrita seguinte, numa medicao viva, continua funcionando."""
    cid = _contrato(client_admin)
    mid = _medicao(client_admin, cid, 1)
    assert client_admin.post(f"/api/medicoes/{mid}/estado",
        json={"estado": "cancelada", "motivo": "obra paralisada"}).status_code == 200
    for campo in ("protocolado", "atestado"):
        assert client_admin.put(f"/api/medicoes/{mid}/valor",
            json={"campo": campo, "valor": "50.000,00"}).status_code == 422
    d = client_admin.get(f"/api/medicoes/{mid}").json()
    assert d["valor_protocolado_centavos"] is None and d["valor_atestado_centavos"] is None
    outra = _medicao(client_admin, cid, 2)
    assert client_admin.put(f"/api/medicoes/{outra}/valor",
        json={"campo": "protocolado", "valor": "50.000,00"}).status_code == 200


# --- fase 3,5: checklist acoplado ao protocolar ---

def _com_tipo_exigido(client_admin):
    """Contrato + medicao, com UM tipo de certidao aplicavel por padrao e nenhuma
    certidao anexada: o checklist fica pendente."""
    cid = novo_contrato({
        "orgao": "SINFRA", "numero_instrumento": "IC 9/2026", "objeto": "Obra",
        "valor_original": "1.000,00"})
    mid = client_admin.post(f"/api/contratos/{cid}/medicoes",
        json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"}).json()["id"]
    from app import certidoes, db          # a rota de criar tipo saiu no bloco 9
    conn = db.get_conn()
    try:
        certidoes.criar_tipo(conn, None, "CND Federal", "federal", "RFB/PGFN", True)
    finally:
        conn.close()
    return cid, mid


def test_protocolo_travado_por_certidao_pendente(client_admin):
    _, mid = _com_tipo_exigido(client_admin)
    r = client_admin.post(f"/api/medicoes/{mid}/protocolo", json={"data": "2026-08-01"})
    assert r.status_code == 422
    assert "Protocolo travado" in r.json()["detail"] and "CND Federal" in r.json()["detail"]
    # assumir sem justificar tambem nao passa
    r = client_admin.post(f"/api/medicoes/{mid}/protocolo",
                          json={"data": "2026-08-01", "apesar_das_pendencias": True})
    assert r.status_code == 422 and "justificativa" in r.json()["detail"]
    assert client_admin.get(f"/api/medicoes/{mid}").json()["estado"] == "prevista"


def test_protocolo_apesar_das_pendencias_vai_para_a_auditoria(client_admin):
    from app import db
    _, mid = _com_tipo_exigido(client_admin)
    _no_estado(mid, "nota_emitida")
    r = client_admin.post(f"/api/medicoes/{mid}/protocolo", json={
        "data": "2026-08-01", "apesar_das_pendencias": True,
        "justificativa": "órgão aceita a CND em 5 dias"})
    assert r.status_code == 201, r.text
    assert r.json()["ressalva"]["certidoes_pendentes"] == ["CND Federal"]
    assert r.json()["ressalva"]["pendencias"] == ["CND Federal"]
    conn = db.get_conn()
    try:
        depois = conn.execute("SELECT depois FROM audit_log WHERE acao='medicao.protocolo' "
                              "ORDER BY id DESC LIMIT 1").fetchone()[0]
    finally:
        conn.close()
    assert "órgão aceita a CND em 5 dias" in depois and "CND Federal" in depois


def test_protocolo_sem_tipo_exigido_nao_trava(client_admin):
    cid = novo_contrato({
        "orgao": "SINFRA", "numero_instrumento": "IC 8/2026", "objeto": "Obra",
        "valor_original": "1.000,00"})
    mid = client_admin.post(f"/api/contratos/{cid}/medicoes",
        json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"}).json()["id"]
    _no_estado(mid, "nota_emitida")
    r = client_admin.post(f"/api/medicoes/{mid}/protocolo", json={"data": "2026-08-01"})
    assert r.status_code == 201 and r.json()["ressalva"] is None


# --- testes de quebra 10/10/2026, A-16: valor do espelho nao se edita a mao ---

def _medicao_do_espelho(client_admin, origem="espelho"):
    """Medicao em `nota_emitida` com o valor vindo do espelho (como a 631 do banco de teste)."""
    from app import db
    cid = _contrato(client_admin)
    mid = _medicao(client_admin, cid)
    conn = db.get_conn()
    try:
        conn.execute("UPDATE medicoes SET estado='nota_emitida', valor_protocolado_centavos=938483418, "
                     "valor_protocolado_origem=? WHERE id=?", (origem, mid))
        conn.commit()
    finally:
        conn.close()
    return mid


def test_valor_do_espelho_nao_se_edita_a_mao_depois_da_nota(client_admin):
    mid = _medicao_do_espelho(client_admin)
    r = client_admin.put(f"/api/medicoes/{mid}/valor", json={"campo": "protocolado", "valor": "1,00"})
    assert r.status_code == 422 and "gere o espelho de novo" in r.json()["detail"]
    d = client_admin.get(f"/api/medicoes/{mid}").json()
    assert d["valor_protocolado_centavos"] == 938483418 and d["valor_protocolado_origem"] == "espelho"


def test_atestado_da_medicao_do_espelho_continua_editavel(client_admin):
    mid = _medicao_do_espelho(client_admin)
    assert client_admin.put(f"/api/medicoes/{mid}/valor",
                            json={"campo": "atestado", "valor": "9.000.000,00"}).status_code == 200


def test_valor_aceito_continua_editavel_depois_da_nota(client_admin):
    mid = _medicao_do_espelho(client_admin, origem="aceito")
    assert client_admin.put(f"/api/medicoes/{mid}/valor",
                            json={"campo": "protocolado", "valor": "1,00"}).status_code == 200


# --- testes de quebra 10/10/2026, A-09: protocolo manual nao pula a nota sem justificativa ---

def _no_estado(mid, estado):
    from app import db
    conn = db.get_conn()
    try:
        conn.execute("UPDATE medicoes SET estado=? WHERE id=?", (estado, mid))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("estado", ["prevista", "planilha_gerada", "espelho_gerado", "espelho_enviado"])
def test_protocolo_manual_antes_da_nota_exige_justificativa(client_admin, estado):
    from app import db
    mid = _medicao(client_admin, _contrato(client_admin))
    _no_estado(mid, estado)
    r = client_admin.post(f"/api/medicoes/{mid}/protocolo", json={"data": "2026-10-10", "numero_oficio": "OF-A09"})
    assert r.status_code == 422 and "Nota fiscal ainda não emitida" in r.json()["detail"]
    # assumir com justificativa curta tambem nao passa
    r = client_admin.post(f"/api/medicoes/{mid}/protocolo", json={
        "data": "2026-10-10", "apesar_das_pendencias": True, "justificativa": "ok"})
    assert r.status_code == 422 and "justificativa" in r.json()["detail"]
    d = client_admin.get(f"/api/medicoes/{mid}").json()
    assert d["estado"] == estado and d["protocolos"] == []
    r = client_admin.post(f"/api/medicoes/{mid}/protocolo", json={
        "data": "2026-10-10", "apesar_das_pendencias": True,
        "justificativa": "órgão pediu o protocolo antes da nota"})
    assert r.status_code == 201, r.text
    # gate Sol S3: a falta da nota vai em `pendencias`; `certidoes_pendentes` so' com certidoes
    assert r.json()["ressalva"]["pendencias"] == [
        "Nota fiscal ainda não emitida: protocolar agora pula o faturamento e a nota"]
    assert r.json()["ressalva"]["certidoes_pendentes"] == []
    assert client_admin.get(f"/api/medicoes/{mid}").json()["estado"] == "protocolada"
    conn = db.get_conn()
    try:
        depois = conn.execute("SELECT depois FROM audit_log WHERE acao='medicao.protocolo' "
                              "ORDER BY id DESC LIMIT 1").fetchone()[0]
    finally:
        conn.close()
    assert "Nota fiscal ainda não emitida" in depois and "órgão pediu o protocolo antes da nota" in depois


def test_protocolo_manual_com_nota_emitida_segue_como_antes(client_admin):
    mid = _medicao(client_admin, _contrato(client_admin))
    _no_estado(mid, "nota_emitida")
    r = client_admin.post(f"/api/medicoes/{mid}/protocolo", json={"data": "2026-10-10"})
    assert r.status_code == 201 and r.json()["ressalva"] is None


def test_valor_acima_do_teto_brl_da_422(client_admin):
    """A-08: o teto e' o do espelho (R$ 99.999.999.999,99), nao mais so' o int64."""
    mid = _medicao(client_admin, _contrato(client_admin))
    r = client_admin.put(f"/api/medicoes/{mid}/valor", json={"campo": "atestado", "valor": "99999999999999999999,00"})
    assert r.status_code == 422 and "máximo aceito" in r.json()["detail"]
    r = client_admin.put(f"/api/medicoes/{mid}/valor", json={"campo": "atestado", "valor": "100.000.000.000,00"})
    assert r.status_code == 422
    assert client_admin.put(f"/api/medicoes/{mid}/valor",
                            json={"campo": "atestado", "valor": "99.999.999.999,99"}).status_code == 200
    assert client_admin.get(f"/api/medicoes/{mid}").json()["valor_atestado_centavos"] == 9_999_999_999_999


def test_atestado_com_digito_arabe_indico_da_422(client_admin):
    """A-14 (testes de quebra 10/10/2026): "١٢٣,٤٥" era gravado como 12345."""
    mid = _medicao(client_admin, _contrato(client_admin))
    assert client_admin.put(f"/api/medicoes/{mid}/valor",
                            json={"campo": "atestado", "valor": "١٢٣,٤٥"}).status_code == 422
    assert client_admin.get(f"/api/medicoes/{mid}").json()["valor_atestado_centavos"] is None
    assert client_admin.put(f"/api/medicoes/{mid}/valor",
                            json={"campo": "atestado", "valor": "123,45"}).status_code == 200


def test_certidao_pendente_exige_justificativa_de_10_caracteres(client_admin):
    """Gate Sol S6 (10/10/2026): qualquer pendencia assumida exige MIN_JUSTIFICATIVA, certidao ou nota."""
    _, mid = _com_tipo_exigido(client_admin)
    _no_estado(mid, "nota_emitida")
    for curta in ("x", "  curta   "):
        r = client_admin.post(f"/api/medicoes/{mid}/protocolo", json={
            "data": "2026-08-01", "apesar_das_pendencias": True, "justificativa": curta})
        assert r.status_code == 422
        assert r.json()["detail"] == "Protocolar com pendência exige justificativa (ao menos 10 caracteres)"
    assert client_admin.get(f"/api/medicoes/{mid}").json()["estado"] == "nota_emitida"


def test_linha_do_tempo_traz_a_edicao_de_valor(client_admin):
    """B-02 (10/10/2026): editar o valor nao aparecia na linha do tempo da medicao."""
    cid = _contrato(client_admin)
    mid = client_admin.post(f"/api/contratos/{cid}/medicoes",
                            json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"}).json()["id"]
    for valor in ("1.000,00", "1.234,56", "1.234,56"):       # o terceiro nao muda nada: nao vira evento
        client_admin.put(f"/api/medicoes/{mid}/valor", json={"campo": "protocolado", "valor": valor})
    client_admin.put(f"/api/medicoes/{mid}/valor", json={"campo": "atestado", "valor": "1.200,00", "data": "2026-08-10"})
    eventos = client_admin.get(f"/api/medicoes/{mid}").json()["edicoes_valor"]
    assert [e["texto"] for e in eventos] == [
        "Valor protocolado definido em R$ 1.000,00 por Admin",
        "Valor protocolado alterado de R$ 1.000,00 para R$ 1.234,56 por Admin",
        "Atestado definido em R$ 1.200,00 por Admin",
    ]
    assert all(e["data"] for e in eventos)
    # a pagina da medicao le a lista da obra
    assert client_admin.get(f"/api/contratos/{cid}/medicoes").json()[0]["edicoes_valor"] == eventos


def test_auditoria_torta_nao_derruba_a_medicao(client_admin):
    """Gate Sol S1 (10/10/2026): linha antiga de auditoria com JSON invalido ou nao-dicionario dava 500."""
    from app import db
    cid = _contrato(client_admin)
    mid = client_admin.post(f"/api/contratos/{cid}/medicoes",
                            json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"}).json()["id"]
    client_admin.put(f"/api/medicoes/{mid}/valor", json={"campo": "protocolado", "valor": "1.000,00"})
    conn = db.get_conn()
    for antes, depois in (("[]", '{"valor_protocolado_centavos": 5}'), ("", "{torto"), (None, "[1, 2]")):
        conn.execute("INSERT INTO audit_log (usuario_id, acao, entidade, entidade_id, antes, depois, hash_prev, hash) "
                     "VALUES (1, 'medicao.valor_protocolado', 'medicao', ?, ?, ?, 'x', 'y')", (str(mid), antes, depois))
    conn.commit(); conn.close()
    r = client_admin.get(f"/api/medicoes/{mid}")
    assert r.status_code == 200
    assert [e["texto"] for e in r.json()["edicoes_valor"]] == ["Valor protocolado definido em R$ 1.000,00 por Admin"]
    assert client_admin.get(f"/api/contratos/{cid}/medicoes").status_code == 200


# --- issue #12: medicao manual nao nasce fora do espelho numa obra com regra ativa ---

def _com_regra_de_espelho(cid, situacao):
    """Regra com saidas de execucao e reajuste (como a da 5 Bairros): nenhuma de projeto."""
    import json
    from app import db
    regra = {"saidas": [{"chave": "medicao", "natureza": "medicao"}, {"chave": "reajuste", "natureza": "reajuste"}]}
    conn = db.get_conn()
    try:
        conn.execute("INSERT INTO espelho_regras (contrato_id, situacao, regra, modelos, sha256) "
                     "VALUES (?,?,?,'{}','x')", (cid, situacao, json.dumps(regra)))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("tipo", ["execucao", "reajuste", "projeto"])
def test_medicao_manual_recusada_em_obra_com_regra_ativa(client_admin, tipo):
    """Qualquer tipo, inclusive o que a regra nao gera (aqui, projeto): a issue nao abre excecao."""
    cid = _contrato(client_admin)
    _com_regra_de_espelho(cid, "ativa")
    r = client_admin.post(f"/api/contratos/{cid}/medicoes",
                          json={"numero": 1, "tipo": tipo, "competencia": "2026-07"})
    assert r.status_code == 422 and "Gerar espelho" in r.json()["detail"]
    assert client_admin.get(f"/api/contratos/{cid}/medicoes").json() == []


@pytest.mark.parametrize("situacao", [None, "prova"])
def test_medicao_manual_segue_em_obra_sem_regra_ativa(client_admin, situacao):
    cid = _contrato(client_admin)
    if situacao:
        _com_regra_de_espelho(cid, situacao)
    r = client_admin.post(f"/api/contratos/{cid}/medicoes",
                          json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"})
    assert r.status_code == 201


# --- issue #53: recebimento manual so' para admin, com motivo obrigatorio e auditado ---

def _protocolada(client_admin):
    mid = _medicao(client_admin, _contrato(client_admin))
    _no_estado(mid, "protocolada")
    return mid


def _entrar(cl, email):
    cl.cookies.clear()
    r = cl.post("/api/auth/login", json={"email": email, "senha": "senha-forte-123"})
    assert r.status_code == 200, r.text
    cl.cookies.set("sessao", r.cookies.get("sessao") or cl.cookies.get("sessao"))
    cl.headers["X-CSRF-Token"] = r.json()["csrf"]


def test_recebimento_manual_e_so_do_admin(client_admin):
    from app import auth, db
    mid = _protocolada(client_admin)
    outra = _protocolada(client_admin)
    conn = db.get_conn()
    auth.criar_usuario(conn, "Eng", "eng@lotufo.com", "senha-forte-123", "engenharia")
    conn.close()
    _entrar(client_admin, "eng@lotufo.com")
    r = client_admin.post(f"/api/medicoes/{mid}/estado", json={"estado": "recebida", "motivo": MOTIVO_RM})
    assert r.status_code == 403 and "administrador" in r.json()["detail"]
    assert client_admin.get(f"/api/medicoes/{mid}").json()["estado"] == "protocolada"
    # os outros atos da rota seguem com a engenharia
    assert client_admin.post(f"/api/medicoes/{outra}/estado", json={"estado": "cancelada"}).status_code == 200


@pytest.mark.parametrize("motivo", [None, "", "   ", "curto", "  nove car "])
def test_recebimento_manual_exige_motivo(client_admin, motivo):
    mid = _protocolada(client_admin)
    corpo = {"estado": "recebida"} if motivo is None else {"estado": "recebida", "motivo": motivo}
    r = client_admin.post(f"/api/medicoes/{mid}/estado", json=corpo)
    assert r.status_code == 422 and "motivo" in r.json()["detail"]
    assert client_admin.get(f"/api/medicoes/{mid}").json()["estado"] == "protocolada"


def test_recebimento_manual_audita_o_motivo(client_admin):
    import json
    from app import db
    mid = _protocolada(client_admin)
    r = client_admin.post(f"/api/medicoes/{mid}/estado",
                          json={"estado": "recebida", "motivo": f"  {MOTIVO_RM}  ", "data": "2026-09-30"})
    assert r.status_code == 200
    conn = db.get_conn()
    try:
        ultimo = conn.execute("SELECT usuario_id, depois FROM audit_log WHERE acao='medicao.estado' "
                              "AND entidade_id=? ORDER BY id DESC LIMIT 1", (str(mid),)).fetchone()
    finally:
        conn.close()
    assert ultimo["usuario_id"] is not None
    # #203: a rota grava tambem a origem "manual", que o servidor controla (o motivo nao decide)
    assert json.loads(ultimo["depois"]) == {"estado": "recebida", "motivo": MOTIVO_RM, "recebida_em": "2026-09-30",
                                            "origem": "manual"}


def test_recebimento_pela_rota_e_manual_mesmo_com_motivo_que_imita_o_corte(client_admin):
    """Issue #203 (gate Sol S2): a rota grava a origem "manual" na auditoria; o motivo digitado nao decide."""
    from app import conciliacao, db
    mid = _protocolada(client_admin)
    assert client_admin.post(f"/api/medicoes/{mid}/estado",
        json={"estado": "recebida", "motivo": "corte de 22/09/2026: baixa conferida no extrato"}).status_code == 200
    conn = db.get_conn()
    try:
        assert mid in conciliacao.recebidas_a_mao(conn)
    finally:
        conn.close()


# --- issue #281: planilha/carta de medicao ---------------------------------------------------------------

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _arquivos_planilha(texto="Oficio CT assinado"):
    from tests.conftest import _pdf_com_texto
    return {"oficio": ("oficio.pdf", _pdf_com_texto(texto), "application/pdf"),
            "planilha": ("planilha.xlsx", b"PK\x03\x04" + texto.encode() + b"\x00" * 64, XLSX)}


def _nova_planilha(cl, cid, numero=1, competencia="2026-07", inicio="2026-07-01", fim="2026-07-31",
                   valor="12.345,67", **extra):
    return cl.post(f"/api/contratos/{cid}/planilhas", files=_arquivos_planilha(f"oficio {numero} {inicio}"),
                   data={"numero": numero, "competencia": competencia, "periodo_inicio": inicio,
                         "periodo_fim": fim, "valor": valor, **extra})


def test_planilha_cria_versao_1_e_poe_em_planilha_gerada(client_admin):
    cid = _contrato(client_admin)
    r = _nova_planilha(client_admin, cid, numero_orgao=7)
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert corpo["versao"] == 1 and corpo["estado"] == "planilha_gerada" and corpo["avisos"] == []
    assert corpo["acumulado_anterior_centavos"] == 0 and corpo["saldo_apos_pedido_centavos"] == 100_000_00 - 12_345_67
    d = client_admin.get(f"/api/medicoes/{corpo['medicao_id']}").json()
    assert d["estado"] == "planilha_gerada" and d["valor_protocolado_centavos"] == 12_345_67
    assert (d["periodo_inicio"], d["periodo_fim"], d["numero_orgao"]) == ("2026-07-01", "2026-07-31", 7)
    assert [(p["versao"], p["valor_pedido_centavos"]) for p in d["planilhas"]] == [(1, 12_345_67)]


def test_planilha_exige_os_dois_anexos_e_pdf_de_verdade(client_admin):
    cid = _contrato(client_admin)
    dados = {"numero": 1, "competencia": "2026-07", "periodo_inicio": "2026-07-01", "periodo_fim": "2026-07-31",
             "valor": "1,00"}
    so_oficio = {"oficio": _arquivos_planilha()["oficio"]}
    assert client_admin.post(f"/api/contratos/{cid}/planilhas", files=so_oficio, data=dados).status_code == 422
    falso = {**_arquivos_planilha(), "oficio": ("oficio.pdf", b"nao sou pdf", "application/pdf")}
    assert client_admin.post(f"/api/contratos/{cid}/planilhas", files=falso, data=dados).status_code == 415
    assert client_admin.get(f"/api/contratos/{cid}/medicoes").json() == []


def test_planilha_periodo_invertido_da_422(client_admin):
    cid = _contrato(client_admin)
    assert _nova_planilha(client_admin, cid, inicio="2026-07-31", fim="2026-07-01").status_code == 422


def test_planilha_recusada_nao_deixa_arquivo_na_pasta(client_admin):
    from app import db
    cid = _contrato(client_admin)
    assert _nova_planilha(client_admin, cid).status_code == 201
    pasta = db.db_path().parent / "planilhas"
    antes = sorted(p.name for p in pasta.iterdir())
    r = _nova_planilha(client_admin, cid, inicio="2026-07-02")     # mesmo nº: recusa, com anexos novos
    assert r.status_code == 422 and "registre uma revisão" in r.json()["detail"]
    r = client_admin.post(f"/api/medicoes/{_mid_unica(client_admin, cid)}/planilhas",
                          files=_arquivos_planilha("sem motivo"),
                          data={"periodo_inicio": "2026-07-01", "periodo_fim": "2026-07-31", "valor": "1,00"})
    assert r.status_code == 422
    assert sorted(p.name for p in pasta.iterdir()) == antes


def _mid_unica(cl, cid):
    return cl.get(f"/api/contratos/{cid}/medicoes").json()[0]["id"]


def _pasta_planilhas():
    from app import db
    pasta = db.db_path().parent / "planilhas"
    return sorted(p.name for p in pasta.iterdir()) if pasta.exists() else []


def test_planilha_invalida_nao_deixa_o_oficio_gravado(client_admin):
    """Gate Sol rodada 1: os dois anexos sao validados antes de gravar qualquer um."""
    cid = _contrato(client_admin)
    arquivos_ = {**_arquivos_planilha(), "planilha": ("planilha.xlsx", b"nao sou zip", XLSX)}
    r = client_admin.post(f"/api/contratos/{cid}/planilhas", files=arquivos_, data={
        "numero": 1, "competencia": "2026-07", "periodo_inicio": "2026-07-01", "periodo_fim": "2026-07-31",
        "valor": "1,00"})
    assert r.status_code == 415
    assert _pasta_planilhas() == []


def test_registro_que_falha_com_o_mesmo_pdf_nao_apaga_o_arquivo_da_versao(client_admin, monkeypatch):
    """Gate Sol rodada 2: a requisicao que falha (corrida, clique duplo) nao apaga nada; o arquivo de que a versao
    ja' registrada depende continua na pasta."""
    from app import db, medicao_planilhas
    cid = _contrato(client_admin)
    mid = _nova_planilha(client_admin, cid).json()["medicao_id"]
    antes = _pasta_planilhas()

    def recusa(*_a, **_k):
        raise ValueError("Estado da medição mudou concorrentemente; tente novamente")
    monkeypatch.setattr(medicao_planilhas, "registrar", recusa)
    r = client_admin.post(f"/api/contratos/{cid}/planilhas", files=_arquivos_planilha("oficio 1 2026-07-01"),
                          data={"numero": 2, "competencia": "2026-08", "periodo_inicio": "2026-08-01",
                                "periodo_fim": "2026-08-31", "valor": "1,00"})
    assert r.status_code == 422
    assert _pasta_planilhas() == antes and len(antes) == 2
    v = client_admin.get(f"/api/medicoes/{mid}").json()["planilhas"][0]
    pasta = db.db_path().parent / "planilhas"
    assert (pasta / f"{v['sha256']}.pdf").exists() and (pasta / f"{v['sha256_planilha']}.xlsx").exists()
    # conteudo NOVO (revisor, rodada 2): a limpeza antiga apagaria estes dois; agora ficam (o outro clique pode
    # ja' depender deles)
    r = client_admin.post(f"/api/contratos/{cid}/planilhas", files=_arquivos_planilha("oficio novo da 2a"),
                          data={"numero": 2, "competencia": "2026-08", "periodo_inicio": "2026-08-01",
                                "periodo_fim": "2026-08-31", "valor": "1,00"})
    assert r.status_code == 422
    assert len(_pasta_planilhas()) == 4 and set(antes) < set(_pasta_planilhas())


def test_revisao_sem_motivo_recusada_com_motivo_vira_versao_2(client_admin):
    cid = _contrato(client_admin)
    mid = _nova_planilha(client_admin, cid).json()["medicao_id"]
    rev = {"periodo_inicio": "2026-07-01", "periodo_fim": "2026-07-31", "valor": "11.000,01"}
    r = client_admin.post(f"/api/medicoes/{mid}/planilhas", files=_arquivos_planilha("rev"), data=rev)
    assert r.status_code == 422 and "motivo" in r.json()["detail"]
    r = client_admin.post(f"/api/medicoes/{mid}/planilhas", files=_arquivos_planilha("rev01"),
                          data={**rev, "motivo": "Rev01: supervisora pediu ajuste no item 3"})
    assert r.status_code == 201, r.text
    assert r.json()["versao"] == 2
    d = client_admin.get(f"/api/medicoes/{mid}").json()
    assert [(p["versao"], p["valor_pedido_centavos"], p["motivo"]) for p in d["planilhas"]] == [
        (1, 12_345_67, None), (2, 11_000_01, "Rev01: supervisora pediu ajuste no item 3")]
    assert d["valor_protocolado_centavos"] == 11_000_01


def test_periodo_sobreposto_ou_pulando_devolve_aviso_e_grava(client_admin):
    cid = _contrato(client_admin)
    assert _nova_planilha(client_admin, cid, 1, "2026-07", "2026-06-26", "2026-07-25").json()["avisos"] == []
    r = _nova_planilha(client_admin, cid, 2, "2026-08", "2026-07-20", "2026-08-25")
    assert r.status_code == 201 and len(r.json()["avisos"]) == 1 and "sobrepõe" in r.json()["avisos"][0]
    r = _nova_planilha(client_admin, cid, 3, "2026-10", "2026-09-26", "2026-10-25")
    assert r.status_code == 201 and len(r.json()["avisos"]) == 1 and "pula" in r.json()["avisos"][0]
    assert [m["estado"] for m in client_admin.get(f"/api/contratos/{cid}/medicoes").json()] == ["planilha_gerada"] * 3


def test_planilha_diretoria_recebe_403(client_admin):
    from app import auth, db
    cid = _contrato(client_admin)
    mid = _nova_planilha(client_admin, cid).json()["medicao_id"]
    conn = db.get_conn()
    auth.criar_usuario(conn, "Dir", "dir@lotufo.com", "senha-forte-123", "diretoria")
    conn.close()
    _entrar(client_admin, "dir@lotufo.com")
    assert _nova_planilha(client_admin, cid, 2, "2026-08", "2026-08-01", "2026-08-31").status_code == 403
    assert client_admin.post(f"/api/medicoes/{mid}/planilhas", files=_arquivos_planilha(),
                             data={"periodo_inicio": "2026-07-01", "periodo_fim": "2026-07-31", "valor": "1,00",
                                   "motivo": "Rev01"}).status_code == 403
    # diretoria so' le: a sugestao (com acumulado e saldo) e a medicao com as versoes
    assert client_admin.get(f"/api/contratos/{cid}/planilhas/sugestao").json()["numero"] == 2
    assert len(client_admin.get(f"/api/medicoes/{mid}").json()["planilhas"]) == 1
