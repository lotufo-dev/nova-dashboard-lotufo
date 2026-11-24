"""Telas de Licitacoes (issue #908): Triagem e Favoritas, por perfil, com o que depende do dia. Dado inventado."""
import datetime

import pytest

from app import auth, db, licitacoes, permissoes, tempo
from tests.test_api_radar import CHAVE_A, CHAVE_B, UTC, certame, com_token, fechar, mandar, relogio  # noqa: F401

SENHA = "senha-forte-123"
CHAVE_C = "98765432000198-1-000003/2026"
DOSSIE = {"pasta": "2026-CE-001-exemplo-pavimentacao", "etapa": "em_analise", "selos": ["Diretoria: interesse"], "prazos": [
    {"codigo": "esclarecimento", "rotulo": "Esclarecimento", "data": "2026-11-27", "hora": None, "aviso": ""},
    {"codigo": "sessao", "rotulo": "Sessão", "data": "2026-12-10", "hora": "09:00", "aviso": ""}]}


def _entrar(client, perfil):
    conn = db.get_conn()
    auth.criar_usuario(conn, perfil.title(), f"{perfil}@exemplo.com.br", SENHA, perfil)
    conn.close()
    r = client.post("/api/auth/login", json={"email": f"{perfil}@exemplo.com.br", "senha": SENHA})
    assert r.status_code == 200, r.text
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))
    return client.get("/api/auth/eu").json()


def _todas(client):
    """As linhas da Triagem, favoritas e recomendadas juntas."""
    t = client.get("/api/licitacoes/triagem").json()
    return t["favoritas"] + t["recomendadas"]


def _agora(monkeypatch, ano, mes, dia, hora_cuiaba):
    monkeypatch.setattr(tempo, "agora_utc", lambda: datetime.datetime(ano, mes, dia, hora_cuiaba + 4, 0, tzinfo=UTC))


# --- quem ve ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("perfil,status", [("admin", 200), ("diretoria", 403), ("engenharia", 403)])
def test_as_telas_sao_de_quem_tem_ver_licitacoes(client, perfil, status):
    for rota in ("/api/licitacoes/triagem", "/api/licitacoes/favoritas"):
        assert client.get(rota).status_code == 401
    eu = _entrar(client, perfil)
    assert ("ver_licitacoes" in eu["permissoes"]) is (status == 200)
    for rota in ("/api/licitacoes/triagem", "/api/licitacoes/favoritas"):
        assert client.get(rota).status_code == status


def test_sem_a_permissao_ninguem_ve(client, monkeypatch):
    monkeypatch.setitem(permissoes.PERFIS, "admin", permissoes.PERFIS["admin"] - {permissoes.VER_LICITACOES})
    _entrar(client, "admin")
    assert client.get("/api/licitacoes/triagem").status_code == 403


def test_banco_vazio(client):
    _entrar(client, "admin")
    assert client.get("/api/licitacoes/triagem").json() == {
        "leitura": {"lido_em": None, "atrasada": True, "fontes_com_problema": 0},
        "decisoes": "radar", "pode_decidir": False,
        "contagens": {"recomendadas": 0, "favoritas": 0, "novas": 0, "novas_desde": None, "por_orgao": []},
        "favoritas": [], "recomendadas": []}
    assert client.get("/api/licitacoes/favoritas").json()["favoritas"] == []


# --- o que depende do dia ---------------------------------------------------------------------------------------

def test_dias_uteis_contam_o_dia_da_sessao_e_descontam_feriado():
    hoje = datetime.date(2026, 11, 24)                                   # terca
    assert licitacoes.dias_uteis_ate(hoje, hoje) == 0
    assert licitacoes.dias_uteis_ate(hoje, datetime.date(2026, 11, 27)) == 3
    assert licitacoes.dias_uteis_ate(hoje, datetime.date(2026, 11, 29)) == 3        # domingo: os mesmos tres
    assert licitacoes.dias_uteis_ate(hoje, datetime.date(2026, 11, 20)) == -2       # passada: segunda e terca
    # de segunda a segunda: cinco dias uteis; com o Natal (sexta, 25/12) no meio, quatro
    assert licitacoes.dias_uteis_ate(datetime.date(2026, 11, 30), datetime.date(2026, 12, 7)) == 5
    assert licitacoes.dias_uteis_ate(datetime.date(2026, 12, 21), datetime.date(2026, 12, 28)) == 4


