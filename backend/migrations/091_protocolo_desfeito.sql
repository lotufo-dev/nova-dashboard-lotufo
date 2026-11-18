-- 091 (docs/adr/0006, "Atos de correcao de cadastro"): protocolo da nota desfeito pela correcao de cadastro.
-- A carga do historico e a correcao gravaram protocolo de nota em medicao que os documentos mostram estar em analise
-- no orgao. O ato `devolver` (`correcao_medicoes`) leva a medicao ao estado provado e marca aqui o protocolo que nao
-- houve: `desfeita_em` (quando) e `motivo_desfazer` (o motivo e a fonte). A linha fica (nada financeiro se apaga) e
-- deixa de contar como protocolo da nota em toda leitura (`etapa='nota' AND desfeita_em IS NULL`).
-- So' acrescenta: protocolo existente nasce sem a marca, e nenhuma linha muda.
ALTER TABLE medicao_protocolos ADD COLUMN desfeita_em TEXT;
ALTER TABLE medicao_protocolos ADD COLUMN motivo_desfazer TEXT;
