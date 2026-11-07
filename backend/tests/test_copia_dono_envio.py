"""Envio por e-mail da copia cifrada do dono (issue #420), pelo simulador do Graph."""
import hashlib
import json
import logging
import os
import threading
import time

import pytest

from app import auditoria, auth, backup, copia_dono_envio, correio, db, envio_reserva, graph


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


def _gravar(arq, tamanho):
    """Como a geracao grava: arquivo age (cabecalho) e o .sha256 ao lado."""
    dados = copia_dono_envio.CABECALHO_AGE + os.urandom(tamanho - len(copia_dono_envio.CABECALHO_AGE))
    arq.write_bytes(dados)
    (arq.parent / f"{arq.name}.sha256").write_text(f"{hashlib.sha256(dados).hexdigest()}  {arq.name}\n", "utf-8")
    return arq


def _ok(n):
    return {"emails": n, "partes": n, "completo": True}


NADA = {"emails": 0, "partes": None, "completo": False}


def _copia(tmp_path, nome="dashboard-dono-20261105-080000.tar.age", tamanho=2500) -> os.PathLike:
    pasta = tmp_path / "dados" / "backups" / "dono"
    pasta.mkdir(parents=True, exist_ok=True)
    return _gravar(pasta / nome, tamanho)


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
    assert copia_dono_envio.enviar_nova(conn, arq) == _ok(1)
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
    assert copia_dono_envio.enviar_nova(conn, arq) == _ok(3)
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
    assert copia_dono_envio.enviar_nova(conn, arq) == _ok(1)
    assert copia_dono_envio.enviar_nova(conn, arq) == NADA
    assert len(_enviados(tmp)) == 1
    nova = _copia(tmp, nome="dashboard-dono-20261112-080000.tar.age")
    assert copia_dono_envio.enviar_nova(conn, nova) == _ok(1)
    msgs = _enviados(tmp)
    assert [m["anexos"][0]["nome"] for m in msgs] == [arq.name, nova.name]


def test_reenviar_manda_de_novo_a_copia_mais_recente_e_fica_na_auditoria(ambiente):
    conn, tmp = ambiente
    _copia(tmp, nome="dashboard-dono-20261029-080000.tar.age")
    arq = _copia(tmp)
    copia_dono_envio.enviar_nova(conn, arq)
    r = copia_dono_envio.reenviar(conn, tmp / "dados" / "backups", _admin(conn))
    assert r == {"arquivo": arq.name, **_ok(1)}
    msgs = _enviados(tmp)
    assert len(msgs) == 2 and msgs[1]["anexos"] == msgs[0]["anexos"]
    assert [x[0] for x in conn.execute("SELECT rodada FROM copia_dono_envios ORDER BY id")] == [1, 2]
    inicio, fim = conn.execute("SELECT entidade, entidade_id, depois FROM audit_log WHERE acao='copia_dono.reenviar' "
                               "ORDER BY id").fetchall()
    assert (fim["entidade"], fim["entidade_id"]) == ("copia_dono", arq.name)
    assert json.loads(inicio["depois"])["resultado"] == "iniciado"
    depois = json.loads(fim["depois"])
    assert (depois["resultado"], depois["enviados"], depois["partes"], depois["rodada"]) == ("completo", 1, 1, 2)


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
        assert copia_dono_envio.enviar_nova(conn, _copia(tmp)) == NADA
    assert _enviados(tmp) == [] and conn.execute("SELECT COUNT(*) FROM copia_dono_envios").fetchone()[0] == 0
    assert "copia_dono" in caplog.text
    assert "geral.yaml" in backup.ESTADO["ultimo_envio_copia_dono_erro"]


