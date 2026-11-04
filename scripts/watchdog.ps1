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
param(
    [string]$Url = "http://localhost/api/health",
    [string]$Tarefa = "DashboardLotufo",
    [string]$Log = "C:\DashboardLotufo\logs\watchdog.log",
    [string]$Pausa = "C:\DashboardLotufo\watchdog.pause",
    # Tempo limite, em segundos, de cada chamada ao agendador (schtasks.exe).
    [ValidateRange(1, 600)]
    [int]$LimiteAgendador = 30
)

function Escrever($m) {
    try { Add-Content -Path $Log -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) -Encoding utf8 } catch {}
}
function Saudavel {
    try { return ((Invoke-WebRequest -Uri $Url -TimeoutSec 10 -UseBasicParsing).StatusCode -eq 200) }
    catch { return $false }
}

if (Test-Path $Pausa) { exit 0 }              # manutencao em curso: nao tocar
if (Saudavel) { exit 0 }
Start-Sleep -Seconds 15
if (Test-Path $Pausa) { exit 0 }
if (Saudavel) { exit 0 }                       # foi so um blip transitorio

. (Join-Path $PSScriptRoot "comum_agendador.ps1")   # Agendador: schtasks.exe com tempo limite

Escrever "SEM RESPOSTA em $Url -> reiniciando a tarefa $Tarefa"
$fim = Agendador @("/End", "/TN", $Tarefa) $LimiteAgendador
if ($fim.Estourou) {
    Escrever "agendador de tarefas nao respondeu (schtasks /End levou mais de $LimiteAgendador s)"
    exit 1
}
if ($fim.Codigo -ne 0) { Escrever ("schtasks /End devolveu " + $fim.Codigo + ": " + $fim.Saida + " (segue para o /Run)") }
Start-Sleep -Seconds 3
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
Escrever ("pos-restart saudavel=" + (Saudavel))
