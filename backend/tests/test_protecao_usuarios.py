"""Protecao das tabelas de usuarios e de sessoes (issue #422): fora da aplicacao o banco recusa criar, apagar ou mudar
uma conta (fora o contador de senha errada) e criar, mudar ou apagar uma sessao; a conferencia de hora em hora acusa no
bloco Seguranca a protecao removida e a cadeia da auditoria quebrada."""
import sqlite3

import pytest

from app import auditoria, auth, db, seguranca

PROTECAO = "Proteção da tabela de usuários removida"
SESSOES = "Proteção da tabela de sessões removida"
MIGRACAO = "062_protecao_usuarios.sql"
CADEIA = "Cadeia da auditoria quebrada"


@pytest.fixture(autouse=True)
def conferencia_limpa(monkeypatch):
    """O resultado da conferencia mora no processo: cada teste comeca sem conferencia e devolve o estado no fim."""
    monkeypatch.setattr(seguranca, "_conferencia", [])


@pytest.fixture
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "t.db"
    monkeypatch.setenv("DASH_DB_PATH", str(caminho))
    c = db.get_conn(); db.migrate(c)
    uid = auth.criar_usuario(c, "Engenheira", "eng@lotufo.com", "senha-forte-123", "engenharia")
    yield c, uid, caminho
    c.close()


def _crua(caminho):
    """Uma conexao como a do sqlite3 de linha de comando ou do DB Browser: sem a funcao da aplicacao."""
    c = sqlite3.connect(caminho)
    c.row_factory = sqlite3.Row
    return c


def _usuario(conn, uid):
    return tuple(conn.execute("SELECT id, nome, email, senha_hash, perfil, ativo, criado_em FROM usuarios WHERE id=?",
                              (uid,)).fetchone())


@pytest.mark.parametrize("sql", [
    "UPDATE usuarios SET perfil='admin' WHERE id=?",
    "UPDATE usuarios SET email='outro@lotufo.com' WHERE id=?",
    "UPDATE usuarios SET senha_hash='trocada' WHERE id=?",
    "UPDATE usuarios SET ativo=0 WHERE id=?",
    "UPDATE usuarios SET nome='Outra pessoa' WHERE id=?",
    "UPDATE usuarios SET criado_em='2000-01-01 00:00:00' WHERE id=?",
    # gate Sol S2: trocar os ids de duas contas faria as sessoes de uma resolverem para o perfil da outra
    "UPDATE usuarios SET id=id+1000 WHERE id=?",
    "DELETE FROM usuarios WHERE id=?",
])
def test_conexao_crua_nao_muda_nem_apaga_usuario(banco, sql):
    c, uid, caminho = banco
    antes = _usuario(c, uid)
    crua = _crua(caminho)
    with pytest.raises(sqlite3.OperationalError, match="dash_conexao_app"):
        crua.execute(sql, (uid,))
    crua.close()
    assert _usuario(c, uid) == antes


def test_conexao_crua_nao_cria_usuario(banco):
    c, _, caminho = banco
    crua = _crua(caminho)
    with pytest.raises(sqlite3.OperationalError, match="dash_conexao_app"):
        crua.execute("INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES ('X', 'x@lotufo.com', 'h', 'admin')")
    crua.close()
    assert c.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 1


def test_conexao_crua_le_e_mexe_nas_tentativas_e_no_bloqueio(banco):
    c, uid, caminho = banco
    crua = _crua(caminho)
    assert crua.execute("SELECT email FROM usuarios WHERE id=?", (uid,)).fetchone()[0] == "eng@lotufo.com"
    crua.execute("UPDATE usuarios SET tentativas_falhas=3, bloqueado_ate='2026-11-05 12:00:00' WHERE id=?", (uid,))
    crua.commit()
    assert crua.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    crua.close()
    assert tuple(c.execute("SELECT tentativas_falhas, bloqueado_ate FROM usuarios WHERE id=?", (uid,)).fetchone()) == (
        3, "2026-11-05 12:00:00")


def test_conexao_da_aplicacao_muda_e_apaga_usuario(banco):
    c, uid, _ = banco
    c.execute("UPDATE usuarios SET perfil='admin', email='nova@lotufo.com', senha_hash='h', ativo=0, nome='N' WHERE id=?",
              (uid,))
    assert _usuario(c, uid)[1:6] == ("N", "nova@lotufo.com", "h", "admin", 0)
    c.execute("DELETE FROM usuarios WHERE id=?", (uid,))
    assert c.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0
    c.rollback()


def test_migracao_rodada_duas_vezes_nao_falha(banco):
    c, _, _ = banco
    c.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); c.commit()
    db.migrate(c)
    for tabela, gatilhos in seguranca.GATILHOS.items():
        nomes = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabela,))}
        assert set(gatilhos) <= nomes
    assert seguranca.conferir(c) == []


