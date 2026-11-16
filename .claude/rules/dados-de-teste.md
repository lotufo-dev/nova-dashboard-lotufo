---
paths:
  - "backend/tests/**"
  - "cadastro-exemplo/**"
  - "docs/**"
---

# Dado de teste e repositório público

- **O repositório é público e cada push sai na hora.** O que entra aqui já é conhecido de quem quiser ler;
  não existe "apago depois". Conferir o diff antes de commitar.
- **Continua proibido na árvore** (código, teste, fixture, migração, exemplo de cadastro, docs, spec, plano,
  backlog, comentário): nome de pessoa, e-mail real, CNPJ ou CPF real, número de nota fiscal, valor real (de
  contrato, medição ou nota), certidão, nome de máquina, porta e tarefa de produção, identificador de aplicativo e
  domínio do Microsoft 365. O nome do dono também não se escreve: nos textos vale o papel ("o dono").
- **Exceção para o nome do dono já escrito**: fica como está em migração já aplicada (não se reescreve), em dado de
  teste do qual um assert depende, na verificação de vazamento (`scripts/vazamento*`, mudança nela é do dono) e no
  registro histórico de `docs/superpowers/specs/` e `plans/`. Texto novo usa o papel.
- **Nome de obra e de órgão de contrato público não é dado real** (decisão de 16/11/2026, `docs/adr/0011`): é
  informação publicada em Diário Oficial. O que já está escrito com nome real de obra ou órgão (código,
  migração, teste, doc) não é violação e não precisa de troca.
- **Dado de teste é sintético.** Em teste e fixture NOVOS, preferir a obra e o órgão fictícios de
  `cadastro-exemplo/`. Em fixtures e `cadastro-exemplo/`, usar CNPJ fictício com dígito válido; em docs, sempre
  placeholder inválido (`00.000.000/0001-00`); razão social inventada ("Construtora Alfa Ltda"), pessoa pelo papel
  ("faturamento", "controladoria", "engenheira da obra", "fiscal do contrato"), e-mail em `@exemplo.com.br` ou
  `@lotufo.com` e valores inventados.
- **Cadastro real mora fora do repositório**: no repositório privado `lotufo-cadastro` (clone em
  `C:\DashboardLotufo\cadastro`, lido via `DASH_CADASTRO_DIR`) e em `C:\DashboardLotufo`. O que o código precisa
  para testar está em `cadastro-exemplo/`, com órgão e contrato fictícios.
- **Máquina e Microsoft 365 vêm de variável**: `<servidor>` nos textos e `$env:DASH_SERVIDOR` nos scripts. Client
  ID e tenant do Microsoft 365 vêm de variável de ambiente; em exemplo, vale
  `00000000-0000-0000-0000-000000000000`.
- Achou dado proibido já escrito (fixtures, migração, código)? Avise o dono e abra uma issue: a troca precisa de um
  mapa único, para o mesmo dado virar o mesmo valor fictício em todo lugar.
