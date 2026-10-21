# Motores de medição e apostilamento: o que o Outlook mostra e as decisões pendentes (20/10/2026)

Complemento à síntese `docs/levantamento-motores-2026-10-20.md` e à spec
`docs/superpowers/specs/2026-10-20-motores-medicao-apostilamento.md` (ainda não corrigida; a correção depende das
decisões da seção 5). Fonte: caixa do responsável pela engenharia no Outlook, itens enviados e recebidos de 2025 em
diante, só leitura (a caixa só existe desde 13/05/2026). Pessoas pelo papel; endereços e nomes ficam fora, como manda
`.claude/rules/dados-de-teste.md`.

## 0. Vocabulário (vale daqui em diante, inclusive na spec)

- **Boletim de medição**: o PDF que o órgão emite (na SINFRA, o pacote do SMO: capa, resumo, ficha do contrato,
  cálculo reajustado, cronograma) com o resumo da medição e os nomes dos fiscais e da Lotufo para assinar.
- **Planilha/carta de medição**: o que a Lotufo envia antes, com o valor pedido (planilha editável, ofício CT, memórias,
  diários, ensaios, croqui).
- Fatos informados pelo dono do produto em 20/10/2026: o SMO chega às vezes por e-mail, às vezes por WhatsApp; vai
  para o DocuSign com o que chegou no momento, nem sempre completo; assinatura parada não é problema (o aviso
  "boletim recebido sem assinatura" sai da spec).

## 1. Fluxo por órgão, com os e-mails que o provam

Os e-mails estão na caixa do responsável pela engenharia, em cópia em todos. "Operadora" = quem protocola pela
Lotufo; "engenheira" = quem cobre o Consórcio Integra BRT; "diretor" = quem assina pelo consórcio ou pela Lotufo.

### SINFRA, superintendência de obras rodoviárias (SUEF II: MT-388)

Ordem confirmada, com datas da 14ª medição da MT-388:

1. **Lotufo envia a planilha/carta** (pedido). 06/10/2026, operadora → SUEF II, "CT-337-LT-2025 - 14ª Medição
   (09_2026) - IC_082_2025 - Porto Espiridião": "Encaminho arquivo para protocolo. Encaminho ainda arquivos editáveis
   para envio à supervisora e fiscalização". Mesmo texto para a 13ª (CT-303, 09/2026) e a 12ª (CT-271, 08/2026).
2. **SUEF II protocola e manda à supervisora.** 07/10/2026, SUEF II: "Seguem protocolos da medição, com isso, o
   processo entra para análise na supervisora". Antes, em 06/10: "todos os documentos, bem como o ofício, devem estar
   devidamente assinados".
3. **Supervisora devolve a planilha analisada** (revisão com o valor que ela aceita). 09/10/2026, supervisora →
   SUEF II: "Segue medição analisada, juntamente com relatório mensal contendo os ensaios" (anexo: planilha Rev01).
   O mesmo em 11/09 (13ª), 12/08 (12ª), 15/07 (11ª), 16/06 (10ª).
4. **SUEF II emite o boletim no SMO e o envia por e-mail.** 09/10/2026, SUEF II: "Após análise técnica da 14ª
   Medição Provisória e Reajustamento, a medição e o reajuste estão propícios a serem digitalizados contendo todas
   as assinaturas dos envolvidos. Valores: PI R$ 1.568.399,34; R R$ 98.386,80", anexos: Relatório de Capa, de Resumo,
   Ficha do Contrato Analítica, Cronograma Físico-Financeiro, Boletim de Desempenho, cálculo de medição reajustada
   (PDFs pequenos, 13 a 90 KB) e a planilha Rev01. Mesmo e-mail para a 13ª (14/09) e a 12ª (13/08). Só o SUEF II
   manda o boletim por e-mail; nas outras superintendências não há e-mail (ver abaixo).
5. **Lotufo monta o envelope no DocuSign.** 09/10/2026 17:17, DocuSign em nome da operadora: "Complete com o
   Docusign: 14ª_Medição_(09_2026)_-_IC_082-2025_-_MT-388_P._Esperidião.pdf" (um PDF só, 535 páginas, com a capa do
   SMO na p. 2). Concluído em 14/10/2026 10:42.
6. **Quem assina**, pelo certificado do DocuSign do cronograma da mesma medição (envelope de 14/10/2026): a
   supervisora, o diretor da Lotufo e o fiscal da SINFRA (pelo endereço institucional que o cadastro já guarda como
   destinatário dos assinados). O responsável pela engenharia e a operadora entram só como cópia.
