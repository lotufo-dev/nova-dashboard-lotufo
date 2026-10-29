"""Rotas do monitor do SIGA (issue #327): token de servico no POST e na lista do robo, sessao na leitura da tela.

Processos e pessoas sao ficticios (repositorio publico)."""
import datetime
import subprocess
from types import SimpleNamespace

import pytest

from app import auth, db, siga, tempo
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


def test_processo_ja_ligado_a_medicao_nao_e_reescrito_pela_tela_siga(api, com_token):
    # o robo mandou so' o numero igual ao "Nº do protocolo no órgão": a linha ficou ligada ao protocolo e a' medicao
    cl, cid, mid = api
    pid = _enviado(cl, cid, mid)
    assert cl.post(f"/api/protocolos/{pid}/numero-orgao", data={"numero": "MTPAR-PRO-2026/00001"}).status_code == 200
    cl.post("/api/siga/leituras", json={"lido_em": CORPO["lido_em"], "processos": [
        {"codigo": None, "numero": "MTPAR-PRO-2026/00001", "nome": "Nome do robô", "situacao": None,
         "movimentacoes": []}]}, headers=_robo())
    (p,) = cl.get("/api/siga").json()["processos"]
    assert (p["protocolo_id"], p["medicao_id"]) == (pid, mid)
    r = cl.post("/api/siga/processos-avulsos", json={"link": LINK_SIGA, "nome": "Aditivo de prazo",
                                                     "numero": "MTPAR-PRO-2026/00001"})
    assert r.status_code == 422
    assert r.json()["detail"] == "Este processo do SIGA já está ligado a outro protocolo ou a outra medição"
    assert cl.get("/api/siga/processos", headers=_robo()).json() == [
        {"codigo": None, "numero": "MTPAR-PRO-2026/00001", "nome": "Nome do robô"}]


def test_contrato_id_fora_do_inteiro_e_422_e_nao_500(api, com_token):
    cl, _cid, _mid = api
    r = cl.post("/api/siga/processos-avulsos", json={"link": LINK_SIGA, "nome": "X", "contrato_id": 2 ** 70})
    assert r.status_code == 422


def test_diretoria_nao_cola_link_na_tela_siga(api, com_token):
    cl, _cid, _mid = api
    _diretoria(cl)
    assert cl.get("/api/siga").status_code == 200
    r = cl.post("/api/siga/processos-avulsos", json={"link": LINK_SIGA, "nome": "X"})
    assert r.status_code == 403
    assert cl.get("/api/siga/processos", headers=_robo()).json() == []


# --- botao de atualizar e rodadas do robo (issue #342) -----------------------------------------------------

TAREFA = "Robo SIGA de teste"
SEM_INICIO = "O robô não começou. O usuário dele pode estar desconectado do servidor."


@pytest.fixture
def schtasks(monkeypatch):
    """`DASH_SIGA_TAREFA` definida e o `schtasks` trocado por um duble: sucesso, erro ou prazo estourado."""
    monkeypatch.setenv("DASH_SIGA_TAREFA", TAREFA)
    chamadas, resposta = [], {"codigo": 0, "saida": b"", "erro": b"", "estoura": False}

    def run(args, **kw):
        chamadas.append((args, kw))
        if resposta["estoura"]:
            raise subprocess.TimeoutExpired(args, kw.get("timeout"))
        return subprocess.CompletedProcess(args, resposta["codigo"], resposta["saida"], resposta["erro"])

    monkeypatch.setattr(siga.subprocess, "run", run)
    return SimpleNamespace(chamadas=chamadas, resposta=resposta)


@pytest.fixture
def relogio_movel(monkeypatch):
    """Comeca as 12h de Cuiaba de 28/10/2026 (16h UTC) e anda quando o teste manda."""
    agora = [datetime.datetime(2026, 10, 28, 16, 0, tzinfo=UTC)]
    monkeypatch.setattr(tempo, "agora_utc", lambda: agora[0])

    def andar(minutos, segundos=0):
        agora[0] += datetime.timedelta(minutes=minutos, seconds=segundos)
    return andar


def _com_processos(cl):
    """Os dois processos do CORPO (Alfa e Beta), recebidos pelo robo. -> os ids."""
    assert cl.post("/api/siga/leituras", json=CORPO, headers=_robo()).status_code == 200
    return [p["id"] for p in cl.get("/api/siga").json()["processos"]]


def _robo_painel(cl):
    return cl.get("/api/siga").json()["robo"]


def _rodada(cl):
    r = cl.post("/api/siga/rodadas", headers=_robo())
    assert r.status_code == 200, r.text
    return r.json()


def _fim(cl, rodada_id, nao_lidos=()):
    return cl.post(f"/api/siga/rodadas/{rodada_id}/fim", json={"nao_lidos": list(nao_lidos)}, headers=_robo())


def _conta_rodadas():
    conn = db.get_conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM siga_rodadas").fetchone()[0]
    finally:
        conn.close()


