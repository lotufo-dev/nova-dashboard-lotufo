"""Envio unico e registrado (pacote 1 da fase 4, testes de quebra de 10/10/2026): reserva atomica antes do
e-mail, registro que insiste quando o banco esta' travado e simulador que nao sobrescreve arquivo."""
import json
import sqlite3
import threading
import time

import pytest

from app import correio, db, protocolo
from tests.test_protocolo import cenario  # noqa: F401  (fixture)

# Gera PDF (a carta, por protocolo.criar) com a fonte da producao (Arial no Windows): a CI roda este modulo nos dois
# jobs (marcador pdf).
pytestmark = pytest.mark.pdf


class CorreioFalso:
    """No lugar de `correio.cliente`: conta os e-mails, demora `espera` segundos e pode rodar `no_meio` com o
    e-mail 'saindo' (so' na primeira chamada) -- e' assim que os testes de API reproduzem a corrida."""

    def __init__(self, espera=0.0, no_meio=None, falha=None):
        self.enviados, self.espera, self.no_meio, self.falha = [], espera, no_meio, falha
        self._trava = threading.Lock()

    def __call__(self, usuario_id, email_usuario=""):
        return self

    def remetente(self):
        return "maria@l.com"

    def enviar(self, para, copia, assunto, corpo_html, anexos, cco=(), inline=()):
        if self.falha:
            raise self.falha
        no_meio, self.no_meio = self.no_meio, None
        if no_meio:
            no_meio()
        time.sleep(self.espera)
        with self._trava:
            self.enviados.append(assunto)
            return f"<falso-{len(self.enviados)}@teste>"


def sempre_travado(*a, **k):
    raise sqlite3.OperationalError("database is locked")


def _protocolo(c, ids):
    return protocolo.criar(c, ids["uid"], ids["mtpar"], "unico", [ids["mtpar_exec"]], "301")


def _reserva(c, pid):
    return tuple(c.execute("SELECT envio_reservado_em, envio_reservado_por FROM protocolos WHERE id=?",
                           (pid,)).fetchone())


def test_reserva_e_exclusiva_e_liberar_destrava(cenario):
    from app import envio_reserva
    c, ids = cenario
    pid = _protocolo(c, ids)
    envio_reserva.reservar(c, "protocolos", pid, ids["uid"])
    assert _reserva(c, pid)[1] == ids["uid"]
    outra = db.get_conn()
    try:
        with pytest.raises(envio_reserva.EnvioEmAndamento,
                           match=r"em andamento ou foi interrompido \(iniciado às \d\d:\d\d por Maria\)"):
            envio_reserva.reservar(outra, "protocolos", pid, ids["uid"])
        envio_reserva.liberar(c, "protocolos", pid)
        assert _reserva(c, pid) == (None, None)
        envio_reserva.reservar(outra, "protocolos", pid, ids["uid"])        # destravado: a outra conexao pega
    finally:
        outra.close()


def test_reserva_antiga_continua_travada(cenario):
    """Sem tomada automatica: o banco nao distingue "processo morreu antes do e-mail" de "e-mail saiu e nao
    registrou" (esse com envio_id NULL). Quem decide e' uma pessoa, depois de olhar a caixa de Enviados."""
    from app import envio_reserva
    c, ids = cenario
    pid = _protocolo(c, ids)
    with db.mutacao(c):
        c.execute("UPDATE protocolos SET envio_reservado_em=datetime('now','-1 hours'), envio_reservado_por=? "
                  "WHERE id=?", (ids["uid"], pid))
    with pytest.raises(envio_reserva.EnvioEmAndamento, match="em andamento ou foi interrompido"):
        envio_reserva.reservar(c, "protocolos", pid, ids["uid"])


def _reservar_ha(c, pid, uid, minutos):
    with db.mutacao(c):
        c.execute("UPDATE protocolos SET envio_reservado_em=datetime('now', ?), envio_reservado_por=? WHERE id=?",
                  (f"-{minutos} minutes", uid, pid))
    return _reserva(c, pid)[0]


