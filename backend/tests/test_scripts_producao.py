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
    # estouro aborta antes de tudo, com a frase da issue
    estouro = _bloco_do_if(leitura, "if ($r.Estourou) {")
    assert "$msgAgendador (schtasks /Query levou mais de $LimiteAgendador s); nada foi alterado" in estouro
    assert "exit 1" in estouro
    assert '$msgAgendador = "deploy abortado: agendador de tarefas nao respondeu"' in script
    # gate Sol da PR #389 (Aviso 1): QUALQUER falha do /Query aborta; -Porta informada nao inventa raiz nem modo
    falhou = _bloco_do_if(leitura, "if ($r.Codigo -ne 0) {")
    assert "throw " in falhou and "nada foi alterado" in falhou and "return" not in falhou
    assert "$null" not in _codigo(script[script.index("function PortaDaTarefa"):script.index("$comTls = TlsDaTarefa")])
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
    # parada COMPROVADA (gate Sol da PR #389, Critico 1): solicitada antes do /End, provada pelo estado (so' Ready ou
    # Disabled) e pela porta livre; qualquer falha lanca
    parar = codigo[codigo.index("function PararComprovado"):codigo.index("function Reiniciar")]
    ordem = ["$script:tarefaParada = $true", "$script:producaoMexida = $true", 'ComandoTarefa "End" $false',
             "$estado = EstadoDaTarefa $tarefaNome $LimiteAgendador", "if (-not (TarefaParada $estado)) { throw ",
             "LiberarPorta"]
    assert [parar.index(passo) for passo in ordem] == sorted(parar.index(passo) for passo in ordem)
    assert "catch" not in parar
    reiniciar = codigo[codigo.index("function Reiniciar"):codigo.index("function SaudavelENovo")]
    assert reiniciar.index('PararComprovado "reinicio"') < reiniciar.index('ComandoTarefa "Run" $true')
    # no ponto da sentinela a parada nao fica num try que engole: a excecao sobe para quem chama
    sentinela = codigo[codigo.index("function SentinelaAntesDa456"):codigo.index("function AvisarSeCopia")]
    para = sentinela.index('PararComprovado "ponto da sentinela"')
    assert para < sentinela.index("$script:sentinelaParou = $true") < sentinela.index("try {")
    # antes do checkout, parada nao provada nao faz checkout: religa o anterior ou mantem o sentinela
    principal = codigo[codigo.index("$anterior = (& git"):]
    antes = _bloco_do_if(principal, "try { SentinelaAntesDa456 $anterior $alvo }\n    catch {")
    assert "Construir" not in antes and "VoltarPinado" not in antes and "exit 1" in antes
    assert "$script:soltarWatchdog = $true" in antes and "$script:manterSentinela = $true" in antes
    # remescla com a #475: religar so' solta com processo novo no commit anterior e a producao provada no inicio
    assert "$religou = (SaudavelENovo) -and (NoArEm $anterior)" in antes
    assert "if ($religou -and $script:producaoProvada) {" in antes
    assert principal.index("try { SentinelaAntesDa456 $anterior $alvo }") < principal.index("try { Construir $alvo")
    voltar = codigo[codigo.index("function VoltarPinado"):codigo.index("function SentinelaAntesDa456")]
    assert voltar.index("Reconstruir") < voltar.index("RegistrarDeploy")
    rollback = codigo[codigo.index("ROLLBACK para $anterior"):]
    tentativa = rollback[:rollback.index("} catch {")]
    assert all(passo in tentativa for passo in ("SentinelaAntesDa456 $novo $anterior", "Construir $anterior",
                                                 "RegistrarDeploy", "Reiniciar"))
    assert "$script:manterSentinela = $true" in rollback[rollback.index("} catch {"):]
    assert "-not $script:manterSentinela) {" in codigo and "Remove-Item $pause" in codigo


