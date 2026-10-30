// Numeros que nao sao dinheiro nem data (DESIGN.md › Numeros e datas): virgula decimal, e espaco
// NAO separavel entre o numero e a unidade ("1,5 MB" nunca quebra entre o 5 e o MB). Dinheiro e'
// `brl` (aqui, re-exportado por Medicoes.tsx); data e competencia moram em tempo.ts. Nada de `toFixed` +
// `replace` a mao.

/** Dinheiro: "R$ 1.234.567,89"; nulo vira tracinho e negativo leva o sinal de menos (U+2212), nao o hifen:
 *  "−R$ 5.555.566,66" (DESIGN.md › Numeros e datas). Centavos inteiros. */
export function brl(centavos: number | null): string {
  if (centavos === null) return "\u2014";
  const texto = (centavos / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  return texto.startsWith("-") ? `\u2212${texto.slice(1)}` : texto;
}

/** Contagem com o substantivo no numero certo: "1 medição", "3 medições" (milhar pt-BR). */
export function contar(n: number, um: string, varios: string): string {
  return `${n.toLocaleString("pt-BR")} ${n === 1 ? um : varios}`;
}

const NBSP = "\u00a0";

/** Tamanho de arquivo: "48 KB" ou "1,5 MB" (arquivo menor que 1 KB aparece como 1 KB). */
export function fmtTamanho(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    const mb = (bytes / 1024 / 1024).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    return `${mb}${NBSP}MB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))}${NBSP}KB`;
}

/** Dias: "1 dia", "1.234 dias" (milhar pt-BR; o numero nao se separa da unidade). */
export function fmtDias(n: number): string {
  return `${n.toLocaleString("pt-BR")}${NBSP}${n === 1 ? "dia" : "dias"}`;
}

/** Fracao -> percentual pt-BR: 0,4 -> "40%"; 0,0462 -> "4,62%". Com `fixas`, sempre `casas` decimais, para coluna
 *  alinhada: fmtPercentual(0,298, 1, true) -> "29,8%"; fmtPercentual(0,01, 1, true) -> "1,0%". */
export function fmtPercentual(fracao: number, casas = 2, fixas = false): string {
  return fracao.toLocaleString("pt-BR", {
    style: "percent", maximumFractionDigits: casas, ...(fixas ? { minimumFractionDigits: casas } : {}),
  });
}

/** A cota da Lotufo no cabecalho da obra e da medicao (F-50): "cota 40%" so' em consorcio; com 100%, null. */
export function baseDosValores(percentualBp: number): string | null {
  return percentualBp === 10000 ? null : `cota ${fmtPercentual(percentualBp / 10000)}`;
}

// Campo de valor em dinheiro (issue #190): os digitos entram pela direita, como em caixa registradora. Tudo
// em texto (os digitos sao os centavos), sem `float` no caminho; o servidor converte com o parse_brl.

/** Teto do parse_brl do servidor (R$ 99.999.999.999,99): 13 digitos de centavos. */
export const MAX_DIGITOS_VALOR = 13;

/** Digitos dos centavos -> texto do campo: "1" -> "0,01", "5000000" -> "50.000,00"; so' zeros -> "0,00";
 *  sem digitos -> "". */
export function digitosParaBrl(digitos: string): string {
  const todos = digitos.replace(/\D/g, "");
  if (!todos) return "";
  const d = todos.replace(/^0+/, "");
  if (!d) return "0,00";
  const cheio = d.padStart(3, "0");
  const inteiro = cheio.slice(0, -2).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${inteiro},${cheio.slice(-2)}`;
}

// o mesmo formato que o parse_brl do servidor aceita (app/dinheiro.py, _PADRAO_BRL)
const PADRAO_COLADO = /^([0-9]{1,3}(\.[0-9]{3})*|[0-9]+)(,[0-9]{1,2})?$/;

/** Texto colado, em reais -> texto do campo: "50.000,00", "50000,5" e "50000" viram "50.000,00", "50.000,50" e
 *  "50.000,00" (sem virgula e' real, nao centavo). Formato que o servidor recusaria (ex.: "1234.56") ou acima do
 *  teto -> null. */
export function coladoParaBrl(texto: string): string | null {
  const limpo = texto.replace("R$", "").replace(/[\s ]/g, "");
  if (!PADRAO_COLADO.test(limpo)) return null;
  const [inteiro, dec = ""] = limpo.replace(/\./g, "").split(",");
  const digitos = (inteiro + dec.padEnd(2, "0")).replace(/^0+/, "");
  if (digitos.length > MAX_DIGITOS_VALOR) return null;
  return digitos ? digitosParaBrl(digitos) : "0,00";
}
