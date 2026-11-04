# Deploy da producao PINADA (mitigacao [16], 2026-09-10): a producao NAO roda mais do
# working tree de desenvolvimento, e sim de um worktree git DEDICADO e imutavel em
# C:\DashboardLotufo\app (detached HEAD num commit). Assim uma edicao/branch/troca no
# tree de dev, ou um reboot no meio de uma edicao, nao muda o que a producao executa.
#
# Este script atualiza esse diretorio para um commit e reinicia, com o watchdog pausado
# (senao ele reergueria no meio) e ROLLBACK automatico para o commit anterior se a saude
# nao voltar. Rodar como administrador (parar/iniciar a tarefa exige).
#
# Fluxo de deploy: (1) commit+push no tree de dev; (2) rodar este script (Ref=origin/master).
# Os dados (banco/logs/backups) ficam em -Raiz (C:\DashboardLotufo), fora do codigo, e nao
# sao alterados (o banco so' e' lido, no backup pre-migracao). .venv, node_modules e dist do diretorio pinado sao reconstruidos aqui.
#
# Agendador de tarefas SEM cmdlets CIM (issue #386): em 2026-11-04 um deploy ficou mais de
# 10 minutos parado em Get-ScheduledTask porque o provedor CIM do agendador nao respondia,
# enquanto schtasks.exe respondia em segundos. Toda conversa com o agendador passa por
# schtasks.exe num processo filho com tempo limite (30 s); estouro antes do checkout aborta
# sem tocar no pinado, estouro no reinicio volta o pinado ao commit anterior.
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
    # Tempo limite, em segundos, de cada chamada ao agendador de tarefas (schtasks.exe).
    # Estouro = "agendador de tarefas nao respondeu". So' para prova em servidor de revisao.
    [ValidateRange(1, 600)]
    [int]$LimiteAgendador = 30,
    # So' para prova: nome de um executavel que finge ser o schtasks.exe (ex.: um .cmd que dorme
    # mais que -LimiteAgendador), para ver o estouro de tempo sem travar o agendador de verdade.
    [string]$Schtasks = "schtasks.exe"
)
$ErrorActionPreference = "Stop"
$pause = "C:\DashboardLotufo\watchdog.pause"
$tarefaNome = "DashboardLotufo"
$py = Join-Path $AppDir "backend\.venv\Scripts\python.exe"
$lock = Join-Path $AppDir "backend\requirements.lock"
if (-not (Test-Path $py)) { throw "venv da producao ausente em $py (setup inicial do diretorio pinado nao feito)" }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "rode como administrador: parar e iniciar a tarefa $tarefaNome exige sessao elevada; nada foi alterado"
}

# Uma linha de progresso por etapa, com hora: quem acompanha por SSH sabe onde o script esta'.
function Etapa([string]$texto) { Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $texto) }

. (Join-Path $PSScriptRoot "comum_agendador.ps1")   # Agendador: schtasks.exe com tempo limite
function Agendar([string[]]$argumentos) { return Agendador $argumentos $LimiteAgendador $Schtasks }
$msgAgendador = "deploy abortado: agendador de tarefas nao respondeu"

# A porta e' a da tarefa agendada, nao uma segunda fonte: com a tarefa na 8080 (VM em que a 80 e' do IIS)
# um deploy na 80 acharia o IIS como dono da porta e abortaria DEPOIS do checkout, sem rollback.
# Le o XML da tarefa (schtasks /Query /XML): os argumentos saem em <Arguments>, sem depender do
# idioma dos cabecalhos do /FO LIST.
function PortaDaTarefa {
    $r = Agendar @("/Query", "/TN", $tarefaNome, "/XML")
    if ($r.Estourou) {
        Write-Host "$msgAgendador (schtasks /Query levou mais de $LimiteAgendador s); nada foi alterado" -ForegroundColor Red
        exit 1
    }
    if ($r.Codigo -ne 0) { $script:saidaQuery = $r.Saida; return 0 }   # tarefa nao existe (ou schtasks falhou: saida guardada)
    if ($r.Saida -notmatch "<Arguments>([^<]*)</Arguments>") {
        throw "nao consegui ler os argumentos da tarefa $tarefaNome no XML do schtasks; nada foi alterado"
    }
    if ($Matches[1] -match "-Porta (\d+)") { return [int]$Matches[1] }
    return 80
}
$portaTarefa = PortaDaTarefa
if ($Porta -eq 0) {
    if ($portaTarefa -eq 0) { throw "tarefa $tarefaNome nao encontrada (schtasks: $script:saidaQuery); informe -Porta ou instale a tarefa (instalar_autostart.ps1)" }
    $Porta = $portaTarefa
} elseif ($portaTarefa -ne 0 -and $Porta -ne $portaTarefa) {
    throw "-Porta $Porta nao bate com a tarefa $tarefaNome (porta $portaTarefa); nada foi alterado"
}
Etapa "porta lida: $Porta (tarefa $tarefaNome, agendador respondeu)"

