# Recebimento vem do RM, com exceção registrada do administrador

A medição vira recebida pela baixa do título no RM, que é fato contábil. A exceção: o administrador registra o
recebimento à mão, com motivo, quando o RM não vai mostrar a baixa. Duas decisões fecham os casos de borda. A nota
que chega depois de um recebimento à mão pode ser ligada à medição sem mudar o estado dela; solta, ela somaria no
a receber um dinheiro que já entrou. A medição faturada em mais de uma nota só vira recebida quando as notas
vigentes cobrem o valor da medição; com uma nota cancelada no RM, a quitação da outra não basta.

## Exceção: obra sem o passo "Envio da nota" (16/11/2026, #743)

O recebimento parte de `protocolada`. Na obra cuja lista `passos_medicao` do cadastro não tem `envio_nota`, a empresa
não envia a nota ao órgão e a medição ficava em nota emitida sem caminho até recebida. Nessas obras, a medição com
nota emitida é recebida direto, sem protocolo, pela baixa do RM ou pelo registro do administrador com motivo; a
cobertura das notas vigentes vale igual, e a espera pelo pagamento conta da emissão da nota. Na obra com o passo, sem
a chave ou com a lista vazia (vale a família do órgão), nada muda. A decisão sobre os passos é a mesma da barra da
página da medição (`passos_das_medicoes`), para a tela e o servidor não divergirem.

## Exceção: nota da empresa em consórcio, na página Fechamento (17/11/2026, #756)

Em contrato de consórcio, a medição vira recebida quando o órgão paga a fatura do consórcio. A cota da construtora só
entra quando o consórcio repassa, e o fato contábil do repasse é a baixa do título da nota que ela emite ao
consórcio, no livro dela no RM. Por isso, com essa nota ligada à medição, o recebido da página Fechamento segue a
baixa do título dessa nota, e não o estado da medição: recebido é o que foi baixado, em aberto é o valor da nota menos
isso. Vale igual para a medição recebida pela baixa do RM, pelo registro do administrador e pelo corte. O estado da
medição não muda, e sem a nota da empresa ligada vale a regra de cima (a medição recebida leva a nota ao recebido).

Consequências:
- A medição de consórcio já fechada (pelo corte, por exemplo) reaparece no em aberto do Fechamento quando ganha a nota
  da empresa com título aberto. O em aberto do ano sobe a cada lote de vínculos por efeito desta regra, não por erro.
- A tela mostra essas linhas em grupo próprio do em aberto, que diz que o órgão já pagou e falta a baixa do repasse:
  quem deve é o consórcio.
- Se o repasse entrar sem baixa no RM, o registro à mão não tira a nota do em aberto. A saída que existe é desfazer o
  vínculo da nota da empresa, que devolve a medição à regra da fatura do consórcio.
- A página da medição e o a receber do Início e da lista de Obras ainda não seguem esta exceção (`docs/backlog.md`).
