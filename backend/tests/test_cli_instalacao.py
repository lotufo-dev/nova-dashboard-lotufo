"""`python -m app.cli instalacao gerar-chave|assinar` (issue #417): o dono gera o par no Mac e assina o arquivo que o
servidor confere na subida. O par e' gerado dentro do teste; nada de chave fixa no repositorio."""
import os
import stat
import sys

import pytest
from cryptography.hazmat.primitives import serialization

from app import cli, instalacao

pytestmark = pytest.mark.instalacao_real


def _gerar(tmp_path, capsys):
    assert cli.main(["instalacao", "gerar-chave", "--saida", str(tmp_path / "chaves")]) == 0
    saida = capsys.readouterr().out
    return tmp_path / "chaves" / "instalacao-privada.pem", tmp_path / "chaves" / "instalacao-publica.pem", saida


def test_gerar_chave_grava_o_par_e_mostra_a_publica(tmp_path, capsys):
    privada, publica, saida = _gerar(tmp_path, capsys)
    texto_publica = publica.read_text(encoding="ascii")
    assert texto_publica.startswith("-----BEGIN PUBLIC KEY-----")
    assert texto_publica.strip() in saida                       # para colar na issue
    assert "PRIVATE" not in saida                                # a privada nunca sai na tela
    chave = serialization.load_pem_private_key(privada.read_bytes(), password=None)
    assert chave.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo).decode() == texto_publica
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(privada).st_mode) == 0o600


def test_gerar_chave_nao_sobrescreve(tmp_path, capsys):
    privada, _, _ = _gerar(tmp_path, capsys)
    antes = privada.read_bytes()
    assert cli.main(["instalacao", "gerar-chave", "--saida", str(tmp_path / "chaves")]) == 1
    assert "já existe" in capsys.readouterr().out
    assert privada.read_bytes() == antes


def test_assinar_produz_arquivo_que_a_verificacao_aceita(tmp_path, capsys, monkeypatch):
    privada, publica, _ = _gerar(tmp_path, capsys)
    monkeypatch.setattr(instalacao, "CHAVE_PUBLICA", publica.read_text(encoding="ascii"))
    arquivo = tmp_path / "instalacao.json"
    assert cli.main(["instalacao", "assinar", "--chave", str(privada), "--maquina", "MAQUINA-TESTE",
                     "--saida", str(arquivo)]) == 0
    saida = capsys.readouterr().out
    assert "MAQUINA-TESTE" in saida and "AVISO" not in saida
    assert instalacao.conferir_arquivo(arquivo.read_bytes(), "MAQUINA-TESTE") is None
    assert instalacao.conferir_arquivo(arquivo.read_bytes(), "OUTRA") == "maquina"
    # o caminho completo: com o arquivo no lugar padrao e o nome da maquina, o servidor sobe autorizado
    monkeypatch.delenv("DASH_DEV", raising=False)
    monkeypatch.setattr(instalacao, "maquina_atual", lambda: "MAQUINA-TESTE")
    monkeypatch.setenv("DASH_INSTALACAO_ARQUIVO", str(arquivo))
    assert instalacao.verificar() == {"instalacao": "autorizada", "motivo": None}


def test_assinar_recusa_chave_que_nao_e_a_embutida(tmp_path, capsys):
    """O servidor recusaria o arquivo: nada e' gravado, para ninguem copiar para a VM um arquivo que derruba o deploy."""
    privada, _, _ = _gerar(tmp_path, capsys)
    arquivo = tmp_path / "instalacao.json"
    assert cli.main(["instalacao", "assinar", "--chave", str(privada), "--maquina", "MAQUINA-TESTE",
                     "--saida", str(arquivo)]) == 1
    assert "não é a que o código confere" in capsys.readouterr().out
    assert not arquivo.exists()


def test_assinar_nunca_grava_por_cima(tmp_path, capsys, monkeypatch):
    """--saida apontando, por engano, para a propria chave privada: a chave fica intacta."""
    privada, publica, _ = _gerar(tmp_path, capsys)
    monkeypatch.setattr(instalacao, "CHAVE_PUBLICA", publica.read_text(encoding="ascii"))
    antes = privada.read_bytes()
    for alvo in (privada, publica):
        assert cli.main(["instalacao", "assinar", "--chave", str(privada), "--maquina", "MAQUINA-TESTE",
                         "--saida", str(alvo)]) == 1
        assert "já existe" in capsys.readouterr().out
    assert privada.read_bytes() == antes


def test_conciliacao_antiga_nao_fala_com_o_rm_numa_copia(monkeypatch, capsys):
    from app import rm

    def nao_chamar():
        raise AssertionError("a copia chamou o RM")

    monkeypatch.setattr(rm, "de_ambiente", nao_chamar)
    monkeypatch.setattr(instalacao, "_estado", {"instalacao": "nao-autorizada", "motivo": "maquina"})
    assert cli.main(["conciliacao", "antiga", "--usuario", "admin@lotufo.com", "--ensaio"]) == 1
    assert "Sincronização desligada: instalação não autorizada." in capsys.readouterr().out


