import { IconeVoltar } from "./icones";
import { tituloDe } from "./navegacao";
import { parseRota, type Busca, type Origem, type Rota } from "./rota";
import { Link } from "./Link";

// Pecas da casca (NAVEGACAO.md › Subnavegacao, breadcrumb e voltar): o breadcrumb diz onde se esta' na
// hierarquia, o "← origem" diz de onde se veio, e as abas sao links (abrem em nova aba do navegador).

type Destino = { para: Rota; busca?: Busca; secao?: string };

/** Endereco guardado (a origem) de volta em destino de link, com os filtros que ele tinha. */
export function destinoDeHref(href: string): Destino {
  const u = new URL(href, "http://x");
  const busca = Object.fromEntries(u.searchParams);
  return { para: parseRota(u.pathname), busca: Object.keys(busca).length ? busca : undefined,
    secao: u.hash.replace(/^#/, "") || undefined };
}

/** `fixa`: o link vai sempre ao `para` dela (com a `busca` dela), nunca a origem de onde se chegou. */
export type Migalha = { rotulo: string; para?: Rota; busca?: Busca; fixa?: boolean };

/** "Obras › MT-388": os ancestrais sao links; o ultimo e' onde se esta'. Quando a origem e' o proprio
 *  ancestral (chegou-se pela lista de Obras filtrada), o link dele volta com os filtros. */
export function Migalhas({ itens, origem }: { itens: Migalha[]; origem?: Origem | null }) {
  return (
    <nav className="migalhas" aria-label="Você está em">
      <ol>
        {itens.map((m, i) => {
          const volta = origem && m.para && !m.fixa && origem.tela === m.para.tela ? destinoDeHref(origem.href) : null;
          return (
            <li key={`${m.rotulo}-${i}`} aria-current={i === itens.length - 1 ? "page" : undefined}>
              {m.para && i < itens.length - 1
                ? <Link para={volta?.para ?? m.para} busca={volta?.busca ?? m.busca} title={m.rotulo}>{m.rotulo}</Link>
                : <span title={m.rotulo}>{m.rotulo}</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** "← Medicoes": so' quando se chegou de outra tela que nao a do breadcrumb (esta ja' volta sozinha). */
export function VoltarOrigem({ origem, alemDe }: { origem: Origem | null; alemDe: Rota["tela"][] }) {
  if (!origem || alemDe.includes(origem.tela)) return null;
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
