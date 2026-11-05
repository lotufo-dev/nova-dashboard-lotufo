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
    assert set(r.json()) == {"hoje", "notas_a_enviar", "certidoes", "reajustes", "protocoladas", "medido",
                             "por_contratante", "recebido_ano", "a_receber", "prazos"}
    assert r.json()["protocoladas"]["obras_ativas"] == 1


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
