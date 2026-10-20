# Motores de medição e apostilamento: proposta de consolidação da dashboard

**Data:** 20/10/2026. **Origem:** fases 0 a 3 do levantamento SharePoint + Outlook
(`docs/superpowers/plans/2026-10-19-levantamento-motores-sharepoint.md`; síntese em
`docs/levantamento-motores-2026-10-20.md`). **Autoridade:** complementa a spec de 2026-09-21 (§2, §5, §6, §7, §8,
§11 e §12); o que ela não contradiz continua valendo. **Revisão:** sem gate Sol nesta etapa (decisão de 19/10/2026);
revisor-adversarial e gate Sol entram nas PRs da fase 5, pelas regras normais.

Regras que esta spec respeita e nenhuma opção pode violar: centavos inteiros e arredondamento único; valor
pedido congelado no envio; correção é evento novo, nunca sobrescrita; sem exclusão física de registro financeiro;
auditoria append-only; cadastro e instrumento versionados em YAML, aplicados por `cadastro aplicar`, instrumento
aplicado não se altera; sem custo de API por uso (extração determinística com fila humana; OCR local só onde já
decidido); e-mail sai da conta de quem clicou, envio único com reserva atômica.

## 0. O que o levantamento mostrou, em seis linhas

1. A dashboard tem **647 medições** carregadas do legado, mas o acumulado medido está **abaixo do documento em
   15 das 21 obras** (faltam de 1 a 13 medições por obra, sempre as mais recentes) e acima em 3; nenhuma medição
   tem valor aprovado registrado (`medicao_atestos` vazia), então "valor pedido × valor aprovado", que diverge
   com frequência, não existe no sistema.
2. **Reajuste:** 22 datas-base, 1 apostilamento de reajuste carregado (Granito) contra dezenas nos documentos; o motor
   conta o ciclo por ano, mas o apostilamento da SINFRA lista o reajuste **mês a mês, vinculado ao nº da medição**.
3. **Prazos:** só o último instrumento de prazo de cada obra está no banco (o resto virou uma linha
   `carga-legado`), então o histórico da carta de prorrogação sai com o ordinal errado; paralisações só em 2 obras
   (documentos mostram 5); **garantia vazia nas 22 obras** e nenhum endosso, enquanto 16 de 21 obras estão com a
   garantia vencida ou ausente nos documentos.
4. **Cronograma:** 22 versões, todas da carga de 04/09/2026, com 1 a 31 competências; nenhuma por aditivo; não há
   tela para criar versão; a curva S compara o medido com um previsto que ninguém mantém.
5. **O fluxo real da SINFRA** (SMO + DocuSign + NF) não tem "protocolo" como documento; a data que existe é a
   aprovação no SMO. O "protocolo" com carimbo só existe na Prefeitura de Cuiabá e, em parte, na MT-PAR.
6. **A medição mais recente está no Outlook, não no SharePoint, em 7 obras.** Qualquer solução que dependa de ler a
   pasta da obra fica um a dois meses atrasada por construção.

## 1. Opções de consolidação

Custo em dias de trabalhadora (issues de meio dia, orquestradora com até 10 em paralelo), sem contar a revisão do
Leo. "Risco" é o de produto (dado errado na tela) e o de adoção (a operação não usar).

### A. Histórico primeiro (carga única do consolidado)

- **Entra na tela:** as medições que faltam (execução e reajuste), o valor aprovado de cada uma (como evento de
  atesto), os instrumentos de prazo históricos (um por aditivo, no lugar da linha `carga-legado`), os
  apostilamentos de reajuste já homologados, a garantia e os endossos de cada obra, as paralisações, e uma versão de
  cronograma por aditivo (a curva do SMO ou a carta de repactuação). Curva S e saldo passam a ter dado real;
  os avisos de garantia, endosso e apostilamento passam a disparar.
- **Sai:** nada de código; sai o dado legado que o documento contradiz (cancelado com motivo, nunca apagado).
- **Como:** YAML do contrato ganha `garantia`, os instrumentos completos e `cronograma` (§2.4); medições históricas
  entram por um carregador novo (`cadastro carregar-medicoes <obra>.csv --ensaio`), idempotente por (nº, tipo),
  que **nunca altera medição existente**: valor diferente vira evento de correção com a fonte. O CSV de cada obra
  é preparado das análises do vault (privado) e conferido pelo Leo, obra a obra.
- **Custo:** 2 dias de código (carregador + validação + testes) e 4 a 6 dias de preparação e conferência dos CSVs
  (sessão manual, uma rodada por 3 ou 4 obras). **6 a 8 dias.**
