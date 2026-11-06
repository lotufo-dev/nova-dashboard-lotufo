import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { api, mensagemDeErro } from "./api";
import { brl } from "./formato";
import { IconeAlerta } from "./icones";
import { fmtCompetencia, fmtMesCurto, fmtMesExtenso } from "./tempo";
import "./aReceber.css";

// A receber (redesenho #162; enxugada em 06/11/2026 para a diretoria; tudo na cota da Lotufo): o total a receber, o
// recebido do mes e do ano, o recebido dos ultimos 6 meses e o a receber por contratante ou por obra. O recebido e' o
// REAL: as baixas do RM (`diretoria.rm_por_mes`), nao as medicoes marcadas como recebidas (o cadastro de medicoes pode
// estar atrasado). Sairam da tela o "previsto" por vencimento estimado, o medido sem nota, a nota sem protocolo e a
// lista de cobrancas. O valor a receber so' aparece com o total liberado (conciliado com a controladoria).

type Mes = { competencia: string; atual: boolean; futuro: boolean; previsto_centavos: number | null; recebido_centavos: number | null;
  recebido_real_centavos?: number | null };
type Obra = { contrato_id: number; obra: string; quantidade: number; valor_centavos: number | null };
type Orgao = { orgao_id: number | null; orgao: string; quantidade: number; valor_centavos: number | null };
type Resposta = {
  hoje: string; total_a_receber_liberado: boolean;
  total: { quantidade: number; obras: number; valor_centavos: number | null };
  recebido_ano_centavos?: number;
  mes: Mes; meses: Mes[]; por_obra: Obra[]; por_orgao?: Orgao[];
};
/** Uma linha do "a receber por": contratante ou obra. */
type Fatia = { chave: string; nome: string; quantidade: number; valor_centavos: number | null };
type Corte = "orgao" | "obra";

function valor(v: number | null | undefined): string { return v === null || v === undefined ? "—" : brl(v); }
/** O recebido de verdade do mes (baixas do RM); servidor antigo so' manda o das medicoes. */
function recebido(m: Mes): number | null { return m.recebido_real_centavos !== undefined ? m.recebido_real_centavos : m.recebido_centavos; }
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
  const maior = Math.max(0, ...meses.map(m => recebido(m) ?? 0));
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
          const rec = recebido(m);
          const rotulo = `${fmtMesExtenso(m.competencia)} de ${m.competencia.slice(0, 4)}: recebido ${valor(rec)}`;
          return (
            <g key={m.competencia} className={`g-grupo${i === escolhido ? " selecionado" : ""}`} tabIndex={0} role="button"
              aria-pressed={i === escolhido} aria-label={rotulo} data-mes={m.competencia}
              onClick={() => escolher(i)} onKeyDown={ev => teclas(ev, i)}>
              <title>{rotulo}</title>
              {m.atual && <rect className="g-atual" x={ml + gw * i + 2} y={mt - 22} width={gw - 4} height={ph + 22 + mb} rx={8} />}
              <rect className="g-alvo" x={ml + gw * i + 2} y={mt - 22} width={gw - 4} height={ph + 22 + mb} rx={8} />
              {rec !== null && rec > 0 && <rect className="b-recebido" x={cx - bw / 2} y={y(rec)} width={bw} height={y(0) - y(rec)} rx={3} />}
              {/* em tela estreita o rotulo nao cabe no vao do mes: fica so' o do mes escolhido (o detalhe abaixo diz o valor) */}
              {rec !== null && (gw >= 56 || i === escolhido) && <text className="g-valor" x={cx} y={y(rec) - 6} textAnchor="middle">{curto(rec)}</text>}
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
  return <><strong>{nome}</strong>: recebido <span className="dinheiro">{valor(recebido(m))}</span></>;
}

