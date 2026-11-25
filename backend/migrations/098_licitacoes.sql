-- 098: licitacoes (issue #908, docs/adr/0018). So' acrescenta.
-- O radar de licitacoes (fora do repositorio) le as fontes, junta, classifica e entrega a leitura por chave; a
-- dashboard guarda e mostra. Nada se apaga: o certame que o radar deixa de listar ganha `fora_desde`, e a favorita
-- tirada ganha `removida_em`.

-- Um certame, como o radar mandou. `dados` e' o certame preparado (JSON); as colunas ao lado sao copia do que se
-- filtra e ordena. `resumo` e' calculado pelo radar sobre o conteudo: igual ao gravado, nada muda.
CREATE TABLE IF NOT EXISTS lic_certames (
    id INTEGER PRIMARY KEY,
    chave TEXT NOT NULL UNIQUE,
    resumo TEXT NOT NULL,
    dados TEXT NOT NULL,
    uf TEXT NOT NULL DEFAULT '',
    data_sessao TEXT,                                   -- AAAA-MM-DD (data de documento)
    valor_centavos INTEGER,
    encerrada INTEGER NOT NULL DEFAULT 0 CHECK (encerrada IN (0, 1)),   -- pela situacao que a fonte publicou
    nova INTEGER NOT NULL DEFAULT 0 CHECK (nova IN (0, 1)),             -- esta' na lista de novas do radar
    grande_vulto INTEGER NOT NULL DEFAULT 0 CHECK (grande_vulto IN (0, 1)),
    nota INTEGER,                                       -- nota de recomendada; NULL = fora do perfil
    recebido_em TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
    fora_desde TEXT                                     -- o radar deixou de listar (UTC); NULL = listado
);
CREATE INDEX IF NOT EXISTS lic_certames_listados ON lic_certames(fora_desde);

-- Uma linha por rodada fechada do radar. `lido_em` em UTC, como todo carimbo do banco.
CREATE TABLE IF NOT EXISTS lic_leituras (
    id INTEGER PRIMARY KEY,
    lido_em TEXT NOT NULL UNIQUE,
    certames INTEGER NOT NULL,                          -- quantos o radar listou
    fontes TEXT NOT NULL DEFAULT '[]',                  -- a situacao de cada fonte na leitura (JSON)
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A licitacao que alguem decidiu acompanhar. Ate' o corte (docs/adr/0018) e' espelho do radar (`origem` radar,
-- `autor_radar` como ele escreveu). Sem FK para lic_certames: a chave e' a identidade que o radar usa, e a favorita
-- tirada continua contando a historia mesmo se o certame mudar de chave la'.
CREATE TABLE IF NOT EXISTS lic_favoritas (
    id INTEGER PRIMARY KEY,
    chave TEXT NOT NULL,
    desde TEXT NOT NULL,                                -- AAAA-MM-DD: o dia em que foi favoritada
    etapa TEXT CHECK (etapa IS NULL OR etapa IN ('acompanhando', 'em_analise', 'proposta_enviada', 'vencida',
                                                 'perdida', 'desistida', 'encerrada')),
    etapa_em TEXT,
    origem TEXT NOT NULL DEFAULT 'radar' CHECK (origem IN ('radar', 'dashboard')),
    autor_radar TEXT,
    criada_por INTEGER REFERENCES usuarios(id),
    criada_em TEXT NOT NULL DEFAULT (datetime('now')),
    removida_em TEXT,
    removida_por INTEGER REFERENCES usuarios(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS lic_favoritas_ativa ON lic_favoritas(chave) WHERE removida_em IS NULL;
