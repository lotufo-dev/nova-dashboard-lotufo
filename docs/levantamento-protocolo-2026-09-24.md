# Levantamento do protocolo de medição (bloco 5, tarefa 5.0), 2026-09-24

Base das cartas e das peças que o sistema monta. Os textos literais das cartas estão em `cadastro/cartas.yaml`;
aqui fica a origem de cada um, a estrutura e o que ficou sem documento. Tudo foi lido de cópias no scratchpad
(DT2 do plano); nada foi enviado nem alterado no SharePoint.

## Fontes lidas

| Família | Documento | Data | Observação |
|---|---|---|---|
| MTPAR | CT-301/LT/2026 e CT-302/LT/2026 (Complexo Cultural) | 16/09/2026 | papel timbrado atual; logo extraído para `cadastro/modelos/carta/logo-lotufo.jpg` |
| SES | CT/232/LT/2026 e CT/233/LT/2026 (Hospital Regional de Alta Floresta) | 17/07/2026 | lista numerada; local da carta é o município da obra |
| SINFRA (SUPU) | CT/050/LT/2026, 27ª medição, IC 161/2022 (5 Bairros) | 02/03/2026 | 51 páginas: carta + peças |
| SINFRA (SUPU) | CT/051/LT/2026, reajuste da 27ª medição, IC 161/2022 | 02/03/2026 | carta curta, 25 páginas |
| SINFRA (SUEF II) | CT/058/LT-CUIABÁ/2026, 7ª medição, IC 082/2025 (MT-388) | 02/03/2026 | papel timbrado atual |
| SINFRA (SACID) | CT/291/LT/2026, 1ª RPFO, IC 004/2026 (Cavalaria) | 21/08/2026 | só o cabeçalho (destinatário e A/C) |
| SINFRA (SAGPM) | CT 048/2026 do Consórcio Integra BRT | 2026 | só o nome da secretaria adjunta |
| SINFRA | IN 001/2024 com anexos (76 páginas), SharePoint da MT-388 | — | art. 4º §1º e Anexo II; o Anexo III (check-list) é imagem, sem texto |

## Estrutura comum das cartas

Timbre, número do ofício, local e data, destinatário (órgão, secretaria adjunta, superintendência), A/C com
o fiscal e o cargo (às vezes com a portaria), Ref. com o contrato e o objeto por extenso, assunto, vocativo pelo
tratamento do fiscal, corpo, fecho e assinatura do diretor. O sistema gera tudo isso de
`cartas.yaml`, `orgaos.yaml` (`carta_destinatario`) e do contrato (fiscal vigente, `objeto_completo`).

## MTPAR

- Corpo: qualificação da empresa, "utiliza-se da presente para encaminhar os arquivos relativos" à medição,
  com período, e a lista em romanos minúsculos ("i. ...;", o último com ponto final).
- Itens: nota fiscal e certidões, nessa ordem; certidões na ordem municipal, trabalhista, estadual, federal, FGTS.
- Destinatário: uma linha, "A MT PARTICIPAÇÕES E PROJETOS S.A – MT-PAR".
- E-mail pede devolutiva com o número de protocolo.

## SES

- Corpo: qualificação com sala 07 e CEP, encaminha a medição "da" obra, "Tendo como anexo os documentos abaixo:"
  e lista numerada; várias medições juntas viram sub-itens "Sendo: ...".
- Local da carta é o município da obra; assinatura com "Eng°" e CREA.
- Peças na ordem do pacote real: ART, diário, relatório fotográfico, cronograma, boletim, memoriais, ensaios.
- Certidões na ordem estadual, federal, FGTS, municipal, trabalhista.

## SINFRA

### Carta de medição (CT/050 e CT/058)

- Destinatário em três linhas: a secretaria ("Infraestrutura e Logística" no timbre novo), a secretaria adjunta
  (SAOR nas rodoviárias) e a superintendência. Na SUEF II o A/C é a própria superintendente, com cargo e sigla.
- O corpo cita as INs 003/2024 e 005/2024/GS/SINFRA/MT e encaminha "para análise e posterior aprovação" os
  arquivos da medição, com período.
- Lista em romanos maiúsculos com hífen: "I - Diagrama Linear dos serviços;", depois memória de cálculo geral
  (folha de medição, ficha de canteiro, ficha de mobilização), ficha de índices pluviométricos, croqui de
  localização e ensaios tecnológicos da empreiteira.
- Fecho com "Atenciosamente,"; assinatura "Lotufo Engenharia e Construções Ltda / nome do diretor".

### Carta de reajuste (CT/051)

Carta própria e curta: "Encaminhamos para análise e aprovação planilha de reajustamento" da medição, com o
ordinal por extenso entre parênteses ("27ª (vigésima sétima)"), e fecho "Cordialmente,". O sistema usa
`reajuste_carta_assunto` e `reajuste_carta_corpo` quando o protocolo é só de reajuste, e o campo
`{numero_extenso}` (`carta.ordinal_extenso`).

### IN 001/2024: documentos da contratada (art. 4º §1º), na ordem

1. Cronograma físico-financeiro de evolução mensal
2. Diagrama linear
3. Memória de cálculo
4. Ficha dos índices pluviométricos
5. Croqui de localização
6. Registro fotográfico com coordenadas
7. Diário de obras
8. Ensaios tecnológicos da empreiteira

Protocolo até o 1º dia útil do mês seguinte. O reajuste corre em processo próprio (Anexo II, documentos 1, 2,
4, 5 e 6). O Anexo II ("resumo suporte documental de medição para obras", itens 1 a 18) lista também o que é
do fiscal e da supervisora, fora do pacote da contratada.

### Como virou cadastro

- `pecas` das cinco superintendências na ordem do art. 4º §1º, restritas à execução (`naturezas: [execucao]`);
  "Planilha de reajustamento" só no reajuste; planilha editável exigida e solta nas duas.
- Exigidas nas rodoviárias (SUPU, SUEF I, SUEF II): as cinco das cartas reais (diagrama, memória,
  pluviometria, croqui, ensaios). Na SAGPM e na SACID (obras urbanas e edificação), só a memória e a planilha:
  as outras aparecem na carta quando anexadas.
- Tipos novos de peça: `diagrama`, `pluviometria`, `croqui`. A memória de cálculo usa o tipo `boletim`.
- 05/11/2026 (issue #462): `no_oficio: true` na peça diz que ela vai dentro do PDF assinado do ofício (não cobra
  nem se anexa no envio da planilha/carta nem na etapa `medicao` do protocolo); `pecas_no_oficio` no contrato
  substitui essa marca só nele. Mapeamento por obra em `docs/mapeamento-pecas-planilha-carta-2026-11-05.md`.

## Prefeituras

Sem carta nova no levantamento: o texto de `cartas.yaml` segue o padrão MTPAR, e o relatório fotográfico vai
solto no e-mail, opcional.

## Sem documento

- **SUOESP**: nenhuma carta; o destinatário da SAGPM usa só a secretaria adjunta.
- **SAGPM**: a carta encontrada é do Consórcio Integra BRT, com timbre do consórcio; a da Lotufo ainda não foi vista.
- **Anexo III da IN 001/2024** (check-list) é imagem; a ordem usada é a do art. 4º §1º, que as cartas reais seguem.
- **CT/245/LT/2026** (conclusão, Orla): fica para o bloco 7, que é quem usa.
