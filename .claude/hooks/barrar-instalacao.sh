#!/bin/sh
# Versao Mac/Linux de barrar-instalacao.ps1 (mesma regra; os detalhes estao la'). Hook PreToolUse
# (Bash|PowerShell), issue #710: `npm ci`, `npm install` e `pip install` sao barrados (exit 2, motivo no stderr)
# quando a pasta atual e' um worktree ou o comando cita uma pasta de `.claude/worktrees/`.
# Payload ilegivel ou python ausente -> exit 0 (o hook nunca trava a sessao por falta de ferramenta).
payload=$(cat)
py="$CLAUDE_PROJECT_DIR/backend/.venv/bin/python"
[ -x "$py" ] || py=python3
# Duas linhas: "1" se o comando cita `.claude/worktrees/` (senao "0") e a pasta atual. Nada, se nao e' instalacao.
# A expressao INSTALA e' a mesma do .ps1 (backend/tests/test_travas_repositorio.py compara as duas).
lido=$(printf '%s' "$payload" | "$py" -c '
import json, re, sys
INSTALA = r"(?:^|[;&|(\n`])\s*(?:\w+=\S*\s+)*(?:(?:sudo|uv|command|exec)\s+)?(?:npm(?:\.cmd)?(?:\s+--?[\w-]+(?:[= ]\S+)?)*\s+(?:ci|install|i)\b|(?:\S*[/\\])?pip[\d.]*(?:\.exe)?\s+install\b|(?:\S*[/\\])?python[\d.]*(?:\.exe)?\s+-m\s+pip\s+install\b)"
try:
    d = json.load(sys.stdin)
    comando = (d.get("tool_input") or {}).get("command") or ""
except Exception:
    sys.exit(0)
if not isinstance(comando, str) or not re.search(INSTALA, comando, re.I):
    sys.exit(0)
print("1" if re.search(r"\.claude[/\\]+worktrees[/\\]", comando) else "0")
print(d.get("cwd") or "")
' 2>/dev/null)
[ -n "$lido" ] || exit 0
cita=$(printf '%s\n' "$lido" | sed -n 1p)
cwd=$(printf '%s\n' "$lido" | sed -n 2p)

barrar() {
    {
        echo "Instalacao barrada: $1"
        echo "Num worktree, frontend/node_modules e backend/.venv sao links para os da pasta principal;"
        echo "\`npm ci\`, \`npm install\` e \`pip install\` aqui alteram a pasta principal e os outros worktrees."
        echo "Dependencia se instala numa sessao aberta na pasta principal."
    } >&2
    exit 2
}

[ "$cita" = "1" ] && barrar "o comando cita uma pasta de .claude/worktrees/."
case "$cwd" in */.claude/worktrees/*) barrar "a pasta atual e' um worktree ($cwd)." ;; esac
# Worktree criado fora de .claude/worktrees/: o `.git` dele nao e' o `.git` comum.
[ -n "$cwd" ] && [ -d "$cwd" ] || exit 0
proprio=$(git -C "$cwd" rev-parse --path-format=absolute --git-dir 2>/dev/null) || exit 0
comum=$(git -C "$cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
[ "$proprio" != "$comum" ] && barrar "a pasta atual e' um worktree ($cwd)."
exit 0
