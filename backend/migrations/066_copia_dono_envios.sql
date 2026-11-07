-- 066: envio por e-mail da copia cifrada do dono (issue #420). So' acrescenta: uma tabela nova.
--
-- Cada e-mail da copia e' uma linha: a reserva atomica do envio (app/envio_reserva.py, 035) e o envio que saiu.
-- Arquivo acima do teto do anexo vai em partes, um e-mail por parte, uma linha por parte. `rodada` 1 e' o envio
-- automatico logo depois de gerar a copia; 2, 3... sao os "Reenviar cópia do dono" de Administracao > Saude.
CREATE TABLE IF NOT EXISTS copia_dono_envios (
    id INTEGER PRIMARY KEY,
    arquivo TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    tamanho INTEGER NOT NULL,
    rodada INTEGER NOT NULL CHECK (rodada >= 1),
    parte INTEGER NOT NULL CHECK (parte >= 1),
    partes INTEGER NOT NULL CHECK (partes >= parte),
    envio_id INTEGER REFERENCES envios(id),
    envio_reservado_em TEXT,
    envio_reservado_por INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (arquivo, rodada, parte)
);
CREATE TRIGGER IF NOT EXISTS copia_dono_envios_sem_delete BEFORE DELETE ON copia_dono_envios
BEGIN
    SELECT RAISE(ABORT, 'Envio da cópia do dono não se apaga');
END;
