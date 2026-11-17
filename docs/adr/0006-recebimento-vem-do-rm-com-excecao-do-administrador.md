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
