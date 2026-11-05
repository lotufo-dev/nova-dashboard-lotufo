-- 060: os apostilamentos que o pacote montado cita (issue #278, revisor adversarial e gate Sol na PR #435).
--
-- Na MT-PAR e na Prefeitura o oficio de reajuste cita o termo de apostilamento que cobre a competencia de cada
-- medicao de reajuste. A montagem grava aqui (JSON) cada medicao de reajuste do pacote com o termo (chave e numero)
-- que a cobria naquela hora, ou nenhum; o envio compara com o de agora e, se o termo entrou, saiu ou foi corrigido
-- depois da montagem, fica bloqueado ate' montar de novo. NULL: montado antes desta migracao ou em orgao cujo oficio
-- nao cita o termo (nao compara).
-- So' acrescenta.
ALTER TABLE protocolos ADD COLUMN montado_apostilamentos TEXT;
