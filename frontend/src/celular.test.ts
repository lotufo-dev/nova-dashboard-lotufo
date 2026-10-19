/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// o vitest entrega CSS vazio (mesmo com ?raw): le o arquivo do disco (o vitest roda na pasta frontend)
const ler = (nome: string) => readFileSync(join(process.cwd(), "src", nome), "utf8");
const inicioCss = ler("inicio.css");
const tokensCss = ler("tokens.css");
const medicaoPagina = ler("MedicaoPagina.tsx");

// B-13 (10/10/2026): no celular (375 px) o valor do Inicio quebrava no meio ("…276,8 / 5") e o titulo da medicao
// virava "Es…". O jsdom nao mede layout: aqui so' a presenca das regras; a medida foi conferida com Playwright.
function blocoMedia(css: string, largura: number): string {
  const i = css.indexOf(`@media (max-width: ${largura}px)`);
  if (i < 0) return "";
  let nivel = 0;
  for (let j = css.indexOf("{", i); j < css.length; j++) {
    if (css[j] === "{") nivel++;
    else if (css[j] === "}" && --nivel === 0) return css.slice(i, j + 1);
  }
  return "";
}

describe("celular", () => {
  it("Início: o valor grande não quebra e a fonte acompanha a largura abaixo de 420 px", () => {
    const bloco = blocoMedia(inicioCss, 420);
    expect(bloco).toMatch(/\.ini-numero__valor\s*\{[^}]*white-space:\s*nowrap/);
    expect(bloco).toMatch(/\.ini-numero__valor\s*\{[^}]*font-size:\s*clamp\(/);
  });

  it("Medição: abaixo de 600 px a meta desce para baixo do título", () => {
    // pagina redesenhada (#152): titulo e meta num bloco, "Mais acoes" ao lado; no celular desce tudo para uma coluna
    expect(medicaoPagina).toContain('className="med-cabeca"');
    expect(medicaoPagina).toContain('className="med-meta"');
    const bloco = blocoMedia(ler("etapas.css"), 767);
    expect(bloco).toMatch(/\.med-cabeca\s*\{[^}]*flex-direction:\s*column/);
  });

  it("Topo (issue #13): a meta cede com reticências e o topo não alarga a página em 375 px", () => {
    expect(tokensCss).toMatch(/\.topbar__linha > \.topbar__meta\s*\{[^}]*min-width:\s*12ch;[^}]*white-space:\s*nowrap;[^}]*overflow:\s*hidden;[^}]*text-overflow:\s*ellipsis/);
    expect(tokensCss).toMatch(/\.topbar__trilha, \.topbar__linha\s*\{[^}]*min-width:\s*0/);
    expect(tokensCss).toMatch(/\.topbar__titulo\s*\{[^}]*min-width:\s*0[^}]*text-overflow:\s*ellipsis/);
    expect(tokensCss).toMatch(/\.topbar__resumo\s*\{[^}]*min-width:\s*0/);
    expect(tokensCss).toMatch(/\.topbar\s*\{[^}]*width:\s*100%/);
    // listas (Medições, Documentos, Obras): o topo é a barra de seção, cujo título cede com reticências
    expect(tokensCss).toMatch(/\.barra__titulo\s*\{[^}]*min-width:\s*0[^}]*text-overflow:\s*ellipsis[^}]*white-space:\s*nowrap/);
    expect(blocoMedia(tokensCss, 767)).toMatch(/\.abas\s*\{[^}]*overflow-x:\s*auto/);
    expect(blocoMedia(tokensCss, 767)).toMatch(/\.barra\s*\{[^}]*padding:\s*0 8px 0 16px/);
    // no celular o respiro lateral encolhe para 16 px
    expect(blocoMedia(tokensCss, 900)).toMatch(/\.topbar, \.pagina\s*\{[^}]*padding-left:\s*16px/);
  });
});
