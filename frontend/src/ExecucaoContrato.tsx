import { useEffect, useState } from "react";
import { diasEntre, linhaDoTempo, seloDoPrazo } from "./obra";
import Selo from "./Selo";
import { fmtDataPura, hojeLocal } from "./tempo";

// "Execucao do contrato" (#160, prototipo aprovado): duas linhas do tempo, Execucao e Vigencia. Cada uma mostra a
// data de inicio, o marcador "Hoje" (calculado pela data do dia em Cuiaba: anda sozinho, e a tela o refaz na virada
// do dia sem recarregar) e a data final; o prazo perto do fim ou vencido vira selo (seloDoPrazo; texto na tela,
// 26/10/2026: quantos dias restam nao se escreve).

type Status = "ativo" | "suspenso" | "em_encerramento" | "encerrado" | "rescindido";

/** A data do dia, relida a cada minuto: o marcador muda de lugar na virada do dia sem a pessoa recarregar. */
export function useHoje(): string {
  const [hoje, setHoje] = useState(hojeLocal);
  useEffect(() => {
    const t = window.setInterval(() => setHoje(hojeLocal()), 60_000);
    return () => window.clearInterval(t);
  }, []);
  return hoje;
}

function Linha({ titulo, inicio, fim, status, hoje, paralisada }:
    { titulo: string; inicio: string | null; fim: string | null; status: Status; hoje: string; paralisada?: boolean }) {
  // data final ausente ou ilegivel: so' a data, como a tela antiga (nunca "vencida ha NaN dias")
  if (!fim || Number.isNaN(diasEntre(hoje, fim))) {
    return (
      <div className="lt">
        <p className="lt__titulo"><span>{titulo}</span></p>
        <p className="lt__nota lt__nota--esq">{fim ? fmtDataPura(fim) : "—"}</p>
      </div>
    );
  }
  const { posicao, restantes } = linhaDoTempo(inicio, fim, hoje);
  // D16: obra paralisada nao conta o vencimento da execucao (Lei 14.133, art. 115, par. 5o). Prazo vencido so' em
  // obra ativa (a mesma regra da lista de Obras); nos outros casos o servidor nao avisa de proposito.
  const selo = status === "ativo" && !paralisada ? seloDoPrazo(restantes) : null;
  const pos = posicao ?? 0;
  return (
    <div className="lt">
      <p className="lt__titulo"><span>{titulo}</span>{paralisada && <Selo classe="selo--atencao">paralisada</Selo>}
        {selo && <Selo classe={selo.classe}>{selo.texto}</Selo>}</p>
      {posicao === null ? (
        <p className="lt__nota lt__nota--esq">—</p>
      ) : (
        <div className="lt__trilho" role="img"
          aria-label={`${titulo}: de ${fmtDataPura(inicio ?? "")} a ${fmtDataPura(fim)}, hoje em ${Math.round(pos)}% do prazo`}>
          <span className="lt__feito" style={{ width: `${pos}%` }} />
          <span className="lt__hoje" style={{ left: `${pos}%`, transform: `translateX(-${pos}%)`, ["--p" as string]: `${pos}%` }}>
            Hoje {fmtDataPura(hoje)}
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

export default function ExecucaoContrato({ execucaoInicio, execucaoFim, vigenciaInicio, vigenciaFim, status }:
    { execucaoInicio: string | null; execucaoFim: string | null; vigenciaInicio: string | null; vigenciaFim: string | null;
      status: Status }) {
  const hoje = useHoje();
  return (
    <section className="cartao" aria-labelledby="titulo-execucao">
      <div className="cartao__cabeca"><h2 className="cartao__titulo" id="titulo-execucao">Execução do contrato</h2></div>
      <div className="linhas-tempo">
        <Linha titulo="Execução" inicio={execucaoInicio} fim={execucaoFim} status={status} hoje={hoje} paralisada={status === "suspenso"} />
        <Linha titulo="Vigência" inicio={vigenciaInicio} fim={vigenciaFim} status={status} hoje={hoje} />
      </div>
    </section>
  );
}
