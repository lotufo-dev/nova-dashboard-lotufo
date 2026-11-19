// Familias de valor (#805, decisao do dono de 18/11/2026): as contas e os limites das pecas Variacao.tsx,
// Diferenca.tsx, Andamento.tsx e MarcaEtapa.tsx, num lugar so'. A regra esta' em docs/identidade-visual.md, secao
// "Valores". Os valores comparados vem do servidor (a mesma conta nos dois lados); aqui so' a razao entre eles, para
// a etiqueta. Limite em inteiros, sem arredondar antes de comparar. O andamento vem lido do servidor (#822).

import { fmtCompetencia } from "./tempo";

// ---------------------------------------------------------------- etapa do dinheiro

/** As etapas do ciclo, do azul claro da analise ao verde do recebido. O "em aberto" nao e' etapa do ciclo (e' o que
 *  falta receber) e o "atrasado" e' a protocolada alem do prazo do orgao. */
export type Etapa = "em_analise" | "boletim" | "nota" | "protocolado" | "recebido" | "em_aberto" | "atrasado";

export const ROTULO_DA_ETAPA: Record<Etapa, string> = {
  em_analise: "Em análise", boletim: "Boletim", nota: "Nota", protocolado: "Protocolado", recebido: "Recebido",
  em_aberto: "Em aberto", atrasado: "Atrasado",
};

// ---------------------------------------------------------------- variacao

/** Ate' quanto a variacao, para cima ou para baixo, conta como estavel: 2% da referencia. */
export const ESTAVEL_ATE_PCT = 2;

export type Direcao = "subiu" | "caiu" | "estavel";