@pytest.mark.parametrize("sessao,dias,prazo", [("2026-11-27", 3, "critico"), ("2026-12-01", 5, "critico"),
                                                ("2026-12-10", 12, "breve"), ("2026-12-15", 15, "breve"),
                                                ("2026-12-16", 16, None), ("2027-01-20", 39, None)])
def test_prazo_da_sessao(client, com_token, sessao, dias, prazo):
    mandar(client, certame(data_sessao=sessao))
    assert fechar(client, [CHAVE_A]).status_code == 200
    _entrar(client, "admin")
    (linha,) = client.get("/api/licitacoes/triagem").json()["recomendadas"]
    assert (linha["dias_uteis"], linha["prazo"], linha["encerrada"]) == (dias, prazo, False)


def test_sessao_passada_ou_situacao_encerrada_saem_da_triagem(client, com_token):
    mandar(client, certame(data_sessao="2026-11-23"), certame(CHAVE_B, "b" * 16, encerrada=True),
           certame(CHAVE_C, "c" * 16, data_sessao=None))
    fechar(client, [CHAVE_A, CHAVE_B, CHAVE_C])
    _entrar(client, "admin")
    t = client.get("/api/licitacoes/triagem").json()
    assert [l["chave"] for l in t["recomendadas"]] == [CHAVE_C]           # sem data de sessao nao e' passada
    assert t["recomendadas"][0]["dias_uteis"] is None and t["recomendadas"][0]["prazo"] is None
    assert (t["contagens"]["recomendadas"], t["contagens"]["novas"]) == (1, 1)


@pytest.mark.parametrize("agora,lido_em,atrasada", [
    ((2026, 11, 24, 11), "2026-11-24T09:05:00-04:00", False),            # terca 11h, leitura da propria terca
    ((2026, 11, 24, 11), "2026-11-23T13:00:00-04:00", True),             # terca 11h, leitura de segunda
    ((2026, 11, 24, 9), "2026-11-23T13:00:00-04:00", False),             # terca 9h: a de hoje ainda nao e' esperada
    ((2026, 11, 29, 12), "2026-11-27T13:00:00-04:00", False),            # domingo, leitura de sexta
    ((2026, 11, 29, 12), "2026-11-26T13:00:00-04:00", True),             # domingo, leitura de quinta
    ((2026, 11, 23, 11), "2026-11-19T13:00:00-04:00", True),             # segunda 11h; sexta 20/11 foi feriado
    ((2026, 11, 23, 9), "2026-11-19T13:00:00-04:00", False),             # segunda 9h: o dia util anterior e' a quinta
])
def test_leitura_atrasada(client, com_token, monkeypatch, agora, lido_em, atrasada):
    _agora(monkeypatch, 2026, 11, 30, 12)                                # para o fechamento nao cair no futuro
    assert fechar(client, [], lido_em=lido_em, fontes=[
        {"fonte": "pncp", "nome": "PNCP", "problema": None}, {"fonte": "siag", "nome": "SIAG", "problema": "zerou"},
    ]).status_code == 200
    _agora(monkeypatch, *agora)
    _entrar(client, "admin")
    leitura = client.get("/api/licitacoes/triagem").json()["leitura"]
    assert leitura == {"lido_em": datetime.datetime.fromisoformat(lido_em).astimezone(UTC).isoformat(),
                       "atrasada": atrasada, "fontes_com_problema": 1}
    assert client.get("/api/licitacoes/favoritas").json()["leitura"] == leitura


# --- triagem e favoritas ------------------------------------------------------------------------------------------

