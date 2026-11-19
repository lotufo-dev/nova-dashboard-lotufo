-- 096: as notas que entraram no pacote montado (issue #873, docs/adr/0017).
--
-- Nos orgaos em que as notas vao DENTRO do PDF do pacote (carta + notas), o pacote guarda aqui os ids (JSON, de
-- medicao_documentos) dos PDFs de nota que levou. Quando a lista de notas que vao ao orgao muda depois da montagem
-- (nota trocada pela consorciada, nota anexada depois), o envio fica bloqueado ate' montar de novo: sem isso o
-- pacote antigo saia com a nota antiga dentro e com o numero dela na carta. Como a 041 faz com a FRC assinada.
-- NULL: montado antes desta migracao (nao se sabe o que levou; so' pede montar de novo onde alguma nota da medicao
-- ja' nao vai ao orgao). So' acrescenta.
ALTER TABLE protocolos ADD COLUMN montado_notas TEXT;
