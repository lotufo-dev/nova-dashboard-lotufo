import { useLayoutEffect, useRef, useState } from "react";
import { brl, fmtDias, fmtPercentual } from "./formato";
import { Link } from "./Link";
import { curvaS, type PontoDaCurva, type PrevistoAnterior } from "./obra";
import { fmtDataPura, fmtMesCurto } from "./tempo";
import "./ficha.css";

// Ficha executiva da obra (#510, aprovada em 06/11/2026): seis cartoes e a curva S. Desde a #646 ela e' o resumo no
// alto da pagina unica da obra (`ContratoPagina`), que le os dados e os passa para ca'.
// A cor e' so' da informacao (docs/identidade-visual.md): feito verde, em andamento azul, vence em breve ambar,
// critico vermelho, o resto preto. Quem decide o nivel de prazo e de certidao e' o servidor (`ficha_obra`).

type Nivel = "critico" | "atencao" | "normal";
type Curva = { pontos: PontoDaCurva[]; anterior: PrevistoAnterior | null };
type Vencimento = { chave: "certidao" | "execucao" | "vigencia"; rotulo: string; data: string | null; dias: number | null; nivel: Nivel };
type Medicao = { id: number; titulo: string; rotulo: string; competencia: string; valor_centavos: number | null };
export type Ficha = {
  // #646: base de execucao (sem o aditivo de reajuste) e cota da Lotufo; vigente − medido = saldo
  topo: { vigente_centavos: number; medido_centavos: number; saldo_centavos: number; reajuste_centavos: number };
  contrato: { original_centavos: number; original_igual: boolean; tas: number; data_base: string | null };
  ultima_medicao: (Medicao & { recebida_em: string | null; dias_apos_nota: number | null }) | null;
  em_andamento: (Medicao & { etapa: string; desde: string | null; outras: number }) | null;
  vencimentos: Vencimento[];
};

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
/** "2026-09" -> "set/2026" (a ficha escreve o mes por extenso curto, como na imagem aprovada). */
export function mesAno(c: string): string {
  const m = /^(\d{4})-(\d{2})/.exec(c);
  return m && MESES[Number(m[2]) - 1] ? `${MESES[Number(m[2]) - 1]}/${m[1]}` : c;
}
const diaMes = (iso: string) => { const m = /^\d{4}-(\d{2})-(\d{2})/.exec(iso); return m ? `${m[2]}/${m[1]}` : iso; };
const data = (iso: string | null) => (iso ? fmtDataPura(iso.slice(0, 10)) : "—");
const INFO: Record<Nivel, string> = { critico: "info--critico", atencao: "info--breve", normal: "" };
const PONTO: Record<Nivel, string> = { critico: "ponto--critico", atencao: "ponto--breve", normal: "ponto--normal" };
const INDISPONIVEL = <p className="erro" role="alert">indisponível agora</p>;
const CARREGANDO = <p className="ficha__nota">Carregando…</p>;

/** O desvio do medido contra o previsto, em pontos percentuais do previsto total, ate' a ultima competencia medida. */
export function desvioDaCurva(pontos: PontoDaCurva[], anterior: PrevistoAnterior | null): { pp: number } | null {
  const serie = curvaS(pontos, anterior);
  const total = serie.length ? serie[serie.length - 1].acumuladoPrevisto : 0;
  const ultimo = [...serie].reverse().find(p => p.acumuladoMedido !== null);
  if (!ultimo || total <= 0) return null;
  return { pp: ((ultimo.acumuladoMedido ?? 0) - ultimo.acumuladoPrevisto) / total * 100 };
}

function Cartao({ titulo, children, classe = "", lado }: { titulo: string; children: React.ReactNode; classe?: string; lado?: React.ReactNode }) {
  return (
    <section className={`cartao ficha__cartao ${classe}`.trim()} aria-label={titulo}>
      <div className="ficha__cabeca"><h2 className="ficha__titulo">{titulo}</h2>{lado}</div>
      {children}
    </section>
  );
}

