import { LinhasDoTempo, type StatusDaObra } from "./ExecucaoContrato";
import { brl, fmtDias, fmtPercentual } from "./formato";
import { Link } from "./Link";
import Selo, { Glifo } from "./Selo";
import { fmtDataPura } from "./tempo";
import "./obra.css";
import Falha from "./Falha";

// O alto da pagina da obra (#646), redesenhado na #774: a pagina responde "como esta' esta obra hoje": quanto falta
// executar, se cabe no prazo, onde esta' a medicao e o que pede acao. Tres pecas, na ordem da pergunta:
//  - `FichaObra`: a faixa de numeros (valor vigente, medido, saldo, reajuste contratado) e a barra do executado;
//  - `PrazoDaObra`: um painel so' para o prazo (os dias da execucao, as duas linhas do tempo e o ritmo), no lugar
//    dos cartoes "Prazo", "Proximos vencimentos", "Ritmo e prazo" e "Execucao do contrato", que repetiam as datas;
//  - `MedicoesAgora`: a medicao em andamento e a ultima recebida, na coluna do lado.
// Quem decide o nivel de prazo e' o servidor (`ficha_obra`); o selo das linhas do tempo segue `seloDoPrazo`.

type Nivel = "critico" | "atencao" | "normal";
type Vencimento = { chave: "execucao"; rotulo: string; data: string | null; dias: number | null; nivel: Nivel };
type Medicao = { id: number; titulo: string; rotulo: string; competencia: string; valor_centavos: number | null };
export type Ficha = {
  // #646: base de execucao (sem o aditivo de reajuste) e cota da Lotufo; vigente − medido = saldo
  topo: { vigente_centavos: number; medido_centavos: number; saldo_centavos: number; reajuste_centavos: number };
  contrato: { original_centavos: number; original_igual: boolean; tas: number; data_base: string | null };
  // #655: a conta de `prazos.ritmo_e_prazo`, na mesma base do topo; `situacao` nula quando a conta nao fecha
  ritmo: { ritmo_centavos: number | null; conclusao: string | null;
    situacao: "no_prazo" | "atrasa" | null; dias_alem: number | null };
  ultima_medicao: (Medicao & { recebida_em: string | null; dias_apos_nota: number | null }) | null;
  em_andamento: (Medicao & { etapa: string; desde: string | null }) | null;
  vencimentos: Vencimento[];
};

const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
/** "2026-09" -> "set/2026" (a ficha escreve o mes por extenso curto). */
export function mesAno(c: string): string {
  const m = /^(\d{4})-(\d{2})/.exec(c);
  return m && MESES[Number(m[2]) - 1] ? `${MESES[Number(m[2]) - 1]}/${m[1]}` : c;
}
const diaMes = (iso: string) => { const m = /^\d{4}-(\d{2})-(\d{2})/.exec(iso); return m ? `${m[2]}/${m[1]}` : iso; };
const data = (iso: string | null) => (iso ? fmtDataPura(iso.slice(0, 10)) : "—");
const INDISPONIVEL = <Falha>indisponível agora</Falha>;
const CARREGANDO = <p className="obra-nota">Carregando…</p>;

/** A faixa de numeros da obra, na base de execucao (sem o aditivo de reajuste) e na cota da Lotufo: os numeros vem do
 *  `topo` do servidor. O percentual e a barra sao numero, nao situacao: vao em tinta, sem glifo. */
export default function FichaObra({ ficha }: { ficha: Ficha | null | undefined }) {
  const topo = ficha?.topo;
  const pctExec = topo && topo.vigente_centavos > 0 ? topo.medido_centavos / topo.vigente_centavos : null;
  return (
    <section className="obra-resumo" id="resumo" aria-label="Resumo da obra">
      {ficha === undefined ? CARREGANDO : ficha === null || !topo ? INDISPONIVEL : (
        <>
          <dl className="obra-numeros">
            <div className="obra-numero">
              <dt>Valor vigente</dt>
              <dd>{brl(topo.vigente_centavos)}</dd>
            </div>
            <div className="obra-numero">
              <dt>Medido</dt>
              <dd>{brl(topo.medido_centavos)}</dd>
            </div>
            <div className="obra-numero">
              <dt>Saldo a executar</dt>
              <dd className={topo.saldo_centavos < 0 ? "obra-numero--critico" : undefined}>
                {topo.saldo_centavos < 0 && <Glifo situacao="critico" />}{brl(topo.saldo_centavos)}
              </dd>
            </div>
            {topo.reajuste_centavos !== 0 && (
              <div className="obra-numero">
                <dt>Reajuste contratado</dt>
                <dd>{brl(topo.reajuste_centavos)}</dd>
              </div>
            )}
          </dl>
          <div className="obra-executado">
            <div className="obra-executado__barra" role="progressbar" aria-label="Execução do contrato" aria-valuemin={0} aria-valuemax={100}
              aria-valuenow={pctExec === null ? undefined : Math.round(Math.min(1, pctExec) * 100)}>
              <span style={{ width: `${Math.min(100, Math.max(0, (pctExec ?? 0) * 100))}%` }} />
            </div>
            <span className="obra-executado__pct">{pctExec === null ? "—" : `${fmtPercentual(pctExec, 0)} executado`}</span>
          </div>
          <p className="obra-nota">
            {[ficha.contrato.original_igual ? "original igual" : `original ${brl(ficha.contrato.original_centavos)}`,
              `${ficha.contrato.tas} ${ficha.contrato.tas === 1 ? "TA" : "TAs"}`,
              ficha.contrato.data_base ? `data-base ${mesAno(ficha.contrato.data_base)}` : null].filter(Boolean).join(" · ")}
          </p>
        </>
      )}
    </section>
  );
}

