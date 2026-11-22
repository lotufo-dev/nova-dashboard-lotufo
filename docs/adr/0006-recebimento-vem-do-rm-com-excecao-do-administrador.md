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
  de novo como cobrança do RM.
- O recebido do Início (o "Recebido no mês" e os doze meses) segue a mesma escolha desde 17/11/2026
  (`diretoria._pct_do_recebido`): com a nota da empresa ligada à medição, entra a baixa do título dela, pela face e
  no mês em que foi baixada, e a baixa da fatura do consórcio da mesma medição não entra. As duas telas escolhem as
  mesmas notas; continuam diferentes na base, por desenho: o Início mostra o líquido baixado, pelo mês da baixa, e o
  Fechamento o bruto, pela competência. Na cópia da produção de 17/11/2026 a troca tirou dos meses de março a setembro
  o que o órgão pagou ao consórcio de uma obra e pôs em outubro, quando o repasse foi baixado, e tirou de outubro as
  faturas de duas medições cujo repasse ainda não tem baixa. Cada diferença foi conferida nota a nota.
- No passo Pagamento da página da medição, a medição de consórcio sem espelho conta pelos títulos da nota da empresa
  ligada e, sem ela, pelos títulos da fatura do consórcio vezes a cota; a fatura que a nota da empresa tirou da conta
  aparece sem valor.

O que fica como está, por decisão de 17/11/2026:
- **A medição de consórcio continua virando recebida pela fatura do consórcio** (`sincronizacao_rm._recebimentos` só
  olha as notas da coligada do contrato, e a cobertura das notas vigentes também). O estado diz que o órgão pagou;
  o repasse é outra pergunta, respondida pelo recebido. Trocar a regra para a baixa da nota da empresa contradiria o
  estado de medições já recebidas: na cópia da produção, duas medições recebidas têm a nota da empresa sem baixa, e é
  delas o grupo "repasse sem baixa" do Fechamento.
- **O complemento do medido pelas notas do RM** (`diretoria.complemento_rm`) só olha a nota sem medição ligada. Sem
  medição não há nota da empresa ligada, e vale a regra geral: a fatura do consórcio vezes a cota.
- **O passo Pagamento da medição com espelho continua pelas saídas do espelho.** O espelho diz, saída a saída, o que a
  empresa fatura: sem nota casada a saída mostra "—", e espelho sem saída da empresa fecha a cota em zero. Pôr no
  lugar a fatura do consórcio vezes a cota mostraria como recebido da empresa um dinheiro que entrou no consórcio.
- **A página da obra mostra o a receber em valor cheio e não leva o repasse.** Ali o número é o que o órgão deve ao
  contrato; o repasse é dívida do consórcio com a empresa, na cota, e aparece na lista de Obras, no Início e no
  Fechamento. Na obra de consórcio com repasse pendente a lista mostra a receber e a página da obra, não: são duas
  perguntas, e somar cota com valor cheio no mesmo número não fecharia com nenhuma das duas.

## O a receber do Início e o em aberto do Fechamento (conciliação de 17/11/2026)

As duas telas respondem a perguntas diferentes e não mostram o mesmo total. A conta que as liga:

**a receber do Início e da lista de Obras = em aberto do Fechamento (2025, 2026 e o anterior a 2025, nas três partes:
nota não paga, repasse sem baixa e medição sem nota ligada) + cobranças do RM em aberto que nenhuma medição em aberto
representa.**

As cobranças do RM que só o Início soma (`diretoria._notas_em_aberto`) são de dois tipos:
- a nota sem medição ligada. O Fechamento a mostra à parte, fora do total (não tem competência), pelo valor bruto; o
  Início a soma pelo que falta nos títulos do RM, que nascem líquidos, sem as retenções. A mesma nota aparece com
  valor menor no Início;
- a nota ligada a medição já recebida (pelo corte de 25/09/2026 ou pela correção de cadastro, por exemplo) com título
  ainda aberto no RM. O Início a soma pelo que falta nos títulos; no Fechamento a medição recebida leva a nota inteira
  ao recebido, e ela não aparece em aberto. Só a nota ligada a medição recebida à mão pelo administrador fica fora das
  duas telas: ver "Medição recebida por registro", abaixo.

