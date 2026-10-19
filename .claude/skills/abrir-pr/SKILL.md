---
name: abrir-pr
description: Fecha o trabalho de uma issue e abre a PR em português no modelo .github/pull_request_template.md, depois de testes verdes, /code-review e, numa sessão manual, agente revisor-adversarial em toda PR e gate Sol nas issues com risco:*. Numa trabalhadora da orquestradora, o revisor e o gate ficam como "pendente (orquestradora)". Usada ao fim de uma tarefa, quando a implementação está pronta.
---

# Abrir a PR

Dentro do recorte (aprovado pelo Leo numa sessão manual, ou a própria issue numa trabalhadora), a sessão
decide sozinha; cada decisão vai na seção `## Suposições` da PR, com o motivo. Numa sessão manual, o que sai do
recorte volta para aprovação antes de ser feito; numa trabalhadora, vira pergunta na issue com label `decisao`.

## Antes de abrir (nesta ordem)

1. **Commits feitos** na branch do worktree, em português, assunto sem acento no padrão `tipo: descricao`.
2. **Testes verdes.** Só o que a mudança tocou: os arquivos de teste do módulo no backend
   (`python -m pytest -q backend/tests/test_x.py`, com o `.venv` do projeto) e, se mexeu em `.ts/.tsx`,
   `npx tsc -b`, `npm run lint` e `npm test -- <arquivo>` em `frontend`. Anotar o resultado. A suíte inteira
   roda na CI da PR, que é a prova oficial; não a rode nesta máquina.
3. **`/code-review`** sobre o diff da branch (skill `code-review`), em toda PR. Triar os achados: corrigir o
   que for defeito real e registrar na PR (seção "Gates") o que foi corrigido e o que foi refutado, com motivo.
4. **Numa trabalhadora da orquestradora: parar aqui.** O `revisor-adversarial` e o gate Sol são rodados pela
   orquestradora depois que a PR existe; na seção `## Gates` eles entram como "pendente (orquestradora)".
   **Numa sessão manual:** rodar o **agente `revisor-adversarial`** (Agent tool,
   `subagent_type: revisor-adversarial`, com o número da issue no prompt) em toda PR, e depois o **gate Sol**
   (skill `gate-sol`) só se a issue tem label `risco:*` ou o diff toca `app/dinheiro.py`, medições/notas/
   protocolo, `auth.py`/permissões, `correio.py`/`graph.py`/envios, ou `backend/migrations/`. A revisão é
   bloqueante: cada achado é corrigido (com teste) ou refutado com motivo na PR.
5. Se alguma correção dos passos 3 e 4 mudou código, rodar de novo os testes do módulo tocado.

## Abrir

1. `git push -u origin HEAD:<N>-<nome-curto>`, com a branch no GitHub legível, ex.: `231-oficio-envio-por-fora`
   (número da issue, 2 a 5 palavras do título, minúsculas, sem acento, com hífen). A branch local fica com o
   nome que tem (a ferramenta do worktree o rastreia). Como os nomes diferem, todo push seguinte é
   `git push origin HEAD:<N>-<nome-curto>` (o `git push` simples recusa).
2. Escrever o corpo num arquivo da pasta temporária da sessão, com EXATAMENTE as seções do modelo
   `.github/pull_request_template.md`, nesta ordem:
   - `## O que mudou`: 3 a 6 linhas em português, sem jargão, do ponto de vista do Leo (o que ele passa a ver
     ou fazer). Nada de nome de função, arquivo ou tabela.
   - `## Por quê`: link da issue e `Closes #N`.
   - `## Como testar no navegador`: passos numerados que o Leo segue no preview, com a URL da tela
     (ex.: `http://localhost:5173/obras/12/medicoes/70`), o que clicar e o que deve aparecer. Um passo por critério de
     aceite da issue.
   - `## Suposições`: o que foi decidido sem perguntar e por quê; "Nenhuma" se não houve.
   - `## Migração de banco`: "Não", ou "Sim: `NNN_nome.sql`" e se só acrescenta (coluna, tabela, índice) ou
     mexe em dados (explicar o quê).
   - `## Gates`: checklist com o resumo de cada um:
     ```
     - [x] Testes do módulo: backend N verdes em test_x.py; frontend N testes, tsc e lint ok (suíte inteira na CI)
     - [x] /code-review: N achados, M corrigidos
     - [x] revisor-adversarial: N achados, M corrigidos, K refutados com motivo (ou "OK"; numa trabalhadora, "pendente (orquestradora)")
     - [x] Gate Sol: N achados, M corrigidos, K refutados com motivo (ou "não se aplica (issue sem risco marcado)"; numa trabalhadora com risco, "pendente (orquestradora)")
     ```
3. `gh pr create --base master --head <N>-<nome-curto> --title "tipo: descricao (#N)" --body-file "<scratchpad>/pr-<N>.md"`
   O título repete o título da issue e termina com o número dela.

## Depois de abrir

```bash
M=$(gh pr view <N>-<nome-curto> --json number -q .number)
gh issue comment <N> --body "PR #$M aberta (<nome curto>)"
```

Responder na sessão com o link da PR e as linhas de "Como testar no navegador". Não mergear nem ligar o
auto-merge aqui: numa sessão manual o merge é do Leo; numa trabalhadora, quem liga o auto-merge é a
orquestradora, depois dos gates dela (skill `orquestrar`), em qualquer PR aprovada.