def test_deploy_com_reinicio_que_falha_para_e_passa_o_ponto_da_sentinela_antes_de_voltar_o_pinado():
    # Revisor da PR #389 (A1): o /Run que estoura no cliente pode ter subido o commit novo (e a 063); voltar o pinado sem
    # passar o ponto para a auditoria faria o anterior acusar "Estado da sentinela apagado" (issue #478), e o build do
    # anterior correria com o novo no ar.
    codigo = _codigo(_ler("deploy.ps1"))
    falha = codigo[codigo.index("try { Reiniciar }"):codigo.index("if ((SaudavelENovo -ExigirInstalacao) -and (NoArEm $novo)) {")]
    parada = _bloco_do_if(falha, "if ($script:tarefaParada) {")   # o primeiro: antes de voltar o pinado
    assert parada.index("$script:sentinelaParou = $false") < parada.index("SentinelaAntesDa456 $novo $anterior")
    # sem a troca da #456, a mesma parada comprovada (estado e porta), nao um /End que so' avisa
    assert 'if (-not $script:sentinelaParou) { PararComprovado "antes de voltar o pinado" }' in parada
    assert "ComandoTarefa" not in parada
    # gate Sol (Critico 1) e revisor (Aviso), rodada 2 da PR #389: parada nao provada NAO toca no pinado; mantem o
    # sentinela e sai com intervir a mao
    nao_provada = parada[parada.index("} catch {"):]
    assert "$script:manterSentinela = $true" in nao_provada and "exit 1" in nao_provada
    assert "NAO foi voltado" in nao_provada and "VoltarPinado" not in nao_provada
    assert falha.index("SentinelaAntesDa456 $novo $anterior") < falha.index("VoltarPinado $anterior")
    assert falha.index(nao_provada) < falha.index("VoltarPinado $anterior")


def test_deploy_so_solta_o_watchdog_com_a_producao_comprovada():
    # Gate Sol da PR #389 (Critico 2): a consulta da porta que lanca (CIM travado) escapava da verificacao e o finally
    # apagava o watchdog.pause sem o processo novo provado e sem rollback.
    codigo = _codigo(_ler("deploy.ps1"))
    novo = codigo[codigo.index("function SaudavelENovo"):codigo.index("function DiagnosticoPorta")]
    falha = _bloco_do_if(novo, "catch {")
    assert novo.index("try { $dono = DonoDaPorta }") < novo.index("catch {")
    assert "return $false" in falha
    # o sentinela so' sai sem parada, ou com a producao (nova ou anterior) comprovada
    principal = codigo[codigo.index("$anterior = (& git"):]
    assert principal.index("$script:producaoMexida = $false") < principal.index("New-Item -ItemType File -Path $pause")
    assert principal.index("$script:producaoProvada = $false") < principal.index("New-Item -ItemType File -Path $pause")
    ok = principal[principal.index("if ((SaudavelENovo -ExigirInstalacao) -and (NoArEm $novo)) {"):principal.index("DEPLOY OK")]
    assert "$script:producaoProvada = $true" in ok
    rollback_ok = next(linha for linha in principal.splitlines() if "ROLLBACK OK" in linha)
    assert rollback_ok.strip().startswith("if ($voltou) { $script:producaoProvada = $true; $script:soltarWatchdog = $true;")
    # remescla com a #475: a prova do inicio deixa de valer quando o processo no ar vai ser trocado
    assert principal.index("$script:producaoProvada = $false\n    try { Reiniciar }") < principal.index("DEPLOY OK")
    # no catch do reinicio, religar so' prova com processo novo no commit anterior
    reinicio = principal[principal.index("try { Reiniciar }"):principal.index("DEPLOY OK")]
    assert "try { Reiniciar; $religou = (SaudavelENovo) -and (NoArEm $anterior) }" in reinicio
    fim = principal[principal.rindex("} finally {"):]
    assert "if ($script:producaoMexida -and -not $script:producaoProvada) { $script:manterSentinela = $true }" in fim
    assert fim.index("-not $script:producaoProvada) {") < fim.index("if ($script:soltarWatchdog -and $script:producaoProvada -and -not $script:manterSentinela) {")
    # schtasks que estoura e nem morto morre: o /End ou /Run orfao ainda pode concluir, o watchdog fica pausado
    comando = codigo[codigo.index("function ComandoTarefa"):codigo.index("function PararComprovado")]
    assert "if ($r.FilhoVivo) { $script:manterSentinela = $true; throw " in comando


def test_deploy_faz_rollback_quando_a_instalacao_nao_e_autorizada():
    # Issue #417: health 200 com `instalacao` diferente de "autorizada" depois do deploy conta como falha e cai no
    # rollback que ja' existe. O rollback confere so' o 200: o commit anterior pode nem ter o campo.
    script = _ler("deploy.ps1")
    corpo = script[script.index("function Saudavel"):script.index("function Construir")]
    assert "ConvertFrom-Json" in corpo
    assert re.search(r'\.instalacao -eq "autorizada"', corpo)
    assert "[switch]$ExigirInstalacao" in corpo
    assert script.count("SaudavelENovo -ExigirInstalacao") == 1
    deploy = script.index("if ((SaudavelENovo -ExigirInstalacao) -and (NoArEm $novo)) {")
    rollback = script.index("ROLLBACK para $anterior")
    assert deploy < rollback
    assert "$voltou = (SaudavelENovo) -and (NoArEm $anterior)\n" in script[rollback:]
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
    # os argumentos lidos uma vez por schtasks /Query /XML (issue #386); sem a tarefa o deploy ja' abortou
    assert "$argumentosTarefa = $argumentosDaTarefa" in funcao
    assert "if (-not $Raiz) {\n    $Raiz = $raizTarefa\n}" in script
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


