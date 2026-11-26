"""Fontes e Resultados (fatia 4 da #906, issue #919): os alertas do dia, os pares para conferir, o quadro de resultados,
a conferencia pela tela e o radar na Saude. Certames, orgaos, regras e numeros inventados; os CNPJs das chaves sao os
de exemplo dos geradores publicos."""
import pytest

from tests.test_api_licitacoes import _entrar
from tests.test_api_licitacoes_decisoes import _cortar, _linhas
from tests.test_api_radar import certame, com_token, fechar, mandar, radar, relogio  # noqa: F401

LIDO_2 = "2026-11-24T10:05:00-04:00"
LIDO_3 = "2026-11-24T10:35:00-04:00"


def _chave(n):
    return f"11444777000161-1-{n:06d}/2026"


def _c(n, **outros):
    return certame(_chave(n), f"{n:016x}", **outros)


FONTES = [{"fonte": "pncp", "nome": "PNCP", "estado": "ok", "lidos": 412, "hora": "09:01"},
          {"fonte": "diario-ex", "nome": "Diário de Exemplo", "estado": "erro", "lidos": 0, "hora": "09:02",
           "problema": "a página não respondeu"},
          {"fonte": "agregador", "nome": "Agregador", "estado": None, "lidos": None, "hora": None,
           "aguardando": "a próxima janela do robô"}]
ALERTAS = [{"regra": "orgao-interesse", "nome": "Órgãos de interesse", "chaves": [_chave(1), _chave(2)]},
           {"regra": "grande-vulto", "nome": "Grande vulto", "chaves": []}]
PARES = [{"par": "p-1-3", "a": _chave(1), "b": _chave(3), "motivo": "mesmo objeto e mesma data de sessão"},
         {"par": "p-2-4", "a": _chave(2), "b": _chave(4), "motivo": "mesmo edital em duas fontes"}]
RESULTADOS = {
    "funil": [{"rotulo": "Analisadas", "n": 30}, {"rotulo": "Propostas", "n": 12}, {"rotulo": "Vencidas", "n": 3}],
    "por_tipo": [{"grupo": "Rodovia", "participadas": 7, "vencidas": 2}, {"grupo": "Edificação", "participadas": 3, "vencidas": 0},
                 {"grupo": "Ponte", "participadas": 0, "vencidas": 0}],
    "por_modalidade": [{"grupo": "Concorrência", "participadas": 12, "vencidas": 3}],
    "perdas": [{"licitacao": "PME · CE 010/2026", "motivo": "preço", "data": "2026-10-20"}],
    "descontos": [{"licitacao": "PME · CE 010/2026", "empresa": 812, "vencedor": 1530},
                  {"licitacao": "DER-EX · CE 007/2026", "empresa": 1105, "vencedor": None, "vencemos": True}]}


@pytest.fixture
def admin(client, com_token):
    """Quatro certames recebidos; administrador logado com CSRF."""
    mandar(client, *(_c(n) for n in range(1, 5)))
    eu = _entrar(client, "admin")
    client.headers["X-CSRF-Token"] = eu["csrf"]
    return client


def _fechar(client, lido_em="2026-11-24T09:05:00-04:00", **outros):
    return fechar(client, [_chave(n) for n in range(1, 5)], lido_em=lido_em, **outros)


def _fontes(client):
    r = client.get("/api/licitacoes/fontes")
    assert r.status_code == 200, r.text
    return r.json()


def _ids_dos_pares():
    return {r["par"]: r["id"] for r in _linhas("SELECT id, par FROM lic_pares")}


def _conferir(client, par, resposta="mesmo"):
    return client.post(f"/api/licitacoes/pares/{_ids_dos_pares()[par]}/conferencia", json={"resposta": resposta})


# --- quem ve e quem decide ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("perfil,status", [("admin", 200), ("diretoria", 403), ("engenharia", 403)])
def test_fontes_e_resultados_sao_de_quem_tem_ver_licitacoes(client, perfil, status):
    for rota in ("/api/licitacoes/fontes", "/api/licitacoes/resultados"):
        assert client.get(rota).status_code == 401
    _entrar(client, perfil)
    for rota in ("/api/licitacoes/fontes", "/api/licitacoes/resultados"):
        assert client.get(rota).status_code == status


@pytest.mark.parametrize("perfil", ["diretoria", "engenharia"])
def test_so_quem_tem_editar_licitacoes_confere(client, com_token, perfil):
    eu = _entrar(client, perfil)
    client.headers["X-CSRF-Token"] = eu["csrf"]
    assert client.post("/api/licitacoes/pares/1/conferencia", json={"resposta": "mesmo"}).status_code == 403
    assert client.post("/api/licitacoes/pares/1/conferencia/desfazer").status_code == 403


def test_banco_vazio(admin):
    f = _fontes(admin)
    assert (f["fontes"], f["alertas"], f["pares"], f["conferidos"], f["decisoes"], f["pode_decidir"]) == (
        [], [], [], [], "radar", False)
    assert f["respostas"] == [{"resposta": "mesmo", "rotulo": "É o mesmo"}, {"resposta": "outro", "rotulo": "É outro"}]
    assert admin.get("/api/licitacoes/resultados").json()["resultados"] is None


