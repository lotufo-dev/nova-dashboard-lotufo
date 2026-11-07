-- 069: boletim do orgao (issue #290). So' acrescenta (uma coluna e uma tabela).
--
-- `medicao_atestos.pedido_centavos`: o pedido da medicao no momento em que o boletim foi registrado, congelado no
-- evento, para a linha do tempo mostrar a diferenca daquele dia (o pedido da medicao pode mudar depois, ex.: a
-- prevista do fluxo antigo que recebe o valor do espelho). NULL nos eventos anteriores a esta migracao e nos
-- boletins registrados sem pedido: a linha do tempo nao mostra pedido nem diferenca.
ALTER TABLE medicao_atestos ADD COLUMN pedido_centavos INTEGER
    CHECK (pedido_centavos IS NULL OR typeof(pedido_centavos) = 'integer');

-- Cada leitura da capa do SMO que propos campos: o servidor guarda o que leu de qual PDF (sha256) para qual
-- medicao. O boletim so' grava com origem `aceito` quando o PDF enviado e os tres campos sao exatamente os de uma
-- leitura guardada; senao, `manual`. Nao e' registro financeiro (nao muda valor nenhum); fica como historico.
CREATE TABLE IF NOT EXISTS medicao_boletim_leituras (
    id INTEGER PRIMARY KEY,
    medicao_id INTEGER NOT NULL REFERENCES medicoes(id),
    sha256 TEXT NOT NULL,
    numero_orgao TEXT,
    data TEXT,
    valor_centavos INTEGER CHECK (valor_centavos IS NULL OR (typeof(valor_centavos) = 'integer' AND valor_centavos >= 0)),
    fonte TEXT CHECK (fonte IS NULL OR fonte IN ('texto','ocr')),
    usuario_id INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_medicao_boletim_leituras ON medicao_boletim_leituras (medicao_id, sha256, id);
