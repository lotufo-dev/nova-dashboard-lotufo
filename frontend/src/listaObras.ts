// Regras de APRESENTACAO da lista de Obras (NAVEGACAO.md › Obras): funcoes puras sobre /api/contratos (com os dias e o
// pedido de prorrogacao da mudanca A9). Os dias ate' o fim da execucao e da vigencia sao do servidor; aqui so' se
// filtra, ordena e se le o nivel dos avisos de prazo que a tela ja' carrega (nenhum limiar novo no front).

import type { Aviso, Nivel } from "./Alertas";
import { fmtDias } from "./formato";

export type ObraLista = {
  id: number; orgao: string; numero_instrumento: string; nome_curto?: string | null; estado: string;
  encerramento_iniciado_em?: string | null; entidade_id?: number | null;
  valor_vigente_centavos?: number | null; valor_vigente_execucao_centavos?: number | null; valor_reajuste_centavos?: number | null;
  execucao_fim_vigente?: string | null; vigencia_fim_vigente?: string | null;
  dias_execucao?: number | null; dias_vigencia?: number | null; vigencia_automatica?: boolean; paralisada_desde?: string | null;
  pedido_prorrogacao?: { enviado_em: string; numero_oficio: string | null; dias: number | null } | null;
  // valor cheio: o medido de execucao (atestado; protocolado ate' atestar) e o saldo a executar (vigente − medido)
  medido_execucao_centavos?: number | null; saldo_centavos?: number | null;
  // o contratante, como em Medicoes ("SINFRA" para toda a familia, com a superintendencia em `orgao_sub`)
  contratante?: string | null; orgao_sub?: string | null;
};

/** `paralisadas`: os ids das obras paralisadas (`prazoDaObra`); a execucao delas nao vence (D16). */
export type FiltroObras = {
  todas?: boolean; orgao?: string | null; termina?: number | null; q?: string | null; paralisadas?: ReadonlySet<number>;
  /** O nome da empresa de cada obra (`entidade_id`): a busca tambem acha pela empresa. */
  empresas?: ReadonlyMap<number, string> | null;
};

// "Em andamento": a obra que ainda nao foi encerrada nem rescindida (inclui a suspensa e a em encerramento).
const FORA = new Set(["encerrado", "rescindido"]);

export function nomeDaObra(o: ObraLista): string {
  return o.nome_curto || o.numero_instrumento;
}

/** Termina em ate' N dias: a execucao ou a vigencia (a que o orgao nao prorroga junto) que acaba ate' N dias a
 *  partir de hoje, incluida a que ja' venceu numa obra que nao foi encerrada (e' o caso mais grave: prazo vencido).
 *  Obra paralisada: so' a vigencia conta; o cronograma para junto com a obra (D16, Lei 14.133, art. 115, §5º). */
export function terminaEm(o: ObraLista, n: number, paralisada = false): boolean {
  const aberta = !FORA.has(o.estado);
  const dentro = (d: number | null | undefined) => d !== null && d !== undefined && d <= n && (d >= 0 || aberta);
  return (!paralisada && dentro(o.dias_execucao)) || (!o.vigencia_automatica && dentro(o.dias_vigencia));
}

/** O fim que vem primeiro (com sinal: o vencido e' negativo e fica na frente); sem prazo, no fim da lista. */
function primeiroFim(o: ObraLista, paralisada: boolean): number {
  const d = [paralisada ? null : o.dias_execucao, o.vigencia_automatica ? null : o.dias_vigencia].filter((x): x is number => x !== null && x !== undefined);
  return d.length ? Math.min(...d) : 99999;
}

/** Os avisos agrupados pela obra (`contrato_id`); o aviso sem obra fica de fora. */
export function avisosPorObra(avisos: Aviso[]): Map<number, Aviso[]> {
  const m = new Map<number, Aviso[]>();
  for (const a of avisos) if (a.contrato_id !== null) m.set(a.contrato_id, [...(m.get(a.contrato_id) ?? []), a]);
  return m;
}

/** O que a lista precisa do prazo de uma obra, tudo vindo dos avisos que a tela ja' carrega: o nivel do aviso de
 *  cada prazo (sem aviso, nulo: a nota fica neutra), quantos avisos e quantos criticos, e a paralisacao. */
export type PrazoObra = {
  execucao: Nivel | null; vigencia: Nivel | null; total: number; criticos: number;
  paralisada: boolean; paralisadaDesde: string | null;
};

const GRAVIDADE: Record<string, number> = { critico: 0, acao: 1, atencao: 2 };

/** `avisos`: os da obra. Paralisada e' o estado suspenso da propria lista ou o aviso "obra paralisada" (que traz a
 *  data em que parou). Nivel que o servidor inventar conta como atencao, como no selo dos avisos. */
