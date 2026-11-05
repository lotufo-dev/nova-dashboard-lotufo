# Deploy da producao PINADA (mitigacao [16], 2026-09-10): a producao NAO roda mais do
# working tree de desenvolvimento, e sim de um worktree git DEDICADO e imutavel em
# C:\DashboardLotufo\app (detached HEAD num commit). Assim uma edicao/branch/troca no
# tree de dev, ou um reboot no meio de uma edicao, nao muda o que a producao executa.
#
# Este script atualiza esse diretorio para um commit e reinicia, com o watchdog pausado
# (senao ele reergueria no meio) e ROLLBACK automatico para o commit anterior se a saude
# nao voltar. Rodar como administrador (Stop/Start da tarefa exige).
#
# Fluxo de deploy: (1) commit+push no tree de dev; (2) rodar este script (Ref=origin/master).
# Os dados (banco/logs/backups) ficam em -Raiz (C:\DashboardLotufo), fora do codigo, e nao
# sao alterados (o banco so' e' lido, no backup pre-migracao). .venv, node_modules e dist do diretorio pinado sao reconstruidos aqui.
#
# Chamar SEM redirecionar stderr (nada de *>&1): com ErrorActionPreference=Stop o PowerShell
# 5.1 transforma o aviso do Vite em erro fatal. Este arquivo fica so' com ASCII (sem BOM, o
# 5.1 le como ANSI e acento quebra o parse).
[CmdletBinding()]
param(
    [string]$Ref = "origin/master",
    [string]$AppDir = "C:\DashboardLotufo\app",
    [switch]$SemFrontend,  # pula npm/build quando a mudanca e' so backend/docs
    # Porta em que a producao responde. 0 = ler dos argumentos da tarefa DashboardLotufo
    # (-Porta N; sem ele, 80). Informada e diferente da tarefa, o deploy aborta antes do checkout.
    [ValidateRange(0, 65535)]
    [int]$Porta = 0
)
$ErrorActionPreference = "Stop"
$pause = "C:\DashboardLotufo\watchdog.pause"
$py = Join-Path $AppDir "backend\.venv\Scripts\python.exe"
$lock = Join-Path $AppDir "backend\requirements.lock"
$instalacaoArquivo = "C:\DashboardLotufo\segredos\instalacao.json"   # issue #417, o mesmo de rodar_producao.ps1
if (-not (Test-Path $py)) { throw "venv da producao ausente em $py (setup inicial do diretorio pinado nao feito)" }

# A porta e' a da tarefa agendada, nao uma segunda fonte: com a tarefa na 8080 (VM em que a 80 e' do IIS)
# um deploy na 80 acharia o IIS como dono da porta e abortaria DEPOIS do checkout, sem rollback.
function PortaDaTarefa {
    $tarefa = Get-ScheduledTask -TaskName "DashboardLotufo" -ErrorAction SilentlyContinue
    if (-not $tarefa) { return 0 }
    $argumentosTarefa = ($tarefa.Actions | ForEach-Object { $_.Arguments }) -join " "
    if ($argumentosTarefa -match "-Porta (\d+)") { return [int]$Matches[1] }
    return 80
}
$portaTarefa = PortaDaTarefa
if ($Porta -eq 0) {
    if ($portaTarefa -eq 0) { throw "tarefa DashboardLotufo nao encontrada; informe -Porta ou instale a tarefa (instalar_autostart.ps1)" }
    $Porta = $portaTarefa
} elseif ($portaTarefa -ne 0 -and $Porta -ne $portaTarefa) {
    throw "-Porta $Porta nao bate com a tarefa DashboardLotufo (porta $portaTarefa); nada foi alterado"
}

