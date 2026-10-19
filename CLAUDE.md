# Dashboard Lotufo — instruções para o Claude Code

Ler primeiro: `README.md` (rodar e testar), `docs/runbook.md` (produção), `docs/fluxo-de-trabalho-2026-10-11.md`
(como o trabalho anda). Autoridade de produto: `docs/superpowers/specs/2026-09-21-reestruturacao-design.md`
(o que ela não contradiz da spec de 2026-08-28 continua valendo). Tarefas abertas: **GitHub Issues**.
Decisões e dívidas que não viraram issue: `docs/backlog.md` (uma linha por item; fechou, apaga a linha).
Regras por tema carregam sozinhas de `.claude/rules/` quando a sessão mexe nos arquivos certos.

## O produto em cinco linhas

Sistema web interno da Lotufo Engenharia (FastAPI + React + SQLite) para contratos de obras públicas e o
ciclo da medição: espelho de NF → envio ao faturamento → nota → envio ao órgão/protocolo → pagamento.
O sistema é onde o trabalho é feito; o registro é consequência. Nada adivinha: não lê e-mail, planilha nem
SharePoint; a única fonte automática é o TOTVS RM, que só confirma o que a pessoa já fez. Quem opera
digita pouco e confere; regra, cadastro e instrumento são do Leo, em arquivo versionado (`cadastro/*.yaml`).

## Regras que o código não conta

- **Esta máquina é o servidor de produção da dashboard e do TOTVS RM.** A produção roda do
  worktree pinado `C:\DashboardLotufo\app` com dados em `C:\DashboardLotufo`. Nunca editar, trocar branch,
  parar tarefa agendada ou mexer nos dados de lá por conta própria: deploy só pela skill `deploy`.
