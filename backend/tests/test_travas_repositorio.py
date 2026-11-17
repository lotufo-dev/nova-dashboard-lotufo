"""Travas do repositorio (issue #710): proibicoes que eram frase e passam a ser barradas sozinhas.
  1. Tabelas `arquivo_` (historico da deteccao antiga, .claude/rules/banco.md) nao sao lidas por `backend/app`.
  2. `.githooks/commit-msg` recusa assunto fora de `tipo: descricao` sem acento; commit de merge passa.
  3. `.claude/hooks/barrar-instalacao` barra `npm ci`, `npm install` e `pip install` dentro de worktree.
  4. `.claude/settings.json` nao tem regra `ask` e mantem a `deny` de force push (docs/adr/0014).
Os ganchos rodam de verdade (git e sh; o .ps1 roda onde houver pwsh, como na CI do Ubuntu)."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
APP = RAIZ / "backend" / "app"
MIGRACOES = RAIZ / "backend" / "migrations"
COMMIT_MSG = RAIZ / ".githooks" / "commit-msg"
HOOKS = RAIZ / ".claude" / "hooks"

SH = shutil.which("sh")
GIT = shutil.which("git")
PWSH = shutil.which("pwsh")


# --- 1. tabelas arquivo_ ---------------------------------------------------------------------------------------

def _tabelas_arquivo() -> set:
    """Os nomes saem das migracoes (RENAME TO / CREATE TABLE), para tabela nova com o prefixo entrar sozinha."""
    criacao = re.compile(r"(?:RENAME\s+TO|CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+[\"'`\[]?(arquivo_\w+)", re.I)
    achadas = set()
    for sql in MIGRACOES.glob("*.sql"):
        achadas.update(n.lower() for n in criacao.findall(sql.read_text(encoding="utf-8")))
    return achadas


def _citacoes(tabelas: set, pasta: Path) -> list:
    alvo = re.compile(r"(?<![\w])(" + "|".join(sorted(map(re.escape, tabelas))) + r")(?![\w])", re.I)
    achados = []
    for py in sorted(pasta.rglob("*.py")):
        for n, linha in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if alvo.search(linha):
                achados.append(f"{py.relative_to(pasta).as_posix()}:{n}: {linha.strip()}")
    return achados


def test_as_migracoes_tem_tabelas_arquivo_para_conferir():
    # sem isto, uma mudanca na forma das migracoes deixaria o teste abaixo passando sem conferir nada
    assert "arquivo_sugestoes" in _tabelas_arquivo()


def test_nenhum_modulo_do_app_cita_tabela_arquivo():
    achados = _citacoes(_tabelas_arquivo(), APP)
    assert achados == [], "tabela arquivo_ nao se le (.claude/rules/banco.md):\n" + "\n".join(achados)


def test_a_busca_de_tabela_arquivo_acha_a_citacao_e_ignora_nome_parecido(tmp_path):
    (tmp_path / "le.py").write_text('conn.execute("SELECT * FROM arquivo_sugestoes")\n', encoding="utf-8")
    (tmp_path / "parecido.py").write_text("arquivo_sugestoes_novo = arquivo_token(1)\n", encoding="utf-8")
    assert _citacoes({"arquivo_sugestoes"}, tmp_path) == ['le.py:1: conn.execute("SELECT * FROM arquivo_sugestoes")']


# --- 2. assunto de commit ----------------------------------------------------------------------------------------

def _git(pasta: Path, *args, check=True):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Teste", "GIT_AUTHOR_EMAIL": "teste@exemplo.com.br",
           "GIT_COMMITTER_NAME": "Teste", "GIT_COMMITTER_EMAIL": "teste@exemplo.com.br"}
    for herdada in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):   # o pre-commit do repositorio as define
        env.pop(herdada, None)
    r = subprocess.run([GIT, *args], cwd=pasta, env=env, capture_output=True, text=True, encoding="utf-8")
    if check:
        assert r.returncode == 0, r.stderr
    return r


@pytest.fixture
def repo(tmp_path):
    """Repositorio de mentira com o commit-msg do projeto ligado, e um commit inicial."""
    if not (SH and GIT):
        pytest.skip("precisa de git e sh")
    pasta = tmp_path / "repo"
    ganchos = tmp_path / "ganchos"
    pasta.mkdir()
    ganchos.mkdir()
    destino = ganchos / "commit-msg"
    shutil.copyfile(COMMIT_MSG, destino)
    destino.chmod(0o755)
    _git(pasta, "init", "-q", "-b", "principal")
    _git(pasta, "config", "core.hooksPath", str(ganchos))
    _git(pasta, "config", "commit.gpgsign", "false")
    (pasta / "a.txt").write_text("a\n", encoding="utf-8")
    _git(pasta, "add", "a.txt")
    _git(pasta, "commit", "-q", "-m", "chore: commit inicial")
    return pasta


def _commit(repo: Path, assunto: str):
    return _git(repo, "commit", "-q", "--allow-empty", "-m", assunto, check=False)


@pytest.mark.parametrize("assunto", [
    "feat: boletim aceita competencia de dois meses",
    "fix: nota cancelada sai do a receber",
    "docs: runbook explica a troca de porta",
    "test: cobre o reajuste sem indice",
    "chore: sobe a versao do ruff (#123)",
])
def test_commit_com_assunto_no_padrao_passa(repo, assunto):
    r = _commit(repo, assunto)
    assert r.returncode == 0, r.stderr
    assert _git(repo, "log", "-1", "--format=%s").stdout.strip() == assunto


@pytest.mark.parametrize("assunto", [
    "arruma a nota",                       # sem tipo
    "refactor: separa o link de rota",     # tipo fora da lista
    "Fix: nota cancelada",                 # tipo em maiuscula
    "fix:nota cancelada",                  # sem espaco depois dos dois-pontos
    "fix(notas): nota cancelada",          # escopo nao faz parte do padrao
    "fix: ",                               # sem descricao
])
def test_commit_com_assunto_fora_do_padrao_e_recusado_com_o_padrao_na_mensagem(repo, assunto):
    r = _commit(repo, assunto)
    assert r.returncode != 0
    assert "tipo: descricao" in r.stderr and "feat, fix, docs, test ou chore" in r.stderr
    assert _git(repo, "log", "-1", "--format=%s").stdout.strip() == "chore: commit inicial"


def test_commit_com_acento_no_assunto_e_recusado_e_no_corpo_passa(repo):
    r = _commit(repo, "fix: medição recebida some da fila")
    assert r.returncode != 0 and "sem acento" in r.stderr
    arquivo = repo.parent / "mensagem.txt"
    arquivo.write_text("fix: medicao recebida some da fila\n\nA medição já recebida não volta à fila.\n", encoding="utf-8")
    r = _git(repo, "commit", "-q", "--allow-empty", "-F", str(arquivo), check=False)
    assert r.returncode == 0, r.stderr


def test_commit_de_merge_passa_com_qualquer_assunto(repo):
    _git(repo, "switch", "-q", "-c", "outra")
    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "feat: arquivo b")
    _git(repo, "switch", "-q", "principal")
    (repo / "c.txt").write_text("c\n", encoding="utf-8")
    _git(repo, "add", "c.txt")
    _git(repo, "commit", "-q", "-m", "feat: arquivo c")
    # assunto padrao do git ("Merge branch 'outra'") e assunto escrito a mao, com acento
    r = _git(repo, "merge", "-q", "--no-ff", "--no-edit", "outra", check=False)
    assert r.returncode == 0, r.stderr
    assert _git(repo, "log", "-1", "--format=%s").stdout.startswith("Merge branch 'outra'")
    _git(repo, "reset", "-q", "--hard", "HEAD~1")
    r = _git(repo, "merge", "-q", "--no-ff", "-m", "junta a correção da outra branch", "outra", check=False)
    assert r.returncode == 0, r.stderr
    assert len(_git(repo, "log", "-1", "--format=%P").stdout.split()) == 2


# --- 3. instalacao em worktree -----------------------------------------------------------------------------------

def _implementacoes():
    sh = pytest.param([SH, str(HOOKS / "barrar-instalacao.sh")] if SH else None, id="sh",
                      marks=pytest.mark.skipif(not SH, reason="sem sh"))
    ps = pytest.param([PWSH, "-NoProfile", "-File", str(HOOKS / "barrar-instalacao.ps1")] if PWSH else None, id="ps1",
                      marks=pytest.mark.skipif(not PWSH, reason="sem pwsh"))
    return [sh, ps]


@pytest.fixture(params=_implementacoes())
def barrar(request):
    comando_do_hook = request.param

    def rodar(cwd, comando, entrada=None):
        if entrada is None:
            entrada = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(cwd),
                                  "tool_input": {"command": comando}})
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        return subprocess.run(comando_do_hook, input=entrada, env=env, capture_output=True, text=True,
                              encoding="utf-8", timeout=60)
    return rodar


@pytest.fixture
def pastas(tmp_path):
    principal = tmp_path / "projeto"
    worktree = principal / ".claude" / "worktrees" / "sessao-1" / "frontend"
    worktree.mkdir(parents=True)
    return principal, worktree


INSTALACOES = [
    "npm ci",
    "npm install",
    "npm i",
    "npm install vitest --save-dev",
    "npm --prefix frontend ci",
    "cd frontend && npm ci",
    "cd backend; pip install -r requirements.lock",
    "pip3 install pypdf",
    ".venv/bin/pip install pypdf",
    ".venv/bin/python -m pip install -r requirements.lock",
    "python3 -m pip install pypdf",
    "CI=1 npm ci",
    "git status\nnpm ci",
    "(cd frontend && npm install)",
]

OUTROS = [
    "npm test",
    "npm run build",
    "npm run lint",
    "npx tsc -b",
    ".venv/bin/python -m pytest -q",
    'git commit -m "chore: barra npm ci e pip install em worktree"',
    "echo rode npm install na pasta principal",
    "grep -rn 'pip install' docs",
    "npm init -y",
]


@pytest.mark.parametrize("comando", INSTALACOES)
def test_instalacao_e_barrada_dentro_de_worktree(barrar, pastas, comando):
    _, worktree = pastas
    r = barrar(worktree, comando)
    assert r.returncode == 2, (comando, r.stdout, r.stderr)
    assert "Instalacao barrada" in r.stderr and "pasta principal" in r.stderr


@pytest.mark.parametrize("comando", INSTALACOES)
def test_instalacao_passa_na_pasta_principal(barrar, pastas, comando):
    principal, _ = pastas
    r = barrar(principal, comando)
    assert r.returncode == 0, (comando, r.stderr)


@pytest.mark.parametrize("comando", OUTROS)
def test_comando_que_nao_instala_passa_dentro_de_worktree(barrar, pastas, comando):
    _, worktree = pastas
    r = barrar(worktree, comando)
    assert r.returncode == 0, (comando, r.stderr)


def test_instalacao_que_entra_no_worktree_pelo_comando_e_barrada(barrar, pastas):
    principal, _ = pastas
    r = barrar(principal, "cd .claude/worktrees/sessao-1/frontend && npm ci")
    assert r.returncode == 2 and "o comando cita" in r.stderr


def test_instalacao_e_barrada_em_worktree_do_git_fora_de_claude_worktrees(barrar, tmp_path):
    if not GIT:
        pytest.skip("precisa de git")
    principal = tmp_path / "projeto"
    principal.mkdir()
    _git(principal, "init", "-q", "-b", "principal")
    _git(principal, "config", "commit.gpgsign", "false")
    _git(principal, "commit", "-q", "--allow-empty", "--no-verify", "-m", "chore: commit inicial")
    solto = tmp_path / "solto"
    _git(principal, "worktree", "add", "-q", str(solto))
    assert barrar(solto, "npm ci").returncode == 2
    assert barrar(principal, "npm ci").returncode == 0


@pytest.mark.parametrize("entrada", ["", "isto nao e json", "[]", '{"tool_input": {"file_path": "a.py"}}',
                                     '{"tool_input": {"command": 7}}'])
def test_payload_ilegivel_nao_trava_a_sessao(barrar, pastas, entrada):
    _, worktree = pastas
    assert barrar(worktree, "", entrada=entrada).returncode == 0


def test_sh_e_ps1_usam_a_mesma_expressao():
    sh = re.search(r'^INSTALA = r"(.+)"$', (HOOKS / "barrar-instalacao.sh").read_text(encoding="utf-8"), re.M)
    ps = re.search(r"^\$INSTALA = '(.+)'$", (HOOKS / "barrar-instalacao.ps1").read_text(encoding="utf-8"), re.M)
    assert sh and ps and sh.group(1) == ps.group(1)


def test_o_hook_esta_ligado_no_settings_para_bash_e_powershell():
    cfg = json.loads((RAIZ / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entradas = [e for e in cfg["hooks"]["PreToolUse"]
                if any("barrar-instalacao" in h["command"] for h in e["hooks"])]
    assert len(entradas) == 1 and set(entradas[0]["matcher"].split("|")) == {"Bash", "PowerShell"}


# --- 4. settings.json: sem regra que pede confirmacao, com a recusa de force push ------------------------------

def test_o_settings_versionado_nao_tem_regra_que_pede_confirmacao():
    # docs/adr/0014: regra `ask` interrompe a sessao em modo automatico (basta um trecho de comando composto casar, e
    # nenhuma regra `allow` passa por cima). Quem quiser a trava de volta decide num ADR novo, nao numa linha aqui.
    cfg = json.loads((RAIZ / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert cfg["permissions"].get("ask", []) == []


@pytest.mark.parametrize("ferramenta", ["Bash", "PowerShell"])
def test_o_settings_versionado_recusa_force_push(ferramenta):
    # docs/adr/0014: a `deny` fica. Ela recusa sem perguntar, em qualquer modo, e passa na frente do `allow`.
    cfg = json.loads((RAIZ / ".claude" / "settings.json").read_text(encoding="utf-8"))
    esperadas = {f"{ferramenta}(git push {forma})" for forma in ("*--force*", "-f *", "* -f", "* -f *", "* +*")}
    assert esperadas <= set(cfg["permissions"].get("deny", []))
