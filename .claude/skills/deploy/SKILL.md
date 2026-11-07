---
name: deploy
description: Sobe o master do GitHub para a produção (no próprio servidor ou do Mac por SSH), seguindo docs/runbook.md seção "Subir e derrubar" - sentinela do watchdog, scripts\deploy.ps1 com rollback automático, conferência do /api/health e registro do commit. Usar quando o Leo pedir "deploy", "sobe para produção" ou "põe no ar", depois de a PR estar mergeada.
---

# Deploy em produção

Fonte: `docs/runbook.md`, seções "Subir e derrubar" e "Saúde", e o cabeçalho de `scripts\deploy.ps1`. Não
acrescentar passo que não esteja lá. Se algo não estiver claro no runbook, citar o trecho ao Leo e perguntar,
em vez de decidir.

Resumo do runbook: a produção roda de um diretório **pinado** (`C:\DashboardLotufo\app`, worktree git em
detached HEAD) e não do tree de desenvolvimento. `scripts\deploy.ps1` atualiza esse diretório para
`origin/master`, reconstrói `.venv`/`dist`, reinicia a tarefa agendada, confere a saúde e faz
**rollback automático** para o commit anterior se ela não voltar.

## Pré-condições (todas; se uma falhar, parar e dizer ao Leo qual)

1. **PR mergeada** no GitHub: `gh pr view <M> --json state,mergeCommit -q '.state+" "+.mergeCommit.oid'` → `MERGED`.
2. **CI verde no master**: `gh run list --branch master --workflow ci --limit 1` → `completed success` no
   commit do merge.
3. **De onde o `deploy.ps1` roda.** No servidor com pasta de desenvolvimento: pasta principal em `master`
   atualizado (`git switch master` e `git pull --ff-only`; `git rev-parse master origin/master` iguais). Na VM de
   produção **não há pasta de desenvolvimento**: o script roda da cópia pinada
   `C:\DashboardLotufo\app\scripts\deploy.ps1` (runbook, "Variante sem pasta de desenvolvimento no servidor"), e a
   cópia é a do commit que está no ar: mudança no próprio `deploy.ps1` só vale no deploy seguinte (o runbook diz
   como rodar a versão nova de uma pasta fora do pinado).
4. **Sessão elevada** (o script para e inicia a tarefa agendada):
   `([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)`
   → `True`. Se `False`, pedir ao Leo para rodar o deploy num PowerShell aberto como administrador.

## Dois caminhos: local elevado ou SSH

- **Local elevado**: a sessão roda no próprio servidor, num PowerShell como administrador. As pré-condições 3 e 4
  se conferem direto ali; os comandos abaixo valem como estão.
