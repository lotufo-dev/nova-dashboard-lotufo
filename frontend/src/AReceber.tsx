import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import CaixaAviso from "./CaixaAviso";
import Falha from "./Falha";
import { brl, contar } from "./formato";
import { Link } from "./Link";
import MarcaEtapa from "./MarcaEtapa";
import { tituloMedicao } from "./medicao";
import type { Parada } from "./parada";
import { diaMes } from "./Passos";
import Rolagem from "./Rolagem";
import type { Busca, Ir } from "./rota";
import Selo from "./Selo";
import TempoParado from "./TempoParado";
import { fmtCompetencia, fmtDataPura } from "./tempo";
import "./aReceber.css";

// A RECEBER (#816; decisao do dono de 18/11/2026, #805): o em aberto do Fechamento nota a nota, na area Financeiro.
// A pergunta e' "o que esta' protocolado e ainda nao entrou, e ha' quanto tempo": um grupo por contratante (o cabecalho
// de grupo forte, com quantas linhas, o prazo de pagamento do orgao e o subtotal) e, dentro dele, pela data do
// protocolo, a mais antiga primeiro. Sem faixas de dias. Cada linha: a obra e a medicao, a nota, a data do protocolo,
// o tempo parado com a data prevista (quando o prazo do orgao e' conhecido) e o valor em aberto.
//
// Tudo vem pronto de GET /api/a-receber (`app/a_receber.py`): o total e' o em aberto do Fechamento (2025 e 2026), o
// subtotal de cada contratante e' o dele na aba "Por contratante" do Fechamento, e o tempo parado e' a leitura do
// servidor, com o prazo do orgao como limite. A tela nao soma, nao conta e nao le prazo nenhum.
//
// O total leva o rotulo do Fechamento ("Em aberto"), e uma frase diz o que ele soma: o "a receber" da Inicio e de
// Obras e' outra conta (docs/adr/0006), e as duas paginas que levam o nome diferem.
//
// `?contratante=<chave>` mostra so' um contratante. A chave e' a da pagina dele em Obras ("/obras/contratante/<chave>");
// a fileira de escolhas mantem os contratantes sem nada em aberto, com zero. Sem filtro, com mais de um contratante
// com linhas, os grupos nascem recolhidos (so' o cabecalho, com o subtotal): com o volume da producao a pagina inteira
// passava de uma tela e meia. Um clique no nome abre o grupo ali mesmo.
//
// A' parte, fora do total: a nota sem medicao ligada e o em aberto de antes de 2025. Com o total a receber ainda nao
// liberado (a trava do Fechamento), o servidor nao manda nada do em aberto e a pagina diz a trava em uma frase.

/** (a) nota protocolada nao paga (a paga em parte, pelo que falta), (a') repasse sem baixa (o orgao pagou o
 *  consorcio; quem deve e' o consorcio) ou (b) medicao protocolada sem nota ligada. */
export type LinhaAReceber = {
  tipo_aberto: "nota" | "repasse" | "sem_nota"; nota_id: number | null; numero: string | null; valor_centavos: number;
  paga_em_parte: boolean; contrato_id: number; obra: string; medicao_id: number; medicao_numero: number; tipo: string;
  competencia: string; protocolo_em: string | null;
  /** #743: na obra sem o passo "Envio da nota" nao ha' protocolo; a espera conta da emissao da nota */
  emitida_em: string | null;
  /** o tempo parado desde o protocolo, com o prazo do orgao; nulo no repasse (o orgao ja' pagou) */
  parada: Parada | null;
  /** so' no repasse: o dia em que o orgao pagou (nulo na medicao recebida sem data) */
  orgao_pagou_em: string | null;
};
/** Nota de cobranca em aberto no RM sem medicao ligada: sem competencia, fora do total. */
export type NotaSemMedicao = { nota_id: number; numero: string; contrato_id: number; obra: string; emissao: string | null;
  valor_centavos: number; paga_em_parte: boolean };
type Anteriores = { quantidade: number; valor_centavos: number };
/** Um contratante: `chave` e' a da pagina dele em Obras (nula sem orgao no cadastro); `prazo_orgao_dias`, o prazo de
 *  pagamento (docs/adr/0007; nulo = sem previsao); `alem_do_prazo`, quantas linhas passaram da data esperada. */
