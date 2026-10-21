-- 043: motor de apostilamento (issue #270; spec 2026-10-20-motores-medicao-apostilamento, secao 2.2). So' acrescenta.
-- `reajuste_previsoes` e' evento: uma linha por competencia por fonte, que nunca se altera nem se apaga (correcao e'
-- linha nova, como a 039). A previsao vigente de uma competencia e' a mais recente da origem mais forte
-- (apostilamento > pleito > manual); ver app/reajuste.py (previsoes_vigentes).
CREATE TABLE IF NOT EXISTS reajuste_previsoes (
    id INTEGER PRIMARY KEY,
    contrato_id INTEGER NOT NULL REFERENCES contratos(id),
    data_base_mes TEXT NOT NULL CHECK (data_base_mes GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'
        AND substr(data_base_mes, 6, 2) BETWEEN '01' AND '12'),
    ciclo INTEGER NOT NULL CHECK (typeof(ciclo) = 'integer'),
    competencia TEXT NOT NULL CHECK (competencia GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'
        AND substr(competencia, 6, 2) BETWEEN '01' AND '12'),
    -- centavos inteiros; sem limite de sinal: indice deflacionario da' reajuste negativo
    valor_previsto_centavos INTEGER NOT NULL CHECK (typeof(valor_previsto_centavos) = 'integer'),
    origem TEXT NOT NULL CHECK (origem IN ('pleito','apostilamento','manual')),
    pleito_id INTEGER REFERENCES pleitos(id),
    instrumento_id INTEGER REFERENCES instrumentos(id),
    usuario_id INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    -- a previsao diz de onde veio: a do pleito aponta o pleito, a do apostilamento aponta o instrumento
    CHECK (origem <> 'pleito' OR pleito_id IS NOT NULL),
    CHECK (origem <> 'apostilamento' OR instrumento_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_reajuste_previsoes_competencia
    ON reajuste_previsoes (contrato_id, data_base_mes, ciclo, competencia, id);

-- a fonte apontada e' do mesmo contrato (a linha nao se apaga depois, entao a guarda e' na entrada)
CREATE TRIGGER IF NOT EXISTS reajuste_previsoes_fonte_do_contrato BEFORE INSERT ON reajuste_previsoes
WHEN (NEW.pleito_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM pleitos WHERE id = NEW.pleito_id AND contrato_id = NEW.contrato_id))
  OR (NEW.instrumento_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM instrumentos WHERE id = NEW.instrumento_id AND contrato_id = NEW.contrato_id))
BEGIN
    SELECT RAISE(ABORT, 'Previsão de reajuste aponta pleito ou instrumento de outro contrato');
END;

CREATE TRIGGER IF NOT EXISTS reajuste_previsoes_sem_update BEFORE UPDATE ON reajuste_previsoes
BEGIN
    SELECT RAISE(ABORT, 'Previsão de reajuste é evento: não se altera (registre uma previsão nova)');
END;
CREATE TRIGGER IF NOT EXISTS reajuste_previsoes_sem_delete BEFORE DELETE ON reajuste_previsoes
BEGIN
    SELECT RAISE(ABORT, 'Previsão de reajuste é evento: não se apaga');
END;

-- medicao de reajuste: a data-base e o ciclo que ela cobre (gravados na criacao; 5 Bairros tem duas bases)
ALTER TABLE medicoes ADD COLUMN data_base_mes TEXT;
ALTER TABLE medicoes ADD COLUMN ciclo INTEGER;
-- pleito reemitido apos aditivo aponta o anterior; o apostilamento que o atendeu (chave do instrumento no cadastro)
ALTER TABLE pleitos ADD COLUMN reemite_pleito_id INTEGER REFERENCES pleitos(id);
ALTER TABLE pleitos ADD COLUMN instrumento_chave TEXT;
