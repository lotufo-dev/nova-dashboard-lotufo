import { Link } from "./Link";
import type { Busca, Ir } from "./rota";

// A RECEBER (decisao do dono de 18/11/2026, #805): o em aberto nota a nota, na area Financeiro; sai do fim do
// Fechamento. Esta e' a pagina-casca (issue #814): o endereco ("/a-receber"), o titulo e o caminho, que a barra do
// topo escreve ("Financeiro › A receber"), e o estado vazio. A issue #816 traz as notas, agrupadas por contratante e
// por data do protocolo, e preenche aqui dentro; ate' la' a pagina mostra sempre o vazio.
//
// `?contratante=` mostra so' um contratante: o nome vem na busca da URL, como a pagina do contratante e a fila de
// Medicoes vao mandar.

export default function AReceber({ busca = {}, ir }: { busca?: Busca; ir: Ir }) {
  const contratante = (busca.contratante ?? "").trim().slice(0, 80);
  return (
    <section className="cartao" aria-label={contratante ? `A receber de ${contratante}` : "A receber"}>
      <div className="vazio vazio--curto">
        <p className="vazio__titulo">{contratante ? `Nenhuma nota em aberto de ${contratante}.` : "Nenhuma nota em aberto."}</p>
        {contratante && <p><Link para={{ tela: "a-receber" }} ir={ir}>Ver todos os contratantes</Link></p>}
      </div>
    </section>
  );
}
