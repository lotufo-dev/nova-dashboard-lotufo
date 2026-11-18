import type { Ir } from "./rota";

// O LUGAR DA BUSCA UNICA no topo (decisao do dono de 18/11/2026, #805: "busca unica no topo: obra, numero de medicao,
// numero de processo"). Esta e' a casca (issue #814): a barra do topo ja' desenha a peca, entre o caminho e a conta,
// e por ora ela nao devolve nada. A issue #819 preenche aqui dentro, sem mexer na casca.
//
// O que a casca entrega: o `perfil` de quem esta' logado (so' aparece no resultado o que o perfil pode abrir: quem nao
// acessa o SIGA nao recebe processo) e o `ir` do roteador. O estilo da peca vai em css proprio; a barra do topo
// (`.topo`, tokens.css) quebra em linhas quando falta largura, e a busca nao pode cobrir o caminho.

export default function Busca(_props: { perfil: string; ir: Ir }) {
  return null;
}
