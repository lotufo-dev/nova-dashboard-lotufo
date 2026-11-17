---
paths:
  - "frontend/src/**"
  - "frontend/public/**"
---

# Frontend (React 18 + Vite + TypeScript strict)

O porquê de cada regra visual está em `docs/identidade-visual.md`. A referência são a Início e a página da medição,
montadas pelo dono: onde outra tela divergir delas, valem elas.

## Antes de desenhar

- **Comece pela pergunta que a tela responde** e pela informação que ela mostra. Tela nova ou redesenho parte da
  decisão do dono registrada na issue, com a imagem aprovada anexa quando existir. Ajuste pequeno segue direto.
- **Há comparação de valores entre linhas? Use tabela, não cartões.** Cartão por item esconde a coluna que a pessoa
  quer correr com o olho.
- **Número que aparece em duas telas tem uma definição só**, calculada no backend (`.claude/rules/paineis.md`). Se a
  conta é outra, o rótulo é outro e a diferença fica registrada (ADR ou `docs/backlog.md`).
- **Texto na tela** segue `.claude/rules/texto-na-tela.md`; os termos são os do `GLOSSARY.md`.

## Variáveis e peças

- **Cor, família, tamanho de letra e raio só por `var(--…)` de `src/tokens.css`.** Faltou um valor: ele nasce no
  `:root` de `tokens.css`, com nome pelo papel, e a PR diz por quê. `literais.test.ts` reprova cor, família e tamanho
  de letra escritos em `.css` e em estilo de `.tsx`; a auditoria da prova das telas (`scripts/prova/auditoria.mjs`)
  acusa letra fora da escala e canto arredondado.
- **`--cor-marca` (o laranja) não entra em regra de tela.** Nunca é situação nem ação; `pecasBase.test.tsx` reprova.
- **Cantos retos.** Só o avatar é redondo.
- **Use a peça de base; não escreva outra com a mesma função:**

| Para… | Use |
|---|---|
| situação de uma linha (prazo, documento, medição) | `Selo` com `situacao`; sem situação, `Selo` neutro ou só o texto |
| o símbolo da situação solto (célula, lista) | `Glifo` (`Selo.tsx`) |
| quantidade ao lado de um título | `Contador` |
| explicar as situações que a tela usa | `LegendaCor` |
| falha de leitura ou de ação | `Falha` |
| ação impedida, ou motivo de botão desligado | `CaixaAviso nivel="trava"`, com o botão desligado ao lado |
| algo venceu, diverge ou passou do limite, sem impedir | `CaixaAviso nivel="critico"` |
| pede confirmação ou atenção, e a ação segue | `CaixaAviso nivel="atencao"` |
| justificativa obrigatória | `CaixaJustificativa`, junto do botão que a exige |
| formulário ou ação fora do fluxo da página | `Janela` |
| bloco com título | painel (`.cartao`) |
| lista de valores | `.tabela` dentro de `.tabela-wrap`; valor em `.col-num` |
| escolha entre opções (filtro, vista, ano) | `.escolha` dentro de `.escolhas`; a quantidade em `.escolha__n` |
| botão | `button`/`.btn` (40 px); `.btn--primario` para a ação principal; `.btn--pequeno` (32 px) em linha de tabela; `.btn--destrutivo` para apagar |

- **Situação: uma das quatro de `situacao.ts`** (feito, andamento, breve, critico), sempre com o glifo; ponto de cor
  sozinho não existe. Critério de qual usar: seção "Quando usar cada uma" de `docs/identidade-visual.md`. O que não
  tem situação fica em tinta, sem marca.

## Comportamento

- **Português** em rótulo, erro e confirmação ("Nota enviada às HH:MM."). Erro mostra o que aconteceu em palavras
  da pessoa: código interno, nome de exceção e "Failed to fetch" ficam fora da tela.
- **Quem só consulta** (diretoria) não vê botão de escrita; o 403 vira "Seu perfil só consulta esta tela…".
- **Largura.** A 1024 px a página não rola de lado; tabela larga rola dentro da própria caixa. Celular (390 px) é
  requisito nas telas de leitura da diretoria: Início, Obras, página da obra, Fechamento e Resumo das medições; nelas
  a tabela vira um bloco por linha. As telas de operação são de computador, mas a 390 px nada se sobrepõe.
- **Acessibilidade mínima:** foco visível, teclado, `aria-live` em confirmação, tabela `sr-only` para gráfico. O
  glifo é decorativo: a palavra ao lado (ou um texto `sr-only`) diz a situação.
- Teste ao lado do componente (`X.test.tsx`, vitest + jsdom).

## Antes de abrir PR de tela

1. `cd frontend && npm test && npm run typecheck && npm run lint`.
2. `python3 scripts/prova/ponta_a_ponta.py --larguras 1440,1024,390 --capturas todas --pasta <pasta fora do repositório>`:
   abre cada tela e estado de `scripts/prova/telas.mjs` com os três perfis nas três larguras. Reprova com erro de
   console, resposta 4xx/5xx, tela em branco ou rolagem lateral. Sem opções, roda só a 1440, como a CI.
3. Leia os avisos da auditoria no fim da saída (texto cortado, fora da vista ou sobreposto, letra e canto fora da
   fundação) e olhe as capturas da tela que mudou, nas três larguras. Aviso não reprova: corrija ou explique na PR.
4. Tela ou estado que a prova não abre (janela, formulário, vazio, erro): acrescente em `scripts/prova/telas.mjs`,
   com resposta simulada de dado fictício em `simulados.mjs` se o cadastro de exemplo não chega lá.
5. Na PR, em "Suposições", cada decisão de desenho tomada sem pergunta, com o motivo.
