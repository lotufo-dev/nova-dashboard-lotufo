// Regras de APRESENTACAO das abas da obra (NAVEGACAO.md › Obra): funcoes puras sobre o que a API ja' entrega
// (/aditivos, /cadastro, /prazos, /reajuste). Nada aqui decide prazo, valor ou reajuste: so' junta, filtra e ordena.

export type AditivoApi = { id: number; tipo: string; forma?: string | null; numero: string | null; objeto: string | null;
  observacao?: string | null; delta_valor_centavos: number; nova_vigencia_fim: string | null; nova_execucao_fim: string | null;
  status: string; data_assinatura: string | null; ressalva_reajuste?: string | null;
  valor_anterior_centavos?: number | null; valor_novo_centavos?: number | null;
  cancelado_em: string | null; cancelado_motivo?: string | null };
export type InstrumentoCadastro = { id: number; chave?: string; tipo: string; numero: string | null; data: string; dados: Record<string, unknown> };
export type InstrumentoPrazo = { id: number; numero: string | null; forma?: string | null; data_assinatura: string | null;
  retroativo: boolean };

/** Os instrumentos do cadastro que moram em Contrato › Instrumentos. Os marcos de encerramento moram em
 *  Prazos › Encerramento. */
export const TIPOS_DO_CADASTRO = ["apostilamento_reajuste", "paralisacao", "reinicio", "endosso_garantia"];

export type LinhaInstrumento =
  | { de: "aditivo"; chave: string; data: string | null; aditivo: AditivoApi; dePrazo: boolean; retroativo: boolean }
  | { de: "cadastro"; chave: string; data: string | null; instrumento: InstrumentoCadastro };

/** Contrato › Instrumentos: todo instrumento da obra numa lista so' (aditivos de prazo e de valor, apostilamentos,
 *  paralisacoes, reinicios e endossos), do mais novo ao mais antigo; o que ainda nao foi assinado vai para o fim.
 *  Quais contam como instrumento de prazo, e quais sao retroativos, diz o servidor (`/prazos`, que lista linhas
 *  de aditivos): e' a mesma conta que a aba Prazos mostra. */
export function instrumentosDaObra(aditivos: AditivoApi[], cadastro: InstrumentoCadastro[], prazo: InstrumentoPrazo[]): LinhaInstrumento[] {
  const dePrazo = new Set(prazo.map(p => p.id));
  const retro = new Set(prazo.filter(p => p.retroativo).map(p => p.id));
  const linhas: LinhaInstrumento[] = [
    ...aditivos.map(a => ({ de: "aditivo" as const, chave: `a${a.id}`, data: a.data_assinatura, aditivo: a,
      dePrazo: dePrazo.has(a.id), retroativo: retro.has(a.id) })),
    ...cadastro.filter(i => TIPOS_DO_CADASTRO.includes(i.tipo))
      .map(i => ({ de: "cadastro" as const, chave: `c${i.id}`, data: i.data, instrumento: i })),
  ];
  return linhas.sort((x, y) => (y.data ?? "").localeCompare(x.data ?? ""));
}

/** O desfecho de um pedido de prorrogacao enviado: o primeiro instrumento de prazo assinado no dia do envio ou
 *  depois (e' com essa regra que o servidor da' o pedido por atendido, em `prazos.situacao`), ou nenhum ainda. */
export function desfechoDoPedido<I extends InstrumentoPrazo>(enviadoEm: string | null, prazo: I[]): I | null {
  if (!enviadoEm) return null;
  const dia = enviadoEm.slice(0, 10);
  return [...prazo].filter(p => (p.data_assinatura ?? "") >= dia)
    .sort((a, b) => (a.data_assinatura ?? "").localeCompare(b.data_assinatura ?? ""))[0] ?? null;
}

export type CicloApi = { data_base_mes: string; indice: string | null; aplica_a?: string | null; ciclo: number; aniversario: string; situacao: string;
  dias: number | null; apostilamento?: InstrumentoCadastro | null };
export type PleitoResumo = { id: number; data_base_mes: string | null; ciclo: number | null };

export type DataBase<C extends CicloApi, P, I> = { data_base_mes: string; atual: C;
  pleitosDoCiclo: P[]; pleitosAnteriores: P[]; apostilamentos: I[] };

/** O ciclo (ano) que o apostilamento fecha: `ciclo`, senao o ano da `eficacia`, senao o da data do termo (a regra de
 *  `reajuste.ciclo_do_apostilamento`). */
export function cicloDoApostilamento(i: InstrumentoCadastro): number | null {
  const ano = Number(String(i.dados.ciclo || i.dados.eficacia || i.data).slice(0, 4));
  return Number.isInteger(ano) && ano > 0 ? ano : null;
}

