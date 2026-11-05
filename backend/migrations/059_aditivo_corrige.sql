-- 059: o aditivo guarda a chave do instrumento que ele corrige (issue #409; gate Sol, rodada 2, PR #407). So' acrescenta.
-- Ate' aqui o `corrige` do aditivo ia so' para a `observacao` ("Corrige ta-01") e o aditivo corrigido seguia fechando
-- o ciclo de reajuste: o TA2 que corrige o TA1 de 2026 para 2025 deixava os dois ciclos fechados. O motor do reajuste
-- tira o aditivo corrigido (`reajuste.aditivo_de_reajuste`), como `_termo_vale` tira o apostilamento corrigido.
-- Os ja' aplicados recebem a chave da observacao: so' o `cadastro aplicar` grava aditivo com `chave_cadastro`, sempre
-- assinado (a tela nao edita aditivo assinado), e a observacao dele e' "Corrige <chave>" ou nada. O agregado da carga
-- do legado (`carga-legado`, migracao 018) nao veio do aplicar e fica de fora.
ALTER TABLE aditivos ADD COLUMN corrige_chave TEXT;

UPDATE aditivos SET corrige_chave = substr(observacao, 9)
 WHERE corrige_chave IS NULL AND chave_cadastro IS NOT NULL AND chave_cadastro <> 'carga-legado'
   AND substr(observacao, 1, 8) = 'Corrige ' AND length(observacao) > 8;
