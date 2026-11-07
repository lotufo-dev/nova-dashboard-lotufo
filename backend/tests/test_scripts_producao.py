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
    # Issue #386: a tarefa e' lida por schtasks /Query /XML (processo filho com tempo limite), nunca pelo cmdlet CIM
    assert "ScheduledTask" not in _codigo(script)
    leitura = script[script.index("function ArgumentosDaTarefa"):script.index("$argumentosDaTarefa = ArgumentosDaTarefa")]
    assert 'Agendar @("/Query", "/TN", $tarefaNome, "/XML")' in leitura
    # estouro aborta antes de tudo, com a frase da issue; tarefa inexistente guarda a saida do schtasks
    estouro = _bloco_do_if(leitura, "if ($r.Estourou) {")
    assert "$msgAgendador (schtasks /Query levou mais de $LimiteAgendador s); nada foi alterado" in estouro
    assert "exit 1" in estouro
    assert '$msgAgendador = "deploy abortado: agendador de tarefas nao respondeu"' in script
    assert "if ($r.Codigo -ne 0) { $script:saidaQuery = $r.Saida; return $null }" in leitura
    # os argumentos saem de <Arguments> (todas as acoes, como o Actions.Arguments do cmdlet), com o escape do XML desfeito
    padrao = re.search(r'\[regex\]::Matches\(\$r\.Saida, "([^"]+)"\)', leitura).group(1)
    xml = ('<?xml version="1.0" encoding="UTF-16"?><Task><Actions Context="Author"><Exec><Command>powershell.exe'
           '</Command><Arguments>-NoProfile -File &quot;C:\\x\\rodar_producao.ps1&quot; -Raiz &quot;D:\\Dados&quot; '
           '-Porta 8080</Arguments></Exec></Actions></Task>')
    assert [m.group(1) for m in re.finditer(padrao, xml)] == [
        '-NoProfile -File &quot;C:\\x\\rodar_producao.ps1&quot; -Raiz &quot;D:\\Dados&quot; -Porta 8080']
    assert "[System.Net.WebUtility]::HtmlDecode(" in leitura
    assert "nao consegui ler os argumentos da tarefa $tarefaNome no XML do schtasks; nada foi alterado" in leitura
    # o /XML redirecionado para arquivo costuma vir nos bytes da pagina de codigo; com NUL no meio e' UTF-16 de verdade
    # e e' relido como Unicode (## Suposicoes da PR #389)
    comum = _ler("comum_agendador.ps1")
    ler = comum[comum.index("function LerSaidaAgendador"):comum.index("function Agendador")]
    assert "Get-Content $arquivo -Raw -ErrorAction SilentlyContinue" in ler
    assert "$texto.IndexOf([char]0) -ge 0" in ler and "-Encoding Unicode" in ler
    assert re.search(r'-match "-Porta \(\\d\+\)"', script)
    # tarefa sem -Porta = padrao do modo do rodar_producao.ps1 (issue #425, /code-review): 80 com -SemTls, 8443 com TLS
    funcao = script[script.index("function PortaDaTarefa"):script.index("$portaTarefa = PortaDaTarefa")]
    assert "if ($null -eq $argumentosDaTarefa) { return 0 }" in funcao
    assert 'if ($argumentosTarefa -match "-SemTls\\b") { return 80 }' in funcao
    assert funcao.rstrip().endswith("return 8443\n}")
    assert "-Porta $Porta nao bate com a tarefa $tarefaNome (porta $portaTarefa); nada foi alterado" in script
    # a leitura e a conferencia vem antes de qualquer git checkout
    assert script.index("$argumentosDaTarefa = ArgumentosDaTarefa") < script.index("$portaTarefa = PortaDaTarefa")
    assert script.index("$portaTarefa = PortaDaTarefa") < script.index("function Construir")


def test_deploy_para_a_tarefa_por_schtasks_tambem_no_ponto_da_sentinela_e_mantem_o_sentinela_ao_falhar():
    # Juncao da #386 com a #478: a parada do ponto da sentinela tambem passa pelo schtasks com tempo limite, e marca a
    # tarefa como (talvez) parada ANTES do /End; a volta do pinado registra o deploy do commit anterior; o rollback que
    # falha mantem o sentinela do watchdog.
    codigo = _codigo(_ler("deploy.ps1"))
    sentinela = codigo[codigo.index("function SentinelaAntesDa456"):codigo.index("function AvisarSeCopia")]
    assert sentinela.index("$script:tarefaParada = $true") < sentinela.index('ComandoTarefa "End" $false')
    assert sentinela.index('ComandoTarefa "End" $false') < sentinela.index("LiberarPorta")
    voltar = codigo[codigo.index("function VoltarPinado"):codigo.index("function SentinelaAntesDa456")]
    assert voltar.index("Reconstruir") < voltar.index("RegistrarDeploy")
    rollback = codigo[codigo.index("ROLLBACK para $anterior"):]
    tentativa = rollback[:rollback.index("} catch {")]
    assert all(passo in tentativa for passo in ("SentinelaAntesDa456 $novo $anterior", "Construir $anterior",
                                                 "RegistrarDeploy", "Reiniciar"))
    assert "$script:manterSentinela = $true" in rollback[rollback.index("} catch {"):]
    assert "if ($script:manterSentinela)" in codigo and "Remove-Item $pause" in codigo


