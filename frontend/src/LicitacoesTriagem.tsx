import { useState } from "react";
import Contador from "./Contador";
import Falha from "./Falha";
import { contar } from "./formato";
import {
  fmtKm, nomeDaLicitacao, useDecisoes, useLicitacoes,
  type AnaliseDoEdital, type FalhaDaDecisao, type Favorita, type LinhaLicitacao, type Recomendada, type RespostaTriagem,
} from "./licitacoes";
import {
  Etapa, FalhaAoAtualizar, JanelaDaAnalise, JanelaDoDescarte, LeituraDoRadarLinha, Licitacao, Mudanca, Prazo, SemLeitura, Traco, Valor,
} from "./LicitacoesPecas";
import { Link } from "./Link";
import Rolagem from "./Rolagem";
import { Glifo } from "./Selo";
import type { Situacao } from "./situacao";
import { fmtDiaNoAno } from "./tempo";

// TRIAGEM (#908 e fatia 2 da #906, docs/adr/0018): a pagina padrao da area Licitacoes ("/licitacoes"). Responde "o que
// pede decisao agora": as favoritas com prazo chegando ou mudanca que ninguem viu e as recomendadas que ainda nao tem
// decisao. E' a fila que esvazia: decidiu, a linha sai.
//
// Tudo vem pronto de GET /api/licitacoes/triagem: as contagens do alto, as duas listas ja' na ordem, os dias uteis ate'
// cada prazo e a situacao dele. A tela nao conta, nao ordena e nao compara data com limite.
//
// AS DECISOES (fatia 2): so' com `pode_decidir`, que o servidor manda depois do corte e a quem decide; antes dele as
// decisoes sao espelho do radar e a pagina nao tem botao. Na recomendada: Favoritar (a acao principal da linha), Analisar
// o edital (favorita e devolve o comando para a sessao de analise) e Descartar (com o motivo). Na favorita com mudanca
// nao vista: Marcar como vista, que manda as chaves das mudancas que a linha mostrou (a que chegar depois continua nao
// vista). Depois de cada decisao a pagina le a rota de novo: a linha sai pelo que o servidor diz, e nao por conta da
// tela. A recusa do servidor aparece junto da linha, ou dentro da janela aberta.
//
// A MUDANCA DA LINHA: depois do corte, as que ninguem viu (todas: sao elas que poem a favorita aqui, e a mais recente
// pode ja' estar vista); sem nenhuma, a mais recente, na letra de apoio. Antes do corte ninguem marca nada: a mais
// recente, como na fatia 1.
//
// Os numeros do alto e os titulos dos blocos tem o mesmo rotulo quando sao a mesma conta ("Recomendadas a decidir"). O
// bloco das favoritas tem outro titulo que o numero "Favoritas": o numero conta todas as favoritas (e e' a porta para a
// pagina delas); o bloco lista so' as que pedem atencao.
//
// O motivo da recomendacao vai sob o objeto, e nao numa coluna: com ele em coluna as sete nao cabiam em 792 px (1024 com
// o menu aberto), e ele e' uma frase, nao um valor que se compara entre linhas.

/** O que as linhas precisam para decidir; nulo quando a pagina e' so' de leitura. */
type Decisoes = {
  ocupada: number | null; falha: FalhaDaDecisao | null;
  favoritar: (l: LinhaLicitacao) => void; analisar: (l: LinhaLicitacao) => void; descartar: (l: LinhaLicitacao) => void;
  marcarVista: (l: LinhaLicitacao) => void;
};

/** Um numero da faixa: o rotulo (com o simbolo da situacao, so' quando ha' o que contar), o numero em tinta e o apoio. */
function Numero({ rotulo, situacao, apoio, children }: {
  rotulo: string; situacao?: Situacao; apoio?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="lic-numero">
      <dt>{situacao && <Glifo situacao={situacao} />}{rotulo}</dt>
      <dd className="lic-numero__valor">{children}</dd>
      {apoio && <dd className="lic-numero__apoio">{apoio}</dd>}
    </div>
  );
}

