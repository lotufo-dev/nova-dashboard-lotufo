// As telas que a prova percorre (issues #701 e #702). ESTE e' o unico lugar que lista telas e perfis: a captura
// (`capturar.mjs`) e o teste de ponta a ponta da CI (`ponta_a_ponta.py`, job `ponta-a-ponta`) leem daqui.
//
// Mudou o menu, entrou ou saiu tela? Mexa so' aqui. Exemplo: o redesenho trocou "A receber" e "Carteira" pelo
// "Fechamento" (#748) e trouxe o "Resumo das medicoes" (#749): sairam as linhas `a-receber` e `carteira*` e
// entraram `fechamento`, `resumo-medicoes` e a vista QDOP da lista de Obras (`obras-qdop`).
//
// Cada tela diz:
//   rota     a tela do roteador (`frontend/src/rota.tsx`) que ela abre. Toda rota de la' precisa de uma tela aqui ou
//            de uma linha em ROTAS_FORA, com o motivo: `capturar.mjs` recusa rodar sem isso
//   id       nome curto; vira o nome do arquivo da captura e o que `--telas` aceita
//   caminho  a URL. `:obra`, `:medicao` e `:empresa` sao trocados por um registro do banco da prova: a primeira
//            obra com medicao, a primeira medicao dela e a primeira empresa com certidao exigida (ver `capturar.mjs`)
//   perfis   quem abre a tela na prova (o menu de cada perfil esta' em frontend/src/navegacao.ts)
//   espera   seletor do conteudo principal: sem ele visivel, a tela nao carregou
//   menu     so' quando o link do menu e' outro endereco que leva a esta tela (Avisos: `/avisos` abre Obras)
//   passos   o que fazer depois de a tela abrir, para chegar ao ESTADO a conferir (janela, formulario, aba):
//            { clicar: seletor }, { preencher: [seletor, texto] } ou { arquivo: [seletor do campo, nome do PDF] }.
//            Com passos, `espera` e' o seletor do estado ja' aberto
//   simular  respostas da API trocadas so' nesta tela: { caminho: /regex do caminho/, metodo: "GET", status: 200,
//            corpo: {...} }. Serve para a tela vazia, a tela de erro e o que o cadastro de exemplo nao alcanca.
//            `corpo` pode ser funcao dos registros da prova, e `ajustar: (resposta, registros) => resposta` muda a
//            resposta verdadeira em vez de troca-la
//   erro     true quando a tela DEVE mostrar o aviso de erro (a falha foi simulada); sem ele, aviso de erro reprova
//   parou    true quando a tela DEVE cair na tela "A tela parou de responder" (a resposta simulada quebra o desenho)
//   destino  o caminho em que a tela termina, quando ela so' leva a outra (`/notas/envio/:id` abre a pagina da medicao)
//
// Todo item do menu de um perfil precisa de uma tela aqui para esse perfil: a prova reprova o item sem tela.
import { cabecalhoCom, CUSTO_DA_OBRA, detalheDoEnvio, espelhoGerado, falha, inicioComAParte, medicaoComEspelhoGerado,
         medicaoComExcluidosNoRm, obrasComAParte, reconciliacaoComBaixados,
         medicaoComNotaDivergente, medicaoComNotaEmitida, medicaoDaMtpar, NOTAS_COM_DIVERGENCIA, notasAEnviar, notasComEnvioAberto,
         PDF_ILEGIVEL,
         prazosEmEncerramento, prazosParalisada, PREVIA_DO_ESPELHO, PROTOCOLO_ID, RESPOSTA_QUE_QUEBRA, RM_EXCLUSAO_RECUSADA,
         SIGA_COM_PROCESSOS } from "./simulados.mjs";

export const PERFIS = ["admin", "engenharia", "diretoria"];
export const LARGURAS = [1440, 1024, 390];

// Os links do menu lateral (`frontend/src/Casca.tsx`): mudou a casca, muda aqui.
export const MENU = "nav.menu a.menu__item";

