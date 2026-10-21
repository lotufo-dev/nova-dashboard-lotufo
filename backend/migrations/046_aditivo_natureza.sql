-- 046: natureza do aditivo de valor (issue #262, spec 2026-10-20 §3.2). So' acrescenta.
-- Na SES o reajuste entra por termo aditivo de valor: o vigente inclui o reajuste, mas o medido e' a precos
-- iniciais. `natureza` separa o aditivo de execucao (entra no saldo) do de reajuste (serie propria no painel).
-- Todo aditivo gravado antes desta migracao e' de execucao, que e' a conta que o saldo ja' fazia.
ALTER TABLE aditivos ADD COLUMN natureza TEXT NOT NULL DEFAULT 'execucao' CHECK (natureza IN ('execucao','reajuste'));
