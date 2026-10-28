// Tela SIGA (issue #329): o que o servidor devolve em GET /api/siga e as contas da tela (ordem, tempo no setor,
// nivel de atraso, textos da linha). Funcoes puras; o SigaPagina so' desenha o que sai daqui.

export type Movimentacao = {
  data: string; evento: string | null; cad_lotacao: string; cad_pessoa: string; at_lotacao: string; at_pessoa: string;
};

export type ProcessoSiga = {
  id: number; codigo: string | null; link: string | null; numero: string | null; nome: string | null;
  contrato_id: number | null; obra: string | null; medicao_id: number | null; medicao_titulo: string | null;
  protocolo_id: number | null; situacao: string | null; setor: string; caixa_entrada: boolean; com_quem: string;
  desde: string | null; dias_uteis: number | null; hoje: number; ultima: Movimentacao | null;
  protocolado_em: string | null; movimentacoes: Movimentacao[];
};

export type PainelSiga = { lido_em: string | null; atrasado: boolean; processos: ProcessoSiga[] };

// Os mesmos limites dos avisos: ambar a partir de 5 dias uteis no mesmo setor, vermelho a partir de 10.
export const DIAS_ATENCAO = 5;
export const DIAS_ACAO = 10;

export function nivelDias(dias: number | null): "atencao" | "acao" | null {
  if (dias === null) return null;
  return dias >= DIAS_ACAO ? "acao" : dias >= DIAS_ATENCAO ? "atencao" : null;
}

const instante = (iso: string | null, vazio: number): number => {
  const t = iso === null ? NaN : Date.parse(iso);
  return Number.isNaN(t) ? vazio : t;
};

/** Quem andou hoje primeiro (a movimentacao mais recente no topo), depois os parados ha mais tempo. */
export function ordenar(processos: ProcessoSiga[]): ProcessoSiga[] {
  return [...processos].sort((a, b) => {
    const aHoje = a.hoje > 0, bHoje = b.hoje > 0;
    if (aHoje !== bHoje) return aHoje ? -1 : 1;
    if (aHoje) {
      return instante(b.ultima?.data ?? null, -Infinity) - instante(a.ultima?.data ?? null, -Infinity) || a.id - b.id;
    }
    return (b.dias_uteis ?? -1) - (a.dias_uteis ?? -1)
      || instante(a.desde, Infinity) - instante(b.desde, Infinity) || a.id - b.id;
  });
}

/** "N dias uteis" a partir de um dia util; antes disso, minutos ou horas; passado um dia corrido sem dia util
 *  completo (fim de semana, feriado), "menos de 1 dia util". */
export function tempoNoSetor(p: ProcessoSiga, agora: Date): string {
  if (p.desde === null || p.dias_uteis === null) return "—";
  if (p.dias_uteis >= 1) return p.dias_uteis === 1 ? "1 dia útil" : `${p.dias_uteis} dias úteis`;
  const desde = instante(p.desde, NaN);
  if (Number.isNaN(desde)) return "—";
  const minutos = Math.max(1, Math.floor((agora.getTime() - desde) / 60_000));
  if (minutos < 60) return `${minutos} min`;
  if (minutos < 24 * 60) return `${Math.floor(minutos / 60)} h`;
  return "menos de 1 dia útil";
}

/** "(2º Volume)" quando o processo ja' esta' num volume depois do primeiro; o ultimo volume e' o da situacao. */
export function volumeDe(situacao: string | null): string {
  const ultimo = (situacao ?? "").split(" | ").pop() ?? "";
  const n = /(\d+)º\s*Volume/i.exec(ultimo);
  return n && Number(n[1]) > 1 ? `(${n[1]}º Volume)` : "";
}

/** O evento sem o texto que o SIGA poe depois de " |". */
export function tituloDoEvento(evento: string | null): string {
  return (evento ?? "").split("|")[0].trim();
}

/** "COFIN/ORGAO" -> "COFIN". */
export function sigla(lotacao: string | null): string {
  return (lotacao ?? "").split("/")[0].trim();
}

const ehTransferencia = (m: Movimentacao) => /transfer/i.test(m.evento ?? "");

/** Quem fez / quem tem: na transferencia, quem passou (cadastro); nas demais, a pessoa e o setor atribuidos. */
export function quemDaMovimentacao(m: Movimentacao): string {
  const t = ehTransferencia(m);
  const pessoa = (t ? m.cad_pessoa || m.at_pessoa : m.at_pessoa || m.cad_pessoa).trim();
  const setor = t ? sigla(m.cad_lotacao) || sigla(m.at_lotacao) : sigla(m.at_lotacao) || sigla(m.cad_lotacao);
  return [pessoa, setor].filter(Boolean).join(", ");
}

/** Para onde foi, na transferencia: o setor de destino. */
export function destinoDaMovimentacao(m: Movimentacao): string {
  return ehTransferencia(m) && sigla(m.at_lotacao) ? `→ ${sigla(m.at_lotacao)}` : "";
}

/** Nome do processo como a pessoa o reconhece: obra e medicao quando ligado, senao o que o robo mandou. */
export function nomeDoProcesso(p: ProcessoSiga): string {
  if (p.medicao_id !== null && p.obra) return p.medicao_titulo ? `${p.obra} · ${p.medicao_titulo}` : p.obra;
  return p.nome || p.numero || p.codigo || "Processo sem nome";
}

const semAcento = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();

/** Filtro por obra: obra, nome do robo, numero e medicao, sem maiuscula nem acento. */
export function casaComBusca(p: ProcessoSiga, texto: string): boolean {
  const q = semAcento(texto.trim());
  if (!q) return true;
  return [p.obra, p.nome, p.numero, p.medicao_titulo].some(c => c && semAcento(c).includes(q));
}
