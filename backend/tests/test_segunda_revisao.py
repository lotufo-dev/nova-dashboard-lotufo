"""scripts/segunda_revisao.py (issue #709): PR que toca dinheiro, envio ou banco exige o item "Segunda revisao
independente" marcado e preenchido no corpo; PR que nao toca passa sem o item; base que nao e' o master so' avisa."""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "segunda_revisao.py"

_spec = importlib.util.spec_from_file_location("segunda_revisao", SCRIPT)
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)

MODELO = (RAIZ / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
LINHA_DO_MODELO = next(linha for linha in MODELO.splitlines() if "Segunda revisão" in linha)

SEM_ITEM = "## O que mudou\n\nCorrige a soma.\n\n## Conferência\n\n- [x] Suíte verde: 10 testes\n"
ITEM_VAZIO = MODELO.replace("- [ ] Segunda revisão", "- [x] Segunda revisão")
ITEM_PREENCHIDO = MODELO.replace(
    LINHA_DO_MODELO, LINHA_DO_MODELO.replace("- [ ]", "- [x]") + "um agente separado, só com o diff; sem achados.")

TOCA = ["README.md", "backend/app/medicoes.py"]
NAO_TOCA = ["README.md", "backend/app/saude_x.py", "frontend/src/Admin.test.tsx"]


@pytest.fixture(scope="module")
def padroes():
    return sr.ler_padroes()


# --- caminhos lidos das regras -----------------------------------------------------------------------------------

def test_os_caminhos_saem_dos_tres_arquivos_de_regra(padroes):
    assert set(padroes) == {"dinheiro", "envio", "banco"}
    for area, rel in sr.REGRAS.items():
        texto = (RAIZ / rel).read_text(encoding="utf-8")
        assert padroes[area], area
        for caminho in padroes[area]:
            assert f'- "{caminho}"' in texto


def test_o_script_nao_guarda_copia_dos_caminhos(padroes):
    fonte = SCRIPT.read_text(encoding="utf-8")
    for caminho in {c for lista in padroes.values() for c in lista}:
        assert caminho not in fonte, caminho


def test_cabecalho_de_regra_com_e_sem_lista():
    texto = '---\npaths:\n  - "a/b.py"\n  - c/**\noutra: 1\n  - "nao/conta.py"\n---\n\n# Titulo\n  - "corpo/nao.py"\n'
    assert sr.caminhos_da_regra(texto) == ["a/b.py", "c/**"]
    assert sr.caminhos_da_regra("# Regra sem cabeçalho\n") == []


@pytest.mark.parametrize("arquivo, area", [
    ("backend/app/medicoes.py", "dinheiro"),
    ("backend/app/notas_fiscais_x.py", "dinheiro"),      # backend/app/notas*.py
    ("frontend/src/MedicaoPagina.tsx", "dinheiro"),      # frontend/src/Medic*.tsx
    ("backend/app/inicio.py", "dinheiro"),               # somas que a diretoria le
    ("backend/app/fechamento.py", "dinheiro"),
    ("backend/app/correio.py", "envio"),
    ("backend/migrations/999_nova.sql", "banco"),        # backend/migrations/**
    ("cadastro-exemplo/orgaos/alfa/orgao.yaml", "banco"),  # cadastro-exemplo/**, com subpasta
    ("backend\\app\\db.py", "banco"),                    # barra do Windows
])
def test_arquivo_das_areas_e_reconhecido(padroes, arquivo, area):
    assert area in {a for _, a, _ in sr.tocados([arquivo], padroes)}


@pytest.mark.parametrize("arquivo", [
    "backend/app/saude_x.py", "backend/tests/test_medicoes.py", "backend/app/sub/notas.py", "docs/medicoes.py",
    "frontend/src/Admin.tsx", "frontend/src/sub/Medicoes.tsx", "scripts/segunda_revisao.py", "README.md", "",
])
def test_arquivo_de_fora_das_areas_nao_e_reconhecido(padroes, arquivo):
    assert sr.tocados([arquivo], padroes) == []


def test_arquivo_em_duas_areas_aparece_nas_duas(padroes):
    # protocolo.py esta' nas regras de dinheiro e de envio
    assert {a for _, a, _ in sr.tocados(["backend/app/protocolo.py"], padroes)} == {"dinheiro", "envio"}


# --- item no corpo -----------------------------------------------------------------------------------------------

def test_o_modelo_de_pr_tem_o_item_que_o_script_procura():
    assert sr.item_da_revisao(MODELO) == ("desmarcado", "")


@pytest.mark.parametrize("corpo, estado", [
    (SEM_ITEM, "ausente"),
    ("", "ausente"),
    (None, "ausente"),
    (MODELO, "desmarcado"),
    (ITEM_VAZIO, "vazio"),
    (ITEM_PREENCHIDO, "ok"),
    # formas que as PRs ja' usaram: sem a chamada "quem revisou e o que achou", e com o item encurtado
    ("- [x] Segunda revisão independente, por quem não escreveu o código (obrigatória quando a PR toca dinheiro, "
     "envio ou banco): um agente separado, que recebeu só o diff. Não achou defeito.", "ok"),
    ("- [x] Segunda revisão independente: feita por um revisor que não escreveu o código. Pode entrar.", "ok"),
    ("* [X] segunda revisao independente: revisor externo, sem achados\r\n", "ok"),
    # texto nas linhas recuadas logo abaixo do item
    ("- [x] Segunda revisão independente: quem revisou e o que achou:\n  - agente separado: sem achados\n", "ok"),
    ("- [x] Segunda revisão independente: quem revisou e o que achou:\n\n- [x] O que não foi conferido: nada\n", "vazio"),
    # preenchido mas desmarcado, marcado sem dois-pontos, e so' pontuacao
    ("- [ ] Segunda revisão independente: agente separado, sem achados", "desmarcado"),
    ("- [x] Segunda revisão independente feita", "vazio"),
    ("- [x] Segunda revisão independente: —", "vazio"),
    ("- [x] Segunda revisão independente: não se aplica, só muda um teste.", "nao_se_aplica"),
    ("- [x] Segunda revisão independente: quem revisou e o que achou: N/A", "nao_se_aplica"),
    # item dentro de comentario HTML nao conta; fora de caixa de marcar tambem nao
    ("<!-- - [x] Segunda revisão independente: agente separado -->", "ausente"),
    ("Segunda revisão independente: agente separado, sem achados", "ausente"),
])
def test_estado_do_item_no_corpo(corpo, estado):
    assert sr.item_da_revisao(corpo)[0] == estado


def test_o_texto_do_item_volta_sem_a_chamada_do_modelo():
    assert sr.item_da_revisao(ITEM_PREENCHIDO) == ("ok", "um agente separado, só com o diff; sem achados.")


# --- a regra: tres corpos, PR que toca e que nao toca ------------------------------------------------------------

@pytest.mark.parametrize("corpo, falta", [
    (SEM_ITEM, "não tem o item"),
    (ITEM_VAZIO, "sem texto depois dos dois-pontos"),
    (MODELO, "está desmarcado"),
])
def test_pr_que_toca_sem_a_revisao_falha_com_mensagem_em_portugues(padroes, corpo, falta):
    passa, linhas = sr.conferir(TOCA, corpo, padroes)
    mensagem = "\n".join(linhas)
    assert not passa
    assert "Esta PR toca dinheiro" in linhas[0] and falta in linhas[0]
    assert "backend/app/medicoes.py  (dinheiro: backend/app/medicoes.py)" in mensagem
    assert "README.md" not in mensagem
    assert "quem revisou e o que achou" in mensagem


def test_pr_que_toca_com_a_revisao_preenchida_passa(padroes):
    passa, linhas = sr.conferir(TOCA, ITEM_PREENCHIDO, padroes)
    assert passa and "está registrada" in linhas[0]


@pytest.mark.parametrize("corpo", [SEM_ITEM, ITEM_VAZIO, ITEM_PREENCHIDO, MODELO, ""])
def test_pr_que_nao_toca_passa_sem_exigir_o_item(padroes, corpo):
    passa, linhas = sr.conferir(NAO_TOCA, corpo, padroes)
    assert passa and "não é exigida" in linhas[0]


# --- linha de comando --------------------------------------------------------------------------------------------

def _rodar(tmp_path, arquivos, corpo, *extras, na_ci=False):
    # a suite roda dentro da CI: GITHUB_ACTIONS sai do ambiente, e so' entra quando o teste pede
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
    if na_ci:
        env["GITHUB_ACTIONS"] = "true"
    (tmp_path / "arquivos.txt").write_text("\n".join(arquivos) + "\n", encoding="utf-8")
    (tmp_path / "corpo.md").write_text(corpo, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--arquivos", str(tmp_path / "arquivos.txt"), "--corpo", str(tmp_path / "corpo.md"),
         *extras], capture_output=True, text=True, encoding="utf-8", env=env)