- **Repositório público** (decisão do Leo de 13/10/2026; corte feito em 14/10/2026, #107): cada push sai na hora e
  não se apaga. Dado real (cadastro, NF, certidão, e-mail, CNPJ) mora no repositório privado `lotufo-cadastro`
  (clone em `C:\DashboardLotufo\cadastro`, lido via `DASH_CADASTRO_DIR`) e em `C:\DashboardLotufo`; nunca nesta árvore.
  Nada de pessoa, e-mail ou máquina nos textos (papel no lugar do nome, `<servidor>` no lugar da máquina).
- **Banco.** Dev usa `backend/dados/dashboard.db` só com `DASH_DEV=1`. Servidor de revisão, seed e teste
  exploratório só com `DASH_DB_PATH` apontando para o scratchpad (`DASH_DEV=1`, `DASH_SEM_JOBS=1`).
  Nunca semear nem apagar o banco padrão. Migrações em `backend/migrations/`, idempotentes, nunca destrutivas.
- **Sem custo de API** (spec §15, decisão de 2026-09-01): o produto não chama serviço pago por uso.
  Extração determinística (regex, pypdf, openpyxl) com fila humana para o resto. Única exceção decidida em
  2026-09-24: OCR local (Tesseract no servidor) nas certidões sem texto. Microsoft 365 e RM, já pagos, não contam.
- **Dinheiro e histórico.** Centavos inteiros, arredondamento único, valor protocolado congelado no protocolo,
  correção é evento novo (nunca sobrescrita), sem exclusão física de registro financeiro, auditoria append-only.
  O cadastro guarda o contrato na cota do consórcio; as medições guardam o valor cheio e a cota é derivada.
- **Cadastro versionado.** Obras, órgãos, entidades e instrumentos moram em `cadastro/*.yaml`, editados pelo
  Leo com o Claude e aplicados por `python -m app.cli cadastro aplicar`. Não existe tela de cadastro;
  instrumento aplicado não se altera (correção é instrumento novo).
- **Envio de e-mail sai da conta Microsoft de quem clicou**, nunca de conta de serviço. Envio é único e
  registrado antes de sair (reserva atômica); reenvio exige intenção explícita.
- **Projeto antigo** (`~/dev/lotufo-dashboard`, `~/dev/lotufo-automacao-medicao`): leitura autorizada para
  comparar produto e extrair regra de domínio, por subagente; nunca herdar código de lá.
- **Textos da interface, mensagens de erro, commits, issues e PRs em português.** Assunto de commit no padrão
  `tipo: descricao` (feat/fix/docs/test/chore), sem acento. Nada de código interno ou inglês na tela.
- **Sem perguntar a terceiros.** Nunca propor perguntar ao faturamento, TI ou órgão; resolver pelos documentos
  (Outlook, RM, SharePoint, banco) ou decidir e registrar.

## Como o trabalho anda

- A fila é o GitHub Issues. Issue com label `decisao` espera resposta do Leo; `precisa-do-leo` espera ele
  olhar uma PR ou falha; `parar` em qualquer issue aberta pausa a orquestradora.
  `sessao-manual` é trabalho feito com o Leo (dado de produção, Outlook dele): a orquestradora não pega.
  `redesenho` é tela refeita pelo Higgsfield: a orquestradora implementa e trata como qualquer PR (auto-merge
  liberado pelo Leo em 16/10/2026).
- **Como se nomeia** (decidido em 19/10/2026). Número de issue ou PR nunca aparece sozinho em resposta,
  resumo, comentário ou relatório: vai com o nome curto ao lado, "#231 (ofício no envio por fora)"; a PR cita
  a issue, "PR #238 da #231 (ofício no envio por fora)". Toda issue leva um label `area:*` com a etapa do
  ciclo (`contrato`, `medicao`, `faturamento`, `nota`, `protocolo`, `pagamento`, `infra`). A branch sobe ao
  GitHub como `<N>-<nome-curto>` (`231-oficio-envio-por-fora`), pela skill `abrir-pr`.
- **Orquestradora** (decidido em 13/10/2026): sessão fixa do Leo na pasta principal, em `master`, modelo Opus.
  Quando ele diz "rodada" ou "até acabar", a skill `orquestrar` pega até 10 issues elegíveis, abre uma
  **trabalhadora** por issue (agente `trabalhadora`, worktree próprio, Sonnet; Opus se a issue tem `risco:*`),
  roda o `revisor-adversarial` (Opus) em toda PR e o gate Sol (codex) nas de risco, manda os achados de volta
  (2 rodadas no máximo), e liga o auto-merge em qualquer PR quando as travas passam (CI verde, sem conflito,
  revisor-adversarial sem Crítico/Aviso em aberto, sem comentário do Leo pedindo para segurar; vale também
  para redesenho, migração, `risco:*` e PR que toca `.github/`, `scripts/deploy.ps1` ou `.claude/`, decisão do
  Leo de 16/10/2026). O gate Sol roda quando o codex existe; na nuvem não é trava. A orquestradora não edita
  código e não faz deploy.
- A trabalhadora não pergunta ao Leo: escolha técnica vira `## Suposições` da PR; regra de negócio sem fonte
  vira pergunta na issue com label `decisao`, e ela para sem PR.
- Sessão manual em worktree pelo app continua valendo para o que o Leo quiser conduzir: abre em modo Plan,
  apresenta o recorte, espera o OK, e aí trabalha sem perguntar de novo; nela, o `revisor-adversarial` e o
  gate Sol rodam na própria sessão, como a skill `abrir-pr` descreve.
- Toda mudança de comportamento sai com teste ao lado dos existentes. Localmente só os testes do módulo
  tocado; a CI é a suíte oficial. `/code-review` em toda PR, com os achados triados e registrados nela.
- Merge: automático pela orquestradora quando as travas passam; o que ela segurar é do Leo, no GitHub, com CI verde.
  Deploy só pela skill `deploy`, quando ele pedir.

## Testes

- Backend: `cd backend && .venv\Scripts\python -m pytest -q` (~930 testes). Frontend: `cd frontend && npm test`,
  `npm run typecheck`, `npm run lint`. Esses são os comandos da CI; **localmente, só o arquivo de teste do
  módulo tocado** (`pytest -q tests/test_x.py`, `npm test -- <arquivo>`), porque a suíte inteira em dois
  worktrees derruba a CPU desta máquina, que é a produção. Num worktree, `.venv` e `node_modules` são junções para os do tree
  principal, criadas no início da sessão pelo hook `preparar-worktree.ps1` (no Mac, `.sh` e links simbólicos;
  ver "Rodar no Mac" no README; se faltarem, rodar o script à mão); o código testado é o do worktree. Ao remover um worktree, o hook `desfazer-juncoes.ps1` tira as
  junções antes (senão fica a casca da pasta); `npm ci` ou `pip install` dentro do worktree mexem no
  `node_modules`/`.venv` principal, então não os rode num worktree.
- Hooks do projeto (`.claude/settings.json`): depois de cada edição, `ruff check --fix` (E9, F) no `.py`
  e `oxlint` no `.ts/.tsx`, e erro que sobra volta para corrigir. `ruff format` e ordenação de imports não
  rodam: o código existente não está formatado e não vamos reformatá-lo (issue #74). Antes de cada commit, o
  `.githooks/pre-commit` (ligado por `core.hooksPath` no início da sessão) roda `ruff check` nos `.py` e
  `tsc` nos `.ts/.tsx` que estão no commit; a suíte inteira fica para a CI.
- Frontend: identidade visual em `docs/identidade-visual.md`; as 13 skills de design em `.claude/skills/`
  (taste-skill) valem para tela nova. Verificação visual exige login (`DASH_DEV=1`, ver README).
