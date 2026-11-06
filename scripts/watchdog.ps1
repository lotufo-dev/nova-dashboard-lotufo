# Watchdog da producao: reergue a tarefa DashboardLotufo se o servidor cair.
#
# Motivo (incidente 2026-09-10 08:17->09:58): o processo do uvicorn morreu e a tarefa
# agendada NAO reergue sozinha (ficou 'Ready' com LastTaskResult de timeout). Este script
# roda a cada poucos minutos (tarefa DashboardLotufoWatchdog, ver instalar_watchdog.ps1),
# confere a saude e, se estiver fora, para e reinicia a tarefa principal.
#
# NAO restaura durante manutencao: se existir o arquivo-sentinela $Pausa, sai sem mexer
# (o deploy cria o sentinela antes de parar a producao e apaga depois). Faz dupla checagem
# com 15s de intervalo para nao reiniciar por um blip de rede transitorio.
#
# HTTPS (issue #425): com -Url https://localhost:<porta>/... o -Certificado e' o cert.pem da instalacao
# (<raiz>\segredos\tls\cert.pem) e so' esse certificado e' aceito, pelo thumbprint (comum_tls.ps1). O arquivo e'
# lido a cada rodada: certificado trocado nao pede reinstalar o watchdog.
param(
    [string]$Url = "http://localhost/api/health",
    [string]$Certificado = "",
    [string]$Tarefa = "DashboardLotufo",
    [string]$Log = "C:\DashboardLotufo\logs\watchdog.log",
    [string]$Pausa = "C:\DashboardLotufo\watchdog.pause"
)
# Erro sem tratamento para o script (e sai com 1); cada passo que pode falhar tem o seu try/catch e registra no log.
$ErrorActionPreference = "Stop"

function Escrever($m) {
    try { Add-Content -Path $Log -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) -Encoding utf8 } catch {}
}
. (Join-Path $PSScriptRoot "comum_tls.ps1")
$script:ultimoErro = ""
function Saudavel {
    try {
        $resposta = Invoke-SaudeLocal -Url $Url -Certificado $Certificado -TimeoutSec 10
        $script:ultimoErro = "HTTP $($resposta.StatusCode)"
        return ($resposta.StatusCode -eq 200)
    }
    catch { $script:ultimoErro = $_.Exception.Message; return $false }
}

if (Test-Path $Pausa) { exit 0 }              # manutencao em curso: nao tocar
# Problema no CONFERIDOR nao e' problema da producao (revisor da PR #476): cert.pem ilegivel ou ausente, ou o C# da
# saude bloqueado (antivirus no Add-Type), fariam o watchdog reiniciar uma producao saudavel a cada 3 minutos, para
# sempre. Nesses casos registra no log e sai sem tocar na tarefa.
if ($Url -like "https://*") {
    try {
        Initialize-DashSaudeLocal
        $null = Get-ThumbprintDoCertificado -Caminho $Certificado
    }
    catch {
        Escrever ("CONFERIDOR com problema, producao NAO reiniciada: " + $_.Exception.Message)
        exit 1
    }
}
if (Saudavel) { exit 0 }
Start-Sleep -Seconds 15
if (Test-Path $Pausa) { exit 0 }
if (Saudavel) { exit 0 }                       # foi so um blip transitorio

Escrever "SEM RESPOSTA em $Url ($script:ultimoErro) -> reiniciando a tarefa $Tarefa"
try { Stop-ScheduledTask -TaskName $Tarefa -ErrorAction SilentlyContinue } catch {}
Start-Sleep -Seconds 3
try {
    # -ErrorAction Stop: tarefa desabilitada da' erro nao fatal, que sem isto passaria por "disparado" (gate Sol da PR #476)
    Start-ScheduledTask -TaskName $Tarefa -ErrorAction Stop
    Escrever "Start-ScheduledTask disparado"
} catch {
    Escrever ("FALHA ao iniciar: " + $_.Exception.Message)
    exit 1
}
Start-Sleep -Seconds 25
if (Saudavel) { Escrever "pos-restart saudavel=True" }
else {
    Escrever "pos-restart saudavel=False ($script:ultimoErro)"
    exit 1
}
