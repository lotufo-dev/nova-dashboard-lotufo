import type { Situacao } from "./situacao";

// Situacao (#720): cada uma das quatro tem cor E forma (o glifo): feito = circulo com visto, andamento = circulo
// meio cheio, breve (vence em breve) = triangulo com exclamacao, critico = octogono com exclamacao. A forma sai da
// situacao, e nao de quem chama: a mesma situacao tem a mesma cara em qualquer tela (situacao.ts, tokens.css).

/** O simbolo da situacao, solto (legenda, lista, faixa de aviso). Decorativo: o rotulo ao lado diz a situacao. */
export function Glifo({ situacao }: { situacao: Situacao }) {
  return <span className={`glifo glifo--${situacao}`} aria-hidden="true" />;
}

/** Selo: a situacao de uma linha (prazo, documento, medicao), sempre glifo + rotulo. Sem `situacao` e' neutro e nao
 *  leva glifo. A maiuscula inicial vem do CSS; o texto fica como o servidor manda. */
export default function Selo({ situacao, className, sufixo, title, children }: {
  situacao?: Situacao; className?: string; sufixo?: React.ReactNode; title?: string; children: React.ReactNode;
}) {
  return (
    <span className={`selo${situacao ? ` selo--${situacao}` : ""}${className ? ` ${className}` : ""}`} title={title}>
      {situacao && <Glifo situacao={situacao} />}
      <span className="selo__texto">{children}</span>
      {sufixo}
    </span>
  );
}

// Selo do nivel de uma pendencia (F-46): a palavra e' o proprio nivel, no vocabulario dos avisos.
// O neutro e' o passo do ciclo ("Passo"), que nao trava nem atrasa.
export function SeloNivel({ nivel }: { nivel: "critico" | "atencao" | "neutro" }) {
  return nivel === "critico" ? <Selo situacao="critico">Crítico</Selo>
    : nivel === "atencao" ? <Selo situacao="breve">Atenção</Selo>
    : <Selo>Passo</Selo>;
}