# --- o que o radar manda ------------------------------------------------------------------------------------------

def test_o_fechamento_grava_fontes_alertas_pares_e_resultados(admin):
    r = _fechar(admin, fontes=FONTES, alertas=ALERTAS, pares=PARES, resultados=RESULTADOS)
    assert r.status_code == 200, r.text
    assert r.json()["pares"] == 2
    f = _fontes(admin)
    assert [(x["nome"], x["situacao"]) for x in f["fontes"]] == [
        ("PNCP", "feito"), ("Diário de Exemplo", "critico"), ("Agregador", "breve")]
    assert f["fontes"][1]["problema"] == "a página não respondeu" and f["leitura"]["fontes_com_problema"] == 1
    assert [(a["regra"], [l["chave"] for l in a["linhas"]]) for a in f["alertas"]] == [
        ("orgao-interesse", [_chave(1), _chave(2)]), ("grande-vulto", [])]
    assert f["alertas"][0]["linhas"][0]["orgao"] == "Prefeitura Municipal de Exemplo"     # a mesma linha das outras telas
    assert [(p["par"], p["a"]["chave"], p["b"]["chave"], p["motivo"]) for p in f["pares"]] == [
        ("p-1-3", _chave(1), _chave(3), "mesmo objeto e mesma data de sessão"), ("p-2-4", _chave(2), _chave(4), "mesmo edital em duas fontes")]

    res = admin.get("/api/licitacoes/resultados").json()
    assert res["lido_em"] == "2026-11-24T13:05:00+00:00"
    q = res["resultados"]
    assert q["funil"] == RESULTADOS["funil"] and q["perdas"] == RESULTADOS["perdas"]
    # a taxa em milesimos, arredondada; sem participada, nenhuma
    assert [(g["grupo"], g["taxa"]) for g in q["por_tipo"]] == [("Rodovia", 286), ("Edificação", 0), ("Ponte", None)]
    assert q["por_modalidade"][0]["taxa"] == 250
    assert [(d["empresa"], d["vencedor"], d["vencemos"]) for d in q["descontos"]] == [(812, 1530, False), (1105, None, True)]


@pytest.mark.parametrize("extra", [
    {"alertas": [{"regra": "r", "nome": "Regra", "chaves": ["98765432000198-1-000009/2026"]}]},
    {"pares": [{"par": "p-x", "a": _chave(1), "b": "98765432000198-1-000009/2026"}]},
])
def test_chave_desconhecida_num_alerta_ou_num_par_recusa_o_fechamento(admin, extra):
    r = _fechar(admin, **extra)
    assert r.status_code == 422 and "ainda não recebeu" in r.json()["detail"]
    assert _linhas("SELECT * FROM lic_leituras") == [] and _linhas("SELECT * FROM lic_pares") == []


@pytest.mark.parametrize("extra", [
    {"pares": [{"par": "p-x", "a": _chave(1), "b": _chave(1)}]},
    {"resultados": {"por_tipo": [{"grupo": "Rodovia", "participadas": 1, "vencidas": 2}]}},
    {"resultados": {"descontos": [{"licitacao": "PME · CE 001/2026", "empresa": 10001}]}},
])
def test_par_de_um_certame_so_e_resultado_impossivel_sao_recusados(admin, extra):
    assert _fechar(admin, **extra).status_code == 422


def test_o_par_que_o_radar_nao_lista_mais_sai_e_volta(admin):
    assert _fechar(admin, pares=PARES).status_code == 200
    assert _fechar(admin, lido_em=LIDO_2, pares=PARES[:1]).status_code == 200
    assert [p["par"] for p in _fontes(admin)["pares"]] == ["p-1-3"]
    assert {r["par"]: r["fora_desde"] for r in _linhas("SELECT par, fora_desde FROM lic_pares")} == {
        "p-1-3": None, "p-2-4": "2026-11-24 14:05:00"}
    # sem `pares`, nada muda; voltando, volta
    assert _fechar(admin, lido_em=LIDO_3).status_code == 200
    assert [p["par"] for p in _fontes(admin)["pares"]] == ["p-1-3"]
    assert _fechar(admin, lido_em="2026-11-24T10:45:00-04:00", pares=PARES).status_code == 200
    assert [p["par"] for p in _fontes(admin)["pares"]] == ["p-1-3", "p-2-4"]


def test_vale_o_ultimo_quadro_de_resultados_e_os_alertas_da_ultima_leitura(admin):
    assert _fechar(admin, alertas=ALERTAS, resultados=RESULTADOS).status_code == 200
    assert _fechar(admin, lido_em=LIDO_2).status_code == 200                   # sem quadro e sem alertas
    assert admin.get("/api/licitacoes/resultados").json()["lido_em"] == "2026-11-24T13:05:00+00:00"
    assert _fontes(admin)["alertas"] == []


