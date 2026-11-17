# Mapeamento dos e-mails do ciclo de medição (caixa do dono, 2026-09-16)

Fonte: caixa do dono via conector Microsoft 365, só leitura. Objetivo: o sistema
gerar automaticamente o e-mail do espelho ao faturamento e o e-mail de protocolo ao órgão.

## 0. Escopo real

- A caixa só tem mensagens desde **2026-05-13** (~4 meses mapeáveis, 837 mensagens na entrada).
- O dono quase nunca é o remetente: 12 itens enviados no período. Quem opera o ciclo é
  a operadora, com a segunda operadora como suplente; o dono entra em cópia. Consequência: a conta que
  protocola é a da operadora; ela precisa de usuário na dashboard e de login Microsoft próprio.

## 1. Protocolo ao órgão: três famílias

### 1.A MTPAR (Complexo Cultural, Orla, Xtreme, Espaço Show, Granito)
- TO: o e-mail de protocolo da MTPAR + 1 fiscal nominal por obra (muda com o tempo: o Cultural trocou de
  fiscal entre 21/08 e 16/09). Orla apareceu só com o e-mail de protocolo.
- CC fixo: a equipe interna (cinco endereços, incluindo o do dono).
- Assunto: `CT-{nnn}-LT-2026 - {n}ª Medição - {Obra}` e `CT-{nnn}-LT-2026 - Reajuste {n}ª Medição - {Obra}`
  (variantes com barras e com "Medição Contratual (MM/AAAA) ... IC nnn/ano").
- Corpo literal: "Bom dia." (ou "Boa tarde.") / "Encaminho arquivo para protocolo." / "Solicito, por favor,
  devolutiva com os dados (nº de protocolo) sob os quais o arquivo seja protocolado." / "Atenciosamente,".
- Anexo: 1 PDF único, nome = assunto + .pdf (carta + medição + certidões consolidados, ~800 KB).
- Regra forte: medição e reajuste SEMPRE em e-mails separados, cada um com seu CT (dois números consecutivos).
- MTPAR nunca respondeu com o nº de protocolo no período, apesar do pedido no corpo.

### 1.B SINFRA (endereço por superintendência, não por obra)
| Superintendência | Obras | TO | CC extra |
|---|---|---|---|
| SAGPM / SUOESP | Integra BRT (IC 041/2025), Estações (IC 176/2025), Terminais (IC 044/2026) | os dois gabinetes + os fiscais nominais da obra | três pessoas da cópia interna |
| SUEF II | MT-388 (IC 082/2025) | o e-mail da superintendência | dois servidores da SUEF II, a supervisora Tokio Marine (duas pessoas), um engenheiro da supervisão e uma pessoa da cópia interna |
| SUEF I | MT-402 (IC 019/2024), Oriundi (IC 074/2021) | três e-mails da superintendência e o fiscal; assinados vão a um quarto e-mail da SUEF I | supervisora Ecoplan (duas pessoas) e um engenheiro da supervisão |
| SUPU | 5 Bairros (IC 161/2022) | o e-mail da superintendência | — |
| Protocolo geral | ofícios, aditivos, cronogramas | o e-mail do protocolo geral | — |

- CC interno fixo: a equipe interna (três endereços).
- Assunto: `CT-{nnn}-LT-2026_-_{n}ª_Medição_({MM_AAAA})_-_IC_{nnn}_{ano}_-_{Obra}` (underscores, vem do
  DocuSign) ou `{n}ª Medição e Reajuste ({MM/AAAA}) - {Obra} - IC {nnn}/{ano}`.
- Corpo literal: "Bom dia." / "Encaminho arquivo para protocolo." / "Encaminho ainda, arquivos editáveis
  para envio a supervisora e fiscalização." / "Atenciosamente,". Não pede devolutiva. Variante: "Encaminho
  arquivos assinados para protocolo."
