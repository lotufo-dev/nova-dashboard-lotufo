"""Instalacao assinada (issue #417): fora do servidor oficial a dashboard sobe em modo copia, sem e-mail e sem RM.

Os testes geram o proprio par de chaves e trocam a chave publica embutida por ela; a do dono so' aparece no teste
que confere que ela carrega e recusa o que outra chave assinou. O conftest faz todo teste rodar como `dev`; quem
confere o arquivo de verdade marca `instalacao_real`."""
import os
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi.testclient import TestClient

from app import instalacao

MAQUINA = "MAQUINA-TESTE"
COPIA = {"instalacao": "nao-autorizada", "motivo": "ausente"}


def _publica(privada) -> str:
    return privada.public_key().public_bytes(serialization.Encoding.PEM,
                                              serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


@pytest.fixture
def chave(monkeypatch):
    """Par gerado no teste: o codigo passa a conferir contra a publica dele."""
    privada = Ed25519PrivateKey.generate()
    monkeypatch.setattr(instalacao, "CHAVE_PUBLICA", _publica(privada))
    return privada


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """Fora do dev, nesta maquina, com o banco em <raiz>/dados: o arquivo e' procurado em <raiz>/segredos."""
    monkeypatch.delenv("DASH_DEV", raising=False)
    monkeypatch.delenv("DASH_INSTALACAO_ARQUIVO", raising=False)
    monkeypatch.setattr(instalacao, "maquina_atual", lambda: MAQUINA)
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "dados" / "dashboard.db"))
    return tmp_path / "segredos" / "instalacao.json"


def _gravar(caminho: Path, conteudo: bytes) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo)
    return caminho


# --- conferencia do arquivo ------------------------------------------------------------------------------------

@pytest.mark.instalacao_real
def test_arquivo_valido_para_a_maquina_autoriza(chave, ambiente):
    _gravar(ambiente, instalacao.assinar(chave, MAQUINA))
    assert instalacao.verificar() == {"instalacao": "autorizada", "motivo": None}


@pytest.mark.instalacao_real
def test_nome_da_maquina_sem_diferenca_de_maiusculas(chave, ambiente):
    # o Windows guarda o COMPUTERNAME em maiusculas; quem assina pode digitar em minusculas
    _gravar(ambiente, instalacao.assinar(chave, "maquina-teste"))
    assert instalacao.verificar()["instalacao"] == "autorizada"


def test_nome_da_maquina_vem_do_sistema_e_nao_da_variavel(monkeypatch):
    """Quem sobe a copia troca o COMPUTERNAME com um comando; o nome da maquina vem do sistema."""
    monkeypatch.setenv("COMPUTERNAME", "NOME-FALSO-DA-COPIA")
    assert instalacao.maquina_atual() not in ("", "NOME-FALSO-DA-COPIA")


class _Kernel32Falso:
    """No lugar do kernel32 do Windows: devolve o nome pela API, como o GetComputerNameW."""

    def __init__(self, nome, ok=True):
        self.nome, self.ok, self.chamadas = nome, ok, 0

    def GetComputerNameW(self, buffer, tamanho):
        self.chamadas += 1
        if not self.ok:
            return 0
        buffer.value = self.nome
        return 1


def _windows_falso(monkeypatch, kernel32):
    import ctypes
    import sys
    from types import SimpleNamespace
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel32), raising=False)


def test_no_windows_o_nome_vem_da_api_e_nao_da_variavel(monkeypatch):
    kernel32 = _Kernel32Falso("MAQUINA-DA-API")
    _windows_falso(monkeypatch, kernel32)
    monkeypatch.setenv("COMPUTERNAME", "NOME-FALSO-DA-COPIA")
    assert instalacao.maquina_atual() == "MAQUINA-DA-API"
    assert kernel32.chamadas == 1


def test_no_windows_sem_resposta_da_api_cai_no_nome_de_rede(monkeypatch):
    import platform
    _windows_falso(monkeypatch, _Kernel32Falso("", ok=False))
    monkeypatch.setenv("COMPUTERNAME", "NOME-FALSO-DA-COPIA")
    assert instalacao.maquina_atual() == platform.node()


@pytest.mark.instalacao_real
def test_sem_arquivo_e_copia_por_ausencia(chave, ambiente):
    assert instalacao.verificar() == {"instalacao": "nao-autorizada", "motivo": "ausente"}


