import { Fragment, useEffect, useState } from "react";
import { destinoDoAviso, semEmpresa, semObra, type Aviso } from "./Alertas";
import { api } from "./api";
import {
  FAMILIAS, daAgenda, diasAteOAviso, diasPorExtenso, familiaDaBusca, familiaDoAviso, filtrarAvisos, ondeEstao, porSecao,
  rotuloDaFamilia, semRSOrfao, vencidosPorObra, type GrupoVencido, type Secao,
} from "./avisos";
import Contador from "./Contador";
import Falha from "./Falha";
import LegendaCor, { type ItemLegenda } from "./LegendaCor";
import { Link } from "./Link";
import { ehDoContratante, nomeDaObra, type ObraLista } from "./listaObras";
import Rolagem from "./Rolagem";
import type { Busca } from "./rota";
import Selo, { Glifo } from "./Selo";
import type { Situacao } from "./situacao";
import "./avisosPagina.css";

// Avisos, com pagina propria (#805, proposta aprovada pelo dono em 18/11/2026). Antes abriam dentro de Obras: com o
// volume da producao eram dezenas de vencidos em lista corrida acima da primeira obra, sob o titulo "Obras".
// A pagina responde "o que vence quando, e onde ja' venceu":
//  - as contagens pelo prazo (Vencidos, Esta semana, Este mes, Proximos 90 dias): as secoes de `avisos.ts`, a mesma
//    regra da caixa "Avisos importantes" do Inicio;
//  - as abas por assunto, com a quantidade (?familia=);
//  - a Agenda: o que ainda vai vencer, em ordem de data, uma linha por aviso;
//  - os Vencidos por obra: agrupados pela obra (ou pela empresa), da maior idade para a menor; a linha abre os avisos
//    dela ali mesmo. Todo vencido aparece, sem limite de idade (#656).
// A fonte e' a fila consolidada do servidor (GET /api/inicio), com o recorte do perfil; so' entra o aviso com data
// (docs/adr/0008). Filtros na URL: ?familia=, ?obra= e ?c= (as obras de um contratante).

// A situacao vem da secao (o tempo), como no Inicio: vencido = critico; o que vence em ate' 30 dias = vence em breve;
// de 31 a 90 dias ainda nao pede nada: neutro, sem simbolo.
const SITUACAO_DA_SECAO: Partial<Record<Secao, Situacao>> = { vencido: "critico", semana: "breve", mes: "breve" };
const ROTULO_DA_SECAO: Record<Secao, string> = { vencido: "Vencidos", semana: "Esta semana", mes: "Este mês", depois: "Próximos 90 dias" };
const LEGENDA: ItemLegenda[] = [{ situacao: "critico", texto: "vencido" }, { situacao: "breve", texto: "vence em até 30 dias" }];

const contar = (n: number) => (n === 1 ? "1 aviso" : `${n.toLocaleString("pt-BR")} avisos`);
const chaveDe = (a: Aviso, i: number) => `${a.tipo}-${a.contrato_id}-${a.entidade_id ?? ""}-${a.medicao_id ?? ""}-${i}`;

/** Uma linha por aviso: os dias, a obra (ou a empresa), o que e' e o assunto. A linha inteira e' o link para onde o
 *  aviso se resolve. `semQuem`: dentro do grupo da obra, que ja' diz o nome. */
function LinhaAviso({ a, secao, semQuem = false }: { a: Aviso; secao: Secao; semQuem?: boolean }) {
  const destino = destinoDoAviso(a), dias = diasAteOAviso(a);
  const quem = semQuem ? "" : a.obra ?? a.entidade ?? "";
  // a obra (ou a empresa) tem linha propria: a mensagem perde o "Nome: " do comeco
  const texto = semRSOrfao((a.obra ? semObra(a) : semEmpresa(a)).mensagem);
  return (
    <li className="avs-linha">
      {dias !== null && <Selo situacao={SITUACAO_DA_SECAO[secao]} className="avs-dias">{diasPorExtenso(dias)}</Selo>}
      <span className="avs-linha__corpo">
        {quem && <span className="avs-linha__obra">{quem}</span>}
        <span className="avs-linha__fato">
          {destino ? <Link para={destino.para} busca={destino.busca} secao={destino.secao} className="avs-linha__link">{quem && <span className="sr-only">{quem}: </span>}{texto}</Link> : texto}
        </span>
      </span>
      <span className="avs-linha__assunto">{rotuloDaFamilia(familiaDoAviso(a))}</span>
    </li>
  );
}

