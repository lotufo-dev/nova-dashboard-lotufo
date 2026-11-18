import { IconeVoltar } from "./icones";
import { tituloDe } from "./navegacao";
import { parseRota, temOrigem, type Busca, type Origem, type Rota } from "./rota";
import { Link } from "./Link";

// Pecas de navegacao dentro da pagina: o "← origem" diz de onde se veio, e as abas sao links (abrem em nova aba do
// navegador). O caminho ("Obras › SINFRA › MT-388"), que diz onde se esta' na hierarquia, e' da casca: uma peca so',
// na barra do topo (Caminho.tsx, #814); as paginas nao desenham mais trilha propria.

type Destino = { para: Rota; busca?: Busca; secao?: string };

/** Endereco guardado (a origem) de volta em destino de link, com os filtros que ele tinha. */
export function destinoDeHref(href: string): Destino {
  const u = new URL(href, "http://x");
  const busca = Object.fromEntries(u.searchParams);
  return { para: parseRota(u.pathname), busca: Object.keys(busca).length ? busca : undefined,
    secao: u.hash.replace(/^#/, "") || undefined };
}

/** "← Medicoes": so' quando se chegou de outra tela que nao as do caminho (estas ja' voltam sozinhas). */
export function VoltarOrigem({ origem, alemDe }: { origem: Origem | null; alemDe: Rota["tela"][] }) {
  if (!temOrigem(origem, alemDe)) return null;
  const d = destinoDeHref(origem.href);
  return (
    <Link className="btn--voltar" para={d.para} busca={d.busca}>
      <IconeVoltar className="icone icone--p" /> {tituloDe(origem.tela)}
    </Link>
  );
}

export type Aba<T extends string> = { id: T; rotulo: string; para: Rota };

/** Faixa de abas como links: a aba e' um endereco, e o item atual leva aria-current. */
export function Abas<T extends string>({ rotulo, itens, atual, classe }: { rotulo: string; itens: Aba<T>[]; atual: T; classe?: string }) {
  return (
    <nav className={classe ? `abas ${classe}` : "abas"} aria-label={rotulo}>
      {itens.map(a => (
        <Link key={a.id} className="aba" para={a.para} aria-current={a.id === atual ? "page" : undefined}>
          {a.rotulo}
        </Link>
      ))}
    </nav>
  );
}
