import { ROTULO_DA_ETAPA, type Etapa } from "./valores";

// MarcaEtapa (#805, familias de valor): a etapa do dinheiro, dita pelo quadradinho do tom dela ao lado do rotulo. Os
// tons sao os da Inicio (--etapa-*): do azul claro da analise ao azul escuro do protocolado, e o verde do recebido. O
// "em aberto" nao e' etapa do ciclo (e' o que falta receber) e leva outra forma, um triangulo no tom do "vence em
// breve"; o "atrasado" e' a protocolada alem do prazo do orgao, no tom do critico. Uma peca so', para a legenda da
// matriz da Inicio e para o cabecalho das colunas de valor.

/** A marca da etapa e o rotulo. Sem `children`, o rotulo e' o nome da etapa; com ele, o nome que a tela usa para o
 *  valor daquela etapa ("Aprovado" e' o valor do boletim). A marca e' desenho: o rotulo diz a etapa. */
export default function MarcaEtapa({ etapa, children }: { etapa: Etapa; children?: React.ReactNode }) {
  return (
    <span className="marca-etapa">
      <span className={`marca-etapa__cor marca-etapa__cor--${etapa}`} aria-hidden="true" />
      {children ?? ROTULO_DA_ETAPA[etapa]}
    </span>
  );
}