def test_sem_conta_conectada_nada_sai_e_a_saude_mostra_o_motivo(ambiente, monkeypatch, caplog):
    conn, tmp = ambiente
    monkeypatch.delenv("DASH_GRAPH_SIMULADOR")
    monkeypatch.setenv("DASH_GRAPH_CLIENT_ID", "cliente-teste")
    monkeypatch.setenv("DASH_GRAPH_TOKENS_DIR", str(tmp / "tokens"))
    with caplog.at_level(logging.WARNING, logger="app.copia_dono_envio"):
        assert copia_dono_envio.enviar_nova(conn, _copia(tmp)) == NADA
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
    assert copia_dono_envio.enviar_nova(conn, _copia(tmp)) == NADA
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
    # parcial: a resposta diz quantas sairam de quantas e que nao esta' completo
    assert copia_dono_envio.enviar_nova(conn, _copia(tmp)) == {"emails": 1, "partes": 3, "completo": False}
    linhas = conn.execute("SELECT parte, envio_id, envio_reservado_em FROM copia_dono_envios ORDER BY parte").fetchall()
    assert [(l[0], l[1] is not None, l[2]) for l in linhas] == [(1, True, None), (2, False, None), (3, False, None)]
    assert "parte 2 de 3" in backup.ESTADO["ultimo_envio_copia_dono_erro"]
    # reenvio depois manda as tres de novo
    monkeypatch.setattr(correio, "cliente", lambda *a, **k: correio.CorreioSimulado(tmp / "sim", DONO))
    assert copia_dono_envio.reenviar(conn, tmp / "dados" / "backups", _admin(conn))["emails"] == 3


class FalhaSempre(FalhaNaSegunda):
    def enviar(self, *a, **k):
        raise graph.ErroGraph("Graph inacessível (TimeoutError)")


@pytest.mark.parametrize("falso, resultado, enviados", [(FalhaNaSegunda, "parcial", 1), (FalhaSempre, "nada", 0)])
def test_reenvio_que_falha_fica_na_auditoria_com_o_resultado(ambiente, monkeypatch, falso, resultado, enviados):
    # a auditoria e' gravada depois da rodada: "reenviou" so' com o que o Graph aceitou
    conn, tmp = ambiente
    monkeypatch.setattr(copia_dono_envio, "TAMANHO_PARTE", 1000)
    _copia(tmp)
    monkeypatch.setattr(correio, "cliente", falso())
    with pytest.raises(ValueError):
        copia_dono_envio.reenviar(conn, tmp / "dados" / "backups", _admin(conn))
    inicio, fim = conn.execute("SELECT depois FROM audit_log WHERE acao='copia_dono.reenviar' ORDER BY id").fetchall()
    assert json.loads(inicio["depois"])["resultado"] == "iniciado"
    depois = json.loads(fim["depois"])
    assert (depois["resultado"], depois["enviados"], depois["partes"]) == (resultado, enviados, 3)


def test_reenvio_interrompido_deixa_o_evento_iniciado_com_quem_clicou(ambiente, monkeypatch):
    # issue #482: o servidor cai no meio da rodada (o evento do resultado nunca e' gravado); o "iniciado" entrou na
    # mesma transacao da reserva, com quem clicou
    conn, tmp = ambiente
    monkeypatch.setattr(copia_dono_envio, "TAMANHO_PARTE", 1000)
    _copia(tmp)
    monkeypatch.setattr(correio, "cliente", FalhaNaSegunda())
    monkeypatch.setattr(copia_dono_envio, "_auditar_reenvio", lambda *a, **k: None)   # caiu antes do resultado
    with pytest.raises(ValueError):
        copia_dono_envio.reenviar(conn, tmp / "dados" / "backups", _admin(conn))
    [a] = conn.execute("SELECT usuario_id, entidade_id, depois FROM audit_log WHERE acao='copia_dono.reenviar'").fetchall()
    assert a["usuario_id"] == _admin(conn)["id"]
    depois = json.loads(a["depois"])
    assert (depois["resultado"], depois["partes"], depois["rodada"]) == ("iniciado", 3, 1)


def test_auditoria_do_inicio_que_falha_nao_reserva_nem_envia(ambiente, monkeypatch):
    conn, tmp = ambiente
    _copia(tmp)

    def quebra(*a, **k):
        raise RuntimeError("banco ocupado")
    monkeypatch.setattr(auditoria, "registrar", quebra)
    with pytest.raises(RuntimeError):
        copia_dono_envio.reenviar(conn, tmp / "dados" / "backups", _admin(conn))
    assert conn.execute("SELECT COUNT(*) FROM copia_dono_envios").fetchone()[0] == 0
    assert _enviados(tmp) == []


