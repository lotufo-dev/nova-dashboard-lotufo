"""Todas e Grande vulto (fatia 3 da #906) e a etapa final que encerra a favorita (decisao do dono de 26/11/2026).
Certames, orgaos e valores inventados; os CNPJs das chaves sao os de exemplo dos geradores publicos."""
import pytest

from tests.test_api_licitacoes import _entrar
from tests.test_api_licitacoes_decisoes import _cortar, _decidir, _ids, _triagem
from tests.test_api_radar import certame, com_token, fechar, mandar, relogio  # noqa: F401

MI = 100_000_000                                   # R$ 1 milhao, em centavos


def _chave(n):
    return f"11444777000161-1-{n:06d}/2026"


def _c(n, **outros):
    """Um certame inventado, novo, sem recomendacao: cada teste diz o que interessa."""
    return certame(_chave(n), f"{n:016x}", **{"recomendada": None, **outros})


def _todas(client, **busca):
    r = client.get("/api/licitacoes/todas", params=busca)
    assert r.status_code == 200, r.text
    return r.json()


def _chaves(resposta):
    return [l["chave"] for l in resposta["linhas"]]


def _opcoes(resposta, filtro):
    (f,) = [f for f in resposta["filtros"] if f["filtro"] == filtro]
    return {o["valor"]: o["n"] for o in f["opcoes"]}


@pytest.fixture
def admin(client, com_token):
    eu = _entrar(client, "admin")
    client.headers["X-CSRF-Token"] = eu["csrf"]
    return client


def _receber(client, *certames, favoritas=None, descartadas=None, listadas=None):
    mandar(client, *certames)
    chaves = listadas if listadas is not None else [c["chave"] for c in certames]
    decisoes = None if favoritas is None and descartadas is None else {"favoritas": favoritas or [],
                                                                        "descartadas": descartadas or []}
    corpo = {"decisoes": decisoes} if decisoes is not None else {}
    assert fechar(client, chaves, **corpo).status_code == 200


# --- quem ve --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("perfil,status", [("admin", 200), ("diretoria", 403), ("engenharia", 403)])
def test_todas_e_de_quem_tem_ver_licitacoes(client, perfil, status):
    assert client.get("/api/licitacoes/todas").status_code == 401
    _entrar(client, perfil)
    assert client.get("/api/licitacoes/todas").status_code == status
    assert client.get("/api/licitacoes/todas", params={"vista": "grande-vulto"}).status_code == status


def test_vista_ordem_e_data_fora_do_formato_sao_recusadas(admin):
    for busca in ({"vista": "outra"}, {"ordem": "nota"}, {"sessao_de": "10/12/2026"}):
        assert admin.get("/api/licitacoes/todas", params=busca).status_code == 422


def test_banco_vazio(admin):
    t = _todas(admin)
    assert (t["vista"], t["total"], t["linhas"], t["ordem"], t["decisoes"], t["pode_decidir"]) == (
        "novas", 0, [], "padrao", "radar", False)
    assert [o["ordem"] for o in t["ordens"]] == ["padrao", "prazo", "publicacao", "valor"]
    assert [f["filtro"] for f in t["filtros"]] == ["tipo", "modalidade", "orgao", "esfera", "valor", "km", "situacao",
                                                   "decisao", "portal"]
    # as opcoes fixas aparecem mesmo sem licitacao, com zero; as que saem do dado, nao
    assert _opcoes(t, "situacao") == {"em-aberto": 0, "encerrada": 0} and _opcoes(t, "tipo") == {}


# --- as duas vistas -------------------------------------------------------------------------------------------

def test_novas_e_grande_vulto_sao_o_que_o_radar_lista_hoje(admin):
    _receber(admin, _c(1), _c(2, nova=False), _c(3, grande_vulto=True, valor_centavos=200 * MI),
             _c(4, nova=False, grande_vulto=True, valor_centavos=180 * MI), _c(5), listadas=[_chave(n) for n in (1, 2, 3, 4)])
    novas, gv = _todas(admin), _todas(admin, vista="grande-vulto")
    assert sorted(_chaves(novas)) == [_chave(1), _chave(3)] and novas["total"] == 2     # a 5 saiu da lista do radar
    assert sorted(_chaves(gv)) == [_chave(3), _chave(4)] and gv["vista"] == "grande-vulto"
    linha = next(l for l in novas["linhas"] if l["chave"] == _chave(1))
    # a mesma linha da Triagem, com a decisao em vigor
    assert (linha["orgao"], linha["dias_uteis"], linha["prazo"], linha["favorita"], linha["descarte"]) == (
        "Prefeitura Municipal de Exemplo", 12, "breve", None, None)


