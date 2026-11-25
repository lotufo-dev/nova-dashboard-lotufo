"""Decisoes das licitacoes (fatia 2 da #906): o corte, as seis decisoes pela tela, o que o radar busca e a linha da
Inicio. Dado inventado."""
import datetime
import threading

import pytest

from app import cli, db, licitacoes, licitacoes_decisoes, permissoes, tempo
from tests.test_api_licitacoes import CHAVE_C, DOSSIE, _entrar
from tests.test_api_radar import CHAVE_A, CHAVE_B, UTC, certame, com_token, fechar, mandar, radar, relogio  # noqa: F401

DECISOES = ("favorita", "favorita/remover", "etapa", "descarte", "descarte/desfazer", "analise", "mudancas-vistas")
CORPO = {"etapa": {"etapa": "em_analise"}, "descarte": {"motivo": "valor"}}
MUDOU = [{"data": "2026-11-20", "fonte": "iomat", "texto": "publicou adiamento", "rotulo": "Sessão adiada"}]


def _ids():
    conn = db.get_conn()
    try:
        return {r["chave"]: r["id"] for r in conn.execute("SELECT id, chave FROM lic_certames")}
    finally:
        conn.close()


def _linhas(sql, *args):
    conn = db.get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def _cortar(email="admin@exemplo.com.br"):
    conn = db.get_conn()
    try:
        uid = conn.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone()["id"]
        return licitacoes_decisoes.corte(conn, uid)
    finally:
        conn.close()


def _decidir(client, cid, decisao, corpo=None):
    return client.post(f"/api/licitacoes/{cid}/{decisao}", json=corpo if corpo is not None else CORPO.get(decisao))


@pytest.fixture
def admin(client, com_token):
    """Tres certames recebidos (o A com mudanca, o C longe da sessao), rodada fechada, administrador logado com CSRF."""
    mandar(client, certame(historico=MUDOU), certame(CHAVE_B, "b" * 16),
           certame(CHAVE_C, "c" * 16, data_sessao="2027-03-01", link=""))
    assert fechar(client, [CHAVE_A, CHAVE_B, CHAVE_C], decisoes={"favoritas": [], "descartadas": []}).status_code == 200
    eu = _entrar(client, "admin")
    client.headers["X-CSRF-Token"] = eu["csrf"]
    return client


def _triagem(client):
    return client.get("/api/licitacoes/triagem").json()


def _favoritas(client):
    return client.get("/api/licitacoes/favoritas").json()["favoritas"]


# --- o corte -----------------------------------------------------------------------------------------------------

def test_antes_do_corte_ninguem_decide_pela_tela(admin):
    ids = _ids()
    assert _triagem(admin)["decisoes"] == "radar" and _triagem(admin)["pode_decidir"] is False
    for decisao in DECISOES:
        r = _decidir(admin, ids[CHAVE_A], decisao)
        assert r.status_code == 409, (decisao, r.text)
        assert r.json()["detail"] == "As decisões ainda estão com o radar: o corte das licitações não foi feito"
    assert _linhas("SELECT 1 FROM lic_favoritas") == [] and _linhas("SELECT 1 FROM lic_descartes") == []
    assert _linhas("SELECT 1 FROM audit_log WHERE acao LIKE 'licitacoes.%'") == []