- **Risco:** baixo no código; médio no dado (entre 18 e 78 itens `[CONFERIR]` por obra). O maior: em um mês a
  dashboard volta a estar desatualizada, porque nada muda em como a medição nasce.

### B. Motores novos: medição e apostilamento com o fluxo inteiro na dashboard

- **Entra na tela:** a medição nasce na dashboard como **boletim** (período, valor pedido, planilha anexada,
  ofício de encaminhamento gerado), vai ao fiscal, recebe a **aprovação** (valor aprovado, data, documento do
  órgão), e só então segue para espelho, nota e protocolo, que já existem. O reajuste da Nª medição nasce do
  **ciclo de apostilamento**: previsão por competência (da planilha do pleito), pedido, aprovado, apostilado,
  faturado, cada um com data e documento; divergência entre pedido e previsto, e NF antes do apostilamento, viram
  aviso. Detalhe em §2.
- **Sai:** a dependência do SharePoint e do Outlook como fonte da medição; "valor protocolado" como único valor
  da medição; a digitação do reajuste no espelho sem referência.
- **Custo:** motor de medição 8 a 10 dias; motor de apostilamento 6 a 8 dias. **14 a 18 dias.**
- **Risco:** médio-alto de adoção (muda o passo zero de quem opera: hoje o boletim é feito na planilha e
  protocolado no SMO/DocuSign por fora; a dashboard precisa aceitar "feito por fora" em todo passo, como já faz
  no envio da nota). Sem o histórico (A), curva, saldo e ciclo de reajuste nascem vazios.

### C. Leitura determinística dos documentos existentes, com fila humana

- **Entra na tela:** "arraste o pacote" em três lugares: a capa do SMO (nº, período, valor desta medição,
  acumulado, situação, data de realização, fins de execução e vigência), o termo aditivo ou de apostilamento de
  prazo (dias e datas novas) e o termo de apostilamento de reajuste (valor mês a mês). O leitor (regex + pypdf,
  como `leitura_nfse`; OCR local quando o PDF é imagem, como nas certidões) preenche; a pessoa confere e aceita
  (`detectado` → `aceito`, origens que já existem no banco). Nenhuma recarga manual.
- **Sai:** a digitação de valor, data e nº; a recarga manual do histórico (C também carrega o passado: basta
  arrastar as capas antigas).
- **Custo:** leitor da capa do SMO 3 dias (texto, leiaute fixo, só SINFRA); leitor de termo de prazo e de
  apostilamento 3 a 4 dias (quase todos são imagem: OCR, qualidade variável); fila humana e tela 2 dias; carga do
  passado por arrasto 2 a 3 dias de operação. **8 a 10 dias.**
- **Risco:** médio: o SMO só existe na SINFRA (12 obras); MT-PAR tem boletim próprio e Prefeitura carimbo
  manuscrito, que o OCR não decide; o fluxo continua fora da dashboard (a pessoa arrasta depois do fato), o que
  contradiz "o sistema é onde o trabalho é feito".

### A+B (recomendada)

Histórico pela carga única e, em cima dele, os dois motores. A carga dá a curva S, o saldo e o ciclo de reajuste
de cada obra no primeiro dia; os motores impedem que a dashboard volte a atrasar. **20 a 26 dias.** Risco: o de B,
mitigado por "feito por fora" em todo passo e pela carga que mostra valor na tela antes de pedir mudança de hábito.
Inclui um pedaço de C: o leitor da capa do SMO dentro do passo "registrar aprovação" (1 issue), porque é onde a
digitação mais erra (acumulado e data de realização).

### A+C

Histórico pela carga e, dali em diante, arrastar os documentos. **14 a 18 dias.** Menos mudança de hábito, dado
sempre com documento, mas a dashboard segue atrás do fato: a medição mais recente continua no Outlook e a
pessoa precisa lembrar de arrastar. Boa opção se a operação não puder absorver o motor de medição agora; pode
ser o primeiro degrau de A+B (o leitor da capa é reaproveitado inteiro).

### Recomendação em uma frase

**A+B**, na ordem A (carga, 3 obras por rodada, as ativas de maior saldo primeiro), motor de apostilamento (menor,
fecha o padrão mais caro: reajuste sem apostila), motor de medição (maior, muda o hábito), com o leitor da capa
do SMO embutido no passo de aprovação; A+C fica como plano B se a operação pedir para não mudar o passo zero.

## 2. Desenho dos motores

