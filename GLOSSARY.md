# Dashboard Lotufo

O vocabulário do sistema de contratos de obras públicas e do ciclo da medição: do pedido ao órgão até o
recebimento. Cada termo tem um significado só, usado na tela, nas issues, nos testes e nas conversas.

## Language

### Contrato

**Órgão**:
Quem contrata a obra, aprova a medição e paga.
_Avoid_: cliente; contratante para um órgão só (ver Contratante; em relatório oficial que use a palavra, vale)

**Contratante**:
O órgão como as telas de leitura o agrupam: "SINFRA" reúne todas as superintendências; os outros órgãos são, cada
um, um contratante. É o primeiro nível de Obras: cada contratante tem página própria, com as obras dele, e é dele o
prazo de pagamento (`docs/adr/0007`).
_Avoid_: órgão (é quem assina o contrato: "SINFRA - SUEF II"), cliente

**Entidade**:
Empresa ou consórcio que assina contrato ou emite nota: a construtora, um consórcio ou uma consorciada.
_Avoid_: empresa (quando pode ser consórcio), coligada (é o número da entidade no RM)

**Consórcio**:
Entidade formada por duas ou mais empresas para um contrato, cada uma com sua cota.

**Cota**:
A parte da construtora num contrato de consórcio.
_Avoid_: participação, percentual da Lotufo

**Valor cheio**:
O valor total do consórcio, antes de aplicar a cota. A medição guarda o valor cheio; o contrato é cadastrado na cota.
_Avoid_: valor bruto (bruto é o da nota, antes das retenções), valor total

**Instrumento**:
Documento assinado que altera o contrato: aditivo de valor ou de prazo, apostilamento, ordem de paralisação ou de
reinício, marco de encerramento. Não se altera depois de aplicado; a correção é um instrumento novo.

**Aditivo**:
Instrumento assinado pelas duas partes que muda valor ou prazo.
_Avoid_: TA (salvo no número do documento)

**Apostilamento**:
Instrumento do órgão que reconhece reajuste ou prazo sem termo aditivo.

**Execução**:
O prazo para concluir a obra. É o relógio que importa para os avisos de prazo.

**Vigência**:
O prazo de validade do contrato.

**Folga**:
A distância que o órgão exige entre o fim da execução e o fim da vigência.

**Paralisação**:
Período entre a ordem de paralisação e a ordem de reinício, em que o prazo de execução não corre.

**Data-base**:
O mês de referência do reajuste de um contrato. O reajuste vale a partir do aniversário da data-base.

**Pleito**:
Pedido formal ao órgão: reajuste, prorrogação de prazo ou comunicação de conclusão.
_Avoid_: solicitação, requerimento

**Cadastro**:
Obras, órgãos, entidades e instrumentos escritos em arquivos versionados pelo dono e aplicados por comando. Não
existe tela de cadastro.

### Ciclo da medição

**Medição**:
O que foi executado num contrato numa competência, com número próprio. Tipos: execução, reajuste e projeto.

**Competência**:
O mês a que a medição se refere.
_Avoid_: período, mês de referência

**Competência em trabalho**:
O mês anterior ao de hoje, cuja medição está sendo feita agora. É a competência que a tela Medições e o Resumo das
medições abrem.

**Em análise**:
Etapa em que a planilha/carta foi enviada ao órgão e ele ainda não aprovou.

**Boletim**:
O documento em que o órgão aprova a medição; também a etapa em que a medição aprovada espera a nota. Na MT-PAR é a
empresa que o preenche, no modelo do órgão, e o fiscal do órgão assina; o reajuste tem boletim próprio
(`docs/adr/0013`).
_Avoid_: atestado, atesto

**Nota**:
A nota fiscal de serviço que fatura uma medição; também a etapa em que a nota emitida espera o protocolo.
_Avoid_: NF na tela (vale em nome de arquivo e no número do documento)

