# Hook PreToolUse (Bash|PowerShell), issue #710: num worktree, frontend\node_modules e backend\.venv sao links
# (juncoes) para os da pasta principal, criados por preparar-worktree. `npm ci`, `npm install` e `pip install`
# rodados ali alteram a pasta principal e todos os outros worktrees. O comando e' barrado (exit 2, motivo no
# stderr, que volta para o Claude) quando:
#   - a pasta atual esta' em .claude\worktrees\ ou e' um worktree do git (o `.git` dela nao e' o `.git` comum);
#   - ou o comando cita uma pasta de .claude\worktrees\ (ex.: `cd .claude/worktrees/x/frontend && npm ci`).
# Na pasta principal o comando passa. A expressao so' casa a instalacao em posicao de comando (comeco, depois de
# `&&`, `;`, `|`, `(` ou quebra de linha): "npm ci" dentro de uma mensagem de commit nao e' barrado. E' trava
# contra descuido, nao contra quem quer contornar.
# Payload ilegivel -> exit 0 (o hook nunca trava a sessao por falha dele mesmo).
[Console]::InputEncoding = [Text.Encoding]::UTF8
try { $payload = [Console]::In.ReadToEnd() | ConvertFrom-Json } catch { exit 0 }
if (-not $payload -or -not $payload.tool_input) { exit 0 }
$comando = $payload.tool_input.command
if ($comando -isnot [string] -or -not $comando) { exit 0 }

# A mesma expressao do .sh (backend/tests/test_travas_repositorio.py compara as duas).
$INSTALA = '(?:^|[;&|(\n`])\s*(?:\w+=\S*\s+)*(?:(?:sudo|uv|command|exec)\s+)?(?:npm(?:\.cmd)?(?:\s+--?[\w-]+(?:[= ]\S+)?)*\s+(?:ci|install|i)\b|(?:\S*[/\\])?pip[\d.]*(?:\.exe)?\s+install\b|(?:\S*[/\\])?python[\d.]*(?:\.exe)?\s+-m\s+pip\s+install\b)'
if ($comando -notmatch $INSTALA) { exit 0 }

function Barrar($motivo) {
    [Console]::Error.WriteLine("Instalacao barrada: $motivo")
    [Console]::Error.WriteLine("Num worktree, frontend/node_modules e backend/.venv sao links para os da pasta principal;")
    [Console]::Error.WriteLine('`npm ci`, `npm install` e `pip install` aqui alteram a pasta principal e os outros worktrees.')
    [Console]::Error.WriteLine("Dependencia se instala numa sessao aberta na pasta principal.")
    exit 2
}

if ($comando -match '\.claude[/\\]+worktrees[/\\]') { Barrar "o comando cita uma pasta de .claude/worktrees/." }
$cwd = "$($payload.cwd)"
if ($cwd -match '[/\\]\.claude[/\\]worktrees[/\\]') { Barrar "a pasta atual e' um worktree ($cwd)." }
# Worktree criado fora de .claude\worktrees\: o `.git` dele nao e' o `.git` comum.
if (-not $cwd -or -not (Test-Path -LiteralPath $cwd -PathType Container)) { exit 0 }
$proprio = git -C $cwd rev-parse --path-format=absolute --git-dir 2>$null
$comum = git -C $cwd rev-parse --path-format=absolute --git-common-dir 2>$null
if ($proprio -and $comum -and ($proprio -ne $comum)) { Barrar "a pasta atual e' um worktree ($cwd)." }
exit 0
