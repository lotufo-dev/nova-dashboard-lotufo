-- #603: linhas da consulta de custo puladas por mes ilegivel. Nao e' falha (o retrato foi trocado com as demais
-- linhas), por isso fica fora de custo_erro.
ALTER TABLE rm_sincronizacoes ADD COLUMN custo_aviso TEXT;
