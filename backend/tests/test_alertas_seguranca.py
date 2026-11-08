"""Alertas de seguranca por e-mail ao dono e resumo diario (issue #424), pelo simulador do Graph e com relogio fixo."""
import datetime
import json

import pytest

from app import alertas_seguranca, auditoria, auth, correio, db, graph, instalacao, seguranca, tempo

DONO = "dono@exemplo.com.br"
PARA = "caixa-do-dono@exemplo.com.br"
CUIABA = datetime.timezone(datetime.timedelta(hours=-4))
# 05/11/2026 10:02 em Cuiaba
AGORA = datetime.datetime(2026, 11, 5, 10, 2, tzinfo=CUIABA).astimezone(datetime.timezone.utc)


@pytest.fixture(autouse=True)
def estado_limpo(monkeypatch):
    monkeypatch.setattr(alertas_seguranca, "ESTADO", {"erro": None, "falhou_em": None})
    monkeypatch.setattr(alertas_seguranca.integridade, "commit_atual", lambda: "abc1234")


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "dados" / "teste.db"))
    monkeypatch.setenv("DASH_GRAPH_SIMULADOR", str(tmp_path / "sim"))
    (tmp_path / "dados").mkdir()
    conn = db.get_conn()
    db.migrate(conn)
    auth.criar_usuario(conn, "Dono", DONO, "senha-forte-123", "admin")
    conn.execute("INSERT INTO cadastro_geral (chave, valor) VALUES ('alertas_seguranca', ?)",
                 (json.dumps({"para": [PARA], "enviada_por": [DONO]}),))
    conn.commit()
    yield conn, tmp_path
    conn.close()


def _enviados(tmp_path) -> list[dict]:
    pasta = tmp_path / "sim" / "enviados"
    return [json.loads(a.read_text(encoding="utf-8")) for a in sorted(pasta.glob("*.json"))] if pasta.exists() else []


def _itens(monkeypatch, itens):
    monkeypatch.setattr(seguranca, "itens", lambda conn, agora=None: list(itens))


def _item(mensagem, hora_local="10:00", nivel="acao", dia=5):
    h, m = map(int, hora_local.split(":"))
    data = datetime.datetime(2026, 11, dia, h, m, tzinfo=CUIABA).astimezone(datetime.timezone.utc)
    return {"nivel": nivel, "mensagem": mensagem, "data": data.isoformat()}


def _alertas(tmp_path):
    return [m for m in _enviados(tmp_path) if "alerta de segurança" in m["assunto"]]


# --- alerta imediato --------------------------------------------------------------------------------------------

def test_login_de_administrador_de_origem_nova_manda_alerta_na_rodada(ambiente):
    conn, tmp = ambiente
    uid = conn.execute("SELECT id FROM usuarios WHERE email=?", (DONO,)).fetchone()[0]
    with db.mutacao(conn):
        auditoria.registrar(conn, uid, "auth.login", depois={"origem": "10.0.0.9", "navegador": "x", "perfil": "admin"})
    agora = tempo.agora_utc()
    assert [i["nivel"] for i in seguranca.itens(conn, agora)] == ["acao"]   # decisao do Leo de 08/11/2026
    alertas_seguranca.rodada(conn, agora)
    [m] = _alertas(tmp)
    assert m["assunto"] == ("Dashboard Lotufo: alerta de segurança: Administrador Dono entrou de uma origem nova "
                            "(10.0.0.9)")
    assert m["para"] == [PARA] and m["remetente"] == DONO
    assert conn.execute("SELECT tipo FROM envios").fetchone()[0] == "alertas_seguranca"


def test_o_mesmo_item_nao_sai_duas_vezes(ambiente, monkeypatch):
    conn, tmp = ambiente
    _itens(monkeypatch, [_item("Leitura de cadastro por x.exe (conta)")])
    alertas_seguranca.rodada(conn, AGORA)
    alertas_seguranca.rodada(conn, AGORA + datetime.timedelta(minutes=1))
    assert len(_alertas(tmp)) == 1
    linha = conn.execute("SELECT * FROM alertas_seguranca_envios WHERE tipo='alerta'").fetchone()
    assert linha["envio_id"] is not None and linha["envio_reservado_em"] is None


def test_itens_iguais_na_mesma_hora_vao_num_email_so(ambiente, monkeypatch):
    conn, tmp = ambiente
    _itens(monkeypatch, [_item("Tarefa agendada criada por conta", "10:05"),
                         _item("Tarefa agendada criada por conta", "10:40")])
    alertas_seguranca.rodada(conn, AGORA)
    [m] = _alertas(tmp)
    assert m["corpo"].count("Tarefa agendada criada por conta") == 2


