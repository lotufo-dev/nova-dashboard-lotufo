import { useEffect, useMemo, useState } from "react";
import Andamento from "./Andamento";
import { api, mensagemDeErro } from "./api";
import Falha from "./Falha";
import { contar } from "./formato";
import { Link } from "./Link";
import {
  andamentoDaObra, contratanteDaObra, criticosPorObra, fimDaExecucao, filtrarObras, mesesDoMedido, nomeDaObra, participacao,
  pctExecutado, posicaoDe, resumoDe, totaisDe, type ObraLista,
} from "./listaObras";
import MarcaEtapa from "./MarcaEtapa";
import { type Painel } from "./ObrasCarteira";
import { AReceber, EtiquetasDeAtencao, Executado, MedidoNoMes, NumerosDeObras, SituacaoDaObra } from "./ObrasPecas";
import Rolagem from "./Rolagem";
import { useNomesDoCaminho } from "./nomesDoCaminho";
import { substituir, type AbaContratante, type Busca, type Ir } from "./rota";
import "./obras.css";

// A pagina do contratante (#805), o segundo nivel de Obras: "/obras/contratante/<chave>". A chave e' a que o servidor
// manda em cada obra (`contratante_chave`: a familia "sinfra" ou a chave do orgao no cadastro), nunca o nome escrito.
// No alto, os mesmos numeros do bloco do contratante (das obras em andamento dele), com a participacao na carteira e o
// prazo de pagamento do orgao; embaixo, uma linha por obra, com o andamento e a situacao com o motivo. Tudo na COTA da
// Lotufo e do servidor (`/api/contratos`, `/api/diretoria`). `?situacao=todas` traz as obras encerradas a' tabela.
// As abas Medicoes, A receber e Processos no SIGA do contratante ficam para a PR seguinte (#818); ate' la', os atalhos
// levam a's paginas que ja' existem. O endereco de cada aba ja' existe na rota (`aba`, #814).

const FORA = new Set(["encerrado", "rescindido"]);

