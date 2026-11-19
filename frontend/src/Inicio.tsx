import { Fragment, useEffect, useState } from "react";
import { destinoDoAviso, semEmpresa, semObra, type Aviso } from "./Alertas";
import { api, mensagemDeErro } from "./api";
import { daAgenda, diasAteOAviso, porSecao, semRSOrfao, type Secao } from "./avisos";
import Contador from "./Contador";
import EmAbertoAParte from "./EmAbertoAParte";
import Falha from "./Falha";
import { brl, contar } from "./formato";
import LegendaCor from "./LegendaCor";
import type { Usuario } from "./Login";
import MarcaEtapa from "./MarcaEtapa";
import Rolagem from "./Rolagem";
import { type Ir } from "./rota";
import { Link } from "./Link";
import Selo, { Glifo } from "./Selo";
import type { Situacao } from "./situacao";
import { fmtCompetencia, fmtMesCurto, fmtMesExtenso } from "./tempo";
import type { Etapa } from "./valores";
import Variacao from "./Variacao";
import "./inicio.css";

// Inicio do redesenho de 11/2026: informacao geral para a diretoria. Issue #642 (decisao do dono de 10/11/2026): a
// faixa do ciclo da medicao entrou no lugar do destaque de protocoladas e das barras por contratante.
// Tudo vem de GET /api/inicio/painel; as regras de cada numero moram em `backend/app/inicio.py`. A tela so' desenha.
// Acao operacional (nota a enviar, espelho a conferir) saiu daqui: vive nas telas dela e na tela Avisos.
// #666: a caixa "Avisos importantes" le GET /api/inicio, a MESMA fila da tela Avisos (com o recorte do perfil), e usa a
// mesma regra de secao (`avisos.ts`): a contagem dela e' a soma de Vencido, Esta semana e Este mes daquela tela.
// #721 (redesenho, etapa 2a): a tela como o dono a montou em 15/11/2026. Os mesmos blocos e os mesmos numeros, em outra
// disposicao: saudacao e numeros do mes no alto; o grupo "Cota da Lotufo" (a base dita uma vez, no titulo do grupo) com
// o ciclo e a previsao lado a lado e o recebido embaixo; depois os avisos e a matriz, na largura toda.
// #805 (decisao do dono de 18/11/2026): os dois numeros do alto dizem se estao melhor ou pior que antes, com a peca
// Variacao. As referencias vem do servidor, com a mesma conta do numero em outro periodo; a tela so' desenha.
// #817 (reestrutura 5c): o que faltava apresentar a' diretoria, acrescentado sem mexer no que o dono montou. No grupo da
// cota entram o ciclo aberto por contratante (logo abaixo do ciclo e da previsao) e o medido em 12 meses (ao lado do
// recebido, com a mesma forma). Todo numero novo e' uma porta: o contratante e o a receber dele abrem a pagina do
// contratante, e o medido de cada mes abre o mes no Fechamento (o do alto tambem). As contas moram em
// `backend/app/inicio.py`; a tela nao soma nada.

type ChaveEtapa = "em_analise" | "boletim" | "nota" | "protocolado" | "recebido_mes";
// #642: uma etapa da faixa do ciclo, na cota da Lotufo; `mais_antigo_dias` nulo = etapa vazia ou sem idade (recebido)
type EtapaCiclo = { etapa: ChaveEtapa; valor_centavos: number; quantidade: number; mais_antigo_dias: number | null };
// #652: o recebido de um mes (baixas do RM, na cota) e uma linha da previsao de entrada
type MesRecebido = { mes: string; valor_centavos: number };
type GrupoPrevisao = { valor_centavos: number; quantidade: number };
// #659: a etapa da medicao de uma competencia; `atrasado` = protocolada alem do prazo do contratante (a regra da
// previsao de entrada). Celula nula = sem medicao na competencia
type EtapaMatriz = "em_analise" | "boletim" | "nota" | "protocolado" | "atrasado" | "recebida";
type CelulaMatriz = { etapa: EtapaMatriz; medicao_id: number } | null;
type ObraMatriz = { contrato_id: number; obra: string; celulas: CelulaMatriz[] };
/** #805: o medido de outra competencia, a referencia da variacao; nulo sem com o que comparar */
type ReferenciaMedido = { competencia: string; valor_centavos: number } | null;
// #817: as quatro etapas do ciclo que abrem por contratante (o recebido no mes nao abre)
type EtapaAberta = Exclude<ChaveEtapa, "recebido_mes">;
/** #817: um contratante no ciclo, na cota. `chave` e' a do endereco da pagina dele (nula sem orgao no cadastro);
 *  `a_receber_centavos` e' o a receber da pagina do contratante e da lista de Obras (nao o em aberto do Fechamento,
 *  docs/adr/0006), e vem nulo sem o total a receber liberado */
