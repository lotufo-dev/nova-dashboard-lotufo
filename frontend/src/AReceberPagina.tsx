import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { api, mensagemDeErro } from "./api";
import { brl } from "./formato";
import { IconeAlerta } from "./icones";
import { Link } from "./Link";
import { fmtCompetencia, fmtDataPura, fmtMesCurto, fmtMesExtenso } from "./tempo";
import Rolagem from "./Rolagem";
import "./aReceber.css";

// A receber (redesenho #162; enxugada em 06/11/2026 para a diretoria; tudo na cota da Lotufo): onde esta' o dinheiro
// (medido sem nota, nota sem protocolo, protocolado a receber, recebido no mes), o recebido dos ultimos 6 meses, o a
// receber por contratante ou por obra (clicar filtra a tabela) e a lista das cobrancas, da maior para a menor. O
// "previsto" por vencimento estimado saiu da tela: era palpite (prazo do orgao) e somava medicao ja' paga. As regras
// moram em `diretoria.a_receber`; o valor so' aparece com o total liberado (conciliado com a controladoria).

type Mes = { competencia: string; atual: boolean; futuro: boolean; previsto_centavos: number | null; recebido_centavos: number | null };
type Grupo = { quantidade: number; valor_centavos: number | null };
type Obra = { contrato_id: number; obra: string; quantidade: number; valor_centavos: number | null };
type Orgao = { orgao_id: number | null; orgao: string; quantidade: number; valor_centavos: number | null };
type Item = {
  contrato_id: number; orgao_id?: number | null; obra: string; medicao_id: number | null; numero: number | null; tipo: string; nota_numero: string | null;
  competencia: string | null; protocolada_em: string | null; valor_centavos: number | null;
};
type Resposta = {
  hoje: string; total_a_receber_liberado: boolean;
  total: { quantidade: number; obras: number; valor_centavos: number | null };
  antes_do_protocolo?: { medido_esperando_nota: Grupo; nota_esperando_protocolo: Grupo };
  mes: Mes; meses: Mes[]; por_obra: Obra[]; por_orgao?: Orgao[]; itens: Item[];
};
/** Uma linha do "a receber por": contratante ou obra, com a chave que filtra a tabela. */
type Fatia = { chave: string; nome: string; quantidade: number; valor_centavos: number | null };
type Corte = "orgao" | "obra";

const TIPOS: Record<string, string> = { reajuste: "reajuste", projeto: "projeto" };

function valor(v: number | null): string { return v === null ? "—" : brl(v); }
function maiuscula(s: string): string { return s.charAt(0).toUpperCase() + s.slice(1); }
/** Valor curto do eixo e das barras: "4,2 mi" ou "850 mil". So' apresentacao; a conta e' em centavos inteiros. */
function curto(c: number): string {
  if (Math.round(c / 100_000) >= 1000) return `${(c / 100_000_000).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} mi`;
  if (c === 0) return "0";
  return c < 100_000 ? `R$ ${Math.round(c / 100).toLocaleString("pt-BR")}` : `${Math.round(c / 100_000).toLocaleString("pt-BR")} mil`;
}
/** Topo do eixo e passo: o maior valor arredondado para cima num degrau 1, 2 ou 5 (x 10^k) de tres divisoes. */
function eixo(maior: number): { topo: number; passo: number } {
  const bruto = Math.max(maior, 1) / 3;
  const pot = 10 ** Math.floor(Math.log10(bruto));
  const passo = ([1, 2, 5, 10].find(f => f * pot >= bruto) ?? 10) * pot;
  return { topo: Math.ceil(Math.max(maior, 1) / passo) * passo, passo };
}
function tituloMedicao(i: Item): string {
  if (i.tipo === "nota") return `Nota do RM ${i.nota_numero ?? ""}`.trim();
  const extra = TIPOS[i.tipo];
  return `${i.numero}ª${extra ? ` (${extra})` : ""}`;
}

/** Largura do contentor, para o SVG ter texto de 11px de verdade em tela estreita (sem ResizeObserver, 720). */
function useLargura() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(720);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const medir = () => { if (el.clientWidth > 0) setW(el.clientWidth); };
    medir();
    if (typeof ResizeObserver === "undefined") return;
    const o = new ResizeObserver(medir);
    o.observe(el);
    return () => o.disconnect();
  }, []);
  return [ref, w] as const;
}

