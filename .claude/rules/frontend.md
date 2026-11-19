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
| a etapa do dinheiro de um valor ou de uma coluna (em análise, boletim, nota, protocolado, recebido, em aberto) | `MarcaEtapa`, ao lado do rótulo |
| valor melhor ou pior que antes | `Variacao`, com a referência que o servidor manda e o rótulo dela ("set", "out/25") |
| dois valores que deveriam ser iguais (aprovado × pedido) | `Diferenca`, com o corte (`abaixo`), a base e o limite que o servidor manda; o `acima` só na linha da medição, nunca na que soma |
| ritmo da obra contra o necessário | `Andamento`, com a `leitura` que o servidor manda (palavra, percentual, limites ou o motivo de a obra ficar fora da régua); a tela não compara o ritmo com o necessário. `detalhe="percentual"` é o padrão, `"valores"` escreve "R$ x/mês de R$ y" onde a tabela não tem coluna para eles, `"palavra"` onde o percentual e os valores já estão em colunas |
| quantas obras estão devagar ou em atenção | a etiqueta do tom da leitura, sem glifo (`.obras-etiqueta`); a contagem usa `andamentoDaObra` (`listaObras.ts`), a mesma régua da peça `Andamento` |
| o fluxo da medição de uma obra numa linha de tabela (feitos, o da vez, os que faltam) | `BarraDePassos`, com os passos que o servidor manda; a barra com data e clique é a da página da medição (`Passos`) |
| há quantos dias úteis uma medição está no passo da vez | `TempoParado`, com o `parada` que o servidor manda (dias, situação e, no Pagamento, o prazo do órgão); em cartão, com `frase` |
| há quanto tempo um processo do SIGA está no setor | o `Selo` da situação que o servidor leu; na tabela em que o tempo é a pergunta da tela (SIGA), a borda esquerda da linha leva a mesma cor |
| abrir um grupo de linhas ou um bloco (contratante, quem tem de agir, categoria) | o cabeçalho de grupo forte: faixa de tinta cheia com a letra clara, o nome à esquerda e a contagem à direita; o subtotal do grupo nas colunas, quando a tabela tem valores; o que está parado ou atrasado no grupo vai no `Selo`, dentro da faixa |
| onde está o dinheiro de um conjunto de medições, por etapa | o quadro por etapa (`ResumoQuadro`) e o cartão de medição (`CartaoDaMedicao`); para comparar valores entre linhas, a tabela |
| falha de leitura ou de ação | `Falha` |
| ação impedida, ou motivo de botão desligado | `CaixaAviso nivel="trava"`, com o botão desligado ao lado |
| algo venceu, diverge ou passou do limite, sem impedir | `CaixaAviso nivel="critico"` |
| pede confirmação ou atenção, e a ação segue | `CaixaAviso nivel="atencao"` |
| justificativa obrigatória | `CaixaJustificativa`, junto do botão que a exige |
| formulário ou ação fora do fluxo da página | `Janela` |
| bloco com título | painel (`.cartao`) |
| lista de valores | `.tabela` dentro de `.tabela-wrap`; valor em `.col-num` |
| escolha entre opções (filtro, ano) | `.escolha` dentro de `.escolhas`; a quantidade em `.escolha__n` |
| vistas de uma página, cada uma com endereço (abas) | `.aba` dentro de `nav.abas`, como link, com `aria-current="page"` |
| dizer onde a página está (o caminho no alto) | nada na página: a casca desenha o `Caminho` na barra do topo. A página que carrega um objeto só diz o nome dele com `useNomesDoCaminho` (`nomesDoCaminho.ts`); o caminho de uma rota nova entra em `trechosDe` (`navegacao.ts`) |
| voltar para a tela de onde se veio | `VoltarOrigem` (`Topo.tsx`), só quando ela não é um trecho do caminho (`temOrigem`) |
| botão | `button`/`.btn` (40 px); `.btn--primario` para a ação principal; `.btn--pequeno` (32 px) em linha de tabela; `.btn--destrutivo` para apagar |

- **Situação: uma das quatro de `situacao.ts`** (feito, andamento, breve, critico), sempre com o glifo; ponto de cor
  sozinho não existe. Critério de qual usar: seção "Quando usar cada uma" de `docs/identidade-visual.md`. O que não
  tem situação fica em tinta, sem marca.