**Protocolado**:
A nota e o pacote foram enviados formalmente ao órgão. A data do protocolo começa a contar o prazo de pagamento.
Na obra sem o passo "Envio da nota", a medição com nota emitida conta como protocolada nas somas (protocolado, em
aberto, a receber), com a data da emissão da nota (`docs/adr/0006`).
_Avoid_: protocolada para a planilha enviada (isso é "em análise")

**Recebido**:
O órgão pagou: há baixa no RM, ou registro do administrador com motivo. Parte do protocolado; na obra sem o passo
"Envio da nota", parte da nota emitida, sem protocolo, e a espera conta da emissão da nota.
_Avoid_: pago, quitado

**Paga em parte**:
A nota com alguma baixa com valor no RM e falta acima da tolerância de R$ 1,00. O em aberto dela é o que falta nos
títulos do RM, limitado ao valor da nota; o resto do valor bruto conta como recebido. Título baixado sem valor não é
recebimento. O título que o RM dá como baixado (baixa total) com valor não tem falta, mesmo com o valor baixado
menor que o original (`docs/adr/0006`).

**Pedido**:
O valor que a planilha/carta pede ao órgão.
_Avoid_: valor protocolado

**Aprovado**:
O valor que o órgão fixa no boletim. Na MT-PAR, o "Valor Total da Nª Medição" da página do "Visto" do boletim
assinado e, no reajuste, o "TOTAL REAJUSTE" do boletim dele. Sem o valor do boletim gravado, a medição só conta como
aprovada depois da nota emitida (a nota prova que o órgão aprovou), pelo valor do pedido; antes disso fica só no
medido.
_Avoid_: valor atestado

**Faturado**:
O valor das notas emitidas para a medição.

**Medido**:
O aprovado e, enquanto não houver boletim, o pedido. O medido da obra soma as medições de execução e de projeto
a partir do envio da planilha/carta; reajuste fica fora, e medição cancelada, desistida ou ainda não enviada não
conta (`docs/adr/0012`).

**Saldo a executar**:
O valor vigente de execução (sem o aditivo de reajuste) menos o medido da obra.
_Avoid_: saldo do contrato

**Ritmo**:
O medido de execução por mês, numa janela de seis meses. O projeto fica fora: projeto pago não é obra
andando. A conclusão estimada é o saldo a executar nesse ritmo (`docs/adr/0012`). O necessário por mês é o saldo a
executar dividido pelas competências que restam, da de hoje à do fim da execução; com o ritmo igual ou acima
dele, a obra está no ritmo do prazo.

**Medição final**:
A última medição do contrato, marcada pela engenharia; põe o contrato em encerramento.

**Data do encerramento**:
O dia em que o contrato acabou, pelo encerramento ou pela rescisão. Vem do cadastro (`status_desde` do contrato
encerrado ou rescindido) e é o que a página da obra mostra em "encerrada desde". Sem ela, a página diz só o estado.

**Feito por fora**:
O ato do ciclo que a pessoa fez por e-mail ou no sistema do órgão, sem passar pela dashboard. A tela tem registro
próprio para ele (envio e protocolo feitos por fora).

**Ronda**:
A rotina diária da sessão do agente, fora do produto, que procura o que foi feito por fora nas fontes do dono e
lança o que tem documento que prova. É temporária (`docs/adr/0016`; roteiro na skill `ronda`).
_Avoid_: varredura, monitor de e-mail

### Documentos do ciclo

**Planilha/carta**:
A planilha de medição e a carta que a acompanha, enviadas ao órgão para análise. Fixam o pedido.

**Espelho**:
O documento que o sistema gera pedindo ao faturamento a emissão das notas de uma medição, com valor e retenções.

**Saída do espelho**:
Cada nota que o espelho pede: um emissor, um município, um valor.

**Pacote**:
O conjunto de documentos do protocolo, montado na ordem que o órgão exige: ofício, notas, certidões,
regularidade e peças técnicas.

