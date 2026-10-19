import { useEffect, useMemo, useRef, useState } from "react";
import { SELO, semObra, type Aviso, type Nivel } from "./Alertas";
import { api, mensagemDeErro } from "./api";
import AvisosPagina from "./AvisosPagina";
import { STATUS, type StatusObra } from "./ContratoPagina";
import { IconeAlerta } from "./icones";
import {
  avisoPrincipal, avisosParaLeitor, avisosPorObra, cDaUrlAntiga, classePrazo, contagemObras, contratanteDaObra, contratantesDe, ehDoContratante, escopoDaUrl, filtrarObras,
  nivelDoPrazo, nomeDaObra, pctExecutado, prazoDaObra, quandoVence, resumoContratante, rotuloCriticos,
  type ObraLista, type PrazoObra, type ResumoContratante,
} from "./listaObras";
import { fmtDias } from "./formato";
import { brl } from "./Medicoes";
import { trocarBusca, type Busca, type Ir } from "./rota";
import { Link } from "./Link";
import { fmtDataPura } from "./tempo";
import Rolagem from "./Rolagem";
import Selo from "./Selo";
import { Migalhas } from "./Topo";
import "./obras.css";

// Obras (NAVEGACAO.md › Obras), redesenho aprovado pelo Leo em 16/10/2026 (#159). Duas telas no mesmo endereco:
//  1. a ESCOLHA DO CONTRATANTE (o orgao do cadastro, pela sigla de Medicoes): uma linha larga por contratante, com o numero de obras, o % executado,
//     os avisos e o saldo a executar; a primeira linha, "Todas as obras", e' a soma das outras;
//  2. a LISTA DE OBRAS do contratante, em cartoes (ou na tabela de antes), com os Avisos abrindo na propria pagina.
// Valores cheios. O estado de cada tela fica na URL: ?c=<orgao> | todas, ?q=, ?termina=90|180, ?situacao=todas (com as
// encerradas), ?ver=tabela, ?avisos=1 (+ ?agrupar= ?familia= ?nivel= ?obra=, dos Avisos). Os links de antes (?orgao=,
// ?termina=, ?q=) seguem abrindo. O nome da empresa vem de /api/entidades, pelo id que a lista ja' manda; os avisos, do
// /api/inicio. O cadastro (contrato, aditivo, entidade) e' editado pelo Leonardo em arquivo (`cadastro/*.yaml` +
// `python -m app.cli cadastro aplicar`); a tela so' mostra.

type Entidade = { id: number; nome: string; nome_curto?: string | null };

function status(c: ObraLista): StatusObra {
  return (c.estado === "ativo" && c.encerramento_iniciado_em ? "em_encerramento" : c.estado) as StatusObra;
}

const obrasN = (k: number) => (k === 1 ? "1 obra" : `${k} obras`);

/** O fim (execucao ou vigencia) com os dias do servidor embaixo, na palavra dos Avisos ("vence em N dias", "vence
 *  hoje", "venceu ha' N dias") e na cor do nivel do aviso da obra (`nivel`; sem aviso, neutro). Obra paralisada
 *  (`paralisada`, so' na execucao): "Paralisada desde DD/MM/AAAA" em Atencao, sem contar o vencimento (D16). */
function Fim({ fim, dias, automatica, nivel: nivelDoAviso = null, aberta = true, paralisada }: {
  fim?: string | null; dias?: number | null; automatica?: boolean; nivel?: Nivel | null; aberta?: boolean;
  paralisada?: { desde: string | null };
}) {
  if (!fim && !paralisada) return <>—</>;
  // o nivel tambem vai em forma (triangulo no Critico, ponto na Atencao), nao so' na cor (F-58)
  const nivel = nivelDoPrazo(nivelDoAviso, dias, aberta);
  return (
    <>
      {fim ? fmtDataPura(fim.slice(0, 10)) : "—"}
      {paralisada ? (
        <div className="campo__nota prazo--atencao prazo--paralisada">
          {paralisada.desde ? <>Paralisada desde <span className="sem-quebra">{fmtDataPura(paralisada.desde.slice(0, 10))}</span></> : "Paralisada"}
        </div>
      ) : fim && dias !== null && dias !== undefined && (
        <div className={`campo__nota prazo--data${classePrazo(nivel)}`}>
          {nivel === "critico" ? <IconeAlerta className="icone icone--p" /> : nivel ? <span className="prazo__ponto" aria-hidden="true" /> : null}
          {quandoVence(dias)}
        </div>
      )}
      {fim && automatica && <div className="campo__nota">o órgão prorroga junto</div>}
    </>
  );
}

