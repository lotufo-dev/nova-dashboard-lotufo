"""Roteiros de prova (scripts/prova, issue #702): as recusas do ambiente, o ambiente do servidor de prova, o
comparador do retrato e as listas de rotas do retrato conferidas contra as rotas de verdade do backend."""
import os
import shutil
import socket
import sqlite3
import subprocess
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


# --- recusas: banco de uma instalacao e banco com contratos sem `--copia` ----------------------------------------

def _instalacao(pasta):
    """Uma pasta montada como a da producao: `dados/dashboard.db` e `segredos/instalacao.json`."""
    (pasta / "dados").mkdir(parents=True)
    (pasta / "segredos").mkdir()
    (pasta / "segredos" / "instalacao.json").write_text("{}", encoding="utf-8")
    return pasta / "dados" / "dashboard.db"


def _banco(caminho, contratos=0, usuarios=()):
    """Um banco SQLite so' com o que a guarda le: a tabela de contratos e a de usuarios."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho)
    conn.execute("CREATE TABLE contratos (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, email TEXT)")
    conn.executemany("INSERT INTO contratos DEFAULT VALUES", [()] * contratos)
    conn.executemany("INSERT INTO usuarios (email) VALUES (?)", [(u,) for u in usuarios])
    conn.commit()
    conn.close()
    return caminho


USUARIOS_DE_TESTE = [comum.email_de_teste(p) for p in comum.PERFIS]


def test_banco_de_uma_instalacao_e_recusado_exista_ou_nao_o_arquivo(repo):
    raiz, fora = repo
    banco = _instalacao(fora / "Dashboard")
    for alvo in (banco, banco.with_name("outro.db")):       # o banco ainda nem existe, ou e' outro arquivo da pasta
        with pytest.raises(comum.Recusa, match="banco de uma instalação") as e:
            comum.banco_de_prova({"DASH_DB_PATH": str(alvo)}, raiz)
        assert "Copie o arquivo do banco" in str(e.value)
    _banco(banco, contratos=2)
    with pytest.raises(comum.Recusa, match="banco de uma instalação"):
        comum.banco_de_prova({"DASH_DB_PATH": "Dashboard/dados/dashboard.db"}, raiz, base=fora)    # relativo


def test_pasta_com_cara_de_producao_mas_sem_o_arquivo_da_instalacao_passa(repo):
    raiz, fora = repo
    banco = fora / "Dashboard" / "dados" / "dashboard.db"
    (fora / "Dashboard" / "segredos").mkdir(parents=True)     # a pasta existe, o arquivo da instalacao nao
    assert comum.banco_de_prova({"DASH_DB_PATH": str(banco)}, raiz) == banco.resolve()


def test_terminal_com_a_variavel_da_instalacao_recusa(repo):
    raiz, fora = repo
    arquivo = fora / "outro-lugar" / "instalacao.json"
    ambiente = {"DASH_DB_PATH": str(fora / "prova.db"), "DASH_INSTALACAO_ARQUIVO": str(arquivo)}
    assert comum.banco_de_prova(ambiente, raiz) == (fora / "prova.db").resolve()     # aponta para o que nao existe
    arquivo.parent.mkdir()
    arquivo.write_text("{}", encoding="utf-8")
    with pytest.raises(comum.Recusa, match="DASH_INSTALACAO_ARQUIVO"):
        comum.banco_de_prova(ambiente, raiz)


def test_o_marcador_da_instalacao_e_o_mesmo_arquivo_que_o_backend_le(monkeypatch, tmp_path):
    """`comum.py` roda sem as dependencias do backend e por isso repete a regra de `instalacao.caminho_arquivo`.
    Se a regra de la' mudar, este teste reprova e a guarda da prova muda junto."""
    from app import instalacao
    banco = tmp_path / "Dashboard" / "dados" / "dashboard.db"
    monkeypatch.setenv("DASH_DB_PATH", str(banco))
    monkeypatch.delenv("DASH_INSTALACAO_ARQUIVO", raising=False)
    assert instalacao.caminho_arquivo() == comum.marcador_de_instalacao(banco)
    assert comum.marcador_de_instalacao(banco) == tmp_path / "Dashboard" / "segredos" / "instalacao.json"
    # o nome da variavel tambem e' o mesmo dos dois lados: o backend le o arquivo que ela aponta, e a prova recusa
    arquivo = tmp_path / "outro-lugar" / "instalacao.json"
    arquivo.parent.mkdir()
    arquivo.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DASH_INSTALACAO_ARQUIVO", str(arquivo))
    assert instalacao.caminho_arquivo() == arquivo
    with pytest.raises(comum.Recusa, match="DASH_INSTALACAO_ARQUIVO"):
        comum.banco_de_prova(dict(os.environ))


