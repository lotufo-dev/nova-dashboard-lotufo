import { brl } from "./formato";
import { IconeMais, IconeSeta } from "./icones";
import { Link } from "./Link";
import { passoDe } from "./medicao";
import { cliqueSimples, ir } from "./rota";
import { nivelParada, textoParada, type LinhaResumo } from "./resumoMedicoes";
import { fmtDataPura } from "./tempo";
import "./abaAguardandoNota.css";

// Aba "Aguardando nota" (#156, prototipo aprovado pelo Leo em 14/10/2026): as medicoes cujo e-mail ao faturamento ja'
// saiu e que esperam a nota no RM. A linha inteira abre a medicao na etapa pendente (clique e teclado), sem botao de
// acao; o nome da obra segue sendo link para a obra. "Parada ha'" mantem a regra de hoje (nivelParada: 7 e 15 dias).
// As linhas ja' vem filtradas por situacao de GET /api/medicoes/resumo; aqui so' o desenho.

function Parada({ l }: { l: LinhaResumo }) {
  const nivel = nivelParada(l.dias, l.situacao);
  return (
    <span className={nivel ? `medicoes__parada medicoes__parada--${nivel}` : "medicoes__parada"}>
      {nivel && <i className={`aba-nota__ponto aba-nota__ponto--${nivel}`} aria-hidden="true" />}
      {textoParada(l.dias)}
      {nivel && <span className="sr-only">{nivel === "acao" ? ", atrasada" : ", atenção"}</span>}
    </span>
  );
}

function Linha({ l }: { l: LinhaResumo }) {
  const secao = passoDe(l.proximo_passo)?.secao || undefined;
  const abrir = () => ir({ tela: "medicao", obra: l.contrato_id, id: l.medicao_id }, { secao });
  return (
    <tr className="aba-nota__linha" tabIndex={0}
      onClick={ev => { if (cliqueSimples(ev) && !(ev.target as HTMLElement).closest("a")) abrir(); }}
      onKeyDown={ev => { if (ev.key === "Enter" && ev.target === ev.currentTarget) { ev.preventDefault(); abrir(); } }}>
      <td><Link className="medicoes__obra" para={{ tela: "obra", id: l.contrato_id, aba: "medicoes" }}>{l.obra}</Link></td>
      <td>{l.contratante}{l.orgao_sub && <span className="medicoes__sub">{l.orgao_sub}</span>}</td>
      <td><Link className="medicoes__medicao" para={{ tela: "medicao", obra: l.contrato_id, id: l.medicao_id }}
        secao={secao}>{l.titulo}</Link></td>
      <td className="col-num dinheiro">{brl(l.valor_centavos)}</td>
      <td className="aba-nota__data" data-rotulo="Enviada ao faturamento em">
        {l.marco ? fmtDataPura(l.marco) : <span className="medicoes__traco">{"—"}</span>}</td>
      <td data-rotulo="Parada há"><Parada l={l} /></td>
      <td className="aba-nota__ir"><IconeSeta className="icone icone--p" /></td>
    </tr>
  );
}

function Iniciar({ podeIniciar, aoIniciar }: { podeIniciar: boolean; aoIniciar: () => void }) {
  return podeIniciar ? (
    <div className="medicoes__acoes">
      <button type="button" className="btn btn--primario medicoes__iniciar" onClick={aoIniciar}>
        <IconeMais className="icone" />Iniciar processo de medição
      </button>
    </div>
  ) : null;
}

export default function AbaAguardandoNota({ linhas, podeIniciar, aoIniciar }:
    { linhas: LinhaResumo[]; podeIniciar: boolean; aoIniciar: () => void }) {
  if (linhas.length === 0) {
    return (
      <>
      <Iniciar podeIniciar={podeIniciar} aoIniciar={aoIniciar} />
      <section className="medicoes__quadro" aria-label="Aguardando nota">
        <div className="vazio"><p className="vazio__titulo">Nenhuma medição esperando nota.</p></div>
      </section>
      </>
    );
  }
  return (
    <>
    <Iniciar podeIniciar={podeIniciar} aoIniciar={aoIniciar} />
    <section className="medicoes__quadro" aria-labelledby="aba-nota-titulo">
      <div className="medicoes__quadro-cabeca">
        <h2 id="aba-nota-titulo">Aguardando nota</h2>
      </div>
      <table className="aba-nota__tabela">
        <caption className="sr-only">Medições aguardando a nota fiscal</caption>
        <colgroup>
          <col className="aba-nota__c-obra" /><col className="aba-nota__c-contr" /><col className="aba-nota__c-med" />
          <col className="aba-nota__c-val" /><col className="aba-nota__c-env" /><col className="aba-nota__c-par" />
          <col className="aba-nota__c-ir" />
        </colgroup>
        <thead>
          <tr>
            <th scope="col">Obra</th><th scope="col">Contratante</th><th scope="col">Medição</th>
            <th scope="col" className="col-num">Valor</th><th scope="col">Enviada ao faturamento em</th>
            <th scope="col">Parada há</th><th scope="col"><span className="sr-only">Abrir</span></th>
          </tr>
        </thead>
        <tbody>{linhas.map(l => <Linha key={l.medicao_id} l={l} />)}</tbody>
      </table>
    </section>
    </>
  );
}
