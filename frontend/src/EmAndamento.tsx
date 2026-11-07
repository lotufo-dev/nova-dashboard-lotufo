import { brl } from "./formato";
import { Link } from "./Link";
import { passoDe } from "./medicao";
import { nivelParada, textoParada, type LinhaResumo } from "./resumoMedicoes";
import Rolagem from "./Rolagem";

// "Em andamento" (redesenho 2026-11, #507; tela aprovada em 06/11/2026): uma linha por medição iniciada e não recebida,
// com o passo atual (selo com número e nome, o mesmo da barra de passos da página), com quem está (Lotufo ou órgão), há
// quanto tempo está parada, o valor e "Abrir". Tudo vem de GET /api/medicoes/resumo; a tela só desenha.

function Linha({ l }: { l: LinhaResumo }) {
  const nivel = nivelParada(l.dias, l.situacao);
  // abre na etapa pendente (#etapa-N), a mesma de passoDe na página da medição
  const secao = passoDe(l.proximo_passo)?.secao || undefined;
  return (
    <tr>
      <td>
        <Link className="medicoes__obra" para={{ tela: "obra", id: l.contrato_id, aba: "medicoes" }}>{l.obra}</Link>
        <span className="medicoes__sub">{l.contratante}{l.orgao_sub ? ` · ${l.orgao_sub}` : ""}</span>
      </td>
      <td>{l.titulo}</td>
      <td><span className={`sit-pilula sit-pilula--${l.situacao}`}>{l.passo.numero} · {l.passo.nome}</span></td>
      <td className={l.com_quem === "Lotufo" ? "andamento__lotufo" : "andamento__orgao"}>{l.com_quem}</td>
      <td><span className={nivel ? `medicoes__parada medicoes__parada--${nivel}` : "medicoes__parada"}>{textoParada(l.dias)}</span></td>
      <td className="col-num dinheiro">{l.valor_centavos === null ? <span className="medicoes__traco">—</span> : brl(l.valor_centavos)}</td>
      <td className="andamento__acao">
        <Link className="btn btn--pequeno" para={{ tela: "medicao", obra: l.contrato_id, id: l.medicao_id }} secao={secao}
          aria-label={`Abrir ${l.titulo} de ${l.obra}`}>Abrir</Link>
      </td>
    </tr>
  );
}

export default function EmAndamento({ linhas }: { linhas: LinhaResumo[] }) {
  return (
    <div className="pagina medicoes">
      <section className="medicoes__quadro" aria-labelledby="em-andamento-titulo">
        <div className="medicoes__quadro-cabeca">
          <h2 id="em-andamento-titulo">Em andamento <span className="andamento__n">{linhas.length}</span></h2>
        </div>
        {linhas.length === 0 ? (
          <div className="vazio"><p className="vazio__titulo">Nenhuma medição em andamento.</p></div>
        ) : (
          <Rolagem rotulo="Medições em andamento">
            <table className="medicoes__tabela andamento__tabela">
              <colgroup>
                <col className="andamento__c-obra" /><col className="andamento__c-medicao" /><col className="andamento__c-passo" />
                <col className="andamento__c-quem" /><col className="andamento__c-parada" /><col className="andamento__c-valor" />
                <col className="andamento__c-acao" />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">Obra</th><th scope="col">Medição</th><th scope="col">Passo atual</th><th scope="col">Com quem</th>
                  <th scope="col">Parada há</th><th scope="col" className="col-num">Valor</th><th scope="col"><span className="sr-only">Ação</span></th>
                </tr>
              </thead>
              <tbody>{linhas.map(l => <Linha key={`${l.situacao}-${l.medicao_id}`} l={l} />)}</tbody>
            </table>
          </Rolagem>
        )}
      </section>
    </div>
  );
}
