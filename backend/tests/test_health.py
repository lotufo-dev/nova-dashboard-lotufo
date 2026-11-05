import pytest


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["status"] == "ok" and corpo["banco"] == "ok"
    assert "ultimo_snapshot" in corpo["backup"]
    # issue #417: os testes rodam como dev (conftest)
    assert (corpo["instalacao"], corpo["instalacao_motivo"]) == ("dev", None)


def _app_de_verdade(tmp_path, monkeypatch, maquina="MAQUINA-TESTE"):
    """App fora do dev, com o banco em <raiz>/dados: a instalacao e' conferida de verdade na subida."""
    from fastapi.testclient import TestClient
    from app.main import create_app
    monkeypatch.delenv("DASH_DEV", raising=False)
    monkeypatch.delenv("DASH_INSTALACAO_ARQUIVO", raising=False)
    from app import instalacao
    monkeypatch.setattr(instalacao, "maquina_atual", lambda: maquina)
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "dados" / "dashboard.db"))
    monkeypatch.setenv("DASH_SEM_JOBS", "1")
    monkeypatch.setenv("DASH_SEM_FRONTEND", "1")
    return TestClient(create_app())


def _assinar_para(tmp_path, monkeypatch, maquina):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from app import instalacao
    privada = Ed25519PrivateKey.generate()
    monkeypatch.setattr(instalacao, "CHAVE_PUBLICA", privada.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii"))
    arquivo = tmp_path / "segredos" / "instalacao.json"
    arquivo.parent.mkdir(parents=True)
    arquivo.write_bytes(instalacao.assinar(privada, maquina))


@pytest.mark.instalacao_real
def test_health_200_no_modo_copia_com_o_motivo_e_sem_caminho(tmp_path, monkeypatch):
    """O watchdog so' olha o 200: no modo copia ele nao pode reiniciar o servidor em laco."""
    with _app_de_verdade(tmp_path, monkeypatch) as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    corpo = r.json()
    assert (corpo["status"], corpo["banco"]) == ("ok", "ok")
    assert (corpo["instalacao"], corpo["instalacao_motivo"]) == ("nao-autorizada", "ausente")
    assert str(tmp_path) not in r.text and "instalacao.json" not in r.text and "segredos" not in r.text


@pytest.mark.instalacao_real
@pytest.mark.parametrize("assinado_para, motivo", [("MAQUINA-TESTE", None), ("OUTRA-MAQUINA", "maquina")])
def test_health_com_o_arquivo_assinado(tmp_path, monkeypatch, assinado_para, motivo):
    _assinar_para(tmp_path, monkeypatch, assinado_para)
    with _app_de_verdade(tmp_path, monkeypatch) as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    assert (r.json()["instalacao"], r.json()["instalacao_motivo"]) == \
        ("autorizada" if motivo is None else "nao-autorizada", motivo)


def test_health_acusa_copia_dos_arquivos_que_nao_termina(client, monkeypatch):
    # issue #55 / S1: o prazo e' conferido na leitura do health, nao pelo worker travado
    import time
    from app import backup
    monkeypatch.setattr(backup, "_arquivos_fase", "local")
    monkeypatch.setattr(backup, "_arquivos_desde", time.monotonic() - 3 * 3600)
    corpo = client.get("/api/health").json()
    assert corpo["backup"]["ultima_copia_arquivos_erro"] == "a cópia está rodando há 3 horas sem terminar"


def test_health_503_quando_o_banco_nao_responde(client, monkeypatch):
    import sqlite3
    from app import db
    def quebrada():
        raise sqlite3.OperationalError("unable to open database file")
    monkeypatch.setattr(db, "get_conn", quebrada)
    r = client.get("/api/health")
    assert r.status_code == 503 and r.json()["status"] == "erro"


def test_logs_em_arquivo_quando_DASH_LOG_DIR(tmp_path, monkeypatch):
    import logging
    from app import logs
    monkeypatch.setenv("DASH_LOG_DIR", str(tmp_path / "logs"))
    arquivo = logs.configurar()
    logs.configurar()  # segunda chamada nao duplica handler
    try:
        logging.getLogger("uvicorn.error").info("subiu")
        logging.getLogger("app.backup").error("falhou")
        for h in logging.getLogger("uvicorn").handlers:
            h.flush()
        texto = arquivo.read_text(encoding="utf-8")
        assert texto.count("subiu") == 1 and "falhou" in texto
    finally:
        for nome in logs._LOGGERS:
            lg = logging.getLogger(nome)
            for h in [h for h in lg.handlers if h.get_name() == logs._NOME_HANDLER]:
                lg.removeHandler(h); h.close()
            if nome:
                lg.propagate = True


def test_app_sobe_sem_modulo_de_robo(tmp_path, monkeypatch):
    """Spec §15.2: o robo das federais saiu. Nenhum atributo dele pode sobrar no app."""
    import importlib
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "r.db"))
    monkeypatch.setenv("DASH_SEM_JOBS", "1")
    monkeypatch.setenv("DASH_SEM_FRONTEND", "1")
    import app.main as m
    importlib.reload(m)
    assert not hasattr(m, "robo_mod")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.robo_certidoes")
