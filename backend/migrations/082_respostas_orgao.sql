-- Issue #644: a resposta do orgao chega a' dashboard pela conversa do e-mail que a propria dashboard enviou.
-- `envios.conversa_id` e' o identificador da conversa (`conversationId` do Graph) gravado no envio; envio antigo fica
-- sem e nao e' lido. `medicao_respostas_orgao` guarda cada mensagem da conversa que nao e' de quem enviou: remetente,
-- data e hora, assunto, o trecho inicial do texto (ate' 500 caracteres) e os nomes dos anexos (JSON). O corpo inteiro
-- e os anexos nao sao gravados. `mensagem_id` unico: a mesma mensagem nunca entra duas vezes. So' acrescenta.
ALTER TABLE envios ADD COLUMN conversa_id TEXT;

CREATE TABLE IF NOT EXISTS medicao_respostas_orgao (
    id INTEGER PRIMARY KEY,
    medicao_id INTEGER NOT NULL REFERENCES medicoes(id),
    envio_id INTEGER NOT NULL REFERENCES envios(id),
    mensagem_id TEXT NOT NULL UNIQUE,
    remetente TEXT NOT NULL,
    remetente_nome TEXT,
    recebida_em TEXT NOT NULL,
    assunto TEXT NOT NULL DEFAULT '',
    trecho TEXT NOT NULL DEFAULT '',
    anexos TEXT NOT NULL DEFAULT '[]',
    lida_por INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_medicao_respostas_orgao_medicao ON medicao_respostas_orgao (medicao_id, recebida_em);
