"""Rotas do radar de licitacoes (issue #908): token de servico, gravacao dos certames e fechamento da rodada.

Certames, orgaos e valores sao inventados (repositorio publico); os CNPJs das chaves sao os de exemplo dos geradores
publicos."""
import datetime
import json

import pytest

from app import db, tempo

TOKEN = "token-de-teste-do-radar-0123456789"
UTC = datetime.timezone.utc
CHAVE_A = "11444777000161-1-000001/2026"
CHAVE_B = "12345678000195-1-000002/2026"
LIDO = "2026-11-24T09:05:00-04:00"                    # terca, 9h05 em Cuiaba


def certame(chave=CHAVE_A, resumo="a1b2c3d4e5f60718", **outros):
    """Um certame como o radar manda: ja' classificado. Dado inventado."""
    base = {
        "chave": chave, "resumo": resumo, "orgao": "Prefeitura Municipal de Exemplo", "unidade": "",
        "sigla_orgao": "PME", "grupo_orgao": "Outros órgãos", "esfera": "Municipal", "municipio": "Exemplo",
        "uf": "MT", "cidade": "Exemplo", "km": 120, "edital": "CE 001/2026", "modalidade": "Concorrência",
        "processo": "001/2026", "objeto": "Pavimentação de vias urbanas no bairro Alfa",
        "objeto_completo": "Pavimentação asfáltica de vias urbanas no bairro Alfa, com drenagem",
        "tipo_obra": "Urbanização", "categoria": "obra", "valor_centavos": 1_234_567_89, "valor_rotulo": "",
        "situacao": "Divulgada no PNCP", "situacao_grupo": "Em andamento", "encerrada": False,
        "data_publicacao": "2026-11-10", "data_sessao": "2026-12-10", "hora_sessao": "09:00",
        "primeira_vez": "2026-11-11", "link": "https://exemplo.com.br/editais/1", "portal": "Site do órgão",
        "modo_disputa": "Aberto", "srp": False, "fontes": ["PNCP"], "nova": True, "grande_vulto": False,
        "recomendada": {"nota": 7, "pontos": {"valor": 3, "distancia": 2, "acervo": 2},
                        "motivo": "concorrência · R$ 123,4 mi · Exemplo · 120 km · 2 atestados"},
        "historico": [{"data": "2026-11-11", "fonte": "pncp", "texto": "visto pela primeira vez", "rotulo": None}],
        "espelhos": [], "dossie": None,
    }
    return {**base, **outros}


@pytest.fixture(autouse=True)
def relogio(monkeypatch):
    """Agora = terca, 24/11/2026, 11h em Cuiaba."""
    monkeypatch.setattr(tempo, "agora_utc", lambda: datetime.datetime(2026, 11, 24, 15, 0, tzinfo=UTC))


@pytest.fixture
def com_token(tmp_path, monkeypatch):
    arquivo = tmp_path / "radar-token.txt"
    arquivo.write_text(TOKEN + "\n", encoding="utf-8")
    monkeypatch.setenv("DASH_RADAR_TOKEN_ARQUIVO", str(arquivo))


def radar(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def mandar(client, *certames):
    r = client.post("/api/radar/certames", json={"certames": list(certames)}, headers=radar())
    assert r.status_code == 200, r.text
    return r.json()


def fechar(client, chaves, lido_em=LIDO, **outros):
    return client.post("/api/radar/leituras", json={"lido_em": lido_em, "chaves": chaves, **outros}, headers=radar())


def _linhas(sql, *args):
    conn = db.get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


# --- token ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("metodo,rota,corpo", [
    ("get", "/api/radar/estado", None),
    ("post", "/api/radar/certames", {"certames": []}),
    ("post", "/api/radar/leituras", {"lido_em": LIDO, "chaves": []}),
])
def test_sem_variavel_503_sem_token_401_com_token_200(client, tmp_path, monkeypatch, metodo, rota, corpo):
    pedir = lambda **kw: getattr(client, metodo)(rota, **({"json": corpo} if corpo is not None else {}), **kw)  # noqa: E731
    monkeypatch.delenv("DASH_RADAR_TOKEN_ARQUIVO", raising=False)
    r = pedir(headers=radar())
    assert r.status_code == 503 and r.json()["detail"] == "Radar de licitações não configurado"
    arquivo = tmp_path / "radar-token.txt"
    monkeypatch.setenv("DASH_RADAR_TOKEN_ARQUIVO", str(arquivo))
    assert pedir(headers=radar()).status_code == 503                    # arquivo que nao existe
    arquivo.write_text("  \n", encoding="utf-8")
    assert pedir(headers=radar()).status_code == 503                    # arquivo vazio
    arquivo.write_bytes(TOKEN.encode("utf-16"))
    assert pedir(headers=radar()).status_code == 503                    # o `>` do PowerShell 5.1 (UTF-16)
    arquivo.write_text(TOKEN, encoding="utf-8-sig")                     # com BOM: vale
    assert pedir().status_code == 401
    assert pedir(headers=radar("outro-token-qualquer-0123456789")).status_code == 401
    assert pedir(headers={"Authorization": f"Basic {TOKEN}"}).status_code == 401
    assert pedir(headers=radar()).status_code == 200


