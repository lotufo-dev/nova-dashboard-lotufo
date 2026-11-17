-- 088: tipos de movimento do RM que, so' numa obra, tambem sao cobranca ao orgao (docs/adr/0015).
-- `tipos_cobranca_extras_rm` do contrato no cadastro: lista JSON de tipos de movimento (como "2.2.03") alem da lista
-- geral de `app/cobranca_orgao.py`. NULL = nenhum (o padrao): vale so' a lista geral. So' acrescenta a coluna; nenhuma
-- linha muda, e ela so' recebe valor por `cadastro aplicar`.
ALTER TABLE contratos ADD COLUMN tipos_cobranca_extras_rm TEXT;
