import { useEffect, useState } from "react";
import { api, mensagemDeErro } from "./api";
import Contador from "./Contador";
import Falha from "./Falha";
import { brl, contar } from "./formato";
import { IconeBaixar } from "./icones";
import { Link } from "./Link";
import MarcaEtapa from "./MarcaEtapa";
import {
  ANTES, ETAPAS, linhasDaEtapa, maiuscula, mesDaUltima, nomeDaMesmaAltura, nomeDaReferencia,
  type ContagemDaEtapa, type Grupo, type Referencia, type RespostaResumo,
} from "./resumoEtapas";
import { mesPorExtenso, somarMes } from "./resumoMedicoes";
import ResumoQuadro from "./ResumoQuadro";
import ResumoTabela from "./ResumoTabela";
import { trocarBusca, type Busca, type Ir, type Rota } from "./rota";
import { fmtDataHora, fmtMesExtenso } from "./tempo";
import Variacao from "./Variacao";
import "./resumoDasMedicoes.css";

export type { RespostaResumo } from "./resumoEtapas";

// Resumo das medicoes (#749; quadro por etapa desde a #805, decisao do dono de 18/11/2026). A pagina e' de quem LE (a
// diretoria) e responde "onde esta' o dinheiro do mes?": no alto, quanto ha' em cada etapa do ciclo (em analise,
// boletim, nota, protocolado, recebido) e o medido do mes; embaixo, o quadro com uma coluna por etapa e um cartao por
// medicao. So' leitura: tudo vem pronto de GET /api/resumo-medicoes (`app/resumo_medicoes.py`); a tela nao calcula
// etapa, nao soma e nao estima data.
//
// O que fica na URL (F5 e o link copiado abrem a mesma coisa): a competencia (?mes=), a aba (?aba=anteriores), a
// vista do mes (?vista=tabela) e o contratante (?contratante=). O padrao de cada um nao entra nela.
// - Abas: a competencia (a em trabalho e' a padrao) e os meses anteriores em aberto, de 2025 em diante.
// - Vistas do mes: o Quadro (padrao) e a Tabela, que e' a de antes (uma linha por medicao, uma coluna por etapa) e
//   serve para comparar os valores entre as linhas.
// - Os meses anteriores saem na forma da tabela, agrupados por competencia: quase tudo ali esta' numa etapa so' (o
//   protocolado), e no quadro quatro colunas ficariam vazias.
// - O filtro por contratante recorta no servidor, para os numeros do alto e as referencias serem os do contratante.

const MES = /^[0-9]{4}-(0[1-9]|1[0-2])$/;
const AQUI: Rota = { tela: "resumo-medicoes" };

/** Sem valor ou zero nao e' numero a ler: "—". */
const valor = (c: number | null | undefined) => (c === null || c === undefined || c === 0 ? "—" : brl(c));

/* ------------------------------------------------------------------ a faixa das etapas (o alto da pagina) */

/** A variacao do medido contra uma competencia de referencia (o mes anterior, o mesmo mes do ano anterior). */
function VariacaoDoMedido({ atual, referencia, mes }: { atual: number; referencia: Referencia | null; mes: string }) {
  if (!referencia) return null;
  const nome = nomeDaReferencia(referencia.competencia, mes);
  return <Variacao atual={atual} referencia={referencia.valor_centavos} rotulo={nome.curto} porExtenso={nome.extenso} />;
}

/** Quanto ha' em cada etapa (o medido das medicoes que estao nela, na cota) e quantas medicoes. No mes, o protocolado
 *  e o recebido levam a variacao contra a mesma altura do mes anterior, e a faixa fecha com o medido do mes (a soma
 *  das cinco etapas, o numero do Fechamento) e as variacoes dele. Nos meses anteriores, so' as etapas. */