def test_corte_e_um_ato_so_e_o_ensaio_nao_grava(admin, capsys, monkeypatch):
    fechar(admin, [CHAVE_A, CHAVE_B, CHAVE_C], lido_em="2026-11-24T10:00:00-04:00", decisoes={
        "favoritas": [{"chave": CHAVE_A, "desde": "2026-11-12", "autor": "o dono"}],
        "descartadas": [{"chave": CHAVE_B, "motivo": "local", "autor": "o dono"}]})
    assert cli.main(["licitacoes", "corte", "--usuario", "ninguem@exemplo.com.br"]) == 1
    assert cli.main(["licitacoes", "corte", "--usuario", "admin@exemplo.com.br", "--ensaio"]) == 0
    saida = capsys.readouterr().out
    assert "ENSAIO (nada foi gravado)" in saida and "favoritas em vigor: 1" in saida and "descartadas em vigor: 1" in saida
    assert _linhas("SELECT corte_em, corte_por FROM lic_estado") == [{"corte_em": None, "corte_por": None}]
    assert _triagem(admin)["decisoes"] == "radar"

    assert cli.main(["licitacoes", "corte", "--usuario", "admin@exemplo.com.br"]) == 0
    assert "CORTE FEITO" in capsys.readouterr().out
    (estado,) = _linhas("SELECT corte_em, corte_por FROM lic_estado")
    assert estado["corte_em"] == "2026-11-24 15:00:00" and estado["corte_por"] is not None
    (linha,) = _linhas("SELECT usuario_id, depois FROM audit_log WHERE acao='licitacoes.corte'")
    assert linha["usuario_id"] == estado["corte_por"] and '"favoritas": 1' in linha["depois"]

    monkeypatch.setattr(tempo, "agora_utc", lambda: datetime.datetime(2026, 11, 25, 15, 0, tzinfo=UTC))
    assert cli.main(["licitacoes", "corte", "--usuario", "admin@exemplo.com.br"]) == 0
    assert "já foi feito" in capsys.readouterr().out
    assert _linhas("SELECT corte_em FROM lic_estado") == [{"corte_em": "2026-11-24 15:00:00"}]
    assert len(_linhas("SELECT 1 FROM audit_log WHERE acao='licitacoes.corte'")) == 1
    t = _triagem(admin)
    assert (t["decisoes"], t["pode_decidir"]) == ("dashboard", True)
    # o ultimo espelho e' a migracao: a favorita e a descartada do radar continuam valendo
    assert [l["chave"] for l in t["recomendadas"]] == [CHAVE_C] and [l["chave"] for l in _favoritas(admin)] == [CHAVE_A]


def test_depois_do_corte_o_radar_nao_manda_decisao_e_busca_as_da_dashboard(admin):
    ids = _ids()
    _cortar()
    estado = admin.get("/api/radar/estado", headers=radar()).json()
    assert (estado["decisoes"], estado["corte_em"]) == ("dashboard", "2026-11-24T15:00:00+00:00")

    r = fechar(admin, [CHAVE_A], lido_em="2026-11-24T10:00:00-04:00", decisoes={"favoritas": []})
    assert r.status_code == 409 and r.json()["detail"] == "As decisões das licitações estão na dashboard desde 24/11/2026"
    assert len(_linhas("SELECT 1 FROM lic_leituras")) == 1                 # a rodada recusada nao foi gravada
    assert _linhas("SELECT 1 FROM lic_certames WHERE fora_desde IS NOT NULL") == []
    assert fechar(admin, [CHAVE_A, CHAVE_B, CHAVE_C], lido_em="2026-11-24T10:00:00-04:00").status_code == 200

    assert _decidir(admin, ids[CHAVE_A], "favorita").status_code == 200
    assert _decidir(admin, ids[CHAVE_A], "etapa", {"etapa": "proposta_enviada"}).status_code == 200
    assert _decidir(admin, ids[CHAVE_B], "descarte", {"motivo": "órgão"}).status_code == 200
    assert admin.get("/api/radar/decisoes").status_code == 401            # sessao de pessoa nao serve
    d = admin.get("/api/radar/decisoes", headers=radar()).json()
    assert d["corte_em"] == "2026-11-24T15:00:00+00:00"
    assert d["favoritas"] == [{"chave": CHAVE_A, "desde": "2026-11-24", "etapa": "proposta_enviada", "autor": "Admin"}]
    assert d["descartadas"] == [{"chave": CHAVE_B, "motivo": "órgão", "quando": "2026-11-24T15:00:00+00:00",
                                 "autor": "Admin"}]

    # pendencia da revisao da fatia 1: o espelho do radar nunca roda por cima de uma favorita gravada pela tela. A
    # favorita de origem `dashboard` so' existe depois do corte, e ai' a rodada com decisoes e' recusada inteira, antes
    # de qualquer gravacao (o indice "uma ativa por chave" nao chega a ser tocado)
    antes = _linhas("SELECT chave, desde, etapa, origem, removida_em FROM lic_favoritas ORDER BY id")
    assert [f["origem"] for f in antes] == ["dashboard"]
    r = fechar(admin, [CHAVE_A, CHAVE_B, CHAVE_C], lido_em="2026-11-24T10:30:00-04:00", decisoes={
        "favoritas": [{"chave": CHAVE_A, "desde": "2026-11-12", "etapa": "acompanhando"}],
        "descartadas": [{"chave": CHAVE_B, "motivo": "local"}]})
    assert r.status_code == 409
    assert _linhas("SELECT chave, desde, etapa, origem, removida_em FROM lic_favoritas ORDER BY id") == antes
    assert _linhas("SELECT motivo, origem FROM lic_descartes WHERE desfeito_em IS NULL") == [
        {"motivo": "órgão", "origem": "dashboard"}]
    assert len(_linhas("SELECT 1 FROM lic_leituras")) == 2


