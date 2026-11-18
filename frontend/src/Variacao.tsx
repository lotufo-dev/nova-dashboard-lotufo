import { variacao, type Direcao } from "./valores";

// Variacao (#805, familias de valor): o valor contra uma referencia escrita ("× set", "× out/25"). A seta diz a
// direcao e a cor diz se e' bom: no que quanto maior, melhor (medido, protocolado), subir e' bom; no que quanto menor,
// melhor (em aberto), cair e' bom. As formas (▲ ▼ ●) nao sao as dos glifos de situacao, de proposito: valor nao e'
// situacao. Os dois valores vem do servidor (a mesma conta nos dois periodos); a conta da razao esta' em valores.ts.

type Sentido = "maior-e-melhor" | "menor-e-melhor";

const SETA: Record<Direcao, string> = { subiu: "▲", caiu: "▼", estavel: "●" };

/** A variacao de `atual` contra `referencia`. `rotulo` e' o nome curto da referencia, que vai escrito depois do "×"
 *  ("set", "out/25", "out até o dia 18"); `porExtenso` e' o mesmo nome para o leitor de tela ("setembro", "outubro de
 *  2025"). Sem referencia (nula ou zero), nada aparece. */
export default function Variacao({ atual, referencia, rotulo, porExtenso, sentido = "maior-e-melhor" }: {
  atual: number | null | undefined; referencia: number | null | undefined; rotulo: string; porExtenso: string; sentido?: Sentido;
}) {
  const v = variacao(atual, referencia);
  if (!v) return null;
  const bom = sentido === "maior-e-melhor" ? v.direcao === "subiu" : v.direcao === "caiu";
  const tom = v.direcao === "estavel" ? "estavel" : bom ? "bom" : "ruim";
  const sinal = v.direcao === "subiu" ? "+" : "−";
  return (
    <span className={`variacao variacao--${tom}`}>
      <span className="variacao__parte" aria-hidden="true">
        {SETA[v.direcao]} {v.direcao === "estavel" ? "estável" : `${sinal}${v.percentual}`}
      </span>
      <span className="variacao__parte" aria-hidden="true">× {rotulo}</span>
      <span className="sr-only">
        {v.direcao === "estavel" ? `estável em relação a ${porExtenso}` : `${v.direcao} ${v.percentual} em relação a ${porExtenso}`}
      </span>
    </span>
  );
}
