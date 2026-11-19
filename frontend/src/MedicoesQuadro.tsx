import Contador from "./Contador";
import { brl, contar } from "./formato";
import type { GrupoDoQuadro, Limites, LinhaDoQuadro, PassoDoQuadro } from "./filaMedicoes";
import { Link } from "./Link";
import MarcaEtapa from "./MarcaEtapa";
import { Aprovado } from "./MedicoesFila";
import { diaMes, PASSOS } from "./Passos";
import type { SigaNoQuadro } from "./resumoMedicoes";
import Selo, { Glifo } from "./Selo";
import { situacaoDoAtraso, textoSemMovimentacao } from "./siga";
import { textoDoTempo } from "./parada";

// O QUADRO DO MES (#643, aprovado pelo dono em 10/11/2026), a segunda vista de Medicoes desde a #805: uma linha por
// obra e uma coluna por passo do fluxo, na competencia. Tres mudancas da #805: as obras vem agrupadas por contratante,
// sob o cabecalho de grupo forte com o pedido e o aprovado do grupo; o passo da vez diz ha' quantos dias uteis a
// medicao esta' nele, no selo da situacao do tempo parado; e o aprovado leva a diferenca contra o pedido. A obra sem
// medicao na competencia saiu da matriz (fica no bloco "Sem medição"). Tudo vem de GET /api/medicoes/fila.

const traco = <span className="medicoes__traco">—</span>;

/** #664: onde está o processo do SIGA da medição que está neste passo: sigla do setor e, #840, há quanto tempo ele está
 *  sem movimentação, com o texto da coluna "Dias sem movimentação" da tela SIGA ("hoje" quando andou hoje) e a
 *  situação do atraso pela leitura do servidor. Sem movimentação nenhuma, só a sigla. */
function PosicaoSiga({ siga }: { siga: SigaNoQuadro | null }) {
  if (!siga) return null;
  const situacao = situacaoDoAtraso(siga);
  const tempo = siga.hoje > 0 ? "hoje" : textoSemMovimentacao(siga);
  return (
    <span className="quadro__siga">
      <span className="sr-only">No SIGA: </span>
      <span className="quadro__siga-setor">{siga.setor}</span>
      {tempo !== "—" && <> <span className={`quadro__siga-tempo num${situacao ? ` quadro__siga-tempo--${situacao}` : ""}`}>{situacao && <Glifo situacao={situacao} />}{tempo !== "hoje" && siga.situacao_tempo !== "sobrestado" && <span className="sr-only">sem movimentação há </span>}{tempo}</span></>}
    </span>
  );
}

function CelulaPasso({ n, passo, linha }: { n: number; passo: PassoDoQuadro | undefined; linha: LinhaDoQuadro }) {
  const nome = PASSOS[n - 1];
  // o passo que a obra não tem fica vazio
  if (!passo) return <td className="quadro__passo quadro__passo--sem" data-rotulo={nome} />;
  if (passo.situacao === "feito") {
    const data = diaMes(passo.data);
    return (
      <td className="quadro__passo quadro__passo--feito" data-rotulo={nome}>
        <span className="quadro__feito">
          <Glifo situacao="feito" />
          {data ? <><span className="sr-only">Feito em </span><span className="num">{data}</span></> : "Feito"}
        </span>
      </td>
    );
  }
  if (passo.situacao === "atual" && passo.medicao_id !== null) {
    const medicao = linha.medicoes.find(m => m.id === passo.medicao_id);
    // o selo "Atual" leva a situacao do tempo parado, e os dias vao escritos embaixo; sem a data do evento, em andamento
    const tempo = passo.parada && passo.parada.dias_uteis !== null ? textoDoTempo(passo.parada) : null;
    return (
      <td className="quadro__passo" data-rotulo={nome} aria-current="step">
        <span className="quadro__da-vez">
          <Link className="link-selo quadro__atual" para={{ tela: "medicao", obra: linha.contrato_id, id: passo.medicao_id }}
            secao={`passo-${n}`}
            aria-label={`Abrir ${medicao?.titulo ?? "a medição"} de ${linha.obra}: ${nome}${tempo ? `, ${tempo === "hoje" ? "desde hoje" : `há ${tempo}`}` : ""}`}>
            <Selo situacao={passo.parada?.situacao ?? "andamento"}>Atual</Selo>
          </Link>
          {tempo && <span className="quadro__dias num">{tempo}</span>}
        </span>
        <PosicaoSiga siga={passo.siga} />
      </td>
    );
  }
  return <td className="quadro__passo quadro__passo--futuro" data-rotulo={nome}>A fazer<PosicaoSiga siga={passo.siga} /></td>;
}

