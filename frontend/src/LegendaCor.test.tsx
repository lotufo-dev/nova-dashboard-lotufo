import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import LegendaCor from "./LegendaCor";

describe("LegendaCor", () => {
  afterEach(cleanup);

  it("mostra as quatro situações na ordem da regra de cor", () => {
    render(<LegendaCor />);
    const itens = within(screen.getByRole("list", { name: "Legenda das cores" })).getAllByRole("listitem");
    expect(itens.map(i => i.textContent)).toEqual(["feito", "em andamento", "vence em breve", "crítico"]);
  });
});