function FaixaDasEtapas({ etapas, rotulo, mes, medido, mesmaAltura }: {
  etapas: ContagemDaEtapa[]; rotulo: string; mes: string; medido?: RespostaResumo["medido"]; mesmaAltura?: RespostaResumo["mesma_altura"];
}) {
  const de = new Map(etapas.map(e => [e.etapa, e]));
  const altura = mesmaAltura ? nomeDaMesmaAltura(mesmaAltura.competencia, mesmaAltura.ate, mes) : null;
  // so' o protocolado e o recebido tem a referencia; nula (sem lastro) ou zero, a variacao nao aparece
  const referenciaDe = (etapa: string): number | null =>
    (etapa === "protocolado" ? mesmaAltura?.protocolado_centavos : etapa === "recebido" ? mesmaAltura?.recebido_centavos : null) ?? null;
  return (
    <dl className="rdm-faixa" aria-label={rotulo}>
      {ETAPAS.map(e => {
        const x = de.get(e.chave);
        const n = x?.medicoes ?? 0;
        const referencia = referenciaDe(e.chave);
        return (
          <div key={e.chave} className="rdm-faixa__item">
            <dt><MarcaEtapa etapa={e.chave} /></dt>
            <dd className="rdm-faixa__valor">{n === 0 ? "—" : valor(x?.valor_centavos)}</dd>
            {n > 0 && <dd className="rdm-faixa__apoio rdm-faixa__qtd num">{contar(n, "medição", "medições")}</dd>}
            {altura && referencia !== null && referencia > 0 && (
              <dd className="rdm-faixa__apoio rdm-faixa__variacao">
                <Variacao atual={x?.valor_centavos ?? 0} referencia={referencia} rotulo={altura.curto} porExtenso={altura.extenso} />
              </dd>
            )}
          </div>
        );
      })}
      {medido && (
        <div className="rdm-faixa__item rdm-faixa__item--medido">
          <dt>Medido em {fmtMesExtenso(mes)}</dt>
          <dd className="rdm-faixa__valor">{valor(medido.valor_centavos)}</dd>
          {(medido.mes_anterior || medido.ano_anterior) && (
            <dd className="rdm-faixa__apoio rdm-faixa__variacoes">
              <VariacaoDoMedido atual={medido.valor_centavos} referencia={medido.mes_anterior} mes={mes} />
              <VariacaoDoMedido atual={medido.valor_centavos} referencia={medido.ano_anterior} mes={mes} />
            </dd>
          )}
        </div>
      )}
    </dl>
  );
}

/* ------------------------------------------------------------------ os blocos curtos sob o quadro */

/** A medicao com a planilha/carta gerada e ainda nao enviada ao orgao: existe, mas o ciclo nao comecou e ela nao tem
 *  coluna no quadro. Fica dita aqui, com o link dela. */
