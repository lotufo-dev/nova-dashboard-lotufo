import { useEffect, useMemo, useState } from "react";
import { type Aviso } from "./Alertas";
import { api, mensagemDeErro } from "./api";
import AvisosPagina from "./AvisosPagina";
import { IconeAlerta } from "./icones";
import {
  ehDoContratante, escopoDaUrl, filtrarObras, gruposPorContratante, nomeDaObra, pctExecutado, posicaoDe, totaisDe,
  type ObraLista,
} from "./listaObras";
import { brl } from "./Medicoes";
import { trocarBusca, type Busca, type Ir } from "./rota";
import { Link } from "./Link";
import Rolagem from "./Rolagem";
import "./obras.css";

// Obras (lista), redesenho de 06/11/2026 (#509) revisto em 10/11/2026 (#645): uma tabela de posicao financeira NA COTA
// DA LOTUFO (o cabecalho diz uma vez; os numeros vem prontos do servidor, em `posicao`), agrupada por contratante com o
// subtotal de cada um, os totais sob o titulo e a busca no topo. O estado fica na URL: ?q=<busca>, ?situacao=todas (com
// as encerradas) e, nos links de antes, ?c=<contratante> (ou ?orgao=), que mostra so' o grupo dele.
// Os Avisos (?avisos=1) continuam abrindo acima da tabela enquanto a tela propria deles nao existe.

type Entidade = { id: number; nome: string; nome_curto?: string | null };
type Obra = ObraLista;

const FORA = new Set(["encerrado", "rescindido"]);

/** "R$ 1.712,6 mi", como nos totais da imagem. */
function emMilhoes(centavos: number): string {
  return `R$ ${(centavos / 100_000_000).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} mi`;
}