def test_envio_automatico_nao_grava_evento_de_reenvio(ambiente):
    conn, tmp = ambiente
    assert copia_dono_envio.enviar_nova(conn, _copia(tmp)) == _ok(1)
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='copia_dono.reenviar'").fetchone()[0] == 0


def test_trava_que_nao_sai_no_meio_das_partes_vai_junto_do_motivo(ambiente, monkeypatch):
    conn, tmp = ambiente
    monkeypatch.setattr(copia_dono_envio, "TAMANHO_PARTE", 1000)
    monkeypatch.setattr(correio, "cliente", FalhaNaSegunda())

    def ocupado(*a, **k):
        raise ValueError("banco ocupado")
    monkeypatch.setattr(envio_reserva, "liberar_com_retentativa", ocupado)
    assert copia_dono_envio.enviar_nova(conn, _copia(tmp))["emails"] == 1     # a 1a parte saiu e continua contada
    erro = backup.ESTADO["ultimo_envio_copia_dono_erro"]
    assert "parte 2 de 3" in erro and "2 reservas ficaram presas" in erro


def test_soltar_tenta_todas_as_reservas_mesmo_com_uma_que_falha(ambiente, monkeypatch):
    conn, tmp = ambiente
    monkeypatch.setattr(copia_dono_envio, "TAMANHO_PARTE", 1000)
    monkeypatch.setattr(correio, "cliente", FalhaNaSegunda())
    real, tentadas = envio_reserva.liberar_com_retentativa, []

    def uma_falha(conn_, tabela, id_):
        tentadas.append(id_)
        if len(tentadas) == 1:
            raise ValueError("banco ocupado")
        return real(conn_, tabela, id_)
    monkeypatch.setattr(envio_reserva, "liberar_com_retentativa", uma_falha)
    copia_dono_envio.enviar_nova(conn, _copia(tmp))
    assert len(tentadas) == 2                       # partes 2 e 3, mesmo com a 2 falhando
    linhas = conn.execute("SELECT parte, envio_reservado_em IS NOT NULL FROM copia_dono_envios ORDER BY parte")
    assert [tuple(l) for l in linhas] == [(1, 0), (2, 1), (3, 0)]
    assert "1 reserva ficou presa" in backup.ESTADO["ultimo_envio_copia_dono_erro"]


def test_e_mail_sem_registro_com_trava_que_nao_sai_conta_as_presas_na_saude(ambiente, monkeypatch):
    conn, tmp = ambiente
    monkeypatch.setattr(copia_dono_envio, "TAMANHO_PARTE", 1000)

    def quebra(*a, **k):
        raise correio.EnvioNaoRegistrado(None, "x", [PARA])

    def ocupado(*a, **k):
        raise ValueError("banco ocupado")
    monkeypatch.setattr(correio, "enviar_e_registrar", quebra)
    monkeypatch.setattr(envio_reserva, "liberar_com_retentativa", ocupado)
    with pytest.raises(correio.EnvioNaoRegistrado):
        copia_dono_envio.enviar_nova(conn, _copia(tmp))
    erro = backup.ESTADO["ultimo_envio_copia_dono_erro"]
    assert "o e-mail saiu e o registro falhou" in erro and "2 reservas ficaram presas" in erro


def test_copia_ja_enviada_nem_le_o_arquivo_de_novo(ambiente):
    conn, tmp = ambiente
    arq = _copia(tmp)
    assert copia_dono_envio.enviar_nova(conn, arq) == _ok(1)
    arq.unlink()                                    # sumiu (rotacao das 4 copias): o automatico nao acusa nada
    assert copia_dono_envio.enviar_nova(conn, arq) == NADA
    assert backup.ESTADO["ultimo_envio_copia_dono_erro"] is None


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
    assert "o e-mail saiu e o registro falhou" in backup.ESTADO["ultimo_envio_copia_dono_erro"]


