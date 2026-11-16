# Comparação: dashboard antiga × nova (2026-09-03)

Levantamento autorizado pelo dono em 2026-09-03. A antiga é `~/dev/lotufo-dashboard`
(site estático HTML/CSS/JS + Cloudflare Worker, ~9.500 linhas de JS, 9 páginas). A leitura
foi feita por 25 subagentes sobre o código real, mais conferência visual rodando a antiga
(`python -m http.server 4173` + `?mock=1`).

## O que cada uma é

A antiga é **analítica e de mercado**: lê uma planilha consolidada e mostra a carteira,
a saúde financeira e o que vale disputar. A nova é **operacional e transacional**: observa
Outlook, SharePoint e RM, e registra a história de cada medição com auditoria, congelamento
de valor e origem por dado. Uma responde "como está a empresa"; a outra, "o que precisa ser
feito hoje nesta medição".

Nenhuma substitui a outra inteira. A antiga tem análise que a nova não tem; a nova tem
rastro e integração que a antiga não tem.

## O achado que muda o plano de cadastro

Dentro do repositório antigo existe `backup-sharepoint-2026-08-04/`, com as listas do
SharePoint exportadas em JSON. **A dashboard antiga nunca leu esses arquivos** — eles são
backup do que o Power Automate alimentava. Conteúdo conferido:

| Arquivo | Registros | Serve para |
|---|---|---|
| `Cadastro de Obras.json` | 27 obras | contrato, órgão, valores, datas, e os 4 cadastros da detecção |
| `Cronograma-Previsto.json` | 6.845 linhas | bootstrap do cronograma, 25 baselines nomeadas |
| `Itens de Faturamento.json` | 973 notas | bruto × líquido, retenções, reconciliação RM |
| `Medicoes.json` | 405 medições | histórico com estado e procedência do backfill |
| `Saidas-Modelo.json` | 55 saídas | motor fiscal do espelho, célula a célula (fase 7) |
| `Custos-Mensais.json` | 421 linhas | custo por obra e mês |
| `Etapas-Realizado.json` | 311 linhas | físico realizado por etapa |
| `Certidoes.json` + PDFs | 63 | certidões com validade |

O `Cadastro de Obras` traz, por obra: `Contrato`, `Orgao`, `ValorPI`, `ValorAditivo`,
`ValorContratual`, `Inicio`, `Termino`, `VigenciaQDOP`, `ExecucaoCI`, `VigenciaCI`,
`BaseSINAPI`, `BaseSICRO`, `UltReajSINAPI`, `UltReajSICRO`, `Empreita`, `PercDireito`, e —
decisivo para a fase 6 — `GrafiasAlternativas` (os apelidos de contrato, ex.: `MT388 | MT-388
| MT - 388 | Porto Esperidião-Cáceres`), `PastaSPEngenharia` (o nome exato da pasta da obra),
`EmailFiscal` (canal do órgão), `EmailContabilidade` (faturamento) e `EmailCopia`.

Ou seja: **as pendências "cadastrar contratos", "cadastrar apelidos", "cadastrar canais do
órgão e faturamento" e "cadastrar a pasta de cada obra" já existem prontas em JSON.**

## Trazer para a nova, por ordem de valor

1. **Cadastro das 27 obras a partir do JSON** — contratos, apelidos, canais, pastas. Destrava
   a fase 6 e o bootstrap do histórico de uma vez.
2. **Motor fiscal do espelho (`Saidas-Modelo.json`)** — 55 saídas com aba, célula de input,
   modelo .docx, condição de emissão (`EmitirSe`, "bloco zerado não emite NF") e as células de
   valor, MO, material, INSS, ISS, IRRF, líquido e extenso. É o insumo direto da fase 7.
3. **Ciclo de reajuste completo** — data-base por índice (SINAPI e SICRO separados), último
   reajuste, próximo ciclo e prazo de ofício com 60 dias de antecedência, com farol de vencido,
   urgente e em dia. A nova só tem um alerta simples de aniversário de data-base.
4. **Cota de consórcio** — a antiga distingue valor cheio do contrato da cota da Lotufo em
   todos os indicadores. A nova soma valor cheio, o que infla a carteira.
5. **Alerta de exaustão de saldo contratual** e **% executado do contrato**.
6. **Radar de licitações (PNCP)** — feed nacional, classificador determinístico de "é obra?",
   régua de interesse por valor × distância de Cuiabá, município extraído do texto do edital,
   fila por urgência de decisão. Área inteira ausente na nova, e é prospecção de receita.
