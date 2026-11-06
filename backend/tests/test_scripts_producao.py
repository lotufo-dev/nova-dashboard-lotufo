# Os scripts de producao (scripts\*.ps1) rodam so no servidor Windows; aqui eles sao lidos como texto, no estilo
# de test_producao_nao_aceita_x_forwarded_for em test_auth.py (que segue cobrindo o --no-proxy-headers).
# Issue #361 (porta configuravel nos scripts de producao): a VM nova tem a 80 ocupada pelo IIS, entao a porta
# vem do parametro -Porta, e o padrao continua 80.
import pathlib
import re

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"


def _ler(nome):
    return (SCRIPTS / nome).read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("nome", ["rodar_producao.ps1", "instalar_autostart.ps1", "instalar_watchdog.ps1", "deploy.ps1"])
def test_script_declara_o_parametro_porta_com_faixa(nome):
    script = _ler(nome)
    assert re.search(r"\[int\]\$Porta\s*=\s*\d+", script), f"{nome} sem [int]$Porta no param()"
    assert re.search(r"\[ValidateRange\([01], 65535\)\]\s*\[int\]\$Porta", script), f"{nome} sem ValidateRange na porta"


def test_rodar_producao_usa_a_porta_do_parametro():
    script = _ler("rodar_producao.ps1")
    comandos = [linha for linha in script.splitlines() if "-m uvicorn" in linha]
    assert len(comandos) == 2
    assert "--port 80" not in script and "--port 8443" not in script
    assert script.count("--port $Porta") == 2
    # sem -Porta nada muda: 80 em HTTP (-SemTls) e 8443 com TLS
    assert "[int]$Porta = 0" in script
    assert "$Porta = 80" in script and "$Porta = 8443" in script


def test_autostart_repassa_a_porta_so_quando_informada():
    script = _ler("instalar_autostart.ps1")
    assert "[int]$Porta = 0" in script
    linha = next(linha for linha in script.splitlines() if "-Porta $Porta" in linha)
    assert "$Porta -ne 0" in linha and "$argumentos +=" in linha


def test_watchdog_e_instalado_com_a_url_da_porta():
    script = _ler("instalar_watchdog.ps1")
    # issue #425: padrao do modo, como nos outros scripts (80 com -SemTls, 8443 com TLS)
    assert "[int]$Porta = 0" in script
    assert "$Porta = 80" in script and "$Porta = 8443" in script
    assert '$url = "http://localhost:$Porta/api/health"' in script
    assert '$url = "https://localhost:$Porta/api/health"' in script
    montagens = [linha for linha in script.splitlines() if "$argumentos =" in linha]
    assert len(montagens) == 2 and all('-Url "{1}"' in linha and "$script, $url" in linha for linha in montagens)
    assert "New-ScheduledTaskAction -Execute \"powershell.exe\" -Argument $argumentos" in script
    # o watchdog.ps1 precisa aceitar -Url, senao o argumento cai no chao
    assert re.search(r"\[string\]\$Url\s*=", _ler("watchdog.ps1"))


def test_deploy_usa_a_porta_na_saude_no_dono_da_porta_e_nas_mensagens():
    script = _ler("deploy.ps1")
    assert "localhost/api/health" not in script
    assert '"http://localhost:$Porta/api/health"' in script and '"https://localhost:$Porta/api/health"' in script
    assert "LocalPort 80" not in script
    assert "-LocalPort $Porta" in script
    assert not re.search(r"porta 80\b", script), "mensagem ainda cita a porta 80 fixa"


def test_deploy_le_a_porta_da_tarefa_agendada():
    # revisor-adversarial: deploy na 80 com a tarefa na 8080 acharia o IIS como dono da porta e abortaria
    # depois do checkout, sem rollback. A porta vem da tarefa; -Porta diferente dela aborta antes.
    script = _ler("deploy.ps1")
    assert "[int]$Porta = 0" in script
    assert 'Get-ScheduledTask -TaskName "DashboardLotufo"' in script
    assert re.search(r'-match "-Porta \(\\d\+\)"', script)
    # tarefa sem -Porta = padrao do modo do rodar_producao.ps1 (issue #425, /code-review): 80 com -SemTls, 8443 com TLS
    funcao = script[script.index("function PortaDaTarefa"):script.index("$portaTarefa = PortaDaTarefa")]
    assert 'if ($argumentosTarefa -match "-SemTls\\b") { return 80 }' in funcao
    assert funcao.rstrip().endswith("return 8443\n}")
    assert "nao bate com a tarefa DashboardLotufo" in script
    # a conferencia vem antes de qualquer git checkout
    assert script.index("$portaTarefa = PortaDaTarefa") < script.index("function Construir")