def test_leitura_da_sentinela_que_cresce_na_mesma_hora_nao_repete(ambiente, monkeypatch):
    # o item da sentinela soma as quantidades das rodadas: a mensagem muda, o item e' o mesmo
    conn, tmp = ambiente
    _itens(monkeypatch, [_item("Leitura de cadastro por x.exe (conta), 3 arquivos", "10:05")])
    alertas_seguranca.rodada(conn, AGORA)
    _itens(monkeypatch, [_item("Leitura de cadastro por x.exe (conta), 9 arquivos", "10:10")])
    alertas_seguranca.rodada(conn, AGORA + datetime.timedelta(minutes=10))
    assert len(_alertas(tmp)) == 1


def test_mesmo_item_em_outra_hora_e_outro_email(ambiente, monkeypatch):
    conn, tmp = ambiente
    _itens(monkeypatch, [_item("Tarefa agendada criada por conta", "09:50"),
                         _item("Tarefa agendada criada por conta", "10:01")])
    alertas_seguranca.rodada(conn, AGORA)
    assert len(_alertas(tmp)) == 2


def test_atencao_nao_manda_alerta_imediato(ambiente, monkeypatch):
    conn, tmp = ambiente
    _itens(monkeypatch, [_item("Logon privilegiado de conta fora da lista", nivel="atencao")])
    alertas_seguranca.rodada(conn, AGORA)
    assert _alertas(tmp) == []


def test_falha_antes_do_envio_solta_e_tenta_de_novo_depois(ambiente, monkeypatch):
    conn, tmp = ambiente
    _itens(monkeypatch, [_item("Proteção da tabela de usuários removida", nivel="critico")])
    original = correio.enviar_e_registrar

    def falha(*a, **k):
        raise graph.ErroGraph("HTTP 503", status=503)

    monkeypatch.setattr(correio, "enviar_e_registrar", falha)
    alertas_seguranca.rodada(conn, AGORA)
    assert alertas_seguranca.situacao(conn) == "o último envio falhou (o serviço de e-mail não respondeu; tente de " \
                                              "novo mais tarde)"
    linha = conn.execute("SELECT * FROM alertas_seguranca_envios").fetchone()
    assert linha["envio_id"] is None and linha["envio_reservado_em"] is None
    monkeypatch.setattr(correio, "enviar_e_registrar", original)
    alertas_seguranca.rodada(conn, AGORA + datetime.timedelta(minutes=1))   # ainda na espera depois da falha
    assert _alertas(tmp) == []
    alertas_seguranca.rodada(conn, AGORA + datetime.timedelta(minutes=alertas_seguranca.ESPERA_FALHA_MIN))
    assert len(_alertas(tmp)) == 1
    assert alertas_seguranca.situacao(conn) is None


def test_envio_incerto_nao_repete_sozinho(ambiente, monkeypatch):
    conn, tmp = ambiente
    _itens(monkeypatch, [_item("Proteção da tabela de usuários removida", nivel="critico")])

    def incerto(*a, **k):
        raise correio.EnvioIncerto(None, "x", [PARA])

    monkeypatch.setattr(correio, "enviar_e_registrar", incerto)
    alertas_seguranca.rodada(conn, AGORA)
    assert conn.execute("SELECT envio_reservado_em FROM alertas_seguranca_envios").fetchone()[0] is not None
    assert "confira os Enviados" in alertas_seguranca.situacao(conn)
    chamadas = []
    monkeypatch.setattr(correio, "enviar_e_registrar", lambda *a, **k: chamadas.append(a[5]))
    alertas_seguranca.rodada(conn, AGORA + datetime.timedelta(hours=1))
    assert [assunto for assunto in chamadas if "alerta" in assunto] == []
    with db.mutacao(conn):                          # passados 15 minutos, a Saude le a marca do banco
        conn.execute("UPDATE alertas_seguranca_envios SET envio_reservado_em=datetime('now', '-20 minutes')")
    assert "confira os Enviados" in alertas_seguranca.situacao(conn)


# --- resumo diario ----------------------------------------------------------------------------------------------

def _resumos(tmp_path):
    return [m for m in _enviados(tmp_path) if "resumo de segurança" in m["assunto"]]


def _as(h, m=0, dia=5):
    return datetime.datetime(2026, 11, dia, h, m, tzinfo=CUIABA).astimezone(datetime.timezone.utc)


