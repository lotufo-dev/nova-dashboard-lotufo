// Regras de APRESENTACAO da lista de Obras (NAVEGACAO.md › Obras): funcoes puras sobre /api/contratos (com os dias e o
// pedido de prorrogacao da mudanca A9). Os dias ate' o fim da execucao e da vigencia sao do servidor; aqui so' se
// filtra, ordena e se le o nivel dos avisos de prazo que a tela ja' carrega (nenhum limiar novo no front).

import type { Aviso, Nivel } from "./Alertas";
import { fmtDias, fmtPercentual } from "./formato";
import { fmtDataPura, fmtMesCurto, fmtMesExtenso } from "./tempo";
import { andamento, type AndamentoDoServidor } from "./valores";

export type ObraLista = {
  id: number; orgao: string; numero_instrumento: string; nome_curto?: string | null; estado: string;
  encerramento_iniciado_em?: string | null; entidade_id?: number | null;
  valor_vigente_centavos?: number | null; valor_vigente_execucao_centavos?: number | null; valor_reajuste_centavos?: number | null;
  execucao_fim_vigente?: string | null; vigencia_fim_vigente?: string | null;
  dias_execucao?: number | null; dias_vigencia?: number | null; vigencia_automatica?: boolean; paralisada_desde?: string | null;
  pedido_prorrogacao?: { enviado_em: string; numero_oficio: string | null; dias: number | null } | null;
  // valor cheio: o medido, execucao e projeto (#742; atestado, protocolado ate' atestar), e o saldo a executar
  // (vigente − medido)
  medido_centavos?: number | null; saldo_centavos?: number | null;
  // o contratante, como em Medicoes ("SINFRA" para toda a familia, com a superintendencia em `orgao_sub`)
  contratante?: string | null; orgao_sub?: string | null;
  // a cota da Lotufo (10000 = 100%)
  percentual_direito_bp?: number | null;
  // #645: o que a lista de Obras mostra, ja' NA COTA da Lotufo e na base de execucao, pela conta do topo da pagina da
  // obra (servidor); o a receber e' nulo ate' o total ser liberado
  posicao?: PosicaoObra | null;
  // #805 (Obras por contratante), tudo do servidor e na cota: a chave da pagina do contratante (nula no contrato sem
  // orgao no cadastro); o ritmo e o necessario por mes, pela conta do painel "Prazo" da pagina da obra, com a
  // `leitura` do andamento ja' feita (#822: a mesma da pagina da obra); e o medido da ultima competencia fechada com
  // o da anterior, o mesmo numero do Fechamento
  contratante_chave?: string | null;
  andamento?: { ritmo_centavos: number | null; necessario_centavos: number | null; leitura?: AndamentoDoServidor | null } | null;
  medido_mes?: MedidoMes | null;
};

/** O medido de uma competencia fechada e a referencia da variacao (a competencia anterior); sem referencia que sirva
 *  (anterior ao primeiro ano que as telas contam), os dois campos dela vem nulos. */
export type MedidoMes = { competencia: string; valor_centavos: number; referencia_competencia: string | null; referencia_centavos: number | null };

// 17/11/2026 (docs/adr/0006): `a_receber_centavos` soma so' a competencia de `a_receber_ano_inicial` em diante que o RM ainda
// informa; o anterior e a nota sem atualizacao do RM vem a' parte, fora do total (nulos ate' o total ser liberado)
export type PosicaoObra = { vigente_centavos: number; medido_centavos: number; saldo_centavos: number; a_receber_centavos: number | null;
  a_receber_ano_inicial?: string; a_receber_anterior_centavos?: number | null; a_receber_sem_atualizacao_centavos?: number | null };

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

/** O valor vigente e o medido da obra (execucao e projeto, #742), em valor cheio; o que a API nao deu conta como zero.
 *  O vigente e' o de execucao (#262): o medido e' a precos iniciais, entao o aditivo de reajuste fica fora do % e do saldo. */
export const vigenteDe = (o: ObraLista) => o.valor_vigente_execucao_centavos ?? o.valor_vigente_centavos ?? 0;
export const medidoDe = (o: ObraLista) => o.medido_centavos ?? 0;

/** A posicao da obra na cota da Lotufo (#645), como o servidor mandou; o que ele nao deu conta como zero. */
export function posicaoDe(o: ObraLista): PosicaoObra {
  return o.posicao ?? { vigente_centavos: 0, medido_centavos: 0, saldo_centavos: 0, a_receber_centavos: null };
}

