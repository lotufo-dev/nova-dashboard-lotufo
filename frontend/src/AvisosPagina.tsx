import { destinoDoAviso, semEmpresa, semObra, type Aviso } from "./Alertas";
import { FAMILIAS, familiaDaBusca, daAgenda, filtrarAvisos, porSecao, diasAteOAviso, semRSOrfao, type Secao } from "./avisos";
import Contador from "./Contador";
import LegendaCor, { type ItemLegenda } from "./LegendaCor";
import { trocarBusca, type Busca } from "./rota";
import { Link } from "./Link";
import Selo from "./Selo";
import type { Situacao } from "./situacao";
import "./avisosPagina.css";
import Falha from "./Falha";

// Avisos (redesenho #511, aprovado em 06/11/2026): "o que vence quando". Quatro secoes exclusivas pelo tempo
// (Vencido · Esta semana · Este mes · Depois). Agenda (#656): so' o aviso com data, do que ja' venceu (todos, sem
// limite de idade) ate' 90 dias a frente; o aviso sem data e' do admin (Administracao > Pendencias de cadastro). Uma
// linha por aviso: a data do fato, a obra (ou a empresa), o que e' e os dias. A fonte e' a fila consolidada do
// servidor, com o recorte do perfil. Filtros na URL: ?familia= (reajustes, prazos, certidoes ou o id da familia) e ?obra=.

const dataBR = (iso: string | null | undefined) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  return m ? `${m[3]}/${m[2]}/${m[1]}` : "—";
};

// A situacao vem da secao (o tempo), como na caixa de avisos do Inicio: vencido = critico; o que vence na semana ou no
// mes = vence em breve. "Depois" (31 a 90 dias) ainda nao pede nada: selo e contador neutros, sem simbolo.
const SITUACAO_DA_SECAO: Partial<Record<Secao, Situacao>> = { vencido: "critico", semana: "breve", mes: "breve" };
const LEGENDA: ItemLegenda[] = [{ situacao: "critico", texto: "vencido" }, { situacao: "breve", texto: "vence em até 30 dias" }];

/** Os dias do aviso: "há N dias" no vencido, "N dias" nos demais; sem dias, nada. */
function Dias({ a, secao }: { a: Aviso; secao: Secao }) {
  const d = diasAteOAviso(a);
  if (d === null) return null;
  const n = Math.abs(d), txt = `${n}\u00a0${n === 1 ? "dia" : "dias"}`;
  return <Selo situacao={SITUACAO_DA_SECAO[secao]} className="avs-linha__dias">{secao === "vencido" ? `há ${txt}` : txt}</Selo>;
}

function LinhaAviso({ a, secao }: { a: Aviso; secao: Secao }) {
  const d = destinoDoAviso(a);
  // a obra (ou a empresa) tem coluna propria: a mensagem perde o "Nome: " do comeco
  const quem = a.obra ?? a.entidade ?? "";
  const texto = semRSOrfao((a.obra ? semObra(a) : semEmpresa(a)).mensagem);
  return (
    <li className="avs-linha">
      <span className="avs-linha__data num">{dataBR(a.data)}</span>
      <span className="avs-linha__obra">{quem}</span>
      <span className="avs-linha__fato">
        {d ? <Link para={d.para} busca={d.busca} secao={d.secao} className="avs-linha__link">{quem && <span className="sr-only">{quem}: </span>}{texto}</Link> : texto}
      </span>
      <Dias a={a} secao={secao} />
    </li>
  );
}

function SecaoAvisos({ id, rotulo, itens }: { id: Secao; rotulo: string; itens: Aviso[] }) {
  const titulo = `secao-avisos-${id}`;
  return (
    <section className="avs-secao" aria-labelledby={titulo}>
      <header className="avs-secao__topo">
        <h3 id={titulo}>{rotulo}</h3>
        {/* secao sem aviso: contador neutro, sem o simbolo da situacao */}
        <Contador situacao={itens.length > 0 ? SITUACAO_DA_SECAO[id] : undefined} rotulo={itens.length === 1 ? "1 aviso" : `${itens.length} avisos`}>
          {itens.length.toLocaleString("pt-BR")}
        </Contador>
      </header>
      {itens.length > 0 && (
        <ul className="avs-secao__lista">
          {itens.map((a, i) => <LinhaAviso key={`${a.tipo}-${a.contrato_id}-${a.entidade_id ?? ""}-${a.medicao_id ?? ""}-${i}`} a={a} secao={id} />)}
        </ul>
      )}
    </section>
  );
}

