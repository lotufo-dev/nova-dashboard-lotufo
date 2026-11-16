import { IconeProibido } from "./icones";
import { Glifo } from "./Selo";

// Caixa de aviso (#720): tres formas que se distinguem de relance, e a FORMA sai do nivel, nunca de quem chama.
// - "trava": bloco cheio no critico, texto claro e o sinal de proibido. A acao esta' impedida: o botao dela fica
//   desligado ao lado.
// - "atencao": faixa clara do "vence em breve" com o triangulo. Pede confirmacao ou atencao; a acao segue, com o
//   botao ativo.
// - "critico": faixa clara do critico com o octogono (diverge, venceu, passou do limite). Nao trava.
// A justificativa escrita tem a propria caixa, de moldura grossa: CaixaJustificativa, abaixo.
export type NivelAviso = "trava" | "critico" | "atencao";

export default function CaixaAviso({ nivel, como = "p", role, className, children }: {
  nivel: NivelAviso; como?: "p" | "span" | "div"; role?: "alert" | "status"; className?: string; children: React.ReactNode;
}) {
  const Tag = como;
  const classe = `aviso${nivel === "atencao" ? "" : ` aviso--${nivel}`}${className ? ` ${className}` : ""}`;
  return (
    <Tag className={classe} role={role}>
      {nivel === "trava" ? <IconeProibido className="icone" />
        : <Glifo situacao={nivel === "critico" ? "critico" : "breve"} />}
      {/* a palavra do nivel para o leitor de tela: o simbolo e' decorativo (aria-hidden) */}
      <span><span className="sr-only">{nivel === "atencao" ? "Atenção: " : "Crítico: "}</span>{children}</span>
    </Tag>
  );
}

/** A caixa da justificativa: moldura grossa de tinta em volta do rotulo, do campo obrigatorio e do erro dele. Fica
 *  junto do botao que a exige. Quem chama poe o rotulo, o campo e o ErroCampo dentro. */
export function CaixaJustificativa({ children }: { children: React.ReactNode }) {
  return <div className="campo justificativa">{children}</div>;
}