def test_deploy_faz_rollback_quando_a_instalacao_nao_e_autorizada():
    # Issue #417: health 200 com `instalacao` diferente de "autorizada" depois do deploy conta como falha e cai no
    # rollback que ja' existe. O rollback confere so' o 200: o commit anterior pode nem ter o campo.
    script = _ler("deploy.ps1")
    corpo = script[script.index("function Saudavel"):script.index("function Construir")]
    assert "ConvertFrom-Json" in corpo
    assert re.search(r'\.instalacao -eq "autorizada"', corpo)
    assert "[switch]$ExigirInstalacao" in corpo
    assert script.count("SaudavelENovo -ExigirInstalacao") == 1
    deploy = script.index("if (SaudavelENovo -ExigirInstalacao) {")
    rollback = script.index("ROLLBACK para $anterior")
    assert deploy < rollback
    assert "if (SaudavelENovo) {" in script[rollback:]
    # rollback para um commit que ja' confere a instalacao e voltou em modo copia: ROLLBACK OK, mas com aviso
    aviso = script[script.index("function AvisarSeCopia"):script.index("$anterior = (")]
    assert '$saude.instalacao -and $saude.instalacao -ne "autorizada"' in aviso and "Write-Warning" in aviso
    linha_ok = next(linha for linha in script[rollback:].splitlines() if "ROLLBACK OK" in linha)
    assert linha_ok.rstrip().endswith("AvisarSeCopia }")
    # o Saudavel antigo (so' o status) nao pode ter sobrado em outro lugar
    assert script.count("function Saudavel") == 2      # Saudavel e SaudavelENovo
    # SaudavelENovo repassa a exigencia: sem o parametro o PowerShell 5.1 poria -ExigirInstalacao em $args, sem erro,
    # e o deploy voltaria a aceitar so' o 200 (revisor-adversarial da PR #437, ao juntar com a #389)
    novo = script[script.index("function SaudavelENovo"):script.index("function AvisarSeCopia")]
    assert novo.startswith("function SaudavelENovo([switch]$ExigirInstalacao) {")
    assert "Saudavel -ExigirInstalacao:$ExigirInstalacao" in novo


def test_deploy_confere_a_instalacao_antes_de_parar_a_producao():
    # Issue #417 (gate Sol da PR #437): as migracoes rodam na subida, entao a conferencia do codigo novo vem depois do
    # build e ANTES de parar a tarefa; recusada, cai no catch do Construir, que volta o pinado sem reiniciar nada.
    script = _ler("deploy.ps1")
    assert '$instalacaoArquivo = Join-Path $Raiz "segredos\\instalacao.json"' in script
    funcao = script[script.index("function ConferirInstalacao"):script.index("function DonoDaPorta")]
    assert "& $py -m app.cli instalacao verificar --arquivo $instalacaoArquivo" in funcao
    assert 'Push-Location (Join-Path $AppDir "backend")' in funcao
    assert re.search(r"if \(\$LASTEXITCODE -ne 0\) \{ throw ", funcao)
    chamada = script.index("try { Construir $alvo; ConferirInstalacao }")
    assert chamada < script.index("    Reiniciar\n") and chamada < script.index("SaudavelENovo -ExigirInstalacao")
    # o rollback (Construir $anterior) nao confere: o commit anterior pode nem ter o comando
    assert script.count("ConferirInstalacao") == 2      # a definicao e a chamada do deploy


