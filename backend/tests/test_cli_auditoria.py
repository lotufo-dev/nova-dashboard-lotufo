"""`python -m app.cli auditoria conferir --linha N --hash H` (issue #424): o hash do resumo diario ancora a cadeia."""
from app import auditoria, auth, cli, db


def _banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn()
    db.migrate(c)
    auth.criar_usuario(c, "Dono", "dono@exemplo.com.br", "senha-forte-123", "admin")
    with db.mutacao(c):
        auditoria.registrar(c, None, "seguranca.alerta", depois={"mensagem": "x"})
    return c


def test_conferir_confere_e_nao_confere(tmp_path, monkeypatch, capsys):
    c = _banco(tmp_path, monkeypatch)
    linha = c.execute("SELECT id, hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    with db.mutacao(c):                                     # linhas novas depois do resumo nao mudam a ancora
        auditoria.registrar(c, None, "seguranca.alerta_resolvido", depois={"mensagem": "x"})
    assert cli.main(["auditoria", "conferir", "--linha", str(linha["id"]), "--hash", linha["hash"]]) == 0
    assert capsys.readouterr().out.strip() == "confere"
    trocado = ("0" if linha["hash"][0] != "0" else "1") + linha["hash"][1:]
    assert cli.main(["auditoria", "conferir", "--linha", str(linha["id"]), "--hash", trocado]) == 1
    assert capsys.readouterr().out.strip() == "não confere"
    assert cli.main(["auditoria", "conferir", "--linha", "999999", "--hash", linha["hash"]]) == 1
    assert capsys.readouterr().out.strip() == "não confere"
    c.close()


def test_auditoria_reescrita_nao_confere(tmp_path, monkeypatch, capsys):
    # quem reescreve a cadeia inteira recalcula os hashes: o enviado ontem deixa de existir
    c = _banco(tmp_path, monkeypatch)
    linha = c.execute("SELECT id, hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    primeira = c.execute("SELECT MIN(id) FROM audit_log").fetchone()[0]
    for t in [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_log'")]:
        c.execute(f"DROP TRIGGER {t}")
    c.execute("UPDATE audit_log SET acao='outra' WHERE id=?", (primeira,))
    c.commit()
    assert cli.main(["auditoria", "conferir", "--linha", str(linha["id"]), "--hash", linha["hash"]]) == 1
    assert capsys.readouterr().out.strip() == "não confere"
    c.close()
