-- 051: leituras do monitor do SIGA (issue #327). So' acrescenta.
-- O robo do SIGA (fora do repositorio) le a cada 15 minutos a situacao e as movimentacoes de cada processo
-- protocolado e manda para POST /api/siga/leituras. Nada se apaga nem se sobrescreve: leitura repetida nao cria
-- linha (UNIQUE), e o processo so' ganha codigo, numero, nome ou vinculo onde estava vazio.
CREATE TABLE IF NOT EXISTS siga_processos (
    id INTEGER PRIMARY KEY,
    codigo TEXT UNIQUE,                         -- codigo do link de acompanhamento; pode faltar
    numero TEXT,                                -- ORGAO-PRO-AAAA/NNNNN, como o SIGA escreve; pode faltar
    nome TEXT,
    contrato_id INTEGER REFERENCES contratos(id),
    protocolo_id INTEGER REFERENCES protocolos(id),
    medicao_id INTEGER REFERENCES medicoes(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (codigo IS NOT NULL OR numero IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS siga_processos_numero ON siga_processos(numero);
CREATE INDEX IF NOT EXISTS siga_processos_medicao ON siga_processos(medicao_id);

-- Uma linha por processo e rodada do robo. `lido_em` em UTC (formato do SQLite), como todo carimbo do banco.
CREATE TABLE IF NOT EXISTS siga_leituras (
    id INTEGER PRIMARY KEY,
    processo_id INTEGER NOT NULL REFERENCES siga_processos(id),
    lido_em TEXT NOT NULL,
    situacao TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (processo_id, lido_em)
);
CREATE INDEX IF NOT EXISTS siga_leituras_processo ON siga_leituras(processo_id, lido_em);

-- `data` e' a do SIGA, hora de Cuiaba, gravada como 'AAAA-MM-DD HH:MM:SS' (data de documento, nao carimbo).
-- Campos de texto NOT NULL DEFAULT '': no SQLite, NULL nao repete em UNIQUE, e a linha vazia duplicaria.
CREATE TABLE IF NOT EXISTS siga_movimentacoes (
    id INTEGER PRIMARY KEY,
    processo_id INTEGER NOT NULL REFERENCES siga_processos(id),
    data TEXT NOT NULL,
    evento TEXT NOT NULL DEFAULT '',
    cad_lotacao TEXT NOT NULL DEFAULT '',
    cad_pessoa TEXT NOT NULL DEFAULT '',
    at_lotacao TEXT NOT NULL DEFAULT '',
    at_pessoa TEXT NOT NULL DEFAULT '',
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (processo_id, data, evento, cad_lotacao, cad_pessoa, at_lotacao, at_pessoa)
);
CREATE INDEX IF NOT EXISTS siga_movimentacoes_processo ON siga_movimentacoes(processo_id, data);
