import { useEffect, useMemo, useRef, useState } from "react";
import { type Aviso } from "./Alertas";
import { api, mensagemDeErro } from "./api";
import { ABAS_CARTEIRA, motivosDaLinha, porFarol, type Motivo } from "./carteira";
import { fmtDias, fmtPercentual } from "./formato";
import { IconeAlerta, IconeBaixar } from "./icones";
import { filtrarObras, type ObraLista } from "./listaObras";
import { brl } from "./Medicoes";
import { type AbaCarteira, type Ir } from "./rota";
import { Link } from "./Link";
import { fmtCompetencia, fmtDataPura, fmtMesCurto as mesCurto } from "./tempo";
import Rolagem from "./Rolagem";
import Selo from "./Selo";
import { Abas } from "./Topo";

// Carteira (NAVEGACAO.md › Carteira; bloco 8, spec §10.5; redesenho #163, opcao A), a entrada da diretoria, em
// abas na URL: Resumo (a padrao, so' o essencial), QDOP e Producao; o "Exportar QDOP" fica visivel nas tres. Tudo na COTA da Lotufo, com o vocabulario fixo: medido, faturado, protocolado,
// recebido. As regras moram em `app/diretoria.py`; o total a receber so' mostra valor depois de conciliado
// (geral.yaml: diretoria.total_a_receber_liberado). O a receber (por obra, previsto e recebido) mora
// em A receber; os reajustes esperando apostilamento, na aba Reajuste da obra; a lista de avisos, na tela de Avisos; o que termina, em Obras.

type Grupo = { quantidade: number; valor_centavos: number | null };
type PorOrgao = Grupo & { orgao: string; maior_dias: number | null };
type Dinheiro = {
  medido_esperando_nota: Grupo; nota_esperando_protocolo: Grupo; recebido_mes: Grupo;
  protocolado: Grupo & { faixas: Record<"ate_30" | "de_31_a_60" | "mais_60", Grupo>; por_orgao: PorOrgao[] };
  reajustes_apostilamento: { quantidade: number; maior_dias: number | null };
};
type MesAno = {
  mes: string; medido_mes_centavos: number; previsto_mes_centavos: number; mesmo_mes_ano_anterior_centavos: number;
  acumulado_ano_centavos: number; previsto_ano_centavos: number;
  faturado_mes_centavos: number; notas_faturadas_mes: number;
  serie: { competencia: string; medido_centavos: number; previsto_centavos: number }[];
};
type Proximo = { competencia: string; faturamento_previsto_centavos: number };
/** Issue #296: a curva S da carteira (obras ativas, cada uma na cota), com o previsto anterior a ultima repactuacao. */
type PontoCarteira = { competencia: string; previsto_centavos: number; previsto_anterior_centavos: number; medido_centavos: number };
type Carteira = {
  saldo_centavos: number; ritmo_mensal_centavos: number; meses_de_producao: number | null;
  por_orgao: { orgao: string; saldo_centavos: number; fracao: number; vigente_centavos: number; medido_centavos: number; obras: number }[];
};
type Obra = {
  contrato_id: number; seq: number; obra: string; contratante: string; empreita: string; direito: number;
  pi_va: number; faturados: number; saldo: number; pct_recebido: number; status: string; termino: string | null;
  vigencia?: string | null; farol: "verde" | "atencao" | "acao" | "vermelho"; motivo: string; motivos?: Motivo[];
  desvio_pp?: number | null; desvio_base?: "anterior" | "vigente" | null;
};
type ResumoMes = { mes: string; obras_protocoladas: number; obras_ativas: number };
type Painel = {
  hoje: string; total_a_receber_liberado: boolean; dinheiro: Dinheiro; mes_ano: MesAno; curva_carteira: PontoCarteira[]; proximos: Proximo[];
  carteira: Carteira; obras: Obra[]; obras_base: ObrasBase; avisos: Aviso[];
};
type ObrasBase = { ativas: number; encerramento: number; suspensas: number; encerradas: number };

// O selo diz a palavra do nivel (D12, D10), a mesma do Selo dos avisos: Critico, Acao e Atencao. Acao e Atencao
// dividem o ambar e se separam pela forma (contorno cheio na Acao), como em Alertas. So' o QDOP EXPORTADO
// (arquivo) segue com o vocabulario oficial (verde, amarelo, vermelho).
const FAROL: Record<Obra["farol"], { rotulo: string; classe: string; forte?: boolean }> = {
  verde: { rotulo: "Em dia", classe: "selo--ok" },
  acao: { rotulo: "Ação", classe: "selo--atencao", forte: true },
  atencao: { rotulo: "Atenção", classe: "selo--atencao" },
  vermelho: { rotulo: "Crítico", classe: "selo--acao" },
};

