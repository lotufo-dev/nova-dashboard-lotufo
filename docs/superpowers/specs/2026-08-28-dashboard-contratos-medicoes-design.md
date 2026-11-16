# Dashboard de Gestão de Contratos e Medições — Lotufo Engenharia

> **Histórico.** Este documento deixou de ser autoridade em 15/11/2026 (`docs/adr/0001`). As regras vivas estão em
> `.claude/rules/`, `GLOSSARY.md` e `docs/adr/`. Leia-o só para saber de onde veio uma decisão antiga; onde ele e o
> código divergem, vale o código.

**Data:** 2026-08-28 (v3 — modelo de observação automática; v2 incorporou 4 revisões externas; §15 de 2026-09-01 revoga a §14: produto sem custo de API)
**Autor:** Leonardo Praeiro (com Claude)
**Status:** Aprovado em brainstorming + revisão externa + reestruturação de automação; aguardando plano de implementação

## 0. Filosofia (v3)

**Sistema que observa, não sistema onde se registra.** O processo real da Lotufo já deixa rastro digital em três lugares — Outlook (protocolos por e-mail com assunto padronizado, documentos assinados retornando, espelhos e FRCs circulando), SharePoint (planilhas de medição e documentos por obra) e RM (NFs e baixas). A dashboard vigia essas três fontes e monta as linhas do tempo sozinha. O trabalho humano se resume a:

1. Aceitar sugestões com 1 clique (fila única no Painel da Engenharia);
2. Preencher o delta do aditivo quando assinado (única digitação estrutural restante);
3. Upload de certidões estadual/municipal (federais são baixadas por robô); [revogado pela §15 em 2026-09-01: sem robô; upload manual de todas]
4. Resolver os raros casos ambíguos da detecção.

Regra de confiança: o que o sistema deduz com alta confiança é aplicado e marcado "detectado automaticamente" (com desfazer); o que fica ambíguo vira sugestão aguardando clique. Nada é inventado em silêncio. O padrão de assunto dos e-mails já usado pela equipe (ex.: `CT-271-LT-2026 - 12ª Medição (07_2026) - IC 082_2025`) é a chave oficial do rastreio.

## 1. Objetivo

Sistema web interno para a Lotufo Engenharia gerenciar contratos de obras públicas e seus ciclos de medição, do cronograma previsto ao recebimento, substituindo controles manuais em planilhas, e-mails e fluxos frágeis de Power Automate. Usuários: engenharia (opera) e diretoria (acompanha).

Funcionalidades centrais:

1. Acompanhamento físico-financeiro (previsto × realizado por obra e consolidado mensal).
2. Ciclo de medições com rastreio automático (Prevista → Protocolada → NF emitida → Recebida).
3. Acompanhamento de aditivos (Em andamento → Assinado, com detecção de assinatura).
4. Prazos (vigência e execução) e alerta antecipado de reajuste por data-base — 100% automáticos por calendário.
5. Geração de espelhos de notas fiscais + e-mail pronto para o faturamento.
6. Certidões: robô de emissão automática das federais (CND RFB/PGFN, CRF/FGTS, CNDT) por CNPJ para Lotufo + consórcios; estadual/municipal por upload; checklist "pronto para protocolar" + montagem do pacote. [revogado pela §15 em 2026-09-01: sem robô; upload manual de todas]
7. Geração de FRC + arquivamento automático das FRCs/NFS-e recebidas por e-mail.
8. Controle de faturamento mensal (previsto, medido, emitido, recebido).

**Fora do escopo (decisões explícitas):**
- "Medição em atraso" (alerta de protocolo fora do prazo) — datas registradas permitem reintroduzir depois.
- Cálculo automático do valor de reajuste por índice.
- Acesso externo à rede (túnel futuro possível).
- Entidade de empenho/exercício — exclusão declarada; medição tem campo "motivo de represamento".

**Backlog pós-v1:** aging de tramitação por órgão, projeção de caixa por mediana do órgão, alerta de exaustão de saldo/limite de aditamento, feed .ics.

## 2. Contexto descoberto (verificado, não suposto)