function Saudavel {
    try { return ((Invoke-WebRequest "http://localhost:$Porta/api/health" -TimeoutSec 12 -UseBasicParsing).StatusCode -eq 200) }
    catch { return $false }
}
# Sem fetch aqui: o fluxo principal ja' buscou o alvo (e o rollback usa um commit local).
function Construir([string]$alvo) {
    Etapa "checkout $alvo"
    & git -C $AppDir checkout --quiet --detach $alvo
    if ($LASTEXITCODE -ne 0) { throw "git checkout $alvo falhou (diretorio pinado sujo?)" }
    Reconstruir
}
function Reconstruir {
    Etapa "pip install (requirements.lock)"
    & $py -m pip install --quiet --disable-pip-version-check -r $lock
    if ($LASTEXITCODE -ne 0) { throw "pip install do requirements.lock falhou" }
    if (-not $SemFrontend) {
        Push-Location (Join-Path $AppDir "frontend")
        try {
            Etapa "npm ci"
            & npm ci --silent; if ($LASTEXITCODE -ne 0) { throw "npm ci falhou" }
            Etapa "npm run build"
            & npm run build;   if ($LASTEXITCODE -ne 0) { throw "npm run build falhou" }
        } finally { Pop-Location }
    } else {
        Etapa "npm: pulado (-SemFrontend)"
    }
}
function DonoDaPorta {
    $c = Get-NetTCPConnection -LocalPort $Porta -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $c) { return $null }
    return Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"
}
# Servidor ORFAO do Agendador (incidente de 2026-09-21): parar a tarefa nao o mata, ele
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
# Para e inicia a tarefa por schtasks /End e /Run. Estouro de tempo lanca uma excecao com a
# mensagem propria, que o fluxo principal trata voltando o pinado. /End que falha (tarefa
# ja' parada, instancia orfa) so' avisa: LiberarPorta cuida do que sobrou na porta. /Run que falha e' fatal.
function ComandoTarefa([string]$verbo, [bool]$fatal) {
    $r = Agendar @("/$verbo", "/TN", $tarefaNome)
    # Texto proprio, sem o "$msgAgendador" de antes do checkout: aqui a producao pode ter mudado.
    if ($r.Estourou) { throw "agendador de tarefas nao respondeu ao schtasks /$verbo (mais de $LimiteAgendador s)" }
    if ($r.Codigo -ne 0) {
        $texto = "schtasks /$verbo $tarefaNome falhou (codigo $($r.Codigo)): $($r.Saida)"
        if ($fatal) { throw $texto }
        Write-Warning $texto
    }
}
function Reiniciar {
    Etapa "reinicio: parando a tarefa $tarefaNome"
    ComandoTarefa "End" $false; Start-Sleep -Seconds 3
    LiberarPorta
    $script:tarefaParada = $true   # daqui em diante a producao esta' fora ate' o /Run
    $script:reinicioEm = Get-Date
    Etapa "reinicio: iniciando a tarefa $tarefaNome"
    ComandoTarefa "Run" $true
    $script:tarefaParada = $false
    Start-Sleep -Seconds 15
}
# Saude so' vale se quem responde NASCEU depois do reinicio: health 200 de processo antigo
# nao prova que o commit novo esta' no ar.
function SaudavelENovo {
    Etapa "saude: conferindo http://localhost:$Porta/api/health"
    if (-not (Saudavel)) { return $false }
    $dono = DonoDaPorta
    if (-not $dono -or $dono.CreationDate -lt $script:reinicioEm) {
        Write-Warning "health 200, mas o dono da porta $Porta e' anterior ao reinicio (PID $($dono.ProcessId), $($dono.CreationDate))"
        return $false
    }
    return $true
}
# Volta o diretorio pinado para $anterior sem fetch (a rede pode ser a causa) e so' reconstroi
# se o HEAD saiu de $anterior: se a falha foi no fetch/checkout do alvo, o HEAD nunca saiu e o
# build nao e' refeito (npm/vite esvaziariam o dist servido com a producao no ar).
function VoltarPinado([string]$anterior) {
    $atual = (& git -C $AppDir rev-parse HEAD).Trim()
    if ($atual -ne $anterior) {
        Etapa "voltando o diretorio pinado para $anterior"
        & git -C $AppDir checkout --quiet --detach $anterior
        if ($LASTEXITCODE -ne 0) { throw "git checkout $anterior falhou" }
        Reconstruir
    }
}

