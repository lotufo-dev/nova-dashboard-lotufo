# As regras vivas moram em regras, glossário e ADR; as specs são histórico

As specs de produto (`docs/superpowers/specs/`) foram a autoridade até 15/11/2026. Decisões posteriores do dono
já contradiziam a de 2026-09-21 em cerca de sessenta afirmações, e uma sessão que abrisse a spec lia regra morta
misturada com regra viva. Decidimos que a spec vira registro histórico e que a regra viva mora em três lugares:
`.claude/rules/` (regra por tema, que carrega sozinha quando a sessão mexe no arquivo), `GLOSSARY.md` (termos) e
`docs/adr/` (decisão com o motivo). O `CLAUDE.md` guarda só o que vale em qualquer arquivo.

## Opções consideradas

- Reescrever uma spec única e atual: melhor para ler de ponta a ponta, mas não carrega sozinha e envelhece de novo
  na primeira decisão que não for escrita de volta.
- Manter a spec e emendar: mais barato no dia, e quem lê precisa reconciliar o texto com as emendas.

## Consequências

- Uma frase só fica como regra se o código não a conta sozinho e se quebrá-la causa dano difícil de perceber.
  Regra que descreve o código (lista de estados, nome de migração, narração de implementação) sai.
- Cada regra mora em um lugar só. README e runbook dizem como rodar e operar e apontam para a regra.
- Comentários do código que citam "spec §N" continuam válidos como ponteiro para o histórico.
