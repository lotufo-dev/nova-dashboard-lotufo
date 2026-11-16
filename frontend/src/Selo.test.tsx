/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import Contador from "./Contador";
import Selo, { Glifo, SeloNivel } from "./Selo";
import { SITUACOES, situacaoDoNivel } from "./situacao";

// #720: um sistema so' de situacao. O selo, o contador e a legenda usam as mesmas quatro situacoes, cada uma com a
// sua forma (o glifo), e nenhuma tela guarda o selo antigo de tres niveis nem a pilula a' parte.
const SRC = join(process.cwd(), "src");
const tokensCss = readFileSync(join(SRC, "tokens.css"), "utf8");

describe("Selo: as quatro situações", () => {
  afterEach(cleanup);

  it.each(SITUACOES)("%s: a classe da situação, o glifo dela antes do rótulo e o texto", situacao => {
    render(<Selo situacao={situacao}>há 12 dias</Selo>);
    const selo = screen.getByText("há 12 dias").closest(".selo")!;
    expect(selo.className).toBe(`selo selo--${situacao}`);
    const glifo = selo.querySelector(".glifo")!;
    expect(glifo.className).toBe(`glifo glifo--${situacao}`);
    expect(glifo.getAttribute("aria-hidden")).toBe("true");      // a forma e' decorativa: o rotulo diz a situacao
    expect(selo.firstElementChild).toBe(glifo);
    expect(selo.textContent).toBe("há 12 dias");
  });

  it("cada situação tem cor e forma próprias em tokens.css", () => {
    for (const s of SITUACOES) {
      expect(tokensCss).toMatch(new RegExp(`\\.glifo--${s}\\s*\\{\\s*background-image:\\s*var\\(--situacao-${s}-forma\\)`));
      expect(tokensCss).toMatch(new RegExp(`\\.selo--${s}\\s*\\{\\s*background:\\s*var\\(--situacao-${s}-fundo\\);\\s*color:\\s*var\\(--situacao-${s}-texto\\)`));
      expect(tokensCss).toMatch(new RegExp(`\\.contador--${s}\\s*\\{\\s*background:\\s*var\\(--situacao-${s}-fundo\\)`));
    }
    const formas = SITUACOES.map(s => new RegExp(`--situacao-${s}-forma:\\s*(url\\([^)]*\\))`).exec(tokensCss)?.[1]);
    expect(new Set(formas).size).toBe(4);                          // quatro desenhos diferentes
    expect(formas.every(Boolean)).toBe(true);
  });

  it("sem situação o selo é neutro e não leva glifo", () => {
    render(<Selo title="lida do PDF">digitada</Selo>);
    const selo = screen.getByText("digitada").closest(".selo")!;
    expect(selo.className).toBe("selo");
    expect(selo.querySelector(".glifo")).toBeNull();
    expect(selo.getAttribute("title")).toBe("lida do PDF");
  });

  it("o nível das pendências e o vocabulário antigo caem nas quatro situações", () => {
    render(<><SeloNivel nivel="critico" /><SeloNivel nivel="atencao" /><SeloNivel nivel="neutro" /></>);
    expect(screen.getByText("Crítico").closest(".selo")!.className).toContain("selo--critico");
    expect(screen.getByText("Atenção").closest(".selo")!.className).toContain("selo--breve");
    expect(screen.getByText("Passo").closest(".selo")!.className).toBe("selo");
    expect(["ok", "atencao", "acao", "andamento", "neutro", "normal", "", null].map(situacaoDoNivel))
      .toEqual(["feito", "breve", "critico", "andamento", undefined, undefined, undefined, undefined]);
  });

  it("o glifo solto (legenda, lista) é a mesma peça", () => {
    const { container } = render(<Glifo situacao="breve" />);
    expect(container.innerHTML).toBe('<span class="glifo glifo--breve" aria-hidden="true"></span>');
  });

  // So' as classes GLOBAIS removidas. Os pontos proprios de tela (documentos, SIGA, abas de Medicoes) seguem com as
  // classes de tres niveis de cada tela e ficam para a etapa de cada uma: este teste nao os cobre.
  it("as classes globais antigas do selo, do ponto e da pílula não voltam", () => {
    const velho = /selo--(?:ok|atencao|acao|forte)\b|selo__ponto|pilula-info|aviso__ponto/;
    const restos = readdirSync(SRC)
      .filter(f => /\.(?:tsx?|css)$/.test(f) && !/\.test\.tsx?$/.test(f))
      .filter(f => velho.test(readFileSync(join(SRC, f), "utf8")));
    expect(restos).toEqual([]);
  });
});

describe("Contador", () => {
  afterEach(cleanup);

  it("neutro sem glifo; com situação, o glifo dela e o rótulo para o leitor de tela", () => {
    render(<><Contador rotulo="14 avisos">14</Contador><Contador situacao="critico" rotulo="5 vencidos">5</Contador></>);
    const neutro = screen.getByText("14 avisos").closest(".contador")!;
    expect(neutro.className).toBe("contador");
    expect(neutro.querySelector(".glifo")).toBeNull();
    const critico = screen.getByText("5 vencidos").closest(".contador")!;
    expect(critico.className).toBe("contador contador--critico");
    expect(critico.querySelector(".glifo--critico")).not.toBeNull();
    expect(critico.querySelector("[aria-hidden='true']:not(.glifo)")!.textContent).toBe("5");
  });

  // #721: `aria-label` num <span> sem papel o leitor de tela costuma ignorar. O rotulo vai como texto so' de leitor
  // de tela e o numero desenhado sai da leitura, para nao ser dito duas vezes ("14 14 avisos").
  it("o rótulo é texto só de leitor de tela, sem aria-label no span; o número desenhado fica fora da leitura", () => {
    render(<Contador situacao="breve" rotulo="4 avisos">4</Contador>);
    const rotulo = screen.getByText("4 avisos");
    expect(rotulo.className).toBe("sr-only");
    const contador = rotulo.closest(".contador")!;
    expect(contador.getAttribute("aria-label")).toBeNull();
    expect(screen.queryByLabelText("4 avisos")).toBeNull();
    expect([...contador.children].map(c => [c.textContent, c.getAttribute("aria-hidden")])).toEqual(
      [["", "true"], ["4", "true"], ["4 avisos", null]]);
  });

  it("sem rótulo o número é o próprio texto do contador", () => {
    const { container } = render(<Contador situacao="critico">5</Contador>);
    const contador = container.querySelector(".contador")!;
    expect(contador.textContent).toBe("5");
    expect(contador.querySelector(".sr-only")).toBeNull();
  });
});
