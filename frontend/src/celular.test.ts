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

  it("Início (#642): a faixa do ciclo cabe a 1024 px e vira lista vertical em painel estreito", () => {
    // a 1024 px com o menu lateral aberto (240) e o respiro da pagina (2 x 32) e do painel (2 x 16) sobram 688 px
    const util = 1024 - Number(/--trilho-largo:\s*(\d+)px/.exec(tokensCss)?.[1]) - 2 * 32 - 2 * 16;
    const minimo = Number(/--ini-faixa-min:\s*(\d+)px/.exec(inicioCss)?.[1]);
    const vao = Number(/\.ini-faixa\s*\{[^}]*gap:\s*(\d+)px/.exec(inicioCss)?.[1]);
    const corte = Number(/@container \(max-width:\s*(\d+)px\)/.exec(inicioCss)?.[1]);
    const cinco = 5 * minimo + 4 * vao;
    expect(cinco).toBeLessThanOrEqual(util);        // a faixa inteira cabe: sem rolagem horizontal
    expect(corte).toBe(cinco - 1);                  // abaixo do que os cinco trechos pedem, uma coluna so'
    expect(inicioCss).toMatch(/\.ini-ciclo\s*\{[^}]*container-type:\s*inline-size[^}]*padding:\s*16px/);
    const bloco = inicioCss.slice(inicioCss.indexOf("@container"));
    expect(bloco).toMatch(/\.ini-faixa\s*\{\s*grid-template-columns:\s*minmax\(0, 1fr\)/);
  });

  it("Medição: abaixo de 600 px a meta desce para baixo do título", () => {
    // pagina da obra em medicao (#508): obra, meta e o valor grande num cabecalho, valor e "Mais acoes" ao lado; no
    // celular desce tudo para uma coluna
    expect(medicaoPagina).toContain('className="med-topo"');
    expect(medicaoPagina).toContain('className="med-meta"');
    const bloco = blocoMedia(ler("passos.css"), 767);
    expect(bloco).toMatch(/\.med-topo\s*\{[^}]*flex-direction:\s*column/);
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
