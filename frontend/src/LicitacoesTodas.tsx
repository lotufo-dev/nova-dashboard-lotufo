import { useEffect, useId, useState } from "react";
import Falha from "./Falha";
import { contar } from "./formato";
import {
  fmtKm, nomeDaLicitacao, pedidoDeTodas, temFiltro, useDecisoes, useLicitacoes,
  type FalhaDaDecisao, type FiltroDeTodas, type LinhaDeTodas, type RespostaTodas,
} from "./licitacoes";
import {
  FalhaAoAtualizar, LeituraDoRadarLinha, Licitacao, Prazo, RecusaSemLinha, SemLeitura, Traco, Valor,
} from "./LicitacoesPecas";
import { Link } from "./Link";
import { VISTAS_DE_TODAS } from "./navegacao";
import Rolagem from "./Rolagem";
import { trocarBusca, type Busca, type VistaTodas } from "./rota";
import Selo from "./Selo";
import { Abas } from "./Topo";

// TODAS (fatia 3 da #906, docs/adr/0018): "/licitacoes/todas" e "/licitacoes/grande-vulto". Responde "existe a
// licitacao que procuro?": a lista inteira das novas que o radar mostra hoje (ou a das obras de grande vulto, em
// qualquer estado), com busca, filtros e ordem.
//
// A busca, os filtros e a ordem vao na busca do endereco: o link guarda o recorte. Quem filtra, conta e ordena e' o
// servidor (GET /api/licitacoes/todas): a pagina so' manda o que esta' no endereco e desenha o que volta, inclusive
// as opcoes de cada filtro com a quantidade de licitacoes que a lista teria escolhendo-a. O campo de busca espera a
// pessoa parar de digitar (BUSCA_ESPERA) antes de trocar o endereco, para nao pedir a lista a cada letra.
//
// AS DECISOES, so' com `pode_decidir` (depois do corte, a quem decide), pelas rotas da Triagem: Favoritar a que nao e'
// favorita nem esta' descartada ou encerrada, e Desfazer o descarte da descartada. E' a unica pagina que lista as
// descartadas (o filtro "Decisão"). A coluna Decisao existe sempre, porque diz tambem o que ja' foi decidido; por isso
// a tabela vira um bloco por licitacao ate' 900 px de pagina, como a Triagem com as decisoes.
//
// As vistas sao abas, cada uma no proprio endereco; o recorte nao passa de uma para a outra, porque as listas sao
// outras (as opcoes de tipo, orgao e portal saem de cada uma).

const BUSCA_ESPERA = 300;
const VISTAS: readonly VistaTodas[] = ["novas", "grande-vulto"];

/** O que as linhas precisam para decidir; nulo quando a pagina e' so' de leitura. */
type Decisoes = {
  ocupada: boolean; falha: FalhaDaDecisao | null;
  favoritar: (l: LinhaDeTodas) => void; desfazerDescarte: (l: LinhaDeTodas) => void;
};

/** O campo de busca: o texto fica na pagina enquanto se digita e vai para o endereco quando a pessoa para. Se o endereco
 *  muda por fora (Limpar os filtros, Voltar), o campo acompanha. */
function CampoDeBusca({ valor }: { valor: string }) {
  const [texto, setTexto] = useState(valor);
  // o endereco mudou por fora: o campo passa a ser o dele (o ajuste durante a renderizacao, sem efeito)
  const [doEndereco, setDoEndereco] = useState(valor);
  if (valor !== doEndereco) { setDoEndereco(valor); setTexto(valor); }
  useEffect(() => {
    if (texto === valor) return;
    const t = window.setTimeout(() => trocarBusca({ q: texto.trim() ? texto : null }), BUSCA_ESPERA);
    return () => window.clearTimeout(t);
  }, [texto, valor]);
  return (
    <div className="campo lic-filtro lic-filtro--busca">
      <label className="campo__rotulo" htmlFor="lic-busca">Buscar</label>
      <input id="lic-busca" type="search" autoComplete="off" placeholder="Órgão, edital, objeto ou município…" maxLength={200}
        value={texto} onChange={ev => setTexto(ev.target.value)} />
    </div>
  );
}