function Grafico({ meses, escolhido, escolher }:
    { meses: Mes[]; escolhido: number; escolher: (i: number) => void }) {
  const [ref, largura] = useLargura();
  const W = Math.max(260, largura - 40);
  const estreito = W < 420;
  const H = estreito ? 200 : 240, mt = 26, mb = 28, ml = 52, mr = 4;
  const ph = H - mt - mb, pw = W - ml - mr;
  const maior = Math.max(0, ...meses.map(m => m.recebido_centavos ?? 0));
  const { topo, passo } = eixo(maior);
  const y = (c: number) => mt + ph - (c / topo) * ph;
  const gw = pw / meses.length;
  // uma barra por mes: o rotulo ("17,1 mi") cabe sempre no vao do proprio mes, sem encostar no vizinho
  const bw = Math.min(56, gw * 0.5);
  const ticks: number[] = [];
  for (let t = 0; t <= topo; t += passo) ticks.push(t);
  const teclas = (ev: KeyboardEvent, i: number) => {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); escolher(i); }
    const alvo = ev.key === "ArrowRight" ? i + 1 : ev.key === "ArrowLeft" ? i - 1 : null;
    if (alvo === null || alvo < 0 || alvo >= meses.length) return;
    ev.preventDefault();
    escolher(alvo);
    ev.currentTarget.parentElement?.querySelector<SVGGElement>(`[data-mes="${meses[alvo].competencia}"]`)?.focus();
  };
  return (
    <div className="ar-grafico" ref={ref} role="group" aria-label={`Recebido nos últimos ${meses.length} meses`}>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H}>
        {ticks.map(t => (
          <g key={t}>
            <line className={t ? "g-grade" : "g-base"} x1={ml} x2={W - mr} y1={y(t)} y2={y(t)} />
            <text x={ml - 8} y={y(t) + 4} textAnchor="end">{curto(t)}</text>
          </g>
        ))}
        {meses.map((m, i) => {
          const cx = ml + gw * i + gw / 2;
          const rec = m.recebido_centavos;
          const rotulo = `${fmtMesExtenso(m.competencia)} de ${m.competencia.slice(0, 4)}: recebido ${valor(rec)}`;
          return (
            <g key={m.competencia} className={`g-grupo${i === escolhido ? " selecionado" : ""}`} tabIndex={0} role="button"
              aria-pressed={i === escolhido} aria-label={rotulo} data-mes={m.competencia}
              onClick={() => escolher(i)} onKeyDown={ev => teclas(ev, i)}>
              <title>{rotulo}</title>
              {m.atual && <rect className="g-atual" x={ml + gw * i + 2} y={mt - 22} width={gw - 4} height={ph + 22 + mb} rx={8} />}
              <rect className="g-alvo" x={ml + gw * i + 2} y={mt - 22} width={gw - 4} height={ph + 22 + mb} rx={8} />
              {rec !== null && rec > 0 && <rect className="b-recebido" x={cx - bw / 2} y={y(rec)} width={bw} height={y(0) - y(rec)} rx={3} />}
              {rec !== null && <text className="g-valor" x={cx} y={y(rec) - 6} textAnchor="middle">{curto(rec)}</text>}
              <text className={`g-mes${m.atual ? " g-mes--atual" : ""}`} x={cx} y={H - 8} textAnchor="middle">
                {estreito ? fmtMesCurto(m.competencia).split("/")[0] : fmtMesCurto(m.competencia)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Detalhe({ m }: { m: Mes }) {
  const nome = `${maiuscula(fmtMesExtenso(m.competencia))} de ${m.competencia.slice(0, 4)}`;
  return <><strong>{nome}</strong>: recebido <span className="dinheiro">{valor(m.recebido_centavos)}</span></>;
}

export default function AReceberPagina() {
  const [p, setP] = useState<Resposta | null>(null);
  const [erro, setErro] = useState("");
  const [escolhido, setEscolhido] = useState<number | null>(null);
  const [corte, setCorte] = useState<Corte>("orgao");
  const [filtro, setFiltro] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    api<Resposta>("/api/a-receber").then(d => { if (vivo) setP(d); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, []);

  if (erro) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro} Recarregue a página para tentar de novo.</p>;
  if (!p) return <section className="cartao"><div className="vazio"><p>Carregando…</p></div></section>;

  const liberado = p.total_a_receber_liberado;
  const mes = p.mes;
  const nomeMes = fmtMesExtenso(mes.competencia);
  // o grafico e' so' do que ja' aconteceu: os meses ate' o atual
  const passados = p.meses.filter(m => !m.futuro);
  const indiceMes = Math.min(escolhido ?? Math.max(0, passados.findIndex(m => m.atual)), passados.length - 1);
  // sem contratante na resposta (servidor antigo), a tela cai no corte por obra
  const temOrgao = (p.por_orgao?.length ?? 0) > 0;
  const corteAtual: Corte = temOrgao ? corte : "obra";
  const fatias: Fatia[] = corteAtual === "orgao"
    ? (p.por_orgao ?? []).map(o => ({ chave: String(o.orgao_id), nome: o.orgao, quantidade: o.quantidade, valor_centavos: o.valor_centavos }))
    : p.por_obra.map(o => ({ chave: String(o.contrato_id), nome: o.obra, quantidade: o.quantidade, valor_centavos: o.valor_centavos }));
  const chaveDe = (i: Item) => String(corteAtual === "orgao" ? i.orgao_id : i.contrato_id);
  const escolhida = fatias.find(f => f.chave === filtro) ?? null;
  // a maior cobranca primeiro: o residuo de centavos de nota antiga nao abre a lista
  const itens = p.itens.filter(i => escolhida === null || chaveDe(i) === escolhida.chave)
    .map((i, k) => ({ i, k })).sort((a, b) => (b.i.valor_centavos ?? 0) - (a.i.valor_centavos ?? 0) || a.k - b.k).map(x => x.i);
  const maior = Math.max(1, ...fatias.map(o => o.valor_centavos ?? o.quantidade));
  const totalItens = liberado ? itens.reduce((s, i) => s + (i.valor_centavos ?? 0), 0) : null;
  const antes = p.antes_do_protocolo;
  const trocarCorte = (c: Corte) => { setCorte(c); setFiltro(null); };

  return (
    <div className="pilha">
      <section aria-labelledby="t-caminho">
        <h2 className="cart-titulo-secao ar-titulo" id="t-caminho">Onde está o dinheiro, na cota</h2>
        <ol className="ar-numeros">
          {antes && (
            <li className="cartao ar-numero">
              <span className="ar-numero__rotulo">Medido, sem nota</span>
              <span className="ar-numero__valor num">{valor(antes.medido_esperando_nota.valor_centavos)}</span>
            </li>
          )}
          {antes && (
            <li className="cartao ar-numero">
              <span className="ar-numero__rotulo">Nota emitida, sem protocolo</span>
              <span className="ar-numero__valor num">{valor(antes.nota_esperando_protocolo.valor_centavos)}</span>
            </li>
          )}
          <li className="cartao ar-numero ar-numero--destaque">
            <span className="ar-numero__rotulo">Protocolado, a receber</span>
            <span className="ar-numero__valor num">{valor(p.total.valor_centavos)}</span>
          </li>
          <li className="cartao ar-numero">
            <span className="ar-numero__rotulo">Recebido em {nomeMes}</span>
            <span className="ar-numero__valor num">{valor(mes.recebido_centavos)}</span>
          </li>
        </ol>
      </section>

      <section className="cartao" aria-labelledby="t-grafico">
        <div className="cartao__cabeca">
          <h2 className="cartao__titulo" id="t-grafico">Recebido por mês</h2>
        </div>
        <Grafico meses={passados} escolhido={indiceMes} escolher={setEscolhido} />
        <p className="ar-detalhe" role="status"><Detalhe m={passados[indiceMes]} /></p>
        <table className="sr-only">
          <caption>Recebido por mês, na cota</caption>
          <thead><tr><th scope="col">Mês</th><th scope="col">Recebido</th></tr></thead>
          <tbody>
            {passados.map(m => (
              <tr key={m.competencia}><th scope="row">{fmtCompetencia(m.competencia)}</th><td>{valor(m.recebido_centavos)}</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      <div className="ar-duas">
        <section className="cartao" aria-labelledby="t-obras">
          <div className="cartao__cabeca cartao__cabeca--quebra">
            <h2 className="cartao__titulo" id="t-obras">A receber por</h2>
            {temOrgao && (
              <div className="cart-farois" role="group" aria-label="Agrupar o a receber">
                <button type="button" className="cart-farol-btn" aria-pressed={corteAtual === "orgao"} onClick={() => trocarCorte("orgao")}>Contratante</button>
                <button type="button" className="cart-farol-btn" aria-pressed={corteAtual === "obra"} onClick={() => trocarCorte("obra")}>Obra</button>
              </div>
            )}
          </div>
          {fatias.length === 0 ? (
            <div className="vazio vazio--curto"><p>Nenhuma cobrança esperando pagamento.</p></div>
          ) : (
            <ul className="ar-obras">
              {fatias.map(o => (
                <li key={o.chave}>
                  <button type="button" className="ar-obra" aria-pressed={filtro === o.chave}
                    onClick={() => setFiltro(filtro === o.chave ? null : o.chave)}>
                    <span className="ar-obra__nome">{o.nome}</span>
                    <span className="ar-obra__trilho" aria-hidden="true">
                      <span className="ar-obra__barra" style={{ width: `${(((o.valor_centavos ?? o.quantidade) / maior) * 100).toFixed(1)}%` }} />
                    </span>
                    <span className="ar-obra__valor">{valor(o.valor_centavos)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="ar-obras__total"><span>Total</span><span className="dinheiro">{valor(p.total.valor_centavos)}</span></div>
        </section>

        <section className="cartao" aria-labelledby="t-medicoes">
          <div className="cartao__cabeca cartao__cabeca--quebra">
            <h2 className="cartao__titulo" id="t-medicoes">Cobranças esperando pagamento</h2>
            {escolhida && (
              <div className="ar-filtro">
                <span className="selo"><span className="selo__texto">Só {escolhida.nome}</span></span>
                <button type="button" className="btn btn--pequeno" onClick={() => setFiltro(null)}>Mostrar todas</button>
              </div>
            )}
          </div>
          {itens.length === 0 ? (
            <div className="vazio vazio--curto"><p className="vazio__titulo">Nenhuma medição protocolada esperando pagamento.</p></div>
          ) : (
            <Rolagem rotulo="Cobranças esperando pagamento">
              <table className="tabela ar-tabela">
                <caption className="sr-only">Cobranças esperando pagamento, na cota</caption>
                <thead>
                  <tr>
                    <th scope="col">Obra</th><th scope="col">Medição</th><th scope="col">Protocolada em</th>
                    <th scope="col" className="col-num">Valor na cota</th><th scope="col"><span className="sr-only">Abrir</span></th>
                  </tr>
                </thead>
                <tbody>
                  {itens.map((i, k) => (
                    <tr key={`${k}-${i.medicao_id ?? "nota"}-${i.contrato_id}-${i.nota_numero ?? i.numero}`}>
                      <td className="ar-forte col-largo" data-rotulo="Obra">{i.obra}</td>
                      <td data-rotulo="Medição">
                        {tituloMedicao(i)}{i.competencia && <> <span className="campo__nota">({fmtCompetencia(i.competencia)})</span></>}
                      </td>
                      <td className="ar-data" data-rotulo="Protocolada em">{i.protocolada_em ? fmtDataPura(i.protocolada_em) : "—"}</td>
                      <td className="col-num dinheiro" data-rotulo="Valor na cota">{valor(i.valor_centavos)}</td>
                      <td>
                        {i.medicao_id !== null ? (
                          <Link para={{ tela: "medicao", obra: i.contrato_id, id: i.medicao_id }} secao="etapa-5"
                            aria-label={`Abrir ${tituloMedicao(i)} de ${i.obra}`}>Abrir</Link>
                        ) : (
                          <Link para={{ tela: "obra", id: i.contrato_id, aba: "medicoes" }}
                            aria-label={`Abrir a obra ${i.obra}`}>Abrir</Link>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th scope="row" className="col-largo">
                      {escolhida ? `Total de ${escolhida.nome}` : "Total"}
                    </th>
                    <td /><td />
                    <td className="col-num" data-rotulo="Valor na cota">{valor(totalItens)}</td><td />
                  </tr>
                </tfoot>
              </table>
            </Rolagem>
          )}
        </section>
      </div>
    </div>
  );
}
