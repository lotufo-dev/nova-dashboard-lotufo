-- 093 (docs/adr/0005, "Uma nota em mais de uma medicao"): vinculo de PARTE de uma nota.
-- Ha' nota que fatura mais de uma medicao (duas medicoes numa nota so'). `nf_alocacoes.valor_alocado_centavos` ja'
-- existia, mas todo vinculo era da nota inteira, e o valor gravado ali e' o da nota no dia do vinculo (o RM pode
-- corrigi-lo depois; as contas usam o valor atual da nota). `partilhada` = 1 marca o vinculo que vale por PARTE da
-- nota: nele `valor_alocado_centavos` e' o valor daquela medicao na nota, e toda conta usa esse valor. Os vinculos
-- partilhados vigentes de uma nota somam no maximo o valor dela (`sincronizacao_rm.alocar`). So' a correcao de
-- cadastro (`ligar_nf` com o valor de cada parte) cria vinculo partilhado.
-- So' acrescenta: vinculo existente nasce 0 (nota inteira), e nenhuma linha muda.
ALTER TABLE nf_alocacoes ADD COLUMN partilhada INTEGER NOT NULL DEFAULT 0 CHECK (partilhada IN (0, 1));
