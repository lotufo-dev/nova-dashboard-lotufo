# Registra a tarefa DashboardLotufoWatchdog: roda watchdog.ps1 a cada 3 minutos como
# SYSTEM (mesma conta da producao). Idempotente (-Force). Rodar como administrador.
#
# Usa Register-ScheduledTask (nao schtasks) porque o caminho do repo tem espacos
# ("Nova Dashboard Lotufo") e o schtasks /TR quebra o argumento nos espacos.
# Para remover: Unregister-ScheduledTask -TaskName DashboardLotufoWatchdog -Confirm:$false
#
# Modo, porta e raiz iguais aos da tarefa DashboardLotufo (instalar_autostart.ps1): -Porta e -Raiz omitidos vem dos
# argumentos dela, e valor diferente aborta. Padrao (issue #425): HTTPS, o watchdog confere
# https://localhost:<porta>/api/health aceitando so' o certificado <Raiz>\segredos\tls\cert.pem (pelo thumbprint).
# -SemTls: http://localhost:<porta>/api/health. Sem a tarefa, -Porta 0 = padrao do modo (80 com -SemTls, 8443 com TLS).
[CmdletBinding()]
param(
    [switch]$SemTls,
    [ValidateRange(0, 65535)]
    [int]$Porta = 0,
    # Vazio = a raiz da tarefa DashboardLotufo (sem ela, C:\DashboardLotufo).
    [string]$Raiz = ""
)
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "watchdog.ps1"
if (-not (Test-Path $script)) { throw "watchdog.ps1 nao encontrado em $script" }
if (-not (Test-Path (Join-Path $PSScriptRoot "comum_tls.ps1"))) { throw "comum_tls.ps1 nao encontrado ao lado de $script" }
# Modo, porta e raiz tem que ser os da tarefa principal: watchdog em HTTPS com a producao em HTTP (ou o contrario), ou
# conferindo outra porta, nunca a veria saudavel e a reiniciaria a cada 3 minutos (gate Sol da PR #476). Com a tarefa
# instalada, os argumentos dela mandam: -Porta e -Raiz omitidos vem dela, e um valor explicito diferente aborta aqui,
# antes de registrar (como no deploy.ps1). Sem a tarefa, valem os padroes do modo.
$tarefa = Get-ScheduledTask -TaskName "DashboardLotufo" -ErrorAction SilentlyContinue
if ($tarefa) {
    $argumentosTarefa = ($tarefa.Actions | ForEach-Object { $_.Arguments }) -join " "
    $tarefaSemTls = [bool]($argumentosTarefa -match "-SemTls\b")
    if ($tarefaSemTls -ne [bool]$SemTls) {
        if ($tarefaSemTls) { $modo = "HTTP (-SemTls)" } else { $modo = "HTTPS (sem -SemTls)" }
        throw "a tarefa DashboardLotufo esta em $modo; instale o watchdog no mesmo modo. Nada foi alterado."
    }
    if ($argumentosTarefa -match "-Porta (\d+)") { $portaTarefa = [int]$Matches[1] }
    elseif ($tarefaSemTls) { $portaTarefa = 80 }
    else { $portaTarefa = 8443 }
    if ($argumentosTarefa -match '-Raiz\s+(?:"([^"]+)"|(\S+))') {
        if ($Matches[1]) { $raizTarefa = $Matches[1] } else { $raizTarefa = $Matches[2] }
    } else { $raizTarefa = "C:\DashboardLotufo" }
    if ($Porta -eq 0) { $Porta = $portaTarefa }
    elseif ($Porta -ne $portaTarefa) {
        throw "-Porta $Porta nao bate com a tarefa DashboardLotufo (porta $portaTarefa). Nada foi alterado."
    }
    if (-not $Raiz) { $Raiz = $raizTarefa }
    elseif ($Raiz.TrimEnd("\") -ne $raizTarefa.TrimEnd("\")) {
        throw "-Raiz $Raiz nao bate com a tarefa DashboardLotufo (raiz $raizTarefa). Nada foi alterado."
    }
}
if ($Porta -eq 0) {
    if ($SemTls) { $Porta = 80 } else { $Porta = 8443 }
}
if (-not $Raiz) { $Raiz = "C:\DashboardLotufo" }
$certificado = Join-Path $Raiz "segredos\tls\cert.pem"
if ($SemTls) {
    $url = "http://localhost:$Porta/api/health"
    $argumentos = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Url "{1}"' -f $script, $url
} else {
    $url = "https://localhost:$Porta/api/health"
    # Sem o certificado o watchdog nunca veria a producao saudavel e a reiniciaria a cada 3 minutos.
    if (-not (Test-Path -LiteralPath $certificado)) {
        throw "certificado do HTTPS nao encontrado em $certificado (rodar scripts\gerar_certificado.ps1 -Raiz $Raiz, ou -SemTls)"
    }
    $argumentos = ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Url "{1}"' -f $script, $url) + " -Certificado `"$certificado`""
}

$acao = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argumentos
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
