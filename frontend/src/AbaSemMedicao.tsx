import { IconeDocumento, IconeMais, IconeSeta } from "./icones";
import { destino } from "./IniciarMedicao";
import { Link } from "./Link";
import { porContratante, textoMedicao, textoParada, type ObraResumo } from "./resumoMedicoes";
import "./abaSemMedicao.css";

// Aba "Sem medição aberta" (#154, prototipo aprovado em 14/10/2026): as obras ativas sem medicao em andamento,
// por contratante (o grupo com mais obras primeiro; os dois primeiros abertos, os outros fechados, abrem ao
// clicar). Por obra: ultima medicao, ha' quanto tempo (do fim da competencia dela, sem cor), a prevista do
// cronograma e "Iniciar a Nª medicao". Tudo vem de GET /api/medicoes/resumo; a tela so' desenha.

function Linha({ o }: { o: ObraResumo }) {
  return (
    <tr>
      <td><Link className="sem-medicao__obra" para={{ tela: "obra", id: o.contrato_id, aba: "medicoes" }}>{o.obra}</Link></td>
      <td>{o.contratante}{o.orgao_sub && <span className="sem-medicao__setor">{o.orgao_sub}</span>}</td>
      <td data-rotulo="Última medição:">{o.ultima ? textoMedicao(o.ultima) : <span className="sem-medicao__traco">—</span>}</td>
      <td data-rotulo="Há quanto tempo:" className={o.ha_dias === null ? "sem-medicao__so-tela" : undefined}>
        {o.ha_dias === null ? <span className="sem-medicao__traco">—</span> : textoParada(o.ha_dias)}</td>
      <td className={o.prevista ? undefined : "sem-medicao__so-tela"}>
        {o.prevista ? <span className="sem-medicao__prevista">Prevista: {textoMedicao(o.prevista)}</span>
          : <span className="sem-medicao__traco">—</span>}</td>
      <td className="sem-medicao__acao">
        <Link className="sem-medicao__iniciar-link" para={destino(o)}>Iniciar a {o.proxima}ª medição{o.proxima_tipo === "projeto" ? " de Projeto" : ""}</Link></td>
    </tr>
  );
}

export default function AbaSemMedicao({ obras, podeIniciar, aoIniciar }:
    { obras: ObraResumo[]; podeIniciar: boolean; aoIniciar: () => void }) {
  const grupos = porContratante(obras);
  return (
    <>
      {podeIniciar && (
        <div className="medicoes__acoes">
          <button type="button" className="btn btn--primario medicoes__iniciar" onClick={aoIniciar}>
            <IconeMais className="icone" />Iniciar processo de medição
          </button>
        </div>
      )}
      <section className="medicoes__quadro sem-medicao" aria-labelledby="sem-medicao-titulo">
        <div className="medicoes__quadro-cabeca">
          <h2 id="sem-medicao-titulo">Sem medição aberta</h2>
        </div>
        {grupos.length === 0 ? (
          <div className="vazio">
            <IconeDocumento className="icone" />
            <p className="vazio__titulo">Todas as obras ativas têm medição aberta.</p>
          </div>
        ) : grupos.map((g, i) => (
          <details key={g.contratante} className="sem-medicao__grupo" open={i < 2 || undefined}>
            <summary>
              <IconeSeta className="icone icone--p sem-medicao__seta" />
              <span className="sem-medicao__grupo-nome">{g.contratante}</span>
            </summary>
            <table className="sem-medicao__tabela">
              <caption className="sr-only">{`${g.contratante}: obras sem medição aberta`}</caption>
              <colgroup><col className="c-obra" /><col className="c-contratante" /><col className="c-ultima" />
                <col className="c-ha" /><col className="c-prevista" /><col className="c-acao" /></colgroup>
              <thead>
                <tr>
                  <th scope="col">Obra</th><th scope="col">Contratante</th><th scope="col">Última medição</th>
                  <th scope="col">Há quanto tempo</th><th scope="col">Prevista</th>
                  <th scope="col"><span className="sr-only">Ação</span></th>
                </tr>
              </thead>
              <tbody>{g.obras.map(o => <Linha key={o.contrato_id} o={o} />)}</tbody>
            </table>
          </details>
        ))}
      </section>
    </>
  );
}
