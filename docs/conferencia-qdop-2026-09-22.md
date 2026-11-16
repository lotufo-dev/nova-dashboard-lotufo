# Conferência do cadastro com o QDOP de 22/09/2026 (bloco 8, tarefa 8.2)

Fonte: `GL.SGI.FRP.DE.250 - QDOP - QUADRO DEMONSTRATIVO DE OBRAS E PROJETOS (3).xlsx` (Downloads, pasta
"LICITAÇÕES 11.08.2026"), lido só com os valores que o Excel calculou. Base da dashboard: cópia da produção de
24/09/2026 com o cadastro do bloco 7 aplicado. Casamento de cada contrato com a linha do QDOP pelo valor
original na cota, o mesmo critério de `carga_legado.conferir_com_qdop`.

Regra (memória "hierarquia das fontes"): o instrumento assinado manda; o QDOP confere e não alimenta. Só vira
YAML o que tem instrumento ou fato documentado.

## Resultado

| Obra | Linha | Vigente (cota) | Datas | O que fazer |
|---|---|---|---|---|
| Região Oeste | 14 | confere | conferem | — |
| Parque Atalaia | 15 | R$ 0,01 de diferença (arredondamento da cota de 80%) | conferem | nada |
| Alta Floresta | 16 | confere | conferem | QDOP: CONCLUÍDA; cadastro em encerramento desde 17/07/2026 |
| Deciolândia | 17 | confere | QDOP: término 30/11/2026 e vigência 01/03/2027; cadastro: 29/06/2026 e 28/09/2026 | P2: falta o instrumento que prorrogou |
| MT-401 | 18 | confere | conferem | — |
| 5 Bairros | 19 | confere | conferem | — |
| Leblon | 20 | confere | conferem | — |
| MT-402 | 21 | confere | conferem | — |
| Integra BRT | 22 | confere | conferem | — |
| Espaço Show | 23 | confere | conferem | — |
| Complexo Orla | 24 | confere | conferem | QDOP: CONCLUÍDA; cadastro em encerramento |
| Complexo Cultural | 25 | confere | conferem | — |
| Complexo Xtreme | 26 | confere | conferem | — |
| Coxipó 2ª Etapa | 27 | confere | conferem | QDOP: PARALISADA; cadastro suspenso, paralisação desde 01/10/2025 |
| Coxipó 3ª Etapa | 28 | R$ 0,02 de diferença (arredondamento) | conferem | nada |
| BR-163 | 29 | confere | conferem | — |
| MT-388 | 30 | confere | QDOP: início 01/08/2025 (ordem de serviço), vigência 05/06/2027; cadastro: 16/07/2025 (assinatura), 06/06/2027 | P2: o cadastro usa a assinatura como início; 1 dia na vigência |
| Granito | 31 | confere | conferem | — |
| Maternidade VG | 32 | confere | QDOP: vigência 18/12/2027; cadastro: 31/10/2027 (vigência antes da execução, aviso do `cadastro validar`) | P2: conferir o 1º aditivo |
| Estações BRT | 33 | confere | conferem | — |
| Cavalaria | 34 | confere | conferem | — |
| Terminais BRT | 35 | confere | QDOP: vigência 16/02/2027; cadastro: 20/03/2027 | P2: conferir qual instrumento vale |
| Rota do Oeste lote 2 | 36 | sem contrato no cadastro | — | P2: entra quando a entidade do consórcio (20%) for confirmada |

## O que virou YAML

- `objeto_completo` das 22 obras, da coluna DESCRIÇÃO DA OBRA, com a fonte em comentário. Nas cartas, o
  corpo usa o objeto sem o "EXECUÇÃO" inicial (`carta.objeto_na_frase`), e a linha "Ref." usa o texto inteiro.
- `nome_qdop` e `tipo_contratante` dos 10 órgãos (coluna CONTRATANTE e TIPO).

Datas e valores: nada mudou. As diferenças acima não têm instrumento no repositório e ficam como pendência.

## P2 (o dono)

- Deciolândia: instrumento que levou a execução a 30/11/2026 e a vigência a 01/03/2027.
- MT-388: início da execução pela ordem de serviço (01/08/2025) ou pela assinatura (16/07/2025); vigência 05 ou
  06/06/2027.
- Maternidade VG e Terminais BRT: vigência do último instrumento.
- Rota do Oeste lote 2: entidade do consórcio e percentual (20% no QDOP).

## Ensaio do cadastro (cópia da produção com o bloco 7 aplicado, 24/09/2026)

```
orgaos: 0 criados, 10 alterados, 0 iguais        (nome_qdop, tipo_contratante)
entidades: 0 criados, 0 alterados, 10 iguais
contratos: 0 criados, 22 alterados, 0 iguais     (objeto_completo)
instrumentos: 0 criados, 0 alterados, 38 iguais
pleitos: 0 criados, 0 alterados, 19 iguais
geral: 2 criados, 0 alterados, 2 iguais          (+ diretoria, + qdop)
espelho: 0 criados, 0 alterados, 19 iguais
```
