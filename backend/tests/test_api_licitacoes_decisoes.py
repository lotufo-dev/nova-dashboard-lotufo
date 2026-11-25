"""Decisoes das licitacoes (fatia 2 da #906): o corte, as seis decisoes pela tela, o que o radar busca e a linha da
Inicio. Dado inventado."""
import datetime
import json
import threading

import pytest

from app import auth, cli, db, licitacoes, licitacoes_decisoes, permissoes, tempo
from tests.test_api_licitacoes import CHAVE_C, DOSSIE, SENHA, _entrar
from tests.test_api_radar import CHAVE_A, CHAVE_B, UTC, certame, com_token, fechar, mandar, radar, relogio  # noqa: F401

DECISOES = ("favorita", "favorita/remover", "etapa", "descarte", "descarte/desfazer", "analise", "mudancas-vistas")
CORPO = {"etapa": {"etapa": "em_analise"}, "descarte": {"motivo": "valor"},
         "mudancas-vistas": {"chaves": ["0123456789abcdef"]}}
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


def _chaves_novas(linha):
    """As chaves das mudancas nao vistas de uma linha, como a tela as manda ao marcar como vistas."""
    return [m["chave"] for m in linha["favorita"]["mudancas"] if not m["vista"]]


def _mudou(data, rotulo, texto="texto que o radar leu"):
    return {"data": data, "fonte": "pncp", "texto": texto, "rotulo": rotulo}


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
    # a etapa e o motivo fora da lista tambem: antes do corte a resposta e' a mesma, e nao a da validacao
    for decisao, corpo in (("etapa", {"etapa": "ganhamos"}), ("descarte", {"motivo": "caro"})):
        assert _decidir(admin, ids[CHAVE_A], decisao, corpo).status_code == 409, decisao
    assert _decidir(admin, 999999, "favorita").status_code == 409
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
    assert "favoritas pedindo atenção depois do corte: 1" in saida          # a favorita A, com a sessao em 12 dias uteis
    assert _linhas("SELECT 1 FROM audit_log WHERE acao='licitacoes.corte'") == []
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


@pytest.mark.parametrize("perfil", ["engenharia", "diretoria"])
def test_corte_so_por_quem_decide_as_licitacoes(admin, capsys, perfil):
    """O corte grava em nome de quem o faz: usuario ativo sem `editar_licitacoes` nao corta, nem em ensaio."""
    conn = db.get_conn()
    auth.criar_usuario(conn, perfil.title(), f"{perfil}@exemplo.com.br", SENHA, perfil)
    conn.close()
    for extra in ([], ["--ensaio"]):
        assert cli.main(["licitacoes", "corte", "--usuario", f"{perfil}@exemplo.com.br", *extra]) == 1
        saida = capsys.readouterr().out
        assert "não tem essa permissão: nada foi gravado" in saida and "CORTE FEITO" not in saida and "ENSAIO" not in saida
    assert _linhas("SELECT corte_em, corte_por FROM lic_estado") == [{"corte_em": None, "corte_por": None}]
    assert _linhas("SELECT 1 FROM audit_log WHERE acao='licitacoes.corte'") == []


def test_corte_sem_a_linha_de_estado_falha_em_vez_de_dizer_que_cortou(admin, capsys):
    conn = db.get_conn()
    conn.execute("DELETE FROM lic_estado"); conn.commit(); conn.close()
    for extra in ([], ["--ensaio"]):
        assert cli.main(["licitacoes", "corte", "--usuario", "admin@exemplo.com.br", *extra]) == 1
        saida = capsys.readouterr().out
        assert "O corte não foi gravado: falta a linha de estado das licitações" in saida
        assert "CORTE FEITO" not in saida and "ENSAIO" not in saida
    assert _linhas("SELECT 1 FROM lic_estado") == [] and _triagem(admin)["decisoes"] == "radar"
    assert _linhas("SELECT 1 FROM audit_log WHERE acao='licitacoes.corte'") == []


