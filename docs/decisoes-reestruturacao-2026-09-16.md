# Diário de decisões da reestruturação (a partir de 2026-09-16)

Método combinado com o dono em 2026-09-16: uma decisão por vez. Para cada uma, o Claude propõe
como faria e por quê; o dono decide e justifica; o Claude analisa a justificativa (o que ela ganha,
o que custa); a decisão fica registrada com o efeito nos itens de `inventario-fica-ou-sai-2026-09-16.md`.
Ao final, as decisões e justificativas são relacionadas numa explicação única do produto, que vira a spec.

Decisões já tomadas antes deste diário (mesma data):
- A dashboard NOVA é a base; a antiga é fonte de funções e será desligada.
- Acesso só pela rede interna.
- A aba de licitações sai.

**Mudança de método (mesma data):** em vez de o Claude propor decisão por decisão, o dono expõe
as ideias dele por tópico; o Claude analisa cada ideia contra o que existe (antiga e nova), registra aqui,
e ao final formula qual é a objeção real do dono à dashboard nova, para o dono confirmar.
O roteiro abaixo fica como lista de tópicos a cobrir, não como ordem obrigatória.

## Roteiro das decisões (ordem prevista)

| # | Decisão | Decide o quê no inventário |
|---|---|---|
| D1 | Centro da operação: obra ou fila | bloco D inteiro, A11, C11 |
| D2 | O que a home de quem opera mostra e com que limiares | bloco A |
| D3 | O que a diretoria vê: número principal (cota ou cheio), tabela central, o que vira relatório | blocos B e I |
| D4 | Página da obra: abas e campos de cadastro | bloco C |
| D5 | Reajuste: por índice, avanço automático, prazo por órgão, valor calculado ou não | bloco E |
| D6 | Certidões: fonte (SharePoint ou upload), entidades e tipos, leitores, OCR, pacote | bloco F |
| D7 | Perfis: perfil financeiro, permissão por obra, sessão | bloco G |
| D8 | Avisos por e-mail e desligamento dos fluxos do Power Automate | bloco H |
| D9 | Custo e margem: fora até quando e sob que condição | B16, J6 |
| D10 | Ordem de entrega dos blocos | plano |

Após D10: síntese das decisões e justificativas → spec em `docs/superpowers/specs/2026-09-16-reestruturacao-design.md` → plano de implementação.

---

## T1. Tela inicial de quem opera

**Ideias do dono.**
- Não gosta de "sugestões a decidir". Não quer mais o motor de leitura de planilha do SharePoint; não quer
  "medições no órgão sem NF" nem "pendências" na home.
- Quer que o sistema seja essencial e entre na rotina para ATESTAR informações (registrar fatos), não para
  revisar palpites.
- Os espelhos "já são gerados no sistema"; após emitir o espelho, uma opção "medição protocolada" que uma
  estagiária pode marcar sempre.
- Home: avisos de prazos de vigência e de reajuste anual; "Medições protocoladas X/X"; valor protocolado R$;
  valor total das medições do mês passado protocoladas.

**Análise do Claude.**
- Corte do motor de planilha: concorda (maior gerador de ruído: 24 sugestões para 12 medições; 10 MB por obra).
- Espelho como porta de entrada = a ideia mais forte: a medição nasce ao gerar o espelho (obra, nº,
  competência, valor já conhecidos); "protocolada" vira um clique com data. Na nova o espelho NÃO existe
  (fase 7); na antiga roda por Power Automate + Office Script + Word no OneDrive. Esse fluxo é a peça viva
  mais importante do legado e precisa ser reconstruído dentro da nova (ou ligado a ela) antes do resto.
- Avisos de vigência/reajuste: existem parcialmente (60 d); reajuste anual correto exige data-base por
  índice e último reajuste no contrato (E1/E2 do inventário).
- Os 3 números da home saem só da tabela `medicoes`, sem integração; faltam definir denominador e qual data
  manda (ofício × competência).
- Sai sem substituto: aviso de medição parada no órgão; sugestão do Claude: coluna discreta na lista, sem
  alarde.
- Hipótese para a síntese: a objeção é ao princípio "observar em vez de registrar" da spec; o dono quer
  "registrar no ponto de passagem obrigatório (espelho) e calcular a partir daí".

**Pendências de esclarecimento (perguntadas em 2026-09-16).**
- Corte é só da planilha ou de toda a detecção (Outlook e RM)? Claude recomenda manter o casamento de NF
  do RM como avanço automático de estado, com a dúvida virando botão dentro da medição.
- Onde o espelho é gerado hoje (Power Automate da antiga?).
- Ordem real: protocolo → atesto → espelho, ou espelho junto com o ofício?
- Denominador de "X/X" e data que manda (ofício × competência) nos 3 números.

**Efeito no inventário.** A5, A6, A7, A10, A11 saem; D2–D11 caem (fila deixa de ser central); C9 (espelho)
sobe para primeiro bloco; E1/E2 confirmados; H1 fica pendente da resposta sobre Outlook.

**Respostas do dono (2026-09-16).**
1. Detecção: sai a leitura de planilha E a de e-mail; fica SÓ o casamento de NF do RM.
2. O espelho é gerado hoje no fluxo do Power Automate da dashboard antiga (Office Script + Word no OneDrive).
3. Ordem REAL do processo: órgão informa a medição por canal não mapeável (e-mail, WhatsApp, foto) →
   engenharia gera o espelho e manda ao faturamento (faturamento) pelo Outlook → faturamento emite a(s) NF(s) e
   devolve → engenharia monta a carta de protocolo conforme a obra e emite as certidões necessárias → tudo
   vai ao órgão pelo Outlook com remetente/destinatário/texto padronizados (= data do ofício).
4. A data que manda é a do ofício.

**Análise do Claude (2026-09-16).**
- ACHADO PRINCIPAL: a nova modela a ordem errada. Spec e código assumem Prevista → Protocolada → NF →
  Recebida e o código recusa NF anterior ao protocolo. No processo real a NF vem ANTES do protocolo e o
  valor informado pelo órgão é o PRIMEIRO dado. Máquina de estados correta: Informada pelo órgão (pessoa,
  ao gerar o espelho) → Espelho enviado (sistema) → NF emitida (RM) → Protocolada (clique com data do
  ofício, ou automático ao gerar a carta) → Recebida (RM). Provável raiz da objeção: o sistema pede um
  protocolo que ainda não aconteceu e chama de "glosa" o valor de origem.
- Dois ganchos de rotina: espelho (medição nasce com valor) e carta de protocolo (data, nº do ofício e
  certidões anexadas saem do próprio ato). Certidões exigidas viram lista POR CONTRATO, não só por CNPJ.
- Espelho: (a) nova chama o fluxo do Power Automate existente e registra a medição no mesmo ato (dias);
  (b) reconstruir em Python com os 57 modelos + regras das planilhas-motor (fase 7, semanas). Recomendação:
  (a) primeiro, (b) depois.
- Três números da home com data do ofício: protocoladas X de N obras ativas no mês; Σ valor com ofício no
  mês; idem mês anterior. Denominador "obras ativas" assumido.
- Sai do código: sincronizacao_graph, deteccao, padrões, planilhas_config, tela Microsoft 365. Cliente
  Graph fica guardado para uso futuro (pasta de certidões, rascunho de e-mail).

**Efeito no inventário (atualizado).** H1 SAI; H2 FICA; D1 MUDA (nova máquina de estados); C9 e C4
(carta de protocolo) viram os dois primeiros blocos; F1 MUDA (exigência por contrato); A12 confirmado.

**Ideia do dono (ainda T1): enviar o e-mail de protocolo pelo sistema, sincronizado com o Outlook,
e o envio = protocolada.** Decisão: espelho pela opção (b), reconstruir o gerador em Python na nova.