def test_liberar_manual_exige_justificativa_declaracao_e_audita(cenario):
    from app import envio_reserva
    c, ids = cenario
    pid = _protocolo(c, ids)
    ok = "  conferi: o e-mail não saiu  "
    with pytest.raises(ValueError, match="não está reservado"):
        envio_reserva.liberar_manual(c, ids["uid"], "protocolos", pid, ok, conferi_enviados=True)
    em = _reservar_ha(c, pid, ids["uid"], 16)
    for curta in ("", "  .  ", "ok"):
        with pytest.raises(ValueError, match="10 caracteres"):
            envio_reserva.liberar_manual(c, ids["uid"], "protocolos", pid, curta, conferi_enviados=True)
    with pytest.raises(ValueError, match="Confirme que conferiu a caixa de Enviados"):          # S5
        envio_reserva.liberar_manual(c, ids["uid"], "protocolos", pid, ok, conferi_enviados=False)
    assert _reserva(c, pid)[1] == ids["uid"]
    envio_reserva.liberar_manual(c, ids["uid"], "protocolos", pid, ok, conferi_enviados=True)
    assert _reserva(c, pid) == (None, None)
    a = c.execute("SELECT usuario_id, entidade, entidade_id, antes, depois FROM audit_log "
                  "WHERE acao='envio.liberar'").fetchone()
    assert (a["usuario_id"], a["entidade"], a["entidade_id"]) == (ids["uid"], "protocolo", str(pid))
    assert json.loads(a["antes"]) == {"reservado_em": em, "reservado_por": ids["uid"]}
    assert json.loads(a["depois"]) == {"justificativa": "conferi: o e-mail não saiu", "conferi_enviados": True}
    envio_reserva.reservar(c, "protocolos", pid, ids["uid"])                # liberado: reserva de novo


def test_liberar_manual_recusa_envio_que_pode_estar_saindo(cenario):
    """Gate Sol S1: com 1 minuto o envio de A pode ainda estar no Graph; B conferiria os Enviados cedo demais."""
    from app import envio_reserva
    c, ids = cenario
    pid = _protocolo(c, ids)
    _reservar_ha(c, pid, ids["uid"], 1)
    with pytest.raises(ValueError, match=r"Envio iniciado há 1 min por Maria: aguarde até \d\d:\d\d antes de liberar"):
        envio_reserva.liberar_manual(c, ids["uid"], "protocolos", pid, "conferi a caixa de Enviados", True)
    assert _reserva(c, pid)[1] == ids["uid"]
    _reservar_ha(c, pid, ids["uid"], 16)
    envio_reserva.liberar_manual(c, ids["uid"], "protocolos", pid, "conferi a caixa de Enviados", True)
    assert _reserva(c, pid) == (None, None)


def test_erro_de_reserva_vem_estruturado(cenario):
    """Gate Sol S6: a tela decide pelo codigo, nao pelo texto."""
    import datetime
    from app import envio_reserva
    c, ids = cenario
    pid = _protocolo(c, ids)
    _reservar_ha(c, pid, ids["uid"], 3)
    with pytest.raises(envio_reserva.EnvioEmAndamento) as erro:
        envio_reserva.reservar(c, "protocolos", pid, ids["uid"])
    e = erro.value
    assert (e.codigo, e.reservado_por_nome) == ("ENVIO_RESERVADO", "Maria")
    em, livre = datetime.datetime.fromisoformat(e.reservado_em), datetime.datetime.fromisoformat(e.liberavel_a_partir_de)
    assert livre - em == datetime.timedelta(minutes=15) and em.utcoffset() == datetime.timedelta(hours=-4)
    assert e.detalhe() == {"mensagem": str(e), "codigo": "ENVIO_RESERVADO", "reservado_em": e.reservado_em,
                           "reservado_por_nome": "Maria", "liberavel_a_partir_de": e.liberavel_a_partir_de}
    eid = correio.registrar_envio(c, ids["uid"], "protocolo", "maria@l.com", ["x@orgao.gov.br"], [], "A", None, [])
    with db.mutacao(c):
        c.execute("UPDATE protocolos SET envio_id=?, envio_reservado_em=NULL, envio_reservado_por=NULL WHERE id=?",
                  (eid, pid))
    with pytest.raises(envio_reserva.EnvioEmAndamento) as erro:
        envio_reserva.reservar(c, "protocolos", pid, ids["uid"], envio_id_visto=None)
    assert erro.value.codigo == "ENVIO_CONCLUIDO_NO_MEIO" and erro.value.reservado_em is None


