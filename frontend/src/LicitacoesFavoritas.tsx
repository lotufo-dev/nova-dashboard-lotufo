import { useRef, useState } from "react";
import Contador from "./Contador";
import Falha from "./Falha";
import { contar } from "./formato";
import {
  nomeDaLicitacao, useDecisoes, useLicitacoes,
  type EtapaDaFavorita, type FalhaDaDecisao, type LinhaLicitacao, type RespostaFavoritas,
} from "./licitacoes";
import LicitacoesCalendario from "./LicitacoesCalendario";
import {
  AbasDasFavoritas, Etapa, FalhaAoAtualizar, JanelaDeTirarAFavorita, LeituraDoRadarLinha, Licitacao, Mudanca, Prazo, RecusaSemLinha,
  SemLeitura, Traco, Valor,
} from "./LicitacoesPecas";
import LicitacoesQuadro from "./LicitacoesQuadro";
import Rolagem from "./Rolagem";
import type { Busca, VistaFavoritas } from "./rota";
import Selo from "./Selo";

// FAVORITAS (#908 e fatia 2 da #906, docs/adr/0018): "/licitacoes/favoritas". Responde "em que etapa esta' cada uma e o
// que vence", em tres vistas com endereco proprio: a lista (a padrao), o quadro por etapa ("/quadro",
// LicitacoesQuadro.tsx) e o calendario dos prazos ("/calendario", LicitacoesCalendario.tsx).
//
// A lista e o quadro leem GET /api/licitacoes/favoritas, que manda tudo pronto: a ordem (as em aberto primeiro, pela
// sessao; as encerradas no fim), a etapa com o rotulo, os dias uteis e a situacao de cada prazo, e as etapas na ordem.
//
// AS DECISOES (fatia 2), so' na lista e so' com `pode_decidir` (depois do corte, a quem decide): a etapa da favorita
// sem etapa de dossie troca num controle de escolha, com as etapas que o servidor manda, e grava no botao Gravar que
// aparece ao lado quando a escolha muda; a que tem etapa de dossie so' mostra, e diz que vem do dossie. Tirar a favorita
// pede confirmacao. Depois de cada decisao a pagina le a rota de novo. Uma decisao por vez na pagina.
//
// As encerradas ficam num grupo recolhido no fim, como os encerrados do SIGA: nao tem prazo correndo, e a pagina
// responde o que vence. Nelas o prazo e' so' o nome e a data, sem os dias e sem cor (o servidor ja' manda sem situacao).

/** Quantas mudancas a linha mostra; o resto vira a contagem ("e mais 2"). */
const MUDANCAS_A_VISTA = 3;

/** O que as linhas precisam para decidir; nulo quando a pagina e' so' de leitura. `ocupada`: ha' decisao em curso.
 *  `mudarEtapa` devolve se gravou. */
type Decisoes = {
  etapas: EtapaDaFavorita[]; ocupada: boolean; falha: FalhaDaDecisao | null;
  mudarEtapa: (l: LinhaLicitacao, etapa: string) => Promise<boolean>; tirar: (l: LinhaLicitacao) => void;
};

/** A etapa na lista de quem decide: o controle de escolha na favorita sem etapa de dossie; na que tem, o selo e de onde
 *  ela vem. O que o dossie diz alem da etapa continua ao lado.
 *
 *  A escolha nao grava sozinha: pelo teclado o controle fechado muda a cada seta, e cada passagem viraria uma etapa
 *  gravada que ninguem escolheu. A etapa escolhida fica no controle e o botao Gravar aparece ao lado enquanto ela for
 *  outra que a do servidor; o controle nao desliga enquanto grava, para o foco nao cair. */
function EtapaQueSeDecide({ l, decisoes }: { l: LinhaLicitacao; decisoes: Decisoes }) {
  const [escolhida, setEscolhida] = useState<string | null>(null);
  const controle = useRef<HTMLSelectElement>(null);
  const f = l.favorita;
  if (!f) return null;
  if (f.etapa_do_dossie) return <><Etapa f={f} /><span className="lic-sub">do dossiê</span></>;
  const nome = nomeDaLicitacao(l);
  const gravar = (etapa: string) => void decisoes.mudarEtapa(l, etapa).then(gravou => {
    if (gravou) setEscolhida(null);
    controle.current?.focus();                       // o botao some (ou desliga): o foco volta para o controle
  });
  return (
    <span className="lic-etapa">
      <select ref={controle} className="lic-etapa__escolha" aria-label={`Etapa: ${nome}`} value={escolhida ?? f.etapa}
        onChange={ev => setEscolhida(ev.target.value)}>
        {decisoes.etapas.map(e => <option key={e.etapa} value={e.etapa}>{e.rotulo}</option>)}
      </select>
      {escolhida !== null && escolhida !== f.etapa && (
        <button type="button" className="btn btn--pequeno" disabled={decisoes.ocupada} aria-label={`Gravar a etapa: ${nome}`}
          onClick={() => gravar(escolhida)}>Gravar</button>
      )}
      {f.selos.map((s, i) => <Selo key={`${i}-${s}`}>{s}</Selo>)}
    </span>
  );
}