/** O que ainda vai vencer, em ordem de data: esta semana (com o de hoje), este mes e ate' 90 dias. */
function Agenda({ secoes }: { secoes: { id: Secao; itens: Aviso[] }[] }) {
  const total = secoes.reduce((n, s) => n + s.itens.length, 0);
  return (
    <section className="cartao avs-bloco" aria-labelledby="avs-agenda">
      <header className="cartao__cabeca">
        <h2 className="cartao__titulo" id="avs-agenda">Agenda</h2>
        <Contador rotulo={contar(total)}>{total.toLocaleString("pt-BR")}</Contador>
      </header>
      {total === 0 && <div className="vazio vazio--curto"><p>Nada a vencer em 90 dias.</p></div>}
      {secoes.filter(s => s.itens.length > 0).map(s => (
        <section key={s.id} className="avs-quando" aria-labelledby={`avs-quando-${s.id}`}>
          <header className="avs-quando__topo">
            <h3 id={`avs-quando-${s.id}`}>{ROTULO_DA_SECAO[s.id]}</h3>
            <Contador situacao={SITUACAO_DA_SECAO[s.id]} rotulo={contar(s.itens.length)}>{s.itens.length.toLocaleString("pt-BR")}</Contador>
          </header>
          <ul className="avs-lista">
            {s.itens.map((a, i) => <LinhaAviso key={chaveDe(a, i)} a={a} secao={s.id} />)}
          </ul>
        </section>
      ))}
    </section>
  );
}

/** Os vencidos, uma linha por obra (ou empresa): o nome, os assuntos, quantos avisos e o mais antigo. Abrir a linha
 *  mostra os avisos dela. Com um grupo so' (a pagina filtrada por uma obra), ele ja' vem aberto. */
