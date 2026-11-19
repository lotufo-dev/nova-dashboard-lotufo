import BarraDePassos from "./BarraDePassos";
import Contador from "./Contador";
import Diferenca from "./Diferenca";
import { brl, contar } from "./formato";
import { contratanteDe, ROTULO_COM_QUEM, ROTULO_DA_ACAO, type ComparadosDaLinha, type Comparados, type ContagemFila,
         type FilaMedicoes, type GrupoFila, type Limites, type LinhaFila, type SemMedicao } from "./filaMedicoes";
import { Link } from "./Link";
import MarcaEtapa from "./MarcaEtapa";
import { diaMes } from "./Passos";
import Selo, { Glifo } from "./Selo";
import TempoParado from "./TempoParado";
import { fmtCompetencia, fmtMesExtenso } from "./tempo";

// A FILA DE TRABALHO de Medicoes (#805, etapa 3a; decisao do dono de 18/11/2026): a entrada da tela de quem opera. A
// pergunta e' "o que eu preciso fazer agora?": um painel por quem tem de agir (a Lotufo, o faturamento, o orgao), cada
// um da medicao mais parada para a menos, com a barra de passos da obra, o tempo parado, o pedido, o aprovado com a
// diferenca e o botao do proximo passo, que so' LEVA a' pagina da medicao. Embaixo, as concluidas no mes e as obras
// sem medicao. Tudo vem de GET /api/medicoes/fila; a tela so' desenha.

const traco = <span className="medicoes__traco">—</span>;

/** O aprovado com a diferenca contra o pedido embaixo. `acima` so' na linha da medicao (ou da obra); onde soma, nao. */
export function Aprovado({ v, limite, comAcima = false }: { v: Comparados | ComparadosDaLinha; limite: number; comAcima?: boolean }) {
  if (v.aprovado_centavos === null) return traco;
  return (
    <span className="fila__cel">
      <span>{brl(v.aprovado_centavos)}</span>
      <Diferenca abaixo={v.abaixo_do_pedido_centavos} acima={comAcima && "acima_do_pedido_centavos" in v ? v.acima_do_pedido_centavos : undefined}
        base={v.pedido_do_aprovado_centavos} nomeBase="pedido" limitePorMil={limite} />
    </span>
  );
}

function LinhaDaFila({ l, limite, opera, comCompetencia }: { l: LinhaFila; limite: number; opera: boolean; comCompetencia: boolean }) {
  const medicao = { tela: "medicao" as const, obra: l.contrato_id, id: l.medicao_id };
  const quem = contratanteDe(l);
  return (
    <tr>
      <th scope="row" className="fila__obra">
        <Link className="medicoes__obra" para={{ tela: "obra", id: l.contrato_id, aba: "medicoes" }}>{l.obra}</Link>
        <span className="fila__medicao">
          <Link para={medicao}>{l.titulo}</Link>
          {comCompetencia && <> · <span className="num">{fmtCompetencia(l.competencia)}</span></>}
          {quem && <> · {quem}</>}
        </span>
      </th>
      <td data-rotulo="Passo"><BarraDePassos passos={l.passos} /></td>
      <td data-rotulo="Parada há"><TempoParado parada={l.parada} /></td>
      <td className="col-num dinheiro" data-rotulo="Pedido">{l.pedido_centavos === null ? traco : brl(l.pedido_centavos)}</td>
      <td className="col-num dinheiro" data-rotulo="Aprovado"><Aprovado v={l} limite={limite} comAcima /></td>
      <td className="quadro__acao">
        {/* o botao so' leva a' pagina da medicao, no passo da vez; quem so' consulta ve "Abrir" em todas */}
        <Link className={`btn btn--pequeno${opera && l.acao ? " btn--primario" : ""}`} para={medicao} secao={`passo-${l.passo.numero}`}
          aria-label={`${opera && l.acao ? ROTULO_DA_ACAO[l.acao] : "Abrir"}: ${l.titulo} de ${l.obra}`}>
          {opera && l.acao ? ROTULO_DA_ACAO[l.acao] : "Abrir"}
        </Link>
      </td>
    </tr>
  );
}

