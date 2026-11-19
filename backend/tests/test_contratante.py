"""Abas da pagina do contratante (issue #818): Medicoes, A receber e Processos no SIGA, cada uma o recorte, pelas obras
do contratante, de uma resposta que outra tela ja' mostra. Nenhuma conta nova: as linhas sao as mesmas, o subtotal a
receber e' o da pagina A receber filtrada, ao centavo, e a diretoria nao recebe a aba do SIGA. Obras, orgaos, processos
e valores ficticios (os cenarios de test_fila_medicoes e test_fechamento)."""
import datetime
import json

import pytest
from fastapi.testclient import TestClient

from app import a_receber, auth, contratante, fila_medicoes, siga, tempo
from app.main import create_app
from tests.test_fechamento import _lancar_dois_anos, contratantes  # noqa: F401  (a fixture `contratantes` vem de la')
from tests.test_fila_medicoes import HOJE, MES, cenario, conn  # noqa: F401  (as fixtures `conn` e `cenario` vem de la')

UTC = datetime.timezone.utc
SENHA = "senha-forte-123"


def _relogio(monkeypatch, instante: datetime.datetime):
    monkeypatch.setattr(tempo, "agora_utc", lambda: instante)


def _cliente(monkeypatch) -> TestClient:
    """O app sobre o banco que a fixture do cenario ja' abriu (DASH_DB_PATH dela)."""
    monkeypatch.setenv("DASH_SEM_JOBS", "1")
    monkeypatch.setenv("DASH_SEM_FRONTEND", "1")
    return TestClient(create_app())


def _entrar(cliente: TestClient, email: str):
    r = cliente.post("/api/auth/login", json={"email": email, "senha": SENHA})
    assert r.status_code == 200, r.text
    cliente.cookies.set("sessao", r.cookies.get("sessao") or cliente.cookies.get("sessao"))


def _perfis(c):
    for perfil in ("diretoria", "engenharia"):
        auth.criar_usuario(c, perfil.title(), f"{perfil}@exemplo.com.br", SENHA, perfil)


# --- Medicoes ----------------------------------------------------------------------------------------------------

def _ids_das_linhas(r):
    return [x["medicao_id"] for g in r["grupos"] for x in g["linhas"]]


def test_medicoes_sao_as_linhas_da_fila_do_mes_em_trabalho_so_das_obras_do_contratante(conn, cenario):
    """A competencia e' a em trabalho (o mes anterior ao de hoje). As linhas sao as da fila, os mesmos objetos, na
    mesma ordem e no mesmo grupo; a obra da MTPAR sai do recorte da SINFRA e vice-versa."""
    ids = cenario
    fila = fila_medicoes.fila(conn, HOJE, MES)
    r = contratante.medicoes(conn, "sinfra", HOJE)
    assert r["mes"] == MES == "2026-10" and r["hoje"] == "2026-11-18"
    assert r["limites"] == fila["limites"]
    # a fila inteira: com a Lotufo A (execucao + reajuste), B e M; com o faturamento F; com o orgao C, G, H e P
    assert [(g["com_quem"], len(g["linhas"])) for g in r["grupos"]] == [("lotufo", 2), ("faturamento", 1), ("orgao", 4)]
    for g in r["grupos"]:
        da_fila = next(x for x in fila["grupos"] if x["com_quem"] == g["com_quem"])
        assert g["linhas"] == [x for x in da_fila["linhas"] if x["contrato_id"] != ids["m"]]
    assert ids["m8"] not in _ids_das_linhas(r)
    # as concluidas no mes e as obras sem medicao nele, so' as do contratante
    assert r["concluidas"] == fila["concluidas"] and [x["medicao_id"] for x in r["concluidas"]] == [ids["k7"]]
    assert [x["obra"] for x in r["sem_medicao"]] == ["Obra D", "Obra X"]
    # a quantidade e' o numero de linhas que a aba mostra: as da fila e as concluidas
    assert r["quantidade"] == 7 + 1 == len(_ids_das_linhas(r)) + len(r["concluidas"])

    m = contratante.medicoes(conn, "mtpar", HOJE)
    assert _ids_das_linhas(m) == [ids["m8"]] and m["grupos"][0]["com_quem"] == "lotufo"
    assert (m["concluidas"], m["sem_medicao"], m["quantidade"]) == ([], [], 1)
    # nenhuma linha some e nenhuma aparece em dois contratantes
    assert sorted(_ids_das_linhas(r) + _ids_das_linhas(m)) == sorted(x["medicao_id"] for g in fila["grupos"] for x in g["linhas"])


