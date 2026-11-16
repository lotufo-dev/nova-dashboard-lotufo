/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

// #720: botao, campo, link, tabela e painel sao as pecas da fundacao, escritas uma vez em tokens.css sobre o proprio
// elemento. O jsdom nao aplica CSS: aqui as regras de cada peca e de cada estado (foco, desabilitado, erro).
const ler = (nome: string) => readFileSync(join(process.cwd(), "src", nome), "utf8");
const tokensCss = ler("tokens.css");
// tudo depois dos blocos de variaveis: as regras das pecas
const regras = tokensCss.slice(tokensCss.lastIndexOf("\n:root {")).replace(/^[^}]*\}/, "");
const regra = (seletor: string) =>
  new RegExp(`(?:^|\\n)${seletor.replace(/[.[\]()"=*+:-]/g, "\\$&")}\\s*\\{([^}]*)\\}`).exec(regras)?.[1] ?? "";

describe("botão", () => {
  afterEach(cleanup);

  it("o principal é tinta cheia e o secundário leva a borda grossa de tinta; o laranja não indica ação", () => {
    expect(regra(".btn--primario")).toMatch(/background:\s*var\(--cor-tinta\);\s*border-color:\s*var\(--cor-tinta\);\s*color:\s*var\(--cor-papel\)/);
    expect(regra("button, .btn")).toMatch(/border:\s*var\(--borda-painel\)/);
    expect(regra("button, .btn")).toMatch(/height:\s*var\(--alvo-minimo\)/);
    // o laranja da marca so' no icone do item ativo do menu (o simbolo o usa no proprio SVG; o foco do menu tem a variavel dele)
    const comMarca = [...regras.matchAll(/([^{}]+)\{[^}]*var\(--cor-marca\)[^}]*\}/g)].map(m => m[1].trim());
    expect(comMarca).toEqual(['.menu__item[aria-current="page"] .menu__icone']);
    for (const f of ["index.css", "passos.css", "medicoes.css", "notas.css", "documentos.css", "inicio.css"])
      expect(ler(f), f).not.toContain("--cor-marca");
  });

  it("desabilitado: sai a tinta, fica o papel escuro com o texto apagado, também no principal e no destrutivo", () => {
    render(<>
      <button type="button" className="btn btn--primario" disabled>Enviar ao faturamento</button>
      <button type="button" className="btn">Cancelar</button>
    </>);
    expect((screen.getByRole("button", { name: "Enviar ao faturamento" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Cancelar" }) as HTMLButtonElement).disabled).toBe(false);
    const apagado = /background:\s*var\(--cor-papel-escuro\);\s*border-color:\s*var\(--cor-papel-escuro\)/;
    expect(regra(":where(button, .btn):disabled")).toMatch(apagado);
    expect(regra("button:disabled, .btn:disabled")).toMatch(/color:\s*var\(--cor-texto-terciario\);\s*cursor:\s*not-allowed/);
    expect(regra(".btn--primario:disabled, .btn--destrutivo:disabled")).toMatch(apagado);
    expect(regra(".btn--primario:disabled, .btn--destrutivo:disabled")).toMatch(/color:\s*var\(--cor-texto-terciario\)/);
    // o passar o mouse nao reacende o botao desligado
    expect(regras).toMatch(/\.btn--primario:hover:not\(:disabled\)/);
    expect(regras).not.toMatch(/\.btn--primario:hover\s*\{/);
  });
});

describe("campo, foco e link", () => {
  it("campo: borda fina de controle na altura do alvo mínimo, com os estados de erro e desabilitado", () => {
    expect(regra("input, select, textarea")).toMatch(/height:\s*var\(--alvo-minimo\)/);
    expect(regra("input, select, textarea")).toMatch(/border:\s*var\(--borda-campo\)/);
    expect(regra('input[aria-invalid="true"], select[aria-invalid="true"], textarea[aria-invalid="true"]')).toMatch(/border:\s*var\(--borda-erro\)/);
    expect(regra(":where(input, select, textarea):disabled")).toMatch(/background:\s*var\(--cor-papel-sombreado\)[^}]*cursor:\s*not-allowed/);
  });

  it("foco: o mesmo contorno de tinta em link, botão e campo; dentro do menu escuro, o da marca", () => {
    const foco = regra(":where(a, button, input, select, textarea, summary, [tabindex]):focus-visible");
    expect(foco).toMatch(/outline:\s*var\(--largura-foco\) solid var\(--cor-foco\)/);
    expect(foco).toMatch(/outline-offset:\s*var\(--afastamento-foco\)/);
    expect(regra(".menu :focus-visible")).toMatch(/outline:\s*var\(--largura-foco\) solid var\(--cor-menu-foco\)/);
  });

  it("link: a cor do texto em volta, sublinhado; o link de componente (.link) é a mesma peça", () => {
    expect(regra("a")).toMatch(/color:\s*inherit;\s*text-underline-offset:\s*var\(--afastamento-sublinhado\)/);
    expect(regra("a")).not.toMatch(/text-decoration:\s*none/);
    expect(regra("a:hover")).toMatch(/text-decoration-thickness:\s*var\(--borda-grossa\)/);
    const link = /(?:^|\n)\.link\s*\{([^}]*)\}/.exec(ler("index.css"))?.[1] ?? "";
    expect(link).toMatch(/text-decoration:\s*underline/);
  });
});

describe("tabela, painel e variáveis", () => {
  it("tabela: cabeçalho sobre a régua de tinta, linhas separadas por fio, sem zebra", () => {
    expect(regra(".tabela thead th")).toMatch(/border-bottom:\s*var\(--regua-secao\)/);
    expect(regra(".tabela tbody td")).toMatch(/border-bottom:\s*var\(--borda-linha\)/);
    expect(regra(".tabela tfoot td, .tabela tfoot th")).toMatch(/border-top:\s*var\(--regua-secao\)/);
    expect(regras).not.toMatch(/tr\.par\b/);
  });

  it("painel: borda grossa de tinta e sombra dura; o título fica dentro, sem régua", () => {
    expect(regra(".cartao")).toMatch(/border:\s*var\(--borda-painel\)/);
    expect(regra(".cartao")).toMatch(/box-shadow:\s*var\(--sombra-painel\)/);
    expect(regra(".cartao__cabeca")).not.toMatch(/border/);
  });

  it("o filtro escolhido é o mais forte (tinta cheia), e o selo dentro de um título mantém a letra do texto", () => {
    const escolhido = regra('.cart-farol-btn[aria-pressed="true"], .cart-farol-btn[aria-pressed="true"]:hover:not(:disabled)');
    expect(escolhido).toMatch(/background:\s*var\(--cor-tinta\);\s*border-color:\s*var\(--cor-tinta\);\s*color:\s*var\(--cor-papel\)/);
    for (const peca of [".selo", ".contador"]) {
      expect(regra(peca), peca).toMatch(/font-family:\s*var\(--fonte-texto\);\s*font-stretch:\s*var\(--largura-texto\);\s*text-transform:\s*none;\s*letter-spacing:\s*normal/);
    }
  });

  it("as sobras da etapa anterior saíram: misturas de contorno, medidas do trilho e a largura antiga da página", () => {
    for (const nome of ["--acao-forte", "--acao-linha", "--atencao-linha", "--ok-linha", "--trilho", "--conteudo"])
      expect(tokensCss, nome).not.toMatch(new RegExp(`${nome}\\b`));
    expect(tokensCss).not.toMatch(/color-mix\([^)]*situacao/);
    // o menu aberto tem a medida da fundacao; o recolhido e' derivada desta etapa
    expect(tokensCss).toMatch(/--largura-menu:\s*232px/);
    expect(tokensCss).toMatch(/--largura-menu-recolhido:\s*64px/);
    expect(regra(".pagina")).toMatch(/max-width:\s*var\(--pagina-largura-max\)/);
  });
});