**Ofício**:
A carta numerada que acompanha o protocolo ou o pleito. A numeração é da empresa e é digitada.
_Avoid_: CT (salvo no número do documento)

**Certidão**:
Documento de regularidade de uma entidade, com validade.

**Regularidade mensal**:
Os comprovantes mensais de folha e encargos de uma entidade, por competência.

**FRC**:
Fatura de Recebimento de Consórcio: a página que soma as notas das consorciadas de uma medição e vai ao órgão
com elas.

### Dinheiro e conferência

**Vínculo**:
A ligação entre uma nota e a medição que ela fatura.
_Avoid_: casamento, alocação (são nomes internos)

**Fatura do consórcio**:
A nota que o consórcio cobra do órgão por uma medição, lançada na coligada do consórcio no RM. Entra nas contas pelo
valor cheio vezes a cota.
_Avoid_: FRC (é a página que soma as notas das consorciadas)

**Nota da empresa ao consórcio**:
A nota que a construtora emite ao consórcio pela sua cota de uma medição. O valor de face dela já é a cota. Ligada à
medição, é dela que saem o protocolado e o recebido da cota no Fechamento: pelo valor de face, sem multiplicar pelo
percentual, e pela baixa dos títulos dela; a fatura do consórcio ligada à mesma medição não entra na conta. Sem ela,
vale a fatura do consórcio vezes a cota. Nunca as duas na mesma medição. O recebido dela é só o que foi baixado nos
títulos dela no RM, mesmo com a medição recebida: a medição vira recebida quando o órgão paga o consórcio, e a cota
só entrou quando o consórcio repassou (`docs/adr/0006`). O que falta dela numa medição recebida é repasse sem baixa:
quem deve é o consórcio, não o órgão.
_Avoid_: NFS-e da consorciada (quando a nota é a da própria construtora)

**Baixa**:
O registro no RM de que um título foi pago. A data da baixa é o dia do pagamento.

**Título**:
O lançamento a receber que o RM cria para uma nota, no valor líquido (sem as retenções). Uma nota pode ter mais de
um. O devido, o recebido e a falta da nota são somados nos títulos, nunca no bruto da nota.

**Excluído no RM**:
A nota ou o título que o RM deixou de devolver sem cancelar: o faturamento excluiu o título e o refez, ou refez o
movimento inteiro. Fica marcado, não se apaga, e sai de toda soma; se voltar a vir, volta a contar. Só a
sincronização marca, depois de duas rodadas completas seguidas sem ele; nota mais antiga do que a consulta alcança
não é exclusão (`docs/adr/0006`).
_Avoid_: apagado, removido (a linha continua no banco); cancelado (é o que o RM diz de uma nota que ele ainda devolve)

**Tipo de movimento**:
A classificação que o RM dá a cada nota (`2.2.01`, `2.2.03`), escolhida pelo faturamento ao lançar.
_Avoid_: codtmv (é o nome da coluna no RM)

**Cobrança ao órgão**:
A nota do RM que cobra o órgão por uma medição: a de tipo de movimento da lista geral e, na obra cujo cadastro
declara, a dos tipos extras dela (`docs/adr/0015`). Só ela entra no faturado do RM e no a receber, liga-se sozinha
à medição e deixa a medição ser recebida pela baixa.

**Prazo do órgão**:
Quantos dias o órgão costuma levar do protocolo ao pagamento: o terceiro quartil dos dias entre o protocolo e o
recebimento, das medições recebidas nos últimos 365 dias, com no mínimo cinco. Com menos, o órgão fica sem previsão.
A medição recebida sem protocolo (obra sem o passo "Envio da nota") fica fora da conta.
A SINFRA conta inteira, não cada superintendência.

**Custo lançado no RM**:
O custo que o RM registra para uma obra. Não é margem nem lucro.

**Participação do contratante**:
Quanto do medido do ano, na cota, é de um contratante, em percentual com uma casa. As participações de um ano somam
100%. Aparece na aba Por contratante do Fechamento. Sem medido no ano, não há participação.
_Avoid_: fatia, share, peso

