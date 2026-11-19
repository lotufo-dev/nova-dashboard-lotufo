import type { ReactNode } from "react";
import type { AReceberDoContratante, Leitura, MedicoesDoContratante, SigaDoContratante } from "./abasDoContratante";
import { APartes, Numeros, Tabela, TRAVA, type Vista } from "./AReceber";
import CaixaAviso from "./CaixaAviso";
import Falha from "./Falha";
import { IconeSiga } from "./icones";
import { Concluidas, GruposDaFila, SemMedicaoNoMes } from "./MedicoesFila";
import { mesPorExtenso } from "./resumoMedicoes";
import type { Ir } from "./rota";
import { porCategoria } from "./siga";
import { PainelDaCategoria } from "./SigaPagina";
import { fmtMesExtenso } from "./tempo";
import "./medicoes.css";
import "./contratante.css";

// As abas Medicoes, A receber e Processos no SIGA da pagina do contratante (#818). Cada uma desenha, com as pecas da
// tela de onde o dado vem, o recorte que o servidor manda (`app/contratante.py`): a fila de trabalho (MedicoesFila), a
// pagina A receber (AReceber) e a tela SIGA (SigaPagina). Nada se soma nem se conta aqui. O invólucro de cada aba
// leva a classe da pagina de origem (`medicoes`, `arc`, `siga`): as pecas medem a largura por ela, e no celular a
// linha vira bloco como la'.

/** A aba enquanto o dado nao chega, ou quando a leitura falhou; pronta, o conteudo. */
function ComLeitura<T>({ leitura, lendo, falha, children }: {
  leitura: Leitura<T>; lendo: string; falha: string; children: (d: T) => ReactNode;
}) {
  if (leitura.estado === "pronta") return <>{children(leitura.dado)}</>;
  if (leitura.estado === "falhou") return <Falha>{falha}: {leitura.erro} Recarregue a página para tentar de novo.</Falha>;
  if (leitura.estado === "lendo") return <div className="vazio"><p role="status">{lendo}</p></div>;
  return null;
}

/** As medicoes do contratante na competencia em trabalho: a fila por quem tem de agir (cada grupo da mais parada para a
 *  menos, com a barra de passos, o tempo parado e a diferenca aprovado x pedido), as concluidas no mes e as obras sem
 *  medicao. Pedido e aprovado sao o valor cheio da medicao, como na tela Medicoes; o cabecalho diz, porque o resto
 *  da pagina e' na cota. Quem so' consulta ve "Abrir" no lugar do proximo passo. */
export function AbaMedicoes({ leitura, nome, opera }: { leitura: Leitura<MedicoesDoContratante>; nome: string; opera: boolean }) {
  return (
    <ComLeitura leitura={leitura} lendo="Carregando as medições…" falha="Não foi possível carregar as medições">
      {d => (
        <div className="medicoes ct-aba">
          <div className="ct-aba__cab">
            <h2 className="medicoes__mes">{mesPorExtenso(d.mes)}</h2>
            <p className="medicoes__cab-rotulo">competência em trabalho · valor cheio</p>
          </div>
          {d.grupos.length > 0
            ? <GruposDaFila grupos={d.grupos} limites={d.limites} opera={opera} />
            : <p className="medicoes__vazio medicoes__vazio--pagina">Nenhuma medição de {nome} em andamento em {fmtMesExtenso(d.mes)}.</p>}
          <div className="fila-blocos">
            <Concluidas d={d} />
            <SemMedicaoNoMes obras={d.sem_medicao} mes={d.mes} podeIniciar={false} aoIniciar={() => undefined} />
          </div>
        </div>
      )}
    </ComLeitura>
  );
}

/** O em aberto do contratante, nota a nota: o mesmo grupo, o mesmo total e o mesmo "a' parte" da pagina A receber
 *  filtrada por ele, com as pecas dela. O cabecalho do grupo traz o prazo de pagamento do orgao e o subtotal. */
export function AbaAReceber({ leitura, nome, ir }: { leitura: Leitura<AReceberDoContratante>; nome: string; ir: Ir }) {
  return (
    <ComLeitura leitura={leitura} lendo="Carregando o em aberto…" falha="Não foi possível carregar o em aberto">
      {d => {
        if (!d.total_a_receber_liberado) {
          return <div className="arc ct-aba"><CaixaAviso nivel="atencao" className="arc-aviso">{TRAVA}</CaixaAviso></div>;
        }
        const g = d.contratante ?? null;
        // a vista de um contratante, como a da pagina A receber filtrada por ele (`vistaDe` em AReceber.tsx)
        const v: Vista | null = g && { ...g, grupos: g.quantidade > 0 ? [g] : [], soltas: g.notas_sem_medicao,
          soltas_centavos: g.notas_sem_medicao_centavos };
        return (
          <div className="arc ct-aba">
            {v && v.quantidade > 0 && <Numeros v={v} anos={d.anos} />}
            {!v || v.grupos.length === 0 ? (
              <section className="cartao" aria-label={`Em aberto de ${nome}`}>
                <div className="vazio vazio--curto"><p className="vazio__titulo">Nenhuma nota em aberto de {nome}.</p></div>
              </section>
            ) : (
              <section className="cartao arc-painel" aria-label={`Em aberto de ${nome}`}>
                <Tabela grupos={v.grupos} recolhidos={false} ir={ir} />
              </section>
            )}
            {v && <APartes v={v} anos={d.anos} comSemNota={v.grupos.some(x => x.linhas.some(l => l.tipo_aberto === "sem_nota"))} />}
          </div>
        );
      }}
    </ComLeitura>
  );
}

/** Os processos vivos do contratante no SIGA: um painel por categoria, cada um do mais parado para o menos, com a
 *  borda da linha na cor do tempo no setor. A linha abre o historico na tela SIGA. */
export function AbaSiga({ leitura, agora }: { leitura: Leitura<SigaDoContratante>; agora?: Date }) {
  return (
    <ComLeitura leitura={leitura} lendo="Carregando os processos…" falha="Não foi possível carregar os processos do SIGA">
      {d => {
        const secoes = porCategoria(d.processos);
        const quando = agora ?? new Date();
        return (
          <div className="siga ct-aba">
            {secoes.length === 0 ? (
              <section className="cartao sg__quadro"><div className="sg__vazio"><IconeSiga className="icone" /><p>Nenhum processo em andamento.</p></div></section>
            ) : secoes.map(s => <PainelDaCategoria key={s.categoria} secao={s} limites={d.limites} agora={quando} robo={d.robo} categoria={null} />)}
          </div>
        );
      }}
    </ComLeitura>
  );
}
