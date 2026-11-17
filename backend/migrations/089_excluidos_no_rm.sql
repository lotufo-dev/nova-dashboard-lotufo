-- 089 (issue #755, docs/adr/0006): nota e titulo que o RM deixou de devolver. O faturamento exclui o titulo e o refaz
-- (o movimento continua e ganha outro lancamento) ou refaz o movimento inteiro (outro idmov, mesmo numero); o antigo
-- some das consultas sem ser cancelado. `excluida_rm_em` e' a marca, gravada e limpa so' pela sincronizacao com o RM
-- (`sincronizacao_rm._marcar_excluidos`): com ela a nota e o titulo saem de toda soma, e a linha continua no banco
-- (nada financeiro se apaga). Voltando a vir do RM, a marca e' limpa. A nota marcada fica com `situacao`
-- 'cancelada', como a desconsiderada da 081; o que o RM dizia dela continua em `status_rm`.
-- So' acrescenta: nota e titulo existentes nascem sem a marca, e nenhuma linha muda.
ALTER TABLE notas_fiscais ADD COLUMN excluida_rm_em TEXT;
ALTER TABLE baixas ADD COLUMN excluida_rm_em TEXT;