export type ContratanteAReceber = {
  contratante: string; chave: string | null; prazo_orgao_dias: number | null; quantidade: number; em_aberto_centavos: number;
  por_ano: Record<string, number>; alem_do_prazo: number; linhas: LinhaAReceber[];
  notas_sem_medicao: NotaSemMedicao[]; notas_sem_medicao_centavos: number; anteriores: Anteriores;
};
export type RespostaAReceber = {
  anos: string[]; total_a_receber_liberado: boolean;
  em_aberto_centavos?: number; por_ano?: Record<string, number>; quantidade?: number; alem_do_prazo?: number;
  /** a lista inteira, na ordem do servidor (a emissao, a mais antiga primeiro); cada contratante leva as dele */
  notas_sem_medicao?: NotaSemMedicao[];
  notas_sem_medicao_centavos?: number; anteriores?: Anteriores; contratantes?: ContratanteAReceber[];
};

/** O que a vista mostra: a pagina inteira ou um contratante, com os numeros que o servidor mandou para ela. */
export type Vista = { quantidade: number; em_aberto_centavos: number; por_ano: Record<string, number>; alem_do_prazo: number;
  grupos: ContratanteAReceber[]; soltas: NotaSemMedicao[]; soltas_centavos: number; anteriores: Anteriores };

const AQUI = { tela: "a-receber" } as const;
export const BASE = "O em aberto do Fechamento, na cota da Lotufo e pelo valor bruto da nota; o a receber da Início e de Obras "
  + "também soma cobranças do RM sem medição em aberto.";
export const TRAVA = "O total a receber ainda não está liberado: o em aberto fica sem valor.";

function prazoDoOrgao(dias: number | null): string {
  return dias === null ? "sem previsão de pagamento" : `prazo do órgão: ${contar(dias, "dia", "dias")}`;
}

function vistaDe(r: Required<RespostaAReceber>, um: ContratanteAReceber | null): Vista {
  if (um) {
    return { ...um, grupos: um.quantidade > 0 ? [um] : [], soltas: um.notas_sem_medicao, soltas_centavos: um.notas_sem_medicao_centavos };
  }
  return { quantidade: r.quantidade, em_aberto_centavos: r.em_aberto_centavos, por_ano: r.por_ano, alem_do_prazo: r.alem_do_prazo,
    grupos: r.contratantes.filter(g => g.quantidade > 0), soltas: r.notas_sem_medicao, soltas_centavos: r.notas_sem_medicao_centavos,
    anteriores: r.anteriores };
}

/* ------------------------------------------------------------------ linhas */

/** De quando a espera conta: o protocolo; sem ele, a emissao da nota (obra sem o passo "Envio da nota"). */
function DataDaLinha({ l }: { l: LinhaAReceber }) {
  if (l.protocolo_em) return <span className="num">{fmtDataPura(l.protocolo_em)}</span>;
  if (l.emitida_em) return <span className="arc-sem-data">nota emitida em <span className="num">{fmtDataPura(l.emitida_em)}</span></span>;
  return <span className="arc-sem-data">sem data de protocolo</span>;
}

/** O numero da nota e o selo do que a linha e': paga em parte (o valor e' o que falta) ou repasse sem baixa. */
function NotaDaLinha({ l }: { l: LinhaAReceber }) {
  if (l.numero === null) return <Selo>sem nota ligada</Selo>;
  return (
    <span className="arc-nota">
      <span className="num">{l.numero}</span>
      {l.tipo_aberto === "repasse" ? <Selo situacao="andamento">repasse sem baixa</Selo>
        : l.paga_em_parte && <Selo situacao="andamento">paga em parte</Selo>}
    </span>
  );
}

/** O tempo parado com o orgao; no repasse o orgao ja' pagou (a medicao recebida leva o selo do feito, com a data). */
function ParadaDaLinha({ l }: { l: LinhaAReceber }) {
  if (l.tipo_aberto === "repasse") {
    const dia = diaMes(l.orgao_pagou_em);
    return <Selo situacao="feito">{dia ? <>órgão pagou em <span className="num">{dia}</span></> : "órgão pagou"}</Selo>;
  }
  return l.parada ? <TempoParado parada={l.parada} /> : <span className="tempo-parado tempo-parado--sem">—</span>;
}

