import "./barraDePassos.css";

// BarraDePassos (#805): o fluxo da medicao de UMA obra em miniatura, para linha de tabela. Um segmento por passo que
// a obra tem (cinco onde a obra nao tem um deles): os feitos, o da vez e os que faltam, com o nome do passo da vez e
// a posicao dele ("Espelhos · 3 de 5"). Os passos e a situacao de cada um vem do servidor
// (`medicoes.passos_das_medicoes`); a barra grande, com data e clique, e' a da pagina da medicao (Passos.tsx).

export type PassoDaBarra = { numero: number; nome: string; situacao: "feito" | "atual" | "futuro" };

/** Os segmentos sao desenho: quem le a tela ouve "Espelhos, passo 3 de 5". Sem passo da vez (tudo feito), so' a barra,
 *  com o nome "todos os passos feitos". */
export default function BarraDePassos({ passos }: { passos: PassoDaBarra[] }) {
  if (passos.length === 0) return null;
  const posicao = passos.findIndex(p => p.situacao === "atual");
  const atual = posicao >= 0 ? passos[posicao] : null;
  return (
    <span className="barra-passos">
      <span className="barra-passos__trilho" aria-hidden="true">
        {passos.map(p => <span key={p.numero} className={`barra-passos__passo barra-passos__passo--${p.situacao}`} />)}
      </span>
      {atual ? (
        <span className="barra-passos__nome">
          {atual.nome}<span aria-hidden="true"> · </span><span className="sr-only">, passo </span>
          <span className="barra-passos__posicao num">{posicao + 1} de {passos.length}</span>
        </span>
      ) : <span className="sr-only">Todos os passos feitos</span>}
    </span>
  );
}
