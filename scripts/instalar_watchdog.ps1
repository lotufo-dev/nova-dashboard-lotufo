# Registra a tarefa DashboardLotufoWatchdog: roda watchdog.ps1 a cada 3 minutos como
# SYSTEM (mesma conta da producao). Idempotente (-Force). Rodar como administrador.
#
# Usa Register-ScheduledTask (nao schtasks) porque o caminho do repo tem espacos
# ("Nova Dashboard Lotufo") e o schtasks /TR quebra o argumento nos espacos.
# Para remover: Unregister-ScheduledTask -TaskName DashboardLotufoWatchdog -Confirm:$false
#
# Modo e porta iguais aos da tarefa DashboardLotufo (instalar_autostart.ps1). Padrao (issue #425): HTTPS, o watchdog
# confere https://localhost:<porta>/api/health aceitando so' o certificado <Raiz>\segredos\tls\cert.pem (pelo
# thumbprint). -SemTls: http://localhost:<porta>/api/health. -Porta: 0 = padrao do modo (80 com -SemTls, 8443 com
# TLS). Ex.: -Porta 8080 na VM em que a 80 e' do IIS.
[CmdletBinding()]
param(
    [switch]$SemTls,
    [ValidateRange(0, 65535)]
    [int]$Porta = 0,
    [string]$Raiz = "C:\DashboardLotufo"
)
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "watchdog.ps1"
if (-not (Test-Path $script)) { throw "watchdog.ps1 nao encontrado em $script" }
if (-not (Test-Path (Join-Path $PSScriptRoot "comum_tls.ps1"))) { throw "comum_tls.ps1 nao encontrado ao lado de $script" }
if ($Porta -eq 0) {
    if ($SemTls) { $Porta = 80 } else { $Porta = 8443 }
}
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