type PrazosDaObra = {
  execucao_inicio?: string | null; vigencia_inicio?: string | null; execucao_fim: string | null; vigencia_fim: string | null;
  status: StatusDaObra; execucao_sem_prazo?: boolean;
};

/** O prazo da obra num painel so': quantos dias faltam para o fim da execucao (o nivel e' do servidor, com o glifo
 *  alem da cor), as linhas do tempo da execucao e da vigencia e, embaixo, a conta do ritmo (#655): no ritmo das 6
 *  ultimas competencias fechadas, a obra termina ate' o fim da execucao? Sem conta, "—" e nenhum selo. */
export function PrazoDaObra({ ficha, prazos }: { ficha: Ficha | null | undefined; prazos: PrazosDaObra }) {
  const r = ficha?.ritmo;
  const exec = ficha?.vencimentos.find(v => v.chave === "execucao") ?? null;
  return (
    <section className="cartao obra-prazo" id="prazo" aria-labelledby="titulo-prazo">
      <div className="cartao__cabeca obra-prazo__cabeca">
        <h2 className="cartao__titulo" id="titulo-prazo">Prazo</h2>
        {r?.situacao === "no_prazo" && <Selo situacao="feito">No prazo</Selo>}
        {r?.situacao === "atrasa" && r.dias_alem !== null && <Selo situacao="critico">{fmtDias(r.dias_alem)} além do prazo</Selo>}
      </div>
      <div className="obra-prazo__corpo">
        <div className="obra-prazo__dias">
          <span className="obra-rotulo">Fim da execução</span>
          {ficha === undefined ? CARREGANDO : ficha === null || !exec ? INDISPONIVEL : (
            <p className={`obra-prazo__numero${exec.nivel === "critico" ? " obra-prazo__numero--critico" : exec.nivel === "atencao" ? " obra-prazo__numero--breve" : ""}`}>
              {exec.nivel !== "normal" && <Glifo situacao={exec.nivel === "critico" ? "critico" : "breve"} />}
              {exec.dias === null ? "—" : exec.dias < 0 ? `vencido há ${fmtDias(-exec.dias)}` : exec.dias === 0 ? "vence hoje" : `em ${fmtDias(exec.dias)}`}
            </p>
          )}
        </div>
        <LinhasDoTempo execucaoInicio={prazos.execucao_inicio ?? null} execucaoFim={prazos.execucao_fim}
          vigenciaInicio={prazos.vigencia_inicio ?? null} vigenciaFim={prazos.vigencia_fim} status={prazos.status}
          execucaoSemPrazo={prazos.execucao_sem_prazo} />
      </div>
      {ficha !== undefined && r && (
        <dl className="obra-ritmo" aria-label="Ritmo e prazo">
          <div><dt>Ritmo mensal</dt><dd>{r.ritmo_centavos === null ? "—" : brl(r.ritmo_centavos)}</dd></div>
          <div><dt>Conclusão estimada</dt><dd>{data(r.conclusao)}</dd></div>
        </dl>
      )}
    </section>
  );
}

/** As medicoes de agora, na coluna do lado: a em andamento (com o passo da vez) e a ultima recebida. */
export function MedicoesAgora({ contratoId, ficha }: { contratoId: number; ficha: Ficha | null | undefined }) {
  return (
    <section className="cartao obra-agora" aria-labelledby="titulo-agora">
      <div className="cartao__cabeca"><h2 className="cartao__titulo" id="titulo-agora">Medições</h2></div>
      {ficha === undefined ? <div className="cartao__corpo">{CARREGANDO}</div> : ficha === null ? <div className="cartao__corpo">{INDISPONIVEL}</div> : (
        <dl className="obra-agora__lista">
          <div>
            <dt className="obra-rotulo">Em andamento</dt>
            {!ficha.em_andamento ? <dd>—</dd> : (
              <dd>
                <Link className="obra-agora__medicao" para={{ tela: "medicao", obra: contratoId, id: ficha.em_andamento.id }}>
                  {ficha.em_andamento.rotulo} · {mesAno(ficha.em_andamento.competencia)}</Link>
                <span className="obra-agora__valor">{brl(ficha.em_andamento.valor_centavos)}</span>
                <Selo situacao="andamento">
                  {ficha.em_andamento.etapa}{ficha.em_andamento.desde && ` desde ${diaMes(ficha.em_andamento.desde)}`}</Selo>
              </dd>
            )}
          </div>
          <div>
            <dt className="obra-rotulo">Última recebida</dt>
            {!ficha.ultima_medicao ? <dd>—</dd> : (
              <dd>
                <Link className="obra-agora__medicao" para={{ tela: "medicao", obra: contratoId, id: ficha.ultima_medicao.id }}>
                  {ficha.ultima_medicao.rotulo} · {mesAno(ficha.ultima_medicao.competencia)}</Link>
                <span className="obra-agora__valor">{brl(ficha.ultima_medicao.valor_centavos)}</span>
                <Selo situacao="feito">
                  {ficha.ultima_medicao.recebida_em ? `recebida em ${data(ficha.ultima_medicao.recebida_em)}` : "recebida"}</Selo>
                {ficha.ultima_medicao.dias_apos_nota !== null && (
                  <span className="obra-nota">{fmtDias(ficha.ultima_medicao.dias_apos_nota)} após a nota</span>
                )}
              </dd>
            )}
          </div>
        </dl>
      )}
    </section>
  );
}