def test_recomendadas_na_ordem_da_nota_sem_as_favoritas_e_sem_quem_saiu_da_lista(client, com_token):
    def rec(nota, km=120):
        return {"nota": nota, "pontos": {"valor": 3, "distancia": 2, "acervo": nota - 5}, "motivo": "inventado",
                "km": km, "cidade": "Exemplo"}
    d = "11444777000161-1-000004/2026"
    e = "11444777000161-1-000005/2026"
    f = "11444777000161-1-000006/2026"
    g = "11444777000161-1-000007/2026"
    h = "11444777000161-1-000008/2026"
    mandar(client, certame(recomendada=rec(7)), certame(CHAVE_B, "b" * 16, recomendada=rec(9)),
           certame(CHAVE_C, "c" * 16, recomendada=rec(9), valor_centavos=None),
           certame(d, "d" * 16, recomendada=None, grupo_orgao="SINFRA-MT", orgao_de_interesse=True,
                   primeira_vez="2026-11-24"),
           certame(e, "e" * 16, recomendada=rec(10)), certame(f, "f" * 16, recomendada=rec(10), nova=False),
           certame(g, "9" * 16, recomendada=rec(9, km=None), valor_centavos=None),
           certame(h, "8" * 16, recomendada=rec(9, km=30), valor_centavos=None, km=900))
    fechar(client, [CHAVE_A, CHAVE_B, CHAVE_C, d, e, f, g, h], lido_em="2026-11-23T09:00:00-04:00")
    # hoje: a `e` saiu da lista do radar; a `f` continua (recomendada mesmo fora das novas); a A virou favorita
    fechar(client, [CHAVE_A, CHAVE_B, CHAVE_C, d, f, g, h],
           decisoes={"favoritas": [{"chave": CHAVE_A, "desde": "2026-11-24"}]})
    _entrar(client, "admin")
    t = client.get("/api/licitacoes/triagem").json()
    # nota; depois o valor maior; depois o mais perto, pelo local da obra que o radar mandou; sem local, no fim
    assert [l["chave"] for l in t["recomendadas"]] == [f, CHAVE_B, h, CHAVE_C, g]
    assert all(l["favorita"] is None for l in t["recomendadas"])
    assert t["contagens"] == {"recomendadas": 5, "favoritas": 1, "novas": 6,
                              "novas_desde": {"desde": "2026-11-23", "quantas": 1},
                              "por_orgao": [{"orgao": "SINFRA-MT", "novas": 1}]}
    linha = t["recomendadas"][1]
    assert (linha["orgao"], linha["edital"], linha["valor_centavos"], linha["km"], linha["link"]) == (
        "Prefeitura Municipal de Exemplo", "CE 001/2026", 123456789, 120, "https://exemplo.com.br/editais/1")
    assert linha["recomendada"] == {"nota": 9, "pontos": {"valor": 3, "distancia": 2, "acervo": 4},
                                    "motivo": "inventado", "km": 120, "cidade": "Exemplo"}
    assert "historico" not in linha and "objeto_completo" not in linha


