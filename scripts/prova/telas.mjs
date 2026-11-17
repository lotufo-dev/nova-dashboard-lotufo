// As telas que a prova percorre (issues #701 e #702). ESTE e' o unico lugar que lista telas e perfis: a captura
// (`capturar.mjs`) e o teste de ponta a ponta da CI (`ponta_a_ponta.py`, job `ponta-a-ponta`) leem daqui.
//
// Mudou o menu, entrou ou saiu tela? Mexa so' em TELAS. Exemplo: o redesenho trocou "A receber" e "Carteira" pelo
// "Fechamento" (#748) e trouxe o "Resumo das medicoes" (#749): sairam as linhas `a-receber` e `carteira*` e
// entraram `fechamento`, `resumo-medicoes` e as vistas da lista de Obras (`obras-resumo`, `obras-qdop`).
//
// Cada tela diz:
//   id       nome curto; vira o nome do arquivo da captura e o que `--telas` aceita
//   caminho  a URL. `:obra`, `:medicao` e `:empresa` sao trocados por um registro do banco da prova: a primeira
//            obra com medicao, a primeira medicao dela e a primeira empresa (ver `capturar.mjs`)
//   perfis   quem abre a tela na prova (o menu de cada perfil esta' em frontend/src/navegacao.ts)
//   espera   seletor do conteudo principal: sem ele visivel, a tela nao carregou
//   menu     so' quando o link do menu e' outro endereco que leva a esta tela (Avisos: `/avisos` abre Obras)
//
// Todo item do menu de um perfil precisa de uma tela aqui para esse perfil: a prova reprova o item sem tela.

export const PERFIS = ["admin", "engenharia", "diretoria"];
export const LARGURAS = [1440, 1024, 390];

const TODOS = PERFIS;
const OPERA = ["admin", "engenharia"];        // quem lanca medicao e envia e-mail
const SO_ADMIN = ["admin"];

export const TELAS = [
  { id: "inicio", caminho: "/inicio", perfis: TODOS, espera: ".ini" },
  { id: "medicoes", caminho: "/medicoes", perfis: OPERA, espera: ".quadro__tabela" },
  { id: "resumo-medicoes", caminho: "/resumo-medicoes", perfis: TODOS, espera: ".rdm-faixa" },
  { id: "obras", caminho: "/obras", perfis: TODOS, espera: ".obras-numeros" },
  { id: "obras-resumo", caminho: "/obras/resumo", perfis: TODOS, espera: ".obras-numeros" },
  { id: "obras-qdop", caminho: "/obras/qdop", perfis: TODOS, espera: "#conteudo .cartao" },
  { id: "avisos",caminho: "/obras?avisos=1", menu: "/avisos", perfis: TODOS, espera: "#avisos-area" },
  { id: "siga", caminho: "/siga", perfis: OPERA, espera: ".sg__quadro" },
  { id: "documentos", caminho: "/documentos", perfis: TODOS, espera: ".doc-painel-aba" },
  { id: "documentos-empresa", caminho: "/documentos/:empresa", perfis: TODOS, espera: ".doc-abas-cartao" },
  { id: "fechamento", caminho: "/fechamento", perfis: TODOS, espera: ".fch-numeros" },
  { id: "ancoras-docusign", caminho: "/ancoras-docusign", perfis: OPERA, espera: ".anc" },
  { id: "obra", caminho: "/obras/:obra", perfis: TODOS, espera: ".obra-grade" },
  { id: "obra-medicoes", caminho: "/obras/:obra/medicoes", perfis: TODOS, espera: ".obra-grade" },
  { id: "obra-prazos", caminho: "/obras/:obra/prazos", perfis: TODOS, espera: ".obra-grade" },
  { id: "obra-reajuste", caminho: "/obras/:obra/reajuste", perfis: TODOS, espera: ".obra-grade" },
  { id: "obra-documentos", caminho: "/obras/:obra/documentos", perfis: TODOS, espera: ".obra-grade" },
  { id: "obra-contrato", caminho: "/obras/:obra/contrato", perfis: TODOS, espera: ".obra-grade" },
  { id: "medicao", caminho: "/obras/:obra/medicoes/:medicao", perfis: TODOS, espera: "nav.passos" },
  { id: "nova-medicao", caminho: "/obras/:obra/medicoes/nova", perfis: OPERA, espera: ".med-grade" },
  { id: "admin", caminho: "/admin", perfis: SO_ADMIN, espera: "#conteudo h2" },
  { id: "admin-reconciliacao", caminho: "/admin/reconciliacao", perfis: SO_ADMIN, espera: "#conteudo h2" },
  { id: "admin-usuarios", caminho: "/admin/usuarios", perfis: SO_ADMIN, espera: "#conteudo h2" },
  { id: "admin-auditoria", caminho: "/admin/auditoria", perfis: SO_ADMIN, espera: "#conteudo h2" },
  { id: "admin-pendencias", caminho: "/admin/pendencias", perfis: SO_ADMIN, espera: "#conteudo h2" },
  { id: "conta", caminho: "/conta", perfis: TODOS, espera: ".coluna-conta" },
];

// A tela de login (antes de entrar) e' conferida a parte, uma vez por perfil: ela nao tem `#conteudo`.
export const LOGIN = { id: "login", caminho: "/", espera: "form.entrar__form" };

// Resposta com erro que faz parte do funcionamento normal e por isso nao reprova a tela. Cada uma com o motivo.
// Qualquer outra resposta 4xx ou 5xx reprova.
export const RESPOSTAS_ESPERADAS = [
  { metodo: "GET", caminho: /^\/api\/auth\/eu$/, status: 401, so: "login",
    motivo: "antes de entrar, a tela pergunta quem esta' logado e o servidor responde que ninguem" },
  { metodo: "GET", caminho: /^\/api\/contratos\/\d+\/custo$/, status: 404,
    motivo: "a obra sem cadastro de custo responde 404 e a aba Medicoes so' deixa de mostrar a coluna do custo (#748)" },
];

export function telasDoPerfil(perfil) {
  return TELAS.filter(t => t.perfis.includes(perfil));
}