- **Valor que se compara não é situação: usa uma das famílias de valor** (seção "Valores" de
  `docs/identidade-visual.md`): etapa, variação, diferença, andamento ou tempo parado. O número fica em tinta e a
  família vai na marca, na etiqueta ou na barra; a referência e o limite vêm do servidor, a tela não os calcula.
  Valor de contrato, data e número de documento seguem em tinta.
- **Leitura de valor não contradiz a situação ao lado.** Na tabela que mostra o andamento e a situação da mesma
  obra, "Em dia" só aparece na obra sem aviso e sem andamento Devagar. A obra devagar e sem aviso leva o motivo do
  andamento na Situação, na etiqueta da família (sem selo e sem glifo), pela mesma régua da coluna
  (`listaObras.andamentoDaObra`). Aviso do farol ganha do andamento.
- **A casca desenha o caminho; a página não desenha trilha própria.** Motivo: antes, a obra, a medição, o
  contratante, a empresa e o histórico do SIGA desenhavam cada uma a sua, com três marcações diferentes.

## Comportamento

- **Português** em rótulo, erro e confirmação ("Nota enviada às HH:MM."). Erro mostra o que aconteceu em palavras
  da pessoa: código interno, nome de exceção e "Failed to fetch" ficam fora da tela.
- **Quem só consulta** (diretoria) não vê botão de escrita; o 403 vira "Seu perfil só consulta esta tela…".
- **Filtro de uma mesma lista vai na busca do endereço** (`?categoria=aditivos`, `?familia=nota`), com `.escolha` e a
  quantidade em `.escolha__n`; vista diferente da tela vai no caminho (`/medicoes/quadro`), com `.aba`. A opção sem
  item continua na fileira, com zero.
- **Linha clicável com link dentro:** o clique no link leva ao destino do link e não dispara a ação da linha.
- **Página em abas: a aba vai no caminho, o filtro na busca.** A aba padrão não entra no endereço (`/fechamento`,
  `/fechamento/contratantes`); o que a pessoa escolhe dentro da aba (ano, contratante, mês) vai na busca
  (`?ano=2025`) e acompanha a troca de aba.
- **O painel da aba não repete o nome da aba como título.** O nome vai no `aria-label` da seção. Motivo: a 1440 px
  o título repetido custava 41 px por aba, e o Fechamento de doze meses passava de uma tela e meia.
- **Número que é porta continua com cara de número.** O valor que leva à página que o explica é um link sem
  sublinhado em repouso; o sublinhado aparece ao passar o mouse e ao receber o foco. Nome (obra, contratante) que é
  link fica sublinhado. Motivo: o dono aprovou a aparência dos números; a porta não pode mudá-la.
- **Link para página que ainda não tem rota vai pelo endereço escrito**, navegando pelo roteador (`irHref`), e a peça
  que cria a rota não precisa voltar à tela que aponta para ela.
- **Página nova entra em quatro lugares, e só neles:** o tipo `Rota`, `parseRota` e `caminhoDe` (`rota.tsx`); a área
  dela em `AREAS` e o recorte em `RECORTE_DA_PAGINA` (`navegacao.ts`), se for item do menu; a linha em `App.tsx`; e a
  tela em `scripts/prova/telas.mjs`. Página nova no menu herda o recorte de uma tela que o perfil já via, ou a issue
  diz que o perfil ganhou a tela. Motivo: o teste "nenhum perfil ganhou tela com as áreas" (`navegacao.test.ts`) só
  protege se o recorte de cada página nova for declarado.
- **Largura.** A 1024 px a página não rola de lado; tabela larga rola dentro da própria caixa. Celular (390 px) é
  requisito nas telas de leitura da diretoria: Início, Obras, página da obra, Fechamento e Resumo das medições; nelas
  a tabela vira um bloco por linha. As telas de operação são de computador, mas a 390 px nada se sobrepõe.
  A barra do topo cresce quando o caminho não cabe numa linha; nada nela é cortado com reticências. Peça nova no
  topo não pode tirar a largura do caminho a 390 px: desce para a linha de baixo ou vira botão.
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
