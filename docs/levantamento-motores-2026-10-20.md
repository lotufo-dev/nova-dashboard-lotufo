# Levantamento dos motores da dashboard contra os documentos das obras (fase 3, 20/10/2026)

Plano e fases: `docs/superpowers/plans/2026-10-19-levantamento-motores-sharepoint.md`. Proposta que sai daqui:
`docs/superpowers/specs/2026-10-20-motores-medicao-apostilamento.md`. Detalhe por obra (análises, consolidado,
CSVs da dashboard, cruzamento linha a linha): repositório privado `vault-licitacoes`, `obras/_sharepoint/<obra>/analises/`,
`obras/_consolidado-2026-10.md` e `obras/_dashboard-2026-10-19/`. Aqui só a síntese, sem dado pessoal.

**Fontes.** Dashboard: cópia de produção de 19/10/2026 (banco e cadastro YAML), lida só para leitura. Documentos:
espelho do SharePoint do Departamento de Engenharia (11.234 arquivos, 21 obras) e anexos dos itens enviados da
caixa do responsável pela engenharia (83 arquivos), lidos por 24 leitores Opus na fase 2 e conferidos pela sessão
principal (verdade-base: 1ª página da última medição e do último instrumento de prazo de cada obra). O cruzamento
linha a linha da fase 3 foi feito por 21 leitores Opus (um por obra) e arbitrado pela sessão principal, que
recomputou por conta própria os cabeçalhos da tabela 1 direto do banco.