def test_deploy_com_reinicio_que_falha_para_e_passa_o_ponto_da_sentinela_antes_de_voltar_o_pinado():
    # Revisor da PR #389 (A1): o /Run que estoura no cliente pode ter subido o commit novo (e a 063); voltar o pinado sem
    # passar o ponto para a auditoria faria o anterior acusar "Estado da sentinela apagado" (issue #478), e o build do
    # anterior correria com o novo no ar.
    codigo = _codigo(_ler("deploy.ps1"))
    falha = codigo[codigo.index("try { Reiniciar }"):codigo.index("if (SaudavelENovo -ExigirInstalacao) {")]
    parada = _bloco_do_if(falha, "if ($script:tarefaParada) {")   # o primeiro: antes de voltar o pinado
    assert parada.index("$script:sentinelaParou = $false") < parada.index("SentinelaAntesDa456 $novo $anterior")
    sem_troca = _bloco_do_if(parada, "if (-not $script:sentinelaParou) {")
    assert 'ComandoTarefa "End" $false' in sem_troca and "LiberarPorta" in sem_troca and "catch" in sem_troca
    assert falha.index("SentinelaAntesDa456 $novo $anterior") < falha.index("VoltarPinado $anterior")


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
    # os argumentos lidos uma vez por schtasks /Query /XML (issue #386); tarefa inexistente = sem raiz
    assert 'if ($null -eq $argumentosDaTarefa) { return "" }' in funcao
    assert script.index("$argumentosDaTarefa = ArgumentosDaTarefa") < script.index("$raizTarefa = RaizDaTarefa")
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
    assert "if ($null -eq $argumentosDaTarefa) { return $true }" in funcao   # lida por schtasks /Query /XML (#386)
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
    assert script.index('SairSePausado ""') < conferidor < script.index('Agendador @("/End", "/TN", $Tarefa)')


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
    parar = script.index('Agendador @("/End", "/TN", $Tarefa)')
    iniciar = script.index('Agendador @("/Run", "/TN", $Tarefa)')
    antes = script.rindex('SairSePausado "antes de parar a tarefa"', 0, parar)
    entre = script.index('SairSePausado "entre a parada e o inicio"')
    assert antes < parar < entre < iniciar
    # e a segunda consulta vem depois de conferir o sentinela de novo
    assert script.index("Start-Sleep -Seconds 15") < script.rindex('SairSePausado ""') < script.rindex("if (Saudavel) { exit 0 }")


def test_watchdog_fala_com_o_agendador_por_schtasks_com_tempo_limite():
    # Issue #386: o provedor CIM do agendador pode ficar sem responder (deploy de 2026-11-04 parado mais de 10 min em
    # Get-ScheduledTask); o watchdog para e inicia a tarefa por schtasks /End e /Run, cada um com tempo limite.
    script = _ler("watchdog.ps1")
    codigo = _codigo(script)
    assert "ScheduledTask" not in codigo
    assert "SilentlyContinue" not in codigo
    assert '. (Join-Path $PSScriptRoot "comum_agendador.ps1")' in codigo
    assert "[int]$LimiteAgendador = 30" in codigo
    parar = codigo.index('$fim = Agendador @("/End", "/TN", $Tarefa) $LimiteAgendador')
    # agendador que nao responde a tempo nao inicia nada: sai com 1 e o watchdog repete em 3 min
    estouro = _bloco_do_if(codigo, "if ($fim.Estourou) {")
    assert "schtasks /End levou mais de $LimiteAgendador s) -> nada iniciado" in estouro and "exit 1" in estouro
    iniciar = codigo.index('$inicio = Agendador @("/Run", "/TN", $Tarefa) $LimiteAgendador')
    assert parar < codigo.index("try { $orfao = DonoDaPorta }") < iniciar
    assert "exit 1" in _bloco_do_if(codigo, "if ($inicio.Estourou) {")
    # a funcao comum mata o schtasks que estoura o limite e devolve Estourou, sem esperar para sempre
    comum = _codigo(_ler("comum_agendador.ps1"))
    agendador = comum[comum.index("function Agendador"):]
    assert "$p.WaitForExit($LimiteSegundos * 1000)" in agendador
    assert "Stop-Process -Id $p.Id -Force" in agendador and "Estourou = $true" in agendador
    for nome in ("comum_agendador.ps1",):
        bruto = (SCRIPTS / nome).read_bytes()
        assert not bruto.startswith(b"\xef\xbb\xbf") and bruto.isascii()


