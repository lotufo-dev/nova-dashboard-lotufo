# Sobe o Dashboard em produção, servindo também o build React.
# Padrão: HTTPS na porta 8443 (pré-requisito: scripts\gerar_certificado.ps1).
# -SemTls: HTTP na porta 80 (http://<servidor>), sem certificado a instalar nas
# máquinas da rede — decisão do Leonardo em 2026-09-02; a senha trafega em claro
# dentro da rede interna. Pré-requisito comum: `npm run build` em frontend\.
#
# Árvore de produção SEPARADA do repositório (parecer de 2026-09-01): banco, snapshots
# e logs ficam em -Raiz (padrão C:\DashboardLotufo), nunca em backend\dados\ — essa
# pasta é do servidor de desenvolvimento. -BackupExterno é a pasta de outro volume ou
# compartilhamento que recebe uma cópia diária dos snapshots (com checksum).
[CmdletBinding()]
param(
    [string]$Raiz = "C:\DashboardLotufo",
    [string]$BackupExterno = "",
    [switch]$SemTls,
    # TOTVS RM (fase 5, leitura). Os tres juntos ligam a sincronizacao horaria; sem eles
    # o servidor sobe com o RM desligado. A senha fica num ARQUIVO de uma linha dentro
    # de $Raiz\segredos (ACL endurecida abaixo), nunca em variavel da tarefa.
    # O endereco da API (servidor e porta) fica FORA do repositorio, que e' publico. Ordem: -RmUrl,
    # variavel de ambiente DASH_RM_ENDERECO, primeira linha de $Raiz\segredos\rm-endereco.txt.
    [string]$RmUrl = "",
    [string]$RmUsuario = "",
    [string]$RmSenhaArquivo = "",
    # O RM da Lotufo so' responde HTTP: a credencial viaja em claro na LAN. O
    # cliente recusa http:// sem esta chave -- ligar e' decisao explicita (runbook).
    [switch]$RmHttpInseguro,
    # Microsoft 365 (so' ENVIO de e-mail, pela conta de cada usuario). ClientId do registro
    # de aplicativo no Entra ID (fluxo de codigo de dispositivo, sem segredo de cliente);
    # cada pessoa conecta a propria conta em Minha conta e o token fica em
    # $Raiz\segredos\usuarios.
    [string]$GraphClientId = "",
    [string]$GraphTenant = "organizations",
    # -GraphCaixa e -GraphSite: ignorados desde o bloco 9 (a leitura do Outlook e do
    # SharePoint saiu); mantidos para a tarefa agendada nao quebrar.
    [string]$GraphCaixa = "me",
    [string]$GraphSite = ""
)
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "comum_acl.ps1")

$repo = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repo "backend"
$certs = Join-Path $repo "certs"

# Chaves de desenvolvimento NUNCA valem em produção: DASH_DEV tira a flag "secure"
# do cookie de sessão, DASH_SEM_JOBS desliga o backup horário, DASH_SEM_FRONTEND
# derruba o build servido em "/" e DASH_DIST_PATH aponta esse build para outra
# pasta (uma env de teste esquecida serviria um dist errado como se fosse a
# produção). Uma delas herdada do ambiente (perfil, tarefa agendada, janela
# anterior) degradaria a produção em silêncio — limpar sempre.
foreach ($chave in "DASH_DEV", "DASH_SEM_JOBS", "DASH_SEM_FRONTEND", "DASH_DIST_PATH", "DASH_SEM_TLS") {
    Remove-Item -Path ("Env:" + $chave) -ErrorAction SilentlyContinue
}
if ($SemTls) { $env:DASH_SEM_TLS = "1" }

# Falhar alto se não houver build: sem isto o servidor sobe "funcionando", só que
# sem interface nenhuma — a "/" devolve 404 e ninguém entende por quê.
$indice = Join-Path $repo "frontend\dist\index.html"
if (-not (Test-Path $indice)) {
    # Write-Host + exit explícito: garante código de saída 1 para quem chamou
    # (tarefa agendada do autostart), sem depender do tratamento de erro do host.
    Write-Host "ERRO: build do frontend nao encontrado em $indice." -ForegroundColor Red
    Write-Host "Rode 'npm run build' em frontend\ antes de subir a producao." -ForegroundColor Red
    exit 1
}

