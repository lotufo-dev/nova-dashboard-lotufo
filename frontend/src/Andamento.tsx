import { andamento, foraDaRegua, reaisCurtos, type AndamentoDoServidor, type LeituraDoAndamento } from "./valores";

// Andamento (#805, familias de valor): o ritmo contra o necessario, numa barra. O trilho vai de zero a 130% do
// necessario; a barra e' o ritmo e o risco de tinta marca o necessario (o limite da "adiantada"), para o olho ver de
// relance se a barra passou dele. A palavra diz a leitura e a frase diz a razao.
// A leitura vem pronta do servidor (#822, `prazos.leitura_do_andamento`): a palavra, o percentual e os limites. A
// peca nao compara o ritmo com o necessario; os dois valores so' entram na frase que os mostra. A obra fora da regua
// (prazo no fim, prorrogacao pedida, sem medicao ha' tres competencias) leva o motivo escrito, em tinta e sem barra:
// o motivo nao e' aviso, e' a razao de nao haver leitura. (O aviso de execucao terminando e' so' da operacao: para a
// diretoria, quem diz o prazo no fim e' a Situacao da obra, "Prazo no fim · execução até dd/mm", `SituacaoDaObra`.)

/** Ate' onde vai o trilho, em percentual do necessario: o ritmo acima disso enche a barra inteira. */
const TRILHO_ATE_PCT = 130;

const PALAVRA: Record<LeituraDoAndamento, string> = { adiantada: "Adiantada", atencao: "Atenção", devagar: "Devagar" };

/** O que vai escrito sob a barra:
 *  - "percentual" (padrao): a palavra e a razao ("Devagar · mede 40% do necessário");
 *  - "valores": a palavra, a razao e os dois valores por mes, abreviados ("R$ 3 mi/mês de R$ 7,5 mi"), para a
 *    tabela que nao tem coluna propria para eles (o valor exato esta' na pagina da obra);
 *  - "palavra": so' a palavra, na tabela que ja' traz o percentual e os dois valores em colunas. */
export type DetalheDoAndamento = "percentual" | "valores" | "palavra";

/** A barra do ritmo contra o necessario, com a palavra e a razao, pela `leitura` do servidor; fora da regua, o
 *  motivo. Sem leitura e sem motivo aparece `vazio` (o tracinho da celula de tabela; por padrao, nada). `ritmo` e
 *  `necessario` so' entram no detalhe "valores". A barra e' desenho: quem usa leitor de tela le a frase. */
export default function Andamento({ leitura, ritmo, necessario, detalhe = "percentual", vazio = null }: {
  leitura: AndamentoDoServidor | null | undefined;
  ritmo?: number | null; necessario?: number | null; detalhe?: DetalheDoAndamento; vazio?: React.ReactNode;
}) {
  const a = andamento(leitura);
  if (!a || !leitura) {
    const fora = foraDaRegua(leitura);
    if (!fora) return <>{vazio}</>;
    return (
      <div className="andamento andamento--fora">
        <p className="andamento__texto">
          <span className="andamento__palavra">{fora.palavra}</span>
          {fora.complemento && <> · {fora.complemento}</>}
        </p>
      </div>
    );
  }
  const largura = Math.min(100, Math.max(0, a.pct) * 100 / TRILHO_ATE_PCT);
  const pct = <span className="num">{a.pct.toLocaleString("pt-BR")}%</span>;
  const comValores = detalhe === "valores" && ritmo !== null && ritmo !== undefined && necessario !== null && necessario !== undefined;
  return (
    <div className={`andamento andamento--${a.leitura}`}>
      <span className="andamento__trilho" aria-hidden="true">
        <span className="andamento__barra" style={{ width: `${largura}%` }} />
        <span className="andamento__necessario" style={{ left: `${leitura.adiantada_desde_pct * 100 / TRILHO_ATE_PCT}%` }} />
      </span>
      <p className="andamento__texto">
        <span className="andamento__palavra">{PALAVRA[a.leitura]}</span>
        {detalhe === "percentual" && <> · mede {pct} do necessário</>}
        {detalhe === "valores" && <> · {pct} do necessário</>}
      </p>
      {comValores && (
        <p className="andamento__texto andamento__valores">
          <span className="num">{reaisCurtos(ritmo)}</span>/mês de <span className="num">{reaisCurtos(necessario)}</span>
        </p>
      )}
    </div>
  );
}