type LinhaContratante = { contratante: string; chave: string | null; a_receber_centavos: number | null }
  & Record<`${EtapaAberta}_centavos`, number>;
/** #817: o medido de uma competencia, pela conta do Fechamento */
type MesMedido = { competencia: string; valor_centavos: number };
export type PainelInicio = {
  hoje: string;
  protocoladas: { obras_protocoladas: number; obras_ativas: number; ultima: string | null };
  // #805: `anterior` e' a competencia anterior e `ano_anterior` a mesma competencia do ano anterior
  medido: { competencia: string; valor_centavos: number; quantidade: number; ultimo_lancamento: string | null;
    anterior: ReferenciaMedido; ano_anterior: ReferenciaMedido };
  // 17/11/2026 (docs/adr/0006): o total soma so' a competencia de `ano_inicial` em diante que o RM ainda informa; o
  // resto vem em `a_parte` (nulo sem o total liberado) e a tela o mostra numa linha propria, fora do total
  a_receber: { liberado: boolean; valor_centavos: number | null; mais_60_centavos: number | null;
    a_parte: { ano_inicial: string; valor_centavos: number; anterior_centavos: number; sem_atualizacao_centavos: number;
      sem_atualizacao_desde: string | null } | null };
  ciclo: EtapaCiclo[];
  // #817: em cada etapa, a soma das linhas e' o valor da etapa em `ciclo`; a do a receber, `a_receber.valor_centavos`
  ciclo_por_contratante: LinhaContratante[];
  // #817: as 12 ultimas competencias fechadas (as da matriz), na cota, pela conta do Fechamento
  medido_12m: MesMedido[];
  recebido_12m: MesRecebido[];
  // #652: `depois` = data esperada alem do proximo mes
  previsao: Record<"neste_mes" | "proximo_mes" | "atrasado" | "sem_previsao" | "depois", GrupoPrevisao>;
  matriz: { competencias: string[]; grupos: { contratante: string; obras: ObraMatriz[] }[] };
  // #805: `anterior` e' o mes anterior ate' o mesmo dia do mes (`ate_dia`: o dia de hoje, ou o ultimo dia do mes
  // anterior quando ele e' mais curto); nulo sem com o que comparar
  notas_mes: { mes: string; valor_centavos: number; notas: number; obras: number;
    anterior: { mes: string; ate_dia: number; valor_centavos: number } | null };
};

/** O mes de uma referencia, curto e por extenso. O ano so' entra quando nao e' o do numero comparado: "set" e
 *  "setembro" no mesmo ano; "dez/25" e "dezembro de 2025" em outro. */
function mesDaReferencia(referencia: string, atual: string): { curto: string; extenso: string } {
  const mesmoAno = referencia.slice(0, 4) === atual.slice(0, 4);
  const curto = fmtMesCurto(referencia), extenso = fmtMesExtenso(referencia);
  return mesmoAno ? { curto: curto.split("/")[0], extenso } : { curto, extenso: `${extenso} de ${referencia.slice(0, 4)}` };
}

/** "Bom dia" / "Boa tarde" / "Boa noite" pela hora de Cuiaba. */
export function saudacao(agora: Date = new Date()): string {
  const h = Number(new Intl.DateTimeFormat("pt-BR", { hour: "numeric", hourCycle: "h23", timeZone: "America/Cuiaba" }).format(agora));
  return h >= 5 && h < 12 ? "Bom dia" : h >= 12 && h < 18 ? "Boa tarde" : "Boa noite";
}

// #642: o rotulo de cada etapa. #721: a cor e' a da propria etapa (inicio.css, --etapa-*), do azul claro da analise
// ao azul escuro do protocolado, e o verde do recebido
const ETAPAS: Record<ChaveEtapa, { rotulo: string }> = {
  em_analise: { rotulo: "Em análise" },
  boletim: { rotulo: "Boletim" },
  nota: { rotulo: "Nota" },
  protocolado: { rotulo: "Protocolado" },
  recebido_mes: { rotulo: "Recebido no mês" },
};

const dias = (n: number) => contar(n, "dia", "dias");
/** A quantidade da etapa: medicoes; no recebido, as notas com baixa no mes. */
const quantos = (e: EtapaCiclo) => e.etapa === "recebido_mes" ? contar(e.quantidade, "nota", "notas") : contar(e.quantidade, "medição", "medições");

/** Ciclo da medicao (#642, #721): uma etapa por linha, com a faixa na cor da etapa em cima. O comprimento da faixa e' a
 *  fracao da etapa de maior valor (`--ini-etapa-fracao`); etapa com valor nunca fica sem faixa (minimo de 1%) e etapa
 *  zerada nao tem faixa. A faixa e' desenho (o ::before da linha, em inicio.css); quem usa leitor de tela le a tabela
 *  equivalente. */
