import threading

import pytest
from app import api_correio, graph

_THREAD = threading.Thread          # a fixture troca threading.Thread pela parada; o teste do clique duplo usa a real


class _ThreadParada:
    """No lugar de threading.Thread: o acompanhamento do login nao roda no teste (ele dormiria
    5 s e acordaria DEPOIS do teste, ja' sem o monkeypatch, batendo na rede de verdade)."""
    def __init__(self, **_):
        pass

    def start(self):
        pass


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_TOKENS_DIR", str(tmp_path / "tokens"))
    monkeypatch.setenv("DASH_GRAPH_CLIENT_ID", "cliente-teste")
    monkeypatch.setattr(api_correio.threading, "Thread", _ThreadParada)
    api_correio._LOGINS.clear()          # estado de login e' global do processo: zera entre testes
    api_correio._CODIGO.clear()
    yield
    api_correio._LOGINS.clear()
    api_correio._CODIGO.clear()


def test_status_de_quem_nunca_conectou(client_admin):
    r = client_admin.get("/api/correio/status").json()
    assert r["configurado"] is True and r["conectado"] is False and r["login"]["estado"] == "nenhum"


def test_conectar_devolve_o_codigo_so_para_quem_pediu(client_admin, monkeypatch):
    monkeypatch.setattr(graph, "iniciar_device_code", lambda tenant, cid, escopos: {
        "device_code": "d", "user_code": "ABCD-1234", "verification_uri": "https://microsoft.com/devicelogin",
        "expires_in": 900, "interval": 5, "message": ""})
    r = client_admin.post("/api/correio/conectar").json()
    assert r["login"]["user_code"] == "ABCD-1234" and r["login"]["estado"] == "aguardando"


def test_conectar_de_novo_enquanto_aguarda_devolve_o_mesmo_codigo_sem_travar(client_admin, monkeypatch):
    # 14/10/2026: o segundo clique pegava a trava dentro da propria trava e o servidor parava de responder
    # o estado da conta para todo mundo, ate' reiniciar.
    pedidos = []
    monkeypatch.setattr(graph, "iniciar_device_code", lambda tenant, cid, escopos: pedidos.append(1) or {
        "device_code": "d", "user_code": "ABCD-1234", "verification_uri": "https://microsoft.com/devicelogin",
        "expires_in": 900, "interval": 5, "message": ""})
    client_admin.post("/api/correio/conectar")
    resposta = {}
    t = _THREAD(target=lambda: resposta.update(r=client_admin.post("/api/correio/conectar")), daemon=True)
    t.start()
    t.join(5)
    if t.is_alive():
        api_correio._LOCK.release()      # solta a trava presa para nao pendurar os outros testes
        pytest.fail("o segundo clique em Conectar travou o servidor")
    assert resposta["r"].status_code == 200 and resposta["r"].json()["login"]["user_code"] == "ABCD-1234"
    assert len(pedidos) == 1                                     # nao pede outro codigo a' Microsoft
    assert client_admin.get("/api/correio/status").json()["login"]["estado"] == "aguardando"


def test_teste_envia_para_a_propria_pessoa_e_registra(client_admin, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    r = client_admin.post("/api/correio/teste")
    assert r.status_code == 200, r.text
    assert r.json()["remetente"] == "admin@lotufo.com"
    assert sorted((tmp_path / "sim" / "enviados").glob("*.json"))[0].exists()


def test_teste_sem_conta_conectada_explica_o_que_fazer(client_admin):
    r = client_admin.post("/api/correio/teste")
    assert r.status_code == 422 and "Minha conta" in r.json()["detail"]


def test_diretoria_le_o_status_mas_nao_conecta(client):
    """B-09 (10/10/2026): /conta da diretoria lia "Permissao necessaria: editar_cadastros"; o status so' exige
    ver_paineis, as acoes seguem com editar_cadastros."""
    from app import auth, db
    conn = db.get_conn()
    auth.criar_usuario(conn, "Diretor", "dir@lotufo.com", "senha-forte-123", "diretoria")
    conn.close()
    r = client.post("/api/auth/login", json={"email": "dir@lotufo.com", "senha": "senha-forte-123"})
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))
    client.headers["X-CSRF-Token"] = r.json()["csrf"]
    assert client.get("/api/correio/status").status_code == 200
    assert client.post("/api/correio/conectar").status_code == 403
    assert client.post("/api/correio/teste").status_code == 403


