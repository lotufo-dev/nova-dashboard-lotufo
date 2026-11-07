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
3. **Pasta principal em `master` atualizado** (é de lá que o `scripts\deploy.ps1` roda):
   `git switch master` e `git pull --ff-only` na pasta principal do projeto; `git rev-parse master origin/master`
   iguais.
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
git -C C:\DashboardLotufo\app grep -c soltarWatchdog "$atual" -- scripts/deploy.ps1
```

- **Arquivo da instalação** (issue #417, runbook "Instalação assinada"): o `Test-Path` tem que dar `True`. Se der `False`,
  parar e avisar o Leo, que assina e copia o arquivo; sem ele a produção sobe em modo cópia, sem e-mail e sem RM.
- **Primeiro deploy com a #417**: o `ls-tree` volta vazio, porque o commit no ar ainda não tem `instalacao.py`. Então
  o `deploy.ps1` do diretório pinado é o antigo, que só confere o 200. Seguir o item "Deploy da issue #417" de
  "Subir e derrubar": rodar o `deploy.ps1` novo copiado para `C:\Temp\deploy`, pelo Mac num `.ps1` com `-File`, e
  conferir `instalacao: autorizada` logo depois.
- **Primeiro deploy com a #443** (rollback sem fetch; sentinela só sai com a produção conferida): o `git grep` de
  `soltarWatchdog` volta vazio, porque o `deploy.ps1` do pinado ainda é o antigo, cujo rollback faz `fetch` e cujo
  `finally` sempre apaga o sentinela. Seguir o item "Deploy da issue #443" de "Subir e derrubar": rodar o `deploy.ps1`
  novo copiado para `C:\Temp\deploy`, como na #417 (pelo Mac num `.ps1` com `-File`). O commit no ar ainda não tem o
  campo `commit` no health: o script avisa `producao NAO conferida no inicio` e só solta o watchdog com `DEPLOY OK`.

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

1. **Não criar o sentinela antes**: o `deploy.ps1` o cria sozinho, antes de mudar qualquer coisa. Conferir
   `Test-Path C:\DashboardLotufo\watchdog.pause`: `True` é uma execução anterior que não terminou provada (`MANTIDO`,
   chamada que caiu) ou uma recuperação à mão em andamento; avisar o Leo antes de seguir. Com o sentinela anterior,
   o script não conta a produção como provada no início: aborto antes do checkout o mantém, e só `DEPLOY OK`,
   `ROLLBACK OK` ou a volta do build que reconstruiu o anterior o apagam.
2. Na pasta principal, pela ferramenta PowerShell, **sem redirecionar stderr** (nada de `2>&1` ou `*>&1`: o
   PowerShell 5.1 transforma o aviso do Vite em erro fatal, cabeçalho do script), com timeout de 600000 ms:
   `& .\scripts\deploy.ps1` ou `& .\scripts\deploy.ps1 -SemFrontend` (a porta vem da tarefa agendada; `-Porta <porta>` só confere e aborta se não bater)
3. Ler a saída:
   - `sem migracao nova; sem backup pre-migracao` ou `BACKUP PRE-MIGRACAO: <caminho>` → guardar o caminho do
     backup para o registro.
   - `BACKUP PRE-MIGRACAO FALHOU: <motivo>` seguido de `deploy abortado antes do checkout` (sai com código 1)
     → nada mudou na produção. Avisar o Leo com o motivo, não tentar de novo sozinho.
   - `DEPLOY OK: <anterior> -> <novo> (health 200 no commit novo, processo novo)` (com `- backup pre-migracao: <caminho>` no
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
     **Não apagar o sentinela** antes de o diretório pinado voltar ao commit anterior.
   - `deploy abortado antes do checkout: diretorio pinado com arquivos alterados ...` → nada mudou; avisar o Leo
     (alguém mexeu no pinado), não tentar de novo sozinho.
   - `sentinela ... MANTIDO: a producao nao foi provada depois do deploy` ou `... nao estava conferida no inicio`
     → mesmo caso de "intervir a mao": avisar o Leo com o erro e **não apagar o sentinela**. O script só o apaga
     sozinho com a produção provada (health 200 com o campo `commit` igual ao commit esperado): `DEPLOY OK`,
     `ROLLBACK OK`, `deploy abortado no build; producao segue ...`, ou aborto antes do checkout com a linha
     `producao conferida no inicio` antes.
   - `sentinela ... MANTIDO POR FALHA NA REMOCAO` (depois de `DEPLOY OK`, `ROLLBACK OK` ou `producao segue ...`) →
     a produção está provada: **não reconstruir nem desfazer o deploy**. Conferir health e `commit` (item 4), corrigir
     o bloqueio (permissão, processo que segura o arquivo) e apagar o arquivo (item 5).
4. Conferir a saúde na própria máquina (runbook, "Saúde" e "HTTP ou HTTPS"):
   `& .\scripts\saude_local.ps1 -Porta <porta>` → 200 com `banco: ok`, `tls: true` e
   `instalacao: autorizada` (`nao-autorizada` é a produção em modo cópia, sem e-mail e sem RM: avisar o Leo com o
   `instalacao_motivo` e seguir o runbook, "Instalação assinada")
   (a porta é a da tarefa agendada; o script fala HTTPS com `localhost` aceitando só o certificado da instalação, pelo
   thumbprint; nunca trocar por `Invoke-WebRequest` com a verificação desligada. Com a tarefa ainda em `-SemTls`, antes
   do corte da issue #425, acrescentar `-SemTls`, e o `tls` vem `false`)
   (503 = banco não respondeu; "SEM RESPOSTA" = servidor parado ou certificado diferente do da instalação). Conferir também `git -C C:\DashboardLotufo\app rev-parse HEAD` igual ao commit
   esperado pela linha final: o `<novo>` (o `origin/master`) em `DEPLOY OK`; o `<anterior>` (HEAD do pinado lido antes
   de rodar) em `ROLLBACK OK`, `deploy abortado no build; producao segue ...` e aborto antes do checkout; e o campo
   `commit` do health igual aos 7 primeiros caracteres desse mesmo commit.
5. Com o commit do item 4 batendo e fora dos casos de "intervir a mao" e de `MANTIDO`: o script já apagou o
   sentinela; confirmar com `Test-Path C:\DashboardLotufo\watchdog.pause` → `False`. Com `MANTIDO POR FALHA NA
   REMOCAO`: corrigir o bloqueio, `Remove-Item C:\DashboardLotufo\watchdog.pause -Force` e `Test-Path` → `False`, sem
   reconstruir nada. Nos casos de "intervir a mao" e dos outros `MANTIDO`, o sentinela só sai depois da recuperação
   descrita no runbook ("Deploy a partir do Mac", item 5), com o OK do Leo: `deploy.ps1 -Ref <anterior>` só se o
   `<anterior>` tem `backend/app/instalacao.py` e o `commit_atual` no `backend/app/main.py` (antes disso ele nunca chega
   a `DEPLOY OK`); sem eles, só a recuperação manual (reconstruir `<anterior>`, reiniciar, árvore limpa, health 200 e
   processo nascido depois do reinício).

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