Convenções: tabelas novas só por migração que acrescenta; toda tabela de evento tem os gatilhos
`*_sem_update` e `*_sem_delete` de `medicao_atestos` (migração 039); "quem clica" é um dos três perfis
(operação, engenharia, diretoria só lê); e-mail pelo mecanismo de `envio_reserva` (reserva atômica, envio único,
registro antes de sair, "feito por fora" com `.eml`); aviso pelo registro único de `app/avisos.py` (spec §11).

### 2.1 Motor de medição (boletim → aprovação → espelho → nota → protocolo → pagamento)

**O que muda no conceito.** A medição passa a ter dois valores de direito próprio, ambos já existentes como
coluna: `valor_protocolado_centavos` é o **pedido** (o boletim que a Lotufo apresenta; congela no envio) e
`valor_atestado_centavos` é o **aprovado** (o que o órgão aprova; vigente = último evento de `medicao_atestos`).
Painéis, saldo e diretoria já leem "aprovado, senão pedido": só falta alguém gravar o aprovado. O motor cria o
passo que grava.

**Estados** (acrescenta dois antes do espelho; o resto é o de hoje):

| Estado | Entra quando | Por quem |
|---|---|---|
| `prevista` | cronograma vigente tem a competência e não há medição | sistema (como hoje) |
| `boletim_gerado` | a pessoa cria o boletim: período, valor pedido, planilha, acumulado anterior conferido | operação |
| `boletim_enviado` | o e-mail de encaminhamento ao fiscal sai pelo sistema, ou a pessoa registra o envio por fora (SMO/DocuSign) com data | sistema, no ato do envio; ou operação com justificativa |
| `espelho_gerado` … `recebida` | como hoje (spec 2026-09-21 §2) | como hoje |

A **aprovação não é estado, é evento** (`medicao_atestos`, com colunas novas): pode vir antes do espelho (SINFRA:
aprovada no SMO, depois NF) ou depois do protocolo (MT-PAR, Prefeitura, SES: boletim e NF vão juntos, a
fiscalização aprova depois). O estado diz onde a medição está no fluxo; o evento diz quanto o órgão aceitou e
quando. Órgão com `etapa` única no cadastro pula `boletim_enviado`: `boletim_gerado` → `espelho_gerado`.

**Tabelas e migração 042 (só acrescenta):**

- `medicoes`: `periodo_inicio`, `periodo_fim` (como em `espelhos`, obrigatórios a partir de `boletim_gerado`),
  `boletim_enviado_em`, `boletim_envio_origem` (`sistema`|`externo`), `numero_orgao` (nº da medição no órgão, quando
  difere do da Lotufo: Região Oeste e Coxipó 3ª têm quatro numerações). O CHECK de `estado` ganha os dois estados.
- `medicao_boletins` (evento): `medicao_id`, `versao`, `periodo_inicio`, `periodo_fim`, `valor_pedido_centavos`,
  `acumulado_anterior_centavos`, `arquivo` (PDF ou XLSX da planilha, pelo hash), `sha256`, `origem`
  (`manual`|`detectado`|`aceito`), `usuario_id`, `criado_em`, `motivo` (da versão nova). Vigente = maior versão;
  gerar de novo antes do envio cria versão; depois do envio é **reapresentação** (versão com `motivo` obrigatório,
  e o pedido congelado continua sendo o da versão enviada: a tela mostra os dois).
- `medicao_atestos` ganha `meio` (`smo`|`oficio`|`email`|`carimbo`|`outro`), `numero_orgao` (nº do processo ou
  do SMO), `arquivo`, `sha256`, `observacao`. Continua append-only.
- `envios.tipo` aceita `boletim`; `envio_medicoes` já liga.
- Carga: nada muda nas medições existentes; as que estão em `prevista` sem valor continuam onde estão.

**O que congela:** o valor pedido no `boletim_enviado` (hoje congela no protocolo, tarde demais: a SINFRA
aprova antes da NF). Reapresentação não descongela: é versão nova com motivo. O aprovado nunca congela, porque é
evento: glosa posterior é outro evento, e o vigente é o último.

**Quem clica, passo a passo:**

1. Operação: "Novo boletim" na obra → nº (sugerido: último + 1, com o nº do órgão opcional), período (sugerido: mês
   da competência), valor pedido, planilha arrastada; o sistema mostra o acumulado anterior (soma dos aprovados,
   senão pedidos) e o saldo, e avisa se o período se sobrepõe ao anterior ou pula um mês.
2. Operação: "Enviar ao fiscal" (SINFRA: e-mail com a planilha e o ofício de encaminhamento gerado da carta
   `boletim` em `cartas.yaml`, para os fiscais do contrato e cópias do órgão) **ou** "Registrar envio por fora"
   (data, meio, comprovante). Reserva atômica, envio único.