# Caminhos absolutos: a produção nunca pode depender do diretório de trabalho.
$dados = Join-Path $Raiz "dados"
$backups = Join-Path $dados "backups"   # ancorado ao banco em app\main.py
$logs = Join-Path $Raiz "logs"
$env:DASH_DB_PATH = Join-Path $dados "dashboard.db"
$env:DASH_LOG_DIR = $logs
# Cadastro real: clone do repositorio privado `lotufo-cadastro`, FORA do worktree pinado (o deploy nao o toca;
# a skill deploy o atualiza com `git pull --ff-only` antes do `cadastro aplicar`). Sem esta variavel o
# `app.cli cadastro` leria o cadastro-exemplo/ ficticio.
$env:DASH_CADASTRO_DIR = Join-Path $Raiz "cadastro"
foreach ($chave in "DASH_RM_URL", "DASH_RM_USUARIO", "DASH_RM_SENHA", "DASH_RM_SENHA_ARQUIVO", "DASH_RM_SIMULADOR", "DASH_RM_HTTP_INSEGURO") {
    Remove-Item -Path "Env:$chave" -ErrorAction SilentlyContinue
}
if ($RmUsuario -and $RmSenhaArquivo -and -not $RmUrl) { $RmUrl = $env:DASH_RM_ENDERECO }
if ($RmUsuario -and $RmSenhaArquivo -and -not $RmUrl) {
    $arquivoEndereco = Join-Path $Raiz "segredos\rm-endereco.txt"
    if (Test-Path -LiteralPath $arquivoEndereco) {
        $linhaEndereco = Get-Content -LiteralPath $arquivoEndereco -TotalCount 1
        if ($linhaEndereco) { $RmUrl = $linhaEndereco.Trim() }
    }
}
if ($RmUsuario -and $RmSenhaArquivo -and $RmUrl) {
    if (-not (Test-Path -LiteralPath $RmSenhaArquivo)) {
        Write-Host "ERRO: arquivo da senha do RM nao encontrado: $RmSenhaArquivo" -ForegroundColor Red
        exit 1
    }
    $segredos = Split-Path -Parent $RmSenhaArquivo
    & icacls $segredos /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Falha ao restringir a ACL de $segredos (rodar como administrador)." }
    & icacls (Join-Path $segredos "*") /reset /T /Q | Out-Null
    Set-DonoAdministradores -Caminho $segredos -Recursivo
    Assert-AclSomenteSistemaEAdmins -Caminho $segredos
    $env:DASH_RM_URL = $RmUrl
    $env:DASH_RM_USUARIO = $RmUsuario
    $env:DASH_RM_SENHA_ARQUIVO = $RmSenhaArquivo
    if ($RmHttpInseguro) { $env:DASH_RM_HTTP_INSEGURO = "1" }
}
else {
    Write-Warning "Sem -RmUsuario/-RmSenhaArquivo ou sem o endereco da API (-RmUrl, variavel DASH_RM_ENDERECO ou $Raiz\segredos\rm-endereco.txt): sincronizacao com o RM desligada. Ver docs\runbook.md (TOTVS RM)."
}
foreach ($chave in "DASH_GRAPH_CLIENT_ID", "DASH_GRAPH_TENANT", "DASH_GRAPH_TOKEN_ARQUIVO", "DASH_GRAPH_TOKENS_DIR", "DASH_GRAPH_CAIXA", "DASH_GRAPH_SITE", "DASH_GRAPH_SIMULADOR") {
    Remove-Item -Path "Env:$chave" -ErrorAction SilentlyContinue
}
if ($GraphClientId) {
    # O token e' gravado pelo proprio servidor (login pela tela); a pasta de segredos
    # precisa existir e estar fechada ANTES, senao o arquivo nasceria com ACL herdada.
    $segredosGraph = Join-Path $Raiz "segredos"
    New-Item -ItemType Directory -Force -Path $segredosGraph | Out-Null
    & icacls $segredosGraph /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Falha ao restringir a ACL de $segredosGraph (rodar como administrador)." }
    & icacls (Join-Path $segredosGraph "*") /reset /T /Q | Out-Null
    Set-DonoAdministradores -Caminho $segredosGraph -Recursivo
    Assert-AclSomenteSistemaEAdmins -Caminho $segredosGraph
    $env:DASH_GRAPH_CLIENT_ID = $GraphClientId
    $env:DASH_GRAPH_TENANT = $GraphTenant
    # Uma conta Microsoft por usuario (envio de e-mail pela propria caixa, spec 2026-09-21 §5.1).
    $env:DASH_GRAPH_TOKENS_DIR = Join-Path $segredosGraph "usuarios"
}
else {
    Write-Warning "Sem -GraphClientId: envio de e-mail pela dashboard desligado. Ver docs\runbook.md (Envio de e-mail)."
}
# Hosts do OneDrive/SharePoint aceitos nos links de arquivo grande do protocolo (issue #118). O tenant da
# empresa fica FORA do repositorio, que e' publico. Ordem: variavel DASH_SHAREPOINT_HOSTS (nivel da maquina),
# primeira linha de $Raiz\segredos\sharepoint-hosts.txt. Lista separada por virgula. Sem nenhuma das duas,
# o servidor recusa todo link (falha fechada).
if (-not $env:DASH_SHAREPOINT_HOSTS) {
    $arquivoHosts = Join-Path $Raiz "segredos\sharepoint-hosts.txt"
    if (Test-Path -LiteralPath $arquivoHosts) {
        $linhaHosts = Get-Content -LiteralPath $arquivoHosts -TotalCount 1
        if ($linhaHosts) { $env:DASH_SHAREPOINT_HOSTS = $linhaHosts.Trim() }
    }
}
if (-not $env:DASH_SHAREPOINT_HOSTS) {
    Write-Warning "Sem DASH_SHAREPOINT_HOSTS (variavel ou $Raiz\segredos\sharepoint-hosts.txt): links do OneDrive no protocolo serao recusados. Ver docs\runbook.md (Envio de e-mail)."
}
if ($BackupExterno) {
    # "Externo" tem que ser outro disco: no mesmo volume do banco, a falha que leva o
    # banco leva a copia junto. UNC (\\servidor\...) passa; letra igual a do banco, nao.
    $volumeBanco = [System.IO.Path]::GetPathRoot($env:DASH_DB_PATH)
    $volumeCopia = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($BackupExterno))
    if (-not $BackupExterno.StartsWith("\\") -and $volumeCopia -ieq $volumeBanco) {
        Write-Host "ERRO: -BackupExterno ($BackupExterno) esta no mesmo volume do banco ($volumeBanco)." -ForegroundColor Red
        Write-Host "Aponte para outro disco ou para um compartilhamento de rede." -ForegroundColor Red
        exit 1
    }
    $env:DASH_BACKUP_EXTERNO = $BackupExterno
}
else {
    Remove-Item -Path Env:DASH_BACKUP_EXTERNO -ErrorAction SilentlyContinue
    Write-Warning "Sem -BackupExterno: os snapshots ficam so neste disco. Ver docs\runbook.md."
}

