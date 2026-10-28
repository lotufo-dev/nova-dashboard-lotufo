"""Rotas do monitor do SIGA (issue #327): token de servico no POST e na lista do robo, sessao na leitura da tela.

Processos e pessoas sao ficticios (repositorio publico)."""
import datetime

import pytest

from app import auth, db, tempo

TOKEN = "token-de-teste-do-siga-0123456789"
UTC = datetime.timezone.utc
NOMES_FICTICIOS = {"Fulano", "Beltrano", "Sicrana", ""}

CORPO = {
    "lido_em": "2026-10-28T11:00:00-04:00",
    "processos": [
        {"codigo": "ABC123", "numero": "sinfra-pro-2026/00001", "nome": "Processo Alfa",
         "situacao": "2º Volume - Aguardando Andamento [COFIN, [X]]",
         "movimentacoes": [
             {"data": "01/10/2026 08:10:00", "evento": "Cadastro", "cad_lotacao": "PROTOC/ORGAO",
              "cad_pessoa": "Beltrano", "at_lotacao": "PROTOC/ORGAO", "at_pessoa": "Beltrano"},
             {"data": "19/10/2026 10:00:00", "evento": "Recebimento", "cad_lotacao": "PROTOC/ORGAO",
              "cad_pessoa": "Beltrano", "at_lotacao": "COFIN/ORGAO", "at_pessoa": "Fulano"}]},
        {"codigo": None, "numero": "ORGAO-PRO-2026/00011", "nome": "Processo Beta",
         "situacao": "1º Volume - Caixa de Entrada [GABIN, [X]]",
         "movimentacoes": [
             {"data": "20/10/2026 08:00:00", "evento": "Transferência", "cad_lotacao": "PROTOC/ORGAO",
              "cad_pessoa": "Sicrana", "at_lotacao": "GABIN/ORGAO", "at_pessoa": ""}]},
    ],
}


@pytest.fixture(autouse=True)
def relogio(monkeypatch):
    """Agora = 28/10/2026, 12h em Cuiaba, logo depois da leitura dos testes."""
    monkeypatch.setattr(tempo, "agora_utc", lambda: datetime.datetime(2026, 10, 28, 16, 0, tzinfo=UTC))


@pytest.fixture
def com_token(tmp_path, monkeypatch):
    arquivo = tmp_path / "siga-token.txt"
    arquivo.write_text(TOKEN + "\n", encoding="utf-8")
    monkeypatch.setenv("DASH_SIGA_TOKEN_ARQUIVO", str(arquivo))


