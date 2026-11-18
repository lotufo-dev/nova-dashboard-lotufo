import contextlib
import re
import shutil
import sqlite3

import pytest
from app import db

# Estes testes exercitam o proprio runner de migracao: partem de um banco vazio de verdade,
# sem o banco-modelo do conftest (issue #88).
pytestmark = pytest.mark.migracao_real

def test_conn_endurecida(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    conn.close()

def test_db_path_exige_variavel_fora_de_dev(tmp_path, monkeypatch):
    import pytest
    monkeypatch.delenv("DASH_DB_PATH", raising=False)
    monkeypatch.delenv("DASH_DEV", raising=False)
    with pytest.raises(RuntimeError, match="DASH_DB_PATH"):
        db.db_path()
    monkeypatch.setenv("DASH_DEV", "1")
    monkeypatch.chdir(tmp_path)
    assert db.db_path().name == "dashboard.db"

def test_migrate_aplica_uma_vez(tmp_path, monkeypatch):
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()
    db.migrate(conn)
    db.migrate(conn)  # idempotente
    tabelas = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"usuarios", "sessoes", "audit_log", "schema_migrations"} <= tabelas
    conn.close()

def test_migrate_recupera_de_estado_parcial(tmp_path, monkeypatch):
    """executescript nao e transacional: uma migracao pode ter criado as tabelas
    sem chegar a registrar o nome em schema_migrations. A reaplicacao precisa
    passar sem erro (migracoes idempotentes)."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()

    # simula estado parcial: script aplicado, registro nao gravado
    sql_file = db.MIGRATIONS_DIR / "001_usuarios_sessoes_audit.sql"
    conn.executescript(sql_file.read_text(encoding="utf-8"))
    conn.commit()

    db.migrate(conn)  # nao pode levantar

    aplicadas = {r[0] for r in conn.execute("SELECT nome FROM schema_migrations")}
    assert sql_file.name in aplicadas
    tabelas = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"usuarios", "sessoes", "audit_log", "schema_migrations"} <= tabelas
    conn.close()

def test_migrate_reaplica_add_column_sem_erro(tmp_path, monkeypatch):
    """ADD COLUMN e' a unica DDL deste projeto sem forma idempotente no SQLite.

    Estado parcial de uma migracao que ALTERA tabela (008): a coluna ja existe e o
    nome nao chegou a `schema_migrations`. Sem a guarda do runner, a reaplicacao
    morre com "duplicate column name: estado_em" e o banco fica travado no lugar.
    """
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()
    db.migrate(conn)
    assert "estado_em" in {r[1] for r in conn.execute("PRAGMA table_info(certidoes)")}

    conn.execute("DELETE FROM schema_migrations WHERE nome=?",
                 ("008_certidoes_estado_em.sql",))
    conn.commit()
    db.migrate(conn)          # nao pode levantar

    colunas = [r[1] for r in conn.execute("PRAGMA table_info(certidoes)")]
    assert colunas.count("estado_em") == 1
    conn.close()

def test_alter_add_column_novo_nao_e_removido_do_script(tmp_path, monkeypatch):
    """A guarda so pula o que JA existe: uma coluna nova continua sendo criada."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()
    conn.execute("CREATE TABLE t (a INTEGER)")
    sql = "ALTER TABLE t ADD COLUMN a TEXT;\nALTER TABLE t ADD COLUMN b TEXT;\n"
    assert db._sem_alters_ja_aplicados(conn, sql).strip() == "ALTER TABLE t ADD COLUMN b TEXT;"
    conn.close()

