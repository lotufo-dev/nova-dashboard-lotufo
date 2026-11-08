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
    monkeypatch.setattr(alertas_seguranca, "_INCERTOS", set())
    monkeypatch.setattr(alertas_seguranca, "_SAIRAM", set())
    # o processo esta' no ar ha' mais que a carencia: o problema que some fecha o episodio
    monkeypatch.setattr(alertas_seguranca, "_INICIO", alertas_seguranca.time.monotonic() - 10 * 3600)
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
    # os alertas valem desde 01/11 (o marco que a primeira rodada com o cadastro grava)
    conn.execute("INSERT INTO alertas_seguranca_envios (chave, tipo, assunto, criado_em) "
                 "VALUES ('marco', 'marco', '', '2026-11-01 00:00:00')")
    conn.commit()
    yield conn, tmp_path
    conn.close()


def _enviados(tmp_path) -> list[dict]:
    pasta = tmp_path / "sim" / "enviados"
    return [json.loads(a.read_text(encoding="utf-8")) for a in sorted(pasta.glob("*.json"))] if pasta.exists() else []


def _itens(monkeypatch, itens):
    monkeypatch.setattr(seguranca, "itens", lambda conn, agora=None: list(itens))


def _item(mensagem, hora_local="10:00", nivel="acao", dia=5, identidade=None):
    h, m = map(int, hora_local.split(":"))
    data = datetime.datetime(2026, 11, dia, h, m, tzinfo=CUIABA).astimezone(datetime.timezone.utc)
    item = {"nivel": nivel, "mensagem": mensagem, "data": data.isoformat()}
    if identidade:
        item["identidade"] = identidade
    return item


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


LEITURA = "Leitura de cadastro por x.exe (conta), {} arquivos"


def test_leitura_da_sentinela_e_o_mesmo_item_enquanto_soma(ambiente, monkeypatch):
    # revisor/Sol C2: rodadas 10:12, 11:32 (o mesmo agregado da hora 10, com mais arquivos e data nova) e 13:22 (outro
    # agregado, da hora 13): dois e-mails
    conn, tmp = ambiente
    a, b = 'sentinela-leitura ["conta", "x.exe", "cadastro", "2026-11-05T10"]', \
        'sentinela-leitura ["conta", "x.exe", "cadastro", "2026-11-05T13"]'
    _itens(monkeypatch, [_item(LEITURA.format(3), "10:12", identidade=a)])
    alertas_seguranca.rodada(conn, _as(10, 12))
    _itens(monkeypatch, [_item(LEITURA.format(9), "11:32", identidade=a)])
    alertas_seguranca.rodada(conn, _as(11, 32))
    _itens(monkeypatch, [_item(LEITURA.format(9), "11:32", identidade=a), _item(LEITURA.format(2), "13:22", identidade=b)])
    alertas_seguranca.rodada(conn, _as(13, 22))
    _itens(monkeypatch, [_item(LEITURA.format(12), "15:40", identidade=a), _item(LEITURA.format(2), "13:22", identidade=b)])
    alertas_seguranca.rodada(conn, _as(15, 40))                 # leitura atrasada do agregado da hora 10
    assert [m["assunto"] for m in _alertas(tmp)] == [
        "Dashboard Lotufo: alerta de segurança: " + LEITURA.format(3),
        "Dashboard Lotufo: alerta de segurança: " + LEITURA.format(2)]


