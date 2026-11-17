# Nomes de arquivo por obra no ciclo de medição (Outlook, 2026-09-17)

Fonte: caixa do dono via conector Microsoft 365, só leitura, período
2026-05-13 a 2026-09-17. 16 das 17 obras com exemplos reais (Via Parecis / Deciolândia não aparece).
Pergunta de origem: "tem diferença de modelo de nome de arquivo entre as obras? Creio que para consórcio
é diferente, por exemplo BRT".

## Resposta

Sim, e a diferença é sistemática. Consórcio muda o nome em cinco eixos, nenhum deles presente em obra
própria da Lotufo:

1. A consorciada entra no nome (BRT no início: `ESPELHO - GUAXE - ...`; Leblon no fim: `... - RIVOLI.docx`).
2. O município vira sufixo obrigatório (`- CBA`, `- VG`), porque a obra cruza dois municípios e gera NFS-e
   separadas.
3. Aparecem `EXECUÇÃO` e `PROJETO` no miolo, porque o contrato remunera as duas coisas em notas distintas.
4. Existe FRC, com numeração sequencial do consórcio, não da medição.
5. O ofício troca a sigla: `LT` vira `CCL` (Leblon) ou `CO` (Oriundi).

MT-388 quebra a regra: não é consórcio e mesmo assim duplica por município (Cáceres, Porto Esperidião),
porque emite NFS-e em duas prefeituras.

## 1. Espelho (.docx ao faturamento)

| Obra | Padrão observado |
|---|---|
| Complexo Cultural | `[Reajuste ]{n}ª medição - Complexo Cultural.docx` (único MTPAR sem o prefixo `ESPELHO - Espelho NF - Lotufo -`) |
| Complexo da Orla | `ESPELHO - Espelho NF - Lotufo - [Reajustes ]{n}ª medição - complexo Orla parque NMT.docx` |
| Complexo Xtreme | `ESPELHO - Espelho NF - Lotufo - [ Reajuste ]{n}ª medição - XTreme.docx` (espaço duplo no reajuste; XTreme/Xtreme) |
| Cobertura Espaço Show | `ESPELHO - Espelho NF - Lotufo - Cobertura espaço Show - [Reajuste ]{n}ª medição.docx` (obra antes do nº) |
| Granito | `ESPELHO - Espelho NF - Lotufo - {n}ª medição - Granito.docx` |
| Integra BRT | `ESPELHO - {CONSORCIADA} - Espelho NF - EXECUÇÃO BRT - {n}ª Medição - {CBA\|VG}.docx` — 6 arquivos por ciclo |
| Estações BRT | `ESPELHO - LOTUFO - Espelho NF - {EXECUÇÃO BRT\|PROJETO ESTAÇÕES BRT} - [REAJUSTE ]{n}ª Medição - {CBA\|VG}.docx` — 5 por ciclo |
| Terminais BRT | `LOTUFO - Espelho NF - PROJETO ESTAÇÕES BRT - {n}ª Medição - Terminal {VG\|Porto}.docx` (rótulo "ESTAÇÕES" sendo Terminais) |
| MT-402 | `ESPELHO - Espelho NF - Lotufo MT-402 - {n}ª Medição.docx` |
| MT-388 | `ESPELHO - Espelho NF - Lotufo MT-388 - [Reajuste ]{n}ª Medição - {CÁCERES\|PORTO ESPERIDIÃO} ({MM.AAAA}).docx` — 4 por ciclo |
| 5 Bairros | `ESPELHO - NF - Lotufo 5 Bairros - [Reaj. ]{n}ª Medição.docx` (miolo `NF -`, reajuste abreviado) |
| Cavalaria | `ESPELHO - NF - Lotufo Cavalaria - [Reaj. ]{n}ª Medição.docx` (`06ª` com zero em setembro, `5ª` sem em agosto) |
| Complexo Leblon | `ESPELHO - Espelho NF - Cons. Leblon [Reajustamento da ]{n}ª Medição - {LOTUFO\|RIVOLI}.docx` |
| Oriundi | não encontrado (só FRC e NFS-e circulam) |
| Região Oeste | `ESPELHO - Espelho NF - Lotufo Região Oeste Cuiabá - [Reajuste ]{n} ({MM.AAAA}).docx` (competência com ponto, sem `ª`) |
| Residencial Coxipó 2ª | `Espelho NF - [Reajuste ]{n}a Medição Residencial Coxipó 2a etapa CT 392.docx` (único com nº do contrato) |
| Maternidade VG | mudou no meio do período: julho `Espelho NF - LOTUFO -  {n}ª Medição - MATERNIDADE VÁRZEA GRANDE.docx`; agosto `ESPELHO - Espelho NF - Lotufo - Maternidade VG - {n}ª Medição.docx` |

