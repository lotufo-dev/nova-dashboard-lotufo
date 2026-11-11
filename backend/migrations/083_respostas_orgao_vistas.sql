-- Issue #654: o aviso flutuante "o orgao respondeu" aparece para quem ENVIOU (`envios.usuario_id`) ate' ela fechar o
-- aviso ou abrir a resposta. `vista_em` guarda quando isso aconteceu; vazio = ainda nao vista por quem enviou. Uma
-- coluna basta: cada resposta pertence a um envio e o envio tem uma pessoa so'. So' acrescenta.
ALTER TABLE medicao_respostas_orgao ADD COLUMN vista_em TEXT;
