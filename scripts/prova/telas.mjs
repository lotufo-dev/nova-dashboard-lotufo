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
//   menu     so' quando o link do menu e' outro endereco que leva a esta tela (hoje nenhuma: todo item abre o proprio)
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
import { avisosEmVolume, semAvisos, cabecalhoCom, cabecalhoEmDia, CUSTO_DA_OBRA, detalheDoEnvio, espelhoEnviadoPorFora, espelhoGerado, falha,
         fechamentoComValores, fichaComNecessario, inicioComAParte, inicioComVariacoes, semAvisoDePrazo,
         medicaoComEspelhoEnviadoPorFora, medicaoComEspelhoGerado, medicaoComExcluidosNoRm, obrasComAParte, reconciliacaoComBaixados,
         medicaoComNotaDivergente, medicaoComNotaEmitida, medicaoDaMtpar, NOTAS_COM_DIVERGENCIA, notasAEnviar, notasComEnvioAberto,
         PDF_ILEGIVEL,
         prazosEmEncerramento, prazosParalisada, PREVIA_DO_ESPELHO, PROTOCOLO_ID, RESPOSTA_QUE_QUEBRA, resumoEmQuadro, RM_EXCLUSAO_RECUSADA,
         SIGA_COM_NAO_LIDOS, SIGA_COM_PROCESSOS, SIGA_SO_MEDICOES } from "./simulados.mjs";
import { fechamentoEmAbas } from "./simulados.mjs";   // #815: em linha propria, para nao mexer na lista de cima

import { carteiraSimulada, filaSimulada, painelDaCarteira } from "./simulados.mjs";
import { cabecalhoDeNomeLongo } from "./simulados.mjs";
// issue #817 (reestrutura 5c): a Inicio com o ciclo por contratante e o medido em 12 meses
import { inicioPorContratante, inicioSemCiclo } from "./simulados.mjs";

export const PERFIS = ["admin", "engenharia", "diretoria"];
export const LARGURAS = [1440, 1024, 390];

// Os links do menu lateral (`frontend/src/Casca.tsx`): mudou a casca, muda aqui.
export const MENU = "nav.menu a.menu__item";

const TODOS = PERFIS;
const OPERA = ["admin", "engenharia"];        // quem lanca medicao e envia e-mail
const SO_ADMIN = ["admin"];

