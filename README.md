# Dashboard de Contratos e Medições — Lotufo

Sistema interno (FastAPI + React + SQLite) para contratos de obras públicas e o ciclo da medição:
espelho de NF → envio ao faturamento → nota → envio ao órgão/protocolo → pagamento. Rede interna, sem nuvem,
sem API paga. A única fonte automática é o TOTVS RM.

> Código publicado para a CI; todos os direitos reservados, Lotufo Engenharia e Construções Ltda. Sem licença de uso.

- Como o trabalho anda (issues, worktrees, PR, gates): `docs/fluxo-de-trabalho-2026-10-11.md`
- Regras para o Claude: `CLAUDE.md` e `.claude/rules/`
- Produto (autoridade): `docs/superpowers/specs/2026-09-21-reestruturacao-design.md`
- Operação e produção: `docs/runbook.md`
- Decisões e dívidas: `docs/backlog.md`; tarefas: GitHub Issues

## Rodar em desenvolvimento

Backend (janela 1):

```
cd backend
$env:DASH_DEV = "1"
$env:DASH_SEM_JOBS = "1"
.venv\Scripts\python -m uvicorn --factory app.main:create_app --reload --port 8080
```

Frontend (janela 2), em `http://localhost:5173` com proxy de `/api` para o backend:

```
cd frontend
npm run dev
```

No app do Claude, as mesmas duas coisas estão em `.claude/launch.json` (`backend-dev`, `frontend-dev`).

- `--factory` é obrigatório: o app só existe depois de `create_app()` (migrações e backup rodam ali).
- `DASH_DEV=1` tira a flag `secure` do cookie, porque o Vite fala HTTP; sem ela o login "não funciona".
  **Nunca em produção** (`scripts\rodar_producao.ps1` limpa a variável).
- `DASH_SEM_JOBS=1` desliga a sincronização do RM e os e-mails de cobrança no dev.
- Banco de dev: `backend\dados\dashboard.db`. Seed ou servidor de revisão: só com `DASH_DB_PATH` apontando
  para uma pasta temporária. Sem RM configurado, o sistema roda com o RM desligado
  (`DASH_RM_SIMULADOR=<pasta>`); e-mail no dev vai para o simulador (`DASH_GRAPH_SIMULADOR=dados/correio-simulado`).
- `DASH_CADASTRO_DIR` aponta a pasta do cadastro (YAML) que `python -m app.cli cadastro validar|aplicar` lê; em
  produção é `C:\DashboardLotufo\cadastro`, clone do repositório privado `lotufo-cadastro`. `--raiz` vence a variável.
- Sem a variável, o cadastro é o `cadastro-exemplo/` do repositório: 100% fictício, usado pelos testes e pela CI.
  O `aplicar` recusa esse exemplo em banco que já tem contratos de outro cadastro.

Telas: `/inicio`, `/medicoes` (com abas), `/obras`, `/obras/N` (abas Medições, Prazos, Reajuste, Documentos
exigidos, Contrato; as notas moram na medição), `/obras/N/medicoes/M` (Espelho, Faturamento, Nota, Envio, Pagamento), `/documentos`,
`/diretoria`, `/admin`, `/conta`.

## Testar

```
cd backend && .venv\Scripts\python -m pytest -q
cd frontend && npm test && npm run typecheck && npm run lint
```

A CI roda o backend em dois jobs: `backend` (Ubuntu, `pytest -n 4 -m "not windows"`, com pytest-xdist) e
`backend-windows` (`pytest -m "windows or pdf"`). Marcador `windows`: só vale no Windows (`tests/test_backup.py`); roda só
no `backend-windows`. Marcador `pdf`: gera PDF com a Arial da produção (`test_carta`, `test_frc`, `test_protocolo`, `test_pdfs`);
roda nos dois jobs (Helvetica no Ubuntu, Arial no Windows).

Recriar o ambiente igual ao testado: `.venv\Scripts\python -m pip install -r requirements.lock`
(faixas suportadas em `backend/pyproject.toml`) e `npm ci` em `frontend`.

