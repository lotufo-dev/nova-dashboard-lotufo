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
        r = c.execute("SELECT medicao_id, sha256, pedido_centavos FROM medicao_grupos").fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO medicao_grupos (medicao_id, sha256, origem, situacao, total_centavos, "
                      "pedido_centavos) VALUES (?,?,'carga','lida',1,?)",
                      (r["medicao_id"], r["sha256"], r["pedido_centavos"]))
        with pytest.raises(sqlite3.IntegrityError):          # leitura valida sem o pedido conferido
            c.execute("INSERT INTO medicao_grupos (medicao_id, sha256, origem, situacao, total_centavos) "
                      "VALUES (?,'outro','carga','lida',1)", (r["medicao_id"],))
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


# --- rodada 1 de correcao (revisor-adversarial e gate Sol) ----------------------------------------------------

def _pasta_com(banco, nome="01ª Medição.xlsx", dados=None):
    pasta = banco / "pasta"
    pasta.mkdir(exist_ok=True)
    (pasta / nome).write_bytes(dados if dados is not None else planilha())
    return pasta


def _executar(pasta):
    assert cli.main(["medicoes", "planilhas", "IC 9/2026", str(pasta)]) == 0


def test_pedido_novo_da_medicao_pede_leitura_nova(banco, capsys):
    """Sol S1: a carga repetida so' reaproveita a leitura se o pedido da medicao continua o mesmo."""
    pasta = _pasta_com(banco)
    _executar(pasta)
    c = db.get_conn()
    c.execute("UPDATE medicoes SET valor_protocolado_centavos=? WHERE numero=1 AND tipo='execucao'", (TOTAL + 500_00,))
    c.commit()
    c.close()
    capsys.readouterr()
    _executar(pasta)
    saida = capsys.readouterr().out
    assert "recusada: diferença de R$ 500,00" in saida and "-> já lida antes" not in saida
    # rodada 2, Sol S1: a leitura feita contra o pedido antigo nao vale mais na consulta
    assert _grupos(1) == ("sem_leitura", None)


def test_pedido_que_muda_durante_a_leitura_e_conferido_sob_o_lock(banco, capsys, monkeypatch):
    """Sol S1: o pedido conferido e' o relido dentro da transacao, nao o lido antes de abrir o xlsx."""
    from app import leitura_planilha_medicao as leitura
    original = leitura.ler

    def ler_e_mudar(dados, cadastro=None):
        c = db.get_conn()
        c.execute("UPDATE medicoes SET valor_protocolado_centavos=? WHERE numero=1 AND tipo='execucao'",
                  (TOTAL + 500_00,))
        c.commit()
        c.close()
        return original(dados, cadastro)

    monkeypatch.setattr(leitura, "ler", ler_e_mudar)
    _executar(_pasta_com(banco))
    assert "recusada: diferença de R$ 500,00" in capsys.readouterr().out
    assert _contar("SELECT COUNT(*) FROM medicao_grupos") == 0


def _cadastro_de_custo(grupos_):
    import json
    c = db.get_conn()
    cid = c.execute("SELECT id FROM contratos").fetchone()[0]
    for i, (nome, itens) in enumerate(grupos_, 1):
        c.execute("INSERT INTO custo_grupos (contrato_id, ordem, nome, tarefas, itens_planilha) VALUES (?,?,?,?,?)",
                  (cid, i, nome, json.dumps(["001"]), json.dumps(itens)))
    c.commit()
    c.close()


def test_carga_agrupa_pelo_cadastro_de_custo_da_obra(banco):
    """Sol S2: com cadastro de custo (#489), a leitura gravada usa os grupos dele, na ordem do yaml."""
    from app import medicao_grupos
    _cadastro_de_custo([("Drenagem", ["3"]), ("Terraplanagem", ["2."])])
    _executar(_pasta_com(banco))
    c = db.get_conn()
    try:
        mid = c.execute("SELECT id FROM medicoes WHERE numero=1 AND tipo='execucao'").fetchone()[0]
        g = medicao_grupos.grupos(c, mid)
    finally:
        c.close()
    assert g["leitura"]["grupo_por"] == "cadastro"
    assert [(x["nome"], x["valor_medido_centavos"]) for x in g["grupos"]] == [
        ("Drenagem", 8505_00), ("Terraplanagem", 2188_09), ("outros", 10000_01)]


