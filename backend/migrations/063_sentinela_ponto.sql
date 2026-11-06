-- 063: o ponto de leitura da sentinela (ultimo EventRecordID lido do log de Seguranca) sai da auditoria para uma tabela
-- de uma linha (issue #456). So' acrescenta. Desde a #423 cada rodada que avancava o ponto gravava uma linha
-- `seguranca.sentinela.ponto` no audit_log (perto de 288 por dia); agora a rodada atualiza esta linha na mesma transacao
-- dos achados. As linhas antigas ficam na auditoria (append-only); a ultima delas e' o ponto de partida desta tabela,
-- para a sentinela nao pular nem reler eventos na troca.
CREATE TABLE IF NOT EXISTS sentinela_ponto (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    ultimo_registro INTEGER NOT NULL,
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO sentinela_ponto (id, ultimo_registro)
SELECT 1, CAST(json_extract(depois, '$.ultimo_registro') AS INTEGER) FROM audit_log
WHERE acao = 'seguranca.sentinela.ponto' AND json_valid(depois)
  AND json_type(depois, '$.ultimo_registro') = 'integer'
ORDER BY id DESC LIMIT 1;
