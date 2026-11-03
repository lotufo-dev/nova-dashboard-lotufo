-- 053: envio da planilha/carta ao protocolo do orgao pelo sistema (issue #282; spec 2026-10-20 §2.1, passo 2; E3 e
-- D11, decididas em 20/10/2026). So' acrescenta: duas tabelas novas. Nenhuma medicao existente muda.
--
-- A reserva atomica do envio (app/envio_reserva.py, 035) e' um UPDATE condicional na linha reservada. Ela nao pode
-- ficar em `medicao_planilhas`, que e' evento com o gatilho `medicao_planilhas_sem_update` (042; nota da
-- orquestradora na issue). Por isso cada versao enviada ganha UMA linha aqui (planilha_id UNIQUE): a reserva, o
-- e-mail que saiu e o numero do oficio digitado. A 1a versao enviada poe a medicao em `planilha_enviada`; a revisao
-- enviada depois (Rev01, Rev02...) e' outra linha, sem mudar o pedido congelado.
CREATE TABLE IF NOT EXISTS medicao_planilha_envios (
    id INTEGER PRIMARY KEY,
    medicao_id INTEGER NOT NULL REFERENCES medicoes(id),
    planilha_id INTEGER NOT NULL UNIQUE REFERENCES medicao_planilhas(id),
    numero_oficio TEXT,
    justificativa TEXT,
    envio_id INTEGER REFERENCES envios(id),
    envio_reservado_em TEXT,
    envio_reservado_por INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_medicao_planilha_envios_medicao ON medicao_planilha_envios (medicao_id, id);
CREATE TRIGGER IF NOT EXISTS medicao_planilha_envios_sem_delete BEFORE DELETE ON medicao_planilha_envios
BEGIN
    SELECT RAISE(ABORT, 'Envio da planilha/carta não se apaga');
END;

-- Pecas que o orgao pede na medicao (`orgaos.pecas`, por natureza), anexadas para ir no e-mail da planilha/carta.
-- Remover so' marca `removida_em` (como protocolo_pecas e pleito_anexos); o arquivo fica pelo hash.
CREATE TABLE IF NOT EXISTS medicao_planilha_pecas (
    id INTEGER PRIMARY KEY,
    medicao_id INTEGER NOT NULL REFERENCES medicoes(id),
    tipo TEXT NOT NULL CHECK (tipo IN ('boletim','planilha','diario','fotos','cronograma','art','ensaios','memorial',
                                       'diagrama','pluviometria','croqui','outro')),
    nome TEXT NOT NULL,
    arquivo TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    tamanho INTEGER NOT NULL,
    ext TEXT NOT NULL CHECK (ext IN ('pdf','xlsx')),
    usuario_id INTEGER REFERENCES usuarios(id),
    removida_em TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_medicao_planilha_pecas_medicao ON medicao_planilha_pecas (medicao_id, id);
CREATE TRIGGER IF NOT EXISTS medicao_planilha_pecas_sem_delete BEFORE DELETE ON medicao_planilha_pecas
BEGIN
    SELECT RAISE(ABORT, 'Peça anexada não se apaga: remova pela tela (fica no histórico)');
END;
