import { useMemo } from "react";
import Andamento from "./Andamento";
import { brl } from "./formato";
import { Link } from "./Link";
import { andamentoDaObra, contratanteDaObra, criticosPorObra, nomeDaObra, porAndamento, resumoDe, type ObraLista } from "./listaObras";
import { type Painel } from "./ObrasCarteira";
import { NumerosDeObras } from "./ObrasPecas";
import Rolagem from "./Rolagem";
import { type Ir } from "./rota";
import { fmtDataPura } from "./tempo";

// "Andamento" (#805): as obras com prazo a cumprir, da que mede a menor parte do necessario para a que mede a maior.
// Com o dado real quase toda obra fica abaixo de 100%, entao o percentual e' o que separa uma da outra: ele tem coluna
// propria, em numero, e a peca `Andamento` desenha a barra com a palavra. O ritmo e o necessario por mes vao exatos,
// em colunas, na COTA da Lotufo, do servidor (`andamento` de `/api/contratos`, a conta da pagina da obra). A obra sem
// necessario (parada, com a execucao vencida, em encerramento ou sem saldo) nao tem prazo a cumprir e fica fora; a
// sem ritmo (sem medicao de execucao nos ultimos seis meses) vai ao fim, sem leitura.

export default function ObrasAndamento({ obras, painel, ir }: { obras: ObraLista[]; painel: Painel | null | undefined; ir: Ir }) {
  const criticos = useMemo(() => criticosPorObra(painel?.avisos ?? []), [painel]);
  const carteira = useMemo(() => resumoDe(obras, criticos), [obras, criticos]);
  const linhas = useMemo(() => porAndamento(obras), [obras]);
  return (
    <>
      {obras.length > 0 && <NumerosDeObras r={carteira} rotulo="Números da carteira" />}
      <section className="cartao obras-painel" aria-label="Andamento das obras">
        {linhas.length === 0 ? (
          <div className="vazio vazio--curto"><p className="vazio__titulo">Nenhuma obra com prazo de execução a cumprir.</p></div>
        ) : (
          <Rolagem rotulo="Andamento das obras" alta>
            <table className="tabela obras-posicao obras-andamento">
              <caption className="sr-only">Obras pelo andamento: o ritmo contra o necessário por mês, do menor para o maior</caption>
              <thead>
                <tr>
                  <th scope="col">Obra</th>
                  <th scope="col" className="col-num">Do necessário</th>
                  <th scope="col">Andamento</th>
                  <th scope="col" className="col-num">Ritmo mensal</th>
                  <th scope="col" className="col-num">Necessário por mês</th>
                  <th scope="col">Fim da execução</th>
                </tr>
              </thead>
              <tbody>
                {linhas.map(o => {
                  const a = andamentoDaObra(o);
                  const ritmo = o.andamento?.ritmo_centavos ?? null, necessario = o.andamento?.necessario_centavos ?? null;
                  return (
                    <tr key={o.id} className="linha linha--obra" onClick={e => { if (!(e.target as HTMLElement).closest("a")) ir({ tela: "obra", id: o.id, aba: "ficha" }); }}>
                      <td data-rotulo="Obra">
                        <Link className="nome-link obras-posicao__nome" para={{ tela: "obra", id: o.id, aba: "ficha" }} ir={ir}>{nomeDaObra(o)}</Link>
                        <div className="obras-posicao__sub">{contratanteDaObra(o)}</div>
                      </td>
                      <td data-rotulo="Do necessário" className="col-num num obras-andamento__pct">{a ? `${a.pct.toLocaleString("pt-BR")}%` : "—"}</td>
                      <td data-rotulo="Andamento" className="obras-posicao__andamento">
                        {a ? <Andamento ritmo={ritmo} necessario={necessario} detalhe="palavra" /> : "—"}
                      </td>
                      <td data-rotulo="Ritmo mensal" className="col-num dinheiro num">{brl(ritmo)}</td>
                      <td data-rotulo="Necessário por mês" className="col-num dinheiro num">{brl(necessario)}</td>
                      <td data-rotulo="Fim da execução" className="num">{o.execucao_fim_vigente ? fmtDataPura(o.execucao_fim_vigente.slice(0, 10)) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Rolagem>
        )}
      </section>
    </>
  );
}
