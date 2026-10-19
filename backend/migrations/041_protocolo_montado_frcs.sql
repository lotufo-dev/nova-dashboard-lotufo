-- 041: as FRC assinadas que entraram no pacote montado (issue #169, revisor adversarial na rodada 3 da PR #179).
--
-- Nos orgaos em que as notas vao DENTRO do PDF do pacote (carta + notas), o pacote montado com a assinada de uma
-- FRC substituida nao pode sair depois que outra assinada (a da FRC vigente) for anexada: o pacote guarda aqui os
-- ids (JSON, de medicao_documentos) das assinadas que levou, e o envio fica bloqueado ate' montar de novo quando a
-- assinada que vale nao e' a do pacote. NULL: montado antes desta migracao (conta como pacote sem assinada).
-- So' acrescenta.
ALTER TABLE protocolos ADD COLUMN montado_frcs TEXT;
