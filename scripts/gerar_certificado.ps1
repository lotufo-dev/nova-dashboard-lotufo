# Gera o certificado autoassinado usado pelo HTTPS interno (rodar 1x, como administrador,
# a partir do diretório pinado: o Python do venv dele converte o .pfx em PEM).
# Saída (issue #425): <Raiz>\segredos\tls\chave.pem e cert.pem, FORA do clone e com a ACL
# de segredos (o .pfx intermediário é apagado no fim). Validade de 5 anos.
# Nomes no certificado (SAN): o nome curto da máquina (-NomeCurto, padrão DASH_SERVIDOR ou
# o nome do computador), o nome DNS completo (-NomeDns, padrão <nome>.<domínio> quando a
# máquina está no domínio), "localhost" e os IPs (-Ip, padrão os IPv4 da máquina fora de
# 127.* e 169.254.*). Conferir a lista impressa no fim antes de distribuir o cert.pem.
[CmdletBinding()]
param(
    [string]$Raiz = "C:\DashboardLotufo",
    [string]$NomeCurto = "",
    [string]$NomeDns = "",
    [string[]]$Ip = @()
)
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "comum_acl.ps1")

# $repo, nao $raiz: no PowerShell $raiz e $Raiz sao a mesma variavel.
$repo = Split-Path -Parent $PSScriptRoot
$segredos = Join-Path $Raiz "segredos"
$pasta = Join-Path $segredos "tls"

if (-not $NomeCurto) {
    if ($env:DASH_SERVIDOR) { $NomeCurto = $env:DASH_SERVIDOR } else { $NomeCurto = $env:COMPUTERNAME }
}
if (-not $NomeDns) {
    $sistema = Get-CimInstance Win32_ComputerSystem
    if ($sistema.PartOfDomain -and $sistema.Domain) { $NomeDns = "$($sistema.DNSHostName).$($sistema.Domain)" }
    else { Write-Warning "Maquina fora do dominio: sem nome DNS completo no certificado (passe -NomeDns se houver)." }
}
if ($Ip.Count -eq 0) {
    $Ip = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        ForEach-Object { $_.IPAddress })
    if ($Ip.Count -eq 0) { Write-Warning "Nenhum IPv4 encontrado: certificado sem IP (passe -Ip)." }
}
# Nome e IP entram no texto da extensao SAN ("DNS=a&IPAddress=b"): um "&" ou "=" num valor abriria outra entrada.
# So' passa nome DNS (letras, digitos, ponto e hifen) e IP que o .NET le como IP.
$nomes = @(@($NomeCurto, $NomeDns, "localhost") | Where-Object { $_ } | Select-Object -Unique)
foreach ($nome in $nomes) {
    if ($nome -notmatch '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$') { throw "Nome invalido para o certificado: '$nome'" }
}
foreach ($endereco in $Ip) {
    $lido = $null
    if (-not [System.Net.IPAddress]::TryParse($endereco, [ref]$lido)) { throw "IP invalido para o certificado: '$endereco'" }
}
$san = (@($nomes | ForEach-Object { "DNS=$_" }) + @($Ip | ForEach-Object { "IPAddress=$_" })) -join "&"

# ORDEM IMPORTA: a pasta nasce e e' TRAVADA antes de existir qualquer segredo.
# Na versao anterior o .pfx e a chave.pem eram escritos com a ACL herdada (ou seja,
# legiveis por "Usuarios" da maquina) e so depois o icacls fechava a pasta. Nessa
# janela a chave privada do TLS ficava ao alcance de qualquer conta -- e quem
# copiasse ali fica com ela para sempre, endurecer depois nao desfaz nada.
# ACL NTFS restrita (spec §5): chave.pem é a chave privada do TLS, em texto claro
# e sem senha (uvicorn precisa lê-la sozinho). Herança removida e acesso apenas
# para SYSTEM (S-1-5-18, conta do serviço) e Administradores (S-1-5-32-544), como
# o rodar_producao.ps1 faz com segredos. SIDs em vez de nomes: o Windows aqui é
# pt-BR e "Administrators" não existe. Primeiro segredos, depois segredos\tls.
foreach ($trancar in $segredos, $pasta) {
    New-Item -ItemType Directory -Force -Path $trancar | Out-Null
    & icacls $trancar /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Falha ao restringir a ACL de $trancar (rodar como administrador)." }
    # Dono tambem: quem e' dono reescreve a DACL quando quiser (WRITE_DAC implicito).
    Set-DonoAdministradores -Caminho $trancar
}
# icacls devolve 0 mesmo deixando ACE explicita de terceiro de pe -- conferir de fato.
Assert-AclSomenteSistemaEAdmins -Caminho $segredos
Assert-AclSomenteSistemaEAdmins -Caminho $pasta

