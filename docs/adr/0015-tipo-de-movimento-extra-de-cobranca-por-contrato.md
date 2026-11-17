# Tipo de movimento extra de cobrança é declarado por contrato, no cadastro

O RM classifica cada nota por um tipo de movimento, e desde a #563 o sistema só trata como cobrança ao órgão a
nota de quatro tipos, os mesmos em toda obra (a lista geral: `2.2.01`, `2.2.02`, `2.2.07` e `2.2.16`). Só essa
nota entra no faturado do RM e no a receber, liga-se sozinha à medição e deixa a medição ser recebida pela baixa.

Em Deciolândia, obra de consórcio, a nota que a empresa emite contra o órgão pela cota dela era de um tipo da
lista geral. Em 09/2026 o faturamento passou todas para o tipo `2.2.03`, e elas saíram da conta sem que ninguém
tivesse decidido que deixaram de ser cobrança. Pôr o `2.2.03` na lista geral não serve: nas outras obras ele é
usado em notas que não cobram o órgão (entre empresas do grupo, da empresa contra o próprio consórcio), e são
centenas.

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

## Consequências

- O mesmo tipo em nota de outra obra, ou em nota sem obra, continua fora do a receber, do faturado, do vínculo
  automático e do recebimento pela baixa.
- Onde a nota ainda não tem contrato (o vínculo automático escolhendo a medição, a conciliação do histórico), a
  nota de tipo extra só é candidata às medições dos contratos que declaram o tipo. O centro de custo de outra obra
  não a leva para lá, e ela só concorre com outra nota pela mesma saída do espelho na obra que declara o tipo. As
  provas do vínculo (`docs/adr/0005`) valem igual.
- A chave não muda as outras regras da nota. O a receber e o faturado do RM continuam só com a nota da coligada
  da entidade do contrato: a nota da empresa em obra de consórcio, de tipo extra ou não, liga-se à medição e conta
  nas notas da cota na página dela, e segue fora dessas duas somas.
- A sincronização com o RM traz toda nota `2.2.NN` e os títulos dela, com ou sem a chave. O tipo decide o que
  conta, não o que entra no banco: declarar o tipo vale também para as notas já sincronizadas.
- Ao aplicar o cadastro com a chave, o vínculo automático antigo de nota desse tipo deixa de segurar a medição:
  na sincronização seguinte ela pode virar recebida pela baixa que o RM já tem, e o a receber e o faturado da obra
  mudam. O `cadastro aplicar --ensaio` mostra a obra com o antes e o depois dos tipos.
- O `cadastro validar` recusa o que não tem o formato de tipo de movimento de nota (`2.2.NN`, o único que a
  sincronização traz), o tipo que já está na lista geral e o repetido.
- O tipo de movimento é da nota inteira. Se uma obra que declara o tipo tiver, nesse mesmo tipo e no mesmo centro
  de custo, nota que não cobra o órgão, o tipo não as separa: ela entra no a receber e no faturado da obra, e só
  as provas do vínculo a mantêm fora da medição. Aparecendo o caso, a decisão é outra (pelo tomador da nota).
- Conta nova que pergunta se uma nota é cobrança usa `cobranca_orgao.e_cobranca` com o contrato da nota; a página
  Fechamento adota a função quando receber esta mudança.