def _regex_da_raiz(script):
    """O padrao do `-match` de RaizDaTarefa, para rodar aqui contra o formato que o instalar_autostart.ps1 grava."""
    funcao = script[script.index("function RaizDaTarefa"):script.index("$raizTarefa = RaizDaTarefa")]
    return re.search(r"-match '([^']+)'", funcao).group(1)


def _raiz(regex, argumentos):
    m = re.search(regex, argumentos)
    return (m.group(1) or m.group(2)) if m else "C:\\DashboardLotufo"


def test_deploy_le_a_raiz_da_tarefa_e_dela_tira_instalacao_e_banco():
    # Gate Sol da PR #437: a tarefa aceita -Raiz; com a producao em outro disco, conferir C:\ recusaria o arquivo valido
    # ou aceitaria um velho enquanto o servidor confere o da raiz certa. A raiz vem da tarefa, como a porta.
    script = _ler("deploy.ps1")
    assert '[string]$Raiz = ""' in script
    funcao = script[script.index("function RaizDaTarefa"):script.index("$raizTarefa = RaizDaTarefa")]
    assert 'Get-ScheduledTask -TaskName "DashboardLotufo"' in funcao
    assert 'return "C:\\DashboardLotufo"' in funcao        # tarefa sem -Raiz = padrao do rodar_producao.ps1
    assert "nao bate com a tarefa DashboardLotufo (raiz $raizTarefa)" in script
    assert script.index("$raizTarefa = RaizDaTarefa") < script.index("function Construir")   # antes do checkout
    # o formato que o instalar_autostart.ps1 grava (e o que alguem escreva a mao, sem aspas) da' a raiz certa
    autostart = _ler("instalar_autostart.ps1")
    assert '-Raiz `"$Raiz`"' in autostart
    regex = _regex_da_raiz(script)
    assert _raiz(regex, '-NoProfile -File "C:\\x\\rodar_producao.ps1" -Raiz "D:\\Dados Lotufo" -SemTls') == \
        "D:\\Dados Lotufo"
    assert _raiz(regex, '-File rodar_producao.ps1 -Raiz D:\\Lotufo -Porta 8080') == "D:\\Lotufo"
    assert _raiz(regex, '-File rodar_producao.ps1 -SemTls -Porta 8080') == "C:\\DashboardLotufo"
    # dela saem o arquivo da instalacao e o banco do backup pre-migracao; nada fixo em C:\ sobrou para eles
    assert '$instalacaoArquivo = Join-Path $Raiz "segredos\\instalacao.json"' in script
    assert '$banco = Join-Path $Raiz "dados\\dashboard.db"' in script
    assert "-Banco $banco" in script and '-PastaBackups (Join-Path $Raiz "dados\\backups")' in script
    codigo ="\n".join(linha.split("#")[0] for linha in script.splitlines())
    assert "C:\\DashboardLotufo\\segredos" not in codigo and "C:\\DashboardLotufo\\dados" not in codigo
    assert script.index("$instalacaoArquivo = Join-Path") < script.index("function Construir")


def test_rodar_producao_fixa_o_arquivo_da_instalacao_na_raiz():
    # Gate Sol da PR #437: uma DASH_INSTALACAO_ARQUIVO herdada apontaria para outro arquivo (falso modo copia e rollback)
    script = _ler("rodar_producao.ps1")
    linha = '$env:DASH_INSTALACAO_ARQUIVO = Join-Path $Raiz "segredos\\instalacao.json"'
    assert script.count(linha) == 1
    assert script.index(linha) < script.index("-m uvicorn")


def test_deploy_fica_so_em_ascii_sem_bom():
    # cabecalho do deploy.ps1: o PowerShell 5.1 le sem BOM como ANSI e acento quebra o parse
    bruto = (SCRIPTS / "deploy.ps1").read_bytes()
    assert not bruto.startswith(b"\xef\xbb\xbf")
    assert bruto.isascii()


# --- Issue #425: producao em HTTPS --------------------------------------------------------------------------------
# Certificado em <raiz>\segredos\tls (fora do clone), emitido para o nome curto, o nome DNS completo e o IP; quem confere
# a saude na propria maquina (watchdog, deploy, saude_local) fala HTTPS com localhost e aceita so' o certificado da
# propria instalacao, pelo thumbprint.