@pytest.mark.instalacao_real
def test_arquivo_que_existe_e_nao_se_le_tem_motivo_proprio(chave, ambiente, caplog):
    """Pasta no lugar do arquivo (ou ACL que barra a leitura): `ilegivel`, nao `ausente`, para ninguem copiar de novo
    um arquivo que ja' esta' la'; o log leva so' o tipo do erro, sem o caminho."""
    ambiente.mkdir(parents=True)
    assert instalacao.verificar() == {"instalacao": "nao-autorizada", "motivo": "ilegivel"}
    assert "segredos" not in caplog.text and str(ambiente) not in caplog.text
    assert "nao se le" in caplog.text


@pytest.mark.instalacao_real
@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="chmod 000 nao barra o Windows nem o root")
def test_arquivo_sem_permissao_de_leitura_e_ilegivel(chave, ambiente):
    _gravar(ambiente, instalacao.assinar(chave, MAQUINA))
    ambiente.chmod(0)
    try:
        assert instalacao.verificar() == {"instalacao": "nao-autorizada", "motivo": "ilegivel"}
    finally:
        ambiente.chmod(0o600)


@pytest.mark.instalacao_real
def test_variavel_troca_o_caminho(chave, ambiente, tmp_path, monkeypatch):
    _gravar(ambiente, instalacao.assinar(chave, MAQUINA))
    outro = _gravar(tmp_path / "outro" / "inst.json", instalacao.assinar(chave, MAQUINA))
    monkeypatch.setenv("DASH_INSTALACAO_ARQUIVO", str(tmp_path / "nao-existe.json"))
    assert instalacao.verificar() == {"instalacao": "nao-autorizada", "motivo": "ausente"}
    monkeypatch.setenv("DASH_INSTALACAO_ARQUIVO", str(outro))
    assert instalacao.verificar()["instalacao"] == "autorizada"


@pytest.mark.instalacao_real
def test_sem_banco_nem_variavel_nao_ha_onde_procurar(chave, monkeypatch):
    monkeypatch.delenv("DASH_DEV", raising=False)
    monkeypatch.delenv("DASH_INSTALACAO_ARQUIVO", raising=False)
    monkeypatch.delenv("DASH_DB_PATH", raising=False)
    assert instalacao.verificar() == {"instalacao": "nao-autorizada", "motivo": "ausente"}


@pytest.mark.instalacao_real
def test_assinado_por_outra_chave(chave, ambiente):
    _gravar(ambiente, instalacao.assinar(Ed25519PrivateKey.generate(), MAQUINA))
    assert instalacao.verificar() == {"instalacao": "nao-autorizada", "motivo": "assinatura"}


@pytest.mark.instalacao_real
def test_assinado_para_outra_maquina(chave, ambiente):
    _gravar(ambiente, instalacao.assinar(chave, "OUTRA-MAQUINA"))
    assert instalacao.verificar() == {"instalacao": "nao-autorizada", "motivo": "maquina"}


@pytest.mark.instalacao_real
def test_outra_chave_e_outra_maquina_acusa_a_assinatura(chave, ambiente):
    _gravar(ambiente, instalacao.assinar(Ed25519PrivateKey.generate(), "OUTRA-MAQUINA"))
    assert instalacao.verificar()["motivo"] == "assinatura"


@pytest.mark.instalacao_real
def test_qualquer_byte_trocado_recusa(chave, ambiente):
    """Inclusive o que o JSON aceitaria igual (espaco, escape, o fim de linha) e o bit que o base64 ignora."""
    bruto = instalacao.assinar(chave, MAQUINA)
    _gravar(ambiente, bruto)
    assert instalacao.verificar()["instalacao"] == "autorizada"
    for i in range(len(bruto)):
        for mascara in (0x01, 0x20):
            trocado = bytearray(bruto)
            trocado[i] ^= mascara
            _gravar(ambiente, bytes(trocado))
            assert instalacao.verificar() == {"instalacao": "nao-autorizada", "motivo": "assinatura"}, \
                f"byte {i} trocado ({mascara:#x}) passou"


@pytest.mark.instalacao_real
@pytest.mark.parametrize("conteudo", [b"", b"{}", b"[1, 2]", b"nao e json", "{\"maquina\": \"ç\"".encode("utf-8"),
                                      b"\xff\xfe", b"x" * 100_000])
def test_arquivo_ilegivel_acusa_a_assinatura(chave, ambiente, conteudo):
    _gravar(ambiente, conteudo)
    assert instalacao.verificar() == {"instalacao": "nao-autorizada", "motivo": "assinatura"}