def test_chave_sem_diferenca_de_maiuscula_e_chave_que_nenhuma_obra_tem_e_desconhecida(conn, cenario):
    assert contratante.medicoes(conn, "SINFRA", HOJE) == contratante.medicoes(conn, "sinfra", HOJE)
    for ler in (contratante.medicoes, contratante.em_aberto, contratante.processos_no_siga):
        with pytest.raises(contratante.ContratanteDesconhecido):
            ler(conn, "orgao-que-nao-existe")


# --- A receber ---------------------------------------------------------------------------------------------------

def _da_pagina(r, chave):
    """O contratante da pagina A receber filtrada por `chave` (como AReceber.tsx acha o `?contratante=`)."""
    return next(g for g in r["contratantes"] if g["chave"] is not None and g["chave"].lower() == chave.lower())


def test_a_receber_e_o_grupo_da_pagina_a_receber_filtrada_ao_centavo(contratantes):
    """O subtotal de cada contratante (com consorcio, nota partilhada entre dois contratantes, paga em parte e medicao
    sem nota) e' o da pagina A receber filtrada por ele; o grupo inteiro, linha a linha, e' o mesmo objeto."""
    c, ids = contratantes
    _lancar_dois_anos(c, ids)
    pagina = a_receber.a_receber(c, HOJE)
    somados = 0
    for chave in ("sinfra", "orgao-x", "companhia-y"):
        aba = contratante.em_aberto(c, chave, HOJE)
        g = _da_pagina(pagina, chave)
        assert aba["contratante"]["em_aberto_centavos"] == g["em_aberto_centavos"]
        assert aba["contratante"] == g
        assert aba["quantidade"] == g["quantidade"] == len(g["linhas"])
        assert aba["anos"] == pagina["anos"] and aba["total_a_receber_liberado"] is True
        somados += aba["contratante"]["em_aberto_centavos"]
    # os tres contratantes tem chave: somam o total da pagina
    assert somados == pagina["em_aberto_centavos"] == 1_434_994
    assert [contratante.em_aberto(c, k, HOJE)["contratante"]["em_aberto_centavos"] for k in ("sinfra", "orgao-x", "companhia-y")] == [
        1_200_002, 234_992, 0]
    assert contratante.em_aberto(c, "SINFRA", HOJE) == contratante.em_aberto(c, "sinfra", HOJE)


def test_a_receber_sem_o_total_liberado_so_a_trava_e_contratante_sem_grupo(contratantes):
    c, ids = contratantes
    _lancar_dois_anos(c, ids)
    # o contratante cujas obras estao todas encerradas e sem nada em aberto nao tem grupo na pagina A receber
    c.execute("UPDATE contratos SET estado='encerrado' WHERE id=?", (ids["Galpão"],))
    c.commit()
    assert all(g["chave"] != "companhia-y" for g in a_receber.a_receber(c, HOJE)["contratantes"])
    assert contratante.em_aberto(c, "companhia-y", HOJE) == {"anos": ["2025", "2026"], "total_a_receber_liberado": True,
                                                             "contratante": None, "quantidade": 0}
    c.execute("UPDATE cadastro_geral SET valor=? WHERE chave='diretoria'", (json.dumps({"total_a_receber_liberado": False}),))
    c.commit()
    # nem valor, nem linha, nem contagem: a contagem de notas em aberto deixaria deduzir quais foram pagas
    assert contratante.em_aberto(c, "sinfra", HOJE) == {"anos": ["2025", "2026"], "total_a_receber_liberado": False}


def test_rota_compara_as_duas_respostas_a_receber_e_e_de_todo_perfil(contratantes, monkeypatch):
    """GET /api/contratantes/<chave>/a-receber contra GET /api/a-receber: o mesmo grupo e o mesmo subtotal."""
    c, ids = contratantes
    _lancar_dois_anos(c, ids)
    _perfis(c)
    _relogio(monkeypatch, datetime.datetime(2026, 11, 18, 15, 0, tzinfo=UTC))
    with _cliente(monkeypatch) as cliente:
        assert cliente.get("/api/contratantes/sinfra/a-receber").status_code == 401
        for email in ("adm@exemplo.com.br", "diretoria@exemplo.com.br", "engenharia@exemplo.com.br"):
            _entrar(cliente, email)
            pagina = cliente.get("/api/a-receber").json()
            for chave in ("sinfra", "orgao-x", "companhia-y"):
                r = cliente.get(f"/api/contratantes/{chave}/a-receber")
                assert r.status_code == 200, r.text
                g = _da_pagina(pagina, chave)
                assert r.json()["contratante"]["em_aberto_centavos"] == g["em_aberto_centavos"]
                assert r.json()["contratante"] == g and r.json()["quantidade"] == g["quantidade"]
        assert cliente.post("/api/contratantes/sinfra/a-receber").status_code == 405


