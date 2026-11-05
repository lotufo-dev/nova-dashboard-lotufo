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
    assert "[int]$Porta = 80" in script
    assert '$url = "http://localhost:$Porta/api/health"' in script
    linha_acao = next(linha for linha in script.splitlines() if "-Argument" in linha)
    assert '-Url "{1}"' in linha_acao and "$url" in linha_acao
    # o watchdog.ps1 precisa aceitar -Url, senao o argumento cai no chao
    assert re.search(r"\[string\]\$Url\s*=", _ler("watchdog.ps1"))


def test_deploy_usa_a_porta_na_saude_no_dono_da_porta_e_nas_mensagens():
    script = _ler("deploy.ps1")
    assert "localhost/api/health" not in script
    assert 'http://localhost:$Porta/api/health' in script
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
    assert "return 80" in script  # tarefa sem -Porta = producao de hoje
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
