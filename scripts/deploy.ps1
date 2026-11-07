# Deploy da producao PINADA (mitigacao [16], 2026-09-10): a producao NAO roda mais do
# working tree de desenvolvimento, e sim de um worktree git DEDICADO e imutavel em
# C:\DashboardLotufo\app (detached HEAD num commit). Assim uma edicao/branch/troca no
# tree de dev, ou um reboot no meio de uma edicao, nao muda o que a producao executa.
#
# Este script atualiza esse diretorio para um commit e reinicia, com o watchdog pausado
# (senao ele reergueria no meio) e ROLLBACK automatico para o commit anterior se a saude
# nao voltar. Rodar como administrador (parar/iniciar a tarefa exige).
#
# Fluxo de deploy: (1) commit+push no tree de dev; (2) rodar este script (Ref=origin/master).
# Os dados (banco/logs/backups) ficam em -Raiz (C:\DashboardLotufo), fora do codigo, e nao
# sao alterados (o banco so' e' lido, no backup pre-migracao). .venv, node_modules e dist do diretorio pinado sao reconstruidos aqui.
#
# Agendador de tarefas SEM cmdlets CIM (issue #386): em 2026-11-04 um deploy ficou mais de
# 10 minutos parado em Get-ScheduledTask porque o provedor CIM do agendador nao respondia,
# enquanto schtasks.exe respondia em segundos. Toda conversa com o agendador passa por
# schtasks.exe num processo filho com tempo limite (30 s); estouro antes do checkout aborta
# sem tocar no pinado, estouro no reinicio volta o pinado ao commit anterior.
#
# Chamar SEM redirecionar stderr (nada de *>&1): com ErrorActionPreference=Stop o PowerShell
# 5.1 transforma o aviso do Vite em erro fatal. Este arquivo fica so' com ASCII (sem BOM, o
# 5.1 le como ANSI e acento quebra o parse).
[CmdletBinding()]
param(
    [string]$Ref = "origin/master",
    [string]$AppDir = "C:\DashboardLotufo\app",
    [switch]$SemFrontend,  # pula npm/build quando a mudanca e' so backend/docs
    # Porta em que a producao responde. 0 = ler dos argumentos da tarefa DashboardLotufo
    # (-Porta N; sem ele, 80). Informada e diferente da tarefa, o deploy aborta antes do checkout.
    [ValidateRange(0, 65535)]
    [int]$Porta = 0,
    # Raiz dos dados (banco, segredos). Vazio = ler dos argumentos da tarefa DashboardLotufo (-Raiz "..."; sem ele,
    # o padrao do rodar_producao.ps1). Informada e diferente da tarefa, o deploy aborta antes do checkout.
    [string]$Raiz = "",
    # Tempo limite, em segundos, de cada chamada ao agendador de tarefas (schtasks.exe).
    # Estouro = "agendador de tarefas nao respondeu". So' para prova em servidor de revisao.
    [ValidateRange(1, 600)]
    [int]$LimiteAgendador = 30,
    # So' para prova: nome de um executavel que finge ser o schtasks.exe (ex.: um .cmd que dorme
    # mais que -LimiteAgendador), para ver o estouro de tempo sem travar o agendador de verdade.
    [string]$Schtasks = "schtasks.exe"
)
$ErrorActionPreference = "Stop"
$pause = "C:\DashboardLotufo\watchdog.pause"
$tarefaNome = "DashboardLotufo"
$py = Join-Path $AppDir "backend\.venv\Scripts\python.exe"
$lock = Join-Path $AppDir "backend\requirements.lock"
if (-not (Test-Path $py)) { throw "venv da producao ausente em $py (setup inicial do diretorio pinado nao feito)" }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "rode como administrador: parar e iniciar a tarefa $tarefaNome exige sessao elevada; nada foi alterado"
}

# Uma linha de progresso por etapa, com hora: quem acompanha por SSH sabe onde o script esta'.
function Etapa([string]$texto) { Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $texto) }

. (Join-Path $PSScriptRoot "comum_agendador.ps1")   # Agendador: schtasks.exe com tempo limite
function Agendar([string[]]$argumentos) { return Agendador $argumentos $LimiteAgendador $Schtasks }
$msgAgendador = "deploy abortado: agendador de tarefas nao respondeu"

# A porta e' a da tarefa agendada, nao uma segunda fonte: com a tarefa na 8080 (VM em que a 80 e' do IIS)
# um deploy na 80 acharia o IIS como dono da porta e abortaria DEPOIS do checkout, sem rollback.
# Le o XML da tarefa (schtasks /Query /XML) UMA vez: os argumentos saem em <Arguments>, sem depender
# do idioma dos cabecalhos do /FO LIST. Porta, raiz e modo (TLS) saem todos dele. Qualquer falha do /Query
# (tarefa inexistente, acesso negado, XML ilegivel) aborta antes de tudo: -Porta informada nao substitui raiz e modo
# desconhecidos, que decidem o arquivo da instalacao e o banco do backup (gate Sol da PR #389).
function ArgumentosDaTarefa {
    $r = Agendar @("/Query", "/TN", $tarefaNome, "/XML")
    if ($r.Estourou) {
        Write-Host "$msgAgendador (schtasks /Query levou mais de $LimiteAgendador s); nada foi alterado" -ForegroundColor Red
        exit 1
    }
    if ($r.Codigo -ne 0) {
        throw "nao consegui ler a tarefa $tarefaNome (schtasks /Query devolveu $($r.Codigo): $($r.Saida)); instale a tarefa (instalar_autostart.ps1) ou confira o agendador; nada foi alterado"
    }
    $acoes = [regex]::Matches($r.Saida, "<Arguments>([^<]*)</Arguments>")
    if ($acoes.Count -eq 0) {
        throw "nao consegui ler os argumentos da tarefa $tarefaNome no XML do schtasks; nada foi alterado"
    }
    # todas as acoes, como o Actions.Arguments do cmdlet; o XML escapa aspas e '&' (&quot; &amp;)
    return [System.Net.WebUtility]::HtmlDecode((($acoes | ForEach-Object { $_.Groups[1].Value }) -join " "))
}
$argumentosDaTarefa = ArgumentosDaTarefa
function PortaDaTarefa {
    $argumentosTarefa = $argumentosDaTarefa
    if ($argumentosTarefa -match "-Porta (\d+)") { return [int]$Matches[1] }
    # Sem -Porta vale o padrao do modo do rodar_producao.ps1 (issue #425): 80 com -SemTls, 8443 com TLS.
    if ($argumentosTarefa -match "-SemTls\b") { return 80 }
    return 8443
}
$portaTarefa = PortaDaTarefa
if ($Porta -eq 0) {
    $Porta = $portaTarefa
} elseif ($Porta -ne $portaTarefa) {
    throw "-Porta $Porta nao bate com a tarefa $tarefaNome (porta $portaTarefa); nada foi alterado"
}
Etapa "porta lida: $Porta (tarefa $tarefaNome, agendador respondeu)"

