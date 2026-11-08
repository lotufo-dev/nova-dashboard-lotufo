-- 078: medicao de reajuste aceita valor negativo (issue #589; decisao do Leo de 08/11/2026, item 3). Apostilamento ou
-- previsao negativos (indice deflacionario) viram pedido negativo na medicao de reajuste. So' o CHECK do protocolado e
-- do atestado muda, e so' para o tipo reajuste: execucao e projeto continuam recusando negativo no banco.
--
-- O CHECK so' muda reconstruindo `medicoes`, pela mesma receita da 042 (criar nova, copiar, apagar a antiga,
-- renomear), com foreign_keys OFF so' durante o script; as filhas referenciam `medicoes` pelo NOME e voltam a valer
-- quando a nova assume o nome. Mesmas colunas, na mesma ordem, e nenhuma linha muda de valor nem de estado.
-- `medicoes` nao tem indice nem gatilho proprio alem do UNIQUE (nada a recriar).
--
-- Reexecutavel: a `_nova` e' apagada antes de recriar (residuo de execucao interrompida nao impede a proxima).
-- Atomica: tudo depois do PRAGMA roda numa transacao so'; se o processo cair entre o DROP e o RENAME, nada fica
-- gravado e `medicoes` continua inteira.
--
-- `espelho_medicoes.valor_centavos` (065) tem CHECK >= 0: o valor com sinal entra numa coluna nova, sem CHECK,
-- gravada em todo espelho daqui em diante (a 065 continua com o valor quando ele nao e' negativo).
PRAGMA foreign_keys=OFF;
BEGIN;

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
    valor_protocolado_centavos INTEGER CHECK (valor_protocolado_centavos >= 0 OR tipo = 'reajuste'),
    valor_protocolado_origem TEXT CHECK (valor_protocolado_origem IN ('detectado','aceito','manual','espelho')),
    valor_atestado_centavos INTEGER CHECK (valor_atestado_centavos >= 0 OR tipo = 'reajuste'),
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

ALTER TABLE espelho_medicoes ADD COLUMN valor_com_sinal_centavos INTEGER
    CHECK (valor_com_sinal_centavos IS NULL OR typeof(valor_com_sinal_centavos) = 'integer');

COMMIT;
PRAGMA foreign_keys=ON;