export default function ContratantePagina({ chave, aba = "obras", perfil, busca = {}, ir }: {
  chave: string; aba?: AbaContratante; perfil: string; busca?: Busca; ir: Ir;
}) {
  const [lista, setLista] = useState<ObraLista[] | null>(null);
  // o painel da diretoria: o farol com os motivos, os avisos e o prazo de pagamento; undefined = carregando; null = falhou
  const [painel, setPainel] = useState<Painel | null | undefined>(undefined);
  const [erro, setErro] = useState("");

  useEffect(() => {
    let vivo = true;
    api<ObraLista[]>("/api/contratos").then(l => { if (vivo) setLista(l); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    api<Painel>("/api/diretoria").then(d => { if (vivo) setPainel(d); })
      .catch(() => { if (vivo) setPainel(null); });
    return () => { vivo = false; };
  }, []);

  const doContratante = useMemo(() => (lista ?? []).filter(o => o.contratante_chave === chave), [lista, chave]);
  const nome = doContratante.length > 0 ? contratanteDaObra(doContratante[0]) : null;
  const comEncerradas = busca.situacao === "todas";
  const emAndamento = useMemo(() => filtrarObras(doContratante, {}), [doContratante]);
  const linhas = useMemo(() => filtrarObras(doContratante, { todas: comEncerradas }), [doContratante, comEncerradas]);
  const criticos = useMemo(() => criticosPorObra(painel?.avisos ?? []), [painel]);
  const r = useMemo(() => resumoDe(emAndamento, criticos), [emAndamento, criticos]);
  const carteira = useMemo(() => totaisDe(filtrarObras(lista ?? [], {})).contratado, [lista]);
  const doPainel = useMemo(() => new Map((painel?.obras ?? []).map(o => [o.contrato_id, o])), [painel]);
  const mes = r.medidoMes ? mesesDoMedido(r.medidoMes).curto : null;
  const aqui = { tela: "contratante" as const, chave };

  useEffect(() => { document.title = `${nome ?? "Contratante"} · Obras · grupolotufo`; }, [nome]);
  // o caminho ("Obras › SINFRA") e' da barra do topo (#814): a pagina so' diz o nome do contratante, quando a lista chega
  useNomesDoCaminho({ contratante: nome ? { nome, chave } : null });
  // As abas Medicoes, A receber, Processos no SIGA e Avisos ja' tem endereco (#814) e chegam com a issue #818. Ate' la'
  // o endereco delas abre a pagina como ela e' hoje (a aba Obras), e a URL diz isso.
  useEffect(() => { if (aba !== "obras") substituir({ tela: "contratante", chave }); }, [aba, chave]);

  return (
    <>
      <header className="topbar topbar--detalhe">
        <div className="topbar__linha topbar__linha--quebra obras-topo">
          <h1 className="topbar__titulo topbar__titulo--grande">{nome ?? "Contratante"} <span className="obras-topo__sub">cota da Lotufo</span></h1>
          {nome && <p className="topbar__meta">{contar(r.obras, "obra em andamento", "obras em andamento")}</p>}
        </div>
      </header>
      <div className="pagina obras">
        {!lista && !erro && <div className="vazio"><p>Carregando as obras…</p></div>}
        {erro && <Falha>{erro} Recarregue a página para tentar de novo.</Falha>}
        {lista && !nome && (
          <section className="cartao">
            <div className="vazio vazio--curto">
              <p className="vazio__titulo">Contratante não encontrado.</p>
              <p><Link para={{ tela: "obras" }} ir={ir}>Ver os contratantes</Link></p>
            </div>
          </section>
        )}
        {lista && nome && (
          <>
            <NumerosDeObras r={r} rotulo={`Números de ${nome}`} participacao={participacao(r.totais.contratado, carteira)}
              prazo={painel?.prazo_pagamento?.[nome] ?? null} />
            <EtiquetasDeAtencao r={r} />
            {painel === null && <Falha>Não foi possível carregar a situação das obras e o prazo de pagamento. Recarregue a página para tentar de novo.</Falha>}

            <section className="cartao obras-painel" aria-label={`Obras de ${nome}`}>
              {linhas.length === 0 ? (
                <div className="vazio vazio--curto"><p className="vazio__titulo">Nenhuma obra em andamento.</p></div>
              ) : (
                <Rolagem rotulo={`Obras de ${nome}`} alta>
                  <table className="tabela obras-posicao obras-do-contratante">
                    <caption className="sr-only">Obras de {nome}: executado, andamento, medido no mês, a receber e situação</caption>
                    <thead>
                      <tr>
                        <th scope="col">Obra</th>
                        <th scope="col">Executado</th>
                        <th scope="col">Andamento</th>
                        <th scope="col" className="col-num">Medido{mes ? ` em ${mes}` : " no mês"}</th>
                        <th scope="col" className="col-num"><MarcaEtapa etapa="em_aberto">A receber</MarcaEtapa></th>
                        <th scope="col">Situação</th>
                      </tr>
                    </thead>
                    <tbody>
                      {linhas.map(o => {
                        const fim = fimDaExecucao(o.execucao_fim_vigente);
                        return (
                          <tr key={o.id} className="linha linha--obra" onClick={e => { if (!(e.target as HTMLElement).closest("a")) ir({ tela: "obra", id: o.id, aba: "ficha" }); }}>
                            <td data-rotulo="Obra">
                              <Link className="nome-link obras-posicao__nome" para={{ tela: "obra", id: o.id, aba: "ficha" }} ir={ir}>{nomeDaObra(o)}</Link>
                              {fim && <div className="obras-posicao__sub">{fim}</div>}
                            </td>
                            <td data-rotulo="Executado"><Executado pct={pctExecutado(o)} /></td>
                            <td data-rotulo="Andamento" className="obras-posicao__andamento">
                              {/* sem necessario ou sem ritmo a peca nao desenha nada: fica o tracinho */}
                              {andamentoDaObra(o) ? <Andamento ritmo={o.andamento?.ritmo_centavos} necessario={o.andamento?.necessario_centavos} detalhe="valores" /> : "—"}
                            </td>
                            <td data-rotulo={`Medido${mes ? ` em ${mes}` : " no mês"}`} className="col-num dinheiro"><MedidoNoMes mm={o.medido_mes} /></td>
                            <td data-rotulo="A receber" className="col-num dinheiro"><AReceber centavos={posicaoDe(o).a_receber_centavos} /></td>
                            <td data-rotulo="Situação" className="obras-do-contratante__situacao">
                              {FORA.has(o.estado) ? (o.estado === "encerrado" ? "Encerrada" : "Rescindida") : <SituacaoDaObra obra={doPainel.get(o.id)} ir={ir} />}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </Rolagem>
              )}
              <footer className="obras-rodape">
                <span>Mostrando <span className="num">{linhas.length}</span> de <span className="num">{doContratante.length}</span> obras</span>
                {!comEncerradas && doContratante.some(o => FORA.has(o.estado)) && <Link para={aqui} busca={{ situacao: "todas" }} ir={ir}>Ver todas</Link>}
                {comEncerradas && <Link para={aqui} ir={ir}>Só em andamento</Link>}
              </footer>
            </section>

            {/* o que e' do contratante nas outras paginas; o SIGA so' para quem o ve (a diretoria nao) */}
            <nav className="obras-atalhos" aria-label={`${nome} em outras páginas`}>
              <Link para={{ tela: "avisos" }} busca={{ c: nome }} ir={ir}>Avisos</Link>
              <Link para={{ tela: "fechamento" }} ir={ir}>Fechamento</Link>
              {perfil !== "diretoria" && <Link para={{ tela: "siga" }} ir={ir}>SIGA</Link>}
            </nav>
          </>
        )}
      </div>
    </>
  );
}
