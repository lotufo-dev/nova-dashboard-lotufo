import { useState } from "react";
import { comPontoFinal } from "./api";
import CaixaAviso from "./CaixaAviso";
import Falha from "./Falha";
import { brl } from "./formato";
import { IconeLinkExterno } from "./icones";
import Janela from "./Janela";
import {
  avisoDaLeitura, copiarTexto, dataDoPrazo, emDiasUteis, linkExterno, nomeDaLicitacao, orgaoDaLinha, quandoLeu,
  type AnaliseDoEdital, type Favorita, type LeituraDoRadar, type LinhaLicitacao, type MotivoDeDescarte, type MudancaDaFavorita,
  type SituacaoDoPrazo,
} from "./licitacoes";
import { VISTAS_DAS_FAVORITAS } from "./navegacao";
import type { VistaFavoritas } from "./rota";
import Selo, { Glifo } from "./Selo";
import { fmtDiaNoAno } from "./tempo";
import { Abas } from "./Topo";
import "./licitacoes.css";

// As pecas que a Triagem e as Favoritas (#908 e fatia 2 da #906) dividem: a linha da leitura do radar, as celulas da
// licitacao (o orgao com o edital e o objeto, a etapa, o prazo, o valor, a mudanca), as abas das Favoritas e as janelas
// das decisoes. Tudo o que e' limite, situacao ou ordem vem do servidor; aqui so' se desenha.

/** No lugar da pagina enquanto a leitura nao chega: "Carregando…" ou a falha, com o botao de tentar de novo.
 *  `children`: o que a pagina mostra mesmo sem a leitura (as abas das Favoritas). */
export function SemLeitura({ erro, tentar, children }: { erro: string; tentar: () => void; children?: React.ReactNode }) {
  return (
    <div className="pagina lic">
      {children}
      {erro
        ? <div className="form-inline"><Falha>Não foi possível ler as licitações: {erro}</Falha>
            <button type="button" className="btn btn--pequeno" onClick={tentar}>Tentar de novo</button></div>
        : <p className="campo__nota" role="status">Carregando as licitações…</p>}
    </div>
  );
}

/** Quando o radar leu. Com a leitura atrasada (ou sem leitura nenhuma), o aviso no lugar, como o do monitor do SIGA. */
export function LeituraDoRadarLinha({ leitura }: { leitura: LeituraDoRadar }) {
  return (
    <div className="lic-leitura">
      {leitura.atrasada
        ? <CaixaAviso nivel="atencao" role="status">{avisoDaLeitura(leitura)}</CaixaAviso>
        : leitura.lido_em && <p className="lic-lido">Última leitura do radar: <span className="num">{quandoLeu(leitura.lido_em)}</span></p>}
    </div>
  );
}

/** O orgao e o edital (link para o endereco do edital, em outra aba, quando ha') e, embaixo, o objeto. `children`: o
 *  que a tabela acrescenta sob o objeto (o motivo da recomendacao). */
export function Licitacao({ l, children }: {
  l: Pick<LinhaLicitacao, "orgao" | "sigla_orgao" | "edital" | "modalidade" | "link" | "objeto">; children?: React.ReactNode;
}) {
  const href = linkExterno(l.link);
  const edital = l.edital || l.modalidade || (href ? "Edital" : "");
  // o icone anda junto com o fim do numero (nunca sozinho na linha de baixo); o comeco quebra onde precisar
  const fim = edital.lastIndexOf(" ") + 1;
  return (
    <>
      <span className="lic-nome">
        {orgaoDaLinha(l)}
        {edital && " · "}
        {edital && (href
          ? <a className="lic-edital" href={href} target="_blank" rel="noopener noreferrer">
              {edital.slice(0, fim)}<span className="lic-edital__fim">{edital.slice(fim)}<IconeLinkExterno className="icone icone--p" /></span>
              <span className="sr-only"> (abre em outra aba)</span>
            </a>
          : edital)}
      </span>
      {l.objeto && <span className="lic-sub">{l.objeto}</span>}
      {children}
    </>
  );
}