# --- Processos no SIGA -------------------------------------------------------------------------------------------

AGORA = datetime.datetime(2026, 10, 28, 20, 0, tzinfo=UTC)          # quarta-feira, 16h em Cuiaba
LIDO = datetime.datetime(2026, 10, 28, 11, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-4)))


def _processo(numero, setor, entrada):
    """Processo lido pelo robo, no `setor` desde `entrada` (DD/MM/AAAA)."""
    return {"codigo": None, "numero": numero, "nome": f"Processo {numero}", "situacao": f"1º Volume - Aguardando [{setor}, [X]]",
            "movimentacoes": [{"data": f"{entrada} 09:00:00", "evento": "Recebimento", "cad_lotacao": "PROTOC/ORGAO",
                               "cad_pessoa": "Beltrano", "at_lotacao": f"{setor}/ORGAO", "at_pessoa": "Fulano"}]}


def _ligar(c, numero, contrato_id, medicao_id=None):
    c.execute("UPDATE siga_processos SET contrato_id=?, medicao_id=? WHERE numero=?", (contrato_id, medicao_id, numero))
    return c.execute("SELECT id FROM siga_processos WHERE numero=?", (numero,)).fetchone()[0]


@pytest.fixture
def processos(contratantes, monkeypatch):
    """Na SINFRA, tres processos vivos (dois lidos, parados ha' 7 e ha' 2 dias uteis, e um nunca lido que o robo nao
    conseguiu ler) e um encerrado (a medicao dele foi recebida); na Secretaria X, um vivo nunca lido; e um sem obra."""
    c, ids = contratantes
    _relogio(monkeypatch, AGORA)
    siga.gravar_leitura(c, LIDO, [_processo("ORGAO-PRO-2026/00001", "COFIN", "19/10/2026"),
                                  _processo("ORGAO-PRO-2026/00002", "GABIN", "26/10/2026"),
                                  _processo("ORGAO-PRO-2026/00003", "COFIN", "01/10/2026"),
                                  _processo("ORGAO-PRO-2026/00004", "COFIN", "05/10/2026"),
                                  _processo("ORGAO-PRO-2026/00005", "SECOM", "01/09/2026")])
    recebida = c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado) "
                         "VALUES (?, 3, 'execucao', '2026-08', 'recebida')", (ids["Estrada"],)).lastrowid
    p = {"sete": _ligar(c, "ORGAO-PRO-2026/00001", ids["Estrada"]), "dois": _ligar(c, "ORGAO-PRO-2026/00002", ids["Ponte"]),
         "encerrado": _ligar(c, "ORGAO-PRO-2026/00003", ids["Estrada"], recebida),
         "secretaria": None, "sem_obra": c.execute("SELECT id FROM siga_processos WHERE numero='ORGAO-PRO-2026/00005'").fetchone()[0]}
    # dois processos colados na tela e nunca lidos: o robo nao conseguiu ler nenhum dos dois na rodada
    for numero, obra in (("ORGAO-PRO-2026/00006", "Ponte"), ("ORGAO-PRO-2026/00007", "Escola")):
        c.execute("INSERT INTO siga_processos (numero, nome, contrato_id) VALUES (?, ?, ?)", (numero, f"Processo {numero}", ids[obra]))
    c.execute("UPDATE siga_processos SET contrato_id=? WHERE numero='ORGAO-PRO-2026/00004'", (ids["Escola"],))
    c.commit()
    p["nunca"] = c.execute("SELECT id FROM siga_processos WHERE numero='ORGAO-PRO-2026/00006'").fetchone()[0]
    p["secretaria"] = c.execute("SELECT id FROM siga_processos WHERE numero='ORGAO-PRO-2026/00004'").fetchone()[0]
    p["secretaria_nunca"] = c.execute("SELECT id FROM siga_processos WHERE numero='ORGAO-PRO-2026/00007'").fetchone()[0]
    rodada = siga.iniciar_rodada(c, AGORA)["rodada_id"]
    siga.terminar_rodada(c, rodada, [{"numero": "ORGAO-PRO-2026/00006", "motivo": "A página não abriu"},
                                     {"numero": "ORGAO-PRO-2026/00007", "motivo": "A página não abriu"}], AGORA)
    return c, ids, p


