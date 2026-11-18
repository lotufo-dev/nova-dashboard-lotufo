/// <reference types="node" />
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import MarcaEtapa from "./MarcaEtapa";
import { ROTULO_DA_ETAPA, type Etapa } from "./valores";

const tokens = readFileSync(join(process.cwd(), "src", "tokens.css"), "utf8");
const regra = (seletor: string) => new RegExp(`(?:^|\\n)${seletor.replace(/[.]/g, "\\.")}\\s*\\{([^}]*)\\}`).exec(tokens)?.[1] ?? "";
const ETAPAS = Object.keys(ROTULO_DA_ETAPA) as Etapa[];

describe("MarcaEtapa (#805)", () => {
  afterEach(cleanup);

  it("a marca da etapa ao lado do nome dela; a marca é desenho, o rótulo diz a etapa", () => {
    const { container } = render(<MarcaEtapa etapa="protocolado" />);
    expect(container.textContent).toBe("Protocolado");
    const marca = container.querySelector(".marca-etapa__cor");
    expect(marca?.className).toBe("marca-etapa__cor marca-etapa__cor--protocolado");
    expect(marca?.getAttribute("aria-hidden")).toBe("true");
  });

  it("a tela pode dar outro nome ao valor da etapa", () => {
    const { container } = render(<MarcaEtapa etapa="boletim">Aprovado</MarcaEtapa>);
    expect(container.textContent).toBe("Aprovado");
    expect(container.querySelector(".marca-etapa__cor--boletim")).not.toBeNull();
  });

  it("cada etapa tem a regra do tom dela em tokens.css, pelos tons da Início", () => {
    expect(ETAPAS).toEqual(["em_analise", "boletim", "nota", "protocolado", "recebido", "em_aberto", "atrasado"]);
    const tom: Record<Etapa, string> = {
      em_analise: "--etapa-analise", boletim: "--etapa-boletim", nota: "--etapa-nota", protocolado: "--etapa-protocolado",
      recebido: "--etapa-recebido", em_aberto: "--etapa-em-aberto", atrasado: "--etapa-atrasado",
    };
    for (const e of ETAPAS) expect(regra(`.marca-etapa__cor--${e}`), e).toContain(`background: var(${tom[e]})`);
    // a análise é clara e leva contorno; o em aberto não é etapa do ciclo e tem outra forma
    expect(regra(".marca-etapa__cor--em_analise")).toContain("var(--etapa-analise-borda)");
    expect(regra(".marca-etapa__cor--em_aberto")).toContain("clip-path");
    expect(tokens).toMatch(/--etapa-em-aberto:\s*var\(--situacao-breve-texto\)/);
  });

  it("as famílias de valor não trazem cor nova: os tons delas apontam para os das situações e os neutros", () => {
    const valores = [...tokens.matchAll(/\n\s*(--valor-[\w-]+):\s*([^;]+);/g)].map(m => [m[1], m[2].trim()]);
    expect(valores.length).toBe(11);
    for (const [nome, valor] of valores) expect(valor, nome).toMatch(/^var\(--(situacao|cor)-[\w-]+\)$/);
    // e a cor da marca não entra em nenhuma regra das quatro peças
    const pecas = tokens.slice(tokens.indexOf("/* FAMILIAS DE VALOR"), tokens.indexOf("/* EM ABERTO A' PARTE"));
    for (const peca of [".variacao", ".diferenca", ".andamento", ".marca-etapa"]) expect(pecas).toContain(`\n${peca}`);
    expect(pecas).not.toContain("--cor-marca");
  });
});
