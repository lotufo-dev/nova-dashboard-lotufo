"""Rotas do monitor do SIGA (issue #327): token de servico no POST e na lista do robo, sessao na leitura da tela.

Processos e pessoas sao ficticios (repositorio publico)."""
import datetime

import pytest

from app import auth, db, tempo
from tests.test_api_protocolos import LINK_SIGA, _enviado, api  # noqa: F401  (a fixture `api` vem de la')

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


def test_link_gravado_na_etapa_4_aparece_na_lista_do_robo(api, com_token):
    # issue #328: o robo passa a acompanhar o processo sem ninguem editar arquivo no servidor
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    assert cl.get("/api/siga/processos", headers=_robo()).json() == []
    r = cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "MTPAR-PRO-2026/00001", "link_siga": LINK_SIGA})
    assert r.status_code == 200, r.text
    assert cl.get("/api/siga/processos", headers=_robo()).json() == [
        {"codigo": "AbCdEf1234", "numero": "MTPAR-PRO-2026/00001", "nome": "23ª Medição - Obra MTPAR"}]
    # a leitura seguinte do robo cai no mesmo processo (mesmo codigo) e o painel o mostra ligado ao protocolo e a' medicao
    cl.post("/api/siga/leituras", json={"lido_em": CORPO["lido_em"], "processos": [
        {"codigo": "AbCdEf1234", "numero": None, "nome": "Alfa", "situacao": None, "movimentacoes": []}]}, headers=_robo())
    alfa = cl.get("/api/siga").json()["processos"][0]
    assert (alfa["protocolo_id"], alfa["medicao_id"], alfa["nome"]) == (pid, mid, "23ª Medição - Obra MTPAR")


def test_get_siga_traz_o_link_so_com_codigo_e_modelo_configurado(client_admin, com_token, monkeypatch):
    assert client_admin.post("/api/siga/leituras", json=CORPO, headers=_robo()).status_code == 200
    monkeypatch.delenv("DASH_SIGA_LINK_MODELO", raising=False)
    sem_modelo = client_admin.get("/api/siga").json()["processos"]
    assert [p["link"] for p in sem_modelo] == [None, None]
    monkeypatch.setenv("DASH_SIGA_LINK_MODELO", "https://siga.exemplo.com.br/acompanhar?n={codigo}")
    alfa, beta = client_admin.get("/api/siga").json()["processos"]
    assert alfa["link"] == "https://siga.exemplo.com.br/acompanhar?n=ABC123"
    assert beta["link"] is None   # sem codigo, sem link
    # modelo fora de https ou sem o {codigo} nao vira link
    monkeypatch.setenv("DASH_SIGA_LINK_MODELO", "http://siga.exemplo.com.br/acompanhar?n={codigo}")
    assert client_admin.get("/api/siga").json()["processos"][0]["link"] is None
    monkeypatch.setenv("DASH_SIGA_LINK_MODELO", "https://siga.exemplo.com.br/acompanhar")
    assert client_admin.get("/api/siga").json()["processos"][0]["link"] is None


# --- link colado na tela SIGA (issue #339) -----------------------------------------------------------------

def _diretoria(cl):
    conn = db.get_conn()
    auth.criar_usuario(conn, "Diretoria", "diretoria@exemplo.com.br", "senha-forte-123", "diretoria")
    conn.commit(); conn.close()
    cl.cookies.clear()
    r = cl.post("/api/auth/login", json={"email": "diretoria@exemplo.com.br", "senha": "senha-forte-123"})
    assert r.status_code == 200, r.text
    cl.cookies.set("sessao", r.cookies.get("sessao") or cl.cookies.get("sessao"))
    cl.headers["X-CSRF-Token"] = r.json()["csrf"]


