# Inventário das regras do Power Automate (e de onde as regras realmente moram)

**Task 4 da Fase 0** · Executado em 2026-08-31 com o dono (conta dele no make.powerautomate.com; definições exportadas em pacote .zip e lidas do `definition.json`; regras extraídas do Office Script `Motor Multi.osts` e do `cadastro-obras.json` no OneDrive corporativo).

## 1. Descoberta central (muda o desenho das fases 7–8)

**As regras fiscais NÃO estão no Power Automate.** Os fluxos são orquestração fina. A cadeia real:

```
cliente (espelho.js / chamada HTTP)
  → fluxo "Espelho Multi" (HTTP: obraId, inputsJson, medicao, periodo)
    → Office Script "Motor Multi" sobre a PLANILHA-MOTOR da obra
      (/Gestao Financeira e Contratos/Automacao Medicao/motor/planilhas/{obraId}.xlsm)
      — injeta inputs → recalcula → lê células de saída (valor, MO, material, INSS, ISS, IRRF, líquido)
    → popula modelos Word por obra (/Automacao Medicao/modelos/{obraId}/*.docx)
  → fluxo "FRC PDF" (xlsx em base64 → OneDrive → ConvertFile PDF → devolve base64)
robo-nf (Node local) → API RM localhost:<porta-da-api> (sistema T) + fluxos "SP Proxy Dados"/"SP Gravar Item"
  (ponte p/ lista SharePoint do Depto. de Engenharia; de-para centro de custo RM → item, robo-nf/depara-cc.json)
```

- **A planilha .xlsm de cada obra é a fonte da verdade e o motor de cálculo** (princípio declarado no `_meta` do cadastro). O script só lê e formata; **nunca recalcula tributo**.
- `cadastro-obras.json` (145 KB, 18 obras) documenta célula a célula cada planilha — fórmulas, alíquotas, bases, arredondamento — verificado contra os espelhos reais. O `Motor Multi.osts` (const CADASTRO) é a fiação operacional gerada dele.
- A numeração/geração da FRC **não** está no Power Automate: o fluxo FRC PDF apenas converte um xlsx pronto em PDF. O rateio de consórcio está nas planilhas-motor (participações) e o envio da FRC é da controladoria.

## 2. Inventário dos 8 fluxos

| Fluxo | Estado | Gatilho | Função | Conexões |
|---|---|---|---|---|
| **Espelho Multi** | Ativo, saudável (~15–20s) | HTTP (obraId, inputsJson, medicao, periodo) | Orquestra o motor: Run Script na planilha da obra → 1 espelho Word por nota → responde array base64 | Excel Online, Word Online, OneDrive |
| **Espelho MT-402** | **Desativado** (protótipo) | HTTP (valorMedicao) | Versão mono-obra do mesmo padrão (MT-402-TESTE.xlsm → MODELO-ESPELHO-MT402.docx) | Excel, Word, OneDrive |
| **FRC PDF** | Ativo, **falhando às vezes** (aviso de 5 falhas em 2026-08-10) | HTTP (nome, conteudo base64) | xlsx → OneDrive raiz → ConvertFile PDF → responde base64 → apaga o arquivo | OneDrive |
| **SP Proxy Dados** | Ativo, **falhando às vezes** (14 falhas idem) | HTTP (path) | Proxy GET genérico da REST do SharePoint (site DepartamentodeEngenharia) | SharePoint |
| **SP Gravar Item** | Ativo | HTTP (path, body, method) | Proxy POST/MERGE genérico da mesma REST (IF-MATCH: *) | SharePoint |
| **Certidão Alerta** | Ativo | Agendado | Lê lista de certidões no SharePoint e envia e-mail de alerta de vencimento | SharePoint, Outlook |
| **Certidão Arquivo** | Ativo | HTTP (arquivo) | Devolve o conteúdo de um arquivo de certidão | SharePoint |
| **Certidão Gravar** | Ativo | HTTP (empresa, …) | Grava PDF em `/Certidoes/{empresa}` + item na lista | SharePoint |

Nenhum fluxo contém percentual, alíquota ou condicional fiscal. Todos os gatilhos HTTP com `triggerAuthenticationType: All`.

## 3. Tabela de decisão das regras fiscais (por obra — extraída de cadastro-obras.json, célula a célula)

Convenções: salvo nota, **split MO 40% = TRUNC(bruto×0,4;2)** e material = bruto − MO (fecha o resíduo); **INSS 11% sobre MO**; **ISSQN 5% sobre MO**; **IRRF sobre o total**; **líquido = bruto − INSS − ISS − IRRF** (deduz ISS); 2 NFs por medição (execução + reajuste, abas gêmeas). "cru" = fórmula sem ROUND/TRUNC (arredonda só na exibição do espelho).