def test_assinatura_png_cortada_ao_meio_da_422_em_portugues(client_admin):
    """#33: o cabecalho PNG sozinho nao basta; arquivo truncado e' recusado e nada e' gravado."""
    from tests.conftest import _png
    png = _png()
    r = client_admin.post("/api/correio/assinatura", files={"arquivo": ("a.png", png[: len(png) // 2], "image/png")})
    assert r.status_code == 422 and "incompleta ou corrompida" in r.json()["detail"]
    assert client_admin.get("/api/correio/status").json()["assinatura"] is False
    r = client_admin.post("/api/correio/assinatura", files={"arquivo": ("a.png", png, "image/png")})
    assert r.status_code == 200 and r.json()["assinatura"] is True


def test_tirar_assinatura_ocupada_pelo_backup_da_422_em_portugues(client_admin, monkeypatch):
    """#479: o backup lendo a assinatura no Windows (PermissionError no unlink) nao vira 500 em ingles."""
    from pathlib import Path

    from app import correio
    from tests.conftest import _png
    assert client_admin.post("/api/correio/assinatura",
                             files={"arquivo": ("a.png", _png(), "image/png")}).status_code == 200
    monkeypatch.setattr(correio.time, "sleep", lambda s: None)
    real = Path.unlink

    def ocupado(self, missing_ok=False):
        if self.name.startswith("usuario-"):
            raise PermissionError("arquivo aberto por outro processo")
        real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", ocupado)
    r = client_admin.delete("/api/correio/assinatura")
    assert r.status_code == 422 and r.json()["detail"] == "Não foi possível tirar a assinatura agora; tente de novo"
    monkeypatch.setattr(Path, "unlink", real)
    assert client_admin.get("/api/correio/status").json()["assinatura"] is True


def test_dois_cliques_simultaneos_pedem_um_codigo_so(client_admin, monkeypatch):
    pedidos, liberar = [], threading.Event()

    def devagar(tenant, cid, escopos):
        pedidos.append(1)
        liberar.wait(5)
        return {"device_code": "d", "user_code": "ABCD-1234", "verification_uri": "https://microsoft.com/devicelogin",
                "expires_in": 900, "interval": 5, "message": ""}
    monkeypatch.setattr(graph, "iniciar_device_code", devagar)
    respostas = []
    ts = [_THREAD(target=lambda: respostas.append(client_admin.post("/api/correio/conectar")), daemon=True)
          for _ in range(2)]
    for t in ts:
        t.start()
    for _ in range(50):                  # o segundo responde logo, com o "aguardando" reservado pelo primeiro
        if respostas:
            break
        api_correio.time.sleep(0.1)
    # Contrato: enquanto o primeiro espera a Microsoft, o segundo recebe "aguardando" SEM codigo (a tela nao mostra
    # codigo nenhum e consulta de novo a cada 5 s); quando o primeiro termina, o codigo e' o mesmo para os dois.
    assert len(respostas) == 1 and respostas[0].json()["login"] == {
        "estado": "aguardando", "user_code": None, "verification_uri": None}
    liberar.set()
    for t in ts:
        t.join(5)
    assert len(pedidos) == 1 and len(respostas) == 2 and all(r.status_code == 200 for r in respostas)
    assert respostas[1].json()["login"]["user_code"] == "ABCD-1234"
    assert client_admin.get("/api/correio/status").json()["login"]["user_code"] == "ABCD-1234"


def test_falha_da_microsoft_ao_pedir_codigo_desfaz_a_reserva(client_admin, monkeypatch):
    def fora_do_ar(*a):
        raise graph.ErroGraph("Microsoft fora do ar")
    monkeypatch.setattr(graph, "iniciar_device_code", fora_do_ar)
    assert client_admin.post("/api/correio/conectar").status_code == 502
    assert client_admin.get("/api/correio/status").json()["login"]["estado"] == "nenhum"


def test_resposta_incompleta_ou_thread_que_nao_sobe_desfaz_a_reserva(client_admin, monkeypatch):
    monkeypatch.setattr(graph, "iniciar_device_code", lambda tenant, cid, escopos: {"user_code": "X"})
    r = client_admin.post("/api/correio/conectar")
    assert r.status_code == 502 and r.json()["detail"] == "Não foi possível pedir o código à Microsoft; tente de novo"
    assert client_admin.get("/api/correio/status").json()["login"]["estado"] == "nenhum"

    class _ThreadQueFalha(_ThreadParada):
        def start(self):
            raise RuntimeError("can't start new thread")
    monkeypatch.setattr(api_correio.threading, "Thread", _ThreadQueFalha)
    monkeypatch.setattr(graph, "iniciar_device_code", lambda tenant, cid, escopos: {
        "device_code": "d", "user_code": "ABCD-1234", "verification_uri": "u", "expires_in": 900, "interval": 5})
    assert client_admin.post("/api/correio/conectar").status_code == 502
    assert client_admin.get("/api/correio/status").json()["login"]["estado"] == "nenhum"
    assert not api_correio._CODIGO


def test_acompanhamento_de_codigo_velho_nao_apaga_o_conectado_do_novo(monkeypatch):
    monkeypatch.setattr(api_correio.time, "sleep", lambda s: None)
    monkeypatch.setattr(graph, "concluir_device_code", lambda tenant, cid, codigo, arquivo:
                        "ok" if codigo == "novo" else "pendente")
    api_correio._CODIGO[7] = "novo"
    cfg = {"tenant": "t", "client_id": "c"}
    api_correio._acompanhar(7, cfg, "novo", 0, api_correio.time.time() + 60)
    assert api_correio._LOGINS[7]["estado"] == "ok"
    api_correio._acompanhar(7, cfg, "velho", 0, api_correio.time.time() - 1)     # o velho expira depois
    assert api_correio._LOGINS[7]["estado"] == "ok"


def test_falha_inesperada_no_acompanhamento_vira_erro_em_portugues(monkeypatch):
    monkeypatch.setattr(api_correio.time, "sleep", lambda s: None)

    def disco_cheio(*a):
        raise OSError("sem espaco em disco")
    monkeypatch.setattr(graph, "concluir_device_code", disco_cheio)
    api_correio._CODIGO[7] = "c1"
    api_correio._LOGINS[7] = {"estado": "aguardando", "user_code": "X", "verification_uri": "u"}
    api_correio._acompanhar(7, {"tenant": "t", "client_id": "c"}, "c1", 0, api_correio.time.time() + 60)
    assert api_correio._LOGINS[7]["estado"] == "erro"
    assert api_correio._LOGINS[7]["erro"] == "Não foi possível concluir a conexão; tente de novo"


# --- leitura das respostas do orgao (issue #644) -------------------------------------------------------------

def test_leitura_sem_conta_conectada_responde_vazio_sem_erro(client_admin, monkeypatch):
    from app import correio
    monkeypatch.setattr(correio, "_http", lambda *a, **k: pytest.fail("sem conta conectada nada vai ao Graph"))
    r = client_admin.post("/api/correio/respostas/ler")
    assert r.status_code == 200 and r.json() == {"novas": []}


def test_diretoria_nao_dispara_a_leitura(client):
    from app import auth, db
    conn = db.get_conn()
    auth.criar_usuario(conn, "Diretoria", "diretoria@lotufo.com", "senha-forte-123", "diretoria")
    conn.close()
    r = client.post("/api/auth/login", json={"email": "diretoria@lotufo.com", "senha": "senha-forte-123"})
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))
    client.headers["X-CSRF-Token"] = r.json()["csrf"]
    assert client.post("/api/correio/respostas/ler").status_code == 403
    # issue #654: o aviso de resposta e' de quem envia; quem so' consulta nao le nem marca
    assert client.get("/api/correio/respostas/nao-vistas").status_code == 403
    assert client.post("/api/correio/respostas/vistas/1", json={"ate": 1}).status_code == 403


def test_nao_vistas_sem_envio_e_lista_vazia_e_marcar_exige_o_teto(client_admin):
    assert client_admin.get("/api/correio/respostas/nao-vistas").json() == []
    assert client_admin.post("/api/correio/respostas/vistas/1", json={}).status_code == 422
    assert client_admin.post("/api/correio/respostas/vistas/1", json={"ate": 2 ** 63}).status_code == 422
    assert client_admin.post("/api/correio/respostas/vistas/1", json={"ate": 1}).json() == {"marcadas": 0}
