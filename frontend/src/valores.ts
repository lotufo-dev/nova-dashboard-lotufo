// Familias de valor (#805, decisao do dono de 18/11/2026): as contas e os limites das pecas Variacao.tsx,
// Diferenca.tsx, Andamento.tsx e MarcaEtapa.tsx, num lugar so'. A regra esta' em docs/identidade-visual.md, secao
// "Valores". Os valores comparados vem do servidor (a mesma conta nos dois lados); aqui so' a razao entre eles, para
// a etiqueta. Limite em inteiros, sem arredondar antes de comparar.

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

/** O tom e os dois numeros da diferenca; nulo quando nao ha' base (nula, zero ou negativa) ou valor. Critica e' a
 *  diferenca que passa de `limitePorMil` milesimos da base, o limite fora. O limite nao mora aqui: vem do servidor,
 *  que e' quem ja' o usa no aviso "aprovado abaixo do pedido" (#741), para a tela e o aviso nunca discordarem. O
 *  percentual tem uma casa; o que arredonda para zero sai como "< 0,1%", para a etiqueta nao dizer "0,0%" de uma
 *  diferenca que existe. */
export function diferenca(valor: number | null | undefined, base: number | null | undefined, limitePorMil: number):
    { tom: TomDaDiferenca; centavos: number; percentual: string } | null {
  if (valor === null || valor === undefined || base === null || base === undefined || base <= 0) return null;
  const centavos = valor - base;
  if (centavos === 0) return { tom: "igual", centavos, percentual: "" };
  const decimos = Math.round(Math.abs(centavos) * 1000 / base);
  return { tom: Math.abs(centavos) * 1000 > base * limitePorMil ? "ruim" : "leve", centavos,
    percentual: decimos === 0 ? "< 0,1%" : umaCasa(decimos) };
}

// ---------------------------------------------------------------- andamento

/** Os limites do andamento: a partir de 100% do necessario, adiantada; de 70% a 99%, atencao; abaixo de 70%, devagar. */
export const ADIANTADA_DESDE_PCT = 100;
export const ATENCAO_DESDE_PCT = 70;

export type LeituraDoAndamento = "adiantada" | "atencao" | "devagar";

/** A leitura e o percentual inteiro do ritmo sobre o necessario; nulo sem necessario (nulo ou zero) ou sem ritmo. O
 *  percentual arredonda para baixo: 99,6% ainda e' atencao, e a frase nao pode dizer "100%" ao lado dessa palavra. */
export function andamento(ritmo: number | null | undefined, necessario: number | null | undefined):
    { leitura: LeituraDoAndamento; pct: number } | null {
  if (ritmo === null || ritmo === undefined || ritmo < 0 || necessario === null || necessario === undefined || necessario <= 0) return null;
  const pct = Math.floor(ritmo * 100 / necessario);
  return { leitura: pct >= ADIANTADA_DESDE_PCT ? "adiantada" : pct >= ATENCAO_DESDE_PCT ? "atencao" : "devagar", pct };
}