**Análise do Claude.** Viável e é o desenho mais limpo: envio via Graph com permissão delegada
`Mail.Send` (sem consentimento de admin por padrão; app e login delegado já existem). A mensagem aparece
em Itens Enviados; a resposta do órgão chega normal. Regra: "protocolada" = aceite do Graph, gravando
data/hora, destinatários, assunto, id da mensagem e anexos (append-only); falha no envio não marca nada.
Caixa corporativa exige `Mail.Send.Shared` + caixa compartilhada (pendência antiga da fase 6). Anexos > 3 MB
por sessão de upload (até 150 MB). Tela: botão "Protocolar ao órgão" na medição com NF emitida → monta
e-mail pelo padrão da obra (destinatários, assunto, texto) + carta + NFs + certidões → prévia → confirmar.
Alternativas descartadas: rascunho no Outlook (sem leitura, o sistema não sabe que saiu); Outlook COM
(exige sessão de usuário; produção roda como serviço).
Opção (b) do espelho exige autorização para ler `~/dev/lotufo-automacao-medicao` (motor, cadastro de
obras, modelos), hoje proibido; sem isso a reconstrução erra retenção por dedução. PEDIDO ao dono.

**Efeito no inventário.** H4 ganha um segundo uso (envio de protocolo, além do e-mail diário); D-protocolo
vira ato de envio; A13 (já tratei) para protocolo deixa de ser necessário.

**Respostas do dono (2026-09-16).** 1. Autoriza a leitura de `~/dev/lotufo-automacao-medicao`
(memória `automacao-medicao-autorizada`). 2. O protocolo sai da caixa de QUEM manda o e-mail.

**Análise do Claude.** Token do Graph passa a ser POR USUÁRIO (hoje é um refresh token único em arquivo):
cada pessoa conecta a própria conta Microsoft uma vez (código de dispositivo) numa tela de perfil; o
e-mail sai da caixa dela; a auditoria registra quem protocolou. Mudança pequena em `graph.py` + tela
"conectar minha conta". Quem usa qual conta (estagiária × dono) é decisão operacional, não do sistema.

**Fechamento do T1 (2026-09-16).** Denominador de "X de N" = obras ativas (confirmado). Home de quem opera:
avisos (vigência/execução, reajuste anual por índice com prazo de ofício; cada linha com obra, dias, valor);
medições protocoladas X de N obras ativas no mês pela data do ofício; valor protocolado no mês; total do
mês anterior. Sem sugestões, pendências ou "parada no órgão".

---

## T2. A medição, passo a passo dentro do sistema

**Respostas do dono (2026-09-16).**
1. Ao gerar o espelho a pessoa digita: competência, valor da medição (obra ou projeto), valor do reajuste
   (se houver) e número da medição. Só isso; hoje é assim na antiga e basta. Retenções saem de regra
   específica por obra, "que tem que ser analisada minuciosamente para replicar".
2. NFs múltiplas por medição: verificar na dashboard antiga.
3. Reajuste é medição separada, com espelho e modelo próprios.
4. Carta/e-mail de protocolo: mapear no Outlook os e-mails enviados das últimas medições (todas as obras):
   modelo, texto, destinatários, CC, anexos, para o sistema gerar automaticamente.
5. Glosa/reapresentação: não sabe; verificar no Outlook se há caso.
6. Vale guardar a evidência que o órgão mandou (foto, PDF) anexa à medição.

**Ações do Claude (2026-09-16).** Caixa do dono lida via conector Microsoft 365 (conta do dono; exemplo real de protocolo em 21/08/2026: "CT-289-LT-2026 - 22ª Medição
- Complexo Cultural MTPAR" para o protocolo da MTPAR + fiscal, 5 cópias internas, corpo padrão
"Encaminho arquivo para protocolo..."). Dois levantamentos disparados em paralelo: (a) mapeamento de
protocolos, espelhos, retornos do órgão, glosas e FRC nos últimos 12 meses; (b) regras de espelho por
obra (nº de saídas/NFs, eixo, retenções, modelos, gabaritos) na antiga e no motor da automação.
Resultados entram aqui quando chegarem.

**Resultados (2026-09-16).** Relatórios completos em `docs/espelho-regras-por-obra-2026-09-16.md` e
`docs/mapeamento-emails-medicao-2026-09-16.md`.
- NFs múltiplas: SIM em 8 das 19 obras do motor. Eixos: execução × reajuste (todas), município (MT-388,
  Estações, BRT, Atalaia), consorciada (Leblon 50/50, Atalaia 80/20, BRT 49/49/2), fonte de recurso
  (Coxipó 3ª), projeto (BRT, Estações), cota (Deciolândia 33,33%, valor digitado é o cheio). Bloco zerado
  não emite. O motor NÃO calcula: lê células da planilha-motor; o Python reimplementa as fórmulas por obra
  (tabela no relatório) e prova contra 14 notas de gabarito + MT-402 + extenso.
- Quem opera o ciclo é a operadora (o dono em cópia; 12 enviados em 4 meses). A caixa só existe desde
  2026-05-13.
- Protocolo: 3 famílias (MTPAR, SINFRA por superintendência, Prefeitura/supervisora); corpo fixo por
  família; assunto por template; CT-{nnn}-LT-{ano} é contador sequencial GLOBAL; MTPAR separa medição e
  reajuste, SINFRA junta e exige XLSX editável + limite 25 MB + ordem de check-list; fiscal nominal muda
  com o tempo (cadastro editável com histórico). MTPAR nunca devolve nº de protocolo → "protocolada =
  envio" é a regra certa.
- Espelho ao faturamento: destinatários e corpo fixos (faturamento; consorciada quando houver);
  um .docx por NF.
- Glosa: nenhum caso pós-protocolo em 4 meses; correções são sempre no arquivo, antes da NF. Máquina de
  estados não precisa de "glosa após protocolo"; precisa de "revisão antes do espelho".
- FRC: a controladoria emite e numera à mão; sistema só dispara/registra.
- IBS/CBS: zero no motor e nos modelos; entra como trabalho novo no espelho.

**Decisões do dono (2026-09-17).**
- **Número do CT: preenchido MANUALMENTE.** O sistema não gera nem controla o contador; é campo da tela de
  protocolo, obrigatório, gravado junto com o envio.
- **O PDF de protocolo o SISTEMA monta** (carta + medição + certidões consolidados num arquivo só).
- **as operadoras com o mesmo acesso de operação.**
- Pediu verificação: os nomes de arquivo dos anexos variam por obra? (suspeita que consórcio, ex. BRT, é
  diferente). Levantamento disparado no Outlook.

**T2.1 — Padronização dos nomes de arquivo (APROVADA pelo dono em 2026-09-17).**

Levantamento em `docs/nomes-arquivo-por-obra-2026-09-17.md`: 17 obras, 17 convenções, com erros reais
(`114-09-26`, `ESTAÇOES` sem til, `06ª` × `5ª`, espaços duplos, ano errado no reajuste da Cavalaria,
`ECOMIND` virando `ENCOMIND`). Consórcio difere em 5 eixos (consorciada no nome, município como sufixo,
EXECUÇÃO/PROJETO no miolo, FRC com numeração própria, sigla do ofício LT → CCL/CO). MT-388 não é consórcio
e mesmo assim duplica por município: os eixos reais são **quantas entidades emitem** e **quantos municípios
recebem**, não "é consórcio".

**Modelo único aprovado** (vale para todo arquivo que o SISTEMA gera):

```
{DOCUMENTO} - {obra} - {nº}ª {Natureza} ({MM.AAAA})[ - {consorciada}][ - {município}].{ext}
```

- DOCUMENTO: `ESPELHO`, `OFÍCIO`, `CARTA`. No ofício, o número vem na frente:
  `CT-{nnn}-{SIGLA}-{ano} - {obra} - {nº}ª {Natureza} ({MM.AAAA}).pdf`, sigla do cadastro (LT, CCL, CO).
- obra: nome curto cadastrado, um por contrato, sempre igual.
- nº: dois dígitos com zero à esquerda (ordena certo na pasta).
- Natureza: `Medição` | `Reajuste` | `Projeto` (substitui Reaj., Reajustes, Reajustamento da).
- competência: sempre presente, sempre `(MM.AAAA)`.
- consorciada e município: só quando a obra tem mais de uma entidade emissora ou mais de um município.

