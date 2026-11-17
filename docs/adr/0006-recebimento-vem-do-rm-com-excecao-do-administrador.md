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
cobertura das notas vigentes vale igual, e a espera pelo pagamento conta da emissão da nota. Enquanto espera, ela
conta como a protocolada no protocolado e no em aberto do Fechamento e no a receber do Início, da lista de Obras e da
página da obra, com a data da emissão da nota no lugar da do protocolo; no Início ela fica na etapa "Protocolado" do
ciclo e, por não ter protocolo, sem data esperada (`docs/adr/0007`). Na obra com o passo, sem
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
- O a receber do Início e da lista de Obras (na cota) segue esta exceção desde 17/11/2026, pela mesma função que
  decide quais notas contam (`fechamento._notas_da_conta`): a medição que espera o pagamento entra pelo em aberto da
  nota da empresa; a que o órgão já pagou, pelo repasse sem baixa; e a fatura do consórcio da mesma medição não entra
  de novo como cobrança do RM. O a receber da página da obra é em valor cheio (o que o órgão deve ao contrato) e não
  leva o repasse.
- No passo Pagamento da página da medição, a medição de consórcio sem espelho conta pelos títulos da nota da empresa
  ligada e, sem ela, pelos títulos da fatura do consórcio vezes a cota; a fatura que a nota da empresa tirou da conta
  aparece sem valor. Com espelho, o passo continua pelas saídas do espelho.
- O que ainda não segue (a cobertura das notas vigentes, o recebido por mês do Início) está no `docs/backlog.md`.

## O a receber do Início e o em aberto do Fechamento (conciliação de 17/11/2026)

As duas telas respondem a perguntas diferentes e não mostram o mesmo total. A conta que as liga:

**a receber do Início e da lista de Obras = em aberto do Fechamento (2025, 2026 e o anterior a 2025, nas três partes:
nota não paga, repasse sem baixa e medição sem nota ligada) + cobranças do RM em aberto que nenhuma medição em aberto
representa.**

As cobranças do RM que só o Início soma (`diretoria._notas_em_aberto`) são de dois tipos:
- a nota sem medição ligada. O Fechamento a mostra à parte, fora do total (não tem competência), pelo valor bruto; o
  Início a soma pelo que falta nos títulos do RM, que nascem líquidos, sem as retenções. A mesma nota aparece com
  valor menor no Início;
- a nota ligada a medição fechada pelo corte de 25/09/2026, ou recebida pela baixa do RM, com título ainda aberto
  no RM. O Início a soma pelo que falta nos títulos; no Fechamento a medição recebida leva a nota inteira ao recebido,
  e ela não aparece em aberto. A nota ligada a medição recebida por registro (à mão ou pela correção de cadastro) não
  entra em nenhuma das duas telas: ver "Medição recebida por registro", abaixo.

Na parte das medições os dois lados usam bases diferentes e só coincidem quando a nota fecha com a medição: o Início
conta a medição que espera o pagamento pelo valor dela na cota (aprovado, senão o pedido); o Fechamento conta as notas
ligadas pelo bruto, a paga em parte pelo que falta nos títulos, e só usa o valor da medição quando não há nota ligada.
Medição protocolada com a nota já baixada no RM, nota paga em parte e nota de valor diferente da medição fazem os dois
divergirem até a medição virar recebida. Em consórcio com a nota da empresa ligada os dois usam a mesma conta.

Na cópia da produção de 17/11/2026 a parte das medições fechou ao centavo entre as duas telas, e a diferença inteira
foram as cobranças do RM dos dois tipos acima.

## Medição recebida por registro (decisões de 17/11/2026)

O dono delegou estas decisões à sessão em 17/11/2026, medidas numa cópia da produção. Nela não havia nenhuma medição
recebida à mão pelo administrador; os casos contados são os da correção de cadastro e do corte.

- **O registro à mão exige a data.** Sem ela a medição ficava recebida com a data nula, fora do recebido de qualquer
  mês e do prazo do órgão. A rota recusa o registro sem data e com data depois de hoje. As medições recebidas sem data
  que existem vieram do corte e da correção de cadastro, que não sabem o dia.
