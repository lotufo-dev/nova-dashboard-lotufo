import { brl } from "./formato";
import { IconeMais } from "./icones";
import { Link } from "./Link";
import { nivelParada, textoParada, type LinhaResumo } from "./resumoMedicoes";
import { fmtCompetencia } from "./tempo";
import "./abaFaturamento.css";

// Aba "Enviar ao faturamento" (#155, prototipo aprovado pelo Leo em 14/10/2026): uma caixa por contratante e uma
// linha por medicao. O botao abre a medicao na etapa 2 (a conferencia de destinatarios e
// anexos); nao envia direto da lista. "Parada ha'" e' o marco do servidor (`medicoes.resumo`): sem marco, "—".

type GrupoFaturamento = { contratante: string; linhas: LinhaResumo[] };

const maiorParada = (ls: LinhaResumo[]) => Math.max(...ls.map(l => l.dias ?? -1));

/** Linhas por contratante: o que tem a medicao parada ha' mais tempo primeiro (sem marco conta como o menos
 *  parado; empate pelo nome). Dentro do grupo, a ordem do servidor. */
function agruparFaturamento(linhas: LinhaResumo[]): GrupoFaturamento[] {
  const m = new Map<string, LinhaResumo[]>();
  // o servidor manda contratante nulo quando a obra nao esta' mais ativa no cadastro
  for (const l of linhas) { const c = l.contratante ?? "Órgão sem cadastro"; m.set(c, [...(m.get(c) ?? []), l]); }
  return [...m.entries()]
    .map(([contratante, ls]) => ({ contratante, linhas: ls }))
    .sort((a, b) => maiorParada(b.linhas) - maiorParada(a.linhas) || a.contratante.localeCompare(b.contratante, "pt-BR"));
}

function IconeEnviar() {
  return <svg className="icone icone--p" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14" /><path d="M13 6l6 6-6 6" /></svg>;
}

function Parada({ l }: { l: LinhaResumo }) {
  if (l.dias === null) return <span className="fat-parada medicoes__traco">{"—"}</span>;
  const nivel = nivelParada(l.dias, "faturamento");
  return (
    <span className="fat-parada">
      <span className="fat-parada__rot">Parada há </span>
      <span className={nivel ? `medicoes__parada medicoes__parada--${nivel}` : "medicoes__parada"}>{textoParada(l.dias)}</span>
    </span>
  );
}

export default function AbaFaturamento({ linhas, podeIniciar, aoIniciar }:
    { linhas: LinhaResumo[]; podeIniciar: boolean; aoIniciar: () => void }) {
  const grupos = agruparFaturamento(linhas);
  return (
    <>
      {podeIniciar && (
        <div className="medicoes__acoes">
          <button type="button" className="btn btn--primario medicoes__iniciar" onClick={aoIniciar}>
            <IconeMais className="icone" />Iniciar processo de medição
          </button>
        </div>
      )}
      {grupos.length === 0 ? (
        <section className="medicoes__quadro">
          <div className="vazio"><p className="vazio__titulo">Nenhum espelho esperando o envio ao faturamento.</p></div>
        </section>
      ) : (
        <div className="fat-grupos">
          {grupos.map((g, i) => (
            <section key={g.contratante} className="medicoes__quadro" aria-labelledby={`fat-${i}`}>
              <h2 className="fat-grupo__cabeca" id={`fat-${i}`}>{g.contratante}</h2>
              <ul className="fat-lista">
                {g.linhas.map(l => (
                  <li key={l.medicao_id} className="fat-linha">
                    <div>
                      <Link className="fat-linha__obra" para={{ tela: "obra", id: l.contrato_id, aba: "medicoes" }}>{l.obra}</Link>
                      {l.orgao_sub && <span className="medicoes__sub">{l.orgao_sub}</span>}
                      <span className="fat-linha__detalhe">
                        <Link para={{ tela: "medicao", obra: l.contrato_id, id: l.medicao_id }} secao="etapa-2">{l.titulo}</Link>
                        {" · competência "}<span className="dinheiro">{fmtCompetencia(l.competencia)}</span>
                      </span>
                    </div>
                    <span className="dinheiro fat-linha__valor">{brl(l.valor_centavos)}</span>
                    <Parada l={l} />
                    {/* quem so' consulta (diretoria) nao ve o botao; o titulo da medicao segue levando a' etapa 2 */}
                    {podeIniciar && (
                      <Link className="btn btn--primario" para={{ tela: "medicao", obra: l.contrato_id, id: l.medicao_id }} secao="etapa-2"
                        aria-label={`Enviar ao faturamento: ${l.obra}, ${l.titulo}`}>
                        Enviar ao faturamento<IconeEnviar />
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
