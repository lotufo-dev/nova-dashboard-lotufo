"""Busca unica do topo (issue #819): GET /api/busca. Obras, medicoes e processos ficticios (repositorio publico);
nomes de obra e de orgao publico podem (docs/adr/0011)."""
import pytest

from app import auth, busca, db, medicoes
from tests.conftest import novo_contrato

SENHA = "senha-forte-123"
BASE = {"objeto": "Pavimentação", "valor_original": "1.000.000,00", "vigencia_fim": "2027-12-31"}


def _entrar(client, perfil):
    conn = db.get_conn()
    auth.criar_usuario(conn, perfil.title(), f"{perfil}@exemplo.com.br", SENHA, perfil)
    conn.close()
    r = client.post("/api/auth/login", json={"email": f"{perfil}@exemplo.com.br", "senha": SENHA})
    assert r.status_code == 200, r.text
    client.cookies.set("sessao", r.cookies.get("sessao") or client.cookies.get("sessao"))
    return client


def _obra(apelido, instrumento, orgao="SINFRA-MT"):
    cid = novo_contrato({**BASE, "orgao": orgao, "numero_instrumento": instrumento})
    conn = db.get_conn()
    with db.mutacao(conn):
        conn.execute("UPDATE contratos SET nome_curto=? WHERE id=?", (apelido, cid))
    conn.close()
    return cid


def _medicao(cid, numero, competencia, tipo="execucao"):
    conn = db.get_conn()
    try:
        return medicoes.criar(conn, None, {"contrato_id": cid, "numero": numero, "tipo": tipo, "competencia": competencia})
    finally:
        conn.close()


def _processo(numero, nome, contrato_id=None, complemento=None, codigo=None):
    conn = db.get_conn()
    with db.mutacao(conn):
        pid = conn.execute("INSERT INTO siga_processos (codigo, numero, nome, contrato_id, complemento) VALUES (?,?,?,?,?)",
                           (codigo, numero, nome, contrato_id, complemento)).lastrowid
    conn.close()
    return pid


@pytest.fixture
def cenario():
    mt = _obra("MT-388", "900/2025/00/00-SINFRA")
    cox = _obra("Coxipó 3ª Etapa", "901/2024/PMC", orgao="Prefeitura de Cuiabá")
    _obra("Deciolândia", "902/2022/00/00-SINFRA")
    m15 = _medicao(mt, 15, "2026-10")
    r15 = _medicao(mt, 15, "2026-10", "reajuste")
    c15 = _medicao(cox, 15, "2026-02")
    _medicao(cox, 14, "2026-01")
    p1 = _processo("SINFRA-PRO-2026/00123", "15ª Medição - MT-388 - Processo Alfa")
    p2 = _processo(None, "Processo Beta", contrato_id=mt, complemento="Pedido de paralisação", codigo="XYZ999")
    return {"mt": mt, "cox": cox, "m15": m15, "r15": r15, "c15": c15, "p1": p1, "p2": p2}


