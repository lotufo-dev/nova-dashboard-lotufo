-- 038: a FRC assinada fica ligada a' FRC gerada que ela assina (issue #169, achado do gate Sol na PR #168).
--
-- A assinada (DocuSign, por fora) entra como documento `fatura` da medicao. Ate' aqui qualquer `fatura` anexada
-- deixava o envio pronto, mesmo a assinada de uma FRC ja' substituida (notas trocadas, FRC gerada de novo). Agora o
-- anexo guarda a linha de `frcs` vigente no momento em que foi anexado, e so' vale para o envio enquanto essa linha
-- for a vigente e nao estiver desatualizada. NULL: anexo de antes desta migracao, ou de consorcio sem FRC gerada
-- pela dashboard. So' acrescenta.
ALTER TABLE medicao_documentos ADD COLUMN frc_id INTEGER REFERENCES frcs(id);
