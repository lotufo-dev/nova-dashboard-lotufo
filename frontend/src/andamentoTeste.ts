// So' para os testes: a leitura do andamento como o servidor a manda (`prazos.leitura_do_andamento`, #822), para os
// dados sinteticos nao repetirem o objeto inteiro em cada obra. O corte daqui e' o do servidor, escrito uma vez para
// montar o dado de teste; a tela nao o tem.
import type { AndamentoDoServidor } from "./valores";

export const SEM_LEITURA: AndamentoDoServidor = { situacao: null, pct: null, motivo: null, prorrogacao_pedida: false,
  sem_medicao_desde: null, atencao_desde_pct: 70, adiantada_desde_pct: 100 };

/** A leitura de uma obra dentro da regua: o ritmo sobre o necessario, por piso, no corte de 70% e 100%. Sem
 *  necessario ou sem ritmo, sem leitura. `extra` troca o que o teste quiser (o motivo de ficar fora da regua). */
export function leituraDeTeste(ritmo: number | null | undefined, necessario: number | null | undefined,
    extra: Partial<AndamentoDoServidor> = {}): AndamentoDoServidor {
  if (extra.motivo || ritmo === null || ritmo === undefined || necessario === null || necessario === undefined || necessario <= 0) {
    return { ...SEM_LEITURA, ...extra };
  }
  const pct = Math.floor(ritmo * 100 / necessario);
  return { ...SEM_LEITURA, pct, situacao: pct >= 100 ? "adiantada" : pct >= 70 ? "atencao" : "devagar", ...extra };
}

type ComAndamento = { andamento?: { ritmo_centavos: number | null; necessario_centavos: number | null; leitura?: AndamentoDoServidor | null } | null };

/** A obra de teste com a `leitura` que o servidor mandaria para o ritmo e o necessario dela, quando o dado de teste
 *  nao a traz escrita. */
export function comLeitura<T extends ComAndamento>(o: T): T {
  const a = o.andamento;
  return a && a.leitura === undefined ? { ...o, andamento: { ...a, leitura: leituraDeTeste(a.ritmo_centavos, a.necessario_centavos) } } : o;
}