def test_resumo_vazio_as_sete_com_commit_e_hash(ambiente, monkeypatch):
    conn, tmp = ambiente
    _itens(monkeypatch, [])
    with db.mutacao(conn):
        auditoria.registrar(conn, None, "seguranca.alerta_resolvido", depois={"mensagem": "x"})
    alertas_seguranca.rodada(conn, _as(6, 59))
    assert _resumos(tmp) == []
    ultima = conn.execute("SELECT id, hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    alertas_seguranca.rodada(conn, _as(7, 0))
    [m] = _resumos(tmp)
    assert m["assunto"] == "Dashboard Lotufo: resumo de segurança de 05/11/2026"
    assert "Nada a relatar" in m["corpo"]
    assert "Commit em produção: abc1234" in m["corpo"]
    assert f"Auditoria: {total} linhas; última linha {ultima['id']}, hash {ultima['hash']}" in m["corpo"]
    assert f"auditoria conferir --linha {ultima['id']} --hash {ultima['hash']}" in m["corpo"]
    alertas_seguranca.rodada(conn, _as(9, 0))
    assert len(_resumos(tmp)) == 1                                  # um por dia
    alertas_seguranca.rodada(conn, _as(7, 1, dia=6))
    assert len(_resumos(tmp)) == 2


def test_resumo_cheio_traz_os_itens_das_ultimas_24_horas(ambiente, monkeypatch):
    conn, tmp = ambiente
    _itens(monkeypatch, [_item("Logon privilegiado de conta fora da lista", "08:00", "atencao", dia=4),
                         _item("Item de anteontem", "06:00", "atencao", dia=3),
                         _item("Proteção da tabela de usuários removida", "06:00", "critico", dia=1)])
    alertas_seguranca.rodada(conn, _as(7, 0))
    [m] = _resumos(tmp)
    assert "Nada a relatar" not in m["corpo"]
    assert "Logon privilegiado de conta fora da lista" in m["corpo"] and "04/11/2026 08:00" in m["corpo"]
    assert "Item de anteontem" not in m["corpo"]
    assert "Proteção da tabela de usuários removida" in m["corpo"]  # problema critico que continua aberto


def test_resumo_traz_copia_do_dono_e_sentinela(ambiente, monkeypatch):
    conn, tmp = ambiente
    _itens(monkeypatch, [])
    pasta = tmp / "dados" / "backups" / "dono"
    pasta.mkdir(parents=True)
    arq = pasta / "dashboard-dono-20261104-080000.tar.age"
    arq.write_bytes(b"x")
    import os
    quando = datetime.datetime(2026, 11, 4, 8, 0, tzinfo=CUIABA).timestamp()
    os.utime(arq, (quando, quando))
    monkeypatch.setattr(alertas_seguranca.sentinela, "situacao", lambda: {"roda": True, "mensagem": None})
    alertas_seguranca.rodada(conn, _as(7, 0))
    [m] = _resumos(tmp)
    assert "Última cópia do dono: 04/11/2026 08:00" in m["corpo"]
    assert "Sentinela: ativa" in m["corpo"]


# --- sem configuracao, modo copia --------------------------------------------------------------------------------

def test_sem_configuracao_nada_sai_so_log_e_saude_mostra(ambiente, monkeypatch, caplog):
    conn, tmp = ambiente
    with db.mutacao(conn):
        conn.execute("DELETE FROM cadastro_geral WHERE chave='alertas_seguranca'")
    _itens(monkeypatch, [_item("Proteção da tabela de usuários removida", nivel="critico")])
    alertas_seguranca.rodada(conn, _as(7, 0))
    assert _enviados(tmp) == []
    assert conn.execute("SELECT COUNT(*) FROM alertas_seguranca_envios").fetchone()[0] == 0
    assert alertas_seguranca.SEM_CADASTRO == alertas_seguranca.situacao(conn)
    assert "alertas de seguranca" in caplog.text


def test_sem_usuario_de_quem_envia_saude_mostra(ambiente, monkeypatch):
    conn, tmp = ambiente
    with db.mutacao(conn):
        conn.execute("UPDATE cadastro_geral SET valor=? WHERE chave='alertas_seguranca'",
                     (json.dumps({"para": [PARA], "enviada_por": ["outro@exemplo.com.br"]}),))
    _itens(monkeypatch, [_item("x", nivel="critico")])
    alertas_seguranca.rodada(conn, AGORA)
    assert _enviados(tmp) == []
    assert alertas_seguranca.situacao(conn) == alertas_seguranca.SEM_USUARIO


def test_modo_copia_nada_sai(ambiente, monkeypatch):
    conn, tmp = ambiente
    monkeypatch.setattr(instalacao, "ligada", lambda: False)
    _itens(monkeypatch, [_item("x", nivel="critico")])
    alertas_seguranca.rodada(conn, _as(7, 0))
    assert _enviados(tmp) == []
    assert conn.execute("SELECT COUNT(*) FROM alertas_seguranca_envios").fetchone()[0] == 0


def test_saude_traz_o_motivo_dos_alertas(client_admin):
    r = client_admin.get("/api/admin/saude")
    assert r.status_code == 200, r.text
    assert r.json()["alertas_seguranca"] == {"erro": alertas_seguranca.SEM_CADASTRO}