def test_atualizar_processo_grava_o_pedido_roda_o_schtasks_e_o_painel_mostra_na_fila(client_admin, com_token,
                                                                                    schtasks):
    alfa, _beta = _com_processos(client_admin)
    r = client_admin.post("/api/siga/atualizar", json={"processo_id": alfa})
    assert r.status_code == 200, r.text
    pedido = r.json()
    assert (pedido["processo_id"], pedido["novo"], pedido["disparado"], pedido["erro_disparo"]) == (alfa, True, True,
                                                                                                   None)
    ((args, kw),) = schtasks.chamadas
    assert args[1:] == ["/Run", "/TN", TAREFA] and kw["timeout"] == 15 and not kw.get("shell")
    painel = client_admin.get("/api/siga").json()
    assert painel["pode_atualizar"] is True
    assert painel["robo"]["estado"] == "na_fila" and painel["robo"]["rodada"] is None
    assert painel["robo"]["pedidos"] == [{"id": pedido["id"], "processo_id": alfa, "usuario": "Admin",
                                          "pedido_em": "2026-10-28T16:00:00+00:00"}]


def test_atualizar_todos_e_segundo_clique_igual_devolve_o_mesmo_pedido(client_admin, com_token, schtasks):
    _com_processos(client_admin)
    um = client_admin.post("/api/siga/atualizar", json={}).json()
    dois = client_admin.post("/api/siga/atualizar", json={}).json()
    assert um["processo_id"] is None and um["novo"] is True
    assert dois["id"] == um["id"] and dois["novo"] is False
    assert [p["processo_id"] for p in _robo_painel(client_admin)["pedidos"]] == [None]


def test_atualizar_processo_que_nao_existe_e_422(client_admin, com_token, schtasks):
    r = client_admin.post("/api/siga/atualizar", json={"processo_id": 999})
    assert r.status_code == 422 and r.json()["detail"] == "Processo do SIGA não encontrado"
    assert client_admin.post("/api/siga/atualizar", json={"processo_id": 2 ** 70}).status_code == 422
    assert schtasks.chamadas == []


def test_com_rodada_em_andamento_o_clique_grava_o_pedido_e_nao_roda_o_schtasks(client_admin, com_token, schtasks):
    alfa, _beta = _com_processos(client_admin)
    assert _rodada(client_admin)["tipo"] == "automatica"
    r = client_admin.post("/api/siga/atualizar", json={"processo_id": alfa}).json()
    assert (r["disparado"], r["erro_disparo"]) == (False, None) and schtasks.chamadas == []
    robo = _robo_painel(client_admin)
    assert robo["estado"] == "lendo" and [p["id"] for p in robo["pedidos"]] == [r["id"]]
    assert robo["rodada"]["tipo"] == "automatica" and robo["rodada"]["processos"] == [alfa, _beta]


@pytest.mark.parametrize("resposta,motivo", [
    ({"codigo": 1, "erro": "ERRO: acesso negado.\r\n".encode()}, "ERRO: acesso negado."),
    ({"estoura": True}, "sem resposta em 15 segundos"),
])
def test_windows_recusou_traz_erro_disparo_e_o_aviso_no_painel(client_admin, com_token, schtasks, resposta, motivo):
    alfa, _beta = _com_processos(client_admin)
    schtasks.resposta.update(resposta)
    r = client_admin.post("/api/siga/atualizar", json={"processo_id": alfa})
    assert r.status_code == 200, r.text
    assert (r.json()["disparado"], r.json()["erro_disparo"]) == (False, motivo)
    assert {"tipo": "disparo", "processo_id": None,
            "texto": f"O Windows não iniciou o robô: {motivo}"} in _robo_painel(client_admin)["avisos"]


def test_sem_a_tarefa_o_clique_e_503_e_o_painel_nao_pode_atualizar(client_admin, com_token, schtasks, monkeypatch):
    monkeypatch.delenv("DASH_SIGA_TAREFA")
    alfa, _beta = _com_processos(client_admin)
    r = client_admin.post("/api/siga/atualizar", json={"processo_id": alfa})
    assert r.status_code == 503 and r.json()["detail"] == "Atualizar pelo SIGA não está disponível neste servidor"
    painel = client_admin.get("/api/siga").json()
    assert painel["pode_atualizar"] is False and painel["robo"]["pedidos"] == [] and schtasks.chamadas == []


def test_rodadas_escolhe_o_que_ler(client_admin, com_token, schtasks, relogio_movel):
    _alfa, beta = _com_processos(client_admin)
    r = _rodada(client_admin)                      # nunca houve rodada completa: todos, automatica
    assert r["tipo"] == "automatica" and [p["nome"] for p in r["processos"]] == ["Processo Alfa", "Processo Beta"]
    assert _fim(client_admin, r["rodada_id"]).json() == {"rodada_id": r["rodada_id"]}
    relogio_movel(2)
    assert _rodada(client_admin) == {"rodada_id": None, "tipo": None, "processos": []}    # nada a ler
    assert _conta_rodadas() == 1
    client_admin.post("/api/siga/atualizar", json={"processo_id": beta})
    r = _rodada(client_admin)                      # pedido de um processo: so' ele
    assert r["tipo"] == "pedido" and r["processos"] == [
        {"codigo": None, "numero": "ORGAO-PRO-2026/00011", "nome": "Processo Beta"}]
    _fim(client_admin, r["rodada_id"])
    relogio_movel(1)
    client_admin.post("/api/siga/atualizar", json={})
    r = _rodada(client_admin)                      # pedido "todos": todos, do tipo pedido
    assert r["tipo"] == "pedido" and len(r["processos"]) == 2
    _fim(client_admin, r["rodada_id"])
    relogio_movel(13, 59)
    assert _rodada(client_admin)["rodada_id"] is None
    relogio_movel(0, 1)                            # 14 minutos depois da ultima completa: todos, automatica
    r = _rodada(client_admin)
    assert r["tipo"] == "automatica" and len(r["processos"]) == 2