def _codigo(script):
    """O script sem os comentarios de linha inteira (o texto deles cita fetch, sentinela etc.)."""
    return "\n".join(linha for linha in script.splitlines() if not linha.lstrip().startswith("#"))


def test_deploy_rollback_usa_o_commit_anterior_sem_fetch():
    # Issue #443 (Critico do gate Sol na PR #437): o rollback chamava Construir $anterior, que comecava com git fetch;
    # com a rede caida o rollback abortava no fetch e a pasta ficava no commit novo. O unico fetch e' o do fluxo
    # principal, antes do checkout do alvo; Construir so' faz checkout de um commit que ja' esta' no clone.
    codigo = _codigo(_ler("deploy.ps1"))
    construir = codigo[codigo.index("function Construir"):codigo.index("function Reconstruir")]
    assert "fetch" not in construir
    assert "checkout --quiet --detach $alvo" in construir
    assert codigo.count("fetch --quiet") == 1 and codigo.count("git fetch falhou") == 1
    assert codigo.index("& git -C $AppDir fetch --quiet") < codigo.index("try { Construir $alvo; ConferirInstalacao }")
    # o rollback ainda volta para o commit anterior (lido do HEAD antes do deploy, nao de origin)
    rollback = codigo[codigo.index("ROLLBACK para $anterior"):codigo.index("\n} finally {")]
    assert "Construir $anterior" in rollback


def test_deploy_rollback_tem_try_proprio_e_mantem_o_sentinela():
    # Issue #443: checkout, rebuild, reinicio e health do rollback ficam num try proprio; qualquer excecao imprime
    # ROLLBACK TAMBEM FALHOU e sai sem soltar o watchdog (antes ela ia direto ao finally, que apagava o sentinela).
    codigo = _codigo(_ler("deploy.ps1"))
    rollback = codigo[codigo.index("ROLLBACK para $anterior"):codigo.index("\n} finally {")]
    tentativa = rollback[rollback.index("try {"):rollback.index("} catch {")]
    for passo in ("Construir $anterior", "RegistrarDeploy", "Reiniciar", "SaudavelENovo"):
        assert passo in tentativa, f"{passo} fora do try do rollback"
    captura = rollback[rollback.index("} catch {"):]
    captura = captura[:captura.index("exit 1")]
    assert "ROLLBACK TAMBEM FALHOU ($($_.Exception.Message))" in captura
    assert "soltarWatchdog" not in captura
    # o rollback que nao volta saudavel tambem mantem o sentinela; so' o ROLLBACK OK solta
    falhou = rollback[rollback.rindex("ROLLBACK TAMBEM FALHOU"):]
    assert "soltarWatchdog" not in falhou[:falhou.index("exit 1")]
    linha_ok = next(linha for linha in rollback.splitlines() if "ROLLBACK OK" in linha)
    assert "$script:soltarWatchdog = $true" in linha_ok