def test_cadastro_novo_depois_da_carga_pede_leitura_nova(banco, capsys):
    """Sol S2: a leitura e' imutavel, mas o cadastro aplicado depois nao fica preso a ela: a carga le de novo."""
    from app import medicao_grupos
    pasta = _pasta_com(banco)
    _executar(pasta)
    _cadastro_de_custo([("Drenagem", ["3"])])
    capsys.readouterr()
    _executar(pasta)
    assert "gravada" in capsys.readouterr().out
    c = db.get_conn()
    try:
        mid = c.execute("SELECT id FROM medicoes WHERE numero=1 AND tipo='execucao'").fetchone()[0]
        assert medicao_grupos.grupos(c, mid)["leitura"]["grupo_por"] == "cadastro"
    finally:
        c.close()
    assert _contar("SELECT COUNT(*) FROM medicao_grupos") == 2


def test_carga_le_o_anexo_vigente_das_medicoes_com_planilha_anexada(banco, capsys):
    """Sol S3: medicao com planilha/carta anexada antes desta leitura existir entra pela carga, lida do proprio
    anexo e ligada a versao vigente; o arquivo da pasta para ela e' pulado."""
    from app import arquivos, medicao_grupos
    c = db.get_conn()
    mid = c.execute("SELECT id FROM medicoes WHERE numero=2").fetchone()[0]
    rel, sha = arquivos.gravar_bytes("planilhas", planilha(), "xlsx")
    c.execute("INSERT INTO medicao_planilhas (medicao_id, versao, valor_pedido_centavos, acumulado_anterior_centavos, "
              "arquivo_planilha, sha256_planilha, origem) VALUES (?, 1, ?, 0, ?, ?, 'manual')", (mid, TOTAL, rel, sha))
    pid = c.execute("SELECT id FROM medicao_planilhas WHERE medicao_id=?", (mid,)).fetchone()[0]
    c.commit()
    c.close()
    _executar(_pasta_com(banco, "02ª Medição.xlsx"))
    saida = capsys.readouterr().out
    assert "02ª Medição.xlsx: Medição 2 de execução -> pulado: a medição tem planilha/carta anexada" in saida
    assert "anexo da versão 1: Medição 2 de execução; lido R$ 20.693,10" in saida and "gravada" in saida
    c = db.get_conn()
    try:
        g = medicao_grupos.grupos(c, mid)
        assert g["situacao"] == "lida" and g["leitura"]["planilha_id"] == pid and g["leitura"]["origem"] == "anexo"
    finally:
        c.close()
    _executar(banco / "pasta")
    assert "anexo da versão 1: Medição 2 de execução; lido R$ 20.693,10; pedido R$ 20.693,10, diferença R$ 0,00 -> " \
           "já lida antes" in capsys.readouterr().out
    assert _contar("SELECT COUNT(*) FROM medicao_grupos") == 1


def test_arquivo_grande_demais_e_pulado_sem_ler(banco, capsys, monkeypatch):
    """Sol S6 / #503: o arquivo acima do teto e' pulado lendo no maximo o teto mais um byte (nunca inteiro)."""
    import builtins

    from app import leitura_planilha_medicao as leitura
    from app import medicao_grupos
    monkeypatch.setattr(leitura, "MAX_BYTES_ARQUIVO", 1000)
    lidos = []

    class Espiao:
        def __init__(self, f):
            self._f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._f.close()

        def __getattr__(self, nome):
            return getattr(self._f, nome)

        def read(self, *args):
            dados = self._f.read(*args)
            lidos.append(len(dados))
            return dados

    monkeypatch.setattr(medicao_grupos, "open", lambda *a, **k: Espiao(builtins.open(*a, **k)), raising=False)
    _executar(_pasta_com(banco))                                      # a planilha tem bem mais de 1000 bytes
    assert "pulado: arquivo grande demais" in capsys.readouterr().out
    assert lidos and sum(lidos) <= 1001


