import { useId } from "react";
import { contagem, destinoDoAviso, SELO, semEmpresa, semObra, type Aviso, type Nivel } from "./Alertas";
import { FAMILIAS, filtrarAvisos, ondeSeResolve, porFamilia, porObra, quandoDoAviso, semRSOrfao, type Familia, type Grupo } from "./avisos";
import { IconeAlerta } from "./icones";
import { brl } from "./Medicoes";
import { trocarBusca, type Busca } from "./rota";
import { Link } from "./Link";
import Rolagem from "./Rolagem";
import Selo from "./Selo";

// Avisos (NAVEGACAO.md › Avisos), agora DENTRO de Obras (decisao de 09/10/2026): a fila consolidada, com o recorte do perfil (o servidor manda os da
// operacao ou os da diretoria). Por familia (o lar do aviso) ou por obra; dentro, do mais grave ao mais atrasado.
// Em cada grupo, a Atencao fica recolhida (com o mais urgente no resumo), menos quando ha' filtro (tipo, nivel ou
// obra) ou o agrupamento e' por obra: ai tudo aberto. Filtros e agrupamento na URL (?familia= ?nivel=
// ?obra= ?agrupar=obra); o "tipo" da tela e' a familia do aviso (o lar dele).

const NIVEIS: { id: Nivel; rotulo: string }[] = [
  { id: "critico", rotulo: "Crítico" }, { id: "acao", rotulo: "Ação" }, { id: "atencao", rotulo: "Atenção" }];

const chaveDoAviso = (a: Aviso, i: number) => `${a.tipo}-${a.contrato_id}-${a.entidade_id ?? ""}-${a.medicao_id ?? ""}-${i}`;

/** O fato do aviso com a obra (ou a empresa) em negrito, lida do CAMPO e nao do texto; o prefixo no texto (documentos,
 *  que ainda o trazem) tem a mesma saida. Dentro do grupo da obra/empresa (`omitirObra`) o nome ja' esta' no titulo. */
function Fato({ a, texto, omitirObra }: { a: Aviso; texto: string; omitirObra: boolean }) {
  const quem = [a.obra, a.entidade].find(q => q && texto.startsWith(`${q}: `));
  if (quem) return <><span className="forte">{quem}</span>{semRSOrfao(texto.slice(quem.length))}</>;
  if (!omitirObra && a.obra) return <><span className="forte">{a.obra}</span>{": "}{semRSOrfao(texto)}</>;
  return <>{semRSOrfao(texto)}</>;
}

function LinhaAviso({ a, tirar, omitirObra, comValor }: { a: Aviso; tirar: (a: Aviso) => Aviso; omitirObra: boolean; comValor: boolean }) {
  const s = SELO[a.nivel] ?? SELO.atencao;
  const d = destinoDoAviso(a);
  const texto = tirar(a).mensagem;
  // F-54: o fato em texto neutro, com a obra (ou a empresa) em negrito; o link fica no destino
  // dentro do grupo da obra (ou da empresa) o nome ja' esta' no titulo: o destino diz so' a aba (N4-03)
  const onde = ondeSeResolve(a, omitirObra);
  // o link do destino fora de contexto (lista de links do leitor de tela) leva a frase do aviso como descricao
  const idTexto = useId();
  return (
    <tr>
      <td><Selo classe={s.classe} forte={s.forte}>{s.rotulo}</Selo></td>
      <td id={idTexto} className="aviso__fato"><Fato a={a} texto={texto} omitirObra={omitirObra} /></td>
      <td className="num">{quandoDoAviso(a)}</td>
      {comValor && <td className="col-num dinheiro num">{a.valor_centavos !== null ? brl(a.valor_centavos) : ""}</td>}
      <td>{d && onde ? <Link para={d.para} busca={d.busca} secao={d.secao} aria-describedby={idTexto}>{onde}</Link> : onde || "—"}</td>
    </tr>
  );
}

/** So' ha' coluna de Valor quando alguma linha da PAGINA tem valor (F-79): senao ela seria so' um vazio de 136px.
 *  Calculado sobre todos os avisos visiveis e passado a todas as tabelas: com o colgroup comum, Quando e Onde nao
 *  mudam de x entre tabelas irmas (N07-G-05). */
const temValor = (itens: Aviso[]) => itens.some(a => a.valor_centavos !== null);