def test_deploy_so_apaga_o_sentinela_com_a_producao_conferida():
    # Issue #443 / runbook "Subir e derrubar": o sentinela so' sai com o commit novo saudavel, o anterior restaurado e
    # verificado, ou o deploy abortado antes de o pinado mudar. Qualquer outra saida (excecao no reinicio, rollback que
    # falhou, volta do build que falhou) deixa o watchdog pausado.
    script = _ler("deploy.ps1")
    codigo = _codigo(script)
    assert codigo.count("Remove-Item $pause") == 1
    final = codigo[codigo.index("\n} finally {"):]
    soltar = final[final.index("if ($script:soltarWatchdog -and $script:producaoProvada -and -not $script:manterSentinela) {"):final.index("\n    elseif (")]
    assert "Remove-Item $pause" in soltar
    assert "MANTIDO" in final
    # comeca falso, antes de criar o sentinela
    assert codigo.index("$script:soltarWatchdog = $false") < codigo.index("New-Item -ItemType File -Path $pause")
    # os unicos pontos que soltam: antes do checkout do alvo (so' com a producao provada no inicio, rodada 2), a volta
    # do build que deu certo, DEPLOY OK e ROLLBACK OK; da remescla com a #389, os dois religar (parada do ponto da
    # sentinela nao comprovada antes do checkout e reinicio que falhou), so' com processo novo no commit anterior
    soltas = [m.start() for m in re.finditer(r"\$script:soltarWatchdog = \$true", codigo)]
    assert len(soltas) == 5
    antes_checkout = codigo[codigo.index("try { SentinelaAntesDa456 $anterior $alvo }"):codigo.index("try { Construir $alvo")]
    assert antes_checkout.count("$script:soltarWatchdog = $true") == 1
    assert antes_checkout.index("if ($religou -and $script:producaoProvada) {") < antes_checkout.index("$script:soltarWatchdog = $true")
    soltas = [p for p in soltas if not (codigo.index(antes_checkout) <= p < codigo.index(antes_checkout) + len(antes_checkout))]
    inicio = codigo.index("$script:soltarWatchdog = $script:producaoProvada")
    assert codigo.count("$script:soltarWatchdog = $script:producaoProvada") == 1
    checkout = codigo.index("try { Construir $alvo; ConferirInstalacao }")
    assert inicio < codigo.index("& git -C $AppDir fetch --quiet")
    # antes do checkout do alvo a variavel volta a falso: dali em diante o pinado muda
    trava = codigo.rindex("$script:soltarWatchdog = $false", 0, checkout)
    assert inicio < trava < checkout < soltas[0]
    volta = codigo[checkout:codigo.index("$novo = (")]
    assert volta.count("$script:soltarWatchdog = $true") == 1
    assert volta.index("$script:soltarWatchdog = $true") < volta.index("deploy abortado no build; producao segue")
    falha_volta = volta[volta.index("deploy abortado no build E a volta"):]
    assert "soltarWatchdog" not in falha_volta
    ok = codigo[codigo.index("if ((SaudavelENovo -ExigirInstalacao) -and (NoArEm $novo)) {"):codigo.index("ROLLBACK para $anterior")]
    assert ok.count("$script:soltarWatchdog = $true") == 1
    # o reinicio e o health do commit novo ficam depois da trava: excecao ali nao solta o watchdog
    principal = codigo[codigo.index("$novo = ("):codigo.index("if ((SaudavelENovo -ExigirInstalacao) -and (NoArEm $novo)) {")]
    assert trava < codigo.index("$novo = (") and "Reiniciar" in principal
    # no catch do reinicio (PR #389) so' o religar provado (processo novo no commit anterior) solta
    assert principal.count("$script:soltarWatchdog = $true") == 1
    religar = principal[principal.index("try { Reiniciar; $religou = (SaudavelENovo) -and (NoArEm $anterior) }"):]
    assert religar.index("if ($religou) {") < religar.index("$script:soltarWatchdog = $true")
    # as linhas finais de "intervir a mao" saem mesmo com o rev-parse vazio (nada de .Trim() em $null)
    for marca in ("deploy abortado no build E a volta", "ROLLBACK TAMBEM FALHOU ($($_.Exception.Message))"):
        antes = codigo[:codigo.index(marca)].splitlines()[-2]   # a linha anterior ao Write-Host
        assert '$onde = "$(& git -C $AppDir rev-parse HEAD)".Trim()' in antes


def test_deploy_volta_do_build_reconstroi_confere_a_arvore_e_o_health_antes_de_soltar():
    # Gate Sol da PR #475 (issue #443): a volta do build decidia so' por HEAD != $anterior e soltava o watchdog sem
    # conferir nada. Deploy do mesmo commit com pip/npm quebrando a venv ou o dist, checkout pela metade (HEAD parado,
    # arvore misturada) ou reconstrucao sem health soltavam o sentinela com a producao quebrada no disco.
    codigo = _codigo(_ler("deploy.ps1"))
    construir = codigo[codigo.index("function Construir"):codigo.index("function Reconstruir")]
    # o build comeca so' depois do checkout que deu certo
    assert construir.index("throw \"git checkout $alvo falhou") < construir.index("$script:buildComecou = $true") \
        < construir.index("Reconstruir")
    assert codigo.index("$script:buildComecou = $false") < codigo.index("New-Item -ItemType File -Path $pause")
    checkout = codigo.index("try { Construir $alvo; ConferirInstalacao }")
    volta = codigo[checkout:codigo.index("$novo = (")]
    volta = volta[:volta.index("deploy abortado no build E a volta")]
    # o anterior e' reconstruido sempre que o build comecou, mesmo com o HEAD igual (deploy do mesmo commit)
    condicao = volta.index("if ($atual -ne $anterior -or $script:buildComecou -or ")
    assert condicao < volta.index("Reconstruir", condicao)
    # arvore limpa e health do processo no ar antes de soltar
    status = volta.index("& git -C $AppDir status --porcelain --untracked-files=no")
    assert "if ($alterados) { throw " in volta
    health = volta.index("if (-not (NoArEm $anterior)) { throw ")
    solta = volta.index("$script:soltarWatchdog = $true")
    assert condicao < status < health < solta


