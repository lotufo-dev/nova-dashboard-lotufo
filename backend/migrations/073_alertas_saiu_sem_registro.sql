-- 073: o alerta de seguranca que SAIU sem registro fica marcado no banco (issue #588). So' acrescenta: uma coluna.
--
-- `envio_saiu_sem_registro_em`: o Graph aceitou o e-mail e o registro do envio falhou (EnvioNaoRegistrado puro).
-- Gravada numa transacao propria, antes de marcar a linha como saida, e de novo a cada rodada enquanto nao gravar
-- (app/alertas_seguranca.py). Com ela a linha de comando, que roda em outro processo, recusa "nao saiu" lendo so' o
-- banco, e a rodada termina a marcacao mesmo depois de o servidor reiniciar.
ALTER TABLE alertas_seguranca_envios ADD COLUMN envio_saiu_sem_registro_em TEXT;