@pytest.mark.parametrize("arquivos, corpo, codigo", [
    (TOCA, SEM_ITEM, 1), (TOCA, ITEM_VAZIO, 1), (TOCA, ITEM_PREENCHIDO, 0),
    (NAO_TOCA, SEM_ITEM, 0), (NAO_TOCA, ITEM_VAZIO, 0), (NAO_TOCA, ITEM_PREENCHIDO, 0),
])
def test_codigo_de_saida(tmp_path, arquivos, corpo, codigo):
    r = _rodar(tmp_path, arquivos, corpo)
    assert r.returncode == codigo, r.stdout + r.stderr
    assert ("ERRO: Esta PR toca dinheiro" in r.stdout) == (codigo == 1)


def test_base_que_nao_e_o_master_so_avisa(tmp_path):
    r = _rodar(tmp_path, TOCA, SEM_ITEM, "--so-avisa")
    assert r.returncode == 0
    assert r.stdout.startswith("AVISO: Esta PR toca dinheiro") and "backend/app/medicoes.py" in r.stdout
    assert "A base desta PR não é o master" in r.stdout and "reexecute" not in r.stdout


def test_na_ci_a_falha_vira_anotacao_de_erro(tmp_path):
    r = _rodar(tmp_path, TOCA, SEM_ITEM, na_ci=True)
    assert r.returncode == 1 and r.stdout.startswith("::error::Esta PR toca dinheiro")


