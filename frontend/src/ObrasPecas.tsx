import { motivosDaLinha } from "./carteira";
import EmAbertoAParte from "./EmAbertoAParte";
import { brl, contar, fmtDias } from "./formato";
import { Link } from "./Link";
import { mesesDoMedido, pctPiso, type LeituraDaObra, type MedidoMes, type ResumoObras } from "./listaObras";
import MarcaEtapa from "./MarcaEtapa";
import { SeloFarol, type ObraPainel } from "./ObrasCarteira";
import { type Ir } from "./rota";
import Selo from "./Selo";
import Variacao from "./Variacao";
import { prazoNoFimNaSituacao, type AndamentoDoServidor } from "./valores";

// As pecas que as vistas de Obras dividem (#805): a faixa de numeros (da carteira ou de um contratante), o medido do
// mes com a variacao, as etiquetas do que pede atencao e a situacao da obra com o motivo escrito. Tudo na COTA da
// Lotufo e tudo do servidor (`/api/contratos` e `/api/diretoria`); aqui so' se soma o que a vista mostra e se desenha.

/** A barra do executado com o percentual ao lado. O percentual e' numero, nao situacao: tinta, sem glifo. */
export function Executado({ pct }: { pct: number | null }) {
  return (
    <div className="obras-exec">
      <div className="obras-exec__trilho" role="img" aria-label={pct === null ? "sem valor vigente" : `${pct}% executado`}>
        <span className="obras-exec__barra" style={{ width: `${Math.min(100, Math.max(0, pct ?? 0))}%` }} />
      </div>
      <span className="obras-exec__pct num">{pct === null ? "—" : `${pct}%`}</span>
    </div>
  );
}

/** O medido da ultima competencia fechada com a variacao contra a competencia anterior (a referencia vem do servidor).
 *  Mes sem medicao: "—", e a variacao continua dizendo que caiu. */
export function MedidoNoMes({ mm }: { mm: MedidoMes | null | undefined }) {
  if (!mm) return <>—</>;
  const meses = mesesDoMedido(mm);
  return (
    <span className="obras-cel">
      <span className="num">{mm.valor_centavos > 0 ? brl(mm.valor_centavos) : "—"}</span>
      {meses.referencia && (
        <Variacao atual={mm.valor_centavos} referencia={mm.referencia_centavos} rotulo={meses.referencia.curto} porExtenso={meses.referencia.extenso} />
      )}
    </span>
  );
}

/** O a receber: o valor no tom do em aberto quando existe; sem o total liberado (nulo), "—". */
export function AReceber({ centavos }: { centavos: number | null | undefined }) {
  if (centavos === null || centavos === undefined) return <>—</>;
  return <span className={centavos > 0 ? "obras-em-aberto num" : "num"}>{brl(centavos)}</span>;
}

/** A faixa de numeros de um conjunto de obras: a carteira (vista "Por contratante", "Todas as obras" e "Andamento")
 *  ou um contratante (a pagina dele, com a participacao na carteira e o prazo de pagamento do orgao). Os numeros sao
 *  os de `resumoDe` sobre as obras que a vista mostra. `prazo`: os dias do servidor; `null` e' "o sistema nao tem"
 *  (menos de cinco recebimentos em doze meses, docs/adr/0007); `undefined`, a faixa nao tem esse numero. */
export function NumerosDeObras({ r, rotulo, participacao, prazo }: {
  r: ResumoObras; rotulo: string; participacao?: string | null; prazo?: number | null;
}) {
  const t = r.totais;
  const pct = pctPiso(t.medido, t.contratado);
  const meses = r.medidoMes ? mesesDoMedido(r.medidoMes) : null;
  return (
    <>
      <dl className="obras-numeros" aria-label={rotulo}>
        <div className="obras-numero">
          <dt>Contratado</dt><dd>{brl(t.contratado)}</dd>
          {participacao && <dd className="obras-numero__apoio">{participacao} da carteira</dd>}
        </div>
        <div className="obras-numero"><dt>Medido{pct === null ? "" : ` (${pct}%)`}</dt><dd>{brl(t.medido)}</dd></div>
        {r.medidoMes && meses && (
          <div className="obras-numero">
            <dt>Medido em {meses.extenso}</dt>
            <dd>{r.medidoMes.valor_centavos > 0 ? brl(r.medidoMes.valor_centavos) : "—"}</dd>
            {meses.referencia && (
              <dd className="obras-numero__apoio">
                <Variacao atual={r.medidoMes.valor_centavos} referencia={r.medidoMes.referencia_centavos}
                  rotulo={meses.referencia.curto} porExtenso={meses.referencia.extenso} />
              </dd>
            )}
          </div>
        )}
        <div className="obras-numero">
          <dt><MarcaEtapa etapa="em_aberto">A receber</MarcaEtapa></dt>
          <dd className={t.temReceber && t.aReceber > 0 ? "obras-em-aberto" : undefined}>{t.temReceber ? brl(t.aReceber) : "—"}</dd>
        </div>
        {prazo !== undefined && (
          <div className="obras-numero"><dt>Prazo de pagamento</dt><dd>{prazo === null ? "—" : fmtDias(prazo)}</dd></div>
        )}
        <div className="obras-numero">
          <dt>Andamento</dt>
          <dd>{r.comAndamento === 0 ? "—" : `${r.devagar} de ${r.comAndamento}`}</dd>
          {r.comAndamento > 0 && (
            <dd className="obras-numero__apoio">
              <span className={`obras-etiqueta${r.devagar > 0 ? " obras-etiqueta--devagar" : ""}`}>{r.devagar === 1 ? "obra devagar" : "obras devagar"}</span>
            </dd>
          )}
          {/* #822: o "de M" so' conta quem tem leitura; as obras com prazo a cumprir e sem leitura (fora da regua ou
              que ainda nao mediram) vao ao lado, em tinta: e' contagem, nao aviso. As duas somam a vista Andamento */}
          {r.semLeitura > 0 && <dd className="obras-numero__apoio"><span className="num">{r.semLeitura}</span> sem leitura</dd>}
        </div>
      </dl>
      {/* fora do total "A receber": o em aberto antigo e o que o RM deixou de informar, das obras que a vista mostra */}
      {t.anoInicial && <EmAbertoAParte anoInicial={t.anoInicial} anterior={t.aReceberAnterior} semAtualizacao={t.aReceberSemAtualizacao} />}
    </>
  );
}