# Banco de produção ausente com banco de dev presente: quase sempre é a primeira
# subida depois da separação das árvores. Subir agora criaria uma produção VAZIA
# ao lado dos dados reais — parar e mandar migrar (runbook, "Primeira subida").
$dbDev = Join-Path $backend "dados\dashboard.db"
if (-not (Test-Path -LiteralPath $env:DASH_DB_PATH) -and (Test-Path -LiteralPath $dbDev)) {
    Write-Host "ERRO: nao ha banco em $($env:DASH_DB_PATH), mas existe $dbDev." -ForegroundColor Red
    Write-Host "Copie o banco de dev para la (com o servidor de dev PARADO) ou passe -Raiz. Ver docs\runbook.md." -ForegroundColor Red
    exit 1
}

# ACL NTFS restrita (spec §5): o banco tem hashes de senha, tokens de sessão e o
# log de auditoria. Criar as pastas antes (é o que db_path() faria) e travar em
# SYSTEM + Administradores: sem herança, sem "Usuários" da máquina lendo o .db.
# Backups (cada snapshot é uma cópia integral) e logs levam o mesmo tratamento.
#
# Endurecer o CONTAINER e mandar o conteudo HERDAR dele (`\* /reset /T`): arquivo
# criado antes do endurecimento (o .db copiado, backups antigos) passa a herdar
# SYSTEM + Administradores. NAO usar `/grant:r "...(OI)(CI)F" /T`: aplicado a um
# ARQUIVO, o ACE com flags de heranca vira "so para herdar" e o arquivo fica sem
# NENHUM acesso efetivo -- foi assim que o primeiro snapshot ficou inacessivel ate
# para Administradores (2026-09-02). O dono tambem e' trocado recursivamente: o
# dono reescreve a DACL quando quiser (WRITE_DAC implicito).
foreach ($pasta in $dados, $backups, $logs) {
    New-Item -ItemType Directory -Force -Path $pasta | Out-Null
    & icacls $pasta /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Falha ao restringir a ACL de $pasta (rodar como administrador)." }
    & icacls (Join-Path $pasta "*") /reset /T /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Falha ao fazer o conteudo de $pasta herdar a ACL (rodar como administrador)." }
    Set-DonoAdministradores -Caminho $pasta -Recursivo
    # icacls sai com 0 mesmo mantendo ACE EXPLICITA de terceiro (/grant:r so
    # substitui a dos SIDs citados; /inheritance:r so mata as herdadas). Confiar
    # no codigo de saida deixaria o banco -- com hashes de senha, tokens de sessao
    # e a auditoria -- aberto achando que estava fechado. Conferir de fato.
    Assert-AclSomenteSistemaEAdmins -Caminho $pasta
}