### Tela

**Aviso**:
Algo com data que venceu ou vai vencer e pede um ato. Aparece na agenda.

**Pendência**:
Algo sem data que está errado ou faltando numa medição ou numa obra. Aparece onde se resolve.

**Trava**:
A recusa do sistema em continuar, sem opção de seguir mesmo assim.
_Avoid_: bloqueio para o que só pede confirmação ou justificativa

**Justificativa**:
A linha escrita por quem segue adiante com algo fora da regra; fica na auditoria.

**Situação**:
A leitura de um dado em uma de quatro: feito, em andamento, vence em breve ou crítico. Cada uma tem cor e forma. O
que não tem situação fica sem marca.
_Avoid_: status, nível (nível é o do aviso: Crítico, Ação, Atenção)

**Feito**:
Aconteceu e não pede mais nada (recebida, anexada, em dia). Verde, círculo com visto.

**Em andamento**:
Está em curso e dentro do esperado. Azul, círculo meio cheio.

**Vence em breve**:
Ainda não venceu, falta sem travar, ou se acompanha. Amarelo, triângulo.
_Avoid_: atenção como nome da situação (Atenção é um nível de aviso, que aparece como vence em breve)

**Crítico**:
Venceu, diverge, falhou, trava ou pede ação agora. Vermelho, octógono.

**Glifo**:
O símbolo que dá forma à situação, para ela não depender só da cor.

**Selo**:
A situação de uma linha: o glifo e uma palavra sobre o fundo claro da situação. Sem situação, é neutro e sem glifo.
_Avoid_: pílula, chip, badge

**Contador**:
A quantidade ao lado de um título. Com situação, leva o glifo dela.

**Variação**:
O quanto um valor subiu ou caiu contra uma referência escrita ao lado: o mês anterior, o mesmo mês do ano anterior
ou a mesma altura do mês anterior. Até 2% para cima ou para baixo é estável.
_Avoid_: diferença (é entre dois valores que deveriam ser iguais)

**Mesma altura do mês anterior**:
A referência da variação do protocolado e do recebido no Resumo das medições: o que as medições da competência
anterior já tinham protocolado e já tinham recebido até o mesmo dia de hoje, um mês antes, pelas datas dos eventos.

**Protocolado acumulado**:
Tudo o que a competência já protocolou até um dia, tenha ou não sido recebido depois, pela data do primeiro protocolo
da nota ou, sem ele, pela data do recebimento (o recebimento prova o protocolo até aquele dia). É o que a variação do
protocolado compara no Resumo das medições, para o órgão que paga mais rápido não fazer o número cair, e vai escrito
ao lado dela ("acumulado R$ …"). O valor da etapa Protocolado é outro: só o que está parado nela agora.

**Diferença**:
O quanto dois valores que deveriam ser iguais se afastam: o aprovado e o pedido. No mês, na obra e no ano é só o
corte (o aprovado abaixo do pedido), em reais e em percentual do pedido; acima de 0,5% é crítica. Até R$ 0,05 por
medição é arredondamento do órgão e conta como igual.
_Avoid_: variação

**Andamento**:
A leitura do ritmo contra o necessário para o prazo: Adiantada (100% ou mais), Atenção (de 70% a 99%) ou Devagar
(abaixo de 70%). A leitura é uma só, do servidor: a mesma na lista de Obras, na página do contratante e na página
da obra. A obra com o prazo no fim, com prorrogação pedida ou sem medição fica fora da régua, e a tela escreve o
motivo no lugar.
_Avoid_: em andamento (é uma situação)

**Prazo no fim**:
A obra com até duas competências de prazo de execução pela frente, contadas a de hoje e a do fim. Fica fora da régua
do andamento: o necessário por mês viraria o saldo inteiro em um ou dois meses. O pedido de prorrogação enviado e
ainda sem resposta também tira a obra da régua, com qualquer prazo pela frente ("prorrogação pedida").
_Avoid_: execução vencendo (é o aviso de prazo, a 60 e a 30 dias do fim)

