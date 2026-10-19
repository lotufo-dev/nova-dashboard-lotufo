# Fluxo de trabalho "gerente, não prompter" — diagnóstico e plano (11/10/2026)

> **Nota de 12/10/2026:** o fluxo abaixo foi simplificado pelo Leo. Ficou o que foi reconstruído (regras do
> produto, `.claude/rules`, hooks de lint, permissões, proteção da `master`, modelos de issue e PR, skills,
> issues no GitHub); saíram a sessão orquestradora obrigatória, o label `pronta`, os papéis por modelo, os
> vários revisores em toda PR e o hook que rodava a suíte inteira antes de `gh pr create`. **A regra vigente é a
> seção "Como o trabalho anda" do `CLAUDE.md`.** O resto desta página é histórico do diagnóstico e do plano.
>
> **Nota de 13/10/2026:** a orquestradora voltou, depois de pesquisa do que a comunidade faz
> (agent-loop, claude_coding_pipeline, claude-issue-loop, continuous-claude; nenhum automatiza o deploy).
> Desenho vigente, na skill `orquestrar` e na seção "Como o trabalho anda" do `CLAUDE.md`: sessão fixa em
> Opus escolhe até 2 issues por rodada, abre uma trabalhadora por issue (agente `trabalhadora`, Sonnet; Opus
> com `risco:*`), roda o `revisor-adversarial` (Opus) em toda PR e o gate Sol nas de risco, e liga o
> auto-merge quando as travas passam (CI verde, sem conflito, sem comentário do Leo, sem tocar `.github/`,
> `scripts/deploy.ps1`, `.claude/` ou `backend/migrations/`). Labels novos: `parar` e `precisa-do-leo`.
> Deploy continua manual. Modelos fixados nos arquivos dos agentes, não na memória pessoal.
>
> **Revisto em 16/10/2026:** o Leo liberou o auto-merge em toda PR aprovada (CI verde, sem conflito,
> `revisor-adversarial` sem Crítico/Aviso, sem comentário do Leo pedindo para segurar), inclusive redesenho,
> migração, `risco:*` e PR que toca `.github/`, `scripts/deploy.ps1` ou `.claude/`. A lista de arquivos
> protegidos acima vale como histórico. O gate Sol roda onde há codex; na nuvem não é trava. Deploy segue só
> pela skill `deploy`, a pedido do Leo. As permissões de escrita no GitHub (`gh api`, `gh pr close`,
> `gh issue delete`) deixaram de pedir confirmação.

Pedido do Leo: trabalhar neste projeto como os "power users" do r/ClaudeAI descrevem
(sessões em paralelo com worktrees, toda tarefa em branch/PR, plano antes do código,
CLAUDE.md como memória, hooks que corrigem sozinhos, revisão adversarial), de modo que o
gargalo passe a ser o tempo de revisão dele, não o tempo do Claude.

Pipeline de referência (comentário mais votado):
`issues → orquestrador → subagentes (validar, perguntar, implementar) → PR → gates → fila de merge → produção`

---

## 1. Diagnóstico: o que já existe e o que falta

Levantado hoje no repositório, no `.claude/` do projeto, no `~/.claude/` e no GitHub.

