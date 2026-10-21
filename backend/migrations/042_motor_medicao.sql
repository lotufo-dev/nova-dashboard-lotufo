-- 042: motor de medicao (issue #280; spec 2026-10-20-motores-medicao-apostilamento §2.1, decidida pelo Leo em
-- 20/10/2026). So' acrescenta: estados planilha_gerada / planilha_enviada / boletim_recebido (antes do espelho),
-- colunas da planilha/carta na medicao, eventos da planilha/carta (com versao e motivo) e da assinatura, e os
-- campos do boletim no evento de atesto. Nenhuma medicao existente muda de estado nem de valor.
--
-- O CHECK de `estado` so' muda reconstruindo `medicoes`, pela mesma receita da 020 (lang_altertable: criar nova,
-- copiar, apagar a antiga, renomear), com foreign_keys OFF so' durante o script; as filhas referenciam `medicoes`
-- pelo NOME e voltam a valer quando a nova assume o nome. O runner (db.migrate) religa foreign_keys mesmo se o
-- script falhar no meio.
--
-- Reexecutavel (licao da 020): as colunas novas entram ANTES da copia, por ALTER (que o runner pula quando ja'
-- existem), para a copia listar as mesmas colunas na 1a e na 2a vez; a `_nova` e' apagada antes de recriar
-- (residuo de execucao interrompida nao impede a proxima).
--
-- Atomica: tudo depois do PRAGMA roda numa transacao so' (o PRAGMA foreign_keys nao muda dentro de transacao, por
-- isso fica fora). Se o processo cair ou um comando falhar entre o DROP de `medicoes` e o RENAME, nada fica
-- gravado e `medicoes` continua inteira, sem depender da `_nova`.
--
-- A 043 (motor de apostilamento, issue #270) acrescenta `data_base_mes` e `ciclo` em `medicoes` e pode rodar ANTES
-- desta num banco que a recebeu primeiro. Por isso as duas colunas tambem entram aqui por ALTER (pulado quando a
-- 043 ja' as criou; e a 043 pula o dela quando esta veio antes), com a mesma definicao, e vao na copia: em
-- qualquer ordem, nada se perde.
PRAGMA foreign_keys=OFF;
BEGIN;

-- Medicao: periodo da planilha/carta (como em `espelhos`; obrigatorio a partir de planilha_gerada, cobrado pela
-- aplicacao), envio da planilha/carta e o numero da medicao no orgao (D6: o canonico onde difere do da Lotufo).
ALTER TABLE medicoes ADD COLUMN periodo_inicio TEXT;
ALTER TABLE medicoes ADD COLUMN periodo_fim TEXT;
ALTER TABLE medicoes ADD COLUMN planilha_enviada_em TEXT;
ALTER TABLE medicoes ADD COLUMN planilha_envio_origem TEXT CHECK (planilha_envio_origem IN ('sistema','externo'));
ALTER TABLE medicoes ADD COLUMN numero_orgao INTEGER
    CHECK (numero_orgao IS NULL OR (typeof(numero_orgao) = 'integer' AND numero_orgao >= 1));
-- as da 043 (ver cabecalho)
ALTER TABLE medicoes ADD COLUMN data_base_mes TEXT;
ALTER TABLE medicoes ADD COLUMN ciclo INTEGER;

DROP TABLE IF EXISTS medicoes_nova;
CREATE TABLE medicoes_nova (
    id INTEGER PRIMARY KEY,
    contrato_id INTEGER NOT NULL REFERENCES contratos(id),
    numero INTEGER NOT NULL CHECK (numero >= 1),
    tipo TEXT NOT NULL CHECK (tipo IN ('execucao','projeto','reajuste')),
    competencia TEXT NOT NULL CHECK (competencia GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
    estado TEXT NOT NULL DEFAULT 'prevista'
        CHECK (estado IN ('prevista','planilha_gerada','planilha_enviada','boletim_recebido',
                          'espelho_gerado','espelho_enviado','nota_emitida',
                          'protocolada','nf_emitida','recebida','cancelada','desistida')),
    valor_protocolado_centavos INTEGER CHECK (valor_protocolado_centavos >= 0),
    valor_protocolado_origem TEXT CHECK (valor_protocolado_origem IN ('detectado','aceito','manual','espelho')),
    valor_atestado_centavos INTEGER CHECK (valor_atestado_centavos >= 0),
    valor_atestado_origem TEXT CHECK (valor_atestado_origem IN ('detectado','aceito','manual')),
    motivo_represamento TEXT,
    congelada INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    atestado_em TEXT,
    nf_emitida_em TEXT,
    recebida_em TEXT,
    espelho_em TEXT,
    espelho_origem TEXT CHECK (espelho_origem IN ('detectado','aceito','manual')),
    nota_emitida_em TEXT,
    final INTEGER NOT NULL DEFAULT 0,
    final_em TEXT,
    envio_origem TEXT CHECK (envio_origem IN ('sistema','externo')),
    envio_externo_em TEXT,
    envio_externo_obs TEXT,
    periodo_inicio TEXT,
    periodo_fim TEXT,
    planilha_enviada_em TEXT,
    planilha_envio_origem TEXT CHECK (planilha_envio_origem IN ('sistema','externo')),
    numero_orgao INTEGER CHECK (numero_orgao IS NULL OR (typeof(numero_orgao) = 'integer' AND numero_orgao >= 1)),
    data_base_mes TEXT,
    ciclo INTEGER,
    UNIQUE (contrato_id, numero, tipo)
);
INSERT INTO medicoes_nova (id, contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos,
    valor_protocolado_origem, valor_atestado_centavos, valor_atestado_origem, motivo_represamento,
    congelada, criado_em, atestado_em, nf_emitida_em, recebida_em, espelho_em, espelho_origem,
    nota_emitida_em, final, final_em, envio_origem, envio_externo_em, envio_externo_obs,
    periodo_inicio, periodo_fim, planilha_enviada_em, planilha_envio_origem, numero_orgao,
    data_base_mes, ciclo)
  SELECT id, contrato_id, numero, tipo, competencia, estado, valor_protocolado_centavos,
    valor_protocolado_origem, valor_atestado_centavos, valor_atestado_origem, motivo_represamento,
    congelada, criado_em, atestado_em, nf_emitida_em, recebida_em, espelho_em, espelho_origem,
    nota_emitida_em, final, final_em, envio_origem, envio_externo_em, envio_externo_obs,
    periodo_inicio, periodo_fim, planilha_enviada_em, planilha_envio_origem, numero_orgao,
    data_base_mes, ciclo
  FROM medicoes;
DROP TABLE medicoes;
ALTER TABLE medicoes_nova RENAME TO medicoes;

-- Planilha/carta como evento: cada registro (e cada revisao, Rev01, Rev02...) e' uma versao nova, com motivo a
-- partir da 2a. Vigente = maior versao; o pedido congelado e' o da 1a versao enviada (cobrado pela aplicacao).
-- Dois arquivos por versao: o oficio assinado (PDF) em `arquivo`/`sha256` e a planilha (XLSX) em
-- `arquivo_planilha`/`sha256_planilha`, relativos a pasta do banco, pelo hash.
CREATE TABLE IF NOT EXISTS medicao_planilhas (
    id INTEGER PRIMARY KEY,
    medicao_id INTEGER NOT NULL REFERENCES medicoes(id),
    versao INTEGER NOT NULL CHECK (typeof(versao) = 'integer' AND versao >= 1),
    periodo_inicio TEXT,
    periodo_fim TEXT,
    -- centavos inteiros: INTEGER no SQLite e' so' afinidade (100.5 ficaria REAL), por isso o typeof
    valor_pedido_centavos INTEGER NOT NULL
        CHECK (typeof(valor_pedido_centavos) = 'integer' AND valor_pedido_centavos >= 0),
    acumulado_anterior_centavos INTEGER NOT NULL
        CHECK (typeof(acumulado_anterior_centavos) = 'integer' AND acumulado_anterior_centavos >= 0),
    arquivo TEXT,
    sha256 TEXT,
    arquivo_planilha TEXT,
    sha256_planilha TEXT,
    origem TEXT NOT NULL CHECK (origem IN ('manual','detectado','aceito')),
    usuario_id INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    motivo TEXT,
    CHECK (versao = 1 OR (motivo IS NOT NULL AND trim(motivo) <> '')),
    UNIQUE (medicao_id, versao)
);
CREATE TRIGGER IF NOT EXISTS medicao_planilhas_sem_update BEFORE UPDATE ON medicao_planilhas
BEGIN
    SELECT RAISE(ABORT, 'Planilha/carta é evento: não se altera (registre uma versão nova com o motivo)');
END;
CREATE TRIGGER IF NOT EXISTS medicao_planilhas_sem_delete BEFORE DELETE ON medicao_planilhas
BEGIN
    SELECT RAISE(ABORT, 'Planilha/carta é evento: não se apaga');
END;

-- Assinatura no DocuSign: evento (nao e' estado), feito por fora; data e nome do envelope do e-mail de conclusao.
CREATE TABLE IF NOT EXISTS medicao_assinaturas (
    id INTEGER PRIMARY KEY,
    medicao_id INTEGER NOT NULL REFERENCES medicoes(id),
    envelope TEXT,
    assinado_em TEXT NOT NULL,
    origem TEXT NOT NULL DEFAULT 'manual' CHECK (origem IN ('manual')),
    usuario_id INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_medicao_assinaturas_medicao ON medicao_assinaturas (medicao_id, id);
CREATE TRIGGER IF NOT EXISTS medicao_assinaturas_sem_update BEFORE UPDATE ON medicao_assinaturas
BEGIN
    SELECT RAISE(ABORT, 'Assinatura é evento: não se altera (registre uma nova)');
END;
CREATE TRIGGER IF NOT EXISTS medicao_assinaturas_sem_delete BEFORE DELETE ON medicao_assinaturas
BEGIN
    SELECT RAISE(ABORT, 'Assinatura é evento: não se apaga');
END;

-- Boletim do orgao = evento de atesto (039), que continua append-only; ganha o meio, o numero no orgao (processo
-- ou SMO), o documento e a observacao. Atestos antigos ficam com tudo NULL.
ALTER TABLE medicao_atestos ADD COLUMN meio TEXT CHECK (meio IN ('smo','oficio','email','carimbo','ci','outro'));
ALTER TABLE medicao_atestos ADD COLUMN numero_orgao TEXT;
ALTER TABLE medicao_atestos ADD COLUMN arquivo TEXT;
ALTER TABLE medicao_atestos ADD COLUMN sha256 TEXT;
ALTER TABLE medicao_atestos ADD COLUMN observacao TEXT;

-- `envios.tipo` e' texto livre (019, sem CHECK): o tipo 'planilha' ja' e' aceito, nada a mudar.

COMMIT;
PRAGMA foreign_keys=ON;