7. **SUEF II confere o pacote assinado.** 14/10/2026, SUEF II: "No documento não consta o cronograma físico-financeiro
   de evolução mensal emitido pelo sinfralog" e, antes, "a empresa deverá encaminhar justificativa de atraso do
   cronograma". Lotufo responde no mesmo dia com os arquivos assinados e a justificativa.
8. **NF.** 15/10/2026, operadora → SUEF II, "Nota fiscal - 14ª Medição e Reajuste da 14ª Medição (09/2026) -
   082/2025/00/00-SINFRA - MT-388": "notas fiscais, certidões e documentos de regularidade".

### SINFRA, SAGPM/SUOESP (Leblon, BRT Lote 1, Estações BRT, Terminais BRT)

1. **Lotufo envia a planilha/carta.** Leblon: 05/10/2026, operadora, "29ª Medição (09/2026) - Complexo Leblon", zip
   "para supervisora e fiscalização". BRT: 02/10/2026, "15ª Medição (09/2026) - BRT - 041/2025", carta CT/052/BRT/2026
   "em complemento ao e-mail anterior, arquivo editável e croqui". Estações: 02/10/2026, engenheira, "7ª Medição e
   Reajuste (09/2026) - Estações BRT - IC 176/2025": "Encaminho arquivos assinados para protocolo. Encaminho ainda
   arquivo editável com o objetivo de facilitar a análise e eventuais apontamentos por parte da fiscalização" (anexo:
   ofício CT-346 assinado + zip da planilha).
2. **O boletim chega da fiscalização.** Leblon: 14/10/2026, fiscal da SINFRA → operadora, "Caderno da 29ª Medição
   Complexo Leblon IC 012/2024": "Encaminho o caderno da 29ª medição para assinatura e emissão de NF no valor de:
   Preços iniciais: R$ 2.219.697,96", com o zip por link do Google Drive (sem anexo). Para a 26ª (03/07) e a 27ª
   (05/08) o mesmo fiscal só pediu ensaios. BRT, Estações e Terminais: **não confirmado por e-mail** (nenhuma mensagem
   dos fiscais com o boletim; é o caso do WhatsApp).
3. **DocuSign.** Leblon 29ª: envelope de 14/10/2026 13:45 com "2 - Relatório de Capa, 8 - Cronograma, 5 - Resumo da
   Medição 29 SINFRALOG, 13 - Ensaios, 12 - Croqui", concluído 13:52; Lotufo devolve ao fiscal às 13:58 ("Encaminho,
   em anexo, arquivos assinados"). BRT 15ª: envelope de 09/10/2026 com "Relatório de Capa (2), Ficha (4), Resumo (1),
   Cronograma (2), Planilha Resumo 15ª, Diagrama de Localização, Diagrama Linear, Mapa Pluviométrico, Memórias",
   concluído às 17:07. Estações 7ª: envelope de 07/10/2026 com "Relatório cálculo de medição reajustada, Relatório de
   Capa…", concluído às 18:39. Para a 12ª e a 14ª do BRT, a operadora devolveu o zip "Complete com o Docusign
   Relatório de Capa" aos fiscais ("DOCUMENTOS ASSINADOS - 12ª MEDIÇÃO (06/2026) - INTEGRA BRT", 16/07/2026).
4. **NF** no mesmo dia ou no seguinte: Leblon 13/10 (antes do e-mail do caderno: o boletim já tinha chegado por
   outro canal), BRT 09/10 ("arquivos por link do OneDrive"), Estações 07/10 (com a capa do SMO anexa), Terminais
   15/09 (1ª, "arquivos assinados, notas fiscais, documentos e certidões", capa do SMO de 11/09 anexa).

### SINFRA, SUEF I (MT-402), SUPU (5 Bairros) e SACID (Cavalaria)

1. **Lotufo envia a planilha/carta**, sempre em 01/10/2026 pela operadora: "CT-334-LT-2026 - 28ª Medição (09_2026) -
   IC 019-2024 - MT402", "34ª Medição e Reajuste (09/2026) - IC 161/2022" e "7ª Medição (09/2026) - Cavalaria - IC
   004/2026", todos com "arquivo assinado para protocolo" + "arquivos editáveis para envio a supervisora e fiscalização"
   (ou "para facilitar a análise da fiscalização").