function PlanilhaAEnviar({ d, ir }: { d: RespostaResumo; ir: Ir }) {
  const linhas = linhasDaEtapa(d.grupos.flatMap(g => g.linhas), "antes");
  if (linhas.length === 0) return null;
  return (
    <section className="rdm-bloco" aria-labelledby="rdm-antes">
      <div className="rdm-bloco__cab">
        <h3 id="rdm-antes">{ANTES}</h3>
        <Contador rotulo={contar(linhas.length, "medição", "medições")}>{linhas.length}</Contador>
      </div>
      <ul className="rdm-itens">
        {linhas.map(l => (
          <li key={l.medicao_id}>
            <span className="rdm-itens__obra">{l.obra}</span>
            <Link className="link" para={{ tela: "medicao", obra: l.contrato_id, id: l.medicao_id }} ir={ir}>{l.titulo}</Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** As obras ativas sem medicao na competencia, cada uma com o mes da ultima medicao dela. */
function SemMedicaoNoMes({ d, ir }: { d: RespostaResumo; ir: Ir }) {
  const n = d.sem_medicao.length;
  if (n === 0) return null;
  return (
    <section className="rdm-bloco" aria-labelledby="rdm-sem">
      <div className="rdm-bloco__cab">
        <h3 id="rdm-sem">Sem medição em {fmtMesExtenso(d.mes)}</h3>
        <Contador rotulo={contar(n, "obra", "obras")}>{n}</Contador>
      </div>
      <ul className="rdm-itens">
        {d.sem_medicao.map(o => (
          <li key={o.contrato_id}>
            <Link className="rdm-itens__obra" para={{ tela: "obra", id: o.contrato_id, aba: "medicoes" }} ir={ir}>{o.obra}</Link>
            {o.ultima ? (
              <span className="rdm-itens__apoio">
                última em{" "}
                <Link className="link" para={{ tela: "medicao", obra: o.contrato_id, id: o.ultima.medicao_id }} ir={ir}
                  aria-label={`${o.ultima.titulo}, de ${mesPorExtenso(o.ultima.competencia)}`}>
                  {mesDaUltima(o.ultima.competencia, d.mes)}
                </Link>
              </span>
            ) : <span className="rdm-itens__apoio">nunca mediu</span>}
          </li>
        ))}
      </ul>
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
  // tudo o que a pessoa escolhe esta' na URL; sem a competencia, o servidor responde a em trabalho (o mes anterior ao de hoje)
  const mes = busca.mes && MES.test(busca.mes) ? busca.mes : null;
  const contratante = busca.contratante || null;
  const aba = busca.aba === "anteriores" ? "anteriores" : "mes";
  const vista = busca.vista === "tabela" ? "tabela" : "quadro";

  const consulta = new URLSearchParams({ ...(mes ? { mes } : {}), ...(contratante ? { contratante } : {}) }).toString();
  useEffect(() => {
    let vivo = true;
    api<RespostaResumo>(`/api/resumo-medicoes${consulta ? `?${consulta}` : ""}`)
      .then(r => { if (vivo) { setD(r); setErro(""); } })
      .catch(e => { if (vivo) setErro(mensagemDeErro(e)); });
    return () => { vivo = false; };
  }, [consulta]);

  if (!d) {
    return erro
      ? <Falha>Não foi possível carregar o resumo das medições: {erro} Recarregue a página para tentar de novo.</Falha>
      : <p className="rdm-vazio">Carregando…</p>;
  }
  // a competencia em trabalho e' a padrao e nao entra na URL; a troca de mes e' no lugar (Voltar sai da tela)
  const irPara = (novo: string) => trocarBusca({ mes: novo === d.em_trabalho ? null : novo });
  /** A busca de agora com as mudancas; o que e' padrao (nulo) sai dela. */
  const com = (mudancas: Record<string, string | null>): Busca => {
    const nova: Busca = { ...(mes ? { mes } : {}), ...(contratante ? { contratante } : {}), ...(aba === "anteriores" ? { aba } : {}),
      ...(vista === "tabela" ? { vista } : {}) };
    for (const [k, v] of Object.entries(mudancas)) { if (v === null) delete nova[k]; else nova[k] = v; }
    return nova;
  };
  const emTrabalho = d.mes === d.em_trabalho;
  const carregando = (mes ?? d.em_trabalho) !== d.mes || (d.contratante ?? null) !== contratante;
  const nomeMes = mesPorExtenso(d.mes), soMes = fmtMesExtenso(d.mes);
  const linhasDoMes = d.grupos.flatMap(g => g.linhas);
  const doMes: Grupo[] = d.grupos.map(g => ({ chave: g.contratante, titulo: g.contratante, medicoes: g.medicoes, valor_centavos: g.valor_centavos, linhas: g.linhas }));
  const anteriores: Grupo[] = d.anteriores.map(g => ({ chave: g.competencia, titulo: maiuscula(mesPorExtenso(g.competencia)), medicoes: g.medicoes,
    valor_centavos: g.valor_centavos, linhas: g.linhas }));
  const nAnteriores = d.anteriores.reduce((n, g) => n + g.medicoes, 0);
  // o filtro lista quem tem medicao na aba aberta; o contratante que esta' na URL aparece mesmo sem nenhuma
  const opcoes = d.contratantes.map(c => ({ nome: c.contratante, n: aba === "mes" ? c.medicoes : c.anteriores }))
    .filter(c => c.n > 0 || c.nome === contratante);
  if (contratante && !opcoes.some(c => c.nome === contratante)) opcoes.push({ nome: contratante, n: 0 });
  const total = opcoes.reduce((n, c) => n + c.n, 0);
  const exportar = new URLSearchParams({ mes: d.mes, ...(contratante ? { contratante } : {}) }).toString();
  const semNada = <Link para={AQUI} busca={com({ contratante: null })} ir={ir}>Ver todos os contratantes</Link>;

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
        <div className="rdm-cab__acoes">
          <Link className="link" para={{ tela: "fechamento" }} ir={ir}>Mês a mês no Fechamento</Link>
          <a className="btn btn--pequeno" href={`/api/resumo-medicoes.csv?${exportar}`}>
            <IconeBaixar className="icone icone--p" /> Exportar CSV
          </a>
        </div>
      </div>
      <Atualizacao a={d.atualizacao} />
      {erro && <Falha className="rdm-aviso">Não foi possível carregar {mes ? mesPorExtenso(mes) : "a competência"}: {erro}</Falha>}

      <nav className="abas rdm-abas" aria-label="Resumo das medições">
        <Link className="aba" para={AQUI} busca={com({ aba: null })} ir={ir} aria-current={aba === "mes" ? "page" : undefined}>
          {emTrabalho ? `${maiuscula(soMes)} em trabalho` : maiuscula(nomeMes)}
        </Link>
        <Link className="aba" para={AQUI} busca={com({ aba: "anteriores" })} ir={ir} aria-current={aba === "anteriores" ? "page" : undefined}>
          Meses anteriores{nAnteriores > 0 && <> <Contador rotulo={contar(nAnteriores, "medição em aberto", "medições em aberto")}>{nAnteriores}</Contador></>}
        </Link>
      </nav>

      {(opcoes.length > 1 || contratante || aba === "mes") && (
        <div className="rdm-barra">
          {(opcoes.length > 1 || contratante) && (
            <nav className="escolhas" aria-label="Contratante">
              <Link className="escolha" para={AQUI} busca={com({ contratante: null })} ir={ir} aria-current={contratante === null ? "true" : undefined}>
                Todos{contratante === null && <> <span className="escolha__n num">{total.toLocaleString("pt-BR")}</span></>}
              </Link>
              {opcoes.map(c => (
                <Link key={c.nome} className="escolha" para={AQUI} busca={com({ contratante: c.nome })} ir={ir}
                  aria-current={contratante === c.nome ? "true" : undefined}>
                  {c.nome} <span className="escolha__n num">{c.n.toLocaleString("pt-BR")}</span>
                </Link>
              ))}
            </nav>
          )}
          {aba === "mes" && (
            <nav className="escolhas rdm-vistas" aria-label="Vista do mês">
              <Link className="escolha" para={AQUI} busca={com({ vista: null })} ir={ir} aria-current={vista === "quadro" ? "true" : undefined}>Quadro</Link>
              <Link className="escolha" para={AQUI} busca={com({ vista: "tabela" })} ir={ir} aria-current={vista === "tabela" ? "true" : undefined}>Tabela</Link>
            </nav>
          )}
        </div>
      )}

      {aba === "mes" ? <>
        {/* o mes sem medicao nao tem numero a ler: a linha curta embaixo diz o vazio */}
        {linhasDoMes.length > 0 && (
          <FaixaDasEtapas etapas={d.etapas} mes={d.mes} medido={d.medido} mesmaAltura={d.mesma_altura}
            rotulo={`Medições de ${nomeMes} por etapa, com o medido na cota da Lotufo`} />
        )}
        {linhasDoMes.length === 0 ? (
          <p className="rdm-vazio">Nenhuma medição em {nomeMes}{contratante ? ` de ${contratante}` : ""}.{contratante && <> {semNada}</>}</p>
        ) : vista === "quadro" ? (
          <ResumoQuadro linhas={linhasDoMes} etapas={d.etapas} hoje={d.hoje} limitePorMil={d.diferenca_critica_por_mil} ir={ir}
            rotulo={`Medições de ${nomeMes}, uma coluna por etapa`} />
        ) : (
          <section className="cartao rdm-painel" aria-label={`Medições de ${nomeMes} por obra`}>
            <ResumoTabela grupos={doMes} ir={ir} limitePorMil={d.diferenca_critica_por_mil} rotulo={`Medições de ${nomeMes} por obra`}
              legenda={`Etapa da medição de cada obra em ${nomeMes}, por contratante, com a data registrada de cada etapa e o medido na cota da Lotufo`} />
          </section>
        )}
        {vista === "quadro" && <PlanilhaAEnviar d={d} ir={ir} />}
        <SemMedicaoNoMes d={d} ir={ir} />
      </> : <>
        {anteriores.length === 0 ? (
          <p className="rdm-vazio">Nenhuma medição aberta de meses anteriores{contratante ? ` de ${contratante}` : ""}.{contratante && <> {semNada}</>}</p>
        ) : <>
          <FaixaDasEtapas etapas={d.anteriores_etapas} mes={d.mes}
            rotulo={`Medições abertas de meses anteriores a ${nomeMes} por etapa, com o medido na cota da Lotufo`} />
          <section className="cartao rdm-painel" aria-label="Medições abertas de meses anteriores">
            <ResumoTabela grupos={anteriores} ir={ir} limitePorMil={d.diferenca_critica_por_mil} rotulo="Medições abertas de meses anteriores"
              legenda={`Medições de competências anteriores a ${nomeMes} ainda não recebidas, por competência, com a etapa de cada uma e o medido na cota da Lotufo`} />
          </section>
        </>}
      </>}
    </div>
  );
}