- **Espelho de NF**: docx montado pela engenharia por medição, enviado ao faturamento para conferência (cliente, contrato+CNO, período, valor por extenso, split MO×materiais, retenções INSS/ISSQN/IRRF, conta bancária).
- **FRC**: emitida pela controladoria de consórcios após as NFs; numeração sequencial por consórcio; medição e reajuste separadas; acompanha NFS-e de cada consorciada.
- **Protocolo**: pacote enviado por e-mail ao órgão com ofício e assunto padronizado; retorno assinado por e-mail. Execução e reajuste tramitam separados.
- **TOTVS RM**: SQL direto bloqueado (trava TOTVS); **API REST do `<servidor-rm>` sempre ligada** (verificado); caminho = API + Consultas SQL cadastradas. Leonardo tem login de usuário no RM.
- **Consórcios são coligadas no RM da Lotufo** (verificado em GCOLIGADA: Oriundi=12, Leblon=17, Integra BRT=18 etc.) — a sincronização enxerga os dois níveis de NF. Confirmação final no spike RM.
- Status "NF paga" depende da baixa no RM — confirmar no spike, junto com parciais/estornos e campos para casamento.

## 3. Decisões de arquitetura

| # | Decisão | Implicação |
|---|---------|------------|
| 1 | Escopo completo numa única spec | Implementação faseada (§12) |
| 2 | **Rastreio por observação** (Outlook + SharePoint + RM) com fila única de sugestões | Digitação estrutural apenas no delta de aditivo; confirmações de 1 clique; alta confiança auto-aplica com desfazer |
| 3 | Hospedagem no `<servidor>`, rede interna | Sem nuvem; diretoria acessa pela rede |
| 4 | RM via API REST + Consultas SQL cadastradas | Spike antecipado prova o conduto (fase 0) |
| 5 | Recebimento por valor (baixas 1:N, parciais, estornos), origem `rm|manual` | "Paga" derivado do saldo |
| 6 | Microsoft (SharePoint **e Outlook**) via acesso delegado da conta do Leonardo | Uma permissão só; re-login ocasional; alerta ativo de falha; backup independente do token |
| 7 | Dashboard gera espelho e FRC | Regras migradas com inventário prévio (fase 0) + paridade estratificada + sombra |
| 8 | Certidões: **robô de emissão** das federais por CNPJ + cadastro extensível de tipos com jurisdição [revogado pela §15 em 2026-09-01: sem robô; upload manual de todas] | Estadual/municipal por upload; vigente por entidade+tipo+jurisdição; estados incluem revogada e "não se aplica" |
| 9 | Reajuste: alerta antecipado + acompanhamento; série própria nos painéis | Sem cálculo de índice |
| 10 | Login individual, permissões agrupadas em perfis (Engenharia, Diretoria, Administrador) + log de auditoria e uso | Config fiscal/participações/anulações só Administrador |
| 11 | Python (FastAPI) + React + SQLite endurecido, serviço Windows com workers separados | Web, sincronizadores e geração de docs em processos distintos |
| 12 | Carimbo discreto de frescor nas telas com dado importado | Sem banners; falhas detalhadas só na administração + e-mail ao administrador |
| 13 | PDF via docxtpl/openpyxl + LibreOffice headless | Word/Excel COM fora do serviço; utilitário manual de contingência |
| 14 | Consolidado da diretoria por participação Lotufo em consórcios | Valor cheio na página da obra; nunca somar bases distintas |
| 15 | Dinheiro em centavos/decimal, arredondamento único, resíduo de rateio por regra explícita | TDD |

## 4. Arquitetura

Um produto, um deploy, processos separados:

1. **Aplicação web (FastAPI)** — React, HTTPS interno, sessões seguras (cookies HttpOnly/Secure/SameSite, CSRF, lockout, expiração).
2. **Workers** — sincronizadores e geração de documentos em processos próprios (timeout, kill, retry, log `queued→running→success/failed`). Falha de worker nunca derruba o web.
3. **SQLite endurecido** — WAL, busy_timeout, FKs, escrita serializada; ACL NTFS restrita.
4. **Backup** — snapshot local por hora (API de backup do SQLite/`VACUUM INTO`) em destino independente do token; envio diário ao SharePoint com checksum; retenção; **teste de restauração periódico**; falha → e-mail.

**Sincronizadores (workers):**

