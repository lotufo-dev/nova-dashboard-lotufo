"""Rotas da tela inicial, das medicoes em andamento e dos dados da obra (bloco 6)."""
import pytest
from tests.conftest import novo_contrato


@pytest.fixture(autouse=True)
def _sem_certidoes(sem_certidoes_exigidas):
    """Estes testes nao sao sobre certidoes (ver conftest)."""


def _obra(cl):
    cid = novo_contrato({"orgao": "SINFRA", "numero_instrumento": "IC 1/2026", "objeto": "Obra X",
                                          "valor_original": "1.000,00"})
    mid = cl.post(f"/api/contratos/{cid}/medicoes",
                  json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"}).json()["id"]
    cl.put(f"/api/medicoes/{mid}/valor", json={"campo": "protocolado", "valor": "250,00"})
    cl.post(f"/api/medicoes/{mid}/protocolo", json={  # A-09: sem nota, so' assumido
        "data": "2026-07-28", "apesar_das_pendencias": True, "justificativa": "cenário de teste sem nota"})
    return cid


def test_inicio_e_medicoes_em_andamento(client_admin):
    cid = _obra(client_admin)
    r = client_admin.get("/api/inicio")
    assert r.status_code == 200 and set(r.json()) == {"avisos", "resumo"}
    assert r.json()["resumo"]["obras_ativas"] == 1
    assert [m["contrato_id"] for m in client_admin.get("/api/medicoes/andamento?estado=protocolada").json()] == [cid]
    assert client_admin.get("/api/medicoes/andamento?estado=nota_emitida").json() == []


def test_termo_que_nao_esta_no_cadastro_nao_chega_ao_inicio_e_vai_para_o_admin(client_admin):
    # issue #649: a nota de reajuste sem termo que cubra a competencia so' diz "nao achamos o documento"; sai da lista
    # de avisos (/api/inicio), que e' tambem a fila da caixa do Inicio (#666), e vira pendencia de cadastro
    cid = _obra_reajuste("Obra R", "099/2024")
    _reajuste_com_nota(cid, 1, "2025-09", 300_05)
    tipos = {a["tipo"] for a in client_admin.get("/api/inicio").json()["avisos"]}
    assert not tipos & {"reajuste_nota_antes_do_apostilamento", "reajuste_sem_apostilamento", "reajuste_fora_da_previsao"}
    assert "avisos_importantes" not in client_admin.get("/api/inicio/painel").json()      # #666: a caixa le /api/inicio
    assert client_admin.get("/api/admin/pendencias-cadastro").json()["documentos"] == [
        {"contrato_id": cid, "obra": "Obra R", "falta": "Termo de apostilamento da competência 09/2025 não está no cadastro",
         "desde": "2025-09", "aba": "reajuste"}]


def _obra_reajuste(nome, numero):
    """Obra com data-base 06/2024 (ciclos de 2025 e 2026 ja' abertos)."""
    from app import db
    cid = novo_contrato({"orgao": "MTPAR", "numero_instrumento": numero, "objeto": nome, "valor_original": "1.000,00"})
    c = db.get_conn()
    c.execute("UPDATE contratos SET nome_curto=? WHERE id=?", (nome, cid))
    c.execute("INSERT INTO contrato_datas_base (contrato_id, mes, indice) VALUES (?, '2024-06', 'INCC-DI')", (cid,))
    c.commit(); c.close()
    return cid


def _reajuste_com_nota(cid, numero, comp, valor):
    from app import db
    c = db.get_conn()
    c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
              "valor_atestado_centavos) VALUES (?, ?, 'reajuste', ?, 'nota_emitida', ?, ?)", (cid, numero, comp, valor, valor))
    mid = c.execute("SELECT MAX(id) FROM medicoes").fetchone()[0]
    c.execute("INSERT INTO notas_fiscais (coligada, numero, valor_centavos, situacao, origem) VALUES (1, ?, ?, 'ativa', 'pdf')",
              (f"NF-{mid}", valor))
    nid = c.execute("SELECT MAX(id) FROM notas_fiscais").fetchone()[0]
    c.execute("INSERT INTO nf_alocacoes (medicao_id, nota_id, valor_alocado_centavos, origem) VALUES (?, ?, ?, 'manual')",
              (mid, nid, valor))
    c.commit(); c.close()


def test_fila_do_inicio_da_diretoria_nao_traz_a_pendencia_de_cadastro(client_admin):
    # revisor (rodada 2 da PR #579): a fila segue o perfil. Issue #649: nem a operacao nem a diretoria veem a nota
    # sem termo no cadastro. Issue #666: a caixa do Inicio le esta mesma fila, entao a pendencia nao conta nela
    from app import auth, db
    cid = _obra_reajuste("Obra Alfa", "001/2024")
    _reajuste_com_nota(cid, 1, "2025-07", 300_000_00)
    assert not [a for a in client_admin.get("/api/inicio").json()["avisos"] if a["natureza"] != "fato"]
    c = db.get_conn()
    auth.criar_usuario(c, "Diretoria", "dir@lotufo.com", "senha-forte-123", "diretoria")
    c.close()
    r = client_admin.post("/api/auth/login", json={"email": "dir@lotufo.com", "senha": "senha-forte-123"})
    client_admin.cookies.set("sessao", r.cookies.get("sessao") or client_admin.cookies.get("sessao"))
    assert "avisos_importantes" not in client_admin.get("/api/inicio/painel").json()
    assert not [a for a in client_admin.get("/api/inicio").json()["avisos"] if a["natureza"] != "fato"]
    assert client_admin.get("/api/admin/pendencias-cadastro").status_code == 403


