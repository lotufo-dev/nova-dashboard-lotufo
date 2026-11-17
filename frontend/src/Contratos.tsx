import { useEffect, useMemo, useState } from "react";
import { type Aviso } from "./Alertas";
import { api, mensagemDeErro } from "./api";
import AvisosPagina from "./AvisosPagina";
import { IconeAlerta } from "./icones";
import {
  ehDoContratante, escopoDaUrl, filtrarObras, gruposPorContratante, nomeDaObra, pctExecutado, pctPiso, posicaoDe, totaisDe,
  type ObraLista, type TotaisObras,
} from "./listaObras";
import { brl } from "./Medicoes";
import { CurvaDaCarteira, Qdop, Reajustes, SeloFarol, type Painel } from "./ObrasCarteira";
import { trocarBusca, type AbaObras, type Busca, type Ir } from "./rota";
import { Link } from "./Link";
import Rolagem from "./Rolagem";
import { Abas } from "./Topo";
import "./obras.css";
import Falha from "./Falha";

// Obras (lista), redesenhada na #774. A tela responde: quanto a empresa tem contratado, medido, a executar e a receber,
// por contratante e por obra, e que obra pede atencao. Tudo NA COTA DA LOTUFO (o cabecalho diz uma vez; os numeros vem
// prontos do servidor, em `posicao`). Duas vistas:
//  - "Obras" ("/obras"): os numeros da lista, a tabela por contratante com o subtotal de cada um e o farol da obra
//    que nao esta' em dia, a curva do previsto e do medido e os reajustes esperando apostilamento. E' a Posicao com o
//    Resumo que veio da Carteira (#748): os dois mostravam os mesmos totais, por contratante, em dois lugares.
//  - "QDOP" ("/obras/qdop"): o quadro no leiaute oficial, com o farol, os motivos e o arquivo exportado.
// O estado fica na URL: ?q=<busca>, ?situacao=todas (com as encerradas) e ?c=<contratante> (ou, nos links de antes,
// ?orgao=). "/obras/resumo" (link de antes) abre a vista Obras.
// Os Avisos (?avisos=1) continuam abrindo acima da tabela para os links de antes.

type Entidade = { id: number; nome: string; nome_curto?: string | null };
type Obra = ObraLista;

const FORA = new Set(["encerrado", "rescindido"]);
const VISTAS: { id: "posicao" | "qdop"; rotulo: string }[] = [{ id: "posicao", rotulo: "Posição" }, { id: "qdop", rotulo: "QDOP" }];

/** A barra do executado com o percentual ao lado. O percentual e' numero, nao situacao: tinta, sem glifo. */
function Executado({ pct }: { pct: number | null }) {
  return (
    <div className="obras-exec">
      <div className="obras-exec__trilho" role="img" aria-label={pct === null ? "sem valor vigente" : `${pct}% executado`}>
        <span className="obras-exec__barra" style={{ width: `${Math.min(100, Math.max(0, pct ?? 0))}%` }} />
      </div>
      <span className="obras-exec__pct num">{pct === null ? "—" : `${pct}%`}</span>
    </div>
  );
}

// o executado dos totais e do contratante, por piso como o de cada obra: 99,6% nao aparece como 100%
const pctDe = (t: TotaisObras) => pctPiso(t.medido, t.contratado);