/** A grade e o cabecalho comuns a todas as tabelas de avisos (F-47); `caption` so' para o leitor de tela (F-93). */
function CabecaAvisos({ rotulo, comValor }: { rotulo: string; comValor: boolean }) {
  return (
    <>
      <caption className="sr-only">{rotulo}</caption>
      <colgroup>
        <col className="c-nivel" /><col /><col className="c-quando" />{comValor && <col className="c-valor-aviso" />}<col className="c-onde" />
      </colgroup>
      <thead>
        <tr><th scope="col">Nível</th><th scope="col">Aviso</th><th scope="col">Quando</th>
          {comValor && <th scope="col" className="col-num">Valor</th>}<th scope="col">Onde se resolve</th></tr>
      </thead>
    </>
  );
}

function Linhas({ itens, rotulo, tirar, omitirObra, comValor, unica = false }: { itens: Aviso[]; rotulo: string; tirar: (a: Aviso) => Aviso; omitirObra: boolean; comValor: boolean; unica?: boolean }) {
  // caixa com cabecalho fixo so' onde a tabela pode passar de uma tela: lista longa, ou a unica tabela da pagina
  // (filtro por tipo, nivel ou obra). Em toda tabela, cortava as de 12 linhas no meio da pagina (N06-02).
  return (
    <Rolagem rotulo={rotulo} alta={unica || itens.length > 12}>
      <table className="tabela tabela--grade">
        <CabecaAvisos rotulo={rotulo} comValor={comValor} />
        <tbody>
          {itens.map((a, i) => <LinhaAviso key={chaveDoAviso(a, i)} a={a} tirar={tirar} omitirObra={omitirObra} comValor={comValor} />)}
        </tbody>
      </table>
    </Rolagem>
  );
}

/** Por obra (F-55): uma tabela so', um bloco por obra (ou empresa) aberto por uma linha de grupo com o nome, a
 *  contagem e o link. Um cartao por obra repetia cabecalho, cabeca de tabela e respiro para 1 ou 2 avisos. */
function TabelaPorObra({ grupos, comValor }: { grupos: Grupo[]; comValor: boolean }) {
  return (
    <section className="cartao" aria-label="Avisos por obra">
      <Rolagem rotulo="Avisos por obra" alta>
        <table className="tabela tabela--grade">
          <CabecaAvisos rotulo="Avisos por obra" comValor={comValor} />
          {grupos.map(g => {
            const tirar = g.contratoId !== null ? semObra : g.entidadeId != null ? semEmpresa : (a: Aviso) => a;
            return (
              <tbody key={g.chave}>
                <tr className="grupo">
                  <th scope="rowgroup" colSpan={comValor ? 5 : 4} id={g.chave}>
                    {g.contratoId !== null
                      ? <Link para={{ tela: "obra", id: g.contratoId, aba: "medicoes" }}>{g.rotulo}</Link>
                      : g.entidadeId != null
                      ? <Link para={{ tela: "documentos-empresa", id: g.entidadeId }}>{g.rotulo}</Link>
                      : g.rotulo}
                    <span className="grupo__conta num">{contagem(g.itens)}</span>
                  </th>
                </tr>
                {g.itens.map((a, i) => <LinhaAviso key={chaveDoAviso(a, i)} a={a} tirar={tirar} omitirObra={g.contratoId !== null || g.entidadeId != null} comValor={comValor} />)}
              </tbody>
            );
          })}
        </table>
      </Rolagem>
    </section>
  );
}

function CartaoGrupo({ g, abrirTudo, porObraSim, comValor, unico = false }: { g: Grupo; abrirTudo: boolean; porObraSim: boolean; comValor: boolean; unico?: boolean }) {
  // Atencao recolhida, com a contagem e o mais urgente no resumo (ele e' o primeiro dela, na ordem por atraso)
  const graves = abrirTudo ? g.itens : g.itens.filter(a => a.nivel === "critico" || a.nivel === "acao");
  const atencao = abrirTudo ? [] : g.itens.filter(a => a.nivel !== "critico" && a.nivel !== "acao");
  const titulo = `titulo-grupo-${g.chave}`;
  // no grupo da obra (ou da empresa, A11), o nome ja' esta' no titulo: a mensagem perde o "Nome: " do comeco
  const tirar = !porObraSim ? (a: Aviso) => a : g.contratoId !== null ? semObra : g.entidadeId != null ? semEmpresa : (a: Aviso) => a;
  const omitirObra = porObraSim && (g.contratoId !== null || g.entidadeId != null);
  const selo = SELO[atencao[0]?.nivel ?? "atencao"] ?? SELO.atencao;
  return (
    <section className="cartao" aria-labelledby={titulo} id={g.chave}>
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id={titulo}>{g.rotulo}</h2>
        <span className="cartao__dica num">{contagem(g.itens)}</span>
        {g.contratoId !== null && (
          <div className="cartao__acoes">
            <Link className="btn btn--pequeno" para={{ tela: "obra", id: g.contratoId, aba: "medicoes" }}>Abrir a obra</Link>
          </div>
        )}
        {g.entidadeId != null && (
          <div className="cartao__acoes">
            <Link className="btn btn--pequeno" para={{ tela: "documentos-empresa", id: g.entidadeId }}>Abrir em Documentos</Link>
          </div>
        )}
      </div>
      {graves.length > 0 && <Linhas itens={graves} rotulo={`Avisos: ${g.rotulo}`} tirar={tirar} omitirObra={omitirObra} comValor={comValor} unica={unico} />}
      {atencao.length > 0 && (
        <details className="detalhes detalhes--tabela cartao__corpo">
          {/* so' "Atenção (N)" fica no acento de link; o mais urgente (nem sempre atrasado: o prazo pode ainda nao ter
              vencido) e' apoio, com o selo do nivel dele (N4-05, F-79) */}
          <summary>Atenção ({atencao.length})<span className="detalhes__resto"> · o mais urgente: <Selo classe={selo.classe} forte={selo.forte}>{selo.rotulo}</Selo> <Fato a={atencao[0]} texto={tirar(atencao[0]).mensagem} omitirObra={omitirObra} /></span></summary>
          <Linhas itens={atencao} rotulo={`Avisos de atenção: ${g.rotulo}`} tirar={tirar} omitirObra={omitirObra} comValor={comValor} />
        </details>
      )}
    </section>
  );
}

