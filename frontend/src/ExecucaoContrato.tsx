import { useEffect, useState } from "react";
import { diasEntre, linhaDoTempo, seloDoPrazo } from "./obra";
import Selo from "./Selo";
import { fmtDataPura, hojeLocal } from "./tempo";
import { situacaoDoNivel } from "./situacao";

// "Execucao do contrato" (#160, prototipo aprovado): duas linhas do tempo, Execucao e Vigencia. Cada uma mostra a
// data de inicio, o marcador "Hoje" (calculado pela data do dia em Cuiaba: anda sozinho, e a tela o refaz na virada
// do dia sem recarregar) e a data final; o prazo perto do fim ou vencido vira selo (texto na tela, 26/10/2026:
// quantos dias restam nao se escreve). O nivel do selo e' o do servidor (`nivel_execucao` e `nivel_vigencia` do
// cabecalho da obra, `prazos.situacao` no servidor), o mesmo do numero dos dias: a tela so' mostra.

type Status = "ativo" | "suspenso" | "em_encerramento" | "encerrado" | "rescindido";
export type StatusDaObra = Status;
export type Nivel = "critico" | "atencao" | "normal";

/** A data do dia, relida a cada minuto: o marcador muda de lugar na virada do dia sem a pessoa recarregar. */
export function useHoje(): string {
  const [hoje, setHoje] = useState(hojeLocal);
  useEffect(() => {
    const t = window.setInterval(() => setHoje(hojeLocal()), 60_000);
    return () => window.clearInterval(t);
  }, []);
  return hoje;
}

function Linha({ titulo, inicio, fim, nivel, hoje, paralisada, soData, paradaEm }:
    { titulo: string; inicio: string | null; fim: string | null; nivel?: Nivel | null; hoje: string; paralisada?: boolean;
      soData?: boolean; paradaEm?: string | null }) {
  // obra paralisada com a data da ordem: o prazo nao corre, entao a marca fica parada no dia da paralisacao, no
  // lugar do "Hoje" (que andaria sozinho ate' o fim e alem dele). Vale tambem sem prazo de execucao conhecido
  // (#662): a linha mostra onde a obra parou no prazo registrado
  const parou = paralisada && paradaEm && fim && !Number.isNaN(diasEntre(paradaEm, fim)) ? paradaEm : null;
  // data final ausente ou ilegivel: so' a data, como a tela antiga (nunca "vencida ha NaN dias"). #662: tambem quando
  // o prazo de execucao de hoje nao e' conhecido (`soData`): a data registrada, sem trilho nem selo de vencida
  if (!fim || (soData && !parou) || Number.isNaN(diasEntre(hoje, fim))) {
    return (
      <div className="lt">
        <p className="lt__titulo"><span>{titulo}</span></p>
        <p className="lt__nota lt__nota--esq">{fim ? fmtDataPura(fim) : "—"}</p>
      </div>
    );
  }
  const { posicao, restantes } = linhaDoTempo(inicio, fim, parou ?? hoje);
  // o servidor decide se ha' prazo a cobrar (so' em obra ativa; D16: a paralisada nao conta o vencimento da execucao)
  const selo = parou ? null : seloDoPrazo(nivel, restantes);
  const pos = posicao ?? 0;
  return (
    <div className="lt">
      <p className="lt__titulo"><span>{titulo}</span>{paralisada && <Selo situacao="breve">paralisada</Selo>}
        {selo && <Selo situacao={situacaoDoNivel(selo.classe)}>{selo.texto}</Selo>}</p>
      {posicao === null ? (
        <p className="lt__nota lt__nota--esq">—</p>
      ) : (
        <div className="lt__trilho" role="img"
          aria-label={parou ? `${titulo}: de ${fmtDataPura(inicio ?? "")} a ${fmtDataPura(fim)}, paralisada em ${fmtDataPura(parou)}, com ${Math.round(pos)}% do prazo corrido`
            : `${titulo}: de ${fmtDataPura(inicio ?? "")} a ${fmtDataPura(fim)}, hoje em ${Math.round(pos)}% do prazo`}>
          <span className="lt__feito" style={{ width: `${pos}%` }} />
          <span className="lt__hoje" style={{ left: `${pos}%`, transform: `translateX(-${pos}%)`, ["--p" as string]: `${pos}%` }}>
            {parou ? `Paralisada em ${fmtDataPura(parou)}` : `Hoje ${fmtDataPura(hoje)}`}
          </span>
          <span className="lt__marca" style={{ left: `${pos}%` }} />
        </div>
      )}
      <div className="lt__datas">
        <span>{inicio ? fmtDataPura(inicio) : ""}</span>
        <span>{fmtDataPura(fim)}</span>
      </div>
    </div>
  );
}

type Props = { execucaoInicio: string | null; execucaoFim: string | null; vigenciaInicio: string | null; vigenciaFim: string | null;
  status: Status; execucaoSemPrazo?: boolean; nivelExecucao?: Nivel | null; nivelVigencia?: Nivel | null;
  paralisadaDesde?: string | null };

/** As duas linhas do tempo, sem moldura: o painel "Prazo" da pagina da obra as traz dentro dele. */
export function LinhasDoTempo({ execucaoInicio, execucaoFim, vigenciaInicio, vigenciaFim, status, execucaoSemPrazo,
    nivelExecucao, nivelVigencia, paralisadaDesde }: Props) {
  const hoje = useHoje();
  return (
    <div className="linhas-tempo">
      <Linha titulo="Execução" inicio={execucaoInicio} fim={execucaoFim} nivel={nivelExecucao} hoje={hoje}
        paralisada={status === "suspenso" || !!paralisadaDesde} soData={execucaoSemPrazo} paradaEm={paralisadaDesde} />
      <Linha titulo="Vigência" inicio={vigenciaInicio} fim={vigenciaFim} nivel={nivelVigencia} hoje={hoje} />
    </div>
  );
}

export default function ExecucaoContrato(props: Props) {
  return (
    <section className="cartao" aria-labelledby="titulo-execucao">
      <div className="cartao__cabeca"><h2 className="cartao__titulo" id="titulo-execucao">Execução do contrato</h2></div>
      <LinhasDoTempo {...props} />
    </section>
  );
}