def _link(link, destino, pasta=False):
    try:
        link.symlink_to(destino, target_is_directory=pasta)
    except (OSError, NotImplementedError):
        pytest.skip("este sistema não deixa criar link simbólico (Windows sem a permissão)")


def test_pasta_de_dados_que_e_link_para_outro_disco_continua_sendo_da_instalacao(repo):
    """O backend procura `segredos/instalacao.json` a partir do caminho como esta' escrito em DASH_DB_PATH; a
    guarda resolvia o link antes e procurava ao lado do destino, onde o arquivo nao esta'."""
    raiz, fora = repo
    _banco(fora / "outro-disco" / "dados" / "dashboard.db", contratos=2)
    (fora / "Dashboard" / "segredos").mkdir(parents=True)
    (fora / "Dashboard" / "segredos" / "instalacao.json").write_text("{}", encoding="utf-8")
    _link(fora / "Dashboard" / "dados", fora / "outro-disco" / "dados", pasta=True)
    escrito = fora / "Dashboard" / "dados" / "dashboard.db"
    assert not comum.marcador_de_instalacao(escrito.resolve()).exists()      # ao lado do destino nao ha' nada
    for ambiente, base in (({"DASH_DB_PATH": str(escrito)}, None),
                           ({"DASH_DB_PATH": "Dashboard/dados/dashboard.db"}, fora)):
        with pytest.raises(comum.Recusa, match="banco de uma instalação"):
            comum.banco_de_prova(ambiente, raiz, base)
    # sem o arquivo da instalacao, o mesmo link e' so' um caminho: passa e devolve o banco resolvido
    (fora / "Dashboard" / "segredos" / "instalacao.json").unlink()
    assert comum.banco_de_prova({"DASH_DB_PATH": str(escrito)}, raiz) == escrito.resolve()


def test_link_de_fora_para_o_banco_da_instalacao_tambem_e_recusado(repo):
    raiz, fora = repo
    banco = _banco(_instalacao(fora / "Dashboard"), contratos=2)
    (fora / "temp").mkdir()
    _link(fora / "temp" / "atalho.db", banco)
    with pytest.raises(comum.Recusa, match="banco de uma instalação"):
        comum.banco_de_prova({"DASH_DB_PATH": str(fora / "temp" / "atalho.db")}, raiz)


def test_banco_com_contratos_so_com_copia_explicita(repo):
    _, fora = repo
    banco = _banco(fora / "copia.db", contratos=3)
    with pytest.raises(comum.Recusa, match="--copia") as e:
        comum.conferir_copia(banco, False)
    assert "administrador" in str(e.value)
    assert comum.conferir_copia(banco, True) == "copia"
    # com um usuario de teste so' ainda falta criar conta: continua pedindo
    faltando = _banco(fora / "meia.db", contratos=1, usuarios=USUARIOS_DE_TESTE[:1])
    with pytest.raises(comum.Recusa, match="--copia"):
        comum.conferir_copia(faltando, False)


def test_banco_novo_vazio_ou_ja_preparado_nao_pede_copia(repo):
    _, fora = repo
    assert comum.conferir_copia(fora / "novo.db", False) == "novo"
    (fora / "zero.db").write_bytes(b"")
    assert comum.conferir_copia(fora / "zero.db", False) == "vazio"
    assert comum.conferir_copia(_banco(fora / "sem-contrato.db"), False) == "vazio"
    # a prova ja' rodou nele (os tres usuarios de teste existem): subir de novo nao cria conta nenhuma
    preparado = _banco(fora / "preparado.db", contratos=2, usuarios=[*USUARIOS_DE_TESTE, "alguem@exemplo.com.br"])
    assert comum.conferir_copia(preparado, False) == "preparado"
    assert comum.estado_do_banco(preparado) == {"contratos": 2, "usuarios_de_teste": sorted(USUARIOS_DE_TESTE)}


def test_copia_pedida_sobre_arquivo_que_nao_existe_ou_nao_e_banco_recusa(repo):
    _, fora = repo
    with pytest.raises(comum.Recusa, match="não há arquivo"):
        comum.conferir_copia(fora / "caminho-errado.db", True)
    (fora / "lixo.db").write_text("isto não é um banco " * 200, encoding="utf-8")
    for copia in (False, True):
        with pytest.raises(comum.Recusa, match="não abre como banco SQLite"):
            comum.conferir_copia(fora / "lixo.db", copia)


def _nada_nasceu_ao_lado(banco):
    return sorted(p.name for p in banco.parent.iterdir() if p.name.startswith("prova-") or p.name == "correio-simulado")


