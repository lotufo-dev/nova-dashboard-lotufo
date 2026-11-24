"""Telas de Licitacoes (issue #908): Triagem e Favoritas, por perfil, com o que depende do dia. Dado inventado."""
import datetime

import pytest

from app import auth, db, licitacoes, permissoes, tempo
from tests.test_api_radar import CHAVE_A, CHAVE_B, UTC, certame, com_token, fechar, mandar, relogio  # noqa: F401

SENHA = "senha-forte-123"
CHAVE_C = "98765432000198-1-000003/2026"
DOSSIE = {"pasta": "2026-CE-001-exemplo-pavimentacao", "etapa": "em_analise", "prazos": [
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


def _agora(monkeypatch, ano, mes, dia, hora_cuiaba):
    monkeypatch.setattr(tempo, "agora_utc", lambda: datetime.datetime(ano, mes, dia, hora_cuiaba + 4, 0, tzinfo=UTC))


# --- quem ve ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("perfil,status", [("admin", 200), ("diretoria", 200), ("engenharia", 403)])
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
    _entrar(client, "diretoria")
    assert client.get("/api/licitacoes/triagem").json() == {
        "leitura": {"lido_em": None, "atrasada": True, "fontes_com_problema": 0},
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
    def rec(nota):
        return {"nota": nota, "pontos": {"valor": 3, "distancia": 2, "acervo": nota - 5}, "motivo": "inventado"}
    d = "11444777000161-1-000004/2026"
    e = "11444777000161-1-000005/2026"
    f = "11444777000161-1-000006/2026"
    mandar(client, certame(recomendada=rec(7)), certame(CHAVE_B, "b" * 16, recomendada=rec(9)),
           certame(CHAVE_C, "c" * 16, recomendada=rec(9), valor_centavos=None),
           certame(d, "d" * 16, recomendada=None, grupo_orgao="SINFRA-MT", primeira_vez="2026-11-24"),
           certame(e, "e" * 16, recomendada=rec(10)), certame(f, "f" * 16, recomendada=rec(10), nova=False))
    fechar(client, [CHAVE_A, CHAVE_B, CHAVE_C, d, e, f], lido_em="2026-11-23T09:00:00-04:00")
    # hoje: a `e` saiu da lista do radar; a `f` continua (recomendada mesmo fora das novas); a A virou favorita
    fechar(client, [CHAVE_A, CHAVE_B, CHAVE_C, d, f], decisoes={"favoritas": [{"chave": CHAVE_A, "desde": "2026-11-24"}]})
    _entrar(client, "diretoria")
    t = client.get("/api/licitacoes/triagem").json()
    assert [l["chave"] for l in t["recomendadas"]] == [f, CHAVE_B, CHAVE_C]       # nota, depois o valor maior
    assert all(l["favorita"] is None for l in t["recomendadas"])
    assert t["contagens"] == {"recomendadas": 3, "favoritas": 1, "novas": 4,
                              "novas_desde": {"desde": "2026-11-23", "quantas": 1},
                              "por_orgao": [{"orgao": "SINFRA-MT", "novas": 1}]}
    linha = t["recomendadas"][1]
    assert (linha["orgao"], linha["edital"], linha["valor_centavos"], linha["km"], linha["link"]) == (
        "Prefeitura Municipal de Exemplo", "CE 001/2026", 123456789, 120, "https://exemplo.com.br/editais/1")
    assert linha["recomendada"]["nota"] == 9 and "historico" not in linha and "objeto_completo" not in linha


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
    assert fa["proximo_prazo"]["codigo"] == "esclarecimento"
    assert fa["mudancas"] == [{"data": "2026-11-20", "texto": "publicou adiamento", "rotulo": "Sessão adiada"}]

    fb = b["favorita"]
    assert (fb["etapa"], fb["etapa_do_dossie"], fb["dossie"], fb["mudancas"]) == ("proposta_enviada", False, None, [])
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