def test_siga_os_processos_vivos_do_contratante_do_mais_parado_para_o_menos(processos):
    c, ids, p = processos
    painel = siga.painel(c, AGORA)
    r = contratante.processos_no_siga(c, "sinfra", AGORA)
    # os mesmos objetos da tela SIGA; o encerrado, o da Secretaria X e o sem obra ficam de fora
    assert [x["id"] for x in r["processos"]] == [p["sete"], p["dois"], p["nunca"]]
    assert [x["dias_uteis"] for x in r["processos"]] == [7, 2, None]
    da_tela = {x["id"]: x for x in painel["processos"]}
    assert all(x == da_tela[x["id"]] for x in r["processos"])
    assert r["quantidade"] == len(r["processos"]) == 3
    assert (r["limites"], r["lido_em"]) == (painel["limites"], painel["lido_em"])
    # do robo, so' o "nao lido" dos processos da aba (o da Secretaria X e o resumo da rodada ficam na tela SIGA)
    assert [a["processo_id"] for a in painel["robo"]["avisos"] if a["tipo"] == "nao_lido"] == [p["nunca"], p["secretaria_nunca"]]
    assert [(a["tipo"], a["processo_id"]) for a in r["robo"]["avisos"]] == [("nao_lido", p["nunca"])]

    x = contratante.processos_no_siga(c, "orgao-x", AGORA)
    assert [y["id"] for y in x["processos"]] == [p["secretaria"], p["secretaria_nunca"]] and x["quantidade"] == 2
    assert contratante.processos_no_siga(c, "companhia-y", AGORA)["processos"] == []
    # nenhum contratante leva o processo sem obra nem o encerrado
    todos = {y["id"] for k in ("sinfra", "orgao-x", "companhia-y") for y in contratante.processos_no_siga(c, k, AGORA)["processos"]}
    assert p["sem_obra"] not in todos and p["encerrado"] not in todos


def test_rota_do_siga_nega_a_diretoria_e_as_outras_abas_nao(processos, monkeypatch):
    """A diretoria nao ve a tela SIGA: a aba nao aparece e o servidor nao manda o dado dela (403, sem processo no
    corpo). Medicoes e A receber continuam abertas a ela; engenharia e administracao recebem os processos."""
    c, ids, p = processos
    _perfis(c)
    with _cliente(monkeypatch) as cliente:
        assert cliente.get("/api/contratantes/sinfra/siga").status_code == 401
        _entrar(cliente, "diretoria@exemplo.com.br")
        negado = cliente.get("/api/contratantes/sinfra/siga")
        assert negado.status_code == 403 and "processos" not in negado.json() and "ORGAO-PRO" not in negado.text
        assert cliente.get("/api/contratantes/sinfra/medicoes").status_code == 200
        assert cliente.get("/api/contratantes/sinfra/a-receber").status_code == 200
        for email in ("engenharia@exemplo.com.br", "adm@exemplo.com.br"):
            _entrar(cliente, email)
            r = cliente.get("/api/contratantes/sinfra/siga")
            assert r.status_code == 200, r.text
            assert [x["id"] for x in r.json()["processos"]] == [p["sete"], p["dois"], p["nunca"]]
            assert r.json()["quantidade"] == 3
            assert cliente.get("/api/contratantes/orgao-que-nao-existe/siga").status_code == 404


def test_rota_das_medicoes_e_a_chave_invalida(conn, cenario, monkeypatch):
    auth.criar_usuario(conn, "Diretoria", "diretoria@exemplo.com.br", SENHA, "diretoria")
    _relogio(monkeypatch, datetime.datetime(2026, 11, 18, 15, 0, tzinfo=UTC))
    with _cliente(monkeypatch) as cliente:
        assert cliente.get("/api/contratantes/sinfra/medicoes").status_code == 401
        _entrar(cliente, "diretoria@exemplo.com.br")
        r = cliente.get("/api/contratantes/sinfra/medicoes")
        assert r.status_code == 200, r.text
        assert set(r.json()) == {"hoje", "mes", "limites", "grupos", "concluidas", "sem_medicao", "quantidade"}
        assert r.json()["mes"] == "2026-10" and r.json()["quantidade"] == 8
        assert r.json() == contratante.medicoes(conn, "sinfra", HOJE)
        # a chave e' a do endereco da pagina (letras, digitos, ponto, traco e sublinhado); a que nenhuma obra tem, 404
        for ruim in ("-sinfra", "sin%20fra", "a" * 81):
            assert cliente.get(f"/api/contratantes/{ruim}/medicoes").status_code == 422
        for aba in ("medicoes", "a-receber"):
            r = cliente.get(f"/api/contratantes/orgao-que-nao-existe/{aba}")
            assert r.status_code == 404 and r.json()["detail"] == "Contratante não encontrado"
