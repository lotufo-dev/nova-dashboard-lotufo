-- 046: natureza do aditivo de valor (issue #262, spec 2026-10-20 §3.2). So' acrescenta.
-- Na SES o reajuste entra por termo aditivo de valor: o vigente inclui o reajuste, mas o medido e' a precos
-- iniciais. `natureza` separa o aditivo de execucao (entra no saldo) do de reajuste (serie propria no painel).
-- Sem DEFAULT: NULL e' "nao classificado" e conta como execucao, que e' a conta que o saldo ja' fazia. O cadastro
-- aceita a primeira classificacao de um aditivo NULL e trava depois (instrumento aplicado nao se altera).
ALTER TABLE aditivos ADD COLUMN natureza TEXT CHECK (natureza IS NULL OR natureza IN ('execucao','reajuste'));