def test_comentario_citando_alter_nao_engole_o_ddl_seguinte(tmp_path, monkeypatch):
    """Comentario `--` que MENCIONA um ALTER nao pode virar ALTER de verdade.

    A guarda casava dentro de comentario, e o `[^;]*;` dela atravessa linhas: um
    comentario historico ("ver ALTER TABLE t ADD COLUMN a") seguido de um CREATE
    virava UM casamento so, que ia do meio do comentario ate' o `;` do CREATE. Com a
    coluna citada ja existente, a guarda apagava o trecho inteiro -- e o CREATE
    sumia EM SILENCIO: migracao registrada como aplicada, tabela que nunca nasceu.
    """
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()
    conn.execute("CREATE TABLE t (a INTEGER)")
    sql = ("-- histórico: ver ALTER TABLE t ADD COLUMN a TEXT (já aplicado na 001)\n"
           "CREATE TABLE IF NOT EXISTS novo (id INTEGER PRIMARY KEY);\n")

    saida = db._sem_alters_ja_aplicados(conn, sql)

    assert "CREATE TABLE IF NOT EXISTS novo" in saida
    conn.executescript(saida)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='novo'").fetchone()
    conn.close()

def test_comentario_no_fim_da_linha_do_alter_nao_confunde_a_guarda(tmp_path, monkeypatch):
    """ALTER real com comentario na mesma linha continua sendo pulado quando a coluna
    ja existe -- e o DDL seguinte continua intacto."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()
    conn.execute("CREATE TABLE t (a INTEGER)")
    sql = ("ALTER TABLE t ADD COLUMN a TEXT;  -- guardado pelo runner; ver db.migrate\n"
           "CREATE TABLE IF NOT EXISTS novo (id INTEGER PRIMARY KEY);\n")

    saida = db._sem_alters_ja_aplicados(conn, sql)

    assert "ADD COLUMN a TEXT" not in saida
    conn.executescript(saida)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='novo'").fetchone()
    conn.close()

def test_migracao_009_e_idempotente_e_ancora_o_contrato_na_lotufo(tmp_path, monkeypatch):
    """`contratos.entidade_id` nasce apontando para a Lotufo (id 1).

    Sem DEFAULT na coluna, de proposito: o SQLite PROIBE `ADD COLUMN ... REFERENCES ...
    DEFAULT <valor>` (com foreign_keys=ON, um default nao-NULL numa coluna com FK nao
    e' aceito no ALTER). O ancoramento e' feito pelo UPDATE que acompanha o ALTER, e
    reaplicar a migracao (o cenario de `executescript` interrompido) tem que continuar
    passando: o ALTER e' pulado pela guarda do runner e o UPDATE e' inofensivo.
    """
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()
    db.migrate(conn)
    conn.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, "
                 "valor_original_centavos) VALUES ('S','IC 1','X',100)")
    conn.commit()
    assert conn.execute("SELECT entidade_id FROM contratos").fetchone()[0] is None

    conn.execute("DELETE FROM schema_migrations WHERE nome=?", ("009_contrato_entidade.sql",))
    conn.commit()
    db.migrate(conn)          # nao pode levantar
    db.migrate(conn)          # e' idempotente rodando de novo

    colunas = [r[1] for r in conn.execute("PRAGMA table_info(contratos)")]
    assert colunas.count("entidade_id") == 1
    # o UPDATE da reaplicacao ancorou o contrato legado na Lotufo
    assert conn.execute("SELECT entidade_id FROM contratos").fetchone()[0] == 1
    conn.close()

def test_migracao_010_remove_ia_chamadas_e_e_idempotente(tmp_path, monkeypatch):
    """A tabela de custo de IA (007) sai com a IA (spec §15). O DROP e' IF EXISTS
    porque `executescript` nao e' transacional: uma migracao interrompida e' reaplicada
    inteira na proxima subida, e a segunda passada nao pode levantar."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "m.db"))
    conn = db.get_conn()
    db.migrate(conn)
    tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ia_chamadas" not in tabelas

    # Reaplicacao de verdade: apagar o registro e migrar de novo e' o cenario do
    # `executescript` interrompido. Um `db.migrate` extra sem isso apenas PULA o
    # arquivo (o nome ja esta em schema_migrations) e nao provaria nada sobre o DROP.
    conn.execute("DELETE FROM schema_migrations WHERE nome=?", ("010_remove_ia_chamadas.sql",))
    conn.commit()
    db.migrate(conn)          # DROP numa tabela que ja nao existe: nao pode levantar
    db.migrate(conn)          # e' idempotente rodando de novo
    assert "ia_chamadas" not in {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()


# --- Reconstrucao de tabela nao perde linha (docs/adr/0010, issue #705) ----------------------------------------------
#
# A receita do SQLite para mudar CHECK ou tipo e' criar a tabela nova, copiar tudo, apagar a antiga e renomear. O teste
# acha sozinho toda migracao com DROP TABLE, monta o banco como ele estava logo antes dela, poe linhas nas tabelas, roda
# a migracao pelo runner de verdade e compara a contagem. Migracao nova que reconstroi tabela entra sem ninguem editar
# lista nenhuma; se a tabela ainda nao tem como ser semeada, o caso falha dizendo o que falta.
#
# Quem decide quais tabelas conferir e' o banco, nao o nome: das tabelas que o script apaga ou renomeia, valem as que
# ja' existiam antes dele. Assim a tabela de passagem da receita (`_nova`) fica de fora sem regra de sufixo, e a
# receita invertida (renomear a antiga, criar a nova, copiar, apagar a antiga) cai na tabela de verdade.

_MIGRACOES = sorted(db.MIGRATIONS_DIR.glob("*.sql"))
_NOME = r"(?:[\"'`\[]?(\w+)[\"'`\]]?\s*\.\s*)?[\"'`\[]?(\w+)"            # [esquema.]tabela, com ou sem aspas
_DROP_TABLE = re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + _NOME, re.IGNORECASE)
_RENAME = re.compile(r"\bALTER\s+TABLE\s+" + _NOME + r"[\"'`\]]?\s+RENAME\s+TO\s+[\"'`\[]?(\w+)", re.IGNORECASE)
_CREATE_TABLE = re.compile(r"\bCREATE\s+(TEMP\s+|TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + _NOME, re.IGNORECASE)
_COMENTARIO_DE_BLOCO = re.compile(r"/\*.*?\*/", re.DOTALL)

# Tabela apagada de vez, sem recriar: so' com decisao registrada aqui, com o motivo. Qualquer outra faz o teste falhar.
_REMOCOES_DECIDIDAS = {
    # custo de IA: o produto deixou de chamar servico pago por uso; era log operacional, nao dado de negocio
    ("010_remove_ia_chamadas.sql", "ia_chamadas"),
}
_LINHAS = 3


def _arquivo(migracao: str):
    return next(a for a in _MIGRACOES if a.name == migracao)


def _sql(migracao: str) -> str:
    """O script sem os comentarios (de linha e de bloco): a busca nao pode casar com a prosa do cabecalho."""
    return _COMENTARIO_DE_BLOCO.sub(" ", db._mascarar_comentarios(_arquivo(migracao).read_text(encoding="utf-8")))


def _temporarias(sql: str) -> set[str]:
    return {nome.lower() for temp, esquema, nome in _CREATE_TABLE.findall(sql) if temp or esquema.lower() == "temp"}


def _apagadas(migracao: str) -> list[str]:
    """Nomes em DROP TABLE, fora os de tabela temporaria. A `_nova` da receita entra aqui; sai pelo banco, no teste."""
    sql = _sql(migracao)
    temporarias = _temporarias(sql)
    nomes = [nome.lower() for esquema, nome in _DROP_TABLE.findall(sql)
             if esquema.lower() != "temp" and nome.lower() not in temporarias]
    return list(dict.fromkeys(nomes))


def _mexidas(migracao: str) -> list[str]:
    """Nomes que o script apaga ou renomeia (a origem e o destino de cada RENAME), fora os de tabela temporaria."""
    renomeadas = [nome.lower() for _, de, para in _RENAME.findall(_sql(migracao)) for nome in (de, para)]
    return list(dict.fromkeys(_apagadas(migracao) + renomeadas))


_COM_DROP_TABLE = [a.name for a in _MIGRACOES if _apagadas(a.name)]


def _contrato(conn) -> int:
    n = conn.execute("SELECT COUNT(*) FROM contratos").fetchone()[0] + 1
    return conn.execute("INSERT INTO contratos (orgao, numero_instrumento, objeto, valor_original_centavos) "
                        "VALUES ('S',?,'X',100)", (f"IC {n}",)).lastrowid


def _usuario(conn) -> int:
    n = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] + 1
    return conn.execute("INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES ('Teste',?,'x','engenharia')",
                        (f"teste{n}@exemplo.com.br",)).lastrowid


def _medicoes(conn) -> list[int]:
    contrato = _contrato(conn)
    return [conn.execute("INSERT INTO medicoes (contrato_id, numero, tipo, competencia) "
                         "VALUES (?,?,'execucao','2026-01')", (contrato, n)).lastrowid
            for n in range(1, _LINHAS + 1)]


def _medicao_documentos(conn) -> None:
    for medicao in _medicoes(conn):
        conn.execute("INSERT INTO medicao_documentos (medicao_id, fonte, tipo_doc, nome, item_id) "
                     "VALUES (?,'engenharia_sp','nf','nota.pdf','item-1')", (medicao,))


def _notas_fiscais(conn) -> None:
    for n in range(1, _LINHAS + 1):
        conn.execute("INSERT INTO notas_fiscais (coligada, idmov, numero, valor_centavos) VALUES (1,?,?,100)",
                     (n, f"{n:09d}"))


def _protocolo_pecas(conn) -> None:
    protocolo = conn.execute("INSERT INTO protocolos (contrato_id, etapa, natureza, usuario_id) "
                             "VALUES (?,'unico','execucao',?)", (_contrato(conn), _usuario(conn))).lastrowid
    for n in range(1, _LINHAS + 1):
        conn.execute("INSERT INTO protocolo_pecas (protocolo_id, tipo, nome, arquivo, sha256, tamanho, ext) "
                     "VALUES (?,'outro',?,'pecas/x.pdf','x',1,'pdf')", (protocolo, f"peca-{n}.pdf"))


def _pleitos(conn) -> list[int]:
    contrato = _contrato(conn)
    return [conn.execute("INSERT INTO pleitos (contrato_id, tipo) VALUES (?,'prazo')", (contrato,)).lastrowid
            for _ in range(_LINHAS)]


def _pleito_anexos(conn) -> None:
    for pleito in _pleitos(conn):
        conn.execute("INSERT INTO pleito_anexos (pleito_id, tipo, nome, arquivo, sha256, tamanho, ext) "
                     "VALUES (?,'outro','anexo.pdf','pleitos/x.pdf','x',1,'pdf')", (pleito,))


def _envios(conn) -> None:
    usuario = _usuario(conn)
    for n in range(1, _LINHAS + 1):
        conn.execute("INSERT INTO envios (tipo, usuario_id, remetente, para, copia, assunto) "
                     "VALUES ('espelho',?,'faturamento@exemplo.com.br','orgao@exemplo.com.br','',?)",
                     (usuario, f"Envio {n}"))


def _espelhos(conn) -> None:
    contrato, usuario = _contrato(conn), _usuario(conn)
    for n in range(1, _LINHAS + 1):
        conn.execute("INSERT INTO espelhos (contrato_id, numero, competencia, versao, situacao, entradas, saidas, "
                     "regra_sha256, criado_por) VALUES (?,?,'2026-01',1,'vigente','{}','[]','x',?)",
                     (contrato, n, usuario))


def _contrato_fiscais(conn) -> None:
    contrato = _contrato(conn)
    for n in range(1, _LINHAS + 1):
        conn.execute("INSERT INTO contrato_fiscais (contrato_id, nome, email, desde) VALUES (?,?,?,'2026-01-01')",
                     (contrato, f"Fiscal {n}", f"fiscal{n}@exemplo.gov.br"))


# Como por linhas em cada tabela que alguma migracao reconstroi, so' com as colunas obrigatorias: a mesma receita serve
# em qualquer ponto da historia do esquema. Cada caso semeia TODAS as daqui que ja' existem no banco, nao so' a que a
# migracao mexe: a tabela reconstruida fica com linhas filhas apontando para ela (medicao_documentos -> medicoes,
# pleito_anexos -> pleitos), e a reconstrucao que esquecer de desligar as chaves estrangeiras falha aqui.
_SEMEAR = {
    "medicoes": _medicoes,
    "medicao_documentos": _medicao_documentos,
    "notas_fiscais": _notas_fiscais,
    "contrato_fiscais": _contrato_fiscais,
    "protocolo_pecas": _protocolo_pecas,
    "pleitos": _pleitos,
    "pleito_anexos": _pleito_anexos,
    "envios": _envios,
    "espelhos": _espelhos,
}


def _contagens(conn) -> dict[str, int]:
    """Linhas de cada tabela do banco, fora as internas do SQLite e o registro das migracoes."""
    tabelas = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                          "AND name NOT LIKE 'sqlite_%' AND name <> 'schema_migrations'")]
    return {tabela.lower(): conn.execute(f'SELECT COUNT(*) FROM "{tabela}"').fetchone()[0] for tabela in tabelas}


