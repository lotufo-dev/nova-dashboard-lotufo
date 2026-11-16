# Onde ficam as issues: GitHub

As issues e as especificações deste repositório são issues do GitHub. Todas as operações usam o `gh`.

## O repositório é público

Tudo o que se escreve em issue, especificação, ticket ou PR sai na hora e não se apaga. Dado real (valor, nota,
CNPJ, e-mail, nome de pessoa, nome de máquina) não entra no texto: papel no lugar do nome ("o dono", "a
engenheira da obra"), `<servidor>` no lugar da máquina, exemplo inventado no lugar do valor. Nome de obra e de
órgão público pode (`docs/adr/0011`). Texto em português.

Número de issue ou de PR nunca aparece sozinho em resposta, resumo ou comentário: vai com o nome curto ao lado,
"#231 (ofício no envio por fora)". Toda issue leva um label `area:*` com a etapa do ciclo (`contrato`, `medicao`,
`faturamento`, `nota`, `protocolo`, `pagamento`, `infra`) e, quando mexe nisso, um `risco:*` (`dinheiro`, `auth`,
`envio`, `banco`).

## Convenções

- **Criar uma issue**: `gh issue create --title "..." --body-file <arquivo>`, com o corpo num arquivo da pasta
  temporária da sessão.
- **Ler uma issue**: `gh issue view <número> --json number,title,body,labels,comments`.
- **Listar issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`, com os filtros `--label` e `--state` que couberem.
- **Tornar uma issue filha de outra**: `gh issue create --parent <mãe> ...`, ou depois `gh issue edit <mãe> --add-sub-issue <filha>`.
- **Comentar**: `gh issue comment <número> --body-file <arquivo>`.
- **Pôr ou tirar label**: `gh issue edit <número> --add-label "..."` / `--remove-label "..."`.
- **Fechar**: `gh issue close <número> --comment "..."`.

O repositório vem de `git remote -v`; o `gh` faz isso sozinho dentro do clone.

## PR como fila de pedidos

**PR como pedido: não.** Este repositório não recebe PR de fora.

O GitHub usa uma numeração só para issue e PR: um `#42` solto pode ser qualquer um dos dois. Resolver com
`gh pr view 42` e, se não for, `gh issue view 42`.

## Quando uma skill diz "publicar no rastreador de issues"

Criar uma issue no GitHub.

## Quando uma skill diz "buscar o ticket"

Ler como em **Ler uma issue**, acima.