/** O que pede atencao num conjunto de obras, em etiquetas: o andamento (devagar, em atencao) no tom da familia de
 *  valor, sem glifo (valor nao e' situacao); paralisada, neutra; execucao vencida e aviso critico, com o selo do
 *  critico. Sem nenhuma, "Em dia", em tinta.
 *  `semAndamento` (decisao do dono de 18/11/2026): os blocos de "Por contratante" nao levam as etiquetas do andamento
 *  (com a carteira real toda obra esta' abaixo do necessario, e a etiqueta se repetia em todo bloco); o andamento
 *  continua no numero do alto da pagina, na pagina do contratante e na coluna das tabelas. */
export function EtiquetasDeAtencao({ r, semAndamento = false }: { r: ResumoObras; semAndamento?: boolean }) {
  const itens: React.ReactNode[] = [];
  if (!semAndamento && r.devagar > 0) itens.push(<span className="obras-etiqueta obras-etiqueta--devagar">{r.devagar} devagar</span>);
  if (!semAndamento && r.atencao > 0) itens.push(<span className="obras-etiqueta obras-etiqueta--atencao">{r.atencao} em atenção</span>);
  if (r.paralisadas > 0) itens.push(<Selo>{contar(r.paralisadas, "paralisada", "paralisadas")}</Selo>);
  if (r.execucaoVencida > 0) itens.push(<Selo situacao="critico">{r.execucaoVencida} com execução vencida</Selo>);
  if (r.avisosCriticos > 0) itens.push(<Selo situacao="critico">{contar(r.avisosCriticos, "aviso crítico", "avisos críticos")}</Selo>);
  if (itens.length === 0) return <p className="obras-etiquetas obras-etiquetas--emdia">Em dia</p>;
  return <ul className="obras-etiquetas" aria-label="O que pede atenção">{itens.map((x, i) => <li key={i}>{x}</li>)}</ul>;
}

/** A situacao da obra com o motivo escrito: o selo do farol (a palavra do nivel) e o primeiro motivo dele, na ordem
 *  do servidor (o mais grave primeiro); os outros ficam nos avisos da obra. A obra em dia fica so' com a palavra, em
 *  tinta. Sem o painel (carregando, falhou) ou sem a obra nele, nada.
 *  `andamento` (decisao do dono de 18/11/2026): a leitura do andamento da obra (`andamentoDaObra`, a regua unica),
 *  na tabela que tem a coluna Andamento ao lado. A obra sem aviso e com o andamento Devagar nao diz "Em dia", que
 *  contradiria a coluna vizinha: diz o motivo do andamento, com a palavra na etiqueta da familia (valor, sem glifo).
 *  Qualquer aviso do farol continua ganhando, e Atencao no andamento nao tira o "Em dia".
 *  `leitura` (decisao do dono de 19/11/2026): a leitura do andamento como o servidor a manda. A obra sem aviso que o
 *  servidor tirou da regua pelo prazo no fim tambem nao diz "Em dia": diz "Prazo no fim · execução até dd/mm", em
 *  tinta (o aviso de execucao terminando e' so' da operacao; a diretoria nao o ve no farol). */
export function SituacaoDaObra({ obra, ir, andamento, leitura }: {
  obra: ObraPainel | undefined; ir: Ir; andamento?: LeituraDaObra | null; leitura?: AndamentoDoServidor | null;
}) {
  if (!obra) return null;
  if (obra.farol === "verde" && andamento?.leitura === "devagar") {
    return (
      <div className="obras-situacao">
        {/* a mesma palavra da peca `Andamento`, na coluna ao lado (o teste da pagina do contratante confere) */}
        <span className="obras-etiqueta obras-etiqueta--devagar">Devagar</span>
        <span className="obras-situacao__motivo">mede <span className="num">{andamento.pct.toLocaleString("pt-BR")}%</span> do necessário</span>
      </div>
    );
  }
  const prazoNoFim = obra.farol === "verde" ? prazoNoFimNaSituacao(leitura) : null;
  if (prazoNoFim) return <span className="obras-situacao__prazo">{prazoNoFim}</span>;
  if (obra.farol === "verde") return <span className="obras-situacao__emdia">Em dia</span>;
  const { visiveis, mais } = motivosDaLinha(obra.motivos, 1);
  return (
    <div className="obras-situacao">
      <SeloFarol farol={obra.farol} />
      {visiveis.length > 0 && <span className="obras-situacao__motivo">{visiveis[0].texto}</span>}
      {mais > 0 && (
        <Link className="obras-situacao__mais" para={{ tela: "avisos" }} busca={{ obra: String(obra.contrato_id) }} ir={ir}>
          mais {mais}<span className="sr-only"> {mais === 1 ? "motivo" : "motivos"} de {obra.obra}</span>
        </Link>
      )}
    </div>
  );
}
