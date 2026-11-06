"""Envio por e-mail da copia cifrada do dono (issue #420), pelo simulador do Graph."""
import hashlib
import json
import logging
import os
import threading
import time

import pytest

from app import auth, backup, copia_dono_envio, correio, db, envio_reserva, graph


DONO = "dono@exemplo.com.br"
PARA = "caixa-do-dono@exemplo.com.br"


@pytest.fixture(autouse=True)
def estado_limpo(monkeypatch):
    monkeypatch.setattr(backup, "ESTADO", {**backup.ESTADO, "ultimo_envio_copia_dono": None,
                                           "ultimo_envio_copia_dono_erro": None})


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "teste.db"))
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn = db.get_conn()
    db.migrate(conn)
    auth.criar_usuario(conn, "Dono", DONO, "senha-forte-123", "admin")
    conn.execute("INSERT INTO cadastro_geral (chave, valor) VALUES ('copia_dono', ?)",
                 (json.dumps({"para": [PARA], "enviada_por": [DONO]}),))
    conn.commit()
    yield conn, tmp_path
    conn.close()


def _copia(tmp_path, nome="dashboard-dono-20261105-080000.tar.age", tamanho=2500) -> os.PathLike:
    pasta = tmp_path / "dados" / "backups" / "dono"
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / nome
    arq.write_bytes(os.urandom(tamanho))
    return arq


def _enviados(tmp_path) -> list[dict]:
    pasta = tmp_path / "sim" / "enviados"
    return [json.loads(a.read_text(encoding="utf-8")) for a in sorted(pasta.glob("*.json"))] if pasta.exists() else []


def _admin(conn) -> dict:
    r = conn.execute("SELECT id, email FROM usuarios WHERE email=?", (DONO,)).fetchone()
    return {"id": r["id"], "email": r["email"]}


def test_envia_o_arquivo_inteiro_como_anexo_da_conta_configurada(ambiente):
    conn, tmp = ambiente
    arq = _copia(tmp)
    sha = hashlib.sha256(arq.read_bytes()).hexdigest()
    assert copia_dono_envio.enviar_nova(conn, arq) == 1
    [m] = _enviados(tmp)
    assert m["remetente"] == DONO and m["para"] == [PARA] and m["copia"] == []
    assert m["assunto"] == "Dashboard Lotufo: cópia cifrada de 05/11/2026"
    assert m["anexos"] == [{"nome": arq.name, "tamanho": 2500, "sha256": sha}]
    assert sha in m["corpo"] and "05/11/2026" in m["corpo"] and "2.500 bytes" in m["corpo"]
    assert "Abre só com a chave do dono; instruções no runbook, seção Cópia do dono" in m["corpo"]
    assert conn.execute("SELECT tipo FROM envios").fetchall()[0][0] == "copia_dono"
    linha = conn.execute("SELECT * FROM copia_dono_envios").fetchone()
    assert (linha["arquivo"], linha["sha256"], linha["rodada"], linha["parte"], linha["partes"]) == \
        (arq.name, sha, 1, 1, 1)
    assert linha["envio_id"] is not None and linha["envio_reservado_em"] is None
    assert backup.ESTADO["ultimo_envio_copia_dono"] and backup.ESTADO["ultimo_envio_copia_dono_erro"] is None


def test_arquivo_acima_do_teto_vai_em_partes_com_o_sha256_do_inteiro(ambiente, monkeypatch):
    conn, tmp = ambiente
    monkeypatch.setattr(copia_dono_envio, "TAMANHO_PARTE", 1000)
    arq = _copia(tmp, tamanho=2500)
    dados = arq.read_bytes()
    sha = hashlib.sha256(dados).hexdigest()
    assert copia_dono_envio.enviar_nova(conn, arq) == 3
    msgs = _enviados(tmp)
    assert [m["assunto"] for m in msgs] == [f"Dashboard Lotufo: cópia cifrada de 05/11/2026 (parte {n} de 3)"
                                            for n in (1, 2, 3)]
    pedacos = [dados[0:1000], dados[1000:2000], dados[2000:]]
    for n, (m, pedaco) in enumerate(zip(msgs, pedacos), start=1):
        assert m["anexos"] == [{"nome": f"{arq.name}.part0{n}", "tamanho": len(pedaco),
                                "sha256": hashlib.sha256(pedaco).hexdigest()}]
        assert sha in m["corpo"] and "2.500 bytes" in m["corpo"]
    assert [r[0] for r in conn.execute("SELECT parte FROM copia_dono_envios ORDER BY parte")] == [1, 2, 3]