**Não muda** (vem de fora, o sistema só reconhece): nome da NFS-e (faturamento), da FRC (a controladoria, três
convenções), da planilha com sufixo de revisão (fiscalização) e o que passa pelo DocuSign (prefixa e trunca).
Risco baixo: nenhum órgão valida nome de arquivo; só a busca no histórico precisa aceitar os dois padrões
por um tempo.

**T2.2 — As duas telas (2026-09-17).**

*Gerar espelho* (na página da obra): a pessoa digita nº, competência, valor da medição/projeto e valor
do reajuste. O sistema aplica a regra da obra (rateio por município/consorciada, MO/material, INSS, ISS,
IRRF, extenso), mostra UMA LINHA POR NOTA para conferência antes de sair, cria a medição de execução (e a
de reajuste, se houver) com os documentos anexados, e envia o e-mail padrão ao faturamento e ao faturamento pela
conta de quem clicou. Bloco zero não gera.

*Protocolar* (na medição, quando as notas voltaram): a pessoa digita o CT (um ou dois, conforme o cadastro
da obra: MTPAR separa medição e reajuste, SINFRA junta), confere a prévia do e-mail (destinatários, cópias,
assunto, anexos com tamanho) e envia. O sistema monta a carta pelo modelo da obra, junta carta + notas +
certidões vigentes num PDF na ordem do check-list do órgão, divide em medição e reajuste se passar de
25 MB, anexa a planilha editável onde exigido. Ao enviar: medição vira protocolada com data, destinatários,
assunto, id da mensagem e anexos; falha no envio não marca nada.

**Decisões do dono (2026-09-17).**
1. O e-mail do espelho SAI DO SISTEMA também (mesma conta, mesmo caminho do protocolo).
2. Correção antes da nota: pediu recomendação → Claude recomendou e fica: GUARDAR AS DUAS VERSÕES
   (append-only; a mais recente é a vigente, a anterior aparece como substituída, com motivo opcional;
   só a vigente na tela do dia a dia).
3. Protocolar sem nota: pediu recomendação → Claude recomendou e fica: AVISAR E DEIXAR SEGUIR com
   justificativa auditada (mesmo padrão do checklist de certidões). Bloquear empurraria o protocolo para
   fora do sistema. Coxipó: a evidência do órgão cumpre o papel da nota na prévia. Região Oeste (por link):
   o sistema gera o pacote, a pessoa sobe e cola o link no corpo editável; se repetir, vira campo do
   cadastro "protocolo por link".

**T2.3 — Depois do protocolo (2026-09-17).** Nº do protocolo do órgão = campo opcional na medição,
digitado por quem recebeu, com o PDF anexado; sem obrigação (MTPAR não devolve). Nota e recebimento pelo
RM; dúvida do casamento vira botão "vincular nota" dentro da medição. Ciclo: informada pelo órgão →
espelho gerado e enviado → nota emitida → protocolada → recebida.

**T2 FECHADO pelo dono em 2026-09-17.**

---

## T3. Reajuste

**Respostas do dono (2026-09-17).**
1. O ofício de reajuste é solicitado ANTES do aniversário.
2. Dois ofícios separados, um por índice; cada índice tem o seu ciclo relativo ao próprio mês. Exemplo
   dado: "SICRO 08/2025 → reajuste em 09/2026; SINAPI 03/2025 → reajuste para 03/2026" (discrepância de um
   mês entre os exemplos; a confirmar: mês do aniversário ou mês seguinte).
3. O que marca o ciclo cumprido: verificar no SharePoint/Outlook.
4. Obras sem direito a reajuste: verificar no SharePoint/Outlook.
5. A home não mostra nada do ciclo vigente além do prazo.
Pediu levantamento no Outlook de como os pleitos saem (assunto, destinatário, anexos). Disparado.

**Cadastro antigo (backup de 2026-08-04, lido em 2026-09-17), datas-base por índice das 22 obras ativas:**

| Obra | SINAPI | SICRO | Obs. |
|---|---|---|---|
| Atalaia (Oriundi) | — | 11/2016 | |
| Alta Floresta (SES) | 10/2021 | — | |
| 5 Bairros | 03/2022 | 01/2022 | dois índices, datas DIFERENTES |
| Deciolândia | 10/2021 | 10/2021 | dois índices, mesma data |
| MT-401 | 01/2022 | 01/2022 | dois índices, mesma data |
| Região Oeste | 05/2021 | 01/2021 | dois índices, datas DIFERENTES |
| Leblon | 09/2023 | — | |
| MT-402 | — | 04/2023 | |
| Espaço Show | 02/2024 | — | |
| Orla | 03/2024 | — | |
| Coxipó 3ª (RES3) | 09/2023 | 09/2023 | dois índices |
| Complexo Cultural | 06/2024 | — | |
| Coxipó 2ª (CT392) | 05/2024 | 05/2024 | dois índices |
| Integra BRT | 01/2025 | — | sem "último reajuste" |
| MT-388 | 01/2024 | 01/2024 | dois índices |
| Xtreme | 05/2024 | — | |
| Granito | 06/2025 | — | sem "último reajuste" |
| Maternidade VG | 11/2024 | — | |
| Estações BRT | 04/2025 | — | sem "último reajuste" |
| Cavalaria | 03/2023 | — | |
| Terminais BRT | "-" | "-" | sem data-base cadastrada |
| Rota do Oeste (BR-163, privado) | "-" | "-" | sem data-base |

- O campo "UltReaj" do cadastro antigo é o ÚLTIMO ANIVERSÁRIO (data-base + N anos), não a data do pleito
  (ex.: Complexo Cultural base 06/2024, UltReaj 06/2026). Ou seja, a antiga nunca guardou quando o pleito
  saiu; o sistema novo precisa desse marco de verdade.
- "PercDireito" é a COTA no consórcio (80, 50, 49, 33,3, 18), não "direito a reajuste". Não existe campo
  de direito a reajuste em lugar nenhum; a resposta à pergunta 4 depende do Outlook/SharePoint.
- Sete obras com dois índices; em duas (5 Bairros, Região Oeste) as datas divergem, o que confirma a
  necessidade de dois ciclos independentes.

**Levantamento Outlook + SharePoint (2026-09-17), relatório em `docs/reajuste-pleitos-2026-09-17.md`.**
Contradiz duas respostas do dono, com documento:
- (1) "Ofício antes do aniversário": só na MTPAR (−2 a −26 dias). Na SINFRA o ofício sai DEPOIS, 40–55
  dias após o dia 1º do mês de aniversário, porque traz o I1 calculado e o índice FGV só sai em meados do
  mês seguinte. Não existe regra de 60 dias em documento algum.
- (2) "Dois ofícios separados por índice": no 5 Bairros (única obra com duas datas-base e SINAPI/SICRO como
  índice) é UM ofício, CT/234/LT/2026, "mês de aniversário JANEIRO e MARÇO", com duas colunas na memória e
  cada item da planilha apontando para uma data-base.
- Competência inicial = MÊS DO ANIVERSÁRIO (4 evidências). Exemplo do dono corrigido: SICRO 08/2025 →
  08/2026.
- Ciclo cumprido = TERMO DE APOSTILAMENTO homologado (NF de reajuste foi cancelada por falta dele;
  Terminais BRT: ofício em 05/2026, processo nem aberto em 09/2026). Três estados por competência:
  pleiteado, aprovado, faturado.
- Sem direito a reajuste: nenhuma evidência. Sem reajuste visível no período: Coxipó 3ª, Oriundi, Integra
  BRT, Deciolândia, Espaço Show (checar contrato).
- Índice: INCC único nas edificações; setorial FGV/DNIT por grupo nas rodoviárias; SINAPI/SICRO como
  índice só no 5 Bairros. "BaseSINAPI/BaseSICRO" do cadastro antigo = mês da data-base do orçamento.
