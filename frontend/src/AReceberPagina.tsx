import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { api, mensagemDeErro } from "./api";
import { brl, contar } from "./formato";
import { IconeAlerta } from "./icones";
import { Link } from "./Link";
import { fmtCompetencia, fmtDataPura, fmtMesCurto, fmtMesExtenso } from "./tempo";
import Rolagem from "./Rolagem";
import "./aReceber.css";

// A receber (redesenho #162, prototipo aprovado pelo Leo em 16/10/2026; tudo na cota da Lotufo): o total das
// cobrancas protocoladas esperando pagamento, o previsto e o recebido do mes, o grafico dos ultimos 6 meses e dos
// proximos 3, o a receber por obra (clicar filtra a tabela) e a lista das cobrancas. As regras moram em
// `diretoria.a_receber`; o valor so' aparece com o total liberado (conciliado com a controladoria), como antes.

type Mes = { competencia: string; atual: boolean; futuro: boolean; previsto_centavos: number | null; recebido_centavos: number | null };
type Obra = { contrato_id: number; obra: string; quantidade: number; valor_centavos: number | null };
type Item = {
  contrato_id: number; obra: string; medicao_id: number | null; numero: number | null; tipo: string; nota_numero: string | null;
  competencia: string | null; protocolada_em: string | null; valor_centavos: number | null;
};
type Resposta = {
  hoje: string; total_a_receber_liberado: boolean;
  total: { quantidade: number; obras: number; valor_centavos: number | null };
  mes: Mes; meses: Mes[]; por_obra: Obra[]; itens: Item[];
};

const TIPOS: Record<string, string> = { reajuste: "reajuste", projeto: "projeto" };

function valor(v: number | null): string { return v === null ? "—" : brl(v); }
function maiuscula(s: string): string { return s.charAt(0).toUpperCase() + s.slice(1); }
function pct(rec: number | null, prev: number | null): number | null {
  return rec === null || prev === null || prev <= 0 ? null : Math.round((rec / prev) * 100);
}
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

function Grafico({ meses, liberado, escolhido, escolher }:
    { meses: Mes[]; liberado: boolean; escolhido: number; escolher: (i: number) => void }) {
  const [ref, largura] = useLargura();
  const W = Math.max(260, largura - 40);
  const estreito = W < 560;
  const H = estreito ? 220 : 260, mt = 26, mb = 28, ml = 44, mr = 4;
  const ph = H - mt - mb, pw = W - ml - mr;
  const maior = Math.max(0, ...meses.flatMap(m => [m.previsto_centavos ?? 0, m.recebido_centavos ?? 0]));
  const { topo, passo } = eixo(maior);
  const y = (c: number) => mt + ph - (c / topo) * ph;
  const gw = pw / meses.length;
  const bw = Math.min(30, gw * (estreito ? 0.3 : 0.27)), folga = Math.max(2, bw * 0.15);
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
    <div className="ar-grafico" ref={ref} role="group" aria-label="Previsto e recebido nos últimos 6 meses e previsão dos próximos 3">
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H}>
        {ticks.map(t => (
          <g key={t}>
            <line className={t ? "g-grade" : "g-base"} x1={ml} x2={W - mr} y1={y(t)} y2={y(t)} />
            <text x={ml - 8} y={y(t) + 4} textAnchor="end">{curto(t)}</text>
          </g>
        ))}
        {meses.map((m, i) => {
          const cx = ml + gw * i + gw / 2;
          const prev = m.previsto_centavos, rec = m.recebido_centavos;
          const nome = `${fmtMesExtenso(m.competencia)} de ${m.competencia.slice(0, 4)}`;
          const rotulo = m.futuro ? `${nome}: previsão ${valor(prev)}` : `${nome}: previsto ${valor(prev)}, recebido ${valor(rec)}`;
          const x1 = cx - folga / 2 - bw, x2 = cx + folga / 2;
          return (
            <g key={m.competencia} className={`g-grupo${i === escolhido ? " selecionado" : ""}`} tabIndex={0} role="button"
              aria-pressed={i === escolhido} aria-label={rotulo} data-mes={m.competencia}
              onClick={() => escolher(i)} onKeyDown={ev => teclas(ev, i)}>
              <title>{rotulo}</title>
              {m.atual && <rect className="g-atual" x={ml + gw * i + 2} y={mt - 22} width={gw - 4} height={ph + 22 + mb} rx={8} />}
              <rect className="g-alvo" x={ml + gw * i + 2} y={mt - 22} width={gw - 4} height={ph + 22 + mb} rx={8} />
              {m.futuro ? (
                prev !== null && <>
                  <rect className="b-previsao" x={cx - bw / 2} y={y(prev)} width={bw} height={y(0) - y(prev)} rx={3} />
                  {!estreito && <text className="t-previsao" x={cx} y={y(prev) - 18} textAnchor="middle">previsão</text>}
                  {!estreito && <text x={cx} y={y(prev) - 5} textAnchor="middle">{curto(prev)}</text>}
                </>
              ) : (
                <>
                  {prev !== null && <rect className="b-previsto" x={x1} y={y(prev)} width={bw} height={y(0) - y(prev)} rx={3} />}
                  {rec !== null && <rect className="b-recebido" x={x2} y={y(rec)} width={bw} height={y(0) - y(rec)} rx={3} />}
                  {!estreito && prev !== null && <text x={x1 + bw / 2} y={y(prev) - 5} textAnchor="middle">{curto(prev)}</text>}
                  {!estreito && rec !== null && <text x={x2 + bw / 2} y={y(rec) - 5} textAnchor="middle">{curto(rec)}</text>}
                </>
              )}
              <text className={`g-mes${m.atual ? " g-mes--atual" : ""}`} x={cx} y={H - 8} textAnchor="middle">
                {estreito ? fmtMesCurto(m.competencia).split("/")[0] : fmtMesCurto(m.competencia)}
              </text>
            </g>
          );
        })}
        {!liberado && <text x={ml} y={mt - 8}>Previsto a conciliar com a controladoria</text>}
      </svg>
    </div>
  );
}

