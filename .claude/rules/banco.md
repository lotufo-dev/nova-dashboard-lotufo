---
paths:
  - "backend/migrations/**"
  - "backend/app/db.py"
  - "backend/app/backup.py"
  - "backend/app/cadastro_aplicar.py"
  - "cadastro/**"
---

# Banco, migrações e cadastro

- SQLite endurecido: WAL, chaves estrangeiras ligadas, escrita serializada. Contadores e reservas que
  precisam ser atômicos usam `BEGIN IMMEDIATE` (ex.: senhas erradas, reserva de envio).
- Migração nova = arquivo numerado em `backend/migrations/` (próximo número livre), idempotente, **só
  acrescenta** (coluna, tabela, índice). Nunca `DROP`, nunca `DELETE` de dado financeiro, nunca renomear
  coluna em uso. As migrações rodam sozinhas em `create_app()`.
- Tabelas com prefixo `arquivo_` são o histórico da detecção antiga: não ler, não apagar, não migrar.
- A PR que traz migração diz isso na seção "Migração de banco" com o número e a frase "só acrescenta".
- Dev: `backend/dados/dashboard.db` só com `DASH_DEV=1`. Qualquer seed ou servidor de revisão usa
  `DASH_DB_PATH` no scratchpad. Nunca semear nem apagar o banco padrão. Produção: `C:\DashboardLotufo\dados`,
  intocável fora da skill `deploy` e do runbook.
- Cadastro (`cadastro/*.yaml`): editado com o Leo, aplicado por `python -m app.cli cadastro aplicar`
  (`--ensaio` primeiro). Instrumento aplicado não muda; correção é instrumento novo. Reajuste zerado no
  cadastro não significa ausência de reajuste.
- Backup: snapshot horário com ensaio de restauração; não desligar, não mudar retenção sem issue.
- Antes do merge de mudança nestes arquivos, o diff passa por uma revisão do Codex (outro fornecedor, pontos
  cegos diferentes): `/codex:adversarial-review`, ou o agente `codex:codex-rescue` quando é a própria sessão a pedir.
