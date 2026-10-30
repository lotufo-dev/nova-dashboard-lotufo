import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api, mensagemDeErro } from "./api";
import CaixaAviso from "./CaixaAviso";
import { IconeAlerta, IconeLinkExterno, IconeSiga } from "./icones";
import { Link } from "./Link";
import type { ObraLista } from "./listaObras";
import { trocarBusca, type Busca } from "./rota";
import Selo from "./Selo";
import {
  casaComBusca, destinoDaMovimentacao, nivelDias, nomeDoProcesso, ordenar, quemDaMovimentacao, situacaoDoBotao,
  tempoNoSetor, tituloDoEvento, volumeDe, type Movimentacao, type PainelSiga, type ProcessoSiga, type Robo,
} from "./siga";
import { fmtData, fmtDataHora, fmtHora } from "./tempo";
import "./siga.css";

// Tela SIGA (#329, local escolhido pelo Leo em 28/10/2026): onde esta' cada processo protocolado, com quem, ha
// quantos dias uteis e o que andou hoje, com as movimentacoes do escolhido ao lado. A tabela e' a que o Leo
// aprovou no e-mail do monitor (13/10/2026). Tudo vem de GET /api/siga; aqui so' se desenha.

const RELER_A_CADA_MS = 15 * 60_000;
const RELER_COM_ROBO_MS = 5_000;   // pedido na fila ou rodada em andamento (#343): a tela acompanha o robo
const dataOuTraco = (iso: string | null) => (iso ? fmtData(iso) : "—");

function Hoje({ n }: { n: number }) {
  if (n === 0) return <span className="sg__traco">—</span>;
  return (
    <span className="sg__hoje">
      <i className="sg__ponto sg__ponto--hoje" aria-hidden="true" />
      <span className="num">{n}</span>
      <span className="sr-only">, andou hoje</span>
    </span>
  );
}

function NoSetor({ p, agora }: { p: ProcessoSiga; agora: Date }) {
  const texto = tempoNoSetor(p, agora);
  const nivel = nivelDias(p.dias_uteis);
  if (nivel === null) return <span className="num">{texto}</span>;
  return <Selo classe={nivel === "acao" ? "selo--acao" : "selo--atencao"}>{texto}</Selo>;
}

function Linha({ p, agora, escolhido, aoEscolher, robo }: {
  p: ProcessoSiga; agora: Date; escolhido: boolean; aoEscolher: () => void; robo: Robo;
}) {
  const ligado = p.medicao_id !== null && p.contrato_id !== null;
  const volume = volumeDe(p.situacao);
  const ultima = p.ultima;
  const lendo = robo.rodada?.processos.includes(p.id) ?? false;
  const avisos = robo.avisos.filter(a => a.processo_id === p.id);
  return (
    <tr className="sg__linha" tabIndex={0} aria-selected={escolhido} aria-label={nomeDoProcesso(p)}
      onClick={ev => { if (!(ev.target as HTMLElement).closest("a")) aoEscolher(); }}
      onKeyDown={ev => { if (ev.target === ev.currentTarget && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); aoEscolher(); } }}>
      <td>
        {ligado ? (
          <>
            <span className="sg__nome">{p.obra}</span>{" "}
            <Link className="sg__link" para={{ tela: "medicao", obra: p.contrato_id as number, id: p.medicao_id as number }} secao="etapa-4">{p.medicao_titulo}</Link>
          </>
        ) : (
          <>
            <span className="sg__nome">{nomeDoProcesso(p)}</span>
            {p.obra && <span className="sg__fraco">{p.obra}</span>}
          </>
        )}
        {lendo && <span className="sg__fraco sg__lendo">lendo...</span>}
        {avisos.map((a, i) => <span key={i} className="sg__fraco sg__nao-lido">{a.texto}</span>)}
      </td>
      <td data-rotulo="Onde está">
        <span>{p.setor || "—"}</span>
        {p.caixa_entrada && <span className="sg__fraco">caixa de entrada</span>}
        {volume && <span className="sg__fraco">{volume}</span>}
      </td>
      <td data-rotulo="Com quem">{p.com_quem || <span className="sg__traco">—</span>}</td>
      <td data-rotulo="No setor há"><NoSetor p={p} agora={agora} /></td>
      <td className="col-num" data-rotulo="Hoje"><Hoje n={p.hoje} /></td>
      <td data-rotulo="Última ação">
        {ultima ? (
          <>
            <span className="num">{fmtData(ultima.data)}</span>{" "}
            <span>{tituloDoEvento(ultima.evento)}</span>
            {quemDaMovimentacao(ultima) && <span className="sg__fraco">{quemDaMovimentacao(ultima)}</span>}
          </>
        ) : <span className="sg__traco">—</span>}
      </td>
      <td className="num" data-rotulo="Protocolado">{dataOuTraco(p.protocolado_em)}</td>
    </tr>
  );
}