**Sem medição desde**:
O mês da última medição de execução da obra que fechou as três últimas competências sem medir. Fica fora da régua do
andamento. A obra que nunca mediu execução não leva a frase.
_Avoid_: paralisada (é a obra com ordem de paralisação)

**Fila de trabalho**:
A entrada da tela Medições: as medições abertas da competência, agrupadas por com quem estão e, em cada grupo, da
mais parada para a menos.
_Avoid_: lista de pendências (pendência é outra coisa), em andamento como nome de tela

**Com quem está**:
Quem tem de agir na medição, pelo passo da vez: a Lotufo (planilha e carta, espelhos, envio da nota), o faturamento
(emissão da nota) ou o órgão (análise e pagamento). Na MT-PAR, o passo do boletim fica com a Lotufo enquanto nada foi
ao órgão.
_Avoid_: responsável (é uma pessoa; aqui é a Lotufo, o faturamento ou o órgão)

**Parada há**:
Os dias úteis desde o evento que abriu o passo da vez da medição (o envio, o boletim, o espelho, a nota, o
protocolo). Nunca conta da competência nem do lançamento. É a mesma leitura na fila de trabalho e no cartão de
medição do Resumo das medições.

**Parado (processo do SIGA)**:
O processo que está há 10 dias úteis ou mais no mesmo setor do órgão e não andou hoje. É o que a faixa de números e
o cabeçalho do painel da categoria contam na tela SIGA.
_Avoid_: atrasado (é o monitor sem leitura), vencido (o processo não tem prazo)

**Categoria a conferir**:
Aviso na linha do processo do SIGA quando o nome mostrado indica outra categoria que a escolhida por quem cadastrou
("Outros" com o complemento "Aditivo de prazo"). Nada muda sozinho: quem edita corrige no histórico do processo.

**Barra de passos**:
Os passos do fluxo da medição de uma obra, em ordem: os feitos, o da vez e os que faltam. Na página da medição é a
faixa de abas; na fila de trabalho, a miniatura na linha, do tamanho do fluxo da obra.

**Painel**:
O bloco com moldura preta e sombra dura, com o título dentro. É peça de tela, não um tipo de tela.
_Avoid_: cartão, card; painel como nome de tela (ver Tela de leitura)

**Quadro por etapa**:
A vista do Resumo das medições com uma coluna por etapa do ciclo e um cartão por medição na coluna da etapa em que
ela está.
_Avoid_: kanban; quadro do mês (é a matriz de obra por passo da tela Medições)

**Cartão de medição**:
A caixa de uma medição numa coluna do quadro por etapa: obra, contratante, medição, valor, parada há e, quando o
aprovado difere do pedido, a diferença.
_Avoid_: painel (o painel tem título e moldura grossa); cartão para outro bloco

**Tela de leitura**:
A tela de números que a diretoria abre para ler, sem operar: Início, Obras, página da obra, Fechamento e Resumo das
medições. É a elas que `.claude/rules/paineis.md` se refere quando diz "painéis".
_Avoid_: painel, dashboard, relatório

**Régua**:
A linha preta acima de um título: a de grupo, grossa, e a de seção, fina.

**Casca**:
O que fica igual em toda tela: o menu lateral e o topo.
_Avoid_: trilho, layout

**Janela**:
O painel que abre por cima da página para um formulário ou uma ação fora do fluxo dela.
_Avoid_: modal, popup

**Falha**:
A ação ou a leitura que não deu certo. Aparece na faixa de crítico, com o octógono.

**Engenharia**:
O perfil de quem opera o ciclo da medição.
_Avoid_: operação

**Diretoria**:
O perfil de quem só lê.

**Administrador**:
O perfil que cuida de usuários, auditoria, pendências de cadastro e exceções registradas.