| Item dos prints | Situação hoje | O que falta |
|---|---|---|
| **Paralelismo (worktrees, várias sessões)** | Trabalho em série numa sessão só. O único worktree extra é o de produção (`C:\DashboardLotufo\app`), que é outra coisa. | Sessões em worktree pelo app (já suportado, pasta `.claude/worktrees`), reaproveitar `node_modules` (183 MB) e `.venv` (131 MB) em cada worktree, limite de sessões por causa da máquina (ver §3). |
| **Git-flow (branch por tarefa, PR, merge revisado)** | Branch por bloco e merge só com OK do Leo: isso já é feito há 2 meses (452 commits em 30 dias, 30 merges). Mas os merges são locais, sem PR (1 PR em toda a história), `master` sem proteção, 46 branches antigas soltas, CI roda depois do push (não barra nada) e leva 20 a 28 min. | PR para toda branch, CI como condição de merge, auto-merge, limpeza de branches, CI mais rápida. |
| **Plano antes do código** | Existe o hábito: 10 planos em `docs/superpowers/plans/`, 3 specs. Faltam critérios de aceite e testes definidos antes de codar; o modo Plan do app não é usado; plano não vira tarefa rastreável. | Formato padrão de tarefa (issue) com critérios de aceite, sessão orquestradora em modo Plan. |
| **Memória (CLAUDE.md)** | **Este é o buraco mais grave.** `CLAUDE.md`, `README.md`, `PRODUCT.md`, `DESIGN.md` e `NAVEGACAO.md` do projeto foram apagados em 06/10 (commit 684f0dc), junto com os 2 agentes e o comando de UI. Hoje uma sessão nova neste repositório não sabe: regra do banco de produção, "sem custo de API", dinheiro em centavos, cadastro em YAML, commits em português, como rodar os testes. Essas regras só sobrevivem na memória automática pessoal (52 arquivos, fora do git), misturadas com diário de status e com três versões contraditórias do fluxo (02/09 "sem subagente", 04/09 "Fable orquestra", 08/10 "modo Fable"). | Recriar `CLAUDE.md` do projeto (curto), `.claude/rules/` por tema, `README.md`; mover status para `docs/` e limpar a memória pessoal. |
| **Hooks (lint/format automáticos)** | Nenhum hook. Nenhum formatador instalado (sem ruff, black ou prettier); `oxlint` só roda na CI. `.claude/settings.json` do projeto tem só o plugin do codex. Sem lista de permissões: cada sessão pára para pedir autorização, o que mata o paralelismo. | Instalar `ruff`; hooks PostToolUse (formatar/lintar o arquivo editado), PreToolUse (suíte antes de abrir PR), WorktreeCreate (preparar o worktree); lista de permissões. |
| **Não confie, verifique** | Existe e funciona: gate Sol (codex `gpt-5.6-sol`), crítico Fable, testes de quebra de 10/10, 932 testes no backend e 111 no frontend. Mas nada disso está codificado: `.claude/agents` está vazio, o Leo precisa lembrar de pedir, e a regra de quando revisar morava no CLAUDE.md apagado. `/code-review` embutido nunca usado. | Agente revisor adversarial, skill do gate Sol, regra escrita de quando cada gate é obrigatório, `/code-review` na PR. |

Mapeando no pipeline do comentário:

| Etapa | Hoje | Alvo |
|---|---|---|
| issues | `docs/backlog.md` (texto corrido, 1 linha por item) e memória | GitHub Issues (uma por tarefa, com critérios de aceite); `backlog.md` vira só decisões e dívidas |
| orquestrador | Leo + a sessão Fable, informal | Sessão orquestradora fixa (Fable, modo Plan, em `master`) |
| subagentes | subagentes só quando lembrado | Sessões trabalhadoras em worktree (Opus) + agente revisor (Fable) + gate Sol (codex) |
| PR | merge local, sem PR | PR pelo app, com resumo em português e "como testar" |
| gates | CI depois do fato; revisão manual | CI obrigatória para mergear + `/code-review` + revisor adversarial + gate Sol nos temas de risco |
| fila de merge | não existe | Não precisa (projeto de uma pessoa). Basta "PR só mergeia com CI verde" + auto-merge. **Revisto em 15/10/2026:** ligada no ruleset (repositório movido para a organização `lotufo-dev`, a fila não existe em conta pessoal), para várias trabalhadoras em paralelo não quebrarem o `master` juntas; o `ci.yml` roda também em `merge_group` |
| produção | `deploy.ps1` manual no `<servidor>`, worktree pinado, rollback automático, watchdog | Mantém. Vira uma skill `deploy` para rodar o runbook sem erro |

Conclusão: **uns 40% já estão prontos** (git-flow na prática, CI, testes, gates humanos, deploy
seguro). O que falta é (1) devolver a memória ao repositório, (2) automatizar o que hoje depende
de lembrar, (3) trocar o merge local por PR com condição, (4) ligar as sessões em worktree.

