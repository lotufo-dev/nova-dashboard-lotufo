import { brl } from "./formato";
import { fmtDataPura } from "./tempo";

/** O a receber que fica FORA do total das telas da diretoria (decisao do dono de 17/11/2026, docs/adr/0006): a
 *  pendencia de competencia anterior ao ano inicial e a nota que o RM deixou de informar (saiu da janela de 24 meses da
 *  sincronizacao). Uma linha por parte, menor que os numeros da tela, e so' a que tem valor: sem nenhuma, nada aparece.
 *  Os valores e o ano vem do servidor (`inicio._a_receber` e `posicao` da lista de Obras); aqui so' se desenha.
 *  O rotulo do anterior e' o mesmo do Fechamento ("Em aberto de competências anteriores a ..."). */
export default function EmAbertoAParte({ anoInicial, anterior, semAtualizacao, desde }: {
  anoInicial: string; anterior: number | null; semAtualizacao: number | null; desde?: string | null;
}) {
  const temAnterior = (anterior ?? 0) > 0, temSem = (semAtualizacao ?? 0) > 0;
  if (!temAnterior && !temSem) return null;
  return (
    <dl className="em-aberto-a-parte" aria-label="Em aberto fora do total">
      {temAnterior && (
        <div className="em-aberto-a-parte__linha">
          <dt>Em aberto de competências anteriores a {anoInicial}</dt>
          <dd className="num">{brl(anterior)}</dd>
        </div>
      )}
      {temSem && (
        <div className="em-aberto-a-parte__linha">
          <dt>Sem atualização do RM{desde ? ` desde ${fmtDataPura(desde)}` : ""}</dt>
          <dd className="num">{brl(semAtualizacao)}</dd>
        </div>
      )}
    </dl>
  );
}