| Escopo (obra) | Órgão | Desvios do padrão acima | Tributos (arredond.) | NFs/medição | Origem |
|---|---|---|---|---|---|
| MTPAR-COMPLEXO-CULTURAL | MT-PAR | **IRRF 1,5%** | INSS/ISS/IRRF ROUND | 2 | COMPLEXO CULTURAL.xlsm, MEDIÇÃO/REAJUSTE C5–C14 |
| MTPAR-ESPACO-SHOW | MT-PAR | **IRRF 1,5%**; alíquotas em células B10/B11/B12 | ROUND | 2 | ESPAÇO SHOW OPERADORA.xlsm |
| MTPAR-GRANITO | MT-PAR | **IRRF 1,5%**; reajuste nunca faturado (saída inativa) | ROUND | 1 | GRANITO MTPAR.xlsm |
| MTPAR-ORLA | MT-PAR | **IRRF 1,5%** | ROUND | 2 | ORLA MTPAR.xlsm |
| MTPAR-XTREME | MT-PAR | **IRRF 1,5%** | ROUND | 2 | XTREME MTPAR.xlsm |
| PREF-CBA-REGIAO-OESTE-L3 | Pref. Cuiabá/SEMOP | IRRF 1,2% | **TRUNC puro em tudo** | 2 | REGIÃO OESTE.xlsm |
| PMC-COXIPO2-CT392 | Pref. Cuiabá/SMOP | IRRF 1,2%; célula C21 p/ **agrupar 2 medições numa NF** | **inconsistente por versão**: 4ª/5ª ROUND; 2ª/3ª/reajuste cru | 2 | COXIPÓ.xlsm (CT 392) |
| PREF-COXIPO-RES3 | Pref. Cuiabá/SMOP | **2 fontes de recurso (SUDECO × FONTE 100)** = 2 NFs de medição c/ inputs manuais separados; IRRF 1,2% | medição ROUND; reajuste TRUNC na MO + impostos crus | 3 | COXIPÓ.xlsm (CT 248) |
| SES-ALTA-FLORESTA | SES-MT | **MO 60% / material 40% (invertido)**; **SEM INSS** (IN 2.110/2022 art. 114 II); ISS 5% s/ MO(60%); IRRF 1,2%; inputs somam reequilíbrio de ISSQN (F10+F11; C13+C14) | ISS/IRRF crus, espelho exibe **TRUNC** | 2 | ALTA FLORESTA.xlsx |
| SINFRA-5BAIRROS | SINFRA | IRRF 1,2% | MO/INSS/ISS TRUNC; **IRRF cru c/ ROUND na exibição** (motor: roundFields=[irrf]) | 2 | 5 BAIRROS.xlsm |
| SINFRA-ATALAIA (**Cons. Oriundi**) | SINFRA | 2 eixos de desdobramento: **município** (CBA=TRUNC(B4×0,5872), VG=resto) e **empresa** (LOTUFO 80% TRUNC, RIVOLI 20%=resto); IRRF 1,2% | rateios TRUNC; impostos crus | **8** | ORIUNDI .xlsm, colunas G/I linhas 5–27 |
| SINFRA-BRT (**Cons. Integra BRT**) | SINFRA | **município por km** (CBA=TRUNC(B4×0,8619), VG=resto) e **empresa** (Lotufo 49% ROUND, Guaxe 49% ROUND, Encomind 2%=resto); aba PROJETO separada (hoje zerada); IRRF 1,2% | split empresa ROUND; MO TRUNC; impostos crus | até **6** exec (+3 proj) | BRT.xlsm |
| SINFRA-CAVALARIA | SINFRA | IRRF 1,2% | impostos crus | 2 | CAVALARIA.xlsm |
| SINFRA-ESTACOES-BRT | SINFRA | **município por nº de estações** (CBA=TRUNC(B4×61/81), VG=resto); **tipo PROJETO com kit próprio: SEM INSS, SEM split, ISS 5% s/ TOTAL, IRRF 4,80% s/ TOTAL** | EXEC: TRUNC em tudo; PROJ: ROUND/cru (métodos divergem entre abas) | 6 | ESTAÇÕES BRT 3A MEDIÇÃO.xlsm |
| SINFRA-LEBLON (**Cons. Leblon**) | SINFRA | **empresa 50/50** (Lotufo=ROUND(×0,5), Rivoli=resto — pode ficar 1 centavo menor); IRRF 1,2% | MO TRUNC; impostos crus | **4** | LEBLON.xlsm, colunas E/G |
| SINFRA-MT388 | SINFRA | **município por km** (fator TRUNC(36184/43444;4)=0,8328; Cáceres=ROUND, Porto=resto); **ISS de Cáceres incide sobre MATERIAL (60%)** e o de Porto sobre MO (40%); **líquido NÃO deduz ISS** (só INSS+IRRF); espelho lê **coluna D=TRUNC(C;2)**; IRRF 1,2% | coluna D TRUNC | **4** | MT388 10ª.xlsm |
| SINFRA-MT401 | SINFRA | IRRF 1,2% | impostos crus | 2 | MT-401 OPERADORA.xlsm |
| SINFRA-MT402 | SINFRA | IRRF 1,2% | MO TRUNC; impostos crus (IRRF ROUND na exibição — motor) | 2 | MT-402.xlsm |

