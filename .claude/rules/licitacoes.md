---
paths:
  - "backend/app/licitacoes*.py"
  - "backend/app/api_licitacoes.py"
  - "backend/app/api_radar.py"
  - "backend/migrations/*licitacoes*"
  - "frontend/src/Licitac*.tsx"
  - "frontend/src/licitacoes*"
---

# Licitações e a leitura do radar

O porquê está em `docs/adr/0018`. Os termos são os da seção "Licitações" do `GLOSSARY.md`.

- **A dashboard não lê fonte.** Site, diário, PNCP e agregador são do radar, que roda fora e entrega a leitura por
  chave (`docs/adr/0003`). Rota nova que busque algo na internet ou em pasta para as licitações contraria a decisão.
- **A classificação é do radar.** Tipo de obra, distância, esfera, nota e motivo das Recomendadas e o rótulo de cada
  mudança chegam prontos e são mostrados como vieram. O servidor calcula só o que depende do dia (dias úteis até a
  sessão, sessão passada) e das decisões das pessoas.
- **Nada se apaga.** O certame que o radar deixa de mandar fica gravado, marcado com a data. Favorita tirada,
  etapa trocada e conferência refeita guardam o que valia antes, com quem e quando.
- **Um escritor de cada lado do corte.** Antes do corte, as decisões são espelho do radar e a tela não tem botão;
  depois, só a dashboard grava decisão e o radar só busca.
- **Etapa do dossiê não se muda pela tela.** A favorita com dossiê mostra a etapa e os prazos que o radar leu dele.
- **E-mail de licitação não sai da dashboard.**
- **Dado real só no banco.** Em teste, fixture e doc: certame inventado, CNPJ fictício com dígito válido, valor
  inventado; nenhuma favorita, etapa, valor de proposta ou resultado de verdade.
- **Número em duas telas nasce numa função só** (`.claude/rules/paineis.md`): a contagem da Triagem que aparece na
  Início é a mesma função da página.
