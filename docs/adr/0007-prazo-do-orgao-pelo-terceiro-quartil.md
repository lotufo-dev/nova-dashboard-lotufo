# O prazo de pagamento do órgão é o terceiro quartil

O sistema prevê quando o protocolado deve entrar e aponta o que está atrasado. Havia duas contas: a mediana com
cinco casos, na previsão, e o terceiro quartil com dez casos e trinta dias de padrão, em outra tela. Com a
mediana, metade dos pagamentos normais aparece como atrasada em algum momento, e o aviso perde a confiança.
Decidimos por uma conta só: o prazo do órgão é o terceiro quartil dos dias entre o protocolo e o recebimento,
com no mínimo cinco recebimentos em doze meses. Órgão sem casos suficientes fica "sem previsão": não há número
padrão, porque seria inventado.

## Consequências

- O caso contado é a medição recebida, não o pagamento: a execução e o reajuste pagos juntos contam dois casos, cada
  um com o seu protocolo. Decidido em 17/11/2026: o prazo é contado do protocolo de cada medição, e juntar as duas num
  caso só pediria saber que foram pagas no mesmo depósito, o que o sistema não lê.

- "Atrasado" quer dizer fora do normal daquele órgão, e a previsão de entrada fica conservadora.
- A medição recebida sem protocolo, na obra sem o passo "Envio da nota" (`docs/adr/0006`, #743), não entra na
  amostra: o prazo mede do protocolo ao pagamento, e misturar a emissão da nota como início encurtaria ou alongaria o
  prazo dos outros contratos do mesmo órgão. Enquanto espera, ela também não tem data esperada nem "Atrasado".
- A medição de consórcio cuja data do recebimento veio da baixa da nota da empresa (`docs/adr/0006`, #842) também não
  entra na amostra: essa data é a do repasse da cota, que soma a demora do consórcio ao prazo do órgão. Na cópia da
  produção de 20/11/2026, contá-las levaria o prazo da SINFRA de 27 para 39 dias. A medição que ganhou a data pela
  baixa de nota da coligada do contrato é caso como qualquer outra recebida pela baixa.