/** Um painel por quem tem de agir, com o cabecalho de grupo forte e as linhas na ordem do servidor. `comCompetencia`:
 *  a vista "Meses anteriores", em que cada linha e' de um mes. */
export function GruposDaFila({ grupos, limites, opera, comCompetencia = false }: {
  grupos: GrupoFila[]; limites: Limites; opera: boolean; comCompetencia?: boolean;
}) {
  return (
    <>
      {grupos.map(g => {
        const id = `fila-${g.com_quem}`;
        return (
          <section key={g.com_quem} className="fila-grupo" aria-labelledby={id}>
            <div className="fila-grupo__cabeca">
              <h2 id={id} className="fila-grupo__nome">{ROTULO_COM_QUEM[g.com_quem]}</h2>
              <span className="fila-grupo__n num">{contar(g.linhas.length, "medição", "medições")}</span>
            </div>
            <div className="tabela-wrap">
              <table className="tabela fila__tabela" aria-labelledby={id}>
                <colgroup>
                  <col /><col className="fila__c-passo" /><col className="fila__c-parada" /><col className="fila__c-valor" />
                  <col className="fila__c-aprovado" /><col className="fila__c-acao" />
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col">Obra</th><th scope="col">Passo</th><th scope="col">Parada há</th>
                    <th scope="col" className="col-num">Pedido</th>
                    <th scope="col" className="col-num"><MarcaEtapa etapa="boletim">Aprovado</MarcaEtapa></th>
                    <th scope="col"><span className="sr-only">Próximo passo</span></th>
                  </tr>
                </thead>
                <tbody>
                  {g.linhas.map(l => <LinhaDaFila key={l.medicao_id} l={l} limite={limites.diferenca_critica_por_mil} opera={opera} comCompetencia={comCompetencia} />)}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
    </>
  );
}

/** O que chama atencao no grupo, no selo da situacao: no orgao, as que passaram do prazo dele; nos demais (e no orgao
 *  sem atraso de pagamento), as paradas alem dos limites do tempo parado, que o servidor manda. */
function DestaqueDoGrupo({ c, limites, orgao }: { c: ContagemFila; limites: Limites; orgao: boolean }) {
  if (orgao && c.alem_do_prazo > 0) return <Selo situacao="critico">{c.alem_do_prazo} além do prazo<span className="sr-only"> do órgão</span></Selo>;
  // a faixa e' estreita: "10+ dias úteis" para quem ve, por extenso para quem ouve
  const parado = (quantas: number, dias: number) => (
    <><span aria-hidden="true">{quantas} há {dias}+ dias úteis</span><span className="sr-only">{quantas} há {dias} dias úteis ou mais</span></>
  );
  if (c.criticas > 0) return <Selo situacao="critico">{parado(c.criticas, limites.dias_critico)}</Selo>;
  if (c.breves > 0) return <Selo situacao="breve">{parado(c.breves, limites.dias_atencao)}</Selo>;
  return null;
}

/** A faixa de numeros: quantas medicoes estao com cada um, as concluidas, as obras sem medicao e o aprovado do mes com
 *  a diferenca contra o pedido (so' o corte, como no Fechamento; aqui no valor cheio). */
function Numeros({ d }: { d: FilaMedicoes }) {
  const n = d.numeros;
  const mes = fmtMesExtenso(d.mes);
  return (
    <dl className="fila-numeros" aria-label={`Números de ${mes}`}>
      {(["lotufo", "faturamento", "orgao"] as const).map(q => (
        <div key={q} className="fila-numero">
          <dt>{ROTULO_COM_QUEM[q]}</dt><dd>{n.com[q].quantidade.toLocaleString("pt-BR")}</dd>
          <dd className="fila-numero__apoio"><DestaqueDoGrupo c={n.com[q]} limites={d.limites} orgao={q === "orgao"} /></dd>
        </div>
      ))}
      <div className="fila-numero"><dt>Concluídas no mês</dt><dd>{n.concluidas.toLocaleString("pt-BR")}</dd></div>
      <div className="fila-numero"><dt>Sem medição</dt><dd>{n.sem_medicao.toLocaleString("pt-BR")}</dd></div>
      <div className="fila-numero fila-numero--valor">
        <dt><MarcaEtapa etapa="boletim">Aprovado em {mes}</MarcaEtapa></dt>
        <dd>{n.aprovado_centavos === null ? "—" : brl(n.aprovado_centavos)}</dd>
        <dd className="fila-numero__apoio">
          <Diferenca abaixo={n.abaixo_do_pedido_centavos} base={n.pedido_do_aprovado_centavos} nomeBase="pedido" limitePorMil={d.limites.diferenca_critica_por_mil} />
        </dd>
      </div>
    </dl>
  );
}

/** As obras ativas sem medicao na competencia, com o "Iniciar" para quem pode iniciar. */
export function SemMedicaoNoMes({ obras, mes, podeIniciar, aoIniciar }: {
  obras: SemMedicao[]; mes: string; podeIniciar: boolean; aoIniciar: (contratoId: number) => void;
}) {
  return (
    <section className="cartao medicoes__painel fila-bloco" aria-labelledby="sem-medicao-titulo">
      <div className="medicoes__painel-cab">
        <h2 id="sem-medicao-titulo">Sem medição em {fmtMesExtenso(mes)}</h2>
        {obras.length > 0 && <Contador rotulo={contar(obras.length, "obra", "obras")}>{obras.length.toLocaleString("pt-BR")}</Contador>}
      </div>
      {obras.length === 0 ? <p className="medicoes__vazio">—</p> : (
        <ul className="fila-lista">
          {obras.map(o => (
            <li key={o.contrato_id} className="fila-lista__item">
              <Link className="medicoes__obra" para={{ tela: "obra", id: o.contrato_id, aba: "medicoes" }}>{o.obra}</Link>
              {podeIniciar && <button type="button" className="btn btn--pequeno" aria-label={`Iniciar a medição de ${o.obra}`} onClick={() => aoIniciar(o.contrato_id)}>Iniciar</button>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function Concluidas({ d }: { d: Pick<FilaMedicoes, "concluidas"> }) {
  return (
    <section className="cartao medicoes__painel fila-bloco" aria-labelledby="concluidas-titulo">
      <div className="medicoes__painel-cab">
        <h2 id="concluidas-titulo">Concluídas no mês</h2>
        {d.concluidas.length > 0 && <Contador rotulo={contar(d.concluidas.length, "medição", "medições")}>{d.concluidas.length.toLocaleString("pt-BR")}</Contador>}
      </div>
      {d.concluidas.length === 0 ? <p className="medicoes__vazio">—</p> : (
        <ul className="fila-lista">
          {d.concluidas.map(c => {
            const dia = diaMes(c.recebida_em);
            return (
              <li key={c.medicao_id} className="fila-lista__item">
                <span className="fila-lista__feita">
                  <Glifo situacao="feito" />
                  <Link className="medicoes__obra" para={{ tela: "medicao", obra: c.contrato_id, id: c.medicao_id }}>{c.obra} · {c.titulo}</Link>
                </span>
                <span className="fila-lista__apoio">{dia ? <>recebida em <span className="num">{dia}</span></> : "recebida"}</span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export default function MedicoesFila({ d, opera, podeIniciar, aoIniciar }: {
  d: FilaMedicoes; opera: boolean; podeIniciar: boolean; aoIniciar: (contratoId: number) => void;
}) {
  return (
    <>
      <Numeros d={d} />
      {d.grupos.length === 0
        ? <p className="medicoes__vazio medicoes__vazio--pagina">Nenhuma medição em andamento em {fmtMesExtenso(d.mes)}.</p>
        : <GruposDaFila grupos={d.grupos} limites={d.limites} opera={opera} />}
      <div className="fila-blocos">
        <Concluidas d={d} />
        <SemMedicaoNoMes obras={d.sem_medicao} mes={d.mes} podeIniciar={podeIniciar} aoIniciar={aoIniciar} />
      </div>
    </>
  );
}