- Ofício da família A é reemitido a cada aditivo: não serve como chave de ciclo.
- Fórmula das planilhas: I = TRUNC((I1−I0)/I0; 4), R = TRUNC(V×I; 2); índice pode ser negativo.
- Complemento MTPAR/PMC/SES (§9 do relatório): três regimes (INCC único com K por período; múltiplos
  índices setoriais por grupo, IN 59/DNIT; percentual sobre saldo por apostilamento no Granito). Alta
  Floresta: K não encadeado, sempre contra o Io original. Espaço Show 2º ciclo começou no mês SEGUINTE
  (única exceção). Maternidade: medições renumeradas. Coxipó 2ª: rótulos de coluna trocados na planilha.

**Proposta do Claude para o modelo (2026-09-17), a decidir pelo dono:**
- Unidade = (contrato, data-base): até duas por contrato, cada uma com mês de aniversário e rótulo livre
  (INCC, setorial FGV/DNIT, SINAPI, SICRO). O índice em si NÃO é calculado (E8 continua fora).
- Marcos por ciclo, registrados por ato humano: (1) pleito enviado (ofício família A, gerado e enviado
  pelo sistema como o protocolo, CT manual); (2) apostilamento homologado (nº e data, PDF anexo) = ciclo
  cumprido; a medição de reajuste continua marcando a competência.
- Aviso da home: uma linha por (contrato, data-base): "aniversário em MÊS; pleito ainda não enviado" a
  partir de 30 dias antes do aniversário até o pleito sair; depois "pleito enviado em DD/MM, apostilamento
  pendente há N dias" até o apostilamento entrar. Farol por dias. Sem regra de 60 dias.
- Reemissão do ofício por aditivo: novo pleito no mesmo ciclo, sem reabrir o ciclo.
- "Obra sem reajuste": campo booleano no contrato, default falso; sem evidência de caso real.
- Competência inicial do ciclo: campo registrado (default mês do aniversário), não deduzido.
- O alerta "reajuste sem par" da nova SAI.

**MODELO APROVADO pelo dono em 2026-09-17 (versão resumida que ele aprovou):**
- Por obra: mês de aniversário (um ou dois relógios) + nome do índice como texto. Sem cálculo de índice.
- Por ano e por relógio: (1) aviso na home a partir de 30 dias antes do aniversário até o pleito sair;
  (2) ofício de pleito enviado pelo sistema (CT manual) → aviso vira "apostilamento pendente há N dias";
  (3) apostilamento registrado (nº, data, PDF) → aviso some, ciclo fechado; (4) medições de reajuste
  seguem o fluxo normal.
- Sai o "60 dias antes"; sai o alerta "reajuste sem par"; o que fecha o ano é o apostilamento.
- Cadastro por obra: mês(es) de aniversário e marcação "sem reajuste".
- Pendente de resposta: alguma obra além do 5 Bairros manda dois ofícios? (o cadastro aceita os dois casos)

**T3 FECHADO em 2026-09-17.** Retomada da varredura do SharePoint só para as lacunas ("sem evidência")
do relatório, a pedido do dono; resultado no §10 do relatório. Três refinamentos ao modelo aprovado,
sem mudar a decisão:
1. Fonte normativa achada: OT 028/2015/CGE item 3.2.1 (efeitos no 1º dia do mesmo mês do ano seguinte) e
   IN 001/2024 Cap. V (sem prazo em dias; nova solicitação a cada aniversário; pleito = ofício + planilha
   de cálculo + cronograma). O sistema gera e envia o OFÍCIO; a planilha e o cronograma são anexos que a
   pessoa produz fora (o sistema não calcula reajuste).
2. Registro do apostilamento ganha dois campos opcionais: percentual concedido e data de eficácia (MTPAR só
   publica percentual; SINFRA lista valor por medição).
3. A marcação "sem reajuste" perde urgência: nenhuma obra sem reajuste foi encontrada (Espaço Show,
   Deciolândia e Oriundi têm; Coxipó 3ª e Integra BRT sem evidência). Fica como campo, default falso.
Datas-base corrigidas para o cadastro: Xtreme maio/2024, Orla março/2024, Granito junho/2025, Espaço Show
fevereiro/2024, Deciolândia outubro/2021, Maternidade novembro/2024.

---

## T4. Prazos de vigência e execução (aberto pelo dono em 2026-09-17)

**Ideia do dono.** "Nós também protocolamos cartas solicitando" a prorrogação. Pediu varredura de
como isso é feito (Outlook + SharePoint).

**O que a nova tem.** Vigência e execução separadas no contrato, com fim vigente calculado pelos aditivos
assinados; alerta de 60 dias para cada uma; tela de aditivos (rascunho → assinado, com delta de valor e
novas datas, leitura do termo em PDF só como sugestão). Não gera a carta de pedido nem registra o pleito.

**Varredura CONCLUÍDA em 2026-09-17; relatório em `docs/prazos-vigencia-execucao-2026-09-17.md`.**
Achados que mudam o desenho:
- **Prazo vem por APOSTILAMENTO nos contratos sob a Lei 14.133** (Leblon 012/2024, MT-402 019/2024,
  Chapada 031/2024) e por TERMO ADITIVO nos sob a 8.666 (Atalaia 074/2021, 5 Bairros 161/2022, MT-401
  014/2023, Alta Floresta 102/2022). A tabela de aditivos da nova só conhece "aditivo": precisa aceitar
  "apostilamento de prazo", senão perde todo contrato de 2024 em diante.
- **O relógio que importa é o da EXECUÇÃO**: na SINFRA a vigência se prorroga sozinha por cláusula
  (5.2.2 do 082/2025); a execução só muda por instrumento. Vigência = execução + folga do órgão
  (SINFRA 90 d, SES 99, MTPAR 78 ou 55, PMC prazo único) — folga vira campo do contrato.
- **Antecedência real: mediana de 21 dias; 4 cartas protocoladas DEPOIS de vencer.** O buraco não é
  "esquecer de pedir", é "pedido feito e órgão não responde": 3 de 8 instrumentos foram assinados após o
  prazo vencer (MT-401 77 dias depois). O sistema deve ACEITAR instrumento retroativo, nunca bloquear.
- **A carta é gerável quase inteira**: a seção "DO CONTRATO" é o ledger de aditivos que o sistema já tem.
  Resta digitar justificativa e nº de dias. Não existe modelo .dotx; hoje se copia a carta anterior (e se
  propaga "contatual", "CT/070/LT/2032" e nº divergente do nome do arquivo).
- **Paralisação é entidade própria** (ordem de paralisação → ordem de reinício; cláusula 9.2 devolve o
  período por apostilamento). Sem ela o prazo restante fica errado.
- **Endosso do seguro-garantia em 5 dias** após cada instrumento de prazo: obrigação contratual expressa,
  hoje sem alerta nenhum.
- **Risco achado**: obra 161 (Alta Floresta) e obra 173 (Chapada) estão, pelos documentos arquivados, sem
  cobertura de prazo (último instrumento venceu em 2026-06-26 e 2025-11-19). Conferência humana pendente.
- Pendências da varredura: PDFs digitalizados sem texto (obra 168; cláusula primeira dos apostilamentos
  recentes de Leblon e MT-402) e obras 183/184 (ramo terminou por falta de créditos de uso).

**Informado pelo dono em 2026-09-18.** Chapada (173) FINALIZADA. Alta Floresta (161) "finalizando":
confirmado nos PDFs que a 42ª é a MEDIÇÃO FINAL (NF 2225), protocolada em 17/07/2026 (CT/232 e CT/233),
enviada em 20/07/2026, depois da vigência do 9º TA (26/06/2026). Detalhe no §11 do relatório de prazos.

**O que isso ensina ao desenho (Claude, 2026-09-18):**
- Falta um estado de contrato entre "ativo" e "encerrado": **medição final protocolada / em encerramento**.
  Nele os avisos de prazo param e o único passo restante é o recebimento definitivo (e a baixa do RM).
  Hoje o sistema só tem ativo, suspenso, encerrado e rescindido.
