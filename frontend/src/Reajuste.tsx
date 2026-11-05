import { useCallback, useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import { CartaoPleito, NovoPleito, type Pleito, type Reemissao } from "./FluxoOficio";
import { IconeAlerta } from "./icones";
import { focarPorId } from "./foco";
import { cicloDoApostilamento, reajustePorDataBase, termosCorrigidos, type BaseDoTermo, type CicloApi,
  type InstrumentoCadastro } from "./obra";
import { Link } from "./Link";
import { fmtCompetencia as mesAno, fmtDataPura } from "./tempo";
import { brl, fmtPercentual } from "./formato";
import Rolagem from "./Rolagem";
import Selo from "./Selo";
import { LinhaPleito, partesDoEnvio, pleitoEmLinha, type DesfechoPleito } from "./Prazos";

// Aba Reajuste da obra (bloco 7; spec §7.2; NAVEGACAO.md › Obra): um grupo por data-base, com ancora
// (`#db-2023-01`): o cartao do ciclo corrente (situacao, pleito e apostilamento, a tabela por competencia e a
// linha do tempo do ciclo, issue #275), os oficios do ciclo e os ciclos passados recolhidos. Com mais de uma
// data-base, um indice no topo leva a cada uma. O calendario mora em `app/reajuste.py`; a tela so' desenha.

// o mes, a parte do contrato a que a base se aplica (D7: "itens SICRO", "itens SINAPI") e o indice que a corrige
function rotuloDataBase(mes: string, c: CicloApi) {
  return `${mesAno(mes)}${c.aplica_a ? ` (${c.aplica_a})` : ""}${c.indice ? ` · ${c.indice}` : ""}`;
}

// `pleito`: o enviado mais recente do ciclo (o servidor diz quem ele e'); e' nele que se reitera ou reemite.
// `aditivos`: os da linha do tempo do ciclo (issue #275, `reajuste.aditivos_do_ciclo`)
type Ciclo = CicloApi & { situacao: "futuro" | "pleito_pendente" | "apostilamento_pendente" | "reemitir" | "apostilado";
  pleito?: { id: number } | null; aditivos?: AditivoDoCiclo[] };

// issue #277: o que o botao faz no pleito vigente do ciclo (o servidor diz quais cabem, em `reemissoes_possiveis`)
const ACAO_REEMISSAO: Record<Reemissao, { botao: string; titulo: string }> = {
  reiteracao: { botao: "Reiterar", titulo: "Reiteração do pleito" },
  cronograma: { botao: "Reemitir cronograma", titulo: "Reemissão do cronograma do pleito" },
};

/** Competencia com previsao vigente de apostilamento (issue #271; `reajuste.competencias_apostiladas`): aqui so'
 *  para nomear o termo de uma competencia quando o cadastro nao o lista. */
type CompetenciaApostilada = { instrumento_chave: string; instrumento_numero: string | null; instrumento_data: string };

// Issue #275 (spec 2026-10-20 §2.2): uma linha de `reajuste.competencias_por_ciclo`. O estado, o valor de cada fonte e
// os avisos vem do servidor; a tela so' desenha, com a origem de cada celula no titulo.
type EstadoCompetencia = "prevista" | "pedida" | "aprovada" | "apostilada" | "faturada" | "recebida";
type AvisoCompetencia = "fora_da_previsao" | "sem_apostilamento" | "nota_antes_do_apostilamento";
type Competencia = { competencia: string; estado: EstadoCompetencia; previsto_centavos: number | null;
  previsto_origem: "pleito" | "manual" | null; medicoes: number[]; pedido_centavos: number | null;
  aprovado_centavos: number | null; apostilada: boolean; apostilado_centavos: number | null;
  apostilado_percentual: string | number | null; apostilamento_chave: string | null;
  medicao_orgao: string | number | null; faturado_centavos: number | null; recebida_em: string | null;
  avisos?: AvisoCompetencia[] };
/** Data-base e ciclo; os dois nulos no grupo da medicao cuja data-base nao se decide (duas bases, nada gravado). */
type GrupoDoCiclo = { data_base_mes: string | null; ciclo: number | null; competencias: Competencia[] };
type NomeDoTermo = { numero: string | null; data: string };

const ORIGEM_PREVISTO: Record<string, string> = { pleito: "planilha do pleito", manual: "digitada" };

/** As medicoes de reajuste da competencia: "3ª medição de reajuste", "4ª e 7ª medições de reajuste". */
function dasMedicoes(ns: number[]): string {
  const o = ns.map(n => `${n}ª`);
  return o.length > 1 ? `${o.slice(0, -1).join(", ")} e ${o[o.length - 1]} medições de reajuste`
    : `${o[0] ?? ""} medição de reajuste`.trim();
}

/** O percentual do termo da MT-PAR como o cadastro o guarda ("6,76" ou 6.76). */
function percentual(p: string | number): string {
  const s = String(p).trim();
  const n = typeof p === "number" ? p : Number(s.includes(",") ? s.replace(/\./g, "").replace(",", ".") : s);
  return Number.isFinite(n) ? fmtPercentual(n / 100) : `${s}%`;
}

function somaDe(linhas: Competencia[], f: (x: Competencia) => number | null): number | null {
  const v = linhas.map(f).filter((n): n is number => n !== null);
  return v.length > 0 ? v.reduce((a, b) => a + b, 0) : null;
}

/** O estado da competencia e, quando ha', a marca do aviso. A nota antes do termo e' o critico e cobre o "sem
 *  apostilamento" da mesma competencia: um selo so', o mais grave. */
function SituacaoDaCompetencia({ x }: { x: Competencia }) {
  const avisos = x.avisos ?? [];
  const comApostilado = x.apostilado_centavos !== null;
  return (
    <span className="selos">
      <Selo>{x.estado}</Selo>
      {avisos.includes("fora_da_previsao") && (
        <Selo classe="selo--atencao" title={`Pedido ${brl(x.pedido_centavos)}; ${comApostilado ? "apostilado" : "previsto"} ${
          brl(comApostilado ? x.apostilado_centavos : x.previsto_centavos)}`}>fora da previsão</Selo>
      )}
      {avisos.includes("nota_antes_do_apostilamento")
        ? <Selo classe="selo--acao">nota antes do apostilamento</Selo>
        : avisos.includes("sem_apostilamento") && <Selo classe="selo--atencao">sem apostilamento</Selo>}
    </span>
  );
}

/** A tabela de um ciclo: competencia × previsto × pedido × aprovado × apostilado × nota × recebido, com o estado. */
function TabelaCompetencias({ rotulo, linhas, termos }: { rotulo: string; linhas: Competencia[];
    termos: Map<string, NomeDoTermo> }) {
  const origem = (texto: string | null) => (texto ? `Origem: ${texto}` : undefined);
  const daMedicao = (x: Competencia, prefixo: string, valor: unknown) =>
    valor !== null && x.medicoes.length > 0 ? origem(`${prefixo}${dasMedicoes(x.medicoes)}`) : undefined;
  const doTermo = (x: Competencia) => {
    if (!x.apostilada || (x.apostilado_centavos === null && x.apostilado_percentual === null)) return undefined;
    const t = x.apostilamento_chave ? termos.get(x.apostilamento_chave) : undefined;
    const med = x.medicao_orgao !== null && x.medicao_orgao !== "" ? ` (${x.medicao_orgao}ª medição)` : "";
    return origem(`apostilamento${t ? ` ${t.numero ?? "s/n"}, de ${fmtDataPura(t.data)}` : ""}${med}`);
  };
  return (
    <Rolagem rotulo={rotulo}>
      <table className="tabela tabela--densa reajuste-competencias">
        <caption className="sr-only">{rotulo}</caption>
        <thead>
          <tr>
            <th scope="col">Competência</th>
            <th scope="col" className="col-num">Previsto</th>
            <th scope="col" className="col-num">Pedido</th>
            <th scope="col" className="col-num">Aprovado</th>
            <th scope="col" className="col-num">Apostilado</th>
            <th scope="col" className="col-num">Nota</th>
            <th scope="col" className="col-num">Recebido</th>
            {/* a 1024 px a tabela rola na horizontal: a situacao, com a marca do aviso, fica ancorada a' direita */}
            <th scope="col" className="col-fixa">Situação</th>
          </tr>
        </thead>
        <tbody>
          {linhas.map((x, i) => (
            <tr key={x.competencia} className={`linha${i % 2 === 1 ? " par" : ""}`}>
              <th scope="row" className="forte num">{mesAno(x.competencia)}</th>
              <td className="col-num dinheiro num"
                title={x.previsto_centavos !== null && x.previsto_origem
                  ? origem(ORIGEM_PREVISTO[x.previsto_origem] ?? x.previsto_origem) : undefined}>
                {brl(x.previsto_centavos)}
              </td>
              <td className="col-num dinheiro num" title={daMedicao(x, "", x.pedido_centavos)}>{brl(x.pedido_centavos)}</td>
              <td className="col-num dinheiro num" title={daMedicao(x, "boletim da ", x.aprovado_centavos)}>
                {brl(x.aprovado_centavos)}
              </td>
              <td className="col-num dinheiro num" title={doTermo(x)}>
                {x.apostilado_centavos !== null ? brl(x.apostilado_centavos)
                  : x.apostilada && x.apostilado_percentual !== null ? percentual(x.apostilado_percentual) : "—"}
              </td>
              <td className="col-num dinheiro num" title={daMedicao(x, "notas fiscais da ", x.faturado_centavos)}>
                {brl(x.faturado_centavos)}
              </td>
              <td className="col-num num" title={daMedicao(x, "baixa no RM da ", x.recebida_em)}>
                {x.recebida_em ? fmtDataPura(x.recebida_em.slice(0, 10)) : "—"}
              </td>
              <td className="col-fixa"><SituacaoDaCompetencia x={x} /></td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">Total</th>
            <td className="col-num dinheiro num">{brl(somaDe(linhas, x => x.previsto_centavos))}</td>
            <td className="col-num dinheiro num">{brl(somaDe(linhas, x => x.pedido_centavos))}</td>
            <td className="col-num dinheiro num">{brl(somaDe(linhas, x => x.aprovado_centavos))}</td>
            <td className="col-num dinheiro num">{brl(somaDe(linhas, x => x.apostilado_centavos))}</td>
            <td className="col-num dinheiro num">{brl(somaDe(linhas, x => x.faturado_centavos))}</td>
            <td />
            <td />
          </tr>
        </tfoot>
      </table>
    </Rolagem>
  );
}

/** O nome da tabela de um grupo: a data-base e o ciclo, ou o grupo sem data-base. */
function rotuloDoGrupo(g: GrupoDoCiclo): string {
  return g.data_base_mes === null ? "Reajuste por competência sem data-base definida"
    : `Reajuste por competência da data-base ${mesAno(g.data_base_mes)}, ciclo de ${g.ciclo}`;
}

// Issue #275: um aditivo assinado no ciclo depois do primeiro pleito enviado (`reajuste.aditivos_do_ciclo`)
type AditivoDoCiclo = { id: number; numero: string | null; tipo: string; data_assinatura: string };
const TIPO_ADITIVO: Record<string, string> = { prazo: "de prazo", valor: "de valor", misto: "de prazo e valor" };

/** A linha do tempo do ciclo (spec 2026-10-20 §2.2): o envio de cada pleito, reiteracao e reemissao, os aditivos que
 *  pedem reemissao e o termo, em ordem de data. Na mesma data, o pleito vem antes do aditivo e o aditivo antes do
 *  termo. */
function eventosDoCiclo(pleitos: Pleito[], aditivos: AditivoDoCiclo[], termos: InstrumentoCadastro[]) {
  const ev = [
    ...pleitos.filter(p => p.situacao === "enviado" && p.enviado_em).map(p => ({ data: p.enviado_em!.slice(0, 10), ordem: 0,
      // "Pleito ... enviado"; reiteracao e reemissao (femininas) "enviada"
      texto: `${p.rotulo}${p.numero_oficio ? ` ${p.numero_oficio}` : ""} ${p.reemissao || p.reemite_pleito_id ? "enviada" : "enviado"}` })),
    ...aditivos.map(a => ({ data: a.data_assinatura.slice(0, 10), ordem: 1,
      texto: ["Aditivo", TIPO_ADITIVO[a.tipo], a.numero ?? "sem número", "assinado"].filter(Boolean).join(" ") })),
    ...termos.map(i => ({ data: i.data.slice(0, 10), ordem: 2, texto: `${nomeDoTermo(i)} ${i.numero ?? "s/n"}` })),
  ];
  return ev.sort((a, b) => a.data.localeCompare(b.data) || a.ordem - b.ordem);
}

function LinhaDoTempoDoCiclo({ id, ciclo, eventos }: { id: string; ciclo: number;
    eventos: { data: string; texto: string }[] }) {
  return (
    <div className="cartao__corpo">
      <p className="resumo__rotulo" id={id}>Linha do tempo</p>
      <ol className="linha-tempo" aria-label={`Linha do tempo do ciclo de ${ciclo}`}>
        {eventos.map((e, i) => (
          <li key={i}><time className="linha-tempo__data" dateTime={e.data}>{fmtDataPura(e.data)}</time><span>{e.texto}</span></li>
        ))}
      </ol>
    </div>
  );
}

// Pleito nao enviado e' a vez da engenharia: nivel "Acao" do D2 (ambar com contorno cheio), o
// mesmo com que o fato aparece nos avisos. Vermelho fica para o critico.
const SITUACAO: Record<Ciclo["situacao"], { rotulo: string; classe: string; forte?: boolean }> = {
  futuro: { rotulo: "ainda não abriu", classe: "" },
  pleito_pendente: { rotulo: "pleito não enviado", classe: "selo--atencao", forte: true },
  apostilamento_pendente: { rotulo: "apostilamento pendente", classe: "selo--atencao" },
  // issue #273: aditivo de prazo ou valor assinado depois do ultimo pleito enviado; a vez e' da engenharia
  reemitir: { rotulo: "cronograma de reajuste a reemitir", classe: "selo--atencao", forte: true },
  apostilado: { rotulo: "apostilado", classe: "selo--ok" },
};

// espaco nao separavel: "3 dias" nao quebra no meio do selo
function dias(n: number): string {
  return `${n}\u00a0${n === 1 ? "dia" : "dias"}`;
}

/** A linha do ciclo: o ano e o aniversario (quanto falta ou quanto passou nao se escreve; o atraso esta' no selo). */
function linhaDoCiclo(c: Ciclo): string {
  return `Ciclo de ${c.ciclo} · aniversário em ${fmtDataPura(c.aniversario)}`;
}

/** O apostilamento: numero, data e o percentual concedido (o cadastro guarda "3,80"; issue #275: era NaN%). */
function textoApostilamento(i: InstrumentoCadastro): string {
  const pct = i.dados.percentual;
  return [`${i.numero ?? "s/n"}, de ${fmtDataPura(i.data)}`,
          typeof pct === "string" || typeof pct === "number" ? (String(pct).trim() ? percentual(pct) : "") : ""]
    .filter(Boolean).join(" · ");
}

/** O termo que fecha o ciclo: apostilamento ou, na SES, termo aditivo de valor de reajuste (issue #390). */
function nomeDoTermo(i: InstrumentoCadastro): string {
  return i.tipo.startsWith("aditivo") ? "Termo aditivo" : "Apostilamento";
}

/** O desfecho de um pleito enviado (F-71): com o ciclo corrente, o selo diz se o apostilamento veio (Em dia) ou
 *  se falta (Atencao, com os dias que o servidor conta); embaixo, so' a data do envio. Sem o ciclo (ciclo
 *  anterior, data-base que saiu do cadastro), o dado nao diz o desfecho: selo neutro. */
function desfechoDoPleito(p: Pleito, apostilamentos: InstrumentoCadastro[], c?: Ciclo): DesfechoPleito {
  const envio = partesDoEnvio(p);
  const neutro = { classe: "", texto: p.situacao, partes: envio };
  // o cadastro ligou o pleito ao termo que o atendeu (issue #271): vale em qualquer ciclo, corrente ou passado
  // (na SES, o termo aditivo de valor de reajuste, issue #390: `apostilamentos` traz tambem os aditivos)
  const termo = p.situacao === "enviado" && p.instrumento_chave
    ? apostilamentos.find(i => i.chave === p.instrumento_chave) : undefined;
  if (termo) return { classe: "selo--ok", texto: `atendido pelo ${nomeDoTermo(termo).toLowerCase()} ${termo.numero ?? "s/n"}`, partes: envio };
  // so' o pleito vigente do ciclo (o enviado mais recente) leva o desfecho; os anteriores (reiterados ou
  // reemitidos) ficam com o envio e a cadeia, sem repetir a espera do ciclo (issue #277)
  if (!c || p.situacao !== "enviado" || (c.pleito && c.pleito.id !== p.id)) return neutro;
  if (c.situacao === "apostilamento_pendente" || c.situacao === "reemitir") {
    return { classe: "selo--atencao", partes: envio,
      texto: c.dias !== null && c.dias >= 0 ? `sem apostilamento há ${dias(c.dias)}` : "sem apostilamento ainda" };
  }
  // atendido so' pelo termo ligado ao pleito (acima): sem a ligacao, o ciclo apostilado nao diz que foi este
  // pleito que o termo atendeu (gate Sol, PR #317)
  return neutro;
}

// pleito que ainda se trabalha: feito no sistema, nem enviado nem descartado (o mesmo corte do CartaoPleito)
const emAberto = (p: Pleito) => p.origem === "sistema" && p.situacao !== "enviado" && p.situacao !== "descartado";

export default function Reajuste({ contratoId, podeEditar }: { contratoId: number; podeEditar: boolean }) {
  const [dados, setDados] = useState<{ ciclos: Ciclo[]; pleitos: Pleito[]; competencias?: CompetenciaApostilada[];
    bases_dos_termos?: BaseDoTermo[]; aditivos_de_reajuste?: InstrumentoCadastro[];
    competencias_por_ciclo?: GrupoDoCiclo[] } | null>(null);
  const [apostilamentos, setApostilamentos] = useState<InstrumentoCadastro[]>([]);
  const [erro, setErro] = useState("");
  const [novo, setNovo] = useState<string | null>(null);            // data-base do pleito sendo criado
  // reiteracao ou reemissao sendo criada: a data-base, o pleito anterior e o que se faz com ele
  const [reemitir, setReemitir] = useState<{ dataBase: string; anterior: Pleito; reemissao: Reemissao } | null>(null);
  // para onde o foco vai quando o formulario fecha: o botao que o abriu (cancelar) ou o pleito criado
  const [foco, setFoco] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      setDados(await api(`/api/contratos/${contratoId}/reajuste`));
      const cad = await api<{ instrumentos: InstrumentoCadastro[] }>(`/api/contratos/${contratoId}/cadastro`);
      setApostilamentos(cad.instrumentos.filter(i => i.tipo === "apostilamento_reajuste"));
    } catch (e) { setErro(mensagemDeErro(e)); }
  }, [contratoId]);
  useEffect(() => { void carregar(); }, [carregar]);
  // o pleito criado so' existe depois que a lista recarrega: tenta de novo a cada leitura
  useEffect(() => { if (foco && focarPorId(foco)) setFoco(null); }, [foco, dados]);

  if (erro) return <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />{erro}</p>;
  if (!dados) return <section className="cartao"><div className="vazio"><p>Carregando…</p></div></section>;
  const grupos = dados.competencias_por_ciclo ?? [];
  if (dados.ciclos.length === 0 && dados.pleitos.length === 0 && apostilamentos.length === 0 && grupos.length === 0) {
    return <section className="cartao"><div className="vazio vazio--curto"><p>Nenhuma data-base.</p></div></section>;
  }
  const { dataBases, semDataBase, outrosPleitos } = reajustePorDataBase(dados.ciclos, dados.pleitos, apostilamentos,
    dados.bases_dos_termos);
  // o corrigido por outro nao vale e sai da aba (segue em Contrato > Instrumentos), seja qual for a data-base da
  // correcao (PR #317)
  const corrigidos = termosCorrigidos(apostilamentos);
  const vale = (i: InstrumentoCadastro) => !i.chave || !corrigidos.has(i.chave);
  const semBase = semDataBase.filter(vale);
  const aqui = { tela: "obra" as const, id: contratoId, aba: "reajuste" as const };
  // o pleito ligado ao termo aditivo de reajuste (issue #390) diz o termo em qualquer ciclo; a API ja' manda so' os
  // aditivos que valem como termo (o mesmo criterio do ciclo)
  const termos = [...apostilamentos, ...(dados.aditivos_de_reajuste ?? [])];
  // o nome do termo de cada competencia apostilada (issue #275): o cadastro, e a lista das apostiladas para o termo
  // que o cadastro ja' nao traz
  const nomesDosTermos = new Map<string, NomeDoTermo>([
    ...(dados.competencias ?? []).map(x => [x.instrumento_chave, { numero: x.instrumento_numero, data: x.instrumento_data }] as const),
    ...apostilamentos.filter(i => i.chave).map(i => [i.chave!, { numero: i.numero, data: i.data }] as const)]);
  // a tabela de um grupo (data-base e ciclo) de `competencias_por_ciclo`
  const tabela = (g: GrupoDoCiclo) => (
    <TabelaCompetencias key={`${g.data_base_mes}-${g.ciclo}`} rotulo={rotuloDoGrupo(g)} linhas={g.competencias}
      termos={nomesDosTermos} />
  );
  // grupo sem data-base (medicao de base incerta) ou de data-base que o cadastro nao tem mais: cartao proprio no fim
  const conhecidas = new Set(dataBases.map(db => db.data_base_mes));
  const gruposFora = grupos.filter(g => g.data_base_mes === null || !conhecidas.has(g.data_base_mes));
  // cada pleito e' uma secao do cartao pai (F-74): o enviado vira linha com o desfecho no selo; o que ainda se
  // trabalha segue no CartaoPleito, que traz o formulario
  const cartoes = (ps: Pleito[], ciclo?: Ciclo) => ps.map(p => {
    const contexto = p.ciclo ? `ciclo de ${p.ciclo}` : undefined;
    return pleitoEmLinha(p)
      ? <LinhaPleito key={p.id} p={p} desfecho={desfechoDoPleito(p, termos, ciclo)} contexto={contexto} />
      : <CartaoPleito key={p.id} p={p} podeEditar={podeEditar} aoMudar={() => void carregar()} contexto={contexto} />;
  });

  return (
    <div className="pilha">
      {/* com mais de uma data-base, o indice leva a cada uma sem rolar a aba inteira */}
      {dataBases.length > 1 ? (
        <section className="cartao" aria-labelledby="titulo-databases">
          <div className="cartao__cabeca">
            <h2 className="cartao__titulo" id="titulo-databases">Data-bases</h2>
          </div>
          <ul className="lista-simples cartao__corpo indice-db">
            {dataBases.map(db => {
              const s = SITUACAO[db.atual.situacao] ?? { rotulo: db.atual.situacao, classe: "" };
              return (
                <li key={db.data_base_mes}>
                  <Link para={aqui} secao={`db-${db.data_base_mes}`}>{rotuloDataBase(db.data_base_mes, db.atual)}</Link>
                  <Selo classe={s.classe} forte={s.forte}>{s.rotulo}</Selo>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {dataBases.map(db => {
        const c = db.atual;
        const s = SITUACAO[c.situacao] ?? { rotulo: c.situacao, classe: "" };
        const titulo = `titulo-db-${db.data_base_mes}`;
        // termos que valem, separados pelo ciclo deles (PR #317): os do ciclo corrente ficam no cartao, mesmo sem
        // pleito ligado
        const validos = db.apostilamentos.filter(vale);
        const doCiclo = [...(c.apostilamento ? [c.apostilamento] : []),
          // o aditivo (issue #390) vem de outra tabela: o id so' identifica junto com o tipo
          ...validos.filter(i => !(i.id === c.apostilamento?.id && i.tipo === c.apostilamento.tipo)
            && cicloDoApostilamento(i) === c.ciclo)];
        const outrosAp = validos.filter(i => !doCiclo.some(d => d.id === i.id && d.tipo === i.tipo));
        // issue #275: a tabela por competencia do ciclo corrente fica no cartao; a dos ciclos passados, recolhida com
        // eles; a de ciclo posterior (previsao lancada antes da janela abrir), logo abaixo da corrente
        const daBase = grupos.filter(g => g.data_base_mes === db.data_base_mes);
        const doCicloAtual = daBase.find(g => g.ciclo === c.ciclo);
        const gruposAnteriores = daBase.filter(g => g.ciclo !== null && g.ciclo < c.ciclo);
        const gruposSeguintes = daBase.filter(g => g.ciclo !== null && g.ciclo > c.ciclo);
        const eventos = eventosDoCiclo(db.pleitosDoCiclo, c.aditivos ?? [], doCiclo);
        const anteriores = db.pleitosAnteriores.length + outrosAp.length + gruposAnteriores.length;
        const aberto = db.pleitosDoCiclo.find(emAberto);
        // o pleito vigente do ciclo e o que o servidor deixa fazer com ele (reiterar, reemitir o cronograma)
        const vigente = c.pleito ? dados.pleitos.find(p => p.id === c.pleito!.id) : undefined;
        const possiveis = vigente?.reemissoes_possiveis ?? [];
        const reemitindo = reemitir?.dataBase === db.data_base_mes ? reemitir : null;
        const formAberto = novo === db.data_base_mes || reemitindo !== null;
        return (
          // o cartao e' a data-base: o ciclo, e embaixo, como secoes, os oficios dele e os ciclos anteriores; o
          // aviso de reajuste cai na ancora dele
          <section className="cartao" id={`db-${db.data_base_mes}`} key={db.data_base_mes} aria-labelledby={titulo}>
            <div className="cartao__cabeca">
              <h2 className="cartao__titulo" id={titulo}>Data-base {rotuloDataBase(db.data_base_mes, c)}</h2>
              <Selo classe={s.classe} forte={s.forte}>{s.rotulo}</Selo>
              {/* com um pleito em aberto no ciclo, o caminho e' continuar nele, nao abrir outro oficio */}
              {podeEditar && aberto && (
                <div className="cartao__acoes">
                  <Link className="btn btn--pequeno" para={aqui} secao={`oficio-${aberto.id}`}>
                    Continuar o pleito{aberto.numero_oficio ? ` ${aberto.numero_oficio}` : ""}
                  </Link>
                </div>
              )}
              {podeEditar && !aberto && c.situacao === "pleito_pendente" && !formAberto && (
                <div className="cartao__acoes">
                  <button type="button" className="btn btn--pequeno" id={`enviar-pleito-${db.data_base_mes}`} onClick={() => setNovo(db.data_base_mes)}>
                    Enviar pleito
                  </button>
                </div>
              )}
              {/* depois do envio, o oficio novo nasce ligado ao vigente: reiteracao (MT-PAR e Prefeitura) ou
                  reemissao do cronograma (apos aditivo); issue #277 */}
              {podeEditar && !aberto && vigente && possiveis.length > 0 && c.situacao !== "futuro" && !formAberto && (
                <div className="cartao__acoes">
                  {possiveis.map(r => (
                    <button key={r} type="button" className="btn btn--pequeno" id={`reemitir-${r}-${db.data_base_mes}`}
                      onClick={() => setReemitir({ dataBase: db.data_base_mes, anterior: vigente, reemissao: r })}>
                      {ACAO_REEMISSAO[r].botao}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="cartao__corpo linhas">
              <p className="num">{linhaDoCiclo(c)}</p>
              {doCiclo.map(i => (
                <p key={`${i.tipo}-${i.id}`}><span className="resumo__rotulo">{nomeDoTermo(i)}</span>{" "}{textoApostilamento(i)}</p>
              ))}
            </div>
            {doCicloAtual && tabela(doCicloAtual)}
            {gruposSeguintes.map(g => (
              <div className="cartao__corpo" key={`${g.data_base_mes}-${g.ciclo}`}>
                <p className="resumo__rotulo">Ciclo de {g.ciclo}</p>
                {tabela(g)}
              </div>
            ))}
            {eventos.length > 0 && <LinhaDoTempoDoCiclo id={`tempo-${db.data_base_mes}`} ciclo={c.ciclo} eventos={eventos} />}
            {(formAberto || db.pleitosDoCiclo.length > 0 || anteriores > 0) && (
              <div className="secoes-pleito">
                {reemitindo && (
                  <section className="cartao" aria-labelledby={`titulo-reemitir-${db.data_base_mes}`}>
                    <div className="cartao__cabeca">
                      <h3 className="cartao__titulo" id={`titulo-reemitir-${db.data_base_mes}`}>
                        {ACAO_REEMISSAO[reemitindo.reemissao].titulo} {reemitindo.anterior.numero_oficio ?? "sem número"}
                      </h3>
                    </div>
                    <NovoPleito contratoId={contratoId} tipo="reajuste" dataBase={db.data_base_mes}
                      reemite={{ id: reemitindo.anterior.id, reemissao: reemitindo.reemissao }}
                      aoCriar={p => { setReemitir(null); setFoco(`oficio-${p.id}`); void carregar(); }}
                      aoCancelar={() => { setReemitir(null); setFoco(`reemitir-${reemitindo.reemissao}-${db.data_base_mes}`); }} />
                  </section>
                )}
                {novo === db.data_base_mes && (
                  <section className="cartao" aria-labelledby={`titulo-novo-${db.data_base_mes}`}>
                    <div className="cartao__cabeca">
                      <h3 className="cartao__titulo" id={`titulo-novo-${db.data_base_mes}`}>Novo pleito da data-base {mesAno(db.data_base_mes)}</h3>
                    </div>
                    <NovoPleito contratoId={contratoId} tipo="reajuste" dataBase={db.data_base_mes}
                      aoCriar={p => { setNovo(null); setFoco(`oficio-${p.id}`); void carregar(); }}
                      aoCancelar={() => { setNovo(null); setFoco(`enviar-pleito-${db.data_base_mes}`); }} />
                  </section>
                )}
                {cartoes(db.pleitosDoCiclo, c)}
                {anteriores > 0 && (
                  <details className="detalhes pleito-anteriores">
                    <summary>Ciclos anteriores</summary>
                    <div className="secoes-pleito">
                      {outrosAp.length > 0 && (
                        <section className="cartao__corpo" aria-label={`Apostilamentos anteriores da data-base ${mesAno(db.data_base_mes)}`}>
                          <ul className="lista-simples">{outrosAp.map(i => <li key={i.id} className="num">{textoApostilamento(i)}</li>)}</ul>
                        </section>
                      )}
                      {gruposAnteriores.map(g => (
                        <div className="cartao__corpo" key={`${g.data_base_mes}-${g.ciclo}`}>
                          <p className="resumo__rotulo">Ciclo de {g.ciclo}</p>
                          {tabela(g)}
                        </div>
                      ))}
                      {cartoes(db.pleitosAnteriores)}
                    </div>
                  </details>
                )}
              </div>
            )}
          </section>
        );
      })}

      {semBase.length > 0 && (
        <section className="cartao" aria-labelledby="titulo-apostilamentos-sem-base">
          <div className="cartao__cabeca">
            <h2 className="cartao__titulo" id="titulo-apostilamentos-sem-base">Apostilamentos sem data-base no cadastro</h2>
          </div>
          <ul className="lista-simples cartao__corpo">{semBase.map(i => <li key={i.id} className="num">{textoApostilamento(i)}</li>)}</ul>
        </section>
      )}

      {outrosPleitos.length > 0 && (
        <section className="cartao" aria-labelledby="titulo-outros-pleitos">
          <div className="cartao__cabeca">
            <h2 className="cartao__titulo" id="titulo-outros-pleitos">Pleitos de data-base que o cadastro não tem mais</h2>
          </div>
          <div className="secoes-pleito">{cartoes(outrosPleitos)}</div>
        </section>
      )}

      {/* issue #275: nada some em silencio; medicao de data-base incerta entra uma vez so', aqui */}
      {gruposFora.length > 0 && (
        <section className="cartao" aria-labelledby="titulo-competencias-fora">
          <div className="cartao__cabeca">
            <h2 className="cartao__titulo" id="titulo-competencias-fora">Reajuste fora das datas-base do cadastro</h2>
          </div>
          {gruposFora.map(tabela)}
        </section>
      )}
    </div>
  );
}