def _codigo(script):
    """O script sem os comentarios de linha: o que importa e' o que roda, nao o que o comentario conta."""
    return "\n".join(linha.split("#")[0] for linha in script.splitlines())


def test_certificado_sai_em_segredos_tls_fora_do_clone():
    script = _ler("gerar_certificado.ps1")
    assert '[string]$Raiz = "C:\\DashboardLotufo"' in script
    assert '$segredos = Join-Path $Raiz "segredos"' in script
    assert '$pasta = Join-Path $segredos "tls"' in script
    assert '"certs"' not in _codigo(script)
    # $raiz e $Raiz sao a MESMA variavel no PowerShell: o clone nao pode mais se chamar $raiz
    assert "$raiz =" not in script
    # a pasta (e a de segredos) e' travada e conferida ANTES de existir qualquer segredo
    gerar = script.index("New-SelfSignedCertificate")
    assert script.index("Assert-AclSomenteSistemaEAdmins -Caminho $segredos") < gerar
    assert script.index("Assert-AclSomenteSistemaEAdmins -Caminho $pasta") < gerar


def test_certificado_tem_nome_curto_nome_dns_e_ip_por_5_anos():
    script = _ler("gerar_certificado.ps1")
    for parametro in ("[string]$NomeCurto", "[string]$NomeDns", "[string[]]$Ip"):
        assert parametro in script
    assert '"2.5.29.17={text}' in script                     # SAN pela extensao, para caber o IP
    assert '"DNS=$_"' in script and '"IPAddress=$_"' in script
    assert "AddYears(5)" in script
    # nome e IP entram no texto da extensao: so' o que e' nome DNS ou IP valido passa (um "&" abriria outra entrada)
    assert "[System.Net.IPAddress]::TryParse" in script
    assert re.search(r"-notmatch '\^\[A-Za-z0-9", script)
    # o fim mostra o que foi emitido, para conferir antes de distribuir
    assert "Thumbprint" in script and "Nomes no certificado" in script


def test_rodar_producao_le_o_certificado_de_segredos_tls():
    script = _ler("rodar_producao.ps1")
    assert '$certs = Join-Path $Raiz "segredos\\tls"' in script
    assert 'Join-Path $repo "certs"' not in script
    # sem o par no lugar, para alto antes de subir (senao o uvicorn morre e a tarefa reinicia em laco)
    falta = script.index("certificado do HTTPS nao encontrado")
    assert falta < script.index("-m uvicorn")
    assert "Assert-AclSomenteSistemaEAdmins -Caminho $certs" in script
    # o cookie volta a Secure porque DASH_SEM_TLS so' existe com -SemTls
    assert 'if ($SemTls) { $env:DASH_SEM_TLS = "1" }' in script


def test_autostart_com_tls_confere_o_certificado_antes_de_registrar():
    script = _ler("instalar_autostart.ps1")
    conferencia = script.index('Join-Path $Raiz "segredos\\tls\\cert.pem"')
    assert conferencia < script.index("Register-ScheduledTask -TaskName")
    assert "if (-not $SemTls)" in script


def test_saude_local_confere_o_thumbprint_so_em_localhost():
    script = _ler("comum_tls.ps1")
    codigo = _codigo(script)
    # validacao por pedido, nunca a global do processo (o ServicePointManager valeria para qualquer HTTPS do script)
    assert "pedido.ServerCertificateValidationCallback" in codigo
    assert "ServicePointManager.ServerCertificateValidationCallback" not in codigo
    assert "c2.Thumbprint" in codigo and "StringComparison.OrdinalIgnoreCase" in codigo
    assert "uri.IsLoopback" in codigo
    assert "pedido.Proxy = null" in codigo
    # o PowerShell 5.1 nasce sem TLS 1.2 e o uvicorn nao aceita menos
    assert "SecurityProtocolType.Tls12" in codigo
    assert "function Get-ThumbprintDoCertificado" in codigo and "function Invoke-SaudeLocal" in codigo
    # /code-review: o C# so' compila no primeiro pedido https (nada de Add-Type solto no dot-source)
    corpo = codigo[codigo.index("function Initialize-DashSaudeLocal"):]
    assert codigo.index("Add-Type") > codigo.index("function Initialize-DashSaudeLocal")
    assert "Initialize-DashSaudeLocal\n" in corpo[corpo.index("function Invoke-SaudeLocal"):]
    # 4xx/5xx em http devolvem o status como em https (503 = banco fora), em vez de virar "sem resposta"
    assert "catch [System.Net.WebException]" in codigo and "$_.Exception.Response" in codigo