- **RM** (horário): Consultas SQL via API; NFs (ID externo estável, coligada, situação fiscal, nível órgão↔consórcio / consorciada↔consórcio) e baixas (valor, data, estorno) por upsert idempotente; cancelamento/substituição descasa automaticamente; casamento automático só com chave forte (nº da medição em campo padronizado da NF — prática a instituir) ou candidato único exato com tolerância; resto → fila.
- **SharePoint** (Graph, token delegado): documentos das pastas vinculadas (links); **detecção de planilha nova de medição/cronograma** → leitura dos campos (nº, período, valor) → sugestão de 1 clique; detecção de termo aditivo assinado → sugestão.
- **Outlook** (Graph, mesmo token): lê **apenas** e-mails que casam com os padrões de assunto/remetentes do processo (protocolos ao órgão, retornos assinados, espelhos ao faturamento, FRCs da controladoria) — nada além disso é processado. Detecta: **protocolo de medição** (data do e-mail = data do protocolo; nº do ofício/processo extraídos do assunto/corpo), retorno assinado, envio de espelho, chegada de FRC/NFS-e (arquiva vinculando à medição).
- **Robô de certidões** (semanal): emite CND Federal (RFB/PGFN), CRF/FGTS (Caixa) e CNDT (TST) pelos CNPJs de Lotufo, consórcios e consorciadas nos serviços públicos correspondentes; salva PDF + validade; fallback: aviso para emissão manual se o serviço público falhar/mudar.

**Resiliência**: fontes fora do ar não afetam o uso com dados locais; carimbo de frescor visível; retentativas automáticas; falha persistente → log + e-mail ao administrador (+1).

## 5. Modelo de dados

> **MODELO CONGELADO em 2026-08-31** (aprovação do Leonardo, após conclusão da fase 0 e emenda das 4 lacunas fiscais). Mudanças daqui em diante só por emenda explícita com aprovação registrada — as fases de implementação constroem sobre esta versão.

Princípio mantido da v2: **o que muda no tempo é histórico versionado, não estado sobrescrito**; registros com efeito externo são congelados; correção por evento/revisão; sem exclusão física de registros financeiros (estados: cancelado, anulado, substituído, inativo). A v3 muda a **origem** dos eventos (detecção em vez de botão), não o armazenamento.

- **Obra/Projeto** (agrupador opcional) e **Contrato**: como na v2 — cliente/órgão, instrumento, valor original, data-base/índice, vigência, execução, processo, pasta SharePoint, consórcio opcional, estado (ativo|suspenso|encerrado|rescindido) com eventos de suspensão/retomada, flag preparada p/ caução. Vigente = original + deltas de aditivos assinados, em ordem de assinatura.
- **Regras fiscais versionadas** *(emendado após a fase 0 — evidências em `docs/superpowers/research/2026-08-inventario-power-automate.md`)*: tabela de retenções por vigência e **por natureza da nota** (execução | projeto | reajuste — a variação por tipo foi CONFIRMADA: projeto não tem INSS nem split MO/material, ISS incide sobre o total e IRRF tem alíquota própria — 4,8% no caso confirmado). Por tributo: base própria (fração do bruto: % MO, % material ou total), alíquota, **`deduz_do_liquido`** (MT-388 destaca ISSQN sem abater) e fundamento legal opcional para isenção (ex.: IN 2.110/2022 art. 114 II; LC municipal 5.177/2023). Conta bancária. Preset do kit atual.
  - **Política de arredondamento por parcela**: cada parcela do kit (MO, material, cada tributo, líquido) declara o método de leitura — `trunc2` (padrão) ou `round2`; o resíduo de um split fecha sempre na parcela-resto (material = bruto − MO). Regras preservadas POR OBRA, sem padronização (as exceções são realidade contratual); divergência deliberada do documento legado exige registro de aceite na vigência (precedente: MT-402, IRRF truncado ficando 1 centavo abaixo do espelho antigo). A paridade da fase 7 valida contra o **documento real emitido** (espelho/NF), centavo a centavo — nunca contra célula de precisão cheia.
  - **Eixos de desdobramento** (uma medição → N NFs), lista ordenada no kit da obra: natureza (execução×projeto×reajuste) → município (fator com método próprio, ex.: 61/81 estações TRUNC; km 0,8328 TRUNC 4 casas) → fonte de recurso (entradas manuais, ex.: SUDECO×FONTE 100, sem célula-soma) → consorciada (referencia o quadro de participações do consórcio — não duplica). Em cada eixo, **exatamente um item absorve o resto** do rateio; cada folha aponta para seu kit de retenções; **bloco zerado não emite NF**.
  - **Validação de sanidade pré-emissão** (pendência herdada da v2, agora requisito): MO + material fecham o bruto; retenções dentro de faixa plausível; líquido positivo; se falhar, o documento nasce marcado "CONFERIR" em vez de ser emitido. Documentos detectados casam por **valor**, nunca por nome de arquivo (rótulos de espelhos legados mentem número/mês).
