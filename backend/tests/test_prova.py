"""Roteiros de prova (scripts/prova, issue #702): as recusas do ambiente, o ambiente do servidor de prova, o
comparador do retrato e as listas de rotas do retrato conferidas contra as rotas de verdade do backend."""
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "scripts" / "prova"))
import comum  # noqa: E402
import retrato  # noqa: E402
import servidor  # noqa: E402


# --- recusas: banco, cadastro e saida ---------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path):
    """Um repositorio de mentira e uma pasta de fora, para as recusas nao dependerem de onde a suite roda."""
    raiz = tmp_path / "repo"
    (raiz / "backend" / "dados").mkdir(parents=True)
    fora = tmp_path / "fora"
    fora.mkdir()
    return raiz, fora


def test_sem_dash_db_path_recusa(repo):
    raiz, _ = repo
    for ambiente in ({}, {"DASH_DB_PATH": ""}, {"DASH_DB_PATH": "   "}):
        with pytest.raises(comum.Recusa, match="DASH_DB_PATH não definida"):
            comum.banco_de_prova(ambiente, raiz)


@pytest.mark.parametrize("escrita, base", [
    ("{raiz}/backend/dados/dashboard.db", None),             # absoluto
    ("dados/dashboard.db", "{fora}"),                         # como o backend resolve, a partir de backend/
    ("backend/dados/dashboard.db", "{raiz}"),                 # relativo a raiz do repositorio
    ("{raiz}/backend/dados/../dados/dashboard.db", None),     # com volta no caminho
    ("{fora}/outro-clone/backend/dados/dashboard.db", None),  # o banco padrao de outra copia do repositorio
    ("{fora}/outro-clone/Backend/Dados/Dashboard.db", None),  # disco que nao diferencia maiuscula
])
def test_banco_padrao_e_recusado_escrito_de_qualquer_jeito(repo, escrita, base):
    raiz, fora = repo
    valor = escrita.format(raiz=raiz, fora=fora)
    base = Path(base.format(raiz=raiz, fora=fora)) if base else None
    with pytest.raises(comum.Recusa, match="banco padrão"):
        comum.banco_de_prova({"DASH_DB_PATH": valor}, raiz, base)


def test_banco_dentro_do_repositorio_e_recusado(repo):
    raiz, _ = repo
    with pytest.raises(comum.Recusa, match="dentro do repositório"):
        comum.banco_de_prova({"DASH_DB_PATH": str(raiz / "backend" / "dados" / "prova.db")}, raiz)


def test_banco_que_e_pasta_e_recusado(repo):
    raiz, fora = repo
    with pytest.raises(comum.Recusa, match="é uma pasta"):
        comum.banco_de_prova({"DASH_DB_PATH": str(fora)}, raiz)


def test_banco_fora_do_repositorio_passa_novo_ou_copia(repo):
    raiz, fora = repo
    novo, copia = fora / "prova.db", fora / "copia.db"
    copia.write_bytes(b"")
    assert comum.banco_de_prova({"DASH_DB_PATH": str(novo)}, raiz) == novo.resolve()
    assert comum.banco_de_prova({"DASH_DB_PATH": "copia.db"}, raiz, base=fora) == copia.resolve()


def test_o_repositorio_de_verdade_recusa_o_proprio_banco_padrao():
    with pytest.raises(comum.Recusa, match="banco padrão"):
        comum.banco_de_prova({"DASH_DB_PATH": str(RAIZ / "backend" / "dados" / "dashboard.db")})


def test_cadastro_faltando_ou_inexistente_recusa(repo):
    _, fora = repo
    with pytest.raises(comum.Recusa, match="DASH_CADASTRO_DIR não definida"):
        comum.cadastro_de_prova({})
    with pytest.raises(comum.Recusa, match="não é uma pasta que existe"):
        comum.cadastro_de_prova({"DASH_CADASTRO_DIR": str(fora / "nao-existe")})
    assert comum.cadastro_de_prova({"DASH_CADASTRO_DIR": str(fora)}) == fora.resolve()
    assert comum.cadastro_de_prova({"DASH_CADASTRO_DIR": "cadastro-exemplo"}, base=RAIZ) == comum.CADASTRO_EXEMPLO