@pytest.mark.parametrize("sql", [
    "INSERT INTO sessoes (token_hash, usuario_id, csrf_token, expira_em) VALUES ('conhecido', ?, 'c', '2099-01-01')",
    "UPDATE sessoes SET expira_em='2099-01-01T00:00:00+00:00' WHERE usuario_id=?",
    "UPDATE sessoes SET usuario_id=usuario_id WHERE usuario_id=?",
    "DELETE FROM sessoes WHERE usuario_id=?",
])
def test_conexao_crua_nao_cria_muda_nem_apaga_sessao(banco, sql):
    """Gate Sol S3: inserir uma sessao com um token conhecido seria entrar como a pessoa sem senha."""
    c, uid, caminho = banco
    token, _ = auth.criar_sessao(c, uid)
    antes = [tuple(r) for r in c.execute("SELECT * FROM sessoes")]
    crua = _crua(caminho)
    with pytest.raises(sqlite3.OperationalError, match="dash_conexao_app"):
        crua.execute(sql, (uid,))
    crua.close()
    assert [tuple(r) for r in c.execute("SELECT * FROM sessoes")] == antes
    assert auth.sessao_valida(c, token) is not None


def test_conexao_da_aplicacao_cria_e_encerra_sessao(banco):
    c, uid, _ = banco
    token, _ = auth.criar_sessao(c, uid)
    assert auth.sessao_valida(c, token) is not None
    auth.encerrar_sessao(c, token)
    assert auth.sessao_valida(c, token) is None


def test_conexao_da_aplicacao_liga_trusted_schema(banco):
    """A funcao do Python nao e' SQLITE_INNOCUOUS: com trusted_schema desligado o gatilho a recusaria na aplicacao."""
    c, uid, _ = banco
    assert c.execute("PRAGMA trusted_schema").fetchone()[0] == 1
    c.execute("PRAGMA trusted_schema=OFF")
    with pytest.raises(sqlite3.OperationalError, match="unsafe use"):
        c.execute("UPDATE usuarios SET perfil='admin' WHERE id=?", (uid,))


def _mensagens(conn):
    return [(i["nivel"], i["mensagem"]) for i in seguranca.itens(conn)]


def _alertas(conn):
    return [r[0] for r in conn.execute(
        "SELECT json_extract(depois, '$.mensagem') FROM audit_log WHERE acao='seguranca.alerta' ORDER BY id")]


def test_tudo_certo_nao_vira_item(banco):
    c, _, _ = banco
    assert seguranca.conferir(c) == []
    assert _mensagens(c) == [] and _alertas(c) == []


def test_gatilho_apagado_por_fora_vira_item_e_linha_na_auditoria(banco):
    c, _, caminho = banco
    crua = _crua(caminho)
    crua.execute("DROP TRIGGER usuarios_protecao_update"); crua.commit(); crua.close()
    seguranca.conferir(c)
    assert _mensagens(c) == [("critico", PROTECAO)]
    assert _alertas(c) == [PROTECAO]
    # a conferencia seguinte com o mesmo problema mantem o item e nao repete a linha na auditoria
    seguranca.conferir(c)
    assert _mensagens(c) == [("critico", PROTECAO)] and _alertas(c) == [PROTECAO]


def test_gatilho_trocado_por_outro_de_mesmo_nome_vira_item(banco):
    c, _, caminho = banco
    crua = _crua(caminho)
    crua.executescript("DROP TRIGGER usuarios_protecao_insert; "
                       "CREATE TRIGGER usuarios_protecao_insert BEFORE INSERT ON usuarios BEGIN SELECT 1; END;")
    crua.close()
    seguranca.conferir(c)
    assert _mensagens(c) == [("critico", PROTECAO)]


def test_cadeia_quebrada_vira_item_sem_linha_na_auditoria(banco):
    c, _, caminho = banco
    with db.mutacao(c):
        auditoria.registrar(c, None, "teste.evento", depois={"x": 1})
        auditoria.registrar(c, None, "teste.evento", depois={"x": 2})
    assert auditoria.verificar_cadeia(c)
    crua = _crua(caminho)
    crua.execute("UPDATE audit_log SET acao='adulterada' WHERE id=(SELECT MIN(id) FROM audit_log)"); crua.commit()
    crua.close()
    total = c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    seguranca.conferir(c)
    assert _mensagens(c) == [("critico", CADEIA)]
    assert c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == total


def test_problema_resolvido_some_na_conferencia_seguinte(banco):
    c, _, caminho = banco
    crua = _crua(caminho)
    crua.execute("DROP TRIGGER usuarios_protecao_delete"); crua.commit(); crua.close()
    seguranca.conferir(c)
    assert _mensagens(c) == [("critico", PROTECAO)]
    c.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); c.commit()
    db.migrate(c)
    seguranca.conferir(c)
    assert _mensagens(c) == []


