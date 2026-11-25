import { emDiasUteis, useLicitacoes, type DiaDoCalendario, type PrazoNoCalendario, type RespostaCalendario } from "./licitacoes";
import { AbasDasFavoritas, FalhaAoAtualizar, LeituraDoRadarLinha, Licitacao, SemLeitura } from "./LicitacoesPecas";
import { Link } from "./Link";
import { mesDaBusca, type Busca, type Rota } from "./rota";
import Selo from "./Selo";
import { fmtDiaNoAno, fmtMesExtenso } from "./tempo";

// CALENDARIO DAS FAVORITAS (fatia 2 da #906): "/licitacoes/favoritas/calendario", com o mes na busca (?mes=2026-12; sem
// ele, o mes de hoje). Cada prazo das favoritas no dia dele, com o nome do prazo e a licitacao. Os prazos sao os da
// lista, com a mesma situacao.
//
// Tudo vem pronto de GET /api/licitacoes/calendario: as semanas, de domingo a sabado, com os dias de fora do mes
// marcados; qual dia e' hoje; o mes anterior e o proximo; quantos prazos ha' no mes; e se o mes e' o de hoje. A tela nao
// faz conta com data: so' escreve o nome do mes e o dia.
//
// E' uma tabela (um dia por celula). Na pagina estreita vira a lista dos dias que tem prazo, cada um com o dia da semana
// e a data escritos; os dias sem prazo e os de fora do mes somem.

const AQUI: Rota = { tela: "licitacoes-favoritas", vista: "calendario" };
// as colunas, na ordem em que o servidor manda os dias de cada semana
const DIAS_DA_SEMANA = [["dom", "domingo"], ["seg", "segunda-feira"], ["ter", "terça-feira"], ["qua", "quarta-feira"],
  ["qui", "quinta-feira"], ["sex", "sexta-feira"], ["sáb", "sábado"]] as const;

/** Um prazo no dia: o nome com a hora, os dias uteis no selo da situacao (so' no prazo que corre e tem situacao) e a
 *  licitacao, com o link do edital. */
function PrazoDoDia({ p }: { p: PrazoNoCalendario }) {
  const dias = p.situacao && !p.passado && !p.licitacao.encerrada ? emDiasUteis(p.dias_uteis, p.hoje) : null;
  return (
    <li className="lic-dia__prazo">
      <span className="lic-prazo__rotulo">{p.rotulo}{p.hora && <span className="num"> {p.hora}</span>}</span>
      {p.situacao && dias && <Selo situacao={p.situacao} className="lic-dias">{dias}</Selo>}
      <span className="lic-dia__licitacao"><Licitacao l={{ ...p.licitacao, objeto: "" }} /></span>
    </li>
  );
}

function Dia({ d, coluna }: { d: DiaDoCalendario; coluna: number }) {
  const classe = `lic-dia${d.do_mes ? "" : " lic-dia--fora"}${d.hoje ? " lic-dia--hoje" : ""}${d.prazos.length === 0 ? " lic-dia--vazio" : ""}`;
  return (
    <td className={classe} data-dia={d.data} aria-current={d.hoje ? "date" : undefined}>
      <span className="lic-dia__data">
        {/* na grade, so' o numero do dia; na lista (pagina estreita), o dia da semana e a data */}
        <span className="num lic-dia__numero">{Number(d.data.slice(8))}</span>
        <span className="lic-dia__extenso">{DIAS_DA_SEMANA[coluna][0]} <span className="num">{fmtDiaNoAno(d.data) ?? d.data}</span></span>
        {d.hoje && <span className="lic-dia__hoje"> hoje</span>}
      </span>
      {d.prazos.length > 0 && (
        <ul className="lic-dia__prazos">
          {d.prazos.map(p => <PrazoDoDia key={`${p.licitacao.chave}-${p.codigo}`} p={p} />)}
        </ul>
      )}
    </td>
  );
}

export default function LicitacoesCalendario({ busca }: { busca: Busca }) {
  const mes = mesDaBusca(busca);
  const { dados, erro, tentar } = useLicitacoes<RespostaCalendario>(`/api/licitacoes/calendario${mes ? `?mes=${mes}` : ""}`);
  if (!dados) return <SemLeitura erro={erro} tentar={() => void tentar()}><AbasDasFavoritas atual="calendario" /></SemLeitura>;

  const titulo = `${fmtMesExtenso(dados.mes)} de ${dados.mes.slice(0, 4)}`;
  return (
    <div className="pagina lic">
      <AbasDasFavoritas atual="calendario" />
      <LeituraDoRadarLinha leitura={dados.leitura} />
      <FalhaAoAtualizar erro={erro} tentar={() => void tentar()} />
      {/* o nome da pagina ja' esta' no alto: o titulo do painel e' o mes */}
      <section className="cartao lic-bloco lic-cal" aria-label="Calendário dos prazos das favoritas">
        <header className="lic-cal__cabeca">
          <h2 className="lic-cal__mes" aria-live="polite">{titulo}</h2>
          <nav className="lic-cal__troca" aria-label="Trocar o mês">
            <Link className="btn btn--pequeno" para={AQUI} busca={{ mes: dados.anterior }}>Mês anterior</Link>
            {!dados.mes_atual && <Link className="btn btn--pequeno" para={AQUI}>Mês atual</Link>}
            <Link className="btn btn--pequeno" para={AQUI} busca={{ mes: dados.proximo }}>Próximo mês</Link>
          </nav>
        </header>
        {dados.prazos === 0 ? <div className="vazio vazio--curto"><p>Nenhum prazo em {titulo}.</p></div> : (
          <table className="lic-cal__grade">
            <caption className="sr-only">Prazos das favoritas em {titulo}, um dia por célula</caption>
            <thead>
              <tr>{DIAS_DA_SEMANA.map(([curto, extenso]) => <th key={curto} scope="col"><abbr title={extenso}>{curto}</abbr></th>)}</tr>
            </thead>
            <tbody>
              {dados.semanas.map(semana => (
                <tr key={semana[0].data}>{semana.map((d, i) => <Dia key={d.data} d={d} coluna={i} />)}</tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