3. Engenharia ou operação: "Registrar aprovação": arrasta a capa do SMO (ou o ofício de aprovação, ou a foto do
   carimbo) → leitor determinístico (§2.3) preenche valor, data e nº → a pessoa confere e aceita. Sem leitura:
   três campos digitados. Valor aprovado ≠ pedido mostra a diferença na hora.
4. Daí em diante, o fluxo de hoje: espelho (o valor do espelho vem do aprovado, senão do pedido; não se digita),
   faturamento, nota, protocolo, RM.

**E-mail de protocolo:** o protocolo da nota (`protocolos`, etapa `nota`) continua como está. O e-mail novo é o de
**encaminhamento do boletim** (tipo `boletim`): assunto "CT/nnn/LT/aaaa - Nª Medição (MM/AAAA) - Obra", corpo da
família do órgão, anexos: ofício gerado, planilha e peças exigidas pelo órgão na etapa `medicao` (`orgaos.pecas`
já distingue naturezas). Onde o boletim entra no SMO/DocuSign e não por e-mail, o passo é "registrar envio por fora".

**Avisos gerados** (acrescentam ao catálogo §11):

| Aviso | Aparece quando | Some quando | Quem vê |
|---|---|---|---|
| Boletim do mês não gerado | dia 5 do mês seguinte à competência sem boletim, obra ativa não paralisada | boletim gerado | operação |
| Boletim sem aprovação | `boletim_enviado` há mais de 15 dias sem evento de aprovação | aprovação registrada | operação |
| Aprovado abaixo do pedido | evento de aprovação com valor menor que o pedido | reapresentação enviada ou diferença aceita com justificativa | operação, diretoria se > 10% |
| Medição fora de ordem | boletim com período que pula ou sobrepõe o anterior | corrigido | operação |

**Tela:** aba Medições da obra ganha a linha "Boletim" antes de "Espelho" na linha do tempo de cada medição, com
pedido, aprovado (data, meio, documento) e a diferença; o cartão "Novo boletim" substitui "Gerar espelho" como
primeiro passo (gerar espelho passa a ser o passo 4, habilitado pela aprovação ou por "seguir sem aprovação" com
justificativa, para as obras em que a NF vai junto). Lista de medições em andamento ganha os dois estados.

### 2.2 Motor de apostilamento (ciclo de reajuste por data-base e por competência)

**O que muda no conceito.** O ciclo continua sendo (contrato, data-base, ano) e o que o fecha continua sendo o
apostilamento (spec §7.2). O que falta é a **competência**: o apostilamento da SINFRA lista o reajuste mês a mês
vinculado ao nº da medição; a MT-PAR apostila um percentual e o reajuste é a aplicação mês a mês; a NF de
reajuste de uma competência não pode existir antes do apostilamento que a cobre (caso da Maternidade VG,
NF cancelada). O motor passa a acompanhar cada competência do ciclo: **prevista → pedida → aprovada → apostilada →
faturada → recebida**, e cruza as quatro fontes (planilha do pleito, boletim de reajuste, apostilamento, NF).

**Tabelas e migração 043 (só acrescenta):**

- `reajuste_previsoes` (evento): `contrato_id`, `data_base_mes`, `ciclo`, `competencia`, `valor_previsto_centavos`,
  `origem` (`pleito`|`apostilamento`|`manual`), `pleito_id`, `instrumento_id`, `usuario_id`, `criado_em`. Uma
  linha por competência por fonte; a previsão vigente de uma competência é a mais recente por origem na ordem
  apostilamento > pleito > manual. Nasce da planilha do pleito (lida por `openpyxl`, sem custo: aba e colunas
  fixas do modelo "Mem. e Cron. - Prev. de Reajuste"; fila humana se o modelo não casar) e do apostilamento
  (campo `competencias` do YAML, §2.4).
- `instrumentos` tipo `apostilamento_reajuste`: `dados` ganha `competencias: [{competencia, valor, medicao}]` e
  `periodo: {de, ate}` validados pelo cadastro; `percentual` continua para a MT-PAR.
- `medicoes` tipo `reajuste`: `data_base_mes` e `ciclo` (derivados da competência e das datas-base do contrato na
  criação; gravados para a 5 Bairros, que tem duas bases num ofício só, decidir por item é impossível: a medição
  de reajuste aponta para a base pela regra do cadastro `datas_base[].aplica_a`, D7).
- `pleitos` ganha `reemite_pleito_id` (reemissão após aditivo aponta para o anterior) e `instrumento_chave` (o
  apostilamento que o atendeu, preenchido pelo sistema quando o instrumento entra pelo cadastro).

**Estados por competência** (derivados, não gravados):

