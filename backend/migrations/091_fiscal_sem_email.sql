-- 091: o fiscal do contrato pode ser cadastrado sem e-mail. O e-mail so' entra no cadastro quando aparece em
-- documento ou mensagem do proprio orgao; o fiscal provado por documento (nome, cargo, portaria) vale como A/C da
-- carta mesmo sem endereco, e nao entra como destinatario.
--
-- `contrato_fiscais.email` deixa de ser NOT NULL. O SQLite nao muda restricao no lugar: a tabela e' reconstruida
-- pela receita da 042 e da 078 (criar nova, copiar todas as linhas, apagar a antiga, renomear), com foreign_keys
-- OFF so' durante o script. Mesmas colunas, na mesma ordem; nenhuma linha muda. Nenhuma tabela referencia
-- `contrato_fiscais`, e ela nao tinha indice nem gatilho proprio alem do UNIQUE.
--
-- O UNIQUE (contrato_id, email, desde) nao segura duas linhas sem e-mail (NULL nao repete para o SQLite): o indice
-- parcial abaixo faz esse papel, para o `cadastro aplicar` continuar sem duplicar o fiscal a cada execucao.
--
-- Reexecutavel: a `_nova` e' apagada antes de recriar. Atomica: tudo depois do PRAGMA roda numa transacao so'.
PRAGMA foreign_keys=OFF;
BEGIN;

DROP TABLE IF EXISTS contrato_fiscais_nova;
CREATE TABLE contrato_fiscais_nova (
    id INTEGER PRIMARY KEY,
    contrato_id INTEGER NOT NULL REFERENCES contratos(id),
    nome TEXT NOT NULL DEFAULT '',
    email TEXT,
    desde TEXT NOT NULL,
    cargo TEXT,
    tratamento TEXT,
    portaria TEXT,
    UNIQUE (contrato_id, email, desde)
);
INSERT INTO contrato_fiscais_nova (id, contrato_id, nome, email, desde, cargo, tratamento, portaria)
    SELECT id, contrato_id, nome, email, desde, cargo, tratamento, portaria FROM contrato_fiscais;
DROP TABLE contrato_fiscais;
ALTER TABLE contrato_fiscais_nova RENAME TO contrato_fiscais;
CREATE UNIQUE INDEX IF NOT EXISTS contrato_fiscais_sem_email
    ON contrato_fiscais(contrato_id, nome, desde) WHERE email IS NULL;

COMMIT;
PRAGMA foreign_keys=ON;
