-- 099: decisoes das licitacoes (fatia 2 da #906, docs/adr/0018). So' acrescenta.
-- O corte passa as decisoes (favorita, etapa, descarte) do radar para a dashboard: antes dele a dashboard so' espelha
-- o que o radar manda; depois, so' ela grava. Nada se apaga: o descarte desfeito ganha `desfeito_em`.

-- Uma linha so': quando foi o corte e quem o fez. `corte_em` NULL = as decisoes ainda estao com o radar.
CREATE TABLE IF NOT EXISTS lic_estado (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    corte_em TEXT,
    corte_por INTEGER REFERENCES usuarios(id)
);
INSERT OR IGNORE INTO lic_estado (id) VALUES (1);

-- A recomendada que alguem tirou da fila, com o motivo. Os motivos sao os que o radar ja' usava.
CREATE TABLE IF NOT EXISTS lic_descartes (
    id INTEGER PRIMARY KEY,
    chave TEXT NOT NULL,
    motivo TEXT NOT NULL CHECK (motivo IN ('tipo de obra', 'local', 'valor', 'órgão', 'outro')),
    origem TEXT NOT NULL DEFAULT 'radar' CHECK (origem IN ('radar', 'dashboard')),
    autor_radar TEXT,
    criado_por INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    desfeito_em TEXT,
    desfeito_por INTEGER REFERENCES usuarios(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS lic_descartes_ativo ON lic_descartes(chave) WHERE desfeito_em IS NULL;

-- Ate' que dia (AAAA-MM-DD) as mudancas da favorita foram vistas: as posteriores a poem de volta na Triagem.
ALTER TABLE lic_favoritas ADD COLUMN mudancas_vistas_ate TEXT;