/** Os termos que outro apostilamento corrige (`corrige` nos dados): nao valem (`reajuste._termo_vale`). */
export function termosCorrigidos(lista: InstrumentoCadastro[]): Set<string> {
  return new Set(lista.map(i => i.dados.corrige).filter((k): k is string => typeof k === "string" && k !== ""));
}

/** A data-base de cada termo como o servidor a resolveu (`reajuste.bases_dos_termos`). */
export type BaseDoTermo = { instrumento_id: number; data_base_mes: string | null };

/** Aba Reajuste: um cartao por data-base, com o ciclo corrente (o que a API manda), os pleitos dele e, a parte,
 *  os pleitos dos ciclos passados. Apostilamento vai para a data-base que o servidor resolveu (`bases`, a regra de
 *  `reajuste.base_do_termo`); sem ela, a que ele diz (`dados.data_base`) ou a data-base unica do contrato; o que
 *  nao se sabe onde fica sobra em `semDataBase`, e pleito de data-base que o contrato nao tem mais, em
 *  `outrosPleitos`. */
export function reajustePorDataBase<C extends CicloApi, P extends PleitoResumo, I extends InstrumentoCadastro>(
    ciclos: C[], pleitos: P[], apostilamentos: I[], bases: BaseDoTermo[] = []): { dataBases: DataBase<C, P, I>[]; semDataBase: I[]; outrosPleitos: P[] } {
  const unica = ciclos.length === 1 ? ciclos[0].data_base_mes : null;
  const resolvida = new Map(bases.map(b => [b.instrumento_id, b.data_base_mes]));
  const baseDe = (i: I): string | null => {
    if (resolvida.has(i.id)) return resolvida.get(i.id) ?? null;
    const d = i.dados.data_base;
    return typeof d === "string" && d ? d.slice(0, 7) : unica;
  };
  const dataBases = ciclos.map(c => {
    const dela = pleitos.filter(p => p.data_base_mes === c.data_base_mes);
    return { data_base_mes: c.data_base_mes, atual: c,
      pleitosDoCiclo: dela.filter(p => p.ciclo === c.ciclo), pleitosAnteriores: dela.filter(p => p.ciclo !== c.ciclo),
      apostilamentos: apostilamentos.filter(i => baseDe(i) === c.data_base_mes) };
  });
  const conhecidas = new Set(ciclos.map(c => c.data_base_mes));
  return { dataBases, semDataBase: apostilamentos.filter(i => !conhecidas.has(baseDe(i) ?? "")),
    outrosPleitos: pleitos.filter(p => !conhecidas.has(p.data_base_mes ?? "")) };
}

/* ------------------------------------------------------------ Pagina da obra: linhas do tempo (#160) */

/** Dias corridos de `a` ate' `b` (datas puras "AAAA-MM-DD", sem fuso: so' aritmetica de calendario em UTC). */
export function diasEntre(a: string, b: string): number {
  const t = (s: string) => { const [y, m, d] = s.slice(0, 10).split("-").map(Number); return Date.UTC(y, m - 1, d); };
  return Math.round((t(b) - t(a)) / 86_400_000);
}

/** Uma linha do tempo (Execucao ou Vigencia): onde o "hoje" cai entre o inicio e o fim (0 a 100; nulo se o cadastro
 *  nao tem o inicio) e quantos dias faltam (negativo = vencida). Depende so' da data do dia, entao anda sozinho. */
export function linhaDoTempo(inicio: string | null, fim: string, hoje: string): { posicao: number | null; restantes: number } {
  const restantes = diasEntre(hoje, fim);
  if (!inicio) return { posicao: null, restantes };
  const total = diasEntre(inicio, fim);
  const corrido = diasEntre(inicio, hoje);
  const posicao = total <= 0 ? (corrido >= 0 ? 100 : 0) : Math.max(0, Math.min(100, (corrido / total) * 100));
  return { posicao, restantes };
}

/** Selo do prazo (texto na tela, 26/10/2026): so' quando pede acao, nos limites do aviso "Execucao vencendo" (spec
 *  §11): a ate' 60 dias do fim em Atencao, a ate' 30 ou vencido em Critico. Fora disso, null (quanto falta nao se
 *  escreve). */
export function seloDoPrazo(restantes: number | null): { classe: string; texto: string } | null {
  if (restantes === null || Number.isNaN(restantes) || restantes > 60) return null;
  const texto = restantes < 0 ? "vencida" : restantes === 0 ? "vence hoje"
    : `vence em ${restantes} ${restantes === 1 ? "dia" : "dias"}`;
  return { classe: restantes <= 30 ? "selo--acao" : "selo--atencao", texto };
}

/** Rótulo curto da marca do aditivo na curva: "2º TA" para "TA 2º Termo Aditivo ao Contrato …"; sem número, "TA". */
export function rotuloAditivo(nome: string): string {
  const m = /(\d+)\s*[ºo°]/.exec(nome);
  return m ? `${m[1]}º TA` : "TA";
}