const TODOS = PERFIS;
const OPERA = ["admin", "engenharia"];        // quem lanca medicao e envia e-mail
const SO_ADMIN = ["admin"];

const MEDICAO = "/obras/:obra/medicoes/:medicao";
const JANELA = "dialog[open] .iniciar__caixa";
const maisAcoes = item => [{ clicar: '#conteudo button:has-text("Mais ações")' }, { clicar: `#conteudo button:has-text("${item}")` }];
const passo = nome => [{ clicar: `nav.passos button:has-text("${nome}")` }];
// a medicao com a nota emitida e o envio ao orgao por fazer (ver simulados.mjs)
const MEDICOES_DA_OBRA = /^\/api\/contratos\/\d+\/medicoes$/;
const comNotaAEnviar = familia => [
  { caminho: MEDICOES_DA_OBRA, ajustar: medicaoComNotaEmitida },
  { caminho: /^\/api\/notas\/a-enviar$/, corpo: notasAEnviar(familia) },
];
// o espelho gerado e ainda nao enviado ao faturamento, com a previa do e-mail (ver simulados.mjs)
const comEspelhoGerado = [
  { caminho: MEDICOES_DA_OBRA, ajustar: medicaoComEspelhoGerado },
  { caminho: /^\/api\/contratos\/\d+\/espelho$/, ajustar: espelhoGerado },
  { caminho: /^\/api\/espelhos\/\d+\/envio$/, corpo: PREVIA_DO_ESPELHO },
];
// o envio da nota ja' comecado (com protocolo): a linha do envio abre o e-mail ao orgao
const comEnvioAberto = divergente => [
  { caminho: MEDICOES_DA_OBRA, ajustar: divergente ? medicaoComNotaDivergente : medicaoComNotaEmitida },
  { caminho: /^\/api\/notas\/a-enviar$/, corpo: notasComEnvioAberto(divergente) },
  { caminho: /^\/api\/notas\/envio\/\d+$/, corpo: detalheDoEnvio(divergente) },
  ...(divergente ? [{ caminho: /^\/api\/medicoes\/\d+\/notas$/, corpo: NOTAS_COM_DIVERGENCIA }] : []),
];
const abrirEnvio = [...passo("Envio da nota"), { clicar: '#passo-5 button:has-text("Enviar a nota")' }];
const OBRA_GRADE = ".obra-grade";