function Tabela({ linhas, legenda, encerradas = false, decisoes }: {
  linhas: LinhaLicitacao[]; legenda: string; encerradas?: boolean; decisoes: Decisoes | null;
}) {
  return (
    <Rolagem rotulo={legenda}>
      <table className={`tabela lic-tabela${decisoes ? " lic-tabela--decide" : ""}`}>
        <caption className="sr-only">{legenda}</caption>
        <thead>
          <tr>
            <th scope="col">Licitação</th><th scope="col">Etapa</th><th scope="col">Prazos</th>
            <th scope="col" className="col-num">Valor</th><th scope="col">Mudanças</th>
            {decisoes && <th scope="col">Decisão</th>}
          </tr>
        </thead>
        <tbody>
          {linhas.map(l => {
            const f = l.favorita;
            if (!f) return null;
            const resto = f.mudancas.length - MUDANCAS_A_VISTA;
            return (
              <tr key={l.chave}>
                <th scope="row" className="lic-c-licitacao"><Licitacao l={l} /></th>
                <td data-rotulo="Etapa">{decisoes ? <EtapaQueSeDecide l={l} decisoes={decisoes} /> : <Etapa f={f} />}</td>
                <td data-rotulo="Prazos">
                  {f.prazos.length === 0 ? <Traco /> : (
                    <ul className="lic-prazos">
                      {f.prazos.map((p, i) => <li key={`${i}-${p.codigo}-${p.data}`} className="lic-prazo"><Prazo p={p} corre={!encerradas} /></li>)}
                    </ul>
                  )}
                </td>
                <td className="col-num lic-c-valor" data-rotulo="Valor"><Valor l={l} /></td>
                <td data-rotulo="Mudanças">
                  {f.mudancas.length === 0 ? <Traco /> : (
                    <ul className="lic-mudancas">
                      {f.mudancas.slice(0, MUDANCAS_A_VISTA).map((m, i) => <li key={`${m.data}-${i}`}><Mudanca m={m} /></li>)}
                      {resto > 0 && <li className="lic-fraco">e mais {resto.toLocaleString("pt-BR")}</li>}
                    </ul>
                  )}
                </td>
                {decisoes && (
                  <td className="lic-c-decisao">
                    <div className="lic-acoes">
                      <button type="button" className="btn btn--pequeno" disabled={decisoes.ocupada}
                        aria-label={`Tirar a favorita: ${nomeDaLicitacao(l)}`} onClick={() => decisoes.tirar(l)}>Tirar a favorita</button>
                    </div>
                    {decisoes.falha?.id === l.id && <Falha className="lic-falha">{decisoes.falha.texto}</Falha>}
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </Rolagem>
  );
}

function Lista({ dados, decisoes }: { dados: RespostaFavoritas; decisoes: Decisoes | null }) {
  const abertas = dados.favoritas.filter(l => !l.encerrada);
  const encerradas = dados.favoritas.filter(l => l.encerrada);
  return (
    <>
      {/* o nome da pagina ja' esta' no alto: o painel nao o repete como titulo */}
      <section className="cartao lic-bloco" aria-label="Favoritas em aberto">
        {abertas.length === 0
          ? <div className="vazio vazio--curto"><p>{encerradas.length === 0 ? "Nenhuma favorita." : "Nenhuma favorita em aberto."}</p></div>
          : <Tabela linhas={abertas} legenda="Favoritas em aberto" decisoes={decisoes} />}
      </section>
      {encerradas.length > 0 && (
        <details className="lic-encerradas">
          <summary>Encerradas <Contador rotulo={contar(encerradas.length, "favorita encerrada", "favoritas encerradas")}>{encerradas.length.toLocaleString("pt-BR")}</Contador></summary>
          <section className="cartao lic-bloco" aria-label="Favoritas encerradas">
            <Tabela linhas={encerradas} legenda="Favoritas encerradas" encerradas decisoes={decisoes} />
          </section>
        </details>
      )}
    </>
  );
}

/** A lista e o quadro: os mesmos dados, uma leitura so' (trocar de uma vista para a outra nao le de novo). */
function ListaOuQuadro({ vista }: { vista: "lista" | "quadro" }) {
  const { dados, erro, tentar } = useLicitacoes<RespostaFavoritas>("/api/licitacoes/favoritas");
  const { ocupada, falha, decidir, limparFalha } = useDecisoes(tentar);
  const [tirar, setTirar] = useState<LinhaLicitacao | null>(null);
  if (!dados) return <SemLeitura erro={erro} tentar={() => void tentar()}><AbasDasFavoritas atual={vista} /></SemLeitura>;

  const decisoes: Decisoes | null = dados.pode_decidir ? {
    // a recusa de tirar a favorita aparece dentro da janela, e nao na linha
    etapas: dados.etapas, ocupada, falha: tirar ? null : falha,
    mudarEtapa: (l, etapa) => decidir(l, "etapa", { etapa }).then(resposta => resposta !== null),
    tirar: l => { limparFalha(); setTirar(l); },
  } : null;
  return (
    <div className="pagina lic">
      <AbasDasFavoritas atual={vista} />
      <LeituraDoRadarLinha leitura={dados.leitura} />
      <FalhaAoAtualizar erro={erro} tentar={() => void tentar()} />
      <RecusaSemLinha falha={decisoes?.falha ?? null} linhas={dados.favoritas} />
      {vista === "quadro" ? <LicitacoesQuadro dados={dados} /> : <Lista dados={dados} decisoes={decisoes} />}
      {tirar && (
        <JanelaDeTirarAFavorita l={tirar} ocupada={ocupada} falha={falha?.id === tirar.id ? falha.texto : null}
          aoConfirmar={() => void decidir(tirar, "favorita/remover").then(feito => { if (feito) setTirar(null); })}
          aoFechar={() => { limparFalha(); setTirar(null); }} />
      )}
    </div>
  );
}

export default function LicitacoesFavoritas({ vista = "lista", busca = {} }: { vista?: VistaFavoritas; busca?: Busca }) {
  return vista === "calendario" ? <LicitacoesCalendario busca={busca} /> : <ListaOuQuadro vista={vista} />;
}