def test_leitura_da_sentinela_gravada_em_duas_rodadas_tem_uma_identidade(ambiente):
    from app import sentinela
    conn, tmp = ambiente
    achado = {"evento": 4663, "nivel": "acao", "conta": "conta", "processo": "x.exe", "pasta": "cadastro",
              "hora": "2026-11-05T10:05:00", "quantidade": 3}
    with db.mutacao(conn):
        auditoria.registrar(conn, None, sentinela.ACAO, "sentinela", None, None, achado)
    agora = tempo.agora_utc()
    alertas_seguranca.rodada(conn, agora)
    with db.mutacao(conn):
        auditoria.registrar(conn, None, sentinela.ACAO, "sentinela", None, None, {**achado, "quantidade": 4})
    [item] = seguranca.itens(conn, agora)
    assert item["mensagem"].endswith("7 arquivos") and item["identidade"]
    alertas_seguranca.rodada(conn, agora + datetime.timedelta(hours=2))
    assert len(_alertas(tmp)) == 1


def test_item_anterior_ao_marco_nao_vira_alerta(ambiente, monkeypatch):
    # Sol C5: o primeiro deploy nao manda o historico; o que vem depois do marco sai quando der, mesmo dias depois
    conn, tmp = ambiente
    with db.mutacao(conn):
        conn.execute("UPDATE alertas_seguranca_envios SET criado_em='2026-11-04 12:00:00' WHERE chave='marco'")
    _itens(monkeypatch, [_item("Administrador Dono entrou de uma origem nova (10.0.0.1)", "07:00", dia=4),
                         _item("Administrador Dono entrou de uma origem nova (10.0.0.2)", "09:00", dia=4)])
    alertas_seguranca.rodada(conn, AGORA + datetime.timedelta(days=2))
    assert [m["assunto"][-10:] for m in _alertas(tmp)] == ["(10.0.0.2)"]


def test_primeira_rodada_com_cadastro_grava_o_marco(ambiente, monkeypatch):
    conn, tmp = ambiente
    conn.execute("UPDATE alertas_seguranca_envios SET chave='marco-antigo' WHERE chave='marco'")
    conn.commit()
    _itens(monkeypatch, [_item("Administrador Dono entrou de uma origem nova (10.0.0.1)", "09:00")])
    alertas_seguranca.rodada(conn, AGORA)
    assert _alertas(tmp) == []
    marco = conn.execute("SELECT criado_em FROM alertas_seguranca_envios WHERE chave='marco'").fetchone()[0]
    assert marco == "2026-11-05 14:02:00"
    _itens(monkeypatch, [_item("Administrador Dono entrou de uma origem nova (10.0.0.3)", "10:30")])
    alertas_seguranca.rodada(conn, AGORA + datetime.timedelta(hours=1))
    assert len(_alertas(tmp)) == 1


def test_problema_aberto_sai_uma_vez_por_episodio_mesmo_depois_de_reiniciar(ambiente, monkeypatch):
    # revisor/Sol C1: a data do problema aberto mora na memoria do processo e muda a cada reinicio
    conn, tmp = ambiente
    problema = "Cadeia da auditoria quebrada"

    def aberto(hora):
        item = _item(problema, hora, "critico")
        monkeypatch.setattr(seguranca, "_conferencia", [item])
        _itens(monkeypatch, [item])

    aberto("10:00")
    alertas_seguranca.rodada(conn, _as(10, 2))
    aberto("13:00")                                             # reiniciou: a data mudou, o problema e' o mesmo
    monkeypatch.setattr(alertas_seguranca, "_INICIO", alertas_seguranca.time.monotonic())
    alertas_seguranca.rodada(conn, _as(13, 2))
    assert len(_alertas(tmp)) == 1
    monkeypatch.setattr(seguranca, "_conferencia", [])           # logo depois do reinicio: a conferencia nao rodou
    _itens(monkeypatch, [])
    alertas_seguranca.rodada(conn, _as(13, 3))
    aberto("13:04")
    alertas_seguranca.rodada(conn, _as(13, 4))
    assert len(_alertas(tmp)) == 1
    monkeypatch.setattr(alertas_seguranca, "_INICIO", alertas_seguranca.time.monotonic() - 10 * 3600)
    monkeypatch.setattr(seguranca, "_conferencia", [])           # o problema sumiu: o episodio fecha
    _itens(monkeypatch, [])
    alertas_seguranca.rodada(conn, _as(15, 0))
    aberto("16:00")                                             # e voltou: sai de novo
    alertas_seguranca.rodada(conn, _as(16, 2))
    assert len(_alertas(tmp)) == 2


