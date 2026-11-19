import { Fragment } from "react";
import { Link } from "./Link";
import MarcaEtapa from "./MarcaEtapa";
import { fmtCompetencia, fmtMesCurto } from "./tempo";
import type { Etapa } from "./valores";
import "./resumoMatriz.css";

// Matriz obra por competencia (#659). Ate' 19/11/2026 ficava na Inicio; a decisao do dono de 19/11/2026 (#805) a trouxe
// para o Resumo das medicoes, na aba "Últimos 12 meses". Tudo vem pronto de GET /api/resumo-medicoes/matriz
// (`resumo_medicoes.matriz`, a mesma conta de antes): a tela so' desenha. Nao tem valor, so' a etapa de cada mes.

/** #659: a etapa da medicao de uma competencia; `atrasado` = protocolada alem do prazo do contratante (a regra da
 *  previsao de entrada da Inicio). Celula nula = sem medicao na competencia */
export type EtapaMatriz = "em_analise" | "boletim" | "nota" | "protocolado" | "atrasado" | "recebida";
type CelulaMatriz = { etapa: EtapaMatriz; medicao_id: number } | null;
type ObraMatriz = { contrato_id: number; obra: string; celulas: CelulaMatriz[] };
export type RespostaMatriz = { competencias: string[]; grupos: { contratante: string; obras: ObraMatriz[] }[] };

// as etapas na ordem da legenda: do azul mais claro ao mais escuro, o verde do recebido e o vermelho da protocolada alem
// do prazo, que leva tambem a marca "!" dentro da celula (#721; resumoMatriz.css)
const ETAPAS_MATRIZ: { chave: EtapaMatriz; rotulo: string }[] = [
  { chave: "em_analise", rotulo: "Em análise" },
  { chave: "boletim", rotulo: "Boletim" },
  { chave: "nota", rotulo: "Nota" },
  { chave: "protocolado", rotulo: "Protocolado" },
  { chave: "recebida", rotulo: "Recebido" },
  { chave: "atrasado", rotulo: "Atrasado" },
];
const ROTULO_MATRIZ = Object.fromEntries(ETAPAS_MATRIZ.map(e => [e.chave, e.rotulo])) as Record<EtapaMatriz, string>;
// a marca da legenda e' a peca MarcaEtapa (#805); a matriz chama de "recebida" a etapa que a peca chama de "recebido"
const marcaDaMatriz = (e: EtapaMatriz): Etapa => (e === "recebida" ? "recebido" : e);

/** Uma linha por obra ativa, agrupada por contratante, e uma celula por competencia com a cor da etapa da medicao. A
 *  celula pintada e' o link para a medicao, com o nome (obra, competencia, etapa) no `aria-label` e na dica; a tabela
 *  equivalente fica para o leitor de tela. */
export default function ResumoMatriz({ matriz }: { matriz: RespostaMatriz }) {
  const { competencias, grupos } = matriz;
  return (
    <section aria-labelledby="rdm-matriz" className="cartao rdm-matriz">
      <div className="rdm-matriz__cab">
        <h3 id="rdm-matriz">Medições por obra e competência</h3>
        <ul className="rdm-matriz__legenda" aria-label="Legenda das etapas">
          {ETAPAS_MATRIZ.map(e => <li key={e.chave}><MarcaEtapa etapa={marcaDaMatriz(e.chave)}>{e.rotulo}</MarcaEtapa></li>)}
        </ul>
      </div>
      {grupos.length === 0 ? <p className="rdm-vazio">Nenhuma obra ativa.</p> : <>
        <div className="rdm-matriz__grade">
          <div className="rdm-matriz__linha rdm-matriz__linha--meses" aria-hidden="true">
            {competencias.map((c, i) => {
              const [mes, ano] = fmtMesCurto(c).split("/");
              return (
                <span key={c} className="rdm-matriz__mes">
                  <span>{mes}</span>{(i === 0 || c.endsWith("-01")) && <span className="rdm-matriz__ano">{ano}</span>}
                </span>);
            })}
          </div>
          {grupos.map(g => (
            <Fragment key={g.contratante}>
              <h4 className="rdm-matriz__grupo">{g.contratante}</h4>
              {g.obras.map(o => (
                <div key={o.contrato_id} className="rdm-matriz__linha rdm-matriz__linha--obra">
                  <span className="rdm-matriz__obra">{o.obra}</span>
                  {competencias.map((c, i) => {
                    const cel = o.celulas[i];
                    if (!cel) return <span key={c} className="rdm-matriz__celula" aria-hidden="true" />;
                    const nome = `${o.obra}, ${fmtCompetencia(c)}: ${ROTULO_MATRIZ[cel.etapa]}`;
                    return <Link key={c} para={{ tela: "medicao", obra: o.contrato_id, id: cel.medicao_id }}
                      className={`rdm-matriz__celula rdm-matriz__celula--${cel.etapa}`} aria-label={nome} title={nome}>{null}</Link>;
                  })}
                </div>))}
            </Fragment>))}
        </div>
        <div className="sr-only"><table>
          <caption>Etapa da medição de cada obra por competência</caption>
          <thead><tr><th scope="col">Obra</th><th scope="col">Contratante</th>
            {competencias.map(c => <th key={c} scope="col">{fmtCompetencia(c)}</th>)}</tr></thead>
          <tbody>
            {grupos.flatMap(g => g.obras.map(o => (
              <tr key={o.contrato_id}>
                <th scope="row">{o.obra}</th><td>{g.contratante}</td>
                {competencias.map((c, i) => { const cel = o.celulas[i]; return <td key={c}>{cel ? ROTULO_MATRIZ[cel.etapa] : "—"}</td>; })}
              </tr>)))}
          </tbody>
        </table></div>
      </>}
    </section>
  );
}
