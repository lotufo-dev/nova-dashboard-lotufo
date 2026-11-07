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
    soltar = final[final.index("if ($script:soltarWatchdog) {"):final.index("\n    elseif (")]
    assert "Remove-Item $pause" in soltar
    assert "MANTIDO" in final
    # comeca falso, antes de criar o sentinela
    assert codigo.index("$script:soltarWatchdog = $false") < codigo.index("New-Item -ItemType File -Path $pause")
    # os unicos pontos que soltam: antes do checkout do alvo (so' com a producao provada no inicio, rodada 2), a volta
    # do build que deu certo, DEPLOY OK e ROLLBACK OK
    soltas = [m.start() for m in re.finditer(r"\$script:soltarWatchdog = \$true", codigo)]
    assert len(soltas) == 3
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
    assert trava < codigo.index("$novo = (") and "Reiniciar" in principal and "soltarWatchdog" not in principal
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
    condicao = volta.index("if ($atual -ne $anterior -or $script:buildComecou) {")
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
    soltar = final[final.index("if ($script:soltarWatchdog) {"):final.index("\n    elseif (")]
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
    soltar = final[final.index("if ($script:soltarWatchdog) {"):final.index("\n    elseif (")]
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
    assert 'Get-ScheduledTask -TaskName "DashboardLotufo"' in funcao
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
    # Issue #480: Stop-ScheduledTask nao mata o uvicorn (incidente de 2026-09-21); o orfao segura a porta, a instancia
    # nova morre com WinError 10048 e o watchdog repetia o Start a cada 3 minutos, para sempre
    codigo = _codigo(_ler("watchdog.ps1"))
    linhas = [linha.strip() for linha in codigo.splitlines()]
    parar = codigo.index("$parada = $false")
    pausa_porta = codigo.index('SairSePausado "antes de conferir a porta"')
    consulta = codigo.index("try { $orfao = DonoDaPorta }")
    pausa_matar = codigo.index('SairSePausado "antes de encerrar o orfao"')
    reconfere = codigo.index("try { $agora = DonoDaPorta }")
    matar = codigo.index("Stop-Process -Id $orfao.ProcessId -Force")
    entre = codigo.index('SairSePausado "entre a parada e o inicio"')
    iniciar = codigo.index("Start-ScheduledTask -TaskName")
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
