---
paths:
  - "frontend/src/**"
  - "frontend/public/**"
---

# Frontend (React 18 + Vite + TypeScript strict)

- Identidade visual em `docs/identidade-visual.md`: claro, índigo `#4F46E5`, tabela como elemento principal,
  símbolo L em grade 2×3. Tokens em `src/tokens.css`. Vermelho/âmbar/verde só com significado (erro, atenção, ok).
- Tela nova ou redesenho: usar as skills de design do projeto (`.claude/skills/`, taste-skill) e o protótipo
  aprovado pelo Leo antes de codar. Ajuste pequeno não precisa de protótipo.
- Texto na tela: só rótulo, valor, situação e ação; frase de apoio segue `.claude/rules/texto-na-tela.md`.
- Tudo em português: rótulos, erros, confirmações ("Nota enviada às HH:MM.", "Número gravado."). Nunca
  mostrar código interno (`medicao.protocolo`), exceção (`ValueError`) ou "Failed to fetch".
- Quem só consulta (diretoria) não vê botão de escrita; 403 vira "Seu perfil só consulta esta tela…".
- Precisa caber a 1024 px sem rolar na horizontal e funcionar no celular (valor numa linha, título inteiro).
- Acessibilidade mínima: foco visível, teclado, `aria-live` em confirmação, tabela `sr-only` para gráfico.
- Teste ao lado do componente (`X.test.tsx`, vitest + jsdom). `npm run typecheck` e `npm run lint` (oxlint)
  verdes antes da PR.
- Dev: `npm run dev` em `http://localhost:5173` com proxy de `/api` para o backend em 8080 com `DASH_DEV=1`
  (sem isso o cookie de sessão não volta e o login "não funciona").