function Linha({ linha, limite }: { linha: LinhaDoQuadro; limite: number }) {
  return (
    <tr>
      <th scope="row" className="quadro__obra">
        <Link className="medicoes__obra" para={{ tela: "obra", id: linha.contrato_id, aba: "medicoes" }}>{linha.obra}</Link>
        {linha.medicoes.map(m => (
          <Link key={m.id} className="quadro__medicao" para={{ tela: "medicao", obra: linha.contrato_id, id: m.id }}>{m.titulo}</Link>
        ))}
      </th>
      {PASSOS.map((_, i) => <CelulaPasso key={i} n={i + 1} passo={linha.passos.find(p => p.numero === i + 1)} linha={linha} />)}
      <td className="col-num dinheiro" data-rotulo="Pedido">{linha.pedido_centavos === null ? traco : brl(linha.pedido_centavos)}</td>
      <td className="col-num dinheiro" data-rotulo="Aprovado"><Aprovado v={linha} limite={limite} comAcima /></td>
    </tr>
  );
}

export default function MedicoesQuadro({ grupos, limites, carregando }: { grupos: GrupoDoQuadro[]; limites: Limites; carregando: boolean }) {
  const obras = grupos.reduce((n, g) => n + g.linhas.length, 0);
  return (
    <section className="cartao medicoes__painel" aria-labelledby="quadro-titulo">
      <div className="medicoes__painel-cab">
        <h2 id="quadro-titulo">Quadro do mês</h2>
        {obras > 0 && <Contador rotulo={contar(obras, "obra", "obras")}>{obras.toLocaleString("pt-BR")}</Contador>}
      </div>
      {obras === 0 ? <p className="medicoes__vazio">Nenhuma medição na competência.</p> : (
        <table className="tabela quadro__tabela" aria-labelledby="quadro-titulo" aria-busy={carregando || undefined}>
          <colgroup>
            <col className="quadro__c-obra" />{PASSOS.map(p => <col key={p} className="quadro__c-passo" />)}
            <col className="quadro__c-valor" /><col className="quadro__c-aprovado" />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">Obra</th>{PASSOS.map(p => <th key={p} scope="col" className="quadro__th-passo">{p}</th>)}
              <th scope="col" className="col-num">Pedido</th>
              <th scope="col" className="col-num"><MarcaEtapa etapa="boletim">Aprovado</MarcaEtapa></th>
            </tr>
          </thead>
          {grupos.map(g => (
            <tbody key={g.contratante}>
              <tr className="quadro__grupo">
                <th scope="rowgroup" colSpan={PASSOS.length + 1}>
                  {g.contratante}<span className="quadro__grupo-n num">{contar(g.linhas.length, "obra", "obras")}</span>
                </th>
                <td className="col-num dinheiro" data-rotulo="Pedido">{g.pedido_centavos === null ? "—" : brl(g.pedido_centavos)}</td>
                <td className="col-num dinheiro" data-rotulo="Aprovado">
                  {g.aprovado_centavos === null ? "—" : <Aprovado v={g} limite={limites.diferenca_critica_por_mil} />}
                </td>
              </tr>
              {g.linhas.map(l => <Linha key={l.contrato_id} linha={l} limite={limites.diferenca_critica_por_mil} />)}
            </tbody>
          ))}
        </table>
      )}
    </section>
  );
}
