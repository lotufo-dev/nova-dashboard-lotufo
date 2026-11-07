import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { STATUS } from "./ContratoPagina";
import { baseDosValores, brl, fmtDias, fmtPercentual } from "./formato";
import LegendaCor from "./LegendaCor";
import { Link } from "./Link";
import { curvaS, type PontoDaCurva, type PrevistoAnterior } from "./obra";
import type { Origem } from "./rota";
import Selo from "./Selo";
import { fmtDataPura, fmtMesCurto } from "./tempo";
import { Migalhas, VoltarOrigem } from "./Topo";
import "./ficha.css";

// Ficha executiva da obra (#510, aprovada em 06/11/2026): seis cartoes e a curva S numa tela so', sem abas.
// A cor e' so' da informacao (docs/identidade-visual.md): feito verde, em andamento azul, vence em breve ambar,
// critico vermelho, o resto preto. Quem decide o nivel de prazo e de certidao e' o servidor (`ficha_obra`).

type Nivel = "critico" | "atencao" | "normal";
type Cabecalho = {
  id: number; obra: string; orgao: string; instrumento: string; valor_vigente_centavos: number;
  percentual_lotufo_bp: number; execucao_fim: string | null; dias_execucao: number | null;
  vigencia_fim: string | null; dias_vigencia: number | null; status: keyof typeof STATUS;
};
type Saldo = { vigente_centavos: number; vigente_execucao_centavos: number; atestado_execucao_centavos: number; saldo_centavos: number };
type Curva = { pontos: PontoDaCurva[]; saldo: Saldo; anterior: PrevistoAnterior | null };
type Vencimento = { chave: "certidao" | "execucao" | "vigencia"; rotulo: string; data: string | null; dias: number | null; nivel: Nivel };
type Medicao = { id: number; titulo: string; rotulo: string; competencia: string; valor_centavos: number | null };
export type Ficha = {
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

export default function FichaObra({ contratoId, origem }: { contratoId: number; origem: Origem | null }) {
  const [c, setC] = useState<Cabecalho | null>(null);
  const [erro, setErro] = useState("");
  const [curva, setCurva] = useState<Curva | null | undefined>(undefined);
  const [ficha, setFicha] = useState<Ficha | null | undefined>(undefined);

  useEffect(() => {
    let vivo = true;
    setC(null); setErro(""); setCurva(undefined); setFicha(undefined);
    api<Cabecalho>(`/api/contratos/${contratoId}/cabecalho`)
      .then(d => { if (vivo) setC(d); }).catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    api<{ curva?: PontoDaCurva[]; saldo: Saldo; anterior?: PrevistoAnterior | null }>(`/api/contratos/${contratoId}/curva`)
      .then(d => { if (vivo) setCurva({ pontos: d.curva ?? [], saldo: d.saldo, anterior: d.anterior ?? null }); })
      .catch(() => { if (vivo) setCurva(null); });
    api<Ficha>(`/api/contratos/${contratoId}/ficha`)
      .then(d => { if (vivo) setFicha(d); }).catch(() => { if (vivo) setFicha(null); });
    return () => { vivo = false; };
  }, [contratoId]);

  useEffect(() => { document.title = `${c ? c.obra : "Obra"} · grupolotufo`; }, [c]);

  const venc = (chave: Vencimento["chave"]) => ficha?.vencimentos.find(v => v.chave === chave) ?? null;
  const prazo = venc("execucao");
  const cota = c && baseDosValores(c.percentual_lotufo_bp) ? `Consórcio, ${baseDosValores(c.percentual_lotufo_bp)!.replace("cota ", "cota Lotufo ")}` : null;
  const pctExec = curva && curva.saldo.vigente_execucao_centavos > 0 ? curva.saldo.atestado_execucao_centavos / curva.saldo.vigente_execucao_centavos : null;
  const desvio = curva ? desvioDaCurva(curva.pontos, curva.anterior) : null;
  const indisponivel = <p className="erro" role="alert">indisponível agora</p>;
  const carregando = <p className="ficha__nota">Carregando…</p>;

  return (
    <>
      <header className="topbar topbar--detalhe">
        <div className="topbar__linha topbar__linha--quebra">
          <div className="topbar__trilha">
            <VoltarOrigem origem={origem} alemDe={["obras"]} />
            <Migalhas origem={origem} itens={[{ rotulo: "Obras", para: { tela: "obras" } }, { rotulo: c?.obra ?? "Obra" }]} />
          </div>
          <LegendaCor />
        </div>
        <div className="topbar__linha topbar__linha--quebra">
          <h1 className="topbar__titulo topbar__titulo--grande" title={c?.obra}>{c ? c.obra : "Obra"}</h1>
          {c && c.status !== "ativo" && <Selo classe={STATUS[c.status]?.classe ?? ""}>{STATUS[c.status]?.rotulo ?? c.status}</Selo>}
          {c && <p className="topbar__meta topbar__meta--obra">{[c.orgao, `Contrato ${c.instrumento}`, cota].filter(Boolean).join(" · ")}</p>}
        </div>
      </header>

      <div className="pagina ficha">
        {erro && <p className="erro" role="alert">{erro}</p>}
        {!c && !erro && <section className="cartao"><div className="vazio"><p>Carregando a obra…</p></div></section>}
        {c && (
          <>
            <div className="ficha__grade">
              <Cartao titulo="Contrato">
                <p className="ficha__rotulo">Valor vigente</p>
                <p className="ficha__grande ficha__valor">{brl(c.valor_vigente_centavos)}</p>
                {ficha === undefined ? carregando : ficha === null ? indisponivel : (
                  <p className="ficha__rodape">
                    {[ficha.contrato.original_igual ? "original igual" : `original ${brl(ficha.contrato.original_centavos)}`,
                      `${ficha.contrato.tas} ${ficha.contrato.tas === 1 ? "TA" : "TAs"}`,
                      ficha.contrato.data_base ? `data-base ${mesAno(ficha.contrato.data_base)}` : null].filter(Boolean).join(" · ")}
                    {" · "}<Link para={{ tela: "obra", id: contratoId, aba: "contrato" }}>ver contrato</Link>
                  </p>
                )}
              </Cartao>

              <Cartao titulo="Execução" lado={curva ? <span className="ficha__pct info--feito">{pctExec === null ? "—" : fmtPercentual(pctExec, 0)}</span> : undefined}>
                {curva === undefined ? carregando : curva === null ? indisponivel : (
                  <>
                    <div className="ficha__barra" role="progressbar" aria-label="Execução do contrato" aria-valuemin={0} aria-valuemax={100}
                      aria-valuenow={pctExec === null ? undefined : Math.round(Math.min(1, pctExec) * 100)}>
                      <span style={{ width: `${Math.min(100, Math.max(0, (pctExec ?? 0) * 100))}%` }} />
                    </div>
                    <dl className="ficha__linhas">
                      <div><dt>Medido</dt><dd>{brl(curva.saldo.atestado_execucao_centavos)}</dd></div>
                      <div><dt>Saldo</dt><dd className={curva.saldo.saldo_centavos < 0 ? "info--critico" : ""}>{brl(curva.saldo.saldo_centavos)}</dd></div>
                    </dl>
                  </>
                )}
              </Cartao>

              <Cartao titulo="Prazo">
                {ficha === undefined ? carregando : ficha === null || !prazo ? indisponivel : (
                  <p className={`ficha__grande ficha__dias ${INFO[prazo.nivel]}`}>
                    {prazo.dias === null ? "—" : prazo.dias < 0 ? `vencido há ${fmtDias(-prazo.dias)}` : fmtDias(prazo.dias)}</p>
                )}
                <p className="ficha__rodape">execução até {data(c.execucao_fim)} · vigência até {data(c.vigencia_fim)}</p>
              </Cartao>

              <Cartao titulo="Última medição">
                {ficha === undefined ? carregando : ficha === null ? indisponivel : !ficha.ultima_medicao
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

              <Cartao titulo="Em andamento">
                {ficha === undefined ? carregando : ficha === null ? indisponivel : !ficha.em_andamento
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
                {ficha === undefined ? carregando : ficha === null ? indisponivel : (
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
              {curva === undefined ? carregando : curva === null ? indisponivel
                : curva.pontos.length === 0 ? <p className="ficha__nota">—</p>
                : <CurvaFicha pontos={curva.pontos} anterior={curva.anterior} />}
            </section>
          </>
        )}
      </div>
    </>
  );
}
