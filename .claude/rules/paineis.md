---
paths:
  - "backend/app/inicio.py"
  - "backend/app/diretoria.py"
  - "backend/app/fechamento.py"
  - "backend/app/resumo_medicoes.py"
  - "backend/app/paineis.py"
  - "backend/app/avisos*.py"
  - "backend/app/custo_obra.py"
  - "backend/app/api_inicio.py"
  - "backend/app/api_diretoria.py"
  - "backend/app/api_paineis.py"
  - "backend/app/api_contratos.py"
  - "backend/app/fila_medicoes.py"
  - "backend/app/a_receber.py"
  - "frontend/src/Inicio.tsx"
  - "frontend/src/ObrasCarteira.tsx"
  - "frontend/src/Contratos.tsx"
  - "frontend/src/ContratantePagina.tsx"
  - "frontend/src/ObrasContratantes.tsx"
  - "frontend/src/ObrasAndamento.tsx"
  - "frontend/src/ObrasPecas.tsx"
  - "frontend/src/listaObras.ts"
  - "frontend/src/Fechamento.tsx"
  - "frontend/src/AReceber.tsx"
  - "frontend/src/ResumoDasMedicoes.tsx"
  - "frontend/src/AvisosPagina.tsx"
  - "frontend/src/avisos.ts"
---

# Painéis, avisos e números para a diretoria

Os nomes das etapas e dos valores são os do `GLOSSARY.md`.

- **Só aparece o que tem lastro.** Número antigo ou sem prova (data do evento, documento) fica fora do painel. A
  idade de uma etapa conta da data do evento (envio, protocolo, emissão), nunca da competência.
- **Tudo na cota** nas telas da diretoria; o valor cheio aparece ao abrir a obra.
- **Aviso com data vai para a agenda; pendência sem data aparece onde se resolve** e na lista do administrador
  (`docs/adr/0008`).
- **Prazo do órgão:** uma conta só, a de `docs/adr/0007`.
- **Tempo parado tem uma leitura só.** "Com quem está" e "parada há" de uma medição saem de `fila_medicoes` (o passo
  da vez diz com quem está; os dias úteis contam do evento que abriu o passo; no Pagamento, crítico só depois do
  prazo do órgão). Tela nova que mostre tempo parado usa essa leitura, para a mesma medição não ter dois tons.
- **Contagem que resume uma tabela nasce no servidor, junto com a leitura que pinta a linha.** A tela não repete
  limite (dias, percentual): recebe a situação pronta e os limites para escrever o rótulo.
- **Leitura que aparece em duas telas nasce numa função só do servidor**, e as rotas a devolvem igual, com um teste
  que pede as duas rotas para a mesma obra e compara. Motivo: o corte do andamento morava na tela, e a lista de
  Obras escrevia "Devagar" onde a página da obra calava a situação (#822).
- **Régua que não vale para um caso diz o motivo no lugar da leitura**, em tinta, sem tom de valor nem de situação
  ("Prazo no fim", "Sem medição desde 07/2026"). O aviso do mesmo fato continua nos Avisos.
- **Recorte ou abertura de um total soma as mesmas linhas do total.** Um número que já existe (o total do ano no
  Fechamento, a faixa do ciclo na Início) ganha outro recorte (por contratante, por obra, por etapa) somando as
  MESMAS linhas que somam o total, pela mesma função de seleção (no Fechamento, no mesmo laço), nunca por uma
  consulta própria. O teste soma as partes e compara com o total em toda coluna (`test_fechamento._confere_soma`; na
  Início, `test_api_diretoria.test_inicio_por_contratante_e_medido_fecham_com_as_outras_telas`). Motivo: consórcio, nota partilhada e nota paga em
  parte já foram resolvidos na linha da medição; uma segunda conta chegaria a outro centavo.
- **Lista nota a nota reaproveita as linhas do total.** A página que abre um total linha a linha lê as linhas da
  mesma função que monta o total (`fechamento._em_aberto_da_medicao`), e o teste compara as duas respostas: o total,
  o subtotal de cada recorte e cada linha.
- **Participação fecha em 100%.** Percentual de cada parte num total sai de `dinheiro.ratear_proporcional` (só
  inteiros, o resíduo nos maiores restos), em milésimos, e a tela só formata. Sem total positivo, ou com parte
  negativa, não há participação (nulo, e a tela não mostra nada).
- **Em aberto e a receber são dois números, com dois rótulos.** O "em aberto" (Fechamento e página Em aberto) soma,
  pela competência e pelo valor bruto da nota, a nota protocolada não paga, o repasse sem baixa e a medição
  protocolada sem nota; o "a receber" (Início, lista de Obras) soma a medição que espera o pagamento pelo valor dela e
  as cobranças do RM sem medição em aberto, pelos títulos. A conta que os liga está no `docs/adr/0006`. Tela que
  mostra um dos dois usa o rótulo dele.
- **Variação de etapa compara o acumulado, na mesma altura.** A variação do protocolado e do recebido de uma
  competência compara tudo o que a competência já protocolou (ou já recebeu) até hoje, tenha ou não seguido adiante
  depois, com o que a competência anterior já tinha protocolado (ou recebido) até o mesmo dia, um mês antes, pelas
  datas dos eventos (`resumo_medicoes._protocolado_ate`, `_mesma_altura`). Nunca o que está parado na etapa: esse
  número cai quando o órgão paga mais rápido. No recebido, que encerra o ciclo, o valor da etapa já é o acumulado.
  O evento seguinte prova o anterior até a data dele: a medição recebida sem protocolo registrado já estava
  protocolada no dia do recebimento. Onde a variação compara o acumulado e o valor ao lado mostra o que está na
  etapa, o acumulado vai escrito na linha da variação ("acumulado R$ …"). Na referência, a medição que não dá para
  situar no dia de corte (sem data nenhuma, ou só com data posterior) apaga a variação; até hoje, o estado basta.
- **Custo** é "custo lançado no RM"; margem e lucro ficam fora (`docs/adr/0004`).
- **O backend calcula o que alguma tela mostra.** Número sem tela sai junto com a tela.
- **A apresentação é do sistema:** tela que substitui um controle manual da equipe parte do dado do sistema e da
  pergunta de quem lê, não do arquivo da pessoa.
- **Correção de dado feita pelo dono é silenciosa na tela:** o número sai certo, sem selo nem aviso; o registro
  fica na auditoria.
