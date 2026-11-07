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
# Fala com o agendador por schtasks.exe, nunca por cmdlet CIM (issue #386: o provedor CIM do
# agendador pode ficar sem responder), com tempo limite de 30 s por chamada; estouro vai
# para o log e o script sai com 1 (a tarefa do watchdog repete em 3 min).
#
# HTTPS (issue #425): com -Url https://localhost:<porta>/... o -Certificado e' o cert.pem da instalacao
# (<raiz>\segredos\tls\cert.pem) e so' esse certificado e' aceito, pelo thumbprint (comum_tls.ps1). O arquivo e'
# lido a cada rodada: certificado trocado nao pede reinstalar o watchdog.
param(
    [string]$Url = "http://localhost/api/health",
    [string]$Certificado = "",
    [string]$Tarefa = "DashboardLotufo",
    [string]$Log = "C:\DashboardLotufo\logs\watchdog.log",
    [string]$Pausa = "C:\DashboardLotufo\watchdog.pause",
    # Tempo limite, em segundos, de cada chamada ao agendador (schtasks.exe).
    [ValidateRange(1, 600)]
    [int]$LimiteAgendador = 30
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

# Dono da porta da URL de saude (issue #480). A consulta lista TODOS os listeners e filtra a porta no pipeline: porta
# livre e' lista vazia ($null), e erro do provedor NetTCPIP/CIM sobe para quem chamou, que registra e sai com 1 (gate
# Sol da PR #494: erro tratado como "porta livre" iniciaria outra instancia contra o orfao, em laco).
$porta = ([uri]$Url).Port
function DonoDaPorta {
    $c = Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -eq $porta } | Select-Object -First 1
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

. (Join-Path $PSScriptRoot "comum_agendador.ps1")   # Agendador: schtasks.exe com tempo limite

# Daqui em diante a producao esta comprovadamente fora (duas consultas, 15 s de intervalo). Agendador que nao responde
# a tempo nao inicia nada (sai com 1, o watchdog repete em 3 min). O schtasks nao da' o estado da tarefa sem depender
# do idioma do Windows, entao /End que falha (tarefa ja' parada, "Ready" com o processo morto, como no incidente de
# 2026-09-10) so' vai para o log e segue: quem segura a porta e' tratado abaixo, e o /Run ignorado por uma instancia
# que continua viva (MultipleInstances IgnoreNew) aparece como "apos-reinicio saudavel=nao" e sai com 1.
SairSePausado "antes de parar a tarefa"
Escrever "SEM RESPOSTA em $Url ($script:ultimoErro) -> reiniciando a tarefa $Tarefa"
$fim = Agendador @("/End", "/TN", $Tarefa) $LimiteAgendador
if ($fim.Estourou) {
    Escrever "agendador de tarefas nao respondeu (schtasks /End levou mais de $LimiteAgendador s) -> nada iniciado"
    exit 1
}
if ($fim.Codigo -ne 0) { Escrever ("schtasks /End devolveu " + $fim.Codigo + ": " + $fim.Saida + " (segue para o /Run)") }
Start-Sleep -Seconds 3
# Servidor ORFAO (incidente de 2026-09-21, issue #480): parar a tarefa (schtasks /End) nao mata o uvicorn; ele segura a porta, a
# instancia nova morre com WinError 10048 e a tarefa volta a Ready. So' o uvicorn da dashboard e' morto, reconhecido
# pelos argumentos exatos com que o rodar_producao.ps1 o sobe ("-m uvicorn --factory app.main:create_app" e "--port
# <porta>"); o caminho do executavel nao serve, porque o python.exe do venv no Windows e' um lancador e quem escuta e' o
# python base, filho dele. Qualquer outro dono da porta, ou orfao que nao morre, deixa a tarefa parada e sai com 1.
function EDaDashboard($p) {
    return ($p.CommandLine -match "-m uvicorn --factory app\.main:create_app " -and $p.CommandLine -match "--port $porta(\s|$)")
}
SairSePausado "antes de conferir a porta"
try { $orfao = DonoDaPorta }
catch {
    Escrever ("FALHA ao consultar a porta ${porta}, nada iniciado: " + $_.Exception.Message)
    exit 1
}
if ($orfao) {
    if (-not (EDaDashboard $orfao)) {
        Escrever "porta $porta ocupada pelo PID $($orfao.ProcessId) ($($orfao.Name)), que nao e' a dashboard -> nada iniciado"
        exit 1
    }
    # Gate Sol da PR #494: a manutencao pode ter comecado (e subido um servidor a mao) desde a ultima conferencia, e o
    # PID pode ter sido reusado; confere o sentinela e o dono de novo logo antes de matar.
    SairSePausado "antes de encerrar o orfao"
    try { $agora = DonoDaPorta } catch { $agora = $null }
    if (-not $agora -or $agora.ProcessId -ne $orfao.ProcessId -or "$($agora.CreationDate)" -ne "$($orfao.CreationDate)") {
        Escrever "dono da porta $porta mudou antes de encerrar o PID $($orfao.ProcessId) -> nada iniciado"
        exit 1
    }
    Escrever "servidor orfao na porta $porta (PID $($orfao.ProcessId), criado em $($orfao.CreationDate)) -> encerrando"
    try { Stop-Process -Id $orfao.ProcessId -Force -ErrorAction Stop }
    catch { Escrever ("FALHA ao encerrar o PID $($orfao.ProcessId): " + $_.Exception.Message) }
    Start-Sleep -Seconds 3
    try { $resto = DonoDaPorta }
    catch {
        Escrever ("FALHA ao consultar a porta $porta depois de encerrar o orfao, nada iniciado: " + $_.Exception.Message)
        exit 1
    }
    if ($resto) {
        Escrever "porta $porta ocupada pelo PID $($resto.ProcessId) depois de encerrar o orfao -> nada iniciado"
        exit 1
    }
}
SairSePausado "entre a parada e o inicio"
# /Run com codigo diferente de 0 (tarefa desabilitada, inexistente) e' falha, nunca "disparado" (gate Sol da PR #476)
$inicio = Agendador @("/Run", "/TN", $Tarefa) $LimiteAgendador
if ($inicio.Estourou) {
    Escrever "agendador de tarefas nao respondeu (schtasks /Run levou mais de $LimiteAgendador s)"
    exit 1
}
if ($inicio.Codigo -ne 0) {
    Escrever ("FALHA ao iniciar (schtasks /Run devolveu " + $inicio.Codigo + "): " + $inicio.Saida)
    exit 1
}
Escrever "schtasks /Run disparado"
Start-Sleep -Seconds 25
if (Saudavel) { Escrever "apos-reinicio saudavel=sim" }
else {
    Escrever "apos-reinicio saudavel=nao ($script:ultimoErro)"
    exit 1
}
