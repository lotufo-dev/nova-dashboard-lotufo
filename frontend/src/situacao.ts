// Situacao (#720): um sistema so', com as quatro situacoes da fundacao. As pecas que as mostram sao Selo.tsx (selo e
// glifo), Contador.tsx e LegendaCor.tsx; as cores e os desenhos moram em tokens.css (--situacao-*).
export type Situacao = "feito" | "andamento" | "breve" | "critico";

export const SITUACOES: readonly Situacao[] = ["feito", "andamento", "breve", "critico"];

/** O vocabulario de nivel que as telas e o servidor ja' usam, na situacao que o mostra. O que nao tem situacao
 *  (neutro, normal, passo do ciclo) fica sem ela: selo neutro, sem glifo. */
const DO_NIVEL: Record<string, Situacao> = {
  ok: "feito", feito: "feito", andamento: "andamento",
  atencao: "breve", breve: "breve", acao: "critico", critico: "critico",
};

export function situacaoDoNivel(nivel: string | null | undefined): Situacao | undefined {
  return nivel ? DO_NIVEL[nivel] : undefined;
}