const umaCasa = (decimos: number) => `${(decimos / 10).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;

/** A direcao e o percentual (uma casa) da variacao; nulo quando nao ha' com o que comparar (referencia nula, zero ou
 *  negativa). Estavel e' a variacao de ate' 2% da referencia, o limite incluido. */
export function variacao(atual: number | null | undefined, referencia: number | null | undefined):
    { direcao: Direcao; percentual: string } | null {
  if (atual === null || atual === undefined || referencia === null || referencia === undefined || referencia <= 0) return null;
  const delta = atual - referencia;
  const direcao: Direcao = Math.abs(delta) * 100 <= referencia * ESTAVEL_ATE_PCT ? "estavel" : delta > 0 ? "subiu" : "caiu";
  return { direcao, percentual: umaCasa(Math.round(Math.abs(delta) * 1000 / referencia)) };
}

// ---------------------------------------------------------------- diferenca

export type TomDaDiferenca = "igual" | "leve" | "ruim";
export type SentidoDaDiferenca = "igual" | "abaixo" | "acima";

/** A leitura da diferenca entre um valor e a base dele, a partir do que o servidor ja' somou: quanto ficou ABAIXO
 *  da base (o corte) e, so' onde faz sentido mostrar, quanto ficou ACIMA. Nulo quando nao ha' base (nula, zero ou
 *  negativa) ou o servidor nao mandou o corte.
 *  - Abaixo: o tom sai do tamanho do corte sobre a base. Critico e' o corte que passa de `limitePorMil` milesimos
 *    dela, o limite fora. O limite nao mora aqui: vem do servidor, que e' quem ja' o usa no aviso "aprovado abaixo do
 *    pedido" (#741), para a tela e o aviso nunca discordarem. O percentual tem uma casa; o que arredonda para zero
 *    sai como "< 0,1%", para a etiqueta nao dizer "0,0%" de um corte que existe.
 *  - Acima: sempre o tom da atencao, nunca critico, e sem percentual. O valor acima da base quase sempre e' a base
 *    gravada errada (revisao da PR #806), e "+900%" em vermelho acusaria o que nao houve.
 *  - Sem um nem outro, igual. A tolerancia de arredondamento e' do servidor: o que ele nao conta como corte nem como
 *    acima chega aqui como zero. */
export function diferenca(abaixo: number | null | undefined, acima: number | null | undefined, base: number | null | undefined,
    limitePorMil: number): { sentido: SentidoDaDiferenca; tom: TomDaDiferenca; centavos: number; percentual: string } | null {
  if (abaixo === null || abaixo === undefined || base === null || base === undefined || base <= 0) return null;
  if (abaixo > 0) {
    const decimos = Math.round(abaixo * 1000 / base);
    return { sentido: "abaixo", tom: abaixo * 1000 > base * limitePorMil ? "ruim" : "leve", centavos: abaixo,
      percentual: decimos === 0 ? "< 0,1%" : umaCasa(decimos) };
  }
  if (acima !== null && acima !== undefined && acima > 0) return { sentido: "acima", tom: "leve", centavos: acima, percentual: "" };
  return { sentido: "igual", tom: "igual", centavos: 0, percentual: "" };
}

// ---------------------------------------------------------------- andamento

export type LeituraDoAndamento = "adiantada" | "atencao" | "devagar";

/** Por que a obra com prazo a cumprir ficou fora da regua (decisao do dono de 18/11/2026, #822). */
export type MotivoForaDaRegua = "prazo_no_fim" | "prorrogacao_pedida" | "sem_medicao";

/** A leitura do andamento como o servidor a manda (`prazos.leitura_do_andamento`), a mesma em `/api/contratos`
 *  (`andamento.leitura`) e na ficha da obra (`ritmo.leitura`). O corte (70% e 100%) e' dele: a tela nao o repete, so'
 *  escreve a palavra, o percentual e o motivo que chegam. Com `situacao`, vem o `pct` (inteiro, por piso); sem ela, o
 *  `motivo` de a obra ficar fora da regua, ou nada (sem prazo a cumprir, ou obra que ainda nao mediu). Os dois
 *  limites vem junto, para o desenho da barra. */
export type AndamentoDoServidor = {
  situacao: LeituraDoAndamento | null; pct: number | null;
  motivo: MotivoForaDaRegua | null; prorrogacao_pedida: boolean; sem_medicao_desde: string | null;
  atencao_desde_pct: number; adiantada_desde_pct: number;
};

/** A leitura (Adiantada, Atencao, Devagar) e o percentual do necessario que o servidor mandou; nulo na obra sem
 *  leitura (sem prazo a cumprir, sem ritmo ou fora da regua). */
export function andamento(l: AndamentoDoServidor | null | undefined): { leitura: LeituraDoAndamento; pct: number } | null {
  return l && l.situacao !== null && l.pct !== null ? { leitura: l.situacao, pct: l.pct } : null;
}

/** O que a tela escreve no lugar da leitura na obra fora da regua: o prazo no fim (com o pedido de prorrogacao, se
 *  ha'), o pedido de prorrogacao sem resposta ou o mes da ultima medicao de execucao. Nulo quando nao ha' o que
 *  escrever: a celula fica com o tracinho. */
export function foraDaRegua(l: AndamentoDoServidor | null | undefined): { palavra: string; complemento: string | null } | null {
  if (!l || l.situacao !== null) return null;
  if (l.motivo === "prazo_no_fim") return { palavra: "Prazo no fim", complemento: l.prorrogacao_pedida ? "prorrogação pedida" : null };
  if (l.motivo === "prorrogacao_pedida") return { palavra: "Prorrogação pedida", complemento: null };
  if (l.motivo === "sem_medicao" && l.sem_medicao_desde) return { palavra: `Sem medição desde ${fmtCompetencia(l.sem_medicao_desde)}`, complemento: null };
  return null;
}

/** A obra tem o que escrever no andamento? A leitura, ou o motivo de estar fora da regua. Sem um nem outro a peca
 *  `Andamento` nao desenha nada, e quem a usa poe o tracinho. */
export function temAndamento(l: AndamentoDoServidor | null | undefined): boolean {
  return andamento(l) !== null || foraDaRegua(l) !== null;
}

/** Valor em reais abreviado, so' para a frase do andamento ("R$ 3 mi/mês de R$ 7,5 mi"): "R$ 7,5 mi", "R$ 500 mil",
 *  "R$ 900". E' leitura de ordem de grandeza ao lado do percentual; o valor exato fica na coluna propria ou na pagina
 *  da obra, com `brl`. */
export function reaisCurtos(centavos: number): string {
  return `R$ ${(centavos / 100).toLocaleString("pt-BR", { notation: "compact", maximumFractionDigits: 1 })}`;
}