def test_deploy_confere_que_o_sentinela_saiu_e_falha_se_ficou():
    # Gate Sol da PR #475 (issue #443): Remove-Item com SilentlyContinue podia falhar (ACL, bloqueio) e o script
    # terminava em DEPLOY OK com o sentinela la', e o watchdog pausado para sempre.
    codigo = _codigo(_ler("deploy.ps1"))
    final = codigo[codigo.index("\n} finally {"):]
    soltar = final[final.index("if ($script:soltarWatchdog -and $script:producaoProvada -and -not $script:manterSentinela) {"):final.index("\n    elseif (")]
    assert "Remove-Item $pause -Force -ErrorAction Stop" in soltar
    assert "SilentlyContinue" not in soltar
    conferencia = soltar.rindex("if (Test-Path $pause) {")
    assert soltar.index("Remove-Item $pause") < conferencia
    depois = soltar[conferencia:]
    assert "$script:sentinelaPreso = $true" in depois and "MANTIDO" in depois
    # depois do finally (DEPLOY OK nao sai com exit), o script sai com 1 se o sentinela ficou
    fim = final[final.index("\n}\n"):]
    assert "if ($script:sentinelaPreso) { exit 1 }" in fim
    assert codigo.index("$script:sentinelaPreso = $false") < codigo.index("New-Item -ItemType File -Path $pause")


def test_deploy_confere_a_producao_no_inicio_e_so_solta_o_aborto_antes_do_checkout_se_ela_estava_provada():
    # Rodada 2 da PR #475 (issue #443): o aborto antes do checkout soltava o watchdog sempre. Numa nova tentativa depois
    # de ROLLBACK TAMBEM FALHOU com a rede caida, o fetch falhava e o finally apagava o sentinela com a venv pela metade.
    codigo = _codigo(_ler("deploy.ps1"))
    # o commit no ar vem do campo `commit` do health (issue #421), comparado nos 7 primeiros caracteres
    health = codigo[codigo.index("function CommitDoHealth"):codigo.index("function NoArEm")]
    assert "ConvertFrom-Json" in health and "$saude.commit" in health and "StatusCode -ne 200" in health
    no_ar = codigo[codigo.index("function NoArEm"):codigo.index("function PinadoLimpo")]
    assert "Substring(0, 7)" in no_ar and "$visto -eq $curto" in no_ar
    limpo = codigo[codigo.index("function PinadoLimpo"):codigo.index("$anterior = (")]
    assert "status --porcelain --untracked-files=no" in limpo
    # a conferencia do inicio: pinado limpo e health no commit do pinado, antes de criar o sentinela
    sentinela = codigo.index("New-Item -ItemType File -Path $pause")
    conferencia = codigo.index("if (PinadoLimpo) { $script:producaoProvada = NoArEm $anterior }")
    assert codigo.index("$anterior = (") < codigo.index("$script:producaoProvada = $false") < conferencia < sentinela
    # o aborto antes do checkout herda a conferencia; o pinado sujo aborta antes do fetch, com mensagem propria
    inicio = codigo.index("$script:soltarWatchdog = $script:producaoProvada")
    sujo = codigo.index("if (-not (PinadoLimpo)) {", sentinela)
    assert sentinela < inicio < sujo < codigo.index("& git -C $AppDir fetch --quiet")
    bloco_sujo = codigo[sujo:codigo.index("& git -C $AppDir fetch --quiet")]
    assert "deploy abortado antes do checkout: diretorio pinado com arquivos alterados" in bloco_sujo
    assert "exit 1" in bloco_sujo and "soltarWatchdog" not in bloco_sujo
    # o finally diz por que manteve
    final = codigo[codigo.index("\n} finally {"):]
    nao_conferida = final[final.index("\n    elseif ("):final.index("\n    else {")]
    assert "-not $script:pinadoMudou -and -not $script:producaoProvada" in nao_conferida
    assert "MANTIDO: a producao nao estava conferida no inicio" in nao_conferida
    assert codigo.index("$script:pinadoMudou = $true") > codigo.rindex(
        "$script:soltarWatchdog = $false", 0, codigo.index("try { Construir $alvo; ConferirInstalacao }"))


