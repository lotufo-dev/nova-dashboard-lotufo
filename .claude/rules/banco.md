---
paths:
  - "backend/migrations/**"
  - "backend/app/db.py"
  - "backend/app/backup.py"
  - "backend/app/cadastro_aplicar.py"
  - "backend/app/cadastro_arquivos.py"
  - "cadastro-exemplo/**"
---

# Banco, migrações e cadastro

- **Migração nunca perde dado** (`docs/adr/0010`). Arquivo numerado em `backend/migrations/`, no próximo número
  livre, idempotente, porque roda sozinha ao subir, inclusive sobre o banco de produção. Pode reconstruir uma
  tabela (criar a nova, copiar todas as linhas, trocar); nunca apaga linha nem coluna com dado financeiro e nunca
  renomeia coluna em uso. Reconstrução de tabela sai com teste que compara a contagem de linhas antes e depois.
- Contador ou reserva que precisa ser atômico usa `BEGIN IMMEDIATE`.
- Tabelas com prefixo `arquivo_` são o histórico da detecção antiga: ficam como estão, sem leitura, migração ou
  limpeza.
- **Cadastro.** O cadastro real mora no repositório privado, lido por `DASH_CADASTRO_DIR`; aqui existe só
  `cadastro-exemplo/`, fictício. Entra no banco por `python -m app.cli cadastro aplicar`, com `--ensaio` antes.
  Instrumento aplicado não muda: a correção é um instrumento novo. Reajuste zerado no cadastro não significa
  ausência de reajuste.
- **Backup.** Snapshot horário com ensaio de restauração: continua ligado, e a retenção só muda por issue.
