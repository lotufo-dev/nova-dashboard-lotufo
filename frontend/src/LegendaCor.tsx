import { Glifo } from "./Selo";
import type { Situacao } from "./situacao";

// Legenda das situacoes, no topo direito das telas que as usam: o glifo de cada situacao (a mesma peca do selo) e a
// palavra. Cada tela que aplica a regra a coloca; aqui so' o componente. `itens` troca as palavras quando a tela tem
// nomes proprios para as situacoes (em dia, vencida); sem ele, as quatro da regra.
export type ItemLegenda = { situacao: Situacao; texto: string };

const ITENS: ItemLegenda[] = [
  { situacao: "feito", texto: "feito" },
  { situacao: "andamento", texto: "em andamento" },
  { situacao: "breve", texto: "vence em breve" },
  { situacao: "critico", texto: "crítico" },
];

export default function LegendaCor({ itens = ITENS }: { itens?: ItemLegenda[] }) {
  return (
    <ul className="legenda-cor" aria-label="Legenda das cores">
      {itens.map(i => (
        <li key={i.texto}><Glifo situacao={i.situacao} />{i.texto}</li>
      ))}
    </ul>
  );
}
