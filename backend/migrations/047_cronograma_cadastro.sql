-- 047: versao de cronograma vinda do cadastro (issue #256; spec 2026-10-20 §2.4 e §3.4).
--
-- `contratos/<obra>.yaml` ganha `cronograma: [{chave, origem, data, instrumento, itens}]`; o `cadastro aplicar`
-- cria uma `cronograma_versoes` por entrada, com criado_em = data do documento. Esta tabela guarda o que o
-- documento diz da versao (a chave do cadastro, a origem contratual/aditivo/carta/smo, a data e o instrumento),
-- para reaplicar sem duplicar e recusar a mesma chave com outro conteudo. A `origem` de cronograma_versoes
-- (detectado/aceito/manual) fica como esta: o CHECK dela nao muda sem reconstruir a tabela.
-- So' acrescenta; nenhuma versao existente e' tocada (as da carga de 04/09/2026 ficam sem linha aqui).
CREATE TABLE IF NOT EXISTS cronograma_versoes_cadastro (
    versao_id INTEGER PRIMARY KEY REFERENCES cronograma_versoes(id),
    contrato_id INTEGER NOT NULL REFERENCES contratos(id),
    chave TEXT NOT NULL,
    origem TEXT NOT NULL CHECK (origem IN ('contratual','aditivo','carta','smo')),
    data_documento TEXT NOT NULL CHECK (data_documento GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    instrumento TEXT,
    UNIQUE (contrato_id, chave)
);