# E conferir o ARQUIVO, não só as pastas: é nele que estão os hashes, os tokens e a
# auditoria. A validação acima olha a ACL do container; um .db com ACE explícita de
# terceiro (ou com dono comum) sobrevive a ela sem aparecer. Os companheiros -wal e
# -shm entram na conferência porque o WAL carrega as páginas ainda não integradas —
# o mesmo conteúdo do banco. Ainda podem não existir (banco novo, ou fechado limpo):
# só se confere o que está no disco.
# A chave privada do TLS entra na mesma conferência: quem a lê passa a poder se fazer
# passar pelo servidor. O cert.pem é público, mas vai junto — trocá-lo é fraude igual.
$arquivos = @($env:DASH_DB_PATH, ($env:DASH_DB_PATH + "-wal"), ($env:DASH_DB_PATH + "-shm"))
if (-not $SemTls) { $arquivos += (Join-Path $certs "chave.pem"), (Join-Path $certs "cert.pem") }
foreach ($arquivo in $arquivos) {
    if (Test-Path -LiteralPath $arquivo) {
        Assert-AclSomenteSistemaEAdmins -Caminho $arquivo
    }
}

# --factory: o app só existe depois de create_app() (migrações + snapshot no boot + logs).
# --no-proxy-headers (#3, limite de login por origem): não há proxy na frente; sem a opção o uvicorn aceita
# X-Forwarded-For vindo de 127.0.0.1 e quem está no próprio servidor trocaria de origem a cada pedido.
Set-Location $backend
$python = Join-Path $backend ".venv\Scripts\python.exe"
if ($SemTls) {
    & $python -m uvicorn --factory app.main:create_app --no-proxy-headers --host 0.0.0.0 --port 80
} else {
    & $python -m uvicorn --factory app.main:create_app --no-proxy-headers `
        --host 0.0.0.0 --port 8443 `
        --ssl-keyfile (Join-Path $certs "chave.pem") --ssl-certfile (Join-Path $certs "cert.pem")
}