- **Cronograma versionado**: passado congelado, futuro pela versão vigente, visão opcional do baseline; importado por detecção + aceite.
- **Medição** — estados visíveis: **Prevista → Protocolada → NF emitida → Recebida**. Campos: contrato; número; tipo (execução|projeto|reajuste); competência; **valor protocolado** (da planilha detectada/aceita) e **valor atestado** (editável quando diferir — glosa sem cerimônia de tela, histórico no log); protocolo (data + nº ofício/processo, detectados do Outlook; reapresentação = novo evento de protocolo detectado, sem apagar o anterior); "motivo de represamento"; documentos vinculados; estados de exceção (cancelada/desistida). Congela após marco externo. Cada dado carrega origem (`detectado|aceito|manual`).
- **Nota Fiscal**: ID externo RM, coligada, número/série, emissão, valor, tomador, **nível**, situação fiscal (ativa|cancelada|substituída) com vínculo substituta↔original, `last_seen_at`.
- **Alocação de faturamento (Medição↔NF, N:N)**: valor alocado, origem do casamento, confiança, histórico.
- **Recebimento/Baixa (1:N por NF)**: valor, data, estorno, origem. Recebido = soma das baixas não estornadas.
- **Aditivo** — estados visíveis: **Em andamento → Assinado**. Assinatura detectada (SharePoint/e-mail) → sugestão; ao confirmar, usuário informa o **delta** (valor com sinal e/ou novas datas) — única digitação estrutural do sistema; vigente recalculado.
- **Consórcio**: coligada RM, quadro de participações versionado — cada participação declara seu método de arredondamento (`round2`|`trunc2`) e **exatamente uma absorve o resto dos centavos** (precedentes: 49/49/2 fecha na Encomind; 50/50 fecha na Rivoli, que pode ficar 1 centavo menor — comportamento aceito, não bug) —, contador FRC (semeado na virada, com corte).
- **FRC**: nº sequencial (consumo atômico na confirmação; anulada preserva número), ancorada em NF(s)/alocações, snapshot do quadro, valores por consorciada **somados das NFs realmente emitidas — nunca recalculados dos percentuais** — com travas de fechamento (retenções fecham com o total de cada NF; bruto − retenções = líquido; geração barrada se faltar consorciada ou município). FRCs recebidas por e-mail são arquivadas e vinculadas automaticamente.
- **Certidão**: entidade; tipo extensível com jurisdição/emissor; emissão/validade; PDF; origem (`robô|upload`); estado (vigente|vencida|revogada|não se aplica); histórico ("qual valia na data do protocolo X").
- **Sugestão** (fila única): tipo (medição detectada, protocolo detectado, aditivo assinado, NF ambígua, importação), payload proposto, confiança, evidência (link do e-mail/planilha), estado (pendente|aceita|corrigida|descartada), decisor, data.
- **Documento gerado**: versão imutável (data/hora, usuário, snapshot de parâmetros e regra, template, hash, status rascunho|final|substituído|anulado).
- **Usuário** e **Log de auditoria** (append-only, hash encadeado, cópia externa): como na v2.

## 6. Semântica dos indicadores (KPIs)

Como na v2: eixos temporais definidos (Previsto = competência do cronograma a preços-base; Medido = competência física pelo valor atestado, ou protocolado enquanto não atestada — marcado; Emitido = emissão da NF; Recebido = data/valor da baixa); reajuste como série própria; saldo = vigente − atestado (execução), reajustes em apartado, fórmula visível; consórcio pela participação Lotufo; carimbo de frescor em toda tela com dado importado.

## 7. Telas

