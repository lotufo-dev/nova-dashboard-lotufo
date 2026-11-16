-- 087: medicao, nota fiscal, envio e espelho nao se apagam (issue #706). So' acrescenta (quatro gatilhos); nenhuma
-- linha muda.
--
-- "Nada financeiro se apaga" ja' era garantido pelo banco em dezoito tabelas (039, 042, 043, 053, 062, 063, 066, 068,
-- 071, 072, 073, 075, 077, 080); faltavam as quatro principais. O codigo nao apaga linha em nenhuma delas: a medicao
-- e a nota mudam de estado, o espelho e' substituido por uma versao nova e o envio e' o registro do que saiu.
--
-- Dois limites do SQLite, para quem mexer nestas tabelas depois:
-- - DROP TABLE nao dispara gatilho de DELETE, entao a reconstrucao de tabela por migracao (docs/adr/0010) continua
--   possivel. So' que o gatilho sai junto com a tabela apagada: a migracao que reconstruir uma destas quatro recria o
--   gatilho dela depois do RENAME. O teste de test_db.py que tenta apagar no esquema final acusa o esquecimento.
-- - INSERT OR REPLACE que cai sobre linha ja' gravada apaga e regrava sem disparar gatilho de DELETE
--   (`recursive_triggers` fica desligado; a 069 fechou esse caminho para a leitura da planilha). O codigo nao usa
--   REPLACE nestas tabelas, e este gatilho nao o recusa.
CREATE TRIGGER IF NOT EXISTS medicoes_sem_delete BEFORE DELETE ON medicoes
BEGIN
    SELECT RAISE(ABORT, 'Medição não se apaga');
END;
CREATE TRIGGER IF NOT EXISTS notas_fiscais_sem_delete BEFORE DELETE ON notas_fiscais
BEGIN
    SELECT RAISE(ABORT, 'Nota fiscal não se apaga');
END;
CREATE TRIGGER IF NOT EXISTS envios_sem_delete BEFORE DELETE ON envios
BEGIN
    SELECT RAISE(ABORT, 'Envio não se apaga');
END;
CREATE TRIGGER IF NOT EXISTS espelhos_sem_delete BEFORE DELETE ON espelhos
BEGIN
    SELECT RAISE(ABORT, 'Espelho não se apaga');
END;