$anterior = (& git -C $AppDir rev-parse HEAD).Trim()
New-Item -ItemType File -Path $pause -Force | Out-Null   # segura o watchdog durante o deploy
try {
    # Backup pre-migracao (issue #75): se o commit novo mexe em backend/migrations, snapshot
    # do banco de producao ANTES do checkout; se falhar, o deploy nao acontece. O rollback
    # do codigo mais abaixo NAO restaura o banco (restauracao manual pelo runbook).
    Etapa "fetch"
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
    try { Construir $alvo }
    catch {
        Write-Warning "Construir $alvo falhou: $($_.Exception.Message) -> voltando o diretorio pinado para $anterior"
        try {
            VoltarPinado $anterior
            Write-Host "deploy abortado no build; producao segue no commit anterior ($anterior), diretorio pinado de volta nele" -ForegroundColor Red
        } catch {
            $onde = (& git -C $AppDir rev-parse HEAD).Trim()
            Write-Host "deploy abortado no build E a volta para $anterior falhou ($($_.Exception.Message)) - intervir a mao: HEAD do diretorio pinado agora em $onde (esperado $anterior)" -ForegroundColor Red
        }
        exit 1
    }
    $novo = (& git -C $AppDir rev-parse HEAD).Trim()
    # Agendador sem resposta no reinicio (depois do checkout): o pinado volta ao commit anterior e,
    # se a tarefa ja' tinha sido parada (falha no /Run), tenta religa-la uma vez com o codigo anterior;
    # se nem isso, a producao esta' FORA e a mensagem diz para religar a mao.
    try { Reiniciar }
    catch {
        $motivo = $_.Exception.Message
        Write-Warning "reinicio falhou: $motivo -> voltando o diretorio pinado para $anterior"
        try {
            VoltarPinado $anterior
            # Um /Run cujo cliente foi morto ainda pode chegar ao servico: quem esta' na porta
            # e' impresso (PID e criacao), nao presumido.
            $dono = DonoDaPorta
            $naPorta = if ($dono) { "na porta $Porta esta' o PID $($dono.ProcessId), criado em $($dono.CreationDate)" } else { "ninguem escuta na porta $Porta" }
            if ($script:tarefaParada) {
                Etapa "religando a tarefa $tarefaNome com o commit anterior"
                $r = Agendar @("/Run", "/TN", $tarefaNome)
                if ($r.Estourou -or $r.Codigo -ne 0) {
                    Write-Host "deploy abortado no reinicio ($motivo); diretorio pinado de volta em $anterior, mas a tarefa $tarefaNome foi parada e NAO religou ($naPorta) - religar a mao com schtasks /Run /TN $tarefaNome quando o agendador responder" -ForegroundColor Red
                } else {
                    Write-Host "deploy abortado no reinicio ($motivo); diretorio pinado de volta em $anterior e tarefa $tarefaNome religada com ele ($naPorta) - conferir /api/health a mao" -ForegroundColor Red
                }
            } else {
                Write-Host "deploy abortado no reinicio ($motivo); diretorio pinado de volta em $anterior; a tarefa nao chegou a ser parada ($naPorta) - conferir /api/health a mao" -ForegroundColor Red
            }
        } catch {
            $onde = (& git -C $AppDir rev-parse HEAD).Trim()
            Write-Host "deploy abortado no reinicio ($motivo) E a volta para $anterior falhou ($($_.Exception.Message)) - intervir a mao: HEAD do diretorio pinado agora em $onde (esperado $anterior)" -ForegroundColor Red
        }
        exit 1
    }
    if (SaudavelENovo) {
        $fim = "DEPLOY OK: $anterior -> $novo (health 200, processo novo)"
        if ($backup) { $fim += " - backup pre-migracao: $backup" }
        Write-Host $fim -ForegroundColor Green
    } else {
        Write-Warning "Saude NAO voltou -> ROLLBACK para $anterior"
        try {
            Construir $anterior
            Reiniciar
        } catch {
            Write-Host "ROLLBACK TAMBEM FALHOU ($($_.Exception.Message)) - intervir a mao (ver watchdog.log e dashboard.log)" -ForegroundColor Red
            exit 1
        }
        if (SaudavelENovo) { Write-Host "ROLLBACK OK: producao de volta em $anterior" -ForegroundColor Yellow }
        else { Write-Host "ROLLBACK TAMBEM FALHOU - intervir a mao (ver watchdog.log e dashboard.log)" -ForegroundColor Red }
        exit 1
    }
} finally {
    Remove-Item $pause -Force -ErrorAction SilentlyContinue   # solta o watchdog
}