def test_envio_incerto_diz_incerto_e_nao_que_saiu(ambiente, monkeypatch):
    conn, tmp = ambiente

    def caiu(*a, **k):
        raise correio.EnvioIncerto(None, "x", [PARA])
    monkeypatch.setattr(correio, "enviar_e_registrar", caiu)
    with pytest.raises(correio.EnvioIncerto):
        copia_dono_envio.enviar_nova(conn, _copia(tmp))
    erro = backup.ESTADO["ultimo_envio_copia_dono_erro"]
    assert "envio incerto: confira os Enviados" in erro and "o e-mail saiu" not in erro


def test_marcacao_que_falha_depois_do_envio_solta_as_partes_seguintes(ambiente, monkeypatch):
    conn, tmp = ambiente
    monkeypatch.setattr(copia_dono_envio, "TAMANHO_PARTE", 1000)
    real, chamadas = envio_reserva.liberar, []

    def liberar(conn_, tabela, id_):
        chamadas.append(id_)
        if len(chamadas) == 1:                      # a marcacao da parte 1, depois do e-mail
            raise RuntimeError("banco quebrado")
        return real(conn_, tabela, id_)
    monkeypatch.setattr(envio_reserva, "liberar", liberar)
    with pytest.raises(correio.EnvioNaoRegistrado):
        copia_dono_envio.enviar_nova(conn, _copia(tmp))
    assert len(_enviados(tmp)) == 1                 # so' a parte 1 saiu
    linhas = conn.execute("SELECT parte, envio_reservado_em IS NOT NULL FROM copia_dono_envios ORDER BY parte")
    assert [tuple(l) for l in linhas] == [(1, 1), (2, 0), (3, 0)]   # so' a parte que saiu fica presa


@pytest.mark.parametrize("estrago", ["em claro", "sha256 diferente", "sem sha256"])
def test_reenvio_recusa_arquivo_que_nao_e_a_copia_cifrada(ambiente, estrago):
    conn, tmp = ambiente
    arq = _copia(tmp)
    sha = arq.parent / f"{arq.name}.sha256"
    if estrago == "em claro":
        dados = b"banco/dashboard.db SEGREDO EM CLARO" * 50
        arq.write_bytes(dados)
        sha.write_text(f"{hashlib.sha256(dados).hexdigest()}  {arq.name}\n", encoding="utf-8")
    elif estrago == "sha256 diferente":
        arq.write_bytes(arq.read_bytes() + b"x")
    else:
        sha.unlink()
    with pytest.raises(copia_dono_envio.CopiaInvalida, match="nada foi enviado"):
        copia_dono_envio.reenviar(conn, tmp / "dados" / "backups", _admin(conn))
    assert copia_dono_envio.enviar_nova(conn, arq) == NADA
    assert _enviados(tmp) == [] and conn.execute("SELECT COUNT(*) FROM copia_dono_envios").fetchone()[0] == 0
    assert "nada foi enviado" in backup.ESTADO["ultimo_envio_copia_dono_erro"]


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
    return _gravar(pasta / nome, 500)


def test_botao_reenviar_manda_a_copia(api, tmp_path):
    arq = _copia_na_pasta()
    r = api.post("/api/admin/copia-dono/reenviar")
    assert r.status_code == 200, r.text
    assert r.json() == {"arquivo": arq.name, **_ok(1)}
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


def _entrar(api, email, senha):
    r = api.post("/api/auth/login", json={"email": email, "senha": senha})
    api.cookies.clear()
    api.cookies.set("sessao", r.cookies["sessao"])
    api.headers["X-CSRF-Token"] = r.json()["csrf"]