def test_corte_deixa_a_triagem_com_as_mesmas_favoritas_da_vespera(admin, capsys):
    """Ate' o corte vale a mudanca dos ultimos 7 dias; depois, a mudanca que ninguem viu. No corte as mudancas com
    mais de 7 dias entram como vistas, senao toda mudanca antiga das favoritas do radar apareceria de uma vez."""
    mandar(admin, certame(CHAVE_B, "b2" * 8, data_sessao="2027-03-01", historico=[_mudou("2026-11-21", "Sessão adiada")]),
           certame(CHAVE_C, "c2" * 8, data_sessao="2027-03-01", historico=[_mudou("2026-10-15", "Edital retificado")]))
    assert fechar(admin, [CHAVE_A, CHAVE_B, CHAVE_C], lido_em="2026-11-24T10:00:00-04:00", decisoes={
        "favoritas": [{"chave": CHAVE_B, "desde": "2026-09-10"}, {"chave": CHAVE_C, "desde": "2026-09-10"}],
        "descartadas": []}).status_code == 200
    # antes: so' a de mudanca de tres dias atras; a de outubro esta' fora
    assert [l["chave"] for l in _triagem(admin)["favoritas"]] == [CHAVE_B]
    assert cli.main(["licitacoes", "corte", "--usuario", "admin@exemplo.com.br", "--ensaio"]) == 0
    assert "favoritas pedindo atenção depois do corte: 1" in capsys.readouterr().out
    assert _linhas("SELECT mudancas_vistas FROM lic_favoritas") == [{"mudancas_vistas": "[]"}] * 2     # o ensaio nao grava
    assert cli.main(["licitacoes", "corte", "--usuario", "admin@exemplo.com.br"]) == 0
    assert "favoritas pedindo atenção depois do corte: 1" in capsys.readouterr().out
    # depois: as mesmas
    t = _triagem(admin)
    assert t["decisoes"] == "dashboard" and [l["chave"] for l in t["favoritas"]] == [CHAVE_B]
    vistas = {l["chave"]: [m["vista"] for m in l["favorita"]["mudancas"]] for l in _favoritas(admin)}
    assert vistas == {CHAVE_B: [False], CHAVE_C: [True]}


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


def test_auditoria_guarda_o_que_valia_antes(admin):
    """Tirar a favorita, desfazer o descarte e favoritar a descartada: o `antes` diz o que valia."""
    ids = _ids()
    _cortar()
    _decidir(admin, ids[CHAVE_A], "favorita")
    _decidir(admin, ids[CHAVE_A], "etapa", {"etapa": "proposta_enviada"})
    _decidir(admin, ids[CHAVE_A], "favorita/remover")
    _decidir(admin, ids[CHAVE_B], "descarte", {"motivo": "local"})
    _decidir(admin, ids[CHAVE_B], "descarte/desfazer")
    _decidir(admin, ids[CHAVE_C], "descarte", {"motivo": "valor"})
    _decidir(admin, ids[CHAVE_C], "favorita")
    def audit(acao, cid):
        return [(json.loads(l["antes"]) if l["antes"] else None, json.loads(l["depois"]) if l["depois"] else None)
                for l in _linhas("SELECT antes, depois FROM audit_log WHERE acao=? AND entidade='licitacao' "
                                 "AND entidade_id=? ORDER BY id", acao, str(cid))]
    assert audit("licitacoes.favorita.remover", ids[CHAVE_A]) == [
        ({"chave": CHAVE_A, "desde": "2026-11-24", "etapa": "proposta_enviada"}, None)]
    assert audit("licitacoes.descarte.desfazer", ids[CHAVE_B]) == [({"chave": CHAVE_B, "motivo": "local"}, None)]
    assert audit("licitacoes.favorita", ids[CHAVE_C]) == [({"descartada": "valor"}, {"chave": CHAVE_C, "etapa": None})]
    assert audit("licitacoes.favorita", ids[CHAVE_A]) == [(None, {"chave": CHAVE_A, "etapa": None})]