Na parte das medições os dois lados usam bases diferentes e só coincidem quando a nota fecha com a medição: o Início
conta a medição que espera o pagamento pelo valor dela na cota (aprovado, senão o pedido); o Fechamento conta as notas
ligadas pelo bruto, a paga em parte pelo que falta nos títulos, e só usa o valor da medição quando não há nota ligada.
Medição protocolada com a nota já baixada no RM, nota paga em parte e nota de valor diferente da medição fazem os dois
divergirem até a medição virar recebida. Em consórcio com a nota da empresa ligada os dois usam a mesma conta.

Na cópia da produção de 17/11/2026 a parte das medições fechou ao centavo entre as duas telas, e a diferença inteira
foram as cobranças do RM dos dois tipos acima.

### A receber antigo, à parte (decisão do dono de 17/11/2026)

Pendência de competência anterior a 2025 fica fora das telas da diretoria. O Fechamento já contava o "em aberto
anterior a 2025" à parte; o Início e a lista de Obras passam a fazer o mesmo, pela mesma definição do ano
(`diretoria.ANO_INICIAL`, de onde `fechamento.ANOS` começa). A conta de cima vale agora duas vezes, uma de cada lado:

**a receber de 2025 em diante (o total do Início e da lista de Obras) = em aberto do Fechamento de 2025 e 2026, nas
três partes + cobranças do RM de 2025 em diante que nenhuma medição em aberto representa − o que o RM deixou de
informar.**

**a receber à parte = em aberto anterior a 2025 do Fechamento + cobranças do RM anteriores a 2025 que nenhuma medição
em aberto representa + o que o RM deixou de informar.**

- **Anterior a 2025** é a competência da medição. A nota do RM não tem competência: vale a da medição (fechada) a que
  está ligada e, na nota sem medição, o ano da emissão, porque a nota não fatura competência posterior à emissão dela.
- **O que o RM deixou de informar.** As consultas de notas e de títulos só trazem a nota emitida nos últimos 24
  meses. A nota que sai da janela para de vir e o título dela fica como estava, em aberto para sempre: a baixa
  lançada depois nunca chega, e a dashboard não sabe se foi pago. Essa nota também sai do total, dita como "sem
  atualização do RM desde" o dia em que o RM a informou pela última vez (`diretoria.sem_atualizacao_do_rm`: não veio
  nas rodadas dos últimos dois dias, contados da nota vista por último; com a sincronização inteira parada, nada
  muda de lugar). Vale para a nota que conta sozinha e para a medição que espera o pagamento quando todas as notas
  ligadas a ela estão assim. A linha que é as duas coisas (anterior e sem atualização) conta em "sem atualização".
  O Fechamento continua contando a medição de 2025 em diante cuja nota o RM deixou de informar no em aberto do ano
  dela; por isso o termo aparece com sinais opostos nas duas contas.