def test_espelho_das_descartadas_antes_do_corte(admin):
    def rodada(hora, descartadas):
        corpo = {"favoritas": []} if descartadas is None else {"favoritas": [], "descartadas": descartadas}
        return fechar(admin, [CHAVE_A, CHAVE_B, CHAVE_C], lido_em=f"2026-11-24T{hora}:00-04:00", decisoes=corpo)
    assert rodada("09:10", [{"chave": CHAVE_A, "motivo": "valor"}, {"chave": CHAVE_B, "motivo": "local"}]).json()[
        "descartadas"] == 2
    assert [l["chave"] for l in _triagem(admin)["recomendadas"]] == [CHAVE_C]
    assert rodada("09:20", None).json()["descartadas"] is None             # radar que ainda nao as manda: nada muda
    assert len(_linhas("SELECT 1 FROM lic_descartes WHERE desfeito_em IS NULL")) == 2
    rodada("09:30", [{"chave": CHAVE_A, "motivo": "outro"}])               # o motivo acompanha; a B deixa de ser
    assert _linhas("SELECT chave, motivo, origem, desfeito_em FROM lic_descartes ORDER BY chave") == [
        {"chave": CHAVE_A, "motivo": "outro", "origem": "radar", "desfeito_em": None},
        {"chave": CHAVE_B, "motivo": "local", "origem": "radar", "desfeito_em": "2026-11-24 13:30:00"}]
    r = rodada("09:40", [{"chave": CHAVE_A, "motivo": "caro"}])
    assert r.status_code == 422
    r = rodada("09:40", [{"chave": "11444777000161-1-000099/2026", "motivo": "valor"}])
    assert r.status_code == 422 and "ainda não recebeu" in r.json()["detail"]


# --- as decisoes ---------------------------------------------------------------------------------------------------

def test_favoritar_e_tirar_a_favorita(admin):
    ids = _ids()
    _cortar()
    assert [l["chave"] for l in _triagem(admin)["recomendadas"]] == [CHAVE_A, CHAVE_B, CHAVE_C]
    assert _triagem(admin)["recomendadas"][0]["id"] == ids[CHAVE_A]
    assert _decidir(admin, ids[CHAVE_B], "favorita").json() == {"id": ids[CHAVE_B]}
    assert [l["chave"] for l in _triagem(admin)["recomendadas"]] == [CHAVE_A, CHAVE_C]
    (fav,) = _favoritas(admin)
    assert (fav["chave"], fav["favorita"]["desde"], fav["favorita"]["etapa_rotulo"]) == (CHAVE_B, "2026-11-24", "Acompanhando")
    assert _decidir(admin, ids[CHAVE_B], "favorita").status_code == 409                     # ja' e' favorita
    assert _decidir(admin, 999999, "favorita").status_code == 404

    assert _decidir(admin, ids[CHAVE_B], "favorita/remover").status_code == 200
    assert [l["chave"] for l in _triagem(admin)["recomendadas"]] == [CHAVE_A, CHAVE_B, CHAVE_C] and _favoritas(admin) == []
    assert _decidir(admin, ids[CHAVE_B], "favorita/remover").status_code == 409             # nao e' mais favorita
    (linha,) = _linhas("SELECT origem, criada_por, removida_em, removida_por FROM lic_favoritas")
    assert linha["origem"] == "dashboard" and linha["criada_por"] == linha["removida_por"] is not None
    assert linha["removida_em"] == "2026-11-24 15:00:00"
    acoes = [l["acao"] for l in _linhas("SELECT acao FROM audit_log WHERE acao LIKE 'licitacoes.favorita%' ORDER BY id")]
    assert acoes == ["licitacoes.favorita", "licitacoes.favorita.remover"]