$pfx     = Join-Path $pasta "dashboard.pfx"
$chave   = Join-Path $pasta "chave.pem"
$publico = Join-Path $pasta "cert.pem"

# Os arquivos novos nascem com sufixo .new e so passam por cima dos definitivos
# depois que TUDO deu certo. Antes, uma RE-execucao que falhasse no meio caia no
# catch e apagava chave.pem/cert.pem -- ou seja, destruia o par BOM da execucao
# anterior e deixava a producao sem certificado nenhum.
$chaveNova   = "$chave.new"
$publicoNovo = "$publico.new"

# E o par antigo vai para .old durante a troca. Nao existe rename atomico de DOIS
# arquivos: sem esse resguardo, uma falha ENTRE os dois Move-Item deixaria chave.pem
# nova com cert.pem velho -- par descasado (uvicorn nao sobe) e, pior, a chave boa
# anterior ja sobrescrita, irrecuperavel. Com o .old o catch desfaz a troca inteira
# e o disco termina com um par consistente: o novo ou o antigo, nunca metade de cada.
$chaveVelha   = "$chave.old"
$publicoVelho = "$publico.old"

# Senha do .pfx sorteada a cada execucao e mantida so em memoria. Antes era uma
# senha fixa escrita neste arquivo, que e' versionado: o .pfx ficava protegido
# por uma senha publicada no repositorio.
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$senhaTexto = [Convert]::ToBase64String($bytes)