# --- rodada 2 de correcao -----------------------------------------------------------------------------------------

def _grupos(numero, tipo="execucao"):
    """(situacao, grupo_por da leitura que vale) da medicao, pela consulta da tela."""
    from app import medicao_grupos
    c = db.get_conn()
    try:
        mid = c.execute("SELECT id FROM medicoes WHERE numero=? AND tipo=?", (numero, tipo)).fetchone()[0]
        g = medicao_grupos.grupos(c, mid)
    finally:
        c.close()
    return g["situacao"], g["leitura"]["grupo_por"] if g["leitura"] else None


def test_cadastro_novo_deixa_a_leitura_antiga_de_lado_ate_ler_de_novo(banco):
    """Sol S1 (rodada 2): leitura feita com outro cadastro nao vale na consulta."""
    _executar(_pasta_com(banco))
    assert _grupos(1) == ("lida", "planilha")
    _cadastro_de_custo([("Drenagem", ["3"])])
    assert _grupos(1) == ("sem_leitura", None)


def test_medicao_que_deixou_de_ser_execucao_fica_sem_leitura(banco):
    """Sol S1 (rodada 2): corrigida para projeto, a medicao nao tem leitura por grupo."""
    _executar(_pasta_com(banco))
    c = db.get_conn()
    c.execute("UPDATE medicoes SET tipo='projeto' WHERE numero=1 AND tipo='execucao'")
    c.commit()
    c.close()
    assert _grupos(1, "projeto") == ("sem_leitura", None)


def test_pedido_que_muda_antes_do_lock_nao_reaproveita_a_leitura_antiga(banco, capsys, monkeypatch):
    """Sol S2 (rodada 2): achar a leitura antiga antes do lock e' so' dica; sob o lock, com o pedido novo, nao ha'
    o que reaproveitar."""
    from app import medicao_grupos
    pasta = _pasta_com(banco)
    _executar(pasta)
    original = medicao_grupos._anterior
    chamadas = []

    def anterior_e_mudar(conn, *a):
        r = original(conn, *a)
        if not chamadas:                    # outra conexao muda o pedido logo depois da primeira olhada
            c = db.get_conn()
            c.execute("UPDATE medicoes SET valor_protocolado_centavos=? WHERE numero=1 AND tipo='execucao'",
                      (TOTAL + 500_00,))
            c.commit()
            c.close()
        chamadas.append(r)
        return r

    monkeypatch.setattr(medicao_grupos, "_anterior", anterior_e_mudar)
    capsys.readouterr()
    _executar(pasta)
    saida = capsys.readouterr().out
    assert chamadas[0] is not None                                   # a dica achou a leitura antiga
    assert "recusada: diferença de R$ 500,00" in saida and "-> já lida antes" not in saida


def _anexar(numero, dados, sha=None):
    from app import arquivos
    c = db.get_conn()
    mid = c.execute("SELECT id FROM medicoes WHERE numero=? AND tipo='execucao'", (numero,)).fetchone()[0]
    rel, sha_real = arquivos.gravar_bytes("planilhas", dados, "xlsx")
    c.execute("INSERT INTO medicao_planilhas (medicao_id, versao, valor_pedido_centavos, acumulado_anterior_centavos, "
              "arquivo_planilha, sha256_planilha, origem) VALUES (?, 1, ?, 0, ?, ?, 'manual')",
              (mid, TOTAL, rel, sha or sha_real))
    c.commit()
    c.close()


def test_recusa_repetida_com_cadastro_nao_duplica(banco, capsys):
    """Sol S3/revisor A1 (rodada 2): a recusa grava a impressao do cadastro; a carga repetida a reaproveita."""
    _cadastro_de_custo([("Drenagem", ["3"])])
    _anexar(2, b"PK\x03\x04 nao sou planilha")
    (banco / "vazia").mkdir()
    for _ in range(3):
        _executar(banco / "vazia")
    assert _contar("SELECT COUNT(*) FROM medicao_grupos WHERE situacao='recusada'") == 1
    assert "já lida antes: o arquivo não abre como planilha .xlsx" in capsys.readouterr().out


