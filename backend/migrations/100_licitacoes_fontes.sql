-- 100: fontes, alertas, conferencia e resultados das licitacoes (fatia 4 da #906, issue #919, docs/adr/0018).
-- So' acrescenta. O radar passa a mandar, no fechamento da rodada, os alertas do dia, os pares que nao conseguiu provar
-- iguais e o quadro de resultados; a dashboard guarda e mostra. Nada se apaga: o par que o radar deixa de listar ganha
-- `fora_desde`, e a conferencia refeita ganha `desfeita_em`.

-- Os alertas do dia por regra (JSON: [{regra, nome, chaves}]) e o quadro de resultados (JSON; NULL = a rodada nao
-- trouxe, e vale o ultimo que trouxe), na rodada em que chegaram.
ALTER TABLE lic_leituras ADD COLUMN alertas TEXT NOT NULL DEFAULT '[]';
ALTER TABLE lic_leituras ADD COLUMN resultados TEXT;

-- Um par de certames que o radar achou parecidos e nao conseguiu provar iguais. `par` e' a identidade que o radar da'.
-- Sem FK para lic_certames: as chaves sao a identidade do radar, como nas favoritas.
CREATE TABLE IF NOT EXISTS lic_pares (
    id INTEGER PRIMARY KEY,
    par TEXT NOT NULL UNIQUE,
    chave_a TEXT NOT NULL,
    chave_b TEXT NOT NULL,
    motivo TEXT NOT NULL DEFAULT '',
    recebido_em TEXT NOT NULL DEFAULT (datetime('now')),
    fora_desde TEXT                                     -- o radar deixou de listar (UTC); NULL = pendente no radar
);

-- A resposta de uma pessoa a um par: "e' o mesmo" ou "e' outro". Ate' o corte e' espelho do radar (`origem` radar).
-- Uma em vigor por par; a refeita fica, com `desfeita_em`.
CREATE TABLE IF NOT EXISTS lic_conferencias (
    id INTEGER PRIMARY KEY,
    par TEXT NOT NULL,
    chave_a TEXT NOT NULL,
    chave_b TEXT NOT NULL,
    resposta TEXT NOT NULL CHECK (resposta IN ('mesmo', 'outro')),
    origem TEXT NOT NULL DEFAULT 'radar' CHECK (origem IN ('radar', 'dashboard')),
    autor_radar TEXT,
    criada_por INTEGER REFERENCES usuarios(id),
    criada_em TEXT NOT NULL DEFAULT (datetime('now')),
    desfeita_em TEXT,
    desfeita_por INTEGER REFERENCES usuarios(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS lic_conferencias_em_vigor ON lic_conferencias(par) WHERE desfeita_em IS NULL;
