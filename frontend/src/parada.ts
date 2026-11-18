import type { Situacao } from "./situacao";

// Tempo parado (#805, a quinta familia de valor de docs/identidade-visual.md): o que o servidor manda sobre ha' quanto
// tempo uma medicao esta' na situacao atual, e o texto disso. A conta, os limites e a situacao sao do servidor
// (`fila_medicoes._parada`); a peca que desenha e' TempoParado.tsx.

/** `desde` e' o dia do evento que abriu a situacao (AAAA-MM-DD); `dias_uteis` nao conta hoje; `hoje` diz que o evento
 *  foi hoje; `situacao` e' a leitura do tempo (nula sem a data do evento). `esperada` e `prazo_orgao_dias` so' no
 *  Pagamento, com o prazo do orgao (docs/adr/0007); `alem_do_prazo`, quando a data esperada ja' passou. */
export type Parada = {
  desde: string | null; dias_uteis: number | null; hoje: boolean; situacao: Situacao | null;
  prazo_orgao_dias: number | null; esperada: string | null; alem_do_prazo: boolean;
};

/** "hoje", "menos de 1 dia útil" (o evento foi no fim de semana ou no feriado), "1 dia útil", "12 dias úteis"; sem a
 *  data do evento, "—". */
export function textoDoTempo(p: Pick<Parada, "dias_uteis" | "hoje">): string {
  if (p.dias_uteis === null) return "—";
  if (p.hoje) return "hoje";
  if (p.dias_uteis < 1) return "menos de 1 dia útil";
  return p.dias_uteis === 1 ? "1 dia útil" : `${p.dias_uteis.toLocaleString("pt-BR")} dias úteis`;
}

/** O mesmo tempo dito em frase, para onde nao ha' a coluna "Parada há" por cima (o cartao do Resumo das medicoes):
 *  "desde hoje", "há menos de 1 dia útil", "há 12 dias úteis". */
export function fraseDoTempo(p: Pick<Parada, "dias_uteis" | "hoje">): string {
  return p.hoje ? "desde hoje" : `há ${textoDoTempo(p)}`;
}