def test_anexo_que_nao_confere_com_a_versao_e_pulado(banco, capsys):
    """Sol S3 (rodada 2): o arquivo gravado trocado por outro nao se liga a versao."""
    _anexar(2, planilha(), sha="0" * 64)
    (banco / "vazia").mkdir()
    _executar(banco / "vazia")
    assert "pulado: o arquivo do anexo não confere com o registrado na versão" in capsys.readouterr().out
    assert _contar("SELECT COUNT(*) FROM medicao_grupos") == 0


def test_anexo_de_versao_sem_sha_registrado_e_pulado(banco, capsys):
    """#503: versao sem o sha256 da planilha nao aceita qualquer arquivo achado no caminho."""
    from app import arquivos
    c = db.get_conn()
    mid = c.execute("SELECT id FROM medicoes WHERE numero=2 AND tipo='execucao'").fetchone()[0]
    rel, _ = arquivos.gravar_bytes("planilhas", planilha(), "xlsx")
    c.execute("INSERT INTO medicao_planilhas (medicao_id, versao, valor_pedido_centavos, acumulado_anterior_centavos, "
              "arquivo_planilha, sha256_planilha, origem) VALUES (?, 1, ?, 0, ?, NULL, 'manual')", (mid, TOTAL, rel))
    c.commit()
    c.close()
    (banco / "vazia").mkdir()
    _executar(banco / "vazia")
    assert "anexo da versão 1: Medição 2 de execução -> pulado: a versão não tem o sha256 da planilha registrado" \
        in capsys.readouterr().out
    assert _contar("SELECT COUNT(*) FROM medicao_grupos") == 0


def test_item_a_mais_numa_leitura_gravada_e_recusado(banco):
    """Sol S5 (rodada 2): a leitura gravada fica selada; item novo nela e' recusado."""
    _executar(_pasta_com(banco))
    c = db.get_conn()
    try:
        lid, n = c.execute("SELECT id, itens FROM medicao_grupos").fetchone()
        assert n == 5
        with pytest.raises(sqlite3.IntegrityError, match="itens dela já foram gravados"):
            c.execute("INSERT INTO medicao_grupo_itens (leitura_id, ordem, grupo, valor_medido_centavos) "
                      "VALUES (?, 6, 'outros', 100)", (lid,))
    finally:
        c.close()


def test_insert_or_replace_numa_leitura_gravada_e_recusado(banco):
    """#502 (Sol, PR #500): o REPLACE numa ordem que ja existe nao troca o item da leitura selada."""
    _executar(_pasta_com(banco))
    c = db.get_conn()
    try:
        lid = c.execute("SELECT id FROM medicao_grupos").fetchone()[0]
        antes = [tuple(r) for r in c.execute("SELECT * FROM medicao_grupo_itens ORDER BY ordem")]
        id1 = antes[0][0]
        for sql, args in (
                ("INSERT OR REPLACE INTO medicao_grupo_itens (leitura_id, ordem, grupo, valor_medido_centavos) "
                 "VALUES (?, 1, 'trocado', 1)", (lid,)),
                ("REPLACE INTO medicao_grupo_itens (leitura_id, ordem, grupo, valor_medido_centavos) "
                 "VALUES (?, 2, 'trocado', 1)", (lid,)),
                # pelo id do item: o REPLACE apagaria o item e regravaria outro no lugar
                ("INSERT OR REPLACE INTO medicao_grupo_itens (id, leitura_id, ordem, grupo, valor_medido_centavos) "
                 "VALUES (?, ?, 1, 'trocado', 1)", (id1, lid)),
                ("INSERT INTO medicao_grupo_itens (leitura_id, ordem, grupo, valor_medido_centavos) "
                 "VALUES (?, 3, 'trocado', 1)", (lid,))):
            with pytest.raises(sqlite3.IntegrityError, match="itens dela já foram gravados"):
                c.execute(sql, args)
        assert [tuple(r) for r in c.execute("SELECT * FROM medicao_grupo_itens ORDER BY ordem")] == antes
    finally:
        c.close()


