-- 072: justificativa do reajuste fora da previsao (issue #274; spec 2026-10-20 §2.2, decisao do Leo de 08/11/2026).
-- So' acrescenta (uma tabela, um indice e dois gatilhos).
--
-- `reajuste_justificativas` e' evento, como `reajuste_previsoes` (043): a operacao explica por que o pedido da
-- competencia difere do previsto vigente, e a linha guarda o pedido e o previsto daquele momento, com a identidade de
-- cada um: `previsto_ref` e' o evento que da' o previsto ("previsao:<id>" de `reajuste_previsoes`, ou
-- "apostilamento:<chave>" do termo), e `medicoes` os numeros das medicoes de reajuste somadas no pedido (JSON). A
-- justificativa vale enquanto nada disso mudar (app/reajuste.py, `justificativa_vigente`): previsao nova, termo novo
-- ou medicao a mais ou a menos derrubam a justificativa mesmo que o valor volte ao de antes. Nunca se altera nem se
-- apaga; justificar de novo e' linha nova.
CREATE TABLE IF NOT EXISTS reajuste_justificativas (
    id INTEGER PRIMARY KEY,
    contrato_id INTEGER NOT NULL REFERENCES contratos(id),
    data_base_mes TEXT NOT NULL CHECK (data_base_mes GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'
        AND substr(data_base_mes, 6, 2) BETWEEN '01' AND '12'),
    ciclo INTEGER NOT NULL CHECK (typeof(ciclo) = 'integer'),
    competencia TEXT NOT NULL CHECK (competencia GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'
        AND substr(competencia, 6, 2) BETWEEN '01' AND '12'),
    texto TEXT NOT NULL CHECK (length(trim(texto)) >= 10),
    pedido_centavos INTEGER NOT NULL CHECK (typeof(pedido_centavos) = 'integer'),
    previsto_centavos INTEGER NOT NULL CHECK (typeof(previsto_centavos) = 'integer'),
    previsto_ref TEXT NOT NULL,
    medicoes TEXT NOT NULL CHECK (json_valid(medicoes)),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_reajuste_justificativas_competencia
    ON reajuste_justificativas (contrato_id, data_base_mes, ciclo, competencia, id);

CREATE TRIGGER IF NOT EXISTS reajuste_justificativas_sem_update BEFORE UPDATE ON reajuste_justificativas
BEGIN
    SELECT RAISE(ABORT, 'Justificativa de reajuste é evento: não se altera (registre uma nova)');
END;
CREATE TRIGGER IF NOT EXISTS reajuste_justificativas_sem_delete BEFORE DELETE ON reajuste_justificativas
BEGIN
    SELECT RAISE(ABORT, 'Justificativa de reajuste é evento: não se apaga');
END;
