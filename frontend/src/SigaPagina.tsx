import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api, mensagemDeErro } from "./api";
import CaixaAviso from "./CaixaAviso";
import { IconeAlerta, IconeLinkExterno, IconeSeta, IconeSiga } from "./icones";
import { Link } from "./Link";
import type { ObraLista } from "./listaObras";
import { ir, trocarBusca, type Busca } from "./rota";
import {
  contagemPorTipo, detalheDoEvento, ehEntradaNoSetorAtual, filtrarMovimentacoes, nivelDias, nomeDoProcesso, ordenar, periodoDe,
  DIAS_ACAO, DIAS_ATENCAO, roboAtivo, setorPessoa, situacaoDoBotao, tempoNoSetor, tituloDoEvento, TIPOS, volumeDe, type Movimentacao, type PainelSiga,
  type ProcessoSiga, type Robo, type TipoMovimentacao,
} from "./siga";
import { fmtData, fmtDataHora, fmtHora } from "./tempo";
import "./siga.css";

// Tela SIGA (#329; redesenho #512, aprovado pelo Leo em 06/11/2026): duas paginas. A principal e' uma tabela com a
// posicao atual de cada processo, do mais parado ao menos; clicar na linha abre o historico completo do processo
// (a mesma rota, com ?processo=<id>). Tudo vem de GET /api/siga; aqui so' se desenha.

const RELER_A_CADA_MS = 15 * 60_000;
const RELER_COM_ROBO_MS = 5_000;   // pedido na fila ou rodada em andamento (#343): a tela acompanha o robo
const dataOuTraco = (iso: string | null) => (iso ? fmtData(iso) : "—");

function NoSetor({ p, agora }: { p: ProcessoSiga; agora: Date }) {
  if (p.hoje > 0) return <span className="sg__dias sg__dias--hoje">hoje</span>;
  const nivel = nivelDias(p.dias_uteis);
  return <span className={`sg__dias${nivel ? ` sg__dias--${nivel}` : ""}`}>{tempoNoSetor(p, agora)}</span>;
}

const abrirHistorico = (id: number) => ir({ tela: "siga" }, { busca: { processo: String(id) } });