function Linha({ l, ir }: { l: LinhaAReceber; ir: Ir }) {
  return (
    <tr>
      <th scope="row" className="arc-a-medicao">
        <Link className="arc-obra" para={{ tela: "obra", id: l.contrato_id, aba: "medicoes" }} ir={ir}>{l.obra}</Link>
        <span className="arc-sub">
          <Link para={{ tela: "medicao", obra: l.contrato_id, id: l.medicao_id }} ir={ir}>{tituloMedicao({ numero: l.medicao_numero, tipo: l.tipo })}</Link>
          {" · "}<span className="num">{fmtCompetencia(l.competencia)}</span>
        </span>
      </th>
      <td className="arc-a-nota" data-rotulo="Nota"><NotaDaLinha l={l} /></td>
      <td className="arc-a-data" data-rotulo="Protocolo"><DataDaLinha l={l} /></td>
      <td className="arc-a-parada" data-rotulo="Parada há"><ParadaDaLinha l={l} /></td>
      <td className="col-num dinheiro num arc-a-valor arc-em-aberto">{brl(l.valor_centavos)}</td>
    </tr>
  );
}

/** O cabecalho de grupo forte do contratante: o nome (o botao que abre e fecha o grupo, quando ele nasce recolhido),
 *  quantas linhas, o prazo do orgao, as que passaram da data esperada e o subtotal na coluna do valor. */
function CabecaDoGrupo({ g, aberto, alternar, id }: { g: ContratanteAReceber; aberto: boolean; alternar: (() => void) | null; id: string }) {
  const nome = alternar
    ? <button type="button" className="arc-grupo__abre" aria-expanded={aberto} aria-controls={id} onClick={alternar}>
        <span className="arc-grupo__seta" aria-hidden="true">{aberto ? "▾" : "▸"}</span>{g.contratante}
      </button>
    : <span className="arc-grupo__nome">{g.contratante}</span>;
  return (
    <tr className="arc-grupo">
      <th scope="rowgroup" colSpan={4}>
        <span className="arc-grupo__cab">
          {nome}
          <span className="arc-grupo__meta">{contar(g.quantidade, "em aberto", "em aberto")} · {prazoDoOrgao(g.prazo_orgao_dias)}</span>
          {g.alem_do_prazo > 0 && <Selo situacao="critico">{g.alem_do_prazo} além do prazo<span className="sr-only"> do órgão</span></Selo>}
        </span>
      </th>
      <td className="col-num dinheiro num">{brl(g.em_aberto_centavos)}</td>
    </tr>
  );
}

export function Tabela({ grupos, recolhidos, ir }: { grupos: ContratanteAReceber[]; recolhidos: boolean; ir: Ir }) {
  const [abertos, setAbertos] = useState<ReadonlySet<string>>(() => new Set());
  const alternar = (nome: string) => setAbertos(a => {
    const novo = new Set(a);
    if (!novo.delete(nome)) novo.add(nome);
    return novo;
  });
  return (
    <Rolagem rotulo="Em aberto por contratante" className="tabela-wrap arc-rolagem">
      <table className="tabela arc-tabela">
        <caption className="sr-only">Em aberto nota a nota, na cota da Lotufo, por contratante e pela data do protocolo, com o tempo parado desde o protocolo e o valor em aberto</caption>
        <thead>
          <tr>
            <th scope="col">Medição</th><th scope="col">Nota</th><th scope="col">Protocolo</th><th scope="col">Parada há</th>
            <th scope="col" className="col-num"><MarcaEtapa etapa="em_aberto">Em aberto</MarcaEtapa></th>
          </tr>
        </thead>
        {grupos.map((g, i) => {
          const id = `arc-grupo-${i}`;
          const aberto = !recolhidos || abertos.has(g.contratante);
          return (
            <tbody key={g.contratante} id={id}>
              <CabecaDoGrupo g={g} aberto={aberto} alternar={recolhidos ? () => alternar(g.contratante) : null} id={id} />
              {aberto && g.linhas.map(l => <Linha key={`${l.tipo_aberto}-${l.medicao_id}-${l.nota_id ?? ""}`} l={l} ir={ir} />)}
            </tbody>
          );
        })}
      </table>
    </Rolagem>
  );
}