- Anexos: PDF assinado do DocuSign (3–15 MB) + XLSX editável (até 16 MB, com sufixo Rev0x); às vezes zip.
  Medição e reajuste podem ir JUNTOS no mesmo e-mail com dois CTs (oposto do MTPAR).
- Regras operacionais (SUEF I, 11/09): SIGADOC aceita no máximo 25 MB por documento; enviar 2 arquivos
  (medição e reajuste) ou partes; tudo num único e-mail, na ordem do check-list ("não serão aceitas
  medições fora da ordem do check-list"). A fiscalização devolve "valor aprovado" com extratos do SINFRALOG.

### 1.C Prefeitura de Cuiabá e supervisoras privadas
- Região Oeste Lote 03 (CT 128/2022): a CAF da Prefeitura em thread reativo ("RE: SOLICITAÇÃO DE NF E
  CERTIDÕES"); a 52ª foi à supervisora por LINK do SharePoint, sem anexo.
- Maternidade/UTI Neonatal VG (CT 118/2025): só os espelhos apareceram; protocolo não encontrado.

## 2. Espelho ao faturamento
- TO: os dois endereços do faturamento (sempre os dois).
  Consórcio acrescenta a consorciada (Leblon: os dois contatos da Rivoli; Integra BRT: o contato da Guaxe).
- CC fixo: a equipe interna e a controladoria.
- Assunto: `Emissão NF - {n}ª Medição [e Reajuste] ({MM/AAAA}) - {Obra} - IC nº {nnn}/{ano}`.
- Corpo literal: "Bom dia." / "Seguem espelhos para emissão de Notas Fiscais." / **"Favor conferir se os
  impostos, base de cálculo e deduções discriminadas no espelho estão corretos."** / "Atenciosamente,".
- Anexos: `ESPELHO - NF - Lotufo {Obra} - {n}ª Medição.docx` e `... - Reaj. {n}ª Medição.docx`; um .docx por NF.
- Retorno do faturamento no mesmo thread ("RE: Emissão NF - ..."), corpo "Segue NFS-e conforme solicitação.",
  anexos `DD-MM-AA NFS {nº} {n}° MED {OBRA}.pdf` (e `... REAJ ...`).
- NFs por medição: medição + reajuste = 2; consórcio = 1 por consorciada (Leblon 28ª: 4 NFs); obra em 2
  municípios = 1 espelho por município (BRT CBA e VG); reajustes acumulados = 1 por competência (Orla 21ª–25ª).

## 3. Retorno do órgão
| Órgão | Remetente | Conteúdo |
|---|---|---|
| SINFRA protocolo geral | o e-mail do protocolo geral (dois servidores) | "documento protocolizado ... Número do Documento" + PDF "SIGA - Gerar Protocolo" |
| SINFRA SUEF I | os e-mails da SUEF I | "Segue anexo o protocolo" + PDF `{n}º Protocolo {IC} PI.pdf`; avisos operacionais |
| SINFRA SUEF II | o e-mail da SUEF II | "medição e reajuste propícios a serem digitalizados"; depois "seguem protocolos ... entra para análise na supervisora" |
| SINFRA SAGPM | o gabinete da SAGPM | ofício com manifestação técnica; "juntado ao expediente SINFRA-TER-2026/..." |
| MTPAR | não encontrado | nenhuma devolutiva de nº de protocolo no período |

## 4. Glosa / reapresentação
Nenhum caso de glosa após protocolo, nenhuma NF cancelada, carta de correção ou NF substituta no período.
O que existe é adequação ANTES do protocolo e antes da NF: Estações BRT 6ª (SINFRA alterou itens; Lotufo
pediu exclusão dos itens; nova planilha REVFinal; espelho só depois), Estações 3ª (arquivo corrigido,
"desconsiderar e-mail anterior"), MT-388 13ª (Rev01 da supervisora), MT-402 27ª (SUEF I devolveu corrigido),
MT-388 12ª (justificativa de atraso exigida), Integra BRT 13ª (FRC substituta pela controladoria). Padrão: correção
é sempre no arquivo, antes da NF; nunca ajuste na medição seguinte.

## 5. FRC de consórcio
- Quem manda: a controladoria, respondendo ao thread do espelho depois que as consorciadas emitem as NFs.
  Para a operadora, o faturamento e as consorciadas; CC a equipe interna.
- Corpo: "Prezados(as), boa tarde! / Segue FRC do Consórcio {Nome} de medição ({n}°) de execução e seu
  referido reajuste, período DD/MM/AAAA á DD/MM/AAAA. / Cordialmente,".
- Anexos: `FRC {nº} - CONSÓRCIO {NOME} ({n}° MEDIÇÃO DE EXECUÇÃO {CIDADE}).pdf` + NFSEs de cada consorciada.
  Numeração contínua por consórcio (Integra BRT 20; Leblon 48/49 em 07/2026, 50/51 em 08/2026).
- No envio ao órgão vai como planilha `FRC - FATURA DE RECEBIMENTO DE CONSÓRCIO.xlsx` junto com NFs e certidões.

## 6. Inventário (17 obras no período)
Complexo Cultural (IC 099/2024, 21ª–23ª), Orla (IC 067/2024, 25ª + reaj. 21ª–25ª), Xtreme (IC 077/2025,
12ª–14ª), Espaço Show (IC 060/2024, 25ª–27ª), Granito (10ª), Integra BRT (IC 041/2025, 9ª–14ª), Estações
BRT (IC 176/2025, 2ª–6ª), Terminais BRT (IC 044/2026, 1ª), MT-402 (IC 019/2024, 24ª, 26ª, 27ª), MT-388
(IC 082/2025, 10ª–13ª), 5 Bairros (IC 161/2022, 33ª), Cavalaria (IC 004/2026, 5ª, 6ª), Leblon (IC 012/2024,
25ª–28ª), Oriundi (IC 074/2021, 43ª, 46ª, 47ª), Região Oeste (CT 128/2022, reaj. 40ª/41ª, 52ª), Coxipó 2ª
etapa (reaj. 9ª), Maternidade VG (CT 118/2025, 1ª, 2ª). Entre 1 e 6 protocolos por obra em 4 meses; ≥ 50
e-mails de protocolo e ≥ 50 threads de espelho.

Endereços por papel: ver seções 1, 2 e 5. Cópia interna da engenharia: as duas operadoras, a engenheira,
o dono e mais quatro pessoas da engenharia.

## 7. O que automatizar e o que cadastrar
1. Corpo: 100% automatizável (3 textos fixos; só a saudação varia por horário).
2. Assunto: 100% por template por órgão; separadores variam por obra e precisam de cadastro.
3. Destinatários: automatizável com cadastro por contrato: endereço de protocolo fixo + fiscal nominal
   editável com histórico (troca com o tempo) + CC fixo por família de órgão.
4. Numeração `CT-{nnn}-LT-{ano}`: contador sequencial GLOBAL da empresa (CT-200 a CT-303 atravessam todas
   as obras em ordem cronológica); medição e reajuste consomem dois números consecutivos.
5. Anexos MTPAR: 1 PDF único com nome = assunto. Anexos SINFRA: PDF DocuSign + XLSX editável com revisão
   escolhida pela engenharia (semi-automatizável).
6. Cadastro por contrato: órgão, superintendência, endereço de protocolo, fiscal atual, supervisora,
   medição e reajuste juntos ou separados, exige XLSX, exige justificativa de atraso, limite de 25 MB e
   ordem de check-list (SINFRA).
7. Espelho ao faturamento: o mais automatizável (destinatários e corpo fixos; nº de docx por regra).
8. FRC: não automatizar o envio, só o gatilho (a controladoria emite e numera).
9. Devolutiva do nº de protocolo: não automatizar a captura (PDF anexo, remetentes instáveis, três Gmails
   do SINFRA; MTPAR não responde). Registro humano ou nada.
