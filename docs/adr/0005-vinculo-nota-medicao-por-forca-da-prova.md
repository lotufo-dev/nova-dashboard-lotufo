# O vínculo entre nota e medição segue a força da prova

Uma nota pode chegar ao sistema pelo PDF que a pessoa anexa ou pelo RM, e precisa ser ligada à medição que ela
fatura. Casar só pelo valor falha: na medição de 09/2026 o valor exato ligava menos da metade das notas do
histórico, com obras inteiras em zero, porque uma medição sai em várias notas e há parcelas de valor repetido.
Proibir o valor de vez também falha: toda nota que o RM enxerga antes do PDF ficaria solta e entraria no a
receber como órfã. Decidimos por uma hierarquia, do mais forte ao mais fraco:

1. **Documento:** o PDF da nota anexado na medição, confirmado pelo RM pelo número.
2. **Pedido do próprio sistema:** nota do RM com o valor exato de uma saída do espelho, na obra do centro de
   custo, emitida depois do envio do espelho, com uma medição só e uma nota só para aquele valor.
3. **Valor da medição sem espelho, dentro da obra** (três regras, decididas em 17/11/2026):
   - na obra do centro de custo da nota, o valor exato da medição, com candidata única (`centro_custo_valor`);
   - na obra do centro de custo, o par de notas do mesmo dia que soma o valor de uma medição só, quando só um par
     fecha aquela medição (`centro_custo_soma_dia`);
   - em consórcio que é uma obra só (coligada sem centro de custo cadastrado), o valor exato da medição, com
     candidata única (`valor_exato`).
4. **Nunca:** valor aproximado, valor fora da obra, e valor em carga de histórico ou em fechamento, que só ligam
   por documento.

## As duas travas valem para todo vínculo por valor

- **De data.** A medição só recebe por valor a nota emitida no dia do pedido dela ou depois. Com espelho, o pedido
  é o primeiro envio do espelho ao faturamento: o e-mail do sistema ou o envio feito por fora, com a data que a
  pessoa registrou (issue #798); havendo os dois, o mais antigo. Sem espelho, é o dia do boletim do órgão (a nota só
  é emitida depois de o órgão aprovar) e, sem boletim gravado, o dia do envio da planilha/carta. Medição sem nenhuma
  dessas datas, espelho sem envio registrado e nota sem data de emissão não provam a ordem: não ligam por valor.
- **De nota repetida.** Havendo mais notas ativas e livres daquele valor que alcançam a medição (mesma coligada,
  cobrança ao órgão naquele contrato, emitidas depois do pedido, na obra dela) do que vagas para aquele valor,
  nenhuma liga sozinha. As vagas são as saídas do espelho daquele valor que esperam nota; na medição sem espelho,
  uma; no par do dia, as notas do próprio par.

## Sem obra, a nota fica solta

Até 17/11/2026 a saída do espelho era procurada na carteira inteira quando o centro de custo da nota não apontava
obra (a nota da própria empresa ao órgão em obra de consórcio, lançada num centro que não é de contrato nenhum). Isso
contrariava o item 4. Decidimos que, na coligada que cadastra centros de custo, a nota cujo centro não aponta obra
não liga por regra nenhuma de valor, nem concorre com a nota da obra: fica em "NFs sem medição" e a pessoa a liga
pelo PDF.

## O contrato de consórcio declara o centro de custo da própria empresa

O contrato de consórcio é de outra coligada, e a empresa lança a nota que emite pela cota dela num centro de custo
do livro dela, que não é o de contrato nenhum. Sem mais nada, a decisão acima deixaria essa nota solta todo mês, e o
recebido e o repasse do consórcio (`docs/adr/0006`) dependem desse vínculo. Decidimos que o cadastro do contrato de
consórcio declara esse centro (`centro_custo_empresa_rm`, coluna criada pela migração 090): com a declaração, a nota
da empresa naquele centro aponta aquela obra, e as regras de valor valem dentro dela, com as duas travas.

