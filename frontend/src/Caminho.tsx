import { Link } from "./Link";
import { trechosDe, type Trecho } from "./navegacao";
import { useNomesPublicados } from "./nomesDoCaminho";
import type { Busca, Origem, Rota } from "./rota";
import { destinoDeHref } from "./Topo";

// O CAMINHO no alto de toda pagina (decisao do dono de 18/11/2026, #805; issue #814): onde se esta', da area ate' o
// objeto, cada trecho um link ("Obras › SINFRA › MT-388 › Medições › 15ª Medição"). E' UMA peca so', desenhada pela
// casca na barra do topo; as trilhas que a obra, a medicao, o contratante, a empresa e o historico do SIGA desenhavam
// cada uma do seu jeito sairam. Os trechos vem de `trechosDe` (navegacao.ts); o nome do objeto, da pagina que ja' o
// carregou (nomesDoCaminho.ts).
//
// O trecho da pagina (ou do objeto) e' o TITULO da barra: nas telas de lista ele e' o h1 da pagina; nas que tem o
// proprio h1 (a obra, a medicao, o Inicio) e' so' texto, com a mesma cara. Depois dele so' pode vir a vista (a aba).
// O ultimo trecho e' onde se esta' (aria-current) e nao e' link.

/** A mesma pagina, sem olhar a vista: a lista de Obras em qualquer vista, a pagina de Documentos do mesmo assunto, o
 *  mesmo contratante. */
function mesmaPagina(a: Rota, b: Rota): boolean {
  if (a.tela !== b.tela) return false;
  if (a.tela === "documentos" && b.tela === "documentos") return (a.pagina ?? "certidoes") === (b.pagina ?? "certidoes");
  if (a.tela === "contratante" && b.tela === "contratante") return a.chave === b.chave;
  return true;
}

/** O caminho da rota, para o perfil (a area leva a' primeira pagina dela no menu dele), com os nomes que a pagina
 *  aberta publicou. `busca`: os filtros do endereco (o historico do SIGA mora neles). `origem`: de onde se chegou ao
 *  detalhe; quando ela e' um trecho do caminho (chegou-se pela lista de Obras filtrada, ou pela pagina do contratante
 *  com as encerradas a' vista), o link do trecho volta para la' como estava. `ehH1`: o trecho do titulo e' o h1. */
export default function Caminho({ rota, perfil, permissoes, busca, origem, ehH1 }: {
  rota: Rota; perfil?: string; permissoes?: readonly string[]; busca?: Busca; origem?: Origem | null; ehH1: boolean;
}) {
  const nomes = useNomesPublicados();
  const trechos: Trecho[] = trechosDe(rota, { perfil, permissoes, nomes, busca });
  if (trechos.length === 0) return null;
  const veioDe = origem ? destinoDeHref(origem.href) : null;
  return (
    <nav className="caminho" aria-label="Você está em">
      <ol>
        {trechos.map((t, i) => {
          const ultimo = i === trechos.length - 1;
          const volta = veioDe && t.para && !t.area && mesmaPagina(veioDe.para, t.para) ? veioDe : null;
          const texto = !ultimo && t.para
            ? <Link para={volta?.para ?? t.para} busca={volta ? volta.busca : t.busca}>{t.rotulo}</Link>
            : <span>{t.rotulo}</span>;
          return (
            <li key={`${t.rotulo}-${i}`} className={t.titulo ? "caminho__trecho caminho__trecho--titulo" : "caminho__trecho"}
              aria-current={ultimo ? "page" : undefined}>
              {t.titulo && ehH1 ? <h1 className="caminho__titulo">{texto}</h1> : texto}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
