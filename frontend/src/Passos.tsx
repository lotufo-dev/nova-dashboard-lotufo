import { IconeCheck } from "./NotasAEnviar";
import { fmtData, fmtDataPura } from "./tempo";
import "./passos.css";

// Issue #508 (aprovado em 06/11/2026, "Fluxo da medição por obra"): a medicao de uma obra e' um fluxo unico numa
// pagina so', com a BARRA DE PASSOS numerados no alto. Os mesmos nomes em toda obra; a obra so' deixa de mostrar o
// passo que nao tem (MT-PAR comeca em Espelhos, com 4 passos). O id do passo (1..6) e' fixo; o numero na tela e' a
// posicao dele na barra da obra. 7 = tudo feito (recebida); 0 = encerrada por excecao (cancelada, desistida).

export const PASSOS = ["Planilha e carta", "Análise do órgão", "Espelhos", "Notas", "Envio da nota", "Pagamento"] as const;

/** O passo da vez pelo estado da medicao. `comPlanilha`: a obra tem os passos 1 e 2 (a planilha/carta vai ao orgao). */
export function passoDe(estado: string, comPlanilha: boolean): number {
  switch (estado) {
    case "prevista": case "planilha_gerada": return comPlanilha ? 1 : 3;
    case "planilha_enviada": return comPlanilha ? 2 : 3;
    case "boletim_recebido": case "espelho_gerado": return 3;
    case "espelho_enviado": return 4;
    case "nota_emitida": return 5;
    case "protocolada": case "nf_emitida": return 6;
    case "recebida": return 7;
    default: return 0;
  }
}

/** Os passos que a barra mostra, pelo id. */
export function passosDa(comPlanilha: boolean): number[] {
  return comPlanilha ? [1, 2, 3, 4, 5, 6] : [3, 4, 5, 6];
}

export type SituacaoPasso = "feito" | "atual" | "futuro";
export function situacaoDoPasso(n: number, atual: number): SituacaoPasso {
  return atual === 0 || n < atual ? "feito" : n === atual ? "atual" : "futuro";
}

/** O passo que a pagina abre: o da vez; tudo feito abre o pagamento; encerrada abre a nota (se saiu) ou o primeiro. */
export function passoInicial(atual: number, temNota: boolean, passos: number[]): number {
  if (atual === 0) return temNota ? 4 : passos[0];
  return Math.min(atual, 6);
}

/** "dd/mm" de uma data pura ("AAAA-MM-DD") ou de um carimbo UTC (o dia em Cuiaba). */
export function diaMes(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const longa = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? fmtDataPura(iso) : fmtData(iso);
  return /^\d{2}\/\d{2}\//.test(longa) ? longa.slice(0, 5) : null;
}

/** A barra: feito = check indigo com a data; atual = circulo maior com o numero; futuro = cinza. `espera` (#188): o
 *  passo da vez parado esperando a outra metade (execucao x reajuste no mesmo e-mail). */
export function Passos({ passos, atual, vendo, datas, espera = false, aoIr }: {
  passos: number[]; atual: number; vendo: number; datas: Record<number, string | null>; espera?: boolean;
  aoIr: (n: number) => void;
}) {
  return (
    <nav className="passos" aria-label="Passos da medição">
      <ol>
        {passos.map((n, i) => {
          const nome = PASSOS[n - 1];
          const s = situacaoDoPasso(n, atual);
          const parada = espera && s === "atual";
          const data = s === "feito" ? datas[n] ?? null : null;
          const classes = ["passo", `passo--${parada ? "espera" : s}`];
          if (n === vendo) classes.push("passo--aberto");
          return (
            <li key={n} className={classes.join(" ")} aria-current={s === "atual" ? "step" : undefined}>
              <button type="button" aria-label={`Passo ${i + 1}: ${nome}${data ? `, feito em ${data}` : ""}${parada ? " · em espera" : ""}`}
                onClick={() => aoIr(n)}>
                <span className="passo__marca" aria-hidden="true">{s === "feito" ? <IconeCheck /> : i + 1}</span>
                <span className="passo__nome">{nome}</span>
                {data && <span className="passo__data num" aria-hidden="true">{data}</span>}
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** "Você está vendo o passo N, já feito · Voltar ao passo atual": outro passo aberto no lugar do da vez. */
export function FaixaPasso({ vendo, atual, passos, aoVoltar }: {
  vendo: number; atual: number; passos: number[]; aoVoltar: () => void;
}) {
  if (atual === 0 || vendo === Math.min(atual, 6)) return null;
  const feito = situacaoDoPasso(vendo, atual) === "feito";
  return (
    <div className="med-faixa">
      <span>Você está vendo o passo {passos.indexOf(vendo) + 1}{feito ? ", já feito" : ""}</span>
      <button type="button" className="botao-link" onClick={aoVoltar}>Voltar ao passo atual</button>
    </div>
  );
}

/** O cartao do passo aberto (passos 3 a 6): "Passo N", o nome e a situacao. */
export function PassoCartao({ n, atual, passos, selo, children }: {
  n: number; atual: number; passos: number[]; selo?: React.ReactNode; children?: React.ReactNode;
}) {
  const s = situacaoDoPasso(n, atual);
  const pos = passos.indexOf(n) + 1;
  return (
    <section className="cartao med-etapa" id={`passo-${n}`} aria-labelledby={`passo-${n}-titulo`}>
      <div className="med-etapa__cabeca">
        <span className="med-etapa__n">Passo {pos}</span>
        <h2 className="med-etapa__titulo" id={`passo-${n}-titulo`}>{PASSOS[n - 1]}</h2>
        {selo ?? (atual !== 0 && s === "feito" ? <span className="selo selo--ok"><span className="selo__ponto" aria-hidden="true" /><span className="selo__texto">Feito</span></span>
          : s === "futuro" ? <span className="selo"><span className="selo__ponto" aria-hidden="true" /><span className="selo__texto">Libera depois do passo {pos - 1}</span></span> : null)}
      </div>
      {children}
    </section>
  );
}