- A medição precisa de uma marcação **"final"**, que dispara esse estado.
- SES é a quarta família de protocolo: carta com lista NUMERADA de anexos (NF discriminada, certidões,
  ARTs, diário de obra, relatório fotográfico, cronograma, boletim, memoriais, ensaios); a do reajuste é
  mais curta; dois CTs consecutivos e dois e-mails. A lista de anexos sai do próprio pacote que o sistema
  monta.
- As quatro falhas de cópia das duas cartas (41ª no lugar de 42ª, ano 2026 no lugar de 2025, coluna
  "reajuste 039", corpo dizendo "medição" no reajuste) são exatamente o que a geração pelo sistema elimina.
- IBS/CBS já sai destacado na NF real (com redução de 60% no caso da SES): o espelho em Python precisa disso.

**O dono, 2026-09-18:** "não houve finalização do contrato, mas creio que a obra está finalizada."
Verificado: nenhuma comunicação de conclusão, pedido de vistoria ou recebimento provisório de Alta Floresta
no Outlook (desde 05/2026) nem no SharePoint. Estado real: obra física concluída (medição final 42ª,
período até 26/12/2025), contrato aberto, vigência do 9º TA vencida em 26/06/2026. Custo ainda correndo:
boletos de locação de cilindros da Norte Floresta Gases (Alta Floresta) em 30/07 e 02/09/2026.
Precedente interno da carta que falta: CT/245/LT/2026 (Orla, MTPAR, 31/07/2026) "Comunicação de Conclusão
da Obra, Solicitação de Vistoria e Reiteração de Pedido de Apostilamento". Contrato sob a Lei 8.666
(9º TA cita o art. 57): art. 73, I prevê recebimento provisório pelo fiscal em até 15 dias da comunicação
escrita da contratada e definitivo por comissão após observação ou vistoria (§3º: até 90 dias).

**O dono, 2026-09-18:** Alta Floresta fica para depois.

**MODELO DE PRAZOS APROVADO pelo dono em 2026-09-18 (versão resumida que ele aprovou):**
- Por contrato: fim da execução e fim da vigência (recalculados por instrumento assinado) + folga do órgão
  (SINFRA 90 d, SES 99, MTPAR a do contrato, PMC prazo único); aviso se um instrumento quebrar a folga.
- O relógio principal é a EXECUÇÃO; aviso de vigência só onde ela não se prorroga sozinha (fora da SINFRA).
- Ciclo: aviso aos 60 dias do fim da execução, vermelho aos 30 → carta enviada pelo sistema (histórico de
  aditivos automático; justificativa, nº de dias e CT digitados) → "pedido enviado, aditivo pendente há N
  dias" → instrumento registrado (nº, data, datas novas, PDF) → aviso some e nasce "endosso do
  seguro-garantia em 5 dias" → execução vencida sem assinatura mantém aviso vermelho com dias e data do pedido.
- Aceita: prazo por apostilamento; instrumento retroativo (registra e sinaliza, nunca bloqueia);
  paralisação (ordem de paralisação e de reinício, período devolvido ao prazo).
- Medição marcada como final → contrato "em encerramento": avisos de prazo param; quatro marcos (conclusão
  comunicada por carta do sistema, recebimento provisório, recebimento definitivo, baixa da garantia).
- A carta não sugere "chuva" sozinha; só ligada a ordem de paralisação do órgão.

**T4 FECHADO em 2026-09-18.**

---

## T5. Cadastro da obra (aberto em 2026-09-18)

**Proposta do Claude.** Os quatro modelos aprovados exigem ~20 campos por contrato que hoje não existem.
Para não virar formulário gigante, três níveis:
1. **Órgão/superintendência** (herdado por todos os contratos dele, sobrescrevível): família de protocolo,
   endereço de protocolo, cópias padrão, texto do e-mail, medição e reajuste juntos ou separados, exige
   planilha editável, limite de 25 MB e ordem do check-list, folga vigência − execução, vigência se prorroga
   sozinha.
2. **Entidade** (Lotufo, consórcios): sigla do ofício (LT, CCL, CO), além do que já existe (CNPJ, coligada RM).
3. **Contrato**: o que já existe + nome curto, lei do contrato (8.666 / 14.133 / 13.303), fiscal nominal
   com histórico, destinatários extras (supervisora), modelo da carta de protocolo, certidões exigidas,
   datas-base (uma ou duas, com rótulo do índice), marcação sem reajuste, consorciadas com cota.
- **Regra do espelho** (saídas, rateio, retenções, arredondamento, modelos .docx): NÃO é digitada; entra ao
  portar o motor obra a obra e é conferida contra os gabaritos.
- **Sai do cadastro** (só servia à detecção cortada): apelidos de contrato, canais de detecção,
  configuração de planilha por contrato. Pasta do SharePoint fica como link opcional.
- Carga inicial pré-preenchida com o que os levantamentos já acharam; a equipe confirma, não digita.

**Decisões do dono (2026-09-21).**
1. **Não haverá tela de cadastro de obras na dashboard.** As informações da obra entram SEMPRE pelo Claude
   (o dono + Claude). Consequência: o cadastro vira arquivo versionado no repositório, carregado no banco
   por comando; a tela de criar/editar contrato (Contratos.tsx) e os formulários de entidade e tipo de
   certidão na Administração saem ou ficam só leitura.
2. **Só o dono edita, e pelo Claude; nada no sistema.**
3. Carga inicial pré-preenchida: autorizada.
4. Lista das obras para ele marcar quais NÃO entram: apresentada em 2026-09-21 (22 contratos da produção
   + 4 "fora de escopo" do cadastro antigo).

**Decisão 4 (2026-09-21): entram as obras do QDOP com os status dele.** Fonte: `GL.SGI.FRP.DE.250 - QDOP -
QUADRO DEMONSTRATIVO DE OBRAS E PROJETOS.xlsx`, versão 03, atualizado em 27/08/2026, 22 obras — as mesmas 22
da produção da nova (casamento 1 a 1). Saem: Chapada e os 4 "fora de escopo" do cadastro antigo (pastas 154,
163, 169, Sucuri). Status do QDOP: 19 EM ANDAMENTO, 2 CONCLUÍDA (Alta Floresta, Orla), 1 PARALISADA (Coxipó 2ª).
Mapeamento para o sistema: EM ANDAMENTO → ativo; PARALISADA → suspenso; CONCLUÍDA → "em encerramento"
(obra concluída não é contrato encerrado; ver Alta Floresta).
Divergências com a produção a corrigir na carga: MT-402 e Coxipó 3ª constam suspensos, QDOP diz em
andamento; Alta Floresta e Orla constam ativos, QDOP diz concluída.
Inconsistências do próprio QDOP para o dono conferir: Estações BRT e Terminais BRT com vigência ANTES do
término da execução (14/12/2026 × 14/03/2027; 16/02/2027 × 26/02/2027), o que o contrato SINFRA não permite
(5.2.3: vigência inclui a execução); Maternidade com execução e vigência no mesmo dia (18/12/2027); término
de execução já passado em obras "em andamento" (Deciolândia 30/01/2026, Xtreme 01/08/2026, Atalaia
27/08/2026, MT-402 28/08, Leblon 31/08, MT-401 01/09) — Leblon e MT-402 já têm apostilamento de 24 e
26/08 que o QDOP de 27/08 não reflete.

**Decisão 5 (2026-09-21): registrar instrumento assinado (aditivo, apostilamento de prazo ou de reajuste) e
trocar o fiscal também são SÓ PELO CLAUDE.** Ajuste aos modelos de T3 e T4: o passo "registrar o
instrumento" é feito pelo dono com o Claude no cadastro versionado; na dashboard fica só o ato de
operação (enviar o pleito, a carta de prorrogação, a comunicação de conclusão) e o aviso "pendente há N
dias", que some quando o instrumento é carregado. A tela de aditivos (rascunho, assinar, cancelar) vira
leitura.

**Divisão resultante:**
- **Cadastro (só o dono, via Claude, arquivo versionado no repositório):** obras, órgãos, entidades,
  datas, valores, datas-base, lei do contrato, fiscal, destinatários, certidões exigidas, instrumentos
  assinados (aditivos, apostilamentos, paralisações), regra do espelho.