# --- busca e filtros ------------------------------------------------------------------------------------------

def test_busca_sem_acento_sem_maiuscula_e_todas_as_palavras(admin):
    _receber(admin, _c(1, objeto="Pavimentação de vias no bairro Alfa", objeto_completo=""),
             _c(2, objeto="Pavimentação de estrada vicinal", objeto_completo="Pavimentação com drenagem"),
             _c(3, objeto="Reforma de escola", objeto_completo="", processo="PROC-777"))
    assert sorted(_chaves(_todas(admin, q="PAVIMENTACAO"))) == [_chave(1), _chave(2)]
    assert _chaves(_todas(admin, q="pavimentacao  alfa")) == [_chave(1)]
    assert _chaves(_todas(admin, q="drenagem")) == [_chave(2)]                 # o objeto completo tambem
    assert _chaves(_todas(admin, q="proc-777")) == [_chave(3)]
    assert _chaves(_todas(admin, q="000002/2026")) == [_chave(2)]              # a chave
    assert _todas(admin, q="ponte")["linhas"] == []


def test_cada_filtro_recorta_e_conta_com_os_outros_aplicados(admin):
    _receber(admin,
             _c(1, tipo_obra="Rodovia", esfera="Estadual", valor_centavos=60 * MI, km=250, portal="PNCP"),
             _c(2, tipo_obra="Rodovia", esfera="Municipal", valor_centavos=5 * MI, km=80, portal="Site do órgão"),
             _c(3, tipo_obra="Edificação", esfera="Estadual", valor_centavos=None, km=None, portal="PNCP"),
             _c(4, tipo_obra="", esfera="Estadual", valor_centavos=150 * MI, km=700, portal="PNCP"))
    t = _todas(admin)
    assert _opcoes(t, "tipo") == {"Edificação": 1, "Rodovia": 2}               # o tipo em branco nao vira opcao
    assert _opcoes(t, "esfera") == {"Estadual": 3, "Municipal": 1}
    assert _opcoes(t, "valor") == {"ate-1mi": 0, "1-10mi": 1, "10-50mi": 0, "50-150mi": 1, "150mi": 1, "sem-valor": 1}
    assert _opcoes(t, "km") == {"ate-100": 1, "100-300": 1, "300-600": 0, "acima-600": 1, "sem-km": 1}

    r = _todas(admin, tipo="Rodovia")
    assert sorted(_chaves(r)) == [_chave(1), _chave(2)]
    # o filtro escolhido conta com os outros: o tipo continua mostrando quantas teria cada tipo
    assert _opcoes(r, "tipo") == {"Edificação": 1, "Rodovia": 2}
    assert _opcoes(r, "esfera") == {"Estadual": 1, "Municipal": 1}
    assert next(f for f in r["filtros"] if f["filtro"] == "tipo")["escolhido"] == "Rodovia"

    r = _todas(admin, tipo="Rodovia", esfera="Estadual")
    assert _chaves(r) == [_chave(1)]
    assert _opcoes(r, "tipo") == {"Edificação": 1, "Rodovia": 1}
    assert _chaves(_todas(admin, valor="sem-valor")) == [_chave(3)]
    assert _chaves(_todas(admin, km="acima-600")) == [_chave(4)]
    assert _chaves(_todas(admin, portal="Site do órgão")) == [_chave(2)]
    # as opcoes que saem do dado tambem contam com os outros filtros
    r = _todas(admin, esfera="Municipal")
    assert _opcoes(r, "portal") == {"PNCP": 0, "Site do órgão": 1}
    assert _opcoes(r, "esfera") == {"Estadual": 3, "Municipal": 1}


def test_valor_do_endereco_que_nao_existe_nao_acha_nada_e_continua_na_lista(admin):
    _receber(admin, _c(1, modalidade="Concorrência"))
    r = _todas(admin, modalidade="Leilão")
    assert r["linhas"] == [] and r["total"] == 1
    assert _opcoes(r, "modalidade") == {"Concorrência": 1, "Leilão": 0}


