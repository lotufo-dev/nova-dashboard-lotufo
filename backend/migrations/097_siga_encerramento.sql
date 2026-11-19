-- 097: criterio de encerramento do SIGA (issue #841). So' acrescenta: duas colunas, uma tabela, um indice e uma coluna.
--
-- 1. Vinculo processo <-> medicao feito pela tela. O vinculo continua sendo `siga_processos.medicao_id` (uma definicao
--    so', a da #663); aqui entra quem o fez e quando. NULL nas duas = vinculo do sistema (numero igual, link colado no
--    protocolo) ou processo sem medicao. Desfazer limpa as tres colunas; o ato fica na auditoria.
ALTER TABLE siga_processos ADD COLUMN medicao_vinculada_por INTEGER REFERENCES usuarios(id);
ALTER TABLE siga_processos ADD COLUMN medicao_vinculada_em TEXT;

-- 2. "Encerrar processo" a' mao, com motivo curto, e "Reabrir". Uma linha por encerramento; reabrir preenche a linha,
--    nunca a apaga. `reaberto_por` NULL com `reaberto_em` preenchido = voltou sozinho, pela movimentacao do SIGA de
--    `reaberto_pela_movimentacao` (data do SIGA, hora de Cuiaba), posterior ao encerramento. Carimbos em UTC.
CREATE TABLE IF NOT EXISTS siga_encerramentos (
    id INTEGER PRIMARY KEY,
    processo_id INTEGER NOT NULL REFERENCES siga_processos(id),
    motivo TEXT NOT NULL CHECK (length(trim(motivo)) BETWEEN 1 AND 200),
    encerrado_por INTEGER NOT NULL REFERENCES usuarios(id),
    encerrado_em TEXT NOT NULL,
    reaberto_em TEXT,
    reaberto_por INTEGER REFERENCES usuarios(id),
    reaberto_pela_movimentacao TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (reaberto_em IS NOT NULL OR (reaberto_por IS NULL AND reaberto_pela_movimentacao IS NULL)),
    CHECK (reaberto_por IS NULL OR reaberto_pela_movimentacao IS NULL)
);
-- no maximo um encerramento em aberto por processo
CREATE UNIQUE INDEX IF NOT EXISTS siga_encerramentos_aberto ON siga_encerramentos(processo_id) WHERE reaberto_em IS NULL;

-- 3. Leitura vazia: o SIGA as vezes devolve a lista de movimentacoes vazia para um processo que tem historico. A
--    leitura fica gravada (o robo leu), marcada, e nao vale como situacao do processo: nao encerra nem reabre. As
--    leituras existentes ficam com 0 (valem como sempre valeram).
ALTER TABLE siga_leituras ADD COLUMN sem_movimentacoes INTEGER NOT NULL DEFAULT 0 CHECK (sem_movimentacoes IN (0, 1));
