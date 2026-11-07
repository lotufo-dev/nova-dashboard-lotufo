# Estado da tarefa agendada pela API COM Schedule.Service, sem o provedor CIM do agendador (issue #386). Chamado por
# EstadoDaTarefa (comum_agendador.ps1) num processo filho, que o mata no tempo limite. Sai com 100 + TASK_STATE
# (0 Unknown, 1 Disabled, 2 Queued, 3 Ready, 4 Running); erro sai com 1. So' ASCII, sem BOM (PowerShell 5.1).
param([Parameter(Mandatory = $true)][string]$Tarefa)
$ErrorActionPreference = "Stop"
try {
    $servico = New-Object -ComObject Schedule.Service
    $servico.Connect()
    $estado = [int]$servico.GetFolder("\").GetTask($Tarefa).State
} catch { exit 1 }
exit (100 + $estado)