def test_comecei_repetido_devolve_a_rodada_aberta_sem_gravar_outra(client_admin, com_token, schtasks):
    _com_processos(client_admin)
    um = _rodada(client_admin)
    assert _rodada(client_admin) == um and _conta_rodadas() == 1


def test_fim_com_nao_lidos_e_falha_aparecem_no_painel(client_admin, com_token, schtasks, relogio_movel):
    alfa, beta = _com_processos(client_admin)
    r = _rodada(client_admin)
    assert _fim(client_admin, r["rodada_id"], [{"codigo": None, "numero": "ORGAO-PRO-2026/00011",
                                                 "motivo": "Processo sem código"}]).status_code == 200
    assert _robo_painel(client_admin)["avisos"] == [
        {"tipo": "nao_lido", "processo_id": beta, "texto": "não lido às 12:00: Processo sem código"},
        {"tipo": "nao_lidos", "processo_id": None, "texto": "1 de 2 processos não foram lidos"}]
    relogio_movel(1)
    client_admin.post("/api/siga/atualizar", json={"processo_id": alfa})
    r = _rodada(client_admin)
    f = client_admin.post(f"/api/siga/rodadas/{r['rodada_id']}/falha", json={"motivo": "O SIGA não abriu"},
                          headers=_robo())
    assert f.status_code == 200, f.text
    assert _robo_painel(client_admin)["avisos"] == [
        {"tipo": "falha", "processo_id": None, "texto": "A rodada das 12:01 falhou: O SIGA não abriu"}]


def test_rodada_sem_fim_e_pedido_parado_avisam_no_painel(client_admin, com_token, schtasks, relogio_movel):
    alfa, _beta = _com_processos(client_admin)
    _rodada(client_admin)
    relogio_movel(12, 1)
    robo = _robo_painel(client_admin)
    assert robo["estado"] == "parado" and [a["texto"] for a in robo["avisos"]] == ["A rodada das 12:00 não terminou."]
    # a rodada morta nao segura o clique: o servidor dispara de novo
    client_admin.post("/api/siga/atualizar", json={"processo_id": alfa})
    assert len(schtasks.chamadas) == 1
    relogio_movel(2, 1)
    assert [a["texto"] for a in _robo_painel(client_admin)["avisos"]] == [SEM_INICIO,
                                                                         "A rodada das 12:00 não terminou."]


def test_fim_ou_falha_de_rodada_terminada_e_409_e_de_rodada_que_nao_existe_e_404(client_admin, com_token, schtasks):
    _com_processos(client_admin)
    rid = _rodada(client_admin)["rodada_id"]
    assert _fim(client_admin, rid).status_code == 200
    for r in (_fim(client_admin, rid),
              client_admin.post(f"/api/siga/rodadas/{rid}/falha", json={"motivo": "caiu"}, headers=_robo())):
        assert r.status_code == 409 and r.json()["detail"] == "Esta rodada do SIGA já terminou"
    assert _fim(client_admin, 999).status_code == 404
    assert _fim(client_admin, 2 ** 70).status_code == 404


def test_rotas_do_robo_recusam_sem_token(client_admin, com_token, schtasks):
    _com_processos(client_admin)
    rotas = (("/api/siga/rodadas", None), ("/api/siga/rodadas/1/fim", {"nao_lidos": []}),
             ("/api/siga/rodadas/1/falha", {"motivo": "caiu"}))
    for caminho, corpo in rotas:
        for cabecalho in ({}, {"Authorization": "Bearer errado"}):    # a sessao do admin tambem nao vale
            assert client_admin.post(caminho, json=corpo, headers=cabecalho).status_code == 401
    assert _conta_rodadas() == 0


def test_atualizar_recusa_sem_login_e_aceita_a_diretoria(api, com_token, schtasks):
    cl, _cid, _mid = api
    alfa, _beta = _com_processos(cl)
    cl.cookies.clear()
    assert cl.post("/api/siga/atualizar", json={"processo_id": alfa}).status_code == 401
    _diretoria(cl)
    r = cl.post("/api/siga/atualizar", json={"processo_id": alfa})
    assert r.status_code == 200, r.text
    assert _robo_painel(cl)["pedidos"][0]["usuario"] == "Diretoria"
    del cl.headers["X-CSRF-Token"]
    assert cl.post("/api/siga/atualizar", json={}).status_code == 403
