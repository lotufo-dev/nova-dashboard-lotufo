import { brl } from "./formato";
import { diferenca } from "./valores";

// Diferenca (#805, familias de valor): quanto um valor se afasta de outro que deveria ser igual (o aprovado e o
// pedido). Igual leva o sinal de igual, no tom do bom; diferente mostra a diferenca em reais e em percentual da base.
// O limite que separa a diferenca pequena da critica vem do servidor (valores.ts diz por que).

/** A diferenca de `valor` contra `base`. `nomeBase` e' como a base se chama na frase ("pedido": "igual ao pedido",
 *  "abaixo do pedido"). `limitePorMil` e' o limite que o servidor manda (5 = 0,5% da base). Sem base, nada aparece. */
export default function Diferenca({ valor, base, nomeBase, limitePorMil }: {
  valor: number | null | undefined; base: number | null | undefined; nomeBase: string; limitePorMil: number;
}) {
  const d = diferenca(valor, base, limitePorMil);
  if (!d) return null;
  if (d.tom === "igual") {
    return (
      <span className="diferenca diferenca--igual">
        <span className="diferenca__parte"><span aria-hidden="true">= </span>igual ao {nomeBase}</span>
      </span>
    );
  }
  const sinal = d.centavos > 0 ? "+" : "−";
  const reais = brl(Math.abs(d.centavos));
  // "< 0,1%" ja' diz que e' pouco; o sinal vai no percentual que tem numero
  const pct = d.percentual.startsWith("<") ? d.percentual : `${sinal}${d.percentual}`;
  return (
    <span className={`diferenca diferenca--${d.tom}`}>
      <span className="diferenca__parte" aria-hidden="true">{sinal} {reais}</span>
      <span className="diferenca__parte" aria-hidden="true">({pct})</span>
      <span className="sr-only">
        {reais} {d.centavos > 0 ? "acima" : "abaixo"} do {nomeBase}, {d.percentual.replace("< ", "menos de ")}
      </span>
    </span>
  );
}
