# Confere o /api/health da producao na propria maquina e imprime a resposta (issue #425). E' o que o runbook e a
# skill deploy usam na conferencia depois do deploy: com a producao em HTTPS o Invoke-WebRequest do PowerShell 5.1
# recusa o certificado autoassinado em https://localhost, e desligar a verificacao aceitaria qualquer um. Aqui so'
# vale o certificado da instalacao (<Raiz>\segredos\tls\cert.pem), pelo thumbprint (comum_tls.ps1).
#
#   scripts\saude_local.ps1 -Porta <porta>            (HTTPS, o normal)
#   scripts\saude_local.ps1 -Porta <porta> -SemTls    (producao em HTTP)
#
# Sai com 0 e o corpo do health quando a resposta e' 200; com 1 em qualquer outro caso.
# Este arquivo fica so' com ASCII (sem BOM, o 5.1 le como ANSI e acento quebra o parse).
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 65535)]
    [int]$Porta,
    [switch]$SemTls,
    [string]$Raiz = "C:\DashboardLotufo"
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "comum_tls.ps1")

$certificado = Join-Path $Raiz "segredos\tls\cert.pem"
if ($SemTls) { $url = "http://localhost:$Porta/api/health" } else { $url = "https://localhost:$Porta/api/health" }
try {
    $resposta = Invoke-SaudeLocal -Url $url -Certificado $certificado -TimeoutSec 12
}
catch {
    Write-Host "SEM RESPOSTA em ${url}: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
Write-Host "HTTP $($resposta.StatusCode) em $url"
Write-Output $resposta.Content
if ($resposta.StatusCode -ne 200) { exit 1 }
exit 0
