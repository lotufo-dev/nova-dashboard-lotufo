import { useEffect, useMemo, useSyncExternalStore } from "react";
import { confirmarSaida, haRascunho } from "./rascunho";

// Roteador da casa (fase 3,5; casca do mapa aprovado em NAVEGACAO.md): URL por tela, objeto e aba, com os
// filtros na busca (?obra=7) e a secao na ancora (#notas), sem dependencia nova.
//
// Antes disto a tela vivia num useState: F5 voltava a home, "Voltar" saia do app, e nao havia link para
// mandar por e-mail ("olha a 12ª medicao do IC 82"). O roteador e' um `history.pushState` + `popstate` em
// cima de UM tipo de dado (`Rota`), e o resto do app continua raciocinando em telas, nao em strings.
//
// Regras:
// - `parseRota` e' TOTAL: qualquer caminho vira uma Rota (o desconhecido vira `raiz`, que o App troca
//   pela entrada do perfil com replaceState, sem empilhar historico).
// - `caminhoDe` e' o inverso: toda Rota tem exatamente um caminho canonico. Caminho antigo (/contratos,
//   /diretoria, /certidoes...) continua abrindo: `parseRota` o le e o App troca a URL pela canonica.
// - Filtro que muda por controle (select, busca) troca a URL no lugar (`trocarBusca`): Voltar sai da tela
//   em vez de desfazer filtro por filtro, e volta a ela com os filtros que ela tinha.
// - Caminho novo entra AQUI, nas duas funcoes e no teste; nada mais no app monta string de URL a mao.

// Abas da obra (NAVEGACAO.md › Obra). As notas moram na pagina de cada medicao.
export type AbaObra = "medicoes" | "prazos" | "reajuste" | "documentos" | "contrato";
// Abas da Carteira (NAVEGACAO.md › Carteira). O Resumo e' a padrao e nao entra na URL.
export type AbaCarteira = "resumo" | "qdop" | "producao";
// Abas da Administracao (NAVEGACAO.md › Administracao). A Saude e' a padrao e nao entra na URL.
export type AbaAdmin = "saude" | "reconciliacao" | "usuarios" | "auditoria";
// Abas de Medicoes (09/10/2026, prototipo aprovado): o Resumo e' a padrao e nao entra na URL; as outras sao as
// situacoes do ciclo. "Enviar nota" e "Aguardando pagamento" eram as telas Notas › A enviar e Aguardando pagamento.
export type AbaMedicoes = "resumo" | "sem-medicao" | "planilha-gerada" | "planilha-enviada" | "boletim-recebido" | "faturamento" | "aguardando-nota" | "enviar-nota" | "aguardando-pagamento";

// Abas da pagina da empresa em Documentos (#161). As Certidoes sao a padrao e nao entram na URL.
export type AbaDocumentos = "certidoes" | "regularidade" | "garantia";

export type Rota =
  | { tela: "raiz" }
  | { tela: "inicio" }
  | { tela: "medicoes"; aba?: AbaMedicoes }
  | { tela: "avisos" }
  | { tela: "documentos" }
  | { tela: "documentos-empresa"; id: number; aba?: AbaDocumentos }
  | { tela: "obras" }
  | { tela: "a-receber" }
  | { tela: "notas-envio"; id: number }
  | { tela: "obra"; id: number; aba: AbaObra }
  | { tela: "medicao"; obra: number; id: number }
  | { tela: "nova-medicao"; obra: number }
  | { tela: "carteira"; aba?: AbaCarteira }
  | { tela: "admin"; aba?: AbaAdmin }
  | { tela: "conta" };

/** Filtros da tela, na busca da URL: `{ termina: "90" }` e' `?termina=90`. */
export type Busca = Record<string, string>;

/** De onde se chegou a um detalhe (obra): o "← Medicoes" do topo volta para la', com os filtros. */
export type Origem = { tela: Rota["tela"]; href: string };
type EstadoHistorico = { origem?: Origem };

const ABAS: readonly AbaObra[] = ["medicoes", "prazos", "reajuste", "documentos", "contrato"];
const ABAS_DOCUMENTOS: readonly AbaDocumentos[] = ["certidoes", "regularidade", "garantia"];
const ABAS_CARTEIRA: readonly AbaCarteira[] = ["resumo", "qdop", "producao"];
const ABAS_ADMIN: readonly AbaAdmin[] = ["saude", "reconciliacao", "usuarios", "auditoria"];
const ABAS_MEDICOES: readonly AbaMedicoes[] = ["resumo", "sem-medicao", "planilha-gerada", "planilha-enviada", "boletim-recebido", "faturamento", "aguardando-nota", "enviar-nota",
  "aguardando-pagamento"];
