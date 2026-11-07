-- 069: leitura da planilha selada tambem contra INSERT OR REPLACE nos itens (issue #502). So' acrescenta (um gatilho).
--
-- O gatilho `medicao_grupo_itens_selada` da 068 recusa ordem alem de `itens`, mas um REPLACE numa ordem (ou num id)
-- que ja existe passa por ele e, sem `recursive_triggers`, apaga e regrava o item sem disparar o gatilho de DELETE.
-- Este recusa qualquer INSERT que caia sobre item ja gravado: a mesma ordem da mesma leitura, ou o mesmo id. O
-- BEFORE INSERT roda antes da resolucao do conflito, e o RAISE(ABORT) vale qualquer que seja o OR da instrucao.
-- A gravacao normal (itens 1..N, ids novos, na transacao da leitura) nao cai em nenhum dos dois.
CREATE TRIGGER IF NOT EXISTS medicao_grupo_itens_sem_replace BEFORE INSERT ON medicao_grupo_itens
WHEN EXISTS (SELECT 1 FROM medicao_grupo_itens WHERE leitura_id = NEW.leitura_id AND ordem = NEW.ordem)
  OR EXISTS (SELECT 1 FROM medicao_grupo_itens WHERE id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'Leitura da planilha é evento: os itens dela já foram gravados');
END;
