import { andamento, reaisCurtos, type LeituraDoAndamento } from "./valores";

// Andamento (#805, familias de valor): o ritmo contra o necessario, numa barra. O trilho vai de zero a 130% do
// necessario; a barra e' o ritmo e o risco de tinta marca o necessario (100%), para o olho ver de relance se a barra
// passou dele. A palavra diz a leitura e a frase diz a razao. Os dois numeros vem do servidor, na mesma unidade; os
// limites (100% e 70%) estao em valores.ts.

/** Ate' onde vai o trilho, em percentual do necessario: o ritmo acima disso enche a barra inteira. */
const TRILHO_ATE_PCT = 130;

const PALAVRA: Record<LeituraDoAndamento, string> = { adiantada: "Adiantada", atencao: "Atenção", devagar: "Devagar" };

/** O que vai escrito sob a barra:
 *  - "percentual" (padrao): a palavra e a razao ("Devagar · mede 27% do necessário");
 *  - "valores": a palavra, a razao e os dois valores por mes, abreviados ("R$ 2,4 mi/mês de R$ 8,8 mi"), para a
 *    tabela que nao tem coluna propria para eles (o valor exato esta' na pagina da obra);
 *  - "palavra": so' a palavra, na tabela que ja' traz o percentual e os dois valores em colunas. */
export type DetalheDoAndamento = "percentual" | "valores" | "palavra";

/** A barra do ritmo contra o necessario, com a palavra e a razao. Sem necessario ou sem ritmo, nada aparece. A barra
 *  e' desenho: quem usa leitor de tela le a frase. */
export default function Andamento({ ritmo, necessario, detalhe = "percentual" }: {
  ritmo: number | null | undefined; necessario: number | null | undefined; detalhe?: DetalheDoAndamento;
}) {
  const a = andamento(ritmo, necessario);
  if (!a || ritmo === null || ritmo === undefined || necessario === null || necessario === undefined) return null;
  const largura = Math.min(100, a.pct * 100 / TRILHO_ATE_PCT);
  const pct = <span className="num">{a.pct.toLocaleString("pt-BR")}%</span>;
  return (
    <div className={`andamento andamento--${a.leitura}`}>
      <span className="andamento__trilho" aria-hidden="true">
        <span className="andamento__barra" style={{ width: `${largura}%` }} />
        <span className="andamento__necessario" style={{ left: `${100 * 100 / TRILHO_ATE_PCT}%` }} />
      </span>
      <p className="andamento__texto">
        <span className="andamento__palavra">{PALAVRA[a.leitura]}</span>
        {detalhe === "percentual" && <> · mede {pct} do necessário</>}
        {detalhe === "valores" && <> · {pct} do necessário</>}
      </p>
      {detalhe === "valores" && (
        <p className="andamento__texto andamento__valores">
          <span className="num">{reaisCurtos(ritmo)}</span>/mês de <span className="num">{reaisCurtos(necessario)}</span>
        </p>
      )}
    </div>
  );
}
