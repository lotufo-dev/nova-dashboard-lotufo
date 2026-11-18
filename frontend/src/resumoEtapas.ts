import type { Parada } from "./parada";
import { fmtMesCurto, fmtMesExtenso } from "./tempo";

// Resumo das medicoes (#749, #805): o que GET /api/resumo-medicoes devolve (`app/resumo_medicoes.py`) e as funcoes
// puras de apresentacao da pagina. A etapa de cada medicao, os valores (na cota), as referencias das variacoes, os
// dois lados da diferenca e o tempo parado vem prontos do servidor; aqui so' se escolhe o rotulo e a ordem.

export type Etapa = "em_analise" | "boletim" | "nota" | "protocolado" | "recebido";
/** `antes`: a planilha/carta foi gerada e ainda nao foi enviada ao orgao (a medicao existe, o ciclo nao comecou). */
export type EtapaDaVez = Etapa | "antes";
/** `sem_registro`: a etapa ficou para tras e o sistema nao tem o registro do evento dela. */
export type EtapaDaLinha = { etapa: Etapa; situacao: "feito" | "sem_registro" | "atual" | "futuro"; data: string | null };
export type Linha = {
  contrato_id: number; obra: string; contratante: string | null; medicao_id: number; medicao_ids: number[]; titulo: string;
  numero: number; tipo: string; competencia: string; etapa: EtapaDaVez; etapas: EtapaDaLinha[]; valor_centavos: number | null;
  /** Ha' quanto tempo a medicao esta' parada: o mesmo `parada` da fila de trabalho da tela Medicoes (parada.ts).
   *  Nulo na recebida, que nao esta' parada. */
  parada: Parada | null;
  /** So' na recebida: a data do recebimento e, com a emissao da nota registrada, os dias corridos da nota ate' ele. */
  recebida_em: string | null; dias_da_nota_ao_recebimento: number | null;
  /** A diferenca entre o aprovado e o pedido (a conta do Fechamento); nulos sem os dois valores. */
  pedido_do_aprovado_centavos: number | null; abaixo_do_pedido_centavos: number | null; acima_do_pedido_centavos: number | null;
};
export type SemMedicao = {
  contrato_id: number; obra: string; contratante: string | null;
  ultima: { medicao_id: number; titulo: string; competencia: string; etapa: EtapaDaVez } | null;
};
export type ContagemDaEtapa = { etapa: EtapaDaVez; medicoes: number; valor_centavos: number };
export type Referencia = { competencia: string; valor_centavos: number };
export type RespostaResumo = {
  hoje: string; mes: string; em_trabalho: string;
  atualizacao: { ultimo_lancamento: string | null; rm_lido_em: string | null };
  /** O filtro em vigor e, sem recorte, quem tem medicao na competencia ou aberta em meses anteriores. */
  contratante: string | null;
  contratantes: { contratante: string; medicoes: number; anteriores: number }[];
  etapas: ContagemDaEtapa[];
  /** O medido da competencia (o numero do Fechamento) e as referencias da variacao; nula a que nao serve. */
  medido: { valor_centavos: number; mes_anterior: Referencia | null; ano_anterior: Referencia | null };
  /** O protocolado e o recebido da competencia anterior na mesma data, um mes antes; nulo o que nao tem lastro. */
  mesma_altura: { competencia: string; ate: string; protocolado_centavos: number | null; recebido_centavos: number | null } | null;
  diferenca_critica_por_mil: number;
  grupos: { contratante: string; medicoes: number; valor_centavos: number; linhas: Linha[] }[];
  sem_medicao: SemMedicao[];
  anteriores_etapas: ContagemDaEtapa[];
  anteriores: { competencia: string; medicoes: number; valor_centavos: number; linhas: Linha[] }[];
};
/** Um grupo de linhas da tabela: o contratante ou, nos meses anteriores, a competencia. */
export type Grupo = { chave: string; titulo: string; medicoes: number; valor_centavos: number; linhas: Linha[] };

export const ETAPAS: { chave: Etapa; rotulo: string }[] = [
  { chave: "em_analise", rotulo: "Em análise" }, { chave: "boletim", rotulo: "Boletim" }, { chave: "nota", rotulo: "Nota" },
  { chave: "protocolado", rotulo: "Protocolado" }, { chave: "recebido", rotulo: "Recebido" },
];
export const ANTES = "Planilha/carta a enviar";
export const ROTULO = { antes: ANTES, ...Object.fromEntries(ETAPAS.map(e => [e.chave, e.rotulo])) } as Record<EtapaDaVez, string>;

export const maiuscula = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** O nome de uma competencia de referencia ao lado da competencia da pagina: do mesmo ano, so' o mes ("set",
 *  "setembro"); de outro, com o ano ("out/25", "outubro de 2025"). */
export function nomeDaReferencia(competencia: string, mes: string): { curto: string; extenso: string } {
  const mesmoAno = competencia.slice(0, 4) === mes.slice(0, 4);
  return {
    curto: mesmoAno ? fmtMesCurto(competencia).split("/")[0] : fmtMesCurto(competencia),
    extenso: mesmoAno ? fmtMesExtenso(competencia) : `${fmtMesExtenso(competencia)} de ${competencia.slice(0, 4)}`,
  };
}

/** A referencia da "mesma altura": a competencia anterior ate' o mesmo dia de hoje, um mes antes ("set até 18/10",
 *  "setembro até 18 de outubro"). */
export function nomeDaMesmaAltura(competencia: string, ate: string, mes: string): { curto: string; extenso: string } {
  const nome = nomeDaReferencia(competencia, mes);
  const dia = ate.slice(8, 10), mesDoDia = ate.slice(5, 7);
  return {
    curto: `${nome.curto} até ${dia}/${mesDoDia}`,
    extenso: `${nome.extenso} até ${Number(dia)} de ${fmtMesExtenso(ate.slice(0, 7))}`,
  };
}

/** A linha tem diferenca a mostrar: o aprovado ficou abaixo ou acima do pedido, fora da tolerancia do servidor. */
export function temDiferenca(l: Linha): boolean {
  return (l.abaixo_do_pedido_centavos ?? 0) > 0 || (l.acima_do_pedido_centavos ?? 0) > 0;
}

/** As linhas de cada etapa do quadro, a de maior valor primeiro (empate: a ordem do servidor). */
export function linhasDaEtapa(linhas: Linha[], etapa: EtapaDaVez): Linha[] {
  return linhas.filter(l => l.etapa === etapa).sort((a, b) => (b.valor_centavos ?? 0) - (a.valor_centavos ?? 0));
}

/** "set" ou, de outro ano que o da pagina, "set/25": o mes da ultima medicao de uma obra sem medicao na competencia. */
export function mesDaUltima(competencia: string, mes: string): string {
  return nomeDaReferencia(competencia, mes).curto;
}