def test_colar_link_na_tela_siga_grava_com_obra_e_aparece_para_o_robo_e_na_tela(api, com_token):
    cl, cid, _mid = api
    r = cl.post("/api/siga/processos-avulsos", json={"link": LINK_SIGA, "nome": "Aditivo de prazo", "contrato_id": cid,
                                                     "numero": "MTPAR-PRO-2026/ 00009"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert cl.get("/api/siga/processos", headers=_robo()).json() == [
        {"codigo": "AbCdEf1234", "numero": "MTPAR-PRO-2026/00009", "nome": "Aditivo de prazo"}]
    (p,) = cl.get("/api/siga").json()["processos"]
    assert (p["id"], p["nome"], p["contrato_id"], p["obra"], p["medicao_id"]) == (pid, "Aditivo de prazo", cid, "Obra MTPAR", None)
    assert p["link"] == LINK_SIGA and p["situacao"] is None and p["movimentacoes"] == []
    c = db.get_conn()
    reg = c.execute("SELECT entidade, entidade_id, depois FROM audit_log WHERE acao='protocolo.siga' "
                    "ORDER BY id DESC LIMIT 1").fetchone()
    c.close()
    assert (reg["entidade"], int(reg["entidade_id"])) == ("siga_processo", pid)
    assert "AbCdEf1234" in reg["depois"]


def test_colar_so_o_codigo_sem_obra_vale(api, com_token):
    cl, _cid, _mid = api
    r = cl.post("/api/siga/processos-avulsos", json={"link": "AbCdEf1234", "nome": "Indenizatório"})
    assert r.status_code == 200, r.text
    (p,) = cl.get("/api/siga").json()["processos"]
    assert (p["codigo"], p["nome"], p["contrato_id"], p["obra"], p["numero"]) == ("AbCdEf1234", "Indenizatório", None,
                                                                                  None, None)


@pytest.mark.parametrize("corpo,detalhe", [
    ({"link": LINK_SIGA, "nome": "  "}, "Dê um nome ao processo"),
    ({"link": "https://siga.exemplo.com.br.evil.example/acompanhar?n=AbCdEf1234", "nome": "X"},
     "Link do SIGA inválido: cole o link que o órgão mandou"),
    ({"link": "", "nome": "X"}, "Link do SIGA inválido: cole o link que o órgão mandou"),
    ({"link": LINK_SIGA, "nome": "X", "contrato_id": 9999}, "Obra não encontrada"),
])
def test_nome_vazio_link_estranho_ou_obra_inexistente_e_422_e_nada_grava(api, com_token, corpo, detalhe):
    cl, _cid, _mid = api
    r = cl.post("/api/siga/processos-avulsos", json=corpo)
    assert r.status_code == 422 and r.json()["detail"] == detalhe
    assert cl.get("/api/siga/processos", headers=_robo()).json() == []


def test_codigo_ja_acompanhado_e_409_com_o_nome_existente(api, com_token):
    cl, _cid, _mid = api
    assert cl.post("/api/siga/processos-avulsos", json={"link": LINK_SIGA, "nome": "Aditivo de prazo"}).status_code == 200
    r = cl.post("/api/siga/processos-avulsos", json={"link": "AbCdEf1234", "nome": "Outro nome"})
    assert r.status_code == 409
    assert r.json()["detail"] == "Este processo do SIGA já está sendo acompanhado: Aditivo de prazo"
    assert [p["nome"] for p in cl.get("/api/siga/processos", headers=_robo()).json()] == ["Aditivo de prazo"]


def test_processo_que_o_robo_mandou_so_pelo_numero_ganha_codigo_nome_e_obra(api, com_token):
    cl, cid, _mid = api
    cl.post("/api/siga/leituras", json={"lido_em": CORPO["lido_em"], "processos": [
        {"codigo": None, "numero": "MTPAR-PRO-2026/00009", "nome": "Nome do robô", "situacao": None,
         "movimentacoes": []}]}, headers=_robo())
    r = cl.post("/api/siga/processos-avulsos", json={"link": LINK_SIGA, "nome": "Aditivo de prazo", "contrato_id": cid,
                                                     "numero": "MTPAR-PRO-2026/00009"})
    assert r.status_code == 200, r.text
    assert cl.get("/api/siga/processos", headers=_robo()).json() == [
        {"codigo": "AbCdEf1234", "numero": "MTPAR-PRO-2026/00009", "nome": "Aditivo de prazo"}]
    assert cl.get("/api/siga").json()["processos"][0]["contrato_id"] == cid


def test_diretoria_nao_cola_link_na_tela_siga(api, com_token):
    cl, _cid, _mid = api
    _diretoria(cl)
    assert cl.get("/api/siga").status_code == 200
    r = cl.post("/api/siga/processos-avulsos", json={"link": LINK_SIGA, "nome": "X"})
    assert r.status_code == 403
    assert cl.get("/api/siga/processos", headers=_robo()).json() == []
