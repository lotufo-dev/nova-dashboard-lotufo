from tests.conftest import novo_contrato


def _contrato():
    return novo_contrato({
        "orgao": "SINFRA", "numero_instrumento": "IC 1/2026", "objeto": "Obra",
        "valor_original": "1.000.000,00", "vigencia_fim": "2026-12-31"})


def _aditivo(cid):
    from app import aditivos, db
    conn = db.get_conn()
    try:
        return aditivos.criar(conn, None, cid, {"tipo": "misto", "numero": "1º TA", "objeto": "Drenagem",
                                                "delta_valor_centavos": 250_000_00,
                                                "nova_vigencia_fim": "2027-06-30"})
    finally:
        conn.close()


def test_lista_de_aditivos(client_admin):
    cid = _contrato()
    aid = _aditivo(cid)
    assert client_admin.get(f"/api/contratos/{cid}/aditivos").json()[0]["status"] == "em_andamento"
    assert client_admin.get(f"/api/aditivos/{aid}/conferencia").status_code == 404


def test_escrita_de_aditivo_pela_api_saiu(client_admin):
    """Bloco 9: aditivo entra pelo cadastro versionado; rascunho, assinatura, cancelamento e leitura do
    termo em PDF sairam da API."""
    cid = _contrato()
    aid = _aditivo(cid)
    assert client_admin.post(f"/api/contratos/{cid}/aditivos", json={"tipo": "valor"}).status_code == 405
    assert client_admin.put(f"/api/aditivos/{aid}", json={"tipo": "valor"}).status_code == 404
    for acao in ("assinar", "cancelar"):
        assert client_admin.post(f"/api/aditivos/{aid}/{acao}", json={}).status_code == 404
    assert client_admin.post(f"/api/contratos/{cid}/aditivos/ler-pdf").status_code == 404
