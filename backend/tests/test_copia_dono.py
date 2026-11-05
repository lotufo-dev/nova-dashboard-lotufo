"""Copia cifrada semanal para a chave do dono (issue #419)."""
import datetime
import io
import os
import sqlite3
import tarfile
import time

import pytest

pyrage = pytest.importorskip("pyrage")
from pyrage import x25519

from app import backup, copia_dono, tempo


@pytest.fixture
def dono():
    return x25519.Identity.generate()


@pytest.fixture
def raiz(tmp_path, monkeypatch, dono):
    monkeypatch.delenv("DASH_CHAVE_PUBLICA_DONO", raising=False)
    monkeypatch.delenv("DASH_CADASTRO_DIR", raising=False)
    (tmp_path / "segredos").mkdir()
    (tmp_path / "segredos" / "chave-publica-dono.txt").write_text(f"# chave\n{dono.to_public()}\n", encoding="utf-8")
    (tmp_path / "segredos" / "token.txt").write_text("SEGREDO-UNICO-123", encoding="utf-8")
    (tmp_path / "cadastro").mkdir()
    (tmp_path / "cadastro" / "obras.yaml").write_text("obras: []\n", encoding="utf-8")
    (tmp_path / "cadastro" / ".git").mkdir()
    (tmp_path / "cadastro" / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    (tmp_path / "dados").mkdir()
    origem = tmp_path / "dados" / "dashboard.db"
    conn = sqlite3.connect(origem)
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()
    backup.criar_snapshot(origem, tmp_path / "dados" / "backups")
    return tmp_path


def _pasta(raiz):
    return raiz / "dados" / "backups"


def _abrir(arquivo, dono):
    return tarfile.open(fileobj=io.BytesIO(pyrage.decrypt(arquivo.read_bytes(), [dono])))


def test_gera_arquivo_cifrado_com_sha256_e_decifra_com_a_privada(raiz, dono, tmp_path):
    destino = copia_dono.gerar(raiz, _pasta(raiz))
    assert destino.parent == _pasta(raiz) / "dono" and destino.name.endswith(".tar.age")
    assert (destino.parent / f"{destino.name}.sha256").read_text().split()[0] == backup._sha256(destino)
    tar = _abrir(destino, dono)
    nomes = tar.getnames()
    assert "segredos/token.txt" in nomes and "cadastro/obras.yaml" in nomes
    assert not any(".git" in n.split("/") for n in nomes)
    banco = [n for n in nomes if n.startswith("banco/dashboard-") and n.endswith(".db")]
    assert len(banco) == 1
    saida = tmp_path / "restaurado.db"
    saida.write_bytes(tar.extractfile(banco[0]).read())
    conn = sqlite3.connect(saida)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 42
    conn.close()


def test_nada_em_claro_no_disco(raiz):
    destino = copia_dono.gerar(raiz, _pasta(raiz))
    assert b"SEGREDO-UNICO-123" not in destino.read_bytes()
    assert not list(raiz.rglob("*.tar")) and not list(raiz.rglob("*.tmp"))
    assert sorted(a.name for a in destino.parent.iterdir()) == sorted([destino.name, f"{destino.name}.sha256"])


def test_a_quinta_copia_apaga_a_mais_antiga(raiz):
    pasta = _pasta(raiz) / "dono"
    pasta.mkdir()
    for i in range(4):
        (pasta / f"dashboard-dono-20260101-00000{i}.tar.age").write_bytes(b"x")
        (pasta / f"dashboard-dono-20260101-00000{i}.tar.age.sha256").write_text("x")
    nova = copia_dono.gerar(raiz, _pasta(raiz))
    restantes = sorted(a.name for a in pasta.glob("*.tar.age"))
    assert len(restantes) == 4 and nova.name in restantes
    assert "dashboard-dono-20260101-000000.tar.age" not in restantes
    assert not (pasta / "dashboard-dono-20260101-000000.tar.age.sha256").exists()


def test_sem_chave_publica_nada_e_gerado(raiz):
    (raiz / "segredos" / "chave-publica-dono.txt").unlink()
    with pytest.raises(copia_dono.NaoConfigurada):
        copia_dono.gerar(raiz, _pasta(raiz))
    assert not (_pasta(raiz) / "dono").exists()
    assert copia_dono.configurada(raiz) is False


def test_chave_privada_e_recusada(raiz, dono):
    (raiz / "segredos" / "chave-publica-dono.txt").write_text(f"{dono}\n", encoding="utf-8")
    with pytest.raises(copia_dono.CopiaDonoErro, match="chave privada"):
        copia_dono.gerar(raiz, _pasta(raiz))
    assert not (_pasta(raiz) / "dono").exists()


def test_variavel_sobrescreve_o_arquivo_da_chave(raiz, tmp_path, monkeypatch):
    outra = x25519.Identity.generate()
    arq = tmp_path / "outra.txt"
    arq.write_text(str(outra.to_public()), encoding="utf-8")
    monkeypatch.setenv("DASH_CHAVE_PUBLICA_DONO", str(arq))
    destino = copia_dono.gerar(raiz, _pasta(raiz))
    assert _abrir(destino, outra).getnames()


def test_rodada_semanal_so_depois_de_7_dias(raiz):
    copia_dono.rodada_semanal(raiz, _pasta(raiz))
    primeira = copia_dono.copias(_pasta(raiz))
    assert len(primeira) == 1
    copia_dono.rodada_semanal(raiz, _pasta(raiz))
    assert copia_dono.copias(_pasta(raiz)) == primeira  # menos de 7 dias: nao gera outra
    velho = time.time() - 8 * 86400
    os.utime(primeira[0], (velho, velho))
    time.sleep(1.1)  # o nome tem resolucao de segundos
    copia_dono.rodada_semanal(raiz, _pasta(raiz))
    assert len(copia_dono.copias(_pasta(raiz))) == 2


def test_rodada_semanal_sem_chave_nao_faz_nada_nem_acusa_erro(raiz):
    (raiz / "segredos" / "chave-publica-dono.txt").unlink()
    backup.ESTADO["ultima_copia_dono_erro"] = None
    copia_dono.rodada_semanal(raiz, _pasta(raiz))
    assert not (_pasta(raiz) / "dono").exists() and backup.ESTADO["ultima_copia_dono_erro"] is None


def test_atrasada_acima_de_8_dias(raiz):
    agora = tempo.agora_utc()
    assert copia_dono.atrasada(_pasta(raiz), agora) is True  # nunca houve
    copia_dono.gerar(raiz, _pasta(raiz))
    assert copia_dono.atrasada(_pasta(raiz), agora) is False
    assert copia_dono.atrasada(_pasta(raiz), agora + datetime.timedelta(days=9)) is True
    assert backup.situacao(_pasta(raiz), False, agora)["ultima_copia_dono"]
