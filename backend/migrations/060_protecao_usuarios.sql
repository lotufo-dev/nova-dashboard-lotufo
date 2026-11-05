-- 060: a tabela de usuarios so' muda pela aplicacao (issue #422). So' acrescenta.
-- Criar, apagar ou mudar e-mail, senha, perfil ou situacao de uma conta chama a funcao `dash_conexao_app()`, que so'
-- a aplicacao registra (`db.get_conn`). Numa conexao sem ela (sqlite3 de linha de comando, DB Browser, script avulso)
-- o SQLite recusa o comando com "no such function"; leitura, integrity_check e as colunas de fora (tentativas_falhas,
-- bloqueado_ate) seguem normais. Funcao, e nao marca em tabela, porque gatilho em `main` nao enxerga tabela temporaria.
-- O texto destes gatilhos em sqlite_master e' conferido de hora em hora pelo sha256 (`seguranca.GATILHOS_USUARIOS`):
-- mudar um aqui exige atualizar o sha256 de la'.
CREATE TRIGGER IF NOT EXISTS usuarios_protecao_insert BEFORE INSERT ON usuarios
BEGIN
    SELECT dash_conexao_app();
END;

CREATE TRIGGER IF NOT EXISTS usuarios_protecao_delete BEFORE DELETE ON usuarios
BEGIN
    SELECT dash_conexao_app();
END;

CREATE TRIGGER IF NOT EXISTS usuarios_protecao_update BEFORE UPDATE OF email, senha_hash, perfil, ativo ON usuarios
BEGIN
    SELECT dash_conexao_app();
END;
