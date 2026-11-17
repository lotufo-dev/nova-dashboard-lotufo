# Dashboard Lotufo

O vocabulário do sistema de contratos de obras públicas e do ciclo da medição: do pedido ao órgão até o
recebimento. Cada termo tem um significado só, usado na tela, nas issues, nos testes e nas conversas.

## Language

### Contrato

**Órgão**:
Quem contrata a obra, aprova a medição e paga.
_Avoid_: cliente, contratante (salvo em relatório oficial que use a palavra)

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
O documento em que o órgão aprova a medição; também a etapa em que a medição aprovada espera a nota.
_Avoid_: atestado, atesto

**Nota**:
A nota fiscal de serviço que fatura uma medição; também a etapa em que a nota emitida espera o protocolo.
_Avoid_: NF na tela (vale em nome de arquivo e no número do documento)

**Protocolado**:
A nota e o pacote foram enviados formalmente ao órgão. A data do protocolo começa a contar o prazo de pagamento.
_Avoid_: protocolada para a planilha enviada (isso é "em análise")

**Recebido**:
O órgão pagou: há baixa no RM, ou registro do administrador com motivo. Parte do protocolado; na obra sem o passo
"Envio da nota", parte da nota emitida, sem protocolo, e a espera conta da emissão da nota.
_Avoid_: pago, quitado

**Paga em parte**:
A nota com alguma baixa com valor no RM e falta acima da tolerância de R$ 1,00. O em aberto dela é o que falta nos
títulos do RM, limitado ao valor da nota; o resto do valor bruto conta como recebido. Título baixado sem valor não é
recebimento.

**Pedido**:
O valor que a planilha/carta pede ao órgão.
_Avoid_: valor protocolado

**Aprovado**:
O valor que o órgão fixa no boletim. Sem o valor do boletim gravado, a medição só conta como aprovada depois da nota
emitida (a nota prova que o órgão aprovou), pelo valor do pedido; antes disso fica só no medido.
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
andando. A conclusão estimada é o saldo a executar nesse ritmo (`docs/adr/0012`).

**Medição final**:
A última medição do contrato, marcada pela engenharia; põe o contrato em encerramento.

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

**Engenharia**:
O perfil de quem opera o ciclo da medição.
_Avoid_: operação

**Diretoria**:
O perfil de quem só lê.

**Administrador**:
O perfil que cuida de usuários, auditoria, pendências de cadastro e exceções registradas.