def test_item_aparece_em_saude(client_admin):
    conn = db.get_conn()
    conn.execute("DROP TRIGGER usuarios_protecao_insert"); conn.commit()
    seguranca.conferir(conn)
    conn.close()
    r = client_admin.get("/api/admin/saude")
    assert r.status_code == 200, r.text
    assert (r.json()["seguranca"][0]["nivel"], r.json()["seguranca"][0]["mensagem"]) == ("critico", PROTECAO)


def test_login_errado_continua_contando_e_bloqueando(banco):
    c, uid, _ = banco
    for _ in range(5):
        assert auth.autenticar(c, "eng@lotufo.com", "errada") is None
    assert auth.autenticar(c, "eng@lotufo.com", "senha-forte-123") is None
    assert c.execute("SELECT bloqueado_ate FROM usuarios WHERE id=?", (uid,)).fetchone()[0] is not None


def test_item_critico_fica_no_topo_do_bloco_mesmo_mais_antigo(monkeypatch):
    antigo = {"nivel": "critico", "mensagem": PROTECAO, "data": "2026-11-01T10:00:00+00:00"}
    novos = [{"nivel": "atencao", "mensagem": f"Administrador {n} entrou de uma origem nova (10.0.0.{n})",
              "data": f"2026-11-05T10:{n:02d}:00+00:00"} for n in range(seguranca.ITENS_NA_TELA + 1)]
    monkeypatch.setattr(seguranca, "_conferencia", [antigo])
    monkeypatch.setattr(seguranca, "_origem_nova", lambda conn, agora: novos)
    itens, fora = seguranca.bloco(None)
    assert itens[0] == antigo and fora == 2
    assert [i["data"] for i in itens[1:]] == sorted((i["data"] for i in itens[1:]), reverse=True)


def _alertas_e_resolvidos(conn):
    return [tuple(r) for r in conn.execute(
        "SELECT acao, json_extract(depois, '$.mensagem') FROM audit_log WHERE acao LIKE 'seguranca.%' ORDER BY id")]


def test_gatilho_de_sessoes_apagado_vira_item(banco):
    c, _, caminho = banco
    crua = _crua(caminho)
    crua.execute("DROP TRIGGER sessoes_protecao_insert"); crua.commit(); crua.close()
    seguranca.conferir(c)
    assert _mensagens(c) == [("critico", SESSOES)]
    assert _alertas(c) == [SESSOES]


def test_reinicio_com_o_problema_presente_nao_repete_o_alerta_e_guarda_a_data(banco, monkeypatch):
    """Gate Sol S5: o incidente aberto mora na auditoria, nao so' no processo."""
    c, _, caminho = banco
    crua = _crua(caminho)
    crua.execute("DROP TRIGGER usuarios_protecao_update"); crua.commit(); crua.close()
    seguranca.conferir(c)
    data = seguranca.itens(c)[0]["data"]
    # o alerta passa a ser de dias atras; recuar a data quebra o hash, entao a cadeia fica dada como integra
    c.execute("UPDATE audit_log SET criado_em='2026-11-01 08:00:00' WHERE acao='seguranca.alerta'"); c.commit()
    monkeypatch.setattr(auditoria, "verificar_cadeia", lambda conn: True)
    monkeypatch.setattr(seguranca, "_conferencia", [])           # o processo novo nao lembra de nada
    seguranca.conferir(c)
    assert _alertas(c) == [PROTECAO]
    assert seguranca.itens(c)[0]["data"] == "2026-11-01T08:00:00+00:00" != data


def test_problema_resolvido_fecha_o_alerta_e_reaparecer_abre_outro(banco):
    c, _, caminho = banco
    crua = _crua(caminho)
    crua.execute("DROP TRIGGER usuarios_protecao_delete"); crua.commit(); crua.close()
    seguranca.conferir(c)
    c.execute("DELETE FROM schema_migrations WHERE nome=?", (MIGRACAO,)); c.commit()
    db.migrate(c)
    seguranca.conferir(c)
    seguranca.conferir(c)
    crua = _crua(caminho)
    crua.execute("DROP TRIGGER usuarios_protecao_delete"); crua.commit(); crua.close()
    seguranca.conferir(c)
    assert _alertas_e_resolvidos(c) == [("seguranca.alerta", PROTECAO), ("seguranca.alerta_resolvido", PROTECAO),
                                        ("seguranca.alerta", PROTECAO)]


def test_falha_ao_gravar_o_alerta_nao_esconde_o_item(banco, monkeypatch):
    """Gate Sol S6: o resultado e' publicado antes de gravar na auditoria."""
    c, _, caminho = banco
    crua = _crua(caminho)
    crua.execute("DROP TRIGGER usuarios_protecao_insert"); crua.commit(); crua.close()

    def falha(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(auditoria, "registrar", falha)
    assert [i["mensagem"] for i in seguranca.conferir(c)] == [PROTECAO]
    assert _mensagens(c) == [("critico", PROTECAO)] and _alertas(c) == []
    assert not c.in_transaction