export function prazoDaObra(o: ObraLista, avisos: Aviso[] = []): PrazoObra {
  const p: PrazoObra = { execucao: null, vigencia: null, total: avisos.length, criticos: 0,
    paralisada: o.estado === "suspenso", paralisadaDesde: o.paralisada_desde ?? null };
  const pior = (atual: Nivel | null, n: Nivel): Nivel => atual === null || GRAVIDADE[n] < GRAVIDADE[atual] ? n : atual;
  for (const a of avisos) {
    if (a.nivel === "critico") p.criticos += 1;
    const n: Nivel = GRAVIDADE[a.nivel] === undefined ? "atencao" : a.nivel;
    if (a.tipo === "execucao_vencendo" || a.tipo === "instrumento_pendente") p.execucao = pior(p.execucao, n);
    else if (a.tipo === "vigencia_vencendo") p.vigencia = pior(p.vigencia, n);
    else if (a.tipo === "obra_paralisada") { p.paralisada = true; p.paralisadaDesde = p.paralisadaDesde ?? a.data ?? null; }
  }
  return p;
}

/** Quando o prazo acaba, na palavra dos Avisos (`quandoDoAviso`, sentido "prazo"). */
export function quandoVence(dias: number): string {
  return dias > 0 ? `vence em ${fmtDias(dias)}` : dias === 0 ? "vence hoje" : `venceu há ${fmtDias(-dias)}`;
}

/** O nivel do selo do prazo: o do aviso da obra; sem aviso, o prazo que ja' venceu (dias < 0) vale Critico
 *  so' quando `podeCritico` (obra ativa fora do encerramento, e fora da vigencia automatica). Nos outros casos o
 *  backend nao avisa de proposito (prazos.py) e a tela nao inventa o nivel (N08-01). */
export function nivelDoPrazo(nivel: Nivel | null, dias: number | null | undefined, podeCritico = true): Nivel | null {
  return nivel === null && podeCritico && dias !== null && dias !== undefined && dias < 0 ? "critico" : nivel;
}

/** Texto do "Avisos" para o leitor de tela: a contagem, a obra e quantos sao criticos. */
export function avisosParaLeitor(p: PrazoObra, obra: string): string {
  const palavra = p.total === 1 ? "aviso" : "avisos";
  return `${p.total} ${palavra} de ${obra}${p.criticos > 0 ? `, ${p.criticos} ${p.criticos === 1 ? "crítico" : "críticos"}` : ""}`;
}

/** "3 críticos", com espaco nao separavel entre o numero e a palavra. */
export function rotuloCriticos(k: number): string {
  return `${k} ${k === 1 ? "crítico" : "críticos"}`;
}

/** Para a busca: sem acento e sem caixa ("Coxipó 2ª" e "coxipo 2a" sao a mesma coisa). */
export function paraBusca(s: string): string {
  return s.normalize("NFKD").replace(/\p{M}/gu, "").toLocaleLowerCase("pt-BR");
}

/** Os filtros da URL; na ordem do nome da obra, ou, com "termina", a que termina antes primeiro (a vencida na frente). */
export function filtrarObras(lista: ObraLista[], f: FiltroObras): ObraLista[] {
  const q = paraBusca((f.q ?? "").trim());
  const parada = (o: ObraLista) => o.estado === "suspenso" || !!f.paralisadas?.has(o.id);
  return lista.filter(o => (f.todas || !FORA.has(o.estado))
      && (!f.orgao || o.orgao === f.orgao)
      && (!f.termina || terminaEm(o, f.termina, parada(o)))
      && (!q || paraBusca(nomeDaObra(o)).includes(q) || paraBusca(o.numero_instrumento).includes(q)
        || paraBusca(o.orgao).includes(q) || paraBusca(o.contratante ?? "").includes(q) || (o.entidade_id != null && paraBusca(f.empresas?.get(o.entidade_id) ?? "").includes(q))))
    .sort((a, b) => (f.termina ? primeiroFim(a, parada(a)) - primeiroFim(b, parada(b)) : 0) || nomeDaObra(a).localeCompare(nomeDaObra(b), "pt-BR"));
}

/* --------------------------------------------------- contratantes (a entrada de Obras, redesenho #159) */

/** O valor vigente e o medido de execucao da obra, em valor cheio; o que a API nao deu conta como zero. O vigente e'
 *  o de execucao (#262): o medido e' a precos iniciais, entao o aditivo de reajuste fica fora do % e do saldo. */
const vigenteDe = (o: ObraLista) => o.valor_vigente_execucao_centavos ?? o.valor_vigente_centavos ?? 0;
const medidoDe = (o: ObraLista) => o.medido_execucao_centavos ?? 0;