@pytest.mark.parametrize("nome", ["comum_tls.ps1", "watchdog.ps1", "instalar_watchdog.ps1", "deploy.ps1",
                                  "saude_local.ps1", "rodar_producao.ps1", "instalar_autostart.ps1",
                                  "gerar_certificado.ps1"])
def test_nenhum_script_desliga_a_verificacao_do_certificado(nome):
    codigo = _codigo(_ler(nome))
    assert "SkipCertificateCheck" not in codigo
    assert not re.search(r"ServerCertificateValidationCallback\s*=\s*\{\s*\$true\s*\}", codigo)
    assert "return true;" not in codigo


@pytest.mark.parametrize("nome", ["comum_tls.ps1", "watchdog.ps1", "instalar_watchdog.ps1", "saude_local.ps1"])
def test_scripts_novos_da_saude_ficam_em_ascii_sem_bom(nome):
    bruto = (SCRIPTS / nome).read_bytes()
    assert not bruto.startswith(b"\xef\xbb\xbf")
    assert bruto.isascii()


def test_watchdog_confere_por_https_com_o_certificado_da_instalacao():
    instalador = _ler("instalar_watchdog.ps1")
    assert "[switch]$SemTls" in instalador and '[string]$Raiz = ""' in instalador
    assert '$certificado = Join-Path $Raiz "segredos\\tls\\cert.pem"' in instalador
    assert '-Certificado `"$certificado`"' in instalador
    # /code-review: o modo vem conferido contra o da tarefa principal, antes de registrar
    assert 'Get-ScheduledTask -TaskName "DashboardLotufo"' in instalador
    assert '$tarefaSemTls -ne [bool]$SemTls' in instalador
    assert instalador.index("$tarefaSemTls -ne [bool]$SemTls") < instalador.index('Register-ScheduledTask -TaskName')
    watchdog = _ler("watchdog.ps1")
    assert '[string]$Certificado = ""' in watchdog
    assert '. (Join-Path $PSScriptRoot "comum_tls.ps1")' in watchdog
    assert "Invoke-SaudeLocal -Url $Url -Certificado $Certificado" in watchdog
    assert "Invoke-WebRequest" not in _codigo(watchdog)


def test_deploy_confere_a_saude_no_modo_da_tarefa():
    # a tarefa diz o modo: com -SemTls (a producao de antes do corte) a saude e' HTTP; sem ele, HTTPS pelo thumbprint
    script = _ler("deploy.ps1")
    funcao = script[script.index("function TlsDaTarefa"):script.index("$comTls = TlsDaTarefa")]
    assert 'Get-ScheduledTask -TaskName "DashboardLotufo"' in funcao
    assert '-match "-SemTls\\b"' in funcao
    assert '. (Join-Path $PSScriptRoot "comum_tls.ps1")' in script
    assert '$certificado = Join-Path $Raiz "segredos\\tls\\cert.pem"' in script
    assert script.count("Invoke-SaudeLocal -Url $urlSaude -Certificado $certificado") == 2   # Saudavel e AvisarSeCopia
    assert "Invoke-WebRequest" not in _codigo(script)
    # sem o certificado no modo HTTPS, aborta antes de pausar o watchdog e de qualquer checkout
    aborta = script.index("certificado do HTTPS nao encontrado")
    assert aborta < script.index("New-Item -ItemType File -Path $pause")


def test_saude_local_existe_para_a_conferencia_manual():
    script = _ler("saude_local.ps1")
    assert '. (Join-Path $PSScriptRoot "comum_tls.ps1")' in script
    assert "[switch]$SemTls" in script and "Mandatory" in script
    assert "Invoke-SaudeLocal" in script and "exit 1" in script