def test_deploy_so_solta_com_o_health_no_commit_esperado():
    # Rodada 2 da PR #475 (issue #443): o Saudavel aceitava qualquer processo que respondesse 200. Com o anterior sem a
    # #417, a nova tentativa falhava na conferencia da instalacao, caia na volta do build, e o 200 do processo NOVO no
    # ar fazia o script dizer "producao segue no commit anterior" e soltar o watchdog.
    codigo = _codigo(_ler("deploy.ps1"))
    checkout = codigo.index("try { Construir $alvo; ConferirInstalacao }")
    volta = codigo[checkout:codigo.index("deploy abortado no build E a volta")]
    # o unico Saudavel da volta e' o do religamento depois do ponto da sentinela (issue #478), e o NoArEm vem depois dele
    religa = volta[volta.index("if ($script:sentinelaParou) {"):volta.index("$alterados = ")]
    assert "Saudavel" not in volta.replace(religa, "").replace("NoArEm", "")
    assert volta.index("if ($script:sentinelaParou) {") < volta.index("if (-not (NoArEm $anterior)) { throw ")
    assert volta.index("if (-not (NoArEm $anterior)) { throw ") < volta.index("$script:soltarWatchdog = $true")
    # DEPLOY OK exige o commit novo no health; ROLLBACK OK, o anterior
    assert "if ((SaudavelENovo -ExigirInstalacao) -and (NoArEm $novo)) {" in codigo
    rollback = codigo[codigo.index("ROLLBACK para $anterior"):codigo.index("\n} finally {")]
    assert "$voltou = (SaudavelENovo) -and (NoArEm $anterior)" in rollback
    assert rollback.index("$voltou = (SaudavelENovo) -and (NoArEm $anterior)") < rollback.index("if ($voltou) {")


def test_deploy_distingue_o_sentinela_que_nao_saiu_com_a_producao_provada():
    # Rodada 2 da PR #475 (issue #443): o MANTIDO da remocao que falhou (producao provada) e' outro caso: nao se desfaz
    # o deploy, so' se tira o arquivo.
    codigo = _codigo(_ler("deploy.ps1"))
    final = codigo[codigo.index("\n} finally {"):]
    soltar = final[final.index("if ($script:soltarWatchdog -and $script:producaoProvada -and -not $script:manterSentinela) {"):final.index("\n    elseif (")]
    assert "MANTIDO POR FALHA NA REMOCAO" in soltar and "nao reconstruir nem desfazer o deploy" in soltar
    resto = final[final.index("\n    elseif ("):]
    assert "MANTIDO POR FALHA NA REMOCAO" not in resto
    assert "MANTIDO: a producao nao foi provada depois do deploy" in resto[resto.index("\n    else {"):]