// Links antigos (e-mails, favoritos) continuam abrindo a secao que absorveu a aba.
// A aba Notas saiu (mapa de 2026-09-28): as notas estao na medicao e na coluna Notas das medicoes da obra.
const ABA_ANTIGA: Record<string, AbaObra> = { protocolo: "medicoes", notas: "medicoes", cronograma: "contrato", aditivos: "contrato" };

// Telas de um segmento so' ("/medicoes"), sem parametro, e os nomes antigos de cada uma.
// Bloco 9: "/engenharia" e "/sugestoes" sairam; por nao estarem aqui, caem na raiz (entrada do perfil).
const SIMPLES = ["inicio", "medicoes", "avisos", "documentos", "obras", "a-receber", "carteira", "admin", "conta"] as const;
type Simples = (typeof SIMPLES)[number];
const SIMPLES_ANTIGAS: Record<string, Simples> = {
  certidoes: "documentos",   // bloco 4: Certidoes virou Documentos de protocolo
  painel: "carteira",        // bloco 8: o Painel geral virou a tela da Diretoria
  diretoria: "carteira",     // mapa de 2026-09-28: a Diretoria virou a Carteira
  contratos: "obras",        // mapa de 2026-09-28: a URL diz o que o menu diz
};

function ehSimples(s: string): s is Simples {
  return (SIMPLES as readonly string[]).includes(s);
}

function ehAba(s: string): s is AbaObra {
  return (ABAS as readonly string[]).includes(s);
}

function ehAbaDocumentos(s: string): s is AbaDocumentos {
  return (ABAS_DOCUMENTOS as readonly string[]).includes(s);
}

function ehAbaCarteira(s: string): s is AbaCarteira {
  return (ABAS_CARTEIRA as readonly string[]).includes(s);
}

function ehAbaAdmin(s: string): s is AbaAdmin {
  return (ABAS_ADMIN as readonly string[]).includes(s);
}

function ehAbaMedicoes(s: string): s is AbaMedicoes {
  return (ABAS_MEDICOES as readonly string[]).includes(s);
}

function ehId(s: string): boolean {
  return /^[1-9][0-9]{0,14}$/.test(s);
}

export function parseRota(pathname: string): Rota {
  const partes = pathname.split("/").filter(p => p !== "");
  if (partes.length === 0) return { tela: "raiz" };
  const [a, b, c] = partes;
  if (partes.length === 1 && ehSimples(a)) return { tela: a };
  if (partes.length === 1 && Object.prototype.hasOwnProperty.call(SIMPLES_ANTIGAS, a)) return { tela: SIMPLES_ANTIGAS[a] };
  if ((a === "obras" || a === "contratos") && b !== undefined) {
    // So' inteiro positivo em decimal: "/obras/abc" e "/obras/1e3" nao sao obras, sao caminhos
    // desconhecidos. Number("") seria 0 e passaria sem isto. Ate' 15 digitos: cabe no inteiro seguro do
    // JS (2^53), entao o id nunca e' arredondado para OUTRA obra ao virar number.
    if (!ehId(b)) return { tela: "raiz" };
    const id = Number(b);
    if (c === undefined) return { tela: "obra", id, aba: "medicoes" };
    // A medicao tem pagina propria, dentro da obra (NAVEGACAO.md › Arvore de telas).
    if (c === "medicoes" && partes.length === 4 && ehId(partes[3])) return { tela: "medicao", obra: id, id: Number(partes[3]) };
    // Nova medicao (2026-10-09): a etapa 1 (espelho) antes de a medicao existir.
    if (c === "medicoes" && partes.length === 4 && partes[3] === "nova") return { tela: "nova-medicao", obra: id };
    if (partes.length === 3 && Object.prototype.hasOwnProperty.call(ABA_ANTIGA, c)) {
      return { tela: "obra", id, aba: ABA_ANTIGA[c] };
    }
    if (partes.length === 3 && ehAba(c)) return { tela: "obra", id, aba: c };
  }
  // A Carteira e a Administracao tem abas; a padrao ("/carteira/resumo", "/admin/saude") vira a forma canonica
  // ("/carteira", "/admin"), que o App poe na URL.
  // Notas (2026-10-09): a lista e as que aguardam pagamento viraram abas de Medicoes (09/10/2026); os links antigos
  // ("/notas", "/notas/aguardando", com os filtros) abrem a aba e o App troca a URL pela canonica. O envio de um
  // protocolo continua com caminho proprio.
  if (a === "notas" && partes.length === 1) return { tela: "medicoes", aba: "enviar-nota" };
  if (a === "notas" && partes.length === 2 && b === "aguardando") return { tela: "medicoes", aba: "aguardando-pagamento" };
  if (a === "notas" && partes.length === 3 && b === "envio" && ehId(c)) return { tela: "notas-envio", id: Number(c) };
  if (a === "medicoes" && partes.length === 2 && ehAbaMedicoes(b)) return b === "resumo" ? { tela: "medicoes" } : { tela: "medicoes", aba: b };
  // A empresa em Documentos (#161): "/documentos/3" e as outras abas; a padrao vira a forma canonica.
  if (a === "documentos" && b !== undefined && ehId(b) && partes.length <= 3) {
    if (partes.length === 2) return { tela: "documentos-empresa", id: Number(b) };
    if (ehAbaDocumentos(c)) return c === "certidoes" ? { tela: "documentos-empresa", id: Number(b) } : { tela: "documentos-empresa", id: Number(b), aba: c };
  }
  if (a === "carteira" && partes.length === 2 && ehAbaCarteira(b)) return b === "resumo" ? { tela: "carteira" } : { tela: "carteira", aba: b };
  if (a === "admin" && partes.length === 2 && ehAbaAdmin(b)) return b === "saude" ? { tela: "admin" } : { tela: "admin", aba: b };
  return { tela: "raiz" };
}