def test_linha_ja_marcada_nao_envia(ambiente, monkeypatch):
    # revisor: outra rodada (ou outro processo) ja' marcou o envio deste grupo
    conn, tmp = ambiente
    item = _item("Tarefa agendada criada por conta", "10:05")
    with db.mutacao(conn):
        conn.execute("INSERT INTO alertas_seguranca_envios (chave, tipo, assunto, envio_reservado_em) VALUES (?,?,?,"
                     "datetime('now'))", ("alerta 2026-11-05 10 Tarefa agendada criada por conta", "alerta", "x"))
    _itens(monkeypatch, [item])
    alertas_seguranca.rodada(conn, AGORA)
    assert _alertas(tmp) == []


def test_assunto_sem_quebra_de_linha(ambiente, monkeypatch):
    conn, tmp = ambiente
    _itens(monkeypatch, [_item("Administrador A\r\nB entrou de uma origem nova (x)")])
    alertas_seguranca.rodada(conn, AGORA)
    [m] = _alertas(tmp)
    assert m["assunto"] == "Dashboard Lotufo: alerta de segurança: Administrador A B entrou de uma origem nova (x)"


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
    assert alertas_seguranca.situacao(conn)["erro"] == "o último envio falhou (o serviço de e-mail não respondeu; " \
                                                       "tente de novo mais tarde)"
    linha = conn.execute("SELECT * FROM alertas_seguranca_envios").fetchone()
    assert linha["envio_id"] is None and linha["envio_reservado_em"] is None
    monkeypatch.setattr(correio, "enviar_e_registrar", original)
    alertas_seguranca.rodada(conn, AGORA + datetime.timedelta(minutes=1))   # ainda na espera depois da falha
    assert _alertas(tmp) == []
    alertas_seguranca.rodada(conn, AGORA + datetime.timedelta(minutes=alertas_seguranca.ESPERA_FALHA_MIN))
    assert len(_alertas(tmp)) == 1
    assert alertas_seguranca.situacao(conn) == {"erro": None, "conectar": False}


def test_envio_incerto_nao_repete_sozinho(ambiente, monkeypatch):
    conn, tmp = ambiente
    _itens(monkeypatch, [_item("Proteção da tabela de usuários removida", nivel="critico")])

    def incerto(*a, **k):
        raise correio.EnvioIncerto(None, "x", [PARA])

    monkeypatch.setattr(correio, "enviar_e_registrar", incerto)
    alertas_seguranca.rodada(conn, AGORA)
    rid = conn.execute("SELECT id FROM alertas_seguranca_envios WHERE envio_reservado_em IS NOT NULL").fetchone()[0]
    assert f"o e-mail nº {rid} pode não ter saído" in alertas_seguranca.situacao(conn)["erro"]
    chamadas = []
    monkeypatch.setattr(correio, "enviar_e_registrar", lambda *a, **k: chamadas.append(a[5]))
    alertas_seguranca.rodada(conn, AGORA + datetime.timedelta(hours=1))
    assert [assunto for assunto in chamadas if "alerta" in assunto] == []
    # Sol C3: depois de reiniciar (memoria vazia), a marca parada continua na Saude, sem prazo, ate' alguem conferir
    monkeypatch.setattr(alertas_seguranca, "_INCERTOS", set())
    with db.mutacao(conn):
        conn.execute("UPDATE alertas_seguranca_envios SET envio_reservado_em=datetime('now', '-30 days') WHERE id=?",
                     (rid,))
    assert f"o e-mail nº {rid} pode não ter saído" in alertas_seguranca.situacao(conn)["erro"]
    uid = conn.execute("SELECT id FROM usuarios").fetchone()[0]
    alertas_seguranca.conferir_envio(conn, uid, rid, saiu=True)
    assert alertas_seguranca.situacao(conn)["erro"] is None
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE acao='seguranca.alerta_envio_conferido'").fetchone()[0] == 1