| Estado | Regra |
|---|---|
| `prevista` | existe previsão (pleito ou apostilamento) e não há medição de reajuste |
| `pedida` | medição de reajuste em `boletim_gerado`/`boletim_enviado` |
| `aprovada` | evento de aprovação na medição de reajuste |
| `apostilada` | apostilamento com a competência (ou percentual MT-PAR com `periodo` que a cobre) |
| `faturada` | nota emitida |
| `recebida` | baixa no RM |

Estado do ciclo (já existe: `futuro`, `pleito_pendente`, `apostilamento_pendente`, `apostilado`) ganha
**`reemitir`**: há aditivo de prazo ou valor assinado depois do último pleito enviado e nenhum pleito posterior.

**O que congela:** o valor pedido da medição de reajuste no envio do boletim (como na execução); as previsões são
eventos (versão nova a cada reemissão); o apostilamento é instrumento (não se altera; correção é instrumento novo
com `corrige`).

**Quem clica:** operação cria o pleito (já existe) e arrasta a planilha; o sistema lê as previsões e mostra
a tabela competência × previsto para conferência antes de montar a carta; o Leo aplica o apostilamento pelo
cadastro quando o termo chega (como hoje, com as competências); a operação cria a medição de reajuste **junto com
o boletim de execução** (o sistema sugere o valor: o apostilado da competência se houver, senão o previsto no
pleito, senão vazio; a pessoa confirma ou digita o da planilha); a aprovação entra pelo mesmo passo 3 de §2.1.
O sistema **não calcula índice nem valor**: só compara o que a pessoa digitou com o que está previsto e apostilado.

**E-mail:** o pleito (família A), a reiteração (família B, MT-PAR e Prefeitura) e o ofício de reajuste da Nª
medição (família C; na SINFRA é aba do caderno assinada pelo fiscal, logo "feito por fora"; na MT-PAR é ofício da
Lotufo que encaminha a NF, e sai pelo protocolo de nota que já existe com natureza `reajuste`). Novidade: a
**reiteração** como pleito tipo `reajuste` com `reemite_pleito_id`, corpo próprio em `cartas.yaml`.

**Avisos** (acrescentam a `reajuste_pleito` e `reajuste_apostilamento`):

| Aviso | Aparece quando | Some quando | Quem vê |
|---|---|---|---|
| Reajuste fora da previsão | pedido ≠ previsto vigente da competência (tolerância R$ 1,00) | reapresentação ou justificativa | operação |
| Reajuste sem apostilamento | medição de reajuste aprovada ou faturada em competência que nenhum apostilamento cobre | apostilamento carregado | operação; diretoria se soma > R$ 100 mil |
| Nota de reajuste antes do apostilamento | nota emitida em competência não apostilada | apostilamento carregado | operação (crítico) |
| Cronograma de reajuste a reemitir | ciclo em `reemitir` | pleito novo enviado | operação |
| Pedido de reajuste sem resposta | pleito enviado há mais de 120 dias sem apostilamento (MT-PAR e Prefeitura: reiteração) | reiteração enviada ou apostilamento | operação, diretoria |

**Tela:** aba Reajuste da obra, por data-base e ciclo: cabeçalho (aniversário, índice, pleito, apostilamento,
situação), tabela competência × previsto × pedido × aprovado × apostilado × nota × recebido, com a origem de cada
célula ao passar o mouse e a linha do tempo do ciclo (pleito, aditivos, reemissões, termo). Diretoria: o bloco
"reajustes esperando apostilamento" passa a somar por competência, com o valor já medido.

### 2.3 Leitor determinístico da capa do SMO (pedaço de C dentro de A+B)

