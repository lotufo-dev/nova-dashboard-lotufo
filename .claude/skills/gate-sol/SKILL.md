---
name: gate-sol
description: Gate Sol, a revisão independente do diff da branch pelo codex CLI (modelo gpt-5.6-sol, outro fornecedor). Obrigatória quando a issue tem label risco:dinheiro, risco:auth, risco:envio ou risco:banco. Usar antes de abrir a PR, depois do revisor-adversarial.
---

# Gate Sol

Revisão do diff inteiro da branch por um modelo de outra família (GPT-5.6 Sol, pelo `codex` CLI), para não
ter o mesmo ponto cego de quem implementou e de quem revisou. Usa a assinatura ChatGPT do Leo, não API paga.

## Quando é obrigatória

- A issue tem pelo menos um destes labels: `risco:dinheiro`, `risco:auth`, `risco:envio`, `risco:banco`
  (conferir com `gh issue view <N> --json labels -q '.labels[].name'`).
- Sem label de risco: não roda; na PR fica "Gate Sol: não se aplica (issue sem risco marcado)".
- Dispensa só se o Leo escrever na issue ou na PR que dispensa; na PR fica "Gate Sol: dispensado pelo Leo em
  DD/MM/AAAA".

## Como rodar

Rodar pela ferramenta **Bash** (Git Bash), não pelo PowerShell: o PowerShell 5.1 recodifica o que passa pelo
pipe e estraga os acentos do diff. O codex só lê o texto, não executa nada (o sandbox do codex no Windows
não abre subprocessos, então não peça para ele rodar testes ou `git`).