function valor(v: number | null): string {
  return v === null ? "—" : brl(v);
}
function pct(f: number): string {
  return fmtPercentual(f, 1);
}
/** Desvio em pontos percentuais, com sinal e uma casa: "+2,9", "−16,7" (menos U+2212, como o `brl`), "0,0". */
function pp(v: number): string {
  const t = Math.abs(v).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return v > 0 ? `+${t}` : v < 0 ? `−${t}` : t;
}
/** "R$ 12,3 mi": o numero grande do Resumo; o valor exato vai no title. */
function mi(centavos: number): string {
  if (centavos === 0) return "R$ 0";
  // abaixo de 1 milhao "R$ 0,0 mi" pareceria zero: nesse caso, em mil
  if (Math.abs(centavos) < 100_000_000) return `R$ ${(centavos / 100_000).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} mil`;
  return `R$ ${(centavos / 100_000_000).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} mi`;
}
function data(iso: string | null | undefined): string {
  return iso ? fmtDataPura(iso.slice(0, 10)) : "—";
}

// Escala e unidade repetidas do Cronograma de proposito (a linguagem visual mora no tokens.css).
function escala(maxCentavos: number): { topo: number; passo: number } {
  const max = Math.max(1, maxCentavos);
  const alvo = max / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(alvo)));
  const passo = Math.max(1, [1, 2, 2.5, 5, 10].map(m => m * mag).find(p => p >= alvo) ?? mag * 10);
  return { topo: Math.ceil(max / passo) * passo, passo };
}
function unidade(topo: number): { divisor: number; rotulo: string } {
  const reais = topo / 100;
  if (reais >= 1_000_000) return { divisor: 100_000_000, rotulo: "R$ mi" };
  if (reais >= 10_000) return { divisor: 100_000, rotulo: "R$ mil" };
  return { divisor: 100, rotulo: "R$" };
}