def test_saida_padrao_fica_ao_lado_do_banco(repo):
    raiz, fora = repo
    ambiente = {"DASH_DB_PATH": str(fora / "prova.db")}
    assert comum.saida_de_prova(ambiente, raiz=raiz) == (fora / "prova-saida").resolve()


def test_saida_dentro_do_repositorio_so_na_pasta_ignorada(repo):
    raiz, fora = repo
    banco = fora / "prova.db"
    with pytest.raises(comum.Recusa, match="dentro do repositório"):
        comum.saida_de_prova({"DASH_PROVA_SAIDA": str(raiz / "docs" / "capturas")}, banco, raiz)
    with pytest.raises(comum.Recusa, match="dentro do repositório"):
        comum.saida_de_prova({"DASH_PROVA_SAIDA": str(raiz)}, banco, raiz)
    dentro = raiz / comum.SAIDA_NO_REPOSITORIO / "entrega-1"
    assert comum.saida_de_prova({"DASH_PROVA_SAIDA": str(dentro)}, banco, raiz) == dentro.resolve()
    assert comum.saida_de_prova({"DASH_PROVA_SAIDA": str(fora / "x")}, banco, raiz) == (fora / "x").resolve()


def test_a_pasta_de_saida_do_repositorio_esta_no_gitignore():
    linhas = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert f"{comum.SAIDA_NO_REPOSITORIO}/" in linhas


def test_o_que_nasce_ao_lado_do_banco_fica_na_pasta_dele(repo):
    _, fora = repo
    arquivos = comum.arquivos_da_prova(fora / "prova.db")
    assert set(arquivos) == {"senha", "servidor", "log", "correio", "dist"}
    assert all(a.parent == fora for a in arquivos.values())


# --- ambiente do servidor de prova -------------------------------------------------------------------------------

def test_ambiente_do_servidor_nao_herda_rm_nem_email_de_verdade(repo):
    _, fora = repo
    terminal = {"PATH": "/bin", "HOME": "/casa", "DASH_RM_URL": "https://rm", "DASH_RM_SENHA": "x",
                "DASH_GRAPH_CLIENT_ID": "id", "DASH_GRAPH_TOKENS_DIR": "/tokens", "DASH_EMAIL_REAL_EM_DEV": "1",
                "DASH_EMAIL_REDIRECIONAR": "a@exemplo.com.br", "DASH_BACKUP_EXTERNO": "/disco",
                "DASH_SEM_FRONTEND": "1", "DASH_DB_PATH": "outro.db", "DASH_FONTE_CARTA": "/fontes/a.ttf"}
    banco, cadastro, dist = fora / "prova.db", fora / "cadastro", fora / "dist"
    env = comum.ambiente_do_servidor(terminal, banco, cadastro, dist)
    assert {k: v for k, v in env.items() if k.startswith("DASH_")} == {
        "DASH_DEV": "1", "DASH_SEM_JOBS": "1", "DASH_DB_PATH": str(banco), "DASH_CADASTRO_DIR": str(cadastro),
        "DASH_GRAPH_SIMULADOR": str(fora / "correio-simulado"), "DASH_DIST_PATH": str(dist),
        "DASH_FONTE_CARTA": "/fontes/a.ttf"}
    assert env["PATH"] == "/bin" and env["HOME"] == "/casa"


def test_ambiente_do_servidor_sem_frontend(repo):
    _, fora = repo
    env = comum.ambiente_do_servidor({}, fora / "prova.db", fora, None)
    assert env["DASH_SEM_FRONTEND"] == "1" and "DASH_DIST_PATH" not in env