/* ------------------------------------------------------------------ numeros e a' parte */

/** O total da vista, com o de cada ano (os numeros do Fechamento, que mostra um ano por vez; o ano sem nada em aberto
 *  nao entra) e, quando ha', quantas linhas passaram da data esperada do recebimento. */
export function Numeros({ v, anos }: { v: Vista; anos: string[] }) {
  const doAno = [...anos].reverse().filter(a => (v.por_ano[a] ?? 0) !== 0);
  return (
    <dl className="arc-numeros">
      <div className="arc-numero">
        <dt className="arc-numero__rotulo"><MarcaEtapa etapa="em_aberto">Em aberto</MarcaEtapa></dt>
        <dd className="arc-numero__valor">{brl(v.em_aberto_centavos)}</dd>
        {doAno.length > 1 && (
          <dd className="arc-numero__apoio">
            {doAno.map((a, i) => <span key={a}>{i > 0 && " · "}{a}: <span className="num">{brl(v.por_ano[a])}</span></span>)}
          </dd>
        )}
      </div>
      {v.alem_do_prazo > 0 && (
        <div className="arc-numero arc-numero--selo">
          <dt className="sr-only">Passaram da data esperada do recebimento</dt>
          <dd><Selo situacao="critico">{v.alem_do_prazo.toLocaleString("pt-BR")} além do prazo do órgão</Selo></dd>
        </div>
      )}
    </dl>
  );
}

/** Fora do total, como no Fechamento: a nota em aberto no RM sem medicao ligada (sem competencia) e o em aberto de
 *  competencia anterior ao primeiro ano. */