def test_insert_or_replace_na_leitura_gravada_e_recusado(banco):
    """#502 (revisor e Sol, rodada 1): o REPLACE pela leitura (o pai) nao reabre a leitura para item novo."""
    _executar(_pasta_com(banco))
    c = db.get_conn()
    try:
        r = c.execute("SELECT * FROM medicao_grupos").fetchone()
        pai = [tuple(x) for x in c.execute("SELECT * FROM medicao_grupos")]
        itens = [tuple(x) for x in c.execute("SELECT * FROM medicao_grupo_itens ORDER BY id")]
        for verbo in ("INSERT OR REPLACE", "REPLACE"):
            # pelo id da leitura, com mais itens e outro total
            with pytest.raises(sqlite3.IntegrityError, match="evento"):
                c.execute(f"{verbo} INTO medicao_grupos (id, medicao_id, sha256, origem, situacao, total_centavos, "
                          "pedido_centavos, itens) VALUES (?,?,?,'carga','lida',999999,?,?)",
                          (r["id"], r["medicao_id"], r["sha256"], r["pedido_centavos"], r["itens"] + 1))
            # pela mesma leitura (o indice unico das lidas), com id novo
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(f"{verbo} INTO medicao_grupos (medicao_id, sha256, origem, situacao, total_centavos, "
                          "pedido_centavos, itens) VALUES (?,?,'carga','lida',999999,?,?)",
                          (r["medicao_id"], r["sha256"], r["pedido_centavos"], r["itens"] + 1))
        with pytest.raises(sqlite3.IntegrityError, match="itens dela já foram gravados"):
            c.execute("INSERT INTO medicao_grupo_itens (leitura_id, ordem, grupo, valor_medido_centavos) "
                      "VALUES (?,?, 'outros', 999699)", (r["id"], r["itens"] + 1))
        assert [tuple(x) for x in c.execute("SELECT * FROM medicao_grupos")] == pai
        assert [tuple(x) for x in c.execute("SELECT * FROM medicao_grupo_itens ORDER BY id")] == itens
    finally:
        c.close()


def test_id_zero_ou_negativo_e_recusado_e_a_gravacao_normal_segue(banco):
    """#502 (Sol, rodadas 1 e 2): no BEFORE INSERT o id omitido vale -1, entao o selo por id so' confere id positivo;
    por isso nenhuma linha nova pode ter id <= 0, nem por REPLACE, e a gravacao normal segue."""
    c = db.get_conn()
    try:
        mid = c.execute("SELECT id FROM medicoes WHERE numero=2").fetchone()[0]
        for verbo in ("INSERT", "INSERT OR REPLACE", "REPLACE"):
            for id_ in (0, -1):
                with pytest.raises(sqlite3.IntegrityError, match="evento"):
                    c.execute(f"{verbo} INTO medicao_grupos (id, medicao_id, sha256, origem, situacao, "
                              "total_centavos, pedido_centavos, itens) VALUES (?, ?, 'x', 'carga', 'lida', 100, 100, 1)",
                              (id_, mid))
    finally:
        c.close()
    _executar(_pasta_com(banco))
    c = db.get_conn()
    try:
        lid = c.execute("SELECT id FROM medicao_grupos").fetchone()[0]
        for verbo in ("INSERT", "INSERT OR REPLACE", "REPLACE"):
            for id_ in (0, -1):
                with pytest.raises(sqlite3.IntegrityError, match="evento"):
                    c.execute(f"{verbo} INTO medicao_grupo_itens (id, leitura_id, ordem, grupo, "
                              "valor_medido_centavos) VALUES (?, ?, 1, 'g', 100)", (id_, lid))
        assert c.execute("SELECT MIN(id) FROM medicao_grupo_itens").fetchone()[0] >= 1
    finally:
        c.close()
    assert _contar("SELECT COUNT(*) FROM medicao_grupos WHERE situacao = 'lida'") == 1
    assert _contar("SELECT COUNT(*) FROM medicao_grupo_itens") == 5
