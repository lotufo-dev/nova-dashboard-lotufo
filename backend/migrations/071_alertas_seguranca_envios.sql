-- 071: alertas de seguranca por e-mail ao dono e resumo diario (issue #424). So' acrescenta: uma tabela nova.
--
-- Cada e-mail e' uma linha, gravada ANTES de sair (app/alertas_seguranca.py): `chave` e' o grupo de itens iguais na
-- mesma hora ("alerta <AAAA-MM-DD HH> <mensagem>") ou o dia do resumo ("resumo <AAAA-MM-DD>"), e o UNIQUE impede o
-- mesmo e-mail duas vezes. `envio_reservado_em` marca o envio em curso; falha antes do e-mail solta a marca (a
-- proxima rodada tenta de novo); envio incerto ou sem registro deixa a marca, e nada se repete sozinho.
CREATE TABLE IF NOT EXISTS alertas_seguranca_envios (
    id INTEGER PRIMARY KEY,
    chave TEXT NOT NULL UNIQUE,
    tipo TEXT NOT NULL CHECK (tipo IN ('alerta', 'resumo')),
    assunto TEXT NOT NULL,
    envio_id INTEGER REFERENCES envios(id),
    envio_reservado_em TEXT,
    envio_reservado_por INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TRIGGER IF NOT EXISTS alertas_seguranca_envios_sem_delete BEFORE DELETE ON alertas_seguranca_envios
BEGIN
    SELECT RAISE(ABORT, 'Envio de alerta de segurança não se apaga');
END;
