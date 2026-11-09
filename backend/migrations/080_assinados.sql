-- 080: envio dos documentos assinados ao orgao (issue #627, SINFRA). So' acrescenta: uma tabela nova e cinco
-- colunas em `medicao_assinaturas`. Nenhuma linha existente muda.
--
-- A assinatura (042, evento append-only) passa a guardar o PDF assinado (`arquivo`, `sha256`) e, quando nasceu do
-- envio ao orgao, como ele foi: `envio_origem` 'sistema' (com `envio_id`, o e-mail registrado) ou 'externo'
-- (registrado por fora), e a linha do envio (`assinados_envio_id`). A coluna `origem` da 042 tem CHECK so' com
-- 'manual' e mudar o CHECK exigiria reconstruir a tabela: o "como foi enviado" fica numa coluna nova, NULL nas
-- assinaturas registradas so' com a data.
--
-- Um envio dos assinados por linha (pelo sistema ou registrado por fora): os PDFs que foram (o da medicao, o do
-- reajuste do par e a justificativa de atraso), o motivo do reenvio e a reserva atomica do e-mail
-- (app/envio_reserva.py, 035). `anteriores` e' quantos envios concluidos a pessoa viu ao pedir este: a reserva so'
-- passa se ainda forem esses (o reenvio exige motivo, e outro envio concluido no meio recusa).
CREATE TABLE IF NOT EXISTS medicao_assinados_envios (
    id INTEGER PRIMARY KEY,
    medicao_id INTEGER NOT NULL REFERENCES medicoes(id),
    reajuste_id INTEGER REFERENCES medicoes(id),
    origem TEXT NOT NULL CHECK (origem IN ('sistema','externo')),
    assinado_em TEXT NOT NULL,
    arquivo TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    nome TEXT NOT NULL,
    arquivo_reajuste TEXT,
    sha256_reajuste TEXT,
    nome_reajuste TEXT,
    arquivo_justificativa TEXT,
    sha256_justificativa TEXT,
    nome_justificativa TEXT,
    eml TEXT,
    motivo TEXT,
    anteriores INTEGER NOT NULL DEFAULT 0,
    envio_id INTEGER REFERENCES envios(id),
    envio_reservado_em TEXT,
    envio_reservado_por INTEGER REFERENCES usuarios(id),
    usuario_id INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_medicao_assinados_envios_medicao ON medicao_assinados_envios (medicao_id, id);
CREATE TRIGGER IF NOT EXISTS medicao_assinados_envios_sem_delete BEFORE DELETE ON medicao_assinados_envios
BEGIN
    SELECT RAISE(ABORT, 'Envio dos documentos assinados não se apaga');
END;

ALTER TABLE medicao_assinaturas ADD COLUMN arquivo TEXT;
ALTER TABLE medicao_assinaturas ADD COLUMN sha256 TEXT;
ALTER TABLE medicao_assinaturas ADD COLUMN envio_id INTEGER REFERENCES envios(id);
ALTER TABLE medicao_assinaturas ADD COLUMN envio_origem TEXT CHECK (envio_origem IN ('sistema','externo'));
ALTER TABLE medicao_assinaturas ADD COLUMN assinados_envio_id INTEGER REFERENCES medicao_assinados_envios(id);
