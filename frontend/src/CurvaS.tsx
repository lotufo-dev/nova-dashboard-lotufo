import { useLayoutEffect, useRef, useState } from "react";
import { brl } from "./Medicoes";
import { curvaS, desviosEmPP, type MarcaAditivo, type PontoDaCurva, type PrevistoAnterior } from "./obra";
import { Link } from "./Link";
import { useHoje } from "./ExecucaoContrato";
import { fmtCompetencia, fmtMesCurto } from "./tempo";

// Curva S da pagina da obra (#160, prototipo aprovado): previsto do cronograma vigente (cinza) contra o medido de
// execucao (indigo), acumulados, com a visao "por mes". Os numeros sao os da API da curva (`/curva`); a tela so'
// acumula e desenha. A tabela por competencia continua na aba Contrato.

type Modo = "acumulado" | "mes";

const ML = 52, MR = 12, MT = 14, MB = 28;

function passoRedondo(max: number): number {
  const bruto = Math.max(1, max) / 5;
  const mag = Math.pow(10, Math.floor(Math.log10(bruto)));
  return ([1, 2, 2.5, 5, 10].find(k => k * mag >= bruto) ?? 10) * mag;
}

function rotuloEixo(centavos: number): string {
  const r = centavos / 100;
  const f = (n: number, casas: number) => n.toLocaleString("pt-BR", { maximumFractionDigits: casas });
  return r >= 1e6 ? `${f(r / 1e6, 1)} mi` : r >= 1e3 ? `${f(r / 1e3, 0)} mil` : f(r, 0);
}

function mesesEntre(a: string, b: string): number {
  const [ya, ma] = a.split("-").map(Number), [yb, mb] = b.split("-").map(Number);
  return (yb - ya) * 12 + (mb - ma);
}