/** Quanto da obra ja' foi executado, em %, inteiro: medido de execucao ÷ valor vigente. Sem valor vigente, nulo. */
export function pctExecutado(o: ObraLista): number | null {
  const v = vigenteDe(o);
  return v > 0 ? Math.round((medidoDe(o) * 100) / v) : null;
}

export type ResumoContratante = {
  obras: number; encerradas: number; vigente: number; medido: number; saldo: number; pct: number;
  comAviso: number; criticos: number; nivelMax: Nivel | null;
};

/** O resumo de um grupo de obras: so' as em andamento (nem encerradas nem rescindidas) entram nos numeros; as
 *  encerradas (e rescindidas) sao so' contadas. O saldo e' vigente − medido somados, entao a linha "Todas as obras" e' a soma das
 *  linhas dos contratantes. `criticos`: avisos criticos; `comAviso`: obras com algum aviso. */
export function resumoContratante(obras: ObraLista[], avisos: ReadonlyMap<number, Aviso[]> | null = null): ResumoContratante {
  const ativas = obras.filter(o => !FORA.has(o.estado));
  const r: ResumoContratante = { obras: ativas.length, encerradas: obras.filter(o => FORA.has(o.estado)).length,
    vigente: 0, medido: 0, saldo: 0, pct: 0, comAviso: 0, criticos: 0, nivelMax: null };
  for (const o of ativas) {
    r.vigente += vigenteDe(o); r.medido += medidoDe(o); r.saldo += vigenteDe(o) - medidoDe(o);
    const av = avisos?.get(o.id) ?? [];
    if (av.length) r.comAviso += 1;
    for (const a of av) {
      if (a.nivel === "critico") r.criticos += 1;
      const n: Nivel = GRAVIDADE[a.nivel] === undefined ? "atencao" : a.nivel;
      if (r.nivelMax === null || GRAVIDADE[n] < GRAVIDADE[r.nivelMax]) r.nivelMax = n;
    }
  }
  r.pct = r.vigente > 0 ? Math.round((r.medido * 100) / r.vigente) : 0;
  return r;
}

/** O contratante da obra: a sigla do orgao do cadastro, a mesma de Medicoes ("SINFRA" para a familia toda); sem ela,
 *  o nome do orgao. */
export const contratanteDaObra = (o: ObraLista) => o.contratante || o.orgao;

/** A obra e' do contratante `nome`? O link de antes (`?orgao=SINFRA - SUEF II`) traz o nome inteiro do orgao: vale. */
export const ehDoContratante = (o: ObraLista, nome: string) => contratanteDaObra(o) === nome || o.orgao === nome;

/** Os contratantes que tem obra, na ordem do nome. */
export function contratantesDe(lista: ObraLista[]): string[] {
  return [...new Set(lista.map(contratanteDaObra))].sort((a, b) => a.localeCompare(b, "pt-BR"));
}

/** O contratante da URL: `?c=todas` e' "Todas as obras" (sem recorte de orgao); `?c=<orgao>` (ou o `?orgao=` dos
 *  links de antes) e' um orgao. Sem `c`, a pagina e' a escolha do contratante, a menos que haja um filtro de antes
 *  (`?termina=`, `?q=`, `?situacao=`): esses links abrem a lista de todas as obras, como abriam, e a tela poe `c`
 *  na URL (`cDaUrlAntiga`) para que limpar o ultimo filtro nao volte a escolha. */
export function escopoDaUrl(busca: Record<string, string>): { escolha: boolean; orgao: string | null } {
  const c = busca.c ?? busca.orgao ?? "";
  if (c && c !== "todas") return { escolha: false, orgao: c };
  const antigo = ["termina", "q", "situacao", "ver", "avisos"].some(k => busca[k] !== undefined);
  return { escolha: !c && !antigo, orgao: null };
}

/** O `c` que um link de antes ainda nao tem: `?orgao=X` vira `?c=X` e os filtros soltos (`?termina=`, `?q=`...) viram
 *  `?c=todas`. Nulo quando a URL ja' esta' no formato novo (ou e' a escolha do contratante). */
export function cDaUrlAntiga(busca: Record<string, string>): string | null {
  if (busca.c !== undefined) return null;
  if (busca.orgao) return busca.orgao;
  return ["termina", "q", "situacao", "ver", "avisos"].some(k => busca[k] !== undefined) ? "todas" : null;
}

/** O aviso mais grave da obra, para a linha do cartao. */
export function avisoPrincipal(avisos: Aviso[]): Aviso | null {
  let melhor: Aviso | null = null;
  for (const a of avisos) {
    const g = GRAVIDADE[a.nivel] ?? GRAVIDADE.atencao;
    if (melhor === null || g < (GRAVIDADE[melhor.nivel] ?? GRAVIDADE.atencao)) melhor = a;
  }
  return melhor;
}
