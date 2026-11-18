import { Glifo } from "./Selo";
import type { Situacao } from "./situacao";

/** Contador (#720): a quantidade ao lado de um titulo. Neutro sem glifo; com situacao, traz o glifo dela. `rotulo`
 *  e' o que o leitor de tela diz no lugar do numero solto ("3 linhas"): vai como texto so' de leitor de tela, e o
 *  numero desenhado sai da leitura. `aria-label` num <span> sem papel o leitor de tela costuma ignorar (#721). */
export default function Contador({ situacao, rotulo, children }: {
  situacao?: Situacao; rotulo?: string; children: React.ReactNode;
}) {
  return (
    <span className={`contador${situacao ? ` contador--${situacao}` : ""}`}>
      {situacao && <Glifo situacao={situacao} />}
      {rotulo ? <><span aria-hidden="true">{children}</span><span className="sr-only">{rotulo}</span></> : children}
    </span>
  );
}
