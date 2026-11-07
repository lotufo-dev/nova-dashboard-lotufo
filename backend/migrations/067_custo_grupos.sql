-- 067: cadastro do custo por obra (issue #489, decisao do Leo de 06/11/2026). A secao `custo:` do yaml do contrato
-- diz o projeto do Solum (`projeto_rm`), os grupos da planilha do orgao (cada um com prefixos de tarefa do RM e de
-- item da planilha, e o item-chave para o custo unitario), as naturezas fora do custo (`custo_nao_e_custo`, lista
-- JSON de prefixos) e a regra do custo sem tarefa (`custo_sem_tarefa`, hoje so' 'proporcional'). E' cadastro, nao
-- historico financeiro: o yaml e' a verdade, aplicado por `cadastro aplicar` com auditoria. Obra sem a secao fica
-- com tudo NULL e sem grupo. So' acrescenta.
ALTER TABLE contratos ADD COLUMN projeto_rm TEXT;
ALTER TABLE contratos ADD COLUMN custo_nao_e_custo TEXT;
ALTER TABLE contratos ADD COLUMN custo_sem_tarefa TEXT;

CREATE TABLE IF NOT EXISTS custo_grupos (
    id INTEGER PRIMARY KEY,
    contrato_id INTEGER NOT NULL REFERENCES contratos(id),
    ordem INTEGER NOT NULL,                 -- 1, 2, ... na ordem do yaml
    nome TEXT NOT NULL,                     -- como aparece na planilha do orgao e na tela
    tarefas TEXT NOT NULL,                  -- lista JSON de prefixos do codigo da tarefa do Solum
    itens_planilha TEXT NOT NULL,           -- lista JSON de prefixos dos itens da planilha do orgao
    item_chave_codigo TEXT,
    item_chave_unidade TEXT,
    UNIQUE (contrato_id, nome)
);
CREATE INDEX IF NOT EXISTS ix_custo_grupos_contrato ON custo_grupos (contrato_id, ordem);