// F-83: o passo de cada mes vem da largura do conteiner (minimo de 64px; abaixo disso o grafico rola). O texto do
// eixo nao escala: so' o vao entre os meses e a largura das barras crescem.
const PASSO_MIN = 64;
function GraficoAno({ serie }: { serie: MesAno["serie"] }) {
  const medida = useRef<HTMLDivElement>(null);
  const [larg, setLarg] = useState(0);
  useEffect(() => {
    const el = medida.current;
    if (!el) return;
    const medir = () => setLarg(el.clientWidth);
    medir();
    // jsdom (testes) nao tem ResizeObserver: la' a medicao unica basta
    if (typeof ResizeObserver === "undefined") return;
    const observador = new ResizeObserver(medir);
    observador.observe(el);
    return () => observador.disconnect();
  }, []);
  const MARGEM_E = 66, MARGEM_D = 14, VAO = 4, TOPO = 24, ALTURA = 180;
  const PASSO = Math.max(PASSO_MIN, Math.floor((larg - MARGEM_E - MARGEM_D) / Math.max(1, serie.length)));
  const LARG = Math.min(32, Math.max(16, Math.round(PASSO / 4)));
  const BASE = TOPO + ALTURA, H = BASE + 28, W = MARGEM_E + serie.length * PASSO + MARGEM_D;
  const { topo, passo } = escala(Math.max(...serie.map(m => Math.max(m.medido_centavos, m.previsto_centavos))));
  const { divisor, rotulo } = unidade(topo);
  const y = (v: number) => BASE - (v / topo) * ALTURA;
  const alt = (v: number) => (v <= 0 ? 0 : Math.max(2, (v / topo) * ALTURA));
  const grade: number[] = [];
  for (let v = 0; v <= topo + passo / 2; v += passo) grade.push(v);
  return (
    <div ref={medida} className="grafico__medida">
    <svg className="grafico__svg" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Medido e previsto nos últimos 12 meses, na cota da Lotufo, em ${rotulo}. `
        + "Os mesmos números estão na “Tabela por competência”, recolhida logo abaixo."}>
      <text className="g-eixo num" x={MARGEM_E - 8} y={TOPO - 9} textAnchor="end">{rotulo}</text>
      {grade.map(v => (
        <g key={v}>
          <line className={v === 0 ? "g-base" : "g-grade"} x1={MARGEM_E} y1={y(v)} x2={W - MARGEM_D} y2={y(v)} />
          <text className="g-eixo num" x={MARGEM_E - 8} y={y(v) + 4} textAnchor="end">
            {(v / divisor).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}
          </text>
        </g>
      ))}
      {serie.map((m, i) => {
        const cx = MARGEM_E + i * PASSO + PASSO / 2;
        const hp = alt(m.previsto_centavos), hm = alt(m.medido_centavos);
        return (
          <g key={m.competencia}>
            <title>{`${fmtCompetencia(m.competencia)} — previsto ${brl(m.previsto_centavos)} · medido ${brl(m.medido_centavos)}`}</title>
            {hp > 0 ? <rect className="g-previsto" x={cx - VAO / 2 - LARG} y={BASE - hp} width={LARG} height={hp} rx={2.5} />
              : <rect className="g-talo" x={cx - VAO / 2 - LARG} y={BASE - 4} width={LARG} height={4} rx={2} />}
            {hm > 0 ? <rect className="g-execucao" x={cx + VAO / 2} y={BASE - hm} width={LARG} height={hm} rx={2.5} />
              : <rect className="g-talo" x={cx + VAO / 2} y={BASE - 4} width={LARG} height={4} rx={2} />}
            <text className="g-eixo-x" x={cx} y={BASE + 18} textAnchor="middle">{mesCurto(m.competencia)}</text>
          </g>
        );
      })}
    </svg>
    </div>
  );
}

// KPI de uma faixa (D13): valor em Display e rotulo embaixo.
function Kpi({ valorTexto, rotulo, dinheiro = true }: { valorTexto: string; rotulo: string; dinheiro?: boolean }) {
  return (
    <li className={`kpi${dinheiro ? " kpi--dinheiro" : ""}`}>
      <span className="kpi__valor num">{valorTexto}</span>
      <span className="kpi__rotulo">{rotulo}</span>
    </li>
  );
}

function Secao({ id, titulo, acoes, children }:
    { id: string; titulo: string; acoes?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="cartao" aria-labelledby={id}>
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id={id}>{titulo}</h2>
        {acoes && <div className="cartao__acoes">{acoes}</div>}
      </div>
      {children}
    </section>
  );
}

// O que termina, pela regra da lista de Obras (`listaObras.ts`), com o link para ela filtrada.
const PRAZOS = [{ dias: 90, busca: "90", quando: `em ${fmtDias(90)}` }, { dias: 180, busca: "180", quando: "em 6\u00a0meses" }];

/** Largura do contêiner, acompanhada (jsdom não tem ResizeObserver: lá a medição única basta). */
function useLargura() {
  const ref = useRef<HTMLDivElement>(null);
  const [larg, setLarg] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const medir = () => setLarg(el.clientWidth);
    medir();
    if (typeof ResizeObserver === "undefined") return;
    const observador = new ResizeObserver(medir);
    observador.observe(el);
    return () => observador.disconnect();
  }, []);
  return { ref, larg };
}

/** Curva S da carteira (#296): o previsto vigente, o previsto anterior à última repactuação e o medido de execução
 *  ACUMULADOS na janela de 12 meses (`curva_carteira`, a soma das curvas das obras ativas), com a leitura de cada mês
 *  embaixo (passar o ponteiro troca o mês; sem ponteiro, o último). */
function CurvaS({ serie }: { serie: PontoCarteira[] }) {
  const { ref, larg } = useLargura();
  const [sel, setSel] = useState<number | null>(null);
  const acc = useMemo(() => {
    const out: { competencia: string; previsto: number; anterior: number; medido: number }[] = [];
    for (const s of serie) {
      const ant = out[out.length - 1];
      out.push({ competencia: s.competencia, previsto: (ant?.previsto ?? 0) + s.previsto_centavos,
        anterior: (ant?.anterior ?? 0) + s.previsto_anterior_centavos, medido: (ant?.medido ?? 0) + s.medido_centavos });
    }
    return out;
  }, [serie]);
  if (acc.length === 0) return null;
  const ultimo = acc.length - 1;
  const i = Math.min(sel ?? ultimo, ultimo);
  const a = acc[i];
  const W = Math.max(280, larg), H = W < 480 ? 220 : 260, mE = 48, mD = 12, T = 22, B = 30;
  const { topo, passo } = escala(Math.max(1, ...acc.map(x => Math.max(x.previsto, x.anterior, x.medido))));
  const { divisor, rotulo } = unidade(topo);
  const larguraMes = (W - mE - mD) / acc.length;
  const x = (k: number) => mE + (k + 0.5) * larguraMes;
  const y = (v: number) => T + (1 - v / topo) * (H - T - B);
  const linha = (k: "previsto" | "anterior" | "medido") => acc.map((p, n) => `${n ? "L" : "M"}${x(n).toFixed(1)} ${y(p[k]).toFixed(1)}`).join(" ");
  const grade: number[] = [];
  for (let v = 0; v <= topo + passo / 2; v += passo) grade.push(v);
  const pular = Math.max(1, Math.ceil(46 / larguraMes));
  const mover = (ev: React.PointerEvent<SVGRectElement>) => {
    const r = ev.currentTarget.ownerSVGElement?.getBoundingClientRect();
    if (!r || r.width === 0) return;
    const px = ((ev.clientX - r.left) * W) / r.width;
    setSel(Math.max(0, Math.min(ultimo, Math.floor((px - mE) / larguraMes))));
  };
  return (
    <>
      <div ref={ref} className="cart-curva">
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
          aria-label={`Previsto e medido acumulados de ${fmtCompetencia(acc[0].competencia)} a ${fmtCompetencia(acc[ultimo].competencia)}, `
            + `nas obras ativas, na cota da Lotufo. Ao fim, previsto ${brl(acc[ultimo].previsto)}, `
            + `previsto anterior à última repactuação ${brl(acc[ultimo].anterior)} e medido ${brl(acc[ultimo].medido)}.`}>
          <text className="g-eixo num" x={mE - 8} y={T - 10} textAnchor="end">{rotulo}</text>
          {grade.map(v => (
            <g key={v}>
              <line className={v === 0 ? "g-base" : "g-grade"} x1={mE} y1={y(v)} x2={W - mD} y2={y(v)} />
              <text className="g-eixo num" x={mE - 8} y={y(v) + 4} textAnchor="end">
                {(v / divisor).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}
              </text>
            </g>
          ))}
          {acc.map((p, n) => (ultimo - n) % pular === 0
            && <text key={p.competencia} className="g-eixo-x" x={x(n)} y={H - 10} textAnchor="middle">{mesCurto(p.competencia)}</text>)}
          <path className="cart-c-area" d={`${linha("medido")} L${x(ultimo)} ${y(0)} L${x(0)} ${y(0)} Z`} />
          <path className="cart-c-ant" d={linha("anterior")} />
          <path className="cart-c-prev" d={linha("previsto")} />
          <path className="cart-c-med" d={linha("medido")} />
          <line className="cart-c-guia" x1={x(i)} x2={x(i)} y1={T} y2={y(0)} />
          {acc.map((p, n) => (
            <g key={p.competencia}>
              <circle className="cart-c-ponto-prev" cx={x(n)} cy={y(p.previsto)} r={3.5} />
              <circle className="cart-c-ponto-med" cx={x(n)} cy={y(p.medido)} r={4} />
            </g>
          ))}
          <rect x={mE} y={T} width={W - mE - mD} height={H - T - B} fill="transparent"
            onPointerMove={mover} onPointerDown={mover} onPointerLeave={() => setSel(null)} />
        </svg>
      </div>
      <p className="cartao__corpo cart-leitura" role="status">
        Até {fmtCompetencia(a.competencia)}: previsto <span className="num">{brl(a.previsto)}</span> · previsto anterior{" "}
        <span className="num">{brl(a.anterior)}</span> · medido{" "}
        <span className="num">{brl(a.medido)}</span>
      </p>
    </>
  );
}

/** Resumo (a aba padrao): os três números, a curva S e um cartão por contratante. O resto mora em QDOP e Produção. */
function Resumo({ p, ir }: { p: Painel; ir: Ir }) {
  const m = p.mes_ano, k = p.carteira;
  return (
    <>
      <ul className="cart-numeros" aria-label="Os números da carteira">
        <li className="cartao cart-numero">
          <span className="cart-numero__rotulo">Saldo a executar</span>
          <span className="cart-numero__valor num" title={brl(k.saldo_centavos)}>{mi(k.saldo_centavos)}</span>
        </li>
        <li className="cartao cart-numero">
          <span className="cart-numero__rotulo">Medido no ano</span>
          <span className="cart-numero__valor num" title={brl(m.acumulado_ano_centavos)}>{mi(m.acumulado_ano_centavos)}</span>
        </li>
        <li className="cartao cart-numero">
          <span className="cart-numero__rotulo">Faturado no mês</span>
          <span className="cart-numero__valor num" title={brl(m.faturado_mes_centavos)}>{mi(m.faturado_mes_centavos)}</span>
        </li>
      </ul>

      <Secao id="dir-curva" titulo="Previsto e medido acumulados nos últimos 12 meses">
        <CurvaS serie={p.curva_carteira} />
        <div className="legenda">
          <span className="legenda__item"><span className="legenda__chave legenda__chave--previsto" aria-hidden="true" />previsto</span>
          <span className="legenda__item"><span className="legenda__chave legenda__chave--anterior" aria-hidden="true" />previsto anterior à última repactuação</span>
          <span className="legenda__item"><span className="legenda__chave legenda__chave--execucao" aria-hidden="true" />medido</span>
        </div>
      </Secao>

      <h2 className="cart-titulo-secao">Por contratante</h2>
      {k.por_orgao.length === 0 ? <p className="cart-nota-resumo">Nenhum contratante com saldo a executar.</p> : (
        <ul className="cart-contratantes" aria-label="Por contratante">
          {k.por_orgao.map(o => {
            const feito = o.vigente_centavos > 0 ? Math.max(0, Math.min(1, o.medido_centavos / o.vigente_centavos)) : 0;
            return (
              <li key={o.orgao}>
                <Link className="cartao cart-contratante" para={{ tela: "obras" }} busca={o.orgao === "sem órgão" ? undefined : { orgao: o.orgao }} ir={ir}>
                  <h3 className="cart-contratante__nome">{o.orgao}</h3>
                  <span className="cart-contratante__rotulo">Saldo a executar</span>
                  <span className="cart-contratante__valor num" title={brl(o.saldo_centavos)}>{mi(o.saldo_centavos)}</span>
                  <span className="cart-progresso">
                    <span className="cart-progresso__rotulo">% executado</span>
                    <span className="cart-progresso__trilho" role="img" aria-label={`${Math.floor(feito * 100)}% executado`}>
                      <span className="cart-progresso__feito" style={{ width: `${(feito * 100).toFixed(1)}%` }} />
                    </span>
                    <span className="cart-progresso__pct num">{Math.floor(feito * 100)}%</span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}

/** QDOP: o painel do farol (filtro, o que termina, avisos) e a tabela no leiaute do QDOP, pelo farol, com a linha de
 *  total e ate' 2 motivos por obra (o resto nos avisos da obra). */
function Qdop({ p, ir }: { p: Painel; ir: Ir }) {
  const [filtro, setFiltro] = useState<"todas" | "problema" | Obra["farol"]>("todas");
  // o que termina vem da lista de Obras (/api/contratos); undefined = carregando; null = nao carregou
  const [lista, setLista] = useState<ObraLista[] | null | undefined>(undefined);
  useEffect(() => {
    let vivo = true;
    api<ObraLista[]>("/api/contratos").then(l => { if (vivo) setLista(l); }).catch(() => { if (vivo) setLista(null); });
    return () => { vivo = false; };
  }, []);
  const obras = porFarol(p.obras.filter(o => filtro === "todas" || (filtro === "problema" ? o.farol !== "verde" : o.farol === filtro)));
  const soma = (f: (o: Obra) => number) => obras.reduce((t, o) => t + f(o), 0);
  const FILTROS: { id: typeof filtro; rotulo: string }[] = [
    { id: "todas", rotulo: "Todas" }, { id: "problema", rotulo: "Com problema" },
    { id: "vermelho", rotulo: "Crítico" }, { id: "acao", rotulo: "Ação" },
    { id: "atencao", rotulo: "Atenção" }, { id: "verde", rotulo: "Em dia" },
  ];
  return (
    <>
      <Secao id="dir-problema" titulo="Obras pelo farol">
        <div className="cartao__corpo pilha">
          <div className="cart-farois" role="group" aria-label="Filtrar o QDOP pelo farol">
            {FILTROS.map(f => (
              <button key={f.id} type="button" className="cart-farol-btn" aria-pressed={filtro === f.id} onClick={() => setFiltro(f.id)}>
                {f.rotulo}
              </button>
            ))}
          </div>
          <div className="cart-qdop-lado">
            <div>
              <p className="campo__rotulo">Terminam</p>
              <ul className="lista-simples">
                {PRAZOS.map(x => {
                  const n = lista ? filtrarObras(lista, { termina: x.dias }).length : null;
                  return (
                    <li key={x.busca}>
                      <Link para={{ tela: "obras" }} busca={{ termina: x.busca }} ir={ir}>
                        {n === null ? `Obras que terminam ${x.quando}` : n === 1 ? `1 obra termina ${x.quando}` : `${n} obras terminam ${x.quando}`}
                      </Link>
                    </li>
                  );
                })}
              </ul>
              {lista === null && <p className="campo__nota">Não foi possível contar as obras; os links abrem a lista.</p>}
            </div>
            <div>
              <p className="campo__rotulo">Avisos da diretoria</p>
              <p><strong className="num">{p.avisos.length}</strong> {p.avisos.length === 1 ? "aviso" : "avisos"}</p>
              <p><Link para={{ tela: "avisos" }} ir={ir}>Ver os avisos</Link></p>
            </div>
          </div>
        </div>
      </Secao>

      <Secao id="dir-qdop" titulo="QDOP">
        <Rolagem rotulo="QDOP" alta>
          <table className="tabela qdop">
            <caption className="sr-only">QDOP, na cota da Lotufo: as obras pelo farol</caption>
            <thead>
              <tr>
                <th scope="col">Obra</th><th scope="col">Empreita</th><th scope="col" className="col-num">Contratual (PI+VA)</th>
                <th scope="col" className="col-num">Faturado</th><th scope="col" className="col-num">Saldo (contratual − faturado)</th>
                <th scope="col" className="col-num">Desvio (p.p.)</th>
                <th scope="col">Término e vigência</th><th scope="col">Status</th>
                <th scope="col">Farol</th><th scope="col">Motivos</th>
              </tr>
            </thead>
            <tbody>
              {obras.length === 0 && <tr><td colSpan={10}>Nenhuma obra neste farol.</td></tr>}
              {obras.map(o => {
                const { visiveis, mais } = motivosDaLinha(o.motivos);
                return (
                  <tr key={o.contrato_id}>
                    <td><Link className="nome-link truncar truncar--nome" title={o.obra} para={{ tela: "obra", id: o.contrato_id, aba: "medicoes" }} ir={ir}>{o.obra}</Link></td>
                    <td>{o.empreita}{o.direito < 1 ? ` (${pct(o.direito)})` : ""}</td>
                    <td className="col-num dinheiro num">{brl(o.pi_va)}</td><td className="col-num dinheiro num">{brl(o.faturados)}</td>
                    <td className={`col-num dinheiro num${o.saldo < 0 ? " negativo" : ""}`}>{brl(o.saldo)}</td>
                    {/* #296: medido − previsto acumulados ate' o mes fechado, sobre o contratual; embaixo, a linha de base
                        (a anterior a ultima repactuacao quando a obra tem uma) */}
                    {o.desvio_pp == null ? <td className="col-num num">—</td> : (
                      <td className={`col-num num${o.desvio_pp < 0 ? " negativo" : ""}`}>
                        {pp(o.desvio_pp)}
                        <div className="campo__nota" title={o.desvio_base === "anterior" ? "Contra o previsto anterior à última repactuação" : "Contra o previsto vigente"}>
                          {o.desvio_base}
                        </div>
                      </td>
                    )}
                    {/* as duas datas numa coluna so' (as colunas do QDOP cabem a 1366): o termino da execucao e,
                        embaixo, a vigencia */}
                    <td className="num">{data(o.termino)}<div className="campo__nota">vig. {data(o.vigencia)}</div></td>
                    <td className="sem-quebra">{o.status}</td>
                    <td><Selo classe={(FAROL[o.farol] ?? FAROL.atencao).classe} forte={(FAROL[o.farol] ?? FAROL.atencao).forte}>{(FAROL[o.farol] ?? FAROL.atencao).rotulo}</Selo></td>
                    <td>{!o.motivos ? (o.motivo || "—") : visiveis.length === 0 ? "—" : (
                      <ul className="motivos">
                        {visiveis.map(x => <li key={`${x.tipo}-${x.texto}`}>{x.texto}</li>)}
                        {mais > 0 && (
                          <li><Link para={{ tela: "avisos" }} busca={{ obra: String(o.contrato_id) }} ir={ir}>
                            mais {mais}<span className="sr-only"> {mais === 1 ? "motivo" : "motivos"} de {o.obra}</span>
                          </Link></li>
                        )}
                      </ul>
                    )}</td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" colSpan={2}>Total</th>
                <td className="col-num dinheiro num">{brl(soma(o => o.pi_va))}</td>
                <td className="col-num dinheiro num">{brl(soma(o => o.faturados))}</td>
                <td className={`col-num dinheiro num${soma(o => o.saldo) < 0 ? " negativo" : ""}`}>{brl(soma(o => o.saldo))}</td>
                <td colSpan={5} />
              </tr>
            </tfoot>
          </table>
        </Rolagem>
      </Secao>
    </>
  );
}

/** Producao: o mês, onde está o dinheiro, o mês a mês (barras e tabela), os próximos meses e o saldo a executar. */
function Producao({ p }: { p: Painel }) {
  const d = p.dinheiro, m = p.mes_ano, k = p.carteira;
  // "N de M obras protocolaram" vem do /api/inicio. undefined = carregando; null = nao carregou.
  const [mes, setMes] = useState<ResumoMes | null | undefined>(undefined);
  useEffect(() => {
    let vivo = true;
    api<{ resumo: ResumoMes }>("/api/inicio").then(r => { if (vivo) setMes(r.resumo); }).catch(() => { if (vivo) setMes(null); });
    return () => { vivo = false; };
  }, []);
  // "N de M obras ativas protocolaram" e' um KPI do mes (F-64): carregando "…", sem dado "—" com o aviso no rotulo
  const protocolos = mes === undefined ? { v: "…", r: "obras ativas protocolaram" }
    : mes === null ? { v: "—", r: "não foi possível contar os protocolos do mês" }
    : { v: `${mes.obras_protocoladas} de ${mes.obras_ativas}`, r: "obras ativas protocolaram" };
  const totalPrevisto = m.serie.reduce((t, s) => t + s.previsto_centavos, 0);
  const totalMedido = m.serie.reduce((t, s) => t + s.medido_centavos, 0);
  return (
    <>
      <Secao id="dir-mes" titulo={`O mês: ${fmtCompetencia(m.mes)}`}>
        <ul className="kpis cart-kpis--quebra" aria-label="O mês">
          <Kpi valorTexto={brl(m.medido_mes_centavos)} rotulo="medido no mês" />
          <Kpi valorTexto={brl(m.acumulado_ano_centavos)} rotulo="acumulado do ano" />
          <Kpi valorTexto={protocolos.v} rotulo={protocolos.r} dinheiro={false} />
        </ul>
      </Secao>

      <Secao id="dir-dinheiro" titulo="Onde está o dinheiro (cota)">
        <ul className="kpis cart-kpis--quebra" aria-label="Onde está o dinheiro">
          <Kpi valorTexto={brl(d.medido_esperando_nota.valor_centavos)} rotulo="medido esperando nota" />
          <Kpi valorTexto={brl(d.nota_esperando_protocolo.valor_centavos)} rotulo="nota emitida esperando protocolo" />
          <Kpi valorTexto={valor(d.protocolado.valor_centavos)} rotulo="protocolado esperando pagamento" />
          <Kpi valorTexto={brl(d.recebido_mes.valor_centavos)} rotulo="recebido no mês" />
        </ul>
      </Secao>

      <Secao id="dir-grafico" titulo="Mês a mês">
        <div className="cartao__corpo pilha">
          <Rolagem rotulo="Gráfico de medido e previsto nos últimos 12 meses" className="grafico"><GraficoAno serie={m.serie} /></Rolagem>
          <div className="legenda">
            <span className="legenda__item"><span className="legenda__chave legenda__chave--previsto" aria-hidden="true" />previsto</span>
            <span className="legenda__item"><span className="legenda__chave legenda__chave--execucao" aria-hidden="true" />medido</span>
          </div>
          {/* os valores do grafico em texto, para teclado e leitor de tela (o SVG e' role="img") */}
          <details className="detalhes">
            <summary>Tabela por competência</summary>
            <Rolagem rotulo="Previsto e medido nos últimos 12 meses">
              <table className="tabela">
                <caption className="sr-only">Previsto e medido nos últimos 12 meses, na cota da Lotufo</caption>
                <thead>
                  <tr>
                    <th scope="col">Competência</th>
                    <th scope="col" className="col-num">Previsto</th>
                    <th scope="col" className="col-num">Medido</th>
                  </tr>
                </thead>
                <tbody>
                  {m.serie.map((s, i) => (
                    <tr key={s.competencia} className={`linha${i % 2 === 1 ? " par" : ""}`}>
                      <td className="num">{fmtCompetencia(s.competencia)}</td>
                      <td className="col-num dinheiro num">{brl(s.previsto_centavos)}</td>
                      <td className="col-num dinheiro num">{brl(s.medido_centavos)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr><th scope="row">Total</th><td className="col-num dinheiro num">{brl(totalPrevisto)}</td>
                    <td className="col-num dinheiro num">{brl(totalMedido)}</td></tr>
                </tfoot>
              </table>
            </Rolagem>
          </details>
        </div>
      </Secao>

      <div className="cartoes-lado">
        <Secao id="dir-proximos" titulo="Próximos meses">
          <Rolagem rotulo="Próximos meses">
            <table className="tabela tabela--estreita">
              <thead><tr><th scope="col">Mês</th><th scope="col" className="col-num">Faturamento previsto</th></tr></thead>
              <tbody>
                {p.proximos.map(x => (
                  <tr key={x.competencia}><td className="num">{fmtCompetencia(x.competencia)}</td>
                    <td className="col-num dinheiro num">{brl(x.faturamento_previsto_centavos)}</td></tr>
                ))}
              </tbody>
            </table>
          </Rolagem>
        </Secao>

        <Secao id="dir-saldo" titulo="Saldo a executar">
          <ul className="kpis cart-kpis--quebra" aria-label="Saldo a executar">
            <Kpi valorTexto={brl(k.saldo_centavos)} rotulo="saldo a executar" />
            <Kpi valorTexto={brl(k.ritmo_mensal_centavos)} rotulo="ritmo mensal" />
            <Kpi valorTexto={k.meses_de_producao === null ? "—" : `${k.meses_de_producao.toLocaleString("pt-BR")} meses`}
              rotulo="de produção" dinheiro={false} />
          </ul>
          <Rolagem rotulo="Saldo a executar por órgão">
            <table className="tabela tabela--estreita">
              <caption className="sr-only">Saldo a executar por órgão, na cota da Lotufo</caption>
              <thead><tr><th scope="col">Órgão</th><th scope="col" className="col-num">Saldo a executar</th>
                <th scope="col" className="col-num">Participação</th></tr></thead>
              <tbody>
                {k.por_orgao.map(o => (
                  <tr key={o.orgao}><td>{o.orgao}</td><td className="col-num dinheiro num">{brl(o.saldo_centavos)}</td>
                    <td className="col-num num">{fmtPercentual(o.fracao, 1, true)}</td></tr>
                ))}
              </tbody>
              {k.por_orgao.length > 0 && (
                <tfoot><tr><th scope="row">Total</th><td className="col-num dinheiro num">{brl(k.saldo_centavos)}</td>
                  <td className="col-num num">{fmtPercentual(1, 1, true)}</td></tr></tfoot>
              )}
            </table>
          </Rolagem>
        </Secao>
      </div>
    </>
  );
}

export default function Diretoria({ ir, aba = "resumo" }: { ir: Ir; aba?: AbaCarteira }) {
  const [p, setP] = useState<Painel | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    let vivo = true;
    api<Painel>("/api/diretoria")
      .then(d => { if (vivo) setP(d); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, []);

  // as abas sao links (NAVEGACAO.md › Subnavegacao): a aba fica na URL, e trocar de aba nao busca o painel de novo.
  // O "Exportar QDOP" fica ao lado delas, visivel nas tres (e tambem enquanto carrega).
  const abas = (
    <div className="cart-topo">
      <Abas rotulo="Seções da Carteira" atual={aba}
        itens={ABAS_CARTEIRA.map(a => ({ ...a, para: { tela: "carteira" as const, aba: a.id } }))} />
      <a className="btn" href="/api/diretoria/qdop.xlsx"><IconeBaixar className="icone icone--p" /> Exportar QDOP (.xlsx)</a>
    </div>
  );
  if (erro) return <div className="pilha">{abas}<p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro} Recarregue a página para tentar de novo.</p></div>;
  if (!p) return <div className="pilha">{abas}<section className="cartao"><div className="vazio"><p>Carregando…</p></div></section></div>;
  return (
    <div className="pilha">
      {abas}
      {aba === "resumo" && <Resumo p={p} ir={ir} />}
      {aba === "qdop" && <Qdop p={p} ir={ir} />}
      {aba === "producao" && <Producao p={p} />}
    </div>
  );
}
