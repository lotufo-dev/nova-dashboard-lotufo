import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import CaixaAviso from "./CaixaAviso";
import Contador from "./Contador";
import { brl, contar } from "./formato";
import { IconeBaixar } from "./icones";
import { Link } from "./Link";
import { mesPorExtenso, somarMes } from "./resumoMedicoes";
import Rolagem from "./Rolagem";
import { trocarBusca, type Busca, type Ir } from "./rota";
import Selo, { Glifo } from "./Selo";
import { fmtCompetencia, fmtDataCurta, fmtDataHora, fmtDataPura } from "./tempo";
import "./resumoDasMedicoes.css";

// Resumo das medicoes (#749): em que etapa do ciclo (em analise, boletim, nota, protocolado, recebido) esta' a medicao
// de cada obra na competencia em trabalho, quais obras nao tem medicao nela e o que ficou aberto de meses anteriores.
// So' leitura: tudo vem pronto de GET /api/resumo-medicoes (`app/resumo_medicoes.py`); a tela nao calcula etapa, nao
// soma nem estima data. A obra so' tem as etapas do fluxo dela, e cada etapa alcancada leva a data que o sistema
// registrou. A etapa que ficou para tras sem o registro do evento (a medicao pulou a etapa, ou veio do historico) nao
// leva visto nem data: a pagina so' afirma o que tem registro.
//
// A fundacao nao tinha a faixa das etapas de uma linha: aqui ela e' uma coluna por etapa, com a data de cada uma
// (decisao do dono de 17/11/2026).

type Etapa = "em_analise" | "boletim" | "nota" | "protocolado" | "recebido";
/** `antes`: a planilha/carta foi gerada e ainda nao foi enviada ao orgao (a medicao existe, o ciclo nao comecou). */
type EtapaDaVez = Etapa | "antes";
/** `sem_registro`: a etapa ficou para tras e o sistema nao tem o registro do evento dela. */
type EtapaDaLinha = { etapa: Etapa; situacao: "feito" | "sem_registro" | "atual" | "futuro"; data: string | null };
type Linha = {
  contrato_id: number; obra: string; contratante: string | null; medicao_id: number; medicao_ids: number[]; titulo: string;
  numero: number; tipo: string; competencia: string; etapa: EtapaDaVez; etapas: EtapaDaLinha[]; valor_centavos: number | null;
};
type SemMedicao = {
  contrato_id: number; obra: string; contratante: string | null;
  ultima: { medicao_id: number; titulo: string; competencia: string; etapa: EtapaDaVez } | null;
};
export type RespostaResumo = {
  hoje: string; mes: string; em_trabalho: string;
  atualizacao: { ultimo_lancamento: string | null; rm_lido_em: string | null };
  etapas: { etapa: EtapaDaVez; medicoes: number; valor_centavos: number }[];
  grupos: { contratante: string; linhas: Linha[] }[];
  sem_medicao: SemMedicao[];
  anteriores: { competencia: string; linhas: Linha[] }[];
};
type Grupo = { chave: string; titulo: string; linhas: Linha[] };

const ETAPAS: { chave: Etapa; rotulo: string }[] = [
  { chave: "em_analise", rotulo: "Em análise" }, { chave: "boletim", rotulo: "Boletim" }, { chave: "nota", rotulo: "Nota" },
  { chave: "protocolado", rotulo: "Protocolado" }, { chave: "recebido", rotulo: "Recebido" },
];
const ANTES = "Planilha/carta a enviar";
const ROTULO = { antes: ANTES, ...Object.fromEntries(ETAPAS.map(e => [e.chave, e.rotulo])) } as Record<EtapaDaVez, string>;
const MES = /^[0-9]{4}-(0[1-9]|1[0-2])$/;

const maiuscula = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
/** Sem valor ou zero nao e' numero a ler: "—". */
const valor = (c: number | null) => (c === null || c === 0 ? "—" : brl(c));
const quantas = (linhas: Linha[]) => linhas.reduce((n, l) => n + l.medicao_ids.length, 0);

/* ------------------------------------------------------------------ faixa das etapas (o mes inteiro) */

/** Quantas medicoes da competencia estao em cada etapa, com o medido delas na cota (nao e' o bruto das notas, que e'
 *  o protocolado e o recebido do Fechamento: a frase do alto e o nome da lista dizem a base), e quantas obras estao
 *  sem medicao. A cor de cada etapa e' a da fundacao (--etapa-*), a mesma das linhas abaixo; o rotulo esta' sempre
 *  escrito. */
