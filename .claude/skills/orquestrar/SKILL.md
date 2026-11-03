---
name: orquestrar
description: Rodada da orquestradora: escolhe issues abertas do GitHub, abre uma trabalhadora por issue em worktree, roda o revisor-adversarial e o gate Sol nas PRs, manda os achados de volta, liga o auto-merge quando as travas passam e resume ao Leo. Usar quando o Leo disser "rodada" (uma) ou "até acabar" (emenda rodadas até esvaziar a fila). Não faz deploy.
---

# Orquestrar uma rodada

A orquestradora é a sessão fixa do Leo nesta máquina, aberta na **pasta principal** do projeto, em `master`,
com o modelo Opus escolhido no app. Ela **não edita código**: escolhe, abre trabalhadoras, julga os gates,
liga o auto-merge e relata. Deploy continua sendo pedido do Leo (skill `deploy`).

Modelos: trabalhadora em `sonnet` (padrão do agente) ou `opus` quando a issue tem label `risco:*`;
`revisor-adversarial` em `opus` (fixo no agente); `listar-issues` em `haiku`; gate Sol no codex.

## Pré-condições (todas; se uma falhar, parar e dizer ao Leo qual)

1. Sessão na pasta principal (`git rev-parse --show-toplevel` sem `.claude\worktrees`), em `master`, sem
   mudança pendente em arquivo versionado (`git status --short` só com `??`).
2. `git fetch origin` e `git pull --ff-only`: `master` igual a `origin/master`.
3. Nenhuma issue aberta com label `parar` (o agente `listar-issues` avisa).
4. Teto de trabalhadoras ao mesmo tempo, pela máquina onde a orquestradora roda: **20 no Mac** (decidido pelo Leo em
   20/10/2026; não é a produção) e **10 no `<servidor>`** (decidido em 13/10/2026; é a produção e a CPU cai sob
   carga). No Windows vale 10.

## Rodada

1. **Listar.** Agent `listar-issues` (`subagent_type: listar-issues`). Guardar a tabela.
2. **Escolher** as primeiras da tabela, até o teto da máquina (pré-requisito 4). Antes de abrir, ler cada issue (`gh issue view <N>`); se o texto não
   diz o que o Leo quer ver na tela nem dá para deduzir dos documentos (`docs/`, `docs/backlog.md`,
   `cadastro/`), não abrir trabalhadora: comentar a pergunta na issue, pôr `decisao` e pegar a próxima.
   Se a leitura mostrar label `decisao`, `parar`, `precisa-do-leo` ou `sessao-manual` posto depois da
   listagem, pular a issue.
3. **Abrir as trabalhadoras**, todas na mesma mensagem (rodam em paralelo), com
   `subagent_type: trabalhadora`, `isolation: "worktree"`, `run_in_background: true`, e `model: "opus"` se a
   issue tem label `risco:*` (senão deixar o padrão, `sonnet`). Prompt: `Issue #N` e nada mais. Guardar o
   nome do agente para o passo 6. A orquestradora **não cria worktree** para a branch da PR: o da própria
   trabalhadora (que ela devolve na resposta) já é onde a branch está, e o da correção (passo 6) quem cria é a
   trabalhadora nova.
4. **Quando uma trabalhadora termina**, ler a resposta dela:
   - `PAROU`: a pergunta já está na issue com `decisao`. Registrar no resumo, remover o worktree (passo 10)
     e seguir.
   - `FALHOU`: registrar o motivo, pôr o label `precisa-do-leo` na issue, remover o worktree (passo 10) e
     seguir.
   - `PR aberta`: seguir para os gates. Se em `## Gates` o `/code-review` consta como "não rodou" (a skill
     pode não existir dentro de um subagente), a orquestradora roda `/code-review` com a branch como alvo
     (skill `code-review`, argumento = nome da branch) e trata os achados como os do revisor.