# Instalacao assinada (issue #417): depois do deploy so' vale o health 200 com instalacao "autorizada" (arquivo
# assinado para esta maquina em C:\DashboardLotufo\segredos\instalacao.json). Modo copia (arquivo ausente, assinatura
# ou maquina) conta como falha e dispara o rollback. O rollback confere so' o 200: o commit anterior pode nem ter o campo.
function Saudavel([switch]$ExigirInstalacao) {
    try { $resposta = Invoke-WebRequest "http://localhost:$Porta/api/health" -TimeoutSec 12 -UseBasicParsing }
    catch { return $false }
    if ($resposta.StatusCode -ne 200) { return $false }
    if (-not $ExigirInstalacao) { return $true }
    $saude = $null
    try { $saude = $resposta.Content | ConvertFrom-Json } catch { $saude = $null }
    if ($saude -and $saude.instalacao -eq "autorizada") { return $true }
    if ($saude) { $situacao = "$($saude.instalacao) (motivo: $($saude.instalacao_motivo))" } else { $situacao = "health ilegivel" }
    Write-Warning "health 200, mas a instalacao nao esta autorizada: $situacao - ver docs\runbook.md (Instalacao assinada)"
    return $false
}
function Construir([string]$alvo) {
    & git -C $AppDir fetch --quiet
    if ($LASTEXITCODE -ne 0) { throw "git fetch falhou" }
    & git -C $AppDir checkout --quiet --detach $alvo
    if ($LASTEXITCODE -ne 0) { throw "git checkout $alvo falhou (diretorio pinado sujo?)" }
    Reconstruir
}
function Reconstruir {
    & $py -m pip install --quiet --disable-pip-version-check -r $lock
    if ($LASTEXITCODE -ne 0) { throw "pip install do requirements.lock falhou" }
    if (-not $SemFrontend) {
        Push-Location (Join-Path $AppDir "frontend")
        try {
            & npm ci --silent; if ($LASTEXITCODE -ne 0) { throw "npm ci falhou" }
            & npm run build;   if ($LASTEXITCODE -ne 0) { throw "npm run build falhou" }
        } finally { Pop-Location }
    }
}
# Issue #417: antes de parar a producao, o codigo NOVO (ja' no pinado, depois do build) confere o arquivo da
# instalacao. Sem "autorizada" o deploy para aqui: as migracoes so' rodam na subida, entao o banco nao e' migrado e o
# processo no ar nao e' trocado; o catch do Construir volta o pinado para o commit anterior.
function ConferirInstalacao {
    Push-Location (Join-Path $AppDir "backend")
    try { & $py -m app.cli instalacao verificar --arquivo $instalacaoArquivo }
    finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "instalacao nao autorizada para o commit novo - ver docs\runbook.md (Instalacao assinada)" }
}
function DonoDaPorta {
    $c = Get-NetTCPConnection -LocalPort $Porta -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $c) { return $null }
    return Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"
}
# Servidor ORFAO do Agendador (incidente de 2026-09-21): Stop-ScheduledTask nao o mata, ele
# segura a porta, a instancia nova morre com WinError 10048 e o health 200 que se ve e' o
# do processo ANTIGO. Por isso: quem sobrar na porta depois do Stop e' morto aqui -- so' se
# for o uvicorn da dashboard; qualquer outro dono da porta aborta o deploy.
function LiberarPorta {
    $dono = DonoDaPorta
    if (-not $dono) { return }
    if ($dono.CommandLine -notmatch "uvicorn" -or $dono.CommandLine -notmatch "app\.main") {
        throw "porta $Porta ocupada por processo que nao e' a dashboard (PID $($dono.ProcessId): $($dono.Name)); nada foi morto"
    }
    Write-Warning "servidor orfao na porta $Porta (PID $($dono.ProcessId), criado em $($dono.CreationDate)) -> encerrando"
    Stop-Process -Id $dono.ProcessId -Force
    Start-Sleep -Seconds 3
    if (DonoDaPorta) { throw "porta $Porta continua ocupada depois de encerrar o PID $($dono.ProcessId)" }
}
function Reiniciar {
    Stop-ScheduledTask -TaskName "DashboardLotufo"; Start-Sleep -Seconds 3
    LiberarPorta
    $script:reinicioEm = Get-Date
    Start-ScheduledTask -TaskName "DashboardLotufo"; Start-Sleep -Seconds 15
}
# Saude so' vale se quem responde NASCEU depois do reinicio: health 200 de processo antigo
# nao prova que o commit novo esta' no ar.
function SaudavelENovo([switch]$ExigirInstalacao) {
    if (-not (Saudavel -ExigirInstalacao:$ExigirInstalacao)) { return $false }
    $dono = DonoDaPorta
    if (-not $dono -or $dono.CreationDate -lt $script:reinicioEm) {
        Write-Warning "health 200, mas o dono da porta $Porta e' anterior ao reinicio (PID $($dono.ProcessId), $($dono.CreationDate))"
        return $false
    }
    return $true
}
# Depois do ROLLBACK OK: o commit anterior pode ja' conferir a instalacao (issue #417) e ter voltado em modo copia, sem
# envio de e-mail e sem RM. Commit anterior ao #417 nao tem o campo e nao avisa.
function AvisarSeCopia {
    try { $saude = (Invoke-WebRequest "http://localhost:$Porta/api/health" -TimeoutSec 12 -UseBasicParsing).Content | ConvertFrom-Json }
    catch { return }
    if ($saude.instalacao -and $saude.instalacao -ne "autorizada") {
        Write-Warning "producao de volta, mas em modo copia: instalacao $($saude.instalacao) (motivo: $($saude.instalacao_motivo)), sem envio de e-mail e sem RM - ver docs\runbook.md (Instalacao assinada)"
    }
}

