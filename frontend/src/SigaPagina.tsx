import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api, mensagemDeErro } from "./api";
import CaixaAviso from "./CaixaAviso";
import { IconeAlerta, IconeLinkExterno, IconeSeta, IconeSiga } from "./icones";
import { Link } from "./Link";
import type { ObraLista } from "./listaObras";
import { FINAIS, tituloMedicao } from "./medicao";
import { ir, trocarBusca, type Busca } from "./rota";
import {
  CATEGORIAS, contagemPorTipo, detalheDoEvento, ehEntradaNoSetorAtual, filtrarMovimentacoes, nivelDias, nomeDoProcesso, ordenar, periodoDe, porCategoria,
  DIAS_ACAO, DIAS_ATENCAO, roboAtivo, ROTULO_ENCERRADO, setorPessoa, situacaoDoBotao, tempoNoSetor, tituloDoEvento, TIPOS, volumeDe, type Movimentacao, type PainelSiga,
  type ProcessoSiga, type Robo, type TipoMovimentacao,
} from "./siga";
import { fmtData, fmtDataHora, fmtHora } from "./tempo";
import "./siga.css";

// Tela SIGA (#329; redesenho #512, aprovado pelo Leo em 06/11/2026): duas paginas. A principal e' uma tabela com a
// posicao atual de cada processo, do mais parado ao menos; clicar na linha abre o historico completo do processo
// (a mesma rota, com ?processo=<id>). Tudo vem de GET /api/siga; aqui so' se desenha.
// #663: a tabela principal tem uma secao por categoria (Medicoes, Aditivos, Indenizatorios, Outros) e o nome do
// processo e' montado pelo sistema; quem edita cadastros corrige categoria, obra e complemento no historico.

const RELER_A_CADA_MS = 60 * 60_000;   // o robo le de hora em hora (#657)
const RELER_COM_ROBO_MS = 5_000;   // pedido na fila ou rodada em andamento (#343): a tela acompanha o robo
const dataOuTraco = (iso: string | null) => (iso ? fmtData(iso) : "—");

function NoSetor({ p, agora }: { p: ProcessoSiga; agora: Date }) {
  if (p.hoje > 0) return <span className="sg__dias sg__dias--hoje">hoje</span>;
  const nivel = nivelDias(p.dias_uteis);
  return <span className={`sg__dias${nivel ? ` sg__dias--${nivel}` : ""}`}>{tempoNoSetor(p, agora)}</span>;
}

const abrirHistorico = (id: number) => ir({ tela: "siga" }, { busca: { processo: String(id) } });