$falhou = $null
$cert = $null
# Em que ponto da troca do par definitivo a execucao esta -- e' o que diz ao catch
# o que desfazer. Sem isso, um .old esquecido por uma execucao antiga voltaria por
# cima de um par bom numa falha que nem chegou perto da troca.
#   0 = nao mexeu nos definitivos   1 = guardando o par antigo em .old
#   2 = promovendo os .new          3 = troca completa
$swapEtapa = 0
# QUAL lado ESTA execucao chegou a guardar em .old. A etapa sozinha nao basta: ela e'
# a mesma para os dois arquivos, mas os Move-Item da etapa 1 sao DOIS, um de cada vez.
# Falhando entre eles, so a chave foi guardada -- e decidir o rollback por Test-Path
# do .old faria o cert.pem.old (de uma execucao antiga, ou recem-criado) voltar por
# cima de um cert.pem que nunca saiu do lugar: par bom destruido pelo proprio
# rollback. Estes flags dizem o que ESTA execucao moveu, e o catch desfaz so isso.
$guardouChave = $false
$guardouPublico = $false
try {
    # SAN pela extensao de texto (2.5.29.17): o -DnsName nao aceita IP.
    $cert = New-SelfSignedCertificate -Subject "CN=$NomeCurto" -TextExtension @("2.5.29.17={text}$san") `
        -CertStoreLocation "Cert:\LocalMachine\My" -NotAfter (Get-Date).AddYears(5)

    $senha = ConvertTo-SecureString $senhaTexto -AsPlainText -Force
    Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $senha | Out-Null

    # uvicorn precisa de PEM: extrair chave e certificado do .pfx com o Python do venv
    # (dependência só deste script: .venv\Scripts\python -m pip install cryptography).
    # A senha viaja por VARIAVEL DE AMBIENTE, nunca em argv: a linha de comando de um
    # processo e' legivel por qualquer um que liste a tabela de processos da maquina.
    $python = Join-Path $repo "backend\.venv\Scripts\python.exe"
    $env:DASH_PFX_SENHA = $senhaTexto
    & $python -c @"
import os
from cryptography.hazmat.primitives.serialization import pkcs12, Encoding, PrivateFormat, NoEncryption
senha = os.environ['DASH_PFX_SENHA'].encode()
data = open(r'$pfx', 'rb').read()
key, cert, _ = pkcs12.load_key_and_certificates(data, senha)
open(r'$chaveNova', 'wb').write(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
open(r'$publicoNovo', 'wb').write(cert.public_bytes(Encoding.PEM))
"@
    if ($LASTEXITCODE -ne 0) { throw "Falha ao converter o .pfx para PEM (cryptography instalado no venv?)" }
    if (-not (Test-Path -LiteralPath $chaveNova) -or -not (Test-Path -LiteralPath $publicoNovo)) {
        throw "A conversao nao gerou chave.pem.new e cert.pem.new."
    }

    # O .pfx ja cumpriu o papel: quem serve o HTTPS e' o uvicorn, com o par PEM.
    # Guarda-lo seria deixar uma SEGUNDA copia da chave privada parada no disco,
    # trancada por uma senha que morre com este processo (ninguem consegue abrir).
    Remove-Item -LiteralPath $pfx -Force

    # Ultimo passo, e so aqui: promover o par novo por cima do definitivo. Ordem:
    # guardar o par antigo em .old -> promover os .new -> so entao descartar os .old.
    # Qualquer erro no meio cai no catch, que devolve os .old ao lugar: o disco
    # termina ou com o par novo INTEIRO, ou com o antigo INTEIRO. Nunca metade.
    # Sobra de execucao anterior sai ANTES da troca: um .old velho parado aqui e' um
    # par PEM aposentado que nao tem nada a ver com esta execucao, e deixa-lo no disco
    # so cria armadilha para o rollback e para a mensagem final.
    foreach ($velho in $chaveVelha, $publicoVelho) {
        Remove-Item -LiteralPath $velho -Force -ErrorAction SilentlyContinue
    }

    $swapEtapa = 1
    # O flag e' ligado DEPOIS do Move-Item: se ele falhar, o catch nao tenta desfazer
    # um backup que nao existe.
    if (Test-Path -LiteralPath $chave) {
        Move-Item -LiteralPath $chave -Destination $chaveVelha -Force
        $guardouChave = $true
    }
    if (Test-Path -LiteralPath $publico) {
        Move-Item -LiteralPath $publico -Destination $publicoVelho -Force
        $guardouPublico = $true
    }

    $swapEtapa = 2
    Move-Item -LiteralPath $chaveNova   -Destination $chave   -Force
    Move-Item -LiteralPath $publicoNovo -Destination $publico -Force
    $swapEtapa = 3   # par novo completo no lugar: nao ha mais o que desfazer

    # O par antigo cumpriu o papel de rede de seguranca: chave privada velha nao
    # fica parada no disco. Melhor esforco (-EA SilentlyContinue) de proposito --
    # um erro AQUI nao pode disparar o rollback e derrubar uma geracao que deu certo;
    # um .old que sobre e' sobrescrito pela proxima execucao (Move-Item -Force).
    foreach ($velho in $chaveVelha, $publicoVelho) {
        Remove-Item -LiteralPath $velho -Force -ErrorAction SilentlyContinue
    }
}
catch {
    $falhou = $_
    # Falha depois que material sensivel ja existe: nao deixar meio-termo no disco
    # (.pfx orfao, ou par PEM incompleto que faria o uvicorn subir com credencial
    # errada). Os intermediarios desta execucao saem primeiro.
    foreach ($sobra in $pfx, $chaveNova, $publicoNovo) {
        Remove-Item -LiteralPath $sobra -Force -ErrorAction SilentlyContinue
    }
    # Troca interrompida: desfazer, para o disco nao ficar com chave nova + cert velho.
    # A decisao e' por LADO, e pelo que ESTA execucao guardou ($guardou*) -- nunca por
    # Test-Path do .old, que nao distingue backup desta execucao de sobra de outra.
    #   guardou -> devolve o .old ao definitivo (e o .old deixa de existir).
    #   nao guardou, etapa 2 -> aquele lado nao tinha par anterior, logo o que estiver
    #     no definitivo e' o arquivo promovido AGORA: sai, para nao ficar meio par novo.
    #   nao guardou, etapa 1 -> aquele lado nunca foi tocado; o definitivo que esta la
    #     e' o ANTIGO, intacto. Nao encostar.
    # -EA SilentlyContinue porque ja estamos tratando um erro; o que de fato sobrou e'
    # conferido na mensagem final, que nao promete o que nao fez.
    if ($swapEtapa -eq 1 -or $swapEtapa -eq 2) {
        if ($guardouChave) {
            Move-Item -LiteralPath $chaveVelha -Destination $chave -Force -ErrorAction SilentlyContinue
        }
        elseif ($swapEtapa -eq 2) { Remove-Item -LiteralPath $chave -Force -ErrorAction SilentlyContinue }

        if ($guardouPublico) {
            Move-Item -LiteralPath $publicoVelho -Destination $publico -Force -ErrorAction SilentlyContinue
        }
        elseif ($swapEtapa -eq 2) { Remove-Item -LiteralPath $publico -Force -ErrorAction SilentlyContinue }
    }
}
finally {
    # A senha nao pode sobreviver ao script em lugar nenhum.
    Remove-Item -Path "Env:DASH_PFX_SENHA" -ErrorAction SilentlyContinue
    if ($null -ne $bytes) { [Array]::Clear($bytes, 0, $bytes.Length) }
    $senhaTexto = $null
    $senha = $null
}

if ($null -ne $falhou) {
    # Observacao: o certificado pode ter ficado em Cert:\LocalMachine\My. A chave
    # privada la e' protegida pela ACL do proprio store (SYSTEM/Administradores);
    # remova-o a mao se quiser, com o thumbprint mostrado por Get-ChildItem Cert:\LocalMachine\My.
    Write-Host ("ERRO ao gerar o certificado: " + $falhou.Exception.Message) -ForegroundColor Red
    # A mensagem descreve o que EXISTE no disco, nao o que era para existir: se o
    # rollback nao conseguiu devolver os .old, dizer "preservado" seria mentira e o
    # operador subiria a producao com um par descasado achando que estava tudo bem.
    # So contam os .old que ESTA execucao criou ($guardou*): um .old de outra execucao
    # nao diz nada sobre o par atual, e alarmar por ele mandaria o operador renomear
    # material aposentado por cima de um par bom -- exatamente o que se quer evitar.
    $sobraram = @()
    if ($guardouChave   -and (Test-Path -LiteralPath $chaveVelha))   { $sobraram += $chaveVelha }
    if ($guardouPublico -and (Test-Path -LiteralPath $publicoVelho)) { $sobraram += $publicoVelho }
    if ($sobraram.Count -gt 0) {
        Write-Host "ATENCAO: sobraram arquivos '.old' em $pasta -- o par PEM anterior nao voltou sozinho:" -ForegroundColor Red
        foreach ($sobra in $sobraram) { Write-Host "  $sobra" -ForegroundColor Red }
        Write-Host "Confira chave.pem/cert.pem e, se nao formarem um par, renomeie os '.old' de volta (tirando o sufixo) antes de subir a producao." -ForegroundColor Red
    }
    else {
        Write-Host "Nenhum arquivo parcial ficou em $pasta; o par PEM anterior (se havia) segue intacto." -ForegroundColor Red
    }
    exit 1
}

Write-Host "Certificado gerado em $pasta (cert.pem e chave.pem), com ACL restrita a SYSTEM e Administradores."
# O que conferir antes de distribuir o cert.pem: os nomes com que a operacao abre a dashboard e a validade.
Write-Host "Nomes no certificado: $($san -replace '&', ', ')"
Write-Host "Thumbprint: $($cert.Thumbprint)  (o watchdog, o deploy e o saude_local.ps1 aceitam so' este)"
Write-Host "Valido ate: $($cert.NotAfter.ToString('dd/MM/yyyy'))"
