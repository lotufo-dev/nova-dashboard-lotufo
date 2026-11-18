import { useEffect, useMemo, useState } from "react";
import { api, mensagemDeErro } from "./api";
import EmAbertoAParte from "./EmAbertoAParte";
import {
  andamentoDaObra, ehDoContratante, escopoDaUrl, fimDaExecucao, filtrarObras, gruposPorContratante, nomeDaObra, pctExecutado, pctPiso, posicaoDe, totaisDe,
  type ObraLista, type TotaisObras,
} from "./listaObras";
import { brl } from "./Medicoes";
import { Glifo } from "./Selo";
import Andamento from "./Andamento";
import ObrasAndamento from "./ObrasAndamento";
import { Qdop, Reajustes, type Painel } from "./ObrasCarteira";
import ObrasContratantes from "./ObrasContratantes";
import { Executado, SituacaoDaObra } from "./ObrasPecas";
import { substituir, trocarBusca, type AbaObras, type Busca, type Ir } from "./rota";
import { Link } from "./Link";
import Rolagem from "./Rolagem";
import { Abas } from "./Topo";
import "./obras.css";
import Falha from "./Falha";

// Obras em niveis, comecando pelo contratante (#805, decisao do dono de 18/11/2026: "e' tudo uma lista, um em cima do
// outro"; "todos os numeros estao em preto"). Tudo NA COTA DA LOTUFO (o cabecalho diz uma vez; os numeros vem prontos
// do servidor, em `/api/contratos` e `/api/diretoria`). Quatro vistas, cada uma com endereco:
//  - "Por contratante" ("/obras", a entrada): os numeros da carteira e um bloco por contratante, que leva a' pagina
//    dele (`ObrasContratantes.tsx`; a pagina e' `ContratantePagina.tsx`, "/obras/contratante/<chave>").
//  - "Todas as obras" ("/obras/todas"): a tabela de posicao da #774, agrupada por contratante com o cabecalho de grupo
//    forte, com a coluna Andamento e o motivo da situacao sob o nome; os reajustes esperando apostilamento, recolhidos.
//  - "Andamento" ("/obras/andamento"): as obras com prazo a cumprir, da que mede a menor parte do necessario para a
//    maior (`ObrasAndamento.tsx`).
//  - "QDOP" ("/obras/qdop"): o quadro no leiaute oficial, com o farol, os motivos e o arquivo exportado.
// Os enderecos de antes: "/obras" com filtro (?q=, ?situacao=, ?termina=, ?c=todas) abre "Todas as obras";
// "/obras?c=<contratante>" abre a pagina do contratante; "/obras/posicao" e "/obras/resumo" estao em rota.tsx.
// O estado fica na URL: ?q=<busca>, ?situacao=todas (com as encerradas) e ?c=<contratante> (ou, nos links de antes,
// ?orgao=). "/obras/resumo" (link de antes) abre a vista Obras.

type Obra = ObraLista;

const FORA = new Set(["encerrado", "rescindido"]);
const VISTAS: { id: AbaObras; rotulo: string }[] = [{ id: "contratantes", rotulo: "Por contratante" }, { id: "todas", rotulo: "Todas as obras" },
  { id: "andamento", rotulo: "Andamento" }, { id: "qdop", rotulo: "QDOP" }];

// o executado dos totais e do contratante, por piso como o de cada obra: 99,6% nao aparece como 100%
const pctDe = (t: TotaisObras) => pctPiso(t.medido, t.contratado);

