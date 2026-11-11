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

  it("Início (#642, #659): na faixa do ciclo o valor inteiro cabe no próprio trecho de 1024 a 1920 px; em painel estreito, lista vertical", () => {
    // #659: a 1440 px o trecho de maior valor espremia os outros e o valor em reais vazava para o trecho vizinho. A
    // regra: o minimo de cada trecho e' o conteudo dele (o valor nao quebra), e a fonte do valor sai da largura do
    // painel de modo que cinco valores de 11 digitos caibam lado a lado. O jsdom nao mede layout: aqui a conta, com a
    // largura de "R$ 100.000.000,00" em Lexend 700 medida no Chrome.
    const EM_MEDIDO = 9.81;
    const em = Number(/--ini-faixa-valor-em:\s*([\d.]+)/.exec(inicioCss)?.[1]);
    expect(em).toBeGreaterThanOrEqual(EM_MEDIDO);
    const vao = Number(/\.ini-faixa\s*\{[^}]*gap:\s*(\d+)px/.exec(inicioCss)?.[1]);
    const respiro = Number(/\.ini-faixa__etapa\s*\{[^}]*padding:\s*\d+px (\d+)px/.exec(inicioCss)?.[1]);
    const fonte = /\.ini-faixa__valor\s*\{[^}]*font-size:\s*clamp\((\d+)px, calc\(\(100cqi - (\d+)px\) \/ \(5 \* var\(--ini-faixa-valor-em\)\)\), (\d+)px\)/.exec(inicioCss);
    const [minima, folga, maxima] = [Number(fonte?.[1]), Number(fonte?.[2]), Number(fonte?.[3])];
    expect(folga).toBe(5 * 2 * respiro + 4 * vao);            // o que nao e' valor: respiros dos cinco trechos e vaos
    expect(inicioCss).toMatch(/\.ini-faixa__valor\s*\{[^}]*white-space:\s*nowrap/);
    expect(ler("Inicio.tsx")).toContain("minmax(min-content, ");
    // com o menu lateral aberto (240), o respiro da pagina (2 x 32) e o do painel (2 x 16)
    const painel = (largura: number) => largura - Number(/--trilho-largo:\s*(\d+)px/.exec(tokensCss)?.[1]) - 2 * 32 - 2 * 16;
    const cinco = (f: number) => 5 * (em * f + 2 * respiro) + 4 * vao;
    for (const largura of [1024, 1280, 1440, 1920]) {
      const f = Math.min(maxima, Math.max(minima, (painel(largura) - folga) / (5 * em)));
      expect(cinco(f), `${largura} px`).toBeLessThanOrEqual(painel(largura));     // cabe: sem corte, sem vazar, sem rolagem
    }
    // abaixo do que os cinco trechos pedem na fonte minima, uma coluna so'; a 1024 px a faixa continua deitada
    const corte = Number(/@container \(max-width:\s*(\d+)px\)/.exec(inicioCss)?.[1]);
    expect(corte).toBe(cinco(minima) - 1);
    expect(painel(1024)).toBeGreaterThan(corte);
    expect(inicioCss).toMatch(/\.ini-ciclo\s*\{[^}]*container-type:\s*inline-size[^}]*padding:\s*16px/);
    const bloco = inicioCss.slice(inicioCss.indexOf("@container"));
    expect(bloco).toMatch(/\.ini-faixa\s*\{\s*grid-template-columns:\s*minmax\(0, 1fr\)/);
  });

  it("Início (#659): a matriz cabe na largura do painel e, em painel estreito, o nome da obra sobe para a própria linha", () => {
    // 12 colunas que encolhem (minmax(0, 1fr)) ao lado do nome: nenhuma largura fixa empurra a pagina
    expect(inicioCss).toMatch(/\.ini-matriz\s*\{[^}]*container-type:\s*inline-size/);
    expect(inicioCss).toMatch(/\.ini-matriz__linha\s*\{[^}]*grid-template-columns:\s*minmax\(0, \d+px\) repeat\(12, minmax\(0, 1fr\)\)/);
    expect(inicioCss).toMatch(/\.ini-matriz__obra\s*\{[^}]*min-width:\s*0[^}]*overflow-wrap:\s*anywhere/);
    const bloco = inicioCss.slice(inicioCss.indexOf(".ini-matriz__cor--atrasado"));
    expect(bloco).toMatch(/@container \(max-width:\s*\d+px\)\s*\{\s*\.ini-matriz__linha\s*\{\s*grid-template-columns:\s*repeat\(12, minmax\(0, 1fr\)\)/);
    expect(bloco).toMatch(/\.ini-matriz__obra\s*\{\s*grid-column:\s*1 \/ -1/);
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