const MEDICAO = "/obras/:obra/medicoes/:medicao";
const JANELA = "dialog[open] .iniciar__caixa";
// issue #805: a carteira de quatro contratantes no lugar do cadastro de exemplo (ver simulados.mjs)
const comCarteira = [
  { caminho: /^\/api\/contratos$/, corpo: carteiraSimulada },
  { caminho: /^\/api\/diretoria$/, ajustar: painelDaCarteira },
];
// issue #805: o mes de Medicoes com medicao em cada grupo da fila (ver simulados.mjs)
const comFila = [{ caminho: /^\/api\/medicoes\/fila$/, ajustar: filaSimulada }];
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
// issue #798: o espelho com o envio ao faturamento registrado como feito por fora
const comEspelhoEnviadoPorFora = [
  { caminho: MEDICOES_DA_OBRA, ajustar: medicaoComEspelhoEnviadoPorFora },
  { caminho: /^\/api\/contratos\/\d+\/espelho$/, ajustar: espelhoEnviadoPorFora },
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
// issue #803: a obra com a execucao em dia e o necessario por mes; `noRitmo` poe o ritmo acima dele
const comNecessario = noRitmo => [
  { caminho: /^\/api\/contratos\/\d+\/cabecalho$/, ajustar: cabecalhoEmDia },
  { caminho: /^\/api\/contratos\/\d+\/ficha$/, ajustar: fichaComNecessario(noRitmo) },
  { caminho: /^\/api\/inicio$/, ajustar: semAvisoDePrazo },
];
// issue #822: a pagina da obra fora da regua do andamento: o motivo no lugar da leitura, sem selo na conclusao.
// `noFim`: a execucao termina no mes que vem (duas competencias)
import { cabecalhoNoFim, fichaForaDaRegua } from "./simulados.mjs";
const foraDaRegua = (fora, noFim = false) => [
  { caminho: /^\/api\/contratos\/\d+\/cabecalho$/, ajustar: noFim ? cabecalhoNoFim : cabecalhoEmDia },
  { caminho: /^\/api\/contratos\/\d+\/ficha$/, ajustar: fichaForaDaRegua(fora, noFim) },
  { caminho: /^\/api\/inicio$/, ajustar: semAvisoDePrazo },
];
// issue #805: a fila de avisos com o volume da producao (dezenas de vencidos em varias obras, um aviso de cada assunto
// pelo menos; ver simulados.mjs). O servidor recorta a fila pelo perfil, e a simulada tambem: a tela entra duas vezes
// na lista com o mesmo id, uma para quem opera (com certidao, prazo a vencer, nota e SIGA) e outra para a diretoria
const comAvisosEmVolume = tela => [
  { ...tela, perfis: OPERA, simular: [{ caminho: /^\/api\/inicio$/, ajustar: avisosEmVolume("operacao") }] },
  { ...tela, perfis: ["diretoria"], simular: [{ caminho: /^\/api\/inicio$/, ajustar: avisosEmVolume("diretoria") }] },
];

// issue #805: o SIGA com processos, que o cadastro de exemplo nao tem (ver simulados.mjs)
const comSiga = corpo => [{ caminho: /^\/api\/siga$/, corpo }];
// issue #805: o mes do Resumo das medicoes com medicao em cada etapa (ver simulados.mjs)
const comResumo = opcoes => [{ caminho: /^\/api\/resumo-medicoes$/, ajustar: resumoEmQuadro(opcoes) }];

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
  // as familias de valor (#805): os dois numeros do alto com a variacao contra as referencias (subiu, caiu e estavel)
  { rota: "inicio", id: "inicio-variacoes", caminho: "/inicio", perfis: ["diretoria"], espera: ".ini-numero__variacoes .variacao",
    simular: [{ caminho: /^\/api\/inicio\/painel$/, ajustar: inicioComVariacoes }] },
  // o que faltava apresentar a' diretoria (#817): o ciclo aberto por contratante e o medido em 12 meses, com o volume
  // que o cadastro de exemplo nao tem; e a mesma tela sem nada no ciclo
  { rota: "inicio", id: "inicio-por-contratante", caminho: "/inicio", perfis: TODOS, espera: ".ini-orgaos table tfoot",
    simular: [{ caminho: /^\/api\/inicio\/painel$/, ajustar: inicioPorContratante }] },
  { rota: "inicio", id: "inicio-sem-ciclo", caminho: "/inicio", perfis: ["diretoria"], espera: ".ini-orgaos .ini-vazio",
    simular: [{ caminho: /^\/api\/inicio\/painel$/, ajustar: inicioSemCiclo }] },
  // a ultima rede: uma resposta que a tela nao sabe desenhar derruba o desenho e aparece "A tela parou de responder"
  { rota: "inicio", id: "tela-parou", caminho: "/inicio", perfis: TODOS, espera: ".falha", parou: true,
    simular: [{ caminho: /^\/api\/inicio\/painel$/, corpo: RESPOSTA_QUE_QUEBRA }] },

  // ---- Medicoes (#805): a fila de trabalho (a entrada), o quadro do mes e os meses anteriores; a janela de iniciar e
  // a falha de leitura. As telas `-cheia` trocam o cadastro de exemplo (sem medicao no mes) por um mes com medicao em
  // cada grupo, parada ha' pouco e ha' muito, com o aprovado abaixo, acima e igual ao pedido (ver simulados.mjs).
  // A diretoria nao tem Medicoes no menu, mas o link abre a tela para leitura, sem botao de escrita
  { rota: "medicoes", id: "medicoes", caminho: "/medicoes", perfis: TODOS, espera: ".fila-numeros" },
  { rota: "medicoes", id: "medicoes-cheia", caminho: "/medicoes", perfis: TODOS, espera: ".fila-grupo .fila__tabela", simular: comFila },
  { rota: "medicoes", id: "medicoes-quadro", caminho: "/medicoes/quadro", perfis: TODOS, espera: ".medicoes__painel" },
  { rota: "medicoes", id: "medicoes-quadro-cheio", caminho: "/medicoes/quadro", perfis: TODOS, espera: ".quadro__tabela .quadro__grupo",
    simular: comFila },
  { rota: "medicoes", id: "medicoes-anteriores", caminho: "/medicoes/anteriores", perfis: TODOS, espera: ".medicoes__vistas" },
  { rota: "medicoes", id: "medicoes-anteriores-cheia", caminho: "/medicoes/anteriores", perfis: TODOS, espera: ".fila-resumo",
    simular: comFila },
  { rota: "medicoes", id: "medicoes-iniciar", caminho: "/medicoes", perfis: OPERA, antes: ".fila-bloco", espera: JANELA,
    passos: [{ clicar: '.fila-bloco button:has-text("Iniciar")' }] },
  { rota: "medicoes", id: "medicoes-erro", caminho: "/medicoes", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/medicoes\/fila$/) },
  // ---- Resumo das medicoes em quadro por etapa (#805): o cadastro de exemplo, e o mes simulado (ver simulados.mjs)
  // com medicao em cada etapa, as diferencas para o pedido, as obras sem medicao e os meses anteriores, nas duas
  // vistas, na aba dos meses anteriores, com o filtro por contratante (etapas vazias) e no mes sem medicao
  { rota: "resumo-medicoes", id: "resumo-medicoes", caminho: "/resumo-medicoes", perfis: TODOS, espera: ".rdm-abas" },
  { rota: "resumo-medicoes", id: "resumo-medicoes-quadro", caminho: "/resumo-medicoes", perfis: TODOS, espera: ".rdm-quadro .rdm-cartao .diferenca",
    simular: comResumo() },
  { rota: "resumo-medicoes", id: "resumo-medicoes-tabela", caminho: "/resumo-medicoes?vista=tabela", perfis: ["diretoria"],
    espera: ".rdm-tabela--etapas .rdm-grupo", simular: comResumo() },
  { rota: "resumo-medicoes", id: "resumo-medicoes-anteriores", caminho: "/resumo-medicoes?aba=anteriores", perfis: ["diretoria"],
    espera: ".rdm-tabela--etapas .rdm-grupo", simular: comResumo() },
  { rota: "resumo-medicoes", id: "resumo-medicoes-contratante", caminho: "/resumo-medicoes?contratante=MTPAR", perfis: ["diretoria"],
    espera: ".rdm-quadro .rdm-coluna__vazia", simular: comResumo({ contratante: "MTPAR" }) },
  { rota: "resumo-medicoes", id: "resumo-medicoes-vazio", caminho: "/resumo-medicoes", perfis: ["diretoria"], espera: ".rdm-vazio",
    simular: comResumo({ vazio: true }) },
  { rota: "resumo-medicoes", id: "resumo-medicoes-erro", caminho: "/resumo-medicoes", perfis: SO_ADMIN, espera: "#conteudo [role=alert]",
    erro: true, simular: falha(/^\/api\/resumo-medicoes$/) },

  // ---- Obras em niveis (#805): "Por contratante" (a entrada), "Todas as obras", "Andamento" e o QDOP; a pagina de
  // um contratante; a lista vazia e a falha. As telas `-carteira` trocam o cadastro de exemplo (um orgao, duas obras)
  // por uma carteira de quatro contratantes, com obra devagar, em atencao, adiantada, paralisada e vencida
  { rota: "obras", id: "obras", caminho: "/obras", perfis: TODOS, espera: ".obras-contratantes" },
  { rota: "obras", id: "obras-carteira", caminho: "/obras", perfis: TODOS, espera: ".obras-contratantes .obras-etiquetas .selo",
    simular: comCarteira },
  { rota: "obras", id: "obras-todas", caminho: "/obras/todas", perfis: TODOS, espera: ".obras-posicao" },
  { rota: "obras", id: "obras-todas-carteira", caminho: "/obras/todas", perfis: TODOS, espera: ".obras-posicao .andamento",
    simular: comCarteira },
  { rota: "obras", id: "obras-todas-reajustes", caminho: "/obras/todas", perfis: ["diretoria"], antes: ".obras-reajustes",
    espera: ".obras-reajustes[open] table", simular: comCarteira, passos: [{ clicar: ".obras-reajustes > summary" }] },
  { rota: "obras", id: "obras-andamento", caminho: "/obras/andamento", perfis: TODOS, espera: ".obras-painel" },
  { rota: "obras", id: "obras-andamento-carteira", caminho: "/obras/andamento", perfis: TODOS, espera: ".obras-andamento .andamento",
    simular: comCarteira },
  { rota: "obras", id: "obras-qdop", caminho: "/obras/qdop", perfis: TODOS, espera: "#conteudo .cartao" },
  // a pagina do contratante: o do cadastro de exemplo (a familia "sinfra"); da carteira simulada, um com prazo de
  // pagamento e de tudo um pouco (SINFRA, com as encerradas a' vista) e um sem prazo no sistema (MTPAR)
  { rota: "contratante", id: "contratante", caminho: "/obras/contratante/sinfra", perfis: TODOS, espera: ".obras-do-contratante" },
  { rota: "contratante", id: "contratante-carteira", caminho: "/obras/contratante/sinfra", perfis: TODOS,
    espera: ".obras-do-contratante .andamento", simular: comCarteira },
  { rota: "contratante", id: "contratante-todas", caminho: "/obras/contratante/sinfra?situacao=todas", perfis: ["diretoria"],
    espera: ".obras-do-contratante .andamento", simular: comCarteira },
  { rota: "contratante", id: "contratante-sem-prazo", caminho: "/obras/contratante/mtpar", perfis: ["diretoria"],
    espera: ".obras-do-contratante .andamento", simular: comCarteira },
  { rota: "contratante", id: "contratante-nao-encontrado", caminho: "/obras/contratante/nao-existe", perfis: SO_ADMIN, espera: "#conteudo .vazio" },
  { rota: "contratante", id: "contratante-erro", caminho: "/obras/contratante/sinfra", perfis: SO_ADMIN, espera: "#conteudo [role=alert]",
    erro: true, simular: falha(/^\/api\/contratos$/) },
  { rota: "obras", id: "obras-a-parte", caminho: "/obras", perfis: ["diretoria"], espera: ".em-aberto-a-parte",
    simular: [{ caminho: /^\/api\/contratos$/, ajustar: obrasComAParte }] },
  { rota: "obras", id: "obras-vazia", caminho: "/obras/todas", perfis: SO_ADMIN, espera: ".obras-painel .vazio",
    simular: [{ caminho: /^\/api\/contratos$/, corpo: [] }] },
  { rota: "obras", id: "obras-erro", caminho: "/obras", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/contratos$/) },

  // ---- Avisos (#805): a pagina propria com o cadastro de exemplo; com o volume da producao (dezenas de vencidos em
  // varias obras, todos os assuntos), fechada e com uma obra aberta; filtrada por uma obra e por um assunto (o
  // endereco de antes, `?familia=nota`, abre a aba Medicoes); vazia; a falha; e o endereco de antes, de quando os
  // Avisos abriam dentro de Obras
  { rota: "avisos", id: "avisos", caminho: "/avisos", perfis: TODOS, espera: ".avs-numeros" },
  ...comAvisosEmVolume({ rota: "avisos", id: "avisos-volume", caminho: "/avisos", espera: ".avs-vencidos" }),
  ...comAvisosEmVolume({ rota: "avisos", id: "avisos-volume-aberta", caminho: "/avisos", antes: ".avs-vencidos", espera: ".avs-vencido__itens",
    passos: [{ clicar: ".avs-vencido:nth-child(1) .avs-abre" }] }),
  ...comAvisosEmVolume({ rota: "avisos", id: "avisos-obra", caminho: "/avisos?obra=:obra", espera: ".avs-recorte + .avs-numeros" }),
  ...comAvisosEmVolume({ rota: "avisos", id: "avisos-assunto", caminho: "/avisos?familia=nota", espera: ".avs-vencidos" }),
  { rota: "avisos", id: "avisos-vazia", caminho: "/avisos", perfis: SO_ADMIN, espera: ".avs-barra + .avs-vazio",
    simular: [{ caminho: /^\/api\/inicio$/, ajustar: semAvisos }] },
  { rota: "avisos", id: "avisos-erro", caminho: "/avisos", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/inicio$/) },
  { rota: "avisos", id: "avisos-endereco-de-antes", caminho: "/obras?c=todas&avisos=1", destino: "/avisos", perfis: SO_ADMIN,
    espera: ".avs-numeros" },

  // ---- SIGA (#805, um painel por categoria): sem processo (o cadastro de exemplo); todos, com processo em cada
  // categoria e em cada faixa do tempo parado; uma categoria; a categoria sem processo; com nao lidos; o historico de
  // um processo e os dois formularios
  // a faixa de numeros existe com ou sem processo: a tela abre tambem sobre uma copia do banco, que tem processos
  { rota: "siga", id: "siga", caminho: "/siga", perfis: OPERA, espera: ".sg-numeros" },
  { rota: "siga", id: "siga-acompanhar", caminho: "/siga", perfis: OPERA, antes: ".sg-numeros", espera: 'form[aria-label="Acompanhar processo"]',
    passos: [{ clicar: '#conteudo button:has-text("Acompanhar processo")' }] },
  { rota: "siga", id: "siga-processos", caminho: "/siga", perfis: OPERA, espera: ".sg-grupo table", simular: comSiga(SIGA_COM_PROCESSOS) },
  { rota: "siga", id: "siga-categoria", caminho: "/siga?categoria=medicoes", perfis: OPERA, espera: ".sg-grupo table",
    simular: comSiga(SIGA_COM_PROCESSOS) },
  { rota: "siga", id: "siga-categoria-vazia", caminho: "/siga?categoria=aditivos", perfis: OPERA, espera: ".sg__barra + .sg__quadro",
    simular: comSiga(SIGA_SO_MEDICOES) },
  { rota: "siga", id: "siga-nao-lidos", caminho: "/siga", perfis: OPERA, espera: ".sg__etiqueta", simular: comSiga(SIGA_COM_NAO_LIDOS) },
  { rota: "siga", id: "siga-encerrados", caminho: "/siga", perfis: OPERA, antes: ".sg-grupo table", espera: ".sg__encerrados[open] table",
    simular: comSiga(SIGA_COM_PROCESSOS), passos: [{ clicar: ".sg__encerrados > summary" }] },
  { rota: "siga", id: "siga-historico", caminho: "/siga?processo=1", perfis: OPERA, espera: ".sg__quadro table", simular: comSiga(SIGA_COM_PROCESSOS) },
  { rota: "siga", id: "siga-corrigir", caminho: "/siga?processo=2", perfis: OPERA, antes: ".sg__quadro",
    espera: 'form[aria-label="Corrigir categoria"]', simular: comSiga(SIGA_COM_PROCESSOS),
    passos: [{ clicar: '#conteudo button:has-text("Corrigir categoria")' }] },
  { rota: "siga", id: "siga-erro", caminho: "/siga", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/siga$/) },

  // ---- Documentos: as tres abas, a fila do "Anexar PDF", a janela do ZIP e a pagina da empresa
  { rota: "documentos", id: "documentos", caminho: "/documentos", perfis: TODOS, espera: ".doc-painel-aba" },
  // #814: cada assunto tem o proprio endereco (e o proprio item no menu); antes eram abas de "/documentos"
  { rota: "documentos", id: "documentos-regularidade", caminho: "/documentos/regularidade", perfis: TODOS,
    espera: '#aba-regularidade[aria-selected="true"]' },
  { rota: "documentos", id: "documentos-garantias", caminho: "/documentos/garantias", perfis: TODOS, espera: '#aba-garantias[aria-selected="true"]' },
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
  { rota: "fechamento", id: "fechamento-2025", caminho: "/fechamento", perfis: TODOS, antes: ".fch-numeros",
    espera: '.escolha[aria-pressed="true"]:has-text("2025")', passos: [{ clicar: '.escolha:has-text("2025")' }] },
  // as familias de valor (#805): a tabela do mes com dois anos (a variacao do medido), a diferenca entre o aprovado e
  // o pedido (so' o corte, no mes) e o em aberto; no segundo estado, tres meses abertos ate' a medicao: o corte
  // critico, o corte ao lado de um arredondamento, e o aprovado acima do pedido, que so' aparece na linha da medicao
  { rota: "fechamento", id: "fechamento-valores", caminho: "/fechamento", perfis: ["diretoria"], espera: ".fch-tabela--meses .variacao",
    simular: [{ caminho: /^\/api\/fechamento$/, corpo: fechamentoComValores }] },
  { rota: "fechamento", id: "fechamento-valores-medicao", caminho: "/fechamento", perfis: ["diretoria"], antes: ".fch-tabela--meses .variacao",
    espera: ".fch-linha--medicao", simular: [{ caminho: /^\/api\/fechamento$/, corpo: fechamentoComValores }],
    passos: ["Julho", "Agosto", "Setembro"].flatMap((mes, i) => [
      { clicar: `.fch-abre[aria-label^="${mes} de 2026"]` },
      { clicar: `.fch-abre[aria-label="Obra Exemplo, medições de 0${7 + i}/2026"]` }]) },
  { rota: "fechamento", id: "fechamento-erro", caminho: "/fechamento", perfis: SO_ADMIN, espera: "#conteudo [role=alert]", erro: true,
    simular: falha(/^\/api\/fechamento$/) },
  // Fechamento em abas (#815): cada aba pelo endereco dela, com o cadastro de exemplo (um contratante so') e com o
  // simulado de quatro contratantes e dois anos (a variacao na comparacao, a participacao e o nome comprido); o ano
  // pelo endereco; o mes aberto pelo endereco; e a pagina sem lancamento nas tres abas
  { rota: "fechamento", id: "fechamento-comparacao", caminho: "/fechamento/comparacao", perfis: TODOS, espera: ".fch-tabela--comparacao" },
  { rota: "fechamento", id: "fechamento-contratantes", caminho: "/fechamento/contratantes?ano=2025", perfis: TODOS,
    espera: ".fch-tabela--contratantes" },   // o cadastro de exemplo so' mede em 2025: o ano vai no endereco
  { rota: "fechamento", id: "fechamento-comparacao-valores", caminho: "/fechamento/comparacao", perfis: ["diretoria"],
    espera: ".fch-tabela--comparacao .variacao", simular: [{ caminho: /^\/api\/fechamento$/, corpo: fechamentoEmAbas() }] },
  { rota: "fechamento", id: "fechamento-contratantes-valores", caminho: "/fechamento/contratantes", perfis: TODOS,
    espera: ".fch-tabela--contratantes .fch-parte", simular: [{ caminho: /^\/api\/fechamento$/, corpo: fechamentoEmAbas() }] },
  { rota: "fechamento", id: "fechamento-mes-aberto", caminho: "/fechamento?mes=2026-08", perfis: ["diretoria"],
    espera: ".fch-linha--obra", simular: [{ caminho: /^\/api\/fechamento$/, corpo: fechamentoEmAbas() }] },
  ...[["", "meses"], ["/comparacao", "comparacao"], ["/contratantes", "contratantes"]].map(([aba, nome]) => (
    { rota: "fechamento", id: `fechamento-${nome}-vazio`, caminho: `/fechamento${aba}`, perfis: ["diretoria"], espera: ".fch-painel .fch-vazio",
      simular: [{ caminho: /^\/api\/fechamento$/, corpo: fechamentoEmAbas({ vazio: true }) }] })),
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
    simular: [{ caminho: /^\/api\/contratos\/\d+\/cabecalho$/,
        ajustar: cabecalhoCom("suspenso", { status_desde: "2026-08-03", paralisada_desde: "2026-08-03" }) },
      { caminho: /^\/api\/contratos\/\d+\/prazos$/, ajustar: prazosParalisada }] },
  { rota: "obra", id: "obra-encerramento", caminho: "/obras/:obra/prazos", perfis: TODOS, espera: OBRA_GRADE,
    simular: [{ caminho: /^\/api\/contratos\/\d+\/cabecalho$/, ajustar: cabecalhoCom("em_encerramento", { status_desde: "2026-10-01" }) },
      { caminho: /^\/api\/contratos\/\d+\/prazos$/, ajustar: prazosEmEncerramento }] },
  // a obra encerrada sem a data do encerramento no sistema: o painel "Prazo" diz so' "encerrada"
  { rota: "obra", id: "obra-encerrada", caminho: "/obras/:obra", perfis: TODOS, espera: OBRA_GRADE,
    simular: [{ caminho: /^\/api\/contratos\/\d+\/cabecalho$/, ajustar: cabecalhoCom("encerrado", { status_desde: null }) }] },
  // #803: a obra de exemplo tem a execucao vencida e mostra "—" no necessario; aqui, a execucao em dia com o ritmo
  // abaixo do necessario (selo critico com os dias) e com o ritmo acima dele (selo "No ritmo do prazo")
  { rota: "obra", id: "obra-ritmo-abaixo", caminho: "/obras/:obra", perfis: ["diretoria"], espera: ".obra-ritmo .selo--critico",
    simular: comNecessario(false) },
  { rota: "obra", id: "obra-no-ritmo", caminho: "/obras/:obra", perfis: ["diretoria"], espera: ".obra-ritmo .selo--feito",
    simular: comNecessario(true) },
  // #822: fora da regua do andamento, o painel "Prazo" escreve o motivo (prazo no fim com a prorrogacao pedida; sem
  // medicao ha' tres competencias) e a conclusao estimada fica sem selo
  { rota: "obra", id: "obra-prazo-no-fim", caminho: "/obras/:obra", perfis: ["diretoria"], espera: ".obra-ritmo .andamento--fora",
    simular: foraDaRegua({ motivo: "prazo_no_fim", prorrogacao_pedida: true }, true) },
  { rota: "obra", id: "obra-sem-medicao", caminho: "/obras/:obra", perfis: ["diretoria"], espera: ".obra-ritmo .andamento--fora",
    simular: foraDaRegua({ motivo: "sem_medicao", sem_medicao_desde: "2026-07" }) },
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
  // issue #798: a janela "Já enviei por fora" do espelho, e o passo depois do registro (o envio por fora e a data)
  { rota: "medicao", id: "medicao-espelho-fora", caminho: MEDICAO, perfis: OPERA, antes: "nav.passos", espera: JANELA,
    simular: comEspelhoGerado, passos: [...passo("Espelhos"), { clicar: '#passo-3 button:has-text("Já enviei por fora")' }] },
  { rota: "medicao", id: "medicao-espelho-enviado-fora", caminho: MEDICAO, perfis: TODOS, antes: "nav.passos",
    espera: '#passo-3 .selo:has-text("Enviado por fora em 21/05/2025")', simular: comEspelhoEnviadoPorFora, passos: passo("Espelhos") },
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

  // ---- Menu em areas, caminho no alto e as rotas das paginas novas (#814)
  // A receber: a pagina-casca (o estado vazio), inteira e so' de um contratante; a #816 traz as notas
  { rota: "a-receber", id: "a-receber", caminho: "/a-receber", perfis: TODOS, espera: "#conteudo .vazio" },
  { rota: "a-receber", id: "a-receber-contratante", caminho: "/a-receber?contratante=SINFRA", perfis: ["diretoria"],
    espera: '#conteudo .vazio a[href="/a-receber"]' },
  // os enderecos de antes de Documentos: a aba na busca e "/documentos/certidoes" abrem a pagina do assunto
  { rota: "documentos", id: "documentos-endereco-de-antes", caminho: "/documentos?aba=garantias", destino: "/documentos/garantias",
    perfis: SO_ADMIN, espera: '#aba-garantias[aria-selected="true"]' },
  { rota: "documentos", id: "documentos-certidoes-por-extenso", caminho: "/documentos/certidoes", destino: "/documentos", perfis: SO_ADMIN,
    espera: ".doc-painel-aba" },
  // a aba do contratante ja' tem endereco; enquanto a #818 nao chega, ele abre a pagina do contratante
  { rota: "contratante", id: "contratante-aba", caminho: "/obras/contratante/sinfra/medicoes", destino: "/obras/contratante/sinfra",
    perfis: ["diretoria"], espera: ".obras-do-contratante" },
  // O menu no estado que as outras telas nao mostram: um clique no botao do pe' o recolhe no computador (so' os
  // icones, com o fio entre as areas) e o abre por cima da tela no celular (onde ele nasce recolhido). No computador a
  // escolha fica guardada no navegador: a segunda tela desfaz o clique, e as telas seguintes voltam ao menu aberto.
  // As duas ficam JUNTAS e nesta ordem.
  { rota: "inicio", id: "menu-alternado", caminho: "/inicio", perfis: TODOS, antes: ".ini", espera: "nav.menu .menu__recolher",
    passos: [{ clicar: "nav.menu .menu__recolher" }] },
  { rota: "inicio", id: "menu-de-volta", caminho: "/inicio", perfis: TODOS, antes: ".ini", espera: "nav.menu .menu__recolher",
    passos: [{ clicar: "nav.menu .menu__recolher" }] },
  // o caminho com os cinco trechos e nomes compridos (o contratante por extenso, a obra de nome longo): a barra do
  // topo quebra em linhas em vez de cortar ou de alargar a pagina
  { rota: "medicao", id: "caminho-longo", caminho: MEDICAO, perfis: TODOS, antes: "nav.passos", espera: ".topo .caminho li:nth-child(5)",
    simular: [{ caminho: /^\/api\/contratos\/\d+\/cabecalho$/, ajustar: cabecalhoDeNomeLongo }] },
  { rota: "obra", id: "caminho-longo-obra", caminho: "/obras/:obra/prazos", perfis: ["diretoria"], antes: OBRA_GRADE,
    espera: ".topo .caminho li:nth-child(4)", simular: [{ caminho: /^\/api\/contratos\/\d+\/cabecalho$/, ajustar: cabecalhoDeNomeLongo }] },
  // ---- Busca unica do topo (#819). No computador o campo esta' na barra; no celular, o botao da lupa abre o campo por
  // cima dela: o primeiro passo clica o que estiver a' vista (a lupa ou o proprio campo). Os resultados abrem por cima
  // da pagina. A diretoria entra com o servidor de verdade: o recorte do perfil e' dele, e nao ha' grupo Processos.
  { rota: "inicio", id: "busca-fechada", caminho: "/inicio", perfis: TODOS, antes: ".ini", espera: ".topo .busca" },
  { rota: "inicio", id: "busca-resultados", caminho: "/inicio", perfis: OPERA, antes: ".ini", espera: ".busca__opcao",
    simular: [{ caminho: /^\/api\/busca$/, corpo: BUSCA_CHEIA }], passos: abrirBusca("15") },
  { rota: "inicio", id: "busca-sem-resultado", caminho: "/inicio", perfis: OPERA, antes: ".ini", espera: ".busca__vazio",
    simular: [{ caminho: /^\/api\/busca$/, corpo: BUSCA_VAZIA }], passos: abrirBusca("xyzw") },
  { rota: "inicio", id: "busca-sem-siga", caminho: "/inicio", perfis: ["diretoria"], antes: ".ini", espera: ".busca__opcao",
    passos: abrirBusca("1") },
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

