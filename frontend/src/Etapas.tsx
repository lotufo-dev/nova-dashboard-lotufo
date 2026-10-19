import { IconeCheck } from "./NotasAEnviar";
import "./etapas.css";

// Fluxo da medicao numa pagina so' (opcao B, aprovada em 16/10/2026): trilho de 5 etapas em setas -- Espelho,
// Faturamento, Nota fiscal, Envio ao orgao e Pagamento --, com so' a etapa aberta. A da vez vem do estado da
// medicao; clicar numa feita abre no lugar da atual, com a faixa para voltar.

export const ETAPAS = ["Espelho", "Faturamento", "Nota fiscal", "Envio ao órgão", "Pagamento"] as const;

/** 1..5 = a etapa da vez; 6 = tudo feito (recebida); 0 = medicao encerrada por excecao (cancelada, desistida). */
export function etapaDe(estado: string): number {
  switch (estado) {
    case "prevista": return 1;
    case "espelho_gerado": return 2;
    case "espelho_enviado": return 3;
    case "nota_emitida": return 4;
    case "protocolada": case "nf_emitida": return 5;
    case "recebida": return 6;
    default: return 0;
  }
}

export type SituacaoEtapa = "feita" | "atual" | "futura";
export function situacaoDa(n: number, atual: number): SituacaoEtapa {
  return atual === 0 || n < atual ? "feita" : n === atual ? "atual" : "futura";
}

/** A etapa que a pagina abre: a da vez; tudo feito abre o pagamento; encerrada por excecao abre a ultima que teve
 *  dado (a nota, se saiu, senao o espelho). */
export function etapaInicial(atual: number, temNota: boolean): number {
  if (atual === 0) return temNota ? 3 : 1;
  return Math.min(atual, 5);
}

/** O trilho no alto: cinco setas, cada uma abre a etapa dela na pagina. `espera` (issue #188): a etapa da vez esta'
 *  parada esperando a outra metade (execucao x reajuste no mesmo e-mail). Medicao encerrada por excecao
 *  (`atual` 0) mostra o trilho neutro: nenhuma etapa "feita" nem "da vez". */
export function Setas({ atual, vendo, aoIr, espera = false }: {
  atual: number; vendo: number; aoIr: (n: number) => void; espera?: boolean;
}) {
  return (
    <nav className="setas" aria-label="Etapas da medição">
      <ol>
        {ETAPAS.map((t, i) => {
          const n = i + 1;
          const s = atual === 0 ? "encerrada" : situacaoDa(n, atual);
          const parada = espera && s === "atual";
          const aberta = n === vendo;
          return (
            <li key={t} className={`seta seta--${parada ? "espera" : s}${aberta && s !== "atual" ? " seta--vendo" : ""}${aberta ? " seta--rotulo" : ""}`}
              aria-current={s === "atual" ? "step" : undefined}>
              <button type="button" title={t} aria-label={`Etapa ${n}: ${t}${parada ? " · em espera" : ""}`} onClick={() => aoIr(n)}>
                <span className="seta__marca" aria-hidden="true">{s === "feita" ? <IconeCheck /> : n}</span>
                <span className="seta__rotulo">{t}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** "Você está vendo a etapa N, já feita · Voltar à etapa atual": a etapa aberta no lugar da atual. */
export function FaixaVendo({ vendo, atual, aoVoltar }: { vendo: number; atual: number; aoVoltar: () => void }) {
  // medicao encerrada por excecao nao tem "etapa atual"; tudo feito (6) volta ao pagamento
  if (atual === 0 || vendo === Math.min(atual, 5)) return null;
  return (
    <div className="med-faixa" role="status">
      <span>Você está vendo a etapa {vendo}, {vendo < atual ? "já feita" : "que ainda não começou"}</span>
      <span aria-hidden="true">·</span>
      <button type="button" className="botao-link" onClick={aoVoltar}>Voltar à etapa atual</button>
    </div>
  );
}

/** O cartao da etapa aberta: "Etapa N", o titulo, a situacao e o resumo de uma linha. */
export function EtapaCartao({ n, atual, resumo, selo, children }: {
  n: number; atual: number; resumo?: React.ReactNode; selo?: React.ReactNode; children?: React.ReactNode;
}) {
  const s = atual === 0 ? "encerrada" : situacaoDa(n, atual);
  return (
    <section className="cartao med-etapa" id={`etapa-${n}`} aria-labelledby={`etapa-${n}-titulo`}>
      <div className="med-etapa__cabeca">
        <span className="med-etapa__n">Etapa {n}</span>
        <h2 className="med-etapa__titulo" id={`etapa-${n}-titulo`}>{ETAPAS[n - 1]}</h2>
        {selo ?? (s === "feita" ? <span className="selo selo--ok"><span className="selo__ponto" aria-hidden="true" /><span className="selo__texto">Feita</span></span>
          : s === "futura" ? <span className="selo"><span className="selo__ponto" aria-hidden="true" /><span className="selo__texto">Libera depois da etapa {n - 1}</span></span> : null)}
        {resumo && <span className="med-etapa__resumo">{resumo}</span>}
      </div>
      {children}
    </section>
  );
}