def test_decisoes_sobre_o_que_veio_do_radar_depois_do_corte(admin):
    """As favoritas e as descartadas espelhadas do radar continuam valendo depois do corte, e a tela decide sobre
    elas: sem 500, e a linha antiga fica, com a data e quem mudou. Inclusive a chave que o radar mandou como favorita
    e descartada ao mesmo tempo."""
    assert fechar(admin, [CHAVE_A, CHAVE_B, CHAVE_C], lido_em="2026-11-24T10:00:00-04:00", decisoes={
        "favoritas": [{"chave": CHAVE_A, "desde": "2026-11-12", "autor": "o dono"},
                      {"chave": CHAVE_B, "desde": "2026-11-13", "etapa": "acompanhando", "autor": "o dono"}],
        "descartadas": [{"chave": CHAVE_A, "motivo": "valor", "autor": "o dono"},
                        {"chave": CHAVE_C, "motivo": "local", "autor": "o dono"}]}).status_code == 200
    ids = _ids()
    _cortar()
    t = _triagem(admin)                                           # a que e' as duas coisas conta como favorita
    assert t["recomendadas"] == [] and {l["chave"] for l in _favoritas(admin)} == {CHAVE_A, CHAVE_B}
    assert _decidir(admin, ids[CHAVE_A], "descarte", {"motivo": "outro"}).status_code == 409     # favorita nao se descarta
    assert _decidir(admin, ids[CHAVE_A], "favorita/remover").status_code == 200
    assert _decidir(admin, ids[CHAVE_A], "descarte", {"motivo": "outro"}).status_code == 409     # ja' esta' descartada
    assert _decidir(admin, ids[CHAVE_A], "favorita").status_code == 200                          # desfaz o descarte do radar
    assert _decidir(admin, ids[CHAVE_B], "etapa", {"etapa": "proposta_enviada"}).status_code == 200
    assert _decidir(admin, ids[CHAVE_B], "analise").status_code == 200
    assert _decidir(admin, ids[CHAVE_C], "descarte/desfazer").status_code == 200
    assert _decidir(admin, ids[CHAVE_C], "favorita").status_code == 200
    assert _decidir(admin, ids[CHAVE_C], "favorita/remover").status_code == 200
    favoritas = _linhas("SELECT chave, origem, desde, autor_radar, removida_em IS NOT NULL AS removida, "
                        "removida_por IS NOT NULL AS por FROM lic_favoritas ORDER BY id")
    assert favoritas == [
        {"chave": CHAVE_A, "origem": "radar", "desde": "2026-11-12", "autor_radar": "o dono", "removida": 1, "por": 1},
        {"chave": CHAVE_B, "origem": "radar", "desde": "2026-11-13", "autor_radar": "o dono", "removida": 0, "por": 0},
        {"chave": CHAVE_A, "origem": "dashboard", "desde": "2026-11-24", "autor_radar": None, "removida": 0, "por": 0},
        {"chave": CHAVE_C, "origem": "dashboard", "desde": "2026-11-24", "autor_radar": None, "removida": 1, "por": 1}]
    assert _linhas("SELECT chave, motivo, origem, autor_radar, desfeito_em IS NOT NULL AS desfeito, "
                   "desfeito_por IS NOT NULL AS por FROM lic_descartes ORDER BY id") == [
        {"chave": CHAVE_A, "motivo": "valor", "origem": "radar", "autor_radar": "o dono", "desfeito": 1, "por": 1},
        {"chave": CHAVE_C, "motivo": "local", "origem": "radar", "autor_radar": "o dono", "desfeito": 1, "por": 1}]
    assert {l["chave"]: l["favorita"]["etapa"] for l in _favoritas(admin)} == {CHAVE_A: "acompanhando", CHAVE_B: "em_analise"}
    assert [l["chave"] for l in _triagem(admin)["recomendadas"]] == [CHAVE_C]