/** A coluna Avisos da tabela: a contagem; com critico, "N críticos" no selo do nivel (triangulo + palavra) e o total
 *  embaixo. Leva aos Avisos da obra, abertos nesta mesma pagina. */
function AvisosDaObra({ obra, prazo, busca }: { obra: ObraLista; prazo: PrazoObra; busca: Busca }) {
  const c = prazo.criticos;
  return (
    <>
      <Link para={{ tela: "obras" }} busca={{ ...busca, avisos: "1", obra: String(obra.id) }}>
        <span aria-hidden="true">{c > 0 ? <Selo classe="selo--acao" title={rotuloCriticos(c)}>{c}<span className="criticos__palavra">{c === 1 ? " crítico" : " críticos"}</span></Selo> : prazo.total}</span>
        <span className="sr-only">{avisosParaLeitor(prazo, nomeDaObra(obra))}</span>
      </Link>
      {c > 0 && prazo.total > c && <div className="campo__nota sem-quebra" aria-hidden="true">de {prazo.total}{" "}avisos</div>}
    </>
  );
}

function Chevron() {
  return (
    <svg className="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
  );
}

/** Uma linha larga da escolha do contratante: nome e numero de obras, % executado com barra, saldo a executar e avisos. */
function LinhaContratante({ nome, r, c, todas = false, comAvisos }: { nome: string; r: ResumoContratante; c: string; todas?: boolean; comAvisos: boolean }) {
  const nivel = r.nivelMax;
  return (
    <li>
      <Link className={`cartao contratante${todas ? " contratante--todas" : ""}`} para={{ tela: "obras" }} busca={{ c }}>
        <div>
          <p className="contratante__nome">{nome}</p>
          <span className="contratante__obras num">{obrasN(r.obras)}</span>
          {r.encerradas > 0 && <span className="campo__nota"> · {r.encerradas === 1 ? "1 encerrada" : `${r.encerradas} encerradas`}</span>}
        </div>
        <div className="contratante__exec">
          <div className="contratante__pct"><strong>{r.pct}%</strong><span>executado</span></div>
          <div className="progresso" role="img" aria-label={`${r.pct}% executado`}><span className="progresso__barra" style={{ width: `${Math.min(100, Math.max(0, r.pct))}%` }} /></div>
        </div>
        <div className="contratante__saldo">
          <span className="contratante__rotulo">Saldo a executar (valor cheio)</span>
          <span className="contratante__valor">{brl(r.saldo)}</span>
        </div>
        <div className="contratante__avisos">
          {!comAvisos ? <span className="campo__nota">—</span> : r.comAviso > 0 && nivel ? (
            <>
              <span className={`ponto ponto--${nivel}`} aria-hidden="true" />
              <span>
                <span className={`texto--${nivel}`}>{r.comAviso} com aviso</span>
                {r.criticos > 0 ? <span className="campo__nota">{rotuloCriticos(r.criticos)}</span>
                  : <span className="campo__nota">o mais grave: {SELO[nivel].rotulo.toLowerCase()}</span>}
              </span>
            </>
          ) : <span className="campo__nota">sem avisos</span>}
        </div>
        <Chevron />
      </Link>
    </li>
  );
}

