// Situacao (#720): um sistema so', com as quatro situacoes da fundacao. As pecas que as mostram sao Selo.tsx (selo e
// glifo), Contador.tsx e LegendaCor.tsx; as cores e os desenhos moram em tokens.css (--situacao-*).
export type Situacao = "feito" | "andamento" | "breve" | "critico";

export const SITUACOES: readonly Situacao[] = ["feito", "andamento", "breve", "critico"];

/** O vocabulario de nivel que as telas e o servidor ja' usam, na situacao que o mostra. E' o UNICO mapa de nivel
 *  para situacao: aviso (critico, acao, atencao), documento (ok, atencao, acao), farol da obra (verde, atencao, acao,
 *  vermelho) e tempo parado do SIGA (atencao, acao) passam por aqui. Critico e Acao pedem acao agora (octogono);
 *  Atencao se acompanha (triangulo). O que nao tem situacao (neutro, normal, passo do ciclo) fica sem ela: selo
 *  neutro, sem glifo. Quem precisa de um padrao para o nivel sem situacao (o SIGA dentro do prazo e' "em andamento";
 *  o aviso de nivel desconhecido conta como atencao) diz o padrao no proprio lugar, com `??`. */
const DO_NIVEL: Record<string, Situacao> = {
  ok: "feito", feito: "feito", verde: "feito", andamento: "andamento",
  atencao: "breve", breve: "breve", acao: "critico", critico: "critico", vermelho: "critico",
};

export function situacaoDoNivel(nivel: string | null | undefined): Situacao | undefined {
  return nivel ? DO_NIVEL[nivel] : undefined;
}
