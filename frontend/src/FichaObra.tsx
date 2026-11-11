import { brl, fmtDias, fmtPercentual } from "./formato";
import { Link } from "./Link";
import Selo from "./Selo";
import { fmtDataPura } from "./tempo";
import "./ficha.css";

// Ficha executiva da obra (#510, aprovada em 06/11/2026): seis cartoes. Desde a #646 ela e' o resumo no
// alto da pagina unica da obra (`ContratoPagina`), que le os dados e os passa para ca'. Desde a #655, no lugar da curva S, o cartao "Ritmo e prazo".
// A cor e' so' da informacao (docs/identidade-visual.md): feito verde, em andamento azul, vence em breve ambar,
// critico vermelho, o resto preto. Quem decide o nivel de prazo e' o servidor (`ficha_obra`).

type Nivel = "critico" | "atencao" | "normal";
type Vencimento = { chave: "execucao" | "vigencia"; rotulo: string; data: string | null; dias: number | null; nivel: Nivel };
type Medicao = { id: number; titulo: string; rotulo: string; competencia: string; valor_centavos: number | null };
export type Ficha = {
  // #646: base de execucao (sem o aditivo de reajuste) e cota da Lotufo; vigente − medido = saldo
  topo: { vigente_centavos: number; medido_centavos: number; saldo_centavos: number; reajuste_centavos: number };
  contrato: { original_centavos: number; original_igual: boolean; tas: number; data_base: string | null };
  // #655: a conta de `prazos.ritmo_e_prazo`, na mesma base do topo; `situacao` nula quando a conta nao fecha
  ritmo: { ritmo_centavos: number | null; saldo_centavos: number; conclusao: string | null; execucao_fim: string | null;
    situacao: "no_prazo" | "atrasa" | null; dias_alem: number | null };
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

function Cartao({ titulo, children, classe = "", lado }: { titulo: string; children: React.ReactNode; classe?: string; lado?: React.ReactNode }) {
  return (
    <section className={`cartao ficha__cartao ${classe}`.trim()} aria-label={titulo}>
      <div className="ficha__cabeca"><h2 className="ficha__titulo">{titulo}</h2>{lado}</div>
      {children}
    </section>
  );
}

/** O cartao "Ritmo e prazo" (#655): no ritmo das 6 ultimas competencias fechadas, a obra termina ate' o fim da
 *  execucao? O selo e' a situacao (verde no prazo, vermelho com os dias alem dele); sem conta, "—" e nenhum selo. */
export function RitmoEPrazo({ ficha }: { ficha: Ficha | null | undefined }) {
  const r = ficha?.ritmo;
  return (
    <section className="cartao ficha__ritmo" aria-label="Ritmo e prazo">
      <div className="ficha__cabeca">
        <h2 className="ficha__titulo">Ritmo e prazo</h2>
        {r?.situacao === "no_prazo" && <Selo classe="selo--ok">No prazo</Selo>}
        {r?.situacao === "atrasa" && r.dias_alem !== null && <Selo classe="selo--acao">{fmtDias(r.dias_alem)} além do prazo</Selo>}
      </div>
      {ficha === undefined ? CARREGANDO : !r ? INDISPONIVEL : (
        <dl className="ficha__ritmo-dados">
          <div><dt>Ritmo mensal</dt><dd>{r.ritmo_centavos === null ? "—" : brl(r.ritmo_centavos)}</dd></div>
          <div><dt>Saldo</dt><dd>{brl(r.saldo_centavos)}</dd></div>
          <div><dt>Conclusão estimada</dt><dd>{data(r.conclusao)}</dd></div>
          <div><dt>Fim da execução</dt><dd>{data(r.execucao_fim)}</dd></div>
        </dl>
      )}
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