- **Operação (as operadoras, na dashboard):** gerar e enviar espelho, protocolar, enviar pleito de
  reajuste, carta de prorrogação e comunicação de conclusão, marcar medição final, anexar evidência do órgão.
- **Automático (RM):** nota emitida e recebimento.

**T5 FECHADO em 2026-09-21.**

---

## T6. Certidões (aberto em 2026-09-21)

**Estado real verificado (2026-09-21):**
- **Na nova: ZERO certidões cadastradas** na produção. 6 entidades (Lotufo + 5 consórcios), 3 tipos
  (CND federal, CRF/FGTS, CNDT). O checklist de protocolo, que trava por padrão, travaria todo protocolo.
- **A antiga está em uso ativo para certidões**: os anexos dos protocolos de setembro/2026 têm exatamente o
  padrão de nome do ZIP da antiga (`Certidoes - Lotufo - 2026-09-14.zip`, `Certidoes - Lotufo -
  2026-09-11.zip`) e das certidões avulsas (`Lotufo - FGTS - 2026-09-02.pdf`, `Lotufo - ESTADUAL -
  2026-09-24.pdf`, formato `Empresa - TIPO - validade.pdf`). É a única função da antiga em uso diário
  comprovado; desligar a antiga sem substituto quebra o protocolo.
- Antiga: 8 entidades × 6 tipos (federal, FGTS, CNDT, estadual SEFAZ-MT, municipal Cuiabá, falência TJMT),
  leitura de PDF dos 6 (validade da falência calculada em 30 dias úteis), OCR, ZIP por entidade, link
  "emitir", alerta diário por Power Automate às 08:00, lista no SharePoint (63 em 04/08/2026).
- O que vai no protocolo (evidência): SES 42ª Alta Floresta levou 5 certidões dentro do PDF (estadual
  CPEND, federal, FGTS, municipal de CUIABÁ mesmo sendo obra em Alta Floresta, CNDT); SINFRA manda ZIP
  "Certidoes - Lotufo - data" + "Documentos de Regularidade"; consórcios mandam as do consórcio
  ("Certidões Oriundi.zip", "CERTIDÕES DE REGULARIDADE - COMP. LEBLON.pdf"). IN 001/2024 SINFRA art. 12 §3º:
  no reajuste só se exige regularidade fiscal com o Estado e a NF.
- Correção a um achado anterior: a certidão municipal "fixa em Cuiabá" da antiga está CERTA para protocolo
  de medição (é a do domicílio da empresa), não errada.

**Reanálise (Claude, 2026-09-21), com verificação do pacote real de 16/09/2026 (NF 33ª 5 Bairros → SINFRA):**
anexos = 2 NFS-e + `Certidoes - Lotufo - 2026-09-14.zip` (437 KB) + `Documentos de Regularidade - Lotufo
Engenharia..pdf` (3,7 MB). O "Documentos de Regularidade" NÃO é certidão: é o pacote trabalhista e
previdenciário do mês, vindo do DP — comprovante de inscrição no CNO DA OBRA (5 Bairros: CNO
90.014.43907/74, com ART), folha de pagamento do RM Labore (competência 07/2026), SEFIP/eSocial e
INSS/GPS. Ou seja, o protocolo leva DUAS classes de documento de habilitação:
  (a) com VALIDADE, por empresa, reaproveitável enquanto vigente (certidões);
  (b) por COMPETÊNCIA, por empresa/obra, reaproveitável em todos os protocolos do mês (regularidade do DP).

**Proposta do Claude: módulo "Documentos de protocolo", não "Certidões".**
1. Duas gavetas: certidões (validade) e regularidade mensal (competência). O CNO da obra entra no cadastro
   do contrato (já era pendência para o espelho).
2. Subir documento é OPERAÇÃO (operadoras): ~10–15 por mês (FGTS e municipal vencem a cada 30 dias);
   via Claude viraria gargalo. Via Claude fica só O QUE É EXIGIDO (tipos por órgão/contrato, entidades).
3. Arrastar PDF → sistema lê tipo, empresa (pelo CNPJ) e validade → pessoa confere → grava. Porta dos 6
   leitores da antiga para Python, provados contra as 9 certidões reais dos testes dela. Sem OCR: PDF sem
   texto → pessoa digita 3 campos. Leitor registra a natureza (negativa / positiva com efeito de negativa);
   "positiva" pura é recusada.
4. O ponto de passagem obrigatório é o PROTOCOLO: a prévia do pacote mostra o que o órgão exige, o que
   está vigente HOJE e o que falta, com o link "emitir" ao lado. Falta → avisa e deixa seguir com
   justificativa (mesma regra da nota).
5. Formato do anexo por família de órgão (cadastro): dentro do PDF único (MTPAR, SES), ZIP separado +
   PDF de regularidade (SINFRA), certidões do consórcio nas obras de consórcio. No reajuste SINFRA só a
   estadual (IN 001/2024 art. 12 §3º).