---

## 2. Suas regras atuais: o que ajuda e o que atrapalha

### `~/.claude/CLAUDE.md` (global)

- **"Se o pedido for ambíguo, faça uma pergunta antes de qualquer coisa."** Ótimo quando você está
  na frente da tela. Numa sessão trabalhadora rodando sozinha em worktree, isso trava: ela pára
  e espera. Solução: manter a regra global, e a regra do projeto dizer que **tarefa vinda de issue
  com critérios de aceite não pergunta**: decide, registra a suposição no PR, e a dúvida vira
  comentário para você. A pergunta acontece antes, na sessão orquestradora, quando a issue é escrita.
- **"Crie testes permanentes só quando eu pedir ou quando o projeto já mantém testes desse tipo."**
  Este projeto mantém 1.043 testes, então a segunda metade já vale. Mas conflita com "defina os testes
  antes de escrever uma linha". O CLAUDE.md do projeto deve dizer explicitamente: **toda mudança de
  comportamento sai com teste**; o critério de aceite da issue é o teste.
- **"Simplicidade", "mudanças cirúrgicas", "antes de começar diga em uma linha"**: mantêm, ajudam.
- **"Pense antes de codar / exponha suposições"**: mantém; vira o conteúdo da seção "Suposições" do PR.

### Memória automática (52 arquivos)

- Três regras de fluxo contraditórias e empilhadas (02/09, 04/09, 08/10). A de 02/09 diz
  "implementar direto, sem subagente"; a de 04/09 diz "fluxo alto de subagentes cortado". As duas
  contradizem "vá em paralelo". Proposta: **uma regra só, no repositório** (`docs/fluxo-de-trabalho.md`
  + `CLAUDE.md`), e a memória só aponta para ela.
- "NUNCA Sonnet/Haiku; Opus para mecânico; Fable para orquestrar e revisar": **mantém**, já é o
  desenho certo (Fable gerencia e critica, Opus executa).
- Vários arquivos são diário de status (o que entrou em produção, hash de commit). Isso pertence ao
  `docs/backlog.md` e ao git, não à memória. Sugestão: mover e apagar.

### `~/.claude/settings.json`

- `model: opus[1m]`, `effortLevel: high`: bom para as sessões trabalhadoras.
- Sem `permissions.allow` útil (a lista em `settings.local.json` é de comandos antigos soltos).

### `.claude/settings.json` do projeto

- Só `enabledPlugins: codex`. Sem hooks, sem permissões, sem modo padrão.
- 13 skills de design (taste-skill) instaladas, nenhuma skill de fluxo.

---

## 3. Restrições reais desta máquina (o que a Reddit não sabe)

1. **O `<servidor>` é o servidor de produção da dashboard e o servidor do TOTVS RM.** Qualquer
   sessão paralela roda ao lado da produção.
2. **A CPU cai para ~0,4 GHz sob carga** (memória de 23/09). Rodar a suíte do backend (932 testes)
   em 3 worktrees ao mesmo tempo vai travar a máquina e derrubar o tempo de resposta da produção.
3. Por isso o "vá em paralelo" aqui tem teto: **2 sessões trabalhadoras locais + 1 orquestradora**, e
   a suíte completa roda na CI do GitHub, não localmente. Localmente cada trabalhadora roda só os
   testes do módulo que tocou. Se quiser mais paralelismo, a saída é **sessão em nuvem**
   (claude.ai/code, o repositório já está no GitHub), que não pesa na máquina.
4. **Custo em tokens**: o próprio post avisa que "power users gastam muito". Com Fable orquestrando e
   Opus executando, 2 trabalhadoras + revisões dobram ou triplicam o consumo de hoje. Vale olhar o
   uso do plano depois da primeira semana.

---

## 4. O fluxo proposto

