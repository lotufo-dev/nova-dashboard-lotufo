import { fraseDoTempo, partesDaRevisao, textoDoTempo, type Parada } from "./parada";
import Selo from "./Selo";
import { fmtDiaNoAno } from "./tempo";
import "./barraDePassos.css";

// TempoParado (#805, familia de valor "tempo parado" de docs/identidade-visual.md): ha' quantos dias uteis a medicao
// esta' na situacao atual, no selo da situacao que o SERVIDOR leu (os limites do SIGA; no Pagamento, o prazo do orgao
// de docs/adr/0007). Aqui nao ha' conta nem limite: so' o desenho (o tipo e o texto estao em parada.ts).

/** O selo do tempo parado e, no Pagamento com prazo do orgao, a data esperada embaixo: "dd/mm" no ano de hoje e
 *  "dd/mm/aaaa" em outro ano (#816: com prazo longo ela cai no ano que vem, e sem o ano se lia como data passada).
 *  Na medicao reapresentada (#914), a revisao embaixo: o primeiro protocolo (de onde os dias contam), quantas vezes
 *  foi reapresentada e o ultimo envio; a de protocolo unico nao ganha nada. Sem a data do evento, "—". `frase`: o
 *  tempo dito em frase ("há 4 dias úteis", "desde hoje"), para o cartao de medicao do Resumo das medicoes, que nao tem
 *  a coluna "Parada há" por cima; ali, sem a data do evento, nada aparece. */
export default function TempoParado({ parada, frase = false }: { parada: Parada; frase?: boolean }) {
  if (parada.dias_uteis === null) return frase ? null : <span className="tempo-parado tempo-parado--sem">—</span>;
  const dia = fmtDiaNoAno(parada.esperada);
  return (
    <span className="tempo-parado">
      <Selo situacao={parada.situacao ?? undefined}>{frase ? fraseDoTempo(parada) : textoDoTempo(parada)}</Selo>
      {dia && <span className="tempo-parado__prazo">{parada.alem_do_prazo ? `prazo do órgão venceu em ${dia}` : `prazo do órgão: ${dia}`}</span>}
      {parada.revisao && (
        <span className="tempo-parado__revisao">
          {partesDaRevisao(parada.revisao, d => fmtDiaNoAno(d)).map((p, i) => <span key={i}>{p}</span>)}
        </span>
      )}
    </span>
  );
}