def test_o_token_do_siga_nao_abre_as_rotas_do_radar(client, com_token, tmp_path, monkeypatch):
    siga = tmp_path / "siga-token.txt"
    siga.write_text("token-de-teste-do-siga-0123456789", encoding="utf-8")
    monkeypatch.setenv("DASH_SIGA_TOKEN_ARQUIVO", str(siga))
    assert client.get("/api/radar/estado", headers=radar("token-de-teste-do-siga-0123456789")).status_code == 401
    assert client.get("/api/siga/processos", headers=radar()).status_code == 401


def test_sessao_de_pessoa_nao_abre_as_rotas_do_radar(client_admin, com_token):
    assert client_admin.get("/api/radar/estado").status_code == 401


# --- certames ------------------------------------------------------------------------------------------------

def test_gravar_repetir_e_alterar(client, com_token):
    assert mandar(client, certame(), certame(CHAVE_B, "b" * 16)) == {"recebidos": 2, "novos": 2, "alterados": 0}
    estado = client.get("/api/radar/estado", headers=radar()).json()
    assert estado == {"decisoes": "radar", "corte_em": None, "resumos": {CHAVE_A: "a1b2c3d4e5f60718", CHAVE_B: "b" * 16}}
    conn = db.get_conn()
    conn.execute("UPDATE lic_certames SET atualizado_em='2026-01-01 00:00:00'")
    conn.commit(); conn.close()

    assert mandar(client, certame(), certame(CHAVE_B, "b" * 16)) == {"recebidos": 2, "novos": 0, "alterados": 0}
    assert {l["atualizado_em"] for l in _linhas("SELECT atualizado_em FROM lic_certames")} == {"2026-01-01 00:00:00"}

    assert mandar(client, certame(resumo="c" * 16, objeto="Objeto retificado", valor_centavos=None,
                                  recomendada=None)) == {"recebidos": 1, "novos": 0, "alterados": 1}
    a, b = _linhas("SELECT * FROM lic_certames ORDER BY chave")
    assert (a["resumo"], a["valor_centavos"], a["nota"], a["nova"], a["uf"], a["data_sessao"]) == (
        "c" * 16, None, None, 1, "MT", "2026-12-10")
    assert json.loads(a["dados"])["objeto"] == "Objeto retificado" and a["atualizado_em"] != "2026-01-01 00:00:00"
    assert (b["resumo"], b["valor_centavos"], b["nota"], b["atualizado_em"]) == (
        "b" * 16, 123456789, 7, "2026-01-01 00:00:00")
    assert "chave" not in json.loads(a["dados"]) and "resumo" not in json.loads(a["dados"])


@pytest.mark.parametrize("errado", [
    {"link": "javascript:alert(1)"}, {"link": "https://exemplo.com.br/a b"}, {"link": "file:///c:/x"},
    {"espelhos": [{"edital": "PE 9/2026", "link": "data:text/html,x"}]},
    {"resumo": "NAO-E-HEXA"}, {"chave": "   "}, {"valor_centavos": -1}, {"valor_centavos": 10.5},
    {"data_sessao": "10/12/2026"}, {"hora_sessao": "9h"}, {"objeto": "x" * 601},
    {"dossie": {"pasta": "2026-CE-001-exemplo", "etapa": "ganhamos", "prazos": []}},
    {"recomendada": {"nota": 7, "pontos": {"valor": 3, "distancia": 2}, "motivo": "sem acervo"}},
])
def test_certame_invalido_recusa_o_pedido_inteiro(client, com_token, errado):
    r = client.post("/api/radar/certames", json={"certames": [certame(CHAVE_B, "b" * 16), certame(**errado)]},
                    headers=radar())
    assert r.status_code == 422
    assert _linhas("SELECT 1 FROM lic_certames") == []


def test_acima_do_teto_geral_413(client, com_token):
    gordo = certame(objeto_completo="x" * 8000)
    r = client.post("/api/radar/certames", json={"certames": [dict(gordo, chave=f"chave-{i}") for i in range(300)]},
                    headers=radar())
    assert r.status_code == 413
    assert _linhas("SELECT 1 FROM lic_certames") == []


# --- fechamento da rodada --------------------------------------------------------------------------------------