def test_descarte_espelhado_entra_com_a_data_que_tinha_no_radar(admin):
    def rodada(hora, descartadas):
        return fechar(admin, [CHAVE_A, CHAVE_B, CHAVE_C], lido_em=f"2026-11-24T{hora}:00-04:00",
                      decisoes={"favoritas": [], "descartadas": descartadas})
    assert rodada("09:10", [{"chave": CHAVE_A, "motivo": "valor", "quando": "2026-11-10T16:30:00-04:00"},
                            {"chave": CHAVE_B, "motivo": "local"}]).status_code == 200
    (a, b) = _linhas("SELECT chave, criado_em FROM lic_descartes ORDER BY chave")
    assert a == {"chave": CHAVE_A, "criado_em": "2026-11-10 20:30:00"}            # em UTC, como o resto do banco
    assert b["criado_em"] != a["criado_em"] and b["criado_em"] is not None       # sem `quando`, a hora do espelho
    # a data acompanha o radar, como o motivo; a rodada sem ela nao mexe na que ja' veio
    assert rodada("09:20", [{"chave": CHAVE_A, "motivo": "valor", "quando": "2026-11-11T08:00:00-04:00"}]).status_code == 200
    assert rodada("09:30", [{"chave": CHAVE_A, "motivo": "valor"}]).status_code == 200
    assert _linhas("SELECT criado_em FROM lic_descartes WHERE chave=? AND desfeito_em IS NULL", CHAVE_A) == [
        {"criado_em": "2026-11-11 12:00:00"}]
    assert rodada("09:40", [{"chave": CHAVE_A, "motivo": "valor", "quando": "2026-11-11 08:00:00"}]).status_code == 422   # sem fuso
    _cortar()
    (d,) = admin.get("/api/radar/decisoes", headers=radar()).json()["descartadas"]
    assert (d["chave"], d["quando"]) == (CHAVE_A, "2026-11-11T12:00:00+00:00")


def test_defeito_dentro_de_uma_decisao_nao_vira_404_nem_422(admin, monkeypatch):
    """So' as recusas proprias das decisoes viram resposta; `KeyError`, `ValueError` e afins de um defeito sobem."""
    ids = _ids()
    _cortar()
    for erro in (KeyError("campo"), IndexError("fora"), ValueError("json")):
        def quebrada(*_args, _erro=erro):
            raise _erro
        monkeypatch.setattr(licitacoes_decisoes, "favoritar", quebrada)
        with pytest.raises(type(erro)):
            _decidir(admin, ids[CHAVE_A], "favorita")
    assert _linhas("SELECT 1 FROM lic_favoritas") == []


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
    assert r["aviso"] == "Esta licitação não tem link de edital: baixe o edital e passe o arquivo ao comando"
    # com etapa de dossie: favorita, e a etapa continua a do dossie
    assert _decidir(admin, ids[CHAVE_B], "analise").json()["favoritou"] is True
    assert {l["chave"]: (l["favorita"]["etapa"], l["favorita"]["etapa_do_dossie"]) for l in _favoritas(admin)} == {
        CHAVE_A: ("em_analise", False), CHAVE_B: ("em_analise", True), CHAVE_C: ("em_analise", False)}
    assert _linhas("SELECT chave, etapa FROM lic_favoritas ORDER BY chave") == [
        {"chave": CHAVE_A, "etapa": "em_analise"}, {"chave": CHAVE_B, "etapa": None},
        {"chave": CHAVE_C, "etapa": "em_analise"}]


@pytest.mark.parametrize("link", [
    "https://exemplo.com.br/a;calc.exe", "https://exemplo.com.br/$(calc.exe)", "https://exemplo.com.br/a|b",
    "https://exemplo.com.br/a&b=1", "https://exemplo.com.br/`id`", "https://exemplo.com.br/a'b", 'https://exemplo.com.br/a"b',
    "https://exemplo.com.br/a<b>", "https://exemplo.com.br/a\\b", "https://exemplo.com.br/{a,b}", "https://exemplo.com.br/a(b)",
    "https://exemplo.com.br/edital\u200b.pdf", "https://exemplo.com.br/\u202eedital", "https://exemplo.com.br/edital\ufeff",
    "https://exemplo.com.br/edição", "https://exemplo.com.br/a!b", "https://exemplo.com.br/a*"])
def test_link_estranho_nao_entra_no_comando_da_analise(admin, link):
    """O comando e' colado num terminal: o link com caractere que o terminal interpreta, ou que nao se ve, fica de
    fora, e o comando sai como o da licitacao sem link."""
    mandar(admin, certame(CHAVE_B, "e" * 16, link=link))
    ids = _ids()
    _cortar()
    r = _decidir(admin, ids[CHAVE_B], "analise")
    assert r.status_code == 200, r.text
    assert r.json() == {"id": ids[CHAVE_B], "favoritou": True, "comando": "/analisar-edital",
                        "aviso": "Esta licitação não tem link de edital: baixe o edital e passe o arquivo ao comando"}


