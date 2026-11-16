---
paths:
  - "frontend/src/**"
  - "prototipos/**"
---

# Texto na tela: só o que a pessoa usa para decidir ou agir

Decidido pelo dono em 26/10/2026, depois de uma limpeza de 576 frases de apoio, e dividido em dois em 15/11/2026.
A tela mostra rótulo, valor, situação e ação; a regra mora no cadastro e no código.

## Frase de apoio: fora, sempre

| O texto… | Faça |
|---|---|
| explica regra de negócio ("medição e reajuste vão juntos neste órgão", "o e-mail sai da sua conta") | Deixe fora. Se a regra impede a ação agora, ela vira o motivo da trava (última linha). |
| diz onde fazer algo ("isso se faz na etapa 4") | Ponha o link ou o botão; o rótulo dele basta. |
| é legenda ou unidade sob número ou título ("cota", "valor cheio") | Se a base muda a leitura, ela entra uma vez no rótulo ou no cabeçalho da página. |
| descreve o vazio ou o zero ("nada há mais de 60 dias", "nenhum protocolo registrado") | Mostre "—" ou nada. Lista vazia: uma linha curta no lugar da tabela. |
| ensina a preencher o campo ("digite só os números…") | Só o formato que ninguém adivinharia, de preferência como placeholder. O erro de validação explica na hora. |
| avisa trava, falha, vencimento ou divergência que existe agora | **Fica**: uma frase, só quando o estado existe, com o link para resolver. |

- **Número ambíguo se corrige no número.** Se um valor pode enganar, acerte o cálculo ou o rótulo, ou mostre "—".
- **Redesenho leva número e ação; a frase antiga fica para trás.**
- Rótulo de campo, título, texto de botão, `aria-label`, `sr-only`, mensagem de erro e confirmação de ação são
  texto de trabalho, e ficam.

## Dado secundário: decidido na issue da tela

Data, valor ou contagem que acompanha o dado principal ("última medição recebida em…", número e data de um
documento, atributos de uma linha) não tem regra geral. A issue da tela decide, pela pergunta que a tela responde.
Estado vira selo; atraso que pede ação aparece só quando acontece.