def test_assinar_recusa_chave_ausente_ou_que_nao_e_ed25519(tmp_path, capsys):
    arquivo = tmp_path / "instalacao.json"
    assert cli.main(["instalacao", "assinar", "--chave", str(tmp_path / "nada.pem"), "--maquina", "M",
                     "--saida", str(arquivo)]) == 1
    assert "não encontrada" in capsys.readouterr().out
    falsa = tmp_path / "falsa.pem"
    falsa.write_text("isto nao e chave", encoding="ascii")
    assert cli.main(["instalacao", "assinar", "--chave", str(falsa), "--maquina", "M", "--saida", str(arquivo)]) == 1
    assert "chave privada Ed25519" in capsys.readouterr().out
    assert not arquivo.exists()


def test_assinar_recusa_maquina_em_branco(tmp_path, capsys, monkeypatch):
    privada, publica, _ = _gerar(tmp_path, capsys)
    monkeypatch.setattr(instalacao, "CHAVE_PUBLICA", publica.read_text(encoding="ascii"))
    arquivo = tmp_path / "instalacao.json"
    assert cli.main(["instalacao", "assinar", "--chave", str(privada), "--maquina", "  ",
                     "--saida", str(arquivo)]) == 1
    assert "nome da máquina" in capsys.readouterr().out
    assert not arquivo.exists()


# --- `instalacao verificar`: o deploy confere o arquivo com o codigo novo antes de trocar o processo --------------

def _assinado(tmp_path, capsys, monkeypatch, maquina="MAQUINA-TESTE"):
    privada, publica, _ = _gerar(tmp_path, capsys)
    monkeypatch.setattr(instalacao, "CHAVE_PUBLICA", publica.read_text(encoding="ascii"))
    monkeypatch.setattr(instalacao, "maquina_atual", lambda: "MAQUINA-TESTE")
    arquivo = tmp_path / "segredos" / "instalacao.json"
    assert cli.main(["instalacao", "assinar", "--chave", str(privada), "--maquina", maquina,
                     "--saida", str(arquivo)]) == 0
    capsys.readouterr()
    return arquivo


def test_verificar_autorizada_sai_com_zero_sem_caminho_nem_maquina(tmp_path, capsys, monkeypatch):
    arquivo = _assinado(tmp_path, capsys, monkeypatch)
    assert cli.main(["instalacao", "verificar", "--arquivo", str(arquivo)]) == 0
    saida = capsys.readouterr().out
    assert saida.strip() == "Instalação autorizada para esta máquina."
    assert str(tmp_path) not in saida and "MAQUINA-TESTE" not in saida


@pytest.mark.parametrize("caso, motivo", [("ausente", "ausente"), ("outra", "maquina"), ("alterado", "assinatura")])
def test_verificar_nao_autorizada_sai_com_um_e_o_motivo(tmp_path, capsys, monkeypatch, caso, motivo):
    arquivo = _assinado(tmp_path, capsys, monkeypatch, maquina="OUTRA" if caso == "outra" else "MAQUINA-TESTE")
    if caso == "ausente":
        arquivo.unlink()
    elif caso == "alterado":
        arquivo.write_bytes(arquivo.read_bytes().replace(b"MAQUINA-TESTE", b"MAQUINA-TESTF"))
    assert cli.main(["instalacao", "verificar", "--arquivo", str(arquivo)]) == 1
    assert capsys.readouterr().out.strip() == f"Instalação NÃO autorizada (motivo: {motivo})."


def test_verificar_arquivo_que_nao_se_le_diz_ilegivel_sem_o_caminho(tmp_path, capsys, caplog, monkeypatch):
    """Revisor da PR #437: com o arquivo la' e sem leitura, `ausente` mandaria copiar de novo; e a mensagem do sistema
    trazia o caminho para a saida do deploy."""
    arquivo = _assinado(tmp_path, capsys, monkeypatch)
    arquivo.unlink()
    arquivo.mkdir()                             # uma pasta no lugar do arquivo: existe e nao se le
    assert cli.main(["instalacao", "verificar", "--arquivo", str(arquivo)]) == 1
    saida = capsys.readouterr()
    assert saida.out.strip() == "Instalação NÃO autorizada (motivo: ilegivel)."
    for texto in (saida.out, saida.err, caplog.text):
        assert str(tmp_path) not in texto and "instalacao.json" not in texto


def test_verificar_nao_tem_o_atalho_do_dev(tmp_path, capsys, monkeypatch):
    """Sessao de deploy com DASH_DEV=1 herdado nao passa sem o arquivo."""
    monkeypatch.setenv("DASH_DEV", "1")
    assert cli.main(["instalacao", "verificar", "--arquivo", str(tmp_path / "nao-existe.json")]) == 1
    assert "motivo: ausente" in capsys.readouterr().out


def test_verificar_sem_arquivo_usa_o_caminho_da_subida(tmp_path, capsys, monkeypatch):
    arquivo = _assinado(tmp_path, capsys, monkeypatch)
    monkeypatch.delenv("DASH_INSTALACAO_ARQUIVO", raising=False)
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "dados" / "dashboard.db"))
    assert arquivo == tmp_path / "segredos" / "instalacao.json"
    assert cli.main(["instalacao", "verificar"]) == 0


def test_gerar_chave_exige_saida(capsys):
    assert cli.main(["instalacao", "gerar-chave"]) == 1
    assert "exige --saida" in capsys.readouterr().out