@pytest.mark.instalacao_real
def test_arquivo_reformatado_recusa(chave, ambiente):
    """Mesmo conteudo com outro espacamento tambem recusa: o arquivo vale como saiu do `assinar`."""
    import json
    doc = json.loads(instalacao.assinar(chave, MAQUINA))
    _gravar(ambiente, json.dumps(doc, indent=2).encode("utf-8"))
    assert instalacao.verificar()["motivo"] == "assinatura"


@pytest.mark.instalacao_real
def test_fim_de_linha_do_windows_e_aceito(chave, ambiente):
    bruto = instalacao.assinar(chave, MAQUINA)
    _gravar(ambiente, bruto.rstrip(b"\n") + b"\r\n")
    assert instalacao.verificar()["instalacao"] == "autorizada"
    _gravar(ambiente, bruto.rstrip(b"\n"))
    assert instalacao.verificar()["instalacao"] == "autorizada"


@pytest.mark.instalacao_real
def test_modo_dev_libera_sem_arquivo(ambiente, monkeypatch):
    monkeypatch.setenv("DASH_DEV", "1")
    assert instalacao.verificar() == {"instalacao": "dev", "motivo": None}


@pytest.mark.instalacao_real
def test_chave_embutida_e_a_ed25519_do_dono(ambiente):
    """Sem o fixture `chave`: confere contra a chave publica embutida (a do comentario do dono na issue #417)."""
    publica = serialization.load_pem_public_key(instalacao.CHAVE_PUBLICA.encode("ascii"))
    assert isinstance(publica, Ed25519PublicKey)
    assert "PRIVATE" not in instalacao.CHAVE_PUBLICA
    _gravar(ambiente, instalacao.assinar(Ed25519PrivateKey.generate(), MAQUINA))
    assert instalacao.verificar()["motivo"] == "assinatura"


def test_testes_rodam_como_dev(client):
    """O conftest: nenhum teste depende do arquivo, e nada fica desligado."""
    assert instalacao.estado() == {"instalacao": "dev", "motivo": None}
    instalacao.exigir_envio()                   # nao levanta
    assert instalacao.ligada()


# --- na subida: o que liga e o que desliga ----------------------------------------------------------------------

def _subir(monkeypatch, tmp_path, jobs=True):
    from app import alertas_seguranca, backup, cobranca_certidoes, sincronizacao_rm
    from app.main import create_app
    chamadas = []
    monkeypatch.setattr(backup, "agendar_backup_horario",
                        lambda banco, local, externa: chamadas.append(("backup", externa)))
    monkeypatch.setattr(sincronizacao_rm, "agendar", lambda: chamadas.append(("rm",)))
    monkeypatch.setattr(cobranca_certidoes, "agendar", lambda: chamadas.append(("cobranca",)))
    monkeypatch.setattr(alertas_seguranca, "agendar", lambda: chamadas.append(("alertas",)))
    # Issue #457: as conferencias locais (#421, #422, #423) subiam threads de verdade que seguiam vivas no worker e
    # gravavam o estado delas no meio dos testes seguintes
    from app import integridade, seguranca, sentinela
    for modulo in (integridade, seguranca, sentinela):
        monkeypatch.setattr(modulo, "agendar", lambda *a, **k: None)
    monkeypatch.setenv("DASH_BACKUP_EXTERNO", str(tmp_path / "externo"))
    monkeypatch.setenv("DASH_SEM_FRONTEND", "1")
    if jobs:
        monkeypatch.delenv("DASH_SEM_JOBS", raising=False)
    else:
        monkeypatch.setenv("DASH_SEM_JOBS", "1")
    return create_app(), chamadas


@pytest.mark.instalacao_real
def test_autorizada_agenda_tudo(chave, ambiente, monkeypatch, tmp_path):
    _gravar(ambiente, instalacao.assinar(chave, MAQUINA))
    _, chamadas = _subir(monkeypatch, tmp_path)
    assert chamadas == [("backup", tmp_path / "externo"), ("rm",), ("cobranca",), ("alertas",)]


@pytest.mark.instalacao_real
def test_copia_so_agenda_o_backup_local(chave, ambiente, monkeypatch, tmp_path):
    """Sem RM, sem cobranca de certidoes, sem alertas de seguranca por e-mail (#424) e sem a copia externa (que sai
    da maquina); o backup local continua."""
    _, chamadas = _subir(monkeypatch, tmp_path)
    assert chamadas == [("backup", None)]
    assert instalacao.estado() == COPIA


