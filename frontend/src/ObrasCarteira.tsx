import { useEffect, useState } from "react";
import { type Aviso } from "./Alertas";
import { api } from "./api";
import { motivosDaLinha, porFarol, type Motivo } from "./carteira";
import { fmtDias, fmtPercentual } from "./formato";
import { IconeBaixar } from "./icones";
import { filtrarObras, type ObraLista } from "./listaObras";
import { brl } from "./Medicoes";
import { type Ir } from "./rota";
import { Link } from "./Link";
import { fmtDataPura } from "./tempo";
import Rolagem from "./Rolagem";
import Selo from "./Selo";
import { situacaoDoNivel } from "./situacao";
import Falha from "./Falha";

// As pecas da lista de Obras que vieram da Carteira (#748; bloco 8, spec §10.5): os reajustes esperando apostilamento
// e o QDOP. Tudo na COTA da Lotufo, com as regras em `app/diretoria.py` (`/api/diretoria`); quem pede o painel e' a
// lista (`Contratos.tsx`), uma vez para as duas vistas. A curva do previsto e do medido saiu na #802.

type Obra = {
  contrato_id: number; seq: number; obra: string; contratante: string; empreita: string; direito: number;
  pi_va: number; faturados: number; saldo: number; status: string; termino: string | null;
  vigencia?: string | null; farol: "verde" | "atencao" | "acao" | "vermelho"; motivo: string; motivos?: Motivo[];
};
/** #279: por obra, as competências de reajuste já medidas sem apostilamento e o medido delas, na cota. */
type ReajusteObra = { contrato_id: number; obra: string; competencias: number; valor_centavos: number };
export type Painel = {
  hoje: string; medido_ano: { ano: string; valor_centavos: number }; obras: Obra[]; avisos: Aviso[];
  reajustes_apostilamento?: { competencias: number; valor_centavos: number; obras: ReajusteObra[] };
};

// O selo diz a palavra do nivel (D12, D10), a mesma do selo dos avisos, com a forma pelo mesmo criterio (o mapa
// unico de `situacao.ts`): Critico e Acao pedem acao agora e levam o octogono; Atencao leva o triangulo de "vence em breve". So' o
// QDOP EXPORTADO (arquivo) segue com o vocabulario oficial (verde, amarelo, vermelho).
type FarolObra = Obra["farol"];
const FAROL: Record<FarolObra, string> = { verde: "Em dia", acao: "Ação", atencao: "Atenção", vermelho: "Crítico" };

/** O farol da obra como selo: glifo e palavra. Farol que o servidor inventar conta como Atenção. */
export function SeloFarol({ farol }: { farol: FarolObra }) {
  return <Selo situacao={situacaoDoNivel(farol) ?? "breve"}>{FAROL[farol] ?? FAROL.atencao}</Selo>;
}

function pct(f: number): string {
  return fmtPercentual(f, 1);
}
function data(iso: string | null | undefined): string {
  return iso ? fmtDataPura(iso.slice(0, 10)) : "—";
}

function Secao({ id, titulo, acoes, children }:
    { id: string; titulo: string; acoes?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="cartao" aria-labelledby={id}>
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id={id}>{titulo}</h2>
        {acoes && <div className="cartao__acoes">{acoes}</div>}
      </div>
      {children}
    </section>
  );
}

// O que termina, pela regra da lista de Obras (`listaObras.ts`), com o link para ela filtrada.
const PRAZOS = [{ dias: 90, busca: "90", quando: `em ${fmtDias(90)}` }, { dias: 180, busca: "180", quando: "em 6\u00a0meses" }];

/** #279 (spec 2026-10-20 §2.2): o reajuste já medido (pedido ou aprovado) das competências sem apostilamento, por
 *  obra; a obra leva à aba Reajuste dela, com cada competência. */