# --- Achados do revisor-adversarial e do gate Sol na PR #476 ------------------------------------------------------

def test_instalar_watchdog_le_porta_e_raiz_da_tarefa_e_aborta_se_divergir():
    # Gate Sol: com a producao em HTTPS na 8080, o instalador sem -Porta conferiria a 8443 e o watchdog reiniciaria uma
    # producao saudavel a cada 3 minutos. Omitidos vem da tarefa; explicito diferente aborta antes de registrar.
    script = _ler("instalar_watchdog.ps1")
    registro = script.index("Register-ScheduledTask -TaskName")
    bloco = script[script.index('$tarefa = Get-ScheduledTask -TaskName "DashboardLotufo"'):registro]
    assert 'if ($argumentosTarefa -match "-Porta (\\d+)") { $portaTarefa = [int]$Matches[1] }' in bloco
    assert "elseif ($tarefaSemTls) { $portaTarefa = 80 }" in bloco and "else { $portaTarefa = 8443 }" in bloco
    assert "if ($Porta -eq 0) { $Porta = $portaTarefa }" in bloco
    assert "nao bate com a tarefa DashboardLotufo (porta $portaTarefa)" in bloco
    assert "if (-not $Raiz) { $Raiz = $raizTarefa }" in bloco
    assert "nao bate com a tarefa DashboardLotufo (raiz $raizTarefa)" in bloco
    # o padrao da raiz e' o mesmo do deploy.ps1, e da' a raiz certa no formato que o instalar_autostart.ps1 grava
    regex = re.search(r"-match '([^']+)'", bloco).group(1)
    assert regex == _regex_da_raiz(_ler("deploy.ps1"))
    assert _raiz(regex, '-File "C:\\x\\rodar_producao.ps1" -Raiz "D:\\Dados Lotufo" -Porta 8080') == "D:\\Dados Lotufo"
    # o certificado sai da raiz ja' resolvida
    assert bloco.index("$Raiz = $raizTarefa") < script.index('$certificado = Join-Path $Raiz "segredos\\tls\\cert.pem"')


def test_deploy_em_https_recusa_alvo_anterior_a_425_antes_do_checkout():
    # Gate Sol: o rodar_producao.ps1 de antes da #425 procura a chave em app\certs e o watchdog.ps1 de antes nao
    # conhece -Certificado; com a tarefa em HTTPS, um alvo desses derrubaria os dois.
    script = _ler("deploy.ps1")
    trava = script.index("if ($comTls) {\n        $marcador = & git -C $AppDir ls-tree --name-only $alvo -- scripts/comum_tls.ps1")
    assert script.index("$alvo = $alvo.Trim()") < trava
    assert trava < script.index("backup_pre_migracao.ps1") and trava < script.index("try { Construir $alvo")
    bloco = script[trava:script.index("$migracoes =")]
    assert "volte para HTTP antes (runbook, Voltar atras)" in bloco and "exit 1" in bloco
    assert "2>" not in bloco      # stderr redirecionado vira erro fatal no 5.1 com Stop


def test_watchdog_nao_reinicia_por_problema_no_conferidor():
    # Revisor: cert.pem ilegivel ou Add-Type bloqueado nao podem reiniciar a producao a cada 3 minutos
    script = _ler("watchdog.ps1")
    conferidor = script.index("Initialize-DashSaudeLocal\n")
    bloco = script[conferidor:script.index("if (Saudavel) { exit 0 }")]
    assert "$script:thumbprint = Get-ThumbprintDoCertificado -Caminho $Certificado" in bloco
    assert "producao NAO reiniciada" in bloco and "exit 1" in bloco
    assert script.index('SairSePausado ""') < conferidor < script.index("Stop-ScheduledTask -TaskName")


