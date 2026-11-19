# Na obra de consórcio, o envio ao órgão leva a nota que a FRC soma

Quando uma consorciada emite uma nota no lugar de outra que já estava anexada à medição, a dashboard resolvia só
metade do caso. A FRC já tinha a regra: para cada saída do espelho vigente vale o último PDF anexado da mesma
empresa e município, e o que sobra aparece à parte. O envio ao órgão não tinha regra nenhuma: mandava todos os PDFs
de nota da medição. A nota antiga ia no pacote, nos anexos soltos do e-mail e na lista de números da carta, ao lado
de uma FRC que não a somava (#873, achado em 19/11/2026 pela revisão da ronda).

Decidimos que o envio usa a regra da FRC. Na obra de consórcio com espelho vigente que espera notas, vai ao órgão
o PDF de nota que a FRC soma. Fica fora o PDF que o sistema sabe que não é nota da FRC:

- a nota substituída: o PDF lido que sobra, de empresa e município cuja nota esperada já é atendida por outro PDF
  (o último anexado). Vale mesmo com outra nota ainda em falta;
- com todas as notas esperadas atendidas, tudo o que sobra: o PDF lido que não atende nenhuma e o que a leitura não
  entendeu (rascunho, leiaute desconhecido).

Enquanto falta nota esperada, o PDF que sobra sem ser substituído (CNPJ que o cadastro não liga à empresa,
município lido diferente do espelho) e o não lido podem ser a nota que falta, e continuam indo. A segunda revisão
da PR mostrou que tirar toda sobra nesse momento faria o e-mail sair com uma nota a menos do que saía antes.

A nota que fica fora não é apagada nem marcada: continua em `medicao_documentos`, com a auditoria do anexo, e a
tela da FRC continua mostrando que ela não corresponde a nenhuma nota esperada.

A regra mora em `frc.fora_do_envio`, e `protocolo._docs_nota` é a única lista de onde saem o PDF único, os anexos
soltos, os números da carta, o corpo do e-mail e o passo de envio da tela.

Onde as notas vão dentro do PDF único, o pacote montado passa a guardar os PDFs de nota que levou
(`protocolos.montado_notas`, migração 096), como já guardava a FRC assinada. Na obra de consórcio, se a lista que
vai ao órgão muda depois da montagem, o envio e o anexo do assinado ficam bloqueados até montar de novo; a lista é
conferida de novo depois da reserva do envio, antes do e-mail. Sem isso, o pacote montado antes da troca saía com a
nota antiga quando a FRC assinada ainda não estava anexada, e a tela listava as notas de agora para um PDF que
tinha as de antes.

## Opções consideradas

- **Um ato "nota substituída" na tela**, com motivo e auditoria, que marcaria o documento e o tiraria da FRC, do
  envio e da contagem. Rejeitado como regra do envio por três motivos. Quem opera teria de lembrar de mais um
  clique, e o esquecimento é justamente o caso em que a nota antiga sai para fora, que não se desfaz. Seriam duas
  fontes para a mesma pergunta (a marca e a regra da FRC), e elas poderiam discordar: documento marcado que a FRC
  ainda soma, ou o contrário. E pediria uma marca no documento e tela nova para dizer o que o sistema já sabe pela
  ordem dos anexos.
- **Estender a regra à obra própria**, tratando o último PDF da própria empresa por município como o vigente.
  Rejeitado: na obra própria quem diz que a nota vale é o vínculo (`docs/adr/0005`) e o RM, não a ordem dos anexos.
  A nota da própria empresa trocada sai da conta pelo cancelamento no RM ou pela operação `desconsiderar_nf` da
  correção de cadastro, que já aceita `substituida_por`.

## Consequências

- **O envio e a FRC não discordam mais quando a FRC está completa.** O que a FRC assinada lista é o que vai.
- **Não há ato a fazer nem dado a corrigir.** Medição que já tinha nota sobrando passa a mandar só a vigente assim
  que o código novo entra.
- **O pacote montado guarda as notas que levou, mas só a obra de consórcio bloqueia por elas.** Na obra própria o
  pacote continua valendo como foi montado: lá todo PDF de nota anexado vai, não há como tirar um anexado por
  engano, e o bloqueio só teria saída levando-o junto. A nota anexada depois de montar numa obra própria continua
  fora do pacote sem aviso, como antes; fica no `docs/backlog.md`.
- **O pacote montado antes da migração 096 não diz o que levou.** Ele só pede para montar de novo quando alguma
  nota da medição já não vai ao órgão, que é o caso em que pode ter a nota antiga dentro. Os demais seguem valendo.
- **"Vale o último anexado" não tem volta pela tela.** Anexar por engano uma nota da mesma empresa e município
  depois da certa faz a errada valer, e arrastar de novo o PDF certo não muda a ordem (o mesmo arquivo não entra
  duas vezes). Isso já era assim na FRC; agora vale também para o envio. Fica no `docs/backlog.md`.
- **A obra própria continua mandando todos os PDFs de nota anexados**, inclusive o de nota cancelada ou
  desconsiderada. É outro defeito, com outra fonte de verdade, e está no `docs/backlog.md`.
- **Duas saídas da mesma empresa no mesmo município não são distinguidas.** O `checklist` da FRC casa por
  município antes do valor; com duas saídas assim, a troca de uma nota pode deixar de fora a nota válida da outra.
  O cadastro de exemplo não tem esse caso; fica no `docs/backlog.md`.
- **A tela do envio não diz qual PDF ficou de fora.** Isso aparece só no quadro da FRC, no passo da nota.
