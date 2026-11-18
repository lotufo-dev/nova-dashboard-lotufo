import { textoDoTempo, type Parada } from "./parada";
import { diaMes } from "./Passos";
import Selo from "./Selo";
import "./barraDePassos.css";

// TempoParado (#805, familia de valor "tempo parado" de docs/identidade-visual.md): ha' quantos dias uteis a medicao
// esta' na situacao atual, no selo da situacao que o SERVIDOR leu (os limites do SIGA; no Pagamento, o prazo do orgao
// de docs/adr/0007). Aqui nao ha' conta nem limite: so' o desenho (o tipo e o texto estao em parada.ts).

/** O selo do tempo parado e, no Pagamento com prazo do orgao, a data esperada embaixo. Sem a data do evento, "—". */
export default function TempoParado({ parada }: { parada: Parada }) {
  if (parada.dias_uteis === null) return <span className="tempo-parado tempo-parado--sem">—</span>;
  const dia = diaMes(parada.esperada);
  return (
    <span className="tempo-parado">
      <Selo situacao={parada.situacao ?? undefined}>{textoDoTempo(parada)}</Selo>
      {dia && <span className="tempo-parado__prazo">{parada.alem_do_prazo ? `prazo do órgão venceu em ${dia}` : `prazo do órgão: ${dia}`}</span>}
    </span>
  );
}