export function caminhoDe(r: Rota): string {
  switch (r.tela) {
    case "raiz": return "/";
    case "obra":
      // A aba padrao NAO entra na URL: "/obras/7" e "/obras/7/medicoes" sao a mesma pagina, e uma so'
      // forma canonica evita dois historicos para um lugar.
      return r.aba === "medicoes" ? `/obras/${r.id}` : `/obras/${r.id}/${r.aba}`;
    case "medicao": return `/obras/${r.obra}/medicoes/${r.id}`;
    case "nova-medicao": return `/obras/${r.obra}/medicoes/nova`;
    case "documentos-empresa": return r.aba && r.aba !== "certidoes" ? `/documentos/${r.id}/${r.aba}` : `/documentos/${r.id}`;
    case "carteira": return r.aba && r.aba !== "resumo" ? `/carteira/${r.aba}` : "/carteira";
    case "admin": return r.aba && r.aba !== "saude" ? `/admin/${r.aba}` : "/admin";
    case "medicoes": return r.aba && r.aba !== "resumo" ? `/medicoes/${r.aba}` : "/medicoes";
    case "notas-envio": return `/notas/envio/${r.id}`;
    default: return `/${r.tela}`;
  }
}

/** Endereco completo: caminho, filtros (vazios nao entram) e secao. */
export function hrefDe(r: Rota, busca?: Busca, secao?: string): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(busca ?? {})) if (v !== "") q.set(k, v);
  const s = q.toString();
  return `${caminhoDe(r)}${s ? `?${s}` : ""}${secao ? `#${secao}` : ""}`;
}

/** Detalhe = tela de UM objeto, com breadcrumb e "← origem" (a obra e a medicao dela, a empresa em Documentos). */
export function ehDetalhe(r: Rota): boolean {
  return r.tela === "obra" || r.tela === "medicao" || r.tela === "nova-medicao" || r.tela === "documentos-empresa";
}

/** A origem que um detalhe guarda: a tela de onde se veio; dentro do mesmo detalhe (trocar de aba), a
 *  que ele ja' tinha. Tela sem origem (raiz) ou navegacao pelo menu nao guardam nada. */
export function origemPara(de: Rota, deHref: string, para: Rota, anterior: Origem | undefined): Origem | undefined {
  if (!ehDetalhe(para)) return undefined;
  if (ehDetalhe(de)) return anterior;
  if (de.tela === "raiz") return undefined;
  return { tela: de.tela, href: deHref };
}

/* ------------------------------------------------------------ estado da URL */

type Local = { caminho: string; busca: string; secao: string; origem: Origem | null; chave: string };

function chaveAtual(): string {
  return `${window.location.pathname}${window.location.search}${window.location.hash}|${JSON.stringify(window.history.state ?? null)}`;
}