**Fora do levantamento:** BR-163 (contrato privado com a concessionária, sem pasta no SharePoint da engenharia),
173 Chapada (encerrada, não copiada), e o motor de atraso de pagamento por órgão (sai pela #255).

## 1. Cabeçalho por obra: dashboard × documento

Valores cheios em R$ (a dashboard guarda o valor cheio; a cota é derivada). "Medido" = execução a preços iniciais,
acumulado das medições protocoladas/recebidas (dashboard) ou aprovadas pelo órgão (documento). "Falta" = medições
que o documento tem e a dashboard não. Fins de execução e vigência: vigentes pelo último instrumento.

| Obra | Medido dashboard (última) | Medido documento (última) | Falta na dashboard | Reajuste dash × doc | Execução / vigência | Garantia |
|---|---|---|---|---|---|---|
| 159 Atalaia | 35.871.920,05 (43ª 03/2026) | 36.076.746,73 (46ª 06/2026) | 44ª–46ª; buracos 32, 35–42 | 23.241.384,47 × 23.432.001,66 | batem (14º TA) | dash vazia; doc vencida 05/02/2026 |
| 161 Alta Floresta | 156.989.235,78 (42ª 12/2025) | 157.087.138,94 (42ª final) | 42ª refaturada (55.386,40 × 153.289,56) | **11.557,94 × 24.332.061,07** (só a 42ª na dashboard; faltam 39) | batem (9º TA); vigente 186,9 mi bate, mas o saldo mistura base com e sem reajuste (+26,4 mi) | dash vazia; doc vencida 27/03/2026 |
| 165 5 Bairros | 30.401.455,46 (31ª 06/2026) | 29.958.075,21 (31ª) | 32ª (sem pasta), 33ª só NF; buraco 23 | 2.631.743,35 × 2.567.837,65 | batem (8º TA) | dash vazia; doc cobre até 21/02/2027 |
| 166 Deciolândia | 48.521.843,69 (38ª 02/2026) | 22.704.548,27 (até 10/2024; 4 pastas) | pasta incompleta; no mesmo corte (10/2024) a execução bate ao centavo | no corte de 10/2024: 2.845.149,16 × 4.468.171,91 (falta ~1,62 mi) | dash 29/06/2026 e 28/09/2026 × doc 31/12/2024 e 31/03/2025 (1º TA, termo ausente) [CONFERIR] | ambas vazias |
| 167 MT-401 | 24.288.967,52 (32ª 11/2025) | 24.288.943,24 (32ª) | nenhuma; 32ª com valor da REV 00 (+24,18) e competência errada; 29ª +0,10 | 2.607.247,20 × 2.592.747,86 (32ª com valor sem fonte; faltam 3 negativos) | batem (8º TA) | dash vazia; doc vencida 28/04/2026 |
| 168 Região Oeste | 27.527.043,02 (51ª 06/2026) | 26.829.862,84 (50ª 05/2026; 51ª–54ª sem valor) | nº 45 e 46 duplicam a 49ª e 50ª (+466 mil); 51ª com valor sem boletim; numeração das cartas em 4 medições | **382.111,18 × 5.181.930,66** | dash 21/03/2027 (4º TA 20/04/2026) × doc sem termo na pasta [CONFERIR] | dash vazia; doc vencida 20/11/2024 |
| 171 Leblon | 64.662.201,66 (29ª 09/2026) | 79.860.706,92 (29ª) | 26ª–28ª (15,2 mi) | 2.071.702,35 × 2.970.375,18 (24ª com 7.932,70 a mais, sem documento) | batem (6º apost.) | dash vazia; doc cobre até 28/01/2027 |
| 172 MT-402 | 7.756.282,12 (23ª 01/2026) | 10.589.475,61 (27ª 08/2026) | 24ª–27ª de execução (o reajuste da 27ª existe) | 460.694,11 × 723.504,30 | batem (10º apost.) | dash vazia; doc vencida 24/03/2025 |
| 174 Espaço Show | 63.905.814,77 (25ª 06/2026) | 65.857.893,86 (26ª 07/2026) | 1ª, 24ª, 26ª | 3.622.830,41 × 3.886.751,49 | batem (7º TA) | dash vazia; doc vencida 27/06/2026 |
| 175 Orla | 22.390.425,16 (24ª 06/2026) | 23.310.726,19 (25ª 07/2026) | 1ª, 25ª (exatamente 920.301,03) | 850.323,82 × 1.410.111,40 (21ª–25ª) | batem (3º TA) | dash vazia; doc vencida 01/09/2026 |
| 176 Coxipó 3ª | 4.125.527,69 (20ª 07/2026, espelho gerado) | 3.652.544,12 (linhas com valor) | nº 11 duplica a nº 15 (02/2026); nº 12 sem documento; três numerações misturadas; falta a 13ª | 45.881,89 × 111.310,73 | dash 22/10/2026 (planejamento interno) × doc sem instrumento; vigência bate | dash vazia; doc vencida 30/04/2025 |
| 177 Cultural | 52.030.159,67 (24ª 09/2026) | 60.434.518,81 (24ª) | 1ª, 2ª, 22ª, 23ª | 3.187.108,60 × 4.821.266,03 | batem (3º TA) | dash vazia; doc vencida 03/04/2026 |
| 178 Coxipó 2ª | 4.823.573,78 (11ª 10/2025) | 4.303.541,21 (10ª 09/2025; 11ª sem valor) | 6ª, 9ª, 10ª e 11ª com valores sem documento (9ª: 186.076,45 × 290.194,68 na Lotufo × 1.255.531,65 na CI da Prefeitura) | 95.635,02 × 156.759,88 | dash 16/06/2026 × doc 21/11/2025 vencido; vigência bate; suspenso | ambas vazias |
| 179 BRT Lote 1 | 97.594.881,44 (15ª 09/2026) | 126.289.244,20 (15ª) | 12ª–14ª (28,7 mi); 3ª com o valor do cronograma repactuado (−41.333,01) | nenhum (bate) | batem (2º TA) | ambas vazias |
| 181 MT-388 | 14.763.923,05 (14ª 09/2026) | 25.402.707,61 (14ª) | 11ª–13ª (10,6 mi); as 11 que existem batem ao centavo; NF de reajuste da 8ª alocada na execução | 753.024,53 × 1.372.148,48 (idem) | batem (contrato) | dash vazia; doc cobre até 06/06/2027 |
| 182 Xtreme | 17.888.750,53 (15ª 09/2026) | 19.556.812,26 (15ª) | 13ª, 14ª; 12ª "prevista" embora protocolada e faturada; reajuste da 10ª alocado na execução | 1.299.320,46 × 1.593.763,59 | batem (2º TA); vigência vencida 16/10/2026 | dash vazia; doc vencida 16/07/2026 |
| 183 Granito | 3.605.315,13 (10ª 06/2026) | 65,92% de 5.469.054,85 | nenhuma | nenhum (bate); 1º apost. carregado | batem (3º TA) | dash vazia; doc vencida 26/04/2026 |
| 184 Maternidade VG | 337.189,95 (1ª 06/2026) | 882.035,13 (4ª 09/2026) | 2ª–4ª | 0 × 21.015,97 (NF cancelada, sem substituta) | batem; vigência termina antes da execução nos dois | dash vazia; doc até 25/09/2027 (não cobre) |
| 185 Estações BRT | 14.094.316,13 (7ª 09/2026) | 29.266.478,04 (7ª) | 5ª, 6ª; 4ª com 47.766,65 sem documento (SMO 4.798.235,46); a 7ª bate (inclui a devolução da glosa da 4ª); "1ª de projeto" é da Terminais | 856.687,78 × 1.822.198,94 (faltam 2 apostilamentos) | batem (1º TA) | dash vazia; doc vencida 31/07/2026 |
| 186 Cavalaria | 1.637.282,82 (4ª 06/2026) | 41,22% de 10.039.070,44 (7ª) | 5ª–7ª (7ª cancelada por erro) | 288.110,77 × 571.621,26 | execução bate (2º apost.); vigência 05/10/2027 × 01/11/2027 [CONFERIR] | ambas vazias |
| 187 Terminais BRT | 184.119,96 projeto (2ª 09/2026) | 556.496,40 (1ª + 2ª, só projeto) | 1ª (372.376,44; uma das NFs dela está lançada na Estações) | nenhum (data-base 04/2025 INCC × DNIT no contrato) | batem | dash vazia; doc até 12/03/2027, 8 dias antes da vigência |

Leitura da tabela: o acumulado da dashboard está **abaixo** do documento em 15 obras, **acima** em 3 (Deciolândia,
Região Oeste, Coxipó 3ª e 2ª, onde a pasta do SharePoint é que está incompleta ou a numeração é outra) e igual em 3.
Onde as medições existem nos dois lados, os valores batem ao centavo em quase todas (MT-388, Leblon 29ª, BRT 15ª,
Orla 25ª, Granito); as diferenças de valor por medição são raras (MT-401 32ª, Estações 7ª, Alta Floresta 42ª,
Coxipó 2ª 9ª). O problema é de **cobertura e atualização**, não de digitação.

## 2. Resultado do cruzamento linha a linha

84 arquivos de análise (21 obras × 4 motores) ganharam a seção "Divergência com a dashboard", com uma linha por item
comparável (medição, instrumento, data-base, apostilamento, pleito, garantia, competência do cronograma), o valor dos dois
lados, a fonte e a ação.

| Contador | Total |
|---|---|
| Linhas conferidas | 2.514 |
| Batem | 822 |
| Divergem | 664 (cerca de 450 só pela data de protocolo sintética) |
| Só no documento (falta na dashboard) | 799 |
| Só na dashboard (sem documento que sustente) | 100 |
| O documento não decide (conferir com a operação) | 129 |

## 3. O que cada motor mostra hoje contra o que os documentos mostram

### 3.1 Painéis, curva e saldo (`backend/app/paineis.py`)

**Hoje.** Medido = soma das medições em `protocolada`, `nf_emitida` ou `recebida`, pelo valor atestado quando há, senão pelo
protocolado. Saldo = vigente − medido. A curva compara o medido por competência com o previsto efetivo do cronograma.

**Documentos.** O medido real é o acumulado aprovado pelo órgão (capa do SMO na SINFRA, boletim assinado na MT-PAR, CI na
Prefeitura), que difere do pedido em 6 obras e vem depois de glosa ou revisora em 3.

Divergências:

- **Cobertura.** Faltam na dashboard 51 medições de execução e 92 de reajuste com documento, quase sempre as mais recentes
  (de 1 a 13 por obra). As maiores: BRT Lote 1 12ª–14ª (R$ 28,65 mi), Leblon 26ª–28ª (R$ 15,20 mi), Estações 5ª–6ª
  (R$ 11,39 mi), MT-388 11ª–13ª (R$ 10,64 mi), Cultural 22ª–23ª (R$ 8,40 mi), MT-402 24ª–27ª, Alta Floresta 39 reajustes
  (R$ 24,30 mi), Região Oeste reajustes (R$ 4,80 mi).
- **Valor aprovado.** Zero eventos de atesto em produção: a dashboard só conhece o pedido. Onde o órgão aprovou menos
  (BRT Lote 1 em toda medição, Atalaia, MT-401, 5 Bairros 23ª revisora, MT-402 revisora, Estações 4ª glosada), o medido da
  dashboard está acima do real.
- **Valor sem documento.** 13 medições com valor que nenhum documento traz: Região Oeste nº 45, 46 (duplicatas da 49ª e 50ª)
  e 51; Coxipó 3ª nº 11 (duplicata da nº 15) e nº 12; Coxipó 2ª 6ª, 9ª, 10ª e 11ª; Estações 4ª; Cavalaria 3ª; reajustes da
  24ª do Leblon, 33ª e 34ª do Atalaia, 21ª do 5 Bairros e 32ª da MT-401; BRT 3ª com o valor do cronograma repactuado.
- **Saldo na base errada.** Alta Floresta: o vigente inclui os reajustes incorporados por termo aditivo (regra da SES) e o
  medido é a preços iniciais; o saldo sai R$ 26,4 mi maior. Deciolândia: vigente R$ 57,4 mi contra R$ 66,2 mi
  (carga legada sem documento, 2º TA não carregado).
- **Nota alocada na medição errada** em 5 obras: NF de reajuste na execução (MT-388 8ª, Xtreme 10ª), NF de consorciada ou
  FRC como se fosse da Lotufo (Leblon 10ª e 29ª, BRT 2ª–11ª e 15ª), NF de um lote inteiro numa só medição (Orla 9ª,
  Espaço Show 9ª e 23ª). Isso distorce o "a receber" título a título.
- **Cota.** Leblon com 50% na dashboard e 49% no contrato (NFs 50/50 com a consorciada); diretoria e QDOP saem na cota.
- **Medição de outra obra.** A "1ª medição de projeto" da Estações (NF 2297) é da Terminais BRT.
- **Data de protocolo.** As 627 datas da carga legada são o último dia da competência, anteriores ao próprio ofício; o nº do
  ofício e do processo estão vazios. Só 13 protocolos (outubro de 2026, pelo sistema) têm data real.

### 3.2 Reajuste (`backend/app/reajuste.py`)

**Hoje.** Um ciclo por (contrato, data-base, ano); o ciclo fecha com um instrumento `apostilamento_reajuste` do mesmo ano;
aviso "pleito não enviado" 30 dias antes do aniversário e "apostilamento pendente" depois do pleito. O sistema não calcula
índice nem valor.

**Documentos.** A SINFRA apostila o reajuste **mês a mês, vinculado ao nº da medição**, e a NF de reajuste de uma competência
não pode sair antes do apostilamento que a cobre (Maternidade VG: NF cancelada). O ofício do pleito é reemitido a cada
aditivo. A MT-PAR apostila um percentual sobre o saldo. O reajuste de uma competência pode ser negativo (MT-401 9ª, 12ª, 15ª;
5 Bairros 8ª).

Divergências:

- **Apostilamentos.** 1 carregado (Granito) contra mais de 60 nos documentos (Atalaia 20, 5 Bairros 14, MT-402 5, MT-401 7,
  MT-388 4, Estações 2, Espaço Show 2, Orla 2, Cultural 2, Xtreme 2, Leblon 2, Cavalaria 1, Coxipó 2ª e 3ª 1 cada, Região
  Oeste 6º, Alta Floresta 3 por termo aditivo).
- **Avisos falsos** hoje em produção por apostilamento não carregado: Espaço Show e Cultural ("pleito não enviado" com o
  3º apostilamento assinado), Orla ("apostilamento pendente há 234 dias", já na diretoria), Xtreme ("pleito pendente").
- **Pleitos.** 19 carregados, todos de 2026; faltam os de 2024 e 2025 (todas as obras antigas) e os de 2026 em MT-401
  (CT/154, assinada sem protocolo), Região Oeste (CT/116), Cavalaria (CT-365, 14/10/2026), Maternidade (CT-364), Cultural
  (CT/171/LT/2025), Terminais (CT-366 substitui o CT-145). Pleitos "enviado" já atendidos continuam abertos em 5 obras.
- **Datas-base e índices.** 5 Bairros com os índices trocados entre as duas datas-base (SINAPI é março, SICRO é janeiro);
  Atalaia 2016-11 sem índice; Xtreme com o termo dizendo "maio de 2025" por erro; `indice_reajuste` do contrato com
  "SINAPI" ou "SICRO" (tabela de preços do orçamento, não índice) em 19 de 22 obras, enquanto o contrato manda INCC (edificações)
  ou FGV/DNIT por grupo (rodoviárias); Estações e Terminais com DNIT no contrato e INCC na prática.
- **Reajuste sem apostila ou fora da previsão.** Atalaia (R$ 862.909,55), Alta Floresta (R$ 5,75 mi acima dos instrumentos),
  MT-402 (3º ciclo), 5 Bairros (33ª), Cavalaria (7ª), Granito (10ª: apostilado e não medido). O motor por ano não enxerga
  nada disso.

### 3.3 Prazos e garantias (`backend/app/prazos.py`, `backend/app/garantias.py`)

**Hoje.** Execução e vigência vigentes = originais do contrato + último instrumento assinado; histórico da carta de prazo a
partir dos instrumentos carregados; sinal de retroativo; folga por órgão; garantia por apólice + endossos; paralisação por
instrumento.

**Documentos.** Cada obra tem de 1 a 14 instrumentos de prazo; 9 obras com execução vencida e obra andando; 16 de 21 com
garantia vencida ou ausente; aditivo assinado depois do vencimento em 4; paralisações formais em 5.

Divergências:

- **Fins vigentes batem em 17 obras.** Divergem: Região Oeste ("4º TA" de 20/04/2026 sem documento), Coxipó 3ª (22/10/2026
  sem instrumento), Coxipó 2ª (16/06/2026 sem instrumento; o 2º TA só prorroga vigência), Cavalaria (vigência 05/10/2027
  contada do fecho em vez da assinatura: 01/11/2027), Deciolândia (a conferir: pasta incompleta).
- **Fins "originais" errados em 17 obras:** a linha do contrato traz os fins de um aditivo intermediário (o vigente na
  época da carga), e o início da vigência é a data da OS em 15 obras (a vigência conta da assinatura). Com isso o histórico
  da carta e o cálculo de folga começam de um ponto falso.
- **Histórico de instrumentos.** Só o último instrumento de prazo por obra está no banco; os anteriores viraram uma linha
  `carga-legado` de valor, datada do dia da carga. O texto automático da carta de prazo diz "1º termo aditivo" para o 14º do
  Atalaia; a #40 já viu o mesmo na MT-402.
- **Garantia:** vazia em 22 de 22 obras na dashboard; 0 endossos. Nos documentos, 4 obras cobrem o fim de execução
  vigente (5 Bairros, Leblon, MT-388, Terminais por 8 dias), 15 estão vencidas e 2 não têm apólice encontrada (Deciolândia,
  BRT Lote 1; Coxipó 2ª e Cavalaria também sem). O aviso da #65 nunca disparou.
- **Paralisações:** 2 no banco (MT-402, Coxipó 2ª com data das cartas); nos documentos, Atalaia (2, 185 dias), Região Oeste
  (parada em 11/09/2026 com medição final), Coxipó 3ª (21/11/2025 a 15/06/2026, contradizendo a suspensão de 04/08/2026 da
  dashboard), Granito (desde 08/06/2026 sem termo), 5 Bairros (2025). Eventos de suspensão/retomada da carga (04/08/2026 e
  21/09/2026) sem documento em MT-402, Coxipó 2ª e 3ª.
- **Pedidos de prorrogação:** 2 não carregados (Leblon CT/032/CCL/2026, 09/10/2026; Coxipó 2ª extinção 14/08/2026); pedidos
  já atendidos continuam "enviado" em 5 obras (a regra do motor reconhece o atendimento só quando o instrumento está no banco).
- **Recebimento definitivo** da MT-401 (SMO, 04/05/2026) não existe na dashboard, que mantém o contrato "ativo".
- **Vigência vencida com contrato ativo:** Alta Floresta (26/06/2026, sem 10º TA), Xtreme (16/10/2026), Coxipó 2ª
  (15/08/2026), Deciolândia (a conferir).

### 3.4 Cronograma e curva S (`backend/app/cronograma.py`)

**Hoje.** Versões por contrato; cada versão vale do mês em que foi criada; o previsto efetivo congela o passado. Não há tela
para criar versão nem carga pelo cadastro: as 22 versões são da carga de 04/09/2026.

**Documentos.** O cronograma vigente é a curva impressa pelo SMO em cada boletim (refeita com o medido a cada aditivo) ou a
carta de repactuação da Lotufo; existe uma versão por aditivo de prazo.

Divergências:

- **As 22 versões são obsoletas ou sem documento-fonte.** 21 de 21 obras: a versão é a linha de base original (Orla, Granito,
  Deciolândia, Alta Floresta), um pedido superado (Atalaia CT-012, MT-388 CT-233, Leblon CT/022, Estações CT-144, Cavalaria
  CT-122, Terminais CT-145, Região Oeste 08/2025) ou uma tabela que nenhum documento sustenta (Espaço Show, Cultural, Xtreme,
  Maternidade com R$ 303 mil a mais, BRT com R$ 1,39 mi a mais).
- **Realizado lançado como previsto.** Em 9 obras a versão tem um item único com o acumulado realizado até a carga
  (Atalaia 97% em 2022-05, Região Oeste R$ 25,9 mi em 2022-04, 5 Bairros R$ 29,5 mi em 2023-04, MT-401 R$ 23,3 mi em 2023-03,
  MT-402 R$ 7,8 mi em 2024-03, Leblon R$ 55,0 mi em 2024-04, Coxipó 3ª R$ 2,9 mi em 2024-12, Coxipó 2ª R$ 4,3 mi em 2024-11).
  A curva mostra 90% a 100% "previsto" no primeiro mês e um atraso histórico que não existiu.
- **Horizonte curto.** A versão termina antes do fim de execução vigente em 13 obras (Alta Floresta 03/2024, Orla 06/2025,
  Granito 11/2025, Cultural 12/2025, Xtreme 10/2025, Espaço Show 01/2025, Cavalaria 08/2026, Estações 06/2026, MT-388 sem
  2026, MT-402 11/2026, Coxipó 2ª 11/2024, Deciolândia 11/2023, Atalaia sem 04/2026). Para essas obras o previsto efetivo é
  zero nos meses atuais e a curva compara medido com nada.
- **Realizado incompleto** em todas as obras onde faltam medições (3.1); em Região Oeste e Coxipó 3ª, dobrado por duplicata.
- **Desvio na tela × desvio real** (setembro de 2026): Leblon −44,07 p.p. × −16,87; MT-388 "quase em dia" × −40,82; BRT
  −20,16 × −0,77; Região Oeste −41,65 × −2,36; Estações 100% previsto × 50,74%; Terminais 64,08% previsto × 0,43%.

## 4. Lista de divergências por motor (o que carregar, criar ou corrigir)

| Motor | Carregar no cadastro (YAML) | Criar na dashboard | Corrigir (evento novo, com fonte) |
|---|---|---|---|
| Painéis | cota do Leblon (49%) | 51 medições de execução e 92 de reajuste; aprovação (atesto) de cada medição aprovada, com data e meio | 13 valores sem documento; 5 obras com NF alocada na medição errada; 1ª de projeto da Estações → Terminais; competência da 32ª da MT-401, da 11ª da Coxipó 2ª e do reajuste da 1ª da Cavalaria; 12ª da Xtreme "prevista" → protocolada; 20ª da Coxipó 3ª parada em espelho |
| Reajuste | mais de 60 apostilamentos com competências e valores; pleitos de 2024 e 2025; 6 pleitos de 2026; índice certo em 19 contratos; datas-base do 5 Bairros; `aplica_a` | medições de reajuste negativas (MT-401 3, 5 Bairros 1) e as que faltam | pleitos "enviado" já atendidos (5 obras) ligados ao instrumento |
| Prazos e garantias | garantia e endossos das 21 obras; um instrumento de prazo por termo (≈90); fins originais e início da vigência pela assinatura em 17 contratos; 5 paralisações e 2 retomadas; recebimento definitivo da MT-401; 2 pedidos de prorrogação; data do 3º TA da MT-401 e do 1º TA da Estações | nada | eventos de suspensão/retomada de 04/08/2026 e 21/09/2026 sem documento (MT-402, Coxipó 2ª e 3ª); fim de execução da Coxipó 2ª e 3ª e "4º TA" da Região Oeste marcados como sem documento; vigência da Cavalaria |
| Cronograma | uma versão por aditivo com a data do documento (≈60 versões), inclusive a vigente de cada obra | nada | as 22 versões da carga marcadas como superadas (não apagadas) |


## 5. O que está sobrando ou desatualizado na dashboard (objetivo 6)

Registro que o documento contradiz, ou que não tem documento que o sustente, ou que ficou do legado sem uso.

- **Registro com valor sem documento:** 13 medições (3.1), 2 duplicatas (Região Oeste nº 46, Coxipó 3ª nº 11), a 51ª de
  teste do Atalaia (já cancelada), a 7ª da Cavalaria cancelada por "erro" mas faturada, a "1ª de projeto" da Estações.
- **Datas sintéticas:** 627 datas de protocolo iguais ao último dia da competência; 592 medições criadas em 4 segundos de
  04/09/2026 e marcadas `recebida` pelo corte de 22/09/2026, sem comprovante (todas as obras); linhas `carga-legado` e
  aditivos datados do dia da carga (04/08/2026) em vez da assinatura (Atalaia, Região Oeste, Orla, 5 Bairros, MT-401 3º TA,
  Coxipó 2ª e 3ª, Alta Floresta).
- **Cadastro do contrato:** fins "originais" de aditivo intermediário (17 obras); início da vigência pela OS (15);
  `indice_reajuste` com tabela de preços no lugar do índice (19); `data_base` do contrato vazia onde `contrato_datas_base`
  tem o valor (campo antigo, redundante).
- **Eventos sem documento:** suspensão de 04/08/2026 e retomada de 21/09/2026 ("carga inicial: estado do cadastro legado")
  em MT-402, Coxipó 2ª e 3ª.
- **Cronograma:** as 22 versões (3.4).
- **Pleitos abertos já atendidos:** 5 Bairros CT-166, MT-401 CT-137 (cópia de 14/08 sem protocolo), Estações CT-144/CT-260/
  CT-192, Cavalaria CT-122/230/253, Granito CT-135, Orla CT-068, Terminais CT-145.
- **Tabelas do legado sem uso** no banco de produção: `arquivo_*` (detecção, sugestões, mensagens observadas, planilhas:
  2.743 linhas) e `medicao_documentos` de fonte `engenharia_sp`/`controladoria_sp` (178 linhas do SharePoint antigo).
- **Fora do levantamento e sem pasta:** BR-163 (contrato privado, 8 medições, cronograma de 31 meses), a conferir com a
  controladoria por outro caminho.


## 6. Padrões que atravessam as obras e mudam o produto

1. **Cobertura, não digitação.** Onde a medição existe nos dois lados, o valor bate; a dashboard perde as medições
   mais recentes porque a carga foi única (04/09/2026) e nada a alimenta depois além do espelho.
2. **Protocolo da medição não existe como documento na SINFRA** desde 2025: o fluxo é SMO + DocuSign + NF. A data
   que existe para todas as obras SINFRA é a aprovação no SMO ("Data de realização"). Carimbo de protocolo só na
   Prefeitura de Cuiabá e, em parte, na MT-PAR (SIGA). As 627 datas de protocolo da carga legada são o último dia
   do mês da competência; só 13 protocolos (outubro de 2026) têm data real.
3. **Valor pedido × valor aprovado divergem com frequência** (BRT Lote 1 em toda medição, Atalaia 5 vezes, MT-401
   3, Leblon, MT-402, 5 Bairros). A dashboard tem as duas colunas, mas ninguém grava a segunda: 0 eventos de atesto.
4. **Reajuste sem apostilamento ou fora da previsão apostilada** em 9 obras; a SINFRA apostila mês a mês vinculado
   ao nº da medição, logo o ciclo anual do motor precisa descer à competência.
5. **Garantia vencida ou ausente em 16 de 21 obras**; o endosso que cada aditivo exige quase nunca está na pasta.
   A dashboard tem o campo (migração 040) e nenhum valor.
6. **Prazo de execução vencido com obra andando em 9 obras**, aditivo assinado depois do vencimento em 4; o sinal
   `retroativo` do motor de prazos só aparece com os instrumentos carregados, e só o último está.
7. **Cronograma vigente vive na curva impressa pelo SMO**, refeita com o medido a cada aditivo (desvio ≈ 0 por
   construção); a curva S honesta é contra a versão anterior à última repactuação (atrasos de 16 a 48 p.p.).
8. **A medição mais recente está no Outlook em 7 obras**; a pasta do SharePoint fica um a dois meses atrás.
9. **Arquivo com conteúdo trocado** (ofício de uma obra na pasta de outra, OS citando outro contrato): o nome do
   arquivo não identifica a fonte; só o conteúdo.
