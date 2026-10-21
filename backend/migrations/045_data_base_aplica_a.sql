-- 045: a data-base diz a que parte do contrato se aplica (issue #257, spec 2026-10-20 §2.4 e D7).
-- Texto livre vindo do cadastro ("itens SICRO", "itens SINAPI"); vazio quando o contrato tem uma base so'.
-- So' acrescenta.
ALTER TABLE contrato_datas_base ADD COLUMN aplica_a TEXT NOT NULL DEFAULT '';