function CurvaFicha({ pontos, anterior }: { pontos: PontoDaCurva[]; anterior: PrevistoAnterior | null }) {
  const quadro = useRef<HTMLDivElement>(null);
  const [largura, setLargura] = useState(0);
  useLayoutEffect(() => {
    const medir = () => setLargura(quadro.current?.clientWidth ?? 0);
    medir();
    window.addEventListener("resize", medir);
    return () => window.removeEventListener("resize", medir);
  }, []);
  const serie = curvaS(pontos, anterior);
  const N = serie.length;
  const total = N ? serie[N - 1].acumuladoPrevisto : 0;
  // sem medida (jsdom, primeiro quadro) vale 280; medido, acompanha o cartao (no celular cabe em ~240 px) sem estourar
  const W = largura > 0 ? Math.max(160, largura) : 280, H = W < 560 ? 170 : 190;
  // MR deixa espaco para a metade do ultimo rotulo do mes (centralizado no ultimo ponto)
  const ML = 40, MR = 22, MT = 8, MB = 22;
  const iw = W - ML - MR, ih = H - MT - MB;
  const x = (i: number) => ML + (N > 1 ? (iw * i) / (N - 1) : iw / 2);
  const y = (frac: number) => MT + ih - Math.min(1, Math.max(0, frac)) * ih;
  const caminho = (v: (i: number) => number | null) => serie.map((_, i) => ({ i, v: v(i) })).filter(p => p.v !== null)
    .map(({ i, v }, k) => `${k ? "L" : "M"}${x(i).toFixed(1)} ${y(v as number).toFixed(1)}`).join("");
  const cada = Math.max(1, Math.ceil(N / Math.max(1, Math.floor(iw / 60))));
  return (
    <div className="ficha__quadro" ref={quadro}>
      {N > 0 && total > 0 && (
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
          aria-label={`Curva S: previsto e medido acumulados, de ${mesAno(serie[0].competencia)} a ${mesAno(serie[N - 1].competencia)}.`}>
          {[0, 0.2, 0.4, 0.6, 0.8, 1].map(f => (
            <g key={f}>
              <line className={f === 0 ? "c-base" : "c-grade"} x1={ML} x2={W - MR} y1={y(f)} y2={y(f)} />
              <text className="c-eixo" x={ML - 6} y={y(f) + 4} textAnchor="end">{fmtPercentual(f, 0)}</text>
            </g>
          ))}
          {serie.map((p, i) => i % cada === 0 && (
            <text key={p.competencia} className="c-eixo" x={x(i)} y={H - 6} textAnchor="middle">{fmtMesCurto(p.competencia)}</text>
          ))}
          <path className="ficha__previsto" d={caminho(i => serie[i].acumuladoPrevisto / total)} />
          <path className="ficha__medido" d={caminho(i => (serie[i].acumuladoMedido === null ? null : serie[i].acumuladoMedido! / total))} />
        </svg>
      )}
      <div className="ficha__legenda" aria-hidden="true">
        <span><span className="curva__chave curva__chave--previsto" />Previsto acumulado</span>
        <span><span className="curva__chave curva__chave--medido" />Medido acumulado</span>
      </div>
    </div>
  );
}

/** O cartao "Previsto × medido acumulado" da ficha: as duas series e a pilula do desvio. */
export function CurvaDaFicha({ curva }: { curva: Curva | null | undefined }) {
  const desvio = curva ? desvioDaCurva(curva.pontos, curva.anterior) : null;
  return (
    <section className="cartao ficha__curva" aria-label="Previsto × medido acumulado">
      <div className="ficha__curva-cabeca">
        <h2 className="ficha__titulo">Previsto × medido acumulado</h2>
        {desvio && (
          <span className="pilula-info pilula-info--andamento">
            {Math.abs(desvio.pp) < 0.05 ? "medido no previsto"
              : <>medido <strong>{fmtPercentual(Math.abs(desvio.pp) / 100, 1)}</strong> {desvio.pp < 0 ? "abaixo" : "acima"} do previsto</>}
          </span>
        )}
      </div>
      {curva === undefined ? CARREGANDO : curva === null ? INDISPONIVEL
        : curva.pontos.length === 0 ? <p className="ficha__nota">—</p>
        : <CurvaFicha pontos={curva.pontos} anterior={curva.anterior} />}
    </section>
  );
}

/** Os seis cartoes do resumo da obra, no alto da pagina unica (#646). Valor vigente, medido e saldo vem do `topo` do
 *  servidor: base de execucao (sem o aditivo de reajuste) e cota da Lotufo; o reajuste contratado vai a parte. */