def test_liberar_depois_de_falha_insiste_e_nao_esconde_o_erro(cenario, monkeypatch):
    """Gate Sol S4: nada saiu, mas o banco travado impede soltar a reserva."""
    from app import envio_reserva
    c, ids = cenario
    pid = _protocolo(c, ids)
    envio_reserva.reservar(c, "protocolos", pid, ids["uid"])
    monkeypatch.setattr(time, "sleep", lambda s: None)
    original, tentativas = envio_reserva.liberar, []

    def trava_duas(conn, tabela, id_):
        tentativas.append(1)
        if len(tentativas) < 3:
            raise sqlite3.OperationalError("database is locked")
        return original(conn, tabela, id_)

    monkeypatch.setattr(envio_reserva, "liberar", trava_duas)
    try:
        raise RuntimeError("Graph fora do ar")
    except RuntimeError:
        envio_reserva.liberar_com_retentativa(c, "protocolos", pid)
    assert len(tentativas) == 3 and _reserva(c, pid) == (None, None)

    envio_reserva.reservar(c, "protocolos", pid, ids["uid"])
    monkeypatch.setattr(envio_reserva, "liberar", sempre_travado)
    original_erro = RuntimeError("Graph fora do ar")
    with pytest.raises(ValueError, match="O envio NÃO foi feito, mas a trava não pôde ser removida") as erro:
        try:
            raise original_erro
        except RuntimeError:
            envio_reserva.liberar_com_retentativa(c, "protocolos", pid)
    assert erro.value.__cause__ is original_erro


def test_envio_inconsistente_nao_quebra(cenario):
    """envio_id apontando para envio inexistente: recusa com mensagem, sem TypeError."""
    from app import envio_reserva
    c, ids = cenario
    pid = _protocolo(c, ids)
    c.execute("PRAGMA foreign_keys=OFF")
    with db.mutacao(c):
        c.execute("UPDATE protocolos SET envio_id=999 WHERE id=?", (pid,))
    c.execute("PRAGMA foreign_keys=ON")
    with pytest.raises(envio_reserva.EnvioEmAndamento, match="acabou de ser feito por outra pessoa"):
        envio_reserva.reservar(c, "protocolos", pid, ids["uid"], envio_id_visto=None)


def test_envio_concluido_entre_a_leitura_e_a_reserva_nao_se_repete(cenario):
    """Quem leu o protocolo antes de outra pessoa terminar o envio nao reserva por cima do envio ja' feito."""
    from app import envio_reserva
    c, ids = cenario
    pid = _protocolo(c, ids)
    eid = correio.registrar_envio(c, ids["uid"], "protocolo", "maria@l.com", ["x@orgao.gov.br"], [], "A", None, [])
    with db.mutacao(c):
        c.execute("UPDATE protocolos SET envio_id=?, situacao='enviado' WHERE id=?", (eid, pid))
    with pytest.raises(envio_reserva.EnvioEmAndamento, match="acabou de ser feito"):
        envio_reserva.reservar(c, "protocolos", pid, ids["uid"], envio_id_visto=None)
    assert _reserva(c, pid) == (None, None)


def test_tabela_fora_da_lista_recusa(cenario):
    from app import envio_reserva
    c, ids = cenario
    with pytest.raises(ValueError, match="tabela"):
        envio_reserva.reservar(c, "usuarios", ids["uid"], ids["uid"])


def test_registro_com_banco_travado_tenta_de_novo(cenario, monkeypatch):
    c, ids = cenario
    original, tentativas = correio.registrar_envio, []

    def trava_duas_vezes(*a, **k):
        tentativas.append(1)
        if len(tentativas) < 3:
            raise sqlite3.OperationalError("database is locked")
        return original(*a, **k)

    monkeypatch.setattr(correio, "registrar_envio", trava_duas_vezes)
    monkeypatch.setattr(correio.time, "sleep", lambda s: None)
    eid = correio.enviar_e_registrar(c, ids["usuario"], "teste", ["x@orgao.gov.br"], [], "Assunto", "<p>x</p>", [])
    assert len(tentativas) == 3 and c.execute("SELECT COUNT(*) FROM envios WHERE id=?", (eid,)).fetchone()[0] == 1


