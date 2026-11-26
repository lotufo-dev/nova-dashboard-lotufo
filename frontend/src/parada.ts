import type { Situacao } from "./situacao";

// Tempo parado (#805, a quinta familia de valor de docs/identidade-visual.md): o que o servidor manda sobre ha' quanto
// tempo uma medicao esta' na situacao atual, e o texto disso. A conta, os limites e a situacao sao do servidor
// (`fila_medicoes._parada`); a peca que desenha e' TempoParado.tsx.

/** Em que revisao esta' a cobranca da medicao reapresentada (#914, `medicoes.revisoes_do_protocolo`): o primeiro
 *  protocolo da nota (de onde contam os dias e a data esperada), quantas vezes foi reapresentada e o ultimo envio,
 *  que e' so' informacao. */
export type Revisao = { primeiro_protocolo_em: string; reapresentacoes: number; ultimo_envio_em: string };

/** `desde` e' o dia do evento que abriu a situacao (AAAA-MM-DD); `dias_uteis` nao conta hoje; `hoje` diz que o evento
 *  foi hoje; `situacao` e' a leitura do tempo (nula sem a data do evento). `esperada` e `prazo_orgao_dias` so' no
 *  Pagamento, com o prazo do orgao (docs/adr/0007); `alem_do_prazo`, quando a data esperada ja' passou. `revisao`, so'
 *  no Pagamento da medicao reapresentada (#914); nula na de protocolo unico. */
export type Parada = {
  desde: string | null; dias_uteis: number | null; hoje: boolean; situacao: Situacao | null;
  prazo_orgao_dias: number | null; esperada: string | null; alem_do_prazo: boolean; revisao: Revisao | null;
};

/** As tres partes da revisao (#914), na ordem em que a tela as escreve: "1º protocolo em 03/11", "reapresentada 2
 *  vezes", "último envio em 18/11". `dia` formata a data (o `fmtDiaNoAno` da tela: sem o ano no ano de hoje). */
export function partesDaRevisao(r: Revisao, dia: (iso: string) => string | null): string[] {
  const vezes = r.reapresentacoes === 1 ? "1 vez" : `${r.reapresentacoes.toLocaleString("pt-BR")} vezes`;
  return [`1º protocolo em ${dia(r.primeiro_protocolo_em) ?? "—"}`, `reapresentada ${vezes}`,
          `último envio em ${dia(r.ultimo_envio_em) ?? "—"}`];
}

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