def test_favorita_com_dossie_tem_a_etapa_os_prazos_e_as_mudancas(client, com_token):
    historico = [{"data": "2026-11-11", "fonte": "pncp", "texto": "visto pela primeira vez", "rotulo": None},
                 {"data": "2026-11-12", "fonte": "pncp", "texto": "valor mudou", "rotulo": "Valor alterado"},
                 {"data": "2026-11-20", "fonte": "iomat", "texto": "publicou adiamento", "rotulo": "Sessão adiada"},
                 {"data": "2026-11-21", "fonte": "ia", "texto": "anotação de conferência", "rotulo": None}]
    mandar(client, certame(dossie=DOSSIE, historico=historico), certame(CHAVE_B, "b" * 16, data_sessao="2027-03-01"),
           certame(CHAVE_C, "c" * 16, data_sessao="2026-11-20"))
    favs = [{"chave": CHAVE_A, "desde": "2026-11-13", "etapa": "acompanhando"},     # o dossie manda na etapa
            {"chave": CHAVE_B, "desde": "2026-11-13", "etapa": "proposta_enviada"},
            {"chave": CHAVE_C, "desde": "2026-11-13"}]
    fechar(client, [CHAVE_A, CHAVE_B, CHAVE_C], decisoes={"favoritas": favs})
    _entrar(client, "admin")
    a, b, c = client.get("/api/licitacoes/favoritas").json()["favoritas"]           # abertas pela sessao; encerrada no fim
    assert [a["chave"], b["chave"], c["chave"]] == [CHAVE_A, CHAVE_B, CHAVE_C]

    fa = a["favorita"]
    assert (fa["desde"], fa["etapa"], fa["etapa_rotulo"], fa["etapa_do_dossie"], fa["dossie"]) == (
        "2026-11-13", "em_analise", "Em análise", True, "2026-CE-001-exemplo-pavimentacao")
    assert [(p["codigo"], p["dias_uteis"], p["situacao"]) for p in fa["prazos"]] == [
        ("esclarecimento", 3, "critico"), ("sessao", 12, "breve")]
    assert fa["selos"] == ["Diretoria: interesse"]
    assert fa["proximo_prazo"]["codigo"] == "esclarecimento"
    assert fa["mudancas"] == [{"data": "2026-11-20", "texto": "publicou adiamento", "rotulo": "Sessão adiada",
                               "vista": False}]
    assert fa["mudancas_novas"] == 1

    fb = b["favorita"]
    assert (fb["etapa"], fb["etapa_do_dossie"], fb["dossie"], fb["selos"], fb["mudancas"], fb["mudancas_novas"]) == (
        "proposta_enviada", False, None, [], [], 0)
    assert [(p["codigo"], p["rotulo"], p["data"], p["situacao"]) for p in fb["prazos"]] == [
        ("sessao", "Sessão", "2027-03-01", None)]

    fc = c["favorita"]
    assert (c["encerrada"], c["prazo"], fc["etapa"], fc["etapa_rotulo"], fc["proximo_prazo"]) == (
        True, None, "acompanhando", "Acompanhando", None)
    assert [p["situacao"] for p in fc["prazos"]] == [None]

    # a Triagem mostra so' a que tem prazo chegando ou mudanca recente, e a mesma linha das Favoritas
    t = client.get("/api/licitacoes/triagem").json()
    assert t["favoritas"] == [a] and t["recomendadas"] == [] and t["contagens"]["favoritas"] == 3


def test_favorita_longe_do_prazo_entra_na_triagem_so_com_mudanca_recente(client, com_token):
    def com_mudanca_em(data):
        return [{"data": data, "fonte": "pncp", "texto": "publicou retificação", "rotulo": "Retificada"}]
    mandar(client, certame(data_sessao="2027-03-01", historico=com_mudanca_em("2026-11-17")),
           certame(CHAVE_B, "b" * 16, data_sessao="2027-03-01", historico=com_mudanca_em("2026-11-16")))
    fechar(client, [CHAVE_A, CHAVE_B], decisoes={"favoritas": [{"chave": CHAVE_A, "desde": "2026-11-01"},
                                                              {"chave": CHAVE_B, "desde": "2026-11-01"}]})
    _entrar(client, "admin")
    t = client.get("/api/licitacoes/triagem").json()
    assert [l["chave"] for l in t["favoritas"]] == [CHAVE_A]              # mudou ha' 7 dias: entra; ha' 8: nao


# --- achados da segunda revisao -----------------------------------------------------------------------------------

def test_quem_diz_hoje_e_o_servidor_e_zero_dias_uteis_nao_e_hoje(client, com_token, monkeypatch):
    """Sexta, 27/11: a sessao de hoje e a de sabado saem as duas com zero dias uteis; so' a de hoje vem marcada."""
    prazos = [{"codigo": "impugnacao", "rotulo": "Impugnação", "data": "2026-11-27", "hora": None, "aviso": ""},
              {"codigo": "visita", "rotulo": "Visita técnica", "data": "2026-11-28", "hora": None, "aviso": ""}]
    mandar(client, certame(data_sessao="2026-11-27"), certame(CHAVE_B, "b" * 16, data_sessao="2026-11-28"),
           certame(CHAVE_C, "c" * 16, data_sessao="2026-12-10", dossie=dict(DOSSIE, prazos=prazos)))
    fechar(client, [CHAVE_A, CHAVE_B, CHAVE_C], decisoes={"favoritas": [{"chave": CHAVE_C, "desde": "2026-11-12"}]})
    _agora(monkeypatch, 2026, 11, 27, 11)
    _entrar(client, "admin")
    linhas = {l["chave"]: l for l in client.get("/api/licitacoes/favoritas").json()["favoritas"]}
    por_chave = {l["chave"]: l for l in _todas(client)}
    assert (por_chave[CHAVE_A]["dias_uteis"], por_chave[CHAVE_A]["sessao_hoje"]) == (0, True)
    assert (por_chave[CHAVE_B]["dias_uteis"], por_chave[CHAVE_B]["sessao_hoje"]) == (0, False)
    assert [(p["codigo"], p["dias_uteis"], p["hoje"]) for p in linhas[CHAVE_C]["favorita"]["prazos"]] == [
        ("impugnacao", 0, True), ("visita", 0, False), ("sessao", 9, False)]
    assert linhas[CHAVE_C]["sessao_hoje"] is False


