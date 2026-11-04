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
# $LimiteSegundos. Devolve @{ Estourou; Codigo; Saida }. Estouro mata o processo filho e devolve
# Estourou=$true; quem chama decide o que fazer (abortar, voltar o pinado, registrar no log).
# Saida vai para arquivo temporario, nao para pipe: pipe cheio travaria o filho e o WaitForExit.
function Agendador([string[]]$argumentos, [int]$LimiteSegundos = 30, [string]$Executavel = "schtasks.exe") {
    $saidaArq = [System.IO.Path]::GetTempFileName()
    $erroArq = [System.IO.Path]::GetTempFileName()
    try {
        $p = Start-Process -FilePath $Executavel -ArgumentList $argumentos -NoNewWindow -PassThru `
            -RedirectStandardOutput $saidaArq -RedirectStandardError $erroArq
        $null = $p.Handle   # sem isto o PowerShell 5.1 pode devolver ExitCode nulo
        if (-not $p.WaitForExit($LimiteSegundos * 1000)) {
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
            return @{ Estourou = $true; Codigo = -1; Saida = "" }
        }
        $saida = ((LerSaidaAgendador $saidaArq) + "`n" + (LerSaidaAgendador $erroArq)).Trim()
        return @{ Estourou = $false; Codigo = $p.ExitCode; Saida = $saida }
    } finally {
        Remove-Item $saidaArq, $erroArq -Force -ErrorAction SilentlyContinue
    }
}