- **Na tela**, o que fica à parte aparece numa linha própria, menor, com o rótulo do Fechamento ("Em aberto de
  competências anteriores a 2025") e "Sem atualização do RM desde …": no painel do ciclo do Início e sob os totais
  da lista de Obras. Não entra no total, na faixa de mais de 60 dias, na etapa "Protocolado" do ciclo nem na
  previsão de entrada. A página da obra (valor cheio) e a reconciliação da administração continuam mostrando tudo.
- **Medida na cópia da produção de 17/11/2026**: o total e o que fica à parte somam o a receber de antes, e as duas
  contas fecharam ao centavo. De 2025 em diante, o em aberto do Fechamento dos dois anos mais as cobranças do RM
  recentes sem medição; à parte, o em aberto anterior a 2025 do Fechamento (quatro medições) mais quatro notas de
  2022 e 2024 sem medição em aberto, três delas sem atualização do RM. Nenhuma medição de 2025 em diante tinha nota
  fora da janela.

Ficou de fora: pedir ao RM os títulos das notas que saíram da janela (consulta nova no RM, que pede a autorização do
dono) e separar o "sem atualização do RM" também na página Fechamento.

## Medição recebida por registro (decisões de 17/11/2026)

O dono delegou estas decisões em 17/11/2026, medidas numa cópia da produção. Nela não havia nenhuma medição recebida
à mão pelo administrador; os casos contados são os da correção de cadastro e do corte.

- **O registro à mão exige a data.** Sem ela a medição ficava recebida com a data nula, fora do recebido de qualquer
  mês e do prazo do órgão. A rota recusa o registro sem data e com data depois de hoje. As medições recebidas sem data
  que existem vieram do corte e da correção de cadastro, que não sabem o dia. As que têm nota ligada com os títulos
  baixados ganham a data da última baixa (seção "Data do recebimento da medição recebida sem data").
- **Só o recebimento registrado pelo administrador tira a nota do a receber.** Já era assim (#203) e fica assim. A
  medição recebida pela correção de cadastro (`estado: recebida`) não conta como registro à mão: a correção fecha
  medição do histórico em lote, com base nos documentos da carga, e não é afirmação de pagamento. Para ela, como para
  a fechada pelo corte, a evidência que existe é o RM: o que ele mostra em aberto segue a receber pelas notas. A
  medida mostrou o caso: a única nota ligada a medição recebida pela correção de cadastro com título aberto tem o
  título inteiro em aberto no RM, e tirá-la do a receber esconderia um valor que o RM diz que não entrou.
- **A reconciliação mostra toda nota de medição recebida com título aberto no RM**, qualquer que seja o caminho do
  recebimento ("Notas de medições recebidas sem baixa no RM"), e diz se a nota está no a receber. Na recebida à mão é
  o único lugar em que o título aberto aparece; nas outras é a contradição entre o estado da medição e o RM, para
  alguém decidir (reabrir a medição ou esperar a baixa). Na cópia eram três notas: duas de medição fechada pelo corte
  e uma de medição recebida pela correção de cadastro.
- **A nota que chega depois, na medição recebida pela correção de cadastro, é ligada pela própria correção**
  (`ligar_nf`). O casador só procura nota para a recebida à mão: abrir ao casador as medições fechadas em lote seria
  casar 24 meses de notas por coincidência de valor. Na cópia, a única medição recente recebida pela correção sem
  nota é de valor zero.
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

## Data do recebimento da medição recebida sem data (22/11/2026, #842)

O corte, a correção de cadastro em lote e a carga do histórico fecham a medição como recebida sem saber o dia. Sem a
data ela fica fora do recebido de qualquer mês, e a variação do Recebido no Resumo das medições vem sem referência.
Parte delas ganhou a nota depois, e a data da baixa já estava no banco sem chegar à medição.

Decisão do dono: **a medição recebida sem data, com nota ligada e todos os títulos dessas notas baixados no RM, recebe
a data da última baixa.** A medição recebida sem nota ligada fica sem data e não gera aviso: não se põe data sem
documento.

- **Regra no código, não lista gravada à mão** (`sincronizacao_rm.datar_recebidas`). Roda no fim de cada rodada da
  sincronização e pelo comando `rm datar-recebidas`, com ensaio (`docs/runbook.md`). Vale para o que já existe e
  para a medição que ganhar a nota ou a baixa depois.
- **Só preenche a data que falta.** O estado não muda e a data já gravada nunca é trocada, nem a do registro do
  administrador. Por isso roda quantas vezes for, e a segunda não acha nada.
- **Olha na rodada, não no ato de ligar a nota.** A medição faturada em mais de uma nota leva a última baixa do
  conjunto que estiver ligado quando a rodada passar; ligadas uma a uma no mesmo ato, a primeira nota paga daria a
  data antes de a segunda entrar. A nota ligada depois de a data gravada não a move.
- **Baixado é a leitura de sempre** (`_falta_por_titulo`): o título que o RM deu como baixado com valor não tem
  falta, mesmo por valor menor, e entra com a data da baixa; a diferença continua no grupo "Títulos baixados no RM
  por valor menor" da reconciliação. O baixado em parte só conta dentro da tolerância de R$ 1,00 somada das notas.
  Título em aberto, título baixado sem a data da baixa, nota desconsiderada ou sem título no RM: sem data. O título
  cancelado e o excluído no RM ficam fora da conta, como em toda leitura.
- **Nota que saiu por cancelamento ou exclusão no RM segura a data.** A rodada desfaz o vínculo dessa nota antes de
  olhar a data, e a medição faturada em duas notas ficaria com a data da que sobrou; o faturamento costuma refazer a
  nota, e a substituta, ligada e paga depois, não moveria a data. Enquanto nada for ligado à medição depois desse
  vínculo desfeito, ela fica sem data.
- **A ordem dos marcos vale como no registro à mão.** A última baixa depois de hoje, antes da emissão de alguma das
  notas ligadas ou antes da emissão gravada na medição não dá a data: é dia digitado errado no RM ou nota que não é
  daquela medição. A regra não levanta erro, só não grava, e volta a olhar na rodada seguinte.
- **Falha neste passo não derruba a rodada.** As notas, as baixas e os recebimentos da rodada ficam; o erro vai
  para o log e para o evento da rodada na auditoria, e a rodada seguinte tenta de novo.
- **A baixa total sem valor não dá a data.** Glosa, compensação ou encontro de contas não é recebimento (seção
  "Título baixado no RM não tem falta"), e o dia dela não é o de um pagamento. Na cópia da produção de 20/11/2026 é
  o caso de uma medição, a que o levantamento da issue listou como "título baixado por valor menor": o título dela
  está baixado com valor zero e não aparece em grupo nenhum da reconciliação. Ela fica sem data até alguém decidir
  o caso com o documento.
- **A cobertura do valor da medição pelas notas não é exigida**, ao contrário do recebimento pela baixa (#714). Lá a
  pergunta é se a medição foi paga; aqui ela já está recebida e a pergunta é o dia. Em consórcio a nota ligada
  costuma ser só a da empresa, que vale a cota e nunca cobriria o valor cheio.
- **Em consórcio, a data é a do repasse da cota** quando a última baixa é a da nota da empresa: contam as notas
  ligadas de qualquer coligada. É a data que as telas da diretoria, na cota, querem. Ela não é o dia em que o órgão
  pagou: a auditoria marca essas medições e o prazo do órgão não as conta (`docs/adr/0007`).
- **O reajuste negativo absorvido pelo espelho da execução acompanha a data dela**, como acompanha o recebimento
  (#589): ele não tem nota própria, e a nota do par é a da execução.
- **Auditoria.** Cada data gravada é um evento `medicao.recebida_em`, pelo sistema, com a origem ("baixa do RM"), as
  notas, a quantidade de títulos, se alguma nota está no grupo dos títulos baixados por valor menor da reconciliação
  (a mesma lista da tela) e se a data é a do repasse. Na tela nada muda além do número: sem selo nem aviso.
- Medida na cópia da produção de 20/11/2026: 73 medições ganham data, 64 delas de 2025 e 2026, com a mesma data
  que o levantamento da issue propôs para cada uma, e 9 de competências anteriores; 16 pela nota da empresa. A
  segunda execução não grava nada. O prazo do órgão muda só onde há pagamento novo do próprio órgão na amostra.
  Nenhum mês ganha a referência do Recebido na leitura sem filtro, porque em todos sobra medição sem nota; com o
  filtro por contratante, alguns ganham.
  Em 9 das 73 as notas da coligada do contrato somam menos que a medição (consórcio que fatura em parcelas que não
  batem com a medição): a data delas é a da última baixa do que está ligado.

Ficou de fora: desfazer uma data gravada por esta regra (não existe ato; a nota desligada depois não a apaga) e
mostrar na reconciliação o título baixado sem valor de nota ligada a medição.

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

## Título baixado no RM não tem falta (17/11/2026)

O a receber mostrava como dívida o resto de notas já pagas: título com baixa total no RM e valor baixado um pouco
menor que o original, e título com baixa parcial antiga que ficou com uma sobra.

Decisão: **vale o que o RM informa no status do título.** O título que o RM dá como baixado (baixa total) com valor
baixado não tem falta, qualquer que seja a diferença para o valor original: o desconto, a retenção ou o acerto lançado
na baixa não é dívida. Falta é do título em aberto e do baixado em parte. Vale em toda leitura
(`sincronizacao_rm._falta_por_titulo`): a receber, Fechamento, reconciliação, página da medição e o recebimento da
medição pela baixa.

- Isto muda a decisão de 19/10/2026 (issue #35) num ponto: a medição cujo título foi baixado no RM com mais de R$ 1,00
  a menos ficava aberta para conferência; agora vira recebida, e a diferença fica na auditoria do recebimento
  (`medicao.recebida_com_diferenca`, com `baixa_total_no_rm`). A tolerância de R$ 1,00 continua valendo para o
  título baixado em parte.
- **A diferença fica à vista, sem travar nada.** Receber menos do que se cobrou é informação de dinheiro: o título
  que o RM deu como baixado com mais de R$ 1,00 a menos (o mesmo limite, `diretoria.TOLERANCIA_CENTAVOS`) aparece em
  Administração › Reconciliação, no grupo "Títulos baixados no RM por valor menor", com a obra, a medição, a nota, o
  valor do título, o valor baixado, a diferença e a data da baixa, e na contagem da Saúde. É pendência sem data, do
  administrador (`docs/adr/0008`). Só nota de cobrança ao órgão que cai numa obra; o título e a nota excluídos no
  RM não entram. Quem conferiu tira a nota da lista com `encerrar_residuo_nf` (motivo e fonte), que nesse caso só
  registra a conferência: não havia falta a abater.
- A baixa total **sem valor** (glosa, compensação) continua como estava: não é recebimento, e só o a receber da
  diretoria e a reconciliação a tratam como quitada (#563).
- **Resíduo de baixa parcial antiga.** O RM não diz se a sobra de um título baixado em parte é dívida ou resto
  esquecido; a regra automática não alcança. A correção de cadastro encerra o resíduo de uma nota já paga
  (`encerrar_residuo_nf`, com motivo e fonte): grava quanto do que falta foi dado por encerrado, e a conta do que
  falta abate esse valor. Os títulos e as baixas ficam como o RM os deu; o que passar do valor encerrado (um título
  novo, por exemplo) volta a aparecer; `reabrir_residuo_nf` desfaz, com evento novo. Só vale para nota em que todo
  título tem baixa com valor: o título inteiro em aberto é dívida, não resíduo. O `desconsiderar_nf` continua
  recusando nota com baixa.
- Medida na cópia da produção de 17/11/2026: sete títulos baixados com valor menor que o original acima da
  tolerância, dois deles de nota de cobrança ao órgão; as duas notas saíram do a receber, nenhuma medição mudou de
  estado e os totais do Fechamento não mudaram (uma das notas, sem medição, deixou a lista das pagas em parte).

## Atos de correção de cadastro (17/11/2026)

A carga do histórico só criava medição protocolada, e de protocolada só se ia a recebida, cancelada ou desistida.
Medição que os documentos mostram em análise no órgão ficava no a receber sem nota, e a saída era cancelá-la. A
correção de cadastro (`cadastro corrigir-medicoes`, `docs/runbook.md`) ganhou os atos que faltavam. Todos têm
ensaio, motivo e fonte, gravam a auditoria e não apagam nada.

- **Devolver ao estado provado (`devolver`).** A medição protocolada sem nota vigente ligada volta ao estado que o
  documento prova, gravado como a tela o grava (`medicoes.estado_no_fluxo`): em análise (execução e projeto com a
  planilha/carta enviada; o reajuste previsto, com o pedido congelado pela data do envio) ou boletim recebido (com o
  aprovado como evento). O pedido fica. O protocolo de nota que a carga ou a correção gravou não aconteceu: fica no
  banco marcado como desfeito (`medicao_protocolos.desfeita_em`), aparece na linha do tempo dito como desfeito e sai
  de toda leitura de protocolo (protocolado no dia, prazo do órgão, a receber). Recusa a medição com nota vigente,
  com nota enviada ao órgão pelo sistema, com espelho, e a que não está protocolada. Depois dela a medição segue
  pelo fluxo da tela.
- **Reabrir no estado certo.** `reabrir` continua levando a cancelada a protocolada; com o estado de destino, faz a
  reabertura e a devolução no mesmo ato.
- **A carga cria no estado que a linha prova.** Só com o pedido, em análise; com o aprovado e sem nota, boletim
  recebido; com a nota ou o protocolo da nota, protocolada, como antes; com a data do recebimento e a fonte,
  recebida (pela origem, esse recebimento vale como o da correção de cadastro: não é o registro à mão do
  administrador). A medição que já existe não muda de estado pela carga, e a linha dela continua "igual".
- **Desfazer o recebimento sem prova (`desfazer_recebimento`).** A medição que virou recebida pelo corte, pela
  correção em lote ou pela carga volta a protocolada quando não há pagamento provado. Recusa a recebida pela baixa do
  RM (o RM é a prova) e a recebida à mão pelo administrador: esse registro é a afirmação de pagamento de quem
  responde por ela, e não há caminho que o desfaça (nem na tela, nem aqui). Recusa também a medição com nota que tem
  baixa no RM, mesmo parcial: o pagamento está provado, e o que falta do título já segue a receber pela nota;
  desfazer faria a medição contar inteira.