def _banco_antes_de(migracao: str, tmp_path, monkeypatch):
    """Banco como estava logo antes de `migracao`: so' as anteriores, numa copia da pasta, pelo runner de verdade (na
    ordem dos nomes, como numa instalacao nova). Devolve a conexao e a pasta, que vira a `db.MIGRATIONS_DIR` do teste."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    pasta = tmp_path / "migrations"
    pasta.mkdir()
    monkeypatch.setattr(db, "MIGRATIONS_DIR", pasta)
    for arquivo in _MIGRACOES:
        if arquivo.name < migracao:
            shutil.copy(arquivo, pasta / arquivo.name)
    conn = db.get_conn()
    db.migrate(conn)
    return conn, pasta


def _aplicar(conn, pasta, migracao: str) -> None:
    shutil.copy(_arquivo(migracao), pasta / migracao)
    db.migrate(conn)
    assert conn.execute("SELECT 1 FROM schema_migrations WHERE nome=?", (migracao,)).fetchone(), (
        f"{migracao} nao foi registrada: a migracao nao rodou")


def _conferir_que_nada_se_perdeu(conn, migracao: str, antes: dict[str, int], reconstruidas: list[str]) -> None:
    depois = _contagens(conn)
    for tabela, linhas in antes.items():
        if (migracao, tabela) in _REMOCOES_DECIDIDAS:
            continue
        assert tabela in depois, (
            f"{migracao} apaga `{tabela}` e nao recria: migracao nao perde dado (docs/adr/0010). Se a tabela sai de "
            f"vez por decisao, registre em _REMOCOES_DECIDIDAS com o motivo")
        if tabela in reconstruidas:
            assert depois[tabela] == linhas, f"{migracao} mudou a contagem de `{tabela}`: {linhas} -> {depois[tabela]}"
        else:
            assert depois[tabela] >= linhas, f"{migracao} perdeu linha de `{tabela}`: {linhas} -> {depois[tabela]}"


def test_descoberta_acha_as_migracoes_que_apagam_tabela():
    """Guarda da propria descoberta: se a regex parar de casar, os casos abaixo sumiriam em silencio."""
    assert {"010_remove_ia_chamadas.sql", "020_espelho.sql", "022_leitura_danfse.sql", "078_reajuste_negativo.sql"} \
        <= set(_COM_DROP_TABLE)
    assert _apagadas("020_espelho.sql") == ["medicoes_nova", "medicoes", "medicao_documentos_nova",
                                            "medicao_documentos"]
    assert set(_mexidas("020_espelho.sql")) == set(_apagadas("020_espelho.sql"))
    for migracao, tabela in _REMOCOES_DECIDIDAS:       # remocao registrada que nao existe mais e' lixo na lista
        assert migracao in _COM_DROP_TABLE and tabela in _apagadas(migracao)


@pytest.mark.parametrize("migracao", _COM_DROP_TABLE)
def test_reconstrucao_de_tabela_preserva_a_contagem_de_linhas(migracao, tmp_path, monkeypatch):
    conn, pasta = _banco_antes_de(migracao, tmp_path, monkeypatch)
    with contextlib.closing(conn):
        existiam = _contagens(conn)
        mexidas = [tabela for tabela in _mexidas(migracao) if tabela in existiam]
        assert mexidas, (
            f"{migracao} tem DROP TABLE, mas nenhuma tabela que ela apaga ou renomeia existia antes dela: o teste nao "
            f"entendeu o script (nomes lidos: {_mexidas(migracao)})")
        reconstruidas = [tabela for tabela in mexidas if (migracao, tabela) not in _REMOCOES_DECIDIDAS]
        sem_receita = [tabela for tabela in reconstruidas if tabela not in _SEMEAR]
        assert not sem_receita, (
            f"{migracao} apaga ou renomeia {sem_receita} e o teste nao sabe por linhas nela: acrescente em _SEMEAR "
            f"como semear a tabela (ou, se ela sai de vez por decisao, registre em _REMOCOES_DECIDIDAS com o motivo)")

        for tabela, semear in _SEMEAR.items():
            if tabela in existiam:
                semear(conn)
        conn.commit()
        antes = _contagens(conn)
        assert all(antes[tabela] >= _LINHAS for tabela in reconstruidas)

        _aplicar(conn, pasta, migracao)
        _conferir_que_nada_se_perdeu(conn, migracao, antes, reconstruidas)

        # A migracao roda sozinha ao subir e pode ser reaplicada inteira (executescript interrompido antes do
        # registro): a segunda passada tambem nao pode perder linha.
        conn.execute("DELETE FROM schema_migrations WHERE nome=?", (migracao,))
        conn.commit()
        _aplicar(conn, pasta, migracao)
        _conferir_que_nada_se_perdeu(conn, migracao, antes, reconstruidas)


# --- Medicao, nota fiscal, envio e espelho nao se apagam (issue #706) ------------------------------------------------

_MIGRACAO_SEM_DELETE = "087_medicoes_notas_envios_espelhos_sem_delete.sql"
_SEM_DELETE = {"medicoes": "Medição não se apaga", "notas_fiscais": "Nota fiscal não se apaga",
               "envios": "Envio não se apaga", "espelhos": "Espelho não se apaga"}


def _esquema(conn) -> dict:
    return {(r[0], r[1]): (r[2], r[3]) for r in conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master")}


def _dados(conn) -> dict:
    """Todas as linhas de todas as tabelas, fora o registro das migracoes."""
    return {tabela: sorted(repr(tuple(r)) for r in conn.execute(f'SELECT * FROM "{tabela}"'))
            for tabela in _contagens(conn)}


def _gatilho_sem_delete(tabela: str) -> str:
    """O CREATE TRIGGER de `tabela`, como esta' escrito no arquivo da migracao."""
    sql = _arquivo(_MIGRACAO_SEM_DELETE).read_text(encoding="utf-8")
    return re.search(rf"CREATE TRIGGER IF NOT EXISTS {tabela}_sem_delete\b.*?\bEND;", sql, re.DOTALL).group(0)


