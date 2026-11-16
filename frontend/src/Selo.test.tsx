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

  it("nenhuma tela guarda o selo de três níveis, o contorno do nível Ação nem a pílula de situação", () => {
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
    const neutro = screen.getByLabelText("14 avisos");
    expect(neutro.className).toBe("contador");
    expect(neutro.querySelector(".glifo")).toBeNull();
    const critico = screen.getByLabelText("5 vencidos");
    expect(critico.className).toBe("contador contador--critico");
    expect(critico.querySelector(".glifo--critico")).not.toBeNull();
    expect(critico.textContent).toBe("5");
  });
});