def test_reserva_presa_da_copia_do_dono_se_libera_pela_rota_de_envios(api):
    arq = _copia_na_pasta()
    conn = db.get_conn()
    uid = conn.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0]
    rid = conn.execute("INSERT INTO copia_dono_envios (arquivo, sha256, tamanho, rodada, parte, partes, "
                       "envio_reservado_em, envio_reservado_por) VALUES (?,?,?,1,1,1,datetime('now','-30 minutes'),?)",
                       (arq.name, "x" * 64, 500, uid)).lastrowid
    conn.commit()
    conn.close()
    r = api.post("/api/admin/copia-dono/reenviar")
    assert r.status_code == 409
    d = r.json()["detail"]
    assert (d["codigo"], d["tabela"], d["id"]) == ("ENVIO_RESERVADO", "copia_dono_envios", rid)
    # a reserva da copia do dono so' se libera como admin, como o envio dela
    api.post("/api/admin/usuarios", json={"nome": "Eng", "email": "eng@lotufo.com", "senha": "senha-eng-123",
                                          "perfil": "engenharia"})
    corpo = {"tabela": "copia_dono_envios", "id": rid, "justificativa": "conferi os Enviados e não saiu",
             "conferi_enviados": True}
    _entrar(api, "eng@lotufo.com", "senha-eng-123")
    assert api.post("/api/envios/liberar", json=corpo).status_code == 403
    _entrar(api, "admin@lotufo.com", "senha-forte-123")
    r = api.post("/api/envios/liberar", json=corpo)
    assert r.status_code == 200, r.text
    assert api.post("/api/admin/copia-dono/reenviar").status_code == 200


def test_saude_acusa_a_copia_que_nao_saiu_mesmo_depois_de_reiniciar(api, tmp_path, monkeypatch):
    # o erro da memoria some quando o servidor reinicia; a copia mais recente sem envio completo continua acusada
    arq = _copia_na_pasta()
    assert api.get("/api/admin/backup").json()["ultimo_envio_copia_dono_erro"] == \
        "a cópia de 05/11/2026 não saiu por e-mail"
    assert api.post("/api/admin/copia-dono/reenviar").status_code == 200
    assert api.get("/api/admin/backup").json()["ultimo_envio_copia_dono_erro"] is None
    # parte que falhou depois de outra ter saido: a rodada nao esta' completa
    monkeypatch.setattr(copia_dono_envio, "TAMANHO_PARTE", 200)
    monkeypatch.setattr(correio, "cliente", FalhaNaSegunda())
    conn = db.get_conn()
    nova = _copia_na_pasta("dashboard-dono-20261112-080000.tar.age")
    assert copia_dono_envio.enviar_nova(conn, nova) == {"emails": 1, "partes": 3, "completo": False}
    conn.close()
    monkeypatch.setattr(backup, "ESTADO", {**backup.ESTADO, "ultimo_envio_copia_dono_erro": None})  # reiniciou
    assert api.get("/api/admin/backup").json()["ultimo_envio_copia_dono_erro"] == \
        "a cópia de 12/11/2026 não saiu por e-mail"
    assert arq.exists()


def test_saude_acusa_o_envio_interrompido_no_meio_da_rodada(api):
    # o processo caiu com a rodada reservada (deploy, queda, envio incerto): passada a idade minima da liberacao,
    # a reserva vira pendencia, mesmo com outra rodada completa (ela trava o "Reenviar")
    arq = _copia_na_pasta()
    conn = db.get_conn()
    uid = conn.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0]
    eid = correio.registrar_envio(conn, uid, "copia_dono", "admin@lotufo.com", [PARA], [], "x", None, [])
    conn.execute("INSERT INTO copia_dono_envios (arquivo, sha256, tamanho, rodada, parte, partes, envio_id) "
                 "VALUES (?,?,?,1,1,1,?)", (arq.name, "x" * 64, 500, eid))      # rodada 1 completa
    rid = conn.execute("INSERT INTO copia_dono_envios (arquivo, sha256, tamanho, rodada, parte, partes, "
                       "envio_reservado_em, envio_reservado_por) VALUES (?,?,?,2,1,1,datetime('now','-2 minutes'),?)",
                       (arq.name, "x" * 64, 500, uid)).lastrowid                 # rodada 2 reservada
    conn.commit()
    assert api.get("/api/admin/backup").json()["ultimo_envio_copia_dono_erro"] is None   # ainda pode estar saindo
    conn.execute("UPDATE copia_dono_envios SET envio_reservado_em=datetime('now', ?) WHERE id=?",
                 (f"-{envio_reserva.IDADE_MINIMA_LIBERACAO + 1} minutes", rid))
    conn.commit()
    conn.close()
    assert api.get("/api/admin/backup").json()["ultimo_envio_copia_dono_erro"] == \
        "envio da cópia de 05/11/2026 interrompido: confira os Enviados e libere"


