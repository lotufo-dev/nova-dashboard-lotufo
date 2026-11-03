-- 055: a data-base do apostilamento de reajuste fica guardada no termo (issue #271; gate Sol, rodada 3, PR #317).
-- So' acrescenta. O termo sem `data_base` nos dados vale para a base unica do contrato no momento em que e' aplicado;
-- quando o contrato ganha outra base (ou troca a unica), essa base se perdia e o ciclo apostilado reabria. O aplicar
-- grava a base de todo termo novo (app/cadastro_aplicar.py); aqui, os ja' aplicados recebem a base pela regra que
-- valia: `data_base` dos dados, senao a das previsoes que o termo gravou, senao a base unica de agora. Sem nenhuma,
-- fica NULL (o termo segue sem base, como antes).
ALTER TABLE instrumentos ADD COLUMN data_base_mes TEXT;

UPDATE instrumentos SET data_base_mes = COALESCE(
    NULLIF(json_extract(dados, '$.data_base'), ''),
    (SELECT p.data_base_mes FROM reajuste_previsoes p
      WHERE p.instrumento_id = instrumentos.id AND p.origem = 'apostilamento' ORDER BY p.id LIMIT 1),
    (SELECT MIN(b.mes) FROM contrato_datas_base b WHERE b.contrato_id = instrumentos.contrato_id
      HAVING COUNT(*) = 1))
 WHERE tipo = 'apostilamento_reajuste' AND data_base_mes IS NULL;
