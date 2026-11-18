-- 092 (docs/adr/0006, "Titulo baixado no RM nao tem falta"): residuo de nota ja' paga, encerrado pela correcao de
-- cadastro. O titulo pago em parte no RM com um resto pequeno que nunca sera' baixado aparecia como divida no a
-- receber. O ato `encerrar_residuo_nf` (`correcao_medicoes`) grava aqui quanto do que falta nos titulos da nota foi
-- dado por encerrado (`residuo_encerrado_centavos`) e quando (`residuo_encerrado_em`); a conta do que falta
-- (`sincronizacao_rm._falta_por_titulo`) abate esse valor. Nada se apaga: os titulos e as baixas ficam como o RM os
-- deu, e o motivo e a fonte ficam na auditoria. `reabrir_residuo_nf` zera a marca.
-- So' acrescenta: nota existente nasce sem residuo encerrado, e nenhuma linha muda.
ALTER TABLE notas_fiscais ADD COLUMN residuo_encerrado_centavos INTEGER;
ALTER TABLE notas_fiscais ADD COLUMN residuo_encerrado_em TEXT;
