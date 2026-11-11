-- Issue #638: nota que continua ativa no RM mas a dashboard nao conta mais (cancelada na prefeitura e substituida,
-- por exemplo). `desconsiderada_em` e' a marca, gravada por `cadastro corrigir-medicoes` (operacao
-- `desconsiderar_nf`) e limpa por `reconsiderar_nf`; o motivo, a fonte e quem aplicou ficam na auditoria.
-- Enquanto a marca existe, `situacao` fica 'cancelada' (a sincronizacao com o RM nao a devolve a 'ativa'); o que o RM
-- diz da nota continua em `status_rm`. So' acrescenta: nota existente nasce sem a marca.
ALTER TABLE notas_fiscais ADD COLUMN desconsiderada_em TEXT;