/** O cartao de uma obra: nome, orgao, % executado em destaque, uma linha de aviso (quando ha') e o termino. */
function CartaoObra({ obra, avisos, ir }: { obra: ObraLista; avisos: Aviso[]; ir: Ir }) {
  const st = status(obra);
  const s = STATUS[st] ?? { rotulo: obra.estado, classe: "" };
  const pct = pctExecutado(obra);
  const principal = avisoPrincipal(avisos);
  const nivelP: Nivel = principal && SELO[principal.nivel] ? principal.nivel : "atencao";   // nivel novo do servidor conta como atencao
  const fim = obra.execucao_fim_vigente ? fmtDataPura(obra.execucao_fim_vigente.slice(0, 10)) : null;
  const paralisada = prazoDaObra(obra, avisos).paralisada;
  const termino = !fim ? "sem data de término"
    : obra.estado === "encerrado" ? `terminou em ${fim}`
    : paralisada ? `termina em ${fim}, com o prazo parado` : `termina em ${fim}`;
  return (
    <li>
      <Link className="cartao obra-cartao" para={{ tela: "obra", id: obra.id, aba: "medicoes" }} ir={ir}>
        <div className="obra-cartao__cabeca">
          <h2 className="obra-cartao__nome">{nomeDaObra(obra)}</h2>
          {st !== "ativo" && <Selo classe={s.classe}>{s.rotulo}</Selo>}
        </div>
        <span className="obra-cartao__orgao">{obra.orgao}</span>
        <div className="obra-cartao__pct">
          <strong>{pct === null ? "—" : `${pct}%`}</strong><span>executado</span>
        </div>
        {principal && (
          <p className={`obra-cartao__linha texto--${nivelP}`}>
            <span className={`ponto ponto--${nivelP}`} aria-hidden="true" />
            <span>
              <span className="sr-only">{SELO[nivelP].rotulo}: </span>
              {semObra(principal).mensagem}
              {avisos.length > 1 && <span className="obra-cartao__mais"> · mais {avisos.length - 1}</span>}
            </span>
          </p>
        )}
        <p className="obra-cartao__linha obra-cartao__linha--fim">
          <svg className="icone icone--p" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="17" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></svg>
          <span>{termino}</span>
        </p>
      </Link>
    </li>
  );
}

