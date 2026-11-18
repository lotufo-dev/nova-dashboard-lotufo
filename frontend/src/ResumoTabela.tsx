import Diferenca from "./Diferenca";
import { brl, contar } from "./formato";
import { Link } from "./Link";
import MarcaEtapa from "./MarcaEtapa";
import { ANTES, ETAPAS, temDiferenca, type Etapa, type Grupo, type Linha } from "./resumoEtapas";
import Rolagem from "./Rolagem";
import { type Ir } from "./rota";
import Selo, { Glifo } from "./Selo";
import { fmtDataCurta, fmtDataPura } from "./tempo";

// A vista Tabela do Resumo das medicoes (#749; segunda vista desde a #805): uma linha por medicao e uma coluna por
// etapa, com a data registrada de cada uma, para comparar os valores entre as linhas. Tambem e' a forma dos meses
// anteriores, agrupados por competencia. A obra so' tem as etapas do fluxo dela, e cada etapa alcancada leva a data
// que o sistema registrou. A etapa que ficou para tras sem o registro do evento (a medicao pulou a etapa, ou veio do
// historico) nao leva visto nem data: a pagina so' afirma o que tem registro.
// O grupo (o contratante; nos meses anteriores, a competencia) abre com o cabecalho de grupo forte da fundacao, com a
// quantidade e o medido dele, que vem do servidor.

/** Sem valor ou zero nao e' numero a ler: "—". */
const valor = (c: number | null) => (c === null || c === 0 ? "—" : brl(c));

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

export default function ResumoTabela({ grupos, rotulo, legenda, limitePorMil, ir }: {
  grupos: Grupo[]; rotulo: string; legenda: string; limitePorMil: number; ir: Ir;
}) {
  return (
    <Rolagem rotulo={rotulo} className="tabela-wrap rdm-rolagem">
      <table className="tabela rdm-tabela rdm-tabela--etapas">
        <caption className="sr-only">{legenda}</caption>
        <thead>
          <tr>
            <th scope="col" className="rdm-primeira">Obra</th>
            {ETAPAS.map(e => <th key={e.chave} scope="col" className="rdm-th-etapa"><MarcaEtapa etapa={e.chave} /></th>)}
            <th scope="col" className="col-num">Medido</th>
          </tr>
        </thead>
        {grupos.map(g => (
          <tbody key={g.chave}>
            <tr className="rdm-grupo">
              <th scope="rowgroup" colSpan={ETAPAS.length + 1}>
                {g.titulo}<span className="rdm-grupo__n num">{contar(g.medicoes, "medição", "medições")}</span>
              </th>
              <td className="col-num dinheiro num">{valor(g.valor_centavos)}</td>
            </tr>
            {g.linhas.map((l, i) => (
              <tr key={l.medicao_id} className="rdm-linha">
                <Primeira l={l} repetida={i > 0 && g.linhas[i - 1].contrato_id === l.contrato_id} ir={ir}>
                  {l.etapa === "antes" && <Selo className="rdm-antes">{ANTES}</Selo>}
                </Primeira>
                {ETAPAS.map(e => <CelulaEtapa key={e.chave} etapa={e} l={l} />)}
                <td className="col-num dinheiro num rdm-valor" data-rotulo="Medido">
                  <span className="rdm-valor__cel">
                    <span>{valor(l.valor_centavos)}</span>
                    {temDiferenca(l) && (
                      <Diferenca abaixo={l.abaixo_do_pedido_centavos} acima={l.acima_do_pedido_centavos}
                        base={l.pedido_do_aprovado_centavos} nomeBase="pedido" limitePorMil={limitePorMil} />
                    )}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </Rolagem>
  );
}
