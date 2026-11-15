---
paths:
  - "backend/tests/**"
  - "cadastro-exemplo/**"
  - "docs/**"
---

# Dado de teste e repositório público

- **O repositório é público e cada push sai na hora.** O que entra aqui já é conhecido de quem quiser ler;
  não existe "apago depois". Conferir o diff antes de commitar.
- **Dado de teste é sintético.** Nunca colar NF, certidão, e-mail, nome de pessoa ou CNPJ reais em teste,
  fixture, exemplo de cadastro, spec, plano, backlog ou comentário. Em fixtures e `cadastro-exemplo/`, usar CNPJ fictício com dígito válido; em docs, sempre placeholder inválido (`00.000.000/0001-00`);
  razão social inventada ("Construtora Alfa Ltda"), pessoa pelo papel ("faturamento", "controladoria",
  "engenheira da obra", "fiscal do contrato") e e-mail em `@exemplo.com.br` ou `@lotufo.com`.
- **Cadastro real mora fora do repositório**: no repositório privado `lotufo-cadastro` (clone em
  `C:\DashboardLotufo\cadastro`, lido via `DASH_CADASTRO_DIR`) e em `C:\DashboardLotufo`. O que o código precisa
  para testar está em `cadastro-exemplo/`, com órgão e contrato fictícios.
- **Máquina, porta e tarefa de produção também não entram**: `<servidor>` nos textos e `$env:DASH_SERVIDOR`
  nos scripts. Client ID e tenant do Microsoft 365 vêm de variável de ambiente; em exemplo, vale
  `00000000-0000-0000-0000-000000000000`.
- Achou dado real já escrito (fixtures, migração, código)? Avise o dono e abra uma issue: a troca precisa de um
  mapa único, para o mesmo dado virar o mesmo valor fictício em todo lugar.