5. **Gates da orquestradora** (sempre, em toda PR):
   - **`revisor-adversarial`** (Agent, `subagent_type: revisor-adversarial`), prompt com o número da issue, o
     número da PR e o **caminho absoluto do worktree** que a trabalhadora devolveu. Ele lê os arquivos lá e
     roda `git -C <worktree> diff origin/master...HEAD`.
   - **Gate Sol**, só se a issue tem label `risco:*`: skill `gate-sol`, passando o caminho do worktree
     (a skill faz o `cd` dentro de um subshell, que não muda o diretório da sessão), pela ferramenta Bash.
   - **Codex sem cota** ("usage limit" na saída): não é veredito inválido e rodar de novo não adianta (a cota
     é da assinatura do Leo e volta no dia seguinte). Registrar "Gate Sol: sem cota em DD/MM" em `## Gates`.
     Se a rodada 1 do Sol já tinha coberto o diff inteiro da PR e a correção não mexeu em lógica de dinheiro
     ou de envio de forma grande, o `revisor-adversarial` cobre a correção (passo 6) e o gate segue como
     cumprido. Se nem a rodada 1 rodou, ou a correção mexeu nessa lógica de forma grande, a PR **não mergeia
     sozinha**: sem auto-merge, `precisa-do-leo` na issue dizendo que falta só o gate Sol, e no resumo ao Leo
     que o gate roda quando a cota voltar, a pedido dele (skill `gate-sol`; `listar-issues` não devolve
     issue com `precisa-do-leo`, então a rodada seguinte não a pega sozinha).
   - Veredito inválido (resposta vazia, erro, sem "OK" nem lista de achados, **ou "OK" sobre diff vazio**:
     conferir antes `git -C "<worktree>" diff --stat origin/master...HEAD` não vazio): rodar de novo uma vez;
     se continuar inválido, a PR não mergeia sozinha (ver Travas).
6. **Correção**, se houve achado Crítico ou Aviso: anotar o commit atual da PR (`<sha-antes>`, de
   `git -C "<worktree>" rev-parse HEAD` ou `gh pr view <M> --json headRefOid`) e a branch da PR no GitHub
   (`<N>-<nome-curto>`). O agente `trabalhadora` tem `isolation: worktree`: toda instância nasce no próprio
   worktree e a ferramenta recusa `git` em outro, então **não existe** trabalhadora "apontada" para o worktree
   da PR. O caminho é:
   - Mandar a lista inteira à mesma trabalhadora (`SendMessage` com o nome dela), pedindo para corrigir com
     teste ou refutar com `arquivo:linha`, e atualizar a PR. Ela ainda está no worktree dela e é a opção
     preferida. Só conta como "não respondeu" o `SendMessage` avisar que o agente já encerrou ou não existe; **sem
     prazo em minutos** (uma trabalhadora corrigindo com teste pode demorar, e duas corrigindo a mesma PR
     deixam o push da segunda recusado e o `<sha-antes>` sem bater).
   - Se ela não responder (nesse sentido), conferir antes `gh pr view <M> --json headRefOid`. Se já **não** é o
     `<sha-antes>`, a correção subiu enquanto se esperava: não abrir ninguém, rodar o `revisor-adversarial`
     sobre `<sha-antes>..<headRefOid>` no worktree de quem corrigiu (o da trabalhadora que não respondeu).
     Se ainda é o `<sha-antes>`, abrir uma `trabalhadora` **nova, isolada como sempre**
     (`isolation: "worktree"`, `run_in_background: true`), com o prompt "Issue #N, PR #M, branch no GitHub
     `<branch>`: corrija estes achados" e a lista. No worktree novo ela aponta a branch local dela para
     `origin/<branch>` (`git fetch origin` e `git checkout -B <nome da branch local lido com git branch --show-current> origin/<branch>`, o nome
     literal, sem substituição de comando e sem renomear a branch), corrige
     com teste e faz `git push origin HEAD:<branch>`, a mesma branch remota da PR. O worktree original da PR fica parado
     no commit antigo; não importa, o que vale é o remoto.
   - Quando a correção voltar, rodar o `revisor-adversarial` de novo **só sobre o diff novo**, passando no
     prompt o **caminho do worktree de quem corrigiu** (o da trabalhadora nova, se foi ela; ele tem o commit
     novo, o original não) e o intervalo `<sha-antes>..HEAD` (se a correção incluiu `git merge origin/master`, esse intervalo traria o
     código de outras PRs: nesse caso o revisor recebe `origin/master...HEAD`). O gate Sol não roda de novo sobre a
     correção, salvo se ela mexeu em lógica de dinheiro ou de envio de forma grande (regra da skill
     `gate-sol`); nesse caso, havendo cota, roda desse mesmo caminho só sobre o diff novo. **Duas rodadas no
     máximo**, a menos que o próprio Leo escolha a PR para mais uma correção (só se ele pedir; não é
     automático); a fonte é a decisão do Leo na sessão de 03/11/2026, registrada pela orquestradora na issue #356
     (orquestrar: correção isolada). Quando o revisor (e o Sol, se aplicável) dessa rodada extra volta sem
     Crítico/Aviso em aberto, a orquestradora tira o draft (`gh pr ready <M>`) e o label `precisa-do-leo` da
     issue, e só então vai ao passo 8 (a trava de lá exige `isDraft` = `false`). Se ainda sobrar Crítico ou Aviso não refutado, marcar a
     PR como draft (`gh pr ready --undo <M>`), pôr `precisa-do-leo` na issue, e seguir. **Mesma família de achado
     pela 2ª vez em pontos diferentes:** a orquestradora pede à trabalhadora a correção que fecha a família
     inteira, não o ponto (exemplos de 03/11/2026: leitura única do painel por transação; recorte do texto
     original inteiro).