// ---- Tela de login (#821): os estados alem da tela parada. A prova abre cada um antes de entrar, uma vez por
// largura, preenche e-mail e senha de mentira e aperta "Entrar", com a resposta do servidor simulada.
//   id       vira o nome da captura: `login-<id>-<largura>.png`
//   simular  como nas telas; `pendurar: true` deixa o pedido sem resposta, e o botao fica em "Entrando…"
//   espera   seletor do estado ja' na tela
import { LOGIN_NO_LIMITE, LOGIN_RECUSADO } from "./simulados.mjs";

const ENTRAR = /^\/api\/auth\/login$/;
export const ESTADOS_DO_LOGIN = [
  { id: "recusa", simular: [{ metodo: "POST", caminho: ENTRAR, status: 401, corpo: LOGIN_RECUSADO }],
    espera: "form.entrar__form .aviso--falha [role=alert]" },
  { id: "limite", simular: [{ metodo: "POST", caminho: ENTRAR, status: 429, corpo: LOGIN_NO_LIMITE }],
    espera: "form.entrar__form .aviso--falha [role=alert]" },
  { id: "espera", simular: [{ metodo: "POST", caminho: ENTRAR, pendurar: true }],
    espera: 'form.entrar__form button[type="submit"]:disabled' },
];

// ---- Busca unica do topo (#819): os passos que abrem a busca e digitam a pergunta, nas tres larguras
import { BUSCA_CHEIA, BUSCA_VAZIA } from "./simulados.mjs";

function abrirBusca(texto) {
  return [{ clicar: ".topo .busca__abrir:visible, .topo .busca__campo:visible" }, { preencher: [".topo .busca__campo", texto] }];
}
