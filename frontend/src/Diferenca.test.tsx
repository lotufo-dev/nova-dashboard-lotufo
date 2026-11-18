import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import Diferenca from "./Diferenca";
import { diferenca } from "./valores";

// Valores inventados, em centavos. O limite (5 por mil = 0,5%) vem do servidor; aqui é passado como ele o manda.
const POR_MIL = 5;
const texto = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s/g, " ");
const partes = (c: HTMLElement) => [...c.querySelectorAll(".diferenca__parte")].map(texto);
const tom = (c: HTMLElement) => c.querySelector(".diferenca")?.className;

describe("Diferenca (#805)", () => {
  afterEach(cleanup);

  it("igual: o sinal de igual e a frase, no tom do bom", () => {
    const { container } = render(<Diferenca valor={150_000_000} base={150_000_000} nomeBase="pedido" limitePorMil={POR_MIL} />);
    expect(partes(container)).toEqual(["= igual ao pedido"]);
    expect(tom(container)).toBe("diferenca diferenca--igual");
    expect(container.querySelector("[aria-hidden]")?.textContent).toBe("= ");
  });

  it("abaixo, até 0,5% da base: a diferença em reais e em percentual, no tom da atenção", () => {
    const { container } = render(<Diferenca valor={155_688_000} base={156_000_000} nomeBase="pedido" limitePorMil={POR_MIL} />);
    expect(partes(container)).toEqual(["− R$ 3.120,00", "(−0,2%)"]);
    expect(tom(container)).toBe("diferenca diferenca--leve");
    expect(texto(container.querySelector(".sr-only"))).toBe("R$ 3.120,00 abaixo do pedido, 0,2%");
  });

  it("acima de 0,5% da base: o tom do crítico", () => {
    const { container } = render(<Diferenca valor={179_250_000} base={220_480_000} nomeBase="pedido" limitePorMil={POR_MIL} />);
    expect(partes(container)).toEqual(["− R$ 412.300,00", "(−18,7%)"]);
    expect(tom(container)).toBe("diferenca diferenca--ruim");
  });

  it("o limite é o do aviso: exatamente 0,5% ainda é pequena; um centavo a mais é crítica", () => {
    expect(diferenca(99_500, 100_000, POR_MIL)?.tom).toBe("leve");
    expect(diferenca(99_499, 100_000, POR_MIL)?.tom).toBe("ruim");
    // o limite vem de quem chama: com 10 por mil, 0,8% é pequena
    expect(diferenca(99_200, 100_000, 10)?.tom).toBe("leve");
  });

  it("acima da base: sinal de mais, e o mesmo limite pelo tamanho da diferença", () => {
    const { container } = render(<Diferenca valor={101_000} base={100_000} nomeBase="pedido" limitePorMil={POR_MIL} />);
    expect(partes(container)).toEqual(["+ R$ 10,00", "(+1,0%)"]);
    expect(tom(container)).toBe("diferenca diferenca--ruim");
    expect(texto(container.querySelector(".sr-only"))).toBe("R$ 10,00 acima do pedido, 1,0%");
  });

  it("a diferença que arredonda para zero não vira 0,0%", () => {
    const { container } = render(<Diferenca valor={99_999_999} base={100_000_000} nomeBase="pedido" limitePorMil={POR_MIL} />);
    expect(partes(container)).toEqual(["− R$ 0,01", "(< 0,1%)"]);
    expect(texto(container.querySelector(".sr-only"))).toBe("R$ 0,01 abaixo do pedido, menos de 0,1%");
  });

  it("sem base (nula, zero ou negativa) ou sem valor, nada aparece", () => {
    for (const [valor, base] of [[100, null], [100, undefined], [100, 0], [100, -1], [null, 100], [undefined, 100]] as const) {
      const { container } = render(<Diferenca valor={valor} base={base} nomeBase="pedido" limitePorMil={POR_MIL} />);
      expect(container.innerHTML).toBe("");
      cleanup();
    }
  });
});