6. Aviso na home: UMA linha por empresa com contrato ativo ("Lotufo: FGTS vence em 4 dias; municipal
   vencida"), só tipos exigidos por algum contrato ativo; limiar 7 dias para as de 30 dias de validade e
   15 para as demais. E aviso de "regularidade do mês ainda não anexada" a partir do dia 10.
7. ZIP por empresa com data de referência ("vigentes em DD/MM") continua, para licitação.
**Verificado nos e-mails em 2026-09-21 (pergunta do dono: consórcio pede certidão das consorciadas?):**
- SIM. O alerta diário de certidões (fluxo do Power Automate, sai às 08:00 da conta do próprio dono,
  só para ele) lista certidões de 7 empresas com envio recente: Lotufo, Guaxe, Encomind, Rivoli, Consórcio
  Integra BRT, Consórcio Complexo Leblon, Consórcio Oriundi. As consorciadas têm FGTS renovado todo mês
  (Guaxe e Encomind até 28/09, Rivoli até 24/09). Não aparecem: Montante, Via Parecis, BR-163.
- O pacote do Oriundi (03/08/2026) leva `Certidões Oriundi.zip` de 1,48 MB, mais de 3× o ZIP só da Lotufo
  (437 KB), coerente com consórcio + consorciadas; e a regularidade mensal só da Lotufo
  (`052026 - LOTUFO ENGENHARIA.pdf`).
- O ALERTA ATUAL ESTÁ QUEBRADO: 43 linhas por dia, incluindo certidões de junho e julho já substituídas
  (Lotufo FGTS 13/07, 09/08, 02/09 e 28/09 aparecem todas como "sem substituta válida"). Sinal real hoje:
  ~12 itens (Lotufo municipal vencida em 20/09, estadual vence 24/09, Guaxe municipal 22/09...). E vai só
  para o dono, não para quem renova. Confirma o desenho: última por (empresa, tipo), uma linha por
  empresa, na tela de quem opera.
- Cadência medida: FGTS da Lotufo renovado a cada ~25 dias; 7 empresas → 15 a 20 documentos por mês.
- Quem monta o PDF de regularidade (DP pronto ou operadora junta): NÃO muda o desenho. Para o sistema é um
  arquivo por empresa e por mês, anexado uma vez; o comprovante do CNO é da obra e entra no cadastro, e o
  sistema junta os dois.

**Fluxo completo da pessoa para protocolar uma medição (proposta Claude, 2026-09-21):**
0. Fora da medição, quando a home avisar: arrastar certidão renovada; anexar a regularidade do mês.
1. Obra → "Gerar espelho": digita nº, competência, valor da medição, valor do reajuste; arrasta (opcional)
   o que o órgão mandou.
2. Confere uma linha por nota → "Enviar ao faturamento" (e-mail sai da conta dela). Medição nasce.
3. RM detecta a nota → medição "nota emitida". Ela arrasta os PDFs das notas que o faturamento devolveu
   (o RM dá os dados, não o PDF); em consórcio, também as notas das consorciadas e a FRC.
4. "Protocolar": digita o(s) CT(s); arrasta as peças técnicas feitas fora (caderno/boletim assinado,
   planilha editável, fotos, diário, ensaios, conforme o órgão). O sistema gera a carta e junta notas,
   certidões vigentes, regularidade do mês + CNO, na ordem do órgão.
5. Assinatura (DocuSign, fora do sistema): baixa a carta, assina, arrasta a assinada de volta.
6. Prévia (destinatários, assunto, anexos, o que falta) → "Enviar". Medição = protocolada.
7. Depois: RM marca recebida; opcional, digitar o nº de protocolo do órgão e arrastar o comprovante.
Digitação total: 4 campos + CT. Pendente: assinar só a carta ou o pacote inteiro (hoje o pacote inteiro
passa pelo DocuSign: todas as 114 páginas da 42ª de Alta Floresta têm o ID do envelope).

**Objeções do dono ao fluxo (2026-09-21) e verificação:**

*(a) "A nota é emitida no RM ou fora e lançada depois? O faturamento pode devolver a nota por e-mail antes de
ela estar no RM."* CONFIRMADO pelo banco de produção (notas_fiscais.primeiro_visto_em × hora do e-mail de
protocolo, horário de Cuiabá):
| Nota | Protocolada ao órgão | RM enxergou | Diferença |
|---|---|---|---|
| 2307/2308 (5 Bairros 33ª) | 16/09 13:40 | 16/09 15:17 | RM 1h37 DEPOIS do protocolo |
| 2298/2299/2304 (MT-388 13ª) | 16/09 08:32 | 17/09 10:19 | RM 1 dia depois |
| 2288 (MT-402 27ª) | 14/09 15:42 | 15/09 11:43 | RM 20 h depois |
| 2289/2290 (Leblon 28ª) | emitidas 14/09 | 16/09 10:16 | 2 dias |
A NFS-e nasce fora (portal da prefeitura / emissor nacional; o PDF é "Prefeitura Municipal de Cuiabá –
NFS-e" até 08/2026 e "DANFSe v2.0" em 09/2026) e é lançada no RM depois, do mesmo dia até 2 dias. Esperar
o RM atrasaria o protocolo. O número da nota no RM é o da prefeitura (chave de conferência existe).
**Redesenho do passo 3:** quem chegar primeiro avança a medição; o segundo confirma.
- Arrastar o PDF da nota = "nota emitida" na hora (origem: PDF). Leitor determinístico de NFS-e (a antiga
  já lê ISSNet/Cuiabá e Tangará para a FRC; falta o leiaute nacional DANFSe).
- O sistema CONFERE a nota contra o espelho (valor, ISS, INSS, IRRF, tomador) antes do protocolo: inverte o
  "favor conferir os impostos" de hoje.
- O RM confirma depois em silêncio (mesmo número e valor). Divergência de valor → aviso. Nota protocolada e
  ausente do RM após 5 dias → aviso (controle útil para a controladoria).
- Recebimento continua só pelo RM.

*(b) "Dá para mandar ao DocuSign por API, MCP ou conector?"* Verificado em 2026-09-21:
- Existe conector MCP oficial do DocuSign (https://mcp.docusign.com/mcp, beta aberto, no diretório do
  Claude; não conectado nesta conta). Serve a uma sessão do CLAUDE agindo pelo usuário, NÃO ao backend da
  dashboard; não resolve o passo da operadora.
- Para a dashboard o caminho é a API REST de eSignature: cria o envelope com o pacote, signatário (o diretor), consulta o status por polling (rede interna não recebe webhook) e baixa o PDF assinado.
  Produção exige plano com API (plano de desenvolvedor a partir de ~US$ 50/mês, ou Business Pro em diante,
  segundo fontes de terceiros; confirmar no site/conta). Se o plano atual da Lotufo não incluir API, é custo
  novo e esbarra na regra "sem custo de API" → decisão do dono.
- Desenho proposto: o passo "assinar" tem duas implementações atrás da mesma tela: manual (baixar pacote →
  DocuSign → arrastar assinado; custo zero, funciona no dia 1) e por API (botão "enviar para assinatura",
  status "aguardando o diretor", PDF assinado volta sozinho). Começa manual; liga a API se o plano permitir.
- **Decisão do dono: o PACOTE INTEIRO é assinado** (não só a carta).

**APROVADO pelo dono em 2026-09-21:** o modelo de certidões ("documentos de protocolo", duas gavetas)
e o fluxo completo da pessoa, com o passo 3 refeito (PDF da nota avança, RM confirma).
**DocuSign: MANUAL.** O sistema monta o pacote inteiro; a pessoa baixa, assina por fora e arrasta o
assinado de volta; só então envia o e-mail. Sem API, sem conector. (A porta para a API fica fechada; reabrir
só por decisão dele.)
Conferência do PDF assinado (corrigida em 2026-09-21 após aviso do dono de que o DocuSign às vezes
anexa páginas de autenticação no fim, em número variável): NÃO comparar contagem de páginas. Regra:
(1) as N primeiras páginas do assinado devem bater, por texto normalizado e ignorando o carimbo do
envelope, com as N páginas do pacote montado (aponta página trocada, faltando ou fora de ordem; página sem
texto compara só posição); (2) páginas extras no fim são aceitas quando reconhecidas como certificado de
conclusão do DocuSign, qualquer outra sobra avisa; (3) todas as páginas do pacote devem ter o carimbo
"Docusign Envelope ID" e o MESMO identificador (verificado nos PDFs reais da 42ª de Alta Floresta: 114/114
e 12/12 páginas carimbadas, sem certificado anexo) — pega o erro mais provável, arrastar o PDF ainda não
assinado. Aviso com opção de seguir, nunca bloqueio.

**T6 FECHADO em 2026-09-21.**

---

## T7. O que a diretoria vê (aberto em 2026-09-21)

**O que existe.** QDOP (formulário oficial do SGI, GL.SGI.FRP.DE.250 versão 03, assinado por Gerente de
Engenharia e Diretor, atualizado à mão; última em 27/08/2026): uma linha por obra com contratante, tipo,
início, término, vigência, empreita, % de direito, contrato (PI), aditivo (VA), contratual (PI+VA),
reajuste recebido, faturado (PI+VA), saldo a faturar, % recebido, % a receber, status, localidade,
descrição; totalizadores própria / consórcio / total; valores NA COTA da Lotufo. Na nova: Painel geral
com 4 números de caixa, gráfico previsto × medido, tabela de carteira no valor CHEIO e CSV. Na antiga:
visão executiva com 6 indicadores, gráficos, mapa e tabela (parte desligada).

**Proposta do Claude.** A tela da diretoria É o QDOP, vivo: mesma tabela, mesmas colunas, na cota, com os
totalizadores, calculada do que o sistema já registra (cadastro + instrumentos + medições + notas), e
um botão que exporta no leiaute oficial do formulário. Acima dela, os mesmos avisos da operação (só
leitura) e os três números do mês. Um gráfico só: faturamento mensal. Sai: quatro números de caixa como
estão, carteira no cheio, mapa, carteira por contratante, top 10. Custo e margem seguem fora.

**Respostas do dono (2026-09-21).** A diretoria ABRE a dashboard e deve ver o que é realmente
importante para uma diretoria; o QDOP foi só referência, não limitar a ele. operadora atualiza o QDOP
(frequência desconhecida). No QDOP, "valores faturados" = RECEBIDOS. Quer exatamente o item 4: quanto
entrou no mês, quanto está a receber, previsão dos próximos meses.

**Medição no banco de produção (2026-09-21, notas de obra do RM, todas as coligadas, sem regra de cota):**
prazo da emissão da nota ao pagamento, notas desde 09/2025: SINFRA mediana 5 dias (243 notas), MTPAR 10
dias (126), Prefeitura de Cuiabá 57 dias (23, 3º quartil 71). Recebido por mês em 2026: entre R$ 12,7 mi
(maio) e R$ 39,3 mi (junho). "Em aberto" bruto de R$ 92,7 mi, com R$ 44,7 mi da SINFRA há mais de 60 dias:
NÃO CONFIÁVEL como está (inclui consórcios no valor cheio e notas cuja baixa não casou); exige
conciliação com a controladoria e regra de cota antes de ir para a tela.

**Proposta revista (Claude): uma tela, cinco blocos, por ordem de importância.**
1. ONDE ESTÁ O DINHEIRO (na cota): medido aguardando nota → nota emitida aguardando protocolo →
   protocolado aguardando pagamento (até 30 / 31–60 / 60+ dias, por órgão) → recebido no mês. Caixa à parte:
   reajustes travados esperando apostilamento.
2. O MÊS E O ANO: medido no mês × previsto no cronograma × mesmo mês do ano anterior; acumulado do ano;
   um gráfico de 12 meses (medido × previsto, linha de recebido).
3. OS PRÓXIMOS MESES: faturamento previsto (cronogramas) para 6 meses; recebimento previsto = protocolado
   + prazo de pagamento medido de cada órgão.
4. A CARTEIRA: saldo a executar na cota; quantos meses de produção no ritmo atual; concentração por
   órgão; contratos que acabam em 6 meses (queda de carteira = alerta comercial).
5. AS OBRAS: tabela tipo QDOP com farol e o MOTIVO (prazo, pagamento atrasado, paralisada, pleito parado);
   clique abre a obra. Exporta o QDOP no leiaute oficial.
Avisos da diretoria (só os que pedem decisão dela): execução vencida sem instrumento, pagamento atrasado
além do prazo normal DAQUELE órgão, obra paralisada, reajuste pendente há mais de 90 dias. Certidão não.
Vocabulário fixo na tela: medido, faturado (nota emitida), protocolado, recebido (o QDOP chama recebido de
"faturado").
LACUNA DECLARADA: margem por obra (o indicador nº 1 de diretoria) fica fora enquanto o custo não vier do
RM. O RM já entrega nota com centro de custo por obra (16 centros mapeados); custo exigiria mais uma
Consulta SQL cadastrada no RM. Decisão do dono: reabrir ou manter fora.

8. Migração: no corte, reler pelo leitor os PDFs vigentes da biblioteca /Certidoes do SharePoint (não
   confiar na lista), carregar, conferir, e só então desligar os 3 fluxos de certidão do Power Automate
   (gravar, arquivo, alerta das 08:00). Entidades que entram = as que tiverem certidão vigente na migração.

**Proposta de desenho (Claude):** estado de contrato "em encerramento", disparado pela marcação de medição
final. Nele os avisos de prazo param e entra um aviso próprio com quatro marcos: conclusão comunicada
(carta gerada pelo sistema, quinto tipo de carta) → recebimento provisório → recebimento definitivo →
baixa da garantia; do definitivo em diante o contrato vai a "encerrado". O aviso conta dias desde a medição
final sem conclusão comunicada.

**Análise do Claude.** CT manual é a escolha segura: o contador é da empresa inteira (CT-200 a CT-303
atravessam todas as obras) e vive fora do sistema; gerar automático colidiria com quem numera hoje. Custo:
o campo pode ser digitado errado ou repetido — o sistema deve avisar se o número já foi usado, sem travar.
Montar o PDF exige: gerador da carta por obra (modelo Word), anexar o PDF da(s) NF(s) e as certidões
vigentes do checklist, e juntar tudo em um PDF na ordem do check-list (SINFRA recusa fora de ordem) com
teto de 25 MB por documento — quando estourar, o sistema divide em medição e reajuste, como o órgão instrui.

**T7 APROVADO e FECHADO pelo dono em 2026-09-21:** os cinco blocos da tela da diretoria. **Custo e
margem CONTINUAM FORA** (decisão reafirmada).

---

## SÍNTESE: a objeção do dono à dashboard nova (Claude, 2026-09-21, a confirmar por ele)

**Em uma frase.** A nova foi feita para OBSERVAR o trabalho e pedir confirmação; o dono quer um
sistema ONDE O TRABALHO É FEITO, e que por isso já nasce com o registro certo, simples para quem executa
e com o controle das regras nas mãos dele.

**As sete decisões que mostram isso, e o que cada uma rejeita:**
1. *Cortou todo motor que adivinha* (leitura de planilha, leitura de e-mail, fila de sugestões). Rejeita o
   princípio nº 1 da spec antiga, "observar antes de perguntar". Ficou só o RM, que é fato, e mesmo nele o
   ato humano (arrastar a nota) passou a liderar e o RM a confirmar.
2. *Pôs o sistema nos pontos de passagem obrigatória*: espelho, e-mail ao faturamento, pacote e e-mail de
   protocolo, pleito de reajuste, carta de prorrogação, comunicação de conclusão. O registro vira
   subproduto de fazer o trabalho, não uma tarefa a mais. É o que ele chamou de "ser essencial e entrar na
   rotina".
3. *Corrigiu o processo pelo que acontece de verdade.* A nova modelou protocolo antes da nota e "atestado"
   como glosa; o real é órgão informa → espelho → nota → pacote → protocolo → recebimento. Em todos os
   tópicos a regra certa saiu de e-mail, contrato e apostilamento reais, e várias vezes contrariou o que a
   spec antiga, a dashboard antiga e até a lembrança dele diziam (60 dias do reajuste, ofício "antes",
   dois ofícios por índice, nota "no RM").
4. *Separou quem executa de quem decide.* Operação (operadoras): quatro campos, arrastar, conferir,
   clicar. Regras, cadastro e instrumentos: só ele, pelo Claude, em arquivo versionado, sem tela. Rejeita
   a ideia de que todo dado precisa de um formulário e de que o operador deve julgar ("aceitar, corrigir,
   descartar" com sete tipos e jargão interno).
5. *Exigiu aviso que mereça confiança.* Os alertas de hoje ensinam a ignorar: 84 de 102 "reajuste sem par"
   falsos, e-mail diário de certidões com 43 linhas para 12 reais, "vencido há 700 dias". O padrão aprovado
   é o mesmo em reajuste, prazos e certidões: poucos avisos, com obra, dias e valor, que somem por um ato
   real e continuam enquanto o órgão não responde.
6. *Preferiu o simples que funciona ao automático que depende.* CT digitado, DocuSign por fora, sem API
   paga, sem cálculo de índice, custo fora. E "avisa e deixa seguir" no lugar de bloquear, porque bloqueio
   empurra o trabalho para fora do sistema, que é exatamente a falha a evitar.
7. *Quis uma diretoria olhando dinheiro, não painel genérico*: onde está, o que entra, o que está travado,
   quanto de carteira resta.

**O que NÃO é objeção (fica da nova):** servidor na rede interna, banco, auditoria encadeada, histórico
que não sobrescreve, dinheiro em centavos, cota de consórcio, perfis, integração com o RM, watchdog e
deploy pinado. A objeção é ao papel do sistema, não à engenharia dele.

**Consequência para a spec:** a autoridade de produto atual (spec de 2026-08-28, "sistema que observa, não
sistema onde se registra") é substituída. O novo princípio nº 1: *o sistema é onde o trabalho é feito; o
registro é consequência.*

---

## Spec e plano (2026-09-21)

- Síntese da objeção CONFIRMADA pelo dono.
- Spec `docs/superpowers/specs/2026-09-21-reestruturacao-design.md` APROVADA; substitui a de 2026-08-28.
- Plano do bloco 1 `docs/superpowers/plans/2026-09-21-bloco-1-fundacao.md` APROVADO, com as três decisões
  que fogem da spec: máquina de estados da medição vai para o bloco 2 e o remapeamento do legado para o
  bloco 3; "em encerramento" é a coluna `encerramento_iniciado_em`; aditivos de valor e prazo seguem em
  `aditivos`, o resto em `instrumentos`.
- Execução escolhida: NESTA SESSÃO (inline), após um /clear. Nada implementado ainda.
- Pendências do dono para o bloco rodar até o fim: `Mail.Send` e `Mail.ReadWrite` no aplicativo do
  Entra; usuários das operadoras na dashboard.
