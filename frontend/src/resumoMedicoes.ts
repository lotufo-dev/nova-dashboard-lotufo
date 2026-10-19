import type { AbaMedicoes } from "./rota";

// Regras de APRESENTACAO da pagina Medicoes com abas (09/10/2026, prototipo aprovado pelo Leo): funcoes puras sobre
// GET /api/medicoes/resumo. Situacao, marco, dias parados e a linha unica de medicao + reajuste sao do servidor
// (`medicoes.resumo`); aqui so' os rotulos, os limiares de cor do "Parada há" e o agrupamento por contratante.

export type Situacao = "faturamento" | "aguardando-nota" | "enviar-nota" | "aguardando-pagamento";
export type SituacaoOuSem = "sem-medicao" | Situacao;

export type LinhaResumo = {
  situacao: Situacao; contrato_id: number; obra: string; contratante: string; orgao_sub: string | null;
  medicao_id: number; medicao_ids: number[]; numero: number; competencia: string; titulo: string; proximo_passo: string;
  valor_centavos: number | null; marco: string | null; dias: number | null;
};
export type ObraResumo = {
  contrato_id: number; obra: string; contratante: string; orgao_sub: string | null; aberta: boolean;
  prevista_id: number | null;
  encerramento: boolean;   // A-21 (10/10/2026): em encerramento segue na lista, mas nao conta como "obra ativa"
  // #154 (aba Sem medicao aberta): ultima medicao, dias desde o fim da competencia dela, a prevista do cronograma
  // e o numero da proxima. Tudo do servidor.
  // Execucao e projeto tem numeracao propria; `proxima_tipo` diz a serie do `proxima`.
  ultima: MedicaoCurta | null; ha_dias: number | null; prevista: MedicaoCurta | null;
  proxima: number; proxima_tipo: "execucao" | "projeto";
};
export type MedicaoCurta = { numero: number; tipo: string; competencia: string };
export type ResumoMedicoes = {
  hoje: string; contagens: Record<SituacaoOuSem, number>; linhas: LinhaResumo[]; obras: ObraResumo[];
};

// Na ordem do ciclo; e' a ordem das abas, dos cartoes e das linhas da tabela.
export const SITUACOES: readonly { id: SituacaoOuSem; rotulo: string }[] = [
  { id: "sem-medicao", rotulo: "Sem medição aberta" },
  { id: "faturamento", rotulo: "Enviar ao faturamento" },
  { id: "aguardando-nota", rotulo: "Aguardando nota" },
  { id: "enviar-nota", rotulo: "Enviar nota" },
  { id: "aguardando-pagamento", rotulo: "Aguardando pagamento" },
];

export const ABAS_MEDICOES: readonly { id: AbaMedicoes; rotulo: string }[] = [{ id: "resumo", rotulo: "Resumo" }, ...SITUACOES];

export function rotuloSituacao(s: SituacaoOuSem): string {
  return SITUACOES.find(x => x.id === s)?.rotulo ?? s;
}

/** "hoje", "1 dia", "24 dias"; sem marco (o servidor nunca usa a data de lancamento no lugar dele), "—". */
export function textoParada(dias: number | null): string {
  if (dias === null) return "\u2014";
  if (dias <= 0) return "hoje";
  return dias === 1 ? "1\u00a0dia" : `${dias.toLocaleString("pt-BR")}\u00a0dias`;
}

/** Cor do "Parada há": o orgao leva 30+ dias para pagar, entao "aguardando pagamento" so' acende a partir disso
 *  (ambar a partir de 30, vermelho a partir de 45); as outras situacoes dependem da Lotufo (acima de 7 e de 15). */
export function nivelParada(dias: number | null, situacao: SituacaoOuSem): "atencao" | "acao" | null {
  if (dias === null) return null;
  if (situacao === "aguardando-pagamento") return dias >= 45 ? "acao" : dias >= 30 ? "atencao" : null;
  return dias > 15 ? "acao" : dias > 7 ? "atencao" : null;
}

/** "23ª · 01/2026" (numero e competencia "2026-01"); medicao de projeto: "1ª de Projeto · 09/2026". */
export function textoMedicao(m: MedicaoCurta): string {
  return `${m.numero}ª${m.tipo === "projeto" ? " de Projeto" : ""} · ${m.competencia.slice(5, 7)}/${m.competencia.slice(0, 4)}`;
}

export type GrupoContratante = { contratante: string; obras: ObraResumo[] };

/** Obras por contratante, o grupo com mais obras primeiro (empate: pelo nome). Dentro do grupo, a ordem do servidor
 *  (alfabetica). */
export function porContratante(obras: ObraResumo[]): GrupoContratante[] {
  const m = new Map<string, ObraResumo[]>();
  for (const o of obras) m.set(o.contratante, [...(m.get(o.contratante) ?? []), o]);
  return [...m.entries()].map(([contratante, os]) => ({ contratante, obras: os }))
    .sort((a, b) => b.obras.length - a.obras.length || a.contratante.localeCompare(b.contratante, "pt-BR"));
}

const semAcento = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLocaleLowerCase("pt-BR");

/** Busca da janela "Iniciar processo de medição": obra, contratante ou sub-orgao, sem acento nem caixa. */
export function filtrarObras(obras: ObraResumo[], termo: string): ObraResumo[] {
  const t = semAcento(termo.trim());
  if (!t) return obras;
  return obras.filter(o => semAcento([o.obra, o.contratante, o.orgao_sub ?? ""].join(" ")).includes(t));
}