def test_senha_de_teste_e_gerada_uma_vez_e_serve_para_o_sistema(tmp_path):
    from app import auth
    arquivo = tmp_path / "pasta" / "prova-senha.txt"
    assert servidor.garantir_senha(arquivo) is True
    senha = arquivo.read_text(encoding="utf-8").strip()
    assert len(senha) >= auth.SENHA_MIN
    assert servidor.garantir_senha(arquivo) is False                 # ja' existe: nao troca
    assert arquivo.read_text(encoding="utf-8").strip() == senha
    outro = tmp_path / "outra" / "prova-senha.txt"
    servidor.garantir_senha(outro)
    assert outro.read_text(encoding="utf-8").strip() != senha        # cada prova tem a sua


def test_usuarios_de_teste_um_por_perfil_do_sistema():
    from app import permissoes
    assert set(comum.PERFIS) == set(permissoes.PERFIS)
    assert comum.email_de_teste("diretoria") == "prova-diretoria@exemplo.com.br"


# --- comparador do retrato ---------------------------------------------------------------------------------------

def _r(corpo, status=200):
    return {"status": status, "corpo": corpo}


def test_retratos_iguais_nao_tem_diferenca():
    antes = {"/api/x": _r({"a": 1, "lista": [{"id": 1, "v": 2}], "n": None}), "/api/y": _r([1, 2], 404)}
    assert retrato.comparar(antes, {k: dict(v) for k, v in antes.items()}) == []


def test_campo_que_mudou_sai_com_o_caminho_e_os_dois_valores():
    linhas = retrato.comparar({"/api/x": _r({"topo": {"saldo_centavos": 100, "nome": "Obra"}})},
                              {"/api/x": _r({"topo": {"saldo_centavos": 250, "nome": "Obra"}})})
    assert linhas == ["/api/x: 1 diferença(s)", "  topo.saldo_centavos: 100 → 250"]


def test_campo_que_apareceu_e_campo_que_sumiu():
    achadas = retrato.diferencas({"a": 1, "velho": "x"}, {"a": 1, "novo": [1]})
    assert achadas == [("novo", retrato.AUSENTE, [1]), ("velho", "x", retrato.AUSENTE)]
    linhas = retrato.comparar({"/api/x": _r({"a": 1, "velho": "x"})}, {"/api/x": _r({"a": 1, "novo": [1]})})
    assert linhas[1:] == ["  novo: (não tem) → [1]", '  velho: "x" → (não tem)']


def test_lista_de_registros_e_casada_pelo_id():
    antes = [{"id": 1, "estado": "protocolada"}, {"id": 2, "estado": "protocolada"}]
    depois = [{"id": 2, "estado": "recebida"}, {"id": 3, "estado": "nova"}]
    assert retrato.diferencas(antes, depois, caminho="medicoes") == [
        ("medicoes[id=1]", {"id": 1, "estado": "protocolada"}, retrato.AUSENTE),
        ("medicoes[id=2].estado", "protocolada", "recebida"),
        ("medicoes[id=3]", retrato.AUSENTE, {"id": 3, "estado": "nova"}),
    ]


def test_mesmos_registros_em_outra_ordem_e_mudanca():
    antes = [{"id": 1}, {"id": 2}, {"id": 3}]
    assert retrato.diferencas(antes, [{"id": 3}, {"id": 1}, {"id": 2}]) == [("[ordem]", [1, 2, 3], [3, 1, 2])]
    # registro novo no meio nao e' troca de ordem dos que ja' existiam
    assert retrato.diferencas(antes, [{"id": 1}, {"id": 9}, {"id": 2}, {"id": 3}]) == [
        ("[id=9]", retrato.AUSENTE, {"id": 9})]


def test_lista_sem_id_ou_com_id_repetido_e_comparada_por_posicao():
    assert retrato.diferencas([1, 2, 3], [1, 5]) == [("[1]", 2, 5), ("[2]", 3, retrato.AUSENTE)]
    repetido = [{"id": 1, "v": 1}, {"id": 1, "v": 2}]
    assert retrato.diferencas(repetido, [{"id": 1, "v": 1}, {"id": 1, "v": 3}]) == [("[1].v", 2, 3)]