export default function Contratos({ ir, busca = {} }: { ir: Ir; busca?: Busca }) {
  const [lista, setLista] = useState<Obra[] | null>(null);
  const [empresas, setEmpresas] = useState<Map<number, string> | null>(new Map());
  const [avisos, setAvisos] = useState<Aviso[] | null | undefined>(undefined);
  const [erro, setErro] = useState("");

  useEffect(() => {
    let vivo = true;
    api<Obra[]>("/api/contratos").then(l => { if (vivo) setLista(l); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    api<Entidade[]>("/api/entidades")
      .then(l => { if (vivo) setEmpresas(new Map(l.map(e => [e.id, e.nome_curto || e.nome]))); })
      .catch(() => { if (vivo) setEmpresas(null); });
    api<{ avisos: Aviso[] }>("/api/inicio").then(d => { if (vivo) setAvisos(d.avisos); })
      .catch(() => { if (vivo) setAvisos(null); });
    return () => { vivo = false; };
  }, []);

  const { orgao } = escopoDaUrl(busca);
  // link de antes (?orgao=...): a URL ganha o `c`
  const orgaoAntigo = busca.c === undefined && busca.orgao ? busca.orgao : null;
  useEffect(() => { if (orgaoAntigo !== null) trocarBusca({ c: orgaoAntigo, orgao: null }); }, [orgaoAntigo]);
  const comEncerradas = busca.situacao === "todas";
  const avisosAbertos = busca.avisos === "1";

  const doContratante = useMemo(() => (lista ?? []).filter(o => !orgao || ehDoContratante(o, orgao)), [lista, orgao]);
  const idsDoContratante = useMemo(() => (orgao ? new Set(doContratante.map(o => o.id)) : null), [orgao, doContratante]);
  const q = busca.q ?? "";
  const linhas = useMemo(() => filtrarObras(doContratante, { todas: comEncerradas, q }), [doContratante, comEncerradas, q]);
  const grupos = useMemo(() => gruposPorContratante(linhas), [linhas]);
  const totais = totaisDe(linhas);
  const nomeLista = orgao ?? "Todas as obras";
  const aqui = { tela: "obras" as const };
  const semContratante: Busca = { ...busca };
  delete semContratante.c; delete semContratante.orgao;

  return (
    <>
      <header className="topbar topbar--detalhe">
        <div className="topbar__linha topbar__linha--quebra obras-topo">
          <h1 className="topbar__titulo topbar__titulo--grande">Obras <span className="obras-topo__sub">cota da Lotufo</span></h1>
          {lista && (
            <div className="obras-busca">
              {orgao && <Link para={aqui} busca={semContratante}>Todas as obras</Link>}
              <label className="sr-only" htmlFor="obras-busca">Buscar obra</label>
              <input id="obras-busca" type="search" className="obras-busca__campo" value={q} placeholder="Buscar obra ou contrato…"
                autoComplete="off" onChange={ev => { trocarBusca({ q: ev.target.value }); }} />
            </div>
          )}
        </div>
        {lista && (
          <div className="obras-totais" role="group" aria-label="Totais">
            <span>Contratado <strong className="num">{emMilhoes(totais.contratado)}</strong></span>
            <span>Medido <strong className="num">{emMilhoes(totais.medido)}</strong></span>
            <span>Saldo <strong className="num">{emMilhoes(totais.saldo)}</strong></span>
            <span>A receber <strong className="num">{totais.temReceber ? emMilhoes(totais.aReceber) : "—"}</strong></span>
          </div>
        )}
      </header>
      <div className="pagina">
        {!lista && !erro && <div className="vazio"><p>Carregando as obras…</p></div>}
        {erro && <p className="erro" role="alert">
          <IconeAlerta className="icone icone--p" />{erro} Recarregue a página para tentar de novo.
        </p>}
        {lista && (empresas === null || avisos === null) && avisosAbertos && (
          <p className="campo__nota" role="alert">
            Não foi possível carregar {[empresas === null && "os nomes das empresas", avisos === null && "os avisos"].filter(Boolean).join(" nem ")};
            recarregue a página para tentar de novo.
          </p>
        )}

        {lista && avisosAbertos && (
          <AvisosPagina busca={busca} avisos={avisos} escopo={idsDoContratante} nome={nomeLista}
            onFechar={() => { trocarBusca({ avisos: null, familia: null, nivel: null, obra: null, agrupar: null }); }} />
        )}

        {lista && (
          <section className="cartao">
            {linhas.length === 0 ? (
              <div className="vazio vazio--curto"><p className="vazio__titulo">Nenhuma obra.</p></div>
            ) : (
              <Rolagem rotulo="Obras" alta>
                <table className="tabela obras-posicao">
                  <caption className="sr-only">Obras, posição financeira</caption>
                  <thead>
                    <tr>
                      <th scope="col">Obra</th>
                      <th scope="col" className="col-num">Valor vigente</th>
                      <th scope="col" className="col-num">Medido</th>
                      <th scope="col" className="col-num">Saldo a executar</th>
                      <th scope="col">Executado</th>
                      <th scope="col" className="col-num">A receber</th>
                    </tr>
                  </thead>
                  {grupos.map(g => (
                    <tbody key={g.contratante}>
                      <tr className="obras-grupo">
                        <th scope="rowgroup">{g.contratante}</th>
                        <td data-rotulo="Valor vigente" className="col-num dinheiro num">{brl(g.subtotal.contratado)}</td>
                        <td data-rotulo="Medido" className="col-num dinheiro num">{brl(g.subtotal.medido)}</td>
                        <td data-rotulo="Saldo a executar" className="col-num dinheiro num">{brl(g.subtotal.saldo)}</td>
                        <td className="obras-grupo__vazio" />
                        <td data-rotulo="A receber" className="col-num dinheiro num">{g.subtotal.temReceber ? brl(g.subtotal.aReceber) : "—"}</td>
                      </tr>
                      {g.obras.map(o => {
                        const pct = pctExecutado(o);
                        const p = posicaoDe(o);
                        return (
                          <tr key={o.id} className="linha linha--obra" onClick={e => { if (!(e.target as HTMLElement).closest("a")) ir({ tela: "obra", id: o.id, aba: "ficha" }); }}>
                            <td data-rotulo="Obra">
                              <Link className="nome-link obras-posicao__nome" para={{ tela: "obra", id: o.id, aba: "ficha" }} ir={ir}
                                >{nomeDaObra(o)}</Link>
                              {o.nome_curto && <div className="obras-posicao__sub">{o.numero_instrumento}</div>}
                            </td>
                            <td data-rotulo="Valor vigente" className="col-num dinheiro num">{brl(p.vigente_centavos)}</td>
                            <td data-rotulo="Medido" className="col-num dinheiro num">{brl(p.medido_centavos)}</td>
                            <td data-rotulo="Saldo a executar" className="col-num dinheiro num">{brl(p.saldo_centavos)}</td>
                            <td data-rotulo="Executado">
                              <div className="obras-exec">
                                <div className="progresso progresso--feito" role="img" aria-label={pct === null ? "sem valor vigente" : `${pct}% executado`}>
                                  <span className="progresso__barra" style={{ width: `${Math.min(100, Math.max(0, pct ?? 0))}%` }} />
                                </div>
                                <span className="pilula-info pilula-info--feito obras-exec__pct num">{pct === null ? "—" : `${pct}%`}</span>
                              </div>
                            </td>
                            <td data-rotulo="A receber" className="col-num dinheiro num">{p.a_receber_centavos == null ? "—" : brl(p.a_receber_centavos)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  ))}
                </table>
              </Rolagem>
            )}
            <footer className="obras-rodape">
              <span>Mostrando <span className="num">{linhas.length}</span> de <span className="num">{doContratante.length}</span> obras</span>
              {!comEncerradas && doContratante.some(o => FORA.has(o.estado)) && (
                <Link para={aqui} busca={{ ...busca, situacao: "todas" }}>Ver todas</Link>
              )}
              {comEncerradas && (
                <Link para={aqui} busca={{ ...busca, situacao: "" }}>Só em andamento</Link>
              )}
            </footer>
          </section>
        )}
      </div>
    </>
  );
}
