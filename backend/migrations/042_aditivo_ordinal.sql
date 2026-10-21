-- 042: ordinal do termo no aditivo (issue #261, spec 2026-10-20 §3.3). So' acrescenta.
-- Com o cadastro parcial (so' o 14º TA carregado), a carta de prazo contava os carregados e escrevia "1º".
-- O ordinal sai do numero do termo; este campo, vindo do `ordinal` do YAML, cobre o numero sem sufixo.
ALTER TABLE aditivos ADD COLUMN ordinal INTEGER;
