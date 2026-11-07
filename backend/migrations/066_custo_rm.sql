-- 066: custo por tarefa e baixa de estoque do RM (issue #488, piloto de custo por medicao). So' acrescenta (tabelas,
-- indices e colunas). As duas tabelas sao o retrato das consultas DASH25 e DASH26 (agregados por centro e mes, sem
-- chave natural estavel): cada sincronizacao troca o conteudo inteiro numa transacao. Nao sao registro financeiro
-- nosso -- o RM e' a fonte e continua com o dado; aqui e' copia de leitura.
CREATE TABLE IF NOT EXISTS rm_custo_tarefas (
    id INTEGER PRIMARY KEY,
    coligada INTEGER NOT NULL,
    centro_custo TEXT,
    projeto TEXT,
    tarefa TEXT,
    natureza TEXT,
    mes TEXT NOT NULL CHECK (mes GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    qtd INTEGER NOT NULL DEFAULT 0,
    valor_centavos INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rm_custo_tarefas_centro ON rm_custo_tarefas (coligada, centro_custo, mes);

CREATE TABLE IF NOT EXISTS rm_estoque_baixas (
    id INTEGER PRIMARY KEY,
    coligada INTEGER NOT NULL,
    centro_custo TEXT,
    tipo_movimento TEXT,
    mes TEXT NOT NULL CHECK (mes GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    qtd INTEGER NOT NULL DEFAULT 0,
    valor_centavos INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rm_estoque_baixas_centro ON rm_estoque_baixas (coligada, centro_custo, mes);

-- a contagem de cada retrato na rodada; NULL = a rodada nao trouxe (falhou ou a agendada ja' trouxe no dia)
ALTER TABLE rm_sincronizacoes ADD COLUMN custo_tarefas INTEGER;
ALTER TABLE rm_sincronizacoes ADD COLUMN estoque_baixas INTEGER;
-- falha da consulta de custo ou de estoque: nao derruba a rodada das notas
ALTER TABLE rm_sincronizacoes ADD COLUMN custo_erro TEXT;