/** O local da obra da recomendada: a cidade e a distancia que o radar mandou com a recomendacao (o municipio do orgao
 *  ou, na obra do Estado e da Uniao, o que o objeto cita). E' por ele que o servidor ordena, e nao pela cidade e pela
 *  distancia da licitacao. Sem cidade e sem distancia, o traco. */
function Local({ rec }: { rec: Recomendada }) {
  const km = fmtKm(rec.km);
  if (!rec.cidade && !km) return <Traco />;
  return <>{rec.cidade && <span className="lic-cidade">{rec.cidade}</span>}{km && <span className="num lic-km">{km}</span>}</>;
}

/** A celula das decisoes de uma linha: os botoes e, embaixo, a recusa do servidor para esta licitacao. */
function CelulaDeDecisao({ l, falha, children }: { l: LinhaLicitacao; falha: FalhaDaDecisao | null; children?: React.ReactNode }) {
  return (
    <td className="lic-c-decisao">
      {children && <div className="lic-acoes">{children}</div>}
      {falha?.id === l.id && <Falha className="lic-falha">{falha.texto}</Falha>}
    </td>
  );
}

/** A mudanca da favorita na Triagem: depois do corte, as que ninguem viu; sem nenhuma (ou antes do corte), a mais
 *  recente. */
function MudancaDaLinha({ f, cortado }: { f: Favorita; cortado: boolean }) {
  const novas = cortado ? f.mudancas.filter(m => !m.vista) : [];
  if (novas.length > 1) return <ul className="lic-mudancas">{novas.map(m => <li key={m.chave}><Mudanca m={m} /></li>)}</ul>;
  const mostrada = novas[0] ?? f.mudancas[0];
  return mostrada ? <Mudanca m={mostrada} /> : <Traco />;
}