def test_deploy_com_sentinela_de_execucao_anterior_nao_conta_a_producao_como_provada():
    # Rodada extra da PR #475 (issue #443, Critico do revisor-adversarial): depois de uma volta do build que falhou
    # (venv ou dist pela metade, processo antigo no ar respondendo no commit anterior, git status limpo), um novo
    # `deploy.ps1 -Ref <anterior>` com a rede caida contava a producao como provada, o fetch falhava e o finally
    # apagava o sentinela. O sentinela que ja' existia antes da execucao impede a prova do inicio.
    codigo = _codigo(_ler("deploy.ps1"))
    sentinela = codigo.index("New-Item -ItemType File -Path $pause")
    ja_existia = codigo.index("$script:sentinelaJaExistia = Test-Path $pause")
    assert ja_existia < sentinela
    inicio = codigo[ja_existia:sentinela]
    # com o sentinela anterior a conferencia nem roda: producaoProvada fica falso
    assert inicio.index("$script:producaoProvada = $false") < inicio.index("if ($script:sentinelaJaExistia) {") \
        < inicio.index("} elseif (PinadoLimpo) { $script:producaoProvada = NoArEm $anterior }")
    anterior = inicio[inicio.index("if ($script:sentinelaJaExistia) {"):inicio.index("} elseif (PinadoLimpo)")]
    assert "producaoProvada" not in anterior and "ja' existia antes deste deploy" in anterior
    # na volta do build, sem reconstruir o anterior, so' solta se a producao estava provada no inicio
    checkout = codigo.index("try { Construir $alvo; ConferirInstalacao }")
    volta = codigo[checkout:codigo.index("deploy abortado no build E a volta")]
    refez = volta.index("$refez = $true")
    assert volta.index("Reconstruir") < refez
    trava = volta.index("if (-not $refez -and -not $script:producaoProvada) { throw ")
    assert refez < trava < volta.index("$script:soltarWatchdog = $true")
    # o finally diz que o sentinela anterior e' um dos motivos de manter
    final = codigo[codigo.index("\n} finally {"):]
    assert "MANTIDO: a producao nao estava conferida no inicio (sentinela de execucao anterior" in final
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
    assert "$argumentosTarefa = $argumentosDaTarefa" in funcao   # lida por schtasks /Query /XML (#386)
    assert '-match "-SemTls\\b"' in funcao
    assert '. (Join-Path $PSScriptRoot "comum_tls.ps1")' in script
    assert '$certificado = Join-Path $Raiz "segredos\\tls\\cert.pem"' in script
    assert script.count("Invoke-SaudeLocal -Url $urlSaude -Certificado $certificado") == 3   # Saudavel, AvisarSeCopia e CommitDoHealth (#443)
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
    # a funcao comum mata o schtasks que estoura o limite pelo proprio objeto, espera de novo a morte e diz se ele
    # continuou vivo (gate Sol da PR #389, Aviso 2), sem esperar para sempre
    comum = _codigo(_ler("comum_agendador.ps1"))
    agendador = comum[comum.index("function Agendador"):comum.index("function EstadoDaTarefa")]
    assert "$p.WaitForExit($LimiteSegundos * 1000)" in agendador
    estouro = _bloco_do_if(agendador, "if (-not $p.WaitForExit($LimiteSegundos * 1000)) {")
    assert estouro.index("$p.Kill()") < estouro.index("$morreu = $p.WaitForExit(5000)")
    assert "return @{ Estourou = $true; FilhoVivo = (-not $morreu);" in estouro
    assert "Stop-Process" not in agendador
    assert "$vivo = \"; o processo do schtasks /End nao morreu\"" in codigo
    for nome in ("comum_agendador.ps1", "estado_tarefa.ps1"):
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
    # parar o que esta ativo ("Running" e tambem "Queued", que ignoraria o /Run); "Ready" com o processo morto vai
    # direto ao /Run (gate Sol e revisor da PR #389: Queued nao e' parada)
    rodando = _bloco_do_if(codigo, "if (-not (TarefaParada $estado)) {")
    assert '$fim = Agendador @("/End", "/TN", $Tarefa) $LimiteAgendador' in rodando
    falha = rodando[rodando.index("if ($fim.Codigo -ne 0) {"):]
    assert "FALHA ao parar a tarefa, nada iniciado" in falha and "exit 1" in falha
    assert "(segue para o /Run)" not in codigo
    espera = codigo[codigo.index("$parada = $false"):codigo.index('$inicio = Agendador @("/Run"')]
    assert "if (TarefaParada $estado) { $parada = $true; break }" in espera
    assert '$estado -eq "desconhecido") { break }' in espera and '-ne "Running"' not in espera
    assert "continua '$estado' depois da parada -> nada iniciado" in espera and "exit 1" in espera
    assert inicio < leitura < codigo.index("$parada = $false") < codigo.index("try { $orfao = DonoDaPorta }")