def test_queda_entre_a_marca_e_o_envio_fica_na_saude_e_nao_saiu_manda_de_novo(ambiente, monkeypatch):
    conn, tmp = ambiente
    item = _item("Proteção da tabela de usuários removida", "10:00", "critico")
    with db.mutacao(conn):                          # a marca ficou e o processo caiu antes do e-mail
        rid = conn.execute("INSERT INTO alertas_seguranca_envios (chave, tipo, assunto, envio_reservado_em) VALUES "
                           "(?,?,?,datetime('now', '-1 hour'))", ("alerta 2026-11-05 10 " + item["mensagem"], "alerta",
                                                                  "x")).lastrowid
    _itens(monkeypatch, [item])
    alertas_seguranca.rodada(conn, AGORA)
    assert _alertas(tmp) == []
    assert f"o e-mail nº {rid} pode não ter saído" in alertas_seguranca.situacao(conn)["erro"]
    uid = conn.execute("SELECT id FROM usuarios").fetchone()[0]
    alertas_seguranca.conferir_envio(conn, uid, rid, saiu=False)
    alertas_seguranca.rodada(conn, AGORA + datetime.timedelta(minutes=1))
    assert len(_alertas(tmp)) == 1
    assert alertas_seguranca.situacao(conn)["erro"] is None


def test_conferir_envio_recusa_o_que_nao_esta_parado(ambiente, monkeypatch):
    conn, tmp = ambiente
    uid = conn.execute("SELECT id FROM usuarios").fetchone()[0]
    with db.mutacao(conn):
        recente = conn.execute("INSERT INTO alertas_seguranca_envios (chave, tipo, assunto, envio_reservado_em) VALUES "
                               "('a', 'alerta', 'x', datetime('now'))").lastrowid
    with pytest.raises(ValueError, match="pode ainda estar saindo"):
        alertas_seguranca.conferir_envio(conn, uid, recente, saiu=True)
    with pytest.raises(ValueError, match="não está parado"):
        alertas_seguranca.conferir_envio(conn, uid, 999, saiu=True)


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
                         _item("Log de segurança limpo", "06:00", "critico", dia=1)])
    # problema que continua aberto (conferencia de hora em hora): entra mesmo visto ha' dias
    aberto = _item("Proteção da tabela de usuários removida", "06:00", "critico", dia=1)
    monkeypatch.setattr(seguranca, "_conferencia", [aberto])
    alertas_seguranca.rodada(conn, _as(7, 0))
    [m] = _resumos(tmp)
    assert "Nada a relatar" not in m["corpo"]
    assert "Logon privilegiado de conta fora da lista" in m["corpo"] and "04/11/2026 08:00" in m["corpo"]
    assert "Item de anteontem" not in m["corpo"]
    assert "Log de segurança limpo" not in m["corpo"]             # evento critico antigo, nao problema aberto
    assert "Proteção da tabela de usuários removida" in m["corpo"]


def test_resumo_diz_os_dias_sem_resumo_e_a_copia_ausente(ambiente, monkeypatch):
    # Sol A1/A3: servidor parado o dia inteiro; nenhuma copia do dono em disco
    conn, tmp = ambiente
    _itens(monkeypatch, [])
    alertas_seguranca.rodada(conn, _as(7, 0, dia=2))
    alertas_seguranca.rodada(conn, _as(8, 0, dia=5))
    *_, m = _resumos(tmp)
    assert "Sem resumo em: 03/11/2026, 04/11/2026" in m["corpo"]
    assert "Última cópia do dono: nenhuma encontrada" in m["corpo"]
    alertas_seguranca.rodada(conn, _as(7, 0, dia=6))
    assert "Sem resumo" not in _resumos(tmp)[-1]["corpo"]


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
    with db.mutacao(conn):
        alertas_seguranca.sentinela._gravar_ponto(conn, 42)
        conn.execute("UPDATE sentinela_ponto SET atualizado_em='2026-11-05 10:55:00' WHERE id=1")
    alertas_seguranca.rodada(conn, _as(7, 0))
    [m] = _resumos(tmp)
    assert "Última cópia do dono: 04/11/2026 08:00" in m["corpo"]
    assert "Sentinela: última leitura do log em 05/11/2026 06:55" in m["corpo"]


