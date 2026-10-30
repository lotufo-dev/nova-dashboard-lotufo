---
name: nova-tarefa
description: Opcional. Transforma um pedido do Leo em uma ou mais issues no GitHub, no modelo .github/ISSUE_TEMPLATE/tarefa.md (objetivo, regra de negócio, critérios de aceite, testes esperados, risco, arquivos prováveis, origem). Usar só quando o Leo pedir "transforme isto em issues" ou equivalente.
---

# Nova tarefa: pedido do Leo → issue

Entender o pedido, ler o que precisa no repositório (código, `docs/`, `docs/backlog.md`, `cadastro/`) e
escrever issues que uma sessão consegue executar sozinha com o recorte aprovado pelo Leo.

## Regras

- **Uma issue = uma PR.** No máximo meio dia de trabalho. Pedido maior vira várias issues, cada uma
  entregável sozinha; se uma depende de outra, dizer em "Origem" ("depende da #N").
- **Critérios de aceite verificáveis pelo Leo no navegador** (ou na API, quando não houver tela): o que ele
  clica, o que aparece, com que texto. Nada de "o código fica limpo".
- **Testes esperados** nomeiam o arquivo de teste e o comportamento (ex.: `backend/tests/test_api_protocolos.py`:
  comprovante em PDF é gravado e aparece no detalhe; `frontend/src/Protocolo.test.tsx`: botão some para a
  diretoria). Cada critério de aceite tem pelo menos um teste.
- **Risco**: marcar com os labels `risco:dinheiro`, `risco:auth`, `risco:envio`, `risco:banco` (um ou mais) ou
  nenhum. Com risco, a PR passa também pelo agente `revisor-adversarial` e pelo gate Sol (skill `gate-sol`).
  - dinheiro: valor, cota, reajuste, nota, protocolo, recebimento;
  - auth: login, sessão, perfil, permissão;
  - envio: e-mail pelo Graph, protocolo enviado ao órgão;
  - banco: migração nova em `backend/migrations/`.
- **Área**: sempre um label `area:*` com a etapa do ciclo: `area:contrato` (obra, órgão, instrumento,
  garantia, cadastro), `area:medicao` (medição e espelho de NF), `area:faturamento`, `area:nota` (nota e RM),
  `area:protocolo` (envio ao órgão, ofício, carta), `area:pagamento` (recebimento) ou `area:infra` (deploy,
  login, automação do trabalho). Os labels já existem no GitHub.
- **Perguntar ao Leo só o que a issue não consegue decidir sozinha** (regra de negócio sem fonte, escolha entre
  dois comportamentos que ele vai ver). Tudo de uma vez, numa mensagem só, numerado. Escolha técnica não é
  pergunta: decida e escreva na "Regra de negócio" ou em "Arquivos prováveis".
- Datas no formato DD/MM/AAAA. Tudo em português.

## Passo a passo

1. Montar o rascunho das issues, cada uma com EXATAMENTE as seções do modelo
   `.github/ISSUE_TEMPLATE/tarefa.md`, nesta ordem:
   `## Objetivo`, `## Regra de negócio`, `## Critérios de aceite`, `## Testes esperados`, `## Risco`,
   `## Arquivos prováveis`, `## Origem`.
   Título: curto, em português, no formato `tipo: descricao` (vira o título da PR).
2. Se houver perguntas, fazê-las todas juntas antes de criar qualquer issue.
3. Criar os labels que faltarem (erro de "já existe" é ignorado):

   ```bash
   gh label create "risco:dinheiro" --color B60205 --description "Mexe em valor, cota, nota, protocolo ou recebimento"
   gh label create "risco:auth"     --color 5319E7 --description "Mexe em login, sessão, perfil ou permissão"
   gh label create "risco:envio"    --color D93F0B --description "Mexe em e-mail ou envio ao órgão"
   gh label create "risco:banco"    --color 0E8A16 --description "Tem migração de banco"
   ```

4. Criar cada issue com o corpo num arquivo da pasta temporária da sessão (não no repositório):

   ```bash
   gh issue create --title "tipo: descricao" --body-file "<scratchpad>/issue-1.md" --label "area:nota,risco:dinheiro"
   ```

   Sem risco, só o label de área.
5. Pôr cada issue no quadro "Fila da Dashboard", coluna **Na fila** (ou **Esperando o Leo** se saiu com
   `decisao`), com os comandos da seção "Quadro" da skill `orquestrar` (id da coluna Na fila: `6724fdd6`).
6. Responder ao Leo com a lista: número, título, área e risco.
