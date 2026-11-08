-- 071: alertas de seguranca por e-mail ao dono e resumo diario (issue #424). So' acrescenta: uma tabela nova.
--
-- Cada e-mail e' uma linha, gravada ANTES de sair (app/alertas_seguranca.py), com `chave` unica: o mesmo e-mail nao
-- sai duas vezes. `envio_reservado_em` marca o envio em curso; falha antes do e-mail solta a marca (a proxima rodada
-- tenta de novo); envio incerto, sem registro ou interrompido deixa a marca, e nada se repete sozinho: a Saude acusa
-- ate' uma pessoa conferir os Enviados e registrar o resultado (`envio_conferido_em` quando saiu; a marca solta
-- quando nao saiu).
-- `mensagem` e `problema_resolvido_em`: o problema que continua aberto (protecao das tabelas, cadeia da auditoria,
-- codigo diferente do deploy) sai uma vez por episodio, e o episodio fecha quando o problema some.
-- `tipo = 'marco'`: uma linha so', o momento em que os alertas comecaram a valer; item mais antigo nao vira e-mail.
CREATE TABLE IF NOT EXISTS alertas_seguranca_envios (
    id INTEGER PRIMARY KEY,
    chave TEXT NOT NULL UNIQUE,
    tipo TEXT NOT NULL CHECK (tipo IN ('alerta', 'resumo', 'marco')),
    assunto TEXT NOT NULL,
    mensagem TEXT,
    problema_resolvido_em TEXT,
    envio_id INTEGER REFERENCES envios(id),
    envio_reservado_em TEXT,
    envio_reservado_por INTEGER REFERENCES usuarios(id),
    envio_conferido_em TEXT,
    envio_conferido_por INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TRIGGER IF NOT EXISTS alertas_seguranca_envios_sem_delete BEFORE DELETE ON alertas_seguranca_envios
BEGIN
    SELECT RAISE(ABORT, 'Envio de alerta de segurança não se apaga');
END;