export function APartes({ v, anos, comSemNota }: { v: Vista; anos: string[]; comSemNota: boolean }) {
  if (v.soltas.length === 0 && v.anteriores.quantidade === 0) return null;
  return (
    <section className="cartao arc-painel" aria-labelledby="arc-aparte">
      <div className="arc-painel__cab"><h2 id="arc-aparte">À parte, fora do total</h2></div>
      {v.soltas.length > 0 && <>
        <h3 className="arc-subtitulo" id="arc-soltas">Nota sem medição ligada</h3>
        {comSemNota && (
          <CaixaAviso nivel="atencao" className="arc-aviso">
            Medição sem nota ligada e nota sem medição ligada podem ser a mesma cobrança enquanto o vínculo não for feito.
          </CaixaAviso>
        )}
        <Rolagem rotulo="Notas sem medição ligada" className="tabela-wrap arc-rolagem">
          <table className="tabela arc-tabela arc-tabela--soltas" aria-labelledby="arc-soltas">
            <thead>
              <tr><th scope="col">Obra</th><th scope="col">Nota</th><th scope="col">Emissão</th>
                <th scope="col" className="col-num"><MarcaEtapa etapa="em_aberto">Em aberto</MarcaEtapa></th></tr>
            </thead>
            <tbody>
              {v.soltas.map(n => (
                <tr key={n.nota_id}>
                  <th scope="row" className="arc-a-medicao"><span className="arc-obra">{n.obra}</span></th>
                  <td className="arc-a-nota" data-rotulo="Nota">
                    <span className="arc-nota"><span className="num">{n.numero}</span>
                      {n.paga_em_parte && <Selo situacao="andamento">paga em parte</Selo>}</span>
                  </td>
                  <td className="arc-a-data" data-rotulo="Emissão">
                    {n.emissao ? <span className="num">{fmtDataPura(n.emissao)}</span> : <span className="arc-sem-data">sem data de emissão</span>}
                  </td>
                  <td className="col-num dinheiro num arc-a-valor">{brl(n.valor_centavos)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot><tr><th scope="row" colSpan={3}>Subtotal à parte</th><td className="col-num dinheiro num">{brl(v.soltas_centavos)}</td></tr></tfoot>
          </table>
        </Rolagem>
      </>}
      {v.anteriores.quantidade > 0 && (
        <dl className="arc-antigo">
          <div><dt>Em aberto de competências anteriores a {anos[0]}</dt>
            <dd className="num">{brl(v.anteriores.valor_centavos)}</dd></div>
        </dl>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ pagina */

export default function AReceber({ busca = {}, ir }: { busca?: Busca; ir: Ir }) {
  const [r, setR] = useState<RespostaAReceber | null>(null);
  const [erro, setErro] = useState("");
  useEffect(() => {
    let vivo = true;
    api<RespostaAReceber>("/api/a-receber").then(d => { if (vivo) setR(d); })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, []);
  const filtro = (busca.contratante ?? "").trim().slice(0, 80);
  if (erro) return <Falha>Não foi possível carregar o a receber: {erro} Recarregue a página para tentar de novo.</Falha>;
  if (!r) return <p className="arc-carregando" role="status">Carregando…</p>;
  if (!r.total_a_receber_liberado) {
    return (
      <div className="arc">
        <CaixaAviso nivel="atencao" className="arc-aviso">{TRAVA}</CaixaAviso>
      </div>
    );
  }
  const tudo = r as Required<RespostaAReceber>;
  const um = filtro ? tudo.contratantes.find(g => g.chave !== null && g.chave.toLowerCase() === filtro.toLowerCase()) ?? null : null;
  const nome = um?.contratante ?? filtro;
  const v = vistaDe(tudo, filtro ? um ?? { ...SEM_NADA, contratante: filtro } : null);
  const opcoes = tudo.contratantes.filter(g => g.chave !== null);
  const recolhidos = !filtro && v.grupos.length > 1;
  const comSemNota = v.grupos.some(g => g.linhas.some(l => l.tipo_aberto === "sem_nota"));
  return (
    <div className="arc">
      {opcoes.length > 0 && (
        <nav className="escolhas arc-escolhas" aria-label="Contratante">
          <Link className="escolha" para={AQUI} ir={ir} aria-current={filtro ? undefined : "true"}>
            Todos <span className="escolha__n num">{tudo.quantidade.toLocaleString("pt-BR")}</span>
          </Link>
          {opcoes.map(g => (
            <Link key={g.contratante} className="escolha" para={AQUI} busca={{ contratante: g.chave ?? "" }} ir={ir}
              aria-current={um === g ? "true" : undefined}>
              {g.contratante} <span className="escolha__n num">{g.quantidade.toLocaleString("pt-BR")}</span>
            </Link>
          ))}
        </nav>
      )}
      {v.quantidade > 0 && <>
        <Numeros v={v} anos={tudo.anos} />
        <p className="arc-base">{BASE}</p>
      </>}
      {v.grupos.length === 0 ? (
        <section className="cartao" aria-label={filtro ? `Em aberto de ${nome}` : "Em aberto"}>
          <div className="vazio vazio--curto">
            <p className="vazio__titulo">{filtro ? `Nenhuma nota em aberto de ${nome}.` : "Nenhuma nota em aberto."}</p>
            {filtro && <p><Link para={AQUI} ir={ir}>Ver todos os contratantes</Link></p>}
          </div>
        </section>
      ) : (
        <section className="cartao arc-painel" aria-label={filtro ? `Em aberto de ${nome}` : "Em aberto por contratante"}>
          <Tabela key={filtro} grupos={v.grupos} recolhidos={recolhidos} ir={ir} />
        </section>
      )}
      <APartes v={v} anos={tudo.anos} comSemNota={comSemNota} />
    </div>
  );
}

/** O contratante do endereco que a resposta nao conhece: a vista vazia, sem nada a' parte. */
const SEM_NADA: ContratanteAReceber = { contratante: "", chave: null, prazo_orgao_dias: null, quantidade: 0, em_aberto_centavos: 0,
  por_ano: {}, alem_do_prazo: 0, linhas: [], notas_sem_medicao: [], notas_sem_medicao_centavos: 0,
  anteriores: { quantidade: 0, valor_centavos: 0 } };
