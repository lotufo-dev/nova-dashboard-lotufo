# Spike — Extração por IA no corpus real: resultados

**Executado em 2026-08-31**, pós-merge da fase 2, por ordem do dono ("usar IA para extrair, sem inserção manual"). Protocolo em `2026-08-spike-extracao-ia-protocolo.md`. Método: extração CEGA por Claude **Sonnet** (o tier realista de produção), julgada pelo controller contra gabaritos independentes; dinheiro re-verificado por busca literal na fonte.

## Corpus

- **86 e-mails reais** (2026-05..08, caixa do dono): 21 protocolos, 16 espelhos, 9 FRC, 8 NF-ao-órgão, 32 ruídos difíceis (DocuSign com "CT-…-Protocolo", a controladoria não-FRC, supervisora devolvendo medição etc.). 34 com corpo coletado.
- **5 documentos reais**: 3 espelhos de NF (MTPAR, SES/reajuste-sem-INSS, SEMOP), cláusulas de valor/prazo do Contrato 019/2024 SINFRA, 1º Termo Aditivo 082/2025 (valor).
- Gabaritos com **armadilhas deliberadas**: nota de empenho imitando valor global; espelho declarando NÃO-retenção de INSS; apostilamento imitando nº de contrato; data vigente citada num aditivo só-valor; e 3 casos de **assunto mentindo o nº da medição** (assunto reaproveitado de e-mail anterior).

## Resultados — e-mails (Sonnet, cego)

| Métrica | IA | Baseline regex v2 (fase 0) |
|---|---|---|
| Categoria correta | **86/86 (100%)** | espelho 100 · protocolo 100 (núcleo) · **FRC 13%** |
| nº da medição | **51/51** | 67-80% "extração completa" |
| competência (extraível da entrada) | **46/46** | idem |
| ofício / IC-contrato / nº FRC | **14/14 · 38/38 · 9/9** | FRC: inviável por assunto |
| consórcio | 13/17 (76%) | — |
| e-mails multi-medição | **2/2 duplos + 1 quíntuplo (5/5 eventos)** | finditer parcial |
| campos inventados (alucinação) | **0** | n/a |

**Adjudicações relevantes (registradas contra o gabarito):**
1. Nos 20 e-mails "execução + reajuste"/multi-itens, o extrator produziu N eventos onde o gabarito registrou 1 — **o extrator está certo** (formato do gabarito subcontava); ex.: FRC 48+49 viraram 2 eventos com nº de FRC cada, granularidade melhor que o próprio gabarito.
2. Nos 2 casos de **assunto mentiroso** (24ª×25ª; 43ª×46ª), o extrator seguiu o corpo com `fonte_numero=corpo` e evidência verbatim — **venceu o gabarito humano**, que havia copiado o assunto.
3. Nos 3 casos de competência ausente da entrada, o extrator devolveu `null` em vez de chutar — o comportamento desejado num sistema financeiro.
4. Única fraqueza real: **consórcio** omitido em 4 casos onde o nome estava no assunto ("Oriundi", "Leblon") — correção trivial: dicionário de consórcios conhecidos no prompt (Oriundi=12, Leblon=17, Integra BRT=18, já mapeados na fase 0).

## Resultados — documentos (Sonnet, cego)

**100% dos campos** · **14/14 valores de dinheiro re-localizados literalmente nas fontes** · **4/4 armadilhas vencidas** (empenho R$ 5,2M ≠ valor global R$ 15,1M, nomeado na observação; INSS registrado 0 com a IN citada; contrato 128/2022 ≠ apostilamento; 06/06/2027 corretamente NÃO lançada como nova data do aditivo). Nenhum valor derivado inventado (líquido ausente = null nos 3 espelhos). Confianças auto-reportadas calibradas: os 2 campos que o extrator rebaixou (0.75/0.85) são exatamente os que o gabarito marcou como inferidos/ambíguos.

**Métrica eliminatória (erro de dinheiro): ZERO.**

## Custo estimado de produção

Por e-mail (assunto+corpo+prompt ≈ 1,5-3k tokens): **≈ R$ 0,05-0,10 com Sonnet**. Por documento (espelho/aditivo): ≈ R$ 0,15-0,40. Volume real (dezenas de e-mails relevantes/mês): **unidades de reais por mês**. Custo não é fator de decisão.

## Recomendação (modelo híbrido c, decidido pelo dono)

1. **Gate determinístico continua na frente** (barato, sem egress): remetente+prefixo triam o ruído óbvio e identificam o candidato. O que passa o gate vai à IA.
2. **IA como extrator de campos de tudo que passa o gate** — substitui as regex de extração (frágeis) e resolve o que elas estruturalmente não alcançam: FRC (13%→100%), retorno do órgão (data confirmada no corpo), multi-medição, formatos variantes.
3. **Regra nova descoberta pelo spike:** quando assunto e corpo divergem, **o corpo vence e a sugestão NUNCA auto-aplica** — vai à fila com a divergência como evidência. (3 casos reais no corpus; é o modo de falha mais perigoso do processo por e-mail.)
4. **Auto-aplicar** (fase 6) exige: confiança alta + campos completos + fonte coerente (sem divergência assunto×corpo). Resto = sugestão de 1 clique.
5. **Documentos** (fases 4 e 7): extração IA + validador de código obrigatório — todo valor de dinheiro re-localizado literalmente na fonte antes de entrar em payload (o passo que este spike executou via grep); aditivos ganham conferência aritmética (novo = anterior + delta).
6. **Consórcios**: dicionário fixo no prompt.
7. **Custo/permissão**: extração automática roda nos workers (fase 6); disparo MANUAL de extração pela dashboard é **admin-only** (regra do dono, 2026-08-31).

## Próximo passo

Emenda à spec redesenhando as fases 4-7 com o extrator híbrido (gate determinístico → IA → validador de código → fila de sugestões) — a fila da fase 2 já tem todos os campos necessários (`confianca`, `evidencia`, `origem`, `tipo` livre); nenhuma migração nova.