## 2. NFS-e devolvida pelo faturamento

Padrão dominante: `{DD-MM-AA} NFS {nº} [REAJ ]{n}° MED {DESCRITOR}.pdf`, sempre com `°`, nunca `ª`.
Descritores por obra: `COMPLEXO CULTURAL PQ NMT`, `COMPLEXO DA ORLA PQ N MT`, `COMPLEXO XTREME`,
`ESPAÇO SHOW PQ NMT`, `ASSENT. PAGINAÇÃO GRANITO`, `INTEGRA BRT {CBA|VG} LOTUFO`,
`ESTAÇÕES DO BRT {CBA|VG}`, `ELABORAÇÃO PROJETO TERMINAL BRT {PORTO CBA|VG}`, `PAVIMENTAÇÃO MT-402`,
`PAVIMENTAÇÃO RODOVIA MT-388 {CACERES|PORTO ESPERIDIÃO}`, `PAVIMENTAÇÃO 5 BAIRROS`,
`SEDE DA CAVALARIA PQ N MT`, `COMPLEXO VIARIO LEBLON`, `REGIÃO OESTE`, `RES. COXIPO 2° ETAPA`,
`MATERNIDADE E UTI NEONATAL VG`.

Exceções: Rivoli usa convenção própria (`{DD-MM-AAAA} - NF {nº} {n}ª MED CONSORCIO LEBLON - RIVOLI.pdf`);
Oriundi vem pela controladoria sem data (`NFS-e {nº} - GRUPO {LOTUFO|RIVOLI} ({n}° MEDIÇÃO DE EXECUÇÃO {CBA|VGE}-MT).pdf`);
Guaxe e Encomind mandam o objeto por extenso. Erros reais observados: `114-09-26` (dígito espúrio, 3 vezes),
`ESTAÇOES` sem til, espaços duplos, `ECOMIND` no espelho virando `(ENCOMIND)` na nota.

## 3. Protocolo ao órgão

São dois protocolos distintos: (A) protocolo da medição (ofício assinado + planilha editável) e
(B) protocolo da nota fiscal (NFS-e + documentos de regularidade + certidões).

