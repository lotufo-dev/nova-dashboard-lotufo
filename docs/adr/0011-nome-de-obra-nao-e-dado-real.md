# Nome de obra e de órgão público não é dado real

A regra do repositório público contava nome de obra e fato de domínio com nome de obra como dado real, proibido
na árvore. A varredura de 16/11/2026 achou nome de obra em cerca de 1.100 linhas de 85 arquivos: código, quatro
migrações já aplicadas, testes e docs. O histórico do git já é público e migração aplicada não se reescreve, então
a regra era impossível de cumprir. E o nome da obra e do órgão de um contrato público já sai em Diário Oficial.
Decidimos (o dono, 16/11/2026) estreitar a regra: nome de obra e de órgão de contrato público deixa de ser dado
real. Continua proibido nome de pessoa, e-mail real, CNPJ, número de nota fiscal, valor real (de contrato,
medição ou nota), certidão, nome de máquina, porta e tarefa de produção, identificador de aplicativo e domínio do
Microsoft 365. O nome do dono também não se escreve: vale o papel.

## Consequências

- Nome de obra já escrito não é violação e não se troca. Teste e fixture novos continuam preferindo a obra
  fictícia de `cadastro-exemplo/`.
- O detalhe da regra está em `.claude/rules/dados-de-teste.md`.
