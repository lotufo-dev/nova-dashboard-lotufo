# Medido da obra soma execução e projeto; o ritmo fica só com a execução

O medido da obra somava só as medições de execução. A obra com medição de projeto aparecia com medido zero e saldo
igual ao contrato inteiro, embora o faturado contasse o projeto. Em 16/11/2026 o dono decidiu (#670, #742): o
projeto faz parte do valor do contrato, então entra no medido e reduz o saldo a executar. Medido = execução +
projeto, nos estados que medem (a partir do envio da planilha/carta); reajuste continua em série própria, fora do
medido e do saldo; cancelada, desistida, prevista e planilha gerada não contam.

No mesmo dia, revendo a PR, o dono decidiu que o ritmo fica só com a execução: projeto pago não é obra andando. Uma
medição de projeto grande na janela aceleraria o ritmo e anteciparia uma conclusão que a obra não tem.

## Consequências

- Uma regra só para o medido (`paineis.mede_no_medido`, `paineis.TIPOS_NO_MEDIDO`) serve ao saldo da obra, ao topo
  da página da obra, à lista de Obras e aos totais por contratante, e à carteira e à tabela de obras da Diretoria.
- O ritmo (cartão "Ritmo e prazo", sugestão de dias da carta de prazo, ritmo e meses de produção da carteira) soma
  só a execução da janela. Ele divide o saldo a executar da obra, que já desconta o projeto medido: é o que falta.
  O contrato não registra quanto do valor é projeto, então o projeto ainda não medido fica nesse saldo e é dividido
  pelo ritmo da execução; se o cadastro passar a separar o valor do projeto, esta conta é reaberta.
- A curva S (a da obra, a da carteira e a que vai com a carta de prazo) e o desvio contra o cronograma continuam só
  com a execução: comparam o realizado com o cronograma, e o cronograma pode não trazer o projeto. Somar o projeto
  ali muda um documento que vai ao órgão; fica para decisão própria, se o cronograma das obras com projeto o
  incluir.
- O saldo da planilha/carta continua por série (o acumulado da própria série), porque é o número que vai ao órgão.
- O custo da obra (aba Custo) continua comparando o custo com o medido de execução, lido por grupo da planilha; o
  projeto não tem leitura por grupo.
