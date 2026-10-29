-- 052: pedidos de leitura do SIGA e rodadas do robo (issue #342). So' acrescenta.
-- Quem ve a tela SIGA pede uma leitura ("Atualizar processo" ou "Atualizar todos"): o servidor grava o pedido e
-- manda o Windows iniciar a tarefa do robo. O robo avisa quando comeca (o servidor decide o que ler e liga a' rodada
-- os pedidos atendidos), quando termina (com os nao lidos) e quando cai. Carimbos em UTC, como em siga_leituras.
CREATE TABLE IF NOT EXISTS siga_rodadas (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (tipo IN ('automatica', 'pedido')),
    completa INTEGER NOT NULL CHECK (completa IN (0, 1)),   -- 1 = todos os processos acompanhados
    processos TEXT NOT NULL,                                -- JSON: ids de siga_processos que a rodada le
    iniciada_em TEXT NOT NULL,
    terminada_em TEXT,                                      -- NULL = sem fim nem falha
    falha TEXT,                                             -- motivo, quando o robo caiu
    nao_lidos TEXT,                                         -- JSON: [{processo_id, codigo, numero, motivo}] no fim
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS siga_rodadas_terminada ON siga_rodadas(terminada_em);

-- Um pedido por clique que nao repete um pedido em aberto. processo_id NULL = todos.
CREATE TABLE IF NOT EXISTS siga_pedidos (
    id INTEGER PRIMARY KEY,
    processo_id INTEGER REFERENCES siga_processos(id),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    pedido_em TEXT NOT NULL,
    rodada_id INTEGER REFERENCES siga_rodadas(id),          -- NULL = em aberto
    disparado_em TEXT,                                      -- ultimo pedido ao Windows; NULL = nao disparou
    erro_disparo TEXT,                                      -- motivo da recusa no ultimo disparo; NULL = aceito
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS siga_pedidos_rodada ON siga_pedidos(rodada_id);
CREATE INDEX IF NOT EXISTS siga_pedidos_disparo ON siga_pedidos(disparado_em);