/** A etapa da favorita, com o rotulo que o servidor manda, e o que o dossie diz alem dela. Etapa nao e' situacao: selo
 *  neutro, sem glifo. */
export function Etapa({ f }: { f: Favorita }) {
  return (
    <span className="lic-etapa">
      <Selo>{f.etapa_rotulo}</Selo>
      {f.selos.map((s, i) => <Selo key={`${i}-${s}`}>{s}</Selo>)}
    </span>
  );
}

type PrazoNaTela = {
  rotulo?: string; data: string; hora: string | null; dias_uteis: number | null; passado: boolean; hoje: boolean;
  situacao: SituacaoDoPrazo; aviso?: string;
};

/** Um prazo: o nome, a data com a hora e os dias uteis que faltam, no selo da situacao que o servidor leu (sem
 *  situacao, so' o texto). O prazo que passou (`passado`, do servidor) fica so' com o nome e a data. `corre`: falso na
 *  licitacao encerrada, que nao tem prazo correndo: tambem so' o nome e a data. */
export function Prazo({ p, corre = true }: { p: PrazoNaTela; corre?: boolean }) {
  const dias = corre && !p.passado ? emDiasUteis(p.dias_uteis, p.hoje) : null;
  return (
    <>
      {p.rotulo && <span className="lic-prazo__rotulo">{p.rotulo}</span>}
      <span className="num lic-prazo__data">{dataDoPrazo(p.data, p.hora)}</span>
      {dias && (p.situacao
        ? <Selo situacao={p.situacao} className="lic-dias">{dias}</Selo>
        : <span className="lic-prazo__dias">{dias}</span>)}
      {p.aviso && <span className="lic-prazo__aviso">{corre && !p.passado && <Glifo situacao="breve" />}{p.aviso}</span>}
    </>
  );
}

/** O valor estimado, pelos centavos; sem valor, o que o radar diz no lugar ("sigiloso", "sem valor") ou o traco. Com
 *  valor, o rotulo diz de onde ele veio. */
export function Valor({ l }: { l: LinhaLicitacao }) {
  if (l.valor_centavos === null) return <span className="lic-sem-valor">{l.valor_rotulo || "—"}</span>;
  return <>{brl(l.valor_centavos)}{l.valor_rotulo && <span className="lic-sub">{l.valor_rotulo}</span>}</>;
}

/** Uma mudanca da favorita: o rotulo que o radar deu e o dia. A que ja' foi marcada como vista (`vista`, do servidor)
 *  fica na letra de apoio. */
export function Mudanca({ m }: { m: MudancaDaFavorita }) {
  const texto = <>{m.rotulo} <span className="num lic-fraco">{fmtDiaNoAno(m.data) ?? m.data}</span></>;
  return m.vista ? <span className="lic-fraco">{texto}<span className="sr-only"> (vista)</span></span> : texto;
}

/** A leitura que nao chegou depois de uma decisao: a pagina continua com o que tinha, e diz isso. */
export function FalhaAoAtualizar({ erro, tentar }: { erro: string; tentar: () => void }) {
  if (!erro) return null;
  return (
    <div className="form-inline"><Falha>Não foi possível atualizar as licitações: {erro}</Falha>
      <button type="button" className="btn btn--pequeno" onClick={tentar}>Tentar de novo</button></div>
  );
}

/* ------------------------------------------------------------------ Favoritas: as tres vistas */

const VISTAS: readonly VistaFavoritas[] = ["lista", "quadro", "calendario"];

/** As tres vistas das Favoritas (fatia 2 da #906), cada uma no proprio endereco; a lista e' a padrao. */
export function AbasDasFavoritas({ atual }: { atual: VistaFavoritas }) {
  return (
    <Abas rotulo="Vistas das Favoritas" atual={atual} itens={VISTAS.map(v => ({
      id: v, rotulo: VISTAS_DAS_FAVORITAS[v], para: v === "lista" ? { tela: "licitacoes-favoritas" } : { tela: "licitacoes-favoritas", vista: v } }))} />
  );
}

/* ------------------------------------------------------------------ as janelas das decisoes */

