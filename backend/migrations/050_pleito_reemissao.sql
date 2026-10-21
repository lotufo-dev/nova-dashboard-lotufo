-- 050: reiteracao e reemissao do pleito de reajuste (issue #277; spec 2026-10-20-motores-medicao-apostilamento,
-- secao 2.2, E-mail). So' acrescenta. O pleito que aponta outro em `reemite_pleito_id` (migracao 043) diz aqui
-- o que ele e': 'reiteracao' (familia B: cobra o apostilamento, sem cronograma novo; MT-PAR e Prefeitura) ou
-- 'cronograma' (reemissao do cronograma apos aditivo: familia A, com previsao nova). Linha antiga com
-- `reemite_pleito_id` e sem `reemissao` conta como 'cronograma' (app/reajuste.py).
ALTER TABLE pleitos ADD COLUMN reemissao TEXT CHECK (reemissao IS NULL OR reemissao IN ('reiteracao','cronograma'));