def test_etapa_so_muda_na_favorita_sem_etapa_de_dossie(admin):
    mandar(admin, certame(CHAVE_B, "d" * 16, dossie=DOSSIE))
    ids = _ids()
    _cortar()
    assert _decidir(admin, ids[CHAVE_A], "etapa").status_code == 409                        # nao e' favorita
    for chave in (CHAVE_A, CHAVE_B):
        assert _decidir(admin, ids[chave], "favorita").status_code == 200
    assert _decidir(admin, ids[CHAVE_A], "etapa", {"etapa": "proposta_enviada"}).status_code == 200
    assert _decidir(admin, ids[CHAVE_A], "etapa", {"etapa": "proposta_enviada"}).status_code == 200     # igual: nada muda
    r = _decidir(admin, ids[CHAVE_A], "etapa", {"etapa": "ganhamos"})
    assert r.status_code == 422 and r.json()["detail"] == "Escolha a etapa da licitação"
    r = _decidir(admin, ids[CHAVE_B], "etapa", {"etapa": "vencida"})
    assert r.status_code == 409 and r.json()["detail"] == "A etapa desta licitação vem do dossiê e não se muda pela tela"
    etapas = {l["chave"]: l["favorita"]["etapa"] for l in _favoritas(admin)}
    assert etapas == {CHAVE_A: "proposta_enviada", CHAVE_B: "em_analise"}
    assert _linhas("SELECT antes, depois FROM audit_log WHERE acao='licitacoes.etapa'") == [
        {"antes": '{"etapa": null}', "depois": '{"etapa": "proposta_enviada"}'}]


@pytest.mark.parametrize("motivo", licitacoes_decisoes.MOTIVOS_DESCARTE)
def test_descartar_tira_da_triagem_e_desfazer_devolve(admin, motivo):
    ids = _ids()
    _cortar()
    assert _decidir(admin, ids[CHAVE_A], "descarte", {"motivo": motivo}).status_code == 200
    assert [l["chave"] for l in _triagem(admin)["recomendadas"]] == [CHAVE_B, CHAVE_C]
    assert _triagem(admin)["contagens"]["recomendadas"] == 2
    assert _decidir(admin, ids[CHAVE_A], "descarte", {"motivo": motivo}).status_code == 409
    assert _decidir(admin, ids[CHAVE_A], "descarte/desfazer").status_code == 200
    assert _decidir(admin, ids[CHAVE_A], "descarte/desfazer").status_code == 409
    assert [l["chave"] for l in _triagem(admin)["recomendadas"]] == [CHAVE_A, CHAVE_B, CHAVE_C]
    (linha,) = _linhas("SELECT motivo, origem, desfeito_em FROM lic_descartes")
    assert linha == {"motivo": motivo, "origem": "dashboard", "desfeito_em": "2026-11-24 15:00:00"}


