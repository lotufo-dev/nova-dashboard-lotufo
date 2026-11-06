# Runbook — Dashboard Lotufo

## Onde as coisas ficam
- Código: este repositório (branch de produção = `master`). O servidor de **dev** usa `backend\dados\dashboard.db` (só com `DASH_DEV=1`); fora de dev `DASH_DB_PATH` é obrigatória e o servidor não sobe sem ela.
- Árvore de **produção** (`-Raiz` de `scripts\rodar_producao.ps1`, padrão `C:\DashboardLotufo`), ACL restrita a SYSTEM + Administradores:
  - Banco: `C:\DashboardLotufo\dados\dashboard.db` (+ `-wal`/`-shm`).
  - Snapshots locais: `C:\DashboardLotufo\dados\backups\dashboard-AAAAMMDD-HHMMSS.db` — um no boot e um por hora, 48 mais recentes. Cada snapshot passa por ensaio de restauração (abre e roda `integrity_check`) antes de valer.
  - Arquivos no backup (issues #55 e #441): as pastas de `dados` que o sistema grava (`notas`, `espelhos`, `modelos`, `evidencias`, `certidoes`, `regularidades`, `protocolos`, `pleitos`, `curvas`, `planilhas`, `frc`, `boletins`, `anexos` e `assinaturas`; a lista é `PASTAS_ARQUIVOS` em `backend/app/backup.py`) são copiadas por uma tarefa própria do servidor, separada da do snapshot: ela começa logo depois de cada snapshot (ou de hora em hora, se o snapshot falhar), copia primeiro para `dados\backups\arquivos\<pasta>\` e depois, havendo `-BackupExterno`, para `<pasta externa>\arquivos\<pasta>\`. Cópia lenta ou pendurada (disco travado, antivírus, compartilhamento sem resposta) não para os snapshots; se uma passada passar de 2 horas, o health acusa "a cópia está rodando há N horas sem terminar" (calculado na hora da consulta), e se a tarefa morrer o health acusa e o servidor a sobe de novo na hora seguinte. Coerência: um snapshot só tem os arquivos que cita no backup quando a passada seguinte a ele termina (normalmente minutos; a cópia externa diária do banco também não espera a dos arquivos). A primeira passada em produção leva o acervo inteiro; as seguintes, só o que falta (mesmo nome e tamanho conta como presente), e uma vez por dia o destino é relido inteiro pelo sha256 e o arquivo estragado é trocado (o arquivo que falhar é conferido de novo na passada seguinte, sem reler o resto). Os nomes são o sha256 do conteúdo: cada cópia é conferida pelo hash, arquivo cujo conteúdo não confere com o nome fica de fora (e aparece no erro) e nada é apagado, então uma cópia de cada arquivo serve a todos os snapshots e o espaço ocupado é o das próprias pastas, não 48 vezes isso. O health mostra `ultima_copia_arquivos`/`_erro` (local) e `ultima_copia_externa_arquivos`/`_erro` (fora); a tela Administração › Saúde mostra as duas. As mensagens ali não trazem caminho do servidor; o detalhe fica em `logs\dashboard.log`. A cópia em andamento fica num `<arquivo>.<pid>-<thread>-<aleatório>.tmp` aberto até ser conferida; sobra de cópia interrompida com mais de 1 hora é apagada na passada seguinte (a ativa, aberta, o Windows não deixa apagar). Cuidado conhecido: no Windows, se alguém regravar um arquivo que já estava estragado no exato instante em que o backup o lê para conferir, a gravação pode recusar com "acesso negado"; basta repetir a ação.
  - Cópia externa (`-BackupExterno`, outro volume ou compartilhamento): uma por dia, com `.sha256` ao lado conferido relendo o destino. Retenção em camadas: 7 diárias, 5 semanais, 12 mensais. **A tarefa roda como SYSTEM**, que chega à rede como a conta de computador (`<servidor>$`): o compartilhamento precisa dar gravação a essa conta (no servidor de arquivos, permissão de compartilhamento e NTFS para `<servidor>$`). Enquanto não tiver, o health mostra `ultima_copia_externa_erro` com "Acesso negado" e os snapshots ficam só no disco local.
  - Logs: `C:\DashboardLotufo\logs\dashboard.log` (app + uvicorn), rotação à meia-noite, 30 dias.
  - PDFs de certidão: `dados\certidoes\<sha256>.pdf`.
- TLS: `certs\cert.pem` e `certs\chave.pem` no repositório (gerados por `scripts\gerar_certificado.ps1`, 5 anos).

## Primeira subida (migrar o banco de dev para a árvore de produção)
Uma vez só, como administrador, com o servidor de dev e qualquer uvicorn parados:
1. `New-Item -ItemType Directory -Force C:\DashboardLotufo\dados`
2. Copiar `backend\dados\dashboard.db` (e `-wal`/`-shm`, se existirem) para `C:\DashboardLotufo\dados\`.
3. `scripts\rodar_producao.ps1 -BackupExterno <pasta externa>` — o script recusa subir se o banco de produção não existir e o de dev existir.
4. Conferir `https://<servidor>:8443/api/health`: `banco: ok` e `backup.ultimo_snapshot` preenchido em até um minuto.

## Subir e derrubar
- **Valores locais ficam fora do repositório**, que é público: o nome do servidor, o endereço e a porta da API do RM, o nome das
  tarefas agendadas e o nome do serviço do RM não aparecem aqui. Neste documento são `<servidor>`, `<servidor-rm>`, `<porta-da-api>`,
  `<tarefa>` e `<tarefa-do-watchdog>`. Os valores reais vêm de variável de ambiente (`DASH_SERVIDOR`, `DASH_RM_ENDERECO`) ou de arquivo
  local em `C:\DashboardLotufo\segredos` (`rm-endereco.txt`); ver `scripts\rodar_producao.ps1`.
  O nome real das tarefas sai de `Get-ScheduledTask | Where-Object TaskName -like '*Dashboard*'`.
- **Produção roda de um diretório PINADO** (mitigação [16], 2026-09-10): a tarefa agendada executa `C:\DashboardLotufo\app\scripts\rodar_producao.ps1` — um **worktree git dedicado** (detached HEAD num commit), com seu próprio `backend\.venv` e `frontend\dist`. O tree de dev (`C:\Users\...\Nova Dashboard Lotufo`) é **só para desenvolver**; editar/trocar branch lá NÃO muda a produção, e um reboot no meio de uma edição também não. Os dados (banco/logs/backups) ficam em `-Raiz` (`C:\DashboardLotufo`), fora do código.
- **Deploy** (após commit+push no dev): `scripts\deploy.ps1 [-Ref origin/master] [-SemFrontend] [-Porta 8080]` (elevado; sem `-Porta`, usa a porta registrada na tarefa agendada, e com `-Porta` diferente dela aborta antes do checkout) — pausa o watchdog, atualiza o diretório pinado (git checkout + `requirements.lock` + build), reinicia, confere a saúde e faz **rollback automático** para o commit anterior se não voltar. Se o build (`pip`/`npm`/`vite`) falhar depois do checkout, o script volta o diretório pinado para o commit anterior (checkout direto, sem `git fetch`, e reconstrução só se o HEAD tinha saído dele), imprime que a produção segue nele e sai com código 1 (issue #78); se a volta também falhar, avisa para intervir à mão. Setup inicial do diretório pinado: `git worktree add --detach C:\DashboardLotufo\app <commit>`, depois `python -m venv` + `pip install -r backend\requirements.lock` e `npm ci && npm run build` em `frontend`.
- **Backup pré-migração** (automático no deploy, desde a issue #75): antes de trocar o código, o `deploy.ps1` compara o commit atual do diretório pinado com o novo (`git diff --name-only <atual> <novo> -- backend/migrations`). Sem mudança em migrações, imprime `sem migracao nova; sem backup pre-migracao` e segue. Com mudança, chama `scripts\backup_pre_migracao.ps1`, que tira um snapshot do banco de produção com o servidor ainda no ar (API de backup do SQLite, pelo Python do diretório pinado; nunca cópia do `.db`, que perderia o `-wal`), confere o `integrity_check` e grava `C:\DashboardLotufo\dados\backups\dashboard-PRE-<7 caracteres do commit novo>-<AAAAMMDD-HHMMSS>.db`. O caminho sai em `BACKUP PRE-MIGRACAO: <caminho>` e de novo na linha final `DEPLOY OK`. Se o snapshot falhar, sai `BACKUP PRE-MIGRACAO FALHOU: <motivo>`, o deploy para **antes** do checkout (produção segue no commit anterior, código e banco intactos), o watchdog é solto e o script sai com código 1. **O rollback automático só volta o código, não o banco**: se a versão nova migrou o banco e for preciso voltar também os dados, restaurar à mão o arquivo `dashboard-PRE-...` impresso no deploy, pela seção "Restaurar o banco a partir de um snapshot". Se o mesmo deploy foi tentado mais de uma vez (rollback e nova tentativa), o banco já pode ter migrado na primeira: o arquivo certo é o `dashboard-PRE-<commit>` **mais antigo** daquele commit.
- **Deploy da issue #110 (FRC e cobrança de certidão pelo cadastro): `cadastro aplicar` no mesmo passo.** Logo depois do `deploy.ps1`, `cadastro aplicar --ensaio` e real com `--raiz` do cadastro real (seção "Cadastro versionado"); o relatório deve trazer `frc: 0 criados, 2 alterados` e `cobranca_certidoes` criado no geral. Sem isso, a FRC do Integra BRT é recusada ("Logo da FRC não encontrado na pasta de dados: aplique o cadastro") e a cobrança de certidões só registra no log.
- **Deploy da issue #271 (apostilamento com competências; pleito atendido pelo termo): `cadastro aplicar` no mesmo passo.** Logo depois do `deploy.ps1`, `cadastro aplicar --ensaio` e real com `--raiz` do cadastro real (seção "Cadastro versionado"); o relatório deve trazer, em pleitos alterados, `<obra>/reajuste <ofício>: atendido por <chave>` para cada apostilamento de reajuste já aplicado com pleito enviado no ciclo. Sem isso, o ciclo desse pleito aparece como "apostilamento pendente" (com aviso, que vai à diretoria depois de 90 dias) até o próximo `aplicar`. O termo só liga o pleito enviado até a data dele: se o pleito de produção (pedido original ou reemissão do cronograma) tiver data posterior à do termo, ele não é ligado e o ciclo fica pendente; a reiteração posterior não atrapalha (o termo do pedido que ela reitera fecha o ciclo).
- **Deploy da issue #409 (aditivo de reajuste corrigido por outro; migração 059): `cadastro aplicar` no mesmo passo.** Logo depois do `deploy.ps1`, `cadastro aplicar --ensaio` e real com `--raiz` do cadastro real. O aditivo de reajuste corrigido por outro aditivo de reajuste (`corrige`) deixa de fechar ciclo assim que a 059 roda; é o `aplicar` que passa o pleito dele à correção (mesmo ciclo: `<obra>/reajuste <ofício>: atendido por <chave> (corrige <chave antiga>)`) ou o tira (outro ciclo: `sem termo (<chave> corrige <chave antiga> para o ciclo <ano>)`). Sem isso, o ciclo desse pleito aparece como "apostilamento pendente" até o próximo `aplicar`. Contrato sem aditivo com `corrige` não muda.
- **Deploy da issue #417 (instalação assinada): arquivo na VM antes e `deploy.ps1` novo, uma vez só.**
  1. Antes de rodar, `Test-Path C:\DashboardLotufo\segredos\instalacao.json` deve dar `True`. Se der `False`, parar: assinar e copiar pela seção "Instalação assinada".
  2. Rodar o `deploy.ps1` de `origin/master` copiado para `C:\Temp\deploy`, não o do diretório pinado. O PowerShell lê o script inteiro antes do checkout, e o antigo só confere o 200: sem o arquivo, ele terminaria em `DEPLOY OK` com a produção em modo cópia, sem e-mail e sem RM. Os comandos estão na seção "Instalação assinada", item "Primeiro deploy".
  3. Pelo Mac, esses comandos vão num `.ps1` temporário copiado para a VM com `scp` e rodado com `powershell -NoProfile -ExecutionPolicy Bypass -File`. No `-Command -` o `git fetch` consome o resto do script pelo stdin, e o script para no meio.
  4. Logo depois, `/api/health` com `instalacao: autorizada`. Se não vier, voltar à mão como diz o "Primeiro deploy".
- Dev: ver README ("Rodar em desenvolvimento").
- Produção (manual, avançado): `scripts\rodar_producao.ps1 [-SemTls] [-Porta 8080] [-Raiz C:\DashboardLotufo] [-BackupExterno \\servidor\backups\dashboard]` (elevado, a partir do diretório pinado). Hoje: `-SemTls`, sem cópia externa.
- **Porta** (issue #361): os quatro scripts (`rodar_producao.ps1`, `instalar_autostart.ps1`, `instalar_watchdog.ps1`, `deploy.ps1`) aceitam `-Porta`; sem ela vale o padrão de hoje (80 em HTTP com `-SemTls`, 8443 em HTTPS), e a produção atual não precisa reinstalar nada. Numa máquina em que a 80 é de outro serviço (IIS na VM nova), passar a mesma porta nos quatro (ex.: `-Porta 8080`) e liberar essa porta no firewall (seção "HTTP ou HTTPS"). Neste documento `http://localhost:<porta>/api/health` é a saúde nessa porta.
- Autostart: `scripts\instalar_autostart.ps1 [-AppDir C:\DashboardLotufo\app] [-SemTls] [-Porta 8080] [-Raiz ...] [-BackupExterno ...] [-RmUrl ... -RmUsuario ... -RmSenhaArquivo ... -RmHttpInseguro]` (sem os parâmetros do RM a tarefa sobe com o RM desligado; ver "TOTVS RM") registra a tarefa agendada apontando para o `rodar_producao.ps1` do diretório PINADO `-AppDir` (SYSTEM, no boot, reinício automático 3× a 1 min). Parar: `Stop-ScheduledTask -TaskName <tarefa>`; iniciar: `Start-ScheduledTask -TaskName <tarefa>`.
- Watchdog: `scripts\instalar_watchdog.ps1 [-Porta 8080]` registra a tarefa do watchdog (SYSTEM, a cada 3 min) que roda `scripts\watchdog.ps1 -Url http://localhost:<porta>/api/health` — confere `/api/health` na porta de `-Porta` (padrão 80 em HTTP) e, se cair, reinicia a tarefa principal (o reinício automático embutido da tarefa não cobriu a queda de 2026-09-10: timeout, não "falha"). **Antes de qualquer parada/deploy manual, crie o sentinela `C:\DashboardLotufo\watchdog.pause` para o watchdog não reerguer no meio; apague ao terminar.** Log: `C:\DashboardLotufo\logs\watchdog.log`. Remover: `Unregister-ScheduledTask -TaskName <tarefa-do-watchdog> -Confirm:$false`.

### Deploy a partir do Mac (SSH)

Caminho usado em 15/10/2026 (produção 109c887 para 8954dca, health 200). Vale quando não há sessão PowerShell elevada no
próprio servidor. O resto do deploy (`scripts\deploy.ps1`, rollback automático, backup pré-migração) é o descrito acima.

1. **Conta.** `ssh <servidor>` com a conta local administradora de deploy: a sessão já chega elevada. A conta Azure AD
   não serve ao OpenSSH do Windows.
2. **Comandos como script pelo stdin**, nunca inline: `ssh <servidor> 'powershell -NoProfile -ExecutionPolicy Bypass -Command -' < script.ps1`
   (aspas e `&` inline quebram no PowerShell 5.1). O `script.ps1` é um arquivo temporário no Mac, fora do repositório (nome
   diferente de `scripts\deploy.ps1`, que é o do projeto). No `-Command -` uma falha de comando nativo não para o script:
   conferir `$LASTEXITCODE` depois de cada `git` e sair com `exit 1`. Escrever cada conferência numa linha só (bloco de várias
   linhas pode exigir uma linha em branco depois, no 5.1).
3. **Primeira chamada, só leitura** (nada muda no servidor): `Set-Location` na pasta principal do projeto; `git switch master`;
   `git pull --ff-only`; `git rev-parse master origin/master` iguais (senão `exit 1`); conferir administrador numa linha
   (`if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { exit 1 }`);
   e imprimir o que vai subir: `git log --oneline "$atual..origin/master"` e `git diff --name-only` de `backend/migrations` e de `frontend`,
   com `$atual` = `git -C C:\DashboardLotufo\app rev-parse HEAD`. Com isso a sessão avisa o Leo de migração nova (número e o que faz)
   e escolhe `-SemFrontend` se nada em `frontend/` mudou.
4. **Segunda chamada, o deploy**: criar o sentinela do watchdog (`New-Item -ItemType File -Path C:\DashboardLotufo\watchdog.pause -Force | Out-Null`),
   `& .\scripts\deploy.ps1` (ou com `-SemFrontend`; a porta vem da tarefa agendada, `-Porta <porta>` só para conferir), **sem redirecionar stderr** dentro do PowerShell, e ler a linha final:
   `DEPLOY OK`, `ROLLBACK OK`, `ROLLBACK TAMBEM FALHOU`, `BACKUP PRE-MIGRACAO FALHOU` seguido de `deploy abortado antes do
   checkout` (nada mudou na produção), `deploy abortado no build; producao segue no commit anterior ...` (a produção segue no
   commit anterior) ou `deploy abortado no build E a volta para ... falhou ... - intervir a mao`. Nos dois casos de
   "intervir a mao" (`ROLLBACK TAMBEM FALHOU` e este último), **não apagar o sentinela** antes de o diretório pinado voltar ao
   commit anterior.
5. **Terceira chamada, conferência**: `Invoke-WebRequest http://localhost:<porta>/api/health -UseBasicParsing` (200 com `banco: ok` e `instalacao: autorizada`, seção "Instalação assinada";
   a porta é a de `-Porta`, padrão 80 em HTTP, quando dá para omitir o `:80`),
   `git -C C:\DashboardLotufo\app rev-parse --short HEAD` igual ao `origin/master`, e apagar o sentinela
   (`Remove-Item C:\DashboardLotufo\watchdog.pause -Force -ErrorAction SilentlyContinue`; `Test-Path` deve dar `False`).
   Apagar o sentinela também quando o deploy der `ROLLBACK` ou `BACKUP PRE-MIGRACAO FALHOU`.
6. **Se a chamada do deploy cair** (conexão SSH perdida, timeout da ferramenta) **ou não trouxer a linha final**: o PowerShell
   remoto pode ter morrido sem rodar o `finally` do `deploy.ps1`, deixando o sentinela e o watchdog pausado. **`/api/health` 200 e
   `rev-parse` igual ao `origin/master` não provam deploy concluído**: se a queda foi no `npm run build`, o pinado já está no
   commit novo com o `dist` pela metade e o processo antigo segue no ar (o health só olha o banco). E `DEPLOY OK`/`ROLLBACK`
   saem na tela, não em `logs\dashboard.log`, que portanto não serve de prova. O que fazer: reconectar, conferir
   `Test-Path C:\DashboardLotufo\watchdog.pause`, manter (ou recriar) o sentinela e **rodar de novo `& .\scripts\deploy.ps1`**
   (repetível: checkout, build, reinício, conferência e rollback), até vir a linha final; só então a chamada 3 e apagar o sentinela.
   Um caminho desacoplado seria uma tarefa agendada avulsa (`Register-ScheduledTask` como SYSTEM, disparada e removida depois),
   porque o OpenSSH do Windows provavelmente mata os processos da sessão ao fechá-la e `Start-Process` não escapa disso.
   **Não testado.**

## Saúde
`GET /api/health` toca o banco (503 se não responder) e devolve a última rodada de backup: `ultimo_snapshot`, `ultimo_snapshot_erro`, `ultima_copia_arquivos`, `ultima_copia_arquivos_erro`, `ultima_copia_externa`, `ultima_copia_externa_erro`, `ultima_copia_externa_arquivos`, `ultima_copia_externa_arquivos_erro`. Cópia externa com data de ontem ou erro preenchido = olhar o log. Traz também `instalacao` (`autorizada`, `nao-autorizada` ou `dev`) e `instalacao_motivo` (seção "Instalação assinada"). Traz ainda `commit` (7 caracteres do clone, lido na subida).

### Código em produção diferente do último deploy (issue #421)
O `scripts\deploy.ps1` grava `<raiz>\deploy-atual.json` (commit, data e sha256 do manifesto de `frontend\dist`) depois do build e antes de reiniciar; o rollback regrava. O servidor confere na subida e de hora em hora (não em dev, e não enquanto `watchdog.pause` existir): HEAD do clone, `git status --porcelain` vazio e manifesto do `dist`. Diferença = item crítico "Código em produção diferente do último deploy" em Administração > Saúde > Segurança (com contagens, sem nomes de arquivo) e uma linha `seguranca.arvore_alterada` na auditoria por diferença nova. Sem o arquivo = item de atenção "Sem registro do último deploy" até o próximo deploy. O deploy seguinte limpa o item. Para gravar o registro sem deploy: `python -m app.cli integridade registrar --raiz C:\DashboardLotufo` (no `backend` do clone, com o venv dele).

## Instalação assinada (issue #417)
Copiar a pasta de produção para outra máquina não basta para ter uma dashboard funcionando. Na subida o servidor lê `C:\DashboardLotufo\segredos\instalacao.json` (`<raiz>\segredos`, a pasta ao lado de `dados`, onde está o banco; a variável `DASH_INSTALACAO_ARQUIVO` troca o caminho) e confere a assinatura do dono e o nome da máquina (o `COMPUTERNAME`, lido do Windows e não da variável de ambiente). A conferência é só na subida: arquivo novo vale a partir do próximo reinício.

- **Autorizada**: tudo funciona; `/api/health` mostra `instalacao: autorizada`.
- **Modo cópia** (arquivo ausente ou que não se lê, assinatura que não confere ou outra máquina): `/api/health` continua 200 (o watchdog não reinicia em laço), com `instalacao: nao-autorizada` e `instalacao_motivo` `ausente`, `ilegivel`, `assinatura` ou `maquina`, sem caminho de arquivo. Login e leitura continuam. Todo envio de e-mail recusa com "Envio desligado: instalação não autorizada." antes da reserva (nada fica preso); "Sincronizar agora" recusa com "Sincronização desligada: instalação não autorizada."; a sincronização horária do RM e a cobrança de certidões não sobem; o backup local continua, a cópia externa (`-BackupExterno`) não. Toda tela, inclusive o login, mostra a faixa vermelha "Instalação não autorizada da Dashboard Lotufo. Envio de e-mail e sincronização com o RM estão desligados." O `logs\dashboard.log` registra `instalacao NAO autorizada (motivo: ...)` na subida.
- **Dev** (`DASH_DEV=1`) e testes: `instalacao: dev`, nada desligado, arquivo não exigido.
- **Deploy**: depois do build e **antes de parar a produção**, o `deploy.ps1` roda com o código novo `python -m app.cli instalacao verificar --arquivo <raiz>\segredos\instalacao.json` (sai 0 só com `Instalação autorizada para esta máquina.`, sem o atalho do dev). A `<raiz>` é a do `-Raiz` gravado na tarefa agendada, a mesma que o `rodar_producao.ps1` usa; dela sai também o banco do backup pré-migração. `-Raiz` informado e diferente da tarefa aborta antes do checkout, como a porta. Recusado, o deploy para ali, sem migrar o banco (as migrações só rodam na subida) e sem trocar o processo: aviso `instalacao nao autorizada para o commit novo` e linha final `deploy abortado no build; producao segue no commit anterior ...`. Depois do reinício ele ainda exige `instalacao: autorizada` no health; outro valor conta como falha (aviso `health 200, mas a instalacao nao esta autorizada: ...`) e dispara o rollback. O rollback confere só o 200 (o commit anterior pode nem ter o campo); se ele voltar em modo cópia, o `ROLLBACK OK` vem seguido do aviso `producao de volta, mas em modo copia: ...`. Por essa conferência, o `deploy.ps1` só sobe commit que já tem a instalação assinada.
- **Primeiro deploy com a instalação assinada (PR #437 da #417), uma vez só.** O PowerShell lê o `deploy.ps1` inteiro antes do checkout, e o do diretório pinado ainda é o antigo, que só confere o 200: rodado dali, sem o arquivo ele terminaria em `DEPLOY OK` com a produção em modo cópia (sem e-mail e sem RM). Nesta vez:
  1. Copiar o arquivo assinado para a VM (subseção abaixo) e conferir `Test-Path C:\DashboardLotufo\segredos\instalacao.json` → `True`.
  2. Rodar o `deploy.ps1` de `origin/master` copiado para `C:\Temp\deploy`, com os scripts que ele chama pelo `$PSScriptRoot` ao lado (hoje `backup_pre_migracao.ps1`; depois da #386, também `comum_agendador.ps1`): `New-Item -ItemType Directory -Force C:\Temp\deploy | Out-Null`, `git -C C:\DashboardLotufo\app fetch`, `git -C C:\DashboardLotufo\app show origin/master:scripts/deploy.ps1 | Set-Content -Encoding ascii C:\Temp\deploy\deploy.ps1` (idem os outros) e `& C:\Temp\deploy\deploy.ps1`, com o sentinela e o resto como em "Subir e derrubar". **Pelo Mac**, esses comandos vão num `.ps1` temporário no Mac (fora do repositório), copiado para a VM com `scp script.ps1 <vm>:C:/Temp/deploy-417.ps1` e rodado com `ssh <vm> 'powershell -NoProfile -ExecutionPolicy Bypass -File C:\Temp\deploy-417.ps1'`, nunca pelo stdin (`-Command -`): ali o `git fetch` consome o resto do script e ele para no meio. Conferir `$LASTEXITCODE` depois de cada `git` e apagar o `.ps1` no fim.
  3. Logo depois, conferir no `/api/health` a `instalacao: autorizada`. Se não vier (o script antigo rodou por engano, por exemplo), voltar à mão para o commit anterior com o script **dele**: os mesmos comandos do passo 2 com `git show <anterior>:scripts/...` para `C:\Temp\deploy-anterior` e `& C:\Temp\deploy-anterior\deploy.ps1 -Ref <anterior>`; depois resolver o arquivo e repetir o passo 2.

### Chave do dono (uma vez, no Mac)
`cd ~/dev/nova-dashboard-lotufo/backend && .venv/bin/python -m app.cli instalacao gerar-chave --saida ~/.lotufo` grava `instalacao-privada.pem` (permissão 0600) e `instalacao-publica.pem` e imprime a pública; nunca sobrescreve uma chave que já existe. A privada fica só com o dono, com uma cópia cifrada fora do Mac; nunca vai ao servidor nem ao repositório. A pública está embutida em `backend/app/instalacao.py` (`CHAVE_PUBLICA`): trocar de chave é uma PR, e todo arquivo assinado com a chave antiga passa a dar `assinatura`. A chave atual foi gerada em 05/11/2026 pelo comando do comentário da issue #417 (`~/.lotufo/instalacao-privada.pem`).

### Assinar e copiar para a máquina (no Mac)
A produção roda na VM (`<vm>`, seção "Mudar de servidor"); o SSH é o mesmo do deploy.
1. Nome da máquina: `ssh <vm> "cmd /c echo %COMPUTERNAME%"` (maiúsculas e minúsculas não importam).
2. Assinar: `.venv/bin/python -m app.cli instalacao assinar --chave ~/.lotufo/instalacao-privada.pem --maquina <nome> --saida ~/.lotufo/instalacao-<nome>.json`. O comando recusa, sem gravar nada, chave que não é a embutida no código e `--saida` que já existe (para assinar de novo, apagar o arquivo antigo antes).
3. Copiar: `scp ~/.lotufo/instalacao-<nome>.json <vm>:C:/DashboardLotufo/segredos/instalacao.json` (conta administradora de deploy; a pasta `segredos` tem a ACL de SYSTEM e Administradores e o arquivo herda). Conferir: `ssh <vm> "cmd /c type C:\DashboardLotufo\segredos\instalacao.json"`.
4. Não editar o arquivo, nem abrir e salvar no Bloco de Notas: ele vale exatamente como saiu do `assinar` (o fim de linha do Windows também serve); qualquer outro byte diferente dá `assinatura`.
5. Reiniciar a tarefa (com o sentinela do watchdog) ou fazer o deploy e conferir `/api/health`: `instalacao: autorizada`, sem faixa na tela.

### Faixa vermelha no servidor oficial
O servidor subiu em modo cópia. O motivo está no `/api/health`: `ausente` (arquivo fora de `segredos` ou com outro nome: copiar de novo), `ilegivel` (o arquivo está lá, mas o servidor não consegue lê-lo: conferir a ACL de `segredos` e do arquivo, sem copiar de novo), `assinatura` (arquivo alterado ou assinado com outra chave: assinar de novo), `maquina` (assinado para outro nome; o `COMPUTERNAME` mudou: assinar com o nome atual). Depois, reiniciar a tarefa e conferir o health.

### Trocar de máquina
Assinar para o nome da máquina nova e copiar para a `segredos` dela antes da primeira subida (seção "Mudar de servidor"). O arquivo da máquina antiga não vale na nova (motivo `maquina`), e o da nova não vale na antiga.

## Sentinela (issue #423)
Uma thread do servidor lê o log de Segurança do Windows a cada 5 minutos (`wevtutil`, sem dependência nova) e põe no bloco Segurança de Administração > Saúde, por 7 dias, o que indica cópia ou leitura de dados e segredos de dentro da VM ou pela rede. Só roda no Windows e fora de `DASH_DEV=1`; no resto, a Saúde mostra "Sentinela não roda neste ambiente". Cada achado também vira linha `seguranca.sentinela` na auditoria (evento, conta, processo, pasta, quantidade, hora).

### Pré-requisitos (uma vez, na VM, como administrador)
`<raiz>` é a pasta de produção (a que tem `dados`, `segredos` e `cadastro`). Subcategorias pelo GUID, porque o Windows está em português.
```powershell
auditpol /set /subcategory:"{0CCE921D-69AE-11D9-BED3-505054503030}" /success:enable   # Sistema de Arquivos
auditpol /set /subcategory:"{0CCE922F-69AE-11D9-BED3-505054503030}" /success:enable   # Alteração da política de auditoria
wevtutil sl Security /ms:268435456                                                    # log de 256 MB
$raiz = '<raiz>'
foreach ($p in 'dados','segredos','cadastro') {
  $acl = Get-Acl -Path "$raiz\$p"
  foreach ($sid in 'S-1-5-4','S-1-5-2') {   # INTERATIVO e REDE
    $id = New-Object System.Security.Principal.SecurityIdentifier $sid
    $regra = New-Object System.Security.AccessControl.FileSystemAuditRule($id, 'Read,Write,Delete,ChangePermissions', 'ContainerInherit,ObjectInherit', 'None', 'Success')
    $acl.AddAuditRule($regra)
  }
  Set-Acl -Path "$raiz\$p" -AclObject $acl
}
```
O servidor, o antivírus e o backup rodam como SYSTEM, que não carrega INTERATIVO nem REDE: o volume fica baixo e só aparece quem entrou na VM ou leu pela rede (`\\<servidor>\C$`).

### Lista de contas e processos conhecidos
`<raiz>\segredos\sentinela.json` (fora do repositório). Acesso a arquivo (4663) só deixa de gerar item quando a conta **e** o processo estão na lista; a conta pode vir com ou sem domínio. Contas listadas também não geram o aviso de logon com privilégio (4672). Exemplo com nomes fictícios:
```json
{"contas": ["SERVIDOR\\operador.exemplo", "admin.exemplo"], "processos": ["explorer.exe", "robocopy.exe"]}
```
O ponto de leitura do log (último registro lido) fica no banco, na auditoria (`seguranca.sentinela.ponto`), na mesma transação dos achados; `<raiz>\dados\sentinela.json` é só uma cópia, com as falhas em aberto e os avisos do dia. Na primeira leitura com sucesso a sentinela só marca o ponto de partida do log; não lê o histórico. Se a cópia for apagada, ficar ilegível ou apontar além do ponto gravado no banco, a rodada seguinte grava o item crítico "Estado da sentinela apagado, ilegível ou alterado" e segue do ponto do banco, sem pular nenhum evento. A SACL precisa auditar Delete (regra acima); a sentinela confere esse direito e acusa "SACL ausente" se faltar.

### O que vira item
- **4663** nas três pastas, agrupado por conta, processo, pasta e hora: "Leitura de segredos por explorer.exe (<conta>), 12 arquivos". `segredos` e `dados` são críticos, `cadastro` é ação.
- **4670** (permissão trocada nas três pastas): crítico.
- **4672** (logon com privilégio especial) de conta fora da lista e fora das contas de sistema: um item por conta por dia, atenção.
- **4698 a 4702** (tarefa criada, apagada, habilitada, desabilitada, alterada) com nome começando por `DashboardLotufo`: crítico. O próprio deploy mexe nessas tarefas; um item no horário de um deploy é esperado.
- **1102** (log limpo) e **4719** (política de auditoria alterada): crítico.
- A cada rodada, `auditpol /get` e a leitura da SACL conferem que a auditoria e a SACL continuam no lugar: "Auditoria de arquivos desligada", "Auditoria da alteração da política desligada" ou "SACL ausente em <pasta>" (crítico). Se a sentinela não consegue ler o log, a auditoria ou a SACL, vira item de atenção. Cada falha vira item quando começa e é regravada uma vez por dia enquanto durar, para não sumir da Saúde ao fim dos 7 dias com a sentinela ainda cega; corrigida e falhando de novo, avisa outra vez.

### Limites
Quem administra a VM pode desligar a auditoria ou limpar o log, mas cada uma dessas ações gera o próprio evento (4719, 1102), que a sentinela lê antes de perder o acesso. Parar o servidor para a sentinela (e o resumo diário some: tratado na issue de alertas). Eventos entre o fim da rodada e o início de uma limpeza do log podem se perder se o log for limpo antes da próxima rodada.

## Restaurar o banco a partir de um snapshot
1. Parar o servidor (tarefa agendada e qualquer uvicorn em 8080/8443).
2. Mover `dashboard.db`, `-wal` e `-shm` atuais para uma pasta de quarentena.
3. Copiar o snapshot escolhido para `C:\DashboardLotufo\dados\dashboard.db`. Se veio da cópia externa, antes conferir com `Get-FileHash` contra o `.sha256` ao lado dele. O snapshot local não tem `.sha256`: a conferência dele é o `integrity_check` do passo 4 (já foi ensaiado ao ser criado).
4. `backend\.venv\Scripts\python -c "import sqlite3; print(sqlite3.connect(r'C:\DashboardLotufo\dados\dashboard.db').execute('PRAGMA integrity_check').fetchone())"` → `('ok',)`.
5. Devolver os arquivos que o banco cita (todas as pastas de `PASTAS_ARQUIVOS`: notas, espelhos, modelos, evidências, certidões, protocolos, pleitos, curvas S, planilhas, FRC e as outras), da cópia local ou da externa (`<pasta externa>\arquivos`), sem apagar o que já está em `dados`: `cd backend; .venv\Scripts\python -c "from pathlib import Path; from app import backup; print(backup.copiar_arquivos(Path(r'C:\DashboardLotufo\dados\backups\arquivos'), Path(r'C:\DashboardLotufo\dados'), conferir=True), 'arquivos copiados')"`. Copia o que falta, relê pelo sha256 o que já está em `dados` e troca o estragado, e confere cada cópia. Se terminar com "arquivo(s) sem cópia", os listados estão estragados também no backup: tentar a outra cópia (local ou externa). Única pasta sem o sha256 no nome: `assinaturas` (`usuario-<id>`, a imagem que cada pessoa sobe); a restauração põe no lugar a do backup, então a assinatura trocada depois da última cópia volta à anterior e a que a pessoa tirou volta (o backup não apaga): conferir com quem envia.
6. Subir o servidor; as migrações pendentes rodam sozinhas em `create_app()`.

## Cópia do dono
Uma vez por semana (primeira rodada do backup depois de 7 dias da cópia anterior) e a qualquer hora pelo botão "Gerar cópia do dono agora" em Administração › Saúde (só admin), o servidor gera `dados\backups\dono\dashboard-dono-AAAAMMDD-HHMMSS.tar.age` (+ `.sha256`; ficam as 4 mais recentes). É um `.tar` cifrado no formato age (X25519) para a chave pública do dono, com o último snapshot válido, a pasta `segredos` e o clone do cadastro (sem `.git`). O `.tar` é montado em memória: nada em claro vai ao disco. A chave privada nunca está no servidor; o código recusa chave privada como configuração e não decifra nada.
- **Configurar (uma vez).** No Mac: `cd backend; python -m app.cli dono gerar-chave --saida <pasta>` (ou `rage-keygen`). Guarde `chave-privada-dono.txt` no cofre do dono e leve **só** a pública para a VM, em `<raiz>\segredos\chave-publica-dono.txt` (a variável `DASH_CHAVE_PUBLICA_DONO` aponta outro arquivo). Sem a chave pública nada é gerado e a Saúde mostra "Cópia do dono não configurada".
- **Saúde.** `/api/health` e a tela mostram `ultima_copia_dono` e `ultima_copia_dono_erro`; mais de 8 dias sem cópia aparece em destaque na Saúde.
- **Abrir no Mac.** Copiar o `.tar.age` (conferir o `.sha256`) e `rage -d -i <chave privada> <arquivo>.tar.age > pacote.tar`; `tar -xf pacote.tar` traz `banco/`, `segredos/` e `cadastro/`. Siga "Restaurar o banco a partir de um snapshot" com o `.db` de `banco/`.

## HTTP ou HTTPS
Decisão de 2026-09-02: produção em **HTTP na porta 80** (`http://<servidor>`), com `-SemTls` em `rodar_producao.ps1` e `instalar_autostart.ps1`. Ninguém precisa instalar certificado; a senha trafega em claro só dentro da rede interna. `DASH_SEM_TLS=1` tira a flag `secure` do cookie de sessão (o resto continua igual). Voltar a HTTPS = reinstalar a tarefa sem `-SemTls` e seguir a seção abaixo. Outra porta (VM em que a 80 é do IIS): `-Porta 8080` nos scripts de autostart, watchdog e deploy, e a regra de firewall abaixo com essa porta. Liberar a porta no firewall do servidor (uma vez, como administrador):
```
New-NetFirewallRule -DisplayName "Dashboard Lotufo HTTP 80" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow -Profile Domain,Private
```
Em outra porta, trocar o `80` do `-LocalPort` e do `-DisplayName` pela porta de `-Porta` (ex.: `"Dashboard Lotufo HTTP 8080"` e `-LocalPort 8080`).

## Certificado nos navegadores (só no modo HTTPS)
O certificado é autoassinado: cada máquina da rede precisa confiar nele uma vez, como administrador:
```
Import-Certificate -FilePath \\<servidor>\...\certs\cert.pem -CertStoreLocation Cert:\LocalMachine\Root
```
(ou por GPO, "Autoridades de Certificação Raiz Confiáveis"). Chrome e Edge usam o repositório do Windows; Firefox precisa de `security.enterprise_roots.enabled = true` ou importação manual.

## Contas
- Primeiro administrador: `cd backend; $env:DASH_DB_PATH='C:\DashboardLotufo\dados\dashboard.db'; .venv\Scripts\python -m app.cli criar-admin --nome ... --email ...`.
- Demais usuários (inclusive o segundo administrador): tela Administração → Usuários.
- Senha esquecida: não há reset pela tela hoje; criar outro usuário e desativar o antigo. Dívida registrada.
- Mexer em usuário ou sessão direto no banco não funciona, por desenho (issue #422): criar ou apagar uma conta, mudar
  qualquer coluna dela fora o contador de senha errada (`tentativas_falhas`, `bloqueado_ate`), e criar, mudar ou apagar
  uma sessão pelo `sqlite3`, DB Browser ou script avulso falha com "no such function: dash_conexao_app" e nada muda (os
  gatilhos da migração 062 só deixam passar a conexão da aplicação). Use a tela Administração → Usuários ou
  `python -m app.cli` (`criar-admin`, `desbloquear`, `redefinir-senha`). **Limite conhecido:** a proteção para o
  `sqlite3`, o DB Browser e o script comum; um script Python que registre ele mesmo a função `dash_conexao_app` passa
  pelos gatilhos, e apagar a linha final da auditoria não quebra a cadeia (a âncora fora do banco é a issue #424).
  Apagar ou trocar esses gatilhos, ou adulterar a cadeia da auditoria, aparece em Administração → Saúde › Segurança na
  conferência seguinte (de hora em hora e no boot), como "Proteção da tabela de usuários removida", "Proteção da
  tabela de sessões removida" ou "Cadeia da auditoria quebrada", e a proteção removida vira "Alerta de segurança" na
  auditoria (uma vez por incidente; "Alerta de segurança resolvido" quando volta). Para repor os gatilhos: o comando do
  parágrafo seguinte e reiniciar o serviço (a migração recria os seis).
- **Rollback para um commit anterior à issue #422** (automático do `deploy.ps1` ou à mão): o código antigo não
  registra `dash_conexao_app`, e com os gatilhos no banco ninguém entra (o login cria sessão) nem se cria ou altera
  usuário, embora o `/api/health` responda 200. Logo depois do rollback, com o serviço parado, no diretório `backend`
  do diretório pinado: `.venv\Scripts\python -c "import sqlite3; c=sqlite3.connect(r'C:\DashboardLotufo\dados\dashboard.db'); c.executescript('DROP TRIGGER IF EXISTS usuarios_protecao_insert; DROP TRIGGER IF EXISTS usuarios_protecao_delete; DROP TRIGGER IF EXISTS usuarios_protecao_update; DROP TRIGGER IF EXISTS sessoes_protecao_insert; DROP TRIGGER IF EXISTS sessoes_protecao_delete; DROP TRIGGER IF EXISTS sessoes_protecao_update;'); c.execute('DELETE FROM schema_migrations WHERE nome=?', ('062_protecao_usuarios.sql',)); c.commit(); print('gatilhos:', c.execute('SELECT COUNT(*) FROM sqlite_master WHERE name LIKE ?', ('%_protecao_%',)).fetchone()[0], 'migracao 062:', c.execute('SELECT COUNT(*) FROM schema_migrations WHERE nome=?', ('062_protecao_usuarios.sql',)).fetchone()[0])"`.
  Tem que imprimir `gatilhos: 0 migracao 062: 0`; outra coisa, não suba e refaça. Sem aspas duplas nem `$` dentro do
  comando, de propósito: o PowerShell repassa o texto ao Python sem mexer. Depois, subir o serviço. O próximo deploy
  de um commit com a #422 recria os gatilhos.

## Variáveis de ambiente
`DASH_DB_PATH` (obrigatória fora de dev), `DASH_DEV` (só dev; libera o caminho padrão `dados/dashboard.db` e sobe a instalação como `dev`), `DASH_INSTALACAO_ARQUIVO` (troca o caminho do arquivo da instalação assinada), `DASH_SEM_TLS` (produção HTTP: cookie sem `secure`), `DASH_LOG_DIR` (logs em arquivo), `DASH_BACKUP_EXTERNO` (cópia diária), `DASH_CHAVE_PUBLICA_DONO` (cópia do dono), `DASH_SEM_JOBS`, `DASH_SEM_FRONTEND`, `DASH_DIST_PATH`. RM (fase 5): `DASH_RM_URL`, `DASH_RM_USUARIO`, `DASH_RM_SENHA_ARQUIVO` (ou `DASH_RM_SENHA`, só dev), `DASH_RM_SISTEMA` (padrão `F`), `DASH_RM_HTTP_INSEGURO=1` (aceita URL http://, ver seção TOTVS RM), `DASH_RM_CONSULTA_NF` / `DASH_RM_CONSULTA_BAIXA` (padrão `DASH10` / `DASH11`), `DASH_RM_SIMULADOR` (pasta com `<CODIGO>.json`, dev/teste). Microsoft 365 (só envio de e-mail): `DASH_GRAPH_CLIENT_ID`, `DASH_GRAPH_TENANT` (passar o tenant explícito, ver "Envio de e-mail"), `DASH_GRAPH_TOKENS_DIR` (um token por pessoa), `DASH_GRAPH_SIMULADOR` (pasta onde o envio é gravado em vez de sair, dev/teste). Links de arquivo grande no protocolo: `DASH_SHAREPOINT_HOSTS` (hosts do OneDrive/SharePoint aceitos, separados por vírgula; sem ela todo link é recusado, ver "Envio de e-mail", item 9). Monitor do SIGA: `DASH_SIGA_TOKEN_ARQUIVO`, `DASH_SIGA_LINK_MODELO`, `DASH_SIGA_TAREFA` (ver "Monitor do SIGA"). Nenhuma chave de serviço pago: o produto não chama API paga (spec §15); o RM e o Microsoft 365 já são da empresa.

## TOTVS RM (fase 5, leitura)
A sincronização roda a cada hora (e no boot) quando `DASH_RM_URL`, `DASH_RM_USUARIO` e a senha estão definidos; sem eles o sistema segue com NF e recebimento registrados à mão. Botão "Sincronizar agora" e reconciliação em Administração → TOTVS RM.

1. **Conta de serviço** no RM (TI): usuário só de leitura, com acesso à aplicação Fluxus e às consultas abaixo. O usuário da API é o **código do usuário** do RM (ex.: `<código do usuário no RM>`, que pode ter espaço), não o login do Windows. A senha viaja em Basic **sobre HTTP** na LAN (porta da API). O cliente **recusa `http://` por padrão**: ligar com HTTP exige `DASH_RM_HTTP_INSEGURO=1` (`rodar_producao.ps1 -RmHttpInseguro`), decisão consciente do operador — conta dedicada, permissão mínima, e HTTPS no host do RM (ou túnel TLS) como pedido à TI.
2. **Senha em arquivo**: `C:\DashboardLotufo\segredos\rm.txt` (uma linha, UTF-8). `rodar_producao.ps1 -RmUrl <url da API do RM> -RmUsuario '...' -RmSenhaArquivo C:\DashboardLotufo\segredos\rm.txt` endurece a ACL da pasta `segredos` (SYSTEM + Administradores) antes de subir. Nunca colocar a senha na tarefa agendada nem no repositório. **O endereço da API** (`http://<servidor-rm>:<porta-da-api>`) também não está no repositório: ao reinstalar a tarefa, passe `instalar_autostart.ps1 -RmUrl ...` junto com `-RmUsuario` e `-RmSenhaArquivo`, ou crie `C:\DashboardLotufo\segredos\rm-endereco.txt` (uma linha) ou a variável `DASH_RM_ENDERECO` no nível da máquina. Sem nenhum dos três, o servidor sobe com o RM desligado e um aviso no log.
3. **Consultas SQL cadastradas** no RM (Serviços Globais → Gestão → Visões de Dados; aplicação RM Fluxus, "visível a todas as coligadas", todas com `(NOLOCK)`):

   `DASH10` — notas fiscais dos últimos 24 meses, todas as coligadas:
   ```sql
   SELECT M.IDMOV, M.CODCOLIGADA, M.NUMEROMOV, M.SERIE, M.DATAEMISSAO, M.VALORBRUTO,
          M.CODTMV, M.STATUS, M.CAMPOLIVRE1, M.CODCCUSTO, F.NOMEFANTASIA AS TOMADOR
   FROM TMOV M (NOLOCK)
   LEFT JOIN FCFO F (NOLOCK) ON F.CODCOLIGADA = M.CODCOLCFO AND F.CODCFO = M.CODCFO
   WHERE M.CODTMV LIKE '2.2.%' AND M.DATAEMISSAO >= DATEADD(MONTH, -24, GETDATE())
   ```
   `DASH11` — lançamentos a receber (baixas) ligados a esses movimentos:
   ```sql
   SELECT L.IDLAN, L.CODCOLIGADA, L.IDMOV, L.NUMERODOCUMENTO, L.VALORORIGINAL,
          L.VALORBAIXADO, L.STATUSLAN, L.DATABAIXA
   FROM FLAN L (NOLOCK)
   WHERE L.PAGREC = 1 AND EXISTS (SELECT 1 FROM TMOV M (NOLOCK)
         WHERE M.CODCOLIGADA = L.CODCOLIGADA AND M.IDMOV = L.IDMOV
           AND M.CODTMV LIKE '2.2.%' AND M.DATAEMISSAO >= DATEADD(MONTH, -24, GETDATE()))
   ```
   Confirmar na primeira execução: (a) `FLAN.IDMOV` existe na 12.1.2510 — se não, trocar o vínculo por `TMOVLAN` (`IDMOV` ↔ `IDLAN`) na `DASH11`; (b) `PAGREC = 1` é o lado **a receber** do razão (spec §15.3) — conferir com uma NF conhecida; (c) o `LEFT JOIN FCFO` (tomador) é opcional: se a coluna do cliente for outra, remover o join e o campo `TOMADOR`.
4. **Coligada por entidade**: campo `coligada_rm` de `cadastro/entidades.yaml`, aplicado por `cadastro aplicar` (Lotufo = 1; consórcios têm a própria coligada: Oriundi 12, Leblon 17, Integra BRT 18). Entidade sem coligada fica fora do casamento automático.
5. **Casamento NF → medição**: automático quando `CAMPOLIVRE1` da NF traz `<instrumento> - <nº>[ REAJ|PROJ]` (ex.: `IC 082/2025 - 12`) — instituir isso com o faturamento — ou quando há uma única medição protocolada, sem NF, com o mesmo valor. Com mais de uma medição candidata a NF fica sem vínculo automático (só uma linha no log `app.rm`; coluna "Ambíguas" das rodadas) e a pessoa anexa o PDF da nota na medição; o aviso "nota ausente do RM" cobre a medição que ficou sem nota. Recebimento: quando as baixas (status 1, 3 ou 4) somam o valor alocado, a medição vira "recebida" com a maior data de baixa; data implausível do RM (ano fora da faixa) fica guardada como bruta e não conta.
6. **Primeira rodada**: Administração → Sincronizar agora; conferir a reconciliação (NFs sem medição, medições sem NF, divergências) e o `dashboard.log` (`app.rm`).

## Cadastro versionado

O cadastro de obras mora em `cadastro/` (YAML), é editado pelo Leonardo com o Claude e entra no banco por comando. Não há tela.

A pasta vem de `DASH_CADASTRO_DIR` (produção: `C:\DashboardLotufo\cadastro`, clone do repositório privado `lotufo-cadastro`, atualizado com `git pull --ff-only` antes do `cadastro aplicar`; `rodar_producao.ps1` a exporta só para o servidor: na sessão do `cadastro aplicar` ela precisa ser definida à mão, `$env:DASH_CADASTRO_DIR = "C:\DashboardLotufo\cadastro"`); `--raiz` vence a variável. Sem nenhuma das duas, o comando lê `cadastro-exemplo/` (fictício, para testes e CI), que o `aplicar` recusa em banco com contratos, órgãos ou entidades de outro cadastro. `validar` e `aplicar` imprimem na primeira linha a pasta que leram: conferir antes de confiar no resultado.

1. Editar os arquivos, rodar `cd backend && .venv\Scripts\python -m app.cli cadastro validar --raiz <pasta do cadastro>` (ou com `DASH_CADASTRO_DIR` definida) e conferir a pasta impressa.
2. Commit e push no `lotufo-cadastro`, e `git -C C:\DashboardLotufo\cadastro pull --ff-only` na produção. O deploy
   (`scripts\deploy.ps1`) só atualiza o código e não toca esse clone.
3. No checkout de produção (`C:\DashboardLotufo\app\backend`), com `DASH_DB_PATH` (banco de produção) e `DASH_CADASTRO_DIR` (ou `--raiz`) definidos:
   `.venv\Scripts\python -m app.cli cadastro aplicar --usuario <e-mail do admin> --ensaio` e conferir o relatório;
   repetir sem `--ensaio`. O snapshot horário do backup cobre o antes.
4. Instrumento assinado já aplicado não se altera: correção é instrumento novo com `corrige: <chave>`.

O esquema de cada tipo de instrumento (apostilamento de reajuste SINFRA e MT-PAR, retificação, paralisação e reinício, endosso de garantia, aditivo de reajuste, `datas_base` com `aplica_a`, `pleitos_anteriores`) está comentado em `cadastro-exemplo/contratos/obra-propria.yaml`.

## Carga do histórico de medições

Caminho de uma carga de medições por CSV, do Mac à produção (`cadastro carregar-medicoes`, issue #262). Uma obra por arquivo; o nome do arquivo é o slug da obra, como em `contratos/`. O exemplo fictício é `cadastro-exemplo/medicoes/obra-propria.csv`.

### O CSV

Separador `;`, codificação UTF-8 (ou CP1252 do Excel), uma linha de cabeçalho. Dinheiro como texto brasileiro (`412.345,67`), datas `DD/MM/AAAA`, competência `AAAA-MM` ou `MM/AAAA`. A chave de cada medição é (obra, nº, tipo). Colunas:

| Coluna | O que é |
|---|---|
| `nº` | número da medição na obra (obrigatória) |
| `nº do órgão` | número da medição no órgão, se diferente |
| `tipo` | `execucao`, `projeto` ou `reajuste` (obrigatória) |
| `competência` | mês da medição (obrigatória) |
| `período` | período medido, texto livre (`10/03/2025 a 30/04/2025`) |
| `valor pedido` | valor cheio protocolado (obrigatória); vira o valor congelado da medição |
| `valor aprovado` | valor aprovado pelo órgão (obrigatória; pode ficar vazio na linha, e então não há atesto) |
| `data da aprovação` | data do atesto |
| `meio` | como veio a aprovação: `e-mail`, `smo`, `ofício`, `carimbo`, `protocolo físico`, `ci` ou `outro`; meio desconhecido é erro da linha |
| `nº do processo no órgão` | processo do órgão |
| `data do protocolo da nota` | data em que a nota foi protocolada no órgão |
| `NF` | número da NF, procurada no RM da empresa do contrato e vinculada se achada |
| `fonte` | de onde veio o dado (boletim, planilha, ofício); fica no atesto e na auditoria |
| `cancelar` | opcional: nº da medição que substitui esta; a linha é duplicata dela e será cancelada com motivo |
| `corrige competência` | opcional: `sim` corrige a competência de uma medição que já existe com outra |

### Onde o CSV mora

`medicoes/<slug>.csv` no repositório privado `lotufo-cadastro` (clone em `C:\DashboardLotufo\cadastro` na produção). **Nunca** no repositório público: só o exemplo fictício fica aqui.

### Passo a passo

1. **Ensaio no Mac**, numa cópia do snapshot horário (nunca no banco padrão nem em produção):

   ```bash
   scp <vm>:C:/DashboardLotufo/dados/backups/dashboard-AAAAMMDD-HHMMSS.db "$TMPDIR/ensaio.db"
   cd backend
   DASH_DEV=1 DASH_SEM_JOBS=1 DASH_DB_PATH="$TMPDIR/ensaio.db" \
     .venv/bin/python -m app.cli cadastro carregar-medicoes <pasta do cadastro>/medicoes/<slug>.csv --ensaio
   ```

2. **Ler o relatório**: uma linha por linha do CSV (`linha N: nº X tipo competência: categoria`) e o `Total:` no fim. Categorias:
   - `nova`: não existe medição com a chave; será criada (protocolada, congelada, com atesto, protocolo da nota e NF).
   - `igual`: competência, pedido e aprovado já batem; não faz nada (rodar duas vezes não duplica).
   - `valor diferente`: pedido ou aprovado diferem do banco; o pedido existente nunca muda, o aprovado novo entra como evento novo de atesto com a fonte.
   - `incompleta`: o CSV deixa vazio um valor que o banco tem; não altera.
   - `cancelamento` e `correção`: efeito das colunas `cancelar` e `corrige competência`.
   - `conflito`: mesmo nº e tipo com outra competência, medição cancelada/desistida no banco, ou competência já presente em NF, espelho ou planilha/carta em andamento (estado da planilha: planilha gerada, planilha enviada ou boletim recebido). **Conflito nunca se força**: o CSV se corrige e o ensaio se repete.
   - `erro`: a linha não se lê (valor, data, meio, competência); o relatório traz o número da linha do arquivo.

   Qualquer `erro` ou `conflito` faz a gravação recusar o arquivo inteiro, sem gravar nada.
3. **OK do Leo** sobre o relatório do ensaio, antes de qualquer gravação.
4. **Produção, pela VM, em dois scripts**: o `--ensaio` sai com 0 mesmo com linhas `correção` ou `valor diferente`, então o código de saída não substitui a leitura do relatório. Por isso o ensaio de produção e a gravação nunca ficam no mesmo script: primeiro o script 1 (atualizar o clone e ensaiar), depois a leitura do relatório e a conferência do `planilha_enviada_em`, e só com o OK o script 2 (gravar). A sessão `ssh` abre na pasta do perfil da conta, não em `C:\DashboardLotufo\app\backend`; por isso os dois começam com `Set-Location`. Comando nativo não encontrado não altera `$LASTEXITCODE`, então o `Set-Location` vem antes e cada comando nativo é seguido da checagem.

   **Script 1, pull e ensaio** (não grava nada):

   ```powershell
   Set-Location C:\DashboardLotufo\app\backend -ErrorAction Stop
   git -C C:\DashboardLotufo\cadastro pull --ff-only
   if ($LASTEXITCODE -ne 0) { exit 1 }
   $env:DASH_CADASTRO_DIR = "C:\DashboardLotufo\cadastro"
   $env:DASH_DB_PATH = "C:\DashboardLotufo\dados\dashboard.db"
   $csv = "C:\DashboardLotufo\cadastro\medicoes\<slug>.csv"
   .venv\Scripts\python -m app.cli cadastro carregar-medicoes $csv --ensaio
   if ($LASTEXITCODE -ne 0) { exit 1 }
   ```

   **Entre os dois**: ler o relatório do ensaio de produção (o que mudou desde o ensaio do Mac, categorias do passo 2) e, em cada linha `correção`, conferir o `planilha_enviada_em` (seção "Regra: competência de medição com planilha ou carta enviada"). Qualquer `erro`, `conflito` ou linha inesperada: parar, corrigir o CSV no repositório privado e repetir o script 1. O `-ErrorAction Stop` no `Set-Location` é necessário: no PowerShell 5.1 um `Set-Location` que falha só mostra o erro e o script segue na pasta errada. "Arquivo não encontrado" no script 1 significa que o CSV não está nesse caminho (ainda não chegou ao repositório privado, ou o `<slug>` está errado). "Banco não encontrado" com o caminho certo indica que a conta de deploy não tem leitura no arquivo do banco; "Banco ilegível" fica para banco corrompido ou `-wal`/`-shm` sem leitura.

   **Script 2, gravação** (só depois do OK sobre o relatório de produção):

   ```powershell
   Set-Location C:\DashboardLotufo\app\backend -ErrorAction Stop
   $env:DASH_CADASTRO_DIR = "C:\DashboardLotufo\cadastro"
   $env:DASH_DB_PATH = "C:\DashboardLotufo\dados\dashboard.db"
   $csv = "C:\DashboardLotufo\cadastro\medicoes\<slug>.csv"
   .venv\Scripts\python -m app.cli cadastro carregar-medicoes $csv --usuario <e-mail do admin>
   if ($LASTEXITCODE -ne 0) { exit 1 }
   ```

   Pelo Mac, cada script vai num `.ps1` temporário no Mac, fora do repositório, e roda na VM (`<vm>`, não `<servidor>`) com `-File`: no `-Command -` o comando nativo (`git`, `python`) consome o resto do script pelo stdin e ele para no meio (ver "Mudar de servidor"). Copiar com `scp script.ps1 <vm>:C:/Temp/x.ps1` ou, se o `scp` falhar, por stdin: `ssh <vm> 'powershell -NoProfile -Command "[Console]::In.ReadToEnd() | Set-Content -Path C:\Temp\x.ps1 -Encoding ASCII"' < script.ps1`; rodar com `ssh <vm> 'powershell -NoProfile -ExecutionPolicy Bypass -File C:\Temp\x.ps1'` e apagar o `x.ps1` depois. O shell remoto é PowerShell 5.1: sem `&&`, usar `;`. O `git pull` do cadastro privado precisa de credencial do GitHub na VM; se falhar, o script 1 sai com 1 antes do ensaio, que não deve rodar com o CSV velho. A gravação é uma transação por obra e termina em `GRAVADO: <obra> (<arquivo>), N medição(ões) criada(s)`. O snapshot horário do backup cobre o antes.
5. **Conferir**: `GET /api/health` com `banco: ok`; a aba Medições da obra mostra as medições novas; e o `audit_log` tem a ação `medicao.carga_historico` no contrato, com arquivo, criadas, corrigidas e as linhas. Rodar de novo sem nada novo não deixa rastro.

### Regra: competência de medição com planilha ou carta enviada

A carga **não** recusa a correção de competência (`corrige competência = sim`) de uma medição `protocolada` que já teve a planilha/carta enviada (`planilha_enviada_em` preenchido) e não tem NF vinculada: só recusa, como `conflito`, quando a medição está num estado da planilha, num estado de espelho, com a nota emitida, ou tem NF. Até a issue #383 entrar, o operador confere o `planilha_enviada_em` de cada linha `correção` do ensaio antes de gravar (na página da medição, ou numa consulta à tabela `medicoes` da cópia do banco usada no ensaio), e a correção de competência dessa medição vai pela tela, não pelo CSV (tirar a linha ou a marca `sim`). Quando a #383 entrar, atualizar esta regra.

## Espelho de NF (bloco 2)

**Como a operação usa.** Na página da obra, aba Medições, o cartão "Espelho de NF" aparece quando a obra
tem regra fiscal `ativa`. Gerar espelho → número, competência e os valores informados pelo órgão →
Conferir (uma linha por nota: valor, mão de obra, material, INSS, ISS, IRRF, líquido) → Gerar. A medição
nasce aí, em `espelho_gerado` (execução e reajuste, quando há reajuste), com os `.docx` para baixar.
Enviar ao faturamento → prévia do e-mail (destinatários, cópia, assunto, corpo editável, anexos com
tamanho) → Enviar: sai pela conta Microsoft de quem clicou (Minha conta) e a medição passa a
`espelho_enviado`. Gerar de novo cria versão nova (a anterior fica em "versões anteriores", com motivo);
o valor da medição segue a versão vigente. Opcional: anexar o PDF que o órgão mandou (evidência).
Protocolar continua pelo botão da linha da medição até o bloco 5. Obra sem regra ativa mostra "fluxo
antigo" e continua gerando o espelho pelo Power Automate.

**Arquivos.** `dados/espelhos/<sha>.docx` (gerados), `dados/modelos/<sha>.docx` (modelos copiados pelo
`cadastro aplicar`), `dados/evidencias/<sha>.pdf`. O snapshot horário do backup cobre só o banco; essas
pastas vão pela cópia dos arquivos do backup (issues #55 e #441). O caminho gravado no banco é relativo à pasta do banco.

**Receita de uma onda nova (habilitar uma obra):**
1. Copiar os modelos Word da obra do motor antigo (`~/dev/lotufo-automacao-medicao/modelos/<OBRA-ID>/`)
   para `cadastro/modelos/espelho/<slug>/`, um por saída, com o nome da chave da saída (`medicao.docx`,
   `caceres-reajuste.docx`...). O `slug` é o do arquivo do contrato (`cadastro/contratos/<slug>.yaml`).
2. Escrever `cadastro/espelho/<slug>.yaml` com `situacao: prova`, pela tabela "Regra por obra" do plano
   `docs/superpowers/plans/2026-09-22-bloco-2-espelho.md` (entradas, parcelas de rateio, retenções por
   tributo com `trunc`/`round`, saídas com emissor, município e modelo). Fatores de rateio vêm das
   fórmulas da planilha-motor, nunca inferidos.
3. `cd backend && .venv\Scripts\python -m app.cli cadastro validar`: acusa controle faltando no modelo,
   emissor desconhecido, nomes de arquivo repetidos.
4. Acrescentar em `backend/tests/test_espelho_cadastro_real.py` o gabarito da obra: as linhas do espelho
   real mais recente (valor, MO, material, INSS, ISS, IRRF), copiadas do `.docx` enviado ao faturamento (thread
   "Emissão NF" na caixa) ou do último modelo preenchido. Suíte verde ao centavo; 1 centavo de diferença
   é política de arredondamento errada, nunca se ajusta o gabarito.
5. Gerar o `.docx` no scratchpad com a regra real e abrir no Word contra o espelho real.
6. Trocar para `situacao: ativa`, commit, merge com OK do Leonardo, `deploy.ps1 -SemFrontend`,
   `cadastro aplicar --ensaio` (espera `espelho: 1 alterados`) e `aplicar` em produção.
7. Avisar as operadoras; desligar o fluxo do Power Automate daquela obra só depois do primeiro
   espelho real sair pelo sistema e o faturamento emitir a nota sem ressalva.

**Modelos sem controle.** O validador exige no `.docx` os controles (`w:tag`) `valor`, `mo`, `material`,
`inss`, `iss`, `irrf`, `valor_extenso`, `medicao`, `periodo` que a saída preenche; `ibs`/`cbs` são aviso.
Modelo sem controle se corrige no Word (Desenvolvedor → Controle de conteúdo de texto, com a tag) antes
da onda. Casos conhecidos: Região Oeste (sem `periodo` e sem `valor_extenso` na medição).

## Envio de e-mail pela conta de cada pessoa

Só o envio usa o Microsoft Graph. O sistema não lê caixa de e-mail nem SharePoint desde o bloco 9.

1. No portal do Entra ID, no aplicativo `Dashboard Lotufo` (Registros de aplicativo; *Permitir fluxos de
   cliente público* = Sim, sem segredo de cliente), em Permissões de API → Microsoft Graph → delegadas:
   `Mail.Send`, `Mail.ReadWrite`, `User.Read` e `offline_access` (nenhuma exige consentimento de
   administrador). Subir com `rodar_producao.ps1 -GraphClientId 00000000-0000-0000-0000-000000000000 -GraphTenant 00000000-0000-0000-0000-000000000000`.
2. Cada pessoa de operação abre Minha conta (clique no próprio nome), clica em "Conectar minha conta
   Microsoft", digita o código em microsoft.com/devicelogin com a conta da Lotufo e depois usa "Enviar e-mail
   de teste". O e-mail tem que aparecer na caixa de entrada E nos itens enviados dela.
3. O token fica em `C:\DashboardLotufo\segredos\usuarios\usuario-<id>.txt`. Apagar o arquivo desconecta
   a pessoa. Token sem uso por 90 dias expira: basta conectar de novo.
4. O sistema não lê caixa de e-mail. `Mail.ReadWrite` é exigida pelo Graph para criar o rascunho e subir
   anexo acima de 3 MB.
5. **Tenant**: `organizations` e `common` não funcionam nesta conta. O endpoint de código de dispositivo
   responde AADSTS50059 ("No tenant-identifying information found") e a tela mostra "invalid_request".
   Passar o tenant explícito (o domínio do tenant ou o GUID do diretório).
6. Administração → "Contas Microsoft conectadas" mostra quem conectou e quando o token foi gravado.
7. **Janela de envio como no Outlook** (2026-09-25): destinatários em etiquetas com sugestão enquanto digita, botão
   "Para" que abre "Adicionar Destinatários", Cc e Cco, anexos em cartões e a assinatura de quem envia. As
   sugestões vêm do cadastro (usuários, fiscais, faturamento, órgãos, obras e quem já recebeu e-mail) e, com as
   permissões delegadas `People.Read` e `User.ReadBasic.All` no aplicativo (nenhuma exige administrador), também do
   diretório da empresa. Quem conectou a conta antes precisa clicar em "Conectar de novo" em Minha conta para
   liberar o diretório; sem isso, o envio funciona igual e só as sugestões do cadastro aparecem.
8. **Assinatura**: o Graph não lê a assinatura do Outlook. Cada pessoa sobe a imagem da sua (PNG ou JPG, até 1 MB)
   em Minha conta; ela vai no fim de todo e-mail como imagem embutida. Arquivo em `dados/assinaturas/usuario-<id>`.
9. **Links de arquivo grande** (issue #118): o protocolo só aceita link cujo host seja exatamente um dos de
   `DASH_SHAREPOINT_HOSTS` (ex.: `<tenant>-my.sharepoint.com,<tenant>.sharepoint.com`, sem `https://`). O tenant
   da empresa não está no repositório: `rodar_producao.ps1` usa a variável no nível da máquina ou, sem ela, a
   primeira linha de `C:\DashboardLotufo\segredos\sharepoint-hosts.txt`. Sem nenhuma das duas, o log avisa na
   subida e a tela recusa todo link ("não estão liberados neste servidor"); nada sai com link errado.

## Nota fiscal (bloco 3)

**O que a pessoa faz.** Na linha da medição, botão **Notas** abre o painel: uma linha por nota esperada (as
saídas Lotufo do espelho vigente da medição) com valor, ISS, INSS, IRRF e líquido. Arrastar os PDFs que o
faturamento devolveu (vários de uma vez). A nota da Lotufo é lida (leiaute Prefeitura de Cuiabá / ISSNet,
que serve também a Várzea Grande, e DANFSe v2.0 do emissor nacional, usado pela Prefeitura de Cuiabá desde
09/2026), vinculada e **conferida ao centavo** contra a saída que atende (valor exato;
senão município): diferença de até 1 centavo num tributo aparece como "arredondamento" (o portal arredonda
onde algumas regras truncam); valor bruto, município, tomador ou tributo acima disso é "diverge" e vira aviso
no painel da engenharia, fechado por nota nova ou pelo botão **Justificar**. A nota divergente fica vinculada.
Quando toda saída esperada tem nota, a medição vai sozinha para **Nota emitida**; se o faturamento emitiu
menos notas do que o espelho previa, **Declarar completas** com justificativa. Nota de consorciada e a FRC
(marcar "é a fatura do consórcio") ficam como documentos da medição, sem leitura obrigatória. PDF sem texto
ou de leiaute desconhecido: o arquivo fica listado e a pessoa clica em
"Informar número, data e valor". O vínculo manual com uma NF do RM ("Vincular nota do RM") foi
retirado em 2026-09-25: a nota entra pelo PDF, e o RM confirma pelo número.

**O que o RM faz.** Na rodada horária, a NF do RM com o mesmo número (e mesma emissão ou mesmo valor) da nota
lida preenche a linha dela e a marca `confirmada` (valor igual) ou `divergente`; nota sem PDF nasce `so_rm`
e, quando o PDF chega, é a mesma linha que ganha os valores lidos. O casador só olha medições em andamento
que ainda faltam nota e **não são legado** (nascidas do espelho ou de competência a partir de 07/2026): valor
igual a uma saída esperada aloca com regra `saida_espelho`; o resto segue como antes (centro de custo, soma do
dia; a NF ambígua fica sem vínculo desde o bloco 9). Recebimento: medição `protocolada` cujas notas **da coligada da entidade do contrato** têm o
título quitado vira `recebida`; a NFS-e da Lotufo ao órgão em obra de consórcio (coligada 1, repassada pelo
consórcio depois) não segura. Avisos (na tela inicial desde o bloco 6): `nota_divergente`, `nota_ausente_rm` (5 dias
após o protocolo sem o RM ver a nota), `nota_cancelada_rm`, `nota_sem_protocolo`.

**Estados.** `espelho_gerado`/`espelho_enviado` → `nota_emitida` (pela nota) → `protocolada` → `recebida`.
`nf_emitida` deixou de existir: o botão "Emitir NF" saiu; "Receber" manual continua até o bloco 8.

**Remapeamento do legado (uma vez, com o serviço parado).** `nf_emitida` → `protocolada` (a data da nota vai
para `nota_emitida_em`), `recebida` continua, `prevista` sem valor → `cancelada`. O comando aplica a migração
021 antes:

```
cd C:\DashboardLotufo\app\backend
$env:DASH_DB_PATH = "C:\DashboardLotufo\dados\dashboard.db"
.venv\Scripts\python -m app.cli legado remapear --usuario <e-mail do Leonardo> --ensaio
.venv\Scripts\python -m app.cli legado remapear --usuario <e-mail do Leonardo>
```

Ensaio sobre a cópia da produção de 2026-09-22: 426 → protocolada, 0 previstas canceladas, 201 recebidas
mantidas, `foreign_key_check` vazio.

**Receita de deploy do bloco 3**, nesta ordem: criar `C:\DashboardLotufo\watchdog.pause` → parar a tarefa
agendada → backup `dashboard-PRE-BLOCO3-<data>.db` → atualizar o checkout pinado e o `dist` →
`legado remapear --ensaio` → `legado remapear` → `cadastro aplicar` (CNPJ dos órgãos) → subir → `/api/health`
→ observar uma rodada do RM no `dashboard.log` (`app.rm`: sem alocação nem sugestão sobre o legado) →
apagar o `watchdog.pause`.

## Documentos de protocolo (bloco 4)

**Operação (tela Documentos).** Arrastar o PDF da certidão: o sistema lê o tipo (federal, FGTS, trabalhista,
estadual SEFAZ/PGE-MT, municipal de Cuiabá, falência TJMT), a empresa pelo CNPJ, a natureza, a emissão e a
validade; a pessoa confere e grava. A leitura manda: os campos só são digitados quando o PDF não tem texto ou
o leitor não reconhece (empresa, tipo, emissão, validade, natureza; na falência a validade vazia é calculada
em 30 dias úteis descontando feriados nacionais). **Certidão positiva pura (ex.: estadual CPD) é recusada**,
sem digitação que a contorne. Repetida (mesma empresa, tipo, emissão e validade) é recusada. O **CRF do FGTS**
deve ser salvo pela página da Caixa com "Imprimir → Salvar como PDF" do navegador: salvo por driver de
impressora ele vira imagem (letras em curvas, sem texto) e cai no OCR (9 dos 13 CRFs do backup de 04/08/2026).
**PDF sem texto passa pelo OCR local** (decisão de 2026-09-24): as 2 primeiras páginas são desenhadas a 300 dpi
(`pypdfium2`) e lidas pelo Tesseract do servidor, um OCR por vez, prazo de 40 s; a leitura vai para conferência
com o aviso "lido por OCR" e a certidão gravada leva `observacao = "lida por OCR"`. Sem OCR instalado, ou se ele
falha, abre a digitação como antes. Prova de 2026-09-24 nos 23 PDFs sem texto da biblioteca: 22 com tipo, empresa
e validade iguais ao nome do arquivo; o 23º (falência da consorciada A) difere pelos feriados de 07/09 e 12/10, que o nome
não desconta. **Regularidade do mês**
(pacote do DP: folha, SEFIP/eSocial, INSS): anexar por empresa e competência; a partir do dia 10 o esperado é
a competência de dois meses antes (antes do dia 10, três meses antes ainda serve); o nome `MMAAAA - ...pdf`
pré-preenche a competência. **ZIP**: um por empresa, com as vigentes na data escolhida
(`Certidoes - <Empresa> - <data>.zip`, arquivos `<Empresa> - <TIPO> - <validade>.pdf`).

**O que é exigido** mora no cadastro: `orgaos.yaml` (`documentos_medicao`, `documentos_reajuste`; chaves
`federal fgts trabalhista estadual municipal falencia regularidade`), exceção por contrato no YAML do contrato
(mesmos campos; Deciolândia está com as duas listas vazias) e composição dos consórcios em `entidades.yaml`
(`consorciadas`, e `regularidade_propria: true` quando a folha é do consórcio, como no Complexo Leblon). Mudar:
editar o YAML → `cadastro validar` → `cadastro aplicar --ensaio` → `cadastro aplicar`. O checklist do protocolo
e os alertas "Documentos da empresa" e "Regularidade do mês" seguem o cadastro.

**Carga das certidões** (ato separado, com backup e OK): baixar a biblioteca "Certidões (documentos)" do site
**DepartamentodeEngenharia** (`/sites/DepartamentodeEngenharia/Certidoes`, uma pasta por empresa; o endereço
antigo no site GestaoContratosFaturamento dá 404 desde set/2026) para uma pasta local (o sistema não lê
SharePoint) → backup do banco →
`python -m app.cli documentos importar <pasta> --usuario <e-mail do Leonardo> --ensaio` → conferir o
relatório (gravadas, repetidas, vencidas, positivas, sem leitura) → rodar sem `--ensaio` → a operação digita os
`sem_leitura` pela tela. Ensaio de 2026-09-23 sobre cópia da produção com o backup de 04/08: 20 gravadas,
27 vencidas, 2 positivas (estaduais das consorciadas A e B), 14 sem texto. **Carga real em 2026-09-24 08:36** (backup
`dashboard-PRE-CERTIDOES-20260924-083617.db`), biblioteca baixada no dia (92 PDFs): 33 gravadas, 33 vencidas,
3 positivas (SEFAZ-MT consorciada B ×2 e consorciada A, positivas de fato), 23 sem texto (FGTS salvo como imagem, quase todos).

**OCR no servidor (instalação única).** Tesseract: `winget install --id UB-Mannheim.TesseractOCR -e` (fica em
`C:\Program Files\Tesseract-OCR`). Português: `por.traineddata` do repositório oficial `tesseract-ocr/tessdata_fast`
em `C:\DashboardLotufo\dados\tessdata\` (ao lado do banco; o sistema acha sozinho). Outro lugar: `DASH_TESSDATA`
(pasta do idioma) e `DASH_TESSERACT` (executável). Sem os dois, o OCR fica desligado e nada quebra. Teste real:
`DASH_TESSDATA=<pasta> pytest tests/test_leitura_pdf.py` (sem a variável, o teste do OCR é pulado).

**Receita de deploy do bloco 4**: `deploy.ps1` com frontend (a migração 024 aplica na subida) →
`cadastro aplicar --ensaio` e real (nomes curtos, Montante, consorciadas, regularidade na SINFRA, exceção da
Deciolândia) → `/api/health`. A carga das certidões vem depois, com a pasta do dia.

## Protocolo de medição (bloco 5)

**Operação (aba Protocolo do contrato).** "Pronto para protocolar" mostra o checklist de documentos. Abaixo,
"Novo protocolo": escolher a etapa, as medições e digitar o número do ofício (CT). O sistema grava o número no
padrão do órgão (`CT-301-LT-2026`) e acusa ofício repetido. No cartão do protocolo:

1. anexar as peças técnicas que o órgão pede (PDF; a planilha editável é `.xlsx` e vai solta no e-mail);
2. conferir ou editar o texto da carta (vazio volta ao padrão) e **Montar**: carta com o papel timbrado,
   notas, certidões e peças na ordem do órgão, num PDF só (`CT-301-LT-2026 - Obra - 23ª Medição (09.2026).pdf`);
3. baixar, assinar no DocuSign e arrastar o assinado de volta;
4. marcar os protocolos do mesmo e-mail e abrir a **Prévia**: destinatários, cópias, assunto, corpo, anexos
   com tamanho e pendências. Com pendência, o envio exige justificativa (fica gravada);
5. **Enviar**: o e-mail sai pela conta de quem envia. Só depois de aceito a medição vira `protocolada`,
   ligada ao envio;
6. quando o órgão responder, registrar o número de protocolo do órgão e o comprovante.

A **conferência do assinado é aviso**, não trava: páginas iguais às do montado (semelhança ≥ 0,90), o mesmo
`Docusign Envelope ID` em todas e, no fim, só o "Certificado de Conclusão" (pode ter várias páginas). Página
trocada, envelope misturado ou PDF sem carimbo viram pendência. Provado em 2026-09-24 com três PDFs reais
(Cavalaria CT-291, 92 páginas; MT-388 CT-073 com 4 páginas de certificado; Orla CT-286 sem assinatura).

**Famílias e etapas.**

| Família | Etapas | PDF montado | Solto no e-mail | Marca protocolada |
|---|---|---|---|---|
| MTPAR | única | carta, notas, certidões | — | sim; execução e reajuste em ofícios separados; pede devolutiva |
| SES | única | capa, carta, notas, certidões, peças (com divisórias) | — | sim; execução e reajuste podem ir juntos |
| SINFRA | 1) medição assinada | carta, peças | planilha editável | não |
| SINFRA | 2) nota, certidões e regularidade | — (sem carta) | notas, ZIP das certidões, CNO, regularidade | sim, com o ofício da etapa 1 |
| Prefeitura | única | carta, notas | ZIP das certidões, peças soltas | sim |

Na SINFRA, a execução e o reajuste vão no mesmo e-mail, cada um no seu PDF e com carta própria (o reajuste usa
`reajuste_carta_*`). Limite de 25 MB por documento na SINFRA e 25 MB por e-mail (limite do Exchange sobre a
mensagem codificada).

**Onde mudar.** Textos da carta e do e-mail: `cadastro/cartas.yaml` (por família; campos entre chaves são
preenchidos pelo sistema, os desconhecidos ficam visíveis). Destinatário da carta, peças (ordem, `exigida`,
`solto`, `naturezas`) e ordem das certidões: `cadastro/orgaos.yaml`. Fiscal da carta (cargo, tratamento,
portaria), `objeto_completo` e comprovante do CNO (`cno_pdf`): YAML do contrato. Papel timbrado: `logo` e
`fundo` do emitente em `cartas.yaml`. Depois: `cadastro validar` → `aplicar --ensaio` → `aplicar`.
Levantamento das cartas reais: `docs/levantamento-protocolo-2026-09-24.md`.

**Garantia do contrato** (issue #65, decisão de 15/10/2026). No YAML do contrato: `garantia: {apolice, vigencia_fim, arquivo}`
(`arquivo` é o PDF, dentro da pasta do cadastro, copiado por `aplicar`). Cada instrumento `endosso_garantia` com `vigencia_fim` e `apolice` (a do contrato; sem `apolice` o `cadastro validar` recusa) substitui a vigência
da garantia (vale o de data mais recente; instrumento aplicado não muda, correção é instrumento novo). A garantia
avisa aos 30 dias (ação aos 15, crítico vencida) para operação e diretoria, na tela Documentos e em Avisos, até
o marco `baixa_garantia`; contrato sem `garantia` no cadastro não avisa. A ART saiu do contrato (#239): não há
número, PDF nem aviso, e `art:` preenchido no contrato é recusado pelo `cadastro validar` (`art: null` passa). A ART
continua só como peça `art` do pacote do protocolo, em `pecas` do órgão em `orgaos.yaml`.

**Receita de deploy do bloco 5**: `deploy.ps1` com frontend (a migração 025 aplica na subida; `fpdf2` entra no
venv pelo `requirements.lock`) → `cadastro aplicar --ensaio` e real (9 órgãos e `geral.cartas`) → `/api/health`.

## Monitor do SIGA (issue #327)

O robô do SIGA (fora deste repositório) manda a cada 15 minutos o que leu para `POST /api/siga/leituras` e pergunta
o que acompanhar em `GET /api/siga/processos`, as duas com `Authorization: Bearer <token>`. As telas leem
`GET /api/siga` (sessão). Nada se apaga: leitura repetida não cria linha. Cada pedido tem o teto geral de 2 MB:
rodada maior vai em mais de um POST com o mesmo `lido_em` (cada um grava só o que traz).

1. **Token em arquivo**: `C:\DashboardLotufo\segredos\siga-token.txt` (uma linha, UTF-8, ao menos 32 caracteres
   aleatórios). Gerar e gravar sem BOM (o `>` do PowerShell 5.1 grava UTF-16 e o arquivo é recusado):
   `$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [IO.File]::WriteAllText('C:\DashboardLotufo\segredos\siga-token.txt', [Convert]::ToBase64String($b), (New-Object Text.UTF8Encoding $false))`.
   O mesmo token vai para o robô (item 4). Nunca no repositório nem na tarefa agendada.
2. **Variável** `DASH_SIGA_TOKEN_ARQUIVO` com o caminho do arquivo, no nível da máquina (como `DASH_RM_ENDERECO`), e
   reiniciar a tarefa de `<servidor>` pela skill `deploy`. O arquivo é lido a cada pedido: trocar o token não pede
   reinício. Sem a variável (ou com o arquivo vazio ou ilegível), as duas rotas do robô respondem 503 "Monitor do
   SIGA não configurado"; token errado ou ausente, 401.
3. Conferir: `Invoke-RestMethod http://<servidor>/api/siga/processos -Headers @{Authorization = "Bearer <token>"}`
   devolve a lista (vazia antes da primeira rodada).
4. **Lado do robô** (issue #331): o robô guarda o token no cofre de credenciais do Windows da conta em que a tarefa
   dele roda, pelo `salvar-token-dashboard.bat` da pasta do robô (cola o token uma vez; rodar de novo substitui),
   como já faz com a senha do MT Login e a conta Microsoft. Ele fala com a dashboard em `http://localhost`, porque
   roda no mesmo servidor. No início de cada rodada pede a lista (`GET /api/siga/processos`) e a junta com a lista
   local dele (o mesmo código conta uma vez; processo da dashboard só com número fica fora, porque abrir pelo número
   exige captcha); no fim, logo depois de gravar o estado local, manda a leitura (`POST /api/siga/leituras`). Dashboard
   parada, sem token ou token recusado: o robô registra "dashboard: ..." no `dados\monitor.log` dele e a rodada e o
   e-mail seguem normais.
5. **Trocar o token**: gerar o arquivo de novo (item 1) e rodar o `salvar-token-dashboard.bat` com o valor novo. Trocado
   só de um lado, o robô registra 401 no log dele e a leitura para de chegar; as movimentações não se perdem (a
   próxima rodada com os dois lados iguais manda tudo o que está no SIGA), só as rodadas do intervalo ficam sem
   registro de leitura.
6. **Conferir pela tela**: Administração › Saúde mostra a última leitura do monitor e quantos processos ele acompanha;
   a tela SIGA mostra "Lido às" com a hora da rodada e, sem leitura há mais de 2 horas úteis, "O monitor do SIGA não
   lê desde …".

**Link do SIGA na etapa 4**: a operação cola o link que o órgão mandou (ou só o código do parâmetro `n=`) no campo
"Link do SIGA" do protocolo enviado ou do registro por fora; o servidor grava o código em `siga_processos`, ligado ao
protocolo, e o robô passa a acompanhá-lo pela lista de `GET /api/siga/processos`. O domínio aceito é o de
`DASH_SIGA_LINK_MODELO` (`https://`, com `{codigo}`); sem a variável só o código colado vale.

O processo cujo número é **igual** (maiúsculas, sem espaços) ao "Nº do protocolo no órgão" de um protocolo enviado,
ou ao número de um envio registrado por fora, fica ligado à medição na rodada seguinte do robô. Número parecido não
liga.

**Link "Abrir no SIGA"** (tela SIGA): a variável `DASH_SIGA_LINK_MODELO` guarda o modelo do link de acompanhamento,
começando em `https://` e com `{codigo}` no lugar do código do processo (o que vem no parâmetro `n=` do link que o
órgão manda). Sem a variável, ou com modelo sem `https://` ou sem `{codigo}`, a tela não mostra o link.

**Atualizar pela tela** (issue #342): quem vê a tela SIGA pede a leitura de um processo ou de todos
(`POST /api/siga/atualizar`). O servidor grava o pedido e manda o Windows iniciar a tarefa agendada do robô
(`schtasks /Run /TN <tarefa do robô>`, sem shell, com prazo de 15 segundos); com uma rodada iniciada há menos de 10
minutos e sem fim não dispara, e o robô atende o pedido ao terminar a rodada atual. Clique repetido com o pedido
ainda em aberto não cria outro pedido, mas dispara de novo.

1. **Variável** `DASH_SIGA_TAREFA` com o nome da tarefa agendada do robô, no nível da máquina (como
   `DASH_SIGA_TOKEN_ARQUIVO`), e reiniciar a tarefa de `<servidor>` pela skill `deploy`. Sem a variável, os botões
   somem da tela (`pode_atualizar: false` em `GET /api/siga`) e o pedido responde 503.
2. **Conferir que o servidor inicia a tarefa**: a dashboard roda como SYSTEM, que pode iniciar qualquer tarefa
   agendada. Num PowerShell de administrador, `schtasks /Query /TN "<tarefa do robô>"` mostra a tarefa com o nome
   exato da variável. Depois, na tela SIGA, "Atualizar todos": em até 2 minutos `robo.estado` de `GET /api/siga`
   passa a `lendo`. "O Windows não iniciou o robô: …" traz a saída do `schtasks` (nome errado, tarefa
   desabilitada); "O robô não começou" quer dizer que o Windows aceitou, mas a tarefa não rodou (o usuário do robô
   desconectado do servidor).
3. **Conversa com o robô** (rotas de serviço, com o mesmo token das leituras). No início, `POST /api/siga/rodadas`
   ("comecei"): o servidor responde `rodada_id`, `tipo` e `processos` (o mesmo formato de `GET /api/siga/processos`).
   A rodada é completa com pedido "todos" em aberto ou quando a última rodada completa terminada começou há 14
   minutos ou mais (`tipo: automatica` quando é completa por tempo, que é a da tarefa de 15 em 15 minutos; `pedido`
   nos demais casos); senão, só os processos pedidos. Fora do horário, o robô manda `{"so_pedidos": true}` (issue
   #347): o servidor não abre rodada completa por tempo e só atende os pedidos em aberto, que valem a qualquer hora.
   `rodada_id: null` quer dizer nada a ler. As leituras continuam
   por `POST /api/siga/leituras`. No fim, `POST /api/siga/rodadas/<id>/fim` com
   `{"nao_lidos": [{"codigo" ou "numero", "motivo"}]}` ("terminei"); se cair, `POST /api/siga/rodadas/<id>/falha` com
   `{"motivo"}`. Antes de encerrar, o robô pergunta de novo em `POST /api/siga/rodadas` se chegou pedido. Rodada já
   terminada recusa outro fim ou falha (409). O motivo é gravado com até 300 caracteres. "Comecei" repetido com a
   rodada aberta há menos de 10 minutos devolve a mesma rodada (o robô repetindo por falta de resposta).
4. **O que a tela mostra** (bloco `robo` de `GET /api/siga`): `lendo` (rodada iniciada há no máximo 12 minutos e
   sem fim), `na_fila` (pedido em aberto) ou `parado`; os pedidos em aberto, com quem pediu e quando; e os avisos:
   o Windows recusou o último disparo, pedido parado há mais de 2 minutos sem rodada, a última rodada terminada
   falhou ou deixou processos sem ler ("não lido às HH:MM: …" por processo e "N de M processos não foram lidos"), e
   rodada iniciada há mais de 12 minutos sem fim (só a mais recente; o Windows encerra o robô aos 10). Cada aviso de rodada vale até
   a próxima rodada terminar sem aquele problema; o do disparo, até o próximo disparo aceito.

## Tela inicial e avisos (bloco 6)

**Início** (home da operação e do admin; a diretoria abre o Painel até o bloco 8): três números e os
avisos. "Medições protocoladas no mês: X de N": N são os contratos `ativo` sem encerramento iniciado;
X, os que têm ao menos uma medição cuja **primeira** data de protocolo cai no mês. "Valor protocolado"
soma o valor protocolado (cheio) dessas medições; o mês anterior segue a mesma regra. Reprotocolo não conta
de novo.

**Catálogo em vigor** (`app/avisos.py`, registro único; a tela só desenha):

| Aviso | Nível | Some quando |
|---|---|---|
| Documentos da empresa (um por empresa) | ação se venceu ou falta, atenção se vence em breve | a certidão válida é gravada em Documentos |
| Regularidade do mês (a partir do dia 10) | ação | a regularidade da competência esperada é anexada |
| Nota divergente do espelho | ação | a nota é justificada ou trocada |
| Nota ausente do RM (5 dias após o protocolo) | atenção | o RM confirma a nota |
| Nota cancelada no RM | ação | outra nota é vinculada à medição |
| Execução vencendo (60 dias) | atenção; crítico a 30 dias e depois de vencida | aditivo ou apostilamento de prazo carregado no cadastro |
| Vigência vencendo (60 dias, só órgão com `vigencia_automatica: false`) | idem | idem |

Contrato suspenso ou em encerramento não tem aviso de prazo. Aviso nenhum some por "dispensar": só por ato
real. Ordem: nível, depois dias (o que vence antes, ou já venceu, primeiro), depois obra. O bloco 7 troca o
aviso de prazo pela versão completa e acrescenta os de reajuste; o bloco 8, o de pagamento.

**Medições** (menu): as medições entre o espelho e o pagamento, com o próximo passo e a data do último
marco; filtro por obra e estado; a linha abre a obra.

**Página da obra**: cabeçalho (órgão, instrumento, execução e vigência com os dias, valor vigente e cota da
Lotufo, status) e as abas Medições (espelho, medições e protocolo), Notas, Documentos, Reajuste, Prazos e
Contrato. Reajuste, Prazos e Contrato só mostram o cadastro (mudar é no YAML). Links antigos continuam:
`/contratos/7/protocolo` abre Medições; `/cronograma` e `/aditivos` abrem Contrato.

## Reajuste, prazos e encerramento (bloco 7)

**Ciclo do reajuste** (`app/reajuste.py`, aba Reajuste da obra). Um ciclo por data-base do contrato. O reajuste
vale a partir do mês do aniversário; o aviso "pleito não enviado" começa 30 dias antes do dia 1º desse mês
(atenção antes do aniversário, ação depois). Enviado o pleito, vira "apostilamento pendente há N dias" (a
diretoria vê depois de 90 dias). Fecha com o `apostilamento_reajuste` do cadastro da mesma data-base e ciclo (sem
`data_base` nos dados vale a única data-base; sem `ciclo`, o ano da eficácia ou da data). Só o ciclo corrente
conta. `sem_reajuste: true` desliga.

**Prazo** (`app/prazos.py`, aba Prazos). O relógio é a execução vigente: aviso a 60 dias (atenção), crítico a 30;
vencida sem pedido vira "instrumento pendente" crítico, também para a diretoria. Pedido enviado troca o aviso por
"prorrogação pedida em DD/MM (CT), instrumento pendente há N dias" até entrar um instrumento de prazo assinado na
data do envio ou depois. Vigência só conta em órgão com `vigencia_automatica: false`. Folga (vigência − execução)
menor que a do contrato (`folga_vigencia_dias` no YAML) ou a do órgão vira "folga quebrada". Paralisação aberta
(última `paralisacao` sem `reinicio` depois) suspende o aviso de execução e vira "obra paralisada" para a
diretoria. Endosso do seguro-garantia: instrumento de prazo assinado nos últimos 60 dias sem `endosso_garantia`
(com `referente: <chave>` ou data posterior) avisa (atenção até 5 dias, ação depois). Instrumento assinado depois do
fim da execução que prorroga é marcado "retroativo" e nunca recusado.

**Pleitos** (`app/pleitos.py`): reajuste, prorrogação de prazo e comunicação de conclusão, com o mesmo caminho do
protocolo (ofício gerado, anexos, montar, assinar no DocuSign, arrastar o assinado, prévia, enviar). Anexos
exigidos: memória de cálculo e cronograma no reajuste, cronograma no prazo. No prazo, a "Curva S.xlsx" (competência,
previsto vigente, previsto anterior à última repactuação e medido, acumulados; issue #293) entra sozinha nos anexos ao
criar o pedido e é trocada pela do dia a cada "montar" (fica em `curvas/` na pasta de dados). Ela não se remove, e o
nome "Curva S.xlsx" não se usa em anexo arrastado no prazo. O "O que falta", a prévia e o envio comparam as células da
curva anexada (competência e centavos) com a curva dos dados de agora, não os bytes do xlsx (issue #447: o zip muda
com o sistema e as versões do openpyxl sem o dado mudar). Curva que falta, que mudou desde o "montar" (cronograma
novo, medição mudada ou cancelada, versões superadas) ou cujo arquivo sumiu de `curvas/` ou não bate com o sha256
trava o envio, e a justificativa não libera; o botão "Atualizar curva S" troca (ou regrava) a curva sem montar a carta
de novo, então a assinada do DocuSign fica. Sem previsto vigente, não há curva. Justificativa de prazo que fala em
chuva sem paralisação cadastrada vira pendência. Destinatários: `protocolo_para` do órgão, fiscal vigente e
`destinatarios_extras`; cópia `protocolo_copia` do órgão mais `copia_extras` do contrato. Textos em `cartas.yaml` (`pleito_reajuste`, `prazo`,
`conclusao`; `<campo>_<família>` vence o comum: o reajuste da SINFRA cita a IN 001/2024).

**Medição final** (tabela de medições, "Medição final"): põe o contrato em encerramento (se ainda não estava).
Desmarcar pede motivo e só tira o encerramento se nenhuma outra medição for final. `cadastro aplicar` preserva o
encerramento de contrato com medição final mesmo com o YAML em `ativo` e avisa para atualizar o YAML. Em
encerramento os avisos de prazo param e fica "conclusão não comunicada" até a carta de conclusão sair.

**Cadastro** (YAML do contrato):

```yaml
folga_vigencia_dias: 78            # vence a do órgão
instrumentos:
- {chave: paralisacao-2026-02, tipo: paralisacao, data: '2026-02-01', numero: Termo de Paralisação 004/2026}
- {chave: reinicio-2026-05, tipo: reinicio, data: '2026-05-05'}
- {chave: endosso-ta-3, tipo: endosso_garantia, data: '2026-08-01', referente: ta-3}
- {chave: marco-provisorio, tipo: marco_encerramento, data: '2026-10-01', marco: provisorio}  # conclusao, provisorio, definitivo, baixa_garantia
pleitos_anteriores:                 # enviados antes do sistema; não duplicam ao reaplicar
- {tipo: reajuste, oficio: CT-122-LT-2026, data: 2026-04-23, data_base: 2023-03, ciclo: 2026}
- {tipo: prazo, oficio: CT-282-LT-2026, data: 2026-08-07, dias: 180}
- {tipo: conclusao, oficio: CT-245-LT-2026, data: 2026-07-31}
# corrigir pleito já aplicado com data ou ofício errado (#399): o item com `corrige` substitui o antigo na lista;
# só pleito do cadastro (o da tela não se corrige aqui); `data` dentro de `corrige` é a gravada, opcional, e confere
- {tipo: prazo, oficio: CT-300-LT-2026, data: 2026-05-06, dias: 180, corrige: {oficio: CT-300-LT-2026, data: 2026-08-14}}
- {tipo: valor, oficio: CT-301-LT-2026, data: 2026-03-27, valor: '1.000.000,00', objeto: 1ª RPFO}  # pedido de aditivo de valor; atendido pelo aditivo de valor assinado depois
```

**Receita de deploy do bloco 7**: `deploy.ps1` com frontend (migração 026 na subida) → `cadastro aplicar
--ensaio` e real (textos dos pleitos, 20 pleitos anteriores, folgas de Espaço Show e Granito, paralisações da MT-402
e da Coxipó 2ª) → `/api/health`.

## Diretoria e QDOP (bloco 8)

**Tela da diretoria** (`app/diretoria.py`; menu "Diretoria", home da diretoria; `/painel` abre ela). Tudo na
cota da Lotufo (`contratos.cota`, arredondamento único); valor de uma medição é o atestado quando houver, senão o
protocolado.

- **Onde está o dinheiro:** medido esperando nota (espelho gerado ou enviado), nota emitida esperando protocolo,
  protocolado esperando pagamento (por faixa de dias desde o **primeiro** protocolo: até 30, 31 a 60, mais de 60,
  e por órgão), recebido no mês; à parte, os reajustes esperando apostilamento.
- **O mês e o ano:** medido da competência atual contra o previsto do cronograma vigente e o mesmo mês do ano
  anterior, acumulado do ano e a série de 12 meses.
- **Próximos meses:** faturamento previsto pelo cronograma (o recebimento previsto saiu na #255, motor de atraso de pagamento).
- **Carteira:** saldo a executar dos contratos ativos sem encerramento, ritmo (média dos últimos 6 meses), meses de
  produção, participação por órgão e os contratos que terminam nos próximos 183 dias.
- **Obras:** as linhas do QDOP com farol (vermelho: aviso crítico; acao: aviso de Ação; atencao: aviso de Atenção; verde:
  nenhum) e o motivo.

**Prazo normal do órgão:** saiu da Diretoria na #255 (motor de atraso de pagamento; decisão de 19/10/2026): não
há mais aviso de pagamento atrasado nem recebimento previsto. O a receber da Diretoria mostra só a idade (faixas e
maior número de dias). O "previsto" da tela A receber ainda usa o 3º quartil do órgão (com menos de 10 amostras,
30 dias); a #255 não tratou dele.

**Total a receber:** enquanto `geral.yaml` tiver `diretoria.total_a_receber_liberado: false`, a tela mostra
quantidade e dias do protocolado, sem valor ("a conciliar"). Depois da conciliação com a controladoria: trocar para `true`, `cadastro
validar`, `aplicar --ensaio`, `aplicar`.

**QDOP** (`app/qdop.py`, botão "Exportar QDOP (.xlsx)" ou `GET /api/diretoria/qdop.xlsx`): escrito sobre o modelo
`cadastro/modelos/qdop/qdop-modelo.xlsx` (cabeçalho e logo do oficial, linha 14 como estilo, rodapé), com valores e
não fórmulas. Colunas na cota; "faturados" e reajuste somam as medições faturadas (nota emitida, protocolada ou
recebida), que é o que bate com o oficial de 22/09/2026; contratante e tipo vêm de `nome_qdop` e
`tipo_contratante` do órgão; descrição do `objeto_completo`. Status: CONCLUÍDA (encerramento), PARALISADA
(paralisação aberta ou contrato suspenso), EM ANDAMENTO.

**Trocar o modelo do QDOP:** recortar do oficial novo com o script da tarefa 8.1 do plano (cabeçalho 1-13, linha
14 vazia, rodapé em 16-17, formulas do cabeçalho vazias), conferir no Excel (PDF da página 1), salvar em
`cadastro/modelos/qdop/qdop-modelo.xlsx` e aplicar o cadastro (o arquivo é copiado para a pasta de dados pelo hash).

**Receita de deploy do bloco 8:** `deploy.ps1` com frontend (sem migração) → `cadastro aplicar --ensaio` e real
(nome e tipo do contratante nos 10 órgãos, `objeto_completo` das 22 obras, `diretoria` e `qdop` no geral) →
`/api/health` → abrir a Diretoria e exportar o QDOP.

## Conciliação dos recebidos do legado (2026-09-25)

As medições do legado ficaram `protocolada` sem nota ligada, e o casador do RM não olha para elas
(competência antes de 07/2026). `python -m app.cli conciliacao historica --usuario <e-mail> [--ensaio]` parte
de cada uma e procura a nota do RM que a pagou: coligada da entidade do contrato, centro de custo do contrato,
emitida de 15 dias antes a 120 dias depois do último protocolo, valor cheio da medição (uma nota, ou 2 a 3 do
mesmo dia somando). Só liga quando a medição tem uma única opção e nenhuma nota dela serve a outra medição
(regra `conciliacao_historica`, origem `detectado`); depois a regra normal marca `recebida` quem tem o título
quitado, com a data da baixa. Roda uma vez, com backup antes, `--ensaio` e depois real.

`conciliacao antiga` faz o mesmo com as notas de jun/2021 a set/2024, lidas direto do RM pelas consultas
**DASH12** (notas, igual à DASH10 sem o limite de 24 meses, faixa fixa `20210601` a `20241001`, sem o tomador) e
**DASH13** (baixas dessas notas), cadastradas em 25/09/2026 no RM Fluxus, visíveis a todas as coligadas. Só a
nota que liga e as baixas dela entram no banco. Precisa das variáveis do RM no shell (as mesmas da tarefa:
`DASH_RM_URL`, `DASH_RM_USUARIO`, `DASH_RM_SENHA_ARQUIVO`, `DASH_RM_HTTP_INSEGURO=1`). O RM trocou os centros de
custo por volta de 2024; a obra que tem notas no centro velho lista esse centro em `centros_custo_anteriores_rm`
no YAML (Alta Floresta 6.004.003, Região Oeste 6.003.001), e só a conciliação olha para ele.

O que não casa fica `protocolada`: consórcio que fatura em parcelas que não batem com a medição (Leblon,
Deciolândia, BR-163) e medição cuja nota não bate com o valor protocolado.

### Corte de 22/09/2026 (decisão do Leonardo em 25/09/2026)

O faturado até o QDOP de 22/09/2026 conta como pago, menos o que o RM mostra em aberto.
`python -m app.cli conciliacao corte --data 2026-09-22 --usuario <e-mail> [--ensaio]` fecha como `recebida`
(sem data, motivo na auditoria) as medições do legado que continuam `protocolada` com protocolo até a data. O
"a receber" da Diretoria soma as medições protocoladas e as cobranças do RM ainda não pagas que nenhuma medição
em aberto representa (título com mais de R$ 1,00 faltando, na cota, idade pela emissão da nota). Liberado em `geral.yaml`
(`diretoria.total_a_receber_liberado: true`). Ordem em produção: backup → `cadastro aplicar` →
`conciliacao antiga` → `conciliacao corte`.

## Tabelas arquivadas (bloco 9)

A migração 027 renomeou as tabelas da detecção antiga, sem apagar nada: `arquivo_sugestoes`,
`arquivo_deteccao_padroes`, `arquivo_deteccao_config`, `arquivo_mensagens_observadas`,
`arquivo_planilhas_config`, `arquivo_planilhas_observadas` e `arquivo_graph_sincronizacoes`. Nenhum código
lê ou escreve nelas. Não ler pela aplicação nem apagar: são o histórico do que a detecção viu e decidiu.
Para consultar, abrir uma cópia do banco (ou o próprio, só leitura:
`sqlite3 "file:C:/DashboardLotufo/dados/dashboard.db?mode=ro"`) e usar `SELECT` nelas.

## Corte do sistema novo (bloco 9)

A dashboard antiga e seus fluxos do Power Automate continuam ligados (decisão de 2026-09-24); nada do
sistema novo depende deles. Ficam dois itens externos, só do sistema novo, feitos depois do bloco 9 em
produção e com OK do Leonardo para cada um:

| # | Item | Prova antes |
|---|---|---|
| 1 | Tirar do app do Entra ID as permissões de leitura (`Mail.Read`, `Mail.Read.Shared`, `Sites.Read.All`, `Files.Read.All`) | bloco 9 em produção; `grep` no código sem uso. Conferir antes se algum fluxo ou robô da dashboard antiga usa o MESMO app (o client ID da tarefa agendada, `-GraphClientId`); se usar, o item não é feito |
| 2 | Tirar os argumentos `-GraphSite` e `-GraphCaixa` da tarefa agendada e apagar `C:\DashboardLotufo\segredos\graph.txt` (token da leitura) | bloco 9 em produção; depois de retirar os argumentos, `deploy.ps1` com health 200 |

Até o item 2, os dois argumentos seguem na tarefa sem efeito: `rodar_producao.ps1` os aceita e ignora.

## Mudar de servidor (VM nova, porta 8080)

Decisão de 03/11/2026: a dashboard sai da máquina de hoje (`<servidor>`, que é a estação de trabalho e o servidor do RM) para
uma VM do TI (`<vm>`). A VM é compartilhada (servidor de sessões do RM, IIS na 80, antivírus corporativo), então a dashboard
responde em **`http://<vm>:8080`** (`-Porta 8080` nos scripts, issue #361). De fora da rede o acesso é pela VPN da empresa
(OpenVPN Connect, decisão do TI); a porta 8080 só aceita rede interna e faixas privadas (regra de firewall abaixo). Sem Tailscale
nem túnel na VM.

**O que a VM tem (preparo feito em 03/11/2026, sem tocar a produção).** Python 3.12, Git, Tesseract 5.4 (instaladores
oficiais, hash conferido), Node 24. `C:\DashboardLotufo` com a mesma estrutura e ACL da produção (`app` é um **clone** em
detached HEAD, não worktree; `deploy.ps1` funciona igual), `dados\tessdata\por.traineddata`, `segredos\rm.txt`, venv e
`frontend\dist` construídos, tarefa `DashboardLotufo` (com `-Porta 8080`), `DashboardLotufoWatchdog` (`-Porta 8080`) e a regra
de firewall `New-NetFirewallRule -DisplayName "Dashboard Lotufo HTTP 8080" -Direction Inbound -Protocol TCP -LocalPort 8080
-Action Allow -Profile Domain,Private -RemoteAddress 10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`. O RM responde da VM pelo mesmo
endereço que a produção usa (`-RmUrl` da tarefa); o RM local da VM devolve HTTP 500 às consultas e não serve.

**Peculiaridades da VM.**
- O antivírus intercepta HTTPS: `npm ci` falha com `SELF_SIGNED_CERT_IN_CHAIN`. Resolvido com a variável de máquina
  `NODE_USE_SYSTEM_CA=1` (o Node passa a confiar no repositório de certificados do Windows; `pip` e `git` já confiam). Sem ela
  o `deploy.ps1` para no `npm ci`.
- A VM **não alcança** `<servidor>` (SSH, HTTP e SMB fechados no sentido VM → servidor); o contrário funciona. Cópia de
  segredos e dados: pelo Mac (`scp` de um lado e do outro, arquivo apagado do Mac em seguida) ou por RDP. Nunca pelo repositório.
- Por SSH, script longo (git, pip, npm) vai por `scp` e roda com `powershell -File`: no `-Command -` o comando nativo consome o
  resto do script pelo stdin e ele para no meio.
- Não há credencial do GitHub na VM: o clone público não precisa; o `git pull` do cadastro privado precisa (decisão pendente).

**Corte (feito em 03/11/2026 às 17:00 com o OK do dono do produto; parada de uns 10 minutos para a operação). O roteiro abaixo é o que foi executado.**

1. Avisar a operação da hora. Conferir que a VM responde: `http://<vm>:8080/api/health` 200.
2. Em `<servidor>`, nesta ordem: sentinela `New-Item -ItemType File C:\DashboardLotufo\watchdog.pause`;
   `Disable-ScheduledTask` e `Stop-ScheduledTask` nas duas tarefas, watchdog primeiro (só parar não basta: o gatilho do watchdog
   repete a cada 3 min e o da tarefa principal dispara no boot; sem desinstalar, porque é o rollback);
   conferir que nada mais escuta na 80 (`Get-NetTCPConnection -LocalPort 80 -State Listen`); **só então** o snapshot:
   `scripts\backup_pre_migracao.ps1 -Banco C:\DashboardLotufo\dados\dashboard.db -PastaBackups C:\DashboardLotufo\dados\backups
   -Python C:\DashboardLotufo\app\backend\.venv\Scripts\python.exe -Rotulo CORTE` (a API de backup do SQLite funciona com o
   servidor parado). Snapshot antes da parada perderia o que a operação, o RM ou um envio gravasse no intervalo.
3. Na VM, com a tarefa parada (`Stop-ScheduledTask` das duas e o sentinela), mover o banco vazio da VM e os companheiros
   (`dados\dashboard.db`, `-wal`, `-shm`) para uma pasta de quarentena, como na seção "Restaurar o banco". Depois copiar: o
   snapshot `dashboard-PRE-CORTE-...db` (vira `dados\dashboard.db`; o snapshot não tem `-wal`/`-shm`), `dados\notas`, `espelhos`, `modelos`, `evidencias`, `certidoes`,
   `assinaturas`; `segredos` inteiro (`rm.txt`, `rm-endereco.txt` se houver, `sharepoint-hosts.txt`, `siga-token.txt`,
   `usuarios\` com os tokens Microsoft de cada pessoa); o clone `cadastro`. Empacotar com o `tar.exe` do próprio Windows
   (`tar -cf C:\Temp\corte.tar -C C:\DashboardLotufo dados/notas ... segredos cadastro`), levar pelo Mac com `scp` e conferir
   tamanho e `Get-FileHash` dos dois lados; apagar o `.tar` das duas máquinas e do Mac depois (ele carrega os segredos).
   `dados\backups` e os `dashboard-PRE-*.db` antigos da raiz de `dados` ficam no servidor antigo como histórico.
   Sem os tokens, cada pessoa reconecta a conta Microsoft em Minha conta (não é erro, só trabalho a mais).
4. Na VM: `integrity_check` do banco (seção "Restaurar o banco"); variáveis de máquina `DASH_SIGA_TOKEN_ARQUIVO`,
   `DASH_SIGA_LINK_MODELO` (copiar os valores de `<servidor>`); `DASH_SIGA_TAREFA` só se o robô do SIGA também mudar para a VM
   (sem ela os botões "Atualizar" da tela SIGA ficam escondidos). Credencial do cadastro privado: token de leitura do GitHub em
   `segredos\github-cadastro.git-credentials` (formato `https://x-access-token:<token>@github.com`) e, no `.git\config` do clone,
   `[credential]` com uma linha `helper =` vazia (desliga o Git Credential Manager) e `helper = store --file=C:/DashboardLotufo/segredos/github-cadastro.git-credentials`
   (barra normal: com `\` o git lê o caminho como escape e o token não é achado). `Start-ScheduledTask DashboardLotufo`, `/api/health` 200 com `banco: ok`, `cadastro aplicar --usuario <e-mail do admin>
   --raiz C:\DashboardLotufo\cadastro --ensaio` sem diferença (seção "Cadastro versionado"), `Start-ScheduledTask DashboardLotufoWatchdog`, apagar o sentinela. Login de cada pessoa da operação.
5. Endereço novo para a operação: `http://<vm>:8080` (o nome da VM está no DNS do domínio e resolve em qualquer PC da empresa;
   o apelido antigo precisava de linha no `hosts`). Máquina fora do domínio (o Mac de desenvolvimento, em outra VLAN) usa o IP
   ou uma linha no `hosts`. Robô do SIGA: trocar o endereço da dashboard para `http://<vm>:8080` (repositório do robô).
6. **Rollback** em uma linha: em `<servidor>`, `Enable-ScheduledTask DashboardLotufo; Enable-ScheduledTask DashboardLotufoWatchdog;
   Start-ScheduledTask DashboardLotufo; Start-ScheduledTask DashboardLotufoWatchdog; Remove-Item C:\DashboardLotufo\watchdog.pause`,
   e a operação volta ao endereço antigo. Na VM, sentinela primeiro e depois
   `Stop-ScheduledTask` do watchdog e da tarefa (sem o sentinela o watchdog da VM religa em 3 minutos e ficam duas instâncias
   no ar). O que foi digitado na VM depois do corte não volta sozinho (fica no banco da VM).
7. Depois de uma semana estável: `Unregister-ScheduledTask` das duas tarefas em `<servidor>`, desligar a regra
   `Dashboard Lotufo HTTP 80`, manter os backups locais de lá até a cópia externa da VM estar configurada.

**Decisões pendentes (03/11/2026).** Data do corte; robô do SIGA (fica em `<servidor>` apontando para a VM, e o botão
"Atualizar" da tela SIGA deixa de funcionar porque ele dispara a tarefa agendada na própria máquina, ou muda para a VM junto);
cópia externa: a tarefa da VM aponta para a pasta de rede do servidor de arquivos (`-BackupExterno \\<servidor-de-arquivos>\...`)
e a conta de computador da VM (`<vm>$`) recebeu Modificar na pasta (NTFS, pelo Explorer numa sessão do domínio na própria VM)
e Change no compartilhamento (`Grant-SmbShareAccess -Name <compartilhamento> -AccountName "<domínio>\<vm>$" -AccessRight Change
-CimSession <servidor-de-arquivos>`, pelo nome DNS: por IP o WinRM recusa); de um PC fora do domínio a busca da conta de
computador não funciona. Teste: tarefa avulsa como SYSTEM na VM gravando um arquivo na pasta; o robô do SIGA ficou em `<servidor>` com o
endereço da dashboard trocado para a VM (cópia do arquivo original ao lado), até ser refeito para rodar na VM sem janela.

## Riscos conhecidos
- Leitura e validação de PDF (rotas de documentos, notas e aditivos) rodam em subprocesso com limite de 10 s de parede e são interrompidas ao estourar: o filho é morto e o cliente recebe 422/415 sem derrubar o servidor. **Custo por chamada ≈ 2 s sob uvicorn no Windows** (0,3–1 s medido em teste; `spawn` + importar pypdf, e o processo do servidor está mais carregado que o do pytest). **Pior caso de parede: até 10 s esperando vaga (só 2 leituras simultâneas) + 10 s de leitura + até 4 s de encerramento, ≈ 24 s.** **No máximo 2 leituras simultâneas**: a terceira espera uma vaga pelo mesmo orçamento de 10 s e é recusada com 422 "tente de novo em alguns segundos" (415 no upload) — não fica pendurada. A pré-checagem de bomba de descompressão roda **dentro do filho**, antes do pypdf: recusa só o stream Flate que expande mais de 50:1 (4 MB por stream, 16 MB no total); o que ela não consegue medir (filtro desconhecido, PDF cifrado, dicionário fora da janela de 8 KB, `/Length` indireto) é ignorado e fica por conta do limite de tempo. Tetos que continuam valendo: 10 MB, 20 páginas, 60 mil caracteres. Limites conhecidos: (a) a memória do filho não é limitada além do kill por tempo — PDF que infle muito em menos de 10 s consome RAM até terminar ou ser morto; (b) **cada filho morto por timeout deixa 1 handle do Windows no processo do servidor** (medido; inerente a `spawn` + `terminate`) — só cresce com upload hostil repetido, e a tarefa agendada reinicia o processo.
- O backup roda como thread do processo do servidor (não há worker separado); com `--workers` maior que 1 cada processo faria a sua rodada. Hoje é processo único.
