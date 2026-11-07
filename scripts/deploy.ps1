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
    [int]$Porta = 0,
    # Raiz dos dados (banco, segredos). Vazio = ler dos argumentos da tarefa DashboardLotufo (-Raiz "..."; sem ele,
    # o padrao do rodar_producao.ps1). Informada e diferente da tarefa, o deploy aborta antes do checkout.
    [string]$Raiz = ""
)
$ErrorActionPreference = "Stop"
$pause = "C:\DashboardLotufo\watchdog.pause"
$py = Join-Path $AppDir "backend\.venv\Scripts\python.exe"
$lock = Join-Path $AppDir "backend\requirements.lock"
if (-not (Test-Path $py)) { throw "venv da producao ausente em $py (setup inicial do diretorio pinado nao feito)" }

# A porta e' a da tarefa agendada, nao uma segunda fonte: com a tarefa na 8080 (VM em que a 80 e' do IIS)
# um deploy na 80 acharia o IIS como dono da porta e abortaria DEPOIS do checkout, sem rollback.
function PortaDaTarefa {
    $tarefa = Get-ScheduledTask -TaskName "DashboardLotufo" -ErrorAction SilentlyContinue
    if (-not $tarefa) { return 0 }
    $argumentosTarefa = ($tarefa.Actions | ForEach-Object { $_.Arguments }) -join " "
    if ($argumentosTarefa -match "-Porta (\d+)") { return [int]$Matches[1] }
    # Sem -Porta vale o padrao do modo do rodar_producao.ps1 (issue #425): 80 com -SemTls, 8443 com TLS.
    if ($argumentosTarefa -match "-SemTls\b") { return 80 }
    return 8443
}
$portaTarefa = PortaDaTarefa
if ($Porta -eq 0) {
    if ($portaTarefa -eq 0) { throw "tarefa DashboardLotufo nao encontrada; informe -Porta ou instale a tarefa (instalar_autostart.ps1)" }
    $Porta = $portaTarefa
} elseif ($portaTarefa -ne 0 -and $Porta -ne $portaTarefa) {
    throw "-Porta $Porta nao bate com a tarefa DashboardLotufo (porta $portaTarefa); nada foi alterado"
}