Um leitor em `app/leitura_smo.py`, no padrão de `leitura_nfse`: regex sobre o texto da 1ª e 2ª páginas do pacote
do SMO (capa "Nª Medição Provisória", situação "APROVADA", "Data de realização", "Valor desta medição",
"Faturamento realizado acumulado – Preços iniciais", "Reajustamento", fins de vigência e execução, dias
paralisados). PDF sem texto (os envelopes DocuSign do BRT Lote 1): OCR local das 2 primeiras páginas, como nas
certidões; sem OCR, três campos digitados. Saída: proposta de evento de aprovação (valor, data, nº) e, como
subproduto, conferência dos fins de execução e vigência contra o cadastro (aviso "capa do SMO diz 24/02/2027,
cadastro diz 06/11/2026": é assim que o 10º apostilamento da MT-402 teria aparecido). Testes contra os textos
reais já extraídos no vault (copiados para fixture com nomes e números trocados).

### 2.4 Cadastro (YAML) e carga do histórico (opção A)

- `contratos/<obra>.yaml` ganha `garantia: {apolice, vigencia_fim, arquivo}` (já previsto na #65, vazio em
  produção), `instrumentos` completos (um por termo, com `corrige` quando for o caso) e **`cronograma`**:
  `[{chave, origem: contratual|aditivo|carta|smo, data, instrumento, itens: [{competencia, valor}]}]`; o
  carregador cria uma `cronograma_versoes` por entrada, com `criado_em` = data do documento (o congelamento de
  `previsto_efetivo` passa a respeitar a data do documento, não a da carga; migração só de leitura).
- `datas_base[]` ganha `aplica_a` (texto livre: "itens SICRO", "itens SINAPI") e `indice` passa a ser obrigatório.
- `cadastro carregar-medicoes <obra>.csv [--ensaio]`: colunas nº, nº do órgão, tipo, competência, período, valor
  pedido, valor aprovado, data da aprovação, meio, nº do órgão, data do protocolo da nota, NF, fonte. Regras: não
  toca medição existente com o mesmo (nº, tipo); se o valor difere, grava evento de aprovação com a fonte e deixa
  o pedido como está; estado da medição histórica = `recebida` se a NF está baixada no RM, senão `protocolada`.
  Relatório do ensaio por obra, aplicado só com o OK do Leo.

## 3. O que falta para os quatro motores atuais funcionarem de verdade

Evidência do levantamento (cruzamento de 20/10/2026; detalhe por obra na síntese e no vault).

### 3.1 Reajuste (`app/reajuste.py`)

| Falta | Evidência | O que fazer |
|---|---|---|
| Apostilamentos no banco | 1 instrumento `apostilamento_reajuste` (Granito) contra dezenas de termos nos documentos (Atalaia R$ 22,6 mi apostilados, MT-388 4º, Estações 2º, Leblon, MT-402, 5 Bairros, Cavalaria…); o aviso "apostilamento pendente" não fecha nunca | carga (A) + `competencias` no YAML (§2.2) |
| Ciclo por competência | SINFRA apostila mês a mês; Atalaia faturou R$ 862.909,55 de reajuste sem apostila; Alta Floresta R$ 5,75 mi acima dos instrumentos; MT-402 3º ciclo sem apostila | motor de apostilamento |
| Data-base e índice corretos | Atalaia com data-base 2016-11 (SICRO, sem índice); Terminais com INCC na data-base e DNIT no contrato (CT-366 já usa DNIT); Estações contrato DNIT × SMO INCC; 5 Bairros com duas bases num ofício só; `indice` vazio em 6 datas-base, BR-163 sem data-base, e o campo `indice_reajuste` do contrato com "SINAPI" ou "SICRO" (tabela de preços, não índice) em 19 das 22 obras | `indice` obrigatório, `aplica_a`, conferência obra a obra (D7) |
| Pleitos anteriores a 2026 | 19 pleitos, todos de 2026; o 1º ciclo de obras de 2022–2024 não existe no sistema | carga (A), só os que fecharam ciclo aberto |
| Reemissão após aditivo | 5 Bairros, MT-402, Estações reemitiram o cronograma após o TA; o sistema trata como pleito novo sem ligação | `reemite_pleito_id` e estado `reemitir` |

### 3.2 Painéis, curva e saldo (`app/paineis.py`)

| Falta | Evidência | O que fazer |
|---|---|---|
| Medições recentes | acumulado abaixo do documento em 15 obras (MT-388 faltam 11ª–13ª, R$ 8,6 mi; Leblon 26ª–28ª, R$ 15,2 mi; BRT 12ª–14ª, R$ 28,7 mi; Cultural 22ª–23ª; Maternidade 2ª–4ª; MT-402 24ª–27ª; Xtreme 13ª–14ª; Estações 5ª–6ª; Cavalaria 5ª–6ª; Terminais 1ª; Atalaia 44ª–46ª; Alta Floresta reajustes; Região Oeste reajustes; Orla 25ª e reajustes 21ª–25ª; Espaço Show 26ª) | carga (A); motor de medição evita repetir |
| Valor aprovado | 0 eventos de atesto; "atestado pendente" marca toda medição; BRT Lote 1 pede o dobro do aprovado em toda medição e a dashboard mostra o pedido | passo "registrar aprovação" (§2.1) |
| Valor vigente e saldo na mesma base | Alta Floresta: o vigente R$ 186,9 mi bate com o 8º TA porque na SES o reajuste entra por termo aditivo, mas o medido é a preços iniciais (base R$ 160,8 mi), e o saldo sai R$ 26,4 mi maior do que é; Deciolândia R$ 57,4 mi × R$ 66,2 mi (carga legada de R$ 1,2 mi sem documento, 2º TA de R$ 10,0 mi não carregado); Coxipó 3ª e Granito com centavos de diferença | instrumentos de valor um a um no YAML (A); saldo calculado só a preços iniciais, com o reajuste apostilado em série própria |
| Cota certa | Leblon 50% na dashboard × 49% no contrato (NF 50/50 com a consorciada); diretoria e QDOP saem na cota | D8 |
| Valor sem documento | Região Oeste nº 45 e 46 duplicam a 49ª e 50ª (+R$ 466 mil) e a 51ª tem valor sem boletim; Coxipó 3ª nº 11 duplica a nº 15 (+R$ 544 mil) e a nº 12 não tem documento; Coxipó 2ª com quatro valores sem fonte (6ª, 9ª, 10ª, 11ª); reajuste da 24ª do Leblon, da 33ª/34ª do Atalaia, da 21ª do 5 Bairros e da 32ª da MT-401 com valores que nenhum documento traz; BRT 3ª com o valor do cronograma repactuado no lugar do aprovado | correção como evento novo, com a fonte; duplicata cancelada com motivo |

### 3.3 Prazos e garantias (`app/prazos.py`, `app/garantias.py`)

| Falta | Evidência | O que fazer |
|---|---|---|
| Histórico de instrumentos | só o último TA de prazo por obra; `historico_texto` escreve "O 1º termo aditivo n.º 074/2021/01/14" para o 14º TA do Atalaia (a #40 já viu isso na MT-402) | um instrumento por termo no YAML (A); ordinal pelo nº do termo quando o cadastro é parcial |
| Garantia | `garantia_apolice` vazio nas 22 obras; 0 endossos; nos documentos 16 de 21 obras com garantia vencida ou ausente, 4 com cobertura; o aviso de garantia (#65) nunca disparou | carga (A) + aviso contra o fim de execução vigente (§4.4) |
| Paralisações | 2 obras no banco; documentos: Atalaia 185 dias, Região Oeste parada em 11/09/2026, Coxipó 3ª 21/11/2025 a 15/06/2026, Granito desde 08/06/2026, MT-402 93 dias (ok) | carga (A) |
| Fim de execução sem instrumento | Região Oeste: dashboard tem "4º TA" de 20/04/2026 (+12 meses) que não está na pasta; Coxipó 3ª: fim 22/10/2026 de "planejamento interno"; Deciolândia: 2026-06-29 sem termo encontrado (pasta incompleta) | marcar `fonte: conferir` no YAML e aviso "instrumento sem PDF" |
| Vigência vencida com obra andando | Alta Floresta (SES) e Xtreme (MT-PAR) com vigência expirada; o aviso de vigência depende de `vigencia_automatica` do órgão, que está certo; falta o dado | carga (A) |
| Retroativos | Atalaia 4 TAs assinados após o vencimento, Granito 3, MT-401 e BRT 1; o sinal `retroativo` existe e só aparece com os instrumentos carregados | carga (A) |

### 3.4 Cronograma e curva S (`app/cronograma.py`)

| Falta | Evidência | O que fazer |
|---|---|---|
| Versão por aditivo | 22 versões, todas de 04/09/2026 (carga), nenhuma por aditivo; Atalaia com 2 competências, Coxipó 2ª com 1 | `cronograma` no YAML com data do documento (§2.4) |
| Tela ou carga | não existe tela de versão de cronograma (backlog de 28/09/2026) e o cadastro não carrega | carga pelo YAML; tela fica fora |
| Linha de base honesta | a curva do SMO é refeita com o medido a cada aditivo (desvio ≈ 0 por construção); contra a versão anterior o atraso é de 16 a 48 p.p. em 7 obras | curva S com duas linhas: vigente e a anterior à última repactuação (§4.3, D9) |
| Previsto que ninguém mantém | `previsto_efetivo` congela pelo mês de criação da versão; como todas nasceram em 09/2026, o passado foi semeado e o futuro depende de versão que não vem | `criado_em` = data do documento na carga |

## 4. Automações que agilizam

1. **Aviso de pleito a partir do cronograma de reajuste.** Hoje o aviso nasce 30 dias antes do aniversário. Com as
   previsões por competência (§2.2) o aviso passa a dizer o valor em jogo ("R$ 213 mil previstos para o ciclo
   2026; pleito não enviado") e, após aditivo, "cronograma de reajuste a reemitir". A planilha do pleito é lida por
   `openpyxl`, sem custo.
2. **Ofício de reajuste gerado da medição.** Na MT-PAR e na Prefeitura o ofício de reajuste da Nª medição é da
   Lotufo: nasce do protocolo de nota com natureza `reajuste` (já existe) com o texto da família e a referência ao
   apostilamento (nº e competência) preenchida pelo motor; sem apostilamento que cubra a competência, o sistema
   avisa antes de montar.
3. **Carta de prorrogação com histórico automático.** `historico_texto` já existe; passa a ter os instrumentos
   todos (A) e, com `reajuste_previsoes` e o cronograma vigente, sugere o nº de dias pelo saldo a executar no ritmo
   dos últimos 6 meses (a pessoa confirma). Curva S do pedido anexada (xlsx gerado do cronograma vigente).
4. **Alerta de garantia contra o novo fim de execução.** Hoje o aviso de garantia conta dias até a própria
   vigência da apólice. Passa a comparar com o fim de execução vigente mais a folga do órgão: instrumento de prazo
   carregado que deixa a garantia aquém do novo fim gera "endosso necessário até dd/mm" no mesmo dia (o aviso
   `endosso_garantia` de 5 dias existe, mas só olha se o endosso foi entregue, não se cobre).
5. **Curva S na obra e na diretoria.** `CurvaS.tsx` já existe na obra; ganha a segunda linha (base anterior) e a
   marca dos aditivos; a diretoria ganha a curva da carteira (soma das obras ativas, na cota) e o desvio em p.p.
   por obra na tabela do QDOP.
6. **Conferência automática da capa do SMO** (§2.3) contra prazo e saldo: todo registro de aprovação confere fins
   de execução e vigência, valor do contrato e acumulado; divergência vira aviso "capa do SMO difere do cadastro".

## 5. Decisões para o Leo

| # | Decisão | Opções | Recomendação |
|---|---|---|---|
| D1 | Qual consolidação | A+B; A+C; só A | **A+B**, com A+C como plano B |
| D2 | Alcance da carga do histórico | todo o contrato desde a 1ª medição; só 2025 em diante; só o que falta para fechar o acumulado atual | **todo o contrato** nas obras ativas (é o que dá curva S e reajuste por ciclo); nas encerradas, só fechar o acumulado |
| D3 | Boletim por item ou só total | só total e período (v1); por item (planilha orçamentária na dashboard) | **só total na v1**; por item fica para quando a planilha editável entrar |
| D4 | Aprovação | evento (atesto) registrado à mão com documento; evento com leitor da capa do SMO desde a v1 | **leitor desde a v1**, só SINFRA; outros órgãos à mão |
| D5 | Onde o instrumento entra | só pelo YAML (regra de hoje); upload na dashboard que gera o YAML para o Leo aplicar | **só pelo YAML**; a dashboard só avisa "capa do SMO cita instrumento que o cadastro não tem" |
| D6 | Numeração canônica da medição | nº da Lotufo (como hoje) com `numero_orgao` opcional; nº do órgão canônico | **nº da Lotufo** + `numero_orgao` obrigatório onde difere (Região Oeste, Coxipó 3ª, Leblon pasta 30ª) |
| D7 | 5 Bairros, duas datas-base | reajuste por item aponta para a base (impossível sem planilha); medição de reajuste única com `aplica_a` textual e ciclo pelas duas; duas medições de reajuste por competência | **uma medição, duas bases** (o ofício é um só; o apostilamento também) |
| D8 | Cota do Leblon | 49% (contrato); 50% (NF e FRC) | **49% no contrato, 50% na regra do espelho** (a cota é do contrato; a NF segue o acordo do consórcio) |
| D9 | Linha de base da curva S | vigente; anterior à última repactuação; contratual original | **vigente e anterior à última repactuação**, as duas na tela |
| D10 | Aviso de garantia | contra a vigência da apólice (hoje); contra o fim de execução vigente + folga do órgão | **contra o fim de execução + folga** |

## 6. Ordem de entrega (prévia da fase 5)

1. Carga (A): YAML com garantia, instrumentos e cronograma; `carregar-medicoes`; 7 rodadas de 3 obras
   (sessão manual). Migração: nenhuma (040 já tem a garantia).
2. Motor de apostilamento: migração 043, `reajuste_previsoes`, leitura da planilha do pleito, estados por
   competência, 5 avisos, aba Reajuste. Risco: dinheiro.
3. Motor de medição: migração 042, estados `boletim_*`, `medicao_boletins`, colunas em `medicao_atestos`, e-mail
   `boletim`, leitor da capa do SMO, 4 avisos, tela. Risco: dinheiro e envio.
4. Automações 3, 4 e 5 (prazos, garantia, curva S); #255 continua fora.