- **A nota ligada a medição recebida por registro não entra no a receber.** Registro é o ato feito para aquela
  medição, com motivo: o do administrador, à mão (já valia, #203), e o da correção de cadastro (`estado: recebida`),
  que passa a valer igual. O estado diz que o dinheiro entrou, o Fechamento já levava a nota inteira ao recebido, e o
  título ainda aberto no RM aparece na Saúde ("Notas de medições recebidas por registro sem baixa no RM"), para a
  contradição não sumir: quem a resolve reabre a medição ou confirma o registro. Ficam como estavam a medição fechada
  pelo corte (a decisão do corte diz que o que o RM mostra em aberto segue a receber pelas notas) e a recebida pela
  baixa do RM. Na cópia, uma nota saiu do a receber por esta regra.
- **A nota que chega depois, na medição recebida pela correção de cadastro, é ligada pela própria correção**
  (`ligar_nf`). O casador só procura nota para a recebida à mão: a correção de cadastro fecha medição do histórico em
  lote, e abrir todas ao casador seria casar 24 meses de notas por coincidência de valor. Na cópia, a única medição
  recente recebida pela correção sem nota é de valor zero.
- **Janela de datas da recebida à mão no casador.** A nota só liga a ela se foi emitida entre o pedido da medição
  (`docs/adr/0005`) e cinco dias depois da data do recebimento. Sem a janela, a nota de outra medição de mesmo valor
  na obra, emitida meses depois, ligava a ela. O tamanho saiu da medida: de 624 pares de nota e medição recebida com
  as duas datas, 622 tinham a nota emitida até o dia do recebimento e dois depois dele, um e três dias. Recebimento
  registrado sem data não tem janela: a nota não liga sozinha.
- **Recebida à mão faturada em duas notas, com uma já ligada, não recebe a segunda sozinha.** Fica assim: com uma nota
  ligada ela deixa de ser candidata, e reabrir a busca por "o que falta" seria casar por diferença de valor. A medição
  ganha o aviso de que as notas ligadas não cobrem o valor dela, na página da medição e na lista do administrador
  (`docs/adr/0008`), e a nota que falta entra pelo PDF.
- **Na medição recebida, o administrador anexa o PDF da nota e desfaz vínculo.** Antes os dois davam erro e só a
  correção de cadastro ligava e desligava. O estado e a data do recebimento não mudam; o vínculo feito ou desfeito
  fica na auditoria com quem fez, o motivo e o estado da medição. Para os outros perfis continua recusado.
- **Aviso "notas pagas não cobrem a medição".** A medição que espera a baixa com todas as notas ligadas pagas no RM
  e sem cobertura do valor não vira recebida (regra do começo deste documento) e passou a ter aviso próprio, o par do
  aviso da nota maior que a medição. Não muda estado nenhum: a saída é ligar a nota que falta ou o administrador
  registrar o recebimento.

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
- **Teto contra exclusão em massa.** A resposta parcial que não é vazia (uma coligada inteira que deixa de vir, a
  consulta editada no RM, a permissão da conta) passa pelas provas acima, e marcar desfaria de uma vez centenas de
  vínculos, muitos feitos à mão. Se a rodada afetaria mais notas distintas (as que seriam marcadas e as que têm
  título a marcar) do que o maior entre 30 e 5% das notas que vieram, ela não marca nada: nem aos poucos, nem a
  parte pequena que seria verdadeira. O resto da rodada segue; a recusa vai para a auditoria e para a Saúde, como
  atenção, e se repete enquanto durar. A exclusão grande que é verdadeira é liberada pelo administrador, com ensaio
  antes (`rm liberar-exclusao`, no `docs/runbook.md`). O piso de trinta foi conferido numa cópia da produção: a
  primeira rodada, que marca de uma vez o que sumiu desde o começo, cabe nele.
- **A nota marcada vale como cancelada**: deixa de ser ativa, o vínculo com a medição é desfeito e auditado ("NF
  excluída no RM") e a medição não volta de estado sozinha, como na nota cancelada no RM. A substituta liga pelas
  regras de sempre (`docs/adr/0005`); medição aberta que fica sem nota ganha o aviso da nota cancelada, dito como
  excluída.
- **A nota que volta a vir recupera o vínculo.** A marca sai, a situação volta à que o RM diz e o vínculo que a
  exclusão desfez é refeito como vínculo novo, com o mesmo valor, a mesma origem e a mesma regra, auditado. Não é
  refeito, e a auditoria diz por quê, quando a nota voltou cancelada ou está desconsiderada, quando ela já teve
  outro vínculo depois, quando a medição foi encerrada ou quando outra nota ocupou o lugar (a saída do espelho já
  tem nota, ou as notas vigentes com ela passariam do valor da medição).
- **A baixa da nota que saiu** fica gravada e marcada, fora do recebido. Quando há substituta, o dinheiro conta
  pelo título dela, uma vez. A medição que já estava recebida continua recebida.
- **Na tela**, a página da medição mostra a nota e o título marcados, ditos como excluídos no RM, fora dos totais.
- **No Fechamento**, a nota marcada sai do protocolado e do em aberto (a medição que fica sem nota volta ao em
  aberto pelo valor dela, como "sem nota ligada"), e o título marcado não entra na leitura de paga, paga em parte ou
  em aberto: a baixa de um título excluído não é recebimento.
- A correção de cadastro não desconsidera nem liga nota marcada: ela já não conta, e a marca é só da sincronização.

Ficou de fora: passar o vínculo da nota antiga para a substituta sem prova (a substituta só liga pelas regras do
vínculo), e apagar a linha (nada financeiro se apaga).