export function Reajustes({ r, ir }: { r: NonNullable<Painel["reajustes_apostilamento"]>; ir: Ir }) {
  return (
    <Secao id="dir-reajustes" titulo="Reajustes esperando apostilamento">
      {r.obras.length === 0 ? (
        <div className="vazio vazio--curto"><p>Nenhum reajuste esperando apostilamento.</p></div>
      ) : (
        <Rolagem rotulo="Reajustes esperando apostilamento por obra">
          <table className="tabela tabela--estreita">
            <caption className="sr-only">Reajustes esperando apostilamento por obra, na cota da Lotufo</caption>
            <thead><tr><th scope="col">Obra</th><th scope="col" className="col-num">Competências</th>
              <th scope="col" className="col-num">Medido</th></tr></thead>
            <tbody>
              {r.obras.map(o => (
                <tr key={o.contrato_id}>
                  <td><Link className="nome-link truncar truncar--nome" title={o.obra}
                    para={{ tela: "obra", id: o.contrato_id, aba: "reajuste" }} ir={ir}>{o.obra}</Link></td>
                  <td className="col-num num">{o.competencias}</td>
                  <td className="col-num dinheiro num">{brl(o.valor_centavos)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot><tr><th scope="row">Total</th><td className="col-num num">{r.competencias}</td>
              <td className="col-num dinheiro num">{brl(r.valor_centavos)}</td></tr></tfoot>
          </table>
        </Rolagem>
      )}
    </Secao>
  );
}

type Filtro = "todas" | "problema" | FarolObra;
const FILTROS: { id: Filtro; rotulo: string }[] = [
  { id: "todas", rotulo: "Todas" }, { id: "problema", rotulo: "Com problema" },
  { id: "vermelho", rotulo: "Crítico" }, { id: "acao", rotulo: "Ação" },
  { id: "atencao", rotulo: "Atenção" }, { id: "verde", rotulo: "Em dia" },
];
const noFiltro = (o: Obra, f: Filtro) => f === "todas" || (f === "problema" ? o.farol !== "verde" : o.farol === f);

/** QDOP: um painel so'. No alto, o filtro pelo farol (cada botao com a contagem) e o arquivo exportado; a tabela no
 *  leiaute do QDOP, pelo farol, com a linha de total e ate' 2 motivos por obra (o resto nos avisos da obra); embaixo,
 *  o que termina e os avisos da diretoria, com os links. */
export function Qdop({ p, ir }: { p: Painel; ir: Ir }) {
  const [filtro, setFiltro] = useState<Filtro>("todas");
  // o que termina vem da lista de Obras (/api/contratos); undefined = carregando; null = nao carregou
  const [lista, setLista] = useState<ObraLista[] | null | undefined>(undefined);
  useEffect(() => {
    let vivo = true;
    api<ObraLista[]>("/api/contratos").then(l => { if (vivo) setLista(l); }).catch(() => { if (vivo) setLista(null); });
    return () => { vivo = false; };
  }, []);
  const obras = porFarol(p.obras.filter(o => noFiltro(o, filtro)));
  const soma = (f: (o: Obra) => number) => obras.reduce((t, o) => t + f(o), 0);
  return (
    <section className="cartao qdop-painel" aria-labelledby="dir-qdop">
      <div className="cartao__cabeca qdop-painel__cabeca">
        <h2 className="cartao__titulo" id="dir-qdop">QDOP</h2>
        <div className="cartao__acoes">
          <a className="btn btn--pequeno" href="/api/diretoria/qdop.xlsx"><IconeBaixar className="icone icone--p" /> Exportar QDOP (.xlsx)</a>
        </div>
      </div>
      <div className="escolhas qdop-filtros" role="group" aria-label="Filtrar o QDOP pelo farol">
        {FILTROS.map(f => {
          const n = p.obras.filter(o => noFiltro(o, f.id)).length;
          return (
            <button key={f.id} type="button" className="escolha" aria-pressed={filtro === f.id} onClick={() => setFiltro(f.id)}>
              {f.rotulo} <span className="escolha__n num">{n}</span>
            </button>
          );
        })}
      </div>
      <Rolagem rotulo="QDOP" alta>
        <table className="tabela qdop-tabela">
          <caption className="sr-only">QDOP, na cota da Lotufo: as obras pelo farol</caption>
          <thead>
            <tr>
              <th scope="col">Obra</th><th scope="col" className="col-num">Contratual de execução (PI+VA)</th>
              <th scope="col" className="col-num">Faturado</th><th scope="col" className="col-num">Saldo</th>
              <th scope="col">Término</th><th scope="col">Farol</th>
            </tr>
          </thead>
          <tbody>
            {obras.length === 0 && <tr><td colSpan={6}>Nenhuma obra neste farol.</td></tr>}
            {obras.map(o => {
              const { visiveis, mais } = motivosDaLinha(o.motivos);
              return (
                <tr key={o.contrato_id}>
                  <td data-rotulo="Obra">
                    <Link className="nome-link qdop-tabela__nome" para={{ tela: "obra", id: o.contrato_id, aba: "medicoes" }} ir={ir}>{o.obra}</Link>
                    <div className="qdop-tabela__sub">{o.empreita}{o.direito < 1 ? ` (${pct(o.direito)})` : ""} · {o.status}</div>
                  </td>
                  <td data-rotulo="Contratual de execução (PI+VA)" className="col-num dinheiro num">{brl(o.pi_va)}</td>
                  <td data-rotulo="Faturado" className="col-num dinheiro num">{brl(o.faturados)}</td>
                  <td data-rotulo="Saldo" className={`col-num dinheiro num${o.saldo < 0 ? " negativo" : ""}`}>{brl(o.saldo)}</td>
                  {/* 06/11/2026: a coluna "Desvio (p.p.)" (#296) saiu da tela */}
                  <td data-rotulo="Término" className="num">{data(o.termino)}<div className="qdop-tabela__sub">vigência {data(o.vigencia)}</div></td>
                  <td data-rotulo="Farol">
                    {/* a obra em dia fica so' com a palavra, em tinta: o selo e' da excecao (com o banco real, mais de
                        dez linhas repetiam o mesmo selo verde) */}
                    {o.farol === "verde" ? "Em dia" : <SeloFarol farol={o.farol} />}
                    {!o.motivos ? (o.motivo ? <div className="qdop-tabela__motivo">{o.motivo}</div> : null) : visiveis.length === 0 ? null : (
                      <ul className="qdop-tabela__motivos">
                        {visiveis.map(x => <li key={`${x.tipo}-${x.texto}`}>{x.texto}</li>)}
                        {mais > 0 && (
                          <li><Link para={{ tela: "avisos" }} busca={{ obra: String(o.contrato_id) }} ir={ir}>
                            mais {mais}<span className="sr-only"> {mais === 1 ? "motivo" : "motivos"} de {o.obra}</span>
                          </Link></li>
                        )}
                      </ul>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">Total</th>
              <td data-rotulo="Contratual de execução (PI+VA)" className="col-num dinheiro num">{brl(soma(o => o.pi_va))}</td>
              <td data-rotulo="Faturado" className="col-num dinheiro num">{brl(soma(o => o.faturados))}</td>
              <td data-rotulo="Saldo" className={`col-num dinheiro num${soma(o => o.saldo) < 0 ? " negativo" : ""}`}>{brl(soma(o => o.saldo))}</td>
              <td className="qdop-tabela__vazio" colSpan={2} />
            </tr>
          </tfoot>
        </table>
      </Rolagem>
      <footer className="qdop-rodape">
        <ul className="qdop-rodape__lista">
          {PRAZOS.map(x => {
            const n = lista ? filtrarObras(lista, { termina: x.dias }).length : null;
            return (
              <li key={x.busca}>
                <Link para={{ tela: "obras" }} busca={{ termina: x.busca }} ir={ir}>
                  {n === null ? `Obras que terminam ${x.quando}` : n === 1 ? `1 obra termina ${x.quando}` : `${n} obras terminam ${x.quando}`}
                </Link>
              </li>
            );
          })}
          <li>
            <Link para={{ tela: "avisos" }} ir={ir}>
              {p.avisos.length === 1 ? "1 aviso da diretoria" : `${p.avisos.length} avisos da diretoria`}
            </Link>
          </li>
        </ul>
        {lista === null && <Falha>Não foi possível contar as obras; os links abrem a lista.</Falha>}
      </footer>
    </section>
  );
}
