-- 075: resposta do orgao ao pleito de reajuste (issue #586). So' acrescenta (uma tabela, um indice e dois gatilhos).
--
-- `pleito_respostas` e' evento: a operacao registra a resposta formal do orgao ao pleito enviado mais recente do
-- ciclo, com a data, o documento que a traz e o texto. 'indeferido' fecha o ciclo para os avisos de pedido sem
-- resposta e de cronograma a reemitir (app/reajuste.py, `indeferimento_do_ciclo`); 'deferido_parcial' fica registrado
-- e o ciclo continua esperando o termo; 'sem_efeito' anula a resposta registrada por engano (o ciclo volta a esperar).
-- Nunca se altera nem se apaga: a correcao e' resposta nova no mesmo pleito, que aponta a corrigida em
-- `corrige_resposta_id`; vale a mais recente.
CREATE TABLE IF NOT EXISTS pleito_respostas (
    id INTEGER PRIMARY KEY,
    pleito_id INTEGER NOT NULL REFERENCES pleitos(id),
    resultado TEXT NOT NULL CHECK (resultado IN ('indeferido','deferido_parcial','sem_efeito')),
    data TEXT NOT NULL CHECK (data GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]-[0-3][0-9]'),
    documento TEXT NOT NULL CHECK (length(trim(documento)) >= 1),
    texto TEXT NOT NULL CHECK (length(trim(texto)) >= 10),
    corrige_resposta_id INTEGER REFERENCES pleito_respostas(id),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_pleito_respostas_pleito ON pleito_respostas (pleito_id, id);

CREATE TRIGGER IF NOT EXISTS pleito_respostas_sem_update BEFORE UPDATE ON pleito_respostas
BEGIN
    SELECT RAISE(ABORT, 'Resposta do órgão ao pleito é evento: não se altera (registre uma nova)');
END;
CREATE TRIGGER IF NOT EXISTS pleito_respostas_sem_delete BEFORE DELETE ON pleito_respostas
BEGIN
    SELECT RAISE(ABORT, 'Resposta do órgão ao pleito é evento: não se apaga');
END;
