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

  it("usa a peça de situação (#720): cada item traz o glifo da situação dele, o mesmo do selo", () => {
    render(<LegendaCor />);
    const itens = within(screen.getByRole("list", { name: "Legenda das cores" })).getAllByRole("listitem");
    expect(itens.map(i => i.querySelector(".glifo")?.className)).toEqual(
      ["glifo glifo--feito", "glifo glifo--andamento", "glifo glifo--breve", "glifo glifo--critico"]);
    for (const i of itens) expect(i.querySelector(".glifo")!.getAttribute("aria-hidden")).toBe("true");
  });

  it("a tela com nomes próprios para as situações troca só as palavras", () => {
    render(<LegendaCor itens={[{ situacao: "feito", texto: "em dia" }, { situacao: "critico", texto: "vencida" }]} />);
    const itens = screen.getAllByRole("listitem");
    expect(itens.map(i => i.textContent)).toEqual(["em dia", "vencida"]);
    expect(itens[1].querySelector(".glifo--critico")).not.toBeNull();
  });
});