def test_corpo_que_nao_existe_e_erro_de_uso(tmp_path):
    (tmp_path / "arquivos.txt").write_text("README.md\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--arquivos", str(tmp_path / "arquivos.txt"),
                        "--corpo", str(tmp_path / "nao-existe.md")], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 2 and "não consegui ler" in r.stderr


# --- com git de verdade: os arquivos saem de `git diff base...HEAD` ------------------------------------------------

@pytest.fixture
def copia(tmp_path):
    """Repositorio de mentira com o script e as regras, e uma branch `pr` saindo de `master`."""
    git = shutil.which("git")
    if not git:
        pytest.skip("precisa de git")
    pasta = tmp_path / "repo"
    for rel in ["scripts/segunda_revisao.py", *sr.REGRAS.values()]:
        destino = pasta / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(RAIZ / rel, destino)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Teste", "GIT_AUTHOR_EMAIL": "teste@exemplo.com.br",
           "GIT_COMMITTER_NAME": "Teste", "GIT_COMMITTER_EMAIL": "teste@exemplo.com.br"}
    for herdada in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GITHUB_ACTIONS"):
        env.pop(herdada, None)

    def rodar(*args):
        r = subprocess.run([git, *args], cwd=pasta, env=env, capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr
        return r

    def conferir(corpo, *extras):
        (tmp_path / "corpo.md").write_text(corpo, encoding="utf-8")
        return subprocess.run([sys.executable, "scripts/segunda_revisao.py", "--base", "master",
                               "--corpo", str(tmp_path / "corpo.md"), *extras],
                              cwd=pasta, env=env, capture_output=True, text=True, encoding="utf-8")

    def commit(rel, texto, assunto):
        arquivo = pasta / rel
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(texto, encoding="utf-8")
        rodar("add", "-A")
        rodar("commit", "-q", "--no-verify", "-m", assunto)

    rodar("init", "-q", "-b", "master")
    rodar("config", "commit.gpgsign", "false")
    commit("backend/app/medicoes.py", "x = 1\n", "chore: commit inicial")
    rodar("switch", "-q", "-c", "pr")
    return pasta, commit, conferir, rodar


def test_com_git_pr_que_nao_toca_passa_e_a_que_toca_exige(copia):
    _, commit, conferir, _ = copia
    commit("docs/nota.md", "texto\n", "docs: nota")
    assert conferir(SEM_ITEM).returncode == 0
    commit("backend/app/medicoes.py", "x = 2\n", "fix: soma")
    r = conferir(SEM_ITEM)
    assert r.returncode == 1 and "backend/app/medicoes.py" in r.stdout and "docs/nota.md" not in r.stdout
    assert conferir(ITEM_VAZIO).returncode == 1
    assert conferir(ITEM_PREENCHIDO).returncode == 0
    assert conferir(SEM_ITEM, "--so-avisa").returncode == 0


def test_com_git_o_que_entrou_no_master_depois_nao_conta_como_da_pr(copia):
    _, commit, conferir, rodar = copia
    commit("docs/nota.md", "texto\n", "docs: nota")
    rodar("switch", "-q", "master")
    commit("backend/app/db.py", "y = 1\n", "feat: banco anda no master")
    rodar("switch", "-q", "pr")
    assert conferir(SEM_ITEM).returncode == 0


def test_com_git_tirar_o_caminho_da_regra_na_mesma_pr_nao_dispensa(copia):
    pasta, commit, conferir, _ = copia
    regra = pasta / sr.REGRAS["dinheiro"]
    sem = regra.read_text(encoding="utf-8").replace('  - "backend/app/medicoes.py"\n', "")
    commit(sr.REGRAS["dinheiro"], sem, "docs: regra de dinheiro sem o medicoes")
    commit("backend/app/medicoes.py", "x = 3\n", "fix: soma")
    r = conferir(SEM_ITEM)
    assert r.returncode == 1 and "backend/app/medicoes.py" in r.stdout


def test_com_git_base_que_nao_existe_e_erro(copia):
    pasta, _, _, _ = copia
    r = subprocess.run([sys.executable, "scripts/segunda_revisao.py", "--base", "origin/nao-existe", "--corpo", "-"],
                       cwd=pasta, input="", capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 2 and "segunda_revisao:" in r.stderr
