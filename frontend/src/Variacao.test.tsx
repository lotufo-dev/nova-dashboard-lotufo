import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { variacao } from "./valores";
import Variacao from "./Variacao";

// Valores inventados, em centavos.
const partes = (c: HTMLElement) => [...c.querySelectorAll(".variacao__parte")].map(p => p.textContent);
const lido = (c: HTMLElement) => c.querySelector(".sr-only")?.textContent;
const tom = (c: HTMLElement) => c.querySelector(".variacao")?.className;

describe("Variacao (#805)", () => {
  afterEach(cleanup);

  it("subiu: seta para cima, sinal de mais, uma casa com vírgula e a referência escrita; no que é melhor maior, é bom", () => {
    const { container } = render(<Variacao atual={112_400} referencia={100_000} rotulo="set" porExtenso="setembro" />);
    expect(partes(container)).toEqual(["▲ +12,4%", "× set"]);
    expect(tom(container)).toBe("variacao variacao--bom");
    expect(lido(container)).toBe("subiu 12,4% em relação a setembro");
  });

  it("caiu: seta para baixo e o sinal de menos (não o hífen); no que é melhor maior, é ruim", () => {
    const { container } = render(<Variacao atual={91_900} referencia={100_000} rotulo="out/25" porExtenso="outubro de 2025" />);
    expect(partes(container)).toEqual(["▼ −8,1%", "× out/25"]);
    expect(tom(container)).toBe("variacao variacao--ruim");
    expect(lido(container)).toBe("caiu 8,1% em relação a outubro de 2025");
  });

  it("menor é melhor (o em aberto): cair é bom e subir é ruim; a seta continua dizendo a direção", () => {
    const caiu = render(<Variacao atual={80_000} referencia={100_000} rotulo="out" porExtenso="outubro" sentido="menor-e-melhor" />);
    expect(partes(caiu.container)[0]).toBe("▼ −20,0%");
    expect(tom(caiu.container)).toBe("variacao variacao--bom");
    cleanup();
    const subiu = render(<Variacao atual={130_000} referencia={100_000} rotulo="out" porExtenso="outubro" sentido="menor-e-melhor" />);
    expect(partes(subiu.container)[0]).toBe("▲ +30,0%");
    expect(tom(subiu.container)).toBe("variacao variacao--ruim");
  });

  it("estável é a variação de até 2%, para cima ou para baixo, o limite incluído: ponto, sem percentual, tom neutro", () => {
    for (const atual of [100_000, 102_000, 98_000, 100_900]) {
      const { container } = render(<Variacao atual={atual} referencia={100_000} rotulo="set" porExtenso="setembro" />);
      expect(partes(container), String(atual)).toEqual(["● estável", "× set"]);
      expect(tom(container)).toBe("variacao variacao--estavel");
      expect(lido(container)).toBe("estável em relação a setembro");
      cleanup();
    }
    // um centavo além do limite já é variação
    expect(variacao(102_001, 100_000)).toEqual({ direcao: "subiu", percentual: "2,0%" });
    expect(variacao(97_999, 100_000)).toEqual({ direcao: "caiu", percentual: "2,0%" });
  });

  it("sem referência (nula, zero ou negativa) ou sem valor, nada aparece", () => {
    for (const [atual, referencia] of [[100, null], [100, undefined], [100, 0], [100, -50], [null, 100], [undefined, 100]] as const) {
      const { container } = render(<Variacao atual={atual} referencia={referencia} rotulo="set" porExtenso="setembro" />);
      expect(container.innerHTML).toBe("");
      cleanup();
    }
  });

  it("o valor que zerou caiu 100%; milhar no percentual segue o pt-BR", () => {
    expect(variacao(0, 100_000)).toEqual({ direcao: "caiu", percentual: "100,0%" });
    expect(variacao(1_334_500, 100_000)).toEqual({ direcao: "subiu", percentual: "1.234,5%" });
  });

  it("a seta e o número ficam fora da leitura; quem lê a tela ouve a frase", () => {
    const { container } = render(<Variacao atual={112_400} referencia={100_000} rotulo="set" porExtenso="setembro" />);
    expect([...container.querySelectorAll(".variacao__parte")].every(p => p.getAttribute("aria-hidden") === "true")).toBe(true);
    expect(container.querySelector(".sr-only")?.getAttribute("aria-hidden")).toBeNull();
  });
});
