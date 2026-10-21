import pytest
from tests.conftest import novo_contrato


@pytest.fixture(autouse=True)
def _sem_certidoes(sem_certidoes_exigidas):
    """Fase 3,5: estes testes nao sao sobre certidoes (ver conftest)."""


def _cenario(client_admin):
    cid = novo_contrato({
        "orgao": "SINFRA", "numero_instrumento": "IC 1/2026", "objeto": "Obra X",
        "valor_original": "1.000,00"})
    client_admin.post(f"/api/contratos/{cid}/cronograma", json={
        "itens": [{"competencia": "2026-07", "valor": "300,00"}]})
    mid = client_admin.post(f"/api/contratos/{cid}/medicoes",
        json={"numero": 1, "tipo": "execucao", "competencia": "2026-07"}).json()["id"]
    client_admin.put(f"/api/medicoes/{mid}/valor", json={"campo": "protocolado", "valor": "250,00"})
    client_admin.post(f"/api/medicoes/{mid}/protocolo", json={  # A-09: sem nota, so' assumido
        "data": "2026-07-28", "apesar_das_pendencias": True, "justificativa": "cenário de teste sem nota"})
    return cid

def test_curva(client_admin):
    cid = _cenario(client_admin)
    r = client_admin.get(f"/api/contratos/{cid}/curva").json()
    assert r["curva"][0]["previsto_centavos"] == 300_00
    assert r["saldo"]["saldo_centavos"] == 750_00 and r["saldo"]["formula"].startswith("saldo")

def test_alertas_endpoint(client_admin):
    _cenario(client_admin)
    r = client_admin.get("/api/paineis/alertas")
    assert r.status_code == 200 and isinstance(r.json(), list)

def test_csv_medicoes(client_admin):
    cid = _cenario(client_admin)
    r = client_admin.get(f"/api/contratos/{cid}/medicoes.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    corpo = r.content.decode("utf-8-sig")
    assert corpo.splitlines()[0] == "numero;tipo;competencia;estado;valor_protocolado;valor_atestado;origem_protocolado"
    assert "1;execucao;2026-07;protocolada;R$ 250,00;;manual" in corpo

def test_csv_contrato_inexistente_404(client_admin):
    assert client_admin.get("/api/contratos/9999/medicoes.csv").status_code == 404
    assert client_admin.get("/api/contratos/9999/curva").status_code == 404

def test_paineis_exigem_sessao(client):
    for rota in ("/api/paineis/alertas", "/api/contratos/1/curva", "/api/contratos/1/medicoes.csv"):
        assert client.get(rota).status_code == 401, rota


def test_rotas_da_deteccao_sairam(client_admin):
    """Bloco 9: fila de sugestoes, leitura do Graph e paineis antigos fora da API."""
    for rota in ("/api/sugestoes", "/api/graph/status", "/api/paineis/engenharia",
                 "/api/paineis/consolidado", "/api/paineis/consolidado.csv"):
        assert client_admin.get(rota).status_code == 404, rota


def test_curva_traz_a_linha_anterior_e_as_marcas_dos_aditivos(client_admin):
    cid = _cenario(client_admin)
    r0 = client_admin.get(f"/api/contratos/{cid}/curva").json()
    assert r0["anterior"] is None and r0["aditivos"] == []
    client_admin.post(f"/api/contratos/{cid}/cronograma", json={
        "itens": [{"competencia": "2026-07", "valor": "100,00"}, {"competencia": "2026-08", "valor": "100,00"}]})
    r = client_admin.get(f"/api/contratos/{cid}/curva").json()
    assert r["anterior"] == [{"competencia": "2026-07", "previsto_centavos": 300_00}]
    assert r["aditivos"] == []
