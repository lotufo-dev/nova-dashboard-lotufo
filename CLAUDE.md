# Dashboard Lotufo

Você é dono e mantenedor de longo prazo deste código, e o desenho dele é decisão sua.

## O produto em cinco linhas

Sistema web interno da Lotufo Engenharia (FastAPI + React + SQLite) para contratos de obras públicas e o
ciclo da medição: em análise no órgão → boletim → nota → protocolado → recebido.
O sistema é onde o trabalho é feito; o registro é consequência. Ele só lê o que a pessoa entregou a ele, o que ele
mesmo enviou e o TOTVS RM, que só confirma o que a pessoa já fez; caixa de e-mail, pasta e SharePoint ficam fora.
Trava só o que sai errado para fora e não se desfaz; o resto avisa e segue com justificativa. Quem opera digita
pouco e confere; regra, cadastro e instrumento são do dono, em arquivo versionado.

## Onde está cada coisa

- `README.md`: rodar e testar. `docs/runbook.md`: produção e deploy.
- Termos: `GLOSSARY.md`. Decisões com o motivo: `docs/adr/`.
- Regras por tema: `.claude/rules/`, que carregam sozinhas quando a sessão mexe nos arquivos do tema.
- `docs/superpowers/specs/`: histórico, para saber de onde veio uma decisão antiga (`docs/adr/0001`).
- Decisões e dívidas que não viraram issue: `docs/backlog.md` (uma linha por item; fechou, apaga a linha).
- Identidade visual: `docs/identidade-visual.md`. O que seguir ao mexer em tela: `.claude/rules/frontend.md`.

## Regras que valem em qualquer arquivo

- **A produção roda em outro computador**, o `<servidor>`, a partir de uma cópia fixa do código em
  `C:\DashboardLotufo\app`, com os dados em `C:\DashboardLotufo`. Ela é tratada como em uso: o código dela muda só
  por deploy pedido pelo dono (skill `deploy`). Gravação de dado nela (carga, correção, `cadastro aplicar`) não
  espera autorização do dono: a sessão grava pelo rito do `docs/runbook.md` (ensaio lido, backup antes, conferência
  depois) e relata o que gravou (`docs/adr/0014`). Conta de acesso e gravação no RM continuam só com a
  autorização dele na hora. A máquina onde se desenvolve não é a produção.
- **Repositório público**: cada push sai na hora e não se apaga. Dado real (cadastro, pessoa, NF, valor, certidão,
  e-mail, CNPJ) mora no repositório privado `lotufo-cadastro` (lido via `DASH_CADASTRO_DIR`) e na produção; nesta
  árvore, não. Nome de obra e de órgão público não conta como dado real (`docs/adr/0011`). Nos textos, papel no lugar do nome da pessoa ("o dono", "o faturamento") e
  `<servidor>` no lugar do nome da máquina. O detalhe está em `.claude/rules/dados-de-teste.md`.
- **Banco de dev.** `backend/dados/dashboard.db` só com `DASH_DEV=1`. Servidor de revisão, seed e teste
  exploratório usam `DASH_DB_PATH` apontando para a pasta temporária da sessão (`DASH_DEV=1`, `DASH_SEM_JOBS=1`),
  para o banco padrão nunca ser semeado nem apagado.
- **Sem custo de API**: o produto não chama serviço pago por uso. Extração determinística (regex, pypdf,
  openpyxl) com fila humana para o resto. Única exceção decidida: OCR local (Tesseract no servidor) nas certidões
  sem texto. Microsoft 365 e RM, já pagos, não contam.
- **Dinheiro, envio e banco** têm regra própria em `.claude/rules/`. Mudança neles passa por uma segunda revisão
  independente, de quem não escreveu o código, antes do merge.
- **Merge sem esperar o dono.** A sessão liga o merge da PR sozinha quando a conferência do corpo da PR está
  fechada (suíte, revisão do código e, em dinheiro, envio ou banco, a segunda revisão) e a CI está verde
  (`docs/adr/0014`). O que a CI barra para merge do dono (verificação de vazamento e hooks) continua dele.
- **Projeto antigo** (`~/dev/lotufo-dashboard`, `~/dev/lotufo-automacao-medicao`): leitura autorizada para
  comparar produto e extrair regra de domínio. O código de lá não se herda.
- **Português** nos textos da interface, mensagens de erro, commits, issues e PRs. Assunto de commit no padrão
  `tipo: descricao` (feat/fix/docs/test/chore), sem acento.
- **Sem perguntar a terceiros.** Dúvida não vira proposta de perguntar ao faturamento, à TI ou ao órgão:
  resolve-se pelos documentos (Outlook, RM, SharePoint, banco) ou decide-se e registra-se.
- **Mudança de comportamento sai com teste** ao lado dos existentes.

## Testes

- Backend: `cd backend && .venv/bin/python -m pytest -q` (no Windows, `.venv\Scripts\python`). Frontend:
  `cd frontend && npm test`, `npm run typecheck`, `npm run lint`. A CI roda esses mesmos comandos no Ubuntu.
- Depois de cada edição, um hook roda `ruff check --fix` no `.py` e `oxlint` no `.ts/.tsx`, e o erro que sobra
  volta para corrigir. `ruff format` e ordenação de imports não rodam: o código existente não está formatado e
  reformatá-lo esconderia as mudanças reais nos diffs.
- Num worktree, `.venv` e `node_modules` são links para os da pasta principal, criados por hook. `npm ci` e
  `pip install` dentro de um worktree alterariam os da pasta principal.
- Verificação visual exige login (`DASH_DEV=1`, ver README).

## Agent skills

### Issue tracker

As issues e especificações ficam no GitHub Issues deste repositório, que é público. Ver `docs/agents/issue-tracker.md`.

### Triage labels

Cinco papéis de triagem mapeados para os labels do repositório (`triagem`, `decisao`, `pronta`, `sessao-manual`,
`wontfix`). Ver `docs/agents/triage-labels.md`.

### Domain docs

Contexto único: `GLOSSARY.md` na raiz e `docs/adr/`. Ver `docs/agents/domain.md`.