def test_resumo_diz_quando_a_sentinela_nao_roda(ambiente, monkeypatch):
    conn, tmp = ambiente
    _itens(monkeypatch, [])
    monkeypatch.setattr(alertas_seguranca.sentinela, "situacao",
                        lambda: {"roda": False, "mensagem": "Sentinela não roda neste ambiente"})
    alertas_seguranca.rodada(conn, _as(7, 0))
    [m] = _resumos(tmp)
    assert "Sentinela: Sentinela não roda neste ambiente" not in m["corpo"]
    assert "Sentinela não roda neste ambiente" in m["corpo"]


# --- sem configuracao, modo copia --------------------------------------------------------------------------------

def test_sem_configuracao_nada_sai_so_log_e_saude_mostra(ambiente, monkeypatch, caplog):
    conn, tmp = ambiente
    with db.mutacao(conn):
        conn.execute("DELETE FROM cadastro_geral WHERE chave='alertas_seguranca'")
    _itens(monkeypatch, [_item("Proteção da tabela de usuários removida", nivel="critico")])
    alertas_seguranca.rodada(conn, _as(7, 0))
    assert _enviados(tmp) == []
    assert conn.execute("SELECT COUNT(*) FROM alertas_seguranca_envios WHERE tipo != 'marco'").fetchone()[0] == 0
    assert alertas_seguranca.situacao(conn) == {"erro": alertas_seguranca.SEM_CADASTRO, "conectar": False}
    assert "alertas de seguranca" in caplog.text


def test_sem_usuario_de_quem_envia_saude_mostra(ambiente, monkeypatch):
    conn, tmp = ambiente
    with db.mutacao(conn):
        conn.execute("UPDATE cadastro_geral SET valor=? WHERE chave='alertas_seguranca'",
                     (json.dumps({"para": [PARA], "enviada_por": ["outro@exemplo.com.br"]}),))
    _itens(monkeypatch, [_item("x", nivel="critico")])
    alertas_seguranca.rodada(conn, AGORA)
    assert _enviados(tmp) == []
    assert alertas_seguranca.situacao(conn) == {"erro": alertas_seguranca.SEM_USUARIO, "conectar": False}


def test_conta_desconectada_leva_a_minha_conta(ambiente, monkeypatch, tmp_path):
    conn, tmp = ambiente
    monkeypatch.delenv("DASH_GRAPH_SIMULADOR")
    monkeypatch.setenv("DASH_GRAPH_CLIENT_ID", "00000000-0000-0000-0000-000000000000")
    monkeypatch.setenv("DASH_GRAPH_TOKENS_DIR", str(tmp_path / "tokens"))
    assert alertas_seguranca.situacao(conn) == {
        "erro": f"nada sai: a conta Microsoft de {DONO} não está conectada", "conectar": True}


def test_modo_copia_nada_sai(ambiente, monkeypatch):
    conn, tmp = ambiente
    monkeypatch.setattr(instalacao, "ligada", lambda: False)
    _itens(monkeypatch, [_item("x", nivel="critico")])
    alertas_seguranca.rodada(conn, _as(7, 0))
    assert _enviados(tmp) == []
    assert conn.execute("SELECT COUNT(*) FROM alertas_seguranca_envios WHERE tipo != 'marco'").fetchone()[0] == 0