def test_situacao_e_sessao_de_ate(admin):
    _receber(admin, _c(1, data_sessao="2026-12-01"), _c(2, data_sessao="2026-12-10"), _c(3, data_sessao=None),
             _c(4, data_sessao="2026-11-20"), _c(5, encerrada=True))
    assert sorted(_chaves(_todas(admin, situacao="encerrada"))) == [_chave(4), _chave(5)]
    assert _opcoes(_todas(admin), "situacao") == {"em-aberto": 3, "encerrada": 2}
    assert _chaves(_todas(admin, sessao_de="2026-12-01", sessao_ate="2026-12-01")) == [_chave(1)]   # inclusive
    assert sorted(_chaves(_todas(admin, sessao_de="2026-12-01"))) == [_chave(1), _chave(2), _chave(5)]
    assert _chaves(_todas(admin, sessao_ate="2026-11-30")) == [_chave(4)]      # sem data fica fora do recorte


# --- ordem ----------------------------------------------------------------------------------------------------

def test_as_quatro_ordens_e_as_encerradas_no_fim(admin):
    rec = lambda nota: {"nota": nota, "pontos": {"valor": 1, "distancia": 1, "acervo": 1}, "motivo": "inventado"}  # noqa: E731
    _receber(admin,
             _c(1, data_sessao="2026-12-20", data_publicacao="2026-11-02", valor_centavos=3 * MI),
             _c(2, data_sessao="2026-12-01", data_publicacao="2026-11-05", valor_centavos=None),
             _c(3, data_sessao="2026-12-15", data_publicacao="2026-11-10", valor_centavos=9 * MI, recomendada=rec(4)),
             _c(4, data_sessao=None, data_publicacao=None, valor_centavos=1 * MI, recomendada=rec(9)),
             _c(5, data_sessao="2026-11-20", data_publicacao="2026-11-20", valor_centavos=99 * MI))     # encerrada
    ordem = lambda o: [int(c.split("-")[-1][:6]) for c in _chaves(_todas(admin, ordem=o))]  # noqa: E731
    assert ordem("padrao") == [4, 3, 2, 1, 5]          # recomendadas pela nota; depois as outras pela sessao
    assert ordem("prazo") == [2, 3, 1, 4, 5]
    assert ordem("publicacao") == [3, 2, 1, 4, 5]
    assert ordem("valor") == [3, 1, 4, 2, 5]


def test_na_ordem_do_prazo_a_mesma_data_vai_pela_hora(admin):
    _receber(admin, _c(1, hora_sessao="14:00"), _c(2, hora_sessao="09:00"), _c(3, hora_sessao=None))
    assert _chaves(_todas(admin, ordem="prazo")) == [_chave(2), _chave(1), _chave(3)]


# --- decisoes -------------------------------------------------------------------------------------------------

def test_a_descartada_aparece_com_o_motivo_e_desfazer_a_devolve_a_triagem(admin):
    rec = {"nota": 6, "pontos": {"valor": 2, "distancia": 2, "acervo": 2}, "motivo": "inventado"}
    _receber(admin, _c(1, recomendada=rec), _c(2, recomendada=rec), _c(3),
             favoritas=[{"chave": _chave(3), "desde": "2026-11-20"}],
             descartadas=[{"chave": _chave(1), "motivo": "local", "quando": "2026-11-23T10:00:00-04:00"}])
    t = _todas(admin)
    descartada = next(l for l in t["linhas"] if l["chave"] == _chave(1))
    assert descartada["descarte"] == {"motivo": "local", "rotulo": "Local", "quando": "2026-11-23T14:00:00+00:00"}
    assert _opcoes(t, "decisao") == {"favorita": 1, "descartada": 1, "sem-decisao": 1}
    assert _chaves(_todas(admin, decisao="favorita")) == [_chave(3)]
    assert _chaves(_todas(admin, decisao="descartada")) == [_chave(1)]
    assert _chaves(_todas(admin, decisao="sem-decisao")) == [_chave(2)]

    _cortar()
    assert _todas(admin)["pode_decidir"] is True
    assert [l["chave"] for l in _triagem(admin)["recomendadas"]] == [_chave(2)]
    assert _decidir(admin, _ids()[_chave(1)], "descarte/desfazer").status_code == 200
    assert _todas(admin, decisao="descartada")["linhas"] == []
    assert sorted(l["chave"] for l in _triagem(admin)["recomendadas"]) == [_chave(1), _chave(2)]