@pytest.mark.parametrize("tabela", sorted(_SEM_DELETE))
def test_medicao_nota_envio_e_espelho_nao_se_apagam(tabela, tmp_path, monkeypatch):
    """No esquema final, com todas as migracoes. O gatilho sai junto quando a tabela e' apagada: se uma migracao
    futura reconstruir uma destas tabelas e nao recriar o gatilho dela, e' aqui que aparece."""
    monkeypatch.setenv("DASH_DB_PATH", str(tmp_path / "t.db"))
    conn = db.get_conn()
    db.migrate(conn)
    _SEMEAR[tabela](conn)
    conn.commit()
    antes = _contagens(conn)[tabela]
    assert antes >= _LINHAS

    with pytest.raises(sqlite3.IntegrityError, match=_SEM_DELETE[tabela]):
        conn.execute(f"DELETE FROM {tabela}")
    with pytest.raises(sqlite3.IntegrityError, match=_SEM_DELETE[tabela]):
        conn.execute(f"DELETE FROM {tabela} WHERE id = (SELECT MIN(id) FROM {tabela})")
    conn.rollback()

    assert _contagens(conn)[tabela] == antes
    conn.close()


def test_gatilhos_contra_exclusao_so_acrescentam_e_podem_ser_reaplicados(tmp_path, monkeypatch):
    """Sobre um banco com dados, feito pelas migracoes anteriores: a migracao cria os quatro gatilhos e mais nada (o
    resto do esquema e todas as linhas ficam como estavam), e rodar de novo nao falha nem muda nada."""
    conn, pasta = _banco_antes_de(_MIGRACAO_SEM_DELETE, tmp_path, monkeypatch)
    for tabela in _SEM_DELETE:
        _SEMEAR[tabela](conn)
    conn.commit()
    esquema_antes, dados_antes = _esquema(conn), _dados(conn)
    assert all(dados_antes[tabela] for tabela in _SEM_DELETE)

    _aplicar(conn, pasta, _MIGRACAO_SEM_DELETE)

    esquema = _esquema(conn)
    assert {chave: esquema[chave] for chave in esquema_antes} == esquema_antes
    assert set(esquema) - set(esquema_antes) == {("trigger", f"{tabela}_sem_delete") for tabela in _SEM_DELETE}
    for tabela in _SEM_DELETE:
        dono, sql = esquema[("trigger", f"{tabela}_sem_delete")]
        assert dono == tabela and f"BEFORE DELETE ON {tabela}" in sql
    assert _dados(conn) == dados_antes

    # Reaplicacao de verdade (executescript interrompido antes do registro), e depois a subida normal, que pula.
    conn.execute("DELETE FROM schema_migrations WHERE nome=?", (_MIGRACAO_SEM_DELETE,))
    conn.commit()
    db.migrate(conn)
    db.migrate(conn)
    assert _esquema(conn) == esquema
    assert _dados(conn) == dados_antes
    conn.close()