@pytest.mark.parametrize("link", ["https://exemplo.com.br/editais/2026/CE-001_v2.pdf?id=12#anexos",
                                  "http://exemplo.com.br:8080/~obras/edital%20001,parte+1"])
def test_link_comum_entra_no_comando_da_analise(admin, link):
    mandar(admin, certame(CHAVE_B, "e" * 16, link=link))
    ids = _ids()
    _cortar()
    assert _decidir(admin, ids[CHAVE_B], "analise").json()["comando"] == f"/analisar-edital {link}"


def test_mudanca_vista_tira_a_favorita_da_triagem_e_mudanca_nova_a_traz_de_volta(admin):
    antigo = [{"data": "2026-11-23", "fonte": "iomat", "texto": "publicou adiamento", "rotulo": "Sessão adiada"}]
    mandar(admin, certame(CHAVE_C, "c1" * 8, data_sessao="2027-03-01", historico=antigo))
    conn = db.get_conn()                                        # favorita desde antes da mudanca (espelho do radar)
    conn.execute("INSERT INTO lic_favoritas (chave, desde, origem) VALUES (?, '2026-11-01', 'radar')", (CHAVE_C,))
    conn.commit(); conn.close()
    ids = _ids()
    _cortar()
    (linha,) = _triagem(admin)["favoritas"]                      # longe do prazo, mas com mudanca que ninguem viu
    assert (linha["chave"], linha["favorita"]["mudancas_novas"]) == (CHAVE_C, 1)
    (adiada,) = _chaves_novas(linha)
    # so' vale a chave de uma mudanca desta favorita: a inventada e a lista vazia nao marcam nada
    r = _decidir(admin, ids[CHAVE_C], "mudancas-vistas", {"chaves": ["0123456789abcdef"]})
    assert r.status_code == 409 and r.json()["detail"] == "Esta favorita não tem mudança nova"
    for corpo in ({"chaves": []}, {}, {"chaves": [adiada] * 201}, {"chaves": ["x" * 33]}, {"chaves": [""]}):
        assert admin.post(f"/api/licitacoes/{ids[CHAVE_C]}/mudancas-vistas", json=corpo).status_code == 422, corpo
    assert len(_triagem(admin)["favoritas"]) == 1
    assert _decidir(admin, ids[CHAVE_C], "mudancas-vistas", {"chaves": [adiada, "0123456789abcdef"]}).status_code == 200
    assert _triagem(admin)["favoritas"] == []
    (fav,) = _favoritas(admin)
    assert (fav["favorita"]["mudancas_novas"], [m["vista"] for m in fav["favorita"]["mudancas"]]) == (0, [True])
    r = _decidir(admin, ids[CHAVE_C], "mudancas-vistas", {"chaves": [adiada]})
    assert r.status_code == 409 and r.json()["detail"] == "Esta favorita não tem mudança nova"
    # a auditoria guarda a lista de antes e a de depois, so' com a chave que era mesmo uma mudanca
    assert _linhas("SELECT antes, depois FROM audit_log WHERE acao='licitacoes.mudancas_vistas'") == [
        {"antes": '{"vistas": []}', "depois": json.dumps({"vistas": [adiada]})}]

    # o cenario que falhava com a marca por data: a rodada seguinte traz uma mudanca do MESMO dia da que foi vista e
    # outra de um dia ANTERIOR (o radar le mais de uma vez por dia). As duas nascem nao vistas e a favorita volta
    novo = antigo + [{"data": "2026-11-23", "fonte": "pncp", "texto": "publicou retificação", "rotulo": "Retificada"},
                     {"data": "2026-11-21", "fonte": "iomat", "texto": "publicou a suspensão", "rotulo": "Suspensa"}]
    mandar(admin, certame(CHAVE_C, "c2" * 8, data_sessao="2027-03-01", historico=novo))
    (linha,) = _triagem(admin)["favoritas"]
    assert sorted((m["data"], m["rotulo"], m["vista"]) for m in linha["favorita"]["mudancas"]) == [
        ("2026-11-21", "Suspensa", False), ("2026-11-23", "Retificada", False), ("2026-11-23", "Sessão adiada", True)]
    assert linha["favorita"]["mudancas_novas"] == 2
    # a tela marca o que mostrou: se mostrou so' uma, a outra continua nao vista e a favorita continua na Triagem
    retificada = next(m["chave"] for m in linha["favorita"]["mudancas"] if m["rotulo"] == "Retificada")
    assert _decidir(admin, ids[CHAVE_C], "mudancas-vistas", {"chaves": [retificada]}).status_code == 200
    (linha,) = _triagem(admin)["favoritas"]
    assert [m["rotulo"] for m in linha["favorita"]["mudancas"] if not m["vista"]] == ["Suspensa"]
    assert _decidir(admin, ids[CHAVE_C], "mudancas-vistas", {"chaves": _chaves_novas(linha)}).status_code == 200
    assert _triagem(admin)["favoritas"] == []
    assert _decidir(admin, ids[CHAVE_A], "mudancas-vistas", {"chaves": [adiada]}).status_code == 409    # nao e' favorita


