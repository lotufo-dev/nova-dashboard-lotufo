import Contador from "./Contador";
import { contar } from "./formato";
import { useLicitacoes, type LinhaLicitacao, type RespostaFavoritas } from "./licitacoes";
import { Etapa, LeituraDoRadarLinha, Licitacao, Mudanca, Prazo, SemLeitura, Traco, Valor } from "./LicitacoesPecas";
import Rolagem from "./Rolagem";

// FAVORITAS (#908, docs/adr/0018): "/licitacoes/favoritas". Responde "em que etapa esta' cada uma e o que vence": todas
// as favoritas ativas, cada uma com a etapa, todos os prazos e as mudancas desde que foi favoritada. So' leitura nesta
// fatia: as favoritas sao espelho do que o radar manda.
//
// Tudo vem pronto de GET /api/licitacoes/favoritas: a ordem (as em aberto primeiro, pela sessao; as encerradas no fim),
// a etapa com o rotulo, os dias uteis e a situacao de cada prazo.
//
// As encerradas ficam num grupo recolhido no fim, como os encerrados do SIGA: nao tem prazo correndo, e a pagina
// responde o que vence. Nelas o prazo e' so' o nome e a data, sem os dias e sem cor (o servidor ja' manda sem situacao).

/** Quantas mudancas a linha mostra; o resto vira a contagem ("e mais 2"). */
const MUDANCAS_A_VISTA = 3;

function Tabela({ linhas, legenda, encerradas = false }: { linhas: LinhaLicitacao[]; legenda: string; encerradas?: boolean }) {
  return (
    <Rolagem rotulo={legenda}>
      <table className="tabela lic-tabela">
        <caption className="sr-only">{legenda}</caption>
        <thead>
          <tr>
            <th scope="col">Licitação</th><th scope="col">Etapa</th><th scope="col">Prazos</th>
            <th scope="col" className="col-num">Valor</th><th scope="col">Mudanças</th>
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
                <td data-rotulo="Etapa"><Etapa f={f} /></td>
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
              </tr>
            );
          })}
        </tbody>
      </table>
    </Rolagem>
  );
}

export default function LicitacoesFavoritas() {
  const { dados, erro, tentar } = useLicitacoes<RespostaFavoritas>("/api/licitacoes/favoritas");
  if (!dados) return <SemLeitura erro={erro} tentar={tentar} />;

  const abertas = dados.favoritas.filter(l => !l.encerrada);
  const encerradas = dados.favoritas.filter(l => l.encerrada);
  return (
    <div className="pagina lic">
      <LeituraDoRadarLinha leitura={dados.leitura} />
      {/* o nome da pagina ja' esta' no alto: o painel nao o repete como titulo */}
      <section className="cartao lic-bloco" aria-label="Favoritas em aberto">
        {abertas.length === 0
          ? <div className="vazio vazio--curto"><p>{encerradas.length === 0 ? "Nenhuma favorita." : "Nenhuma favorita em aberto."}</p></div>
          : <Tabela linhas={abertas} legenda="Favoritas em aberto" />}
      </section>
      {encerradas.length > 0 && (
        <details className="lic-encerradas">
          <summary>Encerradas <Contador rotulo={contar(encerradas.length, "favorita encerrada", "favoritas encerradas")}>{encerradas.length.toLocaleString("pt-BR")}</Contador></summary>
          <section className="cartao lic-bloco" aria-label="Favoritas encerradas">
            <Tabela linhas={encerradas} legenda="Favoritas encerradas" encerradas />
          </section>
        </details>
      )}
    </div>
  );
}