- Com espelho, vale a saída do espelho (item 2), como em toda medição nascida dele.
- Sem espelho, o valor comparado é a cota da medição (um arredondamento, o de `contratos.cota`), porque a nota da
  empresa já é a cota: valem o valor exato da cota e o par do dia que soma a cota. A nota um centavo ao lado da cota
  não liga. A fatura do próprio consórcio continua casando pelo valor cheio, na coligada dele.
- Sem a declaração, a nota da empresa não liga sozinha.
- Cada centro aponta uma obra só: o `cadastro validar` recusa o mesmo centro em dois contratos, o centro que já é o
  centro de custo de uma obra própria e a chave em contrato que não é de consórcio. Se a repetição chegar ao banco por
  outro caminho, o centro não aponta obra nenhuma.

Na cópia da produção de 17/11/2026, com o centro declarado nas três obras de consórcio que têm nota da empresa ligada,
desfeitos os 27 vínculos e as medições de volta a protocoladas: o casador refez os 3 das medições nascidas do espelho,
todos pela saída; 20 são de medição do legado, que o casador não olha; e 4 são de medição sem espelho e sem data de
boletim nem de envio da planilha/carta (a trava de data). Em 26 das 27 notas o valor é a cota ao centavo; uma difere
dois centavos.

## Uma nota em mais de uma medição (17/11/2026)

Há nota que fatura duas ou mais medições. O vínculo era sempre da nota inteira e uma nota só entrava numa medição.

- A correção de cadastro liga a mesma nota a mais de uma medição com o valor de cada parte (`ligar_nf` com `valor`),
  pela prova do documento (o PDF da nota diz as medições). O vínculo de parte é marcado (`nf_alocacoes.partilhada`)
  e vale o valor gravado nele; o vínculo da nota inteira continua valendo o valor atual da nota.
- Os vínculos de parte vigentes de uma nota somam no máximo o valor dela. A nota já ligada inteira a uma medição não
  recebe parte: desfaz-se o vínculo e liga-se de novo com o valor de cada parte.
- Toda conta que usa o vínculo respeita o valor da parte: a cobertura que fecha a medição pela baixa
  (`docs/adr/0006`), o aviso de notas pagas que não cobrem, a página da medição, o protocolado e o recebido do
  Fechamento. O que é dos títulos da nota (devido, recebido, falta) reparte-se pelas partes na proporção do valor de
  cada uma, só com inteiros, e as partes somam a nota (`sincronizacao_rm.partes_da_nota`). No a receber do Início,
  a parte da medição em aberto conta pela medição; a parte de medição fechada sem pagamento provado e o resto da
  nota que nenhuma medição levou contam pelo que falta nos títulos.
- Onde a nota entra uma vez só (faturado do mês, notas protocoladas no mês), continua uma vez só.
- O casador automático e a tela não criam vínculo de parte, e a medição com espelho não o recebe: nela a nota liga
  pela saída do espelho, inteira. A nota partilhada que o RM deixa de devolver e volta a devolver não tem o vínculo
  refeito sozinha (`docs/adr/0006`): religa-se pela correção de cadastro.

## Consequências

- Duas notas ativas com o mesmo valor para a mesma saída, ou para a mesma medição sem espelho, ficam soltas e a
  pessoa decide pelo PDF. É o caso da nota cancelada na prática e reemitida, que o RM mantém ativa.
- O vínculo não depende de ninguém de fora preencher campo no RM.
- Os vínculos por valor feitos na conciliação do histórico continuam e são conferidos contra o documento no
  fechamento.
- Vínculo já gravado não é desfeito por mudança de regra: as travas valem para o que o casador fizer dali em diante.
- A nota da própria empresa em obra de consórcio só liga sozinha na obra cujo cadastro declara o centro de custo
  dela. Depois do deploy que traz essa regra, o centro tem de ser declarado em cada contrato de consórcio; até lá a
  nota entra pelo PDF anexado na medição ou pela correção de cadastro.
- A medição sem espelho e sem data de boletim nem de envio da planilha/carta (lançada à mão direto no protocolo) não
  atrai nota por valor.