/** Um filtro de escolha: "Todos" e as opcoes que o servidor manda, cada uma com a quantidade. */
function Escolha({ f }: { f: FiltroDeTodas }) {
  const id = useId();
  return (
    <div className="campo lic-filtro">
      <label className="campo__rotulo" htmlFor={id}>{f.rotulo}</label>
      <select id={id} value={f.escolhido ?? ""} onChange={ev => trocarBusca({ [f.filtro]: ev.target.value || null })}>
        <option value="">Todos</option>
        {f.opcoes.map(o => <option key={o.valor} value={o.valor}>{o.rotulo} ({o.n.toLocaleString("pt-BR")})</option>)}
      </select>
    </div>
  );
}

function Filtros({ dados, busca }: { dados: RespostaTodas; busca: Busca }) {
  return (
    <form className="lic-filtros" role="search" aria-label="Buscar e filtrar as licitações" onSubmit={ev => ev.preventDefault()}>
      <CampoDeBusca valor={busca.q ?? ""} />
      {dados.filtros.map(f => <Escolha key={f.filtro} f={f} />)}
      <div className="campo lic-filtro">
        <label className="campo__rotulo" htmlFor="lic-sessao-de">Sessão de</label>
        <input id="lic-sessao-de" type="date" value={busca.sessao_de ?? ""} onChange={ev => trocarBusca({ sessao_de: ev.target.value || null })} />
      </div>
      <div className="campo lic-filtro">
        <label className="campo__rotulo" htmlFor="lic-sessao-ate">Sessão até</label>
        <input id="lic-sessao-ate" type="date" value={busca.sessao_ate ?? ""} onChange={ev => trocarBusca({ sessao_ate: ev.target.value || null })} />
      </div>
      <div className="campo lic-filtro">
        <label className="campo__rotulo" htmlFor="lic-ordem">Ordem</label>
        <select id="lic-ordem" value={dados.ordem} onChange={ev => trocarBusca({ ordem: ev.target.value === "padrao" ? null : ev.target.value })}>
          {dados.ordens.map(o => <option key={o.ordem} value={o.ordem}>{o.rotulo}</option>)}
        </select>
      </div>
    </form>
  );
}

/** A decisao em vigor da linha e, a quem decide, o botao que cabe a ela. */
function CelulaDaDecisao({ l, decisoes }: { l: LinhaDeTodas; decisoes: Decisoes | null }) {
  const nome = nomeDaLicitacao(l);
  return (
    <td className="lic-c-decisao" data-rotulo="Decisão">
      {l.favorita ? <><Selo>Favorita</Selo><span className="lic-sub">{l.favorita.etapa_rotulo}</span></>
        : l.descarte ? <><Selo>Descartada</Selo><span className="lic-sub">{l.descarte.rotulo}</span></>
        : !decisoes || l.encerrada ? <Traco /> : null}
      {decisoes && !l.favorita && (l.descarte || !l.encerrada) && (
        <div className="lic-acoes">
          {l.descarte
            ? <button type="button" className="btn btn--pequeno" disabled={decisoes.ocupada}
                aria-label={`Desfazer o descarte: ${nome}`} onClick={() => decisoes.desfazerDescarte(l)}>Desfazer o descarte</button>
            : <button type="button" className="btn btn--pequeno btn--primario" disabled={decisoes.ocupada}
                aria-label={`Favoritar: ${nome}`} onClick={() => decisoes.favoritar(l)}>Favoritar</button>}
        </div>
      )}
      {decisoes?.falha?.id === l.id && <Falha className="lic-falha">{decisoes.falha.texto}</Falha>}
    </td>
  );
}