def test_servidor_recusa_banco_de_instalacao_e_banco_com_contratos_antes_de_gravar(tmp_path):
    cadastro = str(comum.CADASTRO_EXEMPLO)
    producao = _banco(_instalacao(tmp_path / "Dashboard"), contratos=2)
    copia = _banco(tmp_path / "temp" / "copia.db", contratos=2)
    antes = {b: b.read_bytes() for b in (producao, copia)}
    for banco, com_copia, frase in ((producao, False, "banco de uma instalação"),
                                    (producao, True, "banco de uma instalação"),     # --copia nao abre a producao
                                    (copia, False, "--copia")):
        with pytest.raises(comum.Recusa, match=frase):
            servidor.subir({"DASH_DB_PATH": str(banco), "DASH_CADASTRO_DIR": cadastro}, com_frontend=False,
                           copia=com_copia)
        assert banco.read_bytes() == antes[banco]
        assert _nada_nasceu_ao_lado(banco) == []        # nem a senha de teste


@pytest.mark.parametrize("onde, argumentos, frase", [
    ("instalacao", [], "banco de uma instalação"),
    ("instalacao", ["--copia"], "banco de uma instalação"),
    ("copia", [], "--copia"),
])
def test_semear_chamado_direto_nao_e_atalho_para_criar_conta(tmp_path, onde, argumentos, frase):
    """`semear.py` e' quem cria os usuarios de teste: as recusas valem nele tambem, antes de abrir o banco."""
    banco = _instalacao(tmp_path / "Dashboard") if onde == "instalacao" else tmp_path / "temp" / "copia.db"
    _banco(banco, contratos=2)
    antes = banco.read_bytes()
    senha = tmp_path / "senha.txt"
    servidor.garantir_senha(senha)
    env = comum.ambiente_do_servidor(os.environ, banco, comum.CADASTRO_EXEMPLO, None)
    env["PYTHONPATH"] = str(comum.BACKEND)
    feito = subprocess.run([sys.executable, str(RAIZ / "scripts" / "prova" / "semear.py"), str(senha), *argumentos],
                           cwd=comum.BACKEND, env=env, capture_output=True, text=True, encoding="utf-8")
    assert feito.returncode != 0
    assert "RECUSADO" in feito.stderr and frase in feito.stderr
    assert banco.read_bytes() == antes
    conn = sqlite3.connect(banco)
    assert conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0
    conn.close()


def test_porta_pedida_ja_ocupada_recusa_sem_preparar_o_banco(tmp_path):
    banco = tmp_path / "prova.db"
    ambiente = {"DASH_DB_PATH": str(banco), "DASH_CADASTRO_DIR": str(comum.CADASTRO_EXEMPLO)}
    with socket.socket() as outro:                       # outra dashboard ja' escutando na porta pedida
        outro.bind(("127.0.0.1", 0))
        outro.listen()
        porta = outro.getsockname()[1]
        assert servidor.porta_ocupada(porta) is True
        with pytest.raises(comum.Recusa, match=f"porta {porta} já está em uso"):
            servidor.subir(ambiente, porta=porta, com_frontend=False)
    assert not banco.exists() and _nada_nasceu_ao_lado(banco) == []
    assert servidor.porta_ocupada(porta) is False        # liberada, a mesma porta serve


def test_porta_de_servidor_que_atendeu_e_caiu_esta_livre_na_hora():
    """O fluxo do retrato: tirar "antes", derrubar o servidor de prova e subir de novo na mesma `--porta`. A
    conexao atendida e fechada segura a porta no sistema por uns 30 s para quem tenta um `bind` simples; quem
    decide e' a pergunta que importa (alguem responde nesta porta?), e ninguem responde."""
    servidor_que_caiu = socket.socket()
    servidor_que_caiu.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)     # como o uvicorn abre a porta
    servidor_que_caiu.bind(("127.0.0.1", 0))
    servidor_que_caiu.listen()
    porta = servidor_que_caiu.getsockname()[1]
    with socket.create_connection(("127.0.0.1", porta)) as cliente:
        atendida, _ = servidor_que_caiu.accept()
        assert servidor.porta_ocupada(porta) is True      # no ar e atendendo
        cliente.sendall(b"GET /api/health HTTP/1.0\r\n\r\n")
        atendida.recv(100)
        atendida.sendall(b"HTTP/1.0 200 OK\r\n\r\n")
        atendida.close()                                  # o servidor fecha primeiro, como ao ser derrubado
        cliente.recv(100)
    servidor_que_caiu.close()
    assert servidor.porta_ocupada(porta) is False
    servidor.exigir_porta_livre(porta)                    # nao recusa: a subida seguinte na mesma porta passa


