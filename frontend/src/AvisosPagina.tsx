import { useState } from "react";
import { destinoDoAviso, semEmpresa, semObra, type Aviso } from "./Alertas";
import { FAMILIAS, familiaDaBusca, filtrarAvisos, porSecao, diasAteOAviso, semRSOrfao, type Secao } from "./avisos";
import { IconeAlerta } from "./icones";
import LegendaCor from "./LegendaCor";
import { trocarBusca, type Busca } from "./rota";
import { Link } from "./Link";

// Avisos (redesenho #511, aprovado em 06/11/2026): "o que vence quando". Quatro secoes exclusivas pelo tempo
// (Vencido · Esta semana · Este mes · Depois) e, no fim, "Sem data". Uma linha por aviso: a data do fato, a obra (ou
// a empresa), o que e' e os dias. A fonte e' a fila consolidada do servidor, com o recorte do perfil. Filtros na URL:
// ?familia= (reajustes, prazos, certidoes ou o id da familia) e ?obra=.

/** Quantos vencidos aparecem antes do "… e mais N". */
const VENCIDOS_VISIVEIS = 6;

const dataBR = (iso: string | null | undefined) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  return m ? `${m[3]}/${m[2]}/${m[1]}` : "—";
};

/** Os dias do aviso: "há N dias" no vencido, "N dias" nos demais; sem dias, nada. */
function Dias({ a, secao }: { a: Aviso; secao: Secao }) {
  const d = diasAteOAviso(a);
  if (d === null) return null;
  const n = Math.abs(d), txt = `${n} ${n === 1 ? "dia" : "dias"}`;
  return <span className={`aviso-linha__dias aviso-linha__dias--${secao}`}>{secao === "vencido" ? `há ${txt}` : txt}</span>;
}

function LinhaAviso({ a, secao }: { a: Aviso; secao: Secao }) {
  const d = destinoDoAviso(a);
  // a obra (ou a empresa) tem coluna propria: a mensagem perde o "Nome: " do comeco
  const quem = a.obra ?? a.entidade ?? "";
  const texto = semRSOrfao((a.obra ? semObra(a) : semEmpresa(a)).mensagem);
  return (
    <li className="aviso-linha">
      <strong className="aviso-linha__data num">{dataBR(a.data)}</strong>
      <span className="aviso-linha__obra">{quem}</span>
      <span className="aviso-linha__fato">
        {d ? <Link para={d.para} busca={d.busca} secao={d.secao} className="aviso-linha__link">{quem && <span className="sr-only">{quem}: </span>}{texto}</Link> : texto}
      </span>
      <Dias a={a} secao={secao} />
    </li>
  );
}

function SecaoAvisos({ id, rotulo, itens }: { id: Secao; rotulo: string; itens: Aviso[] }) {
  const [tudo, setTudo] = useState(false);
  const corta = id === "vencido" && !tudo && itens.length > VENCIDOS_VISIVEIS;
  const visiveis = corta ? itens.slice(0, VENCIDOS_VISIVEIS) : itens;
  const titulo = `secao-avisos-${id}`;
  return (
    <section className="aviso-secao" aria-labelledby={titulo}>
      <h3 className={`aviso-secao__cabeca aviso-secao__cabeca--${id}`} id={titulo}>
        {rotulo.toUpperCase()}<span aria-hidden="true"> · </span><span className="aviso-secao__n">{itens.length}</span>
      </h3>
      {visiveis.length > 0 && (
        <ul className="aviso-secao__lista">
          {visiveis.map((a, i) => <LinhaAviso key={`${a.tipo}-${a.contrato_id}-${a.entidade_id ?? ""}-${a.medicao_id ?? ""}-${i}`} a={a} secao={id} />)}
        </ul>
      )}
      {corta && (
        <button type="button" className="aviso-secao__mais" onClick={() => setTudo(true)}>… e mais {itens.length - VENCIDOS_VISIVEIS}</button>
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
  const lista = (avisos ?? []).filter(a => escopo === null || (a.contrato_id !== null && escopo.has(a.contrato_id)));
  const filtrados = filtrarAvisos(lista, { familia, obra });
  const secoes = porSecao(filtrados).filter(s => s.id !== "sem-data" || s.itens.length > 0);
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
    <section className="cartao avisos-area" id="avisos-area" aria-labelledby="titulo-avisos">
      <div className="cartao__cabeca">
        <div className="avisos-area__titulos">
          <h2 className="cartao__titulo" id="titulo-avisos">Avisos · {nome}</h2>
          <span className="avisos-area__sub">o que vence quando</span>
        </div>
        <div className="cartao__acoes">
          <LegendaCor />
          <button type="button" className="btn btn--pequeno" onClick={onFechar}>Fechar os avisos</button>
        </div>
      </div>
      <div className="cartao__corpo avisos-area__corpo">
        <div className="filtros-avisos__linhas" role="group" aria-label="Filtros dos avisos">
          <p className="filtros-avisos__linha">
            <span className="campo__rotulo">Tipo</span>
            <Link para={aqui} busca={com({ familia: null })} aria-current={familia === null ? "true" : undefined}>Todas</Link>
            {FAMILIAS.map(f => {
              const n = filtrarAvisos(lista, { familia: f.id, obra }).length;
              return n === 0 && familia !== f.id ? null : (
                <Link key={f.id} para={aqui} busca={com({ familia: f.id })} aria-current={familia === f.id ? "true" : undefined}>{f.rotulo}</Link>
              );
            })}
          </p>
          <div className="form-inline">
            <div className="campo">
              <label className="campo__rotulo" htmlFor="avisos-obra">Obra</label>
              <select id="avisos-obra" value={obra ?? ""} onChange={e => trocarBusca({ obra: e.target.value || null })}>
                <option value="">Todas</option>
                {obraSemAviso && <option value={obra!}>a obra filtrada, sem avisos</option>}
                {obras.map(([id, nomeDela]) => <option key={id} value={id}>{nomeDela}</option>)}
              </select>
            </div>
          </div>
        </div>

        {avisos === undefined && <div className="vazio vazio--curto"><p>Carregando os avisos…</p></div>}
        {avisos === null && (
          <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />
            Não foi possível verificar os avisos. Recarregue a página para tentar de novo.</p>
        )}
        {avisos && filtrados.length === 0 && (
          <div className="vazio vazio--curto">
            <p className="vazio__titulo">{temFiltro ? "Nenhum aviso com esses filtros." : "Nenhum aviso."}</p>
            {temFiltro && <p><Link para={aqui} busca={com({ familia: null, obra: null })}>Limpar os filtros</Link></p>}
          </div>
        )}
        {avisos && filtrados.length > 0 && (
          <div className="avisos-area__grupos">
            {secoes.map(s => <SecaoAvisos key={`${s.id}-${familia}-${obra}`}id={s.id} rotulo={s.rotulo} itens={s.itens} />)}
          </div>
        )}
      </div>
    </section>
  );
}
