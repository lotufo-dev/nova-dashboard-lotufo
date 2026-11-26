import { fmtCentesimos, fmtMilesimos, quandoLeu, useLicitacoes, type GrupoDeResultado, type QuadroDeResultados, type RespostaResultados } from "./licitacoes";
import { LeituraDoRadarLinha, SemLeitura, Traco } from "./LicitacoesPecas";
import Rolagem from "./Rolagem";
import Selo from "./Selo";
import { fmtDataPura } from "./tempo";

// RESULTADOS (fatia 4 da #906, docs/adr/0018): "/licitacoes/resultados". Responde "como fomos nas que participamos?":
// o funil, participadas e vencidas por tipo de obra e por modalidade (com a taxa), as perdas com o motivo e o desconto
// da empresa ao lado do desconto do vencedor.
//
// O quadro e' do radar: ele le os dossies, que a producao nao tem, e manda o quadro pronto no fechamento da rodada; a
// dashboard guarda o ultimo e mostra. A taxa (vencidas sobre participadas) vem do servidor em milesimos, e os descontos
// em centesimos de ponto, como o radar mandou: a tela so' formata. Valores que se comparam entre linhas: tabelas.

function Grupos({ titulo, id, grupos, coluna }: { titulo: string; id: string; grupos: GrupoDeResultado[]; coluna: string }) {
  return (
    <section className="cartao lic-bloco" aria-labelledby={id}>
      <header className="cartao__cabeca"><h2 className="cartao__titulo" id={id}>{titulo}</h2></header>
      {grupos.length === 0 ? <div className="vazio vazio--curto"><p>—</p></div> : (
        <Rolagem rotulo={titulo}>
          <table className="tabela lic-tabela lic-tabela--grupos">
            <caption className="sr-only">{titulo}: participadas, vencidas e a taxa</caption>
            <thead>
              <tr>
                <th scope="col">{coluna}</th><th scope="col" className="col-num">Participadas</th>
                <th scope="col" className="col-num">Vencidas</th><th scope="col" className="col-num">Taxa</th>
              </tr>
            </thead>
            <tbody>
              {grupos.map(g => (
                <tr key={g.grupo}>
                  <th scope="row">{g.grupo}</th>
                  <td className="col-num" data-rotulo="Participadas">{g.participadas.toLocaleString("pt-BR")}</td>
                  <td className="col-num" data-rotulo="Vencidas">{g.vencidas.toLocaleString("pt-BR")}</td>
                  <td className="col-num" data-rotulo="Taxa">{g.taxa === null ? <Traco /> : fmtMilesimos(g.taxa)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Rolagem>
      )}
    </section>
  );
}

function Quadro({ q }: { q: QuadroDeResultados }) {
  return (
    <>
      {q.funil.length > 0 && (
        <dl className="lic-numeros lic-funil" aria-label="Funil das licitações">
          {q.funil.map(p => (
            <div key={p.rotulo} className="lic-numero">
              <dt>{p.rotulo}</dt><dd className="lic-numero__valor">{p.n.toLocaleString("pt-BR")}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="lic-lado-a-lado">
        <Grupos titulo="Por tipo de obra" id="lic-por-tipo" grupos={q.por_tipo} coluna="Tipo de obra" />
        <Grupos titulo="Por modalidade" id="lic-por-modalidade" grupos={q.por_modalidade} coluna="Modalidade" />
      </div>
      <section className="cartao lic-bloco" aria-labelledby="lic-perdas">
        <header className="cartao__cabeca"><h2 className="cartao__titulo" id="lic-perdas">Perdas</h2></header>
        {q.perdas.length === 0 ? <div className="vazio vazio--curto"><p>—</p></div> : (
          <Rolagem rotulo="Perdas">
            <table className="tabela lic-tabela">
              <caption className="sr-only">As licitações perdidas, com o motivo</caption>
              <thead><tr><th scope="col">Licitação</th><th scope="col">Motivo</th><th scope="col">Data</th></tr></thead>
              <tbody>
                {q.perdas.map((p, i) => (
                  <tr key={`${i}-${p.licitacao}`}>
                    <th scope="row" className="lic-c-licitacao"><span className="lic-nome">{p.licitacao}</span></th>
                    <td data-rotulo="Motivo">{p.motivo || <Traco />}</td>
                    <td className="num" data-rotulo="Data">{p.data ? fmtDataPura(p.data) : <Traco />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Rolagem>
        )}
      </section>
      <section className="cartao lic-bloco" aria-labelledby="lic-descontos">
        <header className="cartao__cabeca"><h2 className="cartao__titulo" id="lic-descontos">Descontos</h2></header>
        {q.descontos.length === 0 ? <div className="vazio vazio--curto"><p>—</p></div> : (
          <Rolagem rotulo="Descontos">
            <table className="tabela lic-tabela">
              <caption className="sr-only">O desconto da empresa ao lado do desconto do vencedor</caption>
              <thead>
                <tr>
                  <th scope="col">Licitação</th><th scope="col" className="col-num">Desconto da empresa</th>
                  <th scope="col" className="col-num">Desconto do vencedor</th>
                </tr>
              </thead>
              <tbody>
                {q.descontos.map((d, i) => (
                  <tr key={`${i}-${d.licitacao}`}>
                    <th scope="row" className="lic-c-licitacao">
                      <span className="lic-nome">{d.licitacao}</span>{d.vencemos && <Selo>Vencida</Selo>}
                    </th>
                    <td className="col-num" data-rotulo="Desconto da empresa">{fmtCentesimos(d.empresa)}</td>
                    <td className="col-num" data-rotulo="Desconto do vencedor">{d.vencedor === null ? <Traco /> : fmtCentesimos(d.vencedor)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Rolagem>
        )}
      </section>
    </>
  );
}

export default function LicitacoesResultados() {
  const { dados, erro, tentar } = useLicitacoes<RespostaResultados>("/api/licitacoes/resultados");
  if (!dados) return <SemLeitura erro={erro} tentar={() => void tentar()} />;
  return (
    <div className="pagina lic">
      <LeituraDoRadarLinha leitura={dados.leitura} />
      {dados.resultados && dados.lido_em
        ? <>
            {/* so' quando o quadro veio de uma leitura anterior a' ultima: a rodada que nao manda quadro deixa o ultimo */}
            {dados.lido_em !== dados.leitura.lido_em && <p className="lic-lido">Quadro da leitura de <span className="num">{quandoLeu(dados.lido_em)}</span></p>}
            <Quadro q={dados.resultados} />
          </>
        : <div className="cartao lic-bloco"><div className="vazio vazio--curto"><p>O radar ainda não mandou resultados.</p></div></div>}
    </div>
  );
}