def test_descarte_motivo_fora_da_lista_favorita_nao_se_descarta_e_favoritar_desfaz_o_descarte(admin):
    ids = _ids()
    _cortar()
    r = _decidir(admin, ids[CHAVE_A], "descarte", {"motivo": "caro"})
    assert r.status_code == 422 and r.json()["detail"] == "Escolha o motivo do descarte"
    assert _decidir(admin, ids[CHAVE_A], "descarte", {"motivo": "valor"}).status_code == 200
    assert _decidir(admin, ids[CHAVE_A], "favorita").status_code == 200                     # desfaz o descarte
    assert _linhas("SELECT 1 FROM lic_descartes WHERE desfeito_em IS NULL") == []
    r = _decidir(admin, ids[CHAVE_A], "descarte", {"motivo": "valor"})
    assert r.status_code == 409 and r.json()["detail"] == "Favorita não se descarta: tire a favorita"


def test_analisar_o_edital(admin):
    mandar(admin, certame(CHAVE_B, "d" * 16, dossie=DOSSIE))
    ids = _ids()
    _cortar()
    assert _decidir(admin, ids[CHAVE_A], "analise").json() == {
        "id": ids[CHAVE_A], "favoritou": True, "comando": "/analisar-edital https://exemplo.com.br/editais/1",
        "aviso": None}
    # ja' favorita, em outra etapa: volta para "Em analise"; sem link, o comando vem sem ele e com o aviso
    assert _decidir(admin, ids[CHAVE_C], "favorita").status_code == 200
    assert _decidir(admin, ids[CHAVE_C], "etapa", {"etapa": "acompanhando"}).status_code == 200
    r = _decidir(admin, ids[CHAVE_C], "analise").json()
    assert (r["favoritou"], r["comando"]) == (False, "/analisar-edital") and "não tem link de edital" in r["aviso"]
    # com etapa de dossie: favorita, e a etapa continua a do dossie
    assert _decidir(admin, ids[CHAVE_B], "analise").json()["favoritou"] is True
    assert {l["chave"]: (l["favorita"]["etapa"], l["favorita"]["etapa_do_dossie"]) for l in _favoritas(admin)} == {
        CHAVE_A: ("em_analise", False), CHAVE_B: ("em_analise", True), CHAVE_C: ("em_analise", False)}
    assert _linhas("SELECT chave, etapa FROM lic_favoritas ORDER BY chave") == [
        {"chave": CHAVE_A, "etapa": "em_analise"}, {"chave": CHAVE_B, "etapa": None},
        {"chave": CHAVE_C, "etapa": "em_analise"}]


def test_mudanca_vista_tira_a_favorita_da_triagem_e_mudanca_nova_a_traz_de_volta(admin):
    antigo = [{"data": "2026-11-20", "fonte": "iomat", "texto": "publicou adiamento", "rotulo": "Sessão adiada"}]
    mandar(admin, certame(CHAVE_C, "c1" * 8, data_sessao="2027-03-01", historico=antigo))
    conn = db.get_conn()                                        # favorita desde antes da mudanca (espelho do radar)
    conn.execute("INSERT INTO lic_favoritas (chave, desde, origem) VALUES (?, '2026-11-01', 'radar')", (CHAVE_C,))
    conn.commit(); conn.close()
    ids = _ids()
    _cortar()
    (linha,) = _triagem(admin)["favoritas"]                      # longe do prazo, mas com mudanca que ninguem viu
    assert (linha["chave"], linha["favorita"]["mudancas_novas"]) == (CHAVE_C, 1)
    assert _decidir(admin, ids[CHAVE_C], "mudancas-vistas").status_code == 200
    assert _triagem(admin)["favoritas"] == []
    (fav,) = _favoritas(admin)
    assert (fav["favorita"]["mudancas_novas"], [m["vista"] for m in fav["favorita"]["mudancas"]]) == (0, [True])
    r = _decidir(admin, ids[CHAVE_C], "mudancas-vistas")
    assert r.status_code == 409 and r.json()["detail"] == "Esta favorita não tem mudança nova"

    novo = antigo + [{"data": "2026-11-23", "fonte": "pncp", "texto": "publicou retificação", "rotulo": "Retificada"}]
    mandar(admin, certame(CHAVE_C, "c2" * 8, data_sessao="2027-03-01", historico=novo))
    (linha,) = _triagem(admin)["favoritas"]
    assert [(m["data"], m["vista"]) for m in linha["favorita"]["mudancas"]] == [("2026-11-23", False), ("2026-11-20", True)]
    assert _decidir(admin, ids[CHAVE_A], "mudancas-vistas").status_code == 409              # nao e' favorita


