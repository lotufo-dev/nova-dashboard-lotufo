import { Fragment, useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import CaixaAviso from "./CaixaAviso";
import Diferenca from "./Diferenca";
import { brl, contar, fmtPercentual } from "./formato";
import { Link } from "./Link";
import MarcaEtapa from "./MarcaEtapa";
import { tituloMedicao } from "./medicao";
import Rolagem from "./Rolagem";
import { cliqueSimples, irHref, useRota, type AbaFechamento, type Busca, type Ir } from "./rota";
import Selo from "./Selo";
import { fmtCompetencia, fmtMesCurto, fmtMesExtenso } from "./tempo";
import { diferenca, variacao, type Etapa } from "./valores";
import Variacao from "./Variacao";
import "./fechamento.css";
import Falha from "./Falha";

// Fechamento (#748): o que foi medido, aprovado, protocolado e recebido em cada mes de competencia de 2025 e 2026, na
// cota da Lotufo, e o total do que esta' em aberto. Os numeros vem prontos do servidor (`app/fechamento.py`), ja'
// somados mes a mes, obra a obra, medicao a medicao e contratante a contratante: a tela nao soma nem estima nada. O mes
// de todo numero e' a competencia da medicao (a nota e o recebimento, a da medicao a que a nota esta' ligada).
//
// #815 (decisao do dono de 18/11/2026): a pagina tem tres abas, uma pergunta em cada, com a aba no endereco:
// "/fechamento" (mes a mes), "/fechamento/comparacao" (os dois anos lado a lado) e "/fechamento/contratantes" (cada
// contratante no ano, com a participacao dele no medido). O ano escolhido vai na busca (?ano=2025; o mais novo e' o
// padrao e nao entra), e ?mes=2026-10 abre a pagina com aquele mes aberto por obra. O em aberto nota a nota saiu
// daqui: fica o total do ano, com o link para a pagina A receber. A aba e o ano saem do endereco (`useRota`), entao o
// link guardado abre no mesmo lugar.
//
// O mes abre as obras, e a obra as medicoes, como linhas recuadas da mesma tabela (decisao do dono de 16/11/2026).
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
/** #815: um contratante no ano, com os mesmos numeros do ano (as linhas somam `por_ano`, coluna a coluna) e a
 *  participacao do medido dele no medido do ano, em milesimos (nula sem medido no ano). `contratante_chave` e' a da
 *  pagina do contratante em Obras; sem orgao no cadastro, nao ha' chave nem pagina. */
type DoContratante = Numeros & { contratante: string; contratante_chave: string | null; participacao_medido_por_mil: number | null };
// O em aberto nota a nota nao e' mais desenhado aqui (#815): o servidor continua mandando `em_aberto`,
// `em_aberto_anteriores` e `notas_sem_medicao`, que a pagina A receber (#816) reaproveita.
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
  por_contratante?: Record<string, DoContratante[]>;
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

/** O endereco da pagina A receber (#816), onde mora o em aberto nota a nota. Vai escrito, e nao por `Rota`: a rota
 *  nasce na peca do menu em areas (#814). */
const A_RECEBER = "/a-receber";

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

/** Os cinco numeros do ano. O em aberto leva o link para a pagina A receber (#815), que tem as notas uma a uma; com a
 *  trava do total a receber nao ha' valor a abrir, e o link nao aparece. */
function NumerosDoAno({ f, ano }: { f: RespostaFechamento; ano: string }) {
  const t = f.por_ano[ano];
  return (
    <dl className="fch-numeros" aria-label={`Totais de ${ano}`}>
      {COLUNAS.map(c => (
        <div key={c.chave} className="fch-numero">
          <dt className="fch-numero__rotulo">{c.rotulo}</dt>
          <dd className="fch-numero__valor">{t ? valor(t[c.chave]) : "—"}</dd>
          {c.chave === "em_aberto_centavos" && f.total_a_receber_liberado && (
            <dd className="fch-numero__porta">
              <a className="link" href={A_RECEBER} onClick={ev => { if (cliqueSimples(ev)) { ev.preventDefault(); irHref(A_RECEBER); } }}>
                A receber, nota a nota
              </a>
            </dd>
          )}
        </div>
      ))}
    </dl>
  );
}

/* ------------------------------------------------------------------ as cinco colunas */

/** A referencia da variacao do medido de um mes: a competencia do mesmo mes do ano anterior e o medido dela. */
type Referencia = { competencia: string; centavos: number };

/** A variacao do medido de um mes contra o mesmo mes do ano anterior. */
function VariacaoDoMedido({ atual, referencia }: { atual: number; referencia: Referencia }) {
  return <Variacao atual={atual} referencia={referencia.centavos} rotulo={fmtMesCurto(referencia.competencia)}
    porExtenso={`${fmtMesExtenso(referencia.competencia)} de ${referencia.competencia.slice(0, 4)}`} />;
}

/** As cinco celulas de valor de uma linha (mes, obra, medicao, contratante ou total). Familias de valor (#805): sob o
 *  medido, a variacao contra `referencia` (so' a linha do mes a tem); sob o aprovado, a diferenca contra o pedido,
 *  quando a linha tem o corte e a base e a pagina tem o limite do servidor (`limite`); o em aberto, no tom do "vence
 *  em breve". `acima` so' vem na linha da medicao: nas linhas que somam, a diferenca e' so' o corte. `parte` (#815, so'
 *  a linha do contratante): a participacao do medido dela no medido do ano, em milesimos, escrita sob o medido.
 *  `data-rotulo` leva o nome da coluna para a tabela que vira um bloco por linha no celular. */
function Celulas({ x, limite, referencia, acima, parte }:
    { x: Numeros; limite?: number; referencia?: Referencia | null; acima?: number; parte?: number | null }) {
  return (
    <>
      {COLUNAS.map(c => {
        const v = x[c.chave];
        const doMedido = c.chave === "medido_centavos";
        const comVariacao = doMedido && !!referencia && variacao(v, referencia.centavos) !== null;
        const comParte = doMedido && parte !== null && parte !== undefined;
        const comDiferenca = c.chave === "aprovado_centavos" && limite !== undefined && !!v
          && diferenca(x.abaixo_do_pedido_centavos, acima, x.pedido_do_aprovado_centavos, limite) !== null;
        const emAberto = c.chave === "em_aberto_centavos" && !!v;
        return (
          <td key={c.chave} data-rotulo={c.rotulo} className={`col-num dinheiro num${opcional(c)}${emAberto ? " fch-em-aberto" : ""}`}>
            {comVariacao || comDiferenca || comParte ? (
              <span className="fch-cel">
                <span>{valor(v)}</span>
                {comVariacao && referencia && <VariacaoDoMedido atual={x.medido_centavos} referencia={referencia} />}
                {comParte && <span className="fch-parte">{fmtPercentual(parte / 1000, 1, true)} do total</span>}
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

/** O cabecalho das tabelas de cinco numeros (a do mes e a do contratante): a marca da etapa ao lado do rotulo. */
function Cabecalho({ primeira }: { primeira: string }) {
  return (
    <thead>
      <tr>
        <th scope="col" className="fch-primeira">{primeira}</th>
        {COLUNAS.map(c => (
          <th key={c.chave} scope="col" className={`col-num${opcional(c)}`}>
            {c.etapa ? <MarcaEtapa etapa={c.etapa}>{c.rotulo}</MarcaEtapa> : c.rotulo}
          </th>
        ))}
      </tr>
    </thead>
  );
}

/* ------------------------------------------------------------------ tabela do mes */

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

/** `mesAberto` (#815): a competencia que o endereco pede aberta por obra (?mes=2026-10), quando e' do ano mostrado. */
function TabelaDoAno({ f, ano, ir, mesAberto }: { f: RespostaFechamento; ano: string; ir: Ir; mesAberto?: string | null }) {
  const [abertos, setAbertos] = useState<Set<string>>(() => new Set(mesAberto ? [mesAberto] : []));
  const ab: Abertos = {
    tem: k => abertos.has(k),
    trocar: k => setAbertos(s => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; }),
  };
  const meses = f.meses.filter(m => m.competencia.startsWith(`${ano}-`));
  const limite = f.diferenca_critica_por_mil;
  if (meses.length === 0) return <p className="fch-vazio">Nenhum lançamento em {ano}.</p>;
  return (
    <Rolagem rotulo={`Por mês de competência, ${ano}`} className="tabela-wrap fch-rolagem">
      <table className="tabela fch-tabela fch-tabela--cinco fch-tabela--meses">
        <caption className="sr-only">Medido, aprovado, protocolado, recebido e em aberto por mês de competência de {ano}, na cota da Lotufo</caption>
        <Cabecalho primeira="Mês" />
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

/** Os dois anos lado a lado, mes a mes, no numero escolhido. No medido, o mes encerrado do ano mais novo leva a
 *  variacao contra o mesmo mes do ano anterior (#815): a referencia e' a que o servidor manda para a tabela do mes
 *  (`medido_ano_anterior_centavos`), o mesmo valor da coluna ao lado. */
function Comparacao({ f }: { f: RespostaFechamento }) {
  const [chave, setChave] = useState<Coluna>("medido_centavos");
  const [a, b] = f.anos;
  const porMes = new Map(f.meses.map(m => [m.competencia, m]));
  const mms = [...new Set(f.meses.map(m => m.competencia.slice(5)))].sort();
  const ate = f.acumulado.ate_mes;
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
      {mms.length === 0 ? <p className="fch-vazio">Nenhum lançamento em {a} nem em {b}.</p> : (
        <Rolagem rotulo={`${rotulo}: ${b} e ${a}, mês a mês`} className="tabela-wrap fch-rolagem">
          <table className="tabela fch-tabela fch-tabela--comparacao">
            <caption className="sr-only">{rotulo} por mês de competência, {a} e {b}, na cota da Lotufo</caption>
            <thead><tr><th scope="col" className="fch-primeira">Mês</th><th scope="col" className="col-num">{a}</th><th scope="col" className="col-num">{b}</th></tr></thead>
            <tbody>
              {mms.map(mm => {
                const x = porMes.get(`${a}-${mm}`), y = porMes.get(`${b}-${mm}`);
                const referencia = chave === "medido_centavos" && y ? referenciaDoMes(y) : null;
                const comVariacao = !!y && !!referencia && variacao(y.medido_centavos, referencia.centavos) !== null;
                return (
                  <tr key={mm}>
                    <th scope="row" className="fch-primeira">{nomeMes(`${a}-${mm}`)}</th>
                    <td className="col-num dinheiro num">{x ? valor(x[chave]) : "—"}</td>
                    <td className="col-num dinheiro num">
                      {y && referencia && comVariacao ? (
                        <span className="fch-cel">
                          <span>{valor(y[chave])}</span>
                          <VariacaoDoMedido atual={y.medido_centavos} referencia={referencia} />
                        </span>
                      ) : y ? valor(y[chave]) : "—"}
                    </td>
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
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ por contratante */

/** #815: cada contratante no ano, com os cinco numeros e a participacao dele no medido do ano. As linhas e o total
 *  vem do servidor (a linha de baixo e' o total do ano, o mesmo da tabela do mes): a tela nao soma. O nome leva a'
 *  pagina do contratante; sem orgao no cadastro nao ha' pagina, e o nome fica em texto. */
function PorContratante({ f, ano, ir }: { f: RespostaFechamento; ano: string; ir: Ir }) {
  const linhas = f.por_contratante?.[ano] ?? [];
  const limite = f.diferenca_critica_por_mil;
  if (linhas.length === 0) return <p className="fch-vazio">Nenhum lançamento em {ano}.</p>;
  return (
    <Rolagem rotulo={`Por contratante, ${ano}`} className="tabela-wrap fch-rolagem">
      <table className="tabela fch-tabela fch-tabela--cinco fch-tabela--contratantes">
        <caption className="sr-only">Medido, aprovado, protocolado, recebido e em aberto de cada contratante em {ano}, na cota da Lotufo, com a participação no medido do ano</caption>
        <Cabecalho primeira="Contratante" />
        <tbody>
          {linhas.map(g => (
            <tr key={g.contratante} className="fch-linha fch-linha--contratante">
              <th scope="row" className="fch-primeira">
                {g.contratante_chave
                  ? <Link className="link" para={{ tela: "contratante", chave: g.contratante_chave }} ir={ir}>{g.contratante}</Link>
                  : g.contratante}
              </th>
              <Celulas x={g} limite={limite} parte={g.participacao_medido_por_mil} />
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr><th scope="row" className="fch-primeira">Total de {ano}</th><Celulas x={f.por_ano[ano]} limite={limite} /></tr>
        </tfoot>
      </table>
    </Rolagem>
  );
}

/* ------------------------------------------------------------------ avisos */

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

const ABAS: readonly AbaFechamento[] = ["meses", "comparacao", "contratantes"];

/** O que o endereco pede (#815): a aba, pelo caminho; o ano, por ?ano= (o mais novo quando falta ou nao e' da
 *  pagina); e o mes a abrir por obra, por ?mes=AAAA-MM, que tambem escolhe o ano dele. */
function doEndereco(f: RespostaFechamento, aba: AbaFechamento | undefined, busca: Busca) {
  const padrao = f.anos[f.anos.length - 1];
  const mes = /^\d{4}-(0[1-9]|1[0-2])$/.test(busca.mes ?? "") && f.anos.includes(busca.mes.slice(0, 4)) ? busca.mes : null;
  const ano = mes ? mes.slice(0, 4) : f.anos.includes(busca.ano ?? "") ? busca.ano : padrao;
  return { aba: aba && ABAS.includes(aba) ? aba : "meses", ano, padrao, mes };
}

export default function Fechamento({ ir }: { ir: Ir }) {
  const { rota, busca, trocarBusca } = useRota();
  const [f, setF] = useState<RespostaFechamento | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    let vivo = true;
    api<RespostaFechamento>("/api/fechamento").then(d => { if (vivo) setF(d); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, []);
  if (erro) return <Falha>Não foi possível carregar o fechamento: {erro} Recarregue a página para tentar de novo.</Falha>;
  if (!f) return <p className="fch-vazio">Carregando…</p>;
  const { aba, ano: atual, padrao, mes } = doEndereco(f, rota.tela === "fechamento" ? rota.aba : undefined, busca);
  // a aba leva o ano escolhido para a outra; o mes aberto e' so' da tabela do mes
  const doAno: Busca | undefined = atual === padrao ? undefined : { ano: atual };
  const [a, b] = f.anos;
  const rotulos: Record<AbaFechamento, string> = { meses: "Mês a mês", comparacao: `${b} × ${a}`, contratantes: "Por contratante" };
  return (
    <div className="fch">
      <nav className="abas fch-abas" aria-label="Fechamento">
        {ABAS.map(x => (
          <Link key={x} className="aba" para={x === "meses" ? { tela: "fechamento" } : { tela: "fechamento", aba: x }} busca={doAno} ir={ir}
            aria-current={x === aba ? "page" : undefined}>{rotulos[x]}</Link>
        ))}
      </nav>
      <div className="fch-cota">
        <h2>Cota da Lotufo</h2>
        {aba !== "comparacao" && (
          <div className="escolhas" role="group" aria-label="Ano">
            {[...f.anos].reverse().map(x => (
              <button key={x} type="button" className="escolha" aria-pressed={atual === x}
                onClick={() => trocarBusca({ ano: x === padrao ? null : x, mes: null })}>{x}</button>
            ))}
          </div>
        )}
      </div>
      <p className="fch-base">Protocolado e recebido pelo valor bruto da nota; cada número no mês de competência da medição, não no mês do pagamento.</p>
      {aba !== "comparacao" && <NumerosDoAno f={f} ano={atual} />}
      {!f.total_a_receber_liberado && (
        <CaixaAviso nivel="atencao" className="fch-aviso">
          O total a receber ainda não está liberado: recebido e em aberto ficam sem valor.
        </CaixaAviso>
      )}
      {aba !== "comparacao" && (
        <>
          <AvisoCobertura f={f} ano={atual} />
          <AvisoNotasDiferem f={f} ano={atual} ir={ir} />
          <AvisoParesMistos f={f} ano={atual} ir={ir} />
        </>
      )}
      {aba === "meses" && (
        <section className="cartao fch-painel" aria-labelledby="fch-meses">
          <div className="fch-painel__cab"><h2 id="fch-meses">Por mês de competência</h2></div>
          <TabelaDoAno key={`${atual}:${mes ?? ""}`} f={f} ano={atual} ir={ir} mesAberto={mes} />
        </section>
      )}
      {aba === "comparacao" && <Comparacao f={f} />}
      {aba === "contratantes" && (
        <section className="cartao fch-painel" aria-labelledby="fch-contratantes">
          <div className="fch-painel__cab"><h2 id="fch-contratantes">Por contratante</h2></div>
          <PorContratante f={f} ano={atual} ir={ir} />
        </section>
      )}
    </div>
  );
}