A CI (`.github/workflows/ci.yml`) roda tudo isso em cada PR e em `master`; a branch `master` só aceita merge
por PR com os checks `backend` e `frontend` verdes.

### Dado real no repositorio

O repositorio e' publico: nenhum CNPJ/CPF real, e-mail de dominio real, chave de NFS-e/NF-e, nome da maquina ou nome
de pessoa pode entrar. `scripts/vazamento.py` faz essa varredura (so' biblioteca padrao) e mostra o achado mascarado.
Ele roda em tres lugares: no `.githooks/pre-commit` (so' os arquivos do commit, `--staged`), no `.githooks/pre-push`
(cada commit que o push envia, `--push`, porque cherry-pick, rebase, merge e edicao pela web nao passam pelo
pre-commit e dado que entra e sai continua no historico) e no job `vazamento` da CI (arvore, cada commit da PR e
`gitleaks`). O job e' uma guarda, obrigatoria a partir do corte para o repositorio publico (#107): enquanto nao for
check obrigatorio do `master`, nao impede o merge. Os hooks usam `DASH_SERVIDOR` ou, sem ela, o `COMPUTERNAME` para o
nome da maquina; a CI le o secret `DASH_SERVIDOR`. A lista local de nomes de pessoas e' `scripts/vazamento-nomes.txt`
(ignorada pelo git, uma por linha, o Leo mantem). Dado ficticio de proposito vai em `scripts/vazamento-excecoes.txt`.
Mudar essa lista, o proprio script ou os hooks exige merge do Leo: o job falha na PR que os altera.

## Rodar no Mac

Para desenvolver num Mac (zsh); a produção continua só no Windows. Uma vez, na raiz do clone:

```bash
brew install python@3.12 node@24
python3.12 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.lock
(cd frontend && npm ci)
git config core.hooksPath .githooks
```

E no `~/.zshrc`: `export DASH_SERVIDOR=` seguido do nome do servidor de produção (ver o último item abaixo).

- Backend: `cd backend && DASH_DEV=1 DASH_SEM_JOBS=1 .venv/bin/python -m uvicorn --factory app.main:create_app --reload --port 8080`.
  Frontend igual ao Windows (`cd frontend && npm run dev`). No app do Claude: `backend-dev-mac`, `frontend-dev-mac`
  e `prototipo-login-mac` em `.claude/launch.json`.
- Testes: `cd backend && .venv/bin/python -m pytest -q` e os de frontend acima. A suíte oficial é a CI (Ubuntu, mais o job `backend-windows`);
  teste que só vale no Windows é pulado ou pode falhar no Mac.
- Os hooks do Claude passam por `.claude/hooks/rodar.sh`, que roda o `.ps1` no Windows e o `.sh` de mesmo nome
  no Mac; num worktree, `node_modules` e `.venv` viram links simbólicos para os do clone principal.
- `DASH_SERVIDOR` é o nome do servidor de produção para a varredura de dado real nos hooks do git. Sem ela,
  o commit e o push param (o Mac não tem `COMPUTERNAME`). Copie também a lista local
  `scripts/vazamento-nomes.txt` do Windows; sem ela, a checagem de nomes de pessoas é pulada.

## Produção

Roda no `<servidor>` (`http://<servidor>`), de um worktree pinado em `C:\DashboardLotufo\app`, com dados,
snapshots e logs em `C:\DashboardLotufo`. Deploy, backup, restauração, watchdog e TLS: `docs/runbook.md`.
Resumo do deploy (PowerShell como administrador, depois do merge em `master`; ou a skill `deploy` no Claude):

```
scripts\deploy.ps1
```

O `deploy.ps1` pausa o watchdog, atualiza o worktree pinado, instala o `requirements.lock`, faz o build do
frontend, reinicia a tarefa agendada, confere `/api/health`, volta ao commit anterior sozinho se a saúde não
voltar e despausa o watchdog.

O monitor do SIGA (`monitor-siga/`) não faz parte do repositório (a pasta está no `.gitignore`): mora em
`C:\DashboardLotufo\monitor-siga`, junto dos dados da produção.