def test_watchdog_so_inicia_a_tarefa_que_de_fato_parou():
    # Gate Sol da PR #476: parada que falha, ou instancia ainda "Running", fazia o Start ser ignorado (IgnoreNew) com o
    # log dizendo "disparado". Sem CIM (issue #386, revisor da PR #389): o estado vem da COM Schedule.Service, numerica.
    codigo = _codigo(_ler("watchdog.ps1"))
    inicio = codigo.index('SairSePausado "antes de parar a tarefa"')
    leitura = codigo.index("$estado = EstadoDaTarefa $Tarefa $LimiteAgendador", inicio)
    ilegivel = _bloco_do_if(codigo, 'if ($estado -eq "desconhecido") {\n    Escrever')
    assert "FALHA ao parar a tarefa, nada iniciado" in ilegivel and "exit 1" in ilegivel
    # parar so' o que esta rodando: "Ready" com o processo morto vai direto ao /Run
    rodando = _bloco_do_if(codigo, 'if ($estado -eq "Running") {')
    assert '$fim = Agendador @("/End", "/TN", $Tarefa) $LimiteAgendador' in rodando
    falha = rodando[rodando.index("if ($fim.Codigo -ne 0) {"):]
    assert "FALHA ao parar a tarefa, nada iniciado" in falha and "exit 1" in falha
    assert "(segue para o /Run)" not in codigo
    espera = codigo[codigo.index("$parada = $false"):codigo.index('$inicio = Agendador @("/Run"')]
    assert '$estado -ne "Running"' in espera and '$estado -eq "desconhecido") { break }' in espera
    assert "continua '$estado' depois da parada -> nada iniciado" in espera and "exit 1" in espera
    assert inicio < leitura < codigo.index("$parada = $false") < codigo.index("try { $orfao = DonoDaPorta }")


def test_estado_da_tarefa_vem_da_com_num_processo_filho_com_tempo_limite():
    comum = _codigo(_ler("comum_agendador.ps1"))
    funcao = comum[comum.index("function EstadoDaTarefa"):]
    assert "New-Object -ComObject Schedule.Service" in funcao and "exit (100 + [int]" in funcao
    assert ".GetTask('$Tarefa').State" in funcao
    # powershell filho pela Agendador (mata no estouro); -EncodedCommand evita aspas no ArgumentList do 5.1
    assert '"-EncodedCommand", $codificado) $LimiteSegundos "powershell.exe"' in funcao
    assert "[Text.Encoding]::Unicode.GetBytes($comando)" in funcao
    # estouro, erro (o filho sai com 1) ou fora da faixa = desconhecido; 100 + 4 = Running
    assert 'if ($r.Estourou -or $r.Codigo -lt 100 -or $r.Codigo -gt 104) { return "desconhecido" }' in funcao
    assert '@("Unknown", "Disabled", "Queued", "Ready", "Running")[$r.Codigo - 100]' in funcao


def _bloco_do_if(codigo, cabeca):
    """O corpo do bloco que comeca em `cabeca`, ate' o '}' que o fecha na mesma indentacao."""
    inicio = codigo.index(cabeca)
    linha_ini = codigo.rfind("\n", 0, inicio) + 1
    recuo = codigo[linha_ini:inicio]
    fim = codigo.index("\n" + recuo + "}", inicio)
    return codigo[inicio:fim]


def test_watchdog_consulta_a_porta_sem_tratar_erro_como_porta_livre():
    # Gate Sol da PR #494 (S2): erro do Get-NetTCPConnection virava "porta livre" e o Start corria contra o orfao
    codigo = _codigo(_ler("watchdog.ps1"))
    assert "([uri]$Url).Port" in codigo
    dono = codigo[codigo.index("function DonoDaPorta"):]
    dono = dono[:dono.index("\n}") + 2]
    # lista todos os listeners e filtra a porta no pipeline: ausencia e' lista vazia, nao erro
    assert "Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -eq $porta }" in dono
    assert "-LocalPort" not in dono
    consulta = dono[:dono.index("if (-not $c) { return $null }")]
    assert "try" not in consulta and "catch" not in consulta
    # quem chama registra o erro e nao inicia nada, antes e depois de encerrar o orfao
    falha_antes = _bloco_do_if(codigo, 'catch {\n    Escrever ("FALHA ao consultar a porta ${porta}, nada iniciado')
    assert "exit 1" in falha_antes
    assert codigo.index("try { $orfao = DonoDaPorta }") < codigo.index(falha_antes)
    falha_depois = _bloco_do_if(
        codigo, 'catch {\n        Escrever ("FALHA ao consultar a porta $porta depois de encerrar o orfao')
    assert "nada iniciado" in falha_depois and "exit 1" in falha_depois
    assert codigo.index("try { $resto = DonoDaPorta }") < codigo.index(falha_depois)


