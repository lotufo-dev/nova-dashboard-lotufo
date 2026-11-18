import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import Diferenca from "./Diferenca";
import { diferenca } from "./valores";

// Valores inventados, em centavos. O corte (abaixo), o acima e o limite (5 por mil = 0,5%) vem do servidor; aqui são
// passados como ele os manda.
const POR_MIL = 5;
const texto = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s/g, " ");
const partes = (c: HTMLElement) => [...c.querySelectorAll(".diferenca__parte")].map(texto);
const tom = (c: HTMLElement) => c.querySelector(".diferenca")?.className;

describe("Diferenca (#805)", () => {
  afterEach(cleanup);

  it("igual (sem corte e sem acima): o sinal de igual e a frase, no tom do bom", () => {
    const { container } = render(<Diferenca abaixo={0} acima={0} base={150_000_000} nomeBase="pedido" limitePorMil={POR_MIL} />);
    expect(partes(container)).toEqual(["= igual ao pedido"]);
    expect(tom(container)).toBe("diferenca diferenca--igual");
    expect(container.querySelector("[aria-hidden]")?.textContent).toBe("= ");
  });

  it("abaixo, até 0,5% da base: o corte em reais e em percentual, no tom da atenção", () => {
    const { container } = render(<Diferenca abaixo={312_000} base={156_000_000} nomeBase="pedido" limitePorMil={POR_MIL} />);
    expect(partes(container)).toEqual(["\u2212 R$ 3.120,00", "(\u22120,2%)"]);
    expect(tom(container)).toBe("diferenca diferenca--leve");
    expect(texto(container.querySelector(".sr-only"))).toBe("R$ 3.120,00 abaixo do pedido, 0,2%");
  });

  it("abaixo, acima de 0,5% da base: o tom do crítico", () => {
    const { container } = render(<Diferenca abaixo={41_230_000} base={220_480_000} nomeBase="pedido" limitePorMil={POR_MIL} />);
    expect(partes(container)).toEqual(["\u2212 R$ 412.300,00", "(\u221218,7%)"]);
    expect(tom(container)).toBe("diferenca diferenca--ruim");
  });

  it("o limite é o do aviso: exatamente 0,5% ainda é pequena; um centavo a mais é crítica", () => {
    expect(diferenca(500, 0, 100_000, POR_MIL)?.tom).toBe("leve");
    expect(diferenca(501, 0, 100_000, POR_MIL)?.tom).toBe("ruim");
    // o limite vem de quem chama: com 10 por mil, 0,8% é pequena
    expect(diferenca(800, 0, 100_000, 10)?.tom).toBe("leve");
  });

  it("acima da base: diz o sentido por escrito, sempre no tom da atenção, nunca crítico, e sem percentual", () => {
    // o pedido gravado dez vezes menor: seria "+900%"; a etiqueta só diz quanto e para que lado
    const { container } = render(<Diferenca abaixo={0} acima={54_000_000} base={6_000_000} nomeBase="pedido" limitePorMil={POR_MIL} />);
    expect(partes(container)).toEqual(["+ R$ 540.000,00", "acima do pedido"]);
    expect(tom(container)).toBe("diferenca diferenca--leve");
    expect(container.textContent).not.toContain("%");
    expect(diferenca(0, 1, 100_000, POR_MIL)).toEqual({ sentido: "acima", tom: "leve", centavos: 1, percentual: "" });
  });

  it("no nível que soma (mês, obra, ano) só o corte entra: sem `acima`, o que não tem corte é igual", () => {
    const { container } = render(<Diferenca abaixo={0} base={6_000_000} nomeBase="pedido" limitePorMil={POR_MIL} />);
    expect(partes(container)).toEqual(["= igual ao pedido"]);
    // e o corte vale mesmo quando outra linha ficou acima: o acima não desconta
    expect(diferenca(10_000, 550_000, 2_000_000, POR_MIL)).toEqual({ sentido: "abaixo", tom: "leve", centavos: 10_000, percentual: "0,5%" });
  });

  it("o corte que arredonda para zero não vira 0,0%", () => {
    const { container } = render(<Diferenca abaixo={6} base={100_000_000} nomeBase="pedido" limitePorMil={POR_MIL} />);
    expect(partes(container)).toEqual(["\u2212 R$ 0,06", "(< 0,1%)"]);
    expect(texto(container.querySelector(".sr-only"))).toBe("R$ 0,06 abaixo do pedido, menos de 0,1%");
  });

  it("sem base (nula, zero ou negativa) ou sem o corte do servidor, nada aparece", () => {
    for (const [abaixo, base] of [[100, null], [100, undefined], [100, 0], [100, -1], [null, 100], [undefined, 100]] as const) {
      const { container } = render(<Diferenca abaixo={abaixo} acima={50} base={base} nomeBase="pedido" limitePorMil={POR_MIL} />);
      expect(container.innerHTML).toBe("");
      cleanup();
    }
  });
});