def test_estado_da_tarefa_vem_da_com_num_processo_filho_com_tempo_limite():
    # O corpo da COM e' um arquivo estatico (revisor da PR #389: -EncodedCommand a cada leitura, como SYSTEM, tende a ser
    # barrado pelo antivirus como ofuscacao, e o watchdog nunca mais reiniciaria a producao)
    estatico = _codigo(_ler("estado_tarefa.ps1"))
    assert "[Parameter(Mandatory = $true)][string]$Tarefa" in estatico
    assert "New-Object -ComObject Schedule.Service" in estatico and ".GetTask($Tarefa).State" in estatico
    assert "} catch { exit 1 }" in estatico and "exit (100 + $estado)" in estatico
    comum = _codigo(_ler("comum_agendador.ps1"))
    funcao = comum[comum.index("function EstadoDaTarefa"):comum.index("function TarefaParada")]
    assert "EncodedCommand" not in comum
    assert '$arquivo = Join-Path $PSScriptRoot "estado_tarefa.ps1"' in funcao
    assert '"-File", "`"$arquivo`"", "-Tarefa", $Tarefa)' in funcao and '$LimiteSegundos "powershell.exe"' in funcao
    # Unknown (100), erro (o filho sai com 1), estouro ou fora da faixa = desconhecido (gate Sol, Aviso 3); 104 = Running
    assert 'if ($r.Estourou -or $r.Codigo -lt 101 -or $r.Codigo -gt 104) { return "desconhecido" }' in funcao
    assert '@("Disabled", "Queued", "Ready", "Running")[$r.Codigo - 101]' in funcao
    # parada so' e' Ready ou Disabled; Queued e' ativa
    parada = comum[comum.index("function TarefaParada"):]
    assert 'return ($estado -eq "Ready" -or $estado -eq "Disabled")' in parada and "Queued" not in parada


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


def test_deploy_com_sentinela_anterior_ignora_sem_frontend():
    # Gate Sol, rodada extra da PR #475 (Critico 1): a execucao anterior caiu no Vite com o dist pela metade; com
    # -SemFrontend a nova so' refazia a venv, o health 200 no commit certo apagava o sentinela e a tela ficava sem JS.
    codigo = _codigo(_ler("deploy.ps1"))
    trava = codigo.index("if ($script:sentinelaJaExistia -and $SemFrontend) {")
    bloco = codigo[trava:codigo.index("}", trava)]
    assert "$SemFrontend = $false" in bloco
    assert codigo.index("$script:sentinelaJaExistia = Test-Path $pause") < trava
    assert trava < codigo.index("New-Item -ItemType File -Path $pause") < codigo.index("try { Construir $alvo")


def test_deploy_https_confere_a_chave_antes_de_mexer_em_algo():
    # Gate Sol, rodada extra da PR #475 (Critico 2): sem a chave.pem o processo novo e o do rollback nao sobem em HTTPS,
    # e o atual (com a chave carregada) ja' teria sido parado.
    codigo = _codigo(_ler("deploy.ps1"))
    assert '$chaveTls = Join-Path $Raiz "segredos\\tls\\chave.pem"' in codigo
    leitura = codigo.index("[System.IO.File]::OpenRead($chaveTls).Dispose()")
    assert "chave do HTTPS ausente ou ilegivel" in codigo[leitura:leitura + 400]
    assert codigo.index("if ($comTls) {") < leitura < codigo.index("New-Item -ItemType File -Path $pause")


def test_deploy_volta_do_build_religa_o_servico_parado_antes_da_trava_do_sentinela_anterior():
    # Gate Sol, rodada extra da PR #475 (Critico 3): com o servico parado para o ponto da sentinela (#478) e o checkout
    # do alvo falhando antes do build, a trava do sentinela anterior lancava antes do Reiniciar e a producao ficava
    # parada. Agora o anterior e' reconstruido (servico parado e producao nao provada), religado e conferido antes.
    codigo = _codigo(_ler("deploy.ps1"))
    checkout = codigo.index("try { Construir $alvo; ConferirInstalacao }")
    volta = codigo[checkout:codigo.index("deploy abortado no build E a volta")]
    condicao = volta.index(
        "if ($atual -ne $anterior -or $script:buildComecou -or ($script:sentinelaParou -and -not $script:producaoProvada)) {")
    religa = volta.index("if ($script:sentinelaParou) {")
    trava = volta.index("if (-not $refez -and -not $script:producaoProvada) { throw ")
    assert condicao < volta.index("Reconstruir", condicao) < religa < volta.index("Reiniciar", religa) < trava
    assert trava < volta.index("$script:soltarWatchdog = $true")


def test_runbook_so_manda_criar_o_sentinela_antes_das_paradas_manuais():
    # Gate Sol, rodada extra da PR #475 (Aviso): o item do watchdog mandava criar o sentinela antes de qualquer deploy,
    # contra o item 4 de "Deploy a partir do Mac"; um sentinela anterior faz a producao nao contar como provada.
    runbook = (SCRIPTS.parent / "docs" / "runbook.md").read_text(encoding="utf-8")
    linha = next(linha for linha in runbook.splitlines() if linha.startswith("- Watchdog: `scripts\\instalar_watchdog.ps1"))
    assert "parada/deploy manual" not in linha
    assert "O `deploy.ps1` cria o próprio sentinela: não crie antes de rodá-lo" in linha
