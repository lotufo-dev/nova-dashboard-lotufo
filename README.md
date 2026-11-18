# Dashboard de Contratos e Medições — Lotufo

Sistema interno (FastAPI + React + SQLite) para contratos de obras públicas e o ciclo da medição:
espelho de NF → envio ao faturamento → nota → envio ao órgão/protocolo → pagamento. Rede interna, sem nuvem,
sem API paga. A única fonte automática é o TOTVS RM.

> Código publicado para a CI; todos os direitos reservados, Lotufo Engenharia e Construções Ltda. Sem licença de uso.

- Como o trabalho anda e regras para o Claude: `CLAUDE.md` e `.claude/rules/`
- Domínio e decisões: `GLOSSARY.md`, `docs/adr/` e `.claude/rules/`
- Operação e produção: `docs/runbook.md`
- Decisões e dívidas: `docs/backlog.md`; tarefas: GitHub Issues

## Rodar em desenvolvimento

Backend (janela 1):

```
cd backend
$env:DASH_DEV = "1"
$env:DASH_SEM_JOBS = "1"
$env:DASH_GRAPH_SIMULADOR = "dados/correio-simulado"
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
- Banco de dev: `backend\dados\dashboard.db`; `DASH_DB_PATH` aponta outro arquivo (quando usar cada um:
  `CLAUDE.md`, item "Banco"). Sem RM configurado, o sistema roda com o RM desligado
  (`DASH_RM_SIMULADOR=<pasta>`); e-mail no dev vai para o simulador (`DASH_GRAPH_SIMULADOR=dados/correio-simulado`).
- **E-mail real travado no dev** (issue #707): com `DASH_DEV=1` e sem `DASH_GRAPH_SIMULADOR`, todo envio é recusado,
  com a mensagem de como ligar o simulador: no envio feito por pessoa, antes da reserva; nos jobs de alerta de
  segurança e de cobrança de certidões, a marca do job é gravada e solta, sem chamar o Graph (nada sai, nada fica
  preso). Para um teste deliberado com e-mail de verdade, suba
  também com `DASH_EMAIL_REAL_EM_DEV=1`. Sem `DASH_DEV` (produção) a variável não é lida e nada muda.
- `DASH_CADASTRO_DIR` aponta a pasta do cadastro (YAML) que `python -m app.cli cadastro validar|aplicar` lê; em
  produção é `C:\DashboardLotufo\cadastro`, clone do repositório privado `lotufo-cadastro`. `--raiz` vence a variável.
- Sem a variável, o cadastro é o `cadastro-exemplo/` do repositório: 100% fictício, usado pelos testes e pela CI.
  O `aplicar` recusa esse exemplo em banco que já tem contratos de outro cadastro.

Telas: `/inicio`, `/medicoes` (com abas), `/resumo-medicoes`, `/obras`, `/obras/N` (abas Medições, Prazos, Reajuste, Documentos
exigidos, Contrato; as notas moram na medição), `/obras/N/medicoes/M` (Espelho, Faturamento, Nota, Envio, Pagamento), `/documentos`,
`/fechamento`, `/admin`, `/conta`.

## Testar

```
cd backend && .venv\Scripts\python -m pytest -q
cd frontend && npm test && npm run typecheck && npm run lint
```

A CI roda o backend num job só, `backend` (Ubuntu, `pytest -q -n 4`, com pytest-xdist), com a Liberation Sans
instalada pelo apt (`fonts-liberation`). Teste que só vale no Windows se pula com `skipif` no próprio teste.
A carta, os ofícios e a FRC procuram a fonte Unicode numa lista (`app/carta.py`, `fonte_carta`): Arial no Windows
(a produção) e no Mac, Liberation Sans no Linux, ou o par apontado por `DASH_FONTE_CARTA` e `DASH_FONTE_CARTA_NEGRITO`;
sem nenhuma, Helvetica com o texto trocado para latin-1 (o travessão vira hífen). Na CI a falta da fonte é erro.
Marcador `pdf`: gera PDF com essa fonte (`test_carta`, `test_frc`, `test_protocolo`, `test_pdfs`, `test_notas_envio`, `test_pleitos`, `test_api_protocolos`, `test_api_pleitos`, `test_envio_reserva`, `test_api_siga`; para achar os módulos, `grep -lE "carta\.gerar|frc\.gerar|protocolo\.montar|pleitos\.montar|conferir_pdfs|textos_por_pagina_com_limite|_texto_da_frc|protocolo\.criar|/montar" backend/tests/*.py` acha os candidatos, e o que decide é a medição: `cd backend && PYTHONPATH=tests .venv/bin/python -m pytest -q -p contar_pdfs tests` (plugin `tests/contar_pdfs.py`, só carrega com `-p`, roda em série) imprime os PDFs gerados por módulo; `test_api_admin` casa com o grep e gera 0 PDFs, e `test_notas` não gera nenhum, por isso os dois ficam sem o marcador).

Recriar o ambiente igual ao testado: `.venv\Scripts\python -m pip install -r requirements.lock`
(faixas suportadas em `backend/pyproject.toml`) e `npm ci` em `frontend`.

A CI (`.github/workflows/ci.yml`) roda tudo isso em cada PR e em `master`; a branch `master` só aceita merge
por PR, pela fila de merge, com os checks obrigatórios `backend`, `frontend` e `vazamento` verdes.

### Ponta a ponta e prova de uma entrega

- **Ponta a ponta** (job `ponta-a-ponta` da CI; na máquina, o mesmo comando): `python3 scripts/prova/ponta_a_ponta.py`
  monta o frontend, sobe o sistema num banco novo com o `cadastro-exemplo/` e o e-mail no simulador, entra como admin,
  engenharia e diretoria e abre cada tela e cada estado (janela, formulário, tela vazia, tela de erro) de
  `scripts/prova/telas.mjs`, a lista única de telas e perfis. Reprova com
  erro de console, resposta 4xx/5xx, tela de erro, tela em branco ou rolagem lateral. Navegador: o do Playwright
  (`cd frontend && npx playwright install --only-shell chromium`) ou, sem ele, o Chrome da máquina.
- **Prova de uma entrega** numa cópia do banco, com `DASH_DB_PATH` (a cópia, fora do repositório) e `DASH_CADASTRO_DIR`
  definidas: `python3 scripts/prova/servidor.py --copia` sobe o servidor de prova (o `--copia` é pedido na primeira
  subida sobre um banco que já tem contratos: a prova roda as migrações e cria três usuários de teste nele);
  `python3 scripts/prova/retrato.py tirar antes`, `tirar depois` e `comparar antes depois` dizem o que mudou nas
  respostas da API; `node scripts/prova/capturar.mjs` captura as telas por perfil a 1440, 1024 e 390 e faz a auditoria
  visual de cada uma (texto cortado ou sobreposto, letra e canto fora da fundação). O cabeçalho de
  cada roteiro tem as opções; nada sai para dentro do repositório (senha de teste, correio simulado e saídas ficam ao
  lado do banco, ou em `DASH_PROVA_SAIDA`). O banco de uma instalação (o da produção, que tem
  `segredos/instalacao.json` na pasta acima da dele) é recusado: a prova só roda numa cópia.

### Dado real no repositorio

A regra (o que não pode entrar) está em `CLAUDE.md` e em `.claude/rules/dados-de-teste.md`. Quem confere é
`scripts/vazamento.py` (só biblioteca padrão), que mostra o achado mascarado e roda no `.githooks/pre-commit`
(`--staged`), no `.githooks/pre-push` (`--push`) e no job `vazamento` da CI, que é check obrigatório do `master`.
Para os hooks: `git config core.hooksPath .githooks` e `DASH_SERVIDOR` com o nome do servidor de produção (sem
ela, usa o `COMPUTERNAME`); a CI lê o secret `DASH_SERVIDOR`. A lista local de nomes de pessoas é
`scripts/vazamento-nomes.txt` (ignorada pelo git, uma por linha, mantida pelo dono); dado fictício de propósito vai
em `scripts/vazamento-excecoes.txt`. Mudar essa lista, o próprio script ou os hooks exige merge do dono: o job falha
na PR que os altera.

## Rodar no Mac

Para desenvolver num Mac (zsh); a produção continua só no Windows. Uma vez, na raiz do clone:

```bash
brew install python@3.12 node@24
python3.12 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.lock
(cd frontend && npm ci)
git config core.hooksPath .githooks
```

E no `~/.zshrc`: `export DASH_SERVIDOR=` seguido do nome do servidor de produção (ver o último item abaixo).

- Backend: `cd backend && DASH_DEV=1 DASH_SEM_JOBS=1 DASH_GRAPH_SIMULADOR=dados/correio-simulado .venv/bin/python -m uvicorn --factory app.main:create_app --reload --port 8080`.
  Frontend igual ao Windows (`cd frontend && npm run dev`). No app do Claude: `backend-dev-mac`, `frontend-dev-mac`
  e `prototipo-login-mac` em `.claude/launch.json`.
- Testes: `cd backend && .venv/bin/python -m pytest -q` e os de frontend acima. A suíte oficial é a CI (Ubuntu);
  teste que só vale no Windows é pulado ou pode falhar no Mac.
- Os hooks do Claude passam por `.claude/hooks/rodar.sh`, que roda o `.ps1` no Windows e o `.sh` de mesmo nome
  no Mac; num worktree, `node_modules` e `.venv` viram links simbólicos para os do clone principal.
- `DASH_SERVIDOR` é o nome do servidor de produção para a varredura de dado real nos hooks do git. Sem ela,
  o commit e o push param (o Mac não tem `COMPUTERNAME`). Copie também a lista local
  `scripts/vazamento-nomes.txt` do Windows; sem ela, a checagem de nomes de pessoas é pulada.

## Produção

Roda no `<servidor>` (`http://<servidor>`), de um clone git pinado (HEAD destacado) em `C:\DashboardLotufo\app`, com dados,
snapshots e logs em `C:\DashboardLotufo`. Deploy, backup, restauração, watchdog e TLS: `docs/runbook.md`.
Resumo do deploy (PowerShell como administrador, depois do merge em `master`; ou a skill `deploy` no Claude):

```
scripts\deploy.ps1
```

O `deploy.ps1` pausa o watchdog, atualiza o clone pinado (`fetch` e `checkout --detach`), instala o `requirements.lock`, faz o build do
frontend, reinicia a tarefa agendada, confere `/api/health`, volta ao commit anterior sozinho se a saúde não
voltar e despausa o watchdog.

O monitor do SIGA (`monitor-siga/`) não faz parte do repositório (a pasta está no `.gitignore`): roda no
computador do escritório, fora desta instalação.