def test_watchdog_le_o_thumbprint_uma_vez_e_usa_em_todas_as_consultas():
    # Gate Sol (rodada 2): cada Saudavel relia o cert.pem; ilegivel no meio da execucao, virava "producao fora"
    script = _ler("watchdog.ps1")
    saudavel = script[script.index("function Saudavel"):script.index("function SairSePausado")]
    assert "Invoke-SaudeLocal -Url $Url -Certificado $Certificado -Thumbprint $script:thumbprint" in saudavel
    assert _codigo(script).count("Get-ThumbprintDoCertificado") == 1
    comum = _ler("comum_tls.ps1")
    invoke = comum[comum.index("function Invoke-SaudeLocal"):]
    assert '[string]$Thumbprint = ""' in invoke
    # com o thumbprint dado, o arquivo nao e' relido
    assert "if (-not $Thumbprint) {" in invoke
    assert invoke.index("if (-not $Thumbprint) {") < invoke.index("Get-ThumbprintDoCertificado -Caminho $Certificado")


def test_watchdog_confere_o_sentinela_antes_de_cada_passo_na_tarefa():
    # Gate Sol (rodada 2): a manutencao pode comecar durante a segunda consulta (ate' 10 s)
    script = _ler("watchdog.ps1")
    funcao = script[script.index("function SairSePausado"):script.index('SairSePausado ""')]
    assert "if (Test-Path $Pausa) {" in funcao and "exit 0" in funcao
    parar = script.index("Stop-ScheduledTask -TaskName")
    iniciar = script.index("Start-ScheduledTask -TaskName")
    antes = script.rindex('SairSePausado "antes de parar a tarefa"', 0, parar)
    entre = script.index('SairSePausado "entre a parada e o inicio"')
    assert antes < parar < entre < iniciar
    # e a segunda consulta vem depois de conferir o sentinela de novo
    assert script.index("Start-Sleep -Seconds 15") < script.rindex('SairSePausado ""') < script.rindex("if (Saudavel) { exit 0 }")


def test_watchdog_so_inicia_a_tarefa_que_de_fato_parou():
    # Gate Sol (rodada 2): Stop com SilentlyContinue + catch vazio anulava a parada; instancia ainda "Running" fazia o
    # Start ser ignorado (IgnoreNew) com o log dizendo "disparado"
    script = _ler("watchdog.ps1")
    codigo = _codigo(script)
    assert "Stop-ScheduledTask -TaskName $Tarefa -ErrorAction Stop" in codigo
    assert "SilentlyContinue" not in codigo
    assert 'if ("$estado" -eq "Running") { Stop-ScheduledTask' in codigo   # Ready com o processo morto vai direto ao Start
    assert "FALHA ao parar a tarefa, nada iniciado" in codigo
    espera = codigo[codigo.index("$parada = $false"):codigo.index("Start-ScheduledTask -TaskName")]
    assert '"$estado" -ne "Running"' in espera and "continua '$estado' depois da parada -> nada iniciado" in espera
    assert "exit 1" in espera


def test_watchdog_acusa_tarefa_que_nao_iniciou_e_saude_que_nao_voltou():
    # Gate Sol: tarefa desabilitada da' erro nao fatal e o log dizia "disparado"; sem saude depois, sai com 1
    script = _ler("watchdog.ps1")
    assert '$ErrorActionPreference = "Stop"' in script
    assert "Start-ScheduledTask -TaskName $Tarefa -ErrorAction Stop" in script
    fim = script[script.index("Start-Sleep -Seconds 25"):]
    assert '"apos-reinicio saudavel=sim"' in fim
    assert 'apos-reinicio saudavel=nao ($script:ultimoErro)' in fim and "exit 1" in fim
    assert "pos-restart" not in script and "=True" not in script and "=False" not in script


def test_rodar_producao_nao_repassa_o_codigo_de_saida_do_uvicorn():
    # Revisor (rodada 2): saida diferente de 0 ligaria o RestartCount da tarefa, que nao respeita o watchdog.pause e
    # subiria no meio do rollback do deploy. O reinicio da producao caida e' so' do watchdog.
    script = _ler("rodar_producao.ps1")
    fim = _codigo(script[script.rindex("-m uvicorn"):])
    assert "exit" not in fim and "$LASTEXITCODE" not in fim
    assert "NÃO é repassado" in script and "watchdog.pause" in script