function ler(): Local {
  const estado = (window.history.state ?? null) as EstadoHistorico | null;
  return { caminho: window.location.pathname, busca: window.location.search,
    secao: decodeURIComponent(window.location.hash.replace(/^#/, "")), origem: estado?.origem ?? null, chave: chaveAtual() };
}

let local: Local | null = null;
const ouvintes = new Set<() => void>();

// Onde se estava antes do ultimo movimento: o Voltar do navegador ja' trocou a URL quando o popstate chega, entao
// recusar a saida (rascunho) e' repor este endereco.
let ultimo: { href: string; estado: unknown } | null = null;

function marcarUltimo() {
  ultimo = { href: `${window.location.pathname}${window.location.search}${window.location.hash}`, estado: window.history.state ?? null };
}

function avisar() {
  local = ler();
  marcarUltimo();
  for (const f of ouvintes) f();
}

function aoVoltar() {
  const anterior = ultimo;
  if (anterior && haRascunho() && window.location.pathname !== anterior.href.split(/[?#]/)[0] && !confirmarSaida()) {
    window.history.pushState(anterior.estado, "", anterior.href);
    return;
  }
  avisar();
}

function assinar(f: () => void) {
  if (ouvintes.size === 0) { marcarUltimo(); window.addEventListener("popstate", aoVoltar); }
  ouvintes.add(f);
  return () => {
    ouvintes.delete(f);
    if (ouvintes.size === 0) window.removeEventListener("popstate", aoVoltar);
  };
}

// O instantaneo so' muda quando a URL ou o estado mudam: o useSyncExternalStore compara por identidade.
function instantaneo(): Local {
  if (local === null || local.chave !== chaveAtual()) local = ler();
  return local;
}

/** `forcar`: a navegacao e' o desfecho de uma acao concluida (gerou, enviou, descartou): nao pergunta pelo rascunho. */
export type OpcoesIr = { busca?: Busca; secao?: string; menu?: boolean; forcar?: boolean };
/** Assinatura de `ir`, para as telas que recebem a navegacao por prop (e os testes, que passam um vazio). */
export type Ir = (destino: Rota, opcoes?: OpcoesIr) => void;

/** Leva a uma tela, empilhando historico (Voltar funciona). Clicar no lugar em que ja' se esta' nao
 *  empilha uma copia: dois "Voltar" para sair de um lugar clicado duas vezes ensinam a nao confiar no botao. */
export function ir(destino: Rota, opcoes: OpcoesIr = {}) {
  const href = hrefDe(destino, opcoes.busca, opcoes.secao);
  const aqui = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  // Ja' se esta' no endereco: com secao, leva de novo ate' ela (a pessoa rolou para longe e clicou o link
  // da secao outra vez); sem secao, nao empilha copia.
  if (href === aqui) { if (opcoes.secao) irParaSecao(opcoes.secao); return; }
  const de = parseRota(window.location.pathname);
  const outroCaminho = caminhoDe(destino) !== window.location.pathname;
  // Trocar de tela com formulario sujo pede confirmacao; filtro e secao da mesma tela nao.
  if (outroCaminho && !opcoes.forcar && !confirmarSaida()) return;
  const anterior = ((window.history.state ?? null) as EstadoHistorico | null)?.origem;
  const origem = opcoes.menu ? undefined
    : origemPara(de, `${window.location.pathname}${window.location.search}`, destino, anterior);
  window.history.pushState(origem ? { origem } : null, "", href);
  // Tela (ou aba) nova comeca do topo; com secao, quem rola e' o App (a secao so' existe depois dos dados).
  if (!opcoes.secao && outroCaminho) window.scrollTo({ top: 0, behavior: "instant" });
  avisar();
}

/** Leva a um endereco guardado (a origem de um detalhe), com os filtros que ele tinha. */
export function irHref(href: string) {
  const u = new URL(href, window.location.origin);
  ir(parseRota(u.pathname), { busca: Object.fromEntries(u.searchParams), secao: u.hash.replace(/^#/, "") || undefined });
}

/** Troca a tela no lugar, mantendo filtros, secao e origem (redirect de rota antiga, raiz -> entrada). Opcoes:
 *  `busca`: os filtros passam a ser esses (a rota antiga que muda de dono, como Avisos dentro de Obras);
 *  `secao`: a ancora passa a ser essa (o endereco antigo que cai numa etapa da medicao);
 *  `semBusca`: o destino nao leva os filtros do endereco de antes. */
export type OpcoesSubstituir = { busca?: Busca; secao?: string; semBusca?: boolean };
export function substituir(destino: Rota, opcoes: OpcoesSubstituir = {}) {
  const q = opcoes.busca ? new URLSearchParams(opcoes.busca).toString()
    : opcoes.semBusca ? "" : window.location.search.replace(/^\?/, "");
  const hash = opcoes.secao !== undefined ? `#${opcoes.secao}` : opcoes.semBusca ? "" : window.location.hash;
  window.history.replaceState(window.history.state, "", `${caminhoDe(destino)}${q ? `?${q}` : ""}${hash}`);
  avisar();
}

/** Os filtros com que a rota antiga /avisos abre no lugar novo: os Avisos dentro de Obras, de todas as obras, com os
 *  filtros que o link tinha (?familia= ?nivel= ?obra= ?agrupar=). */
export function buscaDosAvisosEmObras(busca: Busca): Busca {
  return { c: "todas", avisos: "1", ...busca };
}

/** Muda filtros da tela no lugar: `null` ou "" tira o filtro da URL. */
export function trocarBusca(mudancas: Record<string, string | null>) {
  const q = new URLSearchParams(window.location.search);
  for (const [k, v] of Object.entries(mudancas)) {
    if (v === null || v === "") q.delete(k); else q.set(k, v);
  }
  const s = q.toString();
  window.history.replaceState(window.history.state, "", `${window.location.pathname}${s ? `?${s}` : ""}${window.location.hash}`);
  avisar();
}

/** Rota corrente, filtros, secao e origem, e as funcoes de navegacao. */
export function useRota() {
  const l = useSyncExternalStore(assinar, instantaneo);
  const rota = useMemo(() => parseRota(l.caminho), [l.caminho]);
  const busca = useMemo<Busca>(() => Object.fromEntries(new URLSearchParams(l.busca)), [l.busca]);
  return { rota, busca, secao: l.secao, origem: l.origem, ir, substituir, trocarBusca, irHref };
}

/** Rola ate' a secao e poe o foco nela (quem navega por teclado continua dali, como numa ancora comum). */
function irParaSecao(id: string, focar = true): boolean {
  const el = document.getElementById(id);
  if (!el) return false;
  el.scrollIntoView({ block: "start" });
  if (focar) {
    if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
    el.focus({ preventScroll: true });
  }
  return true;
}

/** Leva a pagina ate' a secao da ancora (#notas, #emp-3) quando ela aparecer: a secao so' existe depois
 *  que os dados da tela chegam, e o que carrega acima dela ainda a empurra por um instante. Enquanto a
 *  tela assenta (ate' 2 s depois de achar), a pagina acompanha a secao; se a pessoa rolar, para de mexer. */
export function useRolarAteSecao(secao: string, chave: string) {
  useEffect(() => {
    if (!secao) return;
    let achouEm = 0;
    let parou = false;
    const parar = () => { parou = true; };
    const tentar = () => {
      if (parou) return;
      // o foco vai a secao uma vez, quando ela aparece; depois a pagina so' acompanha o que carrega acima
      if (!irParaSecao(secao, !achouEm)) return;
      if (!achouEm) achouEm = Date.now();
    };
    tentar();
    const obs = new MutationObserver(() => {
      tentar();
      if (achouEm && Date.now() - achouEm > 2000) obs.disconnect();
    });
    obs.observe(document.body, { childList: true, subtree: true });
    const limite = window.setTimeout(() => obs.disconnect(), 10000);
    for (const ev of ["wheel", "touchstart", "keydown", "mousedown"]) window.addEventListener(ev, parar, { passive: true });
    return () => {
      obs.disconnect();
      window.clearTimeout(limite);
      for (const ev of ["wheel", "touchstart", "keydown", "mousedown"]) window.removeEventListener(ev, parar);
    };
  }, [secao, chave]);
}

/** Clique "normal" (botao esquerdo, sem modificador): o unico que o roteador intercepta.
 *  Ctrl/Cmd+clique e botao do meio seguem para o navegador abrir em outra aba — e' para isso que os
 *  links sao <a href> de verdade, e nao botoes. */
export function cliqueSimples(ev: React.MouseEvent): boolean {
  return ev.button === 0 && !ev.metaKey && !ev.ctrlKey && !ev.shiftKey && !ev.altKey
    && !ev.defaultPrevented;
}