def test_o_teto_da_parte_cabe_no_limite_do_e_mail_com_a_assinatura():
    assert copia_dono_envio.TAMANHO_PARTE + correio.ASSINATURA_MAX <= correio.MAX_TOTAL


def test_a_mesma_copia_nao_sai_duas_vezes_e_a_nova_sai_sozinha(ambiente):
    conn, tmp = ambiente
    arq = _copia(tmp)
    assert copia_dono_envio.enviar_nova(conn, arq) == 1
    assert copia_dono_envio.enviar_nova(conn, arq) == 0
    assert len(_enviados(tmp)) == 1
    nova = _copia(tmp, nome="dashboard-dono-20261112-080000.tar.age")
    assert copia_dono_envio.enviar_nova(conn, nova) == 1
    msgs = _enviados(tmp)
    assert [m["anexos"][0]["nome"] for m in msgs] == [arq.name, nova.name]


def test_reenviar_manda_de_novo_a_copia_mais_recente_e_fica_na_auditoria(ambiente):
    conn, tmp = ambiente
    _copia(tmp, nome="dashboard-dono-20261029-080000.tar.age")
    arq = _copia(tmp)
    copia_dono_envio.enviar_nova(conn, arq)
    r = copia_dono_envio.reenviar(conn, tmp / "dados" / "backups", _admin(conn))
    assert r == {"arquivo": arq.name, "emails": 1}
    msgs = _enviados(tmp)
    assert len(msgs) == 2 and msgs[1]["anexos"] == msgs[0]["anexos"]
    assert [x[0] for x in conn.execute("SELECT rodada FROM copia_dono_envios ORDER BY id")] == [1, 2]
    a = conn.execute("SELECT entidade, entidade_id FROM audit_log WHERE acao='copia_dono.reenviar'").fetchone()
    assert (a["entidade"], a["entidade_id"]) == ("copia_dono", arq.name)


def test_reenviar_sem_copia_gerada_recusa(ambiente):
    conn, tmp = ambiente
    with pytest.raises(ValueError, match="Nenhuma cópia do dono gerada"):
        copia_dono_envio.reenviar(conn, tmp / "dados" / "backups", _admin(conn))
    assert _enviados(tmp) == []


def test_sem_copia_dono_no_cadastro_nada_sai_e_fica_no_log(ambiente, caplog):
    conn, tmp = ambiente
    conn.execute("DELETE FROM cadastro_geral WHERE chave='copia_dono'")
    conn.commit()
    with caplog.at_level(logging.WARNING, logger="app.copia_dono_envio"):
        assert copia_dono_envio.enviar_nova(conn, _copia(tmp)) == 0
    assert _enviados(tmp) == [] and conn.execute("SELECT COUNT(*) FROM copia_dono_envios").fetchone()[0] == 0
    assert "copia_dono" in caplog.text
    assert "geral.yaml" in backup.ESTADO["ultimo_envio_copia_dono_erro"]


def test_sem_conta_conectada_nada_sai_e_a_saude_mostra_o_motivo(ambiente, monkeypatch, caplog):
    conn, tmp = ambiente
    monkeypatch.delenv("DASH_GRAPH_SIMULADOR")
    monkeypatch.setenv("DASH_GRAPH_CLIENT_ID", "cliente-teste")
    monkeypatch.setenv("DASH_GRAPH_TOKENS_DIR", str(tmp / "tokens"))
    with caplog.at_level(logging.WARNING, logger="app.copia_dono_envio"):
        assert copia_dono_envio.enviar_nova(conn, _copia(tmp)) == 0
    assert conn.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM copia_dono_envios").fetchone()[0] == 0
    erro = backup.ESTADO["ultimo_envio_copia_dono_erro"]
    assert "conta Microsoft" in erro and DONO in erro and "não está conectada" in caplog.text
    s = backup.situacao(tmp / "dados" / "backups", False, backup.tempo.agora_utc())
    assert "conta Microsoft" in s["ultimo_envio_copia_dono_erro"] and s["ultimo_envio_copia_dono_erro_em"]


def test_sem_usuario_ativo_com_o_login_configurado_nada_sai(ambiente):
    conn, tmp = ambiente
    conn.execute("UPDATE cadastro_geral SET valor=? WHERE chave='copia_dono'",
                 (json.dumps({"para": [PARA], "enviada_por": ["outro@exemplo.com.br"]}),))
    conn.commit()
    assert copia_dono_envio.enviar_nova(conn, _copia(tmp)) == 0
    assert _enviados(tmp) == []
    assert "enviada_por" in backup.ESTADO["ultimo_envio_copia_dono_erro"]