2. **Protocolo devolvido**: SUPU, 08/09/2026, "Re: 33ª Medição e Reajuste (08/2026) - IC 161/2022": "Segue em anexo
   protocolo da 33ª medição para conhecimento e acompanhamento".
3. **Boletim**: não confirmado por e-mail em nenhuma das três.
4. **DocuSign**: MT-402 28ª, envelope de 14/10/2026 "28ª Medição e Reajuste (09_2026) - MT402.pdf" (dois PDFs:
   medição e reajuste), concluído 20:38; Cavalaria 7ª, envelope de 08/10/2026 "Relatório de Resumo da Medição -
   2026-10-08T162517.476.pdf, Diários de Obras", concluído 21:23.
5. **NF** à caixa dos assinados da SINFRA: MT-402 27ª em 14/09 e 01/10 (medição e reajuste em e-mails separados),
   5 Bairros 33ª em 16/09, Cavalaria 7ª em 08/10 ("nota fiscal, documentos, certidões e documentos assinados").

### MT-PAR (Cultural, Espaço Show, Orla, Xtreme, Granito)

1. **Lotufo envia ofício CT com a NF e as certidões, direto ao protocolo.** 07/10/2026 e 08/10/2026, "CT-342-LT-2026 -
   24ª Medição - Complexo Cultural MTPAR", "CT-343 - Reajuste da 24ª", "CT-361 - 15ª Medição - Complexo Xtreme",
   "CT-362 - Reajuste da 15ª": "Encaminho arquivo para protocolo. Solicito devolutiva com os dados (nº de protocolo)".
2. **O protocolo da MT-PAR responde** no dia seguinte com o número e, no reajuste, "Foi iniciada a abertura do processo
   de pagamento MTPAR-PRO-2026/02017 no sigadoc" (08/10/2026).
3. **DocuSign** só do ofício: envelope de 07/10/2026 "CT-342-LT-2026 - Complexo Cultural - 24ª Medição (09.2026).pdf,
   CT-343…", concluído 19:00, PDFs anexos ao e-mail de conclusão.
4. **Boletim da MT-PAR e quem o assina: não confirmado por e-mail.** Nenhuma mensagem da fiscalização da MT-PAR com
   boletim; a única da fiscal é uma Nota Técnica sobre suspensão (19/08/2026). O SharePoint mostra boletins
   "Provisória" com campo de assinatura da fiscalização (ver síntese).

### Prefeitura de Cuiabá (Região Oeste, Coxipó 2ª e 3ª)

1. **A Lotufo faz o boletim e protocola fisicamente.** 08/06/2026, operadora → fiscal, "46ª medição (05/2026) -
   Região Oeste": "Seguem os arquivos editáveis e complementares para protocolo. Informo que os documentos devidamente
   assinados foram protocolados fisicamente". Coxipó 3ª: 03/09/2026, operadora → fiscal, "12ª Medição (06/2026 e
   07/2026) - Res. Coxipó 3ª etapa": "ajustes solicitados" (anexos: o boletim da Lotufo da 12ª medição e do reajuste,
   relatórios fotográficos, croqui); fiscal responde "Recebido" (04/09).
2. **A Prefeitura aprova e pede a NF.** 13/05/2026 (Coxipó 2ª, 9ª), 21/08/2026 (Região Oeste, reajustes 40ª e 41ª)
   e 20/10/2026 (Coxipó 3ª, "20ª" de 07/2026): e-mails "Solicitação de NF e certidões" da Prefeitura, respondidos com
   as notas. A NF, portanto, sai depois da aprovação, a pedido do órgão.
3. **Quem assina o boletim**: a Lotufo (assinado antes do protocolo físico); assinatura da fiscalização não
   confirmada por e-mail (no SharePoint, as planilhas recentes da Região Oeste só têm a assinatura da Lotufo).

### SES (Alta Floresta) e DNIT

- **SES: não confirmado.** Nenhum e-mail de medição da obra na caixa (a última medição, 42ª, é de 12/2025, antes da
  caixa existir; a reemissão de 07/2026 não deixou e-mail de medição). Vale o que o SharePoint mostra: compilado
  montado pela Lotufo (ofício, NF, certidões, ART, diário, fotos, cronograma, boletim, memória) e protocolo no SIGADOC.
- **DNIT: não há obra do DNIT** no levantamento; "DNIT" aparece só como índice de reajuste (tabelas FGV/DNIT).

