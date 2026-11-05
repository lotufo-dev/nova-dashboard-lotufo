-- 060: de onde veio a data-base guardada no aditivo de reajuste (issue #410; revisor e gate Sol, rodada 2, PR #407).
-- So' acrescenta. 'declarada' (o `data_base` do cadastro), 'unica' (a data-base unica do contrato quando o aplicar a
-- gravou) ou 'pleito' (a do pleito ja' ligado ao aditivo aplicado antes da 058). So' a declarada trava; a inferida
-- cede a primeira declaracao, auditada. NULL nos existentes: conta como inferida, e o proximo `cadastro aplicar` que
-- declarar a mesma base grava 'declarada'.
ALTER TABLE aditivos ADD COLUMN data_base_origem TEXT;