def test_lista_vazia_contra_lista_com_registros():
    assert retrato.diferencas([], [{"id": 7, "v": 1}], caminho="notas") == [
        ("notas[id=7]", retrato.AUSENTE, {"id": 7, "v": 1})]
    assert retrato.diferencas([], []) == []


def test_tipo_diferente_e_mudanca_mas_inteiro_e_decimal_iguais_nao():
    assert retrato.diferencas({"v": 1}, {"v": 1.0}) == []
    assert retrato.diferencas({"v": 1}, {"v": True}) == [("v", 1, True)]
    assert retrato.diferencas({"v": None}, {"v": 0}) == [("v", None, 0)]
    assert retrato.diferencas({"v": {"a": 1}}, {"v": [1]}) == [("v", {"a": 1}, [1])]


def test_status_que_mudou_e_rota_que_so_existe_num_dos_lados():
    antes = {"/api/a": _r({"x": 1}), "/api/b": _r({"detail": "não achou"}, 404), "/api/so-antes": _r([])}
    depois = {"/api/a": _r({"x": 1}), "/api/b": _r({"ok": True}), "/api/so-depois": _r([], 500)}
    assert retrato.comparar(antes, depois) == [
        "/api/b: status 404 → 200",
        '  detail: "não achou" → (não tem)',
        "  ok: (não tem) → true",
        "/api/so-antes: só no antes (status 200)",
        "/api/so-depois: só no depois (status 500)",
    ]


def test_campo_ignorado_nao_conta_em_nenhuma_profundidade():
    antes = {"/api/x": _r({"hoje": "2026-01-01", "itens": [{"id": 1, "hoje": "a", "v": 1}]})}
    depois = {"/api/x": _r({"hoje": "2026-01-02", "itens": [{"id": 1, "hoje": "b", "v": 1}]})}
    assert retrato.comparar(antes, depois, ignorar={"hoje"}) == []
    assert len(retrato.comparar(antes, depois)) == 3


def test_limite_corta_a_lista_e_diz_quantas_ficaram_de_fora():
    antes = {"/api/x": _r({f"c{i:02d}": 0 for i in range(10)})}
    depois = {"/api/x": _r({f"c{i:02d}": 1 for i in range(10)})}
    linhas = retrato.comparar(antes, depois, limite=3)
    assert linhas[0] == "/api/x: 10 diferença(s)"
    assert linhas[1:4] == ["  c00: 0 → 1", "  c01: 0 → 1", "  c02: 0 → 1"]
    assert linhas[4] == "  … e mais 7 (use --limite para ver)"


def test_valor_comprido_e_cortado_na_linha():
    linhas = retrato.comparar({"/api/x": _r({"t": "a" * 500})}, {"/api/x": _r({"t": "b"})})
    assert len(linhas[1]) < 130 and "…" in linhas[1]


# --- rotas do retrato -------------------------------------------------------------------------------------------

@pytest.fixture
def rotas_get_do_backend(client):
    return {caminho for caminho, verbos in client.app.openapi()["paths"].items()
            if "get" in verbos and caminho.startswith("/api/")}


def test_toda_rota_do_retrato_existe_no_backend(rotas_get_do_backend):
    de_verdade = {retrato.forma(r) for r in rotas_get_do_backend}
    sumiram = [r for r in (*retrato.ROTAS, *retrato.FORA) if retrato.forma(r) not in de_verdade]
    assert sumiram == [], "rota que saiu do backend continua em scripts/prova/retrato.py (ROTAS ou FORA)"