1. **Painel geral (home Diretoria)**: consolidado mensal (§6), histórico/projeção, carteira, alertas.
2. **Painel da Engenharia (home Engenharia)**: **fila única de sugestões** (1 clique: aceitar/corrigir/descartar, com evidência anexa); avisos urgentes (certidões, data-base, prazos); processos aguardando resposta do órgão (dias parados); pendências.
3. **Página da obra/contrato**: resumo, curva, estado; abas medições, aditivos, NFs, documentos, config fiscal, consórcio. Linha do tempo de cada medição montada pelas detecções.
4. **Medição**: os 4 estados com origem de cada dado; checklist "pronto para protocolar"; "montar pacote de protocolo" (merge/zip); botão "enviar espelho ao faturamento" (rascunho de e-mail pronto no Outlook — usuário só envia).
5. **Aditivos**: em andamento / assinados; confirmação de assinatura com delta.
6. **Certidões**: tabela entidade × tipo × jurisdição, semáforo, origem robô/upload, download. [revogado pela §15 em 2026-09-01 na parte do robô: origem `robo` fica no schema como histórico, mas nada a grava]
7. **Consórcios**: participações (versões), FRCs geradas e recebidas.
8. **Administração**: usuários/permissões; auditoria e uso; saúde de sincronizações, robô e backups; **reconciliação RM × dashboard**; padrões de detecção (assuntos, remetentes, pastas); configurações; runbook. [revogado pela §15 em 2026-09-01 na parte do robô: não há robô cuja saúde monitorar]
- Toda listagem exporta CSV/Excel.

## 8. Geração de documentos

Como na v2: espelho (docxtpl + LibreOffice headless, versão imutável, regra vigente da competência com snapshot; bloqueio se config incompleta) e FRC (número atômico, rateio com snapshot, openpyxl + PDF). Acrescido: e-mail do espelho pré-pronto via Graph (rascunho na conta do usuário; envio é humano). Fidelidade de templates validada na paridade.

## 9. Migração das regras do Power Automate

Como na v2: fase 0 de inventário completo (tabela de decisão com origem por branch), configuração versionada, paridade estratificada (execução/reajuste/consórcio) + recálculo manual de um caso por regra, sombra de 1–2 ciclos, aposentadoria explícita por fase.

## 10. Segurança, erros e testes

Como na v2 (HTTPS interno, CSRF, lockout, argon2/bcrypt, permissões no servidor, ACL NTFS, DPAPI com runbook, log hash-encadeado, e-mail de falha, TDD das regras de cálculo, simuladores de integração, teste de restore). Acrescido: **escopo mínimo de leitura do Outlook** — o worker processa somente mensagens que casam com padrões cadastrados (assunto/remetente/pasta), configuráveis na administração; conteúdo fora dos padrões não é lido nem armazenado; testes de detecção com corpus real de e-mails históricos (precisão medida antes de ligar auto-aplicação).

## 11. Migração histórica e cutover (validar na fase 2)

Como na v2: contratos ativos completos via backfill assistido (agora acelerado pela detecção retroativa — o Outlook e o SharePoint guardam o histórico: protocolos e planilhas antigos podem ser detectados em lote); saldos reconciliados; contador FRC semeado; corte na fila de NFs; RPO ~1h.

## 12. Ordem de implementação

- **Fase 0 — Inventário e provas**: regras do Power Automate inventariadas; **spike RM** (usuário, 1 consulta fim a fim; baixa? parciais? campos de chave? NFs das coligadas-consórcio?); **spike de detecção**: rodar os padrões de assunto contra o histórico real do Outlook e medir precisão (base para calibrar auto-aplicação × sugestão). *Pré-condição para congelar modelo.*
- **Fase 1 — Fundação**: projeto, banco, login/perfis, auditoria, cadastro de contratos (estados, aditivos-delta).
- **Fase 2 — Medições + cronograma + painéis**: 4 estados, fila de sugestões (ainda alimentada por importação manual), previsto × realizado, painéis, alertas de calendário, export CSV.
- **Fase 3 — Certidões**: cadastro extensível + **robô das federais** + alertas + checklist de protocolo. [revogado pela §15 em 2026-09-01: sem robô; upload manual + leitura determinística do PDF (§15.2)]
- **Fase 4 — Aditivos**: fluxo de 2 estados com confirmação de delta; **delta extraído por IA do termo assinado** (§14), humano confirma.
- **Fase 5 — Integração RM**: sincronização idempotente, casamento, recebimentos, reconciliação, carimbo. **Sem IA** — a API é estruturada (§14.3).
- **Fase 6 — SharePoint + Outlook**: token delegado, pastas, **detecção pelo extrator híbrido** (gate determinístico → IA → validador → fila, §14) para planilhas e e-mails (medição, protocolo, aditivo, FRC, NF-ao-órgão), backfill histórico retroativo.
- **Fase 7 — Espelho de NF**: config fiscal versionada + paridade + sombra; pacote de protocolo; e-mail pré-pronto; **paridade lê o documento real via extrator com validador literal** (§14.4).
- **Fase 8 — Consórcios + FRC**: participações versionadas, geração + arquivamento automático + paridade + sombra.