def _q(client, q):
    r = client.get("/api/busca", params={"q": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_sem_login_nega(client):
    assert client.get("/api/busca", params={"q": "x"}).status_code == 401


def test_obra_por_nome_sem_acento_e_sem_caixa(client, cenario):
    _entrar(client, "engenharia")
    for q in ("coxipo", "COXIPÓ", "coxipó 3ª"):
        obras = _q(client, q)["obras"]
        assert [o["id"] for o in obras["itens"]] == [cenario["cox"]] and obras["total"] == 1
    o = _q(client, "coxipo")["obras"]["itens"][0]
    assert o == {"id": cenario["cox"], "nome": "Coxipó 3ª Etapa", "instrumento": "901/2024/PMC",
                 "contratante": "Prefeitura de Cuiabá", "orgao_sub": None}


def test_obra_pela_sigla_com_ou_sem_hifen_e_pelo_instrumento(client, cenario):
    _entrar(client, "engenharia")
    for q in ("MT-388", "mt388", "mt 388", "900/2025"):
        assert [o["id"] for o in _q(client, q)["obras"]["itens"]] == [cenario["mt"]], q


def test_numero_de_medicao_em_varias_obras(client, cenario):
    _entrar(client, "engenharia")
    for q in ("15", "15ª", "15a", "medição 15"):
        med = _q(client, q)["medicoes"]
        assert {m["id"] for m in med["itens"]} == {cenario["m15"], cenario["r15"], cenario["c15"]}, q
        assert med["total"] == 3
    primeira = _q(client, "15")["medicoes"]["itens"][0]       # a competencia mais nova vem antes
    assert primeira == {"id": cenario["m15"], "contrato_id": cenario["mt"], "titulo": "15ª Medição",
                        "competencia": "2026-10", "obra": "MT-388", "contratante": "SINFRA-MT"}


def test_numero_de_medicao_com_a_obra_e_o_tipo(client, cenario):
    _entrar(client, "engenharia")
    assert [m["id"] for m in _q(client, "MT-388 15")["medicoes"]["itens"]] == [cenario["m15"], cenario["r15"]]
    assert [m["id"] for m in _q(client, "coxipo 15ª")["medicoes"]["itens"]] == [cenario["c15"]]
    assert [m["id"] for m in _q(client, "reajuste 15")["medicoes"]["itens"]] == [cenario["r15"]]
    assert _q(client, "MT-388 99")["medicoes"] == {"itens": [], "total": 0}


def test_processo_pelo_numero_e_pelo_assunto(client, cenario):
    _entrar(client, "engenharia")
    for q in ("00123", "SINFRA-PRO-2026/00123", "sinfra-pro-2026/00123"):
        assert [p["id"] for p in _q(client, q)["processos"]["itens"]] == [cenario["p1"]], q
    # o nome montado (obra e assunto), o mesmo da tela SIGA
    paralisacao = _q(client, "paralisacao")["processos"]["itens"]
    assert paralisacao == [{"id": cenario["p2"], "numero": None, "assunto": "MT-388 · Pedido de paralisação"}]


def test_sem_resultado_volta_grupos_vazios(client, cenario):
    _entrar(client, "admin")
    vazio = {"itens": [], "total": 0}
    assert _q(client, "xyzw") == {"obras": vazio, "medicoes": vazio, "processos": vazio}
    assert _q(client, "   ") == {"obras": vazio, "medicoes": vazio, "processos": vazio}


def test_limite_por_grupo_com_o_total(client):
    _entrar(client, "admin")
    for i in range(busca.LIMITE + 3):
        _obra(f"Obra Teste {i}", f"{i:03d}/2026/TESTE")
    obras = _q(client, "obra teste")["obras"]
    assert len(obras["itens"]) == busca.LIMITE and obras["total"] == busca.LIMITE + 3


def test_pergunta_longa_demais_e_recusada(client):
    _entrar(client, "admin")
    assert client.get("/api/busca", params={"q": "x" * (busca.MAX_PERGUNTA + 1)}).status_code == 422


@pytest.mark.parametrize("perfil,ve", [("admin", True), ("engenharia", True), ("diretoria", False)])
def test_processo_so_para_quem_abre_o_siga(client, cenario, perfil, ve):
    """Risco de auth (#819): a diretoria nao abre o SIGA; nem o grupo, nem a contagem dele saem na resposta."""
    _entrar(client, perfil)
    for q in ("15", "00123", "MT-388", "paralisacao", "xyzw", ""):
        corpo = _q(client, q)
        assert ("processos" in corpo) is ve, (perfil, q)
        assert "SINFRA-PRO" not in str(corpo) or ve
    # obras e medicoes: todo perfil abre (a diretoria chega a' medicao pela obra)
    corpo = _q(client, "MT-388 15")
    assert [m["id"] for m in corpo["medicoes"]["itens"]] == [cenario["m15"], cenario["r15"]]
    assert [o["id"] for o in _q(client, "MT-388")["obras"]["itens"]] == [cenario["mt"]]


def test_nao_sai_valor_em_reais(client, cenario):
    _entrar(client, "admin")
    corpo = _q(client, "15")
    texto = str(corpo)
    assert "centavos" not in texto and "valor" not in texto


def test_ve_siga_segue_as_permissoes():
    assert busca.ve_siga("admin") and busca.ve_siga("engenharia")
    assert not busca.ve_siga("diretoria") and not busca.ve_siga("desconhecido")


def test_ler_pergunta():
    assert busca.ler_pergunta("MT-388 15ª")["numero"] == 15
    assert busca.ler_pergunta("MT-388 15ª")["da_obra"] == ["mt-388"]
    assert busca.ler_pergunta("Reajuste da 7ª medição") == {
        "palavras": ["reajuste", "da", "7a", "medicao"], "numero": 7, "tipo": "reajuste", "da_obra": []}
    assert busca.ler_pergunta("coxipo")["numero"] is None