def test_toda_rota_de_leitura_do_backend_esta_no_retrato_ou_fora_com_motivo(rotas_get_do_backend):
    no_retrato = {retrato.forma(r) for r in retrato.ROTAS}
    fora = {retrato.forma(r) for r in retrato.FORA}
    sem_decisao = sorted(r for r in rotas_get_do_backend if retrato.forma(r) not in no_retrato | fora)
    assert sem_decisao == [], ("rota GET nova: ponha em ROTAS (entra no retrato antes/depois) ou em FORA, com o "
                               "motivo, em scripts/prova/retrato.py")
    assert no_retrato & fora == set()
    assert all(isinstance(m, str) and m.strip() for m in retrato.FORA.values())


def test_cada_rota_do_retrato_tem_no_maximo_um_marcador_com_fonte():
    assert len(set(retrato.ROTAS)) == len(retrato.ROTAS)
    for rota in retrato.ROTAS:
        m = retrato.marcador(rota)
        assert m is None or m in retrato.FONTES, rota
    for fontes in retrato.FONTES.values():
        for rota, _ in fontes:
            assert rota in retrato.ROTAS, f"a fonte {rota} tambem precisa estar no retrato"
    with pytest.raises(ValueError):
        retrato.marcador("/api/medicoes/{medicao}/planilhas/{planilha}")


def test_ids_saem_da_api_e_as_rotas_sao_abertas_uma_por_registro():
    respostas = {
        "/api/contratos": [{"id": 1}, {"id": 2}],
        "/api/contratos/1/medicoes": [],
        "/api/contratos/2/medicoes": [{"id": 5}, {"id": 4}],
        "/api/contratos/2/protocolos": {"protocolos": [{"id": 9}]},
        "/api/contratos/1/reajuste": {"pleitos": [{"id": 3}]},
        "/api/contratos/2/prazos": {"pleitos": [{"id": 3}, {"id": 8}]},
        "/api/contratos/1/espelho": {"detail": "sem regra"},
    }
    pedidas = []

    def ler(rota):
        pedidas.append(rota)
        return {"status": 200, "corpo": respostas.get(rota, {})}

    ids = retrato.ids_dos_marcadores(ler)
    assert ids == {"contrato": [1, 2], "medicao": [4, 5], "protocolo": [9], "pleito": [3, 8], "espelho": []}
    caminhos = retrato.rotas_do_retrato(ids)
    assert "/api/contratos/1/ficha" in caminhos and "/api/contratos/2/ficha" in caminhos
    assert [c for c in caminhos if c.startswith("/api/medicoes/") and c.endswith("/par")] == [
        "/api/medicoes/4/par", "/api/medicoes/5/par"]
    assert "/api/pleitos/8" in caminhos and "/api/inicio" in caminhos
    assert not [c for c in caminhos if "{" in c]
    assert len(set(caminhos)) == len(caminhos)
    # --contrato restringe as obras e o que depende delas
    so_um = retrato.ids_dos_marcadores(ler, contratos=[1])
    assert so_um["contrato"] == [1] and so_um["medicao"] == [] and so_um["pleito"] == [3]


def test_nome_do_arquivo_de_cada_rota_e_unico_e_sem_barra():
    caminhos = retrato.rotas_do_retrato({"contrato": [1, 12], "medicao": [1], "protocolo": [1], "pleito": [1],
                                         "espelho": [1]})
    nomes = [retrato.arquivo_da_rota(c) for c in caminhos]
    assert len(set(nomes)) == len(nomes)
    assert all("/" not in n and n.endswith(".json") for n in nomes)
    assert retrato.arquivo_da_rota("/api/contratos/2/medicoes") == "api__contratos__2__medicoes.json"


def test_rotulo_simples_fica_na_saida_e_caminho_e_usado_como_esta(tmp_path):
    assert retrato.pasta_do_retrato(tmp_path, "antes") == tmp_path / "retrato" / "antes"
    assert retrato.pasta_do_retrato(tmp_path, str(tmp_path / "outra" / "pasta")) == (tmp_path / "outra" / "pasta").resolve()
