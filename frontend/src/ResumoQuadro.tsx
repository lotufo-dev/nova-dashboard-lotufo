import Diferenca from "./Diferenca";
import { brl, contar, fmtDias } from "./formato";
import { Link } from "./Link";
import MarcaEtapa from "./MarcaEtapa";
import { ETAPAS, linhasDaEtapa, temDiferenca, type ContagemDaEtapa, type Etapa, type Linha } from "./resumoEtapas";
import { type Ir } from "./rota";
import Selo from "./Selo";
import { fmtDataCurta } from "./tempo";
import TempoParado from "./TempoParado";

// O quadro por etapa do Resumo das medicoes (#805, decisao do dono de 18/11/2026): uma coluna por etapa do ciclo (em
// analise, boletim, nota, protocolado, recebido) e um cartao por medicao dentro da coluna em que ela esta'. Responde
// "onde esta' o dinheiro do mes?" sem ler linha por linha. A etapa de cada medicao, a quantidade e o valor de cada
// coluna, o tempo parado e a diferenca entre o aprovado e o pedido vem do servidor; aqui so' se desenha, com o
// cartao de maior valor primeiro. O tempo parado e' o da fila de trabalho da tela Medicoes (`TempoParado`): a mesma
// leitura nas duas telas.

/** O cartao de uma medicao: a obra, o contratante e a medicao (com o link da pagina dela), o medido na cota, ha'
 *  quanto tempo esta' parada e desde quando (no protocolado, com o prazo do orgao; na recebida, a data e os dias da
 *  nota ao recebimento) e, quando o aprovado difere do pedido, a diferenca. */
export function CartaoDaMedicao({ l, limitePorMil, ir }: { l: Linha; limitePorMil: number; ir: Ir }) {
  const recebida = l.etapa === "recebido";
  return (
    <li className="rdm-cartao">
      <Link className="rdm-cartao__obra" para={{ tela: "obra", id: l.contrato_id, aba: "medicoes" }} ir={ir}>{l.obra}</Link>
      <span className="rdm-cartao__sub">
        {l.contratante && <>{l.contratante} · </>}
        <Link className="link" para={{ tela: "medicao", obra: l.contrato_id, id: l.medicao_id }} ir={ir}>{l.titulo}</Link>
      </span>
      <span className="rdm-cartao__valor num">{l.valor_centavos === null || l.valor_centavos === 0 ? "—" : brl(l.valor_centavos)}</span>
      {recebida && l.recebida_em && (
        <span className="rdm-cartao__tempo">
          <Selo situacao="feito"><span className="sr-only">recebida </span>em {fmtDataCurta(l.recebida_em)}</Selo>
          {l.dias_da_nota_ao_recebimento !== null && (
            <span className="rdm-cartao__desde">
              {l.dias_da_nota_ao_recebimento === 0 ? "no dia da nota" : `${fmtDias(l.dias_da_nota_ao_recebimento)} após a nota`}
            </span>
          )}
        </span>
      )}
      {!recebida && l.parada && l.parada.desde && l.parada.dias_uteis !== null && (
        <span className="rdm-cartao__tempo">
          <TempoParado parada={l.parada} frase />
          {/* #914: na reapresentada o "1º protocolo em" da revisao ja' diz desde quando */}
          {!l.parada.hoje && !l.parada.revisao && <span className="rdm-cartao__desde">desde {fmtDataCurta(l.parada.desde)}</span>}
        </span>
      )}
      {temDiferenca(l) && (
        <Diferenca abaixo={l.abaixo_do_pedido_centavos} acima={l.acima_do_pedido_centavos} base={l.pedido_do_aprovado_centavos}
          nomeBase="pedido" limitePorMil={limitePorMil} />
      )}
    </li>
  );
}

function Coluna({ etapa, contagem, linhas, limitePorMil, ir }: {
  etapa: { chave: Etapa; rotulo: string }; contagem: ContagemDaEtapa | undefined; linhas: Linha[]; limitePorMil: number; ir: Ir;
}) {
  const n = contagem?.medicoes ?? 0;
  const id = `rdm-coluna-${etapa.chave}`;
  return (
    <section className={`rdm-coluna rdm-cor--${etapa.chave}`} aria-labelledby={id}>
      <div className="rdm-coluna__cab">
        <h3 id={id}><MarcaEtapa etapa={etapa.chave} /></h3>
        {n > 0 && (
          <p className="rdm-coluna__total">
            <span className="num">{contar(n, "medição", "medições")}</span>
            <span className="num">{brl(contagem?.valor_centavos ?? 0)}</span>
          </p>
        )}
      </div>
      {linhas.length === 0 ? <p className="rdm-coluna__vazia">nenhuma medição</p> : (
        <ul className="rdm-cartoes">
          {linhas.map(l => <CartaoDaMedicao key={l.medicao_id} l={l} limitePorMil={limitePorMil} ir={ir} />)}
        </ul>
      )}
    </section>
  );
}

export default function ResumoQuadro({ linhas, etapas, limitePorMil, rotulo, ir }: {
  linhas: Linha[]; etapas: ContagemDaEtapa[]; limitePorMil: number; rotulo: string; ir: Ir;
}) {
  const de = new Map(etapas.map(e => [e.etapa, e]));
  return (
    <div className="rdm-quadro" role="group" aria-label={rotulo}>
      {ETAPAS.map(e => (
        <Coluna key={e.chave} etapa={e} contagem={de.get(e.chave)} linhas={linhasDaEtapa(linhas, e.chave)}
          limitePorMil={limitePorMil} ir={ir} />
      ))}
    </div>
  );
}
