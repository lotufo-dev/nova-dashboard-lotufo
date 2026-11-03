# Os scripts de producao (scripts\*.ps1) rodam so no servidor Windows; aqui eles sao lidos como texto, no estilo
# de test_producao_nao_aceita_x_forwarded_for em test_auth.py. Issue #361 (porta configuravel nos scripts de
# producao): a VM nova tem a 80 ocupada pelo IIS, entao a porta vem do parametro -Porta, e o padrao continua 80.
import pathlib
import re

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"


def _ler(nome):
    return (SCRIPTS / nome).read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("nome", ["rodar_producao.ps1", "instalar_autostart.ps1", "instalar_watchdog.ps1", "deploy.ps1"])
def test_script_declara_o_parametro_porta(nome):
    assert re.search(r"\[int\]\$Porta\s*=\s*\d+", _ler(nome)), f"{nome} sem [int]$Porta no param()"


def test_rodar_producao_usa_a_porta_do_parametro():
    script = _ler("rodar_producao.ps1")
    comandos = [linha for linha in script.splitlines() if "-m uvicorn" in linha]
    assert len(comandos) == 2
    assert "--port 80" not in script and "--port 8443" not in script
    assert script.count("--port $Porta") == 2
    # sem -Porta nada muda: 80 em HTTP (-SemTls) e 8443 com TLS
    assert "[int]$Porta = 0" in script
    assert re.search(r"if \(\$SemTls\) \{ \$Porta = 80 \} else \{ \$Porta = 8443 \}", script)


def test_rodar_producao_mantem_no_proxy_headers():
    # #3 (limite de login por origem): a porta nao pode ter levado a opcao junto
    comandos = [linha for linha in _ler("rodar_producao.ps1").splitlines() if "-m uvicorn" in linha]
    assert all("--no-proxy-headers" in c for c in comandos)


def test_autostart_repassa_a_porta_so_quando_informada():
    script = _ler("instalar_autostart.ps1")
    assert "[int]$Porta = 0" in script
    assert re.search(r"if \(\$Porta -ne 0\) \{ \$argumentos \+= \" -Porta \$Porta\" \}", script)


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
    assert "[int]$Porta = 80" in script
    assert "localhost/api/health" not in script
    assert 'http://localhost:$Porta/api/health' in script
    assert "LocalPort 80" not in script
    assert "-LocalPort $Porta" in script
    assert not re.search(r"porta 80\b", script), "mensagem ainda cita a porta 80 fixa"


def test_deploy_fica_so_em_ascii_sem_bom():
    # cabecalho do deploy.ps1: o PowerShell 5.1 le sem BOM como ANSI e acento quebra o parse
    bruto = (SCRIPTS / "deploy.ps1").read_bytes()
    assert not bruto.startswith(b"\xef\xbb\xbf")
    assert bruto.isascii()
