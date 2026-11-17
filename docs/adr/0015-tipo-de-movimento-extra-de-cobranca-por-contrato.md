# Tipo de movimento extra de cobrança é declarado por contrato, no cadastro

O RM classifica cada nota por um tipo de movimento, e desde a #563 o sistema só trata como cobrança ao órgão a
nota de quatro tipos, os mesmos em toda obra (a lista geral: `2.2.01`, `2.2.02`, `2.2.07` e `2.2.16`). Só essa
nota entra no faturado do RM e no a receber, liga-se sozinha à medição e deixa a medição ser recebida pela baixa.

Em Deciolândia, obra com o contrato em nome do consórcio, a nota que a empresa emite contra o órgão pela cota
dela era de um tipo da lista geral. Em 09/2026 o faturamento passou todas para o tipo `2.2.03`, e elas deixaram
de ser cobrança para o sistema sem que ninguém tivesse decidido isso: não se ligam mais sozinhas à medição e saem
do protocolado e do recebido da página Fechamento (branch `redesenho`). No a receber e no faturado do RM elas
nunca estiveram, nem antes nem depois da reclassificação: ali só conta a nota da coligada da entidade do
contrato, e a empresa é outra coligada. Pôr o `2.2.03` na lista geral não serve: nas outras obras ele é usado em
notas que não cobram o órgão (entre empresas do grupo, da empresa contra o próprio consórcio), e são centenas.

Em 17/11/2026 o dono decidiu: o `2.2.03` é cobrança só nessa obra. A regra geral que sai daí: **o contrato
declara, no cadastro versionado, os tipos de movimento que só nele também são cobrança ao órgão**
(`tipos_cobranca_extras_rm`, vazio por padrão). A lista geral continua como está, e tipo novo só entra nela por
decisão.

Uma função só responde "esta nota, atribuída a este contrato, é cobrança?": `cobranca_orgao.e_cobranca`, com a
lista geral e os tipos extras do contrato. A nota chega ao contrato pela medição a que está ligada (o vínculo) e,
sem vínculo, pelo centro de custo do contrato; no consórcio sem centro de custo, pela coligada. Nota que não cai
em contrato nenhum só é cobrança pela lista geral.

Ficaram de fora: pôr o tipo na lista geral (contaria as notas das outras obras) e marcar nota a nota pela correção
de cadastro (cada nota nova pediria um ato de alguém, e a regra é do dono, em arquivo).

## Antes de declarar o tipo: as notas gêmeas

A reclassificação não troca o tipo da nota que o sistema já tem. O RM passa a devolver outro movimento, com o
mesmo número, a mesma emissão e o mesmo valor, no tipo novo, e o movimento antigo vem cancelado ou só deixa de
vir. Cancelado, o vínculo dele é desfeito e, com a chave, a nota nova liga à medição e recebe pela baixa. Quando
só deixa de vir, a nota antiga continua ativa no banco e ligada à medição, e a nova fica solta: declarado o tipo,
as duas contam, e o faturado e o a receber da obra saem em dobro sem que tela nenhuma acuse.

Por isso declarar um tipo extra é travado enquanto houver esse par. O `cadastro aplicar`, no ensaio e para valer,
procura, na obra que está ganhando o tipo, as notas ativas gêmeas (mesma coligada, mesmo número, mesma emissão e
mesmo valor, em movimentos diferentes; uma de tipo da lista geral e a outra do tipo declarado; as duas contando)
e recusa o cadastro inteiro, dizendo quais são. O passo de quem declara:

1. rodar `cadastro aplicar --ensaio`;
2. para cada par listado, tirar da conta a nota de tipo da lista geral, pela correção de cadastro: `desligar_nf`
   se ela estiver ligada a uma medição e `desconsiderar_nf` pelo idmov;
3. aplicar de novo. Na sincronização seguinte a nota nova liga à medição.

A trava é do ato de declarar. O par que aparece depois, numa obra que já declara o tipo, não é conferido: a nota
e o título que deixam de vir do RM e continuam ativos no banco são assunto da #755 (título excluído no RM
continua contando na nota).

## Consequências

- O mesmo tipo em nota de outra obra, ou em nota sem obra, continua fora do a receber, do faturado, do vínculo
  automático e do recebimento pela baixa.
- Onde a nota ainda não tem contrato (o vínculo automático escolhendo a medição, a conciliação do histórico), a
  nota de tipo extra só é candidata às medições dos contratos que declaram o tipo. O centro de custo de outra obra
  não a leva para lá, e ela só concorre com outra nota pela mesma saída do espelho na obra que declara o tipo. As
  provas do vínculo (`docs/adr/0005`) valem igual.
- A chave não muda a regra da coligada. O a receber, o faturado e o recebido do RM e o recebimento pela baixa
  continuam só com a nota da coligada da entidade do contrato. No contrato em nome do consórcio, a nota da
  própria empresa, de tipo extra ou não, fica fora dessas contas com ou sem a chave. Para ela a chave vale no
  vínculo automático (pela saída do espelho), na nota repetida e na página Fechamento. Em obra
  da própria empresa e na fatura do próprio consórcio, a chave vale em tudo.
- A sincronização com o RM traz toda nota `2.2.NN` e os títulos dela, com ou sem a chave. O tipo decide o que
  conta, não o que entra no banco: declarar o tipo vale também para as notas já sincronizadas.
- Ao aplicar o cadastro com a chave, o vínculo automático antigo de nota desse tipo, da coligada da entidade do
  contrato, deixa de segurar a medição: na sincronização seguinte ela pode virar recebida pela baixa que o RM já
  tem, e o a receber e o faturado da obra mudam. O `cadastro aplicar --ensaio` mostra a obra com o antes e o
  depois dos tipos.
- O `cadastro validar` recusa o que não tem o formato de tipo de movimento de nota (`2.2.NN`, o único que a
  sincronização traz), o tipo que já está na lista geral e o repetido.
- A coluna só recebe valor pelo `cadastro aplicar`. Se mesmo assim trouxer algo que não é uma lista de tipos,
  vale "nenhum tipo extra" para aquele contrato, com aviso no log, e a aplicação seguinte do cadastro a regrava:
  uma célula ruim não derruba o a receber nem a sincronização.
- O tipo de movimento é da nota inteira. Se uma obra que declara o tipo tiver, nesse mesmo tipo e no mesmo centro
  de custo, nota que não cobra o órgão, o tipo não as separa: ela entra no a receber e no faturado da obra, e só
  as provas do vínculo a mantêm fora da medição. Aparecendo o caso, a decisão é outra (pelo tomador da nota).
- Conta nova que pergunta se uma nota é cobrança usa `cobranca_orgao.e_cobranca` com o contrato da nota; a página
  Fechamento a usa nas notas ligadas à medição (`fechamento._notas_por_medicao`), com o contrato da medição.