def test_watchdog_so_encerra_o_uvicorn_da_dashboard_pelos_argumentos_exatos():
    # Gate Sol da PR #494 (S1): duas substrings soltas casariam outro FastAPI; os argumentos sao os do rodar_producao
    codigo = _codigo(_ler("watchdog.ps1"))
    funcao = codigo[codigo.index("function EDaDashboard"):]
    funcao = funcao[:funcao.index("\n}") + 2]
    assert '-match "-m uvicorn --factory app\\.main:create_app "' in funcao
    assert '-match "--port $porta(\\s|$)"' in funcao and "-and" in funcao
    rodar = _ler("rodar_producao.ps1")
    assert rodar.count("-m uvicorn --factory app.main:create_app ") == 2 and rodar.count("--port $Porta") == 2
    # dono que nao e' a dashboard: PID no log, nada morto, sai com 1
    alheio = _bloco_do_if(codigo, "if (-not (EDaDashboard $orfao)) {")
    assert ('Escrever "porta $porta ocupada pelo PID $($orfao.ProcessId) ($($orfao.Name)), '
            'que nao e\' a dashboard -> nada iniciado"') in alheio
    assert "exit 1" in alheio and "Stop-Process" not in alheio


def test_watchdog_encerra_o_uvicorn_orfao_antes_de_iniciar_a_tarefa():
    # Issue #480: parar a tarefa nao mata o uvicorn (incidente de 2026-09-21); o orfao segura a porta, a instancia
    # nova morre com WinError 10048 e o watchdog repetia o Start a cada 3 minutos, para sempre
    codigo = _codigo(_ler("watchdog.ps1"))
    linhas = [linha.strip() for linha in codigo.splitlines()]
    parar = codigo.index('Agendador @("/End", "/TN", $Tarefa)')
    pausa_porta = codigo.index('SairSePausado "antes de conferir a porta"')
    consulta = codigo.index("try { $orfao = DonoDaPorta }")
    pausa_matar = codigo.index('SairSePausado "antes de encerrar o orfao"')
    reconfere = codigo.index("try { $agora = DonoDaPorta }")
    matar = codigo.index("Stop-Process -Id $orfao.ProcessId -Force")
    entre = codigo.index('SairSePausado "entre a parada e o inicio"')
    iniciar = codigo.index('Agendador @("/Run", "/TN", $Tarefa)')
    # Gate Sol da PR #494 (S3): o sentinela e' conferido antes de consultar a porta e logo antes de matar
    assert parar < pausa_porta < consulta < pausa_matar < reconfere < matar < entre < iniciar
    # reuso de PID: o dono e' reconferido (PID e criacao) antes do Stop-Process
    mudou = _bloco_do_if(codigo, "if (-not $agora -or $agora.ProcessId -ne $orfao.ProcessId")
    assert '"$($agora.CreationDate)" -ne "$($orfao.CreationDate)"' in mudou
    assert "nada iniciado" in mudou and "exit 1" in mudou
    # a linha logo antes do Stop-Process e' o log com o PID que vai ser encerrado
    i = next(n for n, linha in enumerate(linhas) if "Stop-Process -Id $orfao.ProcessId -Force" in linha)
    assert linhas[i - 1] == (
        'Escrever "servidor orfao na porta $porta (PID $($orfao.ProcessId), criado em $($orfao.CreationDate)) '
        '-> encerrando"'
    )
    # se nao morre, nada e' iniciado e sai com 1, com o PID no log
    resto = _bloco_do_if(codigo, "if ($resto) {")
    assert ('Escrever "porta $porta ocupada pelo PID $($resto.ProcessId) depois de encerrar o orfao '
            '-> nada iniciado"') in resto
    assert "exit 1" in resto


def test_watchdog_acusa_tarefa_que_nao_iniciou_e_saude_que_nao_voltou():
    # Gate Sol: tarefa desabilitada da' erro nao fatal e o log dizia "disparado"; sem saude depois, sai com 1
    script = _ler("watchdog.ps1")
    assert '$ErrorActionPreference = "Stop"' in script
    # schtasks /Run com codigo diferente de 0 (tarefa desabilitada, inexistente) e' falha, nunca "disparado" (#386)
    falha = _bloco_do_if(script, "if ($inicio.Codigo -ne 0) {")
    assert "FALHA ao iniciar (schtasks /Run devolveu" in falha and "exit 1" in falha
    assert script.index(falha) < script.index('Escrever "schtasks /Run disparado"')
    fim =script[script.index("Start-Sleep -Seconds 25"):]
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
