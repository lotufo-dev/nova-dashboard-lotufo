# Spike de detecção — padrões de assunto contra o histórico real do Outlook

**Task 2 da Fase 0** · Executado em 2026-08-31, inline na sessão principal, via MCP `outlook_email_search` na caixa do dono.

## 1. Amostra usada

Buscas por `"Medição"` (todas as pastas e Itens Enviados), `"Emissão NF"` (todas as pastas e Itens Enviados), `"protocolo"` (Itens Enviados) e remetente da controladoria, cobrindo o período **2026-05 a 2026-08** (o que a busca de relevância do Graph devolveu; ~100 e-mails varridos, 46 assuntos distintos rotulados):

| Categoria | Assuntos distintos | Observação |
|---|---|---|
| Protocolo de medição | 6 | Volume real de protocolo POR E-MAIL é baixo — parte do fluxo é conduzida pela operadora e o retorno vem de gmails do órgão (três e-mails de superintendências da SINFRA) |
| Espelho (Emissão NF) | 15 | Enviados pelo dono e pela operadora |
| FRC (consórcio) | 8 | Remetente é sempre a controladoria |
| Ruído (não deve casar) | 17 | NF-e de fornecedores, NF pessoal, DANFE, faturas, DocuSign, ofícios do órgão, envio de NF ao órgão |

O mínimo de 30/categoria do plano não existe no alcance da busca para protocolo e FRC — vale a regra "ou tudo que existir". A medição foi automatizada (script em anexo do spike, corpus verbatim embutido); números reproduzíveis.

## 2. Regex finais ajustadas (v2)

As candidatas do plano (v1) falharam no histórico real; as v2 abaixo são as que a fase 6 deve implementar.

```python
# PROTOCOLO — núcleo obrigatório: ofício + nº da medição; competência e IC OPCIONAIS.
# O separador real é "_-_" ou " - "; a competência vem como (07_2026); o IC vem como
# IC_082_2025 (underscore, que \s NÃO casa — principal defeito da v1).
PROTOCOLO_MEDICAO = re.compile(
    r"(?P<oficio>CT[-/ ]\d{2,4}[-/ ](?:LT|CO)[-/ ]\d{4})"
    r"[_ ]*-?[_ ]*(?P<num>\d{1,3})ª[_ ]?Medi[çc][ãa]o"
    r"(?:[_ ]*\((?P<comp>\d{2}[_/:]\d{4})\))?"
    r"(?:.*?(?P<ic>IC[_ ]*n?[º°]?[_ ]*\d{1,4}[_/]\d{4}))?", re.I)

# ESPELHO — em duas partes: um GATE de prefixo (mata o falso positivo
# "Emissão NF Eletrônica realizada pela empresa ..." dos fornecedores) e um
# finditer de itens, porque UM e-mail real carrega até DUAS medições.
ESPELHO_GATE = re.compile(
    r"^(?:RE:|ENC:|FW:|Fw:|Re:)?\s*(?:Emiss[ãa]o|Espelho)[ ]?NF\b(?!\s+Eletr[ôo]nica)", re.I)
ESPELHO_ITEM = re.compile(
    r"(?:Reajuste\s+(?:d[ao]\s+)?)?(?P<num>\d{1,3})ª\s*medi[çc][ãa]o"
    r"(?P<reaj_suf>(?:\s+(?:de\s+Reajuste|e\s+reajuste))?)"
    r"(?:\s*\((?P<comp>\d{2}[/:_]\d{4})\))?", re.I)

# FRC — regex de assunto existe, mas só 1 dos 8 FRCs reais a exercita (ver §4);
# o detector real é remetente + corpo.
FRC_ASSUNTO = re.compile(
    r"\bFRC\b[ ]*(?:N[º°]?[ ]*)?(?P<nums>\d+(?:[ ]*E[ ]*\d+)*)?", re.I)
```

Exemplos reais casados pela v2:

- `CT-271-LT-2026_-_12ª_Medição_(07_2026)_-_IC_082_2025_-_Porto_Espiridião` → ofício `CT-271-LT-2026`, nº 12, comp `07_2026`, IC `IC_082_2025` (a v1 **não** casava: `\s` não casa `_` no IC).
- `CT-017-CO-2026 - 47ª Medição (07_2026) - IC 074_2021 - Oriundi` → variante `CO` de consórcio, espaços.
- `Emissão NF - 40ª Medição de Reajuste (07/2025) - 41ª Medição de Reajuste (08/2025) - Região Oeste - CT 128/2022` → **dois** itens extraídos (40ª/07-2025 e 41ª/08-2025); a v1 só via o primeiro.
- `Emissão NF - 10ª Medição e Reajuste (05:2026) - …` → typo real de dois-pontos na competência, aceito e normalizável.

## 3. Tabela de precisão

Medida sobre o corpus rotulado (46 assuntos). "Extração completa" = todos os campos necessários para auto-aplicar presentes (protocolo: nº + competência; espelho: nº + competência; FRC: nºs).

| Categoria | Regex | Casou (recall) | Extração completa | Falsos positivos |
|---|---|---|---|---|
| Protocolo | v1 (plano) | 1/6 (17%) | 17% | 0 |
| Protocolo | **v2** | **6/6 (100%)** | **4/6 (67%)** | 0 |
| Espelho | v1 (plano) | 11/15 (73%) | 73% | 4 |
| Espelho | **v2** | **15/15 (100%)** | **12/15 (80%)** | 6\* |
| FRC | v1 (plano) | 1/8 (13%) | 13% | 0 |
| FRC | v2 (assunto) | 1/8 (13%) | 13% | 0 |

\* Os "falsos positivos" do espelho v1/v2 são todos o mesmo fenômeno: as **respostas `RE:` da controladoria na thread do espelho são a chegada da FRC** — o assunto é idêntico ao do espelho. Não é defeito de regex; é prova de que assunto sozinho não separa as duas categorias (ver §4).

## 4. Falsos positivos/negativos encontrados e por quê

1. **FRC quase nunca está no assunto** (7 de 8 casos). A FRC chega como `RE:` no próprio thread do espelho ("Segue as FRC Faturas de Recebimento de Consórcio relativo a 48ª…" — só no corpo). Regex de assunto é estruturalmente incapaz aqui. O discriminador real e estável é: **remetente = a controladoria + "FRC" no corpo** (8/8 na amostra); nº da FRC e consórcio extraíveis do corpo (`FRC … relativo a Nª … Consórcio X`).
2. **`\s` não casa `_`** — o formato dominante de protocolo usa underscore em TUDO (`IC_082_2025`), o que derrubava a v1 para 17%.
3. **Competência e IC faltam em parte dos protocolos reais**: `CT-289-LT-2026 - 22ª Medição - Complexo Cultural MTPAR` (sem ambos) e `CT/243/LT/2026 - 25ª medição contratual (01/06/2026 a 30/06/2026)` (período por extenso no lugar da competência; barras no ofício). Núcleo ofício+nº casa; auto-aplicação exige a competência.
4. **Fornecedores usam "Emissão NF"**: `Emissão NF Eletrônica realizada pela empresa …` (Multhifer, Ferragens Amazon). O gate `(?!\s+Eletrônica)` + exigência de `Nª medição` elimina todos na amostra; cinto-e-suspensório: exigir também remetente interno.
5. **Duas medições num e-mail só** é comum (2/15 espelhos): a detecção deve criar **um evento por item** (finditer), não um por e-mail.
6. **Typo real de dois-pontos** na competência (`05:2026`) — aceitar `[/:_]` e normalizar para MM/AAAA.
7. **Categoria nova observada, fora do escopo das 3**: envio da NF emitida ao órgão, com prefixo `NF - Nª Medição …` (4 ocorrências, para a CAF da Prefeitura de Cuiabá). Não casar como espelho (o gate exige Emissão/Espelho). Candidata a 4ª categoria na fase 6.
8. **Retorno de protocolo** vem de gmail do órgão como `Re:` do mesmo assunto, com a informação decisiva no corpo ("25ª medição foi protocolada em 06/08/2026"). A data do e-mail de ida ≠ data do protocolo em parte dos casos — o órgão às vezes segura ("aguardaremos o protocolo da 25ª"). Para a fase 6: data de protocolo confirmada = a do retorno, quando existir.

