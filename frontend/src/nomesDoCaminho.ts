import { useEffect, useSyncExternalStore } from "react";
import type { NomesDoCaminho } from "./navegacao";

// Os nomes que o caminho do topo (Caminho.tsx, #814) nao tem como saber pela rota: a obra, o contratante, a medicao,
// a empresa e o processo. Quem os diz e' a pagina que ja' carregou o objeto (`useNomesDoCaminho`); o caminho nao faz
// chamada ao servidor por conta propria. Enquanto a pagina carrega, o trecho sai com o nome do tipo ("Obra").
//
// E' um quadro de avisos de uma pagina so': a pagina que esta' na tela escreve, a casca le. Ao sair da tela a pagina
// apaga o que escreveu, para o nome de uma obra nao aparecer no caminho de outra.

const VAZIO: NomesDoCaminho = {};
let atuais: NomesDoCaminho = VAZIO;
const ouvintes = new Set<() => void>();

function publicar(nomes: NomesDoCaminho) {
  atuais = nomes;
  for (const f of ouvintes) f();
}

function assinar(f: () => void) {
  ouvintes.add(f);
  return () => { ouvintes.delete(f); };
}

/** A pagina diz ao caminho os nomes do que ela ja' tem carregado. Chamar com o que houver: o que ainda nao chegou
 *  fica `undefined` ou `null`, e o caminho se completa quando chegar. */
export function useNomesDoCaminho(nomes: NomesDoCaminho) {
  // por valor, e nao por identidade: a pagina monta o objeto a cada desenho
  const chave = JSON.stringify(nomes);
  useEffect(() => {
    const meus = JSON.parse(chave) as NomesDoCaminho;
    publicar(meus);
    return () => { if (atuais === meus) publicar(VAZIO); };
  }, [chave]);
}

/** Os nomes que a pagina da tela publicou (a casca le; vazio enquanto ninguem publicou). */
export function useNomesPublicados(): NomesDoCaminho {
  return useSyncExternalStore(assinar, () => atuais);
}