# --- a conferencia ------------------------------------------------------------------------------------------------

def test_antes_do_corte_as_conferencias_sao_espelho_do_radar(admin):
    conf = [{"par": "p-1-3", "a": _chave(1), "b": _chave(3), "resposta": "outro", "autor": "analista",
             "quando": "2026-11-20T10:00:00-04:00"}]
    assert _fechar(admin, pares=PARES, decisoes={"favoritas": [], "conferencias": conf}).status_code == 200
    f = _fontes(admin)
    assert [p["par"] for p in f["pares"]] == ["p-2-4"] and f["pode_decidir"] is False
    (c,) = f["conferidos"]
    assert (c["par"], c["resposta"], c["resposta_rotulo"], c["quem"], c["quando"]) == (
        "p-1-3", "outro", "É outro", "analista", "2026-11-20T14:00:00+00:00")
    assert _conferir(admin, "p-2-4").status_code == 409                        # a tela nao grava antes do corte
    # o radar mudou a resposta: a antiga fica desfeita; deixou de mandar: desfeita
    conf[0]["resposta"] = "mesmo"
    assert _fechar(admin, lido_em=LIDO_2, decisoes={"favoritas": [], "conferencias": conf}).status_code == 200
    assert [(r["resposta"], r["desfeita_em"]) for r in _linhas("SELECT resposta, desfeita_em FROM lic_conferencias ORDER BY id")] == [
        ("outro", "2026-11-24 14:05:00"), ("mesmo", None)]
    assert _fechar(admin, lido_em=LIDO_3, decisoes={"favoritas": [], "conferencias": []}).status_code == 200
    assert _linhas("SELECT COUNT(*) n FROM lic_conferencias WHERE desfeita_em IS NULL") == [{"n": 0}]
    assert _fechar(admin, lido_em="2026-11-24T10:45:00-04:00", decisoes={"favoritas": [], "conferencias": [
        {**conf[0], "quando": "2027-01-01T10:00:00-04:00"}]}).status_code == 422          # data no futuro


def test_depois_do_corte_a_conferencia_e_da_tela_e_o_radar_a_busca(admin):
    assert _fechar(admin, pares=PARES).status_code == 200
    _cortar()
    assert _fontes(admin)["pode_decidir"] is True
    assert _conferir(admin, "p-1-3", "talvez").status_code == 422
    assert _conferir(admin, "p-1-3").status_code == 200
    assert _conferir(admin, "p-1-3", "outro").status_code == 409                # ja' conferido
    f = _fontes(admin)
    assert [p["par"] for p in f["pares"]] == ["p-2-4"]
    assert [(c["par"], c["resposta"], c["quem"]) for c in f["conferidos"]] == [("p-1-3", "mesmo", "Admin")]
    decisoes = admin.get("/api/radar/decisoes", headers=radar()).json()
    assert [(c["par"], c["a"], c["b"], c["resposta"], c["autor"]) for c in decisoes["conferencias"]] == [
        ("p-1-3", _chave(1), _chave(3), "mesmo", "Admin")]
    acoes = [r["acao"] for r in _linhas("SELECT acao FROM audit_log ORDER BY id")]
    assert "licitacoes.conferencia" in acoes

    # Refazer: o par volta aos pendentes, e a resposta desfeita fica, com quem e quando
    pid = _ids_dos_pares()["p-1-3"]
    assert admin.post(f"/api/licitacoes/pares/{pid}/conferencia/desfazer").status_code == 200
    assert admin.post(f"/api/licitacoes/pares/{pid}/conferencia/desfazer").status_code == 409
    assert [p["par"] for p in _fontes(admin)["pares"]] == ["p-1-3", "p-2-4"]
    (antiga,) = _linhas("SELECT resposta, desfeita_em, desfeita_por FROM lic_conferencias")
    assert antiga["resposta"] == "mesmo" and antiga["desfeita_em"] and antiga["desfeita_por"]
    assert admin.get("/api/radar/decisoes", headers=radar()).json()["conferencias"] == []

    # o par que o radar resolveu sozinho nao se confere mais; o que nao existe, 404
    assert _fechar(admin, lido_em=LIDO_2, pares=PARES[1:]).status_code == 200
    assert _conferir(admin, "p-1-3").status_code == 409
    assert admin.post("/api/licitacoes/pares/9999/conferencia", json={"resposta": "mesmo"}).status_code == 404
    # e o corte conta as conferencias
    assert "conferencias" in _cortar()


# --- a Saude --------------------------------------------------------------------------------------------------------

def test_o_radar_na_saude(client_admin, com_token):
    assert client_admin.get("/api/admin/saude").json()["radar"] == {
        "lido_em": None, "atrasada": True, "fontes_com_problema": 0}
    mandar(client_admin, _c(1))
    assert fechar(client_admin, [_chave(1)], fontes=FONTES).status_code == 200
    assert client_admin.get("/api/admin/saude").json()["radar"] == {
        "lido_em": "2026-11-24T13:05:00+00:00", "atrasada": False, "fontes_com_problema": 1}
