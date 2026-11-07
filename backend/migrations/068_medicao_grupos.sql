-- 068: medido por grupo da planilha da medicao (issue #490). So' acrescenta (duas tabelas, indices e gatilhos).
-- A 067 fica para o cadastro do custo por obra (issue #489).
--
-- Cada xlsx lido e' um evento em `medicao_grupos`: ligado a versao da planilha/carta quando veio do anexo (o
-- `planilha_id`), sem versao quando veio da carga de uma pasta (medicoes anteriores ao fluxo da planilha/carta).
-- A leitura recusada (soma que nao bate com o valor pedido, aba ou cabecalho que falta) tambem fica registrada,
-- com o motivo, para a tela avisar "planilha não lida". Vale a leitura mais nova; as anteriores ficam.
-- Os itens lidos ficam em `medicao_grupo_itens`, com o grupo de cada um. Dinheiro em centavos inteiros;
-- quantidade em texto decimal (nao e' dinheiro, e o REAL do SQLite mudaria a casa decimal lida).
CREATE TABLE IF NOT EXISTS medicao_grupos (
    id INTEGER PRIMARY KEY,
    medicao_id INTEGER NOT NULL REFERENCES medicoes(id),
    planilha_id INTEGER REFERENCES medicao_planilhas(id),
    sha256 TEXT NOT NULL,
    arquivo TEXT,
    origem TEXT NOT NULL CHECK (origem IN ('anexo','carga')),
    -- 'falhou': erro inesperado na leitura do anexo (nao e' recusa da planilha); a carga le o anexo de novo
    situacao TEXT NOT NULL CHECK (situacao IN ('lida','recusada','falhou')),
    motivo TEXT,
    grupo_por TEXT CHECK (grupo_por IS NULL OR grupo_por IN ('cadastro','planilha')),
    -- sha256 dos grupos do cadastro de custo usados na leitura (NULL: pelos titulos da planilha)
    cadastro_sha256 TEXT,
    total_centavos INTEGER CHECK (total_centavos IS NULL OR typeof(total_centavos) = 'integer'),
    -- o valor de referencia conferido: o pedido da versao da planilha/carta (anexo) ou o da medicao (carga)
    pedido_centavos INTEGER CHECK (pedido_centavos IS NULL OR typeof(pedido_centavos) = 'integer'),
    usuario_id INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (situacao = 'lida' OR (motivo IS NOT NULL AND trim(motivo) <> '')),
    CHECK (situacao <> 'lida' OR (total_centavos IS NOT NULL AND pedido_centavos IS NOT NULL))
);
-- a mesma planilha (mesmo sha256) na mesma versao, contra o mesmo pedido e o mesmo cadastro, so' se le uma vez: a
-- carga repetida nao duplica; pedido ou cadastro novo pedem leitura nova
CREATE UNIQUE INDEX IF NOT EXISTS ux_medicao_grupos_lida
    ON medicao_grupos (medicao_id, sha256, COALESCE(planilha_id, 0), pedido_centavos, COALESCE(cadastro_sha256, ''))
    WHERE situacao = 'lida';
CREATE INDEX IF NOT EXISTS ix_medicao_grupos_medicao ON medicao_grupos (medicao_id, id);

CREATE TABLE IF NOT EXISTS medicao_grupo_itens (
    id INTEGER PRIMARY KEY,
    leitura_id INTEGER NOT NULL REFERENCES medicao_grupos(id),
    ordem INTEGER NOT NULL CHECK (typeof(ordem) = 'integer' AND ordem >= 1),
    grupo TEXT NOT NULL CHECK (trim(grupo) <> ''),
    item TEXT,
    codigo TEXT,
    descricao TEXT,
    unidade TEXT,
    quantidade_contratada TEXT,
    quantidade_medida TEXT,
    quantidade_acumulada TEXT,
    preco_unitario_centavos INTEGER
        CHECK (preco_unitario_centavos IS NULL OR typeof(preco_unitario_centavos) = 'integer'),
    valor_medido_centavos INTEGER NOT NULL CHECK (typeof(valor_medido_centavos) = 'integer'),
    valor_acumulado_centavos INTEGER
        CHECK (valor_acumulado_centavos IS NULL OR typeof(valor_acumulado_centavos) = 'integer'),
    UNIQUE (leitura_id, ordem)
);

CREATE TRIGGER IF NOT EXISTS medicao_grupos_sem_update BEFORE UPDATE ON medicao_grupos
BEGIN
    SELECT RAISE(ABORT, 'Leitura da planilha é evento: não se altera (anexe a planilha de novo)');
END;
CREATE TRIGGER IF NOT EXISTS medicao_grupos_sem_delete BEFORE DELETE ON medicao_grupos
BEGIN
    SELECT RAISE(ABORT, 'Leitura da planilha é evento: não se apaga');
END;
CREATE TRIGGER IF NOT EXISTS medicao_grupo_itens_sem_update BEFORE UPDATE ON medicao_grupo_itens
BEGIN
    SELECT RAISE(ABORT, 'Leitura da planilha é evento: não se altera (anexe a planilha de novo)');
END;
CREATE TRIGGER IF NOT EXISTS medicao_grupo_itens_sem_delete BEFORE DELETE ON medicao_grupo_itens
BEGIN
    SELECT RAISE(ABORT, 'Leitura da planilha é evento: não se apaga');
END;