export const TELAS = [
  // ---- Inicio
  { rota: "inicio", id: "inicio", caminho: "/inicio", perfis: TODOS, espera: ".ini" },
  { rota: "inicio", id: "inicio-erro", caminho: "/inicio", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/inicio\/painel$/) },
  { rota: "inicio", id: "inicio-avisos-erro", caminho: "/inicio", perfis: SO_ADMIN, espera: ".ini-avisos [role=alert]", erro: true,
    simular: falha(/^\/api\/inicio$/) },
  // o a receber antigo e o sem atualizacao do RM, na linha a' parte do painel do ciclo (docs/adr/0006)
  { rota: "inicio", id: "inicio-a-parte", caminho: "/inicio", perfis: ["diretoria"], espera: ".ini-ciclo .em-aberto-a-parte",
    simular: [{ caminho: /^\/api\/inicio\/painel$/, ajustar: inicioComAParte }] },
  // a ultima rede: uma resposta que a tela nao sabe desenhar derruba o desenho e aparece "A tela parou de responder"
  { rota: "inicio", id: "tela-parou", caminho: "/inicio", perfis: TODOS, espera: ".falha", parou: true,
    simular: [{ caminho: /^\/api\/inicio\/painel$/, corpo: RESPOSTA_QUE_QUEBRA }] },

  // ---- Medicoes: o quadro do mes, a janela de iniciar, o quadro vazio e a falha de leitura
  // a diretoria nao tem Medicoes no menu, mas o link abre o quadro para leitura
  { rota: "medicoes", id: "medicoes", caminho: "/medicoes", perfis: TODOS, espera: ".quadro__tabela" },
  { rota: "medicoes", id: "medicoes-iniciar", caminho: "/medicoes", perfis: OPERA, antes: ".quadro__tabela", espera: JANELA,
    passos: [{ clicar: '.quadro__tabela button:has-text("Iniciar")' }] },
  { rota: "medicoes", id: "medicoes-erro", caminho: "/medicoes", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/medicoes\/resumo$/) },
  { rota: "resumo-medicoes", id: "resumo-medicoes", caminho: "/resumo-medicoes", perfis: TODOS, espera: ".rdm-faixa" },
  { rota: "resumo-medicoes", id: "resumo-medicoes-erro", caminho: "/resumo-medicoes", perfis: SO_ADMIN, espera: "#conteudo [role=alert]",
    erro: true, simular: falha(/^\/api\/resumo-medicoes$/) },

  // ---- Obras: a lista (Posicao), o QDOP, a lista vazia e a falha
  { rota: "obras", id: "obras", caminho: "/obras", perfis: TODOS, espera: ".obras-numeros" },
  { rota: "obras", id: "obras-qdop", caminho: "/obras/qdop", perfis: TODOS, espera: "#conteudo .cartao" },
  { rota: "obras", id: "obras-a-parte", caminho: "/obras", perfis: ["diretoria"], espera: ".em-aberto-a-parte",
    simular: [{ caminho: /^\/api\/contratos$/, ajustar: obrasComAParte }] },
  { rota: "obras", id: "obras-vazia", caminho: "/obras", perfis: SO_ADMIN, espera: ".obras-painel .vazio",
    simular: [{ caminho: /^\/api\/contratos$/, corpo: [] }] },
  { rota: "obras", id: "obras-erro", caminho: "/obras", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/contratos$/) },
  { rota: "avisos", id: "avisos", caminho: "/obras?avisos=1", menu: "/avisos", perfis: TODOS, espera: ".avs" },

  // ---- SIGA: sem processo (o cadastro de exemplo), com processos, o historico de um e os dois formularios
  { rota: "siga", id: "siga", caminho: "/siga", perfis: OPERA, espera: ".sg__quadro" },
  { rota: "siga", id: "siga-acompanhar", caminho: "/siga", perfis: OPERA, antes: ".sg__quadro", espera: 'form[aria-label="Acompanhar processo"]',
    passos: [{ clicar: '#conteudo button:has-text("Acompanhar processo")' }] },
  { rota: "siga", id: "siga-processos", caminho: "/siga", perfis: OPERA, espera: ".sg__quadro table",
    simular: [{ caminho: /^\/api\/siga$/, corpo: SIGA_COM_PROCESSOS }] },
  { rota: "siga", id: "siga-historico", caminho: "/siga?processo=1", perfis: OPERA, espera: ".sg__quadro table",
    simular: [{ caminho: /^\/api\/siga$/, corpo: SIGA_COM_PROCESSOS }] },
  { rota: "siga", id: "siga-corrigir", caminho: "/siga?processo=2", perfis: OPERA, antes: ".sg__quadro",
    espera: 'form[aria-label="Corrigir categoria"]', simular: [{ caminho: /^\/api\/siga$/, corpo: SIGA_COM_PROCESSOS }],
    passos: [{ clicar: '#conteudo button:has-text("Corrigir categoria")' }] },
  { rota: "siga", id: "siga-erro", caminho: "/siga", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/siga$/) },

  // ---- Documentos: as tres abas, a fila do "Anexar PDF", a janela do ZIP e a pagina da empresa
  { rota: "documentos", id: "documentos", caminho: "/documentos", perfis: TODOS, espera: ".doc-painel-aba" },
  { rota: "documentos", id: "documentos-regularidade", caminho: "/documentos", perfis: TODOS, antes: ".doc-painel-aba", espera: ".doc-painel-aba",
    passos: [{ clicar: '.escolha:has-text("Regularidade")' }] },
  { rota: "documentos", id: "documentos-garantias", caminho: "/documentos", perfis: TODOS, antes: ".doc-painel-aba", espera: ".doc-painel-aba",
    passos: [{ clicar: '.escolha:has-text("Garantias")' }] },
  { rota: "documentos", id: "documentos-anexar", caminho: "/documentos", perfis: OPERA, antes: ".doc-painel-aba", espera: ".doc-fila form",
    simular: [{ metodo: "POST", caminho: /^\/api\/documentos\/anexar\/ler$/, corpo: PDF_ILEGIVEL }],
    passos: [{ arquivo: ['input[aria-label="Escolher PDFs para anexar"]', "certidao-de-prova.pdf"] }] },
  { rota: "documentos", id: "documentos-zip", caminho: "/documentos", perfis: OPERA, antes: ".doc-painel-aba", espera: "dialog.doc-janela[open]",
    passos: [{ clicar: ".doc-linha__zip" }] },
  { rota: "documentos", id: "documentos-erro", caminho: "/documentos", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/documentos$/) },
  { rota: "documentos-empresa", id: "documentos-empresa", caminho: "/documentos/:empresa", perfis: TODOS, espera: ".doc-abas-cartao" },
  { rota: "documentos-empresa", id: "documentos-empresa-regularidade", caminho: "/documentos/:empresa/regularidade", perfis: TODOS,
    espera: ".doc-abas-cartao" },
  { rota: "documentos-empresa", id: "documentos-empresa-garantia", caminho: "/documentos/:empresa/garantia", perfis: TODOS,
    espera: ".doc-abas-cartao" },

  // ---- Fechamento e Ancoras
  { rota: "fechamento", id: "fechamento", caminho: "/fechamento", perfis: TODOS, espera: ".fch-numeros" },
  { rota: "fechamento", id: "fechamento-2025", caminho: "/fechamento", perfis: TODOS, antes: ".fch-numeros", espera: ".fch-tabela--aberto",
    passos: [{ clicar: '.escolha:has-text("2025")' }] },
  { rota: "fechamento", id: "fechamento-erro", caminho: "/fechamento", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/fechamento$/) },
  { rota: "ancoras-docusign", id: "ancoras-docusign", caminho: "/ancoras-docusign", perfis: OPERA, espera: ".anc" },

  // ---- Pagina da obra: as seis abas e a falha
  { rota: "obra", id: "obra", caminho: "/obras/:obra", perfis: TODOS, espera: ".obra-grade" },
  { rota: "obra", id: "obra-medicoes", caminho: "/obras/:obra/medicoes", perfis: TODOS, espera: ".obra-grade" },
  { rota: "obra", id: "obra-prazos", caminho: "/obras/:obra/prazos", perfis: TODOS, espera: ".obra-grade" },
  { rota: "obra", id: "obra-reajuste", caminho: "/obras/:obra/reajuste", perfis: TODOS, espera: ".obra-grade" },
  { rota: "obra", id: "obra-documentos", caminho: "/obras/:obra/documentos", perfis: TODOS, espera: ".obra-grade" },
  { rota: "obra", id: "obra-contrato", caminho: "/obras/:obra/contrato", perfis: TODOS, espera: ".obra-grade" },
  // o que a obra de exemplo nao tem: o custo lancado no RM, a paralisacao e o encerramento
  { rota: "obra", id: "obra-medicoes-custo", caminho: "/obras/:obra/medicoes", perfis: TODOS, espera: OBRA_GRADE,
    simular: [{ caminho: /^\/api\/contratos\/\d+\/custo$/, corpo: CUSTO_DA_OBRA }] },
  { rota: "obra", id: "obra-paralisada", caminho: "/obras/:obra/prazos", perfis: TODOS, espera: OBRA_GRADE,
    simular: [{ caminho: /^\/api\/contratos\/\d+\/cabecalho$/, ajustar: cabecalhoCom("suspenso") },
      { caminho: /^\/api\/contratos\/\d+\/prazos$/, ajustar: prazosParalisada }] },
  { rota: "obra", id: "obra-encerramento", caminho: "/obras/:obra/prazos", perfis: TODOS, espera: OBRA_GRADE,
    simular: [{ caminho: /^\/api\/contratos\/\d+\/cabecalho$/, ajustar: cabecalhoCom("em_encerramento") },
      { caminho: /^\/api\/contratos\/\d+\/prazos$/, ajustar: prazosEmEncerramento }] },
  { rota: "obra", id: "obra-erro", caminho: "/obras/:obra", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/contratos\/\d+\/cabecalho$/) },

  // ---- Pagina da medicao: cada passo aberto, o menu "Mais acoes" e as janelas
  { rota: "medicao", id: "medicao", caminho: MEDICAO, perfis: TODOS, espera: "nav.passos" },
  { rota: "medicao", id: "medicao-planilha", caminho: MEDICAO, perfis: TODOS, antes: "nav.passos", espera: "nav.passos",
    passos: passo("Planilha e carta") },
  { rota: "medicao", id: "medicao-analise", caminho: MEDICAO, perfis: TODOS, antes: "nav.passos", espera: "nav.passos",
    passos: passo("Análise do órgão") },
  { rota: "medicao", id: "medicao-espelhos", caminho: MEDICAO, perfis: TODOS, antes: "nav.passos", espera: "nav.passos",
    passos: passo("Espelhos") },
  { rota: "medicao", id: "medicao-notas", caminho: MEDICAO, perfis: TODOS, antes: "nav.passos", espera: "nav.passos",
    passos: passo("Notas") },
  { rota: "medicao", id: "medicao-envio", caminho: MEDICAO, perfis: TODOS, antes: "nav.passos", espera: "nav.passos",
    passos: passo("Envio da nota") },
  { rota: "medicao", id: "medicao-mais-acoes", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: "#conteudo .conta__item",
    passos: [{ clicar: '#conteudo button:has-text("Mais ações")' }] },
  { rota: "medicao", id: "medicao-cancelar", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: JANELA,
    passos: maisAcoes("Cancelar a medição") },
  { rota: "medicao", id: "medicao-desistencia", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: JANELA,
    passos: maisAcoes("Registrar desistência") },
  { rota: "medicao", id: "medicao-final", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: JANELA,
    passos: maisAcoes("Marcar como medição final") },
  { rota: "medicao", id: "medicao-boletim", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: JANELA,
    passos: maisAcoes("Registrar boletim") },
  { rota: "medicao", id: "medicao-atestado", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: JANELA,
    passos: maisAcoes("Editar o atestado") },
  { rota: "medicao", id: "medicao-protocolo-fora", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: JANELA,
    passos: [...passo("Envio da nota"), { clicar: '#conteudo button:has-text("Registrar protocolo feito fora")' }] },
  { rota: "medicao", id: "medicao-a-enviar", caminho: MEDICAO, perfis: TODOS, antes: "nav.passos", espera: "#passo-5 table",
    simular: comNotaAEnviar("sinfra"), passos: passo("Envio da nota") },
  // o espelho gerado e nao enviado, e o e-mail ao faturamento aberto (assunto comprido, anexo, aviso)
  { rota: "medicao", id: "medicao-espelho-gerado", caminho: MEDICAO, perfis: TODOS, antes: "nav.passos", espera: "#passo-3 .espelho__item",
    simular: comEspelhoGerado, passos: passo("Espelhos") },
  { rota: "medicao", id: "medicao-espelho-email", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: "#passo-3 .ol-janela",
    simular: comEspelhoGerado, passos: [...passo("Espelhos"), { clicar: '#passo-3 button:has-text("Enviar ao faturamento")' }] },
  // o e-mail ao orgao aberto no passo "Envio da nota"; com a nota divergente, a caixa de justificativa acima dele
  { rota: "medicao", id: "medicao-envio-email", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: "#envio-aberto .nota-secao",
    simular: comEnvioAberto(false), passos: abrirEnvio },
  { rota: "medicao", id: "medicao-nota-divergente", caminho: MEDICAO, perfis: TODOS, antes: "nav.passos", espera: "#passo-4 table",
    simular: comEnvioAberto(true), passos: passo("Notas") },
  { rota: "medicao", id: "medicao-envio-divergente", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: "#envio-aberto .justificativa",
    simular: comEnvioAberto(true), passos: abrirEnvio },
  { rota: "medicao", id: "medicao-envio-fora", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: JANELA,
    simular: comNotaAEnviar("sinfra"), passos: [...passo("Envio da nota"), { clicar: '#passo-5 button:has-text("Já enviei por fora")' }] },
  { rota: "medicao", id: "medicao-oficio", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: JANELA,
    simular: comNotaAEnviar("mtpar"), passos: [...passo("Envio da nota"), { clicar: '#passo-5 button:has-text("Enviar a nota")' }] },
  { rota: "medicao", id: "medicao-recebimento", caminho: MEDICAO, perfis: SO_ADMIN, antes: "nav.passos", espera: JANELA,
    passos: [{ clicar: '#conteudo button:has-text("Registrar recebimento")' }] },
  // o passo do boletim da MT-PAR (#753): a pendencia na pagina, o formulario do boletim e o boletim anexado
  { rota: "medicao", id: "medicao-mtpar-sem-boletim", caminho: MEDICAO, perfis: TODOS, espera: "nav.passos",
    simular: [{ caminho: MEDICOES_DA_OBRA, ajustar: medicaoDaMtpar() }] },
  { rota: "medicao", id: "medicao-mtpar-boletim", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: "#passo-2 .planilha__soltar",
    simular: [{ caminho: MEDICOES_DA_OBRA, ajustar: medicaoDaMtpar() }], passos: passo("Análise do órgão") },
  { rota: "medicao", id: "medicao-mtpar-anexado", caminho: MEDICAO, perfis: TODOS, antes: "nav.passos", espera: "#passo-2 .orgao-faixa__dados",
    simular: [{ caminho: MEDICOES_DA_OBRA, ajustar: medicaoDaMtpar(true) }], passos: passo("Análise do órgão") },
  // o que o RM deixou de devolver (#755): o titulo e a nota ditos como excluidos no passo Pagamento
  { rota: "medicao", id: "medicao-excluidos-rm", caminho: MEDICAO, perfis: TODOS, antes: "nav.passos", espera: "#passo-6 table",
    simular: [{ caminho: MEDICOES_DA_OBRA, ajustar: medicaoComExcluidosNoRm }], passos: passo("Pagamento") },
  { rota: "medicao", id: "medicao-erro", caminho: MEDICAO, perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/contratos\/\d+\/medicoes$/) },
  { rota: "nova-medicao", id: "nova-medicao", caminho: "/obras/:obra/medicoes/nova", perfis: OPERA, espera: ".med-grade" },
  // o endereco antigo do envio (/notas/envio/:id) abre a pagina da medicao no passo "Envio da nota"; o cadastro de
  // exemplo nao tem protocolo de nota, entao o protocolo e' simulado. Depois, o estado "nao foi possivel abrir"
  { rota: "notas-envio", id: "notas-envio", caminho: `/notas/envio/${PROTOCOLO_ID}`, destino: MEDICAO, perfis: TODOS, espera: "#passo-5 table",
    simular: comEnvioAberto(false) },
  { rota: "notas-envio", id: "notas-envio-erro", caminho: "/notas/envio/1", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: [{ caminho: /^\/api\/notas\/envio\/\d+$/, status: 404, corpo: { detail: "Protocolo não encontrado" } }] },

  // ---- Administracao: as cinco abas, os formularios de Usuarios, a auditoria vazia e a falha
  { rota: "admin", id: "admin", caminho: "/admin", perfis: SO_ADMIN, espera: "#conteudo h2" },
  { rota: "admin", id: "admin-reconciliacao", caminho: "/admin/reconciliacao", perfis: SO_ADMIN, espera: "#conteudo h2" },
  { rota: "admin", id: "admin-reconciliacao-baixados", caminho: "/admin/reconciliacao?categoria=baixados", perfis: SO_ADMIN,
    espera: "#conteudo table",
    simular: [{ caminho: /^\/api\/rm\/reconciliacao$/, ajustar: reconciliacaoComBaixados }] },
  { rota: "admin", id: "admin-usuarios", caminho: "/admin/usuarios", perfis: SO_ADMIN, espera: "#conteudo h2" },
  { rota: "admin", id: "admin-usuarios-redefinir", caminho: "/admin/usuarios", perfis: SO_ADMIN, antes: "#conteudo table",
    espera: "#conteudo table form", passos: [{ clicar: '#conteudo table button:has-text("Redefinir senha")' }] },
  { rota: "admin", id: "admin-usuarios-acessos", caminho: "/admin/usuarios", perfis: SO_ADMIN, antes: "#conteudo table",
    espera: "#conteudo table", passos: [{ clicar: '#conteudo table button:has-text("Últimos acessos")' }] },
  { rota: "admin", id: "admin-auditoria", caminho: "/admin/auditoria", perfis: SO_ADMIN, espera: "#conteudo h2" },
  { rota: "admin", id: "admin-auditoria-vazia", caminho: "/admin/auditoria", perfis: SO_ADMIN, espera: "#conteudo h2",
    simular: [{ caminho: /^\/api\/admin\/auditoria$/, corpo: { cadeia_integra: true, ha_mais: false, eventos: [] } }] },
  { rota: "admin", id: "admin-pendencias", caminho: "/admin/pendencias", perfis: SO_ADMIN, espera: "#conteudo h2" },
  // a rodada do RM que recusou uma exclusao em massa (#755): atencao no cartao do RM e o aviso no das rodadas
  { rota: "admin", id: "admin-exclusao-recusada", caminho: "/admin", perfis: SO_ADMIN, espera: "#conteudo .aviso",
    simular: [{ caminho: /^\/api\/rm\/status$/, corpo: RM_EXCLUSAO_RECUSADA }] },
  { rota: "admin", id: "admin-erro", caminho: "/admin", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/admin\/backup$/) },

  // ---- Minha conta
  { rota: "conta", id: "conta", caminho: "/conta", perfis: TODOS, espera: ".conta-eu" },
];

