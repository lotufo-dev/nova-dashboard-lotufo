import { useEffect, useMemo, useState } from "react";
import { abasDoPerfil, pronta, useLeitura, type AReceberDoContratante, type MedicoesDoContratante, type SigaDoContratante } from "./abasDoContratante";
import Andamento from "./Andamento";
import { api, mensagemDeErro } from "./api";
import Contador from "./Contador";
import { AbaAReceber, AbaMedicoes, AbaSiga } from "./ContratanteAbas";
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
import { vistaDe } from "./navegacao";
import { type AbaContratante, type Busca, type Ir } from "./rota";
import "./obras.css";
import "./contratante.css";

// A pagina do contratante (#805), o segundo nivel de Obras: "/obras/contratante/<chave>". A chave e' a que o servidor
// manda em cada obra (`contratante_chave`: a familia "sinfra" ou a chave do orgao no cadastro), nunca o nome escrito.
// Logo abaixo do titulo, as abas, cada uma com endereco e com a quantidade de linhas ao lado do nome (#818). Obras, a
// padrao: os mesmos numeros do bloco do contratante (das obras em andamento dele), com a participacao na carteira e o
// prazo de pagamento do orgao, e uma linha por obra, com o andamento e a situacao com o motivo; tudo na COTA da
// Lotufo, de `/api/contratos` e `/api/diretoria`; `?situacao=todas` traz as encerradas. Medicoes, A receber e
// Processos no SIGA: ContratanteAbas.tsx, cada uma o recorte que o servidor manda de uma tela que ja' existe. A aba
// do SIGA nao aparece para quem nao abre a tela SIGA (a diretoria), e a pagina nem pede o dado dela.

const FORA = new Set(["encerrado", "rescindido"]);

/** O que o leitor de tela diz no lugar do numero ao lado do nome da aba. */
const ROTULO_DA_QUANTIDADE: Record<AbaContratante, (n: number) => string> = {
  obras: n => contar(n, "obra", "obras"), medicoes: n => contar(n, "medição", "medições"), "a-receber": n => `${n} em aberto`,
  siga: n => contar(n, "processo", "processos"), avisos: n => contar(n, "aviso", "avisos"),
};

