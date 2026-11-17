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
  é o primeiro envio do espelho ao faturamento. Sem espelho, é o dia do boletim do órgão (a nota só é emitida depois
  de o órgão aprovar) e, sem boletim gravado, o dia do envio da planilha/carta. Medição sem nenhuma dessas datas,
  espelho que não saiu pelo sistema e nota sem data de emissão não provam a ordem: não ligam por valor.
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

## Consequências

- Duas notas ativas com o mesmo valor para a mesma saída, ou para a mesma medição sem espelho, ficam soltas e a
  pessoa decide pelo PDF. É o caso da nota cancelada na prática e reemitida, que o RM mantém ativa.
- O vínculo não depende de ninguém de fora preencher campo no RM.
- Os vínculos por valor feitos na conciliação do histórico continuam e são conferidos contra o documento no
  fechamento.
- Vínculo já gravado não é desfeito por mudança de regra: as travas valem para o que o casador fizer dali em diante.
- A nota da própria empresa em obra de consórcio deixa de ligar sozinha: o contrato é do consórcio e o centro de
  custo dela não aponta obra. Ela entra pelo PDF anexado na medição ou pela correção de cadastro. Se o cadastro do
  contrato de consórcio passar a declarar o centro de custo que a empresa usa para ele, a saída do espelho volta a
  valer dentro da obra; está no `docs/backlog.md`.
- A medição sem espelho e sem data de boletim nem de envio da planilha/carta (lançada à mão direto no protocolo) não
  atrai nota por valor.
