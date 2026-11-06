-- 064: pecas que vao dentro do oficio assinado, por contrato (issue #462, decisao do Leo de 05/11/2026). A regra e'
-- por peca no orgao (`orgaos.regras.pecas[].no_oficio`); `pecas_no_oficio` do contrato (lista JSON de tipos) a
-- substitui so' naquele contrato. NULL = segue o orgao; '[]' = nenhuma vai no oficio. Ver app/protocolo.py
-- (tipos_no_oficio). So' acrescenta.
ALTER TABLE contratos ADD COLUMN pecas_no_oficio TEXT;