def _robo(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def _conta_movimentacoes():
    conn = db.get_conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM siga_movimentacoes").fetchone()[0]
    finally:
        conn.close()


def test_fixtures_so_tem_nomes_ficticios():
    pessoas = {m[k] for p in CORPO["processos"] for m in p["movimentacoes"] for k in ("cad_pessoa", "at_pessoa")}
    assert pessoas <= NOMES_FICTICIOS


def test_post_grava_e_repetir_nao_cria_nada(client, com_token):
    r = client.post("/api/siga/leituras", json=CORPO, headers=_robo())
    assert r.status_code == 200, r.text
    assert r.json() == {"gravados": 2, "novas_movimentacoes": 3}
    r = client.post("/api/siga/leituras", json=CORPO, headers=_robo())
    assert r.json() == {"gravados": 2, "novas_movimentacoes": 0}
    assert _conta_movimentacoes() == 3


@pytest.mark.parametrize("cabecalho", [{}, {"Authorization": "Bearer errado"}, {"Authorization": TOKEN},
                                       {"Authorization": "Basic " + TOKEN}])
def test_post_sem_token_ou_com_token_errado_e_401(client, com_token, cabecalho):
    r = client.post("/api/siga/leituras", json=CORPO, headers=cabecalho)
    assert r.status_code == 401
    assert r.json()["detail"] == "Token do monitor do SIGA inválido ou ausente"
    assert _conta_movimentacoes() == 0


def test_sem_a_variavel_os_endpoints_do_robo_respondem_503(client, monkeypatch):
    monkeypatch.delenv("DASH_SIGA_TOKEN_ARQUIVO", raising=False)
    for r in (client.post("/api/siga/leituras", json=CORPO, headers=_robo()),
              client.get("/api/siga/processos", headers=_robo())):
        assert r.status_code == 503 and r.json()["detail"] == "Monitor do SIGA não configurado"


def test_arquivo_do_token_ausente_ou_vazio_e_503(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_SIGA_TOKEN_ARQUIVO", str(tmp_path / "nao-existe.txt"))
    assert client.get("/api/siga/processos", headers=_robo()).status_code == 503
    vazio = tmp_path / "vazio.txt"
    vazio.write_text("  \n", encoding="utf-8")
    monkeypatch.setenv("DASH_SIGA_TOKEN_ARQUIVO", str(vazio))
    r = client.get("/api/siga/processos", headers={"Authorization": "Bearer "})
    assert r.status_code == 503


def test_post_sem_codigo_e_sem_numero_e_422_em_portugues(client, com_token):
    corpo = {"lido_em": CORPO["lido_em"], "processos": [{"codigo": None, "numero": None, "nome": "x",
                                                         "situacao": None, "movimentacoes": []}]}
    r = client.post("/api/siga/leituras", json=corpo, headers=_robo())
    assert r.status_code == 422 and r.json()["detail"] == "Processo sem o código ou o número do SIGA"


@pytest.mark.parametrize("conteudo,codificacao", [(TOKEN, "utf-8-sig"), (TOKEN + "\r\n", "utf-8-sig")])
def test_arquivo_do_token_com_bom_vale(client, tmp_path, monkeypatch, conteudo, codificacao):
    # Set-Content -Encoding UTF8 do PowerShell 5.1 grava com BOM
    arquivo = tmp_path / "siga-token.txt"
    arquivo.write_bytes(conteudo.encode(codificacao))
    monkeypatch.setenv("DASH_SIGA_TOKEN_ARQUIVO", str(arquivo))
    assert client.get("/api/siga/processos", headers=_robo()).status_code == 200


def test_arquivo_do_token_em_utf16_e_503_e_nao_500(client, tmp_path, monkeypatch):
    # o `>` do PowerShell 5.1 grava UTF-16
    arquivo = tmp_path / "siga-token.txt"
    arquivo.write_bytes(TOKEN.encode("utf-16"))
    monkeypatch.setenv("DASH_SIGA_TOKEN_ARQUIVO", str(arquivo))
    r = client.get("/api/siga/processos", headers=_robo())
    assert r.status_code == 503 and r.json()["detail"] == "Monitor do SIGA não configurado"


def test_data_da_movimentacao_com_espaco_no_fim_e_aceita(client, com_token):
    corpo = {"lido_em": CORPO["lido_em"], "processos": [{**CORPO["processos"][0], "movimentacoes": [
        {**CORPO["processos"][0]["movimentacoes"][0], "data": "01/10/2026 08:10:00 "}]}]}
    r = client.post("/api/siga/leituras", json=corpo, headers=_robo())
    assert r.status_code == 200, r.text
    assert r.json()["novas_movimentacoes"] == 1


def test_post_sem_fuso_no_lido_em_e_422(client, com_token):
    r = client.post("/api/siga/leituras", json={**CORPO, "lido_em": "2026-10-28T11:00:00"}, headers=_robo())
    assert r.status_code == 422


def test_post_com_leitura_no_futuro_e_422(client, com_token):
    r = client.post("/api/siga/leituras", json={**CORPO, "lido_em": "2026-10-28T13:00:00-04:00"}, headers=_robo())
    assert r.status_code == 422 and "no futuro" in r.json()["detail"]


def test_get_processos_com_token_devolve_os_recebidos(client, com_token):
    client.post("/api/siga/leituras", json=CORPO, headers=_robo())
    r = client.get("/api/siga/processos", headers=_robo())
    assert r.status_code == 200
    assert r.json() == [{"codigo": "ABC123", "numero": "sinfra-pro-2026/00001", "nome": "Processo Alfa"},
                        {"codigo": None, "numero": "ORGAO-PRO-2026/00011", "nome": "Processo Beta"}]
    assert client.get("/api/siga/processos", headers=_robo("errado")).status_code == 401


def test_rotas_do_robo_nao_aceitam_a_sessao(client_admin, com_token):
    assert client_admin.get("/api/siga/processos").status_code == 401
    assert client_admin.post("/api/siga/leituras", json=CORPO).status_code == 401


def test_get_siga_sem_sessao_e_401(client):
    assert client.get("/api/siga").status_code == 401


def test_get_siga_logado_traz_derivacoes_e_vinculo(client_admin, com_token, monkeypatch):
    conn = db.get_conn()
    uid = auth.criar_usuario(conn, "Engenharia", "engenharia@exemplo.com.br", "senha-forte-123", "engenharia")
    conn.execute("INSERT INTO contratos (id, orgao, numero_instrumento, objeto, valor_original_centavos, nome_curto) "
                 "VALUES (7, 'SINFRA', 'IC 1/2026', 'Obra', 100, 'Obra Alfa')")
    conn.execute("INSERT INTO medicoes (id, contrato_id, numero, tipo, competencia, estado) "
                 "VALUES (31, 7, 3, 'execucao', '2026-09', 'protocolada')")
    pid = conn.execute("INSERT INTO protocolos (contrato_id, etapa, natureza, usuario_id, situacao, numero_orgao) "
                       "VALUES (7, 'unico', 'execucao', ?, 'enviado', 'SINFRA-PRO-2026/00001')", (uid,)).lastrowid
    conn.execute("INSERT INTO protocolo_medicoes (protocolo_id, medicao_id) VALUES (?, 31)", (pid,))
    conn.commit(); conn.close()
    assert client_admin.post("/api/siga/leituras", json=CORPO, headers=_robo()).status_code == 200
    # quarta-feira, 28/10/2026, 11h10 em Cuiaba
    monkeypatch.setattr(tempo, "agora_utc", lambda: datetime.datetime(2026, 10, 28, 15, 10, tzinfo=UTC))
    r = client_admin.get("/api/siga")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["lido_em"] == "2026-10-28T15:00:00+00:00" and corpo["atrasado"] is False
    alfa, beta = corpo["processos"]
    assert (alfa["setor"], alfa["com_quem"], alfa["dias_uteis"], alfa["caixa_entrada"]) == ("COFIN", "Fulano", 7,
                                                                                            False)
    assert (alfa["medicao_id"], alfa["protocolo_id"], alfa["contrato_id"]) == (31, pid, 7)
    assert alfa["medicao_titulo"] == "3ª Medição" and alfa["obra"] == "Obra Alfa"
    assert alfa["movimentacoes"][0]["data"] == "2026-10-19T10:00:00-04:00"
    assert alfa["desde"] == "2026-10-19T10:00:00-04:00"
    assert beta["medicao_id"] is None and beta["caixa_entrada"] is True