7. **Certidões**: perfis de leitura estadual e municipal, validade calculada da certidão de
   falência (TJMT, 30 dias úteis), datas por extenso, cura de ligadura no texto extraído,
   cadastro das 8 entidades com CNPJ, pacote ZIP por entidade, e a pasta `/Certidoes` do
   SharePoint como fonte detectada.
8. **UX**: busca e filtro nas listagens, confirmação de sucesso após ação, estado de
   carregamento, atalho de busca global, e KPI com delta e minigráfico.

## Deixar de fora, com motivo

- **EVM de custo (CPI, EAC, TCPI), margem por obra e waterfall de caixa** — dependem de custo
  por obra vindo do RM, que a nova não lê hoje; e a spec põe custo/margem em backlog pós-v1,
  sem tela, até decisão futura. O **SPI**, que é índice de prazo e não depende de custo, vale
  trazer.
- **Mapa de MT com anéis de distância** — bonito, mas a régua de distância entrega a decisão
  sem o mapa.
- **Modo escuro** — a decisão de marca da nova é modo único claro.
- **Google Sheets como fonte** — substituído por RM e Graph.
- **Habilitação técnica automatizada** — o próprio sistema antigo declara que nunca diz
  "atende"; o cruzamento exigência × acervo é trabalho humano. Traz-se o acervo catalogado,
  não o veredito.

## Correções que o dado real impõe

- **Retenção fiscal não é 5–6%.** Medida nas 317 notas conciliadas do `Itens de Faturamento`:
  mediana **7,60%**, com casos de 1,2% a 17,15% (dominante: ISS 5% + INSS 11% sobre MO 40% +
  IRRF 1,2% sobre o total). Qualquer tolerância de recebimento calibrada em 6% erra em mais da
  metade da carteira — afeta a trava `recebido >= alocado` da fase 5.
- **Três datas contratuais, não duas.** `VigenciaQDOP`, `ExecucaoCI` e `VigenciaCI` divergem
  entre si (na obra 181: execução 24/03/2027, vigência 06/06/2027). A nova acertou em separar
  execução de vigência, mas o histórico tem duas leituras para a mesma data.
- **Licença do RM.** Cada `RealizarConsultaSQL` consome um slot de licença; o robô antigo trata
  o fault "Excedeu numero de licenças" e nunca grava rodada parcial, com disciplina de uma
  chamada por rodada e nunca em paralelo. A nova sincroniza de hora em hora e não sabe disso.
  Existe também um conduto SOAP (`wsConsultaSQL`, coligada 1, sistema T) como plano B provado.
- **Custo mora no rateio**, não no cabeçalho: quando `CODCCUSTO` vem vazio, o caminho é
  `TITMMOV.CODCCUSTO` ou as tabelas de rateio `FLANRATCCU`/`TMOVRATEIOCCUSTO`. Existe um
  `depara-cc.json` com 19 centros de custo mapeados para obra e 20 marcados como não-obra.
- **Reforma tributária já está nas notas.** As NFS-e de 07/2026 trazem IBS 0,9% e CBS 0,1% da
  LC 214/2025, com chave da Nota Nacional. Nenhum motor fiscal (antigo ou novo) enxerga isso, e
  as alíquotas sobem por calendário legal.
- **CNO e ART da obra** só existem no corpo da NFS-e, e são obrigatórios na nota de serviço de
  construção. Precisam entrar no cadastro do contrato antes da fase 7.
- **Sete fluxos do Power Automate continuam vivos**, um deles disparando e-mail de alerta de
  certidão todo dia às 08:00. Desligar o sistema antigo é uma lista de sete automações, não
  apagar um site.

## Convenções do histórico que precisam viajar com o dado

- **Medição "em bloco"**: obra que entrou no controle no meio da vida tem o acumulado antigo
  lançado numa competência única (ex.: "1ª–41ª em bloco 04/2022").
- **Aditivo sem grade mensal**: o previsto costuma cobrir só o PI, então SPI calculado sobre
  PI+VA nasce distorcido.
- **Procedência do backfill**: a lista `Medicoes` registra, medição a medição, o que nunca foi
  conferido contra a ficha assinada ("extraída dos espelhos de NF — conferir"). Essa ressalva
  precisa entrar junto com o dado, senão o histórico chega na nova com cara de verdade auditada.
- **Estados antigos**: `Lançada · Encaminhada · Faturada`. "Encaminhada" é o protocolo antes de
  existir a palavra protocolo.