def test_reserva_vencida_de_copia_anterior_continua_acusada_depois_da_nova_sair(api):
    # a copia A ficou com envio incerto; a B saiu inteira: a Saude continua acusando a A
    velha = _copia_na_pasta("dashboard-dono-20261029-080000.tar.age")
    conn = db.get_conn()
    uid = conn.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0]
    conn.execute("INSERT INTO copia_dono_envios (arquivo, sha256, tamanho, rodada, parte, partes, envio_reservado_em, "
                 "envio_reservado_por) VALUES (?,?,?,1,1,1,datetime('now','-1 hour'),?)", (velha.name, "x" * 64, 500, uid))
    conn.commit()
    assert copia_dono_envio.enviar_nova(conn, _copia_na_pasta()) == _ok(1)
    conn.close()
    assert api.get("/api/admin/backup").json()["ultimo_envio_copia_dono_erro"] == \
        "envio da cópia de 29/10/2026 interrompido: confira os Enviados e libere"


def test_saude_oferece_a_liberacao_da_reserva_presa_de_copia_anterior(api, tmp_path):
    # issue #482: a copia de 29/10 ficou presa (parte 2 de 3) e a de 05/11 saiu; a Saude devolve a linha presa, a
    # liberacao a solta e o alerta some
    velha = _copia_na_pasta("dashboard-dono-20261029-080000.tar.age")
    conn = db.get_conn()
    uid = conn.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0]
    rid = conn.execute("INSERT INTO copia_dono_envios (arquivo, sha256, tamanho, rodada, parte, partes, "
                       "envio_reservado_em, envio_reservado_por) VALUES (?,?,?,1,2,3,datetime('now','-1 hour'),?)",
                       (velha.name, "x" * 64, 500, uid)).lastrowid
    conn.commit()
    assert copia_dono_envio.enviar_nova(conn, _copia_na_pasta()) == _ok(1)
    conn.close()
    velha.unlink()                                  # a regra das 4 mais recentes apagou o arquivo velho
    s = api.get("/api/admin/backup").json()
    assert s["ultimo_envio_copia_dono_erro"] == "envio da cópia de 29/10/2026 interrompido: confira os Enviados e libere"
    d = s["copia_dono_presa"]
    assert (d["codigo"], d["tabela"], d["id"], d["parte"], d["partes"]) == (
        "ENVIO_RESERVADO", "copia_dono_envios", rid, 2, 3)
    assert d["assunto"] == "Dashboard Lotufo: cópia cifrada de 29/10/2026 (parte 2 de 3)"
    assert d["liberavel_a_partir_de"] and d["reservado_por_nome"]
    r = api.post("/api/envios/liberar", json={"tabela": "copia_dono_envios", "id": rid,
                                              "justificativa": "conferi os Enviados e não saiu", "conferi_enviados": True})
    assert r.status_code == 200, r.text
    s = api.get("/api/admin/backup").json()
    assert (s["ultimo_envio_copia_dono_erro"], s["copia_dono_presa"]) == (None, None)


def test_reserva_presa_de_copia_anterior_nao_trava_o_reenvio_da_nova(api, tmp_path):
    # o e-mail da copia velha pode ter saido sem registro (nao se libera): a mais recente continua saindo
    velha = _copia_na_pasta("dashboard-dono-20261029-080000.tar.age")
    nova = _copia_na_pasta()
    conn = db.get_conn()
    uid = conn.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0]
    conn.execute("INSERT INTO copia_dono_envios (arquivo, sha256, tamanho, rodada, parte, partes, envio_reservado_em, "
                 "envio_reservado_por) VALUES (?,?,?,1,1,1,datetime('now','-1 hour'),?)", (velha.name, "x" * 64, 500, uid))
    conn.commit()
    conn.close()
    r = api.post("/api/admin/copia-dono/reenviar")
    assert r.status_code == 200, r.text
    assert r.json()["arquivo"] == nova.name