export type TotaisObras = { contratado: number; medido: number; saldo: number; aReceber: number; temReceber: boolean;
  // o a receber que fica fora do total (docs/adr/0006): o de competencia anterior e o sem atualizacao do RM
  aReceberAnterior: number; aReceberSemAtualizacao: number; anoInicial: string | null };

/** Os totais (do topo ou de um contratante), somados sobre as linhas que a tabela mostra, ja' na cota: so' soma, nenhum
 *  arredondamento novo. O a receber so' tem valor com o total liberado (todas as obras com nulo): nulo vira "—", nunca zero. */
export function totaisDe(obras: ObraLista[]): TotaisObras {
  const t: TotaisObras = { contratado: 0, medido: 0, saldo: 0, aReceber: 0, temReceber: false,
    aReceberAnterior: 0, aReceberSemAtualizacao: 0, anoInicial: null };
  for (const o of obras) {
    const p = posicaoDe(o);
    t.contratado += p.vigente_centavos; t.medido += p.medido_centavos; t.saldo += p.saldo_centavos;
    if (p.a_receber_centavos != null) { t.aReceber += p.a_receber_centavos; t.temReceber = true; }
    t.aReceberAnterior += p.a_receber_anterior_centavos ?? 0;
    t.aReceberSemAtualizacao += p.a_receber_sem_atualizacao_centavos ?? 0;
    t.anoInicial = p.a_receber_ano_inicial ?? t.anoInicial;
  }
  return t;
}

/** Percentual inteiro por PISO: 99,6% e' 99%, nunca 100%. So' mostra 100% quem concluiu (#779). Sem base, nulo. */
export function pctPiso(parte: number, base: number): number | null {
  return base > 0 ? Math.floor((parte * 100) / base) : null;
}

/** Quanto da obra ja' foi executado, em %, inteiro (por piso): medido (execucao e projeto) ÷ valor vigente (da posicao na cota quando a
 *  lista a traz; a razao e' a mesma do cheio). Sem valor vigente, nulo. */
