-- Issue #663: categoria e complemento dos processos do SIGA. So' acrescenta.
-- `categoria`: uma das quatro, fechadas. "medicoes" e' automatica (todo processo ligado a medicao ou a protocolo de
-- medicao; o codigo a grava junto com o vinculo); as outras sao escolhidas por quem cadastra. `complemento`: o texto
-- que segue a categoria no nome montado pelo sistema ("Aditivo de prazo").
-- Processo existente: o ligado a medicao ou a protocolo fica em "medicoes"; os demais ficam no valor padrao, "outros".
-- Nenhuma outra coluna muda. Reexecutar nao desfaz a categoria que alguem ja' corrigiu (so' toca em quem esta' no
-- valor padrao e tem vinculo).
ALTER TABLE siga_processos ADD COLUMN categoria TEXT NOT NULL DEFAULT 'outros' CHECK (categoria IN ('medicoes','aditivos','indenizatorios','outros'));
ALTER TABLE siga_processos ADD COLUMN complemento TEXT;

UPDATE siga_processos SET categoria='medicoes'
 WHERE categoria='outros' AND (medicao_id IS NOT NULL OR protocolo_id IS NOT NULL);
