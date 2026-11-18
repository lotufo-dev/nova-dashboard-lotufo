import Selo from "./Selo";
import { nivelDias } from "./siga";
import { situacaoDoNivel } from "./situacao";

// TempoNaEtapa (#805, familia "tempo parado"): ha' quantos dias uteis a medicao esta' na etapa, com o selo da
// situacao. Os limites sao os do SIGA (`nivelDias`, siga.ts): 5 dias uteis ou mais, vence em breve; 10 ou mais,
// critico; menos de 5, em andamento; chegou hoje, feito. A data e os dias vem do servidor, que conta do evento da
// etapa (envio, boletim, emissao, protocolo), nunca da competencia: sem a data, nada aparece.

/** `desde` e' a data do evento (AAAA-MM-DD), `diasUteis` os dias uteis dela ate' `hoje` (a data do servidor). */
export default function TempoNaEtapa({ desde, diasUteis, hoje }: { desde: string | null; diasUteis: number | null; hoje: string }) {
  if (desde === null || diasUteis === null) return null;
  if (desde === hoje) return <Selo situacao="feito">desde hoje</Selo>;
  const situacao = situacaoDoNivel(nivelDias(diasUteis)) ?? "andamento";
  // o evento caiu no fim de semana ou no feriado e ainda nao passou um dia util
  if (diasUteis <= 0) return <Selo situacao={situacao}>há menos de 1 dia útil</Selo>;
  return <Selo situacao={situacao}>há {diasUteis.toLocaleString("pt-BR")} {diasUteis === 1 ? "dia útil" : "dias úteis"}</Selo>;
}