# A raiz tambem e' a da tarefa (issue #417, gate Sol da PR #437): dela saem o arquivo da instalacao conferido antes do
# reinicio e o banco do backup pre-migracao. Com a producao em outro disco, conferir C:\ recusaria o arquivo valido, ou
# aceitaria um velho enquanto o servidor confere o da raiz certa. O instalar_autostart.ps1 sempre grava -Raiz "...".
function RaizDaTarefa {
    $tarefa = Get-ScheduledTask -TaskName "DashboardLotufo" -ErrorAction SilentlyContinue
    if (-not $tarefa) { return "" }
    $argumentosTarefa = ($tarefa.Actions | ForEach-Object { $_.Arguments }) -join " "
    if ($argumentosTarefa -match '-Raiz\s+(?:"([^"]+)"|(\S+))') {
        if ($Matches[1]) { return $Matches[1] }
        return $Matches[2]
    }
    return "C:\DashboardLotufo"
}
$raizTarefa = RaizDaTarefa
if (-not $Raiz) {
    if ($raizTarefa) { $Raiz = $raizTarefa } else { $Raiz = "C:\DashboardLotufo" }
} elseif ($raizTarefa -and $Raiz.TrimEnd("\") -ne $raizTarefa.TrimEnd("\")) {
    throw "-Raiz $Raiz nao bate com a tarefa DashboardLotufo (raiz $raizTarefa); nada foi alterado"
}
$instalacaoArquivo = Join-Path $Raiz "segredos\instalacao.json"   # o mesmo que o rodar_producao.ps1 passa ao servidor
$banco = Join-Path $Raiz "dados\dashboard.db"

# HTTPS (issue #425): o modo tambem e' o da tarefa. Com -SemTls nos argumentos (producao de antes do corte) a saude e'
# HTTP; sem ele, https://localhost aceitando so' o certificado da instalacao, pelo thumbprint (comum_tls.ps1).
# Com o certificado ausente no modo HTTPS o deploy nao comeca: o watchdog nem e' pausado e nada muda.
function TlsDaTarefa {
    $tarefa = Get-ScheduledTask -TaskName "DashboardLotufo" -ErrorAction SilentlyContinue
    if (-not $tarefa) { return $true }
    $argumentosTarefa = ($tarefa.Actions | ForEach-Object { $_.Arguments }) -join " "
    return (-not ($argumentosTarefa -match "-SemTls\b"))
}
$comTls = TlsDaTarefa
. (Join-Path $PSScriptRoot "comum_tls.ps1")
$certificado = Join-Path $Raiz "segredos\tls\cert.pem"
if ($comTls) {
    $urlSaude = "https://localhost:$Porta/api/health"
    if (-not (Test-Path -LiteralPath $certificado)) {
        throw "certificado do HTTPS nao encontrado em $certificado (tarefa sem -SemTls); nada foi alterado - ver docs\runbook.md (HTTP ou HTTPS)"
    }
} else {
    $urlSaude = "http://localhost:$Porta/api/health"
}

# Instalacao assinada (issue #417): depois do deploy so' vale o health 200 com instalacao "autorizada" (arquivo
# assinado para esta maquina em <raiz>\segredos\instalacao.json). Modo copia (arquivo ausente, ilegivel, assinatura
# ou maquina) conta como falha e dispara o rollback. O rollback confere so' o 200: o commit anterior pode nem ter o campo.
function Saudavel([switch]$ExigirInstalacao) {
    try { $resposta = Invoke-SaudeLocal -Url $urlSaude -Certificado $certificado -TimeoutSec 12 }
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
# Issue #421: registro do que foi implantado (commit e manifesto do dist) em <raiz>\deploy-atual.json, que o servidor
# confere de hora em hora. Gravado ANTES de reiniciar, para a conferencia da subida ja' achar o registro novo; falha
# aqui so' avisa (o item "Sem registro do ultimo deploy" aparece na Saude).
function RegistrarDeploy {
    Push-Location (Join-Path $AppDir "backend")
    $codigo = 1
    try { & $py -m app.cli integridade registrar --raiz $Raiz; $codigo = $LASTEXITCODE }
    catch { Write-Warning "registro do deploy: $($_.Exception.Message)" }
    finally { Pop-Location }
    if ($codigo -ne 0) { Write-Warning "registro do deploy (deploy-atual.json) nao gravado - ver docs\runbook.md (Saude)" }
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
# Issue #478: rollback de um commit com a #456 (ponto da sentinela na tabela sentinela_ponto, migracao 063) para um
# anterior a ela, que le e grava o ponto so' na auditoria. Com o servico parado e o codigo NOVO ainda no pinado, o
# app.cli grava o ponto na auditoria e tira a tabela, os gatilhos e a linha da 063; sem isso o codigo antigo acusaria
# "Estado da sentinela apagado" e repetiria os achados desde o deploy da #456. Falha aqui so' avisa: o rollback segue.
function SentinelaAntesDa456([string]$de, [string]$para) {
    $temNovo = & git -C $AppDir ls-tree --name-only $de -- backend/migrations/063_sentinela_ponto.sql
    if ($LASTEXITCODE -ne 0) { Write-Warning "git ls-tree $de falhou; ponto da sentinela nao conferido"; return }
    $temAnterior = & git -C $AppDir ls-tree --name-only $para -- backend/migrations/063_sentinela_ponto.sql
    if ($LASTEXITCODE -ne 0) { Write-Warning "git ls-tree $para falhou; ponto da sentinela nao conferido"; return }
    if (-not $temNovo -or $temAnterior) { return }
    $codigo = 1
    Push-Location (Join-Path $AppDir "backend")
    try {
        Stop-ScheduledTask -TaskName "DashboardLotufo"; Start-Sleep -Seconds 3
        LiberarPorta
        & $py -m app.cli sentinela antes-da-456 --banco $banco; $codigo = $LASTEXITCODE
    } catch { Write-Warning "ponto da sentinela: $($_.Exception.Message)" }
    finally { Pop-Location }
    if ($codigo -ne 0) {
        Write-Warning "ponto da sentinela NAO passado para a auditoria antes do rollback - ver docs\runbook.md (Rollback para um commit anterior a issue #456)"
    }
}
# Depois do ROLLBACK OK: o commit anterior pode ja' conferir a instalacao (issue #417) e ter voltado em modo copia, sem
# envio de e-mail e sem RM. Commit anterior ao #417 nao tem o campo e nao avisa.
function AvisarSeCopia {
    try { $saude = (Invoke-SaudeLocal -Url $urlSaude -Certificado $certificado -TimeoutSec 12).Content | ConvertFrom-Json }
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
    # Gate Sol da PR #476: com a tarefa em HTTPS, um alvo de antes da #425 nao sobe (o rodar_producao.ps1 dele procura a
    # chave em app\certs) e derruba o watchdog (o watchdog.ps1 dele nao conhece -Certificado). Recusar antes do backup e
    # do checkout; o marcador e' o scripts/comum_tls.ps1, que nasceu na #425. O finally solta o watchdog.
    # ls-tree (e nao cat-file -e): sem o arquivo ele so' nao imprime nada, sem stderr, que o 5.1 com Stop tornaria fatal.
    if ($comTls) {
        $marcador = & git -C $AppDir ls-tree --name-only $alvo -- scripts/comum_tls.ps1
        if ($LASTEXITCODE -ne 0) { throw "git ls-tree $alvo falhou" }
        if (-not $marcador) {
            Write-Host "deploy abortado antes do checkout: $alvo e' anterior ao HTTPS (issue #425) e a tarefa esta em HTTPS; volte para HTTP antes (runbook, Voltar atras). Producao segue em $anterior" -ForegroundColor Red
            exit 1
        }
    }
    $migracoes = & git -C $AppDir diff --name-only $anterior $alvo -- backend/migrations
    if ($LASTEXITCODE -ne 0) { throw "git diff das migracoes falhou" }
    $backup = $null
    if ($migracoes) {
        $backup = & (Join-Path $PSScriptRoot "backup_pre_migracao.ps1") -Banco $banco `
            -PastaBackups (Join-Path $Raiz "dados\backups") -Python $py -Rotulo $alvo.Substring(0, 7)
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
                RegistrarDeploy
            }
            Write-Host "deploy abortado no build; producao segue no commit anterior ($anterior), diretorio pinado de volta nele" -ForegroundColor Red
        } catch {
            $onde = (& git -C $AppDir rev-parse HEAD).Trim()
            Write-Host "deploy abortado no build E a volta para $anterior falhou ($($_.Exception.Message)) - intervir a mao: HEAD do diretorio pinado agora em $onde (esperado $anterior)" -ForegroundColor Red
        }
        exit 1
    }
    $novo = (& git -C $AppDir rev-parse HEAD).Trim()
    RegistrarDeploy
    Reiniciar
    if (SaudavelENovo -ExigirInstalacao) {
        $fim = "DEPLOY OK: $anterior -> $novo (health 200, processo novo)"
        if ($backup) { $fim += " - backup pre-migracao: $backup" }
        Write-Host $fim -ForegroundColor Green
    } else {
        Write-Warning "Saude NAO voltou -> ROLLBACK para $anterior"
        SentinelaAntesDa456 $novo $anterior
        Construir $anterior
        RegistrarDeploy
        Reiniciar
        if (SaudavelENovo) { Write-Host "ROLLBACK OK: producao de volta em $anterior" -ForegroundColor Yellow; AvisarSeCopia }
        else { Write-Host "ROLLBACK TAMBEM FALHOU - intervir a mao (ver watchdog.log e dashboard.log)" -ForegroundColor Red }
        exit 1
    }
} finally {
    Remove-Item $pause -Force -ErrorAction SilentlyContinue   # solta o watchdog
}