@pytest.mark.instalacao_real
def test_a_conferencia_e_feita_na_subida(chave, ambiente, monkeypatch, tmp_path):
    """O arquivo posto depois da subida so' vale no proximo reinicio."""
    _subir(monkeypatch, tmp_path, jobs=False)
    assert instalacao.estado() == COPIA
    _gravar(ambiente, instalacao.assinar(chave, MAQUINA))
    assert instalacao.estado() == COPIA
    _subir(monkeypatch, tmp_path, jobs=False)
    assert instalacao.estado() == {"instalacao": "autorizada", "motivo": None}


@pytest.mark.instalacao_real
def test_copia_continua_com_login_e_leitura(chave, ambiente, monkeypatch, tmp_path):
    from app import auth, db
    app, _ = _subir(monkeypatch, tmp_path, jobs=False)
    conn = db.get_conn()
    auth.criar_usuario(conn, "Admin", "admin@lotufo.com", "senha-forte-123", "admin")
    conn.close()
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"email": "admin@lotufo.com", "senha": "senha-forte-123"})
        assert r.status_code == 200, r.text
        c.cookies.set("sessao", r.cookies.get("sessao") or c.cookies.get("sessao"))
        assert c.get("/api/auth/eu").status_code == 200
        assert c.get("/api/contratos").status_code == 200


# --- recusas na API ---------------------------------------------------------------------------------------------

def _rm_simulado(tmp_path, monkeypatch):
    from app import rm
    pasta = tmp_path / "rm"
    pasta.mkdir()
    (pasta / f"{rm.CONSULTA_NF}.json").write_text("[]", encoding="utf-8")
    (pasta / f"{rm.CONSULTA_BAIXA}.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("DASH_RM_SIMULADOR", str(pasta))


def test_saude_mostra_a_copia_externa_desligada_no_modo_copia(client_admin, monkeypatch, tmp_path):
    """Gate Sol da PR #437: na copia a copia externa nao roda (main.py); a Saude nao pode dize-la configurada."""
    monkeypatch.setenv("DASH_BACKUP_EXTERNO", str(tmp_path / "externo"))
    monkeypatch.setattr(instalacao, "_estado", {"instalacao": "autorizada", "motivo": None})
    assert client_admin.get("/api/admin/backup").json()["copia_externa_configurada"] is True
    monkeypatch.setattr(instalacao, "_estado", COPIA)
    assert client_admin.get("/api/admin/backup").json()["copia_externa_configurada"] is False


def test_sincronizar_agora_recusa_no_modo_copia(client_admin, monkeypatch, tmp_path):
    _rm_simulado(tmp_path, monkeypatch)              # RM configurado: a recusa e' da instalacao, nao da falta de RM
    monkeypatch.setattr(instalacao, "_estado", {"instalacao": "nao-autorizada", "motivo": "maquina"})
    r = client_admin.post("/api/rm/sincronizar")
    assert r.status_code == 422 and r.json()["detail"] == "Sincronização desligada: instalação não autorizada."
    assert client_admin.get("/api/rm/status").json()["rodadas"] == []          # nenhuma rodada comecou


def test_sincronizar_agora_funciona_com_a_instalacao_autorizada(client_admin, monkeypatch, tmp_path):
    _rm_simulado(tmp_path, monkeypatch)
    monkeypatch.setattr(instalacao, "_estado", {"instalacao": "autorizada", "motivo": None})
    r = client_admin.post("/api/rm/sincronizar")
    assert r.status_code == 200 and r.json()["estado"] == "success", r.text


def test_teste_de_envio_recusa_no_modo_copia_e_nada_sai(client_admin, monkeypatch, tmp_path):
    """A rota do teste de envio so' captura o erro do Graph: a recusa chega pelo tratador geral, em portugues, antes
    de qualquer conversa com o Microsoft 365 (nem o "De:" e' lido)."""
    from app import correio, db
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    monkeypatch.setattr(instalacao, "_estado", COPIA)
    cliente_real = correio.cliente

    def sem_graph(*a, **k):
        raise AssertionError("a copia falou com o Microsoft 365")

    monkeypatch.setattr(correio, "cliente", sem_graph)
    r = client_admin.post("/api/correio/teste")
    assert r.status_code == 422 and r.json()["detail"] == "Envio desligado: instalação não autorizada."
    monkeypatch.setattr(correio, "cliente", cliente_real)
    assert not (tmp_path / "sim" / "enviados").exists()
    conn = db.get_conn()
    try:
        assert conn.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    finally:
        conn.close()
    monkeypatch.setattr(instalacao, "_estado", {"instalacao": "autorizada", "motivo": None})
    r = client_admin.post("/api/correio/teste")
    assert r.status_code == 200, r.text
    assert len(list((tmp_path / "sim" / "enviados").glob("*.json"))) == 1
