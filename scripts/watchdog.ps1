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
$script:thumbprint = ""
function Saudavel {
    try {
        $resposta = Invoke-SaudeLocal -Url $Url -Certificado $Certificado -Thumbprint $script:thumbprint -TimeoutSec 10
        $script:ultimoErro = "HTTP $($resposta.StatusCode)"
        return ($resposta.StatusCode -eq 200)
    }
    catch { $script:ultimoErro = $_.Exception.Message; return $false }
}
# Manutencao em curso (sentinela do deploy ou do runbook): nao tocar. Conferido de novo antes de cada passo que mexe
# na tarefa, porque a manutencao pode comecar no meio desta execucao (gate Sol da PR #476).
function SairSePausado([string]$Momento) {
    if (Test-Path $Pausa) {
        if ($Momento) { Escrever "sentinela de manutencao apareceu $Momento -> nada reiniciado" }
        exit 0
    }
}

# Dono da porta da URL de saude (issue #480). Sem ninguem escutando, o Get-NetTCPConnection da' erro: vira $null.
$porta = ([uri]$Url).Port
function DonoDaPorta {
    try { $c = Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction Stop | Select-Object -First 1 }
    catch { return $null }
    if (-not $c) { return $null }
    # CIM que falha nao vira "porta livre": o dono sem linha de comando conhecida nao e' morto, e nada e' iniciado
    try { $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction Stop } catch { $p = $null }
    if (-not $p) { return [pscustomobject]@{ ProcessId = $c.OwningProcess; Name = "desconhecido"; CommandLine = ""; CreationDate = "" } }
    return $p
}

SairSePausado ""
# Problema no CONFERIDOR nao e' problema da producao (revisor da PR #476): cert.pem ilegivel ou ausente, ou o C# da
# saude bloqueado (antivirus no Add-Type), fariam o watchdog reiniciar uma producao saudavel a cada 3 minutos, para
# sempre. O thumbprint e' lido UMA vez por execucao e usado em todas as consultas: o arquivo que ficar ilegivel no
# meio da execucao nao vira "producao fora". Falhou aqui, registra no log e sai sem tocar na tarefa.
if ($Url -like "https://*") {
    try {
        Initialize-DashSaudeLocal
        $script:thumbprint = Get-ThumbprintDoCertificado -Caminho $Certificado
    }
    catch {
        Escrever ("CONFERIDOR com problema, producao NAO reiniciada: " + $_.Exception.Message)
        exit 1
    }
}
if (Saudavel) { exit 0 }
Start-Sleep -Seconds 15
SairSePausado ""
if (Saudavel) { exit 0 }                       # foi so um blip transitorio

# Daqui em diante a producao esta comprovadamente fora (duas consultas, 15 s de intervalo). So' reinicia se a tarefa
# de fato puder ser reiniciada: parada que falha, ou instancia que continua "Running", fariam o Start ser ignorado
# (MultipleInstances IgnoreNew) com o log dizendo "disparado" (gate Sol da PR #476).
SairSePausado "antes de parar a tarefa"
Escrever "SEM RESPOSTA em $Url ($script:ultimoErro) -> reiniciando a tarefa $Tarefa"
try {
    $estado = (Get-ScheduledTask -TaskName $Tarefa -ErrorAction Stop).State
    # Parar so' o que esta rodando: a tarefa "Ready" com o processo morto (incidente de 2026-09-10) vai direto ao Start.
    if ("$estado" -eq "Running") { Stop-ScheduledTask -TaskName $Tarefa -ErrorAction Stop }
} catch {
    Escrever ("FALHA ao parar a tarefa, nada iniciado: " + $_.Exception.Message)
    exit 1
}
$parada = $false
foreach ($tentativa in 1..10) {
    Start-Sleep -Seconds 1
    try { $estado = (Get-ScheduledTask -TaskName $Tarefa -ErrorAction Stop).State } catch { $estado = "desconhecido" }
    if ("$estado" -ne "Running" -and "$estado" -ne "desconhecido") { $parada = $true; break }
}
if (-not $parada) {
    Escrever "tarefa $Tarefa continua '$estado' depois da parada -> nada iniciado"
    exit 1
}
# Servidor ORFAO (incidente de 2026-09-21, issue #480): Stop-ScheduledTask nao mata o uvicorn; ele segura a porta, a
# instancia nova morre com WinError 10048 e a tarefa volta a Ready. Como no deploy.ps1, so' o uvicorn da dashboard e'
# morto; qualquer outro dono da porta, ou orfao que nao morre, deixa a tarefa parada e sai com 1.
$orfao = DonoDaPorta
if ($orfao) {
    if ($orfao.CommandLine -notmatch "uvicorn" -or $orfao.CommandLine -notmatch "app\.main") {
        Escrever "porta $porta ocupada pelo PID $($orfao.ProcessId) ($($orfao.Name)), que nao e' a dashboard -> nada iniciado"
        exit 1
    }
    Escrever "servidor orfao na porta $porta (PID $($orfao.ProcessId), criado em $($orfao.CreationDate)) -> encerrando"
    try { Stop-Process -Id $orfao.ProcessId -Force -ErrorAction Stop }
    catch { Escrever ("FALHA ao encerrar o PID $($orfao.ProcessId): " + $_.Exception.Message) }
    Start-Sleep -Seconds 3
    $resto = DonoDaPorta
    if ($resto) {
        Escrever "porta $porta ocupada pelo PID $($resto.ProcessId) depois de encerrar o orfao -> nada iniciado"
        exit 1
    }
}
SairSePausado "entre a parada e o inicio"
try {
    # -ErrorAction Stop: tarefa desabilitada da' erro nao fatal, que sem isto passaria por "disparado" (gate Sol da PR #476)
    Start-ScheduledTask -TaskName $Tarefa -ErrorAction Stop
    Escrever "Start-ScheduledTask disparado"
} catch {
    Escrever ("FALHA ao iniciar: " + $_.Exception.Message)
    exit 1
}
Start-Sleep -Seconds 25
if (Saudavel) { Escrever "apos-reinicio saudavel=sim" }
else {
    Escrever "apos-reinicio saudavel=nao ($script:ultimoErro)"
    exit 1
}