## 13. Pendências externas

- Spike RM (fase 0) — dono: Leonardo, com login existente.
- Acesso aos fluxos do Power Automate (fase 0).
- Instituir com o faturamento o nº da medição em campo padronizado da NF no RM (chave forte).
- Manter disciplina do padrão de assunto nos e-mails de protocolo (chave da detecção) — comunicar à equipe.
- Login delegado da conta Microsoft (fase 6).
- Segundo destinatário dos alertas administrativos.
- Verificar existência de caução na carteira.

## 14. Emenda — Extrator híbrido com IA (2026-08-31)

Decisão do Leonardo (2026-08-31): usar IA para extrair as informações no lugar da digitação manual; modelo **híbrido** — regras determinísticas onde bastam, IA (API do Claude) só no ambíguo, com egress aceito conscientemente para esse resíduo. Fundamentação empírica: spike de extração no corpus real (`docs/superpowers/research/2026-08-spike-extracao-ia.md`) — 86 e-mails + 5 documentos, categoria 100%, campos ~100%, FRC de 13%→100%, **zero erros de dinheiro, zero alucinações**; custo de produção em unidades de reais/mês.

### 14.1 Pipeline do extrator (substitui "regex de detecção" onde a spec a citava)

Todo item observado (e-mail, planilha, PDF/docx) passa por 4 estágios:

1. **Gate determinístico** (grátis, sem egress): remetente + direção + prefixo de assunto + posição no thread — as regras v2 da fase 0. Decide só: *é candidato ou é ruído óbvio*. Ruído óbvio morre aqui; nada de IA em NF-e de fornecedor.
2. **Extração por IA** (Sonnet; assunto + corpo + nomes de anexos — e o documento, quando houver): devolve categoria + eventos (um por medição) + campos (nº, tipo, competência, ofício, contrato/IC, consórcio, nº FRC, valores) + confiança + **evidência verbatim por campo** + fonte do nº (assunto|corpo). Prompt fixo versionado com o dicionário de consórcios (Oriundi=12, Leblon=17, Integra BRT=18) e a instrução "campo ausente = null, nunca derivar/chutar".
3. **Validador de código** (determinístico, obrigatório): todo valor de dinheiro é re-localizado por busca literal no texto-fonte — valor não encontrado invalida o campo (vira null + rebaixa confiança); competência normalizada `MM/AAAA`; números re-validados contra as bordas já existentes (int64, faixas); aditivos ganham conferência aritmética (novo = anterior + delta).
4. **Fila de sugestões** (a da fase 2, sem migração): payload + confiança + evidência + origem `detectado`. Auto-aplicação conforme §14.2; o resto espera 1 clique.

### 14.2 Critérios de auto-aplicação (atualiza §0/§5)

Auto-aplica (com desfazer e carimbo `detectado`) somente quando TODAS: (a) gate e IA concordam na categoria; (b) campos exigidos completos; (c) confiança ≥ limiar da categoria (calibrado no backfill da fase 6); (d) validador passou; (e) **sem divergência assunto×corpo**. Regra nova, descoberta no spike (3 casos reais de assunto reaproveitado mentindo o nº): **quando assunto e corpo divergem, o corpo vence e a sugestão NUNCA auto-aplica** — vai à fila com a divergência apontada na evidência. FRC continua nunca-auto-aplicar (vínculo por thread + corpo).

### 14.3 Onde IA NÃO entra

RM/API (dados estruturados — fase 5 permanece 100% determinística); aritmética de dinheiro (IA aponta, código calcula e valida); máquina de estados e auditoria (IA propõe via fila, mecanismos existentes aplicam); geração de documentos da fase 7 (templates determinísticos — IA só na LEITURA de paridade, com validador literal).

### 14.4 Mudanças por fase

