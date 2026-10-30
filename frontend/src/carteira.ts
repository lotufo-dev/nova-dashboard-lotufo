// Carteira (NAVEGACAO.md › Carteira): a ordem e o recorte, no front, do que o /api/diretoria ja' manda. O farol
// e os motivos (A5) sao do servidor (`app/diretoria.py`, pelos avisos da diretoria); aqui nao se decide farol.

import type { AbaCarteira } from "./rota";

/** As abas da Carteira, na ordem do mapa (o Resumo e' a padrao). */
export const ABAS_CARTEIRA: { id: AbaCarteira; rotulo: string }[] = [
  { id: "resumo", rotulo: "Resumo" }, { id: "qdop", rotulo: "QDOP" }, { id: "producao", rotulo: "Produção" },
];

export type Farol = "verde" | "atencao" | "acao" | "vermelho";
export type Motivo = { tipo: string; nivel: string; dias: number | null; valor_centavos: number | null; texto: string };
export type ObraCarteira = { contrato_id: number; seq: number; obra: string; farol: Farol; motivos?: Motivo[] };

const ORDEM_FAROL: Record<Farol, number> = { vermelho: 0, acao: 1, atencao: 2, verde: 3 };

/** O QDOP pelo farol (vermelho, acao, atencao, verde); no mesmo farol, a ordem oficial do QDOP (seq). */
export function porFarol<T extends ObraCarteira>(obras: T[]): T[] {
  return [...obras].sort((a, b) => (ORDEM_FAROL[a.farol] ?? 4) - (ORDEM_FAROL[b.farol] ?? 4) || a.seq - b.seq);
}

/** Os motivos que cabem na linha (ate' `max`) e quantos ficam para os avisos da obra. */
export function motivosDaLinha(motivos: Motivo[] | undefined, max = 2): { visiveis: Motivo[]; mais: number } {
  const m = motivos ?? [];
  return { visiveis: m.slice(0, max), mais: Math.max(0, m.length - max) };
}