function FaixaDasEtapas({ d }: { d: RespostaResumo }) {
  const de = new Map(d.etapas.map(e => [e.etapa, e]));
  const item = (chave: EtapaDaVez, rotulo: string) => {
    const e = de.get(chave);
    const n = e?.medicoes ?? 0;
    return (
      <li key={chave} className={`rdm-faixa__item rdm-cor--${chave === "antes" ? "vazia" : chave}`}>
        <span className="rdm-faixa__rotulo">{rotulo}</span>
        {n === 0 ? <span className="rdm-faixa__qtd">—</span> : <>
          <span className="rdm-faixa__qtd"><span className="rdm-faixa__numero">{n}</span> {n === 1 ? "medição" : "medições"}</span>
          <span className="rdm-faixa__valor">{valor(e?.valor_centavos ?? null)}</span>
        </>}
      </li>
    );
  };
  const sem = d.sem_medicao.length;
  return (
    <ol className="rdm-faixa" aria-label={`Medições de ${mesPorExtenso(d.mes)} por etapa, com o medido na cota da Lotufo`}>
      {(de.get("antes")?.medicoes ?? 0) > 0 && item("antes", ANTES)}
      {ETAPAS.map(e => item(e.chave, e.rotulo))}
      <li className="rdm-faixa__item rdm-faixa__item--sem">
        <span className="rdm-faixa__rotulo">Sem medição</span>
        <span className="rdm-faixa__qtd">{sem === 0 ? "—" : <><span className="rdm-faixa__numero">{sem}</span> {sem === 1 ? "obra" : "obras"}</>}</span>
      </li>
    </ol>
  );
}

/* ------------------------------------------------------------------ a linha de uma medicao */

/** A obra e a medicao, cada uma com o link dela. A obra repetida na linha seguinte (execucao e reajuste em etapas
 *  diferentes) nao se escreve de novo na tabela larga; no celular cada bloco traz o nome. */
function Primeira({ l, repetida, ir, children }: { l: Linha; repetida: boolean; ir: Ir; children?: React.ReactNode }) {
  return (
    <th scope="row" className="rdm-primeira">
      {repetida ? <span className="rdm-obra rdm-obra--repetida">{l.obra}</span>
        : <Link className="rdm-obra" para={{ tela: "obra", id: l.contrato_id, aba: "medicoes" }} ir={ir}>{l.obra}</Link>}
      <Link className="link rdm-medicao" para={{ tela: "medicao", obra: l.contrato_id, id: l.medicao_id }} ir={ir}>{l.titulo}</Link>
      {children}
    </th>
  );
}

/** A etapa foi alcancada e o sistema nao tem a data do evento: o traco, nunca uma data estimada. */
function SemData() {
  return <><span aria-hidden="true">—</span><span className="sr-only">sem data registrada</span></>;
}

/** Uma celula por etapa. A barra de cima e' a faixa da linha (cheia na cor da etapa alcancada, tracejada e neutra na
 *  que ficou para tras sem registro, vazia na que falta, sem barra na etapa que a obra nao tem); embaixo, so' na etapa
 *  alcancada com registro, a situacao com a forma dela e a data registrada. */
function CelulaEtapa({ etapa, l }: { etapa: { chave: Etapa; rotulo: string }; l: Linha }) {
  const x = l.etapas.find(e => e.etapa === etapa.chave);
  if (!x) return <td className="rdm-etapa rdm-etapa--fora"><span className="sr-only">a obra não tem esta etapa</span></td>;
  if (x.situacao === "futuro") {
    return <td className="rdm-etapa rdm-etapa--futuro rdm-cor--vazia"><span className="sr-only">ainda não</span></td>;
  }
  if (x.situacao === "sem_registro") {
    return <td className="rdm-etapa rdm-etapa--sem-registro"><span className="sr-only">sem registro</span></td>;
  }
  const atual = x.situacao === "atual";
  return (
    <td className={`rdm-etapa rdm-etapa--${x.situacao} rdm-cor--${etapa.chave}`} aria-current={atual ? "step" : undefined}>
      <span className="rdm-etapa__nome">{etapa.rotulo}</span>
      <span className="rdm-etapa__dado">
        <Glifo situacao={atual ? "andamento" : "feito"} />
        <span className="sr-only">{atual ? "Etapa atual, desde " : "Feito em "}</span>
        {x.data ? <span title={fmtDataPura(x.data)}>{fmtDataCurta(x.data)}</span> : <SemData />}
      </span>
    </td>
  );
}