// `aba`: a aba do endereco; a que o perfil nao tem (ou que a pagina ainda nao desenha) abre Obras.
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

  // as abas do perfil e o dado de cada uma, pedidos juntos quando a lista diz que o contratante existe (o servidor
  // responde 404 a' chave que nenhuma obra tem): a faixa mostra a quantidade de todas
  const abas = abasDoPerfil(perfil);
  const atual: AbaContratante = abas.includes(aba) ? aba : "obras";
  const doServidor = nome ? `/api/contratantes/${encodeURIComponent(chave)}` : null;
  const medicoes = useLeitura<MedicoesDoContratante>(doServidor && `${doServidor}/medicoes`);
  const aReceber = useLeitura<AReceberDoContratante>(doServidor && `${doServidor}/a-receber`);
  const siga = useLeitura<SigaDoContratante>(doServidor && abas.includes("siga") ? `${doServidor}/siga` : null);
  // a quantidade e' o numero de linhas da aba: na de Obras, as da tabela; nas outras, a do servidor. Sem o dado (lendo,
  // falhou, ou a receber ainda nao liberado), a aba fica so' com o nome.
  const quantidade: Partial<Record<AbaContratante, number>> = {
    obras: linhas.length, medicoes: pronta(medicoes)?.quantidade, "a-receber": pronta(aReceber)?.quantidade,
    siga: pronta(siga)?.quantidade,
  };
  // o nome de cada aba e' o da vista no caminho do topo ("Obras › SINFRA › Medições"); a padrao, Obras
  const rotuloDa = (a: AbaContratante) => (a === "obras" ? "Obras" : vistaDe({ tela: "contratante", chave, aba: a }) ?? a);
  const daAba = rotuloDa(atual);

  useEffect(() => { document.title = `${nome ?? "Contratante"} · ${daAba} · grupolotufo`; }, [nome, daAba]);
  // o caminho ("Obras › SINFRA") e' da barra do topo (#814): a pagina so' diz o nome do contratante, quando a lista chega
  useNomesDoCaminho({ contratante: nome ? { nome, chave } : null });

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
            {/* as abas logo abaixo do titulo, na mesma altura em todas: cada uma com endereco
                ("/obras/contratante/sinfra/medicoes") e a quantidade de linhas dela. Na mesma faixa, a' direita, o que e'
                do contratante noutra pagina: os Avisos, filtrados por ele (o a receber e o SIGA, que antes levavam ao
                Fechamento e a' tela SIGA, sao abas desta pagina, #818) */}
            <div className="ct-faixa">
              <nav className="abas ct-abas" aria-label={`Seções de ${nome}`}>
                {abas.map(a => {
                  const n = quantidade[a];
                  return (
                    <Link key={a} className="aba" para={a === "obras" ? aqui : { ...aqui, aba: a }} ir={ir} aria-current={a === atual ? "page" : undefined}>
                      {rotuloDa(a)}
                      {n !== undefined && <Contador rotulo={`, ${ROTULO_DA_QUANTIDADE[a](n)}`}>{n.toLocaleString("pt-BR")}</Contador>}
                    </Link>
                  );
                })}
              </nav>
              <nav className="obras-atalhos ct-atalhos" aria-label={`${nome} em outras páginas`}>
                <Link para={{ tela: "avisos" }} busca={{ c: nome }} ir={ir}>Avisos</Link>
              </nav>
            </div>

            {atual === "medicoes" && <AbaMedicoes leitura={medicoes} nome={nome} opera={perfil !== "diretoria"} />}
            {atual === "a-receber" && <AbaAReceber leitura={aReceber} nome={nome} ir={ir} />}
            {atual === "siga" && <AbaSiga leitura={siga} />}

            {/* a aba Obras: os numeros do contratante (das obras em andamento dele), o que pede atencao e a tabela */}
            {atual === "obras" && <>
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
                        // a mesma leitura na coluna Andamento e na Situacao (devagar sem aviso nao e' "Em dia")
                        const leitura = andamentoDaObra(o);
                        return (
                          <tr key={o.id} className="linha linha--obra" onClick={e => { if (!(e.target as HTMLElement).closest("a")) ir({ tela: "obra", id: o.id, aba: "ficha" }); }}>
                            <td data-rotulo="Obra">
                              <Link className="nome-link obras-posicao__nome" para={{ tela: "obra", id: o.id, aba: "ficha" }} ir={ir}>{nomeDaObra(o)}</Link>
                              {fim && <div className="obras-posicao__sub">{fim}</div>}
                            </td>
                            <td data-rotulo="Executado"><Executado pct={pctExecutado(o)} /></td>
                            <td data-rotulo="Andamento" className="obras-posicao__andamento">
                              {/* #822: a leitura vem do servidor. Fora da regua a peca escreve o motivo; sem nada, o tracinho */}
                              {leitura
                                ? <Andamento leitura={o.andamento?.leitura} ritmo={o.andamento?.ritmo_centavos} necessario={o.andamento?.necessario_centavos} detalhe="valores" />
                                : <Andamento leitura={o.andamento?.leitura} vazio="—" />}
                            </td>
                            <td data-rotulo={`Medido${mes ? ` em ${mes}` : " no mês"}`} className="col-num dinheiro"><MedidoNoMes mm={o.medido_mes} /></td>
                            <td data-rotulo="A receber" className="col-num dinheiro"><AReceber centavos={posicaoDe(o).a_receber_centavos} /></td>
                            <td data-rotulo="Situação" className="obras-do-contratante__situacao">
                              {FORA.has(o.estado) ? (o.estado === "encerrado" ? "Encerrada" : "Rescindida") : <SituacaoDaObra obra={doPainel.get(o.id)} ir={ir} andamento={leitura} />}
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
            </>}
          </>
        )}
      </div>
    </>
  );
}