/** A licitacao de que a janela trata: o orgao com o edital e, embaixo, o objeto. */
function DaJanela({ l }: { l: LinhaLicitacao }) {
  return (
    <p className="lic-janela__nome">
      <span className="lic-nome">{nomeDaLicitacao(l)}</span>{l.objeto && <span className="lic-sub">{l.objeto}</span>}
    </p>
  );
}

/** Descartar uma recomendada: o motivo, entre os que o servidor manda. A recusa (motivo em branco, licitacao que virou
 *  favorita) aparece aqui, nas palavras do servidor. */
export function JanelaDoDescarte({ l, motivos, ocupada, falha, aoDescartar, aoFechar }: {
  l: LinhaLicitacao; motivos: MotivoDeDescarte[]; ocupada: boolean; falha: string | null;
  aoDescartar: (motivo: string) => void; aoFechar: () => void;
}) {
  const [motivo, setMotivo] = useState("");
  return (
    <Janela titulo="Descartar a licitação" aoFechar={aoFechar}>
      <form className="pilha" onSubmit={ev => { ev.preventDefault(); aoDescartar(motivo); }}>
        <DaJanela l={l} />
        <fieldset className="opcoes">
          <legend className="campo__rotulo">Motivo</legend>
          {motivos.map(m => (
            <label key={m.motivo} className="campo--linha">
              <input type="radio" name="lic-motivo" checked={motivo === m.motivo} onChange={() => setMotivo(m.motivo)} /> {m.rotulo}
            </label>
          ))}
        </fieldset>
        {falha && <Falha>{falha}</Falha>}
        <div className="iniciar__rodape">
          <button type="submit" className="btn btn--primario" disabled={ocupada}>Descartar</button>
          <button type="button" className="btn" onClick={aoFechar}>Cancelar</button>
        </div>
      </form>
    </Janela>
  );
}

/** Tirar a favorita pede confirmacao: a licitacao volta para as recomendadas, e a etapa escolhida fica para tras. */
export function JanelaDeTirarAFavorita({ l, ocupada, falha, aoConfirmar, aoFechar }: {
  l: LinhaLicitacao; ocupada: boolean; falha: string | null; aoConfirmar: () => void; aoFechar: () => void;
}) {
  return (
    <Janela titulo="Tirar a favorita" aoFechar={aoFechar}>
      <DaJanela l={l} />
      {falha && <Falha>{falha}</Falha>}
      <div className="iniciar__rodape">
        <button type="button" className="btn btn--primario" disabled={ocupada} onClick={aoConfirmar}>Tirar a favorita</button>
        <button type="button" className="btn" onClick={aoFechar}>Cancelar</button>
      </div>
    </Janela>
  );
}

/** O comando da analise do edital, que o servidor devolve pronto para colar na sessao de analise (a analise acontece
 *  fora da dashboard). Sem link de edital, o comando vem sem ele e o servidor manda o aviso. */
export function JanelaDaAnalise({ l, analise, aoFechar }: { l: LinhaLicitacao; analise: AnaliseDoEdital; aoFechar: () => void }) {
  const [copiou, setCopiou] = useState<boolean | null>(null);
  const dito = copiou === null ? (analise.favoritou ? "A licitação agora é favorita." : "")
    : copiou ? "Comando copiado." : "Não deu para copiar: selecione o comando.";
  return (
    <Janela titulo="Analisar o edital" aoFechar={aoFechar}>
      <DaJanela l={l} />
      {analise.aviso && <CaixaAviso nivel="atencao">{comPontoFinal(analise.aviso)}</CaixaAviso>}
      <div className="campo">
        <label className="campo__rotulo" htmlFor="lic-comando">Comando para a sessão de análise</label>
        <input id="lic-comando" className="lic-comando" readOnly value={analise.comando} onFocus={ev => ev.currentTarget.select()} />
      </div>
      <p className="lic-janela__dito" role="status">{dito}</p>
      <div className="iniciar__rodape">
        <button type="button" className="btn btn--primario" onClick={() => void copiarTexto(analise.comando).then(setCopiou)}>Copiar</button>
      </div>
    </Janela>
  );
}

export function Traco() {
  return <span className="lic-traco">—</span>;
}