/** A tela de Avisos (dentro de Obras, decisao de 09/10/2026): `escopo` sao os ids das obras do contratante
 *  (`null` = todas, com os avisos sem obra). `avisos`: `undefined` carregando, `null` falhou. */
export default function AvisosPagina({ busca, avisos, escopo = null, nome, onFechar }: {
  busca: Busca; avisos: Aviso[] | null | undefined; escopo?: ReadonlySet<number> | null; nome: string;
  onFechar: () => void;
}) {
  const familia = familiaDaBusca(busca.familia);
  const obra = /^[1-9][0-9]*$/.test(busca.obra ?? "") ? Number(busca.obra) : null;
  // so' a agenda: o filtro por tipo e por obra tambem so' oferece o que ela tem
  const lista = daAgenda(avisos ?? []).filter(a => escopo === null || (a.contrato_id !== null && escopo.has(a.contrato_id)));
  const filtrados = filtrarAvisos(lista, { familia, obra });
  const secoes = porSecao(filtrados);
  const obras = [...new Map(lista.filter(a => a.contrato_id !== null).map(a => [a.contrato_id!, a.obra ?? `Obra ${a.contrato_id}`])).entries()]
    .sort((x, y) => x[1].localeCompare(y[1], "pt-BR"));
  // a obra da URL pode nao ter mais aviso (resolvido, ou link guardado): o select mostra o filtro em vigor
  const obraSemAviso = obra !== null && !obras.some(o => o[0] === obra);
  const temFiltro = familia !== null || obra !== null;
  const aqui = { tela: "obras" as const };
  const com = (m: Record<string, string | null>): Busca => {
    const b: Busca = { ...busca };
    for (const [k, v] of Object.entries(m)) { if (v === null) delete b[k]; else b[k] = v; }
    return b;
  };

  return (
    <section className="cartao avs" id="avisos-area" aria-labelledby="titulo-avisos">
      <div className="avs__cab">
        <h2 id="titulo-avisos">Avisos · {nome}</h2>
        {avisos && <Contador rotulo={filtrados.length === 1 ? "1 aviso" : `${filtrados.length} avisos`}>{filtrados.length.toLocaleString("pt-BR")}</Contador>}
        <div className="avs__acoes">
          <LegendaCor itens={LEGENDA} />
          <button type="button" className="btn btn--pequeno" onClick={onFechar}>Fechar os avisos</button>
        </div>
      </div>
      <div className="avs__filtros" role="group" aria-label="Filtros dos avisos">
        <div className="avs__tipo">
          <span className="campo__rotulo" id="avisos-tipo">Tipo</span>
          <p className="escolhas avs__opcoes" aria-labelledby="avisos-tipo">
            <Link className="escolha" para={aqui} busca={com({ familia: null })} aria-current={familia === null ? "true" : undefined}>Todas</Link>
            {FAMILIAS.map(f => {
              const n = filtrarAvisos(lista, { familia: f.id, obra }).length;
              return n === 0 && familia !== f.id ? null : (
                <Link key={f.id} className="escolha" para={aqui} busca={com({ familia: f.id })} aria-current={familia === f.id ? "true" : undefined}>{f.rotulo}</Link>
              );
            })}
          </p>
        </div>
        <div className="campo avs__obra">
          <label className="campo__rotulo" htmlFor="avisos-obra">Obra</label>
          <select id="avisos-obra" value={obra ?? ""} onChange={e => trocarBusca({ obra: e.target.value || null })}>
            <option value="">Todas</option>
            {obraSemAviso && <option value={obra!}>a obra filtrada, sem avisos</option>}
            {obras.map(([id, nomeDela]) => <option key={id} value={id}>{nomeDela}</option>)}
          </select>
        </div>
      </div>

      {avisos === undefined && <p className="avs__vazio" role="status">Carregando os avisos…</p>}
      {avisos === null && (
        <Falha className="avs__erro">Não foi possível verificar os avisos. Recarregue a página para tentar de novo.</Falha>
      )}
      {avisos && filtrados.length === 0 && (
        <p className="avs__vazio">
          <span>{temFiltro ? "Nenhum aviso com esses filtros." : "Nenhum aviso."}</span>
          {temFiltro && <> <Link para={aqui} busca={com({ familia: null, obra: null })}>Limpar os filtros</Link></>}
        </p>
      )}
      {avisos && filtrados.length > 0 && (
        <div className="avs__secoes">
          {secoes.map(s => <SecaoAvisos key={`${s.id}-${familia}-${obra}`} id={s.id} rotulo={s.rotulo} itens={s.itens} />)}
        </div>
      )}
    </section>
  );
}