function Tabela({ linhas, decisoes, legenda }: { linhas: LinhaDeTodas[]; decisoes: Decisoes | null; legenda: string }) {
  return (
    <Rolagem rotulo={legenda}>
      <table className="tabela lic-tabela lic-tabela--nota lic-tabela--decide">
        <caption className="sr-only">{legenda}</caption>
        <thead>
          <tr>
            <th scope="col" className="col-num">Nota</th><th scope="col">Licitação</th><th scope="col">Tipo de obra</th>
            <th scope="col">Local</th><th scope="col" className="col-num">Valor</th><th scope="col">Sessão</th>
            <th scope="col">Decisão</th>
          </tr>
        </thead>
        <tbody>
          {linhas.map(l => {
            const km = fmtKm(l.km);
            return (
              <tr key={l.chave}>
                <td className="col-num lic-c-nota" data-rotulo="Nota">
                  {l.recomendada ? l.recomendada.nota.toLocaleString("pt-BR") : <Traco />}
                </td>
                <th scope="row" className="lic-c-licitacao"><Licitacao l={l} /></th>
                <td data-rotulo="Tipo de obra">{l.tipo_obra || <Traco />}</td>
                <td data-rotulo="Local">
                  {l.cidade || km
                    ? <>{l.cidade && <span className="lic-cidade">{l.cidade}{l.uf && `/${l.uf}`}</span>}{km && <span className="num lic-km">{km}</span>}</>
                    : <Traco />}
                </td>
                <td className="col-num lic-c-valor" data-rotulo="Valor"><Valor l={l} /></td>
                <td data-rotulo="Sessão">
                  {l.data_sessao
                    ? <span className="lic-prazo"><Prazo p={{ data: l.data_sessao, hora: l.hora_sessao, dias_uteis: l.dias_uteis, passado: l.encerrada, hoje: l.sessao_hoje, situacao: l.prazo }} /></span>
                    : <Traco />}
                </td>
                <CelulaDaDecisao l={l} decisoes={decisoes} />
              </tr>
            );
          })}
        </tbody>
      </table>
    </Rolagem>
  );
}

export default function LicitacoesTodas({ vista, busca }: { vista: VistaTodas; busca: Busca }) {
  const { dados, erro, tentar } = useLicitacoes<RespostaTodas>(pedidoDeTodas(vista, busca));
  const { falha, ocupada, decidir } = useDecisoes(tentar);
  const abas = (
    <Abas rotulo="Vistas de Todas" atual={vista} itens={VISTAS.map(v => ({
      id: v, rotulo: VISTAS_DE_TODAS[v], para: v === "novas" ? { tela: "licitacoes-todas" } : { tela: "licitacoes-todas", vista: v } }))} />
  );
  // os dados da outra vista nao servem enquanto a desta nao chega
  if (!dados || dados.vista !== vista) return <SemLeitura erro={erro} tentar={() => void tentar()}>{abas}</SemLeitura>;

  const decisoes: Decisoes | null = dados.pode_decidir ? {
    ocupada, falha,
    favoritar: l => void decidir(l, "favorita"),
    desfazerDescarte: l => void decidir(l, "descarte/desfazer"),
  } : null;
  const filtrou = temFiltro(busca);
  const n = dados.linhas.length;
  const legenda = vista === "novas" ? "Licitações novas" : "Licitações de grande vulto";
  return (
    <div className="pagina lic">
      {abas}
      <LeituraDoRadarLinha leitura={dados.leitura} />
      <Filtros dados={dados} busca={busca} />
      <FalhaAoAtualizar erro={erro} tentar={() => void tentar()} />
      <RecusaSemLinha falha={decisoes?.falha ?? null} linhas={dados.linhas} />
      <section className="cartao lic-bloco" aria-label={legenda}>
        <header className="cartao__cabeca lic-achadas">
          <p className="lic-achadas__n" role="status">
            {filtrou && n !== dados.total
              ? <>{n.toLocaleString("pt-BR")} de {contar(dados.total, "licitação", "licitações")}</>
              : contar(n, "licitação", "licitações")}
          </p>
          {filtrou && <Link className="lic-limpar" para={vista === "novas" ? { tela: "licitacoes-todas" } : { tela: "licitacoes-todas", vista }}>Limpar os filtros</Link>}
        </header>
        {n === 0
          ? <div className="vazio vazio--curto"><p>{dados.total === 0 ? "Nenhuma licitação." : "Nenhuma licitação com esses filtros."}</p></div>
          : <Tabela linhas={dados.linhas} decisoes={decisoes} legenda={legenda} />}
      </section>
    </div>
  );
}
