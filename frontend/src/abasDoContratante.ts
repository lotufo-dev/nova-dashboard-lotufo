import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import type { ContratanteAReceber } from "./AReceber";
import type { Concluida, GrupoFila, Limites, SemMedicao } from "./filaMedicoes";
import { pode } from "./permissoes";
import type { AbaContratante } from "./rota";
import type { LimitesSiga, ProcessoSiga, Robo } from "./siga";

// As abas da pagina do contratante (ContratantePagina.tsx, #805 e #818) e o dado de cada uma. O endereco de cada aba
// esta' na rota ("/obras/contratante/<chave>/medicoes", #814); a aba que nao esta' em ABAS_PRONTAS o App leva de volta
// a' pagina. Avisos ainda nao e' aba: a pagina leva aos Avisos filtrados pelo contratante.

/** As abas que a pagina desenha, na ordem da faixa. */
export const ABAS_PRONTAS: readonly AbaContratante[] = ["obras", "medicoes", "a-receber", "siga"];

/** As abas de quem esta' na tela: Processos no SIGA so' para quem tem `ver_siga` (#829: os tres perfis, a diretoria
 *  so' para ler), pela lista que o servidor informa em /api/auth/eu; o servidor nega o dado a quem nao tem. */
export function abasDe(permissoes: readonly string[] = []): AbaContratante[] {
  return ABAS_PRONTAS.filter(a => a !== "siga" || pode({ permissoes }, "ver_siga"));
}

// O dado de cada aba: o recorte, pelas obras do contratante, de uma tela que ja' existe (`app/contratante.py`). A
// `quantidade` e' o numero de linhas da aba, que a faixa escreve ao lado do nome.

/** GET /api/contratantes/<chave>/medicoes: a fila de trabalho da competencia em trabalho (`fila_medicoes.fila`). */
export type MedicoesDoContratante = {
  hoje: string; mes: string; limites: Limites; grupos: GrupoFila[]; concluidas: Concluida[]; sem_medicao: SemMedicao[];
  quantidade: number;
};
/** GET /api/contratantes/<chave>/a-receber: o grupo dele na pagina A receber; sem o total liberado, so' a trava. */
export type AReceberDoContratante = {
  anos: string[]; total_a_receber_liberado: boolean; contratante?: ContratanteAReceber | null; quantidade?: number;
};
/** GET /api/contratantes/<chave>/siga: os processos vivos das obras dele, na leitura da tela SIGA. */
export type SigaDoContratante = {
  lido_em: string | null; limites: LimitesSiga; robo: Robo; processos: ProcessoSiga[]; quantidade: number;
};

/** Uma leitura do servidor: lendo, pronta, falhou, ou fora (o perfil nao tem a aba e a pagina nem pede). */
export type Leitura<T> = { estado: "lendo" } | { estado: "pronta"; dado: T } | { estado: "falhou"; erro: string } | { estado: "fora" };

export function useLeitura<T>(caminho: string | null): Leitura<T> {
  // a resposta guarda de que caminho ela e': trocado o caminho, a leitura volta a "lendo" ate' a nova chegar
  const [l, setL] = useState<{ de: string; leitura: Leitura<T> } | null>(null);
  useEffect(() => {
    if (!caminho) return;
    let vivo = true;
    api<T>(caminho).then(dado => { if (vivo) setL({ de: caminho, leitura: { estado: "pronta", dado } }); })
      .catch(e => { if (vivo) setL({ de: caminho, leitura: { estado: "falhou", erro: mensagemDeErro(e) } }); });
    return () => { vivo = false; };
  }, [caminho]);
  if (!caminho) return { estado: "fora" };
  return l && l.de === caminho ? l.leitura : { estado: "lendo" };
}

/** O dado da leitura pronta; lendo, falhou ou fora, nada. */
export function pronta<T>(l: Leitura<T>): T | undefined {
  return l.estado === "pronta" ? l.dado : undefined;
}