@pytest.mark.parametrize("agora", [(2026, 11, 28, 11), (2026, 11, 29, 11)])          # sabado e domingo
def test_sessao_de_sexta_vista_no_fim_de_semana_e_passada(client, com_token, monkeypatch, agora):
    """De sexta para sabado nao ha' dia util: "passada" se decide pela data, nao pelo sinal dos dias uteis."""
    mandar(client, certame(data_sessao="2026-11-27"), certame(CHAVE_B, "b" * 16, data_sessao="2026-11-27"))
    fechar(client, [CHAVE_A, CHAVE_B], decisoes={"favoritas": [{"chave": CHAVE_B, "desde": "2026-11-12"}]})
    _agora(monkeypatch, *agora)
    _entrar(client, "admin")
    t = client.get("/api/licitacoes/triagem").json()
    assert t["recomendadas"] == [] and t["favoritas"] == [] and t["contagens"]["novas"] == 0
    (fav,) = client.get("/api/licitacoes/favoritas").json()["favoritas"]
    assert (fav["dias_uteis"], fav["prazo"], fav["encerrada"]) == (0, None, True)
    assert [(p["passado"], p["situacao"]) for p in fav["favorita"]["prazos"]] == [(True, None)]
    assert fav["favorita"]["proximo_prazo"] is None


def test_sessao_no_domingo_vista_na_sexta_continua_em_aberto(client, com_token, monkeypatch):
    mandar(client, certame(data_sessao="2026-11-29"))
    fechar(client, [CHAVE_A])
    _agora(monkeypatch, 2026, 11, 27, 11)                                # sexta
    _entrar(client, "admin")
    (linha,) = client.get("/api/licitacoes/triagem").json()["recomendadas"]
    assert (linha["dias_uteis"], linha["prazo"], linha["encerrada"]) == (0, "critico", False)


@pytest.mark.parametrize("prazos", [[], [{"codigo": "esclarecimento", "rotulo": "Esclarecimento",
                                          "data": "2026-11-10", "hora": None, "aviso": ""}]])
def test_dossie_sem_a_sessao_nao_esconde_a_sessao_da_favorita(client, com_token, prazos):
    mandar(client, certame(data_sessao="2026-11-27", dossie={"pasta": "2026-CE-001-exemplo", "etapa": None,
                                                              "prazos": prazos}))
    fechar(client, [CHAVE_A], decisoes={"favoritas": [{"chave": CHAVE_A, "desde": "2026-11-12"}]})
    _entrar(client, "admin")
    (linha,) = client.get("/api/licitacoes/triagem").json()["favoritas"]           # sessao em 3 dias uteis: entra
    fav = linha["favorita"]
    assert [p["codigo"] for p in fav["prazos"]] == [p["codigo"] for p in prazos] + ["sessao"]
    assert (fav["proximo_prazo"]["codigo"], fav["proximo_prazo"]["situacao"]) == ("sessao", "critico")
    assert (fav["etapa"], fav["etapa_do_dossie"], fav["dossie"]) == ("acompanhando", False, "2026-CE-001-exemplo")


