import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import EmAbertoAParte from "./EmAbertoAParte";

// docs/adr/0006 (decisão do dono de 17/11/2026): o a receber de competência anterior e o sem atualização do RM ficam
// numa linha própria, fora do total. Valores sintéticos.
describe("EmAbertoAParte", () => {
  afterEach(cleanup);

  it("mostra uma linha para cada parte que tem valor, com o ano e a data vindos do servidor", () => {
    render(<EmAbertoAParte anoInicial="2025" anterior={159_906_581} semAtualizacao={19_939_743} desde="2026-09-25" />);
    const bloco = screen.getByLabelText("Em aberto fora do total");
    expect(within(bloco).getByText("Em aberto de competências anteriores a 2025").nextElementSibling?.textContent?.replace(/\u00a0/g, " ")).toBe("R$ 1.599.065,81");
    expect(within(bloco).getByText("Sem atualização do RM desde 25/09/2026").nextElementSibling?.textContent?.replace(/\u00a0/g, " ")).toBe("R$ 199.397,43");
  });

  it("parte sem valor não vira linha; sem data, o rótulo fica sem ela", () => {
    render(<EmAbertoAParte anoInicial="2025" anterior={0} semAtualizacao={10_001} />);
    expect(screen.queryByText(/competências anteriores/)).toBeNull();
    expect(screen.getByText("Sem atualização do RM").nextElementSibling?.textContent?.replace(/\u00a0/g, " ")).toBe("R$ 100,01");
  });

  it("sem nada à parte (ou sem o total liberado), não aparece", () => {
    const { container } = render(<EmAbertoAParte anoInicial="2025" anterior={0} semAtualizacao={null} />);
    expect(container.innerHTML).toBe("");
  });
});
