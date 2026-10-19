# Protótipos aprovados do redesenho

Aprovados pelo Leo em 16/10/2026 na página de protótipos (dados inventados). São a referência visual e de
conteúdo da implementação de cada tela; abra o `.html` no navegador a partir desta pasta.

| Tela | Issue | Arquivo |
|---|---|---|
| Página da medição (com a Nova medição como etapa 1) | #152, #153 | `medicao.html` |
| Medições › Enviar nota | #157 | `enviar-nota.html` |
| Obras: escolha do contratante e lista de obras | #159 | `obras.html`, `obras-lista.html` |
| Página da obra | #160 | `pagina-da-obra.html` |
| Documentos: empresas e página da empresa | #161 | `documentos.html`, `documentos-empresa.html` |
| A receber | #162 | `a-receber.html` |
| Carteira | #163 | `carteira.html` |
| Administração | #164 | `administracao.html` |
| Minha conta | #165 | `minha-conta.html` |

`base.css` é cópia de `frontend/src/tokens.css` com estilos só de protótipo no fim; `shell.js` desenha a casca
(trilho e barra) igual a `Casca.tsx`. O protótipo mostra todos os botões para todos os perfis: a implementação
mantém as permissões por perfil de hoje. A Página da medição e a aba Enviar nota foram aprovadas depois da
análise de fluxos redundantes de 16/10/2026: o registro de envio ou protocolo feito por fora é uma ação só, na
etapa 4; o nº do protocolo no órgão se informa só na etapa 4, com o comprovante; a aba Enviar nota só mostra o que
vai junto e o que falta e leva à etapa 4; documento faltando no envio pede confirmação (#213), sem justificativa
obrigatória; o botão final é "Enviar o e-mail".
