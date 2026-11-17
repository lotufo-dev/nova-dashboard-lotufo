# A sessão não para para pedir confirmação: sem `ask` e sem autorização em chat

Em 17/11/2026 o dono reuniu 46 pedidos de "Permitir uma vez" do agente, em dois projetos dele, e pediu para acabar
com eles. A causa foi medida nas transcrições das sessões: elas rodam em modo automático, e todo pedido vinha de
uma regra `permissions.ask`. Basta um trecho de um comando composto casar com a regra para a sessão parar, e
nenhuma regra `allow` passa por cima de uma `ask`. Neste projeto, 30 pedidos vinham de regras para `ssh` e `scp`
à máquina da produção (`<vm>` no runbook), que ficavam na configuração local da máquina de desenvolvimento, fora
do repositório, e 2 vinham de `git checkout -- *`, no `.claude/settings.json` versionado.

Depois de ver, item a item, o que cada trava protegia, o dono decidiu tirar:

1. **As regras `ask`** do `.claude/settings.json`: as 20 que pediam confirmação antes de descartar alteração não
   commitada (`git checkout -- <arquivo>`, `git checkout .`, `git checkout -f`, `git switch -f`,
   `git switch --discard-changes`) e antes de mover ou apagar branch à força (`git branch -f`,
   `git branch --delete --force`), em `Bash` e em `PowerShell`.
2. **A autorização do dono em chat** antes de gravar dado na produção e antes de ligar o merge de uma PR.

**A lista `deny` fica.** São as 10 regras que recusam `git push` com `--force`, `-f` ou `+ref`. Ela nunca gerou
pedido: recusa. O dono chegou a decidir tirá-la junto e, no mesmo dia, depois de ver o parecer de uma revisão
independente, decidiu mantê-la.

No mesmo dia, fora do repositório, as regras `ask` de `ssh` e `scp` da configuração local deram lugar a regras
`allow` para a máquina da produção. Não é mudança deste repositório, mas a consequência dela está abaixo, porque
é a maior.

A fila de merge do GitHub na `master` entrou na mesma conversa e ficou de fora: continua como está, pendente de
decisão própria do dono.

## Consequências

- **O que saiu não passa a ser avaliado caso a caso: fica pré-aprovado.** Pela documentação do Claude Code lida em
  17/11/2026, no modo automático o comando que casa com uma regra `allow` roda direto, sem passar pelo
  classificador. O `settings.json` mantém em `allow` `git checkout *`, `git switch *`, `git branch *`,
  `git push *`, `gh pr merge *` e `gh api *`, e a configuração local, `ssh` e `scp` para a máquina da produção.
  Isso não foi testado nas sessões; se o classificador ainda barrar algum desses comandos, a sessão relata o
  bloqueio e não procura outro caminho para o mesmo efeito.
- **Comando remoto na produção roda sem pedido.** Não só a gravação pelo rito: parar o serviço, rodar o deploy,
  apagar ou restaurar o banco, qualquer comando por `ssh`. "Deploy só a pedido do dono" e o rito de gravação
  passam a ser regra escrita, sem trava técnica por trás.
- **Force push continua recusado pela configuração do agente.** A `deny` vale em qualquer modo e passa na frente
  do `allow`. Ela casa pelo texto do comando: pega `--force` (e `--force-with-lease`), `-f` e `+ref` como
  palavra separada num comando que começa com `git push`. Não pega toda forma de forçar: `-f` junto de outra
  letra (`-fu`), `git -C <pasta> push --force` e `git push --mirror` passam. Apagar a branch remota e publicar
  de novo também passa. Na `master` há a segunda barreira, do GitHub (o ruleset
  `master protegida` proíbe push sem avanço rápido e apagar a branch); a sessão tem como editar esse ruleset,
  porque `gh api *` está em `allow` e a conta do `gh` administra o repositório. Já era assim antes, e nenhuma
  regra autoriza a sessão a mexer nele.
- **Alteração não commitada pode ser descartada sem pergunta.** O git não guarda o que nunca foi commitado: um
  `git checkout -- <arquivo>` errado apaga o trabalho em andamento naquele arquivo e não há como desfazer.
- **Branch pode ser movida ou apagada à força sem pergunta.** O git recusa fazer isso com a branch em uso em outro
  worktree; fora disso, o commit que só existia nela fica sem nome. Isso é local: a branch publicada não é
  reescrita por force push. Apagar a remota e publicar de novo continua possível fora da `master`.
- **Gravação de dado na produção deixa de esperar o dono.** Vale para os comandos do `app.cli` que gravam dado e
  têm `--ensaio` (hoje: carga e correção de medições, `cadastro aplicar`, `legado remapear`,
  `documentos importar`, `medicoes planilhas` e `conciliacao`). Conta de acesso e gravação no RM não fazem parte
  desta decisão: continuam só com a autorização do dono na hora. Fica o rito do `docs/runbook.md`, seção
  "Gravação de dado na produção": ensaio com o relatório lido, backup do banco antes (no `cadastro aplicar`
  pedido junto de um deploy, só o snapshot horário), conferência depois e o relato do que foi gravado. Um dado
  errado que passar pelo ensaio entra na produção, que a equipe usa, antes de o dono ver.
- **Desfazer uma gravação errada custa.** A correção de cadastro conserta o dado daqui para a frente. Restaurar o
  backup para a produção e apaga o que a equipe gravou depois dele. E o que já saiu para fora não volta:
  `cadastro aplicar` muda destinatário de e-mail automático e regra de espelho, e um erro ali vira e-mail ou
  documento errado enviado.
- **O merge deixa de esperar o dono, inclusive em dinheiro, envio e banco.** A sessão liga o merge quando a
  conferência do corpo da PR está fechada e a CI está verde. A CI confere que o item da segunda revisão foi
  preenchido, não quem revisou, e quem preenche é a sessão que abriu a PR. Não sobra ponto humano antes da
  `master`. O deploy pedido pelo dono passa a ser o único controle dele, e leva junto todos os merges que ele não
  viu.
- **Cada gravação deixa um backup que ninguém apaga.** O `dashboard-PRE-GRAVACAO-*.db` não entra na rotação do
  backup; a limpeza do disco da produção é à mão.
- **O que não muda.** A lista `deny` de force push. Deploy continua só a pedido do dono (skill `deploy`). A fila
  de merge continua no caminho de toda PR para a `master`. Mudança em dinheiro, envio ou banco continua exigindo o
  item da segunda revisão no corpo da PR. PR que altera a verificação de vazamento, a lista de exceções ou os
  hooks continua exigindo merge do dono, porque a CI falha nela. A `master` continua só por PR, com `backend`,
  `frontend` e `vazamento` verdes. O hook que barra instalação dentro de worktree fica.
- Um teste (`test_travas_repositorio.py`) falha se a lista `ask` reaparecer no `settings.json` ou se uma das dez
  regras de force push sair da `deny`. Mudar qualquer das duas é decisão para um ADR novo.
