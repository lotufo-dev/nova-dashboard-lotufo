-- 090: centro de custo que a propria empresa usa, no RM dela, para um contrato de consorcio (docs/adr/0005).
-- `centro_custo_empresa_rm` do contrato no cadastro: o centro em que a empresa lanca a nota que emite pela cota dela
-- naquela obra. O contrato e' do consorcio (outra coligada), entao `centro_custo_rm` nao serve; com este campo o
-- centro da nota da empresa aponta a obra e o vinculo automatico vale dentro dela. NULL = nao declarado (o padrao):
-- a nota da empresa nao liga sozinha. So' acrescenta a coluna; nenhuma linha muda, e ela so' recebe valor por
-- `cadastro aplicar`.
ALTER TABLE contratos ADD COLUMN centro_custo_empresa_rm TEXT;
