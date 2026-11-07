// Legenda pequena da regra de cor da informacao, no topo direito das telas que a usam (docs/identidade-visual.md).
// Cada tela que aplica a regra a coloca; aqui so' o componente.
const ITENS = [
  { classe: "feito", texto: "feito" },
  { classe: "andamento", texto: "em andamento" },
  { classe: "breve", texto: "vence em breve" },
  { classe: "critico", texto: "crítico" },
] as const;

export default function LegendaCor() {
  return (
    <ul className="legenda-cor" aria-label="Legenda das cores">
      {ITENS.map(i => (
        <li key={i.classe}><span className={`pilula-info__ponto ponto--${i.classe}`} />{i.texto}</li>
      ))}
    </ul>
  );
}
