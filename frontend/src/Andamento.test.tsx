import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import Andamento from "./Andamento";
import { andamento } from "./valores";

// Valores inventados: ritmo e necessário na mesma unidade (centavos por mês).
const texto = (c: HTMLElement) => (c.querySelector(".andamento__texto")?.textContent ?? "").replace(/\s/g, " ");
const classe = (c: HTMLElement) => c.querySelector(".andamento")?.className;
const largura = (c: HTMLElement) => (c.querySelector(".andamento__barra") as HTMLElement).style.width;

describe("Andamento (#805)", () => {
  afterEach(cleanup);

  it("a partir de 100% do necessário: Adiantada", () => {
    const { container } = render(<Andamento ritmo={115_000} necessario={100_000} />);
    expect(texto(container)).toBe("Adiantada · mede 115% do necessário");
    expect(classe(container)).toBe("andamento andamento--adiantada");
  });

  it("de 70% a 99%: Atenção", () => {
    const { container } = render(<Andamento ritmo={81_000} necessario={100_000} />);
    expect(texto(container)).toBe("Atenção · mede 81% do necessário");
    expect(classe(container)).toBe("andamento andamento--atencao");
  });

  it("abaixo de 70%: Devagar", () => {
    const { container } = render(<Andamento ritmo={27_000} necessario={100_000} />);
    expect(texto(container)).toBe("Devagar · mede 27% do necessário");
    expect(classe(container)).toBe("andamento andamento--devagar");
  });

  it("nos limites, 100% e 70% entram na faixa de cima; o percentual arredonda para baixo", () => {
    expect(andamento(100_000, 100_000)).toEqual({ leitura: "adiantada", pct: 100 });
    expect(andamento(99_999, 100_000)).toEqual({ leitura: "atencao", pct: 99 });      // 99,999% não vira "100%"
    expect(andamento(70_000, 100_000)).toEqual({ leitura: "atencao", pct: 70 });
    expect(andamento(69_999, 100_000)).toEqual({ leitura: "devagar", pct: 69 });
    expect(andamento(0, 100_000)).toEqual({ leitura: "devagar", pct: 0 });
  });

  it("a barra é o ritmo num trilho que vai até 130% do necessário, com o risco no necessário; é desenho, fora da leitura", () => {
    const { container } = render(<Andamento ritmo={65_000} necessario={100_000} />);
    expect(largura(container)).toBe("50%");
    expect((container.querySelector(".andamento__necessario") as HTMLElement).style.left).toMatch(/^76\.92/);
    expect(container.querySelector(".andamento__trilho")?.getAttribute("aria-hidden")).toBe("true");
    cleanup();
    // o ritmo além do trilho enche a barra, sem passar da caixa
    expect(largura(render(<Andamento ritmo={400_000} necessario={100_000} />).container)).toBe("100%");
  });

  it("sem necessário (nulo ou zero) ou sem ritmo, nada aparece", () => {
    for (const [ritmo, necessario] of [[100, null], [100, undefined], [100, 0], [100, -5], [null, 100], [undefined, 100], [-1, 100]] as const) {
      const { container } = render(<Andamento ritmo={ritmo} necessario={necessario} />);
      expect(container.innerHTML).toBe("");
      cleanup();
    }
  });
});
