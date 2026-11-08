-- 077: a capa do SMO lida no registro do boletim (issue #286, decisao do Leo de 08/11/2026). So' acrescenta (uma
-- tabela, um indice e dois gatilhos).
--
-- No "Registrar boletim" o servidor le a capa do PDF anexado (so' o texto, sem OCR) e grava aqui os campos que a
-- conferencia contra o cadastro usa, ligados ao evento de atesto (`atesto_id`). A conferencia (fins de execucao e de
-- vigencia, valor do contrato, valor aditivo e acumulado) sai destes campos, nunca de nova leitura do PDF. Os valores
-- sao os impressos na capa: o contrato cheio (a cota se deriva na conferencia) e o acumulado cheio, em centavos.
-- Campo que a capa nao trouxe fica NULL e nao e' conferido. Evento: nao se altera nem se apaga.
CREATE TABLE IF NOT EXISTS medicao_boletim_capas (
    id INTEGER PRIMARY KEY,
    atesto_id INTEGER NOT NULL UNIQUE REFERENCES medicao_atestos(id),
    medicao_id INTEGER NOT NULL REFERENCES medicoes(id),
    numero INTEGER CHECK (numero IS NULL OR (typeof(numero) = 'integer' AND numero >= 1)),
    data_realizacao TEXT,
    vigencia_fim TEXT,
    execucao_fim TEXT,
    valor_contrato_centavos INTEGER CHECK (valor_contrato_centavos IS NULL OR typeof(valor_contrato_centavos) = 'integer'),
    valor_aditivo_centavos INTEGER CHECK (valor_aditivo_centavos IS NULL OR typeof(valor_aditivo_centavos) = 'integer'),
    acumulado_pi_centavos INTEGER CHECK (acumulado_pi_centavos IS NULL OR typeof(acumulado_pi_centavos) = 'integer'),
    acumulado_reajuste_centavos INTEGER
        CHECK (acumulado_reajuste_centavos IS NULL OR typeof(acumulado_reajuste_centavos) = 'integer'),
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_medicao_boletim_capas_medicao ON medicao_boletim_capas (medicao_id, id);
CREATE TRIGGER IF NOT EXISTS medicao_boletim_capas_sem_update BEFORE UPDATE ON medicao_boletim_capas
BEGIN
    SELECT RAISE(ABORT, 'Capa do boletim é evento: não se altera');
END;
CREATE TRIGGER IF NOT EXISTS medicao_boletim_capas_sem_delete BEFORE DELETE ON medicao_boletim_capas
BEGIN
    SELECT RAISE(ABORT, 'Capa do boletim é evento: não se apaga');
END;