7. **Preencher `## Gates` na PR** (`gh pr edit <M> --body-file ...`, mantendo o resto do corpo) com o resultado
   do revisor e do gate Sol, no formato da skill `abrir-pr`.
8. **Travas, todas, antes de ligar o auto-merge:**
   - `gh pr view <M> --json isDraft,mergeable -q '.isDraft,.mergeable'` = `false` e `MERGEABLE` (não é draft,
     sem conflito). `UNKNOWN` não é trava: o GitHub calcula depois de cada push; esperar 20 s e reconsultar,
     até 3 vezes. Só `CONFLICTING` segura;
   - revisor com veredito válido e sem Crítico/Aviso em aberto; gate Sol idem quando se aplica. O gate Sol
     roda quando o codex existe (máquina local). Na nuvem, onde não há codex, não é trava: registrar "gate
     Sol: não disponível na nuvem" em `## Gates`. Sem cota do codex vale o passo 5 (só mergeia sozinha se a
     rodada 1 do Sol já cobriu o diff inteiro e a correção não mexeu em dinheiro ou envio de forma grande);
   - **nenhum comentário nem review na PR** (`gh pr view <M> --json comments,reviews`): todo agente posta com
     a conta do Leo, então qualquer comentário na PR conta como dele. Por isso **a orquestradora e a
     trabalhadora nunca comentam na PR**: o que precisam registrar vai no corpo da PR (`gh pr edit`) ou na
     issue (`gh issue comment`);
   - a CI existe e está rodando ou verde (`gh pr checks <M>`): CI ausente é recusa, não aprovação.
   Não há trava por arquivo nem por label: redesenho, migração, `risco:*` e PR que toca `.github/`,
   `scripts/deploy.ps1` ou `.claude/` entram igual às outras (decisão do Leo de 16/10/2026).
   Passou em tudo: `gh pr merge <M> --auto --merge` e comentar na issue "PR #M com auto-merge ligado".
   **Na nuvem**, onde `gh pr merge --auto` (GraphQL) é bloqueado, o auto-merge se liga por
   `gh api -X PUT repos/lotufo-dev/nova-dashboard-lotufo/pulls/<M>/ccr/auto_merge`.
   O `master` tem fila de merge (ruleset, desde 15/10/2026): com a CI da PR verde, o GitHub põe a PR na fila,
   junta com o `master` atual e roda a CI de novo nessa mistura (evento `merge_group`) antes de mergear.
   Falhou em alguma: comentar na **issue** qual trava segurou, pôr `precisa-do-leo` na issue e seguir.
9. **Esperar a CI e a fila** das PRs com auto-merge: `gh pr checks <M> --watch` em segundo plano (Bash com
   `run_in_background: true`); a CI leva 20 a 30 min, e a fila roda a CI outra vez antes do merge. A PR só
   terminou quando `gh pr view <M> --json state` der `MERGED`. **Fila vermelha:** o GitHub tira a PR da fila e
   desliga o auto-merge sozinho; o log está em `gh run list --event merge_group --limit 5` (branch
   `gh-readonly-queue/master/pr-<M>-...`). Em geral é choque com outra PR que entrou antes: tratar como CI
   vermelha (abaixo), pedindo à trabalhadora `git merge origin/master` junto da correção. **Enquanto espera**, a cada 5 min reconsultar
   `gh pr view <M> --json comments,reviews`: apareceu comentário ou review, é o Leo; desarmar na hora
   (`gh pr merge <M> --disable-auto`), pôr `precisa-do-leo` na issue e seguir.
   **CI vermelha:** primeiro desarmar (`gh pr merge <M> --disable-auto`), senão a correção mergeia sem
   revisão quando a CI do commit novo ficar verde. Anotar o `<sha-antes>` (`gh pr view <M> --json headRefOid`) e pegar o log
   (`gh run list --branch <branch no GitHub> --limit 1 --json databaseId -q '.[0].databaseId'` e
   `gh run view <id> --log-failed`) e mandar à trabalhadora (uma rodada de correção, conta nas duas do passo
   6). Quando ela voltar: a conferência do passo 6 (revisor sobre `<sha-antes>..HEAD` no worktree de quem corrigiu, ou sobre `origin/master...HEAD` se a correção incluiu `git merge origin/master`, e Sol só se a correção mexeu de forma grande em dinheiro ou envio) e o passo 8 inteiro de novo antes de religar o auto-merge.
   Vermelha de novo, `precisa-do-leo`.
