// Regras de APRESENTACAO das abas da obra (NAVEGACAO.md › Obra): funcoes puras sobre o que a API ja' entrega
// (/aditivos, /cadastro, /prazos, /reajuste). Nada aqui decide prazo, valor ou reajuste: so' junta, filtra e ordena.

export type AditivoApi = { id: number; tipo: string; forma?: string | null; numero: string | null; objeto: string | null;
  observacao?: string | null; delta_valor_centavos: number; nova_vigencia_fim: string | null; nova_execucao_fim: string | null;
  status: string; data_assinatura: string | null; ressalva_reajuste?: string | null;
  valor_anterior_centavos?: number | null; valor_novo_centavos?: number | null;
  cancelado_em: string | null; cancelado_motivo?: string | null };
export type InstrumentoCadastro = { id: number; tipo: string; numero: string | null; data: string; dados: Record<string, unknown> };
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

/** Aba Reajuste: um cartao por data-base, com o ciclo corrente (o que a API manda), os pleitos dele e, a parte,
 *  os pleitos dos ciclos passados. Apostilamento vai para a data-base que ele diz (`dados.data_base`); sem ela,
 *  para a data-base unica do contrato (a regra de `reajuste._apostilamento`); o que nao se sabe onde fica sobra
 *  em `semDataBase`, e pleito de data-base que o contrato nao tem mais, em `outrosPleitos`. */
export function reajustePorDataBase<C extends CicloApi, P extends PleitoResumo, I extends InstrumentoCadastro>(
    ciclos: C[], pleitos: P[], apostilamentos: I[]): { dataBases: DataBase<C, P, I>[]; semDataBase: I[]; outrosPleitos: P[] } {
  const unica = ciclos.length === 1 ? ciclos[0].data_base_mes : null;
  const baseDe = (i: I): string | null => {
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

/* ------------------------------------------------------------ Pagina da obra: curva S e linhas do tempo (#160) */

export type PontoDaCurva = { competencia: string; previsto_centavos: number; medido_execucao_centavos: number;
  atestado_pendente: boolean };
export type PontoS = { competencia: string; previsto: number; execucao: number; provisorio: boolean;
  /** Ate' a ultima competencia com execucao medida; depois dela a curva do medido nao continua. */
  medida: boolean; acumuladoPrevisto: number; acumuladoMedido: number | null;
  /** Issue #295: acumulado do previsto anterior a ultima repactuacao; null quando a obra nao tem essa linha. */
  acumuladoAnterior: number | null };
/** Previsto por competencia da versao anterior a ultima repactuacao e a marca de cada aditivo (API da curva). */
export type PrevistoAnterior = { competencia: string; previsto_centavos: number }[];
export type MarcaAditivo = { competencia: string; data: string; nome: string };

/** A curva S da pagina da obra: previsto e medido de execucao, mes a mes e acumulados. O medido acumulado so' vai ate'
 *  a ultima competencia com execucao medida; antes dela, mes sem medicao conta zero (e' dado, nao ausencia). */
export function curvaS(pontos: PontoDaCurva[], anterior?: PrevistoAnterior | null): PontoS[] {
  const dados = new Map(pontos.map(p => [p.competencia, p]));
  const prevAnt = new Map((anterior ?? []).map(a => [a.competencia, a.previsto_centavos]));
  // a linha anterior pode ter meses que o vigente nao tem: o eixo e' a uniao
  for (const c of prevAnt.keys()) {
    if (!dados.has(c)) dados.set(c, { competencia: c, previsto_centavos: 0, medido_execucao_centavos: 0, atestado_pendente: false });
  }
  const ordenadas = [...dados.keys()].sort();
  // a API so' manda as competencias que tem previsto ou medido: o eixo do tempo precisa dos meses vazios no meio
  const ordem: PontoDaCurva[] = [];
  if (ordenadas.length > 0) {
    let [a, m] = ordenadas[0].split("-").map(Number);
    const fim = ordenadas[ordenadas.length - 1];
    for (;;) {
      const c = `${a}-${String(m).padStart(2, "0")}`;
      ordem.push(dados.get(c) ?? { competencia: c, previsto_centavos: 0, medido_execucao_centavos: 0, atestado_pendente: false });
      if (c >= fim) break;
      if (++m > 12) { m = 1; a++; }
    }
  }
  let ultima = -1;
  ordem.forEach((p, i) => { if (p.medido_execucao_centavos > 0) ultima = i; });
  let acP = 0, acM = 0, acA = 0;
  return ordem.map((p, i) => {
    acP += p.previsto_centavos;
    acM += p.medido_execucao_centavos;
    acA += prevAnt.get(p.competencia) ?? 0;
    const medida = i <= ultima;
    return { competencia: p.competencia, previsto: p.previsto_centavos, execucao: p.medido_execucao_centavos,
      provisorio: p.atestado_pendente && p.medido_execucao_centavos > 0, medida,
      acumuladoPrevisto: acP, acumuladoMedido: medida ? acM : null,
      acumuladoAnterior: anterior ? acA : null };
  });
}

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

