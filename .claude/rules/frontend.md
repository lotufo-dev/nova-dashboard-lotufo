---
paths:
  - "frontend/src/**"
  - "frontend/public/**"
---

# Frontend (React 18 + Vite + TypeScript strict)

- **Identidade em redesenho** desde 15/11/2026: `docs/identidade-visual.md` diz o estado. Cor, fonte, tamanho,
  espaçamento e raio vêm das variáveis de `src/tokens.css`; valor novo entra lá primeiro.
- **Tela nova ou redesenho parte da decisão do dono registrada na issue:** que pergunta a tela responde e que
  informação mostra, com a imagem aprovada anexa quando existir. Ajuste pequeno segue direto.
- **Texto na tela** segue `.claude/rules/texto-na-tela.md`; os termos são os do `GLOSSARY.md`.
- **Português** em rótulo, erro e confirmação ("Nota enviada às HH:MM."). Erro mostra o que aconteceu em palavras
  da pessoa: código interno, nome de exceção e "Failed to fetch" ficam fora da tela.
- **Quem só consulta** (diretoria) não vê botão de escrita; o 403 vira "Seu perfil só consulta esta tela…".
- **Largura.** A 1024 px a página não rola de lado; tabela larga rola dentro da própria caixa. Celular (390 px) é
  requisito nas telas de leitura da diretoria: Início, Obras, página da obra, Fechamento e Resumo das medições. As
  telas de operação são de computador.
- **Acessibilidade mínima:** foco visível, teclado, `aria-live` em confirmação, tabela `sr-only` para gráfico.
- Teste ao lado do componente (`X.test.tsx`, vitest + jsdom).
