-- Issue #667: a resposta do orgao que traz o link de acompanhamento do SIGA cria o processo ligado a' medicao e fica
-- marcada como "protocolo do SIGA". `siga_processo_id` e' o processo que essa resposta trouxe; vazio = resposta
-- comum. O link e' procurado no corpo no momento da leitura; o corpo continua sem ser gravado. So' acrescenta.
ALTER TABLE medicao_respostas_orgao ADD COLUMN siga_processo_id INTEGER REFERENCES siga_processos(id);
