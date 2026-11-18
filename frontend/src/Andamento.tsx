import { andamento, type LeituraDoAndamento } from "./valores";

// Andamento (#805, familias de valor): o ritmo contra o necessario, numa barra. O trilho vai de zero a 130% do
// necessario; a barra e' o ritmo e o risco de tinta marca o necessario (100%), para o olho ver de relance se a barra
// passou dele. A palavra diz a leitura e a frase diz a razao. Os dois numeros vem do servidor, na mesma unidade; os
// limites (100% e 70%) estao em valores.ts.

/** Ate' onde vai o trilho, em percentual do necessario: o ritmo acima disso enche a barra inteira. */
const TRILHO_ATE_PCT = 130;

const PALAVRA: Record<LeituraDoAndamento, string> = { adiantada: "Adiantada", atencao: "Atenção", devagar: "Devagar" };

/** A barra do ritmo contra o necessario, com a palavra e a razao. Sem necessario ou sem ritmo, nada aparece. A barra
 *  e' desenho: quem usa leitor de tela le a frase. */
export default function Andamento({ ritmo, necessario }: { ritmo: number | null | undefined; necessario: number | null | undefined }) {
  const a = andamento(ritmo, necessario);
  if (!a) return null;
  const largura = Math.min(100, a.pct * 100 / TRILHO_ATE_PCT);
  return (
    <div className={`andamento andamento--${a.leitura}`}>
      <span className="andamento__trilho" aria-hidden="true">
        <span className="andamento__barra" style={{ width: `${largura}%` }} />
        <span className="andamento__necessario" style={{ left: `${100 * 100 / TRILHO_ATE_PCT}%` }} />
      </span>
      <p className="andamento__texto">
        <span className="andamento__palavra">{PALAVRA[a.leitura]}</span> · mede <span className="num">{a.pct.toLocaleString("pt-BR")}%</span> do necessário
      </p>
    </div>
  );
}
