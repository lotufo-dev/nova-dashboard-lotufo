import { datasDaRevisao, fraseDoTempo, seloDaRevisao, textoDoTempo, type Parada, type Revisao } from "./parada";
import Selo from "./Selo";
import { fmtDiaNoAno } from "./tempo";
import "./barraDePassos.css";

// TempoParado (#805, familia de valor "tempo parado" de docs/identidade-visual.md): ha' quantos dias uteis a medicao
// esta' na situacao atual, no selo da situacao que o SERVIDOR leu (os limites do SIGA; no Pagamento, o prazo do orgao
// de docs/adr/0007). Aqui nao ha' conta nem limite: so' o desenho (o tipo e o texto estao em parada.ts).

/** O selo do tempo parado e, no Pagamento com prazo do orgao, a data esperada embaixo: "dd/mm" no ano de hoje e
 *  "dd/mm/aaaa" em outro ano (#816: com prazo longo ela cai no ano que vem, e sem o ano se lia como data passada).
 *  Na medicao reapresentada (#914, desenho escolhido pelo dono em 26/11/2026), o selo "Rev. N" ao lado do dos dias e,
 *  abaixo do prazo, as duas datas numa linha: o primeiro protocolo (de onde os dias contam) e o ultimo envio; a de
 *  protocolo unico nao ganha nada. Sem a data do evento, "—". `frase`: o
 *  tempo dito em frase ("há 4 dias úteis", "desde hoje"), para o cartao de medicao do Resumo das medicoes, que nao tem
 *  a coluna "Parada há" por cima; ali, sem a data do evento, nada aparece. `comPrimeiro={false}`: a revisao sem o
 *  "1º protocolo", onde a linha ja' tem a coluna da data do protocolo (a pagina Em aberto). */
export default function TempoParado({ parada, frase = false, comPrimeiro = true }: { parada: Parada; frase?: boolean; comPrimeiro?: boolean }) {
  if (parada.dias_uteis === null) return frase ? null : <span className="tempo-parado tempo-parado--sem">—</span>;
  const dia = fmtDiaNoAno(parada.esperada);
  return (
    <span className="tempo-parado">
      <span className="tempo-parado__selos">
        <Selo situacao={parada.situacao ?? undefined}>{frase ? fraseDoTempo(parada) : textoDoTempo(parada)}</Selo>
        {parada.revisao && <SeloRevisao revisao={parada.revisao} />}
      </span>
      {dia && <span className="tempo-parado__prazo">{parada.alem_do_prazo ? `prazo do órgão venceu em ${dia}` : `prazo do órgão: ${dia}`}</span>}
      {parada.revisao && <span className="tempo-parado__revisao">{datasDaRevisao(parada.revisao, d => fmtDiaNoAno(d), comPrimeiro)}</span>}
    </span>
  );
}

/** O selo da revisao (#914): informacao, nao situacao, entao neutro, sem cor nem glifo. Na tela, "Rev. 1"; para o
 *  leitor de tela, por extenso ("revisão 1, reapresentada uma vez"). */
export function SeloRevisao({ revisao }: { revisao: Revisao }) {
  const { curto, extenso } = seloDaRevisao(revisao);
  return <Selo className="selo--revisao"><span aria-hidden="true">{curto}</span><span className="sr-only">{extenso}</span></Selo>;
}