Rateio de consórcio (insumo da fase 8/FRC): Integra BRT = Lotufo 49 / Guaxe 49 / Encomind 2; Leblon = Lotufo 50 / Rivoli 50; Oriundi (Atalaia) = Lotufo 80 / Rivoli 20 — com o **resto do centavo sempre para a última consorciada** (por diferença).

## 4. Regras que NÃO cabem no modelo da spec §5

O núcleo do modelo ("tabela de retenções por vigência: tributo, base própria, alíquota; variação por tipo de medição; quadro de participações versionado") **cobre** alíquotas, bases (como fração do bruto: MO 40%, MO 60%, material 60%, total) e a variação por tipo — que a fase 0 **confirma necessária** (execução × projeto no Estações BRT, com kits totalmente diferentes). Ficam de fora, e precisam entrar no modelo antes do congelamento:

1. **Política de arredondamento por parcela** — TRUNC × ROUND × cru varia por obra, por parcela e até por versão de planilha (COXIPO2). Sem representar isso (`metodo: trunc2|round2|cru` por parcela + quem absorve o resíduo), a paridade centavo a centavo da fase 7 (modo sombra) é impossível.
2. **Eixos de desdobramento pré-fiscais** que multiplicam NFs por medição: por município (fator km/estações com TRUNC/ROUND + "resto por diferença") e por fonte de recurso (inputs manuais SUDECO×FONTE100). A spec prevê o N:N medição↔NF, mas não a REGRA que gera os N — precisa de entidade "eixo de desdobramento" (fator ou manual, método de arredondamento, ordem).
3. **Tributo destacado mas não deduzido do líquido** — MT388 destaca ISSQN no espelho sem abatê-lo do líquido. Falta um flag por tributo (`deduz_do_liquido: bool`).
4. **Método de fechamento de centavos no quadro de participações** — 50/50 do Leblon dá diferença de 1 centavo com regra fixa ("Rivoli pega o resto"); 49/49/2 do BRT fecha na Encomind. O quadro versionado precisa registrar o método, não só os percentuais.

Menores, para registrar: base do ISS pode variar POR MUNICÍPIO dentro da mesma obra (MT388); INSS isento por fundamento legal (IN 2.110/2022) merece campo de fundamento; agrupamento de 2 medições numa NF e parcela de reequilíbrio somada ao valor (SES) são compostos de valor que a alocação N:N registra, com origem manual.

## 5. Implicações práticas para as fases 7–8

- A fase 7 pode **importar as regras direto do `cadastro-obras.json`** (máquina-legível, 18 obras, sincronizado com o motor em 2026-07-04) em vez de redigitar — e validar em modo sombra contra os espelhos .docx reais de cada obra.
- O padrão-ouro de paridade são as PLANILHAS (elas continuam sendo o motor em produção); qualquer divergência da dashboard deve ser comparada contra a célula, não contra o PDF.
- FRC: numeração e emissão não estão automatizadas hoje (fluxo só converte PDF) — a dashboard não substitui um robô existente aqui, ela cria o primeiro.
- Fragilidades atuais que a dashboard herda/conserta: fluxos SP Proxy/FRC PDF falhando de forma intermitente; espelho MT-402 desativado; dependência da macro `VExtensoFree` externa (#VALUE! fora do ambiente); planilhas com valores desatualizados deixados para trás (COXIPO2 9ª).

## Anexos

- Pacotes exportados (definition.json de cada fluxo): Downloads (`*-spike_*.zip`), extraídos no scratchpad da sessão.
- Fontes primárias no OneDrive corporativo: `Automacao Medicao/cadastro-obras.json` (+ backup 2026-07-04), `Documentos/Scripts do Office/Motor Multi.osts` e `Motor MT-402.osts`, `motor/planilhas/*.xlsm` (20 arquivos), `modelos/{obraId}/*.docx`, `robo-nf/config.exemplo.json` e `depara-cc.json`.