# A raiz tambem e' a da tarefa (issue #417, gate Sol da PR #437): dela saem o arquivo da instalacao conferido antes do
# reinicio e o banco do backup pre-migracao. Com a producao em outro disco, conferir C:\ recusaria o arquivo valido, ou
# aceitaria um velho enquanto o servidor confere o da raiz certa. O instalar_autostart.ps1 sempre grava -Raiz "...".
function RaizDaTarefa {
    $argumentosTarefa = $argumentosDaTarefa
    if ($argumentosTarefa -match '-Raiz\s+(?:"([^"]+)"|(\S+))') {
        if ($Matches[1]) { return $Matches[1] }
        return $Matches[2]
    }
    return "C:\DashboardLotufo"
}
$raizTarefa = RaizDaTarefa
if (-not $Raiz) {
    $Raiz = $raizTarefa
} elseif ($Raiz.TrimEnd("\") -ne $raizTarefa.TrimEnd("\")) {
    throw "-Raiz $Raiz nao bate com a tarefa DashboardLotufo (raiz $raizTarefa); nada foi alterado"
}
$instalacaoArquivo = Join-Path $Raiz "segredos\instalacao.json"   # o mesmo que o rodar_producao.ps1 passa ao servidor
$banco = Join-Path $Raiz "dados\dashboard.db"

# HTTPS (issue #425): o modo tambem e' o da tarefa. Com -SemTls nos argumentos (producao de antes do corte) a saude e'
# HTTP; sem ele, https://localhost aceitando so' o certificado da instalacao, pelo thumbprint (comum_tls.ps1).
# Com o certificado ausente no modo HTTPS o deploy nao comeca: o watchdog nem e' pausado e nada muda.
function TlsDaTarefa {
    $argumentosTarefa = $argumentosDaTarefa
    return (-not ($argumentosTarefa -match "-SemTls\b"))
}
$comTls = TlsDaTarefa
. (Join-Path $PSScriptRoot "comum_tls.ps1")
$certificado = Join-Path $Raiz "segredos\tls\cert.pem"
if ($comTls) {
    $urlSaude = "https://localhost:$Porta/api/health"
    if (-not (Test-Path -LiteralPath $certificado)) {
        throw "certificado do HTTPS nao encontrado em $certificado (tarefa sem -SemTls); nada foi alterado - ver docs\runbook.md (HTTP ou HTTPS)"
    }
    # Gate Sol da PR #475: sem a chave o processo novo nao sobe em HTTPS, nem o do rollback; o atual ja' a tem carregada.
    # Confere que existe e abre para leitura.
    $chaveTls = Join-Path $Raiz "segredos\tls\chave.pem"
    try { [System.IO.File]::OpenRead($chaveTls).Dispose() }
    catch { throw "chave do HTTPS ausente ou ilegivel em $chaveTls (tarefa sem -SemTls); nada foi alterado - ver docs\runbook.md (HTTP ou HTTPS)" }
    # Issue #517: chave trocada ou corrompida abre para leitura, mas o uvicorn novo (e o do rollback) nao sobe com ela.
    # O Python da venv do pinado carrega o par como o uvicorn (ssl.SSLContext + load_cert_chain); chave cifrada recebe
    # senha vazia em vez de pedir no terminal. Sem aspas duplas no codigo: o PowerShell 5.1 as estraga na linha de
    # comando. Sem redirecionar o stderr (cabecalho): o motivo sai no stdout pelo excepthook, so' em ASCII (ascii()),
    # para caminho ou mensagem do Windows com acento nao quebrar o print na pagina de codigo do console.
    $conferePar = 'import ssl,sys; sys.excepthook=lambda t,e,b: print(t.__name__, ascii(str(e))); ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(sys.argv[1], sys.argv[2], password=lambda: bytes())'
    $motivoPar = (& $py -I -c $conferePar $certificado $chaveTls) -join " "
    if ($LASTEXITCODE -ne 0) {
        throw "certificado e chave do HTTPS nao formam par ($certificado e $chaveTls; motivo: $motivoPar); nada foi alterado - ver docs\runbook.md (HTTP ou HTTPS, Chave do HTTPS recusada)"
    }
} else {
    $urlSaude = "http://localhost:$Porta/api/health"
}

# Instalacao assinada (issue #417): depois do deploy so' vale o health 200 com instalacao "autorizada" (arquivo
# assinado para esta maquina em <raiz>\segredos\instalacao.json). Modo copia (arquivo ausente, ilegivel, assinatura
# ou maquina) conta como falha e dispara o rollback. O rollback confere so' o 200: o commit anterior pode nem ter o campo.
function Saudavel([switch]$ExigirInstalacao) {
    try { $resposta = Invoke-SaudeLocal -Url $urlSaude -Certificado $certificado -TimeoutSec 12 }
    catch { return $false }
    if ($resposta.StatusCode -ne 200) { return $false }
    if (-not $ExigirInstalacao) { return $true }
    $saude = $null
    try { $saude = $resposta.Content | ConvertFrom-Json } catch { $saude = $null }
    if ($saude -and $saude.instalacao -eq "autorizada") { return $true }
    if ($saude) { $situacao = "$($saude.instalacao) (motivo: $($saude.instalacao_motivo))" } else { $situacao = "health ilegivel" }
    Write-Warning "health 200, mas a instalacao nao esta autorizada: $situacao - ver docs\runbook.md (Instalacao assinada)"
    return $false
}
# Sem fetch aqui (issue #443): o fluxo principal ja' buscou o alvo, e o rollback volta para o commit anterior, que ja'
# esta' no clone. Com a rede caida, um fetch no rollback abortava a volta e deixava o pinado no commit novo.
function Construir([string]$alvo) {
    Etapa "checkout $alvo"
    & git -C $AppDir checkout --quiet --detach $alvo
    if ($LASTEXITCODE -ne 0) { throw "git checkout $alvo falhou (diretorio pinado sujo?)" }
    $script:buildComecou = $true   # daqui em diante pip/npm mexem na venv e no dist (issue #443)
    Reconstruir
}
function Reconstruir {
    Etapa "pip install (requirements.lock)"
    & $py -m pip install --quiet --disable-pip-version-check -r $lock
    if ($LASTEXITCODE -ne 0) { throw "pip install do requirements.lock falhou" }
    if (-not $SemFrontend) {
        Push-Location (Join-Path $AppDir "frontend")
        try {
            Etapa "npm ci"
            & npm ci --silent; if ($LASTEXITCODE -ne 0) { throw "npm ci falhou" }
            Etapa "npm run build"
            & npm run build;   if ($LASTEXITCODE -ne 0) { throw "npm run build falhou" }
        } finally { Pop-Location }
    } else {
        Etapa "npm: pulado (-SemFrontend)"
    }
}
# Issue #417: antes de parar a producao, o codigo NOVO (ja' no pinado, depois do build) confere o arquivo da
# instalacao. Sem "autorizada" o deploy para aqui: as migracoes so' rodam na subida, entao o banco nao e' migrado e o
# processo no ar nao e' trocado; o catch do Construir volta o pinado para o commit anterior.
function ConferirInstalacao {
    Push-Location (Join-Path $AppDir "backend")
    try { & $py -m app.cli instalacao verificar --arquivo $instalacaoArquivo }
    finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "instalacao nao autorizada para o commit novo - ver docs\runbook.md (Instalacao assinada)" }
}
# Issue #421: registro do que foi implantado (commit e manifesto do dist) em <raiz>\deploy-atual.json, que o servidor
# confere de hora em hora. Gravado ANTES de reiniciar, para a conferencia da subida ja' achar o registro novo; falha
# aqui so' avisa (o item "Sem registro do ultimo deploy" aparece na Saude).
function RegistrarDeploy {
    Push-Location (Join-Path $AppDir "backend")
    $codigo = 1
    try { & $py -m app.cli integridade registrar --raiz $Raiz; $codigo = $LASTEXITCODE }
    catch { Write-Warning "registro do deploy: $($_.Exception.Message)" }
    finally { Pop-Location }
    if ($codigo -ne 0) { Write-Warning "registro do deploy (deploy-atual.json) nao gravado - ver docs\runbook.md (Saude)" }
}
function DonoDaPorta {
    $c = Get-NetTCPConnection -LocalPort $Porta -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $c) { return $null }
    return Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"
}
# Servidor ORFAO do Agendador (incidente de 2026-09-21): parar a tarefa nao o mata, ele
# segura a porta, a instancia nova morre com WinError 10048 e o health 200 que se ve e' o
# do processo ANTIGO. Por isso: quem sobrar na porta depois do Stop e' morto aqui -- so' se
# for o uvicorn da dashboard; qualquer outro dono da porta aborta o deploy.
function LiberarPorta {
    $dono = DonoDaPorta
    if (-not $dono) { return }
    if ($dono.CommandLine -notmatch "uvicorn" -or $dono.CommandLine -notmatch "app\.main") {
        throw "porta $Porta ocupada por processo que nao e' a dashboard (PID $($dono.ProcessId): $($dono.Name)); nada foi morto"
    }
    Write-Warning "servidor orfao na porta $Porta (PID $($dono.ProcessId), criado em $($dono.CreationDate)) -> encerrando"
    Stop-Process -Id $dono.ProcessId -Force
    Start-Sleep -Seconds 3
    if (DonoDaPorta) { throw "porta $Porta continua ocupada depois de encerrar o PID $($dono.ProcessId)" }
}
# Para e inicia a tarefa por schtasks /End e /Run. Estouro de tempo lanca uma excecao com a
# mensagem propria, que o fluxo principal trata voltando o pinado. /End que falha (tarefa
# ja' parada, instancia orfa) so' avisa: quem decide e' o estado conferido em PararComprovado e o LiberarPorta.
# /Run que falha e' fatal.
function ComandoTarefa([string]$verbo, [bool]$fatal) {
    $r = Agendar @("/$verbo", "/TN", $tarefaNome)
    # Texto proprio, sem o "$msgAgendador" de antes do checkout: aqui a producao pode ter mudado.
    if ($r.Estourou) {
        # schtasks que nem morto morreu ainda pode concluir o /End ou /Run depois: o watchdog fica pausado
        if ($r.FilhoVivo) { $script:manterSentinela = $true; $script:schtasksPreso = $true; throw "agendador de tarefas nao respondeu ao schtasks /$verbo (mais de $LimiteAgendador s) e o processo do schtasks nao morreu" }
        throw "agendador de tarefas nao respondeu ao schtasks /$verbo (mais de $LimiteAgendador s)"
    }
    if ($r.Codigo -ne 0) {
        $texto = "schtasks /$verbo $tarefaNome falhou (codigo $($r.Codigo)): $($r.Saida)"
        if ($fatal) { throw $texto }
        Write-Warning $texto
    }
}
# Parada COMPROVADA (gate Sol da PR #389): "parada solicitada" ($script:tarefaParada, marcada ANTES do /End, porque um
# /End cujo cliente estourou pode ter parado a tarefa) nao basta. Depois do /End o estado e' lido pela COM
# (EstadoDaTarefa) ate' "Ready" ou "Disabled" (Running e Queued sao ativas; ilegivel nao prova nada) e a porta e'
# liberada (LiberarPorta lanca se a dashboard continua nela). Qualquer falha lanca: quem chama nao mexe no pinado.
function PararComprovado([string]$momento) {
    Etapa "${momento}: parando a tarefa $tarefaNome"
    $script:tarefaParada = $true
    $script:producaoMexida = $true
    ComandoTarefa "End" $false
    $estado = "desconhecido"
    foreach ($tentativa in 1..10) {
        Start-Sleep -Seconds 1
        $estado = EstadoDaTarefa $tarefaNome $LimiteAgendador
        if ((TarefaParada $estado) -or $estado -eq "desconhecido") { break }
    }
    if (-not (TarefaParada $estado)) { throw "tarefa $tarefaNome nao comprovadamente parada (estado: $estado)" }
    Start-Sleep -Seconds 2
    LiberarPorta
}
function Reiniciar {
    PararComprovado "reinicio"
    $script:reinicioEm = Get-Date
    Etapa "reinicio: iniciando a tarefa $tarefaNome"
    ComandoTarefa "Run" $true
    $script:tarefaParada = $false
    Start-Sleep -Seconds 15
}
# Saude so' vale se quem responde NASCEU depois do reinicio: health 200 de processo antigo
# nao prova que o commit novo esta' no ar.
function SaudavelENovo([switch]$ExigirInstalacao) {
    Etapa "saude: conferindo $urlSaude"
    if (-not (Saudavel -ExigirInstalacao:$ExigirInstalacao)) { return $false }
    # Consulta da porta que lanca (WMI/CIM travado, o modo de falha da issue #386) nao prova o processo novo: conta
    # como "nao saudavel" e cai no rollback, em vez de escapar e soltar o watchdog sem nada provado (gate Sol da PR #389)
    try { $dono = DonoDaPorta }
    catch {
        Write-Warning "health 200, mas a consulta do dono da porta $Porta falhou: $($_.Exception.Message)"
        return $false
    }
    if (-not $dono -or $dono.CreationDate -lt $script:reinicioEm) {
        Write-Warning "health 200, mas o dono da porta $Porta e' anterior ao reinicio (PID $($dono.ProcessId), $($dono.CreationDate))"
        return $false
    }
    return $true
}
# Quem esta' na porta, para a linha final; a consulta passa pelo WMI (sem tempo limite), por isso
# fica protegida e so' roda depois de qualquer tentativa de religar.
function DiagnosticoPorta {
    try {
        $dono = DonoDaPorta
        if ($dono) { return "na porta $Porta esta' o PID $($dono.ProcessId), criado em $($dono.CreationDate)" }
        return "ninguem escuta na porta $Porta"
    } catch { return "nao foi possivel consultar a porta $Porta ($($_.Exception.Message))" }
}
# Volta o diretorio pinado para $anterior sem fetch (a rede pode ser a causa) e so' reconstroi
# se o HEAD saiu de $anterior: se a falha foi no fetch/checkout do alvo, o HEAD nunca saiu e o
# build nao e' refeito (npm/vite esvaziariam o dist servido com a producao no ar).
function VoltarPinado([string]$anterior) {
    $atual = (& git -C $AppDir rev-parse HEAD).Trim()
    if ($atual -ne $anterior) {
        Etapa "voltando o diretorio pinado para $anterior"
        & git -C $AppDir checkout --quiet --detach $anterior
        if ($LASTEXITCODE -ne 0) { throw "git checkout $anterior falhou" }
        Reconstruir
        RegistrarDeploy
    }
}
# Issue #478: troca de um commit com a #456 (ponto da sentinela na tabela sentinela_ponto, migracao 063) por um
# anterior a ela, que le e grava o ponto so' na auditoria: no rollback por saude e no deploy com -Ref de um commit
# antigo. Com o servico parado e o codigo com a #456 ainda no pinado (antes do checkout do antigo), o app.cli grava o
# ponto na auditoria e tira a tabela, os gatilhos e a linha da 063; sem isso o codigo antigo acusaria "Estado da
# sentinela apagado" e repetiria os achados desde o deploy da #456. Falha do app.cli so' avisa: a troca segue. Parada
# nao comprovada lanca (PararComprovado).
# $script:sentinelaParou diz se o servico foi parado aqui (o catch do build religa o commit anterior).
$script:sentinelaParou = $false
function SentinelaAntesDa456([string]$de, [string]$para) {
    $temNovo = & git -C $AppDir ls-tree --name-only $de -- backend/migrations/063_sentinela_ponto.sql
    if ($LASTEXITCODE -ne 0) { Write-Warning "git ls-tree $de falhou; ponto da sentinela nao conferido"; return }
    $temAnterior = & git -C $AppDir ls-tree --name-only $para -- backend/migrations/063_sentinela_ponto.sql
    if ($LASTEXITCODE -ne 0) { Write-Warning "git ls-tree $para falhou; ponto da sentinela nao conferido"; return }
    if (-not $temNovo -or $temAnterior) { return }
    # A parada tem de ser comprovada (gate Sol da PR #389): se nao for, PararComprovado lanca e a excecao SOBE, para
    # quem chama nao fazer checkout nem build com a instancia viva. So' a falha do app.cli e' que so' avisa.
    PararComprovado "ponto da sentinela"
    $script:sentinelaParou = $true
    $codigo = 1
    Push-Location (Join-Path $AppDir "backend")
    try { & $py -m app.cli sentinela antes-da-456 --banco $banco; $codigo = $LASTEXITCODE }
    catch { Write-Warning "ponto da sentinela: $($_.Exception.Message)" }
    finally { Pop-Location }
    if ($codigo -ne 0) {
        Write-Warning "ponto da sentinela NAO passado para a auditoria antes do rollback - ver docs\runbook.md (Rollback para um commit anterior a issue #456)"
    }
}
# Depois do ROLLBACK OK: o commit anterior pode ja' conferir a instalacao (issue #417) e ter voltado em modo copia, sem
# envio de e-mail e sem RM. Commit anterior ao #417 nao tem o campo e nao avisa.
function AvisarSeCopia {
    try { $saude = (Invoke-SaudeLocal -Url $urlSaude -Certificado $certificado -TimeoutSec 12).Content | ConvertFrom-Json }
    catch { return }
    if ($saude.instalacao -and $saude.instalacao -ne "autorizada") {
        Write-Warning "producao de volta, mas em modo copia: instalacao $($saude.instalacao) (motivo: $($saude.instalacao_motivo)), sem envio de e-mail e sem RM - ver docs\runbook.md (Instalacao assinada)"
    }
}
# Issue #443 (rodada 2 da PR #475): a producao so' esta' PROVADA com o health 200 cujo `commit` (7 caracteres, lido pelo
# servidor na subida, issue #421) e' o commit esperado. Qualquer processo responde 200; sem o campo (commit anterior a
# #421) nada esta' provado.
function CommitDoHealth {
    try { $resposta = Invoke-SaudeLocal -Url $urlSaude -Certificado $certificado -TimeoutSec 12 }
    catch { return $null }
    if ($resposta.StatusCode -ne 200) { return $null }
    $saude = $null
    try { $saude = $resposta.Content | ConvertFrom-Json } catch { $saude = $null }
    if ($saude -and $saude.commit) { return [string]$saude.commit }
    return $null
}
function NoArEm([string]$commit) {
    $curto = "$commit"
    if ($curto.Length -gt 7) { $curto = $curto.Substring(0, 7) }
    $visto = CommitDoHealth
    if ($visto -and $curto.Length -eq 7 -and $visto -eq $curto) { return $true }
    if (-not $visto) { $visto = "health sem 200 ou sem o campo commit" }
    Write-Warning "o health nao prova o commit $curto no ar (visto: $visto)"
    return $false
}
function PinadoLimpo {
    $alterados = & git -C $AppDir status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0) { return $false }
    return (-not $alterados)
}