export default function Contratos({ ir, busca = {}, aba = "posicao" }: { ir: Ir; busca?: Busca; aba?: AbaObras }) {
  const [lista, setLista] = useState<Obra[] | null>(null);
  const [empresas, setEmpresas] = useState<Map<number, string> | null>(new Map());
  const [avisos, setAvisos] = useState<Aviso[] | null | undefined>(undefined);
  // o painel da diretoria (`/api/diretoria`): o farol de cada obra, o medido do ano, a curva, os reajustes e o QDOP;
  // undefined = carregando; null = nao carregou
  const [painel, setPainel] = useState<Painel | null | undefined>(undefined);
  const [erroPainel, setErroPainel] = useState("");
  const [erro, setErro] = useState("");
  const vista = aba === "qdop" ? "qdop" : "posicao";

  useEffect(() => {
    let vivo = true;
    api<Obra[]>("/api/contratos").then(l => { if (vivo) setLista(l); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    api<Entidade[]>("/api/entidades")
      .then(l => { if (vivo) setEmpresas(new Map(l.map(e => [e.id, e.nome_curto || e.nome]))); })
      .catch(() => { if (vivo) setEmpresas(null); });
    api<{ avisos: Aviso[] }>("/api/inicio").then(d => { if (vivo) setAvisos(d.avisos); })
      .catch(() => { if (vivo) setAvisos(null); });
    api<Painel>("/api/diretoria").then(d => { if (vivo) setPainel(d); })
      .catch(e => { if (vivo) { setPainel(null); setErroPainel(mensagemDeErro(e)); } });
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
  // ?termina=90 (os links do QDOP): so' as obras cuja execucao ou vigencia acaba em ate' N dias, a que acaba antes primeiro
  const termina = /^\d{1,4}$/.test(busca.termina ?? "") ? Number(busca.termina) : null;
  const linhas = useMemo(() => filtrarObras(doContratante, { todas: comEncerradas, q, termina }), [doContratante, comEncerradas, q, termina]);
  const grupos = useMemo(() => gruposPorContratante(linhas), [linhas]);
  const farois = useMemo(() => new Map((painel?.obras ?? []).map(o => [o.contrato_id, o.farol])), [painel]);
  const totais = totaisDe(linhas);
  const pctTotal = pctDe(totais);
  // o medido do ano e' da carteira inteira: so' aparece ao lado dos totais quando a lista nao esta' filtrada
  const listaInteira = !orgao && !q.trim() && !comEncerradas && termina === null;
  const nomeLista = orgao ?? "Todas as obras";
  const aqui = { tela: "obras" as const };
  const semContratante: Busca = { ...busca };
  delete semContratante.c; delete semContratante.orgao; delete semContratante.termina;

  return (
    <>
      <header className="topbar topbar--detalhe">
        <div className="topbar__linha topbar__linha--quebra obras-topo">
          <h1 className="topbar__titulo topbar__titulo--grande">Obras <span className="obras-topo__sub">cota da Lotufo</span></h1>
          {lista && vista === "posicao" && (
            <div className="obras-busca">
              {termina !== null && <span className="obras-busca__filtro">Terminam em até {termina} dias</span>}
              {(orgao || termina !== null) && <Link para={aqui} busca={semContratante}>Todas as obras</Link>}
              <label className="sr-only" htmlFor="obras-busca">Buscar obra</label>
              <input id="obras-busca" type="search" className="obras-busca__campo" value={q} placeholder="Buscar obra ou contrato…"
                autoComplete="off" onChange={ev => { trocarBusca({ q: ev.target.value }); }} />
            </div>
          )}
        </div>
      </header>
      <div className="pagina obras">
        <Abas rotulo="Vistas da lista de Obras" atual={vista}
          itens={VISTAS.map(v => ({ ...v, para: { tela: "obras" as const, aba: v.id } }))} />

        {vista === "qdop" && (
          painel === undefined ? <section className="cartao"><div className="vazio"><p>Carregando…</p></div></section>
            : painel === null ? <Falha>{erroPainel} Recarregue a página para tentar de novo.</Falha>
              : <Qdop p={painel} ir={ir} />
        )}

        {vista === "posicao" && <>
        {!lista && !erro && <div className="vazio"><p>Carregando as obras…</p></div>}
        {erro && <Falha><IconeAlerta className="icone icone--p" />{erro} Recarregue a página para tentar de novo.</Falha>}
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
          <dl className="obras-numeros" aria-label="Totais">
            <div className="obras-numero"><dt>Contratado</dt><dd>{brl(totais.contratado)}</dd></div>
            <div className="obras-numero"><dt>Medido{pctTotal === null ? "" : ` (${pctTotal}%)`}</dt><dd>{brl(totais.medido)}</dd></div>
            <div className="obras-numero"><dt>Saldo a executar</dt><dd>{brl(totais.saldo)}</dd></div>
            <div className="obras-numero"><dt>A receber</dt><dd>{totais.temReceber ? brl(totais.aReceber) : "—"}</dd></div>
            {listaInteira && painel?.medido_ano && (
              <div className="obras-numero"><dt>Medido em {painel.medido_ano.ano}</dt><dd>{brl(painel.medido_ano.valor_centavos)}</dd></div>
            )}
          </dl>
        )}

        {lista && (
          <section className="cartao obras-painel" aria-label="Obras por contratante">
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
                        <td data-rotulo="Executado"><Executado pct={pctDe(g.subtotal)} /></td>
                        <td data-rotulo="A receber" className="col-num dinheiro num">{g.subtotal.temReceber ? brl(g.subtotal.aReceber) : "—"}</td>
                      </tr>
                      {g.obras.map(o => {
                        const p = posicaoDe(o);
                        const farol = farois.get(o.id);
                        return (
                          <tr key={o.id} className="linha linha--obra" onClick={e => { if (!(e.target as HTMLElement).closest("a")) ir({ tela: "obra", id: o.id, aba: "ficha" }); }}>
                            <td data-rotulo="Obra">
                              <Link className="nome-link obras-posicao__nome" para={{ tela: "obra", id: o.id, aba: "ficha" }} ir={ir}
                                >{nomeDaObra(o)}</Link>
                              {o.nome_curto && <div className="obras-posicao__sub">{o.numero_instrumento}</div>}
                              {/* estado vira selo, e so' quando pede atencao: a obra em dia nao leva marca */}
                              {farol && farol !== "verde" && <div className="obras-posicao__farol"><SeloFarol farol={farol} /></div>}
                            </td>
                            <td data-rotulo="Valor vigente" className="col-num dinheiro num">{brl(p.vigente_centavos)}</td>
                            <td data-rotulo="Medido" className="col-num dinheiro num">{brl(p.medido_centavos)}</td>
                            <td data-rotulo="Saldo a executar" className="col-num dinheiro num">{brl(p.saldo_centavos)}</td>
                            <td data-rotulo="Executado"><Executado pct={pctExecutado(o)} /></td>
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

        {lista && painel === null && (
          <Falha>Não foi possível carregar o farol, a curva e os reajustes. Recarregue a página para tentar de novo.</Falha>
        )}
        {lista && painel && listaInteira && <CurvaDaCarteira serie={painel.curva_carteira ?? []} />}
        {/* #279: o reajuste ja' medido das competencias sem apostilamento, por obra; so' quando existe */}
        {lista && painel?.reajustes_apostilamento && listaInteira && painel.reajustes_apostilamento.obras.length > 0
          && <Reajustes r={painel.reajustes_apostilamento} ir={ir} />}
        </>}
      </div>
    </>
  );
}
