-- 069: leitura da planilha selada tambem contra INSERT OR REPLACE (issue #502). So' acrescenta (quatro gatilhos).
--
-- Os gatilhos da 068 recusam UPDATE/DELETE e item alem de `itens`, mas um REPLACE que cai sobre linha que ja existe
-- apaga e regrava a linha sem disparar gatilho de DELETE (`recursive_triggers` fica desligado). Dois caminhos:
-- - nos itens: REPLACE numa ordem (ou id) ja gravada troca grupo e valores do item;
-- - na leitura: REPLACE no id da leitura (ou na mesma leitura do indice unico das lidas) regrava a leitura com outro
--   total e mais `itens`, e o item a mais passaria pelo gatilho da 068.
-- Estes recusam qualquer INSERT que caia sobre linha ja gravada. O BEFORE INSERT roda antes da resolucao do
-- conflito, e o RAISE(ABORT) vale qualquer que seja o OR da instrucao. Com o id omitido, NEW.id vale -1 no BEFORE
-- INSERT: a conferencia por id so' vale para id positivo, para um id negativo gravado nao travar a gravacao normal.
-- A gravacao normal (leitura nova, itens 1..N com ids novos, na mesma transacao) nao cai em nenhum deles.
CREATE TRIGGER IF NOT EXISTS medicao_grupos_sem_replace BEFORE INSERT ON medicao_grupos
WHEN (NEW.id > 0 AND EXISTS (SELECT 1 FROM medicao_grupos WHERE id = NEW.id))
  OR (NEW.situacao = 'lida' AND EXISTS (
        SELECT 1 FROM medicao_grupos
        WHERE situacao = 'lida' AND medicao_id = NEW.medicao_id AND sha256 = NEW.sha256
          AND COALESCE(planilha_id, 0) = COALESCE(NEW.planilha_id, 0) AND pedido_centavos = NEW.pedido_centavos
          AND COALESCE(cadastro_sha256, '') = COALESCE(NEW.cadastro_sha256, '')))
BEGIN
    SELECT RAISE(ABORT, 'Leitura da planilha é evento: não se altera (anexe a planilha de novo)');
END;
CREATE TRIGGER IF NOT EXISTS medicao_grupo_itens_sem_replace BEFORE INSERT ON medicao_grupo_itens
WHEN EXISTS (SELECT 1 FROM medicao_grupo_itens WHERE leitura_id = NEW.leitura_id AND ordem = NEW.ordem)
  OR (NEW.id > 0 AND EXISTS (SELECT 1 FROM medicao_grupo_itens WHERE id = NEW.id))
BEGIN
    SELECT RAISE(ABORT, 'Leitura da planilha é evento: os itens dela já foram gravados');
END;
-- No BEFORE INSERT nao da para distinguir o id omitido (-1) de um id -1 explicito, e o REPLACE num id <= 0 passaria
-- pela conferencia acima. No AFTER INSERT o id ja e' o definitivo: nenhuma linha nova tem id <= 0, entao a
-- conferencia por id positivo cobre todo dado gravado e o REPLACE num id <= 0 nao tem alvo. A gravacao normal
-- (id automatico: maior id + 1, a partir de 1) nunca cai aqui.
CREATE TRIGGER IF NOT EXISTS medicao_grupos_id_positivo AFTER INSERT ON medicao_grupos
WHEN NEW.id <= 0
BEGIN
    SELECT RAISE(ABORT, 'Leitura da planilha é evento: o número dela é dado pelo sistema');
END;
CREATE TRIGGER IF NOT EXISTS medicao_grupo_itens_id_positivo AFTER INSERT ON medicao_grupo_itens
WHEN NEW.id <= 0
BEGIN
    SELECT RAISE(ABORT, 'Leitura da planilha é evento: o número do item é dado pelo sistema');
END;