10. **Depois do merge** de cada PR (e no `PAROU`/`FALHOU` do passo 4): `git pull --ff-only` na pasta
    principal (com `cd` explícito para ela: o diretório do Bash da sessão persiste entre chamadas e pode ainda estar
    dentro de um worktree) e remover o worktree da trabalhadora (e o da trabalhadora de correção, se o passo 6 abriu uma nova), pelo PowerShell na pasta principal (o hook de remoção só
    roda quando o Claude remove sozinho). **Só remover caminho que contém `\.claude\worktrees\`**; a produção
    (`C:\DashboardLotufo\app`) também é worktree deste repositório e nunca entra aqui.
    `git worktree remove "<caminho>"` (se reclamar da junção, antes rode
    `cmd /c rmdir "<caminho>\frontend\node_modules"` e `cmd /c rmdir "<caminho>\backend\.venv"`, que apagam só o
    vínculo) e `git branch -d <branch local que cada uma devolveu>` (se recusar com a PR já `MERGED`, `-D` vale: o commit
    está no `master` pelo merge da PR; a remota o GitHub apaga no merge).
11. **Resumo ao Leo**, em português, uma linha por issue: número com o nome curto ("#231 (ofício no envio
    por fora)"; nunca o número sozinho, aqui nem nos comentários), o que mudou (do ponto de vista dele), estado
    (mergeada / auto-merge ligado, esperando CI / precisa-do-leo: motivo / decisao: pergunta). No fim: quantas
    issues elegíveis sobraram e se há algo com `precisa-do-leo`. Lembrar que o deploy é dele e que, para
    segurar uma PR com auto-merge ligado, ele comenta nela (a orquestradora desarma na próxima conferência)
    ou, para segurar na hora, converte em draft ou fecha.

"**Até acabar**": terminada a rodada (todas as PRs mergeadas ou paradas), `cd` explícito para a pasta principal, `git pull --ff-only` e voltar ao
passo 1, até a tabela do `listar-issues` vir vazia ou aparecer `PARAR`. Entre rodadas, nada de deploy.

## Quadro

O quadro "Fila da Dashboard" (projeto 1 da organização `lotufo-dev`) mostra a fila ao Leo em quatro colunas.
A orquestradora move o cartão da issue: **Em andamento** ao abrir a trabalhadora (passo 3); **Esperando o
Leo** sempre que pôr `decisao` ou `precisa-do-leo`; **Feito** depois do merge (passo 10). Issue sem cartão
entra antes de mover (`gh project item-add 1 --owner lotufo-dev --url <url da issue>`).

```bash
ITEM=$(gh project item-list 1 --owner lotufo-dev --limit 500 --format json -q ".items[] | select(.content.number==<N>) | .id")
gh project item-edit --id "$ITEM" --project-id PVT_kwDOFHPVk84Bnvvw --field-id PVTSSF_lADOFHPVk84BnvvwzhmS6zQ \
  --single-select-option-id <69f676e5 Em andamento | fc5944c9 Esperando o Leo | 5ea5a3c3 Feito>
```

## O que a orquestradora nunca faz

- Editar código, commitar ou fazer push de código próprio; o que vê de errado vira issue (`gh issue create`).
- Mergear à força, pular a CI ou mexer em PR que o Leo comentou.
- Deploy sem o Leo pedir. Mexer em `C:\DashboardLotufo` ou no banco padrão.
- Rodar a suíte inteira localmente ou passar do teto de trabalhadoras da máquina (20 no Mac, 10 no `<servidor>`).
- Reabrir uma issue com `precisa-do-leo` ou `decisao` antes de o Leo tirar o label.