$anterior = (& git -C $AppDir rev-parse HEAD).Trim()
# Sentinela do watchdog (issue #443, runbook "Subir e derrubar"): o finally so' o apaga com $soltarWatchdog, que vale
# $true so' com a producao provada: no aborto antes do checkout se ela estava provada no inicio (nada mudou no disco),
# na volta do build com a arvore limpa e o health no commit anterior, no DEPLOY OK (health no commit novo) e no
# ROLLBACK OK (health no anterior). Qualquer outra saida, inclusive excecao, deixa o watchdog pausado.
# Remescla da PR #389 (issue #386) com a #475: uma variavel so' de prova, $producaoProvada, com a regra mais estrita das
# duas: no inicio, pinado limpo, health no commit do pinado e nenhum sentinela de execucao anterior; depois de qualquer
# parada (PararComprovado), so' health 200 de processo NOVO (SaudavelENovo) no commit esperado (NoArEm). O finally so'
# solta o watchdog com $soltarWatchdog E $producaoProvada, e nunca com $manterSentinela (caminhos de "intervir a mao" e
# schtasks que nao morreu) ou com uma parada ($producaoMexida) sem prova depois.
$script:soltarWatchdog = $false
$script:manterSentinela = $false
$script:schtasksPreso = $false   # schtasks que estourou e nem morto morreu (ComandoTarefa): o /End ou /Run ainda pode concluir
$script:producaoMexida = $false
$script:buildComecou = $false
$script:sentinelaPreso = $false
$script:pinadoMudou = $false
# Conferencia do inicio, antes de criar o sentinela: pinado limpo e o health no commit do pinado. Sem ela, um aborto
# antes do checkout (rede caida no fetch, por exemplo, numa nova tentativa depois de ROLLBACK TAMBEM FALHOU) soltaria o
# watchdog sobre uma producao que ja' estava quebrada.
# Rodada extra da PR #475: sentinela que ja' existia ANTES desta execucao e' de uma execucao anterior que nao terminou
# provada (MANTIDO, chamada que caiu) ou de uma recuperacao a mao. O processo antigo pode responder 200 no commit
# anterior com a venv ou o dist pela metade no disco (volta do build que falhou), entao o health nao prova nada: a
# producao nao conta como provada e esta execucao so' apaga o sentinela depois de reconstruir e provar.
$script:sentinelaJaExistia = Test-Path $pause
$script:producaoProvada = $false
if ($script:sentinelaJaExistia) {
    Write-Warning "sentinela $pause ja' existia antes deste deploy (execucao anterior que nao terminou provada?): a producao nao conta como conferida no inicio; o sentinela so' sai depois de reconstruir e provar"
} elseif (PinadoLimpo) { $script:producaoProvada = NoArEm $anterior }
# Gate Sol, rodada extra: a execucao anterior pode ter caido no Vite com o dist pela metade; -SemFrontend nao o refaria
# e o health 200 no commit certo nao ve a tela sem JS. Com sentinela anterior, o frontend e' sempre reconstruido.
if ($script:sentinelaJaExistia -and $SemFrontend) {
    Write-Warning "-SemFrontend ignorado: com o sentinela de uma execucao anterior o frontend e' sempre reconstruido"
    $SemFrontend = $false
}
if ($script:producaoProvada) { Write-Host "producao conferida no inicio: commit $($anterior.Substring(0, 7)) no ar, diretorio pinado limpo" }
else { Write-Warning "producao NAO conferida no inicio (sentinela anterior, pinado sujo ou health sem o commit $($anterior.Substring(0, 7))): aborto antes do checkout mantem o sentinela" }
New-Item -ItemType File -Path $pause -Force | Out-Null   # segura o watchdog durante o deploy
try {
    # ate' o checkout do alvo o pinado e a producao seguem como estavam: solta so' se ela estava provada no inicio
    $script:soltarWatchdog = $script:producaoProvada
    # Pinado sujo (issue #443): o checkout recusaria sem escrever nada; aborta aqui, antes de qualquer mudanca.
    if (-not (PinadoLimpo)) {
        Write-Host "deploy abortado antes do checkout: diretorio pinado com arquivos alterados (git status --porcelain --untracked-files=no); producao segue em $anterior" -ForegroundColor Red
        exit 1
    }
    # Backup pre-migracao (issue #75): se o commit novo mexe em backend/migrations, snapshot
    # do banco de producao ANTES do checkout; se falhar, o deploy nao acontece. O rollback
    # do codigo mais abaixo NAO restaura o banco (restauracao manual pelo runbook).
    Etapa "fetch"
    & git -C $AppDir fetch --quiet
    if ($LASTEXITCODE -ne 0) { throw "git fetch falhou" }
    $alvo = (& git -C $AppDir rev-parse $Ref)
    if ($LASTEXITCODE -ne 0) { throw "git rev-parse $Ref falhou" }
    $alvo = $alvo.Trim()
    # Gate Sol da PR #476: com a tarefa em HTTPS, um alvo de antes da #425 nao sobe (o rodar_producao.ps1 dele procura a
    # chave em app\certs) e derruba o watchdog (o watchdog.ps1 dele nao conhece -Certificado). Recusar antes do backup e
    # do checkout; o marcador e' o scripts/comum_tls.ps1, que nasceu na #425. O finally solta o watchdog.
    # ls-tree (e nao cat-file -e): sem o arquivo ele so' nao imprime nada, sem stderr, que o 5.1 com Stop tornaria fatal.
    if ($comTls) {
        $marcador = & git -C $AppDir ls-tree --name-only $alvo -- scripts/comum_tls.ps1
        if ($LASTEXITCODE -ne 0) { throw "git ls-tree $alvo falhou" }
        if (-not $marcador) {
            Write-Host "deploy abortado antes do checkout: $alvo e' anterior ao HTTPS (issue #425) e a tarefa esta em HTTPS; volte para HTTP antes (runbook, Voltar atras). Producao segue em $anterior" -ForegroundColor Red
            exit 1
        }
    }
    $migracoes = & git -C $AppDir diff --name-only $anterior $alvo -- backend/migrations
    if ($LASTEXITCODE -ne 0) { throw "git diff das migracoes falhou" }
    $backup = $null
    if ($migracoes) {
        $backup = & (Join-Path $PSScriptRoot "backup_pre_migracao.ps1") -Banco $banco `
            -PastaBackups (Join-Path $Raiz "dados\backups") -Python $py -Rotulo $alvo.Substring(0, 7)
        if ($LASTEXITCODE -ne 0 -or -not $backup) {
            Write-Host "deploy abortado antes do checkout; producao segue em $anterior" -ForegroundColor Red
            exit 1
        }
        Write-Host "BACKUP PRE-MIGRACAO: $backup"
    } else {
        Write-Host "sem migracao nova; sem backup pre-migracao"
    }
    # Construir pode lancar depois do checkout (pip/npm/build): o diretorio pinado nao pode ficar
    # num commit que nao subiu (issue #78). Volta para $anterior (checkout + reconstrucao) e sai com 1.
    # A conferencia da instalacao (issue #417) entra no mesmo try: recusada, a producao nem para.
    $script:soltarWatchdog = $false  # daqui em diante o pinado muda: so' solta com a producao provada
    $script:pinadoMudou = $true
    # Issue #478: alvo de antes da #456 vindo de um commit com ela (-Ref): o ponto da sentinela passa para a auditoria
    # antes do checkout, com o comando do codigo atual e o servico parado (fica parado durante o build).
    try { SentinelaAntesDa456 $anterior $alvo }
    catch {
        # parada nao comprovada: nada de checkout. O pinado segue intocado em $anterior; tenta religar a tarefa com ele.
        # Remescla com a #475: so' solta com processo novo no commit anterior E a producao provada no inicio (sem
        # sentinela anterior); com sentinela anterior, venv ou dist podem estar pela metade e o religar nao prova nada.
        $motivo = $_.Exception.Message
        $religou = $false
        try { Reiniciar; $religou = (SaudavelENovo) -and (NoArEm $anterior) } catch { Write-Warning "religar falhou: $($_.Exception.Message)" }
        if ($religou -and $script:producaoProvada) {
            $script:soltarWatchdog = $true
            Write-Host "deploy abortado antes do checkout ($motivo); diretorio pinado intocado em $anterior e tarefa $tarefaNome religada com ele (health 200 no commit anterior, processo novo)" -ForegroundColor Red
        } elseif ($religou) {
            $script:manterSentinela = $true
            Write-Host "deploy abortado antes do checkout ($motivo); tarefa $tarefaNome religada em $anterior, mas a producao nao estava conferida no inicio (sentinela de execucao anterior, pinado sujo ou health sem o commit): rodar o deploy de novo para reconstruir e provar; sentinela do watchdog mantido" -ForegroundColor Red
        } else {
            $script:manterSentinela = $true
            Write-Host "deploy abortado antes do checkout ($motivo); diretorio pinado intocado em $anterior, mas a tarefa $tarefaNome NAO esta' comprovadamente no ar ($(DiagnosticoPorta)) - intervir a mao: schtasks /End e /Run /TN $tarefaNome quando o agendador responder, conferir /api/health; sentinela do watchdog mantido" -ForegroundColor Red
        }
        exit 1
    }
    try { Construir $alvo; ConferirInstalacao }
    catch {
        Write-Warning "Construir ou conferir a instalacao de $alvo falhou: $($_.Exception.Message) -> voltando o diretorio pinado para $anterior"
        # Sem fetch (a rede pode ser a causa). Issue #443 (gate Sol da PR #475): se o checkout do alvo terminou, o build
        # comecou e pip/npm podem ter mexido na venv e no dist, mesmo num deploy do mesmo commit: o anterior e' sempre
        # reconstruido. Se nem o checkout terminou, o build nao e' refeito (npm/vite esvaziariam o dist servido com a
        # producao no ar); um checkout pela metade aparece no git status. O watchdog so' sai com a arvore limpa em
        # $anterior e o health no commit $anterior (rodada 2: um processo de outro commit tambem responde 200).
        try {
            $atual = "$(& git -C $AppDir rev-parse HEAD)".Trim()
            if ($atual -ne $anterior) {
                & git -C $AppDir checkout --quiet --detach $anterior
                if ($LASTEXITCODE -ne 0) { throw "git checkout $anterior falhou" }
            }
            $refez = $false
            # Gate Sol, rodada extra: com o servico parado para o ponto da sentinela e a producao nao provada no inicio
            # (sentinela anterior), o anterior e' reconstruido antes de religar (sem processo no ar, o build nao
            # esvazia nada servido); senao o religamento subiria uma venv ou um dist pela metade.
            if ($atual -ne $anterior -or $script:buildComecou -or ($script:sentinelaParou -and -not $script:producaoProvada)) {
                Reconstruir
                RegistrarDeploy
                $refez = $true
            }
            if ($script:sentinelaParou) {
                # o servico foi parado para o ponto da sentinela: religa o anterior, cuja 063 reimporta o ponto
                Reiniciar
                if (-not (SaudavelENovo)) { throw "a producao parada para o ponto da sentinela nao voltou em $anterior" }
            }
            # Rodada extra da PR #475: sem reconstruir, so' solta se a producao estava provada no inicio (com sentinela
            # de execucao anterior a venv e o dist podem estar pela metade no disco, com o processo antigo no ar).
            if (-not $refez -and -not $script:producaoProvada) { throw "o anterior nao foi reconstruido e a producao nao estava conferida no inicio" }
            $alterados = & git -C $AppDir status --porcelain --untracked-files=no
            if ($LASTEXITCODE -ne 0) { throw "git status do diretorio pinado falhou" }
            if ($alterados) { throw "diretorio pinado com arquivos alterados em relacao a $anterior (checkout pela metade?)" }
            if (-not (NoArEm $anterior)) { throw "o health da producao no ar nao prova o commit $anterior depois da volta" }
            # Remescla da #389 com a #475: religado, a prova e' o processo novo (SaudavelENovo acima) no commit anterior;
            # sem religar, o processo no ar e' o do inicio e so' conta se ele estava provado la' (sem sentinela anterior).
            if ($script:sentinelaParou) { $script:producaoProvada = $true }
            if (-not $script:producaoProvada) { throw "a producao no ar nao foi religada e nao estava conferida no inicio (sentinela anterior?): nada esta' provado" }
            $script:soltarWatchdog = $true
            Write-Host "deploy abortado no build; producao segue no commit anterior ($anterior), diretorio pinado de volta nele" -ForegroundColor Red
        } catch {
            $script:manterSentinela = $true
            $onde = "$(& git -C $AppDir rev-parse HEAD)".Trim()   # sem .Trim() em $null: a linha final tem de sair
            Write-Host "deploy abortado no build E a volta para $anterior falhou ($($_.Exception.Message)) - intervir a mao: HEAD do diretorio pinado agora em $onde (esperado $anterior); sentinela do watchdog mantido" -ForegroundColor Red
        }
        exit 1
    }
    $novo = (& git -C $AppDir rev-parse HEAD).Trim()
    RegistrarDeploy
    # Agendador sem resposta no reinicio (depois do checkout): o pinado volta ao commit anterior e,
    # se a fase de parada comecou (a tarefa pode estar parada, ou no ar com o commit novo), refaz o
    # ciclo parar -> liberar porta -> iniciar com o commit anterior e so' afirma o que conferiu
    # (saude 200 de processo novo no commit anterior). Se nem isso, a producao esta' FORA, o sentinela
    # fica e a mensagem diz para religar a mao.
    # Daqui em diante o processo no ar e' trocado: a prova do inicio deixa de valer e so' volta com health 200 de
    # processo novo no commit esperado (DEPLOY OK, religar do catch abaixo ou ROLLBACK OK).
    $script:producaoProvada = $false
    try { Reiniciar }
    catch {
        $motivo = $_.Exception.Message
        Write-Warning "reinicio falhou: $motivo -> voltando o diretorio pinado para $anterior"
        try {
            if ($script:tarefaParada) {
                # O /Run que estoura no cliente pode ter iniciado a tarefa: o commit novo pode estar no ar (e ter
                # aplicado a 063). Antes de voltar o pinado, para de novo, COMPROVADAMENTE (estado Ready/Disabled e
                # porta livre), e, na troca para antes da #456, passa o ponto da sentinela para a auditoria com o codigo
                # novo, como no rollback por saude (issue #478). Sem a parada provada o pinado NAO e' tocado: checkout,
                # pip e build embaixo da instancia viva corromperiam venv e dist em uso (gate Sol da PR #389).
                $script:sentinelaParou = $false
                try {
                    SentinelaAntesDa456 $novo $anterior
                    if (-not $script:sentinelaParou) { PararComprovado "antes de voltar o pinado" }
                } catch {
                    $script:manterSentinela = $true
                    Write-Host "deploy abortado no reinicio ($motivo); a tarefa $tarefaNome nao foi comprovadamente parada ($($_.Exception.Message); $(DiagnosticoPorta)), entao o diretorio pinado NAO foi voltado e segue em $novo - intervir a mao: parar a tarefa (schtasks /End /TN $tarefaNome), conferir a porta e so' entao voltar o pinado ou rodar o deploy de novo; sentinela do watchdog mantido" -ForegroundColor Red
                    exit 1
                }
            }
            VoltarPinado $anterior
            if ($script:tarefaParada) {
                Etapa "religando a tarefa $tarefaNome com o commit anterior"
                $religou = $false
                try { Reiniciar; $religou = (SaudavelENovo) -and (NoArEm $anterior) } catch { Write-Warning "religar falhou: $($_.Exception.Message)" }
                $naPorta = DiagnosticoPorta
                if ($religou) {
                    $script:producaoProvada = $true
                    $script:soltarWatchdog = $true
                    Write-Host "deploy abortado no reinicio ($motivo); diretorio pinado de volta em $anterior e tarefa $tarefaNome religada com ele (health 200 no commit anterior, processo novo; $naPorta)" -ForegroundColor Red
                } else {
                    $script:manterSentinela = $true
                    Write-Host "deploy abortado no reinicio ($motivo); diretorio pinado de volta em $anterior, mas a tarefa $tarefaNome NAO esta' comprovadamente no ar com ele ($naPorta) - intervir a mao: schtasks /End e /Run /TN $tarefaNome quando o agendador responder, conferir /api/health; sentinela do watchdog mantido" -ForegroundColor Red
                }
            } else {
                # Remescla com a #475: o processo no ar nao foi trocado, mas o pinado foi reconstruido embaixo dele; sem
                # processo novo no commit esperado nada esta' provado e o sentinela fica.
                Write-Host "deploy abortado no reinicio ($motivo); diretorio pinado de volta em $anterior; a tarefa nao chegou a ser parada ($(DiagnosticoPorta)) - conferir /api/health a mao; sentinela do watchdog mantido" -ForegroundColor Red
            }
        } catch {
            $script:manterSentinela = $true
            $onde = "$(& git -C $AppDir rev-parse HEAD)".Trim()   # sem .Trim() em $null: a linha final tem de sair
            Write-Host "deploy abortado no reinicio ($motivo) E a volta para $anterior falhou ($($_.Exception.Message)) - intervir a mao: HEAD do diretorio pinado agora em $onde (esperado $anterior); sentinela do watchdog mantido" -ForegroundColor Red
        }
        exit 1
    }
    if ((SaudavelENovo -ExigirInstalacao) -and (NoArEm $novo)) {
        $script:producaoProvada = $true
        $fim = "DEPLOY OK: $anterior -> $novo (health 200 no commit novo, processo novo)"
        if ($backup) { $fim += " - backup pre-migracao: $backup" }
        $script:soltarWatchdog = $true
        Write-Host $fim -ForegroundColor Green
    } else {
        Write-Warning "Saude NAO voltou -> ROLLBACK para $anterior"
        # Issue #443: checkout, rebuild, reinicio e health do rollback num try proprio. Excecao em qualquer um deles
        # (checkout, pip, npm, agendador, porta) e' ROLLBACK TAMBEM FALHOU, com o sentinela mantido.
        $voltou = $false
        try {
            SentinelaAntesDa456 $novo $anterior
            Construir $anterior
            RegistrarDeploy
            Reiniciar
            $voltou = (SaudavelENovo) -and (NoArEm $anterior)
        } catch {
            $script:manterSentinela = $true
            $onde = "$(& git -C $AppDir rev-parse HEAD)".Trim()   # sem .Trim() em $null: a linha final tem de sair
            Write-Host "ROLLBACK TAMBEM FALHOU ($($_.Exception.Message)) - intervir a mao (ver watchdog.log e dashboard.log): HEAD do diretorio pinado agora em $onde (esperado $anterior); sentinela do watchdog mantido" -ForegroundColor Red
            exit 1
        }
        if ($voltou) { $script:producaoProvada = $true; $script:soltarWatchdog = $true; Write-Host "ROLLBACK OK: producao de volta em $anterior" -ForegroundColor Yellow; AvisarSeCopia }
        else {
            $script:manterSentinela = $true
            Write-Host "ROLLBACK TAMBEM FALHOU - intervir a mao (ver watchdog.log e dashboard.log); sentinela do watchdog mantido" -ForegroundColor Red
        }
        exit 1
    }
} finally {
    # Solta o watchdog so' com a producao conferida (ver $soltarWatchdog acima). Nos caminhos de "intervir a mao" o
    # pinado esta' num commit ou build que nao se provou: o watchdog nao pode reerguer sozinho; o operador apaga depois.
    # Parada sem producao comprovada depois (excecao que escapou) tambem mantem (gate Sol da PR #389).
    # Issue #443 (gate Sol da PR #475): a remocao falha visivel (ACL, arquivo travado) e e' conferida; se o sentinela
    # continuar la', a linha final diz MANTIDO e o script sai com 1, mesmo depois do DEPLOY OK.
    if ($script:producaoMexida -and -not $script:producaoProvada) { $script:manterSentinela = $true }
    if ($script:soltarWatchdog -and $script:producaoProvada -and -not $script:manterSentinela) {
        if (Test-Path $pause) {
            try { Remove-Item $pause -Force -ErrorAction Stop }
            catch { Write-Warning "nao foi possivel apagar o sentinela $pause ($($_.Exception.Message))" }
        }
        if (Test-Path $pause) {
            # producao provada: nao e' caso de desfazer nada, so' de tirar o arquivo (runbook, Subir e derrubar)
            $script:sentinelaPreso = $true
            Write-Host "sentinela $pause MANTIDO POR FALHA NA REMOCAO: a producao esta' provada; nao reconstruir nem desfazer o deploy: conferir health e commit, corrigir o bloqueio (permissao, arquivo travado) e apagar o arquivo (docs\runbook.md, Subir e derrubar)" -ForegroundColor Red
        }
    }
    elseif (-not $script:pinadoMudou -and -not $script:producaoProvada) {
        Write-Host "sentinela $pause MANTIDO: a producao nao estava conferida no inicio (sentinela de execucao anterior, pinado sujo ou health sem o commit $anterior); conferir e recuperar antes de apaga-lo (docs\runbook.md, Subir e derrubar)" -ForegroundColor Yellow
    }
    elseif ($script:schtasksPreso -and $script:soltarWatchdog -and $script:producaoProvada) {
        # revisor da remescla: religada e provada, mas o schtasks preso ainda pode concluir o /End ou /Run depois
        Write-Host "sentinela $pause MANTIDO: a producao esta' provada, mas um schtasks preso ainda pode concluir o /End ou /Run; conferir que nenhum schtasks.exe segue rodando e o health no commit esperado, e so' entao apaga-lo (docs\runbook.md, Subir e derrubar)" -ForegroundColor Yellow
    }
    else { Write-Host "sentinela $pause MANTIDO: a producao nao foi provada depois do deploy; intervir a mao e so' apaga-lo depois da recuperacao (docs\runbook.md, Subir e derrubar)" -ForegroundColor Yellow }
}
if ($script:sentinelaPreso) { exit 1 }
