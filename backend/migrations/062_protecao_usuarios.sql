-- 062: as tabelas de usuarios e de sessoes so' mudam pela aplicacao (issue #422). So' acrescenta.
-- Criar ou apagar uma conta, mudar qualquer coluna dela fora `tentativas_falhas` e `bloqueado_ate`, e criar, mudar ou
-- apagar uma sessao chamam a funcao `dash_conexao_app()`, que so' a aplicacao registra (`db.get_conn`). Numa conexao
-- sem ela (sqlite3 de linha de comando, DB Browser, script avulso) o SQLite recusa o comando com "no such function";
-- leitura, integrity_check e as duas colunas do contador de senha errada seguem normais. Funcao, e nao marca em tabela,
-- porque gatilho em `main` nao enxerga tabela temporaria.
-- O `id` entra no UPDATE porque trocar os ids de duas contas faria as sessoes de uma resolverem para o perfil da outra;
-- as sessoes entram porque inserir uma linha com um token conhecido e' entrar como qualquer pessoa sem senha (gate
-- Sol, rodada 1). Coluna nova em `usuarios` precisa entrar na lista do `usuarios_protecao_update`.
-- O texto destes gatilhos em sqlite_master e' conferido de hora em hora pelo sha256 (`seguranca.GATILHOS`): mudar um
-- aqui exige atualizar o sha256 de la'.
CREATE TRIGGER IF NOT EXISTS usuarios_protecao_insert BEFORE INSERT ON usuarios
BEGIN
    SELECT dash_conexao_app();
END;

CREATE TRIGGER IF NOT EXISTS usuarios_protecao_delete BEFORE DELETE ON usuarios
BEGIN
    SELECT dash_conexao_app();
END;

CREATE TRIGGER IF NOT EXISTS usuarios_protecao_update
BEFORE UPDATE OF id, nome, email, senha_hash, perfil, ativo, criado_em ON usuarios
BEGIN
    SELECT dash_conexao_app();
END;

CREATE TRIGGER IF NOT EXISTS sessoes_protecao_insert BEFORE INSERT ON sessoes
BEGIN
    SELECT dash_conexao_app();
END;

CREATE TRIGGER IF NOT EXISTS sessoes_protecao_delete BEFORE DELETE ON sessoes
BEGIN
    SELECT dash_conexao_app();
END;

CREATE TRIGGER IF NOT EXISTS sessoes_protecao_update BEFORE UPDATE ON sessoes
BEGIN
    SELECT dash_conexao_app();
END;