$anterior = (& git -C $AppDir rev-parse HEAD).Trim()
New-Item -ItemType File -Path $pause -Force | Out-Null   # segura o watchdog durante o deploy
try {
    # Backup pre-migracao (issue #75): se o commit novo mexe em backend/migrations, snapshot
    # do banco de producao ANTES do checkout; se falhar, o deploy nao acontece. O rollback
    # do codigo mais abaixo NAO restaura o banco (restauracao manual pelo runbook).
    & git -C $AppDir fetch --quiet
    if ($LASTEXITCODE -ne 0) { throw "git fetch falhou" }
    $alvo = (& git -C $AppDir rev-parse $Ref)
    if ($LASTEXITCODE -ne 0) { throw "git rev-parse $Ref falhou" }
    $alvo = $alvo.Trim()
    $migracoes = & git -C $AppDir diff --name-only $anterior $alvo -- backend/migrations
    if ($LASTEXITCODE -ne 0) { throw "git diff das migracoes falhou" }
    $backup = $null
    if ($migracoes) {
        $backup = & (Join-Path $PSScriptRoot "backup_pre_migracao.ps1") -Banco "C:\DashboardLotufo\dados\dashboard.db" `
            -PastaBackups "C:\DashboardLotufo\dados\backups" -Python $py -Rotulo $alvo.Substring(0, 7)
        if ($LASTEXITCODE -ne 0 -or -not $backup) {
            Write-Host "deploy abortado antes do checkout; producao segue em $anterior" -ForegroundColor Red
            exit 1
        }
        Write-Host "BACKUP PRE-MIGRACAO: $backup"
    } else {
        Write-Host "sem migracao nova; sem backup pre-migracao"
    }
    # Construir pode lancar depois do checkout (pip/npm/build): o diretorio pinado nao pode ficar
    # num commit que nao subiu (issue #78). Volta para $anterior (checkout + reconstrucao) e sai com 1.
    # A conferencia da instalacao (issue #417) entra no mesmo try: recusada, a producao nem para.
    try { Construir $alvo; ConferirInstalacao }
    catch {
        Write-Warning "Construir ou conferir a instalacao de $alvo falhou: $($_.Exception.Message) -> voltando o diretorio pinado para $anterior"
        # Sem fetch (a rede pode ser a causa) e so reconstroi se o HEAD saiu de $anterior:
        # se a falha foi no fetch/checkout do alvo, o HEAD nunca saiu e o build nao e refeito
        # (npm/vite esvaziariam o dist servido com a producao no ar).
        try {
            $atual = (& git -C $AppDir rev-parse HEAD).Trim()
            if ($atual -ne $anterior) {
                & git -C $AppDir checkout --quiet --detach $anterior
                if ($LASTEXITCODE -ne 0) { throw "git checkout $anterior falhou" }
                Reconstruir
            }
            Write-Host "deploy abortado no build; producao segue no commit anterior ($anterior), diretorio pinado de volta nele" -ForegroundColor Red
        } catch {
            $onde = (& git -C $AppDir rev-parse HEAD).Trim()
            Write-Host "deploy abortado no build E a volta para $anterior falhou ($($_.Exception.Message)) - intervir a mao: HEAD do diretorio pinado agora em $onde (esperado $anterior)" -ForegroundColor Red
        }
        exit 1
    }
    $novo = (& git -C $AppDir rev-parse HEAD).Trim()
    Reiniciar
    if (SaudavelENovo -ExigirInstalacao) {
        $fim = "DEPLOY OK: $anterior -> $novo (health 200, processo novo)"
        if ($backup) { $fim += " - backup pre-migracao: $backup" }
        Write-Host $fim -ForegroundColor Green
    } else {
        Write-Warning "Saude NAO voltou -> ROLLBACK para $anterior"
        Construir $anterior
        Reiniciar
        if (SaudavelENovo) { Write-Host "ROLLBACK OK: producao de volta em $anterior" -ForegroundColor Yellow; AvisarSeCopia }
        else { Write-Host "ROLLBACK TAMBEM FALHOU - intervir a mao (ver watchdog.log e dashboard.log)" -ForegroundColor Red }
        exit 1
    }
} finally {
    Remove-Item $pause -Force -ErrorAction SilentlyContinue   # solta o watchdog
}
