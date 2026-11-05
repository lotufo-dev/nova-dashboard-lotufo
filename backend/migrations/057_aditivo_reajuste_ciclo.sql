-- 057: o aditivo de valor de natureza reajuste (SES) guarda a data-base e o ciclo que atende (issue #390; revisor e
-- gate Sol, rodada 2, PR #407). So' acrescenta. O aditivo nao tem `dados`: sem estas colunas, o `ciclo`/`data_base`
-- declarados no cadastro nao chegavam ao motor do reajuste, que voltava a ler o ciclo pela data da assinatura.
-- `data_base_mes`: a declarada, senao a base unica do contrato quando o aplicar a grava (como a 055 faz no
-- apostilamento). `ciclo_reajuste`: so' o declarado; sem ele, o ciclo e' o do ultimo aniversario ate' a assinatura.
-- NULL nos existentes: o proximo `cadastro aplicar` preenche (primeira classificacao, auditada) e trava depois.
ALTER TABLE aditivos ADD COLUMN data_base_mes TEXT;
ALTER TABLE aditivos ADD COLUMN ciclo_reajuste INTEGER;