## 2. MT-388 e Leblon: existe planilha/carta antes do SMO?

Sim, nas duas. MT-388: 06/10/2026 ("CT-337… arquivo para protocolo + editáveis", antes do boletim de 09/10); 13ª em
09/09 e 12ª em 13/08 seguem o mesmo rito. Leblon: 05/10/2026 ("29ª Medição (09/2026) - Complexo Leblon", zip para
supervisora e fiscalização, antes do caderno de 14/10). A planilha/carta existe em todas as sete obras SINFRA com
e-mail no período; a pasta do SharePoint da MT-388 e do Leblon é que não a guarda.

## 3. E-mails do DocuSign como fonte do boletim

- **Chegam para quem**: para cada signatário e para quem o remetente copia. O responsável pela engenharia recebe
  todos como **cópia** ("enviou-lhe uma cópia"), não como signatário; o certificado de 14/10/2026 o lista em "Eventos
  de cópia". Depende, portanto, do hábito da operadora de copiá-lo (aconteceu em 100% dos 9 envelopes vistos).
- **Trazem o PDF anexo?** Só quando o envelope é pequeno. Com anexo: cronograma da 14ª MT-388 (216 KB + certificado),
  CT-342/343 da MT-PAR (700 KB cada), cálculo reajustado da Estações (07/10), CT-366 (15/10). Sem anexo: o pacote
  inteiro da 14ª MT-388 (535 páginas), 28ª MT-402, BRT 15ª (capa + ficha + resumo + cronograma + planilha + memórias),
  Cavalaria 7ª (resumo + diários). Ou seja: o e-mail de conclusão é confiável como **registro de que assinou e quando**
  (nome do envelope, data, certificado com os signatários quando anexo), e não como fonte do PDF do boletim.
- **A capa do SMO está sempre no envelope?** Nos 5 envelopes SINFRA vistos, sim (como arquivo separado ou como p. 2 do
  pacote único). Não dá para garantir que estará sempre, porque o envelope é montado com "o que chegou no momento".
- **Conclusão**: o DocuSign não serve como fonte automática do boletim. Serve como fonte do evento "assinado em". A
  fonte do boletim por e-mail só existe no SUEF II (PDFs pequenos, separados); nas demais superintendências e na MT-PAR
  o boletim chega por outro canal e precisa ser arrastado por alguém.
- **Regra do produto a lembrar**: "não lê e-mail" (spec 2026-09-21 §13, decisão de 24/09/2026 que tirou a leitura do
  Graph). Qualquer leitura automática de e-mail, mesmo só do DocuSign, reverte essa decisão.

## 4. Numeração nos assuntos e corpos

- **SINFRA**: uma numeração só, a do SMO, igual à da Lotufo ("14ª Medição (09_2026)", "29ª Medição Complexo Leblon",
  "7ª Medição e Reajuste (09/2026) - Estações", "15ª Medição (09/2026) - BRT", "34ª Medição e Reajuste (09/2026)",
  "28ª Medição (09_2026) - MT402", "7ª Medição (09/2026) - Cavalaria").
- **MT-PAR**: uma numeração só ("24ª Medição - Complexo Cultural", "15ª Medição - Complexo Xtreme").
- **Prefeitura de Cuiabá**: duas numerações na mesma obra e no mesmo mês. Região Oeste: 08/06/2026 a carta ao fiscal
  diz "46ª medição (05/2026)" e 18/06/2026 a NF à Prefeitura diz "50ª medição e reajuste (05/2026)". Coxipó 3ª:
  03/09/2026 "12ª Medição (06/2026 e 07/2026)" ao fiscal; 19/10/2026 "Emissão NF 20ª medição e Reajuste (07/2026)" ao
  faturamento e 20/10/2026 "nota fiscal referente à 20ª medição no período de julho/2026" à Prefeitura.
- **Decisão (fato, D6)**: o número canônico é o do órgão, porque é o que vai na NF, no empenho e no pagamento; o número
  da Lotufo fica guardado como apelido onde difere (só Prefeitura). Na SINFRA e na MT-PAR os dois coincidem.

## 5. Decisões

### Decididas por fato comprovado (sem escolha a fazer)

- **D3, boletim por item ou total**: só o total, com a planilha anexada. A planilha de medição é feita fora (xlsx
  Rev01 que vai e volta da supervisora); a dashboard registra o total pedido e o total aprovado.