def test_registro_que_nunca_grava_diz_que_o_email_saiu(cenario, monkeypatch, tmp_path):
    c, ids = cenario

    def sempre_travado(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(correio, "registrar_envio", sempre_travado)
    monkeypatch.setattr(correio.time, "sleep", lambda s: None)
    with pytest.raises(correio.EnvioNaoRegistrado) as erro:
        correio.enviar_e_registrar(c, ids["usuario"], "teste", ["x@orgao.gov.br"], [], "Assunto X", "<p>x</p>", [])
    assert erro.value.assunto == "Assunto X" and erro.value.para == ["x@orgao.gov.br"]
    assert erro.value.mensagem_id.startswith("<simulado-")
    assert len(list((tmp_path / "sim" / "enviados").glob("*.json"))) == 1     # o e-mail saiu de fato


# --- instalacao nao autorizada (issue #417): o envio e' recusado antes da reserva --------------------------------

COPIA = {"instalacao": "nao-autorizada", "motivo": "ausente"}
RECUSA = r"^Envio desligado: instalação não autorizada\.$"


def _nada_saiu(c, tmp_path):
    assert c.execute("SELECT COUNT(*) FROM envios").fetchone()[0] == 0
    assert not list((tmp_path / "sim" / "enviados").glob("*.json"))


def test_modo_copia_recusa_antes_da_reserva(cenario, monkeypatch, tmp_path):
    from app import envio_reserva, instalacao
    c, ids = cenario
    pid = _protocolo(c, ids)
    monkeypatch.setattr(instalacao, "_estado", COPIA)
    with pytest.raises(instalacao.EnvioDesligado, match=RECUSA):
        envio_reserva.reservar(c, "protocolos", pid, ids["uid"])
    assert _reserva(c, pid) == (None, None)
    with pytest.raises(instalacao.EnvioDesligado, match=RECUSA):      # quem envia sem reserva (teste, cobranca)
        correio.enviar_e_registrar(c, ids["usuario"], "teste", ["x@orgao.gov.br"], [], "Assunto", "<p>x</p>", [])
    _nada_saiu(c, tmp_path)


def test_modo_copia_recusa_o_protocolo_inteiro_sem_reservar(cenario, monkeypatch, tmp_path):
    from app import instalacao
    from tests.test_protocolo import _assinar, _montado
    c, ids = cenario
    pid = _protocolo(c, ids)
    protocolo.receber_assinado(c, ids["uid"], pid, _assinar(_montado(c, ids, pid)))
    pv = protocolo.previa_envio(c, [pid], remetente="maria@l.com")
    monkeypatch.setattr(instalacao, "_estado", COPIA)
    with pytest.raises(instalacao.EnvioDesligado, match=RECUSA):
        protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"])
    assert _reserva(c, pid) == (None, None)
    assert protocolo.detalhe(c, pid)["situacao"] != "enviado"
    assert c.execute("SELECT estado FROM medicoes WHERE id=?", (ids["mtpar_exec"],)).fetchone()[0] == "nota_emitida"
    _nada_saiu(c, tmp_path)
    # com a instalacao autorizada o mesmo envio sai
    monkeypatch.setattr(instalacao, "_estado", {"instalacao": "autorizada", "motivo": None})
    protocolo.enviar(c, ids["usuario"], [pid], pv["para"], pv["copia"], pv["assunto"], pv["corpo"])
    assert protocolo.detalhe(c, pid)["situacao"] == "enviado"


def test_simulador_nao_sobrescreve_envios_simultaneos(tmp_path, monkeypatch):
    """Dois envios ao mesmo tempo contavam o mesmo numero de arquivos e gravavam no MESMO nome (N-02).
    A colisao e' forcada fazendo a pasta parecer vazia para os dois."""
    sim = correio.CorreioSimulado(tmp_path, "maria@l.com")
    with monkeypatch.context() as m:
        m.setattr(correio.Path, "glob", lambda self, padrao: iter([]))
        m1 = sim.enviar(["a@x.com"], [], "Um", "<p>1</p>", [])
        m2 = sim.enviar(["b@x.com"], [], "Dois", "<p>2</p>", [])
    assert m1 != m2
    assert len(list((tmp_path / "enviados").glob("*.json"))) == 2
