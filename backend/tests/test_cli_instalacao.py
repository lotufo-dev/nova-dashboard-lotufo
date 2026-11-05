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
