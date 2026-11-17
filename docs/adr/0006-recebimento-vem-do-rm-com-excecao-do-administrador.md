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

## Nota e título excluídos no RM deixam de contar (17/11/2026, #755)

A sincronização só inseria e atualizava. Quando o faturamento exclui um título e o refaz (o movimento continua e
ganha outro lançamento), ou refaz o movimento inteiro (outro identificador, mesmo número, emissão e valor; é como a
reclassificação chega), o RM deixa de devolver o antigo sem cancelá-lo, e ele ficava no banco para sempre: o devido
e a falta da nota em dobro, a medição que não fechava pela baixa do título novo, a nota antiga contando ao lado da
substituta.

Decisão: **o que o RM deixou de devolver é marcado como excluído no RM e sai de toda soma** (devido, recebido, falta,
faturado, a receber). Nada se apaga: a linha, a baixa gravada e a auditoria ficam. Se voltar a vir, a marca sai e
volta a contar.

- **Título**: marcado quando para de vir na consulta de baixas e a nota dele continua vindo na de notas.
- **Nota**: marcada quando para de vir na consulta de notas estando dentro da janela que a consulta cobre. A janela
  é medida pela própria resposta: só a nota com emissão posterior à da nota mais antiga que veio. A consulta traz
  24 meses; a nota mais antiga, ou sem data, saiu pela janela e não é exclusão. Os títulos da nota marcada são
  marcados com ela.
- **Só com prova de ausência.** Conta a rodada completa: as duas consultas responderam e trouxeram linhas. A que
  falha ou vem vazia não marca nada. E a marca pede ausência em duas rodadas completas seguidas: as consultas do RM
  leem sem bloqueio e uma linha pode faltar numa leitura, e um título aberto que some por uma hora fecharia a
  medição pela baixa dos outros, estado que não volta sozinho. Custa uma hora de atraso.
- **A nota marcada vale como cancelada**: deixa de ser ativa, o vínculo com a medição é desfeito e auditado ("NF
  excluída no RM") e a medição não volta de estado sozinha, como na nota cancelada no RM. A substituta liga pelas
  regras de sempre (`docs/adr/0005`); medição aberta que fica sem nota ganha o aviso da nota cancelada, dito como
  excluída. A nota que volta a vir passa pelo vínculo automático como qualquer nota.
- **A baixa da nota que saiu** fica gravada e marcada, fora do recebido. Quando há substituta, o dinheiro conta
  pelo título dela, uma vez. A medição que já estava recebida continua recebida.
- **Na tela**, a página da medição mostra a nota e o título marcados, ditos como excluídos no RM, fora dos totais.
- A correção de cadastro não desconsidera nem liga nota marcada: ela já não conta, e a marca é só da sincronização.

Ficou de fora: passar o vínculo da nota antiga para a substituta sem prova (a substituta só liga pelas regras do
vínculo), e apagar a linha (nada financeiro se apaga).