export default function FichaObra({ contratoId, prazos, ficha }:
    { contratoId: number; prazos: { execucao_fim: string | null; vigencia_fim: string | null }; ficha: Ficha | null | undefined }) {
  const venc = (chave: Vencimento["chave"]) => ficha?.vencimentos.find(v => v.chave === chave) ?? null;
  const prazo = venc("execucao");
  const topo = ficha?.topo;
  const pctExec = topo && topo.vigente_centavos > 0 ? topo.medido_centavos / topo.vigente_centavos : null;

  return (
    <div className="ficha__grade" id="resumo">
      <Cartao titulo="Contrato">
        <p className="ficha__rotulo">Valor vigente</p>
        {ficha === undefined ? CARREGANDO : ficha === null ? INDISPONIVEL : (
          <>
            <p className="ficha__grande ficha__valor">{brl(ficha.topo.vigente_centavos)}</p>
            {ficha.topo.reajuste_centavos !== 0 && (
              <dl className="ficha__linhas"><div><dt>Reajuste</dt><dd>{brl(ficha.topo.reajuste_centavos)}</dd></div></dl>
            )}
            <p className="ficha__rodape">
              {[ficha.contrato.original_igual ? "original igual" : `original ${brl(ficha.contrato.original_centavos)}`,
                `${ficha.contrato.tas} ${ficha.contrato.tas === 1 ? "TA" : "TAs"}`,
                ficha.contrato.data_base ? `data-base ${mesAno(ficha.contrato.data_base)}` : null].filter(Boolean).join(" · ")}
            </p>
          </>
        )}
      </Cartao>

      <Cartao titulo="Execução" lado={topo ? <span className="ficha__pct info--feito">{pctExec === null ? "—" : fmtPercentual(pctExec, 0)}</span> : undefined}>
        {ficha === undefined ? CARREGANDO : ficha === null ? INDISPONIVEL : (
          <>
            <div className="ficha__barra" role="progressbar" aria-label="Execução do contrato" aria-valuemin={0} aria-valuemax={100}
              aria-valuenow={pctExec === null ? undefined : Math.round(Math.min(1, pctExec) * 100)}>
              <span style={{ width: `${Math.min(100, Math.max(0, (pctExec ?? 0) * 100))}%` }} />
            </div>
            <dl className="ficha__linhas">
              <div><dt>Medido</dt><dd>{brl(ficha.topo.medido_centavos)}</dd></div>
              <div><dt>Saldo</dt><dd className={ficha.topo.saldo_centavos < 0 ? "info--critico" : ""}>{brl(ficha.topo.saldo_centavos)}</dd></div>
            </dl>
          </>
        )}
      </Cartao>

      <Cartao titulo="Prazo">
        {ficha === undefined ? CARREGANDO : ficha === null || !prazo ? INDISPONIVEL : (
          <p className={`ficha__grande ficha__dias ${INFO[prazo.nivel]}`}>
            {prazo.dias === null ? "—" : prazo.dias < 0 ? `vencido há ${fmtDias(-prazo.dias)}` : fmtDias(prazo.dias)}</p>
        )}
        <p className="ficha__rodape">execução até {data(prazos.execucao_fim)} · vigência até {data(prazos.vigencia_fim)}</p>
      </Cartao>

      <Cartao titulo="Última medição">
        {ficha === undefined ? CARREGANDO : ficha === null ? INDISPONIVEL : !ficha.ultima_medicao
          ? <p className="ficha__nota">—</p> : (
            <>
              <p className="ficha__medicao">
                <Link para={{ tela: "medicao", obra: contratoId, id: ficha.ultima_medicao.id }}>
                  {ficha.ultima_medicao.rotulo} · {mesAno(ficha.ultima_medicao.competencia)} · {brl(ficha.ultima_medicao.valor_centavos)}</Link></p>
              <p className="ficha__rodape info--feito">
                {ficha.ultima_medicao.recebida_em ? `recebida em ${data(ficha.ultima_medicao.recebida_em)}` : "recebida"}
                {ficha.ultima_medicao.dias_apos_nota !== null && `, ${fmtDias(ficha.ultima_medicao.dias_apos_nota)} após a nota`}</p>
            </>
          )}
      </Cartao>

      <Cartao titulo="Medição em andamento">
        {ficha === undefined ? CARREGANDO : ficha === null ? INDISPONIVEL : !ficha.em_andamento
          ? <p className="ficha__nota">—</p> : (
            <>
              <p className="ficha__medicao">
                <Link para={{ tela: "medicao", obra: contratoId, id: ficha.em_andamento.id }}>
                  {ficha.em_andamento.rotulo} · {mesAno(ficha.em_andamento.competencia)} · {brl(ficha.em_andamento.valor_centavos)}</Link></p>
              <p className="ficha__rodape">
                <span className="pilula-info pilula-info--andamento">
                  {ficha.em_andamento.etapa}{ficha.em_andamento.desde && ` desde ${diaMes(ficha.em_andamento.desde)}`}</span>
              </p>
            </>
          )}
      </Cartao>

      <Cartao titulo="Próximos vencimentos">
        {ficha === undefined ? CARREGANDO : ficha === null ? INDISPONIVEL : (
          <ul className="ficha__venc">
            {ficha.vencimentos.map(v => (
              <li key={v.chave}>
                <span className={`ponto ${PONTO[v.nivel]}`} aria-hidden="true" />
                <span className="ficha__venc-rotulo">{v.rotulo}</span>
                <span className={`ficha__venc-data ${INFO[v.nivel]}`}>{data(v.data)}</span>
              </li>
            ))}
          </ul>
        )}
      </Cartao>
    </div>
  );
}
