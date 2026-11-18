import { Fragment, useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import CaixaAviso from "./CaixaAviso";
import Contador from "./Contador";
import Diferenca from "./Diferenca";
import { brl, contar } from "./formato";
import { Link } from "./Link";
import MarcaEtapa from "./MarcaEtapa";
import { tituloMedicao } from "./medicao";
import Rolagem from "./Rolagem";
import { type Ir } from "./rota";
import Selo from "./Selo";
import { fmtCompetencia, fmtDataPura, fmtMesCurto, fmtMesExtenso } from "./tempo";
import { diferenca, variacao, type Etapa } from "./valores";
import Variacao from "./Variacao";
import "./fechamento.css";
import Falha from "./Falha";

// Fechamento (#748): o que foi medido, aprovado, protocolado e recebido em cada mes de competencia de 2025 e 2026, na
// cota da Lotufo, e o que esta' em aberto, nota a nota. Os numeros vem prontos do servidor (`app/fechamento.py`), ja'
// somados mes a mes, obra a obra e medicao a medicao: a tela nao soma nem estima nada. O mes de todo numero e' a
// competencia da medicao (a nota e o recebimento, a da medicao a que a nota esta' ligada).
//
// Duas pecas nao existiam na fundacao (decisao do dono de 16/11/2026): o mes abre as obras, e a obra as medicoes, como
// linhas recuadas da mesma tabela; a comparacao entre os anos fica em painel proprio ("2026 × 2025").
//
// #805 (decisao do dono de 18/11/2026): a tabela do mes leva as familias de valor. O cabecalho de cada coluna traz a
// marca da etapa do dinheiro; o medido de cada mes encerrado diz a variacao contra o mesmo mes do ano anterior; o
// aprovado diz a diferenca contra o pedido, so' das medicoes que tem os dois valores; o em aberto sai no tom do "vence
// em breve". Nao ha' diferenca entre o protocolado e o aprovado nem entre o recebido e o protocolado: falta de nota ou
// de pagamento nao e' diferenca de valor. As referencias e o limite vem do servidor.
// Revisao da PR #806 sobre a copia da producao: no mes, na obra e no total a diferenca e' so' o CORTE (o que o orgao
// aprovou abaixo do pedido), sobre o pedido de todas as medicoes comparaveis. O aprovado acima do pedido quase sempre
// e' pedido gravado errado, e somado anulava o corte de outra obra: aparece so' na linha da medicao, onde se confere
// (#807). Ate' R$ 0,05 por medicao e' arredondamento do orgao e conta como igual; quem decide e' o servidor.

// Com o total a receber ainda nao liberado no cadastro (a trava da lista de Obras e do Inicio), o recebido, o em
// aberto e a marca de cada nota vem nulos e as listas do em aberto vem vazias: a tela diz a trava em uma frase.
type Numeros = {
  medido_centavos: number; aprovado_centavos: number; protocolado_centavos: number; recebido_centavos: number | null;
  em_aberto_centavos: number | null;
  /** #805: os dois lados da diferenca aprovado × pedido, so' das medicoes que tem o valor do boletim e o pedido (a
   *  medicao em analise fica fora: nela nao ha' diferenca, ha' etapa nao alcancada). O pedido e' a base do percentual */
  aprovado_com_pedido_centavos?: number; pedido_do_aprovado_centavos?: number;
  /** o corte: a soma do que foi aprovado abaixo do pedido, medicao a medicao, fora o arredondamento de ate' R$ 0,05;
   *  o aprovado acima do pedido nao entra nem desconta */
  abaixo_do_pedido_centavos?: number;
};
/** As tres partes que somam o em aberto do ano: (a) notas que o orgao nao pagou, (a') repasse sem baixa (o orgao ja'
 *  pagou o consorcio e a nota da empresa segue sem baixa) e (b) medicoes sem nota ligada. */
type DoAno = Numeros & { meses: number; em_aberto_notas_centavos: number | null; em_aberto_repasse_centavos: number | null;
  sem_nota_centavos: number | null };
type NotaLinha = { nota_id: number; numero: string; valor_centavos: number; recebida: boolean | null; paga_em_parte: boolean | null;
  aguarda_repasse?: boolean | null };
/** Em consorcio com a nota da propria empresa ligada, a fatura do consorcio ligada a' mesma medicao: sem valor, nao soma. */
type NotaFora = { nota_id: number; numero: string };
type MedicaoLinha = Numeros & {
  medicao_id: number; contrato_id: number; obra: string; numero: number; tipo: string;
  competencia: string; protocolo_em: string | null; notas: NotaLinha[]; notas_fora_da_conta?: NotaFora[]; sem_nota?: boolean;
  /** so' a medicao tem: quanto o aprovado passou do pedido (quase sempre pedido gravado errado, a conferir) */
  acima_do_pedido_centavos?: number;
};
type ObraLinha = Numeros & { contrato_id: number; obra: string; medicoes: MedicaoLinha[] };
/** #805: `medido_ano_anterior_centavos` e' o medido do mesmo mes do ano anterior; nulo no mes ainda aberto e quando o
 *  ano anterior nao esta' na pagina ou nao teve medido no mes */
type Mes = Numeros & { competencia: string; obras: ObraLinha[]; medido_ano_anterior_centavos?: number | null };
/** (a) nota protocolada nao paga (a paga em parte, pelo que falta), (a') nota da empresa ao consorcio sem baixa em
 *  medicao que o orgao ja' pagou, ou (b) medicao protocolada sem nota ligada. */
type EmAberto = {
  tipo_aberto: "nota" | "repasse" | "sem_nota"; nota_id: number | null; numero: string | null; contrato_id: number; obra: string;
  medicao_id: number; medicao_numero: number; tipo: string; competencia: string; protocolo_em: string | null;
  /** #743: na obra sem o passo "Envio da nota" nao ha' protocolo; a espera conta da emissao da nota */
  emitida_em?: string | null;
  valor_centavos: number; paga_em_parte: boolean;
};
/** (c) nota de cobranca em aberto no RM sem medicao ligada: sem competencia, fora dos meses e do total. */
type NotaSolta = { nota_id: number; numero: string; contrato_id: number; obra: string; emissao: string | null;
  valor_centavos: number; paga_em_parte: boolean };
type Contagem = { quantidade: number; valor_centavos: number | null };
type Cobertura = { aprovado_centavos: number; com_nota_centavos: number; sem_nota_centavos: number; medicoes_sem_nota: number;
  percentual: number | null };
/** Medicao de consorcio cujas notas da empresa ligadas nao somam a cota dela (diferenca = notas - cota). */
type NotaDifere = { contrato_id: number; obra: string; medicao_id: number; medicao_numero: number; tipo: string;
  competencia: string; notas_centavos: number; cota_centavos: number; diferenca_centavos: number };
/** A execucao ou o reajuste que ainda conta pela fatura do consorcio enquanto a outra metade do par (`par_*`) ja'
 *  conta pela nota da empresa: a mesma cobranca pode estar somada duas vezes. */
type ParMisto = { contrato_id: number; obra: string; medicao_id: number; medicao_numero: number; tipo: string;
  competencia: string; par_medicao_id: number; par_tipo: string };
export type RespostaFechamento = {
  anos: string[]; meses: Mes[]; por_ano: Record<string, DoAno>;
  acumulado: { ate_mes: string | null } & Record<string, Numeros | string | null>;
  em_aberto: EmAberto[]; em_aberto_anteriores: Contagem;
  notas_sem_medicao: { em_aberto: NotaSolta[]; em_aberto_centavos: number | null; pagas: Contagem };
  cobertura: Record<string, Cobertura>; notas_diferem?: NotaDifere[]; pares_mistos?: ParMisto[];
  /** #805: acima de quantos milesimos do pedido a diferenca do aprovado e' critica (o limite do aviso "aprovado abaixo
   *  do pedido") */
  diferenca_critica_por_mil?: number;
  total_a_receber_liberado: boolean;
};

type Coluna = "medido_centavos" | "aprovado_centavos" | "protocolado_centavos" | "recebido_centavos" | "em_aberto_centavos";
// `curta`: a coluna que fica no celular (a 390 px a tabela mostra o medido e o recebido de cada mes). `etapa`: a marca
// da etapa do dinheiro no cabecalho da tabela do mes (#805); o aprovado e' o valor do boletim, e o medido junta
// etapas (o aprovado e, sem boletim, o pedido), por isso fica sem marca
const COLUNAS: { chave: Coluna; rotulo: string; curta?: boolean; etapa?: Etapa }[] = [
  { chave: "medido_centavos", rotulo: "Medido", curta: true }, { chave: "aprovado_centavos", rotulo: "Aprovado", etapa: "boletim" },
  { chave: "protocolado_centavos", rotulo: "Protocolado", etapa: "protocolado" },
  { chave: "recebido_centavos", rotulo: "Recebido", curta: true, etapa: "recebido" },
  { chave: "em_aberto_centavos", rotulo: "Em aberto", etapa: "em_aberto" },
];
const opcional = (c: { curta?: boolean }) => (c.curta ? "" : " fch-col-opcional");
const COMPARAVEIS = COLUNAS.slice(0, 4);

/** Zero em mes com lancamento nao e' numero a ler, e o valor escondido pela trava tambem nao: "—". */
function valor(c: number | null | undefined): string {
  return c === null || c === undefined || c === 0 ? "—" : brl(c);
}
function nomeMes(comp: string): string {
  const n = fmtMesExtenso(comp);
  return n.charAt(0).toUpperCase() + n.slice(1);
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

/** A referencia da variacao do medido de um mes: a competencia do mesmo mes do ano anterior e o medido dela. */
type Referencia = { competencia: string; centavos: number };

/** As cinco celulas de valor de uma linha (mes, obra, medicao ou total). Familias de valor (#805): sob o medido, a
 *  variacao contra `referencia` (so' a linha do mes a tem); sob o aprovado, a diferenca contra o pedido, quando a
 *  linha tem o corte e a base e a pagina tem o limite do servidor (`limite`); o em aberto, no tom do "vence em breve".
 *  `acima` so' vem na linha da medicao: nas linhas que somam, a diferenca e' so' o corte. */
function Celulas({ x, limite, referencia, acima }: { x: Numeros; limite?: number; referencia?: Referencia | null; acima?: number }) {
  return (
    <>
      {COLUNAS.map(c => {
        const v = x[c.chave];
        const comVariacao = c.chave === "medido_centavos" && !!referencia && variacao(v, referencia.centavos) !== null;
        const comDiferenca = c.chave === "aprovado_centavos" && limite !== undefined && !!v
          && diferenca(x.abaixo_do_pedido_centavos, acima, x.pedido_do_aprovado_centavos, limite) !== null;
        const emAberto = c.chave === "em_aberto_centavos" && !!v;
        return (
          <td key={c.chave} className={`col-num dinheiro num${opcional(c)}${emAberto ? " fch-em-aberto" : ""}`}>
            {comVariacao || comDiferenca ? (
              <span className="fch-cel">
                <span>{valor(v)}</span>
                {comVariacao && referencia && <Variacao atual={v} referencia={referencia.centavos} rotulo={fmtMesCurto(referencia.competencia)}
                  porExtenso={`${fmtMesExtenso(referencia.competencia)} de ${referencia.competencia.slice(0, 4)}`} />}
                {comDiferenca && limite !== undefined && <Diferenca abaixo={x.abaixo_do_pedido_centavos} acima={acima}
                  base={x.pedido_do_aprovado_centavos} nomeBase="pedido" limitePorMil={limite} />}
              </span>
            ) : valor(v)}
          </td>
        );
      })}
    </>
  );
}

/** O mesmo mes do ano anterior, com o medido dele, quando o servidor o manda (#805). */
function referenciaDoMes(m: Mes): Referencia | null {
  const centavos = m.medido_ano_anterior_centavos;
  if (centavos === null || centavos === undefined) return null;
  return { competencia: `${Number(m.competencia.slice(0, 4)) - 1}${m.competencia.slice(4)}`, centavos };
}

/** As notas da medicao, cada uma com a situacao: recebida, paga em parte, repasse sem baixa (o orgao ja' pagou o
 *  consorcio e a nota da empresa segue aberta) ou em aberto (sem selo com a trava). Em
 *  consorcio, com a nota da propria empresa ligada, a fatura do consorcio da mesma medicao vem depois, dita em texto:
 *  nao entra no protocolado, no recebido nem no em aberto (o servidor nao manda valor para ela). */
function Notas({ m }: { m: MedicaoLinha }) {
  if (m.sem_nota) return <ul className="fch-notas"><li><Selo>sem nota ligada</Selo></li></ul>;
  const fora = m.notas_fora_da_conta ?? [];
  if (m.notas.length === 0 && fora.length === 0) return null;
  return (
    <ul className="fch-notas">
      {m.notas.map(n => (
        <li key={n.nota_id}>
          <span className="num">Nota {n.numero}</span>
          {n.recebida !== null && (
            <Selo situacao={n.recebida ? "feito" : "andamento"}>{n.recebida ? "recebida" : n.paga_em_parte ? "paga em parte" : n.aguarda_repasse ? "repasse sem baixa" : "em aberto"}</Selo>
          )}
        </li>
      ))}
      {fora.map(n => (
        <li key={`fora-${n.nota_id}`}>
          <span className="num">Nota {n.numero}</span>
          <span>fatura do consórcio, não entra na conta</span>
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

/** O mes abre as obras, e a obra abre as medicoes, na propria tabela, com as colunas alinhadas. */
function LinhasDoMes({ m, ab, ir, limite }: { m: Mes; ab: Abertos; ir: Ir; limite?: number }) {
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
              <Celulas x={o} limite={limite} />
            </tr>
            {ab.tem(chave) && o.medicoes.map((md, j) => (
              <tr key={md.medicao_id} className="fch-linha fch-linha--medicao" id={j === 0 ? id : undefined}>
                <th scope="row" className="fch-primeira">
                  <Link className="link" para={{ tela: "medicao", obra: md.contrato_id, id: md.medicao_id }} ir={ir}>{tituloMedicao(md)}</Link>
                  <Notas m={md} />
                </th>
                <Celulas x={md} limite={limite} acima={md.acima_do_pedido_centavos ?? 0} />
              </tr>
            ))}
          </Fragment>
        );
      })}
    </>
  );
}

function TabelaDoAno({ f, ano, ir }: { f: RespostaFechamento; ano: string; ir: Ir }) {
  const [abertos, setAbertos] = useState<Set<string>>(new Set());
  const ab: Abertos = {
    tem: k => abertos.has(k),
    trocar: k => setAbertos(s => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; }),
  };
  const meses = f.meses.filter(m => m.competencia.startsWith(`${ano}-`));
  const limite = f.diferenca_critica_por_mil;
  if (meses.length === 0) return <p className="fch-vazio">Nenhum lançamento em {ano}.</p>;
  return (
    <Rolagem rotulo={`Por mês de competência, ${ano}`} className="tabela-wrap fch-rolagem">
      <table className="tabela fch-tabela fch-tabela--meses">
        <caption className="sr-only">Medido, aprovado, protocolado, recebido e em aberto por mês de competência de {ano}, na cota da Lotufo</caption>
        <thead>
          <tr>
            <th scope="col" className="fch-primeira">Mês</th>
            {COLUNAS.map(c => (
              <th key={c.chave} scope="col" className={`col-num${opcional(c)}`}>
                {c.etapa ? <MarcaEtapa etapa={c.etapa}>{c.rotulo}</MarcaEtapa> : c.rotulo}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {meses.map(m => (
            <Fragment key={m.competencia}>
              <tr className="fch-linha fch-linha--mes">
                <th scope="row" className="fch-primeira">
                  <BotaoAbre aberto={ab.tem(m.competencia)} controla={`fch-mes-${m.competencia}`}
                    rotulo={`${nomeMes(m.competencia)} de ${ano}, por obra`} onClick={() => ab.trocar(m.competencia)}>
                    <span className="fch-mes-longo">{nomeMes(m.competencia)}</span>
                    <span className="fch-mes-curto" aria-hidden="true">{nomeMes(m.competencia).slice(0, 3)}</span>
                  </BotaoAbre>
                </th>
                <Celulas x={m} limite={limite} referencia={referenciaDoMes(m)} />
              </tr>
              <LinhasDoMes m={m} ab={ab} ir={ir} limite={limite} />
            </Fragment>
          ))}
        </tbody>
        <tfoot>
          <tr><th scope="row" className="fch-primeira">Total de {ano}</th><Celulas x={f.por_ano[ano]} limite={limite} /></tr>
        </tfoot>
      </table>
    </Rolagem>
  );
}

/* ------------------------------------------------------------------ comparacao */

function Comparacao({ f }: { f: RespostaFechamento }) {
  const [chave, setChave] = useState<Coluna>("medido_centavos");
  const [a, b] = f.anos;
  const porMes = new Map(f.meses.map(m => [m.competencia, m]));
  const mms = [...new Set(f.meses.map(m => m.competencia.slice(5)))].sort();
  const ate = f.acumulado.ate_mes;
  if (mms.length === 0) return null;
  // com a trava do total a receber, o recebido nao tem valor: o botao dele sai
  const comparaveis = COMPARAVEIS.filter(c => f.total_a_receber_liberado || c.chave !== "recebido_centavos");
  const rotulo = comparaveis.find(c => c.chave === chave)?.rotulo ?? "";
  return (
    <section className="cartao fch-painel" aria-labelledby="fch-comparacao">
      <div className="fch-painel__cab">
        <h2 id="fch-comparacao">{b} × {a}</h2>
        <div className="escolhas" role="group" aria-label="Número comparado">
          {comparaveis.map(c => (
            <button key={c.chave} type="button" className="escolha" aria-pressed={chave === c.chave} onClick={() => setChave(c.chave)}>{c.rotulo}</button>
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

// As celulas levam a area (`fch-a-*`) e o rotulo (`data-rotulo`): em tela estreita a linha vira um bloco, com a obra e o
// valor em cima (fechamento.css), e o rotulo da coluna vai escrito antes do dado.
function LinhaEmAberto({ e, ir }: { e: EmAberto; ir: Ir }) {
  return (
    <tr>
      {e.protocolo_em
        ? <th scope="row" className="fch-primeira fch-a-data num" data-rotulo="Protocolo">{fmtDataPura(e.protocolo_em)}</th>
        : e.emitida_em
          ? <th scope="row" className="fch-primeira fch-a-data fch-sem-data">nota emitida em {fmtDataPura(e.emitida_em)}</th>
          : <th scope="row" className="fch-primeira fch-a-data fch-sem-data">sem data de protocolo</th>}
      <td className="fch-a-obra">{e.obra}</td>
      <td className="fch-a-medicao">
        <Link className="link" para={{ tela: "medicao", obra: e.contrato_id, id: e.medicao_id }} ir={ir}>
          {tituloMedicao({ numero: e.medicao_numero, tipo: e.tipo })}
        </Link>
        <span className="fch-sub num">{fmtCompetencia(e.competencia)}</span>
      </td>
      <td className="fch-a-nota">
        {e.numero === null ? <Selo>sem nota ligada</Selo> : <NumeroDaNota numero={e.numero} emParte={e.paga_em_parte} />}
      </td>
      <td className="col-num dinheiro num fch-a-valor">{valor(e.valor_centavos)}</td>
    </tr>
  );
}

/** O numero da nota e, na paga em parte, o selo: o valor ao lado e' o que falta, nao o valor da nota. */
function NumeroDaNota({ numero, emParte }: { numero: string; emParte: boolean }) {
  return (
    <span className="fch-nota">
      <span className="num" data-rotulo="Nota">{numero}</span>
      {emParte && <Selo situacao="andamento">paga em parte</Selo>}
    </span>
  );
}

/** O em aberto do ano escolhido, em tres partes que somam o total do ano (o mesmo numero do alto e do "Total de <ano>"
 *  da tabela do mes): (a) nota protocolada nao paga, (a') nota da empresa sem baixa em medicao de consorcio que o orgao
 *  ja' pagou (quem deve e' o consorcio) e (b) medicao protocolada sem nota ligada. A' parte, sem depender
 *  do ano: (c) nota em aberto no RM sem medicao ligada (sem competencia) e o em aberto de antes do primeiro ano. */
function EmAbertoPainel({ f, ano, ir }: { f: RespostaFechamento; ano: string; ir: Ir }) {
  const doAno = f.em_aberto.filter(e => e.competencia.startsWith(`${ano}-`));
  const notas = doAno.filter(e => e.tipo_aberto === "nota");
  const repasses = doAno.filter(e => e.tipo_aberto === "repasse");
  const semNota = doAno.filter(e => e.tipo_aberto === "sem_nota");
  const t = f.por_ano[ano];
  const soltas = f.notas_sem_medicao.em_aberto;
  const pagas = f.notas_sem_medicao.pagas;
  const anteriores = f.em_aberto_anteriores;
  const n = doAno.length;
  return (
    <section className="cartao fch-painel" aria-labelledby="fch-aberto">
      <div className="fch-painel__cab">
        <h2 id="fch-aberto">Em aberto de {ano}</h2>
        <Contador rotulo={contar(n, "linha", "linhas")}>{n}</Contador>
      </div>
      {n === 0 ? <p className="fch-vazio">Nada em aberto em {ano}.</p> : (
        <Rolagem rotulo={`Em aberto de ${ano}`} className="tabela-wrap fch-rolagem">
          <table className="tabela fch-tabela fch-tabela--aberto">
            <caption className="sr-only">Em aberto de {ano}, na cota da Lotufo, pela data do protocolo: notas protocoladas não pagas, notas da empresa de medições que o órgão já pagou ao consórcio e seguem sem baixa do repasse no RM, e medições protocoladas sem nota ligada</caption>
            <thead>
              <tr>
                <th scope="col" className="fch-primeira">Protocolo</th><th scope="col">Obra</th><th scope="col">Medição</th>
                <th scope="col">Nota</th><th scope="col" className="col-num">Valor</th>
              </tr>
            </thead>
            {notas.length > 0 && (
              <tbody>
                <tr className="fch-grupo"><th scope="rowgroup" colSpan={4}>Nota protocolada não paga</th>
                  <td className="col-num dinheiro num">{valor(t.em_aberto_notas_centavos)}</td></tr>
                {notas.map(e => <LinhaEmAberto key={`n-${e.nota_id}-${e.medicao_id}`} e={e} ir={ir} />)}
              </tbody>
            )}
            {repasses.length > 0 && (
              <tbody>
                <tr className="fch-grupo"><th scope="rowgroup" colSpan={4}>Órgão pagou o consórcio, repasse sem baixa no RM</th>
                  <td className="col-num dinheiro num">{valor(t.em_aberto_repasse_centavos)}</td></tr>
                {repasses.map(e => <LinhaEmAberto key={`r-${e.nota_id}-${e.medicao_id}`} e={e} ir={ir} />)}
              </tbody>
            )}
            {semNota.length > 0 && (
              <tbody>
                <tr className="fch-grupo"><th scope="rowgroup" colSpan={4}>Medição protocolada sem nota ligada</th>
                  <td className="col-num dinheiro num">{valor(t.sem_nota_centavos)}</td></tr>
                {semNota.map(e => <LinhaEmAberto key={`m-${e.medicao_id}`} e={e} ir={ir} />)}
              </tbody>
            )}
            <tfoot><tr><th scope="row" className="fch-primeira" colSpan={4}>Total em aberto de {ano}</th><td className="col-num dinheiro num">{valor(t.em_aberto_centavos)}</td></tr></tfoot>
          </table>
        </Rolagem>
      )}
      {(soltas.length > 0 || anteriores.quantidade > 0) && (
        <div className="fch-soltas">
          <p className="fch-soltas__base">Nota sem medição ligada e em aberto de competência anterior a {f.anos[0]} não dependem do ano escolhido.</p>
          {soltas.length > 0 && (
            <>
              <h3 className="fch-soltas__titulo" id="fch-soltas">Nota sem medição ligada</h3>
              {semNota.length > 0 && (
                <CaixaAviso nivel="atencao" className="fch-aviso">
                  Medição sem nota ligada e nota sem medição ligada podem ser a mesma cobrança enquanto o vínculo não for feito.
                </CaixaAviso>
              )}
              <Rolagem rotulo="Notas sem medição ligada, em aberto" className="tabela-wrap fch-rolagem">
                <table className="tabela fch-tabela fch-tabela--aberto fch-tabela--soltas" aria-labelledby="fch-soltas">
                  <caption className="sr-only">Notas de cobrança em aberto no RM sem medição ligada, pela data da emissão, na cota da Lotufo; fora do total em aberto</caption>
                  <thead>
                    <tr><th scope="col" className="fch-primeira">Emissão</th><th scope="col">Obra</th><th scope="col">Nota</th>
                      <th scope="col" className="col-num">Valor</th></tr>
                  </thead>
                  <tbody>
                    {soltas.map(e => (
                      <tr key={e.nota_id}>
                        {e.emissao
                          ? <th scope="row" className="fch-primeira fch-a-data num" data-rotulo="Emissão">{fmtDataPura(e.emissao)}</th>
                          : <th scope="row" className="fch-primeira fch-a-data fch-sem-data">sem data de emissão</th>}
                        <td className="fch-a-obra">{e.obra}</td>
                        <td className="fch-a-nota"><NumeroDaNota numero={e.numero} emParte={e.paga_em_parte} /></td>
                        <td className="col-num dinheiro num fch-a-valor">{valor(e.valor_centavos)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot><tr><th scope="row" className="fch-primeira" colSpan={3}>Subtotal à parte</th>
                    <td className="col-num dinheiro num">{valor(f.notas_sem_medicao.em_aberto_centavos)}</td></tr></tfoot>
                </table>
              </Rolagem>
            </>
          )}
        </div>
      )}
      {(pagas.quantidade > 0 || anteriores.quantidade > 0) && (
        <dl className="fch-aparte">
          {pagas.quantidade > 0 && (
            <div><dt>Notas pagas sem medição ligada ({f.anos.join(" e ")})</dt>
              <dd><span className="num">{contar(pagas.quantidade, "nota", "notas")}</span> · <span className="num">{valor(pagas.valor_centavos)}</span></dd></div>
          )}
          {anteriores.quantidade > 0 && (
            <div><dt>Em aberto de competências anteriores a {f.anos[0]}</dt>
              <dd><span className="num">{contar(anteriores.quantidade, "linha", "linhas")}</span> · <span className="num">{valor(anteriores.valor_centavos)}</span></dd></div>
          )}
        </dl>
      )}
    </section>
  );
}

/** Aviso de divergencia (texto-na-tela: so' quando existe): o aprovado com nota emitida que ainda nao tem nota ligada
 *  fica sem protocolado e sem recebido. Some com a cobertura total. */
function AvisoCobertura({ f, ano }: { f: RespostaFechamento; ano: string }) {
  const c = f.cobertura[ano];
  if (!c || c.sem_nota_centavos <= 0) return null;
  const pct = c.percentual === null ? "" : ` (${c.percentual.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%)`;
  return (
    <CaixaAviso nivel="atencao" role="status" className="fch-aviso">
      Em {ano}, só {brl(c.com_nota_centavos)}{pct} dos {brl(c.aprovado_centavos)} aprovados com nota emitida têm nota
      ligada; {contar(c.medicoes_sem_nota, "medição aparece", "medições aparecem")} sem protocolado nem recebido.
    </CaixaAviso>
  );
}

/** Aviso de divergencia (so' quando existe): em consorcio, as notas da empresa ligadas a' medicao nao somam a cota
 *  dela. A cobertura do vinculo nao pega (ha' nota ligada); cada medicao vai com o link e a diferenca. */
function AvisoNotasDiferem({ f, ano, ir }: { f: RespostaFechamento; ano: string; ir: Ir }) {
  const xs = (f.notas_diferem ?? []).filter(e => e.competencia.startsWith(`${ano}-`));
  if (xs.length === 0) return null;
  return (
    <CaixaAviso nivel="atencao" role="status" className="fch-aviso">
      Em {ano}, a nota da empresa ao consórcio difere da cota da medição:{" "}
      {xs.map((e, i) => (
        <Fragment key={e.medicao_id}>
          {i > 0 && "; "}
          <Link className="link" para={{ tela: "medicao", obra: e.contrato_id, id: e.medicao_id }} ir={ir}>
            {e.obra}, {tituloMedicao({ numero: e.medicao_numero, tipo: e.tipo })}
          </Link>
          {" "}(<span className="num">{brl(Math.abs(e.diferenca_centavos))}</span> a {e.diferenca_centavos > 0 ? "mais" : "menos"})
        </Fragment>
      ))}.
    </CaixaAviso>
  );
}

/** Aviso de divergencia (so' quando existe): a execucao e o reajuste de mesmo numero contando por notas diferentes.
 *  A fatura do consorcio cobre as duas; a medicao listada ainda conta por ela, e a outra ja' pela nota da empresa. */
function AvisoParesMistos({ f, ano, ir }: { f: RespostaFechamento; ano: string; ir: Ir }) {
  const xs = (f.pares_mistos ?? []).filter(e => e.competencia.startsWith(`${ano}-`));
  if (xs.length === 0) return null;
  return (
    <CaixaAviso nivel="atencao" role="status" className="fch-aviso">
      Em {ano}, falta ligar a nota da empresa ao consórcio, e a cobrança pode estar somada duas vezes:{" "}
      {xs.map((e, i) => (
        <Fragment key={e.medicao_id}>
          {i > 0 && "; "}
          <Link className="link" para={{ tela: "medicao", obra: e.contrato_id, id: e.medicao_id }} ir={ir}>
            {e.obra}, {tituloMedicao({ numero: e.medicao_numero, tipo: e.tipo })}
          </Link>
        </Fragment>
      ))}.
    </CaixaAviso>
  );
}

/* ------------------------------------------------------------------ pagina */

export default function Fechamento({ ir }: { ir: Ir }) {
  const [f, setF] = useState<RespostaFechamento | null>(null);
  const [erro, setErro] = useState("");
  const [ano, setAno] = useState<string | null>(null);
  useEffect(() => {
    let vivo = true;
    api<RespostaFechamento>("/api/fechamento").then(d => { if (vivo) setF(d); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, []);
  if (erro) return <Falha>Não foi possível carregar o fechamento: {erro} Recarregue a página para tentar de novo.</Falha>;
  if (!f) return <p className="fch-vazio">Carregando…</p>;
  const atual = ano ?? f.anos[f.anos.length - 1];
  return (
    <div className="fch">
      <div className="fch-cota">
        <h2>Cota da Lotufo</h2>
        <div className="escolhas" role="group" aria-label="Ano">
          {[...f.anos].reverse().map(a => (
            <button key={a} type="button" className="escolha" aria-pressed={atual === a} onClick={() => setAno(a)}>{a}</button>
          ))}
        </div>
      </div>
      <p className="fch-base">Protocolado e recebido pelo valor bruto da nota; cada número no mês de competência da medição, não no mês do pagamento.</p>
      <NumerosDoAno f={f} ano={atual} />
      {!f.total_a_receber_liberado && (
        <CaixaAviso nivel="atencao" className="fch-aviso">
          O total a receber ainda não está liberado: recebido e em aberto ficam sem valor.
        </CaixaAviso>
      )}
      <AvisoCobertura f={f} ano={atual} />
      <AvisoNotasDiferem f={f} ano={atual} ir={ir} />
      <AvisoParesMistos f={f} ano={atual} ir={ir} />
      <section className="cartao fch-painel" aria-labelledby="fch-meses">
        <div className="fch-painel__cab"><h2 id="fch-meses">Por mês de competência</h2></div>
        <TabelaDoAno key={atual} f={f} ano={atual} ir={ir} />
      </section>
      <Comparacao f={f} />
      {f.total_a_receber_liberado && <EmAbertoPainel f={f} ano={atual} ir={ir} />}
    </div>
  );
}