function Linha({ p, agora, robo }: { p: ProcessoSiga; agora: Date; robo: Robo }) {
  const volume = volumeDe(p.situacao);
  const ultima = p.ultima;
  const lendo = robo.rodada?.processos.includes(p.id) ?? false;
  // encerrado (#657): sem "nao lido" e sem cor de atraso; no lugar de "Com quem" e "No setor ha'", a situacao
  const avisos = p.encerrado ? [] : robo.avisos.filter(a => a.processo_id === p.id);
  return (
    <tr className="sg__linha" tabIndex={0} aria-label={nomeDoProcesso(p)}
      onClick={() => abrirHistorico(p.id)}
      onKeyDown={ev => { if (ev.target === ev.currentTarget && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); abrirHistorico(p.id); } }}>
      <td>
        {p.obra ? (
          <>
            <span className="sg__nome">{p.obra}</span>
            <span className="sg__fraco">{p.o_que_e}</span>
          </>
        ) : <span className="sg__nome">{nomeDoProcesso(p)}</span>}
        {lendo && <span className="sg__fraco sg__lendo">lendo...</span>}
        {avisos.map((a, i) => <span key={i} className="sg__fraco sg__nao-lido">{a.texto}</span>)}
      </td>
      <td data-rotulo="Onde está">
        <span className="sg__nome">{p.setor || "—"}</span>
        {p.caixa_entrada && <span className="sg__fraco">caixa de entrada</span>}
        {volume && <span className="sg__fraco">{volume}</span>}
      </td>
      {p.encerrado ? <td data-rotulo="Situação">{ROTULO_ENCERRADO[p.encerrado]}</td> : (
        <>
          <td data-rotulo="Com quem">{p.com_quem || <span className="sg__traco">—</span>}</td>
          <td data-rotulo="No setor há"><NoSetor p={p} agora={agora} /></td>
        </>
      )}
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
function Historico({ p, dados, aoPedir, podeEditar }: { p: ProcessoSiga; dados: PainelSiga; aoPedir: () => Promise<void>; podeEditar: boolean }) {
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
          {/* o processo de protocolo enviado pelo sistema e' sempre Medicoes: nao ha' o que corrigir */}
          {podeEditar && p.protocolo_id === null && <CorrigirCategoria p={p} aoGravar={aoPedir} />}
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

// Categoria, obra, medicao e complemento (#663): os mesmos campos em "Acompanhar processo" e em "Corrigir categoria".
// Medicao so' na categoria Medicoes, com as medicoes abertas da obra; nela nao ha' complemento (o nome e' o titulo da
// medicao). O servidor valida e responde em portugues.
type Classificacao = { categoria: string; obra: string; medicao: string; complemento: string };
type MedicaoDaObra = { id: number; numero: number; tipo: string; estado: string };

const corpoDa = (c: Classificacao) => ({
  categoria: c.categoria, contrato_id: c.obra ? Number(c.obra) : null,
  medicao_id: c.categoria === "medicoes" && c.medicao ? Number(c.medicao) : null,
  complemento: c.categoria === "medicoes" ? null : c.complemento.trim() || null,
});

function useObras(aberto: boolean, aoFalhar: (erro: string) => void) {
  const [obras, setObras] = useState<ObraLista[] | null>(null);
  useEffect(() => {
    if (!aberto || obras !== null) return;
    api<ObraLista[]>("/api/contratos")
      .then(lista => setObras([...lista].sort((a, b) => (a.nome_curto || a.numero_instrumento).localeCompare(b.nome_curto || b.numero_instrumento))))
      .catch(e => { setObras([]); aoFalhar(mensagemDeErro(e)); });
  }, [aberto, obras, aoFalhar]);
  return obras ?? [];
}

function CamposCategoria({ id, valor, mudar, obras, aoFalhar }: {
  id: string; valor: Classificacao; mudar: (v: Classificacao) => void; obras: ObraLista[]; aoFalhar: (erro: string) => void;
}) {
  const [medicoes, setMedicoes] = useState<{ obra: string; lista: MedicaoDaObra[] } | null>(null);
  const pedeMedicao = valor.categoria === "medicoes" && valor.obra !== "";
  const obra = valor.obra;
  useEffect(() => {
    if (!pedeMedicao) return;
    let vale = true;
    api<MedicaoDaObra[]>(`/api/contratos/${obra}/medicoes`)
      .then(lista => { if (vale) setMedicoes({ obra, lista }); })
      .catch(e => { if (vale) { setMedicoes({ obra, lista: [] }); aoFalhar(mensagemDeErro(e)); } });
    return () => { vale = false; };
  }, [pedeMedicao, obra, aoFalhar]);
  // as abertas da obra; a medicao ja' ligada ao processo continua na lista mesmo depois de recebida
  const abertas = (medicoes?.obra === obra ? medicoes.lista : []).filter(m => !FINAIS.includes(m.estado) || String(m.id) === valor.medicao);
  return (
    <>
      <div className="campo">
        <label className="campo__rotulo" htmlFor={`${id}-categoria`}>Categoria</label>
        <select id={`${id}-categoria`} value={valor.categoria} onChange={e => mudar({ ...valor, categoria: e.target.value, medicao: "" })}>
          <option value="">Escolha</option>
          {CATEGORIAS.map(c => <option key={c.categoria} value={c.categoria}>{c.rotulo}</option>)}
        </select>
      </div>
      <div className="campo">
        <label className="campo__rotulo" htmlFor={`${id}-obra`}>Obra</label>
        <select id={`${id}-obra`} value={valor.obra} onChange={e => mudar({ ...valor, obra: e.target.value, medicao: "" })}>
          <option value="">Sem obra</option>
          {obras.map(o => <option key={o.id} value={o.id}>{o.nome_curto || o.numero_instrumento}</option>)}
        </select>
      </div>
      {valor.categoria === "medicoes" ? (
        <div className="campo">
          <label className="campo__rotulo" htmlFor={`${id}-medicao`}>Medição</label>
          <select id={`${id}-medicao`} value={valor.medicao} onChange={e => mudar({ ...valor, medicao: e.target.value })}>
            <option value="">Escolha</option>
            {abertas.map(m => <option key={m.id} value={m.id}>{tituloMedicao(m)}</option>)}
          </select>
        </div>
      ) : (
        <div className="campo">
          <label className="campo__rotulo" htmlFor={`${id}-complemento`}>Complemento</label>
          <input id={`${id}-complemento`} className="entrada--media" autoComplete="off" maxLength={100} placeholder="de prazo"
            value={valor.complemento} onChange={e => mudar({ ...valor, complemento: e.target.value })} />
        </div>
      )}
    </>
  );
}

const SEM_CLASSIFICACAO: Classificacao = { categoria: "", obra: "", medicao: "", complemento: "" };

// Link colado na tela SIGA (issue #339; formulario da #663): ninguem digita o nome, o sistema monta a partir da
// categoria, da obra, da medicao e do complemento.
function AcompanharProcesso({ aoGravar }: { aoGravar: (id: number) => Promise<void> }) {
  const [aberto, setAberto] = useState(false);
  const [link, setLink] = useState("");
  const [valor, setValor] = useState(SEM_CLASSIFICACAO);
  const [erro, setErro] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const obras = useObras(aberto, setErro);

  async function enviar(ev: FormEvent) {
    ev.preventDefault();
    setOcupado(true); setErro("");
    try {
      const { id } = await api<{ id: number }>("/api/siga/processos-avulsos", { method: "POST", body: JSON.stringify({
        link: link.trim(), ...corpoDa(valor) }) });
      await aoGravar(id);
      setAberto(false); setLink(""); setValor(SEM_CLASSIFICACAO);
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }

  if (!aberto) return <button type="button" className="btn btn--pequeno" onClick={() => setAberto(true)}>Acompanhar processo</button>;
  return (
    <form className="form-inline sg__novo" onSubmit={enviar} aria-label="Acompanhar processo">
      <CamposCategoria id="siga" valor={valor} mudar={setValor} obras={obras} aoFalhar={setErro} />
      <div className="campo">
        <label className="campo__rotulo" htmlFor="siga-link">Link do SIGA</label>
        <input id="siga-link" className="entrada--larga" autoComplete="off" spellCheck={false} maxLength={500} placeholder="https://…?n=…"
          value={link} onChange={e => setLink(e.target.value)} />
      </div>
      <button type="submit" className="btn btn--primario" disabled={ocupado}>Acompanhar</button>
      <button type="button" className="btn btn--pequeno" onClick={() => { setAberto(false); setErro(""); }}>Cancelar</button>
      {erro && <p className="erro sg__erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
    </form>
  );
}

// Pagina do historico (#663): quem edita cadastros corrige categoria, obra e complemento do processo; passando a
// Medicoes, liga o processo a uma medicao da obra.
function CorrigirCategoria({ p, aoGravar }: { p: ProcessoSiga; aoGravar: () => Promise<void> }) {
  const atual = (): Classificacao => ({
    categoria: p.categoria, obra: p.contrato_id === null ? "" : String(p.contrato_id),
    medicao: p.medicao_id === null ? "" : String(p.medicao_id), complemento: p.complemento ?? "" });
  const [aberto, setAberto] = useState(false);
  const [valor, setValor] = useState(atual);
  const [erro, setErro] = useState("");
  const [gravado, setGravado] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const obras = useObras(aberto, setErro);

  async function enviar(ev: FormEvent) {
    ev.preventDefault();
    setOcupado(true); setErro("");
    try {
      await api(`/api/siga/processos/${p.id}/classificacao`, { method: "POST", body: JSON.stringify(corpoDa(valor)) });
      await aoGravar();
      setAberto(false); setGravado(true);
    } catch (e) { setErro(mensagemDeErro(e)); } finally { setOcupado(false); }
  }

  if (!aberto) {
    return (
      <>
        <button type="button" className="btn btn--pequeno" onClick={() => { setValor(atual()); setGravado(false); setAberto(true); }}>Corrigir categoria</button>
        <span className="sg__gravado" role="status">{gravado ? "Categoria gravada." : ""}</span>
      </>
    );
  }
  return (
    <form className="form-inline sg__novo" onSubmit={enviar} aria-label="Corrigir categoria">
      <CamposCategoria id="siga-corrigir" valor={valor} mudar={setValor} obras={obras} aoFalhar={setErro} />
      <button type="submit" className="btn btn--primario" disabled={ocupado}>Salvar</button>
      <button type="button" className="btn btn--pequeno" onClick={() => { setAberto(false); setErro(""); }}>Cancelar</button>
      {erro && <p className="erro sg__erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>}
    </form>
  );
}

export default function SigaPagina({ busca, agora, podeEditar = true }: { busca: Busca; agora?: Date; podeEditar?: boolean }) {
  const [dados, setDados] = useState<PainelSiga | null>(null);
  const [erro, setErro] = useState("");
  const carregar = useCallback(async () => {
    try { setDados(await api<PainelSiga>("/api/siga")); setErro(""); } catch (e) { setErro(mensagemDeErro(e)); }
  }, []);
  useEffect(() => { void carregar(); }, [carregar]);
  // O robo le de hora em hora (#657): com a aba aberta a tela rele no mesmo ritmo. Com pedido na fila ou rodada em
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
  if (aberto) return <Historico key={aberto.id} p={aberto} dados={dados} aoPedir={carregar} podeEditar={podeEditar} />;

  const robo = dados.robo;
  // #657: a tabela principal so' tem os vivos; os encerrados ficam recolhidos no fim da pagina
  const vivos = processos.filter(p => p.encerrado === null);
  const encerrados = processos.filter(p => p.encerrado !== null);
  const n = vivos.length;
  const topo = (
    <div className="sg__topo">
      <div className="sg__vivo" aria-live="polite">{robo.estado !== "parado" && <RoboAgora robo={robo} />}</div>
      {dados.atrasado && dados.lido_em && (
        <CaixaAviso nivel="atencao" role="status">O monitor do SIGA não lê desde {fmtData(dados.lido_em).slice(0, 5)} {fmtHora(dados.lido_em)}.</CaixaAviso>
      )}
      {dados.pode_atualizar && <Atualizar rotulo="Pedir leitura" processoId={null} robo={robo} aoPedir={carregar} />}
      {podeEditar && <AcompanharProcesso aoGravar={carregar} />}
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
  const agoraDe = agora ?? new Date();
  const vazio = processos.length === 0 ? "Nenhum processo acompanhado." : "Nenhum processo em andamento.";
  return (
    <div className="pagina siga">
      {cabeca}
      {topo}
      {n === 0 ? (
        <section className="sg__quadro"><div className="sg__vazio"><IconeSiga className="icone" /><p>{vazio}</p></div></section>
      ) : (
        <section className="sg__quadro" aria-label="Processos no SIGA">
          <table className="sg__tabela" role="grid">
            <caption className="sr-only">Processos acompanhados no SIGA, por categoria, do mais parado ao menos. Escolha um para ver o histórico.</caption>
            <colgroup><col className="sg__c-proc" /><col className="sg__c-onde" /><col className="sg__c-quem" /><col className="sg__c-setor" /><col className="sg__c-ultima" /><col className="sg__c-prot" /><col className="sg__c-seta" /></colgroup>
            <thead>
              <tr>
                <th scope="col">Processo</th><th scope="col">Onde está</th><th scope="col">Com quem</th><th scope="col">No setor há</th>
                <th scope="col">Última movimentação</th><th scope="col">Protocolado em</th><th scope="col"><span className="sr-only">Abrir</span></th>
              </tr>
            </thead>
            {porCategoria(vivos).map(s => (
              <tbody key={s.categoria} aria-label={s.rotulo}>
                <tr className="sg__secao"><th colSpan={7} scope="rowgroup">{s.rotulo}</th></tr>
                {s.processos.map(p => <Linha key={p.id} p={p} agora={agoraDe} robo={robo} />)}
              </tbody>
            ))}
          </table>
        </section>
      )}
      {encerrados.length > 0 && (
        <details className="sg__encerrados" aria-label="Encerrados">
          <summary>Encerrados <span className="num">{encerrados.length}</span></summary>
          <section className="sg__quadro">
            <table className="sg__tabela">
              <caption className="sr-only">Processos encerrados: medição recebida ou processo arquivado. Escolha um para ver o histórico.</caption>
              <colgroup><col className="sg__c-proc-enc" /><col className="sg__c-onde-enc" /><col className="sg__c-sit" /><col className="sg__c-ultima-enc" /><col className="sg__c-prot" /><col className="sg__c-seta" /></colgroup>
              <thead>
                <tr>
                  <th scope="col">Processo</th><th scope="col">Onde está</th><th scope="col">Situação</th>
                  <th scope="col">Última movimentação</th><th scope="col">Protocolado em</th><th scope="col"><span className="sr-only">Abrir</span></th>
                </tr>
              </thead>
              <tbody>
                {encerrados.map(p => <Linha key={p.id} p={p} agora={agoraDe} robo={robo} />)}
              </tbody>
            </table>
          </section>
        </details>
      )}
    </div>
  );
}
