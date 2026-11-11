"""Redesenho 2026-11 (#507): o endpoint da lista "Em andamento" devolve o passo atual e o lado de cada medicao."""
import pytest
from tests.conftest import novo_contrato


@pytest.fixture(autouse=True)
def _sem_certidoes(sem_certidoes_exigidas):
    """Estes testes nao sao sobre certidoes (ver conftest)."""


def test_resumo_devolve_o_passo_da_medicao_no_quadro(client_admin):
    cid = novo_contrato({"orgao": "SINFRA", "numero_instrumento": "IC 1/2026", "objeto": "Obra", "valor_original": "100.000,00"})
    mid = client_admin.post(f"/api/contratos/{cid}/medicoes",
                            json={"numero": 1, "tipo": "execucao", "competencia": "2026-09"}).json()["id"]
    from app import db
    c = db.get_conn()
    c.execute("UPDATE medicoes SET estado='planilha_enviada' WHERE id=?", (mid,))
    c.commit()
    c.close()
    r = client_admin.get("/api/medicoes/resumo?mes=2026-09")
    assert r.status_code == 200
    [linha] = r.json()["quadro"]
    [atual] = [p for p in linha["passos"] if p["situacao"] == "atual"]
    assert (atual["numero"], atual["nome"], atual["medicao_id"]) == (2, "Análise do órgão", mid)
    # #699: a lista "em andamento" antiga (`linhas`) e as contagens do menu sairam da resposta
    assert r.json()["mes"] == "2026-09" and "linhas" not in r.json() and "contagens" not in r.json()
    assert client_admin.get("/api/medicoes/resumo?mes=2026-13").status_code == 422
