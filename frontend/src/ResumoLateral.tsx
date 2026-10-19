import { brl } from "./formato";
import { Link } from "./Link";
import { rotuloDoValor, tituloMedicao, type Evento } from "./medicao";
import { notaDoEspelho, valorEditavel } from "./MedicaoAtos";
import { Estado, type Medicao } from "./Medicoes";
import type { Rota } from "./rota";
import { fmtCompetencia, fmtDataHora, fmtDataPura } from "./tempo";

// A coluna da direita da pagina da medicao (#152): o Resumo da medicao e a Linha do tempo, sempre a' vista,
// qualquer que seja a etapa aberta.

function quando(iso: string): string {
  return iso.length > 10 ? fmtDataHora(iso) : fmtDataPura(iso);
}

export type PassoResumo = { rotulo: string; secao: string } | null;

export function ResumoMedicao({ m, execucao, reajuste, outras, passo, desde, aqui, contratoId, podeEditar, salvando, aoEditarValor }: {
  m: Medicao; execucao: Medicao | null; reajuste: Medicao | null; outras: Medicao[];
  passo: PassoResumo; desde?: string; aqui: Rota; contratoId: number;
  podeEditar: boolean; salvando: boolean; aoEditarValor: () => void;
}) {
  const doPar = execucao && reajuste;
  const soma = doPar ? (execucao.valor_protocolado_centavos ?? 0) + (reajuste.valor_protocolado_centavos ?? 0) : null;
  const rotuloValor = rotuloDoValor(m.estado) === "protocolado" ? "Protocolado" : "Valor da medição";
  const nota = notaDoEspelho(m);
  return (
    <section className="cartao" aria-labelledby="t-resumo">
      <div className="cartao__cabeca"><h2 className="cartao__titulo" id="t-resumo">Resumo da medição</h2></div>
      <div className="cartao__corpo">
        <dl className="res-lista">
          <div><dt>Situação</dt><dd><Estado m={m} /></dd></div>
          {passo && (
            <div><dt>Próximo passo</dt><dd>
              {passo.secao ? <Link className="link forte" para={aqui} secao={passo.secao}>{passo.rotulo}</Link> : passo.rotulo}
              {desde && <span className="res-nota">desde {fmtDataPura(desde)}</span>}
            </dd></div>
          )}
          <div><dt>Competência</dt><dd className="num">{fmtCompetencia(m.competencia)}</dd></div>
          {doPar ? (
            <>
              <div><dt>{rotuloValor}{nota && <span className="res-nota">{nota}</span>}</dt><dd className="num">{brl(execucao.valor_protocolado_centavos)}</dd></div>
              <div><dt>Reajuste</dt><dd className="num">{brl(reajuste.valor_protocolado_centavos)}</dd></div>
              <div className="res-total"><dt>Total</dt><dd className="num">{brl(soma)}</dd></div>
            </>
          ) : (
            <div>
              <dt>{rotuloValor}{nota && <span className="res-nota">{nota}</span>}</dt>
              <dd className="num">{brl(m.valor_protocolado_centavos)}</dd>
            </div>
          )}
          {valorEditavel(m, "protocolado", podeEditar) && (
            <div><dt /><dd>
              <button type="button" id="ato-protocolado" className="btn btn--pequeno" disabled={salvando} onClick={aoEditarValor}>
                {m.valor_protocolado_centavos === null ? "Definir o valor" : "Editar o valor"}
              </button>
            </dd></div>
          )}
          {(m.valor_atestado_centavos !== null || m.atestado_em) && (
            <div>
              <dt>Atestado{m.atestado_em && <span className="res-nota">atestada em {fmtDataPura(m.atestado_em)} · editável em Mais ações</span>}</dt>
              <dd className="num">{brl(m.valor_atestado_centavos)}</dd>
            </div>
          )}
          <div><dt>Medição final</dt><dd>{m.final === 1 ? "Sim · contrato em encerramento" : "Não"}</dd></div>
          <div>
            <dt>Da mesma competência</dt>
            <dd>{outras.length === 0 ? <span className="res-nota">nenhuma outra medição</span>
              : outras.map(x => (
                <span key={x.id} className="res-nota res-nota--link">
                  <Link className="link" para={{ tela: "medicao", obra: contratoId, id: x.id }}>{tituloMedicao(x)}</Link> · <Estado m={x} />
                </span>
              ))}</dd>
          </div>
        </dl>
      </div>
    </section>
  );
}

export function LinhaDoTempo({ eventos }: { eventos: Evento[] }) {
  return (
    <section className="cartao" aria-labelledby="t-tempo">
      <div className="cartao__cabeca"><h2 className="cartao__titulo" id="t-tempo">Linha do tempo</h2></div>
      <div className="cartao__corpo">
        {eventos.length === 0 ? <p className="campo__nota">Nada registrado ainda.</p> : (
          <ol className="tempo">
            {[...eventos].reverse().map((e, i) => <li key={i}><time>{quando(e.data)}</time>{e.texto}</li>)}
          </ol>
        )}
      </div>
    </section>
  );
}
