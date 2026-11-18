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

  // #659: a 1440 px o valor em reais vazava para o trecho vizinho da faixa do ciclo. #721: o ciclo e a previsao viraram
  // linhas de rotulo a' esquerda e valor a' direita, em painel de meia largura (ou da largura toda, no celular). A
  // regra agora: o valor nunca quebra nem sai do painel, e ate' dezenas de milhoes (10 digitos) cabe ao lado do rotulo
  // mais largo sem empurra-lo para a segunda linha (a 390 px "No próximo mês" quebrava). A letra do valor sai da
  // largura do painel. O jsdom nao mede layout: aqui a conta, com as larguras medidas no Chrome em Archivo (largura
  // 92%, peso 620, algarismos tabulares).
  const EM_10 = 7.68, EM_11 = 8.23;              // "R$ 12.480.615,32" e "R$ 800.000.000,00", em vezes a letra
  const token = (nome: string) => /^([\d.]+)(rem|px)$/.exec(new RegExp(`${nome}:\\s*([\\d.]+(?:rem|px))`).exec(tokensCss)?.[1] ?? "");
  // variavel de tokens.css em px (1rem = 16 px)
  const px = (nome?: string) => { const m = token(nome ?? ""); return m ? Number(m[1]) * (m[2] === "rem" ? 16 : 1) : NaN; };
  /** A largura por dentro do painel do ciclo e da previsao numa janela: tira o menu (recolhido no celular), as margens
   *  da pagina, a segunda coluna (de 680 px de pagina em diante) e o respiro e a borda do painel. */
  function porDentro(janela: number): number {
    const menu = janela < 768 ? px("--largura-menu-recolhido") : px("--largura-menu");
    const pagina = Math.min(px("--pagina-largura-max"), janela - menu) - 2 * (janela <= 900 ? 16 : 32);
    const painel = pagina >= 680 ? (pagina - px("--espaco-entre-colunas")) / 2 : pagina;
    return painel - 2 * (janela <= 640 ? px("--espaco-m") : px("--espaco-g")) - 2 * px("--borda-grossa");
  }
  const limitar = (min: number, v: number, max: number) => Math.min(max, Math.max(min, v));

  it("Início (#642, #659, #721): no ciclo o valor inteiro cabe ao lado do rótulo, de 375 a 1920 px, sem quebrar nem vazar", () => {
    const ROTULO = 128.05;                       // "Recebido no mês", o rotulo mais largo, a 16 px no peso forte
    const em = Number(/--ini-etapa-valor-em:\s*([\d.]+)/.exec(inicioCss)?.[1]);
    const rotulo = 16 * Number(/--ini-etapa-rotulo:\s*([\d.]+)rem/.exec(inicioCss)?.[1]);
    expect(em).toBeGreaterThanOrEqual(EM_10);
    expect(rotulo).toBeGreaterThanOrEqual(ROTULO);
    // as pontas do clamp sao passos da escala de tokens.css (#719)
    const fonte = /\.ini-etapa__valor\s*\{[^}]*font-size:\s*clamp\(var\((--[\w-]+)\), calc\(\(100cqi - var\(--ini-etapa-rotulo\) - var\((--[\w-]+)\)\) \/ var\(--ini-etapa-valor-em\)\), var\((--[\w-]+)\)\)/.exec(inicioCss);
    const [minima, vao, maxima] = [px(fonte?.[1]), px(fonte?.[2]), px(fonte?.[3])];
    expect([minima, vao, maxima].every(Number.isFinite)).toBe(true);
    expect(inicioCss).toMatch(/\.ini-etapa__valor\s*\{[^}]*white-space:\s*nowrap/);
    // o rotulo cede (minmax(0, 1fr)); o valor fica do tamanho dele (auto), com o mesmo vao da conta entre os dois
    expect(inicioCss).toMatch(/\.ini-etapa\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto;[^}]*gap:\s*var\(--espaco-mini\) var\(--espaco-m\)/);
    expect(fonte?.[2]).toBe("--espaco-m");
    // o painel e' o container da conta (100cqi e' a largura por dentro dele)
    expect(inicioCss).toMatch(/\.ini-painel\s*\{[^}]*container-type:\s*inline-size/);
    for (const janela of [375, 390, 1024, 1280, 1440, 1920]) {
      const w = porDentro(janela), f = limitar(minima, (w - rotulo - vao) / em, maxima);
      expect(ROTULO + vao + EM_10 * f, `${janela} px, 10 dígitos`).toBeLessThanOrEqual(w);     // rotulo e valor numa linha
      expect(EM_11 * f, `${janela} px, 11 dígitos`).toBeLessThanOrEqual(w);                    // o valor nunca sai do painel
    }
    // de 1024 px em diante a letra do valor e' a da tela aprovada (o passo "valor menor" da escala)
    for (const janela of [1024, 1440]) expect(limitar(minima, (porDentro(janela) - rotulo - vao) / em, maxima)).toBe(px("--texto-valor-menor"));
    // uma etapa por linha em qualquer largura: nao ha' mais a faixa deitada de cinco trechos
    expect(inicioCss).toMatch(/\.ini-etapas\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/);
    expect(inicioCss).not.toContain("ini-faixa");
  });

  it("Início (#721): na previsão \"No próximo mês\" não quebra a 390 px e o valor cabe ao lado dele até 1920 px", () => {
    const ROTULO = 117.61;                       // "No próximo mês", o rotulo mais largo, a 16 px no peso medio
    const em = Number(/--ini-previsao-valor-em:\s*([\d.]+)/.exec(inicioCss)?.[1]);
    const rotulo = 16 * Number(/--ini-previsao-rotulo:\s*([\d.]+)rem/.exec(inicioCss)?.[1]);
    expect(em).toBeGreaterThanOrEqual(EM_10);
    expect(rotulo).toBeGreaterThanOrEqual(ROTULO);
    const fonte = /\.ini-previsao__valor\s*\{[^}]*font-size:\s*clamp\(var\((--[\w-]+)\), calc\(\(100cqi - var\((--[\w-]+)\) - var\(--ini-previsao-rotulo\) - 3 \* var\((--[\w-]+)\)\) \/ var\(--ini-previsao-valor-em\)\), var\((--[\w-]+)\)\)/.exec(inicioCss);
    const [minima, chave, vao, maxima] = [px(fonte?.[1]), px(fonte?.[2]), px(fonte?.[3]), px(fonte?.[4])];
    expect([minima, chave, vao, maxima].every(Number.isFinite)).toBe(true);
    expect(inicioCss).toMatch(/\.ini-previsao__valor\s*\{[^}]*white-space:\s*nowrap/);
    // chave, rotulo (que cede) e valor; os tres vaos da conta: dois entre as colunas e o respiro a' esquerda do valor
    expect(inicioCss).toMatch(/\.ini-previsao__linha\s*\{[^}]*grid-template-columns:\s*auto minmax\(0, 1fr\) auto;[^}]*column-gap:\s*var\(--espaco-pp\)/);
    expect(inicioCss).toMatch(/\.ini-previsao__valor\s*\{[^}]*padding-left:\s*var\(--espaco-pp\)/);
    expect([fonte?.[2], fonte?.[3]]).toEqual(["--tamanho-chave", "--espaco-pp"]);
    for (const janela of [390, 1024, 1280, 1440, 1920]) {
      const w = porDentro(janela), f = limitar(minima, (w - chave - rotulo - 3 * vao) / em, maxima);
      expect(chave + ROTULO + 3 * vao + EM_10 * f, `${janela} px, 10 dígitos`).toBeLessThanOrEqual(w);
      expect(EM_11 * f, `${janela} px, 11 dígitos`).toBeLessThanOrEqual(w);
    }
    // a 1440 px a letra do valor e' a da tela aprovada (o passo "valor" da escala)
    expect(limitar(minima, (porDentro(1440) - chave - rotulo - 3 * vao) / em, maxima)).toBe(px("--texto-valor"));
  });

  it("Início (#721): recebido em 12 meses deita as barras em painel estreito e a célula atrasada da matriz leva a marca", () => {
    const bloco = inicioCss.slice(inicioCss.indexOf(".ini-rec__rotulo"));
    expect(bloco).toMatch(/@container \(max-width:\s*\d+px\)\s*\{\s*\.ini-rec\s*\{\s*grid-template-columns:\s*minmax\(0, 1fr\)/);
    expect(inicioCss).toMatch(/\.ini-rec__coluna\s*\{[^}]*background:\s*var\(--cor-barra-recebido\)/);          // barras de tinta
    expect(inicioCss).toMatch(/\.ini-matriz__celula--atrasado::after\s*\{[^}]*content:\s*var\(--etapa-atrasado-marca\)/);
    expect(tokensCss).toMatch(/--etapa-atrasado-marca:\s*"!"/);
  });

  it("Início (#659): a matriz cabe na largura do painel e, em painel estreito, o nome da obra sobe para a própria linha", () => {
    // 12 colunas que encolhem (minmax(0, 1fr)) ao lado do nome, que tambem encolhe: nenhuma largura fixa empurra a
    // pagina. #721: o container e' o painel, e a largura do nome vem de tokens.css
    expect(inicioCss).toMatch(/\.ini-painel\s*\{[^}]*container-type:\s*inline-size/);
    expect(inicioCss).toMatch(/\.ini-matriz__linha\s*\{[^}]*grid-template-columns:\s*minmax\(0, var\(--largura-nome-obra\)\) repeat\(12, minmax\(0, 1fr\)\)/);
    expect(inicioCss).toMatch(/\.ini-matriz__obra\s*\{[^}]*min-width:\s*0[^}]*overflow-wrap:\s*anywhere/);
    const bloco = inicioCss.slice(inicioCss.indexOf(".ini-matriz__celula--atrasado {"));
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
    expect(tokensCss).toMatch(/\.topbar\s*\{[^}]*width:\s*100%/);
    // a barra do topo leva o caminho da página (#814): ele corre como texto, o que não cabe desce para a linha de
    // baixo e a barra cresce em vez de alargar a página; o nome mais largo que a barra quebra por dentro
    expect(tokensCss).toMatch(/\.topo\s*\{[^}]*min-height:\s*var\(--altura-topo\)/);
    expect(tokensCss).toMatch(/\.caminho\s*\{[^}]*min-width:\s*0/);
    expect(tokensCss).toMatch(/\.caminho ol\s*\{[^}]*display:\s*block/);
    expect(tokensCss).toMatch(/\.caminho__trecho > a,[^{]*\{[^}]*display:\s*inline-block;\s*max-width:\s*100%;\s*white-space:\s*normal;\s*overflow-wrap:\s*anywhere/);
    expect(tokensCss).not.toMatch(/\.caminho[^{]*\{[^}]*text-overflow/);
    expect(blocoMedia(tokensCss, 767)).toMatch(/\.abas\s*\{[^}]*overflow-x:\s*auto/);
    expect(blocoMedia(tokensCss, 767)).toMatch(/\.topo\s*\{[^}]*padding:\s*var\(--espaco-pp\) var\(--espaco-pp\) var\(--espaco-pp\) var\(--espaco-m\)/);
    // no celular os trechos de antes vão numa linha pequena e o título desce para a de baixo
    expect(blocoMedia(tokensCss, 767)).toMatch(/\.caminho__trecho \+ \.caminho__trecho--titulo::before\s*\{[^}]*content:\s*"\\A"/);
    // no celular o respiro lateral encolhe para 16 px
    expect(blocoMedia(tokensCss, 900)).toMatch(/\.topbar, \.pagina\s*\{[^}]*padding-left:\s*16px/);
  });
});