```
 Leo (gerente)
   │ pedido em português
   ▼
 Sessão ORQUESTRADORA  (Fable, em master, modo Plan, nunca edita código)
   │ escreve a issue: objetivo, regra de negócio, critérios de aceite, testes esperados,
   │ arquivos prováveis, risco (dinheiro / auth / envio / banco), e marca "pronta"
   ▼
 Leo aprova a issue (1 min, pelo celular se quiser)
   │
   ▼
 Sessão TRABALHADORA  (Opus, worktree próprio, 1 issue, branch claude/<issue>)
   │ 1. lê CLAUDE.md + rules + issue        4. roda testes do módulo (hook formata/linta)
   │ 2. escreve os testes do critério        5. abre PR (hook roda a suíte inteira antes)
   │ 3. implementa                           6. PR em português: o que mudou, como testar, suposições
   ▼
 Gates automáticos na PR
   │ CI do GitHub (pytest + tsc + oxlint + vitest + build)   → obrigatório para mergear
   │ /code-review (local)                                     → sempre
   │ agente revisor-adversarial (Fable, só lê)                → sempre
   │ gate Sol (codex gpt-5.6-sol sobre o diff)                → se a issue tem risco marcado
   │ a trabalhadora corrige o que os gates apontarem (1 rodada) e marca "pronta para o Leo"
   ▼
 Leo revisa  (lê o resumo, abre o preview no navegador, testa o critério, comenta ou aprova)
   │ aprovou → auto-merge quando a CI estiver verde (squash); branch apagada sozinha
   ▼
 Deploy  (skill `deploy` nesta máquina: pausa watchdog, deploy.ps1, health, despausa)
```

Quem é quem:

| Papel | Modelo | Onde | Faz | Não faz |
|---|---|---|---|---|
| Orquestradora | Fable | `master`, modo Plan | issue, plano, abre as sessões trabalhadoras, responde dúvidas delas | editar código |
| Trabalhadora (até 2) | Opus | worktree | teste + código + PR | perguntar ao Leo (registra suposição) |
| Revisor adversarial | Fable (agente) | dentro da trabalhadora ou da PR | lista defeitos por gravidade | editar |
| Gate Sol | codex | linha de comando | revisão independente de outro fornecedor | editar |
| Leo | humano | app, celular | aprova issue, revisa PR, mergeia, manda deploy | ler código |

---

## 5. Passo a passo

> **Decisões do Leo em 11/10/2026:** GitHub Pro assinado; para o resto, "aplicar a lógica do Reddit, sem
> restrições, mesmo com limitações de CPU": tarefas em GitHub Issues, **sem teto** de sessões paralelas
> (o teto de 2 do §3 vira recomendação, não regra), memória pessoal limpa. Execução das fases 1 a 5
> iniciada no mesmo dia.

### Fase 0 — decisões suas (antes de qualquer coisa)

1. **GitHub Pro (US$ 4/mês)?** O repositório é privado e a conta parece ser Free. No Free, repositório
   privado **não tem proteção de branch**: não dá para obrigar "só mergeia com CI verde". Com Pro, dá.
   Sem Pro, a regra fica combinada (você só clica em merge com a CI verde) e o app ainda mostra o
   status. É o **único software/serviço externo** que o plano precisa, e é opcional.
2. **Issues no GitHub ou continuar no `backlog.md`?** Recomendo GitHub Issues: cada sessão
   trabalhadora nasce de uma issue, a PR fecha a issue sozinha, e você aprova pelo celular. O
   `backlog.md` continua para decisões e dívidas, sem virar fila de tarefas.
3. **Limite de 2 trabalhadoras locais** (§3). Aceita?
4. **Limpar a memória pessoal** (mover status para docs, apagar regras superadas). Aceita?

### Fase 1 — devolver a memória ao repositório (1 sessão, a mais importante)

5. Recriar `CLAUDE.md` na raiz, com menos de 150 linhas, a partir do apagado em 684f0dc:
   regras que o código não conta (banco, sem custo de API, dinheiro, cadastro YAML, idioma dos
   commits), como rodar testes, **o fluxo de trabalho desta página em 10 linhas**, e quando cada gate
   é obrigatório.
