import Contador from "./Contador";
import Falha from "./Falha";
import { contar } from "./formato";
import {
  nomeDaLicitacao, useDecisoes, useLicitacoes,
  type AlertaDoDia, type FalhaDaDecisao, type FonteDoRadar, type LinhaLicitacao, type ParConferido, type ParParaConferir,
  type RespostaDeConferencia, type RespostaFontes,
} from "./licitacoes";
import { FalhaAoAtualizar, LeituraDoRadarLinha, Licitacao, Prazo, SemLeitura, Traco, Valor } from "./LicitacoesPecas";
import Rolagem from "./Rolagem";
import Selo from "./Selo";
import { fmtData } from "./tempo";

// FONTES (fatia 4 da #906, docs/adr/0018): "/licitacoes/fontes". Responde "o radar leu tudo hoje?", em tres paineis:
// a situacao de cada fonte na ultima leitura, os alertas do dia por regra e a conferencia "e' o mesmo / e' outro" dos
// pares que o radar achou parecidos e nao conseguiu provar iguais.
//
// Tudo vem de GET /api/licitacoes/fontes: a situacao de cada fonte ja' lida pelo servidor, as linhas das licitacoes
// (as mesmas das outras paginas), os pares pendentes e os ja' respondidos que o radar ainda lista. A tela so' desenha.
//
// A CONFERENCIA so' com `pode_decidir` (depois do corte, a quem decide): "É o mesmo" e "É outro" no par pendente;
// "Refazer" no respondido, que o devolve aos pendentes. Antes do corte as respostas sao espelho do radar e nao ha'
// botao. A fila e' da pagina das fontes, e nao da Triagem: pedir a uma pessoa que confirme palpite do radar foi o que o
// docs/adr/0003 tirou da primeira versao; ela fica aqui, para quando houver tempo.

const PALAVRA_DA_FONTE: Record<FonteDoRadar["situacao"], string> = { feito: "Lida", breve: "Aguardando", critico: "Com problema" };