class FalhaNaSegunda:
    """No lugar de `correio.cliente`: a 2a parte falha antes do /send (nada dela saiu)."""

    def __init__(self):
        self.enviados = []

    def __call__(self, usuario_id, email_usuario=""):
        return self

    def remetente(self):
        return DONO

    def enviar(self, para, copia, assunto, corpo_html, anexos, cco=(), inline=()):
        if len(self.enviados) == 1:
            raise graph.ErroGraph("Graph inacessível (TimeoutError)")
        self.enviados.append(assunto)
        return f"<falso-{len(self.enviados)}@teste>"


def test_falha_no_meio_das_partes_solta_as_reservas_que_nao_sairam(ambiente, monkeypatch):
    conn, tmp = ambiente
    monkeypatch.setattr(copia_dono_envio, "TAMANHO_PARTE", 1000)
    falso = FalhaNaSegunda()
    monkeypatch.setattr(correio, "cliente", falso)
    assert copia_dono_envio.enviar_nova(conn, _copia(tmp)) == 1
    linhas = conn.execute("SELECT parte, envio_id, envio_reservado_em FROM copia_dono_envios ORDER BY parte").fetchall()
    assert [(l[0], l[1] is not None, l[2]) for l in linhas] == [(1, True, None), (2, False, None), (3, False, None)]
    assert "parte 2 de 3" in backup.ESTADO["ultimo_envio_copia_dono_erro"]
    # reenvio depois manda as tres de novo
    monkeypatch.setattr(correio, "cliente", lambda *a, **k: correio.CorreioSimulado(tmp / "sim", DONO))
    assert copia_dono_envio.reenviar(conn, tmp / "dados" / "backups", _admin(conn))["emails"] == 3


def test_e_mail_que_saiu_sem_registro_segura_a_reserva(ambiente, monkeypatch):
    conn, tmp = ambiente
    arq = _copia(tmp)

    def quebra(*a, **k):
        raise correio.EnvioNaoRegistrado(None, "x", [PARA])
    monkeypatch.setattr(correio, "enviar_e_registrar", quebra)
    with pytest.raises(correio.EnvioNaoRegistrado):
        copia_dono_envio.enviar_nova(conn, arq)
    assert conn.execute("SELECT envio_reservado_em FROM copia_dono_envios").fetchone()[0] is not None
    with pytest.raises(envio_reserva.EnvioEmAndamento):
        copia_dono_envio.reenviar(conn, tmp / "dados" / "backups", _admin(conn))


# --- API ------------------------------------------------------------------------------------------------------

@pytest.fixture
def api(client_admin, tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    conn = db.get_conn()
    conn.execute("INSERT INTO cadastro_geral (chave, valor) VALUES ('copia_dono', ?)",
                 (json.dumps({"para": [PARA], "enviada_por": ["admin@lotufo.com"]}),))
    conn.commit()
    conn.close()
    return client_admin


def _copia_na_pasta(nome="dashboard-dono-20261105-080000.tar.age"):
    pasta = backup.pasta_local() / "dono"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome).write_bytes(os.urandom(500))
    return pasta / nome


def test_botao_reenviar_manda_a_copia(api, tmp_path):
    arq = _copia_na_pasta()
    r = api.post("/api/admin/copia-dono/reenviar")
    assert r.status_code == 200, r.text
    assert r.json() == {"arquivo": arq.name, "emails": 1}
    assert [m["anexos"][0]["nome"] for m in _enviados(tmp_path)] == [arq.name]
    assert api.get("/api/admin/backup").json()["ultimo_envio_copia_dono"]


def test_botao_reenviar_sem_copia_ou_sem_cadastro_responde_o_motivo(api, tmp_path):
    r = api.post("/api/admin/copia-dono/reenviar")
    assert r.status_code == 409 and "Nenhuma cópia do dono gerada" in r.json()["detail"]
    _copia_na_pasta()
    conn = db.get_conn()
    conn.execute("DELETE FROM cadastro_geral WHERE chave='copia_dono'")
    conn.commit()
    conn.close()
    r = api.post("/api/admin/copia-dono/reenviar")
    assert r.status_code == 409 and "geral.yaml" in r.json()["detail"]
    assert _enviados(tmp_path) == []
    assert "geral.yaml" in api.get("/api/admin/backup").json()["ultimo_envio_copia_dono_erro"]