def test_dados_da_obra_e_404(client_admin):
    cid = _obra(client_admin)
    assert client_admin.get(f"/api/contratos/{cid}/cabecalho").json()["status"] == "ativo"
    assert set(client_admin.get(f"/api/contratos/{cid}/cadastro").json()) == {"datas_base", "fiscais", "aditivos",
                                                                            "instrumentos"}
    assert client_admin.get(f"/api/contratos/{cid}/notas").json()[0]["titulo"] == "1ª Medição"
    for rota in ("cabecalho", "cadastro", "notas"):
        assert client_admin.get(f"/api/contratos/999/{rota}").status_code == 404


def test_painel_do_inicio(client_admin):
    _obra(client_admin)
    r = client_admin.get("/api/inicio/painel")
    assert r.status_code == 200
    # #699: so' o que a tela le; as chaves dos cartoes antigos (notas a enviar, certidoes, reajustes, recebido no ano,
    # prazos, espelhos) sairam
    assert set(r.json()) == {"hoje", "protocoladas", "medido", "a_receber", "ciclo", "notas_mes",
                             "recebido_12m", "previsao", "matriz"}
    assert [e["etapa"] for e in r.json()["ciclo"]] == ["em_analise", "boletim", "nota", "protocolado", "recebido_mes"]
    assert r.json()["protocoladas"]["obras_ativas"] == 1


def test_faixa_do_ciclo_e_a_mesma_para_admin_diretoria_e_engenharia(client_admin):
    # issue #642: a obra de teste tem uma medicao protocolada em 28/07/2026, de R$ 250,00
    from app import auth, db
    _obra(client_admin)
    faixa = client_admin.get("/api/inicio/painel").json()["ciclo"]
    protocolado = next(e for e in faixa if e["etapa"] == "protocolado")
    assert (protocolado["valor_centavos"], protocolado["quantidade"]) == (250_00, 1)
    c = db.get_conn()
    for perfil in ("diretoria", "engenharia"):
        auth.criar_usuario(c, perfil.capitalize(), f"{perfil}@lotufo.com", "senha-forte-123", perfil)
    c.close()
    for perfil in ("diretoria", "engenharia"):
        r = client_admin.post("/api/auth/login", json={"email": f"{perfil}@lotufo.com", "senha": "senha-forte-123"})
        client_admin.cookies.set("sessao", r.cookies.get("sessao") or client_admin.cookies.get("sessao"))
        assert client_admin.get("/api/inicio/painel").json()["ciclo"] == faixa


def test_painel_do_inicio_exige_login(client):
    assert client.get("/api/inicio/painel").status_code == 401


def test_obras_ativas_tem_uma_definicao_nas_tres_rotas(client_admin):
    """A-21 (10/10/2026): "obras ativas" = ativo sem encerramento iniciado (`avisos.ativos`) no Inicio e em
    Medicoes; o farol da Carteira conta mais obras, mas diz a base (ativas, em encerramento, suspensas)."""
    from app import db
    ids = [novo_contrato({"orgao": "SINFRA", "numero_instrumento": f"IC {i}/2026", "objeto": f"Obra {i}",
                          "valor_original": "1.000,00"}) for i in range(5)]
    conn = db.get_conn()
    conn.execute("INSERT INTO orgaos (chave, nome, familia, regras) VALUES ('sinfra', 'SINFRA', 'sinfra', '{}')")
    conn.execute("UPDATE contratos SET orgao_id=(SELECT id FROM orgaos WHERE chave='sinfra')")
    conn.execute("UPDATE contratos SET encerramento_iniciado_em='2026-09-01' WHERE id=?", (ids[1],))
    conn.execute("UPDATE contratos SET estado='suspenso' WHERE id=?", (ids[2],))
    conn.execute("UPDATE contratos SET estado='rescindido' WHERE id=?", (ids[3],))
    conn.commit(); conn.close()
    inicio = client_admin.get("/api/inicio/painel").json()["protocoladas"]["obras_ativas"]
    obras = client_admin.get("/api/medicoes/resumo").json()["obras"]
    diretoria = client_admin.get("/api/diretoria").json()
    assert inicio == 2
    assert sum(1 for o in obras if not o["encerramento"]) == inicio
    assert sum(1 for o in obras if o["encerramento"]) == 1
    assert diretoria["obras_base"] == {"ativas": inicio, "encerramento": 1, "suspensas": 1, "encerradas": 0}
    assert len(diretoria["obras"]) == sum(diretoria["obras_base"].values()) == 4


def test_cadastro_da_obra_traz_o_indice_da_data_base_depois_do_aplicar(client_admin):
    # issue #397: a tela da obra le o indice de contrato_datas_base (ObraAbas.tsx), nunca a tabela de precos
    from app import cadastro_aplicar, db
    from tests.test_cadastro_aplicar import _cad, _contrato
    cid = _obra(client_admin)
    conn = db.get_conn()
    conn.execute("UPDATE contratos SET indice_reajuste='SINAPI', numero_instrumento='019/2024/00/00-SINFRA' "
                 "WHERE id=?", (cid,))
    conn.commit()
    valor = conn.execute("SELECT valor_original_centavos FROM contratos WHERE id=?", (cid,)).fetchone()[0]
    c = _contrato(valor_original_centavos=valor, datas_base=[{"mes": "2023-04", "indice": "INCC-DI/FGV"}])
    cadastro_aplicar.aplicar(conn, 1, _cad(contratos=[c]))
    assert conn.execute("SELECT indice_reajuste FROM contratos WHERE id=?", (cid,)).fetchone()[0] == "INCC-DI/FGV"
    conn.close()
    bases = client_admin.get(f"/api/contratos/{cid}/cadastro").json()["datas_base"]
    assert [b["indice"] for b in bases] == ["INCC-DI/FGV"]
