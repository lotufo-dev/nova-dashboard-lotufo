import { Glifo } from "./Selo";
import type { Situacao } from "./situacao";

/** Contador (#720): a quantidade ao lado de um titulo. Neutro sem glifo; com situacao, traz o glifo dela. `rotulo`
 *  e' o que o leitor de tela diz no lugar do numero solto ("3 linhas"). */
export default function Contador({ situacao, rotulo, children }: {
  situacao?: Situacao; rotulo?: string; children: React.ReactNode;
}) {
  return (
    <span className={`contador${situacao ? ` contador--${situacao}` : ""}`} aria-label={rotulo}>
      {situacao && <Glifo situacao={situacao} />}
      {children}
    </span>
  );
}
