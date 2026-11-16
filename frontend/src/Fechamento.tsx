import { Fragment, useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import CaixaAviso from "./CaixaAviso";
import Contador from "./Contador";
import { brl, contar } from "./formato";
import { Link } from "./Link";
import { tituloMedicao } from "./medicao";
import Rolagem from "./Rolagem";
import { type Busca, type Ir } from "./rota";
import Selo from "./Selo";
import { fmtCompetencia, fmtDataPura, fmtMesExtenso } from "./tempo";
import "./fechamento.css";

// Fechamento (#748): o que foi medido, aprovado, protocolado e recebido em cada mes de competencia de 2025 e 2026, na
// cota da Lotufo, e o que esta' em aberto, nota a nota. Os numeros vem prontos do servidor (`app/fechamento.py`), ja'
// somados mes a mes, obra a obra e medicao a medicao: a tela nao soma nem estima nada. O mes de todo numero e' a
// competencia da medicao (a nota e o recebimento, a da medicao a que a nota esta' ligada).
//
// Duas pecas nao existiam na fundacao e ficam com duas variantes, para o dono escolher (`?variante=b` mostra a B das
// duas): a tabela que abre por obra e por medicao (A: as linhas abrem na propria tabela; B: o mes abre um quadro com
// uma tabela por obra) e a comparacao entre os anos (A: painel proprio "2026 × 2025"; B: o mesmo mes do outro ano
// embaixo de cada valor, na tabela do mes).

type Numeros = {
  medido_centavos: number; aprovado_centavos: number; protocolado_centavos: number; recebido_centavos: number;
  em_aberto_centavos: number;
};
type NotaLinha = { nota_id: number; numero: string; valor_centavos: number; recebida: boolean };
type MedicaoLinha = Numeros & {
  medicao_id: number; contrato_id: number; obra: string; numero: number; tipo: string; estado: string;
  competencia: string; protocolo_em: string | null; notas: NotaLinha[];
};
type ObraLinha = Numeros & { contrato_id: number; obra: string; medicoes: MedicaoLinha[] };
type Mes = Numeros & { competencia: string; obras: ObraLinha[] };
type EmAberto = {
  nota_id: number; numero: string; contrato_id: number; obra: string; medicao_id: number; medicao_numero: number;
  tipo: string; competencia: string; protocolo_em: string | null; valor_centavos: number;
};
type Contagem = { quantidade: number; valor_centavos: number };
export type RespostaFechamento = {
  anos: string[]; meses: Mes[]; por_ano: Record<string, Numeros & { meses: number }>;
  acumulado: { ate_mes: string | null } & Record<string, Numeros | string | null>;
  em_aberto: EmAberto[]; em_aberto_centavos: number; em_aberto_anteriores: Contagem; notas_sem_medicao: Contagem;
};

const COLUNAS: { chave: keyof Numeros; rotulo: string }[] = [
  { chave: "medido_centavos", rotulo: "Medido" }, { chave: "aprovado_centavos", rotulo: "Aprovado" },
  { chave: "protocolado_centavos", rotulo: "Protocolado" }, { chave: "recebido_centavos", rotulo: "Recebido" },
  { chave: "em_aberto_centavos", rotulo: "Em aberto" },
];
const COMPARAVEIS = COLUNAS.slice(0, 4);

/** Zero em mes com lancamento nao e' numero a ler: "—". */
function valor(c: number): string {
  return c === 0 ? "—" : brl(c);
}
function nomeMes(comp: string): string {
  const n = fmtMesExtenso(comp);
  return n.charAt(0).toUpperCase() + n.slice(1);
}
function outroAno(anos: string[], ano: string): string | null {
  return anos.find(a => a !== ano) ?? null;
}
function doAcumulado(f: RespostaFechamento, ano: string): Numeros | null {
  const x = f.acumulado[ano];
  return x && typeof x === "object" ? x : null;
}

/* ------------------------------------------------------------------ numeros do ano */

function NumerosDoAno({ f, ano }: { f: RespostaFechamento; ano: string }) {
  const t = f.por_ano[ano];
  return (
    <dl className="fch-numeros" aria-label={`Totais de ${ano}`}>
      {COLUNAS.map(c => (
        <div key={c.chave} className="fch-numero">
          <dt className="fch-numero__rotulo">{c.rotulo}</dt>
          <dd className="fch-numero__valor">{t ? valor(t[c.chave]) : "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ------------------------------------------------------------------ tabela do mes */

function Celulas({ x, outro }: { x: Numeros; outro?: { ano: string; x: Numeros | null } }) {
  return (
    <>
      {COLUNAS.map(c => (
        <td key={c.chave} className="col-num dinheiro num">
          {valor(x[c.chave])}
          {outro && c.chave !== "em_aberto_centavos" && (
            <span className="fch-outro"><span className="sr-only">mesmo mês de </span>{outro.ano}: {outro.x ? valor(outro.x[c.chave]) : "—"}</span>
          )}
        </td>
      ))}
    </>
  );
}

function Notas({ m }: { m: MedicaoLinha }) {
  if (m.notas.length === 0) return null;
  return (
    <ul className="fch-notas">
      {m.notas.map(n => (
        <li key={n.nota_id}>
          <span className="num">Nota {n.numero}</span>
          <Selo situacao={n.recebida ? "feito" : "andamento"}>{n.recebida ? "recebida" : "em aberto"}</Selo>
        </li>
      ))}
    </ul>
  );
}

function BotaoAbre({ aberto, controla, rotulo, children, onClick }:
    { aberto: boolean; controla: string; rotulo: string; children: React.ReactNode; onClick: () => void }) {
  return (
    <button type="button" className="fch-abre" aria-expanded={aberto} aria-controls={controla} aria-label={rotulo} onClick={onClick}>
      <span className="fch-abre__seta" aria-hidden="true" />{children}
    </button>
  );
}

type Abertos = { tem: (k: string) => boolean; trocar: (k: string) => void };

/** Variante A: o mes abre as obras, e a obra abre as medicoes, na propria tabela, com as colunas alinhadas. */
function LinhasA({ m, ab, ir }: { m: Mes; ab: Abertos; ir: Ir }) {
  if (!ab.tem(m.competencia)) return null;
  return (
    <>
      {m.obras.map((o, i) => {
        const chave = `${m.competencia}:${o.contrato_id}`;
        const id = `fch-obra-${m.competencia}-${o.contrato_id}`;
        return (
          <Fragment key={chave}>
            <tr className="fch-linha fch-linha--obra" id={i === 0 ? `fch-mes-${m.competencia}` : undefined}>
              <th scope="row" className="fch-primeira">
                <BotaoAbre aberto={ab.tem(chave)} controla={id} rotulo={`${o.obra}, medições de ${fmtCompetencia(m.competencia)}`}
                  onClick={() => ab.trocar(chave)}>{o.obra}</BotaoAbre>
              </th>
              <Celulas x={o} />
            </tr>
            {ab.tem(chave) && o.medicoes.map((md, j) => (
              <tr key={md.medicao_id} className="fch-linha fch-linha--medicao" id={j === 0 ? id : undefined}>
                <th scope="row" className="fch-primeira">
                  <Link className="link" para={{ tela: "medicao", obra: md.contrato_id, id: md.medicao_id }} ir={ir}>{tituloMedicao(md)}</Link>
                  <Notas m={md} />
                </th>
                <Celulas x={md} />
              </tr>
            ))}
          </Fragment>
        );
      })}
    </>
  );
}

/** Variante B: o mes abre um quadro, com uma tabela curta por obra (as medicoes e o subtotal da obra). */
function QuadroB({ m, ir }: { m: Mes; ir: Ir }) {
  return (
    <tr className="fch-quadro" id={`fch-mes-${m.competencia}`}>
      <td colSpan={COLUNAS.length + 1}>
        <div className="fch-quadro__corpo">
          {m.obras.map(o => (
            <section key={o.contrato_id} className="fch-quadro__obra" aria-label={`${o.obra}, ${fmtCompetencia(m.competencia)}`}>
              <h3 className="fch-quadro__titulo">{o.obra}</h3>
              <table className="tabela fch-quadro__tabela">
                <caption className="sr-only">Medições de {o.obra} em {fmtCompetencia(m.competencia)}, na cota da Lotufo</caption>
                <thead><tr><th scope="col">Medição</th>{COLUNAS.map(c => <th key={c.chave} scope="col" className="col-num">{c.rotulo}</th>)}</tr></thead>
                <tbody>
                  {o.medicoes.map(md => (
                    <tr key={md.medicao_id}>
                      <th scope="row">
                        <Link className="link" para={{ tela: "medicao", obra: md.contrato_id, id: md.medicao_id }} ir={ir}>{tituloMedicao(md)}</Link>
                        <Notas m={md} />
                      </th>
                      <Celulas x={md} />
                    </tr>
                  ))}
                </tbody>
                {o.medicoes.length > 1 && <tfoot><tr><th scope="row">Total da obra</th><Celulas x={o} /></tr></tfoot>}
              </table>
            </section>
          ))}
        </div>
      </td>
    </tr>
  );
}

function TabelaDoAno({ f, ano, variante, ir }: { f: RespostaFechamento; ano: string; variante: "a" | "b"; ir: Ir }) {
  const [abertos, setAbertos] = useState<Set<string>>(new Set());
  const ab: Abertos = {
    tem: k => abertos.has(k),
    trocar: k => setAbertos(s => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; }),
  };
  const meses = f.meses.filter(m => m.competencia.startsWith(`${ano}-`));
  const outro = variante === "b" ? outroAno(f.anos, ano) : null;
  const doOutro = (comp: string) => outro ? f.meses.find(m => m.competencia === `${outro}${comp.slice(4)}`) ?? null : null;
  if (meses.length === 0) return <p className="fch-vazio">Nenhum lançamento em {ano}.</p>;
  const ate = f.acumulado.ate_mes;
  return (
    <Rolagem rotulo={`Por mês de competência, ${ano}`} className="tabela-wrap fch-rolagem">
      <table className={`tabela fch-tabela${variante === "b" ? " fch-tabela--b" : ""}`}>
        <caption className="sr-only">Medido, aprovado, protocolado, recebido e em aberto por mês de competência de {ano}, na cota da Lotufo</caption>
        <thead>
          <tr>
            <th scope="col" className="fch-primeira">Mês</th>
            {COLUNAS.map(c => <th key={c.chave} scope="col" className="col-num">{c.rotulo}</th>)}
          </tr>
        </thead>
        <tbody>
          {meses.map(m => (
            <Fragment key={m.competencia}>
              <tr className="fch-linha fch-linha--mes">
                <th scope="row" className="fch-primeira">
                  <BotaoAbre aberto={ab.tem(m.competencia)} controla={`fch-mes-${m.competencia}`}
                    rotulo={`${nomeMes(m.competencia)} de ${ano}, por obra`} onClick={() => ab.trocar(m.competencia)}>
                    {nomeMes(m.competencia)}
                  </BotaoAbre>
                </th>
                <Celulas x={m} outro={outro ? { ano: outro, x: doOutro(m.competencia) } : undefined} />
              </tr>
              {variante === "a" ? <LinhasA m={m} ab={ab} ir={ir} /> : ab.tem(m.competencia) && <QuadroB m={m} ir={ir} />}
            </Fragment>
          ))}
        </tbody>
        <tfoot>
          <tr><th scope="row" className="fch-primeira">Total de {ano}</th><Celulas x={f.por_ano[ano]} /></tr>
          {variante === "b" && ate && f.anos.map(a => doAcumulado(f, a) && (
            <tr key={a} className="fch-acumulado">
              <th scope="row" className="fch-primeira">{a}, até {fmtMesExtenso(`${a}-${ate}`)}</th>
              <Celulas x={doAcumulado(f, a) as Numeros} />
            </tr>
          ))}
        </tfoot>
      </table>
    </Rolagem>
  );
}

/* ------------------------------------------------------------------ comparacao (variante A) */

function Comparacao({ f }: { f: RespostaFechamento }) {
  const [chave, setChave] = useState<keyof Numeros>("medido_centavos");
  const [a, b] = f.anos;
  const porMes = new Map(f.meses.map(m => [m.competencia, m]));
  const mms = [...new Set(f.meses.map(m => m.competencia.slice(5)))].sort();
  const ate = f.acumulado.ate_mes;
  if (mms.length === 0) return null;
  const rotulo = COMPARAVEIS.find(c => c.chave === chave)?.rotulo ?? "";
  return (
    <section className="cartao fch-painel" aria-labelledby="fch-comparacao">
      <div className="fch-painel__cab">
        <h2 id="fch-comparacao">{b} × {a}</h2>
        <div className="fch-botoes" role="group" aria-label="Número comparado">
          {COMPARAVEIS.map(c => (
            <button key={c.chave} type="button" className="fch-botao" aria-pressed={chave === c.chave} onClick={() => setChave(c.chave)}>{c.rotulo}</button>
          ))}
        </div>
      </div>
      <Rolagem rotulo={`${rotulo}: ${b} e ${a}, mês a mês`} className="tabela-wrap fch-rolagem">
        <table className="tabela fch-tabela fch-tabela--comparacao">
          <caption className="sr-only">{rotulo} por mês de competência, {a} e {b}, na cota da Lotufo</caption>
          <thead><tr><th scope="col" className="fch-primeira">Mês</th><th scope="col" className="col-num">{a}</th><th scope="col" className="col-num">{b}</th></tr></thead>
          <tbody>
            {mms.map(mm => {
              const x = porMes.get(`${a}-${mm}`), y = porMes.get(`${b}-${mm}`);
              return (
                <tr key={mm}>
                  <th scope="row" className="fch-primeira">{nomeMes(`${a}-${mm}`)}</th>
                  <td className="col-num dinheiro num">{x ? valor(x[chave]) : "—"}</td>
                  <td className="col-num dinheiro num">{y ? valor(y[chave]) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            {ate && (
              <tr>
                <th scope="row" className="fch-primeira">Até {fmtMesExtenso(`${b}-${ate}`)}</th>
                <td className="col-num dinheiro num">{valor(doAcumulado(f, a)?.[chave] ?? 0)}</td>
                <td className="col-num dinheiro num">{valor(doAcumulado(f, b)?.[chave] ?? 0)}</td>
              </tr>
            )}
            <tr>
              <th scope="row" className="fch-primeira">Ano</th>
              <td className="col-num dinheiro num">{valor(f.por_ano[a]?.[chave] ?? 0)}</td>
              <td className="col-num dinheiro num">{valor(f.por_ano[b]?.[chave] ?? 0)}</td>
            </tr>
          </tfoot>
        </table>
      </Rolagem>
    </section>
  );
}

/* ------------------------------------------------------------------ em aberto */

function EmAbertoPainel({ f, ir }: { f: RespostaFechamento; ir: Ir }) {
  const n = f.em_aberto.length;
  return (
    <section className="cartao fch-painel" aria-labelledby="fch-aberto">
      <div className="fch-painel__cab">
        <h2 id="fch-aberto">Em aberto</h2>
        <Contador rotulo={contar(n, "nota", "notas")}>{n}</Contador>
      </div>
      {n === 0 ? <p className="fch-vazio">Nenhuma nota em aberto.</p> : (
        <Rolagem rotulo="Notas em aberto" className="tabela-wrap fch-rolagem">
          <table className="tabela fch-tabela fch-tabela--aberto">
            <caption className="sr-only">Notas protocoladas ainda não recebidas, pela data do protocolo, na cota da Lotufo</caption>
            <thead>
              <tr>
                <th scope="col" className="fch-primeira">Protocolo</th><th scope="col">Obra</th><th scope="col">Medição</th>
                <th scope="col">Nota</th><th scope="col" className="col-num">Valor</th>
              </tr>
            </thead>
            <tbody>
              {f.em_aberto.map(e => (
                <tr key={`${e.nota_id}-${e.medicao_id}`}>
                  <th scope="row" className="fch-primeira num">{e.protocolo_em ? fmtDataPura(e.protocolo_em) : "—"}</th>
                  <td>{e.obra}</td>
                  <td>
                    <Link className="link" para={{ tela: "medicao", obra: e.contrato_id, id: e.medicao_id }} ir={ir}>
                      {tituloMedicao({ numero: e.medicao_numero, tipo: e.tipo })}
                    </Link>
                    <span className="fch-sub num">{fmtCompetencia(e.competencia)}</span>
                  </td>
                  <td className="num">{e.numero}</td>
                  <td className="col-num dinheiro num">{brl(e.valor_centavos)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot><tr><th scope="row" className="fch-primeira" colSpan={4}>Total</th><td className="col-num dinheiro num">{brl(f.em_aberto_centavos)}</td></tr></tfoot>
          </table>
        </Rolagem>
      )}
      {(f.notas_sem_medicao.quantidade > 0 || f.em_aberto_anteriores.quantidade > 0) && (
        <dl className="fch-aparte">
          {f.notas_sem_medicao.quantidade > 0 && (
            <div><dt>Notas sem medição ligada ({f.anos.join(" e ")})</dt>
              <dd><span className="num">{contar(f.notas_sem_medicao.quantidade, "nota", "notas")}</span> · <span className="num">{brl(f.notas_sem_medicao.valor_centavos)}</span></dd></div>
          )}
          {f.em_aberto_anteriores.quantidade > 0 && (
            <div><dt>Em aberto de competências anteriores a {f.anos[0]}</dt>
              <dd><span className="num">{contar(f.em_aberto_anteriores.quantidade, "nota", "notas")}</span> · <span className="num">{brl(f.em_aberto_anteriores.valor_centavos)}</span></dd></div>
          )}
        </dl>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ pagina */

export default function Fechamento({ ir, busca = {} }: { ir: Ir; busca?: Busca }) {
  const [f, setF] = useState<RespostaFechamento | null>(null);
  const [erro, setErro] = useState("");
  const [ano, setAno] = useState<string | null>(null);
  const variante = busca.variante === "b" ? "b" : "a";
  useEffect(() => {
    let vivo = true;
    api<RespostaFechamento>("/api/fechamento").then(d => { if (vivo) setF(d); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, []);
  if (erro) return <CaixaAviso nivel="critico" role="alert">Não foi possível carregar o fechamento: {erro} Recarregue a página para tentar de novo.</CaixaAviso>;
  if (!f) return <p className="fch-vazio">Carregando…</p>;
  const atual = ano ?? f.anos[f.anos.length - 1];
  return (
    <div className="fch">
      <div className="fch-cota">
        <h2>Cota da Lotufo</h2>
        <div className="fch-botoes" role="group" aria-label="Ano">
          {[...f.anos].reverse().map(a => (
            <button key={a} type="button" className="fch-botao" aria-pressed={atual === a} onClick={() => setAno(a)}>{a}</button>
          ))}
        </div>
      </div>
      <NumerosDoAno f={f} ano={atual} />
      <section className="cartao fch-painel" aria-labelledby="fch-meses">
        <div className="fch-painel__cab"><h2 id="fch-meses">Por mês de competência</h2></div>
        <TabelaDoAno key={atual} f={f} ano={atual} variante={variante} ir={ir} />
      </section>
      {variante === "a" && <Comparacao f={f} />}
      <EmAbertoPainel f={f} ir={ir} />
    </div>
  );
}
