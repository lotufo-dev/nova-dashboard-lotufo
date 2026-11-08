-- 073: "Aceitar a diferença" do boletim do orgao (issue #288, decisao do Leo de 08/11/2026). So' acrescenta (uma
-- tabela, um indice e dois gatilhos).
--
-- O aviso "aprovado abaixo do pedido" (spec 2026-10-20 §2.1) some quando a operacao ou a engenharia aceita a
-- diferenca, com justificativa. A aceitacao vale para o boletim vigente (`atesto_id`, o ultimo evento de
-- `medicao_atestos`): boletim novo ainda abaixo do pedido traz o aviso de volta. Evento: nao se altera nem se apaga.
-- O aprovado e o pedido do momento ficam congelados no evento, para a linha do tempo dizer a diferenca aceita; se o
-- pedido da medicao mudar depois (a prevista do fluxo antigo que recebe o valor do espelho), a aceitacao nao vale
-- para a diferenca nova, que se aceita de novo (por isso a unicidade e' do boletim com o pedido).
CREATE TABLE IF NOT EXISTS medicao_diferencas_aceitas (
    id INTEGER PRIMARY KEY,
    medicao_id INTEGER NOT NULL REFERENCES medicoes(id),
    atesto_id INTEGER NOT NULL REFERENCES medicao_atestos(id),
    aprovado_centavos INTEGER NOT NULL CHECK (typeof(aprovado_centavos) = 'integer' AND aprovado_centavos >= 0),
    pedido_centavos INTEGER NOT NULL CHECK (typeof(pedido_centavos) = 'integer' AND pedido_centavos >= 0),
    justificativa TEXT NOT NULL CHECK (trim(justificativa) <> ''),
    usuario_id INTEGER REFERENCES usuarios(id),
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (atesto_id, pedido_centavos)
);
CREATE INDEX IF NOT EXISTS ix_medicao_diferencas_aceitas_medicao ON medicao_diferencas_aceitas (medicao_id, id);
CREATE TRIGGER IF NOT EXISTS medicao_diferencas_aceitas_sem_update BEFORE UPDATE ON medicao_diferencas_aceitas
BEGIN
    SELECT RAISE(ABORT, 'Diferença aceita é evento: não se altera');
END;
CREATE TRIGGER IF NOT EXISTS medicao_diferencas_aceitas_sem_delete BEFORE DELETE ON medicao_diferencas_aceitas
BEGIN
    SELECT RAISE(ABORT, 'Diferença aceita é evento: não se apaga');
END;