- **D4, aprovação**: o aprovado é o boletim do órgão (SINFRA: SMO; Prefeitura: "Solicitação de NF"; MT-PAR: ofício com
  NF, aprovação formal não confirmada). Entra pelo PDF arrastado; leitor determinístico da capa do SMO na v1, só para
  a SINFRA.
- **D6, numeração**: número do órgão canônico, número da Lotufo como apelido (seção 4).
- **D11, pedido na SINFRA**: obrigatório, não opcional. As sete obras SINFRA com e-mail mostram a planilha/carta antes
  do boletim.
- **Aviso "boletim recebido sem assinatura"**: sai (assinatura parada não é problema).
- **Aviso "aprovado abaixo do pedido"**: fica só como diferença mostrada na tela; vira aviso à diretoria apenas acima
  de 10%, porque a revisão da supervisora é a regra na SINFRA, não a exceção.
- **O e-mail da planilha/carta é padronizado** ("Encaminho arquivo para protocolo. Encaminho ainda arquivos editáveis
  para envio à supervisora e fiscalização", com ofício assinado + zip): tem o mesmo formato do envio de nota que a
  dashboard já faz.

### Decididas pelo dono do produto em 20/10/2026

| # | Escolha | Decidido | O que muda para a equipe |
|---|---|---|---|
| E1 (= D1) | Qual consolidação | **A+B** (carga + motores, 17 a 23 dias) | A operadora registra o pedido e o boletim na dashboard em vez de só no Outlook |
| E2 (= D2) | Alcance da carga do histórico | **todo o contrato nas obras ativas**; nas encerradas, só fechar o acumulado | 7 rodadas de 3 obras de conferência antes de a curva S ficar completa |
| E3 | Quem envia a planilha/carta | **a dashboard envia**, aceitando reenvio de revisão (Rev01, Rev02…) e "enviado por fora" com data e protocolo | A operadora anexa o ofício assinado e o zip na dashboard e clica "enviar"; o SIGA devolvido fica na medição; o e-mail sai da conta dela, como hoje |
| E4 | Como o boletim entra | **só por arrasto do PDF, com o leitor da capa do SMO**; mais o aviso "pedido enviado há mais de X dias sem boletim registrado", X por órgão (SINFRA SUEF II e SAGPM 15 dias, SUEF I/SUPU/SACID 20, Prefeitura 30, SES 30; MT-PAR não tem o passo) | Quem recebe o boletim (e-mail, WhatsApp ou DocuSign) arrasta o PDF na medição; nada muda no hábito de assinar |

Ajustes do dono do produto: o aviso "aprovado abaixo do pedido" fica para a operação em qualquer diferença (para
decidir se contesta ou reapresenta) e para a diretoria acima de 10%; os itens não confirmados (MT-PAR, SES e as
superintendências sem e-mail) ficam marcados como pendentes na spec (seção 7) e o motor aceita "feito por fora" nesses
órgãos.

O que fica inalterado da spec: D5 (instrumento só pelo YAML), D7 (5 Bairros, uma medição com duas bases), D8 (Leblon
49% no contrato e 50% no espelho), D9 (curva S com duas linhas), D10 (garantia contra o fim de execução + folga).

### O que mudou na spec (aplicado em 20/10/2026)

- §2.1: trocar "o boletim nasce na dashboard" por "a planilha/carta nasce na dashboard e o boletim do órgão entra
  nela" na SINFRA; manter "boletim da Lotufo nasce na dashboard" na Prefeitura e na SES; MT-PAR igual à SINFRA sem SMO.
  Estados: `planilha_enviada` (com protocolo SIGA) → `boletim_recebido` (aprovação como evento, com o PDF) →
  `assinado` (data do DocuSign, feito por fora) → espelho, nota, protocolo. Sem e-mail de encaminhamento ao fiscal
  separado: é o próprio envio da planilha/carta.
- §1: motor de medição de 8 a 10 dias para 5 a 7; A+B de 20 a 26 para 17 a 23 dias.
- §2.1 avisos: sai "boletim sem aprovação"/"sem assinatura"; "aprovado abaixo do pedido" só na tela e à diretoria acima
  de 10%; entra "planilha enviada sem boletim há mais de 20 dias" (a mediana SUEF II é 3 a 8 dias).
- §5: todas as decisões marcadas como decididas; §7 lista as pendências (MT-PAR, SES, canal do boletim nas
  superintendências sem e-mail).