## 5. Recomendação por categoria

Critério do plano: `auto-aplicar` exige precisão ≥ 98% **e** campo completo.

| Categoria | Recomendação | Regra completa (regex + contexto) |
|---|---|---|
| **Espelho (Emissão NF)** | **auto-aplicar** quando gate + nº + competência presentes E remetente interno da equipe (o dono e a operadora) E não for `RE:` de terceiro; **sugerir** quando faltar competência (3/15) | Na amostra: 0 FP com a regra completa; extração completa em 80% |
| **Protocolo de medição** | **auto-aplicar** quando ofício + nº + competência presentes (4/6) E destinatário/remetente é o canal do órgão; **sugerir** sem competência (2/6) | Amostra pequena (n=6) — reavaliar no backfill retroativo da fase 6 antes de confiar o histórico |
| **FRC** | **somente sugerir** (nunca auto-aplicar por assunto). Detector: remetente da controladoria + `FRC` no corpo; vínculo à medição pelo thread (`internetMessageId`/`conversationId`) do espelho + nº extraído do corpo | Assunto sozinho: 13% de recall — inviável |

Regra transversal que a amostra provou necessária: **detecção = regex de assunto + remetente/direção + posição no thread**, nunca regex sozinha. As respostas `RE:` no mesmo thread mudam de categoria (espelho → FRC) mantendo o assunto.

## 6. Disciplina de assunto para a equipe

1. **Padrão canônico de protocolo** (já é o dominante — formalizar): `CT-NNN-LT-AAAA_-_Nª_Medição_(MM_AAAA)_-_IC_NNN_AAAA_-_Obra`. Underscore ou espaço, tanto faz — mas **sempre incluir a competência `(MM_AAAA)`** e o IC/CT do contrato; são eles que faltaram nos 2 casos não auto-aplicáveis.
2. **Espelhos**: manter prefixo `Emissão NF - ` (não variar para `Espelho NF`); competência sempre entre parênteses com barra (`(07/2026)`, sem dois-pontos); em e-mail com mais de uma medição, manter o formato `Nª Medição (MM/AAAA)` para cada uma.
3. **FRC**: pedir à controladoria que responda com assunto próprio `FRC Nº NN - CONSÓRCIO X (Nª MEDIÇÃO)` — como no único caso detectável — em vez de `RE:` do espelho. Enquanto isso não acontecer, a detecção usa remetente+corpo (funciona, mas fica em "sugerir").
4. **Um evento por e-mail quando possível** — e-mails com duas medições funcionam, mas dobram a chance de ambiguidade no vínculo NF↔medição.

## 7. O que a fase 6 implementa (resumo executável)

- As 3 regex v2 do §2, com os contextos do §5 (remetente, direção, thread).
- Normalização: competência `[/:_]` → `MM/AAAA`; ofício `CT[-/ ]` → `CT-NNN-XX-AAAA`; IC `_` → `NNN/AAAA`.
- Um evento por item de medição (finditer no espelho).
- FRC por remetente+corpo com vínculo por `conversationId`.
- 4ª categoria futura: `NF - Nª Medição …` (envio da NF ao órgão).
- Backfill: reavaliar a precisão de protocolo com o histórico completo (n=6 aqui) antes de auto-aplicar retroativamente.