/** A lista de avisos de dentro de Obras (decisao de 09/10/2026; redesenho #159): abre na propria pagina, com o recorte
 *  da lista (`escopo`: os ids das obras do contratante; `null` = todas as obras, com os avisos sem obra). Tudo o que
 *  a tela de Avisos de antes fazia continua aqui: agrupar por tipo ou obra, filtrar por tipo, nivel e obra, e o
 *  "onde se resolve" de cada aviso. `avisos`: `undefined` carregando, `null` falhou. Filtros na URL, ao lado dos da
 *  lista (?familia= ?nivel= ?obra= ?agrupar=obra). */
export default function AvisosPagina({ busca, perfil, avisos, escopo = null, nome, onFechar }: {
  busca: Busca; perfil: string; avisos: Aviso[] | null | undefined; escopo?: ReadonlySet<number> | null; nome: string;
  onFechar: () => void;
}) {
  const familia = (FAMILIAS.find(f => f.id === busca.familia)?.id ?? null) as Familia | null;
  const nivel = (NIVEIS.find(n => n.id === busca.nivel)?.id ?? null) as Nivel | null;
  const obra = /^[1-9][0-9]*$/.test(busca.obra ?? "") ? Number(busca.obra) : null;
  const agruparPorObra = busca.agrupar === "obra";      // ?agrupar=tipo (ou nada) e' o padrao
  const lista = (avisos ?? []).filter(a => escopo === null || (a.contrato_id !== null && escopo.has(a.contrato_id)));
  const filtrados = filtrarAvisos(lista, { familia, nivel, obra });
  const grupos = agruparPorObra ? porObra(filtrados) : porFamilia(filtrados);
  // uma decisao so' para a pagina toda: todas as tabelas visiveis tem as mesmas colunas (N07-G-05)
  const comValor = temValor(filtrados);
  // com filtro, a lista ja' e' curta; por obra, os grupos sao pequenos: recolher so' custaria cliques
  const abrirTudo = familia !== null || obra !== null || nivel !== null || agruparPorObra;
  // as obras do filtro sao as que tem aviso, na ordem alfabetica
  const obras = [...new Map(lista.filter(a => a.contrato_id !== null).map(a => [a.contrato_id!, a.obra ?? `Obra ${a.contrato_id}`])).entries()]
    .sort((x, y) => x[1].localeCompare(y[1], "pt-BR"));
  // a obra da URL pode nao ter mais aviso (resolvido, ou link guardado): o select ganha a opcao dela, para mostrar
  // o filtro em vigor e deixar voltar a "Todas"
  const obraSemAviso = obra !== null && !obras.some(o => o[0] === obra);
  const nomeObra = obra !== null ? obras.find(o => o[0] === obra)?.[1] ?? "a obra filtrada, sem avisos" : null;
  const temFiltro = familia !== null || nivel !== null || obra !== null;
  const aqui = { tela: "obras" as const };
  const com = (m: Record<string, string | null>): Busca => {
    const b: Busca = { ...busca };
    for (const [k, v] of Object.entries(m)) { if (v === null) delete b[k]; else b[k] = v; }
    return b;
  };

  // a meta pode passar da faixa com filtros e nome de obra: corta com reticencias e vai inteira no title (F-50)
  const metaAvisos = !avisos ? ""
    : `${temFiltro ? `${filtrados.length} de ` : ""}${lista.length} ${lista.length === 1 ? "aviso" : "avisos"} ${perfil === "diretoria" ? "da diretoria" : "da operação"}`
      + [familia && FAMILIAS.find(f => f.id === familia)?.rotulo, nivel && NIVEIS.find(n => n.id === nivel)?.rotulo, nomeObra]
        .filter(Boolean).map(x => ` · ${x}`).join("");

  return (
    <section className="cartao avisos-area" id="avisos-area" aria-labelledby="titulo-avisos">
      <div className="cartao__cabeca">
        <h2 className="cartao__titulo" id="titulo-avisos">Avisos · {nome}</h2>
        {metaAvisos && <span className="cartao__dica num" title={metaAvisos}>{metaAvisos}</span>}
        <div className="cartao__acoes"><button type="button" className="btn btn--pequeno" onClick={onFechar}>Fechar os avisos</button></div>
      </div>
      <div className="cartao__corpo avisos-area__corpo">
        <div className="filtros-avisos__linhas" role="group" aria-label="Filtros dos avisos">
          <p className="filtros-avisos__linha">
            <span className="campo__rotulo">Agrupar</span>
            <Link para={aqui} busca={com({ agrupar: null })} aria-current={!agruparPorObra ? "true" : undefined}>por tipo</Link>
            <Link para={aqui} busca={com({ agrupar: "obra" })} aria-current={agruparPorObra ? "true" : undefined}>por obra</Link>
          </p>
          <p className="filtros-avisos__linha">
            <span className="campo__rotulo">Tipo</span>
            <Link para={aqui} busca={com({ familia: null })} aria-current={familia === null ? "true" : undefined}>Todas</Link>
            {FAMILIAS.map(f => {
              const n = filtrarAvisos(lista, { familia: f.id, nivel, obra }).length;
              return n === 0 && familia !== f.id ? null : (
                <Link key={f.id} para={aqui} busca={com({ familia: f.id })} aria-current={familia === f.id ? "true" : undefined}>
                  {f.rotulo} <span className="num">{n}</span>
                </Link>
              );
            })}
          </p>
          <div className="form-inline">
            <div className="campo">
              <label className="campo__rotulo" htmlFor="avisos-nivel">Nível</label>
              <select id="avisos-nivel" value={nivel ?? ""} onChange={e => trocarBusca({ nivel: e.target.value || null })}>
                <option value="">Todos</option>
                {NIVEIS.map(n => <option key={n.id} value={n.id}>{n.rotulo}</option>)}
              </select>
            </div>
            <div className="campo">
              <label className="campo__rotulo" htmlFor="avisos-obra">Obra</label>
              <select id="avisos-obra" value={obra ?? ""} onChange={e => trocarBusca({ obra: e.target.value || null })}>
                <option value="">Todas</option>
                {obraSemAviso && <option value={obra!}>{nomeObra}</option>}
                {obras.map(([id, nomeDela]) => <option key={id} value={id}>{nomeDela}</option>)}
              </select>
            </div>
          </div>
          {nomeObra !== null && obra !== null && (
            <p className="filtros-avisos__linha">
              {obraSemAviso
                ? <span>Filtro de uma obra que não tem avisos: <Link para={{ tela: "obra", id: obra, aba: "medicoes" }}>abrir a obra</Link></span>
                : <span>Só os avisos de <Link para={{ tela: "obra", id: obra, aba: "medicoes" }}>{nomeObra}</Link></span>}
              {" · "}<Link para={aqui} busca={com({ obra: null })}>ver de todas as obras</Link>
            </p>
          )}
        </div>

        {avisos === undefined && <div className="vazio vazio--curto"><p>Carregando os avisos…</p></div>}
        {avisos === null && (
          <p className="erro" role="alert"><IconeAlerta className="icone icone--p" />
            Não foi possível verificar os avisos. Recarregue a página para tentar de novo.</p>
        )}
        {avisos && grupos.length === 0 && (
          <div className="vazio vazio--curto">
            <p className="vazio__titulo">{temFiltro ? "Nenhum aviso com esses filtros." : "Nenhum aviso. Tudo em dia."}</p>
            {temFiltro && <p><Link para={aqui} busca={com({ familia: null, nivel: null, obra: null })}>Limpar os filtros</Link></p>}
          </div>
        )}
        {grupos.length > 0 && (
          <div className="avisos-area__grupos">
            {agruparPorObra ? <TabelaPorObra grupos={grupos} comValor={comValor} />
              : grupos.map(g => <CartaoGrupo key={g.chave} g={g} abrirTudo={abrirTudo} porObraSim={agruparPorObra} comValor={comValor} unico={grupos.length === 1} />)}
          </div>
        )}
      </div>
    </section>
  );
}