def test_botao_reenviar_so_admin(api):
    api.post("/api/admin/usuarios", json={"nome": "Eng", "email": "eng@lotufo.com", "senha": "senha-eng-123",
                                          "perfil": "engenharia"})
    r = api.post("/api/auth/login", json={"email": "eng@lotufo.com", "senha": "senha-eng-123"})
    api.cookies.clear()
    api.cookies.set("sessao", r.cookies["sessao"])
    api.headers["X-CSRF-Token"] = r.json()["csrf"]
    assert api.post("/api/admin/copia-dono/reenviar").status_code == 403


class CorreioLento:
    def __init__(self):
        self.enviados, self._trava = [], threading.Lock()

    def __call__(self, usuario_id, email_usuario=""):
        return self

    def remetente(self):
        return "admin@lotufo.com"

    def enviar(self, para, copia, assunto, corpo_html, anexos, cco=(), inline=()):
        time.sleep(0.3)
        with self._trava:
            self.enviados.append(assunto)
            return f"<falso-{len(self.enviados)}@teste>"


def test_dois_reenvios_simultaneos_saem_uma_vez(api, monkeypatch):
    _copia_na_pasta()
    falso = CorreioLento()
    monkeypatch.setattr(correio, "cliente", falso)
    largada, respostas = threading.Barrier(2), []

    def dispara():
        largada.wait()
        respostas.append(api.post("/api/admin/copia-dono/reenviar"))

    ts = [threading.Thread(target=dispara) for _ in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(r.status_code for r in respostas) == [200, 409], [r.text for r in respostas]
    perdeu = next(r for r in respostas if r.status_code == 409)
    assert perdeu.json()["detail"]["codigo"] == "ENVIO_RESERVADO"
    assert len(falso.enviados) == 1


def test_reserva_presa_da_copia_do_dono_se_libera_pela_rota_de_envios(api):
    arq = _copia_na_pasta()
    conn = db.get_conn()
    uid = conn.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0]
    rid = conn.execute("INSERT INTO copia_dono_envios (arquivo, sha256, tamanho, rodada, parte, partes, "
                       "envio_reservado_em, envio_reservado_por) VALUES (?,?,?,1,1,1,datetime('now','-30 minutes'),?)",
                       (arq.name, "x" * 64, 500, uid)).lastrowid
    conn.commit()
    conn.close()
    assert api.post("/api/admin/copia-dono/reenviar").status_code == 409
    r = api.post("/api/envios/liberar", json={"tabela": "copia_dono_envios", "id": rid,
                                              "justificativa": "conferi os Enviados e não saiu",
                                              "conferi_enviados": True})
    assert r.status_code == 200, r.text
    assert api.post("/api/admin/copia-dono/reenviar").status_code == 200


def test_botao_gerar_tambem_envia_a_copia_nova(api, tmp_path, monkeypatch):
    pytest.importorskip("pyrage")
    from pyrage import x25519
    chave = tmp_path / "chave-publica-dono.txt"
    chave.write_text(str(x25519.Identity.generate().to_public()), encoding="utf-8")
    monkeypatch.setenv("DASH_CHAVE_PUBLICA_DONO", str(chave))
    monkeypatch.delenv("DASH_CADASTRO_DIR", raising=False)
    backup.criar_snapshot(db.db_path(), backup.pasta_local())
    r = api.post("/api/admin/copia-dono")
    assert r.status_code == 200, r.text
    arq = backup.pasta_local() / "dono" / r.json()["arquivo"]
    assert r.json()["emails"] == 1
    [m] = _enviados(tmp_path)
    assert m["anexos"][0]["nome"] == arq.name and backup._sha256(arq) in m["corpo"]


def test_rodada_semanal_gera_e_envia(ambiente, monkeypatch):
    pytest.importorskip("pyrage")
    from pyrage import x25519
    conn, tmp = ambiente
    monkeypatch.delenv("DASH_CADASTRO_DIR", raising=False)
    (tmp / "segredos").mkdir()
    (tmp / "segredos" / "chave-publica-dono.txt").write_text(str(x25519.Identity.generate().to_public()),
                                                              encoding="utf-8")
    pasta = tmp / "dados" / "backups"
    backup.criar_snapshot(tmp / "teste.db", pasta)
    copia_dono_envio.rodada_semanal(tmp, pasta)
    copia_dono_envio.rodada_semanal(tmp, pasta)  # menos de 7 dias: nao gera nem envia de novo
    [m] = _enviados(tmp)
    [arq] = copia_dono_envio.copia_dono.copias(pasta)
    assert m["anexos"][0]["nome"] == arq.name
