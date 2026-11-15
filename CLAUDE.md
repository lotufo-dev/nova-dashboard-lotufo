# Dashboard Lotufo

Você é dono e mantenedor de longo prazo deste código, e o desenho dele é decisão sua.

## O produto em cinco linhas

Sistema web interno da Lotufo Engenharia (FastAPI + React + SQLite) para contratos de obras públicas e o
ciclo da medição: espelho de NF → envio ao faturamento → nota → envio ao órgão/protocolo → pagamento.
O sistema é onde o trabalho é feito; o registro é consequência. Nada adivinha: não lê planilha nem SharePoint, e de
e-mail lê só a conversa que ele mesmo enviou (a resposta do órgão à planilha enviada, pela conta de quem enviou);
fora isso, a única fonte automática é o TOTVS RM, que só confirma o que a pessoa já fez. Quem opera
digita pouco e confere; regra, cadastro e instrumento são do dono, em arquivo versionado (`cadastro/*.yaml`).

## Onde está cada coisa

- `README.md`: rodar e testar. `docs/runbook.md`: produção e deploy.
- Autoridade de produto: `docs/superpowers/specs/2026-09-21-reestruturacao-design.md` (o que ela não contradiz
  da spec de 2026-08-28 continua valendo).
- Decisões e dívidas que não viraram issue: `docs/backlog.md` (uma linha por item; fechou, apaga a linha).
- Regras por tema: `.claude/rules/`, que carregam sozinhas quando a sessão mexe nos arquivos certos.
- Identidade visual: `docs/identidade-visual.md`.

## Regras que o código não conta

- **A produção roda em outro computador**, o `<servidor>`, a partir de uma cópia fixa do código em
  `C:\DashboardLotufo\app`, com os dados em `C:\DashboardLotufo`. A equipe usa essa instalação todos os dias. Ela
  só muda por deploy pedido pelo dono (skill `deploy`) ou por gravação que ele autoriza na hora. A máquina onde
  se desenvolve não é a produção.
- **Repositório público**: cada push sai na hora e não se apaga. Dado real (cadastro, NF, certidão, e-mail, CNPJ)
  mora no repositório privado `lotufo-cadastro` (lido via `DASH_CADASTRO_DIR`) e na produção; nesta árvore, não.
  Nos textos, papel no lugar do nome da pessoa e `<servidor>` no lugar do nome da máquina.
- **Banco.** Dev usa `backend/dados/dashboard.db` só com `DASH_DEV=1`. Servidor de revisão, seed e teste
  exploratório usam `DASH_DB_PATH` apontando para a pasta temporária da sessão (`DASH_DEV=1`, `DASH_SEM_JOBS=1`),
  para o banco padrão nunca ser semeado nem apagado. Migrações em `backend/migrations/`, idempotentes e só de
  acréscimo, porque rodam sozinhas sobre o banco de produção.
- **Sem custo de API**: o produto não chama serviço pago por uso. Extração determinística (regex, pypdf,
  openpyxl) com fila humana para o resto. Única exceção decidida: OCR local (Tesseract no servidor) nas certidões
  sem texto. Microsoft 365 e RM, já pagos, não contam.
- **Dinheiro e histórico.** Centavos inteiros, arredondamento único, valor protocolado congelado no protocolo,
  correção é evento novo (não sobrescreve), sem exclusão física de registro financeiro, auditoria só de acréscimo.
  O cadastro guarda o contrato na cota do consórcio; as medições guardam o valor cheio e a cota é derivada.
- **Cadastro versionado.** Obras, órgãos, entidades e instrumentos moram em `cadastro/*.yaml`, editados pelo
  dono com o Claude e aplicados por `python -m app.cli cadastro aplicar`. Não existe tela de cadastro;
  instrumento aplicado não se altera (correção é instrumento novo).
- **Envio de e-mail sai da conta Microsoft de quem clicou**, não de conta de serviço. Envio é único e
  registrado antes de sair (reserva atômica); reenvio exige intenção explícita.
- **Projeto antigo** (`~/dev/lotufo-dashboard`, `~/dev/lotufo-automacao-medicao`): leitura autorizada para
  comparar produto e extrair regra de domínio. O código de lá não se herda.
- **Português** nos textos da interface, mensagens de erro, commits, issues e PRs. Assunto de commit no padrão
  `tipo: descricao` (feat/fix/docs/test/chore), sem acento. Código interno e inglês não aparecem na tela.
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
