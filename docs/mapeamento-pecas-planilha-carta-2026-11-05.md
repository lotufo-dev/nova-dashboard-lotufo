# Peças da medição no envio da planilha/carta — mapeamento por obra (05/11/2026)

Origem: na 8ª medição da Cavalaria, a etapa 1 da dashboard ("Peças do órgão" do envio da planilha/carta) pediu,
uma a uma, peças que já estavam dentro do PDF assinado do ofício. A spec de 2026-10-20 §2.1 assumiu "ofício
assinado + zip da planilha + peças exigidas" como anexos separados; este mapeamento mostra como cada obra manda
de verdade.

Fonte: a caixa de e-mail do responsável pela dashboard (só o que chegou com ele em cópia), último envio de medição de cada obra e o anterior,
lidos em 05/11/2026. PDF grande foi lido só nas primeiras ~30 páginas (limite do leitor): o que está depois disso
é presumido pela lista da carta, pelo tamanho e pelo envelope DocuSign único.

## Resultado

| Obra | Órgão | Último envio | Formato | Peças | Repete? |
|---|---|---|---|---|---|
| Cavalaria | SINFRA SACID | 03/11 (8ª) | 1 PDF DocuSign (CT-406, 4 MB) + .xlsx | **dentro do PDF** (carta lista I–V) | sim (7ª, 01/10) |
| MT-402 | SINFRA SUEF I | 05/11 (29ª) | 1 PDF DocuSign (CT-424, 2 MB) + .xlsx | **dentro do PDF** (I–V) | sim (28ª) |
| MT-401 | SINFRA SUEF I | 28/10 (42ª, final) | 1 PDF DocuSign (CT-389, 26 p.) + .xlsx | **dentro do PDF** (I–V, lido inteiro) | sim (33ª a 41ª em 27/10) |
| Parque Atalaia | SINFRA SUEF I (consórcio) | 14/08 (47ª, final) | 1 PDF DocuSign (CT-017-CO) + .xlsx | **dentro do PDF** (I–V) | sim (46ª) |
| MT-388 (Cáceres e Porto Esperidião juntos) | SINFRA SUEF II | 03/11 (15ª) | 1 PDF DocuSign (187 p., 8 MB) + .xlsx | **dentro do PDF** (I–V) | sim (14ª, 241 p.; .xlsx por link) |
| 5 Bairros | SINFRA SUPU | 03/11 (35ª) | 1 PDF DocuSign (CT-401) + PDF do reajuste (CT-402) + 2 .xlsx | **dentro do PDF** (I–V) | sim |
| Complexo Leblon | SINFRA SAGPM (consórcio) | 03/11 (30ª) | 1 PDF DocuSign (127 p., 12 MB); .xlsx por link do OneDrive | **dentro do PDF** (I–V) | sim (29ª, 130 p.) |
| Integra BRT | SINFRA SAGPM (consórcio) | 05/11 (16ª) | PDF da carta + resumo + memória; diagrama, croqui, pluviometria e ensaios em PDFs soltos; .xlsx e zip por link | **misto**: memória dentro, o resto solto | **não**: 15ª zip DocuSign; 14ª PDF único + complemento com croqui e ensaios |
| Terminais BRT | SINFRA SAGPM | 03/11 (3ª) | PDF da carta + resumo + memória (CT-404); diagrama e croqui soltos; reajuste com carta própria (CT-405); .xlsx | **misto**: memória dentro, diagrama e croqui soltos | **não**: 2ª foi zip DocuSign com PDF juntado |
| Estações BRT | SINFRA SAGPM | 03/11 (8ª) | zip do DocuSign + .xlsx | **soltas** (dentro do zip) | não visto |
| Deciolândia | SINFRA SUEF II | — | sem envio desde 06/2026 | sem dado | — |
| HR Alta Floresta | SES-MT | 20/07 (42ª) | sem envio antes da nota: o PDF único da nota já leva carta, NF, certidões e todas as peças | — | não visto |
| Coxipó 3ª etapa | Pref. Cuiabá | 03/09 (12ª, "ajustes") | ao fiscal: PDF do boletim + memória (DocuSign); relatório fotográfico e croqui soltos | **misto**, sem carta | não visto |
| Região Oeste | Pref. Cuiabá | 24/09 (54ª) | ao fiscal: zip/link com .xlsx, tickets e relatório fotográfico; assinados protocolados em papel | **soltas**, sem carta | sim (44ª a 54ª) |
| Coxipó 2ª etapa | Pref. Cuiabá | 13/05 | o órgão manda a medição e pede a NF; a Lotufo só responde com NF e certidões | sem dado | — |
| Maternidade/UTI VG | Pref. VG | 28/07 (1ª) | sem envio antes da nota | — | — |
| BR-163 | Rota do Oeste | — | nenhum e-mail de medição encontrado | sem dado | — |

A carta das obras SINFRA com PDF único lista sempre as mesmas cinco peças, "conforme abaixo elencado":
I Diagrama Linear; II Memória de cálculo geral (folha de medição, canteiro e mobilização); III Ficha de índices
pluviométricos; IV Croqui de localização; V Ensaios tecnológicos. Cronograma, registro fotográfico e diário de
obras não aparecem em nenhuma carta. Exceção: na 14ª da MT-388, a SUEF II pediu o envio final em um PDF por
natureza (até 25 MB, limite do SIGADOC), na ordem do checklist dela, com o cronograma físico-financeiro do
Sinfralog dentro.

## O que isso diz para a dashboard

1. **O padrão da Cavalaria é o da maioria.** Sete das dez obras SINFRA com envio recente mandam as peças dentro
   do PDF assinado. Na SUEF I, SUEF II e SUPU o cadastro exige cinco peças: quando essas obras usarem o envio pela
   dashboard, cada uma abre com cinco pendências e pede justificativa.
2. **A regra é por peça, não só por órgão.** Na SAGPM a memória de cálculo vai sempre dentro do PDF da carta; o
   resto varia por obra (Leblon junta tudo; Integra e Terminais soltam diagrama e croqui) e até por mês. Uma marca
   no cadastro dizendo que a peça "vai no ofício assinado", por órgão com exceção por contrato, cobre todos os
   casos; peça que às vezes vai solta continua opcional e anexável.
3. **Peças que nunca vão** (cronograma, fotos e diário na SINFRA) não deveriam aparecer como linha a anexar.
4. **SES e prefeituras não têm esse envio** como a SINFRA: a SES manda tudo com a nota; nas prefeituras de Cuiabá
   a medição vai direto ao fiscal, sem carta. Hoje a dashboard só tira a MT-PAR do passo
   (`planilha_envio.FAMILIAS_SEM_ENVIO`); se SES e prefeituras devem sair também é decisão à parte.

## O que não foi visto

Conteúdo dos zips e dos links do OneDrive; páginas finais dos PDFs grandes (MT-388, Leblon); envios feitos sem o
responsável em cópia; protocolo em papel (Região Oeste) e sistemas próprios dos órgãos.

