# O vínculo entre nota e medição segue a força da prova

Uma nota pode chegar ao sistema pelo PDF que a pessoa anexa ou pelo RM, e precisa ser ligada à medição que ela
fatura. Casar só pelo valor falha: na medição de 09/2026 o valor exato ligava menos da metade das notas do
histórico, com obras inteiras em zero, porque uma medição sai em várias notas e há parcelas de valor repetido.
Proibir o valor de vez também falha: toda nota que o RM enxerga antes do PDF ficaria solta e entraria no a
receber como órfã. Decidimos por uma hierarquia, do mais forte ao mais fraco:

1. **Documento:** o PDF da nota anexado na medição, confirmado pelo RM pelo número.
2. **Pedido do próprio sistema:** nota do RM com o valor exato de uma saída do espelho, na obra do centro de
   custo, emitida depois do envio do espelho, com uma medição só e uma nota só para aquele valor.
3. **Consórcio que é uma obra só:** valor exato da medição, com candidata única.
4. **Nunca:** valor aproximado, valor fora da obra, e valor em carga de histórico ou em fechamento, que só ligam
   por documento.

## Consequências

- Duas notas ativas com o mesmo valor para a mesma saída ficam soltas e a pessoa decide pelo PDF. É o caso da
  nota cancelada na prática e reemitida, que o RM mantém ativa.
- O vínculo não depende de ninguém de fora preencher campo no RM.
- Os vínculos por valor feitos na conciliação do histórico continuam e são conferidos contra o documento no
  fechamento.