# --- quem decide ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("perfil", ["diretoria", "engenharia"])
def test_so_quem_tem_editar_licitacoes_decide(client, com_token, perfil):
    mandar(client, certame())
    fechar(client, [CHAVE_A])
    eu = _entrar(client, "admin")
    _cortar()
    cid = _ids()[CHAVE_A]
    client.post("/api/auth/logout", headers={"X-CSRF-Token": eu["csrf"]})
    client.cookies.clear()
    for decisao in DECISOES:
        assert _decidir(client, cid, decisao).status_code == 401
    eu = _entrar(client, perfil)
    assert "editar_licitacoes" not in eu["permissoes"]
    client.headers["X-CSRF-Token"] = eu["csrf"]
    for decisao in DECISOES:
        assert _decidir(client, cid, decisao).status_code == 403, decisao
    assert client.get("/api/licitacoes/triagem").status_code == 403       # nem ve a area (decisao do dono de 24/11/2026)
    assert _linhas("SELECT 1 FROM lic_favoritas") == []


def test_quem_ve_sem_poder_decidir_le_e_nao_tem_botao(client, com_token, monkeypatch):
    """Nenhum perfil esta' assim hoje (so' o administrador ve, e ele decide); a regra da tela segue a permissao."""
    mandar(client, certame())
    fechar(client, [CHAVE_A])
    _entrar(client, "admin")
    _cortar()
    monkeypatch.setitem(permissoes.PERFIS, "admin", permissoes.PERFIS["admin"] - {permissoes.EDITAR_LICITACOES})
    t = client.get("/api/licitacoes/triagem").json()
    assert (t["decisoes"], t["pode_decidir"]) == ("dashboard", False)


def test_decisao_sem_csrf_e_recusada(admin):
    cid = _ids()[CHAVE_A]
    _cortar()
    del admin.headers["X-CSRF-Token"]
    assert _decidir(admin, cid, "favorita").status_code == 403
    assert _linhas("SELECT 1 FROM lic_favoritas") == []


def test_dois_favoritar_simultaneos_dao_um_200_e_um_409(admin):
    cid = _ids()[CHAVE_A]
    _cortar()
    largada, respostas = threading.Barrier(2), []

    def dispara():
        largada.wait()
        respostas.append(_decidir(admin, cid, "favorita"))

    ts = [threading.Thread(target=dispara) for _ in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(r.status_code for r in respostas) == [200, 409], [r.text for r in respostas]
    assert len(_linhas("SELECT 1 FROM lic_favoritas WHERE removida_em IS NULL")) == 1


# --- a linha da Inicio ----------------------------------------------------------------------------------------------

def test_a_linha_da_inicio_tem_os_numeros_da_triagem(admin):
    ids = _ids()
    _cortar()
    _decidir(admin, ids[CHAVE_B], "favorita")                    # sessao em 12 dias uteis: pede atencao
    _decidir(admin, ids[CHAVE_C], "descarte", {"motivo": "local"})
    t = _triagem(admin)
    inicio = admin.get("/api/inicio").json()["licitacoes"]
    assert inicio == {"leitura": t["leitura"], "recomendadas": t["contagens"]["recomendadas"],
                      "favoritas": len(t["favoritas"])} == {"leitura": t["leitura"], "recomendadas": 1, "favoritas": 1}
    conn = db.get_conn()
    assert licitacoes.resumo(conn)["recomendadas"] == 1
    conn.close()


def test_a_linha_da_inicio_e_so_de_quem_ve_licitacoes(client):
    _entrar(client, "engenharia")
    assert client.get("/api/inicio").json()["licitacoes"] is None
