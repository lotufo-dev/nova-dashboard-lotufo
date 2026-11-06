-- 063: o valor de cada medicao no espelho (issue #359). So' acrescenta.
-- O espelho grava as entradas (JSON) e as notas, mas nao o valor de cada medicao: o aviso "o aprovado mudou depois do
-- espelho" compara o aprovado vigente com este valor. Os espelhos gerados antes desta coluna ficam com NULL e o valor
-- sai das entradas gravadas pela regra da obra (espelhos.valores_vigentes).
ALTER TABLE espelho_medicoes ADD COLUMN valor_centavos INTEGER CHECK (valor_centavos IS NULL OR valor_centavos >= 0);