**Rodar de dentro do worktree** (o `cd "<worktree>"` do subshell abaixo, nunca solto), que já é um repositório git: assim o codex não precisa de
`--skip-git-repo-check`, e a proteção do worktree recusa o comando que leva essa opção (visto na issue #75).
**Nunca use `--skip-git-repo-check`.** O pedido e o diff inteiro vão **juntos num único arquivo de entrada**,
lido pelo stdin com `-` no lugar do prompt.

Antes, garantir que o `master` de comparação está em dia: `git fetch origin` e, se `master` local estiver
atrás de `origin/master`, use `origin/master...HEAD` no lugar de `master...HEAD`. Quando a orquestradora
chama a skill, a branch está no worktree da trabalhadora, não na pasta atual: entre no worktree com o `cd`
do subshell abaixo (nunca com um `cd` solto). **Conferir antes que o diff não é vazio** (`git diff --stat origin/master...HEAD`): diff vazio
dá "OK" do codex sem ele ter lido nada, e isso não é veredito.

O bloco abaixo vai **inteiro numa única chamada do Bash, dentro de um subshell** `( ... )`: o `cd` fica dentro
do subshell e não muda o diretório da sessão. Isso importa porque, na sessão principal (a da orquestradora), o
diretório do Bash persiste de uma chamada para a outra; um `cd` solto deixaria a orquestradora dentro do
worktree da trabalhadora, e o `git pull` seguinte rodaria na branch errada ou a remoção do worktree falharia.
`<worktree>` é o caminho absoluto que a orquestradora passou; numa sessão manual, é a pasta atual do worktree
(`pwd`).

```bash
(
cd "<worktree>" || exit 1
git diff --quiet origin/master...HEAD; rc=$?; [ "$rc" -eq 1 ] || { echo "diff vazio ou erro no git diff (rc=$rc)"; exit 1; }
ENTRADA="<scratchpad>/gate-sol-<N>-entrada.md"
cat > "$ENTRADA" <<'PEDIDO'
Revise este diff (FastAPI + SQLite no backend, React + TypeScript no frontend; dashboard de medições de obra pública). Objetivo da issue #<N>: <objetivo da issue em uma frase>. Procure bugs reais, nesta ordem: dinheiro (centavos, arredondamento, valor protocolado congelado, soma em dobro), estado da medição (transição inválida, estado mudado antes do ato externo dar certo), concorrência e envio duplicado de e-mail, auth e permissão por perfil, migração de banco destrutiva ou não idempotente, texto em inglês ou código interno na tela. Responda em português. Liste os achados por gravidade (Crítico, Aviso, Sugestão), cada um com arquivo:linha, o cenário concreto de falha e a correção. Sem achados, responda OK.

DIFF:
PEDIDO
git diff origin/master...HEAD >> "$ENTRADA" || { echo "git diff falhou"; exit 1; }
rm -f "<scratchpad>/gate-sol-<N>.md"
codex exec -m gpt-5.6-sol -o "<scratchpad>/gate-sol-<N>.md" - < "$ENTRADA" > "<scratchpad>/gate-sol-<N>.log" 2>&1 || { echo "codex falhou:"; tail -n 20 "<scratchpad>/gate-sol-<N>.log"; exit 1; }
)
```

- `<N>` é o número da issue; `<scratchpad>` é a pasta temporária da sessão. O `-o` guarda só a resposta final;
  o `-` manda o codex ler o prompt (pedido + diff) do stdin, que aqui vem do arquivo de entrada.
- A saída do codex (stdout e stderr) vai para `<scratchpad>/gate-sol-<N>.log`, e o `codex falhou:` mostra o
  fim dele: é lá que aparece o "usage limit" (ver "Sem cota", abaixo).
- Depois de rodar, **ler o arquivo do `-o`** (`<scratchpad>/gate-sol-<N>.md`). Ausente, vazio, ou sem "OK" nem
  lista de achados: veredito inválido; rodar de novo uma vez (antes, olhar o `.log`: se for "usage limit",
  é o caso "Sem cota", abaixo, e rodar de novo não adianta).
- Ajuste o foco do prompt ao risco da issue (ex.: `risco:envio` → "e-mail que sai duas vezes, estado gravado
  antes de o Graph aceitar"), como foi feito nos gates dos blocos 1 a 8.
- Diff grande demora: rodar com `timeout` de 600000 ms ou em segundo plano.

## Sem cota ("usage limit")

O codex usa a cota da assinatura ChatGPT do Leo. Se a saída (o `codex falhou:` do comando, o `.log` ou o arquivo do `-o`) trouxer
"usage limit" (ou "limite de uso"), **não é veredito inválido e rodar de novo no mesmo dia não adianta**.
Não insistir e não esperar a cota voltar: o gate passa a ser feito por um **subagente Opus independente**, e a
orquestradora dá o veredito final.

1. Abrir um `Agent` com `model: opus`, `subagent_type` geral, ferramentas só de leitura (Read, Grep, Glob e Bash
   sem gravar). O prompt é o **mesmo arquivo de entrada** que iria ao codex (pedido desta skill + o diff de
   `origin/master...HEAD` do worktree), **sem** o parecer do `revisor-adversarial` e sem a conversa da
   trabalhadora: é um par de olhos novo. Nenhum subagente roda em outro modelo.
2. A orquestradora confere cada achado contra o código e registra o veredito: confirmado, ou refutado com
   `arquivo:linha` que prova. Depois desse veredito **não há nova rodada do gate** (nem Opus de novo, nem codex
   quando a cota voltar).
3. Achado confirmado (Crítico ou Aviso): uma rodada única de correção pela trabalhadora, conferida só pelo
   `revisor-adversarial` sobre o diff novo. A PR segue e o auto-merge liga normalmente quando as outras travas passam.
4. Registrar em `## Gates` da PR:

```
- [x] Gate Sol: codex sem cota em DD/MM; coberto por subagente Opus independente + veredito da orquestradora
```

Na nuvem (sem codex) vale a regra de sempre: "gate Sol: não disponível na nuvem", que não é trava.

## Depois da resposta: uma rodada de correção

1. Conferir **cada** achado contra o código antes de aceitar (rigor antes de concordância). Três destinos:
   - **corrigido**: o defeito existe; corrigir com teste que falha sem a correção;
   - **refutado**: o defeito não existe; anotar o motivo com `arquivo:linha` que prova (ex.: "validade < emissão
     já recusada em `api_documentos.py:89`");
   - **registrado**: existe mas está fora do escopo da issue; vira linha em `docs/backlog.md` ou issue nova
     sugerida no corpo da PR.
2. Uma rodada só: corrigir, rodar os testes do módulo, e não rodar o gate de novo, a menos que a correção tenha
   mudado a lógica de dinheiro ou de envio de forma grande; nesse caso, uma segunda rodada só sobre o diff novo.

## Registrar na PR

Na seção `## Gates` do corpo da PR (modelo em `.github/pull_request_template.md`):

```
- [x] Gate Sol: N achados, M corrigidos, K refutados com motivo
  - S1 (Crítico) arquivo:linha — corrigido: ...
  - S2 (Aviso) arquivo:linha — refutado: ...
```

N = M + K + registrados. Se houver registrados, dizer onde (linha do backlog ou issue sugerida).