// Rotas do roteador que a prova nao abre, cada uma com o motivo.
export const ROTAS_FORA = {
  raiz: "\"/\" e o caminho desconhecido so' levam ao Início, que ja' esta' na lista",
};

// A tela de login (antes de entrar) e' conferida a parte, uma vez por perfil: ela nao tem `#conteudo`.
export const LOGIN = { id: "login", caminho: "/", espera: "form.entrar__form" };

// Resposta com erro que faz parte do funcionamento normal e por isso nao reprova a tela. Cada uma com o motivo.
// Qualquer outra resposta 4xx ou 5xx reprova (as de `simular` sao da propria tela e nao contam).
export const RESPOSTAS_ESPERADAS = [
  { metodo: "GET", caminho: /^\/api\/auth\/eu$/, status: 401, so: "login",
    motivo: "antes de entrar, a tela pergunta quem esta' logado e o servidor responde que ninguem" },
  { metodo: "GET", caminho: /^\/api\/contratos\/\d+\/custo$/, status: 404,
    motivo: "a obra sem cadastro de custo responde 404 e a aba Medicoes so' deixa de mostrar a coluna do custo (#748)" },
  { metodo: "GET", caminho: /^\/api\/correio\/assinatura$/, status: 404,
    motivo: "quem nao cadastrou assinatura responde 404 e o e-mail aberto mostra o aviso de que ela falta" },
];

export function telasDoPerfil(perfil) {
  return TELAS.filter(t => t.perfis.includes(perfil));
}