- **SSH, a partir do Mac**: runbook, subseção "Deploy a partir do Mac (SSH)". Entrar com `ssh <servidor>` na conta
  local administradora de deploy (a conta Azure AD não serve); a sessão já vem elevada. Mandar os comandos como
  **script pelo stdin** (`ssh <servidor> 'powershell -NoProfile -ExecutionPolicy Bypass -Command -' < script.ps1`),
  nunca inline (aspas e `&` quebram no PowerShell 5.1); conferências numa linha só, e `$LASTEXITCODE` depois de cada
  `git`, com `exit 1`, porque no `-Command -` falha nativa não para o script. Em **três chamadas em sequência**:
  1. só leitura: `Set-Location` na pasta principal, `git switch master`, `git pull --ff-only`, `git rev-parse master origin/master`
     iguais, `IsInRole(...Administrator)` acima dando `True` e o bloco "Antes de rodar" (log, migrações, frontend). Daqui
     a sessão avisa o Leo da migração e escolhe `-SemFrontend`. As pré-condições 1 e 2 (`gh`) rodam no Mac;
  2. o deploy: sentinela e "Rodar" itens 1 a 3;
  3. conferência de saúde e commit, e apagar o sentinela (itens 4 e 5).

  Na VM (sem pasta de dev): a chamada 2 é `ssh <vm> 'powershell -NoProfile -ExecutionPolicy Bypass -File C:\DashboardLotufo\app\scripts\deploy.ps1 [-SemFrontend]'`
  (um `-File` direto, sem script pelo stdin), com o sentinela numa chamada curta antes; a chamada 1 usa
  `git -C C:\DashboardLotufo\app fetch` e `log`/`diff` contra `origin/master`, sem `switch`/`pull` (runbook, variante).
  **Se o script não imprimir nada em 2 minutos** (ele imprime `[HH:mm:ss] etapa` a cada passo desde a issue #386), abrir
  outra sessão SSH e conferir se `git`, `python` (pip) ou `node` (npm) estão rodando (`tasklist /FI "IMAGENAME eq git.exe"`
  etc.): rodando, esperar; parados e sem linha nova, abortar a chamada e seguir o item "Se a chamada 2 cair".

  Se a chamada 2 cair ou vier sem a linha final, o `finally` do `deploy.ps1` pode não ter rodado. Health 200 e `rev-parse`
  igual **não provam** deploy concluído (queda no build deixa o `dist` pela metade com o processo antigo no ar) e
  `logs\dashboard.log` não traz `DEPLOY OK`/`ROLLBACK`: reconectar, manter o sentinela e **rodar de novo
  `& .\scripts\deploy.ps1`** (repetível) até vir a linha final; só então conferir e apagar o sentinela (ver runbook).
- Nos dois: nome de máquina, usuário e IP não entram em texto, commit nem registro (repositório público); usar
  `<servidor>` e "conta de deploy".

## Antes de rodar: o que vai subir

```powershell
$atual = (git -C C:\DashboardLotufo\app rev-parse HEAD).Trim()
git log --oneline "$atual..origin/master"
git diff --name-only "$atual" origin/master -- backend/migrations
git diff --name-only "$atual" origin/master -- frontend
Test-Path C:\DashboardLotufo\segredos\instalacao.json
git -C C:\DashboardLotufo\app ls-tree --name-only "$atual" backend/app/instalacao.py
```

Na VM, sem pasta de dev, os comandos `git` que ainda não têm `-C` levam `git -C C:\DashboardLotufo\app` e antes deles
`git -C C:\DashboardLotufo\app fetch`.

- **Arquivo da instalação** (issue #417, runbook "Instalação assinada"): o `Test-Path` tem que dar `True`. Se der `False`,
  parar e avisar o Leo, que assina e copia o arquivo; sem ele a produção sobe em modo cópia, sem e-mail e sem RM.
- **Primeiro deploy com a #417**: o `ls-tree` volta vazio, porque o commit no ar ainda não tem `instalacao.py`. Então
  o `deploy.ps1` do diretório pinado é o antigo, que só confere o 200. Seguir o item "Deploy da issue #417" de
  "Subir e derrubar": rodar o `deploy.ps1` novo copiado para `C:\Temp\deploy`, pelo Mac num `.ps1` com `-File`, e
  conferir `instalacao: autorizada` logo depois.

- **Corte para HTTPS** (issue #425): é um passo à parte, depois de um deploy normal do commit com a #425, e só quando o
  Leo pedir. Seguir o runbook, "HTTP ou HTTPS", subseção "Corte para HTTPS", na ordem (certificado, PCs da operação,
  troca da tarefa e do watchdog, conferência). O `deploy.ps1` lê o modo da tarefa: com `-SemTls` confere por HTTP, sem
  ele por HTTPS, e no HTTPS não começa sem `<raiz>\segredos\tls\cert.pem` ("certificado do HTTPS nao encontrado",
  nada alterado: avisar o Leo).

- **Migração nova** (arquivo adicionado, alterado, removido ou renomeado em `backend/migrations/`): dizer ao Leo **explicitamente**, antes de rodar,
  o número e o que ela faz (ler o `.sql`: só acrescenta coluna/tabela/índice, ou mexe em dados). Pelo runbook,
  as migrações pendentes rodam sozinhas quando o servidor sobe (`create_app()`, seção "Restaurar o banco").
  O backup antes da migração é **automático** (runbook, "Subir e derrubar", item "Backup pré-migração"): se o
  commit novo mexe em `backend/migrations`, o `deploy.ps1` grava
  `C:\DashboardLotufo\dados\backups\dashboard-PRE-<commit>-<data>.db` antes do checkout e, se esse backup
  falhar, não faz o deploy. Não perguntar ao Leo sobre backup.
- **Nada em `frontend/`** mudou: rodar com `-SemFrontend` (pula `npm ci` e build).

## Rodar

1. Criar o sentinela, para o watchdog não reerguer o servidor no meio (runbook, item "Watchdog"):
   `New-Item -ItemType File -Path C:\DashboardLotufo\watchdog.pause -Force | Out-Null`
   (o `deploy.ps1` também cria e apaga o sentinela sozinho; criar antes não atrapalha.)
2. Na pasta principal, pela ferramenta PowerShell, **sem redirecionar stderr** (nada de `2>&1` ou `*>&1`: o
   PowerShell 5.1 transforma o aviso do Vite em erro fatal, cabeçalho do script), com timeout de 600000 ms:
   `& .\scripts\deploy.ps1` ou `& .\scripts\deploy.ps1 -SemFrontend` (a porta vem da tarefa agendada; `-Porta <porta>` só confere e aborta se não bater).
   Na VM: `powershell -NoProfile -ExecutionPolicy Bypass -File C:\DashboardLotufo\app\scripts\deploy.ps1 [-SemFrontend]`.
3. Ler a saída (uma linha `[HH:mm:ss] etapa` por passo: porta lida, fetch, checkout, pip, npm, reinício, saúde):
   - `deploy abortado: agendador de tarefas nao respondeu` (sai com código 1, antes do checkout; o script não criou nem apagou
     sentinela) → nada mudou na produção; o Agendador de Tarefas do servidor está sem responder (issue #386). **Apagar o sentinela
     que a sessão criou** (item 5; o watchdog não pode ficar pausado sem prazo) e avisar o Leo, sem tentar de novo sozinho.
     O mesmo vale para `BACKUP PRE-MIGRACAO FALHOU`.
   - `deploy abortado no reinicio (...)` (sai com código 1) → o pinado voltou ao commit anterior, mas o agendador não respondeu
     na hora de parar ou iniciar a tarefa. Se a parada tinha começado, o script refaz parar → liberar porta → iniciar com o
     commit anterior e só diz "religada" com health 200 de processo novo; senão imprime "NAO esta' comprovadamente no ar",
     mantém o sentinela e pede `schtasks /End` e `/Run` à mão. Nos dois casos a linha traz quem está na porta (PID e hora de
     criação): conferir `/api/health` à mão e avisar o Leo.
   - `deploy abortado no reinicio (...); a tarefa ... nao foi comprovadamente parada (...), entao o diretorio pinado NAO foi
     voltado` ou `deploy abortado antes do checkout (...)` com "NAO esta' comprovadamente no ar" → a parada não se provou (estado
     da tarefa e porta) e o script não mexeu no pinado nem soltou o watchdog. **Não apagar o sentinela**; avisar o Leo na hora.
   - `sem migracao nova; sem backup pre-migracao` ou `BACKUP PRE-MIGRACAO: <caminho>` → guardar o caminho do
     backup para o registro.
   - `BACKUP PRE-MIGRACAO FALHOU: <motivo>` seguido de `deploy abortado antes do checkout` (sai com código 1)
     → nada mudou na produção. Avisar o Leo com o motivo, não tentar de novo sozinho.
   - `DEPLOY OK: <anterior> -> <novo> (health 200, processo novo)` (com `- backup pre-migracao: <caminho>` no
     fim quando houve backup) → seguir.
   - `ROLLBACK OK: producao de volta em <anterior>` (sai com código 1) → a versão nova não subiu e o código
     anterior voltou. Avisar o Leo, não tentar de novo sozinho, olhar `C:\DashboardLotufo\logs\dashboard.log`.
     O rollback não volta o banco: se houve backup pré-migração, dizer ao Leo o caminho do arquivo, que é o
     que se restaura à mão (runbook, "Restaurar o banco a partir de um snapshot") se for preciso.
   - `deploy abortado no build; producao segue no commit anterior ...` → a versão nova não subiu e a produção
     segue no commit anterior. Avisar o Leo com o motivo, não tentar de novo sozinho. Com o aviso
     `instalacao nao autorizada para o commit novo` antes, o motivo é o arquivo da instalação (runbook, "Instalação
     assinada").
   - `ROLLBACK TAMBEM FALHOU - intervir a mao` ou `deploy abortado no build E a volta para ... falhou ... - intervir a mao`
     → avisar o Leo na hora; logs em `C:\DashboardLotufo\logs\dashboard.log` e `C:\DashboardLotufo\logs\watchdog.log`.
     **Não apagar o sentinela** antes de o diretório pinado voltar ao commit anterior (desde a #386 o próprio script o mantém
     nesses casos e imprime `sentinela ... MANTIDO`).
4. Conferir a saúde na própria máquina (runbook, "Saúde" e "HTTP ou HTTPS"):
   `& .\scripts\saude_local.ps1 -Porta <porta>` → 200 com `banco: ok`, `tls: true` e
   `instalacao: autorizada` (`nao-autorizada` é a produção em modo cópia, sem e-mail e sem RM: avisar o Leo com o
   `instalacao_motivo` e seguir o runbook, "Instalação assinada")
   (a porta é a da tarefa agendada; o script fala HTTPS com `localhost` aceitando só o certificado da instalação, pelo
   thumbprint; nunca trocar por `Invoke-WebRequest` com a verificação desligada. Com a tarefa ainda em `-SemTls`, antes
   do corte da issue #425, acrescentar `-SemTls`, e o `tls` vem `false`)
   (503 = banco não respondeu; "SEM RESPOSTA" = servidor parado ou certificado diferente do da instalação). Conferir também `git -C C:\DashboardLotufo\app rev-parse --short HEAD` igual ao
   `origin/master`.
5. Apagar o sentinela: `Remove-Item C:\DashboardLotufo\watchdog.pause -Force -ErrorAction SilentlyContinue`
   e confirmar com `Test-Path C:\DashboardLotufo\watchdog.pause` → `False`.

## Cadastro (só se o Leo pedir `cadastro aplicar` junto)

Depois do corte para o repositório público (#107), o cadastro real não vem no deploy: mora no clone
`C:\DashboardLotufo\cadastro` (repositório privado `lotufo-cadastro`). **Antes do `cadastro aplicar`, atualizar o
clone**: `git -C C:\DashboardLotufo\cadastro pull --ff-only` (se não for avanço simples, parar e avisar o Leo). Depois
seguir o runbook, "Cadastro versionado", em `C:\DashboardLotufo\app\backend` com `DASH_CADASTRO_DIR=C:\DashboardLotufo\cadastro`
e `DASH_DB_PATH` do banco de produção na sessão: `--ensaio` primeiro, conferir o relatório (a primeira linha diz a
pasta lida), depois o real.

Sem `--raiz` nem `DASH_CADASTRO_DIR` o comando cairia no `cadastro-exemplo/` (fictício) e se recusa em banco com
cadastro real.

## Registrar

Comentar em cada PR que subiu (não editar `docs/backlog.md` direto no `master`):

```bash
gh pr comment <M> --body "Em produção: commit <hash curto>, DD/MM/AAAA HH:MM. Migração: <não | NNN_nome.sql aplicada>. Backup pré-migração: <não | caminho>."
```

Responder ao Leo em uma ou duas linhas: o que subiu, o commit, se teve migração e se o health voltou 200.