function CicloMedicao({ etapas, aParte }: { etapas: EtapaCiclo[]; aParte: PainelInicio["a_receber"]["a_parte"] }) {
  const maior = Math.max(0, ...etapas.map(e => e.valor_centavos));
  const fracao = (e: EtapaCiclo) => maior > 0 && e.valor_centavos > 0 ? Math.max(1, Math.round(100 * e.valor_centavos / maior)) : 0;
  return (
    <section aria-labelledby="ini-ciclo" className="cartao ini-painel ini-ciclo">
      <div className="ini-painel__cab"><h2 id="ini-ciclo">Ciclo da medição</h2></div>
      <ol className="ini-etapas" aria-hidden="true">
        {etapas.map(e => (
          <li key={e.etapa} className={`ini-etapa ini-etapa--${e.etapa}`}
            style={{ "--ini-etapa-fracao": `${fracao(e)}%` } as React.CSSProperties}>
            <span className="ini-etapa__rotulo">{ETAPAS[e.etapa].rotulo}</span>
            <span className="ini-etapa__valor">{brl(e.valor_centavos)}</span>
            <span className="ini-etapa__qtd">{quantos(e)}</span>
            {e.mais_antigo_dias !== null && (
              <span className="ini-etapa__idade">
                {e.mais_antigo_dias === 0 ? "mais antiga de hoje" : `mais antiga há ${dias(e.mais_antigo_dias)}`}</span>)}
          </li>
        ))}
      </ol>
      {/* fora da etapa "Protocolado" e de todo total: o em aberto antigo e o que o RM deixou de informar */}
      {aParte && <EmAbertoAParte anoInicial={aParte.ano_inicial} anterior={aParte.anterior_centavos}
        semAtualizacao={aParte.sem_atualizacao_centavos} desde={aParte.sem_atualizacao_desde} />}
      {/* `sr-only` no div, nao na <table>: tabela ignora largura e overflow e alargava a pagina no celular (PR #676) */}
      <div className="sr-only"><table>
        <caption>Ciclo da medição por etapa, na cota da Lotufo</caption>
        <thead><tr><th scope="col">Etapa</th><th scope="col">Valor</th><th scope="col">Quantidade</th><th scope="col">Mais antiga</th></tr></thead>
        <tbody>
          {etapas.map(e => (
            <tr key={e.etapa}>
              <th scope="row">{ETAPAS[e.etapa].rotulo}</th>
              <td>{brl(e.valor_centavos)}</td>
              <td>{quantos(e)}</td>
              <td>{e.mais_antigo_dias === null ? "—" : dias(e.mais_antigo_dias)}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </section>
  );
}

/** Valor de eixo, curto: "1,2 mi", "350 mil"; mes sem recebimento, tracinho. O valor inteiro esta' na tabela. */
function curto(centavos: number): string {
  return centavos > 0 ? (centavos / 100).toLocaleString("pt-BR", { notation: "compact", maximumFractionDigits: 1 }) : "—";
}

/** Recebido em 12 meses (#652): uma barra de tinta por mes, a ultima e' o mes corrente; o tamanho de cada uma e' a
 *  fracao do maior mes (`--ini-rec-tamanho`), com o valor curto logo acima dela (#721). Em painel estreito as barras
 *  deitam, um mes por linha (inicio.css). */
function Recebido12Meses({ meses }: { meses: MesRecebido[] }) {
  const maior = Math.max(0, ...meses.map(m => m.valor_centavos));
  return (
    <section aria-labelledby="ini-recebido" className="cartao ini-painel ini-recebido">
      <div className="ini-painel__cab"><h2 id="ini-recebido">Recebido em 12 meses</h2></div>
      <ol className="ini-rec" aria-hidden="true">
        {meses.map(m => (
          <li key={m.mes} className="ini-rec__mes" style={tamanhoDaColuna(m.valor_centavos, maior)}>
            <ColunaDoMes mes={m.mes} centavos={m.valor_centavos} />
          </li>
        ))}
      </ol>
      <div className="sr-only"><table>
        <caption>Recebido por mês, na cota da Lotufo</caption>
        <thead><tr><th scope="col">Mês</th><th scope="col">Recebido</th></tr></thead>
        <tbody>
          {meses.map(m => <tr key={m.mes}><th scope="row">{fmtCompetencia(m.mes)}</th><td>{brl(m.valor_centavos)}</td></tr>)}
        </tbody>
      </table></div>
    </section>
  );
}

/** O tamanho da coluna de um mes: a fracao do maior mes da serie (`--ini-rec-tamanho`); serie zerada nao divide por zero. */
function tamanhoDaColuna(centavos: number, maior: number): React.CSSProperties {
  return { "--ini-rec-tamanho": `${maior > 0 ? Math.round(100 * Math.max(0, centavos) / maior) : 0}%` } as React.CSSProperties;
}

/** O desenho de um mes nos graficos de 12 meses (recebido, #652, e medido, #817): o valor curto sobre a coluna e o mes embaixo. */
function ColunaDoMes({ mes, centavos }: { mes: string; centavos: number }) {
  return <>
    <span className="ini-rec__trilho"><span className="ini-rec__valor">{curto(centavos)}</span><span className="ini-rec__coluna" /></span>
    <span className="ini-rec__rotulo">{fmtMesCurto(mes)}</span>
  </>;
}

/** Medido em 12 meses (#817): a mesma forma do recebido, uma coluna por competencia, as 12 ultimas fechadas. O valor e' o
 *  medido do mes no Fechamento (a conta dele, na cota), e a coluna e' a porta para o mes la'; competencia sem medido nao
 *  tem o que abrir. A coluna e' um link com o nome escrito (`aria-label`); a tabela equivalente fica para o leitor de tela. */
function Medido12Meses({ meses, ir }: { meses: MesMedido[]; ir: Ir }) {
  const maior = Math.max(0, ...meses.map(m => m.valor_centavos));
  return (
    <section aria-labelledby="ini-medido" className="cartao ini-painel ini-medido">
      <div className="ini-painel__cab"><h2 id="ini-medido">Medido em 12 meses</h2></div>
      <ol className="ini-rec">
        {meses.map(m => {
          const nome = `Medido em ${fmtCompetencia(m.competencia)}: ${brl(m.valor_centavos)}`;
          const coluna = <ColunaDoMes mes={m.competencia} centavos={m.valor_centavos} />;
          return (
            <li key={m.competencia}>
              {m.valor_centavos > 0
                ? <Link para={{ tela: "fechamento" }} busca={{ mes: m.competencia }} ir={ir} className="ini-rec__mes ini-rec__mes--porta"
                  style={tamanhoDaColuna(m.valor_centavos, maior)} aria-label={nome} title={nome}>{coluna}</Link>
                : <span className="ini-rec__mes" style={tamanhoDaColuna(0, maior)} aria-hidden="true">{coluna}</span>}
            </li>);
        })}
      </ol>
      <div className="sr-only"><table>
        <caption>Medido por mês de competência, na cota da Lotufo</caption>
        <thead><tr><th scope="col">Competência</th><th scope="col">Medido</th></tr></thead>
        <tbody>
          {meses.map(m => <tr key={m.competencia}><th scope="row">{fmtCompetencia(m.competencia)}</th><td>{brl(m.valor_centavos)}</td></tr>)}
        </tbody>
      </table></div>
    </section>
  );
}

// #817: as colunas do ciclo por contratante, na ordem do ciclo; a marca e' a da etapa (MarcaEtapa)
const ETAPAS_ABERTAS: { chave: EtapaAberta; etapa: Etapa }[] = [
  { chave: "em_analise", etapa: "em_analise" }, { chave: "boletim", etapa: "boletim" },
  { chave: "nota", etapa: "nota" }, { chave: "protocolado", etapa: "protocolado" },
];

/** Ciclo por contratante (#817): onde o dinheiro esta' parado, por orgao. Uma linha por contratante e uma coluna por
 *  etapa do ciclo, com a marca da etapa, mais o a receber (so' com o total a receber liberado). A linha "Total" repete
 *  os numeros do painel do ciclo e o a receber: sao os que o servidor manda para eles, nao uma soma feita aqui (um teste
 *  do servidor confere que as linhas fecham com eles). O a receber e' o da pagina do contratante e da lista de Obras, e
 *  leva o mesmo rotulo que la' ("A receber"): o "Em aberto" e' o numero do Fechamento, outra conta (docs/adr/0006).
 *  O contratante e o a receber dele abrem a pagina do contratante, que mostra o mesmo valor; o contratante sem orgao no
 *  cadastro e o total nao tem pagina. Em painel estreito (celular) cada contratante vira um bloco, com a etapa escrita
 *  ao lado do valor (inicio.css). */
function CicloPorContratante({ linhas, ciclo, aReceber, ir }:
    { linhas: LinhaContratante[]; ciclo: EtapaCiclo[]; aReceber: PainelInicio["a_receber"]; ir: Ir }) {
  const comAReceber = aReceber.liberado;
  const total = (chave: EtapaAberta) => ciclo.find(e => e.etapa === chave)?.valor_centavos ?? 0;
  const valor = (centavos: number) => centavos > 0 ? brl(centavos) : "—";
  // no celular a etapa vai escrita na celula; no computador ela esta' no cabecalho da coluna e esta copia fica escondida
  const rotulo = (etapa: Etapa, texto?: string) =>
    <span className="ini-orgaos__rotulo" aria-hidden="true"><MarcaEtapa etapa={etapa}>{texto}</MarcaEtapa></span>;
  const aReceberDe = (centavos: number | null, nome: string, chave: string | null) => (
    <td className="col-num dinheiro num">
      {rotulo("em_aberto", "A receber")}
      <span className="ini-orgaos__valor">
        {centavos === null || centavos <= 0 ? "—"
          : chave ? <Link para={{ tela: "contratante", chave }} ir={ir} className="ini-porta"
            aria-label={`${nome}: ${brl(centavos)} a receber`}>{brl(centavos)}</Link>
          : brl(centavos)}
      </span>
    </td>);
  return (
    <section aria-labelledby="ini-orgaos" className="cartao ini-painel ini-orgaos">
      <div className="ini-painel__cab"><h2 id="ini-orgaos">Ciclo por contratante</h2></div>
      {linhas.length === 0 ? <p className="ini-vazio">Nenhum contratante com valor no ciclo.</p> : (
        <Rolagem rotulo="Tabela do ciclo por contratante">
          <table className="tabela ini-orgaos__tabela">
            <caption className="sr-only">Valor em cada etapa do ciclo por contratante, na cota da Lotufo</caption>
            <thead>
              <tr>
                <th scope="col">Contratante</th>
                {ETAPAS_ABERTAS.map(c => <th key={c.chave} scope="col" className="col-num"><MarcaEtapa etapa={c.etapa} /></th>)}
                {comAReceber && <th scope="col" className="col-num"><MarcaEtapa etapa="em_aberto">A receber</MarcaEtapa></th>}
              </tr>
            </thead>
            <tbody>
              {linhas.map(l => (
                <tr key={l.contratante} className="linha">
                  <th scope="row" className="ini-orgaos__nome">
                    {l.chave ? <Link para={{ tela: "contratante", chave: l.chave }} ir={ir}>{l.contratante}</Link> : l.contratante}
                  </th>
                  {ETAPAS_ABERTAS.map(c => (
                    <td key={c.chave} className="col-num dinheiro num">
                      {rotulo(c.etapa)}<span className="ini-orgaos__valor">{valor(l[`${c.chave}_centavos`])}</span>
                    </td>))}
                  {comAReceber && aReceberDe(l.a_receber_centavos, l.contratante, l.chave)}
                </tr>))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" className="ini-orgaos__nome">Total</th>
                {ETAPAS_ABERTAS.map(c => (
                  <td key={c.chave} className="col-num dinheiro num">
                    {rotulo(c.etapa)}<span className="ini-orgaos__valor">{valor(total(c.chave))}</span>
                  </td>))}
                {comAReceber && aReceberDe(aReceber.valor_centavos, "Total", null)}
              </tr>
            </tfoot>
          </table>
        </Rolagem>)}
    </section>
  );
}

// #652: as cinco linhas da previsao, na ordem da tela. Juntas somam a etapa "Protocolado" da faixa do ciclo: "Depois"
// (data esperada alem do proximo mes) entrou para o numero fechar na tela
const LINHAS_PREVISAO: { chave: keyof PainelInicio["previsao"]; rotulo: string }[] = [
  { chave: "neste_mes", rotulo: "Neste mês" },
  { chave: "proximo_mes", rotulo: "No próximo mês" },
  { chave: "depois", rotulo: "Depois" },
  { chave: "atrasado", rotulo: "Atrasado" },
  { chave: "sem_previsao", rotulo: "Sem previsão" },
];

/** Previsao de entrada (#652, #721): o protocolado pela data esperada (protocolo + prazo do orgao), em extrato: a
 *  chave de cor e o rotulo a' esquerda, o valor colado a' direita. Em cima, a faixa proporcional: um trecho por linha
 *  que tem valor, na cor da chave dela (desenho; os numeros estao nas linhas). So' o atrasado, quando existe, e'
 *  critico: texto no tom do critico e o simbolo da situacao; o resto fica em tinta. */
function PrevisaoEntrada({ previsao }: { previsao: PainelInicio["previsao"] }) {
  const total = LINHAS_PREVISAO.reduce((s, { chave }) => s + Math.max(0, previsao[chave].valor_centavos), 0);
  return (
    <section aria-labelledby="ini-previsao" className="cartao ini-painel ini-previsao">
      <div className="ini-painel__cab"><h2 id="ini-previsao">Previsão de entrada</h2></div>
      {total > 0 && (
        <div className="ini-previsao__faixa" aria-hidden="true">
          {LINHAS_PREVISAO.filter(({ chave }) => previsao[chave].valor_centavos > 0).map(({ chave, rotulo }) =>
            <span key={chave} className={`ini-previsao__seg ini-previsao__seg--${chave}`} title={rotulo}
              style={{ flexGrow: previsao[chave].valor_centavos / total }} />)}
        </div>)}
      <ul className="ini-previsao__linhas">
        {LINHAS_PREVISAO.map(({ chave, rotulo }) => {
          const g = previsao[chave];
          const critico = chave === "atrasado" && g.quantidade > 0;
          return (
            <li key={chave} className={`ini-previsao__linha ini-previsao__linha--${chave}${critico ? " ini-previsao__linha--critico" : ""}`}>
              <span className="ini-previsao__rotulo">{critico && <Glifo situacao="critico" />}{rotulo}</span>
              <span className="ini-previsao__valor">{brl(g.valor_centavos)}</span>
              <span className="ini-previsao__conta">{contar(g.quantidade, "medição", "medições")}</span>
            </li>);
        })}
      </ul>
    </section>
  );
}

// #659: as etapas da matriz na ordem da legenda: do azul mais claro ao mais escuro, o verde do recebido e o vermelho
// da protocolada alem do prazo, que leva tambem a marca "!" dentro da celula (#721; inicio.css)
const ETAPAS_MATRIZ: { chave: EtapaMatriz; rotulo: string }[] = [
  { chave: "em_analise", rotulo: "Em análise" },
  { chave: "boletim", rotulo: "Boletim" },
  { chave: "nota", rotulo: "Nota" },
  { chave: "protocolado", rotulo: "Protocolado" },
  { chave: "recebida", rotulo: "Recebido" },
  { chave: "atrasado", rotulo: "Atrasado" },
];
const ROTULO_MATRIZ = Object.fromEntries(ETAPAS_MATRIZ.map(e => [e.chave, e.rotulo])) as Record<EtapaMatriz, string>;
// a marca da legenda e' a peca MarcaEtapa (#805); a matriz chama de "recebida" a etapa que a peca chama de "recebido"
const marcaDaMatriz = (e: EtapaMatriz): Etapa => (e === "recebida" ? "recebido" : e);

/** Matriz obra por competencia (#659): uma linha por obra ativa, agrupada por contratante, e uma celula por competencia
 *  com a cor da etapa da medicao. A celula pintada e' o link para a medicao, com o nome (obra, competencia, etapa) no
 *  `aria-label` e na dica; a tabela equivalente fica para o leitor de tela. */
function MatrizObras({ matriz }: { matriz: PainelInicio["matriz"] }) {
  const { competencias, grupos } = matriz;
  return (
    <section aria-labelledby="ini-matriz" className="cartao ini-painel ini-matriz">
      <div className="ini-painel__cab">
        <h2 id="ini-matriz">Medições por obra e competência</h2>
        <ul className="ini-matriz__legenda" aria-label="Legenda das etapas">
          {ETAPAS_MATRIZ.map(e => <li key={e.chave}><MarcaEtapa etapa={marcaDaMatriz(e.chave)}>{e.rotulo}</MarcaEtapa></li>)}
        </ul>
      </div>
      {grupos.length === 0 ? <p className="ini-vazio">Nenhuma obra ativa.</p> : <>
        <div className="ini-matriz__grade">
          <div className="ini-matriz__linha ini-matriz__linha--meses" aria-hidden="true">
            {competencias.map((c, i) => {
              const [mes, ano] = fmtMesCurto(c).split("/");
              return (
                <span key={c} className="ini-matriz__mes">
                  <span>{mes}</span>{(i === 0 || c.endsWith("-01")) && <span className="ini-matriz__ano">{ano}</span>}
                </span>);
            })}
          </div>
          {grupos.map(g => (
            <Fragment key={g.contratante}>
              <h3 className="ini-matriz__grupo">{g.contratante}</h3>
              {g.obras.map(o => (
                <div key={o.contrato_id} className="ini-matriz__linha ini-matriz__linha--obra">
                  <span className="ini-matriz__obra">{o.obra}</span>
                  {competencias.map((c, i) => {
                    const cel = o.celulas[i];
                    if (!cel) return <span key={c} className="ini-matriz__celula" aria-hidden="true" />;
                    const nome = `${o.obra}, ${fmtCompetencia(c)}: ${ROTULO_MATRIZ[cel.etapa]}`;
                    return <Link key={c} para={{ tela: "medicao", obra: o.contrato_id, id: cel.medicao_id }}
                      className={`ini-matriz__celula ini-matriz__celula--${cel.etapa}`} aria-label={nome} title={nome}>{null}</Link>;
                  })}
                </div>))}
            </Fragment>))}
        </div>
        <div className="sr-only"><table>
          <caption>Etapa da medição de cada obra por competência</caption>
          <thead><tr><th scope="col">Obra</th><th scope="col">Contratante</th>
            {competencias.map(c => <th key={c} scope="col">{fmtCompetencia(c)}</th>)}</tr></thead>
          <tbody>
            {grupos.flatMap(g => g.obras.map(o => (
              <tr key={o.contrato_id}>
                <th scope="row">{o.obra}</th><td>{g.contratante}</td>
                {competencias.map((c, i) => { const cel = o.celulas[i]; return <td key={c}>{cel ? ROTULO_MATRIZ[cel.etapa] : "—"}</td>; })}
              </tr>)))}
          </tbody>
        </table></div>
      </>}
    </section>
  );
}

// #666: as secoes da caixa, na ordem da tela Avisos; "Depois" (31 a 90 dias) fica so' la'. A situacao vem da secao (o
// tempo), nao do `nivel` do aviso: vencido = critico; o que vence na semana ou no mes = vence em breve. #721: sao as
// situacoes das pecas Contador e Selo, ditas direto. Nao passam por `situacaoDoNivel`: la' "acao" e' critico, e o
// nome antigo daqui ("acao" no vencido, "atencao" no que vence) so' confundia.
const SECOES_DA_CAIXA: Partial<Record<Secao, Situacao>> = { vencido: "critico", semana: "breve", mes: "breve" };
const AVISOS_VISIVEIS = 3;

/** O selo de dias do item: "há N dias" no vencido; "hoje" ou "em N dias" no que vence. */
function seloDeDias(a: Aviso, secao: Secao): string {
  const n = Math.abs(diasAteOAviso(a) ?? 0), d = `${n.toLocaleString("pt-BR")} ${n === 1 ? "dia" : "dias"}`;
  return secao === "vencido" ? `há ${d}` : n === 0 ? "hoje" : `em ${d}`;
}

function ItemAviso({ a, secao, situacao, ir }: { a: Aviso; secao: Secao; situacao: Situacao; ir: Ir }) {
  const d = destinoDoAviso(a);
  // a obra (ou a empresa) abre o item, em destaque: a mensagem perde o "Nome: " do comeco, como na tela Avisos. Na tela
  // a obra e a mensagem ficam em linhas separadas; o " · " entre as duas e' so' para o leitor de tela
  const quem = a.obra ?? a.entidade ?? "";
  const texto = semRSOrfao((a.obra ? semObra(a) : semEmpresa(a)).mensagem);
  const corpo = <>
    <span className="ini-aviso__nome">
      {quem && <><span className="ini-aviso__obra">{quem}</span><span className="sr-only"> · </span></>}
      <span className="ini-aviso__msg">{texto}</span>
    </span>
    <Selo situacao={situacao}>{seloDeDias(a, secao)}</Selo>
  </>;
  return <li>{d ? <Link para={d.para} busca={d.busca} secao={d.secao} ir={ir} className="ini-aviso__linha">{corpo}</Link>
    : <span className="ini-aviso__linha">{corpo}</span>}</li>;
}

/** Caixa "Avisos importantes" (#666): so' o que esta' na agenda da tela Avisos, em tres secoes pelo tempo, cada uma
 *  com a contagem e os primeiros itens. `avisos`: `undefined` carregando, `null` falhou (como em AvisosPagina). */
function CaixaAvisos({ avisos, ir }: { avisos: Aviso[] | null | undefined; ir: Ir }) {
  const secoes = porSecao(daAgenda(avisos ?? [])).filter(s => SECOES_DA_CAIXA[s.id]);
  const total = secoes.reduce((n, s) => n + s.itens.length, 0);
  return (
    <aside aria-labelledby="ini-avisos" className="cartao ini-painel ini-avisos">
      <header className="ini-painel__cab">
        <h2 id="ini-avisos">Avisos importantes</h2>
        {avisos && <Contador rotulo={contar(total, "aviso", "avisos")}>{total.toLocaleString("pt-BR")}</Contador>}
        <Link para={{ tela: "avisos" }} ir={ir} className="ini-ver-todos" aria-label="Ver todos os avisos">Ver todos</Link>
      </header>
      {avisos === undefined && <p className="ini-carregando">Carregando…</p>}
      {avisos === null && <Falha>Não foi possível verificar os avisos. Recarregue a página para tentar de novo.</Falha>}
      {avisos && total === 0 && <p className="ini-vazio">Nenhum aviso.</p>}
      {avisos && total > 0 && (
        <div className="ini-avisos__secoes">
          {secoes.map(s => {
            const situacao = SECOES_DA_CAIXA[s.id] ?? "breve", id = `ini-av-${s.id}`;
            return (
              <section key={s.id} aria-labelledby={id} className="ini-aviso">
                <header className="ini-aviso__topo">
                  <h3 id={id}>{s.rotulo}</h3>
                  {/* secao sem aviso: contador neutro, sem o simbolo da situacao */}
                  <Contador situacao={s.itens.length > 0 ? situacao : undefined}>{s.itens.length.toLocaleString("pt-BR")}</Contador>
                </header>
                {s.itens.length > 0 && (
                  <ul className="ini-aviso__lista">
                    {s.itens.slice(0, AVISOS_VISIVEIS).map((a, i) =>
                      <ItemAviso key={`${a.tipo}-${a.contrato_id}-${a.entidade_id ?? ""}-${a.medicao_id ?? ""}-${i}`} a={a} secao={s.id} situacao={situacao} ir={ir} />)}
                  </ul>)}
              </section>);
          })}
        </div>)}
    </aside>
  );
}

export default function Inicio({ usuario, ir }: { usuario: Usuario; ir: Ir }) {
  const [p, setP] = useState<PainelInicio | null>(null);
  const [erro, setErro] = useState("");
  const [avisos, setAvisos] = useState<Aviso[] | null | undefined>(undefined);

  useEffect(() => {
    let vivo = true;
    api<PainelInicio>("/api/inicio/painel")
      .then(d => { if (vivo) setP(d); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    // a fila da tela Avisos; se falhar, so' a caixa mostra o erro
    api<{ avisos: Aviso[] }>("/api/inicio")
      .then(d => { if (vivo) setAvisos(d.avisos); })
      .catch(() => { if (vivo) setAvisos(null); });
    return () => { vivo = false; };
  }, []);

  const nome = usuario.nome.trim().split(/\s+/)[0] ?? "";
  const titulo = <h1 className="ini-titulo">{saudacao()}{nome ? `, ${nome}` : ""}</h1>;
  if (!p) {
    return (
      <div className="ini">
        {titulo}
        {erro ? <Falha>Não foi possível carregar o início: {erro}</Falha>
          : <p className="ini-carregando">Carregando…</p>}
      </div>
    );
  }

  const m = p.medido, nm = p.notas_mes;
  const mesDeHoje = p.hoje.slice(0, 7);
  const refNotas = nm.anterior && mesDaReferencia(nm.anterior.mes, mesDeHoje);
  const refAnterior = m.anterior && mesDaReferencia(m.anterior.competencia, m.competencia);
  const refAnoAnterior = m.ano_anterior && mesDaReferencia(m.ano_anterior.competencia, m.competencia);

  return (
    <div className="ini">
      <div className="ini-grade">
        <div className="ini-saudacao">
          {titulo}
          <LegendaCor />
        </div>
        <section aria-label="Números do mês" className="ini-numeros">
          <dl className="ini-numeros__lista">
            <div className="ini-numero">
              <dt className="ini-numero__rotulo">Notas fiscais protocoladas em {fmtMesExtenso(mesDeHoje)}</dt>
              {/* #817: o numero e' a porta para a pagina que diz em que etapa esta' a medicao de cada obra */}
              <dd className="ini-numero__valor"><Link para={{ tela: "resumo-medicoes" }} ir={ir} className="ini-porta">{brl(nm.valor_centavos)}</Link></dd>
              {/* o mes de hoje esta' pela metade: compara com o mes anterior ate' o mesmo dia, e o rotulo diz isso */}
              {nm.anterior && refNotas && (
                <dd className="ini-numero__variacoes">
                  <Variacao atual={nm.valor_centavos} referencia={nm.anterior.valor_centavos}
                    rotulo={`${refNotas.curto} até o dia ${nm.anterior.ate_dia}`} porExtenso={`${refNotas.extenso} até o dia ${nm.anterior.ate_dia}`} />
                </dd>)}
            </div>
            <div className="ini-numero">
              <dt className="ini-numero__rotulo">Medido em {fmtMesExtenso(m.competencia)}</dt>
              {/* #817: o medido do mes abre o mes no Fechamento */}
              <dd className="ini-numero__valor">
                <Link para={{ tela: "fechamento" }} busca={{ mes: m.competencia }} ir={ir} className="ini-porta">{brl(m.valor_centavos)}</Link>
              </dd>
              {(m.anterior || m.ano_anterior) && (
                <dd className="ini-numero__variacoes">
                  {m.anterior && refAnterior && <Variacao atual={m.valor_centavos} referencia={m.anterior.valor_centavos}
                    rotulo={refAnterior.curto} porExtenso={refAnterior.extenso} />}
                  {m.ano_anterior && refAnoAnterior && <Variacao atual={m.valor_centavos} referencia={m.ano_anterior.valor_centavos}
                    rotulo={refAnoAnterior.curto} porExtenso={refAnoAnterior.extenso} />}
                </dd>)}
            </div>
          </dl>
        </section>
        {/* a base dos valores, dita uma vez: vale para os paineis que vem a seguir, ate' os avisos */}
        <div className="ini-cota"><h2>Cota da Lotufo</h2></div>
        <CicloMedicao etapas={p.ciclo} aParte={p.a_receber.a_parte} />
        <PrevisaoEntrada previsao={p.previsao} />
        <CicloPorContratante linhas={p.ciclo_por_contratante} ciclo={p.ciclo} aReceber={p.a_receber} ir={ir} />
        <Recebido12Meses meses={p.recebido_12m} />
        <Medido12Meses meses={p.medido_12m} ir={ir} />
        <CaixaAvisos avisos={avisos} ir={ir} />
        <MatrizObras matriz={p.matriz} />
      </div>
    </div>
  );
}