export function pctExecutado(o: ObraLista): number | null {
  const v = o.posicao ? o.posicao.vigente_centavos : vigenteDe(o);
  const m = o.posicao ? o.posicao.medido_centavos : medidoDe(o);
  return pctPiso(m, v);
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

/** As obras agrupadas pelo contratante (#645), os grupos na ordem do nome do contratante e as obras de cada um na ordem
 *  do nome, com o subtotal do grupo (`totaisDe`). */
export function gruposPorContratante(obras: ObraLista[]): GrupoDeObras[] {
  return contratantesDe(obras).map(contratante => {
    const doGrupo = obras.filter(o => contratanteDaObra(o) === contratante)
      .sort((a, b) => nomeDaObra(a).localeCompare(nomeDaObra(b), "pt-BR"));
    return { contratante, chave: doGrupo.find(o => o.contratante_chave)?.contratante_chave ?? null, obras: doGrupo, subtotal: totaisDe(doGrupo) };
  });
}

/** `chave`: a da pagina do contratante (`contratante_chave` do servidor); nula no grupo sem orgao no cadastro. */
export type GrupoDeObras = { contratante: string; chave: string | null; obras: ObraLista[]; subtotal: TotaisObras };

/* --------------------------------------------------- andamento e o que pede atencao (#805) */

/** A leitura do andamento da obra (Adiantada, Atencao, Devagar) e o percentual do necessario, como o SERVIDOR os
 *  mandou em `andamento.leitura` (#822): a mesma da peca `Andamento` e da pagina da obra, para a contagem "N obras
 *  devagar" nunca discordar da barra desenhada. A tela nao compara o ritmo com o necessario.
 *  Nula na obra sem leitura: sem necessario (sem prazo a cumprir: parada, vencida, em encerramento, sem saldo), sem
 *  ritmo, ou fora da regua (prazo no fim, prorrogacao pedida, sem medicao ha' tres competencias). */
export const andamentoDaObra = (o: ObraLista) => andamento(o.andamento?.leitura);
/** O que `andamentoDaObra` devolve quando a leitura existe: a palavra e o percentual do necessario. */
export type LeituraDaObra = NonNullable<ReturnType<typeof andamentoDaObra>>;

/** Obra paralisada: o estado suspenso ou a ordem de paralisacao em vigor (`paralisada_desde`, do servidor). */
export const estaParalisada = (o: ObraLista) => o.estado === "suspenso" || !!o.paralisada_desde;

/** Execucao vencida que conta: so' na obra ativa, fora do encerramento e sem paralisacao, como o servidor decide o
 *  nivel do prazo (`prazos._niveis`); os dias sao dele (nulos quando o prazo de execucao nao e' conhecido, #662). */
export function execucaoVencida(o: ObraLista): boolean {
  return o.estado === "ativo" && !o.encerramento_iniciado_em && !estaParalisada(o)
    && o.dias_execucao !== null && o.dias_execucao !== undefined && o.dias_execucao < 0;
}

/** Quantos avisos criticos cada obra tem, dos avisos da diretoria (`/api/diretoria`, os mesmos do farol). */
export function criticosPorObra(avisos: { contrato_id: number | null; nivel: string }[]): Map<number, number> {
  const m = new Map<number, number>();
  for (const a of avisos) if (a.contrato_id !== null && a.nivel === "critico") m.set(a.contrato_id, (m.get(a.contrato_id) ?? 0) + 1);
  return m;
}

/** O medido do mes fechado de um conjunto de obras: a soma do que o servidor mandou em cada uma (so' soma). Sem
 *  nenhuma obra com o dado, nulo; a referencia so' soma quando o servidor a manda. */
export function medidoDoMes(obras: ObraLista[]): MedidoMes | null {
  const com = obras.map(o => o.medido_mes).filter((m): m is MedidoMes => !!m);
  if (com.length === 0) return null;
  const { competencia, referencia_competencia } = com[0];
  return { competencia, valor_centavos: com.reduce((t, m) => t + m.valor_centavos, 0), referencia_competencia,
    referencia_centavos: referencia_competencia === null ? null : com.reduce((t, m) => t + (m.referencia_centavos ?? 0), 0) };
}

/** Os nomes do mes do medido ("outubro", "out") e da referencia da variacao ("set", "setembro"; de outro ano, com o
 *  ano: "dez/25", "dezembro de 2025"). Sem referencia que sirva, nula. */
export function mesesDoMedido(mm: MedidoMes): { extenso: string; curto: string; referencia: { curto: string; extenso: string } | null } {
  const ref = mm.referencia_competencia;
  const mesmoAno = ref !== null && ref.slice(0, 4) === mm.competencia.slice(0, 4);
  return {
    extenso: fmtMesExtenso(mm.competencia), curto: fmtMesCurto(mm.competencia).split("/")[0],
    referencia: ref === null ? null : {
      curto: mesmoAno ? fmtMesCurto(ref).split("/")[0] : fmtMesCurto(ref),
      extenso: mesmoAno ? fmtMesExtenso(ref) : `${fmtMesExtenso(ref)} de ${ref.slice(0, 4)}`,
    },
  };
}

/** O fim da execucao, para a linha de apoio sob o nome da obra ("execução até 31/03/2027"); sem data, nulo. */
export function fimDaExecucao(iso: string | null | undefined): string | null {
  return iso ? `execução até ${fmtDataPura(iso.slice(0, 10))}` : null;
}

/** A participacao de um contratante no contratado da carteira, com uma casa ("47,1%"); sem carteira, nula. */
export function participacao(parte: number, carteira: number): string | null {
  return carteira > 0 ? fmtPercentual(parte / carteira, 1) : null;
}

/** Os numeros de um conjunto de obras (a carteira ou um contratante): os totais da posicao, o medido do mes fechado,
 *  as contagens do andamento (`comAndamento` e' o "de M": as obras em que a leitura existe; a obra fora da regua,
 *  com o prazo no fim, a prorrogacao pedida ou sem medicao, nao entra em nenhuma das duas) e do que pede atencao. */
export type ResumoObras = {
  obras: number; totais: TotaisObras; medidoMes: MedidoMes | null;
  comAndamento: number; devagar: number; atencao: number;
  /** As obras com prazo a cumprir (o servidor mandou o necessario) e sem leitura: fora da regua (prazo no fim,
   *  prorrogacao pedida, sem medicao) ou que ainda nao mediu execucao. A faixa de numeros as conta ao lado do
   *  "N de M", e as duas contagens somam as linhas da vista Andamento (#822; decisao do dono de 19/11/2026: a faixa
   *  contava so' o prazo no fim e nao explicava a tabela). */
  semLeitura: number;
  paralisadas: number; execucaoVencida: number; avisosCriticos: number;
};

export function resumoDe(obras: ObraLista[], criticos?: ReadonlyMap<number, number>): ResumoObras {
  const r: ResumoObras = { obras: obras.length, totais: totaisDe(obras), medidoMes: medidoDoMes(obras),
    comAndamento: 0, devagar: 0, atencao: 0, semLeitura: 0, paralisadas: 0, execucaoVencida: 0, avisosCriticos: 0 };
  for (const o of obras) {
    const a = andamentoDaObra(o);
    if (a) { r.comAndamento += 1; if (a.leitura === "devagar") r.devagar += 1; else if (a.leitura === "atencao") r.atencao += 1; }
    else if ((o.andamento?.necessario_centavos ?? 0) > 0) r.semLeitura += 1;
    if (estaParalisada(o)) r.paralisadas += 1;
    if (execucaoVencida(o)) r.execucaoVencida += 1;
    r.avisosCriticos += criticos?.get(o.id) ?? 0;
  }
  return r;
}

/** Onde a obra sem leitura entra na vista Andamento, depois das que tem: a sem medicao ha' tres competencias (parada
 *  de fato), a com o prazo no fim ou com a prorrogacao pedida, e por ultimo a que nao tem o que escrever. */
const ORDEM_FORA_DA_REGUA: Record<string, number> = { sem_medicao: 1, prazo_no_fim: 2, prorrogacao_pedida: 2 };

/** A vista Andamento: as obras com prazo a cumprir (o servidor mandou o necessario). Primeiro as que tem leitura, da
 *  que mede a menor parte do necessario para a que mede a maior; no empate do percentual, pela razao dos dois valores
 *  e depois pelo nome. Depois as que ficaram fora da regua, com o motivo: a sem medicao (a mais antiga primeiro) e a
 *  com o prazo no fim ou a prorrogacao pedida (a que termina antes primeiro). Por ultimo, pelo nome, a que nao tem o
 *  que escrever (ainda nao mediu execucao). */
export function porAndamento(obras: ObraLista[]): ObraLista[] {
  const comPrazo = obras.filter(o => (o.andamento?.necessario_centavos ?? 0) > 0);
  const razao = (o: ObraLista) => (o.andamento?.ritmo_centavos ?? 0) / (o.andamento?.necessario_centavos ?? 1);
  const grupo = (o: ObraLista) => andamentoDaObra(o) ? 0 : ORDEM_FORA_DA_REGUA[o.andamento?.leitura?.motivo ?? ""] ?? 3;
  const dentroDoGrupo = (a: ObraLista, b: ObraLista, g: number) => {
    if (g === 0) return (andamentoDaObra(a)?.pct ?? 0) - (andamentoDaObra(b)?.pct ?? 0) || razao(a) - razao(b);
    if (g === 1) return (a.andamento?.leitura?.sem_medicao_desde ?? "").localeCompare(b.andamento?.leitura?.sem_medicao_desde ?? "");
    if (g === 2) return (a.execucao_fim_vigente ?? "").localeCompare(b.execucao_fim_vigente ?? "");
    return 0;
  };
  return comPrazo.sort((a, b) => grupo(a) - grupo(b) || dentroDoGrupo(a, b, grupo(a)) || nomeDaObra(a).localeCompare(nomeDaObra(b), "pt-BR"));
}

/** Os blocos da vista "Por contratante": do maior contratado para o menor (a participacao na carteira e' o que o bloco
 *  mostra); no empate, pelo nome. */
export function contratantesPorContratado(obras: ObraLista[]): GrupoDeObras[] {
  return gruposPorContratante(obras).sort((a, b) => b.subtotal.contratado - a.subtotal.contratado || a.contratante.localeCompare(b.contratante, "pt-BR"));
}

/** O contratante da URL: `?c=todas` e' "Todas as obras" (sem recorte de orgao); `?c=<orgao>` (ou o `?orgao=` dos
 *  links de antes) e' um orgao. Sem `c`, a pagina e' a escolha do contratante, a menos que haja um filtro de antes
 *  (`?termina=`, `?q=`, `?situacao=`): esses links abrem a lista de todas as obras, como abriam. */
export function escopoDaUrl(busca: Record<string, string>): { escolha: boolean; orgao: string | null } {
  const c = busca.c ?? busca.orgao ?? "";
  if (c && c !== "todas") return { escolha: false, orgao: c };
  const antigo = ["termina", "q", "situacao", "ver", "avisos"].some(k => busca[k] !== undefined);
  return { escolha: !c && !antigo, orgao: null };
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
