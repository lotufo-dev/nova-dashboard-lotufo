-- 056: pedido de aditivo de valor (RPFO, readequacao) enviado antes do sistema (issue #398). So' acrescenta: o tipo
-- 'valor' no CHECK de `pleitos.tipo` e as colunas `valor_centavos` (o valor pedido) e `objeto`. Esse tipo so' entra
-- pelo cadastro (`pleitos_anteriores`, origem 'cadastro'): nao ha' carta de aditivo de valor no sistema.
--
-- O CHECK de `tipo` so' muda reconstruindo `pleitos`, pela receita da 037 e da 042 (criar nova, copiar, apagar a
-- antiga, renomear), com foreign_keys OFF so' durante o script; as filhas (pleito_anexos,
-- reajuste_previsoes e a propria `reemite_pleito_id`) referenciam `pleitos` pelo NOME e voltam a valer quando a nova
-- assume o nome. Os indices da 026 sao recriados. O runner (db.migrate) religa foreign_keys mesmo se falhar.
--
-- Reexecutavel: as colunas novas entram ANTES da copia, por ALTER (que o runner pula quando ja' existem), para a copia
-- listar as mesmas colunas na 1a e na 2a vez; a `_nova` e' apagada antes de recriar. Atomica: tudo depois do PRAGMA
-- roda numa transacao so' (o PRAGMA foreign_keys nao muda dentro de transacao, por isso fica fora).
PRAGMA foreign_keys=OFF;
BEGIN;

-- centavos inteiros: INTEGER no SQLite e' so' afinidade, por isso o typeof
ALTER TABLE pleitos ADD COLUMN valor_centavos INTEGER
    CHECK (valor_centavos IS NULL OR (typeof(valor_centavos) = 'integer' AND valor_centavos > 0));
ALTER TABLE pleitos ADD COLUMN objeto TEXT;

-- o gatilho da 043 em reajuste_previsoes cita `pleitos` no corpo: o RENAME confere o esquema inteiro e recusaria o
-- gatilho enquanto `pleitos` nao existe. Ele sai antes da troca e volta igual (mesmo texto da 043) depois dela.
DROP TRIGGER IF EXISTS reajuste_previsoes_fonte_do_contrato;
DROP TABLE IF EXISTS pleitos_nova;
CREATE TABLE pleitos_nova (
    id INTEGER PRIMARY KEY,
    contrato_id INTEGER NOT NULL REFERENCES contratos(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('reajuste','prazo','conclusao','valor')),
    origem TEXT NOT NULL DEFAULT 'sistema' CHECK (origem IN ('sistema','cadastro')),
    data_base_mes TEXT,
    ciclo INTEGER,
    dias INTEGER CHECK (dias IS NULL OR dias > 0),
    justificativa TEXT,
    numero_oficio TEXT,
    corpo_carta TEXT,
    montado_arquivo TEXT,
    montado_sha256 TEXT,
    montado_paginas INTEGER,
    assinado_arquivo TEXT,
    assinado_sha256 TEXT,
    conferencia TEXT,
    envio_id INTEGER REFERENCES envios(id),
    envio_justificativa TEXT,
    enviado_em TEXT,
    situacao TEXT NOT NULL DEFAULT 'rascunho'
        CHECK (situacao IN ('rascunho','montado','assinado','enviado','descartado')),
    usuario_id INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    envio_reservado_em TEXT,
    envio_reservado_por INTEGER REFERENCES usuarios(id),
    reemite_pleito_id INTEGER REFERENCES pleitos(id),
    instrumento_chave TEXT,
    reemissao TEXT CHECK (reemissao IS NULL OR reemissao IN ('reiteracao','cronograma')),
    valor_centavos INTEGER
        CHECK (valor_centavos IS NULL OR (typeof(valor_centavos) = 'integer' AND valor_centavos > 0)),
    objeto TEXT,
    -- o valor pedido e' do pedido de valor, e so' dele; o pedido de valor so' entra pelo cadastro
    CHECK ((tipo = 'valor') = (valor_centavos IS NOT NULL)),
    CHECK (tipo <> 'valor' OR origem = 'cadastro')
);
INSERT INTO pleitos_nova (id, contrato_id, tipo, origem, data_base_mes, ciclo, dias, justificativa, numero_oficio,
    corpo_carta, montado_arquivo, montado_sha256, montado_paginas, assinado_arquivo, assinado_sha256, conferencia,
    envio_id, envio_justificativa, enviado_em, situacao, usuario_id, criado_em, envio_reservado_em,
    envio_reservado_por, reemite_pleito_id, instrumento_chave, reemissao, valor_centavos, objeto)
  SELECT id, contrato_id, tipo, origem, data_base_mes, ciclo, dias, justificativa, numero_oficio,
    corpo_carta, montado_arquivo, montado_sha256, montado_paginas, assinado_arquivo, assinado_sha256, conferencia,
    envio_id, envio_justificativa, enviado_em, situacao, usuario_id, criado_em, envio_reservado_em,
    envio_reservado_por, reemite_pleito_id, instrumento_chave, reemissao, valor_centavos, objeto
  FROM pleitos;
DROP TABLE pleitos;
ALTER TABLE pleitos_nova RENAME TO pleitos;

CREATE INDEX IF NOT EXISTS pleitos_contrato ON pleitos(contrato_id, tipo);
-- um oficio pode cobrir duas datas-base (5 Bairros, CT/234/LT/2026: SINAPI jan e SICRO mar)
CREATE UNIQUE INDEX IF NOT EXISTS pleitos_cadastro
    ON pleitos(contrato_id, tipo, numero_oficio, COALESCE(data_base_mes, '')) WHERE origem = 'cadastro';
CREATE TRIGGER IF NOT EXISTS reajuste_previsoes_fonte_do_contrato BEFORE INSERT ON reajuste_previsoes
WHEN (NEW.pleito_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM pleitos WHERE id = NEW.pleito_id AND contrato_id = NEW.contrato_id
                      AND tipo = 'reajuste' AND data_base_mes = NEW.data_base_mes AND ciclo = NEW.ciclo))
  OR (NEW.instrumento_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM instrumentos WHERE id = NEW.instrumento_id AND contrato_id = NEW.contrato_id
                      AND tipo = 'apostilamento_reajuste'))
BEGIN
    SELECT RAISE(ABORT, 'Previsão de reajuste aponta pleito ou instrumento que não é o reajuste deste contrato, data-base e ciclo');
END;
COMMIT;

PRAGMA foreign_keys=ON;