@pytest.mark.parametrize("decisao", ["favorita", "analise"])
def test_quem_favorita_ja_viu_as_mudancas_que_a_licitacao_tem(admin, decisao):
    """Favoritar (ou pedir a analise) no dia de uma mudanca nao poe a favorita na Triagem na mesma hora; a mudanca que
    chegar depois poe."""
    hoje = [_mudou("2026-11-24", "Edital retificado")]
    mandar(admin, certame(CHAVE_C, "c1" * 8, data_sessao="2027-03-01", historico=hoje))
    ids = _ids()
    _cortar()
    assert _decidir(admin, ids[CHAVE_C], decisao).status_code == 200
    assert _triagem(admin)["favoritas"] == []
    (fav,) = _favoritas(admin)
    assert [(m["rotulo"], m["vista"]) for m in fav["favorita"]["mudancas"]] == [("Edital retificado", True)]
    mandar(admin, certame(CHAVE_C, "c2" * 8, data_sessao="2027-03-01", historico=hoje + [_mudou("2026-11-24", "Novo anexo")]))
    (linha,) = _triagem(admin)["favoritas"]
    assert [(m["rotulo"], m["vista"]) for m in linha["favorita"]["mudancas"] if not m["vista"]] == [("Novo anexo", False)]


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
    for decisao in DECISOES:                                              # as sete rotas
        assert _decidir(admin, cid, decisao).status_code == 403, decisao
    admin.headers["X-CSRF-Token"] = "outro-token"
    for decisao in DECISOES:
        assert _decidir(admin, cid, decisao).status_code == 403, decisao
    assert _linhas("SELECT 1 FROM lic_favoritas") == [] and _linhas("SELECT 1 FROM lic_descartes") == []
    assert _linhas("SELECT 1 FROM audit_log WHERE acao LIKE 'licitacoes.%' AND acao<>'licitacoes.corte'") == []


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
    # a linha tem rota propria: `/api/inicio` e' pedida por paginas que so' querem os avisos, e nao roda a Triagem
    linha = admin.get("/api/licitacoes/resumo").json()
    assert linha == {"leitura": t["leitura"], "recomendadas": t["contagens"]["recomendadas"],
                     "favoritas": len(t["favoritas"])} == {"leitura": t["leitura"], "recomendadas": 1, "favoritas": 1}
    assert set(admin.get("/api/inicio").json()) == {"avisos", "resumo"}
    conn = db.get_conn()
    assert licitacoes.resumo(conn)["recomendadas"] == 1
    conn.close()


@pytest.mark.parametrize("perfil", ["engenharia", "diretoria"])
def test_a_linha_da_inicio_e_so_de_quem_ve_licitacoes(client, perfil):
    assert client.get("/api/licitacoes/resumo").status_code == 401
    _entrar(client, perfil)
    assert client.get("/api/licitacoes/resumo").status_code == 403
    assert set(client.get("/api/inicio").json()) == {"avisos", "resumo"}