def test_capturar_recusa_lista_vazia_de_perfis_ou_de_telas():
    """`--perfis ""` ou `--telas ""` com `--conferir` passava sem abrir tela nenhuma."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("sem Node nesta máquina")
    sem_prova = {k: v for k, v in os.environ.items() if not k.upper().startswith("DASH_")}   # recusa antes do banco
    for opcao in ("--perfis", "--telas"):
        feito = subprocess.run([node, str(RAIZ / "scripts" / "prova" / "capturar.mjs"), "--conferir", opcao, ""],
                               capture_output=True, text=True, encoding="utf-8", env=sem_prova)
        assert feito.returncode == 2, feito.stderr
        assert f"{opcao} veio vazio" in feito.stderr


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


def test_retrato_com_caminho_dentro_do_repositorio_so_na_pasta_ignorada(repo):
    """Rotulo com barra e' caminho: passa pela mesma recusa de `comum.saida_de_prova`."""
    raiz, fora = repo
    saida = fora / "prova-saida"
    for rotulo, base in (("docs/retrato-antes", raiz),                 # relativo, rodado na raiz do repositorio
                         (str(raiz / "docs" / "retrato-antes"), None),
                         ("../retrato-antes", raiz / "backend"),
                         (str(raiz) + "/", None)):
        with pytest.raises(comum.Recusa, match="dentro do repositório"):
            retrato.pasta_do_retrato(saida, rotulo, raiz, base)
    ignorada = raiz / comum.SAIDA_NO_REPOSITORIO / "retrato-antes"
    assert retrato.pasta_do_retrato(saida, f"{comum.SAIDA_NO_REPOSITORIO}/retrato-antes", raiz, raiz) == ignorada.resolve()
    assert retrato.pasta_do_retrato(saida, str(fora / "x" / "antes"), raiz) == (fora / "x" / "antes").resolve()
    assert retrato.pasta_do_retrato(saida, "../fora/antes", raiz, raiz) == (fora / "antes").resolve()


def test_retrato_no_repositorio_de_verdade_recusa_pasta_versionada(tmp_path):
    with pytest.raises(comum.Recusa, match="dentro do repositório"):
        retrato.pasta_do_retrato(tmp_path, str(RAIZ / "docs" / "retrato-antes"))


# --- as telas de ato da medicao escolhem a medicao pelo estado ---------------------------------------------------

def _atos_por_estado():
    """O que `ATOS_DA_MEDICAO` (telas.mjs) responde para uma linha de medicao em cada estado do servidor."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("sem Node nesta máquina")
    from app import medicoes
    estados = sorted(medicoes.TRANSICOES)
    roteiro = (
        "import { ATOS_DA_MEDICAO as A } from './scripts/prova/telas.mjs';"
        f"const e = {estados!r}; const s = {{}};"
        "for (const [ato, f] of Object.entries(A)) s[ato] = Object.fromEntries(e.map(x => [x, f({ estado: x })]));"
        "s.sem_protocolo = A.receber({ estado: 'nota_emitida', recebe_sem_protocolo: true });"
        "s.sem_passo_5 = A['protocolo-fora']({ estado: 'protocolada', passos: [1, 2, 3, 4, 6] });"
        "console.log(JSON.stringify(s));")
    feito = subprocess.run([node, "--input-type=module", "-e", roteiro], cwd=RAIZ, capture_output=True, text=True,
                           encoding="utf-8")
    assert feito.returncode == 0, feito.stderr
    import json
    return json.loads(feito.stdout)


def _proximos_da_pagina():
    """`PROXIMOS` de frontend/src/medicao.ts: estado -> destinos que a pagina oferece."""
    import re
    fonte = (RAIZ / "frontend" / "src" / "medicao.ts").read_text(encoding="utf-8")
    bloco = re.search(r"export const PROXIMOS[^=]*=\s*\{(.*?)\n\};", fonte, re.S).group(1)
    return {m[0]: re.findall(r'"(\w+)"', m[1]) for m in re.findall(r"(\w+):\s*\[([^\]]*)\]", bloco)}


def test_telas_de_ato_pedem_a_medicao_no_estado_que_a_pagina_aceita():
    atos = _atos_por_estado()
    proximos = _proximos_da_pagina()
    for estado in atos["cancelar"]:
        assert atos["cancelar"][estado] == ("cancelada" in proximos.get(estado, [])), estado
        assert atos["desistir"][estado] == ("desistida" in proximos.get(estado, [])), estado
        assert atos["receber"][estado] == ("recebida" in proximos.get(estado, [])), estado
    # a recebida, a cancelada e a desistida ja' foram encerradas: nenhum ato serve (o que reprovava na copia do banco)
    for estado in ("recebida", "cancelada", "desistida"):
        assert not any(atos[ato][estado] for ato in ("cancelar", "desistir", "receber", "protocolo-fora")), estado
    assert atos["sem_protocolo"] is True            # #743: nota emitida de obra sem o passo "Envio da nota" recebe
    assert {e for e, ok in atos["protocolo-fora"].items() if ok} == {"protocolada", "nf_emitida"}
    assert atos["sem_passo_5"] is False             # a obra sem o passo "Envio da nota" nao tem o botao