function SituacaoDasFontes({ fontes }: { fontes: FonteDoRadar[] }) {
  return (
    <section className="cartao lic-bloco" aria-labelledby="lic-fontes">
      <header className="cartao__cabeca">
        <h2 className="cartao__titulo" id="lic-fontes">Situação das fontes</h2>
        <Contador rotulo={contar(fontes.length, "fonte", "fontes")}>{fontes.length.toLocaleString("pt-BR")}</Contador>
      </header>
      {fontes.length === 0 ? <div className="vazio vazio--curto"><p>Nenhuma fonte na última leitura.</p></div> : (
        <Rolagem rotulo="Situação das fontes">
          <table className="tabela lic-tabela lic-tabela--fontes">
            <caption className="sr-only">Cada fonte do radar na última leitura</caption>
            <thead>
              <tr>
                <th scope="col">Fonte</th><th scope="col">Situação</th><th scope="col" className="col-num">Lidos</th>
                <th scope="col">Hora</th><th scope="col">Observação</th>
              </tr>
            </thead>
            <tbody>
              {fontes.map(f => (
                <tr key={f.fonte}>
                  <th scope="row" className="lic-c-licitacao"><span className="lic-nome">{f.nome}</span></th>
                  <td data-rotulo="Situação"><Selo situacao={f.situacao}>{PALAVRA_DA_FONTE[f.situacao]}</Selo></td>
                  <td className="col-num" data-rotulo="Lidos">{f.lidos === null ? <Traco /> : f.lidos.toLocaleString("pt-BR")}</td>
                  <td className="num" data-rotulo="Hora">{f.hora ?? <Traco />}</td>
                  <td data-rotulo="Observação">{f.problema || f.aguardando || <Traco />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Rolagem>
      )}
    </section>
  );
}

/** A sessao de uma licitacao, com os dias uteis e a situacao que o servidor leu. */
function Sessao({ l }: { l: LinhaLicitacao }) {
  return l.data_sessao
    ? <span className="lic-prazo"><Prazo p={{ data: l.data_sessao, hora: l.hora_sessao, dias_uteis: l.dias_uteis, passado: l.encerrada, hoje: l.sessao_hoje, situacao: l.prazo }} /></span>
    : <Traco />;
}

function AlertasDoDia({ alertas }: { alertas: AlertaDoDia[] }) {
  const n = alertas.reduce((t, a) => t + a.linhas.length, 0);
  return (
    <section className="cartao lic-bloco" aria-labelledby="lic-alertas">
      <header className="cartao__cabeca">
        <h2 className="cartao__titulo" id="lic-alertas">Alertas do dia</h2>
        <Contador rotulo={contar(n, "licitação", "licitações")}>{n.toLocaleString("pt-BR")}</Contador>
      </header>
      {alertas.length === 0 ? <div className="vazio vazio--curto"><p>Nenhum alerta na última leitura.</p></div> : (
        <Rolagem rotulo="Alertas do dia">
          <table className="tabela lic-tabela lic-tabela--alertas">
            <caption className="sr-only">As licitações que cada regra de alerta pegou na última leitura</caption>
            <thead>
              <tr><th scope="col">Licitação</th><th scope="col" className="col-num">Valor</th><th scope="col">Sessão</th></tr>
            </thead>
            {alertas.map(a => (
              <tbody key={a.regra}>
                <tr className="lic-grupo">
                  <th scope="colgroup" colSpan={3}>
                    <span className="lic-grupo__faixa">
                      <span className="lic-grupo__nome">{a.nome}</span>
                      <Contador rotulo={contar(a.linhas.length, "licitação", "licitações")}>{a.linhas.length.toLocaleString("pt-BR")}</Contador>
                    </span>
                  </th>
                </tr>
                {a.linhas.length === 0
                  ? <tr><td colSpan={3}><Traco /></td></tr>
                  : a.linhas.map(l => (
                    <tr key={`${a.regra}-${l.chave}`}>
                      <th scope="row" className="lic-c-licitacao"><Licitacao l={l} /></th>
                      <td className="col-num lic-c-valor" data-rotulo="Valor"><Valor l={l} /></td>
                      <td data-rotulo="Sessão"><Sessao l={l} /></td>
                    </tr>
                  ))}
              </tbody>
            ))}
          </table>
        </Rolagem>
      )}
    </section>
  );
}

/** Um lado do par: o orgao com o edital e o objeto, o valor e a sessao. */
function Lado({ l, rotulo }: { l: LinhaLicitacao; rotulo: string }) {
  return (
    <td className="lic-lado" data-rotulo={rotulo}>
      <Licitacao l={l} />
      <span className="lic-lado__dados"><Valor l={l} /><Sessao l={l} /></span>
    </td>
  );
}

type Conferir = {
  ocupada: boolean; falha: FalhaDaDecisao | null; respostas: RespostaFontes["respostas"];
  responder: (p: ParParaConferir, r: RespostaDeConferencia) => void; refazer: (p: ParConferido) => void;
};

/** A recusa do servidor junto do par a que se refere (a falha guarda o id do par). */
function RecusaDoPar({ p, conferir }: { p: ParParaConferir; conferir: Conferir | null }) {
  return conferir?.falha?.id === p.id ? <Falha className="lic-falha">{conferir.falha.texto}</Falha> : null;
}

function Conferencia({ pares, conferidos, conferir }: { pares: ParParaConferir[]; conferidos: ParConferido[]; conferir: Conferir | null }) {
  const comDecisao = conferir ? " lic-tabela--decide" : "";
  return (
    <section className="cartao lic-bloco" aria-labelledby="lic-conferencia">
      <header className="cartao__cabeca">
        <h2 className="cartao__titulo" id="lic-conferencia">Conferência</h2>
        <Contador rotulo={contar(pares.length, "par a conferir", "pares a conferir")}>{pares.length.toLocaleString("pt-BR")}</Contador>
      </header>
      {pares.length === 0 ? <div className="vazio vazio--curto"><p>Nenhum par a conferir.</p></div> : (
        <Rolagem rotulo="Pares a conferir">
          <table className={`tabela lic-tabela lic-tabela--pares${comDecisao}`}>
            <caption className="sr-only">Pares que o radar achou parecidos e não conseguiu provar iguais</caption>
            <thead>
              <tr>
                <th scope="col">Motivo</th><th scope="col">Um registro</th><th scope="col">Outro registro</th>
                {conferir && <th scope="col">Decisão</th>}
              </tr>
            </thead>
            <tbody>
              {pares.map(p => (
                <tr key={p.par}>
                  <th scope="row" className="lic-c-motivo">{p.motivo || <Traco />}</th>
                  <Lado l={p.a} rotulo="Um registro" />
                  <Lado l={p.b} rotulo="Outro registro" />
                  {conferir && (
                    <td className="lic-c-decisao">
                      <div className="lic-acoes">
                        {conferir.respostas.map(r => (
                          <button key={r.resposta} type="button" className="btn btn--pequeno" disabled={conferir.ocupada}
                            aria-label={`${r.rotulo}: ${nomeDaLicitacao(p.a)} e ${nomeDaLicitacao(p.b)}`}
                            onClick={() => conferir.responder(p, r.resposta)}>{r.rotulo}</button>
                        ))}
                      </div>
                      <RecusaDoPar p={p} conferir={conferir} />
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </Rolagem>
      )}
      {conferidos.length > 0 && (
        <details className="lic-encerradas lic-conferidos">
          <summary>Respondidos <Contador rotulo={contar(conferidos.length, "par respondido", "pares respondidos")}>{conferidos.length.toLocaleString("pt-BR")}</Contador></summary>
          <Rolagem rotulo="Pares respondidos">
            <table className={`tabela lic-tabela lic-tabela--pares${comDecisao}`}>
              <caption className="sr-only">Pares já respondidos que o radar ainda lista</caption>
              <thead>
                <tr>
                  <th scope="col">Resposta</th><th scope="col">Um registro</th><th scope="col">Outro registro</th>
                  {conferir && <th scope="col">Decisão</th>}
                </tr>
              </thead>
              <tbody>
                {conferidos.map(p => (
                  <tr key={p.par}>
                    <th scope="row" className="lic-c-motivo">
                      <Selo>{p.resposta_rotulo}</Selo>
                      <span className="lic-sub">{p.quem ? `${p.quem} · ` : ""}<span className="num">{fmtData(p.quando)}</span></span>
                    </th>
                    <Lado l={p.a} rotulo="Um registro" />
                    <Lado l={p.b} rotulo="Outro registro" />
                    {conferir && (
                      <td className="lic-c-decisao">
                        <div className="lic-acoes">
                          <button type="button" className="btn btn--pequeno" disabled={conferir.ocupada}
                            aria-label={`Refazer: ${nomeDaLicitacao(p.a)} e ${nomeDaLicitacao(p.b)}`}
                            onClick={() => conferir.refazer(p)}>Refazer</button>
                        </div>
                        <RecusaDoPar p={p} conferir={conferir} />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </Rolagem>
        </details>
      )}
    </section>
  );
}

export default function LicitacoesFontes() {
  const { dados, erro, tentar } = useLicitacoes<RespostaFontes>("/api/licitacoes/fontes");
  const { ocupada, falha, decidir } = useDecisoes(tentar);
  if (!dados) return <SemLeitura erro={erro} tentar={() => void tentar()} />;

  // a decisao vai ao par pelo id dele (POST /api/licitacoes/pares/{id}/conferencia); o nome, para a recusa
  const doPar = (p: ParParaConferir) => ({ ...p.a, id: p.id });
  const conferir: Conferir | null = dados.pode_decidir ? {
    ocupada, falha, respostas: dados.respostas,
    responder: (p, resposta) => void decidir(doPar(p), "conferencia", { resposta }, "pares"),
    refazer: p => void decidir(doPar(p), "conferencia/desfazer", {}, "pares"),
  } : null;
  const nomes = [...dados.pares, ...dados.conferidos];
  return (
    <div className="pagina lic">
      <LeituraDoRadarLinha leitura={dados.leitura} />
      <FalhaAoAtualizar erro={erro} tentar={() => void tentar()} />
      {/* a recusa de um par que ja' saiu da pagina (o radar o resolveu, outra pessoa respondeu) */}
      {falha && !nomes.some(p => p.id === falha.id) && <Falha>{falha.texto}</Falha>}
      <SituacaoDasFontes fontes={dados.fontes} />
      <AlertasDoDia alertas={dados.alertas} />
      <Conferencia pares={dados.pares} conferidos={dados.conferidos} conferir={conferir} />
    </div>
  );
}