export default function Contratos({ ir, busca = {}, perfil = "engenharia" }: { ir: Ir; busca?: Busca; perfil?: string }) {
  const [lista, setLista] = useState<ObraLista[] | null>(null);
  const [empresas, setEmpresas] = useState<Map<number, string> | null>(new Map());
  const [avisos, setAvisos] = useState<Aviso[] | null | undefined>(undefined);
  const [erro, setErro] = useState("");

  useEffect(() => {
    let vivo = true;
    api<ObraLista[]>("/api/contratos").then(l => { if (vivo) setLista(l); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    // o nome da empresa e o numero de avisos completam a linha; sem eles, a lista continua
    api<Entidade[]>("/api/entidades")
      .then(l => { if (vivo) setEmpresas(new Map(l.map(e => [e.id, e.nome_curto || e.nome]))); })
      .catch(() => { if (vivo) setEmpresas(null); });
    api<{ avisos: Aviso[] }>("/api/inicio").then(d => { if (vivo) setAvisos(d.avisos); })
      .catch(() => { if (vivo) setAvisos(null); });
    return () => { vivo = false; };
  }, []);

  const { escolha, orgao } = escopoDaUrl(busca);
  // link de antes (?termina=, ?q=, ?orgao=...): a URL ganha o `c`, e limpar o ultimo filtro nao volta a escolha
  const cAntigo = cDaUrlAntiga(busca);
  useEffect(() => { if (cAntigo !== null) trocarBusca({ c: cAntigo, orgao: null }); }, [cAntigo]);
  const todas = busca.situacao === "todas";
  const termina = busca.termina === "90" ? 90 : busca.termina === "180" ? 180 : null;
  const q = busca.q ?? "";
  const tabela = busca.ver === "tabela";
  const avisosAbertos = busca.avisos === "1";
  const [texto, setTexto] = useState(q);
  const espera = useRef<number | undefined>(undefined);
  const botaoAvisos = useRef<HTMLButtonElement>(null);
  // a URL mudou por fora (Voltar, "Limpar os filtros"): o campo acompanha, menos enquanto a pessoa digita nele
  useEffect(() => { if (document.activeElement?.id !== "obras-busca") setTexto(q); }, [q]);
  useEffect(() => () => window.clearTimeout(espera.current), []);
  const digitar = (v: string) => {
    setTexto(v);
    window.clearTimeout(espera.current);
    espera.current = window.setTimeout(() => trocarBusca({ q: v || null }), 300);
  };
  const temFiltro = Object.keys(busca).some(k => ["termina", "q"].includes(k));
  // o link da coluna Avisos da tabela (?avisos=1&obra=N) abre o painel acima da lista: leva a pagina ate' ele
  const verAvisosDaObra = avisosAbertos && !!busca.obra && lista !== null;
  useEffect(() => {
    if (verAvisosDaObra) document.getElementById("avisos-area")?.scrollIntoView?.({ block: "start" });
  }, [verAvisosDaObra, busca.obra]);

  const porObra = useMemo(() => (avisos ? avisosPorObra(avisos) : null), [avisos]);
  // as obras do contratante (ou todas); os avisos do recorte sao os dessas obras (e, em "Todas", tambem os sem obra)
  const doContratante = useMemo(() => (lista ?? []).filter(o => !orgao || ehDoContratante(o, orgao)), [lista, orgao]);
  const idsDoContratante = useMemo(() => (orgao ? new Set(doContratante.map(o => o.id)) : null), [orgao, doContratante]);
  const avisosDoRecorte = (avisos ?? []).filter(a => idsDoContratante === null || (a.contrato_id !== null && idsDoContratante.has(a.contrato_id)));

  // o prazo de cada obra, lido dos avisos ja' carregados; a paralisada nao conta o vencimento da execucao (D16)
  const prazos = new Map(doContratante.map(o => [o.id, prazoDaObra(o, porObra?.get(o.id))] as const));
  const paralisadas = new Set([...prazos].filter(([, p]) => p.paralisada).map(([id]) => id));
  const filtradas = filtrarObras(doContratante, { todas, termina, q, paralisadas, empresas });
  const { titulo, detalhe } = contagemObras(filtradas.length, doContratante.length, { todas, termina, orgao: null, q });
  const aqui = { tela: "obras" as const };
  const com = (m: Record<string, string | null>): Busca => {
    const b: Busca = { ...busca };
    for (const [k, v] of Object.entries(m)) { if (v === null) delete b[k]; else b[k] = v; }
    return b;
  };

  const nomeLista = orgao ?? "Todas as obras";
  const contratantes = lista ? contratantesDe(lista) : [];
  const total = resumoContratante(lista ?? [], porObra);
  const resumo = resumoContratante(doContratante, porObra);
  const meta = !lista ? "" : escolha
    ? `${contratantes.length === 1 ? "1 contratante" : `${contratantes.length} contratantes`} · ${total.obras} ${total.obras === 1 ? "obra em andamento" : "obras em andamento"}`
    : `${obrasN(resumo.obras)} · ${resumo.pct}% executado · saldo a executar (valor cheio) ${brl(resumo.saldo)}`;
  const nAvisosLabel = avisos ? ` (${escolha ? avisos.length : avisosDoRecorte.length})` : "";

  return (
    <>
      <header className="topbar topbar--detalhe">
        <div className="topbar__trilha">
          <Migalhas itens={escolha ? [{ rotulo: "Início", para: { tela: "inicio" } }, { rotulo: "Obras" }]
            : [{ rotulo: "Obras", para: aqui }, { rotulo: nomeLista }]} />
        </div>
        <div className="topbar__linha topbar__linha--quebra">
          <h1 className="topbar__titulo topbar__titulo--grande">{escolha ? "Contratantes" : nomeLista}</h1>
          {meta && <span className="topbar__meta num" title={meta}>{meta}</span>}
          {escolha && (
            <div className="topbar__acoes">
              <Link className="btn btn--pequeno" para={aqui} busca={{ c: "todas", avisos: "1" }}>Avisos{nAvisosLabel}</Link>
            </div>
          )}
        </div>
      </header>
      <div className="pagina">
        {!lista && !erro && <div className="vazio"><p>Carregando as obras…</p></div>}
        {erro && <p className="erro" role="alert">
          <IconeAlerta className="icone icone--p" />{erro} Recarregue a página para tentar de novo.
        </p>}
        {/* o "—" da empresa e dos avisos nao pode querer dizer "falhou": a falha e' dita aqui */}
        {lista && (empresas === null || avisos === null) && (
          <p className="campo__nota" role="alert">
            Não foi possível carregar {[empresas === null && "os nomes das empresas", avisos === null && "os avisos"].filter(Boolean).join(" nem ")};
            recarregue a página para tentar de novo.
          </p>
        )}

        {lista && escolha && (
          <>
            {lista.length === 0 ? (
              <section className="cartao"><div className="vazio vazio--curto"><p className="vazio__titulo">Nenhuma obra no cadastro.</p></div></section>
            ) : (
              <ul className="contratantes" aria-label="Escolha o contratante">
                <LinhaContratante nome="Todas as obras" r={total} c="todas" todas comAvisos={avisos !== null} />
                {contratantes.map(nome => (
                  <LinhaContratante key={nome} nome={nome} r={resumoContratante(lista.filter(o => contratanteDaObra(o) === nome), porObra)} c={nome} comAvisos={avisos !== null} />
                ))}
              </ul>
            )}
            <p className="resumo-nota">
              Valores cheios do contrato, sem as obras encerradas. Executado = medido (execução) ÷ valor vigente; saldo a executar = valor
              vigente − medido (execução). Valor vigente somado: {brl(total.vigente)}.
            </p>
          </>
        )}

        {lista && !escolha && (
          <>
            <section className="filtros" aria-label="Filtros das obras">
              <div className="campo">
                <label className="sr-only" htmlFor="obras-busca">Buscar obra</label>
                <input id="obras-busca" type="search" value={texto} placeholder="Buscar obra, contrato ou empresa…" autoComplete="off"
                  spellCheck={false} onChange={e => digitar(e.target.value)} />
              </div>
              <p className="filtros-avisos__linha">
                <span className="campo__rotulo">Terminam</span>
                <Link para={aqui} busca={com({ termina: "90" })} aria-current={termina === 90 ? "true" : undefined}>em 90 dias</Link>
                <Link para={aqui} busca={com({ termina: "180" })} aria-current={termina === 180 ? "true" : undefined}>em 6 meses</Link>
                <Link para={aqui} busca={com({ termina: null })} aria-current={termina === null ? "true" : undefined}>em qualquer data</Link>
              </p>
              <label className="marcar" htmlFor="obras-encerradas">
                <input id="obras-encerradas" type="checkbox" checked={todas} onChange={e => trocarBusca({ situacao: e.target.checked ? "todas" : null })} />
                Mostrar as encerradas
              </label>
              <div className="filtros__fim">
                <p className="filtros-avisos__linha">
                  <span className="campo__rotulo">Ver</span>
                  <Link para={aqui} busca={com({ ver: null })} aria-current={!tabela ? "true" : undefined}>cartões</Link>
                  <Link para={aqui} busca={com({ ver: "tabela" })} aria-current={tabela ? "true" : undefined}>tabela</Link>
                </p>
                <button type="button" ref={botaoAvisos} className="btn btn--avisos" aria-expanded={avisosAbertos} aria-controls="avisos-area"
                  onClick={() => trocarBusca({ avisos: avisosAbertos ? null : "1" })}>
                  {avisosAbertos ? "Esconder os avisos" : "Avisos"}{nAvisosLabel}
                </button>
              </div>
            </section>

            {avisosAbertos && (
              <AvisosPagina busca={busca} perfil={perfil} avisos={avisos} escopo={idsDoContratante} nome={nomeLista}
                onFechar={() => { trocarBusca({ avisos: null, familia: null, nivel: null, obra: null, agrupar: null }); botaoAvisos.current?.focus(); }} />
            )}

            {/* o titulo diz quantas obras a tela mostra; o recorte em vigor, em palavras, vai junto */}
            <p className="contagem" role="status">
              {titulo}{detalhe ? ` ${detalhe}` : ""}
              {temFiltro && <> · <Link para={aqui} busca={com({ termina: null, q: null })}>Limpar os filtros</Link></>}
            </p>

            {filtradas.length === 0 && (
              <section className="cartao">
                <div className="vazio vazio--curto">
                  {doContratante.length === 0 ? <p className="vazio__titulo">Nenhuma obra no cadastro.</p> : temFiltro ? (
                    <><p className="vazio__titulo">Nenhuma obra com esses filtros.</p><p><Link para={aqui} busca={com({ termina: null, q: null })}>Limpar os filtros</Link></p></>
                  ) : (
                    <><p className="vazio__titulo">Nenhuma obra sem as encerradas.</p><p><Link para={aqui} busca={com({ situacao: "todas" })}>Mostrar as encerradas</Link></p></>
                  )}
                </div>
              </section>
            )}

            {filtradas.length > 0 && !tabela && (
              <ul className="obra-cartoes" aria-label="Obras">
                {filtradas.map(c => <CartaoObra key={c.id} obra={c} avisos={porObra?.get(c.id) ?? []} ir={ir} />)}
              </ul>
            )}

            {filtradas.length > 0 && tabela && (
              <section className="cartao">
                <Rolagem rotulo="Obras" alta>
                  <table className="tabela obras-lista">
                    <caption className="sr-only">Obras{termina ? `, que terminam em ${termina === 90 ? "90 dias" : "6 meses"}` : ""}</caption>
                    <thead>
                      <tr>
                        <th scope="col">Obra</th><th scope="col">Órgão</th><th scope="col">Empresa</th><th scope="col">Status</th>
                        <th scope="col" className="col-num">Valor vigente</th><th scope="col" className="col-num">Executado</th>
                        <th scope="col" className="col-data">Fim da execução</th>
                        <th scope="col" className="col-data">Fim da vigência</th><th scope="col">Pedido de prorrogação</th><th scope="col" className="col-num">Avisos</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtradas.map((c, i) => {
                        const s = STATUS[status(c)] ?? { rotulo: c.estado, classe: "" };
                        const prazo = prazos.get(c.id) ?? prazoDaObra(c);
                        const p = c.pedido_prorrogacao;
                        const pct = pctExecutado(c);
                        return (
                          <tr key={c.id} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                            <td>
                              <Link className="nome-link truncar-2l" title={nomeDaObra(c)} para={{ tela: "obra", id: c.id, aba: "medicoes" }} ir={ir}>{nomeDaObra(c)}</Link>
                              {c.nome_curto && <div className="campo__nota num">{c.numero_instrumento}</div>}
                            </td>
                            <td><span className="truncar-2l" title={c.orgao}>{c.orgao}</span></td>
                            <td>{c.entidade_id != null && empresas ? empresas.get(c.entidade_id) ?? "—" : "—"}</td>
                            <td><Selo classe={s.classe}>{s.rotulo}</Selo></td>
                            <td className="col-num dinheiro num">{c.valor_vigente_centavos != null ? brl(c.valor_vigente_centavos) : "—"}</td>
                            <td className="col-num num">{pct === null ? "—" : `${pct}%`}</td>
                            <td className="num">
                              <Fim fim={c.execucao_fim_vigente} dias={c.dias_execucao} nivel={prazo.execucao} aberta={status(c) === "ativo"}
                                paralisada={prazo.paralisada ? { desde: prazo.paralisadaDesde } : undefined} />
                            </td>
                            <td className="num"><Fim fim={c.vigencia_fim_vigente} dias={c.dias_vigencia} automatica={c.vigencia_automatica} nivel={prazo.vigencia}
                              aberta={status(c) === "ativo" && !c.vigencia_automatica} /></td>
                            <td className="pedido">{p ? (
                              <Link para={{ tela: "obra", id: c.id, aba: "prazos" }}>
                                <span className="sem-quebra">{p.numero_oficio ?? "ofício"}</span>{p.dias === null ? "" : p.dias === 0 ? ", hoje" : `, há ${fmtDias(p.dias)}`}
                              </Link>
                            ) : "—"}</td>
                            <td className="col-num num">{avisos === null || prazo.total === 0 ? "—" : <AvisosDaObra obra={c} prazo={prazo} busca={busca} />}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </Rolagem>
              </section>
            )}
          </>
        )}
      </div>
    </>
  );
}