- **Fase 3 (certidões)**: no upload estadual/municipal, IA extrai validade/nº/órgão do PDF como sugestão de metadados (humano confirma no mesmo formulário).
- **Fase 4 (aditivos)**: "digitar apenas o delta" vira "**conferir o delta extraído**" — IA lê o termo assinado (PDF), extrai delta/novo valor/prazos com evidência; validador exige conferência aritmética; humano confirma. Data citada de vigência já existente nunca vira data nova (armadilha provada no spike).
- **Fase 6 (Outlook + SharePoint)**: o motor de detecção é o pipeline §14.1. As regex v2 da fase 0 permanecem como o estágio-gate. Backfill retroativo roda o mesmo pipeline com auto-aplicação DESLIGADA (tudo vira sugestão) até o limiar ser calibrado contra o histórico. **Ganho novo**: cadastro de contrato semeado por IA a partir do instrumento PDF (órgão, nº, objeto, valor, prazos, processo — provado no spike), sempre como sugestão.
- **Fase 7 (espelho)**: a paridade contra o documento real emitido (§5) usa o extrator para LER o documento, com o validador literal centavo a centavo.

### 14.5 Custo, permissão e operação

Chamadas de IA rodam nos workers com chave da aplicação; **disparo manual de extração pela dashboard é exclusivo do perfil admin** (regra do Leonardo — toda ação com custo externo é admin-only). Log de custo por chamada (tokens, modelo) na administração. Falha da API de IA não trava nada: item fica pendente de extração com carimbo, gate determinístico continua triando (§ princípio 5 — falha silenciosa proibida, alarde também).

### 14.6 Pendências externas (atualiza §13)

A disciplina de padrão de assunto (§13) deixa de ser *chave* da detecção e vira *otimização do gate* — continua desejável, mas o corpo é a autoridade. Nova pendência: chave da API do Claude para os workers (dono: Leonardo; admin-only).

> **§14 REVOGADA em 2026-09-01 pela §15.** O texto acima fica como registro histórico da decisão e do spike; nada dele vale para as fases 4–7.

## 15. Emenda — Produto sem custo de API (2026-09-01)

Decisão do Leonardo (2026-09-01, após o parecer crítico da mesma data): **nenhum custo recorrente de API no produto.** Revoga a §14 (extrator híbrido com IA via API do Claude) e a parte "robô de emissão" da decisão 8 do §3. A regra "ação com custo externo é admin-only" (§14.5) perde objeto: não existe mais ação com custo externo.

### 15.1 Regra

- O produto não chama nenhum serviço pago por uso. Serviços que a empresa já paga (Microsoft 365 — SharePoint, Outlook, Graph; TOTVS RM) não são custo novo e seguem no roteiro.
- IA só voltaria ao produto se for **local e gratuita** (modelo rodando na própria rede), por decisão futura explícita. Não está no roteiro; nenhuma fase depende dela.
- Tudo que a §14 entregava por IA passa a ser entregue por **regra determinística + fila humana**. O que a regra não alcança vira sugestão "para classificar", nunca dado.

### 15.2 Certidões (fase 3)

- **Robô de emissão das federais: descartado.** RFB/PGFN, Caixa e TST exigem sessão interativa com captcha; sem API paga não há caminho honesto (o projeto anterior chegou à mesma conclusão em 2026-08). Módulo, agendamento e testes saem do código. O valor `robo` continua aceito em `certidoes.origem` para não reescrever a tabela e para preservar histórico eventual.
- Fluxo vigente: **upload manual** de todas as certidões + semáforo + checklist "pronto para protocolar" + alertas derivados do estado do banco. Par entidade×tipo sem certidão é vermelho ("nunca enviada" fica implícito no vermelho sem histórico).
- **"Preencher a partir do PDF"** (substitui "Preencher com IA"): leitura determinística com pypdf + expressões regulares. Layouts fixos das federais — CND RFB/PGFN ("Emitida às … do dia DD/MM/AAAA", "Válida até DD/MM/AAAA", "Código de controle da certidão"), CRF/FGTS ("Validade: DD/MM/AAAA a DD/MM/AAAA", "Certificação Número"), CNDT ("Expedição: DD/MM/AAAA", "Validade: DD/MM/AAAA", "Certidão nº") — e padrão genérico por palavras-chave (validade/válida até/vencimento; emissão/emitida em/expedição; nº/certidão nº/código; CNPJ) para estadual e municipal. Devolve emissão, validade, número, CNPJ e tipo sugerido, **cada campo com o trecho literal de onde saiu**; validador determinístico mantido (CNPJ com DV, validade > emissão, datas reais, divergência com a entidade escolhida → aviso). Campo duvidoso volta `null` com aviso pt-BR. **Nunca grava** — preenche o formulário para a pessoa confirmar. Disponível a `editar_cadastros`; sem custo, sem log de custo.
- Removidos: módulo `ia_extracao`, rota `POST /api/certidoes/extrair` (substituída por `POST /api/certidoes/ler-pdf`), rota `GET /api/ia/chamadas`, tabela `ia_chamadas` (migração 010 a remove), dependência `anthropic`, variável `DASH_ANTHROPIC_KEY`, bloco "Uso de IA" da administração.