def test_reenviar_com_reserva_presa_da_mesma_copia_diz_a_parte(api, monkeypatch):
    arq = _copia_na_pasta()
    conn = db.get_conn()
    uid = conn.execute("SELECT id FROM usuarios WHERE email='admin@lotufo.com'").fetchone()[0]
    rid = conn.execute("INSERT INTO copia_dono_envios (arquivo, sha256, tamanho, rodada, parte, partes, "
                       "envio_reservado_em, envio_reservado_por) VALUES (?,?,?,1,3,4,datetime('now','-30 minutes'),?)",
                       (arq.name, "x" * 64, 500, uid)).lastrowid
    conn.commit()
    conn.close()
    r = api.post("/api/admin/copia-dono/reenviar")
    assert r.status_code == 409
    d = r.json()["detail"]
    assert (d["codigo"], d["id"], d["parte"], d["partes"], d["assunto"]) == (
        "ENVIO_RESERVADO", rid, 3, 4, "Dashboard Lotufo: cópia cifrada de 05/11/2026 (parte 3 de 4)")


class CorreioQueDemora:
    """Cada parte leva 10 minutos (o relogio do banco e' adiantado envelhecendo as reservas). No meio da 3a parte,
    a rodada ja' passa de 20 minutos: nem a Saude acusa interrupcao nem a liberacao manual aceita."""

    def __init__(self, pasta):
        self.pasta, self.enviados, self.vistos = pasta, [], []

    def __call__(self, usuario_id, email_usuario=""):
        return self

    def remetente(self):
        return DONO

    def enviar(self, para, copia, assunto, corpo_html, anexos, cco=(), inline=()):
        c = db.get_conn()
        try:
            c.execute("UPDATE copia_dono_envios SET envio_reservado_em=datetime(envio_reservado_em, '-10 minutes') "
                      "WHERE envio_reservado_em IS NOT NULL")
            c.commit()
            if len(self.enviados) == 2:
                self.vistos.append(copia_dono_envio.pendente(c, self.pasta))
                rid = c.execute("SELECT id FROM copia_dono_envios WHERE parte=3").fetchone()[0]
                uid = c.execute("SELECT id FROM usuarios").fetchone()[0]
                try:
                    envio_reserva.liberar_manual(c, uid, "copia_dono_envios", rid, "conferi e nao saiu", True)
                    self.vistos.append("liberou")
                except ValueError as e:
                    self.vistos.append(str(e))
        finally:
            c.close()
        self.enviados.append(assunto)
        return f"<falso-{len(self.enviados)}@teste>"


def test_rodada_longa_renova_a_reserva_das_partes_que_faltam(ambiente, monkeypatch):
    conn, tmp = ambiente
    monkeypatch.setattr(copia_dono_envio, "TAMANHO_PARTE", 1000)
    falso = CorreioQueDemora(tmp / "dados" / "backups")
    monkeypatch.setattr(correio, "cliente", falso)
    assert copia_dono_envio.enviar_nova(conn, _copia(tmp)) == _ok(3)
    assert falso.vistos[0] is None                  # sem "interrompido" enquanto as partes saem
    assert falso.vistos[1].startswith("Envio iniciado há")   # a liberacao recusa: a rodada esta' viva


def test_botao_gerar_com_envio_parcial_nao_diz_completo(api, monkeypatch):
    arq = _copia_na_pasta()
    monkeypatch.setattr(copia_dono_envio.copia_dono, "gerar_e_registrar", lambda *a, **k: arq)
    monkeypatch.setattr(copia_dono_envio, "TAMANHO_PARTE", 200)
    monkeypatch.setattr(correio, "cliente", FalhaNaSegunda())
    r = api.post("/api/admin/copia-dono")
    assert r.status_code == 200, r.text
    assert r.json() == {"arquivo": arq.name, "emails": 1, "partes": 3, "completo": False}
    assert "parte 2 de 3" in api.get("/api/admin/backup").json()["ultimo_envio_copia_dono_erro"]


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
    assert (r.json()["emails"], r.json()["partes"], r.json()["completo"]) == (1, 1, True)
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
