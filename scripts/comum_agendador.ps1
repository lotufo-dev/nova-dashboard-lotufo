# Conversa com o Agendador de Tarefas do Windows por schtasks.exe, sem cmdlets CIM (issue #386):
# em 2026-11-04 um deploy ficou mais de 10 minutos parado em Get-ScheduledTask porque o provedor
# CIM do agendador nao respondia, enquanto schtasks.exe respondia em segundos. Dot-sourced por
# deploy.ps1 e watchdog.ps1 (`. (Join-Path $PSScriptRoot "comum_agendador.ps1")`).
# So' ASCII, sem BOM (PowerShell 5.1 le como ANSI).

# Le a saida redirecionada do schtasks. O /XML declara UTF-16 mas costuma sair nos bytes da
# pagina de codigo; se vier UTF-16 de verdade (NUL no meio), le de novo como Unicode.
function LerSaidaAgendador([string]$arquivo) {
    $texto = Get-Content $arquivo -Raw -ErrorAction SilentlyContinue
    if ($texto -and $texto.IndexOf([char]0) -ge 0) { $texto = Get-Content $arquivo -Raw -Encoding Unicode -ErrorAction SilentlyContinue }
    if ($null -eq $texto) { return "" }
    return $texto
}

# Chama schtasks.exe (ou $Executavel, so' para prova) num processo filho e espera no maximo
# $LimiteSegundos. Devolve @{ Estourou; FilhoVivo; Codigo; Saida }. Estouro mata o processo filho pelo proprio objeto
# e espera de novo (5 s) a morte; se nem assim ele morreu, FilhoVivo=$true: um /End ou /Run orfao ainda pode concluir
# depois, e quem chama mantem o sentinela do watchdog (gate Sol da PR #389). Quem chama decide o resto (abortar, voltar
# o pinado, registrar no log). Saida vai para arquivo temporario, nao para pipe: pipe cheio travaria o filho e o
# WaitForExit.
function Agendador([string[]]$argumentos, [int]$LimiteSegundos = 30, [string]$Executavel = "schtasks.exe") {
    $saidaArq = [System.IO.Path]::GetTempFileName()
    $erroArq = [System.IO.Path]::GetTempFileName()
    try {
        $p = Start-Process -FilePath $Executavel -ArgumentList $argumentos -NoNewWindow -PassThru `
            -RedirectStandardOutput $saidaArq -RedirectStandardError $erroArq
        $null = $p.Handle   # sem isto o PowerShell 5.1 pode devolver ExitCode nulo
        if (-not $p.WaitForExit($LimiteSegundos * 1000)) {
            try { $p.Kill() } catch {}
            $morreu = $false
            try { $morreu = $p.WaitForExit(5000) } catch {}
            return @{ Estourou = $true; FilhoVivo = (-not $morreu); Codigo = -1; Saida = "" }
        }
        $saida = ((LerSaidaAgendador $saidaArq) + "`n" + (LerSaidaAgendador $erroArq)).Trim()
        return @{ Estourou = $false; FilhoVivo = $false; Codigo = $p.ExitCode; Saida = $saida }
    } finally {
        Remove-Item $saidaArq, $erroArq -Force -ErrorAction SilentlyContinue
    }
}

# Estado da tarefa pela API COM Schedule.Service (TASK_STATE numerico: o /FO LIST e o /FO CSV do schtasks trazem o
# estado em texto no idioma do Windows). A COM roda num powershell filho (scripts\estado_tarefa.ps1, arquivo estatico:
# -EncodedCommand a cada leitura, como SYSTEM, tende a ser barrado pelo antivirus como ofuscacao), pela Agendador, com o
# mesmo tempo limite: na propria sessao ela travaria sem como matar. O filho sai com 100 + estado (1 Disabled, 2 Queued,
# 3 Ready, 4 Running); Unknown (0), erro do filho (sai com 1), estouro ou filho que nao morreu viram "desconhecido".
# Parada so' e' "Ready" ou "Disabled"; "Queued" e' ativa (o /Run seria ignorado pela instancia enfileirada).
function EstadoDaTarefa([string]$Tarefa, [int]$LimiteSegundos = 30) {
    $arquivo = Join-Path $PSScriptRoot "estado_tarefa.ps1"
    $r = Agendador @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", "`"$arquivo`"", "-Tarefa", $Tarefa) `
        $LimiteSegundos "powershell.exe"
    if ($r.Estourou -or $r.Codigo -lt 101 -or $r.Codigo -gt 104) { return "desconhecido" }
    return @("Disabled", "Queued", "Ready", "Running")[$r.Codigo - 101]
}
function TarefaParada([string]$estado) { return ($estado -eq "Ready" -or $estado -eq "Disabled") }