# --- a etapa final encerra a favorita (decisao do dono de 26/11/2026) ----------------------------------------------

def test_etapa_final_encerra_a_favorita_mesmo_com_prazo_por_vir(admin):
    dossie = {"pasta": "2026-CE-001-exemplo", "etapa": "perdida", "selos": [], "prazos": [
        {"codigo": "recurso", "rotulo": "Recurso", "data": "2026-11-27", "hora": None, "aviso": ""}]}
    mudou = [{"data": "2026-11-23", "fonte": "pncp", "texto": "resultado publicado", "rotulo": "Resultado"}]
    _receber(admin, _c(1, dossie=dossie, historico=mudou), _c(2, data_sessao="2026-11-30"), _c(3, data_sessao="2026-12-02"),
             favoritas=[{"chave": _chave(n), "desde": "2026-11-13"} for n in (1, 2, 3)])
    _cortar()
    ids = _ids()
    assert _decidir(admin, ids[_chave(2)], "etapa", {"etapa": "desistida"}).status_code == 200

    # fora da Triagem, apesar do prazo em 3 dias uteis e da mudanca nao vista
    assert [l["chave"] for l in _triagem(admin)["favoritas"]] == [_chave(3)]
    # fora do calendario
    meses = [admin.get("/api/licitacoes/calendario", params={"mes": m}).json() for m in ("2026-11", "2026-12")]
    datas = {p["licitacao"]["chave"] for cal in meses for s in cal["semanas"] for d in s for p in d["prazos"]}
    assert datas == {_chave(3)}
    # nas Favoritas, entre as encerradas, com o resultado publicado depois
    favs = admin.get("/api/licitacoes/favoritas").json()["favoritas"]
    assert [(l["chave"], l["encerrada"]) for l in favs] == [(_chave(3), False), (_chave(2), True), (_chave(1), True)]
    perdida = favs[2]
    assert (perdida["prazo"], perdida["favorita"]["etapa"], [m["rotulo"] for m in perdida["favorita"]["mudancas"]]) == (
        None, "perdida", ["Resultado"])
    assert all(p["situacao"] is None for p in perdida["favorita"]["prazos"])
    # e em Todas, encerradas; e a conta das novas da Triagem e' a das em aberto de Todas
    assert sorted(_chaves(_todas(admin, situacao="encerrada"))) == [_chave(1), _chave(2)]
    assert _triagem(admin)["contagens"]["novas"] == _opcoes(_todas(admin), "situacao")["em-aberto"] == 1


def test_no_calendario_a_etapa_final_tira_o_que_vence_e_deixa_o_que_passou(admin):
    dossie = {"pasta": "2026-CE-002-exemplo", "etapa": "perdida", "selos": [], "prazos": [
        {"codigo": "visita", "rotulo": "Visita técnica", "data": "2026-11-10", "hora": None, "aviso": ""},
        {"codigo": "recurso", "rotulo": "Recurso", "data": "2026-11-27", "hora": None, "aviso": ""}]}
    _receber(admin, _c(1, dossie=dossie, data_sessao="2026-11-20"), favoritas=[{"chave": _chave(1), "desde": "2026-11-02"}])
    cal = admin.get("/api/licitacoes/calendario", params={"mes": "2026-11"}).json()
    assert sorted((p["data"], p["codigo"]) for s in cal["semanas"] for d in s for p in d["prazos"]) == [
        ("2026-11-10", "visita"), ("2026-11-20", "sessao")]


def test_vencida_e_proposta_enviada_nao_encerram(admin):
    _receber(admin, _c(1, data_sessao="2026-11-30"), _c(2, data_sessao="2026-11-30"),
             favoritas=[{"chave": _chave(1), "desde": "2026-11-13", "etapa": "vencida"},
                        {"chave": _chave(2), "desde": "2026-11-13", "etapa": "proposta_enviada"}])
    assert sorted(l["chave"] for l in _triagem(admin)["favoritas"]) == [_chave(1), _chave(2)]