_RECONSTRUCOES_DAS_PROTEGIDAS = [(migracao, tabela) for migracao in _COM_DROP_TABLE if migracao < _MIGRACAO_SEM_DELETE
                                 for tabela in _mexidas(migracao) if tabela in _SEM_DELETE]


def test_ha_reconstrucao_de_medicoes_e_de_notas_fiscais_para_conferir():
    assert {tabela for _, tabela in _RECONSTRUCOES_DAS_PROTEGIDAS} >= {"medicoes", "notas_fiscais"}


@pytest.mark.parametrize("migracao,tabela", _RECONSTRUCOES_DAS_PROTEGIDAS,
                         ids=[f"{m}:{t}" for m, t in _RECONSTRUCOES_DAS_PROTEGIDAS])
def test_reconstrucao_roda_com_o_gatilho_contra_exclusao_presente(migracao, tabela, tmp_path, monkeypatch):
    """A reconstrucao de tabela (docs/adr/0010) continua possivel numa tabela que recusa DELETE: o DROP TABLE da
    receita nao dispara o gatilho. Cada migracao que ja' reconstruiu `medicoes` ou `notas_fiscais` roda aqui com o
    gatilho posto na tabela antes dela. As que vierem depois da 087 ja' encontram o gatilho no teste da contagem."""
    conn, pasta = _banco_antes_de(migracao, tmp_path, monkeypatch)
    _SEMEAR[tabela](conn)
    conn.commit()
    antes = _contagens(conn)[tabela]
    assert antes >= _LINHAS
    conn.executescript(_gatilho_sem_delete(tabela))
    with pytest.raises(sqlite3.IntegrityError, match=_SEM_DELETE[tabela]):      # o gatilho esta' mesmo la'
        conn.execute(f"DELETE FROM {tabela}")
    conn.rollback()

    _aplicar(conn, pasta, migracao)

    assert _contagens(conn)[tabela] == antes
    conn.close()
