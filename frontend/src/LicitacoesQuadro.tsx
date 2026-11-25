import Contador from "./Contador";
import { contar } from "./formato";
import type { RespostaFavoritas } from "./licitacoes";
import { Licitacao, Prazo, Traco } from "./LicitacoesPecas";

// QUADRO DAS FAVORITAS (fatia 2 da #906): "/licitacoes/favoritas/quadro". As mesmas favoritas da lista, uma coluna por
// etapa, na ordem das etapas que o servidor manda (`etapas`); dentro da coluna, a ordem da lista. Cada cartao tem o
// orgao com o edital, o objeto e o proximo prazo, com a situacao que o servidor leu. A etapa sem favorita continua no
// quadro, com zero. So' leitura: a etapa se troca na lista.
//
// O cabecalho da coluna e' o cabecalho de grupo forte (a faixa de tinta, o nome a' esquerda e a contagem a' direita). Na
// pagina larga as sete colunas ficam numa fileira; na media, as que nao cabem descem, na mesma ordem; na estreita viram
// blocos empilhados. O quadro nunca rola de lado (licitacoes.css).

export default function LicitacoesQuadro({ dados }: { dados: RespostaFavoritas }) {
  return (
    <ol className="lic-quadro" aria-label="Favoritas por etapa">
      {dados.etapas.map(e => {
        const linhas = dados.favoritas.filter(l => l.favorita?.etapa === e.etapa);
        return (
          <li key={e.etapa} className="lic-coluna">
            <header className="lic-coluna__cabeca">
              <h2 className="lic-coluna__nome">{e.rotulo}</h2>
              <Contador rotulo={contar(linhas.length, "favorita", "favoritas")}>{linhas.length.toLocaleString("pt-BR")}</Contador>
            </header>
            {linhas.length === 0 ? <p className="lic-coluna__vazia"><Traco /></p> : (
              <ul className="lic-cartoes">
                {linhas.map(l => {
                  const proximo = l.favorita?.proximo_prazo;
                  return (
                    <li key={l.chave} className="lic-cartao">
                      <Licitacao l={l} />
                      {/* a licitacao encerrada nao tem prazo correndo: so' o nome e a data, como na lista */}
                      {proximo && <span className="lic-prazo"><Prazo p={proximo} corre={!l.encerrada} /></span>}
                    </li>
                  );
                })}
              </ul>
            )}
          </li>
        );
      })}
    </ol>
  );
}
