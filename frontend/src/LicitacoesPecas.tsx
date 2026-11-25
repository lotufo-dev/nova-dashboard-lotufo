import CaixaAviso from "./CaixaAviso";
import Falha from "./Falha";
import { brl } from "./formato";
import { IconeLinkExterno } from "./icones";
import {
  avisoDaLeitura, dataDoPrazo, emDiasUteis, linkExterno, orgaoDaLinha, quandoLeu,
  type Favorita, type LeituraDoRadar, type LinhaLicitacao, type MudancaDaFavorita, type SituacaoDoPrazo,
} from "./licitacoes";
import Selo, { Glifo } from "./Selo";
import { fmtDiaNoAno } from "./tempo";
import "./licitacoes.css";

// As pecas que a Triagem e as Favoritas (#908) dividem: a linha da leitura do radar e as celulas da licitacao (o orgao
// com o edital e o objeto, a etapa, o prazo, o valor, a mudanca). Tudo o que e' limite, situacao ou ordem vem do
// servidor; aqui so' se desenha.

/** No lugar da pagina enquanto a leitura nao chega: "Carregando…" ou a falha, com o botao de tentar de novo. */
export function SemLeitura({ erro, tentar }: { erro: string; tentar: () => void }) {
  return (
    <div className="pagina">
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
export function Licitacao({ l, children }: { l: LinhaLicitacao; children?: React.ReactNode }) {
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

/** Uma mudanca da favorita: o rotulo que o radar deu e o dia. */
export function Mudanca({ m }: { m: MudancaDaFavorita }) {
  return <>{m.rotulo} <span className="num lic-fraco">{fmtDiaNoAno(m.data) ?? m.data}</span></>;
}

export function Traco() {
  return <span className="lic-traco">—</span>;
}