| Obra | Ofício / arquivo | Formato |
|---|---|---|
| MTPAR (5 obras) | `CT-{nnn}-LT-2026 - [Reajuste ]{n}ª Medição - {Obra} MTPAR.pdf` | 1 PDF único por ofício, sem XLSX |
| Integra BRT | `Complete com a Docusign: Planilha_{n}ªmedição_BRT_({MM-AAAA}) - IC {IC} - rev01.pdf` | vários; XLSX `rev01`; ZIP de ensaios anexo e croqui por link |
| Estações BRT | `CT_{nnn}_LT_2026_-_[Reajuste_]{n}ª_Medição_Estações_BRT_({MM_AAAA}).pdf` | vários; XLSX `REV03`/`REVFinal`; `CERTIDÕES LOTUFO.zip` |
| Terminais BRT | `Complete_com_o_Docusign_{n}ª_Medição_ Terminais.pdf.zip` | vários; XLSX sem revisão |
| MT-402 | `CT-{nnn}-LT-2026_-_{n}ª_Medição_({MM_AAAA})_-_IC_{IC}_-_MT402.pdf` | vários; XLSX com sufixo ` r` |
| MT-388 | `Complete_com_o_Docusign_{n}ª_Medição_({MM_AAAA}.pdf` (truncado pelo DocuSign) | vários; XLSX `Rev01` |
| 5 Bairros | `CT-{nnn}-LT-2026_-_{n}ª_{Medição\|Reajuste}_({MM_AAAA})_-_IC_{IC}_-_5_Bairros.pdf` | 2 ofícios + 2 planilhas |
| Cavalaria | `CT-{nnn}-LT-2026_-_{n}ª_Med._({MM_AAAA})_-_Cavalaria.pdf` | vários; XLSX `Rev01` |
| Complexo Leblon | `Complete_com_o_Docusign_CT-{nnn}-CCL-2026_-_{n}.pdf` | 1 PDF; XLSX por link do SharePoint |
| Oriundi | `CT-{nnn}-CO-2026 - {n}ª Medição ({MM_AAAA}) - IC {IC} - Oriundi.pdf` | vários; XLSX `RV1`; `Certidões Oriundi.zip` |
| Região Oeste | migrou para ZIP único por link: `{n}ª Medição ({MM_AAAA}) - Região Oeste - CT 128_2022.zip` | certidões como PDFs avulsos |
| Coxipó 2ª | sem ofício: NFS-e + `CERTIDÕES.zip` | a medição vem do órgão |
| Maternidade VG | `CT-{nnn}-LT-2026 - Encaminha Nota Fiscais - {n}ª medição ({MM_AAAA}).pdf` | + relatório fotográfico + ZIP de certidões |

## 4. FRC: três convenções diferentes entre três consórcios

| Consórcio | FRC | Numeração |
|---|---|---|
| Integra BRT | `FRC {seq} - GRUPO LOTUFO ({n}° MEDIÇÃO DE EXECUÇÃO).pdf` (titular oscila com `CONSÓRCIO INTEGRA BRT`) | sequencial simples (20, 21), 1 por ciclo |
| Complexo Leblon | `FRC {seq} - CONSÓRCIO COMPLEXO LEBLON ([REAJUSTE DA ]{n}° MEDIÇÃO DE EXECUÇÃO CBA-MT).pdf` | sequencial, 2 por ciclo (44/45, 48/49, 50/51) |
| Oriundi | `FRC {AAAAMMDD}{seq} - CONSÓRCIO ORIUNDI ([REAJUSTE ]{n}° MEDIÇÃO {MM.AAAA}).pdf` | data + sequencial do dia |

## 5. Planilha da medição (.xlsx)

Sufixos de revisão observados, todos diferentes: `Rev01` (MT-388, Cavalaria), `REV03` e `REVFinal`
(Estações), `rev01` minúsculo (Integra BRT), `RV1` (Oriundi), ` r` (MT-402), `REV01` (Região Oeste),
nenhum (5 Bairros, Terminais, Leblon). MTPAR nunca recebe planilha editável.

## 6. O que o sistema gera sozinho

- **Espelho: 100%.** Depende só de obra, nº, tipo, competência e, em consórcio, consorciada e município.
- **Ofício de protocolo: ~90%.** Falta o número CT, que é controlado fora do sistema (decisão de
  2026-09-17: preenchido manualmente).
- **Depende de fonte externa:** número e data da NFS-e (nascem no faturamento); número da FRC (a controladoria, três
  convenções); sufixo de revisão do XLSX (vem do vai-e-vem com a fiscalização); nomes gerados pelo DocuSign,
  que prefixa `Complete_com_o_Docusign_` e trunca o resto.
- **Cadastro recomendado:** template mais expressão tolerante por obra e tipo, aceitando como ruído
  esperado o sufixo ` (N)` de download duplicado, ponto duplo antes da extensão, espaços duplos, `°` × `ª`
  × `a`, e `_` × espaço. Prever que planilhas e ZIPs grandes chegam por link do SharePoint (Leblon, Região
  Oeste, croquis do BRT): quem só lê anexos perde esses.
