-- 056: versao de cronograma superada pelo cadastro (issue #395; levantamento 2026-10-20 §4, "Corrigir").
--
-- `contratos/<obra>.yaml` ganha `cronograma_superadas: [<numero da versao>]`: versoes ja gravadas sem linha no
-- cadastro (a carga de 04/09/2026, as manuais) que deixam de valer. A versao superada continua na tabela e na lista
-- de versoes (historico, auditoria), mas sai do previsto efetivo, da vigente e da curva comparativa
-- (app/cronograma.py). NULL = vale. So' acrescenta; nenhuma versao existente e' tocada.
ALTER TABLE cronograma_versoes ADD COLUMN superada_em TEXT;