6. Criar `.claude/rules/` por tema, carregadas só quando a sessão mexe nesses arquivos:
   `dinheiro.md` (paths: medições, notas, protocolo), `banco.md` (migrações), `envio.md`
   (e-mail/Outlook), `frontend.md` (identidade visual, skills de design).
7. Recriar `README.md` curto (rodar dev com `DASH_DEV=1`, testes, build).
8. Mover o conteúdo de status das memórias para `docs/backlog.md`/`docs/runbook.md` e deixar na
   memória pessoal só regras e preferências; apagar as regras de fluxo superadas.

### Fase 2 — hooks e permissões (1 sessão)

9. `pip install ruff` no `backend/.venv` e acrescentar ao `requirements.lock`; configurar
   `[tool.ruff]` no `pyproject.toml` com o estilo que o código já tem (sem reformatar tudo de uma vez).
10. Hooks em `.claude/settings.json` (versionado) com scripts em `.claude/hooks/*.ps1`:
    - **PostToolUse** (Edit|Write): `.py` → `ruff format` + `ruff check --fix`; `.ts/.tsx` → `oxlint` no
      arquivo. Erro volta para o Claude corrigir na hora.
    - **PreToolUse** (Bash, comando contém `gh pr create`): roda a suíte do backend e do frontend;
      vermelho bloqueia a abertura da PR.
    - **WorktreeCreate**: cria junções (`mklink /J`) de `frontend/node_modules` e `backend/.venv` do
      tree principal dentro do worktree novo, para não baixar 300 MB nem compilar nada a cada sessão.
      (Precisa de um teste: o `.venv` via junção costuma funcionar; se não, a trabalhadora usa o
      Python do tree principal por caminho absoluto.)
11. Lista de permissões (`permissions.allow`) para `pytest`, `npm test`, `npx tsc`, `git` de leitura,
    `gh pr`, `ruff`: usar o comando `/fewer-permission-prompts`, que varre as sessões passadas e monta
    a lista. Sem isso, sessão paralela pára a cada comando.
12. `.gitignore`: acrescentar `.claude/worktrees/`.

### Fase 3 — agentes e skills do fluxo (1 sessão)

13. `.claude/agents/revisor-adversarial.md`: `model: fable`, só leitura (`Read, Grep, Glob, Bash`),
    instrução de procurar defeito em dinheiro, estado, concorrência, envio duplicado, texto em
    inglês; saída por gravidade.
14. `.claude/skills/gate-sol/SKILL.md`: o comando exato do gate Sol
    (`codex exec -m gpt-5.6-sol` com o diff no stdin, limitação do sandbox no Windows), quando é
    obrigatório, como registrar o resultado no PR.
15. `.claude/skills/nova-tarefa/SKILL.md` (usada pela orquestradora): pedido → issue com o modelo
    da Fase 4, pergunta ao Leo só o que a issue não consegue decidir.
16. `.claude/skills/abrir-pr/SKILL.md` (usada pela trabalhadora): corpo da PR em português
    (o que mudou / por quê / como testar no navegador / suposições / migração sim-não / gates
    rodados), `Closes #N`.
17. `.claude/skills/deploy/SKILL.md`: o runbook (`watchdog.pause`, `deploy.ps1`, health, apagar o
    sentinela), para o deploy ser pedido em uma frase.

### Fase 4 — GitHub (30 min, parte pela interface)

18. Modelo de issue (`.github/ISSUE_TEMPLATE/tarefa.md`): objetivo, regra de negócio, critérios de
    aceite, testes esperados, risco (dinheiro/auth/envio/banco), arquivos prováveis.
19. Modelo de PR (`.github/pull_request_template.md`) igual ao da skill `abrir-pr`.
20. `ci.yml`: trocar `on: push` por `push: branches: [master]` + `pull_request` (hoje cada PR
    rodaria a CI duas vezes). Olhar depois por que o backend leva 20 min (runner Windows + pip);
    não bloqueia o fluxo.
21. Em Settings → General → Pull Requests: ligar **Allow auto-merge** e **Automatically delete head
    branches**.
