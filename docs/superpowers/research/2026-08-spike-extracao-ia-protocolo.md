# Spike — Extração por IA no corpus real (protocolo do experimento)

**Ordem do dono (2026-08-31, pós-merge da fase 2):** usar IA para extrair informações no lugar de digitação manual. Modelo decidido: **híbrido (c)** — regras determinísticas onde bastam, IA só no ambíguo. Regra de produto: **ações com custo externo são exclusivas do perfil admin**.

## Pergunta do spike

A extração por LLM supera o baseline de regex v2 (spike da fase 0) o suficiente para virar o extrator primário das fases 4-7 — e com que taxa de erro em CAMPOS DE DINHEIRO?

## Corpus

1. **E-mails** (caixa do dono via MCP, acesso verificado em 2026-08-31): os 46 assuntos rotulados do spike da fase 0 (2026-05..08: 6 protocolos, 15 espelhos, 8 FRC, 17 ruído) + amostra nova de 2026-08 (fluxo vivo confirmado). Ground truth: os rótulos da fase 0.
2. **Documentos**: 3-5 espelhos de NF (docx, OneDrive NOTAS FISCAIS — caminho conhecido), 2-3 ofícios protocolados (PDF), 1 termo aditivo assinado (PDF, SharePoint DEPARTAMENTO DE ENGENHARIA), 1 instrumento contratual (ex.: Contrato 019.2024 SINFRA, localizado no SharePoint).

## Método

- **Extrator = a própria sessão do Claude** (sem custo de API adicional no spike; o custo por documento em produção é estimado ao final por contagem de tokens).
- Por item: extrair o payload no formato EXATO da fila de sugestões da fase 2 (`{contrato_id?, numero, tipo, competencia, valor_protocolado_centavos}` + tipo de evento + confiança + evidência literal).
- **Dinheiro nunca é aceito da IA sem verificação**: todo valor extraído é re-localizado no texto-fonte por busca literal (o código valida, a IA aponta).
- Comparar contra: (a) ground truth humano; (b) baseline regex v2 (números da fase 0: espelho auto-aplicável, protocolo 6/6 com competência, FRC só sugerir).

## Métricas de decisão

- Precisão/recall por categoria e POR CAMPO (nº, competência, valor, ofício, contrato).
- Erros de dinheiro = métrica eliminatória (1 valor errado com confiança alta reprova o modo auto-aplicar).
- Custo estimado por e-mail/documento em produção (tokens × preço API).
- Recomendação final: o que fica com regra (gate determinístico), o que vai para IA, o que exige humano — por categoria.

## Saída

Doc de resultados no padrão dos spikes da fase 0 + emenda proposta à spec (fases 4-7) com o desenho híbrido e a permissão admin-only para disparos com custo.
