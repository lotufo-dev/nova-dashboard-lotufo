# Na obra de consórcio, o envio ao órgão leva a nota que a FRC soma

Quando uma consorciada emite uma nota no lugar de outra que já estava anexada à medição, a dashboard resolvia só
metade do caso. A FRC já tinha a regra: para cada saída do espelho vigente vale o último PDF anexado da mesma
empresa e município, e o que sobra aparece à parte. O envio ao órgão não tinha regra nenhuma: mandava todos os PDFs
de nota da medição. A nota antiga ia no pacote, nos anexos soltos do e-mail e na lista de números da carta, ao lado
de uma FRC que não a somava (#873, achado em 19/11/2026 pela revisão da ronda).

Decidimos que o envio usa a regra da FRC. Na obra de consórcio com espelho vigente que espera notas, vai ao órgão
o PDF de nota que a FRC soma. Ficam fora:

- o PDF lido que não atende nenhuma saída: a nota antiga, quando outra da mesma empresa e município foi anexada
  depois, e a nota de empresa que o espelho não espera;
- com todas as saídas atendidas, o PDF que a leitura não entendeu (rascunho, leiaute desconhecido). Enquanto falta
  alguma nota esperada ele pode ser a que falta, e continua indo.

A nota que fica fora não é apagada nem marcada: continua em `medicao_documentos`, com a auditoria do anexo, e a
tela da FRC continua mostrando que ela não corresponde a nenhuma nota esperada.

A regra mora em `frc.fora_do_envio`, e `protocolo._docs_nota` é a única lista de onde saem o PDF único, os anexos
soltos, os números da carta, o corpo do e-mail e o passo de envio da tela.

## Opções consideradas

- **Um ato "nota substituída" na tela**, com motivo e auditoria, que marcaria o documento e o tiraria da FRC, do
  envio e da contagem. Rejeitado como regra do envio por três motivos. Quem opera teria de lembrar de mais um
  clique, e o esquecimento é justamente o caso em que a nota antiga sai para fora, que não se desfaz. Seriam duas
  fontes para a mesma pergunta (a marca e a regra da FRC), e elas poderiam discordar: documento marcado que a FRC
  ainda soma, ou o contrário. E pediria migração e tela nova para dizer o que o sistema já sabe pela ordem dos
  anexos.
- **Estender a regra à obra própria**, tratando o último PDF da própria empresa por município como o vigente.
  Rejeitado: na obra própria quem diz que a nota vale é o vínculo (`docs/adr/0005`) e o RM, não a ordem dos anexos.
  A nota da própria empresa trocada sai da conta pelo cancelamento no RM ou pela operação `desconsiderar_nf` da
  correção de cadastro, que já aceita `substituida_por`.

## Consequências

- **O envio e a FRC não discordam mais.** O que a FRC assinada lista é o que vai. Nota trocada depois da FRC a
  deixa desatualizada, o que já bloqueava o envio até gerar e assinar de novo; o pacote montado antes fica
  bloqueado até montar de novo (issue #169), e a nova montagem já sai sem a nota antiga.
- **Não há ato a fazer nem dado a corrigir.** Medição que já tinha nota sobrando passa a mandar só a vigente assim
  que o código novo entra, sem migração.
- **O pacote montado antes desta regra não é refeito sozinho.** Se ele foi montado com a nota antiga dentro e a
  FRC assinada vigente já estava nele, nada o bloqueia: é preciso montar de novo antes de enviar.
- **"Vale o último anexado" não tem volta pela tela.** Anexar por engano uma nota da mesma empresa e município
  depois da certa faz a errada valer, e arrastar de novo o PDF certo não muda a ordem (o mesmo arquivo não entra
  duas vezes). Isso já era assim na FRC; agora vale também para o envio. Fica no `docs/backlog.md`.
- **A obra própria continua como estava**: todos os PDFs de nota anexados vão, inclusive o de nota cancelada ou
  desconsiderada. É outro defeito, com outra fonte de verdade, e está no `docs/backlog.md`.