function Vencidos({ grupos }: { grupos: GrupoVencido[] }) {
  // os grupos que a pessoa abriu ou fechou: o contrario do padrao (fechado; aberto quando ha' um so')
  const [trocados, setTrocados] = useState<ReadonlySet<string>>(new Set());
  const total = grupos.reduce((n, g) => n + g.itens.length, 0);
  const trocar = (chave: string) => setTrocados(t => {
    const novo = new Set(t);
    if (!novo.delete(chave)) novo.add(chave);
    return novo;
  });
  return (
    <section className="cartao avs-bloco" aria-labelledby="avs-vencidos">
      <header className="cartao__cabeca">
        <h2 className="cartao__titulo" id="avs-vencidos">Vencidos por obra</h2>
        <Contador situacao={total > 0 ? "critico" : undefined} rotulo={contar(total)}>{total.toLocaleString("pt-BR")}</Contador>
      </header>
      {total === 0 ? <div className="vazio vazio--curto"><p>Nenhum vencido.</p></div> : (
        <Rolagem rotulo="Vencidos por obra">
          <table className="tabela avs-vencidos">
            <caption className="sr-only">Vencidos por obra, do mais antigo ao mais novo</caption>
            <thead>
              <tr>
                <th scope="col">{grupos.some(g => g.entidadeId !== null) ? "Obra ou empresa" : "Obra"}</th>
                <th scope="col" className="col-num">Avisos</th>
                <th scope="col">Mais antigo</th>
              </tr>
            </thead>
            <tbody>
              {grupos.map(g => {
                const aberto = trocados.has(g.chave) !== (grupos.length === 1), itens = `avs-itens-${g.chave}`;
                return (
                  <Fragment key={g.chave}>
                    <tr className="linha avs-vencido" onClick={ev => { if (!(ev.target as HTMLElement).closest("button")) trocar(g.chave); }}>
                      <th scope="row">
                        <button type="button" className="avs-abre" aria-expanded={aberto} aria-controls={itens} onClick={() => trocar(g.chave)}>
                          <span className="avs-abre__seta" aria-hidden="true" />{g.nome}
                        </button>
                        <span className="avs-vencido__assuntos">{g.familias.map(rotuloDaFamilia).join(" · ")}</span>
                      </th>
                      <td className="col-num num avs-vencido__n" data-unidade={g.itens.length === 1 ? "aviso" : "avisos"}>{g.itens.length.toLocaleString("pt-BR")}</td>
                      <td className="avs-vencido__antigo"><Selo situacao="critico" className="avs-dias">{diasPorExtenso(-g.maisAntigo)}</Selo></td>
                    </tr>
                    {aberto && (
                      <tr className="avs-vencido__itens" id={itens}>
                        <td colSpan={3}>
                          <ul className="avs-lista" aria-label={`Avisos vencidos de ${g.nome}`}>
                            {g.itens.map((a, i) => <LinhaAviso key={chaveDe(a, i)} a={a} secao="vencido" semQuem />)}
                          </ul>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </Rolagem>
      )}
    </section>
  );
}

export default function AvisosPagina({ busca }: { busca: Busca }) {
  // `undefined` carregando, `null` falhou: lista vazia quer dizer "verificamos e nao ha' aviso"
  const [avisos, setAvisos] = useState<Aviso[] | null | undefined>(undefined);
  const [obras, setObras] = useState<ObraLista[] | null | undefined>(undefined);

  const familia = familiaDaBusca(busca.familia);
  const obra = /^[1-9][0-9]{0,14}$/.test(busca.obra ?? "") ? Number(busca.obra) : null;
  const contratante = busca.c && busca.c !== "todas" ? busca.c : null;
  // a lista de obras so' e' lida com recorte: da' o nome da obra filtrada e diz quais obras sao do contratante
  const comRecorte = obra !== null || contratante !== null;

  useEffect(() => {
    let vivo = true;
    api<{ avisos: Aviso[] }>("/api/inicio").then(d => { if (vivo) setAvisos(d.avisos); })
      .catch(() => { if (vivo) setAvisos(null); });
    return () => { vivo = false; };
  }, []);
  useEffect(() => {
    if (!comRecorte) return;
    let vivo = true;
    api<ObraLista[]>("/api/contratos").then(l => { if (vivo) setObras(l); })
      .catch(() => { if (vivo) setObras(null); });
    return () => { vivo = false; };
  }, [comRecorte]);

  // sem a lista de obras nao da' para saber quais sao do contratante: a pagina espera por ela (ou diz que falhou)
  const carregando = avisos === undefined || (contratante !== null && obras === undefined);
  const falhou = avisos === null || (contratante !== null && obras === null);
  const doContratante = contratante !== null && obras ? new Set(obras.filter(o => ehDoContratante(o, contratante)).map(o => o.id)) : null;

  // so' a agenda (aviso com data, do vencido ate' 90 dias), no recorte da pagina: as contagens do alto sao dela
  const daPagina = daAgenda(avisos ?? [])
    .filter(a => doContratante === null || (a.contrato_id !== null && doContratante.has(a.contrato_id)))
    .filter(a => obra === null || a.contrato_id === obra);
  const filtrados = filtrarAvisos(daPagina, { familia });
  const secoes = porSecao(filtrados);
  const onde = ondeEstao(vencidosPorObra(daPagina));

  const obraDaLista = obra !== null ? obras?.find(o => o.id === obra) : undefined;
  const nomeDoRecorte = obra !== null
    ? (obraDaLista ? nomeDaObra(obraDaLista) : (avisos ?? []).find(a => a.contrato_id === obra)?.obra ?? "Obra filtrada")
    : contratante;
  const aqui = { tela: "avisos" as const };
  const com = (m: Record<string, string | null>): Busca => {
    const b: Busca = { ...busca };
    for (const [k, v] of Object.entries(m)) { if (v === null) delete b[k]; else b[k] = v; }
    return b;
  };

  return (
    <div className="avs">
      {nomeDoRecorte !== null && (
        <header className="avs-recorte">
          <h2><span className="sr-only">Avisos ·</span> {nomeDoRecorte}</h2>
          <Link para={aqui} busca={com({ obra: null, c: null })}>Todos os avisos</Link>
        </header>
      )}

      {carregando && !falhou && <p className="avs-vazio" role="status">Carregando os avisos…</p>}
      {falhou && <Falha>Não foi possível verificar os avisos. Recarregue a página para tentar de novo.</Falha>}

      {!carregando && !falhou && <>
        <dl className="avs-numeros" aria-label="Avisos pelo prazo">
          {porSecao(daPagina).map(s => {
            const n = s.itens.length, situacao = n > 0 ? SITUACAO_DA_SECAO[s.id] : undefined;
            return (
              <div key={s.id} className="avs-numero">
                <dt>{situacao && <Glifo situacao={situacao} />}{ROTULO_DA_SECAO[s.id]}</dt>
                <dd className="avs-numero__valor">{n.toLocaleString("pt-BR")}</dd>
                {s.id === "vencido" && onde && <dd className="avs-numero__apoio">{onde}</dd>}
              </div>
            );
          })}
        </dl>

        <div className="avs-barra">
          <nav className="escolhas avs-abas" aria-label="Assunto dos avisos">
            <Link className="escolha" para={aqui} busca={com({ familia: null })} aria-current={familia === null ? "true" : undefined}>
              Tudo <span className="escolha__n num">{daPagina.length.toLocaleString("pt-BR")}</span>
            </Link>
            {FAMILIAS.map(f => {
              const n = filtrarAvisos(daPagina, { familia: f.id }).length;
              // o assunto sem aviso nao vira aba; o que esta' na URL aparece mesmo vazio, para dizer o filtro em vigor
              return n === 0 && familia !== f.id ? null : (
                <Link key={f.id} className="escolha" para={aqui} busca={com({ familia: f.id })} aria-current={familia === f.id ? "true" : undefined}>
                  {f.rotulo} <span className="escolha__n num">{n.toLocaleString("pt-BR")}</span>
                </Link>
              );
            })}
          </nav>
          <LegendaCor itens={LEGENDA} />
        </div>

        {filtrados.length === 0 ? (
          <p className="avs-vazio">
            <span>{familia !== null || comRecorte ? "Nenhum aviso com esse filtro." : "Nenhum aviso."}</span>
            {(familia !== null || comRecorte) && <> <Link para={aqui}>Limpar o filtro</Link></>}
          </p>
        ) : (
          <div className="avs-blocos">
            <Agenda secoes={secoes.slice(1)} />
            {/* a chave refaz o bloco quando o recorte muda: o que estava aberto era de outra lista */}
            <Vencidos key={`${familia}-${obra}-${contratante}`} grupos={vencidosPorObra(filtrados)} />
          </div>
        )}
      </>}
    </div>
  );
}