export default function Contratos({ ir, busca = {}, aba = "contratantes" }: { ir: Ir; busca?: Busca; aba?: AbaObras }) {
  const [lista, setLista] = useState<Obra[] | null>(null);
  // o painel da diretoria (`/api/diretoria`): o farol de cada obra, o medido do ano, os reajustes e o QDOP;
  // undefined = carregando; null = nao carregou
  const [painel, setPainel] = useState<Painel | null | undefined>(undefined);
  const [erroPainel, setErroPainel] = useState("");
  const [erro, setErro] = useState("");

  useEffect(() => {
    let vivo = true;
    api<Obra[]>("/api/contratos").then(l => { if (vivo) setLista(l); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    api<Painel>("/api/diretoria").then(d => { if (vivo) setPainel(d); })
      .catch(e => { if (vivo) { setPainel(null); setErroPainel(mensagemDeErro(e)); } });
    return () => { vivo = false; };
  }, []);

  const { escolha, orgao } = escopoDaUrl(busca);
  // link de antes (?orgao=...): a URL ganha o `c`
  const orgaoAntigo = busca.c === undefined && busca.orgao ? busca.orgao : null;
  useEffect(() => { if (orgaoAntigo !== null) trocarBusca({ c: orgaoAntigo, orgao: null }); }, [orgaoAntigo]);
  // "/obras" com filtro de antes da #805 (?q=, ?situacao=, ?termina=, ?c=) e' a tabela de todas as obras, que e' quem
  // filtra: a vista e' ela, e o endereco passa a ser o dela ("/obras/todas"), com os filtros. Quem abriu a pagina com
  // os Avisos (?avisos=1) fica no endereco em que veio, tambem depois de fecha-los.
  const vista: AbaObras = aba === "contratantes" && !escolha ? "todas" : aba;
  const [abriuComAvisos] = useState(busca.avisos === "1");
  const paraTodas = aba === "contratantes" && !escolha && !abriuComAvisos && busca.avisos !== "1";
  // "/obras?c=<contratante>" (o filtro de antes) abre a pagina do contratante, quando a lista o conhece
  const chaveDoFiltro = paraTodas && orgao ? (lista ?? []).find(o => ehDoContratante(o, orgao) && o.contratante_chave)?.contratante_chave ?? null : null;
  const soContratante = !["q", "situacao", "termina"].some(k => busca[k] !== undefined);
  useEffect(() => {
    if (!paraTodas) return;
    if (orgao && lista === null) return;                        // espera a lista para saber se o filtro e' um contratante
    if (chaveDoFiltro && soContratante) substituir({ tela: "contratante", chave: chaveDoFiltro }, { semBusca: true });
    else substituir({ tela: "obras", aba: "todas" });
  }, [paraTodas, orgao, lista, chaveDoFiltro, soContratante]);
  const comEncerradas = busca.situacao === "todas";

  const doContratante = useMemo(() => (lista ?? []).filter(o => !orgao || ehDoContratante(o, orgao)), [lista, orgao]);
  const q = busca.q ?? "";
  // ?termina=90 (os links do QDOP): so' as obras cuja execucao ou vigencia acaba em ate' N dias, a que acaba antes primeiro
  const termina = /^\d{1,4}$/.test(busca.termina ?? "") ? Number(busca.termina) : null;
  const linhas = useMemo(() => filtrarObras(doContratante, { todas: comEncerradas, q, termina }), [doContratante, comEncerradas, q, termina]);
  const grupos = useMemo(() => gruposPorContratante(linhas), [linhas]);
  const doPainel = useMemo(() => new Map((painel?.obras ?? []).map(o => [o.contrato_id, o])), [painel]);
  // as vistas "Por contratante" e "Andamento" nao tem filtro: sao as obras em andamento da carteira inteira
  const emAndamento = useMemo(() => filtrarObras(lista ?? [], {}), [lista]);
  const totais = totaisDe(linhas);
  const pctTotal = pctDe(totais);
  // o medido do ano e' da carteira inteira: so' aparece ao lado dos totais quando a lista nao esta' filtrada
  const listaInteira = !orgao && !q.trim() && !comEncerradas && termina === null;
  const aqui = { tela: "obras" as const };
  const semContratante: Busca = { ...busca };
  delete semContratante.c; delete semContratante.orgao; delete semContratante.termina;
  // os links que filtram a tabela ficam na vista dela
  const todas = { ...aqui, aba: "todas" as const };

  return (
    <>
      <header className="topbar topbar--detalhe">
        <div className="topbar__linha topbar__linha--quebra obras-topo">
          <h1 className="topbar__titulo topbar__titulo--grande">Obras <span className="obras-topo__sub">cota da Lotufo</span></h1>
          {lista && vista === "todas" && (
            <div className="obras-busca">
              {termina !== null && <span className="obras-busca__filtro">Terminam em até {termina} dias</span>}
              {/* a aba ja' se chama "Todas as obras": o link que desfaz o recorte diz o que faz */}
              {orgao && <span className="obras-busca__filtro">{orgao}</span>}
              {(orgao || termina !== null) && <Link para={todas} busca={semContratante}>Tirar o filtro</Link>}
              <label className="sr-only" htmlFor="obras-busca">Buscar obra</label>
              <input id="obras-busca" type="search" className="obras-busca__campo" value={q} placeholder="Buscar obra ou contrato…"
                autoComplete="off" onChange={ev => { trocarBusca({ q: ev.target.value }); }} />
            </div>
          )}
        </div>
      </header>
      <div className="pagina obras">
        <Abas rotulo="Vistas de Obras" atual={vista}
          itens={VISTAS.map(v => ({ ...v, para: { tela: "obras" as const, aba: v.id } }))} />

        {vista === "qdop" && (
          painel === undefined ? <section className="cartao"><div className="vazio"><p>Carregando…</p></div></section>
            : painel === null ? <Falha>{erroPainel} Recarregue a página para tentar de novo.</Falha>
              : <Qdop p={painel} ir={ir} />
        )}

        {(vista === "contratantes" || vista === "andamento") && (
          <>
            {!lista && !erro && <div className="vazio"><p>Carregando as obras…</p></div>}
            {erro && <Falha>{erro} Recarregue a página para tentar de novo.</Falha>}
            {lista && vista === "contratantes" && <ObrasContratantes obras={emAndamento} painel={painel} ir={ir} />}
            {lista && vista === "andamento" && <ObrasAndamento obras={emAndamento} painel={painel} ir={ir} />}
            {lista && painel === null && (
              <Falha>Não foi possível carregar os avisos das obras e o prazo de pagamento. Recarregue a página para tentar de novo.</Falha>
            )}
          </>
        )}

        {vista === "todas" && <>
        {!lista && !erro && <div className="vazio"><p>Carregando as obras…</p></div>}
        {erro && <Falha>{erro} Recarregue a página para tentar de novo.</Falha>}

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

        {/* fora do total "A receber": o em aberto antigo e o que o RM deixou de informar, das obras que a lista mostra */}
        {lista && totais.anoInicial && (
          <EmAbertoAParte anoInicial={totais.anoInicial} anterior={totais.aReceberAnterior}
            semAtualizacao={totais.aReceberSemAtualizacao} />
        )}

        {lista && painel === null && (
          <Falha>Não foi possível carregar o farol e os reajustes. Recarregue a página para tentar de novo.</Falha>
        )}
        {/* #279: o reajuste ja' medido das competencias sem apostilamento, por obra; so' quando existe. #805: saiu do
            fim da lista; fica acima da tabela, recolhido (a quantidade e o total na faixa do titulo) */}
        {lista && painel?.reajustes_apostilamento && listaInteira && painel.reajustes_apostilamento.obras.length > 0
          && <Reajustes r={painel.reajustes_apostilamento} ir={ir} recolhido />}

        {lista && (
          <section className="cartao obras-painel" aria-label="Obras por contratante">
            {linhas.length === 0 ? (
              <div className="vazio vazio--curto"><p className="vazio__titulo">Nenhuma obra.</p></div>
            ) : (
              <Rolagem rotulo="Obras" alta>
                <table className="tabela obras-posicao obras-todas">
                  <caption className="sr-only">Obras, posição financeira</caption>
                  <thead>
                    <tr>
                      <th scope="col">Obra</th>
                      <th scope="col" className="col-num">Valor vigente</th>
                      <th scope="col" className="col-num">Medido</th>
                      <th scope="col" className="col-num">Saldo a executar</th>
                      <th scope="col">Executado</th>
                      <th scope="col">Andamento</th>
                      <th scope="col" className="col-num">A receber</th>
                    </tr>
                  </thead>
                  {grupos.map(g => (
                    <tbody key={g.contratante}>
                      {/* o cabecalho de grupo forte (#805): o contratante em tinta cheia, com o subtotal nas colunas;
                          o nome leva a' pagina dele */}
                      <tr className="obras-grupo">
                        <th scope="rowgroup">
                          {g.chave ? <Link para={{ tela: "contratante", chave: g.chave }} ir={ir}>{g.contratante}</Link> : g.contratante}
                          <span className="obras-grupo__n num">{g.obras.length === 1 ? "1 obra" : `${g.obras.length} obras`}</span>
                        </th>
                        <td data-rotulo="Valor vigente" className="col-num dinheiro num">{brl(g.subtotal.contratado)}</td>
                        <td data-rotulo="Medido" className="col-num dinheiro num">{brl(g.subtotal.medido)}</td>
                        <td data-rotulo="Saldo a executar" className="col-num dinheiro num">{brl(g.subtotal.saldo)}</td>
                        <td data-rotulo="Executado"><Executado pct={pctDe(g.subtotal)} /></td>
                        <td className="obras-grupo__vazio" />
                        <td data-rotulo="A receber" className="col-num dinheiro num">{g.subtotal.temReceber ? brl(g.subtotal.aReceber) : "—"}</td>
                      </tr>
                      {g.obras.map(o => {
                        const p = posicaoDe(o);
                        const fim = fimDaExecucao(o.execucao_fim_vigente);
                        return (
                          <tr key={o.id} className="linha linha--obra" onClick={e => { if (!(e.target as HTMLElement).closest("a")) ir({ tela: "obra", id: o.id, aba: "ficha" }); }}>
                            <td data-rotulo="Obra">
                              <Link className="nome-link obras-posicao__nome" para={{ tela: "obra", id: o.id, aba: "ficha" }} ir={ir}
                                >{nomeDaObra(o)}</Link>
                              {o.nome_curto && <div className="obras-posicao__sub">{o.numero_instrumento}</div>}
                              {fim && <div className="obras-posicao__sub">{fim}</div>}
                              {/* a situacao com o motivo escrito, e so' quando pede atencao: a obra em dia nao leva marca */}
                              {doPainel.get(o.id) && doPainel.get(o.id)?.farol !== "verde" && (
                                <div className="obras-posicao__farol"><SituacaoDaObra obra={doPainel.get(o.id)} ir={ir} /></div>
                              )}
                            </td>
                            <td data-rotulo="Valor vigente" className="col-num dinheiro num">{brl(p.vigente_centavos)}</td>
                            <td data-rotulo="Medido" className="col-num dinheiro num">{brl(p.medido_centavos)}</td>
                            <td data-rotulo="Saldo a executar" className={`col-num dinheiro num${p.saldo_centavos < 0 ? " negativo" : ""}`}>
                              {/* o medido passou do valor vigente: em critico, como no alto da pagina da obra */}
                              {p.saldo_centavos < 0 && <Glifo situacao="critico" />}{brl(p.saldo_centavos)}</td>
                            <td data-rotulo="Executado"><Executado pct={pctExecutado(o)} /></td>
                            <td data-rotulo="Andamento" className={`obras-posicao__andamento${andamentoDaObra(o) ? "" : " obras-posicao__andamento--sem"}`}>
                              {/* sem necessario ou sem ritmo a peca nao desenha nada: fica o tracinho. A tabela ja' tem
                                  quatro colunas de valor: aqui vai a palavra e a razao; os valores por mes estao na
                                  pagina do contratante e na vista Andamento */}
                              {andamentoDaObra(o) ? <Andamento ritmo={o.andamento?.ritmo_centavos} necessario={o.andamento?.necessario_centavos} /> : "—"}
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
                <Link para={todas} busca={{ ...busca, situacao: "todas" }}>Ver todas</Link>
              )}
              {comEncerradas && (
                <Link para={todas} busca={{ ...busca, situacao: "" }}>Só em andamento</Link>
              )}
            </footer>
          </section>
        )}
        </>}
      </div>
    </>
  );
}