function TabelaDeLinhas({ grupos, rotulo, legenda, ir }: { grupos: Grupo[]; rotulo: string; legenda: string; ir: Ir }) {
  return (
    <Rolagem rotulo={rotulo} className="tabela-wrap rdm-rolagem">
      <table className="tabela rdm-tabela rdm-tabela--etapas">
        <caption className="sr-only">{legenda}</caption>
        <thead>
          <tr>
            <th scope="col" className="rdm-primeira">Obra</th>
            {ETAPAS.map(e => <th key={e.chave} scope="col" className="rdm-th-etapa">{e.rotulo}</th>)}
            <th scope="col" className="col-num">Medido</th>
          </tr>
        </thead>
        {grupos.map(g => (
          <tbody key={g.chave}>
            <tr className="rdm-grupo"><th scope="rowgroup" colSpan={ETAPAS.length + 2}>{g.titulo}</th></tr>
            {g.linhas.map((l, i) => (
              <tr key={l.medicao_id} className="rdm-linha">
                <Primeira l={l} repetida={i > 0 && g.linhas[i - 1].contrato_id === l.contrato_id} ir={ir}>
                  {l.etapa === "antes" && <Selo className="rdm-antes">{ANTES}</Selo>}
                </Primeira>
                {ETAPAS.map(e => <CelulaEtapa key={e.chave} etapa={e} l={l} />)}
                <td className="col-num dinheiro num rdm-valor" data-rotulo="Medido">{valor(l.valor_centavos)}</td>
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </Rolagem>
  );
}

/* ------------------------------------------------------------------ obras sem medicao no mes */

function SemMedicaoNoMes({ d, ir }: { d: RespostaResumo; ir: Ir }) {
  const n = d.sem_medicao.length;
  return (
    <section className="cartao rdm-painel" aria-labelledby="rdm-sem">
      <div className="rdm-painel__cab">
        <h2 id="rdm-sem">Sem medição em {mesPorExtenso(d.mes)}</h2>
        {n > 0 && <Contador rotulo={contar(n, "obra", "obras")}>{n}</Contador>}
      </div>
      {n === 0 ? <p className="rdm-vazio">Nenhuma obra sem medição.</p> : (
        <Rolagem rotulo={`Obras sem medição em ${mesPorExtenso(d.mes)}`} className="tabela-wrap rdm-rolagem">
          <table className="tabela rdm-tabela rdm-tabela--sem">
            <caption className="sr-only">Obras ativas sem medição em {mesPorExtenso(d.mes)}, com a última medição de cada uma</caption>
            <thead>
              <tr><th scope="col" className="rdm-primeira">Obra</th><th scope="col">Órgão</th><th scope="col">Última medição</th><th scope="col">Etapa dela</th></tr>
            </thead>
            <tbody>
              {d.sem_medicao.map(o => (
                <tr key={o.contrato_id} className="rdm-linha">
                  <th scope="row" className="rdm-primeira">
                    <Link className="rdm-obra" para={{ tela: "obra", id: o.contrato_id, aba: "medicoes" }} ir={ir}>{o.obra}</Link>
                  </th>
                  <td data-rotulo="Órgão">{o.contratante ?? "—"}</td>
                  <td data-rotulo="Última medição">
                    {o.ultima ? <>
                      <Link className="link" para={{ tela: "medicao", obra: o.contrato_id, id: o.ultima.medicao_id }} ir={ir}>{o.ultima.titulo}</Link>
                      <span className="rdm-sub num">{fmtCompetencia(o.ultima.competencia)}</span>
                    </> : "—"}
                  </td>
                  <td data-rotulo="Etapa dela">
                    {o.ultima ? <span className="rdm-chave-etapa">
                      <span className={`rdm-chave rdm-cor--${o.ultima.etapa === "antes" ? "vazia" : o.ultima.etapa}`} aria-hidden="true" />
                      {ROTULO[o.ultima.etapa]}
                    </span> : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Rolagem>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ pagina */

/** A base dos valores, dita uma vez (o valor de cada etapa e' o medido das medicoes que estao nela, na cota), e de
 *  quando e' o dado: o ultimo lancamento de uma pessoa numa medicao e a ultima leitura do RM. */
function Atualizacao({ a }: { a: RespostaResumo["atualizacao"] }) {
  const lancamento = a.ultimo_lancamento ? `Último lançamento em ${fmtDataHora(a.ultimo_lancamento)}` : "Nenhum lançamento registrado";
  const rm = a.rm_lido_em ? `; recebimentos lidos do RM em ${fmtDataHora(a.rm_lido_em)}` : "";
  return <p className="rdm-base">Medido das medições de cada etapa, na cota da Lotufo. {lancamento}{rm}.</p>;
}

export default function ResumoDasMedicoes({ ir, busca = {} }: { ir: Ir; busca?: Busca }) {
  const [d, setD] = useState<RespostaResumo | null>(null);
  const [erro, setErro] = useState("");
  // a competencia pedida; sem ela, o servidor responde a competencia em trabalho (o mes anterior ao de hoje)
  const [mes, setMes] = useState<string | null>(() => (busca.mes && MES.test(busca.mes) ? busca.mes : null));

  useEffect(() => {
    let vivo = true;
    api<RespostaResumo>(`/api/resumo-medicoes${mes ? `?mes=${mes}` : ""}`)
      .then(r => { if (vivo) { setD(r); setErro(""); } })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, [mes]);

  if (!d) {
    return erro
      ? <CaixaAviso nivel="critico" role="alert">Não foi possível carregar o resumo das medições: {erro} Recarregue a página para tentar de novo.</CaixaAviso>
      : <p className="rdm-vazio rdm-vazio--pagina">Carregando…</p>;
  }
  // a competencia fica na URL (F5 e o link copiado abrem o mesmo mes); a em trabalho e' a padrao e nao entra nela
  const irPara = (novo: string) => {
    const pedido = novo === d.em_trabalho ? null : novo;
    setMes(pedido);
    trocarBusca({ mes: pedido });
  };
  const emTrabalho = d.mes === d.em_trabalho;
  const carregando = (mes ?? d.em_trabalho) !== d.mes;
  const doMes: Grupo[] = d.grupos.map(g => ({ chave: g.contratante, titulo: g.contratante, linhas: g.linhas }));
  const anteriores: Grupo[] = d.anteriores.map(g => ({ chave: g.competencia, titulo: maiuscula(mesPorExtenso(g.competencia)), linhas: g.linhas }));
  const nMes = quantas(doMes.flatMap(g => g.linhas)), nAnt = quantas(anteriores.flatMap(g => g.linhas));
  const nomeMes = mesPorExtenso(d.mes);

  return (
    <div className="rdm" aria-busy={carregando || undefined}>
      <div className="rdm-cab">
        <div className="rdm-cab__mes">
          <p className="rdm-cab__rotulo">{emTrabalho ? "Competência em trabalho" : "Competência"}</p>
          <div className="rdm-cab__troca">
            <h2 aria-live="polite">{maiuscula(nomeMes)}</h2>
            <div className="rdm-botoes" role="group" aria-label="Trocar a competência">
              <button type="button" className="btn btn--pequeno" aria-label="Mês anterior" onClick={() => irPara(somarMes(d.mes, -1))}>‹</button>
              <button type="button" className="btn btn--pequeno" aria-label="Mês seguinte" onClick={() => irPara(somarMes(d.mes, 1))}>›</button>
              {!emTrabalho && <button type="button" className="btn btn--pequeno" onClick={() => irPara(d.em_trabalho)}>Voltar à competência em trabalho</button>}
            </div>
          </div>
        </div>
        <a className="btn btn--pequeno" href={`/api/resumo-medicoes.csv?mes=${d.mes}`}>
          <IconeBaixar className="icone icone--p" /> Exportar CSV
        </a>
      </div>
      <Atualizacao a={d.atualizacao} />
      {erro && <CaixaAviso nivel="critico" role="alert" className="rdm-aviso">Não foi possível carregar {mes ? mesPorExtenso(mes) : "a competência"}: {erro}</CaixaAviso>}
      <FaixaDasEtapas d={d} />

      <section className="cartao rdm-painel" aria-labelledby="rdm-obras">
        <div className="rdm-painel__cab">
          <h2 id="rdm-obras">Por obra</h2>
          {nMes > 0 && <Contador rotulo={contar(nMes, "medição", "medições")}>{nMes}</Contador>}
        </div>
        {doMes.length === 0 ? <p className="rdm-vazio">Nenhuma medição em {nomeMes}.</p>
          : <TabelaDeLinhas grupos={doMes} ir={ir} rotulo={`Medições de ${nomeMes} por obra`}
              legenda={`Etapa da medição de cada obra em ${nomeMes}, por órgão, com a data registrada de cada etapa e o medido na cota da Lotufo`} />}
      </section>

      <SemMedicaoNoMes d={d} ir={ir} />

      <section className="cartao rdm-painel" aria-labelledby="rdm-anteriores">
        <div className="rdm-painel__cab">
          <h2 id="rdm-anteriores">Meses anteriores em aberto</h2>
          {nAnt > 0 && <Contador rotulo={contar(nAnt, "medição", "medições")}>{nAnt}</Contador>}
        </div>
        {anteriores.length === 0 ? <p className="rdm-vazio">Nenhuma medição aberta de meses anteriores.</p>
          : <TabelaDeLinhas grupos={anteriores} ir={ir} rotulo="Medições abertas de meses anteriores"
              legenda={`Medições de competências anteriores a ${nomeMes} ainda não recebidas, por competência, com a etapa de cada uma e o medido na cota da Lotufo`} />}
      </section>
    </div>
  );
}