function Linha({ p, agora, robo }: { p: ProcessoSiga; agora: Date; robo: Robo }) {
  const ligado = p.medicao_id !== null && p.contrato_id !== null;
  const volume = volumeDe(p.situacao);
  const ultima = p.ultima;
  const lendo = robo.rodada?.processos.includes(p.id) ?? false;
  const avisos = robo.avisos.filter(a => a.processo_id === p.id);
  return (
    <tr className="sg__linha" tabIndex={0} aria-label={nomeDoProcesso(p)}
      onClick={() => abrirHistorico(p.id)}
      onKeyDown={ev => { if (ev.target === ev.currentTarget && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); abrirHistorico(p.id); } }}>
      <td>
        {ligado ? (
          <>
            <span className="sg__nome">{p.obra}</span>
            {p.medicao_titulo && <span className="sg__fraco">{p.medicao_titulo}</span>}
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
        <span className="sg__nome">{p.setor || "—"}</span>
        {p.caixa_entrada && <span className="sg__fraco">caixa de entrada</span>}
        {volume && <span className="sg__fraco">{volume}</span>}
      </td>
      <td data-rotulo="Com quem">{p.com_quem || <span className="sg__traco">—</span>}</td>
      <td data-rotulo="No setor há"><NoSetor p={p} agora={agora} /></td>
      <td data-rotulo="Última movimentação">
        {ultima ? (
          <>
            <span className="num">{fmtData(ultima.data).slice(0, 5)}</span>{" "}
            <span>{tituloDoEvento(ultima.evento)}</span>
          </>
        ) : <span className="sg__traco">—</span>}
      </td>
      <td className="num" data-rotulo="Protocolado em">{dataOuTraco(p.protocolado_em)}</td>
      <td className="sg__seta" aria-hidden="true"><IconeSeta className="icone" /></td>
    </tr>
  );
}

// "Atualizar processo" / "Atualizar todos" (#343): pedir leitura nao muda dado, entao quem ve a tela ve o botao.
// Com pedido ou rodada que ja' cobre o clique, o botao mostra o estado e fica desabilitado.
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
        {situacao === "lendo" ? "Lendo..." : ocupado || situacao === "na_fila" ? "Na fila" : rotulo}
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

const PASSO_HISTORICO = 30;
const PRIMEIRAS = 15;

// Pagina do historico de um processo (#512): todas as movimentacoes gravadas, com filtro por tipo e busca.
function Historico({ p, dados, aoPedir }: { p: ProcessoSiga; dados: PainelSiga; aoPedir: () => Promise<void> }) {
  const [tipo, setTipo] = useState<TipoMovimentacao | null>(null);
  const [texto, setTexto] = useState("");
  const [mostrando, setMostrando] = useState(PRIMEIRAS);
  const nome = nomeDoProcesso(p);
  const contagem = useMemo(() => contagemPorTipo(p.movimentacoes), [p.movimentacoes]);
  const lista = useMemo(() => filtrarMovimentacoes(p.movimentacoes, tipo, texto), [p.movimentacoes, tipo, texto]);
  const periodo = periodoDe(p.movimentacoes, fmtData);
  const total = p.movimentacoes.length;
  const escolher = (t: TipoMovimentacao | null) => { setTipo(t); setMostrando(PRIMEIRAS); };
  return (
    <div className="pagina siga sg-hist">
      <nav className="sg__trilha" aria-label="Você está em">
        <Link className="sg__link" para={{ tela: "siga" }}>SIGA</Link>
        <IconeSeta className="icone icone--p" />
        <span>{nome}</span>
        <IconeSeta className="icone icone--p" />
        <span aria-current="page">Histórico</span>
      </nav>
      <header className="sg__cabeca">
        <h1>Histórico · {nome}</h1>
        <p className="sg__sub">
          {[p.numero, `${total} ${total === 1 ? "movimentação" : "movimentações"}`, periodo].filter(Boolean).join(" · ")}
        </p>
        <div className="sg__acoes">
          {p.link && (
            <a className="btn btn--pequeno sg__abrir" href={p.link} target="_blank" rel="noopener noreferrer">
              Abrir no SIGA<IconeLinkExterno className="icone icone--p" />
            </a>
          )}
          {p.medicao_id !== null && p.contrato_id !== null && (
            <Link className="sg__link" para={{ tela: "medicao", obra: p.contrato_id, id: p.medicao_id }} secao="etapa-4">Ver a medição</Link>
          )}
          {dados.pode_atualizar && <Atualizar rotulo="Pedir leitura" processoId={p.id} robo={dados.robo} aoPedir={aoPedir} />}
        </div>
      </header>
      <div className="sg__filtros">
        <div className="sg__chips" role="group" aria-label="Tipo de movimentação">
          <button type="button" className="sg__chip" aria-pressed={tipo === null} onClick={() => escolher(null)}>
            Todas <span className="num">{total}</span>
          </button>
          {TIPOS.map(t => (
            <button key={t.tipo} type="button" className="sg__chip" aria-pressed={tipo === t.tipo} onClick={() => escolher(t.tipo)}>
              {t.rotulo} <span className="num">{contagem[t.tipo]}</span>
            </button>
          ))}
        </div>
        <label className="sr-only" htmlFor="siga-historico-busca">Buscar setor, pessoa ou documento</label>
        <input id="siga-historico-busca" type="search" className="sg__busca" value={texto} placeholder="Buscar setor, pessoa ou documento…"
          autoComplete="off" onChange={ev => { setTexto(ev.target.value); setMostrando(PRIMEIRAS); }} />
      </div>
      {lista.length === 0 ? (
        <section className="sg__quadro"><div className="sg__vazio"><p>{total === 0 ? "Nenhuma movimentação gravada." : "Nenhuma movimentação encontrada."}</p></div></section>
      ) : (
        <section className="sg__quadro" aria-label="Movimentações do processo">
          <table className="sg__tabela sg__tabela--hist">
            <caption className="sr-only">Movimentações do processo, da mais recente para a mais antiga.</caption>
            <thead>
              <tr><th scope="col">Data e hora</th><th scope="col">Evento</th><th scope="col">De (setor · pessoa)</th><th scope="col">Para (setor · pessoa)</th></tr>
            </thead>
            <tbody>
              {lista.slice(0, mostrando).map((m, i) => <LinhaMovimentacao key={`${m.data}-${i}`} m={m} destaque={ehEntradaNoSetorAtual(p, m)} />)}
            </tbody>
          </table>
          <p className="sg__rodape">
            Mostrando {Math.min(mostrando, lista.length)} de {lista.length}
            {mostrando < lista.length && <> · <button type="button" className="sg__mais" onClick={() => setMostrando(n => n + PASSO_HISTORICO)}>Ver mais</button></>}
          </p>
        </section>
      )}
    </div>
  );
}

function LinhaMovimentacao({ m, destaque }: { m: Movimentacao; destaque: boolean }) {
  const documento = detalheDoEvento(m.evento);
  return (
    <tr className={destaque ? "sg__mov--atual" : undefined} aria-current={destaque ? "true" : undefined}>
      <td className="num" data-rotulo="Data e hora">{fmtDataHora(m.data)}</td>
      <td>
        <span className="sg__nome">{tituloDoEvento(m.evento)}</span>
        {documento && <span className="sg__fraco">{documento}</span>}
      </td>
      <td data-rotulo="De">{setorPessoa(m.cad_lotacao, m.cad_pessoa) || <span className="sg__traco">—</span>}</td>
      <td data-rotulo="Para">{setorPessoa(m.at_lotacao, m.at_pessoa) || <span className="sg__traco">—</span>}</td>
    </tr>
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

export default function SigaPagina({ busca, agora }: { busca: Busca; agora?: Date }) {
  const [dados, setDados] = useState<PainelSiga | null>(null);
  const [erro, setErro] = useState("");
  const carregar = useCallback(async () => {
    try { setDados(await api<PainelSiga>("/api/siga")); setErro(""); } catch (e) { setErro(mensagemDeErro(e)); }
  }, []);
  useEffect(() => { void carregar(); }, [carregar]);
  // O robo le a cada 15 minutos: com a aba aberta a tela rele no mesmo ritmo. Com pedido na fila ou rodada em
  // andamento, a cada 5 segundos, ate' a leitura nova chegar (pedido travado nao conta).
  const comRobo = dados !== null && roboAtivo(dados.robo);
  useEffect(() => {
    const relogio = window.setInterval(() => { void carregar(); }, comRobo ? RELER_COM_ROBO_MS : RELER_A_CADA_MS);
    return () => window.clearInterval(relogio);
  }, [carregar, comRobo]);

  const processos = useMemo(() => ordenar(dados?.processos ?? []), [dados]);

  // processo que nao existe: sai o ?processo= da URL (a barra volta a ter o h1 da secao)
  const idPedido = /^\d+$/.test(busca.processo ?? "") ? Number(busca.processo) : null;
  const existe = dados !== null && idPedido !== null && dados.processos.some(p => p.id === idPedido);
  useEffect(() => {
    if (dados !== null && idPedido !== null && !existe) trocarBusca({ processo: null });
  }, [dados, idPedido, existe]);

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
  // ?processo=<id> abre o historico (o "Abrir" do aviso tambem); id que nao existe cai na tabela
  const aberto = /^\d+$/.test(busca.processo ?? "") ? processos.find(p => p.id === Number(busca.processo)) : undefined;
  if (aberto) return <Historico key={aberto.id} p={aberto} dados={dados} aoPedir={carregar} />;

  const robo = dados.robo;
  const n = processos.length;
  const topo = (
    <div className="sg__topo">
      <div className="sg__vivo" aria-live="polite">{robo.estado !== "parado" && <RoboAgora robo={robo} />}</div>
      {dados.atrasado && dados.lido_em && (
        <CaixaAviso nivel="atencao" role="status">O monitor do SIGA não lê desde {fmtData(dados.lido_em).slice(0, 5)} {fmtHora(dados.lido_em)}.</CaixaAviso>
      )}
      {dados.pode_atualizar && <Atualizar rotulo="Pedir leitura" processoId={null} robo={robo} aoPedir={carregar} />}
      <AcompanharProcesso aoGravar={carregar} />
      {robo.avisos.some(a => a.processo_id === null) && (
        <div className="sg__avisos">
          {robo.avisos.filter(a => a.processo_id === null).map((a, i) => (
            <CaixaAviso key={i} nivel="critico" role="alert">{a.texto}</CaixaAviso>
          ))}
        </div>
      )}
    </div>
  );
  const subtitulo = [`${n} ${n === 1 ? "processo" : "processos"}`, dados.lido_em ? `última leitura ${fmtHora(dados.lido_em)}` : null]
    .filter(Boolean).join(" · ");
  const cabeca = (
    <header className="sg__cabeca sg__cabeca--principal">
      <p className="sg__sub">{subtitulo}</p>
      <ul className="sg__legenda" aria-label="Cor do tempo no setor">
        <li><i className="sg__ponto sg__ponto--hoje" aria-hidden="true" />andou hoje</li>
        <li><i className="sg__ponto sg__ponto--atencao" aria-hidden="true" />parado há {DIAS_ATENCAO} dias úteis ou mais</li>
        <li><i className="sg__ponto sg__ponto--acao" aria-hidden="true" />{DIAS_ACAO} dias úteis ou mais</li>
      </ul>
    </header>
  );
  if (n === 0) {
    return (
      <div className="pagina siga">
        {cabeca}
        {topo}
        <section className="sg__quadro"><div className="sg__vazio"><IconeSiga className="icone" /><p>Nenhum processo acompanhado.</p></div></section>
      </div>
    );
  }

  const agoraDe = agora ?? new Date();
  return (
    <div className="pagina siga">
      {cabeca}
      {topo}
      <section className="sg__quadro" aria-label="Processos no SIGA">
        <table className="sg__tabela" role="grid">
          <caption className="sr-only">Processos acompanhados no SIGA, do mais parado ao menos. Escolha um para ver o histórico.</caption>
          <colgroup><col className="sg__c-proc" /><col className="sg__c-onde" /><col className="sg__c-quem" /><col className="sg__c-setor" /><col className="sg__c-ultima" /><col className="sg__c-prot" /><col className="sg__c-seta" /></colgroup>
          <thead>
            <tr>
              <th scope="col">Processo</th><th scope="col">Onde está</th><th scope="col">Com quem</th><th scope="col">No setor há</th>
              <th scope="col">Última movimentação</th><th scope="col">Protocolado em</th><th scope="col"><span className="sr-only">Abrir</span></th>
            </tr>
          </thead>
          <tbody>
            {processos.map(p => <Linha key={p.id} p={p} agora={agoraDe} robo={robo} />)}
          </tbody>
        </table>
      </section>
    </div>
  );
}