function Grupo({ titulo, processos, agora, atual, aoEscolher, robo }: {
  titulo: string; processos: ProcessoSiga[]; agora: Date; atual: number; aoEscolher: (id: number) => void; robo: Robo;
}) {
  if (processos.length === 0) return null;
  return (
    <tbody>
      <tr className="sg__faixa"><td colSpan={7}>{titulo}</td></tr>
      {processos.map(p => <Linha key={p.id} p={p} agora={agora} escolhido={p.id === atual} aoEscolher={() => aoEscolher(p.id)} robo={robo} />)}
    </tbody>
  );
}

function ItemMovimentacao({ m }: { m: Movimentacao }) {
  const destino = destinoDaMovimentacao(m);
  const quem = quemDaMovimentacao(m);
  return (
    <li className="sg__mov">
      <span className="num sg__mov-data">{fmtDataHora(m.data)}</span>
      <span className="sg__mov-evento">{tituloDoEvento(m.evento)}</span>
      {(quem || destino) && <span className="sg__fraco">{[quem, destino].filter(Boolean).join(" ")}</span>}
    </li>
  );
}

// "Atualizar processo" / "Atualizar todos" (#343): pedir leitura nao muda dado, entao quem ve a tela ve o botao (a
// diretoria tambem). Com pedido ou rodada que ja' cobre o clique, o botao mostra o estado e fica desabilitado.
function Atualizar({ rotulo, processoId, robo, aoPedir }: {
  rotulo: string; processoId: number | null; robo: Robo; aoPedir: () => Promise<void>;
}) {
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const situacao = situacaoDoBotao(robo, processoId);
  async function pedir() {
    setOcupado(true); setErro("");
    try {
      await api("/api/siga/atualizar", { method: "POST", body: JSON.stringify(processoId === null ? {} : { processo_id: processoId }) });
      await aoPedir();
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }
  return (
    <>
      <button type="button" className="btn btn--pequeno" disabled={ocupado || situacao !== null} onClick={() => void pedir()}>
        {situacao === "lendo" ? "Lendo..." : situacao === "na_fila" ? "Na fila" : rotulo}
      </button>
      {erro && <p className="erro sg__erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
    </>
  );
}

// No lugar do "Lido as" enquanto o robo trabalha: a rodada em andamento ou o pedido mais antigo na fila
function RoboAgora({ robo }: { robo: Robo }) {
  if (robo.rodada) {
    return (
      <p className="sg__lido sg__robo">
        <i className="sg__ponto sg__ponto--lendo" aria-hidden="true" />
        Robô lendo agora · começou às <span className="num">{fmtHora(robo.rodada.iniciada_em)}</span> · {robo.rodada.tipo === "automatica" ? "rodada automática" : "pedido feito na tela"}
      </p>
    );
  }
  const primeiro = robo.pedidos[0];
  if (!primeiro) return null;
  return <p className="sg__lido">Pedido de atualização às <span className="num">{fmtHora(primeiro.pedido_em)}</span>, aguardando o robô</p>;
}

function Painel({ p, dados, aoPedir }: { p: ProcessoSiga; dados: PainelSiga; aoPedir: () => Promise<void> }) {
  const movimentacoes = [...p.movimentacoes].sort((a, b) => Date.parse(b.data) - Date.parse(a.data));
  return (
    <aside className="sg__painel" id="painel-siga" aria-label="Detalhe do processo">
      <h2>{nomeDoProcesso(p)}</h2>
      {p.numero && <div className="num">{p.numero}</div>}
      {p.situacao && <div className="sg__situacao">{p.situacao}</div>}
      {(p.link || dados.pode_atualizar) && (
        <div className="sg__acoes">
          {p.link && (
            <a className="sg__link" href={p.link} target="_blank" rel="noopener noreferrer">
              Abrir no SIGA<IconeLinkExterno className="icone icone--p" />
            </a>
          )}
          {dados.pode_atualizar && <Atualizar rotulo="Atualizar processo" processoId={p.id} robo={dados.robo} aoPedir={aoPedir} />}
        </div>
      )}
      {movimentacoes.length > 0 && <ol className="sg__movs" aria-label="Movimentações">
        {movimentacoes.map((m, i) => <ItemMovimentacao key={`${m.data}-${i}`} m={m} />)}
      </ol>}
    </aside>
  );
}

// Link colado na tela SIGA (issue #339): processo sem medicao (aditivo, indenizatorio, avulso). O nome e' da
// pessoa, porque a pagina do SIGA nao mostra o titulo; a obra e' opcional. O servidor valida e responde em portugues.
function AcompanharProcesso({ aoGravar }: { aoGravar: (id: number) => Promise<void> }) {
  const [aberto, setAberto] = useState(false);
  const [link, setLink] = useState("");
  const [nome, setNome] = useState("");
  const [numero, setNumero] = useState("");
  const [obra, setObra] = useState("");
  const [obras, setObras] = useState<ObraLista[] | null>(null);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  useEffect(() => {
    if (!aberto || obras !== null) return;
    api<ObraLista[]>("/api/contratos")
      .then(lista => setObras([...lista].sort((a, b) => (a.nome_curto || a.numero_instrumento).localeCompare(b.nome_curto || b.numero_instrumento))))
      .catch(e => { setObras([]); setErro(mensagemDeErro(e)); });
  }, [aberto, obras]);

  async function enviar(ev: FormEvent) {
    ev.preventDefault();
    setOcupado(true); setErro("");
    try {
      const { id } = await api<{ id: number }>("/api/siga/processos-avulsos", { method: "POST", body: JSON.stringify({
        link: link.trim(), nome: nome.trim(), numero: numero.trim() || null, contrato_id: obra ? Number(obra) : null }) });
      await aoGravar(id);
      setAberto(false); setLink(""); setNome(""); setNumero(""); setObra("");
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }

  if (!aberto) return <button type="button" className="btn btn--pequeno" onClick={() => setAberto(true)}>Acompanhar processo</button>;
  return (
    <form className="form-inline sg__novo" onSubmit={enviar} aria-label="Acompanhar processo">
      <div className="campo">
        <label className="campo__rotulo" htmlFor="siga-link">Link do SIGA</label>
        <input id="siga-link" className="entrada--larga" autoComplete="off" spellCheck={false} maxLength={500} placeholder="https://…?n=…"
          value={link} onChange={e => setLink(e.target.value)} />
      </div>
      <div className="campo">
        <label className="campo__rotulo" htmlFor="siga-nome">Nome</label>
        <input id="siga-nome" className="entrada--media" autoComplete="off" maxLength={200} value={nome} onChange={e => setNome(e.target.value)} />
      </div>
      <div className="campo">
        <label className="campo__rotulo" htmlFor="siga-obra">Obra</label>
        <select id="siga-obra" value={obra} onChange={e => setObra(e.target.value)}>
          <option value="">Sem obra</option>
          {(obras ?? []).map(o => <option key={o.id} value={o.id}>{o.nome_curto || o.numero_instrumento}</option>)}
        </select>
      </div>
      <div className="campo">
        <label className="campo__rotulo" htmlFor="siga-numero">Nº do processo</label>
        <input id="siga-numero" name="numero" className="entrada--media" autoComplete="off" spellCheck={false} maxLength={100} placeholder="ORGAO-PRO-AAAA/NNNNN…"
          value={numero} onChange={e => setNumero(e.target.value)} />
      </div>
      <button type="submit" className="btn btn--primario" disabled={ocupado}>Acompanhar</button>
      <button type="button" className="btn btn--pequeno" onClick={() => { setAberto(false); setErro(""); }}>Cancelar</button>
      {erro && <p className="erro sg__erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
    </form>
  );
}

// ate' 1180 px o painel fica abaixo da lista: ao escolher um processo, leva a vista ate' ele
function irAoPainel() {
  if (window.matchMedia?.("(max-width: 1180px)").matches) document.getElementById("painel-siga")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

export default function SigaPagina({ busca, agora }: { busca: Busca; agora?: Date }) {
  const [dados, setDados] = useState<PainelSiga | null>(null);
  const [erro, setErro] = useState("");
  const [escolhido, setEscolhido] = useState<number | null>(() => (/^\d+$/.test(busca.processo ?? "") ? Number(busca.processo) : null));
  const carregar = useCallback(async () => {
    try { setDados(await api<PainelSiga>("/api/siga")); setErro(""); } catch (e) { setErro(mensagemDeErro(e)); }
  }, []);
  useEffect(() => { void carregar(); }, [carregar]);
  // O robo le a cada 15 minutos: com a aba aberta a tela rele no mesmo ritmo (a linha aberta e a busca ficam). Com
  // pedido na fila ou rodada em andamento, a cada 5 segundos, ate' a leitura nova chegar.
  const comRobo = (dados?.robo.estado ?? "parado") !== "parado";
  useEffect(() => {
    const relogio = window.setInterval(() => { void carregar(); }, comRobo ? RELER_COM_ROBO_MS : RELER_A_CADA_MS);
    return () => window.clearInterval(relogio);
  }, [carregar, comRobo]);

  const texto = busca.q ?? "";
  const { medicoes, outros } = useMemo(() => {
    const lista = ordenar((dados?.processos ?? []).filter(p => casaComBusca(p, texto)));
    return { medicoes: lista.filter(p => p.medicao_id !== null), outros: lista.filter(p => p.medicao_id === null) };
  }, [dados, texto]);

  if (!dados) {
    return (
      <div className="pagina">
        {erro
          ? <div className="form-inline"><p className="erro" role="alert"><IconeAlerta className="icone icone--p" />Não foi possível ler os processos do SIGA: {erro}</p>
              <button type="button" className="btn btn--pequeno" onClick={() => void carregar()}>Tentar de novo</button></div>
          : <p className="campo__nota">Carregando os processos…</p>}
      </div>
    );
  }
  // o processo novo nao pode sumir atras da busca: ela e' limpa ao gravar
  const gravado = async (id: number) => { await carregar(); trocarBusca({ q: null }); setEscolhido(id); };
  const robo = dados.robo;
  const topo = (
    <div className="sg__topo">
      <div aria-live="polite">
        {robo.estado !== "parado"
          ? <RoboAgora robo={robo} />
          : dados.lido_em && <p className="sg__lido">Lido às <span className="num">{fmtHora(dados.lido_em)}</span></p>}
      </div>
      {dados.atrasado && dados.lido_em && (
        <CaixaAviso nivel="atencao" role="status">O monitor do SIGA não lê desde {fmtData(dados.lido_em).slice(0, 5)} {fmtHora(dados.lido_em)}.</CaixaAviso>
      )}
      {dados.pode_atualizar && <Atualizar rotulo="Atualizar todos" processoId={null} robo={robo} aoPedir={carregar} />}
      <AcompanharProcesso aoGravar={gravado} />
      {robo.avisos.some(a => a.processo_id === null) && (
        <div className="sg__avisos">
          {robo.avisos.filter(a => a.processo_id === null).map((a, i) => (
            <CaixaAviso key={i} nivel="critico" role="alert">{a.texto}</CaixaAviso>
          ))}
        </div>
      )}
    </div>
  );
  if (dados.processos.length === 0) {
    return (
      <div className="pagina siga">
        {topo}
        <section className="sg__quadro"><div className="sg__vazio"><IconeSiga className="icone" /><p>Nenhum processo acompanhado.</p></div></section>
      </div>
    );
  }

  const agoraDe = agora ?? new Date();
  const visiveis = [...medicoes, ...outros];
  const atual = visiveis.find(p => p.id === escolhido) ?? visiveis[0];
  const escolher = (id: number) => { setEscolhido(id); irAoPainel(); };

  return (
    <div className="pagina siga">
      {topo}
      <div className="sg__busca-caixa">
        <label className="sr-only" htmlFor="siga-busca">Buscar obra</label>
        <input id="siga-busca" type="search" className="sg__busca" value={texto} placeholder="Buscar obra ou processo…" autoComplete="off"
          onChange={ev => trocarBusca({ q: ev.target.value || null })} />
      </div>
      {atual === undefined ? (
        <section className="sg__quadro"><div className="sg__vazio"><p>Nenhum processo encontrado.</p></div></section>
      ) : (
        <div className="sg">
          <section className="sg__quadro" aria-label="Processos no SIGA">
            <table className="sg__tabela" role="grid">
              <caption className="sr-only">Processos acompanhados no SIGA. Escolha um para ver as movimentações.</caption>
              <colgroup><col className="sg__c-proc" /><col className="sg__c-onde" /><col className="sg__c-quem" /><col className="sg__c-setor" /><col className="sg__c-hoje" /><col className="sg__c-ultima" /><col className="sg__c-prot" /></colgroup>
              <thead>
                <tr>
                  <th scope="col">Processo</th><th scope="col">Onde está</th><th scope="col">Com quem</th><th scope="col">No setor há</th>
                  <th scope="col" className="col-num">Hoje</th><th scope="col">Última ação</th><th scope="col">Protocolado</th>
                </tr>
              </thead>
              <Grupo titulo="Processos de medições" processos={medicoes} agora={agoraDe} atual={atual.id} aoEscolher={escolher} robo={robo} />
              <Grupo titulo="Outros processos" processos={outros} agora={agoraDe} atual={atual.id} aoEscolher={escolher} robo={robo} />
            </table>
          </section>
          <Painel key={atual.id} p={atual} dados={dados} aoPedir={carregar} />
        </div>
      )}
    </div>
  );
}
