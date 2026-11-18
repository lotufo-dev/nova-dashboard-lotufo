import type { ObraResumo, PassoQuadro, LinhaQuadro } from "./resumoMedicoes";
import type { Parada } from "./parada";
import type { PassoDaBarra } from "./BarraDePassos";

// Tela Medicoes como fila de trabalho (#805, etapa 3a): os tipos de GET /api/medicoes/fila (`fila_medicoes.fila` no
// servidor) e os rotulos que a tela escreve. Com quem esta', ha' quantos dias uteis, a situacao do tempo parado, a
// diferenca aprovado x pedido e o proximo ato vem prontos do servidor; aqui nao ha' conta.

export type ComQuem = "lotufo" | "faturamento" | "orgao";
/** O ato de quem opera no passo da vez; nulo quando a vez e' do faturamento ou do orgao. */
export type Acao = "enviar_planilha" | "registrar_boletim" | "gerar_espelho" | "enviar_espelho" | "enviar_nota";

/** Pedido e aprovado no valor cheio da medicao, e a diferenca entre eles pela regra do Fechamento: os dois lados so'
 *  das medicoes com os dois valores (nulos quando nenhuma tem), o corte e, so' na linha, o que ficou acima. */
export type Comparados = {
  pedido_centavos: number | null; aprovado_centavos: number | null;
  aprovado_com_pedido_centavos: number | null; pedido_do_aprovado_centavos: number | null;
  abaixo_do_pedido_centavos: number | null;
};
export type ComparadosDaLinha = Comparados & { acima_do_pedido_centavos: number | null };

/** Uma medicao aberta (ou a medicao com o reajuste dela, na mesma situacao). */
export type LinhaFila = ComparadosDaLinha & {
  contrato_id: number; obra: string; contratante: string | null; orgao_sub: string | null;
  medicao_id: number; medicao_ids: number[]; titulo: string; competencia: string; com_quem: ComQuem;
  passo: { numero: number; nome: string; posicao: number | null; total: number };
  passos: PassoDaBarra[]; parada: Parada; acao: Acao | null;
};
export type GrupoFila = { com_quem: ComQuem; linhas: LinhaFila[] };
export type ContagemFila = { quantidade: number; criticas: number; breves: number; alem_do_prazo: number };
export type Concluida = { contrato_id: number; obra: string; medicao_id: number; titulo: string; recebida_em: string | null };
export type SemMedicao = { contrato_id: number; obra: string; contratante: string | null };

export type PassoDoQuadro = PassoQuadro & { parada: Parada | null };
export type LinhaDoQuadro = Omit<LinhaQuadro, "passos" | "pedido_centavos" | "aprovado_centavos"> & ComparadosDaLinha & { passos: PassoDoQuadro[] };
export type GrupoDoQuadro = Comparados & { contratante: string; linhas: LinhaDoQuadro[] };

export type Anteriores = { linhas: LinhaFila[]; esperam_pagamento: number; antes_do_ano_inicial: number; ano_inicial: string };
export type Limites = { dias_atencao: number; dias_critico: number; diferenca_critica_por_mil: number };

export type FilaMedicoes = {
  hoje: string; mes: string; obras: ObraResumo[]; limites: Limites;
  numeros: Comparados & { com: Record<ComQuem, ContagemFila>; concluidas: number; sem_medicao: number };
  grupos: GrupoFila[]; concluidas: Concluida[]; sem_medicao: SemMedicao[];
  quadro: GrupoDoQuadro[]; anteriores: Anteriores;
};

export const ORDEM_COM_QUEM: readonly ComQuem[] = ["lotufo", "faturamento", "orgao"];
export const ROTULO_COM_QUEM: Record<ComQuem, string> = {
  lotufo: "Com a Lotufo", faturamento: "Com o faturamento", orgao: "Com o órgão",
};
/** O texto do botao do proximo passo, para quem opera. */
export const ROTULO_DA_ACAO: Record<Acao, string> = {
  enviar_planilha: "Enviar planilha", registrar_boletim: "Registrar boletim", gerar_espelho: "Gerar espelho",
  enviar_espelho: "Enviar espelho", enviar_nota: "Enviar a nota",
};

/** As linhas na ordem do servidor (da mais parada para a menos), separadas por quem tem de agir; grupo vazio nao sai. */
export function porComQuem(linhas: LinhaFila[]): GrupoFila[] {
  return ORDEM_COM_QUEM.map(q => ({ com_quem: q, linhas: linhas.filter(l => l.com_quem === q) })).filter(g => g.linhas.length > 0);
}

/** "SINFRA · SUEF II"; sem sub-orgao, so' a sigla. */
export function contratanteDe(l: { contratante: string | null; orgao_sub: string | null }): string {
  return [l.contratante, l.orgao_sub].filter(Boolean).join(" · ");
}
