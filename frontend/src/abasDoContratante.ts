import type { AbaContratante } from "./rota";

/** As abas que a pagina do contratante (ContratantePagina.tsx) ja' desenha. As outras (Medicoes, A receber, Processos
 *  no SIGA, Avisos) ja' tem endereco na rota (#814) e chegam com a issue #818: ate' la' o App leva o endereco delas
 *  para a pagina como ela e' hoje. Quem construir uma aba a acrescenta aqui, e o endereco dela passa a abrir. */
export const ABAS_PRONTAS: readonly AbaContratante[] = ["obras"];