### 15.3 Fases 4–7 sem IA

- **Fase 4 (aditivos)**: o delta é **digitado e conferido aritmeticamente** (novo = anterior + delta; datas novas posteriores às vigentes). Leitura determinística de valores do termo em PDF só quando o layout permitir, sempre como sugestão. Ganha campo de **ressalva de reajuste** na confirmação.
- **Fase 5 (RM)**: inalterada — já era 100% determinística. Antes de desenhar "recebido", confirmar em consulta própria qual lado do razão a `FLAN` devolve (`PAGREC`).
- **Fase 6 (Outlook + SharePoint)**: o motor é o **extrator determinístico** — gate (remetente + direção + prefixo de assunto + posição no thread) → regex v2 do spike da fase 0 (`docs/superpowers/research/2026-08-spike-deteccao-outlook.md` §2) → normalizações → fila. Espelho auto-aplica com regra completa (gate + nº + competência + remetente interno); protocolo auto-aplica com ofício + nº + competência; **FRC sempre sugerir** (remetente da controladoria + "FRC" no corpo, vínculo por `conversationId`); e-mail que passa o gate e não casa regex completa vira sugestão "para classificar" com assunto, remetente e link. **Divergência assunto × corpo**: quando o corpo contém "Nª medição" diferente do assunto, a sugestão nunca auto-aplica. Planilhas do SharePoint: leitura estruturada por `openpyxl` (células conhecidas por obra, cadastradas na administração), **incluindo itens do boletim quando o layout permitir** (ver §15.4). Backfill retroativo: tudo vira sugestão. A semeadura de contrato a partir do instrumento em PDF (ganho novo da §14.4) sai do roteiro.
- **Fase 7 (espelho)**: paridade lê o documento real por regra (`python-docx`/`openpyxl`, campos por posição), centavo a centavo.

### 15.4 Decisões do parecer de 2026-09-01 incorporadas

- **Custo e margem por obra**: backlog pós-v1. **Nada visível na dashboard** até decisão futura; o cadastro pode guardar centro de custo do RM quando a fase 5 precisar, sem tela.
- **Itens de medição e medição de ajuste com valor negativo**: exigência da fase 6, desenhada sobre boletins reais; entra como emenda ao §5 naquela fase (hoje o `CHECK` proíbe negativo e não há itens).
- **Caixa compartilhada de protocolos** (ex.: uma caixa de medições no domínio da empresa) como canal canônico da fase 6, com cópia obrigatória em todo protocolo e espelho; **segundo administrador** do sistema. Aprovados em 2026-09-01.
- **Runbook de uma página** em `docs/runbook.md`: subir e derrubar, onde ficam banco, backups, PDFs e logs, como restaurar, certificado, contas.
- **Alerta de reajuste com antecedência** (padrão 60 dias antes do aniversário da data-base) e alerta "execução protocolada após a data-base sem reajuste par": entram no polimento da fase 3/4.

### 15.5 Pendências externas (atualiza §13 e §14.6)

- Criar a caixa compartilhada de protocolos (TI) e instituir a cópia obrigatória — dono: Leonardo.
- Nomear e criar o segundo administrador pela tela de Administração — dono: Leonardo.
- Credencial de envio de e-mail (SMTP do Exchange ou Graph) para o resumo diário de alertas — dono: Leonardo.
- **Retirada**: chave da API do Claude. Mantida: instituir `CAMPOLIVRE1` com IC/contrato + nº da medição nas NFs do RM.