def test_saude_traz_o_motivo_dos_alertas(client_admin):
    r = client_admin.get("/api/admin/saude")
    assert r.status_code == 200, r.text
    assert r.json()["alertas_seguranca"] == {"erro": alertas_seguranca.SEM_CADASTRO, "conectar": False}


def test_linha_de_comando_registra_o_resultado_do_email_parado(ambiente, capsys):
    from app import cli
    conn, tmp = ambiente
    with db.mutacao(conn):
        rid = conn.execute("INSERT INTO alertas_seguranca_envios (chave, tipo, assunto, envio_reservado_em) VALUES "
                           "('a', 'alerta', 'x', datetime('now', '-1 hour'))").lastrowid
    assert cli.main(["alertas", "conferir-envio", "--id", str(rid), "--saiu", "--usuario", "ninguem@exemplo.com.br"]) == 1
    assert cli.main(["alertas", "conferir-envio", "--id", str(rid), "--saiu", "--usuario", DONO]) == 0
    assert "o e-mail saiu" in capsys.readouterr().out
    assert conn.execute("SELECT envio_conferido_em FROM alertas_seguranca_envios WHERE id=?", (rid,)).fetchone()[0]
    assert cli.main(["alertas", "conferir-envio", "--id", str(rid), "--nao-saiu", "--usuario", DONO]) == 1


# --- rodada 2 da revisao ---------------------------------------------------------------------------------------

def _sem_registro(*a, **k):
    raise correio.EnvioNaoRegistrado("<id>", "x", [PARA])


def test_enviado_sem_registro_fica_como_saido_e_nao_aceita_nao_saiu(ambiente, monkeypatch):
    # revisor: EnvioNaoRegistrado puro = o e-mail SAIU; "nao saiu" mandaria o alerta duas vezes
    conn, tmp = ambiente
    _itens(monkeypatch, [_item("Proteção da tabela de usuários removida", nivel="critico")])
    monkeypatch.setattr(correio, "enviar_e_registrar", _sem_registro)
    alertas_seguranca.rodada(conn, AGORA)
    linha = conn.execute("SELECT * FROM alertas_seguranca_envios WHERE tipo='alerta'").fetchone()
    assert linha["envio_conferido_em"] is not None and linha["envio_reservado_em"] is None
    assert alertas_seguranca.situacao(conn)["erro"] is None
    uid = conn.execute("SELECT id FROM usuarios").fetchone()[0]
    with pytest.raises(ValueError):
        alertas_seguranca.conferir_envio(conn, uid, linha["id"], saiu=False)
    chamadas = []
    monkeypatch.setattr(correio, "enviar_e_registrar", lambda *a, **k: chamadas.append(a[5]))
    alertas_seguranca.rodada(conn, AGORA + datetime.timedelta(hours=1))
    assert [x for x in chamadas if "alerta" in x] == []


def test_enviado_sem_registro_e_marcacao_que_falha_fica_na_memoria_ate_gravar(ambiente, monkeypatch):
    conn, tmp = ambiente
    _itens(monkeypatch, [_item("Proteção da tabela de usuários removida", nivel="critico")])
    monkeypatch.setattr(correio, "enviar_e_registrar", _sem_registro)
    original = alertas_seguranca._marcar_saida

    def falha(conn, rid, envio_id=None):
        alertas_seguranca._SAIRAM.add(rid)
        return False

    monkeypatch.setattr(alertas_seguranca, "_marcar_saida", falha)
    alertas_seguranca.rodada(conn, AGORA)
    rid = conn.execute("SELECT id FROM alertas_seguranca_envios WHERE tipo='alerta'").fetchone()[0]
    with db.mutacao(conn):                          # a marca ficou e ja' passou dos 15 minutos
        conn.execute("UPDATE alertas_seguranca_envios SET envio_reservado_em=datetime('now', '-1 hour') WHERE id=?",
                     (rid,))
    erro = alertas_seguranca.situacao(conn)["erro"]
    assert f"o e-mail nº {rid} saiu sem registro" in erro and "pode não ter saído" not in erro
    uid = conn.execute("SELECT id FROM usuarios").fetchone()[0]
    with pytest.raises(ValueError, match="saiu"):
        alertas_seguranca.conferir_envio(conn, uid, rid, saiu=False)
    monkeypatch.setattr(alertas_seguranca, "_marcar_saida", original)
    alertas_seguranca.rodada(conn, AGORA + datetime.timedelta(hours=1))   # a rodada seguinte grava
    assert conn.execute("SELECT envio_conferido_em FROM alertas_seguranca_envios WHERE id=?", (rid,)).fetchone()[0]
    assert alertas_seguranca._SAIRAM == set()


