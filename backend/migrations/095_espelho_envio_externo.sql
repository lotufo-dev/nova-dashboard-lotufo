-- 095: o envio do espelho ao faturamento feito por fora da dashboard (issue #798).
-- Quando a equipe manda o espelho por e-mail, fora do sistema, a pessoa registra "Já enviei por fora": a data do
-- envio, quem registrou, quando e, se quiser, uma observacao. O registro mora na propria versao do espelho, ao lado
-- de `envio_id` (o envio feito pela dashboard); a versao nova nasce sem ele e volta a pedir o envio.
--
-- `envio_externo_em` e' o dia informado (AAAA-MM-DD, sem hora) e vale como o dia do envio do espelho no vinculo da
-- nota pela saida do espelho (docs/adr/0005). NULL = sem registro por fora (o padrao).
--
-- So' acrescenta coluna; nenhuma linha muda.
ALTER TABLE espelhos ADD COLUMN envio_externo_em TEXT;
ALTER TABLE espelhos ADD COLUMN envio_externo_observacao TEXT;
ALTER TABLE espelhos ADD COLUMN envio_externo_por INTEGER REFERENCES usuarios(id);
ALTER TABLE espelhos ADD COLUMN envio_externo_registrado_em TEXT;