22. Com GitHub Pro: Settings → Rules → ruleset para `master`: exigir PR, exigir o check `backend` e
    `frontend`, bloquear force push, **sem** você na lista de bypass.
23. Apagar as 46 branches locais já mergeadas (`git branch -d`), e as remotas antigas.
24. Carregar as pendências do `backlog.md` que ainda valem como issues (a orquestradora faz isso).

### Fase 5 — o app Claude (10 min)

25. Settings → Claude Code: worktree location já está em `.claude/worktrees` (ok); prefixo de branch
    `claude` (ok, ou trocar por `tarefa`); ligar **Auto-archive sessions when their pull request
    closes**; notificações de "tarefa concluída" em banner, para o celular avisar.
26. Criar **uma sessão fixa "Orquestradora"** em `master`, modo Plan, modelo Fable, e fixar na
    barra lateral. Sessões trabalhadoras nascem com **Nova sessão → marcar worktree**, modelo Opus,
    com o prompt "Issue #N" e nada mais.
27. Teste de fumaça: pegar **um item pequeno do backlog** (ex.: "upload do comprovante do protocolo
    pela tela") e passá-lo pelo caminho inteiro: issue → trabalhadora em worktree → hooks → PR →
    gates → sua revisão → auto-merge → deploy. Ajustar o que emperrar antes de abrir a segunda
    sessão paralela.

### Fase 6 — a rotina do gerente (o que muda no seu dia)

- **Manhã**: abre a Orquestradora, descreve o que quer, aprova as issues, abre 1 ou 2 trabalhadoras.
- **Durante o dia**: o app avisa quando uma PR está "pronta para o Leo". Você lê o resumo, abre o
  preview, testa o critério de aceite, aprova ou comenta. Nunca lê código.
- **Fim do dia**: merges verdes, uma frase "deploy" na sessão desta máquina.
- **Nunca**: mergear local, editar em `master`, pular a CI, rodar 3 suítes ao mesmo tempo.

---

## 6. Software e serviços: o que precisa e o que já tem

| Item | Situação |
|---|---|
| Git for Windows, GitHub CLI (`gh`, logado), Node 24, Python 3.12, codex CLI 0.151, Claude desktop 2.1.274 | **já instalados** |
| `ruff` (formatador/linter Python, grátis) | instalar no `.venv` (Fase 2) |
| GitHub Pro (US$ 4/mês) | **opcional**: só para obrigar CI verde antes do merge em repositório privado |
| Fila de merge do GitHub | **não precisa** (uma pessoa; e não está disponível na conta pessoal) |
| Prettier | não precisa: `oxlint` + `tsc` já cobrem o frontend |
| Nada em nuvem, nenhuma API paga | de acordo com a regra "sem custo de API" do projeto |

---

## 7. O que NÃO vamos copiar da Reddit, e por quê

- **"Merging lane" / vários worktrees na mesma PR**: é para enxame de agentes em projeto do zero.
  Aqui uma issue = um worktree = uma PR. Mais simples e revisável.
- **Fila de merge**: resolve conflito entre dezenas de PRs de times. Com 2 PRs por vez, "atualizar a
  branch antes de mergear" basta.
- **Deploy automático a partir do merge**: a produção roda numa máquina física com watchdog e
  rollback próprios. Deploy continua sendo um clique seu, pela skill.
- **Mais de 2 sessões locais**: a máquina não aguenta (§3).

---

## 8. Ordem sugerida e tempo

| Fase | Tempo estimado | Depende de |
|---|---|---|
| 0 decisões | 10 min | você |
| 1 memória no repositório | 1 sessão | nada; **começar por aqui** |
| 2 hooks e permissões | 1 sessão | Fase 1 |
| 3 agentes e skills | 1 sessão | Fase 1 |
| 4 GitHub | 30 min + Pro | decisão 1 e 2 |
| 5 app + teste de fumaça | 1 tarde | Fases 1 a 4 |
| 6 rotina | contínuo | Fase 5 |

Fases 2 e 3 podem rodar em paralelo em dois worktrees: seria o primeiro teste real do fluxo.