def _parada(conn, chave, tipo="alerta", mensagem=None, resolvido=None):
    with db.mutacao(conn):
        return conn.execute("INSERT INTO alertas_seguranca_envios (chave, tipo, assunto, mensagem, problema_resolvido_em, "
                            "envio_reservado_em) VALUES (?,?,?,?,?,datetime('now', '-1 hour'))",
                            (chave, tipo, "x", mensagem, resolvido)).lastrowid


def test_nao_saiu_diz_se_o_email_ainda_vai_sair(ambiente, monkeypatch):
    # revisor: resumo de dia passado, item que saiu do bloco e episodio fechado nao saem mais
    conn, tmp = ambiente
    uid = conn.execute("SELECT id FROM usuarios").fetchone()[0]
    hoje = tempo.para_local(tempo.agora_utc()).date()
    item = _item("Tarefa agendada criada por conta", "10:05")
    _itens(monkeypatch, [item])
    casos = {
        _parada(conn, f"resumo {hoje.isoformat()}", "resumo"): True,
        _parada(conn, "resumo 2026-01-01", "resumo"): False,
        _parada(conn, "alerta 2026-11-05 10 Tarefa agendada criada por conta"): True,
        _parada(conn, "alerta 2026-11-02 10 Item que saiu do bloco"): False,
        _parada(conn, "aberto 1 Cadeia", mensagem="Cadeia"): None,
        _parada(conn, "aberto 2 Cadeia", mensagem="Cadeia", resolvido="2026-11-05 00:00:00"): False,
    }
    for rid, esperado in casos.items():
        assert alertas_seguranca.conferir_envio(conn, uid, rid, saiu=False) is esperado, rid


def test_falha_passageira_do_git_nao_fecha_o_episodio_do_codigo(ambiente, monkeypatch):
    # revisor: DIFERENTE -> ERRO (atencao, fora do bloco imediato) -> DIFERENTE nao manda um segundo e-mail
    conn, tmp = ambiente
    i = alertas_seguranca.integridade
    diferente = {"estado": i.DIFERENTE, "detalhe": "2 arquivos", "data": _item("x", "10:00")["data"], "assinatura": "a"}

    def estado(e):
        monkeypatch.setattr(i, "ESTADO", e)
        _itens(monkeypatch, i.itens())

    estado(diferente)
    alertas_seguranca.rodada(conn, _as(10, 2))
    estado({**diferente, "estado": i.ERRO, "detalhe": None})
    alertas_seguranca.rodada(conn, _as(11, 2))
    estado({**diferente, "data": _item("x", "12:00")["data"]})
    alertas_seguranca.rodada(conn, _as(12, 2))
    assert len(_alertas(tmp)) == 1
    estado({**diferente, "estado": i.OK, "detalhe": None})           # igual ao deploy: o episodio fecha
    alertas_seguranca.rodada(conn, _as(13, 2))
    estado({**diferente, "data": _item("x", "14:00")["data"]})
    alertas_seguranca.rodada(conn, _as(14, 2))
    assert len(_alertas(tmp)) == 2
