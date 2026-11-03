# Instala a tarefa agendada que sobe o Dashboard no boot (rodar 1x, como administrador).
[CmdletBinding()]
param(
    # Escape para decisao consciente do operador (ex.: a arvore fica num volume
    # onde a ACL e' gerida por outro controle). Desligado por padrao: o normal
    # e' o script ABORTAR quando a arvore estiver aberta.
    [switch]$IgnorarAcl,
    # Diretorio PINADO de producao (mitigacao [16], 2026-09-10): a tarefa executa o
    # rodar_producao.ps1 DESTE diretorio (worktree git dedicado, detached HEAD), NAO do
    # tree de dev. Deploys atualizam esse diretorio via scripts\deploy.ps1.
    [string]$AppDir = "C:\DashboardLotufo\app",
    # Repassados a rodar_producao.ps1 (arvore de producao e pasta da copia externa).
    [string]$Raiz = "C:\DashboardLotufo",
    [string]$BackupExterno = "",
    [switch]$SemTls,
    # Porta do servidor, repassada a rodar_producao.ps1 so quando informada (0 = padrao
    # do modo: 80 com -SemTls, 8443 com TLS). Ex.: 8080 na VM em que a 80 e' do IIS.
    [ValidateRange(0, 65535)]
    [int]$Porta = 0,
    # Repassados a rodar_producao.ps1: RM (fase 5) e Microsoft 365 (fase 6).
    [string]$RmUrl = "",
    [string]$RmUsuario = "",
    [string]$RmSenhaArquivo = "",
    [switch]$RmHttpInseguro,
    [string]$GraphClientId = "",
    [string]$GraphTenant = "organizations",
    [string]$GraphCaixa = "me",
    [string]$GraphSite = ""
)
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "comum_acl.ps1")

# A producao roda do diretorio PINADO ($AppDir), nao do tree onde este instalador esta.
$repo = $AppDir
$roteiro = Join-Path $repo "scripts\rodar_producao.ps1"
if (-not (Test-Path $roteiro)) { throw "rodar_producao.ps1 nao encontrado em $roteiro -- o diretorio pinado ($AppDir) foi preparado? (git worktree + .venv + build)" }

# --- conferencia de ACL antes de registrar a tarefa ---------------------------
# A tarefa roda como SYSTEM, com RunLevel Highest, e executa um .ps1 que esta
# DENTRO deste repositorio, com o Python de backend\.venv. Ou seja: quem puder
# escrever em qualquer um desses caminhos escolhe o que a maquina executa como
# SYSTEM no proximo boot -- elevacao de privilegio completa, sem exploit nenhum.
# Se o repo estiver numa pasta de usuario (C:\Users\...) isso e' o caso PADRAO,
# porque o dono da pasta tem Modificar por heranca.
# Conferimos os containers e os dois executaveis de fato usados; assume-se que os
# arquivos abaixo herdam a ACL do container (o normal). CREATOR OWNER e
# TrustedInstaller sao aceitos: nao sao contas de logon.
$confiaveis = @($SID_SISTEMA, $SID_ADMINISTRADORES, $SID_TRUSTEDINSTALLER, $SID_CRIADOR_PROPRIETARIO)
$alvos = @(
    $repo,
    $roteiro,
    (Join-Path $repo "backend"),
    (Join-Path $repo "backend\.venv"),
    (Join-Path $repo "backend\.venv\Scripts\python.exe")
)

$aberturas = @()
foreach ($alvo in $alvos) {
    if (-not (Test-Path -LiteralPath $alvo)) { continue }
    foreach ($achado in (Get-EscritoresIndevidos -Caminho $alvo -SidsConfiaveis $confiaveis)) {
        $aberturas += ("{0}`n      {1}" -f $alvo, $achado)
    }
    # Dono conta como abertura: sem nenhuma ACE em nome dele, o dono ainda reescreve
    # a ACL e se reconcede Modificar -- mesma elevacao para SYSTEM, um passo a mais.
    $dono = Get-DonoIndevido -Caminho $alvo -SidsConfiaveis $confiaveis
    if ($null -ne $dono) { $aberturas += ("{0}`n      {1}" -f $alvo, $dono) }
}

if ($aberturas.Count -gt 0) {
    Write-Host "ACL insegura: a arvore que rodaria como SYSTEM pode ser alterada por outras contas." -ForegroundColor Red
    foreach ($a in $aberturas) { Write-Host ("  - " + $a) -ForegroundColor Red }
    Write-Host ""
    Write-Host "Enderece a arvore antes de instalar a tarefa (como administrador):" -ForegroundColor Yellow
    Write-Host ("  icacls `"{0}`" /inheritance:r /grant:r `"*S-1-5-18:(OI)(CI)F`" `"*S-1-5-32-544:(OI)(CI)F`" /T" -f $repo) -ForegroundColor Yellow
    Write-Host ("  icacls `"{0}`" /setowner `"*S-1-5-32-544`" /T" -f $repo) -ForegroundColor Yellow
    Write-Host "  (ou mova o repositorio para fora de C:\Users, ex.: C:\DashboardLotufo)" -ForegroundColor Yellow
    if (-not $IgnorarAcl) {
        Write-Host "Instalacao abortada. Use -IgnorarAcl para instalar mesmo assim, por sua conta." -ForegroundColor Red
        exit 1
    }
    Write-Warning "-IgnorarAcl informado: registrando a tarefa com a arvore gravavel por terceiros."
}

# --- registro da tarefa -------------------------------------------------------
$argumentos = "-NoProfile -ExecutionPolicy Bypass -File `"$roteiro`" -Raiz `"$Raiz`""
if ($BackupExterno) { $argumentos += " -BackupExterno `"$BackupExterno`"" }
if ($SemTls) { $argumentos += " -SemTls" }
if ($Porta -ne 0) { $argumentos += " -Porta $Porta" }
if ($RmUsuario -and $RmSenhaArquivo) {
    $argumentos += " -RmUsuario `"$RmUsuario`" -RmSenhaArquivo `"$RmSenhaArquivo`""
    if ($RmUrl) { $argumentos += " -RmUrl `"$RmUrl`"" }
    if ($RmHttpInseguro) { $argumentos += " -RmHttpInseguro" }
}
if ($GraphClientId) {
    $argumentos += " -GraphClientId `"$GraphClientId`" -GraphTenant `"$GraphTenant`" -GraphCaixa `"$GraphCaixa`""
    if ($GraphSite) { $argumentos += " -GraphSite `"$GraphSite`"" }
}
$acao = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argumentos
$gatilho = New-ScheduledTaskTrigger -AtStartup
# Reinicio automatico: o servidor que cair (excecao, kill, uvicorn morto) volta
# sozinho ate 3 vezes com 1 min de intervalo; sem limite de tempo de execucao (o
# padrao de 3 dias mataria o servidor no quarto dia); sobe assim que possivel se o
# gatilho do boot foi perdido.
$config = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable

# O gatilho -AtStartup so dispara em servidor desatendido se a tarefa rodar como conta de
# servico: sem -Principal, Register-ScheduledTask grava um principal interativo e a tarefa
# fica esperando alguem logar. CONFERIR: a conta SYSTEM precisa enxergar o caminho do repo
# e o backend\.venv (se o repo estiver em pasta de usuario ou em rede, trocar por uma conta
# de servico que tenha esse acesso).
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName "DashboardLotufo" -Action $acao -Trigger $gatilho `
    -Principal $principal -Settings $config -Force | Out-Null

Write-Host "Tarefa 'DashboardLotufo' instalada. Inicie com: Start-ScheduledTask -TaskName DashboardLotufo"