def test_novas_desde_conta_do_ultimo_dia_anterior_mesmo_com_duas_rodadas_no_dia(client, com_token):
    mandar(client, certame(primeira_vez="2026-11-24"), certame(CHAVE_B, "b" * 16, primeira_vez="2026-11-20"))
    fechar(client, [CHAVE_A, CHAVE_B], lido_em="2026-11-23T09:00:00-04:00")
    _entrar(client, "admin")
    assert client.get("/api/licitacoes/triagem").json()["contagens"]["novas_desde"] is None       # um dia so'
    fechar(client, [CHAVE_A, CHAVE_B], lido_em="2026-11-24T09:05:00-04:00")
    esperado = {"desde": "2026-11-23", "quantas": 1}
    assert client.get("/api/licitacoes/triagem").json()["contagens"]["novas_desde"] == esperado
    fechar(client, [CHAVE_A, CHAVE_B], lido_em="2026-11-24T10:30:00-04:00")                         # a rodada da tarde
    assert client.get("/api/licitacoes/triagem").json()["contagens"]["novas_desde"] == esperado
    # nem com dezenas de rodadas no mesmo dia: o dia anterior nao some da conta
    for segundo in range(35):
        assert fechar(client, [CHAVE_A, CHAVE_B], lido_em=f"2026-11-24T10:31:{segundo:02d}-04:00").status_code == 200
    assert client.get("/api/licitacoes/triagem").json()["contagens"]["novas_desde"] == esperado


def test_o_que_a_tela_mostra_acompanha_o_que_o_radar_manda(client, com_token):
    """Os tres criterios da issue vistos na resposta da tela: o objeto novo aparece, o certame que saiu da lista some
    e volta, e a favorita tirada no radar some das Favoritas."""
    mandar(client, certame(), certame(CHAVE_B, "b" * 16))
    fechar(client, [CHAVE_A, CHAVE_B], decisoes={"favoritas": [{"chave": CHAVE_B, "desde": "2026-11-12"}]})
    _entrar(client, "admin")
    triagem = lambda: client.get("/api/licitacoes/triagem").json()                                   # noqa: E731
    favoritas = lambda: [l["chave"] for l in client.get("/api/licitacoes/favoritas").json()["favoritas"]]  # noqa: E731
    assert [l["objeto"] for l in triagem()["recomendadas"]] == ["Pavimentação de vias urbanas no bairro Alfa"]
    assert favoritas() == [CHAVE_B]

    mandar(client, certame(resumo="c" * 16, objeto="Objeto retificado"))
    assert [l["objeto"] for l in triagem()["recomendadas"]] == ["Objeto retificado"]

    fechar(client, [CHAVE_B], lido_em="2026-11-24T10:00:00-04:00",
           decisoes={"favoritas": [{"chave": CHAVE_B, "desde": "2026-11-12"}]})
    assert triagem()["recomendadas"] == [] and favoritas() == [CHAVE_B]
    fechar(client, [CHAVE_A, CHAVE_B], lido_em="2026-11-24T10:30:00-04:00", decisoes={"favoritas": []})
    assert [l["chave"] for l in triagem()["recomendadas"]] == [CHAVE_A, CHAVE_B] and favoritas() == []


def test_favoritas_da_triagem_saem_pelo_prazo_mais_proximo(client, com_token):
    mandar(client, certame(data_sessao="2026-12-10"), certame(CHAVE_B, "b" * 16, data_sessao="2026-11-27"),
           certame(CHAVE_C, "c" * 16, data_sessao="2026-12-01"))
    fechar(client, [CHAVE_A, CHAVE_B, CHAVE_C], decisoes={"favoritas": [
        {"chave": k, "desde": "2026-11-12"} for k in (CHAVE_A, CHAVE_B, CHAVE_C)]})
    _entrar(client, "admin")
    assert [l["chave"] for l in client.get("/api/licitacoes/triagem").json()["favoritas"]] == [CHAVE_B, CHAVE_C, CHAVE_A]


def test_leitura_de_hoje_e_esperada_a_partir_das_10h_em_ponto(client, com_token, monkeypatch):
    assert fechar(client, [], lido_em="2026-11-23T13:00:00-04:00").status_code == 200       # segunda
    _entrar(client, "admin")
    monkeypatch.setattr(tempo, "agora_utc", lambda: datetime.datetime(2026, 11, 24, 13, 59, tzinfo=UTC))   # 9h59
    assert client.get("/api/licitacoes/triagem").json()["leitura"]["atrasada"] is False
    monkeypatch.setattr(tempo, "agora_utc", lambda: datetime.datetime(2026, 11, 24, 14, 0, tzinfo=UTC))    # 10h00
    assert client.get("/api/licitacoes/triagem").json()["leitura"]["atrasada"] is True
