"""`python -m app.cli medicoes planilhas <instrumento> <pasta>`: carga do medido por grupo (issue #490)."""
import sqlite3

import pytest

from app import auth, cli, contratos, db
from tests.test_leitura_planilha_medicao import TOTAL, planilha


@pytest.fixture
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    c = db.get_conn()
    db.migrate(c)
    auth.criar_usuario(c, "U", "u@lotufo.com", "senha-forte-123", "admin")
    cid = contratos.criar(c, None, {"orgao": "SINFRA", "numero_instrumento": "IC 9/2026", "objeto": "Obra",
                                    "valor_original_centavos": 1_000_000_00})
    for numero, valor, tipo in ((1, TOTAL, "execucao"), (2, TOTAL + 50_00, "execucao"), (3, TOTAL, "reajuste")):
        c.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos, "
                  "valor_protocolado_origem) VALUES (?,?,?,?, 'recebida', ?, 'manual')",
                  (cid, numero, tipo, f"2026-0{numero}", valor))
    c.commit()
    c.close()
    return tmp_path


def _contar(sql):
    c = db.get_conn()
    try:
        return c.execute(sql).fetchone()[0]
    finally:
        c.close()


def test_carga_registra_pula_e_e_idempotente(banco, capsys):
    pasta = banco / "planilhas"
    pasta.mkdir()
    (pasta / "01ª Medição (01_2026) - Obra.xlsx").write_bytes(planilha())
    (pasta / "02ª Medição (02_2026) - Obra.xlsx").write_bytes(planilha())      # pedido 50,00 acima: recusa
    (pasta / "07ª Medição.xlsx").write_bytes(planilha())                       # sem medicao nº 7
    (pasta / "Resumo geral.xlsx").write_bytes(planilha())                      # sem nº no nome
    (pasta / "leia-me.pdf").write_bytes(b"%PDF-")
    args = ["medicoes", "planilhas", "IC 9/2026", str(pasta), "--usuario", "u@lotufo.com"]

    assert cli.main(args + ["--ensaio"]) == 0
    saida = capsys.readouterr().out
    assert "ENSAIO" in saida and _contar("SELECT COUNT(*) FROM medicao_grupos") == 0

    assert cli.main(args) == 0
    saida = capsys.readouterr().out
    linhas = {ln.split(":")[0].strip(): ln for ln in saida.splitlines() if ln.startswith("  ") and ".xlsx" in ln}
    assert "Medição 1 de execução" in linhas["01ª Medição (01_2026) - Obra.xlsx"]
    assert "lido R$ 20.693,10" in linhas["01ª Medição (01_2026) - Obra.xlsx"]
    assert "gravada" in linhas["01ª Medição (01_2026) - Obra.xlsx"]
    assert "recusada: diferença de R$ 50,00" in linhas["02ª Medição (02_2026) - Obra.xlsx"]
    assert "diferença -R$ 50,00" in linhas["02ª Medição (02_2026) - Obra.xlsx"]
    assert "pulado: nenhuma medição de execução nº 7" in linhas["07ª Medição.xlsx"]
    assert "pulado: sem o nº da medição" in linhas["Resumo geral.xlsx"]
    assert "gravada: 1" in saida and "recusada: 1" in saida
    assert _contar("SELECT COUNT(*) FROM medicao_grupos") == 1      # a recusa da carga so' se imprime
    assert _contar("SELECT COUNT(*) FROM medicao_grupo_itens") == 5
    assert _contar("SELECT origem FROM medicao_grupos") == "carga"
    assert _contar("SELECT planilha_id IS NULL FROM medicao_grupos") == 1

    assert cli.main(args) == 0                                       # de novo: nada duplica
    assert "já lida antes" in capsys.readouterr().out
    assert _contar("SELECT COUNT(*) FROM medicao_grupos") == 1
    assert _contar("SELECT COUNT(*) FROM medicao_grupo_itens") == 5


def test_carga_contrato_ou_pasta_que_nao_existe(banco, capsys):
    assert cli.main(["medicoes", "planilhas", "IC 0/0000", str(banco)]) == 1
    assert "Contrato não encontrado" in capsys.readouterr().out
    assert cli.main(["medicoes", "planilhas", "IC 9/2026", str(banco / "nao-existe")]) == 1
    assert "Pasta não encontrada" in capsys.readouterr().out


def test_medicao_de_reajuste_nao_entra(banco, capsys):
    pasta = banco / "p"
    pasta.mkdir()
    (pasta / "03ª Medição.xlsx").write_bytes(planilha())
    assert cli.main(["medicoes", "planilhas", "IC 9/2026", str(pasta)]) == 0
    assert "pulado: nenhuma medição de execução nº 3" in capsys.readouterr().out


def test_leitura_e_evento_que_nao_se_altera_nem_se_apaga(banco):
    pasta = banco / "p"
    pasta.mkdir()
    (pasta / "01ª.xlsx").write_bytes(planilha())
    assert cli.main(["medicoes", "planilhas", "IC 9/2026", str(pasta)]) == 0
    c = db.get_conn()
    try:
        for sql in ("UPDATE medicao_grupos SET total_centavos=1", "DELETE FROM medicao_grupos",
                    "UPDATE medicao_grupo_itens SET grupo='x'", "DELETE FROM medicao_grupo_itens"):
            with pytest.raises(sqlite3.IntegrityError, match="evento"):
                c.execute(sql)
        # a mesma planilha na mesma versao nao entra duas vezes nem por fora da aplicacao
        r = c.execute("SELECT medicao_id, sha256 FROM medicao_grupos").fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO medicao_grupos (medicao_id, sha256, origem, situacao) VALUES (?,?,'carga','lida')",
                      (r["medicao_id"], r["sha256"]))
    finally:
        c.close()


def test_dois_arquivos_da_mesma_medicao_e_medicao_com_planilha_anexada_sao_pulados(banco, capsys):
    c = db.get_conn()
    mid = c.execute("SELECT id FROM medicoes WHERE numero=2").fetchone()[0]
    c.execute("INSERT INTO medicao_planilhas (medicao_id, versao, valor_pedido_centavos, acumulado_anterior_centavos, "
              "origem) VALUES (?, 1, ?, 0, 'manual')", (mid, TOTAL))
    c.commit()
    c.close()
    pasta = banco / "p"
    pasta.mkdir()
    (pasta / "01ª Medição.xlsx").write_bytes(planilha())
    (pasta / "01ª Medição Rev01.xlsx").write_bytes(planilha())
    (pasta / "02ª Medição.xlsx").write_bytes(planilha())
    assert cli.main(["medicoes", "planilhas", "IC 9/2026", str(pasta)]) == 0
    saida = capsys.readouterr().out
    assert saida.count("mais de um arquivo da medição nº 1") == 2
    assert "a medição tem planilha/carta anexada" in saida
    assert _contar("SELECT COUNT(*) FROM medicao_grupos") == 0