def test_fechar_marca_quem_saiu_e_tira_a_marca_de_quem_voltou(client, com_token):
    mandar(client, certame(), certame(CHAVE_B, "b" * 16))
    fontes = [{"fonte": "pncp", "nome": "PNCP", "estado": "ativa", "lidos": 40, "hora": "09:01", "problema": None},
              {"fonte": "siag", "nome": "SIAG", "estado": "ativa", "lidos": None, "hora": None,
               "problema": "não foi lida hoje"}]
    r = fechar(client, [CHAVE_A], fontes=fontes)
    assert r.status_code == 200 and r.json() == {"listados": 1, "fora": 1, "favoritas": None}
    assert _linhas("SELECT chave, fora_desde FROM lic_certames ORDER BY chave") == [
        {"chave": CHAVE_A, "fora_desde": None}, {"chave": CHAVE_B, "fora_desde": "2026-11-24 13:05:00"}]
    (leitura,) = _linhas("SELECT lido_em, certames, fontes FROM lic_leituras")
    assert (leitura["lido_em"], leitura["certames"]) == ("2026-11-24 13:05:00", 1)
    assert [f["fonte"] for f in json.loads(leitura["fontes"])] == ["pncp", "siag"]

    assert fechar(client, [CHAVE_A], fontes=fontes).json()["fora"] == 0          # a mesma rodada de novo: nada novo
    assert len(_linhas("SELECT 1 FROM lic_leituras")) == 1

    r = fechar(client, [CHAVE_A, CHAVE_B], lido_em="2026-11-24T10:30:00-04:00")
    assert r.json() == {"listados": 2, "fora": 0, "favoritas": None}
    assert _linhas("SELECT fora_desde FROM lic_certames") == [{"fora_desde": None}, {"fora_desde": None}]
    assert len(_linhas("SELECT 1 FROM lic_leituras")) == 2


def test_fechamento_recusado_nao_grava_nada(client, com_token):
    mandar(client, certame())
    r = fechar(client, [CHAVE_A, CHAVE_B])
    assert r.status_code == 422 and r.json()["detail"] == f"Licitação que a dashboard ainda não recebeu: {CHAVE_B}"
    r = fechar(client, [CHAVE_A], decisoes={"favoritas": [{"chave": CHAVE_B, "desde": "2026-11-12"}]})
    assert r.status_code == 422 and CHAVE_B in r.json()["detail"]
    r = fechar(client, [CHAVE_A], lido_em="2026-11-24T11:11:00-04:00")           # 11 minutos no futuro
    assert r.status_code == 422 and "futuro" in r.json()["detail"]
    assert fechar(client, [CHAVE_A], lido_em="2026-11-24T09:05:00").status_code == 422   # sem fuso
    assert _linhas("SELECT 1 FROM lic_leituras") == [] and _linhas("SELECT 1 FROM lic_favoritas") == []

    assert fechar(client, [CHAVE_A]).status_code == 200
    r = fechar(client, [], lido_em="2026-11-23T13:00:00-04:00")                  # rodada antiga chegando depois
    assert r.status_code == 422 and r.json()["detail"] == "Leitura mais antiga que a última gravada"
    assert _linhas("SELECT fora_desde FROM lic_certames") == [{"fora_desde": None}]


def test_favoritas_sao_espelho_do_radar(client, com_token):
    mandar(client, certame(), certame(CHAVE_B, "b" * 16))
    favs = [{"chave": CHAVE_A, "desde": "2026-11-12", "etapa": None, "autor": "o dono"},
            {"chave": CHAVE_B, "desde": "2026-11-13", "etapa": "em_analise", "autor": "o dono"}]
    assert fechar(client, [CHAVE_A, CHAVE_B], decisoes={"favoritas": favs}).json()["favoritas"] == 2
    campos = "chave, desde, etapa, origem, autor_radar, removida_em"
    assert _linhas(f"SELECT {campos} FROM lic_favoritas ORDER BY chave") == [
        {"chave": CHAVE_A, "desde": "2026-11-12", "etapa": None, "origem": "radar", "autor_radar": "o dono",
         "removida_em": None},
        {"chave": CHAVE_B, "desde": "2026-11-13", "etapa": "em_analise", "origem": "radar", "autor_radar": "o dono",
         "removida_em": None}]

    # rodada seguinte: a A muda de etapa, a B deixa de ser favorita no radar; sem `decisoes`, nada mexeria
    assert fechar(client, [CHAVE_A, CHAVE_B], lido_em="2026-11-24T10:00:00-04:00").json()["favoritas"] is None
    assert len(_linhas("SELECT 1 FROM lic_favoritas WHERE removida_em IS NULL")) == 2
    r = fechar(client, [CHAVE_A, CHAVE_B], lido_em="2026-11-24T10:30:00-04:00",
               decisoes={"favoritas": [dict(favs[0], etapa="proposta_enviada")]})
    assert r.json()["favoritas"] == 1
    assert _linhas("SELECT chave, etapa, etapa_em, removida_em FROM lic_favoritas ORDER BY chave") == [
        {"chave": CHAVE_A, "etapa": "proposta_enviada", "etapa_em": "2026-11-24 14:30:00", "removida_em": None},
        {"chave": CHAVE_B, "etapa": "em_analise", "etapa_em": "2026-11-24 13:05:00",
         "removida_em": "2026-11-24 14:30:00"}]

    # volta a ser favorita: linha nova, e a antiga fica contando a historia
    fechar(client, [CHAVE_A, CHAVE_B], lido_em="2026-11-24T10:45:00-04:00", decisoes={"favoritas": favs})
    assert len(_linhas("SELECT 1 FROM lic_favoritas WHERE chave=?", CHAVE_B)) == 2
    assert len(_linhas("SELECT 1 FROM lic_favoritas WHERE removida_em IS NULL")) == 2