export default function AReceberPagina() {
  const [p, setP] = useState<Resposta | null>(null);
  const [erro, setErro] = useState("");
  const [escolhido, setEscolhido] = useState<number | null>(null);
  const [corte, setCorte] = useState<Corte>("orgao");

  useEffect(() => {
    let vivo = true;
    api<Resposta>("/api/a-receber").then(d => { if (vivo) setP(d); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, []);

  if (erro) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro} Recarregue a página para tentar de novo.</p>;
  if (!p) return <section className="cartao"><div className="vazio"><p>Carregando…</p></div></section>;

  const mes = p.mes;
  const nomeMes = fmtMesExtenso(mes.competencia);
  // o grafico e' so' do que ja' aconteceu: os meses ate' o atual
  const passados = p.meses.filter(m => !m.futuro);
  const indiceMes = Math.min(escolhido ?? Math.max(0, passados.findIndex(m => m.atual)), passados.length - 1);
  // sem contratante na resposta (servidor antigo), a tela cai no corte por obra
  const temOrgao = (p.por_orgao?.length ?? 0) > 0;
  const corteAtual: Corte = temOrgao ? corte : "obra";
  const fatias: Fatia[] = corteAtual === "orgao"
    ? (p.por_orgao ?? []).map(o => ({ chave: o.orgao, nome: o.orgao, quantidade: o.quantidade, valor_centavos: o.valor_centavos }))
    : p.por_obra.map(o => ({ chave: String(o.contrato_id), nome: o.obra, quantidade: o.quantidade, valor_centavos: o.valor_centavos }));
  const maior = Math.max(1, ...fatias.map(o => o.valor_centavos ?? o.quantidade));

  return (
    <div className="pilha">
      <section aria-label="Resumo">
        <ul className="ar-numeros">
          <li className="cartao ar-numero ar-numero--destaque">
            <span className="ar-numero__rotulo">A receber, na cota</span>
            <span className="ar-numero__valor num">{valor(p.total.valor_centavos)}</span>
          </li>
          <li className="cartao ar-numero">
            <span className="ar-numero__rotulo">Recebido em {nomeMes}</span>
            <span className="ar-numero__valor num">{valor(recebido(mes))}</span>
          </li>
          {p.recebido_ano_centavos !== undefined && (
            <li className="cartao ar-numero">
              <span className="ar-numero__rotulo">Recebido em {mes.competencia.slice(0, 4)}</span>
              <span className="ar-numero__valor num">{valor(p.recebido_ano_centavos)}</span>
            </li>
          )}
        </ul>
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
              <tr key={m.competencia}><th scope="row">{fmtCompetencia(m.competencia)}</th><td>{valor(recebido(m))}</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="cartao" aria-labelledby="t-obras">
        <div className="cartao__cabeca cartao__cabeca--quebra">
          <h2 className="cartao__titulo" id="t-obras">A receber por</h2>
          {temOrgao && (
            <div className="cart-farois" role="group" aria-label="Agrupar o a receber">
              <button type="button" className="cart-farol-btn" aria-pressed={corteAtual === "orgao"} onClick={() => setCorte("orgao")}>Contratante</button>
              <button type="button" className="cart-farol-btn" aria-pressed={corteAtual === "obra"} onClick={() => setCorte("obra")}>Obra</button>
            </div>
          )}
        </div>
        {fatias.length === 0 ? (
          <div className="vazio vazio--curto"><p>Nenhuma cobrança esperando pagamento.</p></div>
        ) : (
          <ul className="ar-obras">
            {fatias.map(o => (
              <li key={o.chave} className="ar-obra">
                <span className="ar-obra__nome">{o.nome}</span>
                <span className="ar-obra__trilho" aria-hidden="true">
                  <span className="ar-obra__barra" style={{ width: `${(((o.valor_centavos ?? o.quantidade) / maior) * 100).toFixed(1)}%` }} />
                </span>
                <span className="ar-obra__valor">{valor(o.valor_centavos)}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="ar-obras__total"><span>Total</span><span className="dinheiro">{valor(p.total.valor_centavos)}</span></div>
      </section>
    </div>
  );
}
