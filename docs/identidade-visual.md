# Identidade visual

O que o sistema é visualmente e por quê. As instruções para quem mexe em tela estão em `.claude/rules/frontend.md`;
os valores estão em `frontend/src/tokens.css`, e este arquivo não os repete. Os termos (situação, selo, casca,
painel) estão no `GLOSSARY.md`.

A fundação foi escolhida pelo dono em 15/11/2026, componente a componente, na tela Início; a organização da página
da medição, em 16/11/2026, bloco a bloco (#717). Essas duas telas são a referência: onde outra tela divergir delas,
valem elas.

## Ideia

- **O sistema parece da empresa.** A marca (laranja, preto e branco) é a inspiração e o símbolo é o L dela. Motivo:
  antes o sistema tinha cores próprias e cada tela uma execução diferente (decisão do dono, #717).
- **Papel, tinta e régua.** Fundo claro e quente (o papel), texto quase preto (a tinta), linhas pretas que separam
  os grupos, cantos retos. Lembra um formulário de obra impresso, e deixa a cor livre para dizer situação.
- **Tabela e número em primeiro plano.** A pessoa abre a tela para comparar valores; o desenho não disputa com eles.
- **Um modo só, claro.** Não há tema escuro.

## Cor

- **A cor da marca nunca indica situação nem ação.** O laranja aparece em três lugares: o bloco do símbolo L, o
  ícone do item ativo do menu e o contorno de foco dentro do menu. Motivo: laranja fica entre o amarelo de "vence em
  breve" e o vermelho de "crítico"; se pintasse botão ou aviso, seria lido como alerta (decisão do dono, #717;
  PR #723). Um teste confere que `--cor-marca` não aparece em nenhuma outra regra (`pecasBase.test.tsx`).
- **Ação é tinta.** O botão principal é preto cheio; o secundário tem a borda grossa preta. Link tem a cor do texto
  em volta e é sublinhado. Motivo: sobra uma cor só para o que pede atenção, a da situação (PR #725).
- **Valor que se compara leva cor e forma; o que não se compara fica em tinta.** Valor de contrato, data e número
  de documento são tinta. O valor que tem etapa, variação, diferença, andamento ou tempo parado diz isso por uma
  das cinco famílias da seção "Valores". Percentual executado continua número, não situação: 14% executado não é
  "feito", e fica em tinta (PR #776). Motivo: com todo número em preto não dava para saber se o faturamento ou a
  medição protocolada estava melhor ou pior que no mês passado, nem ver a diferença entre o aprovado e o pedido
  (decisão do dono de 18/11/2026, #805). Antes a regra era "número e data são tinta por padrão".
- **Superfície igual ao papel.** O painel tem o mesmo fundo da página e se separa pela moldura e pela sombra.
- **Etapas do ciclo e previsão têm tons próprios**, que não são situação: do azul claro (em análise) ao azul escuro
  (protocolado), verde no recebido; a previsão vai da tinta (neste mês) ao cinza claro (sem previsão). O atrasado é
  sempre o tom do crítico, com a marca "!" (decisão 3 da Início; PR #729). Os tons claros têm pouco contraste com o
  papel, por isso cada célula e cada faixa tem rótulo escrito ou nome para leitor de tela.

## As quatro situações

| Situação | Cor | Forma (o glifo) | Quer dizer |
|---|---|---|---|
| Feito | verde | círculo cheio com visto | aconteceu e não pede mais nada: recebida, anexada, em dia |
| Em andamento | azul | círculo meio cheio | está em curso e dentro do esperado |
| Vence em breve | amarelo | triângulo com exclamação | ainda não venceu, falta sem travar, ou se acompanha |
| Crítico | vermelho | octógono com exclamação | venceu, diverge, falhou, trava ou pede ação agora |

- **Toda situação aparece com cor e forma.** Motivo: quem não distingue as cores, ou lê numa impressão em preto e
  branco, ainda sabe a situação; e o amarelo sozinho quase não se vê sobre o papel (decisão do dono, #717; decisão 2
  da Início; PR #725).
- **A forma sai da situação, nunca da tela.** A mesma situação tem a mesma cara em qualquer lugar: selo, contador,
  legenda, célula e aviso usam o mesmo glifo.
- **O que não tem situação fica em tinta, sem marca.** Estado comum ("Ativo", "Entrou") é só a palavra; a exceção é
  que leva selo. Obra em dia não leva selo na lista. Motivo: marca em tudo deixa de chamar atenção (PRs #776, #781).
- **Cancelada e desistida** ficam neutras e riscadas, sem glifo.

### Quando usar cada uma

- **Pela data:** vencido é crítico; o que ainda vai vencer é vence em breve, em qualquer prazo. Vale para certidão,
  garantia e aviso da agenda. Garantia vencida leva o octógono; garantia a vencer leva o triângulo, falte um dia ou
  sessenta. Motivo: é a mesma leitura das certidões na mesma tela, e antes a garantia a 15 dias dividia a forma com
  a vencida (PR #781). O que vence depois de 30 dias na agenda fica neutro: ainda não pede nada (PR #772).
- **Pelo nível do aviso (Crítico × Ação × Atenção):** a forma diz se o aviso já pede ação. Crítico e Ação levam o
  octógono; Atenção, que se acompanha, leva o triângulo. A palavra separa o Crítico da Ação. Vale para os avisos da
  obra e para o farol da lista de Obras e do QDOP. Motivo: o servidor já trata Crítico e Ação como os níveis
  imediatos, e antes a forma não separava "agir agora" de "acompanhar" (PR #781).
- **Em curso é em andamento, não feito nem alerta.** "Recebido em parte", "Aguardando o órgão", "em aberto", "paga
  em parte", "Pronto" e "Completo" antes do envio, aditivo em andamento, medição provisória: todos em andamento.
  Motivo: pronto para enviar ainda não é enviado, e esperar o órgão dentro do prazo não é alerta (PRs #739, #776).
- **Falta que trava é crítico; falta que não trava é vence em breve.** Certidão vencida ou item que o servidor
  marca como bloqueio é crítico; documento que falta sem impedir o envio é o triângulo (PR #739).
- **Tempo parado** (SIGA): andou hoje é feito; menos de 5 dias úteis, em andamento; 5 ou mais, vence em breve; 10 ou
  mais, crítico (PR #771). A leitura é do servidor, e "parado", na faixa de números e no cabeçalho do painel, é só o
  crítico (#805).
- **Não lido** (SIGA): o processo que o robô não leu na última rodada leva a etiqueta no tom de "vence em breve":
  falta sem travar, e se acompanha (#805).

### Aviso, trava, falha e justificativa

Quatro caixas que se distinguem de relance (decisões 4, 10 e 17 da página da medição; PRs #725, #739):

- **Trava:** bloco vermelho cheio, texto claro, sinal de proibido. A ação está impedida e o botão dela fica
  desligado. O motivo escrito de um botão desligado também aparece assim (PR #773).
- **Crítico que não trava:** faixa vermelha clara com o octógono (nota que diverge, certidão vencida).
- **Atenção ou confirmação:** faixa amarela com o triângulo. A ação segue e o botão continua ativo.
- **Justificativa:** caixa de moldura grossa preta com o campo obrigatório dentro, junto do botão que a exige.
- **Falha** (de leitura ou de ação) é sempre a faixa de crítico com o octógono. Motivo: o triângulo é a forma de
  "vence em breve", e uma falha com triângulo se confundiria com aviso de prazo (PRs #773, #781).

## Valores

Cinco famílias dizem o que um valor é e como ele vai. Decisão do dono de 18/11/2026 (#805): os avisos tinham
categorização por cor e forma, e os números não. O número continua em tinta; a família aparece na marca ao lado
do rótulo, na etiqueta sob o valor ou na barra.

| Família | Responde | Forma | Peça |
|---|---|---|---|
| Etapa do dinheiro | o que o valor é | quadradinho no tom da etapa, ao lado do rótulo | `MarcaEtapa` |
| Variação | está melhor ou pior que antes | seta para cima, seta para baixo ou ponto, com o percentual e a referência | `Variacao` |
| Diferença | quanto dois valores que deveriam ser iguais se afastam | sinal de igual, ou a diferença em reais e em percentual | `Diferenca` |
| Andamento | o ritmo contra o necessário para o prazo | barra com um risco preto no necessário, e a palavra | `Andamento` |
| Tempo parado | há quantos dias está numa etapa ou num setor | o selo da situação | `Selo` |

- **Valor não é situação.** As formas das famílias (seta, ponto, sinal de igual, barra) são outras que as dos
  quatro glifos, de propósito: a seta para cima não pode ser lida como o triângulo de "vence em breve".
- **Não há cor nova.** Melhor é o verde do feito, pior é o vermelho do crítico, atenção é o amarelo de "vence em
  breve", e o estável é neutro. Motivo: "melhor" e "pior" se leem como "feito" e "crítico", e uma segunda paleta
  disputaria com a das situações. A cor da marca continua fora.
- **A conta é do servidor.** A referência da variação e os dois lados da diferença chegam prontos, com a mesma
  definição do número; a tela só desenha. Sem referência, nada aparece.

### Quando usar cada uma

- **Etapa do dinheiro:** em análise, boletim, nota, protocolado e recebido, nos tons que a Início já usa. A marca
  acompanha o rótulo e o cabeçalho da coluna. O aprovado é o valor do boletim e leva a marca dele. O em aberto não é
  etapa do ciclo: leva um triângulo no tom de "vence em breve", e o valor dele sai nesse tom. O medido junta etapas
  (o aprovado e, sem boletim, o pedido) e fica sem marca.
- **Variação:** só contra uma referência escrita ao lado ("× set", "× out/25"). A seta diz a direção e a cor diz
  se é bom: no em aberto, cair é bom. Até 2% para cima ou para baixo é estável. O mês em curso compara com o mês
  anterior até o mesmo dia, e o rótulo diz ("× out até o dia 18"). Motivo: mês pela metade contra mês inteiro diria
  sempre "caiu". O valor de uma etapa do ciclo (o protocolado, o recebido de uma competência) compara com a mesma
  altura do mês anterior: o que a competência anterior tinha na etapa no mesmo dia, um mês antes ("× set até
  18/10"). Sai das datas dos eventos; faltando a data de algum, a variação não aparece. Período sem valor, ou anterior ao primeiro ano que as telas da diretoria contam, não serve de
  referência.
- **Diferença:** entre dois valores que deveriam ser iguais (o aprovado e o pedido). Igual leva o sinal de igual.
  Diferente mostra os reais e o percentual: até 0,5% da base, no tom de "vence em breve"; acima, no tom do crítico.
  É o limite do aviso "aprovado abaixo do pedido" (#741), um número só no sistema. Só entre medições que têm os
  dois valores: medição em análise não é diferença, é etapa não alcançada, e pintá-la de vermelho enganaria quem lê.
  Falta de nota ou de pagamento também não é diferença de valor. Na linha que soma (mês, obra, ano) a diferença é
  só o corte: o que ficou abaixo do pedido, sobre o pedido de todas as medições comparadas. O aprovado acima do
  pedido aparece só na linha da medição, escrito ("+ R$ … acima do pedido") e sempre no tom de "vence em breve":
  quase sempre é o pedido gravado errado, e somado no mês anulava o corte de outra obra. Até R$ 0,05 por medição é
  arredondamento do órgão e conta como igual (decisão do dono de 10/11/2026).
- **Andamento:** a partir de 100% do necessário, "Adiantada", no tom do feito; de 70% a 99%, "Atenção", no tom de
  "vence em breve"; abaixo de 70%, "Devagar", no tom do crítico. Sem necessário ou sem ritmo, nada aparece.
  A contagem de obras por leitura ("3 devagar", "2 em atenção") vai numa etiqueta do tom da leitura, sem glifo:
  é valor, não situação (#805).
- **Tempo parado:** os dias numa etapa ou num setor, com o selo da situação e os limites do SIGA (seção "Quando
  usar cada uma" das situações). Na medição, são os dias úteis desde o evento que abriu o passo da vez. No passo
  Pagamento a régua é o prazo do órgão (`docs/adr/0007`): crítico só depois da data esperada do recebimento; antes
  dela, ou sem prazo, em andamento. Motivo: o órgão leva semanas para pagar, e dez dias úteis de espera não são
  atraso (#805). A leitura é uma só, do servidor: a mesma medição tem o mesmo selo na fila de trabalho e no cartão
  do Resumo das medições. A recebida não está parada: leva o selo do feito com a data.
- **Fica em tinta:** valor de contrato, data, número de documento e o próprio número ao lado da marca ou da
  etiqueta.

## Letras e tamanhos

- **Uma família, Archivo**, no texto, nos números e nos títulos, mudando só a largura: texto na largura normal,
  valores em reais um pouco estreitos, títulos condensados. Barlow só no nome da marca ao lado do símbolo. Servidas
  pelo próprio sistema, sem serviço externo (decisões 4 e 5 da Início; PR #723).
- **Títulos condensados e pesados.** Os de bloco e de painel em caixa-alta; o da página, não.
- **Corpo em 16 px; célula de tabela em 14 px.** Motivo do 14: tabela de 7 a 9 colunas tem de caber em 792 px, que é
  o que sobra a 1024 com o menu aberto. Rótulo de apoio, selo, contador e legenda também em 14; mês, ano e nome de
  grupo na grade em 12 (PR #781).
- **A escala é fechada:** 12, 14, 16, 19,2, 23, 27,6 e 33,2 px (mais os 22 do nome da marca). Tamanho fora dela não
  existe; só os valores grandes da Início e do Pagamento variam com a largura do painel, entre dois passos da escala
  (PRs #724, #729).
- **Valor e data com algarismos de mesma largura**, alinhados à direita nas tabelas, para a coluna não dançar.

## Formas

- **Cantos retos em tudo.** A única forma redonda é o avatar (decisão 6 da Início; PRs #723, #781).
- **Régua de grupo:** linha preta de 2 px acima do título de um grupo de blocos e no alto da página. **Régua de
  seção:** linha preta de 1 px sob o cabeçalho da tabela, acima de subtítulo dentro de painel e na base de gráfico.
  Linhas de uma tabela se separam por um fio cinza, sem zebra.
- **Cabeçalho de grupo forte:** faixa de tinta cheia com a letra clara, que abre um grupo de linhas de tabela ou um
  bloco (o contratante, em Obras e no quadro do mês; quem tem de agir, na fila de trabalho; a categoria, no SIGA),
  com o subtotal do grupo nas colunas. Motivo: na linha cinza o contratante sumia
  entre as obras, e a página parecia uma lista só (decisão do dono de 18/11/2026, #805).
- **Borda do tempo parado:** no SIGA, a borda esquerda da linha leva a cor da situação do tempo no setor, a mesma
  do selo da linha; o encerrado não leva. Motivo: com tudo em tinta não dava para ver o que estava travado antes de
  ler (decisão do dono de 18/11/2026, #805).
- **Barra de passos:** o fluxo da medição de uma obra em miniatura, na linha da tabela: um segmento por passo que
  a obra tem, os feitos no tom do feito, o da vez no tom do em andamento e os que faltam no papel escuro, com o nome
  do passo da vez e a posição escritos ("Espelhos · 3 de 5"). Motivo: na fila de trabalho a linha diz onde a
  medição está sem abrir a matriz (decisão do dono de 18/11/2026, #805).
- **Painel:** moldura preta de 2 px e sombra dura (deslocada 8 px, sem desfoque), com o título dentro e sem régua
  embaixo dele. A janela de diálogo é um painel por cima de um véu; menu suspenso, lista de sugestões e a janela do
  e-mail levam a mesma sombra, e não há sombra com desfoque. Motivo: a moldura separa o painel do papel sem
  mudar a cor do fundo (decisão 6 da Início; PRs #725, #772).
- **Quadro por etapa:** uma coluna por etapa do ciclo, com a barra no tom dela, a marca, a quantidade e o valor no
  cabeçalho, e um cartão por medição embaixo, o de maior valor primeiro. Coluna vazia diz "nenhuma medição". É a
  forma do Resumo das medições, que responde "onde está o dinheiro do mês"; a tabela continua como segunda vista,
  para comparar valores entre linhas (decisão do dono de 18/11/2026, #805).
- **Cartão de medição:** moldura fina com a borda esquerda no tom da etapa; dentro, a obra, o contratante com a
  medição, o valor em tinta e as etiquetas das famílias de valor (o tempo parado e a diferença). Menor que o
  painel: sem título, sem sombra e sem a moldura grossa. Só no quadro por etapa.
- **Abas ficam direto na página, sem caixa em volta dos painéis da aba.** Motivo: caixa dentro de caixa perdia
  40 px de largura e cortava as tabelas da página da obra (PR #776).
- **Selo:** fundo claro da situação, glifo e palavra, com maiúscula inicial. **Contador:** a quantidade ao lado de
  um título; neutro sem glifo, com situação leva o glifo dela.

## Botões e campos

- **Duas alturas:** 40 px com a letra do corpo, e 32 px com a letra de apoio para botão dentro de linha de tabela.
  Motivo: havia oito combinações de altura e letra (PR #781). Exceção: o botão de enviar ao órgão, na página da
  medição, tem 52 px, como o dono montou.
- **Desligado:** fundo de papel escuro e texto apagado, também no principal e no de apagar. Motivo: tinta ou
  vermelho cheio com letra apagada continuaria dizendo "clique".
- **De apagar ou revogar:** vermelho cheio do crítico.
- **Campo:** borda fina cinza, cantos retos, 40 px. Com erro de validação, moldura grossa no tom do crítico.
- **Foco:** contorno preto de 2 px no conteúdo; laranja dentro do menu escuro.
- **Escolha entre opções** (filtro, vista, ano): fileira de botões de 40 px com moldura fina, a escolhida em tinta
  cheia. Uma forma só no Fechamento, no QDOP, no SIGA, em Documentos e na Reconciliação (PRs #771, #772).

## Casca e menu

A casca é o que fica igual em toda tela: o menu à esquerda e o topo (decisões 8, 9 e 10 da Início; PR #725).

- **Menu lateral escuro**, de 232 px, com o símbolo L e o nome da marca em dois pesos, um item por tela e o botão de
  recolher no pé. O item da tela atual tem fundo realçado, texto claro e forte e o ícone em laranja.
- **Recolhido** fica só a coluna dos ícones (64 px). A escolha é guardada no navegador.
- **Topo** de 56 px sobre o papel, com o título da tela e a conta (avatar redondo com as iniciais).
- **Página** com largura máxima de 1320 px e margem lateral de 32 px.

## Larguras

- **1440 px:** a disposição cheia. Na página da medição, a Linha do tempo fica ao lado do passo.
- **1024 px:** menu aberto e 792 px de conteúdo. A página não rola de lado. Colunas ao lado descem para baixo;
  tabela que não cabe rola dentro da própria caixa. O quadro por etapa vira uma etapa embaixo da outra, com os
  cartões lado a lado; no celular, um cartão embaixo do outro.
- **390 px (celular):** o menu nasce recolhido (64 px), abre por cima da tela e fecha ao navegar; no topo fica só o
  avatar. As telas de leitura da diretoria (Início, Obras, página da obra, Fechamento, Resumo das medições) são
  desenhadas para essa largura: uma coluna, e a tabela vira um bloco por linha. As telas de operação são de
  computador; no celular nada se sobrepõe, e o que não cabe rola dentro da área da tela.
- **Na Início e na página da medição, o bloco que muda de disposição mede o próprio painel**, não a janela, porque
  a largura útil depende de o menu estar aberto ou recolhido (PR #729).

## Tela de entrada

A única tela fora da casca (#821).

- **Duas metades iguais: a marca no lado escuro, o formulário no papel.** O lado escuro tem a cor do menu e só a
  marca: o símbolo L e o nome em dois pesos, as mesmas peças do menu, um em cima do outro. O símbolo cresce na
  proporção do menu e o nome vai no maior passo da escala de letra. Motivo: dois terços da tela eram um fundo preto
  com linhas finas, sem marca nem texto, e o formulário ficava num canto (decisão do dono de 18/11/2026, #805).
- **Nada se move.** O desenho animado saiu, com a biblioteca de 3D que só ele usava.
- **No celular** o formulário vem primeiro e a marca fica embaixo, no que sobra da altura.
