# Registra a tarefa DashboardLotufoWatchdog: roda watchdog.ps1 a cada 3 minutos como
# SYSTEM (mesma conta da producao). Idempotente (-Force). Rodar como administrador.
#
# Usa Register-ScheduledTask (nao schtasks) porque o caminho do repo tem espacos
# ("Nova Dashboard Lotufo") e o schtasks /TR quebra o argumento nos espacos.
# Para remover: Unregister-ScheduledTask -TaskName DashboardLotufoWatchdog -Confirm:$false
#
# -Porta: porta em que a producao responde (padrao 80, HTTP); o watchdog confere
# http://localhost:<porta>/api/health. Ex.: -Porta 8080 na VM em que a 80 e' do IIS.
[CmdletBinding()]
param(
    [int]$Porta = 80
)
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "watchdog.ps1"
if (-not (Test-Path $script)) { throw "watchdog.ps1 nao encontrado em $script" }
$url = "http://localhost:$Porta/api/health"

$acao = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Url "{1}"' -f $script, $url)
# Repeticao "indefinida": MaxValue estoura o XML; 10 anos (P3650D) e' valido. O padrao
# "empresta a Repetition" contorna quirks do PS 5.1 em aplicar intervalo+duracao.
$gatilho = New-ScheduledTaskTrigger -Once -At (Get-Date)
$gatilho.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 3) -RepetitionDuration (New-TimeSpan -Days 3650)).Repetition
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "DashboardLotufoWatchdog" -Action $acao -Trigger $gatilho `
    -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "DashboardLotufoWatchdog registrada (a cada 3 min, SYSTEM, confere $url)."