function FavoritasQuePedemAtencao({ linhas, decisoes, cortado }: { linhas: LinhaLicitacao[]; decisoes: Decisoes | null; cortado: boolean }) {
  // a coluna das decisoes so' existe quando alguma linha tem o que decidir: a mudanca que ninguem viu
  const comDecisao = decisoes !== null && linhas.some(l => (l.favorita?.mudancas_novas ?? 0) > 0);
  return (
    <section className="cartao lic-bloco" aria-labelledby="lic-atencao">
      <header className="cartao__cabeca">
        <h2 className="cartao__titulo" id="lic-atencao">Favoritas que pedem atenção</h2>
        <Contador rotulo={contar(linhas.length, "favorita", "favoritas")}>{linhas.length.toLocaleString("pt-BR")}</Contador>
      </header>
      {linhas.length === 0 ? <div className="vazio vazio--curto"><p>Nenhuma favorita pede atenção.</p></div> : (
        <Rolagem rotulo="Favoritas que pedem atenção">
          <table className={`tabela lic-tabela${comDecisao ? " lic-tabela--decide" : ""}`}>
            <caption className="sr-only">Favoritas com prazo chegando ou mudança recente, do prazo mais próximo ao mais distante</caption>
            <thead>
              <tr>
                <th scope="col">Licitação</th><th scope="col">Etapa</th><th scope="col">Próximo prazo</th><th scope="col">Mudança</th>
                {comDecisao && <th scope="col">Decisão</th>}
              </tr>
            </thead>
            <tbody>
              {linhas.map(l => {
                const f = l.favorita;
                if (!f) return null;
                return (
                  <tr key={l.chave}>
                    <th scope="row" className="lic-c-licitacao"><Licitacao l={l} /></th>
                    <td data-rotulo="Etapa"><Etapa f={f} /></td>
                    <td data-rotulo="Próximo prazo">{f.proximo_prazo ? <span className="lic-prazo"><Prazo p={f.proximo_prazo} /></span> : <Traco />}</td>
                    <td data-rotulo="Mudança"><MudancaDaLinha f={f} cortado={cortado} /></td>
                    {comDecisao && decisoes && (
                      <CelulaDeDecisao l={l} falha={decisoes.falha}>
                        {f.mudancas_novas > 0 && (
                          <button type="button" className="btn btn--pequeno" disabled={decisoes.ocupada === l.id}
                            aria-label={`${f.mudancas_novas === 1 ? "Marcar como vista" : "Marcar como vistas"}: ${nomeDaLicitacao(l)}`}
                            onClick={() => decisoes.marcarVista(l)}>
                            {f.mudancas_novas === 1 ? "Marcar como vista" : "Marcar como vistas"}
                          </button>
                        )}
                      </CelulaDeDecisao>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Rolagem>
      )}
    </section>
  );
}

function RecomendadasADecidir({ linhas, decisoes }: { linhas: LinhaLicitacao[]; decisoes: Decisoes | null }) {
  return (
    <section className="cartao lic-bloco" aria-labelledby="lic-recomendadas">
      <header className="cartao__cabeca">
        <h2 className="cartao__titulo" id="lic-recomendadas">Recomendadas a decidir</h2>
        <Contador rotulo={contar(linhas.length, "recomendada", "recomendadas")}>{linhas.length.toLocaleString("pt-BR")}</Contador>
      </header>
      {linhas.length === 0 ? <div className="vazio vazio--curto"><p>Nenhuma recomendada a decidir.</p></div> : (
        <Rolagem rotulo="Recomendadas a decidir">
          <table className={`tabela lic-tabela lic-tabela--nota${decisoes ? " lic-tabela--decide" : ""}`}>
            <caption className="sr-only">Recomendadas ainda sem decisão, da nota maior para a menor</caption>
            <thead>
              <tr>
                <th scope="col" className="col-num">Nota</th><th scope="col">Licitação</th><th scope="col">Tipo de obra</th>
                <th scope="col">Local</th><th scope="col" className="col-num">Valor</th><th scope="col">Sessão</th>
                {decisoes && <th scope="col">Decisão</th>}
              </tr>
            </thead>
            <tbody>
              {linhas.map(l => {
                const rec = l.recomendada;
                if (!rec) return null;
                const nome = nomeDaLicitacao(l);
                return (
                  <tr key={l.chave}>
                    <td className="col-num lic-c-nota" data-rotulo="Nota">{rec.nota.toLocaleString("pt-BR")}</td>
                    <th scope="row" className="lic-c-licitacao">
                      <Licitacao l={l}>
                        {rec.motivo && <span className="lic-sub"><span className="sr-only">Motivo: </span>{rec.motivo}</span>}
                      </Licitacao>
                    </th>
                    <td data-rotulo="Tipo de obra">{l.tipo_obra || <Traco />}</td>
                    <td data-rotulo="Local"><Local rec={rec} /></td>
                    <td className="col-num lic-c-valor" data-rotulo="Valor"><Valor l={l} /></td>
                    <td data-rotulo="Sessão">
                      {l.data_sessao
                        ? <span className="lic-prazo"><Prazo p={{ data: l.data_sessao, hora: l.hora_sessao, dias_uteis: l.dias_uteis, passado: l.encerrada, hoje: l.sessao_hoje, situacao: l.prazo }} /></span>
                        : <Traco />}
                    </td>
                    {decisoes && (
                      <CelulaDeDecisao l={l} falha={decisoes.falha}>
                        <button type="button" className="btn btn--pequeno btn--primario" disabled={decisoes.ocupada === l.id}
                          aria-label={`Favoritar: ${nome}`} onClick={() => decisoes.favoritar(l)}>Favoritar</button>
                        <button type="button" className="btn btn--pequeno" disabled={decisoes.ocupada === l.id}
                          aria-label={`Analisar o edital: ${nome}`} onClick={() => decisoes.analisar(l)}>Analisar o edital</button>
                        <button type="button" className="btn btn--pequeno" disabled={decisoes.ocupada === l.id}
                          aria-label={`Descartar: ${nome}`} onClick={() => decisoes.descartar(l)}>Descartar</button>
                      </CelulaDeDecisao>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Rolagem>
      )}
    </section>
  );
}

export default function LicitacoesTriagem() {
  const { dados, erro, tentar } = useLicitacoes<RespostaTriagem>("/api/licitacoes/triagem");
  const { ocupada, falha, decidir, limparFalha } = useDecisoes(tentar);
  // as janelas guardam a licitacao: a linha dela sai da lista quando a leitura nova chega, e a janela continua aberta
  const [descarte, setDescarte] = useState<LinhaLicitacao | null>(null);
  const [analise, setAnalise] = useState<{ l: LinhaLicitacao; resposta: AnaliseDoEdital } | null>(null);
  if (!dados) return <SemLeitura erro={erro} tentar={() => void tentar()} />;

  const decisoes: Decisoes | null = dados.pode_decidir ? {
    // a recusa do descarte aparece dentro da janela dele, e nao na linha
    ocupada, falha: descarte ? null : falha,
    favoritar: l => void decidir(l.id, "favorita"),
    analisar: l => void decidir<AnaliseDoEdital>(l.id, "analise").then(resposta => { if (resposta) setAnalise({ l, resposta }); }),
    descartar: l => { limparFalha(); setDescarte(l); },
    // as mudancas nao vistas que a linha mostrou: a que o radar trouxer depois desta leitura continua nao vista
    marcarVista: l => void decidir(l.id, "mudancas-vistas", { chaves: (l.favorita?.mudancas ?? []).filter(m => !m.vista).map(m => m.chave) }),
  } : null;

  const c = dados.contagens;
  const desde = c.novas_desde ? fmtDiaNoAno(c.novas_desde.desde) : null;
  return (
    <div className="pagina lic">
      <dl className="lic-numeros" aria-label="Licitações na triagem">
        <Numero rotulo="Recomendadas a decidir">{c.recomendadas.toLocaleString("pt-BR")}</Numero>
        {/* o numero e' a porta para a pagina das favoritas, e continua com cara de numero */}
        <Numero rotulo="Favoritas">
          <Link className="lic-porta" para={{ tela: "licitacoes-favoritas" }}>{c.favoritas.toLocaleString("pt-BR")}</Link>
        </Numero>
        <Numero rotulo="Novas"
          apoio={c.novas_desde && desde && <span className="num">+{c.novas_desde.quantas.toLocaleString("pt-BR")} desde {desde}</span>}>
          {c.novas.toLocaleString("pt-BR")}
        </Numero>
        {dados.leitura.fontes_com_problema > 0 && (
          <Numero rotulo="Fontes com problema" situacao="breve">{dados.leitura.fontes_com_problema.toLocaleString("pt-BR")}</Numero>
        )}
      </dl>
      {c.por_orgao.length > 0 && (
        <div className="lic-orgaos">
          <span className="lic-orgaos__rotulo" id="lic-por-orgao">Novas por órgão</span>
          <ul aria-labelledby="lic-por-orgao">
            {c.por_orgao.map(o => (
              <li key={o.orgao}>{o.orgao} <Contador rotulo={contar(o.novas, "nova", "novas")}>{o.novas.toLocaleString("pt-BR")}</Contador></li>
            ))}
          </ul>
        </div>
      )}
      <LeituraDoRadarLinha leitura={dados.leitura} />
      <FalhaAoAtualizar erro={erro} tentar={() => void tentar()} />
      <FavoritasQuePedemAtencao linhas={dados.favoritas} decisoes={decisoes} cortado={dados.decisoes === "dashboard"} />
      <RecomendadasADecidir linhas={dados.recomendadas} decisoes={decisoes} />
      {descarte && (
        <JanelaDoDescarte l={descarte} motivos={dados.motivos_descarte} ocupada={ocupada === descarte.id}
          falha={falha?.id === descarte.id ? falha.texto : null}
          aoDescartar={motivo => void decidir(descarte.id, "descarte", { motivo }).then(feito => { if (feito) setDescarte(null); })}
          aoFechar={() => { limparFalha(); setDescarte(null); }} />
      )}
      {analise && <JanelaDaAnalise l={analise.l} analise={analise.resposta} aoFechar={() => setAnalise(null)} />}
    </div>
  );
}
