-- 070: boletim do orgao (issue #290). So' acrescenta (uma coluna, uma tabela e um indice).
--
-- `medicao_atestos.pedido_centavos`: o pedido da medicao no momento em que o boletim foi registrado, congelado no
-- evento, para a linha do tempo mostrar a diferenca daquele dia (o pedido da medicao pode mudar depois, ex.: a
-- prevista do fluxo antigo que recebe o valor do espelho). NULL nos eventos anteriores a esta migracao e nos
-- boletins registrados sem pedido: a linha do tempo nao mostra pedido nem diferenca.
ALTER TABLE medicao_atestos ADD COLUMN pedido_centavos INTEGER
    CHECK (pedido_centavos IS NULL OR typeof(pedido_centavos) = 'integer');

-- As leituras da capa do SMO que podem dar origem `aceito`: os tres campos lidos, de qual PDF (sha256), para qual
-- medicao (so' a capa do numero dela). O boletim so' grava `aceito` quando o PDF enviado e os tres campos sao os de
-- uma linha daqui; senao, `manual`. Tabela de apoio, nao registro financeiro: a mesma leitura repetida nao duplica
-- (indice unico) e o servidor guarda so' as mais recentes de cada medicao.
CREATE TABLE IF NOT EXISTS medicao_boletim_leituras (
    id INTEGER PRIMARY KEY,
    medicao_id INTEGER NOT NULL REFERENCES medicoes(id),
    sha256 TEXT NOT NULL,
    numero_orgao TEXT NOT NULL,
    data TEXT NOT NULL,
    valor_centavos INTEGER NOT NULL CHECK (typeof(valor_centavos) = 'integer' AND valor_centavos >= 0),
    fonte TEXT CHECK (fonte IS NULL OR fonte IN ('texto','ocr')),
    usuario_id INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_medicao_boletim_leituras
    ON medicao_boletim_leituras (medicao_id, sha256, numero_orgao, data, valor_centavos);
