# Licitações entram no produto; quem lê as fontes é o radar, de fora, e entrega a leitura

Até 24/11/2026 o produto era contrato e medição. O dono mantém, fora deste repositório, um radar de licitações: um
programa que lê o PNCP, um agregador e as páginas de órgãos e diários (18 fontes), junta os repetidos, classifica e
gera uma página local. O levantamento de 24/11/2026 mostrou que a página não virou hábito: nenhuma triagem feita por
ela, uso em quatro dias de outubro e sempre em leva, numa sessão de trabalho; as favoritas foram todas ligadas ao
dossiê da licitação, que é onde a etapa e os prazos de fato vivem; o aviso por e-mail nunca foi ligado; e a coleta só
roda com sessão aberta na máquina do escritório. A recomendação do levantamento era uma tela só de leitura, depois de
duas semanas de uso medido. O dono decidiu, em 24/11/2026, trazer o radar inteiro para a dashboard.

Decidimos duas coisas.

1. **Licitação passa a ser área do produto**: da publicação do edital ao resultado, o que vem antes do contrato. A
   dashboard é onde se tria, se favorita, se acompanha a etapa e os prazos e se vê o resultado.
2. **O `docs/adr/0003` continua valendo.** A dashboard não lê fonte nenhuma. O radar segue fora, na máquina onde já
   roda, lê, junta, classifica e entrega a leitura à dashboard por chave, no modelo do monitor do SIGA. A dashboard
   guarda, mostra e registra as decisões das pessoas.

## Opções consideradas

- **Tela só de leitura, depois de uso medido** (a recomendação do levantamento): menor, e deixaria a triagem na
  página que não foi usada. O dono preferiu um lugar só.
- **A coleta dentro da dashboard**: contraria o `0003`; a produção é uma máquina virtual compartilhada, com
  antivírus que intercepta conexão segura, e o robô do agregador precisa de navegador e de senha guardada.
- **Refazer na dashboard a classificação do radar** (tipo de obra, distância, nota das Recomendadas): seriam duas
  réguas para o mesmo certame, e a do radar é a que tem as provas e os testes.

## Consequências

- **O radar manda só o que alguma tela mostra, e só o que mudou.** A base dele tem cerca de 19 mil certames; as
  telas usam cerca de 1,2 mil (engenharia com sessão por vir, obras de grande vulto, favoritas e os pares em
  conferência). Cada certame vai com um resumo do conteúdo; o radar pergunta quais resumos a dashboard tem e manda
  só os diferentes, em pedidos abaixo do teto geral de 2 MB. Nada se apaga: o certame que sai das listas fica
  gravado, marcado com a data em que saiu.
- **A classificação chega pronta.** Tipo de obra, distância, esfera, nota e motivo das Recomendadas e o rótulo de
  cada mudança são do radar. A dashboard calcula só o que depende do dia (dias úteis até a sessão, sessão passada)
  e das decisões (favorita, descartada, conferida).
- **O que depende de pasta que a produção não tem chega como leitura.** A etapa e os prazos vindos do dossiê, os
  resultados das licitações em que a empresa participou e os pontos de acervo das Recomendadas são lidos pelo radar
  na máquina dele e mandados já resolvidos. A favorita com dossiê tem a etapa do dossiê, e a tela não a muda.
- **As decisões moram no banco da dashboard a partir do corte.** Antes do corte, favoritas, etapas, descartes e
  conferências são espelho do que o radar manda, e a tela não tem botão. O corte é um ato do administrador, um só,
  registrado: dali em diante a dashboard recusa decisão vinda do radar, e o radar busca as decisões da dashboard
  antes de cada leitura, para juntar os repetidos e para o e-mail dele. O último espelho antes do corte é a
  migração. De cada lado da data há um escritor só.
- **O e-mail de licitação continua saindo do radar.** A dashboard não envia e-mail de licitação e a regra de envio
  (`.claude/rules/envio.md`) não muda. Na dashboard o aviso é na tela.
- **A tela parte do uso que aconteceu, não da página antiga.** A entrada é a Triagem: as favoritas que mudaram ou
  têm prazo chegando e as Recomendadas ainda sem decisão, uma lista que esvazia quando se decide. A lista inteira das
  novas é consulta, com filtro. A conferência "é o mesmo / é outro" fica na página das fontes, fora da fila: pedir a
  uma pessoa que confirme palpite foi o que o `0003` tirou da primeira versão.
- **Dia sem leitura continua existindo.** O radar depende de sessão aberta na máquina do escritório. A dashboard diz
  desde quando ele não lê; não lê no lugar dele.
- **Dado real só no banco.** Favorita, etapa, valor de proposta e resultado não entram em arquivo versionado. O dado
  do certame é público, mas os testes usam certame inventado, com CNPJ fictício.
- **Ficam no radar**: a lista de fontes e o estado de cada uma, as regras de alerta, o envio do e-mail e as regras
  do projeto dele (custo zero, nenhuma fonte desligada, senha só no cofre da máquina). A análise do edital continua
  fora da dashboard.
- **Quem vê e quem decide** são duas permissões novas (`ver_licitacoes`, `editar_licitacoes`). Decisão do dono em
  24/11/2026: só o administrador tem as duas. Diretoria e engenharia não têm a área no menu e recebem 403 nas rotas.
