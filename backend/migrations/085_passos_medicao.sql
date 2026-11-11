-- 085: passos da medicao por obra (issue #660). `passos_medicao` do contrato no cadastro: lista JSON com os passos
-- que a obra tem (planilha, analise, espelhos, notas, envio_nota, pagamento). NULL = sem a chave (vale a familia do
-- orgao); '[]' = o fluxo da medicao nao e' feito pela empresa. So' acrescenta. Ver app/medicoes.py (passos_das_medicoes).
ALTER TABLE contratos ADD COLUMN passos_medicao TEXT;
