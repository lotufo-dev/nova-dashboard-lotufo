---
paths:
  - "frontend/src/**"
  - "prototipos/**"
---

# Texto na tela: só o que a pessoa usa para decidir ou agir

Decidido pelo Leo em 26/10/2026, depois da limpeza geral: as telas tinham 576 frases de apoio (subtítulo, legenda
sob número, explicação de regra, dica de onde clicar, contador secundário). Texto de apoio não é dado. A tela
mostra rótulo, valor, situação e ação; a regra mora no cadastro e no código, não numa frase cinza.

| O texto… | Faça |
|---|---|
| explica regra de negócio ("medição e reajuste vão juntos na SINFRA", "o e-mail sai da sua conta") | Não escreva. Se a regra impede a ação agora, ela vira o motivo do bloqueio (última linha). |
| diz onde fazer algo ("isso se faz na etapa 4") | Não escreva. Ponha o link ou o botão; o rótulo dele basta. |
| é legenda ou unidade sob número ou título ("cota da Lotufo", "valor cheio") | Não escreva. Se a base muda a leitura, ela entra uma vez no rótulo ou no cabeçalho da página. |
| é métrica secundária, comparação ou "última X" ("Última protocolada: …", "R$ X há mais de 60 dias") | Não escreva. Atraso que pede ação vira selo (âmbar ou vermelho) só quando acontece. |
| empilha atributos com "·" ("órgão · 3 notas de … · parada há 3 dias · a pedido do órgão") | Só o que identifica a linha (órgão, data). Estado vira selo; contagem e duração saem. |
| descreve o vazio ou o zero ("nada há mais de 60 dias", "nenhum protocolo registrado") | Mostre "—" ou nada. Lista vazia: uma linha curta no lugar da tabela. |
| ensina a preencher o campo ("digite só os números…") | Só formato que ninguém adivinharia (colar `AAAA-MM;valor`), de preferência como placeholder. O erro de validação explica na hora. |
| avisa bloqueio, falha, vencimento ou divergência que existe agora | **Fica**: uma frase, só quando o estado existe, com o link para resolver, em `CaixaAviso` ou ao lado do botão. |

- **Número ambíguo não se corrige com frase.** Se a revisão aponta que um valor pode enganar, corrija o cálculo,
  o rótulo ou mostre "—"; não acrescente aviso embaixo.
- **Redesenho não carrega texto antigo.** "A tela nova não perde nenhum dado" vale para número e ação, não para
  frase de apoio, legenda ou contador secundário.
- Não valem aqui: rótulo de campo, título, texto de botão, `aria-label`/`sr-only`, mensagem de erro e confirmação
  de ação ("Nota enviada às HH:MM.").
- `frontend/src/textoNaTela.test.ts` falha se uma classe de frase de apoio removida voltar.
