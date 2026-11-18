import { brl } from "./formato";
import { diferenca } from "./valores";

// Diferenca (#805, familias de valor): quanto um valor se afasta de outro que deveria ser igual (o aprovado e o
// pedido). Igual leva o sinal de igual, no tom do bom. Abaixo mostra o corte em reais e em percentual da base, no tom
// da atencao ou no do critico. Acima diz o sentido por escrito e fica sempre no tom da atencao. Quem soma o corte e o
// acima, aplica a tolerancia de arredondamento e guarda o limite e' o servidor (valores.ts diz por que).

/** A diferenca contra `base`: `abaixo` e' o quanto ficou abaixo dela (o corte) e `acima`, o quanto passou. No nivel
 *  que soma varias linhas (mes, obra, ano) so' o corte entra: quem chama nao passa `acima`. `nomeBase` e' como a base
 *  se chama na frase ("pedido": "igual ao pedido", "abaixo do pedido"). `limitePorMil` e' o limite que o servidor
 *  manda (5 = 0,5% da base). Sem base, ou sem o corte do servidor, nada aparece. */
export default function Diferenca({ abaixo, acima, base, nomeBase, limitePorMil }: {
  abaixo: number | null | undefined; acima?: number | null; base: number | null | undefined; nomeBase: string; limitePorMil: number;
}) {
  const d = diferenca(abaixo, acima, base, limitePorMil);
  if (!d) return null;
  if (d.sentido === "igual") {
    return (
      <span className="diferenca diferenca--igual">
        <span className="diferenca__parte"><span aria-hidden="true">= </span>igual ao {nomeBase}</span>
      </span>
    );
  }
  const reais = brl(d.centavos);
  if (d.sentido === "acima") {
    return (
      <span className="diferenca diferenca--leve">
        <span className="diferenca__parte"><span aria-hidden="true">+ </span>{reais}</span>
        <span className="diferenca__parte">acima do {nomeBase}</span>
      </span>
    );
  }
  // "< 0,1%" ja' diz que e' pouco; o sinal vai no percentual que tem numero
  const pct = d.percentual.startsWith("<") ? d.percentual : `\u2212${d.percentual}`;
  return (
    <span className={`diferenca diferenca--${d.tom}`}>
      <span className="diferenca__parte" aria-hidden="true">{"\u2212"} {reais}</span>
      <span className="diferenca__parte" aria-hidden="true">({pct})</span>
      <span className="sr-only">{reais} abaixo do {nomeBase}, {d.percentual.replace("< ", "menos de ")}</span>
    </span>
  );
}
