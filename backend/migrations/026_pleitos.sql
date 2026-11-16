-- 026: pleitos (reajuste, prazo, conclusao), medicao final, folga por contrato (bloco 7; spec §5.2, §7.2 a §7.4).
CREATE TABLE IF NOT EXISTS pleitos (
    id INTEGER PRIMARY KEY,
    contrato_id INTEGER NOT NULL REFERENCES contratos(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('reajuste','prazo','conclusao')),
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
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS pleitos_contrato ON pleitos(contrato_id, tipo);
-- um oficio pode cobrir duas datas-base (obra com dois indices: SINAPI em janeiro e SICRO em marco)
CREATE UNIQUE INDEX IF NOT EXISTS pleitos_cadastro
    ON pleitos(contrato_id, tipo, numero_oficio, COALESCE(data_base_mes, '')) WHERE origem = 'cadastro';

CREATE TABLE IF NOT EXISTS pleito_anexos (
    id INTEGER PRIMARY KEY,
    pleito_id INTEGER NOT NULL REFERENCES pleitos(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('planilha_calculo','cronograma','outro')),
    nome TEXT NOT NULL,
    arquivo TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    tamanho INTEGER NOT NULL,
    ext TEXT NOT NULL CHECK (ext IN ('pdf','xlsx')),
    removido_em TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

ALTER TABLE medicoes ADD COLUMN final INTEGER NOT NULL DEFAULT 0;
ALTER TABLE medicoes ADD COLUMN final_em TEXT;
ALTER TABLE contratos ADD COLUMN folga_vigencia_dias INTEGER;
