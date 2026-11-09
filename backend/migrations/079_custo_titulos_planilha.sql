-- 079: titulos da planilha do orgao que formam cada grupo do cadastro de custo (issue #613). Na obra cuja planilha
-- nao tem nº de item (issue #612), o item cai no grupo pelo titulo lido, procurado nesta lista (sem acento, sem
-- diferenca de maiusculas e com espacos normalizados). Lista JSON de textos, como escritos no yaml; o grupo que ja'
-- existe nasce com a lista vazia. So' acrescenta.
ALTER TABLE custo_grupos ADD COLUMN titulos_planilha TEXT NOT NULL DEFAULT '[]';