/** `pontos`: undefined = carregando; null = a leitura falhou (nao e' o mesmo que obra sem curva). */
export default function CurvaS({ pontos, contratoId, anterior = null, aditivos = [] }: {
  pontos: PontoDaCurva[] | null | undefined; contratoId: number;
  /** Issue #295: previsto anterior a ultima repactuacao (null = a obra so' tem uma versao) e as marcas dos aditivos. */
  anterior?: PrevistoAnterior | null; aditivos?: MarcaAditivo[] }) {
  const [modo, setModo] = useState<Modo>("acumulado");
  const [largura, setLargura] = useState(0);
  const [sobre, setSobre] = useState<number | null>(null);
  const quadro = useRef<HTMLDivElement>(null);

  // a largura do quadro manda no desenho: o SVG nasce no tamanho em que e' lido (texto sempre de 11px)
  useLayoutEffect(() => {
    const medir = () => setLargura(quadro.current?.clientWidth ?? 0);
    medir();
    window.addEventListener("resize", medir);
    return () => window.removeEventListener("resize", medir);
  }, [pontos]);

  const serie = pontos ? curvaS(pontos, pontos.length > 0 && anterior?.length ? anterior : null) : [];
  const temAnterior = serie.length > 0 && serie[0].acumuladoAnterior !== null;
  const N = serie.length;
  const W = Math.max(300, largura - 24), estreito = W < 560;
  const H = estreito ? 220 : 280;
  const iw = W - ML - MR, ih = H - MT - MB;
  const ultimo = [...serie].reverse().find(p => p.acumuladoMedido !== null);
  const maxV = N === 0 ? 1 : modo === "acumulado"
    ? Math.max(serie[N - 1].acumuladoPrevisto, serie[N - 1].acumuladoAnterior ?? 0, ultimo?.acumuladoMedido ?? 0)
    : Math.max(...serie.map(p => Math.max(p.previsto, p.execucao)));
  const passo = passoRedondo(maxV);
  const topo = Math.max(passo, Math.ceil(maxV / passo) * passo);
  const y = (v: number) => MT + ih - (v / topo) * ih;
  const banda = N > 0 ? iw / N : iw;
  const x = (i: number) => ML + banda * (i + 0.5);
  const grade: number[] = [];
  for (let v = 0; v <= topo + 1; v += passo) grade.push(v);

  const hoje = useHoje();
  const iHoje = N > 0 ? mesesEntre(serie[0].competencia, hoje.slice(0, 7)) + (Number(hoje.slice(8, 10)) - 1) / 30 : -1;
  const xHoje = ML + banda * iHoje;
  const hojeVisivel = N > 0 && iHoje >= 0 && iHoje <= N;

  const cada = Math.max(1, Math.ceil(N / Math.max(1, Math.floor(iw / (estreito ? 56 : 64)))));
  const medidos = serie.map((p, i) => ({ p, i })).filter(({ p }) => p.acumuladoMedido !== null);
  const caminho = (lista: { i: number; v: number }[]) => lista.map(({ i, v }, k) => `${k ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join("");
  const linhaPrevisto = caminho(serie.map((p, i) => ({ i, v: p.acumuladoPrevisto })));
  const linhaAnterior = caminho(serie.map((p, i) => ({ i, v: p.acumuladoAnterior ?? 0 })));
  const marcas = aditivos.map(a => ({ ...a, i: serie.findIndex(p => p.competencia === a.competencia) })).filter(a => a.i >= 0);
  const desvio = desviosEmPP(serie);
  const linhaMedido = caminho(medidos.map(({ p, i }) => ({ i, v: p.acumuladoMedido ?? 0 })));
  const bw = Math.max(2, Math.min(14, banda * 0.36));

  const sel = sobre !== null ? serie[sobre] : null;
  const pp = (n: number) => `${(Math.abs(n) < 0.05 ? 0 : n).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} p.p.`;
  const textoDesvio = desvio && desvio.vigente !== null
    ? ` Desvio em ${fmtCompetencia(desvio.competencia)}, contra o vigente: ${pp(desvio.vigente)}${desvio.anterior !== null ? `; contra o anterior: ${pp(desvio.anterior)}` : ""}.`
    : "";
  const rodape = modo === "acumulado"
    ? (ultimo ? `Até ${fmtCompetencia(ultimo.competencia)}: previsto ${brl(ultimo.acumuladoPrevisto)}, medido ${brl(ultimo.acumuladoMedido ?? 0)}. Previsto do cronograma vigente; medido de execução.${textoDesvio}`
      : "Nenhuma execução medida ainda. Previsto do cronograma vigente.")
    : "Por competência: previsto (cinza) e medido de execução (índigo; mais claro quando ainda é provisório: protocolado, sem atestado).";

  return (
    <section className="cartao curva" aria-labelledby="titulo-curva">
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id="titulo-curva">Curva S</h2>
        <div className="curva__cabeca-acoes">
          <div className="curva__modo" role="group" aria-label="Visão da curva">
            <button type="button" aria-pressed={modo === "acumulado"} onClick={() => setModo("acumulado")}>acumulado</button>
            <button type="button" aria-pressed={modo === "mes"} onClick={() => setModo("mes")}>por mês</button>
          </div>
          <div className="curva__legenda" aria-hidden="true">
            <span><span className="curva__chave curva__chave--previsto" />{temAnterior ? "Previsto vigente" : "Previsto"}</span>
            {temAnterior && <span><span className="curva__chave curva__chave--anterior" />Previsto anterior à última repactuação</span>}
            <span><span className="curva__chave curva__chave--medido" />Medido</span>
          </div>
        </div>
      </div>

      {pontos === undefined && <div className="vazio"><p>Carregando a curva…</p></div>}
      {pontos === null && (
        <div className="cartao__corpo"><p className="erro" role="alert">Não foi possível ler a curva agora. Recarregue a página para tentar de novo.</p></div>
      )}
      {pontos && N === 0 && (
        <div className="vazio">
          <p className="vazio__titulo">Nenhuma competência prevista ou medida</p>
          <p>O previsto vem do <Link para={{ tela: "obra", id: contratoId, aba: "contrato" }} secao="cronograma">cronograma</Link> da obra.</p>
        </div>
      )}

      <div className="curva__quadro" ref={quadro} hidden={!pontos || N === 0}>
        {N > 0 && (
          <svg className="curva__svg" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
            aria-label={`Curva S: previsto e medido ${modo === "acumulado" ? "acumulados" : "por mês"}, de ${fmtCompetencia(serie[0].competencia)} a ${fmtCompetencia(serie[N - 1].competencia)}. Os mesmos números estão na tabela por competência, na aba Contrato.`}
            onMouseLeave={() => setSobre(null)}>
            {grade.map(v => (
              <g key={v}>
                <line className={v === 0 ? "c-base" : "c-grade"} x1={ML} x2={W - MR} y1={y(v)} y2={y(v)} />
                <text className="c-eixo" x={ML - 8} y={y(v) + 4} textAnchor="end">{rotuloEixo(v)}</text>
              </g>
            ))}
            {serie.map((p, i) => i % cada === 0 && (
              <text key={p.competencia} className="c-eixo" x={x(i)} y={H - 8} textAnchor="middle">{fmtMesCurto(p.competencia)}</text>
            ))}
            {hojeVisivel && (
              <g>
                <line className="c-hoje" x1={xHoje} x2={xHoje} y1={MT} y2={MT + ih} />
                <text className="c-hoje-txt" x={xHoje > W - 60 ? xHoje - 4 : xHoje + 4} y={MT + 10}
                  textAnchor={xHoje > W - 60 ? "end" : "start"}>Hoje</text>
              </g>
            )}
            {modo === "acumulado" ? (
              <g>
                {medidos.length > 0 && (
                  <path className="c-area" d={`${linhaMedido}L${x(medidos[medidos.length - 1].i).toFixed(1)} ${y(0)}L${x(medidos[0].i).toFixed(1)} ${y(0)}Z`} />
                )}
                {temAnterior && <path className="c-previsto-anterior" d={linhaAnterior} />}
                <path className="c-previsto" d={linhaPrevisto} />
                {N <= 40 && serie.map((p, i) => <circle key={p.competencia} className="c-previsto-ponto" cx={x(i)} cy={y(p.acumuladoPrevisto)} r={2.5} />)}
                <path className="c-medido" d={linhaMedido} />
                {medidos.map(({ p, i }) => (
                  <circle key={p.competencia} className={`c-medido-ponto${p.provisorio ? " c-medido-ponto--provisorio" : ""}`}
                    cx={x(i)} cy={y(p.acumuladoMedido ?? 0)} r={3} />
                ))}
              </g>
            ) : (
              <g>
                {serie.map((p, i) => (
                  <g key={p.competencia}>
                    {p.previsto > 0 && <rect className="c-barra-previsto" x={x(i) - bw - 1} y={y(p.previsto)} width={bw} height={y(0) - y(p.previsto)} rx={1.5} />}
                    {p.execucao > 0 && <rect className={`c-barra-medido${p.provisorio ? " c-barra-medido--provisorio" : ""}`}
                      x={x(i) + 1} y={y(p.execucao)} width={bw} height={y(0) - y(p.execucao)} rx={1.5} />}
                  </g>
                ))}
              </g>
            )}
            {marcas.map((a, k) => (
              <g key={`${a.data}-${a.nome}`} className="c-aditivo">
                <line className="c-aditivo-linha" x1={x(a.i)} x2={x(a.i)} y1={MT} y2={MT + ih} />
                <text className="c-aditivo-txt" x={x(a.i) + (x(a.i) > W - 110 ? -3 : 3)} y={MT + 22 + (k % 2) * 12}
                  textAnchor={x(a.i) > W - 110 ? "end" : "start"}>{a.nome}</text>
              </g>
            ))}
            {sobre !== null && <line className="c-guia" x1={x(sobre)} x2={x(sobre)} y1={MT} y2={MT + ih} />}
            {serie.map((p, i) => (
              <rect key={p.competencia} className="c-alvo" x={ML + banda * i} y={MT} width={banda} height={ih}
                onMouseEnter={() => setSobre(i)} onClick={() => setSobre(sobre === i ? null : i)} />
            ))}
          </svg>
        )}
        {sel && sobre !== null && (
          <div className="curva__dica" style={{ left: Math.min(x(sobre) + 20, Math.max(0, largura - 230)), top: 16 }}>
            <strong>{fmtCompetencia(sel.competencia)}{sel.provisorio ? " · provisório" : ""}</strong>
            {modo === "acumulado" ? (
              <>
                <div className="linha-dica"><span>Previsto acumulado</span><span>{brl(sel.acumuladoPrevisto)}</span></div>
                <div className="linha-dica"><span>Medido acumulado</span><span>{sel.acumuladoMedido === null ? "—" : brl(sel.acumuladoMedido)}</span></div>
                {sel.acumuladoAnterior !== null && (
                  <div className="linha-dica"><span>Anterior acumulado</span><span>{brl(sel.acumuladoAnterior)}</span></div>
                )}
                {sel.acumuladoMedido !== null && (
                  <div className="linha-dica"><span>Diferença</span><span>{brl(sel.acumuladoMedido - sel.acumuladoPrevisto)}</span></div>
                )}
              </>
            ) : (
              <>
                <div className="linha-dica"><span>Previsto no mês</span><span>{brl(sel.previsto)}</span></div>
                <div className="linha-dica"><span>Medido no mês</span><span>{sel.execucao > 0 ? brl(sel.execucao) : "—"}</span></div>
              </>
            )}
          </div>
        )}
      </div>
      {pontos && N > 0 && <p className="curva__rodape">{rodape}</p>}
    </section>
  );
}