function Detalhe({ m, hoje }: { m: Mes; hoje: string }) {
  const nome = `${maiuscula(fmtMesExtenso(m.competencia))} de ${m.competencia.slice(0, 4)}`;
  if (m.futuro) return <><strong>{nome}</strong> (previsão): <span className="dinheiro">{valor(m.previsto_centavos)}</span></>;
  const p = pct(m.recebido_centavos, m.previsto_centavos);
  return (
    <>
      <strong>{nome}</strong>{m.atual && ` (mês atual, até ${hoje.slice(8, 10)}/${hoje.slice(5, 7)})`}: previsto{" "}
      <span className="dinheiro">{valor(m.previsto_centavos)}</span> · recebido{" "}
      <span className="dinheiro">{valor(m.recebido_centavos)}</span>{p !== null && ` · ${p}% do previsto`}
    </>
  );
}

export default function AReceberPagina() {
  const [p, setP] = useState<Resposta | null>(null);
  const [erro, setErro] = useState("");
  const [escolhido, setEscolhido] = useState<number | null>(null);
  const [obra, setObra] = useState<number | null>(null);

  useEffect(() => {
    let vivo = true;
    api<Resposta>("/api/a-receber").then(d => { if (vivo) setP(d); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, []);

  if (erro) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro} Recarregue a página para tentar de novo.</p>;
  if (!p) return <section className="cartao"><div className="vazio"><p>Carregando…</p></div></section>;

  const liberado = p.total_a_receber_liberado;
  const indiceMes = escolhido ?? Math.max(0, p.meses.findIndex(m => m.atual));
  const mes = p.mes;
  const nomeMes = fmtMesExtenso(mes.competencia);
  const percentual = pct(mes.recebido_centavos, mes.previsto_centavos);
  const itens = p.itens.filter(i => obra === null || i.contrato_id === obra);
  const obraEscolhida = p.por_obra.find(o => o.contrato_id === obra) ?? null;
  const maior = Math.max(1, ...p.por_obra.map(o => o.valor_centavos ?? o.quantidade));
  const totalItens = liberado ? itens.reduce((s, i) => s + (i.valor_centavos ?? 0), 0) : null;

  return (
    <div className="pilha">
      <section className="ar-numeros" aria-label="Resumo">
        <div className="cartao ar-numero">
          <span className="ar-numero__rotulo">A receber, na cota</span>
          <span className="ar-numero__valor num">{valor(p.total.valor_centavos)}</span>
          <span className="ar-numero__apoio num">
            {liberado
              ? `${contar(p.total.quantidade, "cobrança", "cobranças")} em ${contar(p.total.obras, "obra", "obras")}`
              : "valores a conciliar com a controladoria"}
          </span>
        </div>
        <div className="cartao ar-numero">
          <span className="ar-numero__rotulo">Previsto em {nomeMes}</span>
          <span className="ar-numero__valor num">{valor(mes.previsto_centavos)}</span>
          <span className="ar-numero__apoio">{liberado ? "vencimentos do mês; o recebido pode incluir pagamentos de outros meses" : "a conciliar com a controladoria"}</span>
        </div>
        <div className="cartao ar-numero">
          <span className="ar-numero__rotulo">Medições recebidas em {nomeMes}</span>
          <span className="ar-numero__valor num">{valor(mes.recebido_centavos)}</span>
          <span className="ar-numero__apoio num">
            {percentual !== null && `${percentual}% do previsto · `}até {fmtDataPura(p.hoje)}
          </span>
        </div>
      </section>

      <section className="cartao" aria-labelledby="t-grafico">
        <div className="cartao__cabeca cartao__cabeca--quebra">
          <h2 className="cartao__titulo" id="t-grafico">Previsto × recebido</h2>
          <div className="legenda ar-cabeca-legenda">
            <span className="legenda__item"><span className="legenda__chave legenda__chave--previsto" />Previsto</span>
            <span className="legenda__item"><span className="legenda__chave legenda__chave--recebido" />Recebido</span>
            <span className="legenda__item"><span className="legenda__chave legenda__chave--previsao" />Previsão</span>
          </div>
        </div>
        <Grafico meses={p.meses} liberado={liberado} escolhido={indiceMes} escolher={setEscolhido} />
        <p className="ar-detalhe" role="status"><Detalhe m={p.meses[indiceMes]} hoje={p.hoje} /></p>
        <table className="sr-only">
          <caption>Previsto e recebido por mês, na cota</caption>
          <thead><tr><th scope="col">Mês</th><th scope="col">Previsto</th><th scope="col">Recebido</th></tr></thead>
          <tbody>
            {p.meses.map(m => (
              <tr key={m.competencia}>
                <th scope="row">{fmtCompetencia(m.competencia)}{m.futuro ? " (previsão)" : ""}</th>
                <td>{valor(m.previsto_centavos)}</td><td>{m.futuro ? "—" : valor(m.recebido_centavos)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div className="ar-duas">
        <section className="cartao" aria-labelledby="t-obras">
          <div className="cartao__cabeca">
            <h2 className="cartao__titulo" id="t-obras">Por obra</h2>
            <span className="cartao__dica">clique para ver as cobranças da obra</span>
          </div>
          {p.por_obra.length === 0 ? (
            <div className="vazio vazio--curto"><p>Nenhuma obra com cobrança esperando pagamento.</p></div>
          ) : (
            <ul className="ar-obras">
              {p.por_obra.map(o => (
                <li key={o.contrato_id}>
                  <button type="button" className="ar-obra" aria-pressed={obra === o.contrato_id}
                    onClick={() => setObra(obra === o.contrato_id ? null : o.contrato_id)}>
                    <span className="ar-obra__nome">{o.obra}<small>{contar(o.quantidade, "cobrança", "cobranças")}</small></span>
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
            {obraEscolhida && (
              <div className="ar-filtro">
                <span className="selo"><span className="selo__texto">Só {obraEscolhida.obra}</span></span>
                <button type="button" className="btn btn--pequeno" onClick={() => setObra(null)}>Mostrar todas</button>
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
                      {obraEscolhida ? `Total de ${obraEscolhida.obra} (${itens.length})` : `Total (${contar(itens.length, "cobrança", "cobranças")})`}
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
