import { brl } from "./formato";
import { IconeCadeado } from "./icones";
import { Link } from "./Link";
import { EXCECOES, rotuloDoValor, tituloMedicao, type Evento } from "./medicao";
import { valorEditavel } from "./MedicaoAtos";
import { Estado, ROTULO_ESTADO, type Medicao } from "./Medicoes";
import type { Rota } from "./rota";
import Selo, { Glifo } from "./Selo";
import { fmtCompetencia, fmtDataHora, fmtDataPura } from "./tempo";

// O alto e o lado da pagina da medicao (#722, como o dono montou em 16/11/2026): o valor grande com o rotulo dele na
// identificacao, o Resumo em faixa de colunas logo abaixo e a Linha do tempo na coluna ao lado do passo (embaixo na
// tela estreita). Sempre a' vista, qualquer que seja o passo aberto.

function quando(iso: string): string {
  return iso.length > 10 ? fmtDataHora(iso) : fmtDataPura(iso);
}

// `acao`: o passo se resolve numa janela da pagina (ex.: "boletim"), nao numa secao (#568)
export type PassoResumo = { rotulo: string; secao: string; acao?: string } | null;

/** O valor grande do alto, com o rotulo dele: "Valor da medição" ate' o protocolo e "Protocolado" depois; no par
 *  (medicao + reajuste) e' o "Total" dos dois. O valor editavel a' mao leva o "Editar o valor" ao lado do rotulo. */
export function ValorDaPagina({ m, doPar, valor, podeEditar, salvando, aoEditarValor }: {
  m: Medicao; doPar: boolean; valor: number | null; podeEditar: boolean; salvando: boolean; aoEditarValor: () => void;
}) {
  const rotulo = doPar ? "Total" : rotuloDoValor(m.estado) === "protocolado" ? "Protocolado" : "Valor da medição";
  return (
    <div className="med-valor-bloco">
      <p className="med-valor__rotulo">
        <span>{rotulo}</span>
        {valorEditavel(m, "protocolado", podeEditar) && (
          <button type="button" id="ato-protocolado" className="botao-link" disabled={salvando} onClick={aoEditarValor}>
            {m.valor_protocolado_centavos === null ? "Definir o valor" : "Editar o valor"}
          </button>
        )}
      </p>
      <p className="med-valor num" aria-label={`Valor: ${brl(valor)}`}>{brl(valor)}</p>
    </div>
  );
}

/** A situacao da medicao no resumo: o sinal da situacao (feito na recebida, em andamento nas demais) e o nome do
 *  estado; a encerrada por excecao (cancelada, desistida) fica como nas listas, riscada e sem sinal. */
function Situacao({ m }: { m: Medicao }) {
  if (EXCECOES.includes(m.estado)) return <Estado m={m} />;
  return (
    <span className="med-situacao">
      <Glifo situacao={m.estado === "recebida" ? "feito" : "andamento"} />
      <span>{ROTULO_ESTADO[m.estado] ?? m.estado}</span>
      {m.final === 1 && <Selo situacao="breve">final</Selo>}
      {m.congelada === 1 && <span className="cadeado"><IconeCadeado className="icone icone--p" titulo="Congelada" /></span>}
    </span>
  );
}

export function ResumoMedicao({ m, execucao, reajuste, outras, passo, aqui, contratoId, aoAcao }: {
  m: Medicao; execucao: Medicao | null; reajuste: Medicao | null; outras: Medicao[];
  passo: PassoResumo; aqui: Rota; contratoId: number; aoAcao?: (acao: string) => void;
}) {
  const doPar = execucao && reajuste;
  const rotuloValor = rotuloDoValor(m.estado) === "protocolado" ? "Protocolado" : "Valor da medição";
  return (
    <section className="med-resumo" aria-labelledby="t-resumo">
      <h2 className="sr-only" id="t-resumo">Resumo da medição</h2>
      <dl className="res-lista">
        <div><dt>Situação</dt><dd><Situacao m={m} /></dd></div>
        {passo && (
          <div><dt>Próximo passo</dt><dd>
            {passo.acao && aoAcao ? (
              <button type="button" className="btn btn--pequeno" onClick={() => aoAcao(passo.acao!)}>{passo.rotulo}</button>
            ) : passo.secao ? <Link className="link forte" para={aqui} secao={passo.secao}>{passo.rotulo}</Link> : passo.rotulo}
          </dd></div>
        )}
        <div><dt>Competência</dt><dd className="num">{fmtCompetencia(m.competencia)}</dd></div>
        {/* no par, o valor de cada metade; o total dos dois e' o valor grande do alto */}
        {doPar && (
          <>
            <div><dt>{rotuloValor}</dt><dd className="num res-valor">{brl(execucao.valor_protocolado_centavos)}</dd></div>
            <div><dt>Reajuste</dt><dd className="num res-valor">{brl(reajuste.valor_protocolado_centavos)}</dd></div>
          </>
        )}
        {(m.valor_atestado_centavos !== null || m.atestado_em) && (
          <div>
            <dt>Atestado</dt>
            <dd className="num res-valor">{brl(m.valor_atestado_centavos)}</dd>
            {m.atestado_em && <dd className="res-nota">atestada em {fmtDataPura(m.atestado_em)}</dd>}
          </div>
        )}
        <div><dt>Medição final</dt><dd>{m.final === 1 ? "Sim" : "Não"}</dd></div>
        <div>
          <dt>Da mesma competência</dt>
          <dd>{outras.length === 0 ? "—"
            : outras.map(x => (
              <span key={x.id} className="res-nota res-nota--link">
                <Link className="link" para={{ tela: "medicao", obra: contratoId, id: x.id }}>{tituloMedicao(x)}</Link> · <Estado m={x} />
              </span>
            ))}</dd>
        </div>
      </dl>
    </section>
  );
}

export function LinhaDoTempo({ eventos }: { eventos: Evento[] }) {
  return (
    <section className="cartao med-tempo" aria-labelledby="t-tempo">
      <h2 className="med-tempo__titulo" id="t-tempo">Linha do tempo</h2>
      {eventos.length === 0 ? <p className="campo__nota">Nada registrado ainda.</p> : (
        <ol className="tempo">
          {[...eventos].reverse().map((e, i) => (
            <li key={i}><time>{quando(e.data)}</time>
              <p>{e.texto}
                {e.href && <> <a className="link" href={e.href} target="_blank" rel="noopener noreferrer">Ver o boletim</a></>}</p></li>
          ))}
        </ol>
      )}
    </section>
  );
}
