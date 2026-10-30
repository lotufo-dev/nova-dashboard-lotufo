-- 054: etapa do registro de protocolo da medicao (issue #283). So' acrescenta.
-- O nº do SIGA que o orgao devolve depois do envio da planilha/carta (spec 2026-10-20 §2.1, passo 2) mora em
-- `medicao_protocolos`, ao lado do protocolo da nota. A coluna separa os dois: 'planilha' e' o da planilha/carta
-- (so' identifica o processo no SIGA) e 'nota' e' o protocolo da nota, o unico que conta como "data do protocolo"
-- nos paineis, na conciliacao e na diretoria. Toda linha que ja' existe e' de nota (o padrao).
ALTER TABLE medicao_protocolos ADD COLUMN etapa TEXT NOT NULL DEFAULT 'nota' CHECK (etapa IN ('planilha','nota'));

-- uma linha da planilha/carta por medicao: a correcao do numero e' na mesma linha, com o antes na auditoria
CREATE UNIQUE INDEX IF NOT EXISTS ux_medicao_protocolos_planilha ON medicao_protocolos (medicao_id)
    WHERE etapa = 'planilha';
