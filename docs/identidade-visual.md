# Identidade visual — Lotufo · Plataforma de Obras

Decidida em 06/10/2026 a partir do painel de marca "opção 2" (espírito Stripe: claro, índigo, dados em primeiro plano).
Este arquivo descreve só o que está no painel aprovado. Não é um manual de regras de tela.

## Ideia
Metáfora: o livro-razão — cada valor na sua linha e coluna.
Frase: "Cada valor no seu lugar."
Símbolo: letra L formada por quatro quadrados arredondados numa grade 2×3 (coluna esquerda cheia + célula inferior direita); as duas células restantes ficam vazias.

## Cores
| Papel | Cor | Uso |
|---|---|---|
| Primária | `#4F46E5` índigo | botões principais, links, símbolo, barras de progresso |
| Tinta clara | `#EEF0FF` lavanda | fundo de destaque suave, hover, selecionado |
| Texto | `#0F172A` ardósia | títulos e valores |
| Texto secundário | `#64748B` cinza frio | legendas, rótulos de coluna |
| Fundo da página | `#F6F8FB` | fundo geral |
| Superfície | `#FFFFFF` | cartões e tabelas |
| Feito / recebido | `#10B981` verde (texto `#047857`) | informação, ver "Regra de cor da informação" |
| Em andamento | `#3B82F6` azul (texto `#1D4ED8`) | informação, idem |
| Vence em breve / faltando | `#F59E0B` âmbar (texto `#B45309`) | informação, idem |
| Crítico / vencido / sem registro | `#EF4444` vermelho (texto `#B91C1C`) | informação, idem |

A marca não usa verde, azul, âmbar nem vermelho.

## Regra de cor da informação
Decidida pelo Leo em 06/11/2026 e válida para a dashboard inteira. A cor é da **informação**, não do desenho da
página (menu índigo, fundo cinza-claro e cartões brancos não mudam).
- Número e data são pretos por padrão.
- **Verde** = feito ou recebido. **Azul** = em andamento. **Âmbar** = vence em breve ou faltando.
  **Vermelho** = crítico, vencido ou sem registro.
- O que não é urgente fica preto (por exemplo, o fim de uma vigência distante).
- Telas que usam a regra mostram no topo direito a legenda pequena "feito · em andamento · vence em breve · crítico"
  (componente `LegendaCor`).
- Em `frontend/src/tokens.css`: tokens `--ok`, `--andamento`, `--atencao`, `--acao` (texto) e os pares `-fundo`,
  `-linha`, `-ponto`. Classes: `.info--feito|andamento|breve|critico` pintam o texto; `.pilula-info--*` é a pílula
  (fundo tingido, texto escuro, `.pilula-info__ponto` opcional). Quem não tem situação não leva classe.
- A aplicação em cada tela é feita na issue da tela (Início, Obras, Avisos, SIGA, Documentos e Medições).

## Tipografia
- Uma fonte só, **Lexend** (400, 500, 600, 700), sem serifa, geométrica, larga e arredondada; servida pelo próprio
  app em `frontend/public/fonts/` (licença OFL ao lado), sem CDN. Títulos e valores em negrito (700).
- Valores em reais na mesma fonte do texto (não há fonte monoespaçada), alinhados à direita nas tabelas, com
  algarismos tabulares (`font-variant-numeric: tabular-nums`, já aplicado a `td` e `th`).
- Escala: 12 (rótulo), 14 (texto), 16 (texto destacado), 24 (título de página), 32–40 (valor grande em cartão).

## Menu lateral
Largo por padrão (240 px), com ícone e nome em cada item e o item ativo em pílula branca; recolhível para só ícones
(64 px) por um botão no pé, e a escolha fica guardada no navegador. No celular (< 768 px) nasce recolhido, abre por
cima da tela e fecha ao navegar. Componente `Trilho` em `frontend/src/Casca.tsx`.

## Forma
- Raio dos cartões e botões: 8 px; pílulas de situação: 999 px.
- Sombra dos cartões: suave (`0 1px 2px rgba(15,23,42,.06), 0 4px 12px rgba(15,23,42,.06)`).
- Espaçamento base: 8 px; respiro entre cartões: 16–24 px.
- Tabela é o elemento principal onde há lista de valores: cabeçalho em cinza frio 12 px, linhas de 44 px, um ponto colorido por situação.
- Pílulas de situação: fundo tingido claro + ponto colorido + texto em ardósia.

## Imagem
Fotografia clara de infraestrutura (pontes, viadutos, rodovias) em tons frios, com leve véu índigo quando usada como fundo.
